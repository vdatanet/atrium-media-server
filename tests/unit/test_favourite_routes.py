# SPDX-License-Identifier: GPL-3.0-or-later
"""`POST` and `DELETE /UserFavoriteItems/{itemId}`: one row, both directions, and no cascade.

The favourite is the simplest thing this feature writes and the one whose *shape* the rest
inherits: an item resolved through the visible-item lookup, one row written, and the answer
re-read through the same hydration a list row goes through. Everything asserted here about the
response body is asserted again in the identity test (T12) against a list row - here it is about
the route, there it is about the two agreeing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db import models
from atrium.domain.user import User
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import QueryWorld, build_query_world


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
    yield Harness(app=built, world=world)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
def world(harness: Harness) -> QueryWorld:
    return harness.world


@pytest.fixture
def app(harness: Harness) -> FastAPI:
    harness.app.dependency_overrides[require_user] = lambda: harness.world.everyone
    return harness.app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def stored(harness: Harness, user: User, item_id: str) -> models.ItemUserData | None:
    with harness.app.state.sessions.begin() as opened:
        return opened.get(models.ItemUserData, (user.id, item_id))


def favourites(harness: Harness, user: User) -> set[str]:
    with harness.app.state.sessions.begin() as opened:
        rows = opened.query(models.ItemUserData).filter_by(user_id=user.id, is_favorite=True).all()
        return {row.item_key for row in rows}


# ------------------------------------------------------------------------------------------
# AC-2: idempotent, in both directions
# ------------------------------------------------------------------------------------------


async def test_ac2_marking_twice_answers_200_twice_and_leaves_one_favourite(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[5]
    first = await client.post(f"/UserFavoriteItems/{item_id}")
    second = await client.post(f"/UserFavoriteItems/{item_id}")
    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["IsFavorite"] is True
    assert second.json() == first.json()
    assert item_id in favourites(harness, world.everyone)


async def test_ac2_unmarking_twice_answers_200_twice_and_leaves_none(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Unmarking what was never marked is not an error - measured, and clients retry."""
    item_id = world.corpus[5]
    await client.post(f"/UserFavoriteItems/{item_id}")
    first = await client.delete(f"/UserFavoriteItems/{item_id}")
    second = await client.delete(f"/UserFavoriteItems/{item_id}")
    assert (first.status_code, second.status_code) == (200, 200)
    assert first.json()["IsFavorite"] is False
    assert item_id not in favourites(harness, world.everyone)


async def test_unmarking_something_never_marked_is_not_an_error(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.delete(f"/UserFavoriteItems/{world.corpus[7]}")
    assert answered.status_code == 200
    assert answered.json()["IsFavorite"] is False


# ------------------------------------------------------------------------------------------
# What one row means (spec section 3.3)
# ------------------------------------------------------------------------------------------


async def test_a_favourite_does_not_cascade_to_the_children(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Favouriting a season leaves every episode unfavourited - the opposite of the played mark,
    and the reason the two routes do not share a sweep."""
    handle = world.series[0]
    answered = await client.post(f"/UserFavoriteItems/{handle.seasons[0]}")
    assert answered.status_code == 200
    marked = favourites(harness, world.everyone)
    assert handle.seasons[0] in marked
    assert not marked & set(handle.episodes)


async def test_a_by_name_item_can_be_a_favourite(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """An artist has no file and is a favourite like anything else - the shape the probe measured
    against the reference, where its `Key` came back as its own identifier."""
    answered = await client.post(f"/UserFavoriteItems/{world.album_artist}")
    assert answered.status_code == 200
    assert answered.json()["Key"] == world.album_artist
    assert world.album_artist in favourites(harness, world.everyone)


async def test_the_flag_is_the_only_thing_the_route_writes(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """A film in the middle of playback stays there. The favourite and the position are different
    facts about one item, and a route that rebuilt the row would quietly reset one of them."""
    resuming = world.resumable[0]
    before = stored(harness, world.everyone, resuming)
    assert before is not None
    position, count = before.playback_position_ticks, before.play_count

    await client.post(f"/UserFavoriteItems/{resuming}")
    after = stored(harness, world.everyone, resuming)
    assert after is not None
    assert (after.playback_position_ticks, after.play_count) == (position, count)
    assert after.is_favorite is True


async def test_the_response_is_what_the_item_route_answers_next(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The identity T12 asserts across every write, here on the write that introduced it."""
    item_id = world.corpus[3]
    marked = await client.post(f"/UserFavoriteItems/{item_id}")
    row = await client.get(f"/Items/{item_id}")
    assert marked.json() == row.json()["UserData"]


async def test_one_users_favourite_is_not_another_users(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[0]
    await client.post(f"/UserFavoriteItems/{item_id}")
    assert item_id in favourites(harness, world.everyone)
    assert item_id not in favourites(harness, world.restricted)


# ------------------------------------------------------------------------------------------
# AC-21: the refusals, as the probe measured them
# ------------------------------------------------------------------------------------------


async def test_ac21_an_unknown_item_is_the_problem_details_404(
    client: httpx.AsyncClient,
) -> None:
    answered = await client.post(f"/UserFavoriteItems/{'a' * 32}")
    assert answered.status_code == 404
    assert answered.headers["content-type"] == "application/json; charset=utf-8"
    assert answered.json()["title"] == "Not Found"


async def test_ac21_an_invisible_item_is_the_identical_404(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """A client that could tell "no such item" from "not yours" could enumerate another user's
    library one identifier at a time (005 plan section 6.13)."""
    harness.app.dependency_overrides[require_user] = lambda: world.restricted
    invisible = await client.post(f"/UserFavoriteItems/{world.series[0].id}")
    unknown = await client.post(f"/UserFavoriteItems/{'b' * 32}")
    assert invisible.status_code == unknown.status_code == 404
    assert invisible.json()["title"] == unknown.json()["title"]


async def test_ac21_a_path_that_is_not_a_guid_is_the_validation_400(
    client: httpx.AsyncClient,
) -> None:
    answered = await client.post("/UserFavoriteItems/banana")
    assert answered.status_code == 400
    assert answered.json()["errors"] == {"itemId": ["The value 'banana' is not valid."]}


async def test_ac21_the_delete_refuses_the_same_way(client: httpx.AsyncClient) -> None:
    """Both directions share the refusals; a route pair that refused differently would be two
    error surfaces for one behaviour."""
    unknown = await client.delete(f"/UserFavoriteItems/{'c' * 32}")
    malformed = await client.delete("/UserFavoriteItems/banana")
    assert (unknown.status_code, malformed.status_code) == (404, 400)


async def test_ac21_no_token_is_the_empty_401(harness: Harness) -> None:
    """Without the dependency override, which is what every other test in this file installs."""
    harness.app.dependency_overrides.clear()
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        answered = await opened.post(f"/UserFavoriteItems/{'d' * 32}")
    assert answered.status_code == 401
    assert answered.content == b""
