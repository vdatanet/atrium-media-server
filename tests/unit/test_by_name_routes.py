# SPDX-License-Identifier: GPL-3.0-or-later
"""The five by-name routes, end to end: envelope, the true count, and the measured omissions.

AC-5 lives here - `TotalRecordCount` is the pre-paging count **with and without `limit`**, which
is the recorded divergence of behaviours 3.1 held on purpose - and so does the endpoint half of
the credit story: in v1 `/Artists` and `/Artists/AlbumArtists` coincide as row sets, which is
behaviours 5.3's consequence and not a bug, so the test asserts the coincidence *with its
reason* and the credit distinction where it actually shows.
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
from tests.fixtures.query import GENRE_SPELLINGS, RATED, QueryWorld, build_query_world


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


async def test_ac5_the_count_is_true_with_and_without_limit(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """behaviours 3.1, held on purpose: the reference answers 0 - or on `/Years`, a number that
    is neither zero nor the row count - and Atrium answers the truth on every one."""
    for path, expected in (
        ("/Genres", 1),
        ("/MusicGenres", 1),
        ("/Years", RATED),
        ("/Artists", 2),
        ("/Artists/AlbumArtists", 2),
    ):
        bare = await client.get(path)
        limited = await client.get(path, params={"limit": "1"})
        assert bare.json()["TotalRecordCount"] == expected, path
        assert limited.json()["TotalRecordCount"] == expected, f"{path} with a limit"
        assert len(limited.json()["Items"]) == 1, path


async def test_the_two_spellings_are_one_genre_row(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/Genres")
    rows = answered.json()["Items"]
    assert len(rows) == 1
    assert rows[0]["Name"] in GENRE_SPELLINGS
    assert rows[0]["Type"] == "Genre"


async def test_genre_rows_carry_no_user_data_and_year_rows_do(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The measured per-route omissions: `/Genres` and `/MusicGenres` without `UserData`,
    `/Years` with it - and the same rows through `/Items` carry it everywhere."""
    for path in ("/Genres", "/MusicGenres"):
        row = (await client.get(path)).json()["Items"][0]
        assert "UserData" not in row, path
        assert row["ChannelId"] is None

    year_row = (await client.get("/Years")).json()["Items"][0]
    assert "UserData" in year_row

    genre_id = (await client.get("/Genres")).json()["Items"][0]["Id"]
    through_items = await client.get("/Items", params={"ids": genre_id})
    assert "UserData" in through_items.json()["Items"][0]


async def test_artist_rows_carry_no_is_folder(client: httpx.AsyncClient, world: QueryWorld) -> None:
    for path in ("/Artists", "/Artists/AlbumArtists"):
        row = (await client.get(path)).json()["Items"][0]
        assert "IsFolder" not in row, path
        assert "UserData" in row, path
        assert row["Type"] == "MusicArtist"


async def test_ac13_the_two_artist_routes_coincide_for_the_recorded_reason(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The endpoint half of the credit distinction, as v1 can honestly state it.

    An Atrium `MusicArtist` is a per-library item the scanner creates per *album artist*
    (behaviours 5.3), so an artist who only performs has a name on every track and no row to
    list - the strict containment the criterion first imagined has no row to show it. What must
    still hold: album-credit is a subset of any-credit, and the *item*-level distinction bites
    through `artistIds`/`albumArtistIds`, measured at T6 and asserted here on the guest track.
    """
    every = {one["Id"] for one in (await client.get("/Artists")).json()["Items"]}
    album = {one["Id"] for one in (await client.get("/Artists/AlbumArtists")).json()["Items"]}
    assert album <= every
    assert album == every, "if these ever differ, behaviours 5.3's argument needs rereading"

    performer = await client.get("/Items", params={"artistIds": world.album_artist})
    fronted = await client.get("/Items", params={"albumArtistIds": world.album_artist})
    assert world.guest_track in {one["Id"] for one in performer.json()["Items"]}
    assert world.guest_track not in {one["Id"] for one in fronted.json()["Items"]}


async def test_a_hidden_librarys_genre_is_absent_for_its_user(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The adversarial half, end to end: the music genre exists only through the music library,
    which the restricted user cannot see - while the film genre, spelled differently, remains."""
    as_user(harness, world.restricted)
    music = await client.get("/MusicGenres")
    assert music.json() == {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}
    films = await client.get("/Genres")
    assert films.json()["TotalRecordCount"] == 1


async def test_search_term_and_paging_work_across_the_family(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    found = await client.get("/Artists", params={"searchTerm": "Various"})
    assert [one["Id"] for one in found.json()["Items"]] == [world.album_artist]

    paged = await client.get("/Years", params={"startIndex": "2", "limit": "3"})
    body = paged.json()
    assert body["StartIndex"] == 2
    assert len(body["Items"]) == 3
    assert body["TotalRecordCount"] == RATED


async def test_sorting_descends_on_request(client: httpx.AsyncClient, world: QueryWorld) -> None:
    descending = await client.get(
        "/Years", params={"sortBy": "SortName", "sortOrder": "Descending"}
    )
    names = [one["Name"] for one in descending.json()["Items"]]
    assert names == sorted(names, reverse=True)


async def test_parent_id_scopes_the_membership(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """A genre reached under the music library is the music genre's row, not the film one's."""
    from atrium.library import identity

    music_root = identity.for_library(world.music.id)
    scoped = await client.get("/MusicGenres", params={"parentId": music_root})
    assert scoped.json()["TotalRecordCount"] == 1
    films_scoped = await client.get("/Genres", params={"parentId": music_root})
    assert films_scoped.json()["TotalRecordCount"] == 0
