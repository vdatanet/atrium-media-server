# SPDX-License-Identifier: GPL-3.0-or-later
"""The whole ladder, as a table of values.

Every semantic of [008 spec section 3.3](../../specs/008-playback-negotiation-and-delivery/spec.md)
is one function of four arguments, so the findings that cost a probe to learn are asserted here -
once - rather than seven times through seven routes. The rows below are the battery of
`tools/probe_decision_ladder.py` translated into values: same source shape, same profiles, same
answers `[probe: tools/probe_decision_ladder.py, Jellyfin 10.11.11, 2026-08-29]`.

What is deliberately *not* here: HTTP, a database, a process and a clock. A `MediaInspection` and
a `DeviceProfile` go in and a `Decision` comes out, which is what lets the negotiation's rules be
checked without producing a single frame.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atrium.domain.media import (
    InspectedStream,
    MediaInspection,
    StreamKind,
    VideoRange,
    VideoRangeType,
)
from atrium.media.decision import (
    CodecKind,
    CodecProfile,
    ConditionProperty,
    ConditionType,
    Decision,
    DeviceProfile,
    DirectPlayProfile,
    MediaKind,
    Outcome,
    PlaybackPolicy,
    ProfileCondition,
    StreamAction,
    SubtitleMethod,
    SubtitleProfile,
    Switches,
    TranscodeReason,
    TranscodingProfile,
    decide,
    method_named,
)
from atrium.media.info import stream_of

PROBED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

#: The container string the reference stores for every member of the mp4 family - a demuxer
#: *list*, which is why membership has to split both sides (008 spec section 3.1).
MP4_FAMILY = "mov,mp4,m4a,3gp,3g2,mj2"

#: **A real stream's frame rate, chosen for the disagreement it exposes.** This rational is a
#: 32-bit float of 23.975988388061523, which the wire prints as `23.975988` - exactly the
#: `ReferenceFrameRate` the probe measured on the reference's own file. A ceiling stated at the
#: printed number is therefore *below* the value compared against, and a ladder that compared the
#: printed number instead would answer direct play where the reference answers a transcode.
AWKWARD_RATE = "16975/708"
PRINTED_RATE = "23.975988"

SOURCE_BITRATE = 3_069_137


def a_video_stream(**overrides: object) -> InspectedStream:
    values: dict[str, object] = {
        "index": 0,
        "kind": StreamKind.VIDEO,
        "codec": "hevc",
        "profile": "Main 10",
        "level": 120,
        "bit_depth": 10,
        "width": 1920,
        "height": 816,
        "framerate": "24000/1001",
        "average_framerate": AWKWARD_RATE,
        "video_range": VideoRange.SDR,
        "video_range_type": VideoRangeType.SDR,
        "bitrate": 2_600_000,
        "is_default": True,
    }
    values.update(overrides)
    return InspectedStream(**values)  # type: ignore[arg-type]


def an_audio_stream(**overrides: object) -> InspectedStream:
    values: dict[str, object] = {
        "index": 1,
        "kind": StreamKind.AUDIO,
        "codec": "ac3",
        "channels": 6,
        "sample_rate": 48000,
        "bitrate": 448_000,
        "is_default": True,
    }
    values.update(overrides)
    return InspectedStream(**values)  # type: ignore[arg-type]


def a_source(
    *streams: InspectedStream, container: str = MP4_FAMILY, **overrides: object
) -> MediaInspection:
    values: dict[str, object] = {
        "size": 1_500_000_000,
        "mtime_ns": 1_700_000_000_000_000_000,
        "container": container,
        "format_names": container,
        "probed_at": PROBED_AT,
        "runtime_ticks": 51_000_000_000,
        "bitrate": SOURCE_BITRATE,
        "streams": streams or (a_video_stream(), an_audio_stream()),
    }
    values.update(overrides)
    return MediaInspection(**values)  # type: ignore[arg-type]


FILM = a_source()
TRACK = a_source(
    an_audio_stream(index=0, codec="flac", channels=2, sample_rate=96000, bitrate=1_100_000),
    container="flac",
)

#: The transcoding target every real browser profile offers, able to copy either of the film's
#: streams - so a rejection that only concerns the container has a remux available.
TS_HLS = TranscodingProfile(
    container="ts",
    video_codec="hevc,h264",
    audio_codec="ac3,aac",
    protocol="hls",
)
#: The same target with no way to keep the source's video: the rung below.
TS_HLS_H264_ONLY = TranscodingProfile(
    container="ts", video_codec="h264", audio_codec="aac", protocol="hls"
)
#: What a browser actually offers - it will take the source's video and will not take its
#: surround ac3, which is the common case section 3.4 is written about.
TS_HLS_AAC_ONLY = TranscodingProfile(
    container="ts", video_codec="hevc,h264", audio_codec="aac", protocol="hls"
)

PLAYS_EVERYTHING = DirectPlayProfile(container="mp4", video_codec="hevc", audio_codec="ac3")


def a_profile(
    *direct_play: DirectPlayProfile,
    transcoding: tuple[TranscodingProfile, ...] = (TS_HLS,),
    codecs: tuple[CodecProfile, ...] = (),
    max_streaming_bitrate: int | None = None,
) -> DeviceProfile:
    return DeviceProfile(
        max_streaming_bitrate=max_streaming_bitrate,
        direct_play_profiles=direct_play,
        transcoding_profiles=transcoding,
        codec_profiles=codecs,
    )


def a_condition(
    prop: ConditionProperty,
    value: str,
    condition: ConditionType = ConditionType.LESS_THAN_EQUAL,
    *,
    is_required: bool = True,
) -> ProfileCondition:
    return ProfileCondition(
        condition=condition, property=prop, value=value, is_required=is_required
    )


def a_video_codec_profile(*conditions: ProfileCondition) -> CodecProfile:
    return CodecProfile(type=CodecKind.VIDEO, codec="hevc,h264", conditions=conditions)


def answer(profile: DeviceProfile | None, **switches: object) -> Decision:
    return decide(FILM, profile, Switches(**switches), is_video=True)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------
# The rungs: every row the probe measured (AC-1 to AC-6)
# ------------------------------------------------------------------------------------------

RUNGS: list[tuple[str, DeviceProfile | None, Outcome, tuple[str, ...]]] = [
    (
        "AC-1 - no profile at all: the client has not spoken, so nothing is refused",
        None,
        Outcome.DIRECT_PLAY,
        (),
    ),
    (
        "an empty profile object is the opposite of an absent one: it permits nothing",
        DeviceProfile(),
        Outcome.NONE,
        (),
    ),
    (
        "AC-2 - the container and both codecs are listed",
        a_profile(PLAYS_EVERYTHING),
        Outcome.DIRECT_PLAY,
        (),
    ),
    (
        "AC-3 - only the container is refused, and both streams survive the change",
        a_profile(DirectPlayProfile(container="mkv", video_codec="hevc", audio_codec="ac3")),
        Outcome.REMUX,
        ("ContainerNotSupported",),
    ),
    (
        "the reasons do not name the rung: a refused codec the target can still copy is a remux",
        a_profile(DirectPlayProfile(container="mp4", video_codec="h264", audio_codec="ac3")),
        Outcome.REMUX,
        ("VideoCodecNotSupported",),
    ),
    (
        "AC-4 - the same refusal with a target that cannot keep the codec is a transcode",
        a_profile(
            DirectPlayProfile(container="mp4", video_codec="h264", audio_codec="ac3"),
            transcoding=(TS_HLS_H264_ONLY,),
        ),
        Outcome.TRANSCODE,
        ("VideoCodecNotSupported",),
    ),
    (
        "AC-7 - only the audio is refused, so only the audio is produced again",
        a_profile(
            DirectPlayProfile(container="mp4", video_codec="hevc", audio_codec="aac"),
            transcoding=(TS_HLS_AAC_ONLY,),
        ),
        Outcome.TRANSCODE,
        ("AudioCodecNotSupported",),
    ),
    (
        "all three refused at once, and the reasons arrive in flag-value order - over a target "
        "that can still copy both, which is a remux carrying three reasons",
        a_profile(DirectPlayProfile(container="mkv", video_codec="h264", audio_codec="vorbis")),
        Outcome.REMUX,
        ("ContainerNotSupported", "VideoCodecNotSupported", "AudioCodecNotSupported"),
    ),
    (
        "a direct-play failure with nothing to blame: no entry to reject at all",
        a_profile(),
        Outcome.REMUX,
        ("DirectPlayError",),
    ),
    (
        "AC-5 - a profile that permits nothing and can produce nothing",
        a_profile(transcoding=()),
        Outcome.NONE,
        (),
    ),
    (
        "a resolution ceiling below the source",
        a_profile(
            PLAYS_EVERYTHING,
            codecs=(a_video_codec_profile(a_condition(ConditionProperty.HEIGHT, "480")),),
        ),
        Outcome.TRANSCODE,
        ("VideoResolutionNotSupported",),
    ),
    (
        "a resolution ceiling above the source refuses nothing",
        a_profile(
            PLAYS_EVERYTHING,
            codecs=(a_video_codec_profile(a_condition(ConditionProperty.HEIGHT, "4320")),),
        ),
        Outcome.DIRECT_PLAY,
        (),
    ),
    (
        "two conditions failing at once, declared in the order the enum does not use",
        a_profile(
            PLAYS_EVERYTHING,
            codecs=(
                a_video_codec_profile(
                    a_condition(ConditionProperty.VIDEO_RANGE_TYPE, "HDR10", ConditionType.EQUALS),
                    a_condition(ConditionProperty.VIDEO_LEVEL, "1"),
                ),
            ),
        ),
        Outcome.TRANSCODE,
        ("VideoLevelNotSupported", "VideoRangeTypeNotSupported"),
    ),
    (
        "AC-9 - the streaming bitrate bounds direct play, and blames the container",
        a_profile(PLAYS_EVERYTHING, max_streaming_bitrate=SOURCE_BITRATE // 2),
        Outcome.TRANSCODE,
        ("ContainerBitrateExceedsLimit",),
    ),
    (
        "a frame-rate ceiling stated at the rate the wire printed is still refused",
        a_profile(
            PLAYS_EVERYTHING,
            codecs=(
                a_video_codec_profile(a_condition(ConditionProperty.VIDEO_FRAMERATE, PRINTED_RATE)),
            ),
        ),
        Outcome.TRANSCODE,
        ("VideoFramerateNotSupported",),
    ),
    (
        "the same ceiling a hair higher is satisfied",
        a_profile(
            PLAYS_EVERYTHING,
            codecs=(
                a_video_codec_profile(a_condition(ConditionProperty.VIDEO_FRAMERATE, "23.975998")),
            ),
        ),
        Outcome.DIRECT_PLAY,
        (),
    ),
]


@pytest.mark.parametrize(
    "profile,outcome,reasons",
    [row[1:] for row in RUNGS],
    ids=[row[0] for row in RUNGS],
)
def test_every_rung_of_the_ladder(
    profile: DeviceProfile | None, outcome: Outcome, reasons: tuple[str, ...]
) -> None:
    decision = answer(profile)
    assert (decision.outcome, decision.reasons) == (outcome, reasons)


def test_the_printed_rate_really_is_below_the_value_compared_against() -> None:
    """The row above is only a test while these two numbers differ.

    If `narrow_to_single` were ever changed to round to the decimal the wire prints, the ceiling
    would be satisfied and the row would pass for the wrong reason - so the disagreement itself
    is asserted rather than assumed.
    """
    stream = a_video_stream()
    assert stream.reference_frame_rate is not None
    assert stream.reference_frame_rate > float(PRINTED_RATE)
    assert stream_of(stream).reference_frame_rate == float(PRINTED_RATE)


# ------------------------------------------------------------------------------------------
# The flags a client branches on (spec section 3.2)
# ------------------------------------------------------------------------------------------


def test_supports_direct_stream_mirrors_direct_play_on_every_outcome() -> None:
    """The reference disables its direct-stream path outright, so the flag never answers alone."""
    for profile in (None, DeviceProfile(), a_profile(PLAYS_EVERYTHING), a_profile()):
        decision = answer(profile)
        assert decision.supports_direct_stream is decision.supports_direct_play


def test_supports_transcoding_is_about_the_profile_not_about_the_answer() -> None:
    """A direct-play answer still says `true` when a target exists, and `false` when none does.

    Measured on one accepting profile with and without a transcoding entry - the flag moved while
    the outcome did not, which is why it cannot be derived from the outcome.
    """
    with_target = answer(a_profile(PLAYS_EVERYTHING))
    without = answer(a_profile(PLAYS_EVERYTHING, transcoding=()))
    assert (with_target.outcome, without.outcome) == (Outcome.DIRECT_PLAY, Outcome.DIRECT_PLAY)
    assert with_target.supports_transcoding is True
    assert without.supports_transcoding is False


def test_a_refusal_carries_no_reasons_because_it_carries_no_url() -> None:
    refusal = answer(a_profile(transcoding=()))
    assert refusal.outcome is Outcome.NONE
    assert (refusal.reasons, refusal.container, refusal.sub_protocol) == ((), None, None)
    assert (refusal.video, refusal.audio) == (None, None)


def test_the_negotiated_container_and_protocol_come_from_the_chosen_target() -> None:
    """What `TranscodingContainer` and `TranscodingSubProtocol` are answered from (T5's input)."""
    decision = answer(a_profile(DirectPlayProfile(container="mkv")))
    assert (decision.container, decision.sub_protocol) == ("ts", "hls")


# ------------------------------------------------------------------------------------------
# The switches: one is honoured, one is ignored on purpose (spec section 3.2)
# ------------------------------------------------------------------------------------------


def test_enable_direct_play_false_is_honoured_and_blames_nothing() -> None:
    """The flags describe *this* negotiation: a source the profile satisfies still gets a URL."""
    decision = answer(a_profile(PLAYS_EVERYTHING), enable_direct_play=False)
    assert decision.outcome is Outcome.REMUX
    assert decision.reasons == ("DirectPlayError",)
    assert decision.supports_direct_play is False


def test_enable_transcoding_false_changes_nothing() -> None:
    """Measured: the `TranscodingUrl` arrives anyway. The switch is declared and never read."""
    forced = a_profile(DirectPlayProfile(container="mkv", video_codec="h264", audio_codec="aac"))
    assert answer(forced) == answer(forced, enable_transcoding=False)


def test_allow_video_stream_copy_false_turns_a_remux_into_a_transcode() -> None:
    """The switch the reference does read on the copy path."""
    container_only = a_profile(DirectPlayProfile(container="mkv", video_codec="hevc"))
    assert answer(container_only).outcome is Outcome.REMUX
    assert answer(container_only, allow_video_stream_copy=False).outcome is Outcome.TRANSCODE


# ------------------------------------------------------------------------------------------
# AC-31: the policy shapes, and the single denial that decides nothing
# ------------------------------------------------------------------------------------------

FORCES_A_TRANSCODE = a_profile(
    DirectPlayProfile(container="mkv", video_codec="h264", audio_codec="vorbis"),
    transcoding=(TS_HLS_H264_ONLY,),
)

POLICIES: list[tuple[str, PlaybackPolicy, bool, Outcome]] = [
    ("every permission granted", PlaybackPolicy(), True, Outcome.TRANSCODE),
    (
        "video transcoding alone denied changes nothing",
        PlaybackPolicy(enable_video_transcoding=False),
        True,
        Outcome.TRANSCODE,
    ),
    (
        "audio transcoding alone denied changes nothing",
        PlaybackPolicy(enable_audio_transcoding=False),
        True,
        Outcome.TRANSCODE,
    ),
    (
        "remuxing alone denied changes nothing",
        PlaybackPolicy(enable_remuxing=False),
        True,
        Outcome.TRANSCODE,
    ),
    (
        "two of the three denied still changes nothing",
        PlaybackPolicy(enable_video_transcoding=False, enable_audio_transcoding=False),
        True,
        Outcome.TRANSCODE,
    ),
    (
        "all three denied at once, and only then",
        PlaybackPolicy(
            enable_video_transcoding=False,
            enable_audio_transcoding=False,
            enable_remuxing=False,
        ),
        False,
        Outcome.NONE,
    ),
]


@pytest.mark.parametrize(
    "policy,supports,outcome",
    [row[1:] for row in POLICIES],
    ids=[row[0] for row in POLICIES],
)
def test_ac31_a_video_policy_needs_all_three_denials(
    policy: PlaybackPolicy, supports: bool, outcome: Outcome
) -> None:
    decision = decide(FILM, FORCES_A_TRANSCODE, Switches(), policy, is_video=True)
    assert (decision.outcome, decision.supports_transcoding) == (outcome, supports)


def test_ac31_an_audio_item_turns_on_the_audio_permission_alone() -> None:
    """The other half of the measured rule, and it is not the video one with a name changed."""
    profile = DeviceProfile(
        direct_play_profiles=(DirectPlayProfile(container="mp3", type=MediaKind.AUDIO),),
        transcoding_profiles=(
            TranscodingProfile(container="mp3", audio_codec="mp3", type=MediaKind.AUDIO),
        ),
    )
    denied = PlaybackPolicy(enable_audio_transcoding=False)
    assert decide(TRACK, profile, Switches(), denied, is_video=False).outcome is Outcome.NONE
    kept = PlaybackPolicy(enable_video_transcoding=False, enable_remuxing=False)
    assert decide(TRACK, profile, Switches(), kept, is_video=False).outcome is Outcome.TRANSCODE


def test_no_policy_shape_produces_an_error() -> None:
    """AC-31's last clause: every answer is a `Decision`. There is no error shape to produce."""
    for _, policy, _, _ in POLICIES:
        decision = decide(FILM, FORCES_A_TRANSCODE, Switches(), policy, is_video=True)
        assert isinstance(decision, Decision)
        assert decision.reasons == () or decision.outcome is not Outcome.NONE


# ------------------------------------------------------------------------------------------
# AC-7 and AC-9: what each stream is planned to become
# ------------------------------------------------------------------------------------------


def test_ac7_a_refused_audio_track_costs_an_audio_encode_and_not_a_video_one() -> None:
    decision = answer(
        a_profile(
            DirectPlayProfile(container="mp4", video_codec="hevc", audio_codec="aac"),
            transcoding=(TS_HLS_AAC_ONLY,),
        )
    )
    assert decision.video is not None and decision.audio is not None
    assert decision.video.action is StreamAction.COPY
    assert (decision.video.codec, decision.video.width, decision.video.height) == (
        "hevc",
        1920,
        816,
    )
    assert decision.audio.action is StreamAction.ENCODE
    assert decision.audio.codec == "aac"


def test_ac9_nothing_is_upscaled() -> None:
    """A 1080p ceiling over an 816-line source plans 816 lines, not 1080."""
    decision = answer(
        a_profile(
            DirectPlayProfile(container="mp4", video_codec="h264"),
            transcoding=(TS_HLS_H264_ONLY,),
            codecs=(
                CodecProfile(
                    type=CodecKind.VIDEO,
                    codec="h264",
                    conditions=(
                        a_condition(ConditionProperty.WIDTH, "1920"),
                        a_condition(ConditionProperty.HEIGHT, "1080"),
                    ),
                ),
            ),
        )
    )
    assert decision.video is not None
    assert (decision.video.action, decision.video.width, decision.video.height) == (
        StreamAction.ENCODE,
        1920,
        816,
    )


def test_ac9_a_ceiling_below_the_source_is_the_ceiling() -> None:
    decision = answer(
        a_profile(
            DirectPlayProfile(container="mp4", video_codec="h264"),
            transcoding=(TS_HLS_H264_ONLY,),
            codecs=(
                CodecProfile(
                    type=CodecKind.VIDEO,
                    codec="h264",
                    conditions=(a_condition(ConditionProperty.HEIGHT, "480"),),
                ),
            ),
        )
    )
    assert decision.video is not None and decision.video.height == 480


def test_a_sample_rate_ceiling_is_honoured_exactly_rather_than_from_the_opus_ladder() -> None:
    """behaviours section 3.7's divergence, decided here because this is where the target is set.

    The reference answers a 22 050 Hz ceiling at 24 000 Hz - the next step of the ladder Opus
    needs, applied to every codec. A client declares a ceiling because something downstream cannot
    go above it, so Atrium plans the ceiling itself.
    """
    profile = DeviceProfile(
        direct_play_profiles=(DirectPlayProfile(container="mp3", type=MediaKind.AUDIO),),
        transcoding_profiles=(
            TranscodingProfile(container="mp3", audio_codec="mp3", type=MediaKind.AUDIO),
        ),
        codec_profiles=(
            CodecProfile(
                type=CodecKind.AUDIO,
                codec="mp3",
                conditions=(a_condition(ConditionProperty.AUDIO_SAMPLE_RATE, "22050"),),
            ),
        ),
    )
    decision = decide(TRACK, profile, Switches(), is_video=False)
    assert decision.audio is not None
    assert decision.audio.sample_rate == 22050


def test_a_channel_ceiling_comes_from_the_body_as_well_as_the_profile() -> None:
    """`MaxAudioChannels` is a request switch, and it binds like a condition would."""
    surround = a_source(
        an_audio_stream(index=0, codec="flac", channels=6, sample_rate=48000), container="flac"
    )
    profile = DeviceProfile(
        transcoding_profiles=(
            TranscodingProfile(container="mp3", audio_codec="mp3", type=MediaKind.AUDIO),
        ),
    )
    decision = decide(surround, profile, Switches(max_audio_channels=2), is_video=False)
    assert decision.audio is not None and decision.audio.channels == 2


def test_a_copied_stream_keeps_the_numbers_the_file_has() -> None:
    decision = answer(a_profile(DirectPlayProfile(container="mkv", video_codec="hevc")))
    assert decision.video is not None and decision.audio is not None
    assert decision.video.action is StreamAction.COPY
    assert (decision.audio.channels, decision.audio.sample_rate) == (6, 48000)


# ------------------------------------------------------------------------------------------
# The reasons vocabulary and its order
# ------------------------------------------------------------------------------------------

#: The whole enum in the order .NET's flags formatter emits it - ascending value, which is *not*
#: the order the reference declares the members in. Spelled out so that a member renamed, added
#: or re-valued fails here rather than on a client.
EVERY_REASON = (
    "ContainerNotSupported",
    "VideoCodecNotSupported",
    "AudioCodecNotSupported",
    "SubtitleCodecNotSupported",
    "AudioIsExternal",
    "SecondaryAudioNotSupported",
    "VideoProfileNotSupported",
    "VideoLevelNotSupported",
    "VideoResolutionNotSupported",
    "VideoBitDepthNotSupported",
    "VideoFramerateNotSupported",
    "RefFramesNotSupported",
    "AnamorphicVideoNotSupported",
    "InterlacedVideoNotSupported",
    "AudioChannelsNotSupported",
    "AudioProfileNotSupported",
    "AudioSampleRateNotSupported",
    "AudioBitDepthNotSupported",
    "ContainerBitrateExceedsLimit",
    "VideoBitrateNotSupported",
    "AudioBitrateNotSupported",
    "UnknownVideoStreamInfo",
    "UnknownAudioStreamInfo",
    "DirectPlayError",
    "VideoRangeTypeNotSupported",
    "VideoCodecTagNotSupported",
    "StreamCountExceedsLimit",
)


def test_the_reason_vocabulary_is_the_references_own_in_its_own_order() -> None:
    ordered = sorted(TranscodeReason, key=lambda one: one.value)
    assert tuple(one.wire_name for one in ordered) == EVERY_REASON


def test_the_declaration_order_and_the_value_order_really_disagree() -> None:
    """Otherwise the ordering row above would pass whichever order the implementation used."""
    declared = [one.wire_name for one in TranscodeReason]
    assert declared.index("VideoRangeTypeNotSupported") > declared.index("VideoLevelNotSupported")
    assert TranscodeReason.VIDEO_RANGE_TYPE_NOT_SUPPORTED.value > (
        TranscodeReason.VIDEO_LEVEL_NOT_SUPPORTED.value
    )


# ------------------------------------------------------------------------------------------
# Comma-separated membership, which is four rules rather than one
# ------------------------------------------------------------------------------------------

CONTAINMENT: list[tuple[str, DirectPlayProfile, bool]] = [
    ("one member of the stored list is enough", DirectPlayProfile(container="mp4"), True),
    ("a list of its own, any member matching", DirectPlayProfile(container="mkv,mp4"), True),
    ("casing does not matter", DirectPlayProfile(container="MP4"), True),
    ("an absent list admits everything", DirectPlayProfile(), True),
    ("an empty list admits everything", DirectPlayProfile(container=""), True),
    ("a leading minus inverts the whole answer", DirectPlayProfile(container="-mp4"), False),
    ("and an exclusion list that misses admits", DirectPlayProfile(container="-mkv"), True),
    ("a member that is not there", DirectPlayProfile(container="mkv"), False),
    (
        "members are not trimmed, because the reference does not",
        DirectPlayProfile(container="mkv, mp4"),
        False,
    ),
]


@pytest.mark.parametrize(
    "entry,accepted",
    [row[1:] for row in CONTAINMENT],
    ids=[row[0] for row in CONTAINMENT],
)
def test_container_membership(entry: DirectPlayProfile, accepted: bool) -> None:
    decision = answer(a_profile(entry))
    assert (decision.outcome is Outcome.DIRECT_PLAY) is accepted


# ------------------------------------------------------------------------------------------
# Conditions: what an unknown value does, and the ones that fail silently
# ------------------------------------------------------------------------------------------


def test_an_unknown_value_satisfies_a_condition_that_is_not_required() -> None:
    """A Matroska stream reports no per-stream bit depth; a profile that merely prefers one is
    not a profile that refuses the file."""
    no_depth = a_source(a_video_stream(bit_depth=None), an_audio_stream())
    conditions = (a_condition(ConditionProperty.VIDEO_BIT_DEPTH, "8", is_required=False),)
    profile = a_profile(PLAYS_EVERYTHING, codecs=(a_video_codec_profile(*conditions),))
    assert decide(no_depth, profile, Switches(), is_video=True).outcome is Outcome.DIRECT_PLAY

    required = (a_condition(ConditionProperty.VIDEO_BIT_DEPTH, "8"),)
    refuses = a_profile(PLAYS_EVERYTHING, codecs=(a_video_codec_profile(*required),))
    assert decide(no_depth, refuses, Switches(), is_video=True).reasons == (
        "VideoBitDepthNotSupported",
    )


def test_a_condition_the_reference_blames_on_nothing_fails_silently() -> None:
    """Eight properties map to no reason at all upstream, so a profile stating one of them gets
    direct play whether or not it holds. Reproduced rather than tidied."""
    profile = a_profile(
        PLAYS_EVERYTHING,
        codecs=(
            a_video_codec_profile(
                a_condition(ConditionProperty.IS_AVC, "true", ConditionType.EQUALS)
            ),
        ),
    )
    assert answer(profile).outcome is Outcome.DIRECT_PLAY


def test_apply_conditions_gate_the_entry_they_belong_to() -> None:
    """ "h264 above level 4.1 must also be 8-bit" must not constrain a stream below that level."""
    gated = CodecProfile(
        type=CodecKind.VIDEO,
        codec="hevc",
        apply_conditions=(
            a_condition(ConditionProperty.VIDEO_LEVEL, "150", ConditionType.GREATER_THAN_EQUAL),
        ),
        conditions=(a_condition(ConditionProperty.VIDEO_BIT_DEPTH, "8"),),
    )
    assert answer(a_profile(PLAYS_EVERYTHING, codecs=(gated,))).outcome is Outcome.DIRECT_PLAY
    reached = CodecProfile(
        type=CodecKind.VIDEO,
        codec="hevc",
        apply_conditions=(
            a_condition(ConditionProperty.VIDEO_LEVEL, "90", ConditionType.GREATER_THAN_EQUAL),
        ),
        conditions=(a_condition(ConditionProperty.VIDEO_BIT_DEPTH, "8"),),
    )
    assert answer(a_profile(PLAYS_EVERYTHING, codecs=(reached,))).reasons == (
        "VideoBitDepthNotSupported",
    )


def test_equals_any_takes_a_pipe_separated_list() -> None:
    profile = a_profile(
        PLAYS_EVERYTHING,
        codecs=(
            a_video_codec_profile(
                a_condition(
                    ConditionProperty.VIDEO_PROFILE, "Main|Main 10", ConditionType.EQUALS_ANY
                )
            ),
        ),
    )
    assert answer(profile).outcome is Outcome.DIRECT_PLAY


def test_an_unreadable_condition_value_costs_a_transcode_rather_than_the_response() -> None:
    """The reference raises on an ordering comparison against a string, which is a 500. Atrium
    answers the request and treats the condition as unmet."""
    profile = a_profile(
        PLAYS_EVERYTHING,
        codecs=(a_video_codec_profile(a_condition(ConditionProperty.VIDEO_PROFILE, "Main")),),
    )
    assert answer(profile).reasons == ("VideoProfileNotSupported",)


# ------------------------------------------------------------------------------------------
# The HDR rule, and what is left of it in v1
# ------------------------------------------------------------------------------------------


def test_a_copy_never_strips_what_the_client_declared() -> None:
    """behaviours section 3.4 in the shape v1 can reach.

    The reference plans removal of HDR10+ side data from a `DOVIWithHDR10Plus` stream as soon as a
    client's declared range types contain `DOVI`, without checking whether the client declared the
    coexistence itself. Atrium's copy path removes nothing at all, and the conditional half of the
    divergence has nothing to condition on: `VideoRangeType` carries only the three members a
    stream listing can produce (`domain/media.py`), so no inspection in v1 ever answers
    `DOVIWithHDR10Plus`. It arrives with the probe that reads Dolby Vision side data.
    """
    assert {one.value for one in VideoRangeType} == {"SDR", "HDR10", "HLG"}
    hdr = a_source(
        a_video_stream(video_range=VideoRange.HDR, video_range_type=VideoRangeType.HDR10),
        an_audio_stream(),
    )
    declares_dovi = a_profile(
        DirectPlayProfile(container="mkv", video_codec="hevc"),
        codecs=(
            a_video_codec_profile(
                a_condition(
                    ConditionProperty.VIDEO_RANGE_TYPE,
                    "SDR|HDR10|DOVI|DOVIWithHDR10Plus",
                    ConditionType.EQUALS_ANY,
                )
            ),
        ),
    )
    decision = decide(hdr, declares_dovi, Switches(), is_video=True)
    assert decision.outcome is Outcome.REMUX
    assert decision.video is not None and decision.video.action is StreamAction.COPY


# ------------------------------------------------------------------------------------------
# Determinism (Principle VII)
# ------------------------------------------------------------------------------------------


def test_the_same_question_twice_is_the_same_answer() -> None:
    for _, profile, _, _ in RUNGS:
        assert answer(profile) == answer(profile)


# ------------------------------------------------------------------------------------------
# The subtitle half (011 T9)
# ------------------------------------------------------------------------------------------
#
# The rows below are `tools/probe_subtitle_negotiation.py`'s batteries as values: the same profile
# classes, the same two track kinds, the same two play methods
# `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`. What is asserted
# per row is **one answer per subtitle stream**, not one for the selected track, because that is
# what the reference emits and a table over the chosen one alone would pass with three-quarters of
# the ladder deleted.


def a_subtitle_stream(**overrides: object) -> InspectedStream:
    values: dict[str, object] = {
        "index": 2,
        "kind": StreamKind.SUBTITLE,
        "codec": "subrip",
        "language": "eng",
        "is_default": True,
    }
    values.update(overrides)
    return InspectedStream(**values)  # type: ignore[arg-type]


#: The stored spelling of a Blu-ray bitmap track - `media/probe.py` renames it at inspection, and
#: the split reads the renamed name (011 T2). Written as the wire spells it, so a test that named
#: ffprobe's own `hdmv_pgs_subtitle` would be testing a string this server never stores.
IMAGE_CODEC = "PGSSUB"

TEXT_TRACK = a_subtitle_stream(index=2, codec="subrip", language="eng")
IMAGE_TRACK = a_subtitle_stream(index=3, codec=IMAGE_CODEC, language="spa", is_default=False)
STYLED_TRACK = a_subtitle_stream(index=4, codec="ass", language="fra", is_default=False)
SIDECAR_TRACK = a_subtitle_stream(
    index=0, codec="srt", language="spa", is_default=False, is_external=True, external_path="a.srt"
)

#: Matroska rather than the mp4 family, because it is the only container an embedded subtitle
#: survives a transcode into - and because a single-name container keeps the embed rows about the
#: embed rule rather than about demuxer-list membership.
SUBTITLED = a_source(
    a_video_stream(index=0),
    an_audio_stream(index=1),
    TEXT_TRACK,
    IMAGE_TRACK,
    STYLED_TRACK,
    container="matroska",
)

PLAYS_MATROSKA = DirectPlayProfile(container="matroska", video_codec="hevc", audio_codec="ac3")
#: A target that cannot embed - `ts` is refused by name - beside one that can.
TS_HLS_MATROSKA = TranscodingProfile(
    container="ts", video_codec="hevc,h264", audio_codec="ac3,aac", protocol="hls"
)
MKV_HTTP = TranscodingProfile(
    container="mkv", video_codec="hevc,h264", audio_codec="ac3,aac", protocol="http"
)

EXTERNAL_VTT = SubtitleProfile(format="vtt", method=SubtitleMethod.EXTERNAL)
MANIFEST_VTT = SubtitleProfile(format="vtt", method=SubtitleMethod.HLS)
EMBED_SUBRIP = SubtitleProfile(
    format="subrip", method=SubtitleMethod.EMBED, container="matroska,mkv"
)


def subtitled_profile(
    *subtitles: SubtitleProfile,
    direct_play: tuple[DirectPlayProfile, ...] = (PLAYS_MATROSKA,),
    transcoding: tuple[TranscodingProfile, ...] = (TS_HLS_MATROSKA,),
) -> DeviceProfile:
    return DeviceProfile(
        direct_play_profiles=direct_play,
        transcoding_profiles=transcoding,
        subtitle_profiles=subtitles,
    )


def methods(decision: Decision) -> dict[int, SubtitleMethod]:
    return {one.index: one.method for one in decision.subtitles}


#: Refuses the container, so the same profile answers a transcode over the same file.
REFUSES_MATROSKA = DirectPlayProfile(container="mp4", video_codec="hevc", audio_codec="ac3")

SUBTITLE_ROWS: tuple[tuple[str, DeviceProfile, dict[int, SubtitleMethod]], ...] = (
    (
        "external vtt, direct play",
        subtitled_profile(EXTERNAL_VTT),
        {2: SubtitleMethod.EXTERNAL, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "external vtt, transcode",
        subtitled_profile(EXTERNAL_VTT, direct_play=(REFUSES_MATROSKA,)),
        {2: SubtitleMethod.EXTERNAL, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "manifest vtt, transcode",
        subtitled_profile(MANIFEST_VTT, direct_play=(REFUSES_MATROSKA,)),
        {2: SubtitleMethod.HLS, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "manifest vtt, direct play - the method is a transcode method and nothing else fits",
        subtitled_profile(MANIFEST_VTT),
        {2: SubtitleMethod.ENCODE, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "embedded subrip, direct play",
        subtitled_profile(EMBED_SUBRIP),
        {2: SubtitleMethod.EMBED, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "embedded subrip, transcode into ts - refused by name",
        subtitled_profile(EMBED_SUBRIP, direct_play=(REFUSES_MATROSKA,)),
        {2: SubtitleMethod.ENCODE, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "embedded subrip, transcode into mkv - admitted by name",
        subtitled_profile(EMBED_SUBRIP, direct_play=(REFUSES_MATROSKA,), transcoding=(MKV_HTTP,)),
        {2: SubtitleMethod.EMBED, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "nothing declared, direct play",
        subtitled_profile(),
        {2: SubtitleMethod.ENCODE, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "nothing declared, transcode",
        subtitled_profile(direct_play=(REFUSES_MATROSKA,)),
        {2: SubtitleMethod.ENCODE, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "an image-format external profile reaches the image track and nothing else",
        subtitled_profile(SubtitleProfile(format=IMAGE_CODEC, method=SubtitleMethod.EXTERNAL)),
        {2: SubtitleMethod.ENCODE, 3: SubtitleMethod.EXTERNAL, 4: SubtitleMethod.ENCODE},
    ),
    (
        "a declared Drop entry is a member no pass can return",
        subtitled_profile(SubtitleProfile(format="subrip", method=SubtitleMethod.DROP)),
        {2: SubtitleMethod.ENCODE, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
    (
        "a language-scoped external profile reaches only the tracks in that language",
        subtitled_profile(
            SubtitleProfile(format="vtt", method=SubtitleMethod.EXTERNAL, language="fra,spa")
        ),
        {2: SubtitleMethod.ENCODE, 3: SubtitleMethod.ENCODE, 4: SubtitleMethod.ENCODE},
    ),
)


@pytest.mark.parametrize(
    ("described", "profile", "expected"), SUBTITLE_ROWS, ids=lambda one: str(one)[:60]
)
def test_a_delivery_method_is_answered_for_every_subtitle_stream(
    described: str, profile: DeviceProfile, expected: dict[int, SubtitleMethod]
) -> None:
    """AC-3: one answer per stream, and `Encode` wherever nothing declared fits."""
    decision = decide(SUBTITLED, profile, Switches(), is_video=True)
    assert methods(decision) == expected, described
    assert len(decision.subtitles) == 3, "one answer per subtitle stream, never fewer"


def test_the_language_row_reaches_the_track_that_is_in_that_language() -> None:
    """The other half of the row above: `fra,spa` refuses `eng` and admits `fra` when it can.

    The styled track is `fra` **and** `ass`, so it is refused for being unconvertible rather than
    for its language - which is why the discrimination is made against a second `fra` track that
    is `subrip`, and why the row above cannot prove the rule on its own.
    """
    french_subrip = a_subtitle_stream(index=5, codec="subrip", language="fra", is_default=False)
    source = a_source(
        a_video_stream(index=0),
        an_audio_stream(index=1),
        TEXT_TRACK,
        french_subrip,
        container="matroska",
    )
    scoped = subtitled_profile(
        SubtitleProfile(format="vtt", method=SubtitleMethod.EXTERNAL, language="fra")
    )
    assert methods(decide(source, scoped, Switches(), is_video=True)) == {
        2: SubtitleMethod.ENCODE,
        5: SubtitleMethod.EXTERNAL,
    }


def test_convertibility_is_not_the_same_question_as_being_text() -> None:
    """`ass` is text, can be served alone, and still reaches the burn-in fallback.

    It cannot be converted *from*, and `vtt` is the only format the profile takes - so this is the
    row that makes `Encode` a real answer for a text track rather than an image-only one (AC-3).
    """
    decision = decide(SUBTITLED, subtitled_profile(EXTERNAL_VTT), Switches(), is_video=True)
    styled = next(one for one in decision.subtitles if one.index == 4)
    assert styled.method is SubtitleMethod.ENCODE
    assert styled.format == "ass", "the fallback states the stream's own codec, not nothing"


def test_a_profile_naming_ass_cannot_reach_it_either() -> None:
    """The other half of the same rule: `ass` cannot be converted *to*, so an exact match is the
    only way a profile that names it ever wins."""
    exact = subtitled_profile(SubtitleProfile(format="ass", method=SubtitleMethod.EXTERNAL))
    assert methods(decide(SUBTITLED, exact, Switches(), is_video=True))[4] is (
        SubtitleMethod.EXTERNAL
    )
    other = subtitled_profile(SubtitleProfile(format="ass", method=SubtitleMethod.EXTERNAL))
    answers = {
        one.index: one for one in decide(SUBTITLED, other, Switches(), is_video=True).subtitles
    }
    assert answers[2].method is SubtitleMethod.ENCODE, "subrip cannot be converted *to* ass"


def test_an_external_stream_skips_the_embedded_half_of_the_ladder() -> None:
    """There is nothing to embed a file that already sits beside the media into.

    The discrimination is the whole point: **one** entry, two text tracks in the same container,
    and only the one the container holds can take it. The sidecar is `srt` - the entry's own
    format, so it would match on the first pass if the pass were reached at all.
    """
    with_sidecar = a_source(
        SIDECAR_TRACK,
        a_video_stream(index=1),
        an_audio_stream(index=2),
        TEXT_TRACK,
        container="matroska",
    )
    embed_only = subtitled_profile(
        SubtitleProfile(format="srt", method=SubtitleMethod.EMBED, container="matroska")
    )
    answered = methods(decide(with_sidecar, embed_only, Switches(), is_video=True))
    assert answered[0] is SubtitleMethod.ENCODE, "the sidecar cannot be embedded"
    assert answered[2] is SubtitleMethod.EMBED, "the container's own subrip converts to srt"


def test_a_client_that_sent_no_profile_is_told_nothing_about_any_subtitle() -> None:
    """Rule 1's shape again: no profile is not an empty profile, here as everywhere else."""
    decision = decide(SUBTITLED, None, Switches(), is_video=True)
    assert decision.subtitles == ()
    assert methods(decide(SUBTITLED, subtitled_profile(), Switches(), is_video=True)) != {}


# ------------------------------------------------------------------------------------------
# The selected track, and what naming one costs
# ------------------------------------------------------------------------------------------


def test_naming_a_track_the_client_cannot_take_costs_the_source_its_direct_play() -> None:
    """The finding neither 011 document had: the *selected* track is a direct-play condition.

    Measured on both sides of the discrimination - an external `vtt` profile keeps direct play
    for the `subrip` track and loses it for the image one - so this is not "a subtitle refuses
    direct play", it is "a subtitle whose method is not external, embedded or dropped does".
    """
    external = subtitled_profile(EXTERNAL_VTT)
    kept = decide(SUBTITLED, external, Switches(subtitle_stream_index=2), is_video=True)
    assert kept.outcome is Outcome.DIRECT_PLAY

    lost = decide(SUBTITLED, external, Switches(subtitle_stream_index=3), is_video=True)
    assert lost.outcome is not Outcome.DIRECT_PLAY
    assert "SubtitleCodecNotSupported" in lost.reasons

    burned = decide(
        SUBTITLED, subtitled_profile(), Switches(subtitle_stream_index=2), is_video=True
    )
    assert burned.outcome is not Outcome.DIRECT_PLAY
    assert burned.reasons == ("SubtitleCodecNotSupported",)


def test_the_manifest_method_cannot_save_a_direct_play_because_it_is_not_reachable_there() -> None:
    """The circularity the reference resolves by asking twice: the direct-play check resolves the
    method *at direct play*, where an `Hls` entry is skipped - so a manifest-only profile loses
    its direct play and then answers `Hls` on the transcode it was pushed onto."""
    decision = decide(
        SUBTITLED, subtitled_profile(MANIFEST_VTT), Switches(subtitle_stream_index=2), is_video=True
    )
    # A remux rather than a transcode: both elementary streams still copy, and the subtitle is
    # the only thing that moved this off direct play.
    assert decision.outcome is Outcome.REMUX
    assert "SubtitleCodecNotSupported" in decision.reasons
    assert methods(decision)[2] is SubtitleMethod.HLS


def test_an_index_naming_no_stream_costs_nothing_and_is_still_restated() -> None:
    """There is no method to resolve for a track that is not there, so nothing is refused - and
    the index still comes back as the source's stated default, `-1` and `99` alike."""
    for named in (-1, 99):
        decision = decide(
            SUBTITLED, subtitled_profile(), Switches(subtitle_stream_index=named), is_video=True
        )
        assert decision.outcome is Outcome.DIRECT_PLAY, named
        assert decision.subtitle_index == named


def test_no_track_named_proposes_no_default_at_all() -> None:
    """v1 keeps no per-user subtitle mode, so it answers what a `SubtitleMode: None` user is
    answered: no default track (AC-2, OQ-12). Never the highest-scoring stream."""
    decision = decide(SUBTITLED, subtitled_profile(EXTERNAL_VTT), Switches(), is_video=True)
    assert decision.subtitle_index is None


def test_an_audio_item_never_reads_a_subtitle_index() -> None:
    """The reference's audio builder does not look at one, so an audio negotiation answers no
    default subtitle track however the body asks."""
    decision = decide(
        TRACK,
        DeviceProfile(
            direct_play_profiles=(
                DirectPlayProfile(container="flac", audio_codec="flac", type=MediaKind.AUDIO),
            ),
            transcoding_profiles=(),
        ),
        Switches(subtitle_stream_index=2),
        is_video=False,
    )
    assert decision.subtitle_index is None


# ------------------------------------------------------------------------------------------
# The vocabulary in a delivery address (011 T11)
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Hls", SubtitleMethod.HLS),
        ("hls", SubtitleMethod.HLS),
        ("HLS", SubtitleMethod.HLS),
        ("hLs", SubtitleMethod.HLS),
        ("3", SubtitleMethod.HLS),
        ("Encode", SubtitleMethod.ENCODE),
        ("0", SubtitleMethod.ENCODE),
        ("external", SubtitleMethod.EXTERNAL),
        ("4", SubtitleMethod.DROP),
        ("+3", SubtitleMethod.HLS),
        ("  3  ", SubtitleMethod.HLS),
        # A comma list is one value and its parts are OR-ed, which is observable rather than
        # academic: `1 | 2` is the manifest method's own ordinal, so these announce.
        ("Embed,External", SubtitleMethod.HLS),
        ("1,2", SubtitleMethod.HLS),
        ("Embed,Embed,External", SubtitleMethod.HLS),
        ("External,External", SubtitleMethod.EXTERNAL),
        ("External,Encode", SubtitleMethod.EXTERNAL),
        ("Hls,banana", None),
        # The classes that name no member, and none of them refuses: this is the half of the same
        # word that does **not** carry across from a request body, where an unbindable word is a
        # `400`. The last four also answered a `200` rather than an exception, which is what a
        # server reading them with a bare integer conversion would have raised.
        ("banana", None),
        ("9", None),
        ("-1", None),
        ("", None),
        ("3.0", None),
        ("--3", None),
        ("\u00b2", None),
        ("9999999999999999999999", None),
        (None, None),
    ],
)
def test_a_delivery_addresss_method_binds_by_case_and_by_ordinal_and_refuses_nothing(
    value: str | None, expected: SubtitleMethod | None
) -> None:
    """Six spellings measured on the master playlist route in one run, plus the members either
    side of them `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`.

    An unreadable value answers `None` and the caller announces nothing, which is the reference's
    own answer: it binds a nullable enum parameter through a binder that catches the conversion
    failure and leaves the value unset `[source:
    Jellyfin.Api/ModelBinders/NullableEnumModelBinder.cs:26-46 @ v10.11.11]`.
    """
    assert method_named(value) is expected
