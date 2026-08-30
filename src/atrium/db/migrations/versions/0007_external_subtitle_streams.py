# SPDX-License-Identifier: GPL-3.0-or-later
"""subtitle streams found beside the media, and the four codec spellings the wire disagrees with

Revision ID: 0007
Revises: 0006
Created: 2026-08-30

**Two jobs in one revision**, as 011 plan section 4 declares: the `media_external_streams` table
below, added by T4, and the codec rewrite added by T2. They are one revision because they are one
change of mind about what a subtitle stream is - a library scanned by 008 holds neither the table
nor the spellings, and there is no state in which one is wanted without the other.

*T2's docstring declared this revision a data migration, because until the table arrived it changed
no schema and `tests/unit/test_migrations.py` reads that declaration rather than reporting a
revision that changed nothing. The declaration is gone with this change, because it has stopped
being true - which is what T2 said would happen.*

## The table

One row per subtitle stream found in a file beside the media file. `models.MediaExternalStreamRow`
carries the reasoning for its columns; the two that decide the shape are `ordinal`, which is what
turns a set of files into stream indices, and the per-row `(size, mtime_ns)`, which is the change
signal that makes discovery reachable on a scan that would otherwise skip the media file entirely.

**No index beyond the primary key.** Every read is `(library_id, relative_path)` for one item's
files, which is that key's own prefix.

## The rewrite

Four subtitle codecs are renamed by the reference *during inspection*, before anything reads them:
`dvb_subtitle` becomes `DVBSUB`, `dvb_teletext` becomes `DVBTXT`, `dvd_subtitle` becomes `DVDSUB`
and `hdmv_pgs_subtitle` becomes `PGSSUB` `[source:
MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:632-652, 765-768 @ v10.11.11]`. 008
stored what the inspection tool said instead, and that is a property already on the wire: a real
library answers `PGSSUB` and `DVDSUB` beside `subrip` and `ass` `[probe:
tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]`.

**A rescan would not fix it.** A media file's change signal is its size and modification time, and
neither moves because this server changed its mind about a name - so a library scanned by 008
would keep the old spelling until the file itself changed. Hence a rewrite rather than a note.

Three properties of the rewrite, all of which come from the two spellings being disjoint - the
inspection tool never emits `DVDSUB` and the reference never emits `dvd_subtitle`:

* **A row written before this revision and one written after it are told apart by the value
  itself.** There is no flag and no timestamp to consult: `codec = 'dvd_subtitle'` on a subtitle
  row is a pre-0007 row and `codec = 'DVDSUB'` is a post-0007 one.
* **Running it twice is running it once.** The second pass finds none of the four names it
  rewrites, because the first pass replaced them with names outside its own domain.
* **Reversible, exactly**, for the same reason: the downgrade maps the four back and cannot
  collide with anything a scan wrote.

Only `type = 'subtitle'` rows are touched, which is where the reference does the rename - it sits
inside the branch that handles a subtitle stream.

See specs/011-subtitle-delivery/plan.md sections 4 and 6.1, and 011 T2 and T4.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op

from atrium.db.types import UtcDateTime

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What the inspection tool reports, and what the reference calls it. Written out rather than
#: imported: a migration records what happened at a point in time, and importing the table would
#: let a later edit to it rewrite history.
RENAMED = {
    "dvb_subtitle": "DVBSUB",
    "dvb_teletext": "DVBTXT",
    "dvd_subtitle": "DVDSUB",
    "hdmv_pgs_subtitle": "PGSSUB",
}

STREAMS = sa.table(
    "media_streams",
    sa.column("type", sa.String),
    sa.column("codec", sa.String),
)


def _rewrite(mapping: Mapping[str, str]) -> None:
    """Replace each key with its value, on subtitle rows, matching without regard to case.

    Case-insensitively because that is how the reference compares these four names, and because a
    stored spelling is whatever some build of the inspection tool wrote.
    """
    for source, target in mapping.items():
        op.execute(
            STREAMS.update()
            .where(STREAMS.c.type == "subtitle")
            .where(sa.func.lower(STREAMS.c.codec) == source.lower())
            .values(codec=target)
        )


def upgrade() -> None:
    op.create_table(
        "media_external_streams",
        sa.Column("library_id", sa.String(32), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("external_path", sa.String(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("stream_index", sa.Integer(), nullable=False),
        sa.Column("codec", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_forced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_hearing_impaired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("probed_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "library_id", "relative_path", "ordinal", name="pk_media_external_streams"
        ),
        sa.ForeignKeyConstraint(
            ["library_id", "relative_path"],
            ["media_probes.library_id", "media_probes.relative_path"],
            ondelete="CASCADE",
            name="fk_media_external_streams_probe",
        ),
    )
    _rewrite(RENAMED)


def downgrade() -> None:
    _rewrite({renamed: raw for raw, renamed in RENAMED.items()})
    op.drop_table("media_external_streams")
