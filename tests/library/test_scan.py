# SPDX-License-Identifier: GPL-3.0-or-later
"""The first scan that writes, and the fact that it cannot unwrite.

AC-1, AC-2, AC-3 and AC-13 live here — the first three because they are about what reaches the
database and stays there, and AC-13 because a sort-name table proves the derivations are right
while proving nothing about whether the **scanner uses them**. Those are different claims, and the
gap between them is where every album in a library ends up in the wrong order.

**The tests that matter most assert an absence.** `library/scan.py` has no removal code path and
`ItemRepository` has no removal method, so a file that disappears leaves its item exactly where it
was. That is not the final behaviour — spec section 3.8 wants it soft-deleted with its user data
kept — it is the behaviour of a scanner that has not been given the ability yet, and T17 grants it
only after T16's guards are green.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, event, func, select

from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import CollectionType, ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.scan import scan
from tests.conftest import data_dir
from tests.fixtures.library import BuiltFixture


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


def a_library(engine: Engine, fixture_library: BuiltFixture, collection_type: str) -> Library:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return config.create(
            LibraryRepository(db),
            collection_type.title(),
            collection_type,
            (str(fixture_library.of(collection_type).root),),
        )


def scanned(engine: Engine, library: Library):  # type: ignore[no-untyped-def]
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db)


def items_of(engine: Engine, library: Library) -> dict[str, object]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return ItemRepository(db).by_library(library.id)


# ------------------------------------------------------------------------------------------
# AC-1: the fixture scans to the expected items
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_a_library_scans_to_items(
    engine: Engine, fixture_library: BuiltFixture, collection_type: str
) -> None:
    library = a_library(engine, fixture_library, collection_type)
    report = scanned(engine, library)

    assert report.added > 0
    assert report.removed == 0, "this scanner has no removal code path at all"
    stored = items_of(engine, library)
    assert len(stored) == report.added
    assert any(item.type is ItemType.COLLECTION_FOLDER for item in stored.values())  # type: ignore[union-attr]


def test_the_skipped_files_are_reported_with_their_reasons(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """Plan section 7: skipped, counted, and reported - never silently dropped."""
    report = scanned(engine, a_library(engine, fixture_library, "movies"))
    assert report.skipped
    assert "not a media extension for this collection type" in report.reasons()


# ------------------------------------------------------------------------------------------
# AC-2 and AC-3: the identifiers do not move
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_scanning_twice_changes_nothing(
    engine: Engine, fixture_library: BuiltFixture, collection_type: str
) -> None:
    """AC-2. The second scan reports no change at all, not merely the same identifiers."""
    library = a_library(engine, fixture_library, collection_type)
    first = scanned(engine, library)
    before = set(items_of(engine, library))

    second = scanned(engine, library)
    assert (second.added, second.updated) == (0, 0)
    assert second.unchanged == first.added
    assert set(items_of(engine, library)) == before


def test_scanning_into_an_empty_database_gives_the_same_identifiers(
    tmp_path: Path, fixture_library: BuiltFixture
) -> None:
    """AC-3. A restore, or a rebuilt database: the identifiers a client cached still resolve.

    The library keeps its own identity across the two databases, which is the thing being tested -
    identity is derived from it and from the relative path, and from nothing else.
    """
    identifiers = []
    for run in ("first", "second"):
        paths = data_dir(tmp_path / run)
        engine = create_database_engine(paths)
        try:
            schema.ensure_current(engine, paths)
            factory = session_factory(engine)
            with session_scope(factory) as db:
                library = LibraryRepository(db).add(
                    Library(
                        id="b" * 32,
                        name="Movies",
                        collection_type=CollectionType.MOVIES,
                        roots=(str(fixture_library.of("movies").root),),
                    )
                )
            with session_scope(factory) as db:
                scan(library, db)
            identifiers.append(set(items_of(engine, library)))
        finally:
            engine.dispose()

    assert identifiers[0] == identifiers[1]
    assert identifiers[0]


def test_moving_the_root_changes_no_identifier(
    engine: Engine, tmp_path: Path, fixture_library: BuiltFixture
) -> None:
    """AC-10 through a real scan, which is what T19 will assert end to end.

    The reference derives from the absolute path and would lose every identifier here.
    """
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    before = set(items_of(engine, library))

    moved = tmp_path / "somewhere-else"
    Path(fixture_library.of("movies").root).rename(moved)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        scan(library, db, roots=[moved])

    assert set(items_of(engine, library)) == before


# ------------------------------------------------------------------------------------------
# AC-13: the scanner uses the dispatcher, which the sort-name table cannot show
# ------------------------------------------------------------------------------------------


def test_a_scanned_episode_and_season_carry_the_override_sort_names(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """AC-13, read back from the database rather than from a function.

    T4 proved the two derivations are right. This proves the **scanner uses them** - a different
    claim, and the one plan section 9 rates most likely to break, because a green sort-name table
    beside a library ordered by the wrong rule looks exactly like success.
    """
    library = a_library(engine, fixture_library, "tvshows")
    scanned(engine, library)
    stored = items_of(engine, library)

    pilot = next(i for i in stored.values() if i.name == "Pilot")  # type: ignore[union-attr]
    assert pilot.sort_name == "001 - 0001 - Pilot", "an Episode was sorted by the base rule"

    specials = next(
        i
        for i in stored.values()
        if i.type is ItemType.SEASON and i.index_number == 0  # type: ignore[union-attr]
    )
    assert specials.sort_name == "0000"


def test_a_scanned_track_keeps_its_raw_name_in_its_sort_name(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """`The Song` sorts under T, not under s. Applying the base rule reorders every album."""
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library)
    for track in items_of(engine, library).values():
        if track.type is not ItemType.AUDIO or track.index_number is None:  # type: ignore[union-attr]
            continue
        assert track.sort_name.endswith(track.name)  # type: ignore[union-attr]


def test_a_scanned_film_carries_the_base_sort_name(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The other half of AC-13, artefacts included: nothing collapses the double space."""
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    sorted_names = {i.name: i.sort_name for i in items_of(engine, library).values()}  # type: ignore[union-attr]
    assert sorted_names["The Matrix"] == "matrix"
    assert sorted_names["Rock & Roll"] == "rock  roll"


# ------------------------------------------------------------------------------------------
# What this scanner cannot do
# ------------------------------------------------------------------------------------------


def test_a_deleted_file_leaves_its_item_exactly_where_it_was(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """Not the final behaviour, and deliberately so.

    Spec section 3.8 wants a missing file soft-deleted with its user data kept, and T17 implements
    that - **after** T16's guards are green. Until then the capability does not exist, so a scan
    over a library that lost a file changes nothing at all.
    """
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    before = set(items_of(engine, library))

    Path(fixture_library.of("movies").path_of("Amélie (2001).mkv")).unlink()
    report = scanned(engine, library)

    assert set(items_of(engine, library)) == before, "an item was removed by a scanner that cannot"
    assert report.removed == 0


def test_a_root_that_lost_everything_still_removes_nothing(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The catastrophic case, and the reason for the whole ordering. An unmounted share and an
    emptied directory look identical, and this scanner cannot act on either.
    """
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    before = set(items_of(engine, library))

    for path in sorted(Path(fixture_library.of("movies").root).rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()

    report = scanned(engine, library)
    assert set(items_of(engine, library)) == before
    assert (report.added, report.updated, report.removed) == (0, 0, 0)


def test_the_repository_has_no_way_to_remove_an_item() -> None:
    """The enforcement, asserted by shape rather than by discipline.

    A scan that merely *chooses* not to delete is one refactor away from deleting. A repository
    with no method for it is not.
    """
    surface = {name for name in vars(ItemRepository) if not name.startswith("_")}
    assert surface == {"by_library", "add", "update"}


def test_update_cannot_reach_removed_at(engine: Engine, fixture_library: BuiltFixture) -> None:
    """Clearing `removed_at` is a revival and setting it is a removal; both are T17's.

    Asserted through behaviour rather than by reading the source, which the first version of this
    test did - and which failed against the docstring explaining why the field is absent.
    """
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    factory = session_factory(engine)
    marked = datetime(2026, 8, 27, tzinfo=UTC)

    with session_scope(factory) as db:
        row = db.execute(select(models.Item).limit(1)).scalar_one()
        item_id = row.id
        row.removed_at = marked

    with session_scope(factory) as db:
        stored = ItemRepository(db).by_library(library.id)[item_id]
        assert stored.removed_at == marked
        ItemRepository(db).update(replace(stored, name="Renamed", removed_at=None))

    with session_scope(factory) as db:
        after = ItemRepository(db).by_library(library.id)[item_id]
        assert after.name == "Renamed", "the update did not happen, so this proves nothing"
        assert after.removed_at == marked, "update revived an item, which is T17's to grant"


# ------------------------------------------------------------------------------------------
# One transaction per library
# ------------------------------------------------------------------------------------------


def test_a_large_tree_is_written_in_one_transaction(engine: Engine, tmp_path: Path) -> None:
    """Plan section 6.7. SQLite has one writer, so a commit per item makes a first scan of a real
    library take orders of magnitude longer than the walk that found it.

    The count is asserted rather than the clock: a timing threshold either flakes on a busy runner
    or is so generous it catches nothing, while "how many transactions" is the actual decision.
    """
    root = tmp_path / "large"
    for n in range(1500):
        directory = root / f"Film {n:04d} ({1900 + n % 120})"
        directory.mkdir(parents=True)
        (directory / f"Film {n:04d} ({1900 + n % 120}).mkv").write_bytes(b"x" * 16)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        library = config.create(LibraryRepository(db), "Large", "movies", (str(root),))

    commits = 0

    @event.listens_for(engine, "commit")
    def _count(_connection: object) -> None:
        nonlocal commits
        commits += 1

    started = time.monotonic()
    with session_scope(factory) as db:
        report = scan(library, db)
    elapsed = time.monotonic() - started
    event.remove(engine, "commit", _count)

    assert report.added == 1501, "1500 films and the library's own CollectionFolder"
    assert commits == 1, f"{report.added} items were written in {commits} transactions"
    assert elapsed < 60, f"a 1,500-film scan took {elapsed:.1f}s"


def test_the_rows_reach_the_database(engine: Engine, fixture_library: BuiltFixture) -> None:
    """The repository is not the only thing that has to be right; the rows have to be there."""
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert db.execute(select(func.count()).select_from(models.Item)).scalar_one() > 0
        assert db.execute(select(func.count()).select_from(models.ItemSource)).scalar_one() > 0
