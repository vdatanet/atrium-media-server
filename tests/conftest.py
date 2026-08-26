# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared fixtures, and the one command-line option the suite adds.

Every test gets a fresh instance with a temporary data directory: no shared state between tests,
no ordering dependencies, and the whole suite runs with no network and no external service
(Principle VII). See specs/001-server-identity-and-discovery/plan.md section 8.4.

The last of those is **enforced rather than intended** - see `no_outbound_connections` below. A
suite that merely happens not to reach the network today is one commit away from a test that skips
when a server is unreachable, and a test that skips is a test that does not exist.
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.config.settings import Settings, load
from atrium.config.state import ServerState, load_or_create
from atrium.domain.user import User
from atrium.server import create_app
from tests.conformance.golden import REWRITTEN, UPDATE_OPTION


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        UPDATE_OPTION,
        action="store_true",
        default=False,
        help="Rewrite the checked-in golden responses from what the server sent. The run reports "
        "what it rewrote: a golden diff is a change to what clients receive, and is reviewed "
        "as one (docs/compatibility/conformance.md, L1).",
    )


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Say what was rewritten, so nobody discovers it in a diff after pushing."""
    rewritten = terminalreporter.config.stash.get(REWRITTEN, set())
    if not rewritten:
        return
    terminalreporter.write_line("")
    terminalreporter.write_line(
        f"{UPDATE_OPTION}: rewrote {len(rewritten)} golden response(s): "
        f"{', '.join(sorted(rewritten))}",
        bold=True,
    )
    terminalreporter.write_line(
        "Read the diff before committing. Each of these is a statement about what a client "
        "receives, and a change to one is a change to the contract."
    )


@pytest.fixture(autouse=True)
def no_outbound_connections(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail any test that opens a TCP connection, rather than trusting that none does.

    Principle VII forbids tests that depend on network availability, and the failure mode it
    guards against is not a test that *fails* without a server - it is one that quietly skips.
    This turns the whole class into a loud error naming the address that was dialled.

    **Datagram sockets are deliberately still allowed.** `net.address.address_facing` opens one
    and calls `connect` to ask the routing table which local address faces a peer; that sends no
    packet and needs nothing reachable, and it is the mechanism under test in
    tests/unit/test_net_address.py.

    A test that genuinely needs a reference server - the differential harness feature 010
    specifies - carries `@pytest.mark.needs_reference` and is exempt. Nothing does yet.
    """
    if request.node.get_closest_marker("needs_reference") is not None:
        return

    original = socket.socket.connect

    def guarded(self: socket.socket, address: object) -> None:
        if self.type == socket.SOCK_STREAM:
            raise AssertionError(
                f"this test opened a TCP connection to {address!r}. The suite runs with no "
                f"network and no external service (Principle VII): use a fixture, or mark the "
                f"test @pytest.mark.needs_reference if it is one of feature 010's."
            )
        original(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


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
def app(paths: DataPaths) -> Iterator[FastAPI]:
    """A real instance, built by the factory the server ships.

    Assembling the pieces by hand here would test a composition nobody runs. The readiness gate is
    opened directly rather than through the lifespan, because these tests drive the application
    through a transport that does not run one.
    """
    built = create_app(paths)
    built.state.readiness.mark_ready()
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
