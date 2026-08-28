# SPDX-License-Identifier: GPL-3.0-or-later
"""A container's played state is **derived**, and the criterion is what happens when the world
moves.

A rollup that is right the first time is easy; the spec forbids a *stale* one, and the only way to
tell the two apart is to change the subtree between two reads. So AC-6 runs against a real scanned
library and mutates it three ways - a child marked, a file added and rescanned, a file removed and
rescanned - reading the season's `UnplayedItemCount` after each.

AC-20 is the other half: the fraction is **field-gated**. A bare container row carries
`UnplayedItemCount` and `Played` and no `PlayedPercentage` at all; `Fields=RecursiveItemCount` is
what produces one `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`.

And OQ-7 - what an *empty* container reports - is settled here, with an answer the question did not
anticipate: for the four types that earn their place, an empty one is not in a response at all.
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import Engine

from atrium.api.deps import require_user
from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import (
    ItemRepository,
    LibraryRepository,
    UserDataRepository,
    UserRepository,
)
from atrium.domain.items import CollectionType, Item, ItemType
from atrium.domain.library import Library
from atrium.domain.playstate import UserItemData
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User
from atrium.library import config, identity
from atrium.library.scan import scan
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.library import BuiltFixture
from tests.fixtures.query import QueryWorld, build_query_world

pytestmark = pytest.mark.conformance

SEASON = "The Series/Season 01"
ADDED = "The Series/Season 01/The Series - S01E05 - A New One.mkv"


# ------------------------------------------------------------------------------------------
# AC-6: the rollup follows the world
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scanned:
    engine: Engine
    library: Library
    user: User
    root: Path


@pytest.fixture
def scanned(tmp_path: Path, fixture_library: BuiltFixture) -> Iterator[Scanned]:
    paths = data_dir(tmp_path / "atrium")
    engine = create_database_engine(paths)
    schema.ensure_current(engine, paths)
    factory = session_factory(engine)
    root = Path(fixture_library.of("tvshows").root)
    with session_scope(factory) as opened:
        library = config.create(LibraryRepository(opened), "Shows", "tvshows", (str(root),))
        user = UserRepository(opened).add(User(id=new_id(), name="joan", enable_all_folders=True))
    with session_scope(factory) as opened:
        scan(library, opened)
    yield Scanned(engine=engine, library=library, user=user, root=root)
    engine.dispose()


def rescan(scanned: Scanned) -> None:
    with session_scope(session_factory(scanned.engine)) as opened:
        scan(scanned.library, opened)


def season_of(scanned: Scanned) -> str:
    """The fullest season in the fixture library.

    Chosen by size rather than by name: the shows fixture holds three series, two of them with a
    single episode in their first season, so "a season numbered 1" is the wrong one two times in
    three - and the test needs a season it can take an episode away from and still have one.
    """
    with session_scope(session_factory(scanned.engine)) as opened:
        repository = ItemQueryRepository(opened)
        seasons = [
            item.id
            for item in ItemRepository(opened).visible(scanned.library.id).values()
            if item.type is ItemType.SEASON
        ]
        return max(seasons, key=lambda one: len(repository.leaf_descendants(one, scanned.user)))


def rollup(scanned: Scanned, item_id: str) -> tuple[bool, int | None]:
    """`(Played, UnplayedItemCount)` as a response would carry them."""
    with session_scope(session_factory(scanned.engine)) as opened:
        page = ItemQueryRepository(opened).run(
            ItemQuery(user=scanned.user, ids=(item_id,), count=False)
        )
        data = page.items[0].user_data
        return data.played, data.unplayed_count


def episodes_of(scanned: Scanned, season_id: str) -> tuple[str, ...]:
    with session_scope(session_factory(scanned.engine)) as opened:
        return ItemQueryRepository(opened).leaf_descendants(season_id, scanned.user)


def mark_played(scanned: Scanned, item_id: str) -> None:
    with session_scope(session_factory(scanned.engine)) as opened:
        UserDataRepository(opened).put(
            scanned.user.id, item_id, UserItemData(played=True, play_count=1)
        )


def test_ac6_the_count_follows_a_mark_an_addition_and_a_removal(scanned: Scanned) -> None:
    season = season_of(scanned)
    episodes = episodes_of(scanned, season)
    assert len(episodes) >= 2, "the fixture season is too small for this to mean anything"

    assert rollup(scanned, season) == (False, len(episodes))

    mark_played(scanned, episodes[0])
    assert rollup(scanned, season) == (False, len(episodes) - 1)

    added = scanned.root / ADDED
    shutil.copyfile(scanned.root / "The Series/Season 01/The Series - S01E01 - Pilot.mkv", added)
    rescan(scanned)
    assert rollup(scanned, season) == (False, len(episodes)), "the new episode is not counted"

    added.unlink()
    rescan(scanned)
    assert rollup(scanned, season) == (False, len(episodes) - 1), (
        "a removed episode is still counted, which is what a cached aggregate looks like"
    )


def test_a_season_reads_played_when_its_last_unplayed_child_is_marked(scanned: Scanned) -> None:
    """The other direction, and the one a client renders as a tick on the poster."""
    season = season_of(scanned)
    for episode in episodes_of(scanned, season):
        mark_played(scanned, episode)
    assert rollup(scanned, season) == (True, 0)


def test_removing_the_only_unplayed_episode_makes_the_season_played(scanned: Scanned) -> None:
    """A stale aggregate's sharpest symptom: the file is gone and the series still says *1 left*."""
    season = season_of(scanned)
    episodes = episodes_of(scanned, season)
    for episode in episodes[1:]:
        mark_played(scanned, episode)
    assert rollup(scanned, season) == (False, 1)

    with session_scope(session_factory(scanned.engine)) as opened:
        first = next(
            item
            for item in ItemRepository(opened).visible(scanned.library.id).values()
            if item.id == episodes[0]
        )
        Path(scanned.root / first.sources[0].relative_path).unlink()
    rescan(scanned)
    assert rollup(scanned, season) == (True, 0)


# ------------------------------------------------------------------------------------------
# AC-20: the percentage is field-gated
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    paths: DataPaths = data_dir(tmp_path / "atrium-query")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
    built.dependency_overrides[require_user] = lambda: world.everyone
    yield Harness(app=built, world=world)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


async def test_ac20_a_bare_container_row_carries_no_percentage(
    client: httpx.AsyncClient, harness: Harness
) -> None:
    season = harness.world.series[0].seasons[0]
    await client.post(f"/UserPlayedItems/{harness.world.series[0].episodes[0]}")

    body = (await client.get(f"/Items/{season}")).json()["UserData"]
    assert "UnplayedItemCount" in body and "Played" in body
    assert "PlayedPercentage" not in body


async def test_ac20_asking_for_recursive_item_count_produces_the_percentage(
    client: httpx.AsyncClient, harness: Harness
) -> None:
    handle = harness.world.series[0]
    season = handle.seasons[0]
    under = (await client.get("/Items", params={"parentId": season, "recursive": "true"})).json()
    total = len([one for one in under["Items"] if one["Type"] == "Episode"])
    await client.post(f"/UserPlayedItems/{handle.episodes[0]}")

    rows = (
        await client.get(
            "/Items",
            params={"ids": season, "fields": "RecursiveItemCount"},
        )
    ).json()["Items"]
    assert rows[0]["UserData"]["PlayedPercentage"] == pytest.approx(100 / total)


async def test_the_percentage_of_a_fully_played_container_is_a_hundred(
    client: httpx.AsyncClient, harness: Harness
) -> None:
    season = harness.world.series[0].seasons[0]
    await client.post(f"/UserPlayedItems/{season}")
    rows = (
        await client.get("/Items", params={"ids": season, "fields": "RecursiveItemCount"})
    ).json()["Items"]
    assert rows[0]["UserData"]["PlayedPercentage"] == 100


async def test_a_leaf_keeps_the_position_over_runtime_reading(
    client: httpx.AsyncClient, harness: Harness
) -> None:
    """The two percentages are different quantities, and the gate is only on the container's."""
    film = harness.world.resumable[0]
    bare = (await client.get(f"/Items/{film}")).json()["UserData"]
    assert bare["PlayedPercentage"] > 0


# ------------------------------------------------------------------------------------------
# OQ-7: what an empty container reports
# ------------------------------------------------------------------------------------------


async def test_oq7_an_empty_season_is_not_in_a_response_at_all(
    client: httpx.AsyncClient, harness: Harness
) -> None:
    """The question was which `Played` an empty container carries. In Atrium it carries none,
    because it is not offered: a `Season` with nothing visible beneath it does not earn its place
    (behaviours section 5.2), so the row a client would read the flag off does not exist."""
    world = harness.world
    empty = identity.for_season(world.series[0].id, 9)
    with harness.app.state.sessions.begin() as opened:
        ItemRepository(opened).add(
            Item(
                id=empty,
                type=ItemType.SEASON,
                name="Season 9",
                library_id=world.shows.id,
                parent_id=world.series[0].id,
                index_number=9,
            )
        )

    answered = await client.get(f"/Items/{empty}")
    assert answered.status_code == 404

    under = (
        await client.get("/Items", params={"parentId": world.series[0].id, "recursive": "false"})
    ).json()
    assert empty not in [one["Id"] for one in under["Items"]]


async def test_oq7_the_one_empty_container_a_client_can_see_is_a_library(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """`CollectionFolder` is exempt from earning its place - an empty library still appears in a
    sidebar - so it is the only shape where the question can be asked, and Atrium answers
    `Played: false` with `UnplayedItemCount: 0`. The reference's source reads a childless folder
    as vacuously *played*; nothing measured contradicts either, and 010's differential owns it."""
    with harness.app.state.sessions.begin() as opened:
        library = LibraryRepository(opened).add(
            Library(
                id=new_id(),
                name="Empty",
                collection_type=CollectionType.MOVIES,
                roots=("/libraries/empty",),
            )
        )
        folder = identity.for_library(library.id)
        ItemRepository(opened).add(
            Item(
                id=folder,
                type=ItemType.COLLECTION_FOLDER,
                name="Empty",
                library_id=library.id,
                parent_id=None,
            )
        )

    body = (await client.get(f"/Items/{folder}")).json()["UserData"]
    assert (body["Played"], body["UnplayedItemCount"]) == (False, 0)
    assert "PlayedPercentage" not in body
