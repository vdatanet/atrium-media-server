# SPDX-License-Identifier: GPL-3.0-or-later
"""What a client asked for, as a value.

`/Items` declares 86 query parameters and v1 answers 32 of them (spec 005 section 3.3). This
module is the shape they arrive in once `api/` has finished parsing and before `db/` has started
querying: a frozen record with no methods, no session, and no idea that HTTP or SQLite exist.

**The point of it being a value is the count.** `ItemQueryRepository.run` promises a total that is
the pre-paging count *under exactly the query's predicates* (plan section 5), and that promise is
only checkable if "the query's predicates" is a thing you can hold - one object, passed to the
predicate builder and to the counter, rather than a signature that grows a parameter every time a
filter is added and drifts between the two call sites.

**Visibility is a field, not a caller's responsibility.** `user` has no default. A query that
could be constructed without one would eventually be, in a route that forgot, and the failure
mode is a user seeing another user's library - the one bug in this feature that is not cosmetic
(plan section 9). There is no "as nobody" query, so there is no way to write one by accident.

**Two ways to say the same thing, both kept.** `filters=IsPlayed` and `isPlayed=true` are
different parameters with the same meaning, and `IsFavorite` doubles `isFavorite` likewise. The
reference accepts both; dropping either is a delta a client would find. They are separate fields
here for that reason, and section 6.2 of the plan is where they are reconciled into one predicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from atrium.domain.items import ItemType
from atrium.domain.user import User


class SortBy(StrEnum):
    """The eight keys `sortBy` accepts.

    A superset of Emby's, and closed: an unrecognised token is **dropped**, never rejected
    (behaviours section 1.12), so leniency belongs to whatever parses the parameter and not to
    this enum. A ninth member added here to be forgiving would be a key no reference server
    orders by, which is a delta in the one direction Principle I has no tolerance for.

    `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` (behaviours section 2.5)
    """

    SORT_NAME = "SortName"
    DATE_CREATED = "DateCreated"
    PREMIERE_DATE = "PremiereDate"
    PLAY_COUNT = "PlayCount"
    DATE_PLAYED = "DatePlayed"
    RANDOM = "Random"
    ALBUM_ARTIST = "AlbumArtist"
    ARTIST = "Artist"


class SortOrder(StrEnum):
    """Per key, not per request - which is why `ItemQuery.sort` pairs them."""

    ASCENDING = "Ascending"
    DESCENDING = "Descending"


class Filter(StrEnum):
    """The four `filters` tokens v1 serves (spec section 3.3, tier 1).

    `IsPlayed` and `IsUnplayed` are both present and are not redundant: absent means "either",
    which is a third state neither one expresses on its own.
    """

    IS_FAVORITE = "IsFavorite"
    IS_PLAYED = "IsPlayed"
    IS_UNPLAYED = "IsUnplayed"
    IS_RESUMABLE = "IsResumable"


@dataclass(frozen=True, slots=True)
class ItemQuery:
    """One request for items, resolved. Frozen, pure, and complete enough to count from."""

    #: Whose visibility and whose user data. No default, deliberately: see the module docstring.
    user: User

    # -- scope -----------------------------------------------------------------------------
    parent_id: str | None = None
    recursive: bool = False

    # -- what kind of thing --------------------------------------------------------------------
    include_types: frozenset[ItemType] | None = None
    exclude_types: frozenset[ItemType] | None = None

    #: `Video`, `Audio`, `Unknown` - the reference's `MediaType`, which is a string rather than an
    #: `ItemType` and does not map onto one: `Movie` and `Episode` are both `Video`.
    media_types: frozenset[str] | None = None

    # -- which specific things -----------------------------------------------------------------
    #: Tuples rather than frozensets: `ids` is the one parameter whose **order** a client can
    #: observe, because `/Items?ids=` is how a client re-fetches a list it already has.
    ids: tuple[str, ...] | None = None
    exclude_ids: tuple[str, ...] | None = None

    # -- name matching -------------------------------------------------------------------------
    search_term: str | None = None
    name_starts_with: str | None = None
    name_starts_with_or_greater: str | None = None
    name_less_than: str | None = None

    # -- related rows --------------------------------------------------------------------------
    #: `genres` matches by **name** and `genre_ids` by identifier. The reference offers both and
    #: they are not interchangeable - a name arrives from a client that never fetched the by-name
    #: row it belongs to.
    genres: tuple[str, ...] | None = None
    genre_ids: tuple[str, ...] | None = None
    studio_ids: tuple[str, ...] | None = None
    artist_ids: tuple[str, ...] | None = None
    album_artist_ids: tuple[str, ...] | None = None
    album_ids: tuple[str, ...] | None = None
    person_ids: tuple[str, ...] | None = None
    years: tuple[int, ...] | None = None

    # -- user state ----------------------------------------------------------------------------
    filters: frozenset[Filter] = frozenset()
    is_played: bool | None = None
    is_favorite: bool | None = None

    min_community_rating: float | None = None

    # -- ordering and paging -------------------------------------------------------------------
    #: Ordered pairs, not a mapping: `sortBy=SortName,DateCreated` means one key then the other,
    #: and a dict would both lose that order and silently swallow a repeated key.
    sort: tuple[tuple[SortBy, SortOrder], ...] = ()
    start_index: int = 0
    limit: int | None = None

    #: `enableTotalRecordCount`. True by default because the reference's default is true, and a
    #: client that never sends it expects a real total to size a scrollbar with (spec 3.3).
    count: bool = True

    #: The shuffle for `SortBy.RANDOM`, and **never anything a client sent**.
    #:
    #: It is a field of the query rather than an argument to the repository because a query is the
    #: whole of what produced a result: two `ItemQuery` values that compare equal must describe the
    #: same page, and a seed living outside them would break that quietly for the one ordering
    #: where it matters most. Fresh entropy per request in the server, injected by tests
    #: (plan section 6.4). It is not a parameter of the API and is never echoed.
    random_seed: int | None = None


__all__ = ["Filter", "ItemQuery", "SortBy", "SortOrder"]
