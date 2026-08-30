# SPDX-License-Identifier: GPL-3.0-or-later
"""What this server will do with one file for one client, decided from values alone.

The ladder of [008 spec section 3.3](../../../specs/008-playback-negotiation-and-delivery/spec.md)
lives here and nowhere else: direct play, then remux, then transcode, stopping at the first
success, with "not playable" as the fourth answer rather than an error. Every route that
negotiates or delivers reads this module's answer; none of them re-derives a rung, so a rule that
is wrong here is wrong once.

**Pure.** No request, no database, no process, no clock - a `MediaInspection`, a `DeviceProfile`,
the request's switches and the user's policy go in, and a `Decision` comes out. That is what lets
the whole of the feature's semantics be a table
(`tests/unit/test_media_decision.py`), and `tests/unit/test_import_directions.py` holds the
module to it.

**The measured shape of the ladder**, all of it from one battery
`[probe: tools/probe_decision_ladder.py, Jellyfin 10.11.11, 2026-08-29]`:

* **An absent profile and an empty one are opposites.** No `DeviceProfile` in the request means
  the client has not told us anything, and the answer is direct play with every capability flag
  true. An empty `DeviceProfile` **object** is a profile whose lists are empty, which permits
  nothing: the answer is every flag false, no URL, and no error. The spec's rule 1 read "empty or
  absent" and only the absent half had been measured.
* **`TranscodeReasons` says why *direct play* failed**, and nothing else. It does not separate a
  remux from a transcode: a profile that rejects a codec for direct play while its transcoding
  profile accepts it answers `VideoCodecNotSupported` over a stream that is copied. What decides
  copy-versus-encode is the *transcoding* profile `[source:
  MediaBrowser.Model/Dlna/StreamBuilder.cs GetVideoTranscodeProfile @ v10.11.11]`.
* **A direct-play failure with nothing to blame is `DirectPlayError`.** Both a profile listing no
  direct-play entry at all and a request carrying `EnableDirectPlay: false` answer with that one
  reason, which is the enum's "Errors" group appearing on an ordinary negotiation.
* **The reasons arrive in flag-value order**, not declaration order. `TranscodeReason` is a
  `[Flags]` enum whose members are declared in groups, so `VideoRangeTypeNotSupported` (1 << 24)
  is written above `VideoLevelNotSupported` (1 << 7) and arrives below it.
* **A frame-rate ceiling is compared at 32-bit precision**, so a client that declares exactly the
  rate it read off the wire is answered with a transcode. See `domain/media.py`'s
  `narrow_to_single`.
* **`SupportsTranscoding` is not about the answer.** It is true whenever this profile leaves the
  server something it could produce, direct play included: an accepting profile with a
  transcoding target answers all three flags true, and the same profile with no transcoding
  target answers direct play with `SupportsTranscoding: false`.

**Of the request's switches, `EnableDirectPlay` is honoured and `EnableTranscoding` is ignored**
(spec section 3.2). The second is declared on `Switches` and never read - deliberately, because
the reference does not read it either, and a field that is absent invites a later reader to add
the branch.

**The user's policy barely gates anything.** A single denied permission changes nothing; a video
item loses `SupportsTranscoding` only when video transcoding, audio transcoding **and** remuxing
are all denied at once, and an audio item turns on the audio permission alone
`[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28; source:
Jellyfin.Api/Helpers/MediaInfoHelper.cs:278-293 @ v10.11.11]`. Even the all-denied answer is
flags, never an error.

**The subtitle half arrived at 011 T9**, and it is not a second ladder beside this one - it hangs
off the same answer, because the reference resolves a delivery method *per subtitle stream* from
the play method this ladder chose `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1442-1590 @
v10.11.11]`, `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`. Two
things about it are worth knowing before reading `subtitle_answers`:

* **There is an answer for every subtitle stream**, not only for the selected one, and the answer
  is `Encode` wherever nothing the client declared fits - which is most of a real track list under
  a text-only profile, and every stream of a profile that declares no subtitle handling at all.
  Nothing is ever burned in here; `Encode` is a word this server says exactly where the reference
  says it (011 spec section 3.3).
* **The selected track feeds back into direct play**, which neither 011 document said. A source
  whose *named* subtitle track resolves - at direct play, against the source's own container - to
  anything but `External`, `Embed` or `Drop` is refused direct play with
  `SubtitleCodecNotSupported`, so the same file and the same profile direct-play with no index
  named and transcode with one. Measured on both sides of the discrimination: an external `vtt`
  profile keeps direct play for a `subrip` track and loses it for an image track, and an index
  naming no stream costs nothing at all.

See specs/008-playback-negotiation-and-delivery/plan.md sections 5 and 6.2, and
specs/011-subtitle-delivery/plan.md section 6.3.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, NamedTuple

from atrium.domain.media import InspectedStream, MediaInspection, StreamKind
from atrium.media.info import is_text_format, is_text_subtitle, supports_external_stream

# ------------------------------------------------------------------------------------------------
# What the ladder answers
# ------------------------------------------------------------------------------------------------


class Outcome(Enum):
    """Exactly the four rows of spec section 3.3's table.

    `REMUX` and `TRANSCODE` are one shape on the wire - both are a `TranscodingUrl` - and what
    separates them is what the session does per frame. `NONE` is the refusal, and it is capability
    flags rather than an error: a `4xx` would be read as a transport failure, and what a client
    branches on is the flags.
    """

    DIRECT_PLAY = "direct_play"
    REMUX = "remux"
    TRANSCODE = "transcode"
    NONE = "none"


class StreamAction(Enum):
    """What happens to one elementary stream: it survives, or it is produced again."""

    COPY = "copy"
    ENCODE = "encode"


class SubtitleMethod(Enum):
    """How one subtitle track would reach this client, in the reference's own five spellings.

    `[source: MediaBrowser.Model/Dlna/SubtitleDeliveryMethod.cs @ v10.11.11]`

    **`DROP` is a member no answer carries.** The ladder's two embedded passes can only return an
    `Embed` profile and its two external passes only an `External` or an `Hls` one, so `Drop`
    exists in the vocabulary a client may *declare* and never in the vocabulary this server
    answers - and a declared `Drop` entry is therefore a track the ladder falls past. It is here
    because a client sends it, not because anything here produces it.

    The value is the wire spelling, which is what `MediaStream.DeliveryMethod` carries and what a
    delivery address spells `SubtitleMethod=`. Reading one back is case-insensitive on the
    reference and refusing one is not: `hls`, `HLS` and the ordinal `3` all bind where `banana`
    is a `400` `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
    """

    ENCODE = "Encode"
    EMBED = "Embed"
    EXTERNAL = "External"
    HLS = "Hls"
    DROP = "Drop"


#: The three methods a **direct play** survives. Anything else on the *selected* track refuses
#: direct play with `SubtitleCodecNotSupported` `[source:
#: MediaBrowser.Model/Dlna/StreamBuilder.cs:1297-1309 @ v10.11.11]`.
DIRECT_PLAYABLE_SUBTITLE_METHODS: Final = frozenset(
    {SubtitleMethod.DROP, SubtitleMethod.EXTERNAL, SubtitleMethod.EMBED}
)

#: The sub-protocol whose manifest can carry a subtitle track, spelled as the wire spells it.
HLS_SUB_PROTOCOL: Final = "hls"

#: What a stream with no language of its own is matched as. `[source:
#: MediaBrowser.Model/Dlna/SubtitleProfile.cs:48-61 @ v10.11.11]`
UNDECLARED_LANGUAGE: Final = "und"

#: The two spellings a track cannot be converted *from*, and also the two it cannot be converted
#: *to*. One list, read twice, which is the reference's own shape `[source:
#: MediaBrowser.Model/Entities/MediaStream.cs:773-805 @ v10.11.11]`.
UNCONVERTIBLE_SUBTITLE_FORMATS: Final = frozenset({"ass", "ssa"})

#: The containers a *transcode* may embed a subtitle into, and the ones it may not - asked in
#: that order, because a container in neither list is refused `[source:
#: MediaBrowser.Model/Dlna/StreamBuilder.cs:1522-1538 @ v10.11.11]`.
EMBED_REFUSING_CONTAINERS: Final = "ts,mpegts,mp4"
EMBED_ADMITTING_CONTAINERS: Final = "mkv,matroska"


@dataclass(frozen=True, slots=True)
class SubtitleProfile:
    """One entry of a client's `SubtitleProfiles`: a format, and how it will take that format.

    `language` is a comma-separated list read by the same three rules as every other list here,
    with an empty one admitting every language. `container` is read by the embedded passes alone.
    """

    format: str | None = None
    method: SubtitleMethod = SubtitleMethod.ENCODE
    language: str | None = None
    container: str | None = None


@dataclass(frozen=True, slots=True)
class SubtitleAnswer:
    """What would happen to one subtitle stream, for this client, on this negotiation.

    `format` is the matched profile's declared format, and on the `Encode` fallback it is the
    **stream's own codec** rather than nothing - which is what makes the fallback a statement
    about the track rather than an absence.
    """

    index: int
    method: SubtitleMethod
    format: str | None


class TranscodeReason(Enum):
    """Why direct play was refused, valued at the reference's own flag bits.

    **The value is the bit, because the bit is the order.** The reference renders this as a
    `[Flags]` enum, and .NET writes the set members in ascending value order rather than in
    declaration order - which matters because the declaration is grouped by subject and the two
    orders genuinely disagree `[source: MediaBrowser.Model/Session/TranscodeReason.cs @
    v10.11.11]`, `[probe: tools/probe_decision_ladder.py, Jellyfin 10.11.11, 2026-08-29]`.

    All twenty-seven members are here even though a v1 negotiation can produce a dozen: the set is
    the vocabulary a client may parse out of a `TranscodeReasons` query parameter, and a member
    left out would be one this project could never explain.
    """

    CONTAINER_NOT_SUPPORTED = 1 << 0
    VIDEO_CODEC_NOT_SUPPORTED = 1 << 1
    AUDIO_CODEC_NOT_SUPPORTED = 1 << 2
    SUBTITLE_CODEC_NOT_SUPPORTED = 1 << 3
    AUDIO_IS_EXTERNAL = 1 << 4
    SECONDARY_AUDIO_NOT_SUPPORTED = 1 << 5
    VIDEO_PROFILE_NOT_SUPPORTED = 1 << 6
    VIDEO_LEVEL_NOT_SUPPORTED = 1 << 7
    VIDEO_RESOLUTION_NOT_SUPPORTED = 1 << 8
    VIDEO_BIT_DEPTH_NOT_SUPPORTED = 1 << 9
    VIDEO_FRAMERATE_NOT_SUPPORTED = 1 << 10
    REF_FRAMES_NOT_SUPPORTED = 1 << 11
    ANAMORPHIC_VIDEO_NOT_SUPPORTED = 1 << 12
    INTERLACED_VIDEO_NOT_SUPPORTED = 1 << 13
    AUDIO_CHANNELS_NOT_SUPPORTED = 1 << 14
    AUDIO_PROFILE_NOT_SUPPORTED = 1 << 15
    AUDIO_SAMPLE_RATE_NOT_SUPPORTED = 1 << 16
    AUDIO_BIT_DEPTH_NOT_SUPPORTED = 1 << 17
    CONTAINER_BITRATE_EXCEEDS_LIMIT = 1 << 18
    VIDEO_BITRATE_NOT_SUPPORTED = 1 << 19
    AUDIO_BITRATE_NOT_SUPPORTED = 1 << 20
    UNKNOWN_VIDEO_STREAM_INFO = 1 << 21
    UNKNOWN_AUDIO_STREAM_INFO = 1 << 22
    DIRECT_PLAY_ERROR = 1 << 23
    VIDEO_RANGE_TYPE_NOT_SUPPORTED = 1 << 24
    VIDEO_CODEC_TAG_NOT_SUPPORTED = 1 << 25
    STREAM_COUNT_EXCEEDS_LIMIT = 1 << 26

    @property
    def wire_name(self) -> str:
        """The spelling a client reads out of `TranscodeReasons`, from the member's own name."""
        return "".join(word.capitalize() for word in self.name.split("_"))


@dataclass(frozen=True, slots=True)
class StreamPlan:
    """One output stream: whether it is produced again, and inside what limits.

    **Every ceiling here is already clamped to the source** - `min(profile, source)`, spec section
    3.4's "limits, not targets". Nothing is ever upscaled, up-sampled or given more bits than it
    arrived with, so a 720p source under a 1080p ceiling plans 720p (AC-9).

    The *URL* a client sees does not carry these numbers: the reference passes the profile's own
    ceiling through unclamped, because only the frame rate is seeded from the stream before being
    minimised against the condition `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:949,
    ApplyTranscodingConditions @ v10.11.11]`, `[probe: tools/probe_decision_ladder.py, Jellyfin
    10.11.11, 2026-08-29]`. These are what to produce; the URL says what was permitted.
    """

    source_index: int
    action: StreamAction
    codec: str | None
    """The target. The source's own codec on a copy, and the transcoding profile's first named
    codec on an encode - which is the same codec when only a ceiling, not the codec, was refused."""

    width: int | None = None
    height: int | None = None
    bitrate: int | None = None
    channels: int | None = None
    sample_rate: int | None = None

    bit_depth: int | None = None
    """The video depth the output is produced at, clamped like every other ceiling.

    Added at 008 T7, because it is the one condition the ladder was already *reading* -
    `VideoBitDepth` is in `_REASON_FOR` and refuses direct play - and the plan had nowhere to
    carry the answer to. Without it a client that rejects ten-bit h264 is answered with a
    transcode that hands it ten-bit h264 anyway, since libx264 keeps the source's depth: a
    refusal at the client's decoder, far from the cause, which is exactly what spec section 3.4
    says the feature exists to prevent (AC-8)."""


@dataclass(frozen=True, slots=True)
class Decision:
    """One answer, for one source and one profile.

    `reasons` is empty on both ends of the ladder and populated in between: a direct-play answer
    has nothing to explain, and a refusal has no URL to carry an explanation on.
    """

    outcome: Outcome
    reasons: tuple[str, ...]
    container: str | None
    """The negotiated output container - `"ts"` - and `None` when nothing is produced."""

    sub_protocol: str | None
    """`"hls"` or `"http"`, and `None` when nothing is produced. The wire's own default for a
    source with no answer is `"http"`, which `media/info.py` already declares."""

    video: StreamPlan | None
    audio: StreamPlan | None

    supports_transcoding: bool
    """**A claim about what this profile leaves producible, not about this answer.** A profile the
    source satisfies still answers `true` here when a transcoding target exists, and `false` when
    none does - measured on the same accepting profile with and without one."""

    subtitles: tuple[SubtitleAnswer, ...] = ()
    """One answer per subtitle stream of the source, in stream order - **not** one for the
    selected track (011 spec section 3.2, measured on a source with six of them).

    Empty when the client sent no profile at all, because the reference annotates nothing then:
    a `GET /PlaybackInfo` and a `POST` with no device profile both answer subtitle streams with
    no `DeliveryMethod` on any of them, where a `POST` carrying a profile with an *empty*
    `SubtitleProfiles` list answers `Encode` on every one. The distinction is the same one rule 1
    already draws for the ladder itself."""

    subtitle_index: int | None = None
    """The track the request named, restated - even when it names no stream, and even when it is
    `-1`, both of which come back as themselves.

    `None` when the request named none, and **v1 proposes no default**: the reference's own
    answer for that case is the source's stated default, which is computed from a per-user
    subtitle mode and language preference 011 section 2 excludes, and a `SubtitleMode: None` user
    is answered no default at all (011 spec section 3.3, OQ-12)."""

    target: TranscodingProfile | None = None
    """The client's own entry this answer was built from, `None` when nothing is produced.

    Carried because the `TranscodingUrl` repeats five of its fields back to the client -
    `MinSegments`, `SegmentLength`, `BreakOnNonKeyFrames`, `TranscodingMaxAudioChannels`,
    `EnableAudioVbrEncoding` - and re-deriving *which* entry was chosen in order to read them
    would be a second copy of `_choose_target`'s ranking, which is the drift this module exists
    to prevent. `container` and `sub_protocol` are this entry's too, and stay declared because
    every reader wants those two and few want the rest.
    """

    @property
    def supports_direct_play(self) -> bool:
        return self.outcome is Outcome.DIRECT_PLAY

    @property
    def supports_direct_stream(self) -> bool:
        """The mirror, and it is the whole rule.

        The reference disables its direct-stream path outright - "direct-stream http streaming is
        currently broken" - so the flag has answered direct play's value on every measured
        response `[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:251-268 @ v10.11.11]`,
        `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28]`. A client that
        branches on it is branching on direct play, and resurrecting a distinction no reference
        answer draws would be the delta.
        """
        return self.outcome is Outcome.DIRECT_PLAY


# ------------------------------------------------------------------------------------------------
# What a client says it can do
# ------------------------------------------------------------------------------------------------


class MediaKind(Enum):
    """Which half of a profile an entry belongs to."""

    AUDIO = "Audio"
    VIDEO = "Video"


class CodecKind(Enum):
    """Which stream a codec profile constrains. `VideoAudio` is the audio track *of a video
    item*, which is a different set of conditions from an audio item's own."""

    AUDIO = "Audio"
    VIDEO = "Video"
    VIDEO_AUDIO = "VideoAudio"


class ConditionType(Enum):
    """The five comparisons a profile may state. `[source:
    MediaBrowser.Model/Dlna/ProfileConditionType.cs @ v10.11.11]`"""

    EQUALS = "Equals"
    NOT_EQUALS = "NotEquals"
    LESS_THAN_EQUAL = "LessThanEqual"
    GREATER_THAN_EQUAL = "GreaterThanEqual"
    EQUALS_ANY = "EqualsAny"


class ConditionProperty(Enum):
    """Everything a condition may be about. `[source:
    MediaBrowser.Model/Dlna/ProfileConditionValue.cs @ v10.11.11]`

    The whole vocabulary is declared because a client may send any of it and a member missing here
    would be a profile this server cannot parse. Not all of them are *decidable*: see
    `_REASON_FOR`, where the ones the reference itself leaves unmapped are absent.
    """

    AUDIO_CHANNELS = "AudioChannels"
    AUDIO_BITRATE = "AudioBitrate"
    AUDIO_PROFILE = "AudioProfile"
    WIDTH = "Width"
    HEIGHT = "Height"
    HAS_64_BIT_OFFSETS = "Has64BitOffsets"
    PACKET_LENGTH = "PacketLength"
    VIDEO_BIT_DEPTH = "VideoBitDepth"
    VIDEO_BITRATE = "VideoBitrate"
    VIDEO_FRAMERATE = "VideoFramerate"
    VIDEO_LEVEL = "VideoLevel"
    VIDEO_PROFILE = "VideoProfile"
    VIDEO_TIMESTAMP = "VideoTimestamp"
    IS_ANAMORPHIC = "IsAnamorphic"
    REF_FRAMES = "RefFrames"
    NUM_AUDIO_STREAMS = "NumAudioStreams"
    NUM_VIDEO_STREAMS = "NumVideoStreams"
    IS_SECONDARY_AUDIO = "IsSecondaryAudio"
    VIDEO_CODEC_TAG = "VideoCodecTag"
    IS_AVC = "IsAvc"
    IS_INTERLACED = "IsInterlaced"
    AUDIO_SAMPLE_RATE = "AudioSampleRate"
    AUDIO_BIT_DEPTH = "AudioBitDepth"
    VIDEO_RANGE_TYPE = "VideoRangeType"
    NUM_STREAMS = "NumStreams"


#: What a failed condition is blamed on. **A property absent from this map fails silently**: the
#: reference maps eight of them to no reason at all, so a profile whose `IsAvc` condition does not
#: hold is answered with direct play anyway `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs
#: GetTranscodeReasonForFailedCondition @ v10.11.11]`. Reproduced rather than tidied: a client
#: sending such a condition today gets direct play, and blaming it would take that away.
_REASON_FOR: Final[dict[ConditionProperty, TranscodeReason]] = {
    ConditionProperty.AUDIO_BITRATE: TranscodeReason.AUDIO_BITRATE_NOT_SUPPORTED,
    ConditionProperty.AUDIO_BIT_DEPTH: TranscodeReason.AUDIO_BIT_DEPTH_NOT_SUPPORTED,
    ConditionProperty.AUDIO_CHANNELS: TranscodeReason.AUDIO_CHANNELS_NOT_SUPPORTED,
    ConditionProperty.AUDIO_PROFILE: TranscodeReason.AUDIO_PROFILE_NOT_SUPPORTED,
    ConditionProperty.AUDIO_SAMPLE_RATE: TranscodeReason.AUDIO_SAMPLE_RATE_NOT_SUPPORTED,
    ConditionProperty.HEIGHT: TranscodeReason.VIDEO_RESOLUTION_NOT_SUPPORTED,
    ConditionProperty.IS_ANAMORPHIC: TranscodeReason.ANAMORPHIC_VIDEO_NOT_SUPPORTED,
    ConditionProperty.IS_INTERLACED: TranscodeReason.INTERLACED_VIDEO_NOT_SUPPORTED,
    ConditionProperty.IS_SECONDARY_AUDIO: TranscodeReason.SECONDARY_AUDIO_NOT_SUPPORTED,
    ConditionProperty.NUM_STREAMS: TranscodeReason.STREAM_COUNT_EXCEEDS_LIMIT,
    ConditionProperty.REF_FRAMES: TranscodeReason.REF_FRAMES_NOT_SUPPORTED,
    ConditionProperty.VIDEO_BIT_DEPTH: TranscodeReason.VIDEO_BIT_DEPTH_NOT_SUPPORTED,
    ConditionProperty.VIDEO_BITRATE: TranscodeReason.VIDEO_BITRATE_NOT_SUPPORTED,
    ConditionProperty.VIDEO_CODEC_TAG: TranscodeReason.VIDEO_CODEC_TAG_NOT_SUPPORTED,
    ConditionProperty.VIDEO_FRAMERATE: TranscodeReason.VIDEO_FRAMERATE_NOT_SUPPORTED,
    ConditionProperty.VIDEO_LEVEL: TranscodeReason.VIDEO_LEVEL_NOT_SUPPORTED,
    ConditionProperty.VIDEO_PROFILE: TranscodeReason.VIDEO_PROFILE_NOT_SUPPORTED,
    ConditionProperty.VIDEO_RANGE_TYPE: TranscodeReason.VIDEO_RANGE_TYPE_NOT_SUPPORTED,
    ConditionProperty.WIDTH: TranscodeReason.VIDEO_RESOLUTION_NOT_SUPPORTED,
}


@dataclass(frozen=True, slots=True)
class ProfileCondition:
    """One comparison a client asks the server to honour.

    `is_required` defaults to true, as the reference's own parameterless constructor does, and it
    decides only what happens when the value is **unknown**: an unknown value satisfies a
    condition that is not required and fails one that is `[source:
    MediaBrowser.Model/Dlna/ProfileCondition.cs, ConditionProcessor.cs @ v10.11.11]`.
    """

    condition: ConditionType
    property: ConditionProperty
    value: str
    is_required: bool = True


@dataclass(frozen=True, slots=True)
class DirectPlayProfile:
    """A container the client can open, with the codecs it can decode inside it.

    Each of the three strings is a **comma-separated list**, empty meaning "anything" and a
    leading `-` meaning "anything but these" (`_csv_contains`).
    """

    container: str | None = None
    audio_codec: str | None = None
    video_codec: str | None = None
    type: MediaKind = MediaKind.VIDEO


@dataclass(frozen=True, slots=True)
class TranscodingProfile:
    """A shape the client will accept the server producing.

    The last five fields decide nothing in the ladder and are carried anyway, because the client
    reads them back out of the `TranscodingUrl` it is handed: the reference copies them from the
    chosen target onto the stream it describes `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs
    SetStreamInfoOptionsFromTranscodingProfile @ v10.11.11]`. `max_audio_channels` arrives as a
    string on the wire and is `None` here when it is not a number, which is the reference's own
    `int.TryParse` and not leniency invented for it.
    """

    container: str
    audio_codec: str | None = None
    video_codec: str | None = None
    type: MediaKind = MediaKind.VIDEO
    protocol: str = "http"
    context: str = "Streaming"
    max_audio_channels: int | None = None
    min_segments: int | None = None
    segment_length: int | None = None
    break_on_non_key_frames: bool = False
    enable_audio_vbr_encoding: bool = True
    enable_subtitles_in_manifest: bool = False
    """Read by nothing here and copied into the delivery address, which is the whole of its
    life: the route that address names cannot read the parameter it is given (011 spec section
    3.4). Bound because a client that parses the address it was handed is why OQ-8 made the
    anatomy exact."""


@dataclass(frozen=True, slots=True)
class CodecProfile:
    """Conditions that apply to one codec, optionally only inside one container.

    `apply_conditions` gates the whole entry: they are evaluated first, and when any of them does
    not hold the `conditions` are not consulted at all. That is how a client says "h264 above
    level 4.1 must also be 8-bit" without constraining every h264 stream.
    """

    type: CodecKind
    codec: str | None = None
    container: str | None = None
    conditions: tuple[ProfileCondition, ...] = ()
    apply_conditions: tuple[ProfileCondition, ...] = ()


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Everything the client said about itself.

    **An instance of this with empty lists is not the same as no profile at all.** This one
    permits nothing; the absence of one means the client has not spoken, and only the absence is
    answered with direct play. `decide` takes `None` for that case.
    """

    max_streaming_bitrate: int | None = None
    direct_play_profiles: tuple[DirectPlayProfile, ...] = ()
    transcoding_profiles: tuple[TranscodingProfile, ...] = ()
    codec_profiles: tuple[CodecProfile, ...] = ()
    subtitle_profiles: tuple[SubtitleProfile, ...] = ()


@dataclass(frozen=True, slots=True)
class Switches:
    """The request body's own `Enable*` and `Allow*` flags, and the ceilings beside them."""

    enable_direct_play: bool = True
    enable_direct_stream: bool = True
    enable_transcoding: bool = True
    """**Declared and never read.** The reference ignores it - a profile that forces a transcode
    answers with a `TranscodingUrl` whether or not the body forbade one `[probe:
    tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28]` - and the field is kept so that
    a reader who looks for it finds this sentence instead of adding the branch."""

    allow_video_stream_copy: bool = True
    allow_audio_stream_copy: bool = True
    max_streaming_bitrate: int | None = None
    """Wins over the profile's own when both are given. `[source:
    MediaBrowser.Model/Dlna/MediaOptions.cs:120-142 @ v10.11.11]`"""

    max_audio_channels: int | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    """Read on the same condition as `audio_stream_index`: only where the body also named this
    media source. Both are dropped in silence otherwise `[source:
    Jellyfin.Api/Helpers/MediaInfoHelper.cs:206-211 @ v10.11.11]`."""

    always_burn_in_subtitle_when_transcoding: bool = False
    """**Read by the address and by nothing else**, which is its whole effect on a negotiation:
    it keeps `SubtitleStreamIndex` in a `TranscodingUrl` whose delivery method is `External` -
    where the parameter is otherwise dropped - and appends its own lower-camel-cased flag to the
    end of that address `[source: MediaBrowser.Model/Dlna/StreamInfo.cs:960,
    Jellyfin.Api/Helpers/MediaInfoHelper.cs:325-328 @ v10.11.11]`, `[probe:
    tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`. It changes no delivery
    method and burns nothing in here: 011 section 2 excludes burn-in and this server never
    produces one."""


@dataclass(frozen=True, slots=True)
class PlaybackPolicy:
    """The three permissions that shape a negotiation, out of the account's whole policy."""

    enable_video_transcoding: bool = True
    enable_audio_transcoding: bool = True
    enable_remuxing: bool = True


#: The defaults a request that says nothing carries.
EVERY_SWITCH_ON: Final = Switches()
#: The policy of an account that is allowed all three steps.
EVERY_PERMISSION: Final = PlaybackPolicy()


# ------------------------------------------------------------------------------------------------
# Comma-separated membership, which is three rules rather than one
# ------------------------------------------------------------------------------------------------


def _csv_contains(listed: str | None, value: str | None) -> bool:
    """Whether a profile's comma-separated list admits a value that may itself be a list.

    Three rules the reference states and one it only implements `[source:
    MediaBrowser.Model/Extensions/ContainerHelper.cs @ v10.11.11]`:

    * an empty or absent list admits everything;
    * a list beginning with `-` is an exclusion list, and the whole answer inverts;
    * the **value** is split on commas too, so the stored container `mov,mp4,m4a,3gp,3g2,mj2`
      matches a profile that lists only `mp4`;
    * and an empty value is admitted by nothing - it is refused before the empty-list rule is
      reached, so even a list that admits everything refuses it.

    Members are compared case-insensitively and are not trimmed, because the reference does not
    trim them: `"mp4, mkv"` genuinely does not list `mkv`.
    """
    excluded = False
    if listed is not None and listed.startswith("-"):
        excluded, listed = True, listed[1:]
    if not value:
        return excluded
    if not listed:
        return True
    wanted = {one.lower() for one in value.split(",") if one}
    found = any(one.lower() in wanted for one in listed.split(",") if one)
    return found != excluded


def _first_codec(listed: str | None) -> str | None:
    """The codec a client named first, which is the one an encode targets."""
    for one in (listed or "").split(","):
        if one:
            return one
    return None


# ------------------------------------------------------------------------------------------------
# Conditions
# ------------------------------------------------------------------------------------------------

Value = int | float | str | bool | None


def _satisfied(condition: ProfileCondition, value: Value) -> bool:
    """Whether one condition holds for one measured value.

    An **unknown** value - a Matroska stream with no bitrate, a container with no codec tag -
    satisfies a condition that is not required and fails one that is. A stated value that cannot
    be read as the property's type fails, which is the reference's parse-failure path and is the
    safe direction: it costs a re-encode rather than an output the client cannot decode.
    """
    if value is None or (isinstance(value, str) and not value):
        return not condition.is_required
    if isinstance(value, bool):
        return _satisfied_flag(condition, value)
    if isinstance(value, str):
        return _satisfied_text(condition, value)
    return _satisfied_number(condition, float(value))


def _satisfied_flag(condition: ProfileCondition, value: bool) -> bool:
    """Only equality is defined for a flag; anything else is a profile this server cannot read."""
    stated = condition.value.strip().lower()
    if stated not in ("true", "false"):
        return False
    expected = stated == "true"
    if condition.condition is ConditionType.EQUALS:
        return value == expected
    if condition.condition is ConditionType.NOT_EQUALS:
        return value != expected
    return False


def _satisfied_text(condition: ProfileCondition, value: str) -> bool:
    """Case-insensitive, and ordering comparisons are meaningless rather than false-by-accident.

    The reference raises on a `LessThanEqual` against a string, which surfaces as a 500 on the
    negotiation. Atrium answers the request instead and treats the condition as unmet, which costs
    the client a transcode where the reference would have cost it the whole response.
    """
    if condition.condition is ConditionType.EQUALS_ANY:
        return value.lower() in {one.lower() for one in condition.value.split("|")}
    if condition.condition is ConditionType.EQUALS:
        return value.lower() == condition.value.lower()
    if condition.condition is ConditionType.NOT_EQUALS:
        return value.lower() != condition.value.lower()
    return False


def _satisfied_number(condition: ProfileCondition, value: float) -> bool:
    if condition.condition is ConditionType.EQUALS_ANY:
        return any(
            candidate == value
            for candidate in (_number(one) for one in condition.value.split("|"))
            if candidate is not None
        )
    stated = _number(condition.value)
    if stated is None:
        return False
    if condition.condition is ConditionType.EQUALS:
        return value == stated
    if condition.condition is ConditionType.NOT_EQUALS:
        return value != stated
    if condition.condition is ConditionType.LESS_THAN_EQUAL:
        return value <= stated
    return value >= stated


def _number(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def _applies(entry: CodecProfile, codec: str | None, container: str | None) -> bool:
    """Whether a codec profile is about this codec in this container."""
    return _csv_contains(entry.container, container) and _csv_contains(entry.codec, codec)


def _failures(
    profile: DeviceProfile,
    kind: CodecKind,
    codec: str | None,
    container: str | None,
    values: dict[ConditionProperty, Value],
) -> set[TranscodeReason]:
    """Every reason this stream fails the profile's conditions, in this container.

    The container is an argument rather than a property of the source because the same conditions
    are asked twice: once about the file as it is, and once about the container a transcode would
    produce.
    """
    found: set[TranscodeReason] = set()
    for entry in profile.codec_profiles:
        if entry.type is not kind or not _applies(entry, codec, container):
            continue
        if not all(
            _satisfied(condition, values.get(condition.property))
            for condition in entry.apply_conditions
        ):
            continue
        for condition in entry.conditions:
            if not _satisfied(condition, values.get(condition.property)):
                reason = _REASON_FOR.get(condition.property)
                if reason is not None:
                    found.add(reason)
    return found


def _video_values(
    source: MediaInspection, stream: InspectedStream
) -> dict[ConditionProperty, Value]:
    """What a video stream answers to each condition property.

    `VideoFramerate` is the **32-bit** reference frame rate, which is the single fact that makes a
    ceiling stated at the rate the wire printed fail (`domain/media.py`). `VideoBitrate` falls
    back to the file's overall bitrate, because a Matroska stream reports none of its own.
    """
    return {
        ConditionProperty.WIDTH: stream.width,
        ConditionProperty.HEIGHT: stream.height,
        ConditionProperty.VIDEO_BIT_DEPTH: stream.bit_depth,
        ConditionProperty.VIDEO_BITRATE: stream.bitrate or source.bitrate,
        ConditionProperty.VIDEO_PROFILE: stream.profile,
        ConditionProperty.VIDEO_LEVEL: stream.level,
        ConditionProperty.VIDEO_FRAMERATE: stream.reference_frame_rate,
        ConditionProperty.VIDEO_CODEC_TAG: stream.codec_tag,
        ConditionProperty.VIDEO_RANGE_TYPE: (
            None if stream.video_range_type is None else stream.video_range_type.value
        ),
        ConditionProperty.IS_ANAMORPHIC: stream.is_anamorphic,
        ConditionProperty.IS_INTERLACED: stream.is_interlaced,
        ConditionProperty.REF_FRAMES: stream.ref_frames,
        ConditionProperty.NUM_STREAMS: len(source.streams),
        ConditionProperty.NUM_VIDEO_STREAMS: sum(
            1 for one in source.streams if one.kind is StreamKind.VIDEO
        ),
        ConditionProperty.NUM_AUDIO_STREAMS: sum(
            1 for one in source.streams if one.kind is StreamKind.AUDIO
        ),
    }


def _audio_values(
    source: MediaInspection, stream: InspectedStream
) -> dict[ConditionProperty, Value]:
    return {
        ConditionProperty.AUDIO_CHANNELS: stream.channels,
        ConditionProperty.AUDIO_BITRATE: stream.bitrate or source.bitrate,
        ConditionProperty.AUDIO_SAMPLE_RATE: stream.sample_rate,
        ConditionProperty.AUDIO_BIT_DEPTH: stream.bit_depth,
        ConditionProperty.AUDIO_PROFILE: stream.profile,
        ConditionProperty.NUM_STREAMS: len(source.streams),
    }


def ceiling(
    profile: DeviceProfile,
    kind: CodecKind,
    codec: str | None,
    container: str | None,
    wanted: ConditionProperty,
) -> float | None:
    """The tightest upper limit the profile states for one property, or None for no limit.

    Only `LessThanEqual` and `Equals` bound an output. `GreaterThanEqual` states a floor, and a
    floor is not something a server that never upscales can honour by producing more - the
    reference does not express it either.

    **Public because the `TranscodingUrl` reads the same limits and reports them unclamped**
    (`media/urls.py`, plan section 6.3). The ladder clamps them against the source and the URL
    does not, so they are two answers from one derivation rather than two derivations - which is
    what stops the number a client is told from drifting from the number it was decided against.
    """
    limits = [
        stated
        for entry in profile.codec_profiles
        if entry.type is kind and _applies(entry, codec, container)
        for condition in entry.conditions
        if condition.property is wanted
        and condition.condition in (ConditionType.LESS_THAN_EQUAL, ConditionType.EQUALS)
        and (stated := _number(condition.value)) is not None
    ]
    return min(limits) if limits else None


def _clamped(limit: float | None, source_value: int | None) -> int | None:
    """`min(profile, source)`, and the source alone when the profile stated no limit.

    Spec section 3.4: ceilings are limits, not targets. A 1080p ceiling over a 720p source plans
    720p, and the sample rate is clamped the same way rather than through the reference's Opus
    ladder - the divergence of behaviours section 3.7, which is honoured here because this is
    where the target number is chosen.
    """
    if limit is None:
        return source_value
    if source_value is None:
        return int(limit)
    return min(source_value, int(limit))


# ------------------------------------------------------------------------------------------------
# The ladder
# ------------------------------------------------------------------------------------------------


def _selected_audio(source: MediaInspection, index: int | None) -> InspectedStream | None:
    """The audio stream this negotiation is about: the one the client named, or the default one."""
    audio = [one for one in source.streams if one.kind is StreamKind.AUDIO]
    if not audio:
        return None
    if index is not None:
        named = next((one for one in audio if one.index == index), None)
        if named is not None:
            return named
    return next((one for one in audio if one.is_default), audio[0])


def _selected_subtitle(source: MediaInspection, index: int | None) -> InspectedStream | None:
    """The subtitle stream this negotiation named, by **wire** index, or `None`.

    Unlike `_selected_audio` there is no fallback: an index naming no subtitle stream selects
    nothing at all, and the reference then resolves no method for a selected track and refuses
    nothing - measured, on an index of 99 and on `-1`, both of which are still restated back to
    the client as the source's default `[probe: tools/probe_subtitle_negotiation.py, Jellyfin
    10.11.11, 2026-08-30]`.
    """
    if index is None:
        return None
    return next(
        (one for one in source.streams if one.kind is StreamKind.SUBTITLE and one.index == index),
        None,
    )


def _supports_language(entry: SubtitleProfile, language: str | None) -> bool:
    """Whether this profile entry admits a stream in this language.

    An entry that names no language admits every one, and a stream that declares none is matched
    as `und` - so a profile listing `und` matches exactly the unlanguaged tracks.
    """
    if not entry.language:
        return True
    return _csv_contains(entry.language, language or UNDECLARED_LANGUAGE)


def _same_spelling(one: str | None, other: str | None) -> bool:
    """Case-insensitive equality with .NET's null rules, which are not Python's.

    `string.Equals(null, null)` is true and `string.Equals(null, "")` is false, so a profile that
    declares no format matches a stream with no codec and nothing else. Reproduced rather than
    collapsed, because the collapsed form would match an empty-string format against a null codec
    on every stream a failed inspection produced.
    """
    if one is None or other is None:
        return one is None and other is None
    return one.lower() == other.lower()


def _convertible_to(stream: InspectedStream, target: str | None) -> bool:
    """Whether this track can be *converted* into that format.

    **Convertibility is not "is text".** A track already in `ass` or `ssa` cannot be converted
    from, and neither can be converted to - so an `ass` track under a `vtt`-only external profile
    reaches the burn-in fallback, which is a real row of a real track list `[source:
    MediaBrowser.Model/Entities/MediaStream.cs:773-805 @ v10.11.11]`.
    """
    if not is_text_subtitle(stream):
        return False
    if (stream.codec or "").lower() in UNCONVERTIBLE_SUBTITLE_FORMATS:
        return False
    return (target or "").lower() not in UNCONVERTIBLE_SUBTITLE_FORMATS


def _embed_supported(container: str | None) -> bool:
    """Whether a **transcode** into this container may embed a subtitle at all.

    Asked in the reference's own order and not as one membership test: `ts`, `mpegts` and `mp4`
    are refused by name, `mkv` and `matroska` are admitted by name, and a container in neither
    list - `mov`, say - is refused for not being admitted rather than for being refused.
    """
    if not container:
        return False
    if _csv_contains(container, EMBED_REFUSING_CONTAINERS):
        return False
    return _csv_contains(container, EMBED_ADMITTING_CONTAINERS)


def _embedded_profile(
    stream: InspectedStream,
    profiles: Sequence[SubtitleProfile],
    *,
    transcoding: bool,
    container: str | None,
    allow_conversion: bool,
) -> SubtitleProfile | None:
    """One pass over the client's entries looking for an `Embed` that fits (steps 1 and 2)."""
    for entry in profiles:
        if entry.method is not SubtitleMethod.EMBED:
            continue
        if not _supports_language(entry, stream.language):
            continue
        if not _csv_contains(entry.container, container):
            continue
        if transcoding and not _embed_supported(container):
            continue
        if allow_conversion:
            if is_text_subtitle(stream) and _convertible_to(stream, entry.format):
                return entry
        elif is_text_subtitle(stream) == is_text_format(entry.format) and _same_spelling(
            entry.format, stream.codec
        ):
            return entry
    return None


def _external_profile(
    stream: InspectedStream,
    profiles: Sequence[SubtitleProfile],
    *,
    transcoding: bool,
    allow_conversion: bool,
) -> SubtitleProfile | None:
    """One pass looking for an `External` or `Hls` entry that fits (steps 3 and 4).

    **The two methods gate on kind differently**, which is the detail that decides what an image
    track can reach: `External` wants the entry's declared format to be the same kind as the
    stream, so an image track matches an image-format external entry; `Hls` wants the stream to
    be text and never looks at the entry's format at all. And `Hls` is skipped outright unless
    the play method is a transcode, which is the mechanical reason a direct-played source
    announces nothing in a manifest.

    The reference asks its encoder here whether it can extract the stream's codec, and that
    answer is an unconditional `true` `[source:
    MediaBrowser.MediaEncoding/Encoder/MediaEncoder.cs:1331-1335 @ v10.11.11]` - so it is not
    reproduced as a branch: a branch there would be a refusal the reference never makes. The
    infinite-stream guard beside it is likewise unreachable, because v1 has no live sources.
    """
    text = is_text_subtitle(stream)
    for entry in profiles:
        if entry.method not in (SubtitleMethod.EXTERNAL, SubtitleMethod.HLS):
            continue
        if entry.method is SubtitleMethod.HLS and not transcoding:
            continue
        if not _supports_language(entry, stream.language):
            continue
        fits = (
            text == is_text_format(entry.format)
            if entry.method is SubtitleMethod.EXTERNAL
            else text
        )
        if not fits:
            continue
        if _same_spelling(stream.codec, entry.format):
            return entry
        if not allow_conversion:
            continue
        if text and supports_external_stream(stream) and _convertible_to(stream, entry.format):
            return entry
    return None


def _subtitle_answer(
    stream: InspectedStream,
    profiles: Sequence[SubtitleProfile],
    *,
    transcoding: bool,
    container: str | None,
    sub_protocol: str | None,
) -> SubtitleAnswer:
    """The reference's four-step ladder for one stream, and its `Encode` fallback.

    The embedded half is skipped entirely for an external stream, and for an HLS transcode -
    there is nothing to embed a sidecar into and a manifest carries its own tracks - so a
    sidecar's answer is always one of the external half's or the fallback.
    """
    if not stream.is_external and not (transcoding and sub_protocol == HLS_SUB_PROTOCOL):
        for allow_conversion in (False, True):
            found = _embedded_profile(
                stream,
                profiles,
                transcoding=transcoding,
                container=container,
                allow_conversion=allow_conversion,
            )
            if found is not None:
                return SubtitleAnswer(stream.index, found.method, found.format)
    for allow_conversion in (False, True):
        found = _external_profile(
            stream, profiles, transcoding=transcoding, allow_conversion=allow_conversion
        )
        if found is not None:
            return SubtitleAnswer(stream.index, found.method, found.format)
    return SubtitleAnswer(stream.index, SubtitleMethod.ENCODE, stream.codec)


def subtitle_answers(
    source: MediaInspection,
    profiles: Sequence[SubtitleProfile],
    *,
    outcome: Outcome,
    container: str | None,
    sub_protocol: str | None,
) -> tuple[SubtitleAnswer, ...]:
    """One answer per subtitle stream, in stream order - the whole of 011 plan section 6.3.

    `container` is the container the answer would be delivered in: the transcoding target's on a
    produced answer and the source's own narrowed to a single name on a direct play, which is
    what the reference hands its own resolution. It is read by the embedded passes and by nothing
    else.

    A **remux** is a transcode here, because it is one there: the reference sets
    `PlayMethod.Transcode` for every answer that is not a direct play, whether or not a stream
    survives the copy.
    """
    transcoding = outcome in (Outcome.REMUX, Outcome.TRANSCODE)
    return tuple(
        _subtitle_answer(
            one,
            profiles,
            transcoding=transcoding,
            container=container,
            sub_protocol=sub_protocol,
        )
        for one in source.streams
        if one.kind is StreamKind.SUBTITLE
    )


def _single_container(
    container: str | None,
    profile: DeviceProfile,
    kind: MediaKind,
    entry: DirectPlayProfile | None,
) -> str | None:
    """A stored demuxer list narrowed to the one name a direct play would report.

    The first member of the list the client can open wins, and a list nothing opens is passed
    through whole `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs
    NormalizeMediaSourceFormatIntoSingleContainer @ v10.11.11]`. **Not the same rule as
    `media/info.py`'s `source_container`**, which is a listing's answer and lets the file's own
    extension win: this one is the negotiation's, and it reads the client's profile.

    Narrowed against the matched direct-play entry alone where there is one, which is what the
    reference passes when it builds the answer, and against every entry of the kind otherwise.
    """
    if not container or "," not in container:
        return container
    candidates = (entry,) if entry is not None else profile.direct_play_profiles
    for member in container.split(","):
        for one in candidates:
            if one.type is kind and _csv_contains(one.container, member):
                return member
    return container


class DirectPlayCheck(NamedTuple):
    """Whether direct play survives, and - when it does - the entry that admitted it.

    `reasons` is `None` exactly when direct play is not refused, and the entry is then the one
    whose container the answer reports. `None` rather than an empty set, because an **empty set
    of reasons is reachable while direct play still fails**: a profile that lists no direct-play
    entry has nothing to complain about and still cannot direct play, and the reference calls
    that `DirectPlayError`. Collapsing the two would answer direct play to a profile that permits
    none.
    """

    entry: DirectPlayProfile | None
    reasons: set[TranscodeReason] | None


def _direct_play_reasons(
    source: MediaInspection,
    profile: DeviceProfile,
    video: InspectedStream | None,
    audio: InspectedStream | None,
    subtitle: InspectedStream | None,
    max_bitrate: int | None,
    *,
    is_video: bool,
) -> DirectPlayCheck:
    """Why direct play is refused, and the entry that admitted it when it is not.

    One `DirectPlayProfile` has to admit the container **and** both codecs; the entry that gets
    furthest - fewest complaints - is the one whose reasons are reported, so a profile listing
    four containers does not answer with four copies of the same complaint. On top of that the
    codec conditions have to hold and the source has to fit inside the streaming bitrate.

    **And the selected subtitle track is a complaint like any other.** The reference resolves its
    delivery method here too - at direct play, against the source's own stored container, with no
    sub-protocol - and adds `SubtitleCodecNotSupported` to *every* entry's failures when the
    answer is not external, embedded or dropped `[source:
    MediaBrowser.Model/Dlna/StreamBuilder.cs:1297-1309 @ v10.11.11]`. So a track the client can
    take as a separate file keeps its direct play and one it can only be shown by burning in
    loses it, on the same file and the same profile
    `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
    """
    kind = MediaKind.VIDEO if is_video else MediaKind.AUDIO
    entries = [one for one in profile.direct_play_profiles if one.type is kind]
    shared: set[TranscodeReason] = set()
    if subtitle is not None:
        chosen = _subtitle_answer(
            subtitle,
            profile.subtitle_profiles,
            transcoding=False,
            container=source.container,
            sub_protocol=None,
        )
        if chosen.method not in DIRECT_PLAYABLE_SUBTITLE_METHODS:
            shared.add(TranscodeReason.SUBTITLE_CODEC_NOT_SUPPORTED)
    if is_video and video is not None:
        shared |= _failures(
            profile, CodecKind.VIDEO, video.codec, source.container, _video_values(source, video)
        )
    if audio is not None:
        shared |= _failures(
            profile,
            CodecKind.VIDEO_AUDIO if is_video else CodecKind.AUDIO,
            audio.codec,
            source.container,
            _audio_values(source, audio),
        )
    if max_bitrate is not None and (source.bitrate or 0) > max_bitrate:
        shared.add(TranscodeReason.CONTAINER_BITRATE_EXCEEDS_LIMIT)

    best: set[TranscodeReason] | None = None
    for entry in entries:
        found = set(shared)
        if not _csv_contains(entry.container, source.container):
            found.add(TranscodeReason.CONTAINER_NOT_SUPPORTED)
        if is_video and video is not None and not _csv_contains(entry.video_codec, video.codec):
            found.add(TranscodeReason.VIDEO_CODEC_NOT_SUPPORTED)
        if audio is not None and not _csv_contains(entry.audio_codec, audio.codec):
            found.add(TranscodeReason.AUDIO_CODEC_NOT_SUPPORTED)
        if not found:
            return DirectPlayCheck(entry, None)
        if best is None or len(found) < len(best):
            best = found
    return DirectPlayCheck(None, best if best is not None else set())


def _plan_video(
    source: MediaInspection,
    profile: DeviceProfile,
    target: TranscodingProfile,
    stream: InspectedStream,
    max_bitrate: int | None,
    switches: Switches,
) -> StreamPlan:
    """What happens to the video stream inside the negotiated container.

    Copied when the transcoding profile names its codec and every condition holds there too -
    which is how a file whose audio alone was refused costs an audio encode and not a video one
    (spec section 3.4, AC-7). Otherwise re-encoded, to the first codec the client listed, inside
    ceilings that never exceed the source.
    """
    values = _video_values(source, stream)
    copyable = (
        switches.allow_video_stream_copy
        and _csv_contains(target.video_codec, stream.codec)
        and not _failures(profile, CodecKind.VIDEO, stream.codec, target.container, values)
        # A cap the whole file already exceeds cannot be met by copying: the video stream is the
        # bulk of the bits, so it is the one that comes down. Copying everything here would ship
        # an output above the ceiling it was negotiated against, which is what AC-8 forbids.
        and (max_bitrate is None or (source.bitrate or 0) <= max_bitrate)
    )
    if copyable:
        return StreamPlan(
            source_index=stream.index,
            action=StreamAction.COPY,
            codec=stream.codec,
            width=stream.width,
            height=stream.height,
            bitrate=stream.bitrate,
            bit_depth=stream.bit_depth,
        )
    codec = _first_codec(target.video_codec)
    bitrate_ceiling = ceiling(
        profile, CodecKind.VIDEO, codec, target.container, ConditionProperty.VIDEO_BITRATE
    )
    if max_bitrate is not None:
        bitrate_ceiling = min(bitrate_ceiling or max_bitrate, max_bitrate)
    return StreamPlan(
        source_index=stream.index,
        action=StreamAction.ENCODE,
        codec=codec,
        width=_clamped(
            ceiling(profile, CodecKind.VIDEO, codec, target.container, ConditionProperty.WIDTH),
            stream.width,
        ),
        height=_clamped(
            ceiling(profile, CodecKind.VIDEO, codec, target.container, ConditionProperty.HEIGHT),
            stream.height,
        ),
        bitrate=_clamped(bitrate_ceiling, stream.bitrate or source.bitrate),
        bit_depth=_clamped(
            ceiling(
                profile,
                CodecKind.VIDEO,
                codec,
                target.container,
                ConditionProperty.VIDEO_BIT_DEPTH,
            ),
            stream.bit_depth,
        ),
    )


def _plan_audio(
    source: MediaInspection,
    profile: DeviceProfile,
    target: TranscodingProfile,
    stream: InspectedStream,
    switches: Switches,
    *,
    is_video: bool,
) -> StreamPlan:
    """What happens to the audio stream, on the same rule and with two more ceilings.

    The encode target is the first codec the client listed **whose conditions this stream could
    meet**, falling back to the first listed - the reference's own preference order, and the
    reason a six-channel FLAC source under a two-channel FLAC profile becomes six-channel AAC
    rather than a downmix `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs
    GetVideoTranscodeProfile @ v10.11.11]`.
    """
    kind = CodecKind.VIDEO_AUDIO if is_video else CodecKind.AUDIO
    values = _audio_values(source, stream)
    copyable = (
        switches.allow_audio_stream_copy
        and _csv_contains(target.audio_codec, stream.codec)
        and not _failures(profile, kind, stream.codec, target.container, values)
    )
    if copyable:
        return StreamPlan(
            source_index=stream.index,
            action=StreamAction.COPY,
            codec=stream.codec,
            bitrate=stream.bitrate,
            channels=stream.channels,
            sample_rate=stream.sample_rate,
        )
    listed = [one for one in (target.audio_codec or "").split(",") if one]
    codec = next(
        (one for one in listed if not _failures(profile, kind, one, target.container, values)),
        _first_codec(target.audio_codec),
    )
    channel_ceiling = ceiling(
        profile, kind, codec, target.container, ConditionProperty.AUDIO_CHANNELS
    )
    if switches.max_audio_channels is not None:
        channel_ceiling = min(
            channel_ceiling or switches.max_audio_channels, switches.max_audio_channels
        )
    return StreamPlan(
        source_index=stream.index,
        action=StreamAction.ENCODE,
        codec=codec,
        bitrate=_clamped(
            ceiling(profile, kind, codec, target.container, ConditionProperty.AUDIO_BITRATE),
            stream.bitrate,
        ),
        channels=_clamped(channel_ceiling, stream.channels),
        sample_rate=_clamped(
            ceiling(profile, kind, codec, target.container, ConditionProperty.AUDIO_SAMPLE_RATE),
            stream.sample_rate,
        ),
    )


def _producible(
    target: TranscodingProfile, video: InspectedStream | None, audio: InspectedStream | None
) -> bool:
    """Whether this target can hold what the source has at all.

    A transcoding profile that names no video codec cannot carry a video stream, and one that
    names no audio codec cannot carry an audio one. Everything else is a matter of copying or
    re-encoding, which is always possible.
    """
    if video is not None and not target.video_codec:
        return False
    return not (audio is not None and not target.audio_codec)


def _may_process(policy: PlaybackPolicy, *, is_video: bool) -> bool:
    """The measured policy gate, and it is deliberately weak.

    A video item needs **all three** permissions denied before the server stops offering to
    produce anything; an audio item turns on the audio permission alone. One denial changes
    nothing, which is the opposite of what the spec's first draft assumed.
    """
    if not is_video:
        return policy.enable_audio_transcoding
    return (
        policy.enable_video_transcoding or policy.enable_audio_transcoding or policy.enable_remuxing
    )


def refused_by_policy(decision: Decision, policy: PlaybackPolicy, *, is_video: bool) -> bool:
    """Whether this account may not have *this* plan produced for it, at delivery.

    Not the negotiation gate above, which is one all-or-nothing question about the item's kind.
    The reference's delivery-time reading is **per stream**: the video stream is forced to a copy
    when `EnableVideoPlaybackTranscoding` is denied and the audio stream when
    `EnableAudioPlaybackTranscoding` is, each against its own permission and each "regardless of
    whether it will be compatible or not" `[source:
    MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:7136-7166 @ v10.11.11]`. Atrium
    refuses the same two steps instead of copying a stream the profile rejected, which is the one
    non-replicated edge of behaviours section 2.21: no client can depend on being handed an
    output it said it could not decode.

    **`EnablePlaybackRemuxing` is not read here, because the reference never reads it at
    delivery** - its only readers are the negotiation's all-three gate and the item DTO. A copy
    is what a denied user is *given*, so refusing one would be inventing an enforcement the
    reference has nowhere.
    """
    if not _may_process(policy, is_video=is_video):
        return True
    forbidden = (
        (decision.video, policy.enable_video_transcoding),
        (decision.audio, policy.enable_audio_transcoding),
    )
    return any(
        plan is not None and plan.action is StreamAction.ENCODE and not permitted
        for plan, permitted in forbidden
    )


NOTHING_PLAYABLE: Final = Decision(
    outcome=Outcome.NONE,
    reasons=(),
    container=None,
    sub_protocol=None,
    video=None,
    audio=None,
    supports_transcoding=False,
)


def decide(
    source: MediaInspection,
    profile: DeviceProfile | None,
    switches: Switches = EVERY_SWITCH_ON,
    policy: PlaybackPolicy = EVERY_PERMISSION,
    *,
    is_video: bool,
) -> Decision:
    """The whole ladder: direct play, remux, transcode, refusal, stopping at the first success.

    `is_video` is the **item's** kind rather than something read off the file, because that is
    what the reference switches on: a music track with cover art carries a video stream and is
    still negotiated as audio. `media/info.py` takes the same flag from the same caller.
    """
    video = source.video if is_video else None
    audio = _selected_audio(source, switches.audio_stream_index)
    # The subtitle half is the *video* builder's alone: the reference's audio builder never reads
    # a subtitle index, so an audio item answers no default subtitle track however the body asks.
    wanted_subtitle = switches.subtitle_stream_index if is_video else None
    subtitle = _selected_subtitle(source, wanted_subtitle)

    if profile is None:
        # Rule 1, and only this half of it: a client that has not described itself is not a
        # client that permits nothing. Every flag true, no URL, nothing to explain - and no
        # delivery method on any subtitle stream, which is measured and is why `subtitles` is
        # empty here rather than a list of fallbacks.
        return Decision(
            outcome=Outcome.DIRECT_PLAY,
            reasons=(),
            container=None,
            sub_protocol=None,
            video=None,
            audio=None,
            supports_transcoding=True,
        )

    max_bitrate = switches.max_streaming_bitrate or profile.max_streaming_bitrate
    kind = MediaKind.VIDEO if is_video else MediaKind.AUDIO
    entry, refused = _direct_play_reasons(
        source, profile, video, audio, subtitle, max_bitrate, is_video=is_video
    )

    def answered(
        outcome: Outcome, container: str | None, sub_protocol: str | None
    ) -> tuple[SubtitleAnswer, ...]:
        return subtitle_answers(
            source,
            profile.subtitle_profiles,
            outcome=outcome,
            container=container,
            sub_protocol=sub_protocol,
        )

    if refused is None and switches.enable_direct_play:
        played = _single_container(source.container, profile, kind, entry)
        return Decision(
            outcome=Outcome.DIRECT_PLAY,
            reasons=(),
            container=None,
            sub_protocol=None,
            video=None,
            audio=None,
            supports_transcoding=_can_produce(source, profile, switches, policy, is_video=is_video),
            subtitles=answered(Outcome.DIRECT_PLAY, played, None),
            subtitle_index=wanted_subtitle,
        )
    # `EnableDirectPlay: false` on a profile the source satisfies, and a profile with no
    # direct-play entry at all, both land on the same one reason: direct play failed with
    # nothing to blame it on.
    reasons = refused or {TranscodeReason.DIRECT_PLAY_ERROR}

    # A refusal still answers a delivery method per stream: the reference's builder returns a
    # stream description whatever the play method was, and the annotation runs off that.
    nothing = Decision(
        outcome=Outcome.NONE,
        reasons=(),
        container=None,
        sub_protocol=None,
        video=None,
        audio=None,
        supports_transcoding=False,
        subtitles=answered(Outcome.NONE, None, None),
        subtitle_index=wanted_subtitle,
    )
    if not _may_process(policy, is_video=is_video):
        return nothing
    chosen = _choose_target(source, profile, video, audio, max_bitrate, switches, is_video=is_video)
    if chosen is None:
        return nothing
    target, video_plan, audio_plan = chosen
    plans = [one for one in (video_plan, audio_plan) if one is not None]
    outcome = (
        Outcome.REMUX
        if plans and all(one.action is StreamAction.COPY for one in plans)
        else Outcome.TRANSCODE
    )
    return Decision(
        outcome=outcome,
        reasons=tuple(one.wire_name for one in sorted(reasons, key=lambda one: one.value)),
        container=target.container,
        sub_protocol=target.protocol,
        video=video_plan,
        audio=audio_plan,
        supports_transcoding=True,
        subtitles=answered(outcome, target.container, target.protocol),
        subtitle_index=wanted_subtitle,
        target=target,
    )


def _choose_target(
    source: MediaInspection,
    profile: DeviceProfile,
    video: InspectedStream | None,
    audio: InspectedStream | None,
    max_bitrate: int | None,
    switches: Switches,
    *,
    is_video: bool,
) -> tuple[TranscodingProfile, StreamPlan | None, StreamPlan | None] | None:
    """The transcoding profile that costs least, with the plan it implies.

    Ranked by how many streams survive a copy, ties broken by the order the client listed them -
    the reference's own preference, and the reason a client whose first target can copy the video
    is never given one that re-encodes it.
    """
    kind = MediaKind.VIDEO if is_video else MediaKind.AUDIO
    best: tuple[int, int, TranscodingProfile, StreamPlan | None, StreamPlan | None] | None = None
    for order, target in enumerate(profile.transcoding_profiles):
        if target.type is not kind or not _producible(target, video, audio):
            continue
        video_plan = (
            None
            if video is None
            else _plan_video(source, profile, target, video, max_bitrate, switches)
        )
        audio_plan = (
            None
            if audio is None
            else _plan_audio(source, profile, target, audio, switches, is_video=is_video)
        )
        encodes = sum(
            1
            for one in (video_plan, audio_plan)
            if one is not None and one.action is StreamAction.ENCODE
        )
        if best is None or (encodes, order) < (best[0], best[1]):
            best = (encodes, order, target, video_plan, audio_plan)
    return None if best is None else (best[2], best[3], best[4])


def _can_produce(
    source: MediaInspection,
    profile: DeviceProfile,
    switches: Switches,
    policy: PlaybackPolicy,
    *,
    is_video: bool,
) -> bool:
    """`SupportsTranscoding` on an answer that did not need it.

    Spec section 3.3: the flag is a claim about *this* negotiation - what the server could produce
    for this profile - and not a boast about the server. Advertising it and failing at delivery
    turns "cannot play this" into a spinner that never resolves.
    """
    if not _may_process(policy, is_video=is_video):
        return False
    video = source.video if is_video else None
    audio = _selected_audio(source, switches.audio_stream_index)
    return (
        _choose_target(source, profile, video, audio, None, switches, is_video=is_video) is not None
    )


__all__ = [
    "DIRECT_PLAYABLE_SUBTITLE_METHODS",
    "EVERY_PERMISSION",
    "EVERY_SWITCH_ON",
    "CodecKind",
    "CodecProfile",
    "ConditionProperty",
    "ConditionType",
    "Decision",
    "DeviceProfile",
    "DirectPlayProfile",
    "MediaKind",
    "Outcome",
    "PlaybackPolicy",
    "ProfileCondition",
    "StreamAction",
    "StreamPlan",
    "SubtitleAnswer",
    "SubtitleMethod",
    "SubtitleProfile",
    "Switches",
    "TranscodeReason",
    "TranscodingProfile",
    "ceiling",
    "decide",
    "refused_by_policy",
    "subtitle_answers",
]
