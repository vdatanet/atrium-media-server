# SPDX-License-Identifier: GPL-3.0-or-later
"""A path under a `tvshows` root, and the episode it is.

Three levels, and **the middle one is often not a directory** (003 spec section 3.4). A season can
be a folder, or a number inside a filename, or neither - and none of those is an error.

**`1x02` is the dominant convention, not the exotic one.** On a real library of 917 episodes it
accounted for **902** of them against `S01E02`'s 15, and in both forms the numbers in the filename
agreed with what the reference resolved - 902 of 902 and 15 of 15, no disagreements
`[read: Jellyfin 10.11.11, 2026-08-27]`. Written from intuition this module would have treated
`S01E02` as the main case and `1x02` as a footnote, and been slow on 98% of a real library.

**Position resolves ambiguity, not preference** (section 3.4). The patterns are matched against the
**filename first** and only then against the directory, which is the whole of why a series called
`24` keeps its title: the digits in the directory name are never consulted while the filename still
has something to say. This is where naive scanners fail.

**The multi-episode patterns are tried before the single ones**, for the same structural reason:
`S01E02-E03` contains `S01E02`, so a scanner that checks the simple pattern first finds it, stops,
and turns one episode into one episode with the second silently discarded - which is AC-5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from atrium.library.naming.clean import cut_at_release_metadata, from_text, is_tag

#: `Specials` is season zero and is **not** an extras directory (003 spec section 3.4, AC-6).
SPECIALS = frozenset({"specials", "special", "season 0", "season 00", "season zero"})

#: How a season directory spells its number. `Season 2024` is a daily show's year.
_SEASON_DIRECTORY = re.compile(
    r"(?i)\A(?:season|series|s|temporada|staffel|saison)[\s._-]*(\d{1,4})\Z"
)

#: Ordered most specific first, and the order is load-bearing rather than tidy - see the module
#: docstring. Each yields (season, episode, end_episode), with None where the form does not say.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # S01E02-E03, S01E02-S01E03, S01E02E03: one episode spanning two numbers (AC-5).
    (
        "span",
        re.compile(
            r"(?i)s(\d{1,4})[\s._-]*e(\d{1,4})(?:[\s._-]*-?[\s._-]*(?:s\d{1,4}[\s._-]*)?e(\d{1,4}))"
        ),
    ),
    # 1x02-1x03, 1x02-03
    (
        "span_x",
        re.compile(
            r"(?i)(?<![\d])(\d{1,3})x(\d{1,3})[\s._-]*-[\s._-]*(?:\d{1,3}x)?(\d{1,3})(?![\d])"
        ),
    ),
    ("sxe", re.compile(r"(?i)s(\d{1,4})[\s._-]*e(\d{1,4})(?![\d])")),
    ("x", re.compile(r"(?i)(?<![\dx])(\d{1,3})x(\d{1,3})(?![\dx])")),
)

#: A daily show's episode is its date. Tried after the numbered forms, so `12x31` stays an episode.
_DATE = re.compile(r"(?<![\d])(\d{4})[.\-_](\d{2})[.\-_](\d{2})(?![\d])")

#: `E02`, `EP02` with no season beside it: the season comes from the directory.
_EPISODE_ONLY = re.compile(r"(?i)(?<![a-z0-9])e(?:p)?[\s._-]*(\d{1,4})(?![\d])")

#: What separates an episode's number from its title.
_TITLE_SEPARATORS = re.compile(r"\A[\s._-]+|[\s._-]+\Z")


@dataclass(frozen=True, slots=True)
class EpisodeParse:
    """What a path says about an episode.

    Every field is optional because every one of them can genuinely be absent from a path.
    """

    series: str = ""
    season: int | None = None
    episode: int | None = None

    end_episode: int | None = None
    """The last number a multi-episode file spans. `None` for the ordinary case; present, the item
    **is** both episodes rather than standing for them (AC-5)."""

    name: str | None = None
    date: str | None = None
    """`YYYY-MM-DD`, for a daily show whose episodes have no numbers."""


def parse_episode(relative_path: str) -> EpisodeParse:
    """The episode at `relative_path`, from the path alone. Never raises (plan section 5)."""
    path = PurePosixPath(relative_path)
    stem = path.name.rsplit(".", 1)[0] if "." in path.name[1:] else path.name
    directories = list(path.parts[:-1])

    season_from_directory, season_index = _season_from_directories(directories)
    series_directory = (
        directories[season_index - 1]
        if season_index > 0
        else (directories[-1] if directories and season_index < 0 else "")
    )
    series = from_text(series_directory).name if series_directory else ""

    found = _numbers(stem)
    if found is not None:
        season, episode, end_episode, remainder = found
        return EpisodeParse(
            series=series,
            season=season if season is not None else season_from_directory,
            episode=episode,
            end_episode=end_episode,
            name=_title(remainder),
        )

    date = _DATE.search(stem)
    if date is not None:
        return EpisodeParse(
            series=series,
            season=season_from_directory,
            date=f"{date.group(1)}-{date.group(2)}-{date.group(3)}",
            name=_title(stem[date.end() :]),
        )

    # Nothing numeric at all. A title and whatever the directories said, never an exception: an
    # unparseable name is one episode nobody can sort, not a library that fails to scan.
    return EpisodeParse(series=series, season=season_from_directory, name=_title(stem))


def season_of_directory(name: str) -> int | None:
    """The season number a directory spells, or None if it does not spell one."""
    if name.casefold().strip() in SPECIALS:
        return 0
    match = _SEASON_DIRECTORY.match(name.strip())
    return int(match.group(1)) if match else None


def _season_from_directories(directories: list[str]) -> tuple[int | None, int]:
    """The nearest season directory and where it sits, searched from the file outwards."""
    for offset, name in enumerate(reversed(directories)):
        season = season_of_directory(name)
        if season is not None:
            return season, len(directories) - 1 - offset
    return None, -1


def _numbers(stem: str) -> tuple[int | None, int | None, int | None, str] | None:
    """Season, episode, end episode and what follows - from the **filename**, in pattern order."""
    for kind, pattern in _PATTERNS:
        match = pattern.search(stem)
        if match is None:
            continue
        season, episode = int(match.group(1)), int(match.group(2))
        end = int(match.group(3)) if kind.startswith("span") else None
        # `S01E02-E03` and `1x02-03` both mean two consecutive numbers; a smaller second number is
        # not a span, it is something else that happened to match.
        if end is not None and end <= episode:
            end = None
        return season, episode, end, stem[match.end() :]

    only = _EPISODE_ONLY.search(stem)
    if only is not None:
        return None, int(only.group(1)), None, stem[only.end() :]
    return None


def _title(remainder: str) -> str | None:
    """The episode's own name, from whatever followed its number.

    `None` rather than an empty string when nothing is left, and `None` when what is left is
    release metadata - `The Series - S01E02 - 1080p x265` names no episode.
    """
    text = _TITLE_SEPARATORS.sub("", cut_at_release_metadata(remainder))
    if not text:
        return None
    kept = [token for token in text.split() if not is_tag(token)]
    while kept and is_tag(kept[-1]):
        kept.pop()
    joined = " ".join(kept).strip(" -_.")
    return joined or None


__all__ = ["SPECIALS", "EpisodeParse", "parse_episode", "season_of_directory"]
