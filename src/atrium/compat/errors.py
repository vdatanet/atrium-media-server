# SPDX-License-Identifier: GPL-3.0-or-later
"""What a refusal looks like on the wire.

Measured against a live 10.11.11 rather than assumed, and the answer is that the reference has
**two** error shapes, not one.
`[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]`

**Empty**, for refusals decided before a handler runs - an unauthenticated request, a path that
matches no route, a method a path does not have. Status line, `Content-Length: 0`, and nothing
else: no body, no `Content-Type`, and **no `WWW-Authenticate`**. A `405` additionally carries
`Allow`, and it lists **every** method the path has.
`[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]`

**RFC 9457 problem details**, for errors a handler or the model binder produced - an item that does
not exist, a malformed identifier in a path. A JSON object with `type`, `title`, `status`, an
`errors` map for validation failures, and a `traceId`.

Only the first is implemented here, because only the first is reachable in feature 001. The second
belongs to the features that raise it; its shape is recorded in
docs/compatibility/behaviours.md section 1.11 so it does not have to be rediscovered.

**Both of the framework's own refusals had to be replaced, and one was already documented as
done.** Starlette raises an `HTTPException` for an unmatched path and for a wrong method, and
FastAPI answers those with `{"detail": "Not Found"}` - the exact shape behaviours section 1.11
warns is neither of the two. Nothing had noticed, because until feature 001 had routes there was
no path to get wrong. Writing the module docstring is not the same as registering the handler.

**The absent `WWW-Authenticate` is worth keeping absent.** RFC 7235 says a 401 SHOULD carry one,
the reference does not, and adding `Basic` would make a browser open a credentials dialog on a
route no browser was meant to drive. Matching the reference is also the safer behaviour here.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

#: The shape Starlette expects of a handler, spelled out so the registry below type-checks against
#: what the application factory passes it.
ExceptionHandler = Callable[[Request, Any], Coroutine[Any, Any, Response]]

#: The refusals the framework decides on its own, before any handler of ours runs.
ROUTING_REFUSALS = frozenset({404, 405})


class UnauthenticatedError(Exception):
    """No usable credential on a route that needs one. Answered with an empty 401."""


def empty_error(status_code: int, headers: dict[str, str] | None = None) -> Response:
    """A refusal with a status line and nothing else, as the reference sends."""
    return Response(status_code=status_code, headers=headers)


async def unauthenticated_handler(_request: Request, _exc: Exception) -> Response:
    return empty_error(401)


async def routing_handler(request: Request, exc: Exception) -> Response:
    """Answer an unmatched path or an unavailable method as the reference does.

    `Allow` is rebuilt from the route table rather than taken from the exception, because
    Starlette fills it from the first route whose path matched and a path can be several routes -
    `/System/Ping` is two. See `atrium.compat.routing.RouteTable.methods_for`.
    """
    if not isinstance(exc, HTTPException) or exc.status_code not in ROUTING_REFUSALS:
        # Not a routing refusal: a handler raised this deliberately, and its shape is problem
        # details rather than emptiness. Nothing in feature 001 raises one, so this defers to the
        # framework instead of inventing a shape the feature that needs it will have to measure.
        return await http_exception_handler(request, exc)  # type: ignore[arg-type]

    headers = None
    if exc.status_code == 405:
        allowed = request.app.state.routes.methods_for(request.url.path)
        # Sorted, so two servers built from the same routes advertise the same string
        # (Principle VII). The one measured case - GET, POST - is alphabetical either way, so
        # the reference's own ordering rule is unknown rather than reproduced.
        headers = {"Allow": ", ".join(sorted(allowed))} if allowed else None
    return empty_error(exc.status_code, headers)


#: Registered by the application factory. Kept here so the wire shape of an error lives beside the
#: wire shape of everything else.
EXCEPTION_HANDLERS: dict[int | type[Exception], ExceptionHandler] = {
    UnauthenticatedError: unauthenticated_handler,
    HTTPException: routing_handler,
}

__all__ = [
    "EXCEPTION_HANDLERS",
    "ROUTING_REFUSALS",
    "ExceptionHandler",
    "UnauthenticatedError",
    "empty_error",
    "routing_handler",
    "unauthenticated_handler",
]
