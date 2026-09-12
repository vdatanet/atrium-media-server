# SPDX-License-Identifier: GPL-3.0-or-later
"""`BitRate` is four fallbacks, and each one is a branch a file can land in.

008's owes list recorded *"a video `BitRate` where `ffprobe` reports none"* as the one item of its
stream-field tranche whose source nobody had read: the reference answers `117861` for a stream the
tool gives no bitrate for, and this server answered nothing. Reading it found not one derivation
but four, and the shape that matters is **which of them a stream is eligible for** — a subtitle is
eligible for none, an audio stream's second fallback depends on whether it is inside an audio file,
and its last one depends on the opposite.

These are asserted against constructed `ffprobe` output rather than real media, on purpose. The
chain has six inputs — the stream's bitrate, the container's, three tags and the item's kind — and
a fixture that happened to carry two of them would leave four branches unasked; the one test that
does open a file is marked `ffmpeg` and asserts the branch a real file actually lands in.

`[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:969-1018, 251-257,
317-363 @ v10.11.11]`
"""

from __future__ import annotations

from typing import Any

import pytest

from atrium.domain.media import StreamKind
from atrium.media.probe import ESTIMATED_AUDIO_BITRATES, _bitrate

VIDEO_FILE = False
AUDIO_FILE = True


def stream(kind: str = "audio", **fields: Any) -> dict[str, Any]:
    """One `ffprobe` stream object, with only what a caller names."""
    return {"codec_type": kind, **fields}


def derived(
    raw: dict[str, Any], container: dict[str, Any] | None = None, *, is_audio: bool
) -> int | None:
    return _bitrate(raw, StreamKind(raw["codec_type"]), container or {}, is_audio=is_audio)


# -- 1. what the stream itself says ------------------------------------------------------------


def test_the_streams_own_bitrate_wins_over_everything_below_it() -> None:
    answered = derived(
        stream("video", bit_rate="800000", tags={"BPS": "1"}),
        {"bit_rate": "999999"},
        is_audio=VIDEO_FILE,
    )
    assert answered == 800000


def test_a_bitrate_arriving_as_a_number_reads_the_same_as_one_arriving_as_a_string() -> None:
    """`ffprobe` spells numbers both ways depending on the field and the build."""
    assert derived(stream("video", bit_rate=800000), is_audio=VIDEO_FILE) == 800000


# -- 2. the container's, and who is eligible for it --------------------------------------------


def test_a_video_stream_with_no_bitrate_takes_the_containers() -> None:
    """The finding this tranche started from: the reference answers `117861` for such a stream."""
    assert derived(stream("video"), {"bit_rate": "117861"}, is_audio=VIDEO_FILE) == 117861


def test_an_audio_stream_inside_an_audio_file_takes_the_containers() -> None:
    assert derived(stream("audio"), {"bit_rate": "117861"}, is_audio=AUDIO_FILE) == 117861


def test_an_audio_stream_inside_a_video_file_does_not() -> None:
    """A video file's container bitrate is the film's, and an audio track is a fraction of it.

    This is the half that makes `is_audio` a parameter rather than something derived from the
    streams: the same stream object answers two different bitrates depending on what the *item* is.
    """
    assert derived(stream("audio"), {"bit_rate": "117861"}, is_audio=VIDEO_FILE) is None


def test_a_subtitle_stream_takes_no_container_bitrate_in_either_kind_of_file() -> None:
    for is_audio in (AUDIO_FILE, VIDEO_FILE):
        assert derived(stream("subtitle"), {"bit_rate": "117861"}, is_audio=is_audio) is None


# -- 3. the three tags -------------------------------------------------------------------------


def test_the_bps_tag_answers_when_nothing_above_it_did() -> None:
    assert derived(stream("audio", tags={"BPS": "448000"}), is_audio=VIDEO_FILE) == 448000


def test_the_language_suffixed_tag_wins_over_the_bare_one() -> None:
    """`??` in the source: Matroska writes both on a track that declares a language."""
    answered = derived(stream("audio", tags={"BPS-eng": "448000", "BPS": "1"}), is_audio=VIDEO_FILE)
    assert answered == 448000


def test_a_tag_is_found_whatever_its_case() -> None:
    """Every stream tag is rebuilt `OrdinalIgnoreCase` before the reference reads one
    `[source: MediaBrowser.MediaEncoding/Probing/FFProbeHelpers.cs:32 @ v10.11.11]`, and these
    three are Matroska's own — which writes them upper case."""
    assert derived(stream("audio", tags={"bps": "448000"}), is_audio=VIDEO_FILE) == 448000
    assert derived(stream("audio", tags={"Bps-Eng": "448000"}), is_audio=VIDEO_FILE) == 448000


def test_bytes_over_duration_when_there_is_no_bps_tag() -> None:
    """8 000 bytes over 2 seconds is 32 000 bits per second."""
    answered = derived(
        stream("audio", tags={"NUMBER_OF_BYTES": "8000", "DURATION": "00:00:02.000"}),
        is_audio=VIDEO_FILE,
    )
    assert answered == 32000


def test_matroskas_own_duration_tag_is_too_precise_for_the_parser_that_reads_it() -> None:
    """**The fourth fallback is nearly unreachable for the container that writes its tags**, and
    this is reproduced rather than fixed.

    `NUMBER_OF_BYTES` and `DURATION` are Matroska's tags — no other container in this repository's
    fixture matrix writes them — and Matroska writes the duration with **nine** fractional digits
    (`00:47:11.520000000`). `TimeSpan.TryParse` accepts seven. So the reference reads the tag, fails
    to parse it, and leaves the stream with no bitrate, on exactly the files the branch exists for.

    Answering a number here would be this server deriving a bitrate the reference does not. **Not
    measured against a running reference**, and the fixture matrix cannot measure it either: its
    Matroska files carry `DURATION` with nine digits and **no** `NUMBER_OF_BYTES` and no `BPS`
    `[probe: ffprobe 9.0.1 over tests/fixtures/media.py, 2026-09-12]`, so the branch is never
    entered there whatever the parser does. Confirming it needs a Matroska muxed with all three
    tags, and it is on 008's owes list as such.
    """
    matroska = stream(
        "audio", tags={"NUMBER_OF_BYTES": "56609280", "DURATION": "00:47:11.520000000"}
    )
    assert derived(matroska, is_audio=VIDEO_FILE) is None


def test_the_division_rounds_half_to_even_the_way_convert_toint32_does() -> None:
    """`Convert.ToInt32(double)` rounds to even; truncating would answer one less.

    1 003 bytes over 16 seconds is `501.5` bits per second exactly. Rounded to even that is
    **502**; truncated it is 501. The pair is chosen so the two disagree — `500.5` would round to
    500 and truncate to 500, and a test using it would pass under either rule.
    """
    answered = derived(
        stream("audio", tags={"NUMBER_OF_BYTES": "1003", "DURATION": "00:00:16.000"}),
        is_audio=VIDEO_FILE,
    )
    assert 1003 * 8 / 16 == 501.5, "the arithmetic this test is about"
    assert answered == 502


def test_a_duration_under_one_second_derives_nothing() -> None:
    """`durationInSeconds.Value >= 1` in the source, so a very short track keeps no bitrate."""
    answered = derived(
        stream("audio", tags={"NUMBER_OF_BYTES": "8000", "DURATION": "00:00:00.500"}),
        is_audio=VIDEO_FILE,
    )
    assert answered is None


def test_a_duration_with_more_precision_than_dotnet_parses_is_refused() -> None:
    """Matroska writes nine fractional digits and `TimeSpan.TryParse` takes seven.

    A value the reference cannot parse leaves the stream with no bitrate, so answering one here
    would be this server inventing a number rather than reproducing one. Nine digits is refused;
    the same duration at seven is not.
    """
    nine = stream("audio", tags={"NUMBER_OF_BYTES": "8000", "DURATION": "00:00:02.123456789"})
    seven = stream("audio", tags={"NUMBER_OF_BYTES": "8000", "DURATION": "00:00:02.1234567"})
    assert derived(nine, is_audio=VIDEO_FILE) is None
    assert derived(seven, is_audio=VIDEO_FILE) is not None


def test_a_subtitle_stream_reads_no_tags_at_all() -> None:
    """The tag branch is `CodecType.Audio || CodecType.Video` in the source."""
    answered = derived(stream("subtitle", tags={"BPS": "448000"}), is_audio=VIDEO_FILE)
    assert answered is None


# -- 4. the estimate, and the hole in it -------------------------------------------------------


@pytest.mark.parametrize(
    ("codec", "channels", "expected"),
    [
        ("aac", 2, 192_000),
        ("aac", 6, 320_000),
        ("mp3", 1, 192_000),
        ("ac3", 2, 192_000),
        ("ac3", 6, 640_000),
        ("eac3", 8, 640_000),
        ("flac", 2, 960_000),
        ("alac", 5, 2_880_000),
    ],
)
def test_the_estimate_table_for_an_audio_stream_in_a_video_file(
    codec: str, channels: int, expected: int
) -> None:
    answered = derived(stream("audio", codec_name=codec, channels=channels), is_audio=VIDEO_FILE)
    assert answered == expected


@pytest.mark.parametrize("channels", [3, 4])
def test_the_hole_between_the_two_thresholds_answers_nothing(channels: int) -> None:
    """The reference switches on `<= 2` and `>= 5` and returns null in between.

    Reproduced rather than smoothed: a 3- or 4-channel stream carries **no** `BitRate` there, and
    filling the gap would be a different wire shape rather than a tidier one.
    """
    answered = derived(stream("audio", codec_name="aac", channels=channels), is_audio=VIDEO_FILE)
    assert answered is None


def test_a_codec_outside_the_table_takes_no_estimate() -> None:
    answered = derived(stream("audio", codec_name="dts", channels=6), is_audio=VIDEO_FILE)
    assert answered is None


def test_a_stream_that_states_no_channels_takes_no_estimate() -> None:
    """`if (!channels.HasValue) return null` is the first line of the reference's own table."""
    assert derived(stream("audio", codec_name="aac"), is_audio=VIDEO_FILE) is None


def test_the_estimate_is_never_reached_inside_an_audio_file() -> None:
    """It lives in the reference's `else (!isAudio)` branch, which is the mirror of the container
    fallback above: an audio file's container bitrate *is* its stream's, so it is used and the
    table is not."""
    answered = derived(stream("audio", codec_name="aac", channels=2), is_audio=AUDIO_FILE)
    assert answered is None


def test_a_video_stream_takes_no_estimate_however_many_channels_it_claims() -> None:
    answered = derived(stream("video", codec_name="aac", channels=2), is_audio=VIDEO_FILE)
    assert answered is None


def test_the_table_carries_the_six_codecs_the_reference_names_and_no_others() -> None:
    """A seventh added here would be a bitrate this server answers and the reference does not."""
    assert set(ESTIMATED_AUDIO_BITRATES) == {"aac", "mp3", "ac3", "eac3", "flac", "alac"}


# -- the order between them --------------------------------------------------------------------


def test_the_tags_are_read_before_the_estimate() -> None:
    """A stream with both a `BPS` tag and a table entry takes the tag: the estimate is the last
    fallback and runs only over streams still carrying nothing."""
    answered = derived(
        stream("audio", codec_name="aac", channels=2, tags={"BPS": "448000"}),
        is_audio=VIDEO_FILE,
    )
    assert answered == 448000


def test_the_container_is_read_before_the_tags() -> None:
    answered = derived(
        stream("audio", tags={"BPS": "448000"}), {"bit_rate": "117861"}, is_audio=AUDIO_FILE
    )
    assert answered == 117861
