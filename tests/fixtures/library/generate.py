# SPDX-License-Identifier: GPL-3.0-or-later
"""Materialise the declared fixture library onto disk, deterministically.

Two builds produce byte-identical files, because every byte is a function of the path it is
written to and of nothing else - no clock, no randomness, no counter, no environment. That is what
makes a difference in a scan result mean a difference in the *scanner* rather than a difference in
the fixture, which is the whole reason the fixture is generated instead of committed
(plan section 8.1).

**These are not decodable media, and 003 has no use for one.** Probing is 008, embedded tags are
004, and nothing in this feature opens a media file: what a 003 test reads from a fixture is its
path, its extension, and a size that changes when the test changes it. Muxing a second of colour
bars would have added a tool outside the locked dependency set and made "byte-identical across two
builds" depend on that tool's version rather than on this file.

Every generated file says what it is in its first line, so nobody who opens one has to wonder
whether the repository grew a copyrighted work.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from tests.fixtures.library.manifest import LIBRARIES, Entry, Kind, Library

#: First line of every generated file. Present so that the answer to "is this somebody's film?" is
#: visible in the first sixty bytes rather than inferred from this module.
BANNER = b"atrium synthetic fixture - not media, not a copyrighted work\n"

#: The smallest body written after the banner. Big enough that a size is a meaningful signal for
#: the change detection of section 6.4, small enough that the whole tree is trivial.
MINIMUM_BODY = 512

#: Every file gets this modification time. A fixed clock is not tidiness: section 6.4 makes
#: `(size, mtime_ns)` the change-detection signal, so a fixture built at the current time would
#: hand every scan a different signal and quietly make "the same tree scanned twice produces the
#: same items" untestable. 2026-01-01T00:00:00Z.
FIXED_MTIME_NS = 1_767_225_600_000_000_000


@dataclass(frozen=True)
class BuiltLibrary:
    root: Path
    library: Library

    @property
    def collection_type(self) -> str:
        return self.library.collection_type

    def path_of(self, entry_path: str) -> Path:
        """The absolute path of one declared entry, for a test that wants to delete or touch it."""
        return self.root.joinpath(*entry_path.split("/"))


@dataclass(frozen=True)
class BuiltFixture:
    base: Path
    libraries: tuple[BuiltLibrary, ...]

    def of(self, collection_type: str) -> BuiltLibrary:
        for built in self.libraries:
            if built.collection_type == collection_type:
                return built
        raise KeyError(f"no {collection_type!r} library in the fixture")


def size_of(entry: Entry) -> int:
    """How many bytes this entry gets. Derived from its path, so it is stable and it varies."""
    if entry.kind is Kind.EMPTY:
        return 0
    spread = hashlib.sha256(f"size:{entry.path}".encode()).digest()[0]
    return len(_head(entry)) + MINIMUM_BODY + spread * 4


def content_of(entry: Entry) -> bytes:
    """The exact bytes this entry gets, as a pure function of its declared path and kind."""
    if entry.kind is Kind.EMPTY:
        return b""
    if entry.path.endswith(".nfo"):
        return _sidecar(entry)

    head = _head(entry)
    filler = hashlib.sha256(entry.path.encode()).digest()
    body_length = size_of(entry) - len(head)
    body = (filler * (1 + body_length // len(filler)))[:body_length]
    return head + body


def _head(entry: Entry) -> bytes:
    return BANNER + entry.path.encode("utf-8") + b"\n"


def _sidecar(entry: Entry) -> bytes:
    """A `.nfo` is a real sidecar rather than filler, because 004 will read these for content.

    Deterministic like everything else: the title is the file's own stem.
    """
    stem = entry.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {BANNER.decode('utf-8').strip()} -->\n"
        f"<metadata><title>{stem}</title><path>{entry.path}</path></metadata>\n"
    ).encode()


def build(destination: Path, libraries: tuple[Library, ...] = LIBRARIES) -> BuiltFixture:
    """Write the whole declared tree under `destination` and say where each root landed.

    Safe to call twice into two directories; the results compare byte for byte. Calling it twice
    into the *same* directory rewrites the same bytes, which is also what a test wants when it is
    checking that a rescan finds nothing new.
    """
    built = []
    for library in libraries:
        root = destination / library.name
        root.mkdir(parents=True, exist_ok=True)
        for entry in library.entries:
            _write(root, entry)
        built.append(BuiltLibrary(root=root, library=library))
    return BuiltFixture(base=destination, libraries=tuple(built))


def _write(root: Path, entry: Entry) -> None:
    # A trailing slash declares a directory that stays empty - a season with no episodes is a
    # normal thing to find, and the tree has to be able to say so.
    if entry.path.endswith("/"):
        root.joinpath(*entry.path.rstrip("/").split("/")).mkdir(parents=True, exist_ok=True)
        return

    target = root.joinpath(*entry.path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content_of(entry))
    os.utime(target, ns=(FIXED_MTIME_NS, FIXED_MTIME_NS))
