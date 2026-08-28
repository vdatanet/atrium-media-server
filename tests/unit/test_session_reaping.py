# SPDX-License-Identifier: GPL-3.0-or-later
"""The sweep, end to end: a session goes silent and the viewer keeps their place.

This is AC-15, and the half of it that is easy to get wrong is not the clearing - it is **what
position gets committed**. The measurement that corrected the criterion reported 40%, went quiet
for 8.6 minutes and read back 48.5%: the reference extrapolates the unpaused position in real time
and the reap commits the extrapolated value, so a client killed by the operating system resumes
where the viewer actually was rather than at the last report.

Both clocks are stepped by hand. A test that slept would take six minutes and still assert less.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.config.paths import DataPaths
from atrium.db import models
from atrium.db.repositories import UserRepository
from atrium.domain.playstate import TICKS_PER_SECOND
from atrium.server import create_app
from atrium.users.playing import SILENCE_THRESHOLD
from tests.conftest import data_dir
from tests.fixtures.query import RUNTIME_TICKS, QueryWorld, build_query_world

PASSWORD = "correct horse battery staple"
CLIENT_HEADER = 'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="bench-1", Version="1"'


class Clocks:
    def __init__(self) -> None:
        self.wall = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        self.elapsed = 1000.0

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.elapsed += seconds


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld
    clocks: Clocks


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
        UserRepository(opened).set_password_hash(
            world.everyone.id, built.state.passwords.hash(PASSWORD)
        )
    clocks = Clocks()
    # The registry the application built, with its clocks replaced: the reaper is the one piece
    # of this feature whose behaviour *is* the passage of time, so the test owns the passing.
    built.state.playing._clock = lambda: clocks.wall
    built.state.playing._monotonic = lambda: clocks.elapsed
    yield Harness(app=built, world=world, clocks=clocks)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


async def log_in(client: httpx.AsyncClient, name: str) -> str:
    answered = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": name, "Pw": PASSWORD},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    token: str = answered.json()["AccessToken"]
    return token


def row(harness: Harness, item_key: str) -> models.ItemUserData | None:
    with harness.app.state.sessions.begin() as opened:
        return opened.get(models.ItemUserData, (harness.world.everyone.id, item_key))


async def playing(client: httpx.AsyncClient, token: str, item_id: str, position: int) -> None:
    headers = {"X-Emby-Token": token}
    await client.post(
        "/Sessions/Playing", json={"ItemId": item_id, "PositionTicks": 0}, headers=headers
    )
    await client.post(
        "/Sessions/Playing/Progress",
        json={"ItemId": item_id, "PositionTicks": position},
        headers=headers,
    )


# ------------------------------------------------------------------------------------------
# AC-15
# ------------------------------------------------------------------------------------------


async def test_ac15_a_silent_session_is_reaped_and_keeps_the_viewers_place(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    world, clocks = harness.world, harness.clocks
    token = await log_in(client, world.everyone.name)
    reported = RUNTIME_TICKS * 40 // 100
    await playing(client, token, world.corpus[1], reported)

    clocks.advance(SILENCE_THRESHOLD.total_seconds() + 60)
    assert harness.app.state.playing.sweep() == 1

    entries = (await client.get("/Sessions", headers={"X-Emby-Token": token})).json()
    assert all("NowPlayingItem" not in one for one in entries), "the session is still playing"

    stored = row(harness, world.corpus[1])
    assert stored is not None
    assert stored.playback_position_ticks == reported + 360 * TICKS_PER_SECOND, (
        "the committed position is the last reported one, not the one the viewer was at"
    )


async def test_the_reaped_position_resolves_through_the_same_rule(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """A session silent long enough to drift past the ceiling is *played*, not resumable - the
    reaped stop goes through section 3.7 like any other."""
    world, clocks = harness.world, harness.clocks
    token = await log_in(client, world.everyone.name)
    await playing(client, token, world.corpus[1], RUNTIME_TICKS * 88 // 100)

    clocks.advance(600)
    harness.app.state.playing.sweep()

    stored = row(harness, world.corpus[1])
    assert stored is not None
    assert (stored.played, stored.playback_position_ticks) == (True, 0)


async def test_a_paused_session_is_reaped_at_the_position_it_paused_at(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    world, clocks = harness.world, harness.clocks
    token = await log_in(client, world.everyone.name)
    paused_at = RUNTIME_TICKS * 30 // 100
    await client.post(
        "/Sessions/Playing",
        json={"ItemId": world.corpus[1], "PositionTicks": 0},
        headers={"X-Emby-Token": token},
    )
    await client.post(
        "/Sessions/Playing/Progress",
        json={"ItemId": world.corpus[1], "PositionTicks": paused_at, "IsPaused": True},
        headers={"X-Emby-Token": token},
    )

    clocks.advance(3600)
    harness.app.state.playing.sweep()

    stored = row(harness, world.corpus[1])
    assert stored is not None and stored.playback_position_ticks == paused_at


async def test_the_reap_and_an_explicit_stop_agree(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """The risk plan section 9 names: two paths to one outcome that drift apart. They are one
    function, and this is what says so - the same position, reaped and reported, lands the same."""
    world, clocks = harness.world, harness.clocks
    token = await log_in(client, world.everyone.name)
    position = RUNTIME_TICKS * 50 // 100

    await playing(client, token, world.corpus[1], position)
    clocks.advance(600)
    harness.app.state.playing.sweep()
    reaped = row(harness, world.corpus[1])
    assert reaped is not None
    committed = reaped.playback_position_ticks

    await client.delete(f"/UserPlayedItems/{world.corpus[1]}", headers={"X-Emby-Token": token})
    await client.post(
        "/Sessions/Playing/Stopped",
        json={"ItemId": world.corpus[1], "PositionTicks": committed},
        headers={"X-Emby-Token": token},
    )
    stopped = row(harness, world.corpus[1])
    assert stopped is not None
    assert (stopped.played, stopped.playback_position_ticks) == (
        reaped.played,
        reaped.playback_position_ticks,
    )


async def test_a_session_that_is_still_reporting_is_left_alone(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    world, clocks = harness.world, harness.clocks
    token = await log_in(client, world.everyone.name)
    await playing(client, token, world.corpus[1], RUNTIME_TICKS // 4)

    clocks.advance(240)
    assert harness.app.state.playing.sweep() == 0
    entries = (await client.get("/Sessions", headers={"X-Emby-Token": token})).json()
    assert any("NowPlayingItem" in one for one in entries)


async def test_a_reap_for_a_session_that_no_longer_exists_is_not_an_error(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """A device that logged out mid-playback: the registry still holds a record and the row it
    would be written against belongs to nobody. The commit finds no session and stops."""
    world, clocks = harness.world, harness.clocks
    token = await log_in(client, world.everyone.name)
    await playing(client, token, world.corpus[1], RUNTIME_TICKS // 4)

    with harness.app.state.sessions.begin() as opened:
        opened.query(models.Session).delete()

    clocks.advance(600)
    assert harness.app.state.playing.sweep() == 1
