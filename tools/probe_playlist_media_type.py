#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Is a playlist's `MediaType` a property of its type, of its creation, or of its contents?

009 tasks T3 asks for one value: `Audio`, described as "the reference's own fallback for a
playlist with nothing in it", to be the type-level answer for `Playlist` in the map that gives
every other item type its `MediaType`. 005 wrote the claim this rests on as a comment on that map
- *"a `Playlist` answers `Audio` on the measured server - derived from its contents rather than
from its type"* - and the two halves of that sentence cannot both be the design: a value derived
from contents is not a value a type-level map can hold, and a value fixed at creation is not
derived from contents at all.

009 section 3.2 states the third reading: `MediaType` is *inferred at creation* - `Audio` for an
empty playlist, the media type of the first resolvable id otherwise - and plan section 4.2 stores
it as a column. Nothing has asked what happens **after** creation, which is the cell that decides
whether a stored column can be right: if the answer tracks the contents, then a playlist created
empty and then filled with films answers `Video` on the reference and `Audio` from a column.

Five creation cells and two mutation cells, plus the shape a `Playlist` row carries beside its
media type - `Type`, `IsFolder`, `CollectionType`, `ChildCount` - which is what an item serialiser
has to reproduce, and whether the type is listable at all through `/Items`.

Writes: creates playlists and deletes them afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_media_type.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
from typing import Any, Optional

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist media type"


def one_item(server: Server, item_type: str) -> dict:
    found = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes=item_type,
        Limit=1,
        SortBy="SortName",
        UserId=server.user_id,
    )
    items = found.get("Items", [])
    if not items:
        raise ProbeError(f"the library has no {item_type} to build a playlist from")
    return items[0]


def create(server: Server, body: dict) -> tuple:
    """POST /Playlists, returning (status, created id or None, first bytes of the body)."""
    status, _, payload = server.post_raw("/Playlists", body=body)
    if status != 200 or not payload:
        return status, None, payload[:190]
    return status, json.loads(payload).get("Id"), payload[:70]


def media_type_of(server: Server, playlist_id: str) -> str:
    shown = server.get(f"/Items/{playlist_id}", userId=server.user_id)
    return str(shown.get("MediaType", "<absent>"))


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_media_type.py",
        question="is a playlist's MediaType its type's, its creation's, or its contents'?",
        document="specs/009-playlists/spec.md",
        section="section 3.2, section 4; plan section 4.2",
        expectation=(
            "MediaType is inferred at creation - Audio for an empty playlist, the media type "
            "of the first resolvable id otherwise - and does not change afterwards"
        ),
    )

    track = one_item(server, "Audio")
    movie = one_item(server, "Movie")
    created: list = []

    def attempt(label: str, body: dict, note: Optional[str] = None) -> Any:
        status, playlist_id, payload = create(server, body)
        if playlist_id:
            created.append(playlist_id)
            detail = f"MediaType={media_type_of(server, playlist_id)!r}"
        else:
            detail = repr(payload)
        probe.observe(label, f"{status}  {detail}{'   ' + note if note else ''}")
        return playlist_id

    moved = False
    try:
        # -- what creation decides ------------------------------------------------------------
        empty = attempt("empty, no MediaType", {"Name": NAME + " 1", "UserId": server.user_id})
        attempt(
            "empty, MediaType Video",
            {"Name": NAME + " 2", "MediaType": "Video", "UserId": server.user_id},
        )
        attempt(
            "from a track, no MediaType",
            {"Name": NAME + " 3", "Ids": [track["Id"]], "UserId": server.user_id},
        )
        from_movie = attempt(
            "from a film, no MediaType",
            {"Name": NAME + " 4", "Ids": [movie["Id"]], "UserId": server.user_id},
        )
        attempt(
            "from a film, MediaType Audio",
            {
                "Name": NAME + " 5",
                "Ids": [movie["Id"]],
                "MediaType": "Audio",
                "UserId": server.user_id,
            },
            "<-- does the body win over the contents",
        )
        attempt(
            "empty, MediaType Nonsense",
            {"Name": NAME + " 6", "MediaType": "Nonsense", "UserId": server.user_id},
        )

        # -- and whether it moves afterwards --------------------------------------------------
        if empty:
            server.post(f"/Playlists/{empty}/Items", ids=movie["Id"], userId=server.user_id)
            after = media_type_of(server, empty)
            probe.observe(
                "the empty one, after a film is added",
                f"MediaType={after!r}   <-- Audio means stored, Video means derived",
            )
            moved = after != "Audio"
        if from_movie:
            server.post(f"/Playlists/{from_movie}/Items", ids=track["Id"], userId=server.user_id)
            probe.observe(
                "the film one, after a track is added",
                f"MediaType={media_type_of(server, from_movie)!r}",
            )

        # -- and whether the value is a filter, which is where a type-level answer shows -----
        #
        # `Unknown` is asked alongside the two the documents name, and it is the cell that decides
        # the *shape* of 009 T6's clause. A fix written as "Audio or Video, per row" is a special
        # case over two values; a playlist that answers neither would fall out of it in silence.
        if empty and from_movie:
            for asked in ("Audio", "Video", "Unknown"):
                filtered = server.get(
                    "/Items",
                    Recursive="true",
                    IncludeItemTypes="Playlist",
                    MediaTypes=asked,
                    UserId=server.user_id,
                )
                ids = {row.get("Id") for row in filtered.get("Items", [])}
                probe.observe(
                    f"mediaTypes={asked} over playlists",
                    f"{filtered.get('TotalRecordCount')} rows; the audio one "
                    f"{'in' if empty in ids else 'out'}, the video one "
                    f"{'in' if from_movie in ids else 'out'}",
                )

        # -- and whether the three answers account for every playlist the server holds --------
        #
        # Subtracting two numbers the block above has been printing side by side: if the filtered
        # rows do not add up to the listing, some playlist answers a value creation cannot produce.
        census: dict = {}
        for row in server.get(
            "/Items", Recursive="true", IncludeItemTypes="Playlist", UserId=server.user_id
        ).get("Items", []):
            census[str(row.get("MediaType", "<absent>"))] = (
                census.get(str(row.get("MediaType", "<absent>")), 0) + 1
            )
        probe.observe(
            "every playlist on the server, by MediaType",
            ", ".join(f"{value}: {count}" for value, count in sorted(census.items())),
        )

        # -- the rest of the row, which an item serialiser has to reproduce -------------------
        if empty:
            shown = server.get(f"/Items/{empty}", userId=server.user_id, fields="ChildCount")
            for field in ("Type", "IsFolder", "CollectionType", "ChildCount", "MediaType"):
                probe.observe(f"  bare item {field}", shown.get(field, "<absent>"))
            listed = server.get(
                "/Items",
                Recursive="true",
                IncludeItemTypes="Playlist",
                UserId=server.user_id,
                Fields="ChildCount",
            )
            rows = [row for row in listed.get("Items", []) if row.get("Id") == empty]
            probe.observe(
                "  /Items?includeItemTypes=Playlist",
                f"{listed.get('TotalRecordCount')} rows, this playlist "
                f"{'present' if rows else 'ABSENT'}",
            )
            if rows:
                for field in ("Type", "IsFolder", "CollectionType", "ChildCount", "MediaType"):
                    probe.observe(f"  list row {field}", rows[0].get(field, "<absent>"))
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")

    probe.conclude(
        (
            "a playlist's MediaType follows its contents after creation, so it is not a value a "
            "stored column or a type-level map can hold"
            if moved
            else "a playlist's MediaType is decided at creation and does not move when the "
            "contents do, so a stored column reproduces it"
        ),
        matches_documentation=not moved,
    )
    probe.note(
        "The type-level question is the last block: whatever a Playlist row answers for Type, "
        "IsFolder and CollectionType is what an item serialiser has to produce for a row that no "
        "scan created, and MediaType is the one cell of it that is not constant per type."
    )
    probe.note(
        "Unknown is a third answer, and the census says so: creation cannot produce it - an id "
        "list that resolves to nothing falls back to Audio [source: "
        "Emby.Server.Implementations/Playlists/PlaylistManager.cs:124-126 @ v10.11.11] - but a "
        "playlist the scanner resolves from a directory is given no media type at all [source: "
        "Emby.Server.Implementations/Library/Resolvers/PlaylistResolver.cs:40-45 @ v10.11.11] and "
        "its own file cannot restore one, because Unknown is the one value the saver does not "
        "write [source: MediaBrowser.LocalMetadata/Savers/PlaylistXmlSaver.cs:52-55 @ v10.11.11]. "
        "So mediaTypes= over playlists is a comparison against the stored row, not a two-value "
        "special case."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
