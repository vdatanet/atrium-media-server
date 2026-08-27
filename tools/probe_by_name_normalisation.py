#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does the reference fold case when it turns a genre name into an item, or does the by-name list
grow duplicates?

Answers 004 OQ-3. specs/004 section 3.7 rule 1 claims that `Sci-Fi` and `sci-fi` in two files
become **one** genre item, with the first spelling seen as the display name. If the reference does
not fold case, that rule is a divergence and has to be argued as one; if it does, the rule is a
reproduction and carries this probe as its provenance.

The measurement is the same one `probe_item_identity.py` makes for path-backed items, applied to
the by-name kind: recompute each returned genre's id from its own returned name, using the
derivation read from the source -

    valid = name with `"<>|:*?\\/` and control characters replaced by spaces,
            then trimmed, then trailing `.` removed
    key   = "metadata\\<Genre|MusicGenre>\\" + valid, all lowercased
    id    = Guid(MD5(UTF16LE(type.FullName + key)))

[source: Emby.Server.Implementations/Library/LibraryManager.cs:636-658,1095-1100 @ v10.11.11]
[source: MediaBrowser.Controller/Entities/Genre.cs:79-92 @ v10.11.11]
[source: Emby.Server.Implementations/IO/ManagedFileSystem.cs:305-334 @ v10.11.11]

A name containing an uppercase letter whose id reproduces from the **lowercased** key is direct
evidence the fold happens; the same name reproducing only from the verbatim key would be evidence
it does not (the reference gates the fold behind `EnableNormalizedItemByNameIds`, default true
[source: MediaBrowser.Model/Configuration/ServerConfiguration.cs:72 @ v10.11.11]). The by-name
rows themselves are the second half of the finding: two rows differing only by case would mean the
list grows duplicates whatever the ids say.

What this probe cannot see, and says so: which spelling *created* a merged row. Read-only, that
history is gone - the row shows one spelling and does not say it was the first. And a library whose
files are consistently tagged can only prove the derivation, not exercise a merge; the probe
reports how many case-variant groups its item sample actually contained, so the reader can tell a
confirmed merge from an unexercised one.

Writes: nothing.

Usage:
    python3 tools/probe_by_name_normalisation.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import hashlib
from typing import Optional

from _probe import Probe, ProbeError, Server, main

#: The characters `GetValidFilename` replaces with a space
#: [source: Emby.Server.Implementations/IO/ManagedFileSystem.cs:21-28 @ v10.11.11]. Inputs to a
#: hash, not code: a wrong set simply fails to reproduce and is counted as such.
INVALID = set('"<>|:*?\\/' + "".join(chr(c) for c in range(32)))

#: (endpoint, metadata folder, C# type full name). The folder is what `ApplicationPaths` combines
#: under `metadata/`; case is irrelevant to the id because the whole key is lowercased, but it is
#: kept faithful anyway so the verbatim candidate is the real verbatim key.
KINDS = [
    ("/Genres", "Genre", "MediaBrowser.Controller.Entities.Genre"),
    ("/MusicGenres", "MusicGenre", "MediaBrowser.Controller.Entities.Audio.MusicGenre"),
]

#: How many items to read back for the item-level spelling sample, per page and in pages. A bound,
#: not the library: the probe reports what it sampled.
PAGE = 800
PAGES = 4


def dotnet_guid(digest: bytes) -> str:
    """`new Guid(byte[16]).ToString("N")`: first three fields little-endian, the rest in order."""
    swapped = [
        digest[3],
        digest[2],
        digest[1],
        digest[0],
        digest[5],
        digest[4],
        digest[7],
        digest[6],
    ]
    return bytes(swapped).hex() + digest[8:16].hex()


def valid_filename(name: str) -> str:
    cleaned = "".join(" " if ch in INVALID else ch for ch in name)
    return cleaned.strip().rstrip(".")


def derived(full_name: str, folder: str, name: str, lowered: bool) -> str:
    key = ("metadata/" + folder + "/" + valid_filename(name)).replace("/", "\\")
    if lowered:
        key = key.lower()
    return dotnet_guid(hashlib.md5((full_name + key).encode("utf-16-le")).digest())  # noqa: S324


def rows_of(server: Server, endpoint: str) -> list[tuple[str, str]]:
    result = server.get(endpoint, UserId=server.user_id, Limit=2000)
    return [(row["Name"], row["Id"]) for row in result.get("Items", [])]


def item_spellings(server: Server) -> tuple[dict[str, set[str]], int]:
    """Distinct item-level genre spellings, grouped case-insensitively, from a bounded sample."""
    groups: dict[str, set[str]] = {}
    seen = 0
    for page in range(PAGES):
        result = server.get(
            "/Items",
            UserId=server.user_id,
            Recursive="true",
            IncludeItemTypes="Movie,Series,Audio",
            Fields="Genres",
            EnableImages="false",
            StartIndex=page * PAGE,
            Limit=PAGE,
        )
        items = result.get("Items", [])
        seen += len(items)
        for item in items:
            for spelling in item.get("Genres") or []:
                groups.setdefault(spelling.casefold(), set()).add(spelling)
        if len(items) < PAGE:
            break
    return groups, seen


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_by_name_normalisation.py",
        question="does the reference fold case when a genre name becomes an item?",
        document="specs/004-metadata-resolution/spec.md",
        section="section 3.7 rule 1 (OQ-3)",
        expectation=(
            "two spellings of one genre differing only by case become one by-name item, "
            "not two rows"
        ),
    )

    normalised_flag: Optional[bool] = None
    try:
        configuration = server.get("/System/Configuration")
        normalised_flag = configuration.get("EnableNormalizedItemByNameIds")
    except ProbeError:
        pass
    probe.observe(
        "EnableNormalizedItemByNameIds",
        "unreadable (not an administrator?)" if normalised_flag is None else normalised_flag,
    )

    lowered_hits = 0
    lowered_case_proof = 0
    verbatim_only = 0
    unexplained: list[str] = []
    duplicate_rows: list[str] = []
    total = 0

    for endpoint, folder, full_name in KINDS:
        rows = rows_of(server, endpoint)
        total += len(rows)

        by_fold: dict[str, list[str]] = {}
        for name, _ in rows:
            by_fold.setdefault(name.casefold(), []).append(name)
        for names in by_fold.values():
            if len(names) > 1:
                duplicate_rows.append(f"{endpoint}: " + " / ".join(sorted(names)))

        for name, item_id in rows:
            if derived(full_name, folder, name, lowered=True) == item_id:
                lowered_hits += 1
                # The folder is uppercase for everyone, so only the *name* carrying case proves
                # anything about how two spellings of one genre relate.
                if valid_filename(name) != valid_filename(name).lower():
                    lowered_case_proof += 1
            elif derived(full_name, folder, name, lowered=False) == item_id:
                verbatim_only += 1
            else:
                unexplained.append(f"{endpoint} {name!r}")

        probe.observe(f"GET {endpoint}", f"{len(rows)} by-name row(s)")

    if total == 0:
        raise ProbeError("the server returned no genres at all; nothing can be measured")

    probe.observe("ids from the lowercased key", f"{lowered_hits} of {total}")
    probe.observe("  ...where case had to fold", lowered_case_proof)
    probe.observe("ids from the verbatim key only", verbatim_only)
    probe.observe("ids from neither key", len(unexplained))
    if unexplained:
        probe.note("unexplained: " + ", ".join(unexplained[:8]))

    groups, sampled = item_spellings(server)
    variant_groups = {fold: s for fold, s in groups.items() if len(s) > 1}
    probe.observe("items sampled for spellings", sampled)
    probe.observe("case-variant genre groups in sample", len(variant_groups))
    for fold in sorted(variant_groups)[:5]:
        probe.observe("  variant", " / ".join(sorted(variant_groups[fold])))

    if duplicate_rows:
        probe.observe("case-duplicate by-name rows", len(duplicate_rows))
        for line in duplicate_rows[:5]:
            probe.observe("  duplicate", line)

    if not variant_groups:
        probe.note(
            "no two items in the sample spell one genre differently, so the merge itself was "
            "not exercised here; the id derivation is the evidence that it would happen, and "
            "which spelling would win is not observable read-only."
        )

    if duplicate_rows:
        probe.conclude(
            f"{len(duplicate_rows)} by-name group(s) hold two rows differing only by case - "
            "the list grows duplicates",
            matches_documentation=False,
        )
    elif unexplained:
        probe.conclude(
            f"{len(unexplained)} of {total} ids reproduce from neither candidate key - the "
            "documented derivation does not hold on this server, so what makes two spellings "
            "one item was not established",
            matches_documentation=False,
        )
    elif verbatim_only:
        probe.conclude(
            f"{verbatim_only} id(s) reproduce only from the verbatim key - this server does not "
            "fold case (EnableNormalizedItemByNameIds off?), so two spellings would become two "
            "items",
            matches_documentation=False,
        )
    elif lowered_case_proof:
        probe.conclude(
            f"case is folded into the id: {lowered_hits} of {total} by-name ids reproduce from "
            f"the lowercased key, {lowered_case_proof} of them only because of the fold, and no "
            "two rows differ only by case - one spelling, one item",
            matches_documentation=True,
        )
    else:
        raise ProbeError(
            f"every one of the {total} measured names is already lowercase-clean, so nothing "
            "here can exercise the fold; the question needs a library whose genre names carry "
            "an uppercase letter"
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
