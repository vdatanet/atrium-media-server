# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Shows/NextUp` and `GET /UserItems/Resume`: the played-state pair, end to end.

NextUp's chain is the probe's: after the **highest-numbered** played episode, one row per
series, most recently played series first - and a chain that has run out answers nothing, with
specials never stepping in. Resume is one query: stored mid-playback positions, newest first,
in the envelope; a finished item cannot appear because 007's rule never stored its position.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
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


def as_user(harness: Harness, user: User) -> None:
    harness.app.dependency_overrides[require_user] = lambda: user


def mark_played(harness: Harness, user: User, item_id: str, when: datetime) -> None:
    with harness.app.state.sessions.begin() as opened:
        opened.add(
            models.ItemUserData(
                user_id=user.id,
                item_key=item_id,
                played=True,
                play_count=1,
                last_played_date=when,
            )
        )


# ------------------------------------------------------------------------------------------
# NextUp
# ------------------------------------------------------------------------------------------


async def test_ac10_one_row_per_series_and_each_is_the_right_episode(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Three watched series, three rows, and every row is the episode after the watched one -
    on the second series that is the multi-episode file, the interesting case by construction."""
    answered = await client.get("/Shows/NextUp")
    body = answered.json()
    assert body["TotalRecordCount"] == len(world.series)
    by_series = {one["SeriesId"]: one for one in body["Items"]}
    assert len(by_series) == len(world.series), "a series appeared twice"
    for handle in world.series:
        assert by_series[handle.id]["Id"] == handle.next_up
    assert by_series[world.series[1].id]["Id"] == world.multi_episode


async def test_the_chain_follows_the_highest_played_episode_not_the_latest_click(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The probe's discriminating case, reproduced: playing a *later* episode moves the anchor
    to the highest number, and rewatching an early one cannot move it back."""
    first = world.series[0]
    # episodes are (S1E1, S1E2, S1E4, S2E1, S2E2, S2E4); S1E1 is already watched.
    mark_played(harness, world.everyone, first.episodes[2], datetime(2026, 3, 5, tzinfo=UTC))
    answered = await client.get("/Shows/NextUp", params={"seriesId": first.id})
    rows = answered.json()["Items"]
    assert [one["Id"] for one in rows] == [first.episodes[3]], (
        "next must follow the highest played episode into the next season"
    )


async def test_a_finished_chain_answers_nothing_and_specials_never_step_in(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The second series carries the specials season; playing out its one regular season must
    end the chain rather than promote season 0 (spec 3.7 - unmeasured on the reference's
    library, held here as specified)."""
    with_specials = world.series[1]
    for episode in with_specials.episodes:
        if episode != with_specials.watched:
            mark_played(
                harness, world.everyone, episode, datetime(2026, 3, 6, tzinfo=UTC)
            )
    answered = await client.get("/Shows/NextUp")
    ids = [one["Id"] for one in answered.json()["Items"]]
    assert not set(ids) & set(with_specials.episodes), "the finished series still answered"


async def test_the_most_recently_played_series_leads(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    third = world.series[2]
    mark_played(
        harness, world.everyone, third.episodes[1], datetime(2026, 4, 1, tzinfo=UTC)
    )
    answered = await client.get("/Shows/NextUp")
    assert answered.json()["Items"][0]["SeriesId"] == third.id


async def test_next_up_pages_like_every_envelope(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/Shows/NextUp", params={"startIndex": "1", "limit": "1"})
    body = answered.json()
    assert body["TotalRecordCount"] == len(world.series)
    assert body["StartIndex"] == 1
    assert len(body["Items"]) == 1


async def test_a_user_who_watched_nothing_gets_an_empty_envelope(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    as_user(harness, world.restricted)
    answered = await client.get("/Shows/NextUp")
    assert answered.json() == {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}


# ------------------------------------------------------------------------------------------
# Resume
# ------------------------------------------------------------------------------------------


async def test_resume_is_the_stored_positions_newest_first(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC's ordering half: bump one item's last-played and it must lead."""
    with harness.app.state.sessions.begin() as opened:
        row = opened.get(
            models.ItemUserData, (world.everyone.id, world.resumable[0])
        )
        assert row is not None
        row.last_played_date = datetime(2026, 4, 2, tzinfo=UTC)

    answered = await client.get("/UserItems/Resume")
    body = answered.json()
    assert body["TotalRecordCount"] == len(world.resumable)
    assert body["Items"][0]["Id"] == world.resumable[0]
    assert {one["Id"] for one in body["Items"]} == set(world.resumable)


async def test_resume_reports_the_position_it_resumes(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/UserItems/Resume")
    for row in answered.json()["Items"]:
        assert row["UserData"]["PlaybackPositionTicks"] > 0
        assert row["UserData"]["Played"] is False


async def test_resume_pages_and_narrows(client: httpx.AsyncClient, world: QueryWorld) -> None:
    limited = await client.get("/UserItems/Resume", params={"limit": "1"})
    assert limited.json()["TotalRecordCount"] == len(world.resumable)
    assert len(limited.json()["Items"]) == 1

    none = await client.get("/UserItems/Resume", params={"mediaTypes": "Audio"})
    assert none.json()["Items"] == []

    movies = await client.get("/UserItems/Resume", params={"includeItemTypes": "Movie"})
    assert movies.json()["TotalRecordCount"] == len(world.resumable)


async def test_resume_is_per_user(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The positions are the unrestricted user's; another user resumes nothing."""
    as_user(harness, world.restricted)
    answered = await client.get("/UserItems/Resume")
    assert answered.json() == {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}
