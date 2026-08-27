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
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.maintenance import DEFAULT_GRACE, purge_removed
from atrium.library.scan import scan
from tests.conftest import data_dir
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
        scan(made, db)
    return made


def rescan(engine: Engine, library: Library, **options: object):  # type: ignore[no-untyped-def]
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db, **options)  # type: ignore[arg-type]


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
        scan(other, db)
    with session_scope(factory) as db:
        before = len(ItemRepository(db).by_library(other.id))

    Path(fixture_library.of("movies").path_of(FILM)).unlink()
    rescan(engine, library)
    with session_scope(factory) as db:
        purge_removed(library, db, grace=timedelta(0))

    with session_scope(factory) as db:
        assert len(ItemRepository(db).by_library(other.id)) == before
