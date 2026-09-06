# SPDX-License-Identifier: GPL-3.0-or-later
"""Where an item's creation date comes from, which is two different places.

**Untested until 2026-09-06, and that is why it was wrong.** `library/scan.py` stamped every item
of a library with one `utc_now()`, so a library's items were all created at the same instant and no
date ordering among them was total - and nothing in this suite said otherwise, because nothing here
asserted the column at all. What the reference does was measured rather than reasoned
`[probe: tools/probe_date_created.py, Jellyfin 10.11.11, 2026-09-06]`, and it is a split:

* a `Movie`, an `Episode` and an `Audio` carry **their file's modification time**, exactly;
* every container carries **the moment the scan made the row**, and not its directory's time.

Both halves are asserted below, and so is the half that decides the implementation's shape: the
date follows the file rather than recording a first sighting, so a rescan writes the column again.

See 003 spec section 3.9 and AC-24, and behaviours section 2.29.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import Item, ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library import scan as scan_module
from atrium.library.report import ScanReport
from atrium.library.scan import scan
from tests.conftest import data_dir, not_media
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


def scanned(engine: Engine, library: Library, **options: object) -> ScanReport:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db, prober=not_media, **options)  # type: ignore[arg-type]


def items_of(engine: Engine, library: Library) -> dict[str, Item]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return ItemRepository(db).by_library(library.id)


def named(stored: dict[str, Item], name: str, kind: ItemType) -> Item:
    """One item by name and type, and a failure that says what was there instead."""
    found = [item for item in stored.values() if item.name == name and item.type is kind]
    assert len(found) == 1, f"{name!r} as {kind}: found {[one.name for one in found]}"
    return found[0]


def stamp(path: Path, when: str) -> datetime:
    """Give a path a modification time and hand back what it now says."""
    moment = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    nanoseconds = int(moment.timestamp()) * 1_000_000_000
    os.utime(path, ns=(nanoseconds, nanoseconds))
    return moment


# ------------------------------------------------------------------------------------------
# The split: a file's own time, and the scan's
# ------------------------------------------------------------------------------------------


def test_a_file_backed_item_carries_its_files_modification_time(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The half that was wrong. Not "when the scan saw it": what the file says."""
    root = fixture_library.of("movies").root
    when = stamp(root / "2 Fast 2 Furious (2003).mkv", "2019-05-06T07:08:09Z")

    library = a_library(engine, fixture_library, "movies")
    before_the_scan = datetime.now(UTC)
    scanned(engine, library)

    film = named(items_of(engine, library), "2 Fast 2 Furious", ItemType.MOVIE)
    assert film.date_created == when
    assert film.date_created < before_the_scan, "it is the file's time and not the scan's"


def test_a_container_carries_the_scans_moment_and_not_its_directorys(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The other half, and it was measured because it is not the obvious one.

    A directory has a modification time too, and the reference does not use it: a season directory
    stamped four years into the past came back carrying the instant of the scan.
    """
    root = fixture_library.of("tvshows").root
    directory = stamp(root / "The Daily Show" / "Season 2024", "2022-08-09T10:11:12Z")

    library = a_library(engine, fixture_library, "tvshows")
    before_the_scan = datetime.now(UTC)
    scanned(engine, library)

    season = named(items_of(engine, library), "Season 2024", ItemType.SEASON)
    assert season.date_created is not None
    assert season.date_created >= before_the_scan
    assert season.date_created != directory


def test_a_two_part_item_takes_the_time_of_the_part_its_path_names(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """Measured by giving the two parts different times: the item follows part one.

    That is the file `Item.path` reports, so this is the same choice the rest of the project makes
    about which of an item's sources speaks for it.
    """
    parts = fixture_library.of("movies").root / "The Long Film (1998)"
    first = stamp(parts / "The Long Film (1998) - part1.mkv", "2013-01-01T01:01:01Z")
    second = stamp(parts / "The Long Film (1998) - part2.mkv", "2015-02-02T02:02:02Z")

    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)

    film = named(items_of(engine, library), "The Long Film", ItemType.MOVIE)
    assert len(film.sources) == 2, "the fixture's two-part film is one item with two sources"
    assert film.date_created == first
    assert film.date_created != second


# ------------------------------------------------------------------------------------------
# It stays in step with the file
# ------------------------------------------------------------------------------------------


def test_a_modification_time_that_moves_moves_the_creation_date(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """Measured on the reference: move the file's time and the next scan moves the item's.

    So the column is not a first sighting, and cannot be written only when the row is added.
    """
    film = fixture_library.of("movies").root / "Wall-E (2008).mkv"
    stamp(film, "2020-06-07T08:09:10Z")
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)

    moved = stamp(film, "2017-03-02T01:02:03Z")
    report = scanned(engine, library)

    assert report.updated >= 1
    assert named(items_of(engine, library), "Wall-E", ItemType.MOVIE).date_created == moved


def test_a_rescan_of_an_unchanged_library_still_writes_nothing(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The guard on the test above. A date read from the file every time must not look like a
    change every time - which is what a column derived from `utc_now()` on the update path would
    do, and what would turn every rescan into a full rewrite."""
    library = a_library(engine, fixture_library, "movies")
    first = scanned(engine, library)
    second = scanned(engine, library)

    assert (second.added, second.updated) == (0, 0)
    assert second.unchanged == first.added


def test_a_date_left_by_an_older_scan_is_corrected_without_a_metadata_refresh(
    engine: Engine, fixture_library: BuiltFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An installation scanned before 2026-09-06 holds the scan's clock in this column.

    The first rescan after the change corrects it - there is no migration, because the value is
    derived from a file that is still there. And it corrects it **without** handing the item to
    004's refresh: a creation date that has moved is no reason to open a file and read its tags,
    which is why `library/scan.py` checks the date beside `_differs` rather than inside it.
    """
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    stored = items_of(engine, library)
    film = named(stored, "2 Fast 2 Furious", ItemType.MOVIE)

    # The shape the old scanner left: every item of the library at one instant of its own.
    scanners_clock = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        from atrium.db import models

        for row in db.query(models.Item).filter(models.Item.library_id == library.id):
            row.date_created = scanners_clock

    handed_to_the_refresh: list[list[str]] = []
    original = scan_module.pending_and_touched

    def capture(session: object, one: Library, touched: list[str]) -> object:
        handed_to_the_refresh.append(list(touched))
        return original(session, one, touched)  # type: ignore[arg-type]

    monkeypatch.setattr(scan_module, "pending_and_touched", capture)
    report = scanned(engine, library)

    corrected = named(items_of(engine, library), "2 Fast 2 Furious", ItemType.MOVIE)
    assert corrected.date_created != scanners_clock
    assert corrected.date_created == film.date_created
    assert report.updated >= 1
    assert handed_to_the_refresh == [[]], "a corrected date is not a reason to re-read the file"
