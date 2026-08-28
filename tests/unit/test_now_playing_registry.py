# SPDX-License-Identifier: GPL-3.0-or-later
"""Live playback: the position that moves, the record that is replaced, and the sweep.

Every test here injects both clocks, so a reap after six minutes of silence costs no seconds and
an extrapolation over ninety of them is arithmetic. Sleeping would make this file the slowest in
the suite and would still assert less: a real clock cannot be stepped to the tick either side of
a threshold.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atrium.domain.playstate import TICKS_PER_SECOND
from atrium.users.playing import (
    SILENCE_THRESHOLD,
    NowPlayingRegistry,
    PlaybackReport,
    PlayingNow,
)

HOUR = 3600 * TICKS_PER_SECOND
SESSION = "session-one"
ITEM = "a" * 32


class Clocks:
    """A wall clock and a monotonic one that move together, by hand."""

    def __init__(self) -> None:
        self.wall = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        self.elapsed = 1000.0

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.elapsed += seconds


@pytest.fixture
def clocks() -> Clocks:
    return Clocks()


@pytest.fixture
def registry(clocks: Clocks) -> NowPlayingRegistry:
    return NowPlayingRegistry(clock=lambda: clocks.wall, monotonic=lambda: clocks.elapsed)


def report(**overrides: object) -> PlaybackReport:
    fields: dict[str, object] = {
        "item_id": ITEM,
        "runtime_ticks": HOUR,
        "position_ticks": 0,
        "can_seek": True,
        "volume_level": 80,
    }
    fields.update(overrides)
    return PlaybackReport(**fields)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------
# The position that moves between reports (spec section 3.8)
# ------------------------------------------------------------------------------------------


def test_the_position_advances_with_the_wall_clock(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    registry.start(SESSION, report(position_ticks=10 * 60 * TICKS_PER_SECOND))
    clocks.advance(90)
    playing = registry.snapshot(SESSION)
    assert playing is not None
    assert playing.position_ticks == (10 * 60 + 90) * TICKS_PER_SECOND


def test_a_paused_session_does_not_move(registry: NowPlayingRegistry, clocks: Clocks) -> None:
    """The reference's ticker does not advance a paused session, and a client that pauses for an
    hour must not come back to a position an hour further on."""
    registry.update(SESSION, report(position_ticks=HOUR // 4, is_paused=True))
    clocks.advance(3600)
    playing = registry.snapshot(SESSION)
    assert playing is not None and playing.position_ticks == HOUR // 4


def test_the_position_is_capped_at_the_runtime(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    """A resume point past the end is one no client can seek to."""
    registry.start(SESSION, report(position_ticks=HOUR - 10 * TICKS_PER_SECOND))
    clocks.advance(600)
    playing = registry.snapshot(SESSION)
    assert playing is not None and playing.position_ticks == HOUR


def test_an_unknown_runtime_is_not_a_cap(registry: NowPlayingRegistry, clocks: Clocks) -> None:
    registry.start(SESSION, report(runtime_ticks=None, position_ticks=0))
    clocks.advance(120)
    playing = registry.snapshot(SESSION)
    assert playing is not None and playing.position_ticks == 120 * TICKS_PER_SECOND


def test_nothing_playing_is_not_an_error(registry: NowPlayingRegistry) -> None:
    assert registry.snapshot("never-played") is None
    assert registry.check_in("never-played") is None
    assert registry.clear("never-played") is None


# ------------------------------------------------------------------------------------------
# The record is replaced, never merged (spec section 3.6)
# ------------------------------------------------------------------------------------------


def test_a_progress_that_omits_a_field_clears_it(registry: NowPlayingRegistry) -> None:
    """The measured behaviour, and the reason `update` is `start`: after a start carrying
    `CanSeek: true` and `VolumeLevel: 80`, a bare progress reads back `CanSeek: false` and no
    volume at all."""
    registry.start(SESSION, report())
    registry.update(SESSION, PlaybackReport(item_id=ITEM, position_ticks=HOUR // 3))
    playing = registry.snapshot(SESSION)
    assert playing is not None
    assert playing.can_seek is False
    assert playing.volume_level is None


def test_a_progress_with_no_start_before_it_establishes_the_record(
    registry: NowPlayingRegistry,
) -> None:
    """Clients are killed and restarted, and a report that landed is a report."""
    registry.update(SESSION, report(position_ticks=HOUR // 5))
    assert registry.snapshot(SESSION) is not None


def test_the_check_in_is_the_moment_of_the_last_report(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    registry.start(SESSION, report())
    first = clocks.wall
    clocks.advance(30)
    assert registry.check_in(SESSION) == first
    registry.update(SESSION, report())
    assert registry.check_in(SESSION) == clocks.wall


def test_clearing_answers_the_final_snapshot(registry: NowPlayingRegistry, clocks: Clocks) -> None:
    registry.start(SESSION, report(position_ticks=HOUR // 2))
    clocks.advance(10)
    final = registry.clear(SESSION)
    assert final is not None and final.position_ticks == HOUR // 2 + 10 * TICKS_PER_SECOND
    assert registry.snapshot(SESSION) is None


def test_two_sessions_of_one_user_are_independent(registry: NowPlayingRegistry) -> None:
    registry.start(SESSION, report(position_ticks=HOUR // 4))
    registry.start("other", report(position_ticks=HOUR // 2))
    assert set(registry.playing()) == {SESSION, "other"}
    registry.clear(SESSION)
    assert set(registry.playing()) == {"other"}


# ------------------------------------------------------------------------------------------
# The sweep (spec section 3.8, AC-15)
# ------------------------------------------------------------------------------------------


def test_a_session_silent_past_the_threshold_is_reaped(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    registry.start(SESSION, report(position_ticks=HOUR * 40 // 100))
    clocks.advance(SILENCE_THRESHOLD.total_seconds() + 60)
    [(session_id, _playing)] = registry.reap()
    assert session_id == SESSION
    assert registry.snapshot(SESSION) is None


def test_the_reaped_position_carries_the_silence(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    """The measurement that corrected AC-15: 40% reported, silence, and the *extrapolated*
    position is what gets committed - 8.6 minutes richer on the reference."""
    reported = HOUR * 40 // 100
    registry.start(SESSION, report(position_ticks=reported))
    clocks.advance(360)
    [(_, playing)] = registry.reap()
    assert playing.position_ticks == reported + 360 * TICKS_PER_SECOND


def test_a_session_still_reporting_is_not_reaped(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    registry.start(SESSION, report())
    clocks.advance(240)
    assert registry.reap() == []
    clocks.advance(240)
    registry.update(SESSION, report())  # a check-in resets the silence
    clocks.advance(240)
    assert registry.reap() == []


def test_the_threshold_is_the_reference_s_five_minutes(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    """One second either side of it, which is what says the constant is used rather than
    approximated."""
    registry.start(SESSION, report())
    clocks.advance(SILENCE_THRESHOLD.total_seconds() - 1)
    assert registry.reap() == []
    clocks.advance(2)
    assert len(registry.reap()) == 1


def test_a_paused_session_is_reaped_at_its_reported_position(
    registry: NowPlayingRegistry, clocks: Clocks
) -> None:
    """Somebody who paused and walked away resumes where they paused, not where the clock got to."""
    registry.start(SESSION, report(position_ticks=HOUR // 3, is_paused=True))
    clocks.advance(600)
    [(_, playing)] = registry.reap()
    assert playing.position_ticks == HOUR // 3


def test_the_sweep_commits_every_reaped_session(clocks: Clocks) -> None:
    committed: list[tuple[str, PlayingNow]] = []
    registry = NowPlayingRegistry(
        clock=lambda: clocks.wall,
        monotonic=lambda: clocks.elapsed,
        commit=lambda session_id, playing: committed.append((session_id, playing)),
    )
    registry.start(SESSION, report(position_ticks=HOUR // 4))
    registry.start("other", report(position_ticks=HOUR // 2))
    clocks.advance(600)

    assert registry.sweep() == 2
    assert {session_id for session_id, _ in committed} == {SESSION, "other"}
    assert registry.sweep() == 0, "a reaped session was swept twice"


def test_a_sweep_with_nothing_to_do_commits_nothing(clocks: Clocks) -> None:
    committed: list[str] = []
    registry = NowPlayingRegistry(
        clock=lambda: clocks.wall,
        monotonic=lambda: clocks.elapsed,
        commit=lambda session_id, _playing: committed.append(session_id),
    )
    registry.start(SESSION, report())
    clocks.advance(10)
    assert registry.sweep() == 0
    assert committed == []
