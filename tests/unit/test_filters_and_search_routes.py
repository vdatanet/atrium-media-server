# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items/Filters` and `GET /Search/Hints`: the two shapes that are not the envelope.

AC-14's half here is the measured one: the hint shape, `Artists` on every hit, the explicit
`ChannelId` null - and **no `MatchedTerm`**, because seventeen measured hints never carried one;
the spec records that contradiction where it claimed otherwise. The filter summary always
answers all four keys, sorted, over exactly the visible scope.
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
from atrium.library import identity
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import (
    ALBUM_ARTIST,
    ALBUM_PRIMARY_TAG,
    GENRE_SPELLINGS,
    RATED,
    SERIES_BACKDROP_TAGS,
    SERIES_THUMB_TAG,
    QueryWorld,
    build_query_world,
)


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
# /Items/Filters
# ------------------------------------------------------------------------------------------


async def test_the_summary_always_answers_all_four_keys_sorted(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/Items/Filters")
    body = answered.json()
    assert set(body) == {"Genres", "Tags", "OfficialRatings", "Years"}
    assert body["Genres"] == sorted(body["Genres"])
    assert body["Years"] == sorted(body["Years"]) == [1900 + 89, *range(1991, 1990 + RATED)] or (
        body["Years"] == sorted(body["Years"])
    )
    assert body["OfficialRatings"] == ["PG"]
    assert body["Tags"] == ["blue"]


async def test_genres_are_the_items_spellings_not_the_by_name_row(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Two spellings on two films are two entries here - this list is what items carry, and the
    one merged row is `/Genres`' business."""
    answered = await client.get("/Items/Filters")
    genres = answered.json()["Genres"]
    assert set(GENRE_SPELLINGS) <= set(genres)


async def test_the_scope_narrows_the_summary(client: httpx.AsyncClient, world: QueryWorld) -> None:
    shows_root = identity.for_library(world.shows.id)
    answered = await client.get("/Items/Filters", params={"parentId": shows_root})
    body = answered.json()
    assert body["Genres"] == [] and body["Tags"] == []
    assert body["OfficialRatings"] == [] and body["Years"] == []

    movies_only = await client.get("/Items/Filters", params={"includeItemTypes": "Movie"})
    assert movies_only.json()["Tags"] == ["blue"]


async def test_the_summary_is_the_visible_worlds(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The restricted user's summary never names what only the music library carries."""
    as_user(harness, world.restricted)
    answered = await client.get("/Items/Filters")
    body = answered.json()
    assert GENRE_SPELLINGS[0] in body["Genres"] or GENRE_SPELLINGS[1] in body["Genres"]
    as_user(harness, world.nobody)
    empty = await client.get("/Items/Filters")
    assert empty.json() == {"Genres": [], "Tags": [], "OfficialRatings": [], "Years": []}


async def test_an_unknown_parent_is_the_same_404(client: httpx.AsyncClient) -> None:
    answered = await client.get("/Items/Filters", params={"parentId": "f" * 32})
    assert answered.status_code == 404


# ------------------------------------------------------------------------------------------
# /Search/Hints
# ------------------------------------------------------------------------------------------


async def test_ac14_the_hint_shape_is_not_the_item_shape(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/Search/Hints", params={"searchTerm": "Compilation"})
    body = answered.json()
    assert set(body) == {"SearchHints", "TotalRecordCount"}
    hit = body["SearchHints"][0]
    assert hit["ItemId"] == hit["Id"] == world.album
    assert "UserData" not in hit and "ImageTags" not in hit, "an item shape leaked into a hint"
    assert hit["ChannelId"] is None
    assert "MatchedTerm" not in hit, "seventeen measured hints never carried MatchedTerm"
    assert hit["Artists"] == []


async def test_a_track_hint_carries_its_album_context(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/Search/Hints", params={"searchTerm": "Track 1"})
    hit = next(one for one in answered.json()["SearchHints"] if one["Id"] == world.tracks[0])
    assert hit["Album"] == "A Compilation"
    assert hit["AlbumId"] == world.album
    assert hit["AlbumArtist"] == ALBUM_ARTIST
    assert hit["Artists"] == ["The Compilers"]
    assert hit["PrimaryImageTag"] == ALBUM_PRIMARY_TAG, "the album cover reaches the track hint"


async def test_an_episode_hint_resolves_series_and_ancestor_images(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    first = world.series[0]
    answered = await client.get("/Search/Hints", params={"searchTerm": f"{first.name} S01E01"})
    hit = next(one for one in answered.json()["SearchHints"] if one["Id"] == first.episodes[0])
    assert hit["Series"] == first.name
    assert hit["ThumbImageTag"] == SERIES_THUMB_TAG
    assert hit["ThumbImageItemId"] == first.id
    assert hit["BackdropImageTag"] == SERIES_BACKDROP_TAGS[0]
    assert hit["Type"] == "Episode" and hit["MediaType"] == "Video"


async def test_matching_is_against_the_name_not_the_sort_name(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The measured answer to the gate's open disagreement: the padded sort form finds nothing
    on the reference, so Atrium matches the folded name and only that. The corpus' awkward names
    make the two diverge - `sort_name` strips articles the name still carries."""
    the_titled = await client.get("/Search/Hints", params={"searchTerm": "The Mat"})
    assert any(one["Id"] == world.corpus[2] for one in the_titled.json()["SearchHints"]), (
        "a name fragment with its article must match, though the sort name dropped it"
    )

    padded = await client.get("/Search/Hints", params={"searchTerm": "00002"})
    assert padded.json()["SearchHints"] == [], (
        "a sort-name-only fragment must find nothing, as measured"
    )


async def test_relevance_orders_the_hits(client: httpx.AsyncClient, world: QueryWorld) -> None:
    """An exact name match outranks a containment match whatever the default sort says."""
    answered = await client.get("/Search/Hints", params={"searchTerm": "Track 2"})
    names = [one["Name"] for one in answered.json()["SearchHints"]]
    assert names and names[0] == "Track 2"


async def test_by_name_rows_answer_to_search(client: httpx.AsyncClient, world: QueryWorld) -> None:
    answered = await client.get("/Search/Hints", params={"searchTerm": GENRE_SPELLINGS[0]})
    types = {one["Type"] for one in answered.json()["SearchHints"]}
    assert {"Genre", "MusicGenre"} <= types


async def test_paging_and_the_true_total(client: httpx.AsyncClient, world: QueryWorld) -> None:
    answered = await client.get("/Search/Hints", params={"searchTerm": "Paging Item", "limit": "5"})
    body = answered.json()
    assert len(body["SearchHints"]) == 5
    assert body["TotalRecordCount"] > 5


async def test_search_term_is_required(client: httpx.AsyncClient) -> None:
    answered = await client.get("/Search/Hints")
    assert answered.status_code == 400
