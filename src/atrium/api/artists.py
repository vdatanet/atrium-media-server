# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Artists` and `GET /Artists/AlbumArtists`: the credit column, read two ways.

The same rows distinguished by `item_artists.credit` and nothing else - `/Artists` is any
credit, `/Artists/AlbumArtists` the album credit (plan section 6.7). **In v1 the two coincide as
row sets, and that is behaviours section 5.3's recorded consequence, not an accident**: an
Atrium `MusicArtist` is a per-library item the scanner creates per *album artist*, so an artist
who only ever performs has a name on every track and no row to list - the reference, whose
artists are by-name rows, lists them. The distinction still bites where T6 measured it,
`artistIds` versus `albumArtistIds`, and both routes exist so a client browsing either sees the
credit reading it asked for.

Measured omissions: an artist row from these routes carries no `IsFolder`, where the same item
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
from atrium.db.item_queries import ALBUM_ARTIST_CREDIT
from atrium.domain.items import ItemType
from atrium.domain.user import User

router = APIRouter()

#: Measured: no `IsFolder` on an artist row from either artist route.
OMITTED = frozenset({"IsFolder"})


@router.get("/Artists")
async def artists(
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
    """`GetArtists` `[spec: GetArtists]`: every credited artist."""
    return by_name_envelope(
        request,
        caller,
        route="/Artists",
        kind=ItemType.MUSIC_ARTIST,
        credit=None,
        omit=OMITTED,
        user_id=userId,
        parent_id=parentId,
        start_index=startIndex,
        limit=limit,
        sort_by=sortBy,
        sort_order=sortOrder,
        search_term=searchTerm,
    )


@router.get("/Artists/AlbumArtists")
async def album_artists(
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
    """`GetAlbumArtists` `[spec: GetAlbumArtists]`: only those credited on an album."""
    return by_name_envelope(
        request,
        caller,
        route="/Artists/AlbumArtists",
        kind=ItemType.MUSIC_ARTIST,
        credit=ALBUM_ARTIST_CREDIT,
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
