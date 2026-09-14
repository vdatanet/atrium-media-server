# SPDX-License-Identifier: GPL-3.0-or-later
"""The address a request is from, and whether it is this machine (014 T3, plan section 6.1).

**Every case names its peer.** `httpx.ASGITransport` defaults to `127.0.0.1` and the shared
`client` fixture to `192.168.1.50`, so a test that forgets the address is silently testing the
other branch - which is why `ask` takes it as a required argument.

The middleware is exercised over a bare Starlette application whose one route reports what the
request looks like after resolution, so a case asserts the resolved `request.client` beside the
answer. The last section drives the application `create_app` builds, which is what says the
middleware is wired where the plan put it and not only correct on its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from atrium.compat.client_address import (
    ClientAddressMiddleware,
    is_loopback,
    is_this_machine,
)
from atrium.config.settings import NetworkSettings
from atrium.server import create_app
from tests.conftest import FAST_PASSWORDS, data_dir

DEFAULT = NetworkSettings().trusted_proxies

#: A documentation range, so no test machine's own addressing can make it accidentally local.
REMOTE = "203.0.113.9"
LAN = "192.168.1.50"


async def _report(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "local": is_this_machine(request),
            "client": request.client.host if request.client else None,
            "scheme": request.url.scheme,
        }
    )


def _resolving(trusted_proxies: Sequence[str]) -> ClientAddressMiddleware:
    return ClientAddressMiddleware(
        Starlette(routes=[Route("/", _report)]), trusted_proxies=trusted_proxies
    )


async def ask(
    peer: str,
    headers: dict[str, str] | None = None,
    *,
    trusted_proxies: Sequence[str] = DEFAULT,
) -> dict[str, object]:
    """What the request from `peer` resolved to. The peer is required, never defaulted."""
    transport = httpx.ASGITransport(app=_resolving(trusted_proxies), client=(peer, 51234))
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        response = await opened.get("/", headers=headers or {})
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


# --------------------------------------------------------------------------------------------
# Loopback, and only loopback
# --------------------------------------------------------------------------------------------


def test_the_default_trusts_ipv4_loopback_and_nothing_else() -> None:
    """uvicorn's own default, so an existing install resolves addresses exactly as it did."""
    assert DEFAULT == ["127.0.0.1"]


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.8.9.1", "::1", "::ffff:127.0.0.1"],
    ids=["ipv4", "ipv4-net", "ipv6", "ipv4-mapped-ipv6"],
)
def test_loopback_is_loopback(host: str) -> None:
    assert is_loopback(host)


@pytest.mark.parametrize(
    "host",
    [LAN, "10.0.0.1", "::ffff:192.168.1.50", "fe80::1", REMOTE, "", None, "atrium.local"],
)
def test_nothing_else_is(host: str | None) -> None:
    """A LAN address is from elsewhere even when this machine holds it (spec section 3.1)."""
    assert not is_loopback(host)


@pytest.mark.parametrize(
    "peer", ["127.0.0.1", "::1", "::ffff:127.0.0.1"], ids=["ipv4", "ipv6", "ipv4-mapped-ipv6"]
)
async def test_a_loopback_peer_with_no_header_is_this_machine(peer: str) -> None:
    assert await ask(peer) == {"local": True, "client": peer, "scheme": "http"}


async def test_a_lan_peer_is_not_this_machine() -> None:
    assert (await ask(LAN))["local"] is False


# --------------------------------------------------------------------------------------------
# A forwarded address, believed only from a declared proxy
# --------------------------------------------------------------------------------------------


async def test_an_untrusted_loopback_peer_forwarding_loopback_is_not_this_machine() -> None:
    """A proxy on this machine nobody declared. Its address is ignored and it is from elsewhere."""
    answer = await ask("127.0.0.1", {"X-Forwarded-For": "127.0.0.1"}, trusted_proxies=["10.0.0.2"])
    assert answer["local"] is False
    assert answer["client"] == "127.0.0.1", "the header was not applied"


async def test_ipv6_loopback_is_not_a_declared_proxy_under_the_default() -> None:
    """The default list names `127.0.0.1` alone, so a proxy reaching the server over `::1` is
    undeclared - and a header it sends is noticed rather than believed."""
    answer = await ask("::1", {"X-Forwarded-For": "::1"})
    assert answer == {"local": False, "client": "::1", "scheme": "http"}


@pytest.mark.parametrize(
    ("header", "value"),
    [("X-Forwarded-For", REMOTE), ("Forwarded", f"for={REMOTE}"), ("X-Real-IP", REMOTE)],
)
async def test_any_forwarding_header_from_an_undeclared_proxy_is_from_elsewhere(
    header: str, value: str
) -> None:
    answer = await ask("127.0.0.1", {header: value}, trusted_proxies=["10.0.0.2"])
    assert answer == {"local": False, "client": "127.0.0.1", "scheme": "http"}


async def test_a_trusted_proxy_forwarding_a_remote_address_is_that_address() -> None:
    answer = await ask("127.0.0.1", {"X-Forwarded-For": REMOTE})
    assert answer["local"] is False
    assert answer["client"] == REMOTE


async def test_a_trusted_proxy_forwarding_loopback_is_this_machine() -> None:
    """The client on the proxy's machine, arriving through it: loopback is its own address."""
    assert (await ask("127.0.0.1", {"X-Forwarded-For": "127.0.0.1"}))["local"] is True


async def test_a_trusted_proxy_is_matched_the_way_the_resolver_matches_it() -> None:
    """A network rather than an address - the trust answer is uvicorn's own, not a second copy."""
    answer = await ask(
        "10.0.0.2", {"X-Forwarded-For": "127.0.0.1"}, trusted_proxies=["10.0.0.0/24"]
    )
    assert answer == {"local": True, "client": "127.0.0.1", "scheme": "http"}


async def test_a_remote_peer_claiming_loopback_is_ignored() -> None:
    answer = await ask(REMOTE, {"X-Forwarded-For": "127.0.0.1"})
    assert answer == {"local": False, "client": REMOTE, "scheme": "http"}


@pytest.mark.parametrize(
    ("header", "value"), [("Forwarded", f"for={REMOTE}"), ("X-Real-IP", REMOTE)]
)
async def test_a_trusted_proxy_forwarding_in_a_header_the_resolver_does_not_read_is_from_elsewhere(
    header: str, value: str
) -> None:
    """Trusted is not the same as believed (plan section 6.1, amended 2026-09-14).

    Only `X-Forwarded-For` is ever applied, so a declared proxy that names the client in
    `Forwarded` or `X-Real-IP` alone leaves the request at the proxy's own loopback address. Called
    local, every request such a proxy passes on would be admitted to the setup window.
    """
    answer = await ask("127.0.0.1", {header: value})
    assert answer == {"local": False, "client": "127.0.0.1", "scheme": "http"}


async def test_a_trusted_proxy_sending_both_is_decided_by_the_header_it_applied() -> None:
    answer = await ask("127.0.0.1", {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"})
    assert answer["local"] is True


async def test_a_request_the_middleware_never_saw_is_not_this_machine() -> None:
    """Nothing recorded the peer, so nothing can say a header was not believed: closed."""
    transport = httpx.ASGITransport(
        app=Starlette(routes=[Route("/", _report)]), client=("127.0.0.1", 51234)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        assert (await opened.get("/")).json()["local"] is False


# --------------------------------------------------------------------------------------------
# Wired into the application, outside every layer that reads the address
# --------------------------------------------------------------------------------------------


def _configured(root: Path, network: str) -> FastAPI:
    paths = data_dir(root)
    paths.config_file.write_text(f"{FAST_PASSWORDS}\n[network]\n{network}\n", encoding="utf-8")
    app = create_app(paths)
    app.state.readiness.mark_ready()
    return app


def test_the_middleware_is_the_outermost_and_carries_the_configured_list(tmp_path: Path) -> None:
    app = _configured(tmp_path / "atrium", 'trusted_proxies = ["10.0.0.2", "10.1.0.0/16"]')
    outermost = app.user_middleware[0]
    assert outermost.cls is ClientAddressMiddleware
    assert outermost.kwargs == {"trusted_proxies": ["10.0.0.2", "10.1.0.0/16"]}


@pytest.mark.parametrize(
    ("peer", "scheme"), [("127.0.0.1", "https"), (LAN, "http")], ids=["trusted", "untrusted"]
)
async def test_local_address_sees_the_scheme_uvicorn_used_to_resolve(
    tmp_path: Path, peer: str, scheme: str
) -> None:
    """`LocalAddress` (001) under `use_request_host`, the one tier that reads the scheme.

    uvicorn's default believed `X-Forwarded-Proto` from `127.0.0.1` and from nobody else, and so
    does this default - so a proxy on this machine saying `https` is advertised as it was before,
    and the same header from the LAN is still ignored.
    """
    app = _configured(tmp_path / "atrium", "use_request_host = true")
    transport = httpx.ASGITransport(app=app, client=(peer, 51234))
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        body = (
            await opened.get("/System/Info/Public", headers={"X-Forwarded-Proto": "https"})
        ).json()
    assert body["LocalAddress"] == f"{scheme}://atrium:8096"
