# SPDX-License-Identifier: GPL-3.0-or-later
"""Media a demuxer can actually open, and a library scanned over it.

**The world 005 and 006 work from has no files.** `tests/fixtures/query.py` opens by saying so -
"a seeded database, not a filesystem" - and the 003 tree in `tests/fixtures/library/` is real paths
full of deliberate filler, which its own generator says is fine because "003 has no use for a
decodable file". Feature 008 is the feature that does: every delivery route reads bytes, and
`ffprobe` has to be able to say what those bytes are. So this builds a second world - a handful of
seconds-long files that are genuinely `h264`, `hevc`, `aac`, `ac3` and 96 kHz `flac`, and the real
003 scan run over them.

**Generated, never checked in.** The same rule the drawn images of `tests/fixtures/images.py`
follow, for the same two reasons: a binary fixture is a file nobody reviews, and the repository
stays small. Every file here is colour bars and a sine tone, and nothing in it is anybody's work.

**Bit-exact, and the flags have to be on the right side of the command line.** Given before the
first input, `-fflags +bitexact` configures the *input* format context and the Matroska muxer goes
on writing a random `SegmentUID` and a wall-clock `DateUTC` - measured, 2026-08-29: two identical
invocations differed in sixty bytes at the same file size. Same size is the part that bites, since
003's change signal is `(size, mtime_ns)`: a rebuilt fixture would have been *invisible* to it
while every content-derived value moved underneath. The flags therefore sit with the output, and
two builds of one entry compare byte for byte.

**Cached across runs, and read-only.** Encoding the matrix costs about a second, which is small
until it is paid by every pytest invocation for the rest of the feature. The tree is written once
into a directory named after a digest of the matrix and the ffmpeg version, published with an
atomic rename, and reused; change the matrix and the digest moves, so a stale cache cannot be read.
Nothing scans destructively, so sharing one tree between tests is safe - a test that wants to
*mutate* a file copies it out first.

**Every entry says why it is in the matrix**, the discipline `tests/fixtures/library/manifest.py`
holds itself to: an entry with no reason is one nobody dares delete when it is inconvenient.

**Subtitles arrived with 011, and one of the two kinds cannot be encoded at all.** ffmpeg has no
Presentation Graphic Stream encoder, and its bitmap encoders refuse a text input outright -
*"Subtitle encoding currently only possible from text to text or bitmap to bitmap"*, measured
2026-08-30 - so an image subtitle track is a bitstream this module **writes itself** and muxes in
with `-c:s copy`. `pgs_bitstream` is that writer, and the entry carrying its output is Matroska
because mp4 accepts neither PGS nor DVD subtitles.

**A subtitle stream that does not begin at zero moves, and takes a cue off the track beside it.**
Measured 2026-08-30, and it is the same class of hazard as the Matroska muxer's random segment
identifier: ffmpeg rebases each *input* on that input's own start time, so a hand-written PGS whose
first display set sits at 0.5 s arrives in the file 0.5 s early - every cue of it - and, under
`-shortest`, the `subrip` track muxed beside it loses every cue after the first. A bitstream
starting at 1.0 s loses two. Both symptoms vanish when the first display set is at zero, which is
why `pgs_bitstream` refuses a cue list that does not start there rather than trusting a caller to
remember.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from sqlalchemy.orm import Session as OrmSession

from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import CollectionType, Item, ItemType
from atrium.domain.library import Library
from atrium.library.config import normalise_root
from atrium.library.scan import scan
from tests.fixtures.library.generate import FIXED_MTIME_NS

#: The two binaries. Named once so the skip in `tests/conftest.py` and the failure raised here
#: cannot disagree about what "ffmpeg is available" means.
BINARIES = ("ffmpeg", "ffprobe")

#: Bumped when the *shape* of what is generated changes in a way the declarations below do not
#: express - a muxer flag, the filter graph, the fixed timestamp. It goes into the cache digest,
#: so an old tree is never read by new code.
#:
#: 2: 011 T1. Subtitle tracks are muxed in, subtitle sources are written beside the media, and an
#: entry that declares one is mapped stream by stream rather than left to ffmpeg's own selection.
GENERATOR_VERSION = 2

#: Where a cached tree lands, unless the environment names somewhere else. A digest directory
#: under it holds one build.
CACHE_ENVIRONMENT_VARIABLE = "ATRIUM_MEDIA_FIXTURE_CACHE"

#: Both libraries' fixed identifiers. Distinct from `query.py`'s and from `images.py`'s, so a test
#: that mixes two worlds collides loudly instead of quietly sharing a library.
MOVIES_LIBRARY_ID = "8" * 32
MUSIC_LIBRARY_ID = "9" * 32

#: The two library roots, as directory names under the generated tree. Two libraries rather than
#: one because the walker admits video extensions into a movies library and audio into a music
#: one, so a 96 kHz flac under `Movies` is a file 003 never looks at.
MOVIES_ROOT = "Movies"
MUSIC_ROOT = "Music"

#: One audio frequency for everything. A tone is a tone; varying it would suggest a test somewhere
#: listens, and none does.
TONE_HZ = 440


# ------------------------------------------------------------------------------------------
# The matrix, declared
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cue:
    """One line of subtitle, and when it is on screen.

    The unit both kinds of track are built from: a text track writes it out as `.srt` and lets a
    demuxer or an encoder read it back, an image track draws a block for exactly its span. Small
    enough to assert in full, which is what spec section 6 asks a converted subtitle to be proven
    against.
    """

    start_seconds: float
    end_seconds: float
    text: str


#: What every embedded track carries. **It starts at zero, and that is a constraint rather than a
#: taste**: an input whose first packet is late arrives early by exactly that much, and takes the
#: later cues of the track beside it (see the module docstring).
CUES: tuple[Cue, ...] = (
    Cue(0.0, 1.0, "The first cue"),
    Cue(2.0, 3.0, "The second cue"),
)

#: What a sidecar carries: different words at different times, so a test handed a cue list can say
#: whether it came from inside the container or from beside it - and a non-zero first start, so a
#: window that rebases its cues on itself can be told from one that keeps the file's timings
#: (spec section 3.5's two switches). Nothing muxes these, so the zero rule does not apply.
SIDECAR_CUES: tuple[Cue, ...] = (
    Cue(0.5, 1.25, "Beside the film"),
    Cue(1.75, 2.5, "And still beside it"),
    Cue(3.0, 3.5, "One last time"),
)

#: The one image subtitle codec this module can produce, and the whole of what makes a declared
#: track an image one. There is no encoder for it - the bytes are written here - and no encoder for
#: the DVD and broadcast spellings from a text source either, so a matrix that wanted a second
#: image format would have to write a second bitstream.
IMAGE_SUBTITLE_CODEC = "hdmv_pgs_subtitle"


@dataclass(frozen=True)
class SubtitleTrack:
    """One subtitle track inside a container: what it is, how it gets there, and why."""

    codec: str
    """Exactly what ffprobe reports as `codec_name` for the muxed track."""

    encoder: str
    """What `-c:s:N` is given. `copy` where the source file already holds the codec, an encoder
    name where ffmpeg converts one text format into another - which is the only conversion it
    will do at all."""

    language: str
    title: str
    reason: str
    """One line. Why the matrix has this track, the same discipline the entries hold to."""

    default: bool = False
    forced: bool = False
    hearing_impaired: bool = False
    """The three flags a subtitle stream carries. Declared here and read back off ffprobe's
    `disposition`, so a muxer that dropped one fails the invariant test rather than a later
    assertion about a manifest."""

    cues: tuple[Cue, ...] = CUES

    @property
    def is_image(self) -> bool:
        return self.codec == IMAGE_SUBTITLE_CODEC

    @property
    def disposition(self) -> str:
        """The `-disposition:s:N` argument. `0` rather than nothing when no flag is set: left
        unstated, ffmpeg carries the input's own disposition through, so "no flags" would be a
        property of the generated `.srt` instead of a property of this declaration."""
        set_flags = [
            name
            for name, on in (
                ("default", self.default),
                ("forced", self.forced),
                ("hearing_impaired", self.hearing_impaired),
            )
            if on
        ]
        return "+".join(set_flags) if set_flags else "0"


@dataclass(frozen=True)
class SidecarFile:
    """A subtitle file written *beside* a media file, which is a different kind of fixture from
    a track inside one: nothing muxes it, 003 skips it for its extension, and everything about
    its language, its flags and its title is in its **name**.

    The name is therefore the declaration, and the reason says what it is meant to exercise.
    """

    name: str
    """The filename, in the media file's own directory. Not a path: a sidecar that was not beside
    its film would be claimed by nothing."""

    reason: str
    cues: tuple[Cue, ...] = SIDECAR_CUES


@dataclass(frozen=True)
class MediaFile:
    """One generated file: what it is, and why the matrix has it.

    The declaration is what drives ffmpeg *and* what the invariant test compares ffprobe's answer
    against. Those are two different programs reading the same statement from opposite ends, which
    is the only thing that makes "this file really is `hevc`" a measurement rather than a comment.
    """

    key: str
    """How a test names this entry. Not a filename: the path is free to change."""

    path: str
    """Relative to the library root, always with forward slashes."""

    root: str
    """Which library root the entry lives under. Declared rather than inferred from the presence
    of a video track: 003 admits an audio file into a movies library and would resolve it to a
    film, and a fixture that decided this by looking at the codec would quietly move an entry
    when its codec changed."""

    reason: str
    """One line. Why this entry is in the matrix at all."""

    muxer: str
    """The format ffmpeg is told to write - `mp4`, `matroska`, `flac`. Passed with `-f` rather
    than inferred from the extension, so the container is a decision and not a side effect."""

    demuxers: str
    """Exactly what ffprobe reports as `format_name`.

    A list for the two video containers, one word for `flac`. Spec section 3.1 turns on this
    distinction: item-level `Container` is the demuxer list, the media source's is the single
    resolved container, and a fixture that recorded only one of them could not tell the two
    apart."""

    audio_codec: str
    audio_encoder: str
    sample_rate: int
    channels: int
    duration_seconds: float

    video_codec: str | None = None
    video_encoder: str | None = None
    width: int | None = None
    height: int | None = None
    frame_rate: str | None = None
    """As a rational, the way ffprobe reports it: `25` and `24000/1001` are both accepted."""

    keyframe_interval_seconds: float | None = None
    """Forced keyframe cadence, where the entry exists to be segmented. `None` leaves the
    encoder's own decision, which for a four-second clip is one keyframe at the start."""

    pixel_format: str = "yuv420p"
    """Eight-bit by default. Ten bits is what a high-dynamic-range entry needs, and it is a
    property of the *encode* rather than of the colour tags beside it."""

    color_transfer: str | None = None
    """The transfer characteristics ffprobe must report back, and **the whole of what makes a
    file high dynamic range** to both servers: the reference reads this one field and nothing
    else `[source: MediaBrowser.Model/Entities/MediaStream.cs GetVideoColorRange @ v10.11.11]`.

    Two details cost a run each to find, 2026-08-29. It has to be given to the *encoder* as well
    as to the muxer - `-color_trc` alone leaves libx264 writing no VUI transfer, so ffprobe
    reports the primaries and the matrix and not the transfer - and the **Matroska muxer drops
    it** on this ffmpeg, so an HDR entry has to be mp4 or it probes back as standard range."""

    color_primaries: str | None = None
    color_space: str | None = None
    """Beside the transfer because a file that carried only the transfer would be a file no
    grader ever produces. Nothing reads them."""

    audio_bitrate: str | None = None
    """`None` for a lossless codec, which has no bitrate to ask for."""

    sample_format: str | None = None

    tags: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """Written into the file. Only the music entry carries any: 003 resolves an *examined* audio
    file from its tags and an unexamined one from its directory, and a track with no tags would
    hang under an album named after its folder."""

    subtitles: tuple[SubtitleTrack, ...] = ()
    """Muxed in, in declaration order, after the video and the audio."""

    sidecars: tuple[SidecarFile, ...] = ()
    """Written beside the file rather than into it. An entry that has one **renumbers its own
    streams** the moment 011 discovers it, so a sidecar never goes beside an entry another
    feature's tests already assert stream indices about."""

    @property
    def has_video(self) -> bool:
        return self.video_codec is not None

    @property
    def stem(self) -> str:
        """The file's name without its extension - what a sidecar's name has to begin with for
        the reference to claim it at all (spec section 3.6)."""
        return Path(self.path).stem


#: The NTSC film rate, on the one entry that exists to be segmented - so 008 T10's rounding
#: arithmetic has a source that actually runs at a fractional rate.
#:
#: **It does not reproduce the reference's measured 3.004 s, and T10 measured why.** The cadence
#: is scaled by the rate the *request* carries, which is the rate the container stores: the
#: measured film stores `23.975988` and answers 3.004 s, while this exact rational reaches the
#: arithmetic as `23.976025` and answers **3.003 s**. Left exact rather than skewed to match,
#: because a fixture that ran at 23.976 to make one number come out would be a fixture asserting
#: the conclusion (`tests/unit/test_hls_planning.py` pins the rule at both rates).
NTSC_FILM_RATE = "24000/1001"

DIRECT_PLAY = MediaFile(
    key="direct_play",
    root=MOVIES_ROOT,
    path="Direct Play (2001).mp4",
    reason="AC-1, AC-2: h264 and aac in mp4 - what every profile accepts, so a negotiation that "
    "answered anything but direct play would be answering about the profile and not the file",
    muxer="mp4",
    demuxers="mov,mp4,m4a,3gp,3g2,mj2",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="aac",
    audio_encoder="aac",
    sample_rate=48000,
    channels=2,
    audio_bitrate="96k",
    duration_seconds=4.0,
)

REJECTED_CONTAINER = MediaFile(
    key="rejected_container",
    root=MOVIES_ROOT,
    path="Rejected Container (2002).mkv",
    reason="AC-3: the same video a profile accepts, in a container it does not, beside an audio "
    "it also rejects - the remux case and the one that must not be confused with `audio_rejected`",
    muxer="matroska",
    demuxers="matroska,webm",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="ac3",
    audio_encoder="ac3",
    sample_rate=48000,
    channels=2,
    audio_bitrate="192k",
    duration_seconds=4.0,
)

REJECTED_VIDEO = MediaFile(
    key="rejected_video",
    root=MOVIES_ROOT,
    path="Rejected Video (2003).mkv",
    reason="AC-4: the codec no browser profile accepts. Step 3 of the decision has nowhere else "
    "to be reached from - every other entry is playable by copying something",
    muxer="matroska",
    demuxers="matroska,webm",
    video_codec="hevc",
    video_encoder="libx265",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="ac3",
    audio_encoder="ac3",
    sample_rate=48000,
    channels=2,
    audio_bitrate="192k",
    duration_seconds=4.0,
)

REJECTED_AUDIO = MediaFile(
    key="rejected_audio",
    root=MOVIES_ROOT,
    path="Rejected Audio (2004).mp4",
    reason="AC-7: an accepted video track beside a rejected audio one, in an accepted container. "
    "The video must survive byte-inspected while only the audio is re-encoded, and that is only a "
    "claim if the container and the video codec are the ones the profile already takes",
    muxer="mp4",
    demuxers="mov,mp4,m4a,3gp,3g2,mj2",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="ac3",
    audio_encoder="ac3",
    sample_rate=48000,
    channels=2,
    audio_bitrate="192k",
    duration_seconds=4.0,
)

LONG_TAKE = MediaFile(
    key="long_take",
    root=MOVIES_ROOT,
    path="The Long Take (2005)/The Long Take (2005).mp4",
    reason="Plan section 8's multi-keyframe entry: long enough to segment, with keyframes on a "
    "known cadence so copy-bucket alignment has boundaries to align to, at 720p so AC-9's "
    "'a 720p source under a 1080p ceiling' is a real source and not a smaller one standing in",
    muxer="mp4",
    demuxers="mov,mp4,m4a,3gp,3g2,mj2",
    video_codec="h264",
    video_encoder="libx264",
    width=1280,
    height=720,
    frame_rate=NTSC_FILM_RATE,
    keyframe_interval_seconds=2.0,
    audio_codec="aac",
    audio_encoder="aac",
    sample_rate=48000,
    channels=2,
    audio_bitrate="96k",
    duration_seconds=12.0,
)

TWO_PARTER_FIRST = MediaFile(
    key="two_parter_first",
    root=MOVIES_ROOT,
    path="The Two Parter (2006)/The Two Parter (2006) - part1.mkv",
    reason="Spec section 3.1: one media source per part. 003 already merges these into one item; "
    "what 008 adds is that the item answers two sources, in part order, and that needs two files "
    "a prober can tell apart",
    muxer="matroska",
    demuxers="matroska,webm",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="aac",
    audio_encoder="aac",
    sample_rate=48000,
    channels=2,
    audio_bitrate="96k",
    duration_seconds=4.0,
)

TWO_PARTER_SECOND = MediaFile(
    key="two_parter_second",
    root=MOVIES_ROOT,
    path="The Two Parter (2006)/The Two Parter (2006) - part2.mkv",
    reason="The second part, which must not become a second item - and is deliberately a "
    "different length from the first, so 'the sources came back in part order' cannot pass by "
    "accident on two identical files",
    muxer="matroska",
    demuxers="matroska,webm",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="aac",
    audio_encoder="aac",
    sample_rate=48000,
    channels=2,
    audio_bitrate="96k",
    duration_seconds=6.0,
)

HIGH_RANGE = MediaFile(
    key="high_range",
    root=MOVIES_ROOT,
    path="The High Range (2007).mp4",
    reason="Spec section 3.7's SDR entrance: the master playlist grows a second variant only "
    "when the video is copied *and* the source is HDR, and no other entry in this matrix is HDR "
    "- so without this one the branch has nowhere to be proven, which is exactly how OQ-7 came "
    "to answer 'exactly one variant' for a case it had never reached",
    muxer="mp4",
    demuxers="mov,mp4,m4a,3gp,3g2,mj2",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    pixel_format="yuv420p10le",
    color_transfer="smpte2084",
    color_primaries="bt2020",
    color_space="bt2020nc",
    audio_codec="ac3",
    audio_encoder="ac3",
    sample_rate=48000,
    channels=2,
    audio_bitrate="192k",
    duration_seconds=4.0,
)
"""**h264 rather than hevc, and that is a deliberate choice about the matrix rather than about
HDR.** Real high dynamic range is hevc or av1 in practice, but the branch under test reads the
source's transfer characteristics and nothing about its codec, and `rejected_video` exists to be
*the* entry whose codec nothing else has. A second hevc file would take that property away from
it to buy realism no assertion here can use. The audio is rejected so the video is copied: an
entrance stands beside a copy and never beside a re-encode."""

BOTH_SUBTITLE_KINDS = MediaFile(
    key="both_subtitle_kinds",
    root=MOVIES_ROOT,
    path="Both Subtitle Kinds (2008).mkv",
    reason="011 AC-1: the text/image split, in one file. Nothing in the matrix had a subtitle "
    "stream of any kind before this entry, so every claim about which streams are text, which "
    "can be served alone and which reach a manifest had nothing to run on",
    muxer="matroska",
    demuxers="matroska,webm",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="aac",
    audio_encoder="aac",
    sample_rate=48000,
    channels=2,
    audio_bitrate="96k",
    duration_seconds=4.0,
    subtitles=(
        SubtitleTrack(
            codec="subrip",
            encoder="copy",
            language="eng",
            title="Plain Cues",
            reason="The text half of the split, and the one format every reader takes. Default, "
            "because a source whose subtitle streams were all undefaulted could not tell a "
            "negotiation that reads the flag from one that ignores it",
            default=True,
        ),
        SubtitleTrack(
            codec=IMAGE_SUBTITLE_CODEC,
            encoder="copy",
            language="spa",
            title="Drawn Cues",
            reason="The image half, and the one thing in this module ffmpeg cannot encode: a "
            "hand-written bitstream, copied in. Its two flags are the pair the text track has "
            "not got, so a track's flags can never be attributed to the wrong stream",
            forced=True,
            hearing_impaired=True,
        ),
    ),
)
"""**Matroska, and that is forced rather than chosen.** mp4 accepts neither Presentation Graphic
Stream nor DVD subtitles, so an entry carrying an image track has no other container available -
the mirror of `high_range`, which has to be mp4 because the Matroska muxer drops a colour
statement."""

UNCONVERTIBLE_SUBTITLE = MediaFile(
    key="unconvertible_subtitle",
    root=MOVIES_ROOT,
    path="The Unconvertible (2009)/The Unconvertible (2009).mkv",
    reason="011 AC-3: `ass` is the text format nothing converts *from*, so it is what reaches an "
    "`Encode` answer under a profile that takes `vtt` alone - and it is the entry the sidecar "
    "goes beside, in a directory of its own so no other film's name can claim that file",
    muxer="matroska",
    demuxers="matroska,webm",
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    audio_codec="aac",
    audio_encoder="aac",
    sample_rate=48000,
    channels=2,
    audio_bitrate="96k",
    duration_seconds=4.0,
    subtitles=(
        SubtitleTrack(
            codec="ass",
            encoder="ass",
            language="fra",
            title="Styled Cues",
            reason="The same cues as `both_subtitle_kinds` carries in `subrip`, in the one text "
            "format a converter cannot read - which is what makes AC-3's `Encode` reachable "
            "without an image track being involved",
        ),
    ),
    sidecars=(
        SidecarFile(
            name="The Unconvertible (2009).Commentary.spa.forced.srt",
            reason="Spec section 3.6's right-to-left read, in one name: `forced` is a flag, `spa` "
            "is a language, and `Commentary` is claimed by nothing and becomes the title. It sits "
            "beside a film 008 asserts nothing about, because discovering it renumbers that "
            "film's streams and an `audioStreamIndex` assertion elsewhere would fail looking "
            "exactly like a bug in the renumbering",
        ),
    ),
)

HIGH_RATE_AUDIO = MediaFile(
    key="high_rate_audio",
    root=MUSIC_ROOT,
    path="Sounds/Untitled Folder/01 Ninety Six Kilohertz.flac",
    reason="AC-19: a sample rate above every ceiling `/universal` can be asked for, so a "
    "constraint that requires re-encoding is a constraint this source really violates. 96 kHz "
    "also sits above the Opus ladder step the reference answers instead (behaviours section 3.7)",
    muxer="flac",
    demuxers="flac",
    audio_codec="flac",
    audio_encoder="flac",
    sample_rate=96000,
    channels=2,
    sample_format="s16",
    duration_seconds=5.0,
    tags=MappingProxyType(
        {
            # The directories are deliberately **not** the album and the artist. 003 T18's lesson
            # is that an unexamined music file resolves from its path and hangs under an album
            # named after its folder - so a fixture whose folders agreed with its tags could not
            # tell a scan that read the file from one that did not.
            "title": "Ninety Six Kilohertz",
            "artist": "The Artist",
            "album_artist": "The Artist",
            "album": "The Album",
            "track": "1",
        }
    ),
)

#: Everything under the movies root, in declaration order.
FILMS: tuple[MediaFile, ...] = (
    DIRECT_PLAY,
    REJECTED_CONTAINER,
    REJECTED_VIDEO,
    REJECTED_AUDIO,
    LONG_TAKE,
    TWO_PARTER_FIRST,
    TWO_PARTER_SECOND,
    HIGH_RANGE,
    BOTH_SUBTITLE_KINDS,
    UNCONVERTIBLE_SUBTITLE,
)

#: Everything under the music root.
TRACKS: tuple[MediaFile, ...] = (HIGH_RATE_AUDIO,)

MATRIX: tuple[MediaFile, ...] = FILMS + TRACKS


# ------------------------------------------------------------------------------------------
# Writing the two subtitle sources
# ------------------------------------------------------------------------------------------


def srt_timestamp(seconds: float) -> str:
    """`HH:MM:SS,mmm`, SubRip's own spelling of an instant."""
    milliseconds = round(seconds * 1000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{milliseconds // 1000:02d},{milliseconds % 1000:03d}"


def srt_document(cues: Sequence[Cue]) -> str:
    """A cue list as SubRip. The source of every text track here, whether it stays `subrip` or is
    encoded into another text format on the way in."""
    blocks = [
        f"{number}\n{srt_timestamp(cue.start_seconds)} --> {srt_timestamp(cue.end_seconds)}\n"
        f"{cue.text}\n"
        for number, cue in enumerate(cues, start=1)
    ]
    return "\n".join(blocks) + "\n"


#: Presentation Graphic Stream segment types, in the order a display set writes them. The `END`
#: one closes a set and carries nothing.
_PGS_PALETTE = 0x14
_PGS_OBJECT = 0x15
_PGS_PRESENTATION = 0x16
_PGS_WINDOW = 0x17
_PGS_END = 0x80

#: The drawn block: one rectangle, run-length encoded a line at a time. Small because nothing
#: looks at it - what is asserted is that a demuxer calls the result `hdmv_pgs_subtitle`.
_PGS_OBJECT_WIDTH = 32
_PGS_OBJECT_HEIGHT = 8

#: The stream's declared canvas, and the clock every timestamp is counted in. The canvas is
#: stated because the format requires it; nothing compares it with the video beside it, and a
#: demuxer that read the two as disagreeing would still call this a subtitle stream.
_PGS_CANVAS = (320, 240)
_PGS_TICKS_PER_SECOND = 90_000


def _pgs_segment(kind: int, seconds: float, payload: bytes) -> bytes:
    """One segment: the magic, a presentation and a decoding timestamp, the type and the length."""
    ticks = round(seconds * _PGS_TICKS_PER_SECOND)
    return b"PG" + struct.pack(">IIBH", ticks, 0, kind, len(payload)) + payload


def _pgs_presentation(number: int, *, drawing: bool) -> bytes:
    """A composition: the canvas, which composition this is, and either one object placed at the
    origin or none at all - which is how a display set erases what the one before it drew."""
    width, height = _PGS_CANVAS
    header = struct.pack(
        ">HHBHBBB",
        width,
        height,
        0x10,  # the frame-rate field, which every writer states and no reader uses
        number,
        0x80,  # epoch start: this set does not depend on the one before it
        0x00,  # no palette-only update
        0x00,  # palette zero
    )
    if not drawing:
        return header + bytes([0])
    placement = struct.pack(">HBBHH", 0, 0, 0x00, 0, 0)
    return header + bytes([1]) + placement


def _pgs_window() -> bytes:
    """One window, at the origin, exactly the size of the object drawn into it."""
    return bytes([1]) + struct.pack(">BHHHH", 0, 0, 0, _PGS_OBJECT_WIDTH, _PGS_OBJECT_HEIGHT)


def _pgs_palette() -> bytes:
    """Two entries: transparent, and opaque white. Enough to draw a block and no more."""
    return bytes([0, 0]) + bytes([0, 16, 128, 128, 0]) + bytes([1, 235, 128, 128, 255])


def _pgs_object() -> bytes:
    """The rectangle, run-length encoded.

    A run of one colour is `00`, then `10` and the length in the low six bits, then the colour;
    `00 00` ends a line. So each of the eight lines is five bytes and the whole object is forty.
    """
    line = bytes([0x00, 0x80 | _PGS_OBJECT_WIDTH, 0x01, 0x00, 0x00])
    pixels = struct.pack(">HH", _PGS_OBJECT_WIDTH, _PGS_OBJECT_HEIGHT) + line * _PGS_OBJECT_HEIGHT
    return struct.pack(">HBB", 0, 0, 0xC0) + len(pixels).to_bytes(3, "big") + pixels


def pgs_bitstream(cues: Sequence[Cue]) -> bytes:
    """A cue list as Presentation Graphic Stream, because nothing else here can make one.

    Two display sets per cue - one that draws the block and one that erases it - of five segment
    types between them, which for the two cues of `CUES` is 434 bytes.

    **The first cue has to start at zero.** ffmpeg rebases an input on its own start time, so a
    bitstream beginning at 0.5 s arrives half a second early and, under `-shortest`, costs the
    text track muxed beside it every cue after the first (module docstring, measured 2026-08-30).
    Refused here rather than left to a caller to remember, because the symptom appears on the
    *other* track.
    """
    if not cues:
        raise ValueError("a Presentation Graphic Stream with no display set has no stream at all")
    if cues[0].start_seconds != 0.0:
        raise ValueError(
            f"the first cue starts at {cues[0].start_seconds}s; ffmpeg would rebase the whole "
            f"stream onto it and truncate the text track beside it"
        )

    out = bytearray()
    for number, cue in enumerate(cues):
        out += _pgs_segment(
            _PGS_PRESENTATION, cue.start_seconds, _pgs_presentation(number * 2, drawing=True)
        )
        out += _pgs_segment(_PGS_WINDOW, cue.start_seconds, _pgs_window())
        out += _pgs_segment(_PGS_PALETTE, cue.start_seconds, _pgs_palette())
        out += _pgs_segment(_PGS_OBJECT, cue.start_seconds, _pgs_object())
        out += _pgs_segment(_PGS_END, cue.start_seconds, b"")
        out += _pgs_segment(
            _PGS_PRESENTATION, cue.end_seconds, _pgs_presentation(number * 2 + 1, drawing=False)
        )
        out += _pgs_segment(_PGS_WINDOW, cue.end_seconds, _pgs_window())
        out += _pgs_segment(_PGS_END, cue.end_seconds, b"")
    return bytes(out)


# ------------------------------------------------------------------------------------------
# Generating
# ------------------------------------------------------------------------------------------


class FfmpegUnavailableError(RuntimeError):
    """Raised rather than skipped. A fixture that skipped itself would hand every test that asked
    for it an empty world and let the assertions decide what that meant."""


class FfmpegFailedError(RuntimeError):
    """One invocation failed, with what ffmpeg said about it - which is where a build without
    `libx265` says so."""


def missing_binaries() -> tuple[str, ...]:
    """Which of `BINARIES` this machine does not have. Empty is the happy answer."""
    return tuple(name for name in BINARIES if shutil.which(name) is None)


def binary(name: str) -> str:
    """An absolute path to one of the binaries, or a refusal naming it."""
    found = shutil.which(name)
    if found is None:
        raise FfmpegUnavailableError(
            f"{name} is not on PATH. Tests that generate or inspect media carry "
            f"@pytest.mark.ffmpeg and are skipped without it; something asked for the media "
            f"world without that marker."
        )
    return found


def _run(command: Sequence[str]) -> str:
    """Run one of the two binaries and hand back its stdout.

    `shell=False` and an absolute executable: the arguments are built from the declarations above
    and never from anything a test typed.
    """
    finished = subprocess.run(  # noqa: S603
        list(command), capture_output=True, text=True, check=False
    )
    if finished.returncode != 0:
        raise FfmpegFailedError(
            f"{' '.join(command)}\nexited {finished.returncode}:\n{finished.stderr.strip()}"
        )
    return finished.stdout


def ffmpeg_version() -> str:
    """The first line of `ffmpeg -version`, which is what the cache digest is keyed on.

    Produced bytes are a function of the encoder, so two ffmpeg builds are two different fixtures.
    That is the risk table's "fixtures regenerate per environment", made mechanical.
    """
    return _run([binary("ffmpeg"), "-hide_banner", "-version"]).splitlines()[0].strip()


def subtitle_sources(one: MediaFile, into: Path) -> tuple[Path, ...]:
    """Write each declared track's source file under `into`, in declaration order.

    They are inputs to the mux and never part of the tree - a `.sup` beside a film is a subtitle
    file 011 would discover, and this one is scaffolding rather than a fixture. The sidecars,
    which *are* fixtures, are written by `generate` into the tree itself.
    """
    written = []
    for index, track in enumerate(one.subtitles):
        if track.is_image:
            path = into / f"{index}.sup"
            path.write_bytes(pgs_bitstream(track.cues))
        else:
            path = into / f"{index}.srt"
            path.write_text(srt_document(track.cues), encoding="utf-8")
        written.append(path)
    return tuple(written)


def _encode_command(one: MediaFile, destination: Path, sources: Sequence[Path]) -> list[str]:
    """The whole invocation for one entry, inputs first and the bit-exact flags with the output.

    The order of those flags is the load-bearing detail: on the input side they configure the
    demuxer of a lavfi source that has no metadata to make exact, and the muxer goes on stamping
    a random segment identifier and the wall clock (see the module docstring).
    """
    command = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]

    inputs = 0
    video_input = None
    if one.has_video:
        video_input = inputs
        inputs += 1
        command += [
            "-f",
            "lavfi",
            "-i",
            f"smptebars=size={one.width}x{one.height}"
            f":rate={one.frame_rate}:duration={one.duration_seconds}",
        ]
    audio_input = inputs
    inputs += 1
    command += [
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={TONE_HZ}:sample_rate={one.sample_rate}:duration={one.duration_seconds}",
    ]
    first_subtitle_input = inputs
    for source in sources:
        command += ["-i", str(source)]

    if one.subtitles:
        # Only where there are subtitles, and that is the point rather than a shortcut: ffmpeg's
        # own stream selection takes the best video, the best audio and **one** subtitle stream,
        # so an entry with two would silently ship one. Left off the entries without subtitles so
        # their bytes are the bytes 008 measured.
        if video_input is not None:
            command += ["-map", f"{video_input}:v"]
        command += ["-map", f"{audio_input}:a"]
        for offset in range(len(sources)):
            command += ["-map", f"{first_subtitle_input + offset}:s"]

    if one.has_video:
        assert one.video_encoder is not None
        command += ["-c:v", one.video_encoder, "-preset", "ultrafast", "-pix_fmt", one.pixel_format]
        parameters = []
        if one.video_encoder == "libx265":
            # Otherwise x265 writes its own banner to stderr whatever `-loglevel` says, and a
            # failure message that is mostly encoder greeting is a failure message nobody reads.
            parameters.append("log-level=none")
        if one.color_transfer is not None:
            # Both to the muxer and to the encoder. The muxer's copy is what ffprobe reads out of
            # an mp4; the encoder's is what puts the same statement inside the bitstream, and
            # without it libx264 writes no transfer at all (see `color_transfer` above).
            command += [
                "-color_trc",
                one.color_transfer,
                "-color_primaries",
                str(one.color_primaries),
                "-colorspace",
                str(one.color_space),
            ]
            parameters += [
                f"colorprim={one.color_primaries}",
                f"transfer={one.color_transfer}",
                f"colormatrix={one.color_space}",
            ]
        if parameters:
            command += [f"-{one.video_encoder[3:]}-params", ":".join(parameters)]
        if one.keyframe_interval_seconds is not None:
            command += [
                "-force_key_frames",
                f"expr:gte(t,n_forced*{one.keyframe_interval_seconds})",
            ]
        if not one.subtitles:
            # **`-shortest` means the shortest stream, and a subtitle track is one.** Measured
            # 2026-08-30: a four-second film whose cues stop at 3.0 s came out 3.007 s long, video
            # and audio truncated with them, and every assertion about its duration failed. Both
            # lavfi sources already carry an explicit `duration=`, so this was belt-and-braces on
            # the entries that have it and is simply wrong on the entries that do not.
            command += ["-shortest"]

    command += ["-c:a", one.audio_encoder, "-ac", str(one.channels), "-ar", str(one.sample_rate)]
    if one.audio_bitrate is not None:
        command += ["-b:a", one.audio_bitrate]
    if one.sample_format is not None:
        command += ["-sample_fmt", one.sample_format]
    for index, track in enumerate(one.subtitles):
        command += [f"-c:s:{index}", track.encoder]
        command += [f"-metadata:s:s:{index}", f"language={track.language}"]
        command += [f"-metadata:s:s:{index}", f"title={track.title}"]
        command += [f"-disposition:s:{index}", track.disposition]

    for name, value in one.tags.items():
        command += ["-metadata", f"{name}={value}"]

    command += ["-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
    command += ["-f", one.muxer, str(destination)]
    return command


def generate(one: MediaFile, into: Path) -> Path:
    """Write one entry under `into`, and hand back where it landed.

    The sidecars go with it, because a sidecar that arrived a step later would be a file whose
    modification time the tree does not control - and its own `(size, mtime_ns)` is the second
    change signal 011 discovers it by.
    """
    destination = into.joinpath(one.root, *one.path.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atrium-subtitle-sources.") as scratch:
        _run(_encode_command(one, destination, subtitle_sources(one, Path(scratch))))
    # The same fixed instant `tests/fixtures/library/generate.py` uses, and for its reason: 003
    # makes `(size, mtime_ns)` the change signal, so a tree stamped with the current time would
    # hand every scan a different one and make "the same tree scanned twice" untestable.
    os.utime(destination, ns=(FIXED_MTIME_NS, FIXED_MTIME_NS))
    for sidecar in one.sidecars:
        beside = destination.with_name(sidecar.name)
        beside.write_text(srt_document(sidecar.cues), encoding="utf-8")
        os.utime(beside, ns=(FIXED_MTIME_NS, FIXED_MTIME_NS))
    return destination


@dataclass(frozen=True)
class BuiltMedia:
    """A generated tree, and where each declaration landed in it."""

    base: Path
    ffmpeg: str
    """The version line this tree was produced by, for a failure message that has to explain
    why an assertion about codecs is suddenly false."""

    @property
    def movies_root(self) -> Path:
        return self.base / MOVIES_ROOT

    @property
    def music_root(self) -> Path:
        return self.base / MUSIC_ROOT

    def path_of(self, one: MediaFile) -> Path:
        return self.base.joinpath(one.root, *one.path.split("/"))

    def sidecar_path_of(self, one: MediaFile, sidecar: SidecarFile) -> Path:
        """Where a declared sidecar landed - beside its film, always, which is the only place a
        stem match can find it."""
        return self.path_of(one).with_name(sidecar.name)

    def copy_into(self, destination: Path) -> BuiltMedia:
        """The whole tree, somewhere a test may write to. The cache never is."""
        shutil.copytree(self.base, destination, dirs_exist_ok=True)
        return BuiltMedia(base=destination, ffmpeg=self.ffmpeg)


def digest_of(version: str) -> str:
    """A name for one build: this matrix, this generator, this ffmpeg.

    Change any of the three and the digest moves, so a cached tree from before the change is never
    read - which is the only reason caching between runs is safe at all.
    """
    material = "\n".join([str(GENERATOR_VERSION), version, *(repr(one) for one in MATRIX)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def cache_root() -> Path:
    named = os.environ.get(CACHE_ENVIRONMENT_VARIABLE)
    base = Path(named) if named else Path(tempfile.gettempdir()) / "atrium-media-fixtures"
    return base


def build_media_files(cache: Path | None = None) -> BuiltMedia:
    """The whole matrix on disk, generated once per (matrix, ffmpeg) and reused after that.

    Published with a rename, so two processes racing - a `pytest -p xdist`, two checkouts, a
    second suite in another terminal - either both see a complete tree or one of them throws its
    own away. A half-written directory is never visible under the name anything reads.
    """
    version = ffmpeg_version()
    base = (cache or cache_root()) / digest_of(version)
    if base.is_dir():
        return BuiltMedia(base=base, ffmpeg=version)

    base.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{base.name}.building.", dir=base.parent))
    try:
        for one in MATRIX:
            generate(one, staging)
        try:
            staging.replace(base)
        except OSError:
            # Somebody else published first. Theirs is the same tree - the digest says so - and
            # ours goes in the bin.
            if not base.is_dir():
                raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return BuiltMedia(base=base, ffmpeg=version)


# ------------------------------------------------------------------------------------------
# Inspecting, for the invariant test
# ------------------------------------------------------------------------------------------


def probe(path: Path) -> Mapping[str, object]:
    """What ffprobe says about a file, parsed. The independent reader of the module docstring.

    `media/probe.py` is T2's, and this is deliberately not it: a fixture whose invariants were
    checked by the code under test would agree with itself about a wrong file.
    """
    output = _run(
        [
            binary("ffprobe"),
            "-hide_banner",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path.as_posix(),
        ]
    )
    parsed: Mapping[str, object] = json.loads(output)
    return parsed


def frame_count(path: Path) -> int:
    """How many video frames a file really holds, counted rather than read off a header.

    `nb_frames` is a container field and a fragmented mp4 - what a progressive re-encode streams
    out of a pipe - does not carry one, so a delivered stream and a source file cannot be compared
    through it. Decoding and counting answers for both, which is what AC-7's "same frame count as
    the source" needs to mean anything.
    """
    output = _run(
        [
            binary("ffprobe"),
            "-hide_banner",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "csv=p=0",
            path.as_posix(),
        ]
    )
    return int(output.strip().rstrip(","))


def subtitle_packet_seconds(path: Path, ordinal: int) -> tuple[float, ...]:
    """Every packet time of one subtitle track, in order.

    The only way to see that the cues declared are the cues muxed: a track's `codec_name` and its
    disposition survive a mux that has quietly shifted or dropped every cue in it, which is
    exactly what a bitstream starting late does to the track beside it (module docstring).
    """
    output = _run(
        [
            binary("ffprobe"),
            "-hide_banner",
            "-v",
            "error",
            "-select_streams",
            f"s:{ordinal}",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "csv=p=0",
            path.as_posix(),
        ]
    )
    return tuple(float(line.rstrip(",")) for line in output.split() if line.rstrip(","))


def keyframe_seconds(path: Path) -> tuple[float, ...]:
    """Every keyframe's presentation time, in order. What plan section 6.4 aligns segments to."""
    output = _run(
        [
            binary("ffprobe"),
            "-hide_banner",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_entries",
            "frame=pts_time",
            "-of",
            "csv=p=0",
            path.as_posix(),
        ]
    )
    return tuple(float(line.rstrip(",")) for line in output.split() if line.rstrip(","))


# ------------------------------------------------------------------------------------------
# The scanned world
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ScannedMediaWorld:
    """Two libraries, scanned by the real 003 pipeline over the generated tree.

    Scanned rather than seeded, unlike `query.py`: the whole point of this world is that the rows
    and the files agree, and a seeded row is a statement about a file nobody read.
    """

    files: BuiltMedia
    movies: Library
    music: Library
    items: Mapping[str, Item]
    """Every item both scans produced, keyed by identifier."""

    def of(self, one: MediaFile) -> Item:
        """The item this file backs - found through its sources, never assumed from its name."""
        wanted = one.path
        for candidate in self.items.values():
            if any(source.relative_path == wanted for source in candidate.sources):
                return candidate
        raise KeyError(f"nothing scanned from {wanted!r}")

    def by_type(self, item_type: ItemType) -> tuple[Item, ...]:
        return tuple(
            item
            for item in self.items.values()
            if item.type is item_type and item.removed_at is None
        )


def build_scanned_media_world(session: OrmSession, files: BuiltMedia) -> ScannedMediaWorld:
    """Declare the two libraries over the generated tree and scan them, in the caller's session.

    Fixed library identifiers, like every fixture world here, so two builds derive the same items
    (Principle VII). `config.create` would mint a random one.
    """
    libraries = LibraryRepository(session)
    movies = libraries.add(
        Library(
            id=MOVIES_LIBRARY_ID,
            name="Films",
            collection_type=CollectionType.MOVIES,
            roots=(normalise_root(str(files.movies_root)),),
        )
    )
    music = libraries.add(
        Library(
            id=MUSIC_LIBRARY_ID,
            name="Tunes",
            collection_type=CollectionType.MUSIC,
            roots=(normalise_root(str(files.music_root)),),
        )
    )
    for library in (movies, music):
        scan(library, session)

    items = ItemRepository(session)
    return ScannedMediaWorld(
        files=files,
        movies=movies,
        music=music,
        items={**items.by_library(movies.id), **items.by_library(music.id)},
    )


__all__ = [
    "BINARIES",
    "BOTH_SUBTITLE_KINDS",
    "CUES",
    "DIRECT_PLAY",
    "FILMS",
    "HIGH_RANGE",
    "HIGH_RATE_AUDIO",
    "IMAGE_SUBTITLE_CODEC",
    "LONG_TAKE",
    "MATRIX",
    "MOVIES_LIBRARY_ID",
    "MUSIC_LIBRARY_ID",
    "REJECTED_AUDIO",
    "REJECTED_CONTAINER",
    "REJECTED_VIDEO",
    "SIDECAR_CUES",
    "TRACKS",
    "TWO_PARTER_FIRST",
    "TWO_PARTER_SECOND",
    "UNCONVERTIBLE_SUBTITLE",
    "BuiltMedia",
    "Cue",
    "FfmpegFailedError",
    "FfmpegUnavailableError",
    "MediaFile",
    "ScannedMediaWorld",
    "SidecarFile",
    "SubtitleTrack",
    "binary",
    "build_media_files",
    "build_scanned_media_world",
    "ffmpeg_version",
    "frame_count",
    "generate",
    "keyframe_seconds",
    "missing_binaries",
    "pgs_bitstream",
    "probe",
    "srt_document",
    "srt_timestamp",
    "subtitle_packet_seconds",
    "subtitle_sources",
]
