# SPDX-License-Identifier: GPL-3.0-or-later
"""The command a `Decision` turns into, asserted as a value rather than by running it.

`tests/conformance/test_progressive_delivery.py` runs real encoders over real fixtures and
inspects the bytes; this file is the other half, and it is the one that can state the *reasons*.
A scale filter that appears when the plan equals the source would still produce a correct-looking
file - it would just quietly re-encode a stream that needed nothing - and only an assertion about
the argument list can say so.

No `ffmpeg` marker: nothing here starts a process. `media.ffmpeg.command` resolves the binary on
PATH, which is the one thing that would need it, so each test that builds a command is given a
resolver that answers without looking.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atrium.domain.media import InspectedStream, MediaInspection, StreamKind
from atrium.media import ffmpeg
from atrium.media.decision import Decision, Outcome, StreamAction, StreamPlan

pytestmark = pytest.mark.usefixtures("resolved_binary")

SOURCE_PATH = "/library/Film.mkv"


@pytest.fixture
def resolved_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    """`shutil.which` without a filesystem, so these stay pure value assertions."""
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: f"/usr/bin/{name}")


def _video(**overrides: object) -> InspectedStream:
    values: dict[str, object] = {
        "index": 0,
        "kind": StreamKind.VIDEO,
        "codec": "h264",
        "width": 1280,
        "height": 720,
        "bit_depth": 8,
    }
    values.update(overrides)
    return InspectedStream(**values)  # type: ignore[arg-type]


def _audio(**overrides: object) -> InspectedStream:
    values: dict[str, object] = {
        "index": 1,
        "kind": StreamKind.AUDIO,
        "codec": "ac3",
        "channels": 6,
        "sample_rate": 48000,
    }
    values.update(overrides)
    return InspectedStream(**values)  # type: ignore[arg-type]


def _source(*streams: InspectedStream) -> MediaInspection:
    return MediaInspection(
        size=1,
        mtime_ns=1,
        container="matroska,webm",
        format_names="matroska,webm",
        probed_at=datetime(2026, 8, 29, tzinfo=UTC),
        runtime_ticks=40_000_000,
        bitrate=None,
        video_keyframes=(),
        streams=tuple(streams),
    )


def _decision(
    video: StreamPlan | None, audio: StreamPlan | None, outcome: Outcome = Outcome.TRANSCODE
) -> Decision:
    return Decision(
        outcome=outcome,
        reasons=(),
        container="mp4",
        sub_protocol="http",
        video=video,
        audio=audio,
        supports_transcoding=True,
    )


def _pairs(argv: list[str]) -> list[tuple[str, str]]:
    """The command as (option, value) pairs, so an assertion names both."""
    return [(argv[i], argv[i + 1]) for i in range(len(argv) - 1)]


# ------------------------------------------------------------------------------------------
# Copying, which is the whole of a remux
# ------------------------------------------------------------------------------------------


def test_a_copy_plan_asks_for_a_copy_and_nothing_else() -> None:
    source = _source(_video(), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.COPY, codec="h264"),
        StreamPlan(source_index=1, action=StreamAction.COPY, codec="ac3"),
        outcome=Outcome.REMUX,
    )

    argv = ffmpeg.command(
        source, decision, ffmpeg.Output("mkv", "/scratch/out.mkv"), path=SOURCE_PATH
    )

    assert ("-c:v", "copy") in _pairs(argv)
    assert ("-c:a", "copy") in _pairs(argv)
    assert "-vf" not in argv
    assert "-b:v" not in argv
    assert argv[-3:] == ["-f", "matroska", "/scratch/out.mkv"]


def test_the_mapped_streams_are_the_ones_the_plan_names() -> None:
    """`-map 0:{index}` is the only place a stream index is used, so a plan about stream 3 and a
    command about stream 1 would be a silent mismatch rather than a failure."""
    source = _source(_video(), _audio(index=3))
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.COPY, codec="h264"),
        StreamPlan(source_index=3, action=StreamAction.COPY, codec="ac3"),
        outcome=Outcome.REMUX,
    )

    argv = ffmpeg.command(
        source, decision, ffmpeg.Output("mkv", "/scratch/out.mkv"), path=SOURCE_PATH
    )

    assert [value for option, value in _pairs(argv) if option == "-map"] == ["0:0", "0:3"]


def test_the_map_names_the_demuxer_stream_and_not_the_wire_one() -> None:
    """**The one place the two numberings meet in this module, and it read the wrong one.**

    A plan's `source_index` is the *wire* index: the number a client sends as `AudioStreamIndex`,
    the number `DefaultAudioStreamIndex` states back, the number the transcoding URL repeats.
    `-map 0:N` counts the **demuxer's** streams, and 011 made the two part company - a subtitle
    file discovered beside the media is numbered ahead of the container's own, so every stream
    inside the file gains one wire index per discovered file. `media/extract.py` has said
    `0:{file_index}` since T6; this line said `0:{index}` until T12.

    The test above cannot reach this: an `InspectedStream` mirrors an unstated `file_index` onto
    its `index`, so a source built the ordinary way agrees with itself whichever number is used.
    Here the two are stated apart, which is the state `renumber` really produces.
    """
    source = _source(_video(index=1, file_index=0), _audio(index=2, file_index=1))
    decision = _decision(
        StreamPlan(source_index=1, action=StreamAction.COPY, codec="h264"),
        StreamPlan(source_index=2, action=StreamAction.COPY, codec="ac3"),
        outcome=Outcome.REMUX,
    )

    argv = ffmpeg.command(
        source, decision, ffmpeg.Output("mkv", "/scratch/out.mkv"), path=SOURCE_PATH
    )

    assert [value for option, value in _pairs(argv) if option == "-map"] == ["0:0", "0:1"]


# ------------------------------------------------------------------------------------------
# Encoding, and the arguments that are only there when they change something
# ------------------------------------------------------------------------------------------


def test_an_encode_names_the_encoder_rather_than_the_codec() -> None:
    """The client asks for `h264`; ffmpeg is asked for `libx264`. A table, because the two
    vocabularies genuinely differ and a pass-through would put a client's string in an argv."""
    source = _source(_video(bitrate=4_000_000), _audio(bitrate=448_000))
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.ENCODE, codec="h264", bitrate=800_000),
        StreamPlan(source_index=1, action=StreamAction.ENCODE, codec="aac", channels=2),
    )

    argv = ffmpeg.command(source, decision, ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH)

    pairs = _pairs(argv)
    assert ("-c:v", "libx264") in pairs
    assert ("-c:a", "aac") in pairs
    assert ("-b:v", "800000") in pairs
    assert ("-ac", "2") in pairs


def test_a_ceiling_equal_to_the_source_is_not_passed_to_the_encoder() -> None:
    """The rule that turned two `500`s into two working encodes on the fixture matrix. A plan
    always states a number - the source's own where the profile stated no limit - so passing them
    all means asking `libmp3lame` for 96 kHz, which it does not have. Left out, ffmpeg picks a
    rate and a bitrate the encoder supports."""
    source = _source(_audio(codec="flac", channels=2, sample_rate=96000, bitrate=1_500_000))
    decision = _decision(
        None,
        StreamPlan(
            source_index=1,
            action=StreamAction.ENCODE,
            codec="mp3",
            bitrate=1_500_000,
            channels=2,
            sample_rate=96000,
        ),
    )

    argv = ffmpeg.command(source, decision, ffmpeg.Output("mp3", ffmpeg.PIPE), path=SOURCE_PATH)

    assert "-ar" not in argv
    assert "-ac" not in argv
    assert "-b:a" not in argv


def test_ac9_no_scale_filter_appears_when_the_plan_is_the_size_the_source_already_is() -> None:
    """AC-9 from the other side. A 720p source under a 1080p ceiling plans 720p, so there is no
    filter at all - which is what makes "nothing is upscaled" structural rather than arithmetic."""
    source = _source(_video(width=1280, height=720), _audio())
    decision = _decision(
        StreamPlan(
            source_index=0, action=StreamAction.ENCODE, codec="h264", width=1280, height=720
        ),
        None,
    )

    argv = ffmpeg.command(source, decision, ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH)

    assert "-vf" not in argv


def test_a_smaller_plan_fits_the_box_rather_than_stretching_to_it() -> None:
    source = _source(_video(width=1280, height=720), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.ENCODE, codec="h264", width=640, height=360),
        None,
    )

    argv = ffmpeg.command(source, decision, ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH)

    filters = dict(_pairs(argv))["-vf"]
    assert filters.startswith("scale=w=640:h=360")
    assert "force_original_aspect_ratio=decrease" in filters
    assert "force_divisible_by=2" in filters


@pytest.mark.parametrize(
    ("planned", "source_depth", "expected"),
    [(8, 10, "yuv420p"), (10, 12, "yuv420p10le"), (10, 10, None), (None, 10, None), (8, 8, None)],
)
def test_the_pixel_format_is_stated_only_where_it_takes_bits_away(
    planned: int | None, source_depth: int, expected: str | None
) -> None:
    """AC-8's other half, and the rule the whole encode side follows: an argument is passed only
    where it asks for **less** than the source has. A ten-bit-only client asking for h264 from a
    ten-bit source is told nothing, because there is nothing to constrain; an eight-bit one is
    told `yuv420p`, without which libx264 would hand it `high10` and it would refuse at its own
    decoder."""
    source = _source(_video(bit_depth=source_depth), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.ENCODE, codec="h264", bit_depth=planned),
        None,
    )

    argv = ffmpeg.command(source, decision, ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH)

    if expected is None:
        assert "-pix_fmt" not in argv
    else:
        assert ("-pix_fmt", expected) in _pairs(argv)


# ------------------------------------------------------------------------------------------
# Where the output goes, and where the input starts
# ------------------------------------------------------------------------------------------


def test_a_start_position_is_asked_for_before_the_input() -> None:
    """`-ss` after `-i` decodes and discards; before it, it seeks. Spec section 3.4 says
    production starts where the client asked, and this is the argument that makes it true."""
    source = _source(_video(), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.COPY, codec="h264"), None, Outcome.REMUX
    )

    argv = ffmpeg.command(
        source,
        decision,
        ffmpeg.Output("mkv", "/scratch/out.mkv"),
        path=SOURCE_PATH,
        start_ticks=60_000_000,
    )

    assert argv.index("-ss") < argv.index("-i")
    assert dict(_pairs(argv))["-ss"] == "6.000000"


def test_a_pipe_destination_fragments_the_mp4_family_and_a_file_does_not() -> None:
    """The index cannot be written last to something that cannot be seeked, so a piped mp4 is
    fragmented. A file is not, because nothing forces it to be."""
    source = _source(_video(), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.COPY, codec="h264"), None, Outcome.REMUX
    )

    piped = ffmpeg.command(source, decision, ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH)
    filed = ffmpeg.command(
        source, decision, ffmpeg.Output("mp4", "/scratch/out.mp4"), path=SOURCE_PATH
    )

    assert "-movflags" in piped
    assert "-movflags" not in filed


def test_a_piped_matroska_is_not_fragmented_because_it_never_needed_to_be() -> None:
    source = _source(_video(), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.COPY, codec="h264"), None, Outcome.REMUX
    )

    argv = ffmpeg.command(source, decision, ffmpeg.Output("mkv", ffmpeg.PIPE), path=SOURCE_PATH)

    assert "-movflags" not in argv


# ------------------------------------------------------------------------------------------
# What cannot be produced at all - the measured 500
# ------------------------------------------------------------------------------------------


def test_a_container_no_muxer_writes_is_refused_rather_than_guessed() -> None:
    """`stream.banana` is a `500` on the reference, and this is where that decision is made: a
    container name is not passed through to an argument list on the chance that ffmpeg knows it."""
    source = _source(_video(), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.COPY, codec="h264"), None, Outcome.REMUX
    )

    with pytest.raises(ffmpeg.ProductionError):
        ffmpeg.command(source, decision, ffmpeg.Output("banana", ffmpeg.PIPE), path=SOURCE_PATH)


def test_a_codec_no_encoder_produces_is_refused_for_the_same_reason() -> None:
    source = _source(_video(), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.ENCODE, codec="banana"), None
    )

    with pytest.raises(ffmpeg.ProductionError):
        ffmpeg.command(source, decision, ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH)


def test_a_decision_that_plans_no_stream_produces_nothing() -> None:
    source = _source(_video(), _audio())

    with pytest.raises(ffmpeg.ProductionError):
        ffmpeg.command(
            source, _decision(None, None), ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH
        )


def test_the_missing_binary_is_the_same_refusal_and_says_static_still_works() -> None:
    """An operator without ffmpeg has a server that cannot transcode and can still serve files.
    Saying so at the request that needed it beats failing at every other."""
    source = _source(_video(), _audio())
    decision = _decision(
        StreamPlan(source_index=0, action=StreamAction.COPY, codec="h264"), None, Outcome.REMUX
    )

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(ffmpeg.shutil, "which", lambda name: None)
        with pytest.raises(ffmpeg.ProductionError, match="static"):
            ffmpeg.command(source, decision, ffmpeg.Output("mp4", ffmpeg.PIPE), path=SOURCE_PATH)


# ------------------------------------------------------------------------------------------
# The tables themselves
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("container", "muxer"),
    [("mp4", "mp4"), ("mkv", "matroska"), ("ts", "mpegts"), ("m4a", "ipod"), ("MP4", "mp4")],
)
def test_the_muxer_table_answers_the_containers_a_transcoding_url_names(
    container: str, muxer: str
) -> None:
    assert ffmpeg.muxer_for(container) == muxer


@pytest.mark.parametrize("absent", [None, "", "banana"])
def test_a_container_the_table_does_not_hold_answers_nothing(absent: str | None) -> None:
    assert ffmpeg.muxer_for(absent) is None


# ------------------------------------------------------------------------------------------
# The container that states its own length - 008 T9
# ------------------------------------------------------------------------------------------


def test_a_self_sizing_container_is_refused_to_a_pipe_rather_than_left_to_lie() -> None:
    """A `wav` muxer writing to a pipe fills both of its size fields with `ffffffff` and exits
    `0`, so nothing downstream would have noticed. The refusal is here rather than in the caller
    because the caller's alternative is a `200` whose header claims four gigabytes.

    The measurement itself - the two invocations, and the eight bytes they differ in - is in
    `tests/conformance/test_wav_delivery.py`, which is where a real encoder may run.
    """
    source = _source(_audio(codec="flac"))
    decision = _decision(
        None, StreamPlan(source_index=1, action=StreamAction.ENCODE, codec="pcm_s16le")
    )

    with pytest.raises(ffmpeg.ProductionError, match="length"):
        ffmpeg.command(source, decision, ffmpeg.Output("wav", ffmpeg.PIPE), path=SOURCE_PATH)


def test_the_same_wav_output_builds_to_a_seekable_destination() -> None:
    """The other side of that refusal, so the test above cannot be passing because everything is
    refused: the identical decision to a file builds, names the PCM encoder and the wav muxer."""
    source = _source(_audio(codec="flac"))
    decision = _decision(
        None, StreamPlan(source_index=1, action=StreamAction.ENCODE, codec="pcm_s16le")
    )

    argv = ffmpeg.command(
        source, decision, ffmpeg.Output("wav", "/scratch/out.wav"), path=SOURCE_PATH
    )

    assert argv[-3:] == ["-f", "wav", "/scratch/out.wav"]
    assert ("-c:a", "pcm_s16le") in _pairs(argv)


@pytest.mark.parametrize(
    ("container", "codec"),
    [("wav", "pcm_s16le"), (".WAV", "pcm_s16le"), ("flac", None), ("", None), (None, None)],
)
def test_only_a_raw_sample_container_names_its_own_codec(
    container: str | None, codec: str | None
) -> None:
    """The row the reference's own inference table has not got. Everything else keeps falling
    back to the source's codec, which is what makes a bare `stream.mkv` a remux."""
    assert ffmpeg.raw_codec_for(container) == codec


@pytest.mark.parametrize(
    ("container", "seeking"), [("wav", True), ("mp4", False), ("mp3", False), ("banana", False)]
)
def test_only_a_self_sizing_container_has_to_be_written_somewhere_seekable(
    container: str, seeking: bool
) -> None:
    assert ffmpeg.needs_seeking(container) is seeking
