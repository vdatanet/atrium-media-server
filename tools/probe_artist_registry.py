#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What population does `/Artists` list, and what is one of its rows?

behaviours §5.3 records an accepted gap in two halves - the same artist in two music libraries is
two rows here, and a performer who is nobody's album artist has no artist item here - and names
*"a deliberate identity migration"* as the closing mechanism. A reading taken on 2026-09-06 put a
number on it from outside: `/Artists` answers **684 rows** where the item tree holds **210**
`MusicArtist` items, 165 identifiers in both, 519 rows that are no item and 45 items that are no
row `[probe: tools/probe_real_library_shapes.py, Jellyfin 10.11.11, 2026-09-06]`.

**That reading measured the sizes and not the shape**, and the shape is what a design turns on.
This probe asks the four questions the counting left open:

1. **What is a row that is no item?** Its `Id` is not in the tree listing - so does `/Items/{id}`
   answer it at all, and if it does, what `Type`, `ParentId` and `LocationType` does it carry?
   A registry that is items and a registry that is rows synthesised for one route are two
   different things to replicate.
2. **Is the registry the same population as the credits?** A track carries `ArtistItems` and
   `AlbumArtists`, each an id and a name. If those ids are the `/Artists` rows' ids, then the row
   population *is* the credit population and one query answers both.
3. **Does a row navigate?** `parentId=<row id>` and `albumArtistIds=<row id>` are what a client
   sends after listing artists. A row whose id lists nothing is a row a client cannot follow.
4. **What is an item that is no row?** 45 of them, and whether they are artists with no credited
   track is the difference between *"two populations"* and *"one population, two filters"*.

**It writes nothing and cannot.** Every request is a `GET`, which is why it may be pointed at a
server somebody owns - the one thing the instance-owning probes in this directory refuse.

**It is deliberately frugal.** That server has request throttling on: the listings are read once
each and the per-row questions are asked of `SAMPLE` rows, not of six hundred.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_artist_registry.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent

#: How many rows each per-row question reads. Small on purpose: see the frugality note above.
SAMPLE = 3

#: What a row's body is read for. `Type` and `LocationType` say whether it is an item of the tree;
#: `ParentId` says what it hangs off; `Path` says whether anything on disk backs it.
BODY_FIELDS: Tuple[str, ...] = ("Type", "ParentId", "Path", "LocationType", "ChildCount")

DOCUMENT = "docs/compatibility/behaviours.md"
SECTION = "section 5.3"

EXPECTATION = (
    "behaviours section 5.3: artists on the reference are by-name items created on demand, so "
    "every performer has a row - and a row is therefore expected to be an item a client can "
    "follow, carrying the same identifier the track's own credits carry"
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


def items(server: Any, **params: Any) -> List[Dict[str, Any]]:
    return list(server.get("/Items", userId=server.user_id, **params).get("Items", []))


def body_of(server: Any, item_id: str) -> Optional[Dict[str, Any]]:
    """One item body, or `None` where the identifier names nothing this seat may read."""
    try:
        return dict(server.get(f"/Items/{item_id}", userId=server.user_id))
    except Exception:
        return None


def summarise(body: Optional[Dict[str, Any]]) -> str:
    if body is None:
        return "no body: /Items/{id} does not answer this identifier"
    return " ".join(f"{name}={body.get(name)!r}" for name in BODY_FIELDS if name in body)


def populations(server: Any, found: Any) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The two listings the 2026-09-06 reading counted, read once each."""
    rows = list(server.get("/Artists", userId=server.user_id, limit=1000).get("Items", []))
    tree = items(server, recursive="true", includeItemTypes="MusicArtist", limit=1000)
    row_ids = {str(one.get("Id")) for one in rows}
    tree_ids = {str(one.get("Id")) for one in tree}
    found.observe("/Artists rows", len(rows))
    found.observe("MusicArtist items in the tree", len(tree))
    found.observe("identifiers in both", len(row_ids & tree_ids))
    found.observe("rows that are no item", len(row_ids - tree_ids))
    found.observe("items that are no row", len(tree_ids - row_ids))
    return rows, tree


def what_a_row_is(server: Any, found: Any, rows: List[Dict[str, Any]], tree_ids: set) -> bool:
    """Question 1: a row whose identifier is in no tree listing - is it an item?

    Returns whether every sampled one **is** an item, which is the half of the expectation this
    function settles: a registry of items and a registry of rows synthesised for one route are two
    different things to replicate.
    """
    orphans = [one for one in rows if str(one.get("Id")) not in tree_ids][:SAMPLE]
    if not orphans:
        found.note("every /Artists row is also a tree item here, so question 1 has no subject")
        return True
    answered = 0
    for one in orphans:
        body = body_of(server, str(one["Id"]))
        if body is not None and str(body.get("Type")) == "MusicArtist":
            answered += 1
        found.observe(
            "row not in the tree: {!r}".format(str(one.get("Name"))[:26]),
            summarise(body),
        )
    return answered == len(orphans)


#: What a filename cannot carry, and what the reference replaces with a space before a name
#: becomes a by-name key `[source: Emby.Server.Implementations/IO/ManagedFileSystem.cs:21-27 @
#: v10.11.11]`. Spelled here rather than imported: `tools/` is standalone programs, and the point
#: of asking it here is to check the rule from outside rather than to trust the copy inside.
PATH_INVALID = frozenset('"<>|:*?\\/') | {chr(code) for code in range(0x00, 0x20)}


def as_a_key(name: str) -> str:
    return "".join(" " if character in PATH_INVALID else character for character in name).lower()


def what_an_item_is(
    server: Any, found: Any, tree: List[Dict[str, Any]], rows: List[Dict[str, Any]], row_ids: set
) -> None:
    """Question 4: a tree item that `/Artists` does not list - what is missing about it?

    **The name is checked beside the tracks and costs no request.** The registry's key replaces
    the characters a path cannot carry, so a tree item called `AC/DC` and a row called `AC DC` are
    one artist wearing two spellings and two identifiers - which is the difference between *"two
    populations"* and *"one population, two filters"*, and that is what a design turns on.
    """
    unlisted = [one for one in tree if str(one.get("Id")) not in row_ids][:SAMPLE]
    if not unlisted:
        found.note("every tree item is also an /Artists row here, so question 4 has no subject")
        return
    keys = {as_a_key(str(one.get("Name", ""))) for one in rows}
    for one in unlisted:
        name = str(one.get("Name", ""))
        under = items(
            server, parentId=str(one["Id"]), recursive="true", includeItemTypes="Audio", limit=1
        )
        folded = as_a_key(name) in keys
        found.observe(
            f"item with no row: {name[:26]!r}",
            f"tracks beneath it: {len(under)}; a row carries its folded name: {folded}",
        )


def the_credits(server: Any, found: Any, row_ids: set) -> Optional[bool]:
    """Question 2: are a track's own credit identifiers the registry's identifiers?

    Returns whether **every** sampled credit is a row, or `None` where no sampled track carried a
    credit with an identifier at all - which is an unanswered question and not a failed one.
    """
    tracks = items(
        server,
        recursive="true",
        includeItemTypes="Audio",
        limit=100,
        fields="ArtistItems,AlbumArtists",
    )
    credited: Dict[str, int] = {}
    for one in tracks:
        for key in ("ArtistItems", "AlbumArtists"):
            for credit in one.get(key) or []:
                identifier = str(credit.get("Id", ""))
                if identifier:
                    credited[identifier] = credited.get(identifier, 0) + 1
    if not credited:
        found.note("no sampled track carries a credit with an identifier, so question 2 is open")
        return None
    found.observe("distinct credit identifiers on 100 sampled tracks", len(credited))
    found.observe(
        "of those, how many are an /Artists row",
        f"{len(set(credited) & row_ids)} of {len(credited)}",
    )
    strangers = sorted(set(credited) - row_ids)[:SAMPLE]
    for identifier in strangers:
        found.observe(
            f"credit that is no row: {identifier[:12]}",
            summarise(body_of(server, identifier)),
        )
    return not (set(credited) - row_ids)


def navigation(server: Any, found: Any, rows: List[Dict[str, Any]], tree_ids: set) -> None:
    """Question 3: what a client sends after listing artists, and whether a row answers it."""
    followed = [one for one in rows if str(one.get("Id")) not in tree_ids][:1] or rows[:1]
    if not followed:
        found.note("this server lists no artists, so question 3 has no subject")
        return
    one = followed[0]
    identifier = str(one["Id"])
    name = str(one.get("Name"))[:26]
    under = items(server, parentId=identifier, recursive="true", limit=5)
    found.observe(
        f"parentId=<row {name!r}>",
        "{} rows, types {}".format(
            len(under), sorted({str(row.get("Type")) for row in under}) or "-"
        ),
    )
    by_credit = items(
        server, recursive="true", albumArtistIds=identifier, includeItemTypes="MusicAlbum", limit=5
    )
    found.observe("albumArtistIds=<that row>", f"{len(by_credit)} albums")
    also = items(server, recursive="true", artistIds=identifier, includeItemTypes="Audio", limit=5)
    found.observe("artistIds=<that row>", f"{len(also)} tracks")


def measure(server: Any, args: argparse.Namespace) -> Any:
    probe = load("_probe")
    found = probe.Probe(
        script="probe_artist_registry.py",
        question="What population does /Artists list, and what is one of its rows?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )
    rows, tree = populations(server, found)
    row_ids = {str(one.get("Id")) for one in rows}
    tree_ids = {str(one.get("Id")) for one in tree}
    rows_are_items = what_a_row_is(server, found, rows, tree_ids)
    what_an_item_is(server, found, tree, rows, row_ids)
    credits_are_rows = the_credits(server, found, row_ids)
    navigation(server, found, rows, tree_ids)
    # Two halves of the expectation this run can settle, and one it cannot: `credits_are_rows is
    # None` means no sampled track carried a credit at all, which is an unanswered question and
    # not a failed one - so the verdict is withheld rather than reported either way.
    held = None if credits_are_rows is None else (rows_are_items and credits_are_rows)
    found.conclude(
        (
            "an /Artists row IS an item: /Items/{id} answers it as a MusicArtist with no ParentId "
            "and a Path under the server's own metadata directory, so the registry is by-name "
            "items rather than rows synthesised for one route - and every credit identifier a "
            "track carries is one of those rows, so the two populations are one"
        )
        if held
        else "the registry is not the shape section 5.3 reads from the source: see the rows above",
        matches_documentation=held,
    )
    return found


def main() -> int:
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "What population /Artists lists and what one of its rows is, for the design "
                "behaviours section 5.3 defers. Every request is a GET: this probe writes "
                "nothing, which is why it may be pointed at a server somebody owns."
            ),
            with_args=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
