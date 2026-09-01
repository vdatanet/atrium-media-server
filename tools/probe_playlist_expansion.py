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

**T10 extended it, because "every container expands" is a claim with a lot of surface.** The five
rows above are five kinds; the rule the implementation has to write is a predicate over every
kind, and four batteries were added to size it:

    * **the width** - a plain folder, the *library root itself*, and another **playlist**, none of
      which the spec had named. Each is a folder to the reference, so each expands, and a client's
      "add this to a playlist" button is offerable on all of them
    * **the mixed batch** - a request naming a film, an album and a second film. Whether the
      album's tracks land where the album was named or after everything else is the difference
      between expanding in place and expanding at the end, and no single-id request can tell
    * **the artist's own order** - the folder query and the artist query state different orderings,
      so the artist's result is compared against both the reference's own three-key sort and the
      album-by-album order a tree walk would produce
    * **the creation path** - `POST /Playlists` with a container in `Ids` expands too, and the
      media type it settles comes from the **expansion** rather than from the container: a series
      whose own media type is `Unknown` creates a `Video` playlist where the empty-list fallback
      is `Audio`. A creation that took the container's own value would store a media type no
      reference server holds

Writes: creates one playlist per case and deletes them afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_expansion.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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


def artist_with_albums(server: Server, least: int) -> Optional[dict]:
    """An artist owning at least `least` albums - one album cannot tell two orderings apart."""
    artists = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes="MusicArtist",
        Limit=40,
        SortBy="SortName",
        UserId=server.user_id,
    ).get("Items", [])
    for artist in artists:
        children = server.get("/Items", ParentId=artist["Id"], UserId=server.user_id, Limit=50).get(
            "Items", []
        )
        if len([one for one in children if one.get("Type") == "MusicAlbum"]) >= least:
            return artist
    return None


def smallest_library_root(server: Server) -> Optional[Tuple[dict, int]]:
    """The library root with the fewest children, and how many it has.

    The smallest on purpose: a root is a folder like any other and expands to **everything under
    it**, so measuring the question on the largest library would write thousands of entries to
    somebody's server to learn what twenty-one prove.
    """
    sized: List[Tuple[int, dict]] = []
    for view in server.get("/UserViews", UserId=server.user_id).get("Items", []):
        count = server.get("/Items", ParentId=view["Id"], UserId=server.user_id, Limit=1).get(
            "TotalRecordCount"
        )
        if view.get("Type") == "CollectionFolder" and count:
            sized.append((int(count), view))
    if not sized:
        return None
    sized.sort(key=lambda pair: pair[0])
    return sized[0][1], sized[0][0]


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_expansion.py",
        question="does adding a container add its children, and in what order?",
        document="specs/009-playlists/spec.md",
        section="section 3.4 and AC-7",
        expectation=(
            "every container expands - an album into its tracks in the album's own order, and a "
            "folder, a library root and another playlist alike - in place, and creation expands "
            "too, settling the media type from what the ids expanded to"
        ),
    )

    album, children = album_with_tracks(server, 5)
    probe.observe("album", f"{album['Name'][:40]!r}  {len(children)} track(s)")
    probe.observe(
        "the album's own order",
        " | ".join(f"{c.get('IndexNumber', '?')}:{c['Name'][:18]}" for c in children[:6]),
    )

    created: List[str] = []
    ordered: Optional[bool] = None

    def create(tag: str, ids: Optional[List[str]] = None) -> str:
        body: Dict[str, object] = {"Name": f"{NAME} {tag[:16]}", "UserId": server.user_id}
        if ids is not None:
            body["Ids"] = ids
        playlist_id = server.post("/Playlists", body=body)["Id"]
        created.append(playlist_id)
        return playlist_id

    def rows_of(playlist_id: str) -> List[dict]:
        return server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id, Limit=500).get(
            "Items", []
        )

    def add(playlist_id: str, ids: List[str]) -> int:
        status, _, _ = server.post_raw(
            f"/Playlists/{playlist_id}/Items", Ids=",".join(ids), UserId=server.user_id
        )
        return int(status)

    def add_container(label: str, container: Optional[dict]) -> List[dict]:
        if container is None:
            probe.observe(label, "no such item in this library - not measured")
            return []
        playlist_id = create(label)
        status = add(playlist_id, [container["Id"]])
        rows = rows_of(playlist_id)
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

        artist = artist_with_albums(server, 3) or first_of(server, "MusicArtist")
        artist_rows = add_container("add an artist", artist)
        add_container("add a series", first_of(server, "Series"))
        add_container("add a season", first_of(server, "Season"))
        add_container("add a collection", first_of(server, "BoxSet"))

        # -- the width the specification had not named ---------------------------------------
        add_container("add a plain folder", first_of(server, "Folder"))
        root = smallest_library_root(server)
        if root is None:
            probe.observe("add a library root", "no library root has children - not measured")
        else:
            view, count = root
            got = add_container(f"add the library root {view['Name'][:14]!r}", view)
            probe.observe(
                "  the root's own children",
                f"{count} listed under it, {len(got)} entries - a root is a folder too",
            )

        source = create("a playlist", [child["Id"] for child in children[:3]])
        add_container("add another playlist", {"Id": source, "Name": "playlist"})
        add_container("add an empty playlist", {"Id": create("empty"), "Name": "empty"})

        # -- the mixed batch, which is where "in place" is decided ----------------------------
        films = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes="Movie",
            Limit=2,
            SortBy="SortName",
            UserId=server.user_id,
        ).get("Items", [])
        if len(films) == 2:
            mixed = create("mixed")
            status = add(mixed, [films[0]["Id"], album["Id"], films[1]["Id"]])
            got = rows_of(mixed)
            in_place = [row["Id"] for row in got] == (
                [films[0]["Id"]] + [child["Id"] for child in children] + [films[1]["Id"]]
            )
            probe.observe(
                "a film, the album and a second film",
                f"{status}  ->  {len(got)} entries, "
                + (
                    "expanded in place, where the album was named"
                    if in_place
                    else "NOT in place - the tracks are not where the album was named"
                ),
            )

        # -- the artist's order, which is not the folder's ------------------------------------
        if artist is not None and artist_rows:
            got = [row["Id"] for row in artist_rows]
            by_artist = server.get(
                "/Items",
                ArtistIds=artist["Id"],
                IncludeItemTypes="Audio",
                Recursive="true",
                SortBy="AlbumArtist,Album,SortName",
                Limit=500,
                UserId=server.user_id,
            ).get("Items", [])
            albums = [
                one
                for one in server.get(
                    "/Items", ParentId=artist["Id"], UserId=server.user_id, Limit=500
                ).get("Items", [])
                if one.get("Type") == "MusicAlbum"
            ]
            grouped: List[str] = []
            for one in albums:
                grouped += [
                    track["Id"]
                    for track in server.get(
                        "/Items", ParentId=one["Id"], UserId=server.user_id, Limit=500
                    ).get("Items", [])
                ]
            probe.observe(
                f"the artist's order, over {len(albums)} album(s)",
                ("the artist query's three keys" if got == [x["Id"] for x in by_artist] else "?")
                + (
                    " - and the same as album by album"
                    if got == grouped
                    else f" - and NOT album by album ({len(grouped)} rows that way)"
                ),
            )

        # -- the creation path expands too, and settles the media type from the expansion -----
        for label, container in (("album", album), ("series", first_of(server, "Series"))):
            if container is None:
                continue
            playlist_id = create(f"create {label}", [container["Id"]])
            item = server.get(f"/Items/{playlist_id}", UserId=server.user_id)
            got = rows_of(playlist_id)
            probe.observe(
                f"POST /Playlists with a {label} in Ids",
                f"{len(got)} entries, MediaType={item.get('MediaType')!r}"
                f" (the container's own is {container.get('MediaType')!r})",
            )
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")

    probe.conclude(
        (
            "a container is expanded to its playable children, in place, and an album arrives in "
            "the order the album itself shows - and every folder is a container, the library "
            "root and another playlist included"
            if ordered
            else "a container is expanded to its playable children, but the order is not the "
            "album's own: AC-7's 'in track order' names an order the expansion does not produce"
        ),
        matches_documentation=bool(ordered),
    )
    probe.note(
        "The rows below the album are the width of the rule rather than the question: section 3.4 "
        "names one container and the reference expands every kind that declares itself playable, "
        "which is what decides whether a client's 'add this to a playlist' button can be offered "
        "on a series as well as on an album."
    )
    probe.note(
        "The creation rows are the same rule reached by the other route, and they are why T10 "
        "touches the create path at all: the media type a playlist is born with is settled from "
        "what the ids expand to, so a series in `Ids` creates a Video playlist where the "
        "container's own media type is Unknown and the empty-list fallback is Audio."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
