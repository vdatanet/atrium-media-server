#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Is `TotalRecordCount` really 0 on the by-name endpoints when the request has no `limit`?

Discharges the last-dated debt in docs/compatibility/reference-target.md's register: the claim
was measured on `master` on 2026-08-05 (upstream jellyfin/jellyfin#17541) and cited from three
documents, but `master` is explicitly not the target — this probe asks the pinned line itself.
behaviours §3.1 says `/Artists`, `/Artists/AlbumArtists`, `/Genres`, `/MusicGenres` and
`/Studios` share the `GetItemValues` path, which disables counting when the request has no
`limit`; `/Years` is documented separately as its own face of the defect.

Read-only. Two requests per endpoint and writes nothing.

Usage:
    python3 tools/probe_by_name_counts.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from _probe import Probe, ProbeError, Server, main

#: The endpoints behaviours §3.1 names as sharing the counting-disabled path.
SHARED_PATH = ["/Artists", "/Artists/AlbumArtists", "/Genres", "/MusicGenres", "/Studios"]

#: Documented separately (its own face of the defect); observed here for the record, not gated.
SEPARATE = ["/Years"]

#: High enough that the count under `limit` is the true one on any realistic library.
LIMIT = 1000


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_by_name_counts.py",
        question="is TotalRecordCount 0 on the by-name endpoints when the request has no limit?",
        document="docs/compatibility/behaviours.md",
        section="section 3.1",
        expectation=(
            "without limit: TotalRecordCount is 0 beside a non-empty Items; with limit: the true "
            "count — on /Artists, /Artists/AlbumArtists, /Genres, /MusicGenres and /Studios"
        ),
    )

    disagreements: list[str] = []
    empty = 0

    for path in SHARED_PATH + SEPARATE:
        try:
            bare = server.get(path, UserId=server.user_id)
            limited = server.get(path, UserId=server.user_id, limit=LIMIT)
        except ProbeError as exc:
            raise ProbeError(f"{path} did not answer: {exc}") from exc

        rows = len(bare.get("Items", []))
        bare_count = bare.get("TotalRecordCount")
        limited_count = limited.get("TotalRecordCount")
        probe.observe(
            path,
            f"no limit: TotalRecordCount={bare_count} Items={rows}; "
            f"limit={LIMIT}: TotalRecordCount={limited_count}",
        )

        if path in SEPARATE:
            continue
        if rows == 0:
            empty += 1
            continue
        if bare_count != 0:
            disagreements.append(f"{path} counts {bare_count} without limit")
        # "The true count" is pre-paging: a library larger than LIMIT truncates Items and not
        # the count, so equality with the page only holds when the page was not full.
        limited_rows = len(limited.get("Items", []))
        true_count_holds = (
            limited_count == limited_rows
            if limited_rows < LIMIT
            else isinstance(limited_count, int) and limited_count >= LIMIT
        )
        if not true_count_holds:
            disagreements.append(f"{path} with limit says {limited_count} for {limited_rows} rows")

    if empty == len(SHARED_PATH):
        raise ProbeError("every shared-path endpoint is empty; an empty library measures nothing")
    if empty:
        probe.note(
            f"{empty} endpoint(s) answered no rows at all and are not part of the finding: "
            "a defect that zeroes a count cannot be seen on a count that is truly zero."
        )

    if disagreements:
        probe.conclude("; ".join(disagreements), matches_documentation=False)
    else:
        probe.conclude(
            "the pinned line has the defect exactly as behaviours §3.1 states it: counting is "
            "disabled without limit on every non-empty shared-path endpoint, and honest under "
            "one",
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
