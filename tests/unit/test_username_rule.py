# SPDX-License-Identifier: GPL-3.0-or-later
"""The username rule `POST /Startup/User` renames by (014 plan section 6.4).

**Written against the categories and not against a pattern**, because the reference's word class
and Python's `\\w` disagree at exactly the edges tested here: a combining mark and a connector are
word characters there and not here, and a superscript digit and a Roman numeral are word characters
here and not there. A transliterated pattern would pass the ASCII cases and get all four wrong.
"""

from __future__ import annotations

import re
import unicodedata

import pytest

from atrium.users.first_account import is_blank, is_valid_username


@pytest.mark.parametrize(
    "name",
    [
        "MyJellyfinUser",
        "joan",
        "J",
        "7",
        "Joan Vila",
        "o'brien",
        "first.last",
        "under_score",
        "dash-ed",
        "at@home",
        "plus+one",
        "Élodie",  # Ll/Lu beyond ASCII
        "ǅemal",  # Lt, a titlecase letter
        "ʰuser",  # Lm, a modifier letter
        "日本語",  # Lo
        "user\u0663",  # Nd outside ASCII: ARABIC-INDIC DIGIT THREE
    ],
)
def test_the_reference_categories_and_characters_are_accepted(name: str) -> None:
    assert is_valid_username(name)


def test_a_combining_mark_is_a_word_character() -> None:
    """`Mn`, which the reference's word class admits whole and Python's `\\w` does not."""
    name = "e\u0301mile"  # e + COMBINING ACUTE ACCENT
    assert unicodedata.category("\u0301") == "Mn"
    assert re.fullmatch(r"\w+", name) is None, "the premise: Python's \\w refuses it"
    assert is_valid_username(name)


def test_a_connector_is_a_word_character() -> None:
    """`Pc` beyond `_`: the reference admits the category, Python's `\\w` only the underscore."""
    name = "left\u203fright"  # UNDERTIE
    assert unicodedata.category("\u203f") == "Pc"
    assert re.fullmatch(r"\w+", name) is None, "the premise: Python's \\w refuses it"
    assert is_valid_username(name)


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("user\u00b2", "No"),  # SUPERSCRIPT TWO
        ("user\u216b", "Nl"),  # ROMAN NUMERAL TWELVE
        ("user\u0903", "Mc"),  # a spacing mark
    ],
)
def test_what_python_calls_a_word_character_and_the_reference_does_not_is_refused(
    name: str, category: str
) -> None:
    assert unicodedata.category(name[-1]) == category
    assert not is_valid_username(name)


@pytest.mark.parametrize("name", [" joan", "joan ", " joan ", " ", "  "])
def test_leading_and_trailing_spaces_are_refused(name: str) -> None:
    assert not is_valid_username(name)


@pytest.mark.parametrize("name", ["\tjoan", "joan\t", "jo\u00a0an", "jo\nan", "\njoan"])
def test_other_white_space_is_not_in_the_set_at_all(name: str) -> None:
    assert not is_valid_username(name)


def test_one_final_line_feed_is_admitted_after_a_valid_name() -> None:
    """The end anchor matches before a final line feed (plan section 6.4, amended 2026-09-14)."""
    assert is_valid_username("joan\n")
    assert not is_valid_username("joan\n\n")
    assert not is_valid_username("joan \n")
    assert not is_valid_username("\n")


@pytest.mark.parametrize("name", ["", "bad/name", "bad:name", "bad/name:here", "a<b", "a*b"])
def test_empty_slash_colon_and_other_punctuation_are_refused(name: str) -> None:
    """`/` and `:` together are the reading T1 took; each alone is refused by the same rule."""
    assert not is_valid_username(name)


@pytest.mark.parametrize("password", [None, "", " ", "\t\n", "\u00a0", "\u2028", "\u3000"])
def test_a_blank_password(password: str | None) -> None:
    assert is_blank(password)


@pytest.mark.parametrize("password", ["x", " x ", "\x1c"])
def test_a_password_that_is_not_blank(password: str) -> None:
    """`\\x1c` is white space to Python's `isspace` and not to the reference's test."""
    assert not is_blank(password)
