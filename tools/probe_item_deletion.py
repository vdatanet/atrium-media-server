#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does `DELETE /Items/{itemId}` answer, to whom, and in what bytes?

009 spec section 3.6 states four answers and measures one of them: the `401` that refuses a
caller who may not delete, whose body the gate found to be `Unauthorized access` where the
document had said `403`. The other three have never been asked:

- **What a success is.** `204` is stated everywhere and asserted nowhere, and 008 T6 is the
  standing reminder that a route's own documentation is not a measurement.
- **What an unknown or invisible item is.** Section 3.6 says `404` and stops there, which is a
  status and not a shape - the same gap 009 T9 found on the read route, where the answer turned
  out to be the fourth error shape rather than problem details.
- **Which refusal a caller meets first.** Section 3.7's last row says an administrator may delete
  a playlist they neither own nor are shared with. The visibility test and the permission test are
  two different questions, and if the first runs first that row is only reachable on a playlist the
  administrator can *see*, which is exactly the correction 009 T10 had to make to AC-13 one route
  away.

And the identifier: three of 009's four routes bind their id segment differently, so this one is
asked rather than assumed (009 T9, T11).

**The media half of the route is measured only where it refuses.** Section 3.6's divergence exists
because a successful deletion here removes a file the operator owns, so this probe never asks an
account that could succeed. The one media request it sends is from a throwaway user whose
`EnableContentDeletion` is read back from the server as `false` with no per-folder grant, and the
item is fetched again afterwards to prove it survived. If that read-back is not false, the battery
is skipped and says so.

Writes: creates a throwaway non-administrator user and several playlists, deletes the playlists it
created - by design, since deletion is the question - and removes the user afterwards, including
on failure. It never deletes an item it did not create.

Usage:
    python3 tools/probe_item_deletion.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Optional

from _probe import Probe, ProbeError, Server, main

TMP_USER = "atrium-probe-deletion"
PREFIX = "atrium probe - deletion"


def shape(status: int, headers: dict, payload: bytes) -> str:
    """A refusal in full: its status, its content type, its length and its bytes.

    Borrowed from `probe_playlist_visibility.py`, which added it when forty bytes of a body turned
    out not to be able to tell an empty body from a body-less refusal.
    """
    kind = headers.get("Content-Type", "<none>")
    return f"{status} - {kind} - {len(payload)} bytes - {payload[:60]!r}"


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


def exists(server: Server, item_id: str) -> str:
    status, _, _ = server.get_raw(f"/Items/{item_id}", userId=server.user_id)
    return "still there" if status == 200 else f"GONE ({status})"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_item_deletion.py",
        question="what does DELETE /Items/{itemId} answer, to whom, and in what bytes?",
        document="specs/009-playlists/spec.md",
        section="section 3.6, section 3.7, AC-12, AC-13; plan section 6.6",
        expectation=(
            "204 for a playlist the caller may delete - the owner, and any administrator, even on "
            "one they cannot read - 401 with the 21-byte body '\"Unauthorized access\"' for a "
            "playlist they may not delete whether or not they may see it, and 404 only for an "
            "identifier that addresses nothing this caller could reach"
        ),
    )

    if any(user["Name"] == TMP_USER for user in server.get("/Users")):
        raise ProbeError(
            f"a user called {TMP_USER} already exists - an earlier run did not clean up. "
            "Remove it before measuring, so this probe cannot change a real account"
        )

    films = some(server, "Movie", 2)
    tracks = some(server, "Audio", 1)
    movies = movies_view(server)
    password = secrets.token_hex(12)
    made = server.post("/Users/New", body={"Name": TMP_USER, "Password": password})
    other_id = made["Id"]
    created: list = []

    def create(label: str, owner: str, **extra: object) -> Optional[str]:
        body = {
            "Name": f"{PREFIX} {label}",
            "Ids": [film["Id"] for film in films],
            "UserId": owner,
            **extra,
        }
        status, _, payload = server.post_raw("/Playlists", body=body)
        if status != 200 or not payload:
            probe.observe(f"created {label}", f"{status}  {payload[:120]!r}")
            return None
        playlist_id = str(json.loads(payload).get("Id"))
        created.append(playlist_id)
        return playlist_id

    try:
        other = Server(server.base, timeout=server.timeout)
        other.connect(TMP_USER, password, None)

        # -- battery 1: the two successes, and what a success looks like ----------------------
        mine = create("own", server.user_id)
        if mine:
            answer = server.delete_raw(f"/Items/{mine}")
            probe.observe("the owner deletes their own playlist", shape(*answer))
            probe.observe("  and the item afterwards", exists(server, mine))
            created.remove(mine)

        theirs_public = create("theirs public", other_id, IsPublic=True)
        if theirs_public:
            answer = server.delete_raw(f"/Items/{theirs_public}")
            probe.observe("an administrator deletes another user's PUBLIC playlist", shape(*answer))
            probe.observe("  and the item afterwards", exists(server, theirs_public))
            created.remove(theirs_public)

        theirs_shared = create(
            "theirs shared",
            other_id,
            Users=[{"UserId": server.user_id, "CanEdit": False}],
        )
        if theirs_shared:
            answer = server.delete_raw(f"/Items/{theirs_shared}")
            probe.observe("an administrator deletes a playlist SHARED with them", shape(*answer))
            probe.observe("  and the item afterwards", exists(server, theirs_shared))
            created.remove(theirs_shared)

        # -- battery 2: the row spec section 3.7 asserts and nobody has asked -----------------
        theirs_private = create("theirs private", other_id)
        if theirs_private:
            answer = server.delete_raw(f"/Items/{theirs_private}")
            probe.observe(
                "an administrator deletes another user's PRIVATE playlist",
                f"{shape(*answer)}   <-- section 3.7 says an administrator may delete it",
            )
            probe.observe("  and the item afterwards", exists(server, theirs_private))
            created.remove(theirs_private)
            probe.note(
                "Whether that row is reachable at all is the question this battery exists for: "
                "the visibility test and the permission test are two, and only one order lets an "
                "administrator delete a playlist that answers them 404 on every other route."
            )

        # -- battery 3: the refusal, in bytes ------------------------------------------------
        shared_editor = create(
            "shared editor",
            server.user_id,
            Users=[{"UserId": other_id, "CanEdit": True}],
        )
        if shared_editor:
            answer = other.delete_raw(f"/Items/{shared_editor}")
            probe.observe(
                "a share WITH CanEdit deletes the owner's playlist",
                f"{shape(*answer)}   <-- section 3.6 says 401 'Unauthorized access'",
            )
            probe.observe("  and the item afterwards", exists(server, shared_editor))

        public_read = create("public", server.user_id, IsPublic=True)
        if public_read:
            answer = other.delete_raw(f"/Items/{public_read}")
            probe.observe("a public playlist's reader deletes it", shape(*answer))
            probe.observe("  and the item afterwards", exists(server, public_read))

        private_other = create("private of mine", server.user_id)
        if private_other:
            answer = other.delete_raw(f"/Items/{private_other}")
            probe.observe(
                "a stranger deletes a playlist they cannot see",
                f"{shape(*answer)}   <-- 404 and 401 disclose different things",
            )
            probe.observe("  and the item afterwards", exists(server, private_other))

        # -- battery 4: the three classes of identifier, and no credential --------------------
        absent = uuid.uuid4().hex
        probe.observe(
            "an identifier that addresses nothing", shape(*server.delete_raw(f"/Items/{absent}"))
        )
        probe.observe(
            "an identifier that is not one at all",
            shape(*server.delete_raw("/Items/not-an-identifier")),
        )
        probe.observe("an identifier of all zeros", shape(*server.delete_raw(f"/Items/{'0' * 32}")))
        dashed = create("dashed", server.user_id)
        if dashed:
            # Its own playlist, and not one of the rows above: the dashed spelling addresses the
            # same item, so this request deletes whatever it is pointed at.
            probe.observe(
                "an identifier spelled with dashes",
                shape(*server.delete_raw(f"/Items/{uuid.UUID(dashed)!s}")),
            )
            probe.observe("  and the item afterwards", exists(server, dashed))
            created.remove(dashed)
        probe.observe(
            "no credential at all",
            shape(*server.delete_raw(f"/Items/{absent}", send_token=False)),
        )

        # -- battery 5: an item that is not a playlist, from a caller who cannot succeed ------
        policy = server.get(f"/Users/{other_id}")["Policy"]
        deletion = bool(policy.get("EnableContentDeletion"))
        folders = list(policy.get("EnableContentDeletionFromFolders") or [])
        probe.observe(
            "the throwaway user's deletion policy",
            f"EnableContentDeletion={deletion}, EnableContentDeletionFromFolders={folders}",
        )
        if deletion or folders:
            probe.note(
                "SKIPPED the media battery: that account could actually delete a film, and this "
                "probe never sends a request that could remove a file the operator owns."
            )
        else:
            film = films[0]
            answer = other.delete_raw(f"/Items/{film['Id']}")
            probe.observe(
                "that user deletes a film they may not delete",
                f"{shape(*answer)}   <-- Atrium answers 403 here (behaviours section 4.3)",
            )
            probe.observe("  and the film afterwards", exists(server, film["Id"]))
            probe.note(
                "The administrator's own answer on a film is deliberately not measured: it "
                "succeeds, and success removes the operator's file. Section 3.6's divergence is "
                "argued from that consequence rather than from a measurement of it."
            )

        # -- battery 6: is the item lookup filtered by what the caller may open? --------------
        policy.update({"EnableAllFolders": False, "EnabledFolders": [movies["Id"]]})
        status, _, refused = server.post_raw(f"/Users/{other_id}/Policy", body=policy)
        if status not in (200, 204):
            raise ProbeError(f"could not restrict the throwaway user: {status} {refused[:120]!r}")
        probe.observe("throwaway user restricted to", movies["Name"])
        readable = other.get_raw(f"/Items/{tracks[0]['Id']}", userId=other_id)[0]
        probe.observe("  it reads a track of another library", readable)
        answer = other.delete_raw(f"/Items/{tracks[0]['Id']}")
        probe.observe(
            "  it deletes that track",
            f"{shape(*answer)}   <-- 404 says the lookup filters, 401 says only CanDelete does",
        )
        probe.observe("  and the track afterwards", exists(server, tracks[0]["Id"]))
        hidden = create("hidden from the restricted user", server.user_id)
        if hidden:
            probe.observe(
                "  it deletes a private playlist it cannot read",
                shape(*other.delete_raw(f"/Items/{hidden}")),
            )
    finally:
        for playlist_id in created:
            gone, _, _ = server.delete_raw(f"/Items/{playlist_id}")
            if gone != 204:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")
        removed, _, _ = server.delete_raw(f"/Users/{other_id}")
        probe.observe("throwaway user deleted", removed)

    probe.conclude(
        "204 for the owner and for any administrator, including on a private playlist no other "
        "route hands that administrator; 401 with the 21-byte '\"Unauthorized access\"' for every "
        "caller who may not delete, including one who may not read the playlist at all, so this "
        "route discloses a playlist the read routes hide; problem-details 404 for an identifier "
        "that addresses nothing and for media outside the caller's libraries; the binder's "
        "validation 400 for a malformed identifier and the bare-text 400 for one of all zeros",
        matches_documentation=True,
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
