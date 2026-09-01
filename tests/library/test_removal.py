# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-11: a file that goes and comes back costs the user nothing.

This is the criterion the whole shape of feature 003 was built around. Identifiers are **derived**
rather than allocated, user data is keyed by that identity and carries **no foreign key** to the
items table, and removal is **soft** — three decisions in three different files, and this is where
they have to add up.

The scenario is ordinary rather than exotic: a re-download, a share that was slow to mount, a disk
swapped out and back. What makes it worth this much machinery is that the failure is silent. The
identifiers were derived, so nothing stored the old ones; a user whose favourites emptied would
have nothing to report but a feeling that the library looks wrong.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from atrium.compat.dates import utc_now
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import ItemRepository, LibraryRepository, PlaylistRepository
from atrium.domain.items import ItemType
from atrium.domain.library import Library
from atrium.domain.playlists import Playlist, Share
from atrium.domain.user import User
from atrium.library import config
from atrium.library.maintenance import DEFAULT_GRACE, purge_removed
from atrium.library.scan import scan
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture

FILM = "Amélie (2001).mkv"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def library(engine: Engine, fixture_library: BuiltFixture) -> Library:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        made = config.create(
            LibraryRepository(db), "Movies", "movies", (str(fixture_library.of("movies").root),)
        )
    with session_scope(factory) as db:
        scan(made, db, prober=not_media)
    return made


def rescan(engine: Engine, library: Library, **options: object):  # type: ignore[no-untyped-def]
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db, prober=not_media, **options)  # type: ignore[arg-type]


def film_id(engine: Engine, library: Library) -> str:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return next(
            item.id
            for item in ItemRepository(db).by_library(library.id).values()
            if item.type is ItemType.MOVIE and item.name == "Amélie"
        )


def favourite(engine: Engine, item_key: str) -> str:
    """A user, and something they did with that item.

    007 owns what these columns mean; 003 owes only that they survive.
    """
    user_id = "c" * 32
    factory = session_factory(engine)
    with session_scope(factory) as db:
        db.add(models.User(id=user_id, name="Joan", name_normalised="joan", password_hash=None))
        db.flush()
        db.add(
            models.ItemUserData(
                user_id=user_id,
                item_key=item_key,
                is_favorite=True,
                play_count=3,
                playback_position_ticks=12_345_670_000,
            )
        )
    return user_id


def user_data(engine: Engine, item_key: str) -> models.ItemUserData | None:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return db.execute(
            select(models.ItemUserData).where(models.ItemUserData.item_key == item_key)
        ).scalar_one_or_none()


# ------------------------------------------------------------------------------------------
# AC-11
# ------------------------------------------------------------------------------------------


def test_a_deleted_file_disappears_from_queries_and_its_user_data_survives(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """The first half of AC-11."""
    item_id = film_id(engine, library)
    favourite(engine, item_id)

    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    assert rescan(engine, library).removed == 1

    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert item_id not in ItemRepository(db).visible(library.id), "it still answers queries"
        assert item_id in ItemRepository(db).by_library(library.id), "its row was deleted"

    surviving = user_data(engine, item_id)
    assert surviving is not None, "the user's favourites went with the file"
    assert (surviving.is_favorite, surviving.play_count) == (True, 3)


def test_restoring_the_file_revives_the_item_with_the_same_identifier(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """The second half of AC-11, and the reason identifiers are derived rather than allocated.

    Nothing reconnects the user's data to the item, because the two were never disconnected: the
    path derives the same identifier it did before, and the user data was keyed to that.
    """
    item_id = film_id(engine, library)
    favourite(engine, item_id)
    path = Path(fixture_library.of("movies").path_of(FILM))
    contents = path.read_bytes()

    path.unlink()
    rescan(engine, library)
    path.write_bytes(contents)
    report = rescan(engine, library)

    assert report.revived == 1
    assert report.added == 0, "the film came back as a NEW item, so every client's state is lost"
    assert film_id(engine, library) == item_id

    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert item_id in ItemRepository(db).visible(library.id)
    surviving = user_data(engine, item_id)
    assert surviving is not None
    assert surviving.playback_position_ticks == 12_345_670_000, "the resume position moved"


def test_a_file_that_never_left_is_not_revived(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """The control: revival is a transition, not something every rescan reports."""
    assert rescan(engine, library).revived == 0


def test_an_already_removed_item_is_not_removed_again(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """Otherwise the threshold guard fires on every scan after a large removal, forever, with
    nothing left to protect."""
    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    assert rescan(engine, library).removed == 1
    second = rescan(engine, library)
    assert (second.removed, second.missing) == (0, 0)


# ------------------------------------------------------------------------------------------
# Purging: an operator's decision, never a scan's
# ------------------------------------------------------------------------------------------


def test_a_scan_never_purges(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """However many times it runs. The row is what a returning file comes back to."""
    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    item_id = film_id(engine, library)
    for _ in range(3):
        rescan(engine, library)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert item_id in ItemRepository(db).by_library(library.id)


def test_purging_leaves_a_removed_item_inside_its_grace_period(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """The failure this protects against is an operator tidying up on the same afternoon a share
    was slow to mount."""
    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    rescan(engine, library)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        report = purge_removed(library, db)
    assert (report.purged, report.kept) == (0, 1)


def test_purging_after_the_grace_period_removes_the_row(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    rescan(engine, library)
    item_id = film_id(engine, library)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        report = purge_removed(library, db, now=utc_now() + DEFAULT_GRACE + timedelta(days=1))
    assert report.purged == 1

    with session_scope(factory) as db:
        assert item_id not in ItemRepository(db).by_library(library.id)


def test_purging_does_not_delete_the_users_data(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """The point of the missing foreign key, at the one moment a row really is deleted.

    Purging removes the thing a user pointed at, not what they did with it — so if that file ever
    returns, the association returns with it. That is what makes purging safe enough to exist.
    """
    item_id = film_id(engine, library)
    favourite(engine, item_id)
    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    rescan(engine, library)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        purge_removed(library, db, grace=timedelta(0))

    surviving = user_data(engine, item_id)
    assert surviving is not None, "purging an item deleted a user's history"
    assert surviving.is_favorite is True


def test_a_purged_item_whose_file_returns_finds_its_history_again(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """The strongest form of "user data outlives items": it outlives the row itself."""
    item_id = film_id(engine, library)
    favourite(engine, item_id)
    path = Path(fixture_library.of("movies").path_of(FILM))
    contents = path.read_bytes()

    path.unlink()
    rescan(engine, library)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        purge_removed(library, db, grace=timedelta(0))

    path.write_bytes(contents)
    report = rescan(engine, library)

    assert report.added == 1, "the row was purged, so this is a fresh insert"
    assert film_id(engine, library) == item_id, "and it derived the same identifier it had before"
    surviving = user_data(engine, item_id)
    assert surviving is not None
    assert surviving.play_count == 3


def test_purging_only_touches_the_library_it_was_asked_about(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        other = config.create(
            LibraryRepository(db), "Music", "music", (str(fixture_library.of("music").root),)
        )
    with session_scope(factory) as db:
        scan(other, db, prober=not_media)
    with session_scope(factory) as db:
        before = len(ItemRepository(db).by_library(other.id))

    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    rescan(engine, library)
    with session_scope(factory) as db:
        purge_removed(library, db, grace=timedelta(0))

    with session_scope(factory) as db:
        assert len(ItemRepository(db).by_library(other.id)) == before


# ------------------------------------------------------------------------------------------
# 009 AC-20: playlist state survives a full library rescan
# ------------------------------------------------------------------------------------------
#
# 009's criterion, asserted here because this is the only file in the repository that runs a
# **real** scan over a real library. It sits beside 003's AC-11 for the reason that criterion
# exists: a playlist is the one item a rescan cannot rebuild (009 spec section 4), so where a film
# that goes and comes back costs a user their favourites, a playlist that goes costs them the list
# itself and nothing regenerates it.
#
# What makes it a test rather than a reading is the mechanism it depends on. The scan's removal
# pass walks `by_library(library.id)` and skips anything that is not file-backed; a playlist has
# `library_id IS NULL` and is not file-backed, so **two** independent clauses have to hold for it
# to survive, and neither is stated anywhere a scan change would be read.


PLAYLIST = "7c" * 16


def a_playlist(engine: Engine, owner: str, item_keys: list[str]) -> None:
    """One playlist, through the door that writes them, with a share and the public flag set.

    Everything a playlist owns is written here - the item row, the playlist row, its shares and
    its entries - because AC-20 says *playlist state*, and a test that seeded only the entries
    would pass over a scan that dropped the shares.
    """
    factory = session_factory(engine)
    with session_scope(factory) as db:
        PlaylistRepository(db, ItemQueryRepository(db)).create(
            Playlist(
                id=PLAYLIST,
                name="Survives a rescan",
                owner_user_id=owner,
                is_public=True,
                media_type="Video",
                shares=(Share(user_id=owner, can_edit=True),),
            ),
            item_keys,
        )


def movie_ids(engine: Engine, library: Library) -> list[str]:
    """Every film the scan produced, in a stable order.

    A playlist needs two entries before "the entry kept its place" is a claim about anything.
    """
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return sorted(
            item.id
            for item in ItemRepository(db).by_library(library.id).values()
            if item.type is ItemType.MOVIE
        )


def playlist_state(
    engine: Engine, reader: User
) -> tuple[str, bool, list[tuple[str, bool]], list[str]]:
    """Name, public flag, shares and the entries this reader is given, in order."""
    factory = session_factory(engine)
    with session_scope(factory) as db:
        repository = PlaylistRepository(db, ItemQueryRepository(db))
        stored = repository.by_id(PLAYLIST, reader)
        assert stored is not None, "the playlist row itself went"
        return (
            stored.name,
            stored.is_public,
            [(one.user_id, one.can_edit) for one in stored.shares],
            repository.entries(PLAYLIST, reader),
        )


@pytest.fixture
def reader(engine: Engine) -> User:
    """A user with no library restrictions, so `entries` is filtered by removal and nothing else."""
    user_id = "e" * 32
    factory = session_factory(engine)
    with session_scope(factory) as db:
        db.add(models.User(id=user_id, name="Owner", name_normalised="owner", password_hash=None))
    return User(id=user_id, name="Owner")


def test_ac20_a_playlist_and_its_entries_survive_a_rescan_that_changes_nothing(
    engine: Engine, library: Library, reader: User
) -> None:
    """AC-20's plain reading, and the one a scan change is most likely to break.

    The removal pass is scoped to the library it was asked about and skips rows that are not
    file-backed. A playlist satisfies neither test, so a pass that lost either clause would
    soft-delete every playlist on the server on the next scan of any library - and the row would
    still be there, which is what makes the failure quiet.
    """
    film = film_id(engine, library)
    a_playlist(engine, reader.id, [film])
    before = playlist_state(engine, reader)

    for _ in range(3):
        report = rescan(engine, library)
        assert report.removed == 0

    assert playlist_state(engine, reader) == before
    assert before[3] == [film], "the fixture holds nothing, so nothing below proves anything"


def test_ac20_an_entry_whose_file_goes_and_returns_keeps_its_place(
    engine: Engine, library: Library, fixture_library: BuiltFixture, reader: User
) -> None:
    """The harder half, and 003's AC-11 seen from a playlist.

    A file that goes is soft-deleted, so the entry stops being served (009 T7) and its row stays.
    When the file returns it derives the same identifier it had before, so the entry comes back
    **at its original position** rather than at the end - which is the whole reason the ordinal is
    stored against the item key rather than the entry being re-appended.
    """
    film = film_id(engine, library)
    other = next(one for one in movie_ids(engine, library) if one != film)
    a_playlist(engine, reader.id, [other, film])

    path = Path(fixture_library.of("movies").path_of(FILM))
    contents = path.read_bytes()
    path.unlink()
    assert rescan(engine, library).removed == 1
    assert playlist_state(engine, reader)[3] == [other], "a removed item is not served as an entry"

    path.write_bytes(contents)
    assert rescan(engine, library).revived == 1
    assert playlist_state(engine, reader)[3] == [other, film], "the entry came back at the end"


def test_ac20_a_purge_does_not_take_the_playlist_row_with_it(
    engine: Engine, library: Library, fixture_library: BuiltFixture, reader: User
) -> None:
    """The one moment an item row really is deleted, and a playlist entry points at one.

    `playlist_entries.item_key` deliberately carries **no** foreign key (009 plan section 4.3), for
    the reason 007's user data does not: the identifier outlives the row. A purge that cascaded
    here would delete the entry and leave a playlist that is shorter than it was, permanently.
    """
    film = film_id(engine, library)
    a_playlist(engine, reader.id, [film])

    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    rescan(engine, library)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        purge_removed(library, db, grace=timedelta(0))

    name, is_public, shares, served = playlist_state(engine, reader)
    assert (name, is_public, shares) == ("Survives a rescan", True, [(reader.id, True)])
    assert served == [], "the item is gone, so the entry is not served"

    with session_scope(factory) as db:
        stored = db.execute(
            select(models.PlaylistEntry.item_key)
            .where(models.PlaylistEntry.playlist_id == PLAYLIST)
            .order_by(models.PlaylistEntry.ordinal)
        ).scalars()
        assert list(stored) == [film], "the purge cascaded into the playlist's entries"
