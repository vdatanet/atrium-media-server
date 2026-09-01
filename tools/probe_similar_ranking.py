#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does the reference rank `Similar`, and does its `limit` mean what it says?

Answers 010 §7 OQ-4 — *what to do when the reference's own response is non-deterministic* — and
with it 005 §7 OQ-5, which has stood open since that spec was written because nobody had asked the
reference how it ranks. The answer is that it does not rank at all: the route filters on the seed's
genres and tags and orders the result at random `[source:
Jellyfin.Api/Controllers/LibraryController.cs:790-801 @ v10.11.11]`, so two identical requests are
two independent draws rather than one ranking read twice.

That matters to a differential harness in a way a value comparison cannot express. The rows are not
"the same items in a different order" — successive draws over a large pool share nothing — so the
response can only be compared by **shape**, and the thing being allowlisted is a whole array rather
than a field.

The second battery is the one no one asked for. The pinned document calls `limit` *"the maximum
number of records to return"* `[spec: GetSimilarItems]`, and for a **movie** seed it is not one: the
repository adds four to any limit it is given whenever the query groups by metadata key `[source:
Jellyfin.Server.Implementations/Item/BaseItemRepository.cs:1427-1429 @ v10.11.11]`, and this route
sets that flag for exactly the movie case `[source:
Jellyfin.Api/Controllers/LibraryController.cs:795 @ v10.11.11]`. Nothing de-duplicates afterwards,
so the four extra rows are handed to the caller. A series, an album or an artist seed honours the
limit exactly, which is what makes the reading discriminating rather than a coincidence of pool
sizes.

Read-only. Writes nothing.

Usage:
    python3 tools/probe_similar_ranking.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from _probe import Probe, ProbeError, Server, main

#: The seed types the route treats differently. `Movie` is the one the grouping flag is set for.
SEED_TYPES = ["Movie", "Series", "MusicAlbum", "MusicArtist"]

#: Limits asked for in the second battery. Small enough that a modest library still has a pool.
LIMITS = [1, 5, 20]

#: Draws taken in the first battery. Four is enough for an intersection to be meaningful and
#: cheap enough that the probe stays a handful of requests.
DRAWS = 4

#: The limit used for the draws. Big enough to make an accidental agreement unlikely.
DRAW_LIMIT = 10


def similar(server: Server, item_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
    parameters: Dict[str, Any] = {"userId": server.user_id}
    if limit is not None:
        parameters["limit"] = limit
    return server.get_where(f"/Items/{item_id}/Similar", parameters)


def seeds_of(server: Server, item_type: str, count: int) -> List[Dict[str, Any]]:
    return list(
        server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes=item_type,
            Limit=count,
            SortBy="SortName",
            userId=server.user_id,
        ).get("Items", [])
    )


def a_seed_with_a_pool(server: Server, item_type: str, wanted: int) -> Optional[Dict[str, Any]]:
    """The first item of this type whose unlimited `Similar` pool is larger than `wanted`.

    A seed whose pool is exhausted answers the same rows every time and honours every limit -
    truthfully, and uselessly. Both batteries need a pool with room in it, or they measure the
    library rather than the server.
    """
    for candidate in seeds_of(server, item_type, 8):
        pool = similar(server, str(candidate["Id"]))
        if len(pool.get("Items", [])) > wanted:
            return candidate
    return None


def draws(server: Server, seed: Dict[str, Any]) -> List[Tuple[str, ...]]:
    return [
        tuple(
            str(row["Id"]) for row in similar(server, str(seed["Id"]), DRAW_LIMIT).get("Items", [])
        )
        for _ in range(DRAWS)
    ]


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_similar_ranking.py",
        question="does the reference rank `Similar`, and does its `limit` mean what it says?",
        document="specs/010-conformance-harness/spec.md",
        section="section 7 OQ-4 and the G-1/G-2 rows (005 section 7 OQ-5 points here)",
        expectation=(
            "the reference draws `Similar` at random rather than ranking it, so successive "
            "identical requests share few or no rows and only the shape is comparable; and "
            "`limit` is honoured exactly except on a movie seed, which answers limit + 4"
        ),
    )

    movie = a_seed_with_a_pool(server, "Movie", max(LIMITS) + 4)
    if movie is None:
        raise ProbeError(
            "no movie on this server has a `Similar` pool larger than "
            f"{max(LIMITS) + 4} items, so neither battery can be told apart from an exhausted pool"
        )

    # -- battery one: is one request one reading of a ranking, or one draw? --------------------
    taken = draws(server, movie)
    union: set = set()
    overlap: set = set(taken[0])
    for one in taken:
        union |= set(one)
        overlap &= set(one)
    probe.observe("seed", f"{movie['Type']} {movie['Name']!r}")
    probe.observe("draws", f"{DRAWS} identical requests, limit={DRAW_LIMIT}")
    probe.observe("rows per draw", ", ".join(str(len(one)) for one in taken))
    probe.observe("distinct orders", len(set(taken)))
    probe.observe("union of the draws", f"{len(union)} items")
    probe.observe("intersection of the draws", f"{len(overlap)} items")

    stable = len(set(taken)) == 1

    # -- battery two: what does `limit` bound? -------------------------------------------------
    honoured: Dict[str, bool] = {}
    for item_type in SEED_TYPES:
        seed = a_seed_with_a_pool(server, item_type, max(LIMITS) + 4)
        if seed is None:
            probe.observe(f"{item_type} seed", "none with a pool large enough - not measured")
            continue
        cells = []
        exact = True
        for limit in LIMITS:
            answer = similar(server, str(seed["Id"]), limit)
            got = len(answer.get("Items", []))
            total = answer.get("TotalRecordCount")
            cells.append(f"limit={limit} -> {got} rows, TotalRecordCount={total}")
            exact = exact and got == limit
        honoured[item_type] = exact
        probe.observe(f"{item_type} {str(seed['Name'])[:24]!r}", "; ".join(cells))

    movie_overshoots = honoured.get("Movie") is False
    others_exact = [kind for kind, exact in honoured.items() if kind != "Movie" and exact]
    others_loose = [kind for kind, exact in honoured.items() if kind != "Movie" and not exact]

    probe.note(
        "The route orders by `Random` and carries no similarity score at all: it filters on the "
        "seed's own genres and tags and shuffles what matches "
        "[source: Jellyfin.Api/Controllers/LibraryController.cs:790-801 @ v10.11.11]. "
        "`TotalRecordCount` is the number of rows returned, not the size of the pool "
        "[source: Jellyfin.Api/Controllers/LibraryController.cs:814-817 @ v10.11.11]."
    )
    probe.note(
        "The four extra rows are the repository's, not the controller's: a limited query that "
        "groups by metadata key is given `Limit + 4` "
        "[source: Jellyfin.Server.Implementations/Item/BaseItemRepository.cs:1427-1429 @ "
        "v10.11.11], and this route sets that flag for a movie seed and for nothing else "
        "[source: Jellyfin.Api/Controllers/LibraryController.cs:795 @ v10.11.11]. Nothing "
        "de-duplicates after the over-fetch, so the caller receives the four."
    )

    probe.conclude(
        (
            f"{DRAWS} identical requests returned {len(union)} distinct items with "
            f"{len(overlap)} in common, so the response is a fresh draw rather than a ranking; "
            "a movie seed answers limit + 4 rows "
            f"({'observed' if movie_overshoots else 'NOT observed'}) while "
            f"{', '.join(others_exact) or 'no other type'} honours the limit exactly"
            + (f"; unexpectedly loose: {', '.join(others_loose)}" if others_loose else "")
        ),
        matches_documentation=(
            not stable and movie_overshoots and not others_loose and bool(others_exact)
        ),
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(
        main(
            run,
            "Does the reference rank `Similar`, and does its `limit` mean what it says?",
        )
    )
