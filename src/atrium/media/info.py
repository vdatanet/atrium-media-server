# SPDX-License-Identifier: GPL-3.0-or-later
"""What a response says about a file, assembled from what inspection wrote down.

`media/probe.py` records *facts about a file*; this module turns them into the two wire shapes a
client reads - `MediaSourceInfo` and `MediaStream` - and it is the only place that conversion
happens. The two vocabularies differ on purpose (see `domain/media.py`), and the clearest case is
the single container a source reports: it is not a property of the file at all, so it is derived
here, per response, rather than stored.

**Nothing here touches the filesystem or the database.** Everything it needs arrives as arguments:
the item's sources, whatever inspection stored for each of them, and the library root a path is
rebuilt from. That is what lets the item DTO builder emit media properties while still issuing no
query (005 plan section 5).

**A source exists for every part, inspected or not.** The reference emits one for a file it has
never probed - streams empty, container taken from the file's extension `[source:
MediaBrowser.Controller/Entities/BaseItem.cs:1200-1207 @ v10.11.11]` - and so does this. An item
whose inspection failed or has not run therefore still answers a playable path rather than
vanishing from a client's view.

**What is deliberately not emitted** is three groups, and each is a different debt:

* `DisplayTitle` and the five `Localized*` properties are the *localised* rendering of a track -
  "Español - MP3 - Stereo - Predeterminado" on a server whose culture is Spanish. They need the
  server's localisation table, and an English-only approximation would be a different string from
  the reference's on every track rather than a missing one.
* `IsAVC`, `TimeBase` and `NalLengthSize` are read from the demuxer and are not columns of
  migration 0006. Emitting them means a further migration, which is not this change.
* `DeliveryMethod`, `DeliveryUrl` and `IsExternalUrl` are declared and left empty *here*, and
  filled by the negotiation: they are answers to one rather than facts about a file, so
  `api/media_info.py` writes them onto the streams of a source it has negotiated about and every
  bare read leaves them absent (011 T9). `Path` arrives with the subtitle files discovered beside
  the media. `Score` is emitted by nothing at all: the reference scores only the streams a user's
  subtitle mode selected, and v1 keeps no mode.

See specs/008-playback-negotiation-and-delivery/spec.md section 3.1 and plan section 6.1, and
specs/011-subtitle-delivery/spec.md section 3.2 and plan section 6.1.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Annotated, Any

from atrium.compat.guids import derive
from atrium.compat.model import AtriumModel, PropertyKeyed
from atrium.compat.ticks import WireTicks
from atrium.domain.items import Item, MediaSource
from atrium.domain.media import (
    IMPLAUSIBLE_FRAME_RATE,
    InspectedStream,
    MediaInspection,
    StreamKind,
    narrow_to_single,
)

#: .NET counts 100-nanosecond ticks from 0001-01-01; the Unix epoch is this far along.
TICKS_AT_UNIX_EPOCH = 621_355_968_000_000_000

#: Nanoseconds per tick. A modification time in nanoseconds is truncated, not rounded, which is
#: what .NET does when it reads a file's timestamp on a filesystem that has more precision.
NANOSECONDS_PER_TICK = 100

#: What the reference calls a local file's transport, and the only one v1 has.
FILE_PROTOCOL = "File"

#: The one media-source type a file produces. The reference's other members describe grouped
#: alternate versions and placeholders, neither of which v1 creates.
DEFAULT_SOURCE_TYPE = "Default"

#: The one video type v1 produces: a plain file, as opposed to the reference's disc-image members.
VIDEO_FILE = "VideoFile"

#: What a stream that is not video answers for both range properties. The reference's enums default
#: to this member rather than to null, so every stream carries both - measured on 471 streams
#: `[probe: tools/probe_media_source.py, Jellyfin 10.11.11, 2026-08-29]`.
UNKNOWN_RANGE = "Unknown"

#: The audio profiles that name a spatial format, and what the reference calls each. `[source:
#: MediaBrowser.Model/Entities/MediaStream.cs AudioSpatialFormat @ v10.11.11]`
SPATIAL_FORMATS = (("dolby atmos", "DolbyAtmos"), ("dts:x", "DTSX"))

#: The answer for everything else, including every stream that is not audio. Same source.
NO_SPATIAL_FORMAT = "None"

#: The height at which the reference calls an item high definition. `[source:
#: MediaBrowser.Controller/Entities/BaseItem.cs:391 @ v10.11.11]`
HD_HEIGHT = 720

#: The two codec spellings that mean an image subtitle by being the *whole* name rather than by
#: being contained in one - the bare file extensions, which is what a stream read out of a
#: `.sup` or a `.sub` is named after. Containment would be wrong here: `subrip` contains `sub`.
#: `[source: MediaBrowser.Model/Entities/MediaStream.cs:751-761 @ v10.11.11]`
IMAGE_SUBTITLE_SPELLINGS = frozenset({"sup", "sub"})


class MediaStream(AtriumModel):
    """One elementary stream on the wire, in the pinned document's field order.

    Every property here is either stored by inspection or derived from something that is. The
    three families that are not emitted at all are named in this module's own docstring, with the
    reason each is owed rather than absent.
    """

    codec: str | None = None
    codec_tag: str | None = None
    language: str | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    title: str | None = None
    #: Both always present, `"Unknown"` on anything that is not video - the reference's enums
    #: default to a member rather than to null, so these two never fall to null-suppression.
    video_range: str = UNKNOWN_RANGE
    video_range_type: str = UNKNOWN_RANGE
    audio_spatial_format: str = NO_SPATIAL_FORMAT
    is_interlaced: bool = False
    channel_layout: str | None = None
    bit_rate: int | None = None
    bit_depth: int | None = None
    ref_frames: int | None = None
    channels: int | None = None
    sample_rate: int | None = None
    is_default: bool = False
    is_forced: bool = False
    is_hearing_impaired: bool = False
    height: int | None = None
    width: int | None = None
    #: **`int | float`, and the union is the wire format rather than indecision.** The reference
    #: declares all three as 32-bit floats and .NET's serialiser writes an integral one without a
    #: fractional part - `25`, not `25.0` - which a byte comparison sees. `_frame_rate` returns
    #: whichever of the two the value is, and pydantic's smart union then keeps it.
    average_frame_rate: int | float | None = None
    real_frame_rate: int | float | None = None
    reference_frame_rate: int | float | None = None
    profile: str | None = None
    type: str
    aspect_ratio: str | None = None
    index: int
    #: Never set. The reference scores only the streams a user's subtitle *mode* selected and a
    #: mode of `None` scores none, which is the mode v1 has - so this falls to null suppression on
    #: every stream, exactly as it does for a `SubtitleMode: None` user of the reference `[source:
    #: Emby.Server.Implementations/Library/MediaStreamSelector.cs:97-152 @ v10.11.11]`.
    score: int | None = None
    is_external: bool = False
    #: Answers to a negotiation rather than facts about a file, and absent from a bare read
    #: `[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`. 011 T9 fills
    #: them from `api/media_info.py`: a delivery method on every subtitle stream of a negotiated
    #: source, and the address and its flag on the streams whose method is `External` alone.
    delivery_method: str | None = None
    delivery_url: str | None = None
    is_external_url: bool | None = None
    #: **Both are non-nullable on the reference and are answered for every stream**, video, audio
    #: and cover art included, where they are `false` - measured on 1 968 streams, 947 of them
    #: subtitles `[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`. They
    #: read the codec spelling `media/probe.py` normalised, never the file.
    is_text_subtitle_stream: bool = False
    supports_external_stream: bool = False
    #: The subtitle file this stream was read out of, and nothing else: absent on every container
    #: stream on the wire. 011 T4 fills it for the streams it discovers.
    path: str | None = None
    pixel_format: str | None = None
    #: Declared a double upstream and always integral in practice - ffprobe reports a whole
    #: number - so the same union keeps `31` from becoming `31.0`.
    level: int | float | None = None
    is_anamorphic: bool | None = None


class MediaSourceInfo(AtriumModel):
    """One file behind an item, in the pinned document's field order.

    The declared set is the measured wire: 31 properties on every audio source and those plus
    `VideoType` on every video one, across 180 sources of three item types
    `[probe: tools/probe_media_source.py, Jellyfin 10.11.11, 2026-08-29]`. Most of them are
    constants for a local file and are declared with those constants rather than left out - a
    property the reference sends unconditionally is one a client can see missing, which is the
    argument 005 used for `ChannelId` and it applies here to fifteen booleans.

    `TranscodingUrl` and `TranscodingContainer` are absent on a listing because they are answers
    to a *negotiation*, and `DefaultSubtitleStreamIndex` because subtitle selection is a per-user
    choice v1 does not make.
    """

    protocol: str = FILE_PROTOCOL
    id: str
    path: str | None = None
    type: str = DEFAULT_SOURCE_TYPE
    container: str | None = None
    size: int | None = None
    name: str | None = None
    is_remote: bool = False
    #: `ETag`, not `Etag`. The item-level property of the same idea is spelled with a lowercase
    #: `t` and this one is not, which is why the field is `e_tag`: the generator produces the
    #: right spelling for each from the Python name, and the conformance sweep would fail either
    #: of them written the other way.
    e_tag: str | None = None
    run_time_ticks: WireTicks | None = None
    read_at_native_framerate: bool = False
    ignore_dts: bool = False
    ignore_index: bool = False
    gen_pts_input: bool = False
    supports_transcoding: bool = True
    supports_direct_stream: bool = True
    supports_direct_play: bool = True
    is_infinite_stream: bool = False
    use_most_compatible_transcoding_profile: bool = False
    requires_opening: bool = False
    requires_closing: bool = False
    requires_looping: bool = False
    supports_probing: bool = True
    video_type: str | None = None
    media_streams: list[MediaStream] | None = None
    media_attachments: list[Any] | None = None
    formats: list[str] | None = None
    bitrate: int | None = None
    required_http_headers: Annotated[dict[str, str] | None, PropertyKeyed] = None
    transcoding_url: str | None = None
    transcoding_sub_protocol: str = "http"
    transcoding_container: str | None = None
    default_audio_stream_index: int | None = None
    default_subtitle_stream_index: int | None = None
    has_segments: bool = False


# ------------------------------------------------------------------------------------------------
# The derivations
# ------------------------------------------------------------------------------------------------


def media_etag(mtime_ns: int) -> str:
    """The tag the reference puts on a local file's media source.

    `MD5` over the file's modification time expressed as a **.NET tick count**, and then the two
    conventions that make reading the assignment insufficient: the decimal string is hashed as
    **UTF-16 little-endian**, and the sixteen bytes are rendered through .NET's GUID byte order,
    which reverses the first three groups `[source:
    MediaBrowser.Controller/Entities/BaseItem.cs:1164, MediaBrowser.Common/Extensions/
    BaseExtensions.cs GetMD5 @ v10.11.11]`.

    Both were proven rather than reasoned: three files of three item types had their exact tick
    count recovered from the tag by searching the second their `Last-Modified` header names
    `[probe: tools/probe_media_source.py, Jellyfin 10.11.11, 2026-08-29]`. Either convention taken
    naively produces a well-formed 32-character tag that is wrong for every file, and no shape
    check would notice.

    It is not a hash of the bytes, so it changes when the file is touched and not when it is
    rewritten identically - which is the same signal 003 already uses for staleness.
    """
    ticks = TICKS_AT_UNIX_EPOCH + mtime_ns // NANOSECONDS_PER_TICK
    digest = hashlib.md5(str(ticks).encode("utf-16-le"), usedforsecurity=False).digest()
    return (digest[3::-1] + digest[5:3:-1] + digest[7:5:-1] + digest[8:]).hex()


def source_container(container: str | None, relative_path: str) -> str | None:
    """The single container a **media source** reports on a listing.

    The stored string is the reference's normalised container, which for several formats is a
    demuxer *list*; resolving it to one name is a property of the response rather than of the file
    (spec section 3.1). On a listing no profile is involved: the file's own extension wins where
    the list contains it - case-insensitively, and in the file's own casing - and the list's first
    member wins where it does not `[source:
    Emby.Server.Implementations/Dto/DtoService.cs:316-352 @ v10.11.11]`,
    `[probe: tools/probe_media_container.py, Jellyfin 10.11.11, 2026-08-29]`.

    A single-name container is passed through untouched, and a file with no inspection behind it
    falls back to its extension, which is what the reference does for the same case.
    """
    extension = _extension(relative_path)
    if not container:
        return extension
    members = container.split(",")
    if len(members) < 2:
        return container
    if extension is not None and any(one.lower() == extension.lower() for one in members):
        return extension
    return members[0]


def _extension(relative_path: str) -> str | None:
    suffix = PurePosixPath(relative_path).suffix.lstrip(".")
    return suffix or None


def _source_name(relative_path: str) -> str:
    """What the reference calls a source: the file's name without its extension. `[source:
    MediaBrowser.Controller/Entities/BaseItem.cs GetMediaSourceName @ v10.11.11]`"""
    return PurePosixPath(relative_path).stem


def source_id(item_id: str, part_index: int, relative_path: str) -> str:
    """The identifier a client addresses this file by.

    Part zero answers the **item's own id**, which is the reference's convention - it derives a
    source's id from the item that owns the file, and 003 derives an item's id from part zero's
    path, so the two coincide without being made to.

    A later part has no item of its own here, because Atrium models a multi-part film as one item
    with several sources where the reference models it as several items (see the note in spec
    section 3.1). Its id is derived from the item and the file, so it is stable across rescans and
    across a remount, like every other identifier in this project (Principle VII).

    Public since 008 T7, because `mediaSourceId` on a delivery route is resolved by deriving these
    and comparing - there is no stored column to look one up in, and a second derivation beside
    this one would be a source a client could address on one route and not the other.
    """
    if part_index == 0:
        return item_id
    return derive(item_id, relative_path)


def _source_id(item: Item, part_index: int, part: MediaSource) -> str:
    return source_id(item.id, part_index, part.relative_path)


def _spatial_format(stream: InspectedStream) -> str:
    if stream.kind is not StreamKind.AUDIO or not stream.profile:
        return NO_SPATIAL_FORMAT
    lowered = stream.profile.lower()
    return next((name for token, name in SPATIAL_FORMATS if token in lowered), NO_SPATIAL_FORMAT)


def _frame_rate(rational: str | None) -> int | float | None:
    """A frame rate as the wire carries it, from the exact rational inspection stored.

    Two conversions, and the second is the one that is easy to miss. The rational is divided -
    that part is obvious, and it is done here rather than in the prober because the rational is
    what the segment cadence needs (plan section 6.4) while a client reads a number. Then the
    result is put through **32-bit** precision, because the reference's field is a single and its
    serialiser writes the shortest string that round-trips as one: `24000/1001` reaches a client
    as `23.976025`, not as the seventeen digits a double prints
    `[probe: tools/probe_media_source.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    if rational is None:
        return None
    dividend, _, divisor = rational.partition("/")
    try:
        top, bottom = float(dividend), float(divisor or 1)
    except ValueError:
        return None
    return None if bottom == 0 else as_single(top / bottom)


def as_single(value: float) -> int | float:
    """The number a 32-bit float would print, and an integer where it is whole.

    Public because `media/urls.py` prints the same number into a `MaxFramerate`: a client reads
    `23.975988` off a stream and `23.975988` out of the URL it is handed, and two roundings would
    eventually disagree in the last digit.

    The narrowing itself is `domain/media.py`'s, because a negotiation compares against the same
    single (008 T4). What belongs here is the **printing**, and it is a different number: .NET
    writes the shortest decimal that reads back as the same single, found by trying precisions in
    turn, so `23.975988388061523` reaches a client as `23.975988`. The negotiation is handed the
    former and a client reads the latter, which is why a ceiling stated at the printed rate is
    refused (`narrow_to_single`).

    An integral result comes back as an `int` so that the serialiser writes `25` rather than
    `25.0` - a difference no parser sees and every byte comparison does.
    """
    narrowed = narrow_to_single(value)
    for digits in range(1, 10):
        rounded = float(f"{narrowed:.{digits}g}")
        if narrow_to_single(rounded) == narrowed:
            narrowed = rounded
            break
    return int(narrowed) if narrowed.is_integer() else narrowed


def _reference_frame_rate(
    average: int | float | None, real: int | float | None
) -> int | float | None:
    """The average, unless it is implausible, in which case the real one. `[source:
    MediaBrowser.Model/Entities/MediaStream.cs ReferenceFrameRate @ v10.11.11]`"""
    if average is not None and average < IMPLAUSIBLE_FRAME_RATE:
        return average
    return real


def is_text_subtitle(stream: InspectedStream) -> bool:
    """Whether this stream is a subtitle track made of *text* rather than of pictures.

    **A lookup on the codec spelling, not an inspection of the file.** Everything counts as text
    except a codec containing `pgs`, `dvdsub` or `dvbsub`, or spelled exactly `sup` or `sub` - and
    `microdvd` is exempted from the whole rule, because that text format shares the `.sub`
    extension with an image one `[source: MediaBrowser.Model/Entities/MediaStream.cs:751-761 @
    v10.11.11]`. A stream with no codec at all is text only when it came from a file beside the
    media `[source: MediaBrowser.Model/Entities/MediaStream.cs:639-654 @ v10.11.11]`.

    The spelling it reads is the one `media/probe.py` normalised. Against the tool's own names the
    rule inverts on `dvd_subtitle` and `dvb_subtitle`, which contain neither `dvdsub` nor `dvbsub`
    until they have been renamed - so every DVD subtitle track in a library would be announced as
    text, offered in a manifest and offered for conversion.
    """
    if stream.kind is not StreamKind.SUBTITLE:
        return False
    if not stream.codec and not stream.is_external:
        return False
    return is_text_format(stream.codec)


def is_text_format(spelling: str | None) -> bool:
    """The same rule over a bare format name, which is what a *profile* declares.

    The reference splits the two: `IsTextSubtitleStream` is the property of a stream and
    `IsTextFormat` is the static rule behind it, and the negotiation's subtitle ladder compares
    the two against each other - a profile's declared format has to be the same *kind* as the
    stream for that profile to serve it `[source:
    MediaBrowser.Model/Entities/MediaStream.cs:751-761,
    MediaBrowser.Model/Dlna/StreamBuilder.cs:1476, 1564 @ v10.11.11]`.

    **An absent format is text**, because every clause of the rule is a negation: a profile that
    declares no format at all matches a text stream and never an image one. That is not an edge
    case invented here - it is what a `{"Method": "External"}` entry with no `Format` does.
    """
    lowered = (spelling or "").lower()
    if "microdvd" in lowered:
        return True
    return not (
        "pgs" in lowered
        or "dvdsub" in lowered
        or "dvbsub" in lowered
        or lowered in IMAGE_SUBTITLE_SPELLINGS
    )


def is_pgs_subtitle(stream: InspectedStream) -> bool:
    """Whether this is a Presentation Graphic Stream track - the Blu-ray bitmap format.

    Its own rule rather than "not text": the two disagree on every DVD and broadcast bitmap
    format, and that disagreement is the whole of `supports_external_stream` for those `[source:
    MediaBrowser.Model/Entities/MediaStream.cs:765-771 @ v10.11.11]`.
    """
    if stream.kind is not StreamKind.SUBTITLE:
        return False
    codec = stream.codec or ""
    if not codec and not stream.is_external:
        return False
    lowered = codec.lower()
    return "pgs" in lowered or lowered == "sup"


def supports_external_stream(stream: InspectedStream) -> bool:
    """Whether this stream can be served on its own, away from the file it sits in.

    A file beside the media can, a text track can, and a Presentation Graphic Stream track can -
    everything else, a DVD bitmap track included, cannot `[source:
    Emby.Server.Implementations/Library/MediaSourceManager.cs:112-129 @ v10.11.11]`. Measured on a
    real library, `PGSSUB` answers `true` and `DVDSUB` answers `false` `[probe:
    tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`.
    """
    return stream.is_external or is_text_subtitle(stream) or is_pgs_subtitle(stream)


def stream_of(stream: InspectedStream, root: str | None = None) -> MediaStream:
    """One stored stream as the wire shape."""
    average = _frame_rate(stream.average_framerate)
    real = _frame_rate(stream.framerate)
    return MediaStream(
        codec=stream.codec,
        codec_tag=stream.codec_tag,
        language=stream.language,
        color_range=stream.color_range,
        color_space=stream.color_space,
        color_transfer=stream.color_transfer,
        color_primaries=stream.color_primaries,
        title=stream.title,
        video_range=UNKNOWN_RANGE if stream.video_range is None else stream.video_range.value,
        video_range_type=(
            UNKNOWN_RANGE if stream.video_range_type is None else stream.video_range_type.value
        ),
        audio_spatial_format=_spatial_format(stream),
        is_interlaced=stream.is_interlaced,
        channel_layout=stream.channel_layout,
        bit_rate=stream.bitrate,
        bit_depth=stream.bit_depth,
        ref_frames=stream.ref_frames,
        channels=stream.channels,
        sample_rate=stream.sample_rate,
        is_default=stream.is_default,
        is_forced=stream.is_forced,
        is_hearing_impaired=stream.is_hearing_impaired,
        height=stream.height,
        width=stream.width,
        average_frame_rate=average,
        real_frame_rate=real,
        reference_frame_rate=_reference_frame_rate(average, real),
        profile=stream.profile,
        type=stream.kind.value.capitalize(),
        aspect_ratio=stream.aspect_ratio,
        index=stream.index,
        is_external=stream.is_external,
        # **Absolute on the wire and relative in storage**, which is the rule every path in this
        # project follows and the reason `MediaSourceInfo.path` is built the same way one line
        # above: a remount must change nothing that is stored. Absent on every container stream,
        # measured - the reference answers `Path` on the streams that came from a file and on no
        # others `[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`.
        path=(
            None
            if root is None or stream.external_path is None
            else f"{root.rstrip('/')}/{stream.external_path}"
        ),
        is_text_subtitle_stream=is_text_subtitle(stream),
        supports_external_stream=supports_external_stream(stream),
        pixel_format=stream.pixel_format,
        level=stream.level,
        is_anamorphic=stream.is_anamorphic,
    )


def _default_audio_index(streams: Sequence[InspectedStream]) -> int | None:
    """Which audio stream a client should start with, absent any preference of its own.

    The reference sorts by the user's language preferences and then prefers the default-flagged
    track; with no preference expressed that reduces to "the default-flagged audio stream, or the
    first one" `[source: Emby.Server.Implementations/Library/MediaStreamSelector.cs
    GetDefaultAudioStreamIndex @ v10.11.11]`. v1 stores no per-user audio language preference, so
    that is the whole rule here, and the day a preference exists this is where it applies.
    """
    audio = [one for one in streams if one.kind is StreamKind.AUDIO]
    if not audio:
        return None
    return next((one.index for one in audio if one.is_default), audio[0].index)


def source_of(
    item: Item,
    part_index: int,
    part: MediaSource,
    inspection: MediaInspection | None,
    root: str | None = None,
    *,
    is_video: bool,
) -> MediaSourceInfo:
    """One part of an item as the wire shape, with or without an inspection behind it."""
    streams = () if inspection is None else inspection.streams
    return MediaSourceInfo(
        id=_source_id(item, part_index, part),
        path=None if root is None else f"{root.rstrip('/')}/{part.relative_path}",
        container=source_container(
            None if inspection is None else inspection.container, part.relative_path
        ),
        size=part.size if inspection is None else inspection.size,
        name=_source_name(part.relative_path),
        e_tag=None if part.mtime_ns is None else media_etag(part.mtime_ns),
        run_time_ticks=None if inspection is None else inspection.runtime_ticks,
        video_type=VIDEO_FILE if is_video else None,
        media_streams=[stream_of(one, root) for one in streams],
        media_attachments=[],
        formats=[],
        bitrate=None if inspection is None else inspection.bitrate,
        required_http_headers={},
        default_audio_stream_index=_default_audio_index(streams),
    )


def sources_for(
    item: Item,
    inspections: Sequence[MediaInspection | None],
    root: str | None = None,
    *,
    is_video: bool,
) -> list[MediaSourceInfo]:
    """Every part of an item, in part order, whatever inspection managed to read.

    `inspections` is positional against `item.sources`: index *n* is what inspection stored for
    part *n*, or `None`. A short sequence is padded rather than refused, so a page whose probe rows
    are partly missing answers partly-detailed sources instead of nothing.
    """
    return [
        source_of(
            item,
            index,
            part,
            inspections[index] if index < len(inspections) else None,
            root,
            is_video=is_video,
        )
        for index, part in enumerate(item.sources)
    ]


# ------------------------------------------------------------------------------------------------
# The item's own media properties
# ------------------------------------------------------------------------------------------------
#
# These read the stored inspections rather than the assembled sources, and that is not a shortcut:
# a bare list row carries `Container`, `HasSubtitles` and `VideoType` without carrying
# `MediaSources` at all, so building a source to answer them would build the expensive shape for
# every row of every list to read one string off it. The reference has the same split for the same
# reason - all three are columns on its item, denormalised at inspection.


def item_container(item: Item, inspections: Sequence[MediaInspection | None]) -> str | None:
    """The item-level container: the normalised string inspection stored for part zero.

    Not resolved to a single name - that resolution belongs to a media source, and the same file
    answers differently on a listing and in a negotiation (spec section 3.1). An uninspected file
    answers its extension, which is the fallback the reference uses for the same case `[source:
    MediaBrowser.Controller/Entities/BaseItem.cs:1200-1207 @ v10.11.11]`.
    """
    first = inspections[0] if inspections else None
    if first is not None and first.container:
        return first.container
    return _extension(item.sources[0].relative_path) if item.sources else None


def item_streams(
    inspections: Sequence[MediaInspection | None], root: str | None = None
) -> list[MediaStream]:
    """The item-level `MediaStreams`: part zero's, and only part zero's. `[source:
    Emby.Server.Implementations/Dto/DtoService.cs:1151-1170 @ v10.11.11]`

    `root` is what a discovered subtitle stream's `Path` is rebuilt from, the same way a media
    source's own is; without it those streams answer no path, which is the honest answer for a
    library whose root nothing here can name."""
    first = inspections[0] if inspections else None
    return [] if first is None else [stream_of(one, root) for one in first.streams]


def primary_video_stream(
    inspections: Sequence[MediaInspection | None],
) -> InspectedStream | None:
    """The video stream an item's own `Width`, `Height` and `IsHD` describe.

    The first video stream of part zero: the reference stores those three on the item, set from
    the file it probed, and the file it probed is part zero.
    """
    first = inspections[0] if inspections else None
    return None if first is None else first.video


def has_subtitles(inspections: Sequence[MediaInspection | None]) -> bool:
    """Whether any stream of any part is a subtitle. `[source:
    MediaBrowser.Providers/MediaInfo/FFProbeVideoInfo.cs:275 @ v10.11.11]`

    The reference counts subtitle files *beside* the media here too; v1 inspects none, so an item
    with a sidecar subtitle and none inside its container answers nothing where the reference
    answers `true`. Recorded in spec section 3.1 rather than approximated.
    """
    return any(
        stream.kind is StreamKind.SUBTITLE
        for one in inspections
        if one is not None
        for stream in one.streams
    )


def is_hd(inspections: Sequence[MediaInspection | None]) -> bool:
    """720 lines or more, which is the whole of the reference's definition."""
    stream = primary_video_stream(inspections)
    return stream is not None and (stream.height or 0) >= HD_HEIGHT


__all__ = [
    "HD_HEIGHT",
    "MediaSourceInfo",
    "MediaStream",
    "as_single",
    "has_subtitles",
    "is_hd",
    "is_pgs_subtitle",
    "is_text_format",
    "is_text_subtitle",
    "item_container",
    "item_streams",
    "media_etag",
    "primary_video_stream",
    "source_container",
    "source_id",
    "source_of",
    "sources_for",
    "stream_of",
    "supports_external_stream",
]
