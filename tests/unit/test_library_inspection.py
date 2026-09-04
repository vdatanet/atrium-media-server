# SPDX-License-Identifier: GPL-3.0-or-later
"""The trigger a negotiation evaluates, and the inspection it negotiates against when nothing opens.

**The table below is written against the reference's condition and not against the symptom.** The
symptom is "a source nobody ever inspected"; the condition is that *source zero* carries no stream
of the item's own kind `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:174-178
@ v10.11.11]`. Two rows separate them, and they are the reason this module exists rather than a
one-line `is None`:

* a **video** item whose only file was inspected successfully and holds no video stream fires the
  trigger - and fires it again on the next call, and every call after that, for ever;
* a two-part item whose part zero is annotated and whose part one is not does **not** fire it.

That second row also asks a question of 003 that no measurement of the reference can answer,
because the reference has no such item: T1 measured that an unreadable second part is neither a
source of the grouped item nor an item of its own there `[probe:
tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`. What **this** server's resolver
does with it is measured here, over a real scan of the real tree, rather than assumed - see
`test_a_two_part_item_keeps_its_unreadable_part_and_does_not_fire_the_trigger`.

The last section is AC-10's guard: `unopened()` put through `media/info.py:source_of` serialises to
exactly what a `None` inspection serialises to, so nothing a listing says can move when this
feature starts handing the ladder a transient inspection.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from atrium.domain.items import Item, ItemType, MediaSource
from atrium.domain.media import InspectedStream, MediaInspection, StreamKind
from atrium.library import inspection
from atrium.media.info import (
    has_subtitles,
    is_hd,
    item_container,
    item_streams,
    primary_video_stream,
    source_of,
    sources_for,
)
from atrium.media.probe import ProberUnavailableError, UnreadableMediaError, inspect
from tests.fixtures.media import (
    DIRECT_PLAY,
    MISSING_HALF_FIRST,
    MISSING_HALF_SECOND,
    SOUNDLESS,
    UNREADABLE,
    VIDEOLESS,
    BuiltMedia,
    MediaFile,
    UninspectableFile,
)
from tests.fixtures.media_world import ScannedMediaWorld

PROBED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)

#: One real modification time, so the `ETag` two sources derive is a real one rather than zero.
MTIME_NS = 1_767_225_600_000_000_000


def a_source(path: str, **overrides: object) -> MediaSource:
    values: dict[str, object] = {"relative_path": path, "size": 4096, "mtime_ns": MTIME_NS}
    values.update(overrides)
    return MediaSource(**values)  # type: ignore[arg-type]


def a_stream(kind: StreamKind) -> InspectedStream:
    return InspectedStream(index=0, kind=kind, codec="h264" if kind is StreamKind.VIDEO else "aac")


def an_inspection(*kinds: StreamKind) -> MediaInspection:
    return MediaInspection(
        size=4096,
        mtime_ns=MTIME_NS,
        container="mkv",
        format_names="matroska,webm",
        probed_at=PROBED_AT,
        streams=tuple(a_stream(one) for one in kinds),
    )


def an_item(*paths: str, item_type: ItemType = ItemType.MOVIE) -> Item:
    return Item(
        id="a" * 32,
        type=item_type,
        name="A Film",
        library_id="1" * 32,
        sources=tuple(a_source(one) for one in paths),
    )


# ------------------------------------------------------------------------------------------
# The trigger
# ------------------------------------------------------------------------------------------

VIDEO = (StreamKind.VIDEO, StreamKind.AUDIO)
AUDIO = (StreamKind.AUDIO,)

#: `(what it is, sources, inspections, is_video, fires)`. Every row is a state this server can
#: reach except the `.strm` one, which is in the reference's condition and reachable in no v1
#: library - written and cited rather than dropped, so the condition here is the whole condition.
TRIGGER: tuple[
    tuple[str, tuple[MediaSource, ...], list[MediaInspection | None], bool, bool], ...
] = (
    (
        "a film nothing ever opened",
        (a_source("Unreadable (2012).mkv"),),
        [None],
        True,
        True,
    ),
    (
        "a film whose inspection holds a video stream",
        (a_source("A Film (2010).mkv"),),
        [an_inspection(*VIDEO)],
        True,
        False,
    ),
    (
        "a film whose inspection holds no video stream",
        (a_source("Videoless (2010).mkv"),),
        [an_inspection(*AUDIO)],
        True,
        True,
    ),
    (
        "a track whose inspection holds an audio stream",
        (a_source("01 A Track.m4a"),),
        [an_inspection(*AUDIO)],
        False,
        False,
    ),
    (
        "a track whose inspection holds only a video stream",
        (a_source("01 Soundless.m4a"),),
        [an_inspection(StreamKind.VIDEO)],
        False,
        True,
    ),
    (
        "a two-part film, part zero annotated and part one not",
        (a_source("Two - part1.mkv"), a_source("Two - part2.mkv")),
        [an_inspection(*VIDEO), None],
        True,
        False,
    ),
    (
        "a two-part film whose part zero is the one nothing opened",
        (a_source("Two - part1.mkv"), a_source("Two - part2.mkv")),
        [None, an_inspection(*VIDEO)],
        True,
        True,
    ),
    (
        "a part list longer than the inspections it was given",
        (a_source("Two - part1.mkv"), a_source("Two - part2.mkv")),
        [an_inspection(*VIDEO)],
        True,
        False,
    ),
    (
        "an item with no sources at all",
        (),
        [],
        True,
        False,
    ),
    (
        "a stream descriptor, which no v1 library admits",
        (a_source("A Channel.strm"),),
        [an_inspection(*VIDEO)],
        True,
        True,
    ),
)


@pytest.mark.parametrize(
    ("sources", "inspections", "is_video", "fires"),
    [row[1:] for row in TRIGGER],
    ids=[row[0] for row in TRIGGER],
)
def test_the_trigger_is_the_references_condition(
    sources: tuple[MediaSource, ...],
    inspections: list[MediaInspection | None],
    is_video: bool,
    fires: bool,
) -> None:
    """One row per state, including the two that separate the condition from the symptom.

    Row three and row six are the pair: an inspected file with no stream of its item's kind fires,
    and an uninspected *second part* does not. A trigger written as "this part has no stored
    inspection" would answer the opposite on both.
    """
    assert inspection.wanted(sources, inspections, is_video=is_video) is fires


@pytest.mark.ffmpeg
def test_opening_the_file_does_not_clear_the_condition(media_files: BuiltMedia) -> None:
    """The half of the condition that has no cure, run through the real prober rather than argued.

    The trigger is asked, the file is really opened, and the trigger is asked again with exactly
    what the inspection learned: it still fires, because what it reads is a property of the file
    and opening the file does not change one. So the probe is paid on **every** negotiation of this
    item, for ever - measured on the reference at 0.18 s, 0.19 s and 0.20 s for three consecutive
    requests `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    sources = (a_source(VIDEOLESS.path),)

    assert inspection.wanted(sources, [None], is_video=True) is True

    healed = inspection.opened(media_files.path_of(VIDEOLESS))
    assert healed is not None, "the fixture is readable: this is not the unreadable one"
    assert healed.video is None and healed.audio is not None
    assert inspection.wanted(sources, [healed], is_video=True) is True


def test_the_kind_that_is_asked_for_is_the_items_and_not_the_files() -> None:
    """One inspection, two items, two answers.

    A file holding a video stream and no audio is a fine film and an impossible track, and the
    condition reads the *item's* media type. `decide()` was given the same rule at 008 T4 for the
    same reason: a music track with cover art carries a video stream and is negotiated as audio.
    """
    sources = (a_source("Odd One.mkv"),)
    found = [an_inspection(StreamKind.VIDEO)]

    assert inspection.wanted(sources, found, is_video=True) is False
    assert inspection.wanted(sources, found, is_video=False) is True


# ------------------------------------------------------------------------------------------
# Opening one file
# ------------------------------------------------------------------------------------------


def test_opening_answers_what_the_prober_found() -> None:
    found = an_inspection(*VIDEO)
    assert inspection.opened(Path("/films/A Film.mkv"), lambda _: found) is found


@pytest.mark.parametrize(
    "failure",
    [UnreadableMediaError("these bytes are not a container"), ProberUnavailableError("no ffprobe")],
    ids=["unreadable", "no prober"],
)
def test_opening_answers_none_for_either_failure(failure: Exception) -> None:
    """The two exceptions mean opposite things to a scan and the same thing to one request.

    A route cannot install a prober and cannot repair a file, so both answer the un-inspectable
    source of AC-1. `library/scan.py` keeps them apart where the difference decides something
    (003 section 3.7): there a missing prober stops the phase for the whole library.
    """

    def refuses(path: Path) -> MediaInspection:
        raise failure

    assert inspection.opened(Path("/films/A Film.mkv"), refuses) is None


@pytest.mark.ffmpeg
def test_opening_a_real_file_and_a_real_refusal(media_files: BuiltMedia) -> None:
    """The wrapper against the real prober, on two real files: it adds nothing and it loses nothing.

    Compared as the whole record with the clock held still, rather than by picking a field: a
    wrapper that dropped the keyframes or the streams would pass any assertion narrow enough to
    read like a smoke test.
    """
    assert inspection.opened(media_files.path_of(UNREADABLE)) is None

    readable = media_files.path_of(DIRECT_PLAY)
    found = inspection.opened(readable)
    assert found is not None
    assert replace(found, probed_at=PROBED_AT) == replace(inspect(readable), probed_at=PROBED_AT)


# ------------------------------------------------------------------------------------------
# The inspection that is never stored
# ------------------------------------------------------------------------------------------


def test_the_transient_inspection_holds_nothing_but_the_source_rows_own_facts() -> None:
    """No streams, no runtime, no bitrate, and a container that names nothing.

    The empty container is what `media/info.py:source_container` falls back through, and it is
    also what tells this record from a real one: `media/probe.py:inspect` refuses a file whose
    container has no name, so no inspection it returns can carry an empty one. 012 T4's invariant
    - `store` never receives one of these - has that to test against.
    """
    part = a_source("Unreadable (2012).mkv")
    built = inspection.unopened(part)

    assert built.streams == ()
    assert built.runtime_ticks is None
    assert built.bitrate is None
    assert built.video_keyframes is None
    assert built.container == inspection.UNOPENED_CONTAINER
    assert (built.size, built.mtime_ns) == (part.size, part.mtime_ns)


@pytest.mark.parametrize(
    "path",
    ["Unreadable (2012).mkv", "Unreadable (2012).unknownext", "Unreadable (2012)"],
    ids=["an extension the container list would carry", "an unknown extension", "no extension"],
)
def test_the_transient_inspection_serialises_as_no_inspection_at_all(path: str) -> None:
    """AC-10's guard, byte for byte and not field by field.

    This is the whole reason `unopened` puts an **empty** container in rather than the file's
    extension: the fallback that answers `Container` for a source with no inspection is the same
    fallback either way, so a listing's answer cannot move when a negotiation starts handing the
    ladder one of these. Compared as serialised bytes, because casing, `null`-vs-absent and
    numeric type are the parts of the contract only the wire shows (Principle VIII).
    """
    item = an_item(path)
    part = item.sources[0]
    absent = source_of(item, 0, part, None, "/films", is_video=True)
    transient = source_of(item, 0, part, inspection.unopened(part), "/films", is_video=True)

    assert transient.model_dump_json() == absent.model_dump_json()


def test_the_one_source_row_that_cannot_answer_identically_is_one_no_scan_writes() -> None:
    """A part with no stored size answers `Size: 0` here and `Size: null` there.

    Recorded rather than worked around: `item_sources.size` is nullable and
    `MediaInspection.size` is not, so the transient record has no way to say "unknown". Nothing
    reaches the state - `library/walker.py`'s `Candidate.size` is an integer from a `stat()` and is
    the only thing that ever fills the column - and this test is what says so, so that a later
    writer of a source row with no size finds the consequence written down instead of a surprise
    on the wire.
    """
    item = an_item("Unreadable (2012).mkv")
    part = a_source("Unreadable (2012).mkv", size=None, mtime_ns=None)
    absent = source_of(item, 0, part, None, "/films", is_video=True)
    transient = source_of(item, 0, part, inspection.unopened(part), "/films", is_video=True)

    assert absent.size is None
    assert transient.size == 0


def test_every_reader_of_an_inspection_answers_the_same_either_way() -> None:
    """AC-10 in its strong form: not one function, but every one that reads an inspection.

    `source_of` is what the negotiation hands the transient record to, and it is not the only
    thing in `media/info.py` that takes one - five more read the same sequence to build an item
    body, and the listing routes call them. None of them may notice the difference between "never
    opened" and "opened and empty", and `item_container` is the one that would have: it answers
    the stored container where there is one, and only an **empty** string falls through to the
    extension the way a missing inspection does.
    """
    item = an_item("Unreadable (2012).mkv")
    part = item.sources[0]
    absent: list[MediaInspection | None] = [None]
    transient: list[MediaInspection | None] = [inspection.unopened(part)]

    assert item_container(item, transient) == item_container(item, absent)
    assert item_streams(transient, "/films") == item_streams(absent, "/films")
    assert primary_video_stream(transient) == primary_video_stream(absent)
    assert has_subtitles(transient) == has_subtitles(absent)
    assert is_hd(transient) == is_hd(absent)
    assert [
        one.model_dump_json() for one in sources_for(item, transient, "/films", is_video=True)
    ] == [one.model_dump_json() for one in sources_for(item, absent, "/films", is_video=True)]


# ------------------------------------------------------------------------------------------
# What this server's own resolver hands the trigger
# ------------------------------------------------------------------------------------------


@pytest.mark.ffmpeg
def test_a_two_part_item_keeps_its_unreadable_part_and_does_not_fire_the_trigger(
    scanned_media_world: ScannedMediaWorld,
) -> None:
    """The question T1 could not ask of the reference, asked of this server's resolver.

    **The two servers differ, and the difference is 003's.** There, a two-part film whose second
    part no prober will accept is one item with **one** media source - the unreadable part is
    neither a source of the grouped item nor an item of its own `[probe:
    tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`. Here the grouping is a
    naming decision and the inspection is a separate step, so the item answers **two** sources and
    the second has no probe row. Measured on a real scan of the generated tree on 2026-09-04, and
    declared in the reference-reading comparison by T2 rather than designed around by this task.

    What it means for the trigger is the row above it in the table: source zero is annotated, so
    nothing fires, and 012 never opens that second part. Whether it should is the reference's
    answer to give and the reference has no such item to give it with.
    """
    item = scanned_media_world.of(MISSING_HALF_FIRST)
    inspections = [
        scanned_media_world.inspection_of(MISSING_HALF_FIRST),
        scanned_media_world.inspection_of(MISSING_HALF_SECOND),
    ]

    assert [one.relative_path for one in item.sources] == [
        MISSING_HALF_FIRST.path,
        MISSING_HALF_SECOND.path,
    ]
    assert inspections[0] is not None and inspections[0].video is not None
    assert inspections[1] is None
    assert inspection.wanted(item.sources, inspections, is_video=True) is False


@pytest.mark.ffmpeg
@pytest.mark.parametrize(
    ("entry", "is_video"),
    [(UNREADABLE, True), (VIDEOLESS, True), (SOUNDLESS, False)],
    ids=["nothing opened it", "no video stream in a film", "no audio stream in a track"],
)
def test_the_three_states_the_trigger_fires_on_are_states_a_scan_produces(
    scanned_media_world: ScannedMediaWorld,
    entry: MediaFile | UninspectableFile,
    is_video: bool,
) -> None:
    """The rows of the table above, over rows a real scan wrote rather than values a test built.

    Two of the three were inspected successfully, which is what makes them the interesting half:
    the scan opened the file, stored what it said, and the condition is still true - so the probe
    is paid on every negotiation of those items for ever. A fixture whose only unopenable file was
    the unreadable one could not tell that trigger from `is None`.
    """
    item = scanned_media_world.of(entry)
    found = scanned_media_world.inspection_of(entry)

    assert inspection.wanted(item.sources, [found], is_video=is_video) is True


@pytest.mark.ffmpeg
def test_a_scanned_source_that_was_opened_does_not_fire_it(
    scanned_media_world: ScannedMediaWorld,
) -> None:
    """The control on the same world: the ordinary film nothing in this feature touches."""
    item = scanned_media_world.of(DIRECT_PLAY)
    found = scanned_media_world.inspection_of(DIRECT_PLAY)

    assert found is not None
    assert inspection.wanted(item.sources, [found], is_video=True) is False


@pytest.mark.ffmpeg
def test_the_unreadable_source_serialises_the_same_way_either_way(
    scanned_media_world: ScannedMediaWorld,
) -> None:
    """AC-10 again, over the row a real scan wrote for a file the real prober refused."""
    item = scanned_media_world.of(UNREADABLE)
    part = item.sources[0]
    root = scanned_media_world.movies.roots[0]
    absent = source_of(item, 0, part, None, root, is_video=True)
    transient = source_of(item, 0, part, inspection.unopened(part), root, is_video=True)

    assert transient.model_dump_json() == absent.model_dump_json()
