# SPDX-License-Identifier: GPL-3.0-or-later
"""What a refusal looks like on the wire.

Measured against a live 10.11.11 rather than assumed, and the answer is that the reference has
**three** error shapes, not one.
`[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]`

**Empty**, for refusals decided before a handler runs - an unauthenticated request, a path that
matches no route, a method a path does not have. Status line, `Content-Length: 0`, and nothing
else: no body, no `Content-Type`, and **no `WWW-Authenticate`**. A `405` additionally carries
`Allow`, and it lists **every** method the path has.
`[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]`

**RFC 9457 problem details**, for errors a handler or the model binder produced - an item that does
not exist, a malformed identifier in a path. A JSON object with `type`, `title`, `status`, an
`errors` map for validation failures, and a `traceId`.

**Plain text**, for a refusal a controller decided itself. `text/plain` with no charset, and a
fixed 25-byte body reading `Error processing request.` Every refusal from
`POST /Users/AuthenticateByName` has this shape - the `400` for a broken client header, the `401`
for an unknown username, the `403` for a disabled account - so the status is the entire difference
between them. `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`

The first was implemented in feature 001, because only the first was reachable there. The second
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


class ClientAuthorizationError(Exception):
    """The client-identification header is missing or unreadable where it is required.

    A `400`, and deliberately not a `401`: a client that reads this as one tells its user that
    their password is wrong, when what actually happened is that the client sent a broken header
    (spec section 3.3).
    """


class InvalidCredentialsError(Exception):
    """The username or the password was wrong. A `401` in the controller's shape.

    Distinct from `UnauthenticatedError`, which is the *empty* `401` a route sends when no token
    reached it. Same status, different bytes, decided by which layer refused - which is exactly
    what makes behaviours section 1.11 worth having.
    """


class AccountUnavailableError(Exception):
    """The credentials were not the problem: this account cannot log in at all.

    A `403`, measured, and the difference from `401` is load-bearing. Clients re-authenticate on
    `401` and stop on `403`, so answering `401` here loops a user through a login their correct
    password can never complete.
    `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`
    """


#: What a controller's own refusal says, byte for byte. Measured, and it is the same 25 bytes
#: whatever went wrong, which is why the golden responses compare bytes and not status codes.
CONTROLLER_ERROR_BODY = b"Error processing request."

#: No `charset`, unlike the JSON responses (behaviours section 1.10). Measured.
CONTROLLER_ERROR_TYPE = "text/plain"


def empty_error(status_code: int, headers: dict[str, str] | None = None) -> Response:
    """A refusal with a status line and nothing else, as the reference sends."""
    return Response(status_code=status_code, headers=headers)


async def unauthenticated_handler(_request: Request, _exc: Exception) -> Response:
    return empty_error(401)


def controller_error(status_code: int) -> Response:
    """The third shape: a status, `text/plain`, and the reference's fixed sentence.

    The content type is set as a **header** rather than through `media_type`, which is not
    fussiness. Starlette appends `; charset=utf-8` to any `text/*` media type it is given, and the
    reference sends bare `text/plain` here - measured, and different from its JSON responses, which
    do carry the charset (behaviours sections 1.10 and 1.11). Going through `media_type` produced
    `text/plain; charset=utf-8` on every refusal from this feature, which is a difference a client
    can see, and it took a test comparing the header to notice.
    """
    return Response(
        content=CONTROLLER_ERROR_BODY,
        status_code=status_code,
        headers={"Content-Type": CONTROLLER_ERROR_TYPE},
    )


async def client_authorization_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(400)


async def invalid_credentials_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(401)


async def account_unavailable_handler(_request: Request, _exc: Exception) -> Response:
    return controller_error(403)


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
    ClientAuthorizationError: client_authorization_handler,
    InvalidCredentialsError: invalid_credentials_handler,
    AccountUnavailableError: account_unavailable_handler,
    HTTPException: routing_handler,
}

__all__ = [
    "CONTROLLER_ERROR_BODY",
    "CONTROLLER_ERROR_TYPE",
    "EXCEPTION_HANDLERS",
    "ROUTING_REFUSALS",
    "AccountUnavailableError",
    "ClientAuthorizationError",
    "ExceptionHandler",
    "InvalidCredentialsError",
    "UnauthenticatedError",
    "account_unavailable_handler",
    "client_authorization_handler",
    "controller_error",
    "empty_error",
    "invalid_credentials_handler",
    "routing_handler",
    "unauthenticated_handler",
]
