# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `AudioController`: `GET /Audio/{itemId}/stream` and its suffixed form.

The audio twins of `api/videos.py`, and deliberately a separate module for the reason plan section
3 gives: six controllers own these routes upstream, and keeping the mapping mechanical is what
lets the surface audit stay mechanical. The behaviour is `api/delivery.py`'s, shared with the
video pair, because on a `static=true` request the two families differ in nothing at all - the
label comes from the container and the container table is one table, so `stream.mp3` answers
`audio/mpeg` on either.

`/Audio/{itemId}/universal` is **not** here: it is a third controller upstream and T8's task, and
it is also the one route of the three that requires a token (`api/delivery.py`).

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.5 and 3.6.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from starlette.responses import Response

from atrium.api.delivery import CONTAINER_PATTERN, static_response
from atrium.compat.errors import DeliveryNotFoundError
from atrium.compat.guids import WireGuid

router = APIRouter(tags=["Audio"])

UNSUFFIXED = "/Audio/{itemId}/stream"
SUFFIXED = "/Audio/{itemId}/stream.{container}"


@router.get(UNSUFFIXED)
async def get_audio_stream(
    request: Request,
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    static: Annotated[bool | None, Query()] = None,
    container: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,
) -> Response:
    """`GetAudioStream` `[spec: GetAudioStream]`. No authentication dependency, measured."""
    return _serve(request, itemId, container, static=static)


@router.get(SUFFIXED)
async def get_audio_stream_by_container(
    request: Request,
    itemId: WireGuid,  # noqa: N803
    container: Annotated[str, Path(pattern=CONTAINER_PATTERN)],
    static: Annotated[bool | None, Query()] = None,
) -> Response:
    """`GetAudioStreamByContainer` `[spec: GetAudioStreamByContainer]`: the container in the path.

    `stream.wav?static=true` reaches here and answers the untouched source behind `audio/wav` -
    which is the one shape of the reference's PCM/WAV defect that is **not** broken, because
    static never starts an encoder (behaviours sections 2.20 and 3.2; the produced form is T9's).
    """
    return _serve(request, itemId, container, static=static)


def _serve(
    request: Request, item_id: str, container: str | None, *, static: bool | None
) -> Response:
    if not static:
        # ⚠️ **Temporary, and only until T7** - see the identical branch in `api/videos.py`.
        raise DeliveryNotFoundError
    return static_response(request, item_id, container)


__all__ = ["SUFFIXED", "UNSUFFIXED", "router"]
