# SPDX-License-Identifier: GPL-3.0-or-later
"""What a refusal looks like on the wire.

Measured against a live 10.11.11 rather than assumed, and the answer is that the reference has
**four** error shapes, not one.
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

**A JSON-encoded bare string**, for a controller that refused *with a message*. The image route's
own `404`: `"<item name> does not have an image of type <Type>"`, quoted, in
`application/json; charset=utf-8`. One route, two `404` bodies - an item that does not exist gets
problem details, an item that exists and lacks the image gets this - split by which of the two
lookups failed. `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`

The first was implemented in feature 001, because only the first was reachable there. The second
belongs to the features that raise it; its shape is recorded in
docs/compatibility/behaviours.md section 1.11 so it does not have to be rediscovered. The fourth
arrived with feature 006 and lives here rather than in `api/images.py` for the reason the whole
module exists: a shape settled once is a shape no later route can get subtly wrong.

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

import secrets
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from atrium.compat.responses import AtriumJSONResponse

#: The shape Starlette expects of a handler, spelled out so the registry below type-checks against
#: what the application factory passes it.
ExceptionHandler = Callable[[Request, Any], Coroutine[Any, Any, Response]]

#: The refusals the framework decides on its own, before any handler of ours runs.
ROUTING_REFUSALS = frozenset({404, 405})


class UnauthenticatedError(Exception):
    """No usable credential on a route that needs one. Answered with an empty 401."""


class ForbiddenError(Exception):
    """A usable credential, and the account may not do this. Answered with an empty 403.

    ⚠️ **The shape is not measured.** The empty `401` above was measured for an unauthenticated
    route; no refusal of this kind could be issued against the reference from here, because the
    account available to measure with is an administrator and an administrator lacks no
    permission. It is emitted in the same shape as the `401` beside it, on the argument that it is
    decided in the same place - before any route body runs - and 002 spec section 7 (OQ-5) carries
    it as an open question rather than as a claim.
    """


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


#: RFC 9457 `type` URIs, as the reference spells them - `tools.ietf.org`, not `iana.org`, and
#: pointing at RFC 9110's status-code sections. Measured.
#: `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`
PROBLEM_TYPE_BAD_REQUEST = "https://tools.ietf.org/html/rfc9110#section-15.5.1"
PROBLEM_TYPE_NOT_FOUND = "https://tools.ietf.org/html/rfc9110#section-15.5.5"

#: The reference's own wording, byte for byte.
VALIDATION_TITLE = "One or more validation errors occurred."
NOT_FOUND_TITLE = "Not Found"


class NotFoundError(Exception):
    """A handler looked and there was nothing there. Answered with a problem-details `404`.

    Not the same refusal as an unmatched path, which is the **empty** `404` of section 1.11's
    first table. Same status, different bytes, decided by which layer refused - and 005 AC-8
    requires an unknown id and an invisible one to be byte-identical, so both go through here.
    """


class ItemNotFoundError(NotFoundError):
    """The item a route was asked about does not exist, or has been removed.

    *(Named `ItemNotFound` by plan section 5. The `Error` suffix is this project's lint rule and
    every exception beside it obeys one, `NotFoundError` included, so the contract's spelling is
    amended rather than exempted.)*

    The same wire shape as `NotFoundError`, and a separate name on purpose: the image route has
    **two** `404`s, and plan section 7 asks for the split to be verified by exception type rather
    than by reading a body. A service that raises one of these has decided *which* lookup failed,
    and that decision is the whole difference between the two bodies below.

    Measured: a well-formed identifier nothing owns answers problem details on
    `/Items/{itemId}/Images/{imageType}`, byte-identical to the same refusal on `/Items/{itemId}`
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """


class ImageNotFoundError(Exception):
    """The item exists and has no image of that type. Answered with the fourth shape.

    *(Plan section 5 spells it `ImageNotFound`; see the note on `ItemNotFoundError` above.)*

    Carries the item's **display name**, which is what the measured message says and therefore
    what travels to any caller holding an id - the image route requires no token (behaviours
    section 2.10), so the name is disclosed to whoever can name the item. That is the
    id-as-capability consequence, recorded in behaviours sections 1.11 and 2.10 and named here so
    it stays a decision rather than becoming an accident.

    The reference raises it for every way an image can be absent: no row of that type, an
    `imageIndex` past the last backdrop, a chapter with no thumbnail, and a vocabulary member no
    item can hold. The message names the **type**, never the index - `Backdrop/99` answers
    `"… does not have an image of type Backdrop"`
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """

    def __init__(self, item_name: str, image_type: str) -> None:
        super().__init__(image_absent_message(item_name, image_type))
        self.item_name = item_name
        self.image_type = image_type


#: The reference's wording, byte for byte, with the two values it interpolates. Measured on four
#: refusals of three kinds - an absent type, an out-of-range index and a chapter with no
#: thumbnail - which all produce this one sentence.
#: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`
IMAGE_ABSENT_TEMPLATE = "{name} does not have an image of type {image_type}"


def image_absent_message(item_name: str, image_type: str) -> str:
    return IMAGE_ABSENT_TEMPLATE.format(name=item_name, image_type=image_type)


def trace_id() -> str:
    """A W3C trace-context identifier, in the shape the reference's `traceId` carries.

    `00-<32 hex>-<16 hex>-00`: version, trace id, parent id, flags. Per request by definition, so
    behaviours section 1.11 compares it by shape rather than by value and the goldens mask it.
    """
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-00"


def problem_details(
    status_code: int,
    title: str,
    type_uri: str,
    errors: dict[str, list[str]] | None = None,
) -> Response:
    """The second of the three shapes: RFC 9457 problem details as JSON.

    **The keys stay camelCase whatever content profile was negotiated.** They come from the
    reference's own framework rather than from its API models, so `profile="PascalCase"` does not
    make them `Type` and `Title` - the negotiated media type is echoed, the key spellings are not
    touched. `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`

    Key order is the reference's: `type`, `title`, `status`, then `errors` where there is one,
    then `traceId`. It costs nothing to preserve and a golden compares bytes.
    """
    body: dict[str, Any] = {"type": type_uri, "title": title, "status": status_code}
    if errors is not None:
        body["errors"] = errors
    body["traceId"] = trace_id()
    return AtriumJSONResponse(body, status_code=status_code)


#: What the reference says about a value inside a body that did not bind. Measured, and the key
#: it is filed under is the **empty string**.
BODY_VALUE_INVALID = "The supplied value is invalid."


def validation_errors(raw: list[Any], body_parameter: str | None = None) -> dict[str, list[str]]:
    """The framework's validation failures, keyed and worded as the reference words them.

    The key is the **declared** parameter name rather than the spelling the client sent: a request
    with `Limit=abc` against a route declaring `limit` comes back keyed `limit`, measured, which
    is also what `compat.query_params` canonicalisation produces before the binder ever runs.

    ⚠️ **Only the type-mismatch wording is measured** - `The value 'abc' is not valid.` What the
    reference says for a *missing* required parameter was not measured, so that case carries the
    framework's own message rather than a guess at the reference's.
    `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`

    **A refusal of the *body* is keyed differently, and 007 T1 measured how.** The reference files
    the binder's own complaint under `""` (a value inside the body that did not bind) or `"$"`
    (the text was not JSON at all), *and* names the action parameter the body binds to with
    `The <parameter> field is required.` - so one failure spells its keys differently on each
    route. `body_parameter` is that name, read from the route, because the framework here would
    otherwise key the **model's field**: `item_id`, in snake_case, on the wire.
    `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`, behaviours section 1.11.
    """
    collected: dict[str, list[str]] = {}
    for error in raw:
        location = tuple(error.get("loc") or ("",))
        if body_parameter is not None and location and location[0] == "body":
            # The text failing to parse is `json_invalid`, and its location is `("body", 0)` -
            # a byte offset rather than a field, so the error's *type* is what tells the two
            # apart and `len(location)` is not.
            unparseable = str(error.get("type", "")).startswith("json_")
            key = "$" if unparseable else ""
            message = (
                str(error.get("msg", BODY_VALUE_INVALID)) if unparseable else BODY_VALUE_INVALID
            )
            collected.setdefault(key, []).append(message)
            required = f"The {body_parameter} field is required."
            if required not in collected.setdefault(body_parameter, []):
                collected[body_parameter].append(required)
            continue
        name = str(location[-1])
        if "input" in error:
            message = f"The value '{error['input']}' is not valid."
        else:
            message = str(error.get("msg", "The value is not valid."))
        collected.setdefault(name, []).append(message)
    return collected


def body_parameter_of(request: Request) -> str | None:
    """The name the route's body binds to, which is what the reference's `errors` map names.

    Read off the resolved route rather than guessed: the three reporting routes call theirs
    `playbackStartInfo`, `playbackProgressInfo` and `playbackStopInfo` after the reference's own
    parameters, and a route with no body at all answers `None` and keeps the old keying.
    """
    route = request.scope.get("route")
    field = getattr(route, "body_field", None)
    if field is None:
        return None
    name: str | None = getattr(field, "alias", None) or getattr(field, "name", None)
    return name


async def validation_handler(request: Request, exc: Exception) -> Response:
    """Replace the framework's `422` with the reference's `400`, status **and** body.

    FastAPI answers an unbindable value with `422 Unprocessable Entity` and
    `{"detail": [...]}`, which is neither the reference's status nor any of its three shapes. The
    replacement is global rather than per route, because the one route that forgets is the one a
    client meets. behaviours sections 1.11 and 1.12: the line is token-versus-type - an
    unrecognised enum *token* is dropped and answered `200`, a value that cannot parse as its
    declared *type* is this.
    """
    raw = exc.errors() if isinstance(exc, RequestValidationError) else []
    return problem_details(
        400,
        VALIDATION_TITLE,
        PROBLEM_TYPE_BAD_REQUEST,
        validation_errors(list(raw), body_parameter_of(request)),
    )


async def not_found_handler(_request: Request, _exc: Exception) -> Response:
    return problem_details(404, NOT_FOUND_TITLE, PROBLEM_TYPE_NOT_FOUND)


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


async def forbidden_handler(_request: Request, _exc: Exception) -> Response:
    return empty_error(403)


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


def message_error(status_code: int, message: str) -> Response:
    r"""The fourth shape: the message as a JSON-encoded **bare string**.

    A quoted string is a complete JSON document, and that is exactly what the reference sends -
    `"#1 to Infinity does not have an image of type Box"`, 51 bytes including the quotes, under
    `application/json; charset=utf-8`. Going through `AtriumJSONResponse` rather than writing the
    bytes by hand is what makes the escaping and the negotiated profile the same here as
    everywhere else: an item called `DW Español` comes back as `DW Espa\u00F1ol`, uppercase hex,
    measured on the reference and produced here by the response class rather than by this
    function. `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`
    """
    return AtriumJSONResponse(message, status_code=status_code)


async def image_not_found_handler(_request: Request, exc: Exception) -> Response:
    message = str(exc) if isinstance(exc, ImageNotFoundError) else NOT_FOUND_TITLE
    return message_error(404, message)


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
        # (Principle VII) - and alphabetical is what the reference sends on the one measured
        # pair where alphabetical and registration order differ: PUT /UserFavoriteItems/{itemId}
        # answers "Allow: DELETE, POST" (behaviours section 1.11, probe_routing 2026-08-28).
        headers = {"Allow": ", ".join(sorted(allowed))} if allowed else None
    return empty_error(exc.status_code, headers)


#: Registered by the application factory. Kept here so the wire shape of an error lives beside the
#: wire shape of everything else.
EXCEPTION_HANDLERS: dict[int | type[Exception], ExceptionHandler] = {
    UnauthenticatedError: unauthenticated_handler,
    ForbiddenError: forbidden_handler,
    ClientAuthorizationError: client_authorization_handler,
    InvalidCredentialsError: invalid_credentials_handler,
    AccountUnavailableError: account_unavailable_handler,
    NotFoundError: not_found_handler,
    # `ItemNotFoundError` inherits `NotFoundError` and needs no row: Starlette resolves a
    # handler by walking the exception's MRO, so the subclass finds the base's handler and the
    # two shapes stay one shape. `ImageNotFoundError` does not inherit it - different shape.
    ImageNotFoundError: image_not_found_handler,
    RequestValidationError: validation_handler,
    HTTPException: routing_handler,
}

__all__ = [
    "CONTROLLER_ERROR_BODY",
    "CONTROLLER_ERROR_TYPE",
    "EXCEPTION_HANDLERS",
    "IMAGE_ABSENT_TEMPLATE",
    "NOT_FOUND_TITLE",
    "PROBLEM_TYPE_BAD_REQUEST",
    "PROBLEM_TYPE_NOT_FOUND",
    "ROUTING_REFUSALS",
    "VALIDATION_TITLE",
    "AccountUnavailableError",
    "ClientAuthorizationError",
    "ExceptionHandler",
    "ForbiddenError",
    "ImageNotFoundError",
    "InvalidCredentialsError",
    "ItemNotFoundError",
    "NotFoundError",
    "UnauthenticatedError",
    "account_unavailable_handler",
    "client_authorization_handler",
    "controller_error",
    "empty_error",
    "forbidden_handler",
    "image_absent_message",
    "image_not_found_handler",
    "invalid_credentials_handler",
    "message_error",
    "not_found_handler",
    "problem_details",
    "routing_handler",
    "trace_id",
    "unauthenticated_handler",
    "validation_errors",
    "validation_handler",
]
