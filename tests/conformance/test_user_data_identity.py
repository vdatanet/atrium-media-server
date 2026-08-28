# SPDX-License-Identifier: GPL-3.0-or-later
"""One object, two paths - and one user's state is never another's.

Three cross-cutting claims live here, none of which belongs to a single route:

* **A mark response is the next list row's `UserData`, byte for byte.** Both are built by
  `item_dto.user_data_dto` from a freshly-read row, so this is a property of the code path; the
  test is what says the path did not fork (007 plan section 6.3).
* **`Key` and `ItemId` are on every item of every response** (AC-1), which matters because they
  are the dialect marker a client uses to tell Jellyfin from Emby - present, not parsed.
* **Two users' state on one item is fully independent** (AC-7), through every write this feature
  owns rather than through one of them.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.user import LibraryAccess, User
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import RUNTIME_TICKS, QueryWorld, build_query_world

pytestmark = pytest.mark.conformance


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld
    second: User


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
        users = UserRepository(opened)
        # A second account that sees the same libraries: "per user" is not a claim a world with
        # one user in it can make, and the restricted user cannot see most of it.
        second = users.add(User(id="e" * 32, name="second", enable_all_folders=True))
        users.set_library_access(second.id, LibraryAccess(enabled_folders=()))
    built.dependency_overrides[require_user] = lambda: world.everyone
    yield Harness(app=built, world=world, second=second)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
def world(harness: Harness) -> QueryWorld:
    return harness.world


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def as_user(harness: Harness, user: User) -> None:
    harness.app.dependency_overrides[require_user] = lambda: user


async def user_data_of(client: httpx.AsyncClient, item_id: str) -> dict[str, Any]:
    body = (await client.get(f"/Items/{item_id}")).json()
    data: dict[str, Any] = body["UserData"]
    return data


# ------------------------------------------------------------------------------------------
# The mark response and the list row (plan section 6.3)
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["/UserFavoriteItems", "/UserPlayedItems"])
async def test_the_mark_response_is_the_list_rows_user_data_byte_for_byte(
    client: httpx.AsyncClient, world: QueryWorld, route: str
) -> None:
    item_id = world.corpus[7]
    marked = await client.post(f"{route}/{item_id}")
    listed = await client.get("/Items", params={"ids": item_id})
    row = listed.json()["Items"][0]["UserData"]
    assert json.dumps(marked.json()) == json.dumps(row)


@pytest.mark.parametrize("route", ["/UserFavoriteItems", "/UserPlayedItems"])
async def test_the_same_holds_for_a_container(
    client: httpx.AsyncClient, world: QueryWorld, route: str
) -> None:
    """The interesting half: a container's object carries a rollup the stored row does not have,
    and the mark response has to recompute it after its own writes."""
    season = world.series[0].seasons[0]
    marked = await client.post(f"{route}/{season}")
    listed = await client.get("/Items", params={"ids": season})
    assert json.dumps(marked.json()) == json.dumps(listed.json()["Items"][0]["UserData"])


async def test_the_unmark_response_agrees_too(client: httpx.AsyncClient, world: QueryWorld) -> None:
    season = world.series[0].seasons[0]
    await client.post(f"/UserPlayedItems/{season}")
    cleared = await client.delete(f"/UserPlayedItems/{season}")
    listed = await client.get("/Items", params={"ids": season})
    assert json.dumps(cleared.json()) == json.dumps(listed.json()["Items"][0]["UserData"])


async def test_a_report_lands_in_the_next_list_row(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The reports answer `204` and say nothing, so the only way to see what they did is the next
    request - which is exactly how a client sees it."""
    item_id = world.corpus[1]
    await client.post(
        "/Sessions/Playing/Progress",
        json={"ItemId": item_id, "PositionTicks": RUNTIME_TICKS // 2},
    )
    row = await user_data_of(client, item_id)
    assert row["PlaybackPositionTicks"] == RUNTIME_TICKS // 2
    assert row["PlayedPercentage"] == pytest.approx(50)


# ------------------------------------------------------------------------------------------
# AC-1: Key and ItemId, everywhere
# ------------------------------------------------------------------------------------------

LIST_ROUTES = [
    ("/Items", {"limit": "5"}),
    ("/Items/Latest", {"limit": "5"}),
    ("/UserItems/Resume", {}),
    ("/Shows/NextUp", {}),
    ("/UserViews", {}),
]


@pytest.mark.parametrize("path,params", LIST_ROUTES, ids=[path for path, _ in LIST_ROUTES])
async def test_ac1_every_row_carries_user_data_with_key_and_item_id(
    client: httpx.AsyncClient, path: str, params: dict[str, str]
) -> None:
    body = (await client.get(path, params=params)).json()
    rows = body["Items"] if isinstance(body, dict) else body
    assert rows, f"{path} answered nothing, so this asserts nothing"
    for row in rows:
        data = row["UserData"]
        assert data["Key"] == row["Id"], f"{path}: Key is not the item's identity"
        assert data["ItemId"] == row["Id"], f"{path}: ItemId is not the item's identity"


async def test_ac1_the_single_item_route_carries_them_too(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    data = await user_data_of(client, world.corpus[0])
    assert data["Key"] == data["ItemId"] == world.corpus[0]


async def test_the_by_name_routes_are_the_measured_exception(
    client: httpx.AsyncClient,
) -> None:
    """`/Genres` and the artist routes send **no** `UserData` at all - measured, and 005 declares
    it as an omission per route rather than as an accident. AC-1 is about the item responses; this
    is the boundary of "every"."""
    rows = (await client.get("/Genres")).json()["Items"]
    assert rows, "the world has no genres, so this asserts nothing"
    assert all("UserData" not in row for row in rows)


# ------------------------------------------------------------------------------------------
# AC-7: two users, one item
# ------------------------------------------------------------------------------------------


async def test_ac7_every_write_is_per_user(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[9]

    await client.post(f"/UserFavoriteItems/{item_id}")
    await client.post(f"/UserPlayedItems/{item_id}")
    await client.post(
        "/Sessions/Playing/Progress",
        json={"ItemId": item_id, "PositionTicks": 1_000_000_000},
    )
    mine = await user_data_of(client, item_id)
    assert (mine["IsFavorite"], mine["Played"]) == (True, True)

    as_user(harness, harness.second)
    theirs = await user_data_of(client, item_id)
    assert (theirs["IsFavorite"], theirs["Played"], theirs["PlayCount"]) == (False, False, 0)
    assert theirs["PlaybackPositionTicks"] == 0


async def test_ac7_a_second_users_writes_do_not_reach_the_first(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[9]
    as_user(harness, harness.second)
    await client.post(f"/UserPlayedItems/{item_id}")

    as_user(harness, world.everyone)
    mine = await user_data_of(client, item_id)
    assert (mine["Played"], mine["PlayCount"]) == (False, 0)


async def test_ac7_a_container_rollup_is_per_user_too(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The aggregate is computed from *this* user's rows, which is a different sentence from "the
    stored flags are per user" and fails differently: one shared `EXISTS` and everybody's series
    reads watched the moment anybody finishes it."""
    season = world.series[0].seasons[0]
    episodes = (await client.get("/Items", params={"parentId": season})).json()["TotalRecordCount"]
    assert episodes > 0, "the season is empty, so neither user could tell the difference"

    await client.post(f"/UserPlayedItems/{season}")
    mine = await user_data_of(client, season)
    assert (mine["Played"], mine["UnplayedItemCount"]) == (True, 0)

    as_user(harness, harness.second)
    theirs = await user_data_of(client, season)
    assert (theirs["Played"], theirs["UnplayedItemCount"]) == (False, episodes)
