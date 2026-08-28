# SPDX-License-Identifier: GPL-3.0-or-later
"""The three reports: `204` from all of them, and what each one does to the stored row.

The rule itself is proven in `test_domain_playstate.py`, against pure functions and a table. What
is proven here is the **wiring**: that a progress and a stop reach the same rule, that a start
counts the play and clears `Played`, that a positionless stop counts a second time, and that the
error floor sits exactly where the probe measured it - after the body binds, and nowhere else.

The branch table at the bottom runs one item per branch, which the world can only supply since
T4 gave it three runtime shapes: an hour-long film, a 215-second track, and episodes with no
runtime at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from atrium.api.deps import require_user
from atrium.config.paths import DataPaths
from atrium.db import models
from atrium.domain.playstate import TICKS_PER_SECOND
from atrium.domain.user import User
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import (
    EPISODE_RUNTIME_TICKS,
    RUNTIME_TICKS,
    SHORT_RUNTIME_TICKS,
    QueryWorld,
    build_query_world,
)

START = "/Sessions/Playing"
PROGRESS = "/Sessions/Playing/Progress"
STOPPED = "/Sessions/Playing/Stopped"


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    built.state.readiness.mark_ready()
    with built.state.sessions.begin() as opened:
        world = build_query_world(opened)
    yield Harness(app=built, world=world)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
def world(harness: Harness) -> QueryWorld:
    return harness.world


@pytest.fixture
def app(harness: Harness) -> FastAPI:
    harness.app.dependency_overrides[require_user] = lambda: harness.world.everyone
    return harness.app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened


def row(harness: Harness, item_key: str, user: User | None = None) -> models.ItemUserData | None:
    target = user or harness.world.everyone
    with harness.app.state.sessions.begin() as opened:
        return opened.get(models.ItemUserData, (target.id, item_key))


def film(world: QueryWorld) -> str:
    """The one item with both a runtime and a seeded resume position."""
    return world.resumable[0]


def ticks(percent: float, runtime: int = RUNTIME_TICKS) -> int:
    return int(runtime * percent / 100)


# ------------------------------------------------------------------------------------------
# AC-8, AC-9, AC-11: the answers
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [START, PROGRESS, STOPPED])
async def test_ac8_every_report_answers_204_with_an_empty_body(
    client: httpx.AsyncClient, world: QueryWorld, path: str
) -> None:
    answered = await client.post(path, json={"ItemId": film(world), "PositionTicks": ticks(30)})
    assert answered.status_code == 204
    assert answered.content == b""


@pytest.mark.parametrize("path", [START, PROGRESS, STOPPED])
async def test_ac11_a_report_for_an_unknown_item_is_204_and_writes_nothing(
    harness: Harness, client: httpx.AsyncClient, path: str
) -> None:
    """A report for an item removed mid-playback is not worth failing; the client could not act
    on the failure anyway."""
    ghost = "a" * 32
    answered = await client.post(path, json={"ItemId": ghost, "PositionTicks": 1000})
    assert answered.status_code == 204
    assert row(harness, ghost) is None


@pytest.mark.parametrize("path", [START, PROGRESS, STOPPED])
async def test_a_report_with_no_item_at_all_is_204(client: httpx.AsyncClient, path: str) -> None:
    """`ItemId` binds as optional, so an absent one skips rather than refusing - which is the
    difference between a body that does not bind and a body that says nothing."""
    assert (await client.post(path, json={})).status_code == 204


async def test_ac9_a_progress_without_a_media_source_or_a_start_still_lands(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Emby requires `MediaSourceId` here and Jellyfin does not: a server that refused without it
    would silently lose the resume positions of every Jellyfin-dialect client."""
    item_id = world.corpus[1]
    await client.post(PROGRESS, json={"ItemId": item_id, "PositionTicks": ticks(20)})
    stored = row(harness, item_id)
    assert stored is not None and stored.playback_position_ticks == ticks(20)


# ------------------------------------------------------------------------------------------
# AC-17, AC-18, AC-19, AC-10: the effects
# ------------------------------------------------------------------------------------------


async def test_ac17_a_start_counts_the_play_sets_the_date_and_clears_played(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    watched = world.series[0].watched
    before = row(harness, watched)
    assert before is not None and before.played and before.play_count == 1

    await client.post(START, json={"ItemId": watched, "PositionTicks": 0})
    after = row(harness, watched)
    assert after is not None
    assert (after.played, after.play_count) == (False, 2)
    assert after.last_played_date is not None and after.last_played_date > before.last_played_date


async def test_a_start_does_not_write_the_position_it_carries(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Measured: a `Start` at 30% leaves the stored position alone. The seeded film is *already*
    resumable, which is the case that matters - a client restarting playback from the beginning
    must not destroy the point it is about to seek to."""
    item_id = world.resumable[1]
    before = row(harness, item_id)
    assert before is not None and before.playback_position_ticks > 0

    await client.post(START, json={"ItemId": item_id, "PositionTicks": ticks(30)})
    after = row(harness, item_id)
    assert after is not None
    assert after.playback_position_ticks == before.playback_position_ticks


async def test_ac18_a_stop_with_a_position_does_not_count_and_one_without_counts_again(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[1]
    await client.post(START, json={"ItemId": item_id})
    await client.post(STOPPED, json={"ItemId": item_id, "PositionTicks": ticks(50)})
    assert row(harness, item_id).play_count == 1

    await client.post(STOPPED, json={"ItemId": item_id})
    ended = row(harness, item_id)
    assert (ended.play_count, ended.played, ended.playback_position_ticks) == (2, True, 0)


async def test_ac19_a_progress_past_the_ceiling_marks_played_mid_playback(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[1]
    await client.post(START, json={"ItemId": item_id})
    await client.post(PROGRESS, json={"ItemId": item_id, "PositionTicks": ticks(95)})
    stored = row(harness, item_id)
    assert (stored.played, stored.playback_position_ticks) == (True, 0)


async def test_ac10_a_later_report_carrying_an_older_position_rewinds_it(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Last writer wins: a deliberate seek backwards arrives as exactly this report."""
    item_id = world.corpus[1]
    await client.post(PROGRESS, json={"ItemId": item_id, "PositionTicks": ticks(40)})
    await client.post(PROGRESS, json={"ItemId": item_id, "PositionTicks": ticks(20)})
    assert row(harness, item_id).playback_position_ticks == ticks(20)


async def test_a_progress_carrying_no_position_leaves_the_stored_one_alone(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """What a pause report looks like: it says the session is paused and says nothing about
    where. Reading a missing position as zero would send every pausing client back to the start."""
    item_id = world.corpus[1]
    await client.post(PROGRESS, json={"ItemId": item_id, "PositionTicks": ticks(40)})
    await client.post(PROGRESS, json={"ItemId": item_id, "IsPaused": True})
    assert row(harness, item_id).playback_position_ticks == ticks(40)


async def test_ac14_a_failed_stop_records_nothing_and_the_start_keeps_its_effects(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The draft's "a playback that never started is not progress" was half right: the stop is
    inert, and the start already happened."""
    item_id = world.corpus[1]
    await client.delete(f"/UserPlayedItems/{item_id}")
    await client.post(START, json={"ItemId": item_id})
    await client.post(STOPPED, json={"ItemId": item_id, "PositionTicks": ticks(50), "Failed": True})
    stored = row(harness, item_id)
    assert (stored.play_count, stored.played) == (1, False)
    assert stored.playback_position_ticks == 0, "the failed stop wrote its position"
    assert stored.last_played_date is not None, "the start's date went with the failed stop"


# ------------------------------------------------------------------------------------------
# AC-12 at the wire: one item per branch of the rule
# ------------------------------------------------------------------------------------------


def branches(world: QueryWorld) -> list[tuple[str, str, int | None, bool, int]]:
    """`(name, item, reported position, expected played, expected stored position)`."""
    episode = world.series[1].episodes[0]  # the series with no runtimes at all
    return [
        ("no position at all", world.corpus[1], None, True, 0),
        ("the runtime is unknown", episode, EPISODE_RUNTIME_TICKS // 2, True, 0),
        ("below the floor", world.corpus[1], ticks(2), False, 0),
        ("above the ceiling", world.corpus[1], ticks(95), True, 0),
        (
            "within one second of the end",
            world.corpus[1],
            RUNTIME_TICKS - TICKS_PER_SECOND,
            True,
            0,
        ),
        (
            "a short item stopped mid-way",
            world.short_track,
            SHORT_RUNTIME_TICKS // 2,
            True,
            0,
        ),
        ("the resumable case", world.corpus[1], ticks(50), False, ticks(50)),
    ]


async def test_ac12_every_branch_of_the_rule_reaches_the_wire(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    for name, item_id, position, played, stored_position in branches(world):
        await client.delete(f"/UserPlayedItems/{item_id}")
        body: dict[str, Any] = {"ItemId": item_id}
        if position is not None:
            body["PositionTicks"] = position
        assert (await client.post(STOPPED, json=body)).status_code == 204

        stored = row(harness, item_id)
        assert stored is not None, f"{name}: nothing was written"
        assert stored.played is played, f"{name}: Played is {stored.played}"
        assert stored.playback_position_ticks == stored_position, f"{name}: wrong position"


async def test_the_same_rule_runs_on_a_progress(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """The one branch that is stop-only is "no position at all"; everything else is shared, and
    a table that only ever posted to `/Stopped` would not notice if it were not."""
    for _name, item_id, position, played, stored_position in branches(world):
        if position is None:
            continue
        await client.delete(f"/UserPlayedItems/{item_id}")
        await client.post(PROGRESS, json={"ItemId": item_id, "PositionTicks": position})
        stored = row(harness, item_id)
        assert stored is not None
        assert (stored.played, stored.playback_position_ticks) == (played, stored_position)


# ------------------------------------------------------------------------------------------
# AC-21: the error floor, where the probe measured it
# ------------------------------------------------------------------------------------------


async def test_ac21_a_stop_with_a_negative_position_is_the_text_plain_400(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    item_id = world.corpus[30]  # nothing seeded, so "no row" is a real assertion
    answered = await client.post(STOPPED, json={"ItemId": item_id, "PositionTicks": -1})
    assert answered.status_code == 400
    assert answered.headers["content-type"] == "text/plain"
    assert answered.content == b"Error processing request."
    assert row(harness, item_id) is None, "the refusal wrote a row on its way out"


@pytest.mark.parametrize("path", [START, PROGRESS, STOPPED])
async def test_ac21_a_body_that_is_not_json_is_the_validation_400(
    client: httpx.AsyncClient, path: str
) -> None:
    answered = await client.post(
        path, content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert answered.status_code == 400
    body = answered.json()
    assert body["title"] == "One or more validation errors occurred."
    # The keys are the reference's; the `$` *message* is this parser's, and the divergence is
    # recorded rather than faked - reproducing .NET's byte-position sentence would be theatre.
    assert set(body["errors"]) == {
        "$",
        {START: "playbackStartInfo", PROGRESS: "playbackProgressInfo", STOPPED: "playbackStopInfo"}[
            path
        ],
    }


@pytest.mark.parametrize("path", [START, PROGRESS, STOPPED])
async def test_ac21_an_item_id_that_is_not_a_guid_is_the_validation_400(
    client: httpx.AsyncClient, path: str
) -> None:
    """Leniency starts *after* the body binds, which is the whole of the floor: a well-formed id
    naming nothing is `204`, and a string that is not an id at all is `400`."""
    answered = await client.post(path, json={"ItemId": "banana", "PositionTicks": 1000})
    assert answered.status_code == 400
    parameter = {
        START: "playbackStartInfo",
        PROGRESS: "playbackProgressInfo",
        STOPPED: "playbackStopInfo",
    }[path]
    assert answered.json()["errors"] == {
        "": ["The supplied value is invalid."],
        parameter: [f"The {parameter} field is required."],
    }


async def test_no_token_is_the_empty_401(harness: Harness) -> None:
    harness.app.dependency_overrides.clear()
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        answered = await opened.post(START, json={"ItemId": "a" * 32})
    assert answered.status_code == 401
    assert answered.content == b""


async def test_an_unknown_property_in_the_body_is_ignored(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """behaviours section 1.12's lenient direction: a client sending a property this server does
    not know about is a client on a newer dialect, not a client to refuse."""
    item_id = world.corpus[1]
    answered = await client.post(
        PROGRESS,
        json={
            "ItemId": item_id,
            "PositionTicks": ticks(50),
            "NowPlayingQueue": [],
            "Brightness": 3,
        },
    )
    assert answered.status_code == 204
    assert row(harness, item_id).playback_position_ticks == ticks(50)


async def test_a_report_for_an_invisible_item_is_204_rather_than_404(
    harness: Harness, client: httpx.AsyncClient, world: QueryWorld
) -> None:
    """Rule 1 covers "the caller cannot see it" as much as "it does not exist" - the report path
    never tells a client anything about an item, which is the mark routes' 404 seen from the
    other side."""
    harness.app.dependency_overrides[require_user] = lambda: world.restricted
    answered = await client.post(
        STOPPED, json={"ItemId": world.series[0].episodes[0], "PositionTicks": 1000}
    )
    assert answered.status_code == 204
    assert row(harness, world.series[0].episodes[0], world.restricted) is None
