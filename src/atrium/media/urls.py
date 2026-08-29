# SPDX-License-Identifier: GPL-3.0-or-later
"""The URL a negotiation hands back, spelled exactly the way the reference spells it.

A `TranscodingUrl` is the one answer in this feature that clients **parse** rather than merely
follow: OQ-8 exists because some read the parameters back out of it, and one of the reference's
own delivery routes is on the other end of it. So this module reproduces the anatomy rather than
inventing an equivalent one - the leading `?&`, the PascalCase names, the order, and the two
different spellings of a boolean that live four parameters apart.

`[probe: tools/probe_transcode_decision.py, Jellyfin 10.11.11, 2026-08-28]`
`[source: MediaBrowser.Model/Dlna/StreamInfo.cs ToUrl @ v10.11.11]`

**Every number here is what the profile *permitted*, not what the session will produce.** A
`Height <= 4320` condition against an 816-line source reaches the URL as `MaxHeight=4320`;
`VideoBitrate` is the streaming cap minus the audio's share and stays far above the source's own
rate. Only `MaxFramerate` is clamped, because it alone is seeded from the stream before the
condition is minimised against it `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:949,
ApplyTranscodingConditions @ v10.11.11]`. The clamped numbers - what to *produce* - are the
`StreamPlan`'s, and they are a different set of numbers on the same negotiation (008 T4, plan
section 6.3).

Three spellings that are easy to lose and impossible to guess:

* **`BreakOnNonKeyFrames=True` and `RequireAvc=false` in one URL.** The first is .NET's own
  `bool.ToString()`; the second is lowercased at the call site. Both were measured in the same
  query string.
* **`VideoCodec` is the transcoding profile's list verbatim**, even when the video is being
  copied, while **`AudioCodec` narrows to the single codec** when one can be copied and stays a
  list when none can.
* **The condition triplet is qualified by the *source's* video codec** - `hevc-level`,
  `hevc-videobitdepth`, `hevc-profile` - even where the target codec is `h264`, and the profile
  name is lowercased. The reference strips spaces from these values rather than encoding them,
  which is why `Constrained Baseline` arrives as `constrainedbaseline`.

See specs/008-playback-negotiation-and-delivery/plan.md section 6.3.
"""

from __future__ import annotations

import urllib.parse

from atrium.domain.media import InspectedStream, MediaInspection
from atrium.media.decision import (
    CodecKind,
    ConditionProperty,
    ConditionType,
    Decision,
    DeviceProfile,
    StreamAction,
    StreamPlan,
    Switches,
    ceiling,
)
from atrium.media.info import as_single

#: The sub-protocol whose URL is a playlist rather than a stream.
HLS = "hls"

#: The floor the reference puts under a computed video bitrate, whatever the arithmetic said.
#: `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1116-1119 @ v10.11.11]`
MINIMUM_VIDEO_BITRATE = 64_000


def dashed(identifier: str) -> str:
    """A 32-character identifier in the dashed form these paths spell it in.

    The reference stores its identifiers as GUIDs and writes them into a URL with the default
    format, which is dashed - so the delivery path carries `6d312111-b0c9-f384-75ba-76c8c4064d7a`
    for an item whose `Id` is 32 unbroken characters. `compat/guids.py` accepts both spellings
    coming back, which is what makes the round trip work.
    """
    groups = (
        identifier[:8],
        identifier[8:12],
        identifier[12:16],
        identifier[16:20],
        identifier[20:],
    )
    return "-".join(groups)


def _tightest(
    profile: DeviceProfile,
    kind: CodecKind,
    codecs: list[str],
    container: str | None,
    wanted: ConditionProperty,
) -> float | None:
    """The limit this profile leaves after every target codec's conditions have been applied.

    The reference applies each codec's conditions in turn with `min` semantics, so the number that
    survives is the tightest across the whole target list - not the first codec's.
    `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1061-1071, ApplyTranscodingConditions @
    v10.11.11]`
    """
    candidates: list[str | None] = list(codecs) if codecs else [None]
    limits = [
        found
        for codec in candidates
        if (found := ceiling(profile, kind, codec, container, wanted)) is not None
    ]
    return min(limits) if limits else None


def _listed(value: str | None) -> list[str]:
    return [one for one in (value or "").split(",") if one]


def transcoding_url(
    decision: Decision,
    source: MediaInspection,
    profile: DeviceProfile,
    switches: Switches,
    *,
    item_id: str,
    media_source_id: str,
    play_session_id: str,
    tag: str | None = None,
    api_key: str | None = None,
    device_id: str | None = None,
    start_time_ticks: int | None = None,
    is_video: bool,
) -> str:
    """Where this client should fetch this source instead of fetching the file.

    Raises `ValueError` for a decision that produces nothing: a refusal and a direct play have no
    URL at all, and rendering one for them would advertise a route that answers nothing.
    """
    target = decision.target
    if target is None:
        raise ValueError(
            "a decision with no transcoding target has no TranscodingUrl: direct play and the "
            "refusal are both answered by the capability flags alone (spec section 3.2)"
        )

    parts: list[str] = []

    def add(name: str, value: object) -> None:
        # Percent-encoded with the comma left alone, because a comma is a *separator* in three of
        # these values. The reference encodes nothing at all, which is a difference only a device
        # id or a codec name carrying a reserved character could show - and there the encoded form
        # is the one that survives being parsed back.
        parts.append(f"&{name}={urllib.parse.quote(str(value), safe=',')}")

    video_stream = source.video if is_video else None
    video_codecs = _listed(target.video_codec)
    audio = decision.audio
    copied_audio = audio if audio is not None and audio.action is StreamAction.COPY else None
    audio_codecs = (
        [copied_audio.codec]
        if copied_audio is not None and copied_audio.codec
        else _listed(target.audio_codec)
    )
    audio_kind = CodecKind.VIDEO_AUDIO if is_video else CodecKind.AUDIO

    if device_id:
        add("DeviceId", device_id)
    add("MediaSourceId", media_source_id)
    if video_codecs:
        add("VideoCodec", ",".join(video_codecs))
    if audio_codecs:
        add("AudioCodec", ",".join(audio_codecs))
    if audio is not None:
        add("AudioStreamIndex", audio.source_index)

    audio_bitrate = audio.bitrate if audio is not None else None
    video_bitrate = _video_bitrate(
        profile, switches, target.container, video_codecs, audio_bitrate=audio_bitrate
    )
    if video_bitrate is not None:
        add("VideoBitrate", video_bitrate)
    if audio_bitrate is not None:
        add("AudioBitrate", audio_bitrate)

    # A copied stream reports the rate it already has; a re-encoded one reports the ceiling it was
    # permitted, which is the profile's own number and may sit above the source's.
    sample_rate: float | None = (
        copied_audio.sample_rate
        if copied_audio is not None
        else _tightest(
            profile,
            audio_kind,
            audio_codecs,
            target.container,
            ConditionProperty.AUDIO_SAMPLE_RATE,
        )
    )
    if sample_rate is not None:
        add("AudioSampleRate", int(sample_rate))

    frame_rate = _max_framerate(profile, target.container, video_codecs, video_stream)
    if frame_rate is not None:
        add("MaxFramerate", frame_rate)
    for name, wanted in (
        ("MaxWidth", ConditionProperty.WIDTH),
        ("MaxHeight", ConditionProperty.HEIGHT),
    ):
        limit = _tightest(profile, CodecKind.VIDEO, video_codecs, target.container, wanted)
        if limit is not None:
            add(name, int(limit))

    if decision.sub_protocol == HLS:
        if decision.container:
            add("SegmentContainer", decision.container)
        if target.segment_length:
            add("SegmentLength", target.segment_length)
        if target.min_segments:
            add("MinSegments", target.min_segments)
        # Unconditional, and spelled the way .NET spells a boolean: `True`, four parameters above
        # a `RequireAvc=false` that is lowercased at its own call site.
        add("BreakOnNonKeyFrames", _dotnet_bool(target.break_on_non_key_frames))
    elif start_time_ticks:
        # The seek belongs to the URL only where there is no playlist: an HLS client seeks by
        # asking for a segment, and the reference writes this parameter in the other branch.
        add("StartTimeTicks", start_time_ticks)

    add("PlaySessionId", play_session_id)
    if api_key:
        add("ApiKey", api_key)
    if _requires(profile, ConditionProperty.IS_ANAMORPHIC):
        add("RequireNonAnamorphic", _dotnet_bool(True))
    if target.max_audio_channels is not None:
        add("TranscodingMaxAudioChannels", target.max_audio_channels)
    add("RequireAvc", _lowercase_bool(_requires(profile, ConditionProperty.IS_AVC)))
    add("EnableAudioVbrEncoding", _lowercase_bool(target.enable_audio_vbr_encoding))
    if tag:
        add("Tag", tag)

    for name, value in _stream_options(video_stream, copied_audio):
        add(name, value)

    if decision.reasons:
        add("TranscodeReasons", ",".join(decision.reasons))

    prefix = "videos" if is_video else "audio"
    if decision.sub_protocol == HLS:
        path = f"/{prefix}/{dashed(item_id)}/master.m3u8?"
    else:
        suffix = f".{decision.container}" if decision.container else ""
        path = f"/{prefix}/{dashed(item_id)}/stream{suffix}?"
    return path + "".join(parts)


def _video_bitrate(
    profile: DeviceProfile,
    switches: Switches,
    container: str,
    video_codecs: list[str],
    *,
    audio_bitrate: int | None,
) -> int | None:
    """What the profile left for the video, which is the cap minus what the audio took.

    Not the source's rate and not the plan's: a 120 Mbit cap over a 2 Mbit file reaches the URL as
    `VideoBitrate=119552000` once a 448 kbit audio track is subtracted. With no cap stated at all
    the number is whatever ceiling the profile's own conditions left, and absent when they left
    none. `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1105-1120 @ v10.11.11]`
    """
    stated = _tightest(
        profile, CodecKind.VIDEO, video_codecs, container, ConditionProperty.VIDEO_BITRATE
    )
    cap = switches.max_streaming_bitrate or profile.max_streaming_bitrate
    if cap is None:
        return None if stated is None else int(stated)
    available = cap - (audio_bitrate or 0)
    current = available if stated is None else int(stated)
    return max(min(available, current), MINIMUM_VIDEO_BITRATE)


def _max_framerate(
    profile: DeviceProfile,
    container: str,
    video_codecs: list[str],
    video_stream: InspectedStream | None,
) -> int | float | None:
    """The one ceiling that is clamped to the source, printed the way the wire prints a rate.

    It is seeded from the stream and then minimised against the condition, which is the asymmetry
    the rest of this module exists to respect: every other ceiling here is the profile's own.
    """
    rate = None if video_stream is None else video_stream.reference_frame_rate
    limit = _tightest(
        profile, CodecKind.VIDEO, video_codecs, container, ConditionProperty.VIDEO_FRAMERATE
    )
    if rate is None:
        return None if limit is None else as_single(limit)
    return as_single(rate if limit is None else min(rate, limit))


def _requires(profile: DeviceProfile, wanted: ConditionProperty) -> bool:
    """Whether any codec profile insists on this flag being true.

    `IsAvc Equals true` and `IsAvc NotEquals false` both mean "must be AVC", and the reference
    reads them that way - one parameter for two spellings of one requirement.
    `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1802-1822 @ v10.11.11]`

    `IsAnamorphic` is read by the same two rules and produces `RequireNonAnamorphic`, which reads
    backwards - a profile stating `IsAnamorphic Equals true` asks the server *not* to produce one.
    Reproduced rather than corrected: it is the reference's own reading, and a client that stated
    the condition gets what it gets there.
    """
    for entry in profile.codec_profiles:
        for condition in entry.conditions:
            if condition.property is not wanted:
                continue
            stated = condition.value.strip().lower()
            if stated == "true" and condition.condition is ConditionType.EQUALS:
                return True
            if stated == "false" and condition.condition is ConditionType.NOT_EQUALS:
                return True
    return False


def _stream_options(
    video_stream: InspectedStream | None, copied_audio: StreamPlan | None
) -> list[tuple[str, str]]:
    """The qualified options, in the order the reference writes them into its dictionary.

    Qualified by the **source's** video codec rather than by the target's, which is visible in a
    URL whose `VideoCodec=h264` carries `hevc-level=120` beside it. The audio three appear only
    where the audio stream is copied, and `audiochannels` is qualified by the *video* codec -
    which reads like a mistake and is what the reference does.
    `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:948-1030 @ v10.11.11]`
    """
    qualifier = None if video_stream is None else video_stream.codec
    found: list[tuple[str, str]] = []
    if video_stream is not None and qualifier:
        if video_stream.level is not None:
            found.append((f"{qualifier}-level", str(video_stream.level)))
        if video_stream.bit_depth is not None:
            found.append((f"{qualifier}-videobitdepth", str(video_stream.bit_depth)))
        if video_stream.profile:
            found.append((f"{qualifier}-profile", _stripped(video_stream.profile)))
    if copied_audio is None:
        return found
    if qualifier and copied_audio.channels is not None:
        found.append((f"{qualifier}-audiochannels", str(copied_audio.channels)))
    return found


def _stripped(value: str) -> str:
    """Lowercased, with the spaces removed rather than encoded - `Constrained Baseline`'s fate."""
    return value.replace(" ", "").lower()


def _dotnet_bool(value: bool) -> str:
    return "True" if value else "False"


def _lowercase_bool(value: bool) -> str:
    return "true" if value else "false"


__all__ = ["HLS", "MINIMUM_VIDEO_BITRATE", "dashed", "transcoding_url"]
