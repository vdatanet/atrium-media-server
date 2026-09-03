# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Sessions` - what a device declared about itself, and what the server says about it.

**Twenty-three fields, in the reference's order**, measured rather than guessed
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`. Two of them are worth
stopping on:

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
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`

## What `POST /Sessions/Capabilities/Full` answers

`204`, with no body, and it **replaces** rather than merges - the route is `Full`. Measured, along
with two things about what it accepts: an unknown *property* is accepted at the door - though the
reference then drops it from the session's echo, where Atrium keeps it (behaviours section 5.9) -
and an unknown value in `SupportedCommands` is a `400` carrying RFC 9457 problem details, because
the reference binds that field to an enum. Atrium accepts it; the argument is in behaviours
section 5.

See specs/002-authentication-users-and-sessions/spec.md section 3.8.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field

from atrium.api.delivery import policy_of
from atrium.api.deps import get_playing, get_registry, get_sessions, get_state, require_user
from atrium.api.dynamic_hls import transcode_manager
from atrium.api.item_dto import BuildContext, Width, build_dto
from atrium.api.item_models import BaseItemDto
from atrium.api.items import library_context
from atrium.compat.dates import WireDateTime
from atrium.compat.model import AtriumModel, PropertyKeyed
from atrium.compat.ticks import WireTicks
from atrium.config.state import ServerState
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import LibraryRepository, SessionRepository, UserRepository
from atrium.domain.queries import ItemQuery
from atrium.domain.session import Session
from atrium.domain.user import User as DomainUser
from atrium.media.sessions import TranscodingReport
from atrium.users.playing import PlayingNow
from atrium.users.sessions import SessionRegistry

router = APIRouter(tags=["Session"])

#: .NET's `DateTime.MinValue`, which is what the reference sends for a session that has never
#: reported playback. Measured.
DOTNET_MIN_DATE = datetime(1, 1, 1, tzinfo=UTC)

#: The reference's `HardwareAccelerationType` for "no hardware at all", which is both its shipped
#: default and the truth about this server: nothing here asks ffmpeg for a hardware encoder
#: `[source: MediaBrowser.Model/Entities/HardwareAccelerationType.cs:13 @ v10.11.11]`.
SOFTWARE_ACCELERATION = "none"

#: **What a `NowPlayingItem` is not.** Measured against a live playback: it carries 41 properties
#: and a full `/Items/{itemId}` body carries 56, and the difference is exactly this set - so the
#: shape is not a bespoke selection but the full body minus a named fifteen
#: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
#:
#: Five of them are properties v1 emits today (`Etag`, `SortName`, `People`, `UserData`, `Tags`);
#: the rest name properties no v1 emitter produces yet, and they are listed anyway because that is
#: what makes this a **tripwire**: 008 adds `MediaSources`, and the day it does, this set is what
#: keeps it out of a session entry the reference does not put it in (006's `Chapter` pattern).
NOT_IN_NOW_PLAYING: frozenset[str] = frozenset(
    {
        "Etag",
        "CanDelete",
        "CanDownload",
        "SortName",
        "ForcedSortName",
        "MediaSources",
        "ProductionLocations",
        "PlayAccess",
        "RemoteTrailers",
        "People",
        "UserData",
        "DisplayPreferencesId",
        "Tags",
        "LockedFields",
        "LockData",
    }
)


class PlayState(AtriumModel):
    """The **last report, whole** - never an accumulation of them.

    Measured: after a start carrying `CanSeek: true` and `VolumeLevel: 80`, a progress omitting
    both reads back `CanSeek: false` and no `VolumeLevel` at all, so a server that merged reports
    would send a `PlayState` no reference server sends
    `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`.

    Eleven fields in the measured order, `PositionTicks` **first** - the nullable ones absent
    exactly when the last report omitted them, which is the null suppression every response gets
    (behaviours section 1.7) doing the work. Empty before anything plays, which is 002's measured
    shape and unchanged by the six fields added here.
    """

    position_ticks: WireTicks | None = None
    can_seek: bool = False
    is_paused: bool = False
    is_muted: bool = False
    volume_level: int | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    media_source_id: str | None = None
    play_method: str | None = None
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


class TranscodingInfo(AtriumModel):
    """What a device is having produced for it, while it is being produced.

    Thirteen properties upstream, measured on a live re-encode and reproduced in that order
    `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`. **Eleven are
    declared here**, and the two that are not - `Framerate` and `CompletionPercentage` - are the
    two that come from parsing the encoder's progress output, which Atrium does not do. They are
    nullable upstream and genuinely absent there twice: before ffmpeg has said anything, and
    after the job stops, where the measured object keeps exactly these eleven keys. The argument
    for the divergence is in behaviours section 3.11.

    `HardwareAccelerationType` is the operator's encoding setting rather than a fact about the
    job - the measured server answers `qsv` because that is what it is configured for - and its
    shipped default is `none` `[source:
    MediaBrowser.Model/Entities/HardwareAccelerationType.cs:13 @ v10.11.11]`, which is what
    Atrium answers and what it does.
    """

    audio_codec: str | None = None
    video_codec: str | None = None
    container: str | None = None
    is_video_direct: bool = False
    is_audio_direct: bool = False
    bitrate: int | None = None
    width: int | None = None
    height: int | None = None
    audio_channels: int | None = None
    hardware_acceleration_type: str = SOFTWARE_ACCELERATION
    transcode_reasons: list[str] = Field(default_factory=list)


def transcoding_info(report: TranscodingReport | None) -> TranscodingInfo | None:
    """The wire object for one manager report, or nothing when nothing is being produced."""
    if report is None:
        return None
    return TranscodingInfo(
        audio_codec=report.audio_codec,
        video_codec=report.video_codec,
        container=report.container,
        is_video_direct=report.video_direct,
        is_audio_direct=report.audio_direct,
        bitrate=report.bitrate,
        width=report.width,
        height=report.height,
        audio_channels=report.audio_channels,
        transcode_reasons=list(report.reasons),
    )


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
    #: **Between `DeviceName` and `DeviceId`**, measured - and absent, not null, when nothing is
    #: playing, so the twenty-three-field order 002 pinned is untouched for an idle session.
    now_playing_item: BaseItemDto | None = None
    device_id: str = ""
    application_version: str = ""
    #: **Between `ApplicationVersion` and `IsActive`**, which is where the reference's own
    #: document puts it `[spec: SessionInfoDto]` - and absent, not null, for a device having
    #: nothing produced for it, so 002's twenty-three-field order is untouched for every session
    #: that is not transcoding.
    transcoding_info: TranscodingInfo | None = None
    is_active: bool = True
    supports_media_control: bool = False
    supports_remote_control: bool = False
    now_playing_queue: list[dict[str, Any]] = Field(default_factory=list)
    now_playing_queue_full_items: list[dict[str, Any]] = Field(default_factory=list)
    has_custom_device_name: bool = False
    server_id: str
    user_primary_image_tag: str | None = None
    supported_commands: list[str] = Field(default_factory=list)


def play_state(playing: PlayingNow | None) -> PlayState:
    """The last report as `PlayState`, or the empty object an idle session carries."""
    if playing is None:
        return PlayState()
    return PlayState(
        position_ticks=playing.position_ticks,
        can_seek=playing.can_seek,
        is_paused=playing.is_paused,
        is_muted=playing.is_muted,
        volume_level=playing.volume_level,
        audio_stream_index=playing.audio_stream_index,
        subtitle_stream_index=playing.subtitle_stream_index,
        media_source_id=playing.media_source_id,
        play_method=playing.play_method,
    )


def to_wire(
    session: Session,
    user_name: str,
    server_id: str,
    last_activity: datetime | None = None,
    playing: PlayingNow | None = None,
    now_playing_item: BaseItemDto | None = None,
    check_in: datetime | None = None,
    transcoding: TranscodingReport | None = None,
) -> SessionInfo:
    """Build the wire object from a domain session.

    `last_activity` and `check_in` are passed in rather than read off the session: the live values
    live in the registries between flushes, and reporting the stored ones would tell a client that
    the session it is using right now was last active half a minute ago (plan section 6.5) and
    that the playback it is reporting has not checked in (007 plan section 6.6).

    `transcoding` is passed in for the same reason and one more: it comes from the transcode
    manager rather than from the database, because a transcode is a live process and nothing
    about it survives a restart (008 spec section 3.8).
    """
    capabilities = dict(session.capabilities)
    return SessionInfo(
        play_state=play_state(playing),
        now_playing_item=now_playing_item,
        transcoding_info=transcoding_info(transcoding),
        capabilities=capabilities,
        playable_media_types=list(capabilities.get("PlayableMediaTypes") or []),
        supported_commands=list(capabilities.get("SupportedCommands") or []),
        remote_end_point=session.remote_end_point,
        id=session.id,
        user_id=session.user_id,
        user_name=user_name,
        client=session.client,
        last_activity_date=last_activity or session.last_activity_date or DOTNET_MIN_DATE,
        last_playback_check_in=check_in or session.last_playback_check_in or DOTNET_MIN_DATE,
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
    playing = get_playing(request)
    transcodes = transcode_manager(request)
    with session_scope(get_sessions(request)) as opened:
        repository = SessionRepository(opened)
        found = repository.all() if user.is_administrator else repository.for_user(user.id)
        users = UserRepository(opened)
        # One lookup per distinct user rather than per session: an administrator's list is mostly
        # one person's devices.
        people = {one.user_id: users.by_id(one.user_id) or user for one in found}
        names = {user_id: person.name for user_id, person in people.items()}

        live = {one.id: snapshot for one in found if (snapshot := playing.snapshot(one.id))}
        items = _now_playing_items(opened, live, found, people, state.server_id)

    return [
        to_wire(
            one,
            names.get(one.user_id, ""),
            state.server_id,
            registry.activity(one.id) or one.last_activity_date,
            playing=live.get(one.id),
            now_playing_item=items.get(one.id),
            check_in=playing.check_in(one.id) or registry.playback_check_in(one.id),
            # By **device**, not by session: the reference hangs its report on the device's
            # session and the delivery routes only ever carry a `deviceId`, which is the
            # identifier a client puts in the negotiated URL rather than the session row's id.
            transcoding=transcodes.reporting(one.device_id),
        )
        for one in found
    ]


def _now_playing_items(
    opened: Any,
    live: dict[str, PlayingNow],
    found: list[Session],
    people: dict[str, DomainUser],
    server_id: str,
) -> dict[str, BaseItemDto]:
    """One `NowPlayingItem` per playing session, built by 005's own DTO builder.

    **Through each session's own user**, not the caller's: an administrator reading `/Sessions`
    sees what other people are playing, and resolving those items through the administrator's
    visibility would be a different question with the same answer only by accident.

    One query per distinct playing user rather than one per session - a person's devices mostly
    play different things, and there are as many playing sessions as there are people watching.
    """
    if not live:
        return {}
    sessions_by_id = {one.id: one for one in found}
    libraries = library_context(LibraryRepository(opened))
    repository = ItemQueryRepository(opened)

    wanted: dict[str, set[str]] = {}
    for session_id, snapshot in live.items():
        owner = sessions_by_id[session_id].user_id
        wanted.setdefault(owner, set()).add(snapshot.item_id)

    built: dict[str, dict[str, BaseItemDto]] = {}
    for user_id, item_ids in wanted.items():
        # **One context per playing user, not one for the batch**, because `policy` is that
        # user's: the entries here are built through each session's own account, and a context
        # hoisted out of this loop would answer the first watcher's permissions on everybody
        # else's row. `MediaSources` is omitted from this shape, so nothing on the wire reads it
        # today - which is exactly the kind of silence the field's own absence of a default
        # exists to stop growing into a difference later.
        context = BuildContext(
            server_id=server_id,
            policy=policy_of(people[user_id]),
            width=Width.FULL,
            # The measured shape, expressed as what it is missing (`NOT_IN_NOW_PLAYING`) rather
            # than as a bespoke list of what it has - so a property added to the full body is in
            # a session entry only if the reference puts it there.
            enable_user_data=False,
            libraries=libraries,
            omit=NOT_IN_NOW_PLAYING,
        )
        page = repository.run(
            ItemQuery(user=people[user_id], ids=tuple(sorted(item_ids)), count=False)
        )
        built[user_id] = {one.id: build_dto(one, context) for one in page.items}

    answered: dict[str, BaseItemDto] = {}
    for session_id, snapshot in live.items():
        owner = sessions_by_id[session_id].user_id
        found_item = built.get(owner, {}).get(snapshot.item_id)
        if found_item is not None:
            answered[session_id] = found_item
    return answered


@router.post("/Sessions/Capabilities/Full", status_code=204)
async def post_capabilities(
    request: Request,
    user: Annotated[DomainUser, Depends(require_user)],
) -> Response:
    """Store what this device says it can do. `204`, no body, and it replaces rather than merges.

    v1 acts on none of it. Storing it is still not optional: a client that posts capabilities and
    then does not see them in `/Sessions` has observed a difference, and this is measured to be
    reflected there (spec section 3.8).

    An unknown property is kept rather than rejected. The reference also accepts one - the same
    `204` - and then drops it from the session's `Capabilities`, so the keep is a recorded
    divergence rather than parity (behaviours section 5.9): nothing can depend on the echo,
    because no client of the reference ever reads its stranger back. An unknown value inside
    `SupportedCommands` is a `400` there and is accepted here - behaviours section 5 carries the
    argument, which is that reproducing a thirty-value enum to refuse values no working client
    sends is cost without a client that benefits.
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
    "NOT_IN_NOW_PLAYING",
    "SOFTWARE_ACCELERATION",
    "ClientCapabilities",
    "PlayState",
    "SessionInfo",
    "TranscodingInfo",
    "router",
    "to_wire",
    "transcoding_info",
]
