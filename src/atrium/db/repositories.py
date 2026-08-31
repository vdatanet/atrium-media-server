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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.compat.guids import new_id
from atrium.db import models
from atrium.domain.items import (
    BY_NAME,
    MEDIA_TYPE_OF,
    CollectionType,
    Item,
    ItemType,
    MediaSource,
)
from atrium.domain.library import Library
from atrium.domain.media import (
    DeliveredFile,
    DiscoveredSubtitles,
    InspectedStream,
    MediaInspection,
    StreamKind,
    VideoRange,
    VideoRangeType,
    renumber,
)
from atrium.domain.playlists import Playlist, Share, may_read, moved
from atrium.domain.playstate import UserItemData
from atrium.domain.session import AccessToken, IssuedToken, Session
from atrium.domain.sorting import sort_name
from atrium.domain.user import LibraryAccess, User
from atrium.library.identity import for_name
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind
from atrium.metadata.byname import fold_for_search, genre_type, identity_of, person_type_of
from atrium.metadata.merge import MetadataChanges
from atrium.metadata.model import Field, MetadataField, PersonCredit, PersonKind

if TYPE_CHECKING:
    # Type-only: `db/item_queries.py` imports this module for `inspection_of`, so importing it back
    # at runtime would be a cycle. `PlaylistRepository` is handed one rather than building one, and
    # the annotation is all that is needed to say which one.
    from atrium.db.item_queries import ItemQueryRepository

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

    def touch(self, session_id: str, when: datetime, playback: datetime | None = None) -> None:
        """Advance the activity timestamp, and the playback check-in when one is given.

        Both in one statement because they are flushed together on one pass (007 plan section
        6.6). `last_playback_check_in` had **no writer at all** until 007: 002 created the column
        and reflected it back, and nothing ever moved it, so a session that had played something
        reported `0001-01-01` for ever.
        """
        row = self._session.get(models.Session, session_id)
        if row is not None:
            row.last_activity_date = when
            if playback is not None:
                row.last_playback_check_in = playback

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


def _library(row: models.Library, roots: list[str]) -> Library:
    return Library(
        id=row.id,
        name=row.name,
        collection_type=CollectionType(row.collection_type),
        roots=tuple(roots),
        case_sensitive_identity=row.case_sensitive_identity,
    )


class LibraryRepository:
    """Configured libraries and their roots.

    **There is no method here that changes `case_sensitive_identity`.** That is the enforcement,
    not a convention: `rename` and `set_roots` take the fields an operator may edit, and the flag
    is not among them, so no caller can change it by forgetting a rule. `library/config.py` refuses
    the request with an explanation; this refuses it by having nowhere to put it.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def by_id(self, library_id: str) -> Library | None:
        row = self._session.get(models.Library, library_id)
        return _library(row, self._roots(library_id)) if row is not None else None

    def all(self) -> list[Library]:
        rows = list(
            self._session.execute(select(models.Library).order_by(models.Library.name)).scalars()
        )
        return [_library(row, self._roots(row.id)) for row in rows]

    def add(self, library: Library) -> Library:
        """Domain object in, domain object out. The flag arrives here once and never again."""
        row = models.Library(
            id=library.id or new_id(),
            name=library.name,
            collection_type=library.collection_type.value,
            case_sensitive_identity=library.case_sensitive_identity,
        )
        self._session.add(row)
        self._session.flush()
        self._write_roots(row.id, library.roots)
        return _library(row, self._roots(row.id))

    def rename(self, library_id: str, name: str) -> None:
        self._require(library_id).name = name

    def set_roots(self, library_id: str, roots: tuple[str, ...]) -> None:
        """Replaces rather than merges, which is what an operator editing a list means by it."""
        self._require(library_id)
        self._session.execute(
            delete(models.LibraryRoot).where(models.LibraryRoot.library_id == library_id)
        )
        self._write_roots(library_id, roots)

    def remove(self, library_id: str) -> None:
        """Takes the library's roots and every item under it, by the database's own cascade."""
        self._session.execute(delete(models.Library).where(models.Library.id == library_id))

    def _roots(self, library_id: str) -> list[str]:
        rows = self._session.execute(
            select(models.LibraryRoot.path)
            .where(models.LibraryRoot.library_id == library_id)
            .order_by(models.LibraryRoot.path)
        )
        return list(rows.scalars())

    def _write_roots(self, library_id: str, roots: tuple[str, ...]) -> None:
        # Deduplicated and ordered, so that two roots given twice are one row and the order a
        # caller happened to pass them in is not part of the configuration.
        for path in sorted(set(roots)):
            self._session.add(models.LibraryRoot(library_id=library_id, path=path))
        self._session.flush()

    def _require(self, library_id: str) -> models.Library:
        row = self._session.get(models.Library, library_id)
        if row is None:
            raise LookupError(f"no library {library_id}")
        return row


def _item(row: models.Item, sources: list[models.ItemSource]) -> Item:
    return Item(
        id=row.id,
        type=ItemType(row.type),
        name=row.name,
        library_id=row.library_id,
        parent_id=row.parent_id,
        sort_name=row.sort_name,
        sources=tuple(
            MediaSource(relative_path=one.relative_path, size=one.size, mtime_ns=one.mtime_ns)
            for one in sorted(sources, key=lambda one: one.part_index)
        ),
        index_number=row.index_number,
        parent_index_number=row.parent_index_number,
        end_index_number=row.end_index_number,
        date_created=row.date_created,
        date_modified=row.date_modified,
        removed_at=row.removed_at,
    )


class ItemRepository:
    """Everything a library holds, and the two ends of an item's life.

    **Nothing here deletes a row.** `mark_removed` sets `removed_at` and `revive` clears it; the
    row stays either way, which is what makes 003 spec section 3.8's "user data outlives items"
    true. A file that disappears and comes back - a re-download, a remount, a share slow to mount -
    costs the user nothing, because the identifier is derived from the path and the path has not
    changed. Hard deletion is a maintenance action and lives in `library/maintenance.py`, which a
    scan does not import.

    Until T16's guards were green this class had no removal method at all, so the scanner was
    *incapable* of destroying a library rather than merely careful. `update` still cannot reach
    `removed_at`: changing what an item **is** and changing whether it is **there** are different
    operations, and a method that did both would be a removal path wearing another name.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def by_library(self, library_id: str) -> dict[str, Item]:
        """Every item in one library, by identifier, with its sources attached.

        Sources are fetched in one further query rather than through the relationship, which is
        `lazy="raise"`: a scan reads the whole library once and then compares in memory, so two
        queries is the whole cost regardless of how many items there are.
        """
        rows = list(
            self._session.execute(
                select(models.Item).where(models.Item.library_id == library_id)
            ).scalars()
        )
        if not rows:
            return {}
        sources: dict[str, list[models.ItemSource]] = {}
        for source in self._session.execute(
            select(models.ItemSource).where(models.ItemSource.item_id.in_([row.id for row in rows]))
        ).scalars():
            sources.setdefault(source.item_id, []).append(source)
        return {row.id: _item(row, sources.get(row.id, [])) for row in rows}

    def visible(self, library_id: str) -> dict[str, Item]:
        """What a query sees: everything that has not been removed.

        The shape 005 will use. `by_library` deliberately returns removed items too, because a scan
        has to find them to bring one back when its file returns.
        """
        return {
            item_id: item
            for item_id, item in self.by_library(library_id).items()
            if not item.is_removed
        }

    def mark_removed(self, item_ids: Sequence[str], when: datetime) -> int:
        """The file is gone. The row is not (003 plan section 6.6)."""
        if not item_ids:
            return 0
        result = self._session.execute(
            update(models.Item)
            .where(models.Item.id.in_(list(item_ids)), models.Item.removed_at.is_(None))
            .values(removed_at=when)
        )
        self._session.flush()
        return cast("CursorResult[Any]", result).rowcount

    def revive(self, item_ids: Sequence[str]) -> int:
        """The file came back, and it is the same item: same path, same derivation, same id."""
        if not item_ids:
            return 0
        result = self._session.execute(
            update(models.Item)
            .where(models.Item.id.in_(list(item_ids)), models.Item.removed_at.is_not(None))
            .values(removed_at=None)
        )
        self._session.flush()
        return cast("CursorResult[Any]", result).rowcount

    def add(self, item: Item) -> None:
        self._session.add(
            models.Item(
                id=item.id,
                library_id=item.library_id,
                parent_id=item.parent_id,
                type=item.type.value,
                name=item.name,
                sort_name=item.sort_name,
                # **The third derivation of the same string, and it was missing.** `name`,
                # `sort_name` and `name_folded` all come from the item's name; the first two were
                # written here and the third was left to `MetadataRepository.apply`, which only
                # sets it when a refresh *changes* the name. An item scanned and not yet
                # refreshed therefore had an empty folded name - and an empty folded name is
                # invisible to `searchTerm` and `nameStartsWith`, silently, while the item itself
                # looks perfectly correct in every list. Found by 005 T6.
                name_folded=fold_for_search(item.name),
                index_number=item.index_number,
                parent_index_number=item.parent_index_number,
                end_index_number=item.end_index_number,
                date_created=item.date_created,
                date_modified=item.date_modified,
                removed_at=item.removed_at,
            )
        )
        self._session.flush()
        self._write_sources(item)

    def update(self, item: Item) -> None:
        """Everything a rescan can change. `id` is not among them - it is what identifies the row.

        `removed_at` is deliberately absent too: clearing it is a *revival*, which is T17's, and a
        method that could set it either way would be a removal path by another name.

        **`name` and `sort_name` are absent once a refresh has resolved them** (004 T10). The
        scanner names an item when it *creates* it, from its path; after that those two columns
        belong to 004, which resolves them from sidecars and tags and writes them through
        `MetadataRepository.apply`. Without this, the two features overwrite one column on every
        scan in turn - the scan re-deriving `The Matrix` from the filename, the refresh restoring
        `The Matrix (1999)` from the sidecar - and every rescan of an unchanged library reports
        every item as updated, forever.

        A retitled track still follows: its title tag reaches the name through the refresh, which
        reads the same file.
        """
        row = self._session.get(models.Item, item.id)
        if row is None:
            raise LookupError(f"no item {item.id}")
        row.parent_id = item.parent_id
        if row.metadata_refreshed_at is None:
            row.name = item.name
            row.sort_name = item.sort_name
            row.name_folded = fold_for_search(item.name)
        row.index_number = item.index_number
        row.parent_index_number = item.parent_index_number
        row.end_index_number = item.end_index_number
        row.date_modified = item.date_modified
        self._session.execute(delete(models.ItemSource).where(models.ItemSource.item_id == item.id))
        self._write_sources(item)

    def _write_sources(self, item: Item) -> None:
        for part_index, source in enumerate(item.sources):
            self._session.add(
                models.ItemSource(
                    item_id=item.id,
                    part_index=part_index,
                    relative_path=source.relative_path,
                    size=source.size,
                    mtime_ns=source.mtime_ns,
                )
            )
        self._session.flush()


class MetadataRepository:
    """The only way 004's resolved metadata reaches the database.

    `metadata/` must not write the item table directly (architecture section 1), and this is the
    other end of that rule: `refresh.py` is the single caller, and everything it can do is one of
    three methods.

    **`apply` writes one item completely or not at all.** It never commits - the caller's unit of
    work owns that - but within a call it flushes as a whole, so a failure part-way leaves the
    caller's transaction rollable back with no half-written item in it. That matters more here
    than elsewhere in this module: an item's genres live in a second table, and an item with its
    new name and its old genres is worse than an item nothing touched.

    **A by-name row is derived, so garbage collection is safe here** in a way it is not for 003's
    containers. Deleting a genre nothing references loses only which spelling created it - and the
    next reference recreates the row with the same identifier, because the identifier comes from
    the folded name and nothing else (004 plan section 6.7).
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    # -- reading, for the merge's "what does the item already have?" ---------------------------

    def values_of(self, item_id: str) -> dict[Field, object]:
        """What the item currently holds, in the merge's vocabulary.

        The merge needs this to answer "is this field empty?", which is the whole left-hand column
        of its matrix. Lists come back from the join tables in their stored order.
        """
        row = self._session.get(models.Item, item_id)
        if row is None:
            raise LookupError(f"no item {item_id}")

        values: dict[Field, object] = {}
        for field, column in _SCALAR_COLUMNS.items():
            if field in _THE_SCANNER_OWNS:
                continue
            found = getattr(row, column)
            if found is not None:
                values[field] = found
        if row.provider_ids:
            values[Field.PROVIDER_IDS] = dict(row.provider_ids)
        if row.tags:
            values[Field.TAGS] = list(row.tags)
        if row.forced_sort_name:
            values[Field.SORT_NAME] = row.forced_sort_name
        images = self.images_of(item_id)
        if images:
            values[Field.IMAGES] = images

        genres = self._joined(models.ItemGenre, item_id, models.ItemGenre.position)
        if genres:
            values[Field.GENRES] = [one.name for one in genres]
        studios = self._joined(models.ItemStudio, item_id, models.ItemStudio.position)
        if studios:
            values[Field.STUDIOS] = [one.name for one in studios]
        people = self._joined(models.ItemPerson, item_id, models.ItemPerson.sort_order)
        if people:
            values[Field.PEOPLE] = [
                PersonCredit(
                    name=one.name,
                    kind=PersonKind(one.person_type),
                    role=one.role,
                    sort_order=one.sort_order,
                )
                for one in people
            ]
        for field, credit in ((Field.ARTISTS, "artist"), (Field.ALBUM_ARTISTS, "album_artist")):
            names = [
                one.name
                for one in self._joined(models.ItemArtist, item_id, models.ItemArtist.position)
                if one.credit == credit
            ]
            if names:
                values[field] = names
        return values

    def images_of(self, item_id: str) -> list[ImageAssociation]:
        """The associations as they are stored, in the shape `apply` takes.

        Read back so the merge can tell that an item's artwork is already what a rescan just found
        - without it, every image row in the library is rewritten on every refresh.
        """
        return [
            ImageAssociation(
                kind=ImageKind(row.image_type),
                index=row.image_index,
                source_kind=SourceKind(row.source_kind),
                relative_path=row.relative_path,
                width=row.width,
                height=row.height,
                tag=row.tag,
            )
            for row in self._joined(models.ItemImage, item_id, models.ItemImage.image_index)
        ]

    def locks_of(self, item_id: str) -> tuple[bool, frozenset[MetadataField]]:
        """`(whole item locked, the fields locked)`. Unknown values in the stored list are
        dropped, the same way the sidecar parser drops them: a lock written by a newer build is
        not a reason to refuse the ones this build understands."""
        row = self._session.get(models.Item, item_id)
        if row is None:
            raise LookupError(f"no item {item_id}")
        known = {member.value: member for member in MetadataField}
        return row.is_locked, frozenset(
            known[one] for one in (row.locked_fields or []) if one in known
        )

    def refreshed(self, library_id: str) -> set[str]:
        """Items a refresh has already resolved, so the scanner no longer owns their names.

        One query, asked once per scan. The alternative was putting `metadata_refreshed_at` on the
        domain item, which would have carried 004's bookkeeping into the vocabulary every layer
        shares for the sake of one boolean.
        """
        return set(
            self._session.execute(
                select(models.Item.id).where(
                    models.Item.library_id == library_id,
                    models.Item.metadata_refreshed_at.is_not(None),
                )
            ).scalars()
        )

    def pending(self, library_id: str) -> list[str]:
        """Items a provider failure left wanting another go (AC-8).

        The next scan retries these **even when their files did not change**, which is the one
        thing in 004 that reads an item the change-detection signal would have skipped.
        """
        return list(
            self._session.execute(
                select(models.Item.id).where(
                    models.Item.library_id == library_id,
                    models.Item.refresh_pending.is_(True),
                )
            ).scalars()
        )

    # -- writing --------------------------------------------------------------------------------

    def apply(
        self,
        item_id: str,
        changes: MetadataChanges,
        *,
        is_locked: bool | None = None,
        locked_fields: Sequence[MetadataField] | None = None,
        refresh_pending: bool | None = None,
        refreshed_at: datetime | None = None,
    ) -> None:
        """Everything one refresh decided about one item.

        The lock arguments are separate from `changes` because a lock is not a value a provider
        supplied - it constrains what every provider may do, and it arrives from the sidecar
        rather than from the merge (004 T3).
        """
        row = self._session.get(models.Item, item_id)
        if row is None:
            raise LookupError(f"no item {item_id}")

        values = dict(changes.values)
        for field, column in _SCALAR_COLUMNS.items():
            if field in values:
                setattr(row, column, values[field])

        if Field.NAME in values:
            row.name = str(values[Field.NAME])
            row.name_folded = fold_for_search(row.name)
        if Field.TAGS in values:
            row.tags = _strings(values[Field.TAGS])
        if Field.SORT_NAME in values:
            row.forced_sort_name = str(values[Field.SORT_NAME])
        if Field.NAME in values or Field.SORT_NAME in values:
            # A name that changed has a sort name that changed with it, and an explicit sort title
            # replaces the derivation entirely (003 section 3.7.3). Recomputed here rather than by
            # the caller, so the two columns cannot disagree.
            forced = row.forced_sort_name
            row.sort_name = sort_name(_item(row, []), forced=forced)
        if Field.PROVIDER_IDS in values:
            row.provider_ids = dict(cast("Mapping[str, str]", values[Field.PROVIDER_IDS]))

        if is_locked is not None:
            row.is_locked = is_locked
        if locked_fields is not None:
            row.locked_fields = [one.value for one in locked_fields]
        if refresh_pending is not None:
            row.refresh_pending = refresh_pending
        row.metadata_refreshed_at = refreshed_at if refreshed_at is not None else utc_now()

        if Field.YEAR in values and values[Field.YEAR] is not None:
            # **The by-name row for a year, which nothing created until 005 T8.** A `Year` is
            # referenced by `items.production_year` rather than by a join table, so it has no
            # write path of its own the way a genre does - and `collect_by_name_garbage` below
            # has always protected these rows on the assumption that something made them. Without
            # this, `/Years` lists nothing and `GET /Items/{yearId}` answers 404 for a year the
            # library plainly has.
            self.ensure_by_name(ItemType.YEAR, str(values[Field.YEAR]))

        kind = ItemType(row.type)
        if Field.GENRES in values:
            self._write_genres(item_id, kind, _strings(values[Field.GENRES]))
        if Field.STUDIOS in values:
            self._write_studios(item_id, _strings(values[Field.STUDIOS]))
        if Field.PEOPLE in values:
            self._write_people(item_id, _credits(values[Field.PEOPLE]))
        if Field.ARTISTS in values or Field.ALBUM_ARTISTS in values:
            self._write_artists(
                item_id,
                row.library_id,
                _strings(values.get(Field.ARTISTS, [])) if Field.ARTISTS in values else None,
                _strings(values.get(Field.ALBUM_ARTISTS, []))
                if Field.ALBUM_ARTISTS in values
                else None,
            )
        if Field.IMAGES in values:
            self._write_images(item_id, values[Field.IMAGES])

        self._session.flush()

    def ensure_by_name(self, kind: ItemType, spelling: str) -> str:
        """The identifier of the by-name row for this spelling, creating the row if it is new.

        **The incoming spelling becomes the display name only when no row exists.** An existing
        row is reused rather than renamed, so the first spelling seen is the one `/Genres` shows -
        which is the reference's behaviour and the reason two files spelling one genre two ways
        produce one item with one name (AC-14).
        """
        item_id = identity_of(kind, spelling)
        if self._session.get(models.Item, item_id) is None:
            display = spelling.strip() or spelling
            self._session.add(
                models.Item(
                    id=item_id,
                    library_id=None,
                    parent_id=None,
                    type=kind.value,
                    name=display,
                    sort_name=sort_name(Item(id=item_id, type=kind, name=display, library_id=None)),
                    name_folded=fold_for_search(display),
                )
            )
            self._session.flush()
        return item_id

    def collect_by_name_garbage(self) -> int:
        """Delete every by-name row nothing references. Returns how many went.

        Safe here in a way it is not for 003's containers, because a by-name row is **derivable**:
        the next reference recreates it with the same identifier, losing only which spelling came
        first - which is exactly what the reference loses too.

        A `Year` row is referenced by `items.production_year` rather than by a join table, which is
        why it is checked separately: it is the one by-name kind with no join table at all.
        """
        referenced: set[str] = set()
        for column in (
            models.ItemGenre.genre_item_id,
            models.ItemStudio.studio_item_id,
            models.ItemPerson.person_item_id,
        ):
            referenced.update(self._session.execute(select(column)).scalars())

        years = {
            identity_of(ItemType.YEAR, str(year))
            for year in self._session.execute(
                select(models.Item.production_year).where(models.Item.production_year.is_not(None))
            ).scalars()
        }
        referenced.update(years)

        collectable = [
            row_id
            for row_id in self._session.execute(
                select(models.Item.id).where(models.Item.type.in_([one.value for one in BY_NAME]))
            ).scalars()
            if row_id not in referenced
        ]
        if not collectable:
            return 0
        self._session.execute(delete(models.Item).where(models.Item.id.in_(collectable)))
        self._session.flush()
        return len(collectable)

    # -- the join tables ------------------------------------------------------------------------

    def _joined(self, model: Any, item_id: str, order: Any) -> list[Any]:
        return list(
            self._session.execute(
                select(model).where(model.item_id == item_id).order_by(order)
            ).scalars()
        )

    def _replace(self, model: Any, item_id: str) -> None:
        self._session.execute(delete(model).where(model.item_id == item_id))

    def _write_genres(self, item_id: str, kind: ItemType, names: Sequence[str]) -> None:
        """The display string on the join row **and** the by-name row it merges into.

        Two facts, two homes (004 plan section 4): an item's own response carries the spelling its
        file used, while `/Genres` shows the first spelling anybody used. Deriving either from the
        other loses the other.
        """
        self._replace(models.ItemGenre, item_id)
        genre_kind = genre_type(kind)
        for position, name in enumerate(names):
            self._session.add(
                models.ItemGenre(
                    item_id=item_id,
                    position=position,
                    name=name,
                    genre_item_id=self.ensure_by_name(genre_kind, name),
                )
            )

    def _write_studios(self, item_id: str, names: Sequence[str]) -> None:
        self._replace(models.ItemStudio, item_id)
        for position, name in enumerate(names):
            self._session.add(
                models.ItemStudio(
                    item_id=item_id,
                    position=position,
                    name=name,
                    studio_item_id=self.ensure_by_name(ItemType.STUDIO, name),
                )
            )

    def _write_people(self, item_id: str, people: Sequence[PersonCredit]) -> None:
        """**Order and role are metadata, not an accident of insertion** (spec section 3.7 rule 2).

        `sort_order` is the position in the list rather than whatever the source put in an
        `<order>` element: those are sparse and sometimes duplicated, and the column is the join
        table's primary key. What the source said is honoured by the *order of the list*, which
        the merge and the parser preserve.
        """
        self._replace(models.ItemPerson, item_id)
        for position, person in enumerate(people):
            self._session.add(
                models.ItemPerson(
                    item_id=item_id,
                    sort_order=position,
                    person_type=person_type_of(person.kind),
                    name=person.name,
                    role=person.role,
                    person_item_id=self.ensure_by_name(ItemType.PERSON, person.name),
                )
            )

    def _write_artists(
        self,
        item_id: str,
        library_id: str | None,
        artists: Sequence[str] | None,
        album_artists: Sequence[str] | None,
    ) -> None:
        """`/Artists` and `/Artists/AlbumArtists` are the `credit` column and nothing else.

        An artist is a `MusicArtist`, which is **per-library** rather than by-name in Atrium -
        the accepted gap of docs/compatibility/behaviours.md section 5.3 - so the row it points at
        is derived from `(type, library, name)` the way 003 derives every other one, and it is
        the *scanner* that creates it.

        **The link is therefore optional and the name is not.** The scanner creates one artist per
        album artist; a track's performers are frequently other people, so a credit naming one has
        a name and no item behind it. Creating the missing item here would put a tree item outside
        the scan that builds the tree, and the next scan would mark it removed - a row that
        appears and disappears every other scan. Revision 0004 carries the argument.
        """
        if library_id is None:
            return
        for credit, names in (("artist", artists), ("album_artist", album_artists)):
            if names is None:
                continue
            self._session.execute(
                delete(models.ItemArtist).where(
                    models.ItemArtist.item_id == item_id, models.ItemArtist.credit == credit
                )
            )
            for position, name in enumerate(names):
                self._session.add(
                    models.ItemArtist(
                        item_id=item_id,
                        credit=credit,
                        position=position,
                        name=name,
                        artist_item_id=self._artist_item(library_id, name),
                    )
                )

    def _artist_item(self, library_id: str, name: str) -> str | None:
        """The `MusicArtist` this credit links to, or `None` when the scanner made no such item."""
        artist_id = for_name(ItemType.MUSIC_ARTIST, library_id, name)
        return artist_id if self._session.get(models.Item, artist_id) is not None else None

    def _write_images(self, item_id: str, images: object) -> None:
        """Dimensions and tag are **never** null here, which the schema also enforces: 005 emits
        `PrimaryImageAspectRatio` from these rows before 006 serves a byte.

        The value must be `ImageAssociation`s rather than `ArtworkFile`s: which base a path is
        relative to is `source_kind`, and `metadata/artwork.associate` is the one place that
        decision is made. Anything else is ignored rather than guessed at.
        """
        self._replace(models.ItemImage, item_id)
        if not isinstance(images, Sequence):
            return
        for image in images:
            if not isinstance(image, ImageAssociation):
                continue
            self._session.add(
                models.ItemImage(
                    item_id=item_id,
                    image_type=image.kind.value,
                    image_index=image.index,
                    source_kind=image.source_kind.value,
                    relative_path=image.relative_path,
                    width=image.width,
                    height=image.height,
                    tag=image.tag,
                )
            )


# --------------------------------------------------------------------------------------------
# User data
# --------------------------------------------------------------------------------------------


class UserDataRepository:
    """One user's state for one item, read and written by the item's **derived identity**.

    Two methods, because that is all a writer needs: the transitions in `domain/playstate.py`
    decide what a row becomes, and this decides where it lives. Everything about *which* items a
    cascade touches is the query layer's, which already knows what a user can see.

    **`item_key` is not a foreign key, and a writer is exactly who would add one.** The column
    references nothing on purpose (003 spec section 3.8, and the argument is on
    `models.ItemUserData`): the row outliving the item is the guarantee that a network share
    mounting slowly does not delete a user's favourites and resume positions. Referential hygiene
    here buys nothing - the key is derived from the path, so it is restored the moment the file
    is - and costs a user's history, permanently, with a rescan as the only symptom.

    Absence is a state rather than a gap: a user who has never touched an item has no row, and
    `get` answers the default record instead of `None` so that no caller has to decide what
    "never played" means a second time.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def get(self, user_id: str, item_key: str) -> UserItemData:
        row = self._session.get(models.ItemUserData, (user_id, item_key))
        if row is None:
            return UserItemData()
        return UserItemData(
            is_favorite=row.is_favorite,
            played=row.played,
            play_count=row.play_count,
            playback_position_ticks=row.playback_position_ticks,
            last_played_date=row.last_played_date,
        )

    def put(self, user_id: str, item_key: str, data: UserItemData) -> None:
        """Upsert the five stored columns, and only those.

        `unplayed_count` is not written here and has no column: it is a **rollup** the query layer
        computes per page from the subtree (005 plan section 5). Storing it would be the cached
        aggregate spec section 3.5 forbids, and this is the method where somebody would add it.
        """
        row = self._session.get(models.ItemUserData, (user_id, item_key))
        if row is None:
            row = models.ItemUserData(user_id=user_id, item_key=item_key)
            self._session.add(row)
        row.is_favorite = data.is_favorite
        row.played = data.played
        row.play_count = data.play_count
        row.playback_position_ticks = data.playback_position_ticks
        row.last_played_date = data.last_played_date
        self._session.flush()


# --------------------------------------------------------------------------------------------
# Playlists (009)
# --------------------------------------------------------------------------------------------


class PlaylistRepository:
    """The only way a playlist is read or written, and the reason there is only one.

    **Two reads and six writes.** Both reads take a `User`, which is 009 plan section 9's second
    risk written as a signature: an entries query that forgot the reader is how section 3.17's
    divergence stops applying on one route, silently, in a change that looks like a refactor.
    `tests/unit/test_playlist_repository.py` asserts the classification by reflection, so a ninth
    method has to declare which of the two it is before the suite goes green again.

    **The stored order never leaves this class.** `entries` answers what its caller may see, and
    the move takes its arithmetic *in* rather than handing the full order out (`reorder`): a
    public "the whole order, unfiltered" would be a read with nothing to filter it, next to a
    read that filters, which is the shape the risk above describes. It is also the only way the
    read and the write that depends on it are one transaction.

    **`media_type` is read, never re-derived** (009 plan section 4.2). The column is filled at
    creation and never revised, `ItemQueries._hydrate` reads the same column for the `/Items`
    path, and a repository that recomputed the value from the entries would make one playlist
    report two media types depending on which route asked.
    """

    def __init__(self, session: OrmSession, queries: ItemQueryRepository) -> None:
        self._session = session
        self._queries = queries

    # -- reads -------------------------------------------------------------------------------

    def by_id(self, playlist_id: str, user: User) -> Playlist | None:
        """The playlist's permission facts, or `None` if this caller may not learn it exists.

        **The `User` is an existence filter and not the decision.** Deciding is
        `domain/playlists.py`'s, over the object this returns; what happens here is the answer
        009 spec section 3.3 gives to a caller who may not read the playlist - `404` rather than
        `403`, so the id discloses nothing.

        **And an administrator is handed the row they may not read**, which looks like a hole and
        is the one thing that makes T12 writable: deletion is the single operation an
        administrator may perform on a playlist they neither own nor are shared
        `[source: MediaBrowser.Controller/Playlists/Playlist.cs:261-264 @ v10.11.11]`, so a door
        that filtered by `may_read` would answer `404` to the one caller spec section 3.6 says
        must succeed. Every read route still applies `may_read` to what comes back - an
        administrator reading somebody's private playlist is `404` (spec section 3.7's last row),
        and it is that call, not this one, that says so.
        """
        row = self._session.get(models.Playlist, playlist_id)
        item = self._session.get(models.Item, playlist_id)
        if row is None or item is None or item.removed_at is not None:
            return None
        playlist = Playlist(
            id=row.item_id,
            name=item.name,
            owner_user_id=row.owner_user_id,
            is_public=row.is_public,
            media_type=row.media_type,
            shares=self._shares(playlist_id),
        )
        if may_read(playlist, user) or user.is_administrator:
            return playlist
        return None

    def entries(self, playlist_id: str, user: User) -> list[str]:
        """The item identifiers this reader may see, in the playlist's order.

        Two exclusions, and they are one call: an entry whose item is missing or soft-deleted, and
        an entry in a library this reader may not open. The first is the reference's own behaviour
        `[source: MediaBrowser.Controller/Entities/Folder.cs:1637-1643 @ v10.11.11]`; the second
        is 009's divergence (behaviours section 3.17), and both fall out of asking
        `ItemQueryRepository` the same question `/Items` asks rather than writing a second
        predicate here.

        Constant in statements: the order, then one question about the whole page of keys.
        """
        stored = self._order(playlist_id)
        visible = self._queries.visible_ids(stored, user)
        return [item_key for item_key in stored if item_key in visible]

    # -- writes ------------------------------------------------------------------------------

    def create(self, playlist: Playlist, item_keys: Sequence[str]) -> Playlist:
        """The `items` row, the three playlist rows, and the entries, as one unit.

        The item row is what makes a playlist answer `/Items`, `UserData` and favourites (plan
        section 10's rejected alternative), and it carries **no library**: `library_id IS NULL` is
        half of `ck_items_by_name_has_no_library`, widened by migration 0008 for exactly this row.

        `date_created` is taken here rather than passed in, which is what makes it the one thing
        about a playlist a caller cannot fake - and is why `tests/fixtures/query.py` still writes
        its five worlds itself: a deterministic world needs fixed dates (Principle VII), and a
        fixture built by the code under test cannot fail it.
        """
        ItemRepository(self._session).add(self._item_row(playlist))
        self._session.add(
            models.Playlist(
                item_id=playlist.id,
                owner_user_id=playlist.owner_user_id,
                is_public=playlist.is_public,
                media_type=playlist.media_type,
            )
        )
        for share in playlist.shares:
            self._session.add(
                models.PlaylistShare(
                    playlist_id=playlist.id, user_id=share.user_id, can_edit=share.can_edit
                )
            )
        self._session.flush()
        self.append(playlist.id, item_keys)
        return playlist

    def append(self, playlist_id: str, item_keys: Sequence[str]) -> int:
        """Add what is not there already, at the end, and answer how many that was.

        **The key is not the whole of de-duplication, and the plan said it was.** The primary key
        `(playlist_id, item_key)` does make a duplicate impossible - and an insert that conflicts
        and is skipped leaves the ordinal it would have occupied unused, so a playlist that
        de-duplicated by conflict alone develops holes in a column three other operations assume
        is contiguous. The batch is therefore reduced *before* the ordinals are handed out - which
        is also the only way to answer AC-5's "how many were added" without a second read - and
        the constraint stays as the backstop that turns a concurrent double-add into a loud
        failure instead of a quiet duplicate.

        **First occurrence wins**, within the batch and against what is already stored, which is
        what the reference does when its own de-duplication fires
        `[probe: tools/probe_playlist_writes.py, Jellyfin 10.11.11, 2026-08-31]`.
        """
        stored = self._order(playlist_id)
        already = set(stored)
        wanted: list[str] = []
        for item_key in item_keys:
            if item_key in already:
                continue
            already.add(item_key)
            wanted.append(item_key)
        for offset, item_key in enumerate(wanted):
            self._session.add(
                models.PlaylistEntry(
                    playlist_id=playlist_id, item_key=item_key, ordinal=len(stored) + offset
                )
            )
        self._session.flush()
        return len(wanted)

    def remove(self, playlist_id: str, item_keys: Sequence[str]) -> None:
        """Drop the named entries and close the gaps they leave.

        An identifier that is not in the playlist is not an error (spec section 3.5): the delete
        matches nothing and the renumbering is a no-op. The two statements are one transaction
        because a reader between them would see a hole in the order and page over it.
        """
        if not item_keys:
            return
        self._session.execute(
            delete(models.PlaylistEntry)
            .where(models.PlaylistEntry.playlist_id == playlist_id)
            .where(models.PlaylistEntry.item_key.in_(list(item_keys)))
        )
        self._renumber(playlist_id, self._order(playlist_id))

    def reorder(self, playlist_id: str, entry: str, new_index: int, visible: Sequence[str]) -> None:
        """Move one entry to `new_index` of the list this caller was given.

        **The arithmetic is `domain.playlists.moved` and it happens here**, where plan section 5
        had the caller do it and pass the resulting order in. The caller cannot: computing it
        needs the *stored* order, which is the one thing no route may hold (see the class
        docstring), and reading it in one request and writing it in the next is the read-then-write
        the transaction below exists to prevent.

        Raises `MoveIndexOutOfRangeError` for an index below zero or past the caller's own entry
        count - 009's third divergence, which the route turns into `400` (behaviours section 3.15)
        - and a plain `ValueError` when `visible` is not a sub-sequence of the stored order, which
        is a caller bug and not a client's.
        """
        self._renumber(
            playlist_id, list(moved(self._order(playlist_id), entry, new_index, visible))
        )

    def rename(self, playlist_id: str, name: str) -> None:
        """The one property `POST /Items/{itemId}` may change on a playlist (spec section 3.8).

        **Three columns, not one.** `name`, `sort_name` and `name_folded` are three derivations of
        one string, and writing only the first leaves a playlist that sorts under its old name and
        cannot be found by `searchTerm` or `nameStartsWith` at all - the failure 005 T6 found in
        `ItemRepository.add`, which is one row of the same table. `ItemRepository.update` is not
        the door for this: it writes neither name once a refresh has touched the item, and it
        rewrites the sources a playlist does not have.
        """
        row = self._session.get(models.Item, playlist_id)
        if row is None:
            raise LookupError(f"no playlist {playlist_id}")
        row.name = name
        row.sort_name = sort_name(_item(row, []))
        row.name_folded = fold_for_search(name)
        self._session.flush()

    def delete(self, playlist_id: str) -> None:
        """The item row goes, and the database takes the rest.

        A playlist is the one item that is **not** soft-deleted (plan section 4.5): its identity is
        minted rather than derived, so there is no returning file for a kept row to belong to. The
        entries and the shares follow through `ON DELETE CASCADE`, which is enforced because
        `db/engine.py` turns the pragma on for every connection - a fact migration 0008 had to
        learn the hard way, in the other direction.
        """
        self._session.execute(delete(models.Item).where(models.Item.id == playlist_id))
        self._session.flush()

    # -- internals ---------------------------------------------------------------------------

    def _order(self, playlist_id: str) -> list[str]:
        """The stored order, whole and unfiltered. Private, and the class docstring says why.

        Ordered by `(ordinal, item_key)` rather than by `ordinal` alone: the index is deliberately
        not unique (plan section 4.3), so the tie-break is what keeps two rows that briefly share
        an ordinal from ordering themselves differently on two reads (Principle VII).
        """
        return list(
            self._session.execute(
                select(models.PlaylistEntry.item_key)
                .where(models.PlaylistEntry.playlist_id == playlist_id)
                .order_by(models.PlaylistEntry.ordinal, models.PlaylistEntry.item_key)
            ).scalars()
        )

    def _renumber(self, playlist_id: str, order: Sequence[str]) -> None:
        """Rewrite `ordinal` contiguously from zero, in the order given."""
        rows = {
            row.item_key: row
            for row in self._session.execute(
                select(models.PlaylistEntry).where(models.PlaylistEntry.playlist_id == playlist_id)
            ).scalars()
        }
        for ordinal, item_key in enumerate(order):
            rows[item_key].ordinal = ordinal
        self._session.flush()

    def _shares(self, playlist_id: str) -> tuple[Share, ...]:
        return tuple(
            Share(user_id=row.user_id, can_edit=row.can_edit)
            for row in self._session.execute(
                select(models.PlaylistShare)
                .where(models.PlaylistShare.playlist_id == playlist_id)
                .order_by(models.PlaylistShare.user_id)
            ).scalars()
        )

    def _item_row(self, playlist: Playlist) -> Item:
        item = Item(
            id=playlist.id,
            type=ItemType.PLAYLIST,
            name=playlist.name,
            library_id=None,
            date_created=utc_now(),
        )
        return replace(item, sort_name=sort_name(item))


# --------------------------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImageLocation:
    """One `item_images` row, with everything needed to open the bytes it names.

    A **record, not a row**: the serve path never sees an ORM object, like everywhere else
    (ADR-0003). It carries the library's roots and, for an `embedded` row, the item's part-zero
    source path, because those are the two joins the reading needs and a second query for either
    would be a second chance to disagree with the first.
    """

    item_id: str
    item_name: str
    """Carried because the absent-image refusal names it (behaviours section 1.11), and because
    the request that fails is the request that already looked the item up."""

    library_roots: tuple[str, ...]
    """Absolute, in configured order. The `file` reading takes the **first one the relative path
    exists under**, which is what `metadata/refresh.py` already does for its own root search."""

    image_type: str
    index: int

    source_kind: SourceKind
    relative_path: str | None
    """Null exactly when the row is `embedded` - the schema says so with a check constraint."""

    width: int
    height: int
    tag: str
    """Never null (004 plan section 4). The stored dimensions answer the never-upscale question
    before a file is opened, and the tag is the cache key's content half."""

    carrier_path: str | None
    """The item's part-zero source, relative to a root. Only an `embedded` row needs it, and only
    an item with a source has one."""


@dataclass(frozen=True, slots=True)
class ImageLookup:
    """What one lookup found: the item's name if it exists, and the image if it has one.

    Two optional fields rather than two exceptions, because **which refusal this becomes is a wire
    decision** and `db/` does not make those (architecture section 1). `images/source.py` turns
    this into `ItemNotFoundError` or `ImageNotFoundError`, which are the two `404` bodies the
    reference actually sends (behaviours section 1.11).

    The invariant is one-directional and asserted by the tests: a `location` implies an
    `item_name`, and the reverse says nothing.
    """

    item_name: str | None
    location: ImageLocation | None

    @property
    def item_exists(self) -> bool:
        return self.item_name is not None


class ImageRepository:
    """The one query the image routes need, and the only reader they get.

    Route modules own no SQL (005 plan section 9 row 2, asserted by
    `tests/unit/test_import_directions.py`), and `images/` owns bytes rather than storage - so
    everything the serve path knows about the database is this class.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def locate(self, item_id: str, image_type: str, index: int) -> ImageLookup:
        """Resolve `(item, type, index)` to what it takes to open the bytes.

        **A soft-removed item is not found**, the same reading 005 serves items under: the world a
        client browses has no removed items in it, and an image route that disagreed would answer
        `200` for an item every list says is gone.

        The type is matched case-insensitively, because a path segment is (behaviours section
        1.14) and this one arrives as a path segment.
        """
        item = self._session.get(models.Item, item_id)
        if item is None or item.removed_at is not None:
            return ImageLookup(item_name=None, location=None)

        row = self._session.scalars(
            select(models.ItemImage).where(
                models.ItemImage.item_id == item_id,
                func.lower(models.ItemImage.image_type) == image_type.lower(),
                models.ItemImage.image_index == index,
            )
        ).first()
        if row is None:
            return ImageLookup(item_name=item.name, location=None)

        return ImageLookup(
            item_name=item.name,
            location=ImageLocation(
                item_id=item_id,
                item_name=item.name,
                library_roots=self._roots_of(item.library_id),
                image_type=row.image_type,
                index=row.image_index,
                source_kind=SourceKind(row.source_kind),
                relative_path=row.relative_path,
                width=row.width,
                height=row.height,
                tag=row.tag,
                carrier_path=self._carrier_path(item_id),
            ),
        )

    def _roots_of(self, library_id: str | None) -> tuple[str, ...]:
        if library_id is None:
            return ()
        return tuple(
            self._session.scalars(
                select(models.LibraryRoot.path)
                .where(models.LibraryRoot.library_id == library_id)
                .order_by(models.LibraryRoot.path)
            ).all()
        )

    def _carrier_path(self, item_id: str) -> str | None:
        """Part zero, and only part zero: embedded art is read from the file the item's identity
        derives from, and a two-part film's second part is not a second cover."""
        return self._session.scalars(
            select(models.ItemSource.relative_path).where(
                models.ItemSource.item_id == item_id, models.ItemSource.part_index == 0
            )
        ).first()


#: Fields 003's scanner derives from a file's name and place, which `values_of` therefore does
#: **not** report as the item's own values.
#:
#: They are read by `metadata/refresh.py` as the **path source**, last in the chain, because the
#: reference merges what an item already had only after every provider has spoken
#: `[source: MediaBrowser.Providers/Manager/MetadataService.cs:849-861 @ v10.11.11]`. Reporting
#: them here would make a filename-derived name a value a default refresh must not overwrite, and
#: AC-1 - "a film with a full `.nfo` resolves entirely from it" - would be unreachable.
_THE_SCANNER_OWNS: frozenset[Field] = frozenset(
    {Field.NAME, Field.INDEX_NUMBER, Field.PARENT_INDEX_NUMBER}
)

#: Which column each scalar field is stored in. A field absent from here is stored some other way -
#: a name, a list, a map - and `apply` handles each of those explicitly.
_SCALAR_COLUMNS: dict[Field, str] = {
    Field.OVERVIEW: "overview",
    Field.TAGLINE: "tagline",
    Field.ORIGINAL_TITLE: "original_title",
    Field.YEAR: "production_year",
    Field.PREMIERE_DATE: "premiere_date",
    Field.RUNTIME: "runtime_ticks",
    Field.OFFICIAL_RATING: "official_rating",
    Field.COMMUNITY_RATING: "community_rating",
    Field.NORMALIZATION_GAIN: "normalization_gain",
    Field.INDEX_NUMBER: "index_number",
    Field.PARENT_INDEX_NUMBER: "parent_index_number",
}


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(one) for one in value]
    return []


def _credits(value: object) -> list[PersonCredit]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [one for one in value if isinstance(one, PersonCredit)]
    return []


# --------------------------------------------------------------------------------------------
# Media probes (008 T2)
# --------------------------------------------------------------------------------------------


def _stream(row: models.MediaStreamRow) -> InspectedStream:
    return InspectedStream(
        index=row.stream_index,
        kind=StreamKind(row.type),
        codec=row.codec,
        codec_tag=row.codec_tag,
        profile=row.profile,
        level=row.level,
        bit_depth=row.bit_depth,
        width=row.width,
        height=row.height,
        aspect_ratio=row.aspect_ratio,
        framerate=row.framerate,
        average_framerate=row.average_framerate,
        channels=row.channels,
        channel_layout=row.channel_layout,
        sample_rate=row.sample_rate,
        language=row.language,
        title=row.title,
        is_default=row.is_default,
        is_forced=row.is_forced,
        is_hearing_impaired=row.is_hearing_impaired,
        is_external=row.is_external,
        bitrate=row.bitrate,
        video_range=VideoRange(row.video_range) if row.video_range else None,
        video_range_type=VideoRangeType(row.video_range_type) if row.video_range_type else None,
        color_range=row.color_range,
        color_transfer=row.color_transfer,
        color_primaries=row.color_primaries,
        color_space=row.color_space,
        pixel_format=row.pixel_format,
        ref_frames=row.ref_frames,
        is_interlaced=row.is_interlaced,
        is_anamorphic=row.is_anamorphic,
    )


def inspection_of(
    row: models.MediaProbe,
    streams: Sequence[models.MediaStreamRow],
    externals: Sequence[models.MediaExternalStreamRow] = (),
) -> MediaInspection:
    """Three sets of rows into the domain record, ADR-0003's direction.

    Public because `item_queries.py` hydrates a whole page's inspections in three statements
    rather than asking this repository once per file, and both readers must produce the same
    record from the same rows - a second conversion is a second answer waiting to happen.

    **This is where the two numberings meet, and it is the only place.** The stored
    `stream_index` of a container stream is a demuxer index; the wire index every caller above
    this line reads is derived here by `renumber`, which puts the discovered files at 0..k-1 and
    pushes the container's own up by k (011 plan section 5). A caller cannot obtain an
    un-renumbered inspection, because there is no path to one.
    """
    keyframes = row.video_keyframes
    return MediaInspection(
        size=row.size,
        mtime_ns=row.mtime_ns,
        container=row.container,
        format_names=row.format_names,
        runtime_ticks=row.runtime_ticks,
        bitrate=row.bitrate,
        video_keyframes=None if keyframes is None else tuple(int(one) for one in keyframes),
        probed_at=row.probed_at,
        streams=renumber(
            [_stream(one) for one in streams], [_external_stream(one) for one in externals]
        ),
    )


def _external_stream(row: models.MediaExternalStreamRow) -> InspectedStream:
    """One discovered subtitle stream. Its wire index is not read from the row - there is no wire
    column - and `renumber` supplies it from the ordinal the rows came back in."""
    return InspectedStream(
        index=row.ordinal,
        kind=StreamKind.SUBTITLE,
        file_index=row.stream_index,
        external_path=row.external_path,
        codec=row.codec,
        language=row.language,
        title=row.title,
        is_default=row.is_default,
        is_forced=row.is_forced,
        is_hearing_impaired=row.is_hearing_impaired,
        is_external=True,
    )


class MediaProbeRepository:
    """What inspection found, per file, and whether it still applies.

    **Keyed the way `item_sources` names a file** - its library and its path relative to the
    root - so that the join a wire assembly makes is exact and a remounted root keeps its
    inspections. See `models.MediaProbe`.

    Two readers rather than one, because the two callers ask different questions. A scan asks
    "does what I stored still describe this file", hands over the `stat` it already has, and gets
    nothing back when the answer is no. Everything else asks "what is in this file" and must not
    touch the filesystem to find out: a stale row is re-inspected by the next scan, not by a
    request (plan section 6.1).
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def get(self, library_id: str, relative_path: str) -> MediaInspection | None:
        """The stored inspection, however old it is - renumbered, like every read here."""
        row = self._session.get(models.MediaProbe, (library_id, relative_path))
        if row is None:
            return None
        return inspection_of(
            row,
            self._streams(library_id, relative_path),
            self._external_streams(library_id, relative_path),
        )

    def external_signal(
        self, library_id: str, relative_path: str
    ) -> frozenset[tuple[str, int, int]]:
        """The `(external_path, size, mtime_ns)` of every sidecar stored beside this media file.

        **The second change signal, and the reason discovery is reachable on an ordinary scan.**
        Dropping an `.srt` beside a film changes nothing about the film's own size or modification
        time, so `current` still answers "unchanged" and the file is never reopened. This is the
        comparison the scan makes instead, and it is independent of that one (011 plan section
        6.2).

        A set rather than a list: two sidecars swapping ordinals is not a change, and a file
        appearing or vanishing is.
        """
        return frozenset(
            (one.external_path, one.size, one.mtime_ns)
            for one in self._external_streams(library_id, relative_path)
        )

    def current(
        self, library_id: str, relative_path: str, size: int, mtime_ns: int
    ) -> MediaInspection | None:
        """The stored inspection when it still describes these bytes, otherwise nothing.

        Staleness is the comparison and not a timestamp: 003 makes `(size, mtime_ns)` the change
        signal, and a file rewritten to the same size *and* the same modification time is one
        nothing in this project claims to notice.
        """
        found = self.get(library_id, relative_path)
        if found is None or not found.unchanged_since(size, mtime_ns):
            return None
        return found

    def put(self, library_id: str, relative_path: str, inspection: MediaInspection) -> None:
        """Store one inspection, replacing whatever was there.

        The streams are deleted and rewritten rather than merged: a file that lost a track between
        two scans has fewer streams now, and merging would leave the old one behind as a track no
        file has.
        """
        self._session.execute(
            delete(models.MediaStreamRow).where(
                models.MediaStreamRow.library_id == library_id,
                models.MediaStreamRow.relative_path == relative_path,
            )
        )
        row = self._session.get(models.MediaProbe, (library_id, relative_path))
        if row is None:
            row = models.MediaProbe(library_id=library_id, relative_path=relative_path)
            self._session.add(row)
        row.size = inspection.size
        row.mtime_ns = inspection.mtime_ns
        row.container = inspection.container
        row.format_names = inspection.format_names
        row.runtime_ticks = inspection.runtime_ticks
        row.bitrate = inspection.bitrate
        row.video_keyframes = (
            None if inspection.video_keyframes is None else list(inspection.video_keyframes)
        )
        row.probed_at = inspection.probed_at
        self._session.flush()

        for one in inspection.streams:
            self._session.add(
                models.MediaStreamRow(
                    library_id=library_id,
                    relative_path=relative_path,
                    # The **demuxer** index. `one.index` is the wire number and is equal to this
                    # on a fresh inspection - but a caller that read an inspection back and put it
                    # again would be storing a number `renumber` had already moved, and the
                    # second store would move it again.
                    stream_index=one.file_index,
                    type=one.kind.value,
                    codec=one.codec,
                    codec_tag=one.codec_tag,
                    profile=one.profile,
                    level=one.level,
                    bit_depth=one.bit_depth,
                    width=one.width,
                    height=one.height,
                    aspect_ratio=one.aspect_ratio,
                    framerate=one.framerate,
                    average_framerate=one.average_framerate,
                    channels=one.channels,
                    channel_layout=one.channel_layout,
                    sample_rate=one.sample_rate,
                    language=one.language,
                    title=one.title,
                    is_default=one.is_default,
                    is_forced=one.is_forced,
                    is_hearing_impaired=one.is_hearing_impaired,
                    is_external=one.is_external,
                    bitrate=one.bitrate,
                    video_range=None if one.video_range is None else one.video_range.value,
                    video_range_type=(
                        None if one.video_range_type is None else one.video_range_type.value
                    ),
                    color_range=one.color_range,
                    color_transfer=one.color_transfer,
                    color_primaries=one.color_primaries,
                    color_space=one.color_space,
                    pixel_format=one.pixel_format,
                    ref_frames=one.ref_frames,
                    is_interlaced=one.is_interlaced,
                    is_anamorphic=one.is_anamorphic,
                )
            )
        self._session.flush()

    def put_external(
        self,
        library_id: str,
        relative_path: str,
        files: Sequence[DiscoveredSubtitles],
    ) -> None:
        """Replace the whole discovered set for one media file. Never a merge.

        **A merge is AC-12 failing in the least visible way available.** It would leave a row for
        a file that is gone, at an ordinal that shifts every index after it - so an address a
        client minted before the sidecar was deleted would name a different track, and nothing
        would look wrong from the outside. The same reason `put` replaces stream rows.

        **The argument is a sequence of files, not of streams**, which is a widening of plan
        section 5's `put_external(..., streams)`: an `.mks` holds several tracks behind one
        `(size, mtime_ns)`, and a per-stream argument would carry that pair once per track with
        nothing keeping the copies equal. The ordinals run across the whole flattened sequence,
        because an ordinal numbers a *stream* - that is what a wire index counts.

        The order given is the order stored, and the caller is the scan, which orders by
        `external_path` (011 plan section 6.2). It is not re-derived here: a second sort is a
        second answer.
        """
        self._session.execute(
            delete(models.MediaExternalStreamRow).where(
                models.MediaExternalStreamRow.library_id == library_id,
                models.MediaExternalStreamRow.relative_path == relative_path,
            )
        )
        self._session.flush()
        ordinal = 0
        for file in files:
            for one in file.streams:
                self._session.add(
                    models.MediaExternalStreamRow(
                        library_id=library_id,
                        relative_path=relative_path,
                        ordinal=ordinal,
                        external_path=file.external_path,
                        size=file.size,
                        mtime_ns=file.mtime_ns,
                        stream_index=one.file_index,
                        codec=one.codec,
                        language=one.language,
                        title=one.title,
                        is_default=one.is_default,
                        is_forced=one.is_forced,
                        is_hearing_impaired=one.is_hearing_impaired,
                        probed_at=utc_now(),
                    )
                )
                ordinal += 1
        self._session.flush()

    def _external_streams(
        self, library_id: str, relative_path: str
    ) -> list[models.MediaExternalStreamRow]:
        return list(
            self._session.scalars(
                select(models.MediaExternalStreamRow)
                .where(
                    models.MediaExternalStreamRow.library_id == library_id,
                    models.MediaExternalStreamRow.relative_path == relative_path,
                )
                .order_by(models.MediaExternalStreamRow.ordinal)
            )
        )

    def _streams(self, library_id: str, relative_path: str) -> list[models.MediaStreamRow]:
        return list(
            self._session.scalars(
                select(models.MediaStreamRow)
                .where(
                    models.MediaStreamRow.library_id == library_id,
                    models.MediaStreamRow.relative_path == relative_path,
                )
                .order_by(models.MediaStreamRow.stream_index)
            )
        )


class MediaFileRepository:
    """The one query the four delivery routes need: an item id, and the file behind it.

    Separate from `ItemQueryRepository` because that one takes a user and applies 005's visibility
    predicate, and a delivery route has neither - it may be called with no token at all
    (behaviours section 2.10). Separate from `MediaProbeRepository` because a static request needs
    no inspection: the bytes are the file's, and their size and modification time come from the
    filesystem, which is what the reference reads too.
    """

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    def locate(self, item_id: str, part_index: int = 0) -> DeliveredFile | None:
        """The part's file, or `None` when no item, no part, or a removed item holds that id.

        **A soft-removed item is not found**, the same reading the image routes serve under: the
        world a client browses has no removed items in it, and a delivery route that disagreed
        would answer bytes for an item every list says is gone.
        """
        item = self._session.get(models.Item, item_id)
        if item is None or item.removed_at is not None:
            return None
        relative_path = self._session.scalars(
            select(models.ItemSource.relative_path).where(
                models.ItemSource.item_id == item_id,
                models.ItemSource.part_index == part_index,
            )
        ).first()
        if relative_path is None:
            return None
        roots = tuple(
            self._session.scalars(
                select(models.LibraryRoot.path)
                .where(models.LibraryRoot.library_id == item.library_id)
                .order_by(models.LibraryRoot.path)
            ).all()
        )
        return DeliveredFile(
            library_roots=roots,
            relative_path=relative_path,
            library_id=item.library_id,
            part_index=part_index,
            # The item's own kind, read from the one table that already states it rather than
            # from the file: a track with cover art has a video stream and is negotiated as
            # audio all the same (008 T4).
            is_video=MEDIA_TYPE_OF.get(ItemType(item.type)) == "Video",
        )

    def present(self, item_id: str) -> bool:
        """Whether an item with this identifier is here at all, files or no files.

        The four delivery routes never ask - a `404` is a `404` whether the item is missing or its
        file is - but 011's subtitle fetch splits its refusal on exactly this question: an
        identifier nothing holds is a `400` and an item that *is* here and has nothing servable is
        a `500`, measured on a series id and on an audio track in one run
        `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. Without this
        the two would be one answer, because `locate` returns `None` for both.
        """
        item = self._session.get(models.Item, item_id)
        return item is not None and item.removed_at is None

    def parts(self, item_id: str) -> tuple[str, ...]:
        """Every part's relative path, in part order - what a `mediaSourceId` is resolved against.

        The identifiers themselves are not stored and never were: a source id is a *derivation*
        from the item and the file (`media/info.py`, Principle VII), so the caller derives them
        rather than this querying a column that does not exist.
        """
        return tuple(
            self._session.scalars(
                select(models.ItemSource.relative_path)
                .where(models.ItemSource.item_id == item_id)
                .order_by(models.ItemSource.part_index)
            ).all()
        )
