# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependencies routes declare.

`require_user` is the **authentication seam**. Feature 001 settled its signature and left the body
refusing everything, so that routes could be gated by something real before there was anything to
authenticate with. Feature 002 replaced the body.

**The signature did not change**, which was the point of defining it early: 001's own tests reach
the authenticated path through `app.dependency_overrides` and still pass unmodified. If it had
needed to change, that would have been a finding for 001's plan and a change to this docstring -
not a quiet edit.

## What a refusal looks like here

| Situation | Answer |
|---|---|
| No token at all | empty `401`, measured |
| A token nothing knows | empty `401`, measured, and byte-identical to the one above |
| A token whose account is disabled | `403` ⚠️ **shape not measured**, see below |
| A valid token, and the account may not do this | `403` ⚠️ same |

The two measured rows are `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11,
2026-08-26]`.

A token belonging to a disabled account answers `403` rather than `401` because a client that
re-authenticates on `401` would be sent to `AuthenticateByName`, which answers `403` for that
account anyway - so `401` buys a round trip and arrives at the same place. The reference's own
answer here is **not measured**: it needs a live token whose user is disabled afterwards, which
means an account somebody is willing to lock out of their own server (spec section 7, OQ-5).

## Three reads per authenticated request

Resolve the token, find its session, load the user. That is three indexed lookups where a joined
query would do one, and it is deliberate for now: the repositories return domain objects, and a
join that returned a row would have to cross the boundary architecture section 1 exists to keep
closed. Collapsing them stays possible **behind** that boundary, which is where an optimisation
belongs when something measures that it is needed.

See specs/001-server-identity-and-discovery/plan.md section 1 and section 5, and
specs/002-authentication-users-and-sessions/plan.md section 5.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from atrium.compat.auth import extract_token
from atrium.compat.errors import ForbiddenError, UnauthenticatedError
from atrium.config.paths import DataPaths
from atrium.config.settings import Settings
from atrium.config.state import ServerState
from atrium.db.engine import session_scope
from atrium.db.repositories import SessionRepository, TokenRepository, UserRepository
from atrium.domain.user import User
from atrium.users.passwords import Passwords
from atrium.users.service import Authenticator
from atrium.users.sessions import SessionRegistry


def get_settings(request: Request) -> Settings:
    """The operator's configuration, put on the application by its factory."""
    settings: Settings = request.app.state.settings
    return settings


def get_state(request: Request) -> ServerState:
    """The server's own record of itself, including the identity it must never regenerate."""
    state: ServerState = request.app.state.server_state
    return state


def get_paths(request: Request) -> DataPaths:
    paths: DataPaths = request.app.state.paths
    return paths


def get_sessions(request: Request) -> sessionmaker[OrmSession]:
    factory: sessionmaker[OrmSession] = request.app.state.sessions
    return factory


def get_registry(request: Request) -> SessionRegistry:
    registry: SessionRegistry = request.app.state.registry
    return registry


def get_authenticator(request: Request) -> Authenticator:
    authenticator: Authenticator = request.app.state.authenticator
    return authenticator


def get_passwords(request: Request) -> Passwords:
    passwords: Passwords = request.app.state.passwords
    return passwords


async def require_user(request: Request) -> User:
    """Resolve any of the five token mechanisms to a user, or refuse.

    Feature 002 supplies the resolution. The refusal for a request carrying nothing is unchanged
    from 001's - the same empty `401`, which is what the reference sends and what 001's tests
    already assert.
    """
    token = extract_token(request)
    if not token:
        raise UnauthenticatedError

    factory = get_sessions(request)
    registry = get_registry(request)

    with session_scope(factory) as opened:
        record = TokenRepository(opened).resolve(token)
        if record is None:
            raise UnauthenticatedError

        user = UserRepository(opened).by_id(record.user_id)
        if user is None:
            # The foreign key cascades, so this is a row that should not exist. Refusing beats
            # trusting it: a token pointing at nobody is not a credential.
            raise UnauthenticatedError

        if user.is_disabled:
            raise ForbiddenError("the account is disabled")

        session = SessionRepository(opened).by_device(user.id, record.device_id)

    if session is not None:
        # In memory. Writing it here would take a SQLite write lock on every authenticated
        # request, which is the whole reason the registry exists (plan section 6.5).
        registry.touch(record.token_sha256, session.id)

    # Left for the routes that need to know *which* session asked - `/Sessions/Capabilities/Full`
    # applies to the caller's own. Stashed rather than re-resolved, because resolving it twice
    # means two more reads for something already in hand.
    request.state.token_sha256 = record.token_sha256
    request.state.session_id = session.id if session is not None else None
    return user


__all__ = [
    "get_authenticator",
    "get_passwords",
    "get_paths",
    "get_registry",
    "get_sessions",
    "get_settings",
    "get_state",
    "require_user",
]
