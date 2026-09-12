# SPDX-License-Identifier: GPL-3.0-or-later
"""the zero a non-nullable int leaves behind

Revision ID: 0012
Revises: 0011
Created: 2026-09-12

**Three columns on the sidecar table, and a backfill on the main one — and the backfill is what
makes this revision different from 0011.**

008's owes list recorded `Level: 0` on audio and subtitle, and `Width: 0`/`Height: 0` on a text
subtitle, as *"values the reference defaults or derives"* and called reproducing them a decision.
Reading the source says they are not defaults anybody chose: the reference's probing DTO holds
`Level`, `Width` and `Height` as **non-nullable `int`** and assigns them unconditionally — `Level`
in the common `MediaStream` initialiser, so every stream gets one, and `Width`/`Height` in the
**subtitle** and **video** branches only, so an audio stream gets neither `[source:
MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:709, 776-777, 823-824 and
MediaStreamInfo.cs:95, 109, 172 @ v10.11.11]`. An absent property deserialising into an `int` is
`0`. That is the whole mechanism.

**The sidecar table needs the three columns**, for the same reason it needed `time_base` in 0011:
`MediaInfoResolver` runs a subtitle beside the media through the **same** probing pipeline and then
merges the path's metadata over the answer `[source:
MediaBrowser.Providers/MediaInfo/MediaInfoResolver.cs:314-344 @ v10.11.11]`, so it lands in the
subtitle branch like an embedded one. Unlike 0011's pair, all three belong: a drawn sidecar carries
a real frame size where a text one carries `0`.

**And this one backfills, where 0011 could not.** 0011 said *"no backfill, and none is possible"*
and that was true of it — `time_base`, `nal_length_size` and `is_avc` come from opening the file.
These do not. The value is `0` precisely **because** nothing was read, so a row storing `NULL`
today already holds every fact the backfill needs, and leaving it would mean a library answering
`Level: null` until somebody happened to rescan. The rule is the one 003 §3.9 and §3.10 record from
the other side: a value that needs the media waits for a scan, and a value that does not should not
be made to.

The backfill is therefore **exactly** the coercion, narrowed the same way:

* `level` — every stream of every kind, because the initialiser runs before any branch;
* `width` and `height` — `video` and `subtitle` rows only. An audio row keeps `NULL`, which is a
  different answer from `0` and the one the reference gives.

**Reversible, and the downgrade does not pretend.** It drops the sidecar columns; it does **not**
put the `NULL`s back on `media_streams`, because nothing records which zeroes were backfilled and
which were read, and inventing that distinction is worse than a column of honest zeroes. A
downgrade followed by an upgrade is a no-op rather than a loss.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The table the backfill runs over. Named once so the two directions cannot disagree.
TABLE = "media_streams"

#: The table that gains the three columns.
EXTERNAL_TABLE = "media_external_streams"

#: The stream kinds whose branch assigns a frame size in the reference. `media/probe.py`'s
#: `FRAMED_KINDS` holds the same two, and `tests/unit/test_migrations.py` is where they are
#: asserted to still agree.
FRAMED_KINDS = ("video", "subtitle")


def upgrade() -> None:
    with op.batch_alter_table(EXTERNAL_TABLE) as batch:
        batch.add_column(sa.Column("level", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("width", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("height", sa.Integer(), nullable=True))

    # **Written as text rather than as an ORM update**, because a migration that imported the
    # models would break the day a column is renamed above it. The table and the two kinds are
    # module constants, so nothing user-supplied reaches these strings.
    kinds = ", ".join(f"'{one}'" for one in FRAMED_KINDS)
    level = f"UPDATE {TABLE} SET level = 0 WHERE level IS NULL"  # noqa: S608
    width = f"UPDATE {TABLE} SET width = 0 WHERE width IS NULL AND type IN ({kinds})"  # noqa: S608
    height = f"UPDATE {TABLE} SET height = 0 WHERE height IS NULL AND type IN ({kinds})"  # noqa: S608
    for statement in (level, width, height):
        op.execute(sa.text(statement))


def downgrade() -> None:
    with op.batch_alter_table(EXTERNAL_TABLE) as batch:
        batch.drop_column("height")
        batch.drop_column("width")
        batch.drop_column("level")
