# SPDX-License-Identifier: GPL-3.0-or-later
"""The ORM tables.

Empty of tables at T2 on purpose: this module exists so the migration environment has one piece of
metadata to compare a database against, and so T4 adds tables rather than also rewiring Alembic.
`Base.metadata` being empty is what makes T2's "no revisions yet, and the check agrees" a state the
code can be in rather than a special case.

**Nothing here crosses the repository boundary.** A route never sees one of these; `db/` turns them
into domain objects and hands those out (architecture section 1, ADR-0003).

See specs/002-authentication-users-and-sessions/plan.md section 4.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """The declarative base every table in this project inherits.

    One base, so one `metadata` - which is what `alembic revision --autogenerate` compares against
    a live database. A second base would produce migrations that silently omit half the schema.
    """


__all__ = ["Base"]
