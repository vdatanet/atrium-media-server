# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `VideosController`: `GET /Videos/{itemId}/stream` and its suffixed form.

Two routes, one behaviour, and the suffix is not part of it. `stream.{container}` names the
container a client would like; on a `static=true` request that decides the `Content-Type` and
nothing else, and on any other request it decides what the output is muxed into. Everything both
routes do lives in `api/delivery.py`, which is where the range negotiation, the label, the header
set and the produced half are.

**The two halves answer differently on purpose.** `static=true` is the original bytes, sized and
range-capable; anything else is produced - a remux, served sized because Atrium writes it to
scratch first (the divergence of behaviours section 3.3, AC-15), or a re-encode, chunked with
`Accept-Ranges: none` because its length is not known until the last frame (AC-17).

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.5 and 3.7.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from starlette.responses import Response

from atrium.api.delivery import (
    CONTAINER_PATTERN,
    DeliveryParameters,
    produced_response,
    static_response,
    video_parameters,
    with_container,
)
from atrium.compat.guids import WireGuid

router = APIRouter(tags=["Videos"])

UNSUFFIXED = "/Videos/{itemId}/stream"
SUFFIXED = "/Videos/{itemId}/stream.{container}"

#: The query set both routes bind, declared once in `api/delivery.py` and reached as a dependency
#: - which `compat/query_params.py` walks into when it builds the case-insensitive spelling table,
#: so a parameter declared here canonicalises exactly like one in a handler's own signature.
Parameters = Annotated[DeliveryParameters, Depends(video_parameters)]


@router.get(UNSUFFIXED)
async def get_video_stream(
    request: Request,
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    parameters: Parameters,
    static: Annotated[bool | None, Query()] = None,
    container: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,
) -> Response:
    """`GetVideoStream` `[spec: GetVideoStream]`.

    **No authentication dependency**, which is the measured rule and not an omission: this route
    answers `200` to a request carrying no token at all, and the identical `200` to one carrying a
    token nothing issued (`api/delivery.py`, behaviours section 2.10).

    `container` is declared here as well as in the path, because the reference declares it on both
    and honours it on both: `?container=mkv` on this route answers the same
    `Content-Type: video/x-matroska` the suffixed form does, over the same original bytes
    `[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    return await _serve(request, itemId, with_container(parameters, container), static=static)


@router.get(SUFFIXED)
async def get_video_stream_by_container(
    request: Request,
    itemId: WireGuid,  # noqa: N803
    container: Annotated[str, Path(pattern=CONTAINER_PATTERN)],
    parameters: Parameters,
    static: Annotated[bool | None, Query()] = None,
) -> Response:
    """`GetVideoStreamByContainer` `[spec: GetVideoStreamByContainer]`: the container in the path.

    On a static request this is the same answer as the route above with `?container=` set, byte
    for byte - which is what makes a mismatched suffix a label and not a request to convert
    anything. On a produced one it is what the output is muxed into, and a container no muxer
    writes is the measured `500` rather than a conversion nobody can perform.
    """
    return await _serve(request, itemId, with_container(parameters, container), static=static)


async def _serve(
    request: Request, item_id: str, parameters: DeliveryParameters, *, static: bool | None
) -> Response:
    if not static:
        return await produced_response(request, item_id, parameters, is_video_route=True)
    return static_response(request, item_id, parameters.container, parameters.media_source_id)


__all__ = ["SUFFIXED", "UNSUFFIXED", "router"]
