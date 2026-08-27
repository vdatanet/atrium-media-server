# SPDX-License-Identifier: GPL-3.0-or-later
"""The fixture library, declared: what is in the tree and why each thing is in it.

This is the *metadata* half of what specs/003 section 6 promises to check in. No bytes live here
and none are committed anywhere - `generate.py` writes them, deterministically, from the paths
below. That is what makes "no fixture file is a copyrighted work" a property of the code rather
than a promise somebody has to keep reviewing.

**Every entry carries the reason it exists**, for the same reason the naming corpus does
(plan section 6.1): an entry with no reason is one nobody dares delete when it becomes
inconvenient, and one nobody dares keep when a pattern fails against it. Several of these entries
look like clutter and are not - `theme.mp3` beside a film is the case a scanner gets wrong by
being generous.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType


class Kind(Enum):
    """What the scanner is expected to do with this file. Nothing here asserts it - the tests do.

    The distinction between IGNORED and SIDECAR is not about behaviour, which is identical: both
    produce no item. It is about *why*, and 004 will read the sidecars while nothing will ever
    read the rest.
    """

    MEDIA = "becomes an item"
    SIDECAR = "read by 004, never an item"
    IGNORED = "present, and deliberately produces nothing"
    EMPTY = "zero bytes, which is an incomplete copy rather than a file"


@dataclass(frozen=True)
class Entry:
    path: str
    """Relative to the library root, always with forward slashes."""

    kind: Kind
    reason: str
    """One line. Why this entry is in the tree at all."""

    tags: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """What a metadata reader would find embedded in the file.

    003 never opens a file, so nothing here is written into one: these are what the T14
    `MetadataSource` stub hands back, and what 004 will eventually read for real. They are
    declared here rather than there because they are part of describing the fixture - the
    compilation case is only a compilation because of what these say.
    """


@dataclass(frozen=True)
class Library:
    name: str
    collection_type: str
    entries: tuple[Entry, ...]


def _audio(
    path: str,
    reason: str,
    *,
    album: str,
    artist: str,
    albumartist: str,
    track: str,
    disc: str = "1",
) -> Entry:
    return Entry(
        path=path,
        kind=Kind.MEDIA,
        reason=reason,
        tags=MappingProxyType(
            {
                "album": album,
                "artist": artist,
                "albumartist": albumartist,
                "track": track,
                "disc": disc,
                "title": path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            }
        ),
    )


MOVIES = Library(
    name="Movies",
    collection_type="movies",
    entries=(
        # -- the layouts of spec section 3.3 ---------------------------------------------------
        Entry("Amélie (2001).mkv", Kind.MEDIA, "bare file, and the diacritic case of section 3.7"),
        Entry(
            "The Matrix (1999)/The Matrix (1999).mkv",
            Kind.MEDIA,
            "folder-per-film, where the folder and the file agree",
        ),
        Entry(
            "The Long Film (1998)/The Long Film (1998) - part1.mkv",
            Kind.MEDIA,
            "AC-4: one film in two parts. Doubling a user's library is the most visible "
            "scanning bug there is",
        ),
        Entry(
            "The Long Film (1998)/The Long Film (1998) - part2.mkv",
            Kind.MEDIA,
            "AC-4: the second part, which must not become a second item",
        ),
        # -- AC-13: names whose sort order is decided by section 3.7.1 --------------------------
        Entry(
            "2 Fast 2 Furious (2003).mkv",
            Kind.MEDIA,
            "AC-13: every digit run pads, not just the first",
        ),
        Entry(
            "10 Things I Hate About You (1999).mkv",
            Kind.MEDIA,
            "AC-13: sorts after 2, which is the point of padding",
        ),
        Entry(
            "A Bridge Too Far (1977).mkv", Kind.MEDIA, "AC-13: a single-letter article at the start"
        ),
        Entry("iRobot (2004).mkv", Kind.MEDIA, "AC-13: case normalised without the name changing"),
        Entry("Wall-E (2008).mkv", Kind.MEDIA, "AC-13: a removed character"),
        Entry(
            "Rock & Roll (1978).mkv",
            Kind.MEDIA,
            "AC-13: the DOUBLE SPACE artefact - nothing collapses it",
        ),
        Entry("Don't Look Up (2021).mkv", Kind.MEDIA, "AC-13: an apostrophe is removed"),
        Entry(
            "S.W.A.T. (2003).mkv",
            Kind.MEDIA,
            "AC-13: the TRAILING SPACE artefact - nothing trims it",
        ),
        Entry("100% Wolf (2020).mkv", Kind.MEDIA, "AC-13: replacement and padding in one name"),
        Entry(
            "  Padded   (1999).mkv", Kind.MEDIA, "AC-13: trimmed at step 1, before anything else"
        ),
        # -- the other admitted extensions, measured at T1 --------------------------------------
        Entry(
            "An Old Transfer (1985).avi", Kind.MEDIA, "a measured movies extension that is not .mkv"
        ),
        Entry(
            "A Newer Transfer (2015).mp4",
            Kind.MEDIA,
            "a measured movies extension that is not .mkv",
        ),
        Entry("A Broadcast Capture (2011).ts", Kind.MEDIA, "the fourth measured movies extension"),
        # -- present, and deliberately nothing --------------------------------------------------
        Entry(
            "The Matrix (1999)/theme.mp3",
            Kind.IGNORED,
            "T1 measured this: an audio file under a video root is NOT an item. 89 of these on "
            "the reference produced nothing. behaviours 2.15",
        ),
        Entry(
            "The Matrix (1999)/commentary.mka",
            Kind.IGNORED,
            "T1 measured this too - .mka under a video root is not an item either",
        ),
        Entry(
            "The Matrix (1999)/The Matrix (1999)-trailer.mkv",
            Kind.IGNORED,
            "an extra, not the work",
        ),
        Entry(
            "The Matrix (1999)/The Matrix (1999)-sample.mkv", Kind.IGNORED, "a sample, not the work"
        ),
        Entry("The Matrix (1999)/The Matrix (1999).nfo", Kind.SIDECAR, "the sidecar 004 will read"),
        Entry(
            "The Matrix (1999)/poster.jpg",
            Kind.SIDECAR,
            "artwork beside a film is ordinary, not an error",
        ),
        Entry(
            ".hidden/A Hidden Film (2000).mkv",
            Kind.IGNORED,
            "a path component beginning with a dot",
        ),
        Entry("Excluded/.ignore", Kind.IGNORED, "the operator's explicit exclusion marker"),
        Entry(
            "Excluded/An Excluded Film (2000).mkv",
            Kind.IGNORED,
            "excluded by the .ignore beside it",
        ),
        Entry(
            "An Incomplete Copy (2000).mkv",
            Kind.EMPTY,
            "zero bytes: a download that never finished",
        ),
    ),
)


SHOWS = Library(
    name="Shows",
    collection_type="tvshows",
    entries=(
        Entry(
            "The Series/Season 01/The Series - S01E01 - Pilot.mkv",
            Kind.MEDIA,
            "the ordinary three-level layout",
        ),
        Entry(
            "The Series/Season 01/The Series - S01E02-E03 - Two Parter.mkv",
            Kind.MEDIA,
            "AC-5: ONE item spanning two numbers, not two items",
        ),
        Entry(
            "The Series/Season 01/The Series - S01E04 - Old Transfer.avi",
            Kind.MEDIA,
            "a measured tvshows extension that is not .mkv",
        ),
        Entry(
            "The Series/Specials/The Series - S00E01 - A Special.mkv",
            Kind.MEDIA,
            "AC-6: Specials is an alias for season zero",
        ),
        Entry(
            "The Series/The Series - S02E01 - No Season Directory.mkv",
            Kind.MEDIA,
            "the middle level is often not a directory; the season is inferred from the episode",
        ),
        Entry(
            "24/Season 01/24 - S01E01 - 12-00 AM.mkv",
            Kind.MEDIA,
            "AC-7: a series named with digits keeps its title. The pattern is matched against "
            "the filename first, then the directory - this is where naive scanners fail",
        ),
        Entry(
            "The Daily Show/Season 2024/The Daily Show - 2024-01-31.mkv",
            Kind.MEDIA,
            "date-based naming, for a show with no episode numbers",
        ),
        Entry(
            "The Series/Season 02/The Series - S02E99 - Beyond Any Real Count.mp4",
            Kind.MEDIA,
            "section 3.4: an episode number exceeding any real count is not an error",
        ),
        Entry(
            "The Series/Season 03/",
            Kind.IGNORED,
            "section 3.4: a season directory with no episodes is normal, and stays empty here",
        ),
        Entry(
            "The Series/Season 01/The Series - S01E01 - Pilot-behindthescenes.mkv",
            Kind.IGNORED,
            "an extra attaches to its parent rather than becoming an episode",
        ),
        Entry("The Series/theme.mp3", Kind.IGNORED, "T1: audio under a video root is not an item"),
        Entry(
            "The Series/Season 01/The Series - S01E01 - Pilot.srt",
            Kind.SIDECAR,
            "subtitles are not items",
        ),
        Entry("The Series/tvshow.nfo", Kind.SIDECAR, "the series sidecar 004 will read"),
        Entry("The Series/fanart.jpg", Kind.SIDECAR, "artwork is ordinary, not an error"),
    ),
)


MUSIC = Library(
    name="Music",
    collection_type="music",
    entries=(
        _audio(
            "The Artist/First Album (2001)/01 - Opening.flac",
            "the ordinary artist/album/track layout, with a year on the directory",
            album="First Album",
            artist="The Artist",
            albumartist="The Artist",
            track="1",
        ),
        _audio(
            "The Artist/First Album (2001)/02 - Second.flac",
            "a second track, so the album is not a single-track special case",
            album="First Album",
            artist="The Artist",
            albumartist="The Artist",
            track="2",
        ),
        _audio(
            "The Artist/Second Album/01 - In Another Container.m4a",
            "a measured music extension that is not .flac",
            album="Second Album",
            artist="The Artist",
            albumartist="The Artist",
            track="1",
        ),
        _audio(
            "The Artist/Second Album/02 - And Another.dsf",
            "the third measured music extension",
            album="Second Album",
            artist="The Artist",
            albumartist="The Artist",
            track="2",
        ),
        _audio(
            "The Artist/Double Album/CD1/01 - First Disc.flac",
            "AC-8: one album, and the disc number comes from the directory",
            album="Double Album",
            artist="The Artist",
            albumartist="The Artist",
            track="1",
            disc="1",
        ),
        _audio(
            "The Artist/Double Album/CD2/01 - Second Disc.flac",
            "AC-8: the second disc must not become a second album",
            album="Double Album",
            artist="The Artist",
            albumartist="The Artist",
            track="1",
            disc="2",
        ),
        _audio(
            "Various Artists/A Compilation (1999)/01 - By One Artist.flac",
            "AC-9: a compilation is ONE album. Its identity is the album artist, not the track "
            "artist, which differs on every track here",
            album="A Compilation",
            artist="One Artist",
            albumartist="Various Artists",
            track="1",
        ),
        _audio(
            "Various Artists/A Compilation (1999)/02 - By Another.flac",
            "AC-9: a different track artist, same album",
            album="A Compilation",
            artist="Another Artist",
            albumartist="Various Artists",
            track="2",
        ),
        _audio(
            "Various Artists/A Compilation (1999)/03 - By A Third.flac",
            "AC-9: a third, because two could be a coincidence",
            album="A Compilation",
            artist="A Third Artist",
            albumartist="Various Artists",
            track="3",
        ),
        _audio(
            "The Artist/spandau_ballet-through_the_barricades/01 - Tagged Differently.flac",
            "T1 measured this shape: the tag bears no resemblance to the directory, and the tag "
            "wins. 413 of 5,814 tracks on the reference looked like this. spec section 3.5",
            album="Through the Barricades ",
            artist="The Artist",
            albumartist="The Artist",
            track="1",
        ),
        Entry(
            "The Artist/First Album (2001)/cover.jpg", Kind.SIDECAR, "album artwork is not a track"
        ),
        Entry(
            "The Artist/First Album (2001)/album.nfo",
            Kind.SIDECAR,
            "the album sidecar 004 will read",
        ),
        Entry(
            "The Artist/First Album (2001)/01 - Opening.lrc", Kind.IGNORED, "lyrics are not a track"
        ),
        Entry(
            "The Artist/Not A Film (2001).mkv",
            Kind.IGNORED,
            "spec section 3.1: a file under a music root is never resolved as a movie, whatever "
            "it is called. The inverse of the theme.mp3 case above",
        ),
    ),
)


#: Declaration order is the build order, and the build order is stable, because a fixture whose
#: tree depends on dictionary iteration is a fixture that produces a different scan on a different
#: day for no reason anybody can see.
LIBRARIES: tuple[Library, ...] = (MOVIES, SHOWS, MUSIC)
