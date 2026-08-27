# SPDX-License-Identifier: GPL-3.0-or-later
"""The seam, live: a scan that reads the files rather than only their names.

003 shipped `MetadataSource` answering nothing, so a music library was resolved entirely from its
paths and a well-tagged FLAC was filed under whatever directory it happened to sit in. This is the
test that says that stopped being true - AC-5's groundwork, one scan below the integration level
where T10 holds the criterion itself.

**And the test that says nothing else changed.** 003's whole suite runs against the same scanner,
including its change-detection tests, so the seam going live is proved not to have broken the one
guarantee it hangs off: an unchanged file is never opened.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from mutagen.flac import FLAC
from sqlalchemy import Engine, select

from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import LibraryRepository
from atrium.domain.items import ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.naming import PATH_ONLY
from atrium.library.scan import scan
from atrium.metadata.tags import TagSource
from tests.conftest import data_dir

TEMPLATE = Path(__file__).resolve().parents[1] / "fixtures" / "metadata" / "audio" / "template.flac"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


def a_track(root: Path, relative: str, **tags: str) -> Path:
    """A real FLAC at `relative`, carrying `tags`, under a directory that says something else."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE, path)
    opened = FLAC(path)
    for name, value in tags.items():
        opened[name] = [value]
    opened.save()
    return path


def a_music_library(engine: Engine, root: Path) -> Library:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return config.create(LibraryRepository(db), "Music", "music", (str(root),))


def scanned(engine: Engine, library: Library, **kwargs: object) -> list[models.Item]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        scan(library, db, **kwargs)  # type: ignore[arg-type]
    with session_scope(factory) as db:
        return list(db.execute(select(models.Item)).scalars())


def test_a_tagged_track_hangs_under_the_album_its_tags_name(tmp_path: Path, engine: Engine) -> None:
    """AC-5's groundwork. The directory says `Some Folder`; the tags say `The Real Album` by
    `The Real Artist`, and the tags win - which is the whole reason spec section 3.1 inverts the
    first two sources for music."""
    root = tmp_path / "music"
    a_track(
        root,
        "Some Folder/Another Folder/01 - First.flac",
        album="The Real Album",
        albumartist="The Real Artist",
        title="The Real Title",
    )
    items = scanned(engine, a_music_library(engine, root))

    by_type = {kind: [item.name for item in items if item.type == kind] for kind in ItemType}
    assert by_type[ItemType.MUSIC_ALBUM] == ["The Real Album"]
    assert by_type[ItemType.MUSIC_ARTIST] == ["The Real Artist"]
    assert by_type[ItemType.AUDIO] == ["The Real Title"]


def test_the_same_tree_without_a_reader_resolves_from_its_directories(
    tmp_path: Path, engine: Engine
) -> None:
    """`PATH_ONLY` is still what a server with no reader runs on, and it still works - which is
    what makes the test above a statement about the *seam* rather than about the fixture."""
    root = tmp_path / "music"
    a_track(
        root,
        "Some Folder/Another Folder/01 - First.flac",
        album="The Real Album",
        albumartist="The Real Artist",
        title="The Real Title",
    )
    items = scanned(engine, a_music_library(engine, root), source=PATH_ONLY)

    by_type = {kind: [item.name for item in items if item.type == kind] for kind in ItemType}
    assert by_type[ItemType.MUSIC_ALBUM] == ["Another Folder"]
    assert by_type[ItemType.MUSIC_ARTIST] == ["Some Folder"]
    assert by_type[ItemType.AUDIO] == ["First"]


def test_an_untagged_track_still_resolves_from_its_path(tmp_path: Path, engine: Engine) -> None:
    """The default reader must not make an untagged library worse than the path-only one."""
    root = tmp_path / "music"
    path = root / "Some Folder/Another Folder/01 - First.flac"
    path.parent.mkdir(parents=True)
    shutil.copy(TEMPLATE, path)
    items = scanned(engine, a_music_library(engine, root))

    by_type = {kind: [item.name for item in items if item.type == kind] for kind in ItemType}
    assert by_type[ItemType.MUSIC_ALBUM] == ["Another Folder"]
    assert by_type[ItemType.AUDIO] == ["First"]


def test_rescanning_an_unchanged_library_produces_the_same_tree(
    tmp_path: Path, engine: Engine
) -> None:
    """003's signal gating, through the live seam. The failure this guards against is the one 003
    T18 found: an unexamined music file resolves from its *path*, so a second scan that skipped
    the read would hang the same track under a second album named after its directory - silently
    doubling every album in the library.
    """
    root = tmp_path / "music"
    a_track(
        root,
        "Some Folder/Another Folder/01 - First.flac",
        album="The Real Album",
        albumartist="The Real Artist",
    )
    library = a_music_library(engine, root)
    first = {(item.id, item.type, item.name) for item in scanned(engine, library)}
    second = {(item.id, item.type, item.name) for item in scanned(engine, library)}
    assert first == second
    assert len([one for one in second if one[1] == ItemType.MUSIC_ALBUM]) == 1


def test_an_unchanged_file_is_never_opened_on_the_second_scan(
    tmp_path: Path, engine: Engine
) -> None:
    """The constraint 003 wrote down for this seam, asserted rather than assumed: a source handed
    to a second scan is not consulted for a file whose `(size, mtime_ns)` has not moved."""
    root = tmp_path / "music"
    a_track(root, "Artist/Album/01 - First.flac", album="The Real Album")
    library = a_music_library(engine, root)

    scanned(engine, library)

    watched = TagSource([root])
    scanned(engine, library, source=watched)
    assert watched.opened == 0, "the second scan opened a file whose signal had not moved"


def test_a_deep_scan_does_open_it(tmp_path: Path, engine: Engine) -> None:
    """`deep` empties the unchanged set, which is the whole of what `deep` means - and it is the
    escape hatch for exactly the case the signal cannot see: a library whose tags were rewritten
    in place by a tool that preserved both size and modification time."""
    root = tmp_path / "music"
    a_track(root, "Artist/Album/01 - First.flac", album="The Real Album")
    library = a_music_library(engine, root)
    scanned(engine, library)

    watched = TagSource([root])
    scanned(engine, library, source=watched, deep=True)
    assert watched.opened == 1


def test_a_file_that_is_not_really_audio_does_not_stop_a_scan(
    tmp_path: Path, engine: Engine
) -> None:
    """003's own fixture library is full of these. The scan walks them, the reader warns, and the
    item resolves from its path (spec section 3.3)."""
    root = tmp_path / "music"
    impostor = root / "Artist/Album/01 - First.flac"
    impostor.parent.mkdir(parents=True)
    impostor.write_bytes(b"atrium synthetic fixture - not media\n" + b"\0" * 600)
    items = scanned(engine, a_music_library(engine, root))
    assert [item.name for item in items if item.type == ItemType.AUDIO] == ["First"]
