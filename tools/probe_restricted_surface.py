#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How much of the surface answers differently to a restricted non-administrator?

Every probe in this repository authenticates as an administrator, and an administrator lacks no
permission. [009's task list](../specs/009-playlists/tasks.md) hands 010 two comparisons that are
invisible from that seat - a playlist read that names its own reader
([behaviours §3.16](../docs/compatibility/behaviours.md)) and entries a reader cannot reach
([§3.17](../docs/compatibility/behaviours.md)) - and calls them *named* comparisons rather than
sweeps. This probe asks the question behind both: **how many of the surface's reads change their
answer when the caller changes**, and therefore how much of a differential run has to be run twice.

The answer decides a harness requirement, not a behaviour. A run that authenticates once measures
one row of a two-row table, and nothing in the report would say so - a green run as an
administrator is not evidence about anybody else.

The restricted seat is built rather than borrowed: a throwaway non-administrator, restricted to one
library, plus one private playlist holding an item from that library and an item from another. Both
are removed afterwards, including on failure. **Nothing the operator owns is touched.**

Read-only apart from those two, which it creates and deletes.

Usage:
    python3 tools/probe_restricted_surface.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Callable, Dict, List, Optional, Tuple

from _probe import Probe, ProbeError, Server, main

TMP_USER = "atrium-probe-restricted-surface"
PLAYLIST = "atrium probe - restricted surface"

#: A search term short enough to match something on any library and long enough not to match
#: everything. Only the *shape* of the two answers is compared, never the hits themselves.
SEARCH_TERM = "a"


def view_of(server: Server, collection_type: str) -> Optional[Dict[str, Any]]:
    for view in server.get("/UserViews", userId=server.user_id).get("Items", []):
        if view.get("CollectionType") == collection_type:
            return view
    return None


def first_of(server: Server, item_type: str) -> Optional[Dict[str, Any]]:
    rows = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes=item_type,
        Limit=1,
        SortBy="SortName",
        userId=server.user_id,
    ).get("Items", [])
    return rows[0] if rows else None


def summarise(status: int, payload: bytes) -> str:
    """A cell small enough to read in a table and specific enough to see a permission in.

    The row count is the whole signal for the two named comparisons - what a restricted reader is
    shown of a playlist is a *shorter list*, not a different status - so an envelope reports its
    length, and everything else reports its size.
    """
    if status != 200:
        return str(status)
    try:
        body = json.loads(payload)
    except ValueError:
        return f"200, {len(payload)} bytes"
    if isinstance(body, list):
        return f"200, {len(body)} rows"
    if isinstance(body, dict) and "Items" in body:
        return f"200, {len(body['Items'])} rows, total {body.get('TotalRecordCount')}"
    if isinstance(body, dict):
        return f"200, {len(body)} properties"
    return f"200, {len(payload)} bytes"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_restricted_surface.py",
        question="how much of the surface answers differently to a restricted non-administrator?",
        document="specs/010-conformance-harness/spec.md",
        section="section 3.9",
        expectation=(
            "several reads of the surface answer differently to a restricted non-administrator, "
            "including reads that are not refusals but shorter lists, so a differential that "
            "authenticates only as an administrator leaves those rows unmeasured"
        ),
    )

    if any(user["Name"] == TMP_USER for user in server.get("/Users")):
        raise ProbeError(
            f"a user called {TMP_USER} already exists - an earlier run did not clean up. "
            "Remove it before measuring, so this probe cannot change a real account"
        )

    movies = view_of(server, "movies")
    if movies is None:
        raise ProbeError("no movies library to restrict the throwaway user to")
    movie = first_of(server, "Movie")
    track = first_of(server, "Audio")
    if movie is None or track is None:
        raise ProbeError(
            "the library needs at least one movie and one track: the point of the measurement is "
            "one item the restricted user may open and one it may not"
        )

    password = secrets.token_hex(12)
    made = server.post("/Users/New", body={"Name": TMP_USER, "Password": password})
    other_id = str(made["Id"])
    playlist_id: Optional[str] = None

    try:
        policy = server.get(f"/Users/{other_id}")["Policy"]
        policy.update({"EnableAllFolders": False, "EnabledFolders": [movies["Id"]]})
        status, _, body = server.post_raw(f"/Users/{other_id}/Policy", body=policy)
        if status not in (200, 204):
            raise ProbeError(f"could not restrict the throwaway user: {status} {body[:120]!r}")

        playlist_id = str(
            server.post(
                "/Playlists",
                body={
                    "Name": PLAYLIST,
                    "Ids": [movie["Id"], track["Id"]],
                    "UserId": server.user_id,
                    "IsPublic": False,
                },
            )["Id"]
        )

        other = Server(server.base, timeout=server.timeout)
        other.connect(TMP_USER, password, None)

        probe.observe("administrator", "the .env account")
        probe.observe(
            "restricted seat",
            f"non-administrator, {movies['Name']!r} only; playlist holds one item from it "
            f"and one from outside it",
        )

        cases: List[Tuple[str, Callable[[Server], Tuple[int, Dict[str, str], bytes]]]] = [
            ("GET /System/Info/Public", lambda s: s.get_raw("/System/Info/Public")),
            ("GET /System/Info", lambda s: s.get_raw("/System/Info")),
            ("GET /System/Ping", lambda s: s.get_raw("/System/Ping")),
            ("GET /Users/Public", lambda s: s.get_raw("/Users/Public")),
            ("GET /Users/Me", lambda s: s.get_raw("/Users/Me")),
            (
                "GET /Users/{administrator}",
                lambda s: s.get_raw(f"/Users/{server.user_id}"),
            ),
            ("GET /Sessions", lambda s: s.get_raw("/Sessions")),
            ("GET /Localization/Cultures", lambda s: s.get_raw("/Localization/Cultures")),
            ("GET /UserViews", lambda s: s.get_raw("/UserViews", userId=s.user_id)),
            (
                "GET /Items (recursive)",
                lambda s: s.get_raw(
                    "/Items", Recursive="true", Limit=50, SortBy="SortName", userId=s.user_id
                ),
            ),
            (
                "GET /Items/{a film it may open}",
                lambda s: s.get_raw(f"/Items/{movie['Id']}", userId=s.user_id),
            ),
            (
                "GET /Items/{a track it may not}",
                lambda s: s.get_raw(f"/Items/{track['Id']}", userId=s.user_id),
            ),
            ("GET /Items/Latest", lambda s: s.get_raw("/Items/Latest", userId=s.user_id, limit=20)),
            ("GET /Items/Filters", lambda s: s.get_raw("/Items/Filters", userId=s.user_id)),
            ("GET /UserItems/Resume", lambda s: s.get_raw("/UserItems/Resume", userId=s.user_id)),
            ("GET /Shows/NextUp", lambda s: s.get_raw("/Shows/NextUp", userId=s.user_id)),
            ("GET /Artists", lambda s: s.get_raw("/Artists", userId=s.user_id, Limit=50)),
            ("GET /Genres", lambda s: s.get_raw("/Genres", userId=s.user_id, Limit=50)),
            ("GET /MusicGenres", lambda s: s.get_raw("/MusicGenres", userId=s.user_id, Limit=50)),
            ("GET /Years", lambda s: s.get_raw("/Years", userId=s.user_id, Limit=50)),
            (
                "GET /Search/Hints",
                lambda s: s.get_raw(
                    "/Search/Hints", userId=s.user_id, searchTerm=SEARCH_TERM, limit=20
                ),
            ),
            (
                "GET /Playlists/{id}/Items",
                lambda s: s.get_raw(f"/Playlists/{playlist_id}/Items", userId=s.user_id),
            ),
            (
                "GET /Playlists/{id}/Items?userId={owner}",
                lambda s: s.get_raw(f"/Playlists/{playlist_id}/Items", userId=server.user_id),
            ),
        ]

        differing: List[str] = []
        for label, ask in cases:
            mine = summarise(*_answer(ask, server))
            theirs = summarise(*_answer(ask, other))
            if mine != theirs:
                differing.append(label)
            probe.observe(label, f"{mine:34}  ->  {theirs}")

        probe.note(
            "Two of the differing rows are the ones 009 named, and neither is a refusal. The "
            "playlist read that names its owner is answered rather than refused, and the entries "
            "it returns are not filtered by what the reader may open - so the signal is a row "
            "count, which no status-code comparison would see."
        )
        probe.note(
            "The rows that do not differ are as much of the finding as the rows that do: a "
            "harness that runs the whole surface twice pays twice for them. What the second "
            "identity is worth is exactly the differing rows, and it is a measurement rather "
            "than a policy."
        )

        probe.conclude(
            (
                f"{len(differing)} of {len(cases)} read cases answer differently to a restricted "
                f"non-administrator - {', '.join(differing) or 'none'} - so a differential run "
                "under one identity leaves those endpoints unmeasured"
            ),
            matches_documentation=len(differing) > 0,
        )
        return probe
    finally:
        if playlist_id:
            server.delete_raw(f"/Items/{playlist_id}")
        server.delete_raw(f"/Users/{other_id}")


def _answer(
    ask: Callable[[Server], Tuple[int, Dict[str, str], bytes]], who: Server
) -> Tuple[int, bytes]:
    status, _, payload = ask(who)
    return status, payload


if __name__ == "__main__":
    raise SystemExit(
        main(
            run,
            "How much of the surface answers differently to a restricted non-administrator?",
            needs_writes=True,
        )
    )
