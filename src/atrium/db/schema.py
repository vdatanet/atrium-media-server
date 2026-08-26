# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether this database is the one this build expects, and what happens when it is not.

**Refusing beats warning.** Serving requests against a schema the code does not expect does not
produce an error, it produces wrong data - and the wrongness is discovered much later, by which
time the writes are done. So a database that is behind the code stops the server before it answers
anything, and says which command to run (plan section 7).

There is one case where refusing would be wrong, and the plan did not distinguish it: **an empty
database.** A first run has no schema, and answering "run a migration first" to somebody who has
just installed the server is a refusal without a decision behind it - creating a schema where there
was none cannot lose anything, because there is nothing to lose. So:

| The database | What happens |
|---|---|
| Stamped at the revision this build knows | serve |
| Empty - no tables at all | create it, bring it to head, serve |
| Has tables but no revision stamp | **refuse**: it is not ours, or it predates migrations |
| Stamped behind this build | **refuse**, naming the command |
| Stamped at a revision this build has never heard of | **refuse**: a newer Atrium wrote it |

The last row is the one nobody thinks of and everybody eventually hits: downgrading the server
after an upgrade leaves a database from the future, and treating that as "behind" would run a
migration backwards over data the older code cannot read.

See specs/002-authentication-users-and-sessions/plan.md section 4 and section 7.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import SQLAlchemyError

from atrium.config.paths import ConfigurationError, DataPaths

logger = logging.getLogger(__name__)

#: Resolved from this file rather than from `alembic.ini`, whose `script_location` is relative to
#: whatever directory somebody happened to run the command from. An installed server has no
#: working directory worth trusting.
SCRIPT_LOCATION = Path(__file__).resolve().parent / "migrations"

#: What an operator is told to run. Named in one place so the message and the documentation cannot
#: drift apart.
UPGRADE_COMMAND = "uv run alembic upgrade head"

#: Alembic's own bookkeeping table. Present without any of ours means a stamped but empty schema,
#: which is a state `alembic stamp` produces and is not the same as a database with no tables.
VERSION_TABLE = "alembic_version"


def alembic_config(paths: DataPaths) -> Config:
    """A configuration pointing at this build's migrations, with no URL in it.

    The `%` doubling is not superstition: `Config` stores options in a `configparser`, which reads
    `%` as interpolation and raises on the way back out. A data directory called `50% full` is
    unusual and legal, and the failure it would cause names neither the path nor the reason.
    """
    config = Config()
    config.set_main_option("script_location", str(SCRIPT_LOCATION).replace("%", "%%"))
    config.attributes["paths"] = paths
    return config


def head_revision(config: Config) -> str | None:
    """The newest revision this build carries, or None when it carries none."""
    try:
        return ScriptDirectory.from_config(config).get_current_head()
    except CommandError as exc:
        # Two heads mean two migrations claim the same parent - a merge that was never made. It is
        # a mistake in this repository, not in the operator's installation, so say so.
        raise ConfigurationError(
            f"the migration history in {SCRIPT_LOCATION} has more than one head: {exc}. "
            f"That is a bug in this build, not in your database."
        ) from exc


def current_revision(engine: Engine) -> str | None:
    """What the database says it is stamped at, or None when it is unstamped."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _table_names(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return [name for name in inspect(connection).get_table_names() if name != VERSION_TABLE]


def upgrade_to_head(engine: Engine, paths: DataPaths) -> None:
    """Bring the database to head over the engine that already has the pragmas attached.

    Alembic would happily open its own connection from a URL. It would open one **without** the
    foreign-key pragma, and a migration that rewrites a table in batch mode with foreign keys off
    is exactly the migration that leaves an orphan behind.
    """
    config = alembic_config(paths)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def ensure_current(engine: Engine, paths: DataPaths) -> None:
    """Serve, create, or refuse - the table in this module's docstring, in order."""
    config = alembic_config(paths)
    head = head_revision(config)

    try:
        current = current_revision(engine)
        tables = _table_names(engine)
    except SQLAlchemyError as exc:
        raise ConfigurationError(
            f"cannot read the schema of {paths.database}: {exc}. A database Atrium cannot inspect "
            f"is one it must not write to."
        ) from exc

    if current == head:
        return

    if current is None:
        if tables:
            raise ConfigurationError(
                f"{paths.database} holds tables {sorted(tables)} but no migration stamp, so "
                f"Atrium cannot tell what shape they are. Point ATRIUM_DATA_DIR at an empty "
                f"directory, or move that file aside."
            )
        logger.info("creating the database at %s", paths.database)
        upgrade_to_head(engine, paths)
        return

    script = ScriptDirectory.from_config(config)
    try:
        script.get_revision(current)
    except CommandError as exc:
        raise ConfigurationError(
            f"{paths.database} is stamped at revision {current}, which this build of Atrium has "
            f"never heard of - it was almost certainly written by a newer one. Install that "
            f"version again, or start from an empty data directory. ({exc})"
        ) from exc

    raise ConfigurationError(
        f"{paths.database} is at revision {current} and this build of Atrium expects {head}. "
        f"Run `{UPGRADE_COMMAND}` and start again. Atrium will not serve against a schema it does "
        f"not expect: that produces wrong data rather than an error, and the wrongness is found "
        f"long after the writes are."
    )


__all__ = [
    "SCRIPT_LOCATION",
    "UPGRADE_COMMAND",
    "VERSION_TABLE",
    "alembic_config",
    "current_revision",
    "ensure_current",
    "head_revision",
    "upgrade_to_head",
]
