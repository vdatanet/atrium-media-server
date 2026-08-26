# SPDX-License-Identifier: GPL-3.0-or-later
"""Who is asking.

Grown by feature 002 from the three fields 001 needed into the account itself. Still **not a wire
type**: what a client sees is built from this, not this. The distinction is what lets the column
names, the domain names and the property names a client reads all be different without any of them
being wrong.

The nine honoured policy flags are fields here because something reads them. The other 31 sit in
`policy_extra` untouched, and `configuration` is whole for the same reason - v1 acts on two of its
sixteen properties and stores all of them, because a client that round-trips a document from a
newer server must get its own data back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class User:
    """An account. Frozen, because a repository hands these out and nothing upstream owns them."""

    id: str
    name: str
    is_administrator: bool = False

    #: What a login is matched against. The reference matches case-insensitively (spec 3.3).
    name_normalised: str = ""

    #: The self-describing Argon2id record, or None for an account with no password at all - which
    #: is not the same as an empty one. **Excluded from `repr`**: a domain object ends up in a log
    #: line or an exception message eventually, and a password hash is not something to print
    #: because somebody wrote `logger.debug("%s", user)` (plan section 8.2).
    password_hash: str | None = field(default=None, repr=False)

    is_disabled: bool = False
    is_hidden: bool = False
    enable_all_folders: bool = True
    enable_media_playback: bool = True
    enable_content_deletion: bool = False

    #: The reference sends -1, which is a sentinel rather than a count - spec section 7, OQ-6.
    login_attempts_before_lockout: int = -1
    invalid_login_attempt_count: int = 0
    #: 0 means unlimited.
    max_active_sessions: int = 0

    last_login_date: datetime | None = None
    last_activity_date: datetime | None = None

    #: The 31 policy properties v1 does not act on, and the whole `UserConfiguration`. Echoed back
    #: exactly as they arrived; feature 002 never reads inside either one.
    policy_extra: dict[str, Any] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)


__all__ = ["User"]
