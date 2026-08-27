# SPDX-License-Identifier: GPL-3.0-or-later
"""Embedded tags, in all four containers, from the templates T2 checked in.

Each case copies a silent template and writes the tags it wants with mutagen, so what is under
test is one file's worth of tags on a known, empty container - not a fixture somebody tagged once
and nobody has looked at since (plan section 8).

The two rules that matter most pull in opposite directions and both have to hold in every
container: **three artists are three artists** (AC-6), and **a `;` inside one value is still one
artist**. Guessing at separators is how `AC/DC` becomes two artists; joining lists is how three
artists become one string a client renders as one link.
"""

from __future__ import annotations

import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

import mutagen
import pytest
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCOM, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, TXXX, UFID
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

from atrium.metadata.model import Field, PersonKind
from atrium.metadata.tags import TagSource, read_tags

TEMPLATES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata" / "audio"

#: The smallest valid PNG, so an embedded-art case costs 70 bytes rather than a fixture.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
)

#: What every container writes, in that container's own spelling. One dictionary per format, so
#: the *same* logical tags are written four different ways and read back one way - which is the
#: whole claim `metadata/tags.py` makes.
CONTAINERS = ("flac", "ogg", "mp3", "m4a")


def tagged(
    tmp_path: Path,
    container: str,
    *,
    title: str = "A Track",
    artists: Sequence[str] = ("First", "Second", "Third"),
    album_artists: Sequence[str] = ("The Album Artist",),
    album: str = "The Album",
    track: str = "3/12",
    disc: str = "2/2",
    date: str = "1998-05-04",
    genres: Sequence[str] = ("Electronic", "Ambient"),
    composers: Sequence[str] = ("A Composer",),
    gain: str | None = "-7.25 dB",
    ids: Mapping[str, str] | None = None,
    art: bytes | None = None,
) -> Path:
    """A copy of the `container` template carrying exactly these tags."""
    ids = dict(ids or {})
    path = tmp_path / f"track.{container}"
    shutil.copy(TEMPLATES / f"template.{container}", path)

    if container in ("flac", "ogg"):
        opened = FLAC(path) if container == "flac" else OggVorbis(path)
        opened["title"] = [title]
        opened["artist"] = list(artists)
        opened["albumartist"] = list(album_artists)
        opened["album"] = [album]
        opened["tracknumber"] = [track]
        opened["discnumber"] = [disc]
        opened["date"] = [date]
        opened["genre"] = list(genres)
        opened["composer"] = list(composers)
        if gain is not None:
            opened["replaygain_track_gain"] = [gain]
        for name, value in ids.items():
            opened[name] = [value]
        if art is not None and container == "flac":
            picture = Picture()
            picture.data, picture.type, picture.mime = art, 3, "image/png"
            opened.add_picture(picture)
        opened.save()
        return path

    if container == "mp3":
        frames = ID3()
        frames.add(TIT2(encoding=3, text=[title]))
        frames.add(TPE1(encoding=3, text=list(artists)))
        frames.add(TPE2(encoding=3, text=list(album_artists)))
        frames.add(TALB(encoding=3, text=[album]))
        frames.add(TRCK(encoding=3, text=[track]))
        frames.add(TPOS(encoding=3, text=[disc]))
        frames.add(TDRC(encoding=3, text=[date]))
        frames.add(TCON(encoding=3, text=list(genres)))
        frames.add(TCOM(encoding=3, text=list(composers)))
        if gain is not None:
            frames.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=[gain]))
        for name, value in ids.items():
            if name == "musicbrainz_recordingid":
                frames.add(UFID(owner="http://musicbrainz.org", data=value.encode()))
            else:
                frames.add(TXXX(encoding=3, desc=_ID3_DESC[name], text=[value]))
        if art is not None:
            frames.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=art))
        frames.save(path)
        return path

    opened_mp4 = MP4(path)
    opened_mp4["\xa9nam"] = [title]
    opened_mp4["\xa9ART"] = list(artists)
    opened_mp4["aART"] = list(album_artists)
    opened_mp4["\xa9alb"] = [album]
    opened_mp4["trkn"] = [(int(track.split("/")[0]), 0)]
    opened_mp4["disk"] = [(int(disc.split("/")[0]), 0)]
    opened_mp4["\xa9day"] = [date]
    opened_mp4["\xa9gen"] = list(genres)
    opened_mp4["\xa9wrt"] = list(composers)
    if gain is not None:
        opened_mp4["----:com.apple.iTunes:replaygain_track_gain"] = [gain.encode()]
    for name, value in ids.items():
        opened_mp4[f"----:com.apple.iTunes:{_MP4_DESC[name]}"] = [value.encode()]
    if art is not None:
        opened_mp4["covr"] = [MP4Cover(art, imageformat=MP4Cover.FORMAT_PNG)]
    opened_mp4.save()
    return path


_ID3_DESC = {
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
}
_MP4_DESC = {
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_recordingid": "MusicBrainz Track Id",
}


# ----------------------------------------------------------------------------------------------
# T2's promise, now that there is a tag reader to check it with
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("container", CONTAINERS)
def test_the_templates_carry_no_tags_at_all(container: str) -> None:
    """T2 asserted the *field names* were absent from the bytes and said the real property needed
    a tag reader. There is one now: a template a reader finds anything in would put a tool's own
    version inside every test case below."""
    opened = mutagen.File(TEMPLATES / f"template.{container}")
    assert opened is not None
    assert not opened.tags, f"{container} template carries {dict(opened.tags)}"


@pytest.mark.parametrize("container", CONTAINERS)
def test_an_untagged_template_reads_as_nothing_rather_than_as_a_warning(container: str) -> None:
    """Most of a library looks like this before anybody tags it. A file with no tag block is not a
    problem to report; the path still resolves the track."""
    result = read_tags(TEMPLATES / f"template.{container}")
    assert result.warning == ""
    assert dict(result.values) == {}
    assert dict(result.tags) == {}


# ----------------------------------------------------------------------------------------------
# AC-6, in every container
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_track_with_three_artists_has_three_artists(tmp_path: Path, container: str) -> None:
    """AC-6. Vorbis repeats keys, ID3v2.4 separates with NUL, MP4 repeats atom entries - three
    encodings of one idea, and none of them may arrive as one string with separators in it."""
    result = read_tags(tagged(tmp_path, container))
    assert result.values[Field.ARTISTS] == ["First", "Second", "Third"]


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_semicolon_inside_one_value_stays_one_artist(tmp_path: Path, container: str) -> None:
    """The reverse of AC-6, and the reason the reference's custom delimiters default to **off**
    `[source: MediaBrowser.Model/Configuration/LibraryOptions.cs:37-40 @ v10.11.11]`. Guessing at
    separators is how `AC/DC` becomes two artists."""
    result = read_tags(tagged(tmp_path, container, artists=("Earth, Wind & Fire; Live",)))
    assert result.values[Field.ARTISTS] == ["Earth, Wind & Fire; Live"]


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_slash_inside_one_artist_stays_one_artist(tmp_path: Path, container: str) -> None:
    result = read_tags(tagged(tmp_path, container, artists=("AC/DC",)))
    assert result.values[Field.ARTISTS] == ["AC/DC"]


@pytest.mark.parametrize("container", CONTAINERS)
def test_multiple_genres_stay_multiple(tmp_path: Path, container: str) -> None:
    assert read_tags(tagged(tmp_path, container)).values[Field.GENRES] == ["Electronic", "Ambient"]


# ----------------------------------------------------------------------------------------------
# The rest of the field map, in every container
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("container", CONTAINERS)
def test_the_scalar_fields_read_the_same_from_every_container(
    tmp_path: Path, container: str
) -> None:
    values = read_tags(tagged(tmp_path, container)).values
    assert values[Field.NAME] == "A Track"
    assert values[Field.ALBUM_ARTISTS] == ["The Album Artist"]
    assert values[Field.INDEX_NUMBER] == 3
    assert values[Field.PARENT_INDEX_NUMBER] == 2
    assert values[Field.YEAR] == 1998


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_composer_is_a_person_rather_than_a_string(tmp_path: Path, container: str) -> None:
    """`PersonKind` carries all twenty-five members precisely so this one is not an actor."""
    people = read_tags(tagged(tmp_path, container)).values[Field.PEOPLE]
    assert isinstance(people, list)
    assert [(person.name, person.kind) for person in people] == [
        ("A Composer", PersonKind.COMPOSER)
    ]


@pytest.mark.parametrize("container", CONTAINERS)
def test_the_track_gain_is_one_number_with_its_unit_stripped(
    tmp_path: Path, container: str
) -> None:
    """The one replay-gain value the reference reads and serves, as `NormalizationGain` (T1)."""
    values = read_tags(tagged(tmp_path, container)).values
    assert values[Field.NORMALIZATION_GAIN] == pytest.approx(-7.25)


@pytest.mark.parametrize("container", CONTAINERS)
@pytest.mark.parametrize(
    ("written", "expected"),
    [("-7.25 dB", -7.25), ("-7.25dB", -7.25), ("-7.25 DB", -7.25), ("+3.5 dB", 3.5), ("4.0", 4.0)],
)
def test_the_gain_suffix_is_stripped_the_way_the_reference_strips_it(
    tmp_path: Path, container: str, written: str, expected: float
) -> None:
    values = read_tags(tagged(tmp_path, container, gain=written)).values
    assert values[Field.NORMALIZATION_GAIN] == pytest.approx(expected)


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_gain_that_is_not_a_number_is_left_out_rather_than_stored(
    tmp_path: Path, container: str
) -> None:
    values = read_tags(tagged(tmp_path, container, gain="loud")).values
    assert Field.NORMALIZATION_GAIN not in values


@pytest.mark.parametrize("container", CONTAINERS)
def test_musicbrainz_ids_reach_their_canonical_spellings(tmp_path: Path, container: str) -> None:
    path = tagged(
        tmp_path,
        container,
        ids={
            "musicbrainz_albumid": "mb-album",
            "musicbrainz_releasegroupid": "mb-group",
            "musicbrainz_artistid": "mb-artist",
        },
    )
    assert read_tags(path).values[Field.PROVIDER_IDS] == {
        "MusicBrainzAlbum": "mb-album",
        "MusicBrainzReleaseGroup": "mb-group",
        "MusicBrainzArtist": "mb-artist",
    }


@pytest.mark.parametrize("container", ["flac", "mp3", "m4a"])
def test_embedded_cover_art_comes_back_as_bytes(tmp_path: Path, container: str) -> None:
    """Ogg Vorbis is out of this list on purpose: it carries a picture as a base64 field inside
    the comment block rather than as a structure mutagen exposes, and no fixture here writes one.
    """
    result = read_tags(tagged(tmp_path, container, art=PNG))
    assert result.art is not None
    assert result.art.data == PNG


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_file_with_no_art_reports_none(tmp_path: Path, container: str) -> None:
    assert read_tags(tagged(tmp_path, container)).art is None


# ----------------------------------------------------------------------------------------------
# 003's seam, whose contract is not this module's field vocabulary
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("container", CONTAINERS)
def test_the_seam_speaks_003s_vocabulary_and_nothing_else(tmp_path: Path, container: str) -> None:
    """Section 3.5's keys exactly. A key this source invents is a key the resolver ignores, which
    would be a silent half-wiring rather than a failure."""
    tags = read_tags(tagged(tmp_path, container)).tags
    assert set(tags) <= {"albumartist", "album", "title", "track", "disc", "artist", "year"}
    assert tags["album"] == "The Album"
    assert tags["albumartist"] == "The Album Artist"
    assert tags["title"] == "A Track"
    assert tags["year"] == "1998"


@pytest.mark.parametrize("container", ["flac", "ogg", "mp3"])
def test_the_seam_keeps_the_number_verbatim_for_003_to_parse(
    tmp_path: Path, container: str
) -> None:
    """`3/12` is track three of twelve, and 003 already knows that. Parsing it here and handing
    back `3` would work and would put the same rule in two places."""
    tags = read_tags(tagged(tmp_path, container)).tags
    assert tags["track"] == "3/12"


@pytest.mark.parametrize("container", ["flac", "ogg"])
def test_an_empty_tag_is_present_and_empty_in_the_seam(tmp_path: Path, container: str) -> None:
    """003's rule, restated because breaking it is silent: an empty string is a tag that is there
    and empty, which the reference copies - **different** from an absent key. `values` drops it,
    because there an empty string is not a value. Two rules, two homes."""
    path = tagged(tmp_path, container, album="")
    result = read_tags(path)
    assert result.tags["album"] == "", "the seam keeps it"
    assert Field.NAME in result.values, "and the rest of the file still read"


@pytest.mark.parametrize("container", CONTAINERS)
def test_a_multi_valued_tag_gives_the_seam_its_first_value(tmp_path: Path, container: str) -> None:
    """The seam promised one string per key. The full list survives in `values`, so AC-6 is
    unaffected: what a client sees as three artists comes from there."""
    result = read_tags(tagged(tmp_path, container))
    assert result.tags["artist"] == "First"
    assert result.values[Field.ARTISTS] == ["First", "Second", "Third"]


# ----------------------------------------------------------------------------------------------
# Warn and continue
# ----------------------------------------------------------------------------------------------


def test_a_file_that_is_not_audio_at_all_warns_and_yields_nothing(tmp_path: Path) -> None:
    """003's fixture library is full of these - synthetic files with media extensions - and the
    scan has to walk them without either failing or inventing tags."""
    impostor = tmp_path / "track.flac"
    impostor.write_bytes(b"atrium synthetic fixture - not media\n" + b"\0" * 600)
    result = read_tags(impostor)
    assert result.warning
    assert dict(result.values) == {}
    assert dict(result.tags) == {}


def test_a_truncated_container_warns_rather_than_raising(tmp_path: Path) -> None:
    whole = tagged(tmp_path, "flac")
    truncated = tmp_path / "half.flac"
    truncated.write_bytes(whole.read_bytes()[: len(whole.read_bytes()) // 3])
    result = read_tags(truncated)
    assert result.warning
    assert dict(result.values) == {}


def test_a_missing_file_warns_rather_than_raising(tmp_path: Path) -> None:
    assert read_tags(tmp_path / "absent.flac").warning


# ----------------------------------------------------------------------------------------------
# The memo, which is why the seam and the refresh can both ask
# ----------------------------------------------------------------------------------------------


def test_one_file_is_opened_once_however_many_times_it_is_asked_about(tmp_path: Path) -> None:
    """The resolver asks what album this file is in while the tree is being built; the refresh
    asks everything else afterwards. Opening twice would double the I/O of the one part of a scan
    that touches file contents at all."""
    tagged(tmp_path, "flac")
    source = TagSource([tmp_path])
    for _ in range(5):
        source.tags_for("track.flac")
        source.result_for("track.flac")
    assert source.opened == 1


def test_the_memo_is_per_path_rather_than_global(tmp_path: Path) -> None:
    tagged(tmp_path, "flac")
    tagged(tmp_path, "ogg")
    source = TagSource([tmp_path])
    source.tags_for("track.flac")
    source.tags_for("track.ogg")
    assert source.opened == 2


def test_a_source_resolves_a_relative_path_against_whichever_root_has_it(tmp_path: Path) -> None:
    """A library may have several roots and a relative path does not say which. 003 already
    derives one identity from `(library, relative path)`, so the same relative path under two
    roots is already one item there."""
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    tagged(second, "flac", title="In the second root")
    source = TagSource([first, second])
    assert source.tags_for("track.flac")["title"] == "In the second root"


def test_a_path_no_root_has_is_a_warning_rather_than_an_exception(tmp_path: Path) -> None:
    source = TagSource([tmp_path])
    assert source.tags_for("nowhere/track.flac") == {}
    assert source.result_for("nowhere/track.flac").warning


def test_a_source_reports_every_warning_it_collected(tmp_path: Path) -> None:
    from atrium.metadata.tags import warnings_of

    (tmp_path / "broken.flac").write_bytes(b"not a container")
    tagged(tmp_path, "ogg")
    source = TagSource([tmp_path])
    source.tags_for("broken.flac")
    source.tags_for("track.ogg")
    assert len(warnings_of([source])) == 1
