# SPDX-License-Identifier: GPL-3.0-or-later
"""The cadence arithmetic and the three playlist renderers, against the measured reference bytes.

Plan section 6.8 left one reading owed to 008 T10 - "the exact rounding rule behind the measured
3.004 s" - and this file is the golden that pins it. What is pinned is the **rule**, at five
requested lengths and three frame rates, rather than the single number: the measured 3.004 s turns
out to be a fact about one film's stored frame rate, and the same arithmetic over an exact
`24000/1001` answers 3.003.

Every expected value here was measured `[probe: tools/probe_hls.py, Jellyfin 10.11.11,
2026-08-29]`. `tests/conformance/test_hls_playlists.py` proves the routes reach this module; what
is proven here is the arithmetic and the bytes.

**The third renderer is 011's subtitle playlist**, added at T8, and its numbers come from a
different run `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. One of
them is written differently on purpose: a window duration carries the invariant decimal point
where the reference writes the server's own separator (behaviours section 3.12, 011 AC-16), and
the locale test at the bottom of this file is the only thing here that can fail if that ever
becomes a locale-sensitive format.
"""

from __future__ import annotations

import locale
from typing import Any

import pytest

from atrium.domain.media import InspectedStream, StreamKind, VideoRange, VideoRangeType
from atrium.media.decision import StreamAction, StreamPlan
from atrium.media.hls import (
    Segment,
    buckets_allowed,
    cadence_milliseconds,
    master_playlist,
    media_playlist,
    plan_segments,
    segment_extension,
    subtitle_playlist,
    window_duration_text,
)

#: The frame rate the measured film reports and the reference put in its `MaxFramerate`. Not
#: `24000/1001`: the stored average rate is the exact decimal, and one millisecond of cadence
#: hangs on the difference.
MEASURED_RATE = 23.975988

#: What an exact NTSC film rate reaches this arithmetic as - `media/info.as_single` of
#: `24000/1001`, which is what a negotiation writes into the URL for the T1 `long_take` fixture.
EXACT_NTSC_RATE = 23.976025


# ------------------------------------------------------------------------------------------
# The cadence - plan section 6.8's owed reading
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "milliseconds"),
    [(None, 3004), (1, 1002), (2, 2003), (5, 5006), (10, 10011)],
)
def test_the_re_encode_cadence_is_the_measured_matrix(
    requested: int | None, milliseconds: int
) -> None:
    """Five requested lengths, one frame rate, five measured answers.

    A matrix rather than the single published number, because one row cannot tell `ceil` from
    `round`: at 2 s the two agree and at 1 s, 3 s, 5 s and 10 s they do not.
    """
    assert cadence_milliseconds(requested, MEASURED_RATE, copying_video=False) == milliseconds


def test_the_published_3004_is_a_fact_about_one_films_stored_rate() -> None:
    """The same rule at an exact `24000/1001` answers **3003**, not 3004.

    Spec section 3.7 reads "3.004 s per segment re-encoded (the forced-keyframe cadence at
    23.976 fps)", which invites the reading that 3.004 follows from 23.976 fps. It follows from
    `23.975988` - the rate that film's container stores and that the negotiation put in the URL.
    A source at the exact rational is one millisecond shorter, which is a different playlist and
    a different set of forced keyframes.
    """
    assert cadence_milliseconds(None, MEASURED_RATE, copying_video=False) == 3004
    assert cadence_milliseconds(None, EXACT_NTSC_RATE, copying_video=False) == 3003


def test_a_copy_is_never_scaled_and_defaults_to_six_seconds() -> None:
    """The scaling exists so ffmpeg can force keyframes on the boundaries; a copy forces none."""
    assert cadence_milliseconds(None, MEASURED_RATE, copying_video=True) == 6000
    assert cadence_milliseconds(5, MEASURED_RATE, copying_video=True) == 5000


@pytest.mark.parametrize("rate", [None, 0.0, 25.0, 30.0, 24.0])
def test_a_whole_or_absent_frame_rate_is_not_scaled(rate: float | None) -> None:
    """A request carrying no `MaxFramerate` is the unscaled 3 s, which is what `main.m3u8` asked
    for with no query at all answers on the reference."""
    assert cadence_milliseconds(None, rate, copying_video=False) == 3000


# ------------------------------------------------------------------------------------------
# The two shapes
# ------------------------------------------------------------------------------------------


def test_an_equal_grid_is_uniform_with_a_short_tail() -> None:
    """AC-22's boundary half: every body duration equal, the last no longer than a body, and the
    whole thing summing to the runtime rather than to something near it."""
    runtime = 2842 * 30_040_000 + 12_380_000
    segments = plan_segments(runtime, 3004)

    assert len(segments) == 2843
    bodies = {one.duration_ticks for one in segments[:-1]}
    assert bodies == {30_040_000}
    assert segments[-1].duration_ticks == 12_380_000
    assert segments[-1].duration_ticks <= segments[0].duration_ticks
    assert sum(one.duration_ticks for one in segments) == runtime
    assert [one.index for one in segments[:3]] == [0, 1, 2]
    assert segments[2].start_ticks == 2 * 30_040_000


def test_a_runtime_that_divides_exactly_has_no_tail() -> None:
    segments = plan_segments(4 * 60_000_000, 6000)

    assert len(segments) == 4
    assert {one.duration_ticks for one in segments} == {60_000_000}


def test_no_runtime_plans_nothing() -> None:
    """Where the reference throws and answers `500`; the route turns the empty tuple into the
    same refusal rather than rendering a playlist of nothing."""
    assert plan_segments(0, 3000) == ()
    assert plan_segments(10_000_000, 0) == ()


def test_a_copy_buckets_the_keyframes_and_never_drifts_off_the_grid() -> None:
    """Each cut is the first keyframe at or past the next multiple of the cadence - and the next
    multiple advances by the cadence whatever the cut actually was, so one long bucket does not
    push the ones after it.

    Keyframes every 2 s over 12 s, asked for at 5 s: the cuts are 6 s and 10 s, not 6 s and 11 s.
    """
    keyframes = tuple(one * 20_000_000 for one in range(6))
    segments = plan_segments(120_000_000, 5000, keyframes)

    assert [one.duration_ticks for one in segments] == [60_000_000, 40_000_000, 20_000_000]
    assert [one.start_ticks for one in segments] == [0, 60_000_000, 100_000_000]


def test_a_keyframe_list_that_reaches_the_runtime_still_gets_its_tail() -> None:
    """The reference appends the tail unconditionally, so a final keyframe on the runtime produces
    a zero-length last segment rather than one segment fewer. Reproduced rather than tidied."""
    segments = plan_segments(60_000_000, 5000, (0, 60_000_000))

    assert [one.duration_ticks for one in segments] == [60_000_000, 0]


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("Film (2001).mkv", True),
        ("Film (2001).MKV", True),
        ("Film (2001).mp4", False),
        ("Film (2001).ts", False),
        ("Film", False),
    ],
)
def test_only_the_allowed_extensions_may_bucket(path: str, allowed: bool) -> None:
    """The gate the measurement found: the reference reads keyframes on demand only for a
    container the operator has allowed it for, and ships that list as `mkv` alone. An mp4 copy is
    the equal grid - which is where the published 6.0 s came from."""
    assert buckets_allowed(path) is allowed


# ------------------------------------------------------------------------------------------
# The media playlist, byte for byte
# ------------------------------------------------------------------------------------------

QUERY = "?&DeviceId=d&MediaSourceId=m&VideoCodec=h264"


def test_the_media_playlist_is_the_measured_header_and_entry() -> None:
    """The five header lines, the `, nodesc` suffix, six decimals always, and the two per-segment
    parameters appended to the whole forwarded query."""
    body = media_playlist(plan_segments(60_080_000, 3004), query=QUERY, container="ts")

    lines = body.splitlines()
    assert lines[:5] == [
        "#EXTM3U",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:4",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    assert lines[5] == "#EXTINF:3.004000, nodesc"
    assert lines[6] == (f"hls1/main/0.ts{QUERY}&runtimeTicks=0&actualSegmentLengthTicks=30040000")
    assert lines[7] == "#EXTINF:3.004000, nodesc"
    assert lines[8] == (
        f"hls1/main/1.ts{QUERY}&runtimeTicks=30040000&actualSegmentLengthTicks=30040000"
    )
    assert lines[-1] == "#EXT-X-ENDLIST"
    assert body.endswith("#EXT-X-ENDLIST\n"), "the reference ends every line, the last included"
    assert "\r" not in body


def test_a_whole_number_of_seconds_still_prints_six_decimals() -> None:
    assert Segment(index=0, start_ticks=0, duration_ticks=60_000_000).duration_text == "6.000000"
    assert Segment(index=0, start_ticks=0, duration_ticks=50_450_000).duration_text == "5.045000"


def test_the_target_duration_is_the_longest_segment_rounded_up() -> None:
    """`#EXT-X-TARGETDURATION:6` over 5.045 s buckets, measured on the mkv the copy bucketing was
    found with - so it is the *longest* segment and not the requested length."""
    segments = plan_segments(120_000_000, 5000, (0, 450_000, 50_450_000, 100_450_000))

    assert "#EXT-X-TARGETDURATION:6" in media_playlist(segments, query=QUERY, container="ts")


def test_an_fmp4_playlist_is_version_seven_with_an_initialisation_segment() -> None:
    """`SegmentContainer=mp4` is the one shape that changes the header: HLS carries fMP4 only from
    version 7, and the init segment is segment `-1`."""
    body = media_playlist(plan_segments(60_000_000, 6000), query=QUERY, container="mp4")

    lines = body.splitlines()
    assert lines[2] == "#EXT-X-VERSION:7"
    assert lines[5] == (
        f'#EXT-X-MAP:URI="hls1/main/-1.mp4{QUERY}&runtimeTicks=0&actualSegmentLengthTicks=0"'
    )
    assert lines[7].startswith("hls1/main/0.mp4")


@pytest.mark.parametrize(
    ("container", "extension"), [("ts", ".ts"), ("mp4", ".mp4"), (None, ".ts"), ("", ".ts")]
)
def test_the_segment_extension_is_the_container_or_ts(
    container: str | None, extension: str
) -> None:
    assert segment_extension(container) == extension


# ------------------------------------------------------------------------------------------
# The master playlist, byte for byte
# ------------------------------------------------------------------------------------------

#: The measured film's video stream, as this project stores it: 1920x816 HEVC Main at level 120.
MEASURED_VIDEO = InspectedStream(
    index=0,
    kind=StreamKind.VIDEO,
    codec="hevc",
    width=1920,
    height=816,
    level=120,
    profile="Main",
    bit_depth=8,
    bitrate=4_938_398,
    video_range=VideoRange.SDR,
    video_range_type=VideoRangeType.SDR,
    framerate="24000/1001",
)


def _copy(codec: str, bitrate: int, **extra: Any) -> StreamPlan:
    return StreamPlan(
        source_index=0, action=StreamAction.COPY, codec=codec, bitrate=bitrate, **extra
    )


def test_the_copy_master_variant_is_the_reference_line_byte_for_byte() -> None:
    """The whole `#EXT-X-STREAM-INF` of the measured stream-copy session, reproduced exactly:
    field order, the quoted `CODECS` pair, the HEVC string's `hvc1.1.4.L120.B0` shape, and a
    `FRAME-RATE` rounded to three decimals."""
    video = _copy("hevc", 4_938_398, width=1920, height=816, bit_depth=8)
    audio = StreamPlan(
        source_index=4, action=StreamAction.COPY, codec="ac3", bitrate=448_000, channels=6
    )

    body = master_playlist(
        query=QUERY,
        video=video,
        audio=audio,
        source_video=MEASURED_VIDEO,
        frame_rate=MEASURED_RATE,
    )

    assert body.splitlines() == [
        "#EXTM3U",
        "#EXT-X-STREAM-INF:BANDWIDTH=5386398,AVERAGE-BANDWIDTH=5386398,VIDEO-RANGE=SDR,"
        'CODECS="hvc1.1.4.L120.B0,ac-3",RESOLUTION=1920x816,FRAME-RATE=23.976',
        f"main.m3u8{QUERY}",
    ]
    assert body.endswith("\n")


def test_the_re_encode_master_describes_the_target_and_not_the_source() -> None:
    """`CODECS="avc1.424029,mp4a.40.2"` - constrained baseline at level 41, which is what the
    reference describes an h264 re-encode as when the profile requested no level and no profile,
    even though the *source* is HEVC Main at 120 and its `hevc-level` is right there in the query.

    `BANDWIDTH` is the one field this project answers differently, and knowingly: the reference
    scales the source's rate between the input and output codecs and advertises the result
    (8678663 here), where this advertises what its own encoder is aimed at. Both servers advertise
    their own target; with one variant there is nothing to select on it.
    """
    video = StreamPlan(
        source_index=0,
        action=StreamAction.ENCODE,
        codec="h264",
        width=1920,
        height=816,
        bitrate=4_938_398,
    )
    audio = StreamPlan(
        source_index=4, action=StreamAction.ENCODE, codec="aac", bitrate=448_000, channels=6
    )

    variant = master_playlist(
        query=QUERY,
        video=video,
        audio=audio,
        source_video=MEASURED_VIDEO,
        frame_rate=MEASURED_RATE,
        options={"hevc-level": "120", "hevc-profile": "main"},
    ).splitlines()[1]

    assert 'CODECS="avc1.424029,mp4a.40.2"' in variant
    assert "RESOLUTION=1920x816" in variant
    assert "FRAME-RATE=23.976" in variant
    assert "VIDEO-RANGE=SDR" in variant


def test_a_requested_level_is_read_from_the_query_and_capped() -> None:
    """`{codec}-level` qualified by the **target** codec, which is how a h264-to-h264 re-encode
    picks up the level the negotiation wrote - and level 62 is capped to 51 for compatibility,
    which is `avc1.424033`."""
    video = StreamPlan(source_index=0, action=StreamAction.ENCODE, codec="h264", bitrate=1)

    high = master_playlist(
        query="",
        video=video,
        audio=None,
        source_video=MEASURED_VIDEO,
        frame_rate=25.0,
        options={"h264-level": "62", "h264-profile": "high"},
    )
    low = master_playlist(
        query="",
        video=video,
        audio=None,
        source_video=MEASURED_VIDEO,
        frame_rate=25.0,
        options={"h264-level": "40"},
    )

    assert 'CODECS="avc1.640033"' in high
    assert "FRAME-RATE=25" in high, "a whole rate prints without a fractional part"
    assert 'CODECS="avc1.424028"' in low


def test_a_copied_hdr_stream_is_labelled_by_its_transfer_and_a_re_encode_is_always_sdr() -> None:
    """`VIDEO-RANGE` is the source's only where the video survives; the reference encodes SDR and
    nothing else, so a re-encode of an HDR source says SDR."""
    hdr = InspectedStream(
        index=0,
        kind=StreamKind.VIDEO,
        codec="hevc",
        width=3840,
        height=2160,
        level=150,
        profile="Main 10",
        video_range=VideoRange.HDR,
        video_range_type=VideoRangeType.HDR10,
    )
    copied = _copy("hevc", 1, width=3840, height=2160)
    encoded = StreamPlan(source_index=0, action=StreamAction.ENCODE, codec="h264", bitrate=1)

    copy_master = master_playlist(
        query="", video=copied, audio=None, source_video=hdr, frame_rate=None
    )
    encode_master = master_playlist(
        query="", video=encoded, audio=None, source_video=hdr, frame_rate=None
    )

    assert "VIDEO-RANGE=PQ" in copy_master
    assert 'CODECS="hvc1.2.4.L150.B0"' in copy_master
    assert "VIDEO-RANGE=PQ" not in encode_master
    assert encode_master.count("#EXT-X-STREAM-INF") == 1, (
        "a re-encode already produces SDR, so there is no entrance to stand beside it"
    )


def test_an_hdr_copy_carries_an_sdr_entrance_at_the_copys_own_bandwidth() -> None:
    """The whole two-variant master of the measured HDR stream copy, reproduced exactly.

    **Spec section 3.7 said 'exactly one variant', measured on a standard-range film that could
    not reach this branch.** Against an HDR source the reference appends an h264 entrance at the
    *same* `BANDWIDTH` and `AVERAGE-BANDWIDTH` as the copy - so nothing selects on rate and a
    client picks by colour range - repeating the copy's own `RESOLUTION` and `FRAME-RATE`, and
    addressing it with `VideoCodec` replaced in place and `AllowVideoStreamCopy=false` appended.
    The leading empty pair of the negotiated `?&` does not survive into the entrance's address.
    `[probe: tools/probe_transcode_decision.py, Jellyfin 10.11.11, 2026-08-29]`
    """
    hdr = InspectedStream(
        index=0,
        kind=StreamKind.VIDEO,
        codec="hevc",
        width=3840,
        height=2160,
        level=150,
        profile="Main 10",
        video_range=VideoRange.HDR,
        video_range_type=VideoRangeType.HDR10,
        framerate="24000/1001",
        average_framerate="24000/1001",
    )
    video = _copy("hevc", 26_064_862, width=3840, height=2160, bit_depth=10)
    audio = StreamPlan(
        source_index=2, action=StreamAction.ENCODE, codec="aac", bitrate=640_000, channels=6
    )
    query = (
        "?&DeviceId=d&MediaSourceId=m&VideoCodec=hevc,h264&AudioCodec=aac"
        "&hevc-level=150&hevc-profile=main10&TranscodeReasons=AudioCodecNotSupported"
    )

    body = master_playlist(
        query=query,
        video=video,
        audio=audio,
        source_video=hdr,
        frame_rate=23.976025,
        options={"hevc-level": "150", "hevc-profile": "main10"},
    )

    assert body.splitlines() == [
        "#EXTM3U",
        "#EXT-X-STREAM-INF:BANDWIDTH=26704862,AVERAGE-BANDWIDTH=26704862,VIDEO-RANGE=PQ,"
        'CODECS="hvc1.2.4.L150.B0,mp4a.40.2",RESOLUTION=3840x2160,FRAME-RATE=23.976',
        f"main.m3u8{query}",
        "#EXT-X-STREAM-INF:BANDWIDTH=26704862,AVERAGE-BANDWIDTH=26704862,VIDEO-RANGE=SDR,"
        'CODECS="avc1.424029,mp4a.40.2",RESOLUTION=3840x2160,FRAME-RATE=23.976',
        "main.m3u8?DeviceId=d&MediaSourceId=m&VideoCodec=h264&AudioCodec=aac"
        "&hevc-level=150&hevc-profile=main10&TranscodeReasons=AudioCodecNotSupported"
        "&AllowVideoStreamCopy=false",
    ]


def test_the_entrance_names_the_codec_even_where_the_query_never_did() -> None:
    """`VideoCodec` is replaced in place where the negotiation wrote one and appended where it
    did not - which is a bare `main.m3u8` request, the one the spec's refusal table calls 'not a
    refusal: a copy is planned at the copy default and a playlist is answered'."""
    hdr = InspectedStream(
        index=0,
        kind=StreamKind.VIDEO,
        codec="hevc",
        width=1920,
        height=1080,
        level=120,
        profile="Main 10",
        video_range=VideoRange.HDR,
        video_range_type=VideoRangeType.HLG,
    )
    video = _copy("hevc", 1, width=1920, height=1080)

    lines = master_playlist(
        query="", video=video, audio=None, source_video=hdr, frame_rate=None
    ).splitlines()

    assert lines[2] == "main.m3u8"
    assert lines[4] == "main.m3u8?VideoCodec=h264&AllowVideoStreamCopy=false"
    assert "VIDEO-RANGE=HLG" in lines[1], "an HLG copy is labelled by its own transfer"
    assert "VIDEO-RANGE=SDR" in lines[3]


# ------------------------------------------------------------------------------------------
# The subtitle playlist, byte for byte - and the one number this project writes differently
# ------------------------------------------------------------------------------------------

#: The measured source: a runtime of 5 407.851 s answered 181 windows at 30 s, whose last
#: `#EXTINF` read `7,851` on a Spanish-configured host `[probe:
#: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.
MEASURED_RUNTIME_TICKS = 54_078_510_000
MEASURED_WINDOWS = 181

#: Locales whose decimal separator is a comma. The first one this host can set is used; a host
#: that can set none still runs every assertion, because what is asserted is that the output does
#: not move - Principle VII forbids a test that depends on the host's locale, and this one only
#: gets *harder* where a comma locale exists.
COMMA_LOCALES = ("es_ES.UTF-8", "es_ES.utf8", "de_DE.UTF-8", "fr_FR.UTF-8", "pt_BR.UTF-8")


def test_the_subtitle_playlist_is_the_measured_header_and_entry() -> None:
    """The five header lines in **this** route's order, and one entry per window.

    Not the media playlist's order: the target duration comes first here and the playlist type
    last, and the target duration is the *requested* window length rather than the longest entry -
    which is visible precisely because the last window is shorter than it.
    """
    body = subtitle_playlist(MEASURED_RUNTIME_TICKS, 30, "TOKEN")

    lines = body.splitlines()
    assert lines[:5] == [
        "#EXTM3U",
        "#EXT-X-TARGETDURATION:30",
        "#EXT-X-VERSION:3",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    assert lines[5] == "#EXTINF:30,"
    assert lines[6] == (
        "stream.vtt?CopyTimestamps=true&AddVttTimeMap=true"
        "&StartPositionTicks=0&EndPositionTicks=300000000&ApiKey=TOKEN"
    )
    entries = [line for line in lines if not line.startswith("#")]
    assert len(entries) == MEASURED_WINDOWS
    assert lines[-1] == "#EXT-X-ENDLIST"
    assert body.endswith("#EXT-X-ENDLIST\n")
    assert "\r" not in body


def test_the_last_window_is_the_remainder_and_its_end_is_the_runtime() -> None:
    """The grid advances by the requested length and the tail is what is left of the runtime."""
    lines = subtitle_playlist(MEASURED_RUNTIME_TICKS, 30, "TOKEN").splitlines()

    assert lines[-3] == "#EXTINF:7.851,"
    assert lines[-2].endswith(
        f"&StartPositionTicks=54000000000&EndPositionTicks={MEASURED_RUNTIME_TICKS}&ApiKey=TOKEN"
    )


def test_a_runtime_that_divides_exactly_has_no_partial_window() -> None:
    """Every `#EXTINF` a whole number, written the way the reference writes one - `30`, not
    `30.0`. The divergence below is visible on the last window and nowhere else."""
    lines = subtitle_playlist(120 * 10_000_000, 30, None).splitlines()

    assert [line for line in lines if line.startswith("#EXTINF")] == ["#EXTINF:30,"] * 4
    assert lines[6].endswith("&ApiKey="), "a caller with no token writes an empty parameter"


@pytest.mark.parametrize(("runtime", "window"), [(0, 30), (-1, 30), (10_000_000, 0)])
def test_a_playlist_needs_a_positive_runtime_and_a_positive_window(
    runtime: int, window: int
) -> None:
    """Both are the route's `400` before this is called; the guard is here because a window of
    zero would not terminate the loop."""
    with pytest.raises(ValueError, match="positive"):
        subtitle_playlist(runtime, window, "TOKEN")


@pytest.mark.parametrize(
    ("ticks", "text"),
    [
        (300_000_000, "30"),
        (78_510_000, "7.851"),
        (10_000_000, "1"),
        (12_345_678, "1.2345678"),
        (1, "0.0000001"),
    ],
)
def test_a_window_duration_is_written_with_a_point_and_no_trailing_zeros(
    ticks: int, text: str
) -> None:
    assert window_duration_text(ticks) == text


def test_ac16_the_decimal_point_survives_a_locale_that_writes_a_comma() -> None:
    """AC-16 and behaviours section 3.12, from below.

    The reference appends this number as a `double`, which formats in the **server's** culture:
    a Spanish-configured host writes `#EXTINF:7,851,`, which an HLS parser reads as a duration of
    `7` and a title of `851`. Atrium has no server locale to reproduce that from, so it writes the
    invariant point always - and this test is the only thing that can fail if that ever becomes a
    locale-sensitive format.

    The locale is set where the host has one; a host with none still runs the assertions, because
    Principle VII forbids a test that depends on the host's locale.
    """
    previous = locale.setlocale(locale.LC_ALL)
    applied = None
    try:
        for candidate in COMMA_LOCALES:
            try:
                locale.setlocale(locale.LC_ALL, candidate)
            except locale.Error:
                continue
            applied = candidate
            break
        body = subtitle_playlist(MEASURED_RUNTIME_TICKS, 30, "TOKEN")
    finally:
        locale.setlocale(locale.LC_ALL, previous)

    durations = [line for line in body.splitlines() if line.startswith("#EXTINF")]
    assert "#EXTINF:7.851," in durations, f"under {applied or 'the host locale'}"
    assert not any("," in line[len("#EXTINF:") : -1] for line in durations)
