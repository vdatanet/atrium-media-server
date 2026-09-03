# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /UserViews`: the libraries as this user sees them, after policy.

Each visible library's `CollectionFolder` item, in the third of the three widths - as wide as a
full body, unasked (spec section 3.2) - with `CollectionType` telling the client which navigation
to offer (spec section 3.6). A user with no permitted libraries gets an **empty envelope**, not
an error (AC-9): the request is fine, the world is just small.

The declared parameter is `userId`. The other three the reference declares -
`includeExternalContent`, `presetViews`, `includeHidden` - govern external channels and preset
views this version has none of; they stay undeclared, so a client sending them shows up in the
ignored-parameter record rather than being silently half-honoured (spec section 3.3's mechanism,
applied one route over).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from atrium.api.delivery import access_of, policy_of
from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, dto_values
from atrium.api.item_models import UserViewDto, UserViewQueryResult
from atrium.api.items import effective_user, library_context
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import LibraryRepository, UserRepository
from atrium.domain.items import ItemType
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

router = APIRouter()


@router.get("/UserViews")
async def user_views(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    userId: WireGuid | None = None,  # noqa: N803 - the reference's spelling
) -> UserViewQueryResult:
    """`GetUserViews` `[spec: GetUserViews]`."""
    state = get_state(request)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        repository = ItemQueryRepository(opened)
        page = repository.run(
            ItemQuery(
                user=target,
                include_types=frozenset({ItemType.COLLECTION_FOLDER}),
            )
        )
        context = BuildContext(
            server_id=state.server_id,
            policy=policy_of(target),
            access=access_of(target),
            width=Width.USER_VIEW,
            libraries=library_context(LibraryRepository(opened)),
            aggregates=repository.aggregates_for([one.id for one in page.items], target),
        )
        views = [UserViewDto(**dto_values(one, context)) for one in page.items]

    return UserViewQueryResult(items=views, total_record_count=page.total, start_index=0)


__all__ = ["router"]
