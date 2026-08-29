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
than a promise: the same request twice reads one file. Clearing them is 008 T12's, together with
the ping timeout this module's `ping` feeds and the stop route that ends a session on demand.

See specs/008-playback-negotiation-and-delivery/spec.md sections 3.4, 3.7 and 3.8, and plan
sections 5 and 6.7.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from atrium.domain.media import MediaInspection
from atrium.media import ffmpeg, hls
from atrium.media.decision import Decision

#: How often a waiting request looks again. The reference polls at 100 ms; this is finer because
#: the fixture films are seconds long and a whole segment can appear inside one of its ticks.
POLL_SECONDS: Final = 0.02

#: The reference's read-ahead tolerance, as a number of seconds divided by the segment length: a
#: request up to 24 seconds of media ahead of what is being produced waits for the encoder to
#: reach it, and anything further is treated as a seek `[source:
#: Jellyfin.Api/Controllers/DynamicHlsController.cs:1497 @ v10.11.11]`.
GAP_SECONDS_ALLOWED: Final = 24


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


@dataclass(slots=True, eq=False)
class TranscodeSession:
    """One playback session's scratch directory and the process filling it."""

    key: SessionKey
    scratch: Path
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    running: ffmpeg.Production | None = None
    last_ping: float = 0.0

    @property
    def producing(self) -> bool:
        """Whether this session has a process that has not yet exited."""
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
    ) -> None:
        self._scratch = scratch
        self._ledger = ledger
        self._clock = clock
        self._sessions: dict[SessionKey, TranscodeSession] = {}

    @property
    def sessions(self) -> tuple[TranscodeSession, ...]:
        """Every live session, for the tests and for 008 T12's sweep."""
        return tuple(self._sessions.values())

    def obtain(self, key: SessionKey) -> TranscodeSession:
        """The session this request belongs to, created if this is its first request."""
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        session = TranscodeSession(key=key, scratch=self._scratch / key.digest)
        self._sessions[key] = session
        return session

    def ping(self, session: TranscodeSession) -> None:
        """Mark the session as still wanted. Called by every request that reaches it.

        The clock is injectable so that 008 T12's kill-timer test can move time rather than
        spend it - `SessionRegistry`'s shape, for the same reason.
        """
        session.last_ping = self._clock()

    async def segment(
        self, session: TranscodeSession, plan: SegmentPlan, *, index: int, start_ticks: int
    ) -> Path:
        """The file holding this segment, produced if it does not exist yet.

        Raises `ffmpeg.ProductionError` when production stopped without ever writing it, which is
        the measured `500`: an encoder that never started and one that died before reaching the
        requested segment are one answer on the reference too.
        """
        self.ping(session)
        extension = hls.segment_extension(plan.container)
        target = session.scratch / f"{index}{extension}"

        if not target.exists():
            async with session.lock:
                if not target.exists():
                    await self._begin(session, plan, index=index, start_ticks=start_ticks)
        return await self._settled(session, target, index, extension)

    async def shutdown(self) -> None:
        """Stop every session's encoder. Called from the application's lifespan.

        The scratch is left where it is: clearing it wholesale, at shutdown and at startup, is
        008 T12's, together with the sweep that reclaims a session nobody is asking about.
        """
        for session in list(self._sessions.values()):
            await self._halt(session)
        self._sessions.clear()

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
    "POLL_SECONDS",
    "SegmentPlan",
    "SessionKey",
    "TranscodeManager",
    "TranscodeSession",
]
