# SPDX-License-Identifier: GPL-3.0-or-later
"""The fixture tree as a reference instance is given it.

The entry point 010 plan section 6.6 names.

`tools/_reference.py` builds no tree: the caller hands it a root and it mounts that root read-only.
The harness therefore needs one place that says *which tree, in how many libraries, of which
collection types*, and this is it - in `tests/` rather than in `tools/` because the trees are the
ones `tests/fixtures/library/generate.py` and `tests/fixtures/media.py` already build, and a
second generator would disagree with the first the day either changed (plan section 6.6).

**Both worlds go across, and that is a measurement rather than a choice.** D-4 asked which world
a reference instance is given, and its default was *the media world extended with the structural
entries spec section 3.1 owes*. The default did not survive its own probe: the reference makes
**items** out of the 003 tree - 59 of them, 37 backed by a file none of its probers can open,
because it resolves an item from a path and probes it afterwards
`[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`. So the second branch is
the measured one: the 003 tree goes across as it stands, the media world goes across beside it,
and AC-2 compares both.

**Nothing here is a third fixture world.** It is the two declared trees, the collection types
their own declarations give each library, and one library with nothing in it - handed across the
mount unchanged. The fixed modification time both generators stamp is load-bearing across that
mount and a bind preserves it; a copy would not, and a fixture whose timestamps moved between the
two servers would put a difference into `DateCreated` on every item - a field the allowlist
excuses, which is worse than a visible failure because the noise would be invisible.

**Standard library only, and that is why the media matrix is where it is.** This module is
imported by `tools/probe_reference_scan.py`, a standalone program on the Python 3.9 floor where
nothing of this project's runtime environment exists - so the declarations and the generator it
reaches for must not need SQLAlchemy, the `atrium` package or an image library.
`tests/fixtures/media.py` was split at 010 T11 for exactly that: the scanned world it used to
carry is `tests/fixtures/media_world.py` now, and everything left is standard library and ffmpeg.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from tests.fixtures.library.generate import build as build_fixture_library
from tests.fixtures.library.manifest import LIBRARIES
from tests.fixtures.media import MOVIES_ROOT, MUSIC_ROOT, build_media_files

#: Where the media world lands under the mount. One subtree rather than two top-level directories,
#: because both worlds name their roots `Movies` and `Music` and a flat layout would have one
#: overwrite the other - silently, since `copytree` merges.
MEDIA_SUBTREE = "Decodable"

#: The library with nothing in it, and it is a named comparison rather than tidiness.
#: [behaviours section 5.7](../../docs/compatibility/behaviours.md) is the one place a folder's
#: played state can be asked at all - a `Series`, `Season`, `MusicArtist` or `MusicAlbum` with
#: nothing visible beneath it is not offered, so a `CollectionFolder` is the only shape that stays
#: in a sidebar with nothing behind it - and no reachable library has one, because creating one
#: means writing into somebody's server.
EMPTY_LIBRARY = "Empty"

#: What the empty library is declared as. Any collection type would do, since it holds nothing;
#: `movies` is named so that the reference is not asked to run a music scanner over an empty
#: directory, which would be a difference between the two servers about nothing.
EMPTY_COLLECTION_TYPE = "movies"


class ReferenceLibrary(NamedTuple):
    """One library the instance is asked to make over the mounted tree.

    `subpath` is where the library's root sits **under the mount**, which is what lets one bind
    mount carry every library. For the 003 tree it is the directory name `generate.build` writes
    each library to and for the media world it is the subtree above, so the two cannot drift: a
    library renamed in either declaration is renamed here by construction.
    """

    name: str
    collection_type: str
    subpath: str
    decodable: bool
    """Whether the files under it are media a prober can open.

    Declared rather than inferred, and it is what a reader of this tree on **Atrium's** side has to
    know: the 003 tree is paths and filler by design, so scanning it with a real prober costs an
    `ffprobe` launch per file to be told what the generator already says, while scanning the media
    world with a stub would compare an unexamined reading against a reference that examined
    everything (003 T18: an unexamined music file resolves from its *path*).
    """


def libraries() -> tuple[ReferenceLibrary, ...]:
    """Every library of both worlds, plus the empty one, in build order.

    Typed rather than mixed, and that is a measurement: a mixed-content library is what the
    reference makes when `AddVirtualFolder` is called without a collection type, and it is not what
    Atrium is being compared against - Atrium's own libraries carry the collection types these
    declarations give them, and a comparison that gave one server typed libraries and the other one
    untyped library would be measuring the typing rather than the scan.

    The media world's two libraries are named `Films` and `Tunes` because
    `tests/fixtures/media_world.py` already names them that on Atrium's side, and because they
    must not collide with the 003 tree's `Movies` and `Music`: a reading is keyed on the library's
    name, so two libraries under one name would be one library in the record.
    """
    structural = tuple(
        ReferenceLibrary(
            name=library.name,
            collection_type=library.collection_type,
            subpath=library.name,
            decodable=False,
        )
        for library in LIBRARIES
    )
    decodable = (
        ReferenceLibrary(
            name="Films",
            collection_type="movies",
            subpath=MEDIA_SUBTREE + "/" + MOVIES_ROOT,
            decodable=True,
        ),
        ReferenceLibrary(
            name="Tunes",
            collection_type="music",
            subpath=MEDIA_SUBTREE + "/" + MUSIC_ROOT,
            decodable=True,
        ),
    )
    empty = (
        ReferenceLibrary(
            name=EMPTY_LIBRARY,
            collection_type=EMPTY_COLLECTION_TYPE,
            subpath=EMPTY_LIBRARY,
            decodable=False,
        ),
    )
    return structural + decodable + empty


def build(destination: Path) -> Path:
    """Write both trees under `destination` and return the root a reference instance mounts.

    The root is `destination` itself: each library lands under a directory named by its own
    `subpath`, so the mount carries all of them.

    **The media world is copied rather than regenerated.** `build_media_files` encodes once into a
    cache keyed on the matrix and the ffmpeg version and publishes it with an atomic rename; the
    copy preserves each file's modification time, which is the fixed instant both generators stamp
    and the signal 003 detects a change with.
    """
    destination.mkdir(parents=True, exist_ok=True)
    build_fixture_library(destination)
    build_media_files().copy_into(destination / MEDIA_SUBTREE)
    (destination / EMPTY_LIBRARY).mkdir(parents=True, exist_ok=True)
    return destination
