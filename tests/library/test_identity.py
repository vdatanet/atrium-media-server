# SPDX-License-Identifier: GPL-3.0-or-later
"""Identifiers survive everything except a change to the thing they identify.

**What is deliberately not retested here:** that the derivation is 32 lowercase hex, deterministic
across processes, and NUL-separated so no two tuples collide. All three are properties of
`atrium.compat.guids.derive`, which 001 built and tests in tests/unit/test_compat_guids.py -
including the cross-process run, which is the only way to catch an identifier that depends on hash
randomisation. Asserting them again here would be testing somebody else's function and would go
stale in the direction of agreeing with itself.

What 003 adds, and what is tested here: *which* facts go into the key for each of the four rules,
how a path is normalised before it becomes one, and what happens when two paths collide.
"""

from __future__ import annotations

import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest

from atrium.compat.guids import CANONICAL
from atrium.domain.items import ItemType
from atrium.library.identity import (
    RULE_OF,
    IdentityCollisionError,
    IdentityRule,
    ensure_unique,
    fold_by_name,
    for_by_name,
    for_file,
    for_library,
    for_name,
    for_season,
    normalise_name,
    normalise_path,
)
from tests.fixtures.library import BuiltFixture, build_fixture_library

LIBRARY = "b" * 32
FILM = "Movies/The Film (1999).mkv"


# ------------------------------------------------------------------------------------------
# The four rules, and that every type has exactly one
# ------------------------------------------------------------------------------------------


def test_every_type_has_an_identity_rule() -> None:
    """A type with no rule cannot be identified, and would fail mid-scan rather than here."""
    assert set(RULE_OF) == set(ItemType)


@pytest.mark.parametrize("rule", list(IdentityRule))
def test_every_rule_is_used_by_some_type(rule: IdentityRule) -> None:
    """A rule nothing uses is a rule nobody maintains."""
    assert rule in RULE_OF.values()


def test_deriving_a_type_the_wrong_way_is_refused() -> None:
    """The failure this prevents is silent: the wrong rule produces a perfectly valid identifier.

    Nothing about the result would look wrong. It would simply be the identifier of a different
    thing, and the symptom would arrive much later as an item that does not match its file.
    """
    with pytest.raises(ValueError, match="takes its identity from"):
        for_file(ItemType.SERIES, LIBRARY, "Shows/The Series")
    with pytest.raises(ValueError, match="takes its identity from"):
        for_name(ItemType.MOVIE, LIBRARY, "The Film")


def test_the_result_is_a_canonical_identifier() -> None:
    for item_id in (
        for_file(ItemType.MOVIE, LIBRARY, FILM),
        for_name(ItemType.SERIES, LIBRARY, "The Series"),
        for_season("a" * 32, 1),
        for_library(LIBRARY),
    ):
        assert CANONICAL.match(item_id), item_id


def test_the_type_is_part_of_the_key() -> None:
    """The same path as two types is two items [spec section 3.6]."""
    assert for_file(ItemType.MOVIE, LIBRARY, FILM) != for_file(ItemType.EPISODE, LIBRARY, FILM)


def test_the_library_is_part_of_the_key() -> None:
    """The same relative path in two libraries is two files."""
    assert for_file(ItemType.MOVIE, LIBRARY, FILM) != for_file(ItemType.MOVIE, "c" * 32, FILM)


# ------------------------------------------------------------------------------------------
# AC-10: moving the root changes nothing
# ------------------------------------------------------------------------------------------


def test_the_identifier_does_not_depend_on_where_the_library_is_mounted(tmp_path: Path) -> None:
    """The relative-path decision, against the real fixture tree built at two different roots.

    The reference derives from the absolute path, so this move costs it every identifier in the
    library. T19 proves the same thing through a whole scan; this is the unit that makes it true,
    and it uses real paths rather than two identical string literals - which would pass whatever
    the derivation did.
    """
    here = build_fixture_library(tmp_path / "mnt-a")
    moved = build_fixture_library(tmp_path / "mnt-b")
    assert here.base != moved.base

    def ids(built: BuiltFixture) -> list[str]:
        movies = built.of("movies")
        return [
            for_file(ItemType.MOVIE, LIBRARY, str(path.relative_to(movies.root)))
            for path in sorted(movies.root.rglob("*.mkv"))
        ]

    assert ids(here), "the fixture produced no films to compare"
    assert ids(here) == ids(moved)


def test_an_absolute_path_is_refused_rather_than_made_relative() -> None:
    """Guessing which prefix was the root is how an identifier silently becomes the wrong one."""
    with pytest.raises(ValueError, match="absolute"):
        for_file(ItemType.MOVIE, LIBRARY, "/mnt/a/" + FILM)


# ------------------------------------------------------------------------------------------
# Normalisation
# ------------------------------------------------------------------------------------------


def test_separators_are_normalised() -> None:
    assert normalise_path("a\\b\\c.mkv") == normalise_path("a/b/c.mkv")


def test_repeated_and_trailing_separators_do_not_change_the_identity() -> None:
    assert normalise_path("a//b/./c.mkv") == "a/b/c.mkv"
    assert normalise_path("/".join(["a", "b", "c.mkv"])) == "a/b/c.mkv"


def test_a_decomposed_name_and_a_composed_one_are_the_same_file() -> None:
    """macOS hands back NFD; Linux gives NFC. Without this, one film has two identifiers.

    The fixture library carries `Amélie (2001).mkv` for exactly this reason.
    """
    composed = unicodedata.normalize("NFC", "Amélie (2001).mkv")
    decomposed = unicodedata.normalize("NFD", "Amélie (2001).mkv")
    assert composed != decomposed, "the two forms differ as bytes, or this test proves nothing"
    assert for_file(ItemType.MOVIE, LIBRARY, composed) == for_file(
        ItemType.MOVIE, LIBRARY, decomposed
    )


def test_case_is_folded_by_default() -> None:
    assert for_file(ItemType.MOVIE, LIBRARY, "A/B.mkv") == for_file(
        ItemType.MOVIE, LIBRARY, "a/b.mkv"
    )


def test_a_case_sensitive_library_keeps_both() -> None:
    """The flag exists because some libraries genuinely hold two files differing only by case."""
    one = for_file(ItemType.MOVIE, LIBRARY, "A/B.mkv", case_sensitive=True)
    other = for_file(ItemType.MOVIE, LIBRARY, "a/b.mkv", case_sensitive=True)
    assert one != other


def test_flipping_the_flag_changes_every_identifier() -> None:
    """Which is why plan section 6.3 freezes it at creation, and why T7 refuses the edit."""
    assert for_file(ItemType.MOVIE, LIBRARY, FILM) != for_file(
        ItemType.MOVIE, LIBRARY, FILM, case_sensitive=True
    )


def test_a_path_above_the_root_is_refused() -> None:
    with pytest.raises(ValueError, match="climbs above"):
        normalise_path("../elsewhere/The Film.mkv")


def test_a_name_is_normalised_the_way_a_path_is() -> None:
    """Section 3.6 says "the normalised name" without defining it; this is the definition."""
    assert for_name(ItemType.SERIES, LIBRARY, "  The Series  ") == for_name(
        ItemType.SERIES, LIBRARY, "the series"
    )
    assert normalise_name("Amélie") == normalise_name(unicodedata.normalize("NFD", "Amélie"))


# ------------------------------------------------------------------------------------------
# The rules that are not paths
# ------------------------------------------------------------------------------------------


def test_a_season_is_identified_by_its_series_and_its_number() -> None:
    """Not by a directory: a season often has no directory of its own [section 3.4]."""
    series = for_name(ItemType.SERIES, LIBRARY, "The Series")
    assert for_season(series, 1) != for_season(series, 2)
    assert for_season(series, 1) != for_season(for_name(ItemType.SERIES, LIBRARY, "Other"), 1)


def test_a_season_directory_may_be_renamed_without_changing_its_identity() -> None:
    """`Season 01`, `Season 1` and `Specials` are all directory spellings of the same number."""
    series = for_name(ItemType.SERIES, LIBRARY, "The Series")
    assert for_season(series, 0) == for_season(series, 0)


def test_a_season_with_no_number_still_gets_one_identity() -> None:
    """A season whose number could not be read still has to be something."""
    series = for_name(ItemType.SERIES, LIBRARY, "The Series")
    assert CANONICAL.match(for_season(series, None))
    assert for_season(series, None) != for_season(series, 0)


def test_an_album_is_identified_by_its_name_not_its_directory() -> None:
    """Which is what makes a two-disc album one album, and a retagged directory harmless."""
    assert for_name(ItemType.MUSIC_ALBUM, LIBRARY, "Double Album") == for_name(
        ItemType.MUSIC_ALBUM, LIBRARY, "double album"
    )


def test_a_library_identifies_its_own_collection_folder() -> None:
    assert for_library(LIBRARY) != for_library("c" * 32)


# ------------------------------------------------------------------------------------------
# Collision
# ------------------------------------------------------------------------------------------


def test_two_paths_deriving_one_identifier_abort_and_name_both() -> None:
    """Plan section 7: a collision aborts rather than merging, because merging hides the bug.

    Exercised with a forced duplicate rather than a real SHA-256 collision, which nobody has.
    """
    with pytest.raises(IdentityCollisionError, match="both derive") as raised:
        ensure_unique([("a" * 32, "one.mkv"), ("a" * 32, "two.mkv")])
    assert "one.mkv" in str(raised.value)
    assert "two.mkv" in str(raised.value)


def test_the_same_path_twice_is_not_a_collision() -> None:
    """A rescan sees the same file again; that is the ordinary case, not an abort."""
    assert ensure_unique([("a" * 32, "one.mkv"), ("a" * 32, "one.mkv")]) == {"a" * 32: "one.mkv"}


def test_ordinary_assignments_come_back_as_a_map() -> None:
    assert ensure_unique([("a" * 32, "one.mkv"), ("b" * 32, "two.mkv")]) == {
        "a" * 32: "one.mkv",
        "b" * 32: "two.mkv",
    }


# ------------------------------------------------------------------------------------------
# Across processes, including the normalisation
# ------------------------------------------------------------------------------------------


def test_the_whole_derivation_is_deterministic_across_processes() -> None:
    """001 proves this for the hash. This proves it for the normalisation wrapped around it -
    a step reached through a set or a dict would be stable in one process and not between two.
    """
    script = (
        "from atrium.domain.items import ItemType; "
        "from atrium.library.identity import for_file; "
        f"print(for_file(ItemType.MOVIE, {LIBRARY!r}, 'Movies/Amélie (2001).mkv'))"
    )
    runs = [
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()
        for _ in range(2)
    ]
    assert runs[0] == runs[1] == for_file(ItemType.MOVIE, LIBRARY, "Movies/Amélie (2001).mkv")


# --------------------------------------------------------------------------------------------
# 004: the by-name rule, and the fold behind it
# --------------------------------------------------------------------------------------------


def test_a_genre_and_a_music_genre_of_the_same_name_are_two_items() -> None:
    """What keeps `/Genres` and `/MusicGenres` disjoint without either endpoint guessing.

    The type is in the key, so `Drama` the film genre and `Drama` the music genre are two rows -
    and a query for one can never return the other.
    """
    assert for_by_name(ItemType.GENRE, "Drama") != for_by_name(ItemType.MUSIC_GENRE, "Drama")


def test_two_spellings_of_one_genre_are_one_item() -> None:
    """AC-14, at identity level: `Sci-Fi` and `sci-fi` in two files produce one genre.

    The reference's own behaviour rather than an improvement - 97 of 97 live ids reproduce from
    the case-folded name (docs/compatibility/behaviours.md section 2.18).
    """
    assert for_by_name(ItemType.GENRE, "Sci-Fi") == for_by_name(ItemType.GENRE, "sci-fi")
    assert for_by_name(ItemType.GENRE, "SCI-FI") == for_by_name(ItemType.GENRE, "sci-fi")


def test_diacritics_are_not_folded() -> None:
    """The other half of section 2.18's envelope, and the half that is easy to over-deliver on.

    Stripping accents would merge `Elektro` and `Elektró` into one genre the reference keeps
    apart, which is a delta a user sees as a genre that vanished.
    """
    assert for_by_name(ItemType.GENRE, "Elektro") != for_by_name(ItemType.GENRE, "Elektró")


def test_no_library_takes_part_in_a_by_name_identity() -> None:
    """Server-wide is the whole difference from `for_name`, and it is what makes `/Genres` a list
    of genres rather than a list of genres per library."""
    assert for_by_name(ItemType.GENRE, "Drama") == for_by_name(ItemType.GENRE, "Drama")
    assert "library" not in for_by_name.__code__.co_varnames


@pytest.mark.parametrize(
    ("spelling", "folded"),
    [
        ("Sci-Fi", "sci-fi"),
        ("  Rock  ", "rock"),
        # Path-invalid characters become spaces, one for one - so these two names are one genre,
        # which is the observable consequence of a fold the reference performs for a reason
        # (building a filename) that does not apply here at all.
        ("Drama/Romance", "drama romance"),
        ("Drama Romance", "drama romance"),
        ('He said "hi"', "he said  hi"),
        ("AC/DC", "ac dc"),
        ("What?", "what"),
        # Trailing dots go, and **the trim does not run again afterwards**. The reference does
        # `Trim().TrimEnd('.')` in that order, so these two fold differently: reproduced rather
        # than tidied, because tidying merges two rows the reference keeps apart.
        ("Drama...", "drama"),
        ("Drama. . .", "drama. . "),
        ("Drama. .", "drama. "),
    ],
)
def test_the_fold_reproduces_the_references_envelope(spelling: str, folded: str) -> None:
    assert fold_by_name(spelling) == folded


def test_the_fold_and_the_identity_cannot_disagree() -> None:
    """One definition, used twice: 004's by-name repository keys its rows on `fold_by_name` and
    the identifier hashes the same call. Two folds written separately is how a spelling ends up
    merging into one row and deriving another one's id."""
    for spelling in ("Sci-Fi", "sci-fi", "Drama/Romance", "Drama Romance"):
        assert for_by_name(ItemType.GENRE, spelling) == for_by_name(
            ItemType.GENRE, fold_by_name(spelling)
        ), "folding twice changes nothing, which is what makes the fold safe to apply early"


def test_a_year_rides_the_same_machinery() -> None:
    """Its digits are its name, and it has no join table: membership is `production_year`."""
    assert for_by_name(ItemType.YEAR, "1999") == for_by_name(ItemType.YEAR, "1999")
    assert for_by_name(ItemType.YEAR, "1999") != for_by_name(ItemType.YEAR, "2000")


@pytest.mark.parametrize("wrong", [ItemType.MOVIE, ItemType.SERIES, ItemType.MUSIC_ARTIST])
def test_a_type_that_belongs_to_another_rule_is_refused(wrong: ItemType) -> None:
    """`MusicArtist` especially: it looks like a by-name type, it is one in the reference, and it
    is per-library here (docs/compatibility/behaviours.md section 5.3). Deriving it this way would
    produce a perfectly valid identifier for the wrong thing."""
    with pytest.raises(ValueError, match="takes its identity from"):
        for_by_name(wrong, "Whatever")
