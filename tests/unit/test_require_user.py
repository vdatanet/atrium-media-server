# SPDX-License-Identifier: GPL-3.0-or-later
"""The seam, implemented: a token in, a user out, and the three ways it refuses.

Driven through the application the factory builds, against `/System/Info` - the route feature 001
gated before there was anything to gate it with. That is the point of the seam, so it is what this
tests against rather than a route invented here.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.session import IssuedToken
from atrium.domain.user import User
from atrium.users.passwords import Passwords

PASSWORD = "correct horse battery staple"


def make_user(app: FastAPI, name: str = "Joan", **overrides: object) -> User:
    passwords: Passwords = app.state.passwords
    fields: dict[str, object] = {
        "id": new_id(),
        "name": name,
        "password_hash": passwords.hash(PASSWORD),
    }
    fields.update(overrides)
    with app.state.sessions.begin() as opened:
        return UserRepository(opened).add(User(**fields))  # type: ignore[arg-type]


def log_in(app: FastAPI, name: str = "Joan") -> IssuedToken:
    from atrium.compat.auth import ClientInfo

    info = ClientInfo(client="Atrium Test", device="Bench", device_id="bench-1", version="1.0")
    return app.state.authenticator.authenticate(name, PASSWORD, info).token


@pytest.fixture
def joan(app: FastAPI) -> User:
    return make_user(app)


# --------------------------------------------------------------------------------------------
# A token reaches the route body
# --------------------------------------------------------------------------------------------


async def test_a_valid_token_reaches_the_route(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    issued = log_in(app)
    served = await client.get("/System/Info", headers={"X-Emby-Token": issued.secret})
    assert served.status_code == 200
    assert served.json()["Id"] == app.state.server_state.server_id


async def test_the_query_form_reaches_it_too(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """The form an image loader or a media player is handed, which sets no headers."""
    issued = log_in(app)
    assert (await client.get(f"/System/Info?api_key={issued.secret}")).status_code == 200


# --------------------------------------------------------------------------------------------
# The three refusals
# --------------------------------------------------------------------------------------------


async def test_no_token_is_the_empty_401_that_001_measured(client: httpx.AsyncClient) -> None:
    """Unchanged by this task, which is the whole reason 001's tests still pass unmodified."""
    refused = await client.get("/System/Info")
    assert refused.status_code == 401
    assert refused.content == b""
    assert "content-type" not in refused.headers


async def test_an_unknown_token_is_the_same_refusal_byte_for_byte(
    client: httpx.AsyncClient, joan: User
) -> None:
    """Measured: the reference answers a bogus token exactly as it answers none at all."""
    nothing = await client.get("/System/Info")
    unknown = await client.get("/System/Info", headers={"X-Emby-Token": "0" * 32})
    assert unknown.status_code == nothing.status_code == 401
    assert unknown.content == nothing.content == b""
    assert "content-type" not in unknown.headers


async def test_a_token_whose_account_was_disabled_is_403(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """A client re-authenticates on `401`, and `AuthenticateByName` answers `403` for this
    account anyway - so `401` here buys a round trip and arrives at the same place."""
    issued = log_in(app)
    with app.state.sessions.begin() as opened:
        UserRepository(opened).set_policy(joan.id, {"is_disabled": True}, {})

    refused = await client.get("/System/Info", headers={"X-Emby-Token": issued.secret})
    assert refused.status_code == 403
    # ⚠️ Not measured, and this line is the second analogy in a row rather than a finding. It read
    # `b""` until 009 T2, by analogy with the empty `401` beside it; the shared handler now sends
    # the controller's 25 bytes, measured for a *permission* refusal and not for this one. 002
    # spec section 7 (OQ-5) still holds the question, and discharging it means disabling a real
    # account that already holds a live token.
    assert refused.content == b"Error processing request."


async def test_a_malformed_client_header_does_not_authenticate(
    client: httpx.AsyncClient, joan: User
) -> None:
    """`Token = x` is a `401` at the reference, and the parser refuses it for that reason."""
    refused = await client.get(
        "/System/Info", headers={"X-Emby-Authorization": 'MediaBrowser Token = "abc"'}
    )
    assert refused.status_code == 401


# --------------------------------------------------------------------------------------------
# What an authenticated request does besides answering
# --------------------------------------------------------------------------------------------


async def test_an_authenticated_request_advances_activity_in_memory(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """In memory, not in the database: writing it here would take a SQLite write lock on every
    authenticated request, which is the whole reason the registry exists."""
    issued = log_in(app)
    registry = app.state.registry
    registry.flush()
    assert registry.snapshot() == {}

    await client.get("/System/Info", headers={"X-Emby-Token": issued.secret})

    snapshot = registry.snapshot()
    assert len(snapshot) == 1
    assert issued.record.device_id == "bench-1"


async def test_a_refused_request_advances_nothing(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    registry = app.state.registry
    registry.flush()
    await client.get("/System/Info", headers={"X-Emby-Token": "0" * 32})
    assert registry.snapshot() == {}


# --------------------------------------------------------------------------------------------
# The signature is still the contract
# --------------------------------------------------------------------------------------------


def test_the_signature_did_not_change() -> None:
    """001 settled it before there was an implementation, and 002 replaced the body only.

    A change here is a finding for 001's plan and a change to its docstring, not a quiet edit -
    which is why this is asserted twice, once in 001's tests and once here.
    """
    import inspect

    from atrium.api.deps import require_user

    signature = inspect.signature(require_user)
    assert list(signature.parameters) == ["request"]
    assert signature.return_annotation in (User, "User")
