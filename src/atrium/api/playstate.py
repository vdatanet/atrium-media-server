# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `PlaystateController`: the played pair, and the three playback reports.

## `POST` and `DELETE /UserPlayedItems/{itemId}`

Both answer the item's updated `UserData`, and the `POST` takes one optional query parameter,
`datePlayed`, which changes more than the date:

* **A bare mark is `max(count, 1)`.** Marking twice leaves the count at one, keeps an existing
  `LastPlayedDate` and resets the position to zero. The count belongs to *playback* (007 spec
  section 3.6), and this route only guarantees it is non-zero.
* **The dated form increments**, once per record, and its date wins. It exists for imports - a
  scrobble backfill - which is why it is the only form that moves a count nobody watched.

`[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`

**A container marks its leaves and never its own row.** Marking a season played writes every
episode's row and leaves the season's at zero: the season reads `Played: true` because its
subtree does, which 005's rollup already computes. Measured, and the sweep reaches through
seasons to episodes, so "mark the series watched" works
`[source: MediaBrowser.Controller/Entities/Folder.cs:1730-1786 @ v10.11.11]`.

Which items sweep is a **type** question, not a "has children" one: the reference's `Folder`
subclasses sweep and its plain `BaseItem`s write their own row, and Atrium's `IN_THE_TREE`
minus `FILE_BACKED` is that same set - `MusicArtist` sweeps, a `Genre` does not
`[source: MediaBrowser.Controller/Entities/Audio/MusicArtist.cs:27,
MediaBrowser.Controller/Entities/Genre.cs:18 @ v10.11.11]`. Reading it off the *result* of the
sweep instead would mark an emptied season played, which is the one shape where the reference
writes nothing at all.

## `POST /Sessions/Playing`, `/Sessions/Playing/Progress` and `/Sessions/Playing/Stopped`

`204` from all three, with an empty body, **including for an item id that names nothing**: these
arrive over unreliable networks from clients that crash, and a report for an item removed
mid-playback is not worth failing - the client could not act on the failure anyway.

Leniency starts **after the body binds**, which is where the measured floor sits: a body that is
not JSON, or an `ItemId` that is not a GUID at all, is the validation `400`; a `Stopped` carrying
a **negative** position is the one refusal past binding, `text/plain` with the fixed
`Error processing request.` (behaviours section 1.11's controller shape). An *absent* `ItemId`
binds and skips.

**A report binds to the caller's session, not to a session it names.** Whatever `PlaySessionId`
a body carries names the playback rather than the session; the session is the authenticated
device `[source: Jellyfin.Api/Controllers/PlaystateController.cs:199-260 @ v10.11.11]`.

**What each report does to the stored row** is 007 spec section 3.6's effects table, and it lives
in `domain/playstate.py` rather than here: the play is counted at the **start** (which also sets
`Played` to false), a position-bearing report resolves through the six-branch rule whether it is a
progress or a stop, a positionless stop means played-to-the-end and counts a second time, and a
`Failed: true` stop records nothing at all - though the start that preceded it keeps its effects.

See specs/007-user-data-and-playstate/spec.md sections 3.4, 3.6 and 3.7, and plan sections 6.1
and 6.2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from atrium.api.deps import (
    get_playing,
    get_registry,
    get_sessions,
    get_state,
    require_user,
)
from atrium.api.item_dto import BuildContext, Width, user_data_dto
from atrium.api.item_models import UserItemDataDto
from atrium.api.items import effective_user
from atrium.compat.dates import WireDateTime, utc_now
from atrium.compat.errors import NotFoundError, controller_error
from atrium.compat.guids import WireGuid
from atrium.compat.model import AtriumModel
from atrium.compat.ticks import WireTicks
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository
from atrium.db.repositories import UserDataRepository, UserRepository
from atrium.domain.items import FILE_BACKED, IN_THE_TREE, ItemType
from atrium.domain.playstate import (
    on_mark_played,
    on_mark_unplayed,
    on_report,
    on_start,
    on_stop_without_position,
)
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User
from atrium.users.playing import PlaybackReport

router = APIRouter(tags=["Playstate"])


def _sweeps(kind: ItemType) -> bool:
    """Whether marking this item marks the things beneath it instead of itself.

    The tree's containers do; files and by-name rows do not. See the module docstring for why
    this is asked of the type rather than of the subtree.
    """
    return kind in IN_THE_TREE and kind not in FILE_BACKED


def _mark(
    request: Request,
    caller: User,
    item_id: str,
    user_id: str | None,
    *,
    played: bool,
    date_played: datetime | None = None,
) -> UserItemDataDto:
    """Load, apply the transition, store - once for a leaf, once per leaf for a container.

    The item resolves through the same visible-item lookup `GET /Items/{itemId}` uses, so an
    unknown item and an invisible one are the identical `404`, and the answer is **re-read** after
    the writes rather than assembled from them: for a container the response's
    `UnplayedItemCount` is a rollup that only exists once the leaves are written, in this same
    transaction (plan section 6.2).
    """
    state = get_state(request)
    when = utc_now()

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, user_id)
        repository = ItemQueryRepository(opened)
        page = repository.run(ItemQuery(user=target, ids=(item_id,), limit=1, count=False))
        if not page.items:
            raise NotFoundError
        found = page.items[0]

        targets = (
            repository.leaf_descendants(item_id, target) if _sweeps(found.item.type) else (item_id,)
        )
        data = UserDataRepository(opened)
        for key in targets:
            stored = data.get(target.id, key)
            data.put(
                target.id,
                key,
                on_mark_played(stored, when, date_played) if played else on_mark_unplayed(stored),
            )

        refreshed = repository.run(
            ItemQuery(user=target, ids=(item_id,), limit=1, count=False)
        ).items[0]
        answered = user_data_dto(
            refreshed, BuildContext(server_id=state.server_id, width=Width.FULL)
        )
    assert answered is not None  # noqa: S101 - enable_user_data is not settable on this path
    return answered


@router.post("/UserPlayedItems/{itemId}")
async def mark_played_item(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    userId: WireGuid | None = None,  # noqa: N803
    datePlayed: WireDateTime | None = None,  # noqa: N803
) -> UserItemDataDto:
    """`MarkPlayedItem` `[spec: MarkPlayedItem]`.

    `datePlayed` is typed rather than parsed by hand, which is what makes `datePlayed=banana` the
    measured validation `400` naming the parameter instead of a mark that silently ignored it.
    """
    return _mark(request, caller, itemId, userId, played=True, date_played=datePlayed)


@router.delete("/UserPlayedItems/{itemId}")
async def mark_unplayed_item(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803
    userId: WireGuid | None = None,  # noqa: N803
) -> UserItemDataDto:
    """`MarkUnplayedItem` `[spec: MarkUnplayedItem]`: the same sweep, back the other way."""
    return _mark(request, caller, itemId, userId, played=False)


# ------------------------------------------------------------------------------------------------
# The three reports (007 spec section 3.6)
# ------------------------------------------------------------------------------------------------


class PlaybackStartInfo(AtriumModel):
    """`[spec: PlaybackStartInfo]`, and **every field is optional** - which is not laxity but the
    measured shape: the reference binds this body and then reads what is there, so a client that
    sends four properties is a client that reported four properties."""

    item_id: WireGuid | None = None
    media_source_id: str | None = None
    play_session_id: str | None = None
    play_method: str | None = None
    position_ticks: WireTicks | None = None
    can_seek: bool = False
    is_paused: bool = False
    is_muted: bool = False
    volume_level: int | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None


class PlaybackProgressInfo(PlaybackStartInfo):
    """`[spec: PlaybackProgressInfo]`: the start's fields, and **`MediaSourceId` is not required**.

    Emby requires it here and Jellyfin does not, so a server that refused without it would
    silently lose the resume positions of every client written against the Jellyfin dialect
    `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`.
    """


class PlaybackStopInfo(AtriumModel):
    """`[spec: PlaybackStopInfo]`. `Failed` is the one field that changes what the report means."""

    item_id: WireGuid | None = None
    media_source_id: str | None = None
    play_session_id: str | None = None
    position_ticks: WireTicks | None = None
    failed: bool = False


def _reported(body: PlaybackStartInfo, item: HydratedItem) -> PlaybackReport:
    """The wire body as the registry holds it, with the runtime the extrapolation needs."""
    return PlaybackReport(
        item_id=item.id,
        runtime_ticks=item.metadata.runtime_ticks,
        position_ticks=body.position_ticks,
        is_paused=body.is_paused,
        can_seek=body.can_seek,
        is_muted=body.is_muted,
        volume_level=body.volume_level,
        audio_stream_index=body.audio_stream_index,
        subtitle_stream_index=body.subtitle_stream_index,
        media_source_id=body.media_source_id,
        play_method=body.play_method,
        play_session_id=body.play_session_id,
    )


def record_stop(
    data: UserDataRepository,
    user_id: str,
    item_key: str,
    position_ticks: int | None,
    runtime_ticks: int | None,
) -> None:
    """Playback ended: at a position, or at the end when none was reported.

    **The reaper calls this too** (plan section 6.5), which is the point of it being a function:
    "a stop arrived" and "we gave up waiting" resolve through one code path, so they cannot drift
    apart into two answers for the same viewer.
    """
    stored = data.get(user_id, item_key)
    updated = (
        on_stop_without_position(stored)
        if position_ticks is None
        else on_report(stored, position_ticks, runtime_ticks)
    )
    data.put(user_id, item_key, updated)


def _found(repository: ItemQueryRepository, user: User, item_id: str | None) -> HydratedItem | None:
    """The reported item, if this caller can see it. `None` is a `204`, never an error."""
    if item_id is None:
        return None
    page = repository.run(ItemQuery(user=user, ids=(item_id,), limit=1, count=False))
    return page.items[0] if page.items else None


@router.post("/Sessions/Playing", status_code=204)
async def report_playback_start(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    playbackStartInfo: PlaybackStartInfo,  # noqa: N803 - the reference's parameter name
) -> Response:
    """`ReportPlaybackStart` `[spec: ReportPlaybackStart]`.

    The play is counted **here**, and `Played` goes false with it: starting an item that was
    watched un-marks it until it completes again. The position the body carries is *not* written -
    measured, and it is what stops a client restarting playback from destroying its own resume
    point.
    """
    when = utc_now()
    with session_scope(get_sessions(request)) as opened:
        found = _found(ItemQueryRepository(opened), caller, playbackStartInfo.item_id)
        if found is not None:
            data = UserDataRepository(opened)
            data.put(caller.id, found.id, on_start(data.get(caller.id, found.id), when))
            _now_playing(request, found, playbackStartInfo, started=True)
    _checked_in(request, when)
    return Response(status_code=204)


@router.post("/Sessions/Playing/Progress", status_code=204)
async def report_playback_progress(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    playbackProgressInfo: PlaybackProgressInfo,  # noqa: N803
) -> Response:
    """`ReportPlaybackProgress` `[spec: ReportPlaybackProgress]`.

    The position resolves through section 3.7's rule like any other, so a progress past the
    ceiling marks the item played mid-playback - and a progress carrying **no** position leaves
    the stored one alone while still refreshing the session's check-in and its live `PlayState`.
    """
    when = utc_now()
    with session_scope(get_sessions(request)) as opened:
        found = _found(ItemQueryRepository(opened), caller, playbackProgressInfo.item_id)
        if found is not None:
            if playbackProgressInfo.position_ticks is not None:
                data = UserDataRepository(opened)
                data.put(
                    caller.id,
                    found.id,
                    on_report(
                        data.get(caller.id, found.id),
                        playbackProgressInfo.position_ticks,
                        found.metadata.runtime_ticks,
                    ),
                )
            _now_playing(request, found, playbackProgressInfo, started=False)
    _checked_in(request, when)
    return Response(status_code=204)


@router.post("/Sessions/Playing/Stopped", status_code=204)
async def report_playback_stopped(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    playbackStopInfo: PlaybackStopInfo,  # noqa: N803
) -> Response:
    """`ReportPlaybackStopped` `[spec: ReportPlaybackStopped]`.

    A negative position is the one refusal past binding, and it is checked before anything is
    written: `400`, `text/plain`, the fixed sentence. `Failed: true` records nothing - though the
    `Start` that preceded it counted its play already, which is why "a failed playback leaves no
    trace" is only half true and the spec says so.
    """
    if playbackStopInfo.position_ticks is not None and playbackStopInfo.position_ticks < 0:
        return controller_error(400)

    when = utc_now()
    with session_scope(get_sessions(request)) as opened:
        found = _found(ItemQueryRepository(opened), caller, playbackStopInfo.item_id)
        if found is not None and not playbackStopInfo.failed:
            record_stop(
                UserDataRepository(opened),
                caller.id,
                found.id,
                playbackStopInfo.position_ticks,
                found.metadata.runtime_ticks,
            )
    session_id = _session_id(request)
    if session_id is not None:
        get_playing(request).clear(session_id)
    _checked_in(request, when)
    return Response(status_code=204)


def _now_playing(
    request: Request, found: HydratedItem, body: PlaybackStartInfo, *, started: bool
) -> None:
    """Record what this session is playing - if the request came through a session at all.

    A report can only reach here authenticated, and every mechanism except the query forms carries
    a device (002 section 3.1), so "no session" is the API-key case: real playback that no
    `/Sessions` entry represents. It still writes the row; there is simply nothing live to update.
    """
    session_id = _session_id(request)
    if session_id is None:
        return
    registry = get_playing(request)
    report = _reported(body, found)
    if started:
        registry.start(session_id, report)
    else:
        registry.update(session_id, report)


def _session_id(request: Request) -> str | None:
    """Which session is reporting: the authenticated device's, never the body's."""
    session_id: str | None = getattr(request.state, "session_id", None)
    return session_id


def _checked_in(request: Request, when: datetime) -> None:
    """`LastPlaybackCheckIn` advances on every report, flushed with the activity (plan 6.6)."""
    session_id = _session_id(request)
    if session_id is not None:
        get_registry(request).touch_playback(session_id, when)


__all__ = [
    "PlaybackProgressInfo",
    "PlaybackStartInfo",
    "PlaybackStopInfo",
    "record_stop",
    "router",
]
