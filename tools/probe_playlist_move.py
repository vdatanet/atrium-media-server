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

Extended again at 009 T11 with the battery the *route* needs rather than the arithmetic: what each
of the three path segments accepts. The document types `playlistId` and `itemId` here as bare
strings where the addition on the same path types `playlistId` as a `uuid` `[spec: MoveItem]`, and
that difference is what produced the removal's unhandled `500` - so the same request is asked with
a malformed identifier, an all-zeros one, and the dashed, braced and upper-case spellings of a real
one, on both segments, plus an index that is not a number.

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

from typing import Dict

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist move"
DUP_NAME = "atrium probe - playlist entries"
BOUNDARY_NAME = "atrium probe - playlist boundary"

#: A syntactically valid identifier that addresses nothing. Section 3.5 says moving it answers 404;
#: the source says it is looked up after the index arithmetic has already run, which is a different
#: claim about *order* as much as about status - so it is asked at an index in range and again at
#: one out of range.
ABSENT_ENTRY = "0123456789abcdef0123456789abcdef"

#: The identifier a default-initialised field serialises to, which T10 found is a third class on
#: the add route: refused rather than skipped. Whether this route knows the difference is a
#: question about *its* lookup, and it is asked below rather than carried over.
ALL_ZEROS = "0" * 32

#: Not an identifier at all. The removal route parses its own path segment and answers `500`;
#: whether this route binds or parses is what the battery below settles.
MALFORMED = "not-an-identifier"


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


MATRIX_NAME = "atrium probe - playlist matrix"
ADDRESSING_NAME = "atrium probe - playlist addressing"


def predicted(order: str, source: int, new_index: int) -> str:
    """The post-removal reading, as 009 plan section 6.4 states it, over a caller who sees all.

    Remove the entry, then place it so that it ends at `new_index` of the resulting list. This is
    the model 009 T1 implements; the matrix below exists to find out whether it reproduces the
    reference on every pair or only on the one pair OQ-1 measured.
    """
    remaining = list(order)
    entry = remaining.pop(source)
    if new_index >= len(remaining):
        remaining.append(entry)
    else:
        remaining.insert(new_index, entry)
    return "".join(remaining)


def matrix(server: Server, probe: Probe, items: list, created: list) -> int:
    """Every (source, target) pair on [A B C D E], one fresh playlist per pair.

    009 spec section 6 asks for this matrix as a *test* - "off-by-one errors in reordering pass
    every hand-written case and fail the one nobody wrote" - and then the only pair anybody ever
    measured is 0 -> 3. A 25-row test asserting a model derived from one row is a 25-row test of
    the model, not of the server. Targets run to 5 as well, so the clamp section 3.5 measured for
    source A alone is asked of every source.

    Returns the number of pairs where the reference disagrees with `predicted`.
    """
    labels = "ABCDE"
    by_name = {item["Name"]: labels[i] for i, item in enumerate(items)}
    start = "ABCDE"
    disagreements = 0

    for source in range(5):
        row = []
        for target in range(6):
            playlist_id = server.post(
                "/Playlists",
                body={
                    "Name": f"{MATRIX_NAME} {source}-{target}",
                    "Ids": [item["Id"] for item in items],
                    "UserId": server.user_id,
                },
            )["Id"]
            created.append(playlist_id)
            before = entries(server, playlist_id)
            if len(before) != 5:
                raise ProbeError(f"expected 5 entries, got {len(before)}; the matrix is unreadable")
            status, _, _ = server.post_raw(
                f"/Playlists/{playlist_id}/Items/{before[source][0]}/Move/{target}"
            )
            after = "".join(by_name.get(name, "?") for _, name in entries(server, playlist_id))
            expected = predicted(start, source, target)
            agrees = status < 400 and after == expected
            disagreements += 0 if agrees else 1
            row.append(f"{after}{'' if agrees else f'!={expected}'}({status})")
        probe.observe(f"move {labels[source]} to 0..5", "  ".join(row))

    return disagreements


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


def shape(status: int, headers: Dict[str, str], body: bytes, limit: int = 56) -> str:
    """Status, content type and body, because a status alone is not a shape.

    T9 and T10 both found a route whose refusal status everybody had right and whose *bytes*
    nobody had asked about - the read's twenty-byte `404`, the removal's `500` where the addition
    beside it answers a validation `400`. This route's own refusals are asked the same way.
    """
    kind = headers.get("Content-Type") or "no content type"
    seen = f"{len(body)}B  {body[:limit]!r}" if body else "empty"
    return f"{status}  {kind}  {seen}"


def dashed(value: str) -> str:
    """The other spelling of one identifier - accepted on one segment of this path, not on both."""
    return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"


def addressing(server: Server, probe: Probe, items: list, created: list) -> None:
    """What the three path segments accept, and what each one refuses with.

    The boundary battery above asks about the *arithmetic*; this one asks about the identifiers
    and the index as **text**, which is a different layer and answers a different question. The
    OpenAPI document types this route's `playlistId` and `itemId` as bare strings where the
    addition beside them types `playlistId` as a `uuid` `[spec: MoveItem]`, and that difference is
    exactly what produced the removal's unhandled `500` - so it is asked rather than inferred.

    A fresh playlist per case, for the boundary battery's reason: a case whose whole question is
    *did anything move* cannot be measured on a list an earlier case may have reordered.
    """

    def fresh(tag: str) -> tuple:
        playlist_id = server.post(
            "/Playlists",
            body={
                "Name": f"{ADDRESSING_NAME} {tag}",
                "Ids": [item["Id"] for item in items],
                "UserId": server.user_id,
            },
        )["Id"]
        created.append(playlist_id)
        return playlist_id, [entry for entry, _ in entries(server, playlist_id)]

    film = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes="Movie",
        Limit=1,
        SortBy="SortName",
        UserId=server.user_id,
    ).get("Items", [])

    # -- the playlist segment ----------------------------------------------------------------
    _holder, before = fresh("holder")
    for label, addressed in (
        ("an absent playlist", ABSENT_ENTRY),
        ("an item that is not a playlist", film[0]["Id"] if film else ABSENT_ENTRY),
        ("the all-zeros playlist id", ALL_ZEROS),
        ("a malformed playlist id", MALFORMED),
    ):
        status, headers, body = server.post_raw(f"/Playlists/{addressed}/Items/{before[0]}/Move/1")
        probe.observe(f"move within {label}", shape(status, headers, body))

    # -- the entry segment: three classes of identifier, and four spellings of one -------------
    # The reference parses the playlist segment with the framework's own parser and matches the
    # entry segment by string comparison against the 32-hex form, so the two segments should
    # accept different spellings of one value. Asked rather than inferred: a route that accepted
    # the dashed form where the reference does not would move an entry no reference server moves,
    # which is a difference a client sees in the order it gets back.
    for label, spelling, new_index in (
        ("the all-zeros entry id, index in range", "zeros", 1),
        ("the all-zeros entry id, index past the end", "zeros", 6),
        ("a malformed entry id, index in range", "malformed", 1),
        ("a malformed entry id, index past the end", "malformed", 6),
        ("the entry's own id", "plain", 1),
        ("an upper-case entry id", "upper", 1),
        ("a dashed entry id", "dashed", 1),
        ("a braced entry id", "braced", 1),
    ):
        holder, before = fresh(label[:12])
        addressed = {
            "zeros": ALL_ZEROS,
            "malformed": MALFORMED,
            "plain": before[0],
            "upper": before[0].upper(),
            "dashed": dashed(before[0]),
            "braced": "{" + before[0] + "}",
        }[spelling]
        status, headers, body = server.post_raw(
            f"/Playlists/{holder}/Items/{addressed}/Move/{new_index}"
        )
        landed = [entry for entry, _ in entries(server, holder)]
        probe.observe(
            f"move addressed by {label}",
            shape(status, headers, body)
            + ("  ->  the entry moved" if landed != before else "  ->  nothing moved"),
        )

    # -- the dashed spelling on the *other* segment, which the framework parses ----------------
    holder, before = fresh("dashed-playlist")
    status, headers, body = server.post_raw(f"/Playlists/{dashed(holder)}/Items/{before[0]}/Move/1")
    landed = [entry for entry, _ in entries(server, holder)]
    probe.observe(
        "move within a dashed playlist id",
        shape(status, headers, body)
        + ("  ->  the entry moved" if landed != before else "  ->  nothing moved"),
    )

    # -- the index, which is the one segment the framework binds as a number -------------------
    for label, raw_index in (
        ("a newIndex that is not a number", "banana"),
        ("an empty newIndex", ""),
    ):
        holder, before = fresh(label[:12])
        status, headers, body = server.post_raw(
            f"/Playlists/{holder}/Items/{before[0]}/Move/{raw_index}"
        )
        probe.observe(f"move to {label}", shape(status, headers, body, limit=300))


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

        # -- the three path segments as text, which is a different layer (T11) ---------------
        addressing(server, probe, items, created)

        # -- the matrix section 6 asks for as a test, asked of the server first ---------------
        disagreements = matrix(server, probe, items, created)
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
        "The three path segments bind three different ways. The playlist id is parsed - dashed "
        "addresses the same playlist and malformed is an unhandled 500, as on the removal and "
        "unlike the addition. The entry id is not parsed at all: it is compared as text against "
        "the plain 32-character spelling, so an upper-case one matches and a dashed or braced one "
        "matches nothing, which is also why a malformed or all-zeros entry id is a silent 204 "
        "rather than the refusal the add route makes of it. The index is bound as a number, so a "
        "newIndex that is not one is the binder's validation 400 keyed `newIndex`."
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
    elif order == "B C D A E" and disagreements == 0:
        probe.conclude(
            "newIndex refers to the list AFTER the entry is removed: the entry ends up at that "
            "index in the resulting list, which is what section 3.5 has said since this probe "
            "first answered OQ-1 on 2026-08-26 - and the reading reproduces the reference on all "
            "thirty (source, target) pairs, targets past the end included",
            matches_documentation=True,
        )
    elif order == "B C D A E":
        probe.conclude(
            f"the discriminating pair reads post-removal, as section 3.5 says, but {disagreements} "
            "of the thirty (source, target) pairs do something else: the reading is not the whole "
            "rule and the matrix rows above say where it breaks",
            matches_documentation=False,
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
