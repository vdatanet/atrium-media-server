# SPDX-License-Identifier: GPL-3.0-or-later
"""`POST` and `DELETE /UserPlayedItems/{itemId}`: the count that does not move, and the cascade.

Two things here are measurements rather than intuitions, and both are asserted against the
database as well as the response: **a bare mark is `max(count, 1)`**, so marking twice leaves the
count at one and only `datePlayed` increments it; and **a container writes its leaves and never
its own row**, so a marked season reads `Played: true` from its subtree while its own stored row
stays at zero with no `LastPlayedDate`.
`[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`
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

IMPORTED = "2019-07-04T00:00:00.0000000Z"


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


def row(harness: Harness, user: User, item_key: str) -> models.ItemUserData | None:
    with harness.app.state.sessions.begin() as opened:
        return opened.get(models.ItemUserData, (user.id, item_key))


def rows(harness: Harness, user: User, keys: tuple[str, ...]) -> dict[str, models.ItemUserData]:
    with harness.app.state.sessions.begin() as opened:
        found = (
            opened.query(models.ItemUserData)
            .filter(models.ItemUserData.user_id == user.id)
            .filter(models.ItemUserData.item_key.in_(keys))
            .all()
        )
        return {one.item_key: one for one in found}


# ------------------------------------------------------------------------------------------
# AC-3: the mark, and the count that only one form moves
# ------------------------------------------------------------------------------------------


async def test_ac3_marking_played_resets_the_position_and_sets_the_count_to_one(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The seeded film is in mid-playback, which is the state this route has to clear: an item
    that is played *and* resumable sits in "continue watching" for ever."""
    resuming = world.resumable[0]
    assert row(harness, world.everyone, resuming).playback_position_ticks > 0

    answered = await client.post(f"/UserPlayedItems/{resuming}")
    assert answered.status_code == 200
    body = answered.json()
    assert (body["Played"], body["PlayCount"], body["PlaybackPositionTicks"]) == (True, 1, 0)


async def test_ac3_marking_twice_leaves_the_count_at_one(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[4]
    once = await client.post(f"/UserPlayedItems/{item_id}")
    twice = await client.post(f"/UserPlayedItems/{item_id}")
    assert once.json()["PlayCount"] == twice.json()["PlayCount"] == 1


async def test_ac3_only_the_dated_form_increments_and_its_date_wins(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[4]
    await client.post(f"/UserPlayedItems/{item_id}")
    dated = await client.post(f"/UserPlayedItems/{item_id}", params={"datePlayed": IMPORTED})
    assert dated.json()["PlayCount"] == 2
    assert dated.json()["LastPlayedDate"] == IMPORTED


async def test_a_bare_mark_keeps_an_existing_last_played_date(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The watched episode carries a date from the fixture. A bare mark must not move it - the
    reference's own rule, and the difference between "watched then" and "marked now"."""
    watched = world.series[0].watched
    before = row(harness, world.everyone, watched).last_played_date
    await client.post(f"/UserPlayedItems/{watched}")
    assert row(harness, world.everyone, watched).last_played_date == before


async def test_ac4_unmarking_clears_all_four_fields(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    watched = world.series[0].watched
    answered = await client.delete(f"/UserPlayedItems/{watched}")
    assert answered.status_code == 200
    body = answered.json()
    assert (body["Played"], body["PlayCount"], body["PlaybackPositionTicks"]) == (False, 0, 0)
    assert "LastPlayedDate" not in body, "a cleared date must be absent, not null"
    assert row(harness, world.everyone, watched).last_played_date is None


async def test_the_favourite_survives_a_mark_and_an_unmark(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    favourite = world.favourites[0]
    await client.post(f"/UserPlayedItems/{favourite}")
    await client.delete(f"/UserPlayedItems/{favourite}")
    assert row(harness, world.everyone, favourite).is_favorite is True


# ------------------------------------------------------------------------------------------
# AC-5: the cascade
# ------------------------------------------------------------------------------------------


async def test_ac5_marking_a_season_writes_every_episode_and_not_the_season(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    handle = world.series[0]
    season = handle.seasons[0]
    answered = await client.post(f"/UserPlayedItems/{season}")
    assert answered.status_code == 200

    written = rows(harness, world.everyone, (season, *handle.episodes))
    under_season = [key for key in written if key != season]
    assert under_season, "the season's episodes were not written"
    assert all(written[key].play_count == 1 for key in under_season)
    assert season not in written, "the container's own row was written"


async def test_ac5_the_response_is_the_rollup_the_writes_just_created(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`UnplayedItemCount: 0` the instant the season is marked - which requires the aggregate to
    be recomputed after the sweep, in the same transaction."""
    answered = await client.post(f"/UserPlayedItems/{world.series[0].seasons[0]}")
    body = answered.json()
    assert (body["Played"], body["UnplayedItemCount"]) == (True, 0)
    assert body["PlayCount"] == 0, "a container's own count is not an aggregate"


async def test_marking_a_series_reaches_its_episodes_through_its_seasons(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    handle = world.series[0]
    await client.post(f"/UserPlayedItems/{handle.id}")
    written = rows(harness, world.everyone, (handle.id, *handle.seasons, *handle.episodes))
    assert set(written) == set(handle.episodes)


async def test_unmarking_a_container_sweeps_the_same_set_back(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    handle = world.series[0]
    await client.post(f"/UserPlayedItems/{handle.id}")
    answered = await client.delete(f"/UserPlayedItems/{handle.id}")
    body = answered.json()
    assert (body["Played"], body["UnplayedItemCount"]) == (False, len(handle.episodes))
    written = rows(harness, world.everyone, handle.episodes)
    assert all(not one.played and one.play_count == 0 for one in written.values())


async def test_marking_an_album_marks_its_tracks(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    await client.post(f"/UserPlayedItems/{world.album}")
    written = rows(harness, world.everyone, (world.album, *world.tracks))
    assert set(written) >= set(world.tracks)
    assert written[world.album].play_count == 0, "the album's own count moved"


async def test_an_artist_sweeps_because_it_is_a_folder(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`MusicArtist` is a `Folder` in the reference and a container here, so marking one reaches
    its tracks through its albums - two hops - and leaves no row of its own behind."""
    await client.post(f"/UserPlayedItems/{world.album_artist}")
    written = rows(harness, world.everyone, (world.album_artist, *world.tracks))
    assert world.album_artist not in written, "the artist's own row was written; it is a Folder"
    assert set(written) >= set(world.tracks)


async def test_a_by_name_row_writes_itself_because_it_is_not_a_folder(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The other half of the same split: the reference's `Genre` is a plain `BaseItem`, so
    `MarkPlayed` writes *its* row. A genre has no children to sweep, and reading "container" off
    an empty result would leave this mark writing nothing at all."""
    with harness.app.state.sessions.begin() as opened:
        genre = opened.query(models.Item).filter_by(type="Genre").first()
        assert genre is not None, "the world has no by-name genre row to mark"
        genre_id = genre.id

    answered = await client.post(f"/UserPlayedItems/{genre_id}")
    assert answered.status_code == 200
    assert answered.json()["Played"] is True
    written = row(harness, world.everyone, genre_id)
    assert written is not None and written.play_count == 1


async def test_the_cascade_is_the_callers_own_scope(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """A user who cannot see the shows library cannot mark its season, and the refusal is the
    identical 404 rather than a partial sweep."""
    harness.app.dependency_overrides[require_user] = lambda: world.restricted
    answered = await client.post(f"/UserPlayedItems/{world.series[0].seasons[0]}")
    assert answered.status_code == 404
    assert rows(harness, world.restricted, world.series[0].episodes) == {}


# ------------------------------------------------------------------------------------------
# AC-21: the refusals
# ------------------------------------------------------------------------------------------


async def test_ac21_an_unknown_item_is_the_problem_details_404(client: httpx.AsyncClient) -> None:
    answered = await client.post(f"/UserPlayedItems/{'a' * 32}")
    assert answered.status_code == 404
    assert answered.json()["title"] == "Not Found"


async def test_ac21_a_path_that_is_not_a_guid_is_the_validation_400(
    client: httpx.AsyncClient,
) -> None:
    answered = await client.post("/UserPlayedItems/banana")
    assert answered.status_code == 400
    assert answered.json()["errors"] == {"itemId": ["The value 'banana' is not valid."]}


async def test_ac21_an_unparseable_date_played_refuses_and_stores_nothing(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Measured: `400` validation problem details naming the parameter, and the mark does not
    happen. A route that parsed the date by hand would either ignore it or store a wrong one."""
    item_id = world.corpus[6]
    answered = await client.post(f"/UserPlayedItems/{item_id}", params={"datePlayed": "banana"})
    assert answered.status_code == 400
    assert "datePlayed" in answered.json()["errors"]
    assert row(harness, world.everyone, item_id) is None


async def test_the_delete_refuses_the_same_way(client: httpx.AsyncClient) -> None:
    unknown = await client.delete(f"/UserPlayedItems/{'c' * 32}")
    malformed = await client.delete("/UserPlayedItems/banana")
    assert (unknown.status_code, malformed.status_code) == (404, 400)


async def test_no_token_is_the_empty_401(harness: Harness) -> None:
    harness.app.dependency_overrides.clear()
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        answered = await opened.post(f"/UserPlayedItems/{'d' * 32}")
    assert answered.status_code == 401
    assert answered.content == b""


async def test_the_date_played_parameter_is_matched_case_insensitively(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """behaviours section 1.15: the reference matches parameter *names* case-insensitively, and
    005's canonicalisation makes that true for every route without each one remembering."""
    item_id = world.corpus[8]
    answered = await client.post(f"/UserPlayedItems/{item_id}", params={"DatePlayed": IMPORTED})
    assert answered.status_code == 200
    assert answered.json()["LastPlayedDate"] == IMPORTED
