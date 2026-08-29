# SPDX-License-Identifier: GPL-3.0-or-later
"""Every filter, and the one property a functional test cannot see: that it filters.

Plan §8 row 16 is the shape of this file. A predicate that silently does nothing returns a
superset of the right answer, so every assertion about the rows it *did* return passes — the test
that catches it is the one that asserts the result got **smaller**. Each row of the table below is
therefore checked twice: it selects something, and it selects less than everything.

The world slices are built to be narrowed. `years` and `minCommunityRating` need films that carry
a year and a rating, and `artistIds` against `albumArtistIds` needs a compilation with one track
by its own compiler — both added to `tests/fixtures/query.py` at T6, because T3's world could not
exercise them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.item_queries import ItemQueryRepository, QueryPage
from atrium.domain.items import ItemType
from atrium.domain.queries import Filter, ItemQuery
from atrium.library import identity
from tests.conftest import QueryCounter, data_dir
from tests.fixtures.query import (
    FIRST_YEAR,
    GENRE_SPELLINGS,
    QueryWorld,
    build_query_world,
)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    prepared: DataPaths = data_dir(tmp_path / "atrium")
    built = create_database_engine(prepared)
    schema.ensure_current(built, prepared)
    yield built
    built.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[OrmSession]:
    opened = session_factory(engine)()
    yield opened
    opened.rollback()
    opened.close()


@pytest.fixture
def world(session: OrmSession) -> QueryWorld:
    built = build_query_world(session)
    session.commit()
    return built


@pytest.fixture
def repository(session: OrmSession) -> ItemQueryRepository:
    return ItemQueryRepository(session)


Slice = Callable[[QueryWorld], dict[str, Any]]

#: One row per predicate `ItemQuery` names. The callable turns the seeded world into the keyword
#: arguments that exercise it, because almost every one needs an identifier the world derived.
PREDICATES: list[tuple[str, Slice]] = [
    ("include_types", lambda w: {"include_types": frozenset({ItemType.MOVIE})}),
    ("exclude_types", lambda w: {"exclude_types": frozenset({ItemType.MOVIE})}),
    ("media_types", lambda w: {"media_types": frozenset({"Audio"})}),
    ("ids", lambda w: {"ids": w.corpus[:3]}),
    ("exclude_ids", lambda w: {"exclude_ids": w.corpus[:3]}),
    ("search_term", lambda w: {"search_term": "paging"}),
    ("name_starts_with", lambda w: {"name_starts_with": "paging"}),
    ("name_starts_with_or_greater", lambda w: {"name_starts_with_or_greater": "s"}),
    ("name_less_than", lambda w: {"name_less_than": "b"}),
    ("genres", lambda w: {"genres": (GENRE_SPELLINGS[0],)}),
    ("genre_ids", lambda w: {"genre_ids": (identity.for_by_name(ItemType.GENRE, "sci-fi"),)}),
    (
        "studio_ids",
        lambda w: {"studio_ids": (identity.for_by_name(ItemType.STUDIO, "A Studio"),)},
    ),
    (
        "person_ids",
        lambda w: {"person_ids": (identity.for_by_name(ItemType.PERSON, "A Director"),)},
    ),
    ("artist_ids", lambda w: {"artist_ids": (w.album_artist,)}),
    ("album_artist_ids", lambda w: {"album_artist_ids": (w.album_artist,)}),
    ("album_ids", lambda w: {"album_ids": (w.album,)}),
    ("years", lambda w: {"years": (FIRST_YEAR,)}),
    ("min_community_rating", lambda w: {"min_community_rating": 8.0}),
    ("is_favorite", lambda w: {"is_favorite": True}),
    ("is_played", lambda w: {"is_played": True}),
    ("filters IsFavorite", lambda w: {"filters": frozenset({Filter.IS_FAVORITE})}),
    ("filters IsPlayed", lambda w: {"filters": frozenset({Filter.IS_PLAYED})}),
    ("filters IsUnplayed", lambda w: {"filters": frozenset({Filter.IS_UNPLAYED})}),
    ("filters IsResumable", lambda w: {"filters": frozenset({Filter.IS_RESUMABLE})}),
]


def everything(repository: ItemQueryRepository, world: QueryWorld) -> QueryPage:
    return repository.run(ItemQuery(user=world.everyone, limit=1000))


@pytest.mark.parametrize(("label", "build"), PREDICATES, ids=[one[0] for one in PREDICATES])
def test_a_predicate_selects_something_and_less_than_everything(
    repository: ItemQueryRepository, world: QueryWorld, label: str, build: Slice
) -> None:
    unfiltered = everything(repository, world)
    narrowed = repository.run(ItemQuery(user=world.everyone, limit=1000, **build(world)))

    assert narrowed.total > 0, f"{label} selected nothing; the slice does not exercise it"
    assert narrowed.total < unfiltered.total, (
        f"{label} selected everything ({narrowed.total} of {unfiltered.total}). A predicate that "
        f"changes nothing returns a superset of the right answer, so every assertion about the "
        f"rows it did return would pass."
    )
    assert len(narrowed.items) == narrowed.total, "the count and the page disagree"


@pytest.mark.parametrize(("label", "build"), PREDICATES, ids=[one[0] for one in PREDICATES])
def test_a_predicate_costs_no_extra_statements(
    engine: Engine,
    repository: ItemQueryRepository,
    world: QueryWorld,
    query_counter: QueryCounter,
    label: str,
    build: Slice,
) -> None:
    """Every filter is a clause on the one statement, never a second query or a walk in Python.

    The ceiling is the hydration budget - seventeen: one count, one page, seven related tables,
    the two 008 T3 added for the page's inspections, four ancestor fetches and two rollups
    (`test_item_queries` holds the exact number). What this test guards is that a *predicate* adds
    no statement on top of it.
    """
    with query_counter.watching(engine):
        repository.run(ItemQuery(user=world.everyone, limit=10, **build(world)))
    assert len(query_counter) <= 17, query_counter.report()


# ------------------------------------------------------------------------------------------
# The ones whose exact answer matters
# ------------------------------------------------------------------------------------------


def test_artist_ids_is_the_superset_and_album_artist_ids_the_subset(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`/Artists` and `/Artists/AlbumArtists` are the same rows distinguished by the credit column
    and nothing else, and this is the first thing to lean on it.

    **Measured, because guessing the direction was possible and wrong.** On the reference,
    `artistIds` answers a superset: "Alan Cook" returns 6 items to `albumArtistIds`' 2, and a
    performer who is nobody's album artist returns 2 to 0.
    `[probe: tools/probe_by_name_counts.py, Jellyfin 10.11.11, 2026-08-28]` So `artistIds`
    matches **any**
    credit — the album's own album-artist row included — and `albumArtistIds` matches that one
    kind.

    The difference is the guest track: performed by this artist, credited to another as album
    artist. Without such an item the two parameters return identical rows and the credit column
    goes untested while looking tested.
    """
    performed = repository.run(
        ItemQuery(user=world.everyone, artist_ids=(world.album_artist,), limit=1000)
    )
    credited = repository.run(
        ItemQuery(user=world.everyone, album_artist_ids=(world.album_artist,), limit=1000)
    )
    performed_ids = {one.id for one in performed.items}
    credited_ids = {one.id for one in credited.items}

    assert credited_ids < performed_ids, "the credit column is not being read"
    assert performed_ids - credited_ids == {world.guest_track}
    assert world.album in credited_ids


def test_the_guest_albums_artist_does_not_own_the_compilation(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The other direction of the same distinction, so neither filter can be passing by returning
    everything."""
    credited = repository.run(
        ItemQuery(user=world.everyone, album_artist_ids=(world.guest_artist,), limit=1000)
    )
    ids = {one.id for one in credited.items}
    assert world.guest_track in ids
    assert world.album not in ids
    assert not (set(world.tracks) & ids)


def test_a_genre_name_finds_both_spellings(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Two spellings of one genre merge to one by-name row (behaviours §2.18), and a client
    filtering by name never fetched that row. Either spelling has to find both films."""
    lower = repository.run(ItemQuery(user=world.everyone, genres=(GENRE_SPELLINGS[0],), limit=1000))
    upper = repository.run(ItemQuery(user=world.everyone, genres=(GENRE_SPELLINGS[1],), limit=1000))
    assert {one.id for one in lower.items} == {one.id for one in upper.items}
    assert set(world.corpus[:2]) <= {one.id for one in lower.items}


def test_a_genre_name_reaches_the_music_genre_too(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`Genre` and `MusicGenre` spelled the same are two rows, and a client filtering by `sci-fi`
    does not know which table its films and its tracks landed in."""
    found = repository.run(ItemQuery(user=world.everyone, genres=(GENRE_SPELLINGS[0],), limit=1000))
    assert world.album in {one.id for one in found.items}


def test_unplayed_includes_items_nobody_has_touched(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Absence of a user-data row *is* a state. `EXISTS(NOT played)` would find only the items
    somebody has already touched, which on a fresh account is none of them - and the filter would
    quietly return almost nothing while looking like it worked."""
    unplayed = repository.run(
        ItemQuery(user=world.everyone, filters=frozenset({Filter.IS_UNPLAYED}), limit=1000)
    )
    ids = {one.id for one in unplayed.items}
    assert world.corpus[50] in ids, "an item with no user-data row at all is unplayed"
    assert all(handle.watched not in ids for handle in world.series)


def test_played_and_unplayed_partition_the_world(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    played = repository.run(
        ItemQuery(user=world.everyone, filters=frozenset({Filter.IS_PLAYED}), limit=1000)
    )
    unplayed = repository.run(
        ItemQuery(user=world.everyone, filters=frozenset({Filter.IS_UNPLAYED}), limit=1000)
    )
    assert played.total + unplayed.total == everything(repository, world).total


def test_resumable_is_a_mid_playback_position(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`playback_position_ticks > 0`. 007 §3.7's six-branch rule already guarantees a stored
    position is a mid-playback one - a report past the completion threshold clears it and marks
    the item played - so there is no "resumable at 99%" for this clause to exclude."""
    resumable = repository.run(
        ItemQuery(user=world.everyone, filters=frozenset({Filter.IS_RESUMABLE}), limit=1000)
    )
    assert {one.id for one in resumable.items} == set(world.resumable)


def test_search_folds_case_and_diacritics_on_both_sides(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """A user typing `amelie` finds `Amélie`. Folding only the column would make the filter depend
    on how the client typed it; folding only the term, on how the file was named."""
    for typed in ("amelie", "AMÉLIE", "Amelie"):
        found = repository.run(ItemQuery(user=world.everyone, search_term=typed, limit=1000))
        assert [one.item.name for one in found.items] == ["Amélie"], typed


def test_an_empty_collection_selects_nothing(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`None` means the client did not ask; an empty collection means it asked for nothing.

    `includeItemTypes=` with every token unrecognised drops to an empty tuple (behaviours §1.12),
    and the honest answer to "items of no type" is no items. Treating the two the same is how a
    filter that dropped all its tokens returns the whole library.
    """
    empty = repository.run(ItemQuery(user=world.everyone, include_types=frozenset(), limit=1000))
    assert empty.total == 0
    assert repository.run(ItemQuery(user=world.everyone, ids=(), limit=1000)).total == 0


def test_two_predicates_are_an_intersection(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    both = repository.run(
        ItemQuery(
            user=world.everyone,
            include_types=frozenset({ItemType.MOVIE}),
            years=(FIRST_YEAR,),
            limit=1000,
        )
    )
    assert both.total == 1
    assert both.items[0].id == world.rated[0]


def test_a_filter_never_widens_past_visibility(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The predicate is `visible AND filtered`, in that order and never the other. A filter that
    replaced the visibility clause rather than narrowing it is the one bug in this file that is
    not cosmetic."""
    everything_visible = repository.run(ItemQuery(user=world.restricted, limit=1000))
    filtered = repository.run(
        ItemQuery(user=world.restricted, include_types=frozenset({ItemType.AUDIO}), limit=1000)
    )
    assert filtered.total == 0, "an audio track reached a user restricted to the films library"
    assert everything_visible.total > 0


def test_album_ids_selects_the_albums_tracks(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    found = repository.run(ItemQuery(user=world.everyone, album_ids=(world.album,), limit=1000))
    assert {one.id for one in found.items} == set(world.tracks)


def test_media_types_reads_the_measured_table(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """There is no `media_type` column: it is a property of the type, measured once. `MusicAlbum`
    is `Unknown` on the reference, which a rule built on "does it hold audio" would get wrong."""
    audio = repository.run(
        ItemQuery(user=world.everyone, media_types=frozenset({"Audio"}), limit=1000)
    )
    assert {one.item.type for one in audio.items} == {ItemType.AUDIO}

    unknown = repository.run(
        ItemQuery(user=world.everyone, media_types=frozenset({"Unknown"}), limit=1000)
    )
    assert ItemType.MUSIC_ALBUM in {one.item.type for one in unknown.items}
    assert ItemType.MOVIE not in {one.item.type for one in unknown.items}


def test_media_types_matches_case_insensitively(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """A parameter whose *name* matches case-insensitively while its *values* did not would be a
    distinction no client could have learned (behaviours §1.15 and §1.12 together)."""
    lower = repository.run(
        ItemQuery(user=world.everyone, media_types=frozenset({"audio"}), limit=1000)
    )
    exact = repository.run(
        ItemQuery(user=world.everyone, media_types=frozenset({"Audio"}), limit=1000)
    )
    assert lower.total == exact.total > 0
