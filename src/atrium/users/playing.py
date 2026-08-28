# SPDX-License-Identifier: GPL-3.0-or-later
"""What is playing right now, per session - in memory, and deliberately nowhere else.

`NowPlayingItem` and `PlayState` change several times a minute, die with the session, and are
lost by the reference's own restart. What has to survive is the resume position, and that is a
row written on every report (007 plan section 6.1), so this holds no database handle and persists
nothing: a restart costs exactly what the reference's costs, which is the extrapolation since each
session's last report.

**Two decisions here are measurements rather than taste.**

**A report replaces the record whole.** After a start carrying `CanSeek: true` and
`VolumeLevel: 80`, a progress omitting both reads back `CanSeek: false` and no `VolumeLevel` at
all - so `start` and `update` are the same operation, and merging would invent a `PlayState` no
reference server sends `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`.

**The position moves between reports.** The reference runs a per-session one-second timer that
extrapolates the unpaused position, and a `/Sessions` poller watches it advance; the reap then
commits the extrapolated value, which is why a session silent for 8.6 minutes stored 48.5% after
reporting 40% `[source: MediaBrowser.Controller/Session/SessionInfo.cs:23, 373-451 @ v10.11.11]`.
The observable is the **value**, not the timer, so it is computed on read: last reported plus
unpaused elapsed, capped at the runtime. Same wire, no alarm per viewer (plan section 10).

Time arrives through two injected callables - a wall clock for what a client sees and a monotonic
one for elapsed - so every test of the reaper and the extrapolation runs without sleeping, and a
clock stepped backwards by NTP cannot make a position go backwards.

See specs/007-user-data-and-playstate/spec.md section 3.8 and plan sections 6.4 and 6.5.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from atrium.compat.dates import utc_now
from atrium.domain.playstate import TICKS_PER_SECOND

logger = logging.getLogger(__name__)

#: How often the sweep runs, and how long a session may be silent before it is stopped. Both are
#: the reference's own constants, named once (spec section 3.8): a sweep every five minutes for
#: sessions whose last check-in is more than five minutes old, which measured at 8.6 minutes.
SWEEP_INTERVAL_SECONDS = 300.0
SILENCE_THRESHOLD = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class PlaybackReport:
    """One report's contents, as the routes hand them over.

    Every field is optional because every field on the wire is: the three reporting endpoints
    accept bodies that carry almost nothing, and what a report omits is what `PlayState` stops
    showing.
    """

    item_id: str
    runtime_ticks: int | None = None
    position_ticks: int | None = None
    is_paused: bool = False
    can_seek: bool = False
    is_muted: bool = False
    volume_level: int | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    media_source_id: str | None = None
    play_method: str | None = None
    play_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class PlayingNow:
    """What a session is playing, with the position already extrapolated to *now*.

    A snapshot rather than a handle: `/Sessions` serialises it, the reaper commits it, and neither
    can hold something that changes underneath them.
    """

    item_id: str
    position_ticks: int
    is_paused: bool
    can_seek: bool
    is_muted: bool
    volume_level: int | None
    audio_stream_index: int | None
    subtitle_stream_index: int | None
    media_source_id: str | None
    play_method: str | None
    play_session_id: str | None
    runtime_ticks: int | None
    last_check_in: datetime


@dataclass(frozen=True, slots=True)
class _Playing:
    """The stored form: the report as it arrived, plus when it did."""

    report: PlaybackReport
    reported_at: float
    checked_in: datetime


class NowPlayingRegistry:
    """Live playback per session. One per instance, like `SessionRegistry`, so two servers in one
    process - which the suite builds constantly - cannot reap each other's sessions."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        commit: Callable[[str, PlayingNow], None] | None = None,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
        silence: timedelta = SILENCE_THRESHOLD,
    ) -> None:
        self._playing: dict[str, _Playing] = {}
        self._clock = clock
        self._monotonic = monotonic
        #: Wired in `server.py`, and it routes through the same function a real `Stopped` uses -
        #: one code path for "a stop arrived" and "we gave up waiting" (plan section 6.5).
        self.commit = commit
        self.sweep_interval = sweep_interval
        self.silence = silence

    # -- reports ---------------------------------------------------------------------------

    def start(self, session_id: str, report: PlaybackReport) -> None:
        """Playback began. The record is written whole, replacing whatever was there."""
        self._playing[session_id] = _Playing(
            report=report, reported_at=self._monotonic(), checked_in=self._clock()
        )

    def update(self, session_id: str, report: PlaybackReport) -> None:
        """A progress report - **the same operation as `start`**, because the reference's
        `PlayState` is the last report and not an accumulation of them.

        A progress that arrives with no start before it establishes the record rather than being
        dropped: clients are killed and restarted, and a report that landed is a report.
        """
        self.start(session_id, report)

    def clear(self, session_id: str) -> PlayingNow | None:
        """Playback stopped. The final snapshot comes back so a caller can commit it."""
        final = self.snapshot(session_id)
        self._playing.pop(session_id, None)
        return final

    # -- reads -----------------------------------------------------------------------------

    def snapshot(self, session_id: str) -> PlayingNow | None:
        """What this session is playing *now*, position included."""
        held = self._playing.get(session_id)
        return None if held is None else self._extrapolated(held)

    def check_in(self, session_id: str) -> datetime | None:
        """The live `LastPlaybackCheckIn`, which is newer than the flushed one between writes."""
        held = self._playing.get(session_id)
        return None if held is None else held.checked_in

    def playing(self) -> dict[str, PlayingNow]:
        """Every playing session, for a `/Sessions` response that lists more than one."""
        return {session_id: self._extrapolated(held) for session_id, held in self._playing.items()}

    def _extrapolated(self, held: _Playing) -> PlayingNow:
        """Last reported, plus the unpaused wall clock since, capped at the runtime.

        A paused session's position is frozen at its report - the reference's ticker does not
        advance one - and a position is never carried past the end of the item, because a resume
        point beyond the runtime is one no client can seek to.
        """
        report = held.report
        position = report.position_ticks or 0
        if not report.is_paused:
            elapsed = max(self._monotonic() - held.reported_at, 0.0)
            position += int(elapsed * TICKS_PER_SECOND)
        if report.runtime_ticks:
            position = min(position, report.runtime_ticks)
        return PlayingNow(
            item_id=report.item_id,
            position_ticks=position,
            is_paused=report.is_paused,
            can_seek=report.can_seek,
            is_muted=report.is_muted,
            volume_level=report.volume_level,
            audio_stream_index=report.audio_stream_index,
            subtitle_stream_index=report.subtitle_stream_index,
            media_source_id=report.media_source_id,
            play_method=report.play_method,
            play_session_id=report.play_session_id,
            runtime_ticks=report.runtime_ticks,
            last_check_in=held.checked_in,
        )

    # -- the sweep -------------------------------------------------------------------------

    def reap(self, older_than: timedelta | None = None) -> list[tuple[str, PlayingNow]]:
        """Stop every session that has been silent too long, and return what they were playing.

        The record is removed here, so a commit that fails loses a position rather than reaping
        the same session for ever - which is the trade the reference makes by stopping the session
        first as well.
        """
        threshold = self.silence if older_than is None else older_than
        cutoff = self._clock() - threshold
        stale = [
            session_id for session_id, held in self._playing.items() if held.checked_in <= cutoff
        ]
        return [(session_id, found) for session_id in stale if (found := self.clear(session_id))]

    def sweep(self) -> int:
        """One pass: reap, and commit each through the caller's stop path. Returns how many."""
        reaped = self.reap()
        if self.commit is not None:
            for session_id, playing in reaped:
                self.commit(session_id, playing)
        return len(reaped)

    async def run(self) -> None:
        """Sweep on the interval until cancelled, started by the application factory.

        The commit goes to a thread because it is blocking database work and this is the event
        loop (ADR-0002), and a failure is logged rather than allowed to kill the task - nothing
        else would restart it, and the next sweep retries the sessions that are still stale.
        """
        while True:
            await asyncio.sleep(self.sweep_interval)
            try:
                await asyncio.to_thread(self.sweep)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("reaping silent playback sessions failed; retrying next sweep")


__all__ = [
    "SILENCE_THRESHOLD",
    "SWEEP_INTERVAL_SECONDS",
    "NowPlayingRegistry",
    "PlaybackReport",
    "PlayingNow",
]
