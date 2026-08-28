# SPDX-License-Identifier: GPL-3.0-or-later
"""Every user-data transition this server performs, as functions of their arguments.

The measured semantics of feature 007 live here and nowhere else: the six-branch resolution a
reported position goes through, the count that moves at *start*, the bare mark that only
guarantees the count is non-zero, the positionless stop that counts a second time. Each is a
function from a `UserItemData` to a `UserItemData` - no clock, no database, no request - so the
findings that cost a probe to learn are asserted against a table rather than through five routes
(007 plan sections 5 and 8).

**Why these are worth isolating:** every one of them contradicted a plausible reading. A play is
counted when playback *starts*, and starting a played item un-marks it; a bare
`POST /UserPlayedItems` is `max(count, 1)` rather than an increment; an older progress report
rewinds the stored position rather than being ignored; and the completion rule runs on progress
reports, not only on stops, so an item can be marked played while it is still playing.
`[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`

The thresholds are the reference's **defaults** rather than protocol - server configuration a
deployment can change - and Atrium adopts them as constants because a client cannot ask what they
are and every analysed one assumes these
(specs/007-user-data-and-playstate/spec.md section 3.7).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Final

#: Ticks of 100 nanoseconds, the internal unit everywhere (architecture.md section 4). Spelled
#: again here rather than imported from `compat/ticks`: `domain/` imports the standard library and
#: other domain modules and nothing else, asserted by tests/unit/test_import_directions.py.
TICKS_PER_SECOND: Final = 10_000_000

#: Below this fraction of the runtime a reported position is not worth remembering.
MIN_RESUME_PCT: Final = 5
#: Above it, the item is finished rather than paused.
MAX_RESUME_PCT: Final = 90
#: An item shorter than this has no meaningful resume point at all, whatever the fraction says.
MIN_RESUME_DURATION_SECONDS: Final = 300


@dataclass(frozen=True, slots=True)
class UserItemData:
    """The requesting user's state for one item. Always present, never null (behaviours 2.1).

    For a container the `played` here is a **rollup, not the stored row**: the reference reports a
    series as played exactly when nothing under it is left unplayed, and sends the count of what
    is left as `UnplayedItemCount` on every bare container row
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. The query layer
    computes both; the stored row still supplies the favourite flag and the position.

    **Defined here rather than beside the query that reads it**, since 007: the transitions below
    are the only things that decide what these fields mean, and a record whose owner is a SQL
    module is a record every writer has to import storage to touch.
    """

    is_favorite: bool = False
    played: bool = False
    play_count: int = 0
    playback_position_ticks: int = 0
    last_played_date: datetime | None = None
    #: Visible file-backed descendants without a played row. None for anything that is not a
    #: tree container, so the DTO can tell "no rollup applies" from "nothing left".
    unplayed_count: int | None = None


class Outcome(Enum):
    """What a resolved position decided. Three answers, not two.

    `RESUMABLE` and `COMPLETED` are the obvious pair; `DISCARDED` is the one a rule written from
    intuition misses - a position below the floor is thrown away **without** marking anything
    played, which is what keeps a film somebody sampled for a minute out of "continue watching"
    and out of "watched" at the same time.
    """

    DISCARDED = "discarded"
    RESUMABLE = "resumable"
    COMPLETED = "completed"


def resolve(position_ticks: int | None, runtime_ticks: int | None) -> Outcome:
    """Rows 1 to 6 of spec section 3.7, in the order the reference applies them.

    Ordered, not independent: a two-minute clip stopped at 1% is `DISCARDED` by the floor before
    the short-runtime branch can call it played, and a position past the ceiling is `COMPLETED`
    before the short-runtime branch is reached.

    **The comparisons are strict, and that was measured at tick precision**: the first tick whose
    percentage reaches five keeps its position and the tick below it does not; the last tick not
    past ninety keeps its position and the tick above it marks the item played. Compared as
    integers - `position * 100` against `runtime * pct` - because a percentage computed in
    floating point puts the boundary a tick either side of where the reference has it, and the
    difference is one resume position per viewer who pauses exactly there.
    `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`
    """
    if position_ticks is None:
        # Row 1: a stop carrying no position means *played to the end* - P becomes R, which every
        # branch below then resolves the same way. Only a stop reaches this; a progress with no
        # position leaves the stored one alone and never calls here.
        return Outcome.COMPLETED
    if not runtime_ticks:
        # Row 2: nothing to be a fraction of. The reference marks it played rather than keeping a
        # position it could never render a progress bar for.
        return Outcome.COMPLETED
    if position_ticks * 100 < runtime_ticks * MIN_RESUME_PCT:
        return Outcome.DISCARDED  # row 3
    if (
        position_ticks * 100 > runtime_ticks * MAX_RESUME_PCT
        or runtime_ticks - position_ticks <= TICKS_PER_SECOND
    ):
        # Row 4, and its second clause is not redundant: for a long item ninety percent can still
        # be minutes from the end, and stopping in the final second is completion whatever the
        # fraction says.
        return Outcome.COMPLETED
    if runtime_ticks < MIN_RESUME_DURATION_SECONDS * TICKS_PER_SECOND:
        # Row 5, and it is about the item's *runtime*, not the position: a track stopped halfway
        # is played, not resumable. Measured on a 215-second track (OQ-6).
        return Outcome.COMPLETED
    return Outcome.RESUMABLE  # row 6


def on_start(data: UserItemData, when: datetime) -> UserItemData:
    """A `Playing` report: the play is counted **here**, at the start.

    And `played` goes **false**: starting an item that was watched un-marks it until it completes
    again, which is what makes a second viewing look like a viewing rather than like nothing. The
    position is untouched - a `Start` carrying one measured as not written at all.
    """
    return replace(
        data,
        played=False,
        play_count=data.play_count + 1,
        last_played_date=when,
    )


def on_report(
    data: UserItemData, position_ticks: int | None, runtime_ticks: int | None
) -> UserItemData:
    """A position-bearing report - a progress, or a stop that carried one.

    No count change: the play was counted at the start. `played` is only ever set, never cleared,
    which is how a position reported *after* completion coexists with `Played: true` - the
    mid-range branch does not touch it.
    """
    outcome = resolve(position_ticks, runtime_ticks)
    if outcome is Outcome.RESUMABLE:
        return replace(data, playback_position_ticks=position_ticks or 0)
    if outcome is Outcome.COMPLETED:
        return replace(data, played=True, playback_position_ticks=0)
    return replace(data, playback_position_ticks=0)


def on_stop_without_position(data: UserItemData) -> UserItemData:
    """A `Stopped` carrying no position: played to the end, and counted **again**.

    Clients send this when playback ends naturally, so a start-to-finish viewing measures
    `PlayCount: 2` - once at the start and once here. Reproduced rather than corrected: a client
    that shows the count is showing the reference's count.
    """
    return replace(data, played=True, play_count=data.play_count + 1, playback_position_ticks=0)


def on_mark_played(
    data: UserItemData, when: datetime, date_played: datetime | None = None
) -> UserItemData:
    """`POST /UserPlayedItems`, whose optional date changes more than the date.

    A bare mark is `max(count, 1)` - marking twice leaves it at one - and keeps an existing
    `LastPlayedDate` rather than moving it. The dated form is for imports: a scrobble backfill
    increments once per record, and the date it carries wins.
    """
    if date_played is None:
        return replace(
            data,
            played=True,
            play_count=max(data.play_count, 1),
            playback_position_ticks=0,
            last_played_date=data.last_played_date or when,
        )
    return replace(
        data,
        played=True,
        play_count=data.play_count + 1,
        playback_position_ticks=0,
        last_played_date=date_played,
    )


def on_mark_unplayed(data: UserItemData) -> UserItemData:
    """`DELETE /UserPlayedItems`: all four fields cleared, and the favourite left alone."""
    return replace(
        data,
        played=False,
        play_count=0,
        playback_position_ticks=0,
        last_played_date=None,
    )


__all__ = [
    "MAX_RESUME_PCT",
    "MIN_RESUME_DURATION_SECONDS",
    "MIN_RESUME_PCT",
    "TICKS_PER_SECOND",
    "Outcome",
    "UserItemData",
    "on_mark_played",
    "on_mark_unplayed",
    "on_report",
    "on_start",
    "on_stop_without_position",
    "resolve",
]
