# SPDX-License-Identifier: GPL-3.0-or-later
"""The operator's four knobs, and what a denied account is refused at delivery.

Three claims, and the middle one is the reason this file exists rather than a couple of extra
cases in `test_transcode_lifecycle.py`:

* **Throttling pauses production and lets it go again.** Asserted on a real child process that
  really stops writing - a boolean on a dataclass would have passed against a signal that was
  never sent.
* **Segment deletion is keyed on the client's position, not on the clock.** The task list, the
  spec and the plan all said "aged" segments; the reference deletes the segments lying a whole
  keep-window *behind the furthest segment the client has fetched*, and deletes nothing at all
  until the client has fetched past that window. The measured row is reproduced exactly: a
  720-second window, a download position of 811 seconds, segment 29 gone and segment 33 still
  there `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`.
* **Both are off as shipped**, asserted against the settings a server with no `config.toml`
  loads rather than against the manager's own argument defaults.

**The producer is real and is not ffmpeg**, for `test_transcode_lifecycle.py`'s reason: a
`SIGSTOP` stops any process, and what is asserted here - the produced files stop appearing, and
start appearing again - is the same assertion whichever binary is writing them. That keeps the
throttle out of the `ffmpeg` marker, which matters because the knobs are the part of this
feature an operator is most likely to have turned on.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from atrium.config.paths import DataPaths
from atrium.config.settings import Settings
from atrium.config.settings import load as load_settings
from atrium.media import ffmpeg, hls
from atrium.media.decision import (
    NOTHING_PLAYABLE,
    Decision,
    Outcome,
    PlaybackPolicy,
    StreamAction,
    StreamPlan,
    refused_by_policy,
)
from atrium.media.sessions import (
    SEGMENT_KEEP_FLOOR_SECONDS,
    THROTTLE_FLOOR_SECONDS,
    SegmentPlan,
    SessionKey,
    TranscodeManager,
    TranscodeSession,
)
from atrium.server import create_app
from tests.conftest import FAST_PASSWORDS

#: The fixture film's grid: three-second segments, which is what both knobs count in.
SEGMENT_SECONDS = 3
CADENCE_TICKS = SEGMENT_SECONDS * hls.TICKS_PER_SECOND

#: The measured row, reproduced. A client whose furthest segment ended 811 seconds in, against a
#: 720-second window, leaves the boundary at `(811 - 720) // 3`.
MEASURED_DOWNLOAD_SECONDS = 811
MEASURED_KEEP_SECONDS = 720
MEASURED_BOUNDARY = (MEASURED_DOWNLOAD_SECONDS - MEASURED_KEEP_SECONDS) // SEGMENT_SECONDS

#: A producer that writes one segment file every twenty milliseconds, for ever. Stopping it is
#: observable as the highest-numbered file it has written standing still.
PRODUCER = (
    "import pathlib, sys, time\n"
    "directory = pathlib.Path(sys.argv[1])\n"
    "index = int(sys.argv[2])\n"
    "while True:\n"
    "    (directory / ('%d.ts' % index)).write_bytes(b'segment')\n"
    "    index += 1\n"
    "    time.sleep(0.02)\n"
)

#: How long the test watches a suspended producer before believing it. Two orders of magnitude
#: above the producer's own tick, so a pass is not a race that happened to be won.
WATCH_SECONDS = 0.4

NEGOTIATED = Decision(
    outcome=Outcome.TRANSCODE,
    reasons=("VideoCodecNotSupported",),
    container="ts",
    sub_protocol="hls",
    video=StreamPlan(source_index=0, action=StreamAction.ENCODE, codec="h264"),
    audio=StreamPlan(source_index=1, action=StreamAction.COPY, codec="aac"),
    supports_transcoding=True,
)


class Clock:
    """The manager's monotonic clock, stepped by hand - `test_transcode_lifecycle.py`'s."""

    def __init__(self) -> None:
        self.elapsed = 1000.0

    def advance(self, seconds: float) -> None:
        self.elapsed += seconds

    def __call__(self) -> float:
        return self.elapsed


def plan_for(source: object = None) -> SegmentPlan:
    """The plan every session here carries: what is being produced, and on what grid."""
    return SegmentPlan(
        path="/library/film.mkv",
        source=source,  # type: ignore[arg-type]
        decision=NEGOTIATED,
        container="ts",
        cadence_ticks=CADENCE_TICKS,
        segment_seconds=SEGMENT_SECONDS,
    )


@pytest.fixture
async def ledger() -> AsyncIterator[ffmpeg.ProductionLedger]:
    built = ffmpeg.ProductionLedger()
    yield built
    await built.shutdown()


def manager_over(
    tmp_path: Path, ledger: ffmpeg.ProductionLedger, clock: Clock, **knobs: object
) -> TranscodeManager:
    scratch = tmp_path / "transcodes"
    scratch.mkdir(parents=True, exist_ok=True)
    return TranscodeManager(scratch, ledger, clock=clock, **knobs)  # type: ignore[arg-type]


async def producing(
    manager: TranscodeManager, ledger: ffmpeg.ProductionLedger, *, start_index: int = 0
) -> TranscodeSession:
    """A session with a real process filling its scratch directory from `start_index` on."""
    session = manager.obtain(
        SessionKey(device_id="bench-1", play_session_id="a" * 32, media_path="/library/film.mkv")
    )
    session.scratch.mkdir(parents=True, exist_ok=True)
    session.plan = plan_for()
    session.started_ticks = start_index * CADENCE_TICKS
    session.started_index = start_index
    session.running = await ledger.start(
        (sys.executable, "-c", PRODUCER, str(session.scratch), str(start_index)), to_pipe=False
    )
    return session


def highest(session: TranscodeSession) -> int:
    """The furthest segment on disk, which is how far the producer has got."""
    written = [int(one.stem) for one in session.scratch.glob("*.ts")]
    return max(written, default=-1)


async def reaching(session: TranscodeSession, index: int) -> None:
    """Wait until the producer has written at least this segment, or fail the test."""
    async with asyncio.timeout(10):
        while highest(session) < index:
            await asyncio.sleep(0.01)


def seeded(session: TranscodeSession, indexes: Sequence[int]) -> None:
    """Produced segments, without a producer: the deletion pass reads the directory alone."""
    session.scratch.mkdir(parents=True, exist_ok=True)
    for index in indexes:
        (session.scratch / f"{index}.ts").write_bytes(b"a produced segment")


def on_disk(session: TranscodeSession) -> set[int]:
    return {int(one.stem) for one in session.scratch.glob("*.ts")}


# ------------------------------------------------------------------------------------------
# AC-27: the shipped default, and it is the reference's
# ------------------------------------------------------------------------------------------


def test_the_shipped_configuration_has_both_features_off() -> None:
    """A server with no `config.toml` throttles nothing and deletes nothing.

    Asserted on the settings a first run loads rather than on the manager's argument defaults,
    because "off as shipped" is a claim about what an operator gets, and the two numbers beside
    the switches are the reference's own `[source:
    MediaBrowser.Model/Configuration/EncodingOptions.cs:22-25 @ v10.11.11]`.
    """
    shipped = Settings().encoding
    assert shipped.enable_throttling is False
    assert shipped.enable_segment_deletion is False
    assert shipped.throttle_delay_seconds == 180
    assert shipped.segment_keep_seconds == 720


def test_the_operator_file_reaches_the_manager(tmp_path: Path) -> None:
    """The knobs are wired, and the two floors are applied where the reference applies them.

    A `throttle_delay_seconds = 5` is not a refusal to start and is not five: the reference
    floors the gap at sixty seconds and the keep window at twenty at the point of use, so a value
    an operator can type into Jellyfin's own configuration page behaves the same way here.
    """
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.config_file.write_text(
        FAST_PASSWORDS + "\n[encoding]\n"
        "enable_throttling = true\n"
        "throttle_delay_seconds = 5\n"
        "enable_segment_deletion = true\n"
        "segment_keep_seconds = 1\n",
        encoding="utf-8",
    )
    settings = load_settings(paths)
    assert settings.encoding.enable_throttling is True
    assert settings.encoding.throttle_delay_seconds == 5

    built = create_app(paths)
    try:
        manager: TranscodeManager = built.state.transcodes
        assert manager._throttling is True
        assert manager._throttle_gap == THROTTLE_FLOOR_SECONDS
        assert manager._segment_deletion is True
        assert manager._segment_keep == SEGMENT_KEEP_FLOOR_SECONDS
    finally:
        built.state.db.dispose()


async def test_ac27_production_runs_to_the_end_when_throttling_is_off(
    tmp_path: Path, ledger: ffmpeg.ProductionLedger
) -> None:
    """The shipped half: an idle client leaves the encoder producing the whole file.

    The gap here is enormous - the producer is thousands of segments ahead of a client that
    fetched one - and a sweep still leaves it running, because nothing was configured.
    """
    clock = Clock()
    manager = manager_over(tmp_path, ledger, clock)
    session = await producing(manager, ledger)
    session.download_ticks = CADENCE_TICKS
    await reaching(session, 30)

    await manager.sweep()
    assert session.running is not None
    assert session.running.paused is False

    reached = highest(session)
    await asyncio.sleep(WATCH_SECONDS)
    assert highest(session) > reached, "production stopped with throttling off"


async def test_ac27_production_pauses_at_the_gap_and_resumes_on_the_next_fetch(
    tmp_path: Path, ledger: ffmpeg.ProductionLedger
) -> None:
    """The enabled half: it stops writing, and the next segment request starts it again.

    **The pause is asserted on the files, not on the flag.** A `paused = True` that had sent no
    signal, or sent one the platform ignored, would satisfy every other assertion in this test.

    The resume goes through `segment()` rather than through the throttle directly, because the
    claim is that a *client* releases the encoder: the request moves the download position, the
    gap closes, and the session is let go before the call returns rather than one sweep later.
    """
    clock = Clock()
    manager = manager_over(tmp_path, ledger, clock, throttling=True, throttle_delay_seconds=180)
    session = await producing(manager, ledger)
    # One segment fetched, and then nothing: the client's position stays at three seconds while
    # production runs away from it.
    session.download_ticks = CADENCE_TICKS
    await reaching(session, THROTTLE_FLOOR_SECONDS * 3 // SEGMENT_SECONDS)

    await manager.sweep()
    assert session.running is not None
    assert session.running.paused is True

    stalled = highest(session)
    await asyncio.sleep(WATCH_SECONDS)
    assert highest(session) == stalled, "a suspended producer went on producing"

    # The client catches up: it asks for a segment near where production stopped. The file is
    # already there, so nothing is started - what changes is the position the gap is measured
    # against.
    index = stalled - 1
    served = await manager.segment(
        session,
        plan_for(),
        index=index,
        start_ticks=index * CADENCE_TICKS,
        length_ticks=CADENCE_TICKS,
    )
    assert served.name == f"{index}.ts"
    assert session.running is not None
    assert session.running.paused is False
    await reaching(session, stalled + 1)


async def test_the_gap_is_measured_from_the_furthest_segment_the_client_took(
    tmp_path: Path, ledger: ffmpeg.ProductionLedger
) -> None:
    """A client filling a gap behind itself does not move the download position backwards.

    The reference stores the larger of the two `[source:
    Jellyfin.Api/Controllers/DynamicHlsController.cs:2029 @ v10.11.11]`, and it matters here: a
    player that re-requests segment 0 after a network failure would otherwise re-throttle a
    session that is streaming happily.
    """
    clock = Clock()
    manager = manager_over(tmp_path, ledger, clock, throttling=True)
    session = await producing(manager, ledger)
    await reaching(session, 4)
    seeded(session, [200, 201])

    far = await manager.segment(
        session, plan_for(), index=200, start_ticks=200 * CADENCE_TICKS, length_ticks=CADENCE_TICKS
    )
    assert far.name == "200.ts"
    assert session.download_ticks == 201 * CADENCE_TICKS

    await manager.segment(session, plan_for(), index=0, start_ticks=0, length_ticks=CADENCE_TICKS)
    assert session.download_ticks == 201 * CADENCE_TICKS


# ------------------------------------------------------------------------------------------
# AC-29: produced segments are reclaimed behind the client, while the session lives
# ------------------------------------------------------------------------------------------


async def test_ac29_segments_a_window_behind_the_client_are_removed_while_it_plays(
    tmp_path: Path, ledger: ffmpeg.ProductionLedger
) -> None:
    """The measured boundary, reproduced: 29 goes and 33 stays, on one 720-second window.

    Two files written seconds apart, the same age, on either side of
    `(811 - 720) / 3` - which is what makes this a position rule rather than an age rule. The
    session is still live afterwards, with its process and its scratch directory: this is
    reclamation *during* playback, not the teardown AC-25 asserts.
    """
    clock = Clock()
    manager = manager_over(
        tmp_path,
        ledger,
        clock,
        segment_deletion=True,
        segment_keep_seconds=MEASURED_KEEP_SECONDS,
    )
    session = manager.obtain(
        SessionKey(device_id="bench-1", play_session_id="b" * 32, media_path="/library/film.mkv")
    )
    session.plan = plan_for()
    seeded(session, range(0, 300))
    session.download_ticks = MEASURED_DOWNLOAD_SECONDS * hls.TICKS_PER_SECOND

    await manager.sweep()

    remaining = on_disk(session)
    assert MEASURED_BOUNDARY == 30
    assert 29 not in remaining
    assert 33 in remaining
    assert min(remaining) == MEASURED_BOUNDARY + 1
    assert manager.sessions == (session,), "the session died with its segments"


async def test_ac29_nothing_is_deleted_until_the_client_has_fetched_past_the_window(
    tmp_path: Path, ledger: ffmpeg.ProductionLedger
) -> None:
    """A session paused inside the window keeps every segment, however long it is paused for.

    This is the assertion an age-based reading fails. The clock moves an hour between the two
    sweeps and the files are the same files: what decides is where the client got to, and it
    never got past twelve minutes.
    """
    clock = Clock()
    manager = manager_over(
        tmp_path, ledger, clock, segment_deletion=True, segment_keep_seconds=MEASURED_KEEP_SECONDS
    )
    session = manager.obtain(
        SessionKey(device_id="bench-1", play_session_id="c" * 32, media_path="/library/film.mkv")
    )
    session.plan = plan_for()
    seeded(session, range(0, 40))
    session.download_ticks = 120 * hls.TICKS_PER_SECOND

    await manager.sweep()
    assert on_disk(session) == set(range(0, 40))

    clock.advance(3600)
    manager.ping(session)
    await manager.sweep()
    assert on_disk(session) == set(range(0, 40))


async def test_ac29_a_deleted_segment_is_produced_again_when_it_is_asked_for(
    tmp_path: Path, ledger: ffmpeg.ProductionLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that rewinds past the window is served, through the restart path.

    Deletion is only safe because a missing segment is a *restart*, not a `404`: the reference's
    own branch table treats "the file is not there and the index is behind production" as a seek
    backwards, and this asserts the two halves meet - the pass removes the file, and the next
    request for it produces it again.
    """
    clock = Clock()
    manager = manager_over(
        tmp_path, ledger, clock, segment_deletion=True, segment_keep_seconds=MEASURED_KEEP_SECONDS
    )
    session = await producing(manager, ledger, start_index=270)
    await reaching(session, 272)
    seeded(session, range(0, 60))
    session.download_ticks = MEASURED_DOWNLOAD_SECONDS * hls.TICKS_PER_SECOND

    await manager.sweep()
    assert 5 not in on_disk(session)

    monkeypatch.setattr(ffmpeg, "segment_command", _fake_segment_command)
    produced = await manager.segment(
        session, plan_for(), index=5, start_ticks=5 * CADENCE_TICKS, length_ticks=CADENCE_TICKS
    )
    assert produced.exists()
    assert produced.name == "5.ts"


def _fake_segment_command(
    source: object, decision: object, output: ffmpeg.SegmentOutput, **_: object
) -> tuple[str, ...]:
    """The producer, in the shape `_begin` asks for one: an argument vector and nothing else."""
    return (
        sys.executable,
        "-c",
        PRODUCER,
        str(output.directory),
        str(output.start_number),
    )


# ------------------------------------------------------------------------------------------
# AC-31, the delivery half: a re-encode the account may not have
# ------------------------------------------------------------------------------------------


def _plan(action: StreamAction) -> StreamPlan:
    return StreamPlan(source_index=0, action=action, codec="h264")


@pytest.mark.parametrize(
    ("video", "audio", "policy", "is_video", "refused"),
    [
        # Every permission: nothing is refused, whatever is being produced.
        (StreamAction.ENCODE, StreamAction.ENCODE, PlaybackPolicy(), True, False),
        # The reference's two force-copies, each against its own permission.
        (
            StreamAction.ENCODE,
            StreamAction.COPY,
            PlaybackPolicy(enable_video_transcoding=False),
            True,
            True,
        ),
        (
            StreamAction.COPY,
            StreamAction.ENCODE,
            PlaybackPolicy(enable_audio_transcoding=False),
            True,
            True,
        ),
        # A denial over a stream that is copied anyway changes nothing: the plan already does
        # what the permission would have forced.
        (
            StreamAction.COPY,
            StreamAction.COPY,
            PlaybackPolicy(enable_video_transcoding=False, enable_audio_transcoding=False),
            True,
            False,
        ),
        # `EnablePlaybackRemuxing` has no delivery-time reader in the reference at all, so a
        # remux for an account denied it is served exactly as a permitted account's is.
        (
            StreamAction.COPY,
            StreamAction.COPY,
            PlaybackPolicy(enable_remuxing=False),
            True,
            False,
        ),
        # The audio item's gate is the audio permission alone, which is the negotiation's rule
        # and the same answer here.
        (
            StreamAction.COPY,
            StreamAction.ENCODE,
            PlaybackPolicy(enable_audio_transcoding=False),
            False,
            True,
        ),
    ],
)
def test_ac31_the_delivery_gate_is_per_stream(
    video: StreamAction,
    audio: StreamAction,
    policy: PlaybackPolicy,
    is_video: bool,
    refused: bool,
) -> None:
    """One permission per stream, which is where the reference reads them.

    Not the negotiation's all-three gate: that one decides whether the server offers to produce
    anything at all, and this one decides whether *this* plan may be carried out. The reference
    answers by copying the stream anyway `[source:
    MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:7136-7166 @ v10.11.11]`; Atrium
    refuses the step instead (behaviours section 2.21).
    """
    decision = Decision(
        outcome=Outcome.TRANSCODE,
        reasons=(),
        container="ts",
        sub_protocol="hls",
        video=_plan(video),
        audio=_plan(audio),
        supports_transcoding=True,
    )
    assert refused_by_policy(decision, policy, is_video=is_video) is refused


def test_ac31_an_account_denied_everything_is_refused_before_anything_is_planned() -> None:
    """The all-denied answer is `NOTHING_PLAYABLE`, and delivering it would produce nothing.

    The negotiation already told this client `SupportsTranscoding: false`; a delivery request
    arriving anyway must not fall through into a production with no streams in it.
    """
    denied = PlaybackPolicy(
        enable_video_transcoding=False, enable_audio_transcoding=False, enable_remuxing=False
    )
    assert refused_by_policy(NOTHING_PLAYABLE, denied, is_video=True) is True
    assert refused_by_policy(NOTHING_PLAYABLE, PlaybackPolicy(), is_video=True) is False
