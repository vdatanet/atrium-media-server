# SPDX-License-Identifier: GPL-3.0-or-later
"""Segment boundaries predicted from stored data, and the three playlists rendered from them.

Pure arithmetic and string building: nothing here starts a process, opens a file or knows what a
session is. That is what makes spec section 3.7's headline measurement possible at all - a media
playlist of 2 843 segments arriving complete and `ENDLIST`-marked in 0.18 s, before a single
segment exists `[probe: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`. Boundaries predicted
from the source are also what makes them **deterministic**, which is AC-22: the same request twice
is the same list, so a client that lost a segment can ask for it again.

**The third is 011's subtitle playlist**, and it shares nothing with the other two but this
module's purity: its windows are laid across a runtime rather than planned from keyframes, its
entries address a different route, and its header order is its own. It lives here because it is
the same kind of thing - a playlist computed from stored data - and not because any line of it is
shared (`subtitle_playlist`).

## The cadence, and the rounding rule behind the measured 3.004 s

Plan section 6.8 left this owed to the task that implements it, and it is the one arithmetic in
this module that cannot be guessed. The requested segment length is scaled up when the output is
being **re-encoded** at a fractional frame rate, so that a whole number of frames fits in a
segment `[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:1425-1432 @ v10.11.11]`:

    milliseconds = ceil(seconds * 1000 * ceil(rate) / rate)

Three details decide the answer, and each of them was measured rather than assumed
`[probe: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`:

* **The rate is the request's, not the file's.** The reference reads `MaxFramerate` off the query
  for a re-encode - the negotiation put the source's clamped rate there - and the *stream's*
  reference rate only when the video is copied, where no scaling happens anyway `[source:
  MediaBrowser.Controller/MediaEncoding/EncodingJobInfo.cs:304-315 @ v10.11.11]`. A `main.m3u8`
  asked for with no `MaxFramerate` at all is therefore unscaled, and answers 3.000 s.
* **The rate is a 32-bit float**, because it made a round trip through a decimal in that URL. The
  measured film reports `23.975988`, and `ceil(3000 * 24 / 23.975988) = 3004`; the same film at an
  exact `24000/1001` - `23.976025` - answers **3003**. The published 3.004 s is a fact about that
  film's stored rate and not about "23.976 fps", which is why the golden below pins the *rule* at
  three rates rather than pinning the number.
* **Only `LessThanEqual`-style scaling, never rounding.** `ceil` at five requested lengths:
  1 s → 1.002, 2 s → 2.003, 3 s → 3.004, 5 s → 5.006, 10 s → 10.011, all at the same rate.

The unrequested default is **3 s for a re-encode and 6 s for a copy** `[source:
MediaBrowser.Controller/Streaming/StreamState.cs:74-105 @ v10.11.11]`. The reference's copy branch
also answers 6 for an Apple user agent and 3 for a segmented live stream; v1 has no live streams
and the two remaining paths both answer 6, so the user-agent test decides nothing here and is not
reproduced.

## The two shapes, and which one a copy gets

A re-encode lays an **equal-length grid** over the runtime, because ffmpeg is told to force
keyframes on exactly those boundaries. A copy has to cut where the source already has keyframes -
and the reference does that **only for a container the operator has allowed on-demand keyframe
extraction for**, whose shipped default is `mkv` alone `[source:
MediaBrowser.Model/Configuration/EncodingOptions.cs:60,
src/Jellyfin.MediaEncoding.Hls/Playlist/DynamicHlsPlaylistGenerator.cs:38-47 @ v10.11.11]`.

**That is where spec section 3.7's parenthetical was wrong.** The measured "6.0 s per segment
stream-copied" came from an mp4 film, so it is the equal-length grid at the copy default and not
"the source's own keyframes". Asked at an off-grid 5 s, the same mp4 answers ten segments of
exactly 5.0 s and an mkv beside it answers `5.045, 5.0, 5.0, …` - the bucketing, visible only
where it is allowed `[probe: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from pathlib import PurePosixPath
from typing import Final

from atrium.domain.media import (
    InspectedStream,
    VideoRange,
    VideoRangeType,
    narrow_to_single,
)
from atrium.media.decision import StreamAction, StreamPlan

TICKS_PER_SECOND: Final = 10_000_000

#: The segment length a request that states none is planned at, split by what happens to the
#: video. `[source: MediaBrowser.Controller/Streaming/StreamState.cs:74-105 @ v10.11.11]`
ENCODE_SEGMENT_SECONDS: Final = 3
COPY_SEGMENT_SECONDS: Final = 6

#: The containers a stream copy's boundaries may be bucketed from the file's own keyframes for -
#: the reference's shipped `AllowOnDemandMetadataBasedKeyframeExtractionForExtensions`, whose live
#: value was read off the operator's server and is this one `[source:
#: MediaBrowser.Model/Configuration/EncodingOptions.cs:60 @ v10.11.11]`, `[probe:
#: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`. Every other container gets the equal grid,
#: because the reference's only metadata-based keyframe reader is the Matroska one.
KEYFRAME_EXTRACTION_EXTENSIONS: Final[tuple[str, ...]] = ("mkv",)

#: What the SDR entrance beside an HDR stream copy re-encodes to. The reference appends this one
#: unconditionally and two more - hevc and av1 - only where the operator has permitted those
#: encoders, and both permissions ship off `[source:
#: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:218-268,
#: MediaBrowser.Model/Configuration/EncodingOptions.cs:57-58 @ v10.11.11]`.
SDR_ENTRANCE_CODEC: Final = "h264"

#: What every segment URI in a media playlist begins with, and what the segment route's path
#: therefore has to spell: `hls1/{playlistId}/{segmentId}.{container}` with the playlist named
#: `main`.
SEGMENT_PREFIX: Final = "hls1/main/"

#: The segment container that makes a playlist fMP4 rather than MPEG-TS, which changes its
#: version and gives it an initialisation segment.
FMP4_CONTAINER: Final = "mp4"

#: The default segment container, and what `GetSegmentFileExtension` falls back to `[source:
#: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:1564-1572 @ v10.11.11]`.
DEFAULT_SEGMENT_CONTAINER: Final = "ts"

#: The `#EXTINF` number format: six decimals, always, including on a whole number of seconds.
_SIX_PLACES: Final = Decimal("0.000001")

#: The one group a master playlist puts its subtitle tracks in, and the value every variant line
#: names. A literal on the reference too - there is no second group and no naming rule `[source:
#: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:197-199 @ v10.11.11]`.
SUBTITLE_GROUP: Final = "subs"

#: The window length every announced address asks the subtitle playlist for. **Hard-coded on the
#: reference**, and not the segment length of the stream it stands beside `[source:
#: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:613-619 @ v10.11.11]`, `[probe:
#: tools/probe_subtitle_manifest.py, Jellyfin 10.11.11, 2026-08-29]`.
ANNOUNCED_WINDOW_SECONDS: Final = 30

#: What `LANGUAGE` says for a stream that states no language. A literal rather than an omission,
#: measured on the one text track of the reference library that states none `[probe: manual
#: requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`.
UNKNOWN_LANGUAGE: Final = "Unknown"


@dataclass(frozen=True, slots=True)
class Segment:
    """One boundary of the predicted list.

    Ticks rather than seconds, because ticks are what the URI carries and what a restart seeks to;
    the `#EXTINF` decimal is derived from them rather than the other way round, so the playlist's
    promise and the segment's own parameters cannot round apart.
    """

    index: int
    start_ticks: int
    duration_ticks: int

    @property
    def duration_text(self) -> str:
        """The `#EXTINF` number: `3.004000`, six decimals, half rounded up.

        `Decimal` rather than `format(float, '.6f')` because the two disagree on a midpoint -
        .NET's `"0.000000"` rounds a half away from zero and Python's float formatting rounds it
        to even - and a tick count is exact, so there is no reason to go through a float at all.
        """
        seconds = Decimal(self.duration_ticks) / Decimal(TICKS_PER_SECOND)
        return str(seconds.quantize(_SIX_PLACES, rounding=ROUND_HALF_UP))


def segment_extension(container: str | None) -> str:
    """The suffix a segment file carries, dot included.

    `"." + container`, and `.ts` when nothing was asked for - the reference's own one-liner, which
    is why an unknown container is not refused here: it becomes a suffix and fails later, at the
    muxer, exactly as it does there `[source:
    MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:1564-1572 @ v10.11.11]`.
    """
    named = (container or "").strip()
    return f".{named}" if named else f".{DEFAULT_SEGMENT_CONTAINER}"


def buckets_allowed(
    relative_path: str, allowed: Iterable[str] = KEYFRAME_EXTRACTION_EXTENSIONS
) -> bool:
    """Whether this file's own keyframes may be read to place a copy's boundaries.

    Keyed on the **extension**, not on the probed container, because that is what the reference
    tests - and the difference is visible on a file whose extension and demuxer disagree.
    """
    suffix = PurePosixPath(relative_path).suffix.lstrip(".").lower()
    return bool(suffix) and suffix in {one.lstrip(".").lower() for one in allowed}


def requested_seconds(requested: int | None, *, copying_video: bool) -> int:
    """The **unscaled** segment length in whole seconds - the URL's, or the path's default.

    The reference's `SegmentLength`, and the number several of its own decisions are made on
    rather than on the scaled cadence below: how far ahead of production a request may be before
    it counts as a seek is `24 / this` `[source:
    MediaBrowser.Controller/Streaming/StreamState.cs:74-105,
    Jellyfin.Api/Controllers/DynamicHlsController.cs:1497 @ v10.11.11]`.
    """
    if requested:
        return requested
    return COPY_SEGMENT_SECONDS if copying_video else ENCODE_SEGMENT_SECONDS


def cadence_milliseconds(
    requested: int | None, frame_rate: float | None, *, copying_video: bool
) -> int:
    """How long a body segment is, in milliseconds. The module docstring's rule, once.

    `requested` is the URL's `SegmentLength`; `frame_rate` is its `MaxFramerate`, which the
    negotiation set to the source's clamped rate and which is absent on a hand-written URL.
    """
    milliseconds = requested_seconds(requested, copying_video=copying_video) * 1000
    if copying_video or not frame_rate:
        return milliseconds
    # A 32-bit float, because the number made a round trip through a decimal in the URL it
    # arrived on and the reference re-reads it as a single. The difference is one millisecond at
    # 23.976 fps, and one millisecond is a different playlist.
    rate = narrow_to_single(frame_rate)
    if abs(rate - math.floor(rate + 0.001)) <= 0.001:
        return milliseconds
    return math.ceil(milliseconds * math.ceil(rate) / rate)


def plan_segments(
    runtime_ticks: int, milliseconds: int, keyframes: Sequence[int] | None = None
) -> tuple[Segment, ...]:
    """Every segment boundary of one session, predicted from the source alone.

    `keyframes` present means the copy bucketing: each cut is the first keyframe at or past the
    next multiple of the cadence, and the desired cut time advances by the cadence whatever the
    cut actually was - so a bucket that ran long does not push the ones after it. Absent, the
    boundaries are an equal grid with a short last segment.

    Returns an empty tuple for a source with no runtime, where the reference raises and answers
    `500`; the caller turns that into the same refusal rather than rendering a playlist of
    nothing.
    """
    if runtime_ticks <= 0 or milliseconds <= 0:
        return ()
    cadence_ticks = milliseconds * (TICKS_PER_SECOND // 1000)
    durations = (
        _equal_durations(runtime_ticks, cadence_ticks)
        if keyframes is None
        else _bucket_durations(runtime_ticks, cadence_ticks, keyframes)
    )
    segments: list[Segment] = []
    start = 0
    for index, duration in enumerate(durations):
        segments.append(Segment(index=index, start_ticks=start, duration_ticks=duration))
        start += duration
    return tuple(segments)


def _equal_durations(runtime_ticks: int, cadence_ticks: int) -> list[int]:
    whole, remainder = divmod(runtime_ticks, cadence_ticks)
    durations = [cadence_ticks] * whole
    if remainder:
        durations.append(remainder)
    return durations


def _bucket_durations(
    runtime_ticks: int, cadence_ticks: int, keyframes: Sequence[int]
) -> list[int]:
    durations: list[int] = []
    last = 0
    desired = cadence_ticks
    for keyframe in keyframes:
        if keyframe >= desired:
            durations.append(keyframe - last)
            last = keyframe
            desired += cadence_ticks
    # The tail always exists, even where the last keyframe is the last frame: the reference
    # appends it unconditionally, so a source whose final keyframe sits on the runtime produces a
    # zero-length final segment rather than one segment fewer.
    durations.append(max(runtime_ticks - last, 0))
    return durations


def media_playlist(segments: Sequence[Segment], *, query: str, container: str | None) -> str:
    """The variant playlist: VOD, complete, ended, and every URI carrying its own two ticks.

    `query` is the whole query string the request arrived with, leading `?` included, forwarded
    verbatim - which is how every parameter of the negotiation survives the hop to the segment
    route. The two per-segment parameters are appended to it: `runtimeTicks`, the segment's
    cumulative start, and `actualSegmentLengthTicks`, its exact duration.
    """
    extension = segment_extension(container)
    fmp4 = extension.lstrip(".").lower() == FMP4_CONTAINER
    longest = max((one.duration_ticks for one in segments), default=0)
    lines = [
        "#EXTM3U",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        # fMP4 segments need version 7; MPEG-TS ones are version 3, which is what the reference
        # answered on every measured playlist.
        f"#EXT-X-VERSION:{7 if fmp4 else 3}",
        f"#EXT-X-TARGETDURATION:{math.ceil(longest / TICKS_PER_SECOND)}",
        "#EXT-X-MEDIA-SEQUENCE:0",
    ]
    if fmp4:
        initialisation = f"{SEGMENT_PREFIX}-1{extension}{query}&runtimeTicks=0"
        lines.append(f'#EXT-X-MAP:URI="{initialisation}&actualSegmentLengthTicks=0"')
    for one in segments:
        lines.append(f"#EXTINF:{one.duration_text}, nodesc")
        lines.append(
            f"{SEGMENT_PREFIX}{one.index}{extension}{query}"
            f"&runtimeTicks={one.start_ticks}"
            f"&actualSegmentLengthTicks={one.duration_ticks}"
        )
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def subtitle_playlist(runtime_ticks: int, segment_seconds: int, token: str | None) -> str:
    """One text subtitle track's windows, laid across the source's runtime.

    **Not `media_playlist` with different arguments**, and the difference is not cosmetic: the two
    have different header orders - this one puts the target duration first and the playlist type
    last, where the media playlist does the opposite - a different `#EXTINF` line, no target
    duration derived from the entries, and entries that are addresses of a different route
    carrying their own switches `[source: Jellyfin.Api/Controllers/SubtitleController.cs:371-409
    @ v10.11.11]`. Sharing a renderer between them would mean a conditional on every line, and one
    of the two would end up wrong the first time either changed.

    `#EXT-X-TARGETDURATION` is the **requested** window length rather than the longest entry, so a
    playlist whose last window is short still declares the full one - which is what the reference
    writes and what the probe read back.

    The entries name a lower-case `stream.vtt` where the fetch route is declared `Stream.{format}`.
    That is the reference's own spelling and it is reproduced: a client follows a playlist as
    written, and 001's relaxed path matching is what makes it answer (011 AC-8).

    `token` is the caller's own credential, appended to every entry because these addresses are
    followed by a player that carries no header. A caller with none writes an empty `ApiKey=`,
    which is what the reference's own `string.Format` of a null does.
    """
    if runtime_ticks <= 0 or segment_seconds <= 0:
        # The caller refuses both of these before rendering (`api/subtitles.py`); this guard is
        # here because a window length of zero would not terminate the loop below.
        raise ValueError("a subtitle playlist needs a positive runtime and a positive window")
    window_ticks = segment_seconds * TICKS_PER_SECOND
    lines = [
        "#EXTM3U",
        f"#EXT-X-TARGETDURATION:{segment_seconds}",
        "#EXT-X-VERSION:3",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]
    start = 0
    while start < runtime_ticks:
        length = min(runtime_ticks - start, window_ticks)
        end = min(runtime_ticks, start + window_ticks)
        lines.append(f"#EXTINF:{window_duration_text(length)},")
        lines.append(
            f"stream.vtt?CopyTimestamps=true&AddVttTimeMap=true"
            f"&StartPositionTicks={start}&EndPositionTicks={end}&ApiKey={token or ''}"
        )
        start += window_ticks
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def window_duration_text(ticks: int) -> str:
    """A subtitle window's `#EXTINF` number: `30` for a whole one, `7.851` for a remainder.

    **The decimal point is the divergence** of behaviours section 3.12 and 011 AC-16. The
    reference appends the duration as a `double`, which formats in the *server's* culture rather
    than the invariant one, so a Spanish-configured host writes `#EXTINF:7,851,` into a file whose
    grammar reads that as a duration of `7` and a title of `851` `[probe:
    tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. Atrium has no server locale
    to reproduce the defect from, and inventing one in order to write a number wrongly is not
    replication - so the point is written always, and a whole window is written `30` and not
    `30.0`, which is what the reference writes for every window but the last.

    `Decimal` and not a float format: a tick count is exact, `10 000 000` ticks is exactly one
    second, and going through a float would introduce a rounding question that does not exist.
    """
    seconds = Decimal(ticks) / Decimal(TICKS_PER_SECOND)
    # `normalize` drops a trailing zero the division cannot produce today and `"f"` undoes the
    # exponent form it puts a whole number into - `Decimal("3E+1")` is `30`.
    return format(seconds.normalize(), "f")


@dataclass(frozen=True, slots=True)
class AnnouncedSubtitle:
    """One `#EXT-X-MEDIA` entry of a master playlist: one text subtitle track, addressed.

    Everything here is already decided. `name` is the assembled display title
    (`media/names.py`), because this module writes strings and does not know what a culture is;
    `is_default` is the answer to *did the request name this stream*, computed by comparing
    indices rather than carried as a selection, which is what makes 011 AC-7 fall out - an
    **image** index matches no announced stream, so every entry reads `DEFAULT=NO`.
    """

    index: int
    name: str
    language: str
    is_forced: bool
    is_default: bool
    uri: str


def subtitle_uri(media_source_id: str | None, index: int, token: str | None) -> str:
    """One announcement's address: a *playlist*, relative to the master's own directory.

    Three things about it are measured and none of them is obvious `[probe:
    tools/probe_subtitle_manifest.py, Jellyfin 10.11.11, 2026-08-29]`:

    * it addresses `subtitles.m3u8` and not a subtitle file, so a player following it lands on
      the windowed playlist and only then on the cues;
    * the window length is **hard-coded thirty seconds** rather than the stream's segment length;
    * it carries **the caller's own token**, and needs to: the playlist route requires a caller
      and a player following a `URI` out of a manifest sends no headers of its own.

    `media_source_id` is the request's, written the way the reference writes it - which is with
    nothing at all where the request named none. That state is unreachable there, because the
    parameter is declared required and an absent one is problem details naming `mediaSourceId`
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`; it is
    reachable here only because 008 binds that parameter optionally on every delivery route.
    """
    return (
        f"{media_source_id or ''}/Subtitles/{index}/subtitles.m3u8"
        f"?SegmentLength={ANNOUNCED_WINDOW_SECONDS}&ApiKey={token or ''}"
    )


def _announcement(subtitle: AnnouncedSubtitle) -> str:
    """One entry, verbatim: the attributes in the measured order, with no space anywhere.

    `AUTOSELECT=YES` on every entry and `GROUP-ID` a literal `subs`, both unconditional
    `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:604, 621-628 @ v10.11.11]`.
    """
    return (
        f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="{SUBTITLE_GROUP}",NAME="{subtitle.name}"'
        f",DEFAULT={'YES' if subtitle.is_default else 'NO'}"
        f",FORCED={'YES' if subtitle.is_forced else 'NO'}"
        f',AUTOSELECT=YES,URI="{subtitle.uri}",LANGUAGE="{subtitle.language}"'
    )


def master_playlist(
    *,
    query: str,
    video: StreamPlan | None,
    audio: StreamPlan | None,
    source_video: InspectedStream | None,
    frame_rate: float | None,
    options: Mapping[str, str] | None = None,
    subtitles: Sequence[AnnouncedSubtitle] = (),
) -> str:
    """The master playlist: one variant for the negotiation, and an SDR entrance beside an
    HDR stream copy.

    **"Exactly one variant" was wrong, and wrong about a branch nothing had reached.** OQ-7 was
    answered from a run against the library's first film, which is standard range in almost any
    library - so the entrance branch could not fire, and its absence was written down as the
    shape of the route. Measured against an HDR source, the reference appends an **h264 SDR
    entrance** whenever the video is stream-copied and the source's own range is HDR, at the
    same `BANDWIDTH` as the copy so that a client selects on colour rather than on rate
    `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:251-268 @ v10.11.11]`, `[probe:
    tools/probe_transcode_decision.py, Jellyfin 10.11.11, 2026-08-29]`.

    **Two more entrances exist there and cannot exist here**, and both are the same absence: the
    reference offers an hevc or an av1 entrance beside the h264 one when the copied codec is
    that codec *and the operator has permitted that encoder*, and those two permissions ship
    `false` `[source: MediaBrowser.Model/Configuration/EncodingOptions.cs:57-58 @ v10.11.11]`.
    Atrium has neither knob, so it answers what a stock reference answers; the measured
    three-variant master came from a server whose operator had turned `AllowHevcEncoding` on.
    See behaviours section 5.10.

    The remaining two multi-variant cases are still unreachable: an HEVC level 5.1 copy offered
    a level 5.0 entrance, and adaptive bitrate streaming, which the reference disables for a
    local caller, for a copy and for anything with no requested video bitrate `[source:
    Jellyfin.Api/Helpers/DynamicHlsHelper.cs:271-314 @ v10.11.11]`.

    **`BANDWIDTH` is what this server plans to produce**, which is the sum of the two stream
    plans' bitrates. The reference reports the same thing about itself - its `OutputVideoBitrate`
    is both what it advertises here and what it passes to the encoder - but it arrives at that
    number through a codec-efficiency scaling this project does not have, so an h264 re-encode of
    an hevc source is advertised higher there than here. The alternative would be advertising a
    rate the encoder is not aiming at, and the entrance is deliberately not a rung of a ladder:
    it carries the copy's own number, so nothing selects on it.

    **The subtitle group belongs to every variant, and this docstring's neighbour used to say
    "the variant".** That sentence was written while this function answered exactly one, and 008's
    own T15 gave an HDR stream copy an SDR entrance beside it hours later. The reference hands its
    group to *every* playlist line it appends - the copy, the two codec entrances, the h264
    entrance, the level rewrite and both adaptive-bitrate variants `[source:
    Jellyfin.Api/Helpers/DynamicHlsHelper.cs:213-315, 325-345 @ v10.11.11]` - measured on the wire
    against an HDR film copied for a client: three variants, all three ending `,SUBTITLES="subs"`
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`. It has to: the
    entrance exists so that a client which cannot render the copy has somewhere to go, and an
    entrance with no subtitle group is that client losing its subtitles for the very reason it was
    offered the entrance. So the group goes through `_variant`, which both lines already pass
    through, rather than onto the first line's construction.

    The `#EXT-X-MEDIA` block is written **before** the first `#EXT-X-STREAM-INF`, which is the
    reference's own order rather than a formatting choice: it appends the announcements and only
    then the variants `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:207-212 @ v10.11.11]`.
    """
    bandwidth = _bandwidth(video, audio)
    lowered = {name.lower(): value for name, value in (options or {}).items()}
    # `RESOLUTION` and `FRAME-RATE` describe the output's size and rate, and an entrance changes
    # neither - so they are computed once, from the copy, and repeated verbatim. The reference
    # reaches the same place by reading them off a state whose only mutation is the output codec.
    shape = _shape(video, source_video, frame_rate)
    # No announcements, no group - which is also how a source with no *text* subtitle stream
    # answers a request that asked for one, because the caller announces nothing for it.
    group = SUBTITLE_GROUP if subtitles else None

    lines = ["#EXTM3U"]
    lines += [_announcement(one) for one in subtitles]
    lines += _variant(
        bandwidth,
        _video_range(video, source_video),
        _codecs(video, audio, source_video, lowered),
        shape,
        f"main.m3u8{query}",
        group,
    )
    if video is not None and _entrance_applies(video, source_video):
        entrance = replace(video, action=StreamAction.ENCODE, codec=SDR_ENTRANCE_CODEC)
        lines += _variant(
            bandwidth,
            # A re-encode is SDR whatever it came from, which is the whole point of the entrance.
            ["VIDEO-RANGE=SDR"],
            _codecs(entrance, audio, source_video, lowered),
            shape,
            f"main.m3u8?{_entrance_query(query, SDR_ENTRANCE_CODEC)}",
            group,
        )
    return "\n".join(lines) + "\n"


def _variant(
    bandwidth: int,
    video_range: list[str],
    codecs: str,
    shape: list[str],
    uri: str,
    subtitle_group: str | None = None,
) -> list[str]:
    """One `#EXT-X-STREAM-INF` and the `main.m3u8` line beneath it, in the measured field order.

    `SUBTITLES` is **last**, after the frame rate. It is appended here rather than at either call
    site so that a variant added later cannot be the one that forgets it.
    """
    fields = [f"BANDWIDTH={bandwidth}", f"AVERAGE-BANDWIDTH={bandwidth}", *video_range]
    if codecs:
        fields.append(f'CODECS="{codecs}"')
    fields += shape
    if subtitle_group:
        fields.append(f'SUBTITLES="{subtitle_group}"')
    return ["#EXT-X-STREAM-INF:" + ",".join(fields), uri]


def _shape(
    video: StreamPlan | None, source: InspectedStream | None, frame_rate: float | None
) -> list[str]:
    fields = []
    if video is not None and video.width and video.height:
        fields.append(f"RESOLUTION={video.width}x{video.height}")
    rate = _frame_rate(video, source, frame_rate)
    if rate is not None:
        fields.append(f"FRAME-RATE={rate}")
    return fields


def _entrance_applies(video: StreamPlan, source: InspectedStream | None) -> bool:
    """Whether an SDR entrance stands beside this variant: a stream copy, of an HDR source.

    Nothing about the *client* enters this - the reference asks only what it is about to send.
    A re-encode already produces SDR and has nothing to offer an entrance beside.
    """
    return (
        source is not None
        and video.action is StreamAction.COPY
        and source.video_range is VideoRange.HDR
    )


def _entrance_query(query: str, codec: str) -> str:
    """The entrance's address: this negotiation's query with the codec named and the copy off.

    Written by rewriting the pairs rather than by re-encoding a parsed mapping, which is what the
    reference does and would round-trip differently on a value nothing here sends (a `+` for a
    space, a repeated key). Two things move, and both were measured: `VideoCodec` is replaced
    **in place**, keeping the parameter order the negotiation wrote, and `AllowVideoStreamCopy`
    is appended at the end because the negotiated URL does not carry one. The leading empty pair
    of the reference's own `?&DeviceId=` doubling does not survive - it is not a parameter, and
    the reference's re-serialisation drops it too `[probe: tools/probe_transcode_decision.py,
    Jellyfin 10.11.11, 2026-08-29]`.
    """
    pairs = [pair for pair in query.lstrip("?").split("&") if pair]
    written = {"VideoCodec": codec, "AllowVideoStreamCopy": "false"}
    rewritten = []
    for pair in pairs:
        name = pair.split("=", 1)[0]
        # Case-sensitive, as the reference's own dictionary is: a differently cased spelling is a
        # different key there, and both then reach the wire.
        value = written.pop(name, None)
        rewritten.append(pair if value is None else f"{name}={value}")
    rewritten += [f"{name}={value}" for name, value in written.items()]
    return "&".join(rewritten)


def _bandwidth(video: StreamPlan | None, audio: StreamPlan | None) -> int:
    return (video.bitrate if video is not None and video.bitrate else 0) + (
        audio.bitrate if audio is not None and audio.bitrate else 0
    )


def _video_range(video: StreamPlan | None, source: InspectedStream | None) -> list[str]:
    """`VIDEO-RANGE`, which only a copy can carry anything but `SDR` in.

    A re-encode is always labelled SDR because the reference only ever encodes SDR; a copy is
    labelled from the source's own metadata, with `HDR10` becoming `PQ` - the transfer function's
    name rather than the format's.
    """
    if video is None or source is None or source.video_range is None:
        return []
    if video.action is not StreamAction.COPY or source.video_range is VideoRange.SDR:
        return ["VIDEO-RANGE=SDR"]
    hlg = source.video_range_type is VideoRangeType.HLG
    return [f"VIDEO-RANGE={'HLG' if hlg else 'PQ'}"]


def _codecs(
    video: StreamPlan | None,
    audio: StreamPlan | None,
    source: InspectedStream | None,
    options: Mapping[str, str],
) -> str:
    parts = [
        one
        for one in (_video_codec_string(video, source, options), _audio_codec_string(audio))
        if one
    ]
    return ",".join(parts)


#: RFC 6381 section 3.3 codec strings for the audio codecs the reference names, and the empty
#: string for anything else - which is its own answer, not a gap `[source:
#: Jellyfin.Api/Helpers/HlsCodecStringHelpers.cs @ v10.11.11]`.
_AUDIO_CODEC_STRINGS: Final[dict[str, str]] = {
    "mp3": "mp4a.40.34",
    "ac3": "ac-3",
    "eac3": "ec-3",
    "flac": "fLaC",
    "alac": "alac",
    "opus": "Opus",
}

#: The four-character profile field of an `avc1.` string, by profile name, and the value an
#: unrecognised profile falls back to - constrained baseline.
_H264_PROFILES: Final[dict[str, str]] = {"high": "6400", "main": "4D40", "baseline": "42E0"}
_H264_FALLBACK: Final = "4240"

#: The level a re-encode is described at when the request named none, per codec, and the level
#: each codec is capped at for compatibility `[source:
#: MediaBrowser.Api/Helpers/DynamicHlsHelper.cs GetOutputVideoCodecLevel,
#: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:1815-1855 @ v10.11.11]`.
_DEFAULT_LEVELS: Final[dict[str, int]] = {"h264": 41, "hevc": 120, "av1": 19}
_LEVEL_CAPS: Final[dict[str, int]] = {"h264": 51, "hevc": 150, "av1": 15}


def _audio_codec_string(audio: StreamPlan | None) -> str:
    if audio is None or not audio.codec:
        return ""
    codec = audio.codec.lower()
    if codec == "aac":
        # The reference distinguishes only HE from everything else, and defaults to LC.
        return "mp4a.40.2"
    return _AUDIO_CODEC_STRINGS.get(codec, "")


def _video_codec_string(
    video: StreamPlan | None, source: InspectedStream | None, options: Mapping[str, str]
) -> str:
    if video is None or not video.codec:
        return ""
    codec = video.codec.lower()
    codec = "hevc" if codec == "h265" else codec
    copying = video.action is StreamAction.COPY
    level = _level(codec, source, options, copying=copying)
    if level is None or level == 0:
        # The reference logs an error and writes nothing here, which is what a source that is
        # neither H.26x nor AV1 gets when the profile requested no level.
        return ""
    profile = _profile(codec, source, options, copying=copying)
    if codec == "h264":
        return f"avc1.{_H264_PROFILES.get(profile, _H264_FALLBACK)}{level:02X}"
    if codec == "hevc":
        return f"hvc1.{'2.4' if profile in ('main10', 'main 10') else '1.4'}.L{level}.B0"
    if codec == "av1":
        depth = video.bit_depth if copying and video.bit_depth in (8, 10, 12) else 8
        tier = {"main": "0", "high": "1", "professional": "2"}.get(profile, "0")
        return f"av01.{tier}.{level:02d}M.{depth:02d}"
    return ""


def _level(
    codec: str, source: InspectedStream | None, options: Mapping[str, str], *, copying: bool
) -> int | None:
    """The level a variant is described at: the source's when copied, else the requested one.

    `options` is the request's own unbound query, lowercased - the reference reads
    `{codec}-level` out of the `StreamOptions` dictionary the negotiation writes there, qualified
    by the **target** codec even though `media/urls.py` writes it qualified by the source's. So a
    re-encode from hevc to h264 finds no `h264-level`, takes the default, and is described at
    level 41 - which is the measured `avc1.424029`.
    """
    if copying:
        return None if source is None else source.level
    stated = options.get(f"{codec}-level")
    level = _DEFAULT_LEVELS.get(codec)
    if stated:
        try:
            level = int(float(stated))
        except ValueError:
            return None
    if level is None:
        return None
    cap = _LEVEL_CAPS.get(codec)
    return cap if cap is not None and (level < 0 or level >= cap) else level


def _profile(
    codec: str, source: InspectedStream | None, options: Mapping[str, str], *, copying: bool
) -> str:
    if copying:
        return "" if source is None or not source.profile else source.profile.strip().lower()
    return (options.get(f"{codec}-profile") or "").split(",")[0].strip().lower()


def _frame_rate(
    video: StreamPlan | None, source: InspectedStream | None, requested: float | None
) -> str | None:
    """`FRAME-RATE`, rounded to three decimals and printed the way .NET prints a double.

    The number is the request's for a re-encode and the stream's own for a copy - the same split
    the cadence turns on - falling back to the stream's real rate when neither is stated.
    """
    copying = video is not None and video.action is StreamAction.COPY
    reference = None if source is None else source.reference_frame_rate
    chosen = reference if copying else requested
    if chosen is None:
        chosen = reference
    if chosen is None:
        return None
    rounded = round(chosen, 3)
    return str(int(rounded)) if float(rounded).is_integer() else repr(rounded)


__all__ = [
    "ANNOUNCED_WINDOW_SECONDS",
    "COPY_SEGMENT_SECONDS",
    "DEFAULT_SEGMENT_CONTAINER",
    "ENCODE_SEGMENT_SECONDS",
    "FMP4_CONTAINER",
    "KEYFRAME_EXTRACTION_EXTENSIONS",
    "SDR_ENTRANCE_CODEC",
    "SEGMENT_PREFIX",
    "SUBTITLE_GROUP",
    "TICKS_PER_SECOND",
    "UNKNOWN_LANGUAGE",
    "AnnouncedSubtitle",
    "Segment",
    "buckets_allowed",
    "cadence_milliseconds",
    "master_playlist",
    "media_playlist",
    "plan_segments",
    "requested_seconds",
    "segment_extension",
    "subtitle_playlist",
    "subtitle_uri",
    "window_duration_text",
]
