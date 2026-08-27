# SPDX-License-Identifier: GPL-3.0-or-later
"""The item model: the shapes the acceptance criteria need, asserted before anything produces them.

Two of these are the model half of an acceptance criterion, and they are here rather than in a scan
test because a scan cannot produce a shape the model cannot hold. AC-4 needs one item with two
sources; AC-5 needs one item spanning two episode numbers. Both were shapes the plan's data model
had no room for - see the T3 note in tasks.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atrium.domain.items import (
    BY_NAME,
    FILE_BACKED,
    IN_THE_TREE,
    PARENT_OF,
    PRODUCED_BY,
    CollectionType,
    Item,
    ItemType,
    MediaSource,
)


def movie(*sources: MediaSource) -> Item:
    return Item(
        id="a" * 32, type=ItemType.MOVIE, name="The Long Film", library_id="b" * 32, sources=sources
    )


# ------------------------------------------------------------------------------------------
# AC-4: one film, two parts
# ------------------------------------------------------------------------------------------


def test_a_two_part_film_is_one_item_with_two_sources() -> None:
    item = movie(
        MediaSource("The Long Film (1998) - part1.mkv", size=100),
        MediaSource("The Long Film (1998) - part2.mkv", size=250),
    )
    assert len(item.sources) == 2
    assert item.size == 350, "a two-part film's size is both parts"


def test_a_films_identity_comes_from_its_first_part() -> None:
    """So that adding a part three years later does not change an id somebody has favourited."""
    first = MediaSource("The Long Film (1998) - part1.mkv")
    assert movie(first).relative_path == first.relative_path
    assert movie(first, MediaSource("part2.mkv")).relative_path == first.relative_path


def test_a_container_has_no_source_at_all() -> None:
    """Which is why the path is not a field on the item: a Series has nothing to put in it."""
    series = Item(id="c" * 32, type=ItemType.SERIES, name="The Series", library_id="b" * 32)
    assert series.sources == ()
    assert series.relative_path is None
    assert series.size is None
    assert not series.is_file_backed


def test_a_source_carries_its_own_change_detection_signal() -> None:
    """Per source, not per item: a film whose second part was replaced has changed."""
    source = MediaSource("part2.mkv", size=250, mtime_ns=1)
    assert (source.size, source.mtime_ns) == (250, 1)


# ------------------------------------------------------------------------------------------
# AC-5: one episode spanning two numbers
# ------------------------------------------------------------------------------------------


def episode(index: int | None, end: int | None = None) -> Item:
    return Item(
        id="d" * 32,
        type=ItemType.EPISODE,
        name="Two Parter",
        library_id="b" * 32,
        index_number=index,
        end_index_number=end,
        parent_index_number=1,
    )


def test_a_multi_episode_file_spans_both_numbers() -> None:
    assert episode(2, 3).spans == (2, 3)


def test_an_ordinary_episode_spans_one() -> None:
    assert episode(2).spans == (2,)


def test_an_episode_with_no_number_spans_nothing() -> None:
    """Section 3.4: an episode whose number cannot be read is not an error."""
    assert episode(None).spans == ()


def test_a_long_run_spans_every_number_in_it() -> None:
    assert episode(2, 5).spans == (2, 3, 4, 5)


# ------------------------------------------------------------------------------------------
# Soft deletion
# ------------------------------------------------------------------------------------------


def test_an_item_is_removed_only_once_it_has_a_removal_time() -> None:
    item = movie(MediaSource("film.mkv"))
    assert not item.is_removed
    assert Item(**{**vars_of(item), "removed_at": datetime(2026, 8, 27, tzinfo=UTC)}).is_removed


def vars_of(item: Item) -> dict[str, object]:
    """`slots=True` means no `__dict__`, so the fields are read by name."""
    return {name: getattr(item, name) for name in item.__slots__}


# ------------------------------------------------------------------------------------------
# The type hierarchy
# ------------------------------------------------------------------------------------------


def test_every_type_in_the_tree_says_what_its_parent_is() -> None:
    """Over `IN_THE_TREE`, and that scoping is the point rather than a concession.

    004 added five types that are **not** in the containment tree - a genre is referenced by items
    in a library, not contained by one - and the tempting fix when this test first failed was to
    widen it to `set(ItemType)` by mapping each of them to `None`. That would have passed and
    would have made the next test meaningless: five types whose chain ends at themselves, in an
    assertion written to prove every chain ends at the library.

    So the exemption is named here, once, and the three maps below are total over the tree. A
    ninth *tree* type with no parent still fails, which is what this test is for.
    """
    assert set(PARENT_OF) == IN_THE_TREE
    assert BY_NAME.isdisjoint(PARENT_OF), "a by-name type with a parent is in the tree by accident"


def test_every_chain_ends_at_the_library_itself() -> None:
    """A film's parent is its CollectionFolder, not nothing - the library is an item too."""
    for start in IN_THE_TREE:
        seen, current = [start], PARENT_OF[start]
        while current is not None:
            assert current not in seen, f"{start} has a cycle in its parent chain: {seen}"
            seen.append(current)
            current = PARENT_OF[current]
        assert seen[-1] is ItemType.COLLECTION_FOLDER


def test_a_by_name_type_has_no_chain_at_all() -> None:
    """The positive statement of the exemption above: not "excused from the tree" but "not in it".

    A genre with a parent would appear under one library and belong to all of them, which is
    precisely the bug the server-wide identity rule exists to avoid (004 spec section 3.7).
    """
    for kind in BY_NAME:
        assert kind not in PARENT_OF
        assert kind not in set().union(*PRODUCED_BY.values())


def test_the_leaves_of_the_hierarchy_are_exactly_the_file_backed_types() -> None:
    """The two facts drifting apart is how a scanner invents a container that owns a container."""
    parents = {parent for parent in PARENT_OF.values() if parent is not None}
    assert IN_THE_TREE - parents - {ItemType.COLLECTION_FOLDER} == FILE_BACKED


@pytest.mark.parametrize("collection_type", list(CollectionType))
def test_a_collection_type_produces_only_its_own_types(collection_type: CollectionType) -> None:
    """Spec section 3.1: a file under a music root is never resolved as a movie."""
    produced = PRODUCED_BY[collection_type]
    others = set(ItemType) - produced
    assert ItemType.COLLECTION_FOLDER in produced, "every library is an item"
    if collection_type is not CollectionType.MOVIES:
        assert ItemType.MOVIE in others


def test_every_type_in_the_tree_is_produced_by_some_collection_type() -> None:
    """A tree type nothing produces is a type the resolver can never create.

    The by-name five are produced by a **refresh** rather than by a resolver - they come from a
    name an item mentions, not from a file a walker found - so they are outside this the same way
    they are outside `PARENT_OF`.
    """
    assert set().union(*PRODUCED_BY.values()) == IN_THE_TREE


def test_no_type_is_produced_by_two_collection_types_except_the_library() -> None:
    """Anything else shared would make a resolver's dispatch ambiguous."""
    for one in CollectionType:
        for other in CollectionType:
            if one is other:
                continue
            shared = PRODUCED_BY[one] & PRODUCED_BY[other]
            assert shared == {ItemType.COLLECTION_FOLDER}, f"{one} and {other} share {shared}"


def test_the_type_values_are_the_references_spellings() -> None:
    """They are the vocabulary; 005 serialises these strings and clients branch on them."""
    assert ItemType.MUSIC_ARTIST == "MusicArtist"
    assert ItemType.COLLECTION_FOLDER == "CollectionFolder"
    assert ItemType.MUSIC_GENRE == "MusicGenre"
    assert CollectionType.TVSHOWS == "tvshows"


def test_the_tree_and_the_by_name_types_partition_every_type() -> None:
    """No third category, and nothing in both. A type that is in neither has no rule anywhere:
    no parent, no collection type, no identity, and no constraint - and the first symptom would be
    a `KeyError` in the middle of a scan."""
    assert set(ItemType) == IN_THE_TREE | BY_NAME
    assert IN_THE_TREE.isdisjoint(BY_NAME)


def test_a_by_name_item_knows_it_is_one() -> None:
    genre = Item(id="e" * 32, type=ItemType.GENRE, name="Drama", library_id=None)
    film = Item(id="f" * 32, type=ItemType.MOVIE, name="The Fixture", library_id="b" * 32)
    assert genre.is_by_name and not genre.is_file_backed
    assert not film.is_by_name
