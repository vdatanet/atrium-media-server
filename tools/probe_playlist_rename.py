#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who can rename a playlist, and through which route?

Asked at the 009 spec review, once the scope decision to bring the rename in had been taken. The
music client renames a playlist with POST /Items/{itemId} `[client-contract: 2026-08-29, section
10]`, and the reference declares that whole controller elevated
`[source: Jellyfin.Api/Controllers/ItemUpdateController.cs @ v10.11.11]` - which would mean the
operation the client actually calls is refused to every user who is not an administrator, on a
stock server, today. A route that only works for one class of user is a different thing to specify
than a route that works, so it is measured rather than read.

The discriminator needs a playlist whose owner is not an administrator, which is why the probe
creates a throwaway user and hands it one: an owner who is refused the rename is the finding, and
an owner who is allowed it means the elevation reads differently on the wire than in the source.

The third row is the route nobody calls. POST /Playlists/{playlistId} - UpdatePlaylist - is not
elevated and tests owner-or-share instead, so if the elevated route refuses the owner then the
reference has two rename paths with opposite permissions, and 009's scope question is which of the
two it is answering.

Writes: creates a throwaway non-administrator user and playlists, and removes them afterwards,
including on failure. It renames nothing that it did not create - POST /Items/{itemId} writes
metadata through the savers, so pointing it at a real library item is not a measurement, it is an
edit.

Usage:
    python3 tools/probe_playlist_rename.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import secrets

from _probe import Probe, ProbeError, Server, main

TMP_USER = "atrium-probe-rename"
NAME = "atrium probe - rename"


def rename_through_items(server: Server, item_id: str, new_name: str, as_user: str) -> tuple:
    """GET the item, change its Name, POST it back - which is what the client does."""
    body = server.get(f"/Items/{item_id}", userId=as_user)
    body["Name"] = new_name
    return server.post_raw(f"/Items/{item_id}", body=body)


def name_of(server: Server, item_id: str, as_user: str) -> str:
    status, _, payload = server.get_raw(f"/Items/{item_id}", userId=as_user)
    if status != 200:
        return f"<{status}>"
    return __import__("json").loads(payload).get("Name", "<no name>")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_rename.py",
        question="who can rename a playlist, and through which route?",
        document="specs/009-playlists/spec.md",
        section="section 2",
        expectation=None,
    )

    if any(user["Name"] == TMP_USER for user in server.get("/Users")):
        raise ProbeError(f"a user called {TMP_USER} already exists - remove it before measuring")

    password = secrets.token_hex(12)
    other_id = server.post("/Users/New", body={"Name": TMP_USER, "Password": password})["Id"]
    created: list = []

    try:
        other = Server(server.base, timeout=server.timeout)
        other.connect(TMP_USER, password, None)

        # -- an administrator renaming their own playlist -------------------------------------
        mine = server.post("/Playlists", body={"Name": NAME, "UserId": server.user_id})["Id"]
        created.append(mine)
        before_path = server.get(f"/Items/{mine}", userId=server.user_id, fields="Path").get("Path")
        status, _, body = rename_through_items(server, mine, NAME + " renamed", server.user_id)
        probe.observe(
            "administrator renames their own, POST /Items/{id}",
            f"{status}  ->  {name_of(server, mine, server.user_id)!r}",
        )
        after = server.get(f"/Items/{mine}", userId=server.user_id, fields="Path")
        moved = after.get("Path")
        probe.observe(
            "  the directory behind it",
            "unchanged" if moved == before_path else f"moved to {moved}",
        )

        # -- a non-administrator renaming a playlist they own themselves ----------------------
        theirs = server.post("/Playlists", body={"Name": NAME + " theirs", "UserId": other_id})[
            "Id"
        ]
        created.append(theirs)
        owner = other.get(f"/Items/{theirs}", userId=other_id).get("OwnerUserId") or "<not shown>"
        probe.observe("the second playlist's owner", f"{owner} (the throwaway user is {other_id})")

        status, _, body = rename_through_items(other, theirs, NAME + " by its owner", other_id)
        probe.observe(
            "its non-administrator owner renames it, POST /Items/{id}",
            f"{status}  {body[:48]!r}  ->  {name_of(other, theirs, other_id)!r}",
        )

        # -- the route nobody calls -----------------------------------------------------------
        status, _, body = other.post_raw(
            f"/Playlists/{theirs}", body={"Name": NAME + " through UpdatePlaylist"}
        )
        probe.observe(
            "the same owner, POST /Playlists/{id}",
            f"{status}  {body[:48]!r}  ->  {name_of(other, theirs, other_id)!r}",
        )
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")
        removed, _, _ = server.delete_raw(f"/Users/{other_id}")
        probe.observe("throwaway user deleted", removed)

    probe.conclude("measured; the two rename routes and who each one admits are in the rows above")
    probe.note(
        "The rename was decided into 009's scope on the strength of a named consumer. What that "
        "consumer calls is the elevated route, so the shape 009 specifies has to say what a "
        "non-administrator owner gets - which is a sentence about a refusal, not about a rename."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
