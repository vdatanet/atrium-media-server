# SPDX-License-Identifier: GPL-3.0-or-later
"""The scan, run inside the server: one worker, one library at a time, and routes that do not wait.

Until 014 `library.scan.scan` had no caller inside the server - tests and a throwaway script were
the only ones. Two operations now start one, `POST /Library/VirtualFolders` with
`refreshLibrary=true` and `POST /Library/Refresh`, and **both answer `204` as the scan starts**
(014 spec sections 3.6 and 3.7). A scan here is synchronous code writing one library inside one
transaction, so a route hands the libraries to `Scanner.request` and returns, and a single task
runs the scans in a thread (014 plan section 6.5).

**The worker starts on the first request, and nothing starts it anywhere else.** The lifespan only
stops it. That was a finding of the task gate rather than a preference: the transport every test
here uses runs no lifespan, so a worker the lifespan started would never have run under test - and
a server that is never asked to scan now runs no scanning task at all.

**A request during a pass is coalesced, not queued.** The ids join a pending set and the worker
runs one more pass once the current one ends. Three refreshes in a row therefore scan everything
twice - the pass that was running, and one more - rather than three times, which is what a caller
who pressed the button three times meant. Nothing is cancelled: the reference's `Cancelling` (spec
section 3.7) is recorded and not reproduced.

**Stopping is a flag the progress sink reads.** `scan` calls its sink as it moves, and the sink
raises when the flag is set, so the library's transaction rolls back and nothing half-written is
committed. **The exception is a `BaseException` and that is load-bearing**: `scan` hands the sink to
a reporter that catches `Exception`, disables the sink and lets the scan carry on, because a broken
progress bar must not roll back a good scan. A stop that was an `Exception` would have been logged
as a broken sink and ignored - found writing this module, 2026-09-14.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from atrium import __version__
from atrium.config.paths import DataPaths
from atrium.config.settings import Settings
from atrium.db.repositories import LibraryRepository
from atrium.library.report import Phase, Progress
from atrium.library.scan import MediaProber, ScanRefusedError, SubtitleProber, scan
from atrium.metadata import musicbrainz, tmdb
from atrium.metadata.remote import ProviderCredentials, RemoteAccess

logger = logging.getLogger(__name__)

#: The phases in the order a scan reports them, which is what turns one phase's fraction into a
#: fraction of the whole scan.
_PHASES: tuple[Phase, ...] = tuple(Phase)


class ScanTrigger(Enum):
    """What asked for a scan. It decides one thing: whether the library row shows it (§6.5)."""

    ADDED = "added"
    """`POST /Library/VirtualFolders` with `refreshLibrary=true`."""

    REFRESH = "refresh"
    """`POST /Library/Refresh`."""


@dataclass(frozen=True, slots=True)
class LibraryRefresh:
    """What `GET /Library/VirtualFolders` says about a library's scan.

    `progress` is a percentage, as the reference's `RefreshProgress` is - `10` and `10.666…` were
    read on it - and `None` whenever `status` is `Idle`, where the reference sends no key.
    """

    status: Literal["Idle", "Active"]
    progress: float | None = None


IDLE = LibraryRefresh(status="Idle")


class _Stopped(BaseException):
    """Raised by the sink once `stop()` has been asked. See the module docstring for why it is not
    an `Exception`."""


@dataclass(frozen=True, slots=True)
class _Current:
    library_id: str
    trigger: ScanTrigger
    progress: float = 0.0


class Scanner:
    """The in-process scan worker (014 plan sections 5 and 6.5).

    `prober` and `subtitle_prober` are handed to `scan` unchanged and default to the real ones; a
    test over the 003 fixture tree, whose files are dummy bytes, passes the refusal a real prober
    would give rather than paying a process launch per file to be told it.
    """

    def __init__(
        self,
        sessions: sessionmaker[OrmSession],
        settings: Settings,
        paths: DataPaths,
        *,
        prober: MediaProber | None = None,
        subtitle_prober: SubtitleProber | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._paths = paths
        self._prober = prober
        self._subtitle_prober = subtitle_prober
        #: Library id -> what asked for it, for the next pass. `ADDED` wins over `REFRESH` for one
        #: library: the caller that added it is the one a client may be waiting on through the row.
        self._pending: dict[str, ScanTrigger] = {}
        #: `request(None, ...)` - every library, resolved when the pass starts rather than when it
        #: was asked, so a library added in between is part of it.
        self._everything: ScanTrigger | None = None
        self._worker: asyncio.Task[None] | None = None
        self._wake: asyncio.Event | None = None
        self._settled: asyncio.Event | None = None
        self._stopping = False
        #: Written by the scan thread, read by the event loop. One reference assignment, replaced
        #: whole, so a reader sees a consistent value or the previous one.
        self._current: _Current | None = None

    # -- what the routes call ------------------------------------------------------------------

    def request(self, library_ids: Collection[str] | None, trigger: ScanTrigger) -> None:
        """Ask for these libraries - every library for `None` - to be scanned, and return at once.

        **Never blocks and never raises**: both routes answer `204` straight after calling it. The
        worker is started here, on the running loop, the first time anything is asked.
        """
        try:
            if library_ids is None:
                self._everything = _stronger(self._everything, trigger)
            else:
                for library_id in library_ids:
                    self._pending[library_id] = _stronger(self._pending.get(library_id), trigger)
            self._ensure_worker()
        except Exception:
            # Nothing above is expected to raise. If it does, the route still answers - a scan that
            # did not start is logged, and the operator can ask again - rather than a 500 for a
            # request whose library was already created.
            logger.exception("a scan request could not be handed to the scanner")

    def refresh_state(self, library_id: str) -> LibraryRefresh:
        """`Active` with its progress **only while a pass started by `ADDED` scans this library**.

        `Idle` otherwise, including during a scan `POST /Library/Refresh` started - the reference's
        own asymmetry, read on 2026-09-14 (spec section 3.5).
        """
        current = self._current
        if current is None or current.library_id != library_id:
            return IDLE
        if current.trigger is not ScanTrigger.ADDED:
            return IDLE
        return LibraryRefresh(status="Active", progress=current.progress)

    async def stop(self) -> None:
        """Stop the worker: a library being scanned rolls back, and nothing pending is scanned.

        Returns once the scan thread has let go of its transaction. The sink raises at the scan's
        next progress report, so a stop waits for that - which during 004's refresh, the one stretch
        of a scan that reports nothing, is the length of the refresh. A later request starts a new
        worker, and the library that was rolled back is scanned from the beginning.
        """
        worker = self._worker
        if worker is None:
            return
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        try:
            await worker
        finally:
            self._worker = None
            self._stopping = False
            self._pending.clear()
            self._everything = None
            if self._settled is not None:
                self._settled.set()

    async def idle(self) -> None:
        """Resolve once nothing is pending and nothing is being scanned. For tests; no client, and
        not Atrium's own, can see it."""
        if self._worker is None or self._settled is None:
            return
        await self._settled.wait()

    # -- the worker ----------------------------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._wake is None or self._settled is None:
            self._wake = asyncio.Event()
            self._settled = asyncio.Event()
        self._settled.clear()
        self._wake.set()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._run(), name="scanner")

    async def _run(self) -> None:
        assert self._wake is not None and self._settled is not None  # noqa: S101 - set by the caller
        while not self._stopping:
            if not self._pending and self._everything is None:
                # No await between finding nothing pending and waiting, so a request cannot slip in
                # between them: `request` runs on this loop too.
                self._settled.set()
                self._wake.clear()
                await self._wake.wait()
                continue
            # Taken on the loop, where `request` writes it, and emptied in the same step - so a
            # request arriving during the pass below lands in the next one.
            batch = dict(self._pending)
            everything = self._everything
            self._pending.clear()
            self._everything = None
            if everything is not None:
                for library_id in await asyncio.to_thread(self._library_ids):
                    batch[library_id] = _stronger(batch.get(library_id), everything)
            for library_id, trigger in batch.items():
                if self._stop_asked():
                    return
                await asyncio.to_thread(self._scan_one, library_id, trigger)

    def _stop_asked(self) -> bool:
        """The flag, read through a call: it is set by `stop()` while this task awaits, which a
        type checker narrowing the attribute across the loop's own condition cannot see."""
        return self._stopping

    def _library_ids(self) -> list[str]:
        """Every library there is now, for `request(None, ...)`. Empty, and logged, if the
        database cannot say - a pass that cannot list libraries scans none rather than ending the
        worker, which nothing would restart."""
        try:
            with self._session() as session:
                return [library.id for library in LibraryRepository(session).all()]
        except Exception:
            logger.exception("the libraries to scan could not be listed")
            return []

    def _scan_one(self, library_id: str, trigger: ScanTrigger) -> None:
        """One library, one session, one transaction - committed, or rolled back and logged.

        Runs in a worker thread. **Nothing escapes it**: a refusal is a warning and anything else
        a traceback, and the pass moves on to the next library either way.
        """
        session = self._sessions()
        try:
            library = LibraryRepository(session).by_id(library_id)
            if library is None:
                return
            if not library.roots:
                # Decided by the operator on 2026-09-14: a library with no paths is not a refusal
                # worth a warning on every refresh - it is what spec section 3.6 adds when no path
                # was given, and its view exists without a scan (`config.create_with_view`).
                return
            self._current = _Current(library_id, trigger)
            with self._providers(session) as providers:
                report = scan(
                    library,
                    session,
                    providers=providers,
                    prober=self._prober,
                    subtitle_prober=self._subtitle_prober,
                    progress=self._sink,
                )
            if self._stopping:
                raise _Stopped
            session.commit()
            logger.info("%s", report.summary())
        except _Stopped:
            session.rollback()
            logger.info("the scan of library %s was stopped and rolled back", library_id)
        except ScanRefusedError as refused:
            session.rollback()
            logger.warning("the scan of library %s was refused: %s", library_id, refused)
        except Exception:
            session.rollback()
            logger.exception("the scan of library %s failed", library_id)
        finally:
            self._current = None
            session.close()

    def _sink(self, progress: Progress) -> None:
        """Records how far the scan is, and is where a stop takes effect."""
        if self._stopping:
            raise _Stopped
        current = self._current
        if current is None:
            return
        position = _PHASES.index(progress.phase) + (progress.fraction or 0.0)
        self._current = _Current(
            current.library_id, current.trigger, 100.0 * position / len(_PHASES)
        )

    @contextmanager
    def _session(self) -> Iterator[OrmSession]:
        session = self._sessions()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def _providers(self, session: OrmSession) -> Iterator[list[object]]:
        """004's two providers, from `config.toml`'s `[providers]`, for one scan's session.

        Both are always handed over: one with no credentials sits out with its reason, and the scan
        report says which did (004 AC-9). Closed afterwards, because each holds an HTTP client.
        """
        configured = self._settings.providers
        contact = configured.musicbrainz_contact
        accesses = [
            RemoteAccess(
                tmdb.NAME,
                session=session,
                base_url=tmdb.BASE_URL,
                rate=tmdb.RATE,
                credentials=ProviderCredentials(api_key=configured.tmdb_api_key),
            ),
            RemoteAccess(
                musicbrainz.NAME,
                session=session,
                base_url=musicbrainz.BASE_URL,
                rate=musicbrainz.RATE,
                credentials=ProviderCredentials(contact=contact),
                headers={"User-Agent": musicbrainz.user_agent(contact, __version__)}
                if contact
                else {},
            ),
        ]
        try:
            yield [
                tmdb.TmdbProvider(
                    accesses[0],
                    artwork_root=self._paths.artwork,
                    country=configured.metadata_country,
                ),
                musicbrainz.MusicBrainzProvider(accesses[1]),
            ]
        finally:
            for access in accesses:
                access.close()


def _stronger(held: ScanTrigger | None, asked: ScanTrigger) -> ScanTrigger:
    return ScanTrigger.ADDED if ScanTrigger.ADDED in (held, asked) else ScanTrigger.REFRESH


__all__ = ["IDLE", "LibraryRefresh", "ScanTrigger", "Scanner"]
