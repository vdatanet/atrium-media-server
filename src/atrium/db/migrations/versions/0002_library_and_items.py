# SPDX-License-Identifier: GPL-3.0-or-later
"""library and items

Revision ID: 0002
Revises: 0001
Created: 2026-08-27

The whole of feature 003's schema. Five tables, and two of them exist because of an acceptance
criterion rather than because of a noun:

* **libraries** and **library_roots** - what the operator configured. A library may have several
  roots, so they are a child table. `case_sensitive_identity` is frozen at creation
  (003 plan section 6.3): flipping it rewrites every identifier in the library.
* **items** - the single table behind every type. It has **no path column**: an item's files are
  in `item_sources`, because AC-4 requires a two-part film to be *one* `Movie` with two of them and
  a `Series` has no file at all. `end_index_number` is there for the same class of reason: AC-5
  requires `S01E02-E03` to be one episode spanning both numbers, which one `index_number` cannot
  say. Both were corrected in 003 plan section 4 at T3, after the plan had been accepted with a
  single `relative_path` column.
* **item_sources** - the file or files, ordered by `part_index`. `size` and `mtime_ns` live here
  rather than on the item because 003 plan section 6.4's change detection has to notice a change to
  *either* part.
* **item_user_data** - **deliberately carrying no foreign key to `items`**. That absence is the
  whole point of the table: 003 spec section 3.8 says a file that disappears and returns must not
  cost the user their favourites and resume position, and under a cascade the first slow network
  mount would delete a user's history permanently. Keyed on the derived identity, so the
  association comes back the moment the same path is scanned again.

`user_library_access.library_id` still carries **no** foreign key, now that `libraries` exists.
That is permanent rather than pending: a policy round-trips whole (002 spec section 3.7) and a
client may name a library this server has not configured, so a foreign key would turn that policy
write into a failure a client can observe.

**Reversible**, and tests/unit/test_migrations.py applies it and rolls it back.

See specs/003-library-configuration-and-scanning/plan.md section 4.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from atrium.db.types import UtcDateTime

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "libraries",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("collection_type", sa.String(), nullable=False),
        sa.Column(
            "case_sensitive_identity", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.CheckConstraint(
            "collection_type IN ('movies', 'tvshows', 'music')", name="ck_libraries_collection_type"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "item_user_data",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("item_key", sa.String(length=32), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("played", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("play_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "playback_position_ticks", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_played_date", UtcDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "item_key"),
    )
    op.create_table(
        "items",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("library_id", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint(
            "type IN ('Movie', 'Series', 'Season', 'Episode', 'MusicArtist', 'MusicAlbum', "
            "'Audio', 'CollectionFolder')",
            name="ck_items_type",
        ),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.create_index(
            "ix_items_library_type_sort", ["library_id", "type", "sort_name"], unique=False
        )
        batch_op.create_index("ix_items_parent_index", ["parent_id", "index_number"], unique=False)

    op.create_table(
        "library_roots",
        sa.Column("library_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("library_id", "path"),
    )
    op.create_table(
        "item_sources",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "part_index"),
    )


def downgrade() -> None:
    # Children first, as in 0001: every one of these carries a foreign key, and the pragma that
    # makes foreign keys real is on for this connection too (db/engine.py).
    op.drop_table("item_sources")
    op.drop_table("library_roots")
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_index("ix_items_parent_index")
        batch_op.drop_index("ix_items_library_type_sort")

    op.drop_table("items")
    op.drop_table("item_user_data")
    op.drop_table("libraries")
