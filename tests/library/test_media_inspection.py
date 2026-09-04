# SPDX-License-Identifier: GPL-3.0-or-later
"""The scan opens files now, and what it does when one will not open.

Two halves, split by whether a binary is needed. The first runs the real prober over 008 T1's
generated matrix and asks what a *second* scan does - which is the whole point of putting
inspection behind a change signal, and the half that cannot be faked. The second hands the scan
probers that refuse, because the two refusals mean opposite things: one file that will not open is
a fact about that file, and a prober that is not installed is a fact about every file at once.

003 plan section 7 named this arrival in advance: "a file whose **contents** cannot be read - not
detected here … 008 finds it when it goes to probe or play it". This is where it is found.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import ItemRepository, LibraryRepository, MediaProbeRepository
from atrium.domain.items import CollectionType, ItemType
from atrium.domain.library import Library
from atrium.domain.media import MediaInspection
from atrium.library.scan import scan
from atrium.media.probe import ProberUnavailableError, UnreadableMediaError
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture
from tests.fixtures.media import MOVIES_LIBRARY_ID, MOVIES_ROOT, UNINSPECTABLE, BuiltMedia


def refused_films() -> set[str]:
    """The paths under the movies root that no prober will accept, read from the declarations.

    A set rather than a count, and read rather than written down, so that an entry added to
    `tests/fixtures/media.py` extends every assertion below instead of breaking one.
    """
    return {one.path for one in UNINSPECTABLE if one.root == MOVIES_ROOT}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[OrmSession]:
    opened = session_factory(engine)()
    yield opened
    opened.rollback()
    opened.close()


def a_library(session: OrmSession, root: Path, collection_type: CollectionType) -> Library:
    return LibraryRepository(session).add(
        Library(
            id=MOVIES_LIBRARY_ID,
            name="Films",
            collection_type=collection_type,
            roots=(str(root),),
        )
    )


# ------------------------------------------------------------------------------------------
# With a real prober, over real files
# ------------------------------------------------------------------------------------------


@pytest.mark.ffmpeg
def test_a_first_scan_inspects_every_file_and_a_second_inspects_none(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The change signal, applied to inspection rather than to tags.

    The second scan is the assertion that matters. Inspection is the slowest thing a scan does, so
    a rule that re-opened every file every time would make an incremental scan of a large library
    cost the same as the first one - and nothing else in the report would show it.
    """
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root, CollectionType.MOVIES)

    first = scan(library, session)
    assert first.inspected > 0
    #: **Not empty, and the count is declared rather than tolerated.** The world holds files no
    #: prober will accept since 012 T2 - the state that feature exists to close - so what this
    #: asserts is that every *other* file was opened and that a refusal is recorded rather than
    #: swallowed. `refused_films()` reads the declarations, so adding one extends this instead of
    #: breaking it.
    assert {one.relative_path for one in first.uninspected} == refused_films()

    again = scan(library, session)
    assert again.inspected == 0, "a scan that changed nothing re-opened files anyway"
    #: **A file that cannot be opened is re-attempted on every scan**, because there is no stored
    #: inspection for the change signal to compare against. Measured here rather than assumed: it
    #: is what makes a rescan the closing mechanism for a file that becomes readable.
    assert {one.relative_path for one in again.uninspected} == refused_films()

    deep = scan(library, session, deep=True)
    assert deep.inspected == first.inspected, "deep is what ignores the signal, here as elsewhere"


@pytest.mark.ffmpeg
def test_a_rewritten_file_is_inspected_again(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """One file, and only that file: staleness is per file because the signal is per file."""
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root, CollectionType.MOVIES)
    scan(library, session)

    victim = next(tree.movies_root.rglob("*.mp4"))
    victim.write_bytes(victim.read_bytes() + b"\x00" * 4096)

    report = scan(library, session)
    assert report.inspected == 1


@pytest.mark.ffmpeg
def test_every_scanned_file_has_an_inspection_keyed_the_way_its_source_is(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The join the wire assembly makes, asserted from the storage side.

    A probe row keyed differently from `item_sources` would be invisible here and would answer
    nothing at request time - a page of films with no media sources and no error anywhere.
    """
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root, CollectionType.MOVIES)
    scan(library, session)

    probes = MediaProbeRepository(session)
    items = ItemRepository(session).by_library(library.id)
    files = [
        source for item in items.values() if item.type is ItemType.MOVIE for source in item.sources
    ]
    assert files, "no film was scanned, so nothing below means anything"
    refused = refused_films()
    assert refused, "the world has no refused entry, so the exclusion below hides nothing"
    for source in files:
        stored = probes.get(library.id, source.relative_path)
        if source.relative_path in refused:
            #: 012 T2's entries, and the one assertion that matters about them here: **no probe
            #: row at all**, rather than an empty one. `tests/unit/test_media_fixtures.py` owns
            #: the rest of what that state looks like.
            assert stored is None, f"{source.relative_path} was inspected and should not have been"
            continue
        assert stored is not None, f"{source.relative_path} has no inspection"
        assert stored.container, f"{source.relative_path} was inspected and said nothing"
        assert stored.unchanged_since(source.size or 0, source.mtime_ns or 0), (
            "the stored change signal disagrees with the one the walk recorded for the same file"
        )


# ------------------------------------------------------------------------------------------
# When the prober refuses
# ------------------------------------------------------------------------------------------


def test_a_file_that_will_not_open_is_recorded_and_keeps_its_item(
    session: OrmSession, fixture_library: BuiltFixture
) -> None:
    """003's fixture tree is dummy bytes, so `not_media` is the truth about every file in it.

    The item is the half that matters. A film that cannot be inspected is still a film: it has a
    path, an identity and a name, and a scan that dropped it would lose a user's favourites over a
    truncated download.
    """
    built = fixture_library.of("movies")
    library = a_library(session, built.root, CollectionType.MOVIES)

    report = scan(library, session, prober=not_media)

    assert report.uninspected, "nothing was recorded although nothing could be opened"
    assert report.inspected == 0
    assert report.added > 0, "the scan gave up on the library over files it could not open"

    refused = {one.relative_path for one in report.uninspected}
    scanned_paths = {
        source.relative_path
        for item in ItemRepository(session).by_library(library.id).values()
        for source in item.sources
    }
    assert refused <= scanned_paths, "a file was reported uninspected and is not in the library"


def test_a_missing_prober_stops_the_phase_instead_of_condemning_every_file(
    session: OrmSession, fixture_library: BuiltFixture
) -> None:
    """The distinction `media/probe.py` raises two exceptions for.

    A library reported as thousands of unreadable files, when what happened is that nobody
    installed the tool, buries the one fact that explains all of them - and it would be the same
    report a genuinely broken library produces.
    """
    built = fixture_library.of("movies")
    library = a_library(session, built.root, CollectionType.MOVIES)

    def missing(path: Path) -> MediaInspection:
        raise ProberUnavailableError("ffprobe is not on PATH")

    report = scan(library, session, prober=missing)

    assert report.uninspected == (), "an operator's problem was recorded as the library's"
    assert report.inspected == 0
    assert report.added > 0


def test_an_uninspectable_file_still_answers_a_source_from_what_the_walk_knew(
    session: OrmSession, fixture_library: BuiltFixture
) -> None:
    """What a client gets for a film nothing could open: a source, a path, a size and a tag.

    The reference does the same for a file it has never probed - the container falls back to the
    extension and the stream list is empty `[source:
    MediaBrowser.Controller/Entities/BaseItem.cs:1200-1207 @ v10.11.11]` - so the item is visible
    and unplayable rather than absent.
    """
    from atrium.media.info import sources_for

    built = fixture_library.of("movies")
    library = a_library(session, built.root, CollectionType.MOVIES)
    scan(library, session, prober=not_media)

    film = next(
        item
        for item in ItemRepository(session).by_library(library.id).values()
        if item.type is ItemType.MOVIE
    )
    source = sources_for(film, [None], str(built.root), is_video=True)[0]

    assert source.container == film.sources[0].relative_path.rsplit(".", 1)[-1]
    assert source.media_streams == []
    assert source.e_tag is not None, "the tag is the modification time, which the walk did read"
    assert source.path is not None


def test_the_stub_prober_is_what_a_library_of_dummy_bytes_deserves(
    session: OrmSession, fixture_library: BuiltFixture
) -> None:
    """A guard on the stub itself: `not_media` must refuse, or every suite that passes it would be
    asserting against inspections nobody produced."""
    with pytest.raises(UnreadableMediaError):
        not_media(Path("anything"))
