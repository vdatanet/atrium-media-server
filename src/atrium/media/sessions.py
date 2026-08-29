# SPDX-License-Identifier: GPL-3.0-or-later
"""One supervised encoder per playback session, and the segment it was asked for.

Everything else in this feature answers a request and forgets it. A segment request cannot: the
answer is a file that does not exist yet, produced by a process that goes on running after the
response is sent, into a directory that has to be found again by the *next* request. That is the
one genuinely new mechanism in 008, and it is why nine tasks were sequenced ahead of it.

## What decides the bytes, and what only decides the name

The segment URI carries an index in its path and a position in its query, and it is easy to read
the index as the position. It is not `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11,
2026-08-29]`:

* **`runtimeTicks` decides where production starts.** Segment 0's own path asked for at the middle
  of the film answers the middle of the film - measured, two different digests from one path.
* **The index decides only what the produced files are called** - it is ffmpeg's `-start_number`,
  and nothing else `[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:1536-1543 @
  v10.11.11]`.

The two agree for every URI a playlist writes, because `media/hls.plan_segments` puts the
segment's own cumulative start in its query. They stop agreeing the moment anything is
hand-written, and a manager that seeked to `index x cadence` would then produce the wrong film.

## When production restarts, and when the request simply waits

The reference's rule, reproduced, because each branch is a different failure if it is missing
`[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:1493-1520 @ v10.11.11]`:

| The request | What happens |
|---|---|
| The segment file is already there | Served, and nothing starts |
| The initialisation segment (-1) | Production restarts; ffmpeg writes it before segment 0 |
| Nothing is producing | Production starts at the requested position |
| It is behind the producing index | Restart - an encoder cannot go backwards |
| It is more than `24 / segment seconds` ahead | Restart - that is a seek, not a read-ahead |
| Anything else | Wait: the encoder is on its way there |

**A segment is finished when the next one exists**, or when production has stopped altogether. A
muxer writes the current segment as it goes, so its mere presence proves nothing; the file after
it is the proof. Serving a segment that is still being written is the one way to break AC-23 -
the retry after a network failure would be longer than the first attempt.

## What it is keyed on

`(device, play session, media path)`. The reference names its output directory
`md5(media path - user agent - device id - play session id)` and nothing else `[source:
Jellyfin.Api/Helpers/StreamingHelpers.cs:374-383 @ v10.11.11]`, which is why every probe row in
this feature needs a fresh device: two requests sharing those four values share a directory, and
the second is served whatever the first produced whether or not it asked for the same thing. The
user agent is left out here - a delivery route in this project reads no such header - and the
consequence is confined to two clients that share a play session id and disagree about their own
name, which is not a client that exists.

**The decision is not part of the key**, and that is deliberate rather than an omission: the
reference rebuilds its whole streaming state from every request, so a session whose second
request asks for a different audio track restarts with the *new* one. A manager that froze the
first request's answer would keep producing the track the client just changed away from.

Segments stay on disk for the life of the session, which is what makes AC-23 structural rather
than a promise: the same request twice reads one file.

## How a session ends, and what goes with it (008 T12)

Three ways, and all three end in the same place - the process stopped and the session's scratch
directory removed:

| The end | Who decides |
|---|---|
| `DELETE /Videos/ActiveEncodings` | The client, when the viewer stops (`api/hls_segment.py`) |
| Nothing has asked for a segment in a minute | `sweep`, on the reference's own kill timer |
| The server is going down | `shutdown`, from the application's lifespan |

**The kill timer is a minute, and it is a minute because the job is not progressive.** The
reference keeps one number per job and picks it by that single property - 10 000 ms for a
progressive stream, 60 000 ms for everything else `[source:
MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:153-160 @ v10.11.11]` - and every
job a session here owns is an HLS one, because the progressive routes die with their response
instead. Measured end to end rather than only read: an HLS session whose client fetched one
segment and then went quiet stopped 58 s and 60 s later on two runs `[probe:
tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`.

**The stop route matches on the play session and on nothing else.** `deviceId` is mandatory at
the binder and then decides nothing: the reference selects by `playSessionId` whenever one was
given `[source: MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:203-205 @
v10.11.11]`, and a `DELETE` carrying a device nothing owns still stopped the named session
`[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`. So `stop` takes the
play session alone; a manager that had required both to match would have leaked an encoder for
every client that spells its device differently between the negotiation and the stop.

**What the scratch root holds is not all session-scoped**, which is why there are two clearing
paths rather than one. A session owns a *directory* named for its key; a remux owns a *file*
named for the command that produced it (`api/delivery.py`), deliberately global because spec
section 3.4 makes a remux byte-identical for everyone who asks for it. Ending one session must
therefore remove one directory and never touch the files beside it, while startup and shutdown
clear the root whole - the reference deletes every file under the transcode path when it starts
`[source: MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:717-736 @ v10.11.11]`.

## What the operator can turn on (008 T13)

Two features, both off as shipped because the reference ships both off, and both measuring
against the same number: **the download position**, which is the end of the furthest segment any
request has asked for and never goes backwards.

* `enable_throttling` with `throttle_delay_seconds` **suspends production** while where the
  encoder has reached leads the download position by `max(delay, 60)` seconds, and lets it go
  again when the client closes the gap.
* `enable_segment_deletion` with `segment_keep_seconds` **removes the produced segments** lying
  more than one window behind the download position, while the session goes on running.

**Neither knob has anything to do with elapsed time**, and the second one reads as though it
does. `SegmentKeepSeconds` is *media the client has already fetched*, not the age of a file:
measured with a 720-second window and a client whose furthest segment ended at 811 seconds, the
reference deleted segment 29 and left segment 33 alone - two files written seconds apart, on
either side of `(811 - 720) / 3`, forty-five seconds after both were produced and with nothing
requested in between `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`.
A session whose client has paused therefore loses nothing however long it waits, where an
age-based reading would throw away the segments it is about to resume into.

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.4, 3.7 and 3.8, and plan
sections 5 and 6.7.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from atrium.domain.media import MediaInspection
from atrium.media import ffmpeg, hls
from atrium.media.decision import Decision, StreamAction

logger = logging.getLogger("atrium.media")

#: How often a waiting request looks again. The reference polls at 100 ms; this is finer because
#: the fixture films are seconds long and a whole segment can appear inside one of its ticks.
POLL_SECONDS: Final = 0.02

#: The reference's read-ahead tolerance, as a number of seconds divided by the segment length: a
#: request up to 24 seconds of media ahead of what is being produced waits for the encoder to
#: reach it, and anything further is treated as a seek `[source:
#: Jellyfin.Api/Controllers/DynamicHlsController.cs:1497 @ v10.11.11]`.
GAP_SECONDS_ALLOWED: Final = 24

#: How long a session survives with nobody asking it for anything. The reference's own kill timer
#: for a non-progressive job, read at the tag and then measured on a live one - 58 s and 60 s from
#: the last segment to the job's disappearance, on two runs `[source:
#: MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:153-160 @ v10.11.11]` `[probe:
#: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`.
PING_TIMEOUT_SECONDS: Final = 60

#: The reference's other kill timer, for a progressive job. Recorded rather than used: nothing in
#: this registry is progressive, because a progressive response owns its encoder for exactly as
#: long as the response lasts and stops it in a `finally` (`api/delivery.py`, AC-26). It is here
#: so the next reader can see that the 60 above is a choice between two numbers.
PROGRESSIVE_PING_TIMEOUT_SECONDS: Final = 10

#: How often the sweep looks. Sixth of the timeout, so a session dies inside a timeout plus a
#: tick rather than inside two of them - the reference's timer fires per job and this is one loop
#: for all of them, which is the shape 007's session reaper already uses. The reference's own two
#: timers are 5 s for the throttle and 20 s for the segment cleaner `[source:
#: MediaBrowser.Controller/MediaEncoding/TranscodingThrottler.cs:46,
#: MediaBrowser.Controller/MediaEncoding/TranscodingSegmentCleaner.cs:51 @ v10.11.11]`; one loop
#: at ten seconds sits between them and is finer than the coarser of the two.
SWEEP_INTERVAL_SECONDS: Final = 10

#: The floor under `throttle_delay_seconds`, applied where the number is used rather than where it
#: is configured, because that is where the reference applies it `[source:
#: MediaBrowser.Controller/MediaEncoding/TranscodingThrottler.cs:118 @ v10.11.11]`.
THROTTLE_FLOOR_SECONDS: Final = 60

#: The floor under `segment_keep_seconds`, same rule, same reason `[source:
#: MediaBrowser.Controller/MediaEncoding/TranscodingSegmentCleaner.cs:98 @ v10.11.11]`.
SEGMENT_KEEP_FLOOR_SECONDS: Final = 20


@dataclass(frozen=True, slots=True)
class SessionKey:
    """What makes two requests the same playback session."""

    device_id: str
    play_session_id: str
    media_path: str

    @property
    def digest(self) -> str:
        """The scratch directory's name. Not observable, so it is this project's own hash rather
        than the reference's md5 - what has to match is which requests collide, not the spelling
        of the folder they collide in."""
        material = "\0".join((self.device_id, self.play_session_id, self.media_path))
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class SegmentPlan:
    """Everything one production needs, decided by the request that triggers it.

    Per request rather than per session, which is what lets a client change audio track mid-film
    and be answered about the new one.
    """

    path: str
    """The source file, absolutely."""

    source: MediaInspection
    decision: Decision

    container: str
    """What the segments are muxed into - `segmentContainer`, resolved."""

    cadence_ticks: int
    """The planned segment length, from `media/hls.cadence_milliseconds`."""

    segment_seconds: int
    """The *unscaled* requested length, which is the only thing the read-ahead tolerance is
    computed from. Three where the cadence is 3.004: the reference divides by its own integer."""


@dataclass(frozen=True, slots=True)
class TranscodingReport:
    """What a session is producing, in the terms `/Sessions` states it in.

    The reference reports this from the *request's* streaming state on every progress tick and
    hangs it off the device's session `[source:
    MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:344-368 @ v10.11.11]`, so it is
    the last request's answer rather than the session's founding one - the same rule that makes
    `SegmentPlan` per request here.

    **Two of the reference's thirteen properties are missing on purpose**, and they are the two
    it drops itself the moment a job stops: `Framerate` and `CompletionPercentage` come from
    parsing the encoder's progress output, which Atrium does not do - it runs its encoders at
    `-loglevel error` and reads their diagnostics only to say why one failed. The shape without
    them is a shape the reference sends, measured on a session whose job had just been killed
    `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`; the argument is
    in behaviours section 3.11.
    """

    container: str
    video_codec: str | None
    audio_codec: str | None
    video_direct: bool
    audio_direct: bool
    bitrate: int | None
    width: int | None
    height: int | None
    audio_channels: int | None
    reasons: tuple[str, ...]

    @classmethod
    def of(cls, decision: Decision, container: str) -> TranscodingReport:
        """The report a request carrying this decision produces.

        `bitrate` is the two streams added up, which is what the reference reports when ffmpeg
        has not yet said a real one: the output's total rather than either half of it.
        """
        video, audio = decision.video, decision.audio
        rates = [plan.bitrate for plan in (video, audio) if plan is not None and plan.bitrate]
        return cls(
            container=container,
            video_codec=video.codec if video is not None else None,
            audio_codec=audio.codec if audio is not None else None,
            video_direct=video is not None and video.action is StreamAction.COPY,
            audio_direct=audio is not None and audio.action is StreamAction.COPY,
            bitrate=sum(rates) if rates else None,
            width=video.width if video is not None else None,
            height=video.height if video is not None else None,
            audio_channels=audio.channels if audio is not None else None,
            reasons=decision.reasons,
        )


@dataclass(slots=True, eq=False)
class TranscodeSession:
    """One playback session's scratch directory and the process filling it."""

    key: SessionKey
    scratch: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    running: ffmpeg.Production | None = None
    last_ping: float = 0.0
    report: TranscodingReport | None = None
    """What the last request through this session asked to be produced, for `/Sessions`."""

    download_ticks: int = 0
    """How far into the film the client has fetched, and it only ever grows.

    The end of the furthest segment any request has asked for - `runtimeTicks` plus
    `actualSegmentLengthTicks`, which is the parameter the segment route otherwise binds and
    ignores. The reference keeps the same number the same way, taking the larger of the stored
    one and the new one so that a client filling a gap behind itself does not move the position
    backwards `[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:2029 @ v10.11.11]`. Both
    operator knobs measure against it: the throttle asks how far production leads it, and
    segment deletion asks which segments lie a whole keep-window behind it.
    """

    plan: SegmentPlan | None = None
    """The last request's plan, for the cadence the two knobs count in."""

    started_ticks: int = 0
    """Where the live production was told to start."""

    started_index: int = 0
    """The `-start_number` it was given, so a file's name can be turned back into a position."""

    @property
    def producing(self) -> bool:
        """Whether this session has a process that has not yet exited.

        A **suspended** process is still producing by this definition, and deliberately: the
        throttle pauses work it intends to resume, so a request waiting on the encoder must go on
        waiting rather than decide production has stopped.
        """
        return self.running is not None and self.running.process.returncode is None


class TranscodeManager:
    """Every playback session this application owns, and the one encoder each of them may have.

    Built on `ProductionLedger` rather than beside it: the ledger is the whole set of processes
    the server started, this is the subset that belongs to a session and can be found again by
    the next request. So "every ffmpeg has an owner" stays a sweep over one set rather than a
    discipline spread across two (architecture section 4).
    """

    def __init__(
        self,
        scratch: Path,
        ledger: ffmpeg.ProductionLedger,
        *,
        clock: Callable[[], float] = time.monotonic,
        ping_timeout: float = PING_TIMEOUT_SECONDS,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
        throttling: bool = False,
        throttle_delay_seconds: int = 180,
        segment_deletion: bool = False,
        segment_keep_seconds: int = 720,
    ) -> None:
        self._scratch = scratch
        self._ledger = ledger
        self._clock = clock
        self._ping_timeout = ping_timeout
        self._sweep_interval = sweep_interval
        self._throttling = throttling
        self._throttle_gap = max(throttle_delay_seconds, THROTTLE_FLOOR_SECONDS)
        self._segment_deletion = segment_deletion
        self._segment_keep = max(segment_keep_seconds, SEGMENT_KEEP_FLOOR_SECONDS)
        self._sessions: dict[SessionKey, TranscodeSession] = {}

    @property
    def sessions(self) -> tuple[TranscodeSession, ...]:
        """Every live session, for the tests and for the sweep."""
        return tuple(self._sessions.values())

    def obtain(self, key: SessionKey) -> TranscodeSession:
        """The session this request belongs to, created if this is its first request.

        Pinged on creation rather than left at zero: a session exists because a request just
        asked for it, and a sweep that saw the sentinel would reap a session younger than its
        own first segment.
        """
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        session = TranscodeSession(key=key, scratch=self._scratch / key.digest)
        self._sessions[key] = session
        self.ping(session)
        return session

    def ping(self, session: TranscodeSession) -> None:
        """Mark the session as still wanted. Called by every request that reaches it.

        The clock is injectable so that the kill-timer test can move time rather than spend it -
        `SessionRegistry`'s shape, for the same reason.
        """
        session.last_ping = self._clock()

    def reporting(self, device_id: str) -> TranscodingReport | None:
        """What this device is having produced for it, or `None` when nothing is.

        The reference hangs one report on the device's session and overwrites it per progress
        tick `[source: Emby.Server.Implementations/Session/SessionManager.cs:1866-1875 @
        v10.11.11]`, so where a device has two live sessions the newest wins - the same answer
        the last writer would have left there.

        **A blank device names nothing**, which is the reference's own guard rather than a
        defensive one `[source:
        MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:344-346 @ v10.11.11]`: a
        delivery request may arrive with no `deviceId` at all, and matching its session against
        every stored session that happens to have no device either would report one viewer's
        transcode on another's row.
        """
        wanted = device_id.strip().casefold()
        if not wanted:
            return None
        live = [
            session
            for session in self._sessions.values()
            if session.report is not None and session.key.device_id.strip().casefold() == wanted
        ]
        if not live:
            return None
        return max(live, key=lambda session: session.last_ping).report

    async def segment(
        self,
        session: TranscodeSession,
        plan: SegmentPlan,
        *,
        index: int,
        start_ticks: int,
        length_ticks: int = 0,
    ) -> Path:
        """The file holding this segment, produced if it does not exist yet.

        Raises `ffmpeg.ProductionError` when production stopped without ever writing it, which is
        the measured `500`: an encoder that never started and one that died before reaching the
        requested segment are one answer on the reference too.

        `length_ticks` is the request's `actualSegmentLengthTicks`, and with `start_ticks` it is
        the download position both operator knobs measure against. The reference records it when
        the *response* completes rather than when the request arrives `[source:
        Jellyfin.Api/Controllers/DynamicHlsController.cs:2020-2030 @ v10.11.11]`; recording it
        here instead is what lets a throttled encoder be released before this call returns
        rather than one sweep later.
        """
        self.ping(session)
        session.report = TranscodingReport.of(plan.decision, plan.container)
        session.plan = plan
        session.download_ticks = max(session.download_ticks, start_ticks + length_ticks)
        # The throttle only, not the whole pass: a paused encoder has to be let go before this
        # call waits on it, while deletion stays on the sweep's timer the way the reference keeps
        # it on the cleaner's - a rewind that arrives before the next tick is served from the
        # file that is still there rather than re-encoded by the request that asked for it.
        self._throttle(session)
        extension = hls.segment_extension(plan.container)
        target = session.scratch / f"{index}{extension}"

        if not target.exists():
            async with session.lock:
                if not target.exists():
                    await self._begin(session, plan, index=index, start_ticks=start_ticks)
        return await self._settled(session, target, index, extension)

    # -- the kill paths ----------------------------------------------------------------------

    async def stop(self, play_session_id: str) -> bool:
        """End every session a client named, and say whether there was one.

        **The play session is the whole key**, which is the measured rule rather than the
        signature the plan first wrote: the route takes a `deviceId` too and it decides nothing.
        `False` for an id nothing owns, and the route answers `204` regardless - the reference's
        fire-and-forget contract, and the only sane one for a stop a client sends while its
        player is already tearing down.
        """
        wanted = play_session_id.casefold()
        matched = [
            session
            for session in self._sessions.values()
            if session.key.play_session_id.casefold() == wanted
        ]
        for session in matched:
            await self._discard(session)
        return bool(matched)

    async def sweep(self) -> int:
        """End every session nobody has asked about for a timeout. Returns how many.

        Reads the injected clock rather than sleeping, so the kill-timer test moves time instead
        of spending it.

        **It is also where the two operator knobs are applied** (008 T13), on the sessions that
        survive the pass: the reference gives each job a timer of its own for each of them - five
        seconds for the throttle, twenty for the segment cleaner - and one loop over every session
        answers both questions with the same reading of the same two positions.
        """
        cutoff = self._clock() - self._ping_timeout
        stale = [session for session in self._sessions.values() if session.last_ping <= cutoff]
        for session in stale:
            await self._discard(session)
        for session in self._sessions.values():
            self.apply_policy(session)
        return len(stale)

    # -- the operator's knobs ----------------------------------------------------------------

    def apply_policy(self, session: TranscodeSession) -> None:
        """Throttle production and reclaim produced segments, as this operator asked.

        The sweep's whole pass over one session. Both halves are off unless configured, and the
        throttle half runs again on every segment request, which is what keeps a paused encoder
        from costing a client a whole sweep interval before it is let go.
        """
        self._throttle(session)
        self._delete_behind(session)

    def _throttle(self, session: TranscodeSession) -> None:
        """Pause production that leads the client by the configured gap; resume it when it does not.

        The reference compares two positions in the film - where the encoder has reached and the
        end of the furthest segment the client has taken - and pauses while the first leads the
        second by `max(ThrottleDelaySeconds, 60)` seconds `[source:
        MediaBrowser.Controller/MediaEncoding/TranscodingThrottler.cs:148-173 @ v10.11.11]`. The
        same two positions here, with the encoder's read off the scratch directory rather than
        off a progress parser: a session that does not read its encoders' output still knows
        which segment they have reached, because that is the file they are writing.
        """
        running = session.running
        if running is None:
            return
        if not self._throttling:
            # An operator who turns it off mid-session must not leave an encoder stopped for ever.
            running.resume()
            return
        produced = self._produced_ticks(session)
        if produced is None:
            return
        gap = (produced - session.download_ticks) / hls.TICKS_PER_SECOND
        if gap >= self._throttle_gap:
            running.suspend()
        else:
            running.resume()

    def _delete_behind(self, session: TranscodeSession) -> None:
        """Remove the produced segments that lie a whole keep-window behind the client.

        **The window is media the client has already fetched, not wall-clock file age**, which is
        the measurement this task turned up: with a 720-second window and a client whose furthest
        segment ended at 811 seconds, the reference deleted segment 29 and kept segment 33 - two
        files written seconds apart, one either side of `(811 - 720) / 3` `[probe:
        tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`, `[source:
        MediaBrowser.Controller/MediaEncoding/TranscodingSegmentCleaner.cs:100-113 @ v10.11.11]`.
        Nothing at all is deleted until the client has fetched past the window, so a session
        paused for an hour keeps every segment it has.

        The index is counted in the *unscaled* requested segment length, the same integer the
        read-ahead tolerance divides by (behaviours section 3.10), not in the scaled cadence the
        playlist states.
        """
        plan = session.plan
        if not self._segment_deletion or plan is None:
            return
        downloaded = round(session.download_ticks / hls.TICKS_PER_SECOND)
        if downloaded <= self._segment_keep:
            return
        seconds = max(plan.segment_seconds, 1)
        last = (downloaded - self._segment_keep) // seconds
        if last <= 0:
            return
        extension = hls.segment_extension(plan.container)
        # The directory is listed and filtered rather than counted down from the boundary: a
        # session an hour into a film has thousands of indexes below it and a handful of files.
        for one in self._produced(session, extension):
            if int(one.stem) <= last:
                with contextlib.suppress(OSError):
                    one.unlink(missing_ok=True)

    def _produced_ticks(self, session: TranscodeSession) -> int | None:
        """Where in the film the live encoder has reached, or `None` when it cannot be told.

        From the file it is writing: production began at `started_ticks` numbering its output
        from `started_index`, so a newest file numbered `n` means it has produced everything up
        to `started_ticks + (n + 1 - started_index)` cadences. That is the same quantity the
        reference reads out of its encoder's progress lines, arrived at from what is on disk -
        which is all a server that runs its encoders at `-loglevel error` has.
        """
        plan = session.plan
        if plan is None:
            return None
        index = self._producing_index(session, hls.segment_extension(plan.container))
        if index is None:
            return session.started_ticks
        return session.started_ticks + (index + 1 - session.started_index) * plan.cadence_ticks

    async def run(self) -> None:
        """Sweep on the interval until cancelled, started by the application factory.

        A failure is logged rather than allowed to kill the task: nothing else would restart it,
        and the sessions the failed pass did not reach are still stale on the next one. 007's
        playback reaper is the same loop for the same reason.
        """
        while True:
            await asyncio.sleep(self._sweep_interval)
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("sweeping idle transcode sessions failed; retrying next sweep")

    async def shutdown(self) -> None:
        """Stop every session's encoder and clear the scratch root. From the lifespan.

        The root rather than the sessions' directories, because a remux file belongs to no
        session and there is nobody left to serve it to.
        """
        for session in list(self._sessions.values()):
            await self._halt(session)
        self._sessions.clear()
        self.clear_scratch()

    def clear_scratch(self) -> None:
        """Empty the scratch root of everything, whoever wrote it.

        Called at startup as well as at shutdown, because a server that was killed rather than
        stopped left a directory per session it was serving and a file per remux it had produced,
        and neither is reachable again: a session's name includes a play session id no client
        will send twice, and a remux's name includes a change signal that a restart has no reason
        to reproduce. The reference deletes every file under this path when it starts, and leaves
        the directories `[source:
        MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:717-736 @ v10.11.11]`; the
        directories go too here, which no client can observe and an operator's `du` can.
        """
        if not self._scratch.exists():
            return
        for entry in sorted(self._scratch.iterdir()):
            try:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
            except OSError:
                # A file the operator has open, or a permission this process does not have.
                # Reclaiming what can be reclaimed beats refusing to start over one entry.
                logger.warning("could not clear the scratch entry %s", entry)

    async def _discard(self, session: TranscodeSession) -> None:
        """Stop one session and take its scratch directory with it.

        **The directory, never the root.** A remux output lives beside these as a file named for
        the command that produced it, shared by every request that asks for the same thing (spec
        section 3.4), and a stop that cleared the root would throw away work belonging to
        sessions it was not asked about.
        """
        await self._halt(session)
        self._sessions.pop(session.key, None)
        shutil.rmtree(session.scratch, ignore_errors=True)

    # -- production ------------------------------------------------------------------------

    async def _begin(
        self, session: TranscodeSession, plan: SegmentPlan, *, index: int, start_ticks: int
    ) -> None:
        """Start production for this request, unless the encoder is already on its way there."""
        extension = hls.segment_extension(plan.container)
        current = self._producing_index(session, extension)
        if not self._restarts(index, current, plan):
            return

        await self._halt(session)
        if current is not None:
            # The newest file is the one the killed encoder was in the middle of writing. The
            # reference deletes exactly it and leaves every finished segment behind, which is
            # what makes a seek cheap: the part of the film already produced is still served.
            newest = self._newest(session, extension)
            if newest is not None:
                newest.unlink(missing_ok=True)

        session.scratch.mkdir(parents=True, exist_ok=True)
        # Where this run begins and how its files are numbered, which is what turns the name of
        # the file the encoder is writing back into a position in the film for the throttle.
        session.started_ticks = start_ticks
        session.started_index = max(index, 0)
        argv = ffmpeg.segment_command(
            plan.source,
            plan.decision,
            ffmpeg.SegmentOutput(
                container=plan.container,
                directory=session.scratch,
                extension=extension,
                # The initialisation segment is not a position in the film: ffmpeg writes it
                # from the head of whatever it is about to produce, so production is numbered
                # from zero and the init file appears beside segment 0.
                start_number=max(index, 0),
                cadence_ticks=plan.cadence_ticks,
            ),
            path=plan.path,
            start_ticks=start_ticks,
        )
        session.running = await self._ledger.start(argv, to_pipe=False)

    def _restarts(self, index: int, current: int | None, plan: SegmentPlan) -> bool:
        """The reference's five branches, in its order."""
        if index == ffmpeg.INITIALISATION_INDEX or current is None:
            return True
        if index < current:
            return True
        allowed = max(GAP_SECONDS_ALLOWED // max(plan.segment_seconds, 1), 1)
        return index - current > allowed

    async def _halt(self, session: TranscodeSession) -> None:
        running = session.running
        session.running = None
        if running is not None:
            await self._ledger.finish(running)

    async def _settled(
        self, session: TranscodeSession, target: Path, index: int, extension: str
    ) -> Path:
        """Wait until this segment is finished, and hand back where it is.

        Finished means the file exists **and** one of: production has stopped, the next segment
        exists, or production is already past this index. A file that merely exists may still be
        open in the muxer.
        """
        following = session.scratch / f"{index + 1}{extension}"
        while True:
            exists = target.exists()
            stopped = not session.producing
            if stopped:
                # An encoder that has run to the end is finished work rather than live work, and
                # the ledger is the set of processes this server has started **and not reaped**.
                # Reaped here rather than by a sweep because this is the moment something
                # noticed, and a ledger holding exited processes cannot answer AC-26's question.
                await self._halt(session)
            if exists and (stopped or following.exists()):
                return target
            if exists and not stopped:
                current = self._producing_index(session, extension)
                if current is not None and index < current:
                    return target
            if stopped:
                break
            await asyncio.sleep(POLL_SECONDS)

        if target.exists():
            return target
        raise ffmpeg.ProductionError(
            f"production stopped without writing segment {index} of {session.key.media_path}"
        )

    # -- reading the scratch directory ------------------------------------------------------

    def _producing_index(self, session: TranscodeSession, extension: str) -> int | None:
        """Which segment the live encoder is on, or `None` when none is running.

        `None` for a stopped encoder too, and that is the reference's own answer: a finished
        production has no position, so the next request that misses a file starts a new one.
        """
        if not session.producing:
            return None
        newest = self._newest(session, extension)
        if newest is None:
            return None
        try:
            return int(newest.stem)
        except ValueError:
            return None

    @staticmethod
    def _produced(session: TranscodeSession, extension: str) -> list[Path]:
        """Every finished segment file in this session's directory, by index.

        The initialisation segment is numbered -1 and is not a position in the film, so it is
        left out here: it is the header every other segment is read against, and a deletion pass
        that took it would break the playback it is meant to be tidying up behind.
        """
        try:
            return [one for one in session.scratch.glob(f"*{extension}") if one.stem.isdigit()]
        except OSError:
            return []

    @staticmethod
    def _newest(session: TranscodeSession, extension: str) -> Path | None:
        """The most recently written segment file - by modification time, not by index.

        The reference's `GetLastTranscodingFile` sorts the same way, and the difference matters
        after a restart: the highest-numbered file may be one an earlier run left behind, while
        the newest is always the one being written now.
        """
        written: list[tuple[int, Path]] = []
        try:
            for one in session.scratch.glob(f"*{extension}"):
                try:
                    written.append((one.stat().st_mtime_ns, one))
                except OSError:
                    # Deleted between the listing and the stat - a restart doing its own
                    # tidying up. It is not the newest file if it is not there any more.
                    continue
        except OSError:
            return None
        if not written:
            return None
        return max(written)[1]


__all__ = [
    "GAP_SECONDS_ALLOWED",
    "PING_TIMEOUT_SECONDS",
    "POLL_SECONDS",
    "PROGRESSIVE_PING_TIMEOUT_SECONDS",
    "SEGMENT_KEEP_FLOOR_SECONDS",
    "SWEEP_INTERVAL_SECONDS",
    "THROTTLE_FLOOR_SECONDS",
    "SegmentPlan",
    "SessionKey",
    "TranscodeManager",
    "TranscodeSession",
    "TranscodingReport",
]
