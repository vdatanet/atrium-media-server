# SPDX-License-Identifier: GPL-3.0-or-later
"""`/Audio/{itemId}/universal`: the constraints are met, and three divergences are on the wire.

Every other delivery route in this feature is *told* what to produce. This one is told what the
client can play, so the assertions here are about the answer a negotiation reached rather than
about a parameter being honoured - and three of them are places Atrium deliberately answers
something the reference does not:

* the **sample rate is the ceiling the client stated**, where the reference answers the step of
  the Opus ladder above it (AC-19, behaviours section 3.7). Read with the probe's own STREAMINFO
  parse, so the number asserted here and the 24 000 measured there come from one reader;
* a request naming **no `audioCodec`** is answered with a real stream, where the reference
  answers `200` with an empty body (behaviours section 3.8);
* **`enableRedirection` never produces a `302`** for a local file (AC-21).

Plus the two shapes this route does not share with its `stream` siblings: it requires a token
(AC-32) and its unknown-item refusal is problem details, not the third error shape.

`[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-29]` is the measurement
behind every assertion in this file.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.compat.errors import CONTROLLER_ERROR_BODY, CONTROLLER_ERROR_TYPE
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.media.info import source_id
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    HIGH_RATE_AUDIO,
    BuiltMedia,
    ScannedMediaWorld,
    build_scanned_media_world,
    probe,
)

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

REPO_ROOT = Path(__file__).resolve().parents[2]

VIEWER_ID = "e" * 32

#: An identifier no scan produced, and the two `mediaSourceId` values the reference splits on the
#: `stream` routes and does **not** split here - both `400` (behaviours section 3.9).
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"
UNKNOWN_SOURCE = "beefdeadbeefdeadbeefdeadbeefdead"
UNPARSEABLE_SOURCE = "banana"

#: The ceiling the reference answers at 24 000 Hz. Below every step of its ladder's neighbours,
#: which is what makes the two answers distinguishable at all.
CEILING_HZ = 22050

#: The complete header set of a direct-play answer, measured on this route rather than assumed
#: from the `stream` pair's - it is the same four, and that is a finding rather than a default.
DIRECT_PLAY_HEADERS = {"content-length", "content-type", "accept-ranges", "last-modified"}

#: What 001's middleware puts on every response. Excluded so this file asserts the route's own.
ALWAYS = {"server", "x-response-time-ms"}


def probe_script() -> Any:
    """The probe module, loaded by path so its readers are literally the ones that measured.

    `tests/conformance/test_routes.py` loads `extract_v1_surface.py` the same way and for the same
    reason: two parsers of one format eventually disagree, and the one that disagrees silently is
    the one nobody ran against the reference. `tools/` is standard library only and does nothing
    at import - no connection is opened until `main` runs, which is what keeps this inside the
    suite's no-network rule.
    """
    tools = str(REPO_ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    path = REPO_ROOT / "tools" / "probe_universal_audio.py"
    spec = importlib.util.spec_from_file_location("atrium_universal_probe", path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


@pytest.fixture
async def unauthenticated(
    served: tuple[FastAPI, ScannedMediaWorld],
) -> AsyncIterator[httpx.AsyncClient]:
    """The same application with the override removed, so `require_user` is the real one."""
    served[0].dependency_overrides.clear()
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


@pytest.fixture
def track(served: tuple[FastAPI, ScannedMediaWorld]) -> tuple[str, Path]:
    """The 96 kHz FLAC and where its bytes are - the one source above every stated ceiling."""
    return served[1].of(HIGH_RATE_AUDIO).id, served[1].files.path_of(HIGH_RATE_AUDIO)


def inspected(body: bytes, tmp_path: Path, name: str) -> dict[str, Any]:
    """What the fixture module's independent ffprobe says about bytes this test was handed."""
    written = tmp_path / name
    written.write_bytes(body)
    return dict(probe(written))


def audio_stream(inspection: dict[str, Any]) -> dict[str, Any]:
    return next(one for one in inspection["streams"] if one["codec_type"] == "audio")


def _without_trace(body: dict[str, Any]) -> dict[str, Any]:
    """A problem-details body minus the one key that is per request on both servers."""
    return {name: value for name, value in body.items() if name != "traceId"}


# ------------------------------------------------------------------------------------------
# AC-19 - the ceiling is the target, not the ladder step above it
# ------------------------------------------------------------------------------------------


async def test_ac19_a_sample_rate_ceiling_is_answered_at_the_ceiling(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """The divergence, read the way it was measured.

    `maxAudioSampleRate=22050` against a 96 kHz source: the reference answers 24 000 Hz - the
    Opus ladder applied to a codec that is not Opus - and Atrium answers 22 050. Both numbers
    come out of the same STREAMINFO reader, so the comparison is between two servers rather than
    between two implementations of a header parse.
    """
    script = probe_script()
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={
            "container": "ogg",
            "transcodingContainer": "flac",
            "transcodingProtocol": "http",
            "audioCodec": "flac",
            "maxAudioSampleRate": CEILING_HZ,
        },
    )

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "audio/flac"
    assert script.flac_sample_rate(answered.content) == CEILING_HZ
    assert script.opus_ladder(CEILING_HZ) == 24000
    # And again through a demuxer, so the claim does not rest on one header parse.
    assert audio_stream(inspected(answered.content, tmp_path, "ceilinged.flac"))[
        "sample_rate"
    ] == str(CEILING_HZ)


async def test_ac19_a_channel_ceiling_below_the_source_is_honoured_too(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """AC-19's other reachable clause. The source is stereo; one channel is asked for and one
    arrives, which is the same `min(profile, source)` the rate went through."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={
            "container": "ogg",
            "transcodingContainer": "flac",
            "audioCodec": "flac",
            "maxAudioChannels": 1,
        },
    )

    assert answered.status_code == 200
    assert audio_stream(inspected(answered.content, tmp_path, "mono.flac"))["channels"] == 1


async def test_a_ceiling_the_source_already_meets_changes_nothing(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """The other side of "limits, not targets", and the rule 008 T7 had to discover: a ceiling
    equal to or above the source is not an instruction. A 192 kHz ceiling over a 96 kHz source is
    answered at 96 kHz and never up-sampled to fill it (AC-9's audio form)."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={
            "container": "ogg",
            "transcodingContainer": "flac",
            "audioCodec": "flac",
            "maxAudioSampleRate": 192000,
        },
    )

    assert answered.status_code == 200
    assert audio_stream(inspected(answered.content, tmp_path, "unclamped.flac"))[
        "sample_rate"
    ] == str(HIGH_RATE_AUDIO.sample_rate)


# ------------------------------------------------------------------------------------------
# AC-21 - direct play is the file, and redirection never fires
# ------------------------------------------------------------------------------------------


async def test_ac21_a_satisfied_constraint_set_is_the_file_with_no_location(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """`enableRedirection=true` on a local source: `200` with the bytes, no `Location`.

    The reference's `302` needs a remote HTTP source and `EnableRemoteMedia` at once, and v1 has
    no remote sources - so this is the whole of the reachable rule, measured rather than argued.
    """
    item_id, path = track
    payload = path.read_bytes()

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={"container": "flac", "enableRedirection": "true"},
    )

    assert answered.status_code == 200
    assert "location" not in {name.lower() for name in answered.headers}
    assert answered.content == payload


async def test_the_direct_play_answer_carries_exactly_the_measured_header_set(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """Four headers and no fifth - the same set the `stream` routes answer with, asserted here
    because it was measured here: no `ETag`, no `Content-Disposition`, no `Cache-Control`."""
    item_id, path = track

    answered = await client.get(f"/Audio/{item_id}/universal", params={"container": "flac"})

    assert answered.status_code == 200
    assert {name.lower() for name in answered.headers} - ALWAYS == DIRECT_PLAY_HEADERS
    assert answered.headers["Content-Length"] == str(path.stat().st_size)
    assert answered.headers["Accept-Ranges"] == "bytes"
    assert answered.headers["Content-Type"] == "audio/flac"


async def test_a_range_on_the_direct_play_answer_is_honoured(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """Measured on the reference: `bytes=8-15` is a `206` with a correct `Content-Range` and
    eight bytes. Direct play here is the same sized answer the static half serves."""
    item_id, path = track
    payload = path.read_bytes()

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={"container": "flac"},
        headers={"Range": "bytes=8-15"},
    )

    assert answered.status_code == 206
    assert answered.headers["Content-Range"] == f"bytes 8-15/{len(payload)}"
    assert answered.content == payload[8:16]


# ------------------------------------------------------------------------------------------
# Behaviours section 3.8 - a codec-less request is answered
# ------------------------------------------------------------------------------------------


async def test_a_codec_less_transcode_takes_the_transcoding_containers_own_codec(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """The reference answers `200` with `Content-Length: 0` and nothing behind it, because the
    codec it infers comes from a request path that has no extension. Atrium gives that same
    inference the container it was written for: `flac` in, `flac` out, and a body."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={
            "container": "ogg",
            "transcodingContainer": "flac",
            "transcodingProtocol": "http",
        },
    )

    assert answered.status_code == 200
    assert answered.content[:4] == b"fLaC"
    assert audio_stream(inspected(answered.content, tmp_path, "inferred.flac"))["codec_name"] == (
        "flac"
    )


async def test_a_codec_less_transcode_with_no_container_either_is_the_mp3_default(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """Measured with **no** `transcodingContainer`: the reference resolves the container fine -
    it answers `Content-Type: audio/mpeg` - and still sends an empty body, which is what shows
    the hole is the codec and not the container. The reference's own default is mp3 for both, so
    this is the request where Atrium and the reference agree about the target and differ only in
    whether anything arrives."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={"container": "ogg", "transcodingProtocol": "http"},
    )

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "audio/mpeg"
    assert audio_stream(inspected(answered.content, tmp_path, "default.mp3"))["codec_name"] == "mp3"


# ------------------------------------------------------------------------------------------
# The shapes this route does not share with its siblings
# ------------------------------------------------------------------------------------------


async def test_ac32_universal_refuses_without_a_token_where_stream_does_not(
    unauthenticated: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """The split AC-32 records, on one transport so neither half can be a property of the client.

    `/universal` answers the empty `401`; `/Audio/{itemId}/stream` answers the file. This is the
    one row of the credential measurement that went the other way from its four siblings.
    """
    item_id, path = track

    refused = await unauthenticated.get(f"/Audio/{item_id}/universal", params={"container": "flac"})
    served = await unauthenticated.get(f"/Audio/{item_id}/stream", params={"static": "true"})

    assert refused.status_code == 401
    assert refused.content == b""
    assert "content-type" not in {name.lower() for name in refused.headers}
    assert served.status_code == 200
    assert served.content == path.read_bytes()


async def test_an_unknown_item_is_problem_details_here_and_text_next_door(
    client: httpx.AsyncClient,
) -> None:
    """One identifier, one feature, two bodies - the pair 008 T6 found and this route reverses.

    The universal controller refuses through the framework's own not-found result, so its body is
    RFC 9457 and identical to `GET /Items/{itemId}`'s apart from the trace identifier, which is
    per request on both servers; the `stream` pair throws out of the streaming helper and answers
    the fixed 25 bytes as `text/plain`.
    """
    universal = await client.get(f"/Audio/{UNKNOWN_ITEM}/universal", params={"container": "flac"})
    stream = await client.get(f"/Audio/{UNKNOWN_ITEM}/stream", params={"static": "true"})
    item = await client.get(f"/Items/{UNKNOWN_ITEM}")

    assert universal.status_code == 404
    assert universal.headers["Content-Type"] == "application/json; charset=utf-8"
    assert _without_trace(universal.json()) == _without_trace(item.json())
    assert stream.status_code == 404
    assert stream.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert stream.content == CONTROLLER_ERROR_BODY


@pytest.mark.parametrize("named", [UNKNOWN_SOURCE, UNPARSEABLE_SOURCE])
async def test_a_media_source_id_naming_no_source_is_one_refusal_for_both_values(
    client: httpx.AsyncClient, track: tuple[str, Path], named: str
) -> None:
    """Measured on this route: **both** values answer `400` in the third error shape, where the
    `stream` pair splits them `400`/`500` on whether the string parses as an identifier. So the
    single `400` behaviours section 3.9 chose for both is not a third behaviour at all - it is
    what the reference itself answers, one route away, to both of them."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal", params={"container": "flac", "mediaSourceId": named}
    )

    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == CONTROLLER_ERROR_TYPE
    assert answered.content == CONTROLLER_ERROR_BODY


async def test_a_media_source_id_naming_the_only_source_is_served(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], track: tuple[str, Path]
) -> None:
    """The refusals above are only meaningful if a real identifier is not refused - the same
    derivation `PlaybackInfo` hands the client, replayed here."""
    item_id, path = track
    named = source_id(item_id, 0, HIGH_RATE_AUDIO.path)

    answered = await client.get(
        f"/Audio/{item_id}/universal", params={"container": "flac", "mediaSourceId": named}
    )

    assert answered.status_code == 200
    assert answered.content == path.read_bytes()


async def test_the_hls_variant_is_refused_until_the_playlists_exist(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """The one shape this task leaves incomplete, asserted so it cannot go unnoticed.

    The reference answers `transcodingProtocol=hls` with a master playlist; 008 T10 builds those,
    and until it does the honest answer is the refusal every unproducible request gets. A
    playlist naming segments nothing can serve would be a stub that lies (Principle VI).
    """
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={
            "container": "ogg",
            "transcodingContainer": "flac",
            "audioCodec": "flac",
            "transcodingProtocol": "hls",
        },
    )

    assert answered.status_code == 500
    assert answered.content == CONTROLLER_ERROR_BODY
