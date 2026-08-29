# SPDX-License-Identifier: GPL-3.0-or-later
"""The profile `/Audio/{itemId}/universal` synthesises out of its query string.

The route's conformance file proves what the delivered bytes are; this one proves the step in
between, because three of its rules are invisible in a body and would each fail silently:

* `container` is split on **commas first and bars second**, so the string a real music client
  sends is eleven direct-play entries rather than one;
* the ceilings are stated **unscoped**, which is the difference between a condition that reaches
  the transcode and one that applies to a container the transcode never uses;
* `transcodingProtocol` is compared case-insensitively and never refused.

`[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-29]`
"""

from __future__ import annotations

import pytest

from atrium.api.universal_audio import (
    codec_for,
    direct_play_profiles,
    synthesised_profile,
)
from atrium.media.decision import CodecKind, ConditionProperty, ConditionType, MediaKind


def profile(**named: object) -> object:
    """`synthesised_profile` with everything it needs and nothing stated but the arguments."""
    fields: dict[str, object] = {
        "transcoding_container": None,
        "transcoding_protocol": None,
        "audio_codec": None,
        "transcoding_audio_channels": None,
        "max_audio_channels": None,
        "max_audio_sample_rate": None,
        "max_audio_bit_depth": None,
        "audio_bit_rate": None,
        "break_on_non_key_frames": False,
        "enable_audio_vbr_encoding": True,
    }
    container = named.pop("container", None)
    fields.update(named)
    return synthesised_profile(container, **fields)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------
# The codec a container carries
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("container", "expected"),
    [
        # The three groups the reference's table remaps, and the identity everything else takes.
        ("ogg", "opus"),
        ("webma", "opus"),
        ("m4a", "aac"),
        ("mkv", "aac"),
        ("ts", "mp3"),
        ("flac", "flac"),
        ("mp3", "mp3"),
        ("opus", "opus"),
        # Spelled the way a client might spell it: the suffix form and the wrong case.
        (".FLAC", "flac"),
        # Nothing at all, which the reference answers `aac` to rather than failing.
        ("", "aac"),
        (None, "aac"),
    ],
)
def test_the_codec_a_container_carries_is_the_references_own_inference(
    container: str | None, expected: str
) -> None:
    """The table exists in the reference and is fed the request path instead of the container -
    which is why `/universal`, whose path has no dot, gets the path back as a codec name and
    answers an empty body (behaviours section 3.8). Same table, right input."""
    assert codec_for(container) == expected


# ------------------------------------------------------------------------------------------
# `container` is a list of lists
# ------------------------------------------------------------------------------------------


def test_the_container_parameter_splits_on_commas_before_bars() -> None:
    """The string a browser music client actually sends. Split the other way round it would be
    one nonsense container and the route would transcode everything."""
    entries = direct_play_profiles("opus,webm|opus,mp3,aac,m4a|aac,flac,wav")

    assert [(one.container, one.audio_codec) for one in entries] == [
        ("opus", None),
        ("webm", "opus"),
        ("mp3", None),
        ("aac", None),
        ("m4a", "aac"),
        ("flac", None),
        ("wav", None),
    ]
    assert all(one.type is MediaKind.AUDIO for one in entries)


def test_a_bar_entry_may_list_several_codecs() -> None:
    """Everything after the first bar is one comma-separated codec list, which is what the
    ladder's own membership rule reads."""
    (entry,) = direct_play_profiles("mkv|aac|mp3")

    assert (entry.container, entry.audio_codec) == ("mkv", "aac,mp3")


def test_no_container_at_all_is_no_direct_play_entry() -> None:
    """And that is not the same as "anything plays": a profile with no direct-play entry permits
    no direct play, which is 008 T4's measured rule and the reason this is asserted."""
    assert direct_play_profiles(None) == ()
    assert direct_play_profiles("") == ()


# ------------------------------------------------------------------------------------------
# The transcoding entry and the ceilings
# ------------------------------------------------------------------------------------------


def test_the_transcoding_entry_defaults_to_mp3_in_both_halves() -> None:
    """The reference's own defaults, and the reason a bare `/universal` transcode is an mp3."""
    (target,) = profile().transcoding_profiles  # type: ignore[attr-defined]

    assert (target.container, target.audio_codec) == ("mp3", "mp3")
    assert target.protocol == "http"
    assert target.type is MediaKind.AUDIO


def test_a_named_container_with_no_codec_takes_the_containers_codec() -> None:
    """Behaviours section 3.8's divergence, at the place it is decided."""
    (target,) = profile(transcoding_container="flac").transcoding_profiles  # type: ignore[attr-defined]

    assert (target.container, target.audio_codec) == ("flac", "flac")


def test_a_named_codec_wins_over_the_containers_own() -> None:
    """The client's word, whenever it said one - the divergence only fills a silence."""
    (target,) = profile(  # type: ignore[attr-defined]
        transcoding_container="mkv", audio_codec="opus"
    ).transcoding_profiles

    assert (target.container, target.audio_codec) == ("mkv", "opus")


@pytest.mark.parametrize(
    ("stated", "expected"),
    [("hls", "hls"), ("HLS", "hls"), ("http", "http"), ("banana", "http"), (None, "http")],
)
def test_the_protocol_is_case_insensitive_and_never_refused(
    stated: str | None, expected: str
) -> None:
    """Measured: `HLS` answers a master playlist and `banana` answers the same progressive body
    `http` does. A typed parameter here would refuse a request the reference serves."""
    (target,) = profile(transcoding_protocol=stated).transcoding_profiles  # type: ignore[attr-defined]

    assert target.protocol == expected


def test_every_stated_ceiling_becomes_one_unscoped_audio_condition() -> None:
    """**The container is deliberately absent**, and that is the one place this synthesis departs
    from the reference's.

    Its own `GetDeviceProfile` scopes these conditions to the *direct-play* container list - the
    containers it will not be transcoding into - so on the transcoding path they apply to nothing,
    and the ceiling reaches the encoder only because the controller passes it to the streaming
    request outside the profile entirely. Atrium has one path and it is the profile: a request
    naming `container=ogg` and `transcodingContainer=flac` really is answered at a constrained
    rate by the reference, and a literal transcription of its profile could not do that.
    """
    (entry,) = profile(
        container="ogg",
        max_audio_sample_rate=22050,
        max_audio_bit_depth=16,
        max_audio_channels=2,
        audio_bit_rate=128000,
    ).codec_profiles  # type: ignore[attr-defined]

    assert entry.type is CodecKind.AUDIO
    assert entry.container is None
    assert [(one.property, one.value) for one in entry.conditions] == [
        (ConditionProperty.AUDIO_SAMPLE_RATE, "22050"),
        (ConditionProperty.AUDIO_BIT_DEPTH, "16"),
        (ConditionProperty.AUDIO_CHANNELS, "2"),
        (ConditionProperty.AUDIO_BITRATE, "128000"),
    ]
    assert all(one.condition is ConditionType.LESS_THAN_EQUAL for one in entry.conditions)
    # Not required, which is the reference's value and decides what an unknown stream value
    # means: a stream whose bit depth nothing reported satisfies the ceiling rather than failing.
    assert all(not one.is_required for one in entry.conditions)


def test_no_ceiling_stated_is_no_codec_profile_at_all() -> None:
    """An empty entry would be a condition list that constrains nothing, which the ladder would
    still walk. The reference omits the entry, and so does this."""
    assert profile(container="flac").codec_profiles == ()  # type: ignore[attr-defined]
