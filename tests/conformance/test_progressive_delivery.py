# SPDX-License-Identifier: GPL-3.0-or-later
"""The produced half of the four `stream` routes: a real encoder, and the bytes it delivered.

`tests/conformance/test_static_delivery.py` proves the half with no process behind it. This is the
other half, and every assertion here is about something a client can observe on the wire or read
out of the body with a demuxer:

* a **remux** carries a `Content-Length` and honours `Range`, which is the one deliberate
  divergence of this feature (behaviours section 3.3, AC-15);
* a **re-encode** is chunked with `Accept-Ranges: none` and never a length it could not know
  (AC-17), and a `Range` on it changes nothing at all - measured;
* the delivered bytes really carry the negotiated codecs, with the accepted stream **copied**
  (AC-7) and nothing above the source's size (AC-8, AC-9);
* a start position lands the output at that position rather than producing from zero (AC-10's
  progressive half);
* and a client that disconnects mid-body stops the encoder (AC-26).

`[probe: tools/probe_progressive_delivery.py, Jellyfin 10.11.11, 2026-08-29]` is the measurement
behind the header assertions and the refusals.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.delivery import NO_RANGES
from atrium.api.deps import require_user
from atrium.compat.errors import CONTROLLER_ERROR_BODY, CONTROLLER_ERROR_TYPE
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.media import ffmpeg
from atrium.media.info import source_id
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    DIRECT_PLAY,
    HIGH_RATE_AUDIO,
    LONG_TAKE,
    REJECTED_AUDIO,
    REJECTED_CONTAINER,
    REJECTED_VIDEO,
    TWO_PARTER_FIRST,
    TWO_PARTER_SECOND,
    BuiltMedia,
    MediaFile,
    ScannedMediaWorld,
    binary,
    build_scanned_media_world,
    frame_count,
    keyframe_seconds,
    probe,
)

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32

#: An identifier no scan produced, for the refusal shared with the static half.
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"

#: A well-formed identifier that names no media source, and one that is not an identifier at all.
#: The reference answers `400` to the first and `500` to the second; Atrium answers the `400` to
#: both (behaviours section 3.9).
UNKNOWN_SOURCE = "beefdeadbeefdeadbeefdeadbeefdead"
UNPARSEABLE_SOURCE = "banana"

#: How long a disconnected encoder is given to be gone. Generous, because the assertion is that it
#: stops rather than that it stops quickly, and a loaded CI machine is not the thing under test.
GRACE_SECONDS = 5.0


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


def item_of(served: tuple[FastAPI, ScannedMediaWorld], entry: MediaFile) -> str:
    return served[1].of(entry).id


def inspected(body: bytes, tmp_path: Path, name: str) -> dict[str, Any]:
    """What a demuxer says about bytes this test was handed.

    Written out and read with `tests/fixtures/media.probe`, which is the fixture module's own
    independent reader - deliberately not `media/probe.py`, so a delivered stream is never checked
    by the same code that decided what to produce.
    """
    written = tmp_path / name
    written.write_bytes(body)
    return dict(probe(written))


def streams_by_kind(inspection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {one["codec_type"]: one for one in inspection.get("streams", [])}


# ------------------------------------------------------------------------------------------
# AC-15 - the remux is sized, and it seeks
# ------------------------------------------------------------------------------------------


async def test_ac15_a_remux_carries_a_length_and_a_range_unit(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The divergence, on the wire. The reference answers this request chunked with
    `Accept-Ranges: none` even though it wrote the output to a file it could have measured; Atrium
    produces to scratch first and says how long it is, because a renderer will not touch a stream
    whose size it does not know (behaviours section 3.3)."""
    item_id = item_of(served, DIRECT_PLAY)

    answered = await client.get(
        f"/Videos/{item_id}/stream.mkv",
        params={"videoCodec": "h264", "audioCodec": "aac"},
    )

    assert answered.status_code == 200
    assert answered.headers["Accept-Ranges"] == "bytes"
    assert answered.headers["Content-Length"] == str(len(answered.content))
    assert answered.headers["Content-Type"] == "video/x-matroska"
    # Matroska magic: the produced bytes really are the container that was asked for, and not the
    # source's mp4 behind a label - which is what separates a remux from `static=true`.
    assert answered.content[:4] == b"\x1a\x45\xdf\xa3"


async def test_ac15_a_remux_honours_a_mid_file_range(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The other half of AC-15, and the reason the remux is produced to a named file: a second
    request for the same thing serves what the first produced rather than encoding again."""
    item_id = item_of(served, DIRECT_PLAY)
    parameters = {"videoCodec": "h264", "audioCodec": "aac"}

    whole = await client.get(f"/Videos/{item_id}/stream.mkv", params=parameters)
    sliced = await client.get(
        f"/Videos/{item_id}/stream.mkv", params=parameters, headers={"Range": "bytes=100-199"}
    )

    size = len(whole.content)
    assert sliced.status_code == 206
    assert sliced.headers["Content-Range"] == f"bytes 100-199/{size}"
    assert sliced.headers["Content-Length"] == "100"
    assert sliced.content == whole.content[100:200]


async def test_a_remux_is_the_same_bytes_every_time_it_is_asked_for(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Spec section 3.4 makes a remux's byte-identity global rather than per session. Asserted
    here because it is what lets the scratch file be named after the command."""
    item_id = item_of(served, DIRECT_PLAY)
    parameters = {"videoCodec": "h264", "audioCodec": "aac"}

    first = await client.get(f"/Videos/{item_id}/stream.mkv", params=parameters)
    second = await client.get(f"/Videos/{item_id}/stream.mkv", params=parameters)

    assert first.content == second.content


async def test_a_bare_non_static_request_produces_into_the_sources_own_container(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured: a bare `/Videos/{id}/stream` on an mkv answers `video/x-matroska`, because with
    no container and no codec named the output extension falls back to the first member of the
    source's stored container string - the third derivation of "the container" in this feature."""
    item_id = item_of(served, REJECTED_CONTAINER)

    answered = await client.get(f"/Videos/{item_id}/stream")

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "video/x-matroska"
    assert answered.headers["Accept-Ranges"] == "bytes"


# ------------------------------------------------------------------------------------------
# AC-17 - the re-encode is chunked, and a Range changes nothing
# ------------------------------------------------------------------------------------------


async def test_ac17_a_re_encode_is_chunked_with_no_length(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The one place Atrium does not diverge: the final length is not known until the last frame,
    and a wrong `Content-Length` truncates playback."""
    item_id = item_of(served, REJECTED_VIDEO)

    answered = await client.get(
        f"/Videos/{item_id}/stream.mp4",
        params={"videoCodec": "h264", "audioCodec": "aac"},
    )

    assert answered.status_code == 200
    assert answered.headers["Accept-Ranges"] == NO_RANGES
    assert "content-length" not in {name.lower() for name in answered.headers}
    assert "content-range" not in {name.lower() for name in answered.headers}
    assert answered.content


@pytest.mark.parametrize("header", ["bytes=100-199", "bytes=-100", "bytes=abc-def", "bytes=0-0"])
async def test_a_range_on_a_chunked_answer_is_ignored_whatever_shape_it_has(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], header: str
) -> None:
    """The reading plan section 6.8 left owed to this task. On a sized answer every unreadable
    `Range` is a `200` with the whole body; on a chunked one **every** `Range` is, readable or
    not, with no `Content-Range` and the body from its beginning."""
    item_id = item_of(served, REJECTED_VIDEO)
    parameters = {"videoCodec": "h264", "audioCodec": "aac"}

    plain = await client.get(f"/Videos/{item_id}/stream.mp4", params=parameters)
    ranged = await client.get(
        f"/Videos/{item_id}/stream.mp4", params=parameters, headers={"Range": header}
    )

    assert ranged.status_code == 200
    assert "content-range" not in {name.lower() for name in ranged.headers}
    assert ranged.headers["Accept-Ranges"] == NO_RANGES
    assert ranged.content[:64] == plain.content[:64]


# ------------------------------------------------------------------------------------------
# AC-7, AC-8, AC-9 - what the delivered bytes actually contain
# ------------------------------------------------------------------------------------------


async def test_ac7_the_accepted_video_stream_is_copied_while_the_audio_is_re_encoded(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], tmp_path: Path
) -> None:
    """The common case, and the one that costs an audio encode rather than a video one. Asserted
    on the delivered bytes: same video codec, same resolution and the **same frame count** as the
    source, beside an audio track that is now the codec the client asked for."""
    item_id = item_of(served, REJECTED_AUDIO)
    origin = inspected(served[1].files.path_of(REJECTED_AUDIO).read_bytes(), tmp_path, "origin.mp4")

    answered = await client.get(
        f"/Videos/{item_id}/stream.mp4",
        params={"videoCodec": "h264", "audioCodec": "aac"},
    )

    assert answered.status_code == 200
    delivered = streams_by_kind(inspected(answered.content, tmp_path, "delivered.mp4"))
    source = streams_by_kind(origin)
    assert delivered["video"]["codec_name"] == "h264" == source["video"]["codec_name"]
    assert delivered["video"]["width"] == source["video"]["width"]
    assert delivered["video"]["height"] == source["video"]["height"]
    assert frame_count(tmp_path / "delivered.mp4") == frame_count(
        served[1].files.path_of(REJECTED_AUDIO)
    )
    assert delivered["audio"]["codec_name"] == "aac"
    assert source["audio"]["codec_name"] == "ac3"


async def test_ac9_a_720p_source_under_a_1080p_ceiling_is_delivered_at_720p(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], tmp_path: Path
) -> None:
    """Nothing is upscaled and nothing is enlarged to fill a ceiling: the 720p `long_take` under a
    1080p ceiling stays 1280x720, because the plan clamps to the source before ffmpeg is asked."""
    item_id = item_of(served, LONG_TAKE)

    answered = await client.get(
        f"/Videos/{item_id}/stream.mp4",
        params={
            "videoCodec": "h264",
            "audioCodec": "aac",
            "maxWidth": 1920,
            "maxHeight": 1080,
            "allowVideoStreamCopy": "false",
        },
    )

    assert answered.status_code == 200
    video = streams_by_kind(inspected(answered.content, tmp_path, "ceilinged.mp4"))["video"]
    assert (video["width"], video["height"]) == (1280, 720)


async def test_ac8_a_ceiling_below_the_source_is_honoured_on_the_delivered_bytes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], tmp_path: Path
) -> None:
    """The other direction, and the one AC-8 is about: an output that violated a condition the
    client declared would fail at its decoder, far from the cause."""
    item_id = item_of(served, LONG_TAKE)

    answered = await client.get(
        f"/Videos/{item_id}/stream.mp4",
        params={"videoCodec": "h264", "audioCodec": "aac", "maxHeight": 240},
    )

    assert answered.status_code == 200
    video = streams_by_kind(inspected(answered.content, tmp_path, "shrunk.mp4"))["video"]
    assert video["height"] <= 240
    assert video["width"] <= 1280


async def test_ac10_a_start_position_begins_production_there(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], tmp_path: Path
) -> None:
    """The progressive half of AC-10. `long_take` is twelve seconds; asked for from six, what
    arrives is about six - which is only true if the encoder was started at the position rather
    than from zero with the first half thrown away."""
    item_id = item_of(served, LONG_TAKE)
    parameters = {"videoCodec": "h264", "audioCodec": "aac"}

    whole = await client.get(f"/Videos/{item_id}/stream.mkv", params=parameters)
    seeked = await client.get(
        f"/Videos/{item_id}/stream.mkv",
        params={**parameters, "startTimeTicks": 6 * 10_000_000},
    )

    assert whole.status_code == seeked.status_code == 200
    full_length = float(inspected(whole.content, tmp_path, "whole.mkv")["format"]["duration"])
    from_six = float(inspected(seeked.content, tmp_path, "seeked.mkv")["format"]["duration"])
    assert full_length == pytest.approx(LONG_TAKE.duration_seconds, abs=0.5)
    # A copied stream restarts at the last keyframe at or before the position, because a copy
    # cannot begin mid-GOP - so the expected length is measured from the fixture's own keyframes
    # rather than written as a number. `long_take`'s forced cadence lands them a hair past each
    # even second at 23.976 fps, which is why six seconds in starts at four and not at six.
    keyframes = keyframe_seconds(served[1].files.path_of(LONG_TAKE))
    began = max(one for one in keyframes if one <= 6.0)
    assert began < 6.0
    assert from_six == pytest.approx(LONG_TAKE.duration_seconds - began, abs=0.5)


# ------------------------------------------------------------------------------------------
# AC-26 - a client that goes away stops the work
# ------------------------------------------------------------------------------------------


async def test_ac26_a_disconnected_client_stops_the_encoder(
    served: tuple[FastAPI, ScannedMediaWorld],
) -> None:
    """AC-26's first appearance, and it needed a client this suite did not have.

    Two things the task statement assumed were wrong. It says the assertion is "on the manager's
    state", and the manager does not exist until T11 - this task's own dependency order says so;
    what exists is `media/ffmpeg.py`'s ledger, the set T11's manager will key sessions on top of.
    And **httpx's ASGI transport cannot drop a connection**: it drives the application to
    completion and hands back a buffered body, so a test that opened a stream and broke out of the
    loop was asserting against a response that had already finished. Plan section 6.8 asked for a
    fixture client that drops mid-body; `_disconnecting_call` is it, and it is nine lines of ASGI
    rather than a dependency.
    """
    item_id = item_of(served, LONG_TAKE)
    ledger = production_ledger_of(served[0])

    seen = await _disconnecting_call(
        served[0],
        f"/Videos/{item_id}/stream.mp4",
        b"videoCodec=hevc&audioCodec=aac",
        ledger,
    )

    assert seen is not None, "no production was live while the body was being sent"
    await _until_stopped(ledger, seen)
    assert not ledger.live
    assert seen.process.returncode is not None


def production_ledger_of(app: FastAPI) -> ffmpeg.ProductionLedger:
    """The application's ledger, created up front so the test never races its first request."""
    existing: ffmpeg.ProductionLedger | None = getattr(app.state, "productions", None)
    if existing is None:
        existing = ffmpeg.ProductionLedger()
        app.state.productions = existing
    return existing


async def _disconnecting_call(
    app: FastAPI, path: str, query: bytes, ledger: ffmpeg.ProductionLedger
) -> ffmpeg.Production | None:
    """Call the application and hang up as soon as the first body chunk is on the wire.

    `http.disconnect` is what a dropped connection *is* at the ASGI boundary, and Starlette's
    streaming response listens for it - so returning one cancels the body generator, which is the
    path the encoder is stopped on. Written here rather than in a shared fixture because it is the
    only test in the repository that needs a client which goes away.
    """
    hung_up = asyncio.Event()
    caught: list[ffmpeg.Production] = []

    async def receive() -> dict[str, Any]:
        await hung_up.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            # Still producing at the moment the client walks away, which is what makes the
            # assertion above a statement about the kill and not about a finished encode.
            caught.extend(one for one in ledger.live if one.process.returncode is None)
            hung_up.set()

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "root_path": "",
            "headers": [(b"host", b"atrium:8096")],
            "client": ("127.0.0.1", 51234),
            "server": ("atrium", 8096),
        },
        receive,
        send,
    )
    return caught[0] if caught else None


async def _until_stopped(ledger: ffmpeg.ProductionLedger, production: ffmpeg.Production) -> None:
    """Wait for the ledger to empty and the child to be reaped, then let the assertions speak.

    Two conditions rather than one: the ledger empties synchronously in the response's `finally`,
    while the exit code appears when the event loop collects the child - and it is the second that
    says the process is actually gone rather than merely forgotten.
    """
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(GRACE_SECONDS):
            while ledger.live or production.process.returncode is None:
                await asyncio.sleep(0.02)


# ------------------------------------------------------------------------------------------
# Which part of the item, and the refusals - measured
# ------------------------------------------------------------------------------------------


async def test_media_source_id_selects_the_part_it_names(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """T6 served part zero and left this to the task that renders and consumes the URL carrying
    it. The second part of the two-parter is a different length from the first on purpose, so
    "it served the part that was named" cannot pass on two identical files."""
    item = served[1].of(TWO_PARTER_SECOND)
    named = source_id(item.id, 1, TWO_PARTER_SECOND.path)
    second = served[1].files.path_of(TWO_PARTER_SECOND).read_bytes()

    answered = await client.get(
        f"/Videos/{item.id}/stream",
        params={"static": "true", "mediaSourceId": named},
    )

    assert answered.status_code == 200
    assert answered.content == second


async def test_the_items_own_id_names_part_zero(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Part zero's derived identifier *is* the item's, which is what makes the reference's own
    fallback - "if it does not match a source, is it the item?" - answer the same thing here."""
    item = served[1].of(TWO_PARTER_SECOND)
    first = served[1].files.path_of(TWO_PARTER_FIRST)

    answered = await client.get(
        f"/Videos/{item.id}/stream",
        params={"static": "true", "mediaSourceId": item.id},
    )

    assert answered.status_code == 200
    assert answered.content == first.read_bytes()


@pytest.mark.parametrize("named", [UNKNOWN_SOURCE, UNPARSEABLE_SOURCE])
@pytest.mark.parametrize("static", ["true", "false"])
async def test_a_media_source_id_that_names_no_part_is_the_third_shape_at_400(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    named: str,
    static: str,
) -> None:
    """**The divergence of behaviours section 3.9, asserted as one row.**

    The reference splits these two by an accident of order - a well-formed identifier that matches
    nothing is a `400`, one that is not an identifier at all throws out of `Guid.Parse` and is a
    `500` - and answers each identically on the static and produced halves. Atrium answers the
    `400` to both: they mean the same thing, and the `400` is the reference's own answer to that
    meaning one value away.
    """
    item_id = item_of(served, DIRECT_PLAY)

    answered = await client.get(
        f"/Videos/{item_id}/stream", params={"static": static, "mediaSourceId": named}
    )

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY


@pytest.mark.parametrize(
    "route",
    ["/Videos/{item}/stream.banana", "/Videos/{item}/stream.mp3", "/Audio/{item}/stream.banana"],
)
async def test_a_container_nothing_can_be_produced_into_is_the_third_shape_at_500(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], route: str
) -> None:
    """Measured on three shapes of the same failure: a container no muxer writes, and one that
    cannot hold the streams it was handed. The reference answers `500` to all three with
    `Accept-Ranges: none` already on the response, because it writes that header before it asks
    for anything - so the refusal carries it here too."""
    item_id = item_of(served, DIRECT_PLAY)

    answered = await client.get(route.format(item=item_id))

    assert answered.status_code == 500
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.headers["Accept-Ranges"] == NO_RANGES
    assert answered.content == CONTROLLER_ERROR_BODY


async def test_an_unknown_item_on_the_produced_half_is_the_same_404_as_the_static_one(
    client: httpx.AsyncClient,
) -> None:
    """One identifier, one body, whichever half of the route answers - which is what makes
    behaviours section 1.11's third shape a property of the *route* rather than of `static`."""
    produced = await client.get(f"/Videos/{UNKNOWN_ITEM}/stream.mp4")
    static = await client.get(f"/Videos/{UNKNOWN_ITEM}/stream", params={"static": "true"})

    assert produced.status_code == static.status_code == 404
    assert produced.content == static.content == CONTROLLER_ERROR_BODY
    assert produced.headers["Content-Type"] == CONTROLLER_ERROR_TYPE


# ------------------------------------------------------------------------------------------
# The audio pair, which is the same answer through the other controller
# ------------------------------------------------------------------------------------------


async def test_a_produced_audio_request_answers_the_measured_shape(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], tmp_path: Path
) -> None:
    """The 96 kHz flac re-encoded to mp3: chunked, `audio/mpeg`, and bytes an demuxer opens as
    mp3. The sample-rate ceiling itself is `/universal`'s question and T8's (AC-19)."""
    item_id = item_of(served, HIGH_RATE_AUDIO)

    answered = await client.get(
        f"/Audio/{item_id}/stream.mp3", params={"audioCodec": "mp3", "audioBitRate": 96000}
    )

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "audio/mpeg"
    assert answered.headers["Accept-Ranges"] == NO_RANGES
    delivered = streams_by_kind(inspected(answered.content, tmp_path, "track.mp3"))
    assert delivered["audio"]["codec_name"] == "mp3"


# ------------------------------------------------------------------------------------------
# `audioStreamIndex`: the track the client named is the track the encoder mapped
# ------------------------------------------------------------------------------------------

#: A film with **two** audio tracks, and the only reason it exists: every entry in T1's matrix
#: carries exactly one, so `audioStreamIndex` had nothing to select between and the parameter
#: could only ever be asserted as a string in a URL. Built here rather than added to the matrix,
#: the way T10 generated its Matroska sibling, because `MediaFile` declares one audio stream.
TWO_TRACKS = "Two Tracks (2007)/Two Tracks (2007).mkv"

#: The two tracks differ **only** in sample rate, and are deliberately the same codec: a test that
#: told them apart by codec would pass on a server that inferred the codec correctly and mapped
#: the wrong stream, which is the failure being ruled out.
FIRST_TRACK_RATE = 48_000
SECOND_TRACK_RATE = 24_000

#: Their indexes in the file, and therefore on the wire: `MediaStream.Index` is the file's own.
FIRST_TRACK_INDEX = 1
SECOND_TRACK_INDEX = 2


def _generate_two_audio_tracks(destination: Path) -> None:
    """One video stream and two aac tracks, at two sample rates, in Matroska.

    Matroska because both tracks have to survive a stream copy: the assertion is about which
    stream was mapped, and a container that re-encoded to hold them would answer a rate neither
    track has.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        binary("ffmpeg"),
        *("-hide_banner", "-loglevel", "error", "-nostdin", "-y"),
        *("-f", "lavfi", "-i", "smptebars=size=320x240:rate=25:duration=4"),
        *("-f", "lavfi", "-i", f"sine=frequency=440:sample_rate={FIRST_TRACK_RATE}:duration=4"),
        *("-f", "lavfi", "-i", f"sine=frequency=880:sample_rate={SECOND_TRACK_RATE}:duration=4"),
        *("-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0"),
        *("-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"),
        *("-c:a", "aac", "-b:a", "96k"),
        *("-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"),
        *("-f", "matroska", str(destination)),
    ]
    finished = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    assert finished.returncode == 0, finished.stderr


@pytest.fixture
def two_track_world(
    media_paths: DataPaths, media_files: BuiltMedia, tmp_path: Path
) -> Iterator[tuple[FastAPI, str]]:
    """The generated matrix plus the two-track sibling, scanned, and the item it produced."""
    copied = media_files.copy_into(tmp_path / "media")
    _generate_two_audio_tracks(copied.movies_root.joinpath(*TWO_TRACKS.split("/")))

    built = create_app(media_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_scanned_media_world(opened, copied)
        UserRepository(opened).add(User(id=VIEWER_ID, name="viewer", enable_all_folders=True))
    built.dependency_overrides[require_user] = _as_viewer

    found = next(
        candidate
        for candidate in world.items.values()
        if any(source.relative_path == TWO_TRACKS for source in candidate.sources)
    )
    yield built, found.id
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
async def two_track_client(
    two_track_world: tuple[FastAPI, str],
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=two_track_world[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


async def test_the_wire_shows_both_tracks_with_the_indexes_the_parameter_names(
    two_track_client: httpx.AsyncClient, two_track_world: tuple[FastAPI, str]
) -> None:
    """The premise, asserted before the thing it is a premise for.

    If the two tracks did not reach the wire under these indexes, the delivery assertion below
    would be selecting between streams a client cannot name.
    """
    _, item_id = two_track_world

    streams = (await two_track_client.get(f"/Items/{item_id}")).json()["MediaSources"][0][
        "MediaStreams"
    ]
    audio = {one["Index"]: one for one in streams if one["Type"] == "Audio"}

    assert sorted(audio) == [FIRST_TRACK_INDEX, SECOND_TRACK_INDEX]
    assert audio[FIRST_TRACK_INDEX]["SampleRate"] == FIRST_TRACK_RATE
    assert audio[SECOND_TRACK_INDEX]["SampleRate"] == SECOND_TRACK_RATE


async def test_ac8_audio_stream_index_changes_the_audio_that_is_produced(
    two_track_client: httpx.AsyncClient,
    two_track_world: tuple[FastAPI, str],
    tmp_path: Path,
) -> None:
    """AC-8 on the one delivery parameter whose effect had only ever been asserted as a string.

    `audioStreamIndex` is bound by `api/delivery.py`, read into the ladder's switches and carried
    into the encoder's stream mapping, and it is forwarded onto every variant and segment URI -
    but the only assertion anywhere was that the negotiated `TranscodingUrl` **spells** it. A
    mapping that ignored the parameter would have passed every test in this repository, and the
    first client to notice would have been one whose user chose the second audio track.

    The pair is the assertion: the same request with and without the parameter, delivering two
    different tracks out of one file.
    """
    _, item_id = two_track_world

    default = await two_track_client.get(f"/Videos/{item_id}/stream.mkv")
    named = await two_track_client.get(
        f"/Videos/{item_id}/stream.mkv", params={"audioStreamIndex": SECOND_TRACK_INDEX}
    )

    assert default.status_code == 200, default.text
    assert named.status_code == 200, named.text

    delivered = streams_by_kind(inspected(default.content, tmp_path, "default.mkv"))
    chosen = streams_by_kind(inspected(named.content, tmp_path, "named.mkv"))

    assert int(delivered["audio"]["sample_rate"]) == FIRST_TRACK_RATE
    assert int(chosen["audio"]["sample_rate"]) == SECOND_TRACK_RATE
    # One audio stream out, not both: the parameter selects rather than reorders.
    assert len(inspected(named.content, tmp_path, "named.mkv")["streams"]) == 2


async def test_an_audio_stream_index_naming_nothing_falls_back_to_the_first(
    two_track_client: httpx.AsyncClient,
    two_track_world: tuple[FastAPI, str],
    tmp_path: Path,
) -> None:
    """Measured leniency, not a guess: an index no stream carries is not a refusal - the route
    delivers the first audio track, which is what a request that named none gets."""
    _, item_id = two_track_world

    answered = await two_track_client.get(
        f"/Videos/{item_id}/stream.mkv", params={"audioStreamIndex": 99}
    )

    assert answered.status_code == 200, answered.text
    delivered = streams_by_kind(inspected(answered.content, tmp_path, "absent.mkv"))
    assert int(delivered["audio"]["sample_rate"]) == FIRST_TRACK_RATE
