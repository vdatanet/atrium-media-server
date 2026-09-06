#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Four readings this repository's fixture cannot make, taken on a library that has real music.

Every one of these was reached and left open by a run against the fixture, and each was left open
for the **same** reason: the fixture's music is silence and filler bytes with almost no readable
tag, so a value that is empty there may be a constant or may be a real value the tree cannot
produce, and nothing measured from outside can tell those two apart.

1. **`SeriesStudio` on a season and an episode.** Empty on every one of the fixture's, where the
   fixture's series have no studio. Is it the parent series' studio - a derivation - or a constant?
   005's list says the first and cannot show it.
2. **The nine by-name counts on a `MusicArtist`** - `AlbumCount`, `SongCount` and their siblings.
   All nine answer `0` on the fixture, on an artist whose own `ChildCount` is 2 and whose
   `RecursiveItemCount` is 7. Do they count anything on a library with real music?
3. **A music container's `RunTimeTicks` and `CumulativeRunTimeTicks`.** Both answer `0` on the
   fixture for every album and artist, because nothing there has a duration - so a rollup and a
   constant are indistinguishable. Which is it?
4. **What `/Artists` actually lists.** On the fixture it answers rows that are not all items, and
   the item tree holds artists that are not all rows. behaviours §5.3 reads from the reference's
   source that artists there are by-name items created on demand, so that **every performer has a
   row**; that has never been measured from outside.

**It writes nothing and cannot.** Every request is a `GET`, the probe is declared read-only, and it
is pointed at a server somebody owns on purpose - which is the one thing the instance-owning probes
in this directory refuse to do, and the reason this one may: a reading changes nothing, and these
four questions have no answer on a tree this project can generate.

**It is deliberately frugal.** The server it is written for has request throttling on, so the
sampling is bounded: a handful of series, a handful of artists, one album and its tracks, and the
by-name listing once.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_real_library_shapes.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent

#: How many rows each sampled question reads. Small on purpose: see the frugality note above.
SAMPLE = 5

#: The nine properties a `MusicArtist` full body carries on the reference and this project does
#: not send, measured absent-or-zero on the fixture at 005 AC-26's tranche.
BY_NAME_COUNTS: Tuple[str, ...] = (
    "AlbumCount",
    "SongCount",
    "ArtistCount",
    "MusicVideoCount",
    "MovieCount",
    "SeriesCount",
    "EpisodeCount",
    "ProgramCount",
    "TrailerCount",
)

DOCUMENT = "specs/005-item-query-api/tasks.md"
SECTION = "what this feature owes the next ones"


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


def items(server: Any, **params: Any) -> List[Dict[str, Any]]:
    return list(server.get("/Items", userId=server.user_id, **params).get("Items", []))


def series_studio(server: Any, found: Any) -> None:
    """Reading 1: is `SeriesStudio` the parent series' studio, or a constant?"""
    series = items(server, recursive="true", includeItemTypes="Series", limit=40, fields="Studios")
    with_studio = [one for one in series if one.get("Studios")][:SAMPLE]
    found.observe("series sampled", f"{len(with_studio)} of {len(series)} carry a studio")
    if not with_studio:
        found.note("no sampled series carries a studio, so reading 1 is unanswered here")
        return
    agreed = disagreed = 0
    for one in with_studio:
        studios = [str(x.get("Name", "")) for x in (one.get("Studios") or [])]
        episodes = items(
            server, parentId=str(one["Id"]), recursive="true", includeItemTypes="Episode", limit=1
        )
        if not episodes:
            continue
        body = server.get("/Items/{}".format(episodes[0]["Id"]), userId=server.user_id)
        carried = str(body.get("SeriesStudio", ""))
        if carried and carried in studios:
            agreed += 1
        else:
            disagreed += 1
            found.note(
                "{!r}: SeriesStudio={!r} against the series' studios {}".format(
                    str(one.get("Name"))[:40], carried, studios[:3]
                )
            )
    found.observe("episodes whose SeriesStudio is one of its series' studios", agreed)
    found.observe("episodes where it is not", disagreed)


def by_name_counts(server: Any, found: Any) -> Optional[List[Dict[str, Any]]]:
    """Readings 2 and 3: the nine counts, and a music container's two runtimes."""
    artists = items(server, recursive="true", includeItemTypes="MusicArtist", limit=SAMPLE)
    if not artists:
        found.note("this server has no MusicArtist items, so readings 2 to 4 are unanswered")
        return None
    non_zero: Dict[str, int] = {}
    for one in artists:
        body = server.get("/Items/{}".format(one["Id"]), userId=server.user_id)
        for name in BY_NAME_COUNTS:
            if isinstance(body.get(name), int) and body[name] > 0:
                non_zero[name] = non_zero.get(name, 0) + 1
        found.observe(
            "artist {!r}".format(str(one.get("Name"))[:26]),
            "ChildCount={} Recursive={} {}".format(
                body.get("ChildCount"),
                body.get("RecursiveItemCount"),
                " ".join(f"{name}={body.get(name)}" for name in BY_NAME_COUNTS if name in body),
            ),
        )
    found.observe(
        "of the nine counts, how many answered non-zero on any sampled artist",
        "{}: {}".format(len(non_zero), ", ".join(sorted(non_zero)) or "none"),
    )
    return artists


def container_runtimes(server: Any, found: Any) -> None:
    """Reading 3 proper: is a music container's `RunTimeTicks` the sum of its tracks?"""
    albums = items(server, recursive="true", includeItemTypes="MusicAlbum", limit=SAMPLE)
    checked = 0
    for one in albums[:SAMPLE]:
        body = server.get("/Items/{}".format(one["Id"]), userId=server.user_id)
        tracks = items(server, parentId=str(one["Id"]), limit=200, fields="Path")
        total = sum(int(t.get("RunTimeTicks") or 0) for t in tracks)
        if not tracks:
            continue
        checked += 1
        found.observe(
            "album {!r}".format(str(one.get("Name"))[:26]),
            "tracks={} their sum={} RunTimeTicks={} Cumulative={}".format(
                len(tracks), total, body.get("RunTimeTicks"), body.get("CumulativeRunTimeTicks")
            ),
        )
        if checked >= 3:
            break


def what_artists_lists(server: Any, found: Any, artists: Sequence[Dict[str, Any]]) -> None:
    """Reading 4: does `/Artists` list the item tree's artists, or something else?"""
    rows = list(server.get("/Artists", userId=server.user_id, limit=1000).get("Items", []))
    tree = items(server, recursive="true", includeItemTypes="MusicArtist", limit=1000)
    row_ids = {str(one.get("Id")) for one in rows}
    tree_ids = {str(one.get("Id")) for one in tree}
    found.observe("/Artists rows", len(rows))
    found.observe("MusicArtist items in the tree", len(tree))
    found.observe("identifiers in both", len(row_ids & tree_ids))
    found.observe("rows that are not items", len(row_ids - tree_ids))
    found.observe("items that are not rows", len(tree_ids - row_ids))

    # behaviours section 5.3's claim, from the far side: a performer who is nobody's album artist.
    tracks = items(server, recursive="true", includeItemTypes="Audio", limit=200)
    performers = {str(name) for one in tracks for name in (one.get("Artists") or []) if str(name)}
    album_artists = {str(one.get("Name", "")) for one in rows}
    found.observe("distinct performer names on 200 sampled tracks", len(performers))
    found.observe(
        "of those, how many have a /Artists row",
        len(performers & album_artists),
    )
    missing = sorted(performers - album_artists)[:5]
    if missing:
        found.note(f"performers with no /Artists row, sampled: {missing}")


def measure(server: Any, args: argparse.Namespace) -> Any:
    probe = load("_probe")
    found = probe.Probe(
        script="probe_real_library_shapes.py",
        question="The four shapes the fixture's silent music cannot answer",
        document=DOCUMENT,
        section=SECTION,
        expectation=None,
    )
    series_studio(server, found)
    artists = by_name_counts(server, found)
    if artists is not None:
        container_runtimes(server, found)
        what_artists_lists(server, found, artists)
    found.conclude(
        "read above: each of the four is a reading rather than a verdict, and what each one "
        "settles is written on 005's list in the same change"
    )
    return found


def main() -> int:
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "Four readings the fixture cannot make, taken on a library with real music. "
                "Every request is a GET: this probe writes nothing, which is why it may be "
                "pointed at a server somebody owns."
            ),
            with_args=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
