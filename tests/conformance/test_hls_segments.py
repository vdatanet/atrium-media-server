# SPDX-License-Identifier: GPL-3.0-or-later
"""One segment at a time, over the HTTP boundary, with a real encoder behind it.

`tests/conformance/test_hls_playlists.py` proves the promise - a complete playlist before
anything exists - and this proves it kept: every URI that playlist writes is followed and the
bytes behind it are inspected by ffprobe rather than by the code that produced them.

Four of these tests are about **work not done**, which is the half of this feature that a
passing request cannot show on its own:

* a segment near the end produces nothing before it, asserted on the scratch directory (AC-10);
* the same segment twice is one file and one encode (AC-23);
* an out-of-order request is served rather than queued behind everything before it (AC-24);
* a mixed plan re-encodes the audio and leaves the video alone (AC-7, AC-8 at the segment
  level), asserted on the delivered segment's own streams.

Every expected value is `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11,
2026-08-29]`, whose segment battery measured this route's headers, its two identity rules and
its five refusals in one run.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.compat.errors import CONTROLLER_ERROR_BODY
from atrium.config.paths import DataPaths
from atrium.db.repositories import SessionRepository, UserRepository
from atrium.domain.session import Session
from atrium.domain.user import User
from atrium.media.labels import MEDIA_TYPES
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    LONG_TAKE,
    REJECTED_AUDIO,
    BuiltMedia,
    probe,
)
from tests.fixtures.media_world import ScannedMediaWorld, build_scanned_media_world

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32
SESSION_ID = "f" * 32
TOKEN = "0123456789abcdef0123456789abcdef"
DEVICE_ID = "test-device-0001"
HEADERS = {
    "X-Emby-Token": TOKEN,
    "X-Emby-Authorization": (
        f'MediaBrowser Client="tests", Device="pytest", DeviceId="{DEVICE_ID}", Version="1"'
    ),
}

UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"

#: What the negotiated URL states, written out here because these tests follow the *playlist*
#: rather than a `PlaybackInfo` round trip: `test_hls_playlists.py` owns the round trip, and a
#: second copy of it here would be proving T5's wiring twice and this task's once.
REENCODE_QUERY = {
    "videoCodec": "hevc",
    "audioCodec": "aac",
    "playSessionId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "deviceId": DEVICE_ID,
}

#: A plan that copies the video and re-encodes only the audio - the source is h264 beside ac3, so
#: naming h264 and aac is naming exactly one change.
MIXED_QUERY = {
    "videoCodec": "h264",
    "audioCodec": "aac",
    "playSessionId": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "deviceId": DEVICE_ID,
}


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
        SessionRepository(opened).upsert(
            Session(
                id=SESSION_ID,
                user_id=VIEWER_ID,
                device_id=DEVICE_ID,
                client="tests",
                device_name="pytest",
            )
        )
    built.dependency_overrides[require_user] = _as_viewer
    yield built, world
    built.dependency_overrides.clear()
    built.state.db.dispose()


def _as_viewer(request: Request) -> User:
    request.state.session_id = SESSION_ID
    request.state.token_sha256 = None
    return User(id=VIEWER_ID, name="viewer", enable_all_folders=True)


@pytest.fixture
async def client(served: tuple[FastAPI, ScannedMediaWorld]) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened
    await served[0].state.transcodes.shutdown()


@pytest.fixture
async def unauthenticated(
    served: tuple[FastAPI, ScannedMediaWorld],
) -> AsyncIterator[httpx.AsyncClient]:
    """The same application with the real `require_user`, so the credential test is not vacuous."""
    served[0].dependency_overrides.clear()
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


async def segment_uris(
    client: httpx.AsyncClient, item_id: str, **query: object
) -> tuple[list[str], list[float]]:
    """The playlist's own segment URIs, followed rather than rebuilt.

    Rebuilding them would let the two per-segment parameters - the ones that decide where
    production starts and how long the segment claims to be - be whatever this test found
    convenient, which is the one thing they must not be.
    """
    answered = await client.get(f"/Videos/{item_id}/main.m3u8", params=query, headers=HEADERS)
    assert answered.status_code == 200, answered.text
    lines = answered.text.splitlines()
    return (
        [f"/Videos/{item_id}/{line}" for line in lines if line and not line.startswith("#")],
        [
            float(line.split(":", 1)[1].split(",", 1)[0])
            for line in lines
            if line.startswith("#EXTINF")
        ],
    )


def scratch_files(paths: DataPaths, suffix: str = ".ts") -> list[str]:
    """Every produced segment on disk, by name, across every session."""
    return sorted(one.name for one in paths.transcodes.rglob(f"*{suffix}"))


# ------------------------------------------------------------------------------------------
# The answer: a finished file, sized, labelled and rangeable
# ------------------------------------------------------------------------------------------


async def test_a_segment_arrives_sized_and_labelled(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The measured header set of a segment, which is the static answer's plus nothing.

    `Last-Modified` is the one that had to be measured rather than reasoned: the progressive
    routes send none (behaviours section 3.3) and this one does, because the reference serves a
    finished file here the way it serves any file. There is no `ETag` on either.
    """
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)

    answered = await client.get(uris[0], headers=HEADERS)

    assert answered.status_code == 200, answered.text
    assert answered.headers["Content-Type"] == MEDIA_TYPES["ts"]
    assert answered.headers["Content-Length"] == str(len(answered.content))
    assert answered.headers["Accept-Ranges"] == "bytes"
    assert "Last-Modified" in answered.headers
    assert "ETag" not in answered.headers
    assert answered.content[:1] == b"G", "an MPEG-TS packet begins with its sync byte"


async def test_a_segment_honours_a_range(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-11 and AC-12 on this route: the body's size is known, so the range is answered."""
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)
    whole = await client.get(uris[0], headers=HEADERS)

    answered = await client.get(uris[0], headers={**HEADERS, "Range": "bytes=100-199"})

    assert answered.status_code == 206
    assert len(answered.content) == 100
    assert answered.headers["Content-Range"] == f"bytes 100-199/{len(whole.content)}"


async def test_ac23_the_same_segment_twice_is_the_same_bytes(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    media_paths: DataPaths,
) -> None:
    """Within one session a produced segment is served identically every time.

    Structural rather than lucky: the second request reads the file the first one produced, which
    the count of files on disk is what shows. Two encoders given one instruction never agree
    byte for byte, so a server that re-encoded per request could not answer a retry.
    """
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)

    first = await client.get(uris[0], headers=HEADERS)
    after_one = scratch_files(media_paths)
    second = await client.get(uris[0], headers=HEADERS)

    assert first.content == second.content
    assert first.content
    assert scratch_files(media_paths) == after_one, (
        "the second request produced something, so it did not read the first one's file"
    )


async def test_ac24_a_segment_out_of_order_is_served(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Players seek; they do not walk the playlist."""
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)
    assert len(uris) > 2, "a playlist this short cannot be asked out of order"

    later = await client.get(uris[2], headers=HEADERS)
    earlier = await client.get(uris[0], headers=HEADERS)

    assert later.status_code == 200, later.text
    assert earlier.status_code == 200, earlier.text
    assert later.content != earlier.content


async def test_ac10_a_segment_near_the_end_produces_nothing_before_it(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    media_paths: DataPaths,
) -> None:
    """The work-not-done form: production starts where the request asked, not at zero.

    Asserted on the scratch directory rather than on a clock, which is what makes it a fact about
    this server rather than about the machine it ran on: a 2h22 film measured 0.9 seconds to a
    segment at 90% on the reference, and the only reproducible half of that is *what was
    produced*.
    """
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)
    last = len(uris) - 1

    answered = await client.get(uris[last], headers=HEADERS)

    assert answered.status_code == 200, answered.text
    assert answered.content
    assert scratch_files(media_paths) == [f"{last}.ts"], (
        "every segment before the requested one was produced and discarded, which is the "
        "behaviour spec section 3.4 exists to forbid"
    )


async def test_ac7_a_mixed_plan_copies_the_video_and_re_encodes_the_audio(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    media_paths: DataPaths,
    tmp_path: Path,
) -> None:
    """AC-7 and AC-8 at the segment level, on the delivered bytes.

    The fixture is h264 beside ac3 in mp4 - a modern video track with an audio track a browser
    cannot decode, which spec section 3.4 calls the common case. Naming h264 and aac asks for
    exactly one change, and the segment is what has to show it: the video codec and its
    resolution unchanged, the audio codec the one the profile asked for.
    """
    item = served[1].of(REJECTED_AUDIO)
    uris, _durations = await segment_uris(client, item.id, **MIXED_QUERY)

    answered = await client.get(uris[0], headers=HEADERS)

    assert answered.status_code == 200, answered.text
    delivered = tmp_path / "delivered.ts"
    delivered.write_bytes(answered.content)
    streams = {
        one["codec_type"]: one
        for one in probe(delivered)["streams"]  # type: ignore[union-attr]
    }
    assert streams["video"]["codec_name"] == REJECTED_AUDIO.video_codec
    assert streams["video"]["width"] == REJECTED_AUDIO.width
    assert streams["video"]["height"] == REJECTED_AUDIO.height
    assert streams["audio"]["codec_name"] == "aac"
    assert scratch_files(media_paths), "nothing was produced, so nothing was inspected"


async def test_the_produced_boundaries_are_the_ones_the_playlist_promised(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], tmp_path: Path
) -> None:
    """Spec section 3.7 rule 2, on the bytes: the declared duration is what is delivered.

    This is the one place Atrium is deliberately not the reference. It states its unscaled
    integer request to ffmpeg and the scaled one to the playlist, so its 3.004 s segments are
    3.000 s of media; the grid stated here is the planned one, so a seek bar built from the
    playlist points at the frame it names (`media/ffmpeg.segment_command`).
    """
    item = served[1].of(LONG_TAKE)
    uris, durations = await segment_uris(client, item.id, **REENCODE_QUERY)

    answered = await client.get(uris[0], headers=HEADERS)

    assert answered.status_code == 200, answered.text
    delivered = tmp_path / "first.ts"
    delivered.write_bytes(answered.content)
    produced = float(probe(delivered)["format"]["duration"])  # type: ignore[index,call-overload]
    assert produced == pytest.approx(durations[0], abs=0.05), (
        f"the playlist promised {durations[0]}s and the segment holds {produced}s"
    )


async def test_the_fragmented_playlists_initialisation_segment_is_produced(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`SegmentContainer=mp4` makes the playlist version 7 and gives it a segment numbered -1.

    Numbered `-1` and *not a position in the film*: it is the fMP4 initialisation segment, which
    ffmpeg writes from the head of whatever it is about to produce. Measured on the reference at
    `hls1/main/-1.mp4`, `video/mp4`, beginning `ftyp`.
    """
    item = served[1].of(LONG_TAKE)
    answered = await client.get(
        f"/Videos/{item.id}/main.m3u8",
        params={**REENCODE_QUERY, "segmentContainer": "mp4"},
        headers=HEADERS,
    )
    assert "#EXT-X-VERSION:7" in answered.text
    mapping = next(line for line in answered.text.splitlines() if line.startswith("#EXT-X-MAP"))
    uri = mapping.split('URI="', 1)[1].rstrip('"')
    assert uri.startswith("hls1/main/-1.mp4")

    initialisation = await client.get(f"/Videos/{item.id}/{uri}", headers=HEADERS)

    assert initialisation.status_code == 200, initialisation.text
    assert initialisation.headers["Content-Type"] == MEDIA_TYPES["mp4"]
    assert initialisation.headers["Content-Length"] == str(len(initialisation.content))
    assert initialisation.content[4:8] == b"ftyp"


# ------------------------------------------------------------------------------------------
# Every ffmpeg has an owner
# ------------------------------------------------------------------------------------------


async def test_a_segment_request_leaves_a_session_that_owns_its_work(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Architecture section 4, asserted rather than intended: the process is in the manager.

    And it is in the ledger only while it is alive - a production that ran to the end is reaped
    by the request that noticed, so "what this server is running" stays answerable.
    """
    application, world = served
    item = world.of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)

    await client.get(uris[0], headers=HEADERS)

    sessions = application.state.transcodes.sessions
    assert len(sessions) == 1
    assert sessions[0].key.play_session_id == REENCODE_QUERY["playSessionId"]
    assert sessions[0].scratch.is_dir()
    for running in application.state.productions.live:
        assert running.process.returncode is None, "an exited encoder is still in the ledger"


# ------------------------------------------------------------------------------------------
# The refusals - measured on this route, in one probe run
# ------------------------------------------------------------------------------------------


async def test_an_item_nothing_holds_is_the_third_error_shape(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)
    query = uris[0].partition("?")[2]

    answered = await client.get(f"/Videos/{UNKNOWN_ITEM}/hls1/main/0.ts?{query}", headers=HEADERS)

    assert answered.status_code == 404
    assert answered.headers["Content-Type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY


async def test_a_media_source_id_naming_no_source_is_the_same_body_at_400(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)

    # Appended to the URI rather than passed as `params`, which would replace the whole query
    # and measure the missing-parameter refusal instead of this one.
    answered = await client.get(f"{uris[0]}&mediaSourceId={UNKNOWN_ITEM}", headers=HEADERS)

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY


async def test_a_segment_carrying_a_start_position_is_refused(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    media_paths: DataPaths,
) -> None:
    """A segment already says where it begins. Two positions in one request have no meaning, and
    the reference throws before it looks the item up - so nothing is produced either."""
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)

    answered = await client.get(f"{uris[0]}&startTimeTicks=600000000", headers=HEADERS)

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY
    assert scratch_files(media_paths) == []


async def test_a_segment_with_no_query_at_all_is_the_frameworks_refusal(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The one refusal on this route that is *not* the third shape, and the contrast that makes
    it interesting: `main.m3u8` with no query answers a playlist, and a segment with no query
    answers problem details, because two of its parameters are required."""
    item = served[1].of(LONG_TAKE)

    answered = await client.get(f"/Videos/{item.id}/hls1/main/0.ts", headers=HEADERS)

    assert answered.status_code == 400
    assert answered.headers["Content-Type"].startswith("application/json")
    assert set(answered.json()["errors"]) == {"runtimeTicks", "actualSegmentLengthTicks"}


async def test_the_segment_route_requires_a_token(
    unauthenticated: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The split behaviours section 2.10 records: the four `stream` routes require no credential
    and the three HLS routes do."""
    item = served[1].of(LONG_TAKE)

    answered = await unauthenticated.get(
        f"/Videos/{item.id}/hls1/main/0.ts",
        params={"runtimeTicks": 0, "actualSegmentLengthTicks": 30030000},
    )

    assert answered.status_code == 401
    assert answered.content == b""


# ------------------------------------------------------------------------------------------
# AC-31, the delivery half: a re-encode this account may not have
# ------------------------------------------------------------------------------------------


def _denying(**permissions: bool) -> Callable[[Request], User]:
    """The viewer, with some of the three playback permissions denied in the stored policy."""

    def resolve(request: Request) -> User:
        request.state.session_id = SESSION_ID
        request.state.token_sha256 = None
        return User(
            id=VIEWER_ID, name="viewer", enable_all_folders=True, policy_extra=dict(permissions)
        )

    return resolve


async def test_ac31_a_denied_re_encode_is_refused_rather_than_force_copied(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    media_paths: DataPaths,
) -> None:
    """The one edge behaviours section 2.21 does not replicate, at the one route that reaches it.

    The reference copies the video stream instead, "regardless of whether it will be compatible
    or not" `[source: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:7136-7145 @
    v10.11.11]` - an hevc-only client handed h264 - and Atrium refuses the step. Asserted with
    the scratch directory as well as with the status, because "never bytes that violate the
    negotiated profile" is a claim about what was *not* produced.
    """
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)
    served[0].dependency_overrides[require_user] = _denying(EnableVideoPlaybackTranscoding=False)

    answered = await client.get(uris[0], headers=HEADERS)

    assert answered.status_code == 500
    assert answered.headers["Content-Type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY
    assert scratch_files(media_paths) == []


async def test_ac31_a_denial_over_a_stream_that_is_copied_anyway_changes_nothing(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`EnablePlaybackRemuxing` has no delivery-time reader on either server, and the audio
    permission decides nothing about a plan whose audio is re-encoded by nobody's request.

    The negotiation's own rule is the same shape - a single denial moves nothing - so a client
    whose account is missing one permission plays exactly as a permitted one does.
    """
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **MIXED_QUERY)
    served[0].dependency_overrides[require_user] = _denying(
        EnablePlaybackRemuxing=False, EnableVideoPlaybackTranscoding=False
    )

    answered = await client.get(uris[0], headers=HEADERS)

    assert answered.status_code == 200, answered.text
    assert answered.content[:1] == b"G"


async def test_a_playlist_id_nothing_named_still_answers_the_segment(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Not a refusal, and worth a test for that reason: `playlistId` decides nothing on either
    server, so a URI naming a playlist that was never generated serves the segment anyway."""
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(client, item.id, **REENCODE_QUERY)

    answered = await client.get(uris[0].replace("/hls1/main/", "/hls1/banana/"), headers=HEADERS)

    assert answered.status_code == 200, answered.text
    assert answered.content[:1] == b"G"


async def test_ac16_and_ac22_a_copied_segment_is_sized_and_identical_twice(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], tmp_path: Path
) -> None:
    """The **remuxed** halves of AC-16 and AC-22, which every other segment test here misses.

    Every other segment in this file is produced by a plan that re-encodes the video, so "every
    segment carries a `Content-Length`, whether it was remuxed or re-encoded" was half asserted,
    and so was "the same **remuxed** source requested twice yields identical segment bytes" - the
    re-encoded twin of that sentence is AC-23 and has its own test. A bare variant request plans a
    copy at the copy default, which is what makes this a remux rather than a second re-encode with
    different arguments; the codec assertions are what prove it was one.
    """
    item = served[1].of(LONG_TAKE)
    uris, _durations = await segment_uris(
        client, item.id, playSessionId="c" * 32, deviceId=DEVICE_ID
    )

    answered = await client.get(uris[0], headers=HEADERS)
    again = await client.get(uris[0], headers=HEADERS)

    assert answered.status_code == 200, answered.text
    assert answered.headers["Content-Length"] == str(len(answered.content))
    assert answered.headers["Accept-Ranges"] == "bytes"
    assert again.content == answered.content

    delivered = tmp_path / "copied.ts"
    delivered.write_bytes(answered.content)
    streams = {
        one["codec_type"]: one
        for one in probe(delivered)["streams"]  # type: ignore[union-attr]
    }
    assert streams["video"]["codec_name"] == LONG_TAKE.video_codec
    assert streams["audio"]["codec_name"] == LONG_TAKE.audio_codec
