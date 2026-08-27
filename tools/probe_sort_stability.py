#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What breaks a tie under each SortBy, and does paging hold once one is broken?

Answers 005 OQ-3. specs/005 section 3.4 requires Atrium's ordering to be **total** so that paging
can never show an item twice or skip one; whether that is parity or a divergence depends on what
the reference does with a tie, which nothing had measured.

The source says the reference resolves almost nothing: the requested ordering is applied, `Name`
is chained after it **only** when the first ordering is `SortName` or `Default`, and no further
key - not `Id`, not anything - is ever appended
[source: Jellyfin.Server.Implementations/Item/BaseItemRepository.cs:1592-1652 @ v10.11.11].
`Random` is a per-row `EF.Functions.Random()` with no seed at all
[source: Jellyfin.Server.Implementations/Item/OrderMapper.cs:33 @ v10.11.11]. A source citation
says what the code appears to do; this probe measures what the server sends, three ways per
SortBy:

  1. the same request twice - is the full ordering even repeatable?
  2. the same window paged in 97s - does the concatenation equal the one-shot list?
  3. inside every run of rows whose primary key ties - which candidate key (Name, SortName, Id,
     DateCreated, or nothing) explains the order the server chose?

Two of the primary keys can only be approximated from the outside - `Artist` and `AlbumArtist`
order by a cleaned join-table value the API does not return - so for those the probe first checks
the observed order is monotone under its approximation and reports rather than concludes when it
is not.

Writes: nothing.

Usage:
    python3 tools/probe_sort_stability.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from typing import Any, Optional

from _probe import Probe, ProbeError, Server, main

#: One-shot window size and the deliberately awkward page size that has to reassemble it.
WINDOW = 485
PAGE = 97


def folded(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def premiere_or_year(row: dict[str, Any]) -> Optional[str]:
    """The mapped PremiereDate key: the date, or Jan 1 of ProductionYear when the date is null
    [source: Jellyfin.Server.Implementations/Item/OrderMapper.cs:49 @ v10.11.11]."""
    premiere = row.get("PremiereDate")
    if premiere:
        return str(premiere)
    year = row.get("ProductionYear")
    if year:
        return f"{year:04d}-01-01T00:00:00.0000000Z"
    return None


#: SortBy -> (item type to query, how to read the primary key off a returned row, exact?).
#: `exact` is False where the key is an approximation of a value the API does not expose.
SORTS: list[tuple[str, str, Callable[[dict[str, Any]], Any], bool]] = [
    ("SortName", "Movie", lambda r: r.get("SortName"), True),
    ("DateCreated", "Movie", lambda r: r.get("DateCreated"), True),
    ("PremiereDate", "Movie", premiere_or_year, True),
    ("PlayCount", "Movie", lambda r: (r.get("UserData") or {}).get("PlayCount"), True),
    ("DatePlayed", "Movie", lambda r: (r.get("UserData") or {}).get("LastPlayedDate"), True),
    ("AlbumArtist", "Audio", lambda r: folded(r.get("AlbumArtist") or ""), False),
    ("Artist", "Audio", lambda r: folded((r.get("Artists") or [""])[0]), False),
]

#: Candidate tie-breakers, each read off the returned row. Ordinal string comparison, which is
#: SQLite's BINARY collation for anything UTF-8.
CANDIDATES: list[tuple[str, Callable[[dict[str, Any]], Any]]] = [
    ("Name", lambda r: r.get("Name") or ""),
    ("SortName", lambda r: r.get("SortName") or ""),
    ("Id", lambda r: r["Id"]),
    ("DateCreated", lambda r: r.get("DateCreated") or ""),
]


def fetch(
    server: Server, item_type: str, sort_by: str, order: str, start: int, limit: int
) -> list[dict[str, Any]]:
    result = server.get(
        "/Items",
        UserId=server.user_id,
        Recursive="true",
        IncludeItemTypes=item_type,
        SortBy=sort_by,
        SortOrder=order,
        StartIndex=start,
        Limit=limit,
        Fields="SortName,DateCreated",
        EnableImages="false",
    )
    return list(result.get("Items", []))


def runs_of(
    rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any]
) -> tuple[list[list[dict[str, Any]]], int]:
    """Consecutive rows sharing a primary key, and how many adjacent pairs *decrease* - the
    latter being the monotonicity check that tells an approximated key from a wrong one."""
    runs: list[list[dict[str, Any]]] = []
    breaks = 0
    for row in rows:
        if runs and key(runs[-1][-1]) == key(row):
            runs[-1].append(row)
        else:
            if runs and _decreasing(key(runs[-1][-1]), key(row)):
                breaks += 1
            runs.append([row])
    return [r for r in runs if len(r) > 1], breaks


def _decreasing(previous: Any, current: Any) -> bool:
    if previous is None or current is None:
        return False
    if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
        return current < previous
    return str(current) < str(previous)


def surviving_candidates(tie_runs: list[list[dict[str, Any]]], descending: bool) -> list[str]:
    names: list[str] = []
    for name, key in CANDIDATES:
        holds = True
        for run in tie_runs:
            values = [str(key(row)) for row in run]
            ordered = sorted(values, reverse=descending)
            if values != ordered:
                holds = False
                break
        if holds:
            names.append(name)
    return names


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_sort_stability.py",
        question="what breaks a tie under each SortBy, and does paging hold?",
        document="specs/005-item-query-api/spec.md",
        section="section 3.4 (OQ-3)",
        expectation=None,
    )

    findings: list[str] = []

    for sort_by, item_type, key, exact in SORTS:
        first = fetch(server, item_type, sort_by, "Ascending", 0, WINDOW)
        if len(first) < PAGE:
            probe.observe(sort_by, f"only {len(first)} {item_type} row(s); too few to measure")
            continue
        second = fetch(server, item_type, sort_by, "Ascending", 0, WINDOW)
        repeatable = [r["Id"] for r in first] == [r["Id"] for r in second]

        paged: list[dict[str, Any]] = []
        for start in range(0, len(first), PAGE):
            paged.extend(fetch(server, item_type, sort_by, "Ascending", start, PAGE))
        pages_match = [r["Id"] for r in paged] == [r["Id"] for r in first]

        tie_runs, breaks = runs_of(first, key)
        tied_rows = sum(len(r) for r in tie_runs)

        label = f"{sort_by} ({item_type}, {len(first)} rows)"
        if breaks and not exact:
            probe.observe(
                label,
                f"approximated key not monotone ({breaks} break(s)); tie analysis withheld. "
                f"repeatable={repeatable} paged={pages_match}",
            )
            findings.append(f"{sort_by}: unmeasurable from outside (join-table key)")
            continue
        if breaks:
            probe.observe(
                label,
                f"PRIMARY KEY NOT MONOTONE: {breaks} break(s). "
                f"repeatable={repeatable} paged={pages_match}",
            )
            findings.append(f"{sort_by}: observed order violates its own primary key")
            continue

        survivors = surviving_candidates(tie_runs, descending=False) if tie_runs else []
        probe.observe(
            label,
            f"repeatable={repeatable} paged={pages_match} ties={len(tie_runs)} run(s)/"
            f"{tied_rows} row(s) ordered-by={','.join(survivors) if survivors else 'nothing'}",
        )
        if not tie_runs:
            findings.append(f"{sort_by}: no ties in the window, nothing to break")
        else:
            stable = "stable" if repeatable and pages_match else "UNSTABLE"
            findings.append(
                f"{sort_by}: {stable}, ties follow "
                + (",".join(survivors) if survivors else "no candidate")
            )

    # Descending once, for the direction of the chained Name key.
    desc_rows = fetch(server, "Movie", "SortName", "Descending", 0, WINDOW)
    tie_runs, _ = runs_of(desc_rows, lambda r: r.get("SortName"))
    if tie_runs:
        survivors = surviving_candidates(tie_runs, descending=True)
        probe.observe(
            f"SortName Descending ({len(desc_rows)} rows)",
            f"ties={len(tie_runs)} run(s) ordered-by="
            + (",".join(survivors) if survivors else "nothing"),
        )

    # Random: observation only. Two identical requests, then whether paging even means anything.
    one = fetch(server, "Movie", "Random", "Ascending", 0, PAGE)
    two = fetch(server, "Movie", "Random", "Ascending", 0, PAGE)
    if one and two:
        same = [r["Id"] for r in one] == [r["Id"] for r in two]
        overlap = len({r["Id"] for r in one} & {r["Id"] for r in two})
        probe.observe(
            f"Random (Movie, {len(one)} rows twice)",
            f"identical={same} overlap={overlap} of {len(one)}",
        )
        findings.append(
            "Random: identical requests agree" if same else "Random: a new shuffle per request"
        )

    if not findings:
        raise ProbeError("no SortBy had enough rows to measure anything")

    probe.note(
        "the source reads: Name is chained after SortName/Default only, nothing after anything "
        "else, and Random has no seed. The rows above are what the server actually sent."
    )
    probe.conclude("; ".join(findings))
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
