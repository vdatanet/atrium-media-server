# SPDX-License-Identifier: GPL-3.0-or-later
"""a MusicArtist may have no library

Revision ID: 0009
Revises: 0008
Created: 2026-09-07

**The capacity, and not the population.** 013 gives `/Artists` a registry of by-name artist rows,
one per credited name; this revision is the one thing the schema has to say before any of them can
exist, and it says nothing else. The rows themselves, the credit links that name them and the
column that stops being nullable are 013 T2's, in a revision of their own - because a schema that
*allows* a row and a database that *has* one are two changes, each reversible on its own.

**`ck_items_by_name_has_no_library` was a biconditional and is two implications.** It said
`(library_id IS NULL) = (type IN (…))`, which `MusicArtist` breaks in *both* directions at once:
it stays the tree item an album hangs off, keyed per library by the scan, **and** it gains a
registry row keyed on the folded name with no library at all. The two halves it stood for are now
written apart - a strictly by-name type has no library, a tree type has one - with `MusicArtist`
exempted from the second by name and nothing else exempted from either.

Written as two constraints on purpose: a single expression carrying an exemption is one a later
reader folds back into a biconditional.

**The pair is the reference's**, which is why this is a capacity worth having rather than a
loosening: an artist there can be a tree item and a registry row under two identifiers - `AC/DC`
in a library against `AC DC` in its metadata directory
`[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]`.

**Reversible.** The downgrade restores the biconditional, and deletes the registry rows first
because the restored constraint would refuse them. There are none to delete until T2 writes them,
and the statement is here anyway: a rollback of a loosened constraint has to leave a database the
tightened one can hold, and writing that later means writing it after somebody needed it.

**A constraint migration**, which is the word `tests/unit/test_migrations.py` needs: it reads the
schema through SQLAlchemy's SQLite dialect, which does not reflect check constraints at all - the
same fact every `copy_from` in this directory exists for - so a revision whose whole content is a
constraint looks to that sweep like a revision that did nothing.

See specs/013-artist-registry/plan.md section 4 and 013 T1.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from atrium.db.types import UtcDateTime

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The types with no library at 0008: 0003's five by-name ones, plus 009's playlist.
_NO_LIBRARY_AT_0008 = "'Genre', 'MusicGenre', 'Studio', 'Person', 'Year', 'Playlist'"

#: 0008's fourteen, spelled out for the reason 0003 gives - a migration records what the schema was
#: at a point in time, and importing the live constant would let a later edit rewrite history.
_TYPES_AT_0008 = (
    "'Movie', 'Series', 'Season', 'Episode', 'MusicArtist', 'MusicAlbum', "
    "'Audio', 'CollectionFolder', 'Genre', 'MusicGenre', 'Studio', 'Person', 'Year', 'Playlist'"
)

#: The one type exempt from *"a tree item has a library"*, and the only one there is.
_ALSO_WITHOUT_A_LIBRARY = "'MusicArtist'"


def _items_at_0008() -> sa.Table:
    """`items` as 0008 left it. `copy_from` again, for 0003's reason: SQLAlchemy's SQLite dialect
    does not reflect check constraints, so a rebuild trusting reflection would silently drop them.
    """
    return sa.Table(
        "items",
        sa.MetaData(),
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("library_id", sa.String(length=32), nullable=True),
        sa.Column("parent_id", sa.String(length=32), nullable=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_name", sa.String(), server_default="", nullable=False),
        sa.Column("index_number", sa.Integer(), nullable=True),
        sa.Column("parent_index_number", sa.Integer(), nullable=True),
        sa.Column("end_index_number", sa.Integer(), nullable=True),
        sa.Column("date_created", UtcDateTime(), nullable=True),
        sa.Column("date_modified", UtcDateTime(), nullable=True),
        sa.Column("removed_at", UtcDateTime(), nullable=True),
        sa.Column("overview", sa.String(), nullable=True),
        sa.Column("tagline", sa.String(), nullable=True),
        sa.Column("original_title", sa.String(), nullable=True),
        sa.Column("production_year", sa.Integer(), nullable=True),
        sa.Column("premiere_date", UtcDateTime(), nullable=True),
        sa.Column("runtime_ticks", sa.BigInteger(), nullable=True),
        sa.Column("official_rating", sa.String(), nullable=True),
        sa.Column("community_rating", sa.Float(), nullable=True),
        sa.Column("provider_ids", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("normalization_gain", sa.Float(), nullable=True),
        sa.Column("locked_fields", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("is_locked", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("refresh_pending", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("metadata_refreshed_at", UtcDateTime(), nullable=True),
        sa.Column("name_folded", sa.String(), server_default="", nullable=False),
        sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("forced_sort_name", sa.String(), nullable=True),
        sa.CheckConstraint(f"type IN ({_TYPES_AT_0008})", name="ck_items_type"),
        sa.CheckConstraint(
            f"(library_id IS NULL) = (type IN ({_NO_LIBRARY_AT_0008}))",
            name="ck_items_by_name_has_no_library",
        ),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_items_library_type_sort", "library_id", "type", "sort_name"),
        sa.Index("ix_items_parent_index", "parent_id", "index_number"),
        sa.Index("ix_items_production_year", "production_year"),
        sa.Index("ix_items_premiere_date", "premiere_date"),
        sa.Index("ix_items_community_rating", "community_rating"),
        sa.Index("ix_items_date_created", "date_created"),
        sa.Index("ix_items_name_folded", "name_folded"),
        sa.Index("ix_items_refresh_pending", "refresh_pending"),
    )


def _items_at_0009() -> sa.Table:
    """`items` as `upgrade()` leaves it: the `copy_from` the rollback needs."""
    table = _items_at_0008()
    table.constraints = {
        constraint
        for constraint in table.constraints
        if getattr(constraint, "name", None) != "ck_items_by_name_has_no_library"
    }
    table.append_constraint(
        sa.CheckConstraint(
            f"type NOT IN ({_NO_LIBRARY_AT_0008}) OR library_id IS NULL",
            name="ck_items_by_name_has_no_library",
        )
    )
    table.append_constraint(
        sa.CheckConstraint(
            f"type IN ({_NO_LIBRARY_AT_0008}, {_ALSO_WITHOUT_A_LIBRARY}) OR library_id IS NOT NULL",
            name="ck_items_in_a_tree_have_a_library",
        )
    )
    return table


def upgrade() -> None:
    with op.batch_alter_table("items", copy_from=_items_at_0008(), recreate="always") as batch_op:
        batch_op.drop_constraint("ck_items_by_name_has_no_library", type_="check")
        batch_op.create_check_constraint(
            "ck_items_by_name_has_no_library",
            f"type NOT IN ({_NO_LIBRARY_AT_0008}) OR library_id IS NULL",
        )
        batch_op.create_check_constraint(
            "ck_items_in_a_tree_have_a_library",
            f"type IN ({_NO_LIBRARY_AT_0008}, {_ALSO_WITHOUT_A_LIBRARY}) OR library_id IS NOT NULL",
        )


def downgrade() -> None:
    # The registry rows the biconditional would refuse are deleted before it comes back. There
    # are none while 013 T2 is unwritten, and this is not a guess about the future: it is what a
    # rollback of a **loosened** constraint has to do to leave a database the tightened one can
    # hold, and writing it later would mean writing it after somebody needed it.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE item_artists SET artist_item_id = NULL WHERE artist_item_id IN "
            "(SELECT id FROM items WHERE type = 'MusicArtist' AND library_id IS NULL)"
        )
    )
    connection.execute(
        sa.text("DELETE FROM items WHERE type = 'MusicArtist' AND library_id IS NULL")
    )

    with op.batch_alter_table("items", copy_from=_items_at_0009(), recreate="always") as batch_op:
        batch_op.drop_constraint("ck_items_in_a_tree_have_a_library", type_="check")
        batch_op.drop_constraint("ck_items_by_name_has_no_library", type_="check")
        batch_op.create_check_constraint(
            "ck_items_by_name_has_no_library",
            f"(library_id IS NULL) = (type IN ({_NO_LIBRARY_AT_0008}))",
        )
