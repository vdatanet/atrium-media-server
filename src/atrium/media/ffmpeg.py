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

**Except where the container states its own length, and then there is no choice at all** (008
T9). A `wav` output begins `RIFF` and four bytes of size, and states a second length on its
`data` chunk; written to a pipe ffmpeg fills both with `ffffffff`, because it can never go back
to correct them. So `NEEDS_SEEKING` is not a preference
between two working shapes the way `NEEDS_FRAGMENTING` is - it is the difference between the
divergence behaviours section 3.2 decided ("a real RIFF header, a real `Content-Length`, `Range`
support") and a header that lies. `command` refuses to build the piped form rather than leaving
it to a caller to remember.

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
import logging
import shutil
import signal
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from atrium.domain.media import InspectedStream, MediaInspection, StreamKind
from atrium.media.decision import Decision, StreamAction, StreamPlan

logger = logging.getLogger("atrium.media")

#: How many of an encoder's last diagnostic lines are kept. Bounded because the point is the
#: reason it stopped, and a build that fails on every frame would otherwise be held whole in
#: memory for the length of a film.
STDERR_LINES_KEPT: Final = 20

#: How much of it is read at a time, and the longest run without a newline that is kept.
STDERR_BLOCK_BYTES: Final = 4096

#: The two job-control signals the throttle uses, or `None` where the platform has neither. The
#: reference pauses by writing a key to ffmpeg's standard input, which this server has already
#: closed with `-nostdin`; stopping the process produces the one thing a client can observe -
#: the output stops growing - without caring which ffmpeg build is running (008 spec section 3.4).
SUSPEND: Final[int | None] = getattr(signal, "SIGSTOP", None)
CONTINUE: Final[int | None] = getattr(signal, "SIGCONT", None)

#: How long a finished production's reader is given to reach the end of a pipe whose writer is
#: already dead. Generous, because it is never spent: the wait exists so that a reader still
#: holding buffered bytes is not cancelled out from under the log line that wanted them.
DRAIN_GRACE_SECONDS: Final = 5.0

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
    # The raw-sample family, and the reason behaviours section 3.2 exists: these encoders emit
    # samples with no header of their own, so everything that makes the output playable comes
    # from the muxer. Six rows because six sample formats are what the WAVE `fmt ` chunk can
    # declare - a `pcm_*` spelling outside them is refused here rather than passed through to a
    # command line, which is `_encoder_for`'s rule for every other codec.
    "pcm_u8": "pcm_u8",
    "pcm_s16le": "pcm_s16le",
    "pcm_s24le": "pcm_s24le",
    "pcm_s32le": "pcm_s32le",
    "pcm_f32le": "pcm_f32le",
    "pcm_f64le": "pcm_f64le",
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
    "wav": "wav",
}

#: The muxers whose index is written at the end of the file, so a non-seekable destination has to
#: be told to fragment instead. Everything else streams as it stands.
NEEDS_FRAGMENTING: Final[frozenset[str]] = frozenset({"mp4", "mov", "ipod", "3gp"})

#: Segment container to what the HLS muxer calls that shape, and the fallback for everything
#: else. **The fallback is the reference's**, not a refusal: it logs "Invalid HLS segment
#: container, default to mpegts" and carries on, so a playlist naming an unknown container gets
#: MPEG-TS bytes behind that container's own extension `[source:
#: Jellyfin.Api/Controllers/DynamicHlsController.cs:1622-1651 @ v10.11.11]`.
SEGMENT_FORMATS: Final[dict[str, str]] = {"ts": "mpegts", "mp4": "fmp4"}
DEFAULT_SEGMENT_FORMAT: Final = "mpegts"

#: The segment index that names the fMP4 initialisation segment rather than a body segment. The
#: media playlist's `#EXT-X-MAP` points at it and ffmpeg writes it under this name beside the
#: playlist `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`.
INITIALISATION_INDEX: Final = -1

#: The encoders that honour `-force_key_frames` and therefore get the segment grid stated to
#: them; the reference sets the grid by GOP for the hardware ones instead, and v1 has no hardware
#: encoding at all `[source:
#: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:1948-2010 @ v10.11.11]`.
KEYFRAME_FORCERS: Final[frozenset[str]] = frozenset({"libx264", "libx265"})

#: The muxers that state a length in a header they can only fill in at the end, and have **no**
#: fragmented form to fall back on - so a non-seekable destination makes them declare a length
#: that is not the body's. `wav` writes `RIFF` followed by four bytes of size: to a file that is
#: the real size, to a pipe it is `ffffffff`, measured on both. That is why the divergence of
#: behaviours section 3.2 - "a real RIFF header, a real `Content-Length`, `Range` support" -
#: cannot be served out of a pipe at all, and why `command` refuses to build one rather than
#: producing a header that lies.
NEEDS_SEEKING: Final[frozenset[str]] = frozenset({"wav"})

#: The codec a container carries when nothing named one, for the containers whose *only* codec is
#: raw samples. One row, because `wav` is the one such container in this feature's surface, and it
#: is the row the reference's own inference is missing: `InferAudioCodec` answers an unlisted
#: container with the container's own name, so `stream.wav` asks for an encoder called `wav` and
#: the request dies before its first byte `[source:
#: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:667-684 @ v10.11.11]`,
#: `[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-29]`. Sixteen-bit because
#: that is what a WAVE file means to every decoder that reads one, and because spec section 3.6
#: already says the target codec is what decides the delivered depth.
RAW_SAMPLE_CODECS: Final[dict[str, str]] = {"wav": "pcm_s16le"}

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


def raw_codec_for(container: str | None) -> str | None:
    """The codec a raw-sample container carries, or `None` for every other container.

    Asked *before* falling back to the source's own codec, because a container that holds nothing
    but raw samples cannot hold the source's codec by definition. Without this a bare
    `stream.wav` copies: ffmpeg's wav muxer accepts a FLAC stream under a codec tag and writes a
    genuine `RIFF` header over it, so the answer would pass a "starts with RIFF" check and be
    unplayable by every wav decoder there is - measured locally, 2026-08-29.
    """
    if not container:
        return None
    return RAW_SAMPLE_CODECS.get(container.strip().lstrip(".").lower())


def needs_seeking(container: str | None) -> bool:
    """Whether this container has to be produced somewhere its muxer can seek back into.

    The property that decides which of the two delivery shapes carries the output: `True` means
    a file and therefore a `Content-Length` and a `Range`, because the alternative is not a
    chunked answer but a header stating the wrong length (`NEEDS_SEEKING`).
    """
    return muxer_for(container) in NEEDS_SEEKING


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
    if not output.seekable and muxer in NEEDS_SEEKING:
        # Refused rather than built, because the command would *succeed* and produce a header
        # whose length field is `ffffffff`. A caller that reaches here has chosen the chunked
        # shape for a container that cannot honestly take it, which is a mistake in this
        # repository rather than in the request - and one no response could show.
        raise ProductionError(
            f"the container {output.container!r} states its own length and cannot be written to "
            f"a pipe"
        )

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


@dataclass(frozen=True, slots=True)
class SegmentOutput:
    """Where one session's segments are written, and on what grid.

    Not an `Output`: the destination is a *directory* full of numbered files rather than one
    place bytes go, and the muxer arguments that produce them have no counterpart in the
    progressive shape.
    """

    container: str
    """The segment container - `ts` or `mp4`. What `segmentContainer` named, not the path's own
    extension: those two disagree freely and only this one decides what is produced
    `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`."""

    directory: Path
    """The session's scratch. Segments land here as `{index}{extension}`."""

    extension: str
    """The suffix produced files carry, dot included. Passed in rather than derived from
    `container` because `media/hls.segment_extension` is what the playlist's URIs are built from,
    and a second derivation here is a second chance for the file a request looks for and the file
    ffmpeg writes to be spelled differently."""

    start_number: int
    """The index the first produced segment is named with - ffmpeg's `-start_number`, and the
    only thing the requested index decides. Where production *begins* is the start position,
    which arrives separately."""

    cadence_ticks: int
    """The planned segment length, the same number `media/hls.plan_segments` laid the playlist
    out on."""

    @property
    def playlist(self) -> Path:
        """ffmpeg's own playlist. Written and never served - `api/dynamic_hls.py` answers from
        the plan - but the muxer needs an output path, and it is what names the init segment's
        directory for the fMP4 shape."""
        return self.directory / "main.m3u8"


def segment_command(
    source: MediaInspection,
    decision: Decision,
    output: SegmentOutput,
    *,
    path: str,
    start_ticks: int | None = None,
) -> list[str]:
    """One session's whole invocation: the same stream plans, muxed into numbered segments.

    **The grid is stated to the encoder, so the playlist's promise and the produced bytes cannot
    drift.** Both `-hls_time` and the forced-keyframe expression take the *planned* cadence -
    `media/hls.cadence_milliseconds`' answer - where the reference states its unscaled integer
    request to ffmpeg and the scaled one to the playlist, and lets the two differ by the four
    milliseconds a fractional frame rate costs `[source:
    Jellyfin.Api/Controllers/DynamicHlsController.cs:1425-1432,1667-1680 @ v10.11.11]`. Spec
    section 3.7 rule 2 asks for the opposite - "the playlist's declared duration matches what is
    delivered" - and nothing observes the difference except a seek bar that would otherwise
    accumulate 11 seconds of error over a two-hour film.

    `-copyts` is what makes a restart land on the same grid as the first run: the forced
    keyframes are expressed in the input's own timeline, so production restarted at 300 seconds
    cuts where production from zero would have cut.
    """
    argv = [executable(), *PREAMBLE]
    if start_ticks:
        argv += ["-ss", _seconds(start_ticks)]
    argv += ["-i", path]
    # No metadata and no chapters in a segment, which is the reference's own choice and saves
    # repeating a file's tags across every one of two thousand of them.
    argv += ["-map_metadata", "-1", "-map_chapters", "-1"]

    cadence = output.cadence_ticks / TICKS_PER_SECOND
    wrote_any = False
    for plan, video in ((decision.video, True), (decision.audio, False)):
        if plan is None:
            continue
        argv += _stream_arguments(
            plan, _stream_of(source, plan.source_index), source.bitrate, video=video
        )
        if video:
            argv += _grid_arguments(plan, cadence)
        wrote_any = True
    if not wrote_any:
        raise ProductionError("the decision plans no output stream")

    argv += ["-copyts", "-avoid_negative_ts", "disabled"]
    segment_format = SEGMENT_FORMATS.get(output.container.lower(), DEFAULT_SEGMENT_FORMAT)
    argv += ["-f", "hls", "-hls_time", f"{cadence:.6f}", "-hls_segment_type", segment_format]
    if segment_format == "fmp4":
        # A name rather than a path: ffmpeg writes it beside the playlist, which is the session's
        # own scratch, and it is the file the `#EXT-X-MAP` line points at.
        argv += ["-hls_fmp4_init_filename", f"{INITIALISATION_INDEX}{output.extension}"]
    argv += [
        "-hls_playlist_type",
        "vod",
        "-hls_list_size",
        "0",
        "-start_number",
        str(output.start_number),
        "-hls_segment_filename",
        str(output.directory / f"%d{output.extension}"),
        "-y",
        str(output.playlist),
    ]
    return argv


def _grid_arguments(plan: StreamPlan, cadence: float) -> list[str]:
    """Where the video is cut, stated only where this server is the one deciding.

    A copy cuts where the source already has keyframes, so there is nothing to force and
    `-start_at_zero` is what the reference sends instead. A re-encode is asked for a keyframe on
    every boundary, and libx264 is additionally told not to insert its own on a scene change -
    without which its post-processing moves the boundary the expression just placed.
    """
    if plan.action is StreamAction.COPY:
        return ["-start_at_zero"]
    argv = ["-force_key_frames:v:0", f"expr:gte(t,n_forced*{cadence:.6f})"]
    if _encoder_for(plan.codec, video=True) in KEYFRAME_FORCERS:
        argv += ["-sc_threshold:v:0", "0"]
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
    argv = ["-map", f"0:{_demuxer_index(plan, stream)}"]
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


def _demuxer_index(plan: StreamPlan, stream: InspectedStream | None) -> int:
    """Which stream of the **file** `-map` names, which is not the number the plan carries.

    A plan's `source_index` is the **wire** index: the number a client sends as
    `AudioStreamIndex`, the number `DefaultAudioStreamIndex` states back and the number the
    transcoding URL repeats. ffmpeg's `0:N` counts the *demuxer's* streams, and 011 made the two
    part company - a subtitle file discovered beside the media is numbered ahead of the
    container's own, so every stream inside the file gains one wire index per discovered file
    (`domain/media.renumber`). Mapping the wire number would hand `-c:v copy` the audio track on
    every film with an `.srt` beside it.

    `media/extract.py` has said `0:{file_index}` since 011 T6 and this line said `0:{index}`
    until 011 T12, which is the whole of the bug: the two numberings meet in exactly two places
    and only one of them knew it.

    A plan whose index names no stream keeps the number it was given - there is nothing to
    translate it with, and the command was going to name a stream the file has not got either
    way.
    """
    return plan.source_index if stream is None else stream.file_index


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
    a command that mapped another would be a silent mismatch.

    **Wire indexes, like every other number a plan carries**: what a client sends and what the
    answer states back. `_demuxer_index` is where that number becomes the one ffmpeg counts, and
    it is the only place the two numberings meet here.
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
    complaints: deque[str] = field(default_factory=lambda: deque(maxlen=STDERR_LINES_KEPT))
    """The encoder's last words, filled by `drain` while it runs.

    **A pipe nobody reads is a pipe that fills**, and a process blocked writing into a full one
    never exits: it stops producing, the request waiting on its output waits for ever, and the
    kill paths of 008 T12 arrive at a process that cannot be reaped by asking it nicely. At
    `-loglevel error` an encode that goes well says nothing at all, which is exactly why the
    hazard survived three tasks - it needs an encode that goes *badly*, over a film's length,
    to show itself.
    """

    reader: asyncio.Task[None] | None = None
    """The task doing that reading, cancelled when the production is finished."""

    paused: bool = False
    """Whether the throttle has suspended it (008 T13). Still a live process either way."""

    def suspend(self) -> None:
        """Stop it producing without ending it. The operator's throttle, `media/sessions.py`.

        **A signal rather than the reference's pause key.** The reference writes `p` - or `c`
        into an unpatched ffmpeg - on the process's standard input `[source:
        MediaBrowser.Controller/MediaEncoding/TranscodingThrottler.cs:128-146 @ v10.11.11]`,
        which needs the encoder to be reading its console and needs to know which build it is.
        A stopped process stops writing whatever it is, which is the whole of what a client can
        observe: the produced file stops growing and starts again. Plan section 6.7 calls it
        process suspension for that reason.

        Safe against the kill paths, which is not obvious: `stop` sends `SIGKILL`, and a stopped
        process is killed by it without ever being resumed. A polite signal would have sat
        pending for ever.
        """
        self._signal(SUSPEND, paused=True)

    def resume(self) -> None:
        """Let it produce again, when the client has caught up or the session is ending."""
        self._signal(CONTINUE, paused=False)

    def _signal(self, number: int | None, *, paused: bool) -> None:
        if self.paused == paused or self.process.returncode is not None:
            return
        if number is None:
            # No job-control signals on this platform: the throttle is then a knob that reads
            # back as configured and pauses nothing, which is what "off" already looks like.
            return
        with contextlib.suppress(ProcessLookupError, OSError, ValueError):
            self.process.send_signal(number)
            self.paused = paused

    async def drain(self) -> None:
        """Read the diagnostic stream to its end, keeping the tail.

        **By block rather than by line**, which is the difference between draining a pipe and
        appearing to. `readline` refuses a line longer than its stream's limit and gives up on
        the reader, so a process that shouts without newlines - a progress meter separated by
        carriage returns, a build with one enormous message - would leave the pipe unread from
        that moment on, which is the exact hazard this method exists to remove. Measured by
        `tests/unit/test_transcode_lifecycle.py`, which hung against the first version.

        Losing the connection to a process being killed is the normal case rather than an error,
        so a read that fails ends the drain instead of raising into a task nobody awaits.
        """
        stream = self.process.stderr
        if stream is None:
            return
        pending = b""
        with contextlib.suppress(Exception):
            while True:
                block = await stream.read(STDERR_BLOCK_BYTES)
                if not block:
                    break
                *finished, pending = (pending + block).split(b"\n")
                for line in finished:
                    self._record(line)
                # A "line" nothing has ended: keep its tail and drop the rest, so an encoder
                # that never writes a newline cannot grow this without bound either.
                pending = pending[-STDERR_BLOCK_BYTES:]
        self._record(pending)

    def _record(self, line: bytes) -> None:
        said = line.decode("utf-8", "replace").strip()
        if said:
            self.complaints.append(said)

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
        """Launch one, recorded from the moment it exists, with its diagnostics being read.

        `shell=False` by construction - `create_subprocess_exec` takes an argument vector, and
        every element of it came from `command()`'s own tables rather than from a client's
        string.

        **The reader is started here rather than left to the caller**, because a caller that
        forgot would not fail: it would hang, once, on the one encode long and noisy enough to
        fill the pipe. Every process this ledger holds therefore has exactly one drain, started
        in the same statement that makes the process reachable.
        """
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE if to_pipe else asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        running = Production(argv=tuple(argv), process=process)
        running.reader = asyncio.create_task(running.drain())
        self.live.add(running)
        return running

    async def finish(self, running: Production) -> None:
        """Forget it, then stop it, then say why it stopped if it had something to say.

        Discarded **before** the stop, because the stop may be cancelled halfway and a ledger that
        still listed a process nobody is waiting for would say the server is producing when it is
        not - which is the one thing this set exists to answer.

        **The drain is waited for rather than cancelled**, which is the difference between having
        the encoder's last words and having an empty deque exactly when they were wanted. The
        process is already dead by here, so its pipe is at end and the reader ends on its own
        almost at once; the bound is for the case where it does not, and cancelling then costs
        nothing, because a reader that is still going is one whose process was killed and whose
        exit is a signal rather than a fault. Cancelling unconditionally looked identical on one
        machine and lost the message on a slower one.

        The complaint is logged only for an encoder that failed on its own: a killed one exits on
        a signal, which is what every stop path here produces and not a fault to report.
        """
        self.live.discard(running)
        await running.stop()
        reader = running.reader
        running.reader = None
        if reader is not None:
            with contextlib.suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(reader, timeout=DRAIN_GRACE_SECONDS)
            reader.cancel()
        if running.process.returncode is not None and running.process.returncode > 0:
            logger.warning(
                "%s exited %s: %s",
                running.argv[0],
                running.process.returncode,
                " / ".join(running.complaints) or "no reason given",
            )

    async def shutdown(self) -> None:
        for running in list(self.live):
            await self.finish(running)


__all__ = [
    "AUDIO_ENCODERS",
    "CHUNK_BYTES",
    "CONTINUE",
    "DEFAULT_SEGMENT_FORMAT",
    "DRAIN_GRACE_SECONDS",
    "ENCODER_PRESET",
    "FFMPEG",
    "FRAGMENT_FLAGS",
    "INITIALISATION_INDEX",
    "KEYFRAME_FORCERS",
    "MUXERS",
    "NEEDS_FRAGMENTING",
    "NEEDS_SEEKING",
    "PIPE",
    "PIXEL_FORMATS",
    "PREAMBLE",
    "RAW_SAMPLE_CODECS",
    "SEGMENT_FORMATS",
    "STDERR_BLOCK_BYTES",
    "STDERR_LINES_KEPT",
    "SUSPEND",
    "TICKS_PER_SECOND",
    "VIDEO_ENCODERS",
    "Output",
    "Production",
    "ProductionError",
    "ProductionLedger",
    "SegmentOutput",
    "command",
    "default_stream_indexes",
    "executable",
    "muxer_for",
    "needs_seeking",
    "raw_codec_for",
    "segment_command",
]
