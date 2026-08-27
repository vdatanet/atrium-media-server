# SPDX-License-Identifier: GPL-3.0-or-later
"""Revision 0002: feature 003's schema, and the one guarantee that is an *absence*.

The generic sweep in test_migrations.py already applies this revision, rolls it back and compares
the schema. What it cannot see is the thing this file exists for: **`item_user_data` has no foreign
key to `items`, on purpose**, and a cascade added later would look like tidying up.

That is the strongest test here and it is asserted twice - once by reading the constraint, and once
by deleting an item row and reading the user data back. The first catches somebody adding the
foreign key; the second catches somebody arranging the deletion in application code instead, which
the first would not notice.

003 spec section 3.8: a file that disappears and comes back - a re-download, a remount, a network
share slow to mount - must not cost the user their favourites and resume position.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError

from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.models import (
    Item,
    ItemSource,
    ItemUserData,
    Library,
    LibraryRoot,
    User,
)
from atrium.domain.items import IN_THE_TREE, ItemType
from tests.conftest import data_dir


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def migrated(prepared: DataPaths) -> Engine:
    engine = create_database_engine(prepared)
    schema.ensure_current(engine, prepared)
    yield engine
    engine.dispose()


def a_library(**overrides: object) -> Library:
    fields: dict[str, object] = {"id": new_id(), "name": "Movies", "collection_type": "movies"}
    fields.update(overrides)
    return Library(**fields)


def an_item(library_id: str, **overrides: object) -> Item:
    fields: dict[str, object] = {
        "id": new_id(),
        "library_id": library_id,
        "type": ItemType.MOVIE.value,
        "name": "The Film",
        "sort_name": "film",
    }
    fields.update(overrides)
    return Item(**fields)


# --------------------------------------------------------------------------------------------
# The absence that is the feature
# --------------------------------------------------------------------------------------------


def test_item_user_data_has_no_foreign_key_to_items(migrated: Engine) -> None:
    """Read from the schema, so that adding one is a failing test rather than a code review."""
    with migrated.connect() as connection:
        keys = inspect(connection).get_foreign_keys("item_user_data")
    referred = {key["referred_table"] for key in keys}
    assert "items" not in referred, (
        "item_user_data now references items. Under a cascade, the first time a network share was "
        "slow to mount a scan would delete every user's favourites and resume positions for that "
        "library, permanently, and the only symptom would be a user saying their list looks wrong. "
        "003 spec section 3.8. Read the docstring on ItemUserData before changing this."
    )
    assert referred == {"users"}, "the only reference it should carry is the account that owns it"


def test_deleting_an_item_leaves_its_user_data_intact(migrated: Engine) -> None:
    """The same guarantee, asserted through behaviour rather than through the schema.

    Somebody could keep the schema honest and still arrange the deletion in application code. This
    notices, because it deletes the row the way a purge would and then reads the user data back.
    """
    factory = session_factory(migrated)
    library_id, item_id, user_id = new_id(), new_id(), new_id()

    with session_scope(factory) as db:
        db.add(User(id=user_id, name="Joan", name_normalised="joan", password_hash=None))
        db.add(a_library(id=library_id))
        db.add(an_item(library_id, id=item_id))
        db.flush()
        db.add(
            ItemUserData(
                user_id=user_id,
                item_key=item_id,
                is_favorite=True,
                playback_position_ticks=12_345_670_000,
            )
        )

    with session_scope(factory) as db:
        db.execute(delete(Item).where(Item.id == item_id))

    with session_scope(factory) as db:
        surviving = db.execute(
            select(ItemUserData).where(ItemUserData.item_key == item_id)
        ).scalar_one()
        assert surviving.is_favorite is True
        assert surviving.playback_position_ticks == 12_345_670_000


def test_the_same_path_scanned_again_finds_its_user_data(migrated: Engine) -> None:
    """Why the key is the derived identity and not a row reference: the association comes back.

    The item is deleted and recreated with the *same* identifier, which is what a rescan of an
    unchanged path produces (003 spec section 3.6). Nothing reconnects them - they were never
    disconnected.
    """
    factory = session_factory(migrated)
    library_id, item_id, user_id = new_id(), new_id(), new_id()

    with session_scope(factory) as db:
        db.add(User(id=user_id, name="Joan", name_normalised="joan", password_hash=None))
        db.add(a_library(id=library_id))
        db.add(an_item(library_id, id=item_id))
        db.flush()
        db.add(ItemUserData(user_id=user_id, item_key=item_id, played=True, play_count=3))

    with session_scope(factory) as db:
        db.execute(delete(Item).where(Item.id == item_id))
    with session_scope(factory) as db:
        db.add(an_item(library_id, id=item_id))

    with session_scope(factory) as db:
        restored = db.execute(
            select(ItemUserData).where(ItemUserData.item_key == item_id)
        ).scalar_one()
        assert (restored.played, restored.play_count) == (True, 3)


def test_deleting_a_user_does_take_their_user_data(migrated: Engine) -> None:
    """The other direction still cascades: the row belongs to the account, not to the item."""
    factory = session_factory(migrated)
    user_id = new_id()

    with session_scope(factory) as db:
        db.add(User(id=user_id, name="Joan", name_normalised="joan", password_hash=None))
        db.flush()
        db.add(ItemUserData(user_id=user_id, item_key=new_id()))

    with session_scope(factory) as db:
        db.execute(delete(User).where(User.id == user_id))
    with session_scope(factory) as db:
        assert db.execute(select(ItemUserData)).all() == []


# --------------------------------------------------------------------------------------------
# The indexes 005 will need
# --------------------------------------------------------------------------------------------


def test_the_ordering_index_exists(migrated: Engine) -> None:
    """005 orders nearly every list by sort_name within a library and a type."""
    with migrated.connect() as connection:
        indexes = {
            index["name"]: list(index["column_names"] or [])
            for index in inspect(connection).get_indexes("items")
        }
    assert indexes["ix_items_library_type_sort"] == ["library_id", "type", "sort_name"]
    assert indexes["ix_items_parent_index"] == ["parent_id", "index_number"]


def test_sort_name_cannot_be_null(migrated: Engine) -> None:
    """An item with no sort name would sort first, everywhere, and nothing would say why.

    Asserted against the **schema**, in SQL, rather than through the ORM. Through the ORM this
    cannot be reached: the column carries a Python-side default, so assigning `None` inserts the
    empty string instead of failing. That default is the right behaviour for the scanner and it
    also means the ORM can never demonstrate the constraint - only a statement that bypasses it
    can, and only that proves the database would refuse a row written by anything else.
    """
    library_id = new_id()
    with migrated.begin() as connection:
        connection.execute(
            text("INSERT INTO libraries (id, name, collection_type) VALUES (:i, 'M', 'movies')"),
            {"i": library_id},
        )
    with pytest.raises(IntegrityError), migrated.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO items (id, library_id, type, name, sort_name) "
                "VALUES (:i, :l, 'Movie', 'The Film', NULL)"
            ),
            {"i": new_id(), "l": library_id},
        )


def test_an_item_written_without_a_sort_name_gets_the_empty_string(migrated: Engine) -> None:
    """The other side of the same column: the scanner never has to remember to set it."""
    factory = session_factory(migrated)
    library_id, item_id = new_id(), new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
        db.add(Item(id=item_id, library_id=library_id, type=ItemType.MOVIE.value, name="The Film"))
    with session_scope(factory) as db:
        assert db.execute(select(Item).where(Item.id == item_id)).scalar_one().sort_name == ""


# --------------------------------------------------------------------------------------------
# AC-4 and AC-5: the two shapes the accepted plan could not hold
# --------------------------------------------------------------------------------------------


def test_one_film_holds_two_sources_in_order(migrated: Engine) -> None:
    """AC-4. One Movie, two parts - the shape a single relative_path column could not store."""
    factory = session_factory(migrated)
    library_id, item_id = new_id(), new_id()

    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
        db.add(an_item(library_id, id=item_id, name="The Long Film"))
        db.flush()
        db.add(ItemSource(item_id=item_id, part_index=0, relative_path="film - part1.mkv", size=1))
        db.add(ItemSource(item_id=item_id, part_index=1, relative_path="film - part2.mkv", size=2))

    with session_scope(factory) as db:
        parts = (
            db.execute(
                select(ItemSource)
                .where(ItemSource.item_id == item_id)
                .order_by(ItemSource.part_index)
            )
            .scalars()
            .all()
        )
        assert [part.relative_path for part in parts] == [
            "film - part1.mkv",
            "film - part2.mkv",
        ]
        assert (
            db.execute(select(Item).where(Item.id == item_id)).scalar_one().name == "The Long Film"
        )


def test_one_episode_spans_two_numbers(migrated: Engine) -> None:
    """AC-5. `S01E02-E03` is one row, not two."""
    factory = session_factory(migrated)
    library_id, item_id = new_id(), new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id, collection_type="tvshows"))
        db.add(
            an_item(
                library_id,
                id=item_id,
                type=ItemType.EPISODE.value,
                name="Two Parter",
                parent_index_number=1,
                index_number=2,
                end_index_number=3,
            )
        )
    with session_scope(factory) as db:
        episode = db.execute(select(Item).where(Item.id == item_id)).scalar_one()
        assert (episode.index_number, episode.end_index_number) == (2, 3)


def test_deleting_an_item_takes_its_sources(migrated: Engine) -> None:
    """Sources are part of the item, unlike user data. The contrast is the whole design."""
    factory = session_factory(migrated)
    library_id, item_id = new_id(), new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
        db.add(an_item(library_id, id=item_id))
        db.flush()
        db.add(ItemSource(item_id=item_id, part_index=0, relative_path="film.mkv"))

    with session_scope(factory) as db:
        db.execute(delete(Item).where(Item.id == item_id))
    with session_scope(factory) as db:
        assert db.execute(select(ItemSource)).all() == []


# --------------------------------------------------------------------------------------------
# What the schema refuses
# --------------------------------------------------------------------------------------------


def test_a_collection_type_the_resolver_cannot_scan_is_refused(migrated: Engine) -> None:
    """Spec section 3.1 has three. A fourth would be a library nothing knows how to scan."""
    factory = session_factory(migrated)
    with pytest.raises(IntegrityError), session_scope(factory) as db:
        db.add(a_library(collection_type="books"))


def test_an_item_type_no_client_knows_is_refused(migrated: Engine) -> None:
    """Principle I: a type the reference lacks is a delta, written long before anyone looks."""
    factory = session_factory(migrated)
    library_id = new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
    with pytest.raises(IntegrityError), session_scope(factory) as db:
        db.add(an_item(library_id, type="Film"))


def test_the_check_constraint_lists_exactly_the_types_the_domain_has(migrated: Engine) -> None:
    """Two lists of the same eight strings; something has to notice when one of them grows.

    It did, at 004 T4, and the answer was not to widen this: **a migration is a record of what the
    schema was at a point in time**, and 0002 predates the five by-name types by a revision. So the
    list this compares against is `IN_THE_TREE` - everything 003 could produce - and 0003 is where
    the other five arrive, asserted in `test_migration_0003.py` against the whole of `ItemType`.
    Widening this one instead would have made it assert nothing: it would list whatever the domain
    lists, forever, which is the shape of a test that cannot fail.
    """
    factory = session_factory(migrated)
    library_id = new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
    for item_type in sorted(IN_THE_TREE):
        with session_scope(factory) as db:
            db.add(an_item(library_id, type=item_type.value))


def test_a_library_takes_several_roots(migrated: Engine) -> None:
    """One of the reference's libraries in the OQ-1 measurement had two."""
    factory = session_factory(migrated)
    library_id = new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
        db.flush()
        db.add(LibraryRoot(library_id=library_id, path="/mnt/a"))
        db.add(LibraryRoot(library_id=library_id, path="/mnt/b"))
    with session_scope(factory) as db:
        assert len(db.execute(select(LibraryRoot)).all()) == 2


def test_removing_a_library_takes_its_roots_and_items(migrated: Engine) -> None:
    factory = session_factory(migrated)
    library_id = new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
        db.flush()
        db.add(LibraryRoot(library_id=library_id, path="/mnt/a"))
        db.add(an_item(library_id))

    with session_scope(factory) as db:
        db.execute(delete(Library).where(Library.id == library_id))
    with session_scope(factory) as db:
        assert db.execute(select(LibraryRoot)).all() == []
        assert db.execute(select(Item)).all() == []


def test_a_removed_item_keeps_its_row(migrated: Engine) -> None:
    """Soft deletion: 003 plan section 6.6. A scan never purges; only maintenance does."""
    factory = session_factory(migrated)
    library_id, item_id = new_id(), new_id()
    with session_scope(factory) as db:
        db.add(a_library(id=library_id))
        db.add(an_item(library_id, id=item_id))
    with session_scope(factory) as db:
        db.execute(select(Item).where(Item.id == item_id)).scalar_one().removed_at = datetime(
            2026, 8, 27, tzinfo=UTC
        )
    with session_scope(factory) as db:
        still_there = db.execute(select(Item).where(Item.id == item_id)).scalar_one()
        assert still_there.removed_at is not None
