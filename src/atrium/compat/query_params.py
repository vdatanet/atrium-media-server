# SPDX-License-Identifier: GPL-3.0-or-later
"""Three fights with the web framework, settled once, before any route has to have them.

All three are places where the reference is looser than the framework and the framework's default
is silently wrong rather than loudly wrong - which is the worst kind, because the symptom appears
in a client and not in a test.

**Query parameter names match case-insensitively** (behaviours section 1.15). The pinned document
spells every parameter camelCase, the reference's own clients send PascalCase, and both work
against a real Jellyfin. FastAPI matches exactly, so `StartIndex` against a route declaring
`startIndex` is not rejected - it is *ignored*, which means every page is page one. A request's
query keys are rewritten to the route's declared spellings before the framework binds them, the
same way `compat.routing` rewrites the path, and for the same reason.

**An unrecognised enum token is dropped, not rejected** (behaviours section 1.12).
`sortBy=NotASortOption` answers `200` with an unfiltered result. The line is token-versus-type: a
value that cannot parse as its declared *type* - `limit=abc` - is still a `400`. `known_tokens`
below is the one place that keeps the good tokens and records the rest.

**A parameter this server does not implement is ignored and counted** (spec 005 section 3.3).
`/Items` declares 86 query parameters and v1 answers 32 of them; rejecting the others would turn a
partial answer into no answer *and* be a delta of its own. The bounded delta is accepted with a
mechanism attached: every ignored `(route, parameter, client)` triple is counted and logged once,
so the set real clients actually send becomes measurable rather than assumed. 010 section 3.6
turns that into a report; this module makes the events exist.

**The client is the third of AC-10's four columns and it was missing** (010 plan section 6.8,
D-5, taken 2026-09-01). The count was reaching nothing at all: `counts` and `total()` had no
reader anywhere in `src/`, and `record` took no client although every authenticated request
carries one in the header `compat/auth.py` already parses. A tally that says *"`is3D` was sent
1 412 times to `/Items`"* cannot be acted on, because promoting a parameter to Tier 2 or declining
it in writing is a decision about **whose** client would notice. So `record` takes the client, the
counter keys on the triple, and `IgnoredParameters.write` puts the tally in the data directory
when the process stops.

**Into the data directory, and never into a route.** An endpoint serving the tally would be an
endpoint Jellyfin does not have, which is Principle I's first forbidden line - and "optional,
behind a flag" does not save it, because an extension a client can discover is still a delta. It
is diagnostic output of this server about itself: it leaves as a file nothing on the wire can ask
for, or it does not leave at all. A file is also the only form that can be complete, since the
last request a route could have answered is the one before shutdown.

**The rewrite never touches a value.** Only the key is unquoted, matched and replaced; the bytes
after the first `=` are copied across exactly as they arrived. Re-encoding the whole pair would
round-trip almost everything correctly and change `+`, `;` and any over-escaped octet, which is a
difference in a search term rather than in a parameter name.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, unquote_plus

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from atrium.compat.auth import QUERY_PARAMETERS as AUTHENTICATION_PARAMETERS
from atrium.compat.auth import client_name
from atrium.compat.routing import RouteTable

logger = logging.getLogger(__name__)

#: Query keys every route accepts without declaring them. `compat.auth` reads the token straight
#: off the query string - it is one of the five authentication mechanisms (002 section 3.1) and
#: belongs to no route's signature - so without this the recorder would report `api_key` as an
#: ignored parameter on every authenticated request a media player makes.
GLOBAL_PARAMETERS: frozenset[str] = frozenset(AUTHENTICATION_PARAMETERS)


#: Where `CanonicalQueryMiddleware` keeps the query string exactly as it arrived. Namespaced, as
#: every extra ASGI scope key must be, so it cannot collide with a server's or another
#: middleware's.
ORIGINAL_QUERY_STRING = "atrium.original_query_string"


class AmbiguousParameterError(RuntimeError):
    """Two declared parameters on one route differ only in case.

    Fatal at startup, because canonicalisation could not then say which one an incoming
    `startindex` meant, and picking either would bind the wrong one for some client. Plan
    section 9 row 5: this fails at boot rather than in a client.
    """


@dataclass(frozen=True, slots=True)
class QueryParameterTable:
    """Every route's declared query parameter spellings, indexed for a case-insensitive lookup."""

    #: Route template -> {lowercased spelling: declared spelling}.
    by_template: Mapping[str, Mapping[str, str]]

    @classmethod
    def from_routers(cls, routers: Iterable[object]) -> QueryParameterTable:
        """Walk the routers the application factory is about to include.

        Built here rather than from the running application for the same reason `RouteTable` is:
        this is the one moment the set of routes is known without asking the framework how it
        stored them.
        """
        built: dict[str, dict[str, str]] = {}
        for router in routers:
            for route in getattr(router, "routes", ()):
                dependant = getattr(route, "dependant", None)
                path = getattr(route, "path", None)
                if dependant is None or path is None:
                    continue
                spellings = built.setdefault(path, {})
                for name in _declared(dependant):
                    existing = spellings.setdefault(name.lower(), name)
                    if existing != name:
                        raise AmbiguousParameterError(
                            f"{path} declares both {existing!r} and {name!r}, which differ only "
                            f"in case. Query parameter names match case-insensitively "
                            f"(behaviours 1.15), so no request could say which one it meant."
                        )
        for spellings in built.values():
            for name in GLOBAL_PARAMETERS:
                spellings.setdefault(name.lower(), name)
        return cls(by_template={path: dict(names) for path, names in built.items()})

    def declared(self, template: str) -> Mapping[str, str]:
        return self.by_template.get(template, {})

    def canonical(self, template: str, key: str) -> str | None:
        """The declared spelling of `key` on this route, or None when the route declares no such
        parameter in any casing - which is what makes it a candidate for the recorder."""
        return self.by_template.get(template, {}).get(key.lower())


def _declared(dependant: object) -> Iterator[str]:
    """Every query parameter name reachable from a route, sub-dependencies included.

    A parameter declared by a shared dependency is as bindable as one in the handler's own
    signature, and a walk that stopped at the top level would canonicalise one and not the other -
    which is the sort of difference that shows up on one endpoint out of seventeen.
    """
    for parameter in getattr(dependant, "query_params", ()):
        alias = getattr(parameter, "alias", None)
        if isinstance(alias, str):
            yield alias
    for sub in getattr(dependant, "dependencies", ()):
        yield from _declared(sub)


#: What an unauthenticated caller - or one whose client header carries no `Client=` - is recorded
#: as. An empty string in the key and this word in the file, so that a reader of the tally is
#: never left wondering whether a blank cell means "nobody" or "not written yet".
UNKNOWN_CLIENT = "unknown"


class Recorder(Protocol):
    """What the parsers need of a tally: somewhere to put a `(route, parameter)` they dropped.

    A protocol rather than `IgnoredParameters` itself, because a route hands its parsers a
    recorder that already knows **who** is asking (`ClientBoundRecorder`), and a parser has no
    business knowing that a client exists.
    """

    def record(self, route: str, parameter: str) -> None: ...


@dataclass(slots=True)
class IgnoredParameters:
    """What the server was sent and did not act on, per `(route, parameter, client)`.

    The measurable trail spec 005 section 3.3 promises in exchange for the one delta v1 accepts
    knowingly, with the client 010 AC-10 asks for. Counted always; logged **once per distinct
    triple per process**, because a client that sends an unimplemented parameter sends it on every
    request and the useful signal is the set, not the volume.
    """

    counts: dict[tuple[str, str, str], int] = field(default_factory=dict)
    _announced: set[tuple[str, str, str]] = field(default_factory=set)

    def record(self, route: str, parameter: str, client: str = "") -> None:
        key = (route, parameter, client)
        self.counts[key] = self.counts.get(key, 0) + 1
        if key not in self._announced:
            self._announced.add(key)
            logger.info(
                "ignored query parameter %s on %s sent by %s; it is not implemented in v1 and "
                "the request was answered without it",
                parameter,
                route,
                client or UNKNOWN_CLIENT,
            )

    def for_client(self, client: str) -> ClientBoundRecorder:
        """This tally, seen from one request, so a parser records the client without knowing it."""
        return ClientBoundRecorder(self, client)

    def total(self) -> int:
        return sum(self.counts.values())

    def rows(self) -> list[dict[str, object]]:
        """AC-10's four columns, ordered loudest first and then alphabetically.

        The order is part of the report: a tally sorted by name buries the parameter every client
        sends under the one a single request sent once.
        """
        return [
            {
                "parameter": parameter,
                "endpoint": route,
                "count": count,
                "client": client or UNKNOWN_CLIENT,
            }
            for (route, parameter, client), count in sorted(
                self.counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]

    def write(self, destination: Path) -> None:
        """The tally, as a file in the data directory, at the one moment it is complete.

        JSON because a program reads it - `tools/differential.py` renders 010 section 3.6's report
        from it - for the same reason `property-names.json` is JSON. Written even when it is
        empty: *no client sent an unimplemented parameter* is a finding, and an absent file cannot
        be told apart from a server that stopped before it could write one.
        """
        payload = {
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "total": self.total(),
            "rows": self.rows(),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True, slots=True)
class ClientBoundRecorder:
    """One request's view of the tally: the same counter, with the client already filled in."""

    tally: IgnoredParameters
    client: str

    def record(self, route: str, parameter: str) -> None:
        self.tally.record(route, parameter, self.client)


def known_tokens[TokenT: Enum](
    values: Sequence[str],
    vocabulary: type[TokenT],
    *,
    route: str = "",
    parameter: str = "",
    ignored: Recorder | None = None,
) -> tuple[TokenT, ...]:
    """The members of `vocabulary` named in `values`, with unrecognised tokens dropped.

    behaviours section 1.12: an unrecognised token drops that filter and the request succeeds. It
    is **not** an error, and it is not the whole parameter either - `sortBy=SortName,Nonsense`
    keeps `SortName`.

    Matched case-insensitively, because a parameter *name* matching case-insensitively while its
    *values* did not would be a distinction no client could have learned. Order is the order the
    client sent, which is what makes `sortBy` a sequence of keys rather than a set.
    """
    members = {member.value.lower(): member for member in vocabulary}
    kept: list[TokenT] = []
    for raw in values:
        token = raw.strip()
        member = members.get(token.lower())
        if member is None:
            if ignored is not None and token:
                ignored.record(route, f"{parameter}={token}" if parameter else token)
            continue
        kept.append(member)
    return tuple(kept)


class CanonicalQueryMiddleware:
    """Rewrite a request's query keys to the spellings its route declares.

    Raw ASGI, like every other middleware here: this changes a request before routing and never
    looks at a response, and `BaseHTTPMiddleware` would buffer every one of them - wrong in kind,
    and wrong for the byte-range delivery feature 008 adds.

    **It must run after `RelaxedPathMiddleware`**, because it looks the route up by the canonical
    path that middleware produces. In `add_middleware` terms that means it is added *first*: the
    last middleware added is the outermost one.
    """

    def __init__(
        self,
        app: ASGIApp,
        table: QueryParameterTable,
        routes: RouteTable,
        ignored: IgnoredParameters,
    ) -> None:
        self.app = app
        self.table = table
        self.routes = routes
        self.ignored = ignored

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("query_string"):
            await self.app(scope, receive, send)
            return

        # Kept before anything is rewritten, for the one route family that hands its own query
        # back to the client. 008's playlists forward the query string **verbatim** into every
        # segment URI, the way the reference forwards what arrived - so a client reading the
        # playlist reads back the spellings it sent, `?&` doubling and all, rather than this
        # server's declared ones (`api/dynamic_hls.py`).
        scope = {**scope, ORIGINAL_QUERY_STRING: scope["query_string"]}

        template = self.routes.template_for(scope["path"])
        if template is None:
            # No route: the request is on its way to an empty 404 and there is nothing to
            # canonicalise it against. Recording here would count parameters against a route that
            # does not exist.
            await self.app(scope, receive, send)
            return

        # Who is asking, for the tally's fourth column (010 AC-10). Read here rather than in the
        # recorder because this is the layer that still has the request: by the time a route's
        # parser drops a token, the headers are three frames up.
        client = client_name(Headers(scope=scope))
        rewritten = self._rewrite(scope["query_string"], template, client)
        if rewritten != scope["query_string"]:
            scope = {**scope, "query_string": rewritten}
        await self.app(scope, receive, send)

    def _rewrite(self, query_string: bytes, template: str, client: str = "") -> bytes:
        parts: list[bytes] = []
        for pair in query_string.split(b"&"):
            if not pair:
                continue
            key, separator, value = pair.partition(b"=")
            decoded = unquote_plus(key.decode("utf-8", "replace"))
            canonical = self.table.canonical(template, decoded)
            if canonical is None:
                self.ignored.record(template, decoded, client)
                parts.append(pair)
                continue
            # The value is copied, never re-encoded: `+`, `;` and an over-escaped octet all mean
            # something inside a search term and nothing inside a parameter name.
            parts.append(quote(canonical).encode("ascii") + separator + value)
        return b"&".join(parts)


__all__ = [
    "GLOBAL_PARAMETERS",
    "ORIGINAL_QUERY_STRING",
    "UNKNOWN_CLIENT",
    "AmbiguousParameterError",
    "CanonicalQueryMiddleware",
    "ClientBoundRecorder",
    "IgnoredParameters",
    "QueryParameterTable",
    "Recorder",
    "known_tokens",
]
