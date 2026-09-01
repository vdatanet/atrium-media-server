#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How wide is a playlist entry row, and what does the read route honour?

Answers 009 spec section 3.3 and plan section 6.5, which between them state the shape of
`GET /Playlists/{playlistId}/Items` in one sentence - "the standard list envelope, with each item
carrying its `PlaylistItemId`" - and never measured the width that sentence assumes.

005 T1 is the reason that is not safe to assume. It found there is **no single item
representation**: a bare `/Items/{itemId}` carries up to 39 properties a bare list row does not,
and `/UserViews` is a third width. A playlist's rows are a width question like any other, and the
only way to know which of the three shapes they are is to ask the same item down both routes and
subtract the two property sets.

Eight questions, all read-only except the playlist this probe creates to have something to read:

1. **Width.** The property set of a playlist row, against the same items as bare `/Items` rows,
   and against the same item's own `/Items/{itemId}` body. A property present on one side and
   absent on the other is either a width difference or a null, so the comparison is over the
   *union* of several rows rather than over one.
2. **`PlaylistItemId`.** On every row, and equal to `Id` - 009 spec section 3.1's whole finding,
   re-asked here because this is the route that emits it. Also: do `/Items` rows carry it?
3. **The envelope.** Which keys, and whether `TotalRecordCount` is the count before paging.
4. **The declared parameters.** `fields`, `enableUserData`, `enableImages` - honoured, or
   decorative? Plan section 6.5 step 4 assumes 005's envelope machinery applies unchanged.
5. **A parameter that is not declared.** `sortBy` was in this spec until the gate removed it.
   Sending it anyway says whether the reference ignores it or refuses it.
6. **No `userId` at all.** The parameter is optional in the schema; what a request without it
   answers decides whether Atrium's `effective_user` default is reachable on this route.
7. **The refusals, in bytes.** Which of behaviours section 1.11's shapes each one is, for an id
   that addresses nothing, an id that addresses a real item which is not a playlist, and an id
   that is not an identifier at all. A `404` reached through a different layer is a different
   body, and this project has been wrong about which layer twice.
8. **Paging past the end**, because a count taken after paging and a count taken before it agree
   on every request except this one.

Writes: creates one playlist and deletes it afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_read.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Set

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist read"

#: How many items go into the probe playlist. Several, because a property that is null on one item
#: is absent from that row and present on the next, and one row cannot tell a width from a null.
ENTRIES = 5

#: A syntactically valid identifier that addresses nothing.
ABSENT = "0123456789abcdef0123456789abcdef"

#: The reference's own sentence, quoted as a complete JSON document: 20 bytes.
ABSENT_BODY = b'"Playlist not found"'


def source_items(server: Server, count: int) -> List[dict]:
    """`count` items of one type, so the two sides of the width comparison are comparable."""
    for item_type in ("Audio", "Movie", "Episode"):
        found = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes=item_type,
            Limit=count,
            SortBy="SortName",
            UserId=server.user_id,
        )
        picked = found.get("Items", [])
        if len(picked) == count:
            return picked
    raise ProbeError(f"could not find {count} items of one type to build a playlist from")


def union_of(rows: List[dict]) -> Set[str]:
    """Every property name any of these rows carries.

    The union rather than the intersection, because the reference omits nulls
    (behaviours section 1.7): a name missing from one row may be gated or may simply be null
    there, and only the union answers "could this route ever send it".
    """
    names: Set[str] = set()
    for row in rows:
        names.update(row.keys())
    return names


def window(envelope: dict) -> str:
    """A paged envelope's three numbers on one line."""
    rows = len(envelope.get("Items", []))
    total = envelope.get("TotalRecordCount")
    start = envelope.get("StartIndex")
    return f"rows={rows} TotalRecordCount={total} StartIndex={start}"


def refusal(status: int, headers: dict, payload: bytes) -> str:
    """A refusal's whole observable shape: status, content type, length and the first bytes.

    The content type is not decoration. Behaviours section 1.11 tells four shapes apart, and two
    of them differ only in the header - an empty body and a body-less refusal read the same in a
    slice of bytes.
    """
    content_type = next(
        (value for key, value in headers.items() if key.lower() == "content-type"), None
    )
    return f"{status}, {content_type!r}, {len(payload)} bytes: {payload[:120]!r}"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_read.py",
        question="how wide is a playlist entry row, and what does the read route honour?",
        document="specs/009-playlists/spec.md",
        section="section 3.3",
        expectation=(
            "the standard list envelope of 005 section 3.1, each row a bare list row carrying "
            "one property more - PlaylistItemId, equal to that row's Id - and the 404 for a "
            "playlist this caller cannot be handed is the JSON-encoded bare string "
            '"Playlist not found", not problem details'
        ),
    )

    items = source_items(server, ENTRIES)
    ident = [item["Id"] for item in items]
    probe.observe("source items", ", ".join(item["Name"][:22] for item in items))

    playlist_id = None
    absent_bodies: Set[bytes] = set()
    try:
        playlist_id = server.post(
            "/Playlists", body={"Name": NAME, "Ids": ident, "UserId": server.user_id}
        )["Id"]

        # 1 - the width -----------------------------------------------------------------------
        envelope = server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id)
        playlist_rows = envelope.get("Items", [])
        listed = server.get(
            "/Items", Ids=",".join(ident), UserId=server.user_id, Recursive="true"
        ).get("Items", [])

        in_playlist = union_of(playlist_rows)
        in_list = union_of(listed)
        extra = sorted(in_playlist - in_list)
        missing = sorted(in_list - in_playlist)
        probe.observe("playlist row properties", len(in_playlist))
        probe.observe("/Items row properties", len(in_list))
        probe.observe("only on the playlist row", ", ".join(extra) or "(none)")
        probe.observe("only on the /Items row", ", ".join(missing) or "(none)")

        full = server.get(f"/Items/{ident[0]}", UserId=server.user_id)
        probe.observe("bare /Items/{itemId} properties", len(full.keys()))
        probe.observe("full body minus playlist row", len(sorted(set(full.keys()) - in_playlist)))

        # 2 - PlaylistItemId ------------------------------------------------------------------
        carried = sum(1 for row in playlist_rows if "PlaylistItemId" in row)
        equal = sum(1 for row in playlist_rows if row.get("PlaylistItemId") == row.get("Id"))
        probe.observe("rows carrying PlaylistItemId", f"{carried}/{len(playlist_rows)}")
        probe.observe("rows where it equals Id", f"{equal}/{len(playlist_rows)}")
        probe.observe(
            "PlaylistItemId on an /Items row",
            "yes" if any("PlaylistItemId" in row for row in listed) else "no",
        )

        # 3 - the envelope --------------------------------------------------------------------
        probe.observe("envelope keys", ", ".join(envelope.keys()))
        probe.observe("TotalRecordCount, unpaged", envelope.get("TotalRecordCount"))
        paged = server.get(
            f"/Playlists/{playlist_id}/Items", UserId=server.user_id, StartIndex=1, Limit=2
        )
        probe.observe("StartIndex=1&Limit=2", window(paged))

        # 4 - the declared parameters ---------------------------------------------------------
        asked: Dict[str, Any] = {"UserId": server.user_id, "Fields": "Path,Overview,DateCreated"}
        with_fields = server.get_where(f"/Playlists/{playlist_id}/Items", asked).get("Items", [])
        gained = sorted(union_of(with_fields) - in_playlist)
        probe.observe("Fields adds", ", ".join(gained) or "(nothing)")
        no_user_data = server.get(
            f"/Playlists/{playlist_id}/Items", UserId=server.user_id, EnableUserData="false"
        ).get("Items", [])
        kept = sum(1 for row in no_user_data if "UserData" in row)
        probe.observe("EnableUserData=false", f"UserData on {kept}/{len(no_user_data)} rows")
        no_images = server.get(
            f"/Playlists/{playlist_id}/Items", UserId=server.user_id, EnableImages="false"
        ).get("Items", [])
        tagged = sum(1 for row in no_images if "ImageTags" in row)
        probe.observe("EnableImages=false", f"ImageTags on {tagged}/{len(no_images)} rows")

        # 5 - a parameter the route does not declare ------------------------------------------
        status, _, _ = server.get_raw(
            f"/Playlists/{playlist_id}/Items",
            UserId=server.user_id,
            SortBy="SortName",
            SortOrder="Descending",
        )
        sorted_rows = server.get(
            f"/Playlists/{playlist_id}/Items",
            UserId=server.user_id,
            SortBy="SortName",
            SortOrder="Descending",
        ).get("Items", [])
        same_order = [row.get("Id") for row in sorted_rows] == [
            row.get("Id") for row in playlist_rows
        ]
        verdict = "unchanged" if same_order else "CHANGED"
        probe.observe("sortBy=SortName&sortOrder=Descending", f"{status}, order {verdict}")

        # 6 - no userId at all -----------------------------------------------------------------
        status, headers, payload = server.get_raw(f"/Playlists/{playlist_id}/Items")
        probe.observe("no userId", refusal(status, headers, payload))
        if status == 200:
            bare = json.loads(payload).get("Items", [])
            with_data = sum(1 for row in bare if "UserData" in row)
            probe.observe("no userId: rows", f"{len(bare)}, UserData on {with_data}")

        # 7 - the refusals -----------------------------------------------------------------
        # Which of behaviours section 1.11's four shapes each one is, in bytes rather than in
        # status alone: this project has been wrong about that twice, and a `404` reached
        # through a different layer is a different body on the wire.
        for label, path in (
            ("unknown playlist id", f"/Playlists/{ABSENT}/Items"),
            ("a real item that is not a playlist", f"/Playlists/{ident[0]}/Items"),
            ("a malformed playlist id", "/Playlists/not-an-identifier/Items"),
        ):
            status, headers, payload = server.get_raw(path, UserId=server.user_id)
            probe.observe(label, refusal(status, headers, payload))
            if status == 404:
                absent_bodies.add(payload)

        # 8 - paging past the end ------------------------------------------------------------
        over = server.get(
            f"/Playlists/{playlist_id}/Items", UserId=server.user_id, StartIndex=99, Limit=2
        )
        probe.observe("StartIndex=99", window(over))
    finally:
        if playlist_id:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")

    width_holds = extra == ["PlaylistItemId"] and not missing and equal == len(playlist_rows)
    refusals_hold = absent_bodies == {ABSENT_BODY}
    if width_holds and refusals_hold:
        probe.conclude(
            "the row is a bare list row plus PlaylistItemId, equal to Id on every row, and the "
            "two ways this route cannot find a playlist are one 20-byte JSON string rather than "
            "problem details - the third, a playlist this reader may not see, is the same body "
            "in probe_playlist_visibility.py, and a malformed id is a 400 that never gets here",
            matches_documentation=True,
        )
    elif width_holds:
        probe.conclude(
            "the width holds - a bare list row plus PlaylistItemId, equal to Id - but the "
            f"refusal bodies are {sorted(absent_bodies)!r} rather than the one measured string",
            matches_documentation=False,
        )
    else:
        probe.conclude(
            f"the row is not a bare list row plus PlaylistItemId: it adds {extra!r} and drops "
            f"{missing!r}, and {equal} of {len(playlist_rows)} rows equal their own Id",
            matches_documentation=False,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__, needs_writes=True))
