# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-3: five mechanisms, three route classes, one answer.

**Supporting only the headers leaves browsing working and every poster and stream broken.** That
failure looks like a bug in the client, which is why this gets its own table rather than being
implied by the API route passing: an image loader and an external player are handed a URL and set
no headers, so the query forms are the only ones they can use.

**Both stubs are gone now, and the second went the way of the first.** The image row became a real
route at 006 T9 and the delivery row at 008 T6, and each time the assertion had to change with it:
a stub answered `200` to anything, while a real route answers what it has. What survives on both
is the claim AC-3 actually makes about these two classes - **presenting a token is never itself a
reason to refuse** - asserted against the tokenless response, byte for byte.

**Only one class treats a token as a credential**, and that is the whole shape of this file now.
`GET /Users/Me` refuses without one; the image routes (006) and the four delivery routes (008 T6)
require none, which is what the reference does and what 002 section 3.1 already said before either
feature chose it `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`
`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`.

**The precedence chain is therefore only observable on the API route**, and the delivery test that
used to prove it a second time is gone rather than rewritten: a route that reads no token cannot
demonstrate which of two tokens wins. Losing that row is a consequence of the decision, recorded
here so it reads as one rather than as a test somebody dropped.
"""

from __future__ import annotations

import re

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.user import User

PASSWORD = "correct horse battery staple"
CLIENT_HEADER = 'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="bench-1", Version="1"'
BOGUS = "0" * 32
ITEM = "1" * 32

#: All three are real routes now.
API_ROUTE = "/Users/Me"
IMAGE_ROUTE = f"/Items/{ITEM}/Images/Primary"
DELIVERY_ROUTE = f"/Videos/{ITEM}/stream?static=true"

#: The one class where a token is a credential and the answer is `200` with one.
#:
#: The other two require none, so "this mechanism authenticated the route" is not a claim that can
#: be made about them at all: a route answering `200` to a request carrying nothing accepts every
#: mechanism trivially. What can be claimed there is the table below it.
TOKEN_OPTIONAL = [
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

#: `traceId` is per request by definition (behaviours §1.11), so two identical refusals differ in
#: exactly those 55 bytes. Masked rather than parsed: what is being compared is the wire, and a
#: comparison that went through `.json()` would stop seeing casing and null-versus-absent.
_TRACE = re.compile(rb'"traceId":"[^"]*"')


def masked(response: httpx.Response) -> bytes:
    return _TRACE.sub(b'"traceId":"?"', response.content)


def same_bytes(first: httpx.Response, second: httpx.Response) -> bool:
    return masked(first) == masked(second)


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


@pytest.mark.parametrize("mechanism", MECHANISM_NAMES)
async def test_every_mechanism_authenticates_the_api_route(
    client: httpx.AsyncClient, token: str, mechanism: str
) -> None:
    """The one class where "authenticated" is a claim: no token here is `401`, so a `200` is the
    mechanism having worked rather than the route not caring."""
    headers, query = next((h, q) for name, h, q in mechanisms(token) if name == mechanism)
    answered = await client.get(API_ROUTE, headers=headers, params=query)
    assert answered.status_code == 200, f"{mechanism} did not authenticate the API route"


@pytest.mark.parametrize("route_class,path", TOKEN_OPTIONAL, ids=[n for n, _ in TOKEN_OPTIONAL])
@pytest.mark.parametrize("mechanism", MECHANISM_NAMES)
async def test_a_token_never_changes_a_token_optional_routes_answer(
    client: httpx.AsyncClient, token: str, route_class: str, path: str, mechanism: str
) -> None:
    """AC-3's half for the two classes that require nothing: **the same answer, whatever arrives.**

    Neither route reads a token (006 plan §1, 008 T6), so every mechanism is accepted trivially -
    and "accepted" is only visible as "the answer did not change". Compared byte for byte against
    the tokenless request rather than by status, because a route that started refusing differently
    per mechanism would keep the status and change the body.

    Both paths name an item nothing holds, so both answers are refusals - and deliberately *two
    different* refusals, the image route's bare JSON string and the delivery route's `text/plain`
    (behaviours §1.11). A comparison by status would not have noticed either.
    """
    tokenless = await client.get(path)
    headers, query = next((h, q) for name, h, q in mechanisms(token) if name == mechanism)

    answered = await client.get(path, headers=headers, params=query)

    assert answered.status_code == tokenless.status_code
    assert same_bytes(answered, tokenless)


@pytest.mark.parametrize("route_class,path", TOKEN_OPTIONAL, ids=[n for n, _ in TOKEN_OPTIONAL])
async def test_the_query_forms_are_the_only_ones_a_player_can_use(
    client: httpx.AsyncClient, token: str, route_class: str, path: str
) -> None:
    """The whole reason this file exists.

    An external player and an image loader are handed a URL and set no headers. A server that
    supported only the headers would leave browsing working and every poster and stream broken -
    a failure that looks like a bug in the client. Neither class needs a token, so what a query
    form must not do is *break* the answer that arrives without one.
    """
    joined = "&" if "?" in path else "?"
    tokenless = await client.get(path)

    for query in (f"{joined}ApiKey={token}", f"{joined}api_key={token}"):
        answered = await client.get(f"{path}{query}")
        assert answered.status_code == tokenless.status_code
        assert same_bytes(answered, tokenless)


async def test_neither_optional_class_demands_a_token(client: httpx.AsyncClient) -> None:
    """002 T1 measured that the reference requires none on either class, and 006 and 008 T6 each
    decided to replicate it. Asserted here as the *absence* of a `401`, which is the one answer
    that would mean the decision had been quietly reversed."""
    for _, path in TOKEN_OPTIONAL:
        assert (await client.get(path)).status_code != 401


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


async def test_a_stale_header_beside_a_fresh_url_cannot_break_delivery(
    client: httpx.AsyncClient, token: str
) -> None:
    """The pair the deleted delivery-precedence test was written for, asserted the only way that
    is still true.

    A player that sets a header once and assembles URLs from a template sends two credentials, and
    they disagree exactly when one is stale. On an API route the chain decides which wins (above).
    On a delivery route **neither is read**, so the failure that test guarded against - a stale
    header refusing a request whose URL carried a good token - cannot happen at all.
    """
    stale = {"X-Emby-Token": BOGUS}
    tokenless = await client.get(DELIVERY_ROUTE)

    answered = await client.get(f"{DELIVERY_ROUTE}&ApiKey={token}", headers=stale)

    assert answered.status_code == tokenless.status_code
    assert same_bytes(answered, tokenless)
