# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures.

Every test gets a fresh instance with a temporary data directory: no shared state between tests,
no ordering dependencies, and the whole suite runs with no network and no external service
(Principle VII). See specs/001-server-identity-and-discovery/plan.md section 8.4.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.api import system
from atrium.api.deps import require_user
from atrium.compat.errors import EXCEPTION_HANDLERS
from atrium.compat.middleware import ResponseHeadersMiddleware
from atrium.compat.responses import AtriumJSONResponse
from atrium.config.paths import DataPaths
from atrium.config.settings import Settings, load
from atrium.config.state import ServerState, load_or_create
from atrium.domain.user import User

#: A user the override hands back. Not a credential: nothing authenticates as this.
TEST_USER = User(id="a" * 32, name="joan", is_administrator=True)


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    prepared = DataPaths(tmp_path / "atrium")
    prepared.prepare()
    return prepared


@pytest.fixture
def settings(paths: DataPaths) -> Settings:
    return load(paths)


@pytest.fixture
def server_state(paths: DataPaths) -> ServerState:
    return load_or_create(paths)


@pytest.fixture
def app(paths: DataPaths, settings: Settings, server_state: ServerState) -> Iterator[FastAPI]:
    """An application with 001's routes wired.

    T15 replaces this body with a call to the real factory. Until then it assembles the same
    pieces, so the tests exercise the composition rather than the routes in isolation.
    """
    built = FastAPI(
        default_response_class=AtriumJSONResponse,
        exception_handlers=dict(EXCEPTION_HANDLERS),
    )
    built.add_middleware(ResponseHeadersMiddleware)
    built.include_router(system.router)
    built.state.paths = paths
    built.state.settings = settings
    built.state.server_state = server_state
    yield built
    built.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, client=("192.168.1.50", 51234))
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


@pytest.fixture
def authenticated(app: FastAPI) -> User:
    """Reach the authenticated path without shipping a credential. plan section 1."""
    app.dependency_overrides[require_user] = lambda: TEST_USER
    return TEST_USER
