# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-3: five mechanisms, three route classes, one answer.

**Supporting only the headers leaves browsing working and every poster and stream broken.** That
failure looks like a bug in the client, which is why this gets its own table rather than being
implied by the API route passing: an image loader and an external player are handed a URL and set
no headers, so the query forms are the only ones they can use.

The image and delivery rows go through **stub routes** carrying the same dependency, because 006
and 008 do not exist yet. They are replaced rather than duplicated when those features arrive.

**The stubs assert that a token is accepted, not that one is required.** T1 measured that the
reference requires no token on either class, and asserting otherwise here would pin a behaviour
006 and 008 have not chosen yet.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from atrium.api.deps import require_user
from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.user import User

PASSWORD = "correct horse battery staple"
CLIENT_HEADER = 'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="bench-1", Version="1"'
BOGUS = "0" * 32
ITEM = "1" * 32

#: The API row is a real route. The other two are the stubs.
API_ROUTE = "/Users/Me"
IMAGE_ROUTE = f"/Items/{ITEM}/Images/Primary"
DELIVERY_ROUTE = f"/Videos/{ITEM}/stream"

ROUTE_CLASSES = [
    ("API", API_ROUTE),
    ("image", IMAGE_ROUTE),
    ("delivery", DELIVERY_ROUTE),
]


def mechanisms(token: str) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    """The five of spec section 3.1, in the order the reference resolves them."""
    return [
        ("Authorization", {"Authorization": f'MediaBrowser Token="{token}"'}, {}),
        ("X-Emby-Authorization", {"X-Emby-Authorization": f'MediaBrowser Token="{token}"'}, {}),
        ("X-Emby-Token", {"X-Emby-Token": token}, {}),
        ("?ApiKey=", {}, {"ApiKey": token}),
        ("?api_key=", {}, {"api_key": token}),
    ]


MECHANISM_NAMES = [name for name, _, _ in mechanisms("x")]


@pytest.fixture(autouse=True)
def stub_routes(app: FastAPI) -> Iterator[None]:
    """An image route and a delivery route, carrying the dependency the real ones will carry.

    Deliberately **not** in `server.ROUTERS`: a route registered there would be served by every
    instance and would fail 001's "no route exists outside the surface file" check, which is right
    - a stub is a test fixture and not a surface. It reaches the application because the path
    middleware rewrites the paths it knows and passes everything else through untouched.
    """

    @app.get("/Items/{itemId}/Images/Primary")
    async def image(itemId: str, user: Annotated[User, Depends(require_user)]) -> dict[str, str]:  # noqa: N803
        return {"Reached": "image", "For": user.name}

    @app.get("/Videos/{itemId}/stream")
    async def stream(itemId: str, user: Annotated[User, Depends(require_user)]) -> dict[str, str]:  # noqa: N803
        return {"Reached": "delivery", "For": user.name}

    app.openapi_schema = None
    yield


@pytest.fixture
def joan(app: FastAPI) -> User:
    with app.state.sessions.begin() as opened:
        return UserRepository(opened).add(
            User(id=new_id(), name="Joan", password_hash=app.state.passwords.hash(PASSWORD))
        )


@pytest.fixture
async def token(client: httpx.AsyncClient, joan: User) -> str:
    answered = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": "Joan", "Pw": PASSWORD},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    issued: str = answered.json()["AccessToken"]
    return issued


# --------------------------------------------------------------------------------------------
# The table: every mechanism, on every route class
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route_class,path", ROUTE_CLASSES, ids=[name for name, _ in ROUTE_CLASSES])
@pytest.mark.parametrize("mechanism", MECHANISM_NAMES)
async def test_every_mechanism_authenticates_every_route_class(
    client: httpx.AsyncClient, token: str, route_class: str, path: str, mechanism: str
) -> None:
    headers, query = next((h, q) for name, h, q in mechanisms(token) if name == mechanism)
    answered = await client.get(path, headers=headers, params=query)
    assert answered.status_code == 200, f"{mechanism} did not authenticate the {route_class} route"


async def test_the_query_forms_are_the_only_ones_a_player_can_use(
    client: httpx.AsyncClient, token: str
) -> None:
    """The whole reason this file exists.

    An external player and an image loader are handed a URL and set no headers. A server that
    supported only the headers would leave browsing working and every poster and stream broken -
    a failure that looks like a bug in the client.
    """
    for path in (IMAGE_ROUTE, DELIVERY_ROUTE):
        assert (await client.get(f"{path}?ApiKey={token}")).status_code == 200
        assert (await client.get(f"{path}?api_key={token}")).status_code == 200


async def test_the_stubs_are_not_asserted_to_demand_a_token(
    client: httpx.AsyncClient, token: str
) -> None:
    """T1 measured that the reference requires none on either class.

    What these stubs pin is that presenting a token is never a *reason to refuse*. Whether the
    class demands one is 006's and 008's decision, and asserting it here would take it for them.
    """
    with_token = await client.get(IMAGE_ROUTE, headers={"X-Emby-Token": token})
    assert with_token.status_code == 200
    assert with_token.json()["Reached"] == "image"


# --------------------------------------------------------------------------------------------
# Refusal, on the class that is measured to refuse
# --------------------------------------------------------------------------------------------


async def test_the_api_route_refuses_without_a_token(client: httpx.AsyncClient) -> None:
    """Measured, and the shape is measured too: empty, no content type."""
    refused = await client.get(API_ROUTE)
    assert refused.status_code == 401
    assert refused.content == b""
    assert "content-type" not in refused.headers


@pytest.mark.parametrize("mechanism", MECHANISM_NAMES)
async def test_a_bogus_token_is_refused_whichever_way_it_arrives(
    client: httpx.AsyncClient, joan: User, mechanism: str
) -> None:
    """A mechanism that authenticated an unknown token would be worse than one that worked."""
    headers, query = next((h, q) for name, h, q in mechanisms(BOGUS) if name == mechanism)
    answered = await client.get(API_ROUTE, headers=headers, params=query)
    assert answered.status_code == 401


# --------------------------------------------------------------------------------------------
# Which one wins, at the boundary
# --------------------------------------------------------------------------------------------


async def test_the_precedence_chain_resolves_as_it_was_measured(
    client: httpx.AsyncClient, token: str
) -> None:
    """`Authorization` > `X-Emby-Authorization` > `X-Emby-Token` > query.

    Measured pair by pair and in both directions each time, at T1 and T7. A client that sets a
    header once when the connection is built and assembles URLs from a template sends two, and they
    disagree exactly when one of them is stale.
    """
    real = f'MediaBrowser Token="{token}"'
    bogus = f'MediaBrowser Token="{BOGUS}"'

    pairs = [
        (
            "Authorization over X-Emby-Authorization",
            {"Authorization": real, "X-Emby-Authorization": bogus},
            "",
            200,
        ),
        ("...the other way round", {"Authorization": bogus, "X-Emby-Authorization": real}, "", 401),
        (
            "X-Emby-Authorization over X-Emby-Token",
            {"X-Emby-Authorization": real, "X-Emby-Token": BOGUS},
            "",
            200,
        ),
        ("...the other way round", {"X-Emby-Authorization": bogus, "X-Emby-Token": token}, "", 401),
        ("X-Emby-Token over the query", {"X-Emby-Token": token}, f"?ApiKey={BOGUS}", 200),
        ("...the other way round", {"X-Emby-Token": BOGUS}, f"?ApiKey={token}", 401),
    ]
    for label, headers, query, expected in pairs:
        answered = await client.get(f"{API_ROUTE}{query}", headers=headers)
        assert answered.status_code == expected, label


async def test_the_chain_holds_on_a_delivery_route_too(
    client: httpx.AsyncClient, token: str
) -> None:
    """The class where a stale header beside a fresh URL is most likely to happen."""
    stale = {"X-Emby-Token": BOGUS}
    assert (await client.get(f"{DELIVERY_ROUTE}?ApiKey={token}", headers=stale)).status_code == 401
    fresh = {"X-Emby-Token": token}
    assert (await client.get(f"{DELIVERY_ROUTE}?ApiKey={BOGUS}", headers=fresh)).status_code == 200
