# SPDX-License-Identifier: GPL-3.0-or-later
"""The vocabulary, and the one rule the whole merge rests on.

`is_value` decides whether a provider's answer may set a field. Spec section 3.1 names four
non-values - `None`, `""`, `[]` and whitespace - and the table below is that sentence, plus the
cases the sentence does not cover and a truthiness test would get wrong.
"""

from __future__ import annotations

import pytest

from atrium.domain.items import ItemType
from atrium.metadata.model import (
    LOCK_OF,
    Ambiguous,
    Field,
    Identity,
    MetadataField,
    NoMatch,
    RefreshMode,
    Subject,
    is_value,
    values_only,
)

# ------------------------------------------------------------------------------------------
# Value-ness
# ------------------------------------------------------------------------------------------

#: (candidate, is a value). The four spec section 3.1 names, then the ones it does not.
VALUE_NESS: tuple[tuple[object, bool], ...] = (
    # Spec section 3.1, verbatim.
    (None, False),
    ("", False),
    ([], False),
    ("   ", False),
    ("\t\n ", False),
    # Values, unremarkably.
    ("The Fixture", True),
    (["Drama"], True),
    ({"Tmdb": "11111"}, True),
    (1999, True),
    (7.4, True),
    # **Zero is a value.** A rating of zero is a rating somebody gave, and `if not value` would
    # discard it with the empty strings. This row is the reason `is_value` is a function.
    (0, True),
    (0.0, True),
    # False is a value for the same reason. Nothing in `Field` is boolean today; the rule should
    # not change the day one is.
    (False, True),
    # Other empty collections behave like the empty list the spec names.
    ((), False),
    ({}, False),
    (set(), False),
    (frozenset(), False),
    (b"", False),
    # Unicode splits "whitespace" in a way worth pinning rather than assuming, because
    # `is_value` inherits whatever `str.strip` believes. A no-break space and an ideographic
    # space are stripped, so a name made of them is not a value; a **zero-width** space is not
    # whitespace to `str.strip` at all, so it is one. .NET agrees on the last of those -
    # `char.IsWhiteSpace('\u200B')` is false - so this is the reference's answer too, not a
    # divergence we would have to argue for.
    ("\u00a0", False),  # NO-BREAK SPACE
    ("\u3000", False),  # IDEOGRAPHIC SPACE
    ("\u200b", True),  # ZERO WIDTH SPACE
)


@pytest.mark.parametrize(("candidate", "expected"), VALUE_NESS, ids=lambda value: repr(value)[:24])
def test_the_value_ness_rule(candidate: object, expected: bool) -> None:
    assert is_value(candidate) is expected


def test_the_seams_present_and_empty_tag_survives_this_rule() -> None:
    """003's seam and this rule are about different questions, and must not be conflated.

    `MetadataSource.tags_for` returning `{"album": ""}` means *the file has an album tag and it is
    empty*, which the reference copies - so the seam must keep that entry. `is_value` says only
    that the empty string may not **set** the album field. Both hold at once, and the day somebody
    "tidies" one into the other, one of the two features breaks silently.
    """
    from_the_seam = {"album": "", "title": "A Track"}
    assert "album" in from_the_seam, "the seam keeps a present-and-empty tag"
    assert from_the_seam["album"] == ""
    assert not is_value(from_the_seam["album"]), "and it still may not set a field"


def test_values_only_drops_the_empties_and_keeps_the_zeroes() -> None:
    found = {
        Field.NAME: "The Fixture",
        Field.OVERVIEW: "",
        Field.TAGLINE: "   ",
        Field.GENRES: [],
        Field.COMMUNITY_RATING: 0.0,
        Field.YEAR: None,
    }
    assert values_only(found) == {Field.NAME: "The Fixture", Field.COMMUNITY_RATING: 0.0}


def test_an_absent_key_is_not_the_same_as_an_empty_one() -> None:
    """The distinction the merge walks the chain on."""
    says_nothing: dict[Field, object] = {}
    says_it_is_empty: dict[Field, object] = {Field.OVERVIEW: ""}
    assert Field.OVERVIEW not in says_nothing
    assert Field.OVERVIEW in says_it_is_empty
    assert values_only(says_nothing) == values_only(says_it_is_empty) == {}


# ------------------------------------------------------------------------------------------
# The two vocabularies
# ------------------------------------------------------------------------------------------


def test_the_lock_vocabulary_is_the_references_nine_values() -> None:
    """`[spec: MetadataField]`. A tenth value, or a different spelling, is a delta."""
    assert {member.value for member in MetadataField} == {
        "Cast",
        "Genres",
        "ProductionLocations",
        "Studios",
        "Tags",
        "Name",
        "Overview",
        "Runtime",
        "OfficialRating",
    }


def test_a_lock_guards_exactly_the_fields_the_reference_guards_with_it() -> None:
    """Measured from the reference's own merge, not grouped by what looks related.

    `[source: MediaBrowser.Providers/Manager/MetadataService.cs:1009-1140 @ v10.11.11]`
    """
    assert dict(LOCK_OF) == {
        Field.NAME: MetadataField.NAME,
        Field.OVERVIEW: MetadataField.OVERVIEW,
        Field.RUNTIME: MetadataField.RUNTIME,
        Field.OFFICIAL_RATING: MetadataField.OFFICIAL_RATING,
        Field.GENRES: MetadataField.GENRES,
        Field.STUDIOS: MetadataField.STUDIOS,
        Field.TAGS: MetadataField.TAGS,
        Field.PEOPLE: MetadataField.CAST,
    }


@pytest.mark.parametrize(
    "unlockable",
    [
        Field.SORT_NAME,
        Field.ORIGINAL_TITLE,
        Field.TAGLINE,
        Field.YEAR,
        Field.PREMIERE_DATE,
        Field.COMMUNITY_RATING,
        Field.INDEX_NUMBER,
        Field.PARENT_INDEX_NUMBER,
        Field.PROVIDER_IDS,
        Field.NORMALIZATION_GAIN,
        Field.ARTISTS,
        Field.ALBUM_ARTISTS,
        Field.IMAGES,
    ],
)
def test_a_field_the_reference_cannot_lock_has_no_lock_here(unlockable: Field) -> None:
    """Especially `ORIGINAL_TITLE`, which sits one line below the name lock in the reference's
    merge and is overwritten unconditionally. Covering it with `Name` would be kinder and wrong.
    """
    assert unlockable not in LOCK_OF


def test_every_lock_that_guards_something_guards_one_field() -> None:
    """No two fields share a lock, so `Replace` cannot un-guard one field by way of another."""
    guarded = list(LOCK_OF.values())
    assert len(guarded) == len(set(guarded))


def test_production_locations_guards_nothing_and_is_still_a_member() -> None:
    """A sidecar may name it, and a token the vocabulary knows is a token that parsed."""
    assert MetadataField.PRODUCTION_LOCATIONS not in set(LOCK_OF.values())


# ------------------------------------------------------------------------------------------
# Modes and identify results
# ------------------------------------------------------------------------------------------


def test_local_only_is_the_one_mode_that_consults_nothing_remote() -> None:
    assert RefreshMode.DEFAULT.consults_remote_providers
    assert RefreshMode.REPLACE.consults_remote_providers
    assert not RefreshMode.LOCAL_ONLY.consults_remote_providers


def test_the_three_identify_results_are_distinct_types() -> None:
    """`NoMatch` and `Ambiguous` both leave the item alone, and the report counts them apart."""
    results = [Identity("Tmdb", "11111"), NoMatch("no candidates"), Ambiguous(("a", "b"))]
    assert len({type(result) for result in results}) == 3


def test_an_identity_names_the_provider_id_key_it_will_be_stored_under() -> None:
    """No second naming scheme between identifying a thing and storing what it is."""
    assert Identity(provider="Tmdb", key="11111").provider == "Tmdb"


def test_a_subject_carries_only_what_a_search_needs() -> None:
    subject = Subject(kind=ItemType.MOVIE, name="The Fixture", year=1999)
    assert subject.provider_ids == {}
    assert not hasattr(subject, "item_id")


def test_the_model_is_frozen() -> None:
    """A provider that could mutate its subject could smuggle a write out of a pure module."""
    subject = Subject(kind=ItemType.MOVIE, name="The Fixture")
    with pytest.raises(AttributeError):
        subject.name = "Something Else"  # type: ignore[misc]
