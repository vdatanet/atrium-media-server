# SPDX-License-Identifier: GPL-3.0-or-later
"""The ORM tables.

**Nothing here crosses the repository boundary.** A route never sees one of these rows; `db/` turns
them into domain objects and hands those out (architecture section 1, ADR-0003). That is what makes
"SQLite is the default, not the only option" a claim rather than a hope.

**Enforcement and storage are structurally separate**, which is the point of the split and the
reason it is visible in the schema rather than only in the code. The reference's `UserPolicy`
carries **42** properties `[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`; v1 honours
**eleven** of them, and those eleven become **nine columns plus two rows in a join table**, because
two of the eleven are lists of libraries rather than flags. The other **31** live in `policy_extra`
and are echoed back untouched. A reader can therefore tell what is enforced from what is merely
kept without reading the enforcement code, and honouring a twelfth means moving a key out of the
blob into a column - a migration, and therefore a decision somebody makes on purpose.

See specs/002-authentication-users-and-sessions/plan.md section 4.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from atrium.db.types import UtcDateTime

#: Every identifier a client sees is 32 lowercase hexadecimal characters (compat/guids.py), and the
#: column is sized for exactly that rather than left open. A row whose id is a different shape is a
#: row that would serialise into a response no client can parse.
ID = String(32)

#: SHA-256, hexadecimal. See `AccessToken`.
SHA256_HEX = String(64)


class Base(DeclarativeBase):
    """The declarative base every table inherits.

    One base, so one `metadata` - which is what `alembic revision --autogenerate` compares against
    a live database. A second base would produce migrations that silently omit half the schema.
    """


class User(Base):
    """An account.

    The nine honoured policy columns are typed and queryable; `policy_extra` holds the rest. The
    reference's default for `login_attempts_before_lockout` is **-1**, which is a sentinel rather
    than a count `[probe: manual request, Jellyfin 10.11.11, 2026-08-26]` - so this column stores
    the reference's own vocabulary and what -1 means is a question for whoever implements lockout,
    not something this schema decides.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(ID, primary_key=True)

    #: What the user sees. `name_normalised` is what a login is matched against: the reference
    #: matches case-insensitively (spec section 3.3), and a unique index on the normalised form is
    #: what makes two accounts differing only in case impossible rather than merely unlikely.
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_normalised: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)

    #: The self-describing Argon2id string. Nullable: an account may have no password at all, which
    #: is not the same as an empty one (spec section 3.3, ADR-0006).
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    last_login_date: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_activity_date: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- the nine honoured policy columns ----------------------------------------------------
    is_administrator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    is_hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    enable_all_folders: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    enable_media_playback: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    enable_content_deletion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    login_attempts_before_lockout: Mapped[int] = mapped_column(
        Integer, nullable=False, default=-1, server_default=text("-1")
    )
    invalid_login_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    max_active_sessions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    # -- what is stored and echoed, not enforced ---------------------------------------------
    #: The other 31 policy properties, returned to a client exactly as they arrived. A client that
    #: round-trips a policy from a newer server must get its own data back (spec AC-8's shape).
    policy_extra: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    #: The whole `UserConfiguration` - 16 properties on the reference
    #: `[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`. All of it is a blob: v1 acts on two
    #: of them and no query filters on any, so columns would buy nothing (plan section 6.4).
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )

    # -- the children ------------------------------------------------------------------------
    #
    # These exist for **insert ordering**, which a foreign-key column alone does not give. The
    # unit of work sorts inserts by relationship, not by `ForeignKey`, so creating a user and its
    # token in one flush inserts the token first and the database rejects it. That failure only
    # happens at all because `db/engine.py` turns the foreign-key pragma on; without it the row
    # would go in with a dangling reference and nothing would say so.
    #
    # `passive_deletes=True` leaves the cascade to the database, where the migration declares it,
    # rather than loading every child in order to delete it one row at a time.
    #
    # `lazy="raise"` because **no ORM object crosses the repository boundary** (architecture
    # section 1): a lazy load here would mean somebody is holding a row outside the session that
    # produced it, and this turns that into an error instead of a surprise query.
    tokens: Mapped[list[AccessToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )
    library_access: Mapped[list[UserLibraryAccess]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )


class UserLibraryAccess(Base):
    """Which libraries a user may see, and which they may delete from.

    A join table rather than two JSON lists because **005 filters every query on it**, on every
    request. A list inside a blob would make library visibility a post-filter in Python over rows
    the database already paid to read.

    The two honoured list properties - `EnabledFolders` and `EnableContentDeletionFromFolders` -
    are the two booleans here. They are the reason eleven honoured properties become nine columns.
    """

    __tablename__ = "user_library_access"

    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    #: Libraries arrive with feature 003; this column deliberately carries no foreign key yet,
    #: because the table it would point at does not exist.
    library_id: Mapped[str] = mapped_column(ID, primary_key=True)

    can_view: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    can_delete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    user: Mapped[User] = relationship(back_populates="library_access", lazy="raise")


class AccessToken(Base):
    """A live credential, stored as a hash and never as itself.

    **No column here holds a value that would authenticate if this file were disclosed.** A token
    is 128 bits of generated entropy rather than a human-chosen secret, so SHA-256 is enough and a
    KDF would only tax every authenticated request (ADR-0006). Lookup is by hash, which is why the
    hash is the primary key: there is no other way to find a row, so there is no way to add a
    plaintext column later and have anything use it.
    """

    __tablename__ = "access_tokens"

    token_sha256: Mapped[str] = mapped_column(SHA256_HEX, primary_key=True)

    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: From `X-Emby-Authorization` (spec section 3.2). `device_id` is what identifies a session, so
    #: it is indexed: re-authenticating from a known device replaces the previous one, and that
    #: lookup happens on every login.
    device_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    client: Mapped[str] = mapped_column(String, nullable=False, default="")
    device_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    app_version: Mapped[str] = mapped_column(String, nullable=False, default="")

    created: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: Flushed periodically rather than written per request: advancing it synchronously would take
    #: a write lock on SQLite for every authenticated call (plan section 6.5).
    last_used: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    user: Mapped[User] = relationship(back_populates="tokens", lazy="raise")


class Session(Base):
    """A `(user, device, client)` triple, as `/Sessions` reports it.

    **Live playback state is not here.** Feature 007 owns `NowPlayingItem` and `PlayState` and keeps
    them in memory, because they change several times a minute per playing session and none of it
    is worth surviving a restart - a client that reconnects reports its state again.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        # One session per device per user: re-authenticating replaces rather than accumulates
        # (spec section 3.8). Enforced here so a bug in the replace path is a constraint violation
        # rather than a second row nobody notices until /Sessions lists the same phone twice.
        UniqueConstraint("user_id", "device_id", name="uq_sessions_user_device"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(String, nullable=False)

    client: Mapped[str] = mapped_column(String, nullable=False, default="")
    device_name: Mapped[str] = mapped_column(String, nullable=False, default="")
    app_version: Mapped[str] = mapped_column(String, nullable=False, default="")
    remote_end_point: Mapped[str | None] = mapped_column(String, nullable=True)

    last_activity_date: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_playback_check_in: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: What the client posted to `/Sessions/Capabilities/Full`, kept whole and reflected back. v1
    #: acts on none of it and a client that posts capabilities and then does not see them has
    #: observed a difference, which is why storing it is not optional (spec section 3.8).
    capabilities: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )

    user: Mapped[User] = relationship(back_populates="sessions", lazy="raise")


__all__ = ["AccessToken", "Base", "Session", "User", "UserLibraryAccess"]
