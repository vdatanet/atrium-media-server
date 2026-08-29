# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `VideosController`: `GET /Videos/{itemId}/stream` and its suffixed form.

Two routes, one behaviour, and the suffix is not part of it. `stream.{container}` names the
container a client would like; on a `static=true` request that decides the `Content-Type` and
nothing else, and on any other request it is T7's problem. Everything both routes do lives in
`api/delivery.py`, which is where the range negotiation, the label and the header set are.

**This module claims only the static half.** A request without `static=true` is a remux or a
re-encode, and feature 008 lands those at T7 - until then such a request is refused rather than
answered wrongly, which is safe precisely because `"008"` is not in `IMPLEMENTED_FEATURES` and no
conformance is claimed for this route yet.

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.5 and 3.7.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from starlette.responses import Response

from atrium.api.delivery import CONTAINER_PATTERN, static_response
from atrium.compat.errors import DeliveryNotFoundError
from atrium.compat.guids import WireGuid

router = APIRouter(tags=["Videos"])

UNSUFFIXED = "/Videos/{itemId}/stream"
SUFFIXED = "/Videos/{itemId}/stream.{container}"


@router.get(UNSUFFIXED)
async def get_video_stream(
    request: Request,
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
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
    return _serve(request, itemId, container, static=static)


@router.get(SUFFIXED)
async def get_video_stream_by_container(
    request: Request,
    itemId: WireGuid,  # noqa: N803
    container: Annotated[str, Path(pattern=CONTAINER_PATTERN)],
    static: Annotated[bool | None, Query()] = None,
) -> Response:
    """`GetVideoStreamByContainer` `[spec: GetVideoStreamByContainer]`: the container in the path.

    The same answer as the route above with `?container=` set, byte for byte - which is what makes
    a mismatched suffix a label and not a request to convert anything.
    """
    return _serve(request, itemId, container, static=static)


def _serve(
    request: Request, item_id: str, container: str | None, *, static: bool | None
) -> Response:
    if not static:
        # ⚠️ **Temporary, and only until T7.** A non-static request is a remux or a re-encode and
        # this task has no process behind it, so the route refuses in the shape it is measured to
        # refuse in rather than serving the source bytes behind a label that promises a
        # conversion. T7 replaces this branch with the real answer.
        raise DeliveryNotFoundError
    return static_response(request, item_id, container)


__all__ = ["SUFFIXED", "UNSUFFIXED", "router"]
