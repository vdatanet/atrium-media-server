# SPDX-License-Identifier: GPL-3.0-or-later
"""The readiness gate: what the server says while it is still starting."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from atrium.lifecycle import (
    DEFAULT_RETRY_AFTER_SECONDS,
    STARTING_MESSAGE,
    Readiness,
    ReadinessMiddleware,
)


@pytest.fixture
def readiness() -> Readiness:
    return Readiness()


@pytest.fixture
async def client(readiness: Readiness) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()

    @app.get("/System/Ping")
    def ping() -> str:
        return "Jellyfin Server"

    app.add_middleware(ReadinessMiddleware, readiness=readiness)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium") as opened:
        yield opened


# --------------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------------


async def test_a_request_while_starting_is_refused(client: httpx.AsyncClient) -> None:
    assert (await client.get("/System/Ping")).status_code == 503


async def test_the_same_request_is_served_once_ready(
    client: httpx.AsyncClient, readiness: Readiness
) -> None:
    readiness.mark_ready()
    served = await client.get("/System/Ping")
    assert served.status_code == 200
    assert served.json() == "Jellyfin Server"


async def test_the_gate_is_server_wide(client: httpx.AsyncClient) -> None:
    """Every one of the reference's 395 operations declares a 503, so nothing is exempt.

    Not even a liveness probe: `Retry-After` is what tells a health check the difference between
    starting and broken, which is more useful than a 200 that means nothing yet.
    """
    for path in ("/System/Ping", "/System/Info/Public", "/Items", "/anything"):
        assert (await client.get(path)).status_code == 503


# --------------------------------------------------------------------------------------------
# What the refusal carries
# --------------------------------------------------------------------------------------------


async def test_retry_after_is_full_seconds(client: httpx.AsyncClient) -> None:
    """The header that separates "starting" from "broken".

    Without it a 503 is indistinguishable from a server that is simply down, and a client that
    cannot tell will either give up or hammer.
    """
    header = (await client.get("/System/Ping")).headers["retry-after"]
    assert header == str(DEFAULT_RETRY_AFTER_SECONDS)
    assert header.isdigit(), "the reference declares an integer, not an HTTP-date"


async def test_the_message_header_says_why(client: httpx.AsyncClient) -> None:
    assert (await client.get("/System/Ping")).headers["message"] == STARTING_MESSAGE


async def test_the_body_is_html_not_json(client: httpx.AsyncClient) -> None:
    """`text/html`, as the pinned document declares. A client that parses it as JSON is wrong."""
    refused = await client.get("/System/Ping")
    assert refused.headers["content-type"].startswith("text/html")
    assert STARTING_MESSAGE in refused.text


async def test_the_body_length_is_declared(client: httpx.AsyncClient) -> None:
    refused = await client.get("/System/Ping")
    assert int(refused.headers["content-length"]) == len(refused.content)


# --------------------------------------------------------------------------------------------
# Going out of service without stopping
# --------------------------------------------------------------------------------------------


async def test_mark_unavailable_takes_the_server_out_of_service(
    client: httpx.AsyncClient, readiness: Readiness
) -> None:
    readiness.mark_ready()
    assert (await client.get("/System/Ping")).status_code == 200

    readiness.mark_unavailable("Rebuilding the library.", retry_after_seconds=60)
    refused = await client.get("/System/Ping")
    assert refused.status_code == 503
    assert refused.headers["message"] == "Rebuilding the library."
    assert refused.headers["retry-after"] == "60"


def test_two_instances_do_not_share_state() -> None:
    """Readiness is an object rather than a module flag, so a test cannot leak into the next."""
    first, second = Readiness(), Readiness()
    first.mark_ready()
    assert second.ready is False
