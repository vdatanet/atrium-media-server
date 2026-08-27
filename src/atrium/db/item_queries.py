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

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session as OrmSession

from atrium.db import models
from atrium.domain.items import (
    FILE_BACKED,
    MEDIA_TYPE_OF,
    Item,
    ItemType,
    MediaSource,
)
from atrium.domain.queries import Filter, ItemQuery
from atrium.domain.user import User
from atrium.library.identity import for_by_name
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind
from atrium.metadata.byname import fold_for_search
from atrium.metadata.model import PersonCredit, PersonKind

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


class ParentNotFoundError(LookupError):
    """`parentId` names an item that does not exist, or one this user may not see.

    **One exception for both**, and that is the security-relevant half. Plan section 6.13 turns it
    into a single identical `404`: a client that could tell "no such item" from "not yours" could
    enumerate another user's library one identifier at a time.
    """


@dataclass(frozen=True, slots=True)
class UserItemData:
    """The requesting user's state for one item. Always present, never null (behaviours 2.1)."""

    is_favorite: bool = False
    played: bool = False
    play_count: int = 0
    playback_position_ticks: int = 0
    last_played_date: datetime | None = None


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
class HydratedItem:
    """One item and everything a response about it needs, with no session behind it.

    A separate record rather than fields on `Item`, deliberately. `Item` is 003's model of what a
    library holds and the scanner builds one from a file; genres, credits and another user's play
    state are not properties of the file, and putting them on `Item` would give the scanner five
    fields it can never fill and a reader no way to tell "empty" from "not loaded".
    """

    item: Item
    genres: tuple[NameLink, ...] = ()
    studios: tuple[NameLink, ...] = ()
    people: tuple[PersonCredit, ...] = ()
    artists: tuple[NameLink, ...] = ()
    images: tuple[ImageAssociation, ...] = ()
    user_data: UserItemData = field(default_factory=UserItemData)

    @property
    def id(self) -> str:
        return self.item.id


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
        total = self._count(scoped) if query.count else 0

        page = scoped.order_by(models.Item.sort_name, models.Item.id).offset(query.start_index)
        if query.limit is not None:
            page = page.limit(query.limit)
        rows = list(self._session.execute(page).scalars())
        return QueryPage(items=self._hydrate(rows, query.user), total=total)

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

        Three parts, and the order they are written in is the order they exclude rows in:
        the item is not soft-deleted, its library is one this user's policy permits, and - for the
        four container types - something with a file is still visible underneath it.
        """
        return (
            (models.Item.removed_at.is_(None))
            & self._library_permitted(user)
            & self._container_earns_its_place()
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
        """
        if not rows:
            return ()
        ids = [row.id for row in rows]

        sources = self._grouped(models.ItemSource, ids)
        genres = self._grouped(models.ItemGenre, ids)
        studios = self._grouped(models.ItemStudio, ids)
        people = self._grouped(models.ItemPerson, ids)
        artists = self._grouped(models.ItemArtist, ids)
        images = self._grouped(models.ItemImage, ids)
        user_data = self._user_data(ids, user)

        return tuple(
            HydratedItem(
                item=_item(row, sources.get(row.id, [])),
                genres=tuple(
                    NameLink(name=one.name, item_id=one.genre_item_id)
                    for one in _ordered(genres.get(row.id, []))
                ),
                studios=tuple(
                    NameLink(name=one.name, item_id=one.studio_item_id)
                    for one in _ordered(studios.get(row.id, []))
                ),
                people=tuple(
                    PersonCredit(
                        name=one.name,
                        kind=PersonKind(one.person_type),
                        role=one.role,
                        sort_order=one.sort_order,
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
                    ImageAssociation(
                        kind=ImageKind(one.image_type),
                        index=one.image_index,
                        source_kind=SourceKind(one.source_kind),
                        relative_path=one.relative_path,
                        width=one.width,
                        height=one.height,
                        tag=one.tag,
                    )
                    for one in sorted(images.get(row.id, []), key=lambda one: one.image_index)
                ),
                user_data=user_data.get(row.id, UserItemData()),
            )
            for row in rows
        )

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
        clauses.append(item.type.in_(_types_of_media(query.media_types)))

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


def _types_of_media(media_types: Iterable[str]) -> list[str]:
    """`Video`, `Audio` or `Unknown` back into the item types that answer them.

    There is no `media_type` column: it is a property of the *type*, measured once into
    `MEDIA_TYPE_OF`. Matching case-insensitively for the same reason `known_tokens` does - a
    parameter whose name matches case-insensitively while its values did not would be a
    distinction no client could have learned.
    """
    wanted = {one.casefold() for one in media_types}
    return [kind.value for kind, media in MEDIA_TYPE_OF.items() if media.casefold() in wanted]


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
    "HydratedItem",
    "ItemQueryRepository",
    "NameLink",
    "ParentNotFoundError",
    "QueryPage",
    "UserItemData",
]
