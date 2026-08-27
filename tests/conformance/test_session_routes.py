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
from atrium.domain.user import User

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
    """Measured `204` at the reference, which is the leniency this route does have."""
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
