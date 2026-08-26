# SPDX-License-Identifier: GPL-3.0-or-later
"""One SQLite file, and the two pragmas that are not optional.

**WAL is required, not preferred** (ADR-0003): without it a library scan's writes block every
read, and the server appears to hang for as long as the scan runs. **Foreign keys are off by
default in SQLite** and are per connection, so a pragma applied once at startup protects nothing -
every connection the pool opens has to be told again. Both are set in the `connect` event for
exactly that reason.

The engine is **synchronous**. ADR-0002 rejected the async ORM: SQLite is a local file with a
global write lock, so async buys nothing and costs a harder debugging story. Database work runs in
a thread pool, which is what FastAPI already does for a `def` route.

Three things were measured rather than assumed before this module was written, because each has a
plausible wrong answer:

* `PRAGMA journal_mode=WAL` inside the `connect` event **takes**, and reports `wal` back. It is
  refused inside a transaction, and a `connect` handler is the one place there is certainly not one.
* `PRAGMA foreign_keys=ON` applied there **is enforced** on that connection.
* the default pool for a file database is `QueuePool`, and it hands connections between threads
  without a `ProgrammingError` - SQLAlchemy already passes `check_same_thread=False` for this
  dialect. Adding it here would be a spell rather than a decision.

See specs/002-authentication-users-and-sessions/plan.md section 3.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import sqlalchemy
from sqlalchemy import Engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from atrium.config.paths import ConfigurationError, DataPaths

logger = logging.getLogger(__name__)

#: Applied to every connection the pool opens, in this order. `journal_mode` is a property of the
#: file and survives a restart; setting it per connection costs one statement and means a database
#: restored from a copy made in another mode is put right rather than silently served slowly.
PRAGMAS = ("journal_mode=WAL", "foreign_keys=ON")


def create_database_engine(paths: DataPaths, *, echo: bool = False) -> Engine:
    """An engine for this instance's database file, with the pragmas attached.

    The listener is bound to **this** engine rather than to the `Engine` class, so two instances in
    one process - which the test suite relies on - do not configure each other's connections.
    """
    engine = sqlalchemy.create_engine(f"sqlite+pysqlite:///{paths.database}", echo=echo)

    @event.listens_for(engine, "connect")
    def _apply_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for pragma in PRAGMAS:
                cursor.execute(f"PRAGMA {pragma}")
        finally:
            cursor.close()

    return engine


def verify_connection(engine: Engine, paths: DataPaths) -> None:
    """Open one connection now, or refuse to start.

    Discovering that the database is unreachable on the first request means answering a client with
    a `500` for something the operator could have been told about at startup - and plan section 7
    says refuse, for the same reason the configuration loader does.
    """
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except SQLAlchemyError as exc:
        raise ConfigurationError(
            f"cannot open the database at {paths.database}: {exc}. Atrium will not start without "
            f"it: every route after feature 001 needs to know who is asking."
        ) from exc


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """The factory the repositories bind to.

    `expire_on_commit=False` because the repository boundary converts rows into domain objects
    before its session ends. With expiry on, reading a value that was already read costs a second
    query, and the object it would refresh is one nothing above `db/` is allowed to hold anyway.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A unit of work: commit on success, roll back on anything else, always close.

    Written here rather than at each call site because "roll back on failure" is the half that gets
    forgotten, and a session returned to the pool mid-transaction takes its lock with it.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = [
    "PRAGMAS",
    "create_database_engine",
    "session_factory",
    "session_scope",
    "verify_connection",
]
