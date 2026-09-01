# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `PlaylistsController`: creating a playlist, reading it, and writing its entries.

## `POST /Playlists` - two refusals that are not the same shape, and then four

The route's error table is the reason this module has a docstring at all: one request path
produces refusals from three different layers, and a client sees the difference as bytes.

* **A body that omits `Name`** is `400` in the validation shape, keyed **`"$"`** - the reference's
  deserialiser refusing the whole document before any property is looked at, with a sentence that
  names the type it was building. 009 plan section 6.1 said the map is *"keyed on the property"*;
  it is not, and the property key belongs to the next row.
* **A body whose `Name` is `null`** is a *different* `400`, keyed **`"Name"`**, reading
  `The Name field is required.` The document deserialised and the property's own validator
  refused it. Nothing in this project had asked for the two to be told apart.
* **A `MediaType` no member matches** is `400` keyed `"$"` again, and the byte position its
  sentence carries is the offset **inside the quoted token** rather than into the request - `3`
  for a one-character value where an eight-character one gives `10` - which is what makes it
  reproducible where section 1.11's parser message is not.
* **An `Ids` or `UserId` entry that is not an identifier** is `400` keyed `""` with the fixed
  `The supplied value is invalid.`, which is the shape 007 already measured.
* **An id in `Ids` that resolves to nothing, before any id that does**, is the *third* shape:
  `text/plain`, the fixed 25 bytes. The reference walks the list to infer a media type when the
  request names none and throws on the first id it cannot resolve, stopping as soon as one
  resolves - so the same two ids in the other order answer `200`.
* **A `UserId` naming another user, from a non-administrator**, is `403` with those same 25 bytes:
  the reference routes this parameter through the helper that refuses on its write routes, which
  is `effective_user` here (009 spec section 3.7, AC-19).

`[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`
`[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`

**And none of them is what a request carrying no name at all gets.** The four parameters may be
sent as **query** rather than as body - the query wins, and a request with only `?name=` and no
body at all creates a playlist - so "no name" is a property of the merged pair rather than of
either. The reference answers that request with **`500`**; Atrium answers `400` in the same
`text/plain` shape and creates nothing, which is behaviours section 3.19 and the same divergence
section 3.15 makes one route away.

**An empty or blank `Name` creates a playlist** and is stored as sent. There is no validation on
the name anywhere: the specification asserted a `400` here until the gate measured it (009 spec
section 3.2, AC-2).

**The media type is decided once, at creation.** The body's value outranks everything; failing
that, the first id in the list that resolves settles it; failing that, `Audio`. It is then stored
and never revised - a playlist created empty answers `Audio` after a film is added to it - which
is why it is a column rather than a lookup (009 plan section 4.2).

## The two entry-writing routes - one identifier list, and what it is allowed to name

**Every container expands, and "container" is a predicate rather than a list** - `_Expander` below
carries the width of that and how it was measured. An unknown id is skipped here in every
position, where creation refuses one that reaches it before the media type has settled; a
malformed one is dropped by the binder; and the all-zeros identifier is refused by both routes
wherever it sits. Three classes of identifier, three different answers, measured side by side
`[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`.

**Both routes refuse in two shapes, in this order.** A playlist this caller cannot see is the read
route's twenty bytes - so a write cannot be used to learn that a private playlist exists - and a
caller who may read it and may not edit it is `403` with **no body and no content type**, which is
the other of the two `403`s this feature ships (`EmptyForbiddenError`).

## `Move` - one route, three bindings, and two refusals the reference does not make

The move is the one piece of arithmetic this feature cannot simplify, and it lives in
`domain/playlists.py` rather than here: this route decides *who* and *what*, and the domain
decides *where*. What is local to the route is that its three path segments bind three different
ways on the reference - the playlist id through the framework's parser, the entry id as text
matched against the 32-hex spelling, the index as an integer - so a dashed playlist id addresses
the playlist and a dashed **entry** id addresses nothing
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`.

See specs/009-playlists/spec.md sections 3.2, 3.3, 3.4 and 3.5, and plan sections 6.1, 6.2
and 6.4.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, ClassVar, Literal

from fastapi import APIRouter, Depends, Request, Response

from atrium.api.deps import get_sessions, get_state, require_user
from atrium.api.item_dto import BuildContext, Width, build_dtos
from atrium.api.item_models import BaseItemDtoQueryResult
from atrium.api.items import (
    aggregates_context,
    effective_user,
    library_context,
    parse_fields,
    recorder,
    split_csv,
)
from atrium.compat.errors import (
    EmptyForbiddenError,
    EmptyIdentifierError,
    PlaylistCreationError,
    PlaylistMoveError,
    PlaylistNotFoundError,
)
from atrium.compat.guids import CANONICAL, WireGuid, new_id, normalise
from atrium.compat.model import AtriumModel
from atrium.db.engine import session_scope
from atrium.db.item_queries import HydratedItem, ItemQueryRepository
from atrium.db.repositories import LibraryRepository, PlaylistRepository, UserRepository
from atrium.domain.items import FILE_BACKED, MEDIA_TYPE_OF, ItemType
from atrium.domain.playlists import (
    MoveIndexOutOfRangeError,
    Playlist,
    Share,
    may_edit,
    may_read,
)
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

router = APIRouter(tags=["Playlists"])

ROUTE = "/Playlists"
ITEMS_ROUTE = "/Playlists/{playlistId}/Items"
MOVE_ROUTE = "/Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}"

#: The reference's `MediaType` vocabulary, verbatim `[spec: MediaType]`. Five values, and the two
#: this server can store are a subset of them: a playlist built from a directory answers `Unknown`
#: and Atrium builds none (009 spec section 4). The set is here rather than in the domain because
#: it is the *wire* vocabulary this one body binds against, not a fact about any item.
MEDIA_TYPES = ("Unknown", "Video", "Audio", "Photo", "Book")

MediaTypeToken = Literal["Unknown", "Video", "Audio", "Photo", "Book"]


class PlaylistUserPermissions(AtriumModel):
    """One share, as the create body carries it `[spec: PlaylistUserPermissions]`.

    This is the whole of how a share is set in v1: the sharing routes are out of scope (009 spec
    section 2), and the create body reaches the same table - which is what puts spec section 3.7's
    second and third classes of caller in scope at all.
    """

    user_id: WireGuid | None = None
    can_edit: bool = False


class CreatePlaylistDto(AtriumModel):
    """The create body `[spec: CreatePlaylistDto]`, with the one property that is required.

    **`Name` is required and the other five are not**, which is measured rather than read off the
    schema: the document declares no `required` list at all, and the reference refuses a body
    without `Name` and accepts one whose `Name` is `""`
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.

    `ids` and `user_id` are typed as identifiers because the reference refuses a malformed one
    through its binder - `{"": ["The supplied value is invalid."]}`, measured on both - where an
    untyped field would have let it reach the id walk and answer the wrong shape.
    """

    #: The two names the reference's own refusals spell out; compat/model.py says why they are
    #: wire facts rather than borrowed code, and compat/errors.py is what reads them.
    WIRE_TYPE: ClassVar[str] = "Jellyfin.Api.Models.PlaylistDtos.CreatePlaylistDto"
    WIRE_ENUM_TYPES: ClassVar[dict[str, str]] = {"MediaType": "Jellyfin.Data.Enums.MediaType"}

    name: str
    ids: list[WireGuid] = []  # noqa: RUF012 - pydantic copies a default per instance
    user_id: WireGuid | None = None
    media_type: MediaTypeToken | None = None
    users: list[PlaylistUserPermissions] = []  # noqa: RUF012
    is_public: bool = False


class PlaylistCreationResult(AtriumModel):
    """`{"Id": "<32 hex>"}` and nothing else `[spec: PlaylistCreationResult]`."""

    id: str


def _media_type(query: str | None, body: CreatePlaylistDto | None, request: Request) -> str | None:
    """The media type the request asked for, or `None` to let the id walk decide.

    **The same value is refused two ways on this one route**, which is behaviours section 1.12
    seen from both sides at once: `Nonsense` in the *body* is the validation `400` above, and
    `mediaType=Nonsense` in the **query** is dropped - the playlist is created and answers the
    inferred value `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
    So the query token is recorded like any other ignored one and the request continues.
    """
    if query is not None:
        token = query.strip()
        for member in MEDIA_TYPES:
            if token.lower() == member.lower():
                return member
        if token:
            recorder(request).record(ROUTE, f"mediaType={token}")
    return body.media_type if body is not None else None


@router.post(ROUTE)
async def create_playlist(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    name: str | None = None,
    ids: str | None = None,
    userId: WireGuid | None = None,  # noqa: N803 - the reference's spellings, throughout
    mediaType: str | None = None,  # noqa: N803
    createPlaylistDto: CreatePlaylistDto | None = None,  # noqa: N803
) -> PlaylistCreationResult:
    """`CreatePlaylist` `[spec: CreatePlaylist]`.

    **The four query parameters are declared because the reference honours them**, deprecated and
    all: `?name=` with no body at all creates a playlist, and a query value beats the body's on
    the same property `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
    A route that required a body would refuse a request the reference serves, which is the
    difference Principle I forbids - the age of a parameter is not a reason a client cannot send
    it.

    The order below is 009 plan section 6.1's, and the first step is not here: a body that fails
    to bind never reaches this function, and the query does not rescue it - measured, `?name=`
    beside a body with no `Name` is still the deserialiser's `400`.
    """
    body = createPlaylistDto
    asked_name = name if name is not None else (body.name if body is not None else None)
    if asked_name is None:
        # The reference crashes here; behaviours section 3.19 is the argument for refusing.
        raise PlaylistCreationError("neither the query nor the body carries a Name")

    asked_ids = split_csv(ids) if ids is not None else (list(body.ids) if body is not None else [])
    asked_owner = userId if userId is not None else (body.user_id if body is not None else None)
    asked_type = _media_type(mediaType, body, request)

    with session_scope(get_sessions(request)) as opened:
        owner = effective_user(UserRepository(opened), caller, asked_owner)
        queries = ItemQueryRepository(opened)
        playlists = PlaylistRepository(opened, queries)
        entries, media_type = _walk(_Expander(queries, playlists), owner, asked_ids, asked_type)
        playlist = Playlist(
            id=new_id(),
            name=asked_name,
            owner_user_id=owner.id,
            is_public=body.is_public if body is not None else False,
            media_type=media_type,
            shares=_shares(body),
        )
        playlists.create(playlist, entries)
    return PlaylistCreationResult(id=playlist.id)


def _shares(body: CreatePlaylistDto | None) -> tuple[Share, ...]:
    """The body's `Users`, which is the only way v1 sets one (009 spec section 3.2)."""
    if body is None:
        return ()
    return tuple(
        Share(user_id=one.user_id, can_edit=one.can_edit)
        for one in body.users
        if one.user_id is not None
    )


#: `Guid.Empty`. Not an unknown identifier and not a malformed one: a third class, refused by
#: both write routes and by creation wherever it appears (`EmptyIdentifierError`).
EMPTY_ID = "0" * 32

#: The value that means "this item does not answer the question", so the next one is asked.
UNKNOWN_MEDIA_TYPE = "Unknown"

#: What a folder is expanded into: the two media types a playlist entry can carry. A container
#: among the descendants answers `Unknown` and is therefore not one, which is the same filter the
#: reference states on its own expansion query
#: `[source: MediaBrowser.Controller/Playlists/Playlist.cs:217-229 @ v10.11.11]`.
PLAYABLE_MEDIA_TYPES = frozenset({"Audio", "Video"})

#: The media type four containers settle **by their kind**, before anything looks at what they
#: hold. Measured through the answer rather than read off the map: a music container creates an
#: `Audio` playlist even when the walk would have gone on to a film
#: `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`
#: `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:95-114 @ v10.11.11]`.
#: Every other container answers from its first playable descendant, which is `_settles` below.
CONTAINER_MEDIA_TYPE: Mapping[ItemType, str] = {
    ItemType.MUSIC_ARTIST: "Audio",
    ItemType.MUSIC_ALBUM: "Audio",
    ItemType.MUSIC_GENRE: "Audio",
    ItemType.GENRE: "Video",
}


@dataclass(frozen=True, slots=True)
class _Expander:
    """Plan section 6.2's one function, serving creation and addition alike.

    **"Is this a container" is a predicate, not a list of five types.** `FILE_BACKED` is the three
    types a *file* produces, and everything else this server can name is something a client can
    ask to add whole: measured, an album, an artist, a series, a season, a collection, a plain
    folder, **the library root itself** and **another playlist** all expand, and the container is
    never an entry of its own `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11,
    2026-09-01]`. Two of those the specification had not named, and a rule written from its five
    would have added a library to a playlist as a single row.

    **Three shapes of expansion, because the reference has three**
    `[source: MediaBrowser.Controller/Playlists/Playlist.cs:191-232 @ v10.11.11]`:

    * a **folder** - anything with children - answers its playable descendants in the folder's own
      order, which is the order `/Items?parentId=` gives and therefore the album's own order
      (AC-7). Recursive, so a series answers episodes rather than seasons;
    * an **artist** or a **music genre** answers the audio linked to it, ordered by album artist,
      then album, then sort name. The link and not the tree: an artist's expansion carries the
      tracks they are credited on and not only the ones under their own albums, which measured as
      forty-two rows where the tree gives forty;
    * **a playlist** answers its own entries, in its own order and filtered to what this reader may
      see - the one container whose children are not in the item tree at all.

    Expansion happens **in place**: a request naming a film, an album and a second film lands the
    album's tracks between the two films rather than after them.

    **Two of these branches the test world cannot discriminate**, named here rather than left to
    look proven: its one music genre is carried by an album and not by that album's tracks, so the
    by-name query and the folder query answer alike there, and its one guest album sorts the same
    way under the artist's three keys as under a plain name ordering - which is why
    `tests/unit/test_playlist_expansion_order.py` asserts the ordering where it is decided.
    """

    queries: ItemQueryRepository
    playlists: PlaylistRepository

    def resolve(self, user: User, item_key: str) -> HydratedItem | None:
        """The item that identifier names, or `None` when it names nothing this user may see.

        The one identifier that is neither is refused here rather than skipped: an all-zeros id is
        `EmptyIdentifierError` on every route that resolves one, which is where the reference puts
        it too - in the lookup, not in any route.
        """
        if item_key == EMPTY_ID:
            raise EmptyIdentifierError("an identifier of all zeros names no item")
        page = self.queries.run(ItemQuery(user=user, ids=(item_key,), limit=1, count=False))
        return page.items[0] if page.items else None

    def expand(self, user: User, found: HydratedItem) -> list[HydratedItem]:
        """This item as playlist entries: itself if it is a file, its contents if it is not."""
        kind = found.item.type
        if kind in FILE_BACKED:
            return [found]
        if kind is ItemType.PLAYLIST:
            return _in_playlist_order(self.queries, user, self.playlists.entries(found.id, user))
        if kind is ItemType.MUSIC_ARTIST:
            return self._linked(ItemQuery(user=user, artist_ids=(found.id,), count=False))
        if kind is ItemType.MUSIC_GENRE:
            return self._linked(ItemQuery(user=user, genre_ids=(found.id,), count=False))
        return list(
            self.queries.run(
                ItemQuery(
                    user=user,
                    parent_id=found.id,
                    recursive=True,
                    media_types=PLAYABLE_MEDIA_TYPES,
                    count=False,
                )
            ).items
        )

    def _linked(self, query: ItemQuery) -> list[HydratedItem]:
        """Audio linked to a by-name row, in the reference's three keys.

        The middle key is why this is sorted here rather than by the query: `Album` is not one of
        the eight tokens `sortBy` accepts, and adding a ninth to express it would put a key on the
        wire that no reference server orders by - which `SortBy`'s own docstring forbids for
        exactly that reason. The three values come off the hydrated rows instead: a track's
        grandparent is its album artist and its parent is its album (`PARENT_OF`), so the ordering
        is the reference's without a new vocabulary. The id closes it, so it is total
        (Principle VII).
        """
        rows = self.queries.run(replace(query, include_types=frozenset({ItemType.AUDIO}))).items
        return sorted(rows, key=_by_album_artist_album_and_name)


def _by_album_artist_album_and_name(one: HydratedItem) -> tuple[str, str, str, str]:
    return (
        one.grandparent.name if one.grandparent is not None else "",
        one.parent.name if one.parent is not None else "",
        one.item.sort_name,
        one.id,
    )


def _settles(found: HydratedItem, expanded: Sequence[HydratedItem]) -> str | None:
    """What this requested id decides the new playlist's media type to be, or `None`.

    Three steps, in the reference's own order: the item's own value if it has one - which for a
    playlist named in `Ids` is the value that playlist was born with - then the four containers
    that answer from their kind, then the first playable thing the expansion produced. A container
    that expands to nothing decides nothing, and the walk moves on to the next id: measured, an
    empty folder followed by a film creates a `Video` playlist and the same folder alone creates
    an `Audio` one, which is the fallback rather than the folder
    `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`.
    """
    own = found.media_type or MEDIA_TYPE_OF[found.item.type]
    if own != UNKNOWN_MEDIA_TYPE:
        return own
    named = CONTAINER_MEDIA_TYPE.get(found.item.type)
    if named is not None:
        return named
    for one in expanded:
        value = one.media_type or MEDIA_TYPE_OF[one.item.type]
        if value != UNKNOWN_MEDIA_TYPE:
            return value
    return None


def _walk(
    expander: _Expander, owner: User, asked_ids: list[str], asked_type: str | None
) -> tuple[list[str], str]:
    """Resolve the id list in order, and settle the media type on the way through.

    **The two refusals in section 3.2's table are one loop**, and the order-dependence is the
    behaviour rather than an artefact of it: while no media type is settled, an id that resolves
    to nothing refuses the whole request, and once one is settled the same id is skipped in
    silence. So `[absent, track]` is `400` and `[track, absent]` is `200`, and naming a
    `MediaType` makes both `200`
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.

    **A container named here expands, and what it expands to settles the media type**, which is
    T10's correction to this function rather than a new capability beside it. An album in `Ids`
    creates a playlist of nineteen tracks answering `Audio`, and a **series** creates one of eight
    episodes answering `Video` - where the series' own media type is `Unknown` and the empty-list
    fallback is `Audio`, so a walk that read the container's own value would store a media type no
    reference server holds `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11,
    2026-09-01]`.

    An empty list, or one that resolves to nothing after the type is settled, keeps `Audio` - the
    reference's own fallback, which is `MEDIA_TYPE_OF`'s entry for the type (009 spec section 3.2).
    """
    entries: list[str] = []
    settled = asked_type
    for item_key in asked_ids:
        found = expander.resolve(owner, item_key)
        if found is None:
            if settled is None:
                raise PlaylistCreationError(f"no item {item_key} to infer a media type from")
            continue
        expanded = expander.expand(owner, found)
        if settled is None:
            settled = _settles(found, expanded)
        entries.extend(one.id for one in expanded)
    return entries, settled if settled is not None else MEDIA_TYPE_OF[ItemType.PLAYLIST]


@router.get(ITEMS_ROUTE)
async def playlist_items(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    playlistId: WireGuid,  # noqa: N803
    userId: WireGuid | None = None,  # noqa: N803
    startIndex: int = 0,  # noqa: N803
    limit: int | None = None,
    fields: str | None = None,
    enableImages: bool = True,  # noqa: N803
    enableUserData: bool = True,  # noqa: N803
    imageTypeLimit: int | None = None,  # noqa: N803
    enableImageTypes: str | None = None,  # noqa: N803
) -> BaseItemDtoQueryResult:
    """`GetPlaylistItems` `[spec: GetPlaylistItems]`, in 009 plan section 6.5's five steps.

    **Eight parameters and no ninth.** There is no sort of any kind: 009 spec section 3.3 claimed
    a `sortBy` until the gate removed it, and honouring one would be a capability a client could
    discover, which is Principle I's plainest breach. Measured for completeness rather than
    assumed - `sortBy=SortName&sortOrder=Descending` answers `200` in the playlist's own order
    `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]` - and there is nothing
    for the tier 3 recorder to record, because an undeclared parameter is not a dropped token.

    **`playlistId` is typed as an identifier, and the measurement is why.** A *malformed* one
    never reaches this function: the reference answers it with the model binder's validation
    `400`, not with the route's own `404`, so the three requests that do reach the refusal below
    - an id addressing nothing, an id addressing a real item that is not a playlist, and a
    playlist this reader may not see - are one body between them and a fourth is a different
    status entirely `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.

    **The refusal is `404` and not `403`, and it is the fourth error shape.**
    `PlaylistNotFoundError` carries the argument; the short version is that the reference's
    visibility test runs in front of its permission test, so the `403` this route declares is
    unreachable for anything the store holds (009 spec section 3.3), and the body is the bare
    JSON string rather than the problem details every other `404` in this project answers.

    **`may_read` is called here even though `by_id` took a `User`.** That door hands the row to an
    administrator on purpose, so that T12's deletion is writable at all - which means the read
    that skipped this call would show an administrator every private playlist on the server
    (009 spec section 3.7's last row).
    """
    route = ITEMS_ROUTE
    state = get_state(request)
    asked_fields = parse_fields(fields, recorder(request), route)

    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        queries = ItemQueryRepository(opened)
        playlists = PlaylistRepository(opened, queries)

        playlist = playlists.by_id(playlistId, target)
        if playlist is None or not may_read(playlist, target):
            raise PlaylistNotFoundError
        visible = playlists.entries(playlist.id, target)

        wanted = _page(visible, startIndex, limit)
        rows = _in_playlist_order(queries, target, wanted)
        context = BuildContext(
            server_id=state.server_id,
            width=Width.LIST_ROW,
            playlist_row=True,
            fields=asked_fields,
            enable_user_data=enableUserData,
            enable_images=enableImages,
            image_type_limit=imageTypeLimit,
            enable_image_types=frozenset(split_csv(enableImageTypes)) or None,
            libraries=library_context(LibraryRepository(opened)),
            aggregates=aggregates_context(queries, rows, target, asked_fields, Width.LIST_ROW),
        )
        built = build_dtos(rows, context)

    return BaseItemDtoQueryResult(
        items=built, total_record_count=len(visible), start_index=startIndex
    )


def _page(visible: Sequence[str], start_index: int, limit: int | None) -> list[str]:
    """The window of the order this reader may see, and the count is taken beside it, not here.

    Plan section 6.5 step 4: the count is what survived filtering and comes **before** paging,
    which is the only order that lets a client page - measured, `startIndex=1&limit=2` answers two
    rows and `TotalRecordCount=5`, and `startIndex=99` answers no rows and the same five
    `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.

    `start_index` is clamped at zero rather than passed to a slice: a negative one would wrap in
    Python and hand back the tail of the playlist, which is a shape no reference server produces
    and the sort of thing only arithmetic notices.
    """
    start = max(start_index, 0)
    end = None if limit is None else start + max(limit, 0)
    return list(visible[start:end])


def _in_playlist_order(
    queries: ItemQueryRepository, target: User, wanted: Sequence[str]
) -> list[HydratedItem]:
    """Hydrate this page's entries, and put them back in the playlist's order.

    The query answers in *its* order, not the playlist's, and the playlist's order is the entire
    point of the endpoint (009 spec section 3.3) - so the rows are re-seated by the identifiers
    they were asked for. One query for the page, never one per entry.

    Every identifier here has already survived `entries()`, so a row that fails to come back is a
    row that vanished between two statements of one transaction; it is dropped rather than
    faked, and the count above still reports what the reader was told the playlist holds.
    """
    if not wanted:
        return []
    page = queries.run(ItemQuery(user=target, ids=tuple(wanted), limit=len(wanted), count=False))
    by_id = {one.id: one for one in page.items}
    return [by_id[item_key] for item_key in wanted if item_key in by_id]


# --------------------------------------------------------------------------------------------
# The two entry-writing routes (T10)
# --------------------------------------------------------------------------------------------
#
# Both take one identifier list, and neither refuses one that names nothing: an unknown id is
# skipped on the add - unconditionally, unlike creation - and a removal that names an entry the
# playlist does not hold is a success `[probe: tools/probe_playlist_add_remove.py, Jellyfin
# 10.11.11, 2026-09-01]`. What they refuse is the caller and the *playlist*, in that order.


def _identifiers(raw: str | None) -> list[str]:
    """A comma-separated identifier list, canonicalised, with unparseable tokens dropped.

    **Dropped rather than refused**, which is the opposite of what the same value does in the
    create *body*: `{"Ids": ["banana"]}` is the binder's validation `400` (T8) and
    `?ids=banana,<a track>` adds the track and says nothing about the word. Measured on the add
    route and on the removal `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11,
    2026-09-01]` - a query list is bound token by token where a body property is bound as a whole,
    so the two are one value with two refusals, which is behaviours section 1.12's shape.
    """
    wanted: list[str] = []
    for token in split_csv(raw):
        canonical = normalise(token)
        if isinstance(canonical, str) and CANONICAL.match(canonical):
            wanted.append(canonical)
    return wanted


def _editable(playlists: PlaylistRepository, playlist_id: str, user: User) -> Playlist:
    """The playlist this caller may write to, or the refusal that says why - in that order.

    **`404` before `403`, and the order is the whole disclosure rule.** A playlist this caller
    cannot see answers exactly what an identifier that names nothing answers, twenty bytes and
    all, so no write route can be used to learn that a private playlist exists
    `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`.

    **Then the editing test, and it is the other `403`.** 009 spec section 3.7's *May edit* column
    is refused with no body and no content type, because the reference *returns* that refusal
    rather than throwing it (`EmptyForbiddenError`). Three callers reach it: a share without
    `CanEdit`, a public playlist's reader, and an administrator who is none of section 3.7's three
    classes - and that last one only where the playlist is **visible** to them, since a private
    one is `404` at the line above and never reaches the test.
    """
    playlist = playlists.by_id(playlist_id, user)
    if playlist is None or not may_read(playlist, user):
        raise PlaylistNotFoundError
    if not may_edit(playlist, user):
        raise EmptyForbiddenError("this caller may read the playlist and may not edit it")
    return playlist


@router.post(ITEMS_ROUTE, status_code=204)
async def add_to_playlist(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    playlistId: WireGuid,  # noqa: N803
    ids: str | None = None,
    userId: WireGuid | None = None,  # noqa: N803
) -> Response:
    """`AddItemToPlaylist` `[spec: AddItemToPlaylist]`. Appends to the end, and answers `204`.

    **Every container expands, in place** - `_Expander` carries the width of that claim and how
    it was measured. The two things this route adds to it are the ones a single-id request cannot
    show: the expansion lands where the container was named rather than after everything else, and
    the batch is de-duplicated as a batch, so an album named twice adds its tracks once.

    **An unknown id is skipped unconditionally here**, which is the difference from creation
    (009 spec section 3.4): `[absent, track]` and `[track, absent]` both add the track, where the
    same pair on `POST /Playlists` answers `400` in one order and `200` in the other. The one
    identifier that is not skipped is all zeros, and `EmptyIdentifierError` says why.

    **`userId` names the writer**, and Atrium refuses a non-administrator who names anybody else -
    `effective_user` again, unchanged, which is the rule the reference applies on this very route
    and not on the read beside it (009 spec section 3.7, behaviours section 3.16).
    """
    with session_scope(get_sessions(request)) as opened:
        target = effective_user(UserRepository(opened), caller, userId)
        queries = ItemQueryRepository(opened)
        playlists = PlaylistRepository(opened, queries)
        playlist = _editable(playlists, playlistId, target)

        expander = _Expander(queries, playlists)
        entries: list[str] = []
        for item_key in _identifiers(ids):
            found = expander.resolve(target, item_key)
            if found is None:
                continue
            entries.extend(one.id for one in expander.expand(target, found))
        playlists.append(playlist.id, entries)
    return Response(status_code=204)


@router.delete(ITEMS_ROUTE, status_code=204)
async def remove_from_playlist(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    playlistId: WireGuid,  # noqa: N803
    entryIds: str | None = None,  # noqa: N803
) -> Response:
    """`RemoveItemFromPlaylist` `[spec: RemoveItemFromPlaylist]`. `204`, and `204` again.

    **An entry id that is not in the playlist is a success**, and the reason is a client's rather
    than a purist's: clients retry, and a retry after a removal that worked must not fail
    (009 spec section 3.5). Measured with each class of identifier - absent, malformed, all zeros -
    and all three are `204` with the playlist untouched
    `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`. The all-zeros id
    is *not* the refusal it is on the add route, because nothing here looks an item up.

    **This route takes no `userId`, and that is the reference's shape rather than an omission**:
    the removal reads the caller's own identity where the addition above declares the parameter
    `[spec: RemoveItemFromPlaylist]`. Declaring one here would be a lever no reference server has.
    """
    with session_scope(get_sessions(request)) as opened:
        queries = ItemQueryRepository(opened)
        playlists = PlaylistRepository(opened, queries)
        playlist = _editable(playlists, playlistId, caller)
        playlists.remove(playlist.id, _identifiers(entryIds))
    return Response(status_code=204)


@router.post(MOVE_ROUTE, status_code=204)
async def move_playlist_item(
    request: Request,
    caller: Annotated[User, Depends(require_user)],
    playlistId: WireGuid,  # noqa: N803
    itemId: str,  # noqa: N803 - a string on purpose; the docstring below is why
    newIndex: int,  # noqa: N803
) -> Response:
    """`MoveItem` `[spec: MoveItem]`. `204`, and the arithmetic is not here.

    **Three path segments, three different bindings, and the reference has all three.** The
    playlist id is *parsed*, by the controller rather than by the binder, so a **dashed** one
    addresses the same playlist and a malformed one is an unhandled `500`
    `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:409-431 @ v10.11.11]`; the entry id
    is never parsed at all and is compared as text against the plain 32-character spelling, so a
    dashed entry id matches **nothing** and an upper-case one matches
    `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:308-323 @ v10.11.11]`; and
    the index is a route-bound integer, so `Move/banana` is the model binder's validation `400`
    keyed `newIndex` - the one refusal on this route that needs no code. All three measured
    `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`.

    So `itemId` is **not** a `WireGuid` and is not passed through `normalise`, which is the
    opposite of every other identifier in this module: normalising it would move an entry on a
    request that moves nothing on a reference server, and the caller would see it in the order
    that comes back. Case is folded and nothing else is.

    **The refusals are in the reference's own order**, which is measured rather than deduced: a
    caller who may not edit is refused `403` even when the index is one the reference crashes on
    `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-09-01]`. So `_editable` runs
    first - `404` in the read route's twenty bytes, then the body-less `403` - and only then is
    the index judged, before the entry is looked up (009 plan section 6.4.1).

    **The two refusals the reference does not make** are both `400` in the bare-text shape, and
    the bytes are the ones its own `500` carries so the status is the whole difference: an index
    past the caller's entry count, and a negative one (behaviours section 3.15). Everything else
    is `204` - a move, a no-op, and an entry id that is not in this caller's list, whether it is
    absent, all zeros or not an identifier at all. The all-zeros id is **not** the refusal it is
    on the add route, because nothing here looks an item up.

    **No `userId`, and that is the reference's shape** `[spec: MoveItem]`: this route reads the
    calling user's identity, as the removal beside it does, so there is no `effective_user` call
    and no way to move an entry on somebody else's behalf.
    """
    with session_scope(get_sessions(request)) as opened:
        queries = ItemQueryRepository(opened)
        playlists = PlaylistRepository(opened, queries)
        playlist = _editable(playlists, playlistId, caller)
        try:
            playlists.reorder(
                playlist.id, itemId.lower(), newIndex, playlists.entries(playlist.id, caller)
            )
        except MoveIndexOutOfRangeError as refused:
            raise PlaylistMoveError(str(refused)) from refused
    return Response(status_code=204)
