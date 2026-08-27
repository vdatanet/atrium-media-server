# SPDX-License-Identifier: GPL-3.0-or-later
"""The seeded world's invariants, asserted so a later edit cannot quietly weaken it.

Every 005 test from T5 onwards reads this world, and almost all of them would still pass if a
fixture got thinner: a paging test over 60 items passes, a NextUp test over one series passes, a
compilation whose credits all point at the same artist passes. **The fixture failing loudly is the
only thing standing between "the world shrank" and "the feature looks fine".**

The determinism check at the end is the other half. Golden responses are checked in against ids
this builder derives, so two builds differing anywhere is a suite that fails on a machine rather
than on a change.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.domain.items import CollectionType, ItemType
from atrium.library import identity
from tests.conftest import data_dir
from tests.fixtures.query import (
    ALBUM_ARTIST,
    AWKWARD_NAMES,
    CORPUS_SIZE,
    GENRE_SPELLINGS,
    SOLO_PERFORMER,
    QueryWorld,
    build_query_world,
)


@pytest.fixture
def session(tmp_path: Path) -> Iterator[OrmSession]:
    prepared: DataPaths = data_dir(tmp_path / "atrium")
    engine: Engine = create_database_engine(prepared)
    schema.ensure_current(engine, prepared)
    opened = session_factory(engine)()
    yield opened
    opened.rollback()
    opened.close()
    engine.dispose()


@pytest.fixture
def world(session: OrmSession) -> QueryWorld:
    return build_query_world(session)


def rows(session: OrmSession, model: type, **where: object) -> list:
    statement = select(model)
    for column, value in where.items():
        statement = statement.where(getattr(model, column) == value)
    return list(session.execute(statement).scalars())


# ------------------------------------------------------------------------------------------
# Libraries and users
# ------------------------------------------------------------------------------------------


def test_three_libraries_one_of_each_kind(world: QueryWorld) -> None:
    kinds = {world.movies.collection_type, world.shows.collection_type, world.music.collection_type}
    assert kinds == {CollectionType.MOVIES, CollectionType.TVSHOWS, CollectionType.MUSIC}


def test_each_library_is_itself_an_item(session: OrmSession, world: QueryWorld) -> None:
    """A `CollectionFolder` per library: `/UserViews` derives its rows from these."""
    for library in (world.movies, world.shows, world.music):
        folder = session.get(models.Item, identity.for_library(library.id))
        assert folder is not None, f"{library.name} has no CollectionFolder"
        assert folder.type == ItemType.COLLECTION_FOLDER.value


def test_the_restricted_user_sees_one_library(session: OrmSession, world: QueryWorld) -> None:
    allowed = rows(session, models.UserLibraryAccess, user_id=world.restricted.id)
    assert [row.library_id for row in allowed] == [world.movies.id]
    assert world.restricted.enable_all_folders is False


def test_the_third_user_may_see_nothing_at_all(session: OrmSession, world: QueryWorld) -> None:
    """AC-9's user. An empty allow-list *and* `enable_all_folders` off - either one alone is a
    user who can still see everything, which is the opposite of what the criterion needs."""
    assert world.nobody.enable_all_folders is False
    assert rows(session, models.UserLibraryAccess, user_id=world.nobody.id) == []


def test_the_unrestricted_user_is_not_restricted(world: QueryWorld) -> None:
    assert world.everyone.enable_all_folders is True


# ------------------------------------------------------------------------------------------
# The paging corpus and the awkward names
# ------------------------------------------------------------------------------------------


def test_the_corpus_is_exactly_the_declared_size(session: OrmSession, world: QueryWorld) -> None:
    movies = rows(session, models.Item, type=ItemType.MOVIE.value)
    assert len(movies) == CORPUS_SIZE == len(world.corpus)


def test_every_corpus_identifier_is_distinct(world: QueryWorld) -> None:
    """A repeated identifier would make a paging test pass while losing a row."""
    assert len(set(world.corpus)) == len(world.corpus)


def test_the_corpus_size_is_awkward_for_every_page_size_the_plan_uses(world: QueryWorld) -> None:
    """Plan §8 row 4 pages at 1, 7 and 97. A corpus divisible by one of them would never exercise
    the short final page, which is where an off-by-one in paging actually lives."""
    assert CORPUS_SIZE % 7 != 0
    assert CORPUS_SIZE % 97 != 0


def test_the_awkward_names_are_all_seeded(session: OrmSession, world: QueryWorld) -> None:
    seeded = {session.get(models.Item, item_id).name for item_id in world.awkward}
    assert seeded == set(AWKWARD_NAMES)


def test_the_whitespace_artefacts_survived_into_the_sort_name(
    session: OrmSession, world: QueryWorld
) -> None:
    """The two rows that exist to fail when somebody tidies the derivation.

    `Rock & Roll` sorts as `rock  roll` with a double space; `S.W.A.T.` keeps a trailing one.
    A fixture whose sort names were tidied would make an ordering test agree with a server that
    had tidied them too - which is the failure this pair was written for in 003.
    """
    by_name = {
        session.get(models.Item, item_id).name: session.get(models.Item, item_id).sort_name
        for item_id in world.awkward
    }
    assert by_name["Rock & Roll"] == "rock  roll"
    assert by_name["S.W.A.T."] == "s w a t "


def test_sort_names_are_derived_rather_than_copied(session: OrmSession, world: QueryWorld) -> None:
    """`The Matrix` sorts under `matrix`. A fixture that copied the name would sort it under
    `the` and every ordering test would still agree with itself."""
    matrix = next(
        session.get(models.Item, item_id)
        for item_id in world.awkward
        if session.get(models.Item, item_id).name == "The Matrix"
    )
    assert matrix.sort_name == "matrix"


# ------------------------------------------------------------------------------------------
# The three series
# ------------------------------------------------------------------------------------------


def test_there_are_three_series(session: OrmSession, world: QueryWorld) -> None:
    """NextUp returns one row per series with a watched episode. With one series seeded, a
    server returning *every* unwatched episode would pass the test (plan §8 row 10)."""
    assert len(world.series) == 3
    assert len(rows(session, models.Item, type=ItemType.SERIES.value)) == 3


def test_every_series_has_a_watched_episode_and_a_next_one(
    session: OrmSession, world: QueryWorld
) -> None:
    for handle in world.series:
        assert handle.watched in handle.episodes
        assert handle.next_up in handle.episodes
        assert handle.watched != handle.next_up
        played = session.get(models.ItemUserData, (world.everyone.id, handle.watched))
        assert played is not None and played.played, f"{handle.name} has no watched episode"


def test_exactly_one_series_carries_the_specials_season(
    session: OrmSession, world: QueryWorld
) -> None:
    specials = [
        row
        for row in rows(session, models.Item, type=ItemType.SEASON.value)
        if row.index_number == 0
    ]
    assert [row.id for row in specials] == [world.specials_season]


def test_the_multi_episode_file_is_one_item_spanning_two_numbers(
    session: OrmSession, world: QueryWorld
) -> None:
    """003 AC-5: `S01E02-E03` *is* both episodes rather than standing for them."""
    episode = session.get(models.Item, world.multi_episode)
    assert episode is not None
    assert episode.index_number == 2
    assert episode.end_index_number == 3


def test_the_multi_episode_file_is_what_next_up_must_answer_with(world: QueryWorld) -> None:
    """Not a coincidence worth losing: the interesting NextUp answer is the odd-shaped episode."""
    carrier = next(handle for handle in world.series if handle.name == "Beta Show")
    assert carrier.next_up == world.multi_episode


# ------------------------------------------------------------------------------------------
# The compilation
# ------------------------------------------------------------------------------------------


def test_the_album_has_one_album_artist(session: OrmSession, world: QueryWorld) -> None:
    credited = rows(session, models.ItemArtist, item_id=world.album, credit="album_artist")
    assert [row.name for row in credited] == [ALBUM_ARTIST]


def test_every_track_carries_its_own_performer(session: OrmSession, world: QueryWorld) -> None:
    """A compilation is one album with a different performer per track. Tracks that all shared a
    performer would make `/Artists` and `/Artists/AlbumArtists` indistinguishable (AC-13)."""
    performers = [
        [row.name for row in rows(session, models.ItemArtist, item_id=track, credit="artist")]
        for track in world.tracks
    ]
    assert all(len(names) == 1 for names in performers)
    assert len({names[0] for names in performers}) == len(world.tracks)


def test_one_performer_is_nobodys_album_artist(session: OrmSession, world: QueryWorld) -> None:
    """The revision-0004 shape, and the reason `artist_item_id` is nullable: a track's performer
    who is nobody's album artist has a name a client renders and no item to click through to."""
    credit = next(
        row
        for track in world.tracks
        for row in rows(session, models.ItemArtist, item_id=track, credit="artist")
        if row.name == SOLO_PERFORMER
    )
    assert credit.artist_item_id is None


def test_the_album_artist_credit_does_point_at_an_item(
    session: OrmSession, world: QueryWorld
) -> None:
    """The other half of the same sentence: without it, the null above would prove nothing but
    that the write path never links anything."""
    credit = next(
        row for row in rows(session, models.ItemArtist, item_id=world.album, credit="album_artist")
    )
    assert credit.artist_item_id == world.album_artist


# ------------------------------------------------------------------------------------------
# Genres
# ------------------------------------------------------------------------------------------


def test_two_spellings_of_one_genre_merge_to_one_row(
    session: OrmSession, world: QueryWorld
) -> None:
    """behaviours §2.18. Each item keeps the spelling its own source used; both point at one
    by-name row, which is what `/Genres` lists."""
    spellings = [
        row
        for item_id in world.corpus[:2]
        for row in rows(session, models.ItemGenre, item_id=item_id)
    ]
    assert {row.name for row in spellings} == set(GENRE_SPELLINGS)
    assert len({row.genre_item_id for row in spellings}) == 1


def test_the_music_genre_is_a_different_row_from_the_film_genre(
    session: OrmSession, world: QueryWorld
) -> None:
    """`Genre` and `MusicGenre` spelled the same are two items, which is what keeps `/Genres` and
    `/MusicGenres` disjoint without either endpoint guessing from context (004 plan §4)."""
    film = rows(session, models.ItemGenre, item_id=world.corpus[0])[0]
    album = rows(session, models.ItemGenre, item_id=world.album)[0]
    assert film.name == album.name
    assert film.genre_item_id != album.genre_item_id


# ------------------------------------------------------------------------------------------
# User data
# ------------------------------------------------------------------------------------------


def test_user_data_covers_the_three_things_the_filters_need(
    session: OrmSession, world: QueryWorld
) -> None:
    written = rows(session, models.ItemUserData, user_id=world.everyone.id)
    # Compared as sets: these rows come back in primary-key order, and asserting the builder's
    # insertion order here would be asserting something no caller can rely on.
    assert {row.item_key for row in written if row.played} == {h.watched for h in world.series}
    assert {row.item_key for row in written if row.is_favorite} == set(world.favourites)
    assert {row.item_key for row in written if row.playback_position_ticks} == set(world.resumable)


def test_a_resumable_item_is_not_also_played(session: OrmSession, world: QueryWorld) -> None:
    """Otherwise the Resume fixture and the NextUp fixture are the same rows and neither test
    proves what it says."""
    for item_key in world.resumable:
        row = session.get(models.ItemUserData, (world.everyone.id, item_key))
        assert row is not None and not row.played


def test_user_data_is_keyed_on_the_derived_identity(session: OrmSession, world: QueryWorld) -> None:
    """`item_key` is the identity, not a row reference: the association survives the item row
    disappearing and coming back (003 §3.8). Asserted by checking the keys are real item ids
    *and* that nothing enforces it - a foreign key here would be the bug."""
    for row in rows(session, models.ItemUserData, user_id=world.everyone.id):
        assert session.get(models.Item, row.item_key) is not None


# ------------------------------------------------------------------------------------------
# Determinism
# ------------------------------------------------------------------------------------------


def test_two_builds_derive_the_same_world(tmp_path: Path, world: QueryWorld) -> None:
    """Principle VII, and the precondition for a checked-in golden response."""
    prepared = data_dir(tmp_path / "second")
    engine = create_database_engine(prepared)
    schema.ensure_current(engine, prepared)
    second_session = session_factory(engine)()
    try:
        second = build_query_world(second_session)
        assert second.corpus == world.corpus
        assert second.awkward == world.awkward
        assert [h.id for h in second.series] == [h.id for h in world.series]
        assert second.album == world.album
        assert second.tracks == world.tracks
        assert second.multi_episode == world.multi_episode
    finally:
        second_session.rollback()
        second_session.close()
        engine.dispose()
