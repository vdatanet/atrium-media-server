# SPDX-License-Identifier: GPL-3.0-or-later
"""What the walk picks up, and what it deliberately walks past.

Driven by the fixture library of T2, which was declared with these cases in it: a `theme.mp3` and a
`commentary.mka` beside a film, a hidden directory, an `.ignore` marker, a zero-byte file, a
trailer and a sample. Each of those entries carries the reason it exists, and this is the test that
consumes them - so a fixture entry silently disappearing fails here rather than quietly reducing
what is covered.

The one that would be worst to get wrong is `test_specials_is_not_an_extras_folder`. `Specials` is
an alias for season zero, and a walker that filed it under extras would drop every special episode
in every series while producing a scan that looks entirely correct.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atrium.domain.items import CollectionType
from atrium.library.walker import (
    AUDIO_EXTENSIONS,
    EXTENSIONS,
    VIDEO_EXTENSIONS,
    Skip,
    found,
    is_extra,
    settle,
    walk,
)
from tests.fixtures.library import BuiltFixture, Kind


def walked(fixture_library: BuiltFixture, collection_type: str):  # type: ignore[no-untyped-def]
    built = fixture_library.of(collection_type)
    return walk(built.root, CollectionType(collection_type))


def paths_of(fixture_library: BuiltFixture, collection_type: str) -> set[str]:
    return {one.relative_path for one in walked(fixture_library, collection_type).candidates}


def skips_of(fixture_library: BuiltFixture, collection_type: str) -> dict[str, Skip]:
    return {
        one.relative_path: one.reason for one in walked(fixture_library, collection_type).skipped
    }


# ------------------------------------------------------------------------------------------
# Against the fixture: everything declared MEDIA is found, and nothing else is
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_every_media_entry_is_a_candidate(
    fixture_library: BuiltFixture, collection_type: str
) -> None:
    """The fixture declares what each file is for; the walk has to agree with all of it."""
    declared = {
        entry.path
        for entry in fixture_library.of(collection_type).library.entries
        if entry.kind is Kind.MEDIA
    }
    assert paths_of(fixture_library, collection_type) == declared


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_nothing_declared_ignored_is_a_candidate(
    fixture_library: BuiltFixture, collection_type: str
) -> None:
    found_paths = paths_of(fixture_library, collection_type)
    for entry in fixture_library.of(collection_type).library.entries:
        if entry.kind in (Kind.IGNORED, Kind.SIDECAR, Kind.EMPTY):
            assert entry.path not in found_paths, f"{entry.path}: {entry.reason}"


# ------------------------------------------------------------------------------------------
# The measured extension rule
# ------------------------------------------------------------------------------------------


def test_an_audio_file_under_a_video_root_is_not_a_candidate(
    fixture_library: BuiltFixture,
) -> None:
    """T1 measured this on the reference: 89 `.mp3` files under video roots produced no item.

    A scanner generous enough to admit every audio extension everywhere would turn theme music
    into items the reference does not have. behaviours.md section 2.15.
    """
    for collection_type in ("movies", "tvshows"):
        skipped = skips_of(fixture_library, collection_type)
        audio = {
            path: reason for path, reason in skipped.items() if path.endswith((".mp3", ".mka"))
        }
        assert audio, f"the {collection_type} fixture has no audio file to walk past"
        assert set(audio.values()) == {Skip.EXTENSION}


def test_the_measured_extensions_are_all_honoured() -> None:
    """The lower bound of spec section 3.2, asserted so that shrinking it fails."""
    assert {".mkv", ".mp4", ".avi", ".ts"} <= VIDEO_EXTENSIONS
    assert {".flac", ".m4a", ".dsf"} <= AUDIO_EXTENSIONS


def test_the_video_and_audio_lists_do_not_overlap() -> None:
    """Measured: the lists do not fall back to one another. An overlap would be the fallback."""
    assert not VIDEO_EXTENSIONS & AUDIO_EXTENSIONS


def test_mp3_is_music_only() -> None:
    assert ".mp3" in EXTENSIONS[CollectionType.MUSIC]
    assert ".mp3" not in EXTENSIONS[CollectionType.MOVIES]
    assert ".mp3" not in EXTENSIONS[CollectionType.TVSHOWS]


def test_a_video_file_under_a_music_root_is_not_a_candidate(
    fixture_library: BuiltFixture,
) -> None:
    """Spec section 3.1: a file under a music root is never resolved as a movie."""
    assert skips_of(fixture_library, "music")["The Artist/Not A Film (2001).mkv"] is Skip.EXTENSION


# ------------------------------------------------------------------------------------------
# The ignore rules, each with its reason
# ------------------------------------------------------------------------------------------


def test_a_hidden_directory_is_not_descended_into(fixture_library: BuiltFixture) -> None:
    """Pruned rather than filtered: nothing under it is listed at all, so nothing under it is
    reported either. A `.hidden` tree costs one `readdir`.
    """
    result = walked(fixture_library, "movies")
    assert not any(one.relative_path.startswith(".hidden/") for one in result.candidates)
    assert not any(one.relative_path.startswith(".hidden/") for one in result.skipped)


def test_a_hidden_file_is_skipped_as_hidden(tmp_path: Path) -> None:
    (tmp_path / ".DS_Store").write_bytes(b"x")
    (tmp_path / ".Something (2000).mkv").write_bytes(b"x")
    reasons = {
        one.relative_path: one.reason for one in walk(tmp_path, CollectionType.MOVIES).skipped
    }
    assert reasons[".Something (2000).mkv"] is Skip.HIDDEN
    assert reasons[".DS_Store"] is Skip.HIDDEN


def test_an_ignore_marker_excludes_its_directory(fixture_library: BuiltFixture) -> None:
    result = walked(fixture_library, "movies")
    assert Skip.IGNORED in {one.reason for one in result.skipped}
    assert not any(one.relative_path.startswith("Excluded/") for one in result.candidates)


def test_an_ignore_marker_excludes_everything_below_it(tmp_path: Path) -> None:
    """Not only the directory holding it: an operator excluding a tree means the tree."""
    deep = tmp_path / "Excluded" / "Deeper" / "Deeper Still"
    deep.mkdir(parents=True)
    (tmp_path / "Excluded" / ".ignore").write_bytes(b"")
    (deep / "A Film (2000).mkv").write_bytes(b"x")
    (tmp_path / "A Kept Film (2000).mkv").write_bytes(b"x")

    result = walk(tmp_path, CollectionType.MOVIES)
    assert [one.relative_path for one in result.candidates] == ["A Kept Film (2000).mkv"]


def test_a_zero_byte_file_is_skipped_as_incomplete(fixture_library: BuiltFixture) -> None:
    assert skips_of(fixture_library, "movies")["An Incomplete Copy (2000).mkv"] is Skip.EMPTY


def test_a_trailer_and_a_sample_are_skipped_as_extras(fixture_library: BuiltFixture) -> None:
    skipped = skips_of(fixture_library, "movies")
    assert skipped["The Matrix (1999)/The Matrix (1999)-trailer.mkv"] is Skip.EXTRA
    assert skipped["The Matrix (1999)/The Matrix (1999)-sample.mkv"] is Skip.EXTRA


def test_an_extra_is_recognised_by_its_containing_folder_too(tmp_path: Path) -> None:
    """Spec section 3.4: by suffix *and* by containing-folder name."""
    (tmp_path / "The Film (1999)" / "Extras").mkdir(parents=True)
    (tmp_path / "The Film (1999)" / "Extras" / "Something.mkv").write_bytes(b"x")
    (tmp_path / "The Film (1999)" / "The Film (1999).mkv").write_bytes(b"x")

    result = walk(tmp_path, CollectionType.MOVIES)
    assert [one.relative_path for one in result.candidates] == [
        "The Film (1999)/The Film (1999).mkv"
    ]
    assert result.reasons() == {Skip.EXTRA: 1}


def test_specials_is_not_an_extras_folder() -> None:
    """`Specials` is season zero (AC-6), not extras.

    Filing it under extras drops every special episode in every series and produces a scan that
    looks entirely correct while doing it. This is the single worst thing this module could get
    wrong, which is why it is asserted on its own rather than inside a table.
    """
    assert not is_extra("The Series/Specials/The Series - S00E01 - A Special.mkv")
    assert is_extra("The Series/Extras/Something.mkv")


def test_the_specials_episode_in_the_fixture_survives_the_walk(
    fixture_library: BuiltFixture,
) -> None:
    assert "The Series/Specials/The Series - S00E01 - A Special.mkv" in paths_of(
        fixture_library, "tvshows"
    )


def test_an_unreadable_directory_is_counted_and_reported(tmp_path: Path) -> None:
    """Plan section 7: skip, count, report with the reason - and do not abort the scan.

    A *directory* rather than a file, because a walk never reads contents: `chmod 000` on a file
    does not stop `stat`, so a permission bit on one is invisible here and would be 008's problem.
    A directory the scan cannot list is the real case, and `os.walk` **discards that error
    silently** unless it is asked not to. Under the default, every file below would look deleted
    to the next scan's diff - a partial loss too small for the emptiness guard to catch.
    """
    (tmp_path / "A Readable Film (2000).mkv").write_bytes(b"x")
    closed = tmp_path / "Closed"
    closed.mkdir()
    (closed / "A Hidden Away Film (2000).mkv").write_bytes(b"x")
    closed.chmod(0o000)
    try:
        if list(closed.iterdir()):  # a root-owned runner can read it anyway
            pytest.skip("this process can read a 0o000 directory, so there is nothing to observe")
    except PermissionError:
        pass

    try:
        result = walk(tmp_path, CollectionType.MOVIES)
    finally:
        closed.chmod(0o755)

    assert [one.relative_path for one in result.candidates] == ["A Readable Film (2000).mkv"]
    assert result.reasons() == {Skip.UNREADABLE: 1}
    assert [one.relative_path for one in result.skipped] == ["Closed"]


# ------------------------------------------------------------------------------------------
# Files still being written
# ------------------------------------------------------------------------------------------


def test_a_file_that_grows_between_the_passes_is_skipped_this_scan(tmp_path: Path) -> None:
    """A download in progress. Skipped now, picked up next time - not half-scanned now."""
    downloading = tmp_path / "A Download (2000).mkv"
    downloading.write_bytes(b"x" * 10)
    (tmp_path / "A Finished Film (2000).mkv").write_bytes(b"x" * 10)

    first = found(tmp_path, CollectionType.MOVIES)
    assert len(first.candidates) == 2

    downloading.write_bytes(b"x" * 20)  # the copy continues
    result = settle(tmp_path, first)

    assert [one.relative_path for one in result.candidates] == ["A Finished Film (2000).mkv"]
    assert result.reasons() == {Skip.BEING_WRITTEN: 1}


def test_the_next_scan_picks_it_up(tmp_path: Path) -> None:
    """The other half of the promise, and the half that would be easy to leave unimplemented."""
    downloading = tmp_path / "A Download (2000).mkv"
    downloading.write_bytes(b"x" * 10)
    first = found(tmp_path, CollectionType.MOVIES)
    downloading.write_bytes(b"x" * 20)
    assert settle(tmp_path, first).candidates == ()

    assert [one.relative_path for one in walk(tmp_path, CollectionType.MOVIES).candidates] == [
        "A Download (2000).mkv"
    ]


def test_a_file_that_vanishes_mid_scan_is_not_an_error(tmp_path: Path) -> None:
    """A file can be moved away while a scan runs. That is not a failure of the scan."""
    going = tmp_path / "A Film (2000).mkv"
    going.write_bytes(b"x")
    first = found(tmp_path, CollectionType.MOVIES)
    going.unlink()

    result = settle(tmp_path, first)
    assert result.candidates == ()
    assert result.reasons() == {Skip.UNREADABLE: 1}


def test_an_unchanged_file_keeps_its_signal(tmp_path: Path) -> None:
    """`(size, mtime_ns)` is what change detection compares at T19; the walk supplies both."""
    (tmp_path / "A Film (2000).mkv").write_bytes(b"x" * 7)
    only = walk(tmp_path, CollectionType.MOVIES).candidates[0]
    assert only.size == 7
    assert only.mtime_ns == (tmp_path / "A Film (2000).mkv").stat().st_mtime_ns


# ------------------------------------------------------------------------------------------
# The walk itself
# ------------------------------------------------------------------------------------------


def test_the_order_is_stable(fixture_library: BuiltFixture) -> None:
    """Determinism starts here: two walks of one tree produce one order (spec section 3.8)."""
    built = fixture_library.of("movies")
    once = walk(built.root, CollectionType.MOVIES)
    again = walk(built.root, CollectionType.MOVIES)
    assert once.candidates == again.candidates
    assert once.skipped == again.skipped


def test_paths_come_back_relative_to_the_root(fixture_library: BuiltFixture) -> None:
    """Identity derives from these, and refuses an absolute one (spec section 3.6)."""
    for candidate in walked(fixture_library, "movies").candidates:
        assert not candidate.relative_path.startswith("/")
        assert "\\" not in candidate.relative_path


def test_an_empty_root_yields_nothing_and_is_not_an_error(tmp_path: Path) -> None:
    """It is T17's guard that decides an empty root is suspicious, not the walk's."""
    assert walk(tmp_path, CollectionType.MOVIES).candidates == ()
