# SPDX-License-Identifier: GPL-3.0-or-later
"""what is actually inside a media file

Revision ID: 0006
Revises: 0005
Created: 2026-08-29

Feature 008's storage: one row per inspected file and one per elementary stream inside it, so that
a negotiation reads rows rather than opening files. Probing a library on every request is not
viable and probing on first playback makes the first play of every item slow (008 spec
section 3.1).

Three things here are not obvious from the column list:

* **The key is the library and the relative path, not a path.** [plan section
  4](../../../../specs/008-playback-negotiation-and-delivery/plan.md) called the primary key
  `path`, "the file inspected". An absolute path would be the one key in this schema that a
  remount invalidates: `library/identity.py` derives every identifier from the path *relative* to
  its root, deliberately, so that moving a root changes nothing - and probe rows keyed absolutely
  would be orphaned by a move that leaves every item, favourite, image and resume position intact.
  This shape is `item_sources`' shape, which is also the table these rows join to.
* **There is one container column, and it is not "the resolved single container".** The plan asked
  for two - a demuxer list and a resolved single form - and the second is not a property of a
  file: the reference derives it per response, from the file's *extension* on a listing and from
  the *device profile* in a negotiation, so one file answers `mp4` on one route and
  `mov,mp4,m4a,3gp,3g2,mj2` on another. What is storable is the normalisation the reference does
  once, at inspection: `matroska,webm` becomes `mkv` where the streams disqualify WebM, and the
  mp4 family survives as the whole list. `format_names` keeps what the demuxer said before that,
  so re-deriving the normalisation never costs a rescan.
* **Nearly every stream column is nullable, from measurement rather than caution.** A Matroska
  stream reports no bitrate, no language tag and no codec tag; a lossless audio stream reports a
  bit depth in one field and zero in the other; and one release of the inspection tool reports no
  reference-frame count at all. A `NOT NULL` on any of those would refuse rows for ordinary files.

**Reversible**, and both tables are derivable: rolling back costs one inspection pass over the
library, which the next scan performs anyway.

See specs/008-playback-negotiation-and-delivery/plan.md sections 4 and 5, and 008 T2.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from atrium.db.types import UtcDateTime

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The demuxer's own vocabulary for what a stream carries, plus the `unknown` an unrecognised one
#: becomes. Written out rather than imported: a migration records what the schema was at a point
#: in time, and importing a constant would let a later edit to it rewrite history.
STREAM_TYPES = "'video', 'audio', 'subtitle', 'data', 'attachment', 'unknown'"


def upgrade() -> None:
    op.create_table(
        "media_probes",
        sa.Column("library_id", sa.String(32), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("container", sa.String(), nullable=False),
        sa.Column("format_names", sa.String(), nullable=False),
        sa.Column("runtime_ticks", sa.BigInteger(), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("video_keyframes", sa.JSON(), nullable=True),
        sa.Column("probed_at", UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["library_id"], ["libraries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("library_id", "relative_path"),
    )

    op.create_table(
        "media_streams",
        sa.Column("library_id", sa.String(32), nullable=False),
        sa.Column("relative_path", sa.String(), nullable=False),
        sa.Column("stream_index", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("codec", sa.String(), nullable=True),
        sa.Column("codec_tag", sa.String(), nullable=True),
        sa.Column("profile", sa.String(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("bit_depth", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("aspect_ratio", sa.String(), nullable=True),
        sa.Column("framerate", sa.String(), nullable=True),
        sa.Column("average_framerate", sa.String(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("channel_layout", sa.String(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_forced", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_hearing_impaired", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_external", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("video_range", sa.String(), nullable=True),
        sa.Column("video_range_type", sa.String(), nullable=True),
        sa.Column("color_range", sa.String(), nullable=True),
        sa.Column("color_transfer", sa.String(), nullable=True),
        sa.Column("color_primaries", sa.String(), nullable=True),
        sa.Column("color_space", sa.String(), nullable=True),
        sa.Column("pixel_format", sa.String(), nullable=True),
        sa.Column("ref_frames", sa.Integer(), nullable=True),
        sa.Column("is_interlaced", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_anamorphic", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["library_id", "relative_path"],
            ["media_probes.library_id", "media_probes.relative_path"],
            ondelete="CASCADE",
            name="fk_media_streams_probe",
        ),
        sa.CheckConstraint(f"type IN ({STREAM_TYPES})", name="ck_media_streams_type"),
        sa.PrimaryKeyConstraint("library_id", "relative_path", "stream_index"),
    )


def downgrade() -> None:
    # Streams first: they hold the foreign key, and dropping the table they point at while they
    # exist is the half-rollback tests/unit/test_migrations.py exists to notice.
    op.drop_table("media_streams")
    op.drop_table("media_probes")
