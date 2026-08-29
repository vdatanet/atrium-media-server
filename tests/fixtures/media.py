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
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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
GENERATOR_VERSION = 1

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

    audio_bitrate: str | None = None
    """`None` for a lossless codec, which has no bitrate to ask for."""

    sample_format: str | None = None

    tags: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """Written into the file. Only the music entry carries any: 003 resolves an *examined* audio
    file from its tags and an unexamined one from its directory, and a track with no tags would
    hang under an album named after its folder."""

    @property
    def has_video(self) -> bool:
        return self.video_codec is not None


#: The frame rate the reference's measured 3.004 s HLS cadence comes from
#: (008 spec OQ-3, `tools/probe_hls.py`). The one entry that exists to be segmented carries it, so
#: T10's rounding arithmetic has a source that actually runs at it.
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
)

#: Everything under the music root.
TRACKS: tuple[MediaFile, ...] = (HIGH_RATE_AUDIO,)

MATRIX: tuple[MediaFile, ...] = FILMS + TRACKS


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


def _encode_command(one: MediaFile, destination: Path) -> list[str]:
    """The whole invocation for one entry, inputs first and the bit-exact flags with the output.

    The order of those flags is the load-bearing detail: on the input side they configure the
    demuxer of a lavfi source that has no metadata to make exact, and the muxer goes on stamping
    a random segment identifier and the wall clock (see the module docstring).
    """
    command = [binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]

    if one.has_video:
        command += [
            "-f",
            "lavfi",
            "-i",
            f"smptebars=size={one.width}x{one.height}"
            f":rate={one.frame_rate}:duration={one.duration_seconds}",
        ]
    command += [
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={TONE_HZ}:sample_rate={one.sample_rate}:duration={one.duration_seconds}",
    ]

    if one.has_video:
        assert one.video_encoder is not None
        command += ["-c:v", one.video_encoder, "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
        if one.video_encoder == "libx265":
            # Otherwise x265 writes its own banner to stderr whatever `-loglevel` says, and a
            # failure message that is mostly encoder greeting is a failure message nobody reads.
            command += ["-x265-params", "log-level=none"]
        if one.keyframe_interval_seconds is not None:
            command += [
                "-force_key_frames",
                f"expr:gte(t,n_forced*{one.keyframe_interval_seconds})",
            ]
        command += ["-shortest"]

    command += ["-c:a", one.audio_encoder, "-ac", str(one.channels), "-ar", str(one.sample_rate)]
    if one.audio_bitrate is not None:
        command += ["-b:a", one.audio_bitrate]
    if one.sample_format is not None:
        command += ["-sample_fmt", one.sample_format]
    for name, value in one.tags.items():
        command += ["-metadata", f"{name}={value}"]

    command += ["-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
    command += ["-f", one.muxer, str(destination)]
    return command


def generate(one: MediaFile, into: Path) -> Path:
    """Write one entry under `into`, and hand back where it landed."""
    destination = into.joinpath(one.root, *one.path.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(_encode_command(one, destination))
    # The same fixed instant `tests/fixtures/library/generate.py` uses, and for its reason: 003
    # makes `(size, mtime_ns)` the change signal, so a tree stamped with the current time would
    # hand every scan a different one and make "the same tree scanned twice" untestable.
    os.utime(destination, ns=(FIXED_MTIME_NS, FIXED_MTIME_NS))
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
    "DIRECT_PLAY",
    "FILMS",
    "HIGH_RATE_AUDIO",
    "LONG_TAKE",
    "MATRIX",
    "MOVIES_LIBRARY_ID",
    "MUSIC_LIBRARY_ID",
    "REJECTED_AUDIO",
    "REJECTED_CONTAINER",
    "REJECTED_VIDEO",
    "TRACKS",
    "TWO_PARTER_FIRST",
    "TWO_PARTER_SECOND",
    "BuiltMedia",
    "FfmpegFailedError",
    "FfmpegUnavailableError",
    "MediaFile",
    "ScannedMediaWorld",
    "build_media_files",
    "build_scanned_media_world",
    "ffmpeg_version",
    "frame_count",
    "keyframe_seconds",
    "missing_binaries",
    "probe",
]
