# SPDX-License-Identifier: GPL-3.0-or-later
"""What a rescan looks at, and what it decides not to look at (plan section 6.4).

A scan is incremental by default: a file whose `(size, mtime_ns)` has not moved is **not examined
again**. Examining, in this feature, means exactly one thing — asking a `MetadataSource` what is
embedded in the file — and that is the only content-reading 003 does. Everything else reads paths.

**The signal is a guess, and it is measurably fallible.** `cp -p`, `rsync -a` and an unpacked
archive all restore the modification time, so a file replaced by a same-sized copy carries the
same signal it did before and is skipped. `deep` is the escape hatch, and the test at the bottom
of this file is the reason it exists rather than an argument that it might be needed one day.

**Nothing here is observable to a client**, which is worth knowing before reading the assertions.
No library item and no media source on the reference carries a modification time
`[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`, so which signal Atrium uses, and
whether it skipped a file, cannot be seen from outside — `Size` is the only half that reaches the
wire. What *is* observable is the consequence of getting it wrong: an item whose name or album is
stale, which is why the correctness tests here are about what an unexamined file resolves to.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from sqlalchemy import Engine, select

from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import Item, ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.report import ScanReport
from atrium.library.scan import scan
from tests.conftest import data_dir
from tests.fixtures.library import BuiltFixture, BuiltLibrary, Kind

#: The track whose tags disagree with its directory — the one file in the fixture where skipping
#: the tag read and keeping the path's answer would be **visibly** wrong. T1 measured 413 of 5,814
#: real tracks shaped like this.
RETAGGED = "The Artist/spandau_ballet-through_the_barricades/01 - Tagged Differently.flac"
RETAGGED_ALBUM = "Through the Barricades "

PART_TWO = "The Long Film (1998)/The Long Film (1998) - part2.mkv"


class Recording:
    """A `MetadataSource` that answers from the fixture's declared tags and records every question.

    The recording is the point. "An unchanged file is skipped" is a claim about what the scanner
    *did not do*, and counting the files it re-examined would not catch a scanner that examined
    them all and then discarded the answers — which is the shape the first draft of this had.
    """

    def __init__(self, built: BuiltLibrary) -> None:
        self._tags = {entry.path: dict(entry.tags) for entry in built.library.entries}
        self.asked: list[str] = []

    def tags_for(self, relative_path: str) -> Mapping[str, str]:
        self.asked.append(relative_path)
        return self._tags.get(relative_path, {})

    def retag(self, relative_path: str, **tags: str) -> None:
        """What a tag editor does to a file that is already on disk."""
        self._tags.setdefault(relative_path, {}).update(tags)


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
        return scan(library, db, **options)  # type: ignore[arg-type]


def items_of(engine: Engine, library: Library) -> dict[str, Item]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return ItemRepository(db).by_library(library.id)


def media_paths(built: BuiltLibrary) -> set[str]:
    return {entry.path for entry in built.library.entries if entry.kind is Kind.MEDIA}


def track_named(engine: Engine, library: Library, title: str) -> Item:
    return next(
        item
        for item in items_of(engine, library).values()
        if item.type is ItemType.AUDIO and item.name == title
    )


def album_of(engine: Engine, library: Library, track: Item) -> Item:
    return items_of(engine, library)[str(track.parent_id)]


# ------------------------------------------------------------------------------------------
# The signal: what gets examined
# ------------------------------------------------------------------------------------------


def test_a_first_scan_examines_every_file(engine: Engine, fixture_library: BuiltFixture) -> None:
    """There is nothing to compare against, so nothing can be skipped."""
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    source = Recording(built)

    report = scanned(engine, library, source=source)

    assert report.examined == len(media_paths(built))
    assert set(source.asked) == media_paths(built)


def test_a_second_scan_examines_nothing(engine: Engine, fixture_library: BuiltFixture) -> None:
    """The whole point of the signal: an untouched library costs one walk and no reads at all."""
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))

    second = Recording(built)
    report = scanned(engine, library, source=second)

    assert second.asked == [], "every file was opened again on a library nothing had touched"
    assert report.examined == 0
    assert (report.added, report.updated) == (0, 0)


def test_only_the_modified_file_is_examined(engine: Engine, fixture_library: BuiltFixture) -> None:
    """A modified file is re-examined; its neighbours are not."""
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))

    changed = "The Artist/First Album (2001)/01 - Opening.flac"
    path = built.path_of(changed)
    path.write_bytes(path.read_bytes() + b"a longer transfer\n")

    second = Recording(built)
    report = scanned(engine, library, source=second)

    assert second.asked == [changed]
    assert (report.examined, report.updated) == (1, 1)


def test_a_modified_file_keeps_its_identity_and_its_user_data(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """Spec section 3.8, the second row: re-inspect and update, **preserving identity**.

    Identity is path-derived, so this holds for the same reason AC-11 does — and it is asserted
    here because "the file changed" is the case where a scanner is most tempted to start again.
    """
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))
    before = track_named(engine, library, "01 - Opening")

    user_id = "c" * 32
    factory = session_factory(engine)
    with session_scope(factory) as db:
        db.add(models.User(id=user_id, name="Joan", name_normalised="joan", password_hash=None))
        db.flush()
        db.add(models.ItemUserData(user_id=user_id, item_key=before.id, play_count=3))

    path = built.path_of("The Artist/First Album (2001)/01 - Opening.flac")
    path.write_bytes(path.read_bytes() + b"a longer transfer\n")
    scanned(engine, library, source=Recording(built))

    after = track_named(engine, library, "01 - Opening")
    assert after.id == before.id, "a re-encode cost the user every client-side reference to it"
    assert after.size != before.size, "the new size never reached the database"

    with session_scope(factory) as db:
        stored = db.execute(
            select(models.ItemUserData).where(models.ItemUserData.item_key == before.id)
        ).scalar_one()
        assert stored.play_count == 3


def test_a_new_file_on_a_rescan_is_added(engine: Engine, fixture_library: BuiltFixture) -> None:
    """Spec section 3.8, the first row: add the item. The scan that finds it is incremental."""
    built = fixture_library.of("movies")
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    before = items_of(engine, library)

    folder = built.root / "The Late Arrival (2020)"
    folder.mkdir()
    (folder / "The Late Arrival (2020).mkv").write_bytes(
        b"atrium synthetic fixture\n" + b"\0" * 600
    )
    scanned(engine, library)

    added = {one.name for key, one in items_of(engine, library).items() if key not in before}
    assert added == {"The Late Arrival"}


def test_a_rename_is_a_delete_plus_an_add(engine: Engine, fixture_library: BuiltFixture) -> None:
    """Spec section 3.8, the rename row: identity is path-derived, so it changes."""
    built = fixture_library.of("movies")
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    [old] = [one for one in items_of(engine, library).values() if one.name == "2 Fast 2 Furious"]

    (built.root / "2 Fast 2 Furious (2003).mkv").rename(
        built.root / "2 Fast 2 Furious Reloaded (2003).mkv"
    )
    scanned(engine, library)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert old.id not in ItemRepository(db).visible(library.id), (
            "the old path's item still answers queries after the delete half"
        )
    [new] = [
        one for one in items_of(engine, library).values() if one.name == "2 Fast 2 Furious Reloaded"
    ]
    assert new.id != old.id, "a renamed path kept its identity, which path derivation forbids"


def test_a_touched_file_is_examined_once_and_then_left_alone(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """A modification time that moved on its own — a `touch`, a metadata tool, a restore.

    The second half is the one that would rot silently: if the new signal were not written back,
    the file would be re-examined on **every** scan from then on, and a library full of them
    turns the incremental scan back into a full one with nothing to show for it.
    """
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))

    touched = "The Artist/Second Album/01 - In Another Container.m4a"
    stat = built.path_of(touched).stat()
    os.utime(built.path_of(touched), ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    second = Recording(built)
    assert scanned(engine, library, source=second).examined == 1
    assert second.asked == [touched]

    third = Recording(built)
    assert scanned(engine, library, source=third).examined == 0
    assert third.asked == [], "the new modification time was never written back"


def test_one_rewritten_part_re_examines_the_film_that_owns_it(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """A two-part film is one item, so the signal is read across the whole source tuple.

    A per-path test would leave the film half-updated: part two's new size recorded and part one's
    row untouched, or the reverse, depending on which path the diff happened to read first.
    """
    built = fixture_library.of("movies")
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    before = next(
        item for item in items_of(engine, library).values() if item.name == "The Long Film"
    )

    path = built.path_of(PART_TWO)
    path.write_bytes(path.read_bytes() + b"a longer second reel\n")
    report = scanned(engine, library)

    after = next(
        item for item in items_of(engine, library).values() if item.name == "The Long Film"
    )
    assert (report.examined, report.updated) == (1, 1)
    assert after.id == before.id
    assert len(after.sources) == 2, "the film became one part, or two films"
    assert after.sources[1].size != before.sources[1].size


# ------------------------------------------------------------------------------------------
# Skipping the examination must not change the answer
# ------------------------------------------------------------------------------------------


def test_an_unexamined_track_keeps_the_album_its_tags_gave_it(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The correctness of the whole optimisation, in the one place it can be seen.

    This track's tag says `Through the Barricades ` and its directory says
    `spandau_ballet-through_the_barricades`. A second scan does not read the tag — so the item it
    resolves to hangs from an album named after the **directory**, which is a container this scan
    invented and must never write. The stored row is kept and the invented album is dropped.

    Get this wrong and the second scan of every music library silently doubles its albums.
    """
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))
    first = items_of(engine, library)
    track = track_named(engine, library, "01 - Tagged Differently")
    assert album_of(engine, library, track).name == RETAGGED_ALBUM, "the fixture stopped biting"

    report = scanned(engine, library, source=Recording(built))

    assert report.added == 0, "a path-derived album was invented for a file nobody re-examined"
    assert set(items_of(engine, library)) == set(first)
    assert album_of(engine, library, track).name == RETAGGED_ALBUM
    assert report.unchanged == len(first)


def test_an_unexamined_track_is_still_revived_when_its_file_comes_back(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """A remount restores the file *and* its modification time, so nothing is re-examined — and
    the item still has to come back. Revival is a fact about the row, not about the reading."""
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))

    path = built.path_of(RETAGGED)
    contents, stat = path.read_bytes(), path.stat()
    path.unlink()
    scanned(engine, library, source=Recording(built))

    path.write_bytes(contents)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    source = Recording(built)
    report = scanned(engine, library, source=source)

    assert (report.revived, report.added, report.examined) == (1, 0, 0)
    assert source.asked == [], "a file that never changed was opened because its row had"
    assert album_of(
        engine, library, track_named(engine, library, "01 - Tagged Differently")
    ).name == (RETAGGED_ALBUM)


# ------------------------------------------------------------------------------------------
# `deep`: the escape hatch, and the blind spot that justifies it
# ------------------------------------------------------------------------------------------


def test_deep_examines_everything_and_still_finds_nothing_to_change(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """`deep` changes what is *looked at*, not what is concluded. A deep scan of an untouched
    library reads every file and writes nothing, which is what makes it safe to reach for."""
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))
    before = items_of(engine, library)

    source = Recording(built)
    report = scanned(engine, library, source=source, deep=True)

    assert set(source.asked) == media_paths(built)
    assert report.examined == len(media_paths(built))
    assert (report.added, report.updated) == (0, 0)
    assert report.unchanged == len(before)


def test_the_signal_cannot_see_a_same_sized_rewrite_and_deep_can(
    engine: Engine, fixture_library: BuiltFixture
) -> None:
    """The measured blind spot, and the whole reason `deep` exists.

    `cp -p`, `rsync -a` and `tar -x` all restore the modification time, and a tag editor that
    rewrites a header in place can leave the size alone. Measured on this filesystem: writing new
    bytes of the same length and restoring the time with `os.utime` produces a byte-for-byte
    identical `(size, mtime_ns)` `[probe: local measurement, macOS APFS, 2026-08-27]`.

    The default misses it — deliberately, because the alternative is hashing every file on every
    scan — and `deep` is how an operator who knows their times are untrustworthy gets the truth.
    """
    built = fixture_library.of("music")
    library = a_library(engine, fixture_library, "music")
    scanned(engine, library, source=Recording(built))

    path = built.path_of(RETAGGED)
    stat = path.stat()
    path.write_bytes(b"Z" * stat.st_size)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    assert path.stat().st_mtime_ns == stat.st_mtime_ns

    retagged = Recording(built)
    retagged.retag(RETAGGED, title="Renamed By A Tag Editor")

    missed = scanned(engine, library, source=retagged)
    assert (missed.examined, missed.updated) == (0, 0)
    assert retagged.asked == []
    assert track_named(engine, library, "01 - Tagged Differently")

    found = scanned(engine, library, source=retagged, deep=True)
    assert track_named(engine, library, "Renamed By A Tag Editor")
    # **The name changed, and the refresh is what changed it** - since 004 T10 the scanner names
    # an item when it creates it and 004 owns the name afterwards, so `report.updated`, which
    # counts rows the *scanner* rewrote, is no longer where a retitled track shows up. The
    # assertion above is the behaviour; this one says which half of the scan did it.
    assert found.refreshed is not None
    assert found.refreshed.changed >= 1  # type: ignore[attr-defined]


def test_deep_does_not_lift_the_guards(engine: Engine, fixture_library: BuiltFixture) -> None:
    """`deep` says how hard to look, not what to believe. An operator reaching for it because a
    share looked wrong must not thereby disarm the guard that catches a share being wrong."""
    from atrium.library.scan import RootSuddenlyEmptyError

    built = fixture_library.of("movies")
    library = a_library(engine, fixture_library, "movies")
    scanned(engine, library)
    before = set(items_of(engine, library))

    for path in sorted(Path(built.root).rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()

    with pytest.raises(RootSuddenlyEmptyError):
        scanned(engine, library, deep=True)
    assert set(items_of(engine, library)) == before
