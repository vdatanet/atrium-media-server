# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Shows/{seriesId}/Seasons` and `/Episodes`, against the seeded world.

The one that matters most here is the specials order: the spec said season 0 sorts last, the
measurement said the reference sends it **first** - plain index order - and AC-11 was corrected
to the measured wire. These tests hold the measured order, and the rest of the surface: the
identical `404`, the scoping parameters, the envelope, and the multi-episode file appearing once.
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


# ------------------------------------------------------------------------------------------
# Seasons
# ------------------------------------------------------------------------------------------


async def test_ac11_season_zero_sorts_first_as_measured(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The corrected AC-11: index order, specials first - the measured wire, not the drafted
    expectation."""
    with_specials = world.series[1]
    answered = await client.get(f"/Shows/{with_specials.id}/Seasons")
    assert answered.status_code == 200
    numbers = [one["IndexNumber"] for one in answered.json()["Items"]]
    assert numbers == sorted(numbers), "seasons out of index order"
    assert numbers[0] == 0, "the specials season leads, as the reference sends it"


async def test_seasons_is_the_envelope_with_the_series_context(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    plain = world.series[0]
    answered = await client.get(f"/Shows/{plain.id}/Seasons")
    body = answered.json()
    assert set(body) == {"Items", "TotalRecordCount", "StartIndex"}
    assert body["TotalRecordCount"] == len(plain.seasons)
    row = body["Items"][0]
    assert row["Type"] == "Season"
    assert row["SeriesId"] == plain.id
    assert row["SeriesName"] == plain.name


async def test_is_special_season_filters_both_ways(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    with_specials = world.series[1]
    only = await client.get(
        f"/Shows/{with_specials.id}/Seasons", params={"isSpecialSeason": "true"}
    )
    assert [one["IndexNumber"] for one in only.json()["Items"]] == [0]
    none = await client.get(
        f"/Shows/{with_specials.id}/Seasons", params={"isSpecialSeason": "false"}
    )
    assert 0 not in [one["IndexNumber"] for one in none.json()["Items"]]


async def test_an_unknown_and_an_invisible_series_answer_the_same_404(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    as_user(harness, world.restricted)
    unknown = await client.get("/Shows/" + "f" * 32 + "/Seasons")
    invisible = await client.get(f"/Shows/{world.series[0].id}/Seasons")
    assert unknown.status_code == invisible.status_code == 404
    assert unknown.json()["title"] == invisible.json()["title"] == "Not Found"


# ------------------------------------------------------------------------------------------
# Episodes
# ------------------------------------------------------------------------------------------


async def test_the_whole_series_arrives_in_season_episode_order(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    with_specials = world.series[1]
    answered = await client.get(f"/Shows/{with_specials.id}/Episodes")
    pairs = [
        (one["ParentIndexNumber"], one["IndexNumber"]) for one in answered.json()["Items"]
    ]
    assert pairs == sorted(pairs), "episodes out of (season, episode) order"
    assert pairs[0][0] == 0, "the specials episodes lead, like their season"


async def test_the_multi_episode_file_appears_once(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """One item that *is* both episodes (003 AC-5), listed once."""
    answered = await client.get(f"/Shows/{world.series[1].id}/Episodes")
    ids = [one["Id"] for one in answered.json()["Items"]]
    assert ids.count(world.multi_episode) == 1


async def test_season_id_scopes_to_one_season(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    plain = world.series[0]
    answered = await client.get(
        f"/Shows/{plain.id}/Episodes", params={"seasonId": plain.seasons[1]}
    )
    body = answered.json()
    assert body["TotalRecordCount"] == 3
    assert {one["ParentIndexNumber"] for one in body["Items"]} == {2}


async def test_season_number_scopes_too(client: httpx.AsyncClient, world: QueryWorld) -> None:
    plain = world.series[0]
    answered = await client.get(f"/Shows/{plain.id}/Episodes", params={"season": "1"})
    assert {one["ParentIndexNumber"] for one in answered.json()["Items"]} == {1}


async def test_episode_paging_reports_the_pre_paging_count(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    plain = world.series[0]
    answered = await client.get(
        f"/Shows/{plain.id}/Episodes", params={"startIndex": "2", "limit": "2"}
    )
    body = answered.json()
    assert body["TotalRecordCount"] == len(plain.episodes)
    assert body["StartIndex"] == 2
    assert len(body["Items"]) == 2


async def test_is_missing_narrows_to_the_placeholders_that_do_not_exist(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`DisplayMissingEpisodes` is honoured trivially (plan 6.9): v1 creates no placeholders, so
    `isMissing=true` is an honest empty answer and `false` excludes nothing."""
    plain = world.series[0]
    missing = await client.get(f"/Shows/{plain.id}/Episodes", params={"isMissing": "true"})
    assert missing.json()["Items"] == []
    real = await client.get(f"/Shows/{plain.id}/Episodes", params={"isMissing": "false"})
    assert real.json()["TotalRecordCount"] == len(plain.episodes)


async def test_an_unknown_season_id_is_the_same_404(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get(
        f"/Shows/{world.series[0].id}/Episodes", params={"seasonId": "f" * 32}
    )
    assert answered.status_code == 404
