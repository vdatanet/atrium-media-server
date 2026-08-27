# SPDX-License-Identifier: GPL-3.0-or-later
"""A title and a year, out of a name somebody's download client chose.

Real filenames carry the work's title, its year, and then a paragraph of release metadata:
resolution, source, codec, audio format, language, and whoever encoded it. **A third of one real
library's films carried that noise** - 527 of 1,557 filenames
`[read: Jellyfin 10.11.11, 2026-08-27]`. Getting a title out of it is most of what naming is.

**Written from the rules, not transcribed from the reference's expressions** (Principle IV). The
reference keeps a large table of regular expressions; that table is its implementation, and the
behaviour is what `tests/corpus/naming.yaml` says it is. The patterns here are whatever makes those
rows pass, which is the inversion 003 plan section 1 chose deliberately.

Two rules do most of the work, and both exist because of a row that would otherwise fail:

* **A year at the start of a name is part of the title.** `2001 A Space Odyssey (1968)` and
  `1917 (2019)` are films whose titles are years, and the release year conventionally *follows* the
  title. So a bare leading number is never taken as the year.
* **Tags are matched as whole words.** `Hard Candy` and `Web of Lies` are real films, and a rule
  that matched `HD` or `WEB` anywhere inside a token would rename both of them.

**Measured against 1,557 real filenames** from a live reference, which is where three of the rules
below come from: 0 crashes, 0 empty titles, and 8 names (0.5%) whose title still carries release
noise. Before that run it was 1 empty title and 46 noisy ones.

The 8 that remain are two known limits, recorded rather than chased:

1. **Dots and spaces tied as separators.** `Title.(Director,.1947).BDRip.1080p` has as many spaces
   as dots, so neither wins and the dots stay glued. Breaking the tie towards dots would change how
   every space-separated name tokenises, which is a much larger blast radius than the eight names
   it would fix.
2. **Noise in the middle of a name whose last token is not a recognised tag.**
   `Mara X265 www pctnew org` keeps its codec because trailing-tag removal stops at `org`. Removing
   tags from anywhere in a name would gut titles that legitimately contain one of these words.

Both are titles that 004 replaces from metadata anyway. Neither is a reason to make the rules
looser, which is the direction that damages real titles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

#: The range a four-digit number has to be in to be a release year at all. Outside it the number is
#: part of the title, brackets and all - `The Film (1899)` keeps its bracket.
EARLIEST_YEAR = 1900
LATEST_YEAR = 2099

#: A token that is a year, with or without the brackets it usually wears.
_YEAR = re.compile(r"\A(?P<open>[(\[])?(?P<year>\d{4})(?P<close>[)\]])?\Z")

#: Release-tag vocabulary, matched against a **whole token** or against the part of one before its
#: first dash - so `x264-GROUP` is a tag and `Web of Lies` is not.
#:
#: Deliberately conservative. Every entry is a term that has no other meaning in a film title, and
#: bare `web`, `hd` and `sd` are **absent on purpose**: they are ordinary English, and the corpus
#: carries `Web of Lies` and `Hard Candy` to keep them out.
_TAGS = frozenset(
    {
        # resolution
        "480p",
        "540p",
        "576p",
        "720p",
        "1080p",
        "1080i",
        "2160p",
        "4320p",
        "4k",
        "8k",
        "uhd",
        # source
        "bluray",
        "blu-ray",
        "bdrip",
        "brrip",
        "bdremux",
        "remux",
        "web-dl",
        "webdl",
        "webrip",
        "hdtv",
        "pdtv",
        "dvdrip",
        "dvdscr",
        "hdrip",
        "cam",
        "telesync",
        "hddvd",
        # video codec
        "x264",
        "x265",
        "h264",
        "h265",
        "hevc",
        "avc",
        "xvid",
        "divx",
        "vp9",
        "av1",
        "10bit",
        "8bit",
        "hdr",
        "hdr10",
        "dolbyvision",
        "dovi",
        # audio
        "aac",
        "ac3",
        "eac3",
        "dd",
        "ddp",
        "dts",
        "dts-hd",
        "truehd",
        "atmos",
        "flac",
        "mp3",
        "opus",
        "2 0",
        "5 1",
        "7 1",
        # other
        "proper",
        "repack",
        "internal",
        "limited",
        "extended",
        "unrated",
        "uncut",
        "imax",
        "multi",
        "dual",
        "subs",
        "sub",
        "dubbed",
        "rip",
        # Language markers, which sit in the same bracket runs as the codecs. Measured on a
        # Spanish-language library, where every one of the 46 noisy titles carried one.
        "castellano",
        "latino",
        "espanol",
        "español",
        "ingles",
        "inglés",
        "vose",
        "vos",
        # Language names, which appear inside the same bracket runs. Safe as tags because a title
        # is only ever trimmed of them from its *end*, so `The English Patient` keeps its middle.
        "spanish",
        "english",
        "french",
        "german",
        "italian",
        "portuguese",
        "japanese",
        "korean",
        "chinese",
        "russian",
        "catalan",
    }
)

#: One bracketed group, not nested. Filenames glue several together with no space between them,
#: which is why this matches groups rather than counting depth across whitespace tokens.
_GROUP = re.compile(r"[\[({][^\[\]({})]*[\])}]")

#: What separates the words inside such a group. A bracket run uses whatever it likes.
_INNER_SEPARATORS = re.compile(r"[\s.,+_/-]+")

#: A tag that carries a channel count or a bit depth glued to it: `ddp5.1`, `dts-hd`, `h.264`,
#: `dd5.1`. Matched as a whole token, so a title containing a decimal is untouched.
_TAG_SHAPES = re.compile(
    r"""\A(?:
          (?:dd|ddp|dts|ac3|eac3|truehd|aac|flac)[.\s-]?\d(?:[.\s]\d)?   # ddp5.1, dd5.1, dts 5.1
        | h[.\s-]?26[45]                                                  # h.264, h 265
        | \d{3,4}p                                                        # 1080p, 2160p
        | \d(?:[.\s]\d)                                                   # a bare 5.1
        )\Z""",
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class CleanName:
    """What a path can say about a work on its own, before any metadata is fetched."""

    name: str
    year: int | None = None


def clean_name(path: str) -> CleanName:
    """The title and year of the file at `path`, from its own name.

    Never raises. An unrecognisable name is a `CleanName` with a title and no year, which is what
    plan section 5 requires and what the reference produces too - a scan that threw on a strange
    filename would abort on somebody's library rather than on ours.
    """
    return from_text(PurePosixPath(path).name.rsplit(".", 1)[0] if "." in path else path)


def from_text(text: str) -> CleanName:
    """The same, from a name that is already free of its directory and extension.

    Separate because a folder name goes through exactly this and has no extension to strip: T11
    needs `The Film (1999)` cleaned the same way `The Film (1999).mkv` is.
    """
    tokens = _tokens(cut_at_release_metadata(text))
    if not tokens:
        return CleanName(name=text.strip())

    index = _year_index(tokens)
    if index is None:
        return CleanName(name=_join(_without_tags(tokens)), year=None)

    year = int(_YEAR.match(tokens[index])["year"])  # type: ignore[index]
    # Everything before the year is the title. Everything after it is release metadata, whether or
    # not this module recognises each term - which is what makes an unknown tag harmless.
    before = _without_tags(tokens[:index])
    if before:
        return CleanName(name=_join(before), year=year)

    # Nothing before it. A leading `(2015) The Film ...` is a real convention, and taking "what
    # comes before the year" literally returns an **empty title** - worse than any wrong title,
    # because an item with no name is one nothing can find. Measured: one film in 1,557 was named
    # this way, and it produced exactly that.
    return CleanName(name=_join(_without_tags(tokens[index + 1 :])) or text.strip(), year=year)


def is_tag(token: str) -> bool:
    """Whether one token is release metadata rather than part of a title."""
    lowered = token.casefold().strip("()[]{}")
    if not lowered:
        return False
    if lowered in _TAGS or _TAG_SHAPES.match(lowered):
        return True
    # `x264-GROUP`: the release group is glued to the codec with a dash. Only the part before the
    # first dash is consulted, and only if it is a tag on its own.
    head = lowered.split("-", 1)[0]
    return head != lowered and (head in _TAGS or bool(_TAG_SHAPES.match(head)))


def _tokens(text: str) -> list[str]:
    """Split into words, treating dots and underscores as spaces where they are the separator.

    `The.Film.1999.1080p` is one convention and `The Film (1999) DDP5.1 H.264` is another. Telling
    them apart by "does it contain a space" is not enough: real names mix both, and
    `El bazar de las sorpresas.(Ernst.Lubitsch,.1940)` has spaces *and* uses dots to separate its
    words. So the test is which character is **doing the separating** - whichever there are more of.

    A name that mostly uses spaces keeps its dots, which is what leaves `DDP5.1`, `H.264` and the
    middle dot in `WALL·E` intact for the tag rules to match on.
    """
    text = text.strip()
    if text.count(".") > text.count(" ") or text.count("_") > text.count(" "):
        text = text.replace(".", " ").replace("_", " ")
    return [token for token in text.split() if token]


def cut_at_release_metadata(text: str) -> str:
    """Everything before the first bracketed group that contains a release tag.

    Real filenames end in a run of them, and the convention is title first, then the run:
    `Codigo 8 [1080p][Castellano][wWw.SomeSite.NL]`. Measured: **46 of 1,557 films** kept release
    noise in their title without this, and the run was the shape of nearly all of them.

    Done on the **text** rather than on tokens, which is the second attempt. Token-level bracket
    counting looked right and missed the common case entirely: `[1080p][Castellano][wWw...]` is a
    single whitespace token whose brackets balance, so nothing ever saw three groups. Real
    filenames glue them together.

    **Only a bracket containing a tag cuts.** `The Film (1899)` keeps its bracket because 1899 is
    neither a year nor a tag, and a bracketed subtitle survives for the same reason - a rule that
    dropped every trailing bracket would take those with it.
    """
    for group in _GROUP.finditer(text):
        inner = group.group(0)[1:-1]
        if any(is_tag(part) for part in _INNER_SEPARATORS.split(inner) if part):
            return text[: group.start()]
    return text


def _year_index(tokens: list[str]) -> int | None:
    """Which token is the release year, if any.

    A bracketed year wins wherever it is: an operator who wrote `(1968)` meant the year. Failing
    that, the **last** bare year, because the convention is title first and year after - and never
    the first token, because `2001 A Space Odyssey` and `1917` are titles.
    """
    bare: list[int] = []
    for index, token in enumerate(tokens):
        match = _YEAR.match(token)
        if match is None or not EARLIEST_YEAR <= int(match["year"]) <= LATEST_YEAR:
            continue
        if match["open"] or match["close"]:
            return index
        if index > 0:
            bare.append(index)
    return bare[-1] if bare else None


def _without_tags(tokens: list[str]) -> list[str]:
    """Drop the run of release tags at the end, and stop at the first token that is not one.

    From the end rather than everywhere, because a tag term appearing mid-title is far more likely
    to be a word - and removing it from the middle would leave a title nobody searches for.
    """
    kept = list(tokens)
    while kept and is_tag(kept[-1]):
        kept.pop()
    return kept


def _join(tokens: list[str]) -> str:
    return " ".join(tokens).strip(" -_")


__all__ = ["CleanName", "clean_name", "cut_at_release_metadata", "from_text", "is_tag"]
