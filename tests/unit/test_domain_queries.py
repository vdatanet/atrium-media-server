# SPDX-License-Identifier: GPL-3.0-or-later
"""The query vocabulary: the three enums pinned to the specification, and every default.

Two things are asserted here that nothing else can catch.

**The `SortBy` vocabulary is a closed set**, and the test compares the whole set rather than
checking that each expected member exists. A member added by a well-meaning change - `Name`, say,
because it looks missing - is a key no reference server orders by, and `sortBy=Name` would quietly
work against Atrium and quietly do nothing against Jellyfin. Equality is what catches an addition;
containment is not.

**Every default is a row in a table**, and a field with no row fails. Defaults are the part of
this module a client sees without sending anything: `count=True` is the difference between a
scrollbar and no scrollbar, and `recursive=False` between one level and a whole library.
"""

from __future__ import annotations

import dataclasses
from enum import StrEnum
from typing import Any

import pytest

from atrium.domain.queries import Filter, ItemQuery, SortBy, SortOrder
from atrium.domain.user import User

#: spec 005 section 3.4, and behaviours section 2.5 - `[prior-probe: Jellyfin 10.11.11,
#: 2026-06-13]`. Spelled out rather than imported from the enum, which would make the test a
#: tautology.
SPEC_SORT_BY = {
    "SortName",
    "DateCreated",
    "PremiereDate",
    "PlayCount",
    "DatePlayed",
    "Random",
    "AlbumArtist",
    "Artist",
}

#: spec 005 section 3.3, tier 1.
SPEC_FILTERS = {"IsFavorite", "IsPlayed", "IsUnplayed", "IsResumable"}

MISSING = dataclasses.MISSING

#: Field name -> its default, or MISSING for a field that has none. Every field of `ItemQuery`
#: appears exactly once; the test below fails on a field that is absent here as loudly as on one
#: whose default changed.
DEFAULTS: dict[str, Any] = {
    "user": MISSING,
    "parent_id": None,
    "recursive": False,
    "include_types": None,
    "exclude_types": None,
    "media_types": None,
    "ids": None,
    "exclude_ids": None,
    "search_term": None,
    "name_starts_with": None,
    "name_starts_with_or_greater": None,
    "name_less_than": None,
    "genres": None,
    "genre_ids": None,
    "studio_ids": None,
    "artist_ids": None,
    "album_artist_ids": None,
    "album_ids": None,
    "person_ids": None,
    "years": None,
    "filters": frozenset(),
    "is_played": None,
    "is_favorite": None,
    "min_community_rating": None,
    "sort": (),
    "start_index": 0,
    "limit": None,
    "count": True,
}


def somebody() -> User:
    return User(id="a" * 32, name="somebody")


# ------------------------------------------------------------------------------------------
# The vocabularies
# ------------------------------------------------------------------------------------------


def test_sort_by_is_exactly_the_specified_vocabulary() -> None:
    assert {member.value for member in SortBy} == SPEC_SORT_BY, (
        "spec 005 section 3.4 and behaviours section 2.5 name eight keys. An extra member is a "
        "key no reference server orders by - it would work here and do nothing there."
    )


def test_sort_order_is_the_two_directions() -> None:
    assert {member.value for member in SortOrder} == {"Ascending", "Descending"}


def test_filter_is_exactly_the_four_tier_one_tokens() -> None:
    assert {member.value for member in Filter} == SPEC_FILTERS


def test_is_played_and_is_unplayed_are_both_present() -> None:
    """Absent means "either", which is a third state neither token expresses alone."""
    assert Filter.IS_PLAYED in Filter
    assert Filter.IS_UNPLAYED in Filter


@pytest.mark.parametrize("enum", [SortBy, SortOrder, Filter], ids=lambda e: e.__name__)
def test_a_member_serialises_as_the_reference_spells_it(enum: type[StrEnum]) -> None:
    """`StrEnum`, so a member *is* its wire spelling and no mapping can drift from it."""
    for member in enum:
        assert str(member) == member.value


# ------------------------------------------------------------------------------------------
# The defaults
# ------------------------------------------------------------------------------------------


def test_every_field_has_a_row_in_the_defaults_table() -> None:
    declared = {field.name for field in dataclasses.fields(ItemQuery)}
    assert declared == set(DEFAULTS), (
        "a field was added to or removed from ItemQuery without its default being stated here. "
        "The default is what a client gets by sending nothing, which is the case least likely to "
        "be covered anywhere else."
    )


@pytest.mark.parametrize("name", sorted(DEFAULTS))
def test_a_field_carries_the_default_the_table_states(name: str) -> None:
    field = next(f for f in dataclasses.fields(ItemQuery) if f.name == name)
    assert field.default_factory is MISSING, (
        f"{name} uses a default_factory. Every default in ItemQuery is an immutable value, and a "
        f"factory would mean one of them is not."
    )
    assert field.default == DEFAULTS[name]


def test_the_four_defaults_the_task_names() -> None:
    """Asserted on a constructed query as well as on the field metadata: a `__post_init__` or a
    slots interaction could make the two disagree, and it is the constructed one clients see.
    """
    query = ItemQuery(user=somebody())
    assert query.recursive is False
    assert query.start_index == 0
    assert query.count is True
    assert query.sort == ()


# ------------------------------------------------------------------------------------------
# Frozen, and no query without a user
# ------------------------------------------------------------------------------------------


def test_a_query_cannot_be_built_without_a_user() -> None:
    with pytest.raises(TypeError):
        ItemQuery()  # type: ignore[call-arg]


def test_a_query_is_frozen() -> None:
    query = ItemQuery(user=somebody())
    with pytest.raises(dataclasses.FrozenInstanceError):
        query.recursive = True  # type: ignore[misc]


def test_a_query_has_no_dict_to_grow_a_field_on() -> None:
    """`slots=True`, like every other domain record. A query that could carry an attribute the
    repository never reads is a query whose predicates are not all in one place.

    **The exception type differs across the interpreters this project supports**, so the assertion
    is that it raises rather than what it raises. On 3.14 a `@dataclass(frozen=True, slots=True)`
    answers an unknown attribute with `FrozenInstanceError`; on **3.12 it answers `TypeError:
    super(type, obj): obj must be an instance or subtype of type`** - the generated `__setattr__`
    reaching a stale `__class__` cell left by the class being rebuilt for slots. Verified on
    3.12.14 and 3.14.7, on a bare dataclass with no Atrium code in it. A known field raises
    `FrozenInstanceError` on both, which is why the frozen test above can be exact and this one
    cannot.
    """
    with pytest.raises((AttributeError, TypeError)):
        ItemQuery(user=somebody()).parent = "x"  # type: ignore[attr-defined]


def test_two_queries_with_the_same_values_are_equal() -> None:
    """The count is memoised per predicate set upstream eventually; equality is what makes that
    possible, and `frozenset`/`tuple` fields are what make equality hold.
    """
    user = somebody()
    left = ItemQuery(user=user, include_types=frozenset(), ids=("a", "b"))
    right = ItemQuery(user=user, include_types=frozenset(), ids=("a", "b"))
    assert left == right
