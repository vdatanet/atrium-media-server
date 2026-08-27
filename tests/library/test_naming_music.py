# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-8, AC-9, and the seam 004 has to be able to take over.

The last of those is what this task owes the next feature. 003 produces the structure a path can
give and *asks* for the rest; if that request is not genuinely substitutable, music identification
lands at 004 as a rewrite rather than an implementation. So there is a stub here that answers with
real tags, and the tests below show it overruling the path in every field - without this module
changing.

**Measured against 5,814 real tracks** `[probe: tools/probe_music_precedence.py,
Jellyfin 10.11.11, 2026-08-27]`: path-only resolution gets the disc right for 98.0%, the album
artist for 89.3%, the album for 84.9% and the track number for 77.9%. The remainder is what the
seam is for.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from atrium.domain.items import ItemType
from atrium.library.identity import for_name
from atrium.library.naming import PATH_ONLY, parse_audio

LIBRARY = "b" * 32


class Tagged:
    """A `MetadataSource` that answers from a table. What 004 will be, with a file behind it."""

    def __init__(self, tags: Mapping[str, Mapping[str, str]]) -> None:
        self._tags = tags

    def tags_for(self, relative_path: str) -> Mapping[str, str]:
        return self._tags.get(relative_path, {})


# ------------------------------------------------------------------------------------------
# AC-8: a two-disc album is one album
# ------------------------------------------------------------------------------------------


def test_two_discs_are_one_album_with_two_disc_numbers() -> None:
    one = parse_audio("The Artist/The Album/CD1/01 - First.flac")
    two = parse_audio("The Artist/The Album/CD2/01 - Second.flac")
    assert one.album == two.album == "The Album"
    assert (one.disc, two.disc) == (1, 2)
    assert one.artist == two.artist == "The Artist"


def test_the_two_discs_derive_one_album_identity() -> None:
    """AC-8 where it actually bites: two discs must not become two albums (spec section 3.6)."""
    discs = [parse_audio(f"The Artist/The Album/CD{n}/01 - Track.flac") for n in (1, 2)]
    identities = {for_name(ItemType.MUSIC_ALBUM, LIBRARY, disc.album or "") for disc in discs}
    assert len(identities) == 1


@pytest.mark.parametrize("directory", ["CD2", "Disc 2", "Disk 2", "Volume 2", "cd 2"])
def test_a_disc_directory_is_spelled_several_ways(directory: str) -> None:
    track = parse_audio(f"The Artist/The Album/{directory}/01 - Track.flac")
    assert (track.album, track.disc) == ("The Album", 2)


def test_a_track_with_no_disc_marker_is_on_disc_one() -> None:
    """Measured: the reference reports disc 1 for 5,152 of 5,814 tracks. Treating an unmarked
    track as *unknown* instead scored 21% against 98%, and it would also give the track a sort
    name one segment short of what spec section 3.7.2 specifies.
    """
    assert parse_audio("The Artist/The Album/01 - Track.flac").disc == 1


# ------------------------------------------------------------------------------------------
# AC-9: a compilation is one album
# ------------------------------------------------------------------------------------------


COMPILATION = {
    f"Various Artists/A Compilation/0{n} - Track.flac": {
        "album": "A Compilation",
        "albumartist": "Various Artists",
        "artist": artist,
        "track": str(n),
    }
    for n, artist in enumerate(["One Artist", "Another Artist", "A Third Artist"], start=1)
}


def test_a_compilation_is_one_album_however_many_artists_it_has() -> None:
    """AC-9. Measured on the reference: 33 albums hold tracks by several artists under a single
    album artist, the largest with **60 tracks by 40 distinct artists**, and every one is one album.
    """
    source = Tagged(COMPILATION)
    tracks = [parse_audio(path, source) for path in COMPILATION]

    assert len({track.track_artist for track in tracks}) == 3, "the track artists really do differ"
    assert len({track.artist for track in tracks}) == 1, "and the album artist does not"

    identities = {for_name(ItemType.MUSIC_ALBUM, LIBRARY, track.album or "") for track in tracks}
    assert len(identities) == 1, "a compilation became one album per track"


def test_the_album_artist_and_the_track_artist_are_different_fields() -> None:
    """Conflating them is what turns a compilation into one album per track."""
    track = parse_audio("Various Artists/A Compilation/01 - Track.flac", Tagged(COMPILATION))
    assert track.artist == "Various Artists"
    assert track.track_artist == "One Artist"


# ------------------------------------------------------------------------------------------
# The seam: 004 overrules the path
# ------------------------------------------------------------------------------------------


def test_the_path_only_source_is_what_003_ships() -> None:
    """Not a placeholder: a server with no metadata provider runs on exactly this, forever."""
    assert PATH_ONLY.tags_for("anything") == {}
    assert parse_audio("The Artist/The Album/01 - Track.flac") == parse_audio(
        "The Artist/The Album/01 - Track.flac", PATH_ONLY
    )


def test_a_tag_overrules_the_directory_it_contradicts() -> None:
    """Spec section 3.5, measured: 413 of 5,814 tracks carry an album name bearing no resemblance
    to their directory, and the tag wins.
    """
    path = "The Artist/spandau_ballet-through_the_barricades/01 - Track.flac"
    assert parse_audio(path).album == "spandau_ballet-through_the_barricades"
    assert parse_audio(path, Tagged({path: {"album": "Through the Barricades"}})).album == (
        "Through the Barricades"
    )


def test_a_tag_is_copied_verbatim_including_whitespace_a_path_cannot_produce() -> None:
    """The fingerprint of a raw tag: 129 of 5,814 resolved names kept leading or trailing space.

    Trimming here would sort those tracks differently from the reference for no reason a user
    could see - and the whitespace is how the measurement identified them as tags in the first
    place.
    """
    path = "The Artist/The Album/01 - Track.flac"
    tagged = parse_audio(path, Tagged({path: {"album": "Through the Barricades "}}))
    assert tagged.album == "Through the Barricades "


@pytest.mark.parametrize(
    ("key", "field", "value", "expected"),
    [
        ("title", "title", "A Real Title", "A Real Title"),
        ("album", "album", "A Real Album", "A Real Album"),
        ("albumartist", "artist", "A Real Artist", "A Real Artist"),
        ("track", "track", "7", 7),
        ("disc", "disc", "3", 3),
        ("year", "year", "1999", 1999),
    ],
)
def test_every_field_the_seam_can_override(
    key: str, field: str, value: str, expected: object
) -> None:
    """If any of these could not be overridden, 004 would have to change this module to add it."""
    path = "The Artist/The Album/01 - Track.flac"
    assert getattr(parse_audio(path, Tagged({path: {key: value}})), field) == expected


def test_a_numbered_tag_of_the_form_three_of_twelve_reads_as_three() -> None:
    """`3/12` is how a great many taggers write a track number."""
    path = "The Artist/The Album/01 - Track.flac"
    assert parse_audio(path, Tagged({path: {"track": "3/12"}})).track == 3


def test_an_absent_tag_leaves_the_path_alone() -> None:
    """A source that knows the album but not the artist must not erase the artist."""
    path = "The Artist/The Album/01 - Track.flac"
    parsed = parse_audio(path, Tagged({path: {"album": "A Real Album"}}))
    assert (parsed.album, parsed.artist, parsed.track) == ("A Real Album", "The Artist", 1)


def test_an_empty_tag_is_a_tag_and_not_an_absence() -> None:
    """A file that says its album is the empty string has said something, and the reference
    copies it. Treating empty as absent would put that track back under its directory's name.
    """
    path = "The Artist/The Album/01 - Track.flac"
    assert parse_audio(path, Tagged({path: {"album": ""}})).album == ""
