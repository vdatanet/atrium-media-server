# SPDX-License-Identifier: GPL-3.0-or-later
"""every artist credit names a by-name row

Revision ID: 0010
Revises: 0009
Created: 2026-09-07

**The population, where `0009` was the capacity.** That revision made a `MusicArtist` with no
library legal; this one creates them - one per distinct credited artist name - points every credit
at the one for its own name, and makes the column that names it `NOT NULL` again.

**`item_artists.artist_item_id` stops being nullable, and this is revision `0004` undone by the
thing `0004` was waiting for.** That column went nullable because an artist was only ever the tree
item the scanner owned, created one per *album artist*, so a track's performers - frequently other
people - had a name here and no item behind them. Every credited name has a row now, so the name is
still what a client renders and the link is always what makes it clickable.

**Every link is repointed, not only the null ones**, and that is the half a reader would not expect.
The column names the *registry* row from here on. A link that pointed at a **tree** artist was
pointing at the right artist and the wrong population, and leaving it would make `/Artists` list a
mixture of the two - which is the shape 013 exists to end. The tree artists themselves are
untouched: they keep the identifiers 003 derived, they stay the items albums hang off, and they are
different rows from the registry ones wherever both exist - which is the pair the reference carries
too `[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]`.

**One index**, on `item_artists (credit, artist_item_id)`: the two artist routes are two
populations over this table, one per credit kind, and each groups by exactly that pair.

**Reversible, and lossy in a way that repairs itself.** The downgrade nulls the links, deletes the
registry rows and puts the column back. What is lost is which spelling of a name was seen first,
and the next scan derives all of it again from the same tags. Nothing here is authored.

**It imports the derivation rather than repeating it**, which is where this file departs from the
rule `0003` states about importing constants. A by-name identifier is *derived*: a second fold
written here is how the backfill and the next scan would come to disagree about which spelling
merges into which row, which is 004 T4's finding. The identifier is the fact, and there is one
function for it.

See specs/013-artist-registry/plan.md section 4 and 013 T2.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from atrium.domain.items import Item, ItemType
from atrium.domain.sorting import sort_name
from atrium.library.identity import for_by_name
from atrium.metadata.byname import fold_for_search

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _item_artists_at_0009() -> sa.Table:
    """`item_artists` as `0004` left it, nullable link and all.

    `copy_from` again, for `0003`'s reason: SQLAlchemy's SQLite dialect does not reflect check
    constraints, so a rebuild trusting reflection would silently drop `ck_item_artists_credit` -
    and `/Artists` against `/Artists/AlbumArtists` is that constraint's column.
    """
    return sa.Table(
        "item_artists",
        sa.MetaData(),
        sa.Column("item_id", sa.String(length=32), nullable=False),
        sa.Column("credit", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("artist_item_id", sa.String(length=32), nullable=True),
        sa.CheckConstraint("credit IN ('artist', 'album_artist')", name="ck_item_artists_credit"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artist_item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("item_id", "credit", "position"),
        sa.Index("ix_item_artists_artist", "artist_item_id"),
    )


def _item_artists_at_0010() -> sa.Table:
    table = _item_artists_at_0009()
    table.c.artist_item_id.nullable = False
    table.append_constraint(sa.Index("ix_item_artists_credit_artist", "credit", "artist_item_id"))
    return table


def _registry_row(name: str) -> dict[str, object]:
    """One registry artist, derived exactly the way the writer derives it.

    `sort_name` and `name_folded` come from the same two functions the by-name writer calls, so a
    row this backfill makes and a row the next scan would make are the same row in every column
    rather than only in its identifier.
    """
    display = name.strip() or name
    item_id = for_by_name(ItemType.MUSIC_ARTIST, name)
    return {
        "id": item_id,
        "name": display,
        "sort_name": sort_name(
            Item(id=item_id, type=ItemType.MUSIC_ARTIST, name=display, library_id=None)
        ),
        "name_folded": fold_for_search(display),
    }


def upgrade() -> None:
    connection = op.get_bind()
    names = [
        str(row[0]) for row in connection.execute(sa.text("SELECT DISTINCT name FROM item_artists"))
    ]
    for name in names:
        row = _registry_row(name)
        # Two spellings fold to one identifier, so the row may already be here. A **tree** artist
        # cannot carry this identifier: the library is part of that derivation's key.
        existing = connection.execute(
            sa.text("SELECT 1 FROM items WHERE id = :id"), {"id": row["id"]}
        ).first()
        if existing is None:
            connection.execute(
                sa.text(
                    "INSERT INTO items (id, library_id, parent_id, type, name, sort_name, "
                    "date_created, date_modified, name_folded) "
                    "VALUES (:id, NULL, NULL, 'MusicArtist', :name, :sort_name, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :name_folded)"
                ),
                row,
            )
        connection.execute(
            sa.text("UPDATE item_artists SET artist_item_id = :id WHERE name = :name"),
            {"id": row["id"], "name": name},
        )

    with op.batch_alter_table(
        "item_artists", copy_from=_item_artists_at_0009(), recreate="always"
    ) as batch_op:
        batch_op.alter_column("artist_item_id", existing_type=sa.String(length=32), nullable=False)
        batch_op.create_index("ix_item_artists_credit_artist", ["credit", "artist_item_id"])


def downgrade() -> None:
    with op.batch_alter_table(
        "item_artists", copy_from=_item_artists_at_0010(), recreate="always"
    ) as batch_op:
        batch_op.drop_index("ix_item_artists_credit_artist")
        batch_op.alter_column("artist_item_id", existing_type=sa.String(length=32), nullable=True)

    # Nulling the links first keeps the foreign key satisfied at every point in between. A credit
    # loses its link and not its name, and the next scan derives the link again.
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
