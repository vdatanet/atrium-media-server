#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What can a user who does not own a playlist see and do?

Answers 009 OQ-4 and three questions the 009 spec review raised. Section 3.7 states a model with
two classes - the owner, and everybody else if IsPublic - and the reference has three, because a
playlist carries shares that a create body can set. It also states an omission rule for entries the
reader cannot see, and says nothing about the number beside them: the reference filters, and takes
the total from the filtered array `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:538-543
@ v10.11.11]`, so a client paging a playlist is paging a length that differs per reader.

The battery that matters most is the userId one. GET /Playlists/{id}/Items takes the caller's
identity from a query parameter - `var callingUserId = userId ?? User.GetUserId();` - and then
tests the permission against *that* user, where the create and add routes on the same controller
route the same parameter through a helper that refuses a non-administrator naming somebody else
`[source: PlaylistsController.cs:521-531, Jellyfin.Api/Helpers/RequestHelpers.cs:67-85 @
v10.11.11]`. If that reads on the wire the way it reads in the source, a private playlist is
readable by anyone who can name its owner, and AC-12 describes a privacy the reference does not
have.

It also carries a shape battery, added when 009 T2 came to implement the refusal this probe first
measured and found the header missing. A forty-byte slice of a body cannot see a content type and
cannot tell an empty body from a body-less refusal, so every 403 the throwaway user can produce is
printed with its status, its content type, its length and its bytes - one row per layer of the
reference that can refuse: a controller helper, an authorization policy, and a controller's own
test. The answer is that a 403 is two shapes, which behaviours section 1.11 now carries.

Writes: creates a throwaway non-administrator user, whose library access it restricts, and two
playlists. Removes all three afterwards, including on failure. The rename row of the shape battery
posts an item body back, and it does that only to a playlist this probe created.

Usage:
    python3 tools/probe_playlist_visibility.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
import secrets

from _probe import Probe, ProbeError, Server, main

TMP_USER = "atrium-probe-playlists"
PRIVATE = "atrium probe - private playlist"
SHARED = "atrium probe - shared playlist"


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
    ).get("Items", [])
    if len(found) < count:
        raise ProbeError(f"the library has fewer than {count} {item_type} items")
    return found


def status_of(server: Server, path: str, **params) -> str:
    status, _, payload = server.get_raw(path, **params)
    if status == 200:
        return "200"
    return f"{status}  {payload[:40]!r}"


def shape(status: int, headers: dict, payload: bytes) -> str:
    """A refusal's whole observable shape: status, content type, and the body's own length.

    The content type is the cell every earlier reading of this probe left out. `Error processing
    request.` and an empty body are both visible in a 40-byte slice, but *which shape* a refusal
    is depends on the header as much as on the bytes - `text/plain` with no charset is the
    controller's own sentence, and no content type at all is the framework refusing before the
    controller runs. Reading only the body cannot tell those apart when the body is empty.
    """
    content_type = next(
        (value for key, value in headers.items() if key.lower() == "content-type"), None
    )
    return f"{status}  {content_type!r}  {len(payload)} bytes  {payload[:48]!r}"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_visibility.py",
        question="what can a user who does not own a playlist see and do?",
        document="specs/009-playlists/spec.md",
        section="section 3.7, AC-12 and AC-13",
        expectation=(
            "a non-public playlist is invisible to another non-administrator, and entries the "
            "reader cannot see are omitted"
        ),
    )

    if any(user["Name"] == TMP_USER for user in server.get("/Users")):
        raise ProbeError(
            f"a user called {TMP_USER} already exists - an earlier run did not clean up. "
            "Remove it before measuring, so this probe cannot change a real account"
        )

    movies = movies_view(server)
    movie = some(server, "Movie", 1)[0]
    tracks = some(server, "Audio", 2)
    password = secrets.token_hex(12)
    made = server.post("/Users/New", body={"Name": TMP_USER, "Password": password})
    other_id = made["Id"]
    created: list = []

    try:
        policy = server.get(f"/Users/{other_id}")["Policy"]
        policy.update({"EnableAllFolders": False, "EnabledFolders": [movies["Id"]]})
        status, _, body = server.post_raw(f"/Users/{other_id}/Policy", body=policy)
        if status not in (200, 204):
            raise ProbeError(f"could not restrict the throwaway user: {status} {body[:120]!r}")
        probe.observe("throwaway user", f"non-administrator, restricted to {movies['Name']!r} only")

        other = Server(server.base, timeout=server.timeout)
        other.connect(TMP_USER, password, None)

        # -- a private playlist, and a mixed one shared with the throwaway user ---------------
        private_id = server.post(
            "/Playlists",
            body={
                "Name": PRIVATE,
                "Ids": [track["Id"] for track in tracks],
                "UserId": server.user_id,
                "IsPublic": False,
            },
        )["Id"]
        created.append(private_id)

        shared_id = server.post(
            "/Playlists",
            body={
                "Name": SHARED,
                "Ids": [movie["Id"]] + [track["Id"] for track in tracks],
                "UserId": server.user_id,
                "IsPublic": False,
                "Users": [{"UserId": other_id, "CanEdit": True}],
            },
        )["Id"]
        created.append(shared_id)
        owner_rows = server.get(f"/Playlists/{shared_id}/Items", UserId=server.user_id)
        probe.observe(
            "the shared playlist, to its owner",
            f"{owner_rows.get('TotalRecordCount')} of {len(owner_rows.get('Items', []))} shown "
            "(1 movie, 2 tracks)",
        )

        # -- AC-12: is a private playlist invisible? ------------------------------------------
        listed = other.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes="Playlist",
            UserId=other_id,
        ).get("Items", [])
        names = {row["Name"] for row in listed}
        probe.observe(
            "private playlist in the other user's /Items",
            "absent" if PRIVATE not in names else "PRESENT",
        )
        probe.observe(
            "shared playlist in the other user's /Items",
            "present" if SHARED in names else "absent",
        )
        probe.observe(
            "GET /Items/{private} as the other user", status_of(other, f"/Items/{private_id}")
        )
        probe.observe(
            "GET /Playlists/{private}/Items as the other user",
            status_of(other, f"/Playlists/{private_id}/Items"),
        )

        # -- the userId battery: does naming the owner defeat all of that? --------------------
        named = other.get_raw(f"/Playlists/{private_id}/Items", userId=server.user_id)
        status, _, payload = named
        leaked = 0
        if status == 200:
            leaked = len(__import__("json").loads(payload).get("Items", []))
        probe.observe(
            "GET /Playlists/{private}/Items?userId=<the owner> as the other user",
            f"{status}"
            + (
                f"   <-- {leaked} entry/entries of a playlist this user cannot see"
                if status == 200
                else f"  {payload[:40]!r}"
            ),
        )
        add_status, _, add_body = other.post_raw(
            f"/Playlists/{private_id}/Items", ids=tracks[0]["Id"], userId=server.user_id
        )
        probe.observe(
            "POST .../Items?userId=<the owner> as the other user",
            f"{add_status}  {add_body[:40]!r}   <-- the same parameter, the other route",
        )

        # -- the shape battery: is a 403 one shape, or several? -------------------------------
        # Atrium answers every refusal of this class through one exception and one handler, so
        # the question is not what *this* route says but whether the routes that share that
        # handler all say the same thing. Three refusals, three layers of the reference:
        # a controller helper, an authorization policy, and a controller's own test.
        probe.observe(
            "SHAPE  POST /Playlists/{id}/Items?userId=  (a controller helper refuses)",
            shape(
                *other.post_raw(
                    f"/Playlists/{private_id}/Items", ids=tracks[0]["Id"], userId=server.user_id
                )
            ),
        )
        rename_body = other.get(f"/Items/{shared_id}", userId=other_id)
        rename_body["Name"] = SHARED + " renamed"
        probe.observe(
            "SHAPE  POST /Items/{id}  (an elevated controller: the rename the client calls)",
            shape(*other.post_raw(f"/Items/{shared_id}", body=rename_body)),
        )
        probe.observe(
            "SHAPE  GET /Users/{someone else}  (a controller tests the caller itself)",
            shape(*other.get_raw(f"/Users/{server.user_id}")),
        )
        # And the creation route, which takes the same parameter in its *body*. behaviours
        # section 3.16 says `CreatePlaylist` shares the helper that refuses on the add route, and
        # says it from the source rather than from a measurement - so the fourth row asks it. It
        # decides which bytes 009 T8's route answers a body naming somebody else, and it is the
        # only place the parameter arrives as a property rather than as a query.
        stolen, _, stolen_body = other.post_raw(
            "/Playlists", body={"Name": PRIVATE + " stolen", "UserId": server.user_id}
        )
        if stolen == 200 and stolen_body:
            made = json.loads(stolen_body).get("Id")
            if made:
                created.append(made)
        probe.observe(
            "SHAPE  POST /Playlists  {UserId: <the owner>}  (the same helper, in a body)",
            shape(stolen, _, stolen_body),
        )

        # -- OQ-4: the entries the reader cannot see ------------------------------------------
        seen = other.get(f"/Playlists/{shared_id}/Items", UserId=other_id)
        seen_rows = seen.get("Items", [])
        probe.observe(
            "the shared playlist, to the restricted reader",
            f"TotalRecordCount={seen.get('TotalRecordCount')}, {len(seen_rows)} row(s): "
            + ", ".join(row.get("Type", "?") for row in seen_rows),
        )
        # Was the restriction real? A leak is only a leak if the same item is out of reach by
        # every other road, so the two roads a client has are measured beside it.
        probe.observe(
            "  the same track, fetched directly by that reader",
            status_of(other, "/Items/" + tracks[0]["Id"]),
        )
        probe.observe(
            "  Audio items that reader can list at all",
            other.get(
                "/Items", Recursive="true", IncludeItemTypes="Audio", Limit=1, UserId=other_id
            ).get("TotalRecordCount"),
        )
        probe.observe(
            "entry ids unchanged for that reader",
            "yes"
            if all(
                row.get("PlaylistItemId")
                in {r.get("PlaylistItemId") for r in owner_rows.get("Items", [])}
                for row in seen_rows
            )
            else "NO",
        )

        # -- the share from the create body: is it a real editor? -----------------------------
        if seen_rows:
            first_entry = seen_rows[0].get("PlaylistItemId")
            move_status, _, _ = other.post_raw(f"/Playlists/{shared_id}/Items/{first_entry}/Move/1")
            after = server.get(f"/Playlists/{shared_id}/Items", UserId=server.user_id)
            shapes = " ".join(row.get("Type", "?")[:2] for row in after.get("Items", []))
            probe.observe(
                "the shared reader moves an entry to index 1",
                f"{move_status}  ->  owner now sees {shapes}",
            )
        delete_status, _, delete_body = other.delete_raw(f"/Items/{shared_id}")
        probe.observe(
            "the shared reader deletes the playlist",
            f"{delete_status}  {delete_body[:40]!r}   <-- section 3.6 says 403",
        )
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")
        removed, _, _ = server.delete_raw(f"/Users/{other_id}")
        probe.observe("throwaway user deleted", removed)

    probe.conclude(
        "measured; see the userId row, which is the one that decides AC-12",
        matches_documentation=None,
    )
    probe.note(
        "What the playlist route filters on is IsVisible, which is a parental-rating and tag "
        "check `[source: MediaBrowser.Controller/Entities/BaseItem.cs:1736-1741 @ v10.11.11]`. "
        "Library access is enforced by the item queries, not by that call - so an entry from a "
        "library the reader has no access to is not an entry the reader cannot see."
    )
    probe.note(
        "The share was set in the create body, through CreatePlaylistDto's Users - so the third "
        "class of writer is reachable even with /Playlists/{id}/Users out of 009's scope, which "
        "is what makes it a question for section 3.7 rather than for the excluded routes."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
