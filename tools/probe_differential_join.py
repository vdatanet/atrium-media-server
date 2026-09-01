#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What can join an item on two servers whose identifiers are derived differently?

Answers 010 §7 OQ-1. A differential compares one request's answer on two servers, and every
comparison past "the two bodies are byte-identical" needs to know which row over here is which row
over there. The identifiers cannot do it: the reference derives one from the item's absolute path
and a .NET type name, Atrium from the path relative to its library root, and matching the
reference's bytes is explicitly not a goal
([behaviours §1.4](../docs/compatibility/behaviours.md)). So the join key has to be something else,
and this probe asks what is actually on the wire to join on.

Three candidates, and the probe measures each rather than arguing it:

* **`Path`** - the one value two servers scanning one tree can agree on. The question is coverage:
  how many rows carry one, on which routes, and whether the ones that do carry a path that names
  the media rather than the server's own data directory.
* **`(Type, Name)`** - free, present on every row, and worth measuring precisely because it looks
  sufficient until a library has two tracks with the same title.
* **Ordinal position** - free too, but only as good as the ordering, and
  [behaviours §3.6](../docs/compatibility/behaviours.md) already records that Atrium's ordering is
  total where the reference's is not.

Read-only. Writes nothing.

Usage:
    python3 tools/probe_differential_join.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from _probe import Probe, ProbeError, Server, main

#: How many rows to draw for the coverage batteries. Large enough to hold several item types on a
#: real library and small enough to stay one page.
SAMPLE = 1000

#: The by-name routes of the v1 surface. They answer rows whose `Type` also appears under /Items,
#: which is what makes measuring them separately worth the requests.
BY_NAME = ["/Artists", "/Artists/AlbumArtists", "/Genres", "/MusicGenres", "/Studios", "/Persons"]


def roots_of(paths: List[str]) -> Set[str]:
    """The two-segment prefixes of a set of absolute paths - `/media/music` and its siblings.

    Only ever printed, so that a reader can see at a glance where each route's paths live. The
    question of whether a path is one this installation invented is asked against the server's
    own `ProgramDataPath` instead, which is a fact rather than a prefix heuristic.
    """
    roots = set()
    for path in paths:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2:
            roots.add("/" + "/".join(parts[:2]))
    return roots


def page(server: Server, path: str, parameters: Dict[str, Any]) -> List[Dict[str, Any]]:
    answer = server.get_where(path, parameters)
    if isinstance(answer, list):
        return list(answer)
    return list(answer.get("Items", []))


def _types_under(rows: List[Dict[str, Any]], prefix: str) -> Set[str]:
    """The item types whose path lies under a prefix - the server's own data directory."""
    return {str(row.get("Type")) for row in rows if str(row.get("Path") or "").startswith(prefix)}


def counts_by_type(rows: List[Dict[str, Any]]) -> Dict[str, Tuple[int, int]]:
    """Per type: how many rows there were, and how many of them carried a non-empty `Path`."""
    tally: Dict[str, Tuple[int, int]] = {}
    for row in rows:
        kind = str(row.get("Type"))
        seen, with_path = tally.get(kind, (0, 0))
        tally[kind] = (seen + 1, with_path + (1 if row.get("Path") else 0))
    return tally


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_differential_join.py",
        question="what can join an item on two servers whose identifiers differ?",
        document="specs/010-conformance-harness/spec.md",
        section="section 7 OQ-1",
        expectation=(
            "`Path` is absent from a default list row and has to be asked for by name; asking "
            "for it covers the file-backed items and no others, and the by-name routes answer "
            "paths inside the server's own data directory rather than inside the media tree"
        ),
    )

    common: Dict[str, Any] = {
        "Recursive": "true",
        "Limit": SAMPLE,
        "SortBy": "SortName",
        "userId": server.user_id,
    }

    bare = page(server, "/Items", common)
    if not bare:
        raise ProbeError("the library is empty, so there is nothing to join")
    asked = page(server, "/Items", dict(common, Fields="Path"))

    bare_with_path = sum(1 for row in bare if row.get("Path"))
    probe.observe("rows sampled", f"{len(bare)} of {len(asked)} asked for again with Fields=Path")
    probe.observe("carrying `Path` by default", f"{bare_with_path} of {len(bare)}")

    single = server.get_where(f"/Items/{bare[0]['Id']}", {"userId": server.user_id})
    probe.observe(
        "a bare GET /Items/{itemId}",
        f"{len(single)} properties, Path {'present' if single.get('Path') else 'absent'}",
    )

    tally = counts_by_type(asked)
    for kind in sorted(tally):
        seen, with_path = tally[kind]
        probe.observe(f"  {kind}", f"{with_path} of {seen} carry a path")
    pathless = sorted(kind for kind, (seen, with_path) in tally.items() if with_path < seen)

    paths = [str(row["Path"]) for row in asked if row.get("Path")]
    probe.observe("paths, distinct", f"{len(set(paths))} of {len(paths)}")

    names = [(str(row.get("Type")), str(row.get("Name"))) for row in asked]
    probe.observe("(Type, Name), distinct", f"{len(set(names))} of {len(names)}")

    data_directory = str(server.get("/System/Info").get("ProgramDataPath") or "")
    if not data_directory:
        raise ProbeError(
            "GET /System/Info answered no ProgramDataPath, so the probe cannot tell a path that "
            "names the media from one this installation invented. It needs an administrator"
        )
    probe.observe("the server's own data directory", data_directory)
    probe.observe("roots seen under /Items", ", ".join(sorted(roots_of(paths))) or "none")
    internal = [one for one in paths if one.startswith(data_directory)]
    probe.observe(
        "/Items paths inside it",
        f"{len(internal)} of {len(paths)}"
        + (" - " + ", ".join(sorted(_types_under(asked, data_directory))) if internal else ""),
    )

    # -- the by-name routes, which answer the same `Type` values through a different population --
    outside: List[str] = []
    for route in BY_NAME:
        rows = page(server, route, {"userId": server.user_id, "Limit": 5, "Fields": "Path"})
        if not rows:
            probe.observe(route, "no rows on this library")
            continue
        theirs = [str(row["Path"]) for row in rows if row.get("Path")]
        elsewhere = [one for one in theirs if one.startswith(data_directory)]
        outside.extend(elsewhere)
        where = sorted(roots_of(theirs)) or ["no path at all"]
        probe.observe(
            route,
            f"{len(theirs)} of {len(rows)} carry a path, under {', '.join(where)}",
        )

    probe.note(
        "A path is the only value on the wire that two servers scanning one tree can be expected "
        "to agree on, and it is not free: it is absent from every default list row, so a run that "
        "joins on it is comparing requests no client sends. Asking for it changes the response "
        "under comparison, which is the cost OQ-1 has to price."
    )
    probe.note(
        "The rows with no path are not an edge: a virtual season, a remote channel and every "
        "by-name row are the shapes a library grows on its own. Where a by-name row does carry a "
        "path it names this installation's own metadata directory, which no fixture tree "
        "reproduces and no second server can derive."
    )

    probe.conclude(
        (
            f"`Path` is on {bare_with_path} of {len(bare)} default list rows and on a bare item "
            f"read; asked for by name it covers all but {', '.join(pathless) or 'nothing'}, "
            f"{len(set(paths))} of {len(paths)} distinct; (Type, Name) is "
            f"{len(set(names))} distinct of {len(names)}, so it is not a key; and "
            f"{len(internal)} of the /Items paths and {len(outside)} of the by-name paths "
            f"sampled lie inside the server's own data directory"
        ),
        matches_documentation=(
            bare_with_path == 0
            and bool(single.get("Path"))
            and bool(pathless)
            and len(set(paths)) == len(paths)
            and len(set(names)) < len(names)
            and bool(outside)
        ),
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(
        main(run, "What can join an item on two servers whose identifiers are derived differently?")
    )
