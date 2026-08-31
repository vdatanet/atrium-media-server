#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does adding a container to a playlist add the container or its children, and in what order?

Answers 009 OQ-3, and the second half of the question is the one that decides an acceptance
criterion. Section 3.4 says "adding an album adds its tracks" and AC-6 says "in track order" - but
the reference expands a folder through a query that states no ordering at all, while an artist and
a genre are expanded through one that states three keys
`[source: MediaBrowser.Controller/Playlists/Playlist.cs:191-232 @ v10.11.11]`. So "track order" is
a claim about whatever a folder's own default is, and the only way to know whether a client sees
its album in the order the album shows is to ask for both and compare them position by position.

The last row asks the other half of the same rule: item types whose SupportsAddingToPlaylist is
false are dropped after the expansion, so a container that expands to nothing adds nothing and
says so with the same 204 as a container that added forty tracks
`[source: MediaBrowser.Controller/Entities/BaseItem.cs:168 @ v10.11.11]`.

Writes: creates one playlist per container and deletes them afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_expansion.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from typing import Optional

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist expansion"


def album_with_tracks(server: Server, least: int) -> tuple:
    """An album with at least `least` tracks, and the tracks in the order the album shows them."""
    albums = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes="MusicAlbum",
        Limit=40,
        SortBy="SortName",
        UserId=server.user_id,
    ).get("Items", [])
    for album in albums:
        shown = server.get("/Items", ParentId=album["Id"], UserId=server.user_id)
        children = shown.get("Items", [])
        if len(children) >= least:
            return album, children
    raise ProbeError(f"no album in the first 40 has {least} tracks; cannot measure an expansion")


def first_of(server: Server, item_type: str) -> Optional[dict]:
    found = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes=item_type,
        Limit=1,
        SortBy="SortName",
        UserId=server.user_id,
    ).get("Items", [])
    return found[0] if found else None


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_expansion.py",
        question="does adding a container add its children, and in what order?",
        document="specs/009-playlists/spec.md",
        section="section 3.4 and AC-6",
        expectation="adding an album adds its tracks, in track order",
    )

    album, children = album_with_tracks(server, 5)
    probe.observe("album", f"{album['Name'][:40]!r}  {len(children)} track(s)")
    probe.observe(
        "the album's own order",
        " | ".join(f"{c.get('IndexNumber', '?')}:{c['Name'][:18]}" for c in children[:6]),
    )

    created: list = []
    ordered: Optional[bool] = None

    def add_container(label: str, container: Optional[dict]) -> list:
        if container is None:
            probe.observe(label, "no such item in this library - not measured")
            return []
        playlist_id = server.post(
            "/Playlists", body={"Name": f"{NAME} {label[:12]}", "UserId": server.user_id}
        )["Id"]
        created.append(playlist_id)
        status, _, _ = server.post_raw(
            f"/Playlists/{playlist_id}/Items", Ids=container["Id"], UserId=server.user_id
        )
        rows = server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id).get("Items", [])
        kinds = sorted({row.get("Type", "?") for row in rows})
        probe.observe(
            label,
            f"{status}  ->  {len(rows)} entry/entries"
            + (f", all {kinds[0]}" if len(kinds) == 1 else (f", {kinds}" if kinds else "")),
        )
        return rows

    try:
        rows = add_container("add the album", album)
        if rows:
            ordered = [row["Id"] for row in rows] == [child["Id"] for child in children]
            probe.observe(
                "the playlist's order",
                " | ".join(f"{r.get('IndexNumber', '?')}:{r['Name'][:18]}" for r in rows[:6]),
            )
            probe.observe(
                "same order as the album",
                "yes" if ordered else "NO - the expansion reorders the album",
            )
            probe.observe(
                "the container itself",
                "absent, as children only"
                if all(row["Id"] != album["Id"] for row in rows)
                else "PRESENT - the album is an entry of its own",
            )

        add_container("add an artist", first_of(server, "MusicArtist"))
        add_container("add a series", first_of(server, "Series"))
        add_container("add a season", first_of(server, "Season"))
        add_container("add a collection", first_of(server, "BoxSet"))
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")

    probe.conclude(
        (
            "a container is expanded to its playable children, and an album arrives in the "
            "order the album itself shows"
            if ordered
            else "a container is expanded to its playable children, but the order is not the "
            "album's own: AC-6's 'in track order' names an order the expansion does not produce"
        ),
        matches_documentation=bool(ordered),
    )
    probe.note(
        "The rows below the album are the width of the rule rather than the question: section 3.4 "
        "names one container and the reference expands every kind that declares itself playable, "
        "which is what decides whether a client's 'add this to a playlist' button can be offered "
        "on a series as well as on an album."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
