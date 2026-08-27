# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-5, AC-6 and AC-7 by name, and the adversarial cases behind AC-7.

The corpus covers these too, and each of its rows says which criterion it is there for. These exist
because the acceptance map at T21 needs a *named* test per criterion - `test_the_corpus[series:…]`
is a parametrised id that a rename would silently change - and because AC-7 deserves more than one
row: a series called `24` is the case where a scanner that consults the directory too eagerly
produces a plausible, wrong answer on every episode of that series.

**Measured, against the 917 episodes of a live library**: season and episode were correct for all
917, with no crashes, none missing and none wrong `[read: Jellyfin 10.11.11, 2026-08-27]`.
"""

from __future__ import annotations

import pytest

from atrium.library.naming import parse_episode, season_of_directory

# ------------------------------------------------------------------------------------------
# AC-5: one item spanning two numbers
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "The Series/Season 01/The Series - S01E02-E03.mkv",
        "The Series/Season 01/The Series - S01E02E03.mkv",
        "The Series/Season 01/The Series - S01E02-S01E03.mkv",
        "The Series/Season 01/The Series - 1x02-1x03.mkv",
        "The Series/Season 01/The Series - 1x02-03.mkv",
    ],
)
def test_a_multi_episode_file_is_one_item_spanning_both_numbers(path: str) -> None:
    """AC-5. The failure is silent: `S01E02-E03` contains `S01E02`, so a scanner that tries the
    simple pattern first finds it, stops, and discards the second number with nothing to show.
    """
    episode = parse_episode(path)
    assert (episode.season, episode.episode, episode.end_episode) == (1, 2, 3)


def test_an_ordinary_episode_spans_nothing() -> None:
    """AC-5's control, without which the test above passes for a parser that spans everything."""
    assert parse_episode("The Series/Season 01/The Series - S01E02.mkv").end_episode is None


def test_a_second_number_that_is_not_larger_is_not_a_span() -> None:
    """`12-00 AM` in an episode title is not a range, and neither is anything counting down."""
    assert parse_episode("24/Season 01/24 - S01E01 - 12-00 AM.mkv").end_episode is None


# ------------------------------------------------------------------------------------------
# AC-6: Specials is season zero
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("directory", ["Specials", "specials", "Season 0", "Season 00"])
def test_specials_is_season_zero(directory: str) -> None:
    """AC-6. And `Specials` is emphatically not an extras folder - T8's walker keeps it."""
    assert season_of_directory(directory) == 0


def test_an_episode_in_specials_is_in_season_zero() -> None:
    assert parse_episode("The Series/Specials/The Series - A Special.mkv").season == 0


def test_a_special_with_its_own_numbers_keeps_them() -> None:
    episode = parse_episode("The Series/Specials/The Series - S00E01 - A Special.mkv")
    assert (episode.season, episode.episode) == (0, 1)


def test_season_zero_is_not_the_same_as_no_season() -> None:
    """`0` and `None` are different answers, and a falsy check would conflate them."""
    assert parse_episode("The Series/Specials/Anything.mkv").season == 0
    assert parse_episode("The Series/Anything.mkv").season is None


# ------------------------------------------------------------------------------------------
# AC-7: a series named with digits
# ------------------------------------------------------------------------------------------


def test_a_series_named_with_digits_keeps_its_title() -> None:
    """AC-7, and the reason spec section 3.4 says position resolves ambiguity: the pattern is
    matched against the **filename** first and only then against the directory.
    """
    episode = parse_episode("24/Season 01/24 - S01E01 - 12-00 AM.mkv")
    assert episode.series == "24"
    assert (episode.season, episode.episode) == (1, 1)


def test_the_title_digits_are_not_read_as_numbers_in_the_dominant_convention() -> None:
    """`1x02` is 902 of 917 real episodes, so AC-7 has to hold in that form too."""
    episode = parse_episode("24/Season 09/24 - 9x12.mkv")
    assert episode.series == "24"
    assert (episode.season, episode.episode) == (9, 12)


def test_a_series_named_with_a_year_shaped_number_keeps_it() -> None:
    """`1923` is a series. A title that looks like a year is still a title."""
    episode = parse_episode("1923/Season 01/1923 - S01E01.mkv")
    assert episode.series == "1923"
    assert (episode.season, episode.episode) == (1, 1)


def test_a_series_whose_directory_carries_a_year_loses_only_the_year() -> None:
    episode = parse_episode("The Series (2005)/Season 01/The Series (2005) - S01E02.mkv")
    assert episode.series == "The Series"


# ------------------------------------------------------------------------------------------
# The middle level is often not a directory
# ------------------------------------------------------------------------------------------


def test_a_season_with_no_directory_is_inferred_from_the_filename() -> None:
    """Section 3.4: the middle level is often not a directory, and that is not an error."""
    episode = parse_episode("The Series/The Series - S02E01.mkv")
    assert (episode.season, episode.episode) == (2, 1)


def test_an_episode_number_alone_takes_its_season_from_the_directory() -> None:
    episode = parse_episode("The Series/Season 03/The Series - E07.mkv")
    assert (episode.season, episode.episode) == (3, 7)


def test_the_filename_beats_the_directory_when_they_disagree() -> None:
    """Position, not preference. A file that says S02 inside a `Season 01` directory says S02."""
    episode = parse_episode("The Series/Season 01/The Series - S02E05.mkv")
    assert episode.season == 2


def test_a_name_with_no_numbers_at_all_is_not_an_error() -> None:
    """Plan section 5: a result with a title and nothing else, never an exception."""
    episode = parse_episode("The Series/Season 01/A Name With No Numbers.mkv")
    assert episode.episode is None
    assert episode.name == "A Name With No Numbers"


# ------------------------------------------------------------------------------------------
# Dates
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("written", ["2024-01-31", "2024.01.31", "2024_01_31"])
def test_a_daily_show_is_dated_rather_than_numbered(written: str) -> None:
    episode = parse_episode(f"The Daily Show/Season 2024/The Daily Show - {written}.mkv")
    assert episode.date == "2024-01-31"
    assert episode.episode is None


def test_a_numbered_episode_is_not_read_as_a_date() -> None:
    """`12x31` is season twelve, episode thirty-one, and the numbered forms are tried first."""
    episode = parse_episode("The Series/Season 12/The Series - 12x31.mkv")
    assert (episode.season, episode.episode) == (12, 31)
    assert episode.date is None
