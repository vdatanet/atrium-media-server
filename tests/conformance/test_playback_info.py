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

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
from fastapi import FastAPI, Request

from atrium.api.deps import require_user
from atrium.api.media_info import PlaybackInfoDto
from atrium.compat.model import AtriumModel
from atrium.config.paths import DataPaths
from atrium.db.repositories import SessionRepository, UserRepository
from atrium.domain.items import ItemType
from atrium.domain.session import Session
from atrium.domain.user import User
from atrium.library import inspection
from atrium.media.info import media_etag
from atrium.media.urls import dashed
from atrium.server import create_app
from atrium.users.policy import AUDIO_TRANSCODING, REMUXING, VIDEO_TRANSCODING
from tests.conformance.test_golden import STATE
from tests.fixtures.media import (
    BOTH_SUBTITLE_KINDS,
    DIRECT_PLAY,
    HIGH_RATE_AUDIO,
    LATENT,
    MISSING_HALF_FIRST,
    MISSING_HALF_SECOND,
    REJECTED_AUDIO,
    REJECTED_CONTAINER,
    REJECTED_VIDEO,
    SOUNDLESS,
    UNCONVERTIBLE_SUBTITLE,
    UNREADABLE,
    VIDEOLESS,
    BuiltMedia,
    MediaFile,
    UninspectableFile,
)
from tests.fixtures.media_world import ScannedMediaWorld, build_scanned_media_world

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

#: Plays an mp4 of h264 and aac, and offers the HLS target every profile here offers. What it is
#: for is 012 AC-1: a source **nothing ever opened** matches no direct-play entry - its inspection
#: carries no container and no codec at all - so the answer is a refusal on the first rung and a
#: produced stream on the third, which is what the reference answers for a file it could not read
#: `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-08-29]`.
PLAYS_NEITHER = profile(
    [{"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "aac"}]
)


# ------------------------------------------------------------------------------------------
# The world, served
# ------------------------------------------------------------------------------------------


@pytest.fixture
def media_paths(tmp_path: Path) -> DataPaths:
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.state_file.write_text(json.dumps(STATE, indent=1), encoding="utf-8")
    return paths


def _serve(
    media_paths: DataPaths, files: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    """The real app over the real scan, committed so the routes' own sessions can see it.

    The override stashes a session id the way `require_user` itself does, because the `POST`
    reads the *caller's session* to find a stored device profile - an override that only handed
    back a user would make that fallback unreachable and its test vacuous.
    """
    built = create_app(media_paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_scanned_media_world(opened, files)
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


@pytest.fixture
def served(
    media_paths: DataPaths, media_files: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    yield from _serve(media_paths, media_files)


@pytest.fixture
def writable_files(media_files: BuiltMedia, tmp_path: Path) -> BuiltMedia:
    """A copy of the generated tree a test may write to. The cached one never is.

    012's healing cases replace `latent.mkv` with a real film **after** the scan, which is the
    only way to reach a source whose bytes nothing has ever successfully opened and that a
    negotiation then can - so they cannot share the session-scoped tree every other test reads.
    """
    return media_files.copy_into(tmp_path / "writable-tree")


@pytest.fixture
def healable(
    media_paths: DataPaths, writable_files: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    """The same app and the same scan, over the tree a test may change underneath the server."""
    yield from _serve(media_paths, writable_files)


@pytest.fixture
async def healable_client(
    healable: tuple[FastAPI, ScannedMediaWorld],
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=healable[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


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


def _real_bytes_over(files: BuiltMedia, target: UninspectableFile, source: MediaFile) -> None:
    """Replace a file the scan could not open with one it would have, keeping its name.

    `latent.mkv`'s whole purpose: after the scan, the only thing that will ever have read these
    bytes successfully is the negotiation (012 AC-2, AC-3). The replacement is a matroska film, so
    the extension the empty annotation answered and the container the inspection stores agree -
    and the only thing that moves between the two answers is what opening the file learned.
    """
    files.path_of(target).write_bytes(files.path_of(source).read_bytes())


def _comparable(document: dict[str, Any]) -> str:
    """One negotiation's answer with its session identifier normalised out, for comparing two.

    A `PlaySessionId` is fresh per request and is copied into every address inside the body, so
    two answers always differ textually - which would make "the second opinion is different" a
    test that passes on a server that ignored the switches entirely.
    """
    rendered = json.dumps(document, sort_keys=True)
    return rendered.replace(document["PlaySessionId"], "<play-session>")


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


# The profile-absent half of AC-31, and it is the opposite rule. The two rows above hold against
# a `DeviceProfile`; a negotiation carrying none reaches no ladder answer to gate, so the flags
# stay the ones the account's own permissions put on the source - one permission per media kind
# `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-02]`. Found by
# `tools/differential.py --named delivery-time-policy-refusal` on 2026-09-02, which negotiates
# with an empty body: Atrium answered `SupportsTranscoding: true` where the reference answered
# `false`, on a seat with all three denied. Delete either gate and one of these fails.

_UNNEGOTIATED: list[tuple[str, dict[str, bool], tuple[bool, bool, bool]]] = [
    ("every permission granted", {}, (True, True, True)),
    ("video transcoding denied alone", {VIDEO_TRANSCODING: False}, (True, True, False)),
    ("audio transcoding denied alone", {AUDIO_TRANSCODING: False}, (True, True, True)),
    ("remuxing denied alone", {REMUXING: False}, (True, False, True)),
    (
        "all three denied",
        {VIDEO_TRANSCODING: False, AUDIO_TRANSCODING: False, REMUXING: False},
        (True, False, False),
    ),
]


@pytest.mark.parametrize(
    "policy,expected",
    [row[1:] for row in _UNNEGOTIATED],
    ids=[row[0] for row in _UNNEGOTIATED],
)
async def test_ac31_a_video_negotiated_against_no_profile_reads_one_permission_per_flag(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    policy: dict[str, bool],
    expected: tuple[bool, bool, bool],
) -> None:
    """A single denial **is** observable here, which is what the all-three gate hides one profile
    away: `SupportsTranscoding` follows `EnableVideoPlaybackTranscoding` and
    `SupportsDirectStream` follows `EnablePlaybackRemuxing`."""
    app, world = served
    app.dependency_overrides[require_user] = _as_viewer(policy)
    item_id = world.of(REJECTED_VIDEO).id

    assert flags(await negotiate(client, item_id)) == expected
    answered = await client.get(f"/Items/{item_id}/PlaybackInfo", headers=HEADERS)
    assert answered.status_code == 200
    assert flags(dict(answered.json())) == expected, "the GET carries no profile either"


async def test_ac31_a_denied_video_permission_moves_nothing_on_an_audio_item(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The per-kind half. An audio item reads the audio permission and no other, and its
    `SupportsDirectStream` is untouched by any of the three - measured on the same run."""
    app, world = served
    item_id = world.of(HIGH_RATE_AUDIO).id

    app.dependency_overrides[require_user] = _as_viewer({VIDEO_TRANSCODING: False, REMUXING: False})
    assert flags(await negotiate(client, item_id)) == (True, True, True)

    app.dependency_overrides[require_user] = _as_viewer({AUDIO_TRANSCODING: False})
    assert flags(await negotiate(client, item_id)) == (True, True, False)


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
# The vocabularies this body carries - 012 AC-8, spec section 3.3, behaviours section 2.28
# ------------------------------------------------------------------------------------------
#
# One binder on `compat/model.py` reads all five, because the reference reads them through one
# converter registered for its whole pipeline (012 T7). Every row below was measured on the
# reference one property at a time, and every one of them is read off `SupportsDirectPlay`
# alone - the answer echoes none of these values back, so what a value bound to is only visible
# in what it *did* `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-04]`.


def _narrow_video(one: MediaFile, **overrides: Any) -> dict[str, Any]:
    """A profile that direct-plays this file, with a codec profile whose condition cannot hold.

    Width at most one pixel: false of anything a camera or an encoder ever produced. So the
    control answers direct play and this answers none, and every row between them says whether
    the value it carried bound.
    """
    stated: dict[str, Any] = {
        "Condition": "LessThanEqual",
        "Property": "Width",
        "Value": "1",
        "IsRequired": True,
    }
    stated.update(overrides)
    document = accepting(one)
    document["CodecProfiles"] = [
        {"Type": "Video", "Codec": one.video_codec, "Conditions": [stated]}
    ]
    return document


async def _direct_plays(client: httpx.AsyncClient, item_id: str, profile: dict[str, Any]) -> bool:
    document = await negotiate(client, item_id, {"DeviceProfile": profile})
    return bool(flags(document)[0])


async def _refused(client: httpx.AsyncClient, item_id: str, profile: dict[str, Any]) -> int:
    answered = await client.post(
        f"/Items/{item_id}/PlaybackInfo", json={"DeviceProfile": profile}, headers=HEADERS
    )
    return answered.status_code


async def test_the_two_controls_the_vocabulary_rows_are_read_against(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Written first because every row below is one of these two answers, or it proves nothing."""
    item = served[1].of(DIRECT_PLAY)
    assert await _direct_plays(client, item.id, accepting(DIRECT_PLAY)) is True
    assert await _direct_plays(client, item.id, _narrow_video(DIRECT_PLAY)) is False


async def test_a_direct_play_entry_binds_its_type_in_any_case_and_by_ordinal(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`DlnaProfileType`, one of the four OQ-4 widened the leniency to.

    `video` was measured binding on 2026-08-30 and the ordinals on 2026-09-04: `1` is `Video`
    and direct-plays, `0` is `Audio` and does not - which is what says the number selected a
    member rather than being ignored.
    """
    item = served[1].of(DIRECT_PLAY)

    async def with_type(value: Any) -> bool:
        document = accepting(DIRECT_PLAY)
        document["DirectPlayProfiles"][0]["Type"] = value
        return await _direct_plays(client, item.id, document)

    for bound in ("video", "VIDEO", 1, "1", "+1", " 1 "):
        assert await with_type(bound) is True, f"{bound!r} names the profile's video entry"
    assert await with_type(0) is False, "the ordinal zero is Audio, and this item is a film"


async def test_a_codec_profile_binds_its_type_by_the_number_the_reference_declares(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The row that would have gone wrong silently, and the reason ordinals are declared here.

    `CodecType` declares `Video = 0, VideoAudio = 1, Audio = 2` - audio **last** - where this
    project's own enumeration declares it first `[source: MediaBrowser.Model/Dlna/CodecType.cs @
    v10.11.11]`. A binder counting members would answer `0` with `Audio`, leaving the video
    condition unapplied and the source direct-playing: the opposite of the measured answer, on a
    request that carried nothing wrong.
    """
    item = served[1].of(DIRECT_PLAY)

    async def with_type(value: Any) -> bool:
        document = _narrow_video(DIRECT_PLAY)
        document["CodecProfiles"][0]["Type"] = value
        return await _direct_plays(client, item.id, document)

    assert await with_type("video") is False, "an altered case applies the profile"
    assert await with_type(0) is False, "zero is Video there, so the condition is applied"
    assert await with_type(2) is True, "two is Audio there, so nothing constrains the video"


async def test_a_condition_binds_its_comparison_and_its_subject_by_ordinal(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`ProfileConditionType` and `ProfileConditionValue`, the other two of the four.

    `NumStreams` is the discriminating subject: the reference's enumeration **skips 15**, so it
    declares 25 where counting its members gives 24 `[source:
    MediaBrowser.Model/Dlna/ProfileConditionValue.cs @ v10.11.11]`. Measured, `25` constrains and
    `15` binds to nothing at all.
    """
    item = served[1].of(DIRECT_PLAY)

    async def with_condition(**overrides: Any) -> bool:
        return await _direct_plays(client, item.id, _narrow_video(DIRECT_PLAY, **overrides))

    assert await with_condition(Condition="lessthanequal") is False
    assert await with_condition(Condition=2) is False, "two is LessThanEqual"
    assert await with_condition(Condition=1) is True, "one is NotEquals, which this width is"
    assert await with_condition(Property="width") is False
    assert await with_condition(Property=3) is False, "three is Width"
    assert await with_condition(Property=25, Value="0") is False, "twenty-five is NumStreams"


async def test_a_word_no_member_has_refuses_on_every_vocabulary_this_body_carries(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The leniency is names and numbers, not values: an unbindable word is still the `400`.

    All five vocabularies this body binds, the subtitle entry's `Method` included - it is the one
    the private binder used to answer, and asking it here is what says the deletion did not take
    the refusal with it. The opposite of what an unknown **query** token does (behaviours
    section 1.12).
    """
    item = served[1].of(DIRECT_PLAY)
    entry_typed = accepting(DIRECT_PLAY)
    entry_typed["DirectPlayProfiles"][0]["Type"] = "dash"
    codec_typed = _narrow_video(DIRECT_PLAY)
    codec_typed["CodecProfiles"][0]["Type"] = "dash"

    subtitled = accepting(DIRECT_PLAY)
    subtitled["SubtitleProfiles"] = [{"Format": "vtt", "Method": "dash"}]

    for document in (
        entry_typed,
        codec_typed,
        _narrow_video(DIRECT_PLAY, Condition="dash"),
        _narrow_video(DIRECT_PLAY, Property="dash"),
        subtitled,
    ):
        assert await _refused(client, item.id, document) == 400


async def test_an_empty_string_refuses_on_every_vocabulary_that_declares_no_default(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The row that proves the binder's fourth class is **not** general.

    Measured at T1 on the two the plan named - a codec profile's `Type` and a direct-play entry's
    `Type` are each a `400` where the delivery protocol's empty string is a `200` taking `http`,
    because only `MediaStreamProtocol` carries `[DefaultValue]`
    `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`. A binder that
    generalised the default clause would answer `200` here on five properties the reference
    refuses.
    """
    item = served[1].of(DIRECT_PLAY)
    entry_typed = accepting(DIRECT_PLAY)
    entry_typed["DirectPlayProfiles"][0]["Type"] = ""
    codec_typed = _narrow_video(DIRECT_PLAY)
    codec_typed["CodecProfiles"][0]["Type"] = ""
    subtitled = accepting(DIRECT_PLAY)
    subtitled["SubtitleProfiles"] = [{"Format": "vtt", "Method": ""}]

    for document in (
        entry_typed,
        codec_typed,
        _narrow_video(DIRECT_PLAY, Condition=""),
        _narrow_video(DIRECT_PLAY, Property=""),
        subtitled,
    ):
        assert await _refused(client, item.id, document) == 400


async def test_a_boolean_is_not_the_ordinal_one(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """`isinstance(True, int)` at the HTTP boundary: `true` is a measured `400` and `1` is a
    measured member, and a binder that folded the two would direct-play a body the reference
    refuses `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`."""
    item = served[1].of(DIRECT_PLAY)
    document = accepting(DIRECT_PLAY)
    document["DirectPlayProfiles"][0]["Type"] = True

    assert await _refused(client, item.id, document) == 400


async def test_an_ordinal_no_member_has_is_the_400_behaviours_326_records(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """**Not a criterion: a boundary, named so it cannot be rediscovered as a surprise.**

    The reference answers a number no member carries three ways - the entry is ignored on
    `DlnaProfileType` and `CodecType`, the condition is *satisfied* on `ProfileConditionValue`,
    and `ProfileConditionType` is a **`500`** `[probe: tools/probe_playback_info.py, Jellyfin
    10.11.11, 2026-09-04]`. This server answers `400` to all four, which
    [behaviours section 3.26](../../docs/compatibility/behaviours.md) records as a third
    behaviour rather than a decision: it predates 012 (a field typed as an enumeration has always
    refused a number no member has) and T7's binder does not move it, because the binder keeps the
    raw number and the field is what refuses.
    """
    item = served[1].of(DIRECT_PLAY)
    entry_typed = accepting(DIRECT_PLAY)
    entry_typed["DirectPlayProfiles"][0]["Type"] = 9
    codec_typed = _narrow_video(DIRECT_PLAY)
    codec_typed["CodecProfiles"][0]["Type"] = 9

    for document in (
        entry_typed,
        codec_typed,
        _narrow_video(DIRECT_PLAY, Condition=9),
        _narrow_video(DIRECT_PLAY, Property=15),
    ):
        assert await _refused(client, item.id, document) == 400


# ------------------------------------------------------------------------------------------
# What a nested refusal is keyed by - 012 AC-8, spec section 3.4, plan section 6.6
# ------------------------------------------------------------------------------------------
#
# One vocabulary failure, two shapes, and the route decides which. `POST /Playlists` keys a
# top-level property `$`, says `Path: $` and counts `len(token) + 2` wherever the property sits;
# this route keys the property's **full JSON path**, repeats it, and counts the byte offset of the
# end of the offending token in the document as sent - `398` for `"dash"`, `395` for `" "` and
# `396` for `true` in one measured body, and `153` for a property earlier in the same one
# `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-03]`,
# `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.

#: Every vocabulary a device profile carries, with the key its refusal is filed under and the
#: reference's own name for the enumeration behind it. The measured key names the transcoding
#: entry's `Protocol`, which is a plain string until 012 T9 types it - so the entry's `Type` is
#: asked here instead, at the same depth under the same list.
NESTED_REFUSALS = [
    ("DirectPlayProfiles[0].Type", "DlnaProfileType"),
    ("TranscodingProfiles[0].Type", "DlnaProfileType"),
    ("CodecProfiles[0].Type", "CodecType"),
    ("CodecProfiles[0].Conditions[0].Condition", "ProfileConditionType"),
    ("CodecProfiles[0].Conditions[0].Property", "ProfileConditionValue"),
    ("SubtitleProfiles[0].Method", "SubtitleDeliveryMethod"),
]


def _with_unbindable(one: MediaFile, where: str) -> dict[str, Any]:
    """The profile of that row, with the one property carrying a word no member has."""
    if where.startswith("DirectPlayProfiles"):
        document = accepting(one)
        document["DirectPlayProfiles"][0]["Type"] = "dash"
        return document
    if where.startswith("TranscodingProfiles"):
        document = accepting(one)
        document["TranscodingProfiles"] = [{**TS_HLS, "Type": "dash"}]
        return document
    if where.startswith("SubtitleProfiles"):
        document = accepting(one)
        document["SubtitleProfiles"] = [{"Format": "vtt", "Method": "dash"}]
        return document
    if where.endswith("Condition"):
        return _narrow_video(one, Condition="dash")
    if where.endswith("Property"):
        return _narrow_video(one, Property="dash")
    document = _narrow_video(one)
    document["CodecProfiles"][0]["Type"] = "dash"
    return document


async def _refusal_errors(
    client: httpx.AsyncClient, item_id: str, raw: bytes
) -> dict[str, list[str]]:
    """One refusal of a body written byte for byte, because a byte offset is what it reports."""
    answered = await client.post(
        f"/Items/{item_id}/PlaybackInfo",
        content=raw,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    assert answered.status_code == 400, answered.content
    return dict(answered.json()["errors"])


@pytest.mark.parametrize(("where", "vocabulary"), NESTED_REFUSALS)
async def test_a_nested_refusal_is_keyed_by_the_propertys_own_json_path(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    where: str,
    vocabulary: str,
) -> None:
    """Every vocabulary this body carries, keyed where it sits rather than at the document root.

    T7 made each of these a `400`; what is asserted here is the key and the sentence, which are
    what a client's error display shows and what a bug report quotes. The enumeration is named in
    full, as the reference names it - the namespace each of these is declared in
    `[source: MediaBrowser.Model/Dlna/ @ v10.11.11]`.
    """
    item = served[1].of(DIRECT_PLAY)
    raw = json.dumps(
        {"DeviceProfile": _with_unbindable(DIRECT_PLAY, where)}, separators=(",", ":")
    ).encode()

    errors = await _refusal_errors(client, item.id, raw)

    key = f"$.DeviceProfile.{where}"
    assert list(errors) == [key]
    ends_at = raw.index(b'"dash"') + len(b'"dash"')
    assert errors[key] == [
        f"The JSON value could not be converted to MediaBrowser.Model.Dlna.{vocabulary}. "
        f"Path: {key} | LineNumber: 0 | BytePositionInLine: {ends_at}."
    ]


async def test_the_nested_positions_move_with_the_property_where_the_top_levels_do_not(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The difference between the two shapes, asserted as a difference rather than described.

    `POST /Playlists` answers `3` for a one-character token whether the body is 62 bytes or twice
    that (`tests/conformance/test_playlists.py`). Here the same token in the same property answers
    a different number once something earlier in the document grows, because the number *is* where
    the token sits.
    """
    item = served[1].of(DIRECT_PLAY)
    document = accepting(DIRECT_PLAY)
    document["DirectPlayProfiles"][0]["Type"] = "dash"
    near = json.dumps({"DeviceProfile": document}, separators=(",", ":")).encode()
    far = near.replace(
        b'"MaxStreamingBitrate":120000000',
        b'"MaxStreamingBitrate":120000000' + b',"X":"' + b"y" * 40 + b'"',
    )

    first = await _refusal_errors(client, item.id, near)
    second = await _refusal_errors(client, item.id, far)

    key = "$.DeviceProfile.DirectPlayProfiles[0].Type"
    assert first[key] != second[key]
    assert first[key][0].endswith(f"BytePositionInLine: {near.index(b'"dash"') + 6}.")
    assert second[key][0].endswith(f"BytePositionInLine: {far.index(b'"dash"') + 6}.")


def _models_under(model: type[AtriumModel]) -> Iterator[type[AtriumModel]]:
    """Every model this body reaches, so a property added inside a nested one is not missed."""
    yield model
    for field in model.model_fields.values():
        for argument in (field.annotation, *get_args(field.annotation)):
            for nested in get_args(argument) or (argument,):
                if isinstance(nested, type) and issubclass(nested, AtriumModel):
                    yield from _models_under(nested)


def test_every_vocabulary_this_body_binds_names_the_enumeration_its_refusal_spells() -> None:
    """The registration the key depends on, asked of the whole body rather than of what T8 typed.

    `compat/errors.py` will not invent the reference's name for an enumeration: a property whose
    model does not supply one is answered 007's `""` and `The supplied value is invalid.`, which
    is a body this route does not send. That is a silent shortfall - the status is right and the
    refusal is right - so the rule is asserted here rather than left to whoever adds the next
    enumerated property. It is the shape T7's ordinal sweep has for the same class of omission.
    """
    unnamed = sorted(
        f"{model.__qualname__}.{field}"
        for model in set(_models_under(PlaybackInfoDto))
        for field in model._vocabularies()
        if (model.model_fields[field].alias or field) not in model.WIRE_ENUM_TYPES
    )

    assert not unnamed, (
        f"these properties bind a vocabulary and name no type for its refusal: {unnamed}. The "
        "reference spells the enumeration out in full, and a model that supplies no name is "
        "answered a sentence measured on another route entirely."
    )


async def test_a_top_level_refusal_of_this_body_keeps_the_key_007_measured(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The rule that keeps the path builder from moving anything that already passed.

    A value one level deep is keyed the way 007 and 009 measured it - the empty string and the
    fixed sentence - on the same route and in the same request as the paths above
    `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    item = served[1].of(DIRECT_PLAY)

    answered = await client.post(
        f"/Items/{item.id}/PlaybackInfo", json={"UserId": "banana"}, headers=HEADERS
    )

    assert answered.status_code == 400
    assert answered.json()["errors"] == {"": ["The supplied value is invalid."]}


# ------------------------------------------------------------------------------------------
# The delivery protocol, in four classes - 012 AC-7, AC-8; spec section 3.3
# ------------------------------------------------------------------------------------------
#
# Eighteen spellings, posted to one item on one profile, answering four ways rather than the two
# the spec's opening reading predicted `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
# 2026-08-29]`, behaviours section 2.24. What separates the classes is observable in two fields at
# once - the address handed over and the sub-protocol stated beside it - and the finding this
# feature exists for is that they used to disagree: a profile saying `Hls` was answered a
# progressive address with `TranscodingSubProtocol: "Hls"`, the client's own spelling, on a
# request that was correct against the reference.

#: The one item every row below negotiates: its container is refused, so a target is chosen and an
#: address is answered whatever the protocol turns out to be.
_PROTOCOL_ITEM = REJECTED_CONTAINER

#: Absent, which is a class of its own and cannot be spelled as a value.
UNSTATED = object()


def _stating(protocol: Any) -> dict[str, Any]:
    """`REMUXABLE` with its transcoding target's `Protocol` set to this - or left out entirely."""
    target = {**TS_HLS, "AudioCodec": "ac3"}
    if protocol is UNSTATED:
        del target["Protocol"]
    else:
        target["Protocol"] = protocol
    return profile(
        [{"Container": "mp4", "Type": "Video", "VideoCodec": "h264", "AudioCodec": "ac3"}],
        transcoding=[target],
    )


async def _delivery(client: httpx.AsyncClient, item_id: str, protocol: Any) -> tuple[Any, str]:
    """What the negotiation states the sub-protocol is, and the address it hands over with it."""
    document = await negotiate(client, item_id, {"DeviceProfile": _stating(protocol)})
    one = document["MediaSources"][0]
    return one["TranscodingSubProtocol"], one["TranscodingUrl"]


@pytest.mark.parametrize("spelling", ["hls", "Hls", "HLS", "hLs"])
async def test_ac7_any_case_of_hls_answers_a_playlist_and_the_enumerations_own_spelling(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], spelling: str
) -> None:
    """The delta this feature was opened for, in the direction Principle I tolerates least.

    Three of these four spellings selected a **progressive** address here and an HLS one on the
    reference, because the comparison was against a string. And the answer echoes the
    enumeration's spelling rather than the profile's, which is the second half of the same
    finding: `Hls` in, `"hls"` out.
    """
    item = served[1].of(_PROTOCOL_ITEM)

    stated, address = await _delivery(client, item.id, spelling)

    assert stated == "hls", "AC-7: the enumeration's spelling, never the profile's"
    assert f"/videos/{dashed(item.id)}/master.m3u8?" in address


@pytest.mark.parametrize("spelling", ["http", "Http", "HTTP"])
async def test_ac7_any_case_of_http_answers_a_progressive_address(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], spelling: str
) -> None:
    """The other member, read the same way - and the control the HLS rows are read against."""
    item = served[1].of(_PROTOCOL_ITEM)

    stated, address = await _delivery(client, item.id, spelling)

    assert stated == "http"
    assert f"/videos/{dashed(item.id)}/stream.ts?" in address


@pytest.mark.parametrize("stated_as", [UNSTATED, None, ""])
async def test_ac8_absent_null_and_empty_take_the_declared_default(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], stated_as: Any
) -> None:
    """The one enumeration in v1 that declares a default, and the only place `wire_default` is
    read by something other than its own test.

    The same empty string is a `400` on the five vocabularies beside this one, which is what says
    the fourth class is a registration rather than a rule (T7,
    `test_an_empty_string_refuses_on_every_vocabulary_that_declares_no_default`).
    """
    item = served[1].of(_PROTOCOL_ITEM)

    stated, address = await _delivery(client, item.id, stated_as)

    assert stated == "http", "the declared default, not a fall-through to whatever was on the wire"
    assert f"/videos/{dashed(item.id)}/stream.ts?" in address


@pytest.mark.parametrize(
    ("ordinal", "expected"), [(0, "http"), ("0", "http"), (1, "hls"), ("1", "hls")]
)
async def test_ac8_a_number_binds_to_the_ordinals_member(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    ordinal: Any,
    expected: str,
) -> None:
    """Both members by number and by digit string, which one converter reads for the whole body.

    `0` is the row `_annotate`'s fallback would have hidden: under a truthiness test the member it
    binds to is written and then discarded, and the field keeps the `"http"` it was initialised
    with - the right word for the wrong reason, which no assertion on this row could tell apart.
    The out-of-range ordinal below is the same trap with a number that is *not* the default.
    """
    item = served[1].of(_PROTOCOL_ITEM)

    stated, address = await _delivery(client, item.id, ordinal)

    assert stated == expected
    playlist = f"/videos/{dashed(item.id)}/master.m3u8?" in address
    assert playlist is (expected == "hls"), "the address and the stated sub-protocol agree (AC-7)"


@pytest.mark.parametrize("ordinal", [2, "2"])
async def test_ac8_an_ordinal_no_member_has_survives_to_the_wire_as_a_number(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], ordinal: Any
) -> None:
    """The reference's own one self-contradiction of this shape, reproduced rather than tidied.

    A progressive address beside `TranscodingSubProtocol: 2` - a **number** in a field the
    enumeration spells as a word (behaviours section 2.24). It is a `200` a client can act on, so
    class B: there is nothing to gain by answering `400` where the reference answers a body.

    `is not True` is not pedantry: `True == 1` in Python, and a boolean reaching this field would
    satisfy an `== 2` written any other way.
    """
    item = served[1].of(_PROTOCOL_ITEM)

    stated, address = await _delivery(client, item.id, ordinal)

    assert stated == 2 and not isinstance(stated, bool), "a JSON number, not the word for one"
    assert f"/videos/{dashed(item.id)}/stream.ts?" in address


@pytest.mark.parametrize("unbindable", ["dash", " ", True])
async def test_ac8_a_value_that_binds_to_no_member_refuses_the_whole_body(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld], unbindable: Any
) -> None:
    """The refusal, keyed on the path this feature's T8 built - and the whole `errors` map.

    **Asserted as a map and not as one key**, because the property is `StreamProtocol | int` and
    the framework refuses it once per member: the second refusal is not a vocabulary mismatch, so
    left alone it files itself under 007's `""` and answers two entries where the reference
    answers exactly one (`compat/errors.py:_reported_body_errors`). A test naming `errors[key]`
    would pass over that.

    `true` is the row that says the `int` half of the union is **strict**. A lax one accepts a
    boolean as the ordinal `1` - `isinstance(True, int)` - and would have answered an HLS address
    and a `200` to a value the reference refuses.
    """
    item = served[1].of(_PROTOCOL_ITEM)
    raw = json.dumps({"DeviceProfile": _stating(unbindable)}, separators=(",", ":")).encode()

    errors = await _refusal_errors(client, item.id, raw)

    key = "$.DeviceProfile.TranscodingProfiles[0].Protocol"
    token = json.dumps(unbindable, separators=(",", ":")).encode()
    ends_at = raw.index(b'"Protocol":' + token) + len(b'"Protocol":') + len(token)
    assert errors == {
        key: [
            "The JSON value could not be converted to "
            f"Jellyfin.Data.Enums.MediaStreamProtocol. Path: {key} | "
            f"LineNumber: 0 | BytePositionInLine: {ends_at}."
        ]
    }


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

    **What answers it changed at 012 T7, and this test is what says the answer did not.** 011
    bound this one property through a private validator; that validator is deleted and the
    general binder on `compat/model.py` carries it, along with the four vocabularies beside it.
    Run with the binder removed, this fails with the three rows above - which is what makes it a
    regression check rather than a description.
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


# ------------------------------------------------------------------------------------------
# 012 - the source the negotiation resolves before it reads the profile
# ------------------------------------------------------------------------------------------
#
# Every case below runs on a file the scan could not open, which is a state no other test in this
# repository can reach: the scan that creates an item is the scan that probes it, so the state
# exists only where the probe *failed* (012 spec section 6). `unreadable.mkv` is four kibibytes
# that are not a container and stays that way; `latent.mkv` is the same bytes with a real film
# written over them after the scan, so the negotiation is the only thing that has ever read them.


async def test_ac1_a_source_nothing_opened_answers_flags_that_were_decided(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-1 and AC-4, which are one answer: the reference's own for a file it cannot read.

    `200`, the empty annotation, and the three flags **decided** against the profile rather than
    left at whatever the model initialised them to - `false`/`false`/`true` for a profile that
    plays neither the container nor the codec - with a `TranscodingUrl` beside them
    `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-08-29]`.
    """
    item = served[1].of(UNREADABLE)
    document = await negotiate(client, item.id, {"DeviceProfile": PLAYS_NEITHER})
    source = document["MediaSources"][0]

    assert flags(document) == (False, False, True)
    assert "TranscodingUrl" in source, "AC-4: an advertised capability carries an address"
    assert source["TranscodingSubProtocol"] == "hls"
    assert source["MediaStreams"] == [], "nothing opened it: there is nothing to annotate"
    assert "RunTimeTicks" not in source
    assert "Bitrate" not in source


async def test_ac1_the_empty_annotation_is_still_the_files_own_container_and_size(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The transient inspection is invisible on the wire, which is what keeps AC-10 true.

    `unopened` carries an **empty** container so `media/info.py:source_container` still falls back
    to the extension, and the size stays the source row's. A record that answered anything else
    would make a negotiation change what the same file reads as.
    """
    item = served[1].of(UNREADABLE)
    document = await negotiate(client, item.id, {"DeviceProfile": PLAYS_NEITHER})
    source = document["MediaSources"][0]

    assert source["Container"] == "mkv"
    assert source["Size"] == served[1].files.path_of(UNREADABLE).stat().st_size


async def test_ac1_a_file_that_can_never_be_read_is_reopened_on_every_negotiation(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """Measured on the reference at 0.18-0.20 s, three times running: a file that can never be
    resolved pays the probe on **every** negotiation, for ever (012 spec section 3.2, OQ-1).

    Asserted as the answer rather than as a duration: the same request answers the same decided
    flags a second and a third time, because nothing was stored to make the trigger stop firing.
    """
    item = served[1].of(UNREADABLE)
    answers = [await negotiate(client, item.id, {"DeviceProfile": PLAYS_NEITHER}) for _ in range(3)]

    assert [flags(one) for one in answers] == [(False, False, True)] * 3


async def test_ac2_the_negotiation_that_opens_the_file_is_the_one_that_answers(
    healable_client: httpx.AsyncClient,
    healable: tuple[FastAPI, ScannedMediaWorld],
    writable_files: BuiltMedia,
) -> None:
    """AC-2: fully annotated **by the request that asked**, not by the next scan.

    And the trap T4 set for this task, asserted here rather than left to the listing: `Size` comes
    from the inspection and `ETag` from the source row (`media/info.py:source_of`), so a
    negotiation that healed the file and then assembled the answer from the item it read *before*
    the heal would send the new size beside the tag of bytes nobody can play - D-1's own failure,
    one line inside the request that fixed it (012 plan section 6.2).
    """
    item = healable[1].of(LATENT)
    before = await negotiate(healable_client, item.id, {"DeviceProfile": PLAYS_NEITHER})
    assert before["MediaSources"][0]["MediaStreams"] == [], (
        "the fixture opened: nothing below is a test"
    )

    _real_bytes_over(writable_files, LATENT, REJECTED_CONTAINER)
    healed = await negotiate(
        healable_client, item.id, {"DeviceProfile": accepting(REJECTED_CONTAINER)}
    )
    source = healed["MediaSources"][0]

    assert [one["Type"] for one in source["MediaStreams"]] == ["Video", "Audio"]
    assert source["RunTimeTicks"] > 0
    assert source["Bitrate"] > 0
    assert source["Size"] == writable_files.path_of(LATENT).stat().st_size
    assert source["Size"] != LATENT.size, "the replacement is a real film, not the junk bytes"
    assert source["ETag"] == media_etag(writable_files.path_of(LATENT).stat().st_mtime_ns), (
        "the healed body answers the tag of the bytes it just read, not the ones the scan saw"
    )
    assert flags(healed) == (True, True, True)


async def test_ac3_the_next_listing_carries_what_the_negotiation_learned(
    healable_client: httpx.AsyncClient,
    healable: tuple[FastAPI, ScannedMediaWorld],
    writable_files: BuiltMedia,
) -> None:
    """AC-3, and the whole of the music client's cure: the inspection is **kept**.

    Listed, negotiated, listed again - with no scan in between. The listing path learned nothing
    and probes nothing; it reads the row the negotiation wrote (012 spec section 3.1 row four,
    OQ-9).
    """
    item = healable[1].of(LATENT)
    empty = await _item(healable_client, item.id)
    assert empty["MediaSources"][0]["MediaStreams"] == []
    assert "RunTimeTicks" not in empty["MediaSources"][0]

    _real_bytes_over(writable_files, LATENT, REJECTED_CONTAINER)
    await negotiate(healable_client, item.id, {"DeviceProfile": accepting(REJECTED_CONTAINER)})

    after = await _item(healable_client, item.id)
    source = after["MediaSources"][0]
    assert [one["Type"] for one in source["MediaStreams"]] == ["Video", "Audio"]
    assert source["RunTimeTicks"] > 0
    assert source["Bitrate"] > 0
    assert source["Size"] == writable_files.path_of(LATENT).stat().st_size
    assert source["ETag"] != empty["MediaSources"][0]["ETag"], (
        "D-1: the change signal moves with the inspection, or the tag describes other bytes"
    )


async def test_ac5_the_second_opinion_is_a_different_answer(
    healable_client: httpx.AsyncClient,
    healable: tuple[FastAPI, ScannedMediaWorld],
    writable_files: BuiltMedia,
) -> None:
    """AC-5: a client that comes back saying *"I cannot direct-play this"* is answered differently.

    **Asserted on a source the profile can direct-play**, which is the discriminating half: asked
    against `unreadable.mkv` and a profile that plays nothing, both answers refuse and the two
    bodies would match while proving nothing. Today - before the resolution - both answers are
    identical for this file too, because the branch that would read the switches is the branch
    that was skipped (012 spec section 3.1, row two).
    """
    item = healable[1].of(LATENT)
    _real_bytes_over(writable_files, LATENT, REJECTED_CONTAINER)
    profile_body = {"DeviceProfile": accepting(REJECTED_CONTAINER)}

    played = await negotiate(healable_client, item.id, profile_body)
    refused = await negotiate(
        healable_client,
        item.id,
        {**profile_body, "EnableDirectPlay": False, "EnableDirectStream": False},
    )

    assert flags(played) == (True, True, True)
    assert flags(refused) == (False, False, True)
    assert _comparable(played) != _comparable(refused), "the switches reached the ladder"
    assert "TranscodingUrl" in refused["MediaSources"][0]
    assert "TranscodingUrl" not in played["MediaSources"][0]


async def test_the_route_yields_while_a_file_is_being_opened(
    healable_client: httpx.AsyncClient,
    healable: tuple[FastAPI, ScannedMediaWorld],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`media/probe.py:inspect` is a `subprocess.run` bounded at 60 s, and this route is `async`.

    Asserted as a fact about the loop rather than as a duration (Principle VII): a second request
    is answered *while* the first is still inside the prober, which is only possible if the
    inspection left the event loop (`asyncio.to_thread`, 012 plan section 6.2). Run the probe
    inline and the second request cannot be answered until the first releases it, and this test
    fails on its own timeout rather than on a clock.
    """
    entered = threading.Event()
    release = threading.Event()

    def blocking(path: Path, prober: Any = None) -> None:
        entered.set()
        assert release.wait(timeout=10), "the second request never answered: the loop was blocked"
        return None

    monkeypatch.setattr(inspection, "opened", blocking)
    unreadable = healable[1].of(UNREADABLE)
    readable = healable[1].of(DIRECT_PLAY)

    first = asyncio.create_task(
        negotiate(healable_client, unreadable.id, {"DeviceProfile": PLAYS_NEITHER})
    )
    assert await asyncio.to_thread(entered.wait, 10), "the negotiation never reached the prober"

    answered = await healable_client.get(f"/Items/{readable.id}/PlaybackInfo", headers=HEADERS)

    assert answered.status_code == 200
    assert not first.done(), "the first request is still inside the prober, which is the point"
    release.set()
    assert flags(await first) == (False, False, True)


async def test_a_part_the_trigger_never_fires_for_is_still_decided_rather_than_advertised(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The source removing the old branch reaches that nothing in this feature opens.

    A two-part film whose part one is readable and whose part two is not: the trigger reads source
    **zero**, finds it annotated and does not fire, so 012 never opens part two (plan section 6.1,
    invariant 2). Part two is nevertheless *answered*, and this is where the rule the feature is
    named for bites - a source advertising three capabilities with no address behind any of them
    is the defect, whether or not the reference has an item shaped like this one. It has not: an
    unreadable part is neither a source of the grouped item nor an item of its own there
    `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`, so what this
    asserts is **this** server's answer being consistent with itself.

    That the trigger does not fire for this item is
    `tests/unit/test_library_inspection.py`'s row, over the same two files and the same real scan.
    """
    item = served[1].of(MISSING_HALF_FIRST)
    assert item.id == served[1].of(MISSING_HALF_SECOND).id, "003 stopped merging the parts"

    document = await negotiate(client, item.id, {"DeviceProfile": PLAYS_NEITHER})
    played, unopened = document["MediaSources"]

    assert unopened["MediaStreams"] == [], "part two is the half nothing ever opened"
    assert played["MediaStreams"] != [], "part one is the half the scan read"
    for source in (played, unopened):
        assert source["SupportsDirectPlay"] is False
        assert source["SupportsDirectStream"] is False
        assert source["SupportsTranscoding"] is True
        assert "TranscodingUrl" in source, "every advertised capability carries an address (AC-4)"


async def test_a_part_the_scan_already_opened_is_not_re_opened_when_the_trigger_fires(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard inside `api/media_info.py:_opened`, held on its own - audit 2026-09-04's M17.

    **The trigger and the guard are two conditions, and only one of them was ever asserted.** The
    trigger asks whether *source zero* carries a stream of the item's own kind; the guard asks,
    per part, whether that part already carries an inspection. `videoless.mkv` is the file where
    they disagree: the scan opened it and stored what it holds, so the guard says "nothing to
    open" - and it holds no video stream, so the trigger fires anyway, on this request and on
    every one after it for ever (012 spec section 3.2). Every other test in this section runs on
    an item where the two agree, which is why deleting the guard left ~5250 tests green.

    Asserted as **zero invocations of the prober**, because the damage is invisible in the body:
    without the guard this negotiation re-runs `ffprobe` over an already-inspected file and
    rewrites its two rows, answering exactly what it answers now. `wanted` is watched rather than
    assumed so the assertion below cannot pass vacuously - a trigger that stopped firing would
    make "the prober was not called" true for the wrong reason, and this test would go green on a
    world where the guard is unreachable.
    """
    fired: list[bool] = []
    probed: list[Path] = []
    trigger = inspection.wanted

    def watched(*args: Any, **keywords: Any) -> bool:
        answer = trigger(*args, **keywords)
        fired.append(answer)
        return answer

    def counted(path: Path, prober: Any = None) -> None:
        probed.append(path)
        return None

    monkeypatch.setattr(inspection, "wanted", watched)
    monkeypatch.setattr(inspection, "opened", counted)

    item = served[1].of(VIDEOLESS)
    document = await negotiate(client, item.id, {"DeviceProfile": PLAYS_NEITHER})
    source = document["MediaSources"][0]

    assert fired == [True], "the trigger must fire, or the guard beneath it is never reached"
    assert probed == [], "an already-inspected part is not re-opened by a trigger about the item"
    assert [one["Type"] for one in source["MediaStreams"]] == ["Audio"], (
        "and the stored inspection is what the answer is built from"
    )


async def test_a_file_gone_from_disk_since_the_scan_is_answered_from_what_the_scan_stored(
    healable_client: httpx.AsyncClient,
    healable: tuple[FastAPI, ScannedMediaWorld],
    writable_files: BuiltMedia,
) -> None:
    """[Spec section 3.4](../../specs/012-negotiation-inputs/spec.md)'s fourth row, which had no
    test at any level until T11 read that table against the map.

    A file **deleted** after the scan is not an un-inspected source and must not be answered as
    one. The stored streams are still there, so the trigger never fires, nothing opens the file,
    and the answer is a normal fully annotated `200` with an address - which is what the reference
    answers too, and for the same reason `[probe: tools/probe_uninspected_source.py, Jellyfin
    10.11.11, 2026-08-29]` (behaviours section 2.23's second consequence).

    **It is the row that discriminates the trigger this feature implements from the one it is
    easily mistaken for.** Written as *"the file cannot be read"* rather than as the reference's
    *"source zero carries no stream of the item's own kind"*, the trigger fires here, the
    inspection fails on bytes that are gone, and a client is handed the empty annotation for an
    item the scan had fully described - every other test in this section still passing. Asserted
    as the **whole body** either side of the deletion, because what the row claims is that nothing
    moves and not that one field survives.
    """
    item = healable[1].of(REJECTED_CONTAINER)
    body = {"DeviceProfile": PLAYS_NEITHER}
    before = await negotiate(healable_client, item.id, body)

    writable_files.path_of(REJECTED_CONTAINER).unlink()
    after = await negotiate(healable_client, item.id, body)

    assert not writable_files.path_of(REJECTED_CONTAINER).exists(), "the deletion is the test"
    source = after["MediaSources"][0]
    assert [one["Type"] for one in source["MediaStreams"]] == ["Video", "Audio"]
    assert source["RunTimeTicks"] > 0 and source["Bitrate"] > 0
    assert "TranscodingUrl" in source, "an address for bytes that are not there: nothing looked"
    assert _comparable(after) == _comparable(before), "the answer is the scan's, deletion or not"


@pytest.mark.parametrize(
    "policy,expected",
    [row[1:] for row in _UNNEGOTIATED],
    ids=[row[0] for row in _UNNEGOTIATED],
)
async def test_a_never_opened_source_with_no_profile_answers_what_it_answered_before(
    client: httpx.AsyncClient,
    served: tuple[FastAPI, ScannedMediaWorld],
    policy: dict[str, bool],
    expected: tuple[bool, bool, bool],
) -> None:
    """The claim removing the old branch rests on, measured instead of traced.

    That branch wrote two flags from the account's own permissions before it skipped the source,
    and the tasks gate traced that `decide()`'s rule 1 writes the same two itself - so a
    profile-less negotiation of a source nothing has opened answers what it answered before,
    field for field. The **same** five policy shapes as the row above, on the source that used to
    take the other branch: what the file behind it holds does not enter rule 1 at all, so the two
    tables answering differently would mean the branch was load-bearing after all.
    """
    app, world = served
    app.dependency_overrides[require_user] = _as_viewer(policy)
    unreadable = world.of(UNREADABLE).id

    posted = await negotiate(client, unreadable)
    assert flags(posted) == expected
    assert "TranscodingUrl" not in posted["MediaSources"][0], (
        "rule 1 returns at the direct-play guard, so no address is added on this path"
    )

    answered = await client.get(f"/Items/{unreadable}/PlaybackInfo", headers=HEADERS)
    assert answered.status_code == 200
    assert flags(dict(answered.json())) == expected, "the GET carries no profile either"


# ------------------------------------------------------------------------------------------
# 012 - the audio refusal, which is the platform's and not this feature's
# ------------------------------------------------------------------------------------------
#
# The condition is the **audio stream** and not the file: the reference's audio builder asks the
# source for its default audio stream and throws when there is none, so a track nothing could open
# and a perfectly readable track carrying no audio track are refused identically (012 spec section
# 3.4). Both are asserted here, over the two worlds that can reach them - `soundless.m4a`
# overwritten with junk before the scan for the first, and the same file as generated for the
# second.


@pytest.fixture
def unopened_audio(
    media_paths: DataPaths, writable_files: BuiltMedia
) -> Iterator[tuple[FastAPI, ScannedMediaWorld]]:
    """An **audio** item whose file nothing has ever opened, which the matrix has no entry for.

    `tests/fixtures/media.py` declares four files no prober will accept and every one of them is
    a film, so the row spec section 3.4 states for an audio item - a `400` with a profile and an
    un-annotated `200` without one - is unreachable over the generated tree as it stands. The
    junk bytes of `unreadable.mkv` are written over `soundless.m4a` **before** the scan, which
    makes the state without adding a file: adding one would move the fixture tree that 010's AC-2
    compares two servers over, and that is a re-recording rather than a test (012 T2's own note).
    """
    writable_files.path_of(SOUNDLESS).write_bytes(UNREADABLE.content())
    yield from _serve(media_paths, writable_files)


@pytest.fixture
async def unopened_audio_client(
    unopened_audio: tuple[FastAPI, ScannedMediaWorld],
) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=unopened_audio[0])
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def _assert_refused(answered: httpx.Response) -> None:
    """The whole of the refusal, in the bytes a client receives.

    Not `== CONTROLLER_ERROR_BODY`: that constant is what this server sends, so comparing against
    it would compare Atrium with itself. The literal is what T1 printed off the reference - `400`,
    `text/plain` with no charset, **25 bytes**, `Error processing request.`
    `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`.
    """
    assert answered.status_code == 400
    assert answered.headers["Content-Type"] == "text/plain"
    assert answered.content == b"Error processing request."
    assert len(answered.content) == 25


async def test_ac6_an_audio_item_with_no_audio_stream_refuses_the_whole_request(
    unopened_audio_client: httpx.AsyncClient, unopened_audio: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-6's first half: `400` for the request, not a source with the flags left alone.

    The whole answer goes, which is what a refusal thrown out of a builder does - there is no
    partial body naming the source it fell over.
    """
    item = unopened_audio[1].of(SOUNDLESS)
    assert item.type is ItemType.AUDIO, "an audio item, or this is not the row spec 3.4 states"

    answered = await unopened_audio_client.post(
        f"/Items/{item.id}/PlaybackInfo", json={"DeviceProfile": PLAYS_NEITHER}, headers=HEADERS
    )

    _assert_refused(answered)


async def test_ac6_the_same_request_with_no_profile_answers_the_un_annotated_source(
    unopened_audio_client: httpx.AsyncClient, unopened_audio: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """AC-6's second half, and it is the same request one field shorter.

    The reference reaches the builder only inside `if (profile is not null)`, so with no profile
    in the body and none stored for the device there is nothing to refuse: `200`, the source with
    nothing annotated on it, and the flags rule 1 writes
    `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:104 @ v10.11.11]`, 012 plan section 6.4.
    """
    item = unopened_audio[1].of(SOUNDLESS)
    document = await negotiate(unopened_audio_client, item.id)
    source = document["MediaSources"][0]

    assert source["MediaStreams"] == [], "nothing opened it: there is nothing to annotate"
    assert "RunTimeTicks" not in source
    assert "TranscodingUrl" not in source, "rule 1 returns before an address is added"

    answered = await unopened_audio_client.get(f"/Items/{item.id}/PlaybackInfo", headers=HEADERS)
    assert answered.status_code == 200, "the GET carries no profile either"


async def test_ac6_a_stored_device_profile_is_a_profile_in_play(
    unopened_audio_client: httpx.AsyncClient, unopened_audio: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The gate is the profile this negotiation ended up with, not the one the body carried.

    A body with no `DeviceProfile` is refused when the device stored one, which is the same
    fallback 008 T4 measured for every other answer on this route - and the half of AC-6's
    second clause that reads *"and no stored device profile"*.
    """
    app, world = unopened_audio
    _store_capabilities(app, PLAYS_NEITHER)
    item = world.of(SOUNDLESS)

    answered = await unopened_audio_client.post(
        f"/Items/{item.id}/PlaybackInfo", json={}, headers=HEADERS
    )

    _assert_refused(answered)


async def test_the_refusal_is_the_missing_audio_stream_and_not_the_unreadable_file(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The row that separates the two conditions, on the file the fixture is named after.

    `soundless.m4a` is a **readable** mp4 that the scan opened and stored a video stream for, and
    it is refused exactly like the junk bytes above: `GetDefaultAudioStream(null)` answering
    nothing is the whole condition `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:104 @
    v10.11.11]`. A condition written as *"the inspection failed"* passes every other test in this
    section and fails this one, which is why the fixture exists (012 plan section 6.4).

    The no-profile answer is asserted first, and it is what proves the file really was opened: an
    annotated source, refused a moment later for what it does not carry rather than for what
    nothing could read.
    """
    item = served[1].of(SOUNDLESS)
    opened = await negotiate(client, item.id)
    source = opened["MediaSources"][0]

    assert [one["Type"] for one in source["MediaStreams"]] == ["Video"], (
        "the scan read this file: a video stream and no audio stream is the whole fixture"
    )
    assert source["RunTimeTicks"] > 0

    answered = await client.post(
        f"/Items/{item.id}/PlaybackInfo", json={"DeviceProfile": PLAYS_NEITHER}, headers=HEADERS
    )

    _assert_refused(answered)


async def test_a_film_with_no_video_stream_is_answered_rather_than_refused(
    client: httpx.AsyncClient, served: tuple[FastAPI, ScannedMediaWorld]
) -> None:
    """The refusal belongs to the **audio** builder, and the mirror image proves it.

    A film whose file carries no video stream fires the same trigger as the track above and is
    answered `200` with its flags decided - spec section 3.4's first row - because the video
    builder has no `ThrowIfNull` beside the audio builder's. Written as *"an item with no stream
    of its own kind"*, this feature would refuse a film the reference answers for.
    """
    item = served[1].of(VIDEOLESS)
    document = await negotiate(client, item.id, {"DeviceProfile": PLAYS_NEITHER})

    assert flags(document) == (False, False, True)
    assert "TranscodingUrl" in document["MediaSources"][0]
