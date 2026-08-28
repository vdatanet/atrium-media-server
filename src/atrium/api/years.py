# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Years`: the production years the visible world spans.

A `Year` is an item - T8's finding was that nothing had ever created one - and this route lists
the rows whose year a visible item carries. No measured omission here: a year row keeps its
`UserData`, unlike its genre siblings
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.deps import require_user
from atrium.api.item_models import BaseItemDtoQueryResult
from atrium.api.items import by_name_envelope
from atrium.compat.guids import WireGuid
from atrium.domain.items import ItemType
from atrium.domain.user import User

router = APIRouter()


@router.get("/Years")
async def years(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    userId: WireGuid | None = None,  # noqa: N803 - the reference's spellings, throughout
    parentId: WireGuid | None = None,  # noqa: N803
    startIndex: int = 0,  # noqa: N803
    limit: int | None = None,
    sortBy: str | None = None,  # noqa: N803
    sortOrder: str | None = None,  # noqa: N803
    searchTerm: str | None = None,  # noqa: N803
) -> BaseItemDtoQueryResult:
    """`GetYears` `[spec: GetYears]`."""
    return by_name_envelope(
        request,
        caller,
        route="/Years",
        kind=ItemType.YEAR,
        user_id=userId,
        parent_id=parentId,
        start_index=startIndex,
        limit=limit,
        sort_by=sortBy,
        sort_order=sortOrder,
        search_term=searchTerm,
    )


__all__ = ["router"]
