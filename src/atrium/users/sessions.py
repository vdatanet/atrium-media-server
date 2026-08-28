# SPDX-License-Identifier: GPL-3.0-or-later
"""Sessions: what is written when, and what is deliberately not.

Two jobs, and they are here together because they are the two halves of a session's life.

**Activity is not a write per request.** `LastActivityDate` advances on every authenticated call,
and persisting that would make SQLite take a write lock on every request - the exact behaviour WAL
mode exists to avoid needing. So activity accumulates in memory and a background task flushes it
every 30 seconds, with a final flush on clean shutdown.

The cost is bounded and stated rather than discovered: **an unclean shutdown loses up to one flush
interval of activity timestamps, and nothing else.** The token itself, the session identity and
every user record are written synchronously. An activity timestamp is the only thing in this
feature that can be a little stale without any client being able to tell.

**Establishing a session is one transaction, and that is the whole point of it.** Re-authenticating
from a known device replaces the session and deletes the previous token together, so there is no
instant at which both tokens work. Two statements in two transactions would leave exactly that
window, and it is the kind that only shows up under load, in somebody else's logs.

`establish_in` exists so a caller that already owns a transaction can compose this into it - and so
the test that proves there is no window can look at the database from a second connection while the
first one is still open.

See specs/002-authentication-users-and-sessions/plan.md sections 6.5 and 6.6.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from atrium.compat.auth import ClientInfo
from atrium.compat.dates import utc_now
from atrium.compat.guids import new_id
from atrium.db.engine import session_scope
from atrium.db.repositories import SessionRepository, TokenRepository
from atrium.domain.session import IssuedToken, Session
from atrium.domain.user import User

logger = logging.getLogger(__name__)

#: Long enough that a busy server is not writing constantly, short enough that what a crash loses
#: is not worth a client noticing. Plan section 6.5.
DEFAULT_FLUSH_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class Established:
    """A session and the token that reaches it. The token's plaintext exists once, here."""

    session: Session
    token: IssuedToken = field(repr=False)


@dataclass(frozen=True, slots=True)
class Activity:
    """One session's most recent request, not yet written down."""

    token_sha256: str
    session_id: str
    when: datetime


class SessionRegistry:
    """In-memory activity, and the one transaction that swaps a device's session.

    One per instance rather than a module-level object: two servers in one process - which the
    suite builds constantly - must not flush into each other's database.
    """

    def __init__(
        self,
        sessions: sessionmaker[OrmSession],
        *,
        flush_interval: float = DEFAULT_FLUSH_SECONDS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._sessions = sessions
        self.flush_interval = flush_interval
        self._clock = clock
        #: Session id -> its latest activity. Latest wins, so a busy session costs one entry
        #: rather than one per request.
        self._pending: dict[str, Activity] = {}
        #: Session id -> its latest playback check-in, flushed on the same pass (007 plan
        #: section 6.6). Separate from `_pending` because a report advances both and an ordinary
        #: request advances only activity - one map could not tell them apart.
        self._checked_in: dict[str, datetime] = {}

    # -- activity ----------------------------------------------------------------------------

    def touch(self, token_sha256: str, session_id: str, when: datetime | None = None) -> None:
        """Record that this session was just used. No I/O."""
        moment = when or self._clock()
        self._pending[session_id] = Activity(token_sha256, session_id, moment)

    def touch_playback(self, session_id: str, when: datetime | None = None) -> None:
        """Record that this session reported playback. No I/O, flushed with the activity.

        A synchronous write here would be the write-per-request the flush exists to avoid, and
        what it costs is the same bound 002 stated: an unclean shutdown loses up to one interval
        of *timestamps*, never a position - positions are rows written per report.
        """
        moment = when or self._clock()
        self._checked_in[session_id] = moment
        self.touch_session(session_id, moment)

    def touch_session(self, session_id: str, when: datetime) -> None:
        """Advance activity for a session whose token this caller does not have to hand.

        The report routes have the session id from the request state and not the token hash, and
        an entry with an empty hash would flush a token update for a token that does not exist.
        """
        held = self._pending.get(session_id)
        if held is not None:
            self._pending[session_id] = Activity(held.token_sha256, session_id, when)

    def playback_check_in(self, session_id: str) -> datetime | None:
        """The live value `/Sessions` reports, newer than the stored one between flushes."""
        return self._checked_in.get(session_id)

    def activity(self, session_id: str) -> datetime | None:
        """The live timestamp, which is newer than the stored one between flushes.

        `/Sessions` reads through this: reporting the flushed value would tell a client that a
        session it is using right now was last active half a minute ago.
        """
        pending = self._pending.get(session_id)
        return pending.when if pending is not None else None

    def snapshot(self) -> dict[str, datetime]:
        """What a flush would write. Copied, so a caller cannot edit the pending set."""
        return {session_id: entry.when for session_id, entry in self._pending.items()}

    def flush(self) -> int:
        """Write what has accumulated, and return how many sessions were advanced.

        Taken and cleared before the write, so a request arriving during it starts a fresh entry
        rather than being dropped by the clear.
        """
        if not self._pending and not self._checked_in:
            return 0
        writing, self._pending = self._pending, {}
        checked_in, self._checked_in = self._checked_in, {}
        try:
            with session_scope(self._sessions) as opened:
                sessions = SessionRepository(opened)
                tokens = TokenRepository(opened)
                for entry in writing.values():
                    sessions.touch(
                        entry.session_id, entry.when, checked_in.pop(entry.session_id, None)
                    )
                    tokens.touch(entry.token_sha256, entry.when)
                # A session that reported playback without an activity entry of its own - the
                # registry was built after the request that authenticated it, which is what a
                # restart mid-playback looks like.
                for session_id, when in checked_in.items():
                    sessions.touch(session_id, when, when)
        except Exception:
            # Put them back rather than losing them: the next flush retries, and a database that
            # is briefly unavailable costs a delay rather than a gap.
            for session_id, entry in writing.items():
                self._pending.setdefault(session_id, entry)
            for session_id, when in checked_in.items():
                self._checked_in.setdefault(session_id, when)
            logger.exception("could not flush session activity; %d entries kept", len(writing))
            raise
        return len(writing)

    async def run(self) -> None:
        """Flush on the interval until cancelled. Started and stopped by the application factory.

        The write goes to a thread because it is blocking database work and this is the event loop
        (ADR-0002). A failure is logged and the loop continues - a flush that raises must not take
        the server's background task down with it, because nothing else would restart it.
        """
        while True:
            await asyncio.sleep(self.flush_interval)
            try:
                await asyncio.to_thread(self.flush)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("session activity flush failed; will retry next interval")

    # -- establishing --------------------------------------------------------------------------

    def establish(
        self, user: User, info: ClientInfo, remote_end_point: str | None = None
    ) -> Established:
        """Give this device a session and a token, replacing whatever it had."""
        with session_scope(self._sessions) as opened:
            return self.establish_in(opened, user, info, remote_end_point)

    def establish_in(
        self,
        opened: OrmSession,
        user: User,
        info: ClientInfo,
        remote_end_point: str | None = None,
    ) -> Established:
        """The same work inside a transaction somebody else owns.

        The order matters. The previous token dies **before** the new one exists, inside one
        transaction, so no reader ever sees two working tokens for one device - and no reader sees
        zero either, because nothing is committed until both are done.
        """
        moment = self._clock()
        sessions = SessionRepository(opened)
        tokens = TokenRepository(opened)

        tokens.revoke_device(user.id, info.device_id)
        existing = sessions.by_device(user.id, info.device_id)
        session = sessions.upsert(
            Session(
                id=existing.id if existing is not None else new_id(),
                user_id=user.id,
                device_id=info.device_id,
                client=info.client,
                device_name=info.device,
                app_version=info.version,
                remote_end_point=remote_end_point,
                last_activity_date=moment,
            )
        )
        issued = tokens.issue(
            user.id,
            device_id=info.device_id,
            client=info.client,
            device_name=info.device,
            app_version=info.version,
            when=moment,
        )
        self._evict(sessions, tokens, user, keeping=session.id)
        self._pending.pop(session.id, None)
        return Established(session=session, token=issued)

    def _evict(
        self, sessions: SessionRepository, tokens: TokenRepository, user: User, keeping: str
    ) -> None:
        """Drop the least recently active sessions over the user's cap.

        `max_active_sessions` of 0 means unlimited, which is what the reference sends for an
        untouched account (spec section 3.5).

        **An evicted session's tokens go with it.** A session removed from `/Sessions` whose token
        still worked would reappear on that device's next request, which is not eviction - it is a
        gap in a list.
        """
        cap = user.max_active_sessions
        if cap <= 0:
            return
        live = [one for one in sessions.for_user(user.id) if one.id != keeping]
        # `for_user` is most-recently-active first, so the tail is what goes.
        surplus = live[max(cap - 1, 0) :]
        for stale in surplus:
            tokens.revoke_device(user.id, stale.device_id)
            sessions.remove(stale.id)
            self._pending.pop(stale.id, None)


__all__ = ["DEFAULT_FLUSH_SECONDS", "Activity", "Established", "SessionRegistry"]
