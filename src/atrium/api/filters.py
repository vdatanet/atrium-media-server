# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items/Filters`: what a scope offers to filter by.

The third of the four shapes (plan section 6.6): `{Genres, Tags, OfficialRatings, Years}`, all
four keys always present, each list the **distinct values over the visible items in scope,
sorted ascending** - measured: the unscoped summary and a `parentId`-scoped one both carry all
four keys, empty lists included, genres as the items' own spellings (two spellings are two
entries - this is not the by-name list), and every list arrives sorted
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.deps import get_sessions, require_user
from atrium.api.item_models import QueryFiltersLegacy
from atrium.api.items import effective_user, parse_kinds, recorder, split_csv
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository, ParentNotFoundError
from atrium.db.repositories import UserRepository
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

router = APIRouter()


@router.get("/Items/Filters")
async def item_filters(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    userId: WireGuid | None = None,  # noqa: N803 - the reference's spellings, throughout
    parentId: WireGuid | None = None,  # noqa: N803
    includeItemTypes: str | None = None,  # noqa: N803
    mediaTypes: str | None = None,  # noqa: N803
) -> QueryFiltersLegacy:
    """`GetQueryFiltersLegacy` `[spec: QueryFiltersLegacy]`."""
    route = "/Items/Filters"
    ignored = recorder(request)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        repository = ItemQueryRepository(opened)
        try:
            page = repository.run(
                ItemQuery(
                    user=target,
                    parent_id=parentId,
                    recursive=parentId is not None,
                    include_types=parse_kinds(includeItemTypes, "includeItemTypes", ignored, route),
                    media_types=frozenset(split_csv(mediaTypes)) or None,
                    count=False,
                )
            )
        except ParentNotFoundError as refused:
            raise NotFoundError from refused

        genres: set[str] = set()
        tags: set[str] = set()
        ratings: set[str] = set()
        years: set[int] = set()
        for one in page.items:
            genres.update(link.name for link in one.genres)
            tags.update(one.metadata.tags)
            if one.metadata.official_rating:
                ratings.add(one.metadata.official_rating)
            if one.metadata.production_year:
                years.add(one.metadata.production_year)

    return QueryFiltersLegacy(
        genres=sorted(genres),
        tags=sorted(tags),
        official_ratings=sorted(ratings),
        years=sorted(years),
    )


__all__ = ["router"]
