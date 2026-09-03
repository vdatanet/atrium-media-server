# SPDX-License-Identifier: GPL-3.0-or-later
"""The registry is the spec table, and the builder emits what the tier says and nothing else.

The first half pins spec section 3.2 as a comparison of two tables (plan section 6.5): the
always-present set, the measured per-type matrix and the gated list are written here as the spec
states them, and the registry must equal all three. A field moved in either place without the
other fails loudly, which is the drift risk plan section 9 row 6 names.

The second half is AC-2 and AC-3 at builder level, plus the emitters whose answers are worth
asserting by value: the ancestor context an episode and a track carry, the container rollup, the
explicit `ChannelId` null, and the one still-unprobed name that must stay absent **even when
asked** - that last one existed for the five 008 filled at T3 and now holds `Chapters` alone, so
that whatever extracts a chapter list changes a failing test rather than nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.api.item_dto import (
    ALWAYS,
    EMITTERS,
    GATED,
    PER_TYPE,
    PLAYLIST_EXTRA,
    UNPROBED,
    USER_VIEW_EXTRAS,
    BuildContext,
    LibraryContext,
    Width,
    build_dto,
    build_dtos,
)
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.item_queries import HydratedItem, ItemQueryRepository
from atrium.domain.items import ItemType
from atrium.domain.queries import ItemQuery
from atrium.media.decision import EVERY_PERMISSION
from tests.conftest import data_dir
from tests.fixtures.query import (
    ALBUM_ARTIST,
    ALBUM_PRIMARY_TAG,
    RUNTIME_TICKS,
    SERIES_BACKDROP_TAGS,
    SERIES_PRIMARY_TAG,
    SERIES_THUMB_TAG,
    SOLO_PERFORMER,
    QueryWorld,
    build_query_world,
)

SERVER_ID = "5" * 32


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    prepared: DataPaths = data_dir(tmp_path / "atrium")
    built = create_database_engine(prepared)
    schema.ensure_current(built, prepared)
    yield built
    built.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[OrmSession]:
    opened = session_factory(engine)()
    yield opened
    opened.rollback()
    opened.close()


@pytest.fixture
def world(session: OrmSession) -> QueryWorld:
    built = build_query_world(session)
    session.commit()
    return built


@pytest.fixture
def repository(session: OrmSession) -> ItemQueryRepository:
    return ItemQueryRepository(session)


@pytest.fixture
def hydrated(repository: ItemQueryRepository, world: QueryWorld) -> dict[str, HydratedItem]:
    """The whole visible world, by id, hydrated once for every test here."""
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    return {one.id: one for one in page.items}


def ctx(**overrides: Any) -> BuildContext:
    overrides.setdefault("policy", EVERY_PERMISSION)
    return BuildContext(server_id=SERVER_ID, **overrides)


def libraries_of(world: QueryWorld) -> dict[str, LibraryContext]:
    return {
        library.id: LibraryContext(
            collection_type=library.collection_type.value, roots=library.roots
        )
        for library in (world.movies, world.shows, world.music)
    }


def wire(one: HydratedItem, context: BuildContext) -> dict[str, Any]:
    return json.loads(build_dto(one, context).model_dump_json())


# ------------------------------------------------------------------------------------------
# The registry is the spec table
# ------------------------------------------------------------------------------------------

#: Spec section 3.2, "Always present, on every item, in every list" - copied, not imported.
SPEC_ALWAYS = {
    "Id",
    "ServerId",
    "Name",
    "Type",
    "MediaType",
    "IsFolder",
    "LocationType",
    "ChannelId",
    "UserData",
    "ImageTags",
    "ImageBlurHashes",
    "BackdropImageTags",
}

#: Spec section 3.2, "Present in a list row when the item type has them" - the measured matrix.
SPEC_PER_TYPE: dict[str, set[str]] = {
    "ProductionYear": {"Movie", "Series", "Season", "Episode", "MusicAlbum", "Audio"},
    "PremiereDate": {"Movie", "Series", "Season", "Episode", "MusicAlbum", "Audio"},
    "RunTimeTicks": {"Movie", "Series", "Episode", "MusicArtist", "MusicAlbum", "Audio"},
    "OfficialRating": {"Movie", "Series"},
    "CommunityRating": {"Movie", "Series", "Episode"},
    "IndexNumber": {"Season", "Episode", "Audio"},
    "ParentIndexNumber": {"Episode", "Audio"},
    "SeriesId": {"Season", "Episode"},
    "SeriesName": {"Season", "Episode"},
    "SeasonId": {"Episode"},
    "SeriesPrimaryImageTag": {"Season", "Episode"},
    "SeriesThumbImageTag": {"Episode"},
    "ParentThumbItemId": {"Season", "Episode"},
    "ParentThumbImageTag": {"Season", "Episode"},
    "ParentBackdropItemId": {"Season", "Episode", "MusicAlbum", "Audio"},
    "ParentBackdropImageTags": {"Season", "Episode", "MusicAlbum", "Audio"},
    "Album": {"Audio"},
    "AlbumId": {"Audio"},
    "AlbumPrimaryImageTag": {"Audio"},
    "AlbumArtist": {"MusicAlbum", "Audio"},
    "AlbumArtists": {"MusicAlbum", "Audio"},
    "Artists": {"MusicAlbum", "Audio"},
    "ArtistItems": {"MusicAlbum", "Audio"},
    "CollectionType": {"CollectionFolder"},
    # 008 T3's three: the media properties a bare row carries without asking.
    "Container": {"Movie", "Episode", "Audio"},
    "HasSubtitles": {"Movie", "Episode"},
    "VideoType": {"Movie", "Episode"},
}

#: Spec section 3.2, "Only when a list row asks for them".
SPEC_GATED = {
    "MediaSources",
    "MediaStreams",
    "Path",
    "Etag",
    "Chapters",
    "DateCreated",
    "DateLastMediaAdded",
    "ProviderIds",
    "Tags",
    "Taglines",
    "ExternalUrls",
    "OriginalTitle",
    "ParentId",
    "CumulativeRunTimeTicks",
    "RecursiveItemCount",
    "ChildCount",
    "SortName",
    "Overview",
    "Genres",
    "GenreItems",
    "Studios",
    "People",
    "PrimaryImageAspectRatio",
    "Width",
    "Height",
    "IsHD",
}


def test_the_always_set_is_the_specs() -> None:
    assert set(ALWAYS) == SPEC_ALWAYS


def test_the_per_type_table_is_the_specs() -> None:
    """Key by key, not as a bag, so a failure names the property that moved."""
    registry = {name: {one.value for one in types} for name, types in PER_TYPE.items()}
    assert registry == SPEC_PER_TYPE


def test_the_gated_list_is_the_specs() -> None:
    assert set(GATED) == SPEC_GATED


def test_every_registry_name_has_an_emitter_and_no_emitter_is_unreachable() -> None:
    assert set(EMITTERS) == set(ALWAYS) | set(PER_TYPE) | set(GATED) | PLAYLIST_EXTRA


def test_every_emitted_name_is_a_field_the_model_declares() -> None:
    """`BaseItemDto(**values)` ignores unknown keys - `extra="ignore"` is the request-side
    leniency the reference has - so a registry name the model does not declare would be dropped
    **silently**, emitter and all. This is the test that catches it; it caught
    `AlbumPrimaryImageTag` on its first run."""
    from atrium.api.item_models import BaseItemDto
    from atrium.compat.aliases import atrium_alias

    declared = {
        field.alias or atrium_alias(name) for name, field in BaseItemDto.model_fields.items()
    }
    emitted = (set(EMITTERS) - UNPROBED) | {"ChannelId"}
    missing = emitted - declared
    assert not missing, f"registry names no model field answers to: {sorted(missing)}"


def test_the_user_view_extras_are_all_gated_names() -> None:
    """The sixteen are a *subset* of the gated list: `/UserViews` un-gates, it does not invent."""
    assert USER_VIEW_EXTRAS < SPEC_GATED


def test_the_three_tiers_do_not_overlap() -> None:
    assert not (SPEC_ALWAYS & set(SPEC_PER_TYPE))
    assert not (SPEC_ALWAYS & SPEC_GATED)
    assert not (set(SPEC_PER_TYPE) & SPEC_GATED)


def test_the_playlist_extra_is_in_none_of_the_three_tiers() -> None:
    """The fourth tier invents where `/UserViews` un-gates, and that asymmetry is measured.

    `PlaylistItemId` is in no tier: `ALWAYS` would put it on every row of every route, and the
    reference sends it on none but the playlist one; `GATED` would make it something `fields`
    asks for, and nothing asks for it
    `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    assert not (PLAYLIST_EXTRA & (SPEC_ALWAYS | set(SPEC_PER_TYPE) | SPEC_GATED))


# ------------------------------------------------------------------------------------------
# The widths
# ------------------------------------------------------------------------------------------


def test_a_bare_movie_row_is_exactly_the_always_set(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """A plain film, nothing asked for: the twelve, and the three 008 T3 put on a film's row.

    `Container`, `HasSubtitles` and `VideoType` are per-type rather than gated - the reference
    sends all three on a bare list row of a film `[probe: tools/probe_item_shapes.py, Jellyfin
    10.11.11, 2026-08-27]` - so "exactly the always set" is now the always set plus that type's
    row, which is what `_considered` computes and what this asserts against.
    """
    body = wire(hydrated[world.corpus[50]], ctx())
    assert set(body) == SPEC_ALWAYS | {"Container", "HasSubtitles", "VideoType"}


def test_full_width_emits_the_gated_fields_unasked(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """`/Items/{itemId}`'s rule: `Fields` has nothing left to add (spec section 3.2)."""
    body = wire(hydrated[world.corpus[0]], ctx(width=Width.FULL, libraries=libraries_of(world)))
    for name in (
        "SortName",
        "Overview",
        "Genres",
        "GenreItems",
        "Studios",
        "People",
        "ProviderIds",
        "Tags",
        "Taglines",
        "ExternalUrls",
        "OriginalTitle",
        "ParentId",
        "DateCreated",
        "Etag",
        "Path",
        "PrimaryImageAspectRatio",
    ):
        assert name in body, f"{name} missing from a full body"
    assert body["Path"].startswith("/libraries/films/"), "the root did not reach the path"
    assert body["ExternalUrls"] == [
        {"Name": "IMDb", "Url": "https://www.imdb.com/title/tt0000001"},
        {"Name": "TMDB", "Url": "https://www.themoviedb.org/movie/42"},
    ]


def test_user_view_width_adds_the_measured_extras(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    folder_id = next(
        one
        for one in hydrated
        if hydrated[one].item.type is ItemType.COLLECTION_FOLDER
        and hydrated[one].item.library_id == world.movies.id
    )
    body = wire(hydrated[folder_id], ctx(width=Width.USER_VIEW, libraries=libraries_of(world)))
    assert body["CollectionType"] == "movies"
    for name in (
        "SortName",
        "DateCreated",
        "Etag",
        "Genres",
        "Tags",
        "Taglines",
        "ProviderIds",
        "Studios",
        "People",
        "GenreItems",
        "ExternalUrls",
    ):
        assert name in body, f"{name} missing from a user-view body"
    assert "Overview" not in body, "Overview is gated and /UserViews does not un-gate it"


# ------------------------------------------------------------------------------------------
# AC-2 and AC-3
# ------------------------------------------------------------------------------------------


def test_ac2_user_data_is_on_every_item_with_key_and_item_id(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """No `Fields`, no `EnableUserData`, every item of the visible world (AC-2)."""
    for one in hydrated.values():
        body = wire(one, ctx())
        assert body["UserData"]["Key"] == one.id
        assert body["UserData"]["ItemId"] == one.id


#: AC-3's per-field battery: for each gated name, an item that *has* a value for it, and the
#: context that supplies what the emitter reads. The one still-unprobed name is asserted the other
#: way round below.
def _gated_cases(world: QueryWorld) -> dict[str, tuple[str, dict[str, Any]]]:
    return {
        "Path": (world.corpus[0], {"libraries": libraries_of(world)}),
        # The five 008 T3 filled. A film rather than a track for the three video ones: the
        # emitters answer nothing for an item with no video stream, which would make the
        # "present when asked" half pass or fail on the fixture's choice of item.
        "MediaSources": (world.corpus[0], {"libraries": libraries_of(world)}),
        "MediaStreams": (world.corpus[0], {}),
        "Width": (world.corpus[0], {}),
        "Height": (world.corpus[0], {}),
        "IsHD": (world.corpus[0], {}),
        "Etag": (world.corpus[0], {}),
        "DateCreated": (world.corpus[0], {}),
        "ProviderIds": (world.corpus[0], {}),
        "Tags": (world.corpus[0], {}),
        "Taglines": (world.corpus[0], {}),
        "ExternalUrls": (world.corpus[0], {}),
        "OriginalTitle": (world.corpus[0], {}),
        "ParentId": (world.corpus[0], {}),
        "SortName": (world.corpus[0], {}),
        "Overview": (world.corpus[0], {}),
        "Genres": (world.corpus[0], {}),
        "GenreItems": (world.corpus[0], {}),
        "Studios": (world.corpus[0], {}),
        "People": (world.corpus[0], {}),
        "PrimaryImageAspectRatio": (world.corpus[0], {}),
        "DateLastMediaAdded": (world.series[0].id, {"aggregates": True}),
        "ChildCount": (world.series[0].id, {"aggregates": True}),
        "RecursiveItemCount": (world.series[0].id, {"aggregates": True}),
        "CumulativeRunTimeTicks": (None, {"aggregates": True}),  # the movies folder; see below
    }


@pytest.mark.parametrize("name", sorted(SPEC_GATED - UNPROBED))
def test_ac3_a_gated_field_is_absent_bare_and_present_when_asked(
    repository: ItemQueryRepository,
    hydrated: dict[str, HydratedItem],
    world: QueryWorld,
    name: str,
) -> None:
    cases = _gated_cases(world)
    item_id, extras = cases[name]
    if item_id is None:
        item_id = next(
            one
            for one in hydrated
            if hydrated[one].item.type is ItemType.COLLECTION_FOLDER
            and hydrated[one].item.library_id == world.movies.id
        )
    overrides: dict[str, Any] = {}
    if extras.get("libraries"):
        overrides["libraries"] = extras["libraries"]
    if extras.get("aggregates"):
        overrides["aggregates"] = repository.aggregates_for([item_id], world.everyone)

    bare = wire(hydrated[item_id], ctx(**overrides))
    assert name not in bare, f"{name} leaked into a bare list row"

    asked = wire(hydrated[item_id], ctx(fields=frozenset({GATED[name]}), **overrides))
    assert name in asked, f"{name} absent although fields={GATED[name]} asked for it"


def test_the_unprobed_stay_absent_even_when_asked(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """Held as a failing-test-in-waiting: whatever teaches this server to read a chapter list
    breaks this assertion and owns updating it (005 plan section 1). It held five names until
    008 T3, and the four it lost are now in `_gated_cases` being asserted the other way round."""
    asked = ctx(fields=frozenset(UNPROBED), width=Width.FULL)
    body = wire(hydrated[world.corpus[0]], asked)
    for name in UNPROBED:
        assert name not in body, f"{name} emitted with nothing to say"


# ------------------------------------------------------------------------------------------
# The emitters whose values are worth asserting
# ------------------------------------------------------------------------------------------


def test_channel_id_is_an_explicit_null_on_the_wire(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    body = wire(hydrated[world.corpus[50]], ctx())
    assert "ChannelId" in body and body["ChannelId"] is None


def test_an_episode_carries_its_ancestors_context(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """Series name and id from two hops up, season id from one, and every `Parent*` image tag
    resolved through the walk - the fixture gives only the first series images, so a lucky
    nothing-found cannot pass."""
    body = wire(hydrated[world.series[0].episodes[0]], ctx())
    assert body["SeriesId"] == world.series[0].id
    assert body["SeriesName"] == world.series[0].name
    assert body["SeasonId"] == world.series[0].seasons[0]
    assert body["SeriesPrimaryImageTag"] == SERIES_PRIMARY_TAG
    assert body["SeriesThumbImageTag"] == SERIES_THUMB_TAG
    assert body["ParentThumbItemId"] == world.series[0].id
    assert body["ParentThumbImageTag"] == SERIES_THUMB_TAG
    assert body["ParentBackdropImageTags"] == list(SERIES_BACKDROP_TAGS)


def test_a_track_carries_its_album_and_the_albums_artist(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    body = wire(hydrated[world.tracks[0]], ctx())
    assert body["Album"] == "A Compilation"
    assert body["AlbumId"] == world.album
    assert body["AlbumPrimaryImageTag"] == ALBUM_PRIMARY_TAG
    assert body["AlbumArtist"] == ALBUM_ARTIST
    assert [pair["Name"] for pair in body["AlbumArtists"]] == [ALBUM_ARTIST]
    assert body["Artists"] == ["The Compilers"]


def test_a_performer_with_no_item_is_a_name_without_an_id(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """The revision-0004 shape reaching the wire: behaviours section 5.3's visible half."""
    body = wire(hydrated[world.tracks[1]], ctx())
    assert body["Artists"] == [SOLO_PERFORMER]
    assert body["ArtistItems"] == [{"Name": SOLO_PERFORMER}]


def test_a_containers_user_data_is_the_rollup(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """One episode of six watched: five left, not played - and a film has no rollup at all."""
    series = wire(hydrated[world.series[0].id], ctx())
    assert series["UserData"]["UnplayedItemCount"] == len(world.series[0].episodes) - 1
    assert series["UserData"]["Played"] is False
    film = wire(hydrated[world.corpus[50]], ctx())
    assert "UnplayedItemCount" not in film["UserData"]


def test_played_percentage_is_position_over_runtime(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    body = wire(hydrated[world.corpus[1]], ctx())
    expected = 600 * 10_000_000 / RUNTIME_TICKS * 100
    assert body["UserData"]["PlayedPercentage"] == pytest.approx(expected)


def test_a_by_name_row_has_no_is_folder(repository: ItemQueryRepository, world: QueryWorld) -> None:
    """Measured: the reference sends no `IsFolder` for a genre, list row and full body alike -
    the one always-present name with a per-type hole."""
    page = repository.run(
        ItemQuery(user=world.everyone, include_types=frozenset({ItemType.GENRE}), limit=10)
    )
    assert page.items, "the world has genres and the query found none"
    body = wire(page.items[0], ctx())
    assert "IsFolder" not in body
    assert body["MediaType"] == "Unknown"
    assert "UserData" in body


def test_image_pruning_follows_the_four_options(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    series = hydrated[world.series[0].id]

    without = wire(series, ctx(enable_images=False))
    for name in ("ImageTags", "ImageBlurHashes", "BackdropImageTags"):
        assert name not in without

    limited = wire(series, ctx(image_type_limit=1))
    assert limited["BackdropImageTags"] == [SERIES_BACKDROP_TAGS[0]]

    only_primary = wire(series, ctx(enable_image_types=frozenset({"Primary"})))
    assert set(only_primary["ImageTags"]) == {"Primary"}
    assert only_primary["BackdropImageTags"] == []

    episode = wire(hydrated[world.series[0].episodes[0]], ctx(enable_images=False))
    assert "SeriesPrimaryImageTag" not in episode


def test_user_data_can_be_suppressed_and_only_on_request(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    body = wire(hydrated[world.corpus[50]], ctx(enable_user_data=False))
    assert "UserData" not in body


def test_image_blur_hashes_is_the_empty_map(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    """Present, `{}`, always: no BlurHash is computed and none is invented (behaviours 5.5)."""
    with_images = wire(hydrated[world.corpus[0]], ctx())
    assert with_images["ImageBlurHashes"] == {}
    assert with_images["ImageTags"] == {"Primary": "d" * 32}


def test_the_batch_builder_preserves_order(
    hydrated: dict[str, HydratedItem], world: QueryWorld
) -> None:
    chosen = [hydrated[world.corpus[3]], hydrated[world.corpus[2]], hydrated[world.corpus[7]]]
    built = build_dtos(chosen, ctx())
    assert [one.id for one in built] == [one.id for one in chosen]
