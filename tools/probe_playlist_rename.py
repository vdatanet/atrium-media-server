#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Who can rename a playlist, through which route, and what does the rest of the body do?

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

**Extended at 009 T13 (2026-09-01), because "applies Name and nothing else" is a claim about a
body with many fields.** The client posts the whole item back, so the route receives every
property the read route emitted, and three questions follow that the first reading never asked:

- **Which of the posted fields the reference actually applies.** One changed property is not a
  measurement of a body that carries forty; a route specified as "only `Name`" has to be checked
  against the ones it is supposed to ignore, and against the ones a client leaves out.
- **How this route binds its identifier.** Three of 009's four routes bind that path segment
  differently and the fourth was asked rather than assumed (T11, T12). This is the fifth, and the
  DELETE beside it on the same path settles nothing about the POST.
- **Which refusal a non-administrator meets first.** An elevated controller refuses before it
  runs, so a caller who is not an administrator should be refused for an item that does not
  exist too - which decides the order the route has to write its checks in.

Writes: creates a throwaway non-administrator user and playlists, and removes them afterwards,
including on failure. It renames nothing that it did not create - POST /Items/{itemId} writes
metadata through the savers, so pointing it at a real library item is not a measurement, it is an
edit. That is why the non-playlist row of 009 plan section 6.6 is *decided* rather than measured:
the request that would measure it is an edit to an item the operator owns.

Usage:
    python3 tools/probe_playlist_rename.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
import secrets
import uuid

from _probe import Probe, ProbeError, Server, main

TMP_USER = "atrium-probe-rename"
NAME = "atrium probe - rename"

#: Properties of the posted body other than `Name`, each given a value nothing else would produce.
#: Every one of them is a real `BaseItemDto` property the read route emits or accepts, so a body
#: carrying them is the body a client that round-trips an item would send.
OTHER_FIELDS = {
    "Overview": "atrium probe overview",
    "SortName": "zzz-atrium-sort",
    "ForcedSortName": "zzz-atrium-forced",
    "OfficialRating": "PG-13",
    "CustomRating": "atrium-custom",
    "ProductionYear": 1997,
    "Genres": ["Atrium Probe Genre"],
    "Tags": ["atrium-probe-tag"],
    "IsFolder": False,
    "Path": "/atrium-probe/not-a-real-path",
}


def shape(status: int, headers: dict, payload: bytes) -> str:
    """A refusal in full: its status, its content type, its length and its bytes.

    Borrowed from `probe_playlist_visibility.py`, which added it when forty bytes of a body turned
    out not to be able to tell an empty body from a body-less refusal.
    """
    kind = next(
        (value for key, value in headers.items() if key.lower() == "content-type"), "<none>"
    )
    return f"{status} - {kind} - {len(payload)} bytes - {payload[:60]!r}"


def rename_through_items(server: Server, item_id: str, new_name: str, as_user: str) -> tuple:
    """GET the item, change its Name, POST it back - which is what the client does."""
    body = server.get(f"/Items/{item_id}", userId=as_user)
    body["Name"] = new_name
    return server.post_raw(f"/Items/{item_id}", body=body)


def fresh(server: Server, created: list, label: str) -> str:
    """A throwaway playlist per battery, so a body that damages one cannot decide the next.

    Added at T13 after the first run: a body the reference accepts can leave the item it names
    unreadable, and a probe that reuses one playlist would attribute that to whichever request
    came next.
    """
    playlist_id = server.post(
        "/Playlists", body={"Name": f"{NAME} - {label}", "UserId": server.user_id}
    )["Id"]
    created.append(playlist_id)
    return playlist_id


def read(server: Server, item_id: str) -> tuple:
    """`GET /Items/{id}` as a status and a body, because after some of these posts there is none."""
    status, _, payload = server.get_raw(f"/Items/{item_id}", userId=server.user_id)
    if status != 200 or not payload:
        return status, None
    return status, json.loads(payload)


def name_of(server: Server, item_id: str, as_user: str) -> str:
    status, _, payload = server.get_raw(f"/Items/{item_id}", userId=as_user)
    if status != 200:
        return f"<{status}>"
    return json.loads(payload).get("Name", "<no name>")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_rename.py",
        question="who can rename a playlist, through which route, and with what body?",
        document="specs/009-playlists/spec.md",
        section="section 3.8",
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

        # -- what the rest of the body does ---------------------------------------------------
        # The client posts the whole item back, so every property below arrives on a rename.
        # Each battery gets a playlist of its own: a body that damages the item would otherwise
        # decide the answer to every question asked after it.
        target = fresh(server, created, "full body")
        full = server.get(f"/Items/{target}", userId=server.user_id)
        probe.observe("the properties a read hands the client", str(len(full)))
        full["Name"] = NAME + " with a full body"
        full.update(OTHER_FIELDS)
        status, headers, body = server.post_raw(f"/Items/{target}", body=full)
        probe.observe("administrator posts a whole item body", shape(status, headers, body))
        read_status, after = read(server, target)
        probe.observe("  the item afterwards", f"GET /Items/{{id}} -> {read_status}")
        if after is not None:
            probe.observe("  Name", f"{after.get('Name')!r}")
            for field, sent in OTHER_FIELDS.items():
                probe.observe(f"  {field}", f"sent {sent!r}  ->  {after.get(field, '<absent>')!r}")

        # -- which properties the body may leave out ------------------------------------------
        # "Applies Name and nothing else" is a claim about a body with thirty-nine properties,
        # and a client that round-trips an item sends all of them. Dropping one at a time is the
        # only way to learn which ones the route cannot do without.
        refused = []
        for field in list(full):
            target = fresh(server, created, f"drop {field}")
            body = {key: value for key, value in full.items() if key != field}
            body["Id"] = target
            body["Name"] = f"{NAME} - dropped {field}"
            status, headers, payload = server.post_raw(f"/Items/{target}", body=body)
            if status != 204:
                read_status, _ = read(server, target)
                refused.append(field)
                probe.observe(
                    f"the body omits {field}",
                    f"{shape(status, headers, payload)}  -  the item afterwards: {read_status}",
                )
        probe.observe("properties the body may not omit", ", ".join(refused) or "none")

        # The same three, present and null rather than absent.
        for field in refused:
            target = fresh(server, created, f"null {field}")
            body = dict(full, Id=target, Name=f"{NAME} - null {field}")
            body[field] = None
            status, headers, payload = server.post_raw(f"/Items/{target}", body=body)
            read_status, _ = read(server, target)
            probe.observe(
                f"the body sends {field}: null",
                f"{shape(status, headers, payload)}  -  the item afterwards: {read_status}",
            )

        # And the smallest body that is accepted, which is the rule stated the other way round.
        target = fresh(server, created, "minimal")
        minimal = {
            "Name": NAME + " from a minimal body",
            "Genres": [],
            "Tags": [],
            "ProviderIds": {},
        }
        status, headers, payload = server.post_raw(f"/Items/{target}", body=minimal)
        probe.observe(
            "a body of exactly Name, Genres, Tags and ProviderIds",
            f"{shape(status, headers, payload)}  ->  {name_of(server, target, server.user_id)!r}",
        )

        # -- the name the route exists to change, and the ways it can be absent ----------------
        for label, mutate in (
            ("absent", lambda body: body.pop("Name", None)),
            ("null", lambda body: body.__setitem__("Name", None)),
            ("empty", lambda body: body.__setitem__("Name", "")),
            ("blank", lambda body: body.__setitem__("Name", "   ")),
        ):
            target = fresh(server, created, f"name {label}")
            body = dict(full, Id=target)
            mutate(body)
            status, headers, payload = server.post_raw(f"/Items/{target}", body=body)
            probe.observe(
                f"a whole body whose Name is {label}",
                f"{shape(status, headers, payload)}  ->  "
                f"{read(server, target)[1].get('Name', '<absent>')!r}",
            )

        # -- what a refused rename leaves behind -----------------------------------------------
        # The refusal is only half of it: the item the request named has to be looked at
        # afterwards, and asked whether anything can put it back.
        target = fresh(server, created, "damage")
        body = {key: value for key, value in full.items() if key != "Genres"}
        body["Id"] = target
        body["Name"] = NAME + " - damaged"
        status, headers, payload = server.post_raw(f"/Items/{target}", body=body)
        probe.observe("a body with no Genres", shape(status, headers, payload))
        probe.observe("  GET /Items/{id} afterwards", shape(*server.get_raw(f"/Items/{target}")))
        listed = server.get("/Items", ids=target, userId=server.user_id)
        probe.observe("  the same item in a listing", f"{listed.get('TotalRecordCount')} row(s)")
        status, headers, payload = server.post_raw(
            f"/Items/{target}", body=dict(full, Id=target, Name=NAME + " - repaired")
        )
        probe.observe("  a whole body posted after it", shape(status, headers, payload))
        probe.observe("  GET /Items/{id} after that", shape(*server.get_raw(f"/Items/{target}")))

        # -- the bodies that are not a rename at all ------------------------------------------
        for label, kwargs in (
            ("nothing but a Name", {"body": {"Name": NAME + " from a bare body"}}),
            ("an empty object", {"body": {}}),
            ("a null Name", {"body": {"Name": None}}),
            ("no body at all", {}),
            ("bytes that are not JSON", {"raw_body": b"{not json"}),
        ):
            target = fresh(server, created, label)
            status, headers, payload = server.post_raw(f"/Items/{target}", **kwargs)
            probe.observe(f"body is {label}", shape(status, headers, payload))
            read_status, after = read(server, target)
            name = after.get("Name") if after is not None else f"<{read_status}>"
            probe.observe("  the name afterwards", repr(name))

        # -- how this route binds its identifier ----------------------------------------------
        # T11 found one 009 route that must not canonicalise its id and T12 found one that binds
        # it as a GUID; the DELETE on this very path is the second. The POST is asked separately.
        addressed = fresh(server, created, "identifiers")
        canonical = addressed.replace("-", "").lower()
        template = server.get(f"/Items/{addressed}", userId=server.user_id)
        spellings = {
            "plain 32 characters": canonical,
            "dashed": str(uuid.UUID(canonical)),
            "braced": "{" + str(uuid.UUID(canonical)) + "}",
            "upper case": canonical.upper(),
            "not an identifier": "not-an-identifier",
            "all zeros": "0" * 32,
            "well formed, unknown": uuid.uuid4().hex,
        }
        for label, spelling in spellings.items():
            marker = f"{NAME} - {label}"
            template["Name"] = marker
            status, headers, body = server.post_raw(f"/Items/{spelling}", body=template)
            applied = name_of(server, addressed, server.user_id) == marker
            probe.observe(
                f"itemId {label}",
                f"{shape(status, headers, body)}  ->  {'renamed' if applied else 'unchanged'}",
            )

        # -- which refusal a non-administrator meets first ------------------------------------
        # An elevated controller is refused before it runs, so the answer should not depend on
        # whether the item exists - and if it does not, the route's checks have an order.
        for label, target in (
            ("a playlist they own", theirs),
            ("a playlist they cannot see", addressed),
            ("an identifier naming nothing", uuid.uuid4().hex),
            ("an identifier that is not one", "not-an-identifier"),
        ):
            status, headers, body = other.post_raw(
                f"/Items/{target}", body={"Name": NAME + " refused"}
            )
            probe.observe(f"non-administrator, {label}", shape(status, headers, body))
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")
        removed, _, _ = server.delete_raw(f"/Users/{other_id}")
        probe.observe("throwaway user deleted", removed)

    probe.conclude(
        "measured; the two rename routes, who each one admits, the three properties a body may "
        "not omit and the seven the route applies beside Name are in the rows above"
    )
    probe.note(
        "The route is not a rename. It applies Overview, ForcedSortName, OfficialRating, "
        "CustomRating, ProductionYear, Genres and Tags as well, and it requires Genres, Tags and "
        "ProviderIds to be present and non-null - so the client's round trip is load-bearing "
        "rather than incidental, and a body carrying only a Name is refused. A body carrying no "
        "Name at all is accepted and erases the one the playlist had."
    )
    probe.note(
        "The rename was decided into 009's scope on the strength of a named consumer. What that "
        "consumer calls is the elevated route, so the shape 009 specifies has to say what a "
        "non-administrator owner gets - which is a sentence about a refusal, not about a rename."
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
