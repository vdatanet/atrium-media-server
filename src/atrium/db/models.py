# SPDX-License-Identifier: GPL-3.0-or-later
"""The ORM tables.

**Nothing here crosses the repository boundary.** A route never sees one of these rows; `db/` turns
them into domain objects and hands those out (architecture section 1, ADR-0003). That is what makes
"SQLite is the default, not the only option" a claim rather than a hope.

**Enforcement and storage are structurally separate**, which is the point of the split and the
reason it is visible in the schema rather than only in the code. The reference's `UserPolicy`
carries **42** properties `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11,
2026-08-28]`; v1 honours
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
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
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
    than a count `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]` -
    so this column stores
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
    #: `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`. All of it is
    #: a blob: v1 acts on two
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
    #: **No foreign key to `libraries`, and this is permanent rather than pending.** 003 created
    #: that table and the obvious next step was to point at it - which would break 002. A policy
    #: round-trips whole (002 spec section 3.7), `EnabledFolders` arrives from the client, and a
    #: client may legitimately name a library this server has not configured. Under a foreign key
    #: that policy write fails instead of round-tripping, which is a difference a client can see.
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


# ----------------------------------------------------------------------------------------------
# Feature 003: libraries, items, and the user data that outlives them
# ----------------------------------------------------------------------------------------------


class Library(Base):
    """A configured root and what it is: the operator's side of feature 003.

    `case_sensitive_identity` is **frozen at creation** and `library/config.py` refuses to change
    it (003 plan section 6.3). It is not a preference: flipping it rewrites every identifier in the
    library, which discards every client's favourites and resume positions for everything in it.
    """

    __tablename__ = "libraries"
    __table_args__ = (
        # The three collection types of 003 spec section 3.1, in the schema rather than only in
        # the resolver. A row with a fourth would be a library nothing knows how to scan, and it
        # would be written long before anything noticed.
        CheckConstraint(
            "collection_type IN ('movies', 'tvshows', 'music')",
            name="ck_libraries_collection_type",
        ),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    collection_type: Mapped[str] = mapped_column(String, nullable=False)

    case_sensitive_identity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    roots: Mapped[list[LibraryRoot]] = relationship(
        back_populates="library", lazy="raise", cascade="all, delete-orphan"
    )
    #: Declared for the ordering, not for the traversal. Without a relationship the unit of work
    #: does not know `items` depends on `libraries`, and writing a library and its items in **one
    #: transaction** - which is exactly what a scan does (003 plan section 6.7) - fails on the
    #: foreign key. The schema knew; the mapper did not.
    items: Mapped[list[Item]] = relationship(
        back_populates="library", lazy="raise", passive_deletes=True
    )


class LibraryRoot(Base):
    """One directory a library is built from. A library may have several (003 plan section 4)."""

    __tablename__ = "library_roots"

    library_id: Mapped[str] = mapped_column(
        ID, ForeignKey("libraries.id", ondelete="CASCADE"), primary_key=True
    )
    #: Absolute, and the only absolute path in the schema. Everything an item stores is relative
    #: to one of these, which is what makes moving a library free (003 spec section 3.6).
    path: Mapped[str] = mapped_column(String, primary_key=True)

    library: Mapped[Library] = relationship(back_populates="roots", lazy="raise")


class Item(Base):
    """Everything a library holds, in one table, because the reference has one kind of thing.

    **No path column.** An item's files live in `item_sources`: a two-part film is one `Movie` with
    two of them (003 spec section 3.3, AC-4), and a `Series` has none at all. Putting the path here
    would make the first impossible and the second a nullable column on every row.
    """

    __tablename__ = "items"
    __table_args__ = (
        CheckConstraint(
            "type IN ('Movie', 'Series', 'Season', 'Episode', 'MusicArtist', 'MusicAlbum', "
            "'Audio', 'CollectionFolder', 'Genre', 'MusicGenre', 'Studio', 'Person', 'Year')",
            name="ck_items_type",
        ),
        # **The by-name types are exactly the ones with no library**, stated as a constraint
        # rather than left to the code that writes the rows. Both directions matter: a genre with
        # a library would appear under one library and belong to all of them, and a film without
        # one would be invisible to every query 005 scopes by library.
        CheckConstraint(
            "(library_id IS NULL) = (type IN ('Genre', 'MusicGenre', 'Studio', 'Person', 'Year'))",
            name="ck_items_by_name_has_no_library",
        ),
        # Pattern-driven, not fact-driven: 005 orders nearly every list by `sort_name` within a
        # library and a type, and walks children by their number. Named here so a later reader
        # can tell which indexes serve a query and which serve a constraint.
        Index("ix_items_library_type_sort", "library_id", "type", "sort_name"),
        Index("ix_items_parent_index", "parent_id", "index_number"),
        # 004 plan section 4's pattern-driven set, every one of them for a 005 query that does not
        # exist yet: `years` and `sortBy=ProductionYear`, `sortBy=PremiereDate`,
        # `minCommunityRating`, `Latest`, and `searchTerm`/`nameStartsWith` on the folded name.
        # They are here rather than in 005 because adding an index to a populated table is a
        # migration somebody has to run, and this table is populated by the feature that adds it.
        Index("ix_items_production_year", "production_year"),
        Index("ix_items_premiere_date", "premiere_date"),
        Index("ix_items_community_rating", "community_rating"),
        Index("ix_items_date_created", "date_created"),
        Index("ix_items_name_folded", "name_folded"),
        # Every scan asks for the set (004 plan section 6.8), and it is almost always empty -
        # which is exactly the shape an index serves best.
        Index("ix_items_refresh_pending", "refresh_pending"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    #: **Null for exactly the five by-name types**, held by the check constraint above.
    library_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ID, ForeignKey("items.id", ondelete="CASCADE"), nullable=True
    )

    type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: The ordering key for nearly every query 005 issues, which is why it is indexed above and
    #: why it is not nullable: an item with no sort name would sort first, everywhere, silently.
    sort_name: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")

    #: Episode or track number, and season or disc number.
    index_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_index_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The last number a multi-episode file spans: `S01E02-E03` is one item, not two (AC-5).
    end_index_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    date_created: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    date_modified: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: **Items are soft-deleted** (003 plan section 6.6). A file that disappears sets this; the row
    #: stays so that the identifier stays derivable and the user data keyed on it stays associated.
    #: Only an explicit maintenance action purges, and a scan never does.
    removed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # -- 004: what a refresh resolves ---------------------------------------------------------

    overview: Mapped[str | None] = mapped_column(String, nullable=True)
    tagline: Mapped[str | None] = mapped_column(String, nullable=True)
    original_title: Mapped[str | None] = mapped_column(String, nullable=True)
    production_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    premiere_date: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Ticks of 100 nanoseconds, converted once at ingestion (architecture section 4).
    runtime_ticks: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    official_rating: Mapped[str | None] = mapped_column(String, nullable=True)
    community_rating: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: Echoed as `ProviderIds`. A map rather than columns because the *keys* are open: a provider
    #: nothing here knows about may still be named in a sidecar, and dropping it would lose the
    #: one thing that stops a future refresh guessing (spec section 3.5 rule 1).
    provider_ids: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )

    #: The track gain in decibels, from the file's own tag. **One number, not four** - the
    #: reference reads only the track gain and serves only this
    #: `[source: MediaBrowser.Providers/MediaInfo/AudioFileProber.cs:362-375 @ v10.11.11]`
    #: `[spec: BaseItemDto]`. Nullable because the tag is usually absent, and a null property is
    #: omitted from a response entirely (behaviours section 1.7). See 004 T1.
    normalization_gain: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: The reference's nine `MetadataField` values, as they were spelled in the sidecar that set
    #: them `[spec: MetadataField]`. **Not** this feature's finer field vocabulary: a lock is a
    #: coarser thing than a merge field, and `metadata/model.py`'s `LOCK_OF` is the map between
    #: them. A list rather than nine booleans because it round-trips a value like
    #: `ProductionLocations`, which locks nothing here and is still the user's.
    locked_fields: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    #: `<lockdata>true</lockdata>`: no provider may change anything about this item.
    is_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    #: A provider was unreachable, so this item kept its local metadata and wants another go
    #: (AC-8). The next scan retries these **even when their files did not change**, which is the
    #: one thing in 004 that reads an item the change-detection signal would have skipped.
    refresh_pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    metadata_refreshed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    #: `<tag>` elements: free-text labels a user put on an item. A JSON array rather than a join
    #: table because, unlike a genre or a studio, a tag has no by-name item in the reference's
    #: model - it is a string on the item and nothing else. Revision 0005.
    tags: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )

    #: The explicit sort title, **as the user wrote it**. `sort_name` is derived from this
    #: (003 section 3.7.3), and a derivation cannot be compared against what it was derived from -
    #: which is why both are stored. Revision 0005.
    forced_sort_name: Mapped[str | None] = mapped_column(String, nullable=True)

    #: Case- and diacritic-folded name. **Written by 004, read by nobody until 005** - it exists
    #: for `searchTerm`, `nameStartsWith` and `/Search/Hints`, and a row that misses it is
    #: invisible to search rather than broken, which is the failure mode worth an index and a
    #: not-null default.
    name_folded: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")

    library: Mapped[Library] = relationship(back_populates="items", lazy="raise")

    #: Self-referential, and declared for the same reason as `Library.items`: a scan writes a
    #: series, its seasons and its episodes in one transaction, and the mapper has to know which
    #: order that is. `passive_deletes` leaves the cascade to the database rather than loading
    #: every descendant into memory to delete it one row at a time.
    parent: Mapped[Item | None] = relationship(
        back_populates="children", lazy="raise", remote_side="Item.id"
    )
    children: Mapped[list[Item]] = relationship(
        back_populates="parent", lazy="raise", passive_deletes=True
    )

    sources: Mapped[list[ItemSource]] = relationship(
        back_populates="item", lazy="raise", cascade="all, delete-orphan"
    )

    genres: Mapped[list[ItemGenre]] = relationship(
        back_populates="item",
        lazy="raise",
        cascade="all, delete-orphan",
        foreign_keys="ItemGenre.item_id",
    )
    studios: Mapped[list[ItemStudio]] = relationship(
        back_populates="item",
        lazy="raise",
        cascade="all, delete-orphan",
        foreign_keys="ItemStudio.item_id",
    )
    people: Mapped[list[ItemPerson]] = relationship(
        back_populates="item",
        lazy="raise",
        cascade="all, delete-orphan",
        foreign_keys="ItemPerson.item_id",
    )
    artists: Mapped[list[ItemArtist]] = relationship(
        back_populates="item",
        lazy="raise",
        cascade="all, delete-orphan",
        foreign_keys="ItemArtist.item_id",
    )
    images: Mapped[list[ItemImage]] = relationship(
        back_populates="item", lazy="raise", cascade="all, delete-orphan"
    )


class ItemSource(Base):
    """One file behind an item, in order. Several of these is a multi-part film."""

    __tablename__ = "item_sources"

    item_id: Mapped[str] = mapped_column(
        ID, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    #: Zero first. The item's identity derives from part zero's path, so adding a part later does
    #: not change an identifier somebody has already favourited.
    part_index: Mapped[int] = mapped_column(Integer, primary_key=True)

    relative_path: Mapped[str] = mapped_column(String, nullable=False)

    #: Together, the change-detection signal (003 plan section 6.4). Per source rather than per
    #: item, because a film whose *second* part was replaced has changed.
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mtime_ns: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    item: Mapped[Item] = relationship(back_populates="sources", lazy="raise")


class ItemUserData(Base):
    """Per-user, per-item state - and **it outlives the item**.

    **There is deliberately no foreign key to `items`**, and that absence is the whole feature.
    003 spec section 3.8 says a file that disappears and comes back must not cost the user their
    favourites and resume position: a re-download, a remount, a network share slow to mount. Under
    a cascade the first slow mount would delete a user's history, permanently, and the only symptom
    would be a user saying their watched list looks wrong.

    Keyed on `item_key` - the derived identity, not a row reference - so the association is
    restored the moment the same path is scanned again, because the same path derives the same
    identifier (003 spec section 3.6).

    **007 owns what these columns mean**; 003 owns the guarantee that the row survives.
    """

    __tablename__ = "item_user_data"

    user_id: Mapped[str] = mapped_column(
        ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    #: The item's derived identity. Not a foreign key. See the docstring above before adding one.
    item_key: Mapped[str] = mapped_column(ID, primary_key=True)

    is_favorite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    played: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    play_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    #: Ticks of 100 nanoseconds, the internal unit everywhere (architecture section 4).
    playback_position_ticks: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    last_played_date: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ItemGenre(Base):
    """One genre on one item, in order, with **both** the spelling and the row it merges into.

    The string is stored here and not only on the by-name item because they are two different
    facts. An item's own response carries the spelling that item's file used - `Genres: ["sci-fi"]`
    - while `/Genres` displays the first spelling anybody used, which may be `Sci-Fi`. One home
    each; deriving either from the other loses the other (004 plan section 4).

    `genre_item_id` points at a `Genre` row for film and series genres and a `MusicGenre` row for
    audio genres, which is the whole of what keeps `/Genres` and `/MusicGenres` disjoint: neither
    endpoint has to guess from context what kind of item referred to a name.
    """

    __tablename__ = "item_genres"
    __table_args__ = (Index("ix_item_genres_genre", "genre_item_id"),)

    item_id: Mapped[str] = mapped_column(
        ID, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    #: Document order. A genre list is ordered by the source that wrote it, not alphabetically.
    position: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    #: **No cascade, deliberately.** Garbage collection deletes a by-name row only when nothing
    #: references it; a cascade would let a mistake there delete the genre off every item that had
    #: it, silently. Without one the same mistake is an integrity error.
    genre_item_id: Mapped[str] = mapped_column(ID, ForeignKey("items.id"), nullable=False)

    item: Mapped[Item] = relationship(back_populates="genres", lazy="raise", foreign_keys=[item_id])


class ItemStudio(Base):
    """One studio on one item, in order. Same two-homes rule as `ItemGenre`."""

    __tablename__ = "item_studios"
    __table_args__ = (Index("ix_item_studios_studio", "studio_item_id"),)

    item_id: Mapped[str] = mapped_column(
        ID, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    studio_item_id: Mapped[str] = mapped_column(ID, ForeignKey("items.id"), nullable=False)

    item: Mapped[Item] = relationship(
        back_populates="studios", lazy="raise", foreign_keys=[item_id]
    )


class ItemPerson(Base):
    """One person on one item, with their role and their place in the billing.

    **The order is metadata, not an accident of insertion** (spec section 3.7 rule 2). Clients
    render "starring" from the first few entries, so a cast list that arrives in a different order
    is a different cast list.

    `role` is the character, and it belongs on this row rather than on the person: the same actor
    is a different character in every film, which is exactly why the association carries it.
    """

    __tablename__ = "item_people"
    __table_args__ = (Index("ix_item_people_person", "person_item_id"),)

    item_id: Mapped[str] = mapped_column(
        ID, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    #: Billing order, and the primary key's second half: one place in the list, one person.
    sort_order: Mapped[int] = mapped_column(Integer, primary_key=True)

    #: `Actor`, `Director`, `Writer`, `Composer` - the reference's `PersonKind` spellings.
    person_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: The character played. Null for a director or a writer, who play nobody.
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    person_item_id: Mapped[str] = mapped_column(ID, ForeignKey("items.id"), nullable=False)

    item: Mapped[Item] = relationship(back_populates="people", lazy="raise", foreign_keys=[item_id])


class ItemArtist(Base):
    """One artist credit on one item, and **the credit kind is the whole point of the row**.

    `/Artists` and `/Artists/AlbumArtists` are the same rows distinguished by this column and
    nothing else. A track's performers are `artist`; the album's are `album_artist`; a compilation
    has one album artist and a different performer on every track, which is what makes it one
    album rather than one per track. Losing the distinction here makes those two endpoints
    impossible to tell apart later without re-reading every file.
    """

    __tablename__ = "item_artists"
    __table_args__ = (
        CheckConstraint("credit IN ('artist', 'album_artist')", name="ck_item_artists_credit"),
        Index("ix_item_artists_artist", "artist_item_id"),
    )

    item_id: Mapped[str] = mapped_column(
        ID, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    credit: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)

    name: Mapped[str] = mapped_column(String, nullable=False)
    #: A `MusicArtist`, which is a **per-library** row rather than a by-name one - the gap
    #: recorded in docs/compatibility/behaviours.md section 5.3 - and therefore **nullable**,
    #: unlike every other link in these tables.
    #:
    #: The others point at by-name rows a refresh creates on demand, so they can never dangle. A
    #: `MusicArtist` is a tree item the *scanner* owns and it creates one per **album artist**; a
    #: track's performers are frequently other people, so a credit naming one has a name and no
    #: item behind it. The name is what a client renders and the link is what makes it clickable:
    #: this column being nullable is that sentence, in the schema. See revision 0004.
    artist_item_id: Mapped[str | None] = mapped_column(ID, ForeignKey("items.id"), nullable=True)

    item: Mapped[Item] = relationship(
        back_populates="artists", lazy="raise", foreign_keys=[item_id]
    )


class ItemImage(Base):
    """Which file is which image for an item, with everything a response needs and no bytes.

    **`relative_path` is read through `source_kind`**, and the three readings are not
    interchangeable (004 plan section 4):

    * `file` - relative to the item's **library root**. The user's own artwork, never written to.
    * `embedded` - **absent**: the bytes are inside the audio file itself.
    * `remote` - relative to the **data directory**, where a downloaded poster lands. Never inside
      a library root, which is the structural half of the read-only guarantee (AC-15).

    `width`, `height` and `tag` are written at association time and **never null**: 005 emits
    `ImageTags` and `PrimaryImageAspectRatio` from these rows alone, before 006 exists to serve a
    single byte, and a row missing them would make an item's aspect ratio silently absent.
    """

    __tablename__ = "item_images"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('file', 'embedded', 'remote')", name="ck_item_images_source_kind"
        ),
        CheckConstraint(
            "(source_kind = 'embedded') = (relative_path IS NULL)",
            name="ck_item_images_embedded_has_no_path",
        ),
    )

    item_id: Mapped[str] = mapped_column(
        ID, ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    #: `Primary`, `Backdrop`, `Logo`, `Thumb`, `Banner`, `Disc` - the reference's `ImageType`.
    image_type: Mapped[str] = mapped_column(String, primary_key=True)
    #: Zero for every type but `Backdrop`, which is numbered and ordered.
    image_index: Mapped[int] = mapped_column(Integer, primary_key=True)

    source_kind: Mapped[str] = mapped_column(String, nullable=False)
    relative_path: Mapped[str | None] = mapped_column(String, nullable=True)

    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    #: 32 lowercase hex: the first 16 bytes of the SHA-256 of the image bytes. Stable across a
    #: rescan because the bytes are, which is 006 AC-2's whole cache story computed here.
    tag: Mapped[str] = mapped_column(ID, nullable=False)

    item: Mapped[Item] = relationship(back_populates="images", lazy="raise")


class ProviderCacheEntry(Base):
    """One response somebody else's server sent, kept so a rescan does not ask again.

    **The schema promises nothing about these rows.** They are evictable at any time: dropping the
    table costs a refresh, not data. That is why the cache is not the mechanism behind AC-13 -
    a rescan of an unchanged library makes no requests because 003's change detection means
    nothing asks, not because something answered from here. This table exists for the two cases
    where something *does* ask again: retrying after a provider was down, and a `Replace` refresh.
    """

    __tablename__ = "provider_cache"

    #: The `ProviderIds` key - `Tmdb`, `MusicBrainz`. The same name the identity is stored under.
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    #: Whatever identifies the request within that provider. Opaque here on purpose: the provider
    #: module owns its own request shape, and this table owns none of it.
    request_key: Mapped[str] = mapped_column(String, primary_key=True)

    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    #: When this stops being fresh. An identity lookup by id never expires - an id does not change
    #: meaning - so this is null for those (004 plan section 6.8).
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
