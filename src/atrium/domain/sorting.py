# SPDX-License-Identifier: GPL-3.0-or-later
"""How every list is ordered.

There is not one rule. There are two, and the second is not a refinement of the first
(spec 003 section 3.7). Movies, series, albums and artists get a six-step normalisation;
`Audio`, `Episode` and `Season` **bypass all of it** for a zero-padded numeric prefix and the raw
name. Applying the first to the second is the single most expensive mistake available here: a track
called `The Song` would sort under `s` rather than `T`, and every album in the library would
reorder. docs/compatibility/behaviours.md section 2.6.

**`sort_name` is the only public function**, and that is the design rather than an interface
preference. A codebase with one public `normalise()` beside a public `numeric_prefix()` invites a
caller to pick, and the wrong pick is silent - nothing raises, nothing logs, the library is simply
in a different order than the reference's. Here there is nothing to pick.

**Nothing trims or collapses whitespace**, at any step. `Rock & Roll` keeps its double space and
`S.W.A.T.` its trailing one, because steps 3 to 5 neither trim nor collapse and the reference does
not either. The tests assert those artefacts with the characters spelled out, because tidying this
function is the natural thing to do and doing it silently reorders every name containing a removed
character.

Measured: `[probe: tools/probe_sort_names.py, Jellyfin 10.11.11, 2026-08-26]`, 15 of 15.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from atrium.domain.items import Item, ItemType


@dataclass(frozen=True, slots=True)
class SortRules:
    """The three lists and the width, which are server configuration rather than protocol.

    An operator may change them, so a name that sorts unexpectedly is not automatically a bug in
    this module - it may be a server whose lists differ. The defaults reproduce every measured
    case.
    """

    articles: tuple[str, ...] = ("the", "a", "an")
    removed: tuple[str, ...] = (",", "&", "-", "{", "}", "'")
    replaced: tuple[str, ...] = (".", "+", "%")
    digit_pad: int = 10
    """Ten. Part of the contract, not a detail: a different width produces a different ordering
    between two names whose digit runs differ in length, which is the whole mechanism by which
    `2 Fast` sorts before `10 Things`.
    """


DEFAULT_RULES: Final = SortRules()

#: (parent width, index width, separator) for the three types that replace the base derivation.
#:
#: **The widths are asymmetric and that is not a transcription error**: an episode's *season* is
#: three digits while its *episode number* is four. It reads like a typo every time.
#: `[source: MediaBrowser.Controller/Entities/Audio/Audio.cs:94-98,
#:  MediaBrowser.Controller/Entities/TV/Episode.cs:238-242,
#:  MediaBrowser.Controller/Entities/TV/Season.cs:149-152 @ v10.11.11]`
_OVERRIDES: Mapping[ItemType, tuple[int, int | None, str]] = {
    ItemType.AUDIO: (4, 4, " - "),  # disc, track
    ItemType.EPISODE: (3, 4, " - "),  # season, episode
    ItemType.SEASON: (4, None, ""),  # the season number alone, and nothing else
}

#: Latin letters that survive NFKD with no ASCII decomposition, so folding alone leaves them.
#:
#: **This table is ours and it is not measured.** Section 3.7.1 step 6 says "transliterate anything
#: still outside ASCII", and the only case the probe measured was `Amélie` - which the fold handles
#: on its own, because `é` decomposes. What the reference does with `ø`, `ß` or a Cyrillic name is
#: spec 003 OQ-7, opened by this module. Until it is answered these are the obvious readings, and
#: anything still outside ASCII afterwards is dropped rather than guessed at.
_TRANSLITERATIONS: Mapping[str, str] = {
    "ø": "o",
    "đ": "d",
    "ð": "d",
    "ł": "l",
    "ß": "ss",
    "æ": "ae",
    "œ": "oe",
    "þ": "th",
    "ħ": "h",
    "\u0131": "i",  # dotless i, spelled by codepoint: it is indistinguishable from `i` here
}


def sort_name(item: Item, *, forced: str | None = None, rules: SortRules = DEFAULT_RULES) -> str:
    """The sort name for an item. The only entry point, deliberately.

    `forced` is an explicit sort title from metadata (004). Section 3.7.3 says it replaces the
    derivation entirely, for every type - **including the three that override**, which is what
    003 OQ-6 is open about. Implemented as the specification states it; if OQ-6 comes back
    differently, this is the one line that changes.
    """
    if forced is not None:
        return _forced(forced, rules)

    override = _OVERRIDES.get(item.type)
    if override is not None:
        return _numeric_prefix(item, override)
    return _normalised(item.name, rules)


# ----------------------------------------------------------------------------------------------
# Section 3.7.1 - the base derivation, in six ordered steps
# ----------------------------------------------------------------------------------------------


def _normalised(name: str, rules: SortRules) -> str:
    """The six steps, in order. The order is part of the contract: step 1 trims before anything
    else can see the whitespace, and step 5 pads digits that step 4 may just have separated.
    """
    sortable = name.strip().lower()  # 1
    sortable = _without_articles(sortable, rules.articles)  # 2
    for character in rules.removed:  # 3
        sortable = sortable.replace(character, "")
    for character in rules.replaced:  # 4
        sortable = sortable.replace(character, " ")
    sortable = _padded(sortable, rules.digit_pad)  # 5
    return _folded(sortable)  # 6


def _without_articles(sortable: str, articles: tuple[str, ...]) -> str:
    """Step 2: from the start when followed by a space, from anywhere when surrounded by spaces,
    and from the end when preceded by one.

    All three positions, which is the part a reimplementation from intuition gets wrong: `Matrix
    The` and `Once The Time` both lose their article, and only the leading case is obvious.
    """
    for article in articles:
        if sortable.startswith(f"{article} "):
            sortable = sortable[len(article) + 1 :]
        sortable = sortable.replace(f" {article} ", " ")
        if sortable.endswith(f" {article}"):
            sortable = sortable[: -(len(article) + 1)]
    return sortable


def _padded(sortable: str, width: int) -> str:
    """Step 5: left-pad **every** run of digits, not only a leading one.

    Numeric ordering here is not numeric comparison - it is lexical comparison over zero-padded
    runs, which is why `2 Fast 2 Furious` pads both twos and why the width is part of the contract.

    `isdecimal` rather than `isdigit`: C#'s `char.IsDigit` is the Unicode Nd category exactly,
    while Python's `isdigit` also accepts superscripts, which would pad `R²` to something no
    ordering wants. Neither behaviour is measured - no name in the probe carried one.
    """
    out: list[str] = []
    run: list[str] = []
    for character in sortable:
        if character.isdecimal():
            run.append(character)
            continue
        if run:
            out.append("".join(run).rjust(width, "0"))
            run = []
        out.append(character)
    if run:
        out.append("".join(run).rjust(width, "0"))
    return "".join(out)


def _folded(sortable: str) -> str:
    """Step 6: fold diacritics, then transliterate what folding cannot reach.

    Anything still outside ASCII after both is dropped. That is a decision rather than a rule: see
    `_TRANSLITERATIONS` and 003 OQ-7. Dropping is at least stable - the same name always sorts to
    the same place - which a partial guess would not be.
    """
    expanded = "".join(_TRANSLITERATIONS.get(character, character) for character in sortable)
    decomposed = unicodedata.normalize("NFKD", expanded)
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return "".join(c for c in without_marks if c.isascii())


# ----------------------------------------------------------------------------------------------
# Section 3.7.2 - the three types that replace it
# ----------------------------------------------------------------------------------------------


def _numeric_prefix(item: Item, widths: tuple[int, int | None, str]) -> str:
    """A zero-padded prefix and the **raw** name: no lowercasing, no articles, no folding, no pad.

    A missing number contributes no segment at all rather than a run of zeros, which is why this
    builds the prefix piece by piece instead of formatting a template.
    """
    parent_width, index_width, separator = widths

    if index_width is None:  # Season: the number alone, and nothing else
        season = item.index_number
        return f"{season:0{parent_width}d}" if season is not None else item.name

    prefix = ""
    if item.parent_index_number is not None:
        prefix += f"{item.parent_index_number:0{parent_width}d}{separator}"
    if item.index_number is not None:
        prefix += f"{item.index_number:0{index_width}d}{separator}"
    return prefix + item.name


# ----------------------------------------------------------------------------------------------
# Section 3.7.3 - an explicit sort title
# ----------------------------------------------------------------------------------------------


def _forced(title: str, rules: SortRules) -> str:
    """Lowercased and digit-padded, but **not** article-stripped.

    Section 3.7.3 says only those three things. It is silent on the removed and replaced character
    sets, so neither is applied: an explicit sort title is something a human wrote on purpose, and
    the one documented difference from the base rule is that its words are left alone.
    """
    return _padded(title.strip().lower(), rules.digit_pad)


__all__ = ["DEFAULT_RULES", "SortRules", "sort_name"]
