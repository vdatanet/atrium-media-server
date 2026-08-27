#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does the reference do with a file whose embedded tags contradict its path?

Answers 003 OQ-5. Music is the one collection type where the path is *not* the authority
[spec section 3.5], and getting the precedence backwards turns a well-tagged library into one
album per directory and a compilation into one album per track.

Method, and it is entirely read-only. The API never exposes a file's raw tags, so the probe
cannot compare tag against path directly. It compares the *resolved* value against the path,
which answers the question anyway: in this feature's world a name has exactly two possible
sources, so a resolved album name that is not derivable from the directory came from the tag.

Three things are measured, in rising order of how hard they are to explain away:

  1. How often `Album` differs from the directory holding the track, split by *how* it differs -
     an exact match says nothing, a directory carrying a year says only that the path was
     cleaned, and a name with no resemblance says the tag won.
  2. Resolved names carrying **leading or trailing whitespace**. This is the fingerprint of a raw
     tag: a directory name cannot end in a space on the filesystems that matter, and the
     reference trims what it derives from a path. A trailing space in `Album` was copied.
  3. Whether an album whose tracks have many different artists is **one** album. That is the
     compilation case, and it is the one a user notices.

Writes: nothing.

Usage:
    python3 tools/probe_music_precedence.py https://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

from _probe import Probe, Server, main

#: A disc directory sits between the album directory and the track, so the album directory is one
#: level higher. [spec section 3.5]
DISC_DIRECTORY = re.compile(r"(?i)^(cd|disc|disk)[\s._-]*\d+$")

#: `Album (2001)`, `[2001] Album`, `2001 - Album`. Stripping these is *path cleaning*, not tag
#: precedence, and conflating the two would report a much stronger finding than the evidence.
TRAILING_YEAR = re.compile(r"\s*[(\[]\s*(?:19|20)\d{2}\s*[)\]]\s*$")
LEADING_YEAR = re.compile(r"^\s*[(\[]?\s*(?:19|20)\d{2}\s*[)\]]?\s*[-\u2013\u2014.]\s*")

EXACT = "identical to the directory (says nothing either way)"
YEAR = "directory carries a year the name does not (path cleaned)"
PART = "one contains the other (directory partly decorated)"
TAG = "no resemblance to the directory - the tag won outright"
UNTAGGED = "no Album at all"


def fold(value: str) -> str:
    """Compare names the way a human would call them 'the same'."""
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFC", value or "").casefold().strip())


def undecorate(directory: str) -> str:
    return LEADING_YEAR.sub("", TRAILING_YEAR.sub("", directory)).strip()


def album_directory(path: str) -> str | None:
    """The directory that would be the album, skipping a disc directory if there is one."""
    parts = path.replace("\\", "/").split("/")
    if len(parts) < 3:
        return None
    if DISC_DIRECTORY.match(parts[-2]) and len(parts) >= 4:
        return parts[-3]
    return parts[-2]


def classify(album: str, directory: str) -> str:
    if not album.strip():
        return UNTAGGED
    if fold(album) == fold(directory):
        return EXACT
    if fold(album) == fold(undecorate(directory)):
        return YEAR
    if fold(album) in fold(directory) or fold(directory) in fold(album):
        return PART
    return TAG


def every_track(server: Server) -> list[dict]:
    tracks, start = [], 0
    while True:
        page = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes="Audio",
            Fields="Path,ParentId,Album,AlbumArtist,Artists",
            Limit=1000,
            StartIndex=start,
            UserId=server.user_id,
        )
        items = page.get("Items") or []
        if not items:
            break
        tracks += items
        start += len(items)
        if start >= page.get("TotalRecordCount", 0):
            break
    return tracks


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_music_precedence.py",
        question="what does the reference do when a file's embedded tags contradict its path?",
        document="specs/003-library-configuration-and-scanning/spec.md",
        section="section 3.5",
        expectation=(
            "embedded tags outrank the path, and an album's identity comes from its album "
            "artist - so a compilation with a different artist on every track is one album"
        ),
    )

    tracks = every_track(server)
    if not tracks:
        probe.observe("music", "no audio items on this server")
        probe.conclude("no music to measure; point the probe at a server with a music library")
        return probe

    buckets: Counter[str] = Counter()
    untrimmed = 0
    example: tuple[str, str] | None = None
    for track in tracks:
        directory = album_directory(track.get("Path") or "")
        if directory is None:
            continue
        album = track.get("Album") or ""
        verdict = classify(album, directory)
        buckets[verdict] += 1
        artist = track.get("AlbumArtist") or ""
        if album != album.strip() or artist != artist.strip():
            untrimmed += 1
        if verdict == TAG and example is None:
            example = (directory, album)

    total = sum(buckets.values())
    probe.observe("tracks measured", total)
    for verdict in (EXACT, YEAR, PART, TAG, UNTAGGED):
        if buckets[verdict]:
            probe.observe(verdict, f"{buckets[verdict]} ({100 * buckets[verdict] / total:.1f}%)")
    if example:
        probe.observe("one of them", f"directory {example[0]!r} -> Album {example[1]!r}")
    probe.observe(
        "resolved names with untrimmed whitespace",
        f"{untrimmed}   <-- a path cannot produce these; they were copied from a tag"
        if untrimmed
        else "0",
    )

    # The compilation case.
    by_album: dict[str, list[dict]] = defaultdict(list)
    for track in tracks:
        if track.get("ParentId"):
            by_album[track["ParentId"]].append(track)
    many_artists = {
        key: group
        for key, group in by_album.items()
        if len({tuple(t.get("Artists") or []) for t in group}) > 1
    }
    compilations = {
        key: group
        for key, group in many_artists.items()
        if len({(t.get("AlbumArtist") or "") for t in group}) == 1
    }
    probe.observe("albums", len(by_album))
    probe.observe("albums with more than one track artist", len(many_artists))
    probe.observe(
        "of those, one album artist throughout",
        f"{len(compilations)}   <-- each is ONE album, not one per track",
    )
    if compilations:
        biggest = max(compilations.values(), key=len)
        distinct = len({tuple(t.get("Artists") or []) for t in biggest})
        probe.observe(
            "largest compilation",
            f"{len(biggest)} tracks, {distinct} distinct track artists, one album, "
            f"AlbumArtist={biggest[0].get('AlbumArtist')!r}",
        )

    # What this library cannot answer.
    spread = sum(
        1
        for group in by_album.values()
        if len({(t.get("Path") or "").replace("\\", "/").rsplit("/", 1)[0] for t in group}) > 1
    )
    probe.observe("albums whose tracks span several directories", spread)
    if not spread:
        probe.note(
            "Every album on this server lives in exactly one directory, so the strongest form of "
            "spec section 3.5 - a FLAT directory of well-tagged files producing the right albums "
            "- is not measured here. What is measured is that the tag beats the directory when "
            "they disagree, which is the same precedence and a weaker demonstration of it."
        )

    probe.note(
        "The API does not return a file's raw tags, so this compares the RESOLVED name against "
        "the path. That is sound for the question: a resolved album name bearing no resemblance "
        "to its directory cannot have come from the directory, and in this feature there is "
        "nowhere else for it to come from."
    )
    probe.note(
        "The `directory carries a year` bucket is kept separate on purpose. Folding it into the "
        "tag-won bucket would roughly double the headline number while proving only that the "
        "reference strips a year from a directory name, which is path cleaning, not precedence."
    )

    won = buckets[TAG]
    if won and compilations:
        probe.conclude(
            f"tags outrank the path, confirmed two ways: {won} of {total} tracks "
            f"({100 * won / total:.1f}%) carry an album name bearing no resemblance to their "
            f"directory, and {len(compilations)} albums hold tracks by many different artists "
            f"under a single album artist without splitting. "
            + (
                f"{untrimmed} resolved names keep whitespace a path cannot produce, which is a "
                "tag copied verbatim"
                if untrimmed
                else ""
            ),
            matches_documentation=True,
        )
    elif not won:
        probe.conclude(
            "every album name on this server is derivable from its directory, so nothing here "
            "distinguishes the two sources. The claim is neither confirmed nor contradicted - "
            "point the probe at a library with mistagged or oddly-named directories",
            matches_documentation=None,
        )
    else:
        probe.conclude(
            f"{won} tracks show the tag beating the path, but no album with several track "
            "artists survived as one album - the compilation half of section 3.5 is not "
            "reproduced here",
            matches_documentation=False,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
