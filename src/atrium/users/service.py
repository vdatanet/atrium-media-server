# SPDX-License-Identifier: GPL-3.0-or-later
"""Authenticate: the only place a password is verified.

One entry point, because the three things it owns are the three that get forgotten when they are
split across callers - the lockout counter, the timing guarantee, and creating the session. A
second caller that verified a password directly would have none of them, and nothing would say so.

## The timing guarantee

**Every failure path runs the KDF.** Argon2id takes tens of milliseconds; skipping it for a
username that does not exist makes that response measurably faster and turns this endpoint into an
oracle for which accounts are real. So an unknown user is verified against a dummy record built at
startup from `secrets`, and a disabled or locked-out account is verified anyway before being
refused.

It is asserted by **counting KDF invocations**, not by measuring time: a timing test that asserts
milliseconds fails on a loaded runner and teaches everyone to ignore it (plan section 8.1). The
count is exact and it fails for the right reason.

## The four failures are not one answer

Measured `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`:

| Failure | Status |
|---|---|
| Unknown username | `401` |
| Wrong password | `401` |
| Disabled account | `403` |
| Locked out | `403`, and the reference's answer here is unmeasured - spec section 7, OQ-5 |

All four carry the **same body** - 25 bytes of `text/plain` - so the status is the entire
difference between them, and the golden responses compare bytes rather than codes.

## The counter has to survive the refusal

A wrong password increments `InvalidLoginAttemptCount`, and that increment is a **write on a path
that ends in an exception**. Raising inside the transaction would roll it back, so the work
produces an outcome and the refusal is raised after the transaction has closed. Getting this
backwards gives a server whose lockout counter never moves, and every test of "a wrong password is
401" still passes.

See specs/002-authentication-users-and-sessions/plan.md sections 5 and 6.2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from atrium.compat.auth import ClientInfo
from atrium.compat.errors import AccountUnavailableError, InvalidCredentialsError
from atrium.config.settings import AuthenticationSettings
from atrium.db.engine import session_scope
from atrium.db.repositories import UserRepository
from atrium.domain.session import IssuedToken, Session
from atrium.domain.user import User
from atrium.users.passwords import PasswordRecordError, Passwords
from atrium.users.sessions import SessionRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthResult:
    """What a successful authentication produced. The token's plaintext exists once, here."""

    user: User
    session: Session
    token: IssuedToken = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Refusal:
    """An outcome that ends in an exception, carried out of the transaction so it can commit.

    The wrong-password path writes - it increments the counter - and then fails. Raising inside the
    unit of work would roll that write back, and a server whose lockout counter never moves passes
    every test of "a wrong password is 401".
    """

    error: Exception


class Authenticator:
    """The single entry point. One per instance, holding that instance's own dependencies."""

    def __init__(
        self,
        sessions: sessionmaker[OrmSession],
        passwords: Passwords,
        registry: SessionRegistry,
        settings: AuthenticationSettings | None = None,
    ) -> None:
        self._sessions = sessions
        self._passwords = passwords
        self._registry = registry
        self._settings = settings or AuthenticationSettings()

    def authenticate(
        self,
        username: str,
        password: str,
        info: ClientInfo,
        remote_end_point: str | None = None,
    ) -> AuthResult:
        """Verify, and on success create the session this device will use."""
        with session_scope(self._sessions) as opened:
            outcome = self._attempt(opened, username, password, info, remote_end_point)
        if isinstance(outcome, _Refusal):
            raise outcome.error
        return outcome

    # -- the attempt itself --------------------------------------------------------------------

    def _attempt(
        self,
        opened: OrmSession,
        username: str,
        password: str,
        info: ClientInfo,
        remote_end_point: str | None,
    ) -> AuthResult | _Refusal:
        users = UserRepository(opened)
        user = users.by_name(username)

        if user is None:
            # The dummy verify is the whole of the timing guarantee. Without it this branch
            # returns in microseconds and every other one in tens of milliseconds.
            self._passwords.verify_dummy(password)
            return _Refusal(InvalidCredentialsError("no such user"))

        if user.is_disabled:
            self._passwords.verify_dummy(password)
            return _Refusal(AccountUnavailableError("the account is disabled"))

        if self._locked_out(user):
            self._passwords.verify_dummy(password)
            return _Refusal(AccountUnavailableError("the account is locked out"))

        verified = self._verify(user, password)
        if not verified:
            users.record_failed_attempt(user.id)
            return _Refusal(InvalidCredentialsError("wrong password"))

        users.record_success(user.id)
        self._rehash_if_stale(users, user, password)
        established = self._registry.establish_in(opened, user, info, remote_end_point)
        refreshed = users.by_id(user.id) or user
        return AuthResult(user=refreshed, session=established.session, token=established.token)

    def _verify(self, user: User, password: str) -> bool:
        """True when this password opens this account.

        An account with **no password at all** is not one with an empty password: it is opened by
        sending nothing, and sending something is a refusal. The dummy verify runs either way, so
        the two answers cost the same - `HasPassword` is public on the login screen anyway, but
        there is no reason to add a second channel for it.
        """
        if user.password_hash is None:
            self._passwords.verify_dummy(password)
            return not password
        try:
            return self._passwords.verify(user.password_hash, password)
        except PasswordRecordError:
            # An unreadable record is not a wrong password. Named here because it means somebody
            # has to reset one rather than remember one (plan section 7). The username, never the
            # password - tests/security asserts that.
            logger.warning("the stored password record for %s cannot be read", user.name)
            return False

    def _rehash_if_stale(self, users: UserRepository, user: User, password: str) -> None:
        """The one moment the plaintext exists, which is what makes raising the cost possible.

        Below the current policy, never different from it: rewriting a stronger record weaker here
        would be the one place it could happen silently (ADR-0006, plan section 6.2).
        """
        if user.password_hash is None:
            return
        try:
            if self._passwords.needs_rehash(user.password_hash):
                users.set_password_hash(user.id, self._passwords.hash(password))
        except PasswordRecordError:
            users.set_password_hash(user.id, self._passwords.hash(password))

    def _locked_out(self, user: User) -> bool:
        """Whether this account has spent its attempts.

        A **positive** `LoginAttemptsBeforeLockout` in the user's own policy is honoured as the
        count it plainly is. The reference's own default is `-1`, a sentinel whose meaning is not
        measured (spec section 7, OQ-6), and an account carrying one falls back to the operator's
        setting - which is `0`, no lockout, until somebody measures it.
        """
        threshold = user.login_attempts_before_lockout
        if threshold <= 0:
            threshold = self._settings.lockout_attempts
        if threshold <= 0:
            return False
        return user.invalid_login_attempt_count >= threshold


__all__ = ["AuthResult", "Authenticator"]
