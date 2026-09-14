# SPDX-License-Identifier: GPL-3.0-or-later
"""The name a library is added under: 014 spec section 3.6.2's four steps, in their order.

**The order is the contract**, and two of its consequences are observable - which is why the
tests below are arranged around them rather than around the steps one by one. Trimming before
replacing keeps a replaced character at either end as a space, so `Movies?` is `Movies ` and does
not collide with `Movies` (measured on the reference). Checking emptiness before either lets a name
made only of replaced characters through, as spaces (read from the source, not measured).
"""

from __future__ import annotations

import pytest

from atrium.library.config import FIRST_NUMBER, REPLACED_IN_NAMES, settle_name

# ------------------------------------------------------------------------------------------
# Step 1: refused if empty or whitespace, on the name as sent
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("requested", ["", " ", "\t\n", "\u00a0", "\u2028"])
def test_an_empty_or_whitespace_name_is_refused(requested: str) -> None:
    with pytest.raises(ValueError, match="empty or whitespace"):
        settle_name(requested, [])


def test_a_name_made_only_of_replaced_characters_passes_and_becomes_spaces() -> None:
    """The second consequence of the order: step 1 looks at `??`, which is not whitespace, and step
    3 then makes it two spaces - and it is not trimmed again."""
    assert settle_name("??", []) == "  "
    assert settle_name(":/", ["  "]) == "  2"


# ------------------------------------------------------------------------------------------
# Step 2: trimmed - and step 3 only afterwards
# ------------------------------------------------------------------------------------------


def test_surrounding_whitespace_is_trimmed() -> None:
    assert settle_name("  Movies\t", []) == "Movies"


def test_a_replaced_character_at_the_end_stays_a_space_and_does_not_collide() -> None:
    """The first consequence, and the one measured: `Movies?` became `Movies ` beside `Movies`
    `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`."""
    assert settle_name("Movies?", ["Movies"]) == "Movies "
    assert settle_name("?Movies", ["Movies"]) == " Movies"


def test_the_trim_is_the_platforms_whitespace_and_not_pythons() -> None:
    """U+001F is whitespace to Python's `str.strip` and not to the reference's trim, so it survives
    step 2 and is replaced at step 3. Borrowing `strip` would have answered `Movies` here, and
    collided."""
    assert settle_name("\x1fMovies", ["Movies"]) == " Movies"
    assert settle_name("Movies\x1c", ["Movies"]) == "Movies "


# ------------------------------------------------------------------------------------------
# Step 3: a fixed set, replaced one for one
# ------------------------------------------------------------------------------------------


def test_the_replaced_set_is_the_references_list() -> None:
    """`"`, `<`, `>`, `|`, `:`, `*`, `?`, `\\`, `/`, the null character and 1 to 31 - and nothing
    else, so `.`, `'` and a non-breaking space inside a name are kept."""
    assert frozenset('"<>|:*?\\/') | {chr(code) for code in range(32)} == REPLACED_IN_NAMES
    assert settle_name('a"b<c>d|e:f*g?h\\i/j\x00k\x07l', []) == "a b c d e f g h i j k l"
    assert settle_name("Mr. O'Brien\u00a0Films", []) == "Mr. O'Brien\u00a0Films"


# ------------------------------------------------------------------------------------------
# Step 4: compared exactly, numbered from 2
# ------------------------------------------------------------------------------------------


def test_a_free_name_is_kept() -> None:
    assert settle_name("Movies", ["Music", "Shows"]) == "Movies"


def test_a_taken_name_is_numbered_from_two_with_nothing_between() -> None:
    assert FIRST_NUMBER == 2
    assert settle_name("Movies", ["Movies"]) == "Movies2"
    assert settle_name("Movies", ["Movies", "Movies2"]) == "Movies3"


def test_numbering_skips_only_what_is_taken() -> None:
    """`Movies2` taken and `Movies` free is `Movies`; a gap in the numbers is not filled past the
    first free one."""
    assert settle_name("Movies", ["Movies2"]) == "Movies"
    assert settle_name("Movies", ["Movies", "Movies3"]) == "Movies2"


def test_names_compare_with_case() -> None:
    """`movies` beside `Movies` is a library of its own, measured on the reference
    `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`."""
    assert settle_name("movies", ["Movies"]) == "movies"
    assert settle_name("Movies", ["movies", "MOVIES"]) == "Movies"


def test_names_compare_exactly_and_not_under_one_unicode_form() -> None:
    """Exactly means code point for code point: a decomposed accent is not the composed one."""
    composed, decomposed = "Am\u00e9lie", "Ame\u0301lie"
    assert settle_name(decomposed, [composed]) == decomposed


def test_the_comparison_is_made_on_the_cleaned_name() -> None:
    """Steps 2 and 3 come before step 4, so a padded or dirty spelling of a taken name collides."""
    assert settle_name("  Movies  ", ["Movies"]) == "Movies2"
    assert settle_name("Mo/vies", ["Mo vies"]) == "Mo vies2"
