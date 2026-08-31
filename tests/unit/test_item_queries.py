# SPDX-License-Identifier: GPL-3.0-or-later
"""The one predicate, the one count, and the hydration that must not grow with the page.

Three properties are asserted here that a functional test cannot see, because the wrong
implementation returns exactly the right answer:

* **Visibility holds under every scope shape.** A predicate that is right for `/Items` and missing
  from the recursive branch shows one user another user's library, and the request succeeds.
* **The count is the pre-paging count under the query's own predicates.** A count rebuilt beside
  the page rather than derived from it drifts, and a client pages past the end of a list that said
  it was longer.
* **Hydration costs a fixed number of statements.** A page of one and a page of fifty are the same
  number of round trips. An N+1 is invisible in a test and quadratic in a library.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.item_queries import (
    EARN_THEIR_PLACE,
    ItemQueryRepository,
    ParentNotFoundError,
    UserItemData,
)
from atrium.db.repositories import ItemRepository
from atrium.domain.items import ItemType
from atrium.domain.queries import ItemQuery
from atrium.library import identity
from tests.conftest import QueryCounter, data_dir
from tests.fixtures.query import (
    ALBUM_ARTIST,
    CORPUS_SIZE,
    RUNTIME_TICKS,
    QueryWorld,
    build_query_world,
)


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


def ids(page: object) -> set[str]:
    return {one.id for one in page.items}  # type: ignore[attr-defined]


def types_in(page: object) -> set[ItemType]:
    return {one.item.type for one in page.items}  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------------
# Visibility, under every scope shape
# ------------------------------------------------------------------------------------------


def test_the_unrestricted_user_sees_the_whole_world(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    assert len(page.items) == page.total
    assert types_in(page) >= {ItemType.MOVIE, ItemType.SERIES, ItemType.AUDIO}


def test_the_restricted_user_sees_only_the_permitted_library(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(ItemQuery(user=world.restricted, limit=1000))
    libraries = {
        one.item.library_id
        for one in page.items
        if not one.item.is_by_name and one.item.type is not ItemType.PLAYLIST
    }
    assert libraries == {world.movies.id}, (
        "an item of an unpermitted library reached a user whose policy excludes it"
    )


def test_every_playlist_still_reaches_every_user(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """009 tasks' gate finding 2, asserted rather than described - and it is a **leak**.

    `_library_permitted` exempts a row with no library, because a by-name row is not *in* one; a
    playlist is not in one either (009 plan §4.1), so it passes that clause for every caller. Until
    T6 adds the fourth sibling clause, every user's private playlists are in every other user's
    listing. This says so out loud instead of excluding the rows from the test above and calling
    it clean: T6 inverts this assertion, and a fixture that quietly stopped seeding playlists fails
    it either way.
    """
    page = repository.run(
        ItemQuery(
            user=world.restricted,
            include_types=frozenset({ItemType.PLAYLIST}),
            limit=1000,
        )
    )
    assert {one.item.id for one in page.items} == {one.id for one in world.playlists}
    assert world.private_playlist.owner_id != world.restricted.id


def test_a_by_name_row_is_reached_through_the_items_that_reference_it(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """A genre is not *in* a library; it is referenced by items that are, so `library_id` is null
    and the library clause cannot speak about it.

    **T5 left this exempt and T8 closed it**, which is why the test was written before the clause
    existed: plan §6.1 gives by-name rows a clause of their own - a genre exists for a user while
    a *visible* item references it. The restricted user still sees the film genres, because the
    films that carry them are in the library that user may see; `test_item_by_name.py` is where
    the adversarial half lives.
    """
    page = repository.run(ItemQuery(user=world.restricted, limit=1000))
    assert any(one.item.is_by_name for one in page.items)


def test_the_restricted_user_sees_nothing_of_another_library_under_a_parent(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The scope shape that would be missed: a predicate applied to the unscoped branch only."""
    shows_root = identity.for_library(world.shows.id)
    with pytest.raises(ParentNotFoundError):
        repository.run(ItemQuery(user=world.restricted, parent_id=shows_root, recursive=True))


def test_the_restricted_user_sees_nothing_recursively_either(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    movies_root = identity.for_library(world.movies.id)
    page = repository.run(
        ItemQuery(user=world.restricted, parent_id=movies_root, recursive=True, limit=1000)
    )
    assert {one.item.library_id for one in page.items} == {world.movies.id}


def test_the_user_permitted_nothing_sees_nothing(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """AC-9's user. An empty page, not an error - the criterion is about a `200` with no rows."""
    page = repository.run(ItemQuery(user=world.nobody, limit=1000))
    assert [one for one in page.items if one.item.library_id is not None] == []


# ------------------------------------------------------------------------------------------
# Scope shapes
# ------------------------------------------------------------------------------------------


def test_direct_children_are_one_level(repository: ItemQueryRepository, world: QueryWorld) -> None:
    series = world.series[0]
    page = repository.run(ItemQuery(user=world.everyone, parent_id=series.id, limit=1000))
    assert ids(page) == set(series.seasons)


def test_recursive_under_a_series_reaches_its_episodes(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Two hops, bounded by `DESCENT`. A one-hop implementation returns the seasons and passes a
    test that only counted rows."""
    series = world.series[0]
    page = repository.run(
        ItemQuery(user=world.everyone, parent_id=series.id, recursive=True, limit=1000)
    )
    assert ids(page) == set(series.seasons) | set(series.episodes)


def test_recursive_under_a_library_is_everything_it_holds(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    root = identity.for_library(world.movies.id)
    page = repository.run(
        ItemQuery(user=world.everyone, parent_id=root, recursive=True, limit=1000)
    )
    assert ids(page) == set(world.corpus)
    assert root not in ids(page), "a library is not its own descendant"


def test_an_unknown_parent_is_the_typed_refusal(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    with pytest.raises(ParentNotFoundError):
        repository.run(ItemQuery(user=world.everyone, parent_id="f" * 32))


def test_an_invisible_parent_raises_the_same_refusal(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The same exception for "no such item" and "not yours", which is what plan §6.13 turns into
    one identical `404`. A client that could tell them apart could enumerate another user's
    library one identifier at a time."""
    music_root = identity.for_library(world.music.id)
    with pytest.raises(ParentNotFoundError):
        repository.run(ItemQuery(user=world.restricted, parent_id=music_root))


# ------------------------------------------------------------------------------------------
# Containers earn their place (behaviours 5.2)
# ------------------------------------------------------------------------------------------


def test_a_series_whose_episodes_are_all_gone_is_not_offered(
    session: OrmSession, repository: ItemQueryRepository, world: QueryWorld
) -> None:
    series = world.series[2]
    ItemRepository(session).mark_removed(list(series.episodes), datetime(2026, 4, 1, tzinfo=UTC))
    session.flush()

    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    assert series.id not in ids(page), "a container with nothing visible beneath it is offered"
    for season in series.seasons:
        assert season not in ids(page)


def test_the_emptied_library_itself_remains(
    session: OrmSession, repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`CollectionFolder` is exempt, and the exemption is the point: an empty library is still a
    library and a client's sidebar must not lose it during a slow mount."""
    every_episode = [episode for handle in world.series for episode in handle.episodes]
    ItemRepository(session).mark_removed(every_episode, datetime(2026, 4, 1, tzinfo=UTC))
    session.flush()

    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    assert identity.for_library(world.shows.id) in ids(page)
    assert not (types_in(page) & EARN_THEIR_PLACE & {ItemType.SERIES, ItemType.SEASON})


def test_a_partly_emptied_series_is_still_offered(
    session: OrmSession, repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """One surviving episode is enough. A predicate written as "no removed children" rather than
    "some visible child" hides a series the moment anything under it goes."""
    series = world.series[0]
    ItemRepository(session).mark_removed(
        list(series.episodes[1:]), datetime(2026, 4, 1, tzinfo=UTC)
    )
    session.flush()
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    assert series.id in ids(page)


# ------------------------------------------------------------------------------------------
# The count
# ------------------------------------------------------------------------------------------


def test_the_count_is_the_prepaging_count(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    root = identity.for_library(world.movies.id)
    page = repository.run(ItemQuery(user=world.everyone, parent_id=root, recursive=True, limit=7))
    assert len(page.items) == 7
    assert page.total == CORPUS_SIZE


def test_the_count_obeys_the_same_predicates_as_the_page(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Derived from the page's own statement rather than rebuilt beside it. Two statements meant
    to carry the same predicates that drifted is how a client pages past the end."""
    unrestricted = repository.run(ItemQuery(user=world.everyone, limit=1000))
    restricted = repository.run(ItemQuery(user=world.restricted, limit=1000))
    assert restricted.total < unrestricted.total
    assert restricted.total == len(restricted.items)


def test_count_false_reports_zero_and_asks_nothing(
    engine: Engine,
    repository: ItemQueryRepository,
    world: QueryWorld,
    query_counter: QueryCounter,
) -> None:
    """`0` rather than `None`: the reference answers a number either way, and the server saved a
    query. Asserted on the statement count, because "reports 0" alone would pass an
    implementation that counted and then threw the answer away."""
    with query_counter.watching(engine):
        with_count = repository.run(ItemQuery(user=world.everyone, limit=5))
        counted = len(query_counter)
        query_counter.reset()
        without = repository.run(ItemQuery(user=world.everyone, limit=5, count=False))
        uncounted = len(query_counter)

    assert with_count.total > 0
    assert without.total == 0
    assert uncounted == counted - 1, query_counter.report()


# ------------------------------------------------------------------------------------------
# Hydration, and the statement count that keeps it honest
# ------------------------------------------------------------------------------------------


def test_a_hydrated_item_answers_everything_without_a_session(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(ItemQuery(user=world.everyone, ids=None, limit=1000))
    poster = next(one for one in page.items if one.id == world.corpus[0])
    assert [link.name for link in poster.genres] == ["sci-fi"]
    assert [link.name for link in poster.studios] == ["A Studio"]
    assert [credit.name for credit in poster.people] == ["A Director", "An Actor"]
    assert [image.kind.value for image in poster.images] == ["Primary"]
    assert poster.user_data.is_favorite is True


def test_the_artist_credits_keep_their_kind(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`/Artists` and `/Artists/AlbumArtists` are these rows and this column, and nothing else."""
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    album = next(one for one in page.items if one.id == world.album)
    assert [(link.name, link.credit) for link in album.artists] == [(ALBUM_ARTIST, "album_artist")]


def test_a_track_performer_who_is_nobodys_album_artist_has_no_item(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    solo = next(
        link
        for one in page.items
        if one.id in world.tracks
        for link in one.artists
        if link.name == "Solo Performer"
    )
    assert solo.item_id is None


def test_an_item_with_nothing_attached_still_hydrates(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Empty, not absent, and `UserData` present with defaults (behaviours §2.1). A hydrator that
    skipped the empty case would make every plain item answer `None` to five questions."""
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    plain = next(one for one in page.items if one.id == world.corpus[50])
    assert plain.genres == () and plain.people == () and plain.images == ()
    assert plain.user_data == UserItemData()


def test_metadata_arrives_with_the_row(repository: ItemQueryRepository, world: QueryWorld) -> None:
    """The 004 columns, read back at last - the mapping gap T9 closed. No extra statement: the
    values ride the row the page already fetched."""
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    poster = next(one for one in page.items if one.id == world.corpus[0])
    assert poster.metadata.overview == "A film about everything."
    assert poster.metadata.original_title == "Roc & Roll"
    assert poster.metadata.official_rating == "PG"
    assert poster.metadata.tags == ("blue",)
    assert poster.metadata.provider_ids == {"Imdb": "tt0000001", "Tmdb": "42"}
    dated = next(one for one in page.items if one.id == world.corpus[1])
    assert dated.metadata.runtime_ticks == RUNTIME_TICKS
    assert dated.metadata.premiere_date is not None


def test_an_episode_arrives_with_its_ancestors(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Parent and grandparent, summarised with their images - what `SeriesName` and the
    `Parent*` tags are emitted from. Only the first series carries images, so a walk that finds
    nothing everywhere cannot pass as one that works."""
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    episode = next(one for one in page.items if one.id == world.series[0].episodes[0])
    assert episode.parent is not None and episode.parent.id == world.series[0].seasons[0]
    assert episode.grandparent is not None and episode.grandparent.id == world.series[0].id
    assert episode.grandparent.name == world.series[0].name
    assert {image.kind.value for image in episode.grandparent.images} == {
        "Primary",
        "Thumb",
        "Backdrop",
    }
    track = next(one for one in page.items if one.id == world.tracks[0])
    assert track.parent is not None and track.parent.id == world.album
    assert [link.credit for link in track.parent.artists] == ["album_artist"]


def test_a_containers_user_data_is_a_rollup_of_its_subtree(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """One of six episodes watched: five unplayed, not played. A film has no rollup, and the
    shows library folder rolls up every series at once."""
    page = repository.run(ItemQuery(user=world.everyone, limit=1000))
    series = next(one for one in page.items if one.id == world.series[0].id)
    assert series.user_data.unplayed_count == len(world.series[0].episodes) - 1
    assert series.user_data.played is False

    film = next(one for one in page.items if one.id == world.corpus[50])
    assert film.user_data.unplayed_count is None

    episodes = sum(len(handle.episodes) for handle in world.series)
    folder = next(
        one
        for one in page.items
        if one.item.type is ItemType.COLLECTION_FOLDER and one.item.library_id == world.shows.id
    )
    assert folder.user_data.unplayed_count == episodes - len(world.series)


def test_aggregates_answer_for_the_containers_asked_about(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The gated subtree numbers: direct children, recursive files, runtime, latest arrival."""
    first = world.series[0]
    movies_folder = identity.for_library(world.movies.id)
    numbers = repository.aggregates_for([first.id, movies_folder], world.everyone)

    assert numbers[first.id].child_count == len(first.seasons)
    assert numbers[first.id].recursive_count == len(first.episodes)
    assert numbers[first.id].date_last_media_added is not None

    assert numbers[movies_folder].child_count == CORPUS_SIZE
    assert numbers[movies_folder].recursive_count == CORPUS_SIZE
    # Exactly one film carries a runtime, so the folder's cumulative sum is that runtime.
    assert numbers[movies_folder].cumulative_runtime_ticks == RUNTIME_TICKS


def test_the_statement_count_does_not_grow_with_the_page(
    engine: Engine,
    repository: ItemQueryRepository,
    world: QueryWorld,
    query_counter: QueryCounter,
) -> None:
    """The N+1 ban, as a contract rather than a hope. This is the assertion the whole shape of
    `_hydrate` exists to satisfy - one query per related table, never one per item."""
    with query_counter.watching(engine):
        repository.run(ItemQuery(user=world.everyone, limit=1))
        small = len(query_counter)
        query_counter.reset()
        repository.run(ItemQuery(user=world.everyone, limit=50))
        large = len(query_counter)

    assert small == large, (
        f"a page of 1 cost {small} statements and a page of 50 cost {large}. Hydration must not "
        f"grow with the page.\n{query_counter.report()}"
    )


def test_the_statement_count_is_what_the_plan_says_it_is(
    engine: Engine,
    repository: ItemQueryRepository,
    world: QueryWorld,
    query_counter: QueryCounter,
) -> None:
    """One count, one page, one per related table - plus what T9 added, still page-independent:
    parents and grandparents with their images and artists (four - an episode's row carries its
    series' name and tags), and the two played-rollup shapes (a container's `UserData` is a
    statement about its subtree). Written as a number so that a *new* related table shows up
    here as a decision rather than as drift.

    **Two more since 008 T3**: the page's media probes and their streams. Unconditional, like the
    ancestors above and for the same reason - a page carries `Container`, `HasSubtitles` and
    `VideoType` on a *bare* row, so a hydrator that fetched inspections only when something asked
    for `MediaSources` would need them anyway on every list of films, and a count that depended on
    what the page happened to hold would make the equality here meaningless.

    **A third since 011 T4**: the subtitle streams discovered in files beside the media. It is not
    optional and it is not conditional - those streams are numbered *ahead of* the container's
    own, so a page hydrated without them answers wrong indices for the video and audio it does
    carry, and `HasSubtitles` is false on an item whose subtitles are all files (AC-11). One
    statement for the page, like its two neighbours."""
    with query_counter.watching(engine):
        repository.run(ItemQuery(user=world.everyone, limit=10))
    assert len(query_counter) == 18, query_counter.report()


def test_a_page_with_no_files_costs_the_same_as_a_page_of_films(
    engine: Engine,
    repository: ItemQueryRepository,
    world: QueryWorld,
    query_counter: QueryCounter,
) -> None:
    """The inspection statements run whether or not the page has a file behind it.

    A page of containers has nothing to look up, and skipping the two reads for it would make the
    count a property of what the page happened to hold - which is the drift the number above is
    written to catch. The predicate compiles to a false clause instead.
    """
    with query_counter.watching(engine):
        repository.run(
            ItemQuery(user=world.everyone, include_types=frozenset({ItemType.SERIES}), limit=10)
        )
        containers = len(query_counter)
        query_counter.reset()
        repository.run(
            ItemQuery(user=world.everyone, include_types=frozenset({ItemType.MOVIE}), limit=10)
        )
        films = len(query_counter)
    assert containers == films, query_counter.report()


def test_an_empty_page_costs_no_hydration(
    engine: Engine,
    repository: ItemQueryRepository,
    world: QueryWorld,
    query_counter: QueryCounter,
) -> None:
    """Paged past the end: the count still runs, and the seven hydration queries do not. A
    hydrator that issued them against an empty id list would be seven round trips for nothing on
    the last page of every list a client scrolls."""
    with query_counter.watching(engine):
        page = repository.run(ItemQuery(user=world.everyone, start_index=100_000, limit=10))
    assert page.items == ()
    assert page.total > 0
    assert len(query_counter) == 2, query_counter.report()


# ------------------------------------------------------------------------------------------
# The cascade's target set (007 T4)
# ------------------------------------------------------------------------------------------


def test_a_seasons_leaves_are_its_episodes(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    handle = world.series[0]
    season = handle.seasons[0]
    under = set(repository.leaf_descendants(season, world.everyone))
    assert under, "a season with episodes answered nothing"
    assert under < set(handle.episodes), "a season answered episodes of another season"
    assert season not in under, "the container's own row is in the set that gets written"


def test_a_series_reaches_its_episodes_through_its_seasons(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Two hops, which is what makes "mark the series watched" work at all - and no seasons in
    the answer, because a season's own row is never written (spec section 3.4)."""
    handle = world.series[0]
    under = set(repository.leaf_descendants(handle.id, world.everyone))
    assert under == set(handle.episodes)
    assert not under & set(handle.seasons)


def test_a_library_folder_reaches_everything_beneath_it(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The `CollectionFolder` fast path: every item under a library carries its id."""
    under = set(repository.leaf_descendants(identity.for_library(world.shows.id), world.everyone))
    assert under == {episode for handle in world.series for episode in handle.episodes}


def test_a_leaf_has_no_leaves(repository: ItemQueryRepository, world: QueryWorld) -> None:
    """A film answers nothing, and so would an empty season - which is why a caller branches on
    the item's type rather than on this being empty."""
    assert repository.leaf_descendants(world.corpus[0], world.everyone) == ()


def test_the_album_reaches_its_tracks_and_not_its_artist(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    assert set(repository.leaf_descendants(world.album, world.everyone)) == set(world.tracks)


def test_a_removed_episode_is_not_a_target(
    repository: ItemQueryRepository, session: OrmSession, world: QueryWorld
) -> None:
    """Plan section 9's risk row: a cascade that swept soft-removed rows would write state for
    items no query can see, and the user would find them played if the file ever came back."""
    handle = world.series[0]
    gone = handle.episodes[0]
    row = session.get(models.Item, gone)
    assert row is not None
    row.removed_at = datetime(2026, 8, 1, tzinfo=UTC)
    session.flush()
    assert gone not in repository.leaf_descendants(handle.id, world.everyone)


def test_the_set_is_the_callers_own_scope(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """A user whose policy excludes the shows library cannot reach its season at all - the same
    refusal every scoped query makes, so a mark cannot tell a caller that an item exists."""
    with pytest.raises(ParentNotFoundError):
        repository.leaf_descendants(world.series[0].seasons[0], world.restricted)


def test_an_unknown_item_is_the_same_refusal(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    with pytest.raises(ParentNotFoundError):
        repository.leaf_descendants("0" * 32, world.everyone)
