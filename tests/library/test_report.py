# SPDX-License-Identifier: GPL-3.0-or-later
"""What a scan says while it runs, and what it says afterwards (plan §3, §7).

The task that produced this file asked for "an unreadable file and an unparseable name, each with
its reason", which sounds like one list with two entries in it. **It cannot be one list.** An
unreadable file produced no item; an unparseable name produced one and it is sitting in the
library. An operator told "2 files skipped" would go looking for two missing films and find one,
having been sent to look for something that is not missing. So the summary has two lists, and the
first test below is the one that would fail if they were ever merged.

**A second thing the task statement got wrong, and this one is measured.** Plan §7 said an
unreadable *file* inside a readable root is skipped, counted and reported. It is not, because
nothing in 003 opens a file: a `chmod 000` file stats perfectly well and is scanned into an item
like any other. What is detectable is a file that cannot be **stat**ed - a dangling symlink - and a
directory that cannot be **listed**. `test_a_file_is_only_unreadable_when_it_cannot_be_stat_ed`
holds all three cases, and plan §7 now says so.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import CollectionType, Item, ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.report import Phase, Progress, ScanReport, silent
from atrium.library.resolver import Notice, resolve
from atrium.library.scan import RootUnreadableError, scan
from atrium.library.walker import Candidate, Skip
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture

#: The fixture entry whose name says nothing. It is under a season directory, so the scan knows
#: which series and which season it belongs to and still cannot place it within one.
BLOB = "The Series/Season 01/blob.mkv"


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


def scanned(engine: Engine, library: Library, **options: object) -> ScanReport:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db, prober=not_media, **options)  # type: ignore[arg-type]


def items_of(engine: Engine, library: Library) -> dict[str, Item]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return ItemRepository(db).by_library(library.id)


class Recording:
    """A progress sink that keeps everything it was told."""

    def __init__(self) -> None:
        self.seen: list[Progress] = []

    def __call__(self, progress: Progress) -> None:
        self.seen.append(progress)

    def phases(self) -> list[Phase]:
        """In order, with runs collapsed - what a reader of a progress bar would have seen."""
        ordered: list[Phase] = []
        for one in self.seen:
            if not ordered or ordered[-1] is not one.phase:
                ordered.append(one.phase)
        return ordered

    def of(self, phase: Phase) -> list[Progress]:
        return [one for one in self.seen if one.phase is phase]


def unreadable(directory: Path) -> bool:
    """`chmod 000` and say whether it took. Root reads it anyway, and so does Windows."""
    directory.chmod(0o000)
    try:
        next(directory.iterdir(), None)
    except OSError:
        return True
    else:
        directory.chmod(0o755)
        return False


# ------------------------------------------------------------------------------------------
# The verification: both are reported, each with its reason, and neither aborts the scan
# ------------------------------------------------------------------------------------------


def test_a_skipped_file_and_a_scanned_one_are_reported_apart(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The task's verification, and the correction to how it was phrased.

    Both are reported with a reason. They are in **different lists**, because one of them is a
    film that is not there and the other is an episode that is.
    """
    built = fixture_library.of("tvshows")
    dangling = built.root / "The Series" / "Season 01" / "Gone - S01E09.mkv"
    dangling.symlink_to(built.root / "nothing-here.mkv")

    library = a_library(engine, (str(built.root),), "tvshows")
    report = scanned(engine, library)

    assert report.added > 0, "the scan aborted, so nothing below means anything"
    assert Skip.UNREADABLE.value in report.reasons()
    assert report.notice_reasons() == {Notice.NO_EPISODE_NUMBER.value: 1}

    skipped_paths = {one.relative_path for one in report.skipped}
    noticed_paths = {one.relative_path for one in report.noticed}
    assert dangling.name in {Path(one).name for one in skipped_paths}
    assert noticed_paths == {BLOB}
    assert not (skipped_paths & noticed_paths), "a file is either scanned or walked past, not both"


def test_a_noticed_file_is_in_the_library_and_a_skipped_one_is_not(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The distinction the two lists exist for, asserted against the database rather than the
    report - which is the only place it could be wrong without either list looking odd."""
    built = fixture_library.of("tvshows")
    library = a_library(engine, (str(built.root),), "tvshows")
    report = scanned(engine, library)
    stored = items_of(engine, library)

    for one in report.noticed:
        assert one.item_id in stored, f"{one.relative_path} was reported as scanned and is not here"
        assert stored[one.item_id].index_number is None

    paths = {source.relative_path for item in stored.values() for source in item.sources}
    for one in report.skipped:
        assert one.relative_path not in paths, f"{one.relative_path} was skipped and is here"


def test_the_unparseable_name_still_became_a_usable_item(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """Plan §7: "an item with a title and nothing else". The title is the half that matters -
    an item with no name is one a user cannot find, so the fallback is the point, not a failure."""
    built = fixture_library.of("tvshows")
    library = a_library(engine, (str(built.root),), "tvshows")
    scanned(engine, library)

    blob = next(item for item in items_of(engine, library).values() if item.relative_path == BLOB)
    assert blob.type is ItemType.EPISODE
    assert blob.name == "blob"
    assert blob.index_number is None
    assert blob.parent_index_number == 1, "the season came from the directory, which did parse"


def test_a_file_is_only_unreadable_when_it_cannot_be_stat_ed(
    engine: Engine, tmp_path: Path
) -> None:
    """The measured correction to plan §7.

    Three files that an operator would all call "unreadable", and only two of them are visible to
    a scanner that never opens anything:

    * a `chmod 000` **file** - stats fine, is scanned, becomes an item. 008 is where it fails.
    * a **dangling symlink** - the stat raises, so it is skipped and reported.
    * an unreadable **directory** - cannot be listed, so it is skipped and reported.

    The first is the one plan §7 named and the one that does not happen.
    """
    root = tmp_path / "movies"
    (root / "Closed").mkdir(parents=True)
    (root / "Closed" / "Inside (2001).mkv").write_bytes(b"x" * 600)
    locked = root / "Locked (1999).mkv"
    locked.write_bytes(b"x" * 600)
    locked.chmod(0o000)
    (root / "Dangling (2002).mkv").symlink_to(root / "nothing-here.mkv")

    if not unreadable(root / "Closed"):
        pytest.skip("this process can read a 0o000 directory, so there is nothing to observe")
    try:
        library = a_library(engine, (str(root),), "movies")
        report = scanned(engine, library)
    finally:
        (root / "Closed").chmod(0o755)

    names = {item.name for item in items_of(engine, library).values()}
    assert "Locked" in names, "a file whose contents cannot be read was skipped; nothing opens it"
    assert "Inside" not in names, "a file under an unlistable directory was somehow found"

    skipped = {one.relative_path: one.reason for one in report.skipped}
    assert skipped.get("Dangling (2002).mkv") is Skip.UNREADABLE
    assert skipped.get("Closed") is Skip.UNREADABLE
    assert "Locked (1999).mkv" not in skipped


# ------------------------------------------------------------------------------------------
# Progress
# ------------------------------------------------------------------------------------------


def test_progress_reports_the_four_phases_in_order(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """Four since 008 T3 added inspection, and it reports even when every file refuses to open:
    a phase that only spoke on success would go silent on the library that needs it most."""
    built = fixture_library.of("movies")
    library = a_library(engine, (str(built.root),), "movies")
    sink = Recording()

    scanned(engine, library, progress=sink)

    assert sink.phases() == [Phase.WALKING, Phase.RESOLVING, Phase.INSPECTING, Phase.WRITING]
    assert all(one.library_id == library.id for one in sink.seen)


def test_the_walk_counts_roots_because_it_does_not_yet_know_the_files(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The honest half of the design. How many files a tree holds is what the walk is computing,
    so a walk that reported a file total would be reporting a number it had made up."""
    first = fixture_library.of("movies").root
    second = fixture_library.of("tvshows").root
    library = a_library(engine, (str(first), str(second)), "movies")
    sink = Recording()

    scanned(engine, library, progress=sink)

    walking = sink.of(Phase.WALKING)
    assert [one.done for one in walking] == [1, 2]
    assert {one.total for one in walking} == {2}, "the total is roots, not files"
    assert {one.detail for one in walking} == {str(first), str(second)}
    assert walking[-1].fraction == 1.0


def test_the_writing_phase_counts_every_item(engine: Engine, fixture_library: BuiltFixture) -> None:
    built = fixture_library.of("music")
    library = a_library(engine, (str(built.root),), "music")
    sink = Recording()

    report = scanned(engine, library, progress=sink)

    writing = sink.of(Phase.WRITING)
    assert [one.done for one in writing] == list(range(1, report.added + 1))
    assert {one.total for one in writing} == {report.added}
    assert writing[-1].fraction == 1.0


def test_a_progress_with_no_total_has_no_fraction() -> None:
    """A progress bar asks for a fraction; the answer is sometimes "there isn't one"."""
    assert Progress("a" * 32, Phase.WALKING, done=3).fraction is None
    assert Progress("a" * 32, Phase.WALKING, done=3, total=0).fraction is None
    assert Progress("a" * 32, Phase.WRITING, done=1, total=4).fraction == 0.25


def test_a_progress_sink_that_raises_does_not_take_the_scan_with_it(
    engine: Engine, fixture_library: BuiltFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """A scan destroyed by its own instrumentation would roll back a transaction that had nothing
    wrong with it. The sink is disabled after the first failure and logged **once** - a scan of a
    large library must not write one traceback per file to explain one broken callback."""
    calls = 0

    def broken(progress: Progress) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("the terminal went away")

    built = fixture_library.of("movies")
    library = a_library(engine, (str(built.root),), "movies")
    with caplog.at_level("ERROR"):
        report = scanned(engine, library, progress=broken)

    assert report.added > 0, "the scan died because a progress bar did"
    assert len(items_of(engine, library)) == report.added, "the transaction was rolled back"
    assert calls == 1, f"a broken sink was called {calls} times"
    assert sum("progress sink raised" in one.message for one in caplog.records) == 1


def test_a_refused_scan_returns_no_summary(engine: Engine, tmp_path: Path) -> None:
    """There is no summary of a scan that did not happen, and a sink told "walking" and then
    nothing more has been told the truth."""
    root = tmp_path / "gone"
    library = a_library(engine, (str(root),), "movies")
    sink = Recording()

    with pytest.raises(RootUnreadableError):
        scanned(engine, library, progress=sink)

    assert sink.seen == [], "progress was reported for a scan that never started"


def test_the_default_sink_reports_to_nobody() -> None:
    """A scan run by a test or a migration says nothing, and says it without a branch."""
    assert silent(Progress("a" * 32, Phase.WALKING, done=1, total=1)) is None


# ------------------------------------------------------------------------------------------
# The summary line, and the notices in isolation
# ------------------------------------------------------------------------------------------


def test_the_summary_names_every_category_including_the_empty_ones(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """A summary that drops a category when it is zero makes "nothing was skipped"
    indistinguishable from "this version does not report skipped files"."""
    quiet = ScanReport(library_id="a" * 32)
    line = quiet.summary()
    for word in ("added", "updated", "unchanged", "removed", "revived", "skipped", "noticed"):
        assert word in line, line
    assert "0 skipped, 0 noticed" in line

    built = fixture_library.of("tvshows")
    library = a_library(engine, (str(built.root),), "tvshows")
    report = scanned(engine, library)
    assert f"{len(report.skipped)} skipped, {len(report.noticed)} noticed" in report.summary()


def a_show_library() -> Library:
    return Library(
        id="b" * 32, name="Shows", collection_type=CollectionType.TVSHOWS, roots=("/shows",)
    )


def resolved_notices(*paths: str) -> tuple[str, ...]:
    candidates = [Candidate(one, size=600, mtime_ns=1) for one in paths]
    return tuple(one.relative_path for one in resolve(a_show_library(), candidates).noticed)


def test_a_dated_episode_is_placed_and_is_not_noticed() -> None:
    """**The bug the fixture caught**, and the reason notices come from the resolver.

    The first version computed them from the finished items - every `Episode` with no
    `index_number` - which is right for a name nothing could be read from and wrong for a daily
    show, whose episodes are ordered by their date and need no number. An `Item` carries no date,
    so from the items alone the two are the same thing. Only the module that read the name knows.

    Left uncaught, a scan of any library with a daily show in it would have reported every one of
    its episodes as unparseable, which is the kind of noise that makes a whole category ignored.
    """
    dated = "The Daily Show/Season 2024/The Daily Show - 2024-01-31.mkv"
    numbered = "The Series/Season 01/The Series - S01E01 - Pilot.mkv"
    nameless = "The Series/Season 01/blob.mkv"

    assert resolved_notices(dated, numbered, nameless) == (nameless,)


def test_a_notice_names_the_item_it_is_about() -> None:
    """An operator reading a notice goes and looks at that item, so it carries the id as well as
    the path - a path alone would make them search for it."""
    nameless = "The Series/Season 01/blob.mkv"
    resolution = resolve(a_show_library(), [Candidate(nameless, size=600, mtime_ns=1)])

    (one,) = resolution.noticed
    assert one.reason is Notice.NO_EPISODE_NUMBER
    assert one.relative_path == nameless
    assert resolution.by_id(one.item_id) is not None, "the notice names an item nobody resolved"


def test_the_notices_are_ordered_so_two_scans_report_the_same_list() -> None:
    """The same tree scanned twice produces the same report, which is the same requirement spec
    §3.8 puts on the items themselves."""
    paths = [f"The Series/Season 01/blob {n}.mkv" for n in (3, 1, 2)]
    resolution = resolve(a_show_library(), [Candidate(one, size=600, mtime_ns=1) for one in paths])
    ids = [one.item_id for one in resolution.noticed]
    assert ids == sorted(ids)
    assert len(ids) == 3
