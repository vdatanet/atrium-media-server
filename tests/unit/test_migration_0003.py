# SPDX-License-Identifier: GPL-3.0-or-later
"""Revision 0003: what it creates, what it refuses, and that it matches the models.

The sweep in `test_migrations.py` already applies every revision and rolls it back. What it cannot
see is the failure this revision is most likely to have, because `items` is **rebuilt** rather than
widened: SQLite cannot alter a check constraint in place, so the whole table is copied - and
SQLAlchemy's SQLite dialect does not reflect check constraints. A rebuild that trusted reflection
would silently drop `ck_items_type` and lose 0002's two indexes, and every existing test would
still pass.

So the first test here is the one that would have caught that: **the schema the migrations produce
and the schema the models declare are the same schema**, compared column by column, index by index,
constraint by constraint. It covers every revision rather than only this one, and it is here rather
than in `test_migrations.py` because this is the revision that made it necessary.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine
from atrium.db.models import Base
from atrium.domain.items import BY_NAME, USER_CREATED, ItemType
from tests.conftest import data_dir


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def migrated(paths: DataPaths) -> Iterator[Engine]:
    """A database brought to head the way an installation is: by running the migrations."""
    built = create_database_engine(paths)
    config = schema.alembic_config(paths)
    with built.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield built
    built.dispose()


def snapshot(engine: Engine) -> dict[str, Any]:
    """Everything about a schema that a migration can get wrong without failing."""
    inspector = inspect(engine)
    found: dict[str, Any] = {}
    for table in sorted(inspector.get_table_names()):
        if table == schema.VERSION_TABLE:
            continue
        found[table] = {
            "columns": {
                column["name"]: (str(column["type"]), column["nullable"])
                for column in inspector.get_columns(table)
            },
            "primary_key": tuple(inspector.get_pk_constraint(table)["constrained_columns"]),
            "indexes": {
                index["name"]: tuple(index["column_names"])
                for index in inspector.get_indexes(table)
            },
            "foreign_keys": sorted(
                (
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    tuple(key["referred_columns"]),
                    (key.get("options") or {}).get("ondelete"),
                )
                for key in inspector.get_foreign_keys(table)
            ),
            "checks": sorted(
                (check["name"], " ".join(str(check["sqltext"]).split()))
                for check in inspector.get_check_constraints(table)
            ),
        }
    return found


def test_the_migrations_and_the_models_describe_the_same_schema(migrated: Engine) -> None:
    """The drift nothing else would catch.

    Two databases: one built by running every migration, one by `create_all` over the declarative
    metadata. They must be indistinguishable. A column added to a model and forgotten in a
    revision - or the reverse - passes every other test in this suite, and shows up as a query
    that works on a developer's machine and fails on an upgraded install.
    """
    declared = create_engine("sqlite://")
    try:
        Base.metadata.create_all(declared)
        from_migrations, from_models = snapshot(migrated), snapshot(declared)
    finally:
        declared.dispose()

    assert set(from_migrations) == set(from_models), (
        f"only in migrations: {sorted(set(from_migrations) - set(from_models))}; "
        f"only in models: {sorted(set(from_models) - set(from_migrations))}"
    )
    for table in sorted(from_migrations):
        assert from_migrations[table] == from_models[table], f"{table} differs"


# --------------------------------------------------------------------------------------------
# What the rebuild must not have lost
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "index",
    [
        "ix_items_library_type_sort",
        "ix_items_parent_index",
        "ix_items_production_year",
        "ix_items_premiere_date",
        "ix_items_community_rating",
        "ix_items_date_created",
        "ix_items_name_folded",
        "ix_items_refresh_pending",
    ],
)
def test_items_keeps_every_index_across_the_rebuild(migrated: Engine, index: str) -> None:
    """The first two are 0002's, and they are the ones at risk: `copy_from` replaces reflection,
    so a definition that did not name them would drop them. An index that quietly stopped existing
    is a query that quietly got slower, which nothing else here would fail on."""
    names = {found["name"] for found in inspect(migrated).get_indexes("items")}
    assert index in names


def test_the_type_check_survived_the_rebuild(migrated: Engine) -> None:
    """The constraint SQLite will not reflect, and therefore the one a rebuild loses."""
    with migrated.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO items (id, library_id, type, name) VALUES ('a', NULL, 'NotAType', 'x')"
            )
        )


# --------------------------------------------------------------------------------------------
# The by-name constraint, in both directions
# --------------------------------------------------------------------------------------------


def a_library(connection: Any, library_id: str = "l" * 32) -> str:
    connection.execute(
        text(
            "INSERT INTO libraries (id, name, collection_type, case_sensitive_identity) "
            "VALUES (:id, 'Films', 'movies', 0)"
        ),
        {"id": library_id},
    )
    return library_id


def test_a_by_name_row_may_have_no_library(migrated: Engine) -> None:
    with migrated.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO items (id, library_id, type, name) "
                "VALUES ('g', NULL, 'Genre', 'Drama')"
            )
        )
        assert connection.execute(text("SELECT count(*) FROM items")).scalar() == 1


def test_a_by_name_row_with_a_library_is_refused(migrated: Engine) -> None:
    """A genre that belonged to one library would appear under it and belong to all of them."""
    with migrated.begin() as connection:
        library = a_library(connection)
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO items (id, library_id, type, name) "
                    "VALUES ('g', :library, 'Genre', 'Drama')"
                ),
                {"library": library},
            )


def test_a_file_backed_row_without_a_library_is_refused(migrated: Engine) -> None:
    """The other direction, which matters just as much: an item with no library is invisible to
    every query 005 scopes by library, and would look like a scanning bug rather than a schema one.
    """
    with migrated.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO items (id, library_id, type, name) "
                "VALUES ('m', NULL, 'Movie', 'The Fixture')"
            )
        )


@pytest.mark.parametrize("kind", ["Genre", "MusicGenre", "Studio", "Person", "Year"])
def test_each_by_name_type_is_accepted(migrated: Engine, kind: str) -> None:
    with migrated.begin() as connection:
        connection.execute(
            text("INSERT INTO items (id, library_id, type, name) VALUES (:id, NULL, :type, 'x')"),
            {"id": kind, "type": kind},
        )


# --------------------------------------------------------------------------------------------
# The join tables
# --------------------------------------------------------------------------------------------


def a_film_and_a_genre(connection: Any) -> None:
    library = a_library(connection)
    connection.execute(
        text(
            "INSERT INTO items (id, library_id, type, name) "
            "VALUES ('film', :library, 'Movie', 'The Fixture')"
        ),
        {"library": library},
    )
    connection.execute(
        text(
            "INSERT INTO items (id, library_id, type, name) "
            "VALUES ('genre', NULL, 'Genre', 'Drama')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO item_genres (item_id, position, name, genre_item_id) "
            "VALUES ('film', 0, 'drama', 'genre')"
        )
    )


def test_deleting_an_item_takes_its_associations_with_it(migrated: Engine) -> None:
    with migrated.begin() as connection:
        a_film_and_a_genre(connection)
        connection.execute(text("DELETE FROM items WHERE id = 'film'"))
        assert connection.execute(text("SELECT count(*) FROM item_genres")).scalar() == 0


def test_deleting_a_referenced_by_name_row_is_refused_rather_than_cascaded(
    migrated: Engine,
) -> None:
    """**The whole reason those foreign keys carry no cascade.** Garbage collection deletes a
    by-name row only when nothing references it; under a cascade a mistake there would remove that
    genre from every item that had it, and the only symptom would be a genre quietly emptying.
    Without one the same mistake is an integrity error, which is a failure somebody can act on.
    """
    with migrated.begin() as connection:
        a_film_and_a_genre(connection)
        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM items WHERE id = 'genre'"))


def test_an_artist_credit_must_be_one_of_the_two(migrated: Engine) -> None:
    """`/Artists` and `/Artists/AlbumArtists` are this column and nothing else."""
    with migrated.begin() as connection:
        library = a_library(connection)
        for item_id, kind in (("track", "Audio"), ("artist", "MusicArtist")):
            connection.execute(
                text(
                    "INSERT INTO items (id, library_id, type, name) "
                    "VALUES (:id, :library, :type, 'x')"
                ),
                {"id": item_id, "library": library, "type": kind},
            )
        connection.execute(
            text(
                "INSERT INTO item_artists (item_id, credit, position, name, artist_item_id) "
                "VALUES ('track', 'album_artist', 0, 'The Artist', 'artist')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO item_artists (item_id, credit, position, name, artist_item_id) "
                    "VALUES ('track', 'performer', 0, 'The Artist', 'artist')"
                )
            )


def an_image(connection: Any, source_kind: str, relative_path: str | None) -> None:
    library = a_library(connection)
    connection.execute(
        text(
            "INSERT INTO items (id, library_id, type, name) "
            "VALUES ('film', :library, 'Movie', 'The Fixture')"
        ),
        {"library": library},
    )
    connection.execute(
        text(
            "INSERT INTO item_images "
            "(item_id, image_type, image_index, source_kind, relative_path, width, height, tag) "
            "VALUES ('film', 'Primary', 0, :kind, :path, 2, 3, :tag)"
        ),
        {"kind": source_kind, "path": relative_path, "tag": "0" * 32},
    )


@pytest.mark.parametrize(
    ("source_kind", "relative_path"),
    [("file", "poster.jpg"), ("remote", "metadata/artwork/film/poster.jpg"), ("embedded", None)],
)
def test_an_image_row_reads_its_path_through_its_source_kind(
    migrated: Engine, source_kind: str, relative_path: str | None
) -> None:
    with migrated.begin() as connection:
        an_image(connection, source_kind, relative_path)


@pytest.mark.parametrize(
    ("source_kind", "relative_path"),
    [("embedded", "poster.jpg"), ("file", None), ("remote", None)],
)
def test_a_path_that_disagrees_with_its_source_kind_is_refused(
    migrated: Engine, source_kind: str, relative_path: str | None
) -> None:
    """The three readings are not interchangeable: embedded bytes live in the audio file and have
    no path at all, and a `file` or `remote` row without one names nothing."""
    with migrated.begin() as connection, pytest.raises(IntegrityError):
        an_image(connection, source_kind, relative_path)


def test_an_image_row_cannot_exist_without_its_dimensions(migrated: Engine) -> None:
    """005 emits `PrimaryImageAspectRatio` from these rows before 006 serves a single byte, so a
    row missing them makes an item's aspect ratio silently absent."""
    with migrated.begin() as connection:
        library = a_library(connection)
        connection.execute(
            text(
                "INSERT INTO items (id, library_id, type, name) "
                "VALUES ('film', :library, 'Movie', 'x')"
            ),
            {"library": library},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO item_images "
                    "(item_id, image_type, image_index, source_kind, relative_path, tag) "
                    "VALUES ('film', 'Primary', 0, 'file', 'poster.jpg', '0')"
                )
            )


def test_the_provider_cache_takes_a_row_and_promises_nothing(migrated: Engine) -> None:
    with migrated.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO provider_cache (provider, request_key, payload, fetched_at) "
                "VALUES ('Tmdb', 'movie/11111', '{}', '2026-08-27T00:00:00.0000000Z')"
            )
        )
        assert connection.execute(text("SELECT count(*) FROM provider_cache")).scalar() == 1


# --------------------------------------------------------------------------------------------
# Rolling back
# --------------------------------------------------------------------------------------------


def test_rolling_back_removes_the_rows_0002_has_no_schema_for(
    migrated: Engine, paths: DataPaths
) -> None:
    """A by-name row cannot exist under 0002's constraint, so the rollback deletes them.

    Losing them costs nothing that is not derivable: the next refresh recreates every one, with
    the same identifier, because the identifier is derived from the folded name (004 plan
    section 6.7). What it loses is which spelling came first - which is exactly what the reference
    loses too.
    """
    with migrated.begin() as connection:
        library = a_library(connection)
        connection.execute(
            text(
                "INSERT INTO items (id, library_id, type, name) "
                "VALUES ('film', :library, 'Movie', 'The Fixture')"
            ),
            {"library": library},
        )
        connection.execute(
            text(
                "INSERT INTO items (id, library_id, type, name) "
                "VALUES ('genre', NULL, 'Genre', 'Drama')"
            )
        )

    config = schema.alembic_config(paths)
    with migrated.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002")

    with migrated.begin() as connection:
        rows = connection.execute(text("SELECT id, type FROM items")).all()
        assert [tuple(row) for row in rows] == [("film", "Movie")], (
            "the film survives and the genre does not"
        )
        assert "overview" not in {
            column["name"] for column in inspect(migrated).get_columns("items")
        }


def test_the_type_check_lists_every_type_this_revision_knows_and_refuses_the_one_it_does_not(
    migrated: Engine,
) -> None:
    """The assertion `test_migration_0002.py` used to make, moved here with the revision that
    widened the list. Two lists of the same strings; something has to notice when one of them
    grows.

    **009 added a fourteenth type, and this test is the fifth structure that was total over
    `ItemType`** - the task list named three. `Playlist` is 0008's value and not 0003's, so the
    accounting stays total by splitting rather than shrinking: every type this revision lists
    inserts, and the one it does not is asserted *refused* here rather than quietly dropped from
    the loop. A fifteenth type breaks this test the way a fourteenth did.
    """
    known = sorted(set(ItemType) - USER_CREATED)
    with migrated.begin() as connection:
        library = a_library(connection)
        for index, kind in enumerate(known):
            connection.execute(
                text(
                    "INSERT INTO items (id, library_id, type, name) "
                    "VALUES (:id, :library, :type, 'x')"
                ),
                {
                    "id": f"{index:032d}",
                    "library": None if kind in BY_NAME else library,
                    "type": kind.value,
                },
            )
        assert connection.execute(text("SELECT count(*) FROM items")).scalar() == len(known)

    insert = "INSERT INTO items (id, library_id, type, name) VALUES (:id, NULL, :type, 'x')"
    for kind in sorted(USER_CREATED):
        with pytest.raises(IntegrityError, match="ck_items_type"), migrated.begin() as connection:
            connection.execute(text(insert), {"id": "f" * 32, "type": kind.value})
