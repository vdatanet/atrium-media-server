# SPDX-License-Identifier: GPL-3.0-or-later
"""The only module that reads items for a query, and the two promises that buys.

Seventeen endpoints ask essentially one question - *which items may this user see, in this scope,
in this order* - and the answer is assembled here rather than seventeen times. That is a structural
decision with two consequences worth naming, because both are load-bearing.

**Visibility is one predicate.** `_visible_to` is the whole of what a user may see, and every query
in this feature is filtered by it. The alternative - each route remembering to add the same three
clauses - fails silently and in the worst direction: a route that forgets shows one user another
user's library, and the request succeeds. A route module that wanted its own SQL now has
`tests/unit/test_import_directions.py` to argue with.

**Hydration is complete, in a fixed number of statements.** A page arrives with its genres,
studios, people, artists, images, sources and the requesting user's user data already attached, so
the DTO builder is handed plain values and has no session to misuse. The number of statements does
not grow with the page: it is one count, one page, and one query per related table. The query
counter in the test suite fails any path that does otherwise, because an N+1 over a hundred-item
page is invisible in a test and quadratic in a library.

**What this module does not do yet.** Filtering is T6, ordering is T7 - the order here is
`sort_name` then `id`, which is deterministic and provisional - and the by-name queries are T8.
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, Select, case, cast, extract, func, or_, select, tuple_
from sqlalchemy.orm import Session as OrmSession

from atrium.db import models
from atrium.db.repositories import inspection_of
from atrium.domain.items import (
    BY_NAME,
    FILE_BACKED,
    IN_THE_TREE,
    MEDIA_TYPE_OF,
    Item,
    ItemType,
    MediaSource,
)
from atrium.domain.media import MediaInspection
from atrium.domain.playstate import UserItemData
from atrium.domain.queries import Filter, ItemQuery, SortBy, SortOrder
from atrium.domain.user import User
from atrium.library.identity import for_by_name
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind
from atrium.metadata.byname import fold_for_search

#: The four container types that have to earn their place. A `Series` with no visible episode is
#: not offered; the row stays and the user simply never meets it - the closing half of
#: behaviours section 5.2, which 003 deliberately left for this feature.
#:
#: `CollectionFolder` is **not** here, and the exemption is the point: an empty library is still a
#: library and `/UserViews` shows it. A container that disappeared when its last file did would
#: make a library vanish from a client's sidebar during a slow mount.
EARN_THEIR_PLACE: frozenset[ItemType] = frozenset(
    {ItemType.SERIES, ItemType.SEASON, ItemType.MUSIC_ARTIST, ItemType.MUSIC_ALBUM}
)

#: How far below a container its files can be: `Series -> Season -> Episode` and
#: `MusicArtist -> MusicAlbum -> Audio` are both two hops, and `PARENT_OF` fixes that at two for
#: every tree this domain has. So the visibility `EXISTS` is a bounded join rather than a
#: recursive query - and if the tree ever grows a level, this constant is what fails first.
DESCENT = 2

#: The value `item_artists.credit` carries for an album artist, as the check constraint spells
#: it. `/Artists` and `/Artists/AlbumArtists` are the same rows distinguished by this string.
ALBUM_ARTIST_CREDIT = "album_artist"

#: The other value the same column carries: a performer on this particular track.
PERFORMER_CREDIT = "artist"

#: How each by-name kind is reached from the items that reference it. `Year` is absent because it
#: has no join table at all - it is referenced by `items.production_year`, a column.
_LINK_OF: dict[ItemType, tuple[Any, str]] = {
    ItemType.GENRE: (models.ItemGenre, "genre_item_id"),
    ItemType.MUSIC_GENRE: (models.ItemGenre, "genre_item_id"),
    ItemType.STUDIO: (models.ItemStudio, "studio_item_id"),
    ItemType.PERSON: (models.ItemPerson, "person_item_id"),
}


class ParentNotFoundError(LookupError):
    """`parentId` names an item that does not exist, or one this user may not see.

    **One exception for both**, and that is the security-relevant half. Plan section 6.13 turns it
    into a single identical `404`: a client that could tell "no such item" from "not yours" could
    enumerate another user's library one identifier at a time.
    """


@dataclass(frozen=True, slots=True)
class NameLink:
    """A related name and the by-name row it merges into, in document order.

    Two facts, not one: the item carries the spelling its own source used, and the link carries the
    row `/Genres` lists. Deriving either from the other loses the other (004 plan section 4).

    `item_id` is **nullable for artists only** - a track performer who is nobody's album artist has
    a name a client renders and no item to click through to (revision 0004,
    behaviours section 5.3).
    """

    name: str
    item_id: str | None = None
    #: `artist` or `album_artist` on an artist link; the person's kind on a person link.
    credit: str = ""
    role: str | None = None


@dataclass(frozen=True, slots=True)
class ItemMetadata:
    """What a refresh resolved for one item - 004's columns, read back for a response.

    A separate record rather than fields on `Item` for T5's reason exactly: these are not
    properties of the file 003's scanner saw, and putting them on `Item` would hand the scanner
    ten fields it can never fill. They cost no extra statement - the columns arrive on the row
    the page already fetched - so this is a mapping gap being closed, not a new query.
    """

    overview: str | None = None
    tagline: str | None = None
    original_title: str | None = None
    production_year: int | None = None
    premiere_date: datetime | None = None
    runtime_ticks: int | None = None
    official_rating: str | None = None
    community_rating: float | None = None
    provider_ids: Mapping[str, str] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    normalization_gain: float | None = None
    refreshed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Ancestor:
    """As much of a parent as a response needs, and no more.

    An episode's row carries `SeriesName`, the series' primary image tag and the nearest thumb; a
    track's carries its album's name and the album's artists. Those live on the *ancestors*, so a
    page hydrates its parents and grandparents alongside - the tree is two hops deep (`DESCENT`),
    so two levels is all of them - and the DTO builder still has no session to misuse.
    """

    id: str
    type: ItemType
    name: str
    images: tuple[ImageAssociation, ...] = ()
    artists: tuple[NameLink, ...] = ()


@dataclass(frozen=True, slots=True)
class HydratedItem:
    """One item and everything a response about it needs, with no session behind it.

    A separate record rather than fields on `Item`, deliberately. `Item` is 003's model of what a
    library holds and the scanner builds one from a file; genres, credits and another user's play
    state are not properties of the file, and putting them on `Item` would give the scanner five
    fields it can never fill and a reader no way to tell "empty" from "not loaded".

    `people` links carry the person's kind in `credit` and the played character in `role` -
    the same shape as every other related name, because that is what a response renders.
    """

    item: Item
    metadata: ItemMetadata = field(default_factory=ItemMetadata)
    #: What inspection stored for each of `item.sources`, **positionally**: index *n* is part
    #: *n*'s inspection, or `None` where nothing has opened that file. Positional rather than
    #: keyed by path because every reader wants them in part order beside the sources they
    #: describe, and a mapping would make "part two was never inspected" a lookup miss rather
    #: than a `None` in the place it belongs.
    probes: tuple[MediaInspection | None, ...] = ()
    genres: tuple[NameLink, ...] = ()
    studios: tuple[NameLink, ...] = ()
    people: tuple[NameLink, ...] = ()
    artists: tuple[NameLink, ...] = ()
    images: tuple[ImageAssociation, ...] = ()
    #: A playlist's **stored** media type, and `None` for everything else.
    #:
    #: Here rather than on `Item` for the reason this record exists at all: it is not a property
    #: of anything a scanner reads. Measured, the reference fixes the value when the playlist is
    #: created and never revises it, so it is a fact about the row and `MEDIA_TYPE_OF` is only the
    #: fallback behind it `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11,
    #: 2026-08-31]`. `api/item_dto.py` prefers this when it is set (009 plan section 4.2).
    media_type: str | None = None
    user_data: UserItemData = field(default_factory=UserItemData)
    parent: Ancestor | None = None
    grandparent: Ancestor | None = None

    @property
    def id(self) -> str:
        return self.item.id


@dataclass(frozen=True, slots=True)
class ContainerAggregates:
    """What a container's subtree adds up to, for the fields a client asks for by name.

    `ChildCount`, `RecursiveItemCount`, `CumulativeRunTimeTicks` and `DateLastMediaAdded` are all
    statements about a container's descendants, and none of them can be answered by the row alone.
    They are fetched on demand - `aggregates_for` - rather than on every page, because a bare list
    row does not carry them (spec section 3.2: all four are gated) and a count nobody asked for is
    a count the page paid for anyway.
    """

    child_count: int = 0
    recursive_count: int = 0
    cumulative_runtime_ticks: int = 0
    date_last_media_added: datetime | None = None


@dataclass(frozen=True, slots=True)
class QueryPage:
    """A page of results and the count of everything the query matched before paging.

    `total` is the **pre-paging** count under exactly the query's predicates - that is what a
    client sizes a scrollbar with. When `count` is false it is `0`, which is the reference's own
    answer and is why this is not `None`: a client reading it gets a number either way, and the
    server saved a count query.
    """

    items: tuple[HydratedItem, ...] = ()
    total: int = 0


class ItemQueryRepository:
    """Every read of the item table that serves a query."""

    def __init__(self, session: OrmSession) -> None:
        self._session = session

    # -- the entry point ---------------------------------------------------------------------

    def run(self, query: ItemQuery) -> QueryPage:
        scoped = self._scope(query)
        if _is_random(query):
            return self._shuffled(scoped, query)

        total = self._count(scoped) if query.count else 0
        page = scoped.order_by(*_order_by(query)).offset(query.start_index)
        if query.limit is not None:
            page = page.limit(query.limit)
        rows = list(self._session.execute(page).scalars())
        return QueryPage(items=self._hydrate(rows, query.user), total=total)

    def root_listing(self, query: ItemQuery) -> QueryPage:
        """The user's top-level folders, and **not a query at all**.

        Measured on a reference instance over this repository's own fixture, one request per
        parameter `[probe: tools/probe_bare_items.py, Jellyfin 10.11.11, 2026-09-06]`: with no
        `parentId`, without `recursive`, and with no `ids`, the reference answers the reading
        account's top-level folders and **ignores every other parameter it was given** -
        `includeItemTypes`, `excludeItemTypes`, `mediaTypes`, `searchTerm`, `nameStartsWith`, the
        five by-name id filters, `years`, `genres`, `filters`, `isPlayed`, `sortBy`, `sortOrder`,
        `startIndex` and **`limit`**. `limit=2` answers six rows of six; `startIndex=2` answers all
        six and echoes the `2`.

        So this is a shape rather than a narrowing, which is why it is here and not a branch in
        `_scope`: everything `_scope` composes - the filters, the ordering, the paging - is exactly
        what this listing does not do.

        **`ids` is the one escape, and it is measured rather than assumed.** `ids=<a film>` with no
        parent and no `recursive` answers that film. A client naming items by identifier is asking
        about those items and not about the shape of the library, and treating it as a root listing
        would answer a question nobody asked - which is the regression this measurement prevented.

        **One row of the reference's six is not here.** Beside the five `CollectionFolder` rows it
        answers a `ManualPlaylistsFolder` named `Playlists`, a type this project does not model:
        009's playlists have no folder above them. That is a declared difference on 005's list
        rather than a gap this method invents an item to fill.

        **Called by the route and not by `run`, which is where the first attempt put it.** Every
        caller of `run` builds an `ItemQuery`, and two of them - `/Shows/NextUp` and
        `/UserItems/Resume` - build one with no parent and no recursion meaning *these items*
        rather than *the root*. A rule in the engine answered both of them with the library
        folders. The shape is a property of what `GET /Items` does with a request, so it is
        decided where the request is read.
        """
        rows = list(
            self._session.execute(
                select(models.Item)
                .where(self._visible_to(query.user))
                .where(models.Item.type == ItemType.COLLECTION_FOLDER.value)
                # By name, which is what the reference answered: the five went out alphabetically
                # rather than in the order they were declared, and its own playlists folder is
                # appended after them rather than sorted among them.
                .order_by(models.Item.name.asc(), models.Item.id.asc())
            ).scalars()
        )
        return QueryPage(
            items=self._hydrate(rows, query.user),
            total=len(rows) if query.count else 0,
        )

    def visible_ids(self, ids: Sequence[str], user: User) -> set[str]:
        """Which of these identifiers this user may see - the one predicate, asked as a question.

        The **only** public way for another module to reach `_visible_to`, and it exists because
        009's playlist entries have to be filtered by exactly what `/Items` filters by. The
        alternative was a second predicate in `db/repositories.py` covering "not removed, and in a
        library this user may open", which is this module's opening warning written out: two
        predicates in two places is how they stop agreeing, and the direction they fail in is a
        reader being handed rows they cannot open.

        A **question rather than the clause itself**: handing out a SQL expression would let a
        caller compose it into a query of their own and get the composition wrong, and the one
        caller there is wants a set. One statement, whatever the length of `ids`.
        """
        if not ids:
            return set()
        rows = self._session.execute(
            select(models.Item.id)
            .where(models.Item.id.in_(list(ids)))
            .where(self._visible_to(user))
        ).scalars()
        return set(rows)

    def _shuffled(self, scoped: Select[tuple[models.Item]], query: ItemQuery) -> QueryPage:
        """`Random`, which is not an `ORDER BY` at all (plan section 6.4).

        The matching **ids** are fetched, shuffled in process against a seed, and only the page is
        hydrated. Tens of thousands of 32-byte strings at worst, which is cheaper than teaching
        SQLite a seeded shuffle and exactly as observable as the reference's per-request one.

        The seed is fresh entropy per request and never exposed, so paging a random ordering is
        not meaningful - which is also true of the reference, whose shuffle is per *row* and whose
        two identical requests shared 4 items of 97
        `[probe: tools/probe_sort_stability.py, Jellyfin 10.11.11, 2026-08-27]`. Clients use it
        for a single page.
        """
        ids = list(
            self._session.execute(scoped.with_only_columns(models.Item.id).order_by(None)).scalars()
        )
        total = len(ids) if query.count else 0
        seed = query.random_seed if query.random_seed is not None else _entropy()
        # S311: a shuffle of a result page, not a secret. The *seed* comes from `secrets`
        # when the caller did not supply one, which is what stops a client predicting the
        # order; `random.Random` is the reproducible shuffle a test can inject into.
        shuffler = random.Random(seed)  # noqa: S311
        shuffler.shuffle(ids)

        end = None if query.limit is None else query.start_index + query.limit
        wanted = ids[query.start_index : end]
        if not wanted:
            return QueryPage(items=(), total=total)

        found = {
            row.id: row
            for row in self._session.execute(
                select(models.Item).where(models.Item.id.in_(wanted))
            ).scalars()
        }
        # Re-ordered to the shuffle: `IN` says nothing about order, and a page that came back in
        # id order would be a shuffle the client never sees.
        rows = [found[one] for one in wanted if one in found]
        return QueryPage(items=self._hydrate(rows, query.user), total=total)

    def run_by_name(
        self, kind: ItemType, query: ItemQuery, *, credit: str | None = None
    ) -> QueryPage:
        """The same pipeline with the type pinned (plan section 6.7).

        `credit` is what separates `/Artists` from `/Artists/AlbumArtists`: `None` means any
        credit and `album_artist` means that one. `MusicArtist` is the odd member of this family -
        it is a **per-library** row in Atrium rather than a by-name one (behaviours section 5.3),
        so it is already carried by the ordinary visibility predicate and only needs the credit
        reading on top.

        **The count is always true**, with `limit` and without. The reference disables counting on
        these routes when there is no `limit` and answers `TotalRecordCount: 0` beside a non-empty
        `Items`; Atrium diverges, argued in behaviours section 3.1.
        """
        statement = (
            select(models.Item)
            .where(models.Item.type == kind.value)
            .where(self._visible_to(query.user))
        )
        for clause in _filters(query):
            statement = statement.where(clause)
        if query.parent_id is not None or credit is not None:
            statement = statement.where(self._reached_from(kind, query, credit))

        total = self._count(statement) if query.count else 0
        page = statement.order_by(*_order_by(query)).offset(query.start_index)
        if query.limit is not None:
            page = page.limit(query.limit)
        rows = list(self._session.execute(page).scalars())
        return QueryPage(items=self._hydrate(rows, query.user), total=total)

    def _reached_from(self, kind: ItemType, query: ItemQuery, credit: str | None) -> Any:
        """Membership narrowed by `parentId`, by a credit reading, or by both.

        The general predicate already says *some visible item references this row*; this says
        *some visible item **in this scope** references it, under this credit*. Both are `EXISTS`
        over the same shape, and they are separate because the first is true of every query and
        the second only of these routes.
        """
        item = models.Item.__table__.alias("reached_from")
        visible = item.c.removed_at.is_(None) & self._library_permitted_on(item, query.user)
        if query.parent_id is not None:
            parent = self._require_visible(query.parent_id, query.user)
            if ItemType(parent.type) is ItemType.COLLECTION_FOLDER:
                visible = visible & (item.c.library_id == parent.library_id)
            else:
                visible = visible & item.c.id.in_(self._descendants(parent.id))

        if kind is ItemType.YEAR:
            return (
                select(item.c.id)
                .where(visible)
                .where(item.c.production_year == cast(models.Item.name, Integer))
                .correlate(models.Item.__table__)
                .exists()
            )

        if kind is ItemType.MUSIC_ARTIST:
            link_table, column = models.ItemArtist, "artist_item_id"
        else:
            link_table, column = _LINK_OF[kind]
        linked = (
            select(link_table.item_id)
            .where(link_table.item_id == item.c.id)
            .where(getattr(link_table, column) == models.Item.id)
            .where(visible)
            .correlate(models.Item.__table__)
        )
        if credit is not None:
            linked = linked.where(link_table.credit == credit)
        return linked.exists()

    # -- scope (plan section 6.2) ------------------------------------------------------------

    def _scope(self, query: ItemQuery) -> Select[tuple[models.Item]]:
        """The three shapes: the whole world, direct children, or a subtree.

        The recursive case has a fast path and a general one, and which applies is decided by the
        parent's *type* rather than by a flag. Under a `CollectionFolder` every descendant carries
        that library's id already, so the subtree is a column comparison. Under anything else it
        is a bounded walk down `DESCENT` levels of parent links.
        """
        statement = select(models.Item).where(self._visible_to(query.user))
        for clause in _filters(query):
            statement = statement.where(clause)

        if query.parent_id is None:
            return statement

        parent = self._require_visible(query.parent_id, query.user)
        if not query.recursive:
            return statement.where(models.Item.parent_id == parent.id)

        if ItemType(parent.type) is ItemType.COLLECTION_FOLDER:
            return statement.where(models.Item.library_id == parent.library_id).where(
                models.Item.id != parent.id
            )
        return statement.where(models.Item.id.in_(self._descendants(parent.id)))

    def _descendants(self, parent_id: str) -> Select[tuple[str]]:
        """Every item at most `DESCENT` hops below `parent_id`, as a subquery of ids.

        One clause per depth rather than a recursive CTE, because the depth *is* a constant of the
        domain model (`PARENT_OF`). A recursive query would be a general answer to a question that
        cannot become general without this module noticing - which is the point of `DESCENT` being
        a named number rather than a loop that stops when it runs out.

        Every level is its own alias. Reusing the mapped table inside a subquery of a statement
        that also selects from it invites SQLAlchemy to correlate the two, and a silently
        correlated subquery here answers "children of themselves".
        """
        node = models.Item.__table__.alias("descendant")
        clauses: list[Any] = [node.c.parent_id == parent_id]
        first = models.Item.__table__.alias("hop_0")
        frontier: Any = select(first.c.id).where(first.c.parent_id == parent_id)
        for level in range(1, DESCENT):
            clauses.append(node.c.parent_id.in_(frontier))
            further = models.Item.__table__.alias(f"hop_{level}")
            frontier = select(further.c.id).where(further.c.parent_id.in_(frontier))
        return select(node.c.id).where(or_(*clauses))

    def leaf_descendants(self, item_id: str, user: User) -> tuple[str, ...]:
        """The file-backed items beneath `item_id` that this user can see - the cascade's targets.

        Marking a container played marks its leaves and **never its own row** (spec section 3.4,
        measured), so this answers exactly the set a mark writes and nothing else: no seasons, no
        albums, no by-name rows, and nothing soft-removed or in a library the caller's policy does
        not permit. The visibility clause is the one every query uses, which is what makes "the
        caller's own scope" true rather than intended - the reference passes its user into its own
        sweep for the same reason.

        **A leaf answers the empty tuple, and so does an empty container.** A caller must branch on
        the item's *type* rather than on whether this came back empty: the two mean opposite
        things, and reading emptiness as "then write the item's own row" would mark an emptied
        season played on the one shape where the reference writes nothing at all.

        Raises `ParentNotFoundError` when the item is unknown or invisible, which is the same
        refusal every scoped query makes, so a mark cannot tell a caller that an item exists.
        """
        parent = self._require_visible(item_id, user)
        leaves = (
            select(models.Item.id)
            .where(self._visible_to(user))
            .where(models.Item.type.in_([kind.value for kind in FILE_BACKED]))
        )
        if ItemType(parent.type) is ItemType.COLLECTION_FOLDER:
            # The same fast path the scope has: everything under a library carries its id.
            leaves = leaves.where(models.Item.library_id == parent.library_id)
        else:
            leaves = leaves.where(models.Item.id.in_(self._descendants(parent.id)))
        return tuple(self._session.execute(leaves).scalars())

    def _require_visible(self, item_id: str, user: User) -> models.Item:
        found = self._session.execute(
            select(models.Item).where(models.Item.id == item_id).where(self._visible_to(user))
        ).scalar_one_or_none()
        if found is None:
            raise ParentNotFoundError(item_id)
        return found

    # -- visibility (plan section 6.1) -------------------------------------------------------

    def _visible_to(self, user: User) -> Any:
        """Everything a user may see, as one clause.

        Five parts, and the order they are written in is the order they exclude rows in: the item
        is not soft-deleted, its library is one this user's policy permits, - for the four
        container types - something with a file is still visible underneath it, a by-name row is
        still referenced by something visible, and a playlist is one this user may reach.

        **The fourth part is not a refinement of the second, and that is the whole reason it
        exists.** `_library_permitted` exempts a row with no library, because a by-name row is not
        *in* one; a playlist is not in one either (009 plan section 4.1), so it passed that clause
        for every caller. Without `_playlist_is_reachable`,
        `/Items?includeItemTypes=Playlist` answers every user's private playlists to everybody.
        """
        return (
            (models.Item.removed_at.is_(None))
            & self._library_permitted(user)
            & self._container_earns_its_place()
            & self._by_name_is_referenced(user)
            & self._playlist_is_reachable(user)
        )

    def _library_permitted(self, user: User) -> Any:
        """002's policy, as a clause rather than as a list walked in Python.

        A by-name row has no library and is exempt: a genre is not *in* a library, it is referenced
        by items that are, and 005 plan section 6.1 gives `/Genres` its own clause on top of this
        one (T8). `enable_all_folders` short-circuits to a literal true, so the common account
        costs no join at all.
        """
        by_name = models.Item.library_id.is_(None)
        if user.enable_all_folders:
            return or_(by_name, models.Item.library_id.is_not(None))
        permitted = (
            select(models.UserLibraryAccess.library_id)
            .where(models.UserLibraryAccess.user_id == user.id)
            .where(models.UserLibraryAccess.can_view)
        )
        return or_(by_name, models.Item.library_id.in_(permitted))

    def _by_name_is_referenced(self, user: User) -> Any:
        """A genre exists for a user while a **visible item** references it (plan section 6.1).

        Without this, `/Genres` lists a genre whose every film sits in a library the user cannot
        see - which is not a leak of the films but is a leak of *what is in the library*, and it
        is the one thing a by-name row can disclose. It is in the general predicate rather than in
        `run_by_name` because a by-name row is an item: `/Items?includeItemTypes=Genre` has to
        agree with `/Genres`, and two predicates in two places is how they stop agreeing.

        The five by-name kinds do not all reach their items the same way, which is why this is a
        `CASE` over the type rather than one clause: three have a join table, `Year` is referenced
        by a **column**, and `Person` and `Studio` have tables of their own.
        """
        return or_(
            models.Item.type.not_in([one.value for one in BY_NAME]),
            *((models.Item.type == kind.value) & self._referenced(kind, user) for kind in BY_NAME),
        )

    def _referenced(self, kind: ItemType, user: User) -> Any:
        """Whether any item this user may see points at the by-name row under consideration."""
        item = models.Item.__table__.alias(f"referencing_{kind.value.lower()}")
        visible = (
            (item.c.removed_at.is_(None))
            & self._library_permitted_on(item, user)
            & item.c.type.in_([one.value for one in IN_THE_TREE])
        )
        if kind is ItemType.YEAR:
            # The one by-name kind with **no join table**: a year is referenced by a column, and
            # the row's own name is the year as text.
            return (
                select(item.c.id)
                .where(visible)
                .where(item.c.production_year == cast(models.Item.name, Integer))
                .correlate(models.Item.__table__)
                .exists()
            )
        link, column = _LINK_OF[kind]
        return (
            select(link.item_id)
            .where(link.item_id == item.c.id)
            .where(getattr(link, column) == models.Item.id)
            .where(visible)
            .correlate(models.Item.__table__)
            .exists()
        )

    def _playlist_is_reachable(self, user: User) -> Any:
        """A playlist exists for a user who owns it, is shared with it, or when it is public.

        Spec section 3.7's four reading classes, as a clause on the general listing rather than as
        a check on the playlist routes alone. The routes are careful by construction - they load a
        playlist through one door that takes a `User` - and `/Items` is the listing beside them
        that would not have been: measured, a private playlist is **absent** from another user's
        `/Items?includeItemTypes=Playlist` and a shared or public one is **present**
        `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`
        `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`.

        **An administrator has no branch here, deliberately.** Spec section 3.7's table gives an
        administrator who is none of the three classes *no* read - deletion is the one operation
        they may perform on a playlist they do not own
        `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:132-134, 422-424, 461-463 @
        v10.11.11]` - so the clause is the same for every caller.

        A playlist item row with no `playlists` row fails the `EXISTS` and is invisible, which is
        the direction to fail in: an unreachable half-written row discloses nothing.
        """
        playlist = models.Playlist
        shared_with = select(models.PlaylistShare.playlist_id).where(
            models.PlaylistShare.user_id == user.id
        )
        reachable = (
            select(playlist.item_id)
            .where(playlist.item_id == models.Item.id)
            .where(
                or_(
                    playlist.is_public,
                    playlist.owner_user_id == user.id,
                    playlist.item_id.in_(shared_with),
                )
            )
            # `correlate` for `_by_name_is_referenced`'s reason: without it the subquery takes its
            # own copy of `items` and the clause is true for every row that any playlist matches.
            .correlate(models.Item.__table__)
            .exists()
        )
        return or_(models.Item.type != ItemType.PLAYLIST.value, reachable)

    def _library_permitted_on(self, item: Any, user: User) -> Any:
        """`_library_permitted`, against an aliased items table rather than the mapped one."""
        if user.enable_all_folders:
            return item.c.library_id.is_not(None)
        permitted = (
            select(models.UserLibraryAccess.library_id)
            .where(models.UserLibraryAccess.user_id == user.id)
            .where(models.UserLibraryAccess.can_view)
        )
        return item.c.library_id.in_(permitted)

    def _container_earns_its_place(self) -> Any:
        """A `Series`, `Season`, `MusicArtist` or `MusicAlbum` with nothing visible beneath it is
        not offered - behaviours section 5.2's closing half.

        One correlated `EXISTS` covering both depths, because `Season` holds its episodes directly
        and `Series` holds them one level further down. Bounded by `DESCENT`, never recursive.
        """
        container = models.Item.__table__.alias("descendant_of")
        middle = models.Item.__table__.alias("middle_of")
        # **`correlate` is not optional here**, and the failure it prevents is silent. Without it
        # SQLAlchemy puts `items` in the subquery's own FROM, which turns the correlated EXISTS
        # into a cross join: the clause then asks "does *any* episode exist" and every container
        # in the library passes. It was caught by emptying a series and watching it stay visible.
        beneath = (
            select(container.c.id)
            .where(container.c.removed_at.is_(None))
            .where(container.c.type.in_([one.value for one in FILE_BACKED]))
            .where(
                or_(
                    container.c.parent_id == models.Item.id,
                    container.c.parent_id.in_(
                        select(middle.c.id)
                        .where(middle.c.parent_id == models.Item.id)
                        .correlate(models.Item.__table__)
                    ),
                )
            )
            .correlate(models.Item.__table__)
        )
        return or_(
            models.Item.type.not_in([one.value for one in EARN_THEIR_PLACE]),
            beneath.exists(),
        )

    # -- counting ----------------------------------------------------------------------------

    def _count(self, scoped: Select[tuple[models.Item]]) -> int:
        """The count of what the query matches, before paging.

        Derived from the same statement the page comes from rather than rebuilt beside it. Two
        statements that were meant to carry the same predicates and drifted is how a client ends
        up paging past the end of a list that said it was longer.
        """
        counted = scoped.with_only_columns(models.Item.id).order_by(None)
        return len(self._session.execute(counted).scalars().all())

    # -- hydration (plan section 5) ----------------------------------------------------------

    def _hydrate(self, rows: Sequence[models.Item], user: User) -> tuple[HydratedItem, ...]:
        """One query per related table for the whole page, never one per item.

        The statement count is a property of this method and is asserted by the query counter in
        the suite: a page of one and a page of a hundred cost the same number of round trips.
        The ancestor and rollup queries below run **unconditionally** for the same reason - a
        count that depended on what types the page happened to contain would make the counter's
        equality assertion meaningless.
        """
        if not rows:
            return ()
        ids = [row.id for row in rows]

        sources = self._grouped(models.ItemSource, ids)
        probes = self._probes(rows, sources)
        genres = self._grouped(models.ItemGenre, ids)
        studios = self._grouped(models.ItemStudio, ids)
        people = self._grouped(models.ItemPerson, ids)
        artists = self._grouped(models.ItemArtist, ids)
        images = self._grouped(models.ItemImage, ids)
        user_data = self._user_data(ids, user)
        ancestors = self._ancestors(rows)
        rollups = self._rollups(rows, user)
        media_types = self._playlist_media_types(ids)

        return tuple(
            HydratedItem(
                item=_item(row, sources.get(row.id, [])),
                metadata=_metadata(row),
                probes=probes.get(row.id, ()),
                genres=tuple(
                    NameLink(name=one.name, item_id=one.genre_item_id)
                    for one in _ordered(genres.get(row.id, []))
                ),
                studios=tuple(
                    NameLink(name=one.name, item_id=one.studio_item_id)
                    for one in _ordered(studios.get(row.id, []))
                ),
                people=tuple(
                    NameLink(
                        name=one.name,
                        item_id=one.person_item_id,
                        credit=one.person_type,
                        role=one.role,
                    )
                    # `sort_order` rather than `position`: the people table spells its document
                    # order differently from the other three, because the credit order *is* the
                    # sort order a source supplied (004 spec section 3.7 rule 2).
                    for one in sorted(people.get(row.id, []), key=lambda one: one.sort_order)
                ),
                artists=tuple(
                    NameLink(name=one.name, item_id=one.artist_item_id, credit=one.credit)
                    for one in _ordered(artists.get(row.id, []))
                ),
                images=tuple(
                    _image(one)
                    for one in sorted(images.get(row.id, []), key=lambda one: one.image_index)
                ),
                media_type=media_types.get(row.id),
                user_data=_rolled(user_data.get(row.id, UserItemData()), rollups.get(row.id)),
                parent=ancestors.get(row.id, (None, None))[0],
                grandparent=ancestors.get(row.id, (None, None))[1],
            )
            for row in rows
        )

    def _playlist_media_types(self, ids: Sequence[str]) -> dict[str, str]:
        """The stored media type of every playlist on the page, one statement for the page.

        **`HydratedItem.media_type` had no writer on this path, and `mediaTypes=` is what made
        that visible.** T4 added the field and taught `api/item_dto.py` to prefer it, and plan
        section 4.2 left the filling to T7's `PlaylistRepository` - which serves the playlist
        routes and not this one. So every playlist listed through `/Items` fell through to
        `MEDIA_TYPE_OF[Playlist]` and answered `MediaType: "Audio"`, four of the fixture world's
        five of them wrongly. Left alone, T6's filter would have returned a row for
        `mediaTypes=Video` whose own body said `Audio`: a listing disagreeing with itself is worse
        than the gap the filter was closing. Measured, the reference's list row carries the same
        value its bare item does `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11,
        2026-08-31]`.

        Unconditional, like the ancestors and the inspections above and for their reason: a
        statement that ran only when the page held a playlist would make the counter's equality
        assertion a property of the page rather than of hydration.
        """
        rows = self._session.execute(
            select(models.Playlist.item_id, models.Playlist.media_type).where(
                models.Playlist.item_id.in_(ids)
            )
        ).all()
        return {row.item_id: row.media_type for row in rows}

    def _probes(
        self, rows: Sequence[models.Item], sources: Mapping[str, Sequence[models.ItemSource]]
    ) -> dict[str, tuple[MediaInspection | None, ...]]:
        """What inspection stored for the page's files, in part order, two statements for the page.

        **Two, and unconditionally**, which is this method's own rule: the statement count is a
        property of hydration rather than of what the page happened to contain, and a page that
        skipped these because no row had a file would make the counter's equality assertion
        meaningless (and would then cost a round trip the first time a movie appeared).

        Read by `(library_id, relative_path)` because that is how the probe is keyed - the pair
        `item_sources` already names the file with - so a remounted root keeps its inspections.
        The predicate is a tuple `IN`, which SQLite expands to one comparison per file rather
        than to a join this page does not need; an empty one compiles to a false clause rather
        than to a skipped statement, which is what keeps the count fixed on a page of containers.
        """
        wanted = sorted(
            {
                (row.library_id, one.relative_path)
                for row in rows
                if row.library_id is not None
                for one in sources.get(row.id, ())
            }
        )
        found = {
            (one.library_id, one.relative_path): one
            for one in self._session.scalars(
                select(models.MediaProbe).where(
                    tuple_(models.MediaProbe.library_id, models.MediaProbe.relative_path).in_(
                        wanted
                    )
                )
            )
        }
        streams: dict[tuple[str, str], list[models.MediaStreamRow]] = {}
        for one in self._session.scalars(
            select(models.MediaStreamRow)
            .where(
                tuple_(models.MediaStreamRow.library_id, models.MediaStreamRow.relative_path).in_(
                    wanted
                )
            )
            .order_by(models.MediaStreamRow.stream_index)
        ):
            streams.setdefault((one.library_id, one.relative_path), []).append(one)

        # **A third statement, and a listing is wrong without it.** These are the subtitle streams
        # discovered in files beside the media, and they are numbered *ahead of* the container's
        # own - so a page hydrated from the two statements above would answer a stream list that
        # is both short and misnumbered, and `HasSubtitles` would be false on an item whose
        # subtitles are all files (011 AC-11). Page-independent, like the two above it.
        externals: dict[tuple[str, str], list[models.MediaExternalStreamRow]] = {}
        for external in self._session.scalars(
            select(models.MediaExternalStreamRow)
            .where(
                tuple_(
                    models.MediaExternalStreamRow.library_id,
                    models.MediaExternalStreamRow.relative_path,
                ).in_(wanted)
            )
            .order_by(models.MediaExternalStreamRow.ordinal)
        ):
            externals.setdefault((external.library_id, external.relative_path), []).append(external)

        collected: dict[str, tuple[MediaInspection | None, ...]] = {}
        for row in rows:
            parts = sorted(sources.get(row.id, ()), key=lambda one: one.part_index)
            if not parts or row.library_id is None:
                continue
            collected[row.id] = tuple(
                None
                if (key := (row.library_id, one.relative_path)) not in found
                else inspection_of(found[key], streams.get(key, []), externals.get(key, []))
                for one in parts
            )
        return collected

    def _ancestors(self, rows: Sequence[models.Item]) -> dict[str, tuple[Ancestor | None, ...]]:
        """The page's parents and grandparents, summarised - four statements, page-independent.

        Two levels is the whole tree (`DESCENT`), and the summaries carry exactly what a response
        reads off an ancestor: the name, the image tags, and - for an album - the credits.
        Ancestors are **not** visibility-filtered: reaching an episode already proved its series
        visible, and a name the item itself displays is not a disclosure.
        """
        parent_ids = sorted({row.parent_id for row in rows if row.parent_id})
        parents = {
            one.id: one
            for one in self._session.execute(
                select(models.Item).where(models.Item.id.in_(parent_ids))
            ).scalars()
        }
        grand_ids = sorted(
            {one.parent_id for one in parents.values() if one.parent_id} - set(parents)
        )
        grands = {
            one.id: one
            for one in self._session.execute(
                select(models.Item).where(models.Item.id.in_(grand_ids))
            ).scalars()
        }
        everyone = {**parents, **grands}
        images = self._grouped(models.ItemImage, sorted(everyone))
        artists = self._grouped(models.ItemArtist, sorted(everyone))

        def summarised(row: models.Item) -> Ancestor:
            return Ancestor(
                id=row.id,
                type=ItemType(row.type),
                name=row.name,
                images=tuple(
                    _image(one)
                    for one in sorted(images.get(row.id, []), key=lambda one: one.image_index)
                ),
                artists=tuple(
                    NameLink(name=one.name, item_id=one.artist_item_id, credit=one.credit)
                    for one in _ordered(artists.get(row.id, []))
                ),
            )

        summaries = {one_id: summarised(one) for one_id, one in everyone.items()}
        linked: dict[str, tuple[Ancestor | None, ...]] = {}
        for row in rows:
            parent_row = everyone.get(row.parent_id) if row.parent_id else None
            above = parent_row.parent_id if parent_row is not None else None
            linked[row.id] = (
                summaries.get(row.parent_id) if row.parent_id else None,
                summaries.get(above) if above else None,
            )
        return linked

    def _rollups(self, rows: Sequence[models.Item], user: User) -> dict[str, tuple[int, int]]:
        """`(files, played)` beneath every tree container on the page - two statements.

        The reference reports a container's `UserData` as a statement about its subtree: `Played`
        exactly when nothing visible beneath is left unplayed, and the remainder as
        `UnplayedItemCount`, on every bare container row
        `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. Counted
        here per page rather than stored, because a stored rollup is a cache with an invalidation
        problem, and the two grouped statements are page-size-independent.

        A `CollectionFolder`'s subtree is its library (the same fast path as scope); everything
        else rolls up through the bounded parent chain.
        """
        containers = [
            row
            for row in rows
            if ItemType(row.type) in IN_THE_TREE and ItemType(row.type) not in FILE_BACKED
        ]
        chained = sorted(
            row.id for row in containers if ItemType(row.type) is not ItemType.COLLECTION_FOLDER
        )
        libraries = {
            row.library_id: row.id
            for row in containers
            if ItemType(row.type) is ItemType.COLLECTION_FOLDER and row.library_id
        }
        counted: dict[str, tuple[int, int]] = {row.id: (0, 0) for row in containers}

        def accumulate(container_id: str | None, total: int, played: int) -> None:
            if container_id in counted:
                sofar = counted[container_id]
                counted[container_id] = (sofar[0] + total, sofar[1] + played)

        for level_one, level_two, total, played in self._session.execute(
            self._files_under_chain(user, chained)
        ):
            accumulate(level_one, total, played or 0)
            accumulate(level_two, total, played or 0)

        for library_id, total, played in self._session.execute(
            self._files_under_library(user, sorted(libraries))
        ):
            accumulate(libraries.get(library_id), total, played or 0)

        return counted

    def _files_under_chain(
        self, user: User, container_ids: Sequence[str], with_sums: bool = False
    ) -> Any:
        """Visible files grouped by their parent *and* grandparent, constrained to the ids given.

        `with_sums` appends the runtime total and the latest arrival, for `aggregates_for`;
        the rollups leave them off rather than pay for sums nobody asked about.
        """
        child = models.Item.__table__.alias("rolled_up")
        parent = models.Item.__table__.alias("rolled_through")
        state = models.ItemUserData.__table__.alias("rolled_state")
        columns: list[Any] = [
            parent.c.id,
            parent.c.parent_id,
            func.count(),
            func.sum(case((state.c.played, 1), else_=0)),
        ]
        if with_sums:
            columns += [
                func.sum(func.coalesce(child.c.runtime_ticks, 0)),
                func.max(child.c.date_created),
            ]
        return (
            select(*columns)
            .select_from(
                child.join(parent, child.c.parent_id == parent.c.id).outerjoin(
                    state,
                    (state.c.item_key == child.c.id) & (state.c.user_id == user.id),
                )
            )
            .where(child.c.type.in_([one.value for one in FILE_BACKED]))
            .where(child.c.removed_at.is_(None))
            .where(self._library_permitted_on(child, user))
            .where(or_(parent.c.id.in_(container_ids), parent.c.parent_id.in_(container_ids)))
            .group_by(parent.c.id, parent.c.parent_id)
        )

    def _files_under_library(
        self, user: User, library_ids: Sequence[str], with_sums: bool = False
    ) -> Any:
        """Visible files grouped by library, for the `CollectionFolder` shapes of both callers."""
        child = models.Item.__table__.alias("rolled_flat")
        state = models.ItemUserData.__table__.alias("rolled_flat_state")
        columns: list[Any] = [
            child.c.library_id,
            func.count(),
            func.sum(case((state.c.played, 1), else_=0)),
        ]
        if with_sums:
            columns += [
                func.sum(func.coalesce(child.c.runtime_ticks, 0)),
                func.max(child.c.date_created),
            ]
        return (
            select(*columns)
            .select_from(
                child.outerjoin(
                    state,
                    (state.c.item_key == child.c.id) & (state.c.user_id == user.id),
                )
            )
            .where(child.c.type.in_([one.value for one in FILE_BACKED]))
            .where(child.c.removed_at.is_(None))
            .where(self._library_permitted_on(child, user))
            .where(child.c.library_id.in_(library_ids))
            .group_by(child.c.library_id)
        )

    def aggregates_for(self, ids: Sequence[str], user: User) -> dict[str, ContainerAggregates]:
        """The gated subtree numbers for the containers a route resolved `Fields` to need.

        Four statements whatever the batch holds: the rows themselves, one grouped count of
        direct children, and the two rollup shapes with the sums and the latest date attached.
        On demand rather than in `_hydrate`, because every one of these is a gated field
        (spec section 3.2) and a bare list row never carries them.
        """
        rows = list(
            self._session.execute(select(models.Item).where(models.Item.id.in_(ids))).scalars()
        )
        containers = [
            row
            for row in rows
            if ItemType(row.type) in IN_THE_TREE and ItemType(row.type) not in FILE_BACKED
        ]
        chained = sorted(
            row.id for row in containers if ItemType(row.type) is not ItemType.COLLECTION_FOLDER
        )
        libraries = {
            row.library_id: row.id
            for row in containers
            if ItemType(row.type) is ItemType.COLLECTION_FOLDER and row.library_id
        }

        children: dict[str, int] = {
            parent_id: counted
            for parent_id, counted in self._session.execute(
                select(models.Item.parent_id, func.count())
                .where(models.Item.parent_id.in_(sorted(row.id for row in containers)))
                .where(self._visible_to(user))
                .group_by(models.Item.parent_id)
            )
            if parent_id is not None
        }

        wanted = {row.id for row in containers}
        recursive: dict[str, tuple[int, int, datetime | None]] = {}

        def accumulate(
            container_id: str | None, total: int, runtime: int, latest: datetime | None
        ) -> None:
            if container_id is None or container_id not in wanted:
                return
            count_sofar, runtime_sofar, latest_sofar = recursive.get(container_id, (0, 0, None))
            newest = max(
                (when for when in (latest_sofar, latest) if when is not None), default=None
            )
            recursive[container_id] = (count_sofar + total, runtime_sofar + runtime, newest)

        for level_one, level_two, total, _played, runtime, latest in self._session.execute(
            self._files_under_chain(user, chained, with_sums=True)
        ):
            accumulate(level_one, total, runtime or 0, latest)
            accumulate(level_two, total, runtime or 0, latest)

        for library_id, total, _played, runtime, latest in self._session.execute(
            self._files_under_library(user, sorted(libraries), with_sums=True)
        ):
            accumulate(libraries.get(library_id), total, runtime or 0, latest)

        return {
            row.id: ContainerAggregates(
                child_count=children.get(row.id, 0),
                recursive_count=recursive.get(row.id, (0, 0, None))[0],
                cumulative_runtime_ticks=recursive.get(row.id, (0, 0, None))[1],
                date_last_media_added=recursive.get(row.id, (0, 0, None))[2],
            )
            for row in containers
        }

    def _grouped(self, model: Any, ids: Sequence[str]) -> dict[str, list[Any]]:
        rows = self._session.execute(select(model).where(model.item_id.in_(ids))).scalars()
        collected: dict[str, list[Any]] = {}
        for row in rows:
            collected.setdefault(row.item_id, []).append(row)
        return collected

    def _user_data(self, ids: Sequence[str], user: User) -> dict[str, UserItemData]:
        """Keyed on `item_key`, the derived identity, which for a live item is its id.

        The column is not a foreign key on purpose (003 spec section 3.8): the row outlives the
        item, so that a file which disappears and comes back does not cost the user their
        favourites. Reading it by id is correct precisely because the identity *is* the id.
        """
        rows = self._session.execute(
            select(models.ItemUserData)
            .where(models.ItemUserData.user_id == user.id)
            .where(models.ItemUserData.item_key.in_(ids))
        ).scalars()
        return {
            row.item_key: UserItemData(
                is_favorite=row.is_favorite,
                played=row.played,
                play_count=row.play_count,
                playback_position_ticks=row.playback_position_ticks,
                last_played_date=row.last_played_date,
            )
            for row in rows
        }


# ------------------------------------------------------------------------------------------------
# Ordering
# ------------------------------------------------------------------------------------------------


def _entropy() -> int:
    """A seed nobody chose and nobody can reproduce. Not `random.seed()`'s own default, so that
    the one place randomness enters this module is visible."""
    return secrets.randbits(64)


def _is_random(query: ItemQuery) -> bool:
    """`Random` is decided by the **first** key, because it is not an `ORDER BY` and cannot be
    combined with one. `sortBy=Random,SortName` is a random ordering."""
    return bool(query.sort) and query.sort[0][0] is SortBy.RANDOM


def _order_by(query: ItemQuery) -> list[Any]:
    """The requested keys, and the tail that makes every ordering **total**.

    behaviours section 3.6 is why the tail exists. The reference appends `Name` after `SortName`
    and nothing at all after any other key - and the cost of that was measured: under
    `AlbumArtist` and `Artist` the concatenation of a query's pages is *not* the one-shot list, so
    a client paging a large audio library sees some items twice and never sees others. Atrium
    appends the id, so paging visits every item exactly once for every `SortBy`. Within a tie the
    result is an order the reference could have produced; what changes is that it holds still.

    A relevance ranking goes **ahead of everything** when `searchTerm` is present, which is the
    reference's own behaviour and not a nicety
    `[source: Jellyfin.Server.Implementations/Item/BaseItemRepository.cs:1604-1611 @ v10.11.11]`:
    a search ordered by name first is a search whose best match is on page four.
    """
    keys: list[Any] = []
    if query.search_term:
        keys.append(_relevance(query.search_term))

    requested = query.sort or ((SortBy.SORT_NAME, SortOrder.ASCENDING),)
    for sort_by, order in requested:
        if sort_by is SortBy.RANDOM:
            continue
        keys.append(_directed(_primary(sort_by, query.user), order))

    # `Name` after a `SortName` ordering is the one chain the reference has. Then the id, always,
    # which is the divergence and the whole of it.
    if requested[0][0] is SortBy.SORT_NAME:
        keys.append(_directed(models.Item.name, requested[0][1]))
    keys.append(models.Item.id.asc())
    return keys


def _directed(expression: Any, order: SortOrder) -> Any:
    return expression.desc() if order is SortOrder.DESCENDING else expression.asc()


def _primary(sort_by: SortBy, user: User) -> Any:
    """Plan section 6.3's table, one expression per key."""
    if sort_by is SortBy.SORT_NAME:
        return models.Item.sort_name
    if sort_by is SortBy.DATE_CREATED:
        return models.Item.date_created
    if sort_by is SortBy.PREMIERE_DATE:
        return _premiere_year()
    if sort_by is SortBy.PLAY_COUNT:
        return func.coalesce(_user_scalar(models.ItemUserData.play_count, user), 0)
    if sort_by is SortBy.DATE_PLAYED:
        return _user_scalar(models.ItemUserData.last_played_date, user)
    if sort_by is SortBy.ALBUM_ARTIST:
        return _credit_name(ALBUM_ARTIST_CREDIT)
    if sort_by is SortBy.ARTIST:
        return _credit_name(PERFORMER_CREDIT)
    raise ValueError(f"no ordering for {sort_by}")


def _premiere_year() -> Any:
    """An item with no `PremiereDate` sorts by **January 1 of its `ProductionYear`** rather than
    clumping with the dateless
    `[source: Jellyfin.Server.Implementations/Item/OrderMapper.cs:49 @ v10.11.11]`.

    Expressed as *the effective year* rather than as a synthesised date, and the difference is
    portability: `COALESCE(premiere_date, jan1(production_year))` needs a database function that
    builds a timestamp out of an integer, and every dialect spells that differently.
    `extract('year', …)` is one SQLAlchemy construct that compiles on both, and ordering by the
    year first puts a year-only item exactly where January 1 would put it - ahead of every dated
    item of the same year, which is what `_order_by`'s caller pairs it with below.
    """
    return func.coalesce(extract("year", models.Item.premiere_date), models.Item.production_year)


def _user_scalar(column: Any, user: User) -> Any:
    """One of the requesting user's user-data values, as a correlated scalar.

    Correlated for the reason everything else here is: without it the subquery grows its own
    `FROM` and stops being about this item.
    """
    return (
        select(column)
        .where(models.ItemUserData.user_id == user.id)
        .where(models.ItemUserData.item_key == models.Item.id)
        .correlate(models.Item.__table__)
        .scalar_subquery()
    )


def _credit_name(credit: str) -> Any:
    """The lowest credit name of one kind on this item, as a correlated scalar.

    ⚠️ **Lower-cased rather than folded.** `fold_for_search` also strips diacritics and no SQL
    dialect does that portably, so `Ángel` and `Angel` sort apart here where the search fold would
    put them together. The reference's own key for these two sorts lives in a joined table the API
    does not return, which is why `probe_sort_stability.py` reports rather than concludes on them
    - so there is nothing measured to be wrong against, and this is recorded as a known
    approximation rather than a claim.
    """
    return (
        select(func.min(func.lower(models.ItemArtist.name)))
        .where(models.ItemArtist.item_id == models.Item.id)
        .where(models.ItemArtist.credit == credit)
        .correlate(models.Item.__table__)
        .scalar_subquery()
    )


def _relevance(term: str) -> Any:
    """Match quality, ahead of whatever `sortBy` asked for: exact, prefix at a word boundary,
    prefix, contains
    `[source: Jellyfin.Server.Implementations/Item/OrderMapper.cs:76-93 @ v10.11.11]`.

    Ascending, because the ranks count upwards from the best match - a `CASE` whose numbers went
    the other way would need every caller to remember the direction.
    """
    folded = fold_for_search(term)
    name = models.Item.name_folded
    return case(
        (name == folded, 0),
        (name.startswith(folded), 1),
        (name.contains(f" {folded}"), 2),
        else_=3,
    ).asc()


# ------------------------------------------------------------------------------------------------
# The filter battery
# ------------------------------------------------------------------------------------------------


def _filters(query: ItemQuery) -> list[Any]:
    """Every predicate `ItemQuery` names, as clauses, in one place.

    A list rather than a chain of `if` statements inside the query builder, because the property
    that matters is that **each field narrows something**: plan section 8 row 16 tests one
    parameter at a time against a world slice built to be narrowed by it, and a predicate that
    silently did nothing would pass every functional test in the feature.

    `None` means "the client did not ask", and an **empty collection means the client asked for
    nothing** - `includeItemTypes=` with every token unrecognised drops to an empty tuple
    (behaviours section 1.12), and the honest answer to "items of no type" is no items rather
    than every item.
    """
    clauses: list[Any] = []
    item = models.Item

    if query.include_types is not None:
        clauses.append(item.type.in_([one.value for one in query.include_types]))
    if query.exclude_types is not None:
        clauses.append(item.type.not_in([one.value for one in query.exclude_types]))
    if query.media_types is not None:
        clauses.append(_media_type_is(query.media_types))

    if query.ids is not None:
        clauses.append(item.id.in_(list(query.ids)))
    if query.exclude_ids is not None:
        clauses.append(item.id.not_in(list(query.exclude_ids)))

    clauses += _name_clauses(query)
    clauses += _related_clauses(query)
    clauses += _user_state_clauses(query)

    if query.years is not None:
        clauses.append(item.production_year.in_(list(query.years)))
    if query.min_community_rating is not None:
        clauses.append(item.community_rating >= query.min_community_rating)
    return clauses


def _media_type_is(media_types: Iterable[str]) -> Any:
    """`mediaTypes=`, which is **two questions** because a playlist answers it per row.

    Thirteen of the fourteen types answer from the type: a film is `Video`, a track is `Audio`, a
    container is `Unknown`, measured once into `MEDIA_TYPE_OF`. A playlist's value is decided at
    creation and stored on the row, and the reference filters playlists by that stored value -
    `mediaTypes=Audio` returns the audio playlist and not the video one, and `mediaTypes=Video`
    the reverse `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`. So
    the clause is a type test **or** a stored-value test, and `Playlist` is excluded from the
    first half rather than given a type-level guess: reading `MEDIA_TYPE_OF[Playlist]` here would
    claim every playlist for `Audio` and none for `Video`.

    **The stored half compares the row, not a two-value special case, and that is measured.** A
    playlist can answer `Unknown` - measured on a stock reference holding eight playlists,
    `mediaTypes=Audio` returns five, `mediaTypes=Video` two and `mediaTypes=Unknown` **one**
    `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`. Creation cannot
    produce that value - an id list that resolves to nothing falls back to `Audio`
    `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:124-126 @ v10.11.11]` - but
    a playlist the scanner resolves from a directory is given no media type at all
    `[source: Emby.Server.Implementations/Library/Resolvers/PlaylistResolver.cs:40-45 @ v10.11.11]`
    and its own file cannot restore one, because an `Unknown` media type is the one value the
    saver does not write
    `[source: MediaBrowser.LocalMetadata/Savers/PlaylistXmlSaver.cs:52-55 @ v10.11.11]`. Atrium
    has no filesystem playlists (009 spec section 4), so its column holds `Audio` or `Video` - but
    the clause answers whatever the column holds, which is what makes that true by measurement
    rather than by assumption.

    Matching case-insensitively on both halves, for the reason `known_tokens` gives: a parameter
    whose name matches case-insensitively while its values did not would be a distinction no
    client could have learned. Measured, `mediaTypes=audio` and `mediaTypes=Audio` are one answer.
    """
    wanted = sorted({one.casefold() for one in media_types})
    types = [
        kind.value
        for kind, media in MEDIA_TYPE_OF.items()
        if kind is not ItemType.PLAYLIST and media.casefold() in wanted
    ]
    stored = (
        select(models.Playlist.item_id)
        .where(models.Playlist.item_id == models.Item.id)
        .where(func.lower(models.Playlist.media_type).in_(wanted))
        .correlate(models.Item.__table__)
        .exists()
    )
    return or_(models.Item.type.in_(types), stored)


def _name_clauses(query: ItemQuery) -> list[Any]:
    """Everything matched against `name_folded`, which 004 wrote and nothing read until now.

    Case **and** diacritics are folded on both sides, so a user typing `amelie` finds `Amélie`.
    Folding only the column would make the filter depend on how the client typed it; folding only
    the term would make it depend on how the file was named.
    """
    clauses: list[Any] = []
    folded = models.Item.name_folded
    if query.search_term:
        clauses.append(folded.contains(fold_for_search(query.search_term)))
    if query.name_starts_with:
        clauses.append(folded.startswith(fold_for_search(query.name_starts_with)))
    if query.name_starts_with_or_greater:
        clauses.append(folded >= fold_for_search(query.name_starts_with_or_greater))
    if query.name_less_than:
        clauses.append(folded < fold_for_search(query.name_less_than))
    return clauses


def _related_clauses(query: ItemQuery) -> list[Any]:
    """The join tables, each as an `EXISTS` rather than a join.

    A join would multiply the result set by the number of matching rows and need a `DISTINCT` to
    undo it, which then has to survive every `ORDER BY` T7 adds. `EXISTS` asks the question the
    filter is actually asking - *is there one* - and leaves the row count alone.
    """
    clauses: list[Any] = []
    if query.genres is not None:
        clauses.append(_links_to(models.ItemGenre, "genre_item_id", _genre_ids(query.genres)))
    if query.genre_ids is not None:
        clauses.append(_links_to(models.ItemGenre, "genre_item_id", list(query.genre_ids)))
    if query.studio_ids is not None:
        clauses.append(_links_to(models.ItemStudio, "studio_item_id", list(query.studio_ids)))
    if query.person_ids is not None:
        clauses.append(_links_to(models.ItemPerson, "person_item_id", list(query.person_ids)))
    if query.artist_ids is not None:
        clauses.append(_links_to(models.ItemArtist, "artist_item_id", list(query.artist_ids)))
    if query.album_artist_ids is not None:
        # **The credit column, leaned on for the first time.** `/Artists` and
        # `/Artists/AlbumArtists` are these same rows distinguished by this one value, so a filter
        # that ignored it would make the two endpoints impossible to tell apart from a query.
        clauses.append(
            _links_to(
                models.ItemArtist,
                "artist_item_id",
                list(query.album_artist_ids),
                credit=ALBUM_ARTIST_CREDIT,
            )
        )
    if query.album_ids is not None:
        # A track's album is its parent. There is no album column, and inventing one would be a
        # second place for a fact the tree already states.
        clauses.append(models.Item.parent_id.in_(list(query.album_ids)))
    return clauses


def _genre_ids(names: Iterable[str]) -> list[str]:
    """Genre **names** to the by-name rows they identify, both kinds.

    A name rather than an id is what a client sends when it never fetched the by-name row, and it
    has to find the item whichever spelling that item used: two spellings of one genre merge to
    one row (behaviours section 2.18), and the row's identity is derived from the folded name. So
    the name is folded through the project's own identity rule rather than compared as a string,
    and `Genre` and `MusicGenre` are both offered because a client filtering by `Rock` does not
    know which table its films and its tracks landed in.
    """
    return [
        for_by_name(kind, name) for name in names for kind in (ItemType.GENRE, ItemType.MUSIC_GENRE)
    ]


def _links_to(model: Any, column: str, ids: Sequence[str], credit: str | None = None) -> Any:
    linked = (
        select(model.item_id)
        .where(model.item_id == models.Item.id)
        .where(getattr(model, column).in_(list(ids)))
        .correlate(models.Item.__table__)
    )
    if credit is not None:
        linked = linked.where(model.credit == credit)
    return linked.exists()


def _user_state_clauses(query: ItemQuery) -> list[Any]:
    """Favourite, played and resumable - and **absence of a row is a state**, not a gap.

    A user with no `item_user_data` row for an item has not played it and has not favourited it.
    So "unplayed" is `NOT EXISTS(played)` rather than `EXISTS(NOT played)`: the second finds only
    the items somebody has already touched, which for a fresh account is none of them.
    """
    clauses: list[Any] = []
    if query.is_favorite is not None:
        clauses.append(_user_state(models.ItemUserData.is_favorite, query.user, query.is_favorite))
    if query.is_played is not None:
        clauses.append(_user_state(models.ItemUserData.played, query.user, query.is_played))

    if Filter.IS_FAVORITE in query.filters:
        clauses.append(_user_state(models.ItemUserData.is_favorite, query.user, True))
    if Filter.IS_PLAYED in query.filters:
        clauses.append(_user_state(models.ItemUserData.played, query.user, True))
    if Filter.IS_UNPLAYED in query.filters:
        clauses.append(_user_state(models.ItemUserData.played, query.user, False))
    if Filter.IS_RESUMABLE in query.filters:
        # `playback_position_ticks > 0`. 007 section 3.7's six-branch rule already guarantees a
        # stored position is a mid-playback one: a report past the completion threshold clears it
        # and marks the item played instead, so there is no "resumable at 99%" to exclude here.
        clauses.append(
            _user_row(query.user).where(models.ItemUserData.playback_position_ticks > 0).exists()
        )
    return clauses


def _user_state(column: Any, user: User, wanted: bool) -> Any:
    present = _user_row(user).where(column).exists()
    return present if wanted else ~present


def _user_row(user: User) -> Select[tuple[str]]:
    """The requesting user's row for the item under consideration, correlated.

    Correlated explicitly for the reason `_container_earns_its_place` is: without it the subquery
    grows its own `FROM` and the clause stops being about *this* item.
    """
    return (
        select(models.ItemUserData.item_key)
        .where(models.ItemUserData.user_id == user.id)
        .where(models.ItemUserData.item_key == models.Item.id)
        .correlate(models.Item.__table__)
    )


def _ordered(rows: Iterable[Any]) -> list[Any]:
    """Document order, which is metadata rather than an accident of insertion: a cast list in a
    different order is a different cast list (004 spec section 3.7 rule 2)."""
    return sorted(rows, key=lambda one: one.position)


def _image(row: Any) -> ImageAssociation:
    return ImageAssociation(
        kind=ImageKind(row.image_type),
        index=row.image_index,
        source_kind=SourceKind(row.source_kind),
        relative_path=row.relative_path,
        width=row.width,
        height=row.height,
        tag=row.tag,
    )


def _metadata(row: models.Item) -> ItemMetadata:
    return ItemMetadata(
        overview=row.overview,
        tagline=row.tagline,
        original_title=row.original_title,
        production_year=row.production_year,
        premiere_date=row.premiere_date,
        runtime_ticks=row.runtime_ticks,
        official_rating=row.official_rating,
        community_rating=row.community_rating,
        provider_ids=dict(row.provider_ids or {}),
        tags=tuple(row.tags or ()),
        normalization_gain=row.normalization_gain,
        refreshed_at=row.metadata_refreshed_at,
    )


def _rolled(stored: UserItemData, rollup: tuple[int, int] | None) -> UserItemData:
    """A container's user data, restated as a rollup of its subtree.

    The favourite flag, the count and the position stay the stored row's - a favourite series is
    the user's statement about the series. `played` and the unplayed remainder are the subtree's,
    which is what the reference reports (see `UserItemData`). An empty subtree is unplayed rather
    than vacuously played: `Played: true` over nothing would mark an emptied series watched.
    """
    if rollup is None:
        return stored
    total, played = rollup
    return UserItemData(
        is_favorite=stored.is_favorite,
        played=total > 0 and played >= total,
        play_count=stored.play_count,
        playback_position_ticks=stored.playback_position_ticks,
        last_played_date=stored.last_played_date,
        unplayed_count=total - played,
        total_count=total,
    )


def _item(row: models.Item, sources: Sequence[models.ItemSource]) -> Item:
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


__all__ = [
    "ALBUM_ARTIST_CREDIT",
    "DESCENT",
    "EARN_THEIR_PLACE",
    "PERFORMER_CREDIT",
    "Ancestor",
    "ContainerAggregates",
    "HydratedItem",
    "ItemMetadata",
    "ItemQueryRepository",
    "NameLink",
    "ParentNotFoundError",
    "QueryPage",
    "UserItemData",
]
