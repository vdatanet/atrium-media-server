# SPDX-License-Identifier: GPL-3.0-or-later
"""The scan worker inside the server: coalescing, refusals, the row's state, and stopping.

014 plan section 6.5, and T6's Verified-by. **Every test here drives a real `scan`** over the 003
fixture tree - the only thing substituted is the prober, which is handed the refusal a real one
gives dummy bytes - and where a test needs a scan to be *in the middle of something*, it wraps the
scanner's own call to `scan` so the scan thread waits at a named point on an event the test
releases. Nothing sleeps: a test that waited for a scan to be "probably running" would be the flake
this suite does not allow.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from atrium.config.paths import DataPaths
from atrium.config.settings import Settings, load
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library import scanner as scanner_module
from atrium.library.report import Phase, Progress, ScanReport
from atrium.library.scanner import IDLE, Scanner, ScanTrigger
from atrium.metadata.remote import RemoteAccess
from atrium.server import create_app
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture

#: How long a scan thread waits on a test before giving up. Never reached by a passing test; it is
#: what turns a broken one into a failure rather than a hung suite.
PATIENCE = 10.0


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def engine(paths: DataPaths) -> Iterator[Engine]:
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def sessions(engine: Engine) -> sessionmaker[Session]:
    return session_factory(engine)


@pytest.fixture
async def scanner(sessions: sessionmaker[Session], paths: DataPaths) -> Any:
    built = Scanner(sessions, load(paths), paths, prober=not_media)
    yield built
    # A test that fails half-way must not leave a worker task or a scan thread behind it.
    await built.stop()


def a_library(
    sessions: sessionmaker[Session], fixture_library: BuiltFixture, kind: str, name: str = ""
) -> Library:
    with session_scope(sessions) as db:
        return config.create(
            LibraryRepository(db), name or kind.title(), kind, (str(fixture_library.of(kind).root),)
        )


def items_of(sessions: sessionmaker[Session], library: Library) -> dict[str, Any]:
    with session_scope(sessions) as db:
        return ItemRepository(db).by_library(library.id)


async def settled(scanner: Scanner) -> None:
    """`idle()`, bounded: a worker that died would otherwise hang the suite rather than fail."""
    await asyncio.wait_for(scanner.idle(), PATIENCE)


class Gate:
    """A point a scan thread stops at until the test lets it go."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.released = threading.Event()

    def hold(self) -> None:
        self.reached.set()
        assert self.released.wait(PATIENCE), "the test never released the scan"

    async def wait_reached(self) -> None:
        assert await asyncio.to_thread(self.reached.wait, PATIENCE), "the scan never got there"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every call the scanner makes to `scan`, recorded and passed through."""
    made: list[dict[str, Any]] = []
    real = scanner_module.scan

    def recording(library: Library, session: Session, **options: Any) -> Any:
        made.append({"library": library, **options})
        return real(library, session, **options)

    monkeypatch.setattr(scanner_module, "scan", recording)
    return made


def wrap_scan(
    monkeypatch: pytest.MonkeyPatch,
    *,
    before: Callable[[Library], None] = lambda _: None,
    on_progress: Callable[[Progress], None] = lambda _: None,
) -> dict[str, int]:
    """Wrap the scanner's `scan`: `before` runs as each scan starts, `on_progress` after the
    scanner's own sink has seen each report. Counts scans started and scans that returned."""
    counts = {"started": 0, "returned": 0}
    real = scanner_module.scan

    def wrapped(library: Library, session: Session, **options: Any) -> Any:
        counts["started"] += 1
        before(library)
        sink = options["progress"]

        def observed(progress: Progress) -> None:
            sink(progress)
            on_progress(progress)

        options["progress"] = observed
        report = real(library, session, **options)
        counts["returned"] += 1
        return report

    monkeypatch.setattr(scanner_module, "scan", wrapped)
    return counts


# ------------------------------------------------------------------------------------------
# A request, and the worker it starts
# ------------------------------------------------------------------------------------------


async def test_a_request_scans_the_library_and_returns_before_the_scan_does(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`request` never waits: it returned while the scan it started was still held."""
    library = a_library(sessions, fixture_library, "movies")
    gate = Gate()
    wrap_scan(monkeypatch, before=lambda _: gate.hold())

    scanner.request([library.id], ScanTrigger.REFRESH)
    await gate.wait_reached()
    assert items_of(sessions, library) == {}, "nothing is committed while the scan is held"
    gate.released.set()
    await settled(scanner)

    stored = items_of(sessions, library)
    assert sum(1 for one in stored.values() if one.type is ItemType.MOVIE) > 0


async def test_idle_on_a_scanner_never_asked_returns_at_once(scanner: Scanner) -> None:
    """No request, no worker: a server that is never asked to scan runs no scanning task."""
    await settled(scanner)
    assert scanner._worker is None


async def test_two_requests_during_a_pass_make_exactly_one_more_pass(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = a_library(sessions, fixture_library, "music")
    gate = Gate()
    counts = wrap_scan(
        monkeypatch, before=lambda _: gate.hold() if not gate.released.is_set() else None
    )

    scanner.request([library.id], ScanTrigger.REFRESH)
    await gate.wait_reached()
    scanner.request([library.id], ScanTrigger.REFRESH)
    scanner.request(None, ScanTrigger.REFRESH)
    gate.released.set()
    await settled(scanner)

    assert counts == {"started": 2, "returned": 2}


async def test_every_library_is_scanned_for_none(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    calls: list[dict[str, Any]],
) -> None:
    libraries = {a_library(sessions, fixture_library, kind).id for kind in ("movies", "music")}
    scanner.request(None, ScanTrigger.REFRESH)
    await settled(scanner)
    assert {call["library"].id for call in calls} == libraries


# ------------------------------------------------------------------------------------------
# A library that cannot be scanned does not stop the pass
# ------------------------------------------------------------------------------------------


async def test_a_refused_library_does_not_stop_the_next(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Guard one refuses a root that is not there; the warning names the library, and the library
    after it in the same pass is scanned."""
    gone = tmp_path / "unmounted"
    gone.mkdir()
    with session_scope(sessions) as db:
        refused = config.create(LibraryRepository(db), "Unmounted", "movies", (str(gone),))
    gone.rmdir()
    scanned = a_library(sessions, fixture_library, "music")

    with caplog.at_level(logging.WARNING, logger=scanner_module.__name__):
        scanner.request([refused.id, scanned.id], ScanTrigger.REFRESH)
        await settled(scanner)

    warnings = [one for one in caplog.records if one.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert refused.id in warnings[0].getMessage()
    assert warnings[0].exc_info is None, "a refusal is the operator's news, not a traceback"
    assert any(one.type is ItemType.AUDIO for one in items_of(sessions, scanned).values())


async def test_an_unexpected_failure_is_logged_with_its_traceback_and_the_pass_continues(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = a_library(sessions, fixture_library, "movies")
    scanned = a_library(sessions, fixture_library, "music")

    def explode(library: Library) -> None:
        if library.id == broken.id:
            raise RuntimeError("a bug in the scan")

    wrap_scan(monkeypatch, before=explode)
    with caplog.at_level(logging.ERROR, logger=scanner_module.__name__):
        scanner.request([broken.id, scanned.id], ScanTrigger.REFRESH)
        await settled(scanner)

    errors = [one for one in caplog.records if one.levelno == logging.ERROR]
    assert len(errors) == 1
    assert broken.id in errors[0].getMessage()
    assert errors[0].exc_info is not None
    assert any(one.type is ItemType.AUDIO for one in items_of(sessions, scanned).values())
    # And the worker survived it: a later request is still served.
    scanner.request([broken.id], ScanTrigger.REFRESH)
    await settled(scanner)


async def test_a_library_with_no_roots_is_skipped_silently(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    calls: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decided by the operator on 2026-09-14: no `ScanRefusedError` log for a library with no
    paths, on this request or any later one - and its view is already there without a scan."""
    with session_scope(sessions) as db:
        library = config.create_with_view(db, "Nowhere", "movies", ())

    with caplog.at_level(logging.DEBUG, logger=scanner_module.__name__):
        scanner.request([library.id], ScanTrigger.ADDED)
        scanner.request(None, ScanTrigger.REFRESH)
        await settled(scanner)

    assert calls == []
    assert [one for one in caplog.records if one.levelno >= logging.WARNING] == []
    assert list(items_of(sessions, library)) == [library.item_id]


# ------------------------------------------------------------------------------------------
# What the library row says about a scan
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("trigger", "shown"), [(ScanTrigger.ADDED, "Active"), (ScanTrigger.REFRESH, "Idle")]
)
async def test_the_row_shows_a_scan_its_library_was_added_with_and_not_a_refresh(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
    trigger: ScanTrigger,
    shown: str,
) -> None:
    library = a_library(sessions, fixture_library, "music")
    other = a_library(sessions, fixture_library, "movies")
    gate = Gate()

    def hold_while_writing(progress: Progress) -> None:
        if progress.phase is Phase.WRITING and progress.done == 2:
            gate.hold()

    wrap_scan(monkeypatch, on_progress=hold_while_writing)
    assert scanner.refresh_state(library.id) == IDLE

    scanner.request([library.id], trigger)
    await gate.wait_reached()
    during = scanner.refresh_state(library.id)
    beside = scanner.refresh_state(other.id)
    gate.released.set()
    await settled(scanner)

    assert during.status == shown
    if shown == "Active":
        assert during.progress is not None
        assert 75.0 < during.progress < 100.0, "writing is the last of four phases, part done"
    else:
        assert during.progress is None
    assert beside == IDLE, "only the library being scanned"
    assert scanner.refresh_state(library.id) == IDLE, "and not once it has finished"


async def test_added_wins_when_one_library_is_asked_both_ways(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coalesced into one pass, the library keeps the trigger a client may be waiting on."""
    library = a_library(sessions, fixture_library, "music")
    first, second = Gate(), Gate()
    seen: list[str] = []

    def hold(progress: Progress) -> None:
        if progress.phase is Phase.WRITING and progress.done == 2:
            seen.append(scanner.refresh_state(library.id).status)
            (second if first.released.is_set() else first).hold()

    wrap_scan(monkeypatch, on_progress=hold)
    scanner.request([library.id], ScanTrigger.REFRESH)
    await first.wait_reached()
    scanner.request([library.id], ScanTrigger.ADDED)
    scanner.request([library.id], ScanTrigger.REFRESH)
    first.released.set()
    await second.wait_reached()
    second.released.set()
    await settled(scanner)

    assert seen == ["Idle", "Active"]


# ------------------------------------------------------------------------------------------
# Stopping
# ------------------------------------------------------------------------------------------


async def test_stop_rolls_the_library_back_and_a_later_request_rescans_it(
    scanner: Scanner,
    sessions: sessionmaker[Session],
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = a_library(sessions, fixture_library, "music")
    gate = Gate()

    def hold_mid_write(progress: Progress) -> None:
        if progress.phase is Phase.WRITING and progress.done == 5 and not gate.released.is_set():
            gate.hold()

    counts = wrap_scan(monkeypatch, on_progress=hold_mid_write)
    scanner.request([library.id], ScanTrigger.REFRESH)
    await gate.wait_reached()

    stopping = asyncio.create_task(scanner.stop())
    await asyncio.sleep(0)  # the flag is set as the task starts
    gate.released.set()
    await asyncio.wait_for(stopping, PATIENCE)

    assert items_of(sessions, library) == {}, "four rows were written and none was committed"
    assert counts == {"started": 1, "returned": 0}, "the sink stopped the scan, not its end"

    scanner.request([library.id], ScanTrigger.REFRESH)
    await settled(scanner)
    assert any(one.type is ItemType.AUDIO for one in items_of(sessions, library).values())
    assert counts == {"started": 2, "returned": 1}


async def test_the_lifespan_stops_a_worker_a_request_started(
    tmp_path: Path, fixture_library: BuiltFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server's own scanner: started by nothing in the lifespan, stopped by it."""
    app = create_app(data_dir(tmp_path / "server"))
    scanner: Scanner = app.state.scanner
    library = a_library(app.state.sessions, fixture_library, "movies")
    gate = Gate()
    wrap_scan(monkeypatch, before=lambda _: gate.hold())

    async with app.router.lifespan_context(app):
        assert scanner._worker is None, "the lifespan starts no scanning task"
        scanner.request([library.id], ScanTrigger.REFRESH)
        await gate.wait_reached()
        gate.released.set()

    assert scanner._worker is None


# ------------------------------------------------------------------------------------------
# Providers
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("configured", [False, True])
async def test_the_providers_are_built_from_the_providers_settings(
    sessions: sessionmaker[Session],
    paths: DataPaths,
    fixture_library: BuiltFixture,
    calls: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    configured: bool,
) -> None:
    """Both of 004's providers, on every scan, with `[providers]`' credentials - so one that is not
    configured sits out with its reason rather than being left out in silence (004 AC-9)."""
    settings = Settings()
    if configured:
        settings = Settings.model_validate(
            {
                "providers": {
                    "tmdb_api_key": "a-key",
                    "musicbrainz_contact": "operator@example.invalid",
                    "metadata_country": "ES",
                }
            }
        )
    closed: list[str] = []
    real_close = RemoteAccess.close

    def close(access: RemoteAccess) -> None:
        closed.append(access.provider)
        real_close(access)

    monkeypatch.setattr(RemoteAccess, "close", close)
    library = a_library(sessions, fixture_library, "tvshows")
    scanner = Scanner(sessions, settings, paths, prober=not_media)

    def read_what_it_was_handed(library: Library, session: Session, **options: Any) -> ScanReport:
        calls.append({"library": library, **options})
        return ScanReport(library_id=library.id)

    # Stubbed rather than run: what is asserted is what the scan was handed, and a real one with
    # credentials would reach for the network the suite refuses.
    monkeypatch.setattr(scanner_module, "scan", read_what_it_was_handed)
    try:
        scanner.request([library.id], ScanTrigger.REFRESH)
        await settled(scanner)
    finally:
        await scanner.stop()

    (call,) = calls
    providers = call["providers"]
    assert [type(one).__name__ for one in providers] == ["TmdbProvider", "MusicBrainzProvider"]
    if configured:
        assert [one.enabled() for one in providers] == [True, True]
        assert providers[0]._country == "ES"
        assert providers[0]._artwork_root == paths.artwork
        assert (
            providers[1]
            ._access._client.headers["User-Agent"]
            .endswith("( operator@example.invalid )")
        )
    else:
        reasons = [one.enabled() for one in providers]
        assert all(isinstance(reason, str) for reason in reasons)
    assert sorted(closed) == sorted(one.name for one in providers)


# ------------------------------------------------------------------------------------------
# AC-8: through the routes, browsed as the first account
# ------------------------------------------------------------------------------------------


async def _fresh_server(tmp_path: Path) -> Any:
    """A server nobody has set up, whose scanner is handed the fixture tree's prober, and the
    first account's token - read into existence, given a password, signed in from this machine."""
    from atrium.users.first_account import FIRST_ACCOUNT_NAME
    from tests.conformance.test_setup_window import LOOPBACK, PASSWORD, ask, token_for

    app = create_app(data_dir(tmp_path / "server"))
    app.state.readiness.mark_ready()
    app.state.scanner = Scanner(
        app.state.sessions, app.state.settings, app.state.paths, prober=not_media
    )
    assert (await ask(app, LOOPBACK, "GET", "/Startup/User")).status_code == 200
    updated = await ask(app, LOOPBACK, "POST", "/Startup/User", json={"Password": PASSWORD})
    assert updated.status_code == 204, updated.content
    return app, await token_for(app, LOOPBACK, FIRST_ACCOUNT_NAME)


async def _browsable_films(app: Any, token: str, name: str) -> tuple[bool, int]:
    """Whether the first account sees the library as a view, and how many films `/Items` finds
    under it - both as an unmodified client asks, from elsewhere, with the token."""
    from tests.conformance.test_setup_window import ELSEWHERE, ask

    viewed = await ask(app, ELSEWHERE, "GET", "/UserViews", token=token)
    assert viewed.status_code == 200, viewed.content
    ids = [row["Id"] for row in viewed.json()["Items"] if row["Name"] == name]
    if not ids:
        return False, 0
    films = await ask(
        app,
        ELSEWHERE,
        "GET",
        "/Items",
        token=token,
        params={"parentId": ids[0], "recursive": "true", "includeItemTypes": "Movie"},
    )
    assert films.status_code == 200, films.content
    return True, int(films.json()["TotalRecordCount"])


def _films_stored(app: Any) -> int:
    with session_scope(app.state.sessions) as db:
        (library,) = LibraryRepository(db).all()
        stored = ItemRepository(db).by_library(library.id)
    return sum(1 for one in stored.values() if one.type is ItemType.MOVIE)


async def test_ac8_a_library_added_with_refresh_is_browsable_once_its_scan_has_finished(
    tmp_path: Path, fixture_library: BuiltFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`refreshLibrary=true`: the `204` arrives while the scan it started is held, `idle()` has not
    resolved, and nothing is browsable yet; once the scan is let go and has finished, the first
    account browses every film the scan stored (014 spec section 3.6, AC-8)."""
    from tests.conformance.test_setup_window import LOOPBACK, ask

    app, token = await _fresh_server(tmp_path)
    scanner: Scanner = app.state.scanner
    gate = Gate()
    wrap_scan(monkeypatch, before=lambda _: gate.hold())
    try:
        answered = await ask(
            app,
            LOOPBACK,
            "POST",
            "/Library/VirtualFolders",
            params={
                "name": "Movies",
                "collectionType": "movies",
                "paths": str(fixture_library.of("movies").root),
                "refreshLibrary": "true",
            },
        )
        assert answered.status_code == 204, answered.content
        idle = asyncio.ensure_future(scanner.idle())
        await gate.wait_reached()
        assert not idle.done(), "the 204 was sent before the scan it started had finished"
        assert await _browsable_films(app, token, "Movies") == (True, 0)

        gate.released.set()
        await asyncio.wait_for(idle, PATIENCE)

        stored = _films_stored(app)
        assert stored > 0
        assert await _browsable_films(app, token, "Movies") == (True, stored)
    finally:
        gate.released.set()
        await scanner.stop()


async def test_ac8_a_library_scanned_through_refresh_is_browsable_once_the_scan_has_finished(
    tmp_path: Path, fixture_library: BuiltFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Added with `refreshLibrary=false` - a view with nothing in it, and no scan started - then
    `POST /Library/Refresh` as the first account, an administrator: its `204` arrives while the
    scan is held, and the films are browsable once the scan has finished (spec section 3.7)."""
    from tests.conformance.test_setup_window import ELSEWHERE, LOOPBACK, ask

    app, token = await _fresh_server(tmp_path)
    scanner: Scanner = app.state.scanner
    gate = Gate()
    wrap_scan(monkeypatch, before=lambda _: gate.hold())
    try:
        added = await ask(
            app,
            LOOPBACK,
            "POST",
            "/Library/VirtualFolders",
            params={
                "name": "Movies",
                "collectionType": "movies",
                "paths": str(fixture_library.of("movies").root),
            },
        )
        assert added.status_code == 204, added.content
        assert scanner._worker is None, "refreshLibrary=false starts no scan"
        assert await _browsable_films(app, token, "Movies") == (True, 0)

        answered = await ask(app, ELSEWHERE, "POST", "/Library/Refresh", token=token)
        assert answered.status_code == 204, answered.content
        idle = asyncio.ensure_future(scanner.idle())
        await gate.wait_reached()
        assert not idle.done(), "the 204 was sent before the scan it started had finished"
        assert await _browsable_films(app, token, "Movies") == (True, 0)

        gate.released.set()
        await asyncio.wait_for(idle, PATIENCE)

        stored = _films_stored(app)
        assert stored > 0
        assert await _browsable_films(app, token, "Movies") == (True, stored)
    finally:
        gate.released.set()
        await scanner.stop()
