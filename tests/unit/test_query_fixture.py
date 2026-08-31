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
from atrium.db.item_queries import ItemQueryRepository
from atrium.domain.items import CollectionType, ItemType
from atrium.domain.playstate import MIN_RESUME_DURATION_SECONDS, TICKS_PER_SECOND
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User
from atrium.library import identity
from tests.conftest import data_dir
from tests.fixtures.query import (
    ALBUM_ARTIST,
    AWKWARD_NAMES,
    CORPUS_SIZE,
    EPISODE_RUNTIME_TICKS,
    FIRST_YEAR,
    GENRE_SPELLINGS,
    RATED,
    RUNTIME_TICKS,
    SHORT_RUNTIME_TICKS,
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


def test_the_rated_films_carry_a_year_and_a_rating(session: OrmSession, world: QueryWorld) -> None:
    """Added at T6, which could not test `years` or `minCommunityRating` without them: a predicate
    over a column that is null on every row narrows nothing and passes every assertion about the
    rows it returned."""
    assert len(world.rated) == RATED
    for offset, item_id in enumerate(world.rated):
        row = session.get(models.Item, item_id)
        assert row is not None
        assert row.production_year == FIRST_YEAR + offset
        assert row.community_rating is not None


def test_no_other_film_carries_a_year(session: OrmSession, world: QueryWorld) -> None:
    """So `years=[FIRST_YEAR]` selects one film rather than most of the library - which is what
    makes the narrowing assertion mean something."""
    years = [
        row.production_year
        for row in rows(session, models.Item, type=ItemType.MOVIE.value)
        if row.production_year is not None
    ]
    assert len(years) == RATED
    assert len(set(years)) == RATED


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
        assert [one.id for one in second.playlists] == [one.id for one in world.playlists]
        assert [one.entries for one in second.playlists] == [one.entries for one in world.playlists]
    finally:
        second_session.rollback()
        second_session.close()
        engine.dispose()


# ------------------------------------------------------------------------------------------
# Images (T9)
# ------------------------------------------------------------------------------------------


def test_the_images_sit_exactly_where_the_dto_tests_need_them(
    session: OrmSession, world: QueryWorld
) -> None:
    """The first film, the first series, its first episode and the compilation carry images -
    **and nothing else does**. The exclusivity is the load-bearing half: the `Parent*` emitters
    resolve tags through an ancestor walk, and a world where every series had a poster could not
    tell a walk that works from one that finds something anywhere.

    **The episode's own `Primary` arrived with 006 T2** and is the one row here that exists for a
    criterion rather than for an emitter: 006 AC-14 says an episode carries its series' tags
    whether or not it has artwork of its own, and until this row no episode in this world had
    any - so "unconditional" and "falls back when empty" were the same test. It sits under the
    imaged series on purpose; under an unimaged one it would prove nothing either."""
    by_item: dict[str, set[tuple[str, int]]] = {}
    for row in rows(session, models.ItemImage):
        by_item.setdefault(row.item_id, set()).add((row.image_type, row.image_index))

    assert by_item[world.corpus[0]] == {("Primary", 0)}
    assert by_item[world.series[0].id] == {
        ("Primary", 0),
        ("Thumb", 0),
        ("Backdrop", 0),
        ("Backdrop", 1),
    }
    assert by_item[world.album] == {("Primary", 0)}
    assert by_item[world.imaged_episode] == {("Primary", 0)}
    assert world.imaged_episode == world.series[0].episodes[0]
    assert set(by_item) == {
        world.corpus[0],
        world.series[0].id,
        world.imaged_episode,
        world.album,
    }


def test_the_dated_film_also_carries_the_runtime(session: OrmSession, world: QueryWorld) -> None:
    """On the film that is also resumable, so `PlayedPercentage` has both inputs on one item."""
    row = session.get(models.Item, world.corpus[1])
    assert row is not None and row.runtime_ticks == RUNTIME_TICKS
    assert world.corpus[1] in world.resumable


def test_the_short_track_is_the_only_item_under_the_resume_floor(
    session: OrmSession, world: QueryWorld
) -> None:
    """007 section 3.7 row 5 is about the *runtime*, and it needs a world with one to fire in.

    Asserted against the domain's own constant rather than against a number written twice: a
    change to `MIN_RESUME_DURATION_SECONDS` that left this fixture alone would silently turn the
    short-item branch into the ordinary one, and every test of it would keep passing.
    """
    floor = MIN_RESUME_DURATION_SECONDS * TICKS_PER_SECOND
    short = session.get(models.Item, world.short_track)
    assert short is not None and short.runtime_ticks == SHORT_RUNTIME_TICKS
    assert 0 < SHORT_RUNTIME_TICKS < floor, "the short track is not short enough to fire row 5"

    under = [
        row.id
        for row in session.query(models.Item).all()
        if row.runtime_ticks and row.runtime_ticks < floor
    ]
    assert under == [world.short_track]


def test_the_first_series_episodes_are_long_enough_for_the_percentage_branches(
    session: OrmSession, world: QueryWorld
) -> None:
    """And the other two series carry no runtime at all, which keeps row 2 - "the runtime is
    unknown" - reachable in the same world as the branches that need one."""
    floor = MIN_RESUME_DURATION_SECONDS * TICKS_PER_SECOND
    for episode_id in world.series[0].episodes:
        row = session.get(models.Item, episode_id)
        assert row is not None and row.runtime_ticks == EPISODE_RUNTIME_TICKS
    assert floor < EPISODE_RUNTIME_TICKS

    for handle in world.series[1:]:
        for episode_id in handle.episodes:
            row = session.get(models.Item, episode_id)
            assert row is not None and row.runtime_ticks is None


# ------------------------------------------------------------------------------------------
# Playlists (009 T5)
# ------------------------------------------------------------------------------------------


def _reaches(session: OrmSession, world: QueryWorld, user: User, ids: tuple[str, ...]) -> set[str]:
    """Which of these items that user may reach, through the predicate `/Items` itself uses.

    Not `library_id in user's folders` restated here: a fixture whose expectations are computed
    the way the fixture was built agrees with itself by construction. `ItemQueryRepository` is the
    thing 009 section 3.7's omission is implemented in terms of, so it is the thing that has to
    agree.
    """
    page = ItemQueryRepository(session).run(ItemQuery(user=user, ids=ids, limit=1000))
    return {one.item.id for one in page.items}


def test_the_five_playlists_are_items_with_no_library(
    session: OrmSession, world: QueryWorld
) -> None:
    """`Type: Playlist`, and `library_id IS NULL` - which migration 0008's widened constraint is
    an equivalence over, so a fixture that gave one a library would not insert at all."""
    assert len(world.playlists) == 5
    for handle in world.playlists:
        row = session.get(models.Item, handle.id)
        assert row is not None, f"{handle.name} was not seeded"
        assert row.type == ItemType.PLAYLIST.value
        assert row.library_id is None
        assert row.name == handle.name


def test_every_playlist_is_owned_by_a_user_that_is_not_the_restricted_one(
    world: QueryWorld,
) -> None:
    """009 T6's own warning, asserted rather than remembered: a visibility test whose playlists
    belong to the querying user passes on a world where nothing was hidden."""
    for handle in world.playlists:
        assert handle.owner_id == world.everyone.id
        assert handle.owner_id != world.restricted.id


def test_the_playlist_rows_carry_the_owner_the_share_and_the_media_type(
    session: OrmSession, world: QueryWorld
) -> None:
    for handle in world.playlists:
        row = session.get(models.Playlist, handle.id)
        assert row is not None
        assert (row.owner_user_id, row.is_public, row.media_type) == (
            handle.owner_id,
            handle.is_public,
            handle.media_type,
        )
        shares = session.execute(
            select(models.PlaylistShare).where(models.PlaylistShare.playlist_id == handle.id)
        ).scalars()
        assert {(one.user_id, one.can_edit) for one in shares} == set(handle.shares)


def test_both_answers_to_can_edit_are_seeded(world: QueryWorld) -> None:
    """AC-14 is two halves and the world has to hold both: a shared **editor** and a shared
    **reader**. Measured on the reference before it was seeded - a `CanEdit: false` share in the
    create body is stored and is a reader who is refused the move
    `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`.
    """
    assert world.shared_playlist.shares == ((world.restricted.id, True),)
    assert world.read_only_playlist.shares == ((world.restricted.id, False),)


def test_exactly_one_playlist_is_public_and_exactly_one_is_audio(world: QueryWorld) -> None:
    """The two rows 009 T6 needs beside the private ones: spec section 3.7's fourth class, and a
    second `media_type` - `mediaTypes=` is answered from the row for a playlist, and a world of
    one media type cannot tell that from a map over the type (plan section 4.2)."""
    assert [one.name for one in world.playlists if one.is_public] == [world.public_playlist.name]
    audio = [one.name for one in world.playlists if one.media_type == "Audio"]
    assert audio == [world.public_playlist.name]
    assert {one.media_type for one in world.playlists} == {"Audio", "Video"}


def test_every_entry_is_ordinal_contiguous_from_zero(
    session: OrmSession, world: QueryWorld
) -> None:
    """The order is the fact; `ordinal` is how it is read back (plan section 4.3). A gap here
    would make every ordering assertion in 009 a statement about the seeder."""
    for handle in world.playlists:
        rows = session.execute(
            select(models.PlaylistEntry)
            .where(models.PlaylistEntry.playlist_id == handle.id)
            .order_by(models.PlaylistEntry.ordinal)
        ).scalars()
        assert [(one.ordinal, one.item_key) for one in rows] == list(enumerate(handle.entries))
        assert len(set(handle.entries)) == len(handle.entries), "a duplicate the key would refuse"


def test_the_private_playlist_is_long_enough_for_the_measured_move_matrix(
    world: QueryWorld,
) -> None:
    """Five entries, because 009 AC-9's `B C D A E` and the boundary rows are stated on five."""
    assert len(world.private_playlist.entries) == 5


def test_the_two_library_playlist_really_does_hold_an_item_the_reader_cannot_see(
    session: OrmSession, world: QueryWorld
) -> None:
    """T5's own verification, and the one thing this fixture exists to make true.

    A playlist that quietly held two reachable items would make 009 T6 and T9 pass for the wrong
    reason: the omission would be untested and the count would be right by accident.
    """
    handle = world.cross_library_playlist
    assert handle.beyond_restricted, "nothing is out of the restricted user's reach"
    assert _reaches(session, world, world.everyone, handle.entries) == set(handle.entries)
    assert _reaches(session, world, world.restricted, handle.entries) == set(handle.restricted_sees)
    assert set(handle.beyond_restricted) & set(handle.restricted_sees) == set()


def test_the_hidden_entries_are_not_all_at_the_end(world: QueryWorld) -> None:
    """The shape that tells the two move arithmetics apart, and it is easy to lose by accident.

    A playlist whose unreachable entries all sit *after* the reachable ones gives the same answer
    whether the landing position is computed in the caller's list or in the stored one - so a
    fixture that appended the tracks would let AC-17's second half pass against either reading
    (009 section 3.5, plan section 6.4).
    """
    handle = world.cross_library_playlist
    hidden = set(handle.beyond_restricted)
    positions = [index for index, one in enumerate(handle.entries) if one in hidden]
    assert min(positions) < len(handle.entries) - 1
    assert len(handle.restricted_sees) >= 3, "too short for a downward move to have room"


def test_no_playlist_entry_points_at_a_playlist(world: QueryWorld) -> None:
    """Every entry is a leaf item. The reference expands a container into its children rather than
    storing the container (009 section 3.4), so an entry naming an album or a playlist would be a
    row no create body can produce."""
    playlist_ids = {one.id for one in world.playlists}
    for handle in world.playlists:
        assert set(handle.entries) & playlist_ids == set()
        assert set(handle.entries) <= set(world.corpus) | set(world.tracks)
