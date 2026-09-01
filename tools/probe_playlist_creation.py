#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does POST /Playlists refuse, and what does it create?

Answers the 009 spec review's questions about the creation route, none of which the specification
cites anything for. Section 3.2 states two refusals and one leniency:

    400 for a missing or empty Name
    ids in Ids that do not exist or are not visible are skipped, not fatal

The source reads against both. There is no name validation anywhere on the route - the name flows
into a filename and then into a directory
`[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:82-83, 130-137 @ v10.11.11]` -
and the leniency is conditional: a request that names no MediaType makes the reference walk the id
list to infer one, throwing on the first id that does not resolve, and stopping as soon as one
does `[source: PlaylistManager.cs:88-121 @ v10.11.11]`. So whether a stale id is fatal depends on
where in the list it sits and on whether the client sent MediaType at all - a distinction section
3.2 does not make, and the music client is the caller that would meet it.

The last battery asks what was created rather than what was refused: the reference builds a
playlist as a directory on disk, which is a thing a client can see through Path and the two date
fields. 009 section 4 calls playlists "the only structural state that does not come from the
filesystem", which is a statement about Atrium; this is the measurement of how much of the
difference reaches the wire.

Writes: creates playlists and deletes them afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_creation.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from typing import Any, Optional

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist creation"

#: Well-formed and addresses nothing. The question is whether an id like this is skipped or fatal,
#: so it has to be syntactically unimpeachable - a malformed one would measure the binder instead.
ABSENT_ID = "ffffffffffffffffffffffffffffffff"


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
        return status, None, payload[:70]
    return status, __import__("json").loads(payload).get("Id"), payload[:70]


def shape(status: int, headers: dict, payload: bytes) -> str:
    """A refusal's whole observable shape: status, content type, length, and the body itself.

    The battery above reads 70 bytes of a body and no headers at all, which is enough to see
    *that* a request was refused and not enough to reproduce the refusal. Both of section 3.2's
    `400`s have to be written as bytes by the route that answers them, and the two are different
    shapes on purpose - one is problem details from the model binder, the other the controller's
    own `text/plain` sentence - so the content type and the whole body are the measurement.

    The body is printed entire rather than sliced: a problem-details `errors` map keys on a
    property name, and which spelling it uses is the cell 007 T8 found the framework getting
    wrong (`item_id`, snake_case, on the wire).
    """
    content_type = next(
        (value for key, value in headers.items() if key.lower() == "content-type"), None
    )
    return f"{status}  {content_type!r}  {len(payload)} bytes  {payload!r}"


def entry_count(server: Server, playlist_id: str) -> int:
    shown = server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id)
    return len(shown.get("Items", []))


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_creation.py",
        question="what does POST /Playlists refuse, and what does it create?",
        document="specs/009-playlists/spec.md",
        section="section 3.2",
        expectation=(
            "400 for a missing or empty Name, and ids that do not exist are skipped rather "
            "than fatal"
        ),
    )

    track = one_item(server, "Audio")
    movie = one_item(server, "Movie")
    created: list = []

    def attempt(label: str, body: dict, note: Optional[str] = None) -> Any:
        status, playlist_id, payload = create(server, body)
        if playlist_id:
            created.append(playlist_id)
            detail = f"created, {entry_count(server, playlist_id)} entry/entries"
        else:
            detail = repr(payload)
        probe.observe(label, f"{status}  {detail}{'   ' + note if note else ''}")
        return playlist_id

    refusals: list = []
    try:
        # -- the name, which section 3.2 says is validated -----------------------------------
        refusals.append(attempt("no Name at all", {"Ids": [], "UserId": server.user_id}))
        refusals.append(attempt('Name = ""', {"Name": "", "UserId": server.user_id}))
        refusals.append(attempt('Name = "   "', {"Name": "   ", "UserId": server.user_id}))

        first = attempt("a plain name", {"Name": NAME, "UserId": server.user_id})
        attempt(
            "the same name again",
            {"Name": NAME, "UserId": server.user_id},
            "<-- a second item, or a refusal",
        )

        # -- the id list, whose leniency the source says is conditional -----------------------
        attempt(
            "one absent id, no MediaType",
            {"Name": NAME + " 1", "Ids": [ABSENT_ID], "UserId": server.user_id},
        )
        attempt(
            "absent id FIRST, no MediaType",
            {"Name": NAME + " 2", "Ids": [ABSENT_ID, track["Id"]], "UserId": server.user_id},
        )
        attempt(
            "absent id LAST, no MediaType",
            {"Name": NAME + " 3", "Ids": [track["Id"], ABSENT_ID], "UserId": server.user_id},
        )
        attempt(
            "absent id FIRST, MediaType Audio",
            {
                "Name": NAME + " 4",
                "Ids": [ABSENT_ID, track["Id"]],
                "MediaType": "Audio",
                "UserId": server.user_id,
            },
        )

        # -- what a created playlist is ------------------------------------------------------
        video = attempt(
            "created from a Movie, no MediaType",
            {"Name": NAME + " 5", "Ids": [movie["Id"]], "UserId": server.user_id},
        )
        if first:
            shown = server.get(
                f"/Items/{first}", userId=server.user_id, fields="Path,DateCreated,ParentId"
            )
            probe.observe("  Type", shown.get("Type"))
            probe.observe("  MediaType", f"{shown.get('MediaType')}   (created with no MediaType)")
            probe.observe("  Path", shown.get("Path", "<absent>"))
            probe.observe("  DateCreated", shown.get("DateCreated", "<absent>"))
            probe.observe("  CanDelete", shown.get("CanDelete"))
            parent_id = shown.get("ParentId")
            if parent_id:
                parent = server.get(f"/Items/{parent_id}", userId=server.user_id)
                probe.observe(
                    "  parent", f"{parent.get('Name')!r}  Type={parent.get('Type')}  {parent_id}"
                )
                views = server.get("/UserViews", userId=server.user_id).get("Items", [])
                in_views = [v for v in views if v.get("Id") == parent_id]
                probe.observe(
                    "  parent in /UserViews",
                    "yes" if in_views else f"no - the {len(views)} views do not include it",
                )
        if video:
            shown_video = server.get(f"/Items/{video}", userId=server.user_id)
            probe.observe("  MediaType from a Movie", shown_video.get("MediaType"))

        # -- the bytes of both refusals, which nothing here had ever read ---------------------
        #
        # Section 3.2's table names two `400` shapes and cites this script for one of them, but
        # every row above prints a 70-byte slice and throws the headers away. A route that has to
        # answer both cannot be written from that: the shapes differ in the content type as much
        # as in the body, and the validation one differs from Atrium's default in the *key* its
        # `errors` map uses.
        probe.observe("-- the shape of each refusal", "status, content type, length, body")
        for label, body in (
            ("no Name at all", {"Ids": [], "UserId": server.user_id}),
            ("Name null", {"Name": None, "UserId": server.user_id}),
            (
                "absent id FIRST, no MediaType",
                {"Name": NAME + " 6", "Ids": [ABSENT_ID], "UserId": server.user_id},
            ),
            (
                "MediaType Nonsense",
                {"Name": NAME + " 7", "MediaType": "Nonsense", "UserId": server.user_id},
            ),
            # The two identifier properties, asked because the answer decides whether Atrium's
            # body model may declare them as identifiers at all: a typed field refuses through
            # the binder, an untyped one lets the id walk of section 3.2 decide.
            (
                "Ids holds a non-identifier",
                {"Name": NAME + " 12", "Ids": ["banana"], "UserId": server.user_id},
            ),
            ("UserId is a non-identifier", {"Name": NAME + " 13", "UserId": "banana"}),
            ("UserId names nobody", {"Name": NAME + " 14", "UserId": ABSENT_ID}),
            # The same refusal with a one-character token. The converter's message carries a byte
            # position, and whether that position is a property of the *request text* or of the
            # token alone decides whether the sentence is reproducible at all: a parser's own
            # offset into the document cannot be, and `len(token) + 2` can.
            ("MediaType X", {"Name": NAME + " 15", "MediaType": "X"}),
        ):
            status, headers, payload = server.post_raw("/Playlists", body=body)
            if status == 200 and payload:
                created.append(__import__("json").loads(payload).get("Id"))
            probe.observe(f"  {label}", shape(status, headers, payload))

        # -- the query form, which the specification says takes precedence --------------------
        #
        # `[spec: CreatePlaylist]` says the four parameters may be sent as query rather than body
        # and that query wins, and section 3.2 repeats it. Nothing has asked whether that is
        # still true of 10.11.11, and it decides whether Atrium's route can require a body at
        # all: a client sending the deprecated form meets a `400` from a server that cannot read
        # it, which is a difference Principle I does not allow.
        status, headers, payload = server.post_raw("/Playlists", body=None, name=NAME + " 8")
        if status == 200 and payload:
            created.append(__import__("json").loads(payload).get("Id"))
        probe.observe("query name, no body", shape(status, headers, payload))
        status, headers, payload = server.post_raw(
            "/Playlists", body={"Name": NAME + " 9 body"}, name=NAME + " 9 query"
        )
        which = None
        if status == 200 and payload:
            which = __import__("json").loads(payload).get("Id")
            created.append(which)
        probe.observe("query and body together", shape(status, headers, payload))
        if which:
            probe.observe(
                "  the name it kept",
                repr(server.get(f"/Items/{which}", userId=server.user_id).get("Name")),
            )
        status, headers, payload = server.post_raw("/Playlists", body=None)
        probe.observe("neither, an empty request", shape(status, headers, payload))
        # Does the query name rescue a body that fails to deserialise? The answer decides *where*
        # Atrium's first refusal sits: if the body is refused before the query is read, the check
        # belongs to the model layer exactly as plan section 6.1 says, and if the query rescues
        # it, the required property is a route-level test over the merged four values.
        status, headers, payload = server.post_raw(
            "/Playlists", body={"Ids": [], "UserId": server.user_id}, name=NAME + " 10"
        )
        if status == 200 and payload:
            created.append(__import__("json").loads(payload).get("Id"))
        probe.observe("query name, body with no Name", shape(status, headers, payload))
        # And the same unbindable token on the query side. behaviours section 1.12 says an
        # unrecognised enum *token* in a query is dropped and answered `200`, where the body's
        # is the `400` measured above - so this is the same value refused two ways on one route.
        status, headers, payload = server.post_raw(
            "/Playlists", body={"Name": NAME + " 11"}, mediaType="Nonsense"
        )
        if status == 200 and payload:
            made = __import__("json").loads(payload).get("Id")
            created.append(made)
            probe.observe(
                "query mediaType Nonsense",
                f"{shape(status, headers, payload)}   MediaType="
                f"{server.get(f'/Items/{made}', userId=server.user_id).get('MediaType')!r}",
            )
        else:
            probe.observe("query mediaType Nonsense", shape(status, headers, payload))
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")

    nameless_refused = all(item is None for item in refusals)
    probe.conclude(
        (
            "the route refuses a missing or empty name"
            if nameless_refused
            else "the route does not validate Name at all: a missing, empty or blank name creates "
            "a playlist. Section 3.2's first error row describes a refusal the reference does not "
            "make, and acceptance criterion 2 asserts it"
        ),
        matches_documentation=nameless_refused,
    )
    probe.note(
        "The id-list rows are the conditional half. Section 3.2 states one rule - unknown ids are "
        "skipped - where the reference has two, split by whether the request names a MediaType, "
        "and the music client sends its playlists' MediaType only sometimes."
    )
    probe.note(
        "Path, DateCreated and the parent are here because the reference's playlist is a "
        "directory in a folder. Whatever of that reaches the wire is what 009 has to decide "
        "about: a value Atrium cannot produce from its own store is a delta a client can read."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
