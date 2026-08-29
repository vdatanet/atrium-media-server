# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-10: a library that moves costs nothing.

Scan a library at one path, move the whole tree somewhere else, reconfigure the root, rescan —
**every identifier is unchanged and no user data is orphaned**. This is the test that proves the
relative-path decision of [plan §1](../../specs/003-library-configuration-and-scanning/plan.md),
and it is the difference between a remount costing nothing and costing every client's favourites.

**The reference does not have this property, and that is measured rather than assumed.** Its item
identifier is reproducible from the file's absolute path alone: across 406 live items, and 447 of
447 whose path contains an uppercase character, `Guid(MD5(UTF16LE(type.FullName + path)))`
reproduces the `Id` the server returned, verbatim on a server with
`EnableCaseSensitiveItemIds` set. `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]` So
moving `/media/movies` to `/mnt/movies` there changes **every** identifier under it, and every
client's favourites and resume positions for everything in that library are silently discarded.
behaviours §1.4.

Atrium derives from the path *relative to its library root*, so the same move changes nothing.
`test_the_identifiers_would_have_moved_under_an_absolute_derivation` is the control that keeps the
rest of this file from being a tautology: it shows the two locations genuinely differ, so
"unchanged" is a result rather than an observation that nothing was asked.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from atrium.compat.guids import derive
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import Item, ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.report import ScanReport
from atrium.library.scan import scan
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture

USER = "c" * 32


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


def a_library(engine: Engine, roots: tuple[str, ...], collection_type: str) -> Library:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return config.create(LibraryRepository(db), collection_type.title(), collection_type, roots)


def scanned(engine: Engine, library: Library) -> ScanReport:
    """Deliberately no `roots=` argument: the roots come from the **configuration**, which is what
    an operator edits and therefore what AC-10 is about."""
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db, prober=not_media)


def items_of(engine: Engine, library: Library) -> dict[str, Item]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return ItemRepository(db).by_library(library.id)


def reconfigured(engine: Engine, library: Library, roots: tuple[str, ...]) -> Library:
    """The operator's edit, through the module that owns which edits are allowed."""
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return config.update(LibraryRepository(db), library.id, roots=roots)


def moved(source: Path, destination: Path) -> Path:
    """Rename the whole tree, which is what a remount looks like from the scanner's side."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)
    return destination


# ------------------------------------------------------------------------------------------
# AC-10
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_moving_a_root_changes_no_identifier(
    engine: Engine, tmp_path: Path, fixture_library: BuiltFixture, collection_type: str
) -> None:
    """All three collection types, because two of them derive containers from names and one does
    not, and a rule that held only for films would be a rule nobody had tested."""
    built = fixture_library.of(collection_type)
    library = a_library(engine, (str(built.root),), collection_type)
    scanned(engine, library)
    before = items_of(engine, library)
    assert before, "nothing was scanned, so this would pass against any derivation at all"

    destination = moved(built.root, tmp_path / "another-mount" / built.root.name)
    library = reconfigured(engine, library, (str(destination),))
    scanned(engine, library)

    after = items_of(engine, library)
    assert set(after) == set(before)
    assert {one.id: one.name for one in after.values()} == {
        one.id: one.name for one in before.values()
    }
    assert {one.id: one.parent_id for one in after.values()} == {
        one.id: one.parent_id for one in before.values()
    }
    assert {one.id: one.sort_name for one in after.values()} == {
        one.id: one.sort_name for one in before.values()
    }


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_the_move_is_invisible_to_the_scan(
    engine: Engine, tmp_path: Path, fixture_library: BuiltFixture, collection_type: str
) -> None:
    """Not merely "the identifiers survived": the rescan has **nothing to do at all**.

    A move that produced the right identifiers by adding every item again and removing every old
    one would satisfy the assertion above and would still have discarded a user's state, because
    the removal is what user data is keyed against surviving. So the report is asserted whole.

    `examined == 0` is the T18 half: renaming a directory does not touch the files' modification
    times, so a remount re-reads nothing either.
    """
    built = fixture_library.of(collection_type)
    library = a_library(engine, (str(built.root),), collection_type)
    first = scanned(engine, library)

    destination = moved(built.root, tmp_path / "another-mount" / built.root.name)
    library = reconfigured(engine, library, (str(destination),))
    report = scanned(engine, library)

    assert (report.added, report.updated, report.removed, report.revived) == (0, 0, 0, 0)
    assert report.missing == 0, "the old paths looked deleted, which is the destructive reading"
    assert report.unchanged == first.added
    assert report.examined == 0


def test_no_user_data_is_orphaned_by_the_move(
    engine: Engine, tmp_path: Path, fixture_library: BuiltFixture
) -> None:
    """The half AC-10 exists for. A row keyed to an identifier that no longer resolves is not an
    error anywhere - it is simply a favourite that has stopped appearing.

    Both a file-backed item and a container, because they are derived by different rules: a
    `Series` comes from its name and an `Episode` from its relative path, and only one of the two
    would break under an absolute derivation. A test that favourited only the series would pass
    against the bug.
    """
    built = fixture_library.of("tvshows")
    library = a_library(engine, (str(built.root),), "tvshows")
    scanned(engine, library)

    before = items_of(engine, library)
    episode = next(one for one in before.values() if one.type is ItemType.EPISODE)
    series = next(one for one in before.values() if one.type is ItemType.SERIES)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        db.add(models.User(id=USER, name="Joan", name_normalised="joan", password_hash=None))
        db.flush()
        for item in (episode, series):
            db.add(
                models.ItemUserData(
                    user_id=USER,
                    item_key=item.id,
                    is_favorite=True,
                    play_count=3,
                    playback_position_ticks=12_345_670_000,
                )
            )

    destination = moved(built.root, tmp_path / "another-mount" / built.root.name)
    library = reconfigured(engine, library, (str(destination),))
    scanned(engine, library)

    with session_scope(factory) as db:
        visible = ItemRepository(db).visible(library.id)
        rows = list(db.execute(select(models.ItemUserData)).scalars())
        keys = {row.item_key for row in rows}

    assert keys == {episode.id, series.id}, "the rows themselves were disturbed"
    orphaned = keys - set(visible)
    assert not orphaned, f"{len(orphaned)} favourite(s) point at nothing after the move"
    assert all(row.play_count == 3 for row in rows)
    assert all(row.playback_position_ticks == 12_345_670_000 for row in rows)


def test_moving_one_root_of_two_changes_no_identifier(
    engine: Engine, tmp_path: Path, fixture_library: BuiltFixture
) -> None:
    """The realistic shape of a remount: one share moves and the others do not.

    Identity is relative to *a* root rather than to the library, so a library with two roots has
    two independent relative namespaces and moving one must not disturb the other. A derivation
    that happened to be relative to the first configured root would pass every test above and fail
    this one.
    """
    first_root = fixture_library.of("movies").root
    second_root = fixture_library.of("tvshows").root
    library = a_library(engine, (str(first_root), str(second_root)), "movies")
    scanned(engine, library)
    before = items_of(engine, library)

    destination = moved(second_root, tmp_path / "another-mount" / second_root.name)
    library = reconfigured(engine, library, (str(first_root), str(destination)))
    report = scanned(engine, library)

    assert set(items_of(engine, library)) == set(before)
    assert (report.added, report.removed, report.missing) == (0, 0, 0)


# ------------------------------------------------------------------------------------------
# The controls: why the assertions above are results rather than tautologies
# ------------------------------------------------------------------------------------------


def test_the_identifiers_would_have_moved_under_an_absolute_derivation(
    engine: Engine, tmp_path: Path, fixture_library: BuiltFixture
) -> None:
    """The reference's rule, modelled with Atrium's own hash, over the two locations.

    Nothing of the reference's algorithm is reproduced here - only its **key**, which is the
    absolute path. The point is that the key differs between the two locations, so an identifier
    derived from it differs too, for every file. That is what the tests above are asserting Atrium
    does not do.
    """
    built = fixture_library.of("movies")
    library = a_library(engine, (str(built.root),), "movies")
    scanned(engine, library)
    stored = [one for one in items_of(engine, library).values() if one.is_file_backed]
    assert stored

    destination = tmp_path / "another-mount" / built.root.name
    here = {
        derive(ItemType.MOVIE.value, str(built.root / str(one.relative_path))) for one in stored
    }
    there = {
        derive(ItemType.MOVIE.value, str(destination / str(one.relative_path))) for one in stored
    }

    assert len(here) == len(stored)
    assert not (here & there), (
        "the two locations derive the same identifiers, so this proves nothing"
    )


def test_nothing_absolute_reaches_the_database(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The structural reason the move is free, asserted where it would actually be broken.

    A scanner can derive from a relative path and still *store* an absolute one, and everything
    above would pass until somebody used the stored path to rebuild identity. Every stored path is
    relative, POSIX-separated, and contains no part of the root.
    """
    built = fixture_library.of("music")
    library = a_library(engine, (str(built.root),), "music")
    scanned(engine, library)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        paths = list(db.execute(select(models.ItemSource.relative_path)).scalars())

    assert paths
    for one in paths:
        assert not one.startswith("/"), one
        assert "\\" not in one, one
        # The invariant itself, not a string property of it: the absolute path is **reconstructed**
        # from the root, so joining the two has to land on the file. A stored path that embedded
        # the root would satisfy any amount of "does not start with a separator" and fail here.
        assert (built.root / one).is_file(), one
