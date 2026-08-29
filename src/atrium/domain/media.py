# SPDX-License-Identifier: GPL-3.0-or-later
"""What a media file turned out to contain, once something opened it.

These are the records `media/probe.py` produces and `db/repositories.py` stores and hands back -
one `MediaInspection` per file, one `InspectedStream` per elementary stream inside it. They live
here rather than beside the prober because the repository returns them (ADR-0003: domain objects
out, never rows), and `tests/unit/test_repositories.py`'s sweep holds that boundary by resolving
return annotations.

**Nothing here is a wire shape.** `MediaSourceInfo` and `MediaStream` are assembled from these by
008 T3, and the two vocabularies deliberately differ: what a file contains is a fact, and what a
response says about it is a decision - the resolved container being the clearest case, since it is
not a property of the file at all (see `container` below).

See specs/008-playback-negotiation-and-delivery/plan.md section 4.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

#: Above this the reference distrusts the average frame rate and falls back to the real one: some
#: libraries report 1000 fps for a file that is nothing of the sort. `[source:
#: MediaBrowser.Model/Entities/MediaStream.cs ReferenceFrameRate @ v10.11.11]`
IMPLAUSIBLE_FRAME_RATE = 1000.0


def narrow_to_single(value: float) -> float:
    """The number a 32-bit float actually holds, which is **not** the number it prints as.

    The reference declares every frame rate and the video level as singles, and the two readers of
    that fact want different things from it. `media/info.py` writes the *shortest decimal that
    reads back as the same single* - `23.975988` - because that is what .NET's serialiser emits.
    `media/decision.py` compares against the value itself - `23.975988388061523` - because that is
    what the reference's condition processor is handed.

    The gap between them is observable: a client that declares a frame-rate ceiling of exactly the
    rate it read off the wire is answered with a **transcode**, because the real single is above
    the decimal it printed as `[probe: tools/probe_decision_ladder.py, Jellyfin 10.11.11,
    2026-08-29]`. A single function that rounded to the printed form would answer direct play
    there and disagree with the reference on the one comparison it exists to make.
    """
    narrowed: float = struct.unpack("f", struct.pack("f", value))[0]
    return narrowed


def _rational(text: str | None) -> float | None:
    """`24000/1001` as a number, or None when it says nothing usable."""
    if text is None:
        return None
    dividend, _, divisor = text.partition("/")
    try:
        top, bottom = float(dividend), float(divisor or 1)
    except ValueError:
        return None
    return None if bottom == 0 else top / bottom


class StreamKind(Enum):
    """What an elementary stream carries.

    The five members of the demuxer's own vocabulary plus `UNKNOWN`, which is what an
    unrecognised or missing kind becomes rather than a refusal: a file with one stream nobody can
    classify still has its other streams, and losing the whole inspection over one of them would
    make an item unplayable to save a row.
    """

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    DATA = "data"
    ATTACHMENT = "attachment"
    UNKNOWN = "unknown"


class VideoRange(Enum):
    """Whether a video stream is high dynamic range. `[source:
    MediaBrowser.Model/Entities/MediaStream.cs GetVideoColorRange @ v10.11.11]`"""

    SDR = "SDR"
    HDR = "HDR"


class VideoRangeType(Enum):
    """Which flavour of range, in the reference's spelling.

    **Only the three derivable from a stream's colour metadata are here.** The reference's
    vocabulary also carries eight Dolby Vision members, and every one of them is decided from
    side data an elementary-stream listing does not include - so a member for them would be one
    no inspection in this project can ever produce. When a probe learns to read that side data,
    the members arrive with it.
    """

    SDR = "SDR"
    HDR10 = "HDR10"
    HLG = "HLG"


@dataclass(frozen=True, slots=True)
class InspectedStream:
    """One elementary stream, as the file describes it.

    Almost everything is optional, and that is measured rather than defensive: a Matroska file
    reports no per-stream bitrate at all, its streams carry no `language` tag where the same
    content muxed into mp4 carries `und`, and its `codec_tag` is the four-zero placeholder the
    reference discards as junk `[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs
    @ v10.11.11]`. A record that required those fields could not describe half the fixture matrix.
    """

    index: int
    kind: StreamKind

    codec: str | None = None
    codec_tag: str | None = None
    """The four-character tag, absent where the container has none to give."""

    profile: str | None = None
    level: int | None = None
    bit_depth: int | None = None

    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None
    """The display aspect ratio as the file states it - `16:9` - not a number."""

    framerate: str | None = None
    """The base frame rate as an exact rational, `24000/1001`. A float here would round the one
    input the segment cadence is computed from (plan section 6.4)."""

    average_framerate: str | None = None
    """The average frame rate, the same way. Separate from `framerate` because the reference
    carries both and they differ on variable-frame-rate content."""

    channels: int | None = None
    channel_layout: str | None = None
    sample_rate: int | None = None

    language: str | None = None
    title: str | None = None

    is_default: bool = False
    is_forced: bool = False
    is_hearing_impaired: bool = False
    is_external: bool = False
    """Always false for now: an external subtitle is a separate file, and nothing in this feature
    inspects one. The column exists because the wire flag does."""

    bitrate: int | None = None

    video_range: VideoRange | None = None
    video_range_type: VideoRangeType | None = None
    """Both `None` on anything that is not a video stream; a video stream always has both."""

    color_range: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    color_space: str | None = None
    pixel_format: str | None = None

    ref_frames: int | None = None
    is_interlaced: bool = False
    is_anamorphic: bool | None = None

    @property
    def reference_frame_rate(self) -> float | None:
        """The frame rate the reference believes: the average one, unless it is implausible.

        This is the number a negotiation compares a `VideoFramerate` ceiling against - the single
        itself, not the shorter decimal `media/info.py` prints from it (`narrow_to_single`).
        """
        average = _rational(self.average_framerate)
        real = _rational(self.framerate)
        chosen = (
            average
            if average is not None and narrow_to_single(average) < IMPLAUSIBLE_FRAME_RATE
            else real
        )
        return None if chosen is None else narrow_to_single(chosen)


@dataclass(frozen=True, slots=True)
class MediaInspection:
    """One media file, opened.

    `size` and `mtime_ns` are 003's change signal, carried here because the inspection is only
    valid for the bytes it read: the repository compares them rather than re-opening the file
    (plan section 6.1).
    """

    size: int
    mtime_ns: int

    container: str
    """**The reference's normalised container string, which is not always one container.**

    ffprobe answers a demuxer *list* for the containers several formats share, and the reference
    stores one normalised form of it: `matroska,webm` becomes `mkv` where the streams disqualify
    WebM, while `mov,mp4,m4a,3gp,3g2,mj2` survives whole. Measured at item level, a `.mkv` answers
    `mkv` and a `.mp4` answers the six-member list `[probe: tools/probe_media_container.py,
    Jellyfin 10.11.11, 2026-08-29]`.

    The **single** container a media source reports is derived from this, twice and differently -
    by the file's extension on a listing, by the device profile in a negotiation - and neither
    derivation belongs to inspection. See the plan section 4 note.
    """

    format_names: str
    """What the demuxer actually said, before that normalisation. Kept because the normalisation
    is a claim about the reference rather than about the file, and re-deriving it must not cost a
    rescan of the library."""

    probed_at: datetime
    """When the inspection ran.

    Required rather than defaulted, and read back rather than write-only. Required because a
    record without one did not come from an inspection, and only the inspection knows; read back
    because revision 0005 exists entirely because two columns that were written and never read
    looked empty on every refresh, and were therefore rewritten for ever.
    """

    runtime_ticks: int | None = None
    bitrate: int | None = None

    video_keyframes: tuple[int, ...] | None = None
    """Keyframe presentation times in ticks, in order; `None` when the file has no video stream.
    The input to copy-bucket segment boundaries (plan section 6.4), stored so predicting them does
    not re-read the file per playlist request."""

    streams: tuple[InspectedStream, ...] = field(default_factory=tuple)

    def unchanged_since(self, size: int, mtime_ns: int) -> bool:
        """Whether this inspection still describes a file with that change signal."""
        return self.size == size and self.mtime_ns == mtime_ns

    @property
    def video(self) -> InspectedStream | None:
        """The first video stream, or `None`. What "is this a video file" means here."""
        return next((one for one in self.streams if one.kind is StreamKind.VIDEO), None)

    @property
    def audio(self) -> InspectedStream | None:
        return next((one for one in self.streams if one.kind is StreamKind.AUDIO), None)


__all__ = [
    "IMPLAUSIBLE_FRAME_RATE",
    "InspectedStream",
    "MediaInspection",
    "StreamKind",
    "VideoRange",
    "VideoRangeType",
    "narrow_to_single",
]
