# SPDX-License-Identifier: GPL-3.0-or-later
"""What Alembic runs inside, for both ways this project drives it.

Two callers, and they hand over different things:

* **`atrium.db.schema`**, at startup, puts a live `Connection` in `config.attributes`. It already
  has an engine with the pragmas attached, and opening a second one would migrate a database with
  foreign keys off.
* **`alembic` on the command line**, during development, hands over nothing. Then the data
  directory is resolved the same way the server resolves it - `ATRIUM_DATA_DIR`, or the documented
  default - so `alembic upgrade head` and the server always mean the same file.

The database URL is deliberately **not** in `alembic.ini`. A path in an ini file is a path that
disagrees with `$ATRIUM_DATA_DIR` eventually, and configparser reads `%` in a path as
interpolation, so a data directory containing one would fail in a way nobody would guess.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection

from atrium.config.paths import DataPaths, resolve_data_dir
from atrium.db.engine import create_database_engine
from atrium.db.models import Base

target_metadata = Base.metadata


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot ALTER most things in place. Batch mode rewrites the table instead, which
        # is the only way a column ever gets dropped or a constraint changed on this backend.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """`--sql` mode: emit the statements without a database to run them against."""
    paths = DataPaths(resolve_data_dir())
    context.configure(
        url=f"sqlite+pysqlite:///{paths.database}",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    existing = context.config.attributes.get("connection")
    if existing is not None:
        _run(existing)
        return

    engine = create_database_engine(DataPaths(resolve_data_dir()))
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
