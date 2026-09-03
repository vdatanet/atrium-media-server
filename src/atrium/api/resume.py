# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /UserItems/Resume`: what this user is in the middle of, most recent first.

The whole endpoint is one query: `IsResumable` is a stored mid-playback position - 007's
six-branch rule guarantees a position past the completion threshold was never stored, so the
exclusion the spec names is structural rather than a filter here (plan section 6.8) - ordered by
when it was last played, newest first, in the envelope.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.delivery import access_of, policy_of
from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, build_dtos
from atrium.api.item_models import BaseItemDtoQueryResult
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
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository, ParentNotFoundError
from atrium.db.repositories import LibraryRepository, UserRepository
from atrium.domain.queries import Filter, ItemQuery, SortBy, SortOrder
from atrium.domain.user import User

router = APIRouter()


@router.get("/UserItems/Resume")
async def resume_items(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    userId: WireGuid | None = None,  # noqa: N803 - the reference's spellings, throughout
    startIndex: int = 0,  # noqa: N803
    limit: int | None = None,
    searchTerm: str | None = None,  # noqa: N803
    parentId: WireGuid | None = None,  # noqa: N803
    fields: str | None = None,
    mediaTypes: str | None = None,  # noqa: N803
    enableUserData: bool = True,  # noqa: N803
    imageTypeLimit: int | None = None,  # noqa: N803
    enableImageTypes: str | None = None,  # noqa: N803
    excludeItemTypes: str | None = None,  # noqa: N803
    includeItemTypes: str | None = None,  # noqa: N803
    enableTotalRecordCount: bool = True,  # noqa: N803
    enableImages: bool = True,  # noqa: N803
) -> BaseItemDtoQueryResult:
    """`GetResumeItems` `[spec: GetResumeItems]`."""
    route = "/UserItems/Resume"
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
                    parent_id=parentId,
                    recursive=parentId is not None,
                    include_types=parse_kinds(includeItemTypes, "includeItemTypes", ignored, route),
                    exclude_types=parse_kinds(excludeItemTypes, "excludeItemTypes", ignored, route),
                    media_types=frozenset(split_csv(mediaTypes)) or None,
                    search_term=searchTerm,
                    filters=frozenset({Filter.IS_RESUMABLE}),
                    sort=((SortBy.DATE_PLAYED, SortOrder.DESCENDING),),
                    start_index=startIndex,
                    limit=limit,
                    count=enableTotalRecordCount,
                )
            )
        except ParentNotFoundError as refused:
            raise NotFoundError from refused

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
                repository, page.items, target, asked_fields, Width.LIST_ROW
            ),
        )
        built = build_dtos(page.items, context)

    return BaseItemDtoQueryResult(
        items=built, total_record_count=page.total, start_index=startIndex
    )


__all__ = ["router"]
