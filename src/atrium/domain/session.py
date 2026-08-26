# SPDX-License-Identifier: GPL-3.0-or-later
"""A device holding a token, seen twice.

`AccessToken` and `Session` are the same `(user, device, client)` triple from two directions: one
is what a request is authenticated against, the other is what `/Sessions` reports. They live in one
module because they are created together, replaced together and deleted together, and splitting
them would suggest a lifecycle they do not have.

**Neither of them carries a token.** `AccessToken` holds the SHA-256 of one, which is what the
database stores and what a lookup uses. The only object in this project that ever holds the
plaintext is `IssuedToken`, it exists for exactly one response, and it keeps the secret out of its
own `repr`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class AccessToken:
    """A live credential, identified by its hash. There is no field here for the token itself."""

    token_sha256: str
    user_id: str
    device_id: str
    client: str = ""
    device_name: str = ""
    app_version: str = ""
    created: datetime | None = None
    last_used: datetime | None = None


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A token, the once. Returned by the repository that generated it and by nothing else.

    `secret` is excluded from `repr` for the same reason `User.password_hash` is: this object is
    handed to the code that builds an authentication response, and that code is exactly where
    somebody eventually adds a debug log line.
    """

    secret: str = field(repr=False)
    record: AccessToken


@dataclass(frozen=True, slots=True)
class Session:
    """What `/Sessions` reports for one device.

    Live playback state is deliberately absent: feature 007 owns `NowPlayingItem` and `PlayState`
    and keeps them in memory, because they change several times a minute and none of it is worth
    surviving a restart.
    """

    id: str
    user_id: str
    device_id: str
    client: str = ""
    device_name: str = ""
    app_version: str = ""
    remote_end_point: str | None = None
    last_activity_date: datetime | None = None
    last_playback_check_in: datetime | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)


__all__ = ["AccessToken", "IssuedToken", "Session"]
