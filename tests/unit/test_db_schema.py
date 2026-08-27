# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether this database is the one this build expects.

Feature 002 has no migrations until T4, so "behind" is not a state the shipped history can be in
yet - and a check that cannot be exercised until the thing it guards exists is a check nobody knows
is broken. These tests build their own two-revision history in a temporary directory and point the
module at it, so every row of the table in `db/schema.py` is a test today rather than an intention.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import inspect, text

from atrium.config.paths import ConfigurationError, DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine
from atrium.server import create_app, main
from tests.conftest import data_dir

#: The first revision reads back `PRAGMA foreign_keys` and refuses if it is off. That is the whole
#: assertion behind `upgrade_to_head` reusing the server's engine: Alembic would happily open its
#: own connection from a URL, and that one would migrate with foreign keys disabled.
FIRST = '''"""first

Revision ID: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("PRAGMA foreign_keys")).scalar() != 1:
        raise AssertionError("this migration is running with foreign keys off")
    op.create_table("widget", sa.Column("id", sa.Integer(), primary_key=True))


def downgrade() -> None:
    op.drop_table("widget")
'''

SECOND = '''"""second

Revision ID: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("widget", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("widget", "name")
'''


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def two_revisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A history with two revisions, using the real `env.py` rather than a stand-in for it."""
    location = tmp_path / "migrations"
    (location / "versions").mkdir(parents=True)
    shutil.copy(schema.SCRIPT_LOCATION / "env.py", location / "env.py")
    shutil.copy(schema.SCRIPT_LOCATION / "script.py.mako", location / "script.py.mako")
    (location / "versions" / "0001_first.py").write_text(FIRST, encoding="utf-8")
    (location / "versions" / "0002_second.py").write_text(SECOND, encoding="utf-8")
    monkeypatch.setattr(schema, "SCRIPT_LOCATION", location)
    return location


# --------------------------------------------------------------------------------------------
# What this build actually ships today
# --------------------------------------------------------------------------------------------


def test_a_fresh_database_is_brought_to_the_shipped_head(prepared: DataPaths) -> None:
    """What every start looks like, including every test in this suite that builds a server.

    Until T4 this asserted the opposite - that a build with no revisions leaves an unstamped
    database, which was true and had to be a state rather than an error. That test failed the
    moment `0001` landed, which is what it was for: it named the day the assumption expired
    instead of leaving a stale one passing.

    **It has now done that five times**, at `0002`, `0003`, `0004` and `0005`. The literal below is
    deliberate and is not to be
    replaced with a lookup of whatever the head happens to be: a test that reads the head from the
    same place the code does asserts that two functions agree, which they always will. This one
    asserts what this build *ships*, and the only way to change it is to notice.
    """
    engine = create_database_engine(prepared)
    try:
        assert schema.head_revision(schema.alembic_config(prepared)) == "0005"
        schema.ensure_current(engine, prepared)
        assert schema.current_revision(engine) == "0005"
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
    finally:
        engine.dispose()
    assert {"users", "user_library_access", "access_tokens", "sessions"} <= tables
    assert {"libraries", "library_roots", "items", "item_sources", "item_user_data"} <= tables
    assert {
        "item_genres",
        "item_studios",
        "item_people",
        "item_artists",
        "item_images",
        "provider_cache",
    } <= tables


# --------------------------------------------------------------------------------------------
# Create, serve, or refuse
# --------------------------------------------------------------------------------------------


def test_an_empty_database_is_created_and_brought_to_head(
    prepared: DataPaths, two_revisions: Path
) -> None:
    """A first run has no schema, and refusing to make one is a refusal with no decision in it."""
    engine = create_database_engine(prepared)
    try:
        schema.ensure_current(engine, prepared)
        assert schema.current_revision(engine) == "0002"
        with engine.connect() as connection:
            assert "widget" in inspect(connection).get_table_names()
            columns = {column["name"] for column in inspect(connection).get_columns("widget")}
        assert columns == {"id", "name"}
    finally:
        engine.dispose()


def test_a_database_at_head_is_left_alone(prepared: DataPaths, two_revisions: Path) -> None:
    engine = create_database_engine(prepared)
    try:
        schema.ensure_current(engine, prepared)
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO widget (name) VALUES ('kept')"))
        schema.ensure_current(engine, prepared)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM widget")).scalar_one() == 1
    finally:
        engine.dispose()


def test_a_database_behind_the_code_refuses_and_names_the_command(
    prepared: DataPaths, two_revisions: Path
) -> None:
    """The refusal an operator meets after upgrading Atrium without migrating."""
    engine = create_database_engine(prepared)
    try:
        config = schema.alembic_config(prepared)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
        assert schema.current_revision(engine) == "0001"

        with pytest.raises(ConfigurationError) as refusal:
            schema.ensure_current(engine, prepared)
    finally:
        engine.dispose()

    message = str(refusal.value)
    assert "0001" in message and "0002" in message
    assert schema.UPGRADE_COMMAND in message


def test_a_database_with_tables_but_no_stamp_refuses(
    prepared: DataPaths, two_revisions: Path
) -> None:
    """Somebody else's SQLite file in the data directory, or one from before migrations existed."""
    engine = create_database_engine(prepared)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE somebody_elses (id INTEGER PRIMARY KEY)"))
        with pytest.raises(ConfigurationError) as refusal:
            schema.ensure_current(engine, prepared)
    finally:
        engine.dispose()
    assert "somebody_elses" in str(refusal.value)


def test_a_database_from_the_future_refuses_rather_than_migrating_backwards(
    prepared: DataPaths, two_revisions: Path
) -> None:
    """Downgrading the server leaves a database a newer one wrote.

    Treating it as "behind" would run migrations over data this build cannot read. It is the row of
    the table nobody thinks of and everybody eventually reaches.
    """
    engine = create_database_engine(prepared)
    try:
        schema.ensure_current(engine, prepared)
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
        with pytest.raises(ConfigurationError) as refusal:
            schema.ensure_current(engine, prepared)
    finally:
        engine.dispose()
    assert "9999" in str(refusal.value)


# --------------------------------------------------------------------------------------------
# What the operator sees
# --------------------------------------------------------------------------------------------


def test_the_server_refuses_to_start_when_the_database_is_behind(
    prepared: DataPaths, two_revisions: Path
) -> None:
    engine = create_database_engine(prepared)
    try:
        config = schema.alembic_config(prepared)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
    finally:
        engine.dispose()

    with pytest.raises(ConfigurationError):
        create_app(prepared)


def test_the_operator_gets_the_sentence_not_a_traceback(
    prepared: DataPaths, two_revisions: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """plan section 7 promises a refusal that names the command. This is that promise, asserted."""
    engine = create_database_engine(prepared)
    try:
        config = schema.alembic_config(prepared)
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
    finally:
        engine.dispose()

    assert main(["--data-dir", str(prepared.root)]) == 1
    refusal = capsys.readouterr().err
    assert schema.UPGRADE_COMMAND in refusal
    assert "Traceback" not in refusal
