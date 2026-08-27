# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Sessions` - what a device declared about itself, and what the server says about it.

**Twenty-three fields, in the reference's order**, measured rather than guessed
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`. Two of them are worth stopping on:

* `LastPlaybackCheckIn` is **`0001-01-01T00:00:00.0000000Z`** for a session that has never played
  anything - .NET's `DateTime.MinValue`, not null and not absent. Sending nothing there, which is
  what a nullable field would do, is a difference on every session in the list.
* `PlayState` and `Capabilities` are **objects, not nulls**, before anything has happened. An empty
  object and an absent property are not the same thing to a decoder.

`SupportsMediaControl` and `SupportsRemoteControl` are `false`, which the specification argued was
honest rather than a gap - a client seeing `true` would offer a remote-control UI that does
nothing. **It is now measured, and it is not a divergence at all**: the reference reports `false`
at the top level even for a session that posted `SupportsMediaControl: true`, while echoing that
`true` back inside `Capabilities`. The declaration is the client's; the flag is the server's
judgement about it, and they are different values from the same request.
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`

## What `POST /Sessions/Capabilities/Full` answers

`204`, with no body, and it **replaces** rather than merges - the route is `Full`. Measured, along
with two things about what it accepts: an unknown *property* is accepted, and an unknown value in
`SupportedCommands` is a `400` carrying RFC 9457 problem details, because the reference binds that
field to an enum. Atrium accepts it; the argument is in behaviours section 5.

See specs/002-authentication-users-and-sessions/spec.md section 3.8.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from atrium.api.deps import get_registry, get_sessions, get_state, require_user
from atrium.compat.dates import WireDateTime
from atrium.compat.model import AtriumModel, PropertyKeyed
from atrium.config.state import ServerState
from atrium.db.engine import session_scope
from atrium.db.repositories import SessionRepository, UserRepository
from atrium.domain.session import Session
from atrium.domain.user import User as DomainUser
from atrium.users.sessions import SessionRegistry

router = APIRouter(tags=["Session"])

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


@router.get("/Sessions")
async def sessions(
    request: Request,
    user: Annotated[DomainUser, Depends(require_user)],
    state: Annotated[ServerState, Depends(get_state)],
    registry: Annotated[SessionRegistry, Depends(get_registry)],
) -> list[SessionInfo]:
    """The sessions the caller may see: their own always, all of them for an administrator.

    **Read through the registry**, not out of the database. Activity is flushed on an interval, so
    reporting the stored value would tell a client that the session it is making this very request
    with was last active half a minute ago (plan section 6.5).
    """
    with session_scope(get_sessions(request)) as opened:
        repository = SessionRepository(opened)
        found = repository.all() if user.is_administrator else repository.for_user(user.id)
        users = UserRepository(opened)
        # One lookup per distinct user rather than per session: an administrator's list is mostly
        # one person's devices.
        names = {one.user_id: (users.by_id(one.user_id) or user).name for one in found}

    return [
        to_wire(
            one,
            names.get(one.user_id, ""),
            state.server_id,
            registry.activity(one.id) or one.last_activity_date,
        )
        for one in found
    ]


@router.post("/Sessions/Capabilities/Full", status_code=204)
async def post_capabilities(
    request: Request,
    user: Annotated[DomainUser, Depends(require_user)],
) -> Response:
    """Store what this device says it can do. `204`, no body, and it replaces rather than merges.

    v1 acts on none of it. Storing it is still not optional: a client that posts capabilities and
    then does not see them in `/Sessions` has observed a difference, and this is measured to be
    reflected there (spec section 3.8).

    An unknown property is kept rather than rejected, which is what the reference does. An unknown
    value inside `SupportedCommands` is a `400` there and is accepted here - behaviours section 5
    carries the argument, which is that reproducing a thirty-value enum to refuse values no working
    client sends is cost without a client that benefits.
    """
    document = await request.json()
    if not isinstance(document, dict):
        document = {}

    session_id = getattr(request.state, "session_id", None)
    if session_id is not None:
        with session_scope(get_sessions(request)) as opened:
            SessionRepository(opened).set_capabilities(session_id, document)
    return Response(status_code=204)


__all__ = [
    "DOTNET_MIN_DATE",
    "ClientCapabilities",
    "PlayState",
    "SessionInfo",
    "router",
    "to_wire",
]
