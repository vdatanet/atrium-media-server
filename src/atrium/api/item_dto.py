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
from atrium.media import info as media_info
from atrium.media.decision import (
    PlaybackPolicy,
    unnegotiated_direct_stream,
    unnegotiated_transcoding,
)
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
class ItemAccess:
    """What the effective user may do with an item, as two properties of the wide widths.

    Separate from `PlaybackPolicy`, which is 008's negotiation input: these two are read by
    nothing but the emitters below, and folding them into the decision engine's structure would
    put an item-representation concern inside a transcoding one.

    **Both are the account's policy AND a property of the item.** Measured on a reference
    instance over this repository's own fixture: a library root answers `CanDownload: false` to
    an administrator whose policy permits downloading, a film answers `true`, and an account with
    `EnableContentDownloading` off answers `false` on both; `PlayAccess` is `Full` under
    `EnableMediaPlayback` and `None` without it
    `[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-03]`.
    """

    #: The account's `EnableContentDownloading`. Absent from a policy means permitted, which is
    #: the reference's own default and what `users/policy.py` reads for the playback three.
    downloading: bool = True
    #: The account's `EnableMediaPlayback`, which has a column of its own.
    playback: bool = True


@dataclass(frozen=True, slots=True)
class BuildContext:
    """Everything the batch shares. Routes fill it; the builder only reads it."""

    server_id: str
    #: **Whose** playback permissions the sources in this batch are answered with, and it has no
    #: default on purpose. The reference writes the account's own permissions onto every static
    #: media source it builds, one per media kind, so a permitted default is exactly the wrong
    #: answer for a denied seat - which is the shortfall this field closed, carried as an
    #: accepted gap until 2026-09-02, whose closing mechanism was named as *"the caller's policy
    #: reaching the item builder, which is a shared context and not one route"*. A field with no
    #: default is that mechanism: a route that emits an item cannot be written without deciding
    #: whose policy it emits under, where a default would have let the next one forget in silence
    #: `[source: Emby.Server.Implementations/Dto/DtoService.cs:261,
    #: Emby.Server.Implementations/Library/MediaSourceManager.cs:355-372 @ v10.11.11]`.
    #:
    #: It is the **effective** user's - `userId` when the request names one, the token holder
    #: otherwise - and not the caller's: an administrator reading an item for a denied account is
    #: answered that account's flags, and reading it for themselves is answered their own
    #: `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-02]`. Which is
    #: `effective_user`, already resolved by every route here.
    policy: PlaybackPolicy
    #: The effective user's two item-access permissions, for the same reason `policy` has no
    #: default: a route that emits an item has to decide whose access it emits under, and a
    #: default lets the next one forget in silence.
    access: ItemAccess
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
    #: `omit`'s positive counterpart, and it has exactly one user. A playlist entry row is the
    #: list-row width plus `PlaylistItemId` and nothing else - measured by subtracting the two
    #: property sets, thirty-two names against thirty-one
    #: `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]` - so it is a flag
    #: rather than a fourth `Width`: the measurement says the row *is* a list row, and a fourth
    #: member of that enum would say the opposite.
    playlist_row: bool = False


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

#: The types whose rows carry an inherited backdrop - the id and the tags both, from one walk.
PARENT_BACKDROP_TYPES: frozenset[ItemType] = frozenset(
    {ItemType.SEASON, ItemType.EPISODE, ItemType.MUSIC_ALBUM, ItemType.AUDIO}
)

#: Present on a bare list row when the item is one of these types - the measured matrix, kept to
#: the fields the spec lists. A type absent from a row means the reference never emits that
#: property on that type's bare list row, asked-for or not observed.
PER_TYPE: Mapping[str, frozenset[ItemType]] = {
    #: Measured on a bare list row of all three series of this repository's fixture and on no
    #: other type, at both widths `[probe: tools/probe_wide_body_constants.py, Jellyfin 10.11.11,
    #: 2026-09-06]`. It is the one field of that tranche that is not wide-only.
    "AirDays": frozenset({ItemType.SERIES}),
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
    #: The season's own name, beside the id that already travels: measured on every joined
    #: episode row and every joined episode body, list row and full body alike
    #: `[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-03]`.
    "SeasonName": frozenset({ItemType.EPISODE}),
    "SeriesPrimaryImageTag": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    # Unconfirmed: never observed, and a null is indistinguishable from a gate from outside.
    # It stays where the spec keeps it rather than being deleted on one library's evidence.
    "SeriesThumbImageTag": frozenset({ItemType.EPISODE}),
    "ParentThumbItemId": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    "ParentThumbImageTag": frozenset({ItemType.SEASON, ItemType.EPISODE}),
    # One set, spelled once, because the pair is a pair: the measured wire carries the id on
    # exactly the rows that carry the tags - 197 of 200 sampled episodes carried both, and not
    # one carried either alone `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11,
    # 2026-08-28]`. Two frozensets that agreed today is two frozensets that can drift.
    "ParentBackdropItemId": PARENT_BACKDROP_TYPES,
    "ParentBackdropImageTags": PARENT_BACKDROP_TYPES,
    "Album": frozenset({ItemType.AUDIO}),
    "AlbumId": frozenset({ItemType.AUDIO}),
    "AlbumPrimaryImageTag": frozenset({ItemType.AUDIO}),
    "AlbumArtist": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "AlbumArtists": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "Artists": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "ArtistItems": frozenset({ItemType.MUSIC_ALBUM, ItemType.AUDIO}),
    "CollectionType": frozenset({ItemType.COLLECTION_FOLDER}),
    # -- 008's media properties, on the types that have a file --------------------------------
    # `Container` on all three, `HasSubtitles` and `VideoType` on the two that carry video: the
    # reference attaches the first to every item unconditionally and the other two inside its
    # `is Video` branch, so a track has a container and no video type
    # `[source: Emby.Server.Implementations/Dto/DtoService.cs:832,1101-1110 @ v10.11.11]`,
    # `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`.
    "Container": frozenset({ItemType.MOVIE, ItemType.EPISODE, ItemType.AUDIO}),
    "HasSubtitles": frozenset({ItemType.MOVIE, ItemType.EPISODE}),
    "VideoType": frozenset({ItemType.MOVIE, ItemType.EPISODE}),
}

#: The two members of the reference's `PlayAccess` enum `[spec: BaseItemDto]`.
PLAY_ACCESS_FULL = "Full"
PLAY_ACCESS_NONE = "None"

#: The types whose media properties describe video rather than only sound. `VideoType` says
#: `VideoFile` for exactly these, and `Width`, `Height` and `IsHD` can only be answered for them.
VIDEO_TYPES: frozenset[ItemType] = frozenset({ItemType.MOVIE, ItemType.EPISODE})

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
    "IsHD": "IsHD",
}

#: What the two **wide** widths carry that a list row never does, unasked and ungated.
#:
#: The differential's key-set pass is what found these, which is the closing mechanism
#: [behaviours section 5](../../../docs/compatibility/behaviours.md)'s *"item fields outside the
#: observed union omitted"* row named for itself. Joined 1:1 by `(Type, Name)` rather than by
#: position - a list ordered by a key the two servers disagree about is a list whose rows do not
#: line up, and an absence measured across misaligned rows is not a measurement - every one of
#: these was present on **every** reference full body and **every** `/UserViews` row, and on no
#: joined list row at all `[probe: tools/differential.py --fixture, Jellyfin 10.11.11,
#: 2026-09-03]`. That last half is the whole reason this is a tier of its own: 005 T1 measured
#: three widths, and supplying a full-body property on a list row would trade one difference for
#: another.
#:
#: **Two of the twelve are deliberately not here.** `CanDelete` would advertise a deletion this
#: server refuses by design ([behaviours section 4.3](../../../docs/compatibility/behaviours.md)),
#: which is a decision about that exception rather than a field to fill; and
#: `DisplayPreferencesId` is a digest of the reference's own display-preferences key - the same
#: value for every `Movie`, another for every `Season`, and on a `CollectionFolder` the row's own
#: identifier - so reproducing it is a derivation and not a value this server holds.
WIDE_ONLY: frozenset[str] = frozenset(
    {
        "CanDownload",
        "EnableMediaSourceDisplay",
        "LocalTrailerCount",
        "LockData",
        "LockedFields",
        "PlayAccess",
        "RemoteTrailers",
        "SpecialFeatureCount",
    }
)

#: What the two wide widths add for **some types only**, unasked. `WIDE_ONLY` above is every type
#: or none; this is the same idea with the per-type matrix `PER_TYPE` carries for list rows, and it
#: exists because the reference's full body is not a list row with more fields on it - it gates by
#: type there too. Measured over this repository's own fixture, every item of every type, one full
#: body each `[probe: tools/probe_wide_body_constants.py, Jellyfin 10.11.11, 2026-09-06]`: 32 of 32
#: movies carry `ProductionLocations` and `Trickplay`, 9 of 9 episodes carry `Trickplay`, and no
#: list row of any type carries either.
WIDE_PER_TYPE: Mapping[str, frozenset[ItemType]] = {
    "ProductionLocations": frozenset({ItemType.MOVIE}),
    "Trickplay": frozenset({ItemType.MOVIE, ItemType.EPISODE}),
    #: The parent series' studio. On both of the types that hang under a series, and on no other -
    #: measured on every item of every type of this repository's fixture, 9 of 9 episodes and 7 of
    #: 7 seasons `[probe: tools/probe_wide_body_constants.py, Jellyfin 10.11.11, 2026-09-06]`.
    "SeriesStudio": frozenset({ItemType.EPISODE, ItemType.SEASON}),
    #: The nine by-name counts, on a `MusicArtist` and on nothing else - 4 of 4 artists there and
    #: no other type, at the same reading.
    **{
        name: frozenset({ItemType.MUSIC_ARTIST})
        for name in (
            "TrailerCount",
            "MovieCount",
            "SeriesCount",
            "ProgramCount",
            "EpisodeCount",
            "SongCount",
            "AlbumCount",
            "ArtistCount",
            "MusicVideoCount",
        )
    },
}

#: What a `MusicArtist`'s by-name counts count on a server that models none of it. Seven of the
#: nine, measured `0` on every sampled artist of a library with **real music** rather than of this
#: fixture - which is the reading that makes them constants this server can state truthfully
#: instead of numbers it failed to compute
#: `[probe: tools/probe_real_library_shapes.py, Jellyfin 10.11.11, 2026-09-06]`. The two that count
#: are `AlbumCount` and `SongCount`, and they have emitters of their own.
COUNTS_OF_WHAT_AN_ARTIST_HAS_NONE_OF: frozenset[str] = frozenset(
    {
        "TrailerCount",
        "MovieCount",
        "SeriesCount",
        "ProgramCount",
        "EpisodeCount",
        "ArtistCount",
        "MusicVideoCount",
    }
)

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

#: What `GET /Playlists/{playlistId}/Items` adds on top of a list row, and it is the whole of the
#: difference: the union of a playlist row's property names minus the union of the same items'
#: `/Items` rows is this one name, and the subtraction the other way is empty
#: `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.
#:
#: A fourth tier of one name rather than a member of `GATED`, because it is not asked for: the
#: route sends it unconditionally and no `fields` token reaches it. It is also not in `ALWAYS`,
#: which would put it on every row of every route - measured, an `/Items` row carrying the same
#: track does not have it.
PLAYLIST_EXTRA: frozenset[str] = frozenset({"PlaylistItemId"})

#: What is still unanswerable, named. This was 008's whole gap until T3 filled it; `Chapters` is
#: what is left, because nothing extracts a chapter list and a stub would lie (005 plan section 1).
#: Its emitter yields nothing and a test asserts the absence, so the day something extracts
#: chapters, a failing test changes rather than nothing.
UNPROBED: frozenset[str] = frozenset({"Chapters"})


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


def _backdrop_owner(one: HydratedItem) -> Ancestor | None:
    """The ancestor whose backdrops this row inherits - named once, read by both emitters.

    `ParentBackdropItemId` and `ParentBackdropImageTags` are one fact told twice, and the whole
    point of the id is that a client can build a URL for the tags beside it. Resolving the
    ancestor in two places is how they come to disagree, so they do not: this is the one walk.

    **Nearest, not topmost.** Measured on a track, where the album carries no backdrops and the
    artist does: the id named the `MusicArtist` and its `BackdropImageTags` were the tags on the
    row, on every sampled track `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11,
    2026-08-28]`. No sampled season had backdrops of its own, so an episode's owner was its
    series every time - which is what nearest-first produces, and does not distinguish it from
    topmost-always. The distinction stays unmeasured and is called out here rather than claimed.
    """
    return _first_with(one, ImageKind.BACKDROP)


def _parent_backdrop_tags(one: HydratedItem, ctx: BuildContext) -> list[str] | None:
    if not ctx.enable_images:
        return None
    owner = _backdrop_owner(one)
    if owner is None:
        return None
    return [image.tag for image in owner.images if image.kind is ImageKind.BACKDROP] or None


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


def user_data_dto(one: HydratedItem, ctx: BuildContext) -> UserItemDataDto | None:
    """The `UserData` object, for a row and for a mark response both.

    **Public because 007's mark routes answer exactly this**, and answering it any other way is
    how a mark response and the next list row start disagreeing about the same item
    (007 plan section 6.3). `PlayedPercentage` is position over runtime here, which is the leaf
    reading; a container's is a fraction of children and is gated on `Fields`.
    """
    if not ctx.enable_user_data:
        return None
    data = one.user_data
    percentage: float | None = None
    runtime = one.metadata.runtime_ticks
    if data.total_count is not None:
        # **A container's percentage is a fraction of its children, and it is field-gated.** A
        # bare container row carries `UnplayedItemCount` and `Played` and no percentage at all;
        # asking for `Fields=RecursiveItemCount` is what produces one - measured, and it is the
        # same token that produces the counts beside it
        # `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]`.
        if "RecursiveItemCount" in ctx.fields and data.total_count > 0:
            played_children = data.total_count - (data.unplayed_count or 0)
            percentage = played_children / data.total_count * 100
    elif data.playback_position_ticks > 0 and runtime:
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


#: The two container types whose runtime rollup the reference answers as `0` rather than omitting.
MUSIC_CONTAINERS: frozenset[ItemType] = frozenset({ItemType.MUSIC_ALBUM, ItemType.MUSIC_ARTIST})


def _series_studio(one: HydratedItem) -> str:
    """The **series'** first studio, for a season or an episode, or the empty string.

    A season's series is its parent and an episode's is its grandparent, which is the same two-hop
    shape `SeriesName` already reads. Empty rather than absent where the series carries none: the
    reference answered `""` on all 9 episodes and all 7 seasons of this repository's fixture, whose
    series have no studio, and answered a real one on five sampled episodes of a library that does
    `[probe: tools/probe_real_library_shapes.py, Jellyfin 10.11.11, 2026-09-06]`. That pair of
    readings is what settled it as a derivation rather than the constant it looks like here.
    """
    above = one.grandparent if one.item.type is ItemType.EPISODE else one.parent
    if above is None or above.type is not ItemType.SERIES or not above.studios:
        return ""
    return above.studios[0].name


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


# -- the media properties ------------------------------------------------------------------------
#
# **Eight properties, and only two of them build a wire shape.** `MediaSources` is the expensive
# one and `MediaStreams` is part zero's slice of it; `Container`, `HasSubtitles`, `Width`,
# `Height` and `IsHD` read the stored inspections directly, and `VideoType` reads nothing at all.
# The split is not an optimisation for its own sake: a bare list row carries `Container`,
# `HasSubtitles` and `VideoType` *without* carrying `MediaSources`, so assembling a source to read
# one string off it would build the whole shape for every row of every list. The reference has the
# same split for the same reason - all three are columns on its item.


def _root_of(one: HydratedItem, ctx: BuildContext) -> str | None:
    """The library root a source's absolute path is rebuilt from - `_path`'s rule, shared.

    A library may declare several roots and the schema does not record which one a file came from
    (003 section 3.6), so the first root is the reconstruction, exactly as `Path` does it. The two
    have to agree: a client that compares an item's `Path` with its source's would otherwise see
    two spellings of one file.
    """
    library_id = one.item.library_id
    if library_id is None:
        return None
    library = ctx.libraries.get(library_id)
    if library is None or not library.roots:
        return None
    return library.roots[0]


def _media_sources(one: HydratedItem, ctx: BuildContext) -> list[Any] | None:
    """Every part of the item, with the reading account's playback permissions written on.

    **A listing is the profile-less negotiation's rule, because it is the reference's own
    function.** An item body's `MediaSources` and a `PlaybackInfo` that reaches no stream builder
    are built by one call there `[source: Emby.Server.Implementations/Dto/DtoService.cs:261,
    Emby.Server.Implementations/Library/MediaSourceManager.cs:355-372 @ v10.11.11]`, so the two
    flags a permission moves are read from `media/decision.py` rather than restated here - one
    per media kind, and `SupportsDirectPlay` untouched by all three. Measured across the six
    policy shapes on `GET /Items/{itemId}`, `GET /Items` and `GET /Items/Latest`, on a video item,
    an audio item and a video item nothing had ever inspected - which carries the account's flags
    exactly as an annotated one does `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
    2026-09-02]`.

    The negotiation overwrites both again from its own answer, so an item asked for through
    `PlaybackInfo` is unaffected by what is written here (008 spec section 3.3).
    """
    if not one.item.sources:
        return None
    is_video = one.item.type in VIDEO_TYPES
    sources = media_info.sources_for(one.item, one.probes, _root_of(one, ctx), is_video=is_video)
    for source in sources:
        source.supports_transcoding = unnegotiated_transcoding(ctx.policy, is_video=is_video)
        source.supports_direct_stream = unnegotiated_direct_stream(ctx.policy, is_video=is_video)
    return sources


def _media_streams(one: HydratedItem, ctx: BuildContext) -> list[Any] | None:
    """Part zero's streams, or nothing when nothing has inspected it.

    An empty list rather than absence would be a claim - "this file has no streams" - about a file
    nothing has opened, and the two are not the same answer.
    """
    return media_info.item_streams(one.probes, _root_of(one, ctx)) or None


def _dimension(one: HydratedItem, pick: Callable[[Any], int | None]) -> int | None:
    """`Width` or `Height` of the primary video stream, absent rather than zero.

    The reference emits neither when the number is not positive, which is the same rule as absent
    for a file it never opened `[source: Emby.Server.Implementations/Dto/DtoService.cs:1298-1314
    @ v10.11.11]`.
    """
    stream = media_info.primary_video_stream(one.probes)
    if stream is None:
        return None
    value = pick(stream)
    return value if value else None


EMITTERS: Mapping[str, Callable[[HydratedItem, BuildContext], Any]] = {
    # -- always ----------------------------------------------------------------------------------
    "Id": lambda one, ctx: one.id,
    # -- the playlist row's one extra, considered only when `playlist_row` is set ----------------
    #: **The item's own id, and that is the finding rather than a shortcut.** The field the
    #: reference answers from is a cache of the resolved item's identifier, so the entry
    #: identity 009 was written around is a distinction the wire does not make: equal on every
    #: row measured, and absent from every route but the playlist one (009 spec section 3.1)
    #: `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    "PlaylistItemId": lambda one, ctx: one.id,
    # -- always, continued -----------------------------------------------------------------------
    "ServerId": lambda one, ctx: ctx.server_id,
    "Name": lambda one, ctx: one.item.name,
    "Type": lambda one, ctx: one.item.type.value,
    #: The **stored** value when the row has one, and the type-level map otherwise.
    #:
    #: Only a playlist has one. Measured, the reference decides a playlist's media type at
    #: creation and never revises it - a playlist created empty answers `Audio` after a film is
    #: added to it, one created from a film answers `Video` after a track is, and the create
    #: body's own `MediaType` outranks the contents outright
    #: `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`. So
    #: `MEDIA_TYPE_OF[Playlist]` is exact for a playlist created empty and wrong for every other,
    #: which is why 009 stores the value per row (009 plan section 4.2) and this reads it.
    "MediaType": lambda one, ctx: one.media_type or MEDIA_TYPE_OF[one.item.type],
    #: Absent for a by-name row - the reference sends no `IsFolder` for a genre, a music genre or
    #: a year, list row and full body alike
    #: `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    "IsFolder": lambda one, ctx: (
        None if one.item.type in BY_NAME else one.item.type not in FILE_BACKED
    ),
    "LocationType": lambda one, ctx: "FileSystem",
    #: Always None; `BaseItemDto.NULL_KEPT` turns that into the measured explicit null.
    "ChannelId": lambda one, ctx: None,
    "UserData": user_data_dto,
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
    "SeasonName": lambda one, ctx: (
        one.parent.name if one.item.type is ItemType.EPISODE and one.parent else None
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
    "ParentBackdropItemId": lambda one, ctx: (
        getattr(_backdrop_owner(one), "id", None) if ctx.enable_images else None
    ),
    "ParentBackdropImageTags": _parent_backdrop_tags,
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
    "Container": lambda one, ctx: media_info.item_container(one.item, one.probes),
    #: `true` or absent, never `false` - the reference sets the property only when it holds.
    "HasSubtitles": lambda one, ctx: media_info.has_subtitles(one.probes) or None,
    "VideoType": lambda one, ctx: media_info.VIDEO_FILE,
    # -- the wide widths only ---------------------------------------------------------------------
    #: A file to fetch and an account permitted to fetch it. A folder is not downloadable on
    #: either server, whatever the policy says.
    "CanDownload": lambda one, ctx: ctx.access.downloading and one.item.type in FILE_BACKED,
    #: A server-wide display switch this server has no knob for, at the reference's default.
    "EnableMediaSourceDisplay": lambda one, ctx: True,
    #: Zero, and it is a count of what this server holds rather than a stand-in for one it does
    #: not: 003 discovers no local trailer and 004 stores no remote one, so both are exact.
    "LocalTrailerCount": lambda one, ctx: 0,
    "RemoteTrailers": lambda one, ctx: [],
    # Three constants, and each is a statement this server can make truthfully: no provider in v1
    # supplies a production location or a broadcast day, and trickplay tiles are images this
    # server does not generate at all. That is the difference from `HasLyrics`, which the same
    # tranche left alone - `false` there would deny lyrics sitting in an `.lrc` beside the track
    # (005 tasks, cause 4).
    "ProductionLocations": lambda one, ctx: [],
    **{name: (lambda one, ctx: 0) for name in COUNTS_OF_WHAT_AN_ARTIST_HAS_NONE_OF},
    "AirDays": lambda one, ctx: [],
    "Trickplay": lambda one, ctx: {},
    #: Nothing in v1 locks a field against the next rescan - 004 T10 measured the scan and the
    #: refresh already fighting over one column, and neither of them consults a lock - so there
    #: is no locked field to name and nothing is locked.
    "LockData": lambda one, ctx: False,
    "LockedFields": lambda one, ctx: [],
    #: `Full` or `None`. The reference answers the enum from the account's `EnableMediaPlayback`
    #: alone; it does not consult the item.
    "PlayAccess": lambda one, ctx: PLAY_ACCESS_FULL if ctx.access.playback else PLAY_ACCESS_NONE,
    #: Zero, for `LocalTrailerCount`'s reason: v1 models no extras at all.
    "SpecialFeatureCount": lambda one, ctx: 0,
    # -- gated -----------------------------------------------------------------------------------
    "MediaSources": _media_sources,
    "MediaStreams": _media_streams,
    "Chapters": lambda one, ctx: None,  # the last unprobed one; see UNPROBED
    "Width": lambda one, ctx: _dimension(one, lambda stream: stream.width),
    "Height": lambda one, ctx: _dimension(one, lambda stream: stream.height),
    #: Same shape as `HasSubtitles`: `true` or absent.
    "IsHD": lambda one, ctx: media_info.is_hd(one.probes) or None,
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
    # **`0` is a value on a music container and an absence everywhere else.** The `or None` below
    # is what kept this field off an album and an artist whose tracks have no readable duration -
    # every album of this repository's fixture - where the reference answers `0`. Measured on a
    # library with real music, the same field is the exact sum of that album's tracks, so it is a
    # rollup rather than a constant `[probe: tools/probe_real_library_shapes.py, Jellyfin 10.11.11,
    # 2026-09-06]`; both readings are the same rule, and only the empty case told them apart.
    "CumulativeRunTimeTicks": lambda one, ctx: _aggregate(
        one,
        ctx,
        lambda numbers: (
            numbers.cumulative_runtime_ticks
            if one.item.type in MUSIC_CONTAINERS
            else (numbers.cumulative_runtime_ticks or None)
        ),
    ),
    # The series' studio, not the item's. Empty string where the series has none, which is what the
    # reference answers rather than omitting the property (005 §3.2).
    "SeriesStudio": lambda one, ctx: _series_studio(one),
    "AlbumCount": lambda one, ctx: _aggregate(
        one, ctx, lambda numbers: numbers.children_by_type.get(ItemType.MUSIC_ALBUM.value, 0)
    ),
    # A song under an artist is a file under it, which is what the recursive rollup already counts:
    # every file-backed descendant of a music artist is a track.
    "SongCount": lambda one, ctx: _aggregate(one, ctx, lambda numbers: numbers.recursive_count),
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
    if ctx.playlist_row:
        named = named | PLAYLIST_EXTRA
    wide_per_type = frozenset(name for name, types in WIDE_PER_TYPE.items() if item_type in types)
    if ctx.width is Width.FULL:
        return named | frozenset(GATED) | WIDE_ONLY | wide_per_type
    gated = frozenset(name for name, token in GATED.items() if token in ctx.fields)
    if ctx.width is Width.USER_VIEW:
        return named | gated | USER_VIEW_EXTRAS | WIDE_ONLY | wide_per_type
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
    "PLAYLIST_EXTRA",
    "PLAY_ACCESS_FULL",
    "PLAY_ACCESS_NONE",
    "UNPROBED",
    "USER_VIEW_EXTRAS",
    "VIDEO_TYPES",
    "WIDE_ONLY",
    "BuildContext",
    "ItemAccess",
    "LibraryContext",
    "Width",
    "build_dto",
    "build_dtos",
    "dto_values",
    "user_data_dto",
]
