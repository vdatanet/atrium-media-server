# SPDX-License-Identifier: GPL-3.0-or-later
"""the four subtitle codec spellings the wire disagrees with

Revision ID: 0007
Revises: 0006
Created: 2026-08-30

**The file is named for the revision's full scope and holds half of it.** 011 plan section 4 gives
`0007` two jobs - the codec rewrite below and the `media_external_streams` table - and T2 lands the
first. T4 adds the table to this same revision.

**Until it does, this is a data migration: it changes no schema.** It rewrites rows, which is the
one thing the migration sweep cannot see - so it says so here, the way an irreversible revision has
to say so, and `tests/unit/test_migrations.py` reads this line rather than reporting the revision
as one that changed nothing. **The declaration comes out when T4 adds the table**, because it will
have stopped being true.

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

See specs/011-subtitle-delivery/plan.md section 6.1 and 011 T2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import sqlalchemy as sa
from alembic import op

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
    _rewrite(RENAMED)


def downgrade() -> None:
    _rewrite({renamed: raw for raw, renamed in RENAMED.items()})
