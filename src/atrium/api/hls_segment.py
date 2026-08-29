# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `HlsSegmentController`, which is where the stop route actually lives.

`DELETE /Videos/ActiveEncodings` is not in `DynamicHlsController` beside the playlists and the
segments it ends; it is on the controller whose other routes serve *static* HLS files `[source:
Jellyfin.Api/Controllers/HlsSegmentController.cs:108-117 @ v10.11.11]`. This module is that
controller, so a reader looking for a route by its upstream home finds it where upstream put it
(plan section 3).

**It must actually stop something.** Clients call it when the viewer stops, and a server that
answers `204` while leaving an encoder running accumulates them until the machine dies -
answering correctly while doing nothing is worse than not serving the route at all, because it
looks right (spec section 3.8).

**Both parameters are mandatory and one of them decides nothing.** `deviceId` and
`playSessionId` are each required at the binder - omitting either is the validation `400` naming
it, measured on all three shapes - and the reference then selects the jobs to kill by
`playSessionId` alone whenever one was given `[source:
MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:203-205 @ v10.11.11]`. Measured
rather than inferred: a `DELETE` carrying a device nothing owns still stopped the named session,
and a `DELETE` carrying a play session nothing issued left a live one running `[probe:
tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`. A server that had required
both to match would leak an encoder for every client that spells its device differently between
the negotiation and the stop.

**`204` whether or not there was anything to stop.** An unknown play session is not an error
here: the call arrives while a player is tearing down, often after the session has already gone
on its own kill timer, and a `404` would tell a client something it can do nothing about.

**And it requires a token**, unlike the four `stream` routes and like the three HLS ones -
`[Authorize]` is on this action by name where its siblings on the same controller carry a
comment explaining why they cannot have it `[source:
Jellyfin.Api/Controllers/HlsSegmentController.cs:109 @ v10.11.11]`. The refusal is the empty
`401` (behaviours section 2.10).

See specs/008-playback-negotiation-and-delivery/spec.md section 3.8, and plan section 6.7.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response

from atrium.api.deps import require_user
from atrium.api.dynamic_hls import transcode_manager
from atrium.domain.user import User

router = APIRouter(tags=["HlsSegment"])

ACTIVE_ENCODINGS = "/Videos/ActiveEncodings"


@router.delete(ACTIVE_ENCODINGS, status_code=204)
async def stop_encoding_process(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    deviceId: Annotated[str, Query()],  # noqa: N803 - the reference's spellings, throughout
    playSessionId: Annotated[str, Query()],  # noqa: N803
) -> Response:
    """`StopEncodingProcess` `[spec: StopEncodingProcess]`: stop one session's work.

    `deviceId` is bound because the reference binds it, and read by nothing: the manager keys on
    the play session, which is what the reference kills by. Declaring it is not decoration - a
    request omitting it is a `400` naming it, and a route that took only what it uses would
    answer `204` to a call the reference refuses.
    """
    await transcode_manager(request).stop(playSessionId)
    return Response(status_code=204)


__all__ = ["ACTIVE_ENCODINGS", "router"]
