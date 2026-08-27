# SPDX-License-Identifier: GPL-3.0-or-later
"""The merge, cell by cell.

AC-10 and AC-11 are held here first, at engine level, and again end-to-end at T14. Twice on
purpose: this suite proves the rule, and that one proves the rule is the one being used.

The matrix is spec section 3.6 and plan section 6.1:

| | field locked | field empty on item | field has a value |
|---|---|---|---|
| **Default** | keep | fill | keep |
| **Replace** | keep | fill | overwrite |
| **Local only** | keep | fill from local sources only | keep |

Every one of those nine cells is a row in `THE_MATRIX`. What follows it is the part no matrix can
express: which fields a lock actually guards, and the four different things a list-valued field
does.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from atrium.domain.items import FILE_BACKED, IN_THE_TREE, ItemType
from atrium.metadata.merge import (
    CHAIN_OF,
    LIST_RULE,
    Current,
    ListRule,
    Source,
    SourceKind,
    merge,
)
from atrium.metadata.model import (
    LOCK_OF,
    Field,
    MetadataField,
    PersonCredit,
    PersonKind,
    RefreshMode,
)

LOCAL = SourceKind.NFO
REMOTE = SourceKind.REMOTE


def film(
    values: Mapping[Field, object] | None = None,
    *,
    locked: frozenset[MetadataField] = frozenset(),
    whole_item: bool = False,
) -> Current:
    return Current(
        kind=ItemType.MOVIE,
        values=dict(values or {}),
        locked_fields=locked,
        is_locked=whole_item,
    )


# ----------------------------------------------------------------------------------------------
# The matrix
# ----------------------------------------------------------------------------------------------

#: (mode, locked, what the item has, what the source offers, what the field becomes).
#: `...` means "unchanged" - the field is absent from the result.
THE_MATRIX: tuple[tuple[RefreshMode, bool, object, object, object], ...] = (
    # Default
    (RefreshMode.DEFAULT, True, "Mine", "Theirs", ...),
    (RefreshMode.DEFAULT, False, None, "Theirs", "Theirs"),
    (RefreshMode.DEFAULT, False, "Mine", "Theirs", ...),
    # Replace
    (RefreshMode.REPLACE, True, "Mine", "Theirs", ...),
    (RefreshMode.REPLACE, False, None, "Theirs", "Theirs"),
    (RefreshMode.REPLACE, False, "Mine", "Theirs", "Theirs"),
    # Local only, over a local source - identical to Default, because that is what it is
    (RefreshMode.LOCAL_ONLY, True, "Mine", "Theirs", ...),
    (RefreshMode.LOCAL_ONLY, False, None, "Theirs", "Theirs"),
    (RefreshMode.LOCAL_ONLY, False, "Mine", "Theirs", ...),
)


@pytest.mark.parametrize(("mode", "locked", "current", "offered", "expected"), THE_MATRIX)
def test_the_matrix(
    mode: RefreshMode, locked: bool, current: object, offered: object, expected: object
) -> None:
    """`NAME` because it is one of the eight fields a lock actually guards."""
    subject = film(
        {Field.NAME: current} if current is not None else {},
        locked=frozenset({MetadataField.NAME}) if locked else frozenset(),
    )
    changes = merge(subject, [Source(LOCAL, {Field.NAME: offered})], mode)
    if expected is ...:
        assert Field.NAME not in changes.values
    else:
        assert changes.values[Field.NAME] == expected


def test_a_locked_field_survives_replace(tmp_path: object) -> None:
    """AC-10, at engine level. The row above says it; this says it by name so a reader looking for
    the criterion finds it."""
    subject = film({Field.NAME: "The User's Title"}, locked=frozenset({MetadataField.NAME}))
    changes = merge(subject, [Source(REMOTE, {Field.NAME: "TMDB's Title"})], RefreshMode.REPLACE)
    assert Field.NAME not in changes.values
    assert Field.NAME in changes.refused, "a refusal is not the same as nobody having offered"


def test_a_default_refresh_never_overwrites_a_non_empty_field() -> None:
    """AC-11, at engine level, over every scalar field at once."""
    scalars = {
        Field.NAME: "Mine",
        Field.OVERVIEW: "Mine",
        Field.TAGLINE: "Mine",
        Field.YEAR: 1999,
        Field.COMMUNITY_RATING: 7.4,
        Field.OFFICIAL_RATING: "PG",
        Field.ORIGINAL_TITLE: "Mine",
        Field.SORT_NAME: "Mine",
    }
    offered = dict.fromkeys(scalars, "Theirs")
    changes = merge(film(scalars), [Source(REMOTE, offered)], RefreshMode.DEFAULT)
    assert changes.values == {}


def test_a_zero_rating_counts_as_a_value_and_is_not_overwritten() -> None:
    """The reason `is_value` is a function: `if not value` would treat a rating of zero - which
    somebody gave - as an empty field and let the next refresh replace it."""
    subject = film({Field.COMMUNITY_RATING: 0.0})
    changes = merge(subject, [Source(REMOTE, {Field.COMMUNITY_RATING: 8.0})], RefreshMode.DEFAULT)
    assert Field.COMMUNITY_RATING not in changes.values


def test_a_whole_item_lock_stops_everything_in_every_mode() -> None:
    """`<lockdata>true</lockdata>`. Every field a source offered is *refused* rather than merely
    absent, so a report can tell a user their lock did something."""
    offered = {Field.NAME: "Theirs", Field.OVERVIEW: "Theirs", Field.GENRES: ["Drama"]}
    for mode in RefreshMode:
        changes = merge(film({}, whole_item=True), [Source(LOCAL, offered)], mode)
        assert changes.values == {}
        assert changes.refused == {Field.NAME, Field.OVERVIEW, Field.GENRES}


# ----------------------------------------------------------------------------------------------
# Precedence
# ----------------------------------------------------------------------------------------------


def test_the_first_source_with_a_value_wins_per_field() -> None:
    """Per field, not per provider. A film taking its title from a sidecar and its overview from
    TMDB is the normal case rather than an edge (spec section 3.1)."""
    changes = merge(
        film(),
        [
            Source(LOCAL, {Field.NAME: "From the sidecar"}),
            Source(REMOTE, {Field.NAME: "From TMDB", Field.OVERVIEW: "From TMDB"}),
        ],
        RefreshMode.DEFAULT,
    )
    assert changes.values == {Field.NAME: "From the sidecar", Field.OVERVIEW: "From TMDB"}


@pytest.mark.parametrize("blank", [None, "", "   ", [], {}])
def test_a_source_that_says_nothing_useful_cannot_blank_a_field(blank: object) -> None:
    """ "Empty string is not a value. A provider returning `""` for an overview leaves the overview
    to the next provider in the chain. Otherwise a sparse sidecar erases everything below it."
    """
    changes = merge(
        film(),
        [Source(LOCAL, {Field.OVERVIEW: blank}), Source(REMOTE, {Field.OVERVIEW: "Real"})],
        RefreshMode.DEFAULT,
    )
    assert changes.values[Field.OVERVIEW] == "Real"


def test_a_field_no_source_mentions_is_not_in_the_changes() -> None:
    changes = merge(film({Field.NAME: "Mine"}), [Source(LOCAL, {})], RefreshMode.REPLACE)
    assert changes.values == {}
    assert not changes


def test_local_only_drops_the_remote_sources_rather_than_behaving_differently() -> None:
    changes = merge(
        film(),
        [Source(LOCAL, {Field.NAME: "Local"}), Source(REMOTE, {Field.OVERVIEW: "Remote"})],
        RefreshMode.LOCAL_ONLY,
    )
    assert changes.values == {Field.NAME: "Local"}


def test_local_only_still_fills_from_a_local_source_under_replace_semantics() -> None:
    """Local only is Default over a shorter chain, so a non-empty field is kept."""
    subject = film({Field.NAME: "Mine"})
    changes = merge(subject, [Source(LOCAL, {Field.NAME: "Theirs"})], RefreshMode.LOCAL_ONLY)
    assert changes.values == {}


# ----------------------------------------------------------------------------------------------
# The chains, as data
# ----------------------------------------------------------------------------------------------


def test_music_inverts_the_first_two_sources() -> None:
    """The whole reason spec section 3.1 has two columns. A music file carries its own metadata;
    a video file almost never does."""
    assert CHAIN_OF[ItemType.AUDIO][:2] == (SourceKind.TAGS, SourceKind.NFO)
    assert CHAIN_OF[ItemType.MOVIE][:2] == (SourceKind.NFO, SourceKind.PATH)


def test_every_tree_type_that_can_be_refreshed_has_a_chain() -> None:
    """A type with no chain is a type a refresh cannot resolve, and the failure would be a
    `KeyError` in the middle of a scan. `CollectionFolder` is the exception: a library root has no
    metadata to resolve."""
    assert set(CHAIN_OF) == IN_THE_TREE - {ItemType.COLLECTION_FOLDER}


def test_a_repeated_source_in_a_chain_changes_nothing() -> None:
    """The film chain lists `PATH` twice because spec section 3.1's table does. In a
    first-value-wins walk the second occurrence can only win a field the first already lost."""
    assert CHAIN_OF[ItemType.MOVIE].count(SourceKind.PATH) == 2
    once = merge(film(), [Source(SourceKind.PATH, {Field.NAME: "A"})], RefreshMode.DEFAULT)
    twice = merge(
        film(),
        [Source(SourceKind.PATH, {Field.NAME: "A"}), Source(SourceKind.PATH, {Field.NAME: "B"})],
        RefreshMode.DEFAULT,
    )
    assert once.values == twice.values


def test_remote_is_the_only_kind_that_is_not_local() -> None:
    assert [kind for kind in SourceKind if not kind.is_local] == [SourceKind.REMOTE]


# ----------------------------------------------------------------------------------------------
# Locks are coarser than fields
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("guarded", "lock"), sorted(LOCK_OF.items()))
def test_each_guarded_field_is_stopped_by_its_own_lock(guarded: Field, lock: MetadataField) -> None:
    subject = film({guarded: "Mine"}, locked=frozenset({lock}))
    changes = merge(subject, [Source(LOCAL, {guarded: ["Theirs"]})], RefreshMode.REPLACE)
    assert guarded not in changes.values
    assert guarded in changes.refused


def test_locking_the_name_does_not_lock_the_original_title() -> None:
    """The trap. The reference overwrites the original title on the line **after** the name lock,
    so a user who locks `Name` keeps their title and loses their original title. Covering both
    with one lock would be kinder and would be a divergence.
    """
    subject = film(
        {Field.NAME: "Mine", Field.ORIGINAL_TITLE: "Mine"},
        locked=frozenset({MetadataField.NAME}),
    )
    changes = merge(
        subject,
        [Source(REMOTE, {Field.NAME: "Theirs", Field.ORIGINAL_TITLE: "Theirs"})],
        RefreshMode.REPLACE,
    )
    assert Field.NAME not in changes.values
    assert changes.values[Field.ORIGINAL_TITLE] == "Theirs"


def shaped(key: Field, which: str) -> object:
    """A value of the right shape for `key`, since a field's rule reads its own shape.

    `PROVIDER_IDS` is a map and `PEOPLE` is a list of credits; handing either a bare string makes
    the merge correctly do nothing, which would have made the test below pass for the wrong
    reason - and it did, once.
    """
    rule = LIST_RULE.get(key)
    if rule is ListRule.ACCUMULATE:
        return {"Tmdb": which}
    if rule is ListRule.ENRICH:
        return [PersonCredit(which)]
    if rule is not None:
        return [which]
    return which


@pytest.mark.parametrize("unlockable", sorted(set(Field) - set(LOCK_OF)))
def test_a_field_with_no_lock_cannot_be_protected_by_any_of_the_nine(unlockable: Field) -> None:
    """Every lock at once, and the field still changes. Thirteen of twenty-one fields are like
    this in the reference, and pretending otherwise would be a promise Atrium cannot keep."""
    subject = film({unlockable: shaped(unlockable, "Mine")}, locked=frozenset(MetadataField))
    changes = merge(
        subject, [Source(LOCAL, {unlockable: shaped(unlockable, "Theirs")})], RefreshMode.REPLACE
    )
    assert unlockable in changes.values


# ----------------------------------------------------------------------------------------------
# List fields, which do not share one rule
# ----------------------------------------------------------------------------------------------


def test_genres_are_taken_whole_from_one_source() -> None:
    """A sidecar naming two genres and TMDB naming five is a film with two genres. A union
    produces a list no single source wrote and no user can correct by fixing any one file."""
    changes = merge(
        film(),
        [
            Source(LOCAL, {Field.GENRES: ["Drama", "Romance"]}),
            Source(REMOTE, {Field.GENRES: ["Drama", "Thriller", "Action", "Crime", "Mystery"]}),
        ],
        RefreshMode.DEFAULT,
    )
    assert changes.values[Field.GENRES] == ["Drama", "Romance"]


def test_a_non_empty_genre_list_is_not_touched_by_a_default_refresh() -> None:
    subject = film({Field.GENRES: ["Drama"]})
    changes = merge(subject, [Source(REMOTE, {Field.GENRES: ["Action"]})], RefreshMode.DEFAULT)
    assert Field.GENRES not in changes.values


def test_studios_and_tags_are_unioned_with_what_the_item_already_has() -> None:
    """**Not** what plan section 10 argued for, and the reference's behaviour
    `[source: MediaBrowser.Providers/Manager/MetadataService.cs:1113-1130 @ v10.11.11]`."""
    subject = film({Field.STUDIOS: ["Fixture Pictures"], Field.TAGS: ["synthetic"]})
    changes = merge(
        subject,
        [Source(REMOTE, {Field.STUDIOS: ["Second Studio"], Field.TAGS: ["checked-in"]})],
        RefreshMode.DEFAULT,
    )
    assert changes.values[Field.STUDIOS] == ["Fixture Pictures", "Second Studio"]
    assert changes.values[Field.TAGS] == ["synthetic", "checked-in"]


def test_the_union_is_case_insensitive_and_keeps_the_spelling_already_recorded() -> None:
    """A studio already recorded as `Fixture Pictures` is not rewritten by a source that shouts."""
    subject = film({Field.STUDIOS: ["Fixture Pictures"]})
    changes = merge(
        subject, [Source(REMOTE, {Field.STUDIOS: ["FIXTURE PICTURES"]})], RefreshMode.DEFAULT
    )
    assert Field.STUDIOS not in changes.values


def test_replace_takes_a_unioned_list_whole() -> None:
    subject = film({Field.STUDIOS: ["Fixture Pictures"]})
    changes = merge(
        subject, [Source(REMOTE, {Field.STUDIOS: ["Second Studio"]})], RefreshMode.REPLACE
    )
    assert changes.values[Field.STUDIOS] == ["Second Studio"]


def test_provider_ids_accumulate_and_a_default_refresh_does_not_replace_one() -> None:
    """An id is the user's decision about what this thing is, so a default refresh that overwrote
    one would undo a correction without being asked to."""
    subject = film({Field.PROVIDER_IDS: {"Tmdb": "the user's"}})
    changes = merge(
        subject,
        [Source(REMOTE, {Field.PROVIDER_IDS: {"Tmdb": "the provider's", "Imdb": "tt1"}})],
        RefreshMode.DEFAULT,
    )
    assert changes.values[Field.PROVIDER_IDS] == {"Tmdb": "the user's", "Imdb": "tt1"}


def test_replace_does_overwrite_a_provider_id() -> None:
    subject = film({Field.PROVIDER_IDS: {"Tmdb": "old"}})
    changes = merge(
        subject, [Source(REMOTE, {Field.PROVIDER_IDS: {"Tmdb": "new"}})], RefreshMode.REPLACE
    )
    assert changes.values[Field.PROVIDER_IDS] == {"Tmdb": "new"}


def test_people_are_enriched_rather_than_replaced_or_appended() -> None:
    """A sidecar that names a cast without roles, refreshed against a provider that has them,
    gains the roles **without the cast list changing**."""
    subject = film(
        {
            Field.PEOPLE: [
                PersonCredit("First Billed"),
                PersonCredit("Second Billed", role="Already Known"),
            ]
        }
    )
    changes = merge(
        subject,
        [
            Source(
                REMOTE,
                {
                    Field.PEOPLE: [
                        PersonCredit("First Billed", role="The Lead", sort_order=0),
                        PersonCredit("Second Billed", role="Something Else"),
                        PersonCredit("Nobody The Sidecar Knew", role="A Cameo"),
                    ]
                },
            )
        ],
        RefreshMode.DEFAULT,
    )
    people = changes.values[Field.PEOPLE]
    assert isinstance(people, list)
    assert [person.name for person in people] == ["First Billed", "Second Billed"], (
        "nobody is added and nobody is removed"
    )
    assert people[0].role == "The Lead", "a missing role is filled in"
    assert people[0].sort_order == 0
    assert people[1].role == "Already Known", "a role the item has is kept"


def test_people_are_matched_ignoring_case_and_diacritics() -> None:
    """The reference's own matching. Not the by-name fold of `library/identity.py`, which keeps
    diacritics apart on purpose - two different questions."""
    subject = film({Field.PEOPLE: [PersonCredit("Amelie Dupont")]})
    changes = merge(
        subject,
        [Source(REMOTE, {Field.PEOPLE: [PersonCredit("AMÉLIE DUPONT", role="Herself")]})],
        RefreshMode.DEFAULT,
    )
    people = changes.values[Field.PEOPLE]
    assert isinstance(people, list)
    assert people[0].name == "Amelie Dupont", "the item's own spelling survives"
    assert people[0].role == "Herself"


def test_an_empty_cast_takes_the_source_whole() -> None:
    subject = film()
    offered = [PersonCredit("First Billed", kind=PersonKind.ACTOR, role="The Lead")]
    changes = merge(subject, [Source(LOCAL, {Field.PEOPLE: offered})], RefreshMode.DEFAULT)
    assert changes.values[Field.PEOPLE] == offered


def test_replace_takes_the_cast_whole() -> None:
    subject = film({Field.PEOPLE: [PersonCredit("Old")]})
    offered = [PersonCredit("New")]
    changes = merge(subject, [Source(REMOTE, {Field.PEOPLE: offered})], RefreshMode.REPLACE)
    assert changes.values[Field.PEOPLE] == offered


def test_every_list_rule_is_used_by_some_field() -> None:
    """A rule nothing uses is a rule nothing tests."""
    assert set(LIST_RULE.values()) == set(ListRule)


# ----------------------------------------------------------------------------------------------
# Runtime, which a file-backed item does not take from metadata
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(FILE_BACKED))
def test_a_file_backed_item_ignores_a_runtime_from_metadata(kind: ItemType) -> None:
    """A film's runtime comes from probing the file. Honouring an `.nfo` `<runtime>` here would
    give Atrium a duration the reference does not report - visible, because 004 has no prober and
    the reference's value comes from one."""
    subject = Current(kind=kind)
    changes = merge(subject, [Source(LOCAL, {Field.RUNTIME: 58_200_000_000})], RefreshMode.REPLACE)
    assert Field.RUNTIME not in changes.values


@pytest.mark.parametrize("kind", sorted(set(CHAIN_OF) - FILE_BACKED))
def test_a_container_does_take_its_runtime_from_metadata(kind: ItemType) -> None:
    subject = Current(kind=kind)
    changes = merge(subject, [Source(LOCAL, {Field.RUNTIME: 58_200_000_000})], RefreshMode.DEFAULT)
    assert changes.values[Field.RUNTIME] == 58_200_000_000


# ----------------------------------------------------------------------------------------------
# Purity
# ----------------------------------------------------------------------------------------------


def test_the_merge_does_not_mutate_what_it_is_given() -> None:
    """It is a pure function and the write path depends on that: `apply` is handed `changes` and
    the subject separately, and a merge that had edited the subject would make the two disagree."""
    original = {Field.STUDIOS: ["Fixture Pictures"], Field.PROVIDER_IDS: {"Tmdb": "1"}}
    subject = film(original)
    offered = {Field.STUDIOS: ["Second"], Field.PROVIDER_IDS: {"Imdb": "tt1"}}
    merge(subject, [Source(REMOTE, offered)], RefreshMode.DEFAULT)
    assert original == {Field.STUDIOS: ["Fixture Pictures"], Field.PROVIDER_IDS: {"Tmdb": "1"}}
    assert offered == {Field.STUDIOS: ["Second"], Field.PROVIDER_IDS: {"Imdb": "tt1"}}


def test_merging_twice_changes_nothing_the_second_time() -> None:
    """Idempotence, which is what makes a rescan of an unchanged library write nothing."""
    subject = film()
    sources = [Source(LOCAL, {Field.NAME: "The Fixture", Field.GENRES: ["Drama"]})]
    first = merge(subject, sources, RefreshMode.DEFAULT)
    settled = film(dict(first.values))
    assert merge(settled, sources, RefreshMode.DEFAULT).values == {}
