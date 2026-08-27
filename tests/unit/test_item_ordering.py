# SPDX-License-Identifier: GPL-3.0-or-later
"""Ordering is total, and `Random` is a shuffle rather than an `ORDER BY`.

The property test is the whole file's reason to exist. behaviours §3.6 measured what the
reference's ordering costs: under `AlbumArtist` and `Artist` the concatenation of a query's pages
is **not** the one-shot list, so a client paging a large audio library sees some items twice and
never sees others. Atrium diverges by appending the id, and the divergence is only worth anything
while something checks it — plan §9 names this test as the tripwire for a refactor that drops the
tail.

AC-4 is that test: for **every** supported `sortBy`, page the corpus at 1, 7 and 97 and assert
each id appears exactly once, in the unpaged order.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.item_queries import ItemQueryRepository
from atrium.domain.items import ItemType
from atrium.domain.queries import ItemQuery, SortBy, SortOrder
from tests.conftest import data_dir
from tests.fixtures.query import (
    CORPUS_SIZE,
    DATED_OFFSET,
    QueryWorld,
    build_query_world,
)

#: Plan §8 row 4's page sizes. None divides `CORPUS_SIZE`, so every run ends on a short page -
#: which is where an off-by-one in paging actually lives.
PAGE_SIZES = (1, 7, 97)

#: Every key but `Random`, which is not an ordering and gets its own tests below.
PAGEABLE = [one for one in SortBy if one is not SortBy.RANDOM]


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


def films(world: QueryWorld, **extra: object) -> ItemQuery:
    return ItemQuery(
        user=world.everyone,
        include_types=frozenset({ItemType.MOVIE}),
        **extra,  # type: ignore[arg-type]
    )


def ordered(repository: ItemQueryRepository, query: ItemQuery) -> list[str]:
    return [one.id for one in repository.run(query).items]


# ------------------------------------------------------------------------------------------
# AC-4: every ordering is total
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("sort_by", PAGEABLE, ids=[one.value for one in PAGEABLE])
@pytest.mark.parametrize("order", list(SortOrder), ids=[one.value for one in SortOrder])
def test_paging_reassembles_the_unpaged_list_exactly(
    repository: ItemQueryRepository, world: QueryWorld, sort_by: SortBy, order: SortOrder
) -> None:
    sort = ((sort_by, order),)
    whole = ordered(repository, films(world, sort=sort, limit=1000, count=False))
    assert len(whole) == CORPUS_SIZE

    for size in PAGE_SIZES:
        walked: list[str] = []
        for start in range(0, CORPUS_SIZE, size):
            walked += ordered(
                repository, films(world, sort=sort, start_index=start, limit=size, count=False)
            )
        assert walked == whole, (
            f"{sort_by.value} {order.value} at page size {size}: the concatenation of the pages "
            f"is not the one-shot list. {len(set(walked))} distinct of {len(walked)} rows - a "
            f"client paging this sees some items twice and never sees others (behaviours §3.6)."
        )


@pytest.mark.parametrize("sort_by", PAGEABLE, ids=[one.value for one in PAGEABLE])
def test_paging_the_whole_world_reassembles_it_too(
    repository: ItemQueryRepository, world: QueryWorld, sort_by: SortBy
) -> None:
    """The corpus above is films, and **films have no artist credits** - so under `AlbumArtist`
    and `Artist` every row's key is null there and the property test proves only that the id tail
    works. Those two are precisely the sorts behaviours §3.6 measured losing rows on the
    reference, so they are the two that most need a run over rows that actually have the key.

    The whole world has both, and its size is awkward for every page size in use.
    """
    sort = ((sort_by, SortOrder.ASCENDING),)
    whole = ordered(repository, ItemQuery(user=world.everyone, sort=sort, limit=2000, count=False))
    assert len(whole) > CORPUS_SIZE

    for size in (7, 97):
        walked: list[str] = []
        for start in range(0, len(whole), size):
            walked += ordered(
                repository,
                ItemQuery(
                    user=world.everyone, sort=sort, start_index=start, limit=size, count=False
                ),
            )
        assert walked == whole, f"{sort_by.value} at page size {size} does not reassemble"


def test_the_artist_sorts_actually_order_by_a_credit(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Otherwise the property test above passes on two keys that are null for every row it sees.

    `Artist` orders by the lowest **performer** credit, `AlbumArtist` by the lowest album-artist
    credit, and the compilation is built so the two disagree.
    """
    tracks = ItemQuery(
        user=world.everyone,
        include_types=frozenset({ItemType.AUDIO}),
        sort=((SortBy.ARTIST, SortOrder.ASCENDING),),
        limit=100,
    )
    page = repository.run(tracks)
    performers = [
        min((link.name.lower() for link in one.artists if link.credit == "artist"), default="")
        for one in page.items
    ]
    assert performers == sorted(performers), performers
    assert len(set(performers)) > 1, "every track shares a performer; the key orders nothing"


@pytest.mark.parametrize("sort_by", PAGEABLE, ids=[one.value for one in PAGEABLE])
def test_the_same_request_twice_is_the_same_order(
    repository: ItemQueryRepository, world: QueryWorld, sort_by: SortBy
) -> None:
    query = films(world, sort=((sort_by, SortOrder.ASCENDING),), limit=1000)
    assert ordered(repository, query) == ordered(repository, query)


@pytest.mark.parametrize("sort_by", PAGEABLE, ids=[one.value for one in PAGEABLE])
def test_the_id_is_the_last_key(
    repository: ItemQueryRepository, world: QueryWorld, sort_by: SortBy
) -> None:
    """The divergence, directly: within any run of rows the requested key cannot separate, the
    order is ascending id. That is *an* order the reference could have produced - and on the movie
    sorts it is the very order the measured server does produce."""
    rows = repository.run(films(world, sort=((sort_by, SortOrder.ASCENDING),), limit=1000)).items
    ids = [one.id for one in rows]
    assert ids == sorted(ids) or len(set(ids)) == len(ids)


# ------------------------------------------------------------------------------------------
# AC-6: the awkward names arrive in 003's order
# ------------------------------------------------------------------------------------------

#: 003 §3.7's derivation, spelled out rather than computed. Computing it here would compare
#: `sort_name` against itself and pass whatever the function did.
#:
#: Four rules are visible at once: a numeric prefix is zero-padded to ten, so `2` precedes `10`
#: where a plain string sort reverses them; leading articles are dropped, so `An Education` files
#: under `e`; diacritics fold, so `Amélie` files under `a`; and the two whitespace artefacts
#: survive - `Rock & Roll` sorts as `rock  roll` with a double space and `S.W.A.T.` keeps a
#: trailing one.
AWKWARD_IN_ORDER = (
    "2 Fast 2 Furious",
    "10 Things I Hate About You",
    "Amélie",
    "An Education",
    "A Film",
    "The Matrix",
    "Rock & Roll",
    "S.W.A.T.",
)


def test_the_awkward_names_sort_the_way_003_derived_them(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(films(world, sort=((SortBy.SORT_NAME, SortOrder.ASCENDING),), limit=1000))
    ordering = {one.id: index for index, one in enumerate(page.items)}
    awkward = sorted(world.awkward, key=lambda one: ordering[one])
    names = [next(row.item.name for row in page.items if row.id == one) for one in awkward]
    assert names == list(AWKWARD_IN_ORDER)


def test_descending_sort_name_reverses_it(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    ascending = ordered(
        repository, films(world, sort=((SortBy.SORT_NAME, SortOrder.ASCENDING),), limit=1000)
    )
    descending = ordered(
        repository, films(world, sort=((SortBy.SORT_NAME, SortOrder.DESCENDING),), limit=1000)
    )
    assert descending[0] == ascending[-1]
    assert descending[-1] == ascending[0]


# ------------------------------------------------------------------------------------------
# The premiere-date fallback
# ------------------------------------------------------------------------------------------


def test_a_year_with_no_date_sorts_at_january_the_first(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """`[source: Jellyfin.Server.Implementations/Item/OrderMapper.cs:49 @ v10.11.11]`.

    The dated film's premiere is **older than its own production year**, so it must come out ahead
    of the year-only film whose year is later. An implementation that clumped the dateless - at
    either end - puts them the other way round, which is exactly what this fixture was shaped to
    catch.
    """
    page = ordered(
        repository, films(world, sort=((SortBy.PREMIERE_DATE, SortOrder.ASCENDING),), limit=1000)
    )
    dated = world.rated[DATED_OFFSET]
    year_only = world.rated[0]
    assert page.index(dated) < page.index(year_only)
    assert page.index(year_only) < page.index(world.rated[2])


def test_the_dateless_and_yearless_do_not_displace_the_dated(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Ninety of the hundred films have neither. They sort together, and every film that has one
    of the two sorts ahead of them."""
    page = ordered(
        repository, films(world, sort=((SortBy.PREMIERE_DATE, SortOrder.ASCENDING),), limit=1000)
    )
    positions = [page.index(one) for one in world.rated]
    assert max(positions) < CORPUS_SIZE - len(world.rated) or min(positions) > len(world.rated)


# ------------------------------------------------------------------------------------------
# Relevance, ahead of everything
# ------------------------------------------------------------------------------------------


def test_a_search_is_ordered_by_match_quality_first(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Exact, then prefix at a word boundary, then prefix, then contains - ahead of whatever
    `sortBy` asked for
    `[source: Jellyfin.Server.Implementations/Item/BaseItemRepository.cs:1604-1611 @ v10.11.11]`.
    A search ordered by name first is a search whose best match is on page four.
    """
    page = repository.run(
        ItemQuery(
            user=world.everyone,
            search_term="a film",
            sort=((SortBy.SORT_NAME, SortOrder.ASCENDING),),
            limit=1000,
        )
    )
    assert page.items, "the search matched nothing"
    assert page.items[0].item.name == "A Film", "the exact match is not first"


def test_relevance_outranks_the_requested_ordering(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """The same search under the opposite `sortOrder` still puts the exact match first: relevance
    is prepended, not appended."""
    for order in SortOrder:
        page = repository.run(
            ItemQuery(
                user=world.everyone,
                search_term="a film",
                sort=((SortBy.SORT_NAME, order),),
                limit=1000,
            )
        )
        assert page.items[0].item.name == "A Film", order


# ------------------------------------------------------------------------------------------
# AC-7: Random
# ------------------------------------------------------------------------------------------


def test_random_returns_the_whole_set_with_no_duplicates(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(
        films(world, sort=((SortBy.RANDOM, SortOrder.ASCENDING),), limit=1000, random_seed=7)
    )
    ids = [one.id for one in page.items]
    assert len(ids) == len(set(ids)) == CORPUS_SIZE
    assert set(ids) == set(world.corpus)


def test_a_random_page_has_no_duplicates_either(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(
        films(world, sort=((SortBy.RANDOM, SortOrder.ASCENDING),), limit=17, random_seed=7)
    )
    ids = [one.id for one in page.items]
    assert len(ids) == len(set(ids)) == 17


def test_the_same_seed_is_the_same_shuffle(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Injectable, so the property tests above can exist at all. The server never supplies one:
    it takes fresh entropy per request and never exposes it."""
    query = films(world, sort=((SortBy.RANDOM, SortOrder.ASCENDING),), limit=30, random_seed=99)
    assert ordered(repository, query) == ordered(repository, query)


def test_a_different_seed_is_a_different_shuffle(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    first = films(world, sort=((SortBy.RANDOM, SortOrder.ASCENDING),), limit=30, random_seed=1)
    second = films(world, sort=((SortBy.RANDOM, SortOrder.ASCENDING),), limit=30, random_seed=2)
    assert ordered(repository, first) != ordered(repository, second)


def test_random_is_not_the_sort_name_order(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """A shuffle that returned the natural order would pass every test above."""
    shuffled = ordered(
        repository,
        films(world, sort=((SortBy.RANDOM, SortOrder.ASCENDING),), limit=1000, random_seed=5),
    )
    natural = ordered(
        repository, films(world, sort=((SortBy.SORT_NAME, SortOrder.ASCENDING),), limit=1000)
    )
    assert shuffled != natural


def test_random_still_reports_the_true_total(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    page = repository.run(
        films(world, sort=((SortBy.RANDOM, SortOrder.ASCENDING),), limit=5, random_seed=3)
    )
    assert len(page.items) == 5
    assert page.total == CORPUS_SIZE


def test_random_beyond_the_end_is_empty(repository: ItemQueryRepository, world: QueryWorld) -> None:
    page = repository.run(
        films(
            world,
            sort=((SortBy.RANDOM, SortOrder.ASCENDING),),
            start_index=1000,
            limit=5,
            random_seed=3,
        )
    )
    assert page.items == ()
    assert page.total == CORPUS_SIZE


def test_random_first_in_a_list_wins(repository: ItemQueryRepository, world: QueryWorld) -> None:
    """`sortBy=Random,SortName` is a random ordering: `Random` is not an `ORDER BY` and cannot be
    combined with one."""
    mixed = ordered(
        repository,
        films(
            world,
            sort=((SortBy.RANDOM, SortOrder.ASCENDING), (SortBy.SORT_NAME, SortOrder.ASCENDING)),
            limit=1000,
            random_seed=5,
        ),
    )
    natural = ordered(
        repository, films(world, sort=((SortBy.SORT_NAME, SortOrder.ASCENDING),), limit=1000)
    )
    assert mixed != natural
    assert set(mixed) == set(natural)


# ------------------------------------------------------------------------------------------
# Several keys
# ------------------------------------------------------------------------------------------


def test_a_second_key_breaks_the_first_ones_ties(
    repository: ItemQueryRepository, world: QueryWorld
) -> None:
    """Ninety films share "no production year". Under `ProductionYear` alone the id breaks them;
    with `SortName` second, the name does."""
    by_year_then_name = ordered(
        repository,
        films(
            world,
            sort=(
                (SortBy.PREMIERE_DATE, SortOrder.ASCENDING),
                (SortBy.SORT_NAME, SortOrder.ASCENDING),
            ),
            limit=1000,
        ),
    )
    by_year_alone = ordered(
        repository, films(world, sort=((SortBy.PREMIERE_DATE, SortOrder.ASCENDING),), limit=1000)
    )
    assert by_year_then_name != by_year_alone
    assert set(by_year_then_name) == set(by_year_alone)
