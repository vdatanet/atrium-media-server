#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The differential allowlist: `docs/compatibility/allowlist.yaml` in, `Rules` mappings out.

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
_ENTRY_START = re.compile(r"^\s*-\s+kind:\s*(\S+)\s*$")
_FIELD = re.compile(r"^\s{2,}(\w+):\s*(.+?)\s*$")

_REQUIRED = ("kind", "endpoint", "pointer", "case", "reason", "because", "since")


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


def parse(text: str) -> Tuple[Dict[str, str], ...]:
    """The hand-written YAML subset, as raw string mappings. Validation is `check`'s job."""
    rows: list[Dict[str, str]] = []
    current: Dict[str, str] | None = None
    started = False

    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):
            continue
        if not raw.strip():
            continue
        if raw.startswith("entries:"):
            started = True
            continue
        start = _ENTRY_START.match(raw)
        if start:
            current = {"kind": start.group(1).strip().strip('"')}
            rows.append(current)
            continue
        field = _FIELD.match(raw)
        if not field or current is None:
            continue
        current[field.group(1)] = field.group(2).strip().strip('"')

    if not started:
        raise AllowlistError(
            "the allowlist has no `entries:` block; the parser and the file disagree"
        )
    return tuple(rows)


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
    "DERIVATION_CLASSES",
    "KINDS",
    "AllowlistError",
    "Entry",
    "Resolution",
    "check",
    "load",
    "parse",
    "resolve",
]
