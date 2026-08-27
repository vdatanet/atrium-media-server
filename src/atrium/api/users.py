# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Users` - the five routes, and the field order that decides their bytes.

**The field order is the reference's, measured** `[probe: manual request, Jellyfin 10.11.11,
2026-08-26]`, and it is not the order the specification lists: `ServerId` comes **before** `Id`.
No client cares about key order; a golden test comparing bytes does, and so does anything comparing
two servers directly.

`ServerName` and `PrimaryImageAspectRatio` are declared and absent from every measured response,
because they are null and nulls are omitted globally (behaviours section 1.7). Their **position**
is therefore unverified - nothing can measure where a property that is never sent would sit.

## `/Users/Public` sends the whole user object

Including `Configuration` and `Policy`, to a caller with **no token at all**, byte-identical to the
authenticated response. Measured, and the opposite of what
[spec section 3.4](../../../specs/002-authentication-users-and-sessions/spec.md) said: it asserted
that the two were omitted precisely so that a login screen discloses nothing about what a user may
do. They are not.

Atrium replicates it, per Principle V and behaviours section 3.0.2 - a defect is not fixed because
it is obviously wrong - and the whole argument, including the case for diverging, is written out in
behaviours section 3.5 so that the decision is a decision rather than an oversight.

## The literal routes are registered before `/Users/{userId}`

`/Users/Public`, `/Users/Me` and `/Users/Configuration` are literal paths that a parameterised
route would also match. The route table tries literals first and then patterns **in registration
order**, so `/users/public` reaches the public route rather than being read as a user whose
identifier is `public`. That is a property of the order below, so a test asserts it rather than a
comment asking for it.

See specs/002-authentication-users-and-sessions/spec.md sections 3.3 to 3.7.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from atrium.api import sessions as session_models
from atrium.api.deps import get_authenticator, get_sessions, get_state, require_user
from atrium.compat.auth import require_client_authorization
from atrium.compat.dates import WireDateTime
from atrium.compat.errors import ForbiddenError, UnauthenticatedError
from atrium.compat.model import AtriumModel, PropertyKeyed
from atrium.config.state import ServerState
from atrium.db.engine import session_scope
from atrium.db.repositories import SessionRepository, UserRepository
from atrium.domain.user import LibraryAccess
from atrium.domain.user import User as DomainUser
from atrium.users import policy as policy_module
from atrium.users.service import Authenticator, AuthResult

router = APIRouter(tags=["User"])


class UserDto(AtriumModel):
    """The user object, in the reference's field order.

    `Configuration` and `Policy` are mappings rather than declared models: v1 carries the 31 policy
    properties it does not act on and all 16 configuration properties untouched, so there is
    nothing to declare them as. They are `PropertyKeyed` because on the reference they are objects,
    and their keys convert under the CamelCase profile - measured.
    """

    name: str
    server_id: str
    server_name: str | None = None
    id: str
    primary_image_tag: str | None = None
    primary_image_aspect_ratio: float | None = None
    has_password: bool = False
    has_configured_password: bool = False
    #: Always false. v1 has no PIN concept (spec section 3.5).
    has_configured_easy_password: bool = False
    enable_auto_login: bool = False
    last_login_date: WireDateTime | None = None
    last_activity_date: WireDateTime | None = None
    configuration: Annotated[dict[str, Any], PropertyKeyed] = Field(default_factory=dict)
    policy: Annotated[dict[str, Any], PropertyKeyed] = Field(default_factory=dict)


class AuthenticateByName(AtriumModel):
    """What a client posts to log in.

    `Pw` is the reference's spelling and it is not a typo. The model accepts any casing of it, as
    the reference's own binder does (compat/model.py).
    """

    username: str = ""
    pw: str = ""


class AuthenticationResult(AtriumModel):
    """`User`, `SessionInfo`, `AccessToken`, `ServerId` - measured order."""

    user: UserDto
    session_info: session_models.SessionInfo
    access_token: str
    server_id: str


def to_wire(user: DomainUser, state: ServerState, access: LibraryAccess | None = None) -> UserDto:
    """Build the wire object from a domain user, assembling the policy as it goes."""
    reachable = access if access is not None else LibraryAccess()
    return UserDto(
        name=user.name,
        server_id=state.server_id,
        id=user.id,
        has_password=user.password_hash is not None,
        has_configured_password=user.password_hash is not None,
        last_login_date=user.last_login_date,
        last_activity_date=user.last_activity_date,
        configuration=dict(user.configuration),
        policy=policy_module.assemble(user, reachable),
    )


# --------------------------------------------------------------------------------------------
# The routes. Literal paths first - see the module docstring.
# --------------------------------------------------------------------------------------------


@router.post("/Users/AuthenticateByName")
async def authenticate_by_name(
    request: Request,
    body: AuthenticateByName,
    authenticator: Annotated[Authenticator, Depends(get_authenticator)],
    state: Annotated[ServerState, Depends(get_state)],
) -> AuthenticationResult:
    """Turn a username and a password into a token.

    The client header is **mandatory here and nowhere else**, and an absent or unreadable one is a
    `400` rather than a `401`: a client reading it as `401` tells its user that their password is
    wrong, when what happened is that the client sent a broken header.
    """
    info = require_client_authorization(
        request.headers.get("X-Emby-Authorization") or request.headers.get("Authorization")
    )
    remote = request.client.host if request.client else None
    result: AuthResult = authenticator.authenticate(body.username, body.pw, info, remote)

    return AuthenticationResult(
        user=to_wire(result.user, state),
        session_info=session_models.to_wire(
            result.session, result.user.name, state.server_id, result.session.last_activity_date
        ),
        access_token=result.token.secret,
        server_id=state.server_id,
    )


@router.get("/Users/Public")
async def public_users(
    request: Request, state: Annotated[ServerState, Depends(get_state)]
) -> list[UserDto]:
    """The users a login screen shows. Unauthenticated.

    **An empty array is a valid `200`**: an installation where every user is hidden legitimately
    returns none (spec section 3.4).
    """
    factory = get_sessions(request)
    with session_scope(factory) as opened:
        users = UserRepository(opened)
        listed = users.visible_on_login_screens()
        return [to_wire(user, state, users.library_access(user.id)) for user in listed]


@router.get("/Users/Me")
async def current_user(
    request: Request,
    user: Annotated[DomainUser, Depends(require_user)],
    state: Annotated[ServerState, Depends(get_state)],
) -> UserDto:
    with session_scope(get_sessions(request)) as opened:
        access = UserRepository(opened).library_access(user.id)
    return to_wire(user, state, access)


@router.post("/Users/Configuration", status_code=204)
async def update_configuration(
    request: Request,
    user: Annotated[DomainUser, Depends(require_user)],
) -> Response:
    """Replace the authenticated user's configuration. `204`, and no body.

    **Replaces rather than merges**, and every property survives - including the fourteen v1 does
    not act on. A client that round-trips a document from a newer server must get its own data
    back, which is what makes this a blob rather than columns (plan section 6.4).
    """
    document = await request.json()
    if not isinstance(document, dict):
        document = {}
    with session_scope(get_sessions(request)) as opened:
        UserRepository(opened).replace_configuration(user.id, document)
    return Response(status_code=204)


@router.get("/Users/{userId}")
async def user_by_id(
    request: Request,
    userId: str,  # noqa: N803 - the reference's spelling, and it reaches the wire
    user: Annotated[DomainUser, Depends(require_user)],
    state: Annotated[ServerState, Depends(get_state)],
) -> UserDto:
    """A user may always read themselves; an administrator may read anybody.

    Anyone else is a `403` - a `404` would tell an ordinary user which identifiers exist, and a
    `401` would send their client round the login loop for a permission it will never be granted.
    """
    if userId != user.id and not user.is_administrator:
        raise ForbiddenError("a user may only read themselves")

    with session_scope(get_sessions(request)) as opened:
        users = UserRepository(opened)
        found = users.by_id(userId)
        if found is None:
            # An identifier nobody has. Answered as a refusal rather than as a miss, for the same
            # reason as above: the two are indistinguishable to a caller who may not look.
            raise UnauthenticatedError if userId == user.id else ForbiddenError("no such user")
        access = users.library_access(found.id)
    return to_wire(found, state, access)


def sessions_for(request: Request, user: DomainUser) -> list[session_models.SessionInfo]:
    """Shared with `api/sessions.py` at T12; here so the registry overlay lives in one place."""
    registry = request.app.state.registry
    state: ServerState = request.app.state.server_state
    with session_scope(get_sessions(request)) as opened:
        found = SessionRepository(opened).for_user(user.id)
    return [
        session_models.to_wire(
            one, user.name, state.server_id, registry.activity(one.id) or one.last_activity_date
        )
        for one in found
    ]


__all__ = ["AuthenticateByName", "AuthenticationResult", "UserDto", "router", "to_wire"]
