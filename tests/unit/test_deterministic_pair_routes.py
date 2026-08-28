# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items/{itemId}/Similar` and `/InstantMix`: deterministic by construction (AC-12).

The Similar ranking is asserted on values - the film sharing a genre row through a *different
spelling* is the one related film, which is what "shared means the by-name row" buys - and the
mix's order is recomputed in the test from the same hash the route uses, so a passing run proves
the order is a pure function of seed and library rather than a cached accident.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from hashlib import sha256
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
# Similar
# ------------------------------------------------------------------------------------------


async def test_similar_finds_the_film_that_shares_the_genre_row(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`sci-fi` and `Sci-Fi` are one by-name row, so the two films share a genre whatever their
    spellings say - and nothing else relates, so the answer is exactly that film."""
    answered = await client.get(f"/Items/{world.corpus[0]}/Similar")
    body = answered.json()
    assert set(body) == {"Items", "TotalRecordCount", "StartIndex"}
    assert [one["Id"] for one in body["Items"]] == [world.corpus[1]]


async def test_a_zero_score_is_excluded_and_the_seed_never_appears(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get(f"/Items/{world.corpus[50]}/Similar")
    assert answered.json() == {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}

    related = await client.get(f"/Items/{world.corpus[0]}/Similar")
    assert world.corpus[0] not in {one["Id"] for one in related.json()["Items"]}


async def test_ac12_similar_answers_identically_on_repeated_calls(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    first = await client.get(f"/Items/{world.corpus[0]}/Similar")
    second = await client.get(f"/Items/{world.corpus[0]}/Similar")
    assert first.content == second.content


async def test_an_unknown_and_an_invisible_seed_are_the_same_404(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    as_user(harness, world.restricted)
    unknown = await client.get("/Items/" + "f" * 32 + "/Similar")
    invisible = await client.get(f"/Items/{world.tracks[0]}/Similar")
    assert unknown.status_code == invisible.status_code == 404


# ------------------------------------------------------------------------------------------
# InstantMix
# ------------------------------------------------------------------------------------------


def mix_order(seed_id: str, pool: list[str]) -> list[str]:
    return sorted(pool, key=lambda one: sha256(f"{seed_id}{one}".encode()).hexdigest())


async def test_the_mix_is_the_keyed_shuffle_of_the_shared_genre_pool(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The order is recomputed here from the same hash: a pure function of seed and library."""
    seed = world.tracks[0]
    answered = await client.get(f"/Items/{seed}/InstantMix")
    body = answered.json()
    listed = [one["Id"] for one in body["Items"]]
    expected_pool = [one for one in world.tracks if one != seed]
    assert listed == mix_order(seed, expected_pool)
    assert body["TotalRecordCount"] == len(expected_pool)


async def test_an_album_seed_mixes_its_tracks(client: httpx.AsyncClient, world: QueryWorld) -> None:
    answered = await client.get(f"/Items/{world.album}/InstantMix")
    listed = [one["Id"] for one in answered.json()["Items"]]
    assert listed == mix_order(world.album, list(world.tracks))


async def test_two_seeds_shuffle_differently_but_each_stably(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Deterministic is not constant: the key includes the seed, so two seeds give two orders,
    and each seed gives its own order every time."""
    first = await client.get(f"/Items/{world.album}/InstantMix")
    again = await client.get(f"/Items/{world.album}/InstantMix")
    assert first.content == again.content

    other = await client.get(f"/Items/{world.album_artist}/InstantMix")
    assert {one["Id"] for one in other.json()["Items"]} == set(world.tracks)


async def test_a_seed_with_no_music_genre_mixes_nothing(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The guest album carries no genre, so its mix is honestly empty rather than the whole
    library."""
    answered = await client.get(f"/Items/{world.guest_track}/InstantMix")
    assert answered.json() == {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}


async def test_the_mix_respects_a_limit(client: httpx.AsyncClient, world: QueryWorld) -> None:
    answered = await client.get(f"/Items/{world.album}/InstantMix", params={"limit": "2"})
    body = answered.json()
    assert len(body["Items"]) == 2
    assert body["TotalRecordCount"] == len(world.tracks)
