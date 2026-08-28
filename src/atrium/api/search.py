# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Search/Hints`: the fourth shape, and it is not the item shape (AC-14).

`{"SearchHints": [...], "TotalRecordCount": n}` - a hint is a flattened summary, not a
`BaseItemDto`, and the model's field set is the measured wire (see `SearchHint`).

**Matching is against the name, and the spec said otherwise until it was measured.** The
discriminating case existed on the live library: an item whose padded sort form shares no
substring with its folded name - searched by that sort fragment, the reference finds nothing
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. So the folded
*name* is what a term is held against - `name_folded`, the plan's own reading - and relevance
orders the hits: exact, prefix at a word boundary, prefix, contains (plan section 6.3), which
the pipeline already prepends for any query carrying a term.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.deps import get_sessions, require_user
from atrium.api.item_models import SearchHint, SearchHintResult
from atrium.api.items import effective_user, parse_kinds, recorder, split_csv
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository, ParentNotFoundError
from atrium.db.repositories import UserRepository
from atrium.domain.items import FILE_BACKED, MEDIA_TYPE_OF, ItemType
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User
from atrium.metadata.artwork import ImageKind

router = APIRouter()


def _tag_holder(one: HydratedItem, kind: ImageKind) -> tuple[str, str] | None:
    """The nearest holder of an image of this kind - the hint's pairs name the item *and* the
    tag, and the measured hints resolve them through the ancestors like the item rows do."""
    for image in one.images:
        if image.kind is kind:
            return one.id, image.tag
    for ancestor in (one.parent, one.grandparent):
        if ancestor is None:
            continue
        for image in ancestor.images:
            if image.kind is kind:
                return ancestor.id, image.tag
    return None


def _hint(one: HydratedItem) -> SearchHint:
    # The primary resolves through the ancestors like the other two pairs: a track's hint
    # carries its album's cover on the measured wire.
    primary = next(
        (
            image
            for holder in (one, one.parent, one.grandparent)
            if holder is not None
            for image in holder.images
            if image.kind is ImageKind.PRIMARY
        ),
        None,
    )
    thumb = _tag_holder(one, ImageKind.THUMB)
    backdrop = _tag_holder(one, ImageKind.BACKDROP)

    series = None
    if one.item.type in {ItemType.EPISODE, ItemType.SEASON}:
        above = one.grandparent if one.item.type is ItemType.EPISODE else one.parent
        series = above.name if above is not None else None

    album = one.parent if one.item.type is ItemType.AUDIO else None
    album_artists = [
        link.name
        for link in (album.artists if album is not None else one.artists)
        if link.credit == "album_artist"
    ]

    return SearchHint(
        item_id=one.id,
        id=one.id,
        name=one.item.name,
        index_number=one.item.index_number,
        production_year=one.metadata.production_year,
        parent_index_number=one.item.parent_index_number,
        primary_image_tag=primary.tag if primary is not None else None,
        thumb_image_tag=thumb[1] if thumb is not None else None,
        thumb_image_item_id=thumb[0] if thumb is not None else None,
        backdrop_image_tag=backdrop[1] if backdrop is not None else None,
        backdrop_image_item_id=backdrop[0] if backdrop is not None else None,
        type=one.item.type.value,
        is_folder=True if one.item.type not in FILE_BACKED and not one.item.is_by_name else None,
        run_time_ticks=one.metadata.runtime_ticks,
        media_type=MEDIA_TYPE_OF[one.item.type],
        series=series,
        album=album.name if album is not None else None,
        album_id=album.id if album is not None else None,
        album_artist=album_artists[0] if album_artists else None,
        artists=[link.name for link in one.artists if link.credit == "artist"],
        primary_image_aspect_ratio=(
            primary.width / primary.height if primary is not None and primary.height else None
        ),
    )


@router.get("/Search/Hints")
async def search_hints(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    searchTerm: str,  # noqa: N803 - the reference's spellings, throughout
    startIndex: int = 0,  # noqa: N803
    limit: int | None = None,
    userId: WireGuid | None = None,  # noqa: N803
    includeItemTypes: str | None = None,  # noqa: N803
    excludeItemTypes: str | None = None,  # noqa: N803
    mediaTypes: str | None = None,  # noqa: N803
    parentId: WireGuid | None = None,  # noqa: N803
) -> SearchHintResult:
    """`GetSearchHints` `[spec: GetSearchHints]`."""
    route = "/Search/Hints"
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
                    exclude_types=parse_kinds(excludeItemTypes, "excludeItemTypes", ignored, route),
                    media_types=frozenset(split_csv(mediaTypes)) or None,
                    search_term=searchTerm,
                    start_index=startIndex,
                    limit=limit,
                )
            )
        except ParentNotFoundError as refused:
            raise NotFoundError from refused

        hints = [_hint(one) for one in page.items]
        total = page.total

    return SearchHintResult(search_hints=hints, total_record_count=total)


__all__ = ["router"]
