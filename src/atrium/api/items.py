# SPDX-License-Identifier: GPL-3.0-or-later
"""`GET /Items` and `GET /Items/{itemId}`: the endpoint everything else is built on.

What is left at route level is exactly what the plan promised would be left (plan section 1):
parameter parsing into an `ItemQuery`, the choice of response shape, and the refusals. The
repository owns the SQL, the builder owns the body, and `compat/` owns the three wire fights -
this module contains none of them.

**The parameters are the pinned document's, spelling and tier alike** (spec section 3.3).
Tier 1 and 2 bind below; a tier 3 parameter never reaches a signature, so it lands in the
ignored-parameter recorder by construction - `compat.query_params` counts what no route
declared. Enum-valued parameters drop unrecognised tokens and keep the rest (behaviours
section 1.12); a value that cannot parse as its declared *type* - `limit=abc`, a malformed
identifier - is the validation `400` (behaviours section 1.11).

**One subtlety in `includeItemTypes` the drop rule does not cover**: `Playlist` is a real
`BaseItemKind` this version cannot produce, and `Nonsense` is not a kind at all. The reference
filters by the first (zero rows here) and ignores the second (the filter vanishes). Telling them
apart takes the reference's own vocabulary, `BASE_ITEM_KINDS` below `[spec: BaseItemKind]` - a
kind v1 cannot produce keeps the filter and matches nothing, an unknown token is dropped and
recorded.

**The identical `404`** (plan section 6.13): `/Items/{itemId}` resolves the id through the same
pipeline as every list - one `ids=` query under the same visibility predicate - so "no such
item" and "not yours" are one empty page and one `NotFoundError`, byte-identical on the wire by
construction. An id that does not parse as an identifier never reaches the query: `WireGuid`
refuses it into the validation `400`, which is the other measured refusal (spec section 3.5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import RequestValidationError

from atrium.api.deps import get_sessions, get_state, require_administrator, require_user
from atrium.api.item_dto import GATED, BuildContext, LibraryContext, Width, build_dto, build_dtos
from atrium.api.item_models import BaseItemDto, BaseItemDtoQueryResult
from atrium.compat.errors import (
    DeletionNotPermittedError,
    EmptyIdentifierError,
    ForbiddenError,
    ItemUpdateError,
    MediaDeletionRefusedError,
    MediaUpdateRefusedError,
    NotFoundError,
)
from atrium.compat.guids import EMPTY, WireGuid, normalise, require_canonical
from atrium.compat.model import AtriumModel
from atrium.compat.query_params import IgnoredParameters, known_tokens
from atrium.db.engine import session_scope
from atrium.db.item_queries import (
    ContainerAggregates,
    HydratedItem,
    ItemQueryRepository,
    ParentNotFoundError,
)
from atrium.db.repositories import LibraryRepository, PlaylistRepository, UserRepository
from atrium.domain.items import ItemType
from atrium.domain.playlists import may_delete
from atrium.domain.queries import Filter, ItemQuery, SortBy, SortOrder
from atrium.domain.user import User

router = APIRouter()

#: The reference's item-kind vocabulary, verbatim `[spec: BaseItemKind]`. Membership decides
#: whether an unmatched `includeItemTypes` token narrows to nothing (a real kind v1 cannot
#: produce) or vanishes (not a kind at all) - see the module docstring.
BASE_ITEM_KINDS: frozenset[str] = frozenset(
    {
        "AggregateFolder",
        "Audio",
        "AudioBook",
        "BasePluginFolder",
        "Book",
        "BoxSet",
        "Channel",
        "ChannelFolderItem",
        "CollectionFolder",
        "Episode",
        "Folder",
        "Genre",
        "ManualPlaylistsFolder",
        "Movie",
        "LiveTvChannel",
        "LiveTvProgram",
        "MusicAlbum",
        "MusicArtist",
        "MusicGenre",
        "MusicVideo",
        "Person",
        "Photo",
        "PhotoAlbum",
        "Playlist",
        "PlaylistsFolder",
        "Program",
        "Recording",
        "Season",
        "Series",
        "Studio",
        "Trailer",
        "TvChannel",
        "TvProgram",
        "UserRootFolder",
        "UserView",
        "Video",
        "Year",
    }
)

#: `fields` tokens this version resolves, lowercased for the case-insensitive match every value
#: gets (behaviours section 1.12). The registry's gated map is the authority on which token
#: gates which property; this is its token set, inverted for lookup.
_FIELD_TOKENS: Mapping[str, str] = {token.lower(): token for token in set(GATED.values())}

#: The gated names whose emitters read `ctx.aggregates` - the batch pays for the subtree
#: queries only when one of these was actually asked for (plan section 6.5).
_AGGREGATE_FIELDS = frozenset(
    {"ChildCount", "RecursiveItemCount", "CumulativeRunTimeTicks", "DateLastMediaAdded"}
)

_KINDS_BY_FOLD = {member.value.lower(): member for member in ItemType}
_REFERENCE_KINDS_BY_FOLD = {kind.lower() for kind in BASE_ITEM_KINDS}


# ------------------------------------------------------------------------------------------------
# Parameter parsing
# ------------------------------------------------------------------------------------------------


def split_csv(raw: str | None) -> list[str]:
    """The reference's list syntax: one query value, comma-separated, blanks dropped."""
    if raw is None:
        return []
    return [token.strip() for token in raw.split(",") if token.strip()]


def _invalid(parameter: str, value: str) -> RequestValidationError:
    """A value that cannot parse as its declared type, in the binder's own error shape, so the
    global handler answers the measured `400` with the parameter's declared spelling as the key."""
    return RequestValidationError(
        [{"loc": ("query", parameter), "msg": "value is not valid", "input": value}]
    )


def parse_guid_list(raw: str | None, parameter: str) -> tuple[str, ...] | None:
    """Identifiers, canonicalised. A malformed one is a type failure, not a droppable token
    (behaviours section 1.12's line), measured on the item route and reproduced here."""
    tokens = split_csv(raw)
    if not tokens:
        return None
    canonical: list[str] = []
    for token in tokens:
        try:
            canonical.append(require_canonical(normalise(token)))
        except ValueError as refused:
            raise _invalid(parameter, token) from refused
    return tuple(canonical)


def parse_int_list(raw: str | None, parameter: str) -> tuple[int, ...] | None:
    tokens = split_csv(raw)
    if not tokens:
        return None
    numbers: list[int] = []
    for token in tokens:
        try:
            numbers.append(int(token))
        except ValueError as refused:
            raise _invalid(parameter, token) from refused
    return tuple(numbers)


def parse_kinds(
    raw: str | None, parameter: str, ignored: IgnoredParameters, route: str
) -> frozenset[ItemType] | None:
    """`includeItemTypes`/`excludeItemTypes`: three answers per token, not two.

    A type of this domain filters; a `BaseItemKind` this version cannot produce keeps the filter
    and can match nothing - `frozenset()` means "asked, and nothing qualifies" (the repository's
    empty-versus-None contract from T6); a token that is no kind at all drops and is recorded.
    """
    tokens = split_csv(raw)
    if not tokens:
        return None
    kept: set[ItemType] = set()
    askable = False
    for token in tokens:
        member = _KINDS_BY_FOLD.get(token.lower())
        if member is not None:
            kept.add(member)
            askable = True
        elif token.lower() in _REFERENCE_KINDS_BY_FOLD:
            askable = True
        else:
            ignored.record(route, f"{parameter}={token}")
    if kept:
        return frozenset(kept)
    return frozenset() if askable else None


def parse_sort(
    sort_by: str | None, sort_order: str | None, ignored: IgnoredParameters, route: str
) -> tuple[tuple[SortBy, SortOrder], ...]:
    """The comma list zipped with its orders; a missing order is `Ascending` (plan section 6.3)."""
    keys = known_tokens(
        split_csv(sort_by), SortBy, route=route, parameter="sortBy", ignored=ignored
    )
    orders = known_tokens(
        split_csv(sort_order), SortOrder, route=route, parameter="sortOrder", ignored=ignored
    )
    return tuple(
        (key, orders[position] if position < len(orders) else SortOrder.ASCENDING)
        for position, key in enumerate(keys)
    )


def parse_fields(raw: str | None, ignored: IgnoredParameters, route: str) -> frozenset[str]:
    """The `ItemFields` tokens v1 resolves; anything else - a token of the reference's enum this
    version does not emit included - is dropped and recorded, which is the same measurable trail
    the tier 3 parameters leave (spec section 3.3)."""
    kept: set[str] = set()
    for token in split_csv(raw):
        canonical = _FIELD_TOKENS.get(token.lower())
        if canonical is not None:
            kept.add(canonical)
        else:
            ignored.record(route, f"fields={token}")
    return frozenset(kept)


def recorder(request: Request) -> IgnoredParameters:
    ignored: IgnoredParameters = request.app.state.ignored_parameters
    return ignored


# ------------------------------------------------------------------------------------------------
# Shared resolution
# ------------------------------------------------------------------------------------------------


def effective_user(users: UserRepository, caller: User, user_id: str | None) -> User:
    """Whose visibility and user data apply (spec section 3.3, tier 1 `userId`).

    A non-administrator naming anybody else gets the `403` through the 002 seam, and it carries
    the reference's own 25 bytes: measured on the same parameter of the same reference controller
    one route away, and corrected here rather than only on 009's routes (009 spec section 3.7,
    AC-19) `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`. Plan
    section 7 called that shape unmeasured and flagged it for the differential; it is measured
    now, and it was empty here for a whole feature.

    **An administrator naming nobody that exists gets the problem-details `404`, and that case is
    measured at last** - 007 T10's Done note left it chosen-but-unmeasured, and 009 T8 asked it on
    the one route where the parameter creates something: the reference answers **`200`** and builds
    a playlist owned by a user that does not exist
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`. Nothing can then
    reach that playlist - every rule in 009 spec section 3.7 compares against an owner or a share -
    so the `404` stands as a divergence with an argument rather than as a guess, and behaviours
    section 3.19 carries it.
    """
    if user_id is None or user_id == caller.id:
        return caller
    if not caller.is_administrator:
        raise ForbiddenError("userId names another user and the caller is no administrator")
    target = users.by_id(user_id)
    if target is None:
        raise NotFoundError
    return target


def library_context(libraries: LibraryRepository) -> dict[str, LibraryContext]:
    """The context the folder rows and `Path` emitters read. One small query; a server has tens
    of libraries at most (plan section 10 argued the same about `/UserViews`)."""
    return {
        library.id: LibraryContext(
            collection_type=library.collection_type.value, roots=tuple(library.roots)
        )
        for library in libraries.all()
    }


def aggregates_context(
    repository: ItemQueryRepository,
    items: Sequence[HydratedItem],
    target: User,
    fields: frozenset[str],
    width: Width,
) -> Mapping[str, ContainerAggregates]:
    """The subtree numbers, fetched only when an emitter will read them."""
    if width is not Width.FULL and not (fields & _AGGREGATE_FIELDS):
        return {}
    return repository.aggregates_for([one.id for one in items], target)


# ------------------------------------------------------------------------------------------------
# The routes
# ------------------------------------------------------------------------------------------------


@router.get("/Items")
async def items(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    userId: WireGuid | None = None,
    parentId: WireGuid | None = None,
    recursive: bool = False,
    startIndex: int = 0,
    limit: int | None = None,
    sortBy: str | None = None,
    sortOrder: str | None = None,
    fields: str | None = None,
    includeItemTypes: str | None = None,
    excludeItemTypes: str | None = None,
    excludeItemIds: str | None = None,
    mediaTypes: str | None = None,
    searchTerm: str | None = None,
    ids: str | None = None,
    genres: str | None = None,
    genreIds: str | None = None,
    studioIds: str | None = None,
    artistIds: str | None = None,
    albumArtistIds: str | None = None,
    albumIds: str | None = None,
    personIds: str | None = None,
    years: str | None = None,
    nameStartsWith: str | None = None,
    nameStartsWithOrGreater: str | None = None,
    nameLessThan: str | None = None,
    minCommunityRating: float | None = None,
    filters: str | None = None,
    isPlayed: bool | None = None,
    isFavorite: bool | None = None,
    enableUserData: bool = True,
    enableImages: bool = True,
    imageTypeLimit: int | None = None,
    enableImageTypes: str | None = None,
    enableTotalRecordCount: bool = True,
) -> BaseItemDtoQueryResult:
    """`GetItems` `[spec: GetItems]`: tier 1 and 2 bound, tier 3 recorded, four shapes away."""
    route = "/Items"
    ignored = recorder(request)
    state = get_state(request)

    query_sort = parse_sort(sortBy, sortOrder, ignored, route)
    asked_fields = parse_fields(fields, ignored, route)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        query = ItemQuery(
            user=target,
            parent_id=parentId,
            recursive=recursive,
            include_types=parse_kinds(includeItemTypes, "includeItemTypes", ignored, route),
            exclude_types=parse_kinds(excludeItemTypes, "excludeItemTypes", ignored, route),
            media_types=frozenset(split_csv(mediaTypes)) or None,
            ids=parse_guid_list(ids, "ids"),
            exclude_ids=parse_guid_list(excludeItemIds, "excludeItemIds"),
            search_term=searchTerm,
            name_starts_with=nameStartsWith,
            name_starts_with_or_greater=nameStartsWithOrGreater,
            name_less_than=nameLessThan,
            genres=tuple(split_csv(genres)) or None,
            genre_ids=parse_guid_list(genreIds, "genreIds"),
            studio_ids=parse_guid_list(studioIds, "studioIds"),
            artist_ids=parse_guid_list(artistIds, "artistIds"),
            album_artist_ids=parse_guid_list(albumArtistIds, "albumArtistIds"),
            album_ids=parse_guid_list(albumIds, "albumIds"),
            person_ids=parse_guid_list(personIds, "personIds"),
            years=parse_int_list(years, "years"),
            filters=frozenset(
                known_tokens(
                    split_csv(filters), Filter, route=route, parameter="filters", ignored=ignored
                )
            ),
            is_played=isPlayed,
            is_favorite=isFavorite,
            min_community_rating=minCommunityRating,
            sort=query_sort,
            start_index=startIndex,
            limit=limit,
            count=enableTotalRecordCount,
        )
        repository = ItemQueryRepository(opened)
        try:
            page = repository.run(query)
        except ParentNotFoundError as refused:
            # One exception for "no such item" and "not yours", one 404 for both (plan 6.13).
            raise NotFoundError from refused

        context = BuildContext(
            server_id=state.server_id,
            width=Width.LIST_ROW,
            fields=asked_fields,
            enable_user_data=enableUserData,
            enable_images=enableImages,
            image_type_limit=imageTypeLimit,
            enable_image_types=frozenset(split_csv(enableImageTypes)) or None,
            libraries=library_context(LibraryRepository(opened)),
            aggregates=aggregates_context(
                repository, page.items, target, asked_fields, Width.LIST_ROW
            ),
        )
        built = build_dtos(page.items, context)

    return BaseItemDtoQueryResult(
        items=built, total_record_count=page.total, start_index=startIndex
    )


@router.get("/Items/{itemId}")
async def item(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,
    userId: WireGuid | None = None,
) -> BaseItemDto:
    """`GetItem` `[spec: GetItem]`: one item, everything, unasked (spec section 3.2)."""
    state = get_state(request)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        repository = ItemQueryRepository(opened)
        page = repository.run(ItemQuery(user=target, ids=(itemId,), limit=1, count=False))
        if not page.items:
            # The identical 404: an unknown id and an invisible one are the same empty page,
            # so the two bodies cannot differ even by accident (AC-8).
            raise NotFoundError
        found: HydratedItem = page.items[0]
        context = BuildContext(
            server_id=state.server_id,
            width=Width.FULL,
            libraries=library_context(LibraryRepository(opened)),
            aggregates=repository.aggregates_for([found.id], target),
        )
        built = build_dto(found, context)
    return built


@router.delete("/Items/{itemId}", status_code=204)
async def delete_item(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    itemId: WireGuid,
) -> Response:
    """`DeleteItem` `[spec: DeleteItem]`: the route 009 owns half of (009 spec section 3.6).

    **Four answers, and three of them are the reference's.** A playlist this caller may delete -
    its owner, or **any** administrator - goes, with its entries and its shares, and the answer is
    `204` with no body and no content type. A playlist they may not delete is `401` carrying the
    JSON-encoded bare string `"Unauthorized access"`. An identifier that addresses nothing this
    caller can reach is the problem-details `404`, and an all-zeros one is the bare-text `400`
    every route that resolves an identifier answers (T10). All four measured
    `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`.

    **The fourth is ours, and it is the whole of what this route refuses**: anything that is not a
    playlist answers `403` (behaviours section 4.3). The reference deletes a film and its file for
    an entitled caller; v1 has no trash to put it in, so 009 claims the playlist half of this route
    and refuses the rest. That includes the by-name rows a deletion would take no file from - a
    genre this server rebuilds on the next scan is Principle VI's plausible-looking stub, not a
    deletion.

    **The order is the reference's, and it is not the order every other 009 route uses.** The
    playlist lookup applies **no visibility test**: measured, a caller who is answered the read
    route's twenty bytes for a private playlist is answered `401` here, so on this one route a
    `404` really does mean "no such item" and the refusal discloses that a playlist exists
    `[source: Jellyfin.Api/Controllers/LibraryController.cs:374-383 @ v10.11.11]`. Media is the
    other way round: an item in a library this caller cannot open is `404` before any permission
    is consulted, which is what `ItemQueryRepository` already answers.

    **No `userId`.** The reference's action takes the caller's own identity and nothing else
    `[spec: DeleteItem]`, so there is no `effective_user` call and no way to delete on somebody's
    behalf.
    """
    if itemId == EMPTY:
        raise EmptyIdentifierError("an identifier of all zeros names no item")

    with session_scope(get_sessions(request)) as opened:
        queries = ItemQueryRepository(opened)
        playlists = PlaylistRepository(opened, queries)

        playlist = playlists.by_id_for_deletion(itemId)
        if playlist is not None:
            if not may_delete(playlist, caller):
                raise DeletionNotPermittedError("this caller may not delete the playlist")
            playlists.delete(playlist.id)
            return Response(status_code=204)

        page = queries.run(ItemQuery(user=caller, ids=(itemId,), limit=1, count=False))
        if not page.items:
            raise NotFoundError
        raise MediaDeletionRefusedError("v1 deletes no item whose removal could take a file")


class UpdateItemDto(AtriumModel):
    """The rename body: a whole `BaseItemDto` on the reference `[spec: UpdateItem]`, four of its
    properties here.

    **The client fetches the item, changes `Name` and posts it back**
    `[client-contract: 2026-08-29, section 10]`, so the body that arrives carries every property
    the read route emitted - thirty-nine of them on a playlist, measured. `extra="ignore"` takes
    the other thirty-five; these four are the ones the route reads or refuses.

    **Three of them are declared `| None` and are still required**, which is the shape of what
    was measured rather than a looseness: the reference refuses a body that omits `Genres`, `Tags`
    or `ProviderIds` **and** one that sends any of the three as `null`, identically, with the
    controller's 25 bytes at `400` `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11,
    2026-09-01]`. Declaring them required *here* would answer the framework's validation shape -
    problem details, keyed on a property - which is a different refusal from the measured one, so
    the check is the route's and the model stays permissive (`ItemUpdateError`).

    `Name` is the same story for the opposite reason: absent or `null`, the reference answers
    `204` and erases the name, which this server refuses instead (behaviours section 3.21).
    """

    #: The reference's own parameter name for this body, which its refusals spell out:
    #: `{"request": ["The request field is required."]}` beside the binder's own key, measured on
    #: a body that is not JSON at all `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11,
    #: 2026-09-01]`. It is the **route parameter** below that carries it onto the wire, not this
    #: class; the note is here because that is where a reader will look for it.
    name: str | None = None
    genres: list[str] | None = None
    tags: list[str] | None = None
    provider_ids: dict[str, str | None] | None = None


@router.post("/Items/{itemId}", status_code=204)
async def update_item(
    http: Request,
    caller: Annotated[User, Depends(require_administrator)],
    itemId: WireGuid,
    request: UpdateItemDto,
) -> Response:
    """`UpdateItem` `[spec: UpdateItem]`: the rename the music client calls (009 spec section 3.8).

    **It is administrator-only, and that is the scope finding rather than a detail.** The reference
    declares the whole controller elevated, so a playlist's own owner is refused the rename of
    their own playlist unless they are an administrator - `403`, no body, no content type, an
    authorization policy's refusal and never a controller's
    `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`
    `[source: Jellyfin.Api/Controllers/ItemUpdateController.cs @ v10.11.11]`. The operation was
    brought into the surface for the music client and refuses that client's own users; the rename
    that would work for an owner is `POST /Playlists/{playlistId}`, which no analysed client calls
    and which Principle VI therefore keeps out (behaviours section 5).

    **The refusal comes first, and `require_administrator` above is where the ordering lives**: a
    non-administrator meets that `403` for a malformed identifier and for one naming nothing, so
    nothing about the item leaks to a caller who may not touch it.

    **What the route applies is `Name` and nothing else, and the reference applies seven more.**
    Measured on a whole posted body, `Overview`, `ForcedSortName`, `OfficialRating`, `CustomRating`,
    `ProductionYear`, `Genres` and `Tags` all take the value they were sent, where `Path` and
    `IsFolder` are computed and ignored. v1 has a consumer for none of that and could not honour it
    anyway - 004 T10 measured the scan and the refresh fighting over `Item.name` - so the narrowing
    is a recorded gap (behaviours section 5) rather than an omission.

    **The three properties a body may not omit are the reference's**, and they are checked here
    rather than declared on the model so that the refusal is the measured 25 bytes.

    Four identifier classes, all measured on this method rather than inherited from the `DELETE`
    that shares its path: plain, dashed, braced and upper-case spellings all address the item, an
    identifier that is not one is the binder's validation `400` keyed `itemId`, all zeros is the
    bare-text `400`, and a well-formed unknown one is the problem-details `404`.

    **The body parameter is called `request`** because the reference's action parameter is, and a
    refusal of a required body names it: `The request field is required.` (behaviours section
    1.11, 007 T8). The ASGI request takes the other name for once.
    """
    if itemId == EMPTY:
        raise EmptyIdentifierError("an identifier of all zeros names no item")

    with session_scope(get_sessions(http)) as opened:
        queries = ItemQueryRepository(opened)
        playlists = PlaylistRepository(opened, queries)

        # `by_id` hands an administrator any playlist, which is the hole T12 relies on and the
        # reason this route needs no second read: every caller who reaches this line is one.
        playlist = playlists.by_id(itemId, caller)
        if playlist is None:
            page = queries.run(ItemQuery(user=caller, ids=(itemId,), limit=1, count=False))
            if not page.items:
                raise NotFoundError
            raise MediaUpdateRefusedError("v1 updates no item that is not a playlist")

        if request.genres is None or request.tags is None or request.provider_ids is None:
            raise ItemUpdateError("the body omits a property the reference requires")
        if request.name is None:
            raise ItemUpdateError("the body carries no name to apply")

        playlists.rename(playlist.id, request.name)

    return Response(status_code=204)


# ------------------------------------------------------------------------------------------------
# The by-name family (plan section 6.7): five routes, one shape
# ------------------------------------------------------------------------------------------------


def by_name_envelope(
    request: Request,
    caller: User,
    *,
    route: str,
    kind: ItemType,
    credit: str | None = None,
    omit: frozenset[str] = frozenset(),
    user_id: str | None,
    parent_id: str | None,
    start_index: int,
    limit: int | None,
    sort_by: str | None,
    sort_order: str | None,
    search_term: str | None,
) -> BaseItemDtoQueryResult:
    """One implementation for `/Artists`, `/Artists/AlbumArtists`, `/Genres`, `/MusicGenres`
    and `/Years` - the same pipeline with the kind pinned, the credit read where the route says,
    and the route's measured omissions applied (spec section 3.9).

    **The count is always true**, with `limit` and without: the reference's no-`limit` answers
    are the recorded defect of behaviours section 3.1 - `0` beside a non-empty list on most of
    the family, and on `/Years` a number that is neither zero nor the row count.
    """
    ignored = recorder(request)
    state = get_state(request)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, user_id)
        repository = ItemQueryRepository(opened)
        query = ItemQuery(
            user=target,
            parent_id=parent_id,
            search_term=search_term,
            sort=parse_sort(sort_by, sort_order, ignored, route),
            start_index=start_index,
            limit=limit,
        )
        try:
            page = repository.run_by_name(kind, query, credit=credit)
        except ParentNotFoundError as refused:
            raise NotFoundError from refused

        context = BuildContext(
            server_id=state.server_id,
            width=Width.LIST_ROW,
            omit=omit,
            libraries=library_context(LibraryRepository(opened)),
        )
        built = build_dtos(page.items, context)

    return BaseItemDtoQueryResult(
        items=built, total_record_count=page.total, start_index=start_index
    )


__all__ = [
    "BASE_ITEM_KINDS",
    "UpdateItemDto",
    "aggregates_context",
    "by_name_envelope",
    "delete_item",
    "effective_user",
    "library_context",
    "parse_fields",
    "parse_guid_list",
    "parse_int_list",
    "parse_kinds",
    "parse_sort",
    "recorder",
    "router",
    "split_csv",
    "update_item",
]
