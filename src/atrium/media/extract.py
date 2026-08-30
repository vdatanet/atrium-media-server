# SPDX-License-Identifier: GPL-3.0-or-later
"""Making one subtitle track readable: the only module in this feature that starts a process.

`media/subtitles.py` beside it is values from end to end - parse, window, render - and it begins
once the text is in hand. Getting the text in hand is this module, and it is the whole of what
ffmpeg does for subtitles (011 plan section 6.7): nothing here converts a format, filters a cue or
writes a document.

    readable(...) -> (the text of the track, the format that text is in)

**Three inputs, one answer, and the branch is the reference's own chain** `[source:
MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:195-254 @ v10.11.11]`:

* a **file beside the media** whose format the parsers cover is read from its own bytes, with its
  encoding detected rather than assumed - a subtitle file is the one input in this project that is
  routinely not UTF-8;
* an **embedded** track, or one inside an external `.mks`, is extracted by one ffmpeg invocation;
* a file beside the media in a text format the parsers do not cover is normalised to `srt` by one
  ffmpeg invocation, which is the reference's fallback for the same case;
* an **image** track raises before any of that. The reference attempts the extraction and refuses
  about twenty seconds later; Atrium answers the same status and the same bytes without starting a
  process, which is the one place this feature is knowingly faster rather than identical.

## Four things the plan's four lines about this module did not say

Each was read off the reference in this change, and the first is the only one a client can see:

1. **The extracted artefact is not what ffmpeg wrote.** After extracting to `.ass` the reference
   replaces `,Arial,` with `,Arial Unicode MS,` in the finished file, and rewrites it **only if
   that changed something** `[source: SubtitleEncoder.cs:928-957 @ v10.11.11]`. The rewrite is
   what puts a **byte order mark** on the file, because the writer it goes back out through emits
   the UTF-8 preamble where ffmpeg's muxer emits none - so the font substitution and the mark
   arrive together or not at all. Measured on the wire, where `Stream.ass` on an embedded `ass`
   track hands back this artefact verbatim through the same-format short circuit: a style line
   reading `Style: Default,Arial Unicode MS,30,...` under a leading `\\xef\\xbb\\xbf`
   `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.
2. **The codec argument is `copy` wherever the codec can be copied, and only otherwise `srt`.**
   Plan section 6.7's *"extracted by one ffmpeg invocation to `srt`"* names the **format** of the
   artefact, which is a different question from what `-c:s` is given: `ass`, `ssa`, `srt` and
   `subrip` are copied out as they are, and everything else is encoded to SubRip `[source:
   SubtitleEncoder.cs:485-493, 629 @ v10.11.11]`. Asking `-c:s srt` for a `subrip` track
   would decode and re-encode every cue, which is a different document for no reason.
3. **The reference extracts every extractable track of the source in one invocation, not one.**
   `ExtractAllExtractableSubtitles` collects each stream that has no artefact yet, takes a lock
   per output path and issues a single command with a `-map`/output pair each `[source:
   SubtitleEncoder.cs:495-556, 608-654 @ v10.11.11]`. This module extracts the one track it was
   asked for. Nothing observable turns on it - the artefacts are identical either way - and it is
   why a first fetch here costs one track where the reference pays for all of them at once.
4. **A non-zero exit is not by itself a failure there.** The reference fails a run only when the
   output is missing or empty, and treats any exit code it did not cancel as possibly fine
   `[source: SubtitleEncoder.cs:704-763 @ v10.11.11]`. Reproduced: the artefact is the test. The
   encoder's own complaint is logged by the ledger and quoted in the refusal, rather than being
   what decides it.

## The cache, and the lock that is the whole reason it has one

The artefact lands in `cache/subtitles/<digest>.<format>`, the digest over the media file's
`(library_id, relative_path)`, the **extracted file's own** `(size, mtime_ns)`, the stream's
**wire** index and the extracted format - written into a private directory beside it and published
by rename, which is `images/cache.py`'s shape and 006's argument for it. Not a `TranscodeSession`:
an extracted subtitle has no play session, no ping timer, no throttle and no segment deletion, and
it is worth keeping across a restart where a session's scratch is cleared at every one (plan
section 10).

**It is still in the ledger**, because every process this server starts is, and because the burst
is real: a client handed a subtitle playlist of a hundred windows fetches them in a burst, and a
hundred requests that each started an ffmpeg for the same track would take the machine down. One
artefact per (file, stream, format) and a **per-digest lock** turns that burst into one extraction
and ninety-nine waits. The reference locks the same thing under the same name - its own keyed
locker, on the output path.

See specs/011-subtitle-delivery/plan.md sections 5 and 6.7.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Final

from atrium.domain.media import DeliveredFile, InspectedStream, MediaInspection, StreamKind
from atrium.media import ffmpeg, subtitles
from atrium.media.info import is_text_subtitle

logger = logging.getLogger(__name__)

#: `<data-dir>/cache/subtitles`. The parent is `DataPaths.cache`, and the caller composes the two
#: the way `api/images.py` composes the image cache's - one directory name, in one place.
DIRECTORY: Final = "subtitles"

#: How long one extraction may run before it is abandoned, which is the reference's own bound
#: `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:694 @ v10.11.11]`. Long
#: because the work is a full demux of a film for a few kilobytes of text, and a track at the end
#: of a large file is minutes rather than seconds - measured at 39.8 s for one `ass` track of one
#: film on the reference `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11,
#: 2026-08-30]`. A process still running at the bound is killed by the ledger and the request
#: answers the same refusal a failed extraction does.
TIMEOUT_SECONDS: Final = 30 * 60

#: Codecs whose bitstream is copied out rather than encoded `[source: SubtitleEncoder.cs:485-493
#: @ v10.11.11]`. `pgssub` is on the reference's list and not on this one: an image track never
#: reaches a command here.
COPYABLE_CODECS: Final[frozenset[str]] = frozenset({"ass", "ssa", "srt", "subrip"})

#: Codecs whose artefact keeps the codec's own spelling. Everything else is extracted to SubRip
#: `[source: SubtitleEncoder.cs:458-470 @ v10.11.11]`.
OWN_FORMAT_CODECS: Final[frozenset[str]] = frozenset({"ass", "ssa"})

#: What every other track is extracted to, and what an unparseable text file beside the media is
#: normalised to. Same source.
DEFAULT_FORMAT: Final = "srt"

#: The container the reference treats as a file beside the media that still has to be demuxed:
#: everything else external is bytes to read, an `.mks` is a Matroska file to extract from.
MATROSKA_SUBTITLE_SUFFIX: Final = ".mks"

#: The font substitution the reference performs on an extracted `.ass`, verbatim `[source:
#: SubtitleEncoder.cs:943 @ v10.11.11]`. Applied to the artefact and not to a rendered document,
#: because that is where it happens: a converted answer goes through this project's own writer and
#: never sees it.
ASS_FONT: Final = ",Arial,"
ASS_FONT_REPLACEMENT: Final = ",Arial Unicode MS,"

#: Byte order marks, longest first - the five a text file can begin with, and the codec each one
#: names. Sniffed before anything is guessed, because a mark is a statement rather than an
#: inference, and the four-byte forms are tested first because both of them **begin with** a
#: two-byte one.
#:
#: Each names the codec that **consumes** the mark rather than the one that would leave it in the
#: text, which is what the reference's own reader does with a preamble it detected - and it
#: matters beyond tidiness: the text this function answers is what a fetch of the format the file
#: is already in hands back, so a mark left in would be a mark on the wire that the reference does
#: not send.
_MARKS: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
)

#: What a text file that is neither marked nor valid UTF-8 is read as. **A choice, and the one
#: place this module is weaker than the reference**, which runs a statistical detector over the
#: bytes and can name any of some thirty encodings. This project has no such detector and the
#: decision - taken at 011 T6 - was to record the limit rather than add a runtime dependency for
#: it, so the fallback is the encoding a Western subtitle file that is not UTF-8 almost always is.
#: It is a fallback that can *fail*, which is deliberate: `latin-1` would decode every byte
#: sequence there is and turn an unreadable file into plausible nonsense, where this one leaves
#: the refusal reachable.
#:
#: **This is an accepted gap and not a safe divergence**, because what differs is the cue text a
#: player draws: `docs/compatibility/behaviours.md` section 5.11, with the closing mechanism -
#: a detector behind `_detect`, its dependency argued in an ADR on the day a real library needs
#: one.
FALLBACK_ENCODING: Final = "cp1252"

#: The encodings ffmpeg converts on its own and refuses to be told about - stating one answers
#: *"do not specify a character encoding"* and the conversion fails `[source:
#: SubtitleEncoder.cs:356-360 @ v10.11.11]`. UTF-8 is here for the other reason: it is what
#: ffmpeg already assumes.
_CHARSET_NOT_STATED: Final[frozenset[str]] = frozenset({"utf-8", "utf-8-sig", "utf-16", "utf-32"})


class ImageSubtitleError(RuntimeError):
    """This track is pictures, and no conversion can make it text.

    Its own class rather than a production failure, because the two answer differently: the
    reference refuses an image track asked for as text with `400` after attempting the extraction,
    and refuses a failed extraction with `500` (spec section 3.7). Raised before any process
    starts, which is the whole of the difference - the same status and the same bytes, sooner.
    """


async def readable(
    ledger: ffmpeg.ProductionLedger,
    cache: Path,
    file: DeliveredFile,
    inspection: MediaInspection,
    stream: InspectedStream,
) -> tuple[str, str]:
    """The text of one subtitle track, and the format that text is in.

    `cache` is the subtitle cache directory - `<data-dir>/cache/subtitles`, composed by the caller
    the way `api/images.py` composes the image one. `stream` carries the **wire** index, which is
    what names the cache entry; the demuxer index inside the file it came from is `file_index`,
    and that is the only number a command may map (plan section 5).

    Raises `ImageSubtitleError` for a track made of pictures, before anything is opened, and
    `ffmpeg.ProductionError` for everything else that can go wrong: no ffmpeg, a file that is
    gone, an extraction that produced nothing, text nothing can decode.
    """
    if stream.kind is not StreamKind.SUBTITLE:
        raise ffmpeg.ProductionError(
            f"stream {stream.index} of {file.relative_path} is {stream.kind.value} and not a "
            f"subtitle, so there is nothing to make readable"
        )
    if not is_text_subtitle(stream):
        raise ImageSubtitleError(
            f"stream {stream.index} of {file.relative_path} is an image subtitle "
            f"({stream.codec}), which no conversion can turn into text"
        )

    external = _external_file(file, stream)
    if external is not None:
        current = _suffix_format(external)
        if external.suffix.lower() != MATROSKA_SUBTITLE_SUFFIX and current in subtitles.READABLE:
            return _read(external), current

    return await _extracted(ledger, cache, file, inspection, stream, external)


# ------------------------------------------------------------------------------------------
# Where the track is, and what it will be called
# ------------------------------------------------------------------------------------------


def _external_file(file: DeliveredFile, stream: InspectedStream) -> Path | None:
    """The file beside the media this stream came out of, or `None` for one the container holds.

    Rebuilt under the library's first root, which is the rule `media/info.py` and
    `DeliveredFile.absolute_path` already follow for every stored relative path.
    """
    if stream.external_path is None or not file.library_roots:
        return None
    return Path(file.library_roots[0].rstrip("/")).joinpath(*stream.external_path.split("/"))


def _suffix_format(path: Path) -> str:
    """A file's format as the reference reads it: its extension without the dot, lower case
    `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:217-218 @ v10.11.11]`."""
    return path.suffix.lstrip(".").lower()


def _artefact_format(stream: InspectedStream) -> str:
    """What an extraction of this track produces: the codec's own spelling for the two SubStation
    ones, SubRip for everything else."""
    codec = (stream.codec or "").lower()
    return codec if codec in OWN_FORMAT_CODECS else DEFAULT_FORMAT


def _output_codec(stream: InspectedStream) -> str:
    """What `-c:s` is given: a copy where the bitstream can be copied, SubRip where it cannot."""
    return "copy" if (stream.codec or "").lower() in COPYABLE_CODECS else DEFAULT_FORMAT


def _digest(
    file: DeliveredFile, signal: tuple[int, int], index: int, fmt: str, source: Path
) -> str:
    """The name this artefact is stored under.

    Every part is a value that changes the bytes: which file, **which version of it** - the change
    signal 003 stores and 008 compares - which stream of it, and what the extraction produced. A
    key without the change signal would serve the previous file's subtitles for as long as the
    artefact survived, which is the mistake `images/cache.py`'s tag exists to prevent.

    **The signal is the extracted file's own, which is not always the media file's.** Plan section
    6.7 names the media file's, and that is right for a track inside the container; for a track
    read out of an `.mks` or a sidecar the ffmpeg fallback normalises, the bytes being read are the
    *sidecar's*, and a sidecar can be replaced without the film being touched at all. Keyed on the
    film's signal alone, the next fetch after that would answer the old subtitle for as long as the
    artefact survived - the same staleness the tag paragraph above exists to rule out, one file to
    the side.
    """
    parts = (
        file.library_id or "",
        file.relative_path,
        source.name,
        str(signal[0]),
        str(signal[1]),
        str(index),
        fmt,
    )
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------
# Extraction
# ------------------------------------------------------------------------------------------


async def _extracted(
    ledger: ffmpeg.ProductionLedger,
    cache: Path,
    file: DeliveredFile,
    inspection: MediaInspection,
    stream: InspectedStream,
    external: Path | None,
) -> tuple[str, str]:
    """The artefact for this track, produced if it is not already there.

    The lock is held across the existence check *and* the production, which is what makes a burst
    of a hundred requests one extraction: a version that checked first and locked afterwards would
    let all hundred miss together.
    """
    normalising = external is not None and external.suffix.lower() != MATROSKA_SUBTITLE_SUFFIX
    fmt = DEFAULT_FORMAT if normalising else _artefact_format(stream)
    source = external if external is not None else _media_file(file)
    signal = (
        (inspection.size, inspection.mtime_ns) if external is None else _change_signal(external)
    )
    target = cache / f"{_digest(file, signal, stream.index, fmt, source)}.{fmt}"

    async with _locked(target.name):
        if not _written(target):

            def command(destination: Path) -> list[str]:
                """The invocation, built against wherever the bytes are actually going. The
                destination is not the cache entry: production writes into a private directory and
                the finished file is renamed into place, so nothing ever reads a half-written one.
                """
                if normalising:
                    return _normalise_command(source, destination)
                return _extract_command(source, stream, destination)

            await _produce(ledger, command, target, converting=normalising)
    return _read(target), fmt


def _change_signal(path: Path) -> tuple[int, int]:
    """A file's size and modification time, the pair 003 uses everywhere as "which version".

    A file the scan recorded and that is gone by the time somebody asks for it is plan section 7's
    own row, and this is where it is noticed: the refusal is the one a failed extraction answers.
    """
    try:
        stated = path.stat()
    except OSError as exc:
        raise ffmpeg.ProductionError(
            f"the subtitle file at {path} cannot be read: {exc.strerror}"
        ) from exc
    return stated.st_size, stated.st_mtime_ns


def _media_file(file: DeliveredFile) -> Path:
    absolute = file.absolute_path()
    if absolute is None:
        raise ffmpeg.ProductionError(
            f"{file.relative_path} is in a library that declares no root, so there is no file to "
            f"extract a subtitle from"
        )
    return Path(absolute)


def _extract_command(source: Path, stream: InspectedStream, target: Path) -> list[str]:
    """One track out of a container, as the reference asks for it.

    `-an -vn` because the output is a subtitle file and stream selection would otherwise offer it
    a video and an audio track it cannot hold; `-flush_packets 1` because the reference decides a
    run succeeded by looking at the file, and a muxer holding its last cue in a buffer is a file
    that looks short. `-map 0:{file_index}` and never `0:{index}`: the wire number is what the
    request named and the demuxer number is what ffmpeg counts (plan section 5).
    """
    return [
        ffmpeg.executable(),
        *ffmpeg.PREAMBLE,
        "-i",
        str(source),
        "-map",
        f"0:{stream.file_index}",
        "-an",
        "-vn",
        "-c:s",
        _output_codec(stream),
        "-flush_packets",
        "1",
        str(target),
    ]


def _normalise_command(source: Path, target: Path) -> list[str]:
    """A text file the parsers here do not cover, rewritten as SubRip.

    **The reference's fallback reaches fewer files than this one does.** Its parser table is built
    by reflection over a subtitle library's whole set of formats, so it parses some dozens of
    extensions natively `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:96-134 @ v10.11.11]` where this
    project reads three families and hands everything else to ffmpeg. The cues are the same
    either way; what differs is which side of the same fallback a `.smi` lands on.

    The detected encoding is stated only where ffmpeg would not work it out and would not refuse
    to be told - which is the rule the reference's two special cases each express one half of.
    """
    charset = _encoding_of(source)
    stating = [] if charset in _CHARSET_NOT_STATED else ["-sub_charenc", charset]
    return [
        ffmpeg.executable(),
        *ffmpeg.PREAMBLE,
        *stating,
        "-i",
        str(source),
        "-c:s",
        DEFAULT_FORMAT,
        str(target),
    ]


async def _produce(
    ledger: ffmpeg.ProductionLedger,
    command: Callable[[Path], list[str]],
    target: Path,
    *,
    converting: bool,
) -> None:
    """Run one invocation to its end and publish what it wrote, or refuse and leave nothing.

    Written into a private directory beside the target and renamed into place, so a reader sees
    either nothing or the whole artefact, and a run that died halfway leaves no file for the next
    request to trust. The rename is atomic only within a filesystem, which is why the scratch
    cannot go to the system temporary directory.

    **The process is finished in a `finally`**, which is what keeps the ledger honest when the
    request that wanted this subtitle goes away halfway through: the ledger is the set of processes
    this server has started *and not reaped*, and a cancelled caller that left one running would
    make it a lie in the direction that matters.
    """
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(dir=target.parent, prefix=".extracting-"))
    except OSError as exc:
        raise ffmpeg.ProductionError(
            f"the subtitle cache at {target.parent} cannot be written ({exc.strerror}), so no "
            f"track can be made readable"
        ) from exc

    written = scratch / target.name
    try:
        argv = command(written)
        running = await ledger.start(argv, to_pipe=False)
        try:
            await asyncio.wait_for(running.process.wait(), timeout=TIMEOUT_SECONDS)
        except TimeoutError:
            logger.warning(
                "a subtitle extraction was abandoned after %s seconds: %s",
                TIMEOUT_SECONDS,
                " ".join(argv),
            )
        finally:
            # After the finish rather than before it: `finish` waits for the drain, which is where
            # the encoder's last words arrive.
            await ledger.finish(running)
        # The artefact is the test, not the exit code: the reference fails a run only where the
        # output is missing or empty, and a subtitle muxer has more than one way to say "nothing
        # to do" while exiting cleanly.
        if not _written(written):
            complaints = " / ".join(running.complaints)
            raise ffmpeg.ProductionError(
                f"extracting a subtitle from {argv[argv.index('-i') + 1]} produced nothing"
                + (f": {complaints}" if complaints else "")
            )
        _substitute_font(written, whatever_it_is_called=converting)
        written.replace(target)
    except OSError as exc:
        raise ffmpeg.ProductionError(
            f"the extracted subtitle could not be stored at {target}: {exc.strerror}"
        ) from exc
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _written(path: Path) -> bool:
    """Whether there is an artefact here worth reading. Empty is missing, which is the
    reference's own test and the reason a failed run leaves nothing behind."""
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def _substitute_font(path: Path, *, whatever_it_is_called: bool) -> None:
    """The reference's own last act on a file it has just produced, and its consequence.

    The substitution is a plain replacement over the finished file, and the file is rewritten
    **only where it changed something** - so a track whose style names another font keeps
    ffmpeg's bytes exactly. Where it did change, the rewrite goes back out through a writer that
    emits the UTF-8 preamble, which is why an extracted `.ass` that had an Arial style arrives
    with a byte order mark and one that did not arrives without: measured on the wire, where this
    artefact is what the same-format short circuit hands back `[probe:
    tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`.

    **The two callers test different things and that is the reference's own asymmetry**, not a
    simplification: after an *extraction* it looks at the output's name and acts on one ending in
    the three characters `ass` - so `.ssa` is passed over - while after a *conversion* it acts on
    the output whatever it is called, which in that branch is always an `.srt` `[source:
    MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:452, 751 @ v10.11.11]`. The second is
    a substitution that changes nothing on any real file and would change a cue that happened to
    contain the six characters being replaced; reproduced rather than tidied, because "no real
    file does this" is an argument about libraries and not about the server.
    """
    if not whatever_it_is_called and path.suffix.lower() != ".ass":
        return
    text = _read(path)
    replaced = text.replace(ASS_FONT, ASS_FONT_REPLACEMENT)
    if replaced != text:
        path.write_bytes(subtitles.BYTE_ORDER_MARK + replaced.encode("utf-8"))


# ------------------------------------------------------------------------------------------
# Reading text off a disk
# ------------------------------------------------------------------------------------------


def _read(path: Path) -> str:
    """One subtitle file as text, in whatever encoding it turns out to be in.

    Bytes first and decoded here rather than through a text-mode read, because a text-mode read
    translates line endings - and the bytes of a file whose format is already the one being asked
    for are answered verbatim, so `\\r\\n` inside a cue is part of the answer rather than noise
    (plan section 6.7 step 1).
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ffmpeg.ProductionError(
            f"the subtitle at {path} cannot be read: {exc.strerror}"
        ) from exc
    encoding = _detect(raw)
    try:
        return raw.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise ffmpeg.ProductionError(
            f"the subtitle at {path} is not text in any encoding this server can read; it was "
            f"read as {encoding}"
        ) from exc


def _encoding_of(path: Path) -> str:
    """What the bytes of this file say they are, for a command that has to be told."""
    try:
        return _detect(path.read_bytes())
    except OSError as exc:
        raise ffmpeg.ProductionError(
            f"the subtitle at {path} cannot be read: {exc.strerror}"
        ) from exc


def _detect(raw: bytes) -> str:
    """A byte order mark, then UTF-8, then the declared fallback.

    Three steps and no statistics, which is the honest description of it: the reference runs a
    detector over the bytes and can name any of some thirty encodings, and this names four with
    certainty and guesses once. Every subtitle file that is UTF-8, or that carries a mark, is
    read identically on both; a legacy file outside the fallback's range decodes to different
    text here, or to none.

    **Decided and recorded, not deferred**: `docs/compatibility/behaviours.md` section 5.11 is the
    accepted gap, and it is a gap rather than one of section 3's deliberate divergences because
    what differs is the text a player draws, which is the one thing a client cannot fail to
    observe. The closing mechanism is a detector here, behind this function.
    """
    for mark, encoding in _MARKS:
        if raw.startswith(mark):
            return encoding
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return FALLBACK_ENCODING
    return "utf-8"


# ------------------------------------------------------------------------------------------
# One extraction per artefact, however many callers asked for it
# ------------------------------------------------------------------------------------------

#: The locks in use right now, by artefact name, with the number of callers waiting on each. Both
#: are emptied as the last caller leaves, so nothing accumulates across a server's life and no
#: lock outlives the event loop it was made on. Reached and incremented in the same statement
#: sequence, with no `await` between, which is what makes "get or create" safe on one loop.
_locks: dict[str, asyncio.Lock] = {}
_waiting: dict[str, int] = {}


@contextlib.asynccontextmanager
async def _locked(key: str) -> AsyncIterator[None]:
    """Hold the lock for one artefact, and forget the lock when nobody is left holding it."""
    lock = _locks.get(key)
    if lock is None:
        lock = _locks[key] = asyncio.Lock()
    _waiting[key] = _waiting.get(key, 0) + 1
    try:
        async with lock:
            yield
    finally:
        _waiting[key] -= 1
        if not _waiting[key]:
            del _waiting[key]
            del _locks[key]


__all__ = [
    "ASS_FONT",
    "ASS_FONT_REPLACEMENT",
    "COPYABLE_CODECS",
    "DEFAULT_FORMAT",
    "DIRECTORY",
    "FALLBACK_ENCODING",
    "MATROSKA_SUBTITLE_SUFFIX",
    "OWN_FORMAT_CODECS",
    "TIMEOUT_SECONDS",
    "ImageSubtitleError",
    "readable",
]
