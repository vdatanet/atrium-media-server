# SPDX-License-Identifier: GPL-3.0-or-later
"""What Alembic runs inside, for both ways this project drives it.

Two callers, and they hand over different things:

* **`atrium.db.schema`**, at startup, puts a live `Connection` in `config.attributes`, taken from
  `schema.migration_connection` - which is where the foreign-key pragma is decided.
* **`alembic` on the command line**, which is the command an operator is told to run, hands over
  nothing. Then the data directory is resolved the same way the server resolves it -
  `ATRIUM_DATA_DIR`, or the documented default - so `alembic upgrade head` and the server always
  mean the same file, and the connection comes from the same helper so that the two paths cannot
  migrate under different rules.

**A migration runs with foreign keys off, and that is the measured answer rather than the obvious
one.** With them on, a batch rebuild's `DROP TABLE` cascades every child row away in silence; see
`schema.migration_connection`, which also checks for orphans before it commits.

The database URL is deliberately **not** in `alembic.ini`. A path in an ini file is a path that
disagrees with `$ATRIUM_DATA_DIR` eventually, and configparser reads `%` in a path as
interpolation, so a data directory containing one would fail in a way nobody would guess.
"""

from __future__ import annotations

from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import Connection

from atrium.config.paths import DataPaths, resolve_data_dir
from atrium.db.engine import create_database_engine
from atrium.db.models import Base
from atrium.db.schema import migration_connection

target_metadata = Base.metadata

#: Where this project's own column types live. Anything under here needs an import written into
#: the migration; anything from SQLAlchemy already has one.
OUR_PACKAGE = "atrium."


def render_item(kind: str, obj: Any, autogen_context: AutogenContext) -> str | Literal[False]:
    """Import the project's own column types into the migrations that use them.

    Alembic adds an import for a rendered type **only** when it comes from `sqlalchemy.dialects`
    (`autogenerate/render.py`, `_repr_type`). For anything else it renders the type with its module
    path - `atrium.db.types.UtcDateTime()` - and imports nothing, so the generated migration is a
    `NameError` waiting for the first operator who runs it. Nothing warns, and autogenerate
    reports success.

    `repr` rather than the bare class name, so a type that takes constructor arguments keeps them.
    """
    if kind == "type" and type(obj).__module__.startswith(OUR_PACKAGE):
        module, name = type(obj).__module__, type(obj).__name__
        autogen_context.imports.add(f"from {module} import {name}")
        return repr(obj)
    return False


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
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
        render_item=render_item,
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
        with migration_connection(engine) as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
