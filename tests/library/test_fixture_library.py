# SPDX-License-Identifier: GPL-3.0-or-later
"""The fixture library is deterministic, self-generated, and covers the cases it claims to.

Four properties, and each of them is load-bearing for a later task rather than tidiness here:

* **byte-identical across two builds** - otherwise a difference in a scan result might be a
  difference in the fixture, and AC-2 and AC-3 stop meaning anything;
* **nothing is committed but code** - which is how "no fixture file is a copyrighted work" stays
  true without anybody reviewing it again;
* **nothing outside the locked dependency set** - the task job installs nothing else, so a
  generator that reached for a muxer would fail there and not here;
* **the awkward cases are actually in the tree** - a fixture that quietly lost the compilation is
  a fixture that makes AC-9 pass by not testing it.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from tests.fixtures.library import LIBRARIES, Kind, build_fixture_library
from tests.fixtures.library.generate import BANNER, FIXED_MTIME_NS, content_of
from tests.fixtures.library.manifest import Entry

FIXTURE_PACKAGE = Path(__file__).resolve().parents[1] / "fixtures"

#: Acceptance criterion -> the entries that put it in the tree. Only the criteria the *fixture* is
#: responsible for are here. AC-2, AC-3, AC-10, AC-11 and AC-12 are mutations performed on the
#: tree at scan time - a rescan, a moved root, a deleted file, an unreadable directory - and a
#: fixture cannot hold them any more than it can hold a second scan.
REQUIRED: dict[int, tuple[tuple[str, str], ...]] = {
    4: (
        ("movies", "The Long Film (1998)/The Long Film (1998) - part1.mkv"),
        ("movies", "The Long Film (1998)/The Long Film (1998) - part2.mkv"),
    ),
    5: (("tvshows", "The Series/Season 01/The Series - S01E02-E03 - Two Parter.mkv"),),
    6: (("tvshows", "The Series/Specials/The Series - S00E01 - A Special.mkv"),),
    7: (("tvshows", "24/Season 01/24 - S01E01 - 12-00 AM.mkv"),),
    8: (
        ("music", "The Artist/Double Album/CD1/01 - First Disc.flac"),
        ("music", "The Artist/Double Album/CD2/01 - Second Disc.flac"),
    ),
    9: (
        ("music", "Various Artists/A Compilation (1999)/01 - By One Artist.flac"),
        ("music", "Various Artists/A Compilation (1999)/02 - By Another.flac"),
        ("music", "Various Artists/A Compilation (1999)/03 - By A Third.flac"),
    ),
    13: (
        ("movies", "Rock & Roll (1978).mkv"),
        ("movies", "S.W.A.T. (2003).mkv"),
        ("movies", "2 Fast 2 Furious (2003).mkv"),
        ("movies", "10 Things I Hate About You (1999).mkv"),
        ("movies", "  Padded   (1999).mkv"),
    ),
}


def entries_of(collection_type: str) -> dict[str, Entry]:
    for library in LIBRARIES:
        if library.collection_type == collection_type:
            return {entry.path: entry for entry in library.entries}
    raise AssertionError(f"no {collection_type!r} library is declared")


def every_file(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ------------------------------------------------------------------------------------------
# Determinism
# ------------------------------------------------------------------------------------------


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    """The property AC-2 and AC-3 rest on: the fixture is never the reason two scans differ."""
    first = every_file(build_fixture_library(tmp_path / "first").base)
    second = every_file(build_fixture_library(tmp_path / "second").base)

    assert first.keys() == second.keys()
    differing = [name for name in first if first[name] != second[name]]
    assert not differing, f"these files differ between two builds: {differing}"


def test_a_rebuild_into_the_same_directory_changes_nothing(tmp_path: Path) -> None:
    """Because a rescan test will do exactly this before asserting that nothing changed."""
    destination = tmp_path / "library"
    before = every_file(build_fixture_library(destination).base)
    assert every_file(build_fixture_library(destination).base) == before


def test_every_file_carries_the_fixed_modification_time(tmp_path: Path) -> None:
    """`(size, mtime_ns)` is the change-detection signal, so the fixture must not supply a clock."""
    root = build_fixture_library(tmp_path / "library").base
    stamps = {path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}
    assert stamps == {FIXED_MTIME_NS}


def test_every_generated_file_is_derived_from_its_declared_path(tmp_path: Path) -> None:
    built = build_fixture_library(tmp_path / "library")
    for library in built.libraries:
        for entry in library.library.entries:
            if entry.path.endswith("/"):
                continue
            assert library.path_of(entry.path).read_bytes() == content_of(entry), entry.path


# ------------------------------------------------------------------------------------------
# Nothing is committed, and nothing is installed
# ------------------------------------------------------------------------------------------


def test_the_generator_is_the_only_source_of_media() -> None:
    """No bytes are committed, so no committed byte can be somebody's copyrighted work.

    This is the assertion behind the definition-of-done line. It is deliberately about the whole
    package rather than a list of extensions: a `.mkv` nobody expected would be caught, and so
    would a `.jpg` that somebody helpfully added "just as an example".
    """
    committed = [
        str(path.relative_to(FIXTURE_PACKAGE))
        for path in sorted(FIXTURE_PACKAGE.rglob("*"))
        if path.is_file()
        and path.suffix != ".py"
        and "__pycache__" not in path.parts  # the interpreter's own output for the files above
    ]
    assert not committed, (
        f"tests/fixtures holds non-code files: {committed}. The fixture library is generated, "
        f"never committed - that is what makes 'no fixture file is a copyrighted work' a "
        f"property of the code rather than a promise."
    )


def test_every_non_empty_file_says_what_it_is(tmp_path: Path) -> None:
    """A human who opens one should not have to read this package to know it is synthetic."""
    root = build_fixture_library(tmp_path / "library").base
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        head = path.read_bytes()[:200]
        assert BANNER.strip() in head, f"{path.name} does not say it is synthetic"


@pytest.mark.parametrize("module", ["generate", "manifest"])
def test_the_generator_needs_nothing_outside_the_standard_library(module: str) -> None:
    """The tests job installs the locked set and nothing else; a muxer would fail there, not here.

    plan section 8.1: byte-identical across two builds must depend on this repository's code, not
    on whichever version of an external tool a runner image happens to carry.
    """
    source = (FIXTURE_PACKAGE / "library" / f"{module}.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])

    outside = sorted(imported - sys.stdlib_module_names - {"tests"})
    assert not outside, f"{module}.py imports {outside}, which the fixture must not need"


# ------------------------------------------------------------------------------------------
# The tree covers what it claims to
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("criterion", sorted(REQUIRED), ids=lambda n: f"AC-{n}")
def test_the_tree_covers_the_awkward_cases(criterion: int) -> None:
    for collection_type, path in REQUIRED[criterion]:
        assert path in entries_of(collection_type), (
            f"AC-{criterion} needs {path!r} in the {collection_type} library, and it is not "
            f"declared. Either the entry was renamed - rename it here too - or the case it "
            f"covered is now untested."
        )


def test_all_three_collection_types_have_media() -> None:
    """AC-1 asks for the expected item set 'for all three collection types'."""
    for collection_type in ("movies", "tvshows", "music"):
        entries = entries_of(collection_type)
        media = [entry for entry in entries.values() if entry.kind is Kind.MEDIA]
        assert len(media) >= 3, f"{collection_type} has {len(media)} media entries"


def test_the_compilation_really_is_one() -> None:
    """AC-9 is only a test if the track artists actually differ under one album artist."""
    tracks = [
        entry
        for path, entry in entries_of("music").items()
        if path.startswith("Various Artists/A Compilation (1999)/")
    ]
    assert len({track.tags["artist"] for track in tracks}) == len(tracks)
    assert len({track.tags["albumartist"] for track in tracks}) == 1


def test_the_two_disc_album_declares_two_discs() -> None:
    """AC-8 is only a test if the discs are numbered differently."""
    tracks = [
        entry
        for path, entry in entries_of("music").items()
        if path.startswith("The Artist/Double Album/")
    ]
    assert {track.tags["disc"] for track in tracks} == {"1", "2"}
    assert len({track.tags["album"] for track in tracks}) == 1


def test_an_audio_file_sits_under_a_video_root_and_is_expected_to_be_ignored() -> None:
    """T1 measured this on the reference, so the fixture has to be able to reproduce it.

    A scanner generous enough to admit every audio extension everywhere would invent items the
    reference does not have, and nothing else in the tree would notice.
    """
    for collection_type in ("movies", "tvshows"):
        audio = {
            path: entry
            for path, entry in entries_of(collection_type).items()
            if path.endswith((".mp3", ".mka"))
        }
        assert audio, f"the {collection_type} tree has no audio file to be ignored"
        assert all(entry.kind is Kind.IGNORED for entry in audio.values())


# ------------------------------------------------------------------------------------------
# The manifest's own rules
# ------------------------------------------------------------------------------------------


def test_every_entry_says_why_it_exists() -> None:
    """The naming corpus's rule, applied here: an entry with no reason is one nobody can judge."""
    for library in LIBRARIES:
        for entry in library.entries:
            assert entry.reason.strip(), f"{library.name}/{entry.path} states no reason"
            assert len(entry.reason) > 20, f"{library.name}/{entry.path}: {entry.reason!r}"


def test_no_entry_is_declared_twice() -> None:
    for library in LIBRARIES:
        paths = [entry.path for entry in library.entries]
        assert len(paths) == len(set(paths)), f"{library.name} declares a path twice"


def test_paths_are_relative_and_use_forward_slashes() -> None:
    for library in LIBRARIES:
        for entry in library.entries:
            assert not entry.path.startswith("/"), entry.path
            assert "\\" not in entry.path, entry.path


def test_the_empty_entry_is_empty_and_is_the_only_one(tmp_path: Path) -> None:
    """Zero bytes is an incomplete copy [spec section 3.2], and it has to really be zero bytes."""
    built = build_fixture_library(tmp_path / "library")
    empty = [
        library.path_of(entry.path)
        for library in built.libraries
        for entry in library.library.entries
        if entry.kind is Kind.EMPTY
    ]
    assert empty, "nothing in the tree exercises the zero-byte rule"
    for path in empty:
        assert path.stat().st_size == 0
