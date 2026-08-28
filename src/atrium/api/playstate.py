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

See specs/007-user-data-and-playstate/spec.md section 3.4 and plan section 6.2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, user_data_dto
from atrium.api.item_models import UserItemDataDto
from atrium.api.items import effective_user
from atrium.compat.dates import WireDateTime, utc_now
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import UserDataRepository, UserRepository
from atrium.domain.items import FILE_BACKED, IN_THE_TREE, ItemType
from atrium.domain.playstate import on_mark_played, on_mark_unplayed
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

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


__all__ = ["router"]
