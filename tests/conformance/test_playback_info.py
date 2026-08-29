# SPDX-License-Identifier: GPL-3.0-or-later
"""What a client is told it may do with a file, over files that really exist.

Every case here runs against 008 T1's generated matrix, scanned by the real 003 pipeline and
served through the real routes, because a negotiation is only meaningful about a file something
opened: the profiles below reject a container this world really has and a codec it really carries,
so an answer is attributable to the rejection rather than to a fixture that stated it.

The classes are the ones spec section 3.3 names, and two of them are the pair 008 T4 measured as
**opposites**: no profile at all is direct play with every flag true, and an empty profile
*object* is every flag false - a client that named no container, no codec and no target has told
us it can play nothing.

`tests/unit/test_media_decision.py` owns the ladder itself, fifty-six rows of it. What is proven
here is the **wiring**: that the body reaches the ladder, that the answer reaches the wire in the
reference's own shape, and that the `TranscodingUrl` a client parses is spelled the way the
reference spells it - which is one exact string rather than a set of parameters that happen to be
present.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db.repositories import SessionRepository, UserRepository
from atrium.domain.session import Session
from atrium.domain.user import User
from atrium.media.info import media_etag
from atrium.media.urls import dashed
from atrium.server import create_app
from atrium.users.policy import AUDIO_TRANSCODING, REMUXING, VIDEO_TRANSCODING
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    DIRECT_PLAY,
    REJECTED_AUDIO,
    REJECTED_CONTAINER,
    REJECTED_VIDEO,
    BuiltMedia,
    MediaFile,
    ScannedMediaWorld,
    build_scanned_media_world,
)

pytestmark = [pytest.mark.conformance, pytest.mark.ffmpeg]

VIEWER_ID = "e" * 32
SESSION_ID = "f" * 32

#: What the request carries so the URL's `ApiKey` and `DeviceId` have something to be. The token
#: never resolves to anything - `require_user` is overridden - which is the point: these two
#: parameters are copied out of the request, not looked up.
TOKEN = "0123456789abcdef0123456789abcdef"
DEVICE_ID = "test-device-0001"
HEADERS = {
    "X-Emby-Token": TOKEN,
    "X-Emby-Authorization": (
        f'MediaBrowser Client="tests", Device="pytest", DeviceId="{DEVICE_ID}", Version="1"'
    ),
}

#: The transcoding target every profile below offers: what a browser profile offers.
TS_HLS = {
    "Container": "ts",
    "Type": "Video",
    "VideoCodec": "h264",
    "AudioCodec": "aac",
    "Protocol": "hls",
    "Context": "Streaming",
    "MinSegments": 1,
    "BreakOnNonKeyFrames": True,
}


def profile(
    direct_play: list[dict[str, Any]],
    transcoding: list[dict[str, Any]] | None = None,
    codec_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A device profile in the shape a client posts one, with the four lists that matter."""
    return {
        "MaxStreamingBitrate": 120_000_000,
        "DirectPlayProfiles": direct_play,
        "TranscodingProfiles": [TS_HLS] if transcoding is None else transcoding,
        "CodecProfiles": codec_profiles or [],
        "ContainerProfiles": [],
        "SubtitleProfiles": [],
    }


def accepting(one: MediaFile) -> dict[str, Any]:
    """A profile that takes this file exactly as it is."""
    return profile(
        [
            {
                "Container": _container(one),
                "Type": "Video",
                "VideoCodec": one.video_codec,
                "AudioCodec": one.audio_codec,
            }
        ]
    )


def _container(one: MediaFile) -> str:
    """The single name a profile lists this entry's container under.

    `mp4` rather than the six-name demuxer family, because that is what a client writes - and the
    containment rule splits both sides, which is what makes the two match (008 T4).
    """
    return "mp4" if "," in one.demuxers else one.demuxers


#: Rejects the container and nothing else, so a remux is attributable to that one rejection. The
#: target lists **two** codecs of each kind on purpose: `VideoCodec` reaches the URL as the whole
#: list even though the video is copied, and `AudioCodec` narrows to the one codec that was - and
#: a target naming a single codec could not tell those two rules apart.
REMUX_FROM_MP4 = profile(
    [{"Container": "mkv", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}],
    transcoding=[{**TS_HLS, "VideoCodec": "h264,hevc", "AudioCodec": "aac,mp3"}],
    codec_profiles=[
        {
            "Type": "Video",
            "Codec": "h264",
            "Conditions": [
                {"Condition": "LessThanEqual", "Property": "Height", "Value": "2160"},
                {"Condition": "LessThanEqual", "Property": "VideoFramerate", "Value": "60"},
            ],
        }
    ],
)

#: The same shape without the ceilings, for the cases that are about flags rather than numbers.
REMUXABLE = profile(
    [{"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "ac3"}],
    transcoding=[{**TS_HLS, "AudioCodec": "ac3"}],
)

#: Takes h264 and refuses hevc, which forces the one entry no browser profile accepts up to the
#: third rung. The audio codec is accepted, so the reasons name the video and nothing else.
REJECTS_HEVC = profile(
    [{"Container": "mkv", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "ac3"}]
)

#: Accepts the container and the video, refuses the audio - AC-7's shape.
REJECTS_AC3 = profile(
    [{"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}]
)

#: No container, no codec, no target: a client that can play nothing.
NOTHING_PLAYS = profile([], transcoding=[])


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
    """The real app over the real scan, committed so the routes' own sessions can see it.

    The override stashes a session id the way `require_user` itself does, because the `POST`
    reads the *caller's session* to find a stored device profile - an override that only handed
    back a user would make that fallback unreachable and its test vacuous.
    """
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
    built.dependency_overrides[require_user] = _as_viewer()
    yield built, world
    built.dependency_overrides.clear()
    built.state.db.dispose()


def _as_viewer(policy: dict[str, Any] | None = None) -> Any:
    """The dependency the override installs: a user, and the session that user is asking from."""

    def resolve(request: Request) -> User:
        request.state.session_id = SESSION_ID
        request.state.token_sha256 = None
        return User(
            id=VIEWER_ID,
            name="viewer",
            enable_all_folders=True,
            policy_extra=policy or {},
        )

    return resolve


@pytest.fixture
async def client(served: tuple[FastAPI, ScannedMediaWorld]) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=served[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


async def negotiate(
    client: httpx.AsyncClient, item_id: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    answered = await client.post(f"/Items/{item_id}/PlaybackInfo", json=body or {}, headers=HEADERS)
    assert answered.status_code == 200, answered.text
    return dict(answered.json())


def flags(document: dict[str, Any]) -> tuple[bool, bool, bool]:
    one = document["MediaSources"][0]
    return (
        one["SupportsDirectPlay"],
        one["SupportsDirectStream"],
        one["SupportsTranscoding"],
    )


async def _item(client: httpx.AsyncClient, item_id: str) -> dict[str, Any]:
    """What the item route says about the same file - the second statement of the same facts."""
    answered = await client.get(f"/Items/{item_id}", headers=HEADERS)
    assert answered.status_code == 200, answered.text
    return dict(answered.json())


def _store_capabilities(app: FastAPI, stated: dict[str, Any]) -> None:
    """What `POST /Sessions/Capabilities/Full` would have stored, stored the same way."""
    with app.state.sessions.begin() as opened:
        SessionRepository(opened).set_capabilities(SESSION_ID, {"DeviceProfile": stated})


# ------------------------------------------------------------------------------------------
# The profile classes - AC-1 through AC-6
# ------------------------------------------------------------------------------------------


async def test_ac1_no_profile_at_all_answers_direct_play(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """A client that has not described itself is not a client that permits nothing."""
    item = served[1].of(DIRECT_PLAY)
    document = await negotiate(client, item.id)

    assert flags(document) == (True, True, True)
    assert "TranscodingUrl" not in document["MediaSources"][0]
    assert "ErrorCode" not in document
    assert len(document["PlaySessionId"]) == 32


async def test_ac1_an_empty_profile_object_answers_the_opposite(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The half of rule 1 that had never been measured until 008 T4 posted it.

    `DeviceProfile: {}` is a profile whose lists are empty, which permits nothing - so it lands on
    the same refusal a nothing-plays profile does, and answering direct play here would hand a
    client bytes it said nothing about being able to open.
    """
    item = served[1].of(DIRECT_PLAY)
    document = await negotiate(client, item.id, {"DeviceProfile": {}})

    assert flags(document) == (False, False, False)
    assert "TranscodingUrl" not in document["MediaSources"][0]
    assert "ErrorCode" not in document, "a refusal by profile is flags, never a code (AC-5)"


async def test_ac2_a_profile_that_accepts_the_source_answers_direct_play(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    item = served[1].of(DIRECT_PLAY)
    document = await negotiate(client, item.id, {"DeviceProfile": accepting(DIRECT_PLAY)})

    assert flags(document) == (True, True, True)
    assert "TranscodingUrl" not in document["MediaSources"][0]
    assert "TranscodingContainer" not in document["MediaSources"][0], (
        "measured: a direct-play answer carries no transcoding container at all"
    )
    assert document["MediaSources"][0]["TranscodingSubProtocol"] == "http"


async def test_ac3_a_rejected_container_answers_a_url_with_both_streams_copied(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The remux, which on the wire is a `TranscodingUrl` like any other (spec section 3.3)."""
    item = served[1].of(REJECTED_CONTAINER)
    document = await negotiate(client, item.id, {"DeviceProfile": REMUXABLE})
    one = document["MediaSources"][0]

    assert flags(document) == (False, False, True)
    assert one["TranscodingContainer"] == "ts"
    assert one["TranscodingSubProtocol"] == "hls"
    assert "TranscodeReasons=ContainerNotSupported" in one["TranscodingUrl"]


async def test_ac4_a_rejected_codec_answers_a_url_and_not_an_error(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The codec no browser profile takes, against a profile that can still produce something."""
    item = served[1].of(REJECTED_VIDEO)
    document = await negotiate(client, item.id, {"DeviceProfile": REJECTS_HEVC})
    one = document["MediaSources"][0]

    assert flags(document) == (False, False, True)
    assert "TranscodeReasons=VideoCodecNotSupported" in one["TranscodingUrl"]
    assert "ErrorCode" not in document


async def test_ac5_a_profile_that_can_play_nothing_is_flags_and_no_error_code(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Never a `4xx`: what a client branches on is the flags, and a `4xx` reads as a transport
    failure."""
    item = served[1].of(DIRECT_PLAY)
    answered = await client.post(
        f"/Items/{item.id}/PlaybackInfo",
        json={"DeviceProfile": NOTHING_PLAYS},
        headers=HEADERS,
    )

    assert answered.status_code == 200
    document = dict(answered.json())
    assert flags(document) == (False, False, False)
    assert "TranscodingUrl" not in document["MediaSources"][0]
    assert "ErrorCode" not in document


async def test_ac6_supports_transcoding_is_about_the_profile_and_not_the_answer(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """One accepting profile, two answers, differing only in whether a target was declared.

    008 T4 measured this and it is why `Decision` carries the flag rather than deriving it: both
    of these are direct play, and only one of them can produce anything.
    """
    item = served[1].of(DIRECT_PLAY)
    with_target = await negotiate(client, item.id, {"DeviceProfile": accepting(DIRECT_PLAY)})
    without = await negotiate(
        client,
        item.id,
        {"DeviceProfile": profile(accepting(DIRECT_PLAY)["DirectPlayProfiles"], transcoding=[])},
    )

    assert flags(with_target) == (True, True, True)
    assert flags(without) == (True, True, False)


async def test_ac7_an_accepted_video_beside_a_rejected_audio_copies_the_video(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The negotiation half of AC-7: the URL says the video codec survives and the audio does not.

    `AudioCodec` narrows to the single codec chosen and `VideoCodec` stays the target's list, which
    is what tells a delivery route which stream to copy.
    """
    item = served[1].of(REJECTED_AUDIO)
    document = await negotiate(client, item.id, {"DeviceProfile": REJECTS_AC3})
    url = document["MediaSources"][0]["TranscodingUrl"]

    assert "&VideoCodec=h264&AudioCodec=aac&" in url
    assert "TranscodeReasons=AudioCodecNotSupported" in url


# ------------------------------------------------------------------------------------------
# The URL a client parses
# ------------------------------------------------------------------------------------------


async def test_the_transcoding_url_is_the_measured_anatomy_exactly(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """One string, compared whole. `[probe: tools/probe_transcode_decision.py, Jellyfin 10.11.11,
    2026-08-28]`, `[source: MediaBrowser.Model/Dlna/StreamInfo.cs ToUrl @ v10.11.11]`

    Whole rather than parameter by parameter, because everything that has ever been wrong about
    this URL was a spelling: the leading `?&`, a `BreakOnNonKeyFrames=True` four parameters above a
    lowercase `RequireAvc=false`, the source codec qualifying the condition triplet even where the
    target codec lists two, and `MaxHeight` carrying the profile's ceiling rather than the source's
    height.

    **The numbers come from the item's own streams**, not from literals: two ffmpeg builds encode
    the same declaration to slightly different bitrates and levels, and a golden that pinned this
    machine's would fail in CI for a reason that is not a difference in behaviour. What is pinned
    is the anatomy, and every number in it is cross-checked against the other route that states
    the same fact - which is exactly the comparison a client parsing this URL would make.
    """
    world = served[1]
    item = world.of(DIRECT_PLAY)
    streams = (await _item(client, item.id))["MediaStreams"]
    video = next(one for one in streams if one["Type"] == "Video")
    audio = next(one for one in streams if one["Type"] == "Audio")

    document = await negotiate(client, item.id, {"DeviceProfile": REMUX_FROM_MP4})
    one = document["MediaSources"][0]
    tag = media_etag(world.files.path_of(DIRECT_PLAY).stat().st_mtime_ns)

    assert one["ETag"] == tag
    assert " " in video["Profile"], (
        "the fixture stopped encoding a profile whose name has a space, which is the whole "
        "reason the reference strips spaces from these values rather than encoding them"
    )
    assert one["TranscodingUrl"] == (
        f"/videos/{dashed(item.id)}/master.m3u8?"
        f"&DeviceId={DEVICE_ID}"
        f"&MediaSourceId={one['Id']}"
        "&VideoCodec=h264,hevc"
        "&AudioCodec=aac"
        f"&AudioStreamIndex={audio['Index']}"
        f"&VideoBitrate={120_000_000 - audio['BitRate']}"
        f"&AudioBitrate={audio['BitRate']}"
        f"&AudioSampleRate={audio['SampleRate']}"
        f"&MaxFramerate={video['ReferenceFrameRate']}"
        "&MaxHeight=2160"
        "&SegmentContainer=ts"
        "&MinSegments=1"
        "&BreakOnNonKeyFrames=True"
        f"&PlaySessionId={document['PlaySessionId']}"
        f"&ApiKey={TOKEN}"
        "&RequireAvc=false"
        "&EnableAudioVbrEncoding=true"
        f"&Tag={tag}"
        f"&h264-level={video['Level']}"
        f"&h264-videobitdepth={video['BitDepth']}"
        f"&h264-profile={video['Profile'].replace(' ', '').lower()}"
        f"&h264-audiochannels={audio['Channels']}"
        "&TranscodeReasons=ContainerNotSupported"
    )


async def test_the_url_carries_the_profiles_ceiling_and_not_the_sources_height(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The asymmetry 008 T4 measured, asserted on its own so the golden above is not its only
    witness: a 240-line source under a 2160-line ceiling reaches the URL as `MaxHeight=2160`,
    while `MaxFramerate` - the one ceiling seeded from the stream - is the source's own rate and
    not the profile's 60."""
    item = served[1].of(DIRECT_PLAY)
    document = await negotiate(client, item.id, {"DeviceProfile": REMUX_FROM_MP4})
    url = document["MediaSources"][0]["TranscodingUrl"]

    assert DIRECT_PLAY.height == 240, "the entry that makes this discriminating changed"
    assert "&MaxHeight=2160" in url
    assert f"&MaxFramerate={DIRECT_PLAY.frame_rate}" in url
    assert "&MaxWidth=" not in url, "the profile stated no width ceiling, so there is none to send"


# ------------------------------------------------------------------------------------------
# The switches, which are not equals
# ------------------------------------------------------------------------------------------


async def test_enable_direct_play_false_flips_the_flag_and_produces_a_url(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The annotation is per request: the same source, the same profile, a different answer."""
    item = served[1].of(DIRECT_PLAY)
    document = await negotiate(
        client,
        item.id,
        {"DeviceProfile": accepting(DIRECT_PLAY), "EnableDirectPlay": False},
    )
    one = document["MediaSources"][0]

    assert flags(document) == (False, False, True)
    assert "TranscodeReasons=DirectPlayError" in one["TranscodingUrl"], (
        "a refusal with nothing to blame is that one reason, on an ordinary 200"
    )


async def test_enable_transcoding_false_changes_nothing(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured, and it is the switch clients most expect to work `[probe:
    tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28]`. The reference sets the flag
    false and then overwrites it, so the URL arrives anyway."""
    item = served[1].of(REJECTED_VIDEO)
    honoured = await negotiate(client, item.id, {"DeviceProfile": REJECTS_HEVC})
    ignored = await negotiate(
        client, item.id, {"DeviceProfile": REJECTS_HEVC, "EnableTranscoding": False}
    )

    assert flags(ignored) == flags(honoured) == (False, False, True)
    assert ignored["MediaSources"][0]["TranscodingUrl"]


# ------------------------------------------------------------------------------------------
# AC-31: the policy
# ------------------------------------------------------------------------------------------


async def test_ac31_one_denied_permission_negotiates_exactly_as_a_permitted_user(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    app, world = served
    item_id = world.of(REJECTED_VIDEO).id
    permitted = await negotiate(client, item_id, {"DeviceProfile": REJECTS_HEVC})

    app.dependency_overrides[require_user] = _as_viewer({VIDEO_TRANSCODING: False})
    denied = await negotiate(client, item_id, {"DeviceProfile": REJECTS_HEVC})

    assert flags(denied) == flags(permitted) == (False, False, True)
    assert denied["MediaSources"][0]["TranscodingUrl"]


async def test_ac31_all_three_denied_is_flags_down_and_no_error_code(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The one policy shape that moves anything, and even it is flags rather than an error."""
    app, world = served
    app.dependency_overrides[require_user] = _as_viewer(
        {VIDEO_TRANSCODING: False, AUDIO_TRANSCODING: False, REMUXING: False}
    )
    document = await negotiate(client, world.of(REJECTED_VIDEO).id, {"DeviceProfile": REJECTS_HEVC})

    assert flags(document) == (False, False, False)
    assert "TranscodingUrl" not in document["MediaSources"][0]
    assert "ErrorCode" not in document


# ------------------------------------------------------------------------------------------
# The GET variant, and the profile a device stored
# ------------------------------------------------------------------------------------------


async def test_the_get_variant_negotiates_nothing_and_still_issues_a_session(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    item = served[1].of(REJECTED_VIDEO)
    answered = await client.get(f"/Items/{item.id}/PlaybackInfo", headers=HEADERS)

    assert answered.status_code == 200
    document = dict(answered.json())
    assert flags(document) == (True, True, True)
    assert "TranscodingUrl" not in document["MediaSources"][0]
    assert len(document["PlaySessionId"]) == 32


async def test_a_post_with_no_profile_falls_back_to_the_devices_stored_one(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """ "No `DeviceProfile`" is not "no profile" `[probe: tools/probe_playback_info.py, Jellyfin
    10.11.11, 2026-08-29]`.

    The same bare request answers direct play before the capabilities are posted and a
    `TranscodingUrl` after, and the `GET` is unaffected - which is what makes the fallback the
    `POST`'s alone.
    """
    app, world = served
    item = world.of(REJECTED_CONTAINER)
    assert flags(await negotiate(client, item.id)) == (True, True, True)

    _store_capabilities(app, REMUXABLE)
    after = await negotiate(client, item.id)
    assert flags(after) == (False, False, True)
    assert after["MediaSources"][0]["TranscodingUrl"]

    answered = await client.get(f"/Items/{item.id}/PlaybackInfo", headers=HEADERS)
    assert flags(dict(answered.json())) == (True, True, True)


async def test_a_stored_profile_that_will_not_bind_is_treated_as_absent(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The capabilities route stores whatever arrives, unread, so this document has never been
    through the models a posted body goes through. A `500` here would leave a client unable to
    negotiate for ever because of one bad token it sent last week."""
    app, world = served
    _store_capabilities(app, {"DirectPlayProfiles": [{"Type": "Hologram"}]})

    assert flags(await negotiate(client, world.of(DIRECT_PLAY).id)) == (True, True, True)


# ------------------------------------------------------------------------------------------
# The refusals, as the probe battery measured them
# ------------------------------------------------------------------------------------------


async def test_an_unknown_item_is_the_same_404_as_the_item_route(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Problem details, and byte-identical to `GET /Items/{itemId}`'s own refusal apart from the
    trace `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`."""
    unknown = "a7c1f5e30b9d4a6c8e2f1b3d5a7c9e10"

    posted = await client.post(f"/Items/{unknown}/PlaybackInfo", json={}, headers=HEADERS)
    got = await client.get(f"/Items/{unknown}/PlaybackInfo", headers=HEADERS)
    item_route = await client.get(f"/Items/{unknown}", headers=HEADERS)

    for answered in (posted, got):
        assert answered.status_code == 404
        assert answered.headers["content-type"] == "application/json; charset=utf-8"
        body = dict(answered.json())
        assert {key: body[key] for key in ("type", "title", "status")} == {
            key: item_route.json()[key] for key in ("type", "title", "status")
        }


async def test_a_request_with_no_token_is_the_empty_401(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Decided before the route runs, which is why it has no body at all - not the problem-details
    shape the `404` above carries."""
    app, world = served
    app.dependency_overrides.clear()
    item = world.of(DIRECT_PLAY)

    for answered in (
        await client.post(f"/Items/{item.id}/PlaybackInfo", json={}),
        await client.get(f"/Items/{item.id}/PlaybackInfo"),
    ):
        assert answered.status_code == 401
        assert answered.content == b""
        assert "content-type" not in answered.headers


async def test_a_media_source_id_naming_nothing_is_the_one_error_code(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The empty source list, which is the reference's only assignment site for an `ErrorCode` -
    and it answers **no** `PlaySessionId`, because one is issued only where there is something to
    play `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`."""
    item = served[1].of(DIRECT_PLAY)
    document = await negotiate(client, item.id, {"MediaSourceId": "0" * 32})

    assert document == {"MediaSources": [], "ErrorCode": "NoCompatibleStream"}


async def test_a_post_with_no_body_at_all_is_answered(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`EmptyBodyBehavior.Allow` on the reference's own parameter, measured `[probe: manual
    requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-29]`. A required body would refuse a
    request the reference answers."""
    item = served[1].of(DIRECT_PLAY)
    answered = await client.post(f"/Items/{item.id}/PlaybackInfo", headers=HEADERS)

    assert answered.status_code == 200
    assert flags(dict(answered.json())) == (True, True, True)


async def test_an_unreadable_token_in_a_posted_profile_is_a_400(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The opposite of what an unknown *query* token does (behaviours section 1.12), and measured
    on this body `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-29]`."""
    item = served[1].of(DIRECT_PLAY)
    answered = await client.post(
        f"/Items/{item.id}/PlaybackInfo",
        json={
            "DeviceProfile": profile(
                [],
                codec_profiles=[
                    {
                        "Type": "Video",
                        "Codec": "h264",
                        "Conditions": [
                            {
                                "Condition": "LessThanEqual",
                                "Property": "NotAThing",
                                "Value": "1",
                            }
                        ],
                    }
                ],
            )
        },
        headers=HEADERS,
    )

    assert answered.status_code == 400
    assert answered.json()["title"] == "One or more validation errors occurred."


async def test_a_photo_entry_in_a_profile_is_dropped_rather_than_refused(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """A real client's profile lists media this negotiation is not about, and the reference binds
    it happily. Refusing here would be a `400` on every request such a client makes."""
    item = served[1].of(DIRECT_PLAY)
    with_photos = accepting(DIRECT_PLAY)
    with_photos["DirectPlayProfiles"].append({"Container": "jpeg", "Type": "Photo"})

    document = await negotiate(client, item.id, {"DeviceProfile": with_photos})

    assert flags(document) == (True, True, True)
