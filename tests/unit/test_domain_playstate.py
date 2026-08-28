# SPDX-License-Identifier: GPL-3.0-or-later
"""The six-branch resolution and every transition, against pure functions.

The whole of feature 007's measured semantics is one module of functions from a `UserItemData` to
a `UserItemData`, so the findings that cost a probe to learn are asserted here - once, as a table -
rather than five times through five routes (007 plan section 8). Every row of spec section 3.7 and
every row of section 3.6's effects table has a case below, and the two boundaries are exercised at
the tick each side of them, which is the precision they were measured at.

What is deliberately *not* here: HTTP, a database, and a clock. `when` arrives as an argument, so
"the count moves at the start" is a test about arithmetic rather than about a route.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atrium.domain.playstate import (
    MAX_RESUME_PCT,
    MIN_RESUME_DURATION_SECONDS,
    MIN_RESUME_PCT,
    TICKS_PER_SECOND,
    Outcome,
    UserItemData,
    on_mark_played,
    on_mark_unplayed,
    on_report,
    on_start,
    on_stop_without_position,
    resolve,
)

#: A film: comfortably past the short-runtime floor, so the percentage branches are reachable.
HOUR = 3600 * TICKS_PER_SECOND
#: The 215-second track the probe measured OQ-6 on: under the floor, so it is never resumable.
TRACK = 215 * TICKS_PER_SECOND

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
EARLIER = datetime(2026, 3, 1, tzinfo=UTC)
IMPORTED = datetime(2019, 7, 4, tzinfo=UTC)


def at_floor(runtime: int) -> int:
    """The smallest position whose percentage reaches the floor - `ceil(runtime * 5 / 100)`."""
    return -(-runtime * MIN_RESUME_PCT // 100)


def at_ceiling(runtime: int) -> int:
    """The largest position not past the ceiling."""
    return runtime * MAX_RESUME_PCT // 100


# ------------------------------------------------------------------------------------------
# Spec section 3.7: the six branches (AC-12)
# ------------------------------------------------------------------------------------------

BRANCHES = [
    ("row 1 - a stop with no position at all", None, HOUR, Outcome.COMPLETED),
    ("row 2 - the runtime is unknown", HOUR // 2, None, Outcome.COMPLETED),
    ("row 2 - the runtime is zero, which is the same absence", HOUR // 2, 0, Outcome.COMPLETED),
    ("row 3 - below the floor", at_floor(HOUR) - 1, HOUR, Outcome.DISCARDED),
    ("row 4 - above the ceiling", at_ceiling(HOUR) + 1, HOUR, Outcome.COMPLETED),
    ("row 4 - within one second of the end", HOUR - TICKS_PER_SECOND, HOUR, Outcome.COMPLETED),
    ("row 5 - a short item stopped mid-way", TRACK // 2, TRACK, Outcome.COMPLETED),
    ("row 6 - the resumable case", HOUR // 2, HOUR, Outcome.RESUMABLE),
]


@pytest.mark.parametrize(
    "position,runtime,expected",
    [case[1:] for case in BRANCHES],
    ids=[case[0] for case in BRANCHES],
)
def test_ac12_every_branch_of_the_rule(
    position: int | None, runtime: int | None, expected: Outcome
) -> None:
    assert resolve(position, runtime) is expected


def test_the_floor_is_about_progress_and_the_short_rule_is_about_runtime() -> None:
    """Row 3 and row 5 are different rules, and conflating them is the mistake to catch.

    A short track sampled for a second is *discarded* - not played - while the same track stopped
    halfway is played. A server that read row 5 as "short items are always played" would mark an
    item watched because somebody pressed play and immediately pressed stop.
    """
    assert resolve(TRACK // 100, TRACK) is Outcome.DISCARDED
    assert resolve(TRACK // 2, TRACK) is Outcome.COMPLETED


# ------------------------------------------------------------------------------------------
# AC-13: the comparisons are strict, at tick precision
# ------------------------------------------------------------------------------------------


def test_ac13_the_first_tick_reaching_the_floor_keeps_its_position() -> None:
    assert resolve(at_floor(HOUR), HOUR) is Outcome.RESUMABLE
    assert resolve(at_floor(HOUR) - 1, HOUR) is Outcome.DISCARDED


def test_ac13_the_last_tick_not_past_the_ceiling_keeps_its_position() -> None:
    assert resolve(at_ceiling(HOUR), HOUR) is Outcome.RESUMABLE
    assert resolve(at_ceiling(HOUR) + 1, HOUR) is Outcome.COMPLETED


def test_the_boundaries_are_integer_arithmetic_not_a_percentage_in_floating_point() -> None:
    """A runtime whose five percent is not a whole number of ticks still lands on the tick.

    Computing `position / runtime * 100` and comparing against 5 puts this boundary a tick either
    side of where the reference has it, depending on the runtime - which is a difference nobody
    would find by reading, on one viewer in a thousand.
    """
    awkward = 3607 * TICKS_PER_SECOND + 7  # divisible by nothing convenient
    assert resolve(at_floor(awkward), awkward) is Outcome.RESUMABLE
    assert resolve(at_floor(awkward) - 1, awkward) is Outcome.DISCARDED
    assert resolve(at_ceiling(awkward), awkward) is Outcome.RESUMABLE
    assert resolve(at_ceiling(awkward) + 1, awkward) is Outcome.COMPLETED


def test_the_within_one_second_clause_changes_no_answer_under_these_thresholds() -> None:
    """Spec section 3.7 calls row 4's second clause "not redundant". Under the reference's own
    defaults it decides nothing, and the reason its justification gives is backwards.

    "For a long item, 90% can still be minutes from the end" is true and points the other way: a
    position within one second of the end of anything longer than ten seconds is *above* ninety
    percent, so the first clause has already fired. Below ten seconds the runtime floor (row 5)
    marks it played anyway. The clause is kept because the reference has it and because a
    deployment that lowered `MinResumeDurationSeconds` would give it something to decide - not
    because any request reaching this server can tell the difference.
    """

    def without_the_clause(position: int, runtime: int) -> Outcome:
        if position * 100 < runtime * MIN_RESUME_PCT:
            return Outcome.DISCARDED
        if position * 100 > runtime * MAX_RESUME_PCT:
            return Outcome.COMPLETED
        if runtime < MIN_RESUME_DURATION_SECONDS * TICKS_PER_SECOND:
            return Outcome.COMPLETED
        return Outcome.RESUMABLE

    runtimes = [1, 2, 5, 9, 10, 11, 60, 299, 300, 301, 3600, 7200]
    for seconds in runtimes:
        runtime = seconds * TICKS_PER_SECOND
        positions = {0, 1, runtime - 1, runtime, at_floor(runtime), at_ceiling(runtime)}
        positions |= {runtime - TICKS_PER_SECOND, runtime * 3 // 4, runtime // 2, runtime // 100}
        for position in sorted(p for p in positions if p >= 0):
            assert resolve(position, runtime) is without_the_clause(position, runtime), (
                f"the clause decided {seconds}s at {position} ticks"
            )


# ------------------------------------------------------------------------------------------
# Spec section 3.6: what each report does (AC-17, AC-18, AC-19)
# ------------------------------------------------------------------------------------------


def test_ac17_a_start_counts_the_play_and_un_marks_a_played_item() -> None:
    """The finding OQ-5 produced: the count moves at the beginning, and `Played` goes false."""
    watched = UserItemData(played=True, play_count=1, last_played_date=EARLIER)
    started = on_start(watched, NOW)
    assert (started.played, started.play_count, started.last_played_date) == (False, 2, NOW)


def test_a_start_does_not_write_the_position_it_carries() -> None:
    """Measured: a Start at 30% leaves the stored position where it was. The position is the
    progress reports' business, and a resume that a start could overwrite is one a client
    restarting playback would destroy."""
    resuming = UserItemData(playback_position_ticks=HOUR // 4)
    assert on_start(resuming, NOW).playback_position_ticks == HOUR // 4


def test_ac18_a_stop_with_a_position_does_not_count_and_one_without_counts_again() -> None:
    after_start = on_start(UserItemData(), NOW)
    assert on_report(after_start, HOUR // 2, HOUR).play_count == 1
    assert on_stop_without_position(after_start).play_count == 2


def test_a_positionless_stop_is_played_to_the_end() -> None:
    ended = on_stop_without_position(UserItemData(playback_position_ticks=HOUR // 2))
    assert (ended.played, ended.playback_position_ticks) == (True, 0)


def test_ac19_a_report_past_the_ceiling_marks_played_and_clears_the_position() -> None:
    """The rule is not stop-only: a progress at 95% does this mid-playback."""
    resumed = on_report(UserItemData(playback_position_ticks=HOUR // 2), at_ceiling(HOUR) + 1, HOUR)
    assert (resumed.played, resumed.playback_position_ticks) == (True, 0)


def test_ac10_a_report_older_than_the_stored_position_rewinds_it() -> None:
    """Last writer wins. A deliberate seek backwards arrives as exactly this report, and a guard
    against it pins every rewinding viewer at their furthest point."""
    forty = on_report(UserItemData(), HOUR * 40 // 100, HOUR)
    twenty = on_report(forty, HOUR * 20 // 100, HOUR)
    assert twenty.playback_position_ticks == HOUR * 20 // 100


def test_a_position_after_completion_coexists_with_played() -> None:
    """How "continue watching forever" is reachable on the reference's own path: the mid-range
    branch does not touch `Played`, so a resumable position lands on an item already played."""
    finished = on_report(UserItemData(), at_ceiling(HOUR) + 1, HOUR)
    again = on_report(finished, HOUR // 2, HOUR)
    assert (again.played, again.playback_position_ticks) == (True, HOUR // 2)


def test_a_report_below_the_floor_neither_keeps_a_position_nor_marks_played() -> None:
    sampled = on_report(UserItemData(playback_position_ticks=HOUR // 2), at_floor(HOUR) - 1, HOUR)
    assert (sampled.played, sampled.playback_position_ticks) == (False, 0)


def test_no_report_moves_the_last_played_date() -> None:
    """Only a start and the marks write it. A progress that refreshed it would make
    `LastPlayedDate` mean "last reported", which is what `LastPlaybackCheckIn` is for."""
    started = on_start(UserItemData(), NOW)
    assert on_report(started, HOUR // 2, HOUR).last_played_date == NOW
    assert on_stop_without_position(started).last_played_date == NOW


# ------------------------------------------------------------------------------------------
# Spec section 3.4: the marks (AC-3, AC-4)
# ------------------------------------------------------------------------------------------


def test_ac3_a_bare_mark_is_max_count_one_and_marking_twice_does_not_move_it() -> None:
    once = on_mark_played(UserItemData(), NOW)
    twice = on_mark_played(once, NOW)
    assert (once.play_count, twice.play_count) == (1, 1)
    assert (once.played, twice.played) == (True, True)


def test_ac3_a_bare_mark_resets_the_position_and_keeps_an_existing_date() -> None:
    resuming = UserItemData(playback_position_ticks=HOUR // 2, last_played_date=EARLIER)
    marked = on_mark_played(resuming, NOW)
    assert marked.playback_position_ticks == 0
    assert marked.last_played_date == EARLIER, "the mark moved a date it should have kept"


def test_ac3_only_the_dated_form_increments_and_its_date_wins() -> None:
    """The `datePlayed` form exists for imports: a scrobble backfill increments once per record."""
    counted = on_mark_played(UserItemData(play_count=3, last_played_date=NOW), NOW, IMPORTED)
    assert (counted.play_count, counted.last_played_date) == (4, IMPORTED)


def test_a_bare_mark_on_an_untouched_row_sets_the_date_it_was_given() -> None:
    assert on_mark_played(UserItemData(), NOW).last_played_date == NOW


def test_ac4_unmarking_clears_played_the_count_the_position_and_the_date() -> None:
    lived_in = UserItemData(
        played=True, play_count=4, playback_position_ticks=HOUR // 2, last_played_date=NOW
    )
    cleared = on_mark_unplayed(lived_in)
    assert (cleared.played, cleared.play_count, cleared.playback_position_ticks) == (False, 0, 0)
    assert cleared.last_played_date is None


# ------------------------------------------------------------------------------------------
# What no transition may touch
# ------------------------------------------------------------------------------------------

TRANSITIONS = {
    "on_start": lambda data: on_start(data, NOW),
    "on_report - resumable": lambda data: on_report(data, HOUR // 2, HOUR),
    "on_report - completed": lambda data: on_report(data, HOUR, HOUR),
    "on_report - discarded": lambda data: on_report(data, 1, HOUR),
    "on_stop_without_position": on_stop_without_position,
    "on_mark_played": lambda data: on_mark_played(data, NOW),
    "on_mark_played - dated": lambda data: on_mark_played(data, NOW, IMPORTED),
    "on_mark_unplayed": on_mark_unplayed,
}


@pytest.mark.parametrize("transition", list(TRANSITIONS), ids=list(TRANSITIONS))
def test_no_played_transition_touches_the_favourite_flag(transition: str) -> None:
    """The favourite is the user's statement about the item and belongs to no playback at all
    (spec section 3.3). It is one `replace()` away from being cleared by every one of these."""
    assert TRANSITIONS[transition](UserItemData(is_favorite=True)).is_favorite is True


@pytest.mark.parametrize("transition", list(TRANSITIONS), ids=list(TRANSITIONS))
def test_every_transition_returns_a_new_record(transition: str) -> None:
    """Frozen and replaced rather than mutated: a caller holding the row it loaded can compare."""
    before = UserItemData(played=True, play_count=2, playback_position_ticks=HOUR // 3)
    after = TRANSITIONS[transition](before)
    assert before == UserItemData(played=True, play_count=2, playback_position_ticks=HOUR // 3)
    assert after is not before
