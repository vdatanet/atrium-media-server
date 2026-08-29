# SPDX-License-Identifier: GPL-3.0-or-later
"""The encoder invocation: what a `Decision` means when a process has to carry it out.

`media/decision.py` answers *what* to produce - which streams survive, which are made again, and
inside what limits. This module answers *how to ask ffmpeg for exactly that*, and it is written
from the argument list up rather than translated from the reference's builder (Principle IV): the
reference assembles its command line across some thousands of lines of `EncodingHelper`, and
nothing here is a rendering of it. What is shared is the *observable*: the delivered bytes satisfy
the profile the negotiation was made against (AC-8), and nothing is upscaled (AC-9).

**Two shapes of output, decided by one property of the answer.**

* A **remux** - every stream copied - is produced to a file and then served whole, so its size is
  known before the first byte leaves. That is the deliberate divergence of [behaviours section
  3.3](../../../docs/compatibility/behaviours.md): the reference streams it chunked with
  `Accept-Ranges: none` even where the size is knowable, and Atrium sends the size and honours
  `Range` (spec section 3.5, AC-15).
* A **re-encode** is written to a pipe and streamed as it is produced, because its final length
  is not known until the last frame. That answer is chunked, exactly as the reference's is
  (AC-17), and the rule is *send the size when it is known*, never *invent one*.

**A pipe is not a file, and the mp4 family notices.** Writing mp4 to a non-seekable destination
means the index cannot be written last, so the fragmented flags go on - our own answer to our own
choice of pipe, and one the reference never has to make because it writes progressive output to a
file and streams the file as it grows. No client can tell the two apart: both are playable mp4,
and spec section 6 already declines to byte-compare produced output with the reference's, because
two encoders given the same instruction never agree.

**Every process this module starts is in a `ProductionLedger`.** A client that disconnects
mid-body must stop the work (AC-26), and "the response generator kills it in a `finally`" is a
claim a test can only check against something that holds the live set. The ledger is that
something; 008 T11's `TranscodeManager` keys sessions on top of it and starts its processes
through here, which is what keeps architecture section 4's "every ffmpeg has an owner" a sweep
rather than a discipline.

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.4 and 3.5, and plan section
6.5.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from atrium.domain.media import InspectedStream, MediaInspection, StreamKind
from atrium.media.decision import Decision, StreamAction, StreamPlan

#: How ffmpeg is invoked before anything else is said to it. `-nostdin` because the server has no
#: terminal to hand it, and a build that waits on stdin waits for ever.
PREAMBLE: Final[tuple[str, ...]] = (
    "-hide_banner",
    "-loglevel",
    "error",
    "-nostdin",
)

#: The destination that means "the standard output", which is what a chunked answer reads from.
PIPE: Final = "pipe:1"

#: The binary, looked up on PATH the way `media/probe.py` looks up its own. Absent, nothing can be
#: produced at all, and the request answers the same refusal an unmuxable container gets - which
#: is honest: an operator without ffmpeg has a server that cannot transcode, and saying so at the
#: one request that needed it is better than pretending at every other.
FFMPEG: Final = "ffmpeg"

#: Codec name to the encoder that produces it. Only the disagreements are listed: a codec whose
#: encoder is spelled the same way needs no row, and `_encoder_for` refuses anything in neither
#: place rather than passing a client's string through to the command line.
VIDEO_ENCODERS: Final[dict[str, str]] = {
    "h264": "libx264",
    "hevc": "libx265",
    "h265": "libx265",
    "vp8": "libvpx",
    "vp9": "libvpx-vp9",
    "av1": "libsvtav1",
    "theora": "libtheora",
    "mpeg4": "mpeg4",
    "mpeg2video": "mpeg2video",
    "wmv2": "wmv2",
}

AUDIO_ENCODERS: Final[dict[str, str]] = {
    "aac": "aac",
    "mp3": "libmp3lame",
    "opus": "libopus",
    "vorbis": "libvorbis",
    "flac": "flac",
    "alac": "alac",
    "ac3": "ac3",
    "eac3": "eac3",
    "dts": "dca",
    "wmav2": "wmav2",
}

#: Container name to the muxer that writes it. A container with no row here cannot be produced at
#: all, which is the measured refusal: `stream.banana` and `?container=banana` on a non-static
#: request both answer `500` in the third error shape, and so does `stream.mp3` on a film - a
#: muxer that cannot hold the streams it was handed is the same failure as a muxer that does not
#: exist `[probe: tools/probe_progressive_delivery.py, Jellyfin 10.11.11, 2026-08-29]`.
MUXERS: Final[dict[str, str]] = {
    "mp4": "mp4",
    "m4v": "mp4",
    "mov": "mov",
    "m4a": "ipod",
    "mkv": "matroska",
    "matroska": "matroska",
    "webm": "webm",
    "ts": "mpegts",
    "m2ts": "mpegts",
    "mpegts": "mpegts",
    "mp3": "mp3",
    "aac": "adts",
    "flac": "flac",
    "ogg": "ogg",
    "oga": "ogg",
    "opus": "opus",
    "asf": "asf",
    "avi": "avi",
    "3gp": "3gp",
}

#: The muxers whose index is written at the end of the file, so a non-seekable destination has to
#: be told to fragment instead. Everything else streams as it stands.
NEEDS_FRAGMENTING: Final[frozenset[str]] = frozenset({"mp4", "mov", "ipod", "3gp"})

#: What a fragmented destination is asked for: an empty index up front and a fragment per
#: keyframe, so a player can start on the first bytes rather than on the last.
FRAGMENT_FLAGS: Final[tuple[str, ...]] = (
    "-movflags",
    "frag_keyframe+empty_moov+default_base_moof",
)

#: The speed/size trade the x264 and x265 encoders are asked for. A server's constraint is
#: concurrent sessions rather than archive size, and the reference ships the same preference for
#: the same reason `[source: MediaBrowser.Model/Configuration/EncodingOptions.cs @ v10.11.11]`.
ENCODER_PRESET: Final[tuple[str, ...]] = ("-preset", "veryfast")
PRESET_TAKERS: Final[frozenset[str]] = frozenset({"libx264", "libx265"})

#: Bit depth to the pixel format that carries it. A `VideoBitDepth` ceiling is a condition the
#: ladder already reads, so the plan states a depth and this turns it into the one argument that
#: makes the output obey it - without which an eight-bit-only client asking for h264 would be
#: handed `high10` from a ten-bit source and refuse it at its own decoder, which is the failure
#: spec section 3.4 exists to prevent.
PIXEL_FORMATS: Final[dict[int, str]] = {8: "yuv420p", 10: "yuv420p10le", 12: "yuv420p12le"}

#: .NET ticks in one second - a start position arrives in ticks and ffmpeg wants seconds.
TICKS_PER_SECOND: Final = 10_000_000

#: How much is read from the pipe at a time. The same size `api/delivery.py` reads a file in, for
#: the same reason: small enough that a cancelled response stops promptly.
CHUNK_BYTES: Final = 64 * 1024


class ProductionError(RuntimeError):
    """Nothing can be produced for this request, or the encoder died before the first byte.

    One error for both because the observable is one answer: the reference refuses an
    unmuxable container and a failed invocation identically, with the third error shape at
    `500` (`api/delivery.py`).
    """


def executable() -> str:
    """An absolute path to ffmpeg, or the refusal that says why nothing can be produced."""
    found = shutil.which(FFMPEG)
    if found is None:
        raise ProductionError(
            f"{FFMPEG} is not on PATH, so nothing can be remuxed or re-encoded; `static=true` "
            f"delivery of the original bytes is unaffected"
        )
    return found


def muxer_for(container: str | None) -> str | None:
    """The muxer that writes this container, or `None` when nothing here can."""
    if not container:
        return None
    return MUXERS.get(container.strip().lstrip(".").lower())


def _encoder_for(codec: str | None, *, video: bool) -> str | None:
    """The encoder that produces this codec.

    A codec neither table knows answers `None` rather than being passed through: these strings
    arrive from a client's query parameters, and an argument list is not a place to forward one.
    """
    if not codec:
        return None
    table = VIDEO_ENCODERS if video else AUDIO_ENCODERS
    lowered = codec.strip().lower()
    return table.get(lowered)


@dataclass(frozen=True, slots=True)
class Output:
    """Where the produced bytes go, and what container they are written in."""

    container: str
    """The resolved output container - the path suffix, the `container` parameter, or what the
    measured fallback chain named (`api/delivery.py`)."""

    destination: str
    """A file path, or `PIPE`."""

    @property
    def seekable(self) -> bool:
        """Whether the muxer may write its index last. `False` is what forces fragmenting."""
        return self.destination != PIPE


def command(
    source: MediaInspection,
    decision: Decision,
    output: Output,
    *,
    path: str,
    start_ticks: int | None = None,
) -> list[str]:
    """The whole invocation for one delivery, from the plans the ladder made.

    `-ss` sits **before** the input, which is what makes a start position cost the seek rather
    than the decode: the reference restarts its encoder at the requested position rather than
    producing from zero and discarding, measured on a progressive URL where there is no playlist
    to seek in `[probe: tools/probe_progressive_delivery.py, Jellyfin 10.11.11, 2026-08-29]`.

    Raises `ProductionError` when the request names a container this server cannot mux into, or
    a codec it cannot encode to - the measured `500`.
    """
    muxer = muxer_for(output.container)
    if muxer is None:
        raise ProductionError(f"no muxer writes the container {output.container!r}")

    argv = [executable(), *PREAMBLE]
    if start_ticks:
        argv += ["-ss", _seconds(start_ticks)]
    argv += ["-i", path]

    wrote_any = False
    for plan, video in ((decision.video, True), (decision.audio, False)):
        if plan is None:
            continue
        argv += _stream_arguments(
            plan, _stream_of(source, plan.source_index), source.bitrate, video=video
        )
        wrote_any = True
    if not wrote_any:
        raise ProductionError("the decision plans no output stream")

    if not output.seekable and muxer in NEEDS_FRAGMENTING:
        argv += list(FRAGMENT_FLAGS)
    argv += ["-f", muxer, output.destination]
    return argv


def _seconds(ticks: int) -> str:
    """Ticks as the seconds ffmpeg reads, with the tick precision kept rather than rounded."""
    return f"{ticks / TICKS_PER_SECOND:.6f}"


def _stream_of(source: MediaInspection, index: int) -> InspectedStream | None:
    return next((one for one in source.streams if one.index == index), None)


def _stream_arguments(
    plan: StreamPlan,
    stream: InspectedStream | None,
    source_bitrate: int | None,
    *,
    video: bool,
) -> list[str]:
    """One stream's whole share of the command: which input stream, and what happens to it.

    **Every ceiling is passed only where it is below what arrived**, and that rule is the whole
    difference between a working encode and a refused one. A `StreamPlan` always states a number
    - `min(profile, source)`, and the source's own where the profile stated no limit - so passing
    each of them unconditionally means telling the encoder to reproduce the source exactly:
    `-ar 96000` at a `libmp3lame` that stops at 48 000, `-b:a 1500000` at one that stops at
    320 000. Both were measured as a `500` on the fixture matrix before this rule existed.

    Left out, ffmpeg negotiates a rate and a bitrate the encoder supports, which is what the
    reference's own invocation gets by leaving the same arguments off. Spec section 3.4 says the
    same thing from the other end: a ceiling is a limit, not a target, so a ceiling equal to the
    source is not an instruction.
    """
    selector = "v" if video else "a"
    argv = ["-map", f"0:{plan.source_index}"]
    if plan.action is StreamAction.COPY:
        return [*argv, f"-c:{selector}", "copy"]

    encoder = _encoder_for(plan.codec, video=video)
    if encoder is None:
        raise ProductionError(f"no encoder produces the codec {plan.codec!r}")
    argv += [f"-c:{selector}", encoder]
    if encoder in PRESET_TAKERS:
        argv += list(ENCODER_PRESET)

    arrived = None if stream is None else stream.bitrate
    if _below(plan.bitrate, arrived if arrived is not None else source_bitrate):
        argv += [f"-b:{selector}", str(plan.bitrate)]

    if video:
        argv += _video_encode_arguments(plan, stream)
    else:
        if _below(plan.channels, None if stream is None else stream.channels):
            argv += ["-ac", str(plan.channels)]
        if _below(plan.sample_rate, None if stream is None else stream.sample_rate):
            argv += ["-ar", str(plan.sample_rate)]
    return argv


def _below(planned: int | None, arrived: int | None) -> bool:
    """Whether the plan asks for less than the source has, which is when it is worth saying.

    An unknown source value answers `False`: the plan then carries the source's own number
    (`_clamped` passes it through), so there is nothing to constrain and the encoder's own choice
    is better informed than ours.
    """
    return planned is not None and arrived is not None and planned < arrived


def _video_encode_arguments(plan: StreamPlan, stream: InspectedStream | None) -> list[str]:
    """The scale filter and the pixel format, each only where it changes something.

    **The filter is added only when the plan is smaller than the source**, which is AC-9 read
    from the other side: a 720p source under a 1080p ceiling plans 720p, the plan equals the
    stream, and no filter appears at all - so there is nothing that could scale it up. The box is
    fitted rather than stretched (`force_original_aspect_ratio=decrease`) and rounded to even
    dimensions, because an encoder handed an odd height refuses the whole job.

    The pixel format follows the same rule: stated only where the profile asked for **fewer** bits
    than the source has, which is spec section 3.4's "never more bits than it arrived with" read
    as an instruction rather than as a restatement.
    """
    argv: list[str] = []
    fits = _shrinks(plan, stream)
    if fits is not None:
        width, height = fits
        argv += [
            "-vf",
            f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
        ]
    arrived = None if stream is None else stream.bit_depth
    if _below(plan.bit_depth, arrived) and plan.bit_depth in PIXEL_FORMATS:
        argv += ["-pix_fmt", PIXEL_FORMATS[plan.bit_depth]]
    return argv


def _shrinks(plan: StreamPlan, stream: InspectedStream | None) -> tuple[int, int] | None:
    """The box to fit into, or `None` when the plan asks for the size the source already is."""
    if plan.width is None or plan.height is None:
        return None
    if (
        stream is not None
        and plan.width >= (stream.width or 0)
        and plan.height >= (stream.height or 0)
    ):
        return None
    return plan.width, plan.height


def default_stream_indexes(source: MediaInspection, *, is_video: bool) -> tuple[int | None, int]:
    """The streams a request that names none is about: the first video, and the default audio.

    Returned as a pair rather than looked up twice, because a plan that addressed one stream and
    a command that mapped another would be a silent mismatch - `-map 0:{index}` is the only place
    the number is ever used.
    """
    video = None
    if is_video:
        video = next((one.index for one in source.streams if one.kind is StreamKind.VIDEO), None)
    audio = next((one.index for one in source.streams if one.kind is StreamKind.AUDIO), 0)
    return video, audio


# ------------------------------------------------------------------------------------------------
# Running one, and knowing that it stopped
# ------------------------------------------------------------------------------------------------


@dataclass(slots=True, eq=False)
class Production:
    """One running ffmpeg, and the ledger row that outlives nothing."""

    argv: tuple[str, ...]
    process: asyncio.subprocess.Process

    async def stop(self) -> None:
        """Kill it if it is still running, and reap it if the caller is still allowed to wait.

        `kill` rather than `terminate`: the process being stopped is producing into a pipe nobody
        is reading any more, so it is blocked on a write that a polite signal would leave it
        sitting in.

        **The kill is synchronous and the reap is not, and the order is the whole point.** This
        runs from the `finally` of a response body that a disconnect has just cancelled, and in a
        cancelled task the very next `await` raises `CancelledError` again - so a version that
        waited first would signal nothing at all. The suppression covers that re-raise only;
        whatever cancelled this caller goes on propagating once the block ends, and the event
        loop reaps the child on its own either way.
        """
        if self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.process.kill()
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await self.process.wait()


@dataclass(slots=True)
class ProductionLedger:
    """Every ffmpeg this application has started and not yet reaped.

    One per application, reached the way `api/images.py` reaches its cache. It exists so that "a
    disconnected client stops the work" is a property something can be *asked about* rather than
    a comment beside a `finally` - AC-26's assertion is that this set empties.

    008 T11's `TranscodeManager` keys sessions by `PlaySessionId` on top of this; the ledger stays
    the lower layer, which is the whole set rather than the ones a session claims.
    """

    live: set[Production] = field(default_factory=set)

    async def start(self, argv: Sequence[str], *, to_pipe: bool) -> Production:
        """Launch one, recorded from the moment it exists.

        `shell=False` by construction - `create_subprocess_exec` takes an argument vector, and
        every element of it came from `command()`'s own tables rather than from a client's
        string.
        """
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE if to_pipe else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        running = Production(argv=tuple(argv), process=process)
        self.live.add(running)
        return running

    async def finish(self, running: Production) -> None:
        """Forget it, then stop it. Safe to call twice.

        Discarded **before** the stop, because the stop may be cancelled halfway and a ledger that
        still listed a process nobody is waiting for would say the server is producing when it is
        not - which is the one thing this set exists to answer.
        """
        self.live.discard(running)
        await running.stop()

    async def shutdown(self) -> None:
        for running in list(self.live):
            await self.finish(running)


__all__ = [
    "AUDIO_ENCODERS",
    "CHUNK_BYTES",
    "ENCODER_PRESET",
    "FFMPEG",
    "FRAGMENT_FLAGS",
    "MUXERS",
    "NEEDS_FRAGMENTING",
    "PIPE",
    "PIXEL_FORMATS",
    "PREAMBLE",
    "TICKS_PER_SECOND",
    "VIDEO_ENCODERS",
    "Output",
    "Production",
    "ProductionError",
    "ProductionLedger",
    "command",
    "default_stream_indexes",
    "executable",
    "muxer_for",
]
