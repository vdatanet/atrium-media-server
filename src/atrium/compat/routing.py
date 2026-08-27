# SPDX-License-Identifier: GPL-3.0-or-later
"""Matching a request path to a route, the way the reference matches it.

Every specification in this repository writes one canonical spelling of a path, and it is easy to
read that as the only spelling that works. The reference is looser in two specific ways, both
measured: `[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]`

* **Case-insensitively.** `/system/info/public` and `/SYSTEM/INFO/PUBLIC` reach the same handler as
  `/System/Info/Public`, because ASP.NET Core compares path segments without regard to case.
  Starlette compares them exactly, so a client that lowercases its paths - and clients do, from
  hand-written path literals to URL normalisers - is served by the reference and gets a `404` from
  an untreated Atrium.
* **One trailing slash, and only one.** `/System/Info/Public/` answers `200`;
  `/System/Info/Public//` answers `404`. Starlette's own answer to the first is a `307` redirect,
  which is a round trip the reference does not make, and to the second a `307` **to a working URL**,
  where the reference refuses.

**A request is rewritten to the canonical spelling before it is routed**, and only its spelling:
the segments a route declares literally are replaced by the way the route declares them, and every
value inside a path parameter is passed through untouched. `scope["raw_path"]` still carries what
the client actually sent, so nothing that wants the original loses it.

The alternative was to relax each route's compiled pattern in place. It works, in the sense that a
five-line loop makes the tests pass - and it reaches into a structure the web framework rebuilds
when it feels like it. This module uses the routers the application declares and Starlette's own
`compile_path`, which are the two public things involved.

**`Allow` on a `405` is rebuilt here too.** Starlette answers with the methods of the *first* route
whose path matched, so `/System/Ping` - two routes, `GET` and `POST` - advertises one of them. The
reference advertises both.

See specs/001-server-identity-and-discovery/spec.md section 3.6.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from starlette.routing import Route, compile_path
from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True, slots=True)
class RelaxedRoute:
    """One route's path, matched the reference's way and spelled the project's way."""

    #: Case-insensitive, with an optional single trailing slash.
    pattern: re.Pattern[str]
    #: `/Users/{userId}/Items` - the canonical spelling, with holes for the parameters.
    template: str
    methods: frozenset[str]

    @property
    def is_literal(self) -> bool:
        return "{" not in self.template


@dataclass(frozen=True, slots=True)
class RouteTable:
    """Every path this server serves, and what may be done to it.

    Built from the routers the application factory includes, before it includes them. That is the
    one place where the set of routes is known without asking the framework how it stored them.
    """

    routes: tuple[RelaxedRoute, ...]
    #: Paths with no parameters, which is what almost every request arrives as. Checking this set
    #: first keeps the common case a hash lookup instead of a walk over the regular expressions.
    literals: frozenset[str]

    @classmethod
    def from_routers(cls, routers: Iterable[object]) -> RouteTable:
        relaxed: list[RelaxedRoute] = []
        for router in routers:
            for route in getattr(router, "routes", ()):
                if not isinstance(route, Route) or not route.methods:
                    continue
                regex, template, _convertors = compile_path(route.path)
                # `/?$` rather than `/*$`: one trailing slash is accepted, two are not.
                pattern = re.compile(
                    re.sub(r"(?<!\\)\$$", "/?$", regex.pattern), regex.flags | re.IGNORECASE
                )
                relaxed.append(
                    RelaxedRoute(
                        pattern=pattern, template=template, methods=frozenset(route.methods)
                    )
                )
        return cls(
            routes=tuple(relaxed),
            literals=frozenset(r.template for r in relaxed if r.is_literal),
        )

    def canonicalise(self, path: str) -> str | None:
        """The canonical spelling of `path`, or None when it matches no route.

        Returning None rather than the path unchanged is the point: the caller must not be able to
        confuse "already canonical" with "not ours", because only the second is a `404`.
        """
        if path in self.literals:
            return path
        for route in self.routes:
            matched = route.pattern.match(path)
            if matched is not None:
                # The template carries the literal segments; the match carries the parameters. A
                # parameter's own value is never reinterpreted - it is substituted as it arrived.
                return route.template.format(**matched.groupdict())
        return None

    def template_for(self, path: str) -> str | None:
        """The declaring template of the route `path` matches - `/Users/{userId}/Items`, not the
        substituted spelling `canonicalise` returns.

        `compat.query_params` needs the template rather than the path, because a route's declared
        parameters are a property of the route and every concrete path under a templated one
        shares them. Returns None when nothing matches, for the same reason `canonicalise` does:
        "not ours" and "already canonical" must not be confusable.
        """
        for route in self.routes:
            if route.pattern.match(path):
                return route.template
        return None

    def methods_for(self, path: str) -> frozenset[str]:
        """Every method registered on the routes whose path matches, in any accepted spelling."""
        allowed: set[str] = set()
        for route in self.routes:
            if route.pattern.match(path):
                allowed |= route.methods
        return frozenset(allowed)

    def paths(self) -> frozenset[tuple[str, str]]:
        """Every `(method, path)` this table serves, for the surface-registration check."""
        return frozenset(
            (method, route.template) for route in self.routes for method in route.methods
        )


class RelaxedPathMiddleware:
    """Rewrite a request's path to the canonical spelling of the route it matches.

    Raw ASGI rather than `BaseHTTPMiddleware`, as everything else in this project is: the
    convenient one buffers every response, which is wrong for the byte-range and HLS delivery
    feature 008 adds. Here it would also be wrong in kind - this changes a request before routing,
    and never looks at the response at all.
    """

    def __init__(self, app: ASGIApp, table: RouteTable) -> None:
        self.app = app
        self.table = table

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            canonical = self.table.canonicalise(scope["path"])
            if canonical is not None and canonical != scope["path"]:
                scope = {**scope, "path": canonical}
        await self.app(scope, receive, send)


__all__ = ["RelaxedPathMiddleware", "RelaxedRoute", "RouteTable"]
