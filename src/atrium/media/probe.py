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
from types import MappingProxyType
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

#: What the reference substitutes for an audio stream whose bitrate nothing states, keyed on the
#: codec and then on the channel count. `[source:
#: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs GetEstimatedAudioBitrate @
#: v10.11.11]`
#:
#: **Two thresholds and a hole between them.** The reference switches on `<= 2` and `>= 5` and
#: returns nothing in between, so a 3- or 4-channel stream takes no estimate at all - and a codec
#: outside these six takes none either. Reproduced rather than smoothed: filling the hole would
#: answer a bitrate the reference leaves empty, which is a different wire shape and not a tidier
#: one.
ESTIMATED_AUDIO_BITRATES: dict[str, tuple[int, int]] = {
    "aac": (192_000, 320_000),
    "mp3": (192_000, 320_000),
    "ac3": (192_000, 640_000),
    "eac3": (192_000, 640_000),
    "flac": (960_000, 2_880_000),
    "alac": (960_000, 2_880_000),
}

#: The suffix the reference prefers on the three bitrate tags before the bare name. Matroska writes
#: `BPS-eng` beside `BPS` on a track tagged with a language, and the reference reads the suffixed
#: one first. Same source, `GetBPSFromTags` and its two siblings.
TAG_LANGUAGE_SUFFIX = "-eng"

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


def inspect(path: Path, ffprobe: str = FFPROBE, *, is_audio: bool = False) -> MediaInspection:
    """Open `path` and describe it. Raises `InspectionError` when it cannot be described.

    The change signal is read here, from the same file and in the same breath as its contents, so
    that a stored inspection can never be attributed to bytes it did not read.

    **`is_audio` is the item's kind and not the file's**, which is the reference's own parameter -
    `GetMediaInfo(..., bool isAudio, ...)` - and it is a parameter there for the same reason it is
    one here: it cannot be derived from the streams. An audio file carrying cover art has a video
    stream, and the reference reclassifies that stream as `EmbeddedImage` before anything reads it
    `[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:797-804 @ v10.11.11]`;
    this server has no such stream kind, so `any(kind is VIDEO)` would call every tagged mp3 a
    video file. What it changes is `_bitrate`, and only for audio streams.
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

    streams = tuple(
        _stream(one, container, is_audio=is_audio)
        for one in parsed.get("streams", ())
        if isinstance(one, Mapping)
    )
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


def inspect_subtitle(path: Path, ffprobe: str = FFPROBE) -> tuple[InspectedStream, ...]:
    """The subtitle streams inside one file sitting beside a media file.

    **The extension does not decide what is in it, which is the whole reason this opens the
    file.** A `.sub` is `microdvd` - a text format - or `dvd_subtitle` - an image one - depending
    on its bytes, and that is exactly the split `IsTextSubtitleStream` turns on (011 plan section
    6.1). An `.mks` is a Matroska container and can hold several tracks, so this takes **every**
    subtitle stream rather than assuming one.

    Streams that are not subtitles are dropped rather than refused: a `.mks` may carry a font
    attachment, and a file whose only stream is a video one is not a subtitle file at all - it
    comes back empty and the caller discovers nothing, which is the same answer as a file that
    holds no subtitle track.

    No change signal and no container: the walk already statted this file, and what a sidecar's
    demuxer calls itself is a fact about a stream here rather than about a source.
    """
    executable = _executable(ffprobe)
    parsed = _run_json(executable, path)
    return tuple(
        _stream(one)
        for one in parsed.get("streams", ())
        if isinstance(one, Mapping) and _kind(one.get("codec_type")) is StreamKind.SUBTITLE
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


def _stream(
    raw: Mapping[str, Any],
    container: Mapping[str, Any] = MappingProxyType({}),
    *,
    is_audio: bool = False,
) -> InspectedStream:
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
        # **Zero and not null when the tool says nothing**, which is not a default anybody chose:
        # the reference's probing DTO holds `Level` as a NON-nullable `int` and the common
        # `MediaStream` initialiser assigns it before any per-kind branch runs, so an absent
        # `level` deserialises to `0` and every stream carries one `[source:
        # MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:709 and
        # MediaStreamInfo.cs:172 @ v10.11.11]`. A value the tool does report is passed through
        # unexamined, negative sentinel included.
        level=_zeroed(raw.get("level")),
        bit_depth=_bit_depth(raw),
        # **Zero for a video or a subtitle and absent for anything else**, which is the same
        # non-nullable `int` one branch further in: the reference assigns `Width`/`Height` in its
        # subtitle and video branches only, so a text subtitle carries `0` and an audio stream
        # carries nothing at all `[source: ProbeResultNormalizer.cs:776-777, 823-824 and
        # MediaStreamInfo.cs:95, 109 @ v10.11.11]`. Measured on the wire the same way
        # `[probe: tools/probe_playback_stream_fields.py, Jellyfin 12.0.0, 2026-09-12]`.
        width=_framed(raw.get("width"), kind),
        height=_framed(raw.get("height"), kind),
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
        bitrate=_bitrate(raw, kind, container, is_audio=is_audio),
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
        time_base=_text(raw.get("time_base")),
        nal_length_size=_text(raw.get("nal_length_size")),
        # **A string on the way in and a boolean on the way out**, which is the tool's spelling
        # rather than a coercion of convenience: `ffprobe` reports `is_avc` as `"true"`/`"false"`,
        # and the reference deserialises it into a non-nullable `bool` - so a stream the tool says
        # nothing about is `false` there and `false` here
        # `[source: MediaBrowser.MediaEncoding/Probing/MediaStreamInfo.cs:235 @ v10.11.11]`.
        is_avc=_flag(raw.get("is_avc")),
    )


def _flag(value: Any) -> bool:
    """`ffprobe`'s `"true"`/`"false"`, and `False` for anything else including absence."""
    if isinstance(value, bool):
        return value
    text = _text(value)
    return text is not None and text.strip().casefold() == "true"


def _tag(tags: Mapping[str, Any], name: str) -> str | None:
    """One of the reference's language-suffixed tags, read the way the reference reads it.

    **Two lookups and both case-insensitive.** The suffixed spelling wins over the bare one, which
    is `??` in the source; and every stream tag is rebuilt into an `OrdinalIgnoreCase` dictionary
    before any of this runs `[source:
    MediaBrowser.MediaEncoding/Probing/FFProbeHelpers.cs:32 @ v10.11.11]`, which matters here
    because these three tags are Matroska's own and it writes them upper case.
    """
    folded = {str(key).lower(): value for key, value in tags.items()}
    for key in (name + TAG_LANGUAGE_SUFFIX, name):
        found = _text(folded.get(key.lower()))
        if found is not None:
            return found
    return None


def _tag_seconds(tags: Mapping[str, Any]) -> float | None:
    """The `DURATION` tag as seconds, parsed as the timespan the reference parses it as.

    `TimeSpan.TryParse` takes `[d.]hh:mm:ss[.fffffff]`, and Matroska writes nine fractional digits
    where .NET accepts seven - so a value this rejects is one the reference rejects too, and the
    stream keeps no bitrate rather than gaining one this server invented.
    """
    text = _tag(tags, "DURATION")
    if text is None:
        return None
    head, _, fraction = text.partition(".")
    if fraction and (len(fraction) > 7 or not fraction.isdigit()):
        return None
    parts = head.split(":")
    if len(parts) != 3 or not all(one.strip().isdigit() for one in parts):
        return None
    hours, minutes, seconds = (int(one) for one in parts)
    if minutes > 59 or seconds > 59:
        return None
    whole = hours * 3600 + minutes * 60 + seconds
    return whole + (int(fraction) / 10 ** len(fraction) if fraction else 0.0)


def _bitrate(
    raw: Mapping[str, Any],
    kind: StreamKind,
    container: Mapping[str, Any],
    *,
    is_audio: bool,
) -> int | None:
    """What the reference answers for `BitRate`, which is four fallbacks and not one reading.

    Before 2026-09-12 this server stored `bit_rate` and nothing else, so every stream the tool
    reports no bitrate for carried none - 'a video `BitRate` where `ffprobe` reports none' on
    008's owes list, and the reference answering `117861` for such a stream. The derivation is
    `[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:969-1018, 251-257 @
    v10.11.11]`:

    1. the stream's own `bit_rate`;
    2. the **container's**, for a video stream always and an audio stream only inside an audio
       file - which is what `is_audio` decides and why it had to become a parameter;
    3. the `BPS` tag, then `NUMBER_OF_BYTES` over `DURATION` - audio and video streams only;
    4. a table keyed on codec and channels, for an audio stream inside a **video** file only.

    **Steps 2 and 4 are the same question answered opposite ways, and that is the design rather
    than an inconsistency.** An audio file's container bitrate essentially *is* its audio stream's,
    so the reference uses it; a video file's is not, so it estimates instead. The reference spells
    this by putting step 4 inside its `else (!isAudio)` branch and gating step 2 on `isAudio`.
    """
    stated = _integer(raw.get("bit_rate")) or 0
    if stated == 0 and (kind is StreamKind.VIDEO or (is_audio and kind is StreamKind.AUDIO)):
        stated = _integer(container.get("bit_rate")) or stated
    if stated > 0:
        return stated

    if kind in (StreamKind.AUDIO, StreamKind.VIDEO):
        tags = _mapping(raw.get("tags"))
        bps = _integer(_tag(tags, "BPS"))
        if bps is not None and bps > 0:
            return bps
        seconds = _tag_seconds(tags)
        measured = _integer(_tag(tags, "NUMBER_OF_BYTES"))
        if seconds is not None and seconds >= 1 and measured is not None:
            # **Rounded half to even, because `Convert.ToInt32` is** - truncation would answer one
            # less than the reference on any file whose division lands above `.5`.
            derived = round(measured * 8 / seconds)
            if derived > 0:
                return derived

    if not is_audio and kind is StreamKind.AUDIO:
        estimate = ESTIMATED_AUDIO_BITRATES.get((_text(raw.get("codec_name")) or "").lower())
        channels = _integer(raw.get("channels"))
        if estimate is not None and channels is not None:
            if channels <= 2:
                return estimate[0]
            if channels >= 5:
                return estimate[1]
    return None


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


#: The two stream kinds whose branch assigns a frame size in the reference. Anything else keeps
#: nothing, which is a different answer from `0` and the one an audio stream gives.
FRAMED_KINDS = (StreamKind.VIDEO, StreamKind.SUBTITLE)


def _zeroed(value: Any) -> int:
    """A whole number, with **zero** where the tool reported nothing.

    The shape a non-nullable `int` gives a field the JSON does not carry. It is not a default in
    the sense of a value somebody picked: it is what deserialising an absent property into an
    `int` produces, and reproducing it is the difference between `Level: 0` and `Level: null` on
    every audio and subtitle stream of every item.
    """
    found = _integer(value)
    return 0 if found is None else found


def _framed(value: Any, kind: StreamKind) -> int | None:
    """`_zeroed` for the kinds the reference frames, and nothing for the rest."""
    return _zeroed(value) if kind in FRAMED_KINDS else _integer(value)


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
