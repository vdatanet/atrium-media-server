# SPDX-License-Identifier: GPL-3.0-or-later
"""WAV: the two symptoms of behaviours section 3.2, answered with a real header.

The reference has one bug here and it comes out in two shapes, both measured at 008 T9 against a
live 10.11.11 `[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-29]`:

* a `500` - `stream.wav` naming no codec asks for an encoder called `wav`, and `stream.wav` with
  a `pcm_*` codec and no `audioBitRate` feeds an empty field to `-ar`. Two causes, one status;
* a `200` carrying **headerless PCM** behind an `audio/wav` label, whenever a bitrate was sent -
  on `stream.wav` and on `/universal` whose transcoding container is `wav` alike.

Atrium answers all of them with a real `RIFF….WAVE`, a `Content-Length` that is the body's, and
a `Range` that is honoured (AC-20). Two things in here are the *reason* that is possible rather
than the divergence itself, and they are asserted below the HTTP boundary on purpose:

* a `wav` muxer writing to a pipe fills both of its size fields with `ffffffff`, so the chunked
  shape of behaviours section 3.3 cannot carry this container at all;
* `media/ffmpeg.command` refuses to build that invocation, so the impossibility is structural
  rather than a rule a caller has to remember.

That split matters because every "streaming" test in this repository is a buffered one - httpx's
ASGI transport drives the application to completion (008 T7) - so a claim about what a header
would say mid-stream cannot be made through the client at all.
"""

from __future__ import annotations

import json
import struct
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.media import ffmpeg
from atrium.server import create_app
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    HIGH_RATE_AUDIO,
    BuiltMedia,
    ScannedMediaWorld,
    binary,
    build_scanned_media_world,
    probe,
)

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32

#: What a WAVE file begins with: `RIFF`, four bytes of size, then `WAVE`. The size counts
#: everything after those first eight bytes, which is what makes it checkable against the body.
RIFF = b"RIFF"
WAVE = b"WAVE"

#: The size a muxer writes when it does not know one and can never come back to fill it in.
UNKNOWN_SIZE = 0xFFFFFFFF

#: The codec a `wav` target names when the client named none (`media/ffmpeg.RAW_SAMPLE_CODECS`).
PCM = "pcm_s16le"

#: A ceiling below the 96 kHz source, so "the ceiling is honoured" is a real constraint here too.
CEILING_HZ = 22050

#: What 001's middleware puts on every response, excluded so the route's own set is what is read.
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
def track(served: tuple[FastAPI, ScannedMediaWorld]) -> tuple[str, Path]:
    """The 96 kHz FLAC and where its bytes are - a source no wav answer can reach by copying."""
    return served[1].of(HIGH_RATE_AUDIO).id, served[1].files.path_of(HIGH_RATE_AUDIO)


def riff_size(payload: bytes) -> int:
    """The length a RIFF header declares for everything after its first eight bytes."""
    return int(struct.unpack_from("<I", payload, 4)[0])


def audio_stream(body: bytes, tmp_path: Path, name: str) -> dict[str, Any]:
    """What the fixture module's independent demuxer says about bytes this test was handed."""
    written = tmp_path / name
    written.write_bytes(body)
    return next(one for one in dict(probe(written))["streams"] if one["codec_type"] == "audio")


def assert_real_wav(answered: httpx.Response) -> None:
    """The whole of "valid RIFF, real length": the magic, the label, and a size that agrees.

    The size check is the one that would have caught a piped answer: `ffffffff` there parses as a
    perfectly well-formed header and is wrong by four gigabytes.
    """
    body = answered.content
    assert answered.status_code == 200
    assert body[:4] == RIFF
    assert body[8:12] == WAVE
    assert answered.headers["Content-Type"] == "audio/wav"
    assert answered.headers["Content-Length"] == str(len(body))
    assert answered.headers["Accept-Ranges"] == "bytes"
    assert riff_size(body) == len(body) - 8


# ------------------------------------------------------------------------------------------
# AC-20, symptom 1 - the routes that answer 500 on the reference
# ------------------------------------------------------------------------------------------


async def test_ac20_the_suffixed_route_answers_a_real_wav(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """`stream.wav` naming no codec: `500` on the reference, because the codec it infers from the
    extension is `wav` and nothing encodes that. Here the container names its own codec."""
    item_id, _ = track

    answered = await client.get(f"/Audio/{item_id}/stream.wav")

    assert_real_wav(answered)
    stream = audio_stream(answered.content, tmp_path, "suffixed.wav")
    assert stream["codec_name"] == PCM
    assert stream["sample_rate"] == str(HIGH_RATE_AUDIO.sample_rate)


async def test_ac20_the_container_parameter_answers_the_same_wav(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """The other spelling of the same request, with the codec named the way the reference's own
    symptom names it. `container=wav&audioCodec=pcm_s16le` and no `audioBitRate` is the exact
    shape that answers `500` upstream - the `-ar` fed from an absent field."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/stream", params={"container": "wav", "audioCodec": PCM}
    )

    assert_real_wav(answered)
    assert audio_stream(answered.content, tmp_path, "parameter.wav")["codec_name"] == PCM


async def test_a_static_wav_request_is_still_the_source_bytes(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """The one shape of this defect that was never broken, asserted beside the two that were:
    `static=true` starts no encoder, so `stream.wav?static=true` is the FLAC behind an `audio/wav`
    label (behaviours section 2.20). The two halves of one URL, answering differently and both
    correctly."""
    item_id, path = track

    answered = await client.get(f"/Audio/{item_id}/stream.wav", params={"static": "true"})

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "audio/wav"
    assert answered.content == path.read_bytes()
    assert answered.content[:4] != RIFF


# ------------------------------------------------------------------------------------------
# AC-20, symptom 2 - /universal, where the reference sends headerless PCM
# ------------------------------------------------------------------------------------------


async def test_ac20_universal_with_a_wav_transcoding_container_answers_a_real_wav(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """Symptom 2's measured request: a `pcm_*` codec, a `wav` transcoding container and a bitrate
    answer `200`, `audio/wav` and a body that begins with samples rather than with `RIFF`.

    The criterion said `Container=wav` until this was measured - that parameter is the direct-play
    list and answers mp3 (see the test below).
    """
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={
            "container": "ogg",
            "transcodingContainer": "wav",
            "audioCodec": PCM,
            "audioBitRate": 128000,
        },
    )

    assert_real_wav(answered)
    assert audio_stream(answered.content, tmp_path, "universal.wav")["codec_name"] == PCM


async def test_universal_infers_pcm_when_a_wav_container_names_no_codec(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """The row the reference's inference table has not got. It answers this request with a real
    RIFF header too - and AAC inside it, because a codec-less streaming request is forced to
    `aac` by a validation guard and the wav muxer happens to accept that (behaviours section
    3.8). Atrium gives the container the codec the container is for."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={"container": "ogg", "transcodingContainer": "wav"},
    )

    assert_real_wav(answered)
    assert audio_stream(answered.content, tmp_path, "inferred.wav")["codec_name"] == PCM


async def test_the_container_parameter_is_the_direct_play_list_and_not_the_target(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """`/universal?container=wav` alone is **not** a wav request on either server: `container` is
    the list of things the client can play, and a source it does not cover transcodes to the
    default target. Measured as `audio/mpeg` on the reference, and mp3 here."""
    item_id, _ = track

    answered = await client.get(f"/Audio/{item_id}/universal", params={"container": "wav"})

    assert answered.status_code == 200
    assert answered.headers["Content-Type"] == "audio/mpeg"
    assert answered.content[:4] != RIFF


# ------------------------------------------------------------------------------------------
# AC-20's second half - a length that is real, and a Range that is honoured
# ------------------------------------------------------------------------------------------


async def test_ac20_a_mid_file_range_on_a_wav_answer_is_honoured(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """The divergence's other half. Every WAV answer on the reference is chunked with
    `Accept-Ranges: none` and ignores a `Range` outright, readable or not (behaviours section
    3.3); this one seeks, because the body was produced somewhere seekable before it was sent."""
    item_id, _ = track

    whole = await client.get(f"/Audio/{item_id}/stream.wav")
    part = await client.get(f"/Audio/{item_id}/stream.wav", headers={"Range": "bytes=100-199"})

    assert part.status_code == 206
    assert part.headers["Content-Range"] == f"bytes 100-199/{len(whole.content)}"
    assert part.headers["Content-Length"] == "100"
    assert part.content == whole.content[100:200]


async def test_a_wav_answer_carries_no_last_modified(
    client: httpx.AsyncClient, track: tuple[str, Path]
) -> None:
    """Sized, but not the file's: a produced body has no modification time to state, which is the
    same restraint the remux answer shows. The divergence adds a size and a range unit and
    nothing else."""
    item_id, _ = track

    answered = await client.get(f"/Audio/{item_id}/stream.wav")

    assert {name.lower() for name in answered.headers} - ALWAYS == {
        "content-length",
        "content-type",
        "accept-ranges",
    }


async def test_a_sample_rate_ceiling_is_honoured_on_a_wav_answer(
    client: httpx.AsyncClient, track: tuple[str, Path], tmp_path: Path
) -> None:
    """PCM is where a stated-everything plan would bite hardest - the raw encoders take any rate
    at all, so a wrong number is delivered rather than refused. The ceiling is below the source
    and is met exactly; the length still agrees with the header."""
    item_id, _ = track

    answered = await client.get(
        f"/Audio/{item_id}/universal",
        params={
            "container": "ogg",
            "transcodingContainer": "wav",
            "audioCodec": PCM,
            "maxAudioSampleRate": CEILING_HZ,
        },
    )

    assert_real_wav(answered)
    assert audio_stream(answered.content, tmp_path, "ceilinged.wav")["sample_rate"] == str(
        CEILING_HZ
    )


# ------------------------------------------------------------------------------------------
# Below the transport - why a wav answer cannot be the chunked one
# ------------------------------------------------------------------------------------------


def test_a_wav_muxer_writing_to_a_pipe_states_a_length_it_does_not_know(
    tmp_path: Path, media_files: BuiltMedia
) -> None:
    """The measurement the refusal rests on, made with ffmpeg directly rather than through any
    response: the same conversion to a file and to a pipe differs in exactly the eight bytes that
    say how long the body is - a WAVE states its length twice, in the `RIFF` header and again in
    the `data` chunk, and neither can be written by something that cannot seek back.

    Made here rather than asserted in a comment because it is the whole argument for producing
    WAV to scratch, and because no test that went through the client could ever see it - the
    ASGI transport buffers the body and hands back a finished one (008 T7).
    """
    source = media_files.path_of(HIGH_RATE_AUDIO)
    to_file = tmp_path / "seekable.wav"
    common = [
        binary("ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:0",
        "-c:a",
        PCM,
        "-f",
        "wav",
    ]
    subprocess.run([*common, str(to_file)], check=True, capture_output=True)  # noqa: S603
    piped = subprocess.run([*common, "pipe:1"], check=True, capture_output=True)  # noqa: S603

    written = to_file.read_bytes()
    assert written[:4] == RIFF and piped.stdout[:4] == RIFF
    assert len(written) == len(piped.stdout)
    assert riff_size(written) == len(written) - 8
    assert riff_size(piped.stdout) == UNKNOWN_SIZE
    # Eight bytes in the whole file: the RIFF size and the `data` chunk's, both `ffffffff`. The
    # offset of the second one moves with the encoder's own `LIST INFO` string, so it is found
    # rather than named - and everything that is not a length is byte-identical, which is what
    # makes this a fact about the header and not about the encode.
    differing = [index for index in range(len(written)) if written[index] != piped.stdout[index]]
    assert len(differing) == 8
    assert all(piped.stdout[index] == 0xFF for index in differing)


def test_a_wav_copy_of_a_flac_source_would_pass_a_riff_check_and_play_nowhere(
    tmp_path: Path, media_files: BuiltMedia
) -> None:
    """Why the wav container names its own codec rather than falling back to the source's.

    ffmpeg's wav muxer **accepts** a FLAC stream under a codec tag and writes a perfectly genuine
    `RIFF….WAVE` over it. So the obvious implementation - a bare `stream.wav` copies, the way a
    bare `stream.mkv` does - would satisfy every header assertion in this file and hand back
    something no wav decoder reads. Measured rather than argued, because "the muxer will refuse
    it" is exactly the assumption that would have made the rule look unnecessary.
    """
    copied = tmp_path / "copied.wav"
    subprocess.run(  # noqa: S603
        [
            binary("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(media_files.path_of(HIGH_RATE_AUDIO)),
            "-map",
            "0:0",
            "-c:a",
            "copy",
            "-f",
            "wav",
            str(copied),
        ],
        check=True,
        capture_output=True,
    )

    assert copied.read_bytes()[:4] == RIFF
    assert audio_stream(copied.read_bytes(), tmp_path, "copied-again.wav")["codec_name"] == "flac"
    assert ffmpeg.raw_codec_for("wav") == PCM
