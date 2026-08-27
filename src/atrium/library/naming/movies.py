# SPDX-License-Identifier: GPL-3.0-or-later
"""A path under a `movies` root, and the film it belongs to.

Three layouts (003 spec section 3.3): a bare file, a folder per film, and a folder per film whose
film is split across two files. The third is the one worth getting right - **a multi-part film
resolved as two items doubles a user's library**, which is the most visible scanning bug there is.

**The folder wins, and that is measured.** Where a film sits in its own directory, the directory's
name is the better title by a wide margin: on 1,557 real films the folder's cleaned name matched
what the reference resolved **1,087 times against the file's 457**
`[read: Jellyfin 10.11.11, 2026-08-27]`. The reason is mechanical rather than aesthetic - download
tools mangle filenames and leave directories alone. Of those films, 135 had a filename with **no
spaces at all** while its folder had them, and others were truncated mid-word or suffixed with the
site that served them.

That measurement also answers **003 OQ-4**, which asked what happens when a folder and a file
disagree. The interesting half of the question turns out not to arise: a folder and a file naming
two genuinely *different* works did not occur once in 1,480 one-film directories. What occurs is
the folder naming the same work more cleanly, and there the folder wins.

**A guard was tried and made it worse.** Preferring the folder only when the two names looked like
the same work scored 1,038 - below taking the folder outright - because the cleaner mangles one
side often enough that the similarity test fails on films where the folder is still right. The
simpler rule is the better one, and the case it cannot see on its own (a *genre* directory holding
many films, where the folder is not a title at all) is settled by `group` below, which can see the
siblings that a single path cannot.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import PurePosixPath

from atrium.library.naming.clean import CleanName, from_text

#: `- part1`, `- pt2`, `- cd1`, `- disc2`, at the very end of a name. Anchored to the end so that
#: `Part of the Family (1994)` keeps its title: the word only marks a part when it *is* the ending.
_NUMBERED_PART = re.compile(r"(?i)[\s._-]+(?:part|pt|cd|disc|disk)[\s._-]*(\d{1,2})\Z")

#: The `-a` / `-b` form section 3.3 names, allowed **only after a closing bracket or a digit**.
#:
#: Unanchored, this eats hyphenated titles: `Vitamin-C` would become part three. Requiring the
#: character before the marker to close a year or a bracket - which is what `The Film (1999)-a`
#: looks like and what `Vitamin-C` does not - is what keeps it from doing that.
_LETTERED_PART = re.compile(r"(?i)[)\]\d]\s*[-_]\s*([a-f])\Z")

#: A file name that says nothing: the folder is the only source of a title.
_PLACEHOLDERS = frozenset({"movie", "film", "video", "index", "main", "playback", "vide"})


@dataclass(frozen=True, slots=True)
class MovieParse:
    """One path's worth of film. `group` turns several of these into one item where they belong."""

    name: str
    year: int | None = None

    parts: tuple[str, ...] = ()
    """Every file backing this film, in part order. One entry until `group` merges them."""

    part_number: int | None = None
    """Which part *this file* is, where its name says so. `None` once merged, and for a
    film that was never split."""

    file_name: str = ""
    """What the file alone claimed, kept so that `group` can reconsider when it sees the siblings.

    A genre directory holding forty films is not a folder-per-film layout, and the only way to tell
    is to look at what else is in it - which a single path cannot do.
    """

    file_year: int | None = None


def parse_movie(relative_path: str) -> MovieParse:
    """The film at `relative_path`, from the path alone.

    Never raises: an unrecognisable name is a title and nothing else (plan section 5).
    """
    path = PurePosixPath(relative_path)
    stem = path.name.rsplit(".", 1)[0] if "." in path.name[1:] else path.name

    stem, part_number = _split_part(stem)
    from_file = from_text(stem)
    from_folder = from_text(path.parent.name) if path.parent.name else None

    chosen = _choose(from_folder, from_file)
    return MovieParse(
        name=chosen.name,
        year=chosen.year if chosen.year is not None else from_file.year,
        parts=(relative_path,),
        part_number=part_number,
        file_name=from_file.name,
        file_year=from_file.year,
    )


def group(parses: list[MovieParse]) -> list[MovieParse]:
    """Merge the parts of one film into one item, and undo the folder rule where it does not apply.

    Two things need the siblings that `parse_movie` cannot see:

    * **AC-4.** `The Film - part1.mkv` and `- part2.mkv` in one directory are one `Movie` with two
      sources. Grouped by directory and title, so two genuinely different films that happen to
      carry part markers are still two films.
    * **A genre directory is not a film.** `Action/The Film (1999).mkv` and forty siblings would
      all have taken `Action` as their title. A directory holding several *different* titles is
      not a folder-per-film layout, and every file in it goes back to its own name.
    """
    by_directory: dict[str, list[MovieParse]] = defaultdict(list)
    for parse in parses:
        by_directory[str(PurePosixPath(parse.parts[0]).parent)].append(parse)

    grouped: list[MovieParse] = []
    for directory, here in by_directory.items():
        if directory != "." and len({parse.file_name.casefold() for parse in here}) > 1:
            # Several different titles under one directory: it names a category, not a film.
            here = [
                replace(parse, name=parse.file_name or parse.name, year=parse.file_year)
                for parse in here
            ]
        grouped.extend(_merge_parts(here))
    return sorted(grouped, key=lambda parse: parse.parts[0])


def _merge_parts(here: list[MovieParse]) -> list[MovieParse]:
    whole = [parse for parse in here if parse.part_number is None]
    parted: dict[tuple[str, int | None], list[MovieParse]] = defaultdict(list)
    for parse in here:
        if parse.part_number is not None:
            parted[(parse.name.casefold(), parse.year)].append(parse)

    for group_of_parts in parted.values():
        ordered = sorted(group_of_parts, key=lambda parse: (parse.part_number or 0, parse.parts[0]))
        whole.append(
            replace(
                ordered[0],
                parts=tuple(part for parse in ordered for part in parse.parts),
                part_number=None,
            )
        )
    return whole


def _choose(from_folder: CleanName | None, from_file: CleanName) -> CleanName:
    """The folder, when there is one that says anything. Measured; see the module docstring."""
    if from_folder is None or not from_folder.name.strip():
        return from_file
    if from_file.name.casefold() in _PLACEHOLDERS:
        return from_folder
    return from_folder


def _split_part(stem: str) -> tuple[str, int | None]:
    numbered = _NUMBERED_PART.search(stem)
    if numbered:
        return stem[: numbered.start()], int(numbered.group(1))
    lettered = _LETTERED_PART.search(stem)
    if lettered:
        # `-a` is part one, `-b` part two. The character before it is kept: it closed the year.
        return stem[: lettered.start() + 1], ord(lettered.group(1).lower()) - ord("a") + 1
    return stem, None


__all__ = ["MovieParse", "group", "parse_movie"]
