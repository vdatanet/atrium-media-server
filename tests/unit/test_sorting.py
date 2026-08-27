# SPDX-License-Identifier: GPL-3.0-or-later
"""The two sort-name derivations, against the fifteen cases measured on the reference.

`[probe: tools/probe_sort_names.py, Jellyfin 10.11.11, 2026-08-26]`

**Two of these rows exist to fail when somebody tidies the function.** `Rock & Roll` keeps a double
space and `S.W.A.T.` a trailing one, because steps 3 to 5 of spec section 3.7.1 neither trim nor
collapse. Collapsing them is the natural thing to do, it looks like an obvious bug fix, and it
silently reorders every name in the library containing a removed character. If one of those two
assertions is in your way, it is doing its job - read behaviours.md section 2.6 before changing it.

Everything goes through `sort_name`, the one public entry point, rather than reaching for the base
derivation directly. That is what the tests for `Audio`, `Episode` and `Season` are really checking:
not the formulas, which are simple, but that the dispatcher does not fall through to the rule that
would reorder every album in the library.
"""

from __future__ import annotations

import pytest

from atrium.domain.items import Item, ItemType
from atrium.domain.sorting import SortRules, sort_name

SPACE = " "

#: (name, expected sort name, what the row isolates). The fifteen the probe sent, including the
#: ASCII control for the diacritic case - spec section 3.7.1's table prints fourteen because that
#: control says nothing on its own, and it is here because the measurement included it.
MEASURED: list[tuple[str, str, str]] = [
    ("The Matrix", "matrix", "article at the start"),
    ("Matrix The", "matrix", "and at the end"),
    ("Once The Time", "once time", "and in the middle"),
    ("A Bridge", "bridge", "single-letter article"),
    ("Amelie", "amelie", "the ASCII control for the row below"),
    ("Amélie", "amelie", "diacritics folded"),
    ("iRobot", "irobot", "case normalised"),
    (
        "2 Fast 2 Furious",
        "0000000002 fast 0000000002 furious",
        "EVERY digit run, not just the first",
    ),
    ("10 Things", "0000000010 things", "which is what makes 2 sort before 10"),
    ("Wall-E", "walle", "character removed"),
    ("Rock & Roll", "rock" + SPACE * 2 + "roll", "TWO SPACES - nothing collapses them"),
    ("Don't Look Up", "dont look up", "apostrophe removed"),
    ("S.W.A.T.", "s w a t" + SPACE, "TRAILING SPACE - nothing trims it"),
    ("100% Wolf", "0000000100" + SPACE * 2 + "wolf", "replacement and padding together"),
    ("  Padded  ", "padded", "trimmed at step 1, before anything else"),
]


def named(name: str, item_type: ItemType = ItemType.MOVIE, **fields: object) -> Item:
    return Item(id="a" * 32, type=item_type, name=name, library_id="b" * 32, **fields)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------
# Section 3.7.1 - the base derivation
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected", "rule"), MEASURED, ids=[rule for _, _, rule in MEASURED]
)
def test_the_measured_cases(name: str, expected: str, rule: str) -> None:
    assert sort_name(named(name)) == expected


def test_the_double_space_survives() -> None:
    """Spelled out separately from the table, because a table row is easy to edit without reading.

    `Rock & Roll` -> `rock  roll`. The ampersand is removed and the spaces around it are not, so
    two spaces remain. An implementation that collapsed them would sort this name differently from
    the reference, and only this name and its kind.
    """
    assert sort_name(named("Rock & Roll")) == "rock  roll"
    assert "  " in sort_name(named("Rock & Roll"))


def test_the_trailing_space_survives() -> None:
    """`S.W.A.T.` -> `s w a t `. The final full stop becomes a space and nothing trims it."""
    assert sort_name(named("S.W.A.T.")) == "s w a t "
    assert sort_name(named("S.W.A.T.")).endswith(" ")


def test_padding_makes_two_sort_before_ten() -> None:
    """The whole purpose of step 5, asserted as an ordering rather than as two strings."""
    assert sort_name(named("2 Fast 2 Furious")) < sort_name(named("10 Things"))


def test_without_padding_the_ordering_would_be_wrong() -> None:
    """The counter-case, so the test above cannot pass for the wrong reason."""
    unpadded = SortRules(digit_pad=0)
    assert sort_name(named("2 Fast"), rules=unpadded) > sort_name(
        named("10 Things"), rules=unpadded
    )


def test_the_lists_are_configuration_and_are_honoured() -> None:
    """An operator may change them; a name that sorts oddly may be a server, not a bug here."""
    assert sort_name(named("The Matrix"), rules=SortRules(articles=())) == "the matrix"
    assert sort_name(named("Wall-E"), rules=SortRules(removed=())) == "wall-e"


# ------------------------------------------------------------------------------------------
# Section 3.7.2 - the three types that replace it
# ------------------------------------------------------------------------------------------


def test_audio_pads_disc_and_track_to_four_and_keeps_the_raw_name() -> None:
    track = named("The Song", ItemType.AUDIO, parent_index_number=1, index_number=3)
    assert sort_name(track) == "0001 - 0003 - The Song"


def test_episode_pads_season_to_three_and_episode_to_four() -> None:
    """The asymmetry is real. It reads like a typo and it is the measured behaviour."""
    episode = named("Pilot", ItemType.EPISODE, parent_index_number=1, index_number=2)
    assert sort_name(episode) == "001 - 0002 - Pilot"


def test_season_is_the_number_alone() -> None:
    assert sort_name(named("Season 4", ItemType.SEASON, index_number=4)) == "0004"


def test_a_missing_number_contributes_no_segment_rather_than_zeros() -> None:
    """Section 3.7.2, and the reason the prefix is built piece by piece rather than formatted."""
    assert sort_name(named("Loose Track", ItemType.AUDIO, index_number=3)) == "0003 - Loose Track"
    assert sort_name(named("Loose Track", ItemType.AUDIO)) == "Loose Track"


def test_a_season_with_no_number_keeps_its_name() -> None:
    assert sort_name(named("Specials", ItemType.SEASON)) == "Specials"


@pytest.mark.parametrize("item_type", [ItemType.AUDIO, ItemType.EPISODE])
def test_the_overriding_types_do_not_fall_through_to_the_base_rule(item_type: ItemType) -> None:
    """The expensive mistake, asserted directly: `The Song` must sort under T, not under S.

    One sort-name function for everything is what a careful implementer builds, and it reorders
    every album in the library. behaviours.md section 2.6, temptation 2.
    """
    item = named("The Song", item_type, parent_index_number=1, index_number=1)
    result = sort_name(item)
    assert result.endswith("The Song"), f"{item_type} lost the raw name to the base derivation"
    assert sort_name(named("The Song")) == "song", "the base rule would have stripped the article"


def test_season_drops_the_name_entirely_which_is_also_not_the_base_rule() -> None:
    """Season is the odd one: the number alone, and nothing else. Not a truncation - the formula.

    Parametrising it with Audio and Episode above would be wrong, and getting that wrong here is
    how somebody later "fixes" this function to append the name.
    """
    season = named("The Song", ItemType.SEASON, index_number=1)
    assert sort_name(season) == "0001"


def test_an_audio_item_keeps_its_article_where_a_movie_loses_one() -> None:
    """The same name, two types, two answers. This is the whole point of there being two rules."""
    fields = {"parent_index_number": 1, "index_number": 1}
    assert sort_name(named("The Song", ItemType.AUDIO, **fields)).endswith("The Song")
    assert sort_name(named("The Song", ItemType.MOVIE)) == "song"


# ------------------------------------------------------------------------------------------
# Section 3.7.3 - an explicit sort title
# ------------------------------------------------------------------------------------------


def test_an_explicit_sort_title_is_lowercased_and_padded_but_keeps_its_articles() -> None:
    assert sort_name(named("Anything"), forced="The 2 Towers") == "the 0000000002 towers"


def test_an_explicit_sort_title_replaces_the_override_too() -> None:
    """Section 3.7.3 says "for every type". 003 OQ-6 is open about whether that holds; this is the
    specification as written, and the one line that changes if the answer differs.
    """
    episode = named("Pilot", ItemType.EPISODE, parent_index_number=1, index_number=2)
    assert sort_name(episode, forced="First") == "first"


# ------------------------------------------------------------------------------------------
# Step 6, and what it cannot do
# ------------------------------------------------------------------------------------------


def test_diacritics_fold_to_their_base_letter() -> None:
    assert sort_name(named("Amélie")) == "amelie"
    assert sort_name(named("Åkerfeldt")) == "akerfeldt"


def test_a_letter_that_does_not_decompose_is_transliterated() -> None:
    """`ø` survives NFKD unchanged, so folding alone would leave it or drop it. 003 OQ-7."""
    assert sort_name(named("Sigur Røs")) == "sigur ros"
    assert sort_name(named("Straße")) == "strasse"


def test_what_neither_can_reach_is_dropped_rather_than_guessed() -> None:
    """Stable, which a partial guess would not be - the same name always sorts to the same place."""
    assert sort_name(named("Мир")) == ""


def test_the_result_of_the_base_rule_is_always_ascii() -> None:
    for name, _, _ in MEASURED:
        assert sort_name(named(name)).isascii()
