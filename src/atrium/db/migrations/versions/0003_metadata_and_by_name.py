# SPDX-License-Identifier: GPL-3.0-or-later
"""metadata and by-name items

Revision ID: 0003
Revises: 0002
Created: 2026-08-27

Feature 004's schema: what a refresh resolves, and the five types that exist because a **name**
does rather than because a file does.

Three things here are not obvious from the column list:

* **`items` is rebuilt, not merely widened.** Two of its check constraints change - the type list
  gains five members, and `library_id` becomes nullable under a new constraint tying that null to
  exactly those five - and SQLite cannot alter a constraint in place. `copy_from` carries the
  table's *whole* 0002 definition into the batch operation, because SQLAlchemy's SQLite dialect
  does **not** reflect check constraints: without it the rebuild would silently drop
  `ck_items_type` and nobody would notice until a row with a nonsense type appeared.
* **The join tables carry no cascade to the by-name row they point at.** Deleting a genre row that
  items still reference is a bug in garbage collection, and a cascade would turn it into a silent
  removal of that genre from every item that had it. Without one it is an integrity error, which
  is the failure this project wants.
* **`provider_cache` promises nothing.** Its rows are what somebody else's server said; dropping
  the table costs a refresh, not data.

**Reversible**, and tests/unit/test_migrations.py applies it and rolls it back.

See specs/004-metadata-resolution/plan.md section 4.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from atrium.db.types import UtcDateTime

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The five types with no library. Written out rather than imported: a migration is a record of
#: what the schema was at a point in time, and importing a constant would let a later edit to that
#: constant rewrite history.
BY_NAME = "'Genre', 'MusicGenre', 'Studio', 'Person', 'Year'"

_TREE_TYPES = (
    "'Movie', 'Series', 'Season', 'Episode', 'MusicArtist', 'MusicAlbum', "
    "'Audio', 'CollectionFolder'"
)


def _items_as_0002_left_it() -> sa.Table:
    """`items` exactly as revision 0002 created it, constraints included.

    Handed to `batch_alter_table` as `copy_from` so the rebuild starts from the truth rather than
    from what SQLite is willing to reflect back.
    """
    return sa.Table(
        "items",
        sa.MetaData(),
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
        sa.CheckConstraint(f"type IN ({_TREE_TYPES})", name="ck_items_type"),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # **0002's two indexes belong in this definition**, not only in 0002. `copy_from`
        # replaces reflection wholesale, so a rebuild that did not name them here would drop
        # both - and an index that quietly stopped existing is a query that quietly got slower,
        # which no test would ever fail on.
        sa.Index("ix_items_library_type_sort", "library_id", "type", "sort_name"),
        sa.Index("ix_items_parent_index", "parent_id", "index_number"),
    )


def upgrade() -> None:
    with op.batch_alter_table(
        "items", copy_from=_items_as_0002_left_it(), recreate="always"
    ) as batch_op:
        batch_op.add_column(sa.Column("overview", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tagline", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("original_title", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("production_year", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("premiere_date", UtcDateTime(), nullable=True))
        batch_op.add_column(sa.Column("runtime_ticks", sa.BigInteger(), nullable=True))
        batch_op.add_column(sa.Column("official_rating", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("community_rating", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("provider_ids", sa.JSON(), server_default=sa.text("'{}'"), nullable=False)
        )
        batch_op.add_column(sa.Column("normalization_gain", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("locked_fields", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
        )
        batch_op.add_column(
            sa.Column("is_locked", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(
            sa.Column("refresh_pending", sa.Boolean(), server_default=sa.text("0"), nullable=False)
        )
        batch_op.add_column(sa.Column("metadata_refreshed_at", UtcDateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("name_folded", sa.String(), server_default="", nullable=False)
        )

        batch_op.alter_column("library_id", existing_type=sa.String(length=32), nullable=True)
        batch_op.drop_constraint("ck_items_type", type_="check")
        batch_op.create_check_constraint("ck_items_type", f"type IN ({_TREE_TYPES}, {BY_NAME})")
        batch_op.create_check_constraint(
            "ck_items_by_name_has_no_library", f"(library_id IS NULL) = (type IN ({BY_NAME}))"
        )

        batch_op.create_index("ix_items_production_year", ["production_year"], unique=False)
        batch_op.create_index("ix_items_premiere_date", ["premiere_date"], unique=False)
        batch_op.create_index("ix_items_community_rating", ["community_rating"], unique=False)
        batch_op.create_index("ix_items_date_created", ["date_created"], unique=False)
        batch_op.create_index("ix_items_name_folded", ["name_folded"], unique=False)
        batch_op.create_index("ix_items_refresh_pending", ["refresh_pending"], unique=False)

    op.create_table(
        "item_genres",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("genre_item_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["genre_item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("item_id", "position"),
    )
    op.create_index("ix_item_genres_genre", "item_genres", ["genre_item_id"], unique=False)

    op.create_table(
        "item_studios",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("studio_item_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["studio_item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("item_id", "position"),
    )
    op.create_index("ix_item_studios_studio", "item_studios", ["studio_item_id"], unique=False)

    op.create_table(
        "item_people",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("person_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("person_item_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("item_id", "sort_order"),
    )
    op.create_index("ix_item_people_person", "item_people", ["person_item_id"], unique=False)

    op.create_table(
        "item_artists",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("credit", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("artist_item_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint("credit IN ('artist', 'album_artist')", name="ck_item_artists_credit"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artist_item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("item_id", "credit", "position"),
    )
    op.create_index("ix_item_artists_artist", "item_artists", ["artist_item_id"], unique=False)

    op.create_table(
        "item_images",
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("image_type", sa.String(), nullable=False),
        sa.Column("image_index", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("tag", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "source_kind IN ('file', 'embedded', 'remote')", name="ck_item_images_source_kind"
        ),
        sa.CheckConstraint(
            "(source_kind = 'embedded') = (relative_path IS NULL)",
            name="ck_item_images_embedded_has_no_path",
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "image_type", "image_index"),
    )

    op.create_table(
        "provider_cache",
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("request_key", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", UtcDateTime(), nullable=False),
        sa.Column("expires_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("provider", "request_key"),
    )


def downgrade() -> None:
    # Children first, as in 0001 and 0002: the pragma that makes foreign keys real is on for this
    # connection too (db/engine.py), and every one of these points at `items`.
    op.drop_table("provider_cache")
    op.drop_table("item_images")
    op.drop_index("ix_item_artists_artist", table_name="item_artists")
    op.drop_table("item_artists")
    op.drop_index("ix_item_people_person", table_name="item_people")
    op.drop_table("item_people")
    op.drop_index("ix_item_studios_studio", table_name="item_studios")
    op.drop_table("item_studios")
    op.drop_index("ix_item_genres_genre", table_name="item_genres")
    op.drop_table("item_genres")

    # **Rows a by-name type owns cannot survive this**, and neither can any item whose library is
    # null - 0002's schema has no such thing, and rolling back into it with those rows present
    # would leave a database that violates its own constraint. Deleting them loses nothing that is
    # not derivable: every by-name row comes back on the next refresh, id and all.
    # S608: BY_NAME is a literal defined at the top of this module. Nothing reaches it.
    op.execute(f"DELETE FROM items WHERE type IN ({BY_NAME}) OR library_id IS NULL")  # noqa: S608

    with op.batch_alter_table(
        "items", copy_from=_items_at_this_revision(), recreate="always"
    ) as batch_op:
        batch_op.drop_index("ix_items_refresh_pending")
        batch_op.drop_index("ix_items_name_folded")
        batch_op.drop_index("ix_items_date_created")
        batch_op.drop_index("ix_items_community_rating")
        batch_op.drop_index("ix_items_premiere_date")
        batch_op.drop_index("ix_items_production_year")

        batch_op.drop_constraint("ck_items_by_name_has_no_library", type_="check")
        batch_op.drop_constraint("ck_items_type", type_="check")
        batch_op.create_check_constraint("ck_items_type", f"type IN ({_TREE_TYPES})")
        batch_op.alter_column("library_id", existing_type=sa.String(length=32), nullable=False)

        for column in (
            "name_folded",
            "metadata_refreshed_at",
            "refresh_pending",
            "is_locked",
            "locked_fields",
            "normalization_gain",
            "provider_ids",
            "community_rating",
            "official_rating",
            "runtime_ticks",
            "premiere_date",
            "production_year",
            "original_title",
            "tagline",
            "overview",
        ):
            batch_op.drop_column(column)


def _items_at_this_revision() -> sa.Table:
    """`items` as `upgrade()` above leaves it. The `copy_from` for the rollback, for the same
    reason the upgrade needs one: the two check constraints would not survive a reflection."""
    table = _items_as_0002_left_it()
    table.constraints = {
        constraint
        for constraint in table.constraints
        if getattr(constraint, "name", None) != "ck_items_type"
    }
    table.append_constraint(
        sa.CheckConstraint(f"type IN ({_TREE_TYPES}, {BY_NAME})", name="ck_items_type")
    )
    table.append_constraint(
        sa.CheckConstraint(
            f"(library_id IS NULL) = (type IN ({BY_NAME}))", name="ck_items_by_name_has_no_library"
        )
    )
    table.c.library_id.nullable = True
    for column in (
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
    ):
        table.append_column(column)
    # After the columns, never before: an index names columns that have to exist first.
    for index in (
        sa.Index("ix_items_production_year", "production_year"),
        sa.Index("ix_items_premiere_date", "premiere_date"),
        sa.Index("ix_items_community_rating", "community_rating"),
        sa.Index("ix_items_date_created", "date_created"),
        sa.Index("ix_items_name_folded", "name_folded"),
        sa.Index("ix_items_refresh_pending", "refresh_pending"),
    ):
        table.append_constraint(index)
    return table
