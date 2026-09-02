# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `MediaInfoController`: what this client should do with this item.

Two routes, and they are not two spellings of one thing.

`POST /Items/{itemId}/PlaybackInfo` is the negotiation: a client describes itself and every media
source comes back **annotated** with what that description leaves possible - the three capability
flags, and a `TranscodingUrl` when the answer is "fetch it from here instead". `GET` is the
profile-less variant, and it negotiates nothing at all: the sources keep their intrinsic
capabilities, all three flags true, and no URL. Both issue a `PlaySessionId`, which is what ties
the negotiation to the delivery request that follows and to the three reports of 007.

**"No `DeviceProfile`" is not "no profile".** A `POST` whose body carries none falls back to the
profile the device stored through `POST /Sessions/Capabilities/Full`, and the answer changes
accordingly: the same profile-less request answers direct play before the capabilities are posted
and a `TranscodingUrl` after `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
2026-08-29]`, `[source: Jellyfin.Api/Controllers/MediaInfoController.cs:137-147 @ v10.11.11]`. The
`GET` is unaffected - it is profile-less by construction, measured on the same session. A client
that describes itself once and then negotiates with a bare body is a client this fallback exists
for, and without it Atrium would hand it a file it never said it could open.

**Every semantic below this module is `media/decision.py`'s.** This one parses a body into that
module's vocabulary, resolves the item the way `GET /Items/{itemId}` resolves it, and renders the
answer. It decides nothing: a rung, a reason and a ceiling are all read from a `Decision`.

**The refusals, measured rather than assumed** `[probe: tools/probe_playback_info.py, Jellyfin
10.11.11, 2026-08-29]`:

* an **unknown or invisible** item is the problem-details `404` on both routes, byte-identical to
  `GET /Items/{itemId}`'s own refusal - the item resolves through the same visible-item lookup, so
  the two cannot drift apart;
* a request with **no token** is the empty `401`, decided before this module runs;
* a profile that can play nothing is a `200` whose flags are all false, with **no** `ErrorCode`;
* the one `ErrorCode` that exists arrives only where the **source list is empty**, which a v1
  request reaches by naming a `MediaSourceId` the item does not have - and that answer carries no
  `PlaySessionId` either, because the reference issues one only when there are sources to play.

**An unrecognised token inside the body is a `400`**, which is the opposite of what an unknown
*query* token does (behaviours section 1.12). A `Property` of `NotAThing` inside a codec profile
is refused rather than dropped, so the profile vocabulary is declared as enums here and the
framework's validation produces the refusal `[probe: manual requests via tools/_probe.py, Jellyfin
10.11.11, 2026-08-29]`. `Photo`, `Subtitle` and `Lyric` are in that vocabulary and are **not**
errors: they are profile entries about media this negotiation is not about, and they are dropped
when the profile is mapped.

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.2 and 3.3, and plan sections
6.2 and 6.3.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BeforeValidator, Field, ValidationError

from atrium.api.delivery import policy_of
from atrium.api.deps import get_sessions, require_user
from atrium.api.item_dto import VIDEO_TYPES, LibraryContext
from atrium.api.items import effective_user, library_context
from atrium.compat.auth import client_info, extract_token
from atrium.compat.errors import NotFoundError
from atrium.compat.guids import WireGuid, new_id
from atrium.compat.model import AtriumModel
from atrium.compat.ticks import WireTicks
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository
from atrium.db.repositories import LibraryRepository, SessionRepository, UserRepository
from atrium.domain.media import MediaInspection
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User
from atrium.media import decision as ladder
from atrium.media import info as media_info
from atrium.media import urls

router = APIRouter(tags=["MediaInfo"])

#: The only `ErrorCode` the reference can produce, and the only one this server emits.
#: `[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:123 @ v10.11.11]`
NO_COMPATIBLE_STREAM = "NoCompatibleStream"

#: Where a device stores the profile a bare `POST` falls back to.
CAPABILITIES_PROFILE = "DeviceProfile"


# ------------------------------------------------------------------------------------------------
# What a client says about itself
# ------------------------------------------------------------------------------------------------


class ProfileType(Enum):
    """`DlnaProfileType` in full. `[source: MediaBrowser.Model/Dlna/DlnaProfileType.cs @
    v10.11.11]`

    All five, because a real browser profile lists entries for media this negotiation is not
    about and the reference binds them happily. Declaring only the two that matter would turn a
    `Photo` entry - which costs nothing - into a `400` on every request the client makes.
    """

    AUDIO = "Audio"
    VIDEO = "Video"
    PHOTO = "Photo"
    SUBTITLE = "Subtitle"
    LYRIC = "Lyric"


#: Which of the five this feature negotiates about. The rest are dropped, not refused.
NEGOTIABLE: dict[ProfileType, ladder.MediaKind] = {
    ProfileType.AUDIO: ladder.MediaKind.AUDIO,
    ProfileType.VIDEO: ladder.MediaKind.VIDEO,
}


class ProfileConditionDto(AtriumModel):
    """`[spec: ProfileCondition]`. `IsRequired` defaults true, as the reference's own does."""

    condition: ladder.ConditionType
    property: ladder.ConditionProperty
    value: str | None = None
    is_required: bool = True


class DirectPlayProfileDto(AtriumModel):
    """`[spec: DirectPlayProfile]`: a container this client can open, and what may be inside it."""

    container: str | None = None
    audio_codec: str | None = None
    video_codec: str | None = None
    type: ProfileType = ProfileType.VIDEO


class TranscodingProfileDto(AtriumModel):
    """`[spec: TranscodingProfile]`: a shape this client will accept the server producing.

    Five of these fields decide nothing and are read straight back out of the `TranscodingUrl`
    (`media/urls.py`). `MaxAudioChannels` is a **string** on the wire and a number only when it
    parses as one, which is the reference's `int.TryParse` rather than leniency invented here.
    """

    container: str = ""
    type: ProfileType = ProfileType.VIDEO
    video_codec: str | None = None
    audio_codec: str | None = None
    protocol: str = "http"
    context: str = "Streaming"
    max_audio_channels: str | None = None
    min_segments: int = 0
    segment_length: int = 0
    break_on_non_key_frames: bool = False
    enable_audio_vbr_encoding: bool = True
    enable_subtitles_in_manifest: bool = False
    """Bound at 011 T9, and honoured exactly as far as the reference honours it: it reaches the
    delivery address and stops there, because the route that address names cannot read it (011
    spec section 3.4)."""


def _bound_subtitle_method(value: Any) -> Any:
    """The three ways the reference's binder accepts a delivery method, and the one it refuses.

    Measured in one run, all four classes: `hls` and `HLS` bind exactly as `Hls` does, the
    ordinal `3` binds to the same member, and `banana` is a `400` - which is the same shape 012's
    gate found for an enum-typed value, arriving here on a request **body**
    `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.

    **The refusal is the half that does not carry across to a query string**, measured at T11: the
    same word in a delivery address is a `200` that announces nothing rather than a `400`, because
    a nullable enum *parameter* binds through a binder that swallows the failure
    (`media/decision.py`'s `method_named`). The vocabulary is one table - the ordinals live beside
    the enumeration, read from both sides - and the two refusals are not.

    Anything this function does not recognise is handed to the model unchanged, so the refusal is
    the framework's validation `400` rather than a second refusal invented here.

    **What is lenient is the binder rather than this one enum**, and the same run says so: a
    direct-play entry typed `"video"` rather than `"Video"` binds and direct-plays on the
    reference. So `ProfileType`, `ConditionType`, `ConditionProperty` and `CodecKind` - all bound
    in this same body and all matched case-sensitively here - are each a `400` where the reference
    answers `200`. Making that general is a change to `compat/model.py`, which every request model
    inherits, so this change fixes only the vocabulary it adds. **The answer lives in 012's
    OQ-4**, widened from the protocol value to the binder by the measurement above; 011 plan
    section 6.8 points at it rather than restating it, and so does this.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        wanted = value.lower()
        return next(
            (one for one in ladder.SubtitleMethod if one.value.lower() == wanted),
            value,
        )
    if isinstance(value, int):
        return ladder.SUBTITLE_METHOD_ORDINALS.get(value, value)
    return value


class SubtitleProfileDto(AtriumModel):
    """`[spec: SubtitleProfile]`: one subtitle format, and how this client will take it.

    Four of the five properties, because `DidlMode` is a DLNA-era string the negotiation never
    reads; it is dropped by `extra="ignore"` like every other unread property of a real profile.

    **`Method` defaults to `Encode`**, which is the member the reference's enum defaults to and is
    measured: an entry with no `Method` key at all answers `Encode` on every stream, which is
    indistinguishable from declaring nothing - because no pass of the ladder can return that
    member `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
    """

    format: str | None = None
    method: Annotated[ladder.SubtitleMethod, BeforeValidator(_bound_subtitle_method)] = (
        ladder.SubtitleMethod.ENCODE
    )
    language: str | None = None
    container: str | None = None


class CodecProfileDto(AtriumModel):
    """`[spec: CodecProfile]`: conditions that apply to one codec, sometimes only in one
    container."""

    type: ladder.CodecKind = ladder.CodecKind.VIDEO
    codec: str | None = None
    container: str | None = None
    conditions: list[ProfileConditionDto] = Field(default_factory=list)
    apply_conditions: list[ProfileConditionDto] = Field(default_factory=list)


class DeviceProfileDto(AtriumModel):
    """`[spec: DeviceProfile]`, narrowed to the five lists a negotiation reads.

    The document a client sends carries more - a name, an identifier, container profiles, a dozen
    DLNA-era fields - and `extra="ignore"` (the base model's) drops them.

    **`SubtitleProfiles` is the fifth, and it arrived at 011 T9.** Until then this docstring said
    "v1 negotiates nothing about subtitles, and a field bound here would be a field somebody
    later assumes is honoured", which was the right rule and is now discharged rather than
    deleted: every entry here is read by `media/decision.py`'s ladder, and every subtitle stream
    of a negotiated source states the delivery method it produced.
    """

    max_streaming_bitrate: int | None = None
    direct_play_profiles: list[DirectPlayProfileDto] = Field(default_factory=list)
    transcoding_profiles: list[TranscodingProfileDto] = Field(default_factory=list)
    codec_profiles: list[CodecProfileDto] = Field(default_factory=list)
    subtitle_profiles: list[SubtitleProfileDto] = Field(default_factory=list)


class PlaybackInfoDto(AtriumModel):
    """`[spec: PlaybackInfoDto]`: the whole request body, and every property optional.

    The body's Python field names never reach a client. 007 T8 measured what happens when they
    do - a validation failure keyed `{"item_id": ...}`, snake_case on the wire - and
    `compat/errors.py` keys a body's refusal by the **route parameter**, which is why the
    parameter below is spelled `playbackInfoDto` after the reference's own.
    """

    user_id: WireGuid | None = None
    max_streaming_bitrate: int | None = None
    start_time_ticks: WireTicks | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    max_audio_channels: int | None = None
    media_source_id: str | None = None
    live_stream_id: str | None = None
    device_profile: DeviceProfileDto | None = None
    enable_direct_play: bool = True
    enable_direct_stream: bool = True
    enable_transcoding: bool = True
    allow_video_stream_copy: bool = True
    allow_audio_stream_copy: bool = True
    auto_open_live_stream: bool = False
    always_burn_in_subtitle_when_transcoding: bool = False


class PlaybackInfoResponse(AtriumModel):
    """`[spec: PlaybackInfoResponse]`. Three properties, and two of them are usually absent.

    Measured: a successful negotiation is `{"MediaSources": [...], "PlaySessionId": "..."}` with
    **no `ErrorCode` key at all** - the global null suppression of behaviours section 1.7 - and the
    empty-source answer is `{"MediaSources": [], "ErrorCode": "NoCompatibleStream"}` with no
    `PlaySessionId` `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`.
    """

    media_sources: list[media_info.MediaSourceInfo] = Field(default_factory=list)
    play_session_id: str | None = None
    error_code: str | None = None


# ------------------------------------------------------------------------------------------------
# The body as the ladder's vocabulary
# ------------------------------------------------------------------------------------------------


def _conditions(stated: list[ProfileConditionDto]) -> tuple[ladder.ProfileCondition, ...]:
    return tuple(
        ladder.ProfileCondition(
            condition=one.condition,
            property=one.property,
            value=one.value or "",
            is_required=one.is_required,
        )
        for one in stated
    )


def _as_int(value: str | None) -> int | None:
    """The reference's `int.TryParse`: a number, or nothing at all, and never an error."""
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


def profile_of(stated: DeviceProfileDto) -> ladder.DeviceProfile:
    """A posted device profile as the values the ladder reads.

    Entries about photos, subtitles and lyrics are dropped here rather than refused above: they
    are legitimate parts of a client's profile and say nothing about audio or video playback.
    """
    return ladder.DeviceProfile(
        max_streaming_bitrate=stated.max_streaming_bitrate,
        direct_play_profiles=tuple(
            ladder.DirectPlayProfile(
                container=one.container,
                audio_codec=one.audio_codec,
                video_codec=one.video_codec,
                type=NEGOTIABLE[one.type],
            )
            for one in stated.direct_play_profiles
            if one.type in NEGOTIABLE
        ),
        transcoding_profiles=tuple(
            ladder.TranscodingProfile(
                container=one.container,
                audio_codec=one.audio_codec,
                video_codec=one.video_codec,
                type=NEGOTIABLE[one.type],
                protocol=one.protocol,
                context=one.context,
                max_audio_channels=_as_int(one.max_audio_channels),
                min_segments=one.min_segments or None,
                segment_length=one.segment_length or None,
                break_on_non_key_frames=one.break_on_non_key_frames,
                enable_audio_vbr_encoding=one.enable_audio_vbr_encoding,
                enable_subtitles_in_manifest=one.enable_subtitles_in_manifest,
            )
            for one in stated.transcoding_profiles
            if one.type in NEGOTIABLE
        ),
        codec_profiles=tuple(
            ladder.CodecProfile(
                type=one.type,
                codec=one.codec,
                container=one.container,
                conditions=_conditions(one.conditions),
                apply_conditions=_conditions(one.apply_conditions),
            )
            for one in stated.codec_profiles
        ),
        subtitle_profiles=tuple(
            ladder.SubtitleProfile(
                format=one.format,
                method=one.method,
                language=one.language,
                container=one.container,
            )
            for one in stated.subtitle_profiles
        ),
    )


def _switches(body: PlaybackInfoDto, *, names_this_source: bool) -> ladder.Switches:
    """The body's own flags, and the two ceilings beside them.

    `AudioStreamIndex` is applied **only where `MediaSourceId` names this source**, which is the
    reference's own condition and is observable: a body naming an audio index without naming a
    source is answered with the default track `[source:
    Jellyfin.Api/Helpers/MediaInfoHelper.cs:206-211 @ v10.11.11]`, `[probe: manual requests via
    tools/_probe.py, Jellyfin 10.11.11, 2026-08-29]`. **`SubtitleStreamIndex` is on the same
    line of the same condition**, so 011 joins it as a field rather than as a branch: an index
    posted without the source id is dropped in silence and the answer states no default track
    `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.

    `AlwaysBurnInSubtitleWhenTranscoding` is **not** behind that gate - it is set on the options
    outside the block that reads it - and it is read only by the delivery address (011 plan
    section 6.3).
    """
    return ladder.Switches(
        enable_direct_play=body.enable_direct_play,
        enable_direct_stream=body.enable_direct_stream,
        enable_transcoding=body.enable_transcoding,
        allow_video_stream_copy=body.allow_video_stream_copy,
        allow_audio_stream_copy=body.allow_audio_stream_copy,
        max_streaming_bitrate=body.max_streaming_bitrate,
        max_audio_channels=body.max_audio_channels,
        audio_stream_index=body.audio_stream_index if names_this_source else None,
        subtitle_stream_index=body.subtitle_stream_index if names_this_source else None,
        always_burn_in_subtitle_when_transcoding=body.always_burn_in_subtitle_when_transcoding,
    )


def _stored_profile(request: Request) -> DeviceProfileDto | None:
    """The profile this device posted to `/Sessions/Capabilities/Full`, if it posted one.

    Read from the caller's own session - never from a session the body names - because that is
    which device is asking. An API key has no session and therefore no stored profile, which is
    the same "no profile at all" a device that never posted one gets.

    **A stored profile that will not bind is treated as absent rather than as a `500`.** The
    capabilities route stores whatever document arrives, unread (002 section 3.8), so unlike a
    posted body this one has never been through these models - and a client should not be unable
    to negotiate for ever because of one bad token it sent a week ago.
    """
    session_id = getattr(request.state, "session_id", None)
    if session_id is None:
        return None
    with session_scope(get_sessions(request)) as opened:
        session = SessionRepository(opened).by_id(session_id)
    stated = (session.capabilities if session is not None else {}).get(CAPABILITIES_PROFILE)
    if not isinstance(stated, dict):
        return None
    try:
        return DeviceProfileDto.model_validate(stated)
    except ValidationError:
        return None


# ------------------------------------------------------------------------------------------------
# The routes
# ------------------------------------------------------------------------------------------------


def _annotate(
    wire: media_info.MediaSourceInfo,
    inspection: MediaInspection | None,
    decided: ladder.Decision,
    *,
    item_id: str,
    play_session_id: str,
    profile: ladder.DeviceProfile,
    switches: ladder.Switches,
    request: Request,
    start_time_ticks: int | None,
    is_video: bool,
) -> None:
    """Write this negotiation's answer onto one source, in place.

    The `TranscodingUrl` condition is the reference's, not a restatement of the outcome: a source
    that cannot be direct-played and can be produced somehow gets a URL, and everything else gets
    none `[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:310-330 @ v10.11.11]`.
    """
    wire.supports_direct_play = decided.supports_direct_play
    wire.supports_direct_stream = decided.supports_direct_stream
    wire.supports_transcoding = decided.supports_transcoding
    if decided.audio is not None:
        wire.default_audio_stream_index = decided.audio.source_index
    # **Before the early return, because a direct play carries them too.** The reference writes
    # the subtitle answers off the stream description whatever the play method was, so a source
    # the client will read byte for byte still states a delivery method on every subtitle stream
    # `[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:334, 470-492 @ v10.11.11]`,
    # `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
    wire.default_subtitle_stream_index = decided.subtitle_index
    _annotate_subtitles(
        wire,
        decided,
        item_id=item_id,
        api_key=extract_token(request),
        start_time_ticks=start_time_ticks,
    )
    if wire.supports_direct_play or not (wire.supports_transcoding or wire.supports_direct_stream):
        return
    if inspection is None or decided.target is None:  # pragma: no cover - defended, not expected
        return
    wire.transcoding_container = decided.container
    wire.transcoding_sub_protocol = decided.sub_protocol or wire.transcoding_sub_protocol
    wire.transcoding_url = urls.transcoding_url(
        decided,
        inspection,
        profile,
        switches,
        item_id=item_id,
        media_source_id=wire.id,
        play_session_id=play_session_id,
        tag=wire.e_tag,
        api_key=extract_token(request),
        device_id=_device_id(request),
        start_time_ticks=start_time_ticks,
        is_video=is_video,
    )


def _annotate_subtitles(
    wire: media_info.MediaSourceInfo,
    decided: ladder.Decision,
    *,
    item_id: str,
    api_key: str | None,
    start_time_ticks: int | None,
) -> None:
    """The delivery method on every subtitle stream, and an address on the external ones.

    **The address is narrower than the method**: `DeliveryUrl` is written only where the method
    is `External`, because that is the only method whose answer is a URL the client fetches for
    itself - a manifest track is addressed by the manifest, an embedded one by the container it
    is in, and a burned-in one by nothing `[probe: tools/probe_subtitle_negotiation.py, Jellyfin
    10.11.11, 2026-08-30]`.

    `IsExternalUrl` is `false` beside it on every one of them: the alternative branch hands back
    the stream's own path for a source that is not a local file, and v1 has no such source
    `[source: MediaBrowser.Model/Dlna/StreamInfo.cs:1251-1272 @ v10.11.11]`.
    """
    answers = {one.index: one for one in decided.subtitles}
    if not answers:
        return
    start = _subtitle_start_ticks(decided, start_time_ticks)
    for stream in wire.media_streams or ():
        answer = answers.get(stream.index)
        if answer is None:
            continue
        stream.delivery_method = answer.method.value
        if answer.method is not ladder.SubtitleMethod.EXTERNAL:
            continue
        address = (
            f"/Videos/{urls.dashed(item_id)}/{wire.id}"
            f"/Subtitles/{stream.index}/{start}/Stream.{answer.format or ''}"
        )
        stream.delivery_url = f"{address}?ApiKey={api_key}" if api_key else address
        stream.is_external_url = False


def _subtitle_start_ticks(decided: ladder.Decision, start_time_ticks: int | None) -> int:
    """Where a subtitle address starts, which is not always zero.

    011 plan section 6.3 said it is zero for every request this feature can produce. It is zero
    for every **HLS** answer, which forces it so because a playlist preserves timestamps - and it
    is the negotiation's own seek on a progressive transcode, measured: a body carrying
    `StartTimeTicks` against an `http` transcoding target answers
    `.../Subtitles/9/6000000000/Stream.vtt` `[source:
    MediaBrowser.Model/Dlna/StreamInfo.cs:1179-1181 @ v10.11.11]`, `[probe:
    tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`. The reference's own
    ordering comment says as much - it writes the subtitle addresses *after* the start position
    is set, on purpose.

    The third input is the transcoding profile's `CopyTimestamps`, which this server binds
    nowhere and which is `false` for every profile it can read.
    """
    if decided.sub_protocol == urls.HLS:
        return 0
    if decided.outcome in (ladder.Outcome.REMUX, ladder.Outcome.TRANSCODE):
        return start_time_ticks or 0
    return 0


def _device_id(request: Request) -> str | None:
    """Which device is asking, for the URL's `DeviceId`. An API key names none, and the reference
    then leaves the parameter out rather than sending an empty one."""
    info = client_info(request)
    return info.device_id if info is not None and info.device_id else None


def _found(
    request: Request, caller: User, item_id: str, user_id: str | None
) -> tuple[HydratedItem, User, dict[str, LibraryContext]]:
    """The item, the user it was resolved for, and the library roots its paths are rebuilt from.

    Resolved through the same query `GET /Items/{itemId}` uses, so an unknown item and an
    invisible one are the identical `404` - measured on this route too, and byte-identical there.
    """
    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, user_id)
        repository = ItemQueryRepository(opened)
        page = repository.run(ItemQuery(user=target, ids=(item_id,), limit=1, count=False))
        if not page.items:
            raise NotFoundError
        return page.items[0], target, library_context(LibraryRepository(opened))


def _root_of(found: HydratedItem, libraries: Mapping[str, LibraryContext]) -> str | None:
    """The library root a source's absolute path is rebuilt from - `item_dto`'s rule, shared: a
    library may declare several and the schema does not record which one a file came from."""
    library_id = found.item.library_id
    library = None if library_id is None else libraries.get(library_id)
    return library.roots[0] if library is not None and library.roots else None


def _negotiation(
    request: Request,
    caller: User,
    item_id: str,
    body: PlaybackInfoDto,
    *,
    profile: DeviceProfileDto | None,
) -> PlaybackInfoResponse:
    """One answer, for one item, for one client. Both routes end here.

    `profile` is `None` for the `GET`, for a `POST` whose body carries none and whose device
    stored none, and for an API key - and in every one of those the ladder answers direct play
    with the flags the *account* carries, which is the intrinsic shape of a source that was never
    negotiated about (spec section 3.3 rule 1). Intrinsic is not unconditional: the reference
    writes the caller's permissions onto every static source before any profile work, one
    permission per media kind, so a seat denied video transcoding is answered
    `SupportsTranscoding: false` here with no profile and `true` with one.
    """
    found, target, libraries = _found(request, caller, item_id, body.user_id)
    is_video = found.item.type in VIDEO_TYPES
    sources = media_info.sources_for(
        found.item, found.probes, _root_of(found, libraries), is_video=is_video
    )
    # Positional against the sources, padded where a part was never inspected - the same rule
    # `sources_for` follows, so index *n* is part *n* on both sides.
    probes: list[MediaInspection | None] = [
        found.probes[index] if index < len(found.probes) else None for index in range(len(sources))
    ]

    if body.media_source_id:
        wanted = body.media_source_id.lower()
        kept = [
            (wire, probe)
            for wire, probe in zip(sources, probes, strict=True)
            if wire.id.lower() == wanted
        ]
        sources = [wire for wire, _ in kept]
        probes = [probe for _, probe in kept]

    if not sources:
        # The one place an ErrorCode exists, and it arrives without a PlaySessionId: the reference
        # issues one only where there is something to play.
        return PlaybackInfoResponse(media_sources=[], error_code=NO_COMPATIBLE_STREAM)

    play_session_id = new_id()
    decided_against = None if profile is None else profile_of(profile)
    policy = policy_of(target)
    for wire, inspection in zip(sources, probes, strict=True):
        if inspection is None:
            # Nothing has opened this file, so there is nothing to negotiate against and the
            # source keeps the intrinsic flags `sources_for` gave it. A rescan is what fixes it -
            # but the account's own permissions are not part of what a rescan would learn, and the
            # reference writes them onto every static source whether or not anything negotiated
            # `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:355-372 @
            # v10.11.11]`. Same rule as the ladder's rule 1, because it is the same moment.
            wire.supports_transcoding = ladder.unnegotiated_transcoding(policy, is_video=is_video)
            wire.supports_direct_stream = not is_video or policy.enable_remuxing
            continue
        switches = _switches(
            body, names_this_source=(body.media_source_id or "").lower() == wire.id.lower()
        )
        decided = ladder.decide(
            inspection,
            decided_against,
            switches,
            policy,
            is_video=is_video,
        )
        _annotate(
            wire,
            inspection,
            decided,
            item_id=found.id,
            play_session_id=play_session_id,
            profile=decided_against or ladder.DeviceProfile(),
            switches=switches,
            request=request,
            start_time_ticks=body.start_time_ticks,
            is_video=is_video,
        )
    return PlaybackInfoResponse(media_sources=sources, play_session_id=play_session_id)


@router.post("/Items/{itemId}/PlaybackInfo")
async def get_posted_playback_info(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    playbackInfoDto: PlaybackInfoDto | None = None,  # noqa: N803
) -> PlaybackInfoResponse:
    """`GetPostedPlaybackInfo` `[spec: GetPostedPlaybackInfo]`: the negotiation.

    **The body is optional**, measured: a `POST` with no body at all is a `200` and not a
    validation failure, because the reference binds this parameter with `EmptyBodyBehavior.Allow`
    `[source: Jellyfin.Api/Controllers/MediaInfoController.cs:135 @ v10.11.11]`, `[probe: manual
    requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-29]`. A body that is present and
    unreadable is still the validation `400`.

    The obsolete query forms of these parameters are not accepted. The reference marks every one
    of them `[ParameterObsolete]` and no analysed client sends them (Principle VI).
    """
    body = playbackInfoDto or PlaybackInfoDto()
    profile = body.device_profile or _stored_profile(request)
    return _negotiation(request, caller, itemId, body, profile=profile)


@router.get("/Items/{itemId}/PlaybackInfo")
async def get_playback_info(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803
    userId: WireGuid | None = None,  # noqa: N803
) -> PlaybackInfoResponse:
    """`GetPlaybackInfo` `[spec: GetPlaybackInfo]`: the profile-less variant.

    There is nothing to negotiate against, so the sources come back with their intrinsic
    capabilities and no `TranscodingUrl` - and a `PlaySessionId` is still issued, which is what
    makes this route usable as the first hop of a direct play. It does **not** consult the
    device's stored capabilities: measured on the same session that answered the `POST` with a
    transcode `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    return _negotiation(request, caller, itemId, PlaybackInfoDto(user_id=userId), profile=None)


__all__ = [
    "NO_COMPATIBLE_STREAM",
    "CodecProfileDto",
    "DeviceProfileDto",
    "DirectPlayProfileDto",
    "PlaybackInfoDto",
    "PlaybackInfoResponse",
    "ProfileConditionDto",
    "ProfileType",
    "TranscodingProfileDto",
    "profile_of",
    "router",
]
