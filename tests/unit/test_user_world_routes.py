# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /UserViews` and `GET /Items/Latest`, end to end, against the seeded world.

The two halves of AC-1 live here - the envelope with `StartIndex` on `/UserViews`, the **bare
array** on `/Items/Latest` - together with AC-9's empty envelope and the grouping rule the task
measured before writing: a group of several recent items surfaces as its container, a group of
one surfaces as the item itself, and two stored configuration keys steer what enters the pool.
"""

from __future__ import annotations

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
from atrium.domain.user import User
from atrium.library import identity
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


def configure(harness: Harness, user: User, configuration: dict[str, Any]) -> None:
    with harness.app.state.sessions.begin() as opened:
        UserRepository(opened).replace_configuration(user.id, configuration)
    # The route reads the user the seam resolved, so the override must hand it the fresh row.
    with harness.app.state.sessions.begin() as opened:
        refreshed = UserRepository(opened).by_id(user.id)
    assert refreshed is not None
    as_user(harness, refreshed)


# ------------------------------------------------------------------------------------------
# /UserViews
# ------------------------------------------------------------------------------------------


async def test_ac9_a_user_permitted_nothing_gets_the_empty_envelope(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    as_user(harness, world.nobody)
    answered = await client.get("/UserViews")
    assert answered.status_code == 200
    assert answered.json() == {"Items": [], "TotalRecordCount": 0, "StartIndex": 0}


async def test_the_views_are_the_visible_libraries_with_their_kinds(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/UserViews")
    body = answered.json()
    assert body["TotalRecordCount"] == 3
    by_name = {one["Name"]: one for one in body["Items"]}
    assert {one["Type"] for one in body["Items"]} == {"CollectionFolder"}
    assert by_name["Films"]["CollectionType"] == "movies"
    assert by_name["Shows"]["CollectionType"] == "tvshows"
    assert by_name["Music"]["CollectionType"] == "music"


async def test_a_view_row_is_the_wide_shape_with_the_two_nulls(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The third width: the measured extras arrive unasked, and `ParentId` is an explicit null
    on a parentless view - beside the `ChannelId` every row carries."""
    answered = await client.get("/UserViews")
    row = answered.json()["Items"][0]
    for name in ("SortName", "DateCreated", "Etag", "Genres", "Tags", "Taglines", "ChildCount"):
        assert name in row, f"{name} missing from a view row"
    assert row["ChannelId"] is None
    assert "ParentId" in row and row["ParentId"] is None
    assert "Overview" not in row


async def test_the_restricted_user_sees_one_view(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    as_user(harness, world.restricted)
    answered = await client.get("/UserViews")
    assert [one["Name"] for one in answered.json()["Items"]] == ["Films"]


async def test_a_views_child_count_is_its_librarys(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/UserViews")
    films = next(one for one in answered.json()["Items"] if one["Name"] == "Films")
    assert films["ChildCount"] == len(world.corpus)


# ------------------------------------------------------------------------------------------
# /Items/Latest
# ------------------------------------------------------------------------------------------


async def test_latest_is_a_bare_array(client: httpx.AsyncClient) -> None:
    """AC-1's other half, and behaviours 1.8: a client decoding an envelope here gets nothing."""
    answered = await client.get("/Items/Latest")
    assert answered.status_code == 200
    assert isinstance(answered.json(), list)


async def test_a_track_surfaces_as_its_album_however_few_the_album_holds(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-28's music half, and it **overturns a measurement** rather than filling a gap.

    This asserted the opposite until 2026-09-06: that the guest album's lone track arrives as the
    `Audio`, which is what a live library was read as answering on 2026-08-28. Read against a
    reference over this repository's own fixture — both servers in the same breath — a track
    surfaces as its album on every case there is, including an album of three tracks with one
    recent member, which is the very shape that sentence described
    `[probe: tools/differential.py's own client, by hand, Jellyfin 10.11.11, 2026-09-06]`.

    So no `Audio` row survives the grouping, and that absence is the sharp half of the claim: a
    rule that grouped by count would leave the lone track standing.
    """
    answered = await client.get("/Items/Latest", params={"limit": "50"})
    rows = answered.json()
    ids = [one["Id"] for one in rows]

    assert not any(one["Type"] == "Audio" for one in rows), (
        "a track surfaces as its album, so no ungrouped track is left in the answer"
    )
    assert world.guest_track not in ids, "the lone guest track arrives as its album"

    assert world.album in ids, "three recent tracks surface as their album"
    album_row = next(one for one in rows if one["Id"] == world.album)
    assert album_row["Type"] == "MusicAlbum"
    assert not set(world.tracks) & set(ids), "no grouped track appears beside its album"


async def test_a_lone_episode_still_surfaces_as_itself(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-28's television half, which the same reading found **unchanged**.

    It is asserted apart from the music half now precisely because the two halves parted: a series
    with several recent episodes arrives as the `Series` and a series with one arrives as the
    `Episode`, on both servers, in the same response. A rule made uniform in either direction
    breaks one of these two tests.
    """
    answered = await client.get("/Items/Latest", params={"limit": "50"})
    ids = [one["Id"] for one in answered.json()]

    for handle in world.series:
        assert handle.id in ids, "several recent episodes surface as their series"
    episode_ids = {episode for handle in world.series for episode in handle.episodes}
    assert not episode_ids & set(ids)


async def test_each_group_appears_once_and_newest_first(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/Items/Latest", params={"limit": "50"})
    ids = [one["Id"] for one in answered.json()]
    assert len(ids) == len(set(ids)), "a group appeared twice"
    # `corpus` is oldest-first, so its positions in a newest-first response must descend.
    movie_positions = [ids.index(one) for one in world.corpus if one in ids]
    assert movie_positions == sorted(movie_positions, reverse=True), "not newest first"


async def test_group_items_false_serves_the_files_plainly(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get("/Items/Latest", params={"limit": "50", "groupItems": "false"})
    ids = [one["Id"] for one in answered.json()]
    assert set(world.tracks) <= set(ids), "ungrouped tracks appear as themselves"
    assert world.album not in ids


async def test_played_items_stay_out_by_default_and_come_back_when_asked(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`HidePlayedInLatest` is true on a configuration never edited (measured), so the watched
    episodes never enter the pool; `isPlayed=true` asks for exactly them - and each series has
    one, so the singleton rule shows them as episodes."""
    watched = {handle.watched for handle in world.series}

    plain = await client.get(
        "/Items/Latest",
        params={"limit": "100", "groupItems": "false", "includeItemTypes": "Episode"},
    )
    assert not watched & {one["Id"] for one in plain.json()}

    played = await client.get("/Items/Latest", params={"limit": "100", "isPlayed": "true"})
    rows = played.json()
    assert {one["Id"] for one in rows} == watched
    assert {one["Type"] for one in rows} == {"Episode"}


async def test_hide_played_in_latest_false_lets_played_items_in(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    configure(harness, world.everyone, {"HidePlayedInLatest": False})
    answered = await client.get(
        "/Items/Latest",
        params={"limit": "100", "groupItems": "false", "includeItemTypes": "Episode"},
    )
    watched = {handle.watched for handle in world.series}
    assert watched <= {one["Id"] for one in answered.json()}


async def test_an_excluded_library_contributes_nothing_unscoped(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`LatestItemsExcludes` names the *view* - the library's own item id - and it bites only
    the request that named no view of its own."""
    music_view = identity.for_library(world.music.id)
    configure(harness, world.everyone, {"LatestItemsExcludes": [music_view]})

    unscoped = await client.get("/Items/Latest", params={"limit": "100"})
    ids = {one["Id"] for one in unscoped.json()}
    assert world.album not in ids and world.guest_track not in ids

    scoped = await client.get("/Items/Latest", params={"limit": "100", "parentId": music_view})
    assert world.album in {one["Id"] for one in scoped.json()}


async def test_include_item_types_narrows_the_pool(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    answered = await client.get(
        "/Items/Latest", params={"limit": "100", "includeItemTypes": "Audio"}
    )
    assert {one["Type"] for one in answered.json()} <= {"Audio", "MusicAlbum"}


async def test_limit_bounds_the_groups(client: httpx.AsyncClient) -> None:
    answered = await client.get("/Items/Latest", params={"limit": "5"})
    assert len(answered.json()) == 5


async def test_an_unknown_parent_is_the_problem_details_404(
    client: httpx.AsyncClient,
) -> None:
    answered = await client.get("/Items/Latest", params={"parentId": "f" * 32})
    assert answered.status_code == 404
    assert answered.json()["title"] == "Not Found"


async def test_latest_rows_are_list_rows(client: httpx.AsyncClient, world: QueryWorld) -> None:
    """The narrow shape: nothing gated leaks, and the always set travels - including the null."""
    answered = await client.get("/Items/Latest", params={"limit": "3"})
    for row in answered.json():
        assert "Overview" not in row and "SortName" not in row
        assert row["ChannelId"] is None
        assert row["UserData"]["Key"] == row["Id"]
