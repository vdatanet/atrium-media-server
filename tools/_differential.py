#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The differential comparison engine: two decoded responses in, a tuple of Differences out.

Pure. It opens no socket, reads no file and consults no clock, so that the mutation proofs of
010 spec section 6 run in the default CI job, where there is no Jellyfin and must not be one, and
so that the thing deciding whether the server is right can itself be tested. A comparison that
cannot be unit-tested is the one thing this feature must not ship (010 plan section 3).

**Rows are compared by position, and that is a consequence rather than a preference.** 010 OQ-1
killed every join key the wire could have offered - `Path` is absent from every default list row,
0 of 1000, and `(Type, Name)` is 976 distinct of 1000
`[probe: tools/probe_differential_join.py, Jellyfin 10.11.11, 2026-09-01]` - so position is what is
left, which promotes the ordering into the contract under test. An engine that knew only about
*values* would report a reordered thousand-row page as a thousand value differences and say nothing
about the one thing that actually differs. Hence five classes and not three: keys, types, LENGTH,
ORDER, VALUE (010 plan §6.2).

Standard library only, on the Python 3.9 floor, like everything under tools/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

#: An empty mapping that a frozen dataclass can hold as a default.
_NOTHING: Mapping[str, str] = MappingProxyType({})

#: How many moved positions an ORDER finding spells out before it stops. The permutation of a
#: thousand-row page is not something a report reader consumes; the count is.
_PERMUTATION_SAMPLE = 8

#: The pointer a status difference is filed under. Not a JSON Pointer - those are "" or start with
#: "/" - and not a header, so it cannot collide with either.
STATUS_POINTER = "status"

#: The array-index wildcard inside an allowlist pointer, RFC 6901's own spelling for "an element of
#: this array". Every field row of spec §3.3 - `Id`, `DateCreated`, `ChildCount` - lives inside a
#: row of a list envelope, so an entry that could only name a literal index could not excuse any of
#: them. See `Rules.excuse`.
INDEX_WILDCARD = "-"


class Class(Enum):
    """Ordered by severity: the report ranks by this (010 AC-5).

    Missing keys first because they are the entire point of the exercise - the only class of
    defect this project structurally cannot find any other way, since L1 and L2 check only what
    somebody already knew to check (spec §3.2).
    """

    MISSING_KEY = 1  # the reference has it, Atrium does not
    EXTRA_KEY = 2  # Atrium has it, the reference does not
    TYPE = 3
    LENGTH = 4  # an array whose lengths differ; suppresses the positional comparison of its rows
    ORDER = 5  # the same multiset of rows, in a different order
    VALUE = 6


@dataclass(frozen=True)
class Response:
    """What one case got back from one server, already decoded.

    `body` is the parsed JSON, or None where the body is bytes. `raw` is kept because three of the
    named comparisons of spec §3.10 parse or byte-compare instead of diffing - a progressive
    re-encode's header frame, a subtitle playlist's decimal point, the manifest's track name. This
    engine never looks at it: spec §6 declines to byte-compare produced media, so a difference in
    `raw` is a named comparison's finding and never a sweep's.
    """

    status: int
    headers: Mapping[str, str] = _NOTHING
    body: Any = None
    raw: bytes = b""


@dataclass(frozen=True)
class Difference:
    """One finding, under a pointer that can be pasted into the report and read against either body.

    `note` carries what the class needs and the pointer cannot: for `ORDER` the permutation, for
    `LENGTH` both counts, for `TYPE` both type names.
    """

    klass: Class
    pointer: str
    atrium: Any = None
    reference: Any = None
    note: str = ""


@dataclass(frozen=True)
class Rules:
    """Everything the comparison consults, resolved for one (endpoint, case, identity).

    Three kinds, as 010 plan §6.3 sets them out. T2 landed the first and T4 the other two.

    | Kind | Not compared | Still compared |
    |---|---|---|
    | `field` | The value | The key's presence and its JSON type |
    | `drawn` | Every row's values | The envelope, the row count, every row's key set and types |
    | `unordered` | The order | Everything, as a multiset of rows |

    Each maps a **pointer** to the one-sentence reason the report prints. A pointer may carry the
    `-` wildcard in place of an array index, and it matches a whole subtree: an entry on
    `/Items/-/ImageTags` excuses every value under it.
    """

    excused_fields: Mapping[str, str] = _NOTHING
    drawn_arrays: Mapping[str, str] = _NOTHING
    unordered_arrays: Mapping[str, str] = _NOTHING

    def excuse(self, pointer: str) -> str | None:
        """The reason `pointer` is excused as a field, or None.

        An entry applies when it matches the pointer or prefixes it, segment by segment - never by
        string prefix, or `/Item` would silently excuse `/Items`.
        """
        return _match(self.excused_fields, pointer)

    def excuse_header(self, name: str) -> str | None:
        """The reason the header `name` may differ in value, or None.

        Separate from `excuse` because a `header:` pointer is not a JSON Pointer and must never be
        matched as one, and because HTTP header names are case-insensitive on both sides of the
        entry - an allowlist row written `header:Date` has to excuse a `date` the other server sent.
        """
        wanted = "header:" + name.lower()
        for entry, reason in self.excused_fields.items():
            if entry.lower() == wanted:
                return reason
        return None

    def drawn(self, pointer: str) -> str | None:
        """The reason the array at `pointer` is a draw rather than a reading, or None."""
        return _match(self.drawn_arrays, pointer, whole=True)

    def unordered(self, pointer: str) -> str | None:
        """The reason the array at `pointer` has no total ordering, or None."""
        return _match(self.unordered_arrays, pointer, whole=True)


#: The rule set of a comparison in which nothing is excused. `Rules` is frozen, so one shared
#: instance is a safe default argument.
NO_RULES = Rules()


# --------------------------------------------------------------------------------------------
# Pointers
# --------------------------------------------------------------------------------------------


def _segments(pointer: str) -> list[str]:
    """RFC 6901 in the two escapes it actually defines. `""` is the root and has no segments."""
    if not pointer:
        return []
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]


def _join(pointer: str, segment: str) -> str:
    return pointer + "/" + str(segment).replace("~", "~0").replace("/", "~1")


def _generalise(pointer: str) -> str:
    """Replace every array index in `pointer` with the wildcard.

    This is what makes a fingerprint position-independent: the mask a row is reduced under must
    not depend on where the row currently sits, or reordering an array would change the very
    values the ordering comparison is trying to hold still.
    """
    out = ""
    for segment in _segments(pointer):
        out = _join(out, INDEX_WILDCARD if segment.isdigit() else segment)
    return out


def _matches(entry: str, pointer: str, whole: bool = False) -> bool:
    if entry and not entry.startswith("/"):
        # Not a JSON Pointer, so it addresses nothing in a body. Without this a `header:` entry
        # parses to **no** segments, prefixes every pointer there is, and excuses the whole body.
        return False
    entry_segments, pointer_segments = _segments(entry), _segments(pointer)
    if whole:
        if len(entry_segments) != len(pointer_segments):
            return False
    elif len(entry_segments) > len(pointer_segments):
        return False
    for position, wanted in enumerate(entry_segments):
        got = pointer_segments[position]
        if wanted == INDEX_WILDCARD and got.isdigit():
            continue
        if wanted != got:
            return False
    return True


def _match(entries: Mapping[str, str], pointer: str, whole: bool = False) -> str | None:
    """The reason of the first entry that covers `pointer`.

    A `field` entry covers a subtree, so it may be a proper prefix. An array entry names the array
    itself and nothing under it - `whole` - or an excused envelope would excuse every row in it.
    """
    for entry, reason in entries.items():
        if _matches(entry, pointer, whole=whole):
            return reason
    return None


# --------------------------------------------------------------------------------------------
# Types
# --------------------------------------------------------------------------------------------


def json_type(value: Any) -> str:
    """The name this engine compares types by.

    Two things a reader will want to have checked. **Booleans are separated before integers**,
    because `bool` is a subclass of `int` in Python and an `isinstance` ladder in the obvious order
    reports `true` and `1` as the same type - on a surface where `IsFolder`, `SupportsTranscoding`
    and a dozen other flags are exactly the fields a decoder would break on. And **an integer is
    not a number**: JSON has one numeric type but Principle VIII says numeric type is part of the
    contract *and only visible in the serialised form*, which is where `0` and `0.0` differ.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# --------------------------------------------------------------------------------------------
# Fingerprints
# --------------------------------------------------------------------------------------------


def _masked(value: Any, rules: Rules, pointer: str) -> Any:
    """`value` with every excused field replaced by a marker naming its type.

    **The marker keeps the key present and keeps its type**, and that is the whole of it. Mask by
    deleting the key instead and a row where Atrium omits `Id` entirely fingerprints identically to
    the reference's row that carries it - so two arrays would compare equal and the missing key,
    the class the report ranks first, would never be reported at all.
    """
    reason = rules.excuse(pointer)
    if reason is not None:
        return ["<excused>", json_type(value)]
    if isinstance(value, dict):
        return {key: _masked(item, rules, _join(pointer, key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [
            _masked(item, rules, _join(pointer, str(index))) for index, item in enumerate(value)
        ]
    return value


def fingerprint(row: Any, rules: Rules, pointer: str) -> str:
    """A row reduced to one canonical string, under the same mask the value comparison uses.

    Canonical so that key order does not make two equal rows look different; masked so that two
    rows differing only by `Id` do not look like a reordering to the very mechanism that exists to
    excuse `Id` (010 plan §6.2). Derived, never stored.
    """
    return json.dumps(
        _masked(row, rules, pointer),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=repr,
    )


# --------------------------------------------------------------------------------------------
# The comparison
# --------------------------------------------------------------------------------------------


def compare(
    atrium: Response, reference: Response, rules: Rules = NO_RULES
) -> tuple[Difference, ...]:
    """Compare two decoded bodies. Total, and it never raises on a difference.

    Any two decoded bodies compare, including a list against an object, which is a `TYPE` at the
    root. A comparison that throws on the first surprise reports one finding per run.

    **A status difference is one finding and stops there.** 010 plan §7 files it as *"a `VALUE`
    difference on the status"*, singular, and it has to be: a `404`'s problem details against a
    `200`'s item body share almost no keys, so walking on would bury the one fact that explains
    every other finding under fifty that do not.
    """
    if atrium.status != reference.status:
        return (
            Difference(
                Class.VALUE,
                STATUS_POINTER,
                atrium.status,
                reference.status,
                note="the bodies were not compared: they answer different statuses",
            ),
        )
    findings: list[Difference] = []
    _walk("", atrium.body, reference.body, rules, findings)
    return tuple(findings)


def compare_headers(
    atrium: Response, reference: Response, rules: Rules = NO_RULES
) -> tuple[Difference, ...]:
    """Compare two header sets by name set and then by value, under `header:` pointers.

    Names are matched case-insensitively, because HTTP says they are and the two servers are
    different stacks: reporting `Content-Type` against `content-type` would be a finding about
    nothing on every response. Header *order* is not compared for the same reason.
    """
    ours = {name.lower(): value for name, value in atrium.headers.items()}
    theirs = {name.lower(): value for name, value in reference.headers.items()}
    findings: list[Difference] = []
    for name in sorted(set(theirs) - set(ours)):
        findings.append(Difference(Class.MISSING_KEY, "header:" + name, None, theirs[name]))
    for name in sorted(set(ours) - set(theirs)):
        findings.append(Difference(Class.EXTRA_KEY, "header:" + name, ours[name], None))
    for name in sorted(set(ours) & set(theirs)):
        pointer = "header:" + name
        if ours[name] == theirs[name]:
            continue
        if rules.excuse_header(name) is not None:
            continue
        findings.append(Difference(Class.VALUE, pointer, ours[name], theirs[name]))
    return tuple(findings)


def _walk(pointer: str, ours: Any, theirs: Any, rules: Rules, out: list[Difference]) -> None:
    excused = rules.excuse(pointer)
    our_type, their_type = json_type(ours), json_type(theirs)
    if our_type != their_type:
        note = our_type + " against " + their_type
        out.append(Difference(Class.TYPE, pointer, ours, theirs, note=note))
        return
    if excused is not None:
        # A `field` entry excuses the value and nothing else: the key's presence was compared by
        # the parent, and its type was compared two lines up.
        return
    if our_type == "object":
        _walk_object(pointer, ours, theirs, rules, out)
    elif our_type == "array":
        _walk_array(pointer, ours, theirs, rules, out)
    elif ours != theirs:
        out.append(Difference(Class.VALUE, pointer, ours, theirs))


def _walk_object(
    pointer: str,
    ours: Mapping[str, Any],
    theirs: Mapping[str, Any],
    rules: Rules,
    out: list[Difference],
) -> None:
    # An explicit `null` is a key that is present. The reference suppresses nulls globally and
    # sends `ChannelId: null` on every item anyway - 208 of 208
    # `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]` - so a key-set pass that
    # treated null as absent would report nothing on the one shape that proves it matters.
    for key in sorted(set(theirs) - set(ours)):
        out.append(Difference(Class.MISSING_KEY, _join(pointer, key), None, theirs[key]))
    for key in sorted(set(ours) - set(theirs)):
        out.append(Difference(Class.EXTRA_KEY, _join(pointer, key), ours[key], None))
    for key in sorted(set(ours) & set(theirs)):
        _walk(_join(pointer, key), ours[key], theirs[key], rules, out)


def _walk_array(
    pointer: str,
    ours: Sequence[Any],
    theirs: Sequence[Any],
    rules: Rules,
    out: list[Difference],
) -> None:
    """Three array kinds, and the length difference means something different in each.

    **A length difference never suppresses what the array's own kind still owes.** It suppresses
    the *positional* comparison, which is the thing that cascades - one inserted row at the top of
    a thousand-row page is a thousand value findings - and nothing else. Applied in the order
    010 plan §6.2 writes it, the guard would delete AC-17 on the only endpoint AC-17 exists for:
    `/Items/{itemId}/Similar` answers `limit + 4` rows on a movie seed where Atrium answers
    exactly `limit` (behaviours §3.24), so a `drawn` array whose length difference stopped the
    walk would never have its rows walked at all. T2's finding; this split is T4's answer to it.

    `drawn` outranks `unordered` where an entry of each covers the same array: a draw's rows have
    no comparable values, which is strictly more than having no comparable order.
    """
    if rules.drawn(pointer) is not None:
        _walk_drawn(pointer, ours, theirs, rules, out)
        return
    if rules.unordered(pointer) is not None:
        _walk_unordered(pointer, ours, theirs, rules, out)
        return
    if len(ours) != len(theirs):
        # The cascade guard. One inserted row at the top of a thousand-row page is a thousand
        # findings without it, and a report with a thousand findings is a report nobody reads.
        out.append(
            Difference(
                Class.LENGTH,
                pointer,
                len(ours),
                len(theirs),
                note=f"rows not compared by position: {len(ours)} against {len(theirs)}",
            )
        )
        return
    row_pointer = _join(_generalise(pointer), INDEX_WILDCARD)
    ours_printed = [fingerprint(row, rules, row_pointer) for row in ours]
    theirs_printed = [fingerprint(row, rules, row_pointer) for row in theirs]
    if ours_printed == theirs_printed:
        return
    if sorted(ours_printed) == sorted(theirs_printed):
        out.append(
            Difference(
                Class.ORDER,
                pointer,
                None,
                None,
                note=_permutation(ours_printed, theirs_printed),
            )
        )
        return
    for index, our_row in enumerate(ours):
        _walk(_join(pointer, str(index)), our_row, theirs[index], rules, out)


def _walk_drawn(
    pointer: str,
    ours: Sequence[Any],
    theirs: Sequence[Any],
    rules: Rules,
    out: list[Difference],
) -> None:
    """A `drawn` array: the envelope, the row count and every row's key set and types (AC-17).

    No row's value is compared, because there is nothing to compare it with - four identical
    requests to `/Items/{itemId}/Similar` returned 48 distinct items with **none** in common
    `[probe: tools/probe_similar_ranking.py, Jellyfin 10.11.11, 2026-09-01]`, so the two servers'
    row 0 is not the same item and never will be.

    **The shape walk is therefore position-free, and that is a correction rather than a
    convenience.** Rows are reduced to one map of *generalised pointer -> the JSON types seen
    there across every row*, and the two maps are compared. Walking row 0 against row 0 instead
    would report content as shape: a null property is absent everywhere by one setting on both
    servers (behaviours §1.7), so a row's key set depends on which item it holds - `ProductionYear`
    is simply absent from an item that has none - and a draw guarantees the two sides hold
    different items.

    **The row count is still a finding, and it is a known divergence rather than noise.** It
    differs on every run of that endpoint, permanently, and reporting it is the point: the count
    is the only quantity of a drawn array that L3 can still check, so excusing it would leave the
    endpoint with nothing measurable at all (T4's decision; behaviours §3.24, AC-17).
    """
    if len(ours) != len(theirs):
        out.append(
            Difference(
                Class.LENGTH,
                pointer,
                len(ours),
                len(theirs),
                note=(
                    f"rows compared for shape only, never by position: "
                    f"{len(ours)} against {len(theirs)}"
                ),
            )
        )
    if not ours or not theirs:
        # An empty array has no shape. Comparing one against a full one would report every key of
        # every row as missing, on an endpoint whose emptiness is a draw's outcome and not a shape.
        return
    row_pointer = _join(_generalise(pointer), INDEX_WILDCARD)
    our_shape = _shape(ours, rules, row_pointer)
    their_shape = _shape(theirs, rules, row_pointer)
    # One pass over both shapes, so that a difference at a node **prunes its own subtree**. That
    # is what `_walk` does with a `TYPE` and what `_walk_object` does with a missing key, and
    # without it a row that lost a whole `UserData` object would report one finding per property
    # inside it - the second cascade, arriving through the door the first one was shut on.
    reported: list[str] = []
    for at in sorted(set(our_shape) | set(their_shape)):
        if any(_covers(already, at) for already in reported):
            continue
        ours_types, theirs_types = our_shape.get(at), their_shape.get(at)
        if ours_types is None or theirs_types is None:
            if _is_element(at):
                # Presence is not comparable here, and neither is anything under it.
                reported.append(at)
                continue
            if ours_types is None:
                note = "no row of Atrium's carries it; the reference's carry " + _types(
                    theirs_types or frozenset()
                )
                out.append(Difference(Class.MISSING_KEY, at, None, None, note=note))
            else:
                note = "no row of the reference's carries it; Atrium's carry " + _types(ours_types)
                out.append(Difference(Class.EXTRA_KEY, at, None, None, note=note))
            reported.append(at)
        elif ours_types != theirs_types:
            note = _types(ours_types) + " against " + _types(theirs_types)
            out.append(Difference(Class.TYPE, at, None, None, note=note))
            reported.append(at)


def _covers(ancestor: str, pointer: str) -> bool:
    """True when `pointer` sits inside the subtree of `ancestor`, segment by segment."""
    return pointer.startswith(ancestor + "/")


def _is_element(pointer: str) -> bool:
    """True for a pointer addressing *an element of* a nested array, `…/-`.

    Presence is not comparable there: the pointer exists on a side only because some row held a
    non-empty array, and one item having three genres where another has none is content. Types
    under it are still compared, on the sides that have any element at all.
    """
    return pointer.endswith("/" + INDEX_WILDCARD)


def _types(names: frozenset[str]) -> str:
    return "|".join(sorted(names))


def _shape(rows: Sequence[Any], rules: Rules, row_pointer: str) -> dict[str, frozenset[str]]:
    """Every row reduced to *generalised pointer -> the set of JSON types seen there*."""
    seen: dict[str, set[str]] = {}
    for row in rows:
        _record(row_pointer, row, rules, seen)
    return {pointer: frozenset(names) for pointer, names in seen.items()}


def _record(pointer: str, value: Any, rules: Rules, seen: dict[str, set[str]]) -> None:
    seen.setdefault(pointer, set()).add(json_type(value))
    if rules.excuse(pointer) is not None:
        # An excused field's own type is compared and its subtree is not, which is exactly what
        # `_walk` does with one: `ImageTags` is a map of content hashes, and its keys are as
        # derived as its values.
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _record(_join(pointer, key), item, rules, seen)
    elif isinstance(value, (list, tuple)):
        child = _join(pointer, INDEX_WILDCARD)
        for item in value:
            _record(child, item, rules, seen)


def _walk_unordered(
    pointer: str,
    ours: Sequence[Any],
    theirs: Sequence[Any],
    rules: Rules,
    out: list[Difference],
) -> None:
    """An `unordered` array: everything, as a multiset of rows (AC-18).

    Equal multisets say **nothing at all** - not even an `ORDER` finding - because the ordering
    under comparison is one the reference does not have: it appends no further key after most
    orderings, so its ties are engine-resolved and paging its artist sorts loses and duplicates
    rows (behaviours §3.6). Reporting that as Atrium's difference would report Atrium doing what
    §3.6 says it does.

    **What plan §6.2 does not say is what happens when the multisets genuinely differ, and this
    is T4's answer: the rows that match are removed, and only the residue is compared.** The gap
    is not hypothetical - §3.6's paging *duplicates* rows as well as losing them, so a page can
    hold one row twice and another not at all **at the same length**, which is the one shape
    neither the `LENGTH` guard nor the `ORDER` class catches (plan §9's risk row claims they do,
    and T2 measured that they do not). Aligning the residue instead of the whole array turns that
    page from `2n` value findings into the one row that really differs. Which reference row a
    residue row is paired with is arbitrary, and it is *allowed* to be arbitrary here precisely
    because this array has no ordering to lose.
    """
    row_pointer = _join(_generalise(pointer), INDEX_WILDCARD)
    ours_printed = [fingerprint(row, rules, row_pointer) for row in ours]
    theirs_printed = [fingerprint(row, rules, row_pointer) for row in theirs]
    if sorted(ours_printed) == sorted(theirs_printed):
        return
    our_residue, their_residue = _residue(ours_printed, theirs_printed)
    if len(ours) != len(theirs):
        out.append(
            Difference(
                Class.LENGTH,
                pointer,
                len(ours),
                len(theirs),
                note=(
                    f"compared as a multiset: {len(our_residue)} of Atrium's rows matched none of "
                    f"the reference's, against {len(their_residue)} the other way"
                ),
            )
        )
    # No `zip`: its `strict=` is 3.10, and tools/ runs on the 3.9 floor (D-2). The pairs beyond
    # the shorter residue are the rows the LENGTH finding above has already counted.
    for position in range(min(len(our_residue), len(their_residue))):
        ours_at, theirs_at = our_residue[position], their_residue[position]
        _walk(_join(pointer, str(ours_at)), ours[ours_at], theirs[theirs_at], rules, out)


def _residue(
    ours_printed: Sequence[str], theirs_printed: Sequence[str]
) -> tuple[list[int], list[int]]:
    """The indices on each side that no row on the other side matches, multiplicities honoured.

    Honoured rather than collapsed for §3.6's reason: a page that lost one row and repeated
    another is not a page where both sides hold the same rows, and a set-based answer would say
    it was.
    """
    pool: dict[str, list[int]] = {}
    for index, printed in enumerate(theirs_printed):
        pool.setdefault(printed, []).append(index)
    matched: set[int] = set()
    ours_left: list[int] = []
    for index, printed in enumerate(ours_printed):
        bucket = pool.get(printed)
        if bucket:
            matched.add(bucket.pop(0))
        else:
            ours_left.append(index)
    theirs_left = [index for index in range(len(theirs_printed)) if index not in matched]
    return ours_left, theirs_left


def _permutation(ours: Sequence[str], theirs: Sequence[str]) -> str:
    """Where each of our rows sits in the reference's sequence.

    Multiplicities are honoured rather than collapsed, because the ordering defect this class
    exists to describe duplicates rows as well as moving them: paging the reference's artist sorts
    *"loses and duplicates rows"* (behaviours §3.6), and a set-based answer would call a page that
    lost one row and repeated another a pure reordering.
    """
    remaining: dict[str, list[int]] = {}
    for index, printed in enumerate(theirs):
        remaining.setdefault(printed, []).append(index)
    moves = []
    for index, printed in enumerate(ours):
        came_from = remaining[printed].pop(0)
        if came_from != index:
            moves.append((index, came_from))
    shown = ", ".join(f"{here}<-{there}" for here, there in moves[:_PERMUTATION_SAMPLE])
    if len(moves) > _PERMUTATION_SAMPLE:
        shown += ", ..."
    return (
        f"same {len(ours)} rows in a different order; "
        f"{len(moves)} moved (atrium<-reference): {shown}"
    )


# --------------------------------------------------------------------------------------------
# The report's ranking
# --------------------------------------------------------------------------------------------


def rank(differences: Sequence[Difference]) -> tuple[Difference, ...]:
    """Severity first, then pointer, so the report reads missing keys first (010 AC-5)."""
    return tuple(sorted(differences, key=lambda found: (found.klass.value, found.pointer)))


def counts(differences: Sequence[Difference]) -> dict[Class, int]:
    """One count per class, every class present, so a report never has to guess a zero."""
    tally = dict.fromkeys(Class, 0)
    for found in differences:
        tally[found.klass] += 1
    return tally
