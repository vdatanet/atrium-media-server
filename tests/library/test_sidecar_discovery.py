# SPDX-License-Identifier: GPL-3.0-or-later
"""A subtitle file beside a film, appearing and disappearing.

011 AC-11 and AC-12, in 003 AC-11's own shape: a mutation test, where the "before" state is
**made** rather than found. T1 ships the sidecar inside the built tree, so the way to observe a
library without one is to copy the tree out and delete it.

**The middle scan being a default scan is the whole point.** Dropping an `.srt` beside a film
changes nothing about the film's own `(size, mtime_ns)`, so the media file's change signal says
"unchanged" and `_inspect_media` would skip it - which is 006's replaced-poster shape one feature
later. Force a deep scan here and every assertion below passes with the second signal deleted.

**And the renumbering is the reason this is a test rather than a row.** A discovered stream is
numbered *ahead of* the container's own, so putting a file beside a film moves every audio and
video index it has - and a stream index is what a delivery address carries.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import LibraryRepository, MediaProbeRepository
from atrium.domain.items import CollectionType
from atrium.domain.library import Library
from atrium.domain.media import StreamKind
from atrium.library.scan import scan
from atrium.media.info import has_subtitles
from tests.conftest import data_dir
from tests.fixtures.media import MOVIES_LIBRARY_ID, UNCONVERTIBLE_SUBTITLE, BuiltMedia

#: The entry T1 put the sidecar beside, and the sidecar's own declaration. Named rather than
#: searched for: the matrix is free to grow another film with another sidecar.
FILM = UNCONVERTIBLE_SUBTITLE
SIDECAR = FILM.sidecars[0]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
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


def a_library(session: OrmSession, root: Path) -> Library:
    return LibraryRepository(session).add(
        Library(
            id=MOVIES_LIBRARY_ID,
            name="Films",
            collection_type=CollectionType.MOVIES,
            roots=(str(root),),
        )
    )


def indices_of(session: OrmSession, library: Library) -> list[tuple[str, int]]:
    """Every stream of the film under test, as `(kind, wire index)` in wire order."""
    found = MediaProbeRepository(session).get(library.id, FILM.path)
    assert found is not None, "the film under test was never inspected"
    return [(one.kind.value, one.index) for one in found.streams]


def film_signal(session: OrmSession, library: Library) -> tuple[int, int]:
    found = MediaProbeRepository(session).get(library.id, FILM.path)
    assert found is not None
    return found.size, found.mtime_ns


@pytest.mark.ffmpeg
def test_a_sidecar_appears_and_disappears_and_the_indices_follow_it(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """AC-11 and AC-12, as one story, because the second is only observable after the first."""
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root)
    sidecar = tree.sidecar_path_of(FILM, SIDECAR)
    assert sidecar.is_file(), "T1's sidecar is not in the built tree; this test proves nothing"
    kept = sidecar.read_bytes()

    # ---- before: the film alone -------------------------------------------------------------
    sidecar.unlink()
    scan(library, session)
    before = indices_of(session, library)
    assert before == [("video", 0), ("audio", 1), ("subtitle", 2)], before
    alone = MediaProbeRepository(session).get(library.id, FILM.path)
    assert [one.is_external for one in alone.streams if alone] == [False, False, False], (
        "with the file deleted, every stream must be the container's own"
    )
    signal_before = film_signal(session, library)

    # ---- the file arrives, and a **default** scan notices ------------------------------------
    sidecar.write_bytes(kept)
    report = scan(library, session)
    assert report.uninspected == ()

    after = indices_of(session, library)
    assert after == [("subtitle", 0), ("video", 1), ("audio", 2), ("subtitle", 3)], (
        f"the discovered stream must be numbered first and push the rest up by one: {after}"
    )
    assert film_signal(session, library) == signal_before, (
        "the film's own change signal moved, so this proved the media file was re-inspected "
        "rather than the sidecar discovered"
    )

    found = MediaProbeRepository(session).get(library.id, FILM.path)
    assert found is not None
    discovered = found.streams[0]
    assert discovered.is_external is True
    assert discovered.external_path == f"{Path(FILM.path).parent}/{SIDECAR.name}"
    assert discovered.kind is StreamKind.SUBTITLE
    assert has_subtitles([found]) is True

    # The right-to-left read of the name, end to end: `forced` is a flag, `spa` a language, and
    # `Commentary` is claimed by nothing and becomes the title.
    assert (discovered.language, discovered.is_forced, discovered.title) == (
        "spa",
        True,
        "Commentary",
    )

    # ---- and away again ---------------------------------------------------------------------
    sidecar.unlink()
    scan(library, session)
    assert indices_of(session, library) == before, (
        "removing the file must put every index back; nothing stored a wire index to correct"
    )
    assert MediaProbeRepository(session).external_signal(library.id, FILM.path) == frozenset()


@pytest.mark.ffmpeg
def test_the_second_scan_after_a_sidecar_lands_reopens_nothing(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The signal has to settle, or every scan of every library re-inspects every sidecar.

    This is the half a "re-inspect when in doubt" implementation passes the test above with and
    fails here, and it is the same assertion `test_a_first_scan_inspects_every_file_and_a_second
    _inspects_none` makes one table across.
    """
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root)
    scan(library, session)

    before = MediaProbeRepository(session).external_signal(library.id, FILM.path)
    assert len(before) == 1, "the fixture's sidecar was not discovered at all"

    again = scan(library, session)
    assert again.inspected == 0, "a scan that changed nothing re-opened files anyway"
    assert MediaProbeRepository(session).external_signal(library.id, FILM.path) == before


@pytest.mark.ffmpeg
def test_a_rewritten_sidecar_is_inspected_again_and_the_film_is_not(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The two signals are independent in both directions, which is what "whatever the media
    file's own signal says" means. Here the sidecar moves and the film does not."""
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root)
    scan(library, session)
    signal_before = film_signal(session, library)

    sidecar = tree.sidecar_path_of(FILM, SIDECAR)
    sidecar.write_text(sidecar.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    scan(library, session)
    assert film_signal(session, library) == signal_before
    stored = MediaProbeRepository(session).external_signal(library.id, FILM.path)
    assert {one[1] for one in stored} == {sidecar.stat().st_size}, (
        "the sidecar's stored change signal did not follow the file"
    )


@pytest.mark.ffmpeg
def test_a_sidecar_belonging_to_no_film_is_discovered_by_nobody(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The stem guard, at scan level rather than in the naming table: a file whose name does not
    begin with a film's own is claimed by nothing, and one directory over is nobody's."""
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root)
    film = tree.path_of(FILM)
    shutil.copy(tree.sidecar_path_of(FILM, SIDECAR), film.with_name("Somebody Else.eng.srt"))
    shutil.copy(tree.sidecar_path_of(FILM, SIDECAR), tree.movies_root / f"{film.stem}.eng.srt")

    scan(library, session)
    stored = MediaProbeRepository(session).external_signal(library.id, FILM.path)
    assert {one[0] for one in stored} == {f"{Path(FILM.path).parent}/{SIDECAR.name}"}, (
        f"a file that is not this film's was claimed for it: {sorted(one[0] for one in stored)}"
    )


@pytest.mark.ffmpeg
def test_the_operator_facing_skip_count_does_not_move(
    session: OrmSession, media_files: BuiltMedia, tmp_path: Path
) -> None:
    """A subtitle produces no item, the report counts files that produced none, and discovering
    one is not a reason for that number to change. Counted with the file and without it."""
    tree = media_files.copy_into(tmp_path / "tree")
    library = a_library(session, tree.movies_root)
    with_file = scan(library, session)

    tree.sidecar_path_of(FILM, SIDECAR).unlink()
    without = scan(library, session)

    assert len(with_file.skipped) - len(without.skipped) == 1, (
        "the sidecar must be counted as skipped exactly once, with the file and not without it"
    )
