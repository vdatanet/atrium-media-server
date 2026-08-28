# SPDX-License-Identifier: GPL-3.0-or-later
"""Assembling an instance.

`create_app` is the one place that decides what an Atrium server is made of, and it is written to
read as a list of decisions rather than as setup. Everything it wires was built to be wired here:
the configuration and state it loads, the middleware it stacks, the routers it includes, and the
authentication seam it leaves for feature 002 to fill.

**Middleware order is load-bearing and was checked rather than assumed.** Starlette makes the
*last* middleware added the outermost, so response headers wrap the readiness gate and a `503`
served while starting still carries `Server` and `X-Response-Time-ms` - as the reference's does,
since its own response-time middleware sits outside everything too.

**Two instances in one process share nothing.** Every piece of state hangs off the application,
not off a module, which is what lets a test suite build a fresh server per test.

See specs/001-server-identity-and-discovery/plan.md section 3.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from atrium import REFERENCE_VERSION, __version__
from atrium import logs as log_setup
from atrium.api import (
    artists,
    filters,
    genres,
    items,
    localization,
    resume,
    search,
    system,
    tv_shows,
    user_library,
    user_views,
    users,
    years,
)
from atrium.api import sessions as session_routes
from atrium.compat.errors import EXCEPTION_HANDLERS
from atrium.compat.middleware import ResponseHeadersMiddleware
from atrium.compat.profiles import ContentProfileMiddleware
from atrium.compat.query_params import (
    CanonicalQueryMiddleware,
    IgnoredParameters,
    QueryParameterTable,
)
from atrium.compat.responses import AtriumJSONResponse
from atrium.compat.routing import RelaxedPathMiddleware, RouteTable
from atrium.config.paths import ConfigurationError, DataPaths, resolve_data_dir
from atrium.config.settings import load as load_settings
from atrium.config.state import load_or_create
from atrium.db.engine import create_database_engine, session_factory, verify_connection
from atrium.db.schema import ensure_current
from atrium.lifecycle import Readiness, ReadinessMiddleware
from atrium.users import passwords as password_module
from atrium.users.service import Authenticator
from atrium.users.sessions import SessionRegistry

logger = logging.getLogger("atrium")

#: Every router this server serves, in one place. The route table is built from exactly these, so
#: a router that is not here is not routed and not in the surface check either.
#: `users.router` registers its literal paths before `/Users/{userId}`, and the route table tries
#: patterns in this order - so `/users/public` reaches the public route rather than being read as a
#: user whose identifier is `public`. tests/conformance/test_routes.py asserts it.
#:
#: `items.router` is deliberately **last**: it owns `/Items/{itemId}`, and the literal `/Items/*`
#: routes still to land (`/Items/Latest` at T11, `/Items/Filters` at T15) must be registered
#: before it, or "Latest" is read as an identifier and refused as one.
ROUTERS = (
    system.router,
    users.router,
    session_routes.router,
    localization.router,
    # The two literal-path item routers land before `items.router`, which owns /Items/{itemId}.
    user_views.router,
    user_library.router,
    tv_shows.router,
    resume.router,
    artists.router,
    genres.router,
    years.router,
    filters.router,
    search.router,
    items.router,
)


def create_app(paths: DataPaths | None = None) -> FastAPI:
    """Build an instance rooted at `paths`, or at the configured data directory."""
    resolved = paths if paths is not None else DataPaths(resolve_data_dir())
    resolved.prepare()

    settings = load_settings(resolved)
    state = load_or_create(resolved)
    readiness = Readiness()

    # The database opens *here* rather than in the lifespan below, which is where 001 expected
    # 002's migrations to go. Both refusals this involves - an unopenable database, and a schema
    # this build does not expect - have to reach the operator as the sentence plan section 7
    # promises, and a lifespan that raises delivers a traceback and "Application startup failed".
    # The gate keeps its purpose: 003's scan is slow, and this is not.
    engine = create_database_engine(resolved)
    verify_connection(engine, resolved)
    ensure_current(engine, resolved)
    sessions = session_factory(engine)

    # Argon2id's dummy record is hashed here, once, rather than on the first login that needs it.
    # It is what an unknown username is verified against, and a record built lazily would make the
    # first such login slower than every later one - which is the timing signal it exists to
    # remove. ADR-0006, plan section 6.2.
    passwords = password_module.build(settings.passwords)

    # Activity accumulates here and reaches the database on the interval below, because advancing
    # LastActivityDate synchronously would take a SQLite write lock on every authenticated
    # request. plan section 6.5.
    registry = SessionRegistry(sessions)

    # The only entry point that verifies a password. It owns the lockout counter, the timing
    # guarantee and session creation, because splitting those across callers is how one of them
    # gets forgotten. plan section 5.
    authenticator = Authenticator(sessions, passwords, registry, settings.authentication)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Everything slow belongs here, before the gate opens. Today there is nothing slow, and
        # the gate exists anyway so that 003's scan has somewhere to go that is already wired,
        # already tested and already answering correctly meanwhile.
        readiness.mark_ready()
        logger.info(
            "Atrium %s serving the Jellyfin %s API from %s",
            __version__,
            REFERENCE_VERSION,
            resolved.root,
        )
        flusher = asyncio.create_task(registry.run())
        try:
            yield
        finally:
            flusher.cancel()
            with suppress(asyncio.CancelledError):
                await flusher
            # The clean-shutdown flush. Without it, stopping a server at the wrong moment would
            # lose activity it had every opportunity to write - which is a different thing from
            # the crash this design already accepts losing thirty seconds to.
            with suppress(SQLAlchemyError):
                registry.flush()
            # Returns every pooled connection, which is what closes the WAL cleanly. Without it a
            # test that builds hundreds of instances leaves hundreds of open files behind.
            engine.dispose()

    app = FastAPI(
        title="Atrium",
        version=__version__,
        lifespan=lifespan,
        default_response_class=AtriumJSONResponse,
        exception_handlers=dict(EXCEPTION_HANDLERS),
        # The reference serves its OpenAPI document at /api-docs/openapi.json. Atrium serves none:
        # the route is not in docs/compatibility/surface.yaml, no analysed client asks for it, and
        # Principle VI forbids adding an endpoint without a named consumer. The document is still
        # *generated* - `app.openapi()` builds it - which is what ADR-0002 chose FastAPI for.
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )

    # What counts as "this path": the reference matches case-insensitively and accepts one trailing
    # slash, and Starlette does neither. Built from ROUTERS rather than read back out of the
    # application, and it is what an Allow header is built from too. compat/routing.py.
    routes = RouteTable.from_routers(ROUTERS)

    # Which query parameter spellings each route declares, and the tally of what was sent and
    # ignored. Built from ROUTERS for the same reason the route table is, and it refuses at boot a
    # route whose parameters differ only in case - plan 005 section 9 row 5. compat/query_params.py.
    query_parameters = QueryParameterTable.from_routers(ROUTERS)
    ignored_parameters = IgnoredParameters()

    # Innermost of all, because it looks a route up by the path the rewrite below has already
    # canonicalised - so it must run *after* that one, which in `add_middleware` terms means being
    # added *before* it: the last added is the outermost.
    app.add_middleware(
        CanonicalQueryMiddleware,
        table=query_parameters,
        routes=routes,
        ignored=ignored_parameters,
    )
    # Then the path rewrite, directly in front of the router so nothing else sees it. Then the
    # profile, which every serialiser downstream reads; then the gate; then the headers - the last
    # added is the outermost, which is what puts `Server` and `X-Response-Time-ms` on a 503 served
    # while starting.
    app.add_middleware(RelaxedPathMiddleware, table=routes)
    app.add_middleware(ContentProfileMiddleware)
    app.add_middleware(ReadinessMiddleware, readiness=readiness)
    app.add_middleware(ResponseHeadersMiddleware)

    for router in ROUTERS:
        app.include_router(router)

    # Starlette's own answer to an unmatched trailing slash is a 307 the reference does not send -
    # and for a doubled slash, a 307 to a URL that works, where the reference answers 404.
    app.router.redirect_slashes = False

    app.state.paths = resolved
    app.state.db = engine
    app.state.sessions = sessions
    app.state.passwords = passwords
    app.state.registry = registry
    app.state.authenticator = authenticator
    app.state.settings = settings
    app.state.server_state = state
    app.state.readiness = readiness
    app.state.routes = routes
    app.state.query_parameters = query_parameters
    app.state.ignored_parameters = ignored_parameters
    return app


def main(argv: list[str] | None = None) -> int:
    """Console entry point."""
    parser = argparse.ArgumentParser(prog="atrium", description="Atrium media server")
    parser.add_argument("--data-dir", type=Path, help="Where this instance keeps its things")
    parser.add_argument("--version", action="store_true", help="Print the version and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(f"atrium {__version__} (Jellyfin {REFERENCE_VERSION} API)")  # noqa: T201
        return 0

    # Not `basicConfig` alone: SQLAlchemy writes every statement and its bound parameters once
    # its logger is enabled for INFO, and this feature's bound parameters are password hashes and
    # token hashes. atrium.logs also redacts the credential the query mechanisms put in a URL.
    log_setup.configure(logging.INFO)

    try:
        app = create_app(DataPaths(resolve_data_dir(args.data_dir)))
    except ConfigurationError as exc:
        # Refusing to start beats starting wrongly, and the operator needs the reason, not a
        # traceback. plan section 7.
        print(f"atrium: {exc}", file=sys.stderr)  # noqa: T201
        return 1

    import uvicorn

    settings = app.state.settings
    uvicorn.run(
        app,
        host=settings.network.bind_address,
        port=settings.network.port,
        # Atrium stamps its own; uvicorn's would be replaced anyway, so do not spend the bytes.
        server_header=False,
        log_config=None,
    )
    return 0


__all__ = ["create_app", "main"]
