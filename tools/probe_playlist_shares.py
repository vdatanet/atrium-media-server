#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which of the playlists a fixture world would seed can a create body actually produce?

009 tasks T5 seeds four playlists into the test world and every task after it asserts against
them: one owned by a user who sees everything, one shared with a restricted user *with* `CanEdit`,
one shared *without* it, and one holding items from two libraries. A fixture is a claim about what
the reference produces, so each of those four is a claim - and three of them have never been
measured.

- **A share without `CanEdit`.** `probe_playlist_visibility.py` measured the `CanEdit: true` form
  and nothing else. AC-14's second half needs the other one to exist: a user who may read a
  playlist and may not reorder it. If the create body drops a `CanEdit: false` share, that class
  of spec section 3.7's table is a row no world can hold.
- **A public playlist.** Spec section 3.7's fourth class is `IsPublic`, and T6's own verification
  wants "the public one present for both" - but no probe has created one, and the four the task
  lists do not include one.
- **A playlist whose entries come from two libraries.** The fixture has to store one `media_type`
  for it (plan section 4.2), and `probe_playlist_media_type.py` measured single-type creations
  only. A body naming a film and a track in one list has never been asked.

Extended at 009 T11 with one row the fixture does not need and the *route* does: when a caller who
may not edit names an index the reference crashes on, which refusal wins. Two refusals are due at
once and the order decides whether Atrium tests the caller before the move arithmetic or after -
deducible from the controller, and this project's habit is to ask.

Writes: creates a throwaway non-administrator user, restricts it to one library, and creates five
playlists. Removes the playlists and the user afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_shares.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Optional

from _probe import Probe, ProbeError, Server, main

TMP_USER = "atrium-probe-shares"
PREFIX = "atrium probe - shares"


def movies_view(server: Server) -> dict:
    for view in server.get("/UserViews", userId=server.user_id).get("Items", []):
        if view.get("CollectionType") == "movies":
            return view
    raise ProbeError("no movies library to restrict the throwaway user to")


def some(server: Server, item_type: str, count: int) -> list:
    found = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes=item_type,
        Limit=count,
        SortBy="SortName",
        UserId=server.user_id,
    )
    items = found.get("Items", [])
    if len(items) < count:
        raise ProbeError(f"the library has only {len(items)} {item_type} items; {count} needed")
    return items


def shape(status: int, headers: dict, payload: bytes) -> str:
    """A refusal in full: its status, its content type, its length and its bytes.

    Borrowed from `probe_playlist_visibility.py`, which added it when a forty-byte slice of a body
    turned out not to be able to tell an empty body from a body-less refusal - the difference
    between the reference's two `403` shapes (behaviours section 1.11).
    """
    kind = headers.get("Content-Type", "<none>")
    return f"{status} - {kind} - {len(payload)} bytes - {payload[:60]!r}"


def media_type_of(server: Server, playlist_id: str) -> str:
    shown = server.get(f"/Items/{playlist_id}", userId=server.user_id)
    return str(shown.get("MediaType", "<absent>"))


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_shares.py",
        question="which of a fixture world's four playlists can a create body actually produce?",
        document="specs/009-playlists/tasks.md",
        section="T5; spec section 3.7, AC-14, AC-15, AC-17; plan section 4.2, section 8",
        expectation=(
            "a share without CanEdit is a reader who cannot reorder, a public playlist is "
            "readable by a second user, and a mixed-library playlist carries one media type"
        ),
    )

    if any(user["Name"] == TMP_USER for user in server.get("/Users")):
        raise ProbeError(
            f"a user called {TMP_USER} already exists - an earlier run did not clean up. "
            "Remove it before measuring, so this probe cannot change a real account"
        )

    movies = movies_view(server)
    films = some(server, "Movie", 3)
    tracks = some(server, "Audio", 2)
    password = secrets.token_hex(12)
    made = server.post("/Users/New", body={"Name": TMP_USER, "Password": password})
    other_id = made["Id"]
    created: list = []

    def create(label: str, body: dict) -> Optional[str]:
        status, _, payload = server.post_raw("/Playlists", body=body)
        if status != 200 or not payload:
            probe.observe(label, f"{status}  {payload[:120]!r}")
            return None
        playlist_id = json.loads(payload).get("Id")
        created.append(playlist_id)
        probe.observe(label, f"{status}  MediaType={media_type_of(server, playlist_id)!r}")
        return playlist_id

    def rows(who: Server, playlist_id: str, as_user: str) -> Any:
        status, _, payload = who.get_raw(f"/Playlists/{playlist_id}/Items", UserId=as_user)
        if status != 200:
            return status, []
        return status, json.loads(payload).get("Items", [])

    try:
        policy = server.get(f"/Users/{other_id}")["Policy"]
        policy.update({"EnableAllFolders": False, "EnabledFolders": [movies["Id"]]})
        status, _, body = server.post_raw(f"/Users/{other_id}/Policy", body=policy)
        if status not in (200, 204):
            raise ProbeError(f"could not restrict the throwaway user: {status} {body[:120]!r}")
        probe.observe("throwaway user", f"non-administrator, restricted to {movies['Name']!r}")

        other = Server(server.base, timeout=server.timeout)
        other.connect(TMP_USER, password, None)

        # -- battery 1: the share that is not an editor ---------------------------------------
        reader_only = create(
            "shared, CanEdit false",
            {
                "Name": f"{PREFIX} 1",
                "Ids": [film["Id"] for film in films],
                "UserId": server.user_id,
                "IsPublic": False,
                "Users": [{"UserId": other_id, "CanEdit": False}],
            },
        )
        editor = create(
            "shared, CanEdit true",
            {
                "Name": f"{PREFIX} 2",
                "Ids": [film["Id"] for film in films],
                "UserId": server.user_id,
                "IsPublic": False,
                "Users": [{"UserId": other_id, "CanEdit": True}],
            },
        )
        for label, playlist_id in (("reader", reader_only), ("editor", editor)):
            if not playlist_id:
                continue
            # Whether the share was stored at all, in the reference's own words.
            stored = server.get_raw(f"/Playlists/{playlist_id}")
            probe.observe(
                f"  {label}: the playlist's own shares",
                f"{stored[0]}  {stored[2][:160]!r}",
            )
            status, seen = rows(other, playlist_id, other_id)
            probe.observe(f"  {label}: reads it as the shared user", f"{status}, {len(seen)} rows")
            if seen:
                moved = other.post_raw(
                    f"/Playlists/{playlist_id}/Items/{seen[0]['PlaylistItemId']}/Move/1"
                )
                after = server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id)
                order = [row["Id"][:4] for row in after.get("Items", [])]
                probe.observe(
                    f"  {label}: moves entry 0 to index 1",
                    f"{shape(*moved)}  ->  owner sees {order}",
                )
                # Which refusal wins when two of them are due at once (009 T11). The index that
                # crashes this route is one the caller may not reach in the first place, and the
                # answer decides whether Atrium tests the caller before the arithmetic or after.
                both = other.post_raw(
                    f"/Playlists/{playlist_id}/Items/{seen[0]['PlaylistItemId']}/Move/9"
                )
                probe.observe(
                    f"  {label}: moves entry 0 to index 9, which is past the end",
                    f"{shape(*both)}   <-- the caller or the index, whichever is judged first",
                )

        # -- battery 2: the public playlist nobody has created --------------------------------
        public = create(
            "public, shared with nobody",
            {
                "Name": f"{PREFIX} 3",
                "Ids": [film["Id"] for film in films],
                "UserId": server.user_id,
                "IsPublic": True,
            },
        )
        if public:
            listed = other.get(
                "/Items", Recursive="true", IncludeItemTypes="Playlist", UserId=other_id
            ).get("Items", [])
            probe.observe(
                "  public: in the other user's /Items",
                "present" if public in {row["Id"] for row in listed} else "ABSENT",
            )
            status, seen = rows(other, public, other_id)
            probe.observe("  public: read by the other user", f"{status}, {len(seen)} rows")
            if seen:
                moved = other.post_raw(
                    f"/Playlists/{public}/Items/{seen[0]['PlaylistItemId']}/Move/1"
                )
                probe.observe(
                    "  public: the other user moves an entry",
                    f"{shape(*moved)}   <-- section 3.7 says a public reader may not",
                )
            deleted = other.delete_raw(f"/Items/{public}")
            probe.observe(
                "  public: the other user deletes it",
                f"{shape(*deleted)}   <-- section 3.6 says 401",
            )

        # -- battery 3: two libraries in one body ---------------------------------------------
        mixed = create(
            "film, track, film, film, track - in that order",
            {
                "Name": f"{PREFIX} 4",
                "Ids": [
                    films[0]["Id"],
                    tracks[0]["Id"],
                    films[1]["Id"],
                    films[2]["Id"],
                    tracks[1]["Id"],
                ],
                "UserId": server.user_id,
                "IsPublic": False,
                "Users": [{"UserId": other_id, "CanEdit": True}],
            },
        )
        track_first = create(
            "track, film - the other order",
            {
                "Name": f"{PREFIX} 5",
                "Ids": [tracks[0]["Id"], films[0]["Id"]],
                "UserId": server.user_id,
            },
        )
        probe.note(
            "The two orders above are the same two libraries: whichever MediaType they answer, "
            "the pair says whether the value follows the first resolvable id or the majority."
        )
        if mixed:
            owner_rows = server.get(f"/Playlists/{mixed}/Items", UserId=server.user_id)
            probe.observe(
                "  mixed: the owner's view",
                " ".join(row["Type"][:2] for row in owner_rows.get("Items", [])),
            )
            status, seen = rows(other, mixed, other_id)
            probe.observe(
                "  mixed: the restricted shared editor's view",
                f"{status}, {len(seen)} rows: " + " ".join(row["Type"][:2] for row in seen),
            )
            if len(seen) > 1:
                moved = other.post_raw(
                    f"/Playlists/{mixed}/Items/{seen[0]['PlaylistItemId']}/Move/1"
                )
                after = server.get(f"/Playlists/{mixed}/Items", UserId=server.user_id)
                probe.observe(
                    "  mixed: that editor moves visible entry 0 to visible index 1",
                    f"{moved[0]}  ->  owner sees "
                    + " ".join(row["Type"][:2] for row in after.get("Items", [])),
                )
        if track_first:
            probe.observe("  the other order's media type", media_type_of(server, track_first))
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")
        removed, _, _ = server.delete_raw(f"/Users/{other_id}")
        probe.observe("throwaway user deleted", removed)

    probe.conclude(
        "measured; the rows that decide the fixture are the CanEdit-false move and the two "
        "mixed-library media types",
        matches_documentation=None,
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
