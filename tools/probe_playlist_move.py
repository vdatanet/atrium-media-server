#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does Move's newIndex refer to the list before or after the entry is removed?

Answers 009 OQ-1, and it is worth answering before implementing rather than after: the two
readings of POST /Playlists/{id}/Items/{entryId}/Move/{newIndex} differ by one position on every
downward move, which looks like a client rendering glitch and is very hard for a client author to
attribute to the server.

The discriminator. With entries [A, B, C, D, E], move A from index 0 to index 3:

    final-index      the entry ends up at index 3 of the resulting list   -> B C D A E
    pre-removal      the entry is inserted before whatever was at index 3 -> B C A D E

Upward moves cannot tell the two apart - moving E from 4 to 1 gives A E B C D either way - which is
why this probe moves downward.

It also checks the premise the question rests on: that a playlist addresses *entries*, not items,
so the same track appearing twice yields two independently addressable rows. That premise is now
measured directly rather than inferred - the probe compares each row's PlaylistItemId with its own
Id, because the reference caches the resolved item's id in the field the response reads from
`[source: MediaBrowser.Controller/Entities/BaseItem.cs:1797-1802 @ v10.11.11]`, and if the two are
equal then 009 section 3.1's whole distinction is a distinction the wire does not make.

Extended at the 009 spec review with the boundary battery OQ-6 asks for. Every one of those cases
is a sentence the specification states without provenance, and the source reads against three of
them: an entry id that is not in the playlist is looked up, not found, logged and returned from
(section 3.5 says 404); the clamp at the end is reached only after an index into the accessible
children, which throws for anything past the count (section 3.5 says "clamped"); and a negative
index has its sign taken off by Math.Max before any of that (section 3.5 says 400).
`[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:307-345 @ v10.11.11]`

Writes: creates one playlist per case and deletes them afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_move.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist move"
DUP_NAME = "atrium probe - playlist entries"
BOUNDARY_NAME = "atrium probe - playlist boundary"

#: A syntactically valid identifier that addresses nothing. Section 3.5 says moving it answers 404;
#: the source says it is looked up after the index arithmetic has already run, which is a different
#: claim about *order* as much as about status - so it is asked at an index in range and again at
#: one out of range.
ABSENT_ENTRY = "0123456789abcdef0123456789abcdef"


def entries(server: Server, playlist_id: str) -> list[tuple[str, str]]:
    """Return [(PlaylistItemId, Name), ...] in playlist order."""
    result = server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id)
    return [
        (item.get("PlaylistItemId", "?"), item.get("Name", "?")) for item in result.get("Items", [])
    ]


def rows(server: Server, playlist_id: str) -> list[dict]:
    """Return the raw item rows in playlist order, for questions about a row's own fields."""
    result = server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id)
    return result.get("Items", [])


def source_items(server: Server, count: int) -> list[dict]:
    """Five items with distinct names, so the resulting order is readable."""
    for item_type in ("Audio", "Movie", "Episode"):
        found = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes=item_type,
            Limit=count * 3,
            SortBy="SortName",
            UserId=server.user_id,
        )
        seen, picked = set(), []
        for item in found.get("Items", []):
            if item["Name"] in seen:
                continue
            seen.add(item["Name"])
            picked.append(item)
            if len(picked) == count:
                return picked
    raise ProbeError(
        f"could not find {count} items with distinct names to build a playlist from; "
        "the library is too small to answer this question"
    )


def boundaries(server: Server, probe: Probe, items: list, created: list) -> None:
    """Section 3.5's table, one fresh playlist per row.

    A fresh playlist per case rather than one playlist moved back and forth: a case whose whole
    question is *did anything move* cannot be measured on a list some earlier case may have left
    in a state nobody predicted.
    """
    labels = "ABCDE"
    by_name = {item["Name"]: labels[i] for i, item in enumerate(items)}

    def fresh(tag: str) -> tuple:
        playlist_id = server.post(
            "/Playlists",
            body={
                "Name": f"{BOUNDARY_NAME} {tag}",
                "Ids": [item["Id"] for item in items],
                "UserId": server.user_id,
            },
        )["Id"]
        created.append(playlist_id)
        return playlist_id, entries(server, playlist_id)

    def order(playlist_id: str) -> str:
        return " ".join(by_name.get(name, "?") for _, name in entries(server, playlist_id))

    # (label, new index, whether to address an entry that is not there)
    cases = (
        ("move A to 4, the last index", 4, False),
        ("move A to 5, one past the end", 5, False),
        ("move A to 6, two past the end", 6, False),
        ("move A to -1", -1, False),
        ("move A to 0, where it already is", 0, False),
        ("absent entry id, index in range", 1, True),
        ("absent entry id, index past the end", 6, True),
    )
    for index, case in enumerate(cases):
        label, new_index, absent = case
        playlist_id, before = fresh(str(index))
        entry = ABSENT_ENTRY if absent else before[0][0]
        status, _, body = server.post_raw(
            f"/Playlists/{playlist_id}/Items/{entry}/Move/{new_index}"
        )
        after = order(playlist_id)
        detail = "" if status < 400 else "   " + repr(body[:70])
        probe.observe(label, f"{status}  ->  {after}{detail}")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_move.py",
        question="does Move's newIndex refer to the list before or after the entry is removed?",
        document="specs/009-playlists/spec.md",
        section="section 3.5",
        expectation=(
            "indices name the entry's position in the list after the move, so moving index 0 to "
            "index 3 of [A B C D E] gives B C D A E"
        ),
    )

    items = source_items(server, 5)
    labels = "ABCDE"
    by_name = {item["Name"]: labels[i] for i, item in enumerate(items)}
    probe.observe(
        "source items", ", ".join(f"{labels[i]}={x['Name'][:28]}" for i, x in enumerate(items))
    )

    created: list[str] = []
    try:
        # -- the premise: are entries addressable, and are duplicates distinct? -----------
        # Creation and addition are separate code paths upstream, so they are probed separately:
        # a server that de-duplicates one may not de-duplicate the other, and the difference
        # decides whether a playlist can hold the same track twice at all.
        dup = server.post(
            "/Playlists",
            body={
                "Name": DUP_NAME,
                "Ids": [items[0]["Id"], items[0]["Id"]],
                "UserId": server.user_id,
            },
        )["Id"]
        created.append(dup)
        on_create = entries(server, dup)
        probe.observe(
            "duplicate on create",
            f"POST /Playlists with the same id twice -> {len(on_create)} entry/entries"
            + ("   <-- de-duplicated" if len(on_create) < 2 else ""),
        )

        server.post(f"/Playlists/{dup}/Items", Ids=items[0]["Id"], UserId=server.user_id)
        on_add = entries(server, dup)
        added = len(on_add) - len(on_create)
        probe.observe(
            "duplicate on add",
            f"POST .../Items with an id already present -> {added} new entry/entries"
            + ("   <-- de-duplicated" if added == 0 else ""),
        )

        distinct = len({entry_id for entry_id, _ in on_add})
        probe.observe("distinct entry ids", f"{distinct} across {len(on_add)} entry/entries")

        # The premise itself, asked of the wire rather than assumed: is a row's PlaylistItemId a
        # value of its own, or the item's own Id under another name? Everything section 3.1 says
        # about entry identity - and the warning that a server accepting either identifier would
        # work by accident - rests on the answer being "a value of its own".
        shown = rows(server, dup)
        same = [row for row in shown if row.get("PlaylistItemId") == row.get("Id")]
        probe.observe(
            "entry id vs item id",
            f"{len(same)} of {len(shown)} row(s) carry PlaylistItemId == Id"
            + ("   <-- the entry id IS the item id" if same else "   <-- distinct, as specified"),
        )

        if len(on_add) >= 2 and distinct == len(on_add):
            server.delete(f"/Playlists/{dup}/Items", EntryIds=on_add[0][0])
            left = entries(server, dup)
            kept_right = len(left) == len(on_add) - 1 and all(e != on_add[0][0] for e, _ in left)
            probe.observe(
                "remove one by entry id",
                f"{len(left)} left, {'the right one' if kept_right else 'THE WRONG ONE'}",
            )
        else:
            probe.observe("remove one by entry id", "not testable - no duplicate survived")

        # -- the question --------------------------------------------------------------------
        playlist = server.post(
            "/Playlists",
            body={
                "Name": NAME,
                "Ids": [item["Id"] for item in items],
                "UserId": server.user_id,
            },
        )["Id"]
        created.append(playlist)

        before = entries(server, playlist)
        if len(before) != 5:
            raise ProbeError(
                f"expected 5 entries after creation, got {len(before)}; the server may be "
                "de-duplicating or expanding the ids, which changes what this probe measures"
            )
        probe.observe("order before", " ".join(by_name.get(n, "?") for _, n in before))

        moved_entry, moved_name = before[0]
        server.post(f"/Playlists/{playlist}/Items/{moved_entry}/Move/3")

        after = entries(server, playlist)
        order = " ".join(by_name.get(n, "?") for _, n in after)
        probe.observe("move index 0 -> 3", order)
        probe.observe("final-index reading", "B C D A E")
        probe.observe("pre-removal reading", "B C A D E")

        ids_preserved = {e for e, _ in before} == {e for e, _ in after}
        probe.observe("entry ids preserved", "yes" if ids_preserved else "NO - ids were reissued")

        # -- OQ-6: the boundaries, which section 3.5 answers in a table with no provenance ----
        boundaries(server, probe, items, created)
    finally:
        for item_id in created:
            try:
                server.delete(f"/Items/{item_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {item_id}; remove it by hand")

    probe.note(
        f"The moved entry is {by_name.get(moved_name, 'A')}. Both readings agree on upward moves, "
        "so only this downward case distinguishes them."
    )
    probe.note(
        "The duplicate rows above are the premise the move question rests on: reordering or "
        "removing 'the second one' is only expressible if entries are addressable independently "
        "of the items they reference. Creation and addition are probed separately because they "
        "are separate code paths upstream."
    )

    if order == "B C A D E":
        probe.conclude(
            "newIndex refers to the list BEFORE the entry is removed: the entry is inserted "
            "before whatever occupied that index originally. specs/009 section 3.5 has said the "
            "opposite since 2026-08-26, so a reading this probe once measured has changed",
            matches_documentation=False,
        )
    elif order == "B C D A E":
        probe.conclude(
            "newIndex refers to the list AFTER the entry is removed: the entry ends up at that "
            "index in the resulting list, which is what section 3.5 has said since this probe "
            "first answered OQ-1 on 2026-08-26",
            matches_documentation=True,
        )
    else:
        probe.conclude(
            f"neither reading: the server produced {order!r}. specs/009 section 3.5 describes a "
            "behaviour the server does not have, and the real rule needs a wider probe",
            matches_documentation=False,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
