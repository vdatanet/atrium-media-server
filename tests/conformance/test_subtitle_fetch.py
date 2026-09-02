# SPDX-License-Identifier: GPL-3.0-or-later
"""The two subtitle fetch routes, over HTTP, against a track whose cues are declared.

011 T7. `GET …/Subtitles/{index}/Stream.{format}` and its ticks-in-path form are one handler, and
what is asserted here is what a client receives: the cues, their timings, the label, the framing
bytes a cue comparison cannot see, and every row of [spec section 3.7]'s fetch column.

**Cue by cue, and framing by bytes.** Spec section 6 settles the split: two converters given the
same cues disagree on whitespace and rounding, so the cues are compared as values - but the
header a format declares, the placement setting on a WebVTT timing line and the byte order mark
are not whitespace, and those are pinned literally.

**One test asserts cue timings and it derives the offset.** An extracted cue carries the
container's own start time, which one AAC frame of encoder priming makes negative on ffmpeg 6.1
and zero on 9.0 for the same bytes (011 T6, `tests/fixtures/media.extraction_offset_seconds`), so
a literal here would be true of one build. Every other test asserts cue **text**, which is what
says the right track was mapped.

`[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]` is the measurement
behind every status, label and mark below.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.compat.errors import CONTROLLER_ERROR_BODY, CONTROLLER_ERROR_TYPE
from atrium.config.paths import DataPaths
from atrium.db.repositories import MediaProbeRepository, UserRepository
from atrium.domain.items import ItemType
from atrium.domain.media import StreamKind
from atrium.domain.user import User
from atrium.media import extract, subtitles
from atrium.media.labels import DEFAULT_MEDIA_TYPE
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    BOTH_SUBTITLE_KINDS,
    CUES,
    MOVIES_LIBRARY_ID,
    UNCONVERTIBLE_SUBTITLE,
    BuiltMedia,
    Cue,
    MediaFile,
    extraction_offset_seconds,
)
from tests.fixtures.media_world import ScannedMediaWorld, build_scanned_media_world

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32

#: A token nothing issued. These routes require none, so it must change nothing.
UNKNOWN_TOKEN = "0123456789abcdef0123456789abcdef"

#: An identifier no scan produced, and the all-zero form beside it - the reference's `Guid.Empty`,
#: which is a separate row of section 3.7 and the same answer.
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"
EMPTY_GUID = "0" * 32

TICKS_PER_SECOND = subtitles.TICKS_PER_SECOND

#: What each writable spelling is labelled with on the wire, measured. `subrip` and `webvtt` have
#: no row in the label lookup on either server, so the framework's own default answers for them -
#: which is a body under `application/octet-stream` and not the refusal both documents predicted.
LABELS = {
    "vtt": "text/vtt",
    "srt": "application/x-subrip",
    "ass": "text/x-ssa",
    "ssa": "text/x-ssa",
    "json": "application/json",
    "js": "application/json",
    "ttml": "application/ttml+xml",
    "subrip": DEFAULT_MEDIA_TYPE,
    "webvtt": DEFAULT_MEDIA_TYPE,
}

#: The whole header set a fetch answers, measured: no `Accept-Ranges`, no `Last-Modified`, no
#: `ETag`, no `Content-Disposition`. The absences are the assertion.
FETCH_HEADERS = {"content-length", "content-type"}

#: What 001's middleware puts on every response. Excluded above so this file asserts the route's
#: own headers rather than re-asserting 001's.
ALWAYS = {"server", "x-response-time-ms"}


# ------------------------------------------------------------------------------------------
# The world, served
# ------------------------------------------------------------------------------------------


@pytest.fixture
def media_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


@pytest.fixture
def served(
    media_paths: DataPaths, media_files: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    """The real application over the real scan, the shape 008 T5 established."""
    built = create_app(media_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_scanned_media_world(opened, media_files)
        UserRepository(opened).add(User(id=VIEWER_ID, name="viewer", enable_all_folders=True))
    built.dependency_overrides[require_user] = _as_viewer
    yield built, world
    built.dependency_overrides.clear()
    built.state.db.dispose()


def _as_viewer(request: Request) -> User:
    request.state.session_id = None
    request.state.token_sha256 = None
    return User(id=VIEWER_ID, name="viewer", enable_all_folders=True)


@pytest.fixture
async def client(served: tuple[FastAPI, ScannedMediaWorld]) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


@pytest.fixture
async def unauthenticated(
    served: tuple[FastAPI, ScannedMediaWorld],
) -> AsyncIterator[httpx.AsyncClient]:
    """The same application with **no dependency override**, so `require_user` is the real one.

    Without this the credential test would be vacuous: an override that hands back a user makes
    every route look tokenless-friendly, including the ones that are not.
    """
    served[0].dependency_overrides.clear()
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


# ------------------------------------------------------------------------------------------
# Naming a track the way a client names one
# ------------------------------------------------------------------------------------------


async def streams_of(client: httpx.AsyncClient, item_id: str) -> list[dict[str, Any]]:
    """The media source's streams as a client reads them, which is where the **wire** index is.

    Read off `/Items/{itemId}` rather than out of the repository: a delivery address carries the
    number a client was given, and a test that took the number from the same place the route does
    could not catch the two ever disagreeing.
    """
    answered = await client.get(f"/Items/{item_id}")
    assert answered.status_code == 200
    sources = answered.json()["MediaSources"]
    streams: list[dict[str, Any]] = sources[0]["MediaStreams"]
    return streams


async def track(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    entry: MediaFile,
    codec: str,
) -> tuple[str, int]:
    """The item id and the wire index of one subtitle track of one generated file."""
    item_id = served[1].of(entry).id
    streams = await streams_of(client, item_id)
    found = [
        one
        for one in streams
        if one["Type"] == "Subtitle" and str(one.get("Codec", "")).lower() == codec.lower()
    ]
    assert found, f"{entry.key} carries no {codec} subtitle stream on the wire"
    return item_id, int(found[0]["Index"])


def stored_subtitle_index(served: tuple[FastAPI, ScannedMediaWorld], entry: MediaFile) -> int:
    """The first text subtitle stream's wire index, read out of the database.

    The one place here that does not read the number off `/Items/{itemId}`, because the caller has
    no token and that route wants one.
    """
    with served[0].state.sessions.begin() as opened:
        stored = MediaProbeRepository(opened).get(MOVIES_LIBRARY_ID, entry.path)
    assert stored is not None, f"nothing inspected {entry.path!r}"
    return next(
        one.index
        for one in stored.streams
        if one.kind is StreamKind.SUBTITLE and (one.codec or "").lower() == "subrip"
    )


def address(item_id: str, index: int, fmt: str = "vtt") -> str:
    """One track's fetch address. Part zero's source id is the item's own (`media/info.py`)."""
    return f"/Videos/{item_id}/{item_id}/Subtitles/{index}/Stream.{fmt}"


def cue_seconds(cues: Sequence[subtitles.Cue]) -> list[tuple[float, float, str]]:
    return [
        (
            round(cue.start_ticks / TICKS_PER_SECOND, 3),
            round(cue.end_ticks / TICKS_PER_SECOND, 3),
            cue.text,
        )
        for cue in cues
    ]


def declared_after_extraction(
    path: Path, cues: Sequence[Cue], *, rebased_on: float = 0.0
) -> list[tuple[float, float, str]]:
    """The declared cue list as this ffmpeg's extraction of this file must answer it.

    The only thing added is the offset the tool applies, read off the container - a derivation and
    not a tolerance, zero on a build that shifts nothing (011 T6).
    """
    offset = extraction_offset_seconds(path) - rebased_on
    return [
        (round(cue.start_seconds + offset, 3), round(cue.end_seconds + offset, 3), cue.text)
        for cue in cues
    ]


def parsed(body: bytes, fmt: str) -> list[tuple[float, float, str]]:
    return cue_seconds(subtitles.parse(extract.as_text(body), fmt))


def texts(body: bytes, fmt: str) -> list[str]:
    return [cue.text for cue in subtitles.parse(extract.as_text(body), fmt)]


# ------------------------------------------------------------------------------------------
# AC-9: the whole track, in the format that was asked for
# ------------------------------------------------------------------------------------------


async def test_ac9_a_whole_file_fetch_answers_the_declared_cues_with_the_files_timings(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-9, and the one test here that asserts timings.

    The cues are the matrix's own declaration shifted by the offset the extracting ffmpeg applies
    to this container, so it is exact on both builds and still fails on a dropped cue, a mangled
    timing or the wrong stream mapped.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    answered = await client.get(address(item_id, index))

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "text/vtt"
    assert answered.headers["Content-Length"] == str(len(answered.content))
    assert parsed(answered.content, "vtt") == declared_after_extraction(
        served[1].files.path_of(BOTH_SUBTITLE_KINDS), CUES
    )


async def test_the_header_set_is_the_measured_one_and_a_range_is_ignored(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`Content-Type` and `Content-Length`, and nothing else.

    The absences are the point: the framework's convenient file response would have added an
    `ETag` and a `Content-Disposition`, and `Accept-Ranges` is the header 008 T14 found false of
    the two HLS playlists and false again here. A `Range` is not honoured - the reference answers
    `200` with the whole body, because nothing about this response is a file.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    plain = await client.get(address(item_id, index))
    ranged = await client.get(address(item_id, index), headers={"Range": "bytes=0-9"})

    assert set(plain.headers) - ALWAYS == FETCH_HEADERS
    assert ranged.status_code == 200
    assert ranged.content == plain.content


async def test_the_vtt_answer_carries_the_region_and_the_placement_on_every_cue(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The framing a cue-by-cue comparison cannot see, pinned as bytes (spec section 3.5).

    `stream.vtt` is what every playlist entry names, so this writer is the whole subtitle path for
    the video client - and a `WEBVTT\\n\\n` header with bare timing lines holds the same cues and
    puts them somewhere else on the screen.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    answered = await client.get(address(item_id, index))
    document = answered.content.decode("utf-8")

    assert answered.content.startswith(subtitles.BYTE_ORDER_MARK)
    assert document.removeprefix("﻿").startswith(
        "WEBVTT\n\nRegion: id:subtitle width:80% lines:3 "
        "regionanchor:50%,100% viewportanchor:50%,90%\n\n"
    )
    timings = [line for line in document.splitlines() if "-->" in line]
    assert timings, "the answer carried no cue at all"
    assert all(line.endswith(" region:subtitle line:90%") for line in timings)


async def test_ac14_a_subtitle_fetched_twice_answers_the_same_bytes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-14, over HTTP: the second fetch reads the cached artefact and renders the same
    document."""
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    first = await client.get(address(item_id, index))
    second = await client.get(address(item_id, index))

    assert first.status_code == second.status_code == 200
    assert first.content == second.content


async def test_both_spellings_of_the_route_answer_the_same_bytes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-8's spelling half, from below.

    Every playlist entry the reference writes names a lower-case `stream.vtt` where its own
    declaration spells the route with a capital, so a client following a playlist as written must
    be served. 001's `RelaxedPathMiddleware` is what does it, and this is the route that needs it.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    upper = await client.get(address(item_id, index))
    lower = await client.get(
        f"/Videos/{item_id}/{item_id}/Subtitles/{index}/stream.vtt",
    )

    assert lower.status_code == upper.status_code == 200
    assert lower.content == upper.content
    assert lower.headers["Content-Type"] == upper.headers["Content-Type"]


async def test_neither_credential_changes_the_answer(
    unauthenticated: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured: no token, an unknown token and a token in the query are one `200`.

    Against the application with the real `require_user`, so the assertion is that the route asks
    for nothing rather than that a fixture handed it a user.

    The index is read out of storage rather than off `/Items/{itemId}`, which every other test
    here uses: that route **does** require a token, and asking it without one is the `401` this
    test exists to prove the fetch route does not send.
    """
    item_id = served[1].of(BOTH_SUBTITLE_KINDS).id
    index = stored_subtitle_index(served, BOTH_SUBTITLE_KINDS)

    bare = await unauthenticated.get(address(item_id, index))
    unknown = await unauthenticated.get(
        address(item_id, index), headers={"X-Emby-Token": UNKNOWN_TOKEN}
    )
    query = await unauthenticated.get(address(item_id, index), params={"ApiKey": UNKNOWN_TOKEN})

    assert bare.status_code == unknown.status_code == query.status_code == 200
    assert bare.content == unknown.content == query.content


# ------------------------------------------------------------------------------------------
# AC-10: the window, and the two switches
# ------------------------------------------------------------------------------------------


async def test_ac10_a_window_answers_its_own_cues_and_the_copy_switch_decides_their_timings(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-10 and OQ-11 together: which cues, and at what time.

    The window starts between the two declared cues and ends after the second, so a route that
    ignored it would answer both. With `CopyTimestamps` the cue keeps the time the file gives it;
    without, it is rebased on the window - the difference the playlist's own entries turn on.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")
    path = served[1].files.path_of(BOTH_SUBTITLE_KINDS)
    start = int(1.5 * TICKS_PER_SECOND)
    window = {"StartPositionTicks": start, "EndPositionTicks": int(3.5 * TICKS_PER_SECOND)}

    copied = await client.get(address(item_id, index), params={**window, "CopyTimestamps": "true"})
    rebased = await client.get(address(item_id, index), params=window)

    assert copied.status_code == rebased.status_code == 200
    assert parsed(copied.content, "vtt") == declared_after_extraction(path, CUES[1:])
    assert parsed(rebased.content, "vtt") == declared_after_extraction(
        path, CUES[1:], rebased_on=1.5
    )


async def test_the_time_map_switch_prepends_a_line_and_drops_the_mark(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """OQ-11's second half, and the one thing that changes the bytes rather than the cues.

    Both switches together are what a playlist entry sets, so this is the exact document a client
    following a manifest receives.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    mapped = await client.get(
        address(item_id, index), params={"AddVttTimeMap": "true", "CopyTimestamps": "true"}
    )
    plain = await client.get(address(item_id, index), params={"CopyTimestamps": "true"})

    assert mapped.status_code == 200
    assert not mapped.content.startswith(subtitles.BYTE_ORDER_MARK)
    assert mapped.content.startswith(f"WEBVTT\n{subtitles.VTT_TIME_MAP}\n".encode())
    assert plain.content.startswith(subtitles.BYTE_ORDER_MARK)
    assert texts(mapped.content, "vtt") == texts(plain.content, "vtt")


async def test_the_time_map_is_read_against_vtt_and_not_against_its_alias(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured: `Stream.webvtt?AddVttTimeMap=true` answers a plain document, mark intact.

    The two spellings share a writer and not the branch - the switch is read against `vtt` alone,
    which is the kind of asymmetry that only survives being reproduced deliberately.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    aliased = await client.get(address(item_id, index, "webvtt"), params={"AddVttTimeMap": "true"})

    assert aliased.status_code == 200
    assert subtitles.VTT_TIME_MAP.encode() not in aliased.content
    assert aliased.content.startswith(subtitles.BYTE_ORDER_MARK)


async def test_a_window_whose_end_precedes_its_start_is_a_body_with_no_cues(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The last row of section 3.7's table: `200`, a well-formed document, and nothing in it."""
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    answered = await client.get(
        address(item_id, index),
        params={
            "StartPositionTicks": int(3 * TICKS_PER_SECOND),
            "EndPositionTicks": int(1 * TICKS_PER_SECOND),
        },
    )

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "text/vtt"
    assert b"-->" not in answered.content


# ------------------------------------------------------------------------------------------
# The ticks-in-path route
# ------------------------------------------------------------------------------------------


async def test_the_ticks_in_the_path_are_the_start_position(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`GetSubtitleWithTicks` is the same answer with the start moved into the address.

    It is the route a negotiation's own `DeliveryUrl` names, so this is the form a client
    following what it was handed actually asks for.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")
    start = int(1.5 * TICKS_PER_SECOND)
    end = int(3.5 * TICKS_PER_SECOND)

    in_path = await client.get(
        f"/Videos/{item_id}/{item_id}/Subtitles/{index}/{start}/Stream.vtt",
        params={"EndPositionTicks": end, "CopyTimestamps": "true"},
    )
    in_query = await client.get(
        address(item_id, index),
        params={
            "StartPositionTicks": start,
            "EndPositionTicks": end,
            "CopyTimestamps": "true",
        },
    )

    assert in_path.status_code == 200
    assert in_path.content == in_query.content


async def test_a_start_position_in_the_query_beats_the_one_in_the_path(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured, and the opposite of the direction plan section 6.7 stated.

    The path names a start past the first cue and the query names zero; the answer carries both
    cues, so the query is what was read.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")
    past_the_first_cue = int(1.5 * TICKS_PER_SECOND)

    answered = await client.get(
        f"/Videos/{item_id}/{item_id}/Subtitles/{index}/{past_the_first_cue}/Stream.vtt",
        params={"StartPositionTicks": 0, "CopyTimestamps": "true"},
    )

    assert answered.status_code == 200
    assert texts(answered.content, "vtt") == [cue.text for cue in CUES]


# ------------------------------------------------------------------------------------------
# The formats: every spelling, its label, and its first bytes
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", sorted(LABELS))
async def test_every_writable_spelling_answers_its_measured_label(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], fmt: str
) -> None:
    """Nine spellings, six writers, and the label of each read off a run rather than a paragraph.

    `subrip` and `webvtt` are the two the reference's own label lookup has no row for: it renders
    the whole document and then has nothing to send it under, and the framework's file result
    defaults the type instead of refusing - so the answer is a body under
    `application/octet-stream`, not the refusal this project's own notes predicted.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    answered = await client.get(address(item_id, index, fmt))

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == LABELS[fmt]
    assert answered.headers["Content-Length"] == str(len(answered.content))


async def test_the_byte_order_mark_is_on_every_rendered_document_but_the_json_one(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Five of the six writers emit the UTF-8 preamble and the JSON one writes bytes directly.

    `srt` is the interesting absence: the track is already SubRip, so that request is answered by
    the same-format short circuit with the artefact's own bytes rather than by a writer - which is
    what the next test is about.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    marks = {}
    for fmt in LABELS:
        answered = await client.get(address(item_id, index, fmt))
        marks[fmt] = answered.content.startswith(subtitles.BYTE_ORDER_MARK)

    assert all(marks[fmt] for fmt in ("vtt", "ass", "ssa", "ttml", "subrip", "webvtt"))
    assert not any(marks[fmt] for fmt in ("json", "js", "srt"))


async def test_the_json_answer_is_the_cue_list_as_an_object_of_track_events(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The two spellings that answer something other than a subtitle file, and they answer one
    thing: `TrackEvents`, with tick positions rather than clock strings."""
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    under_json = await client.get(address(item_id, index, "json"))
    under_js = await client.get(address(item_id, index, "js"))

    assert under_json.content == under_js.content
    events = under_json.json()["TrackEvents"]
    assert [one["Text"] for one in events] == [cue.text for cue in CUES]
    assert all(one["EndPositionTicks"] > one["StartPositionTicks"] for one in events)


@pytest.mark.parametrize("fmt", ["sub", "xyz"])
async def test_a_format_nothing_writes_is_refused_before_any_file_is_opened(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], fmt: str
) -> None:
    """The controller refusal at `400`, in the third shape."""
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    answered = await client.get(address(item_id, index, fmt))

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY


# ------------------------------------------------------------------------------------------
# The same-format short circuit
# ------------------------------------------------------------------------------------------


async def test_a_window_on_the_format_the_track_is_already_in_answers_the_whole_track(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The exception AC-10 states, measured before it was written into the criterion.

    A windowed `Stream.srt` on a SubRip track is answered before anything is parsed, so the window
    and both switches are ignored and the whole track comes back - on the ticks-in-path route as
    well. Unreachable from a playlist, whose entries always name `stream.vtt`, and one request
    away by hand. Reproduced rather than corrected: what it hands back is the artefact, and the
    artefact is what the next test is about.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")
    start = int(1.5 * TICKS_PER_SECOND)
    window = {"StartPositionTicks": start, "EndPositionTicks": int(3.5 * TICKS_PER_SECOND)}

    whole = await client.get(address(item_id, index, "srt"))
    windowed = await client.get(address(item_id, index, "srt"), params=window)
    ticked = await client.get(f"/Videos/{item_id}/{item_id}/Subtitles/{index}/{start}/Stream.srt")
    rendered = await client.get(address(item_id, index, "subrip"), params=window)

    assert whole.status_code == windowed.status_code == ticked.status_code == 200
    assert windowed.content == whole.content
    assert ticked.content == whole.content
    # And the spelling beside it renders the same window, which is what makes the three above a
    # short circuit rather than a track whose every cue happens to be inside the window.
    assert texts(rendered.content, "srt") == [CUES[1].text]


async def test_the_short_circuit_hands_back_the_artefact_and_not_a_rendered_document(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`Stream.ass` on an embedded `ass` track is the only view a client has of an extraction.

    What comes back is not what ffmpeg wrote: the reference replaces `,Arial,` with
    `,Arial Unicode MS,` in a freshly extracted `.ass` and rewrites the file only where that
    changed something, through a writer that emits the UTF-8 preamble - so the substituted font
    and the byte order mark arrive **together**. Answering the decoded text re-encoded would drop
    the mark, which is why `media/extract.py` has a bytes-level entry point at all.
    """
    item_id, index = await track(client, served, UNCONVERTIBLE_SUBTITLE, "ass")

    answered = await client.get(address(item_id, index, "ass"))

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == LABELS["ass"]
    assert answered.content.startswith(subtitles.BYTE_ORDER_MARK)
    document = answered.content.decode("utf-8")
    assert extract.ASS_FONT_REPLACEMENT in document
    assert extract.ASS_FONT not in document
    assert texts(answered.content, "ass") == [cue.text for cue in CUES]


# ------------------------------------------------------------------------------------------
# The deprecated query parameters, which beat the address
# ------------------------------------------------------------------------------------------


async def test_the_format_query_parameter_overrides_the_one_in_the_path(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured: `Stream.vtt?format=srt` answers SubRip under `application/x-subrip`.

    Declared obsolete on the reference and still bound, so a client that sends one gets a
    different document than the address names - and a route that bound only its path would answer
    the wrong thing to exactly that client.
    """
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    overridden = await client.get(address(item_id, index), params={"format": "srt"})
    named = await client.get(address(item_id, index, "srt"))

    assert overridden.status_code == 200
    assert overridden.headers["Content-Type"] == LABELS["srt"]
    assert overridden.content == named.content


async def test_the_index_query_parameter_overrides_the_one_in_the_path(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The same, on the parameter that decides which track is served."""
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    answered = await client.get(address(item_id, 99), params={"index": index})
    missing = await client.get(address(item_id, index), params={"index": 99})

    assert answered.status_code == 200
    assert texts(answered.content, "vtt") == [cue.text for cue in CUES]
    assert missing.status_code == 500


# ------------------------------------------------------------------------------------------
# Spec section 3.7, the fetch column, row by row
# ------------------------------------------------------------------------------------------


async def test_an_item_that_names_nothing_is_the_controller_refusal_at_400(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Two rows, one answer: a well-formed identifier naming nothing, and the all-zero form.

    `400` and **not** the third-shape `404` the four `stream` routes answer for the same miss -
    measured on both in the same run, which is why the two error classes are named apart.
    """
    for item_id in (UNKNOWN_ITEM, EMPTY_GUID):
        answered = await client.get(address(item_id, 0))

        assert answered.status_code == 400, item_id
        assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
        assert answered.content == CONTROLLER_ERROR_BODY


async def test_an_item_that_exists_with_nothing_servable_is_the_500(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The row between this route's two refusals, and the reason the lookup asks about the item
    **first** - measured at T7 and asserted here at T12, which found it unasserted.

    An identifier nothing holds is the `400` above; an identifier naming an item that **is** here
    and has no subtitle to convert is the `500`. Both halves are in one test because the split is
    the assertion: a route that resolved the part before the item - which is what
    `api/delivery.py`'s `locate` does - answers one status for both rows and passes neither the
    first row nor this one. The playlist route beside these two answers its problem-details `404`
    for the same two identifiers (`tests/conformance/test_subtitle_playlist.py`).
    """
    world = served[1]
    audio = world.by_type(ItemType.AUDIO)
    folders = world.by_type(ItemType.MUSIC_ALBUM)
    assert audio and folders, "the scanned world holds no audio item and no album to ask about"

    for label, item_id in (("an audio track", audio[0].id), ("an album", folders[0].id)):
        answered = await client.get(address(item_id, 0))

        assert answered.status_code == 500, label
        assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE, label
        assert answered.content == CONTROLLER_ERROR_BODY, label

    missing = await client.get(address(UNKNOWN_ITEM, 0))
    assert missing.status_code == 400, (
        "the two statuses split on whether the item is there at all, and they collapsed into one"
    )


async def test_an_identifier_that_is_not_one_is_problem_details_naming_the_route_parameter(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The other shape, and the parameter it names is the route's own spelling.

    `routeItemId` and not `itemId`: the fetch routes declare their path parameters with the
    `route` prefix, and a refusal that named the query alias beside it would name a parameter the
    client did not send. **The playlist route beside them names `itemId` for the same value** -
    each route names its own path segment, measured on both in one run and a row of spec section
    3.7 since 011 T8 (`tests/conformance/test_subtitle_playlist.py`).
    """
    answered = await client.get(
        "/Videos/not-a-guid/not-a-guid/Subtitles/0/Stream.vtt",
    )

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == "application/json; charset=utf-8"
    assert "routeItemId" in answered.json()["errors"]


async def test_a_media_source_that_names_nothing_is_the_500(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The row that runs the other way from 008's: a `mediaSourceId` naming no source of this item
    is a `400` on a delivery route and a `500` here, measured on both."""
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "subrip")

    answered = await client.get(f"/Videos/{item_id}/{UNKNOWN_ITEM}/Subtitles/{index}/Stream.vtt")

    assert answered.status_code == 500
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY
    assert "Accept-Ranges" not in answered.headers


async def test_an_index_that_names_no_text_subtitle_is_the_500(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Four rows, one lookup: no stream, a video stream, an audio stream, and a negative index.

    The reference takes the first match of a sequence and throws the same way for all four, and an
    `InvalidOperationException` is not a type its middleware maps - so they are the `500`.
    """
    item_id = served[1].of(BOTH_SUBTITLE_KINDS).id
    streams = await streams_of(client, item_id)
    video = next(int(one["Index"]) for one in streams if one["Type"] == "Video")
    audio = next(int(one["Index"]) for one in streams if one["Type"] == "Audio")

    for index in (99, video, audio, -1):
        answered = await client.get(address(item_id, index))

        assert answered.status_code == 500, index
        assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
        assert answered.content == CONTROLLER_ERROR_BODY


async def test_an_image_track_asked_for_as_text_is_refused_at_400_without_a_process(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-7's fetch half, and the one place this feature is knowingly faster than the reference.

    There, the extraction is attempted and refused about twenty seconds later; here nothing is
    started. The status and the twenty-five bytes are identical, and the ledger is the proof that
    no process ran - a `500` from a failed extraction would look the same to a client.
    """
    # `PGSSUB` and not `hdmv_pgs_subtitle`: the codec is renamed at inspection (011 T2), and the
    # wire spelling is what a client would put in this address.
    item_id, index = await track(client, served, BOTH_SUBTITLE_KINDS, "PGSSUB")

    answered = await client.get(address(item_id, index))

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY
    ledger = getattr(served[0].state, "productions", None)
    assert ledger is None or not ledger.live
