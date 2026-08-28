# SPDX-License-Identifier: GPL-3.0-or-later
"""Domain item to `BaseItemDto`: one registry, three widths, no session.

The registry below is **data** - which properties always go out, which go out for which types,
and which only when asked - so the test that pins spec section 3.2 is a comparison of two tables
rather than sixty hand-written assertions (plan section 6.5). The per-type and always-present
sets are the measured ones, not the remembered ones:
`[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`.

**The width is a property of the call site, not of the item.** A list row applies the table; the
single-item route emits every registry field whatever the request said, because that is what the
reference does - a bare full body carries up to 39 properties a bare list row does not; and
`/UserViews` adds a measured extra set on top of a list row. One table, three entry points.

The builder receives `HydratedItem`s and a `BuildContext` and issues no query, ever - it has no
session to misuse, which is what makes the N+1 ban structural (plan section 5). Everything an
emitter reads arrived with the page: the ancestors, the rollups, and - when a route resolved
`Fields` to need them - the container aggregates, fetched once per batch by the repository.

Three emitters answer for values 004 never stored, and each is a decision recorded rather than a
guess (the Done note of 005 T9 carries the argument):

* `Etag` is a hash of the item's identity and its two change clocks. Opaque and stable, which is
  all an etag promises; the reference's is a hash of its own internals and no client compares
  etags across servers.
* `ExternalUrls` is a table over `ProviderIds`, reproducing the reference's URL patterns as
  measured `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
* `ImageBlurHashes` is always the empty map: Atrium computes no BlurHash, and an invented one
  would be a lie a client renders (behaviours section 5.5).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from hashlib import sha256
from typing import Any

from atrium.db.item_queries import Ancestor, ContainerAggregates, HydratedItem
from atrium.domain.items import BY_NAME, FILE_BACKED, MEDIA_TYPE_OF, ItemType
from atrium.metadata.artwork import ImageKind

from .item_models import BaseItemDto, BaseItemPerson, ExternalUrl, NameGuidPair, UserItemDataDto


class Width(Enum):
    """How much of the registry a call site emits - the three measured shapes of spec 3.2."""

    LIST_ROW = "list-row"
    FULL = "full"
    USER_VIEW = "user-view"


@dataclass(frozen=True, slots=True)
class LibraryContext:
    """What a response needs to know about a library: its declared kind, and where it lives."""

    collection_type: str
    roots: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BuildContext:
    """Everything the batch shares. Routes fill it; the builder only reads it."""

    server_id: str
    width: Width = Width.LIST_ROW
    #: The resolved `fields` tokens, wire spellings, unknown ones already dropped and recorded
    #: by `compat.query_params` (behaviours section 1.12).
    fields: frozenset[str] = frozenset()
    enable_user_data: bool = True
    enable_images: bool = True
    image_type_limit: int | None = None
    enable_image_types: frozenset[str] | None = None
    #: By library id. Small - a server has tens of libraries - and only routes that emit
    #: `CollectionType` or `Path` need to supply it.
    libraries: Mapping[str, LibraryContext] = dataclass_field(default_factory=dict)
    #: By item id, from `ItemQueryRepository.aggregates_for`, when the resolved fields need the
    #: subtree numbers. Empty otherwise: the emitters then leave those properties absent.
    aggregates: Mapping[str, ContainerAggregates] = dataclass_field(default_factory=dict)
    #: Names a route measurably never sends, whatever the tier says. The by-name routes are the
    #: users: `/Genres` and `/MusicGenres` rows carry no `UserData`, and the two artist routes no
    #: `IsFolder`, where the same items through `/Items` carry both
    #: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    omit: frozenset[str] = frozenset()


# ------------------------------------------------------------------------------------------------
# The registry: spec section 3.2 as data
# ------------------------------------------------------------------------------------------------

#: On every item, in every list. `IsFolder`'s emitter still answers nothing for a by-name row and
#: `UserData`'s for a suppressed request - the tier says when a property is *considered*, the
#: emitter says whether the item has a value, and a null is absent (behaviours section 1.7).
ALWAYS: frozenset[str] = frozenset(
    {
        "Id",
        "ServerId",
        "Name",
        "Type",
        "MediaType",
        "IsFolder",
        "LocationType",
        "ChannelId",
        "UserData",
        "ImageTags",
        "ImageBlurHashes",
        "BackdropImageTags",
    }
)

#: Present on a bare list row when the item is one of these types - the measured matrix, kept to
#: the fields the spec lists. A type absent from a row means the reference never emits that
#: property on that type's bare list row, asked-for or not observed.
PER_TYPE: Mapping[str, frozenset[ItemType]] = {
    "ProductionYear": frozenset(
        {
            ItemType.MOVIE,
            ItemType.SERIES,
            ItemType.SEASON,
            ItemType.EPISODE,
            ItemType.MUSIC_ALBUM,
            ItemType.AUDIO,
        }
    ),
    "PremiereDate": frozenset(
        {
            ItemType.MOVIE,
            ItemType.SERIES,
            ItemType.SEASON,
            ItemType.EPISODE,
            ItemType.MUSIC_ALBUM,
            ItemType.AUDIO,
        }
    ),
    "RunTimeTicks": frozenset(
        {
            ItemType.MOVIE,
            ItemType.SERIES,
            ItemType.EPISODE,
            ItemType.MUSIC_ARTIST,
            ItemType.MUSIC_ALBUM,
            ItemType.AUDIO,
        }
    ),
    "OfficialRating": frozenset({ItemType.MOVIE, ItemType.SERIES}),
    "CommunityRating": frozenset({ItemType.MOVIE, ItemType.SERIES, ItemType.EPISODE}),
    "IndexNumber": frozenset({ItemType.SEASON, ItemType.EPISODE, ItemType.AUDIO}),
    "ParentIndexNumber": frozenset({ItemType.EPISODE, ItemType.AUDIO}),
    "SeriesId": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    "SeriesName": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    "SeasonId": frozenset({ItemType.EPISODE}),
    "SeriesPrimaryImageTag": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    # Unconfirmed: never observed, and a null is indistinguishable from a gate from outside.
    # It stays where the spec keeps it rather than being deleted on one library's evidence.
    "SeriesThumbImageTag": frozenset({ItemType.EPISODE}),
    "ParentThumbItemId": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    "ParentThumbImageTag": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    "ParentBackdropImageTags": frozenset(
        {ItemType.SEASON, ItemType.EPISODE, ItemType.MUSIC_ALBUM, ItemType.AUDIO}
    ),
    "Album": frozenset({ItemType.AUDIO}),
    "AlbumId": frozenset({ItemType.AUDIO}),
    "AlbumPrimaryImageTag": frozenset({ItemType.AUDIO}),
    "AlbumArtist": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "AlbumArtists": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "Artists": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "ArtistItems": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "CollectionType": frozenset({ItemType.COLLECTION_FOLDER}),
}

#: Property -> the `ItemFields` token that requests it. Almost the identity map; `GenreItems` is
#: the exception, because the enum has no token of its own for it - the pair travels together
#: under `Genres`. `[spec: ItemFields]`
GATED: Mapping[str, str] = {
    "MediaSources": "MediaSources",
    "MediaStreams": "MediaStreams",
    "Path": "Path",
    "Etag": "Etag",
    "Chapters": "Chapters",
    "DateCreated": "DateCreated",
    "DateLastMediaAdded": "DateLastMediaAdded",
    "ProviderIds": "ProviderIds",
    "Tags": "Tags",
    "Taglines": "Taglines",
    "ExternalUrls": "ExternalUrls",
    "OriginalTitle": "OriginalTitle",
    "ParentId": "ParentId",
    "CumulativeRunTimeTicks": "CumulativeRunTimeTicks",
    "RecursiveItemCount": "RecursiveItemCount",
    "ChildCount": "ChildCount",
    "SortName": "SortName",
    "Overview": "Overview",
    "Genres": "Genres",
    "GenreItems": "Genres",
    "Studios": "Studios",
    "People": "People",
    "PrimaryImageAspectRatio": "PrimaryImageAspectRatio",
    "Width": "Width",
    "Height": "Height",
}

#: What `/UserViews` adds on top of a list row, unasked - measured, all sixteen on all six rows
#: `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`. T11's route passes
#: `Width.USER_VIEW` and this is what it buys.
USER_VIEW_EXTRAS: frozenset[str] = frozenset(
    {
        "ChildCount",
        "DateCreated",
        "DateLastMediaAdded",
        "Etag",
        "ExternalUrls",
        "GenreItems",
        "Genres",
        "ParentId",
        "Path",
        "People",
        "PrimaryImageAspectRatio",
        "ProviderIds",
        "SortName",
        "Studios",
        "Taglines",
        "Tags",
    }
)

#: The 008 gap, named: these describe what probing a file finds, nothing has probed, and a stub
#: would lie (plan section 1). Their emitters yield nothing; a test asserts the absence so that
#: 008's arrival changes a failing test rather than nothing.
UNPROBED: frozenset[str] = frozenset(
    {"MediaSources", "MediaStreams", "Chapters", "Width", "Height"}
)


# ------------------------------------------------------------------------------------------------
# Emitters
# ------------------------------------------------------------------------------------------------


def _series_of(one: HydratedItem) -> Ancestor | None:
    """The series above a season or an episode, whichever distance it sits at."""
    if one.item.type is ItemType.SEASON:
        return one.parent
    if one.item.type is ItemType.EPISODE:
        return one.grandparent
    return None


def _first_with(one: HydratedItem, kind: ImageKind) -> Ancestor | None:
    """The nearest ancestor carrying an image of this kind - `Parent*` walks up, nearest first."""
    for ancestor in (one.parent, one.grandparent):
        if ancestor is not None and any(image.kind is kind for image in ancestor.images):
            return ancestor
    return None


def _tag_of(ancestor: Ancestor | None, kind: ImageKind) -> str | None:
    if ancestor is None:
        return None
    return next((image.tag for image in ancestor.images if image.kind is kind), None)


def _album_artist_links(one: HydratedItem) -> tuple[Any, ...]:
    """The album-artist credits: an album's own, a track's from the album above it."""
    if one.item.type is ItemType.MUSIC_ALBUM:
        links = one.artists
    elif one.item.type is ItemType.AUDIO and one.parent is not None:
        links = one.parent.artists
    else:
        links = ()
    return tuple(link for link in links if link.credit == "album_artist")


def _performer_links(one: HydratedItem) -> tuple[Any, ...]:
    return tuple(link for link in one.artists if link.credit == "artist")


def _image_tags(one: HydratedItem, ctx: BuildContext) -> dict[str, str] | None:
    """Every non-backdrop image as `{kind: tag}` - `{}` when there are none, absent only when
    the caller switched images off. The empty object is the measured empty shape."""
    if not ctx.enable_images:
        return None
    allowed = ctx.enable_image_types
    return {
        image.kind.value: image.tag
        for image in one.images
        if image.kind is not ImageKind.BACKDROP
        and image.index == 0
        and (allowed is None or image.kind.value in allowed)
    }


def _backdrop_tags(one: HydratedItem, ctx: BuildContext) -> list[str] | None:
    if not ctx.enable_images:
        return None
    allowed = ctx.enable_image_types
    if allowed is not None and ImageKind.BACKDROP.value not in allowed:
        return []
    tags = [image.tag for image in one.images if image.kind is ImageKind.BACKDROP]
    if ctx.image_type_limit is not None:
        tags = tags[: max(ctx.image_type_limit, 0)]
    return tags


def _user_data(one: HydratedItem, ctx: BuildContext) -> UserItemDataDto | None:
    if not ctx.enable_user_data:
        return None
    data = one.user_data
    percentage: float | None = None
    runtime = one.metadata.runtime_ticks
    if data.playback_position_ticks > 0 and runtime:
        percentage = data.playback_position_ticks / runtime * 100
    return UserItemDataDto(
        played_percentage=percentage,
        unplayed_item_count=data.unplayed_count,
        playback_position_ticks=data.playback_position_ticks,
        play_count=data.play_count,
        is_favorite=data.is_favorite,
        last_played_date=data.last_played_date,
        played=data.played,
        key=one.id,
        item_id=one.id,
    )


def _etag(one: HydratedItem) -> str:
    """Opaque and stable: the identity and the two change clocks, hashed. 32 hex like the
    reference's, and like every identifier here (behaviours section 1.4)."""
    stamped = f"{one.id}\n{one.item.date_modified or ''}\n{one.metadata.refreshed_at or ''}"
    return sha256(stamped.encode("utf-8")).hexdigest()[:32]


#: `ProviderIds` key -> how the reference links it, measured on a live 10.11.11 across a movie,
#: a series, an episode, an artist, an album and a track
#: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. `Tmdb` is the
#: one key whose URL depends on the item's type: `/movie/` for a film, `/tv/` for the series
#: family. Keys 004 never writes never appear, so nothing else is reproduced here.
_EXTERNAL: tuple[tuple[str, str, str], ...] = (
    ("Imdb", "IMDb", "https://www.imdb.com/title/{0}"),
    ("Tmdb", "TMDB", ""),  # pattern chosen per type below
    ("MusicBrainzAlbum", "MusicBrainz Album", "https://musicbrainz.org/release/{0}"),
    (
        "MusicBrainzAlbumArtist",
        "MusicBrainz Album Artist",
        "https://musicbrainz.org/artist/{0}",
    ),
    (
        "MusicBrainzReleaseGroup",
        "MusicBrainz Release Group",
        "https://musicbrainz.org/release-group/{0}",
    ),
    ("MusicBrainzArtist", "MusicBrainz Artist", "https://musicbrainz.org/artist/{0}"),
)

_TMDB_TV = frozenset({ItemType.SERIES, ItemType.SEASON, ItemType.EPISODE})


def _external_urls(one: HydratedItem) -> list[ExternalUrl]:
    """Always a list - the measured empty case is `[]`, not an absent property."""
    links: list[ExternalUrl] = []
    ids = one.metadata.provider_ids
    for key, name, pattern in _EXTERNAL:
        value = ids.get(key)
        if not value:
            continue
        if key == "Tmdb":
            base = (
                "https://www.themoviedb.org/tv/{0}"
                if one.item.type in _TMDB_TV
                else ("https://www.themoviedb.org/movie/{0}")
            )
            links.append(ExternalUrl(name=name, url=base.format(value)))
            continue
        links.append(ExternalUrl(name=name, url=pattern.format(value)))
    return links


def _path(one: HydratedItem, ctx: BuildContext) -> str | None:
    """The file's place on disk, rebuilt from the library root and the stored relative path.

    A library may declare several roots and the schema does not record which one a source came
    from - identities collide before paths can (003 section 3.6) - so the first root is the
    reconstruction. A container has no path and answers nothing.
    """
    relative = one.item.relative_path
    if relative is None or one.item.library_id is None:
        return None
    library = ctx.libraries.get(one.item.library_id)
    if library is None or not library.roots:
        return None
    return f"{library.roots[0].rstrip('/')}/{relative}"


def _aggregate(
    one: HydratedItem, ctx: BuildContext, pick: Callable[[ContainerAggregates], Any]
) -> Any:
    numbers = ctx.aggregates.get(one.id)
    return pick(numbers) if numbers is not None else None


def _collection_type(one: HydratedItem, ctx: BuildContext) -> str | None:
    library_id = one.item.library_id
    if library_id is None or library_id not in ctx.libraries:
        return None
    return ctx.libraries[library_id].collection_type


EMITTERS: Mapping[str, Callable[[HydratedItem, BuildContext], Any]] = {
    # -- always ----------------------------------------------------------------------------------
    "Id": lambda one, ctx: one.id,
    "ServerId": lambda one, ctx: ctx.server_id,
    "Name": lambda one, ctx: one.item.name,
    "Type": lambda one, ctx: one.item.type.value,
    "MediaType": lambda one, ctx: MEDIA_TYPE_OF[one.item.type],
    #: Absent for a by-name row - the reference sends no `IsFolder` for a genre, a music genre or
    #: a year, list row and full body alike
    #: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    "IsFolder": lambda one, ctx: (
        None if one.item.type in BY_NAME else one.item.type not in FILE_BACKED
    ),
    "LocationType": lambda one, ctx: "FileSystem",
    #: Always None; `BaseItemDto.NULL_KEPT` turns that into the measured explicit null.
    "ChannelId": lambda one, ctx: None,
    "UserData": _user_data,
    "ImageTags": _image_tags,
    #: The empty map, always: no BlurHash is computed and none is invented (behaviours 5.5).
    "ImageBlurHashes": lambda one, ctx: {} if ctx.enable_images else None,
    "BackdropImageTags": _backdrop_tags,
    # -- per type --------------------------------------------------------------------------------
    "ProductionYear": lambda one, ctx: one.metadata.production_year,
    "PremiereDate": lambda one, ctx: one.metadata.premiere_date,
    "RunTimeTicks": lambda one, ctx: one.metadata.runtime_ticks,
    "OfficialRating": lambda one, ctx: one.metadata.official_rating,
    "CommunityRating": lambda one, ctx: one.metadata.community_rating,
    "IndexNumber": lambda one, ctx: one.item.index_number,
    "ParentIndexNumber": lambda one, ctx: one.item.parent_index_number,
    "SeriesId": lambda one, ctx: getattr(_series_of(one), "id", None),
    "SeriesName": lambda one, ctx: getattr(_series_of(one), "name", None),
    "SeasonId": lambda one, ctx: (
        one.parent.id if one.item.type is ItemType.EPISODE and one.parent else None
    ),
    "SeriesPrimaryImageTag": lambda one, ctx: (
        _tag_of(_series_of(one), ImageKind.PRIMARY) if ctx.enable_images else None
    ),
    "SeriesThumbImageTag": lambda one, ctx: (
        _tag_of(_series_of(one), ImageKind.THUMB) if ctx.enable_images else None
    ),
    "ParentThumbItemId": lambda one, ctx: (
        getattr(_first_with(one, ImageKind.THUMB), "id", None) if ctx.enable_images else None
    ),
    "ParentThumbImageTag": lambda one, ctx: (
        _tag_of(_first_with(one, ImageKind.THUMB), ImageKind.THUMB) if ctx.enable_images else None
    ),
    "ParentBackdropImageTags": lambda one, ctx: (
        [
            image.tag
            for image in getattr(_first_with(one, ImageKind.BACKDROP), "images", ())
            if image.kind is ImageKind.BACKDROP
        ]
        or None
        if ctx.enable_images
        else None
    ),
    "Album": lambda one, ctx: getattr(one.parent, "name", None),
    "AlbumId": lambda one, ctx: getattr(one.parent, "id", None),
    "AlbumPrimaryImageTag": lambda one, ctx: (
        _tag_of(one.parent, ImageKind.PRIMARY) if ctx.enable_images else None
    ),
    "AlbumArtist": lambda one, ctx: next((link.name for link in _album_artist_links(one)), None),
    "AlbumArtists": lambda one, ctx: [
        NameGuidPair(name=link.name, id=link.item_id) for link in _album_artist_links(one)
    ],
    "Artists": lambda one, ctx: [link.name for link in _performer_links(one)],
    "ArtistItems": lambda one, ctx: [
        NameGuidPair(name=link.name, id=link.item_id) for link in _performer_links(one)
    ],
    "CollectionType": lambda one, ctx: _collection_type(one, ctx),
    # -- gated -----------------------------------------------------------------------------------
    "MediaSources": lambda one, ctx: None,  # the 008 gap; see UNPROBED
    "MediaStreams": lambda one, ctx: None,
    "Chapters": lambda one, ctx: None,
    "Width": lambda one, ctx: None,
    "Height": lambda one, ctx: None,
    "Path": _path,
    "Etag": lambda one, ctx: _etag(one),
    "DateCreated": lambda one, ctx: one.item.date_created,
    "DateLastMediaAdded": lambda one, ctx: _aggregate(
        one, ctx, lambda numbers: numbers.date_last_media_added
    ),
    "ProviderIds": lambda one, ctx: dict(one.metadata.provider_ids),
    "Tags": lambda one, ctx: list(one.metadata.tags),
    "Taglines": lambda one, ctx: [one.metadata.tagline] if one.metadata.tagline else [],
    "ExternalUrls": lambda one, ctx: _external_urls(one),
    "OriginalTitle": lambda one, ctx: one.metadata.original_title,
    "ParentId": lambda one, ctx: one.item.parent_id,
    "CumulativeRunTimeTicks": lambda one, ctx: _aggregate(
        one, ctx, lambda numbers: numbers.cumulative_runtime_ticks or None
    ),
    "RecursiveItemCount": lambda one, ctx: _aggregate(
        one, ctx, lambda numbers: numbers.recursive_count
    ),
    "ChildCount": lambda one, ctx: _aggregate(one, ctx, lambda numbers: numbers.child_count),
    "SortName": lambda one, ctx: one.item.sort_name,
    "Overview": lambda one, ctx: one.metadata.overview,
    "Genres": lambda one, ctx: [link.name for link in one.genres],
    "GenreItems": lambda one, ctx: [
        NameGuidPair(name=link.name, id=link.item_id) for link in one.genres
    ],
    "Studios": lambda one, ctx: [
        NameGuidPair(name=link.name, id=link.item_id) for link in one.studios
    ],
    "People": lambda one, ctx: [
        BaseItemPerson(name=link.name, id=link.item_id, role=link.role, type=link.credit)
        for link in one.people
    ],
    "PrimaryImageAspectRatio": lambda one, ctx: (
        next(
            (
                image.width / image.height
                for image in one.images
                if image.kind is ImageKind.PRIMARY and image.height
            ),
            None,
        )
        if ctx.enable_images
        else None
    ),
}


# ------------------------------------------------------------------------------------------------
# The builder
# ------------------------------------------------------------------------------------------------


def _considered(item_type: ItemType, ctx: BuildContext) -> frozenset[str]:
    """Which registry names this call site puts to their emitters."""
    named = ALWAYS | frozenset(name for name, types in PER_TYPE.items() if item_type in types)
    if ctx.width is Width.FULL:
        return named | frozenset(GATED)
    gated = frozenset(name for name, token in GATED.items() if token in ctx.fields)
    if ctx.width is Width.USER_VIEW:
        return named | gated | USER_VIEW_EXTRAS
    return named | gated


def dto_values(one: HydratedItem, ctx: BuildContext) -> dict[str, Any]:
    """The wire values, before a model class - for the one route whose rows keep an extra null.

    `/UserViews` emits `"ParentId": null` on its parentless rows (measured; see `UserViewDto`),
    which is a property of the *model* - `NULL_KEPT` is class-level - so T11 pours the same
    values into a different class rather than this module growing a per-call null switch.
    """
    values: dict[str, Any] = {}
    for name in _considered(one.item.type, ctx) - ctx.omit:
        value = EMITTERS[name](one, ctx)
        if value is not None:
            values[name] = value
    return values


def build_dto(one: HydratedItem, ctx: BuildContext) -> BaseItemDto:
    return BaseItemDto(**dto_values(one, ctx))


def build_dtos(items: Sequence[HydratedItem], ctx: BuildContext) -> list[BaseItemDto]:
    """The batch, in order. `ctx` is shared: one width, one field set, one server."""
    return [build_dto(one, ctx) for one in items]


__all__ = [
    "ALWAYS",
    "EMITTERS",
    "GATED",
    "PER_TYPE",
    "UNPROBED",
    "USER_VIEW_EXTRAS",
    "BuildContext",
    "LibraryContext",
    "Width",
    "build_dto",
    "build_dtos",
    "dto_values",
]
