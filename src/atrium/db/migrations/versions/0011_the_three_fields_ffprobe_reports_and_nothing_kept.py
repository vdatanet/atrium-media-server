# SPDX-License-Identifier: GPL-3.0-or-later
"""three stream fields the inspection read and threw away

Revision ID: 0011
Revises: 0010
Created: 2026-09-10

**Three columns, and what makes them worth a revision is what they are not.** A sweep left 242
differences on `PlaybackInfo`, every one a property of a `MediaStream`, and the obvious reading was
that this server stored them and failed to emit them — the *written here, read there* shape three
defects of 2026-09-08 had. Asked of `ffprobe` directly, that was wrong: the stored fields already
agreed, and these three are the only ones the tool reports that nothing kept
`[probe: tools/probe_playback_stream_fields.py, Jellyfin 10.11.11, 2026-09-10]`.

* **`time_base`** — the stream's own time base as an exact rational. **Per file**: the fixture
  answers `1/1000`, `1/12800` and `1/48000` on three files, so it is a column and not a constant.
* **`nal_length_size`** — how many bytes an AVC length prefix takes. A string because it is one on
  the wire and because nothing computes with it.
* **`is_avc`** — `NOT NULL`, default false. The reference's own field is a non-nullable `bool`
  filled from `ffprobe`'s `is_avc`, so a stream the tool says nothing about is `false` there
  rather than unknown.

**No backfill, and none is possible.** These come from opening the file, and this revision does not
open files. Every stream stored before it carries the defaults until the next scan re-inspects it —
which is the same shape [003 §3.9](../../../../specs/003-library-configuration-and-scanning/spec.md)
records for the creation date and §3.10 for the duration: the value derives from a file that is
still there, so a rescan corrects it and no migration has to pretend to.

**Reversible without loss of anything the file does not still hold.** The downgrade drops the three
columns; a later upgrade plus one scan restores every value, because the source is the media and
not this table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The table these three join. Named once so the two directions cannot disagree about it.
TABLE = "media_streams"

#: **And one of them joins a second table.** A subtitle beside the media is a stream a client sees
#: like any other, and the reference answers a `TimeBase` for it - `ffprobe` reports `1/1000` for
#: an `.srt`. The other two do not belong here: `nal_length_size` and `is_avc` are properties of
#: an AVC bitstream and this table holds subtitles.
EXTERNAL_TABLE = "media_external_streams"


def upgrade() -> None:
    with op.batch_alter_table(EXTERNAL_TABLE) as batch:
        batch.add_column(sa.Column("time_base", sa.String(), nullable=True))
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(sa.Column("time_base", sa.String(), nullable=True))
        batch.add_column(sa.Column("nal_length_size", sa.String(), nullable=True))
        # **`server_default` and not just `nullable=False`**: an existing row has no value to put
        # here, and a column added `NOT NULL` with nothing behind it is a migration that fails on
        # the first library anybody has.
        batch.add_column(
            sa.Column(
                "is_avc",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("is_avc")
        batch.drop_column("nal_length_size")
        batch.drop_column("time_base")
    with op.batch_alter_table(EXTERNAL_TABLE) as batch:
        batch.drop_column("time_base")
