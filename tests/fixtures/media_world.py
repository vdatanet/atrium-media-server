# SPDX-License-Identifier: GPL-3.0-or-later
"""The generated media tree, scanned by the real 003 pipeline into a database.

**Split out of `tests/fixtures/media.py` by 010 T11, and the split is what makes that module
usable at all from the harness.** The fixture the reference instance is given is now *both*
worlds (010 plan section 6.6, D-4), so `tests/fixtures/reference_tree.py` has to build the media
matrix - and that module is imported by `tools/probe_reference_scan.py`, a standalone program on
the Python 3.9 floor where none of this project's runtime environment exists. Everything that
needs SQLAlchemy, a session and the `atrium` package therefore lives here rather than beside the
declarations, and `media.py` is standard library only.

Nothing else moved: the same class and the same builder, imported from the same place by every
fixture and test that used them, through `tests/fixtures/media.py`'s own re-export.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.orm import Session as OrmSession

from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import CollectionType, Item, ItemType
from atrium.domain.library import Library
from atrium.library.config import normalise_root
from atrium.library.scan import scan
from tests.fixtures.media import (
    MOVIES_LIBRARY_ID,
    MUSIC_LIBRARY_ID,
    BuiltMedia,
    MediaFile,
)


@dataclass(frozen=True)
class ScannedMediaWorld:
    """Two libraries, scanned by the real 003 pipeline over the generated tree.

    Scanned rather than seeded, unlike `query.py`: the whole point of this world is that the rows
    and the files agree, and a seeded row is a statement about a file nobody read.
    """

    files: BuiltMedia
    movies: Library
    music: Library
    items: Mapping[str, Item]
    """Every item both scans produced, keyed by identifier."""

    def of(self, one: MediaFile) -> Item:
        """The item this file backs - found through its sources, never assumed from its name."""
        wanted = one.path
        for candidate in self.items.values():
            if any(source.relative_path == wanted for source in candidate.sources):
                return candidate
        raise KeyError(f"nothing scanned from {wanted!r}")

    def by_type(self, item_type: ItemType) -> tuple[Item, ...]:
        return tuple(
            item
            for item in self.items.values()
            if item.type is item_type and item.removed_at is None
        )


def build_scanned_media_world(session: OrmSession, files: BuiltMedia) -> ScannedMediaWorld:
    """Declare the two libraries over the generated tree and scan them, in the caller's session.

    Fixed library identifiers, like every fixture world here, so two builds derive the same items
    (Principle VII). `config.create` would mint a random one.
    """
    libraries = LibraryRepository(session)
    movies = libraries.add(
        Library(
            id=MOVIES_LIBRARY_ID,
            name="Films",
            collection_type=CollectionType.MOVIES,
            roots=(normalise_root(str(files.movies_root)),),
        )
    )
    music = libraries.add(
        Library(
            id=MUSIC_LIBRARY_ID,
            name="Tunes",
            collection_type=CollectionType.MUSIC,
            roots=(normalise_root(str(files.music_root)),),
        )
    )
    for library in (movies, music):
        scan(library, session)

    items = ItemRepository(session)
    return ScannedMediaWorld(
        files=files,
        movies=movies,
        music=music,
        items={**items.by_library(movies.id), **items.by_library(music.id)},
    )


__all__ = ["ScannedMediaWorld", "build_scanned_media_world"]
