# SPDX-License-Identifier: GPL-3.0-or-later
"""Revision 0001: the whole of feature 002's schema.

The strongest test here is the last one. "No column holds a usable token" can be asserted by
reading column names, and that only proves nobody called a column `token` - so it is also asserted
by writing a real token through the code that stores one and then reading **the database file, and
its write-ahead log, as bytes**. A future column that quietly kept the plaintext would pass the
first test and fail the second.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError, StatementError

from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.models import AccessToken, Base, Session, User, UserLibraryAccess
from tests.conftest import data_dir

#: Spec section 3.5 honours eleven policy properties. Two of them are lists of libraries and live
#: in `user_library_access`, so nine are columns - which is the count plan section 4 asks for, and
#: the one a reader is most likely to get wrong.
HONOURED_COLUMNS = {
    "is_administrator",
    "is_disabled",
    "is_hidden",
    "enable_all_folders",
    "enable_media_playback",
    "enable_content_deletion",
    "login_attempts_before_lockout",
    "invalid_login_attempt_count",
    "max_active_sessions",
}


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def migrated(prepared: DataPaths) -> Engine:
    """A database at head, created the way a first run creates one."""
    engine = create_database_engine(prepared)
    schema.ensure_current(engine, prepared)
    yield engine
    engine.dispose()


def make_user(**overrides: object) -> User:
    fields: dict[str, object] = {
        "id": new_id(),
        "name": "Joan",
        "name_normalised": "joan",
        "password_hash": None,
    }
    fields.update(overrides)
    return User(**fields)


# --------------------------------------------------------------------------------------------
# Up, and back down
# --------------------------------------------------------------------------------------------


def test_upgrade_then_downgrade_leaves_an_empty_database(prepared: DataPaths) -> None:
    """Reversible, asserted rather than claimed in a docstring."""
    engine = create_database_engine(prepared)
    try:
        config = schema.alembic_config(prepared)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        with engine.connect() as connection:
            assert "users" in inspect(connection).get_table_names()

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        with engine.connect() as connection:
            remaining = set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
    assert remaining <= {schema.VERSION_TABLE}, f"downgrade left {sorted(remaining)} behind"


def test_upgrade_from_an_empty_file(prepared: DataPaths) -> None:
    """The path an operator actually takes: the file exists and has nothing in it.

    Not the same as no file at all - a restore that copied a zero-byte database, or a volume mount
    that created the path, both land here.

    The head is read rather than spelled out, because this test is about the empty file and not
    about which revision is current - it pinned `0001` until `0002` landed and failed for a reason
    that had nothing to do with what it tests. The build's shipped head is pinned deliberately, in
    one place, by test_db_schema.py.
    """
    prepared.database.write_bytes(b"")
    assert prepared.database.stat().st_size == 0

    engine = create_database_engine(prepared)
    try:
        schema.ensure_current(engine, prepared)
        assert schema.current_revision(engine) == schema.head_revision(
            schema.alembic_config(prepared)
        )
    finally:
        engine.dispose()


def test_the_migration_and_the_models_agree(migrated: Engine) -> None:
    """Editing `models.py` without a migration is the mistake this catches.

    Alembic compares the live schema against `Base.metadata` and reports the difference. An empty
    difference is the only state in which the code and the database describe the same thing.
    """
    with migrated.connect() as connection:
        context = MigrationContext.configure(connection)
        difference = compare_metadata(context, Base.metadata)
    assert difference == [], f"models.py and revision 0001 disagree: {difference}"


# --------------------------------------------------------------------------------------------
# Enforced versus echoed
# --------------------------------------------------------------------------------------------


def test_the_honoured_policy_properties_are_nine_columns(migrated: Engine) -> None:
    """Eleven honoured properties, nine columns, two of them a join table. Pinned, because the
    three ways of counting it give three different numbers."""
    with migrated.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("users")}
    assert columns >= HONOURED_COLUMNS
    assert len(HONOURED_COLUMNS) == 9
    assert {"policy_extra", "configuration"} <= columns


def test_the_two_list_properties_are_a_join_table(migrated: Engine) -> None:
    """`EnabledFolders` and `EnableContentDeletionFromFolders`, because 005 filters on them."""
    with migrated.connect() as connection:
        found = inspect(connection).get_columns("user_library_access")
    columns = {column["name"] for column in found}
    assert columns == {"user_id", "library_id", "can_view", "can_delete"}


def test_a_policy_v1_has_never_heard_of_survives_the_round_trip(migrated: Engine) -> None:
    """The blob is echoed, not interpreted. AC-8's shape, at the storage layer."""
    unknown = {"EnableSyncTranscoding": False, "SomethingFromTheFuture": {"nested": [1, 2, 3]}}
    factory = session_factory(migrated)
    user = make_user(policy_extra=unknown, configuration={"AudioLanguagePreference": "cat"})
    with session_scope(factory) as session:
        session.add(user)
    with session_scope(factory) as session:
        stored = session.execute(select(User)).scalar_one()
        assert stored.policy_extra == unknown
        assert stored.configuration == {"AudioLanguagePreference": "cat"}


# --------------------------------------------------------------------------------------------
# No column holds a usable token
# --------------------------------------------------------------------------------------------


def test_no_column_is_named_as_if_it_held_a_token(migrated: Engine) -> None:
    with migrated.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("access_tokens")}
    assert "token_sha256" in columns
    assert not {"token", "access_token", "value", "secret"} & columns


def test_the_token_itself_is_nowhere_in_the_database_file(
    prepared: DataPaths, migrated: Engine
) -> None:
    """The assertion a column name cannot make.

    A leaked database file must not hand over a live session, so the plaintext has to be absent
    from the bytes - including the write-ahead log, where a recent commit still lives until SQLite
    checkpoints it.
    """
    token = secrets.token_hex(16)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()

    factory = session_factory(migrated)
    user = make_user()
    with session_scope(factory) as session:
        session.add(user)
        session.add(
            AccessToken(
                token_sha256=digest,
                user_id=user.id,
                device_id="device-1",
                created=datetime.now(UTC),
                last_used=datetime.now(UTC),
            )
        )

    written = b"".join(
        path.read_bytes() for path in sorted(prepared.root.glob("atrium.db*")) if path.is_file()
    )
    assert token.encode("ascii") not in written, "the plaintext token reached the database file"
    assert digest.encode("ascii") in written, "nothing was stored at all, so this proves nothing"


# --------------------------------------------------------------------------------------------
# The constraints that make a rule a rule
# --------------------------------------------------------------------------------------------


def test_two_accounts_cannot_differ_only_in_case(migrated: Engine) -> None:
    """Login is case-insensitive, so `Joan` and `joan` would be one login and two accounts."""
    factory = session_factory(migrated)
    with session_scope(factory) as session:
        session.add(make_user(name="Joan", name_normalised="joan"))
    with pytest.raises(IntegrityError), session_scope(factory) as session:
        session.add(make_user(name="JOAN", name_normalised="joan"))


def test_one_session_per_user_and_device(migrated: Engine) -> None:
    """Re-authenticating replaces rather than accumulates, enforced here and not only in the code.

    A bug in the replace path is then a constraint violation, rather than a second row nobody
    notices until `/Sessions` lists the same phone twice.
    """
    factory = session_factory(migrated)
    user = make_user()
    with session_scope(factory) as session:
        session.add(user)
        session.add(
            Session(
                id=new_id(),
                user_id=user.id,
                device_id="phone",
                last_activity_date=datetime.now(UTC),
            )
        )
    with pytest.raises(IntegrityError), session_scope(factory) as session:
        session.add(
            Session(
                id=new_id(),
                user_id=user.id,
                device_id="phone",
                last_activity_date=datetime.now(UTC),
            )
        )


def test_deleting_a_user_takes_its_tokens_and_sessions(migrated: Engine) -> None:
    """`ON DELETE CASCADE`, which does nothing at all unless the foreign-key pragma is on."""
    factory = session_factory(migrated)
    user = make_user()
    with session_scope(factory) as session:
        session.add(user)
        session.add(
            AccessToken(
                token_sha256="a" * 64,
                user_id=user.id,
                device_id="phone",
                created=datetime.now(UTC),
                last_used=datetime.now(UTC),
            )
        )
        session.add(
            Session(
                id=new_id(),
                user_id=user.id,
                device_id="phone",
                last_activity_date=datetime.now(UTC),
            )
        )
        session.add(UserLibraryAccess(user_id=user.id, library_id=new_id()))

    with session_scope(factory) as session:
        session.delete(session.execute(select(User)).scalar_one())

    with session_scope(factory) as session:
        assert session.execute(select(AccessToken)).all() == []
        assert session.execute(select(Session)).all() == []
        assert session.execute(select(UserLibraryAccess)).all() == []


# --------------------------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------------------------


def test_a_timestamp_comes_back_as_the_instant_that_went_in(migrated: Engine) -> None:
    """SQLite stores the wall clock and drops the offset. `UtcDateTime` converts instead.

    The `+02:00` value is the one that matters: stored naively it would come back two hours in the
    future, and nothing would raise.
    """
    factory = session_factory(migrated)
    east = datetime(2026, 8, 26, 23, 30, tzinfo=timezone(timedelta(hours=2)))
    user = make_user(last_login_date=east)
    with session_scope(factory) as session:
        session.add(user)
    with session_scope(factory) as session:
        stored = session.execute(select(User)).scalar_one()
        assert stored.last_login_date is not None
        assert stored.last_login_date == east
        assert stored.last_login_date.tzinfo is not None
        assert stored.last_login_date.hour == 21


def test_a_naive_timestamp_is_refused(migrated: Engine) -> None:
    """Guessing which zone somebody meant is how the two-hour error gets in."""
    factory = session_factory(migrated)
    # SQLAlchemy wraps a bind-parameter failure, so the type's own ValueError arrives inside a
    # StatementError - whose message still carries it, which is what an operator would read.
    with pytest.raises(StatementError, match="naive datetime"), session_scope(factory) as session:
        # The naive datetime is the whole point of this test, so DTZ001 is silenced here.
        session.add(make_user(last_login_date=datetime(2026, 8, 26, 21, 30)))  # noqa: DTZ001
