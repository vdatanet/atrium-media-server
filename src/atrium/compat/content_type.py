# SPDX-License-Identifier: GPL-3.0-or-later
"""The content-type gate: `415` where a body's media type is one this server cannot read.

**This is the fifth error shape**, and it sat in
[behaviours section 5](../../../docs/compatibility/behaviours.md) as an accepted gap from 2026-09-01
until 2026-09-06, on a description that turned out to be wrong about the request as well as the
routes. That row said *"a required body that is missing entirely is `400` and not `415`"* and
listed five routes whose body it called required. Measured against a reference instance, one
request per case, on a route whose body is required and on one whose body is optional
`[probe: tools/probe_content_type_gate.py, Jellyfin 10.11.11, 2026-09-06]`:

```
                                no body, no CT   body, no CT   body, text/plain   valid body
POST /Sessions/Playing                     415           415                415          204
POST /Sessions/Playing/Progress            415           415                415          204
POST /Sessions/Playing/Stopped             415           415                415          204
POST /Items/{itemId}/PlaybackInfo          200           415                415          200
```

So the gate is not about a **missing body**: it is about the **media type of a body the server has
to read**. A route whose body is *required* must read one however the request arrived, so it
refuses a request with no acceptable content type even when there is nothing to read; a route whose
body is *optional* reads nothing when nothing was sent and answers normally. `PlaybackInfo` is in
the second group, which is why that row's list of five was four.

**What counts as readable was measured too**, nine media types on one route: `application/json`,
`text/json` and any `+json` suffix are accepted, with parameters and in any case;
`application/x-www-form-urlencoded`, `*/*` and the empty string are refused. So the rule is a
suffix rule rather than a list, which is what an ASP.NET input formatter does.

The body is the ordinary problem-details shape with no `errors` map, and its `type` points at RFC
9110's own section for the status - the same spelling every other problem-details body here uses.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from starlette.routing import Match
from starlette.types import ASGIApp, Receive, Scope, Send

from atrium.compat.errors import (
    PROBLEM_TYPE_UNSUPPORTED_MEDIA_TYPE,
    UNSUPPORTED_MEDIA_TYPE_TITLE,
    problem_details,
)

#: The exact media types an input formatter here reads, beside the `+json` suffix rule below.
READABLE = frozenset({"application/json", "text/json"})

#: The suffix that makes any type readable - `application/problem+json`, `application/vnd.api+json`
#: and anything else shaped that way, all measured accepted.
JSON_SUFFIX = "+json"


def readable(content_type: str | None) -> bool:
    """Whether a body announced as this can be read.

    Parameters are dropped and the type is folded, because `application/json; charset=utf-8` and
    `APPLICATION/JSON` were both accepted. An empty or absent header is not readable, which is the
    case that makes a required body's request a `415` with nothing in it.
    """
    if not content_type:
        return False
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in READABLE or media_type.endswith(JSON_SUFFIX)


def _leaves(routes: Iterable[Any]) -> Iterable[Any]:
    """Every route, descending through the wrappers `include_router` leaves behind.

    **The application's `routes` is not a list of routes.** FastAPI puts an `_IncludedRouter` there
    per `include_router` call, holding the real one as `original_router` - so a search that took
    the list at face value found 26 objects, none with a path and none with a body, and the gate
    silently never fired. Two attribute names are tried and neither is required to exist, because
    this is a shape of the framework rather than of this project.
    """
    for route in routes:
        nested = getattr(route, "routes", None)
        if nested is None:
            inner = getattr(route, "original_router", None)
            nested = getattr(inner, "routes", None) if inner is not None else None
        if nested:
            yield from _leaves(nested)
        else:
            yield route


def _is_required(body_field: Any) -> bool:
    """Whether the route must read a body, however the request arrived.

    Asked of the field's own declaration rather than of a list here. Pydantic answers it directly;
    the fallback is the sentinel that answer is made of, for a version that does not.

    Measured on the five routes this application declares with a required body - 002's
    authentication, 007's three reporting routes and 009's rename - and on the two whose body is
    optional, `POST /Playlists` and `POST /Items/{itemId}/PlaybackInfo`. behaviours §5's row named
    `PlaybackInfo` among the five required ones and it is not one: it answers `200` to a request
    with no body at all `[probe: tools/probe_content_type_gate.py, Jellyfin 10.11.11, 2026-09-06]`.
    """
    info = getattr(body_field, "field_info", None)
    asked = getattr(info, "is_required", None)
    if callable(asked):
        return bool(asked())
    return repr(getattr(info, "default", None)) == "PydanticUndefined"


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if bytes(key).lower() == name:
            return str(bytes(value).decode("latin-1"))
    return None


def _carries_a_body(scope: Scope) -> bool:
    """Whether this request announced a body at all.

    `Content-Length` above zero, or a chunked transfer with no length to read. A request that
    announced neither has nothing for a formatter to read, which is the whole difference between
    the two rows of the table in this module's docstring.
    """
    length = _header(scope, b"content-length")
    if length is not None and length.strip().isdigit() and int(length) > 0:
        return True
    encoding = _header(scope, b"transfer-encoding")
    return bool(encoding and "chunked" in encoding.lower())


class ContentTypeGateMiddleware:
    """Refuse a body this server cannot read, before anything tries to bind it.

    **Ahead of the binding and not inside it**, which is what the gap row asked for: a validation
    handler downstream sees a body that failed to parse and cannot tell that apart from a body that
    parsed into the wrong shape - which is exactly how this server answered `400` where the
    reference answers `415`.

    Raw ASGI, like every other middleware here: `BaseHTTPMiddleware` buffers the response and runs
    the application in another task, and 008's delivery routes cannot have either.

    **Which routes require a body is read off the application rather than listed here.** FastAPI
    knows: a route with a body field that is required must read one, and a route whose body field
    is optional need not. A hand-kept list would be a second statement of something the router
    already holds, and would go stale the day a route gains a body.
    """

    def __init__(self, app: ASGIApp, routes: Sequence[Any]) -> None:
        self.app = app
        #: The application's **live** route list, not a copy of it. This middleware is registered
        #: before the routers are included - it has to be, because the last middleware added is the
        #: outermost and this one belongs inside the path rewrite - so a snapshot taken here would
        #: be empty and the gate would never fire. Iterating the list at request time is also what
        #: keeps it honest if a router is added later.
        self.routes = routes
        self._cached: tuple[Any, ...] | None = None
        self._counted = -1

    def _with_bodies(self) -> tuple[Any, ...]:
        """Every route that can read a body, flattened and remembered.

        **Flattened, because this application's routes are not a flat list.** `include_router`
        wraps each router, so the application's own `routes` holds wrappers and the routes that
        declare a body sit a level down - a search that did not descend found none of them and the
        gate never fired, which is how this was discovered rather than reasoned.

        Remembered against the length of the live list, so the walk happens once and again only if
        a router is added. There is no request-time cost to a `GET`, which never reaches here.
        """
        if self._cached is None or self._counted != len(self.routes):
            self._cached = tuple(
                route for route in _leaves(self.routes) if getattr(route, "body_field", None)
            )
            self._counted = len(self.routes)
        return self._cached

    def _matched(self, scope: Scope) -> Any | None:
        for route in self._with_bodies():
            match, _ = route.matches(scope)
            if match is Match.FULL:
                return route
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        if readable(_header(scope, b"content-type")):
            await self.app(scope, receive, send)
            return

        route = self._matched(scope)
        body_field = getattr(route, "body_field", None)
        if body_field is not None and (_is_required(body_field) or _carries_a_body(scope)):
            response = problem_details(
                415, UNSUPPORTED_MEDIA_TYPE_TITLE, PROBLEM_TYPE_UNSUPPORTED_MEDIA_TYPE
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def required_body_routes(routes: Iterable[Any]) -> tuple[Any, ...]:
    """The routes this gate has anything to say about: the ones that can read a body at all."""
    return tuple(route for route in _leaves(routes) if getattr(route, "body_field", None))


__all__ = [
    "JSON_SUFFIX",
    "READABLE",
    "ContentTypeGateMiddleware",
    "readable",
    "required_body_routes",
]
