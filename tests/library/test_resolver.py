# SPDX-License-Identifier: GPL-3.0-or-later
"""The whole shape, from the fixture tree to a hierarchy of items.

This is the first test that runs the feature end to end without a database: walk the real fixture
library, resolve it, and look at what comes out. AC-1's structure lives here — the scan at T15 adds
persistence and the identity guarantees on top.

The one that would be worst to get wrong is `test_sort_names_come_from_the_dispatcher`.
[plan section 9](../../specs/003-library-configuration-and-scanning/plan.md) rates using one
sort-name function for everything as the most likely mistake and the most expensive one: nothing
raises, nothing logs, and every album in the library is simply in the wrong order.
"""

from __future__ import annotations

import pytest

from atrium.domain.items import PARENT_OF, CollectionType, Item, ItemType
from atrium.domain.library import Library
from atrium.library.resolver import resolve
from atrium.library.walker import walk
from tests.fixtures.library import BuiltFixture

LIBRARY_ID = "b" * 32


def a_library(collection_type: str) -> Library:
    return Library(
        id=LIBRARY_ID, name=collection_type.title(), collection_type=CollectionType(collection_type)
    )


def resolved(fixture_library: BuiltFixture, collection_type: str):  # type: ignore[no-untyped-def]
    built = fixture_library.of(collection_type)
    return resolve(
        a_library(collection_type), walk(built.root, CollectionType(collection_type)).candidates
    )


def named(items: tuple[Item, ...], item_type: ItemType) -> set[str]:
    return {item.name for item in items if item.type is item_type}


# ------------------------------------------------------------------------------------------
# AC-1: the expected structure, for all three collection types
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_a_library_is_always_an_item(fixture_library: BuiltFixture, collection_type: str) -> None:
    """Spec section 3.1. Present even for an empty library: a library that vanished from a client
    because its last file was deleted is a worse answer than an empty one.
    """
    folders = resolved(fixture_library, collection_type).of_type(ItemType.COLLECTION_FOLDER)
    assert len(folders) == 1
    assert folders[0].parent_id is None


def test_an_empty_library_still_has_its_collection_folder() -> None:
    assert len(resolve(a_library("movies"), []).items) == 1


def test_every_item_hangs_from_something_that_is_there() -> None:
    """A dangling parent is an item no query can reach through its library."""
    for collection_type in ("movies", "tvshows", "music"):
        items = resolve(a_library(collection_type), []).items
        assert all(item.parent_id is None for item in items)


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_no_item_has_a_parent_that_does_not_exist(
    fixture_library: BuiltFixture, collection_type: str
) -> None:
    items = resolved(fixture_library, collection_type).items
    known = {item.id for item in items}
    for item in items:
        assert item.parent_id is None or item.parent_id in known, item.name


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_every_parent_is_the_type_the_hierarchy_says(
    fixture_library: BuiltFixture, collection_type: str
) -> None:
    """`PARENT_OF` from T3, checked against what the resolver actually built."""
    resolution = resolved(fixture_library, collection_type)
    for item in resolution.items:
        if item.parent_id is None:
            continue
        parent = resolution.by_id(item.parent_id)
        assert parent is not None
        expected = PARENT_OF[item.type]
        if expected is not None:
            assert parent.type is expected, f"{item.type} hangs from {parent.type}"


# ------------------------------------------------------------------------------------------
# Spec section 3.1: the collection type cannot be talked round
# ------------------------------------------------------------------------------------------


def test_a_file_under_a_music_root_is_never_a_movie(fixture_library: BuiltFixture) -> None:
    """The fixture carries `The Artist/Not A Film (2001).mkv` for exactly this."""
    types = {item.type for item in resolved(fixture_library, "music").items}
    assert ItemType.MOVIE not in types
    assert ItemType.EPISODE not in types


def test_a_library_that_produced_a_foreign_type_is_refused() -> None:
    """Enforced rather than trusted to the dispatch being written correctly.

    A resolver that grew a wrong branch fails here, in this feature, rather than in 005 three
    months later as an item a client cannot make sense of.
    """
    from atrium.library import resolver

    with pytest.raises(ValueError, match="never resolved as anything else"):
        resolver._refuse_foreign_types(
            a_library("music"),
            [Item(id="a" * 32, type=ItemType.MOVIE, name="x", library_id=LIBRARY_ID)],
        )


# ------------------------------------------------------------------------------------------
# The three shapes
# ------------------------------------------------------------------------------------------


def test_the_movies_fixture_resolves_to_films_under_the_library(
    fixture_library: BuiltFixture,
) -> None:
    resolution = resolved(fixture_library, "movies")
    films = resolution.of_type(ItemType.MOVIE)
    assert "The Matrix" in named(resolution.items, ItemType.MOVIE)
    assert all(
        film.parent_id == resolution.of_type(ItemType.COLLECTION_FOLDER)[0].id for film in films
    )


def test_a_two_part_film_is_one_item_with_two_sources(fixture_library: BuiltFixture) -> None:
    """AC-4, end to end for the first time: through the walk and the resolver, not the parse."""
    films = resolved(fixture_library, "movies").of_type(ItemType.MOVIE)
    long_film = [film for film in films if film.name == "The Long Film"]
    assert len(long_film) == 1, "the two parts became two films, which doubles a user's library"
    assert len(long_film[0].sources) == 2


def test_the_series_fixture_resolves_three_levels(fixture_library: BuiltFixture) -> None:
    resolution = resolved(fixture_library, "tvshows")
    assert named(resolution.items, ItemType.SERIES) >= {"The Series", "24", "The Daily Show"}
    assert resolution.of_type(ItemType.SEASON)
    assert resolution.of_type(ItemType.EPISODE)


def test_specials_becomes_season_zero(fixture_library: BuiltFixture) -> None:
    """AC-6, end to end."""
    seasons = resolved(fixture_library, "tvshows").of_type(ItemType.SEASON)
    assert 0 in {season.index_number for season in seasons}
    assert "Specials" in {season.name for season in seasons}


def test_a_multi_episode_file_is_one_episode(fixture_library: BuiltFixture) -> None:
    """AC-5, end to end."""
    spanning = [
        episode
        for episode in resolved(fixture_library, "tvshows").of_type(ItemType.EPISODE)
        if episode.end_index_number is not None
    ]
    assert len(spanning) == 1
    assert spanning[0].spans == (2, 3)


def test_a_series_named_with_digits_keeps_its_title(fixture_library: BuiltFixture) -> None:
    """AC-7, end to end."""
    assert "24" in named(resolved(fixture_library, "tvshows").items, ItemType.SERIES)


def test_the_music_fixture_resolves_three_levels(fixture_library: BuiltFixture) -> None:
    resolution = resolved(fixture_library, "music")
    assert named(resolution.items, ItemType.MUSIC_ARTIST) >= {"The Artist", "Various Artists"}
    assert resolution.of_type(ItemType.MUSIC_ALBUM)
    assert resolution.of_type(ItemType.AUDIO)


def test_a_two_disc_album_is_one_album(fixture_library: BuiltFixture) -> None:
    """AC-8, end to end: two disc directories, one album, two disc numbers."""
    resolution = resolved(fixture_library, "music")
    double = [
        album for album in resolution.of_type(ItemType.MUSIC_ALBUM) if album.name == "Double Album"
    ]
    assert len(double) == 1
    discs = {
        track.parent_index_number
        for track in resolution.of_type(ItemType.AUDIO)
        if track.parent_id == double[0].id
    }
    assert discs == {1, 2}


def test_a_compilation_is_one_album(fixture_library: BuiltFixture) -> None:
    """AC-9, end to end, from the path alone - the fixture's compilation has one album directory."""
    resolution = resolved(fixture_library, "music")
    compilation = [
        album for album in resolution.of_type(ItemType.MUSIC_ALBUM) if album.name == "A Compilation"
    ]
    assert len(compilation) == 1
    tracks = [t for t in resolution.of_type(ItemType.AUDIO) if t.parent_id == compilation[0].id]
    assert len(tracks) == 3


# ------------------------------------------------------------------------------------------
# AC-13: the sort names, and where they come from
# ------------------------------------------------------------------------------------------


def test_sort_names_come_from_the_dispatcher(fixture_library: BuiltFixture) -> None:
    """Plan section 9's most likely and most expensive mistake, asserted on real resolved items.

    `Audio`, `Episode` and `Season` replace the base derivation entirely. Using one sort-name
    function for everything raises nothing and logs nothing - it simply puts every album in the
    library in the wrong order.
    """
    resolution = resolved(fixture_library, "music")
    for track in resolution.of_type(ItemType.AUDIO):
        if track.index_number is None:
            continue
        assert track.sort_name.endswith(track.name), (
            f"{track.name!r} sorted as {track.sort_name!r}: the base rule was applied to Audio, "
            f"which strips its article and reorders every album in the library"
        )
        assert track.sort_name.startswith("000")


def test_an_episode_sorts_by_its_asymmetric_widths(fixture_library: BuiltFixture) -> None:
    """Season padded to three, episode to four. It reads like a typo and it is measured."""
    episodes = resolved(fixture_library, "tvshows").of_type(ItemType.EPISODE)
    pilot = next(e for e in episodes if e.name == "Pilot")
    assert pilot.sort_name == "001 - 0001 - Pilot"


def test_a_season_sorts_as_its_number_alone(fixture_library: BuiltFixture) -> None:
    seasons = resolved(fixture_library, "tvshows").of_type(ItemType.SEASON)
    assert {s.sort_name for s in seasons if s.index_number == 0} == {"0000"}


def test_a_film_sorts_by_the_base_derivation(fixture_library: BuiltFixture) -> None:
    """The other half: films do use section 3.7.1, artefacts and all."""
    films = {
        film.name: film.sort_name
        for film in resolved(fixture_library, "movies").of_type(ItemType.MOVIE)
    }
    assert films["The Matrix"] == "matrix"
    assert films["Rock & Roll"] == "rock  roll"
    assert films["2 Fast 2 Furious"] == "0000000002 fast 0000000002 furious"


def test_every_item_has_a_sort_name(fixture_library: BuiltFixture) -> None:
    """An item with none sorts first, everywhere, and nothing says why."""
    for collection_type in ("movies", "tvshows", "music"):
        for item in resolved(fixture_library, collection_type).items:
            assert item.sort_name, f"{item.type} {item.name!r} has no sort name"


# ------------------------------------------------------------------------------------------
# Determinism
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_resolving_twice_gives_the_same_items(
    fixture_library: BuiltFixture, collection_type: str
) -> None:
    """Spec section 3.8: the same tree resolves to the same items in the same order."""
    assert resolved(fixture_library, collection_type) == resolved(fixture_library, collection_type)


def test_the_order_does_not_depend_on_the_order_candidates_arrived_in(
    fixture_library: BuiltFixture,
) -> None:
    built = fixture_library.of("movies")
    candidates = list(walk(built.root, CollectionType.MOVIES).candidates)
    forwards = resolve(a_library("movies"), candidates)
    backwards = resolve(a_library("movies"), list(reversed(candidates)))
    assert forwards == backwards


@pytest.mark.parametrize("collection_type", ["movies", "tvshows", "music"])
def test_no_two_items_share_an_identifier(
    fixture_library: BuiltFixture, collection_type: str
) -> None:
    items = resolved(fixture_library, collection_type).items
    assert len({item.id for item in items}) == len(items)
