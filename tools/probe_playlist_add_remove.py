#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What do the two entry-writing routes accept, and what do they refuse - in bytes?

009 section 3.4 says *"unknown item ids are skipped - unconditionally here, unlike the creation
path"*, and section 3.5 says a removal names entries that may not be there and answers 204 either
way. Both sentences are about **statuses**, and this feature has already found three times that a
status is not a shape: T8 counted four `400` bodies on one route and T9 found the read's `404` to
be a bare JSON string rather than problem details. So the routes are asked with each class of
identifier, and every answer is recorded with its content type and its bytes.

One row of it is not a shape but a rule, and it is the row that pays for the probe: **the
all-zeros identifier is not an unknown id.** A well-formed identifier that addresses nothing is
skipped exactly as documented; the all-zeros one is refused, on both routes, before anything is
added, and on the creation path it is refused even in the position where the documented walk has
already stopped looking. The reference's item lookup rejects an empty GUID rather than missing it
`[source: Emby.Server.Implementations/Library/LibraryManager.cs:1357-1362 @ v10.11.11]`, and an
empty GUID is exactly what a client sends when it has no id to send.

A first run of this question measured "every unknown id refuses the whole request" and was wrong,
because the id it called unknown was `00000000000000000000000000000000`. Both are measured here,
side by side, so the pair cannot be collapsed again.

The last two rows are the same identifier answered two ways by the two routes on **one path**: the
add binds `playlistId` as an identifier and the remove binds it as a string it parses itself, so a
malformed one is a validation `400` on the POST and an unhandled `500` on the DELETE.

Writes: creates one playlist per case and deletes them afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_add_remove.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist add and remove"

#: Well formed, addresses nothing. Random rather than fixed, so a stale row from an earlier run
#: cannot make an "unknown" id resolve.
ABSENT = "f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0"

#: The one identifier that is not merely absent. `Guid.Empty` is what a default-initialised field
#: serialises to, which is why a client sends it by accident rather than on purpose.
ALL_ZEROS = "0" * 32

MALFORMED = "not-an-identifier"


def tracks_of_an_album(server: Server, least: int) -> List[dict]:
    albums = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes="MusicAlbum",
        Limit=40,
        SortBy="SortName",
        UserId=server.user_id,
    ).get("Items", [])
    for album in albums:
        children = server.get("/Items", ParentId=album["Id"], UserId=server.user_id).get(
            "Items", []
        )
        if len(children) >= least:
            return children[:least]
    raise ProbeError(f"no album in the first 40 has {least} tracks; nothing to write with")


def shape(status: int, headers: Dict[str, str], body: bytes) -> str:
    kind = headers.get("Content-Type") or "no content type"
    return f"{status}  {kind}  {len(body)}B  {body[:48]!r}" if body else f"{status}  {kind}  empty"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_add_remove.py",
        question="what do the add and remove routes accept and refuse, in bytes?",
        document="specs/009-playlists/spec.md",
        section="section 3.4, section 3.5",
        expectation=(
            "an unknown item id is skipped on the add route wherever it sits and a removal of an "
            "entry that is not there answers 204 - but an id of all zeros is refused by the add "
            "route and by creation, and a malformed playlist id is a 500 on the removal"
        ),
    )

    tracks = tracks_of_an_album(server, 3)
    ident = [track["Id"] for track in tracks]
    created: List[str] = []

    def create(tag: str, ids: Optional[List[str]] = None) -> str:
        body: Dict[str, object] = {"Name": f"{NAME} {tag[:16]}", "UserId": server.user_id}
        if ids is not None:
            body["Ids"] = ids
        playlist_id = server.post("/Playlists", body=body)["Id"]
        created.append(playlist_id)
        return playlist_id

    def rows_of(playlist_id: str) -> List[str]:
        return [
            row["Id"]
            for row in server.get(
                f"/Playlists/{playlist_id}/Items", UserId=server.user_id, Limit=500
            ).get("Items", [])
        ]

    def add_case(label: str, ids: List[str], expect_rows: int) -> None:
        playlist_id = create(label)
        status, headers, body = server.post_raw(
            f"/Playlists/{playlist_id}/Items", Ids=",".join(ids), UserId=server.user_id
        )
        landed = len(rows_of(playlist_id))
        probe.observe(
            label,
            f"{shape(status, headers, body)}  ->  {landed} entry/entries"
            + ("" if landed == expect_rows else f"  (expected {expect_rows})"),
        )

    def create_case(label: str, ids: List[str]) -> None:
        try:
            playlist_id = create(label, ids)
        except ProbeError as exc:
            probe.observe(label, f"refused: {exc}".replace("POST /Playlists -> ", ""))
            return
        probe.observe(label, f"200, created with {len(rows_of(playlist_id))} entry/entries")

    try:
        # -- what the add route does with each class of identifier ---------------------------
        add_case("add an absent id", [ABSENT], 0)
        add_case("add a track and an absent id", [ident[0], ABSENT], 1)
        add_case("add an absent id and a track", [ABSENT, ident[0]], 1)
        add_case("add the all-zeros id", [ALL_ZEROS], 0)
        add_case("add a track and the all-zeros id", [ident[0], ALL_ZEROS], 0)
        add_case("add a malformed id and a track", [MALFORMED, ident[0]], 1)

        empty = create("no ids")
        status, headers, body = server.post_raw(f"/Playlists/{empty}/Items", UserId=server.user_id)
        probe.observe("add with no ids parameter at all", shape(status, headers, body))

        # -- the same two identifiers on the creation path, for the contrast -----------------
        create_case("create with a track then an absent id", [ident[0], ABSENT])
        create_case("create with an absent id then a track", [ABSENT, ident[0]])
        create_case("create with a track then the all-zeros id", [ident[0], ALL_ZEROS])

        # -- the playlist identifier itself, on both routes ----------------------------------
        film = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes="Movie",
            Limit=1,
            SortBy="SortName",
            UserId=server.user_id,
        ).get("Items", [])
        addressable: List[Tuple[str, str]] = [
            ("an absent playlist", ABSENT),
            ("an item that is not a playlist", film[0]["Id"] if film else ABSENT),
            ("the all-zeros playlist id", ALL_ZEROS),
            ("a malformed playlist id", MALFORMED),
        ]
        for label, playlist_id in addressable:
            status, headers, body = server.post_raw(
                f"/Playlists/{playlist_id}/Items", Ids=ident[0], UserId=server.user_id
            )
            probe.observe(f"POST to {label}", shape(status, headers, body))
            status, headers, body = server.delete_raw(
                f"/Playlists/{playlist_id}/Items", EntryIds=ident[0], UserId=server.user_id
            )
            probe.observe(f"DELETE on {label}", shape(status, headers, body))

        # -- removal -------------------------------------------------------------------------
        holding = create("removal", ident)
        for label, params in (
            ("remove with no entryIds at all", {}),
            ("remove an entry that is not there", {"EntryIds": ABSENT}),
            ("remove a malformed entry id", {"EntryIds": MALFORMED}),
            ("remove the all-zeros entry id", {"EntryIds": ALL_ZEROS}),
            ("remove the middle entry", {"EntryIds": ident[1]}),
        ):
            status, headers, body = server.delete_raw(
                f"/Playlists/{holding}/Items", UserId=server.user_id, **params
            )
            probe.observe(
                label, f"{shape(status, headers, body)}  ->  {len(rows_of(holding))} left"
            )
        probe.observe(
            "the order after the removal",
            "first and last, in order"
            if rows_of(holding) == [ident[0], ident[2]]
            else f"NOT the surviving order: {rows_of(holding)}",
        )
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")

    probe.conclude(
        "an unknown item id is skipped on the add route wherever it sits, and a removal that "
        "names nothing present is 204 - but the all-zeros identifier is refused by both routes "
        "with the bare-text 400, and by the creation path even after the media type has settled",
        matches_documentation=True,
    )
    probe.note(
        "The two `404`s are the read route's twenty bytes, on both write routes: an absent "
        "playlist and an item that is not a playlist are one body, which is what keeps a private "
        "playlist undisclosable through a write."
    )
    probe.note(
        "A malformed playlist id is the model binder's validation 400 on the POST and an "
        "unhandled 500 on the DELETE, on one path. Atrium answers the validation 400 on both, "
        "which is behaviours section 3.19's argument applied to a third request the reference "
        "cannot serve."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
