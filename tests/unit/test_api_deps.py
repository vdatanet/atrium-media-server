# SPDX-License-Identifier: GPL-3.0-or-later
"""The authentication seam, and the exact shape of a refusal."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import Depends, FastAPI

from atrium.api.deps import require_user
from atrium.compat.errors import EXCEPTION_HANDLERS, UnauthenticatedError, empty_error
from atrium.domain.user import User


@pytest.fixture
def app() -> FastAPI:
    built = FastAPI(exception_handlers=dict(EXCEPTION_HANDLERS))

    @built.get("/System/Info")
    def info(user: User = Depends(require_user)) -> dict[str, str]:  # noqa: B008
        return {"Seen": user.name}

    return built


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium") as opened:
        yield opened


# --------------------------------------------------------------------------------------------
# The seam refuses
# --------------------------------------------------------------------------------------------


async def test_a_gated_route_refuses(client: httpx.AsyncClient) -> None:
    """The correct answer for a server that cannot yet authenticate anyone.

    The alternative is a route that appears to work and is not protected.
    """
    assert (await client.get("/System/Info")).status_code == 401


# --------------------------------------------------------------------------------------------
# The refusal's shape, measured rather than assumed
# --------------------------------------------------------------------------------------------


async def test_the_refusal_has_no_body(client: httpx.AsyncClient) -> None:
    """The reference sends a status line and nothing else.

    FastAPI's own `HTTPException` would send `{"detail": "Not authenticated"}` as JSON, which is a
    difference on every gated route in the project.
    """
    refused = await client.get("/System/Info")
    assert refused.content == b""
    assert refused.headers.get("content-length") == "0"


async def test_the_refusal_has_no_content_type(client: httpx.AsyncClient) -> None:
    assert "content-type" not in (await client.get("/System/Info")).headers


async def test_the_refusal_has_no_www_authenticate(client: httpx.AsyncClient) -> None:
    """RFC 7235 says a 401 SHOULD carry one. The reference does not, and matching is also safer.

    `WWW-Authenticate: Basic` makes a browser open a credentials dialog, on routes no browser was
    meant to drive.
    """
    assert "www-authenticate" not in (await client.get("/System/Info")).headers


def test_empty_error_is_empty_for_any_status() -> None:
    for status in (401, 403, 404):
        assert empty_error(status).status_code == status
        assert empty_error(status).body == b""


# --------------------------------------------------------------------------------------------
# The seam is a seam
# --------------------------------------------------------------------------------------------


async def test_an_override_reaches_the_route_body(app: FastAPI, client: httpx.AsyncClient) -> None:
    """How 001 tests the authenticated path without shipping a credential.

    Feature 002 replaces the dependency's body. Nothing here has to change when it does, which is
    the entire point of settling the signature before the implementation.
    """
    app.dependency_overrides[require_user] = lambda: User(id="a" * 32, name="joan")
    served = await client.get("/System/Info")
    assert served.status_code == 200
    assert served.json() == {"Seen": "joan"}


async def test_removing_the_override_restores_the_refusal(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """An override must not leak between tests, or every later gate test passes for free."""
    app.dependency_overrides[require_user] = lambda: User(id="a" * 32, name="joan")
    assert (await client.get("/System/Info")).status_code == 200
    app.dependency_overrides.clear()
    assert (await client.get("/System/Info")).status_code == 401


async def test_the_seam_returns_the_type_002_will_return(app: FastAPI) -> None:
    """The signature is the contract.

    A change here is a finding for 001's plan, not a quiet edit.
    """
    import inspect

    signature = inspect.signature(require_user)
    assert signature.return_annotation in (User, "User")
    assert list(signature.parameters) == ["request"]


def test_the_exception_is_what_is_registered() -> None:
    assert UnauthenticatedError in EXCEPTION_HANDLERS
