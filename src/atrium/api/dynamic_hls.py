# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `DynamicHlsController`: two playlists from the plan alone, and the segments.

The playlists answer from stored data - the source's runtime, its keyframe list, and the
negotiation the query string carries - so a media playlist of thousands of segments arrives
complete, `ENDLIST`-marked and sized on a session where nothing has ever been encoded `[probe:
tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`. That is AC-22's first half and the reason its
second half is reachable at all: boundaries predicted from the source are the same boundaries next
time, so a lost segment can be asked for again.

**The segment route is here and not in `api/hls_segment.py`**, whose name says otherwise: the
reference's `HlsSegmentController` owns `DELETE /Videos/ActiveEncodings` and the *static* segment
files, while `hls1/{playlistId}/{segmentId}.{container}` is this controller's `[source:
Jellyfin.Api/Controllers/DynamicHlsController.cs:1102-1106 @ v10.11.11]`. It is the one route in
this feature that produces something and then serves it from disk, and everything about running
the encoder is `media/sessions.py`'s.

**Two of its three path parameters decide nothing**, both measured rather than read off the
signature `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`:

* `playlistId` is unused - `hls1/banana/0.ts` answers segment 0, and the reference suppresses its
  own unused-parameter warning on it by name;
* the path's `{container}` is not what the segment is muxed into. `0.mp4` asked for while
  `SegmentContainer=ts` answers MPEG-TS bytes labelled `video/mp2t`. The extension has to *be* a
  container spelling for the route to match, and that is the whole of its effect.

**These three routes require a token, and their four `stream` siblings do not** (behaviours
section 2.10); the whole HLS controller carries `[Authorize]` upstream, and a request with no
credential answers the empty `401` `[source:
Jellyfin.Api/Controllers/DynamicHlsController.cs:39-41 @ v10.11.11]`.

**Their other refusals are the `stream` pair's, not `/universal`'s** - the third error shape,
measured on all three routes: an item nothing holds is `404`, `text/plain`, the fixed 25 bytes; a
`mediaSourceId` naming no source is the same body at `400`; a source with no runtime to divide is
the same body at `500`; and, on the segment route alone, so is a request carrying
`startTimeTicks`, which the reference refuses before it looks at anything else. The one refusal
that is *not* that shape is the framework's own: `runtimeTicks` and `actualSegmentLengthTicks` are
required, so a segment URI stripped of its query answers problem details where a `main.m3u8`
stripped of its query answers a playlist.

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.4, 3.7 and 3.8, and plan
sections 6.4 and 6.7.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from starlette.responses import Response

from atrium.api.delivery import (
    CONTAINER_PATTERN,
    DeliveryParameters,
    decide_delivery,
    inspection_of,
    locate,
    policy_of,
    production_ledger,
    ranged_file,
    refuse_forbidden_production,
    video_parameters,
)
from atrium.api.deps import get_paths, require_user
from atrium.compat.auth import extract_token
from atrium.compat.errors import (
    DeliveryProductionError,
    DeliverySegmentRequestError,
)
from atrium.compat.guids import WireGuid
from atrium.compat.query_params import ORIGINAL_QUERY_STRING
from atrium.domain.media import DeliveredFile, MediaInspection
from atrium.domain.user import User
from atrium.library.naming.external import LANGUAGE_TOKENS
from atrium.media import ffmpeg, hls, names
from atrium.media.decision import (
    Decision,
    StreamAction,
    StreamProtocol,
    SubtitleMethod,
    method_named,
)
from atrium.media.info import is_text_subtitle
from atrium.media.labels import DEFAULT_MEDIA_TYPE, media_type_of
from atrium.media.sessions import SegmentPlan, SessionKey, TranscodeManager

router = APIRouter(tags=["DynamicHls"])

MASTER = "/Videos/{itemId}/master.m3u8"
MAIN = "/Videos/{itemId}/main.m3u8"
SEGMENT = "/Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}"

#: What both playlists are labelled, from the one table `media/labels.py` already holds.
PLAYLIST_MEDIA_TYPE = media_type_of("m3u8")

#: The master carries it and the media playlist does not, measured on both in one run. Set by the
#: reference before it knows whether it will answer anything at all, which is why it is on the
#: `HEAD` answer too `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:136 @ v10.11.11]`.
NO_CACHE = {"Expires": "0"}

Parameters = Annotated[DeliveryParameters, Depends(video_parameters)]

#: The two HLS-only parameters the negotiated URL carries beside the shared delivery set
#: (`media/urls.py`): what the segments are muxed into, and how long the client asked them to be.
SegmentContainer = Annotated[str | None, Query(pattern=CONTAINER_PATTERN)]
SegmentLength = Annotated[int | None, Query()]


@router.get(MASTER)
async def get_master_hls_video_playlist(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    parameters: Parameters,
    segmentContainer: SegmentContainer = None,  # noqa: N803
    segmentLength: SegmentLength = None,  # noqa: N803
) -> Response:
    """`GetMasterHlsVideoPlaylist` `[spec: GetMasterHlsVideoPlaylist]`: one variant, and an SDR
    entrance beside a high-dynamic-range stream copy.

    **This route was documented as answering one variant always, from a measurement that could
    not reach the branch it was answering about**: the probe took the library's first film, which
    was standard range, so the entrance never fired and its absence was recorded as the shape of
    the route. Measured against an HDR source the master carries a second `#EXT-X-STREAM-INF` at
    the copy's own `BANDWIDTH`, so a client selects on colour rather than on rate
    `[probe: tools/probe_transcode_decision.py, Jellyfin 10.11.11, 2026-08-29]`.

    The other two multi-variant cases stay out of reach: a level 5.0 entrance for a high-level
    HEVC copy, and adaptive bitrate streaming, which the reference declines for a copy, for a
    local caller and for a request with no video bitrate.

    The reference also appends an `#EXT-X-IMAGE-STREAM-INF` line for each trickplay resolution it
    has generated, which the operator's server does and v1 does not: the measured 913-byte master
    is this playlist plus that one line. A server with no trickplay images has nothing to
    advertise there, which is an absence rather than a different shape (spec section 3.7).

    **This is also the route 011's whole subtitle announcement hangs off**, and the lever is
    `SubtitleMethod` in the query and nothing else - see `_announced`.
    """
    inspection, decision, _segments = _planned(
        request, itemId, parameters, segmentContainer, segmentLength
    )
    body = hls.master_playlist(
        query=_forwarded(request),
        video=decision.video,
        audio=decision.audio,
        source_video=inspection.video,
        frame_rate=parameters.max_framerate,
        options=request.query_params,
        subtitles=_announced(request, inspection, parameters),
    )
    return Response(content=body, media_type=PLAYLIST_MEDIA_TYPE, headers=NO_CACHE)


def _announced(
    request: Request, inspection: MediaInspection, parameters: DeliveryParameters
) -> tuple[hls.AnnouncedSubtitle, ...]:
    """The `#EXT-X-MEDIA` entries this request earns: one per **text** subtitle stream, or none.

    **One lever, and it is the delivery method alone.** `EnableSubtitlesInManifest` is the other
    half of the reference's own condition and is unreachable on this route, which does not bind it
    - so the reference's own negotiation writes a parameter into an address that the route it
    addresses cannot read `[probe: tools/probe_subtitle_manifest.py, Jellyfin 10.11.11,
    2026-08-29]`.

    **And the index is not part of the lever, which both documents had the other way round.**
    Spec section 3.4 said the announcement needs the manifest method *beside a stream index*;
    measured, `SubtitleMethod=Hls` alone announces every text track of the source, and so does one
    naming `-1` or a stream that does not exist. What the index decides is which entry carries
    `DEFAULT=YES` - and nothing at all when it matches no announced stream `[probe: manual
    requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`, `[source:
    Jellyfin.Api/Helpers/DynamicHlsHelper.cs:192-210, 603-612 @ v10.11.11]`. That matters to the
    client this feature exists for: it rewrites the address it was handed rather than
    re-negotiating, and an implementation that required both would have announced nothing to a
    client that sent only one of them.

    **The filter is on the stream kind and not on the selection**, which is what makes AC-7 a
    property rather than a branch: selecting an *image* track still announces every text track,
    with `DEFAULT=NO` on all of them, because no announced stream matches the selected index.

    The token is `compat/auth.extract_token`'s and not `request.state`'s, which holds only the
    digest of it - and a player following a `URI` out of a manifest sends no headers, so the
    address has to carry the caller's own credential (`media/hls.py`'s `subtitle_uri`).
    """
    if method_named(parameters.subtitle_method) is not SubtitleMethod.HLS:
        return ()
    token = extract_token(request)
    return tuple(
        hls.AnnouncedSubtitle(
            index=stream.index,
            name=names.display_title(stream, LANGUAGE_TOKENS),
            language=stream.language or hls.UNKNOWN_LANGUAGE,
            is_forced=stream.is_forced,
            is_default=stream.index == parameters.subtitle_stream_index,
            uri=hls.subtitle_uri(parameters.media_source_id, stream.index, token),
        )
        for stream in inspection.streams
        if is_text_subtitle(stream)
    )


@router.get(MAIN)
async def get_variant_hls_video_playlist(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803
    parameters: Parameters,
    segmentContainer: SegmentContainer = None,  # noqa: N803
    segmentLength: SegmentLength = None,  # noqa: N803
) -> Response:
    """`GetVariantHlsVideoPlaylist` `[spec: GetVariantHlsVideoPlaylist]`: the whole segment list.

    Complete on the first request and identical on the second, because every boundary is computed
    from the source rather than read off produced output (AC-22). No `Expires` header here, unlike
    the master - measured, and reproduced rather than tidied.
    """
    _inspection, _decision, segments = _planned(
        request, itemId, parameters, segmentContainer, segmentLength
    )
    body = hls.media_playlist(segments, query=_forwarded(request), container=segmentContainer)
    return Response(content=body, media_type=PLAYLIST_MEDIA_TYPE)


@router.get(SEGMENT)
async def get_hls_video_segment(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803
    playlistId: str,  # noqa: N803
    segmentId: int,  # noqa: N803
    container: Annotated[str, Path(pattern=CONTAINER_PATTERN)],
    parameters: Parameters,
    runtimeTicks: Annotated[int, Query()],  # noqa: N803
    actualSegmentLengthTicks: Annotated[int, Query()],  # noqa: N803
    deviceId: Annotated[str | None, Query()] = None,  # noqa: N803
    playSessionId: Annotated[str | None, Query()] = None,  # noqa: N803
    segmentContainer: SegmentContainer = None,  # noqa: N803
    segmentLength: SegmentLength = None,  # noqa: N803
) -> Response:
    """`GetHlsVideoSegment` `[spec: GetHlsVideoSegment]`: one segment, produced then served.

    **`runtimeTicks` is where production starts; `segmentId` is only what the file is called.**
    Reading the index as the position would work for every URI a playlist writes and for nothing
    else, and the reference is measurably the other way round: segment 0's own path asked for at
    the middle of a film answers the middle of the film (`media/sessions.py`).

    `runtimeTicks` and `actualSegmentLengthTicks` are **required**, which is the one refusal on
    this route that is not the third error shape: a segment URI stripped of its query answers the
    framework's problem details, where the same treatment of `main.m3u8` answers a playlist.
    Together they are the **download position** both operator knobs measure against: their sum is
    the end of the furthest segment this client has asked for, which is what the throttle stays
    ahead of and what segment deletion falls behind (008 T13, `media/sessions.py`).

    **This is the one delivery route with a user and a re-encode**, so it is where the delivery
    half of AC-31 lands: a plan that re-encodes a stream the caller's policy forbids is refused
    rather than force-copied into an output the negotiated profile rejects.

    `playlistId` decides nothing, in the reference and here: it is in the path because the URI
    shape has a slot for it, and a playlist nobody named still answers the segment.
    """
    if parameters.start_time_ticks:
        # Before the lookup, because that is where the reference throws it: a segment states its
        # own position and a second one has no meaning. An unknown item asked for with a start
        # position is therefore this refusal, not the `404`.
        raise DeliverySegmentRequestError
    negotiated = _negotiate(request, itemId, parameters, segmentContainer, segmentLength)
    refuse_forbidden_production(
        negotiated.decision, policy_of(caller), is_video=negotiated.found.is_video
    )
    manager = transcode_manager(request)
    session = manager.obtain(
        SessionKey(
            device_id=deviceId or "",
            play_session_id=playSessionId or "",
            media_path=negotiated.absolute,
        )
    )
    try:
        produced = await manager.segment(
            session,
            SegmentPlan(
                path=negotiated.absolute,
                source=negotiated.inspection,
                decision=negotiated.decision,
                container=negotiated.container,
                cadence_ticks=negotiated.milliseconds * (hls.TICKS_PER_SECOND // 1000),
                segment_seconds=negotiated.seconds,
            ),
            index=segmentId,
            start_ticks=runtimeTicks,
            length_ticks=actualSegmentLengthTicks,
        )
    except ffmpeg.ProductionError as error:
        # An encoder that never started and one that stopped short of the requested segment are
        # one answer, the same `500` the progressive routes give a command that cannot be built.
        raise DeliveryProductionError from error
    return ranged_file(
        request,
        produced,
        media_type=media_type_of(negotiated.container) or DEFAULT_MEDIA_TYPE,
    )


@dataclass(frozen=True, slots=True)
class _Negotiation:
    """The lookup and the ladder, run once for whichever of the three routes asked."""

    found: DeliveredFile
    absolute: str
    inspection: MediaInspection
    decision: Decision
    container: str
    seconds: int
    milliseconds: int
    copying: bool


def _negotiate(
    request: Request,
    item_id: str,
    parameters: DeliveryParameters,
    segment_container: str | None,
    segment_length: int | None,
) -> _Negotiation:
    """What the file is, what was negotiated about it, and on what grid.

    Run on the master as well as on the variant, and deliberately: the master's `CODECS`,
    `RESOLUTION` and `BANDWIDTH` describe the negotiated output, so it has to reach the same
    ladder - and a master that answered for a source whose playlist would refuse would be
    advertising a variant nothing can serve. The segment route reaches it for a stronger reason:
    a production planned from anything but this is a production whose boundaries the playlist
    does not describe.
    """
    found, absolute = locate(request, item_id, parameters.media_source_id)
    inspection = inspection_of(request, found)
    container = segment_container or hls.DEFAULT_SEGMENT_CONTAINER
    decision, _container = decide_delivery(
        inspection,
        parameters,
        is_video_route=True,
        is_video=found.is_video,
        container=container,
        protocol=StreamProtocol.HLS,
    )
    copying = decision.video is not None and decision.video.action is StreamAction.COPY
    return _Negotiation(
        found=found,
        absolute=absolute,
        inspection=inspection,
        decision=decision,
        container=container,
        seconds=hls.requested_seconds(segment_length, copying_video=copying),
        milliseconds=hls.cadence_milliseconds(
            segment_length, parameters.max_framerate, copying_video=copying
        ),
        copying=copying,
    )


def _planned(
    request: Request,
    item_id: str,
    parameters: DeliveryParameters,
    segment_container: str | None,
    segment_length: int | None,
) -> tuple[MediaInspection, Decision, tuple[hls.Segment, ...]]:
    """The negotiation plus the cuts, which is what the two playlist routes render.

    **The caller's policy reaches neither of them**, and that is a decision rather than an
    omission: a playlist produces nothing, the reference refuses neither playlist nor segment,
    and a server that refused a playlist would differ from it on a request that costs nothing
    either way. The refusal belongs where the re-encode would have happened, which is the
    segment route.
    """
    negotiated = _negotiate(request, item_id, parameters, segment_container, segment_length)
    keyframes = (
        negotiated.inspection.video_keyframes
        if negotiated.copying
        and negotiated.inspection.video_keyframes
        and hls.buckets_allowed(negotiated.found.relative_path)
        else None
    )
    segments = hls.plan_segments(
        negotiated.inspection.runtime_ticks or 0, negotiated.milliseconds, keyframes
    )
    if not segments:
        # A source with no runtime has no boundaries to state. The reference throws out of
        # `ComputeEqualLengthSegments` for exactly this and answers its own `500`, which is the
        # third error shape - the same one an unmuxable container gets one route away.
        raise DeliveryProductionError
    return negotiated.inspection, negotiated.decision, segments


def transcode_manager(request: Request) -> TranscodeManager:
    """The application's manager, built by `server.py` beside the ledger it starts through.

    Lazily created for the same reason `production_ledger` is: a test that assembles a bare
    application still has one, and two applications in one process never share a session.
    """
    existing: TranscodeManager | None = getattr(request.app.state, "transcodes", None)
    if existing is None:
        existing = TranscodeManager(get_paths(request).transcodes, production_ledger(request))
        request.app.state.transcodes = existing
    return existing


def _forwarded(request: Request) -> str:
    """The request's whole query string **as it arrived**, leading `?` included, or empty.

    Forwarded verbatim into the variant URI and every segment URI, which is what carries the
    negotiation across the two hops - and why the reference's own `?&DeviceId=` doubling survives
    into `main.m3u8?&DeviceId=`. Rebuilding it from the bound parameters would drop everything
    these routes do not declare, including the `{codec}-level` triplet and the API key.

    Read from the scope key `compat/query_params.py` stashes rather than from the request, because
    by the time a handler runs the case-insensitive rewrite has already replaced every recognised
    key with **this** server's declared spelling - so `MaxFramerate` would reach a client's
    playlist as `maxFramerate`. Both work coming back; only one of them is what was sent.
    """
    raw: bytes = request.scope.get(ORIGINAL_QUERY_STRING) or request.url.query.encode()
    return f"?{raw.decode('utf-8', 'replace')}" if raw else ""


__all__ = [
    "MAIN",
    "MASTER",
    "NO_CACHE",
    "PLAYLIST_MEDIA_TYPE",
    "SEGMENT",
    "router",
    "transcode_manager",
]
