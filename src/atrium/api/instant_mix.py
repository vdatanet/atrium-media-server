# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items/{itemId}/InstantMix`: a radio-style queue, stable for a given seed and library.

The pool is the visible `Audio` sharing a music genre with the seed - for an album or artist
seed, the union over its tracks' genres; for a track, its own and its album's, because a music
genre lives on the album row where the sidecar put it. The order is a **keyed shuffle**,
`sha256(seed_id || item_id)` ascending (plan section 6.10): total, stable across processes and
restarts, needing no stored state, and exactly as observable as the reference's own
not-obviously-deterministic mix - a client cannot tell a stable ranking from a lucky one
(spec section 3.7, AC-12).
"""

from __future__ import annotations

from hashlib import sha256
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.delivery import policy_of
from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, build_dtos
from atrium.api.item_models import BaseItemDtoQueryResult
from atrium.api.items import effective_user, library_context, parse_fields, recorder, split_csv
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository
from atrium.db.repositories import LibraryRepository, UserRepository
from atrium.domain.items import ItemType
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

router = APIRouter()


def _mix_key(seed_id: str, item_id: str) -> str:
    return sha256(f"{seed_id}{item_id}".encode()).hexdigest()


def _genre_rows(
    repository: ItemQueryRepository, target: User, seed: HydratedItem
) -> frozenset[str]:
    """The music-genre rows the mix is built from - the seed's, or its family's.

    A `MusicGenre` seed is its own row. A track contributes its own links and its album's; an
    album its own and its tracks'; an artist the union over everything beneath it - the plan's
    "union over its tracks' genres", walked through the same pipeline as everything else.
    """
    if seed.item.type is ItemType.MUSIC_GENRE:
        return frozenset({seed.id})

    rows = {link.item_id for link in seed.genres if link.item_id}
    if seed.item.type is ItemType.AUDIO and seed.parent is not None:
        album_page = repository.run(ItemQuery(user=target, ids=(seed.parent.id,), count=False))
        for album in album_page.items:
            rows.update(link.item_id for link in album.genres if link.item_id)
    if seed.item.type in {ItemType.MUSIC_ALBUM, ItemType.MUSIC_ARTIST}:
        beneath = repository.run(
            ItemQuery(
                user=target,
                parent_id=seed.id,
                recursive=True,
            )
        )
        for one in beneath.items:
            rows.update(link.item_id for link in one.genres if link.item_id)
    return frozenset(rows)


@router.get("/Items/{itemId}/InstantMix")
async def instant_mix(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    userId: WireGuid | None = None,  # noqa: N803
    limit: int | None = None,
    fields: str | None = None,
    enableImages: bool = True,  # noqa: N803
    enableUserData: bool = True,  # noqa: N803
    imageTypeLimit: int | None = None,  # noqa: N803
    enableImageTypes: str | None = None,  # noqa: N803
) -> BaseItemDtoQueryResult:
    """`GetInstantMixFromItem` `[spec: GetInstantMixFromItem]`."""
    route = "/Items/{itemId}/InstantMix"
    ignored = recorder(request)
    state = get_state(request)
    asked_fields = parse_fields(fields, ignored, route)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        repository = ItemQueryRepository(opened)
        seed_page = repository.run(ItemQuery(user=target, ids=(itemId,), count=False))
        if not seed_page.items:
            raise NotFoundError
        seed = seed_page.items[0]

        genre_rows = _genre_rows(repository, target, seed)
        pool: list[HydratedItem] = []
        if genre_rows:
            # A music genre hangs on the album row, so the pool is the tracks of the albums
            # that share one - fetched per album, bounded by how many albums share a genre.
            albums = repository.run(
                ItemQuery(
                    user=target,
                    include_types=frozenset({ItemType.MUSIC_ALBUM}),
                    genre_ids=tuple(sorted(genre_rows)),
                )
            )
            for album in albums.items:
                tracks = repository.run(
                    ItemQuery(
                        user=target,
                        parent_id=album.id,
                        include_types=frozenset({ItemType.AUDIO}),
                    )
                )
                pool.extend(tracks.items)
            # Tracks carrying a shared genre row directly belong in the pool too.
            direct = repository.run(
                ItemQuery(
                    user=target,
                    include_types=frozenset({ItemType.AUDIO}),
                    genre_ids=tuple(sorted(genre_rows)),
                )
            )
            pool.extend(direct.items)

        distinct = {one.id: one for one in pool if one.id != seed.id}
        ordered = sorted(distinct.values(), key=lambda one: _mix_key(seed.id, one.id))
        total = len(ordered)
        if limit is not None:
            ordered = ordered[:limit]

        context = BuildContext(
            server_id=state.server_id,
            policy=policy_of(target),
            width=Width.LIST_ROW,
            fields=asked_fields,
            enable_user_data=enableUserData,
            enable_images=enableImages,
            image_type_limit=imageTypeLimit,
            enable_image_types=frozenset(split_csv(enableImageTypes)) or None,
            libraries=library_context(LibraryRepository(opened)),
        )
        built = build_dtos(ordered, context)

    return BaseItemDtoQueryResult(items=built, total_record_count=total, start_index=0)


__all__ = ["router"]
