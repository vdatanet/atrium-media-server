# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Audio/{itemId}/universal`: the client states constraints, the server decides.

The third audio controller upstream and a third module here, for plan section 3's reason. What
makes it a task of its own rather than a third route in `api/audio.py` is that it is the only
delivery route that **negotiates**: the `stream` pair is told what to produce, and this one is
told what the client can play and works the rest out. The parameter set is therefore synthesised
into a device profile and run through the same `media/decision.py` ladder every other answer in
this feature comes from (plan section 6.6) - so a `/universal` answer and a `PlaybackInfo`
answer about the same file and the same constraints cannot disagree.

**Three things here are deliberate divergences, each measured before it was decided.**

* **The output sample rate is the stated ceiling.** The reference answers a
  `maxAudioSampleRate=22050` request at 24 000 Hz, because the five-step ladder Opus needs -
  `<=8000, <=12000, <=16000, <=24000, else 48000` - is applied to every codec, so the answer can
  sit *above* what the client declared `[probe: tools/probe_universal_audio.py, Jellyfin
  10.11.11, 2026-08-29]`. Atrium clamps to the ceiling and states it, which costs nothing here
  because `media/decision.py` already plans `min(profile, source)` for every limit (behaviours
  section 3.7, AC-19).
* **A request that names no `audioCodec` is answered with a stream.** The reference answers
  `200` with `Content-Length: 0` and an empty body, and does it whether or not a
  `transcodingContainer` was named - the container resolves correctly and the *codec* does not
  (see `codec_for`). Atrium infers the codec from the transcoding container instead (behaviours
  section 3.8).
* **`enableRedirection` binds and never fires.** The `302` needs a source that is remote over
  HTTP, direct-playable, and a user holding `EnableRemoteMedia`, all at once `[source:
  Jellyfin.Api/Controllers/UniversalAudioController.cs:175 @ v10.11.11]`; a library file is
  protocol `File`, so every v1 answer is proxied bytes with a `200`, measured (AC-21).

**And this is the one delivery route that requires a token.** The four `stream` routes accept
every mechanism and require none; this one answers the empty `401` to a request carrying nothing
`[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-29]`, which is the split
behaviours section 2.10 records and spec AC-32 states. Its refusals do not match its siblings'
either: an unknown item is problem details here and the third error shape there
(`api/delivery.locate`).

See specs/008-playback-negotiation-and-delivery/spec.md section 3.6 and plan section 6.6.
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import Response

from atrium.api.delivery import (
    CONTAINER_PATTERN,
    inspection_of,
    locate,
    produce,
    source_response,
)
from atrium.api.deps import get_sessions, require_user
from atrium.api.items import effective_user
from atrium.compat.errors import DeliveryProductionError, ItemNotFoundError
from atrium.compat.guids import WireGuid
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import UserRepository
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User
from atrium.media import ffmpeg
from atrium.media.decision import (
    CodecKind,
    CodecProfile,
    ConditionProperty,
    ConditionType,
    DeviceProfile,
    DirectPlayProfile,
    MediaKind,
    Outcome,
    ProfileCondition,
    Switches,
    TranscodingProfile,
    decide,
)
from atrium.media.labels import label_for

router = APIRouter(tags=["UniversalAudio"])

PATH = "/Audio/{itemId}/universal"

#: What the transcoding profile is built with when the client named no container - the
#: reference's own default, and the reason a bare `/universal` transcode is mp3 `[source:
#: Jellyfin.Api/Controllers/UniversalAudioController.cs:298 @ v10.11.11]`.
DEFAULT_TRANSCODING_CONTAINER: Final = "mp3"

#: The protocol value that means "answer a playlist rather than a body". Compared
#: case-insensitively and **not** declared as an enumeration, because the reference does not
#: refuse an unrecognised one: `transcodingProtocol=banana` answers the same progressive body as
#: `http` and `HLS` answers a master playlist, so a typed parameter here would produce a `400`
#: the reference never sends `[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11,
#: 2026-08-29]`, behaviours section 1.12.
HLS_PROTOCOL: Final = "hls"

#: The codec a container carries when the client named none. **The reference's own inference
#: table**, which it applies to the request path's extension rather than to the container
#: `[source: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:667-684 @ v10.11.11]` - see
#: `codec_for` for why that distinction is the whole of behaviours section 3.8.
CONTAINER_CODECS: Final[dict[str, str]] = {
    "ogg": "opus",
    "oga": "opus",
    "ogv": "opus",
    "webm": "opus",
    "webma": "opus",
    "m4a": "aac",
    "m4b": "aac",
    "mp4": "aac",
    "mov": "aac",
    "mkv": "aac",
    "mka": "aac",
    "ts": "mp3",
    "avi": "mp3",
    "flv": "mp3",
    "f4v": "mp3",
    "swf": "mp3",
}

#: What a container with nothing to infer from falls back to, the reference's own answer to an
#: empty string `[source: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:669-673 @
#: v10.11.11]`.
FALLBACK_CODEC: Final = "aac"


def codec_for(container: str | None) -> str:
    """The codec a transcoding container carries when the client named none.

    **This is behaviours section 3.8's divergence, and it is one argument rather than one
    table.** The reference has exactly this inference and feeds it the wrong value: the codec is
    inferred from the part of the *request path* after the last dot, which on
    `/Audio/{itemId}/stream.mp3` is `mp3` and on `/Audio/{itemId}/universal` is the whole path,
    since there is no dot in it at all `[source: Jellyfin.Api/Helpers/StreamingHelpers.cs:71-75,
    src/Jellyfin.Extensions/StringExtensions.cs RightPart @ v10.11.11]`. The path falls through
    the table unchanged, becomes the encoder name, and the invocation dies before its first byte
    - which is the measured `200` with an empty body, reproduced with **and** without a
    `transcodingContainer` (with one, the container was resolved perfectly well and only the
    codec was nonsense) `[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-29]`.

    So Atrium is not inventing a rule: it gives the reference's own table the value the table was
    written for. A client that names `mp3` or nothing at all gets `mp3` on both servers; the
    divergence is only where the client named a transcoding container and no codec, which is
    where the reference sends nothing.

    **`wav` is the one container the reference's table cannot answer**, and 008 T9 is where that
    stops being academic: an unlisted container falls through to its own name, so `wav` in gives
    `wav` out, and there is no encoder called that. `media/ffmpeg.raw_codec_for` supplies the
    missing row rather than editing the transcribed table, which is what keeps the citation above
    honest about what the reference contains.
    """
    named = (container or "").strip().lstrip(".").lower()
    if not named:
        return FALLBACK_CODEC
    inferred = CONTAINER_CODECS.get(named)
    if inferred is not None:
        return inferred
    return ffmpeg.raw_codec_for(named) or named


def direct_play_profiles(container: str | None) -> tuple[DirectPlayProfile, ...]:
    """The `container` parameter read the way the reference reads it: commas, then bars.

    `container=opus,webm|opus,mp3,aac,m4a|aac,flac` is eleven-ish entries, not one: the value is
    split on commas **first**, and each piece is then split on `|` into a container and the
    codecs the client can decode inside it `[source:
    Jellyfin.Api/Controllers/UniversalAudioController.cs:274-287 @ v10.11.11]`. A piece with no
    bar lists no codec, which the ladder reads as "any codec in this container"
    (`_csv_contains`).
    """
    entries = []
    for piece in (container or "").split(","):
        if not piece:
            continue
        parts = [one for one in piece.split("|") if one]
        if not parts:
            continue
        entries.append(
            DirectPlayProfile(
                type=MediaKind.AUDIO,
                container=parts[0],
                audio_codec=",".join(parts[1:]) or None,
            )
        )
    return tuple(entries)


def synthesised_profile(
    container: str | None,
    *,
    transcoding_container: str | None,
    transcoding_protocol: str | None,
    audio_codec: str | None,
    transcoding_audio_channels: int | None,
    max_audio_channels: int | None,
    max_audio_sample_rate: int | None,
    max_audio_bit_depth: int | None,
    audio_bit_rate: int | None,
    break_on_non_key_frames: bool,
    enable_audio_vbr_encoding: bool,
) -> DeviceProfile:
    """The parameter set as a device profile - plan section 6.6, and one deliberate difference.

    **The ceilings are not scoped to a container here, and the reference's are.** Its
    `GetDeviceProfile` builds one codec profile whose container list is the *direct-play*
    containers, which are the containers it will not be transcoding into - so those conditions
    apply to nothing on the transcoding path, and the ceiling reaches the encoder only because
    the controller also passes `maxAudioSampleRate` straight to the streaming request, outside
    the profile entirely `[source:
    Jellyfin.Api/Controllers/UniversalAudioController.cs:305-360, 233-250 @ v10.11.11]`. Atrium
    has one path and it is the profile, so an unscoped condition is what reproduces the
    observable: a request naming `container=ogg`, `transcodingContainer=flac` and
    `maxAudioSampleRate=22050` is answered *at a constrained rate* by the reference, which a
    literal transcription of its profile could not do `[probe: tools/probe_universal_audio.py,
    Jellyfin 10.11.11, 2026-08-29]`.
    """
    target = (transcoding_container or DEFAULT_TRANSCODING_CONTAINER).strip().lstrip(".").lower()
    conditions = _conditions(
        (ConditionProperty.AUDIO_SAMPLE_RATE, max_audio_sample_rate),
        (ConditionProperty.AUDIO_BIT_DEPTH, max_audio_bit_depth),
        (ConditionProperty.AUDIO_CHANNELS, max_audio_channels),
        (ConditionProperty.AUDIO_BITRATE, audio_bit_rate),
    )
    return DeviceProfile(
        direct_play_profiles=direct_play_profiles(container),
        transcoding_profiles=(
            TranscodingProfile(
                container=target,
                audio_codec=audio_codec or codec_for(target),
                type=MediaKind.AUDIO,
                protocol=_protocol(transcoding_protocol),
                max_audio_channels=transcoding_audio_channels,
                break_on_non_key_frames=break_on_non_key_frames,
                enable_audio_vbr_encoding=enable_audio_vbr_encoding,
            ),
        ),
        codec_profiles=(
            (CodecProfile(type=CodecKind.AUDIO, conditions=conditions),) if conditions else ()
        ),
    )


def _conditions(
    *stated: tuple[ConditionProperty, int | None],
) -> tuple[ProfileCondition, ...]:
    """A ceiling per stated parameter, `LessThanEqual` and not required.

    `is_required=False` is the reference's own value for every one of these `[source:
    Jellyfin.Api/Controllers/UniversalAudioController.cs:309-346 @ v10.11.11]`, and it decides
    what an **unknown** stream value means: a stream whose bit depth nothing reported satisfies a
    bit-depth ceiling rather than failing it.
    """
    return tuple(
        ProfileCondition(
            condition=ConditionType.LESS_THAN_EQUAL,
            property=wanted,
            value=str(value),
            is_required=False,
        )
        for wanted, value in stated
        if value is not None
    )


def _protocol(stated: str | None) -> str:
    """`hls` or `http`, and everything unrecognised is `http` - measured, not lenience."""
    return HLS_PROTOCOL if (stated or "").strip().lower() == HLS_PROTOCOL else "http"


@router.get(PATH)
async def get_universal_audio_stream(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,  # noqa: N803 - the reference's spellings, throughout
    container: Annotated[str | None, Query()] = None,
    mediaSourceId: Annotated[str | None, Query()] = None,  # noqa: N803
    deviceId: Annotated[str | None, Query()] = None,  # noqa: N803
    userId: WireGuid | None = None,  # noqa: N803
    audioCodec: Annotated[str | None, Query(pattern=CONTAINER_PATTERN)] = None,  # noqa: N803
    maxAudioChannels: Annotated[int | None, Query()] = None,  # noqa: N803
    transcodingAudioChannels: Annotated[int | None, Query()] = None,  # noqa: N803
    maxStreamingBitrate: Annotated[int | None, Query()] = None,  # noqa: N803
    audioBitRate: Annotated[int | None, Query()] = None,  # noqa: N803
    startTimeTicks: Annotated[int | None, Query()] = None,  # noqa: N803
    transcodingContainer: Annotated[  # noqa: N803
        str | None, Query(pattern=CONTAINER_PATTERN)
    ] = None,
    transcodingProtocol: Annotated[str | None, Query()] = None,  # noqa: N803
    maxAudioSampleRate: Annotated[int | None, Query()] = None,  # noqa: N803
    maxAudioBitDepth: Annotated[int | None, Query()] = None,  # noqa: N803
    enableRemoteMedia: Annotated[bool | None, Query()] = None,  # noqa: N803
    enableAudioVbrEncoding: Annotated[bool, Query()] = True,  # noqa: N803
    breakOnNonKeyFrames: Annotated[bool, Query()] = False,  # noqa: N803
    enableRedirection: Annotated[bool, Query()] = True,  # noqa: N803
) -> Response:
    """`GetUniversalAudioStream` `[spec: GetUniversalAudioStream]`.

    **`enableRedirection` and `enableRemoteMedia` are bound and decide nothing**, which is AC-21
    read as an instruction rather than as a gap. The reference's `302` needs all of
    direct-playable, protocol HTTP, remote, and the permission - and v1 has no remote sources at
    all, so the reachable subset of that rule is the proxied `200` this route always answers.
    Declaring them and ignoring them is the honest shape: a client that sends
    `enableRedirection=false` is asking for something it already gets.

    `deviceId` is bound for the same reason it is on the negotiation: 008 T11 keys a production
    session on it, and a parameter the reference declares that this route silently dropped would
    be a difference nobody could see until then.
    """
    target = _target_user(request, caller, userId)
    profile = synthesised_profile(
        container,
        transcoding_container=transcodingContainer,
        transcoding_protocol=transcodingProtocol,
        audio_codec=audioCodec,
        transcoding_audio_channels=transcodingAudioChannels,
        max_audio_channels=maxAudioChannels,
        max_audio_sample_rate=maxAudioSampleRate,
        max_audio_bit_depth=maxAudioBitDepth,
        audio_bit_rate=audioBitRate or maxStreamingBitrate,
        break_on_non_key_frames=breakOnNonKeyFrames,
        enable_audio_vbr_encoding=enableAudioVbrEncoding,
    )
    _visible(request, target, itemId)
    found, absolute = locate(request, itemId, mediaSourceId, absent=ItemNotFoundError)
    inspection = inspection_of(request, found)
    decision = decide(
        inspection,
        profile,
        Switches(
            max_streaming_bitrate=maxStreamingBitrate,
            max_audio_channels=maxAudioChannels,
        ),
        # No policy gate: the delivery half of AC-31 is 008 T13's, which is the task that decides
        # what a session does with the policy it was negotiated under. `api/delivery.py` says the
        # same thing about the `stream` pair, for the same reason.
        is_video=False,
    )
    if decision.outcome is Outcome.DIRECT_PLAY:
        # The measured answer, and the only one `enableRedirection` could ever have changed: the
        # file itself, sized, with `Accept-Ranges: bytes` and a `Range` that is honoured.
        return source_response(request, found, absolute, container=None, absent=ItemNotFoundError)
    if decision.sub_protocol == HLS_PROTOCOL:
        # **Still the refusal after 008 T10, and now for a measured reason rather than a deferred
        # one.** The reference answers this with a master playlist whose single variant URI is a
        # relative `main.m3u8` - which resolves to `/Audio/{itemId}/main.m3u8`, a route
        # `docs/compatibility/surface.yaml` does not carry and no accepted specification
        # describes. T10 serves the video pair; the audio pair would be a surface addition, which
        # is a scope decision and not an implementation detail. Answering the master anyway would
        # advertise a route that answers nothing, which is Principle VI's plausible-looking stub -
        # worse than a refusal, because it looks correct.
        # `[probe: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`
        raise DeliveryProductionError
    produced_container = decision.container or DEFAULT_TRANSCODING_CONTAINER
    return await produce(
        request,
        path=absolute,
        source=inspection,
        decision=decision,
        container=produced_container,
        media_type=label_for(produced_container, found.relative_path),
        start_ticks=startTimeTicks,
    )


def _target_user(request: Request, caller: User, user_id: str | None) -> User:
    with session_scope(get_sessions(request)) as opened:
        return effective_user(UserRepository(opened), caller, user_id)


def _visible(request: Request, target: User, item_id: str) -> None:
    """Refuse an item this user cannot see, in the shape this route was measured to refuse with.

    The reference resolves the item **through the user** here `[source:
    Jellyfin.Api/Controllers/UniversalAudioController.cs:124 @ v10.11.11]`, unlike the `stream`
    pair, which has no user to resolve through at all. So the same query `GET /Items/{itemId}`
    runs answers it, and an unknown item and an invisible one are the identical problem-details
    `404` - byte-identical to `/Items/{itemId}`'s own, measured `[probe:
    tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    with session_scope(get_sessions(request)) as opened:
        page = ItemQueryRepository(opened).run(
            ItemQuery(user=target, ids=(item_id,), limit=1, count=False)
        )
    if not page.items:
        raise ItemNotFoundError


__all__ = [
    "CONTAINER_CODECS",
    "DEFAULT_TRANSCODING_CONTAINER",
    "FALLBACK_CODEC",
    "HLS_PROTOCOL",
    "PATH",
    "codec_for",
    "direct_play_profiles",
    "router",
    "synthesised_profile",
]
