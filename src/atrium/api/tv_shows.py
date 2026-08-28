# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Shows/{seriesId}/Seasons` and `GET /Shows/{seriesId}/Episodes`.

Both return the envelope, both answer the identical `404` for a series that does not exist or
is not this user's to see, and both order by the index - **specials first**.

**The specials-first order is measured, against a spec that said the opposite.** Spec section 3.8
claimed season 0 sorts last, "every client expects it last", with no provenance; a series with a
specials season answers `[Specials, Season 1]` on the live reference
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. Principle I
settles the argument: the wire order is index order, season 0 first, and whatever a client shows
its user is the client's business. The spec and AC-11 are corrected in the same change as this
module - and no specials-last expression exists here, because 003's numeric sort names already
produce the measured order by themselves.

`DisplayMissingEpisodes` is honoured trivially in v1: 004 creates no missing-episode
placeholders, so both settings serve the same rows (plan section 6.9) - recorded so nobody hunts
for a bug when a client toggles it. `isMissing` filters the same absence honestly: `true` narrows
to placeholders that cannot exist, `false` excludes nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, build_dtos
from atrium.api.item_models import BaseItemDtoQueryResult
from atrium.api.items import (
    aggregates_context,
    effective_user,
    library_context,
    parse_fields,
    recorder,
    split_csv,
)
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository, ParentNotFoundError
from atrium.db.repositories import LibraryRepository, UserRepository
from atrium.domain.items import ItemType
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

router = APIRouter()


@router.get("/Shows/{seriesId}/Seasons")
async def seasons(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    seriesId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    userId: WireGuid | None = None,  # noqa: N803
    fields: str | None = None,
    isSpecialSeason: bool | None = None,  # noqa: N803
    isMissing: bool | None = None,  # noqa: N803
    enableImages: bool = True,  # noqa: N803
    imageTypeLimit: int | None = None,  # noqa: N803
    enableImageTypes: str | None = None,  # noqa: N803
    enableUserData: bool = True,  # noqa: N803
) -> BaseItemDtoQueryResult:
    """`GetSeasons` `[spec: GetSeasons]`."""
    route = "/Shows/{seriesId}/Seasons"
    ignored = recorder(request)
    state = get_state(request)
    asked_fields = parse_fields(fields, ignored, route)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        repository = ItemQueryRepository(opened)
        try:
            page = repository.run(
                ItemQuery(
                    user=target,
                    parent_id=seriesId,
                    include_types=frozenset({ItemType.SEASON}),
                )
            )
        except ParentNotFoundError as refused:
            raise NotFoundError from refused

        rows = list(page.items)
        if isSpecialSeason is not None:
            rows = [
                one for one in rows if (one.item.index_number == 0) is isSpecialSeason
            ]
        if isMissing:
            # v1 has no missing-episode placeholders to offer (plan section 6.9).
            rows = []

        context = BuildContext(
            server_id=state.server_id,
            width=Width.LIST_ROW,
            fields=asked_fields,
            enable_user_data=enableUserData,
            enable_images=enableImages,
            image_type_limit=imageTypeLimit,
            enable_image_types=frozenset(split_csv(enableImageTypes)) or None,
            libraries=library_context(LibraryRepository(opened)),
            aggregates=aggregates_context(
                repository, rows, target, asked_fields, Width.LIST_ROW
            ),
        )
        built = build_dtos(rows, context)

    return BaseItemDtoQueryResult(items=built, total_record_count=len(built), start_index=0)


@router.get("/Shows/{seriesId}/Episodes")
async def episodes(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    seriesId: WireGuid,  # noqa: N803
    userId: WireGuid | None = None,  # noqa: N803
    fields: str | None = None,
    season: int | None = None,
    seasonId: WireGuid | None = None,  # noqa: N803
    isMissing: bool | None = None,  # noqa: N803
    startIndex: int = 0,  # noqa: N803
    limit: int | None = None,
    enableImages: bool = True,  # noqa: N803
    imageTypeLimit: int | None = None,  # noqa: N803
    enableImageTypes: str | None = None,  # noqa: N803
    enableUserData: bool = True,  # noqa: N803
) -> BaseItemDtoQueryResult:
    """`GetEpisodes` `[spec: GetEpisodes]`.

    The whole series in `(season, episode)` order - 003's numeric sort names are exactly that
    order - or one season of it when `seasonId` or `season` narrows. The multi-episode file is
    one item and appears once (003 AC-5's shape, surfacing here).
    """
    route = "/Shows/{seriesId}/Episodes"
    ignored = recorder(request)
    state = get_state(request)
    asked_fields = parse_fields(fields, ignored, route)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        repository = ItemQueryRepository(opened)
        try:
            if seasonId is not None:
                # One season's episodes, and the season itself must be reachable - an unknown
                # or invisible one is the same 404 the series would be.
                page = repository.run(
                    ItemQuery(
                        user=target,
                        parent_id=seasonId,
                        include_types=frozenset({ItemType.EPISODE}),
                    )
                )
            else:
                page = repository.run(
                    ItemQuery(
                        user=target,
                        parent_id=seriesId,
                        recursive=True,
                        include_types=frozenset({ItemType.EPISODE}),
                    )
                )
        except ParentNotFoundError as refused:
            raise NotFoundError from refused

        rows: list[HydratedItem] = list(page.items)
        if season is not None:
            rows = [one for one in rows if one.item.parent_index_number == season]
        if isMissing:
            rows = []

        total = len(rows)
        window = rows[startIndex:]
        if limit is not None:
            window = window[:limit]

        context = BuildContext(
            server_id=state.server_id,
            width=Width.LIST_ROW,
            fields=asked_fields,
            enable_user_data=enableUserData,
            enable_images=enableImages,
            image_type_limit=imageTypeLimit,
            enable_image_types=frozenset(split_csv(enableImageTypes)) or None,
            libraries=library_context(LibraryRepository(opened)),
            aggregates=aggregates_context(
                repository, window, target, asked_fields, Width.LIST_ROW
            ),
        )
        built = build_dtos(window, context)

    return BaseItemDtoQueryResult(
        items=built, total_record_count=total, start_index=startIndex
    )


__all__ = ["router"]
