# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `AudioController`: `GET /Audio/{itemId}/stream` and its suffixed form.

The audio twins of `api/videos.py`, and deliberately a separate module for the reason plan section
3 gives: six controllers own these routes upstream, and keeping the mapping mechanical is what
lets the surface audit stay mechanical. The behaviour is `api/delivery.py`'s, shared with the
video pair, because on a `static=true` request the two families differ in nothing at all - the
label comes from the container and the container table is one table, so `stream.mp3` answers
`audio/mpeg` on either.

**One declared difference, and it is the reference's.** The audio pair takes no `maxWidth` or
`maxHeight`; the video pair takes both `[source:
Jellyfin.Api/Controllers/VideosController.cs:347-348,
Jellyfin.Api/Controllers/AudioController.cs:93-145 @ v10.11.11]`. Everything else about the two is
the same query set, which is why they share the answer.

`/Audio/{itemId}/universal` is **not** here: it is a third controller upstream and T8's task, and
it is also the one route of the three that requires a token (`api/delivery.py`).

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.5 and 3.6.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from starlette.responses import Response

from atrium.api.delivery import (
    CONTAINER_PATTERN,
    DeliveryParameters,
    audio_parameters,
    produced_response,
    static_response,
    with_container,
)
from atrium.compat.guids import WireGuid

router = APIRouter(tags=["Audio"])

UNSUFFIXED = "/Audio/{itemId}/stream"
SUFFIXED = "/Audio/{itemId}/stream.{container}"

#: The audio pair's query set, one dependency for both routes (`api/videos.py` says why).
Parameters = Annotated[DeliveryParameters, Depends(audio_parameters)]


@router.get(UNSUFFIXED)
async def get_audio_stream(
    request: Request,
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    parameters: Parameters,
    static: Annotated[bool | None, Query()] = None,
    container: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,
) -> Response:
    """`GetAudioStream` `[spec: GetAudioStream]`. No authentication dependency, measured."""
    return await _serve(request, itemId, with_container(parameters, container), static=static)


@router.get(SUFFIXED)
async def get_audio_stream_by_container(
    request: Request,
    itemId: WireGuid,  # noqa: N803
    container: Annotated[str, Path(pattern=CONTAINER_PATTERN)],
    parameters: Parameters,
    static: Annotated[bool | None, Query()] = None,
) -> Response:
    """`GetAudioStreamByContainer` `[spec: GetAudioStreamByContainer]`: the container in the path.

    `stream.wav?static=true` reaches here and answers the untouched source behind `audio/wav` -
    which is the one shape of the reference's PCM/WAV defect that is **not** broken, because
    static never starts an encoder (behaviours sections 2.20 and 3.2). **The produced form is the
    divergence**, landed at 008 T9: where the reference answers `500` - naming no codec, because
    it infers one called `wav`, and naming a `pcm_*` one without a bitrate, because of the `-ar`
    it builds from an absent field - this answers a real `RIFF….WAVE` with a `Content-Length` and
    an honoured `Range` (AC-20, behaviours section 3.2).
    """
    return await _serve(request, itemId, with_container(parameters, container), static=static)


async def _serve(
    request: Request, item_id: str, parameters: DeliveryParameters, *, static: bool | None
) -> Response:
    if not static:
        return await produced_response(request, item_id, parameters, is_video_route=False)
    return static_response(request, item_id, parameters.container, parameters.media_source_id)


__all__ = ["SUFFIXED", "UNSUFFIXED", "router"]
