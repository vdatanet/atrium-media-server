# SPDX-License-Identifier: GPL-3.0-or-later
"""`DisplayTitle` and the five labels it is composed from.

**One piece of work and not two, which is what the reading found.** A sweep reported 84
`Localized*` findings and 28 `DisplayTitle` ones on `PlaybackInfo` as separate causes; they are
the same cause, because the labels are the *vocabulary the title is built out of* — a subtitle's
title reads `Drawn Cues - Spanish - Hearing Impaired - Forced - PGSSUB`, and three of those words
are the labels
`[probe: tools/probe_playback_stream_fields.py, Jellyfin 10.11.11, 2026-09-10]`.

The composition is the reference's, branch for branch
`[source: MediaBrowser.Model/Entities/MediaStream.cs:263-450 @ v10.11.11]`, and so is which label
lands on which kind of stream
`[source: Jellyfin.Server.Implementations/Item/MediaStreamRepository.cs:156-167 @ v10.11.11]`:
audio and subtitle carry `Default` and `External`, a subtitle carries three more, and **a video
carries none** — which is not decoration, because the video branch of the title never reads one.

**Three joins, one dash and one space.** Audio and subtitle join their parts with `" - "`; video
joins with a single space, which is why a video reads `240p H264 SDR` and an audio reads
`AAC - Stereo`. Getting that backwards is invisible until a client renders a track list.

**A title already carrying a part does not repeat it.** Where the stream has a `Title` of its own,
the reference starts from it and appends only the attributes the title does not already contain,
case-insensitively — so a track titled `Commentary` gains its language and flags, and one titled
`English SDH` does not gain `English` twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from atrium.domain.media import InspectedStream, StreamKind
from atrium.metadata.cultures import CULTURES

#: The five, verbatim, as an English reference answers them. They are a table of the server's own
#: locale rather than anything derived from a stream: each took **one** value across every stream
#: of every item read `[probe: tools/probe_playback_stream_fields.py, Jellyfin 10.11.11,
#: 2026-09-10]`. v1 serves one locale, so they are constants here; the day it serves two, this is
#: the table that grows a key.
LOCALIZED_DEFAULT = "Default"
LOCALIZED_EXTERNAL = "External"
LOCALIZED_FORCED = "Forced"
LOCALIZED_UNDEFINED = "Undefined"
LOCALIZED_HEARING_IMPAIRED = "Hearing Impaired"

#: What `video_range` says when nothing read one. Spelled here rather than imported from
#: `media/info.py` because that module builds the wire stream and reads this one: the dependency
#: goes one way.
UNKNOWN_RANGE = "Unknown"

#: Language codes that name no language, and which the title therefore omits rather than expands
#: `[source: MediaBrowser.Model/Entities/MediaStream.cs:25-35 @ v10.11.11]`. `und` is in here,
#: which is why a stream tagged `und` reads `AAC - Stereo` and not `Undefined - AAC - Stereo`.
SPECIAL_LANGUAGE_CODES = frozenset({"mis", "mul", "und", "zxx"})

#: The audio codecs with a name of their own. Everything else is upper-cased
#: `[source: MediaBrowser.Model/MediaInfo/AudioCodec.cs:9-32 @ v10.11.11]`.
AUDIO_CODEC_NAMES = {
    "ac3": "Dolby Digital",
    "eac3": "Dolby Digital+",
    "dca": "DTS",
}

#: The profile the audio branch declines to show, because every AAC track has it and a label that
#: is on everything labels nothing `[source: MediaStream.cs:300-306 @ v10.11.11]`.
UNINTERESTING_AUDIO_PROFILE = "lc"

#: `(max width, max height, name)`, in the order the reference tests them - first match wins, and
#: the widths are the ones its own comments call "16:9 square pixel format"
#: `[source: MediaBrowser.Model/Entities/MediaStream.cs:714-748 @ v10.11.11]`. A frame larger than
#: the last row has **no** resolution text at all, which is why this returns `None` rather than
#: falling back to the dimensions.
RESOLUTIONS: Sequence[tuple[int, int, str]] = (
    (256, 144, "144"),
    (426, 240, "240"),
    (640, 360, "360"),
    (682, 384, "384"),
    (720, 404, "404"),
    (854, 480, "480"),
    (960, 544, "540"),
    (1024, 576, "576"),
    (1280, 962, "720"),
    (2560, 1440, "1080"),
)

#: The two above the progressive/interlaced split: 4K and 8K carry no `p` or `i`.
LARGE_RESOLUTIONS: Sequence[tuple[int, int, str]] = ((4096, 3072, "4K"), (8192, 6144, "8K"))


def first_to_upper(text: str) -> str:
    """The first character upper-cased and the rest untouched, which is .NET's `FirstToUpper`.

    Not `str.title()` and not `capitalize()`: `Chinese (Simplified)` must survive, and both of
    those would rewrite it.
    """
    return text[:1].upper() + text[1:] if text else text


#: What separates a language's plain name from the qualifiers an ISO list carries after it.
#: **This is the one approximation in this module and it is worth naming.** `cultures.py` is
#: generated from the reference's own `/Localization/Cultures`, which is the ISO 639 list, while
#: `DisplayTitle` reads .NET's *neutral culture* display names - and the two disagree: ISO says
#: `Spanish; Castilian` and `Greek, Modern (1453-)` where .NET says `Spanish` and `Greek`.
#: Measured on the four languages this repository's fixture carries, taking the text before the
#: first of these characters answers all four - `eng`, `rus` and `fra` agree outright and `spa` is
#: the one that needed it `[probe: tools/probe_playback_stream_fields.py, Jellyfin 10.11.11,
#: 2026-09-10]`. It is not the same table, and a language whose two names differ by more than a
#: qualifier will read differently here until this server carries .NET's.
QUALIFIER_MARKS = ";,"


def language_name(code: str | None) -> str | None:
    """A language's display name, or the code itself when nothing knows it.

    `None` for a code that names no language (`und` and its siblings): the caller omits the part
    entirely rather than printing a word for it.
    """
    if not code or code.casefold() in SPECIAL_LANGUAGE_CODES:
        return None
    wanted = code.casefold()
    for culture in CULTURES:
        if wanted == culture.two_letter.casefold() or any(
            wanted == one.casefold() for one in culture.three_letters
        ):
            return first_to_upper(_plain(culture.display_name))
    # A tag this server's table does not carry is shown as it arrived rather than dropped: the
    # reference does the same, and a track labelled `qaa` is more use than one labelled nothing.
    return first_to_upper(code)


def _plain(name: str) -> str:
    """A display name without the qualifiers an ISO list carries. See `QUALIFIER_MARKS`."""
    for mark in QUALIFIER_MARKS:
        name = name.split(mark, 1)[0]
    return name.strip()


def resolution_text(width: int | None, height: int | None, *, interlaced: bool) -> str | None:
    """`240p`, `1080i`, `4K` - or nothing at all for a frame bigger than the table's last row."""
    if width is None or height is None:
        return None
    for max_width, max_height, name in RESOLUTIONS:
        if width <= max_width and height <= max_height:
            return name + ("i" if interlaced else "p")
    for max_width, max_height, name in LARGE_RESOLUTIONS:
        if width <= max_width and height <= max_height:
            return name
    return None


def audio_codec_name(codec: str | None) -> str | None:
    if not codec:
        return None
    return AUDIO_CODEC_NAMES.get(codec.casefold(), codec.upper())


def _joined(title: str | None, parts: Iterable[str], separator: str) -> str:
    """The reference's own assembly: a title keeps every part it does not already say.

    The containment test is case-insensitive and is on the **whole** part, which is what makes a
    stream titled `English SDH` gain `SUBRIP` and not `English`.
    """
    attributes = [one for one in parts if one]
    if not title:
        return separator.join(attributes)
    folded = title.casefold()
    return title + "".join(" - " + one for one in attributes if one.casefold() not in folded)


def _audio_parts(stream: InspectedStream) -> list[str]:
    parts: list[str] = []
    language = language_name(stream.language)
    if language:
        parts.append(language)
    profile = stream.profile
    if profile and profile.casefold() != UNINTERESTING_AUDIO_PROFILE:
        parts.append(profile)
    else:
        codec = audio_codec_name(stream.codec)
        if codec:
            parts.append(codec)
    if stream.channel_layout:
        parts.append(first_to_upper(stream.channel_layout))
    elif stream.channels is not None:
        parts.append(f"{stream.channels} ch")
    if stream.is_default:
        parts.append(LOCALIZED_DEFAULT)
    if stream.is_external:
        parts.append(LOCALIZED_EXTERNAL)
    return parts


def _video_parts(stream: InspectedStream) -> list[str]:
    parts: list[str] = []
    resolution = resolution_text(stream.width, stream.height, interlaced=stream.is_interlaced)
    if resolution:
        parts.append(resolution)
    if stream.codec:
        parts.append(stream.codec.upper())
    # `VideoDoViTitle` sits between these two on the reference and this server resolves no Dolby
    # Vision profile at all (behaviours section 5's accepted gaps), so the range is what a video
    # carries here - which is what it carries there too for every source without one.
    if stream.video_range is not None and stream.video_range.value != UNKNOWN_RANGE:
        parts.append(stream.video_range.value)
    return parts


def _subtitle_parts(stream: InspectedStream) -> list[str]:
    parts: list[str] = []
    language = language_name(stream.language)
    # **The one branch where a missing language prints a word**, unlike audio, which omits it.
    parts.append(language or LOCALIZED_UNDEFINED)
    if stream.is_hearing_impaired:
        parts.append(LOCALIZED_HEARING_IMPAIRED)
    if stream.is_default:
        parts.append(LOCALIZED_DEFAULT)
    if stream.is_forced:
        parts.append(LOCALIZED_FORCED)
    if stream.codec:
        parts.append(stream.codec.upper())
    if stream.is_external:
        parts.append(LOCALIZED_EXTERNAL)
    return parts


def display_title(stream: InspectedStream) -> str | None:
    """What a client shows for this stream, or `None` for a kind that has no title.

    The reference answers `null` for every type but the three, and this returns the same rather
    than an empty string: an embedded data stream is not a track anybody picks.
    """
    if stream.kind is StreamKind.AUDIO:
        return _joined(stream.title, _audio_parts(stream), " - ")
    if stream.kind is StreamKind.VIDEO:
        return _joined(stream.title, _video_parts(stream), " ")
    if stream.kind is StreamKind.SUBTITLE:
        return _joined(stream.title, _subtitle_parts(stream), " - ")
    return None


def localized_labels(kind: StreamKind) -> dict[str, str]:
    """Which of the five this kind of stream carries, keyed by the wire model's field names.

    Audio and subtitle carry `Default` and `External`; a subtitle carries three more; **a video
    carries none** `[source: Jellyfin.Server.Implementations/Item/MediaStreamRepository.cs:156-167
    @ v10.11.11]`. The rule has a reason rather than being a list: a stream carries exactly the
    labels its own branch of `display_title` can read, which is why a video - whose branch reads
    none - carries none.
    """
    if kind not in (StreamKind.AUDIO, StreamKind.SUBTITLE):
        return {}
    labels = {
        "localized_default": LOCALIZED_DEFAULT,
        "localized_external": LOCALIZED_EXTERNAL,
    }
    if kind is StreamKind.SUBTITLE:
        labels["localized_undefined"] = LOCALIZED_UNDEFINED
        labels["localized_forced"] = LOCALIZED_FORCED
        labels["localized_hearing_impaired"] = LOCALIZED_HEARING_IMPAIRED
    return labels
