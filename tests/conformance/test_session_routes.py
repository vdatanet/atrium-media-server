# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Sessions` and `POST /Sessions/Capabilities/Full`, at the boundary.

**AC-9** lands here: capabilities posted appear in the caller's `/Sessions` entry. It is the
criterion that decides whether storing a declaration nothing acts on is worth doing, and the
answer is that a client which posts and then does not see them has observed a difference.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.guids import new_id
from atrium.db.repositories import UserRepository
from atrium.domain.playstate import TICKS_PER_SECOND
from atrium.domain.user import User
from tests.fixtures.query import RUNTIME_TICKS, QueryWorld, build_query_world

PASSWORD = "correct horse battery staple"
CLIENT_HEADER = 'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="bench-1", Version="1"'


def make_user(app: FastAPI, name: str = "Joan", **overrides: object) -> User:
    fields: dict[str, object] = {
        "id": new_id(),
        "name": name,
        "password_hash": app.state.passwords.hash(PASSWORD),
    }
    fields.update(overrides)
    with app.state.sessions.begin() as opened:
        return UserRepository(opened).add(User(**fields))  # type: ignore[arg-type]


async def log_in(client: httpx.AsyncClient, name: str = "Joan", device: str = "bench-1") -> str:
    header = CLIENT_HEADER.replace("bench-1", device).replace("Bench", device.title())
    answered = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": name, "Pw": PASSWORD},
        headers={"X-Emby-Authorization": header},
    )
    token: str = answered.json()["AccessToken"]
    return token


@pytest.fixture
def joan(app: FastAPI) -> User:
    return make_user(app)


# --------------------------------------------------------------------------------------------
# GET /Sessions
# --------------------------------------------------------------------------------------------


async def test_a_session_appears_after_logging_in(client: httpx.AsyncClient, joan: User) -> None:
    token = await log_in(client)
    listed = await client.get("/Sessions", headers={"X-Emby-Token": token})
    assert listed.status_code == 200
    [entry] = listed.json()
    assert entry["DeviceId"] == "bench-1"
    assert entry["UserName"] == "Joan"
    assert entry["UserId"] == joan.id


async def test_two_devices_show_two_sessions(client: httpx.AsyncClient, joan: User) -> None:
    await log_in(client, device="phone")
    token = await log_in(client, device="tablet")
    listed = (await client.get("/Sessions", headers={"X-Emby-Token": token})).json()
    assert {one["DeviceId"] for one in listed} == {"phone", "tablet"}


async def test_an_ordinary_user_sees_only_their_own(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    make_user(app, name="Ada")
    await log_in(client, name="Ada", device="ada-laptop")
    token = await log_in(client, device="joan-phone")

    listed = (await client.get("/Sessions", headers={"X-Emby-Token": token})).json()
    assert {one["UserName"] for one in listed} == {"Joan"}


async def test_an_administrator_sees_all_of_them(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    make_user(app, name="Root", is_administrator=True)
    await log_in(client, device="joan-phone")
    token = await log_in(client, name="Root", device="root-laptop")

    listed = (await client.get("/Sessions", headers={"X-Emby-Token": token})).json()
    assert {one["UserName"] for one in listed} == {"Joan", "Root"}


async def test_sessions_needs_a_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/Sessions")).status_code == 401


async def test_the_entry_carries_the_reference_field_order(
    client: httpx.AsyncClient, joan: User
) -> None:
    """The reference's twenty-three, minus `UserPrimaryImageTag` - null here, and nulls are
    omitted globally. A golden comparing bytes cares about this; a client does not."""
    token = await log_in(client)
    [entry] = json.loads((await client.get("/Sessions", headers={"X-Emby-Token": token})).content)
    assert list(entry) == [
        "PlayState",
        "AdditionalUsers",
        "Capabilities",
        "RemoteEndPoint",
        "PlayableMediaTypes",
        "Id",
        "UserId",
        "UserName",
        "Client",
        "LastActivityDate",
        "LastPlaybackCheckIn",
        "DeviceName",
        "DeviceId",
        "ApplicationVersion",
        "IsActive",
        "SupportsMediaControl",
        "SupportsRemoteControl",
        "NowPlayingQueue",
        "NowPlayingQueueFullItems",
        "HasCustomDeviceName",
        "ServerId",
        "SupportedCommands",
    ]


async def test_activity_is_read_through_the_registry_not_the_database(
    app: FastAPI, client: httpx.AsyncClient, joan: User
) -> None:
    """Reporting the flushed value would tell a client that the session it is making this very
    request with was last active half a minute ago."""
    token = await log_in(client)
    headers = {"X-Emby-Token": token}
    listed = (await client.get("/Sessions", headers=headers)).json()
    reported = listed[0]["LastActivityDate"]

    assert app.state.registry.snapshot(), "the request advanced nothing in memory"
    session_id = listed[0]["Id"]
    assert app.state.registry.activity(session_id) is not None
    assert reported


# --------------------------------------------------------------------------------------------
# AC-9: what a client declared comes back
# --------------------------------------------------------------------------------------------


async def test_capabilities_posted_appear_in_the_callers_session(
    client: httpx.AsyncClient, joan: User
) -> None:
    """AC-9. v1 acts on none of it, and a client that posts and then does not see them has
    observed a difference - which is why storing it is not optional."""
    token = await log_in(client)
    headers = {"X-Emby-Token": token}
    posted = {
        "PlayableMediaTypes": ["Video", "Audio"],
        "SupportedCommands": ["Play", "DisplayMessage"],
        "SupportsMediaControl": True,
        "SupportsPersistentIdentifier": False,
    }
    stored = await client.post("/Sessions/Capabilities/Full", json=posted, headers=headers)
    assert stored.status_code == 204
    assert stored.content == b""

    [entry] = (await client.get("/Sessions", headers=headers)).json()
    assert entry["Capabilities"] == posted
    assert entry["PlayableMediaTypes"] == ["Video", "Audio"]
    assert entry["SupportedCommands"] == ["Play", "DisplayMessage"]


async def test_the_declaration_is_echoed_and_the_flag_is_the_servers_own(
    client: httpx.AsyncClient, joan: User
) -> None:
    """Measured: the reference reports `SupportsMediaControl: false` at the top level for a
    session that posted `true`, while echoing that `true` back inside `Capabilities`.

    They are different values from the same request - the declaration is the client's, the flag is
    the server's judgement about it. Hoisting the declaration into the flag is the obvious wrong
    implementation and would be a delta on every session a controlling client opens.
    """
    token = await log_in(client)
    headers = {"X-Emby-Token": token}
    await client.post(
        "/Sessions/Capabilities/Full", json={"SupportsMediaControl": True}, headers=headers
    )
    [entry] = (await client.get("/Sessions", headers=headers)).json()

    assert entry["Capabilities"]["SupportsMediaControl"] is True
    assert entry["SupportsMediaControl"] is False
    assert entry["SupportsRemoteControl"] is False


async def test_posting_replaces_rather_than_merges(client: httpx.AsyncClient, joan: User) -> None:
    """The route is `Full`, and the reference replaces. Measured."""
    token = await log_in(client)
    headers = {"X-Emby-Token": token}
    await client.post(
        "/Sessions/Capabilities/Full",
        json={"PlayableMediaTypes": ["Video"], "SupportsMediaControl": True},
        headers=headers,
    )
    await client.post(
        "/Sessions/Capabilities/Full", json={"PlayableMediaTypes": ["Audio"]}, headers=headers
    )
    [entry] = (await client.get("/Sessions", headers=headers)).json()
    assert entry["Capabilities"] == {"PlayableMediaTypes": ["Audio"]}


async def test_an_unknown_property_is_kept_rather_than_rejected(
    client: httpx.AsyncClient, joan: User
) -> None:
    """Measured `204` at the reference, which is the leniency this route does have.

    The round-trip below is Atrium's own behaviour, not parity: the reference answers the same
    `204` and then drops the stranger from the session's `Capabilities`
    `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]` - the recorded
    divergence of behaviours section 5.9, observable by no client the reference could have.
    """
    token = await log_in(client)
    headers = {"X-Emby-Token": token}
    posted = {"PlayableMediaTypes": ["Video"], "SomethingFromANewerClient": {"x": 1}}
    assert (
        await client.post("/Sessions/Capabilities/Full", json=posted, headers=headers)
    ).status_code == 204
    [entry] = (await client.get("/Sessions", headers=headers)).json()
    assert entry["Capabilities"]["SomethingFromANewerClient"] == {"x": 1}


async def test_an_unknown_command_is_accepted_here_and_refused_there(
    client: httpx.AsyncClient, joan: User
) -> None:
    """A known, argued divergence. The reference binds `SupportedCommands` to an enum and answers
    `400` with problem details; v1 acts on none of those commands, so reproducing a thirty-value
    enum to refuse values no working client sends is cost without a client that benefits.
    behaviours section 5.
    """
    token = await log_in(client)
    headers = {"X-Emby-Token": token}
    answered = await client.post(
        "/Sessions/Capabilities/Full", json={"SupportedCommands": ["NotACommand"]}, headers=headers
    )
    assert answered.status_code == 204


async def test_capabilities_needs_a_token(client: httpx.AsyncClient) -> None:
    assert (await client.post("/Sessions/Capabilities/Full", json={})).status_code == 401


# --------------------------------------------------------------------------------------------
# What a playing session shows (007 AC-22)
# --------------------------------------------------------------------------------------------


@pytest.fixture
def world(app: FastAPI) -> QueryWorld:
    """The 005 world, so a session has something real to be playing.

    Its users are seeded without passwords - 005 never logged one in - and these tests need a real
    session rather than an overridden dependency, because a report binds to the **authenticated
    device**. So the unrestricted user gets one here.
    """
    with app.state.sessions.begin() as opened:
        built = build_query_world(opened)
        UserRepository(opened).set_password_hash(
            built.everyone.id, app.state.passwords.hash(PASSWORD)
        )
        return built


async def playing_session(
    client: httpx.AsyncClient, token: str, item_id: str, **report: object
) -> dict:
    """Start playback as the logged-in device, and read that session back."""
    body = {"ItemId": item_id, "PositionTicks": 0, "CanSeek": True, "VolumeLevel": 80}
    body.update(report)
    answered = await client.post("/Sessions/Playing", json=body, headers={"X-Emby-Token": token})
    assert answered.status_code == 204
    entries = json.loads((await client.get("/Sessions", headers={"X-Emby-Token": token})).content)
    return next(one for one in entries if one.get("NowPlayingItem"))


async def test_ac22_now_playing_sits_between_device_name_and_device_id(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The measured slot. Everything else about the order is 002's and unchanged."""
    token = await log_in(client, world.everyone.name)
    entry = await playing_session(client, token, world.corpus[1])
    keys = list(entry)
    assert keys[keys.index("DeviceName") + 1] == "NowPlayingItem"
    assert keys[keys.index("NowPlayingItem") + 1] == "DeviceId"


async def test_ac22_the_now_playing_item_carries_no_user_data(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The one measured item shape that omits `UserData` entirely - and fourteen other properties
    a full item body carries, which is what `NOT_IN_NOW_PLAYING` names."""
    token = await log_in(client, world.everyone.name)
    entry = await playing_session(client, token, world.corpus[1])
    playing = entry["NowPlayingItem"]
    assert "UserData" not in playing
    assert not {"Etag", "SortName", "People", "Tags"} & set(playing)
    assert playing["Id"] == world.corpus[1]
    assert playing["RunTimeTicks"] == RUNTIME_TICKS


async def test_ac22_play_state_mirrors_exactly_the_last_report(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """A progress omitting `CanSeek` and `VolumeLevel` reads back `CanSeek: false` and no volume:
    the report replaces the state whole, and merging would invent one no reference server sends."""
    token = await log_in(client, world.everyone.name)
    entry = await playing_session(client, token, world.corpus[1], CanSeek=True, VolumeLevel=80)
    assert entry["PlayState"]["CanSeek"] is True
    assert entry["PlayState"]["VolumeLevel"] == 80

    await client.post(
        "/Sessions/Playing/Progress",
        json={"ItemId": world.corpus[1], "PositionTicks": RUNTIME_TICKS // 4},
        headers={"X-Emby-Token": token},
    )
    entries = json.loads((await client.get("/Sessions", headers={"X-Emby-Token": token})).content)
    state = next(one for one in entries if one.get("NowPlayingItem"))["PlayState"]
    assert state["CanSeek"] is False
    assert "VolumeLevel" not in state
    assert state["PositionTicks"] >= RUNTIME_TICKS // 4


async def test_a_report_lands_on_the_callers_session_whatever_it_names(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """AC-24, spec section 3.6: a report binds to the caller's session, never to one it names.

    The body claims a `PlaySessionId` and an `Id` that exist nowhere. The playback must land on
    the authenticated device's entry, and no entry may exist under the claimed identifier — a
    server that trusted the body would let one device write another's play state.
    """
    token = await log_in(client, world.everyone.name, device="honest-device")
    bogus = new_id()
    await client.post(
        "/Sessions/Playing",
        json={
            "ItemId": world.corpus[1],
            "PositionTicks": 0,
            "PlaySessionId": bogus,
            "Id": bogus,
        },
        headers={"X-Emby-Token": token},
    )
    entries = (await client.get("/Sessions", headers={"X-Emby-Token": token})).json()
    playing = [one for one in entries if one.get("NowPlayingItem")]
    assert [one["DeviceId"] for one in playing] == ["honest-device"]
    assert all(one["Id"] != bogus for one in entries)


async def test_the_play_state_field_order_is_the_measured_one(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    token = await log_in(client, world.everyone.name)
    entry = await playing_session(
        client,
        token,
        world.corpus[1],
        IsMuted=False,
        AudioStreamIndex=1,
        SubtitleStreamIndex=-1,
        MediaSourceId=world.corpus[1],
        PlayMethod="DirectPlay",
    )
    assert list(entry["PlayState"]) == [
        "PositionTicks",
        "CanSeek",
        "IsPaused",
        "IsMuted",
        "VolumeLevel",
        "AudioStreamIndex",
        "SubtitleStreamIndex",
        "MediaSourceId",
        "PlayMethod",
        "RepeatMode",
        "PlaybackOrder",
    ]


async def test_the_position_advances_between_reports(
    app: FastAPI, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """A `/Sessions` poller watches the position move without a report arriving, which is what the
    reference's per-second ticker looks like from the outside. The registry's monotonic clock is
    stepped by hand rather than slept through."""
    elapsed = [1000.0]
    app.state.playing._monotonic = lambda: elapsed[0]
    token = await log_in(client, world.everyone.name)
    entry = await playing_session(client, token, world.corpus[1], PositionTicks=RUNTIME_TICKS // 2)
    before = entry["PlayState"]["PositionTicks"]

    elapsed[0] += 30
    entries = json.loads((await client.get("/Sessions", headers={"X-Emby-Token": token})).content)
    after = next(one for one in entries if one.get("NowPlayingItem"))["PlayState"]["PositionTicks"]
    assert after == before + 30 * TICKS_PER_SECOND


async def test_the_entry_goes_back_to_twenty_three_fields_when_playback_stops(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """`NowPlayingItem` is absent rather than null, so an idle session is byte-identical to what
    002 pinned - which is why growing the model moved no golden."""
    token = await log_in(client, world.everyone.name)
    await playing_session(client, token, world.corpus[1])
    await client.post(
        "/Sessions/Playing/Stopped",
        json={"ItemId": world.corpus[1], "PositionTicks": RUNTIME_TICKS // 2},
        headers={"X-Emby-Token": token},
    )
    [entry] = json.loads((await client.get("/Sessions", headers={"X-Emby-Token": token})).content)
    assert "NowPlayingItem" not in entry
    assert entry["PlayState"] == {
        "CanSeek": False,
        "IsPaused": False,
        "IsMuted": False,
        "RepeatMode": "RepeatNone",
        "PlaybackOrder": "Default",
    }


async def test_the_playback_check_in_advances_live(
    client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Read through the registry, like `LastActivityDate`: a client that just reported must not be
    told its own session has never played anything, which is what the stored column says until the
    next flush."""
    token = await log_in(client, world.everyone.name)
    entry = await playing_session(client, token, world.corpus[1])
    assert entry["LastPlaybackCheckIn"] != "0001-01-01T00:00:00.0000000Z"
