# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Genres`, `/MusicGenres`, `/Artists`, `/Artists/AlbumArtists` and `/Years`, at the repository.

Two things are adversarial here rather than illustrative.

**A by-name row discloses what is in a library even when its items do not.** A genre whose every
film sits in a library the user cannot see is not a leak of the films — it is a leak of the fact
that the library contains science fiction. The test that matters is the one that makes a genre
*unreachable* for one user and reachable for another, from the same database.

**`/Artists` and `/Artists/AlbumArtists` are one query and one column.** AC-13 says the first
strictly contains the second, in that direction, and a fixture where they coincide proves nothing
— which is why T6 gave the world a guest track.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.item_queries import ALBUM_ARTIST_CREDIT, ItemQueryRepository
from atrium.domain.items import ItemType
from atrium.domain.queries import ItemQuery
from atrium.library import identity
from tests.conftest import QueryCounter, data_dir
from tests.fixtures.query import (
    ALBUM_ARTIST,
    FIRST_YEAR,
    GENRE_SPELLINGS,
    GUEST_ALBUM_ARTIST,
    RATED,
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


def names(page: object) -> list[str]:
    return [one.item.name for one in page.items]  # type: ignore[attr-defined]


# ------------------------------------------------------------------------------------------
# The rows exist at all
# ------------------------------------------------------------------------------------------


def test_genres_lists_the_film_genre(repository: ItemQueryRepository, world: QueryWorld) -> None:
    page = repository.run_by_name(ItemType.GENRE, ItemQuery(user=world.everyone, limit=100))
    assert names(page) == [GENRE_SPELLINGS[0]], (
        "two spellings of one genre are one row, showing the first spelling anybody used"
    )
    assert page.total == 1


def test_music_genres_is_a_different_row_of_the_same_name(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`/Genres` and `/MusicGenres` are disjoint without either endpoint guessing from context
    (004 plan §4). The same spelling on a film and on an album is two rows."""
    films = repository.run_by_name(ItemType.GENRE, ItemQuery(user=world.everyone, limit=100))
    music = repository.run_by_name(ItemType.MUSIC_GENRE, ItemQuery(user=world.everyone, limit=100))
    assert names(films) == names(music)
    assert {one.id for one in films.items}.isdisjoint({one.id for one in music.items})


def test_years_lists_the_years_the_library_has(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """**Nothing created these rows until T8.** A `Year` is referenced by
    `items.production_year` rather than by a join table, so it had no write path of its own —
    while `collect_by_name_garbage` had always protected them on the assumption that something
    made them.
    """
    page = repository.run_by_name(ItemType.YEAR, ItemQuery(user=world.everyone, limit=100))
    assert page.total == RATED
    assert str(FIRST_YEAR) in names(page)


def test_a_year_row_is_an_item_like_any_other(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Which is why deriving `/Years` from a `DISTINCT` instead of materialising rows would have
    been the wrong shape: `GET /Items/{yearId}` has to answer too."""
    year_id = identity.for_by_name(ItemType.YEAR, str(FIRST_YEAR))
    page = repository.run(ItemQuery(user=world.everyone, ids=(year_id,), limit=10))
    assert [one.item.type for one in page.items] == [ItemType.YEAR]


def test_artists_lists_both_music_artists(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run_by_name(ItemType.MUSIC_ARTIST, ItemQuery(user=world.everyone, limit=100))
    assert set(names(page)) == {ALBUM_ARTIST, GUEST_ALBUM_ARTIST}


# ------------------------------------------------------------------------------------------
# AC-13: the credit distinction, in the right direction
# ------------------------------------------------------------------------------------------


def test_any_credit_strictly_contains_the_album_credit(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """AC-13. `/Artists` is every credited artist; `/Artists/AlbumArtists` only those credited on
    an album — and the containment runs in that direction and no other.

    A fixture where the two coincide passes an implementation that ignores the column entirely,
    which is why the world carries a track performed by somebody who is nobody's album artist.
    """
    every = repository.run_by_name(
        ItemType.MUSIC_ARTIST, ItemQuery(user=world.everyone, limit=100), credit=None
    )
    album = repository.run_by_name(
        ItemType.MUSIC_ARTIST,
        ItemQuery(user=world.everyone, limit=100),
        credit=ALBUM_ARTIST_CREDIT,
    )
    assert {one.id for one in album.items} <= {one.id for one in every.items}
    assert every.total >= album.total


def test_an_artist_credited_only_as_a_performer_is_absent_from_album_artists(
    session: OrmSession, repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The direction that matters. With every artist credited both ways the containment above is
    an equality and proves nothing, so this removes the album credit from one of them."""
    from atrium.db import models

    session.execute(
        models.ItemArtist.__table__.delete().where(
            models.ItemArtist.artist_item_id == world.guest_artist,
            models.ItemArtist.credit == ALBUM_ARTIST_CREDIT,
        )
    )
    session.flush()

    every = repository.run_by_name(
        ItemType.MUSIC_ARTIST, ItemQuery(user=world.everyone, limit=100), credit=None
    )
    album = repository.run_by_name(
        ItemType.MUSIC_ARTIST,
        ItemQuery(user=world.everyone, limit=100),
        credit=ALBUM_ARTIST_CREDIT,
    )
    assert {one.id for one in album.items} < {one.id for one in every.items}
    assert world.guest_artist not in {one.id for one in album.items}


# ------------------------------------------------------------------------------------------
# Visibility, adversarially
# ------------------------------------------------------------------------------------------


def test_a_genre_whose_every_item_is_invisible_is_absent(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The by-name clause of the predicate, and the reason it is in the *general* predicate rather
    than in `run_by_name`: a genre whose every film sits in a library the user cannot see is not a
    leak of the films, it is a leak of what the library contains.

    The music genre is carried only by the compilation, which the restricted user cannot see.
    """
    restricted = repository.run_by_name(
        ItemType.MUSIC_GENRE, ItemQuery(user=world.restricted, limit=100)
    )
    unrestricted = repository.run_by_name(
        ItemType.MUSIC_GENRE, ItemQuery(user=world.everyone, limit=100)
    )
    assert restricted.total == 0
    assert unrestricted.total == 1


def test_the_same_row_is_reachable_for_a_user_who_may_see_its_items(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Otherwise the test above would pass on an implementation that hides every by-name row."""
    page = repository.run_by_name(ItemType.GENRE, ItemQuery(user=world.restricted, limit=100))
    assert page.total == 1


def test_a_by_name_row_agrees_with_the_item_query(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`/Items?includeItemTypes=MusicGenre` and `/MusicGenres` are two routes over one predicate.
    Two predicates in two places is how they stop agreeing."""
    through_items = repository.run(
        ItemQuery(
            user=world.restricted,
            include_types=frozenset({ItemType.MUSIC_GENRE}),
            limit=100,
        )
    )
    through_by_name = repository.run_by_name(
        ItemType.MUSIC_GENRE, ItemQuery(user=world.restricted, limit=100)
    )
    assert through_items.total == through_by_name.total == 0


def test_a_year_disappears_with_the_films_that_carry_it(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The `Year` membership is a **column** rather than a join table, so it is the one branch of
    the clause that could have been forgotten."""
    everyone = repository.run_by_name(ItemType.YEAR, ItemQuery(user=world.everyone, limit=100))
    nobody = repository.run_by_name(ItemType.YEAR, ItemQuery(user=world.nobody, limit=100))
    assert everyone.total == RATED
    assert nobody.total == 0


# ------------------------------------------------------------------------------------------
# Scope, search, paging and the count
# ------------------------------------------------------------------------------------------


def test_parent_id_scopes_the_membership(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    under_music = repository.run_by_name(
        ItemType.GENRE,
        ItemQuery(user=world.everyone, parent_id=identity.for_library(world.music.id), limit=100),
    )
    under_films = repository.run_by_name(
        ItemType.GENRE,
        ItemQuery(user=world.everyone, parent_id=identity.for_library(world.movies.id), limit=100),
    )
    assert under_music.total == 0, "the film genre is not reachable from the music library"
    assert under_films.total == 1


def test_search_term_matches_the_folded_name(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    for typed in ("sci", "SCI-FI", "Sci"):
        page = repository.run_by_name(
            ItemType.GENRE, ItemQuery(user=world.everyone, search_term=typed, limit=100)
        )
        assert page.total == 1, typed


def test_the_count_is_true_with_and_without_a_limit(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """behaviours §3.1's divergence, at the repository. The reference disables counting on these
    routes when the request carries no `limit` and answers `TotalRecordCount: 0` beside a
    non-empty `Items`; Atrium always answers the true count, argued there and re-held on the wire
    at T14."""
    unlimited = repository.run_by_name(ItemType.YEAR, ItemQuery(user=world.everyone))
    limited = repository.run_by_name(ItemType.YEAR, ItemQuery(user=world.everyone, limit=2))
    assert unlimited.total == limited.total == RATED
    assert len(limited.items) == 2


def test_paging_a_by_name_list_is_total_too(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    whole = [
        one.id
        for one in repository.run_by_name(
            ItemType.YEAR, ItemQuery(user=world.everyone, limit=100)
        ).items
    ]
    walked: list[str] = []
    for start in range(0, RATED, 3):
        walked += [
            one.id
            for one in repository.run_by_name(
                ItemType.YEAR, ItemQuery(user=world.everyone, start_index=start, limit=3)
            ).items
        ]
    assert walked == whole


def test_a_by_name_query_costs_a_fixed_number_of_statements(
    engine: Engine,
    repository: ItemQueryRepository,
    world: QueryWorld,
    query_counter: QueryCounter,
) -> None:
    with query_counter.watching(engine):
        repository.run_by_name(ItemType.YEAR, ItemQuery(user=world.everyone, limit=2))
        small = len(query_counter)
        query_counter.reset()
        repository.run_by_name(ItemType.YEAR, ItemQuery(user=world.everyone, limit=100))
        large = len(query_counter)
    assert small == large, query_counter.report()
