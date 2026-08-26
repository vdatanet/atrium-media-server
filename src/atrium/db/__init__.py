# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistence: the engine, the schema, the migrations, and the repository boundary.

Nothing above this package sees a SQLAlchemy type. Repositories return domain objects, which is
what makes ADR-0003's "SQLite is the default, not the only option" a claim rather than a hope.
"""

from __future__ import annotations
