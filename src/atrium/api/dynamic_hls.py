# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `DynamicHlsController`: `master.m3u8` and `main.m3u8`, from the plan alone.

Two routes, no process. Both answer from stored data - the source's runtime, its keyframe list,
and the negotiation the query string carries - so a media playlist of thousands of segments
arrives complete, `ENDLIST`-marked and sized on a session where nothing has ever been encoded
`[probe: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`. That is AC-22's first half and the
reason its second half is reachable at all: boundaries predicted from the source are the same
boundaries next time, so a lost segment can be asked for again.

**These two routes require a token, and their three siblings do not.** The four `stream` routes
accept every mechanism and require none (behaviours section 2.10); the whole HLS controller
carries `[Authorize]` upstream, and a request with no credential answers the empty `401`
- measured in the same run as the refusals below `[source:
Jellyfin.Api/Controllers/DynamicHlsController.cs:39-41 @ v10.11.11]`, `[probe:
tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`.

**The other three refusals are the `stream` pair's, not `/universal`'s** - the third error shape
in all three cases, measured on both routes: an item nothing holds is `404`, `text/plain`, the
fixed 25 bytes; a `mediaSourceId` naming no source is the same body at `400`; and a source with
no runtime to divide is the same body at `500`, which is where the reference's own playlist
generator throws. A `main.m3u8` asked for with **no query at all** is not a refusal on either
server: it plans a copy at the copy default and answers a playlist.

The segments those playlists name are 008 T11's, which is the ordering the task list chose
deliberately: this task is arithmetic, the next one is the first process with an owner.

See specs/008-playback-negotiation-and-delivery/spec.md section 3.7 and plan section 6.4.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response

from atrium.api.delivery import (
    CONTAINER_PATTERN,
    DeliveryParameters,
    decide_delivery,
    inspection_of,
    locate,
    video_parameters,
)
from atrium.api.deps import require_user
from atrium.compat.errors import DeliveryProductionError
from atrium.compat.guids import WireGuid
from atrium.compat.query_params import ORIGINAL_QUERY_STRING
from atrium.domain.media import MediaInspection
from atrium.domain.user import User
from atrium.media import hls
from atrium.media.decision import Decision, StreamAction
from atrium.media.labels import media_type_of
from atrium.media.urls import HLS

router = APIRouter(tags=["DynamicHls"])

MASTER = "/Videos/{itemId}/master.m3u8"
MAIN = "/Videos/{itemId}/main.m3u8"

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
    """`GetMasterHlsVideoPlaylist` `[spec: GetMasterHlsVideoPlaylist]`: one variant, never a ladder.

    The reference builds more than one in three cases none of which v1 reaches - an SDR entrance
    for an HDR copy, a level 5.0 entrance for a high-level HEVC copy, and adaptive bitrate
    streaming, which it declines for a copy, for a local caller and for a request with no video
    bitrate. Every measured master carried exactly one `#EXT-X-STREAM-INF`.

    The reference also appends an `#EXT-X-IMAGE-STREAM-INF` line for each trickplay resolution it
    has generated, which the operator's server does and v1 does not: the measured 913-byte master
    is this playlist plus that one line. A server with no trickplay images has nothing to
    advertise there, which is an absence rather than a different shape (spec section 3.7).
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
    )
    return Response(content=body, media_type=PLAYLIST_MEDIA_TYPE, headers=NO_CACHE)


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


def _planned(
    request: Request,
    item_id: str,
    parameters: DeliveryParameters,
    segment_container: str | None,
    segment_length: int | None,
) -> tuple[MediaInspection, Decision, tuple[hls.Segment, ...]]:
    """Everything both routes need: what the file is, what was negotiated, and where the cuts go.

    Run on the master as well as on the variant, and deliberately: the master's `CODECS`,
    `RESOLUTION` and `BANDWIDTH` describe the negotiated output, so it has to reach the same
    ladder - and a master that answered for a source whose playlist would refuse would be
    advertising a variant nothing can serve.
    """
    found, _absolute = locate(request, item_id, parameters.media_source_id)
    inspection = inspection_of(request, found)
    decision, _container = decide_delivery(
        inspection,
        parameters,
        is_video_route=True,
        is_video=found.is_video,
        container=segment_container or hls.DEFAULT_SEGMENT_CONTAINER,
        protocol=HLS,
    )
    copying = decision.video is not None and decision.video.action is StreamAction.COPY
    milliseconds = hls.cadence_milliseconds(
        segment_length, parameters.max_framerate, copying_video=copying
    )
    keyframes = (
        inspection.video_keyframes
        if copying and inspection.video_keyframes and hls.buckets_allowed(found.relative_path)
        else None
    )
    segments = hls.plan_segments(inspection.runtime_ticks or 0, milliseconds, keyframes)
    if not segments:
        # A source with no runtime has no boundaries to state. The reference throws out of
        # `ComputeEqualLengthSegments` for exactly this and answers its own `500`, which is the
        # third error shape - the same one an unmuxable container gets one route away.
        raise DeliveryProductionError
    return inspection, decision, segments


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


__all__ = ["MAIN", "MASTER", "NO_CACHE", "PLAYLIST_MEDIA_TYPE", "router"]
