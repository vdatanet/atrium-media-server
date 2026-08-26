# SPDX-License-Identifier: GPL-3.0-or-later
"""Who is asking.

The minimum feature 001 can justify: enough to be the return type of the authentication seam, and
no more. Feature 002 owns this type and grows it - policy, configuration, session - when there are
accounts to put in it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class User:
    """An authenticated user. Not a wire type: what a client sees is built from this, not this."""

    id: str
    name: str
    is_administrator: bool = False


__all__ = ["User"]
