# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items/{itemId}/Similar`: related items, deterministic on purpose.

The score is [plan section 6.10]'s table, verbatim, and the constants live beside it:

    3 x shared genres  +  2 x shared people  +  1 x shared studios

Candidates are the seed's own type, visible, never the seed itself; a zero score is excluded;
ties break on `sort_name` then id, so the ranking is total. The reference's ranking is not
obviously deterministic and a non-deterministic endpoint cannot be tested at L2 - determinism is
invisible to a client, which cannot tell a stable ranking from a lucky one (spec section 3.7).

"Shared" means the **by-name row**, not the spelling: two items carrying `sci-fi` and `Sci-Fi`
share a genre because 004 merged the spellings into one row, and people and studios compare the
same way.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.delivery import policy_of
from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, build_dtos
from atrium.api.item_models import BaseItemDtoQueryResult
from atrium.api.items import effective_user, library_context, parse_fields, recorder
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository
from atrium.db.repositories import LibraryRepository, UserRepository
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

router = APIRouter()

#: Plan section 6.10's weights. A change here is a change to every "More like this" row a
#: client shows, which is why they are named constants rather than three literals in a sum.
GENRE_WEIGHT = 3
PERSON_WEIGHT = 2
STUDIO_WEIGHT = 1


def _links(one: HydratedItem) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    return (
        frozenset(link.item_id for link in one.genres if link.item_id),
        frozenset(link.item_id for link in one.people if link.item_id),
        frozenset(link.item_id for link in one.studios if link.item_id),
    )


def _score(seed: HydratedItem, candidate: HydratedItem) -> int:
    seed_genres, seed_people, seed_studios = _links(seed)
    genres, people, studios = _links(candidate)
    return (
        GENRE_WEIGHT * len(seed_genres & genres)
        + PERSON_WEIGHT * len(seed_people & people)
        + STUDIO_WEIGHT * len(seed_studios & studios)
    )


@router.get("/Items/{itemId}/Similar")
async def similar_items(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    userId: WireGuid | None = None,  # noqa: N803
    limit: int | None = None,
    fields: str | None = None,
) -> BaseItemDtoQueryResult:
    """`GetSimilarItems` `[spec: GetSimilarItems]`."""
    route = "/Items/{itemId}/Similar"
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

        candidates = repository.run(
            ItemQuery(user=target, include_types=frozenset({seed.item.type}))
        )
        scored = [(one, _score(seed, one)) for one in candidates.items if one.id != seed.id]
        ranked = sorted(
            (pair for pair in scored if pair[1] > 0),
            key=lambda pair: (-pair[1], pair[0].item.sort_name, pair[0].id),
        )
        chosen = [one for one, _ in ranked]
        total = len(chosen)
        if limit is not None:
            chosen = chosen[:limit]

        context = BuildContext(
            server_id=state.server_id,
            policy=policy_of(target),
            width=Width.LIST_ROW,
            fields=asked_fields,
            libraries=library_context(LibraryRepository(opened)),
        )
        built = build_dtos(chosen, context)

    return BaseItemDtoQueryResult(items=built, total_record_count=total, start_index=0)


__all__ = ["GENRE_WEIGHT", "PERSON_WEIGHT", "STUDIO_WEIGHT", "router"]
