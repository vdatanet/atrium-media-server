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
from atrium.db import schema
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
from tests.fixtures.query import ALBUM_ARTIST, CORPUS_SIZE, QueryWorld, build_query_world


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
    libraries = {one.item.library_id for one in page.items if not one.item.is_by_name}
    assert libraries == {world.movies.id}, (
        "an item of an unpermitted library reached a user whose policy excludes it"
    )


def test_a_by_name_row_is_exempt_from_the_library_clause_for_now(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """A genre is not *in* a library; it is referenced by items that are, so `library_id` is null
    and the library clause cannot speak about it.

    **This is deliberately incomplete.** Plan §6.1 gives by-name rows a clause of their own - a
    genre exists for a user while a visible item references it - and that arrives with the by-name
    queries in T8. Pinned here so that the day it changes, this test says so rather than a
    `/Genres` test failing for reasons nobody connects to this predicate.
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
    """One count, one page, one per related table. Written as a number so that a *new* related
    table shows up here as a decision rather than as drift."""
    with query_counter.watching(engine):
        repository.run(ItemQuery(user=world.everyone, limit=10))
    assert len(query_counter) == 9, query_counter.report()


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
