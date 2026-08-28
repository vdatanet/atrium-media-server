# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Genres` and `GET /MusicGenres`: two disjoint name spaces, one pipeline.

A `Genre` and a `MusicGenre` spelled the same are two rows with two identifiers (004's identity
rule), which is the whole of what keeps these two endpoints disjoint. Visibility is the by-name
clause of the one predicate: a genre exists for a user while a *visible* item references it, so
`/Genres` never names what sits only in a library the user cannot see.

Measured omission: a genre row from these routes carries no `UserData`, where the same row
through `/Items` does `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11,
2026-08-28]`.
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

#: Measured: no `UserData` on a genre row from its own route.
OMITTED = frozenset({"UserData"})


@router.get("/Genres")
async def genres(
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
    """`GetGenres` `[spec: GetGenres]`."""
    return by_name_envelope(
        request,
        caller,
        route="/Genres",
        kind=ItemType.GENRE,
        omit=OMITTED,
        user_id=userId,
        parent_id=parentId,
        start_index=startIndex,
        limit=limit,
        sort_by=sortBy,
        sort_order=sortOrder,
        search_term=searchTerm,
    )


@router.get("/MusicGenres")
async def music_genres(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    userId: WireGuid | None = None,  # noqa: N803
    parentId: WireGuid | None = None,  # noqa: N803
    startIndex: int = 0,  # noqa: N803
    limit: int | None = None,
    sortBy: str | None = None,  # noqa: N803
    sortOrder: str | None = None,  # noqa: N803
    searchTerm: str | None = None,  # noqa: N803
) -> BaseItemDtoQueryResult:
    """`GetMusicGenres` `[spec: GetMusicGenres]`."""
    return by_name_envelope(
        request,
        caller,
        route="/MusicGenres",
        kind=ItemType.MUSIC_GENRE,
        omit=OMITTED,
        user_id=userId,
        parent_id=parentId,
        start_index=startIndex,
        limit=limit,
        sort_by=sortBy,
        sort_order=sortOrder,
        search_term=searchTerm,
    )


__all__ = ["router"]
