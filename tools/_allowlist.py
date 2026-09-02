#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The three registers a differential run is measured against, read from the files that hold them.

The first is the allowlist — `docs/compatibility/allowlist.yaml` in, `Rules` mappings out. The
second is the named-comparison register, `docs/compatibility/named-comparisons.yaml`, which is the
twenty rows of 010 spec §3.10: the differences a sweep cannot raise, each with what a run must have
before the row is even askable. The third is `docs/compatibility/request-cases.yaml`, the requests
the sweep actually issues (AC-3), seeded L3-first. All three live here because 010 plan §3 puts the
registers behind one reader, and because a register nothing parses is prose — which is the
2026-09-01 audit's M1 finding, *"nothing reads it, so nothing fails when it drifts"*.

Pure, like the engine it feeds. It reads one file and consults no socket and no clock, so the
AC-6 proofs run in the default CI job where there is no Jellyfin and must not be one.

**The load is the gate, and it is the automated half of AC-6.** An entry excuses a difference, so
an entry with no reason behind it is how this feature silently deletes itself: the allowlist is
"the mechanism that can silently delete the feature's value" (010 plan §9). Every entry therefore
declares either the `behaviours.md` section that argues a difference one of the two servers
*chose*, or one of four declared derivation classes for a difference **neither** chose. An entry
naming neither, or naming a fifth class, raises rather than being skipped - a bad row that merely
excused nothing would be a bad row nobody noticed.

**Resolution is scoped, and that is the point of the file.** `resolve` matches an entry on the
endpoint, on the request case and on the pointer, never on a bare field name. `ChildCount` is the
case that decides it: the reference's number is a fresh random integer on a `/UserViews` row
`[probe: tools/probe_reference_determinism.py, Jellyfin 10.11.11, 2026-09-01]` and the same
property on a series, a season or a multi-disc album is a real computed subtree aggregate on both
servers - so a name-keyed row would excuse, on every container, exactly the value L2 exists to
check (behaviours §3.25, 010 plan §6.3).

The three mappings `resolve` returns are named for the three fields of `_differential.Rules`, so a
runner builds its rules with `Rules(**resolution.mappings())` and the two modules stay uncoupled:
`tools/` is a directory of standalone programs, not a package, and a private module that imported
a sibling would only work from one working directory.

Standard library only, on the Python 3.9 floor, like everything under tools/.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence, Tuple

DEFAULT_ALLOWLIST = Path("docs/compatibility/allowlist.yaml")
DEFAULT_NAMED_COMPARISONS = Path("docs/compatibility/named-comparisons.yaml")
DEFAULT_REQUEST_CASES = Path("docs/compatibility/request-cases.yaml")

#: The three kinds of entry, and what each stops comparing (010 plan §6.3):
#:
#: | Kind | Not compared | Still compared |
#: |---|---|---|
#: | `field` | The value | The key's presence and its JSON type |
#: | `drawn` | Every row's values | The envelope, the row count, every row's key set and types |
#: | `unordered` | The order | Everything, as a multiset of rows |
KINDS = ("field", "drawn", "unordered")

#: The four declared derivation classes, and no fifth. Each is a fact about how two separate
#: installations of separate software differ, and none of them can ever be the excuse for a value
#: one of the two servers decided - that owes a behaviours.md section instead (010 AC-6, D-3).
DERIVATION_CLASSES = (
    "derived-identifier",  # the two derive this identifier differently by design
    "wall-clock",  # the value is the moment something happened, and they happened apart
    "content-hash",  # a hash over inputs that are themselves derived differently
    "installation-path",  # the value names where this installation keeps its files
)

#: The other half of `because`: a behaviours.md section, which is where the argument lives.
_BEHAVIOURS = re.compile(r"^behaviours §\d+(?:\.\d+)+$")

_ENDPOINT = re.compile(r"^(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) /\S*$")

#: A request-case id from `request-cases.yaml`: lowercase words joined by hyphens.
_CASE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: The header pointer form. A `header:` entry is not a JSON Pointer and must never be matched as
#: one: parsed as a pointer it yields no segments, prefixes every pointer there is, and excuses
#: the whole body. `_differential.Rules` guards it on the other side; this refuses to let a
#: `drawn` or `unordered` entry carry one at all, since a header is not an array.
_HEADER_PREFIX = "header:"

#: The pointer a status difference is filed under, matching `_differential.STATUS_POINTER`.
_STATUS_POINTER = "status"

#: The same hand-written YAML subset `docs/compatibility/surface.yaml` uses, parsed with two
#: regexes so that `tools/` keeps its no-dependency rule.
_FIELD = re.compile(r"^\s{2,}(\w+):\s*(.+?)\s*$")

_REQUIRED = ("kind", "endpoint", "pointer", "case", "reason", "because", "since")

#: A row identifier in the named-comparison register: lowercase words joined by hyphens, the same
#: shape as a request-case id, because both are printed in a report and read by a human.
_ID = _CASE

#: What a named comparison may need before it is askable (010 plan §4.2). Two `identity:` values
#: rather than one, because the two seats are different accounts: the restricted reader of spec
#: §3.9, and one with a playback-processing permission denied (behaviours §2.21).
NEEDS = (
    "identity:restricted",
    "identity:playback-denied",
    "fixture",
    "rescan",
    "wait",
    "latency",
    "bytes",
    "twice",
)

#: The value both `behaviours` and `runner` take when there is nothing to name. On `behaviours` it
#: is a measurement: five of the twenty differences have no behaviours.md entry at all, because an
#: entry there records what the reference *does* and nobody has watched it do these. On `runner` it
#: is a state: the row is outstanding until the task that writes the callable lands.
NONE = "none"

#: A flow sequence in the hand-written subset: `[]`, or `[a, b]`. `surface.yaml`'s `consumers:`
#: is the same spelling, which is why it is the one used.
_LIST = re.compile(r"^\[(.*)\]$")

_NAMED_REQUIRED = (
    "id",
    "what",
    "why_the_sweep_misses_it",
    "needs",
    "behaviours",
    "written_at",
    "runner",
)

#: The register's half of the same field, and it is deliberately wider by one shape: a row may
#: cite a whole chapter, because four of the twenty are answered by a row of behaviours §5's
#: table and those rows have no anchors of their own. The allowlist's `because` stays narrow -
#: an entry that excused a difference by citing a whole chapter would be citing nothing.
_BEHAVIOURS_SECTION = re.compile(r"^behaviours §\d+(?:\.\d+)*$")

#: `written_at` names a document in *this* repository — one of the six "what this feature owes the
#: next ones" lists §3.10 collects, or the compatibility document that carries the question where
#: no list does. Never a path outside it (AGENTS.md: provenance names a version and a date, or a
#: file inside Jellyfin's own tree, and a local path is neither verifiable nor ours to publish).
_WRITTEN_AT = re.compile(r"^(?:specs|docs)/[\w./-]+\.md$")


#: The three seats a run may authenticate as, spelled as `differential.Role`'s values (plan §6.7).
#: A case names the ones it is meaningful for, and a run with one identity covers one (AC-14).
ROLES = ("administrator", "restricted", "playback-denied")

#: What a case may write where **only the running identity can supply the value**. Plan §6.1.1
#: says `userId` *"is not an anchor: it is the identity's own"* and gives no way to write that
#: down — and `POST /Users/AuthenticateByName` cannot be a case at all without one, since its body
#: is the seat's own credentials. These three are the whole vocabulary; anything else in angle
#: brackets fails the load, so a token nobody substitutes cannot reach a server as literal text.
#:
#: **Angle brackets and not braces**, which a path parameter uses: a body is JSON, and `{...}` in
#: a JSON body is an object. A brace-delimited token was written first and matched the device
#: profile's nested objects on the first load.
SUBSTITUTIONS = ("identity.username", "identity.password", "identity.user_id")

#: What an anchor's own name is spelled as when the value belongs in a **query or a body** rather
#: than in the path. Added by 010 T11, and it is what the four shapes T6 could not express needed:
#: an item id in a body (007's three reporting routes), an item id in a query (`ids` on the
#: playlist add, `entryIds` on the remove) and an entry id in a path parameter that no listing of
#: *items* fills. T6 wrote them with `needs: [fixture]` and no anchor at all rather than with a
#: placeholder, because a placeholder compares two `404`s and looks like coverage.
#:
#: The rule is one line: **`<anchor.p>` resolves to whatever the anchor named `p` resolves to**,
#: through the same three kinds and the same per-server resolution. Nothing new is resolvable and
#: nothing may carry an identifier, which is the property the anchor mechanism exists to keep.
ANCHOR_SUBSTITUTION_PREFIX = "anchor."

_SUBSTITUTION = re.compile(r"<([^<>]*)>")

_PATH_PARAMETER = re.compile(r"\{(\w+)\}")

#: The one path parameter that is never an anchor, for the reason plan §6.1.1 gives.
IDENTITY_PATH_PARAMETER = "userId"

_MEDIA_TYPE = re.compile(r"^[a-z]+/[a-z0-9.+-]+$")

#: **Three kinds, because plan §6.1.1's one kind fills a minority of the path parameters here.**
#:
#: - `p=listing:<METHOD> <path>#<case>@<position>` — the plan's anchor: the row at that position
#:   of that declared listing case, resolved against each server just before the case runs.
#: - `p=response:<METHOD> <path>#<case>@<pointer>` — a value an earlier case's *response* carried
#:   and no listing does: a created playlist's `Id`, a negotiated media source's `Id`.
#: - `p=literal:<value>` — a parameter that does not name an item at all. `{container}`,
#:   `{routeFormat}`, `{imageType}`, `{imageIndex}` and `{newIndex}` are the caller's own choice
#:   and the same string on both servers; a grammar that could not say so leaves five routes
#:   unaskable.
_ANCHOR = re.compile(
    r"^(?P<parameter>\w+)=(?P<kind>listing|response):"
    r"(?P<endpoint>(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [^#\s]+)"
    r"#(?P<case>[a-z0-9]+(?:-[a-z0-9]+)*)@(?P<at>\S+)$"
)

_LITERAL_ANCHOR = re.compile(r"^(?P<parameter>\w+)=literal:(?P<value>[^,\s]+)$")

_POSITION = re.compile(r"^\d+$")

_CASE_REQUIRED = (
    "id",
    "endpoint",
    "query",
    "body",
    "content_type",
    "anchors",
    "identities",
    "needs",
    "what_it_is_for",
)

#: `query` is the one field of the three registers whose **empty** value is its commonest one: the
#: AC-3 floor case is a bare request, and a bare request is a case with nothing in its query. So
#: presence is required and content is not, which is T5's *"an empty needs is a value"* met again
#: on a scalar rather than on a list.
_CASE_MAY_BE_EMPTY = ("query",)


class AllowlistError(Exception):
    """A row that cannot be trusted to excuse anything. Raised at load, never swallowed."""


@dataclass(frozen=True)
class Entry:
    """One excused thing, in the seven fields of 010 plan §4.1 and T3's seventh.

    `case` is the seventh, and it only ever narrows. Two rows of spec §3.3 are conditioned on the
    **request** rather than on the route - `TotalRecordCount` *"on by-name endpoints without a
    limit"*, and *"the rows of any listing ordered at random"* - and with six fields neither could
    be written at all without being wider than the prose it comes from: the first would excuse a
    real count difference on every by-name request that *does* carry a limit, and the second would
    excuse the rows of every listing on every request, which is the largest thing this harness
    compares. `resolve(endpoint, case, identity)` in plan §6.3 already takes the dimension; this is
    the column it reads. `"*"` is what an entry with no condition says, and an id no case declares
    matches nothing - so the failure direction is under-excusing.
    """

    kind: str
    endpoint: str
    pointer: str
    case: str
    reason: str
    because: str
    since: str

    @property
    def is_derivation(self) -> bool:
        """True when this entry excuses a difference **neither** server chose."""
        return self.because in DERIVATION_CLASSES

    @property
    def behaviours_section(self) -> str:
        """The behaviours.md section number this entry cites, or `""` for a derivation."""
        if self.is_derivation:
            return ""
        return self.because.split("§", 1)[1]


@dataclass(frozen=True)
class Resolution:
    """The entries that apply to one (endpoint, case), keyed the way the engine consults them."""

    excused_fields: Mapping[str, str]
    drawn_arrays: Mapping[str, str]
    unordered_arrays: Mapping[str, str]

    def mappings(self) -> Dict[str, Mapping[str, str]]:
        """The three, named for `_differential.Rules`' three fields: `Rules(**r.mappings())`."""
        return {
            "excused_fields": self.excused_fields,
            "drawn_arrays": self.drawn_arrays,
            "unordered_arrays": self.unordered_arrays,
        }


@dataclass(frozen=True)
class NamedComparison:
    """One row of 010 spec §3.10: a difference the sweep cannot raise, and what it needs.

    **`needs` is the field that earns the register** (010 plan §4.2). It is what lets a report say
    *"four outstanding, and three of them because no fixture instance was available"* rather than
    *"four outstanding"*, and it is what a run consults to decide whether a row is even askable
    before it counts it as a miss. Two rows carry an **empty** `needs`, and that is a real value:
    the last two of §3.10 are ordinary request cases, listed so a run counts them rather than
    triaging them twice.

    `behaviours` is `none` on **five** rows: five of the twenty differences have no behaviours.md
    entry at all — an entry there records what the reference *does*, and nobody has watched it do
    these. **Four more cite a whole chapter**, `behaviours §5`, because their answer is a row of
    that section's table, which has no anchor of its own, so `what` says which row.
    """

    id: str
    what: str
    why_the_sweep_misses_it: str
    needs: Tuple[str, ...]
    behaviours: str
    written_at: str
    runner: str

    @property
    def is_outstanding(self) -> bool:
        """True while no runner has been written for it. Every row is outstanding until T12."""
        return self.runner == NONE

    @property
    def behaviours_section(self) -> str:
        """The behaviours.md section this row cites, or `""` where none carries it."""
        if self.behaviours == NONE:
            return ""
        return self.behaviours.split("§", 1)[1]


def _scalar(raw: str) -> str:
    """One value of the hand-written subset, with **one matching pair** of quotes removed.

    It used to be `.strip().strip('"')`, which strips a quote off either end independently — so a
    value that merely *ends* in one lost it, and a single-quoted scalar kept both. Neither shape
    existed in the first two registers, and both exist in the third: a request body is JSON, whose
    own double quotes make a YAML single-quoted scalar the only spelling that survives round-trip
    through both this parser and a real YAML reader (`test_the_three_registers_are_valid_yaml`).
    Stripping a matched pair is what the two agree on.
    """
    value = raw.strip()
    for quote in ('"', "'"):
        if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
            return value[1:-1]
    return value


@dataclass(frozen=True)
class Anchor:
    """How one path parameter is filled, per server, immediately before the case runs.

    Never an identifier: the two servers derive those differently by design (behaviours §1.4), so
    a case that carried one would be comparing two different items (plan §6.1.1).
    """

    parameter: str
    kind: str  # "listing", "response" or "literal"
    endpoint: str  # empty for a literal
    case: str  # empty for a literal
    at: str  # a row position, a JSON Pointer into a response, or the literal value itself


@dataclass(frozen=True)
class RequestCase:
    """One request the sweep issues, in the fields of 010 plan §4.3 and the three T6 added.

    `content_type` is one of them, and it exists because two rows of the named-comparison register
    are *"here to be recognised, not discovered"* — ordinary request cases (plan §6.4) — and one
    of them is **a body with no content type**, which no combination of a query and a body can
    say. `needs` is the second, from T6's own statement: a case whose anchor wants a particular
    kind of item declares `fixture` and leaves the anchor unfilled, for T11 to fill. And
    `what_it_is_for` is the third: the sentence review reads when the file grows.

    `body` is the **raw** request body and is sent verbatim, which is what lets a malformed one
    exist at all: the register's `body-binding-dollar-message` row is a case whose body is not
    JSON, and a field parsed as JSON at load could not hold it.
    """

    id: str
    endpoint: str
    query: str
    body: str
    content_type: str
    anchors: Tuple[Anchor, ...]
    identities: Tuple[str, ...]
    needs: Tuple[str, ...]
    what_it_is_for: str

    @property
    def method(self) -> str:
        return self.endpoint.split(" ", 1)[0]

    @property
    def path(self) -> str:
        return self.endpoint.split(" ", 1)[1]

    @property
    def has_body(self) -> bool:
        return self.body != NONE

    def identities_for(self, roster: Sequence[str]) -> Tuple[str, ...]:
        """The seats this case is meaningful for, out of the ones the run actually has.

        An empty `identities` means *every* identity, which is the safe direction: the failure
        this feature is prone to is a case set that names **one** seat, so the value that says
        nothing has to mean all of them rather than the first of them (plan §5, spec §3.9).
        """
        if not self.identities:
            return tuple(roster)
        return tuple(role for role in roster if role in self.identities)


def _parse_block(text: str, block: str, first: str) -> Tuple[Dict[str, str], ...]:
    """The hand-written YAML subset, as raw string mappings. Validation is a `check`'s job.

    One parser for both registers, keyed on the block name and on the field a row starts with, so
    the two files cannot end up read by two subsets of one format.
    """
    start = re.compile(r"^\s*-\s+" + re.escape(first) + r":\s*(.+?)\s*$")
    rows: list[Dict[str, str]] = []
    current: Dict[str, str] | None = None
    started = False

    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        if not raw.strip():
            continue
        if raw.startswith(block + ":"):
            started = True
            continue
        opening = start.match(raw)
        if opening:
            current = {first: _scalar(opening.group(1))}
            rows.append(current)
            continue
        field = _FIELD.match(raw)
        if not field or current is None:
            continue
        current[field.group(1)] = _scalar(field.group(2))

    if not started:
        raise AllowlistError(f"the file has no `{block}:` block; the parser and the file disagree")
    return tuple(rows)


def parse(text: str) -> Tuple[Dict[str, str], ...]:
    """The allowlist's rows, as raw string mappings. Validation is `check`'s job."""
    return _parse_block(text, "entries", "kind")


def parse_named(text: str) -> Tuple[Dict[str, str], ...]:
    """The named-comparison register's rows. Validation is `check_named`'s job."""
    return _parse_block(text, "comparisons", "id")


def check(rows: Sequence[Mapping[str, str]]) -> Tuple[Entry, ...]:
    """Validate every row and return the entries, or raise on the first thing that is wrong.

    Raising rather than reporting is deliberate. A harness that loaded a broken allowlist and
    carried on would produce a report whose "allowlisted" count means nothing, and the number it
    means nothing by is the one the reviewer reads.
    """
    if not rows:
        raise AllowlistError("the allowlist has no entries; the parser and the file disagree")

    seen: set[Tuple[str, str, str]] = set()
    entries: list[Entry] = []
    for index, row in enumerate(rows, start=1):
        where = f"entry {index} ({row.get('pointer', '?')} on {row.get('endpoint', '?')})"

        missing = [name for name in _REQUIRED if not row.get(name)]
        if missing:
            raise AllowlistError(f"{where}: missing {', '.join(missing)}")

        kind, endpoint = row["kind"], row["endpoint"]
        pointer, case, because, since = (
            row["pointer"],
            row["case"],
            row["because"],
            row["since"],
        )
        extra = sorted(set(row) - set(_REQUIRED))
        if extra:
            raise AllowlistError(f"{where}: unknown field(s) {', '.join(extra)}")

        if kind not in KINDS:
            raise AllowlistError(f"{where}: kind {kind!r} is not one of {', '.join(KINDS)}")
        if endpoint != "*" and not _ENDPOINT.match(endpoint):
            raise AllowlistError(
                f"{where}: endpoint {endpoint!r} is neither '*' nor 'METHOD /path'"
            )
        if case != "*" and not _CASE.match(case):
            raise AllowlistError(f"{where}: case {case!r} is neither '*' nor a request-case id")
        if not _DATE.match(since):
            raise AllowlistError(f"{where}: since {since!r} is not a YYYY-MM-DD date")

        _check_pointer(where, kind, pointer)

        # AC-6, and the only reason this function raises rather than warns.
        if because not in DERIVATION_CLASSES and not _BEHAVIOURS.match(because):
            raise AllowlistError(
                f"{where}: because {because!r} is neither a behaviours.md section "
                f"('behaviours §3.25') nor one of the four declared derivation classes "
                f"({', '.join(DERIVATION_CLASSES)}). An entry justified by 'we do it differently' "
                f"is rejected, and a fifth class is not added without review (010 AC-6)"
            )

        key = (endpoint, pointer, case)
        if key in seen:
            raise AllowlistError(f"{where}: a second entry for the same endpoint, pointer and case")
        seen.add(key)
        entries.append(Entry(kind, endpoint, pointer, case, row["reason"], because, since))

    return tuple(entries)


def _check_pointer(where: str, kind: str, pointer: str) -> None:
    if pointer.startswith(_HEADER_PREFIX):
        if kind != "field":
            raise AllowlistError(
                f"{where}: a {kind} entry cannot name a header; a header is not an array"
            )
        if not pointer[len(_HEADER_PREFIX) :].strip():
            raise AllowlistError(f"{where}: a header pointer with no header name")
        return
    if pointer == _STATUS_POINTER:
        if kind != "field":
            raise AllowlistError(f"{where}: a {kind} entry cannot name the status")
        return
    if not pointer.startswith("/"):
        raise AllowlistError(
            f"{where}: pointer {pointer!r} is not a JSON Pointer, a 'header:<name>' or 'status'. "
            f"A bare field name is exactly what this file exists not to carry"
        )
    if pointer.endswith("/"):
        raise AllowlistError(f"{where}: pointer {pointer!r} ends in an empty segment")


def load(path: Path = DEFAULT_ALLOWLIST) -> Tuple[Entry, ...]:
    """Read, parse and validate the allowlist. The one entry point a runner needs."""
    return check(parse(Path(path).read_text(encoding="utf-8")))


def check_named(rows: Sequence[Mapping[str, str]]) -> Tuple[NamedComparison, ...]:
    """Validate the named-comparison register, or raise on the first thing that is wrong.

    It raises for the reason `check` does. A run's coverage line is *"n of the §3.10 list run, n
    outstanding"* (spec §3.4), and a register that half-loaded would make both numbers a guess —
    while the whole point of AC-16 is that an unrun comparison is visible rather than absent.
    """
    if not rows:
        raise AllowlistError("the register has no rows; the parser and the file disagree")

    seen: set[str] = set()
    comparisons: list[NamedComparison] = []
    for index, row in enumerate(rows, start=1):
        where = f"row {index} ({row.get('id', '?')})"

        missing = [name for name in _NAMED_REQUIRED if name not in row or not row[name].strip()]
        if missing:
            raise AllowlistError(f"{where}: missing {', '.join(missing)}")
        extra = sorted(set(row) - set(_NAMED_REQUIRED))
        if extra:
            raise AllowlistError(f"{where}: unknown field(s) {', '.join(extra)}")

        identifier = row["id"]
        if not _ID.match(identifier):
            raise AllowlistError(f"{where}: id {identifier!r} is not a lowercase hyphenated name")
        if identifier in seen:
            raise AllowlistError(f"{where}: a second row with this id")
        seen.add(identifier)

        needs = _needs(where, row["needs"])

        behaviours = row["behaviours"]
        if behaviours != NONE and not _BEHAVIOURS_SECTION.match(behaviours):
            raise AllowlistError(
                f"{where}: behaviours {behaviours!r} is neither a behaviours.md section "
                f"('behaviours §3.16') nor {NONE!r}. A row whose answer is not written in "
                f"behaviours.md says so, and `written_at` is where it is written instead"
            )

        written_at = row["written_at"]
        if not _WRITTEN_AT.match(written_at):
            raise AllowlistError(
                f"{where}: written_at {written_at!r} is not a document of this repository. "
                f"A citation never names a path outside it (AGENTS.md)"
            )

        comparisons.append(
            NamedComparison(
                identifier,
                row["what"],
                row["why_the_sweep_misses_it"],
                needs,
                behaviours,
                written_at,
                row["runner"],
            )
        )

    return tuple(comparisons)


def _needs(where: str, raw: str) -> Tuple[str, ...]:
    """`[]`, or `[a, b]` whose members are all declared.

    An empty list is a **value** and not an absence: the last two rows of §3.10 need nothing at all
    and are still counted.
    """
    match = _LIST.match(raw)
    if not match:
        raise AllowlistError(f"{where}: needs {raw!r} is not a list; an empty one is written []")
    body = match.group(1).strip()
    needs = tuple(part.strip() for part in body.split(",")) if body else ()
    for need in needs:
        if need not in NEEDS:
            raise AllowlistError(
                f"{where}: needs {need!r} is not one of {', '.join(NEEDS)}. A run reads this to "
                f"decide whether a row is askable, so a value it does not know would silently "
                f"never be met"
            )
    if len(set(needs)) != len(needs):
        raise AllowlistError(f"{where}: needs {raw!r} repeats a value")
    return needs


def load_named(path: Path = DEFAULT_NAMED_COMPARISONS) -> Tuple[NamedComparison, ...]:
    """Read, parse and validate the named-comparison register."""
    return check_named(parse_named(Path(path).read_text(encoding="utf-8")))


def parse_cases(text: str) -> Tuple[Dict[str, str], ...]:
    """The request-case register's rows. Validation is `check_cases`' job."""
    return _parse_block(text, "cases", "id")


def check_cases(rows: Sequence[Mapping[str, str]]) -> Tuple[RequestCase, ...]:
    """Validate the request cases, or raise on the first thing that is wrong.

    It raises for the reason the other two do, and for one more of its own: a case is what the
    sweep *sends*. A row that half-loaded would not excuse a difference or miscount a coverage
    line — it would issue a request nobody wrote, against a server, and compare the answer.
    """
    if not rows:
        raise AllowlistError("the register has no cases; the parser and the file disagree")

    seen: set[Tuple[str, str]] = set()
    cases: list[RequestCase] = []
    for index, row in enumerate(rows, start=1):
        where = f"case {index} ({row.get('id', '?')} on {row.get('endpoint', '?')})"

        missing = [
            name
            for name in _CASE_REQUIRED
            if name not in row or (name not in _CASE_MAY_BE_EMPTY and not row[name].strip())
        ]
        if missing:
            raise AllowlistError(f"{where}: missing {', '.join(missing)}")
        extra = sorted(set(row) - set(_CASE_REQUIRED))
        if extra:
            raise AllowlistError(f"{where}: unknown field(s) {', '.join(extra)}")

        identifier, endpoint = row["id"], row["endpoint"]
        if not _CASE.match(identifier):
            raise AllowlistError(f"{where}: id {identifier!r} is not a lowercase hyphenated name")
        if not _ENDPOINT.match(endpoint):
            raise AllowlistError(f"{where}: endpoint {endpoint!r} is not 'METHOD /path'")
        if (endpoint, identifier) in seen:
            raise AllowlistError(
                f"{where}: a second case with this id on this endpoint. An id is unique per "
                f"endpoint because the report names a difference by (endpoint, case, identity), "
                f"and two cases under one name is one difference nobody can reproduce"
            )
        seen.add((endpoint, identifier))

        query, body = row["query"], row["body"]
        content_type = row["content_type"]
        _check_body(where, endpoint, body, content_type)

        anchors = _anchors(where, endpoint, row["anchors"])
        needs = _members(where, "needs", row["needs"], NEEDS)
        identities = _members(where, "identities", row["identities"], ROLES)
        _check_substitutions(where, query, body, anchors)
        _check_path_parameters(where, endpoint, anchors, needs)
        _check_anchors_are_used(where, endpoint, query, body, anchors)

        cases.append(
            RequestCase(
                identifier,
                endpoint,
                query,
                body,
                content_type,
                anchors,
                identities,
                needs,
                row["what_it_is_for"],
            )
        )

    _check_anchor_targets(cases)
    return tuple(cases)


def _check_substitutions(where: str, query: str, body: str, anchors: Sequence[Anchor]) -> None:
    """Every `<token>` is one somebody fills: the identity's own, or a declared anchor's."""
    declared = {one.parameter for one in anchors}
    for text in (query, body):
        for token in _SUBSTITUTION.findall(text):
            if token in SUBSTITUTIONS:
                continue
            if token.startswith(ANCHOR_SUBSTITUTION_PREFIX):
                parameter = token[len(ANCHOR_SUBSTITUTION_PREFIX) :]
                if parameter in declared:
                    continue
                raise AllowlistError(
                    f"{where}: <{token}> names an anchor {parameter!r} this case does not "
                    f"declare, so nothing would fill it"
                )
            raise AllowlistError(
                f"{where}: <{token}> is not one of {', '.join(SUBSTITUTIONS)} and is not "
                f"'{ANCHOR_SUBSTITUTION_PREFIX}<parameter>'. A token nothing substitutes would "
                f"reach the server as those literal characters"
            )


def _check_anchors_are_used(
    where: str, endpoint: str, query: str, body: str, anchors: Sequence[Anchor]
) -> None:
    """An anchor fills a path parameter or a `<anchor.p>` token, and never nothing.

    Without this the register would accept an anchor nobody reads — which is exactly how a case
    ends up *looking* filled while it still sends whatever it sent before. Same shape as T6's
    refusal of a placeholder item id: a case that compares two `404`s counts as coverage.
    """
    parameters = set(_PATH_PARAMETER.findall(endpoint))
    tokens = {
        token[len(ANCHOR_SUBSTITUTION_PREFIX) :]
        for text in (query, body)
        for token in _SUBSTITUTION.findall(text)
        if token.startswith(ANCHOR_SUBSTITUTION_PREFIX)
    }
    for anchor in anchors:
        if anchor.parameter not in parameters and anchor.parameter not in tokens:
            raise AllowlistError(
                f"{where}: anchor {anchor.parameter!r} fills no path parameter of {endpoint!r} "
                f"and no <{ANCHOR_SUBSTITUTION_PREFIX}{anchor.parameter}> in the query or body"
            )


def _check_body(where: str, endpoint: str, body: str, content_type: str) -> None:
    method = endpoint.split(" ", 1)[0]
    if body != NONE and method in {"GET", "HEAD"}:
        raise AllowlistError(f"{where}: a {method} case cannot carry a body")
    if body == NONE and content_type != NONE:
        raise AllowlistError(
            f"{where}: content_type {content_type!r} with no body describes nothing"
        )
    if content_type != NONE and not _MEDIA_TYPE.match(content_type):
        raise AllowlistError(
            f"{where}: content_type {content_type!r} is neither a media type nor {NONE!r}"
        )


def _members(where: str, field: str, raw: str, allowed: Sequence[str]) -> Tuple[str, ...]:
    """`[]`, or `[a, b]` whose members are all declared. An empty list is a value."""
    match = _LIST.match(raw)
    if not match:
        raise AllowlistError(f"{where}: {field} {raw!r} is not a list; an empty one is written []")
    body = match.group(1).strip()
    values = tuple(part.strip() for part in body.split(",")) if body else ()
    for value in values:
        if value not in allowed:
            raise AllowlistError(f"{where}: {field} {value!r} is not one of {', '.join(allowed)}")
    if len(set(values)) != len(values):
        raise AllowlistError(f"{where}: {field} {raw!r} repeats a value")
    return values


def _anchors(where: str, endpoint: str, raw: str) -> Tuple[Anchor, ...]:
    match = _LIST.match(raw)
    if not match:
        raise AllowlistError(f"{where}: anchors {raw!r} is not a list; an empty one is written []")
    body = match.group(1).strip()
    if not body:
        return ()
    anchors: list[Anchor] = []
    for part in body.split(","):
        # Quoted, because `{itemId}` inside an unquoted flow sequence is a YAML flow *mapping*
        # and the two-regex reader cannot tell. `test_the_three_registers_are_valid_yaml` is what
        # said so, on the first anchor that named a path with a parameter in it.
        anchors.append(_anchor(where, endpoint, _scalar(part)))
    if len({one.parameter for one in anchors}) != len(anchors):
        raise AllowlistError(f"{where}: two anchors fill the same path parameter")
    return tuple(anchors)


def _anchor(where: str, endpoint: str, text: str) -> Anchor:
    literal = _LITERAL_ANCHOR.match(text)
    if literal:
        return Anchor(literal.group("parameter"), "literal", "", "", literal.group("value"))

    parsed = _ANCHOR.match(text)
    if not parsed:
        raise AllowlistError(
            f"{where}: anchor {text!r} is none of '<parameter>=literal:<value>', "
            f"'<parameter>=listing:<METHOD> <path>#<case>@<position>' or "
            f"'<parameter>=response:<METHOD> <path>#<case>@<pointer>'"
        )
    anchor = Anchor(
        parsed.group("parameter"),
        parsed.group("kind"),
        parsed.group("endpoint"),
        parsed.group("case"),
        parsed.group("at"),
    )
    if anchor.kind == "listing" and not _POSITION.match(anchor.at):
        raise AllowlistError(f"{where}: a listing anchor ends in a row position, not {anchor.at!r}")
    if anchor.kind == "response" and not anchor.at.startswith("/"):
        raise AllowlistError(
            f"{where}: a response anchor ends in a JSON Pointer, not {anchor.at!r}"
        )
    if anchor.endpoint == endpoint:
        raise AllowlistError(
            f"{where}: anchored on its own endpoint, which cannot be resolved before itself"
        )
    return anchor


def _check_path_parameters(
    where: str, endpoint: str, anchors: Sequence[Anchor], needs: Sequence[str]
) -> None:
    """Every `{parameter}` of the path is accounted for, or the case says it is waiting.

    Three ways to account for one, and no fourth. An anchor fills it; `userId` is the identity's
    own and never an anchor (plan §6.1.1); or the case declares `fixture` and leaves it unfilled
    because the item it wants does not exist in any reachable library, which T11 resolves. A
    parameter that is none of the three is a case that would be sent with a literal `{itemId}` in
    its path and compared as two `404`s.
    """
    declared = {one.parameter for one in anchors}
    for parameter in _PATH_PARAMETER.findall(endpoint):
        if parameter in declared or parameter == IDENTITY_PATH_PARAMETER:
            continue
        if "fixture" in needs:
            continue
        raise AllowlistError(
            f"{where}: path parameter {parameter!r} has no anchor, is not "
            f"{IDENTITY_PATH_PARAMETER!r}, and the case does not declare `needs: [fixture]`"
        )


def _check_anchor_targets(cases: Sequence[RequestCase]) -> None:
    """An anchor names a case, so the case has to be one this file declares."""
    declared = {(one.endpoint, one.id) for one in cases}
    for case in cases:
        for anchor in case.anchors:
            if anchor.kind == "literal":
                continue
            if (anchor.endpoint, anchor.case) not in declared:
                raise AllowlistError(
                    f"case {case.id} on {case.endpoint}: anchor {anchor.parameter} names "
                    f"{anchor.case!r} on {anchor.endpoint!r}, which this register does not declare"
                )


def check_anchor_orderings(cases: Sequence[RequestCase], entries: Sequence[Entry]) -> None:
    """**An anchor is only as sound as the ordering it indexes** (plan §6.1.1).

    A `listing:` anchor says *"the row at position 3"*, so a listing the allowlist marks `drawn`
    or `unordered` gives it an arbitrary row — and every case anchored on one is then a comparison
    of two different items dressed up as a comparison of one. The register refuses it, which is
    why this is a check over the two files together and not over either alone.
    """
    for case in cases:
        for anchor in case.anchors:
            if anchor.kind != "listing":
                continue
            rules = resolve(entries, anchor.endpoint, anchor.case)
            excused = dict(rules.drawn_arrays)
            excused.update(rules.unordered_arrays)
            if excused:
                raise AllowlistError(
                    f"case {case.id} on {case.endpoint}: {anchor.parameter} is anchored on "
                    f"{anchor.case!r} of {anchor.endpoint!r}, whose rows the allowlist excuses "
                    f"({', '.join(sorted(excused))}). An anchor over a listing with no ordering "
                    f"names an arbitrary row (plan §6.1.1)"
                )


def load_cases(
    path: Path = DEFAULT_REQUEST_CASES, entries: Sequence[Entry] = ()
) -> Tuple[RequestCase, ...]:
    """Read, parse and validate the request cases against the allowlist entries.

    `entries` is not optional in spirit: `check_anchor_orderings` is the half of the validation
    that needs both files, and an empty tuple runs every other check and excuses nothing — which
    is what a caller that only wants the shapes gets, and what it says it is getting.
    """
    cases = check_cases(parse_cases(Path(path).read_text(encoding="utf-8")))
    check_anchor_orderings(cases, entries)
    return cases


def cases_for(cases: Iterable[RequestCase], endpoint: str) -> Tuple[RequestCase, ...]:
    """Every case declared for one endpoint, in file order — the order a run issues them in."""
    return tuple(case for case in cases if case.endpoint == endpoint)


def resolve(
    entries: Iterable[Entry],
    endpoint: str,
    case: str = "*",
    identity: str | None = None,
) -> Resolution:
    """The rules for one comparison: `(endpoint, case, identity)` in, three mappings out.

    An entry applies when its `endpoint` is `"*"` or names this one, and its `case` is `"*"` or
    names this one. `"*"` is exactly as wide as it looks, which is why review sees it (plan §6.3).

    **`identity` is accepted and selects nothing today, and that is a statement rather than an
    oversight.** Spec §3.9 makes the identity a first-class dimension of a run - 12 of 23 reads of
    the surface answer differently to a restricted non-administrator, two of them as shorter lists
    `[probe: tools/probe_restricted_surface.py, Jellyfin 10.11.11, 2026-09-01]` - but every one of
    those is a **finding**, not an excuse, and no row of spec §3.3 is conditioned on who asked. An
    entry that needed to be would need an eighth column, which is a contract decision and not
    something a resolver should invent by reading a reason.
    """
    del identity  # documented above: no entry is scoped by it, and none may become so silently
    excused: Dict[str, str] = {}
    drawn: Dict[str, str] = {}
    unordered: Dict[str, str] = {}
    buckets = {"field": excused, "drawn": drawn, "unordered": unordered}
    for entry in entries:
        if entry.endpoint != "*" and entry.endpoint != endpoint:
            continue
        if entry.case != "*" and entry.case != case:
            continue
        buckets[entry.kind][entry.pointer] = entry.reason
    return Resolution(excused, drawn, unordered)


__all__ = [
    "DEFAULT_ALLOWLIST",
    "DEFAULT_NAMED_COMPARISONS",
    "DEFAULT_REQUEST_CASES",
    "DERIVATION_CLASSES",
    "IDENTITY_PATH_PARAMETER",
    "KINDS",
    "NEEDS",
    "NONE",
    "ROLES",
    "SUBSTITUTIONS",
    "AllowlistError",
    "Anchor",
    "Entry",
    "NamedComparison",
    "RequestCase",
    "Resolution",
    "cases_for",
    "check",
    "check_anchor_orderings",
    "check_cases",
    "check_named",
    "load",
    "load_cases",
    "load_named",
    "parse",
    "parse_cases",
    "parse_named",
    "resolve",
]
