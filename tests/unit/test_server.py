# SPDX-License-Identifier: GPL-3.0-or-later
"""The application factory: what an Atrium server is made of."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium import REFERENCE_VERSION, __version__
from atrium.server import create_app, main
from tests.conftest import data_dir


@pytest.fixture
def unstarted(tmp_path: Path) -> FastAPI:
    """An instance whose readiness gate has not been opened, as before startup finishes."""
    return create_app(data_dir(tmp_path / "atrium"))


# --------------------------------------------------------------------------------------------
# It builds and it serves
# --------------------------------------------------------------------------------------------


def test_it_creates_the_data_directory(tmp_path: Path) -> None:
    root = tmp_path / "somewhere-new"
    create_app(data_dir(root))
    assert (root / "cache").is_dir()
    assert (root / "state.json").is_file()


async def test_it_serves_public_info(client: httpx.AsyncClient) -> None:
    """The `client` fixture now drives an app the factory built, not one assembled by hand."""
    assert (await client.get("/System/Info/Public")).status_code == 200


async def test_the_lifespan_opens_the_gate(tmp_path: Path) -> None:
    """Driven through Starlette's own lifespan context rather than `TestClient`.

    `TestClient` reaches the same place and emits a deprecation warning doing it; running the
    lifespan directly is also closer to what a server actually does.
    """
    built = create_app(data_dir(tmp_path / "atrium"))
    assert built.state.readiness.ready is False

    async with built.router.lifespan_context(built):
        assert built.state.readiness.ready is True
        transport = httpx.ASGITransport(app=built)
        async with httpx.AsyncClient(transport=transport, base_url="http://atrium") as opened:
            assert (await opened.get("/System/Info/Public")).status_code == 200


# --------------------------------------------------------------------------------------------
# Middleware order, which is load-bearing
# --------------------------------------------------------------------------------------------


async def test_a_refusal_while_starting_still_carries_the_headers(unstarted: FastAPI) -> None:
    """Response headers wrap the readiness gate, not the other way round.

    Starlette makes the last middleware added the outermost, so the order in the factory is what
    puts `Server` and `X-Response-Time-ms` on a 503. The reference's own response-time middleware
    sits outside everything too.
    """
    transport = httpx.ASGITransport(app=unstarted)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium") as opened:
        refused = await opened.get("/System/Info/Public")
    assert refused.status_code == 503
    assert refused.headers["server"] == f"Atrium/{__version__}"
    assert "x-response-time-ms" in refused.headers
    assert refused.headers["retry-after"].isdigit()


# --------------------------------------------------------------------------------------------
# Two instances share nothing
# --------------------------------------------------------------------------------------------


def test_two_instances_have_two_identities(tmp_path: Path) -> None:
    first = create_app(data_dir(tmp_path / "one"))
    second = create_app(data_dir(tmp_path / "two"))
    assert first.state.server_state.server_id != second.state.server_state.server_id


def test_two_instances_do_not_share_readiness(tmp_path: Path) -> None:
    """Every piece of state hangs off the application, not off a module.

    Without this a test suite that builds a server per test would leak the first one's readiness
    into every later one, and every gate assertion after the first would pass for free.
    """
    first = create_app(data_dir(tmp_path / "one"))
    second = create_app(data_dir(tmp_path / "two"))
    first.state.readiness.mark_ready()
    assert second.state.readiness.ready is False


def test_the_same_directory_gives_the_same_identity(tmp_path: Path) -> None:
    root = data_dir(tmp_path / "shared")
    assert create_app(root).state.server_state.server_id == (
        create_app(root).state.server_state.server_id
    )


# --------------------------------------------------------------------------------------------
# What is deliberately not served
# --------------------------------------------------------------------------------------------


async def test_no_documentation_routes_are_served(client: httpx.AsyncClient) -> None:
    """Principle VI: no endpoint without a named consumer.

    The reference serves its OpenAPI document at /api-docs/openapi.json. That route is not in
    docs/compatibility/surface.yaml and no analysed client asks for it.
    """
    for path in ("/openapi.json", "/docs", "/redoc", "/api-docs/openapi.json"):
        assert (await client.get(path)).status_code == 404


def test_the_document_is_still_generated(unstarted: FastAPI) -> None:
    """Not serving it is a routing decision. ADR-0002 chose FastAPI for the generated document,
    and the contract diff that argument rests on needs it to exist, not to be reachable."""
    document = unstarted.openapi()
    assert "/System/Info/Public" in document["paths"]
    assert "PublicSystemInfo" in document["components"]["schemas"]


# --------------------------------------------------------------------------------------------
# The entry point
# --------------------------------------------------------------------------------------------


def test_version_prints_both_versions(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--version"]) == 0
    printed = capsys.readouterr().out
    assert __version__ in printed
    assert REFERENCE_VERSION in printed


def test_a_broken_data_directory_exits_with_a_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refusing to start beats starting wrongly.

    And the operator needs a reason, not a traceback.
    """
    blocked = tmp_path / "a-file-not-a-directory"
    blocked.write_text("", encoding="utf-8")

    assert main(["--data-dir", str(blocked)]) == 1
    error = capsys.readouterr().err
    assert error.startswith("atrium:")
    assert "Traceback" not in error
