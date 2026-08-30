# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening a media file and writing down what is in it.

One function - `inspect(path)` - runs the reference's own inspection tool over a file and turns
its answer into the `domain/media.py` records the scan stores. No database, no wire shapes, no
decisions: what a profile makes of a stream is `media/decision.py`'s, and what a response says
about it is `media/info.py`'s.

**Two invocations, not one.** The first lists the container and the elementary streams; the second
runs only for a file that has a video stream and collects its keyframe times, which need a packet
listing rather than a stream listing. The packet pass reads the whole file without decoding it,
which is why it is worth storing the answer rather than repeating it per playlist request (plan
section 6.4).

**A lot of what the reference reports is derived rather than read**, and the derivations are here
because they are properties of the file: the container normalisation, whether a stream is
interlaced or anamorphic, the dynamic range, the junk-tag rule. Each cites where the behaviour was
read. What is *not* here is the single container a media source reports - see `_normalise_format`.

**One thing is renamed rather than derived**, and it has to happen here: four subtitle codecs are
rewritten during inspection, so every consumer - the text/image split, a negotiation's format
comparison, the `Codec` a client reads - sees one spelling. See `RENAMED_SUBTITLE_CODECS`.

**Optional means measured.** Against the fixture matrix on 2026-08-29, a Matroska stream reports
no `bit_rate` at all, no `language` tag where the same content in mp4 carries `und`, and the
four-zero `codec_tag` placeholder; and a file the tool opens happily can have no duration at all
(a still image does). Every one of those is a column that must be allowed to be empty, and a parse
that indexed them would fail on half the matrix.

See specs/008-playback-negotiation-and-delivery/plan.md sections 4, 5 and 6.1.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from atrium.compat import ticks
from atrium.compat.dates import utc_now
from atrium.domain.media import (
    InspectedStream,
    MediaInspection,
    StreamKind,
    VideoRange,
    VideoRangeType,
)

#: The inspection tool, by name. Resolved on `PATH` at call time rather than at import, so a
#: server that gains it after starting does not need restarting to use it.
FFPROBE = "ffprobe"

#: How long one invocation may take before it is abandoned. A scan walks thousands of files, and a
#: tool that hangs on one of them - a truncated download, a share that stopped answering - must
#: cost that file rather than the library.
TIMEOUT_SECONDS = 60

#: Container names the reference rewrites, and what it rewrites them to. `[source:
#: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs NormalizeFormat @ v10.11.11]`
RENAMED_CONTAINERS = {"mpegvideo": "mpeg", "mpegts": "ts", "matroska": "mkv"}

#: What a stream must be for a `matroska,webm` file to keep the `webm` half of its answer. Any
#: other stream kind, or any codec outside these, disqualifies it. Same source.
WEBM_VIDEO_CODECS = frozenset({"av1", "vp8", "vp9"})
WEBM_AUDIO_CODECS = frozenset({"opus", "vorbis"})

#: The colour transfer characteristics that mean high dynamic range, and which flavour. `[source:
#: MediaBrowser.Model/Entities/MediaStream.cs GetVideoColorRange @ v10.11.11]`
HDR_TRANSFERS = {
    "smpte2084": VideoRangeType.HDR10,
    "arib-std-b67": VideoRangeType.HLG,
}

#: The container's own placeholder for "this format has no four-character code", which the
#: reference discards rather than storing. Matroska reports it for every stream. Same source as
#: the rename table.
CODEC_TAG_PLACEHOLDER = "[0]"

#: Subtitle codec names the reference rewrites **during inspection**, and what it rewrites them
#: to. `[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:632-652, 765-768 @
#: v10.11.11]`
#:
#: The rename happens here, before anything reads a codec, because it is the renamed spelling that
#: every later rule is written against - the text/image split, the servable-alone rule and the
#: `Codec` a client reads are all one string. Only two of the four change any answer, and neither
#: is the one a fixture can produce: `hdmv_pgs_subtitle` already contains `pgs` and `dvb_teletext`
#: is text under either spelling, while `dvd_subtitle` and `dvb_subtitle` contain neither `dvdsub`
#: nor `dvbsub` and are read as **text** until they have been renamed.
RENAMED_SUBTITLE_CODECS = {
    "dvb_subtitle": "DVBSUB",
    "dvb_teletext": "DVBTXT",
    "dvd_subtitle": "DVDSUB",
    "hdmv_pgs_subtitle": "PGSSUB",
}

#: The handler names a muxer writes when nobody named the track. The reference falls back to
#: `handler_name` for a missing stream title and skips exactly these, which is why an mp4 audio
#: track is untitled rather than called "SoundHandler". Same source.
DEFAULT_HANDLER_NAMES = {
    StreamKind.AUDIO: "soundhandler",
    StreamKind.SUBTITLE: "subtitlehandler",
}


class InspectionError(RuntimeError):
    """A file could not be inspected. The base of the two below, so a caller that does not care
    which kind of failure it was can catch one thing."""


class ProberUnavailableError(InspectionError):
    """The inspection tool is not installed.

    Separate from `UnreadableMediaError` because the two mean opposite things to a scan: this one
    is true of every file and is an operator's problem, and recording thousands of items as
    unexaminable would hide it behind its own consequences.
    """


class UnreadableMediaError(InspectionError):
    """This file is not something a demuxer can open, or it says nothing usable.

    A per-file fact: the scan records it the way 003 section 3.7 records an unexamined file and
    the item simply has no media source until a rescan succeeds.
    """


def inspect(path: Path, ffprobe: str = FFPROBE) -> MediaInspection:
    """Open `path` and describe it. Raises `InspectionError` when it cannot be described.

    The change signal is read here, from the same file and in the same breath as its contents, so
    that a stored inspection can never be attributed to bytes it did not read.
    """
    executable = _executable(ffprobe)
    stat = _stat(path)

    parsed = _run_json(executable, path)
    container = parsed.get("format")
    if not isinstance(container, Mapping):
        raise UnreadableMediaError(f"{path} produced no container description")
    format_names = _text(container.get("format_name"))
    if format_names is None:
        raise UnreadableMediaError(f"{path} has no container format")

    streams = tuple(_stream(one) for one in parsed.get("streams", ()) if isinstance(one, Mapping))
    has_video = any(one.kind is StreamKind.VIDEO for one in streams)

    return MediaInspection(
        size=stat[0],
        mtime_ns=stat[1],
        container=_normalise_format(format_names, streams),
        format_names=format_names,
        runtime_ticks=_ticks(container.get("duration")),
        bitrate=_integer(container.get("bit_rate")),
        video_keyframes=_keyframes(executable, path) if has_video else None,
        probed_at=utc_now(),
        streams=streams,
    )


# --------------------------------------------------------------------------------------------
# Running the tool
# --------------------------------------------------------------------------------------------


def _executable(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise ProberUnavailableError(
            f"{name} is not on PATH. Media cannot be inspected without it, so no item gets a "
            f"media source until it is installed."
        )
    return found


def _stat(path: Path) -> tuple[int, int]:
    try:
        stated = path.stat()
    except OSError as exc:
        raise UnreadableMediaError(f"{path} cannot be read: {exc.strerror}") from exc
    return stated.st_size, stated.st_mtime_ns


def _run(executable: str, arguments: Sequence[str], path: Path) -> str:
    """One invocation, returning its standard output.

    `shell=False` with an absolute executable and a fixed argument list: the only value that comes
    from outside is the path itself, and it arrives as one argument rather than as text a shell
    would re-read.
    """
    command = [executable, "-hide_banner", "-loglevel", "error", *arguments, str(path)]
    try:
        finished = subprocess.run(  # noqa: S603
            command, capture_output=True, text=True, check=False, timeout=TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        raise UnreadableMediaError(
            f"{path} did not finish being inspected within {TIMEOUT_SECONDS}s"
        ) from exc
    except OSError as exc:
        raise ProberUnavailableError(f"{executable} could not be run: {exc}") from exc
    if finished.returncode != 0:
        raise UnreadableMediaError(
            f"{path} could not be inspected: {finished.stderr.strip() or 'no reason given'}"
        )
    return finished.stdout


def _run_json(executable: str, path: Path) -> Mapping[str, Any]:
    output = _run(
        executable,
        ["-print_format", "json", "-show_format", "-show_streams"],
        path,
    )
    try:
        parsed = json.loads(output)
    except ValueError as exc:
        raise UnreadableMediaError(f"{path} produced an unparseable description") from exc
    if not isinstance(parsed, Mapping):
        raise UnreadableMediaError(f"{path} produced an unparseable description")
    return parsed


def _keyframes(executable: str, path: Path) -> tuple[int, ...]:
    """Every keyframe's presentation time, in ticks, in order.

    Read from the *packet* listing rather than the frame listing: the two agreed exactly on the
    fixture matrix (measured 2026-08-29), and the packet pass never decodes a frame - which is the
    difference between reading a two-hour film and decoding one.
    """
    output = _run(
        executable,
        ["-select_streams", "v:0", "-show_entries", "packet=pts_time,flags", "-of", "csv=p=0"],
        path,
    )
    found = []
    for line in output.splitlines():
        fields = line.split(",")
        if len(fields) < 2 or not fields[1].startswith("K"):
            continue
        moment = _ticks(fields[0])
        if moment is not None:
            found.append(moment)
    return tuple(found)


# --------------------------------------------------------------------------------------------
# The container
# --------------------------------------------------------------------------------------------


def _normalise_format(format_names: str, streams: Sequence[InspectedStream]) -> str:
    """The container string the reference stores, from the demuxer list the file reports.

    Three formats are renamed and `webm` survives only where every stream could be in a WebM file;
    everything else is left as it is, comma list and all. `matroska,webm` with an h264 video
    therefore becomes `mkv`, while `mov,mp4,m4a,3gp,3g2,mj2` stays six names long - measured at
    item level on a real library `[probe: tools/probe_media_container.py, Jellyfin 10.11.11,
    2026-08-29]`.

    **This is not the single container a media source reports**, and nothing here can produce it:
    a listing derives that from the file's extension and a negotiation derives it from the device
    profile, so the same file answers `mp4` on one route and the whole list on another. Those two
    derivations belong to whatever is emitting a response - see the plan section 4 note.
    """
    kept = []
    for name in format_names.split(","):
        renamed = RENAMED_CONTAINERS.get(name, name)
        if renamed == "webm" and not _could_be_webm(streams):
            continue
        kept.append(renamed)
    return ",".join(kept) if kept else format_names


def _could_be_webm(streams: Sequence[InspectedStream]) -> bool:
    for one in streams:
        if one.kind is StreamKind.VIDEO and (one.codec or "") in WEBM_VIDEO_CODECS:
            continue
        if one.kind is StreamKind.AUDIO and (one.codec or "") in WEBM_AUDIO_CODECS:
            continue
        return False
    return True


# --------------------------------------------------------------------------------------------
# One stream
# --------------------------------------------------------------------------------------------


def _stream(raw: Mapping[str, Any]) -> InspectedStream:
    kind = _kind(raw.get("codec_type"))
    tags = _mapping(raw.get("tags"))
    disposition = _mapping(raw.get("disposition"))
    is_video = kind is StreamKind.VIDEO
    transfer = _text(raw.get("color_transfer"))

    return InspectedStream(
        index=_integer(raw.get("index")) or 0,
        kind=kind,
        codec=_codec(kind, _text(raw.get("codec_name"))),
        codec_tag=_codec_tag(raw),
        profile=_text(raw.get("profile")),
        # Passed through as reported, negative sentinel included: the reference stores this
        # number unexamined, and an unknown level that became null here would be a different
        # answer from the one a client already gets.
        level=_integer(raw.get("level")),
        bit_depth=_bit_depth(raw),
        width=_integer(raw.get("width")),
        height=_integer(raw.get("height")),
        aspect_ratio=_text(raw.get("display_aspect_ratio")),
        framerate=_rate(raw.get("r_frame_rate")),
        average_framerate=_rate(raw.get("avg_frame_rate")),
        channels=_integer(raw.get("channels")),
        channel_layout=_channel_layout(raw.get("channel_layout")),
        sample_rate=_integer(raw.get("sample_rate")),
        language=_text(tags.get("language")),
        title=_title(kind, tags),
        is_default=bool(disposition.get("default")),
        is_forced=bool(disposition.get("forced")),
        is_hearing_impaired=bool(disposition.get("hearing_impaired")),
        is_external=False,
        bitrate=_integer(raw.get("bit_rate")),
        video_range=_range(transfer) if is_video else None,
        video_range_type=_range_type(transfer) if is_video else None,
        color_range=_text(raw.get("color_range")),
        color_transfer=transfer,
        color_primaries=_text(raw.get("color_primaries")),
        color_space=_text(raw.get("color_space")),
        pixel_format=_text(raw.get("pix_fmt")),
        # Only when it is a real count, which is how the reference reads it too. Measured
        # 2026-08-29: ffprobe 9.0.1 does not report `refs` at all, so this is empty wherever that
        # build inspects. Nothing may require the column, and no test may assert it either way -
        # the suite runs against more than one build of the tool.
        ref_frames=_positive(raw.get("refs")),
        is_interlaced=_is_interlaced(raw.get("field_order")),
        is_anamorphic=_is_anamorphic(raw) if is_video else None,
    )


def _kind(value: Any) -> StreamKind:
    try:
        return StreamKind(str(value))
    except ValueError:
        return StreamKind.UNKNOWN


def _codec(kind: StreamKind, codec: str | None) -> str | None:
    """What the file reports, with the four subtitle renames applied.

    Subtitles only, which is where the reference does it: the rename sits inside the branch that
    handles a subtitle stream, so a video codec that happened to be spelled one of these four
    would be left alone. Matched without regard to case, as the reference matches it; the tool
    reports these four in lower case.
    """
    if kind is not StreamKind.SUBTITLE or codec is None:
        return codec
    return RENAMED_SUBTITLE_CODECS.get(codec.lower(), codec)


def _codec_tag(raw: Mapping[str, Any]) -> str | None:
    """The four-character code, or nothing where the container has none.

    Matroska writes the `[0][0][0][0]` placeholder for every stream; the reference filters it out
    as junk rather than storing it, and a stored placeholder would be a codec tag no file has.
    """
    tag = _text(raw.get("codec_tag_string"))
    if tag is None or CODEC_TAG_PLACEHOLDER in tag:
        return None
    return tag


def _bit_depth(raw: Mapping[str, Any]) -> int | None:
    """Bits per sample where the file states them, bits per *raw* sample otherwise.

    That order is the reference's, and it matters for lossless audio: a flac track reports zero
    for the first and sixteen for the second, so reading only the first would call every one of
    them depthless.
    """
    return _positive(raw.get("bits_per_sample")) or _positive(raw.get("bits_per_raw_sample"))


def _title(kind: StreamKind, tags: Mapping[str, Any]) -> str | None:
    """The track's title, with the muxer's default handler name never mistaken for one."""
    named = _text(tags.get("title"))
    if named is not None:
        return named
    handler = _text(tags.get("handler_name"))
    if handler is None or kind not in DEFAULT_HANDLER_NAMES:
        return None
    return None if handler.lower() == DEFAULT_HANDLER_NAMES[kind] else handler


def _channel_layout(value: Any) -> str | None:
    """`5.1(side)` is stored as `5.1`: the parenthesis says which side channels a layout uses,
    and the reference keeps only the part before it."""
    text = _text(value)
    return None if text is None else text.split("(")[0] or None


def _range(transfer: str | None) -> VideoRange:
    """Every video stream has one, and it is standard range unless its transfer says otherwise.

    The reference reaches the same two answers by a longer route, through Dolby Vision side data
    that an elementary-stream listing does not carry. Until something reads that side data, a
    Dolby Vision file is inspected here as the standard-range file its colour metadata claims.
    """
    return VideoRange.HDR if transfer in HDR_TRANSFERS else VideoRange.SDR


def _range_type(transfer: str | None) -> VideoRangeType:
    return HDR_TRANSFERS.get(transfer or "", VideoRangeType.SDR)


def _is_interlaced(field_order: Any) -> bool:
    """Stated, and not progressive. A file that says nothing about its field order is not
    interlaced, which is the reading the reference takes and the only safe one: guessing
    interlacing from anything else re-encodes progressive video for nobody."""
    stated = _text(field_order)
    return stated is not None and stated.lower() != "progressive"


def _is_anamorphic(raw: Mapping[str, Any]) -> bool:
    """Whether the pixels are non-square, decided the way the reference decides it.

    The ladder is theirs, including the step that is arguably wrong: a stream with **no** sample
    aspect ratio but a stated display one is called anamorphic, because "no ratio" is not the
    `0:1` the test is written against. Reproduced rather than corrected - it is the answer a
    client already gets, and the case only arises where a muxer states one ratio and not the
    other.
    """
    sample = _text(raw.get("sample_aspect_ratio"))
    display = _text(raw.get("display_aspect_ratio"))
    if sample is None and display is None:
        return False
    if sample == "1:1":
        return False
    if sample != "0:1":
        return True
    if display == "0:1":
        return False
    return display != _ratio_of(_integer(raw.get("width")), _integer(raw.get("height")))


def _ratio_of(width: int | None, height: int | None) -> str | None:
    if not width or not height:
        return None
    return f"{width}:{height}"


# --------------------------------------------------------------------------------------------
# Reading one value
# --------------------------------------------------------------------------------------------


def _mapping(value: Any) -> Mapping[str, Any]:
    """A sub-object, or an empty one. Every block below is optional in the listing."""
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    """A non-empty string, or nothing. The tool writes `N/A` where it has no answer, and a
    stored `"N/A"` is worse than an absence because it compares equal to itself."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return None if not stripped or stripped == "N/A" else stripped


def _integer(value: Any) -> int | None:
    """A whole number from whatever spelling the tool used - numbers arrive as strings about as
    often as they arrive as numbers."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _positive(value: Any) -> int | None:
    """A count, where zero means "not stated" rather than zero of them."""
    number = _integer(value)
    return number if number is not None and number > 0 else None


def _rate(value: Any) -> str | None:
    """A frame rate as its exact rational, with the tool's `0/0` for "not a video stream"
    dropped."""
    text = _text(value)
    if text is None or text.startswith("0/"):
        return None
    return text


def _ticks(value: Any) -> int | None:
    """Seconds as the tool prints them, in the unit everything else in this project uses."""
    text = _text(value)
    if text is None:
        return None
    try:
        return ticks.from_seconds(text)
    except (ArithmeticError, ValueError):
        return None


__all__ = [
    "FFPROBE",
    "InspectionError",
    "ProberUnavailableError",
    "UnreadableMediaError",
    "inspect",
]
