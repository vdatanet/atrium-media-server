# SPDX-License-Identifier: GPL-3.0-or-later
"""playlists

Revision ID: 0008
Revises: 0007
Created: 2026-08-31

Feature 009's schema: the one type in this store that no scan produces and no rescan can rebuild.

Three tables are the easy half. The hard half is that `items` was written to **forbid** a
playlist, twice - `ck_items_type` lists thirteen values and `ck_items_by_name_has_no_library` ties
a null library to exactly the five by-name types - and SQLite cannot alter a check constraint in
place. So `items` is rebuilt, the way 0003 and 0004 rebuild theirs, with `copy_from` carrying the
whole 0007 definition in because SQLAlchemy's SQLite dialect does not reflect check constraints.

**A rebuild of a populated `items` deletes rows out of other tables, and it does it silently.**
This was measured before this revision was written, not reasoned about. Batch mode rebuilds a
table by creating a copy, filling it, `DROP TABLE`-ing the original and renaming - and with
`PRAGMA foreign_keys=ON`, which `db/engine.py` sets on every connection, SQLite performs an
implicit `DELETE FROM` before dropping. That fires `ON DELETE CASCADE` on all six tables that
point at `items.id`, so `item_sources`, `item_genres`, `item_studios`, `item_people`,
`item_artists` and `item_images` come out **empty**. Nothing raises, and `PRAGMA foreign_key_check`
afterwards is clean: the rows are simply gone. `db/schema.py`'s `migration_connection` is the
answer - it runs every migration with the pragma off and checks for orphans before committing -
and `tests/unit/test_migrations.py` asserts the loss with the guard removed, because a guard that
cannot fail is decoration.

**Reversible.** The downgrade drops the three tables and narrows both constraints back, after
deleting the playlist rows - a `Playlist` cannot exist under 0007's `ck_items_type`, and there is
no older shape to put those rows into. That is data loss on a rollback and it is the only honest
option: rolling back to a schema with no playlists in it means having no playlists.

See specs/009-playlists/plan.md section 4.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from atrium.db.types import UtcDateTime

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The five types with no library, as 0003 wrote them. Spelled out rather than imported, for the
#: reason 0003 gives: a migration is a record of what the schema was at a point in time, and
#: importing a constant would let a later edit to that constant rewrite history.
BY_NAME = "'Genre', 'MusicGenre', 'Studio', 'Person', 'Year'"

#: 0003's thirteen.
_TYPES_AT_0007 = (
    "'Movie', 'Series', 'Season', 'Episode', 'MusicArtist', 'MusicAlbum', "
    "'Audio', 'CollectionFolder', 'Genre', 'MusicGenre', 'Studio', 'Person', 'Year'"
)

#: The fourteenth. A user creates it; nothing on disk describes it (009 spec section 4).
PLAYLIST = "'Playlist'"

#: **The null-library set gains the playlist rather than the playlist gaining a library.** A
#: playlist belongs to a user, not to a library, and a library would put it under that library's
#: tree - which would make `_library_permitted` the predicate that decides who sees it, where 009
#: needs ownership to decide (plan section 4.1).
_NO_LIBRARY_AT_0008 = f"{BY_NAME}, {PLAYLIST}"


def _items_at_0007() -> sa.Table:
    """`items` exactly as revisions 0002, 0003 and 0005 left it, constraints and indexes included.

    Handed to `batch_alter_table` as `copy_from` so the rebuild starts from the truth rather than
    from what SQLite is willing to reflect back: check constraints are not reflected at all, and
    an index this definition failed to name would be an index that silently stopped existing.
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
        sa.CheckConstraint(f"type IN ({_TYPES_AT_0007})", name="ck_items_type"),
        sa.CheckConstraint(
            f"(library_id IS NULL) = (type IN ({BY_NAME}))",
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


def _items_at_0008() -> sa.Table:
    """`items` as `upgrade()` leaves it: the `copy_from` for the rollback, for the same reason the
    upgrade needs one."""
    table = _items_at_0007()
    table.constraints = {
        constraint
        for constraint in table.constraints
        if getattr(constraint, "name", None)
        not in {"ck_items_type", "ck_items_by_name_has_no_library"}
    }
    table.append_constraint(
        sa.CheckConstraint(f"type IN ({_TYPES_AT_0007}, {PLAYLIST})", name="ck_items_type")
    )
    table.append_constraint(
        sa.CheckConstraint(
            f"(library_id IS NULL) = (type IN ({_NO_LIBRARY_AT_0008}))",
            name="ck_items_by_name_has_no_library",
        )
    )
    return table


def upgrade() -> None:
    with op.batch_alter_table("items", copy_from=_items_at_0007(), recreate="always") as batch_op:
        batch_op.drop_constraint("ck_items_by_name_has_no_library", type_="check")
        batch_op.drop_constraint("ck_items_type", type_="check")
        batch_op.create_check_constraint("ck_items_type", f"type IN ({_TYPES_AT_0007}, {PLAYLIST})")
        batch_op.create_check_constraint(
            "ck_items_by_name_has_no_library",
            f"(library_id IS NULL) = (type IN ({_NO_LIBRARY_AT_0008}))",
        )

    op.create_table(
        "playlists",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("is_public", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        # Stored rather than derived: the reference fixes the value at creation and never revises
        # it `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`.
        sa.Column("media_type", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id"),
    )

    op.create_table(
        "playlist_entries",
        sa.Column("playlist_id", sa.String(length=32), nullable=False),
        # **No foreign key**, and the argument is 007's `item_user_data`: a file that disappears
        # and comes back must not cost the user anything, and a cascade would empty their
        # playlists on the first slow mount. An entry whose item is gone is dropped at read time.
        sa.Column("item_key", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["playlist_id"], ["playlists.item_id"], ondelete="CASCADE"),
        # The key **is** the de-duplication (009 plan section 4.3): `PlaylistItemId` is the item's
        # own id, so there is no entry identifier to store and adding a duplicate adds nothing.
        sa.PrimaryKeyConstraint("playlist_id", "item_key"),
    )
    # Not unique: a move rewrites a contiguous range in one statement, and a unique index would
    # force that into a two-phase dance around a constraint no read depends on.
    op.create_index("ix_playlist_entries_order", "playlist_entries", ["playlist_id", "ordinal"])

    op.create_table(
        "playlist_shares",
        sa.Column("playlist_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("can_edit", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["playlist_id"], ["playlists.item_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("playlist_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("playlist_shares")
    op.drop_index("ix_playlist_entries_order", table_name="playlist_entries")
    op.drop_table("playlist_entries")
    op.drop_table("playlists")

    # A `Playlist` row cannot exist under 0007's `ck_items_type`, and there is no older shape to
    # keep it in. Deleting is the only way back, and unlike every other association this project
    # rolls back, it is **not** derivable from anything: a playlist is the one thing a rescan
    # cannot rebuild. The docstring says so; this is what "rolling back to a schema with no
    # playlists" means.
    op.execute("DELETE FROM items WHERE type = 'Playlist'")

    with op.batch_alter_table("items", copy_from=_items_at_0008(), recreate="always") as batch_op:
        batch_op.drop_constraint("ck_items_by_name_has_no_library", type_="check")
        batch_op.drop_constraint("ck_items_type", type_="check")
        batch_op.create_check_constraint("ck_items_type", f"type IN ({_TYPES_AT_0007})")
        batch_op.create_check_constraint(
            "ck_items_by_name_has_no_library", f"(library_id IS NULL) = (type IN ({BY_NAME}))"
        )
