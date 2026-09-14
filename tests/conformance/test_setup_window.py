# SPDX-License-Identifier: GPL-3.0-or-later
"""The setup window: this machine during setup, or an administrator (014 spec section 3.1, AC-5).

**Every request names the address it is from, and the helper will not let one forget.**
`httpx.ASGITransport` answers `127.0.0.1` when nothing is said and the shared `client` fixture
`192.168.1.50`, so a test that forgets its address is testing the other branch of the one rule
this module exists for - which is why `ask` takes the peer as a required positional argument and
builds its own transport per request (014 plan section 8).

The applications are built by `create_app`, through the `app` fixture, because `is_this_machine`
answers "not local" for a request the address middleware never saw: an application assembled by
hand would refuse every local caller and make the admitted rows unreachable.

**Five routes share the window, and a sixth does not.** The three startup routes (014 T4) and the
two library-structure routes (T7) are one table; `POST /Library/Refresh` requires an administrator
in both states (spec section 3.1, AC-6), so its rows are written apart - and the one that tells the
two policies apart is a caller on this machine with no token during setup, admitted by the table
and refused `401` by the refresh.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.user import User

pytestmark = pytest.mark.conformance

LOOPBACK = "127.0.0.1"
#: A documentation range, so no test machine's own addressing can make it accidentally local.
REMOTE = "203.0.113.9"
#: What a client on the server's own machine is seen as when it addresses the server by the
#: machine's network address rather than by loopback.
THIS_MACHINE_ON_THE_LAN = "192.168.1.10"
ELSEWHERE = "192.168.1.50"

PASSWORD = "setup window password"
CLIENT_HEADER = (
    'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="{device}", Version="1"'
)


async def ask(
    app: FastAPI,
    peer: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    json: Any = None,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    """One request to `app` from `peer`. The peer is required and never defaulted."""
    sent = dict(headers or {})
    if token is not None:
        sent["X-Emby-Token"] = token
    transport = httpx.ASGITransport(app=app, client=(peer, 51234))
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        return await opened.request(method, path, json=json, headers=sent, params=params)


def make_account(app: FastAPI, name: str, *, administrator: bool) -> User:
    with app.state.sessions.begin() as opened:
        return UserRepository(opened).add(
            User(
                id=new_id(),
                name=name,
                is_administrator=administrator,
                password_hash=app.state.passwords.hash(PASSWORD),
            )
        )


async def sign_in(app: FastAPI, peer: str, name: str, password: str = PASSWORD) -> httpx.Response:
    return await ask(
        app,
        peer,
        "POST",
        "/Users/AuthenticateByName",
        json={"Username": name, "Pw": password},
        headers={"X-Emby-Authorization": CLIENT_HEADER.format(device=f"{name}-{peer}")},
    )


async def token_for(app: FastAPI, peer: str, name: str) -> str:
    answered = await sign_in(app, peer, name)
    assert answered.status_code == 200, answered.content
    token: str = answered.json()["AccessToken"]
    return token


async def finish_setup(app: FastAPI) -> None:
    """Through the route, from this machine, so "finished" is the state a client produced."""
    assert (await ask(app, LOOPBACK, "POST", "/Startup/Complete")).status_code == 204


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    admitted: int
    body: Any = None


#: The five setup routes, each with the answer it gives a caller the window admits. The
#: accounts below exist, so `POST /Startup/User` has an account to update and the read creates
#: nothing; the update names the first account by its own name, so nothing is renamed. The add
#: names no path and asks for no scan, so an admitted one is an empty library and starts nothing.
ROUTES = (
    Route("GET", "/Startup/User", 200),
    Route("POST", "/Startup/User", 204, {"Name": "Admin", "Password": "a new password"}),
    Route("POST", "/Startup/Complete", 204),
    Route("GET", "/Library/VirtualFolders", 200),
    Route("POST", "/Library/VirtualFolders?name=Window", 204),
)

CALLERS = ("no token", "unknown token", "non-administrator", "administrator")


@pytest.fixture
async def world(app: FastAPI) -> AsyncIterator[FastAPI]:
    """An administrator inserted first - so it is the first account - and a non-administrator.

    The scanner is stopped afterwards, because an admitted refresh starts its worker and a test
    must not leave a task behind it.
    """
    make_account(app, "Admin", administrator=True)
    make_account(app, "Viewer", administrator=False)
    yield app
    await app.state.scanner.stop()


async def credential(app: FastAPI, caller: str) -> str | None:
    """The token each kind of caller carries, obtained from the LAN so no request here is local."""
    if caller == "no token":
        return None
    if caller == "unknown token":
        return "0" * 32
    return await token_for(app, ELSEWHERE, "Admin" if caller == "administrator" else "Viewer")


def assert_admitted(answered: httpx.Response, route: Route) -> None:
    assert answered.status_code == route.admitted, (route, answered.status_code, answered.content)


def assert_refused_empty(answered: httpx.Response, status: int) -> None:
    """Both refusals carry no body and no `Content-Type` (spec section 3.1)."""
    assert answered.status_code == status, answered.content
    assert answered.content == b""
    assert "content-type" not in answered.headers


# --------------------------------------------------------------------------------------------
# Section 3.1's seven rows, over the three routes
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_unfinished_this_machine_admits_anyone(
    world: FastAPI, route: Route, caller: str
) -> None:
    """Row 1 - authenticated or not, and a token nothing knows is admitted too."""
    token = await credential(world, caller)
    answered = await ask(world, LOOPBACK, route.method, route.path, token=token, json=route.body)
    assert_admitted(answered, route)


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_unfinished_elsewhere_admits_an_administrator(world: FastAPI, route: Route) -> None:
    """Row 2."""
    token = await credential(world, "administrator")
    answered = await ask(world, ELSEWHERE, route.method, route.path, token=token, json=route.body)
    assert_admitted(answered, route)


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_unfinished_elsewhere_refuses_a_non_administrator_403(
    world: FastAPI, route: Route
) -> None:
    """Row 3."""
    token = await credential(world, "non-administrator")
    answered = await ask(world, ELSEWHERE, route.method, route.path, token=token, json=route.body)
    assert_refused_empty(answered, 403)
    assert world.state.server_state.startup_wizard_completed is False


@pytest.mark.parametrize("caller", ["no token", "unknown token"])
@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_unfinished_elsewhere_refuses_no_token_401(
    world: FastAPI, route: Route, caller: str
) -> None:
    """Row 4 - and a token nothing knows is no token, as it is everywhere else."""
    token = await credential(world, caller)
    answered = await ask(world, ELSEWHERE, route.method, route.path, token=token, json=route.body)
    assert_refused_empty(answered, 401)
    assert world.state.server_state.startup_wizard_completed is False


@pytest.mark.parametrize("peer", [LOOPBACK, ELSEWHERE])
@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_finished_admits_an_administrator_from_anywhere(
    world: FastAPI, route: Route, peer: str
) -> None:
    """Row 5."""
    await finish_setup(world)
    token = await credential(world, "administrator")
    answered = await ask(world, peer, route.method, route.path, token=token, json=route.body)
    assert_admitted(answered, route)


@pytest.mark.parametrize("peer", [LOOPBACK, ELSEWHERE])
@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_finished_refuses_a_non_administrator_403_from_anywhere(
    world: FastAPI, route: Route, peer: str
) -> None:
    """Row 6 - this machine included, which is the window closing."""
    await finish_setup(world)
    token = await credential(world, "non-administrator")
    answered = await ask(world, peer, route.method, route.path, token=token, json=route.body)
    assert_refused_empty(answered, 403)


@pytest.mark.parametrize("peer", [LOOPBACK, ELSEWHERE])
@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_finished_refuses_no_token_401_from_anywhere(
    world: FastAPI, route: Route, peer: str
) -> None:
    """Row 7."""
    await finish_setup(world)
    answered = await ask(world, peer, route.method, route.path, json=route.body)
    assert_refused_empty(answered, 401)


# --------------------------------------------------------------------------------------------
# What "this machine" is
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_this_machine_by_its_network_address_is_elsewhere(
    world: FastAPI, route: Route
) -> None:
    """A client on the server's machine addressing it by a LAN address is not loopback (AC-5)."""
    answered = await ask(world, THIS_MACHINE_ON_THE_LAN, route.method, route.path, json=route.body)
    assert_refused_empty(answered, 401)


@pytest.mark.parametrize("peer", ["::1", "::ffff:127.0.0.1"])
async def test_every_spelling_of_loopback_is_this_machine(world: FastAPI, peer: str) -> None:
    assert (await ask(world, peer, "GET", "/Startup/User")).status_code == 200


@pytest.mark.parametrize("route", ROUTES, ids=lambda route: f"{route.method} {route.path}")
async def test_a_forwarded_address_from_an_undeclared_loopback_proxy_is_elsewhere(
    world: FastAPI, route: Route
) -> None:
    """`::1` is loopback and not in the default trusted list, so its header was not believed."""
    answered = await ask(
        world,
        "::1",
        route.method,
        route.path,
        json=route.body,
        headers={"X-Forwarded-For": LOOPBACK},
    )
    assert_refused_empty(answered, 401)


async def test_a_declared_proxy_forwarding_in_a_header_nothing_applies_is_elsewhere(
    world: FastAPI,
) -> None:
    """`127.0.0.1` is declared, and `X-Real-IP` is not the header the resolution reads."""
    answered = await ask(world, LOOPBACK, "GET", "/Startup/User", headers={"X-Real-IP": REMOTE})
    assert_refused_empty(answered, 401)


async def test_a_declared_proxy_forwarding_a_remote_client_is_that_client(world: FastAPI) -> None:
    answered = await ask(
        world, LOOPBACK, "GET", "/Startup/User", headers={"X-Forwarded-For": REMOTE}
    )
    assert_refused_empty(answered, 401)


async def test_a_declared_proxy_forwarding_a_local_client_is_this_machine(world: FastAPI) -> None:
    answered = await ask(
        world, LOOPBACK, "GET", "/Startup/User", headers={"X-Forwarded-For": LOOPBACK}
    )
    assert answered.status_code == 200


async def test_a_remote_peer_claiming_loopback_is_elsewhere(world: FastAPI) -> None:
    answered = await ask(
        world, REMOTE, "GET", "/Startup/User", headers={"X-Forwarded-For": LOOPBACK}
    )
    assert_refused_empty(answered, 401)


# --------------------------------------------------------------------------------------------
# POST /Library/Refresh is not a setup operation
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("caller", ["no token", "unknown token"])
async def test_refresh_refuses_this_machine_with_no_token_401_during_setup(
    world: FastAPI, caller: str
) -> None:
    """The row that tells the two policies apart: the window admits this caller on the five routes
    above and the refresh refuses it, measured **during** setup on the reference
    `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` (spec section 3.7)."""
    token = await credential(world, caller)
    answered = await ask(world, LOOPBACK, "POST", "/Library/Refresh", token=token)
    assert_refused_empty(answered, 401)
    assert world.state.server_state.startup_wizard_completed is False
    assert world.state.scanner._worker is None, "a refused refresh starts nothing"


async def test_refresh_refuses_this_machine_as_a_non_administrator_403_during_setup(
    world: FastAPI,
) -> None:
    token = await credential(world, "non-administrator")
    answered = await ask(world, LOOPBACK, "POST", "/Library/Refresh", token=token)
    assert_refused_empty(answered, 403)
    assert world.state.scanner._worker is None


@pytest.mark.parametrize("peer", [LOOPBACK, ELSEWHERE])
async def test_refresh_admits_an_administrator_during_setup_from_anywhere(
    world: FastAPI, peer: str
) -> None:
    token = await credential(world, "administrator")
    answered = await ask(world, peer, "POST", "/Library/Refresh", token=token)
    assert answered.status_code == 204, answered.content
    assert answered.content == b""
