# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Sessions` - the models now, the routes at T12.

`POST /Users/AuthenticateByName` returns a `SessionInfo`, so the model has to exist before the
routes that report one do. It lives here rather than in `api/users.py` because that is where the
plan's module list puts it, and because T12 adds routes to this module rather than moving anything.

**Twenty-three fields, in the reference's order**, measured rather than guessed
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`. Two of them are worth stopping on:

* `LastPlaybackCheckIn` is **`0001-01-01T00:00:00.0000000Z`** for a session that has never played
  anything - .NET's `DateTime.MinValue`, not null and not absent. Sending nothing there, which is
  what a nullable field would do, is a difference on every session in the list.
* `PlayState` and `Capabilities` are **objects, not nulls**, before anything has happened. An empty
  object and an absent property are not the same thing to a decoder.

`SupportsMediaControl` and `SupportsRemoteControl` are `false`, which is honest rather than a gap:
a client seeing `true` would offer a remote-control UI that does nothing (spec section 3.8).

See specs/002-authentication-users-and-sessions/spec.md section 3.8.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import Field

from atrium.compat.dates import WireDateTime
from atrium.compat.model import AtriumModel, PropertyKeyed
from atrium.domain.session import Session

#: .NET's `DateTime.MinValue`, which is what the reference sends for a session that has never
#: reported playback. Measured.
DOTNET_MIN_DATE = datetime(1, 1, 1, tzinfo=UTC)


class PlayState(AtriumModel):
    """Present and empty before anything plays. Feature 007 fills it."""

    can_seek: bool = False
    is_paused: bool = False
    is_muted: bool = False
    repeat_mode: str = "RepeatNone"
    playback_order: str = "Default"


class ClientCapabilities(AtriumModel):
    """What a client posted about itself. Stored whole and reflected back, acted on by nothing.

    A client that posts capabilities and then does not see them has observed a difference, which
    is why storing it is not optional (spec section 3.8).
    """

    playable_media_types: list[str] = Field(default_factory=list)
    supported_commands: list[str] = Field(default_factory=list)
    supports_media_control: bool = False
    supports_persistent_identifier: bool = False


class SessionInfo(AtriumModel):
    """One device's session, in the reference's field order."""

    play_state: PlayState = Field(default_factory=lambda: PlayState())
    additional_users: list[dict[str, Any]] = Field(default_factory=list)
    capabilities: Annotated[dict[str, Any], PropertyKeyed] = Field(default_factory=dict)
    remote_end_point: str | None = None
    playable_media_types: list[str] = Field(default_factory=list)
    id: str
    user_id: str
    user_name: str
    client: str = ""
    last_activity_date: WireDateTime
    last_playback_check_in: WireDateTime = DOTNET_MIN_DATE
    device_name: str = ""
    device_id: str = ""
    application_version: str = ""
    is_active: bool = True
    supports_media_control: bool = False
    supports_remote_control: bool = False
    now_playing_queue: list[dict[str, Any]] = Field(default_factory=list)
    now_playing_queue_full_items: list[dict[str, Any]] = Field(default_factory=list)
    has_custom_device_name: bool = False
    server_id: str
    user_primary_image_tag: str | None = None
    supported_commands: list[str] = Field(default_factory=list)


def to_wire(
    session: Session, user_name: str, server_id: str, last_activity: datetime | None = None
) -> SessionInfo:
    """Build the wire object from a domain session.

    `last_activity` is passed in rather than read off the session: the live value lives in the
    registry between flushes, and reporting the stored one would tell a client that the session it
    is using right now was last active half a minute ago (plan section 6.5).
    """
    capabilities = dict(session.capabilities)
    return SessionInfo(
        capabilities=capabilities,
        playable_media_types=list(capabilities.get("PlayableMediaTypes") or []),
        supported_commands=list(capabilities.get("SupportedCommands") or []),
        remote_end_point=session.remote_end_point,
        id=session.id,
        user_id=session.user_id,
        user_name=user_name,
        client=session.client,
        last_activity_date=last_activity or session.last_activity_date or DOTNET_MIN_DATE,
        last_playback_check_in=session.last_playback_check_in or DOTNET_MIN_DATE,
        device_name=session.device_name,
        device_id=session.device_id,
        application_version=session.app_version,
        server_id=server_id,
    )


__all__ = ["DOTNET_MIN_DATE", "ClientCapabilities", "PlayState", "SessionInfo", "to_wire"]
