# SPDX-License-Identifier: GPL-3.0-or-later
"""Inspection, and the rows it becomes.

Two halves, and they are deliberately not the same test. The first opens the generated matrix of
`tests/fixtures/media.py` and asserts that what came back is what the entry **declares** - the
007 T4 pattern, the property compared against the constant rather than against a number written
twice - so a fixture that quietly stopped producing `hevc` fails here rather than weakening
every decision test written after it. The second half never touches a file: it hands the
repository a record with every field populated and reads it back, because "the round trip
preserves every column" is a claim about storage and a fixture cannot make it.

The tool is not the code under test in the first half either. `tests/fixtures/media.py` has its
own reader - one that asks for frames where `media/probe.py` asks for packets - and the keyframe
assertion below compares the two. A prober checked against its own output would agree with itself
about a wrong file.

Only the tests that run a binary carry `@pytest.mark.ffmpeg`. The rest are the point of the split:
storage, staleness and the two refusals are testable on a machine with no media tools at all.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.compat import ticks
from atrium.config.paths import DataPaths
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import LibraryRepository, MediaProbeRepository
from atrium.domain.items import CollectionType
from atrium.domain.library import Library
from atrium.domain.media import (
    InspectedStream,
    MediaInspection,
    StreamKind,
    VideoRange,
    VideoRangeType,
)
from atrium.media.probe import (
    InspectionError,
    ProberUnavailableError,
    UnreadableMediaError,
    inspect,
)
from tests.conftest import data_dir
from tests.fixtures.media import (
    DIRECT_PLAY,
    HIGH_RATE_AUDIO,
    LONG_TAKE,
    MATRIX,
    TWO_PARTER_FIRST,
    BuiltMedia,
    MediaFile,
    keyframe_seconds,
)

#: A library identifier for the storage half. Distinct from every fixture world's, so a test that
#: accidentally mixed two collides instead of quietly sharing one.
LIBRARY_ID = "d" * 32

#: A fixed instant for the hand-written records. `probed_at` is required rather than defaulted, so
#: a record built in a test carries one and the round trip below compares it like any other column.
PROBED_AT = datetime(2026, 8, 29, 11, 30, 15, 250_000, tzinfo=UTC)


# ------------------------------------------------------------------------------------------
# Inspecting
# ------------------------------------------------------------------------------------------


@pytest.mark.ffmpeg
@pytest.mark.parametrize("entry", MATRIX, ids=lambda one: one.key)
def test_a_fixture_inspects_to_what_it_declares(entry: MediaFile, media_files: BuiltMedia) -> None:
    """Every value compared against the declaration that drove the encoder, never a literal."""
    found = inspect(media_files.path_of(entry))

    assert found.format_names == entry.demuxers
    assert found.runtime_ticks is not None
    assert found.runtime_ticks == pytest.approx(
        ticks.from_seconds(entry.duration_seconds), rel=0.02
    )

    audio = found.audio
    if not entry.has_audio:
        #: 012 T2's `soundless`: an entry that declares no audio stream has to come back with
        #: none, which is the condition the reference refuses a whole request over.
        assert audio is None
        return
    assert audio is not None
    assert audio.codec == entry.audio_codec
    assert audio.sample_rate == entry.sample_rate
    assert audio.channels == entry.channels

    video = found.video
    if not entry.has_video:
        assert video is None
        return

    assert video is not None
    assert video.codec == entry.video_codec
    assert (video.width, video.height) == (entry.width, entry.height)
    assert entry.frame_rate is not None
    assert video.framerate is not None
    assert Fraction(video.framerate) == Fraction(entry.frame_rate)


@pytest.mark.ffmpeg
@pytest.mark.parametrize("entry", MATRIX, ids=lambda one: one.key)
def test_the_stored_container_is_the_normalised_one(
    entry: MediaFile, media_files: BuiltMedia
) -> None:
    """`matroska,webm` is stored as `mkv`, and the mp4 family is stored whole.

    Derived from the entry's declared muxer rather than written out per entry: the rule is "a
    Matroska file whose streams disqualify WebM collapses to one name", and an entry added later
    is covered by it without anybody extending a list.
    """
    found = inspect(media_files.path_of(entry))
    expected = "mkv" if entry.muxer == "matroska" else entry.demuxers

    assert found.container == expected
    assert (found.container != found.format_names) is (entry.muxer == "matroska"), (
        "the normalisation must change the Matroska entries and only those"
    )


@pytest.mark.ffmpeg
def test_the_change_signal_comes_from_the_file_that_was_read(media_files: BuiltMedia) -> None:
    """Inspection carries the signal 003 stores, read in the same breath as the contents - so a
    stored inspection can never be attributed to bytes it did not read."""
    path = media_files.path_of(DIRECT_PLAY)
    found = inspect(path)

    assert found.size == path.stat().st_size
    # Against the file's own stamp rather than against the fixture's base instant, which is what
    # this test was always trying to say: every file carries its **own** fixed time since
    # 2026-09-06, and "the signal came from the file that was read" is exactly this comparison.
    assert found.mtime_ns == path.stat().st_mtime_ns
    assert found.unchanged_since(found.size, found.mtime_ns)
    assert not found.unchanged_since(found.size, found.mtime_ns + 1)


@pytest.mark.ffmpeg
def test_the_keyframes_agree_with_the_other_reader(media_files: BuiltMedia) -> None:
    """The segmentable entry, read twice by two different questions.

    `media/probe.py` asks for packet flags, which never decodes a frame; `tests/fixtures/media.py`
    asks for keyframes among the decoded frames. Agreement between them is what makes the cheap
    question trustworthy for a two-hour film.
    """
    found = inspect(media_files.path_of(LONG_TAKE))
    assert found.video_keyframes is not None

    expected = tuple(
        ticks.from_seconds(str(one)) for one in keyframe_seconds(media_files.path_of(LONG_TAKE))
    )
    assert found.video_keyframes == expected
    assert len(found.video_keyframes) > 1, "the one entry that exists to be segmented"
    assert found.video_keyframes[0] == 0
    assert list(found.video_keyframes) == sorted(found.video_keyframes)


@pytest.mark.ffmpeg
def test_a_file_with_no_video_has_no_keyframe_list_at_all(media_files: BuiltMedia) -> None:
    """Null rather than empty: "this file has no video" and "this video has no keyframes" are
    different answers, and a copy-segment plan that confused them would divide by nothing."""
    assert inspect(media_files.path_of(HIGH_RATE_AUDIO)).video_keyframes is None
    assert inspect(media_files.path_of(DIRECT_PLAY)).video_keyframes is not None


@pytest.mark.ffmpeg
def test_the_matroska_placeholder_codec_tag_is_not_stored(media_files: BuiltMedia) -> None:
    """A container with no four-character codes writes the four-zero placeholder for every
    stream. Stored, it would be a codec tag no file has; the reference discards it."""
    in_mp4 = inspect(media_files.path_of(DIRECT_PLAY)).video
    in_matroska = inspect(media_files.path_of(TWO_PARTER_FIRST)).video

    assert in_mp4 is not None and in_matroska is not None
    assert in_mp4.codec_tag == "avc1"
    assert in_matroska.codec_tag is None
    assert in_mp4.codec == in_matroska.codec, "same codec, one container that names it and one not"


@pytest.mark.ffmpeg
def test_a_matroska_stream_reports_no_bitrate_of_its_own(media_files: BuiltMedia) -> None:
    """Why the column is nullable, asserted rather than asserted-in-a-comment.

    The same encoder settings produce a per-stream bitrate in mp4 and none in Matroska, which has
    no field for one. A schema that required it would refuse an ordinary library.
    """
    in_mp4 = inspect(media_files.path_of(DIRECT_PLAY))
    in_matroska = inspect(media_files.path_of(TWO_PARTER_FIRST))

    assert in_mp4.video is not None and in_mp4.video.bitrate is not None
    assert all(one.bitrate is None for one in in_matroska.streams)
    assert in_matroska.bitrate is not None, "the file as a whole still has one"


@pytest.mark.ffmpeg
def test_only_a_video_stream_has_a_dynamic_range(media_files: BuiltMedia) -> None:
    """Every video stream has both values and everything else has neither, so that a null in the
    column means "not video" and never "not determined"."""
    found = inspect(media_files.path_of(DIRECT_PLAY))
    video, audio = found.video, found.audio

    assert video is not None and audio is not None
    assert (video.video_range, video.video_range_type) == (VideoRange.SDR, VideoRangeType.SDR)
    assert (audio.video_range, audio.video_range_type) == (None, None)
    assert video.is_anamorphic is False
    assert video.is_interlaced is False
    assert audio.is_anamorphic is None


@pytest.mark.ffmpeg
@pytest.mark.parametrize("content", [b"not a media file at all\n", b""])
def test_a_file_no_demuxer_can_open_is_refused(tmp_path: Path, content: bytes) -> None:
    """Text and an empty file: the two shapes an unexamined file arrives in. A scan records the
    failure and the item has no media source, which needs the failure to be raised."""
    path = tmp_path / "not-media.mp4"
    path.write_bytes(content)

    with pytest.raises(UnreadableMediaError):
        inspect(path)


@pytest.mark.ffmpeg
def test_a_file_that_is_not_there_is_refused(tmp_path: Path) -> None:
    with pytest.raises(UnreadableMediaError):
        inspect(tmp_path / "nothing here.mkv")


def test_a_missing_tool_is_a_different_refusal(tmp_path: Path) -> None:
    """Unmarked on purpose: it is the case where the binary is absent, and it must be catchable
    apart from "this file is not media". A scan that recorded every file as unexaminable because
    nothing was installed would hide an operator's problem behind its own consequences."""
    path = tmp_path / "anything.mp4"
    path.write_bytes(b"\0")

    with pytest.raises(ProberUnavailableError) as raised:
        inspect(path, ffprobe="ffprobe-that-is-not-installed")
    assert isinstance(raised.value, InspectionError)


# ------------------------------------------------------------------------------------------
# Storing
# ------------------------------------------------------------------------------------------


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def engine(prepared: DataPaths) -> Iterator[Engine]:
    built = create_database_engine(prepared)
    schema.ensure_current(built, prepared)
    yield built
    built.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[OrmSession]:
    opened = session_factory(engine)()
    yield opened
    opened.rollback()
    opened.close()


@pytest.fixture
def library(session: OrmSession, tmp_path: Path) -> Library:
    return LibraryRepository(session).add(
        Library(
            id=LIBRARY_ID,
            name="Films",
            collection_type=CollectionType.MOVIES,
            roots=(str(tmp_path / "films"),),
        )
    )


@pytest.fixture
def probes(session: OrmSession) -> MediaProbeRepository:
    return MediaProbeRepository(session)


def everything_populated() -> MediaInspection:
    """A record with **no field left at its default**, which is what makes the round trip a claim
    about every column rather than about the interesting ones.

    Written by hand rather than inspected: a real file leaves half of these empty - no Matroska
    stream has a bitrate, no fixture is interlaced or anamorphic or high dynamic range - so a
    round trip over one would prove that nulls survive and nothing else.
    """
    return MediaInspection(
        size=123_456_789,
        mtime_ns=1_700_000_000_123_456_789,
        container="mkv",
        format_names="matroska,webm",
        runtime_ticks=72_000_000_000,
        bitrate=8_000_000,
        video_keyframes=(0, 20_020_000, 40_040_000),
        probed_at=PROBED_AT,
        streams=(
            InspectedStream(
                index=0,
                kind=StreamKind.VIDEO,
                codec="hevc",
                codec_tag="hvc1",
                profile="Main 10",
                level=150,
                bit_depth=10,
                width=3840,
                height=2160,
                aspect_ratio="16:9",
                framerate="24000/1001",
                average_framerate="24000/1001",
                language="und",
                title="The picture",
                is_default=True,
                is_forced=True,
                is_hearing_impaired=True,
                is_external=True,
                bitrate=7_500_000,
                video_range=VideoRange.HDR,
                video_range_type=VideoRangeType.HDR10,
                color_range="tv",
                color_transfer="smpte2084",
                color_primaries="bt2020",
                color_space="bt2020nc",
                pixel_format="yuv420p10le",
                ref_frames=4,
                is_interlaced=True,
                is_anamorphic=True,
            ),
            InspectedStream(
                index=1,
                kind=StreamKind.AUDIO,
                codec="flac",
                profile="LC",
                bit_depth=24,
                channels=6,
                channel_layout="5.1",
                sample_rate=96_000,
                language="cat",
                title="The sound",
                bitrate=1_500_000,
            ),
            InspectedStream(index=2, kind=StreamKind.SUBTITLE, codec="subrip", is_external=True),
        ),
    )


def test_a_round_trip_preserves_every_column(
    probes: MediaProbeRepository, library: Library
) -> None:
    """Whole-record equality, so a column added to the schema and forgotten in either direction
    of the mapping fails here rather than being discovered as an empty field on the wire."""
    written = everything_populated()
    probes.put(library.id, "A Film (2026)/A Film (2026).mkv", written)

    assert probes.get(library.id, "A Film (2026)/A Film (2026).mkv") == written


def test_the_keyframe_list_comes_back_a_list_of_whole_ticks(
    probes: MediaProbeRepository, library: Library
) -> None:
    """It is stored as one value rather than a table, so the shape it comes back in is this
    repository's promise: an ordered tuple of integers, and not a string that looks like one."""
    written = everything_populated()
    probes.put(library.id, "film.mkv", written)

    read = probes.get(library.id, "film.mkv")
    assert read is not None
    assert read.video_keyframes == written.video_keyframes
    assert all(isinstance(one, int) for one in read.video_keyframes or ())


def test_a_file_with_no_video_stores_no_keyframe_list(
    probes: MediaProbeRepository, library: Library
) -> None:
    written = MediaInspection(
        size=1,
        mtime_ns=2,
        container="flac",
        format_names="flac",
        probed_at=PROBED_AT,
        video_keyframes=None,
    )
    probes.put(library.id, "track.flac", written)

    read = probes.get(library.id, "track.flac")
    assert read is not None and read.video_keyframes is None


def test_nothing_stored_reads_back_as_nothing(
    probes: MediaProbeRepository, library: Library
) -> None:
    assert probes.get(library.id, "never inspected.mkv") is None
    assert probes.current(library.id, "never inspected.mkv", 1, 2) is None


@pytest.mark.parametrize("moved", ["size", "mtime_ns"])
def test_a_changed_file_reads_back_stale(
    probes: MediaProbeRepository, library: Library, moved: str
) -> None:
    """Either half of 003's change signal is enough. The row is still *there* - a stale
    inspection is re-run by the next scan, not by the request that noticed (plan section 6.1) -
    so `get` still answers and only `current` refuses."""
    written = everything_populated()
    probes.put(library.id, "film.mkv", written)
    signal = {"size": written.size, "mtime_ns": written.mtime_ns}

    assert probes.current(library.id, "film.mkv", **signal) == written
    signal[moved] += 1
    assert probes.current(library.id, "film.mkv", **signal) is None
    assert probes.get(library.id, "film.mkv") == written


def test_writing_again_replaces_the_streams_rather_than_adding_to_them(
    probes: MediaProbeRepository, session: OrmSession, library: Library
) -> None:
    """A file that lost a track between two scans has fewer streams now. Merged, the old one
    would survive as a track the file does not have - and a delivery command addressing it by
    index would address something else."""
    probes.put(library.id, "film.mkv", everything_populated())
    probes.put(
        library.id,
        "film.mkv",
        MediaInspection(
            size=9,
            mtime_ns=9,
            container="mkv",
            format_names="matroska,webm",
            probed_at=PROBED_AT,
            streams=(InspectedStream(index=0, kind=StreamKind.VIDEO, codec="h264"),),
        ),
    )

    read = probes.get(library.id, "film.mkv")
    assert read is not None
    assert [one.index for one in read.streams] == [0]
    assert session.query(models.MediaProbe).count() == 1
    assert session.query(models.MediaStreamRow).count() == 1


def test_two_files_under_one_library_are_two_inspections(
    probes: MediaProbeRepository, library: Library
) -> None:
    """The multi-part film, at the storage layer: one row per part, told apart by the path 003
    already stores for it (spec section 3.1)."""
    first = everything_populated()
    second = MediaInspection(
        size=2, mtime_ns=2, container="mkv", format_names="matroska,webm", probed_at=PROBED_AT
    )
    probes.put(library.id, "The Two Parter/part1.mkv", first)
    probes.put(library.id, "The Two Parter/part2.mkv", second)

    assert probes.get(library.id, "The Two Parter/part1.mkv") == first
    assert probes.get(library.id, "The Two Parter/part2.mkv") == second


def test_removing_the_library_takes_its_inspections_with_it(
    probes: MediaProbeRepository, session: OrmSession, library: Library
) -> None:
    """The cascade, asserted rather than declared. A library that is gone leaves no rows behind
    describing files nothing can reach - and the streams go with the probe, which is the half a
    composite foreign key is easy to get wrong."""
    probes.put(library.id, "film.mkv", everything_populated())
    session.flush()

    LibraryRepository(session).remove(library.id)
    session.flush()

    assert session.query(models.MediaProbe).count() == 0
    assert session.query(models.MediaStreamRow).count() == 0


@pytest.mark.ffmpeg
def test_a_real_inspection_survives_the_round_trip(
    probes: MediaProbeRepository, library: Library, media_files: BuiltMedia
) -> None:
    """The two halves joined once: what the tool actually said about a real file, stored and read
    back unchanged. The hand-written record above proves every column moves; this proves the
    record a real file produces is one the schema accepts."""
    for entry in (DIRECT_PLAY, TWO_PARTER_FIRST, HIGH_RATE_AUDIO):
        found = inspect(media_files.path_of(entry))
        probes.put(library.id, entry.path, found)
        assert probes.get(library.id, entry.path) == found
