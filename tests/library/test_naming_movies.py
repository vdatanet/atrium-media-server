# SPDX-License-Identifier: GPL-3.0-or-later
"""AC-4, and the two decisions a single path cannot make.

The corpus in `tests/corpus/naming.yaml` is one path per row, which is what makes it a plain table
test with no fixtures on disk. Two things do not fit in that shape, and both are here:

* **AC-4** - `- part1.mkv` and `- part2.mkv` are *one* film with two sources. Knowing that means
  looking at both paths at once. Getting it wrong doubles a user's library, which is the most
  visible scanning bug there is.
* **A genre directory is not a film.** `Action/` holding forty films would give all forty the title
  `Action` under the folder-wins rule, and the only way to tell a category from a film is to look
  at what else is in the directory.
"""

from __future__ import annotations

from atrium.library.naming import group, parse_movie


def parsed(*paths: str) -> list:  # type: ignore[type-arg]
    return group([parse_movie(path) for path in paths])


# ------------------------------------------------------------------------------------------
# AC-4: one film, two files
# ------------------------------------------------------------------------------------------


def test_a_two_part_film_is_one_item_with_two_sources() -> None:
    films = parsed(
        "The Film (1999)/The Film (1999) - part1.mkv",
        "The Film (1999)/The Film (1999) - part2.mkv",
    )
    assert len(films) == 1, "a two-part film became two films, which doubles a user's library"
    assert films[0].parts == (
        "The Film (1999)/The Film (1999) - part1.mkv",
        "The Film (1999)/The Film (1999) - part2.mkv",
    )
    assert films[0].part_number is None, "a merged film is not itself a part"
    assert (films[0].name, films[0].year) == ("The Film", 1999)


def test_the_parts_come_back_in_order_whatever_order_they_arrived_in() -> None:
    """The order is what a player joins them in, so it is the order of the numbers."""
    films = parsed(
        "The Film (1999)/The Film (1999) - cd2.mkv",
        "The Film (1999)/The Film (1999) - cd1.mkv",
    )
    assert [path.rsplit("- ", 1)[1] for path in films[0].parts] == ["cd1.mkv", "cd2.mkv"]


def test_three_parts_are_still_one_film() -> None:
    films = parsed(*[f"The Film (1999)/The Film (1999) - part{n}.mkv" for n in (1, 2, 3)])
    assert len(films) == 1
    assert len(films[0].parts) == 3


def test_the_letter_form_groups_too() -> None:
    films = parsed(
        "The Film (1999)/The Film (1999)-a.mkv",
        "The Film (1999)/The Film (1999)-b.mkv",
    )
    assert len(films) == 1
    assert len(films[0].parts) == 2


def test_two_different_films_that_both_carry_part_markers_stay_two_films() -> None:
    """Grouped by title as well as by directory, so a shared folder cannot merge two works."""
    films = parsed(
        "Collection/The First Film (1999) - part1.mkv",
        "Collection/The First Film (1999) - part2.mkv",
        "Collection/The Second Film (2005) - part1.mkv",
        "Collection/The Second Film (2005) - part2.mkv",
    )
    assert len(films) == 2
    assert all(len(film.parts) == 2 for film in films)


def test_a_whole_film_beside_a_split_one_is_not_swallowed() -> None:
    films = parsed(
        "Collection/The First Film (1999) - part1.mkv",
        "Collection/The First Film (1999) - part2.mkv",
        "Collection/The Other Film (2005).mkv",
    )
    assert len(films) == 3 - 1
    assert sorted(len(film.parts) for film in films) == [1, 2]


def test_an_ordinary_film_is_one_item_with_one_source() -> None:
    films = parsed("The Film (1999).mkv")
    assert len(films) == 1
    assert films[0].parts == ("The Film (1999).mkv",)


# ------------------------------------------------------------------------------------------
# The folder rule, and where it stops applying
# ------------------------------------------------------------------------------------------


def test_a_directory_holding_one_film_gives_it_its_name() -> None:
    """Measured: the folder matched the resolved name 1,087 times against the file's 457."""
    films = parsed("The Film [BluRay 1080p]/TheFilmBD1080.www.somesite.org.mkv")
    assert films[0].name == "The Film"


def test_a_directory_holding_several_different_films_names_none_of_them() -> None:
    """A genre folder. Under the folder-wins rule alone, all three would be called `Action`.

    This is the case a single path cannot see, and the reason grouping exists rather than the
    folder rule being applied and left.
    """
    films = parsed(
        "Action/The First Film (1999).mkv",
        "Action/The Second Film (2005).mkv",
        "Action/The Third Film (2011).mkv",
    )
    assert sorted(film.name for film in films) == [
        "The First Film",
        "The Second Film",
        "The Third Film",
    ]
    assert not any(film.name == "Action" for film in films)


def test_a_genre_directory_still_groups_the_parts_inside_it() -> None:
    """Both rules at once: no folder title, and the two parts still make one film."""
    films = parsed(
        "Action/The First Film (1999) - part1.mkv",
        "Action/The First Film (1999) - part2.mkv",
        "Action/The Second Film (2005).mkv",
    )
    assert sorted((film.name, len(film.parts)) for film in films) == [
        ("The First Film", 2),
        ("The Second Film", 1),
    ]


def test_files_at_the_root_are_never_given_a_folder_name() -> None:
    films = parsed("The First Film (1999).mkv", "The Second Film (2005).mkv")
    assert sorted(film.name for film in films) == ["The First Film", "The Second Film"]


def test_the_result_is_ordered_so_two_scans_agree() -> None:
    """Determinism (spec section 3.8): the same set of paths gives the same list."""
    paths = ["B/The Second (2005).mkv", "A/The First (1999).mkv", "C/The Third (2011).mkv"]
    assert [film.parts[0] for film in parsed(*paths)] == [
        film.parts[0] for film in parsed(*reversed(paths))
    ]
