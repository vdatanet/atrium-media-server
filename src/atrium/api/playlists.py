# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference's `PlaylistsController`, starting with the one route that creates a playlist.

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

See specs/009-playlists/spec.md section 3.2 and plan section 6.1.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from fastapi import APIRouter, Depends, Request

from atrium.api.deps import get_sessions, require_user
from atrium.api.items import effective_user, recorder, split_csv
from atrium.compat.errors import PlaylistCreationError
from atrium.compat.guids import WireGuid, new_id
from atrium.compat.model import AtriumModel
from atrium.db.engine import session_scope
from atrium.db.item_queries import ItemQueryRepository
from atrium.db.repositories import PlaylistRepository, UserRepository
from atrium.domain.items import MEDIA_TYPE_OF, ItemType
from atrium.domain.playlists import Playlist, Share
from atrium.domain.queries import ItemQuery
from atrium.domain.user import User

router = APIRouter(tags=["Playlists"])

ROUTE = "/Playlists"

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
        entries, media_type = _walk(queries, owner, asked_ids, asked_type)
        playlist = Playlist(
            id=new_id(),
            name=asked_name,
            owner_user_id=owner.id,
            is_public=body.is_public if body is not None else False,
            media_type=media_type,
            shares=_shares(body),
        )
        PlaylistRepository(opened, queries).create(playlist, entries)
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


def _walk(
    queries: ItemQueryRepository, owner: User, asked_ids: list[str], asked_type: str | None
) -> tuple[list[str], str]:
    """Resolve the id list in order, and settle the media type on the way through.

    **The two refusals in section 3.2's table are one loop**, and the order-dependence is the
    behaviour rather than an artefact of it: while no media type is settled, an id that resolves
    to nothing refuses the whole request, and once one is settled the same id is skipped in
    silence. So `[absent, track]` is `400` and `[track, absent]` is `200`, and naming a
    `MediaType` makes both `200`
    `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.

    **A container is not expanded here yet.** Plan section 6.2's one expansion serves creation and
    addition alike, and it arrives with the addition route at T10 - which is also where the
    album's own order is asserted (AC-7). Until then a container named in `Ids` becomes an entry
    of its own, and the media type it settles is the container's rather than its children's.

    An empty list, or one that resolves to nothing after the type is settled, keeps `Audio` - the
    reference's own fallback, which is `MEDIA_TYPE_OF`'s entry for the type (009 spec section 3.2).
    """
    entries: list[str] = []
    settled = asked_type
    for item_key in asked_ids:
        page = queries.run(ItemQuery(user=owner, ids=(item_key,), limit=1, count=False))
        if not page.items:
            if settled is None:
                raise PlaylistCreationError(f"no item {item_key} to infer a media type from")
            continue
        found = page.items[0]
        if settled is None:
            settled = found.media_type or MEDIA_TYPE_OF[found.item.type]
        entries.append(found.id)
    return entries, settled if settled is not None else MEDIA_TYPE_OF[ItemType.PLAYLIST]
