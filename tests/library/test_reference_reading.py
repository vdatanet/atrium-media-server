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
this tree in twenty-six places, every one of them written down below with the reason it is there.
A difference that is not in the table fails the test, which is what makes this a measurement of
Atrium's scan rather than a restatement of it: change a name derivation and a row moves; refresh
the record against a new reference and a row moves. Deciding what Atrium *does* about any of them
belongs to the feature that owns the behaviour (010 spec section 2), not here.
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


#: A file the **reference** makes an item of and Atrium does not. Neither row is a defect in this
#: feature: one is a deliberate rule of 003 and the other is a defect in the fixture, which is T11's
#: to repair and is recorded here so that repairing it moves this table rather than surprising
#: somebody.
ONLY_THE_REFERENCE_MAKES_AN_ITEM_OF = {
    (
        "Movies",
        "An Incomplete Copy (2000).mkv",
    ): "A zero-byte file is an incomplete copy and produces no item here (003 spec section 3.2); "
    "the reference makes a Movie of it. Atrium's rule is deliberate and the difference is real",
    (
        "Movies",
        "Excluded/An Excluded Film (2000).mkv",
    ): "The `.ignore` marker beside it excludes the directory here and does not there - because "
    "the fixture's marker is **not empty**. An empty `.ignore` ignores the directory outright and "
    "one with content is read as gitignore-style rules "
    "[source: Emby.Server.Implementations/Library/DotIgnoreIgnoreRule.cs:58-66 @ v10.11.11], and "
    "`generate.py` writes a banner and filler into every declared entry. **This is a defect in the "
    "fixture, not in either server**: the case the entry exists to exercise is not being exercised "
    "on the reference side. T11 owns the tree",
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
}

CONTAINERS_ONLY_ATRIUM_HAS = {
    ("Movies", "CollectionFolder", "Movies"): "The other half of the library-root row above",
    ("Shows", "CollectionFolder", "Shows"): "The other half of the library-root row above",
    ("Music", "CollectionFolder", "Music"): "The other half of the library-root row above",
    ("Music", "MusicAlbum", "A Compilation"): "The other half of the compilation's renaming",
    ("Music", "MusicAlbum", "album"): "The other half of the first album's renaming",
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

    The tree is built by the entry point the probe builds it with, so a change to the manifest
    moves both sides at once rather than making this test disagree with the record for a reason
    that is not a difference between two servers.
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
            scan(library, db, prober=not_media)
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


def test_the_reading_states_the_item_count_of_every_library(
    recorded: dict[str, object],
    atrium: dict[str, list[tuple[str, str, str | None]]],
) -> None:
    """AC-2's other half - *the same item count* - which over this tree is not the same.

    Six items of fifty-nine, and the reading is the only place the number has ever been written
    down. It is asserted rather than described so that a change to either side has to come here
    and say what it did.
    """
    counted = {
        str(library["name"]): int(library["item_count"])  # type: ignore[index,call-overload]
        for library in recorded["libraries"]  # type: ignore[union-attr]
    }
    assert counted == {"Movies": 19, "Shows": 20, "Music": 20}
    assert {name: len(rows) for name, rows in atrium.items()} == {
        "Movies": 17,
        "Shows": 18,
        "Music": 18,
    }


def test_the_record_carries_its_own_citation(recorded: dict[str, object]) -> None:
    """A reading with no provenance is a claim about a server nobody can check (Principle II)."""
    citation = str(recorded["citation"])
    assert citation.startswith("[probe: tools/probe_reference_scan.py, Jellyfin 10.11.")
    assert citation.endswith("]")
    assert str(recorded["image"]).startswith("jellyfin/jellyfin@sha256:")


def test_the_record_was_taken_with_the_remote_fetchers_off(recorded: dict[str, object]) -> None:
    """Otherwise the record is a reading of somebody else's database, not of the fixture.

    A library added the obvious way fetches metadata from the internet, and over this tree it
    supplied nine of the fifty-nine names - `Highlander: Reunion` for an episode of a series that
    does not exist. Those names change without either server changing, so a record taken that way
    would fail this module on a day when nothing here had moved.
    """
    remote = recorded["remote_metadata"]
    assert remote["enabled"] is False  # type: ignore[index]
    supplied = remote["names_a_fetcher_supplied"]  # type: ignore[index]
    assert supplied, "the comparison that proves the fetchers were the difference was not taken"
    recorded_names = {
        (str(row["library"]), str(row["path"])): str(row["from_a_fetcher"])  # type: ignore[index]
        for row in supplied  # type: ignore[union-attr]
    }
    assert ("Shows", "The Series/Specials/The Series - S00E01 - A Special.mkv") in recorded_names
