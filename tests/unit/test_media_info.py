# SPDX-License-Identifier: GPL-3.0-or-later
"""The wire assembly: the three derivations that are not a field copy.

Most of `media/info.py` moves a stored column into a declared field, and a test that restated
every one of those would assert the same mapping twice. What is worth asserting is where the wire
shape is *derived*: the `ETag`, the single container a source reports, and the frame rates the
demuxer states as rationals.

**The `ETag` case is pinned to a measurement, not to this implementation.** The tag and the
modification time below are one real file's, recovered from a live server by searching the second
its `Last-Modified` header named `[probe: tools/probe_media_source.py, Jellyfin 10.11.11,
2026-08-29]`. A test that hashed the same number the same way and compared the two would agree
with itself; this compares against a string the reference sent.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atrium.domain.items import Item, ItemType, MediaSource
from atrium.domain.media import (
    InspectedStream,
    MediaInspection,
    StreamKind,
    VideoRange,
    VideoRangeType,
)
from atrium.media.info import (
    TICKS_AT_UNIX_EPOCH,
    has_subtitles,
    is_hd,
    item_container,
    media_etag,
    source_container,
    sources_for,
    stream_of,
)

#: One file on the reference server: the `ETag` it sent for a media source, and the modification
#: time that tag was proven to come from. Ticks rather than nanoseconds because ticks are what the
#: probe recovered; the conversion is part of what is under test.
MEASURED_ETAG = "427b0eeab29eb1bfe35c879b6fd409bc"
MEASURED_TICKS = 639_091_099_901_374_746
MEASURED_MTIME_NS = (MEASURED_TICKS - TICKS_AT_UNIX_EPOCH) * 100

PROBED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def an_item(*paths: str) -> Item:
    return Item(
        id="a" * 32,
        type=ItemType.MOVIE,
        name="A Film",
        library_id="1" * 32,
        sources=tuple(
            MediaSource(relative_path=one, size=1000, mtime_ns=MEASURED_MTIME_NS) for one in paths
        ),
    )


def an_inspection(
    container: str, *streams: InspectedStream, **overrides: object
) -> MediaInspection:
    values: dict[str, object] = {
        "size": 1000,
        "mtime_ns": MEASURED_MTIME_NS,
        "container": container,
        "format_names": container,
        "probed_at": PROBED_AT,
        "streams": streams,
    }
    values.update(overrides)
    return MediaInspection(**values)  # type: ignore[arg-type]


def a_video(**overrides: object) -> InspectedStream:
    values: dict[str, object] = {
        "index": 0,
        "kind": StreamKind.VIDEO,
        "codec": "h264",
        "width": 1920,
        "height": 1080,
        "framerate": "24000/1001",
        "average_framerate": "24000/1001",
        "video_range": VideoRange.SDR,
        "video_range_type": VideoRangeType.SDR,
    }
    values.update(overrides)
    return InspectedStream(**values)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------
# The ETag
# ------------------------------------------------------------------------------------------


def test_the_etag_reproduces_a_tag_the_reference_sent() -> None:
    """The whole derivation, against one measured string.

    Three conventions have to be right together for this to pass: the modification time becomes a
    .NET tick count, the decimal string of it is hashed as UTF-16 little-endian, and the sixteen
    bytes are rendered in .NET's GUID byte order. Getting any one of them wrong still produces
    32 lowercase hexadecimal characters, which is why the assertion is a measured value and not a
    shape.
    """
    assert media_etag(MEASURED_MTIME_NS) == MEASURED_ETAG


def test_a_sub_tick_difference_in_the_modification_time_changes_nothing() -> None:
    """Ticks are 100 nanoseconds and the timestamp is truncated to them, not rounded.

    A filesystem with nanosecond resolution therefore produces one tag for the whole 100 ns
    window, which is what makes the tag reproducible from a stored `mtime_ns` at all.
    """
    assert media_etag(MEASURED_MTIME_NS + 99) == MEASURED_ETAG
    assert media_etag(MEASURED_MTIME_NS + 100) != MEASURED_ETAG


def test_the_etag_is_not_the_digests_own_hexadecimal() -> None:
    """The near-miss that a reading of the assignment alone would produce.

    Written as a test rather than a comment because it is the failure mode: an implementation that
    skipped the GUID byte order would pass every shape check and be wrong for every file.
    """
    import hashlib

    plain = hashlib.md5(str(MEASURED_TICKS).encode("utf-16-le"), usedforsecurity=False).hexdigest()
    assert plain != MEASURED_ETAG
    assert sorted(plain) == sorted(MEASURED_ETAG), "the same bytes, in a different order"


# ------------------------------------------------------------------------------------------
# The single container (AC-28)
# ------------------------------------------------------------------------------------------

MP4_FAMILY = "mov,mp4,m4a,3gp,3g2,mj2"


@pytest.mark.parametrize(
    ("container", "path", "expected", "why"),
    [
        (MP4_FAMILY, "films/A Film.mp4", "mp4", "the extension is a member, so it wins"),
        (MP4_FAMILY, "music/A Track.m4a", "m4a", "the same list, a different member"),
        (MP4_FAMILY, "films/A Film.MP4", "MP4", "matched case-insensitively, kept as written"),
        (MP4_FAMILY, "films/A Film.avi", "mov", "no member matches, so the first one wins"),
        (MP4_FAMILY, "films/A Film", "mov", "no extension at all, same branch"),
        ("mkv", "films/A Film.mkv", "mkv", "one name is already single, and is not resolved"),
        ("mkv", "films/A Film.mp4", "mkv", "and the extension does not override it"),
        (None, "films/A Film.avi", "avi", "never inspected: the reference falls back to this"),
    ],
)
def test_the_source_container_is_derived_per_response(
    container: str | None, path: str, expected: str, why: str
) -> None:
    """AC-28's second half, as the table the reference's own branch structure has.

    The uppercase row is not decoration: the membership test is case-insensitive and the value
    kept is the *path's* spelling, so a file named `.MP4` answers `MP4`
    `[source: Emby.Server.Implementations/Dto/DtoService.cs:316-352 @ v10.11.11]`.
    """
    assert source_container(container, path) == expected, why


def test_the_item_level_container_is_the_stored_string_whole() -> None:
    """AC-28's first half. The item keeps the demuxer list; only the source resolves it."""
    item = an_item("films/A Film.mp4")
    probes = [an_inspection(MP4_FAMILY, a_video())]

    assert item_container(item, probes) == MP4_FAMILY
    assert sources_for(item, probes, "/films", is_video=True)[0].container == "mp4"


def test_an_uninspected_file_still_answers_a_container_from_its_extension() -> None:
    item = an_item("films/A Film.mkv")
    assert item_container(item, [None]) == "mkv"
    assert sources_for(item, [None], "/films", is_video=True)[0].container == "mkv"


# ------------------------------------------------------------------------------------------
# Sources
# ------------------------------------------------------------------------------------------


def test_a_two_part_film_answers_two_sources_in_part_order() -> None:
    """Spec section 3.1: one source per part, and part zero keeps the item's own identifier.

    The second part has no item of its own here - the reference models the same film as two items
    - so its identifier is derived, and the only requirements on it are that it is stable and not
    the first part's.
    """
    item = an_item("films/Two - part1.mkv", "films/Two - part2.mkv")
    built = sources_for(item, [an_inspection("mkv", a_video()), None], "/films", is_video=True)

    assert [one.name for one in built] == ["Two - part1", "Two - part2"]
    assert built[0].id == item.id, "part zero is the item, which is what the reference does"
    assert built[1].id != built[0].id
    assert built[1].id == sources_for(item, [], "/films", is_video=True)[1].id, "stable"


def test_a_source_carries_the_measured_constants_of_a_local_file() -> None:
    """The fifteen properties the reference sends unconditionally, and that omitting is the delta.

    Asserted by value rather than by presence: a `false` the reference sends and Atrium sends as
    `true` is exactly as observable as one it does not send at all
    `[probe: tools/probe_media_source.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    source = sources_for(
        an_item("films/A Film.mkv"), [an_inspection("mkv", a_video())], "/films", is_video=True
    )[0]

    assert source.protocol == "File"
    assert source.type == "Default"
    assert source.video_type == "VideoFile"
    assert source.transcoding_sub_protocol == "http"
    assert source.formats == []
    assert source.media_attachments == []
    assert source.required_http_headers == {}
    assert (source.supports_direct_play, source.supports_direct_stream) == (True, True)
    assert (source.supports_transcoding, source.supports_probing) == (True, True)
    assert not any(
        (
            source.is_remote,
            source.read_at_native_framerate,
            source.ignore_dts,
            source.ignore_index,
            source.gen_pts_input,
            source.is_infinite_stream,
            source.use_most_compatible_transcoding_profile,
            source.requires_opening,
            source.requires_closing,
            source.requires_looping,
            source.has_segments,
        )
    )
    assert source.transcoding_url is None, "a listing negotiates nothing"


def test_an_audio_item_reports_no_video_type() -> None:
    source = sources_for(
        an_item("music/A Track.flac"),
        [an_inspection("flac", InspectedStream(index=0, kind=StreamKind.AUDIO, codec="flac"))],
        "/music",
        is_video=False,
    )[0]
    assert source.video_type is None


def test_the_default_audio_index_prefers_the_default_flagged_track() -> None:
    """With no user language preference expressed, which is all v1 has, that is the whole rule."""
    streams = (
        a_video(),
        InspectedStream(index=1, kind=StreamKind.AUDIO, codec="ac3"),
        InspectedStream(index=2, kind=StreamKind.AUDIO, codec="aac", is_default=True),
    )
    built = sources_for(
        an_item("films/A Film.mkv"), [an_inspection("mkv", *streams)], "/films", is_video=True
    )
    assert built[0].default_audio_stream_index == 2

    without = tuple(one for one in streams if one.index != 2)
    plain = sources_for(
        an_item("films/A Film.mkv"), [an_inspection("mkv", *without)], "/films", is_video=True
    )
    assert plain[0].default_audio_stream_index == 1, "no default flag, so the first audio stream"


def test_a_source_without_a_root_carries_no_path_rather_than_a_relative_one() -> None:
    """A relative path on the wire would be a path a client cannot use and cannot tell apart from
    an absolute one - the same rule `BaseItemDto.Path` follows."""
    built = sources_for(an_item("films/A Film.mkv"), [None], None, is_video=True)
    assert built[0].path is None


# ------------------------------------------------------------------------------------------
# Streams
# ------------------------------------------------------------------------------------------


def test_a_frame_rate_becomes_a_number_and_the_reference_rate_prefers_the_average() -> None:
    """`24000/1001` is 23.976. The rational is what the segment cadence needs and the number is
    what a client reads, which is why the conversion is here and not in the prober."""
    wire = stream_of(a_video(framerate="25", average_framerate="24000/1001"))
    assert wire.average_frame_rate == pytest.approx(23.976, abs=0.001)
    assert wire.real_frame_rate == 25
    assert wire.reference_frame_rate == wire.average_frame_rate


def test_a_frame_rate_is_written_the_way_a_thirty_two_bit_float_prints() -> None:
    """The reference's field is a single, and its serialiser writes the shortest string that
    round-trips as one - so `24000/1001` reaches a client as `23.976025` and `25/1` as `25`.

    Asserted on the **serialised** value rather than on the Python object, because that is the
    only place the difference exists: a double holding the same quantity prints seventeen digits,
    and `25.0` and `25` parse identically and compare unequal byte for byte.
    """
    ntsc = stream_of(a_video(framerate="24000/1001", average_framerate="24000/1001"))
    whole = stream_of(a_video(framerate="25/1", average_framerate="25/1"))

    assert '"AverageFrameRate":23.976025' in ntsc.model_dump_json()
    assert '"AverageFrameRate":25,' in whole.model_dump_json()


def test_a_level_stays_the_whole_number_the_demuxer_reported() -> None:
    """Declared a double upstream and always integral in practice; the reference sends `31`."""
    assert '"Level":31' in stream_of(a_video(level=31)).model_dump_json()


def test_an_implausible_average_frame_rate_falls_back_to_the_real_one() -> None:
    """Some libraries report 1000 fps for a file that is nothing of the sort, and the reference
    distrusts exactly that `[source: MediaBrowser.Model/Entities/MediaStream.cs
    ReferenceFrameRate @ v10.11.11]`."""
    wire = stream_of(a_video(framerate="25", average_framerate="1000/1"))
    assert wire.average_frame_rate == 1000
    assert wire.reference_frame_rate == 25


def test_a_stream_that_is_not_video_still_carries_both_range_properties() -> None:
    """`Unknown`, not absent: the reference's enums default to a member, so all 471 measured
    streams carried both `[probe: tools/probe_media_source.py, Jellyfin 10.11.11, 2026-08-29]`."""
    wire = stream_of(InspectedStream(index=1, kind=StreamKind.AUDIO, codec="aac"))
    assert (wire.video_range, wire.video_range_type) == ("Unknown", "Unknown")
    assert wire.type == "Audio"


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        ("DD+ 7.1 / Dolby Atmos", "DolbyAtmos"),
        ("DTS-HD MA / DTS:X", "DTSX"),
        ("LC", "None"),
        (None, "None"),
    ],
)
def test_the_spatial_format_is_read_off_the_audio_profile(
    profile: str | None, expected: str
) -> None:
    wire = stream_of(InspectedStream(index=1, kind=StreamKind.AUDIO, codec="eac3", profile=profile))
    assert wire.audio_spatial_format == expected


def test_a_video_profile_never_names_a_spatial_format() -> None:
    """The reference gates the whole derivation on the stream being audio, and a video profile
    called `High` would otherwise be one substring away from claiming Atmos."""
    assert stream_of(a_video(profile="Dolby Atmos")).audio_spatial_format == "None"


# ------------------------------------------------------------------------------------------
# The two file facts, and the spelling they read
# ------------------------------------------------------------------------------------------


#: Every spelling the rule has an opinion about, and what it answers. The **renamed** spellings
#: are what a stream carries once it has been inspected; the four beside them are what the
#: inspection tool itself reports, and are here to hold the claim that the rename is load-bearing
#: rather than cosmetic. Measured against the wire for the four that a real library has: `DVDSUB`
#: is the one subtitle codec here that cannot be served on its own `[probe:
#: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`.
SUBTITLE_SPELLINGS = [
    # The renamed spellings, which is what `media/probe.py` stores.
    ("PGSSUB", False, True),
    ("DVDSUB", False, False),
    ("DVBSUB", False, False),
    ("DVBTXT", True, True),
    # The tool's own spellings. Two of the four answer the same either way - which is why the
    # only image track the fixture matrix can build proves nothing about the rename.
    ("hdmv_pgs_subtitle", False, True),
    ("dvb_teletext", True, True),
    ("dvd_subtitle", True, True),
    ("dvb_subtitle", True, True),
    # Text formats, and the two bare extensions that are image formats by being the whole name.
    ("subrip", True, True),
    ("ass", True, True),
    ("webvtt", True, True),
    ("mov_text", True, True),
    ("sup", False, True),
    ("sub", False, False),
    # `microdvd` is text however it is spelled, because it shares `.sub` with an image format.
    ("microdvd", True, True),
]


@pytest.mark.parametrize(("codec", "text", "servable"), SUBTITLE_SPELLINGS)
def test_the_split_and_the_servable_rule_are_lookups_on_the_spelling(
    codec: str, text: bool, servable: bool
) -> None:
    """One table, two properties, and the two rows that matter are `dvd_subtitle` and `DVDSUB`.

    They are the same track before and after inspection, and they answer **opposite** things: read
    against the tool's own name, every DVD subtitle in a library is text, servable alone, offered
    in a manifest and offered for conversion.
    """
    wire = stream_of(InspectedStream(index=2, kind=StreamKind.SUBTITLE, codec=codec))
    assert (wire.is_text_subtitle_stream, wire.supports_external_stream) == (text, servable)


def test_the_two_renamed_spellings_that_invert_are_the_reason_the_rename_exists() -> None:
    """The table above, stated as the claim it holds, so deleting a row cannot quietly weaken it.

    `hdmv_pgs_subtitle` already contains `pgs` and `dvb_teletext` is text under either name, so
    two of the four renames change no answer at all - and the one image codec the fixture matrix
    can produce is one of those two.
    """
    from atrium.media.probe import RENAMED_SUBTITLE_CODECS

    answers = {codec: (text, servable) for codec, text, servable in SUBTITLE_SPELLINGS}
    inverted = [
        raw for raw, renamed in RENAMED_SUBTITLE_CODECS.items() if answers[raw] != answers[renamed]
    ]
    assert sorted(inverted) == ["dvb_subtitle", "dvd_subtitle"]


@pytest.mark.parametrize("kind", [StreamKind.VIDEO, StreamKind.AUDIO, StreamKind.DATA])
def test_a_stream_that_is_not_a_subtitle_answers_false_to_both(kind: StreamKind) -> None:
    """Non-nullable on the reference and emitted on every stream, `false` on 1 021 of them that
    are not subtitles `[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`.
    The codec below is a subtitle spelling on purpose: the rules read the stream's *kind* first,
    which is where the reference puts the test too."""
    wire = stream_of(InspectedStream(index=0, kind=kind, codec="subrip"))
    assert (wire.is_text_subtitle_stream, wire.supports_external_stream) == (False, False)


def test_a_subtitle_with_no_codec_is_text_only_when_it_came_from_a_file() -> None:
    """The one branch that is not a lookup: a container track nobody could name is not text, and
    a file beside the media is, because its format is its extension."""
    container = stream_of(InspectedStream(index=2, kind=StreamKind.SUBTITLE, codec=None))
    beside = stream_of(
        InspectedStream(index=0, kind=StreamKind.SUBTITLE, codec=None, is_external=True)
    )
    assert (container.is_text_subtitle_stream, container.supports_external_stream) == (False, False)
    assert (beside.is_text_subtitle_stream, beside.supports_external_stream) == (True, True)


def test_an_external_image_subtitle_can_still_be_served_on_its_own() -> None:
    """A `.sup` beside a film: not text, and servable anyway - the first clause of the rule is
    `IsExternal`, not `IsTextSubtitleStream`."""
    wire = stream_of(
        InspectedStream(index=0, kind=StreamKind.SUBTITLE, codec="sup", is_external=True)
    )
    assert not wire.is_text_subtitle_stream
    assert wire.supports_external_stream


def test_the_five_properties_this_task_declares_and_does_not_fill_stay_absent() -> None:
    """`Score` is emitted by nothing at all and the other four are answered elsewhere - two by a
    negotiation, one by the files discovered beside the media. Declared so the field order is the
    pinned document's, and absent from a bare read on the reference too: none of the four on any
    of 1 968 streams, and `Path` on the 14 that came from a file `[probe:
    tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`."""
    body = stream_of(a_video()).model_dump_json()
    for absent in ("Score", "DeliveryMethod", "DeliveryUrl", "IsExternalUrl", "Path"):
        assert f'"{absent}"' not in body


def test_the_two_file_facts_sit_between_the_index_and_the_pixel_format() -> None:
    """Field order is contract here, and the whole run is one contiguous block in the pinned
    document `[spec: MediaStream]`. A byte comparison sees this; a parsed one does not."""
    body = stream_of(a_video(pixel_format="yuv420p")).model_dump_json()
    assert (
        '"Index":0,"IsExternal":false,"IsTextSubtitleStream":false,'
        '"SupportsExternalStream":false,"PixelFormat":"yuv420p"'
    ) in body


# ------------------------------------------------------------------------------------------
# The item's own media properties
# ------------------------------------------------------------------------------------------


def test_is_hd_is_seven_hundred_and_twenty_lines_or_more() -> None:
    assert is_hd([an_inspection("mkv", a_video(height=720))])
    assert not is_hd([an_inspection("mkv", a_video(height=719))])
    assert not is_hd([an_inspection("mkv", a_video(height=None))])
    assert not is_hd([None])


def test_has_subtitles_counts_a_subtitle_stream_in_any_part() -> None:
    subtitled = an_inspection(
        "mkv", a_video(), InspectedStream(index=1, kind=StreamKind.SUBTITLE, codec="subrip")
    )
    assert has_subtitles([an_inspection("mkv", a_video()), subtitled])
    assert not has_subtitles([an_inspection("mkv", a_video()), None])


def test_the_item_level_streams_are_part_zeros_alone() -> None:
    """The reference's rule: the item-level list is the streams of the source whose id is the
    item's, and part zero is that source `[source:
    Emby.Server.Implementations/Dto/DtoService.cs:1151-1170 @ v10.11.11]`."""
    from atrium.media.info import item_streams

    first = an_inspection("mkv", a_video())
    second = an_inspection("mkv", a_video(index=0), InspectedStream(index=1, kind=StreamKind.AUDIO))
    assert [one.index for one in item_streams([first, second])] == [0]
