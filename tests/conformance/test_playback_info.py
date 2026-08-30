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
    BOTH_SUBTITLE_KINDS,
    DIRECT_PLAY,
    REJECTED_AUDIO,
    REJECTED_CONTAINER,
    REJECTED_VIDEO,
    UNCONVERTIBLE_SUBTITLE,
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

    **Matroska is the second family with a comma in it**, and it arrived with 011's subtitled
    entries. `mkv` rather than `matroska` and rather than `mp4`, because inspection *renames* that
    family down to one name where it leaves the mp4 one six long (008 spec section 3.1) - so the
    stored container is `mkv` and a profile naming anything else refuses it, which would make
    every subtitle answer below attributable to a container rejection instead of to the rule
    under test.
    """
    if one.demuxers.startswith("matroska"):
        return "mkv"
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


# ------------------------------------------------------------------------------------------
# The subtitle half - 011 AC-1, AC-2, AC-3, AC-15
# ------------------------------------------------------------------------------------------
#
# `tests/unit/test_media_decision.py` owns the ladder. What is proven here is the wiring: that
# `SubtitleProfiles` reaches it, that the posted index is read on the reference's own condition,
# and that the answers reach the wire under the reference's own property names.

#: What a client that will fetch subtitle files for itself declares.
EXTERNAL_VTT = {"Format": "vtt", "Method": "External"}
#: What a client that wants them announced in the manifest declares.
MANIFEST_VTT = {"Format": "vtt", "Method": "Hls"}


def takes_subtitles(one: MediaFile, *subtitles: dict[str, Any]) -> dict[str, Any]:
    """A profile that direct-plays this file and declares these subtitle entries."""
    document = accepting(one)
    document["SubtitleProfiles"] = list(subtitles)
    return document


def refuses_container(one: MediaFile, *subtitles: dict[str, Any]) -> dict[str, Any]:
    """The same, with the container rejected - so the answer is a transcode over the same file."""
    document = profile([{"Container": "nothingatall", "Type": "Video"}])
    document["SubtitleProfiles"] = list(subtitles)
    return document


def subtitle_streams(document: dict[str, Any]) -> list[dict[str, Any]]:
    source = document["MediaSources"][0]
    return [one for one in source["MediaStreams"] if one["Type"] == "Subtitle"]


async def test_ac1_a_negotiated_source_states_a_delivery_method_on_every_subtitle_stream(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Every stream, not the selected one - measured on a source with six of them.

    The image track is what makes this discriminating: under a text-only profile it is the row
    that has to answer `Encode`, and a ladder that only ever answered for the chosen track would
    pass a narrower test.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    document = await negotiate(
        client, item.id, {"DeviceProfile": takes_subtitles(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)}
    )

    answered = {one["Index"]: one["DeliveryMethod"] for one in subtitle_streams(document)}
    kinds = {one["Index"]: one["IsTextSubtitleStream"] for one in subtitle_streams(document)}
    assert len(answered) == 2, "the entry carries one text track and one image track"
    text = next(index for index, is_text in kinds.items() if is_text)
    image = next(index for index, is_text in kinds.items() if not is_text)
    assert answered[text] == "External"
    assert answered[image] == "Encode"


async def test_ac3_a_profile_that_declares_no_subtitle_handling_answers_encode_on_every_track(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Burn-in is the answer the reference gives, not a branch it avoids (spec section 3.3)."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    document = await negotiate(
        client, item.id, {"DeviceProfile": takes_subtitles(BOTH_SUBTITLE_KINDS)}
    )

    assert flags(document) == (True, True, True), "declaring nothing about subtitles costs nothing"
    assert {one["DeliveryMethod"] for one in subtitle_streams(document)} == {"Encode"}


async def test_ac3_the_unconvertible_format_reaches_encode_under_a_vtt_only_profile(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`ass` is text, is servable alone, and still cannot be converted *from* - so it is the row
    that makes `Encode` reachable for a text track with no image stream involved."""
    item = served[1].of(UNCONVERTIBLE_SUBTITLE)
    document = await negotiate(
        client, item.id, {"DeviceProfile": takes_subtitles(UNCONVERTIBLE_SUBTITLE, EXTERNAL_VTT)}
    )

    embedded = next(one for one in subtitle_streams(document) if not one["IsExternal"])
    sidecar = next(one for one in subtitle_streams(document) if one["IsExternal"])
    assert embedded["Codec"] == "ass"
    assert embedded["DeliveryMethod"] == "Encode"
    assert sidecar["DeliveryMethod"] == "External", (
        "the sidecar beside it is convertible to vtt, so the two are the discriminating pair"
    )


async def test_ac1_a_bare_read_states_neither_the_method_nor_the_address(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The two negotiated properties are absent from every read that negotiated nothing - the
    item route and the profile-less `GET` alike (spec section 3.2)."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    bare = (await _item(client, item.id))["MediaSources"][0]["MediaStreams"]
    for one in (stream for stream in bare if stream["Type"] == "Subtitle"):
        assert "DeliveryMethod" not in one
        assert "DeliveryUrl" not in one
        assert one["IsTextSubtitleStream"] in (True, False), "the file facts are stated anyway"

    answered = await client.get(f"/Items/{item.id}/PlaybackInfo", headers=HEADERS)
    assert answered.status_code == 200
    for one in subtitle_streams(dict(answered.json())):
        assert "DeliveryMethod" not in one


async def test_ac1_the_delivery_address_is_written_for_the_external_streams_alone(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`DeliveryUrl` names `GetSubtitleWithTicks` - the route with the start position in the path,
    which is why that route is in the surface at all (spec section 2)."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    document = await negotiate(
        client, item.id, {"DeviceProfile": takes_subtitles(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)}
    )
    source = document["MediaSources"][0]
    external = [one for one in subtitle_streams(document) if one["DeliveryMethod"] == "External"]
    burned = [one for one in subtitle_streams(document) if one["DeliveryMethod"] == "Encode"]

    assert len(external) == 1
    assert external[0]["DeliveryUrl"] == (
        f"/Videos/{dashed(item.id)}/{source['Id']}"
        f"/Subtitles/{external[0]['Index']}/0/Stream.vtt?ApiKey={TOKEN}"
    )
    assert external[0]["IsExternalUrl"] is False
    assert all("DeliveryUrl" not in one for one in burned)


async def test_ac2_an_index_is_read_only_where_the_body_also_names_the_source(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The measurement that settles the third-party lead spec section 3.3 was built on: without
    the media source id the index is dropped in **silence**, and the answer is the default - which
    for this server is no default at all."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    named = await negotiate(
        client,
        item.id,
        {"DeviceProfile": takes_subtitles(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)},
    )
    text = next(one["Index"] for one in subtitle_streams(named) if one["IsTextSubtitleStream"])
    source_id = named["MediaSources"][0]["Id"]

    body = {"DeviceProfile": takes_subtitles(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)}
    with_source = await negotiate(
        client, item.id, {**body, "SubtitleStreamIndex": text, "MediaSourceId": source_id}
    )
    without_source = await negotiate(client, item.id, {**body, "SubtitleStreamIndex": text})
    neither = await negotiate(client, item.id, body)

    assert with_source["MediaSources"][0]["DefaultSubtitleStreamIndex"] == text
    assert "DefaultSubtitleStreamIndex" not in without_source["MediaSources"][0]
    assert "DefaultSubtitleStreamIndex" not in neither["MediaSources"][0], (
        "no per-user subtitle preference means no default track (AC-2, OQ-12)"
    )


async def test_ac2_an_index_naming_no_stream_is_restated_rather_than_refused(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    source_id = (await _item(client, item.id))["MediaSources"][0]["Id"]
    for named in (-1, 99):
        document = await negotiate(
            client,
            item.id,
            {
                "DeviceProfile": takes_subtitles(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT),
                "SubtitleStreamIndex": named,
                "MediaSourceId": source_id,
            },
        )
        assert document["MediaSources"][0]["DefaultSubtitleStreamIndex"] == named
        assert flags(document) == (True, True, True), (
            "an index naming no stream resolves no method, so it refuses no direct play"
        )


async def test_naming_a_track_the_profile_cannot_take_costs_the_source_its_direct_play(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The finding neither 011 document had, at the HTTP boundary.

    The same file and the same direct-play entry: naming the text track under an external `vtt`
    profile keeps direct play, and naming the image track loses it with `SubtitleCodecNotSupported`
    `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    body = {"DeviceProfile": takes_subtitles(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)}
    listed = await negotiate(client, item.id, body)
    source_id = listed["MediaSources"][0]["Id"]
    text = next(one["Index"] for one in subtitle_streams(listed) if one["IsTextSubtitleStream"])
    image = next(
        one["Index"] for one in subtitle_streams(listed) if not one["IsTextSubtitleStream"]
    )

    kept = await negotiate(
        client, item.id, {**body, "SubtitleStreamIndex": text, "MediaSourceId": source_id}
    )
    lost = await negotiate(
        client, item.id, {**body, "SubtitleStreamIndex": image, "MediaSourceId": source_id}
    )

    assert flags(kept) == (True, True, True)
    assert flags(lost) == (False, False, True)
    assert "TranscodeReasons=SubtitleCodecNotSupported" in lost["MediaSources"][0]["TranscodingUrl"]


async def test_the_address_carries_the_index_and_the_method_at_their_measured_positions(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`SubtitleStreamIndex` straight after `AudioStreamIndex`, `SubtitleMethod` straight after
    `Tag` - asserted as substrings of the whole address, whose anatomy is pinned as one string by
    `test_the_transcoding_url_is_the_measured_anatomy_exactly`."""
    world = served[1]
    item = world.of(BOTH_SUBTITLE_KINDS)
    listed = await negotiate(
        client, item.id, {"DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, MANIFEST_VTT)}
    )
    source_id = listed["MediaSources"][0]["Id"]
    text = next(one["Index"] for one in subtitle_streams(listed) if one["IsTextSubtitleStream"])

    document = await negotiate(
        client,
        item.id,
        {
            "DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, MANIFEST_VTT),
            "SubtitleStreamIndex": text,
            "MediaSourceId": source_id,
        },
    )
    url = document["MediaSources"][0]["TranscodingUrl"]
    tag = media_etag(world.files.path_of(BOTH_SUBTITLE_KINDS).stat().st_mtime_ns)

    audio = next(
        one for one in document["MediaSources"][0]["MediaStreams"] if one["Type"] == "Audio"
    )
    assert f"&AudioStreamIndex={audio['Index']}&SubtitleStreamIndex={text}&" in url
    assert f"&Tag={tag}&SubtitleMethod=Hls&" in url
    assert "&EnableSubtitlesInManifest=" not in url, "the profile did not declare the flag"


async def test_the_external_method_drops_the_index_from_the_address(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """A client that fetches the track itself was already handed its address, so the parameter is
    not repeated - and `SubtitleMethod` is dropped with it. Both conditions read the *resolved*
    method rather than the declared one."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    listed = await negotiate(
        client, item.id, {"DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)}
    )
    source_id = listed["MediaSources"][0]["Id"]
    text = next(one["Index"] for one in subtitle_streams(listed) if one["IsTextSubtitleStream"])

    document = await negotiate(
        client,
        item.id,
        {
            "DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT),
            "SubtitleStreamIndex": text,
            "MediaSourceId": source_id,
        },
    )
    url = document["MediaSources"][0]["TranscodingUrl"]
    assert "&SubtitleStreamIndex=" not in url
    assert "&SubtitleMethod=" not in url


async def test_an_index_of_minus_one_is_dropped_from_the_address_where_a_missing_one_is_not(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-2's second subtraction, and the pair that makes it a claim rather than a coincidence.

    `-1` names no track at all, so the address does not repeat it back `[source:
    MediaBrowser.Model/Dlna/StreamInfo.cs:960-963 @ v10.11.11]`, `[probe:
    tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`. An index naming a stream
    the source has not got is **not** the same case: it still selects, so `99` is written. A rule
    written as "drop an index that matches no stream" would answer the same thing for both and be
    wrong on the second - which is why the two are asked in one test.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    listed = await negotiate(
        client, item.id, {"DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, MANIFEST_VTT)}
    )
    source_id = listed["MediaSources"][0]["Id"]

    async def address_for(index: int) -> str:
        document = await negotiate(
            client,
            item.id,
            {
                "DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, MANIFEST_VTT),
                "SubtitleStreamIndex": index,
                "MediaSourceId": source_id,
            },
        )
        url: str = document["MediaSources"][0]["TranscodingUrl"]
        return url

    assert "&SubtitleStreamIndex=" not in await address_for(-1)
    assert "&SubtitleStreamIndex=99&" in await address_for(99)


async def test_always_burn_in_keeps_the_index_and_appends_its_own_flag(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The disjunct 011 plan section 6.3 left out, and the parameter that comes with it.

    The flag is appended **after** `TranscodeReasons`, in a lower camel case nothing else in this
    address uses, because the reference appends it once the address is already built
    `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    listed = await negotiate(
        client, item.id, {"DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)}
    )
    source_id = listed["MediaSources"][0]["Id"]
    text = next(one["Index"] for one in subtitle_streams(listed) if one["IsTextSubtitleStream"])

    document = await negotiate(
        client,
        item.id,
        {
            "DeviceProfile": refuses_container(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT),
            "SubtitleStreamIndex": text,
            "MediaSourceId": source_id,
            "AlwaysBurnInSubtitleWhenTranscoding": True,
        },
    )
    url = document["MediaSources"][0]["TranscodingUrl"]
    assert f"&SubtitleStreamIndex={text}&" in url
    assert "&SubtitleMethod=" not in url, "the disjunct is on the index alone, not on the method"
    assert url.endswith("&alwaysBurnInSubtitleWhenTranscoding=true")


async def test_the_manifest_flag_reaches_the_address_and_nothing_else(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """OQ-1's answer, written down as an address: the reference's own negotiation writes the flag
    and the route it addresses cannot read it (spec section 3.4)."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    declaring = refuses_container(BOTH_SUBTITLE_KINDS, MANIFEST_VTT)
    declaring["TranscodingProfiles"] = [{**TS_HLS, "EnableSubtitlesInManifest": True}]

    document = await negotiate(client, item.id, {"DeviceProfile": declaring})
    url = document["MediaSources"][0]["TranscodingUrl"]
    assert "&EnableSubtitlesInManifest=True&RequireAvc=false&" in url, (
        "written as .NET spells a boolean, between TranscodingMaxAudioChannels and RequireAvc"
    )


async def test_a_progressive_transcode_carries_the_seek_into_the_subtitle_address(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Plan section 6.3 said the start position is zero for every request this feature can
    produce. It is zero for every HLS answer, which forces it so - and it is the negotiation's own
    seek on a progressive one `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11,
    2026-08-30]`."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    progressive = refuses_container(BOTH_SUBTITLE_KINDS, EXTERNAL_VTT)
    progressive["TranscodingProfiles"] = [
        {
            "Container": "mp4",
            "Type": "Video",
            "VideoCodec": "h264",
            "AudioCodec": "aac",
            "Protocol": "http",
            "Context": "Streaming",
        }
    ]

    document = await negotiate(
        client, item.id, {"DeviceProfile": progressive, "StartTimeTicks": 6_000_000_000}
    )
    external = [one for one in subtitle_streams(document) if one["DeliveryMethod"] == "External"]
    assert external, "the text track resolves to External on this profile"
    assert "/Subtitles/" in external[0]["DeliveryUrl"]
    assert "/6000000000/Stream.vtt" in external[0]["DeliveryUrl"]


async def test_a_declared_method_binds_in_any_case_and_by_ordinal(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """011 plan section 6.8's owed row, paid.

    `hls`, `HLS` and the ordinal `3` all answer what `Hls` answers, on a request **body** - the
    same four classes 012's gate found for an enum-typed query parameter. A strictly-cased enum
    here would refuse a body the reference accepts `[probe:
    tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
    """
    item = served[1].of(BOTH_SUBTITLE_KINDS)

    async def resolved(method: Any) -> dict[int, str]:
        document = await negotiate(
            client,
            item.id,
            {
                "DeviceProfile": refuses_container(
                    BOTH_SUBTITLE_KINDS, {"Format": "vtt", "Method": method}
                )
            },
        )
        return {one["Index"]: one["DeliveryMethod"] for one in subtitle_streams(document)}

    declared = await resolved("Hls")
    assert "Hls" in declared.values(), "the control row"
    assert await resolved("hls") == declared
    assert await resolved("HLS") == declared
    assert await resolved(3) == declared
    assert await resolved("ExTeRnAl") != declared


async def test_a_method_that_is_no_member_at_all_is_the_validation_400(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The half of the same measurement that is a refusal rather than a leniency: an unreadable
    token inside a body is a `400` here as it is for every other enum this body carries."""
    item = served[1].of(BOTH_SUBTITLE_KINDS)
    answered = await client.post(
        f"/Items/{item.id}/PlaybackInfo",
        json={
            "DeviceProfile": refuses_container(
                BOTH_SUBTITLE_KINDS, {"Format": "vtt", "Method": "banana"}
            )
        },
        headers=HEADERS,
    )
    assert answered.status_code == 400
    assert answered.json()["title"] == "One or more validation errors occurred."


async def test_ac15_a_direct_played_file_answers_what_it_answered_before(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-15: nothing this feature adds changes a direct play - and the entry it is asserted on
    has no subtitle stream at all, so the properties AC-1 and AC-3 add have nowhere to appear."""
    item = served[1].of(DIRECT_PLAY)
    document = await negotiate(client, item.id, {"DeviceProfile": accepting(DIRECT_PLAY)})
    source = document["MediaSources"][0]

    assert flags(document) == (True, True, True)
    assert "TranscodingUrl" not in source
    assert "DefaultSubtitleStreamIndex" not in source
    assert not [one for one in source["MediaStreams"] if one["Type"] == "Subtitle"]
