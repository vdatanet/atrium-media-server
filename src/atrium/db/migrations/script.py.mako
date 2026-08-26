# SPDX-License-Identifier: GPL-3.0-or-later
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}

A migration is reversible unless this docstring says otherwise and says why. See
specs/002-authentication-users-and-sessions/plan.md section 4.

Import order here is the one ruff wants, so a generated migration passes lint without being
edited. The project's own column types are imported by `render_item` in env.py - Alembic does not
import them on its own, and a migration referring to a type it never imported fails at the moment
an operator runs it and not before.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
