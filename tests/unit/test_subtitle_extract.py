# SPDX-License-Identifier: GPL-3.0-or-later
"""`media/extract.py`: one process per artefact, one artefact per track, and none for a picture.

011 T6. The module has one function and four branches, and what is asserted here is the property
each branch exists for rather than the branch itself:

* the cues that come back are **the ones the fixture declared**, which is the only thing that says
  the right stream was extracted from the right file - a command that mapped the wrong track
  succeeds, writes a file and answers somebody else's subtitles;
* a second call for the same key **starts no process**, asserted against a ledger that counts
  rather than against a stopwatch (AC-14);
* a hundred calls at once start **one**, which is the burst a subtitle playlist of a hundred
  windows produces and the reason the lock exists at all;
* an image track raises **before the ledger is touched**, which is the whole of Atrium's
  difference from the reference here: the same status and the same bytes, without the twenty
  seconds of extraction that cannot succeed.

**The ledger is a counting subclass and not a mock.** The processes are real, the artefacts are
real files, and what is instrumented is the one question a test cannot otherwise ask: *was a
process started this time?* A mock would also have to answer *what did ffmpeg write*, which is
the part that has to be true.

## An extracted cue's time is a function of the ffmpeg that extracted it

Found by CI, which runs the distribution's ffmpeg 6.1 where this machine runs 9.0: **every cue of
the embedded track came back 21 milliseconds late there and on time here**, and the cause is one
frame of AAC encoder priming in the audio track *beside* the subtitles. ffmpeg expresses its
output on a timeline starting at the container's start time, that start time is the earliest of
all the streams', and 6.1 reads the priming as a first audio timestamp of -21 ms where 9.0 reads
zero **for the same bytes** (see `tests/fixtures/media.extraction_offset_seconds`).

So exactly **one** test below asserts cue timings, and it asserts them against the offset read off
the file rather than against a literal - a derivation, exact on every build, that still fails on a
dropped cue, a mangled timing or the wrong stream. The two tests that used to assert timings in
passing now assert the cue **text**, which is what each of them was really for: it is the text
that says which track was mapped.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from atrium.domain.media import (
    DeliveredFile,
    InspectedStream,
    MediaInspection,
    StreamKind,
    renumber,
)
from atrium.media import extract, ffmpeg, probe, subtitles
from tests.fixtures.media import (
    BOTH_SUBTITLE_KINDS,
    CUES,
    IMAGE_SUBTITLE_CODEC,
    SIDECAR_CUES,
    UNCONVERTIBLE_SUBTITLE,
    BuiltMedia,
    Cue,
    MediaFile,
    extraction_offset_seconds,
)

#: The library identifier every `DeliveredFile` here carries. Any string does: it is one component
#: of the cache digest and never a lookup.
LIBRARY = "0000000000000000000000000000000f"


class CountingLedger(ffmpeg.ProductionLedger):
    """A real ledger that remembers every invocation it was asked to start.

    Subclassed rather than patched so the processes, the drains and the reaping are the ones the
    server uses - the count is the only thing added.
    """

    def __init__(self) -> None:
        super().__init__()
        self.started: list[tuple[str, ...]] = []

    async def start(self, argv: Sequence[str], *, to_pipe: bool) -> ffmpeg.Production:
        self.started.append(tuple(argv))
        return await super().start(argv, to_pipe=to_pipe)


def delivered(built: BuiltMedia, entry: MediaFile) -> DeliveredFile:
    return DeliveredFile(
        library_roots=(str(built.base / entry.root),),
        relative_path=entry.path,
        library_id=LIBRARY,
        is_video=True,
    )


def subtitle_stream(inspection: MediaInspection, codec: str) -> InspectedStream:
    found = [
        one
        for one in inspection.streams
        if one.kind is StreamKind.SUBTITLE and (one.codec or "").lower() == codec.lower()
    ]
    assert found, f"the fixture entry carries no {codec} subtitle stream"
    return found[0]


def cue_seconds(cues: Sequence[subtitles.Cue]) -> list[tuple[float, float, str]]:
    """A parsed cue list in the shape the fixture declares its own, so the two can be compared
    without either side repeating the other's numbers."""
    return [
        (
            cue.start_ticks / subtitles.TICKS_PER_SECOND,
            cue.end_ticks / subtitles.TICKS_PER_SECOND,
            cue.text,
        )
        for cue in cues
    ]


def declared(cues: Sequence[Cue]) -> list[tuple[float, float, str]]:
    return [(cue.start_seconds, cue.end_seconds, cue.text) for cue in cues]


def declared_after_extraction(path: Path, cues: Sequence[Cue]) -> list[tuple[float, float, str]]:
    """The declared cue list as an **extraction of this file by this ffmpeg** must answer it.

    The only thing added is the offset the tool itself applies, read off the container with
    `ffprobe` (see the module docstring), and rounded to the millisecond the readable formats
    carry. Nothing here is a tolerance: on a build that shifts nothing the offset is zero and the
    assertion is the declaration exactly, and on one that shifts it the amount is not this test's
    guess but the file's own statement.
    """
    offset = extraction_offset_seconds(path)
    return [
        (round(cue.start_seconds + offset, 3), round(cue.end_seconds + offset, 3), cue.text)
        for cue in cues
    ]


def cue_seconds_to_the_millisecond(
    cues: Sequence[subtitles.Cue],
) -> list[tuple[float, float, str]]:
    """A parsed cue list at the resolution SubRip and WebVTT write."""
    return [(round(start, 3), round(end, 3), text) for start, end, text in cue_seconds(cues)]


def cue_texts(cues: Sequence[subtitles.Cue]) -> list[str]:
    """What each cue says, which is what identifies the track it came out of."""
    return [cue.text for cue in cues]


# ------------------------------------------------------------------------------------------
# The embedded track
# ------------------------------------------------------------------------------------------


@pytest.mark.ffmpeg
async def test_an_embedded_text_track_comes_back_as_the_declared_cue_list(
    media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The whole point of the module, end to end: a track inside a container becomes text.

    Compared against the matrix's own declaration rather than against a literal, which is what
    makes it an assertion about the extraction instead of about this test.

    **This is the one test here that asserts cue timings**, and it asserts them shifted by the
    offset the extracting ffmpeg applies to this file - zero on a build that reads the audio's
    encoder priming as nothing, and one AAC frame on a build that reads it as a negative container
    start time (module docstring). The declaration is still the source of every number.
    """
    entry = BOTH_SUBTITLE_KINDS
    path = media_files.path_of(entry)
    inspection = probe.inspect(path)
    stream = subtitle_stream(inspection, "subrip")
    ledger = CountingLedger()

    text, fmt = await extract.readable(
        ledger, tmp_path / extract.DIRECTORY, delivered(media_files, entry), inspection, stream
    )

    assert fmt == extract.DEFAULT_FORMAT
    assert cue_seconds_to_the_millisecond(subtitles.parse(text, fmt)) == declared_after_extraction(
        path, CUES
    )
    assert len(ledger.started) == 1
    assert not ledger.live, "the extraction was left in the ledger after it finished"


@pytest.mark.ffmpeg
async def test_the_command_copies_a_copyable_codec_and_maps_the_demuxer_index(
    media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The two things about the invocation that a working extraction cannot prove on its own.

    **`-c:s copy`, not `-c:s srt`**: the reference copies the bitstream of anything it can and
    encodes only what it cannot, and asking `srt` for a `subrip` track would decode and re-encode
    every cue for nothing.

    **`-map 0:{file_index}`, not `0:{index}`**: the two numbers are equal until a file turns up
    beside the media, and then they are not. Here the streams are renumbered as a discovered
    sidecar would renumber them, so a command built from the wire number would map the wrong
    stream - and would still succeed, because there is another subtitle track next to it.
    """
    entry = BOTH_SUBTITLE_KINDS
    inspection = probe.inspect(media_files.path_of(entry))
    outsider = InspectedStream(index=0, kind=StreamKind.SUBTITLE, external_path="beside.srt")
    wire = renumber(inspection.streams, (outsider,))
    stream = next(
        one
        for one in wire
        if one.kind is StreamKind.SUBTITLE and (one.codec or "") == "subrip" and not one.is_external
    )
    assert stream.index != stream.file_index, "the renumbering under test did not move anything"
    ledger = CountingLedger()

    text, _ = await extract.readable(
        ledger, tmp_path / extract.DIRECTORY, delivered(media_files, entry), inspection, stream
    )

    argv = ledger.started[0]
    assert f"0:{stream.file_index}" in argv
    assert f"0:{stream.index}" not in argv
    assert argv[argv.index("-c:s") + 1] == "copy"
    # And the map was the right one: the cues are the text track's, not the picture track's. The
    # **text** says that and the timings do not - they carry the extracting build's own offset
    # (module docstring), and one test owning that claim is enough.
    assert cue_texts(subtitles.parse(text, extract.DEFAULT_FORMAT)) == [cue.text for cue in CUES]


@pytest.mark.ffmpeg
async def test_a_second_call_for_the_same_key_starts_no_process(
    media_files: BuiltMedia, tmp_path: Path
) -> None:
    """AC-14, asserted against the ledger rather than against a timing.

    A cache that was merely fast would pass a stopwatch test on a warm page cache and fail an
    operator whose library is on a network share.
    """
    entry = BOTH_SUBTITLE_KINDS
    inspection = probe.inspect(media_files.path_of(entry))
    stream = subtitle_stream(inspection, "subrip")
    cache = tmp_path / extract.DIRECTORY
    ledger = CountingLedger()
    file = delivered(media_files, entry)

    first = await extract.readable(ledger, cache, file, inspection, stream)
    second = await extract.readable(ledger, cache, file, inspection, stream)

    assert second == first
    assert len(ledger.started) == 1


@pytest.mark.ffmpeg
async def test_a_hundred_calls_at_once_start_one_process(
    media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The burst a playlist of a hundred windows produces, which is the failure the lock exists
    for: without it every one of the hundred misses the cache together and starts its own ffmpeg.
    """
    entry = BOTH_SUBTITLE_KINDS
    inspection = probe.inspect(media_files.path_of(entry))
    stream = subtitle_stream(inspection, "subrip")
    cache = tmp_path / extract.DIRECTORY
    ledger = CountingLedger()
    file = delivered(media_files, entry)

    answers = await asyncio.gather(
        *(extract.readable(ledger, cache, file, inspection, stream) for _ in range(100))
    )

    assert len(ledger.started) == 1
    assert len(set(answers)) == 1
    # Nothing accumulates: the last caller out takes the lock with it, so a server that has run
    # for a month holds no more of these than it has extractions in flight.
    assert not extract._locks and not extract._waiting


@pytest.mark.ffmpeg
async def test_an_extracted_ass_carries_the_substituted_font_and_the_mark_that_comes_with_it(
    media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The artefact is not what ffmpeg wrote, and both halves of that are measured.

    The reference replaces `,Arial,` with `,Arial Unicode MS,` in an extracted `.ass` and rewrites
    the file only where that changed something - and the rewrite is what adds the byte order mark.
    Measured on the wire in both forms `[probe: tools/probe_subtitle_delivery.py, Jellyfin
    10.11.11, 2026-08-30]`: a track whose style named Arial arrives substituted **and** marked, a
    track whose style named another font arrives as neither.

    The fixture's `ass` track is written by ffmpeg's own encoder, whose default style names Arial,
    so this entry reaches the substituting half.
    """
    entry = UNCONVERTIBLE_SUBTITLE
    inspection = probe.inspect(media_files.path_of(entry))
    stream = subtitle_stream(inspection, "ass")
    cache = tmp_path / extract.DIRECTORY

    text, fmt = await extract.readable(
        CountingLedger(), cache, delivered(media_files, entry), inspection, stream
    )

    assert fmt == "ass"
    assert extract.ASS_FONT_REPLACEMENT in text
    assert extract.ASS_FONT not in text
    stored = next(iter(cache.glob("*.ass")))
    assert stored.read_bytes().startswith(subtitles.BYTE_ORDER_MARK)
    # The cues prove the substitution did not damage the document it rewrote. By text, for the
    # reason the module docstring gives - and this format's own resolution is a centisecond, so
    # it could not carry the offset exactly even where a build applies one.
    assert cue_texts(subtitles.parse(text, fmt)) == [cue.text for cue in CUES]


# ------------------------------------------------------------------------------------------
# The file beside the media
# ------------------------------------------------------------------------------------------


@pytest.mark.ffmpeg
async def test_a_sidecar_in_a_covered_format_is_read_without_a_process(
    media_files: BuiltMedia, tmp_path: Path
) -> None:
    """A file beside the media whose format the parsers cover is bytes to read, not work to do.

    Its cues are the sidecar's own, which is what says the answer came from beside the film rather
    than from inside it: the two declarations carry different words at different times.
    """
    entry = UNCONVERTIBLE_SUBTITLE
    sidecar = entry.sidecars[0]
    inspection = probe.inspect(media_files.path_of(entry))
    stream = InspectedStream(
        index=0,
        kind=StreamKind.SUBTITLE,
        codec="subrip",
        is_external=True,
        external_path=f"{Path(entry.path).parent.as_posix()}/{sidecar.name}",
    )
    ledger = CountingLedger()

    text, fmt = await extract.readable(
        ledger, tmp_path / extract.DIRECTORY, delivered(media_files, entry), inspection, stream
    )

    assert fmt == "srt"
    assert cue_seconds(subtitles.parse(text, fmt)) == declared(SIDECAR_CUES)
    assert ledger.started == []


# ------------------------------------------------------------------------------------------
# Encodings, and the pictures nothing can convert
# ------------------------------------------------------------------------------------------


def beside(tmp_path: Path, name: str, payload: bytes) -> tuple[DeliveredFile, InspectedStream]:
    """A subtitle file beside a media file that does not have to exist.

    Every branch below is decided before the media file is opened - it never is, for an external
    stream in a covered format - so a fixture that encoded one would be seconds spent proving
    nothing.
    """
    (tmp_path / name).write_bytes(payload)
    file = DeliveredFile(
        library_roots=(str(tmp_path),), relative_path="Film.mkv", library_id=LIBRARY
    )
    stream = InspectedStream(
        index=0, kind=StreamKind.SUBTITLE, codec="subrip", is_external=True, external_path=name
    )
    return file, stream


#: One cue, with a character that is one byte in the legacy encodings and two in UTF-8.
LEGACY_CUE = "1\n00:00:01,000 --> 00:00:02,000\nCafé wörld\n\n"


@pytest.mark.parametrize(
    ("label", "payload"),
    [
        ("utf-8, no mark", LEGACY_CUE.encode("utf-8")),
        ("utf-8 with a mark", subtitles.BYTE_ORDER_MARK + LEGACY_CUE.encode("utf-8")),
        ("utf-16 with a mark", LEGACY_CUE.encode("utf-16")),
        ("utf-32 with a mark", LEGACY_CUE.encode("utf-32")),
        ("a legacy single-byte encoding", LEGACY_CUE.encode("cp1252")),
    ],
)
async def test_a_sidecars_encoding_is_detected_rather_than_assumed(
    tmp_path: Path, label: str, payload: bytes
) -> None:
    """Five ways of writing one cue, and one cue list out of all of them.

    A subtitle file is the one input in this project that is routinely not UTF-8, and the text
    below is the reason the detection is not decoration: read as UTF-8, the legacy form raises
    and the two wide forms are unreadable noise.
    """
    file, stream = beside(tmp_path, "Film.srt", payload)

    text, fmt = await extract.readable(
        ffmpeg.ProductionLedger(), tmp_path / extract.DIRECTORY, file, _nothing(), stream
    )

    assert fmt == "srt"
    assert [cue.text for cue in subtitles.parse(text, fmt)] == ["Café wörld"], label
    # The mark is consumed by the codec that named it, not left at the head of the text: what
    # this function answers is what a fetch of the format the file is already in hands back, and
    # the reference sends that without one.
    assert not text.startswith("\ufeff"), label


async def test_text_in_no_readable_encoding_is_a_production_failure(tmp_path: Path) -> None:
    """Plan section 7's row: a file nobody can decode answers the refusal a failed extraction
    does, rather than serving mojibake or hiding the track."""
    file, stream = beside(tmp_path, "Film.srt", b"1\n00:00:01,000 --> 00:00:02,000\n\x81\x8d\n\n")

    with pytest.raises(ffmpeg.ProductionError):
        await extract.readable(
            ffmpeg.ProductionLedger(), tmp_path / extract.DIRECTORY, file, _nothing(), stream
        )


async def test_an_image_track_raises_before_anything_is_started(tmp_path: Path) -> None:
    """The refusal that costs the reference twenty seconds and costs this server nothing.

    No file, no ledger entry, no process: the decision is the codec's spelling and is taken before
    anything is opened, which is what makes the latency the only difference (spec section 3.7).
    """
    ledger = CountingLedger()
    file = DeliveredFile(
        library_roots=(str(tmp_path),), relative_path="Film.mkv", library_id=LIBRARY
    )
    stream = InspectedStream(index=2, kind=StreamKind.SUBTITLE, codec="PGSSUB")

    with pytest.raises(extract.ImageSubtitleError):
        await extract.readable(ledger, tmp_path / extract.DIRECTORY, file, _nothing(), stream)

    assert ledger.started == []
    assert not ledger.live


@pytest.mark.ffmpeg
async def test_the_fixtures_own_image_track_is_the_one_that_is_refused(
    media_files: BuiltMedia, tmp_path: Path
) -> None:
    """The same refusal, on a real track of a real file rather than on a hand-made record.

    The hand-made one above proves the ledger is untouched; this one proves the fixture's image
    track is classified as an image at all, which is the half a constructed record cannot say.
    """
    entry = BOTH_SUBTITLE_KINDS
    inspection = probe.inspect(media_files.path_of(entry))
    stream = subtitle_stream(inspection, "PGSSUB")
    assert IMAGE_SUBTITLE_CODEC not in (stream.codec or ""), (
        "the codec should have been renamed at inspection (011 T2)"
    )
    ledger = CountingLedger()

    with pytest.raises(extract.ImageSubtitleError):
        await extract.readable(
            ledger, tmp_path / extract.DIRECTORY, delivered(media_files, entry), inspection, stream
        )

    assert ledger.started == []


async def test_a_stream_that_is_not_a_subtitle_is_refused(tmp_path: Path) -> None:
    """Plan section 7's row for an index that names a video or audio stream. The route answers the
    same `500` a failed extraction does, so the refusal is the same class."""
    file = DeliveredFile(
        library_roots=(str(tmp_path),), relative_path="Film.mkv", library_id=LIBRARY
    )
    stream = InspectedStream(index=0, kind=StreamKind.VIDEO, codec="h264")

    with pytest.raises(ffmpeg.ProductionError):
        await extract.readable(
            CountingLedger(), tmp_path / extract.DIRECTORY, file, _nothing(), stream
        )


def _nothing() -> MediaInspection:
    """An inspection with a change signal and no streams: enough to name a cache entry, which is
    all the branches above ask of it."""
    from atrium.compat.dates import utc_now

    return MediaInspection(
        size=1, mtime_ns=1, container="mkv", format_names="matroska,webm", probed_at=utc_now()
    )
