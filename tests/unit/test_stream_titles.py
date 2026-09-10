# SPDX-License-Identifier: GPL-3.0-or-later
"""`DisplayTitle` and the five labels, against what a reference answered for the same streams.

Every expected string in `test_the_fixtures_four_streams_read_as_the_reference_answered_them` was
read off a reference instance over this repository's own decodable tree, not composed here
`[probe: tools/probe_playback_stream_fields.py, Jellyfin 10.11.11, 2026-09-10]`. That is the whole
value of this module: the composition has six branches and a containment rule, and a test that
asserted what this server happens to build would pass on any of them.
"""

from __future__ import annotations

import pytest

from atrium.domain.media import InspectedStream, StreamKind, VideoRange
from atrium.media.stream_titles import (
    LOCALIZED_DEFAULT,
    LOCALIZED_EXTERNAL,
    LOCALIZED_FORCED,
    LOCALIZED_HEARING_IMPAIRED,
    LOCALIZED_UNDEFINED,
    display_title,
    language_name,
    localized_labels,
    resolution_text,
)


def a_stream(kind: StreamKind, **values: object) -> InspectedStream:
    return InspectedStream(index=values.pop("index", 0), kind=kind, **values)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------
# The four the reference answered for
# ------------------------------------------------------------------------------------------


def test_the_fixtures_four_streams_read_as_the_reference_answered_them() -> None:
    """The strings on the right are the reference's, read off the wire.

    `Both Subtitle Kinds (2008).mkv` carries all four kinds of case this composition has: a video
    with a resolution and a range, an audio with a layout and no language, a text subtitle that is
    the default, and a drawn one that is forced and hearing-impaired.
    """
    video = a_stream(
        StreamKind.VIDEO, codec="h264", width=320, height=240, video_range=VideoRange.SDR
    )
    assert display_title(video) == "240p H264 SDR"

    audio = a_stream(StreamKind.AUDIO, codec="aac", channel_layout="stereo", profile="LC")
    assert display_title(audio) == "AAC - Stereo"

    text = a_stream(
        StreamKind.SUBTITLE, codec="subrip", language="eng", title="Plain Cues", is_default=True
    )
    assert display_title(text) == "Plain Cues - English - Default - SUBRIP"

    drawn = a_stream(
        StreamKind.SUBTITLE,
        codec="PGSSUB",
        language="spa",
        title="Drawn Cues",
        is_forced=True,
        is_hearing_impaired=True,
    )
    assert display_title(drawn) == "Drawn Cues - Spanish - Hearing Impaired - Forced - PGSSUB"


def test_an_external_subtitle_with_no_title_leads_with_its_language() -> None:
    """The reference's answer for the planted external track, same run."""
    stream = a_stream(
        StreamKind.SUBTITLE, codec="subrip", language="rus", is_external=True, index=3
    )
    assert display_title(stream) == "Russian - SUBRIP - External"


def test_a_default_audio_track_says_so_and_a_dolby_one_is_named() -> None:
    """`ac3` reads `Dolby Digital` rather than `AC3`, which is the reference's own friendly-name
    map and not a nicety - a client's track list shows this string."""
    stream = a_stream(
        StreamKind.AUDIO, codec="ac3", channel_layout="stereo", language="und", is_default=True
    )
    assert display_title(stream) == "Dolby Digital - Stereo - Default"


# ------------------------------------------------------------------------------------------
# The rules underneath
# ------------------------------------------------------------------------------------------


def test_video_joins_with_a_space_and_the_others_with_a_dash() -> None:
    """**The separator is per branch**, and getting it backwards is invisible until a client
    renders a track list: a video reads `240p H264 SDR` and an audio reads `AAC - Stereo`."""
    video = a_stream(StreamKind.VIDEO, codec="h264", width=1280, height=720)
    assert display_title(video) == "720p H264"

    audio = a_stream(StreamKind.AUDIO, codec="flac", channel_layout="mono")
    assert display_title(audio) == "FLAC - Mono"


def test_a_title_does_not_repeat_what_it_already_says() -> None:
    """The reference starts from the stream's own title and appends only what it does not already
    contain, case-insensitively. A track titled `English SDH` keeps one `English`."""
    stream = a_stream(
        StreamKind.SUBTITLE, codec="subrip", language="eng", title="English SDH", is_default=True
    )
    assert display_title(stream) == "English SDH - Default - SUBRIP"


def test_a_language_that_names_no_language_is_omitted_on_audio_and_printed_on_a_subtitle() -> None:
    """`und` is a special code: an audio track drops the part entirely, and a subtitle - whose
    branch has no other way to start - prints the word."""
    audio = a_stream(StreamKind.AUDIO, codec="aac", channel_layout="stereo", language="und")
    assert display_title(audio) == "AAC - Stereo"

    subtitle = a_stream(StreamKind.SUBTITLE, codec="subrip", language="und")
    assert display_title(subtitle) == f"{LOCALIZED_UNDEFINED} - SUBRIP"


def test_a_language_name_loses_the_qualifier_an_iso_list_carries() -> None:
    """The one approximation in this module, asserted where it bites. `cultures.py` comes from the
    ISO 639 list and `DisplayTitle` reads .NET's neutral-culture names: `spa` is `Spanish;
    Castilian` there and `Spanish` on the wire."""
    assert language_name("spa") == "Spanish"
    assert language_name("eng") == "English"
    assert language_name("fra") == "French"
    assert language_name("und") is None
    assert language_name("qaa") == "Qaa", "a code no table carries is shown as it arrived"


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (320, 240, "240p"),
        (1280, 720, "720p"),
        (1920, 1080, "1080p"),
        (3840, 2160, "4K"),
        (7680, 4320, "8K"),
        (10000, 8000, None),
    ],
)
def test_the_resolution_table_is_the_references(
    width: int, height: int, expected: str | None
) -> None:
    """A frame past the last row has **no** resolution text, which is why this returns `None`
    rather than falling back to the dimensions."""
    assert resolution_text(width, height, interlaced=False) == expected


def test_an_interlaced_frame_says_i() -> None:
    assert resolution_text(720, 480, interlaced=True) == "480i"
    assert resolution_text(3840, 2160, interlaced=True) == "4K", "4K carries no p or i"


def test_which_labels_a_stream_carries_is_decided_by_its_kind() -> None:
    """Audio and subtitle carry two, a subtitle carries three more, and **a video carries none** -
    which is not an omission: the video branch of the title reads none of them."""
    assert localized_labels(StreamKind.VIDEO) == {}
    assert localized_labels(StreamKind.AUDIO) == {
        "localized_default": LOCALIZED_DEFAULT,
        "localized_external": LOCALIZED_EXTERNAL,
    }
    assert localized_labels(StreamKind.SUBTITLE) == {
        "localized_default": LOCALIZED_DEFAULT,
        "localized_external": LOCALIZED_EXTERNAL,
        "localized_undefined": LOCALIZED_UNDEFINED,
        "localized_forced": LOCALIZED_FORCED,
        "localized_hearing_impaired": LOCALIZED_HEARING_IMPAIRED,
    }
