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
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, event

from atrium import server
from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.config.settings import Settings, load
from atrium.config.state import ServerState, load_or_create
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.domain.media import MediaInspection
from atrium.domain.user import User
from atrium.media.probe import UnreadableMediaError
from atrium.server import create_app
from tests.conformance.golden import REWRITTEN, UPDATE_OPTION
from tests.fixtures.library import BuiltFixture, build_fixture_library
from tests.fixtures.media import (
    BINARIES,
    BuiltMedia,
    build_media_files,
    missing_binaries,
)
from tests.fixtures.media_world import ScannedMediaWorld, build_scanned_media_world


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


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip an `ffmpeg`-marked test when the binaries are absent, rather than failing it.

    Every other external dependency in this suite is forbidden - the network guard below turns a
    missing server into a loud error precisely so nobody can trade a failure for a skip. This is
    the one exception and it points the other way: ffmpeg is a *build tool*, not a service, the
    tests that need it produce and inspect real media, and a contributor without it should get a
    green suite with an honest gap rather than a wall of red they cannot act on. CI installs it,
    so the gap is never load-bearing there.

    The fence is checkable: `pytest -m "not ffmpeg"` on a machine that *has* ffmpeg must still be
    green, which is what proves every test that reaches a binary carries the marker.
    """
    if item.get_closest_marker("ffmpeg") is None:
        return
    absent = missing_binaries()
    if absent:
        pytest.skip(f"needs {' and '.join(BINARIES)}; not on PATH: {', '.join(absent)}")


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

    A test that genuinely needs a reference service carries `@pytest.mark.needs_reference` and is
    exempt. **One does, since 004 T14**: the live provider replay plan section 8 promised, which
    checks that TMDB and MusicBrainz still answer in the shape this project's synthetic fixtures
    claim. It is skipped unless credentials are in the environment and it never runs in CI.
    Feature 010's differential harness will be the second.
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


@pytest.fixture(autouse=True)
def dispose_database_engines(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Close every database connection a test opened, rather than trusting it to.

    `create_app` opens an engine and the lifespan disposes it - and most of these tests
    deliberately never run a lifespan, so nothing would. SQLite notices: a pooled connection that
    reaches the garbage collector unclosed emits a `ResourceWarning`, and `filterwarnings =
    ["error"]` turns that into a failure in whichever test happened to be running when the
    collector got round to it, which is never the test that opened it.

    Wrapping the factory rather than teaching each test to tidy up keeps this true for the tests
    nobody has written yet, in the same spirit as the network guard above: enforced, not intended.
    """
    opened: list[Engine] = []
    build = server.create_database_engine

    def recording(paths: DataPaths, **kwargs: object) -> Engine:
        engine = build(paths, **kwargs)  # type: ignore[arg-type]
        opened.append(engine)
        return engine

    monkeypatch.setattr(server, "create_database_engine", recording)
    yield
    for engine in opened:
        engine.dispose()


#: A user the override hands back. Not a credential: nothing authenticates as this.
TEST_USER = User(id="a" * 32, name="joan", is_administrator=True)

#: Argon2id at its cheapest, written into every test data directory. Measured on this machine:
#: 41 ms per hash at the shipped parameters against 0.06 ms at these, and the factory hashes the
#: dummy record once per server it builds. plan section 8.4 - a suite that verifies dozens of
#: passwords at 64 MiB takes minutes, and a slow suite gets run less often, which costs more
#: security than the parameters buy.
#:
#: It goes in through `config.toml` rather than by patching a default, because that is the
#: mechanism an operator has, and a test that lowers them any other way is not exercising it.
FAST_PASSWORDS = "[passwords]\nmemory_cost = 8\ntime_cost = 1\nparallelism = 1\n"


def not_media(path: Path) -> MediaInspection:
    """The prober the 003 and 004 fixture libraries scan with, and the truth about them.

    `tests/fixtures/library/generate.py` says it in its own words - "these are not decodable
    media" - so the honest stub is the refusal a real prober would give, not an invented
    inspection. What it saves is the process: several hundred files across those suites, each
    costing an `ffprobe` launch to be told what this function already knows.

    A test that wants a *real* inspection uses `scanned_media_world`, whose files really are
    media and whose scan runs the real prober.
    """
    raise UnreadableMediaError(f"{path} is a fixture file, not media")


def data_dir(root: Path) -> DataPaths:
    """A prepared data directory whose passwords are cheap to check.

    Every test that builds a server goes through here rather than through `DataPaths` directly.
    Nothing else is configured, so a test asserting a default still gets one - and the tests that
    are *about* configuration build their own directories and do not use this.
    """
    paths = DataPaths(root)
    paths.prepare()
    paths.config_file.write_text(FAST_PASSWORDS, encoding="utf-8")
    return paths


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


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


@dataclass
class QueryCounter:
    """Every SQL statement one engine executed, so a test can assert on how many there were.

    The N+1 ban is a contract rather than a hope (005 plan §5): hydration is complete *and* costs
    a fixed number of statements, so a page of one and a page of a hundred are the same number of
    round trips. That is invisible in a functional test - the wrong implementation returns exactly
    the right answer - and quadratic in a real library.

    Counting statements rather than timing them is deliberate: a timing assertion is a flake, and
    what actually went wrong is always visible in the count.
    """

    statements: list[str] = dataclasses_field(default_factory=list)

    def __len__(self) -> int:
        return len(self.statements)

    @contextmanager
    def watching(self, engine: Engine) -> Iterator[QueryCounter]:
        def record(_conn: object, _cursor: object, statement: str, *_rest: object) -> None:
            self.statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            yield self
        finally:
            event.remove(engine, "before_cursor_execute", record)

    def reset(self) -> None:
        self.statements.clear()

    def report(self) -> str:
        """The statements, one per line, for a failure message that says what to delete."""
        return "\n".join(f"  {n + 1}. {one}" for n, one in enumerate(self.statements))


@pytest.fixture
def query_counter() -> QueryCounter:
    return QueryCounter()


@pytest.fixture
def fixture_library(tmp_path: Path) -> BuiltFixture:
    """The declared library of tests/fixtures/library, written fresh for this test.

    Fresh per test rather than shared, deliberately. The 003 tests that matter most *mutate the
    tree* - delete a file and rescan, move a root, make a directory unreadable - and a shared tree
    would make them order-dependent in the one feature whose wrong answers are silent. Building it
    is a few hundred small writes and costs less than the first assertion that has to be debugged.
    """
    return build_fixture_library(tmp_path / "library")


@pytest.fixture(scope="session")
def media_files() -> BuiltMedia:
    """The generated media matrix of `tests/fixtures/media.py`, encoded once.

    Session-scoped and cached between runs, unlike `fixture_library` above, and the difference is
    what each fixture costs against what its tests do to it. A 003 test *mutates the tree* - it
    deletes a file and rescans - so sharing one would make those tests order-dependent, and
    rebuilding it is a few hundred small writes. This one costs real encoder time and nothing reads
    it except to inspect: a test that wants to change a file calls `copy_into` first.

    Only requested by tests carrying `@pytest.mark.ffmpeg`, which are skipped above when the
    binaries are missing - so this never runs on a machine that cannot satisfy it.
    """
    return build_media_files()


@pytest.fixture
def scanned_media_world(tmp_path: Path, media_files: BuiltMedia) -> Iterator[ScannedMediaWorld]:
    """Two libraries over the generated tree, scanned by the real 003 pipeline.

    A fresh database per test over shared files: the rows are cheap and the encodes are not, and a
    world whose rows persisted between tests would be the ordering dependency `fixture_library`
    avoids by rebuilding.

    The real scan rather than seeded rows, unlike `tests/fixtures/query.py`: the point of this
    world is that the rows and the files on disk agree about which file is where, which is exactly
    what a seeded row cannot say.
    """
    paths = data_dir(tmp_path / "atrium")
    engine = create_database_engine(paths)
    schema.ensure_current(engine, paths)
    try:
        with session_factory(engine).begin() as session:
            yield build_scanned_media_world(session, media_files)
    finally:
        engine.dispose()
