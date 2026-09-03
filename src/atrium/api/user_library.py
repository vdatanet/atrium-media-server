# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `UserLibraryController`: `GET /Items/Latest` and the favourite pair.

Two unrelated things in one module because they are one **controller** there, and `api/` is one
module per Jellyfin controller (architecture.md section 1) - which is what has kept every route
audit against the pinned document mechanical. The favourite pair costs an import to keep that
true (007 plan section 10).

## The favourite pair

`POST` and `DELETE /UserFavoriteItems/{itemId}`, each answering the item's updated `UserData` and
each **idempotent**: marking twice is `200` twice and leaves one favourite, unmarking what was
never marked is `200` and not an error. Clients retry.
`[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`

**A favourite does not cascade.** Favouriting a season leaves every episode unfavourited - the
flag is the container's own row, which is the opposite of the played mark (007 spec section 3.3,
measured). Any item type may carry it, including the by-name rows that have no file.

The response is **re-read after the write** rather than assembled from what was just stored, and
it goes through the same builder a list row does, so "the mark response is what the next request
shows" is a property of the code path rather than a claim (007 plan section 6.3).

## `GET /Items/Latest`: recency, grouped upward - and it returns a **bare array**.

No envelope (behaviours section 1.8): a client decoding this as one gets nothing, which is why
the asymmetry is load-bearing (spec section 3.1).

**The grouping rule is measured, and it is not the one the plan first wrote down.** Recent file
items group under their container - an episode under its series, a track under its album, a film
under itself - and a group surfaces as **the container only when it holds more than one recent
item; a group of one surfaces as the item itself**. Measured: a series with several new episodes
arrives as the `Series` row while a lone new episode arrives as the `Episode`, and a lone new
track as the `Audio`, in one and the same response
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. `groupItems=false`
switches the grouping off and serves the file items plainly `[spec: GetLatestMedia]`.

**Two stored configuration keys steer it**, both measured by name on a live user's configuration
(002 section 3.6 stores them faithfully): `LatestItemsExcludes` - view identifiers whose
libraries contribute nothing when the request is unscoped - and `HidePlayedInLatest`, `true` on
a configuration never edited, which keeps played items out unless the caller's own `isPlayed`
asks for them explicitly.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.delivery import access_of, policy_of
from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, build_dtos, user_data_dto
from atrium.api.item_models import BaseItemDto, UserItemDataDto
from atrium.api.items import (
    aggregates_context,
    effective_user,
    library_context,
    parse_fields,
    parse_kinds,
    recorder,
    split_csv,
)
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import CANONICAL, WireGuid, normalise
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository, ParentNotFoundError
from atrium.db.repositories import LibraryRepository, UserDataRepository, UserRepository
from atrium.domain.items import FILE_BACKED, ItemType
from atrium.domain.queries import ItemQuery, SortBy, SortOrder
from atrium.domain.user import User
from atrium.library import identity

router = APIRouter()

#: How many file items each grouping pass fetches. Grouping collapses an unknown number of rows
#: into each entry, so the loop below pages until it has enough groups or the world runs out -
#: a page size, not a cap.
GROUP_PAGE = 100


def _excluded_libraries(target: User, libraries: LibraryRepository) -> frozenset[str]:
    """`LatestItemsExcludes` holds **view** identifiers - the library's own item id - so the
    match is against the derived folder identity, not the library row's key."""
    raw = target.configuration.get("LatestItemsExcludes")
    if not isinstance(raw, list):
        return frozenset()
    excluded = {normalise(str(one)) for one in raw if isinstance(one, str) and one}
    excluded = {one for one in excluded if CANONICAL.match(one)}
    if not excluded:
        return frozenset()
    return frozenset(
        library.id for library in libraries.all() if identity.for_library(library.id) in excluded
    )


def _representative(one: HydratedItem) -> tuple[str, HydratedItem]:
    """The group key, and the container the group surfaces as when it grows past one."""
    if one.item.type is ItemType.EPISODE and one.grandparent is not None:
        return one.grandparent.id, one
    if one.item.type is ItemType.AUDIO and one.parent is not None:
        return one.parent.id, one
    return one.id, one


@router.get("/Items/Latest")
async def latest_media(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    userId: WireGuid | None = None,  # noqa: N803 - the reference's spellings, throughout
    parentId: WireGuid | None = None,  # noqa: N803
    fields: str | None = None,
    includeItemTypes: str | None = None,  # noqa: N803
    isPlayed: bool | None = None,  # noqa: N803
    enableImages: bool = True,  # noqa: N803
    imageTypeLimit: int | None = None,  # noqa: N803
    enableImageTypes: str | None = None,  # noqa: N803
    enableUserData: bool = True,  # noqa: N803
    limit: int = 20,
    groupItems: bool = True,  # noqa: N803
) -> list[BaseItemDto]:
    """`GetLatestMedia` `[spec: GetLatestMedia]`."""
    route = "/Items/Latest"
    ignored = recorder(request)
    state = get_state(request)
    asked_fields = parse_fields(fields, ignored, route)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        repository = ItemQueryRepository(opened)

        kinds = parse_kinds(includeItemTypes, "includeItemTypes", ignored, route)
        include = frozenset(FILE_BACKED) if kinds is None else frozenset(kinds) & FILE_BACKED

        hide_played = bool(target.configuration.get("HidePlayedInLatest", True))
        played = isPlayed if isPlayed is not None else (False if hide_played else None)

        # Exclusions apply to the unscoped request: a client asking for one view's latest by
        # `parentId` said which library it wants, and the exclusion list is about the sections
        # nobody asked for by name.
        excluded = (
            _excluded_libraries(target, LibraryRepository(opened))
            if parentId is None
            else frozenset()
        )

        # First seen wins the position - the pages arrive newest first, so a group sits where
        # its newest member does - and the count decides what the group surfaces as.
        newest: dict[str, HydratedItem] = {}
        members: dict[str, int] = {}
        start = 0
        while len(newest) < limit:
            try:
                page = repository.run(
                    ItemQuery(
                        user=target,
                        parent_id=parentId,
                        recursive=True,
                        include_types=include,
                        is_played=played,
                        sort=((SortBy.DATE_CREATED, SortOrder.DESCENDING),),
                        start_index=start,
                        limit=GROUP_PAGE,
                    )
                )
            except ParentNotFoundError as refused:
                # The identical 404, same as every scoped query (plan section 6.13).
                raise NotFoundError from refused
            for one in page.items:
                if one.item.library_id in excluded:
                    continue
                key, newest_member = _representative(one) if groupItems else (one.id, one)
                if key not in newest:
                    newest[key] = newest_member
                members[key] = members.get(key, 0) + 1
            start += GROUP_PAGE
            if start >= page.total:
                break

        chosen = list(newest.items())[:limit]

        # A group of several surfaces as its container, which is an item of its own - fetched
        # through the same pipeline, so its row carries the rollups a container row carries.
        container_ids = tuple(
            key for key, first in chosen if members.get(key, 0) > 1 and key != first.id
        )
        containers: dict[str, HydratedItem] = {}
        if container_ids:
            grouped_page = repository.run(ItemQuery(user=target, ids=container_ids))
            containers = {one.id: one for one in grouped_page.items}

        ordered = [containers.get(key, first) for key, first in chosen]

        context = BuildContext(
            server_id=state.server_id,
            policy=policy_of(target),
            access=access_of(target),
            width=Width.LIST_ROW,
            fields=asked_fields,
            enable_user_data=enableUserData,
            enable_images=enableImages,
            image_type_limit=imageTypeLimit,
            enable_image_types=frozenset(split_csv(enableImageTypes)) or None,
            libraries=library_context(LibraryRepository(opened)),
            aggregates=aggregates_context(
                repository, ordered, target, asked_fields, Width.LIST_ROW
            ),
        )
        built = build_dtos(ordered, context)

    return built


# ------------------------------------------------------------------------------------------------
# The favourite pair (007 spec section 3.3)
# ------------------------------------------------------------------------------------------------


def _set_favourite(
    request: Request, caller: User, item_id: str, user_id: str | None, *, favourite: bool
) -> UserItemDataDto:
    """One row written - the item's own - and the answer re-read through the ordinary path.

    The item resolves through the same visible-item lookup `GET /Items/{itemId}` uses, so an
    unknown item and an invisible one are the identical `404` (005 plan section 6.13): a client
    that could tell them apart could enumerate another user's library one identifier at a time.
    """
    state = get_state(request)
    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, user_id)
        repository = ItemQueryRepository(opened)
        if not repository.run(ItemQuery(user=target, ids=(item_id,), limit=1, count=False)).items:
            raise NotFoundError

        data = UserDataRepository(opened)
        stored = data.get(target.id, item_id)
        data.put(target.id, item_id, replace(stored, is_favorite=favourite))

        # Re-read rather than patched: the response is a fresh row through the same hydration a
        # list request makes, which is what makes the two byte-identical by construction.
        refreshed = repository.run(
            ItemQuery(user=target, ids=(item_id,), limit=1, count=False)
        ).items[0]
        answered = user_data_dto(
            refreshed,
            BuildContext(
                server_id=state.server_id,
                policy=policy_of(target),
                access=access_of(target),
                width=Width.FULL,
            ),
        )
    assert answered is not None  # noqa: S101 - enable_user_data is not settable on this path
    return answered


@router.post("/UserFavoriteItems/{itemId}")
async def mark_favorite_item(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    userId: WireGuid | None = None,  # noqa: N803
) -> UserItemDataDto:
    """`MarkFavoriteItem` `[spec: MarkFavoriteItem]`."""
    return _set_favourite(request, caller, itemId, userId, favourite=True)


@router.delete("/UserFavoriteItems/{itemId}")
async def unmark_favorite_item(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803
    userId: WireGuid | None = None,  # noqa: N803
) -> UserItemDataDto:
    """`UnmarkFavoriteItem` `[spec: UnmarkFavoriteItem]`. Unmarking what was never marked is
    `200`, not an error - measured, and clients retry."""
    return _set_favourite(request, caller, itemId, userId, favourite=False)


__all__ = ["router"]
