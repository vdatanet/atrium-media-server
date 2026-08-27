# SPDX-License-Identifier: GPL-3.0-or-later
"""an artist credit may name somebody who is not an item

Revision ID: 0004
Revises: 0003
Created: 2026-08-27

One column, from `NOT NULL` to nullable, and the reason is a consequence of an accepted gap that
nobody had followed all the way down.

`item_genres`, `item_studios` and `item_people` point at **by-name rows**, which a refresh creates
on demand - so those links can never dangle and stay `NOT NULL`. `item_artists` points at a
`MusicArtist`, which in Atrium is a **tree item the scanner owns** rather than a by-name row
(docs/compatibility/behaviours.md section 5.3). The scanner creates one per *album artist*. A
track's *performers* are frequently different people, and 004's tag reader records all of them -
so `item_artists` routinely names an artist with no item behind it, and the foreign key made
writing that row impossible.

Three ways out were available and two are worse:

* **Have the refresh create the missing `MusicArtist`.** It would be a tree item created outside
  the scan that builds the tree, and the next scan - which reconciles what it resolved against
  what exists - would mark it removed. A row that appears and disappears every other scan.
* **Drop the credit rows whose artist has no item.** That loses the track artists themselves, and
  "a track with three artists yields three artists" is AC-6.
* **Store the name, and the link when there is one.** The name is what a client renders; the link
  is what makes it clickable. A performer who is nobody's album artist gets the first and not the
  second, which is exactly the state of affairs.

**Reversible**: rolling back nulls no rows out, so the downgrade first deletes the credit rows
that have no link - they are derivable from the files on the next refresh, like every other
association in this feature.

See specs/004-metadata-resolution/plan.md section 4 and 004 T9.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _item_artists() -> sa.Table:
    """`item_artists` as revision 0003 created it, constraints and index included.

    `copy_from` again, for the same reason as 0003: SQLAlchemy's SQLite dialect does not reflect
    check constraints, so a rebuild that trusted reflection would drop `ck_item_artists_credit` -
    and `/Artists` versus `/Artists/AlbumArtists` is that constraint's column.
    """
    return sa.Table(
        "item_artists",
        sa.MetaData(),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("credit", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("artist_item_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint("credit IN ('artist', 'album_artist')", name="ck_item_artists_credit"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artist_item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("item_id", "credit", "position"),
        sa.Index("ix_item_artists_artist", "artist_item_id"),
    )


def upgrade() -> None:
    with op.batch_alter_table(
        "item_artists", copy_from=_item_artists(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("artist_item_id", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    # A credit with no link cannot exist under 0003's constraint. Deleting those rows loses
    # nothing that is not derivable: the next refresh reads the same tags and writes them again.
    op.execute("DELETE FROM item_artists WHERE artist_item_id IS NULL")

    nullable = _item_artists()
    nullable.c.artist_item_id.nullable = True
    with op.batch_alter_table("item_artists", copy_from=nullable, recreate="always") as batch_op:
        batch_op.alter_column("artist_item_id", existing_type=sa.String(length=32), nullable=False)
