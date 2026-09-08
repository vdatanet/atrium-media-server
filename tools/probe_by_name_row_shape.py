#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which properties does a by-name row omit, and is that a property of the route or of the type?

Two routes of this project drop a property from their rows, and both drops come from one manual
reading on 2026-08-28: `/Artists` and `/Artists/AlbumArtists` send no `IsFolder`
(`api/artists.py`'s `OMITTED`), `/Genres` and `/MusicGenres` send no `UserData`
(`api/genres.py`'s). 005 §3.2 states the first as a fact about **by-name rows** — *"absent on a
by-name row: a genre, a music genre or a year carries no `IsFolder`"*.

**The differential run of 2026-09-07 contradicted the artist half**: on the two artist routes the
reference answered `IsFolder: true` where this server sent nothing, four findings across them
`[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-07]`. One of the two readings
is of a different population, a different route or a different server, and which decides whether
013 closes with a defect on its own routes or with a stale sentence in 005.

So this asks the whole family at once, which the original reading did not:

1. **Each by-name route's own row** — `/Artists`, `/Artists/AlbumArtists`, `/Genres`,
   `/MusicGenres` — for both properties rather than for the one each route drops. A rule that is
   the *route's* shows up as four different answers; a rule that is the **type's** shows up as one
   answer per type whatever route asked.
2. **The same artist through `/Items`**, which is a different route over the same rows. If
   `IsFolder` is there and not on `/Artists`, the omission is the route's; if it is on both, the
   2026-08-28 reading was of something else.
3. **A tree artist**, which is a second population of one type (013 §3.4) and the thing a reading
   that sampled *by type* could not tell apart from a registry row.

**It writes nothing and cannot.** Every request is a `GET`, which is why it may be pointed at a
server somebody owns.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_by_name_row_shape.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

HERE = Path(__file__).resolve().parent

#: The two properties this project drops, one per family, from one reading.
WATCHED: Tuple[str, ...] = ("IsFolder", "UserData")

#: The four by-name routes v1 serves, and `/Years` is deliberately not among them: its rows are
#: numbers rather than names, and neither omission was ever measured on it.
BY_NAME_ROUTES: Tuple[str, ...] = (
    "/Artists",
    "/Artists/AlbumArtists",
    "/Genres",
    "/MusicGenres",
)

DOCUMENT = "specs/005-item-query-api/spec.md"
SECTION = "section 3.2"

EXPECTATION = (
    "005 section 3.2 states the omission as a property of a BY-NAME ROW - a genre, a music genre "
    "or a year carries no IsFolder - and api/artists.py drops it from the two artist routes on "
    "the same reading, so a by-name row should answer the same way whichever route asked and "
    "whatever its type"
)


def load(name: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    if spec is None or spec.loader is None:  # pragma: no cover - the files are beside this one
        raise SystemExit(f"tools/{name}.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def carried(row: Optional[Dict[str, Any]]) -> str:
    """Which of the watched properties this row carries, as a readable answer."""
    if row is None:
        return "no row to read"
    return "  ".join("{}={}".format(name, "yes" if name in row else "NO") for name in WATCHED)


def first_row(server: Any, path: str, **params: Any) -> Optional[Dict[str, Any]]:
    answered = server.get(path, userId=server.user_id, limit=1, **params)
    rows = answered.get("Items", []) if isinstance(answered, dict) else []
    return dict(rows[0]) if rows else None


def measure(server: Any, args: argparse.Namespace) -> Any:
    probe = load("_probe")
    found = probe.Probe(
        script="probe_by_name_row_shape.py",
        question="Which properties does a by-name row omit, and is that the route's or the type's?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )

    answers: Dict[str, Optional[Dict[str, Any]]] = {}
    for route in BY_NAME_ROUTES:
        row = first_row(server, route)
        answers[route] = row
        found.observe(f"{route} row", carried(row))

    # The same population through a different route. If `IsFolder` is here and not above, the
    # omission belongs to the route; if it is on both, the 2026-08-28 reading was of something else.
    through_items = first_row(server, "/Items", recursive="true", includeItemTypes="MusicArtist")
    found.observe("the same type through /Items", carried(through_items))

    genre_through_items = first_row(server, "/Items", recursive="true", includeItemTypes="Genre")
    found.observe("a Genre through /Items", carried(genre_through_items))

    # **Whether an artist row carries `IsFolder` may be about the ROW rather than the route**, and
    # this is the reading that tells them apart. A `MusicArtist` is two populations (013 section
    # 3.4): the registry row a credit names, and the tree item an album hangs off. `/Items` above
    # answers a tree one and carries `IsFolder`; `/Artists` answers registry ones and does not. If
    # the property tracks the population, an `/Artists` row that IS a tree item carries it too -
    # which would explain the fixture instance answering `IsFolder: true` on every `/Artists` row
    # while this library answers none: over that tree every artist has a directory.
    rows = server.get("/Artists", userId=server.user_id, limit=1000).get("Items", [])
    tree = server.get(
        "/Items",
        userId=server.user_id,
        recursive="true",
        includeItemTypes="MusicArtist",
        limit=1000,
    ).get("Items", [])
    tree_ids = {str(one.get("Id")) for one in tree}
    with_flag = {str(one.get("Id")) for one in rows if "IsFolder" in one}
    found.observe("/Artists rows carrying IsFolder", f"{len(with_flag)} of {len(rows)}")
    found.observe(
        "of those, how many are also a tree item",
        f"{len(with_flag & tree_ids)} of {len(with_flag)}" if with_flag else "-",
    )
    found.observe(
        "tree-backed /Artists rows carrying it",
        "{} of {}".format(
            len({str(one.get("Id")) for one in rows if "IsFolder" in one} & tree_ids),
            len({str(one.get("Id")) for one in rows} & tree_ids),
        ),
    )

    # A full body of an artist row, where 005 says a single item answers everything unasked.
    artist = answers["/Artists"]
    body = None
    if artist is not None and artist.get("Id"):
        try:
            body = dict(server.get("/Items/{}".format(artist["Id"]), userId=server.user_id))
        except Exception:
            body = None
    found.observe("that artist's full body", carried(body))

    # **The verdict is the correlation and not any single row.** Two readings of "the reference"
    # disagreed - this library's `/Artists` omits `IsFolder` and a fixture instance's sent it on
    # every row - and one rule explains both if the property tracks whether the row is also a tree
    # item: over that fixture every artist has a directory.
    both = with_flag & tree_ids
    tracks_the_population = (
        bool(rows)
        and both == with_flag
        and both == ({str(one.get("Id")) for one in rows} & tree_ids)
    )

    genre_row = answers["/Genres"]
    if genre_row is not None and "IsFolder" not in genre_row:
        found.note("a /Genres row carries no IsFolder, which is what 005 3.2 says")

    found.conclude(
        (
            "IsFolder on an /Artists row is neither the route's rule nor the type's: it is "
            "present exactly when that row is ALSO an item of the library tree, on every row in "
            "both directions. So 005 3.2's sentence is right about a genre and describes an "
            "artist only by accident of which one was sampled, and the two disagreeing readings "
            "of this property are one rule seen on two libraries"
        )
        if tracks_the_population
        else (
            "IsFolder does not track whether the row is a tree item: "
            "{} rows carry it, {} of them are tree items, and {} tree-backed rows do not".format(
                len(with_flag),
                len(both),
                len(({str(one.get("Id")) for one in rows} & tree_ids) - with_flag),
            )
        ),
        matches_documentation=None,
    )
    return found


def main() -> int:
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "Which properties a by-name row omits, and whether that is the route's rule or "
                "the type's. Every request is a GET: this probe writes nothing, which is why it "
                "may be pointed at a server somebody owns."
            ),
            with_args=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
