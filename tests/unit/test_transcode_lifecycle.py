# SPDX-License-Identifier: GPL-3.0-or-later
"""The kill paths: a stop that stops, a timer that reaps, and scratch that dies with its session.

Everything here is asserted **below the transport**, because the claims are about processes and
directories rather than about response bodies. `tests/conformance/test_progressive_delivery.py`
found the reason at 008 T7: httpx's ASGI transport drives the application to completion and hands
back a buffered body, so a test that watched a response could not tell an encoder that stopped
from one that finished. What is watched here instead is the real thing - a real child process's
exit code, a real directory's absence, and the ledger the server keeps of both.

**The processes are real and are not ffmpeg.** `ProductionLedger` takes an argument vector and
does not care what it launches, so a session's encoder here is a Python interpreter asleep for
five minutes: a kill is a kill, and the assertion "the process this session owned is gone" is the
same assertion either way. That keeps this file out of the `ffmpeg` marker, which matters because
the kill paths are the part of 008 an operator's server exercises most and CI without ffmpeg
would otherwise never run them.

**No test here sleeps.** The manager's clock is injected, so a minute of idleness is one
assignment.

Every expected value is `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11,
2026-08-29]`, whose kill battery measured the timer, the two refusals, what the stop route keys
on, and what `/Sessions` carries while and after a transcode.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db.repositories import UserRepository
from atrium.media import ffmpeg
from atrium.media.decision import Decision, Outcome, StreamAction, StreamPlan
from atrium.media.sessions import (
    PING_TIMEOUT_SECONDS,
    SessionKey,
    TranscodeManager,
    TranscodeSession,
    TranscodingReport,
)
from atrium.server import create_app
from tests.conftest import data_dir
from tests.fixtures.query import QueryWorld, build_query_world

PASSWORD = "correct horse battery staple"
DEVICE_ID = "bench-1"
CLIENT_HEADER = (
    f'MediaBrowser Client="Atrium Test", Device="Bench", DeviceId="{DEVICE_ID}", Version="1"'
)

#: A process that will not end on its own inside a test. Stands in for an encoder producing a
#: film: what is asserted about it is that something else ended it.
SLEEPER = (sys.executable, "-c", "import time; time.sleep(300)")

#: More than any pipe buffer this runs on. The hazard `drain` exists for.
SHOUTED_BYTES = 512 * 1024

#: The negotiated answer a session reports, in the shape `/Sessions` states it: an h264/aac
#: re-encode of a 1920x816 source, which is the measured session the probe watched.
NEGOTIATED = Decision(
    outcome=Outcome.TRANSCODE,
    reasons=("ContainerNotSupported", "VideoCodecNotSupported", "AudioCodecNotSupported"),
    container="ts",
    sub_protocol="hls",
    video=StreamPlan(
        source_index=0,
        action=StreamAction.ENCODE,
        codec="h264",
        width=1920,
        height=816,
        bitrate=8_000_000,
    ),
    audio=StreamPlan(
        source_index=1,
        action=StreamAction.ENCODE,
        codec="aac",
        channels=6,
        bitrate=678_663,
    ),
    supports_transcoding=True,
)


class Clock:
    """The manager's monotonic clock, stepped by hand."""

    def __init__(self) -> None:
        self.elapsed = 1000.0

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds

    def __call__(self) -> float:
        return self.elapsed


@dataclass(frozen=True)
class Harness:
    app: FastAPI
    world: QueryWorld
    paths: DataPaths
    clock: Clock

    @property
    def manager(self) -> TranscodeManager:
        found: TranscodeManager = self.app.state.transcodes
        return found

    @property
    def ledger(self) -> ffmpeg.ProductionLedger:
        found: ffmpeg.ProductionLedger = self.app.state.productions
        return found


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
    clock = Clock()
    # The manager the factory built, with its clock replaced: the kill timer *is* the passage of
    # time, so the test owns the passing. 007's session reaper is stepped the same way.
    built.state.transcodes._clock = clock
    yield Harness(app=built, world=world, paths=paths, clock=clock)
    built.dependency_overrides.clear()
    built.state.db.dispose()


@pytest.fixture
async def client(harness: Harness) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=harness.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://atrium:8096") as opened:
        yield opened
    await harness.manager.shutdown()
    await harness.ledger.shutdown()


async def log_in(client: httpx.AsyncClient, name: str) -> str:
    answered = await client.post(
        "/Users/AuthenticateByName",
        json={"Username": name, "Pw": PASSWORD},
        headers={"X-Emby-Authorization": CLIENT_HEADER},
    )
    assert answered.status_code == 200, answered.text
    token: str = answered.json()["AccessToken"]
    return token


async def planted(
    harness: Harness,
    *,
    play_session_id: str,
    device_id: str = DEVICE_ID,
    media_path: str = "/library/film.mkv",
) -> TranscodeSession:
    """One live session: a running process, a scratch directory with a segment in it, a report.

    Built through `obtain` and the ledger, which are the two things the segment route uses, so
    what the kill paths are asked to end is shaped like what they will really meet.
    """
    session = harness.manager.obtain(
        SessionKey(device_id=device_id, play_session_id=play_session_id, media_path=media_path)
    )
    session.scratch.mkdir(parents=True, exist_ok=True)
    (session.scratch / "0.ts").write_bytes(b"a produced segment")
    session.running = await harness.ledger.start(SLEEPER, to_pipe=False)
    session.report = TranscodingReport.of(NEGOTIATED, "ts")
    return session


def remux_output(harness: Harness) -> Path:
    """A produced remux, which lives in the scratch **root** and belongs to no session.

    Named the way `api/delivery.py` names one: a digest of the command and the file's change
    signal, with the container as its extension. It is here because spec section 3.4 makes a
    remux byte-identical for everyone who asks for it, so it is deliberately shared - and a stop
    that took the root instead of one directory would throw away another viewer's work.
    """
    settled = harness.paths.transcodes / f"{'b' * 32}.mp4"
    settled.parent.mkdir(parents=True, exist_ok=True)
    settled.write_bytes(b"a remuxed film")
    return settled


async def stopped(session: TranscodeSession) -> bool:
    """Whether the process this session owned has really exited."""
    running = session.running
    if running is None:
        return True
    await asyncio.wait_for(running.process.wait(), timeout=10)
    return running.process.returncode is not None


# ------------------------------------------------------------------------------------------
# The hazard T11 left, which every path below depends on not existing
# ------------------------------------------------------------------------------------------


async def test_a_process_that_fills_the_diagnostic_pipe_still_exits(
    harness: Harness,
) -> None:
    """A ledger that started processes with an unread `stderr=PIPE` would hang here for ever.

    Not a hypothetical: a pipe has a buffer of tens of kilobytes and a process blocked writing
    into a full one never reaches its own exit. At `-loglevel error` a healthy encode says
    nothing, which is why three tasks shipped over this - it takes an encode that goes *badly*,
    for the length of a film, to fill it. The timeout is what makes the assertion a test rather
    than a hang.

    **The half-megabyte arrives with no newline in it on purpose.** The first drain read by
    line, and a line reader refuses one longer than its stream's limit and stops reading from
    that moment on - the same hang with more code, which this hung against. The second assertion
    is the same test from the other side, and it caught the second version: the words have to
    survive `finish`, which is where they are logged, and a `finish` that cancelled the reader
    rather than waiting for it lost them on a machine slower than the one it was written on.
    """
    noisy = await harness.ledger.start(
        (sys.executable, "-c", f"import sys; sys.stderr.write('x' * {SHOUTED_BYTES})"),
        to_pipe=False,
    )
    await asyncio.wait_for(noisy.process.wait(), timeout=10)
    assert noisy.process.returncode == 0

    await harness.ledger.finish(noisy)
    assert noisy.complaints, "the encoder's last words were read but not kept"
    assert set("".join(noisy.complaints)) == {"x"}
    assert sum(len(one) for one in noisy.complaints) < SHOUTED_BYTES, (
        "the whole shout was kept; a bounded tail is the point"
    )


# ------------------------------------------------------------------------------------------
# AC-25: the stop route stops the named session, and only it
# ------------------------------------------------------------------------------------------


async def test_ac25_the_stop_route_kills_exactly_the_named_session(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    token = await log_in(client, harness.world.everyone.name)
    doomed = await planted(harness, play_session_id=new_id())
    survivor = await planted(harness, play_session_id=new_id(), media_path="/library/other.mkv")

    answered = await client.delete(
        "/Videos/ActiveEncodings",
        params={"deviceId": DEVICE_ID, "playSessionId": doomed.key.play_session_id},
        headers={"X-Emby-Token": token},
    )

    assert (answered.status_code, answered.content) == (204, b"")
    assert await stopped(doomed)
    assert not doomed.scratch.exists(), "the stopped session's scratch was not reclaimed"
    assert survivor.running is not None and survivor.running.process.returncode is None
    assert (survivor.scratch / "0.ts").exists(), "a session nobody named lost its work"
    assert harness.manager.sessions == (survivor,)


async def test_a_stop_leaves_the_remux_beside_it_alone(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """The scratch root holds more than sessions, and only one of the two is session-scoped."""
    token = await log_in(client, harness.world.everyone.name)
    shared = remux_output(harness)
    doomed = await planted(harness, play_session_id=new_id())

    await client.delete(
        "/Videos/ActiveEncodings",
        params={"deviceId": DEVICE_ID, "playSessionId": doomed.key.play_session_id},
        headers={"X-Emby-Token": token},
    )

    assert not doomed.scratch.exists()
    assert shared.read_bytes() == b"a remuxed film", (
        "the stop took a remux that belongs to no session with it"
    )


async def test_the_device_the_stop_route_was_given_decides_nothing(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """Measured, and the opposite of what the plan's own signature said.

    The reference selects the jobs to kill by `playSessionId` whenever one was given, so a client
    that spells its device differently between the negotiation and the stop still stops its work.
    A manager that had required both to match would leak an encoder for exactly that client.
    """
    token = await log_in(client, harness.world.everyone.name)
    doomed = await planted(harness, play_session_id=new_id())

    answered = await client.delete(
        "/Videos/ActiveEncodings",
        params={
            "deviceId": "a-device-this-server-has-never-seen",
            "playSessionId": doomed.key.play_session_id,
        },
        headers={"X-Emby-Token": token},
    )

    assert answered.status_code == 204
    assert await stopped(doomed)
    assert harness.manager.sessions == ()


async def test_a_play_session_nothing_issued_is_a_no_op_204(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    token = await log_in(client, harness.world.everyone.name)
    live = await planted(harness, play_session_id=new_id())

    answered = await client.delete(
        "/Videos/ActiveEncodings",
        params={"deviceId": DEVICE_ID, "playSessionId": new_id()},
        headers={"X-Emby-Token": token},
    )

    assert answered.status_code == 204
    assert live.running is not None and live.running.process.returncode is None
    assert harness.manager.sessions == (live,)


async def test_ac30_a_play_session_id_from_a_negotiation_is_accepted(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """The identifier `PlaybackInfo` mints survives to the route that ends the work.

    Minted here by the same function the negotiation calls, and then used as the delivery routes
    use it - as one third of the manager's session key - so what is proven is the round trip
    rather than that a string can be put in a query parameter.
    """
    token = await log_in(client, harness.world.everyone.name)
    negotiated = new_id()
    session = await planted(harness, play_session_id=negotiated)
    assert harness.manager.sessions == (session,)

    answered = await client.delete(
        "/Videos/ActiveEncodings",
        params={"deviceId": DEVICE_ID, "playSessionId": negotiated},
        headers={"X-Emby-Token": token},
    )

    assert answered.status_code == 204
    assert harness.manager.sessions == ()


# ------------------------------------------------------------------------------------------
# What it refuses
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sent", "named"),
    [
        ({"deviceId": DEVICE_ID}, "playSessionId"),
        ({"playSessionId": "aaaa"}, "deviceId"),
    ],
)
async def test_a_missing_parameter_is_the_validation_400_naming_it(
    harness: Harness, client: httpx.AsyncClient, sent: dict[str, str], named: str
) -> None:
    token = await log_in(client, harness.world.everyone.name)
    answered = await client.delete(
        "/Videos/ActiveEncodings", params=sent, headers={"X-Emby-Token": token}
    )
    assert answered.status_code == 400
    assert named in answered.json()["errors"]


async def test_both_missing_names_both(harness: Harness, client: httpx.AsyncClient) -> None:
    token = await log_in(client, harness.world.everyone.name)
    answered = await client.delete("/Videos/ActiveEncodings", headers={"X-Emby-Token": token})
    assert answered.status_code == 400
    assert {"deviceId", "playSessionId"} <= set(answered.json()["errors"])


async def test_the_stop_route_requires_a_token(client: httpx.AsyncClient) -> None:
    """Unlike the four `stream` routes and like the three HLS ones (behaviours section 2.10)."""
    answered = await client.delete(
        "/Videos/ActiveEncodings",
        params={"deviceId": DEVICE_ID, "playSessionId": new_id()},
    )
    assert (answered.status_code, answered.content) == (401, b"")


# ------------------------------------------------------------------------------------------
# AC-26's server half and AC-29: the kill timer, and the scratch that goes with it
# ------------------------------------------------------------------------------------------


async def test_ac29_a_session_unpinged_past_the_timeout_dies_with_its_scratch(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    forgotten = await planted(harness, play_session_id=new_id())

    harness.clock.advance(PING_TIMEOUT_SECONDS + 1)
    assert await harness.manager.sweep() == 1

    assert await stopped(forgotten)
    assert not forgotten.scratch.exists()
    assert harness.manager.sessions == ()


async def test_a_session_pinged_inside_the_timeout_survives_the_sweep(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """The timer is a minute because the job is not progressive, and a second is not a minute."""
    watched = await planted(harness, play_session_id=new_id())

    harness.clock.advance(PING_TIMEOUT_SECONDS - 1)
    assert await harness.manager.sweep() == 0
    assert harness.manager.sessions == (watched,)

    # A request arrives, and the minute starts again from there.
    harness.manager.ping(watched)
    harness.clock.advance(PING_TIMEOUT_SECONDS - 1)
    assert await harness.manager.sweep() == 0
    assert watched.running is not None and watched.running.process.returncode is None


async def test_the_sweep_leaves_a_remux_alone(harness: Harness, client: httpx.AsyncClient) -> None:
    shared = remux_output(harness)
    await planted(harness, play_session_id=new_id())

    harness.clock.advance(PING_TIMEOUT_SECONDS + 1)
    await harness.manager.sweep()

    assert shared.exists(), "the kill timer reclaimed a file no session owns"


# ------------------------------------------------------------------------------------------
# AC-29's other half: shutdown and startup clear the root
# ------------------------------------------------------------------------------------------


async def test_shutdown_stops_everything_and_leaves_the_scratch_root_empty(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    remux_output(harness)
    running = await planted(harness, play_session_id=new_id())

    await harness.manager.shutdown()

    assert await stopped(running)
    assert list(harness.paths.transcodes.iterdir()) == []
    assert harness.manager.sessions == ()


async def test_an_orphan_a_crash_left_behind_is_cleared_at_startup(tmp_path: Path) -> None:
    """Driven through the application's own lifespan, because "at startup" is the claim.

    A crash leaves both shapes behind and neither is reachable again: a session directory is
    named for a play session id no client will send twice, and a remux file for a change signal
    a restart has no reason to reproduce.
    """
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_app(paths)
    orphan_directory = paths.transcodes / ("c" * 32)
    orphan_directory.mkdir(parents=True)
    (orphan_directory / "17.ts").write_bytes(b"half a segment")
    (paths.transcodes / f"{'d' * 32}.mp4").write_bytes(b"an abandoned remux")

    async with built.router.lifespan_context(built):
        assert list(paths.transcodes.iterdir()) == [], (
            "the scratch root still holds what the last run left"
        )
    built.state.db.dispose()


# ------------------------------------------------------------------------------------------
# `/Sessions` while a transcode runs, and after it stops
# ------------------------------------------------------------------------------------------


async def test_sessions_carries_the_measured_transcoding_info_and_loses_it_on_a_stop(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """Eleven properties in the reference's order, and absent rather than null when idle.

    The two the reference has and this does not - `Framerate` and `CompletionPercentage` - are
    the two it reads out of the encoder's progress output, which Atrium does not parse. The
    measured object drops exactly those two the moment a job stops, so this shape is one the
    reference sends (behaviours section 3.11).
    """
    token = await log_in(client, harness.world.everyone.name)
    headers = {"X-Emby-Token": token}

    idle = (await client.get("/Sessions", headers=headers)).json()
    assert all("TranscodingInfo" not in one for one in idle), "an idle session claims a transcode"

    session = await planted(harness, play_session_id=new_id())
    entries = (await client.get("/Sessions", headers=headers)).json()
    mine = [one for one in entries if one["DeviceId"] == DEVICE_ID]
    assert len(mine) == 1
    info = mine[0]["TranscodingInfo"]

    assert list(info) == [
        "AudioCodec",
        "VideoCodec",
        "Container",
        "IsVideoDirect",
        "IsAudioDirect",
        "Bitrate",
        "Width",
        "Height",
        "AudioChannels",
        "HardwareAccelerationType",
        "TranscodeReasons",
    ]
    assert info == {
        "AudioCodec": "aac",
        "VideoCodec": "h264",
        "Container": "ts",
        "IsVideoDirect": False,
        "IsAudioDirect": False,
        "Bitrate": 8_678_663,
        "Width": 1920,
        "Height": 816,
        "AudioChannels": 6,
        "HardwareAccelerationType": "none",
        "TranscodeReasons": [
            "ContainerNotSupported",
            "VideoCodecNotSupported",
            "AudioCodecNotSupported",
        ],
    }
    assert list(mine[0]).index("TranscodingInfo") == list(mine[0]).index("ApplicationVersion") + 1

    await client.delete(
        "/Videos/ActiveEncodings",
        params={"deviceId": DEVICE_ID, "playSessionId": session.key.play_session_id},
        headers=headers,
    )
    after = (await client.get("/Sessions", headers=headers)).json()
    assert all("TranscodingInfo" not in one for one in after), (
        "the session still claims a transcode after the work was stopped"
    )


async def test_a_delivery_request_with_no_device_reports_on_nobody(
    harness: Harness, client: httpx.AsyncClient
) -> None:
    """The reference's own guard: it hangs no report at all on a blank device id.

    A delivery route may be reached with no `deviceId` in its query, and the session it creates
    is keyed on the empty string. Matching that against every stored session that also has no
    device would put one viewer's transcode on another viewer's row.
    """
    token = await log_in(client, harness.world.everyone.name)
    await planted(harness, play_session_id=new_id(), device_id="")

    entries = (await client.get("/Sessions", headers={"X-Emby-Token": token})).json()
    assert all("TranscodingInfo" not in one for one in entries)
    assert harness.manager.reporting("") is None
