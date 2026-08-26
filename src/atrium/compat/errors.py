# SPDX-License-Identifier: GPL-3.0-or-later
"""What a refusal looks like on the wire.

Measured against a live 10.11.11 rather than assumed, and the answer is that the reference has
**two** error shapes, not one.
`[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]`

**Empty**, for refusals decided before a handler runs - an unauthenticated request, a path that
matches no route. Status line, `Content-Length: 0`, and nothing else: no body, no `Content-Type`,
and **no `WWW-Authenticate`**.

**RFC 9457 problem details**, for errors a handler or the model binder produced - an item that does
not exist, a malformed identifier in a path. A JSON object with `type`, `title`, `status`, an
`errors` map for validation failures, and a `traceId`.

Only the first is implemented here, because only the first is reachable in feature 001. The second
belongs to the features that raise it; its shape is recorded in
docs/compatibility/behaviours.md section 1.11 so it does not have to be rediscovered.

**The absent `WWW-Authenticate` is worth keeping absent.** RFC 7235 says a 401 SHOULD carry one,
the reference does not, and adding `Basic` would make a browser open a credentials dialog on a
route no browser was meant to drive. Matching the reference is also the safer behaviour here.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

#: The shape Starlette expects of a handler, spelled out so the registry below type-checks against
#: what the application factory passes it.
ExceptionHandler = Callable[[Request, Any], Coroutine[Any, Any, Response]]


class UnauthenticatedError(Exception):
    """No usable credential on a route that needs one. Answered with an empty 401."""


def empty_error(status_code: int) -> Response:
    """A refusal with a status line and nothing else, as the reference sends."""
    return Response(status_code=status_code)


async def unauthenticated_handler(_request: Request, _exc: Exception) -> Response:
    return empty_error(401)


#: Registered by the application factory. Kept here so the wire shape of an error lives beside the
#: wire shape of everything else.
EXCEPTION_HANDLERS: dict[int | type[Exception], ExceptionHandler] = {
    UnauthenticatedError: unauthenticated_handler
}

__all__ = [
    "EXCEPTION_HANDLERS",
    "ExceptionHandler",
    "UnauthenticatedError",
    "empty_error",
    "unauthenticated_handler",
]
