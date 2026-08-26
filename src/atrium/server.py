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
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from atrium import REFERENCE_VERSION, __version__
from atrium.api import system
from atrium.compat.errors import EXCEPTION_HANDLERS
from atrium.compat.middleware import ResponseHeadersMiddleware
from atrium.compat.responses import AtriumJSONResponse
from atrium.compat.routing import RelaxedPathMiddleware, RouteTable
from atrium.config.paths import ConfigurationError, DataPaths, resolve_data_dir
from atrium.config.settings import load as load_settings
from atrium.config.state import load_or_create
from atrium.lifecycle import Readiness, ReadinessMiddleware

logger = logging.getLogger("atrium")

#: Every router this server serves, in one place. The route table is built from exactly these, so
#: a router that is not here is not routed and not in the surface check either.
ROUTERS = (system.router,)


def create_app(paths: DataPaths | None = None) -> FastAPI:
    """Build an instance rooted at `paths`, or at the configured data directory."""
    resolved = paths if paths is not None else DataPaths(resolve_data_dir())
    resolved.prepare()

    settings = load_settings(resolved)
    state = load_or_create(resolved)
    readiness = Readiness()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Everything slow belongs here, before the gate opens. Today there is nothing slow, and
        # the gate exists anyway so that 002's migrations and 003's scan have somewhere to go
        # that is already wired, already tested and already answering correctly meanwhile.
        readiness.mark_ready()
        logger.info(
            "Atrium %s serving the Jellyfin %s API from %s",
            __version__,
            REFERENCE_VERSION,
            resolved.root,
        )
        yield

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

    # Innermost, so it sits directly in front of the router and nothing else sees the rewrite.
    # Then the gate, then the headers - the last added is the outermost, which is what puts
    # `Server` and `X-Response-Time-ms` on a 503 served while starting.
    app.add_middleware(RelaxedPathMiddleware, table=routes)
    app.add_middleware(ReadinessMiddleware, readiness=readiness)
    app.add_middleware(ResponseHeadersMiddleware)

    for router in ROUTERS:
        app.include_router(router)

    # Starlette's own answer to an unmatched trailing slash is a 307 the reference does not send -
    # and for a doubled slash, a 307 to a URL that works, where the reference answers 404.
    app.router.redirect_slashes = False

    app.state.paths = resolved
    app.state.settings = settings
    app.state.server_state = state
    app.state.readiness = readiness
    app.state.routes = routes
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

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

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
