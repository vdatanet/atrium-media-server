# SPDX-License-Identifier: GPL-3.0-or-later
"""two columns 0003's list did not have

Revision ID: 0005
Revises: 0004
Created: 2026-08-27

Both were found the same way, by the same test: a **second** refresh of an item nothing had
touched kept writing rows. A field the write path stores but never reads back looks empty on every
refresh, so it is resolved and written again, for ever - and "a rescan of an unchanged library
changes nothing" is false in a way no engine-level test can see, because the merge is doing
exactly what it was told.

* **`tags`** - `<tag>` elements, which 004 spec section 3.2 says are read and
  [plan section 4](../../../../specs/004-metadata-resolution/plan.md)'s column list forgot. A JSON
  array rather than a sixth join table, because unlike genres and studios a tag has no by-name
  item in the reference's model: it is a string on the item and nothing else.
* **`forced_sort_name`** - the `<sorttitle>` a user wrote, kept **as they wrote it**. `sort_name`
  is derived *from* it (003 section 3.7.3), and a derivation cannot be compared against the thing
  it was derived from - so without this column the sort title is re-applied on every refresh. The
  reference keeps the same two values apart for the same reason
  `[source: MediaBrowser.Controller/Entities/BaseItem.cs ForcedSortName @ v10.11.11]`.

**Reversible**, and both columns are derivable: rolling back loses a tag list and a sort title
that the next refresh reads out of the same sidecar.

See specs/004-metadata-resolution/plan.md section 4 and 004 T10.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plain additions, so no table rebuild and no `copy_from`: SQLite adds a column in place, and
    # neither of these touches a constraint.
    op.add_column(
        "items", sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False)
    )
    op.add_column("items", sa.Column("forced_sort_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "forced_sort_name")
    op.drop_column("items", "tags")
