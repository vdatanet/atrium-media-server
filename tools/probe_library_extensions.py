#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which file extensions does the reference admit as items, and which does it ignore?

Answers 003 OQ-1. Getting this wrong is directly observable: a library missing items whose
absence a user notices, or a library full of artwork pretending to be films.

Method, and it is entirely read-only. Two censuses, taken from opposite ends:

  A. every extension the server *admitted* - the path of every leaf item it holds.
  B. every extension *present on disk* under the library roots, read through
     /Environment/DirectoryContents, which is the read-only filesystem view the library-setup
     screen uses.

An extension in A is honoured. An extension in B but never in A is a file that is there, that the
server walked past, and that produced nothing - ignored. The interesting rows are the ones with
many files on disk and no items at all.

**The limit is worth stating before the finding.** This measures the extensions *this library
contains*. An extension nobody has a file of is not measured, and its absence here is not evidence
that the reference rejects it. So the honoured set is a measured lower bound, the ignored set is a
measured fact, and everything else is unmeasured rather than refuted.

Writes: nothing. It creates no file, no item and no library, which is why it can be pointed at a
real server holding somebody's real media.

Usage:
    python3 tools/probe_library_extensions.py https://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from _probe import Probe, ProbeError, Server, main

#: The collection types 003 resolves [spec section 3.1]. `boxsets` and the rest are outside it.
COLLECTION_TYPES = ("movies", "tvshows", "music")

#: Only types whose Path is a *file*. Series, Season, MusicAlbum, MusicArtist and BoxSet carry a
#: *directory* path, and directory names contain full stops - so censusing them yields entries
#: like `.1-castellano+subs]` and `. rex`, which are not extensions and would drown the finding.
#: This is measured, not theoretical: on the reference used for OQ-1 it produced 25 such rows.
LEAF_TYPES = "Movie,Episode,Audio,Video,MusicVideo"

#: What this repository claims after the OQ-1 measurement, per collection type. A run that finds
#: MORE than this is not a contradiction - it is a library with a file this one did not have, and
#: the probe says to record it. A run that finds one of these *ignored* is a contradiction.
HONOURED: dict[str, frozenset[str]] = {
    "movies": frozenset({".mkv", ".mp4", ".avi", ".ts"}),
    "tvshows": frozenset({".mkv", ".avi", ".mp4"}),
    "music": frozenset({".flac", ".m4a", ".dsf"}),
}

#: Extensions measured on disk, in quantity, that produced no item anywhere. `.mp3` and `.mka`
#: are the ones that matter: they are ordinary media extensions, and under a `movies` or `tvshows`
#: root the reference still admits none of them. `.bif` is the reference's own trickplay index.
IGNORED = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".svg",
        ".jfif",
        ".nfo",
        ".srt",
        ".lrc",
        ".bif",
        ".url",
        ".website",
        ".par2",
        ".txt",
        ".mp3",
        ".mka",
    }
)

#: A bounded walk: this is somebody's real filesystem and the probe is a guest on it. Whatever is
#: dropped is reported rather than silently truncated - a census that quietly stopped early reads
#: exactly like a census that found nothing.
DEFAULT_LISTINGS = 240
DEFAULT_PER_ROOT = 45


def extension(name: str) -> str | None:
    """The lowercase extension of a file name, or None when it has nothing extension-shaped.

    A leading dot is a hidden file, not an extension, so `name[1:]` is what is searched.
    """
    if "." not in name[1:]:
        return None
    suffix = name.rsplit(".", 1)[-1]
    if not suffix.isalnum() or not 1 <= len(suffix) <= 5:
        return None
    return "." + suffix.lower()


def admitted(server: Server) -> dict[str, Counter[str]]:
    """Census A: the extension of every leaf item, grouped by its library's collection type."""
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    roots = library_roots(server)

    start = 0
    while True:
        page = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes=LEAF_TYPES,
            Fields="Path",
            Limit=1000,
            StartIndex=start,
            UserId=server.user_id,
        )
        items = page.get("Items") or []
        if not items:
            break
        for item in items:
            path = item.get("Path") or ""
            found = extension(path.replace("\\", "/").rsplit("/", 1)[-1])
            if found:
                by_type[collection_of(path, roots)][found] += 1
        start += len(items)
        if start >= page.get("TotalRecordCount", 0):
            break
    return by_type


def library_roots(server: Server) -> list[tuple[str, str]]:
    """(root path, collection type) for every library 003 resolves, longest root first.

    Longest first because one root may sit inside another, and the deeper one owns the file.
    """
    roots = [
        (location, folder["CollectionType"])
        for folder in server.get("/Library/VirtualFolders")
        if folder.get("CollectionType") in COLLECTION_TYPES
        for location in (folder.get("Locations") or [])
    ]
    return sorted(roots, key=lambda pair: len(pair[0]), reverse=True)


def collection_of(path: str, roots: list[tuple[str, str]]) -> str:
    for root, kind in roots:
        if path.startswith(root):
            return kind
    return "(outside every root 003 resolves)"


def on_disk(server: Server, probe: Probe, listings: int, per_root: int) -> dict[str, Counter[str]]:
    """Census B: the extension of every file under the roots, breadth-first and bounded."""
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    budget, truncated = listings, []

    for root, kind in sorted(library_roots(server), key=lambda pair: pair[0]):
        queue, listed = [root], 0
        while queue and budget > 0 and listed < per_root:
            directory = queue.pop(0)
            budget -= 1
            listed += 1
            try:
                entries = (
                    server.get_where(
                        "/Environment/DirectoryContents",
                        {"path": directory, "includeFiles": "true", "includeDirectories": "true"},
                    )
                    or []
                )
            except ProbeError:
                continue  # a permission or a race; the census is a sample either way
            for entry in entries:
                name = entry.get("Name") or ""
                if entry.get("Type") == "Directory":
                    queue.append(entry["Path"])
                else:
                    by_type[kind][extension(name) or "(no extension)"] += 1
        if queue:
            truncated.append(f"{kind} ({len(queue)} directories unvisited)")

    if truncated:
        probe.note(
            "The walk is bounded and did not reach the whole tree: "
            + "; ".join(truncated)
            + f". Raise --listings above {listings} to widen it. This is said out loud because a "
            "census that stopped early looks exactly like a census that found nothing."
        )
    return by_type


def run(server: Server, args: argparse.Namespace) -> Probe:
    probe = Probe(
        script="probe_library_extensions.py",
        question=(
            "which file extensions does the reference admit as items, and which does it ignore?"
        ),
        document="specs/003-library-configuration-and-scanning/spec.md",
        section="section 3.2",
        expectation=(
            "movies "
            + " ".join(sorted(HONOURED["movies"]))
            + "; tvshows "
            + " ".join(sorted(HONOURED["tvshows"]))
            + "; music "
            + " ".join(sorted(HONOURED["music"]))
            + "; and no item from "
            + " ".join(sorted(IGNORED))
        ),
    )

    seen = admitted(server)
    disk = on_disk(server, probe, args.listings, args.per_root)
    every_admitted = {ext for counts in seen.values() for ext in counts}

    contradictions: list[str] = []
    additions: list[str] = []

    for kind in COLLECTION_TYPES:
        got, files = seen.get(kind, Counter()), disk.get(kind, Counter())
        if not got and not files:
            probe.observe(kind, "no library of this collection type on this server")
            continue

        probe.observe(
            f"{kind}: admitted",
            ", ".join(f"{ext} x{n}" for ext, n in got.most_common()) or "nothing",
        )
        ignored_here = [(ext, n) for ext, n in files.most_common() if ext not in every_admitted]
        probe.observe(
            f"{kind}: on disk, never an item",
            ", ".join(f"{ext} x{n}" for ext, n in ignored_here[:14]) or "nothing",
        )

        for ext in sorted(set(got) - HONOURED.get(kind, frozenset())):
            additions.append(f"{kind} admits {ext}, which is not recorded")
        for ext in sorted(HONOURED.get(kind, frozenset()) - set(got)):
            # Only a contradiction if a file with that extension was actually there to reject.
            if files.get(ext):
                contradictions.append(
                    f"{kind} was recorded as admitting {ext}, and {files[ext]} such file(s) on "
                    f"disk produced no item"
                )

    for ext in sorted(IGNORED & every_admitted):
        contradictions.append(f"{ext} is recorded as ignored and is an item on this server")

    probe.note(
        "An extension is `honoured` here because a file with it became an item, and `ignored` "
        "because files with it are on disk under a root and no item anywhere has it. Neither "
        "statement generalises to an extension this library has no file of - that is unmeasured, "
        "and spec section 3.2's conservative union stands for it."
    )
    probe.note(
        "The two rows worth reading twice are .mp3 and .mka under a movies or tvshows root. Both "
        "are ordinary media extensions, both are present in quantity, and neither produces an "
        "item of any type - so a scanner that admits every audio extension everywhere would "
        "invent items the reference does not have."
    )
    if additions:
        probe.note("Not a contradiction, but record it: " + "; ".join(additions))

    if contradictions:
        probe.conclude("; ".join(contradictions), matches_documentation=False)
    else:
        probe.conclude(
            "the admitted set matches what is recorded, for every collection type on this "
            "server, and nothing recorded as ignored appears as an item"
            + (f". New extensions seen: {len(additions)}" if additions else ""),
            matches_documentation=True,
        )
    return probe


def arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--listings",
        type=int,
        default=DEFAULT_LISTINGS,
        help=f"Total directory listings the walk may spend (default {DEFAULT_LISTINGS})",
    )
    parser.add_argument(
        "--per-root",
        type=int,
        default=DEFAULT_PER_ROOT,
        help=f"Directory listings per library root (default {DEFAULT_PER_ROOT})",
    )


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], extra_arguments=arguments, with_args=True))
