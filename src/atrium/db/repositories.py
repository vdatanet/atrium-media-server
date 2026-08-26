# SPDX-License-Identifier: GPL-3.0-or-later
"""The boundary: domain objects out, never rows.

Everything above `db/` deals in `domain/` types. That is what makes ADR-0003's "SQLite is the
default, not the only option" a claim somebody could act on rather than an intention - and, more
immediately, it is what stops a route from holding a row whose session has closed and triggering a
query when it reads an attribute. The models make that failure loud rather than silent
(`lazy="raise"`), and this module is why it never comes up.

**Token hashing lives here, at the narrowest point.** A caller cannot store a plaintext token
because a caller never has one to store: `TokenRepository.issue` generates the secret, writes only
its SHA-256, and hands the plaintext back exactly once in an `IssuedToken`, whose `repr` does not
include it. There is no method that accepts a token to store. Putting the hash a layer up would
mean every future caller had to remember, and one of them would not.

SHA-256 rather than a KDF, per ADR-0006: a token is 128 bits from the system CSPRNG, not a
human-chosen secret, so there is nothing to brute-force and a KDF would tax every authenticated
request. The lookup is by primary key on the hash, so there is no comparison to make constant-time.

See specs/002-authentication-users-and-sessions/plan.md section 3 and docs/architecture.md
section 1.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.compat.guids import new_id
from atrium.db import models
from atrium.domain.session import AccessToken, IssuedToken, Session
from atrium.domain.user import LibraryAccess, User

#: Sixteen bytes, rendered as 32 lowercase hex characters - the shape the reference's `AccessToken`
#: has. `[prior-probe: Jellyfin 10.11.11, 2026-06-13]`, spec section 3.3.
TOKEN_BYTES = 16


def token_digest(token: str) -> str:
    """What the database stores. The one-way step, in one place."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalise_name(name: str) -> str:
    """What a login is matched against.

    `casefold` rather than `lower`, because it is the one that handles the cases `lower` does not -
    a German account named `STRASSE` and one named `Straße` are the same login, and on a server
    that matches with `lower` they are two accounts one of which cannot be reached.
    """
    return name.strip().casefold()


# --------------------------------------------------------------------------------------------
# Row -> domain
# --------------------------------------------------------------------------------------------


def _user(row: models.User) -> User:
    return User(
        id=row.id,
        name=row.name,
        name_normalised=row.name_normalised,
        password_hash=row.password_hash,
        is_administrator=row.is_administrator,
        is_disabled=row.is_disabled,
        is_hidden=row.is_hidden,
        enable_all_folders=row.enable_all_folders,
        enable_media_playback=row.enable_media_playback,
        enable_content_deletion=row.enable_content_deletion,
        login_attempts_before_lockout=row.login_attempts_before_lockout,
        invalid_login_attempt_count=row.invalid_login_attempt_count,
        max_active_sessions=row.max_active_sessions,
        last_login_date=row.last_login_date,
        last_activity_date=row.last_activity_date,
        # Copied rather than handed over: the row's dict belongs to the identity map, and a caller
        # that mutated it would be editing the session's idea of what is in the database.
        policy_extra=dict(row.policy_extra),
        configuration=dict(row.configuration),
    )


def _token(row: models.AccessToken) -> AccessToken:
    return AccessToken(
        token_sha256=row.token_sha256,
        user_id=row.user_id,
        device_id=row.device_id,
        client=row.client,
        device_name=row.device_name,
        app_version=row.app_version,
        created=row.created,
        last_used=row.last_used,
    )


def _session(row: models.Session) -> Session:
    return Session(
        id=row.id,
        user_id=row.user_id,
        device_id=row.device_id,
        client=row.client,
        device_name=row.device_name,
        app_version=row.app_version,
        remote_end_point=row.remote_end_point,
        last_activity_date=row.last_activity_date,
        last_playback_check_in=row.last_playback_check_in,
        capabilities=dict(row.capabilities),
    )


# --------------------------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------------------------


class UserRepository:
    """Accounts. Takes a unit of work; the caller decides where the transaction ends."""

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def by_id(self, user_id: str) -> User | None:
        row = self._session.get(models.User, user_id)
        return _user(row) if row is not None else None

    def by_name(self, name: str) -> User | None:
        """Case-insensitive, which is what the reference does (spec section 3.3)."""
        row = self._session.execute(
            select(models.User).where(models.User.name_normalised == normalise_name(name))
        ).scalar_one_or_none()
        return _user(row) if row is not None else None

    def all(self) -> list[User]:
        rows = self._session.execute(select(models.User).order_by(models.User.name)).scalars()
        return [_user(row) for row in rows]

    def visible_on_login_screens(self) -> list[User]:
        """What `/Users/Public` lists. An installation where every user is hidden returns none,
        and that is a valid answer rather than an error (spec section 3.4)."""
        rows = self._session.execute(
            select(models.User).where(models.User.is_hidden.is_(False)).order_by(models.User.name)
        ).scalars()
        return [_user(row) for row in rows]

    def add(self, user: User) -> User:
        """Domain object in, domain object out. The normalised name is derived here, not supplied:
        a caller that computed it differently would create an account nobody can log in to."""
        row = models.User(
            id=user.id or new_id(),
            name=user.name,
            name_normalised=normalise_name(user.name),
            password_hash=user.password_hash,
            is_administrator=user.is_administrator,
            is_disabled=user.is_disabled,
            is_hidden=user.is_hidden,
            enable_all_folders=user.enable_all_folders,
            enable_media_playback=user.enable_media_playback,
            enable_content_deletion=user.enable_content_deletion,
            login_attempts_before_lockout=user.login_attempts_before_lockout,
            invalid_login_attempt_count=user.invalid_login_attempt_count,
            max_active_sessions=user.max_active_sessions,
            last_login_date=user.last_login_date,
            last_activity_date=user.last_activity_date,
            policy_extra=dict(user.policy_extra),
            configuration=dict(user.configuration),
        )
        self._session.add(row)
        self._session.flush()
        return _user(row)

    def library_access(self, user_id: str) -> LibraryAccess:
        """The two honoured list properties, read back out of the join table."""
        rows = self._session.execute(
            select(models.UserLibraryAccess)
            .where(models.UserLibraryAccess.user_id == user_id)
            .order_by(models.UserLibraryAccess.library_id)
        ).scalars()
        viewable, deletable = [], []
        for row in rows:
            if row.can_view:
                viewable.append(row.library_id)
            if row.can_delete:
                deletable.append(row.library_id)
        return LibraryAccess(tuple(viewable), tuple(deletable))

    def set_library_access(self, user_id: str, access: LibraryAccess) -> None:
        """Replace this user's library rows wholesale.

        Deleted and rewritten rather than merged, because the two lists arrive as lists: a library
        absent from `EnabledFolders` is a library the user may not see, and a merge would keep the
        row that says otherwise.
        """
        self._session.execute(
            delete(models.UserLibraryAccess).where(models.UserLibraryAccess.user_id == user_id)
        )
        for library_id in sorted(set(access.enabled_folders) | set(access.deletion_folders)):
            self._session.add(
                models.UserLibraryAccess(
                    user_id=user_id,
                    library_id=library_id,
                    can_view=library_id in access.enabled_folders,
                    can_delete=library_id in access.deletion_folders,
                )
            )
        self._session.flush()

    def set_password_hash(self, user_id: str, password_hash: str | None) -> None:
        """Used by the rehash-on-login rule, which is the only moment the plaintext exists."""
        self._require(user_id).password_hash = password_hash

    def record_failed_attempt(self, user_id: str) -> int:
        """Increment and return the new count, so a caller does not have to read it back."""
        row = self._require(user_id)
        row.invalid_login_attempt_count += 1
        self._session.flush()
        return row.invalid_login_attempt_count

    def record_success(self, user_id: str, when: datetime | None = None) -> None:
        """One success resets the counter, per spec section 3.3. Both halves, together, because
        doing them at two call sites is how one of them gets forgotten."""
        row = self._require(user_id)
        row.invalid_login_attempt_count = 0
        row.last_login_date = when or utc_now()
        row.last_activity_date = row.last_login_date

    def set_policy(self, user_id: str, columns: dict[str, object], extra: dict[str, Any]) -> None:
        """Write the honoured flags into their columns and everything else into the blob.

        The two halves land together because they are one document: writing the columns without
        the blob leaves a client's unknown properties behind, and writing the blob without the
        columns changes nothing anybody enforces.
        """
        row = self._require(user_id)
        for column, value in columns.items():
            setattr(row, column, value)
        row.policy_extra = dict(extra)
        self._session.flush()

    def replace_configuration(self, user_id: str, configuration: dict[str, object]) -> None:
        """Replaces, per spec section 3.6 - `POST /Users/Configuration` is not a merge."""
        self._require(user_id).configuration = dict(configuration)

    def _require(self, user_id: str) -> models.User:
        row = self._session.get(models.User, user_id)
        if row is None:
            raise LookupError(f"no user {user_id}")
        return row


# --------------------------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------------------------


class TokenRepository:
    """Live credentials. The plaintext exists here and in the response, and nowhere else."""

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def issue(
        self,
        user_id: str,
        device_id: str,
        client: str = "",
        device_name: str = "",
        app_version: str = "",
        when: datetime | None = None,
    ) -> IssuedToken:
        """Generate a token, store its hash, and return the plaintext once.

        There is deliberately no `store(token)`. The secret is generated inside this method, so
        there is no moment at which a caller holds one that this repository has not already
        reduced to a hash.
        """
        moment = when or utc_now()
        secret = secrets.token_hex(TOKEN_BYTES)
        row = models.AccessToken(
            token_sha256=token_digest(secret),
            user_id=user_id,
            device_id=device_id,
            client=client,
            device_name=device_name,
            app_version=app_version,
            created=moment,
            last_used=moment,
        )
        self._session.add(row)
        self._session.flush()
        return IssuedToken(secret=secret, record=_token(row))

    def resolve(self, token: str) -> AccessToken | None:
        """The lookup every authenticated request makes: hash, then primary key."""
        row = self._session.get(models.AccessToken, token_digest(token))
        return _token(row) if row is not None else None

    def for_user(self, user_id: str) -> list[AccessToken]:
        rows = self._session.execute(
            select(models.AccessToken).where(models.AccessToken.user_id == user_id)
        ).scalars()
        return [_token(row) for row in rows]

    def touch(self, token_sha256: str, when: datetime) -> None:
        """Advance `last_used`. Called by the flush, not by the request (plan section 6.5)."""
        row = self._session.get(models.AccessToken, token_sha256)
        if row is not None:
            row.last_used = when

    def revoke(self, token_sha256: str) -> None:
        self._session.execute(
            delete(models.AccessToken).where(models.AccessToken.token_sha256 == token_sha256)
        )

    def revoke_device(self, user_id: str, device_id: str) -> int:
        """Every token this user holds on this device. Re-authenticating from a known device
        invalidates the previous one, with no window in which both work (spec section 3.8)."""
        # `Session.execute` is typed as returning `Result`, which has no row count; a DELETE
        # always produces a `CursorResult`, which does. The cast says that rather than hiding it.
        result = cast(
            "CursorResult[Any]",
            self._session.execute(
                delete(models.AccessToken).where(
                    models.AccessToken.user_id == user_id,
                    models.AccessToken.device_id == device_id,
                )
            ),
        )
        return int(result.rowcount)


# --------------------------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------------------------


class SessionRepository:
    """One row per `(user, device)`, which the schema enforces rather than trusting."""

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def by_id(self, session_id: str) -> Session | None:
        row = self._session.get(models.Session, session_id)
        return _session(row) if row is not None else None

    def by_device(self, user_id: str, device_id: str) -> Session | None:
        row = self._session.execute(
            select(models.Session).where(
                models.Session.user_id == user_id, models.Session.device_id == device_id
            )
        ).scalar_one_or_none()
        return _session(row) if row is not None else None

    def for_user(self, user_id: str) -> list[Session]:
        rows = self._session.execute(
            select(models.Session)
            .where(models.Session.user_id == user_id)
            .order_by(models.Session.last_activity_date.desc())
        ).scalars()
        return [_session(row) for row in rows]

    def all(self) -> list[Session]:
        """What an administrator sees at `/Sessions` (spec section 3.8)."""
        rows = self._session.execute(
            select(models.Session).order_by(models.Session.last_activity_date.desc())
        ).scalars()
        return [_session(row) for row in rows]

    def upsert(self, session: Session) -> Session:
        """Create the row for this device, or replace what is there.

        Replace rather than accumulate: the unique constraint on `(user_id, device_id)` means the
        alternative is a constraint violation rather than a second row, which is the failure mode
        worth having.
        """
        row = self._session.execute(
            select(models.Session).where(
                models.Session.user_id == session.user_id,
                models.Session.device_id == session.device_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = models.Session(
                id=session.id or new_id(),
                user_id=session.user_id,
                device_id=session.device_id,
            )
            self._session.add(row)
        row.client = session.client
        row.device_name = session.device_name
        row.app_version = session.app_version
        row.remote_end_point = session.remote_end_point
        row.last_activity_date = session.last_activity_date or utc_now()
        row.last_playback_check_in = session.last_playback_check_in
        row.capabilities = dict(session.capabilities)
        self._session.flush()
        return _session(row)

    def set_capabilities(self, session_id: str, capabilities: dict[str, object]) -> None:
        """Stored whole and reflected back. v1 acts on none of it, and a client that posts
        capabilities and then does not see them has observed a difference (spec section 3.8)."""
        row = self._session.get(models.Session, session_id)
        if row is not None:
            row.capabilities = dict(capabilities)

    def touch(self, session_id: str, when: datetime) -> None:
        row = self._session.get(models.Session, session_id)
        if row is not None:
            row.last_activity_date = when

    def remove(self, session_id: str) -> None:
        self._session.execute(delete(models.Session).where(models.Session.id == session_id))

    def remove_device(self, user_id: str, device_id: str) -> None:
        self._session.execute(
            delete(models.Session).where(
                models.Session.user_id == user_id, models.Session.device_id == device_id
            )
        )


__all__ = [
    "TOKEN_BYTES",
    "SessionRepository",
    "TokenRepository",
    "UserRepository",
    "normalise_name",
    "token_digest",
]
