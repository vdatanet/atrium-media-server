# SPDX-License-Identifier: GPL-3.0-or-later
"""The engine, and the two pragmas that would be silently absent if nothing asserted them.

Both failures this file exists for are invisible from the outside. A database that fell back to
rollback-journal mode serves every read correctly and blocks them all during a scan; a connection
without `foreign_keys=ON` accepts an orphan row and reports success. Neither shows up in a response,
so neither would be noticed by anything else in this suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from atrium.config.paths import ConfigurationError, DataPaths
from atrium.db.engine import (
    create_database_engine,
    session_factory,
    session_scope,
    verify_connection,
)


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    return paths


# --------------------------------------------------------------------------------------------
# The file
# --------------------------------------------------------------------------------------------


def test_a_fresh_database_is_created_in_the_data_directory(prepared: DataPaths) -> None:
    assert not prepared.database.exists()
    engine = create_database_engine(prepared)
    try:
        verify_connection(engine, prepared)
        assert prepared.database.is_file()
        assert prepared.database.parent == prepared.root
    finally:
        engine.dispose()


def test_an_unopenable_database_refuses_to_start(prepared: DataPaths) -> None:
    """Named at startup rather than discovered on the first request. plan section 7."""
    prepared.database.mkdir()  # a directory where the file belongs: SQLite cannot open it
    engine = create_database_engine(prepared)
    try:
        with pytest.raises(ConfigurationError) as refusal:
            verify_connection(engine, prepared)
    finally:
        engine.dispose()
    assert str(prepared.database) in str(refusal.value)


# --------------------------------------------------------------------------------------------
# The pragmas
# --------------------------------------------------------------------------------------------


def test_journal_mode_is_wal(prepared: DataPaths) -> None:
    engine = create_database_engine(prepared)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
    finally:
        engine.dispose()


def test_every_connection_gets_the_pragmas_not_just_the_first(prepared: DataPaths) -> None:
    """`foreign_keys` is per connection, so a pragma applied once at startup protects nothing.

    Two connections are opened at the same time, which forces the pool to make a second one rather
    than hand back the first.
    """
    engine = create_database_engine(prepared)
    try:
        with engine.connect() as first, engine.connect() as second:
            assert first.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert second.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert second.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
    finally:
        engine.dispose()


def test_a_foreign_key_is_actually_enforced(prepared: DataPaths) -> None:
    """The pragma is set; this is the assertion that it does something."""
    engine = create_database_engine(prepared)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
            connection.execute(
                text("CREATE TABLE child (id INTEGER PRIMARY KEY, p INTEGER REFERENCES parent(id))")
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("INSERT INTO child (p) VALUES (404)"))
    finally:
        engine.dispose()


def test_wal_survives_being_reopened(prepared: DataPaths) -> None:
    """`journal_mode` belongs to the file, so a second engine inherits it rather than setting it."""
    first = create_database_engine(prepared)
    try:
        with first.connect() as connection:
            connection.execute(text("PRAGMA journal_mode"))
    finally:
        first.dispose()

    second = create_database_engine(prepared)
    try:
        with second.connect() as connection:
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
    finally:
        second.dispose()


def test_two_instances_do_not_configure_each_others_connections(tmp_path: Path) -> None:
    """The listener is bound to one engine, not to the `Engine` class.

    Binding it to the class would work and would mean a second instance in the same process - which
    this suite builds constantly - reconfigures the first one's connections.
    """
    one = DataPaths(tmp_path / "one")
    two = DataPaths(tmp_path / "two")
    one.prepare()
    two.prepare()
    first = create_database_engine(one)
    second = create_database_engine(two)
    try:
        with first.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        with second.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert first.url != second.url
    finally:
        first.dispose()
        second.dispose()


# --------------------------------------------------------------------------------------------
# The unit of work
# --------------------------------------------------------------------------------------------


def test_a_session_scope_commits_what_succeeded(prepared: DataPaths) -> None:
    engine = create_database_engine(prepared)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE note (id INTEGER PRIMARY KEY, body TEXT)"))
        factory = session_factory(engine)
        with session_scope(factory) as session:
            session.execute(text("INSERT INTO note (body) VALUES ('kept')"))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT body FROM note")).scalar_one() == "kept"
    finally:
        engine.dispose()


def test_a_session_scope_rolls_back_what_raised(prepared: DataPaths) -> None:
    """The half that gets forgotten at a call site, which is why it is not written at call sites."""
    engine = create_database_engine(prepared)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE note (id INTEGER PRIMARY KEY, body TEXT)"))
        factory = session_factory(engine)
        with pytest.raises(OperationalError), session_scope(factory) as session:
            session.execute(text("INSERT INTO note (body) VALUES ('doomed')"))
            session.execute(text("INSERT INTO nonexistent (body) VALUES ('boom')"))
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM note")).scalar_one() == 0
    finally:
        engine.dispose()
