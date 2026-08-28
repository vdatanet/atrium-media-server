#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Is `TotalRecordCount` really 0 on the by-name endpoints when the request has no `limit`?

Discharges the last-dated debt in docs/compatibility/reference-target.md's register: the claim
was measured on `master` on 2026-08-05 (upstream jellyfin/jellyfin#17541) and cited from three
documents, but `master` is explicitly not the target — this probe asks the pinned line itself.
behaviours §3.1 says `/Artists`, `/Artists/AlbumArtists`, `/Genres`, `/MusicGenres` and
`/Studios` share the `GetItemValues` path, which disables counting when the request has no
`limit`; `/Years` is documented separately as its own face of the defect.

Since 2026-08-28 it also measures the credit split those two artist routes exist for, mirrored
on `/Items` (the L2 fold pattern of docs/audits/2026-08-28.md): **`artistIds` is the superset
and `albumArtistIds` the subset**, because the first matches *any* credit — the album's own
album-artist row included — and the second only an `album_artist` one. The direction was
hand-measured on 2026-08-27, guessed wrong first (005's tasks record the two parameters as
disjoint sets), and decides `tests/unit/test_item_filters.py` and the seeded world's shape
(`tests/fixtures/query.py`). A performer who is nobody's album artist is the sharp half —
rows to `artistIds`, none to `albumArtistIds` — and is measured when the library has one.

Read-only. Writes nothing.

Usage:
    python3 tools/probe_by_name_counts.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from typing import Any

from _probe import Probe, ProbeError, Server, main

#: The endpoints behaviours §3.1 names as sharing the counting-disabled path.
SHARED_PATH = ["/Artists", "/Artists/AlbumArtists", "/Genres", "/MusicGenres", "/Studios"]

#: Documented separately (its own face of the defect); observed here for the record, not gated.
SEPARATE = ["/Years"]

#: High enough that the count under `limit` is the true one on any realistic library.
LIMIT = 1000


def item_ids(server: Server, parameter: str, artist_id: str) -> set[str]:
    """The visible item ids one artist answers through one of the two credit parameters."""
    page = server.get_where(
        "/Items",
        {"UserId": server.user_id, "Recursive": "true", parameter: artist_id, "Limit": LIMIT},
    )
    return {str(row.get("Id")) for row in page.get("Items", [])}


def measure_credit_split(probe: Probe, server: Server, disagreements: list[str]) -> None:
    """`artistIds` against `albumArtistIds`, per sampled artist - the superset direction.

    An artist with an `album_artist` credit shows the subset relation; a performer who is
    nobody's album artist is the sharp half, and is measured only when the library has one.
    """

    def rows(path: str) -> list[dict[str, Any]]:
        return list(server.get(path, UserId=server.user_id, limit=LIMIT).get("Items", []))

    everyone = rows("/Artists")
    album_artist_ids = {str(r.get("Id")) for r in rows("/Artists/AlbumArtists")}
    with_albums = [r for r in everyone if str(r.get("Id")) in album_artist_ids]
    performers_only = [r for r in everyone if str(r.get("Id")) not in album_artist_ids]

    sampled = [(a, False) for a in with_albums[:5]] + [(a, True) for a in performers_only[:2]]
    if not sampled:
        probe.note("no artist rows at all; the credit split was not measured")
        return

    strict_witness = False
    for artist, performer_only in sampled:
        artist_id = str(artist.get("Id"))
        name = str(artist.get("Name", artist_id))
        any_credit = item_ids(server, "ArtistIds", artist_id)
        album_credit = item_ids(server, "AlbumArtistIds", artist_id)
        tag = " (performer only)" if performer_only else ""
        probe.observe(
            f"credit split: {name}{tag}",
            f"artistIds {len(any_credit)}, albumArtistIds {len(album_credit)}",
        )
        if not album_credit <= any_credit:
            disagreements.append(
                f"albumArtistIds answered rows for {name} that artistIds did not - the "
                "superset direction is reversed"
            )
        if album_credit < any_credit:
            strict_witness = True
        if performer_only and (album_credit or not any_credit):
            disagreements.append(
                f"{name} holds no album_artist credit and answered {len(album_credit)} "
                f"albumArtistIds row(s) beside {len(any_credit)} artistIds one(s) - expected "
                "none and some"
            )

    if not performers_only:
        probe.note(
            "no performer-only artist exists on this library, so the sharp half of the split - "
            "rows to artistIds and none to albumArtistIds - was not exercised."
        )
    if not strict_witness:
        probe.note(
            "every sampled artist answered identical row sets to both parameters, so the "
            "direction rests on the subset check alone for this library."
        )


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_by_name_counts.py",
        question="is TotalRecordCount 0 on the by-name endpoints when the request has no limit?",
        document="docs/compatibility/behaviours.md",
        section="section 3.1",
        expectation=(
            "without limit: TotalRecordCount is 0 beside a non-empty Items; with limit: the true "
            "count — on /Artists, /Artists/AlbumArtists, /Genres, /MusicGenres and /Studios; "
            "and on /Items, artistIds matches any credit while albumArtistIds matches only the "
            "album_artist one — every artist's albumArtistIds rows a subset of its artistIds "
            "rows, a performer-only artist answering rows to the first parameter and none to "
            "the second"
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

    measure_credit_split(probe, server, disagreements)

    if disagreements:
        probe.conclude("; ".join(disagreements), matches_documentation=False)
    else:
        probe.conclude(
            "the pinned line has the defect exactly as behaviours §3.1 states it: counting is "
            "disabled without limit on every non-empty shared-path endpoint, and honest under "
            "one; and artistIds is the superset of the credit split, exactly as measured",
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
