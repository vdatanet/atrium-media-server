# SPDX-License-Identifier: GPL-3.0-or-later
"""Headers on every response: one Atrium's, one the reference's, one nobody would have guessed."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from atrium import REFERENCE_VERSION, __version__
from atrium.compat.middleware import ResponseHeadersMiddleware
from atrium.compat.responses import JSON_MEDIA_TYPE, AtriumJSONResponse


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI(default_response_class=AtriumJSONResponse)

    @app.get("/System/Ping")
    def ping() -> str:
        return "Jellyfin Server"

    app.add_middleware(ResponseHeadersMiddleware)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium") as opened:
        yield opened


# --------------------------------------------------------------------------------------------
# Server: the one place the truth is told
# --------------------------------------------------------------------------------------------


async def test_the_server_header_names_atrium(client: httpx.AsyncClient) -> None:
    assert (await client.get("/System/Ping")).headers["server"] == f"Atrium/{__version__}"


async def test_the_server_header_is_not_the_reference_version(client: httpx.AsyncClient) -> None:
    """The two version constants exist to be different, and a swap must fail rather than pass.

    `Version` in the API's own responses is the reference's, because clients gate capabilities on
    it. `Server` is Atrium's, because people read it. Asserting against both constants is what
    makes a future edit that confuses them break here instead of somewhere subtle.
    """
    server = (await client.get("/System/Ping")).headers["server"]
    assert REFERENCE_VERSION not in server
    assert __version__ != REFERENCE_VERSION


async def test_the_underlying_server_header_is_replaced(client: httpx.AsyncClient) -> None:
    """Uvicorn stamps its own `server: uvicorn`; whatever is underneath must not show through."""
    header = (await client.get("/System/Ping")).headers["server"]
    assert "uvicorn" not in header.lower()
    assert "kestrel" not in header.lower()


# --------------------------------------------------------------------------------------------
# X-Response-Time-ms: the reference's, found by looking at real traffic
# --------------------------------------------------------------------------------------------


async def test_the_response_time_header_is_present(client: httpx.AsyncClient) -> None:
    """On every response upstream, because its middleware is registered unconditionally.

    This project did not know the header existed until a real request was inspected. Neither
    specification mentioned it, and no amount of reading either codebase would have surfaced it.
    """
    assert "x-response-time-ms" in (await client.get("/System/Ping")).headers


async def test_the_response_time_is_a_number(client: httpx.AsyncClient) -> None:
    value = (await client.get("/System/Ping")).headers["x-response-time-ms"]
    assert float(value) >= 0
    assert "." in value, "the reference sends fractional milliseconds, e.g. 2.1329"


async def test_the_response_time_is_measured_not_constant(client: httpx.AsyncClient) -> None:
    values = {(await client.get("/System/Ping")).headers["x-response-time-ms"] for _ in range(20)}
    assert len(values) > 1, "a constant would mean the header is decorative rather than measured"


# --------------------------------------------------------------------------------------------
# Content-Type: a difference on every response in the project
# --------------------------------------------------------------------------------------------


async def test_json_carries_the_charset(client: httpx.AsyncClient) -> None:
    """Starlette appends `charset=utf-8` only to `text/*`; the reference sends it on JSON too."""
    assert (await client.get("/System/Ping")).headers["content-type"] == JSON_MEDIA_TYPE


async def test_the_plain_starlette_class_would_not(client: httpx.AsyncClient) -> None:
    """What the difference actually is, recorded rather than described."""
    from fastapi.responses import JSONResponse

    assert JSONResponse.media_type == "application/json"
    assert AtriumJSONResponse.media_type == "application/json; charset=utf-8"
