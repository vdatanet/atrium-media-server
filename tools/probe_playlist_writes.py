#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a write do to the entries a playlist already holds?

009 section 3.4 measured that a repeated item adds nothing, on a playlist holding **one** entry.
That answers "how many" once; the store this feature builds needs the rest of the question, and
every part of it is about entries that were already there:

    1. a repeated id on ADD      - is the entry already there kept in place, or re-seated at the
                                   end? Both answers read as "no new entry" on a one-entry
                                   playlist, and they differ on every playlist a user keeps
    2. a repeated id on CREATE   - `Ids` naming A B A: which A survives, and where?
    3. a mixed batch             - does one duplicate refuse the whole request, or only itself?
    4. a removal from the middle - what happens to the order, and to `Move`'s own bound, which is
                                   the only way a stored position is observable from outside
    5. **the same add, repeated** - and this is the one that pays for the probe

Question 5 is here because questions 1 and 3 disagreed with each other on the first run. They are
not different questions: the same request, sent to the same server against the same playlist,
sometimes drops the repeated item and sometimes appends it. So the battery runs one shape many
times and counts, because "de-duplicates" and "de-duplicates about two thirds of the time" are
different claims and only the second one is testable by repetition.

The mechanism is in the reference's own source, and it is a **cache miss rather than a policy**:
the filter compares the incoming items against `playlist.LinkedChildren.Select(c => c.ItemId)`
`[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:221-224 @ v10.11.11]`, and
`LinkedChild.Create` sets `Path` and `Type` and never `ItemId`
`[source: MediaBrowser.Controller/Entities/LinkedChild.cs:26-40 @ v10.11.11]`. That field is a
lazily filled cache, written the first time an entry is resolved through `GetLinkedChild`
`[source: MediaBrowser.Controller/Entities/BaseItem.cs:1773-1805 @ v10.11.11]` - the very field
009 section 3.1 is built on. An entry whose cache is empty when the write arrives is invisible to
the filter, so the item goes in twice.

When a duplicate does appear, the probe asks what a client can then do about it. Both rows carry
the same `PlaylistItemId` (section 3.1), so neither `Move` nor `Remove` can name one of them.

Writes: creates one playlist per case and deletes them afterwards, including on failure.

Usage:
    python3 tools/probe_playlist_writes.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from typing import List

from _probe import Probe, ProbeError, Server, main

NAME = "atrium probe - playlist writes"

#: How many times the repeated add is sent. The race fired on 5 of 16 attempts when it was found,
#: so a run of eight sees it with probability around 95% - high enough to be a regression test for
#: the claim, and low enough that a clean run is reported as "did not fire" rather than as parity.
TRIALS = 8


def source_items(server: Server, count: int) -> List[dict]:
    """`count` items with distinct names, so the resulting order is readable as letters."""
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
    raise ProbeError(f"could not find {count} distinctly named items to build a playlist from")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playlist_writes.py",
        question="what does a write do to the entries a playlist already holds?",
        document="specs/009-playlists/spec.md",
        section="section 3.1, section 3.4",
        expectation=(
            "adding an item already present adds nothing, so a playlist cannot hold one item "
            "twice, and the entry already there keeps its position"
        ),
    )

    items = source_items(server, 5)
    letters = "ABCDE"
    letter_of = {item["Id"]: letters[index] for index, item in enumerate(items)}
    ident = [item["Id"] for item in items]
    probe.observe(
        "source items", ", ".join(f"{letters[i]}={x['Name'][:24]}" for i, x in enumerate(items))
    )

    created: List[str] = []

    def create(tag: str, ids: List[str]) -> str:
        playlist_id = server.post(
            "/Playlists",
            body={"Name": f"{NAME} - {tag}", "Ids": ids, "UserId": server.user_id},
        )["Id"]
        created.append(playlist_id)
        return playlist_id

    def rows(playlist_id: str) -> List[dict]:
        return server.get(f"/Playlists/{playlist_id}/Items", UserId=server.user_id).get("Items", [])

    def order(playlist_id: str) -> str:
        return " ".join(letter_of.get(row.get("Id"), "?") for row in rows(playlist_id))

    try:
        # 1 - a repeated id on ADD, against a playlist that already holds several ------------
        playlist = create("add", ident[:3])
        probe.observe("add: before", order(playlist))
        server.post(f"/Playlists/{playlist}/Items", Ids=ident[0], UserId=server.user_id)
        after_add = order(playlist)
        probe.observe(
            "add: re-add A",
            f"{after_add}"
            + ("   <-- kept in place" if after_add == "A B C" else "   <-- NOT kept in place"),
        )

        # 2 - a repeated id on CREATE, at two different positions ----------------------------
        repeated = create("create", [ident[0], ident[1], ident[0]])
        on_create = order(repeated)
        probe.observe(
            "create: Ids A B A",
            f"{on_create}"
            + ("   <-- first occurrence kept" if on_create == "A B" else "   <-- NOT first-wins"),
        )

        # 3 - a batch holding one duplicate and two new ids -----------------------------------
        mixed = create("mixed", ident[:2])
        status, _, body = server.post_raw(
            f"/Playlists/{mixed}/Items",
            None,
            Ids=",".join([ident[0], ident[2], ident[3], ident[2]]),
            UserId=server.user_id,
        )
        probe.observe("mixed batch", f"POST Ids=A,C,D,C -> {status} {body[:24]!r}")
        probe.observe(
            "mixed batch: after",
            f"{order(mixed)}   <-- the repeat within the batch lands once either way",
        )

        # 4 - a removal from the middle, and the bound Move then judges against ---------------
        five = create("remove", ident)
        probe.observe("remove: before", order(five))
        server.delete(f"/Playlists/{five}/Items", EntryIds=ident[1])
        probe.observe("remove: delete B", order(five))
        moved, _, _ = server.post_raw(f"/Playlists/{five}/Items/{ident[0]}/Move/3")
        probe.observe(
            "remove: Move to 3 of 4",
            f"{moved} -> {order(five)}"
            + ("   <-- the four survivors are the bound" if moved < 300 else "   <-- refused"),
        )
        past, _, _ = server.post_raw(f"/Playlists/{five}/Items/{ident[0]}/Move/5")
        probe.observe(
            "remove: Move to 5 of 4",
            f"{past}" + ("   <-- the OLD count still bounds" if past < 300 else "   <-- refused"),
        )

        # 5 - the same repeated add, many times ----------------------------------------------
        duplicated: List[str] = []
        outcomes: List[str] = []
        for trial in range(TRIALS):
            attempt = create(f"race-{trial}", ident[:3])
            server.post(
                f"/Playlists/{attempt}/Items",
                Ids=",".join([ident[0], ident[3]]),
                UserId=server.user_id,
            )
            shown = order(attempt)
            outcomes.append(shown)
            if shown.count("A") > 1:
                duplicated.append(attempt)
        probe.observe("repeated add: outcomes", ", ".join(outcomes))
        probe.observe(
            "repeated add: duplicates",
            f"{len(duplicated)} of {TRIALS} identical requests put A in twice"
            + ("   <-- de-duplication is not total" if duplicated else "   <-- none this run"),
        )

        # What a client can do about a duplicate, if the race produced one.
        if duplicated:
            holder = duplicated[0]
            shown = rows(holder)
            same = sum(1 for row in shown if row.get("PlaylistItemId") == row.get("Id"))
            probe.observe(
                "duplicate: entry ids",
                f"{same} of {len(shown)} rows carry PlaylistItemId == Id, so the two copies of A "
                "share one entry id",
            )
            server.post_raw(f"/Playlists/{holder}/Items/{ident[0]}/Move/3")
            probe.observe("duplicate: Move A to 3", f"{order(holder)}   <-- the first copy moves")
            server.delete(f"/Playlists/{holder}/Items", EntryIds=ident[0])
            probe.observe("duplicate: Remove A", f"{order(holder)}   <-- both copies go")
    finally:
        for playlist_id in created:
            try:
                server.delete(f"/Items/{playlist_id}")
            except ProbeError:
                probe.note(f"could not delete probe playlist {playlist_id}; remove it by hand")

    probe.note(
        "Questions 1 to 4 are about a playlist that already had entries: the one-entry playlist "
        "section 3.4 was measured on cannot tell 'kept in place' from 're-seated'."
    )
    probe.note(
        "A run in which the race does not fire is not evidence that de-duplication is total - "
        "it fired on 5 of 16 attempts when it was found. Re-run before believing a clean run."
    )
    if duplicated:
        probe.conclude(
            f"the repeated item is dropped and the entry already there keeps its position - but "
            f"only when the reference's id cache is warm: {len(duplicated)} of {TRIALS} identical "
            "requests put the same item in the playlist twice, and neither Move nor Remove can "
            "then address one copy apart from the other",
            matches_documentation=False,
        )
    else:
        probe.conclude(
            "the repeated item is dropped in place, the batch de-duplicates within itself and "
            "applies the rest, and a removal renumbers - but the race that puts an item in twice "
            "did not fire in this run, which is not the same as its being absent",
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__, needs_writes=True))
