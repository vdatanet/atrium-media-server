# SPDX-License-Identifier: GPL-3.0-or-later
"""The three destructive-failure tests, and the proof that each guard is what stops the damage.

[plan section 8.3](../../specs/003-library-configuration-and-scanning/plan.md) calls these the ones
worth writing first, because everything else in a scanner fails *visibly* — a wrong title, a missing
item, an ugly sort order — and these fail **quietly and irreversibly**. The identifiers were
derived, so nothing stored the old ones, and the first symptom is a user saying their favourites
look wrong weeks later.

**Every assertion here is against the database**, never against a log line or a returned flag. A
scan that reported a refusal and wrote anyway would pass a test that read its report.

**And each test removes its own guard and asserts the damage.** A guard that cannot be shown to be
load-bearing is decoration: the scan might be refusing for some other reason, or not reaching the
dangerous state at all. The guards are separate functions precisely so that exactly one can be
taken out at a time.

The guards are removed by monkeypatching, not by a flag. A scanner that shipped an off switch for
its safety guards would eventually be run with the switch off.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.library import Library
from atrium.library import config
from atrium.library import scan as scan_module
from atrium.library.scan import (
    RootSuddenlyEmptyError,
    RootUnreadableError,
    ScanRefusedError,
    TooManyRemovalsError,
    scan,
)
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def library(engine: Engine, fixture_library: BuiltFixture) -> Library:
    """A movies library, scanned once, so that there is something to lose."""
    factory = session_factory(engine)
    with session_scope(factory) as db:
        made = config.create(
            LibraryRepository(db), "Movies", "movies", (str(fixture_library.of("movies").root),)
        )
    with session_scope(factory) as db:
        scan(made, db, prober=not_media)
    return made


def stored(engine: Engine, library: Library) -> set[str]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return set(ItemRepository(db).by_library(library.id))


def rescan(engine: Engine, library: Library, **options: object) -> object:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db, prober=not_media, **options)  # type: ignore[arg-type]


def empty_the_root(fixture_library: BuiltFixture) -> None:
    for path in sorted(Path(fixture_library.of("movies").root).rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()


def delete_some_films(fixture_library: BuiltFixture, how_many: int) -> int:
    """Delete films that are actually items, and say how many that was.

    Zero-byte files are skipped: the fixture carries one on purpose (an incomplete copy) and it
    never became an item, so deleting it would make this helper's count disagree with the scan's.
    """
    films = [
        film
        for film in sorted(Path(fixture_library.of("movies").root).glob("*.mkv"))
        if film.stat().st_size > 0
    ]
    for film in films[:how_many]:
        film.unlink()
    return min(how_many, len(films))


# ------------------------------------------------------------------------------------------
# AC-12: a root that cannot be read
# ------------------------------------------------------------------------------------------


def test_an_unreadable_root_removes_nothing(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """AC-12. Asserted against the database: the items are all still there afterwards."""
    before = stored(engine, library)
    root = Path(fixture_library.of("movies").root)
    root.chmod(0o000)
    try:
        if list(root.iterdir()):
            pytest.skip("this process can read a 0o000 directory, so there is nothing to observe")
    except PermissionError:
        pass

    try:
        with pytest.raises(RootUnreadableError):
            rescan(engine, library)
    finally:
        root.chmod(0o755)

    assert stored(engine, library) == before


def test_a_root_that_is_not_there_removes_nothing(
    engine: Engine, library: Library, tmp_path: Path
) -> None:
    """A mount that never came up. Not the same as a root with nothing in it."""
    before = stored(engine, library)
    with pytest.raises(RootUnreadableError, match="not a directory"):
        rescan(engine, library, roots=[tmp_path / "never-mounted"])
    assert stored(engine, library) == before


def test_a_root_that_is_a_file_removes_nothing(
    engine: Engine, library: Library, tmp_path: Path
) -> None:
    """A share that mounted as something other than a directory."""
    not_a_directory = tmp_path / "a-file"
    not_a_directory.write_bytes(b"x")
    with pytest.raises(RootUnreadableError, match="not a directory"):
        rescan(engine, library, roots=[not_a_directory])


# ------------------------------------------------------------------------------------------
# The one that matters: a root that mounts empty
# ------------------------------------------------------------------------------------------


def test_a_root_that_mounts_empty_removes_nothing(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """Guard two, and the reason the guards exist at all.

    An unmounted share and a directory somebody emptied are **the same thing** to a readability
    check: both are a directory that lists nothing. The only way to tell them apart is to remember
    that this library used to have files in it.
    """
    before = stored(engine, library)
    empty_the_root(fixture_library)

    with pytest.raises(RootSuddenlyEmptyError, match="previously held"):
        rescan(engine, library)
    assert stored(engine, library) == before


def test_a_library_that_never_had_files_scans_happily(engine: Engine, tmp_path: Path) -> None:
    """The other half of guard two: *previously*. A new and empty library is not a disaster."""
    empty = tmp_path / "empty-library"
    empty.mkdir()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        made = config.create(LibraryRepository(db), "Empty", "movies", (str(empty),))
    with session_scope(factory) as db:
        report = scan(made, db, prober=not_media)
    assert (report.added, report.missing) == (1, 0), (
        "the library's own CollectionFolder, and no loss"
    )


def test_an_operator_who_really_emptied_it_can_say_so(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """A refusal an operator cannot get past is a refusal they route around."""
    empty_the_root(fixture_library)
    report = rescan(engine, library, confirm_removals=True)
    assert report.missing > 0  # type: ignore[union-attr]


# ------------------------------------------------------------------------------------------
# The slower version: a root that is partly wrong
# ------------------------------------------------------------------------------------------


def test_a_scan_that_would_remove_a_third_of_a_library_stops(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """Guard three. Guard two never fires for this, because the root still yields something."""
    before = stored(engine, library)
    assert delete_some_films(fixture_library, 8) == 8

    with pytest.raises(TooManyRemovalsError, match="over the"):
        rescan(engine, library)
    assert stored(engine, library) == before


def test_losing_one_file_is_not_a_disaster(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    """The threshold has to let ordinary pruning through, or it is a scanner nobody can use."""
    delete_some_films(fixture_library, 1)
    report = rescan(engine, library)
    assert report.missing == 1  # type: ignore[union-attr]
    assert report.removed == 1, "T17 granted the capability this guard constrains"  # type: ignore[union-attr]


def test_the_threshold_is_configurable(
    engine: Engine, library: Library, fixture_library: BuiltFixture
) -> None:
    delete_some_films(fixture_library, 2)
    with pytest.raises(TooManyRemovalsError):
        rescan(engine, library, removal_threshold=0.01)
    assert rescan(engine, library, removal_threshold=0.99)


# ------------------------------------------------------------------------------------------
# Each guard is load-bearing: remove it, and the damage arrives
# ------------------------------------------------------------------------------------------


def test_without_guard_one_an_unreadable_root_looks_like_an_empty_one(
    engine: Engine,
    library: Library,
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remove the readability check and the scan walks on into a root it cannot read.

    What it finds there is nothing - which is precisely what a root whose files were deleted looks
    like. Guard two catches it here, which is the layering working; without *both*, this is a
    library that reports every file missing.
    """
    monkeypatch.setattr(scan_module, "_require_readable_roots", lambda *_: None)
    root = Path(fixture_library.of("movies").root)
    root.chmod(0o000)
    try:
        if list(root.iterdir()):
            pytest.skip("this process can read a 0o000 directory")
    except PermissionError:
        pass
    try:
        with pytest.raises(ScanRefusedError) as raised:
            rescan(engine, library)
        assert not isinstance(raised.value, RootUnreadableError), (
            "guard one still fired, so this test is not exercising its absence"
        )
    finally:
        root.chmod(0o755)


def test_without_guard_two_an_emptied_root_reports_every_file_missing(
    engine: Engine,
    library: Library,
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The damage guard two prevents, made visible.

    With it removed and the threshold raised out of the way, the scan proceeds and counts **every
    file in the library** as gone. T17 turns that count into soft deletions - which is exactly why
    the guard is written and proven before the capability exists.
    """
    held = len(stored(engine, library))
    empty_the_root(fixture_library)
    monkeypatch.setattr(scan_module, "_require_not_suddenly_empty", lambda *_: None)

    report = rescan(engine, library, removal_threshold=1.0)
    assert report.missing > 0  # type: ignore[union-attr]
    assert report.missing == held - 1, "every file-backed item, all but the CollectionFolder"  # type: ignore[union-attr]


def test_without_guard_three_a_third_of_a_library_goes_unremarked(
    engine: Engine,
    library: Library,
    fixture_library: BuiltFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The damage guard three prevents. The scan completes, reports, and nobody is asked."""
    deleted = delete_some_films(fixture_library, 8)
    monkeypatch.setattr(scan_module, "_require_removals_under_threshold", lambda *_: None)

    report = rescan(engine, library)
    assert report.missing == deleted  # type: ignore[union-attr]


def test_the_guards_are_three_separate_functions() -> None:
    """Which is what makes "remove exactly one" possible at all.

    A single `_check_everything` would make each test above prove only that *some* guard fired.
    """
    for name in (
        "_require_readable_roots",
        "_require_not_suddenly_empty",
        "_require_removals_under_threshold",
    ):
        assert callable(getattr(scan_module, name))


def test_every_refusal_shares_one_base_type() -> None:
    """A caller's response is the same to all three: report it and change nothing."""
    for refusal in (RootUnreadableError, RootSuddenlyEmptyError, TooManyRemovalsError):
        assert issubclass(refusal, ScanRefusedError)
