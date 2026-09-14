# SPDX-License-Identifier: GPL-3.0-or-later
"""a library of any declared type

Revision ID: 0013
Revises: 0012
Created: 2026-09-14

**One column on `libraries`: nullable, and its check widened from three types to eight or none.**
014 answers every `collectionType` a caller sends the way the reference answers it - the five
declared types this server does not scan are stored as themselves, and an omitted type or the
undeclared `photos` as no type at all (014 spec section 3.6.1, plan section 4). Three were all the
schema allowed until now, because 003 scanned three and a fourth was a library nothing could scan;
that is still true of the scan, and a library of such a type is created and stays empty.

SQLite cannot alter a check constraint in place, so `libraries` is rebuilt, with `copy_from`
carrying 0002's definition because SQLAlchemy's SQLite dialect does not reflect check constraints.

**A rebuild of `libraries` is the most destructive rebuild in this directory if foreign keys are
on.** Three tables point at it with `ON DELETE CASCADE` - `library_roots`, `items` and
`media_probes` - and `items` has six more beneath it, so the implicit `DELETE FROM` SQLite performs
before dropping an enforced table would empty every library of every row it has, and nothing
would raise (0008's docstring has the measurement). `db/schema.py`'s `migration_connection`
suspends foreign keys for every run and checks for orphans before committing; **this revision does
not trust that it was called that way.** It refuses to rebuild a populated table with enforcement
on, and runs `PRAGMA foreign_key_check` itself after each rebuild, so a harness that opened its own
connection meets a refusal rather than an empty store.

**Reversible, and the downgrade refuses rather than deletes.** A library of one of the five types,
or of none, cannot be held by 0012's constraint, and unlike 0009's registry rows it is not
derivable: an operator created it. So the downgrade names every such library and changes nothing,
and the operator removes them or stays (plan section 7).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "libraries"
CONSTRAINT = "ck_libraries_collection_type"

#: 0002's three, spelled out rather than imported: a migration records what the schema was, and a
#: constant imported from the domain would let a later edit rewrite that record.
THREE = "'movies', 'tvshows', 'music'"

#: The reference's eight `[spec: CollectionTypeOptions]`.
EIGHT = f"{THREE}, 'musicvideos', 'homevideos', 'boxsets', 'books', 'mixed'"


def _libraries(*, nullable: bool, check: str) -> sa.Table:
    """`libraries` as 0002 created it, with the one column and the one check this revision moves."""
    return sa.Table(
        TABLE,
        sa.MetaData(),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("collection_type", sa.String(), nullable=nullable),
        sa.Column(
            "case_sensitive_identity", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(check, name=CONSTRAINT),
        sa.PrimaryKeyConstraint("id"),
    )


AT_0012 = f"collection_type IN ({THREE})"
AT_0013 = f"collection_type IS NULL OR collection_type IN ({EIGHT})"


def _require_foreign_keys_suspended() -> None:
    connection = op.get_bind()
    enforced = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    populated = connection.exec_driver_sql(f"SELECT COUNT(*) FROM {TABLE}").scalar()  # noqa: S608
    if enforced and populated:
        raise RuntimeError(
            f"revision 0013 rebuilds {TABLE}, and this connection enforces foreign keys: the "
            f"rebuild would silently delete every root, item and inspection of all {populated} "
            f"library(ies) through ON DELETE CASCADE. Run it through the server or `alembic`, "
            f"which suspend foreign keys for a migration (db/schema.py, migration_connection)."
        )


def _require_no_orphans() -> None:
    orphans = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").all()
    if orphans:
        raise RuntimeError(
            f"the rebuild of {TABLE} left rows referring to nothing: "
            f"{[tuple(row) for row in orphans]}. Nothing is committed."
        )


def upgrade() -> None:
    _require_foreign_keys_suspended()
    with op.batch_alter_table(
        TABLE, copy_from=_libraries(nullable=False, check=AT_0012), recreate="always"
    ) as batch_op:
        batch_op.alter_column("collection_type", existing_type=sa.String(), nullable=True)
        batch_op.drop_constraint(CONSTRAINT, type_="check")
        batch_op.create_check_constraint(CONSTRAINT, AT_0013)
    _require_no_orphans()


def downgrade() -> None:
    connection = op.get_bind()
    unheld = connection.execute(
        sa.text(
            f"SELECT id, name, collection_type FROM {TABLE} "  # noqa: S608 - module constants
            f"WHERE collection_type IS NULL OR collection_type NOT IN ({THREE}) ORDER BY name, id"
        )
    ).all()
    if unheld:
        named = ", ".join(
            f"{name!r} ({library_id}, {kind if kind is not None else 'no type'})"
            for library_id, name, kind in unheld
        )
        raise RuntimeError(
            f"cannot roll back below revision 0013: revision 0012 holds only movies, tvshows and "
            f"music libraries, and {len(unheld)} library(ies) here are another type or none - "
            f"{named}. Nothing is changed. Remove those libraries first, or stay on this revision; "
            f"a rollback does not delete a library an operator created."
        )

    _require_foreign_keys_suspended()
    with op.batch_alter_table(
        TABLE, copy_from=_libraries(nullable=True, check=AT_0013), recreate="always"
    ) as batch_op:
        batch_op.drop_constraint(CONSTRAINT, type_="check")
        batch_op.alter_column("collection_type", existing_type=sa.String(), nullable=False)
        batch_op.create_check_constraint(CONSTRAINT, AT_0012)
    _require_no_orphans()
