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

**A hit is every declared file being there, not the directory existing.** The default cache is
under `$TMPDIR`, which macOS purges *files* out of while leaving the directory structure standing;
a cache check asking about the directory calls that a hit and hands back paths that no longer open.
`BuiltMedia.is_complete` is the check, and a tree missing any one of its files is rebuilt.

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

import contextlib
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
#:
#: 3: 010 T11. A sidecar is written in the encoding it declares rather than always in UTF-8, and
#: an entry may plant an image carrying an EXIF orientation beside its film.
#:
#: 4: 012 T2. An entry may declare **no audio stream at all**, and a second kind of declaration
#: writes bytes no prober will accept. Both change what is on disk in ways the `MediaFile` rows
#: alone do not express.
GENERATOR_VERSION = 4

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

    encoding: str = "utf-8"
    """How the file's bytes are written, and it is a **fixture case** rather than a detail.

    Every sidecar in this module was `utf-8` until 010 T11, which made
    [behaviours section 5.11](../../docs/compatibility/behaviours.md) unreachable in the suite as
    well as in a differential: the reference runs a statistical charset detector over a subtitle
    file before reading a cue out of it and this server decides by a rule - a byte order mark,
    then strict UTF-8, then one `cp1252` fallback - and the two answers can only differ on a file
    that is neither UTF-8 nor `cp1252`. A world in which no such file exists cannot tell the two
    apart, so it is declared here and written out in whatever encoding the entry names.
    """


#: The tag EXIF calls `Orientation`, and the value that means *rotate 90 degrees clockwise for
#: display*. Chosen rather than 1 (`Normal`) because 1 is what every writer emits by default and
#: is indistinguishable from no tag at all: the difference 006 owes 010 is whether a resize
#: *applies* the rotation, and only a non-identity value can show it.
EXIF_ORIENTATION_TAG = 0x0112
EXIF_ORIENTATION_ROTATE_90 = 6

#: The value that means *no rotation*, carried by the backdrop beside the poster. Two images on
#: one item, encoded by one encoder, differing in the tag and in nothing else: that is what makes
#: "the resize honoured the orientation" a comparison rather than a reading of one number.
EXIF_ORIENTATION_NORMAL = 1


@dataclass(frozen=True)
class PlantedImage:
    """An image file written beside a media file, carrying an EXIF orientation.

    **The one case no remote request can reach** (006 plan section 6.8 row 1, and the
    `exif-orientation-on-resize` row of `docs/compatibility/named-comparisons.yaml`): deciding
    whether a resize honours the tag needs *a planted file in a controlled library*, which is what
    the single-use reference instance of 010 spec section 3.1 finally provides. `images.py` draws
    the images 006's own tests read; that module needs Pillow and this one is standard library
    only, so the tag is spliced into a JPEG this module has ffmpeg produce (see
    `exif_orientation_segment`).

    Named `poster.jpg` where it is meant to become an item's primary image - what both servers
    claim beside a film - which is why the name is the declaration here as it is for a sidecar.
    """

    name: str
    reason: str
    width: int
    height: int
    orientation: int = EXIF_ORIENTATION_ROTATE_90


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

    duration_seconds: float

    audio_codec: str | None = None
    audio_encoder: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    """**All four together, or none of them.** Every entry declared one until 012 T2, and the
    entry that declares none is the one this project could not otherwise build: a file whose
    stream of the *item's own kind* is missing is what makes the reference re-probe an item on
    every negotiation for ever (012 plan section 6.1), and for an audio item that means a file
    with no audio track. `has_audio` is the question, asked rather than inferred from
    `audio_codec` alone so that a half-declared entry fails loudly in `generate`."""

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

    images: tuple[PlantedImage, ...] = ()
    """Artwork written beside the file. Nothing muxes these and 003 does not walk them as media;
    they exist so that a differential has an image with an EXIF orientation to ask both servers
    about."""

    @property
    def has_video(self) -> bool:
        return self.video_codec is not None

    @property
    def has_audio(self) -> bool:
        """Whether this entry declares an audio stream, and the four fields agree or it raises.

        A declaration that names a codec and no sample rate would encode something nobody
        described, and the invariant test would then compare ffprobe's answer against a blank.
        """
        declared = [
            self.audio_codec,
            self.audio_encoder,
            self.sample_rate,
            self.channels,
        ]
        if any(one is not None for one in declared) and not all(
            one is not None for one in declared
        ):
            raise ValueError(f"{self.key} declares some of its audio fields and not others")
        return self.audio_codec is not None

    @property
    def stem(self) -> str:
        """The file's name without its extension - what a sidecar's name has to begin with for
        the reference to claim it at all (spec section 3.6)."""
        return Path(self.path).stem


@dataclass(frozen=True)
class UninspectableFile:
    """Bytes on disk that **no prober will accept**, declared the way a generated file is.

    Every other entry in this module means *ffmpeg wrote this and ffprobe agrees*; this one means
    the opposite, and it is the only way to reach the state 012 exists to close: a file in a
    library that nothing has ever successfully opened. It cannot be generated, because the scan
    that creates an item is the scan that probes it - so the state exists only where the probe
    **failed** (012 spec section 6).

    **Deterministic content, never random.** The build cache is keyed on a digest over these
    declarations, so bytes that differed per build would publish a tree under a name that
    describes a different one. `filler` is repeated to `size` and truncated, which also keeps the
    declaration readable: the reason a file is unreadable is visible in the file.

    **Never zero-length**, and that is measured rather than stylistic: 003's walk skips a file of
    no length before it can become a candidate (`library/walker.py`'s `Skip.EMPTY`), so a
    zero-length entry would produce no item at all and test nothing. The reference admits one and
    answers both a listing and a negotiation for it, which is a difference of 003's
    `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`.
    """

    key: str
    root: str
    path: str
    reason: str
    size: int = 4096
    filler: bytes = b"these bytes are not a container, which is the whole point. "

    def content(self) -> bytes:
        if self.size <= 0:
            raise ValueError(f"{self.key} declares no length, which 003's walk would skip")
        repeated = self.filler * (self.size // len(self.filler) + 1)
        return repeated[: self.size]

    @property
    def stem(self) -> str:
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

#: The Cyrillic cue text the legacy-encoded sidecar carries, and it is chosen rather than
#: decorative. `cp1251` and `cp1252` share every byte position, so these words are **valid
#: `cp1252`** and decode to different letters rather than to an error: the reference's detector
#: names `cp1251` and draws the words, this server's rule falls back to `cp1252` and draws
#: mojibake. A file that merely *failed* to decode would prove the refusal path and not the
#: divergence, which is the half behaviours section 5.11 argues a client sees directly.
LEGACY_CUES: tuple[Cue, ...] = (
    Cue(0.5, 1.25, "Здравствуйте"),
    Cue(1.75, 2.5, "Прощайте"),
)

#: What that sidecar is written in. Not `latin-1`, which decodes every byte there is and would
#: make the refusal unreachable, and not `cp1252`, which is this server's own fallback and would
#: make the two servers agree.
LEGACY_ENCODING = "cp1251"

LEGACY_SUBTITLE = MediaFile(
    key="legacy_subtitle",
    root=MOVIES_ROOT,
    path="The Legacy Encoding (2010)/The Legacy Encoding (2010).mkv",
    reason="010 spec section 3.1's fourth owed entry, and behaviours section 5.11's only "
    "reachable input: every sidecar in this module was UTF-8, so the one difference a client sees "
    "as the wrong letters on the screen had nothing to run on. In a directory of its own because "
    "a sidecar is claimed by stem, and beside a film nothing else asserts stream indices about",
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
    sidecars=(
        SidecarFile(
            name="The Legacy Encoding (2010).rus.srt",
            reason="The legacy-encoded file itself. `rus` is a language the right-to-left name "
            "read claims, so the entry exercises the naming rule as well - and the bytes are the "
            "case, which is why the encoding is declared beside the cues",
            cues=LEGACY_CUES,
            encoding=LEGACY_ENCODING,
        ),
    ),
)

PLANTED_POSTER = MediaFile(
    key="planted_poster",
    root=MOVIES_ROOT,
    path="The Planted Poster (2011)/The Planted Poster (2011).mp4",
    reason="The planted file 006 owes 010: an image carrying an EXIF orientation, beside a film, "
    "in a library this project may write to. 006's own probe says the edge is unreachable from "
    "outside - 'it needs a planted file in a controlled library' - and this is that file's film. "
    "In a directory of its own so the artwork is the film's primary image and not the library's",
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
    images=(
        PlantedImage(
            name="poster.jpg",
            reason="The item's primary image, and not square - which is the whole of what makes "
            "the tag observable: a rotation applied to a 2:3 source answers 3:2, and a rotation "
            "applied to a square one answers nothing at all",
            width=400,
            height=600,
        ),
        PlantedImage(
            name="backdrop.jpg",
            reason="The control, and the reason the same film carries two images: it is the same "
            "encoder, the same colour bars and the same splice with the tag set to `Normal`, so a "
            "difference between the two answers is attributable to the orientation and to nothing "
            "else. It is also the only Backdrop at index 0 either fixture world has, without "
            "which the indexed image case compares two refusals",
            width=640,
            height=360,
            orientation=EXIF_ORIENTATION_NORMAL,
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
VIDEOLESS = MediaFile(
    key="videoless",
    root=MOVIES_ROOT,
    path="Videoless (2010).mkv",
    reason="012 section 3.2: a **film** whose file carries no video stream. The reference's "
    "negotiation re-probes an item whose source zero holds no stream of the item's own kind, on "
    "every request and for ever, and this is the readable half of that condition - the half a "
    "trigger written as 'this source has no stored inspection' would never fire on",
    muxer="matroska",
    demuxers="matroska,webm",
    duration_seconds=4.0,
    audio_codec="aac",
    audio_encoder="aac",
    sample_rate=48000,
    channels=2,
    audio_bitrate="96k",
)

SOUNDLESS = MediaFile(
    key="soundless",
    root=MUSIC_ROOT,
    path="Quiet Corner/Unnamed Folder/01 Soundless.m4a",
    reason="012 AC-6: an **audio** item whose file carries no audio stream, which is the whole "
    "of the reference's condition for refusing the request with 400 - not the file being "
    "unreadable, which is the other fixture and a different reason. Readable on purpose: a test "
    "written against the unreadable one would pass while asserting the wrong condition. Its "
    "folders are deliberately not its tags, like the track beside it: a world where they matched "
    "could not tell a scan that opened the file from one that read the path",
    muxer="mp4",
    demuxers="mov,mp4,m4a,3gp,3g2,mj2",
    duration_seconds=4.0,
    video_codec="h264",
    video_encoder="libx264",
    width=320,
    height=240,
    frame_rate="25",
    tags={
        "artist": "Soundless Artist",
        "album_artist": "Soundless Artist",
        "album": "Soundless Album",
        "title": "Soundless",
    },
)

MISSING_HALF_FIRST = MediaFile(
    key="missing_half_first",
    root=MOVIES_ROOT,
    path="The Missing Half (2011)/The Missing Half (2011) - part1.mkv",
    reason="012 plan section 6.1: the readable half of a two-part film whose second part no "
    "prober will accept. New rather than a track added to `two_parter`, for 011 T1's reason - a "
    "file whose siblings other features assert about must not change underneath them",
    muxer="matroska",
    demuxers="matroska,webm",
    duration_seconds=4.0,
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
)

UNREADABLE = UninspectableFile(
    key="unreadable",
    root=MOVIES_ROOT,
    path="Unreadable (2012).mkv",
    reason="012 AC-1 and AC-4: the source nothing has ever opened. Four kibibytes that are not a "
    "container, in a film's own directory, so the scan makes an item for it and inspection fails",
)

LATENT = UninspectableFile(
    key="latent",
    root=MOVIES_ROOT,
    path="Latent (2013).mkv",
    reason="012 AC-2 and AC-3: the same bytes, for a test that replaces them with a real film "
    "**after** the scan. What answers the negotiation is then the only thing that has ever read "
    "those bytes successfully, which is what makes the on-demand inspection observable at all",
)

MISSING_HALF_SECOND = UninspectableFile(
    key="missing_half_second",
    root=MOVIES_ROOT,
    path="The Missing Half (2011)/The Missing Half (2011) - part2.mkv",
    reason="012 plan section 6.1, the negative case: part one is annotated and part two is not. "
    "The reference has no such item to be faithful to - it keeps the unreadable part as neither "
    "a source nor an item `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, "
    "2026-09-03]` - so what this asks is what **this** server's resolver does with it",
)

#: Bytes on disk no prober will accept. Built like the matrix and declared apart from it, because
#: every invariant the matrix has - it probes back to what it says - is false of these by design.
UNINSPECTABLE: tuple[UninspectableFile, ...] = (UNREADABLE, LATENT, MISSING_HALF_SECOND)


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
    LEGACY_SUBTITLE,
    PLANTED_POSTER,
    VIDEOLESS,
    MISSING_HALF_FIRST,
)

#: Everything under the music root.
TRACKS: tuple[MediaFile, ...] = (HIGH_RATE_AUDIO, SOUNDLESS)

MATRIX: tuple[MediaFile, ...] = FILMS + TRACKS

#: Everything this module writes, of either kind. What the builder walks and what the cache digest
#: is taken over - a tree built before an uninspectable entry existed must not be read by code
#: that expects one.
DECLARED: tuple[MediaFile | UninspectableFile, ...] = MATRIX + UNINSPECTABLE


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


#: The two JPEG markers this module has to know: the start of image, and the application segment
#: EXIF lives in. A JPEG is a marker stream, so a tag can be *added* to a finished file rather
#: than asked of the encoder - which is what lets an image with an EXIF orientation be built by a
#: module that has no image library (see `exif_orientation_segment`).
_JPEG_SOI = b"\xff\xd8"
_JPEG_APP1 = b"\xff\xe1"


def exif_orientation_segment(orientation: int) -> bytes:
    """A whole APP1 segment holding one EXIF tag: the orientation, and nothing else.

    **Written here rather than drawn by an image library**, because this module is standard
    library only - `tests/fixtures/reference_tree.py` imports it from a `tools/` program on the
    Python 3.9 floor, where Pillow does not exist - and because ffmpeg has no way to ask for an
    EXIF tag on an mjpeg output. It is the same move `pgs_bitstream` makes for a subtitle codec
    with no encoder: the format is small enough to write, so it is written.

    The payload is `Exif\\0\\0` and then a TIFF file of exactly one image file directory: the
    big-endian byte order mark, the 42 that says TIFF, the offset of the first directory, one
    entry - `Orientation`, type SHORT, one value - and a zero saying no directory follows. A
    SHORT's value fits in the entry's own four-byte field and is left-aligned in it, which is the
    one detail a hand-written directory usually gets wrong.
    """
    entry = struct.pack(">HHIHH", EXIF_ORIENTATION_TAG, 3, 1, orientation, 0)
    tiff = b"MM" + struct.pack(">HI", 42, 8) + struct.pack(">H", 1) + entry + struct.pack(">I", 0)
    payload = b"Exif\x00\x00" + tiff
    return _JPEG_APP1 + struct.pack(">H", len(payload) + 2) + payload


def with_exif_orientation(jpeg: bytes, orientation: int) -> bytes:
    """The same JPEG, with the orientation segment spliced in directly after the start marker.

    First rather than after whatever the encoder wrote, because that is where the EXIF
    specification puts APP1 and where a reader that stops at the first application segment will
    look for it.
    """
    if not jpeg.startswith(_JPEG_SOI):
        raise ValueError("not a JPEG: it does not begin with the start-of-image marker")
    return _JPEG_SOI + exif_orientation_segment(orientation) + jpeg[len(_JPEG_SOI) :]


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
    audio_input = None
    if one.has_audio:
        audio_input = inputs
        inputs += 1
        command += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={TONE_HZ}:sample_rate={one.sample_rate}"
            f":duration={one.duration_seconds}",
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
        if audio_input is not None:
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

    if one.has_audio:
        assert one.audio_encoder is not None
        command += [
            "-c:a",
            one.audio_encoder,
            "-ac",
            str(one.channels),
            "-ar",
            str(one.sample_rate),
        ]
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
        # `errors="strict"` by construction: an encoding that cannot hold the declared cues is a
        # declaration that is wrong, and a silently replaced character would be a fixture nobody
        # could tell from a decoder bug.
        beside.write_bytes(srt_document(sidecar.cues).encode(sidecar.encoding))
        os.utime(beside, ns=(FIXED_MTIME_NS, FIXED_MTIME_NS))
    for planted in one.images:
        beside = destination.with_name(planted.name)
        beside.write_bytes(planted_image(planted))
        os.utime(beside, ns=(FIXED_MTIME_NS, FIXED_MTIME_NS))
    return destination


def write_uninspectable(one: UninspectableFile, into: Path) -> Path:
    """Write one refused entry under `into`, stamped like everything else in the tree.

    No encoder, no scratch directory and no subtitle sources: the whole content is the
    declaration's. The fixed modification time matters here for the same reason it matters for a
    generated file - 003 makes `(size, mtime_ns)` the change signal, and a tree stamped with the
    clock would make "the same tree scanned twice" untestable.
    """
    destination = into.joinpath(one.root, *one.path.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(one.content())
    os.utime(destination, ns=(FIXED_MTIME_NS, FIXED_MTIME_NS))
    return destination


def planted_image(planted: PlantedImage) -> bytes:
    """One planted image's bytes: colour bars encoded as a JPEG, with an EXIF orientation in it.

    Encoded through ffmpeg rather than drawn, for the reason the media beside it is: this module
    has no image library and must not grow one. The tag is spliced in afterwards, which is what
    makes the result independent of whether the encoder would have written an EXIF block at all.
    """
    with tempfile.TemporaryDirectory(prefix="atrium-planted-image.") as scratch:
        drawn = Path(scratch) / "drawn.jpg"
        _run(
            [
                binary("ffmpeg"),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"smptebars=size={planted.width}x{planted.height}:rate=1:duration=1",
                "-frames:v",
                "1",
                "-fflags",
                "+bitexact",
                "-flags:v",
                "+bitexact",
                "-f",
                "mjpeg",
                str(drawn),
            ]
        )
        return with_exif_orientation(drawn.read_bytes(), planted.orientation)


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

    def path_of(self, one: MediaFile | UninspectableFile) -> Path:
        """Where a declaration landed, of either kind: the two agree about `root` and `path`
        and about nothing else."""
        return self.base.joinpath(one.root, *one.path.split("/"))

    def sidecar_path_of(self, one: MediaFile, sidecar: SidecarFile) -> Path:
        """Where a declared sidecar landed - beside its film, always, which is the only place a
        stem match can find it."""
        return self.path_of(one).with_name(sidecar.name)

    def image_path_of(self, one: MediaFile, planted: PlantedImage) -> Path:
        """Where a declared planted image landed - beside its film, for the same reason."""
        return self.path_of(one).with_name(planted.name)

    def declared_files(self) -> tuple[Path, ...]:
        """Every file a complete tree holds: each declaration, and the sidecars and images that
        landed beside it.

        Derived from `DECLARED` rather than from a walk of the tree, so it says what *should* be
        there - which is the only form of the question `is_complete` can be asked in.
        """
        paths: list[Path] = []
        for one in DECLARED:
            paths.append(self.path_of(one))
            if isinstance(one, MediaFile):
                paths.extend(self.sidecar_path_of(one, sidecar) for sidecar in one.sidecars)
                paths.extend(self.image_path_of(one, planted) for planted in one.images)
        return tuple(paths)

    def is_complete(self) -> bool:
        """Whether every declared file is really on disk.

        **The question the cache has to ask, and asking it about the directory is a bug.** macOS
        purges files out of `$TMPDIR` and leaves the directory structure standing, so a check on
        `base.is_dir()` goes on saying *hit* over a tree whose files are gone and the caller gets
        paths that no longer open - about thirty ffmpeg-dependent tests failing with
        `FileNotFoundError`, three times in one day, each worked around with a fresh cache
        directory.

        Every file, not one of them: a purge that took all but one leaves a tree exactly as
        unusable as a purge that took everything, and a check the survivor satisfied would be the
        same bug at a smaller size. `is_file` and not a length, because what a purge removes is the
        file - and a size assertion here would be this module's declarations written twice.
        """
        return all(path.is_file() for path in self.declared_files())

    def copy_into(self, destination: Path) -> BuiltMedia:
        """The whole tree, somewhere a test may write to. The cache never is."""
        shutil.copytree(self.base, destination, dirs_exist_ok=True)
        return BuiltMedia(base=destination, ffmpeg=self.ffmpeg)


def declared_media_files(base: Path) -> tuple[Path, ...]:
    """Every file the media world holds, once it stands under `base`.

    The same question `BuiltMedia.is_complete` asks, for a caller holding a *copy* of the tree and
    no build of its own - `tests/fixtures/reference_tree.py` asking whether the media subtree of a
    fixture tree composed on an earlier run is still there. Which files should be present is a
    property of the declarations and not of the encoder, so this takes a path and nothing else; the
    empty version line never leaves this function.
    """
    return BuiltMedia(base=base, ffmpeg="").declared_files()


def digest_of(version: str) -> str:
    """A name for one build: this matrix, this generator, this ffmpeg.

    Change any of the three and the digest moves, so a cached tree from before the change is never
    read - which is the only reason caching between runs is safe at all.
    """
    material = "\n".join([str(GENERATOR_VERSION), version, *(repr(one) for one in DECLARED)])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def cache_root() -> Path:
    named = os.environ.get(CACHE_ENVIRONMENT_VARIABLE)
    base = Path(named) if named else Path(tempfile.gettempdir()) / "atrium-media-fixtures"
    return base


def _discard(base: Path) -> None:
    """Take a tree out from under the published name, then delete it.

    The rename is what makes this safe to do while another process is reading: the directory it
    holds open goes on existing until it lets go, and the name resolved after this call is either
    missing or a complete tree. Both steps are best-effort - if somebody published over the name
    first there is nothing here to sweep, and the caller's retry says so.
    """
    doomed = Path(tempfile.mkdtemp(prefix=f"{base.name}.purged.", dir=base.parent))
    with contextlib.suppress(OSError):
        base.replace(doomed / base.name)
    shutil.rmtree(doomed, ignore_errors=True)


def _publish(staging: Path, built: BuiltMedia) -> None:
    """Move a finished build under the name everything reads, or establish that it need not be.

    A rename cannot land on a name a directory already holds, and there are two ways one does.
    Somebody published first, and theirs is the same tree - the digest says so - so ours goes in
    the bin. Or what stands there is a **purged** tree, whose empty directories survived the files:
    that one is swept and the publish retried, because leaving it would mean the rebuild this
    function was called for is thrown away and the caller handed the purged tree back again.
    """
    for last in (False, True):
        try:
            staging.replace(built.base)
            return
        except OSError:
            if built.is_complete():
                return
            if last:
                raise
            _discard(built.base)


def build_media_files(cache: Path | None = None) -> BuiltMedia:
    """The whole matrix on disk, generated once per (matrix, ffmpeg) and reused after that.

    Published with a rename, so two processes racing - a `pytest -p xdist`, two checkouts, a
    second suite in another terminal - either both see a complete tree or one of them throws its
    own away. A half-written directory is never visible under the name anything reads.

    **The cache is hit on the files and not on the directory**, which is `BuiltMedia.is_complete`
    and the reason it exists: the default cache lives under `$TMPDIR`, macOS purges files out of
    there and leaves the directories behind, and a tree in that state is rebuilt rather than
    reported as a hit.
    """
    version = ffmpeg_version()
    built = BuiltMedia(base=(cache or cache_root()) / digest_of(version), ffmpeg=version)
    if built.is_complete():
        return built

    built.base.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{built.base.name}.building.", dir=built.base.parent))
    try:
        for one in MATRIX:
            generate(one, staging)
        for refused in UNINSPECTABLE:
            write_uninspectable(refused, staging)
        _publish(staging, built)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return built


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


def extraction_offset_seconds(path: Path) -> float:
    """What this ffmpeg build adds to every timestamp it extracts out of this file.

    **A property of the tool and of the audio track, not of the subtitles.** ffmpeg expresses an
    output on a timeline that starts at the *container's* start time, so an extracted subtitle
    comes out at `the time the file states it` minus that start time - and the start time is the
    earliest of all the streams'. An AAC encoder emits one frame of priming before the first real
    sample, which lands in Matroska as a first audio timestamp of **-21 ms** (1024 samples at the
    48 kHz these entries declare is 21.33 ms), so the container starts before zero and every cue
    of the subtitle track beside it is extracted 21 ms **late**.

    It is one build's reading and not another's: ffmpeg 6.1 reports that negative start time for
    these files and ffmpeg 9.0 reports zero **for the same bytes**, so this is the demuxer's
    handling of the codec delay rather than anything the mux wrote differently. Measured on
    2026-08-30 across both, with `flac` audio and with no audio at all answering zero on both -
    which is what identifies the priming as the cause.

    So a test that asserts extracted cue times reads this and adds it, rather than asserting a
    literal that is true of one build. That is a derivation and not a tolerance: it is exact on
    every build, and any real failure - a dropped cue, the wrong stream mapped, a mangled timing -
    still fails.
    """
    output = _run(
        [
            binary("ffprobe"),
            "-hide_banner",
            "-v",
            "error",
            "-show_entries",
            "format=start_time",
            "-of",
            "csv=p=0",
            path.as_posix(),
        ]
    )
    stated = output.strip().rstrip(",")
    return 0.0 if stated in {"", "N/A"} else -float(stated)


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


__all__ = [
    "BINARIES",
    "BOTH_SUBTITLE_KINDS",
    "CUES",
    "DECLARED",
    "DIRECT_PLAY",
    "EXIF_ORIENTATION_NORMAL",
    "EXIF_ORIENTATION_ROTATE_90",
    "EXIF_ORIENTATION_TAG",
    "FILMS",
    "HIGH_RANGE",
    "HIGH_RATE_AUDIO",
    "IMAGE_SUBTITLE_CODEC",
    "LATENT",
    "LEGACY_CUES",
    "LEGACY_ENCODING",
    "LEGACY_SUBTITLE",
    "LONG_TAKE",
    "MATRIX",
    "MISSING_HALF_FIRST",
    "MISSING_HALF_SECOND",
    "MOVIES_LIBRARY_ID",
    "MUSIC_LIBRARY_ID",
    "PLANTED_POSTER",
    "REJECTED_AUDIO",
    "REJECTED_CONTAINER",
    "REJECTED_VIDEO",
    "SIDECAR_CUES",
    "SOUNDLESS",
    "TRACKS",
    "TWO_PARTER_FIRST",
    "TWO_PARTER_SECOND",
    "UNCONVERTIBLE_SUBTITLE",
    "UNINSPECTABLE",
    "UNREADABLE",
    "VIDEOLESS",
    "BuiltMedia",
    "Cue",
    "FfmpegFailedError",
    "FfmpegUnavailableError",
    "MediaFile",
    "PlantedImage",
    "SidecarFile",
    "SubtitleTrack",
    "UninspectableFile",
    "binary",
    "build_media_files",
    "declared_media_files",
    "exif_orientation_segment",
    "extraction_offset_seconds",
    "ffmpeg_version",
    "frame_count",
    "generate",
    "keyframe_seconds",
    "missing_binaries",
    "pgs_bitstream",
    "planted_image",
    "probe",
    "srt_document",
    "srt_timestamp",
    "subtitle_packet_seconds",
    "subtitle_sources",
    "with_exif_orientation",
    "write_uninspectable",
]
