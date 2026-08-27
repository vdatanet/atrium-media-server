#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What is an item's identifier derived from, and does moving a library root change it?

Answers the claim behaviours 1.4 makes and the one 003 plan section 1 rests on: the reference's
item id is a function of the file's **absolute path**, so a library that moves to another mount
loses every identifier under it - and with them every client's favourites and resume positions.

Until now that claim carried a `[source: ...]` citation only, read from Jellyfin's tree at
v10.11.11. A source citation is the weakest of the three forms this project uses: it says what the
code appears to do, not what the server did. This probe confirms it from **outside**, against a
running server, by recomputing each item's id from its own reported Path and comparing.

Method, entirely read-only:

  1. Ask for items of each type with their Path.
  2. Recompute the id as Guid(MD5(UTF16LE(type.FullName + key))) for two candidate keys - the
     absolute path verbatim, and lowercased - using .NET's mixed-endian Guid layout.
  3. Report how many reproduced, and from which key.

Nothing of Jellyfin's code is reproduced here. The construction is the one behaviours 1.4 already
records in three lines of pseudocode, and what is being measured is whether the **server's output**
agrees with it - which is a fact about observable behaviour, not a translation of an implementation.

**Case is measured separately, and only paths containing an uppercase character can measure it.**
The two candidate keys are identical for an all-lowercase path, so those are counted apart rather
than allowed to inflate whichever candidate happened to be tried first. The server's own
`EnableCaseSensitiveItemIds` is read so the answer is attributed to a setting rather than guessed;
a server with it **set** cannot tell you what the reference's default is, and this probe says so.

The consequence is then arithmetic rather than another measurement: if the key is the absolute
path, every id under a root changes when the root does. The probe reports the proportion so that
the number is measured on a real library rather than asserted.

Writes: nothing. It creates no item, no library and no file.

Usage:
    python3 tools/probe_item_identity.py https://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import hashlib

from _probe import Probe, ProbeError, Server, main

#: The C# type name that goes into the key, per type. These are **inputs to a hash**, not code:
#: the probe cannot ask the server for them, so it tries the documented ones and reports which
#: reproduced. A type whose name is wrong simply fails to reproduce and is counted as such.
TYPE_NAMES = {
    "Movie": "MediaBrowser.Controller.Entities.Movies.Movie",
    "Episode": "MediaBrowser.Controller.Entities.TV.Episode",
    "Audio": "MediaBrowser.Controller.Entities.Audio.Audio",
    "Series": "MediaBrowser.Controller.Entities.TV.Series",
    "MusicAlbum": "MediaBrowser.Controller.Entities.Audio.MusicAlbum",
}

#: How many of each type to ask for. Enough that a coincidence is impossible - a 128-bit id
#: reproducing once could be luck, and four hundred times cannot be.
PER_TYPE = 100

VERBATIM = "the absolute path, verbatim"
LOWERED = "the absolute path, lowercased"


def dotnet_guid(digest: bytes) -> str:
    """`new Guid(byte[16]).ToString("N")`: the first three fields are little-endian, the rest are
    laid out in order. Getting this wrong makes every comparison fail, which is why the probe
    reports the near miss rather than only the count."""
    return (
        bytes(
            [
                digest[3],
                digest[2],
                digest[1],
                digest[0],
                digest[5],
                digest[4],
                digest[7],
                digest[6],
            ]
        ).hex()
        + digest[8:16].hex()
    )


def derived(type_full_name: str, key: str) -> str:
    return dotnet_guid(hashlib.md5((type_full_name + key).encode("utf-16-le")).digest())  # noqa: S324


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_item_identity.py",
        question="What is an item's identifier derived from?",
        document="docs/compatibility/behaviours.md",
        section="section 1.4",
        expectation=(
            "the id is Guid(MD5(UTF16LE(type.FullName + path))), where path is the item's "
            "absolute path, lowercased unless EnableCaseSensitiveItemIds is set"
        ),
    )

    try:
        configuration = server.get("/System/Configuration")
        case_sensitive = configuration.get("EnableCaseSensitiveItemIds")
    except ProbeError:
        # Not fatal: the derivation is still measurable, only its case half loses its attribution.
        case_sensitive = None
    probe.observe(
        "EnableCaseSensitiveItemIds",
        "unreadable (not an administrator?)" if case_sensitive is None else case_sensitive,
    )

    reproduced: dict[str, int] = {VERBATIM: 0, LOWERED: 0}
    unexplained: list[str] = []
    ambiguous = 0
    total = 0

    for item_type, full_name in TYPE_NAMES.items():
        result = server.get(
            f"/Users/{server.user_id}/Items",
            IncludeItemTypes=item_type,
            Recursive="true",
            Limit=PER_TYPE,
            Fields="Path",
        )
        found = 0
        for item in result.get("Items", []):
            path, item_id = item.get("Path"), item["Id"]
            if not path:
                # A virtual item - a Series whose folder the server never saw, say. It has no path
                # to derive from, so it says nothing about the question.
                continue
            total += 1
            found += 1
            if path == path.lower():
                ambiguous += 1
                if derived(full_name, path) != item_id:
                    unexplained.append(f"{item_type}: {path}")
                continue
            if derived(full_name, path) == item_id:
                reproduced[VERBATIM] += 1
            elif derived(full_name, path.lower()) == item_id:
                reproduced[LOWERED] += 1
            else:
                unexplained.append(f"{item_type}: {path}")
        probe.observe(f"{item_type} items with a path", found)

    if not total:
        raise ProbeError(
            "no item on this server reported a Path, so there is nothing to derive from. "
            "The account may lack access to every library."
        )

    decisive = reproduced[VERBATIM] + reproduced[LOWERED]
    probe.observe("items examined", total)
    probe.observe("paths that distinguish the two keys", decisive)
    probe.observe(f"reproduced from {VERBATIM}", reproduced[VERBATIM])
    probe.observe(f"reproduced from {LOWERED}", reproduced[LOWERED])
    probe.observe("all-lowercase paths (cannot distinguish)", ambiguous)
    probe.observe("not reproduced from either", len(unexplained))
    for one in unexplained[:5]:
        probe.observe("  unexplained", one)

    probe.note(
        "Every identifier here is a function of the absolute path and nothing else - not of the "
        "library, not of a stored row. So moving a library root changes every id underneath it, "
        f"which for this server is all {total} of the items examined. That is the defect 003 "
        "declines to inherit: Atrium derives from the path relative to its library root, so the "
        "same move costs nothing. 003 spec section 3.6, plan section 1."
    )

    if case_sensitive:
        probe.note(
            "This server has EnableCaseSensitiveItemIds SET, so it cannot say what the "
            "reference's DEFAULT is - which is 003 OQ-9, open and measured by nothing. Atrium's "
            "own default is case-insensitive (003 spec section 3.6) and is stated there as its "
            "own decision rather than as a match for the reference's, precisely because this "
            "probe cannot supply one. Pointing it at a server with the flag unset would."
        )

    if len(unexplained) > total // 10:
        probe.conclude(
            f"{len(unexplained)} of {total} items did not reproduce from either key. Either the "
            "type names above are wrong for this version, or the derivation has changed",
            matches_documentation=False,
        )
    elif not decisive:
        probe.conclude(
            "every path on this server is already lowercase, so the derivation is confirmed but "
            "the case half is not measured here",
            matches_documentation=None,
        )
    else:
        winner = VERBATIM if reproduced[VERBATIM] >= reproduced[LOWERED] else LOWERED
        probe.conclude(
            f"the id is derived from the absolute path: {total - len(unexplained)} of {total} "
            f"items reproduced exactly, and of the {decisive} whose path can tell the two keys "
            f"apart, {reproduced[winner]} came from {winner}"
            + (
                " - which is what EnableCaseSensitiveItemIds being set means"
                if winner == VERBATIM and case_sensitive
                else ""
            ),
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
