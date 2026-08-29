# SPDX-License-Identifier: GPL-3.0-or-later
"""The two playlists, over the HTTP boundary, on a session where nothing has been produced.

The whole point of predicting boundaries is that the answer exists before the work does, so the
central assertion here is an **absence**: the media playlist arrives complete and `ENDLIST`-marked
with a `Content-Length`, and the scratch directory is still empty afterwards. That is AC-22's
playlist half; its boundary half is the same list twice, byte for byte.

The other half of this file follows the negotiation rather than hand-writing a query: a
`PlaybackInfo` against a real 23.976 fps file, then the `TranscodingUrl` it hands back, then the
master, then the variant. Only the round trip can show that T5's URL and T10's cadence agree about
`MaxFramerate`, which is the parameter the whole rounding rule turns on.

`tests/unit/test_hls_planning.py` owns the arithmetic and the bytes. What is proven here is the
wiring, the headers, and the three refusals.

`[probe: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]` is the measurement behind every
expected value.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
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
    HIGH_RANGE,
    LONG_TAKE,
    REJECTED_AUDIO,
    BuiltMedia,
    ScannedMediaWorld,
    build_scanned_media_world,
    generate,
    keyframe_seconds,
)

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

#: `long_take` remuxed into Matroska, and the only reason it exists: the reference buckets a
#: stream copy's boundaries from the file's own keyframes **only** for an extension the operator
#: has allowed on-demand extraction for, and ships that list as `mkv` alone. The mp4 entry beside
#: it answers the equal grid, which is where the published 6.0 s came from - so one container
#: cannot prove either half.
LONG_TAKE_MKV = replace(
    LONG_TAKE,
    key="long_take_mkv",
    path="The Long Take In Matroska (2005)/The Long Take In Matroska (2005).mkv",
    muxer="matroska",
    demuxers="matroska,webm",
)

#: A profile whose only playable answer is a re-encode, and the target names **hevc** for one
#: reason: `long_take` is h264, so a target listing h264 would be answered by copying it - on this
#: server and on the reference alike, because both re-read the negotiated URL's `VideoCodec` and
#: both copy what they can. The published 3.004 s came from an hevc film offered an h264 target;
#: the only 23.976 fps fixture in this repository is h264, so the pair is inverted here.
REENCODE = {
    "MaxStreamingBitrate": 120_000_000,
    "DirectPlayProfiles": [
        {"Container": "mkv", "Type": "Video", "VideoCodec": "vp9", "AudioCodec": "ac3"}
    ],
    "TranscodingProfiles": [
        {
            "Container": "ts",
            "Type": "Video",
            "VideoCodec": "hevc",
            "AudioCodec": "aac",
            "Protocol": "hls",
            "Context": "Streaming",
            "MinSegments": 1,
            "BreakOnNonKeyFrames": True,
        }
    ],
    "CodecProfiles": [],
    "ContainerProfiles": [],
    "SubtitleProfiles": [],
}

#: The profile that takes the video and refuses the audio, which is the only way to reach a
#: **stream copy** over HLS - and the SDR entrance stands beside a copy and never beside a
#: re-encode. Named for what it does rather than for the entry it is used on: `high_range` and
#: `rejected_audio` are the same h264-in-mp4-with-ac3 shape, and that is what makes the two
#: comparable.
COPY_THE_VIDEO = {
    "MaxStreamingBitrate": 120_000_000,
    "DirectPlayProfiles": [
        {"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "flac"}
    ],
    "TranscodingProfiles": [
        {
            "Container": "ts",
            "Type": "Video",
            "VideoCodec": "h264",
            "AudioCodec": "aac",
            "Protocol": "hls",
            "Context": "Streaming",
            "MinSegments": 1,
            "BreakOnNonKeyFrames": True,
        }
    ],
    "CodecProfiles": [],
    "ContainerProfiles": [],
    "SubtitleProfiles": [],
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
def with_matroska(media_files: BuiltMedia, tmp_path: Path) -> BuiltMedia:
    """The generated matrix plus one Matroska sibling, in a tree this test may write to."""
    copied = media_files.copy_into(tmp_path / "media")
    generate(LONG_TAKE_MKV, copied.base)
    return copied


@pytest.fixture
def served(
    media_paths: DataPaths, with_matroska: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    built = create_app(media_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_scanned_media_world(opened, with_matroska)
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


@pytest.fixture
async def unauthenticated(
    served: tuple[FastAPI, ScannedMediaWorld],
) -> AsyncIterator[httpx.AsyncClient]:
    """The same application with the real `require_user`, so the credential test is not vacuous."""
    served[0].dependency_overrides.clear()
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def extinf(body: str) -> list[float]:
    return [
        float(line.split(":", 1)[1].split(",", 1)[0])
        for line in body.splitlines()
        if line.startswith("#EXTINF")
    ]


async def negotiated_playlists(
    client: httpx.AsyncClient, item_id: str
) -> tuple[httpx.Response, httpx.Response]:
    """`PlaybackInfo`, then the `TranscodingUrl` it answered, then the variant that names.

    The URL is followed rather than rebuilt, so the parameters the cadence turns on - `MaxFramerate`
    above all - are the ones the negotiation really wrote.
    """
    answered = await client.post(
        f"/Items/{item_id}/PlaybackInfo", json={"DeviceProfile": REENCODE}, headers=HEADERS
    )
    assert answered.status_code == 200, answered.text
    url = answered.json()["MediaSources"][0]["TranscodingUrl"]
    assert "master.m3u8" in url, url

    master = await client.get(url, headers=HEADERS)
    assert master.status_code == 200, master.text
    variant = next(line for line in master.text.splitlines() if line.startswith("main.m3u8"))
    main = await client.get(f"/Videos/{item_id}/{variant}", headers=HEADERS)
    assert main.status_code == 200, main.text
    return master, main


# ------------------------------------------------------------------------------------------
# AC-22: complete before anything is produced, and identical twice
# ------------------------------------------------------------------------------------------


async def test_ac22_the_playlist_is_complete_and_sized_before_any_segment_exists(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    media_paths: DataPaths,
) -> None:
    """The measured headline, at this scale: a whole playlist, ended, with a length, and nothing
    on disk to have derived it from."""
    item = served[1].of(LONG_TAKE)

    _master, main = await negotiated_playlists(client, item.id)

    assert main.headers["Content-Type"] == MEDIA_TYPES["m3u8"]
    assert main.headers["Content-Length"] == str(len(main.content))
    assert main.text.startswith("#EXTM3U\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXT-X-VERSION:3\n")
    assert main.text.endswith("#EXT-X-ENDLIST\n")
    assert "Expires" not in main.headers, "measured on the variant: only the master carries one"
    assert list(media_paths.transcodes.iterdir()) == [], (
        "a playlist that had to produce something to answer is not a predicted playlist"
    )


async def test_ac22_the_same_request_twice_is_the_same_list(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Deterministic boundaries are what make a re-requested segment servable at all: a server
    that re-derived them per session could not answer a retry."""
    item = served[1].of(LONG_TAKE)

    _first_master, first = await negotiated_playlists(client, item.id)
    _second_master, second = await negotiated_playlists(client, item.id)

    assert extinf(first.text) == extinf(second.text)
    assert first.text.count("#EXTINF") == second.text.count("#EXTINF")


# ------------------------------------------------------------------------------------------
# The cadence, through the negotiation that sets it
# ------------------------------------------------------------------------------------------


async def test_the_re_encode_cadence_is_the_rounding_rule_over_the_fixtures_own_rate(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """**3.003 s, not the published 3.004 s** - and that is the rule reproducing, not failing.

    `long_take` runs at an exact `24000/1001`, which reaches the URL as `MaxFramerate=23.976025`;
    `ceil(3000 * 24 / 23.976025) = 3003`. The measured film's container stores `23.975988`
    instead, and the same arithmetic gives 3004 there. Spec section 3.7's "the forced-keyframe
    cadence at 23.976 fps" reads as though the number followed from the nominal rate; it follows
    from the stored one.
    """
    item = served[1].of(LONG_TAKE)

    master, main = await negotiated_playlists(client, item.id)

    assert "&MaxFramerate=23.976025" in master.text
    durations = extinf(main.text)
    assert set(durations[:-1]) == {3.003}
    assert durations[-1] <= durations[0], "AC-22's boundary half: only the last is shorter"
    assert sum(durations) == pytest.approx(LONG_TAKE.duration_seconds, abs=0.05)


async def test_the_master_carries_one_variant_and_the_whole_forwarded_query(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """One `#EXT-X-STREAM-INF` for a **standard-range** negotiation, never a ladder - and its URI
    is the query verbatim, `?&` doubling included, because that is what carries the negotiation
    to the next hop.

    The range qualifier is the whole of what the spec's first answer was missing: it read as a
    property of the route and is a property of the source, and the test below is the other half.
    """
    item = served[1].of(LONG_TAKE)
    answered = await client.post(
        f"/Items/{item.id}/PlaybackInfo", json={"DeviceProfile": REENCODE}, headers=HEADERS
    )
    url = answered.json()["MediaSources"][0]["TranscodingUrl"]
    query = url.split("master.m3u8", 1)[1]

    master = await client.get(url, headers=HEADERS)

    lines = master.text.splitlines()
    assert len(lines) == 3
    assert lines[0] == "#EXTM3U"
    assert lines[1].startswith("#EXT-X-STREAM-INF:BANDWIDTH=")
    assert "RESOLUTION=1280x720" in lines[1], "AC-9: a 720p source is described at 720p"
    assert "FRAME-RATE=23.976" in lines[1]
    assert 'CODECS="hvc1.1.4.L120.B0,mp4a.40.2"' in lines[1], (
        "level 120 is the *default* for an hevc target, not the source's: the negotiated URL "
        "carries `h264-level=31` because the stream-option triplet is qualified by the source's "
        "codec, and the reference looks it up under the target's - so it finds nothing"
    )
    assert lines[2] == f"main.m3u8{query}"
    assert master.headers["Expires"] == "0"
    assert master.headers["Content-Type"] == MEDIA_TYPES["m3u8"]
    assert master.headers["Content-Length"] == str(len(master.content))


async def test_an_hdr_copy_grows_a_second_variant_and_a_standard_range_one_does_not(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Both halves of the branch in one test, on **two files that differ only in colour**.

    `high_range` and `rejected_audio` are the same h264-in-mp4-beside-ac3 shape, negotiated with
    the same profile and copied the same way; the only thing that moves is the source's transfer
    characteristics. So the second `#EXT-X-STREAM-INF` is attributable to that and to nothing
    else - which is exactly what the measurement OQ-7 was answered from could not establish,
    because it had one file and never looked at its range.
    """
    hdr = served[1].of(HIGH_RANGE)
    sdr = served[1].of(REJECTED_AUDIO)

    masters = {}
    for key, item in (("hdr", hdr), ("sdr", sdr)):
        answered = await client.post(
            f"/Items/{item.id}/PlaybackInfo",
            json={"DeviceProfile": COPY_THE_VIDEO},
            headers=HEADERS,
        )
        assert answered.status_code == 200, answered.text
        source = answered.json()["MediaSources"][0]
        assert source["TranscodingUrl"], f"{key}: the audio rejection planned no transcode"
        masters[key] = await client.get(source["TranscodingUrl"], headers=HEADERS)

    sdr_lines = masters["sdr"].text.splitlines()
    assert len(sdr_lines) == 3, "a standard-range copy still answers exactly one variant"

    lines = masters["hdr"].text.splitlines()
    assert len(lines) == 5
    assert "VIDEO-RANGE=PQ" in lines[1], "the copy is labelled by the source's own transfer"
    assert "VIDEO-RANGE=SDR" in lines[3], "the entrance is a re-encode, and those are always SDR"
    # The entrance is offered at the copy's own rate, so nothing selects on bandwidth: the client
    # is meant to choose by colour range.
    for field in ("BANDWIDTH=", "AVERAGE-BANDWIDTH=", "RESOLUTION=", "FRAME-RATE="):
        assert _field(lines[1], field) == _field(lines[3], field)
    assert 'CODECS="avc1.42400D' in lines[3], (
        "level 13 rather than the default 41, because this source *is* h264: the negotiated URL "
        "writes its stream-option triplet qualified by the source's codec, and the entrance "
        "looks it up under the target's - which here are the same codec, so it finds it. "
        "`High 10` is not one of the three profiles the reference names, so both servers fall "
        "back to constrained baseline's `4240`"
    )
    assert "VideoCodec=h264" in lines[4]
    assert lines[4].endswith("&AllowVideoStreamCopy=false")
    assert "?&" not in lines[4], "the entrance's address is rewritten, so the doubling goes"
    assert masters["hdr"].headers["Content-Length"] == str(len(masters["hdr"].content))


def _field(line: str, name: str) -> str:
    """One `#EXT-X-STREAM-INF` attribute, for comparing two variant lines field by field."""
    return line.split(name, 1)[1].split(",", 1)[0]


# ------------------------------------------------------------------------------------------
# The copy: the grid, and the buckets that only one container gets
# ------------------------------------------------------------------------------------------


async def test_a_copy_in_matroska_cuts_on_the_files_own_keyframes(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    with_matroska: BuiltMedia,
) -> None:
    """Every boundary is a real keyframe, read out of the file by ffprobe rather than by anything
    under test - which is what makes "the copy plan reproduces keyframe alignment" an assertion.

    Asked for at 5 s over a file with keyframes every 2 s, so the buckets cannot coincide with the
    grid: the cuts land at 6 s and 10 s.
    """
    item = served[1].of(LONG_TAKE_MKV)
    keyframes = keyframe_seconds(with_matroska.path_of(LONG_TAKE_MKV))
    assert len(keyframes) > 3, "the Matroska sibling stopped carrying a keyframe cadence"

    answered = await client.get(
        f"/Videos/{item.id}/main.m3u8",
        params={"segmentLength": 5, "videoCodec": "h264", "audioCodec": "aac"},
        headers=HEADERS,
    )

    assert answered.status_code == 200, answered.text
    durations = extinf(answered.text)
    boundaries = [round(sum(durations[: index + 1]), 3) for index in range(len(durations) - 1)]
    assert boundaries, "a single-segment playlist proves nothing about bucketing"
    for boundary in boundaries:
        assert any(abs(boundary - one) < 0.001 for one in keyframes), (
            f"segment boundary {boundary} is not a keyframe of {keyframes}"
        )
    assert durations[0] != 5.0, "the buckets coincided with the grid, so nothing was measured"


async def test_a_copy_in_mp4_is_the_equal_grid_and_not_the_keyframes(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The finding, reproduced: the same content in mp4 is cut on the requested length exactly.

    The reference reads keyframes on demand only for an extension its
    `AllowOnDemandMetadataBasedKeyframeExtractionForExtensions` names, whose shipped value is
    `mkv`. So the published "6.0 s per segment stream-copied (the source's own keyframes)" is the
    equal grid at the copy default, measured on an mp4 film.
    """
    item = served[1].of(LONG_TAKE)

    answered = await client.get(
        f"/Videos/{item.id}/main.m3u8",
        params={"segmentLength": 5, "videoCodec": "h264", "audioCodec": "aac"},
        headers=HEADERS,
    )

    assert answered.status_code == 200, answered.text
    durations = extinf(answered.text)
    assert set(durations[:-1]) == {5.0}


async def test_a_bare_variant_request_plans_a_copy_at_the_copy_default(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`main.m3u8` with nothing at all is not a refusal on either server: no codec named is the
    source's own, which is a copy, and a copy's unrequested cadence is six seconds."""
    item = served[1].of(LONG_TAKE)

    answered = await client.get(f"/Videos/{item.id}/main.m3u8", headers=HEADERS)

    assert answered.status_code == 200, answered.text
    assert extinf(answered.text)[0] == 6.0
    assert "#EXT-X-TARGETDURATION:6" in answered.text


# ------------------------------------------------------------------------------------------
# The refusals - the three shapes, measured on these two routes
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["master.m3u8", "main.m3u8"])
async def test_an_item_nothing_holds_is_the_third_error_shape(
    client: httpx.AsyncClient, route: str
) -> None:
    """`404`, `text/plain`, the fixed 25 bytes - the `stream` pair's refusal and not
    `/universal`'s problem details, measured on both playlist routes in one run."""
    answered = await client.get(f"/Videos/{UNKNOWN_ITEM}/{route}", headers=HEADERS)

    assert answered.status_code == 404
    assert answered.headers["Content-Type"] == "text/plain"
    assert answered.content == CONTROLLER_ERROR_BODY


async def test_a_media_source_id_naming_no_source_is_the_same_body_at_400(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    item = served[1].of(LONG_TAKE)

    answered = await client.get(
        f"/Videos/{item.id}/master.m3u8", params={"mediaSourceId": UNKNOWN_ITEM}, headers=HEADERS
    )

    assert answered.status_code == 400
    assert answered.content == CONTROLLER_ERROR_BODY


@pytest.mark.parametrize("route", ["master.m3u8", "main.m3u8"])
async def test_the_playlists_require_a_token_where_their_siblings_require_none(
    unauthenticated: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], route: str
) -> None:
    """The split behaviours section 2.10 records, from the other side: the four `stream` routes
    answer `200` to a request carrying nothing and these two answer the empty `401`, because the
    reference's whole HLS controller carries `[Authorize]` and its stream actions do not."""
    item = served[1].of(LONG_TAKE)

    answered = await unauthenticated.get(f"/Videos/{item.id}/{route}")

    assert answered.status_code == 401
    assert answered.content == b""


def test_the_matroska_sibling_really_is_a_different_container() -> None:
    """A guard on the fixture rather than on the code: if the remux stopped being Matroska, the
    bucketing test above would pass for the wrong reason."""
    assert LONG_TAKE_MKV.path.endswith(".mkv")
    assert LONG_TAKE.path.endswith(".mp4")
    assert LONG_TAKE_MKV.keyframe_interval_seconds == LONG_TAKE.keyframe_interval_seconds


# ------------------------------------------------------------------------------------------
# AC-11's boundary: these are the two sized delivery responses with no range unit
# ------------------------------------------------------------------------------------------


async def test_ac11_a_playlist_is_sized_and_carries_no_range_unit(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-11 stops here, and the stopping point is measured rather than deduced from the rule.

    Spec section 3.5's table reads *"`Accept-Ranges: bytes` on every delivery response whose body
    has a known size"*, and these two routes are where that sentence is wrong: the reference's
    master and media playlists answer `Content-Length`, `Content-Type` and no range unit at all,
    where its segments carry both `[probe: tools/probe_hls.py, Jellyfin 10.11.11, 2026-08-29]`.
    Reproduced rather than tidied - sending the header the rule implies would be a header the
    reference does not send, on the one delivery family a client parses as text.
    """
    item = served[1].of(LONG_TAKE)

    master, main = await negotiated_playlists(client, item.id)

    for answered in (master, main):
        assert answered.headers["Content-Type"] == MEDIA_TYPES["m3u8"]
        assert answered.headers["Content-Length"] == str(len(answered.content))
        assert "Accept-Ranges" not in answered.headers
        assert "Content-Range" not in answered.headers
