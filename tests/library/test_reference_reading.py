# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-2: both servers, pointed at the same built fixture, over one recorded reading.

**This is the criterion that could not be a test, made into one.** 010 plan section 8 mapped AC-2
to *"`tools/probe_reference_scan.py`, by hand — the one criterion that cannot be a test: it needs
both servers"*, and the task list's gate found that it therefore could not be mapped at all:
`tests/conformance/test_acceptance.py` resolves every criterion's proof as `module:function`
through `importlib`, and a `tools/` module is reached by path and never as a package. A criterion
whose only proof is a command somebody remembers to run is a criterion with no proof.

So the probe **records** what the reference makes of the fixture tree —
`docs/compatibility/reference-fixture-reading.json`, with its own citation inside it — and this
module compares **Atrium's** scan of the same tree against that record. Both servers are still
needed to *make* the reading, which is what the probe is for and what a version bump re-runs; what
is no longer needed to *check* it is a second server. Nothing here opens a socket, and no Jellyfin
exists anywhere near the job that runs it.

**The comparison is not an equality, and saying so is the point.** The two servers disagree over
this tree in forty-seven places, every one of them written down below with the reason it is there.
A difference that is not in the table fails the test, which is what makes this a measurement of
Atrium's scan rather than a restatement of it: change a name derivation and a row moves; refresh
the record against a new reference and a row moves. Deciding what Atrium *does* about any of them
belongs to the feature that owns the behaviour (010 spec section 2), not here.

**Six libraries, because D-4 chose both worlds.** The tree the instance is given is the 003 tree
of paths and filler, the media world of files a prober can open, and one library with nothing in
it at all - `tests/fixtures/reference_tree.py` composes the three and this module reads whatever it
composes. That is what makes the media libraries worth having here rather than only in 008's own
tests: over files both servers can actually open, the disagreement is **five names and nothing
else**, and every remaining difference in this module is about a tree neither server can decode.

**Marked `ffmpeg`, and that is new with the media world.** Building the tree means encoding it, so
the comparison is skipped where the binaries are absent and installed by CI, which is where AC-2 is
asserted. Nothing here opens a socket either way.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.library import config
from atrium.library.scan import scan
from tests.conftest import data_dir, not_media
from tests.fixtures.reference_tree import build, libraries

READING = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "compatibility"
    / "reference-fixture-reading.json"
)


# ------------------------------------------------------------------------------------------
# What the two servers disagree about, and why each row is here
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Renaming:
    """One file both servers made an item of, under two different names."""

    library: str
    file: str
    reference: str
    atrium: str
    why: str


#: A file the **reference** makes an item of and Atrium does not. **One row, and it was two.**
#:
#: The row that went is `Excluded/An Excluded Film (2000).mkv`, and it went because the fixture was
#: repaired rather than because a server changed. T10 recorded it as a defect in the tree: an
#: `.ignore` marker excludes a directory outright only when it is **empty**, and a non-empty one is
#: read as gitignore-style rules
#: `[source: Emby.Server.Implementations/Library/DotIgnoreIgnoreRule.cs:58-66 @ v10.11.11]`, so the
#: banner `generate.py` writes into every declared entry made the marker a rule set matching
#: nothing. The entry is `Kind.MARKER` now, it is zero bytes, and **the two servers agree** - which
#: is the case the entry was written for, exercised for the first time on the side it was written
#: for (010 T11).
ONLY_THE_REFERENCE_MAKES_AN_ITEM_OF = {
    (
        "Movies",
        "An Incomplete Copy (2000).mkv",
    ): "A zero-byte file is an incomplete copy and produces no item here (003 spec section 3.2); "
    "the reference makes a Movie of it. Atrium's rule is deliberate and the difference is real",
}

#: A file **Atrium** makes an item of and the reference does not. Empty, and worth stating: over
#: this tree Atrium never invents an item the reference declines to make.
ONLY_ATRIUM_MAKES_AN_ITEM_OF: dict[tuple[str, str], str] = {}

#: The same file, a different name. Three rules produce all twenty.
_WHOLE_STEM = (
    "The reference names an episode and a track after the **whole filename**; Atrium names it "
    "after the part its own parse calls the title (003 spec section 3.4). Same item, same file, "
    "different label"
)
_YEAR_AND_PUNCTUATION = (
    "Atrium's name derivation strips a trailing year, collapses punctuation and trims whitespace; "
    "the reference keeps what the path says"
)
_FOLDER_WITH_A_YEAR = (
    "A film in a folder of its own: the reference names the item after the **folder**, year and "
    "all, and Atrium strips the trailing year. **These five are the whole disagreement over files "
    "both servers can open** - same items, same files, same types, five labels - which is what "
    "makes the media libraries worth comparing rather than only worth serving"
)

NAMED_DIFFERENTLY = (
    Renaming(
        "Movies",
        "  Padded   (1999).mkv",
        "  Padded",
        "Padded",
        "Atrium trims the leading whitespace out of the name; the reference keeps it. The entry "
        "exists for the sort-name artefact of 003 AC-13, and the *name* is where the two servers "
        "part",
    ),
    Renaming("Movies", "S.W.A.T. (2003).mkv", "S.W.A.T.", "S W A T", _YEAR_AND_PUNCTUATION),
    Renaming(
        "Movies",
        "The Long Film (1998)/The Long Film (1998) - part1.mkv",
        "The Long Film (1998)",
        "The Long Film",
        "Both make **one** item of the two parts, which is 003 AC-4 holding on both servers. The "
        "reference names it after the folder including the year; Atrium strips the year",
    ),
    Renaming(
        "Shows",
        "24/Season 01/24 - S01E01 - 12-00 AM.mkv",
        "24 - S01E01 - 12-00 AM",
        "12-00 AM",
        _WHOLE_STEM,
    ),
    Renaming(
        "Shows",
        "The Series/Season 01/The Series - S01E01 - Pilot.mkv",
        "The Series - S01E01 - Pilot",
        "Pilot",
        _WHOLE_STEM,
    ),
    Renaming(
        "Shows",
        "The Series/Season 01/The Series - S01E02-E03 - Two Parter.mkv",
        "The Series - S01E02-E03 - Two Parter",
        "Two Parter",
        _WHOLE_STEM,
    ),
    Renaming(
        "Shows",
        "The Series/Season 01/The Series - S01E04 - Old Transfer.avi",
        "The Series - S01E04 - Old Transfer",
        "Old Transfer",
        _WHOLE_STEM,
    ),
    Renaming(
        "Shows",
        "The Series/Season 02/The Series - S02E99 - Beyond Any Real Count.mp4",
        "The Series - S02E99 - Beyond Any Real Count",
        "Beyond Any Real Count",
        _WHOLE_STEM,
    ),
    Renaming(
        "Shows",
        "The Series/Specials/The Series - S00E01 - A Special.mkv",
        "The Series - S00E01 - A Special",
        "A Special",
        _WHOLE_STEM,
    ),
    Renaming(
        "Shows",
        "The Series/The Series - S02E01 - No Season Directory.mkv",
        "The Series - S02E01 - No Season Directory",
        "No Season Directory",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "The Artist/Double Album/CD1/01 - First Disc.flac",
        "01 - First Disc",
        "First Disc",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "The Artist/Double Album/CD2/01 - Second Disc.flac",
        "01 - Second Disc",
        "Second Disc",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "The Artist/First Album (2001)/01 - Opening.flac",
        "01 - Opening",
        "Opening",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "The Artist/First Album (2001)/02 - Second.flac",
        "02 - Second",
        "Second",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "The Artist/Second Album/01 - In Another Container.m4a",
        "01 - In Another Container",
        "In Another Container",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "The Artist/Second Album/02 - And Another.dsf",
        "02 - And Another",
        "And Another",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "The Artist/spandau_ballet-through_the_barricades/01 - Tagged Differently.flac",
        "01 - Tagged Differently",
        "Tagged Differently",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "Various Artists/A Compilation (1999)/01 - By One Artist.flac",
        "01 - By One Artist",
        "By One Artist",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "Various Artists/A Compilation (1999)/02 - By Another.flac",
        "02 - By Another",
        "By Another",
        _WHOLE_STEM,
    ),
    Renaming(
        "Music",
        "Various Artists/A Compilation (1999)/03 - By A Third.flac",
        "03 - By A Third",
        "By A Third",
        _WHOLE_STEM,
    ),
    Renaming(
        "Films",
        "The Legacy Encoding (2010)/The Legacy Encoding (2010).mkv",
        "The Legacy Encoding (2010)",
        "The Legacy Encoding",
        _FOLDER_WITH_A_YEAR,
    ),
    Renaming(
        "Films",
        "The Long Take (2005)/The Long Take (2005).mp4",
        "The Long Take (2005)",
        "The Long Take",
        _FOLDER_WITH_A_YEAR,
    ),
    Renaming(
        "Films",
        "The Planted Poster (2011)/The Planted Poster (2011).mp4",
        "The Planted Poster (2011)",
        "The Planted Poster",
        _FOLDER_WITH_A_YEAR,
    ),
    Renaming(
        "Films",
        "The Two Parter (2006)/The Two Parter (2006) - part1.mkv",
        "The Two Parter (2006)",
        "The Two Parter",
        _FOLDER_WITH_A_YEAR
        + ". Both make **one** item of the two parts, on files a prober really opens",
    ),
    Renaming(
        "Films",
        "The Unconvertible (2009)/The Unconvertible (2009).mkv",
        "The Unconvertible (2009)",
        "The Unconvertible",
        _FOLDER_WITH_A_YEAR,
    ),
)

#: Container items - the ones no file backs - by `(library, type, name)`. A container is compared
#: without a path deliberately: the reference gives a season and an album the **directory** they
#: were resolved from, and in this project a path belongs to a media source, so a container has
#: none. Comparing them on a value only one side has would report every container as a difference.
CONTAINERS_ONLY_THE_REFERENCE_HAS = {
    (
        "Movies",
        "Folder",
        "Movies",
    ): "The library's own root. The reference calls it `Folder` in a recursive item listing and "
    "`CollectionFolder` in `/UserViews` - two names for one row, from the same server - where "
    "Atrium calls it `CollectionFolder` everywhere. A representation difference rather than a "
    "scan one, and T8's sweep is what compares it on the wire",
    ("Shows", "Folder", "Shows"): "The same row, in the series library",
    ("Music", "Folder", "Music"): "The same row, in the music library",
    (
        "Shows",
        "Season",
        "Season 3",
    ): "An **empty** season directory. The reference makes a Season of it; Atrium makes nothing, "
    "because nothing under it resolved. 003 spec section 3.4 admits the empty directory as normal "
    "and says nothing about giving it an item",
    (
        "Shows",
        "Season",
        "Season Unknown",
    ): "A **virtual** season, invented for the episode whose season nothing names (`blob.mkv`). "
    "It is the only row in the reading with no path at all - the shape this feature's own gate "
    "found on a virtual season of a real library. Atrium files that episode under the season its "
    "directory names instead",
    (
        "Music",
        "Folder",
        "CD1",
    ): "The reference makes a plain `Folder` of a disc directory as well as folding its tracks "
    "into the one album; Atrium makes the album and not the folder. Both agree there is one "
    "`Double Album` (003 AC-8)",
    ("Music", "Folder", "CD2"): "The second disc, for the same reason",
    (
        "Music",
        "MusicAlbum",
        "A Compilation (1999)",
    ): "Named with the year the directory carries; Atrium strips it. Paired with the Atrium row "
    "below - a container cannot be matched on a path, so a renaming shows as two rows",
    (
        "Music",
        "MusicAlbum",
        "First Album (2001)",
    ): "The reference names the album after its directory. Atrium names it `album`, from the "
    "`<title>` of the `album.nfo` beside the tracks - which the reference did **not** read, "
    "although both servers read `tvshow.nfo` and agree the series is called `tvshow`. Paired with "
    "the Atrium row below",
    (
        "Films",
        "Folder",
        "Movies",
    ): "The media library's own root, and it exposes something the 003 tree could not: **the "
    "reference names that row after the DIRECTORY and not after the library**. This library is "
    "called `Films` and its root is `Decodable/Movies`, so the row comes back as `Movies` where "
    "`/UserViews` answers `Films` - three names for one row from one server, where the 003 tree's "
    "directory and library names are equal and the difference was invisible",
    ("Tunes", "Folder", "Music"): "The same row, in the media music library rooted at "
    "`Decodable/Music`",
    (
        "Tunes",
        "MusicArtist",
        "Sounds",
    ): "**The reference takes a music artist from the directory even when the file's tags name "
    "another.** The one track here is tagged `The Artist` and sits under "
    "`Sounds/Untitled Folder/`, and the reference's album agrees with the tag while its artist "
    "does not - so the two readings "
    "are not simply 'tags' against 'paths' on either side. Atrium takes both from the tags "
    "(003 T18). The fixture was built to disagree with itself for exactly this reason",
}

CONTAINERS_ONLY_ATRIUM_HAS = {
    ("Movies", "CollectionFolder", "Movies"): "The other half of the library-root row above",
    ("Shows", "CollectionFolder", "Shows"): "The other half of the library-root row above",
    ("Music", "CollectionFolder", "Music"): "The other half of the library-root row above",
    ("Music", "MusicAlbum", "A Compilation"): "The other half of the compilation's renaming",
    ("Music", "MusicAlbum", "album"): "The other half of the first album's renaming",
    ("Films", "CollectionFolder", "Films"): "The other half of the library-root row above, and "
    "the half that carries the library's own name",
    ("Tunes", "CollectionFolder", "Tunes"): "The other half of the library-root row above",
    ("Tunes", "MusicArtist", "The Artist"): "The other half of the music-artist row above",
    (
        "Empty",
        "CollectionFolder",
        "Empty",
    ): "**A library with nothing in it is nothing at all to the reference**: it answers zero rows "
    "for the empty library - not even the root `Folder` it gives every other one - where Atrium "
    "carries its `CollectionFolder`. Measured for the first time here, because no reachable "
    "library is empty and making one means writing into somebody's server. It is the shape "
    "behaviours section 5.7 needs and could not be asked of before, and this row is the scan half "
    "of it; the played state is the named comparison T12 runs",
}


# ------------------------------------------------------------------------------------------
# The two readings
# ------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recorded() -> dict[str, object]:
    return json.loads(READING.read_text(encoding="utf-8"))


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def atrium(engine: Engine, tmp_path: Path) -> dict[str, list[tuple[str, str, str | None]]]:
    """Atrium's own scan of the same tree, through the real 003 pipeline.

    The tree is built by the entry point the probe builds it with, so a change to either
    declaration moves both sides at once rather than making this test disagree with the record for
    a reason that is not a difference between two servers.

    **The prober follows the library and not the suite's convenience.** The 003 tree is paths and
    filler by design, so a real prober there costs an `ffprobe` launch per file to be told what the
    generator already says; the media world is real media, and scanning it with a stub would put
    Atrium's *unexamined* reading against a reference that examined everything - 003 T18's finding,
    where an unexamined music file resolves from its path and hangs under an album named after its
    folder. `ReferenceLibrary.decodable` is what says which is which.
    """
    root = build(tmp_path / "tree")
    factory = session_factory(engine)
    reading: dict[str, list[tuple[str, str, str | None]]] = {}
    for spec in libraries():
        with session_scope(factory) as db:
            library = config.create(
                LibraryRepository(db),
                spec.name,
                spec.collection_type,
                (str(root / spec.subpath),),
            )
        with session_scope(factory) as db:
            scan(library, db, prober=None if spec.decodable else not_media)
        with session_scope(factory) as db:
            items = ItemRepository(db).by_library(library.id)
        rows = list(items.values())
        reading[spec.name] = sorted(
            (
                item.type.value,
                item.name,
                item.sources[0].relative_path if item.sources else None,
            )
            for item in rows
        )
    return reading


def rows_of(library: dict[str, object]) -> list[tuple[str, str, str | None]]:
    return [
        (str(entry["type"]), str(entry["name"]), entry["file"])  # type: ignore[index]
        for entry in library["items"]  # type: ignore[union-attr]
    ]


def by_file(
    rows: list[tuple[str, str, str | None]],
) -> dict[str, tuple[str, str]]:
    return {file: (kind, name) for kind, name, file in rows if file is not None}


def containers(rows: list[tuple[str, str, str | None]]) -> Counter[tuple[str, str]]:
    return Counter((kind, name) for kind, name, file in rows if file is None)


# ------------------------------------------------------------------------------------------
# AC-2
# ------------------------------------------------------------------------------------------


@pytest.mark.ffmpeg
def test_atriums_scan_of_the_fixture_matches_the_recorded_reference_reading(
    recorded: dict[str, object],
    atrium: dict[str, list[tuple[str, str, str | None]]],
) -> None:
    """AC-2, in the only form that can run where there is no Jellyfin.

    Every difference between the two readings is one of the rows declared above, and every
    declared row is a difference that is still there. Both halves matter: the first stops a change
    to Atrium's scan passing unnoticed, and the second stops the table outliving the difference it
    describes.
    """
    unexpected: list[str] = []
    stale: list[str] = []

    for library in recorded["libraries"]:  # type: ignore[union-attr]
        name = str(library["name"])  # type: ignore[index]
        theirs = rows_of(library)  # type: ignore[arg-type]
        mine = atrium[name]

        their_files, my_files = by_file(theirs), by_file(mine)
        for file in sorted(set(their_files) - set(my_files)):
            if (name, file) not in ONLY_THE_REFERENCE_MAKES_AN_ITEM_OF:
                unexpected.append(f"{name}: only the reference makes an item of {file!r}")
        for file in sorted(set(my_files) - set(their_files)):
            if (name, file) not in ONLY_ATRIUM_MAKES_AN_ITEM_OF:
                unexpected.append(f"{name}: only Atrium makes an item of {file!r}")

        renamings = {(row.library, row.file): row for row in NAMED_DIFFERENTLY}
        for file in sorted(set(their_files) & set(my_files)):
            if their_files[file] == my_files[file]:
                continue
            row = renamings.get((name, file))
            if row is None:
                unexpected.append(
                    f"{name}: {file!r} is {their_files[file]} there and {my_files[file]} here"
                )
            elif (row.reference, row.atrium) != (their_files[file][1], my_files[file][1]):
                unexpected.append(
                    f"{name}: {file!r} was recorded as {row.reference!r} versus {row.atrium!r} "
                    f"and is now {their_files[file][1]!r} versus {my_files[file][1]!r}"
                )
            elif their_files[file][0] != my_files[file][0]:
                unexpected.append(
                    f"{name}: {file!r} is a {their_files[file][0]} there and a "
                    f"{my_files[file][0]} here, which no row excuses"
                )

        their_containers, my_containers = containers(theirs), containers(mine)
        for kind, container in sorted((their_containers - my_containers).elements()):
            if (name, kind, container) not in CONTAINERS_ONLY_THE_REFERENCE_HAS:
                unexpected.append(f"{name}: only the reference has {kind} {container!r}")
        for kind, container in sorted((my_containers - their_containers).elements()):
            if (name, kind, container) not in CONTAINERS_ONLY_ATRIUM_HAS:
                unexpected.append(f"{name}: only Atrium has {kind} {container!r}")

    # The other direction: a declared difference that is no longer one.
    for library_name, file in ONLY_THE_REFERENCE_MAKES_AN_ITEM_OF:
        if file in by_file(atrium[library_name]):
            stale.append(f"{library_name}: Atrium now makes an item of {file!r}")
    for row in NAMED_DIFFERENTLY:
        found = by_file(atrium[row.library]).get(row.file)
        if found is not None and found[1] == row.reference:
            stale.append(f"{row.library}: {row.file!r} is now named {row.reference!r} here too")
    for library_name, kind, container in CONTAINERS_ONLY_ATRIUM_HAS:
        if (kind, container) not in containers(atrium[library_name]):
            stale.append(f"{library_name}: Atrium no longer has {kind} {container!r}")

    assert not unexpected and not stale, (
        "Atrium's scan of the fixture no longer differs from the recorded reference reading in "
        "the way this module declares.\n\nNot declared:\n  "
        + "\n  ".join(unexpected or ["-"])
        + "\n\nDeclared and no longer true:\n  "
        + "\n  ".join(stale or ["-"])
        + f"\n\nThe record is {READING.name}, taken by tools/probe_reference_scan.py against a "
        "single-use reference instance. Re-run the probe to move the record; edit the tables in "
        "this module to move what is expected of the comparison. Do not do the second to make the "
        "first go away."
    )


@pytest.mark.ffmpeg
def test_the_reading_states_the_item_count_of_every_library(
    recorded: dict[str, object],
    atrium: dict[str, list[tuple[str, str, str | None]]],
) -> None:
    """AC-2's other half - *the same item count* - which over this tree is not the same.

    Both worlds and the empty library, and the reading is the only place these numbers have ever
    been written down. They are asserted rather than described so that a change to either side has
    to come here and say what it did.

    **The two media libraries are where the counts agree**, which is the sharpest thing in this
    module: over files a prober can open, the two servers make the same items and differ only in
    five labels. Every count that disagrees is over a tree neither server can decode, or over a
    library with nothing in it.
    """
    counted = {
        str(library["name"]): int(library["item_count"])  # type: ignore[index,call-overload]
        for library in recorded["libraries"]  # type: ignore[union-attr]
    }
    assert counted == {
        "Movies": 18,
        "Shows": 20,
        "Music": 20,
        "Films": 12,
        "Tunes": 4,
        "Empty": 0,
    }
    assert {name: len(rows) for name, rows in atrium.items()} == {
        "Movies": 17,
        "Shows": 18,
        "Music": 18,
        "Films": 12,
        "Tunes": 4,
        "Empty": 1,
    }


def test_the_reading_says_which_libraries_hold_media_a_prober_can_open(
    recorded: dict[str, object],
) -> None:
    """The record distinguishes the two worlds, and the first reading did not.

    T10's finding was *"37 of the 59 items are backed by a file none of its probers can open"*,
    which was true of a tree that was the 003 world alone. The composed tree is both worlds, so a
    record that went on calling every file-backed row undecodable would carry a false statement in
    the one document AC-2 is checked against - a real `h264` file described as unopenable.
    """
    flags = {
        str(library["name"]): bool(library["decodable"])  # type: ignore[index]
        for library in recorded["libraries"]  # type: ignore[union-attr]
    }
    assert flags == {
        "Movies": False,
        "Shows": False,
        "Music": False,
        "Films": True,
        "Tunes": True,
        "Empty": False,
    }
    rows = [
        (bool(library["decodable"]), entry)  # type: ignore[index]
        for library in recorded["libraries"]  # type: ignore[union-attr]
        for entry in library["items"]  # type: ignore[index]
    ]
    backed = [entry for _, entry in rows if entry["file"] is not None]
    undecodable = [
        entry for decodable, entry in rows if not decodable and entry["file"] is not None
    ]
    assert len(undecodable) < len(backed), (
        "every file-backed row is over a file nothing can decode, so either the media world is "
        "not in the tree or the record has stopped distinguishing the two"
    )

    finding = str(recorded["finding"])
    assert f"{len(backed)} of them backed by a file" in finding
    assert f"{len(undecodable)} of those over a file none of its probers can open" in finding
    assert "both worlds go across" in finding


def test_the_declared_differences_are_the_number_this_module_claims() -> None:
    """The docstring says forty-seven, and a number in prose that nothing counts goes stale.

    Counted rather than restated: the comparison above already fails on an undeclared difference
    and on a declared one that has gone away, so this is not a second gate on the servers - it is
    the gate on the sentence a reader takes the shape of the disagreement from.
    """
    declared = (
        len(ONLY_THE_REFERENCE_MAKES_AN_ITEM_OF)
        + len(ONLY_ATRIUM_MAKES_AN_ITEM_OF)
        + len(NAMED_DIFFERENTLY)
        + len(CONTAINERS_ONLY_THE_REFERENCE_HAS)
        + len(CONTAINERS_ONLY_ATRIUM_HAS)
    )
    assert declared == 47
    assert "forty-seven places" in str(__doc__)


def test_the_record_carries_its_own_citation(recorded: dict[str, object]) -> None:
    """A reading with no provenance is a claim about a server nobody can check (Principle II)."""
    citation = str(recorded["citation"])
    assert citation.startswith("[probe: tools/probe_reference_scan.py, Jellyfin 10.11.")
    assert citation.endswith("]")
    assert str(recorded["image"]).startswith("jellyfin/jellyfin@sha256:")


def test_the_record_was_taken_with_the_remote_fetchers_off(recorded: dict[str, object]) -> None:
    """Otherwise the record is a reading of somebody else's database, not of the fixture.

    A library added the obvious way fetches metadata from the internet, and over the 003 tree it
    supplied nine of that reading's names - `Highlander: Reunion` for an episode of a series that
    does not exist. Those names change without either server changing, so a record taken that way
    would fail this module on a day when nothing here had moved.

    **The list may be carried forward, and the record has to say which.** Taking the comparison
    means standing up a second instance whose whole purpose is to let a third party's database
    answer, so an ordinary re-reading skips it - and the finding, which is a property of the
    reference's own defaults rather than of this tree, is carried forward with the citation it was
    taken under. A record with the list missing altogether would let this test stop asserting the
    one thing that keeps the reading honest.
    """
    remote = recorded["remote_metadata"]
    assert remote["enabled"] is False  # type: ignore[index]
    supplied = remote["names_a_fetcher_supplied"]  # type: ignore[index]
    assert supplied, "the comparison that proves the fetchers were the difference was not taken"
    if not remote["compared"]:  # type: ignore[index]
        assert str(remote["carried_forward_from"]).startswith(  # type: ignore[index]
            "[probe: tools/probe_reference_scan.py, Jellyfin 10.11."
        ), "a carried-forward list with no citation is a claim about a run nobody can name"
    recorded_names = {
        (str(row["library"]), str(row["path"])): str(row["from_a_fetcher"])  # type: ignore[index]
        for row in supplied  # type: ignore[union-attr]
    }
    assert ("Shows", "The Series/Specials/The Series - S00E01 - A Special.mkv") in recorded_names
