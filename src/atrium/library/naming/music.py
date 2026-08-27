# SPDX-License-Identifier: GPL-3.0-or-later
"""A path under a `music` root, and the seam where 004 overrules it.

Music inverts the priority of the other two collection types: **embedded tags outrank the path**
(003 spec section 3.5). That is not a preference — a well-tagged library with a flat directory
structure has to produce the right albums, and a compilation must not become one album per track.

**Measured**, across 5,814 real tracks: 413 of them carry an album name bearing no resemblance to
the directory holding the file, and 129 keep leading or trailing whitespace that a path cannot
produce — `Through the Barricades ` under a directory called
`Spandau_Ballet-Through_the_Barricades`. The tag is copied verbatim, artefacts and all.
`[probe: tools/probe_music_precedence.py, Jellyfin 10.11.11, 2026-08-27]`

**Reading those tags is 004.** This module produces the structure a path can give and *asks* for
the rest through `MetadataSource`, which ships here as a path-only implementation that answers
nothing. 004 supplies the real one and nothing in this file changes — that substitutability is what
T13 owes 004, and a stub that returns real tags proves it in the tests rather than in a comment.

**A trailing year in an album directory stays in the album's name**, unlike a film's. `Live 1999`
is an album called `Live 1999`, while `The Album (2001)` is `The Album` from 2001. Only a
*bracketed* year is a year here, because the bare form is part of how albums are named.

**A leading digit is a track number only when a separator follows it.** `24K Magic.flac` is a song
called `24K Magic`, not track 24 of `K Magic`, and `4f3a9c2e1b7d.flac` is a file named after a hash,
not track 4 of `f3a9c2e1b7d`. The separator used to be optional, on the reasoning that a number
alone is a number — which holds for `01.flac` and stops holding the moment a letter touches the
digits. The cost is stated rather than hidden: `01Track.flac` no longer yields track one.

**The reference derives no track number from a filename at all.** A track and a disc number come
from the embedded tag, or failing that from the container's own, and from nowhere else
`[source: MediaBrowser.Providers/MediaInfo/AudioFileProber.cs:181 @ v10.11.11]`
`[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:1369 @ v10.11.11]`; a file
with no title tag is named after its **whole stem**, leading digits included
`[source: Emby.Server.Implementations/Library/ResolverHelper.cs:96 @ v10.11.11]`. So every stem
this module declines to read a number out of is a stem it agrees with the reference about, and that
is the tie-break whenever a shape is ambiguous: parse *less*. What it still does for
`01 - The Track.flac` is a divergence confined to files carrying no tags — recorded in
`docs/compatibility/behaviours.md` §2.16 and open as 003 OQ-8.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol

from atrium.library.naming.clean import from_text

#: Where nothing says otherwise, a track is on the first disc. See `_from_path` for the measurement.
DEFAULT_DISC = 1

#: A directory between the album and its tracks that names a disc (AC-8). One album, not two.
_DISC_DIRECTORY = re.compile(r"(?i)\A(?:cd|disc|disk|volume|vol)[\s._-]*(\d{1,2})\Z")

#: `1-01 Title`: a disc and a track glued with a dash. Requires digits on **both** sides, so that
#: `101 Title` stays track 101 and `01-Title` stays track 1, and a separator or the end of the stem
#: after them, for the reason `_TRACK` gives.
_DISC_AND_TRACK = re.compile(r"\A(\d{1,2})-(\d{1,3})(?![\d])(?:[\s._-]+(.*))?\Z")

#: `01 Title`, `01 - Title`, `01. Title`, and `01` alone - a number by itself is still a number.
#: What may follow the digits is a **separator or nothing at all**: a digit touching a letter is
#: part of a name, not a number in front of one. See the module docstring for what that costs.
_TRACK = re.compile(r"\A(\d{1,3})(?![\d])(?:[\s._-]+(.*))?\Z")

#: A bracketed year on an album directory. Bare digits are left alone - see the module docstring.
_ALBUM_YEAR = re.compile(r"\s*[(\[]\s*((?:19|20)\d{2})\s*[)\]]\s*\Z")


class MetadataSource(Protocol):
    """What 004 will implement, and the whole of what 003 asks of it.

    One method, taking a path and returning whatever a metadata reader found in the file. Keys are
    the tag names of spec section 3.5 — `albumartist`, `album`, `title`, `track`, `disc`, `artist`,
    `year` — and an absent key means the file said nothing, which is different from saying nothing
    *useful*: an empty string is a tag that is there and empty, and the reference copies those too.

    Deliberately not an interface over files. 003 never opens one, so a source that reads a
    sidecar, an embedded tag, a cache or a fixture all satisfy this equally.
    """

    def tags_for(self, relative_path: str) -> Mapping[str, str]:
        """Whatever is embedded in the file at `relative_path`. Empty when nothing is known."""
        ...


class PathOnly:
    """The implementation 003 ships: it knows nothing, so the path decides everything.

    Not a placeholder to be replaced in this feature. A server with no metadata provider configured
    runs on exactly this, and a library whose files carry no tags is scanned by it forever.
    """

    def tags_for(self, relative_path: str) -> Mapping[str, str]:
        return {}


PATH_ONLY: MetadataSource = PathOnly()


@dataclass(frozen=True, slots=True)
class AudioParse:
    """One track.

    Every field is optional: a path may say very little and the file is still scanned.
    """

    title: str | None = None
    album: str | None = None
    artist: str | None = None
    """The **album** artist, which is what an album's identity comes from (spec section 3.5).

    A compilation has one of these and a different `track_artist` on every track, and that is
    exactly what makes it one album rather than one album per track (AC-9).
    """

    track_artist: str | None = None
    track: int | None = None
    disc: int | None = None
    year: int | None = None


def parse_audio(relative_path: str, source: MetadataSource = PATH_ONLY) -> AudioParse:
    """The track at `relative_path`, from the path and then from whatever `source` knows.

    The order is the whole point: the path is read first because it is always available, and then
    every tag the source supplies **replaces** what the path said. Never raises (plan section 5).
    """
    return _with_tags(_from_path(relative_path), source.tags_for(relative_path))


def _from_path(relative_path: str) -> AudioParse:
    path = PurePosixPath(relative_path)
    stem = path.name.rsplit(".", 1)[0] if "." in path.name[1:] else path.name
    directories = [part for part in path.parts[:-1] if part not in (".", "")]

    disc_from_directory = None
    if directories and (match := _DISC_DIRECTORY.match(directories[-1])):
        # `Artist/Album/CD2/…`: the disc directory is not the album (AC-8).
        disc_from_directory = int(match.group(1))
        directories = directories[:-1]

    # `Artist/Album/Track` is the convention, so with only one directory that directory is the
    # **artist** and there is no album. Reading it as an album instead would file every loose
    # track in a library under an album named after the person who made it.
    album_directory = directories[-1] if len(directories) >= 2 else None
    artist_directory = (
        directories[-2] if len(directories) >= 2 else (directories[-1] if directories else None)
    )

    album, year = _album(album_directory)
    disc, track, title = _numbers(stem)

    return AudioParse(
        title=title or None,
        album=album,
        artist=from_text(artist_directory).name or None if artist_directory else None,
        track=track,
        # **A track with no disc marker is on disc one**, not on an unknown disc. Measured: the
        # reference reports disc 1 for 5,152 of 5,814 tracks, and treating an unmarked track as
        # unknown instead scored 21% against 98%. Section 3.7.2 corroborates it from the other
        # side - an Audio sort name is `0001 - 0003 - The Song`, and that leading `0001` is this.
        disc=_first_of(disc, disc_from_directory) or DEFAULT_DISC,
        year=year,
    )


def _first_of(*values: int | None) -> int | None:
    return next((value for value in values if value is not None), None)


def _album(directory: str | None) -> tuple[str | None, int | None]:
    """An album's name, and its year only when the year was written in brackets."""
    if directory is None:
        return None, None
    year = _ALBUM_YEAR.search(directory)
    if year is None:
        return directory.strip() or None, None
    return directory[: year.start()].strip() or None, int(year.group(1))


def _numbers(stem: str) -> tuple[int | None, int | None, str]:
    """Disc, track and title, from the filename.

    A stem neither pattern accepts is a title, whole. Both patterns leave their title group unset
    for a stem that is only numbers, which is why each is read through `or ""`.
    """
    both = _DISC_AND_TRACK.match(stem)
    if both is not None:
        return int(both.group(1)), int(both.group(2)), (both.group(3) or "").strip()
    one = _TRACK.match(stem)
    if one is not None:
        return None, int(one.group(1)), (one.group(2) or "").strip()
    return None, None, stem.strip()


def _with_tags(parsed: AudioParse, tags: Mapping[str, str]) -> AudioParse:
    """Every tag present replaces what the path said. Verbatim, whitespace included.

    Not trimmed, not tidied: the reference copies a tag exactly, and 129 of 5,814 measured tracks
    kept whitespace a path could not have produced. Tidying here would make Atrium sort those
    tracks differently from the reference for no reason a user could see.
    """
    if not tags:
        return parsed

    def text(key: str, fallback: str | None) -> str | None:
        return tags.get(key, fallback)

    def number(key: str, fallback: int | None) -> int | None:
        if key not in tags:
            return fallback
        digits = re.match(r"\s*(\d+)", tags[key])  # `3/12` is track three of twelve
        return int(digits.group(1)) if digits else fallback

    return AudioParse(
        title=text("title", parsed.title),
        album=text("album", parsed.album),
        artist=text("albumartist", parsed.artist),
        track_artist=text("artist", parsed.track_artist),
        track=number("track", parsed.track),
        disc=number("disc", parsed.disc),
        year=number("year", parsed.year),
    )


__all__ = ["DEFAULT_DISC", "PATH_ONLY", "AudioParse", "MetadataSource", "PathOnly", "parse_audio"]
