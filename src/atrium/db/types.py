# SPDX-License-Identifier: GPL-3.0-or-later
"""Column types that keep a promise SQLite does not make.

`compat/dates.py` says naive datetimes have no place in this project, and `utc_now()` returns an
aware one. SQLite has no datetime type at all - values are stored as text - and SQLAlchemy's
default storage format for the dialect **has no offset in it**. Measured before this module was
written:

    stored 2026-08-26 23:30:00+02:00  ->  '2026-08-26 23:30:00.000000'  ->  read back naive 23:30

The offset is not converted and not kept. It is dropped, and the wall-clock reading survives, so a
timestamp written on a machine at `+02:00` comes back two hours in the future and nothing anywhere
raises. `DateTime(timezone=True)` changes none of that on this dialect.

Feature 007 attaches resume positions to these timestamps and 002 expires sessions by them, so the
error would be a real one and would only appear on installations outside UTC - which is most of
them, and not the one this was written on.

`UtcDateTime` converts on the way in and restores on the way out, and **refuses a naive value**
rather than guessing which zone somebody meant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator[datetime]):
    """Aware UTC in, aware UTC out. A naive value is a bug, and it is raised as one."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "a naive datetime reached the database. Every timestamp in this project is "
                "timezone-aware (compat/dates.py); storing this one would silently record the "
                "wall clock of whichever machine produced it."
            )
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        stored: datetime = value
        return stored.replace(tzinfo=UTC)


__all__ = ["UtcDateTime"]
