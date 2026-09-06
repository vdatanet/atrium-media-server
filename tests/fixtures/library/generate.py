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

#: The instant every file's modification time is measured from. A fixed clock is not tidiness:
#: section 6.4 makes `(size, mtime_ns)` the change-detection signal, so a fixture built at the
#: current time would hand every scan a different signal and quietly make "the same tree scanned
#: twice produces the same items" untestable. 2026-01-01T00:00:00Z.
FIXED_MTIME_NS = 1_767_225_600_000_000_000

#: How far **before** that instant a file's own time may land. A year, so that every date in the
#: tree reads as an ordinary date, and so that ~100 files over ~31.5 million seconds practically
#: never land on the same one - `test_every_file_carries_its_own_instant` is what says they did
#: not, rather than this comment.
#:
#: **Before, and that direction is the whole of a defect this had on 2026-09-06**, the day the
#: spread was introduced. It ran *forwards* from `FIXED_MTIME_NS`, which is 2026-01-01, so on any
#: day inside that year part of the tree was stamped in the **future** - 17 files of 78 when it was
#: measured. A reference server clamps a future modification time to the moment of its scan, so
#: those items came back carrying a wall clock rather than the fixed instant they were given: the
#: exact non-reproducibility the per-file stamp was written to remove, re-entering through the one
#: door nobody had looked at. It was also a fixture that changed with the **calendar** - the set of
#: future files shrinks by one every few days - so two runs on two days disagreed for no reason
#: either server owned.
MTIME_SPREAD_SECONDS = 365 * 24 * 3600


def mtime_ns_for(key: str) -> int:
    """One fixed instant per file, and a **different** one for each - both halves load-bearing.

    **Fixed**, for the reason `FIXED_MTIME_NS` gives: the change signal is `(size, mtime_ns)`, so a
    tree stamped with the clock makes "the same tree scanned twice" untestable.

    **Different**, from 2026-09-06, and that half was bought at a price this project paid twice
    before spotting it. Every file carried *one* instant, so every date ordering over the fixture
    was one enormous tie on **both** servers - and a window over a tie, which is what
    `GET /Items/Latest` is, then holds whichever rows the tie-break happened to favour. It hid a
    real defect (003 section 3.9: `DateCreated` was the scan's clock, and a tree of identical times
    could not tell that from the file's) and it made a differential run's `/Items/Latest`
    incomparable between two servers for a reason that was the fixture's rather than either
    server's (010's list).

    **Keyed on the path and not on a position in a list**, deliberately: an ordinal would mean
    inserting one declaration moved every file after it, and a rescan would then report a library
    of unchanged files as changed. A digest of the path moves exactly the file whose path moved.
    """
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    offset = int.from_bytes(digest[:6], "big") % MTIME_SPREAD_SECONDS
    # **Subtracted, never added.** See `MTIME_SPREAD_SECONDS`: a tree stamped into the future is a
    # tree a reference server re-stamps with its own clock, which is the thing this function is for.
    return FIXED_MTIME_NS - offset * 1_000_000_000


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


#: The kinds that get no bytes at all, and they are two rather than one. EMPTY is an incomplete
#: copy - a file that is empty. MARKER is a file whose emptiness *is* its meaning: a non-empty
#: `.ignore` is read as gitignore-style rules and excludes nothing, so writing the banner into one
#: turned the tree's exclusion case into a rule set matching nothing (010 T10, T11).
ZERO_BYTE_KINDS = (Kind.EMPTY, Kind.MARKER)


def size_of(entry: Entry) -> int:
    """How many bytes this entry gets. Derived from its path, so it is stable and it varies."""
    if entry.kind in ZERO_BYTE_KINDS:
        return 0
    spread = hashlib.sha256(f"size:{entry.path}".encode()).digest()[0]
    return len(_head(entry)) + MINIMUM_BODY + spread * 4


def content_of(entry: Entry) -> bytes:
    """The exact bytes this entry gets, as a pure function of its declared path and kind."""
    if entry.kind in ZERO_BYTE_KINDS:
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
    # Keyed on the library's name and the entry's path within it, which is what stays the same
    # between two builds and between two mount points - never on the absolute path, which is a
    # temporary directory in this suite and `/fixture` inside a reference instance.
    stamped = mtime_ns_for(f"{root.name}/{entry.path}")
    os.utime(target, ns=(stamped, stamped))
