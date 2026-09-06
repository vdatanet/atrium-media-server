# SPDX-License-Identifier: GPL-3.0-or-later
"""One declaration, two databases, and the identifiers that have to match.

**The gap this file closes is why nothing caught the defect.** Every fixture world in this suite
pins its library identifiers — `tests/fixtures/media_world.py` says so in as many words, *"fixed
library identifiers, like every fixture world here, so two builds derive the same items"* — and
nothing anywhere built one library **twice, through `config.create`**, which is what a rebuilt
install does. So the identifier being minted was invisible: every test that could have seen it had
been handed the answer.

What it cost was measured before the change and after it, over one tree, on 2026-09-06: two builds
put **16 of 20** rows of a windowed date ordering in different places, and put **two items in one
window that the other build's did not hold at all**. The ties are not the cause and do not move —
52 items over 3 instants either way — it is the tie-*break* that moves, because
`db/item_queries._order_by` ends every ordering on `Item.id` and every file-backed identifier
hashes the library's own.

003 §3.6 and AC-17.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import ItemRepository, LibraryRepository, UserRepository
from atrium.domain.queries import ItemQuery, SortBy, SortOrder
from atrium.domain.user import User
from atrium.library import config
from atrium.library.scan import scan
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture

#: Twenty rows over a tree of fifty-odd items, which is what makes this a **window** rather than a
#: listing — the shape `GET /Items/Latest` has and the one an unstable tie-break moves items in and
#: out of, rather than merely reordering.
WINDOW = 20


def a_build(where: Path, fixture: BuiltFixture) -> tuple[Engine, object]:
    """One whole install: its own database, its own declaration, its own scan.

    `config.create` rather than a pinned identifier, deliberately and unlike every other fixture
    here: what is under test is precisely what that function allocates.
    """
    paths = data_dir(where)
    engine = create_database_engine(paths)
    schema.ensure_current(engine, paths)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        for collection_type in ("movies", "tvshows", "music"):
            library = config.create(
                LibraryRepository(db),
                collection_type.title(),
                collection_type,
                (str(fixture.of(collection_type).root),),
            )
            scan(library, db, prober=not_media)
    return engine, factory


def identifiers(factory: object) -> set[str]:
    with session_scope(factory) as db:  # type: ignore[arg-type]
        repository = ItemRepository(db)
        return {
            item_id
            for library in LibraryRepository(db).all()
            for item_id in repository.by_library(library.id)
        }


def a_window(factory: object) -> list[str]:
    """The most recent `WINDOW` items, by name, in order."""
    with session_scope(factory) as db:  # type: ignore[arg-type]
        user = UserRepository(db).add(User(id="a" * 32, name="everyone", enable_all_folders=True))
        page = ItemQueryRepository(db).run(
            ItemQuery(
                user=user,
                recursive=True,
                limit=WINDOW,
                sort=((SortBy.DATE_CREATED, SortOrder.DESCENDING),),
            )
        )
        return [one.item.name for one in page.items]


def test_two_databases_from_one_declaration_hold_the_same_identifiers(
    tmp_path: Path, fixture_library: BuiltFixture
) -> None:
    """AC-17. The claim a client's cached favourites rest on when a server is rebuilt."""
    one_engine, first = a_build(tmp_path / "first", fixture_library)
    other_engine, second = a_build(tmp_path / "second", fixture_library)
    try:
        one, other = identifiers(first), identifiers(second)
        assert one, "the builds scanned nothing, so this would assert two empty sets"
        assert one == other
    finally:
        one_engine.dispose()
        other_engine.dispose()


def test_the_window_over_a_tied_ordering_holds_still_across_two_builds(
    tmp_path: Path, fixture_library: BuiltFixture
) -> None:
    """The consequence, and the thing that was actually measured wrong.

    Every file of the fixture tree carries one fixed modification time, so a date ordering over it
    is one large tie and the tail decides the whole of it — which makes this the sharpest possible
    statement of the property: not that the order is meaningful, but that it **holds still**.
    """
    one_engine, first = a_build(tmp_path / "first", fixture_library)
    other_engine, second = a_build(tmp_path / "second", fixture_library)
    try:
        one, other = a_window(first), a_window(second)
        assert len(one) == WINDOW
        assert sorted(one) == sorted(other), "the two windows do not even hold the same items"
        assert one == other
    finally:
        one_engine.dispose()
        other_engine.dispose()
