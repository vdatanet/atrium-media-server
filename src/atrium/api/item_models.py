# SPDX-License-Identifier: GPL-3.0-or-later
"""The item surface: the four response shapes 005 serves, as models.

Everything a query endpoint returns is built from what is here - `BaseItemDto` and the three-field
envelope for eleven of the routes, the bare array of `/Items/Latest` (a `list[BaseItemDto]`, so it
needs no model), the filter summary of `/Items/Filters`, and the hint envelope of `/Search/Hints`
(plan section 6.6). Route modules choose among them; nothing here knows a route exists.

**Field order is the reference document's, on purpose.** Pydantic serialises in declaration order
and the reference serialises in its own property order, so declaring these in the pinned
document's order costs nothing now and spares every byte-level comparison later from a wall of
reordered-key noise. `[spec: BaseItemDto, UserItemDataDto, SearchHint]`

**The media properties arrived with 008 T3**, which is what the gap here was waiting for:
`MediaSources`, `MediaStreams`, `Container`, `Width`, `Height`, `HasSubtitles`, `IsHD` and
`VideoType` are all answers about what a file contains, and inspection now stores that. `Chapters`
is the one that stayed behind - nothing extracts a chapter list, and a plausible-looking stub
would violate "it never lies" (005 plan section 1), so its field is still undeclared and its
emitter still yields nothing.

`ChannelId` is the one field that survives null-suppression: the reference emits it as an
explicit `null` on every item of every response, measured against its own configuration saying
otherwise (behaviours section 1.7). `NULL_KEPT` on the model is the mechanism.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from atrium.compat.dates import WireDateTime
from atrium.compat.model import AtriumModel
from atrium.compat.ticks import WireTicks
from atrium.media.info import MediaSourceInfo, MediaStream


class UserItemDataDto(AtriumModel):
    """The requesting user's state, present on every tree item (behaviours section 2.1).

    `Key` and `ItemId` are both the item's derived identity (plan section 5). For a container,
    `Played` and `UnplayedItemCount` are a statement about the subtree, not this row - see
    `domain.playstate.UserItemData`. The declared set is exactly the union a live 10.11.11 was
    measured sending; `Rating` and `Likes` exist on the reference's schema and are 007's to emit
    when user ratings exist to report.
    `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`
    """

    played_percentage: float | None = None
    unplayed_item_count: int | None = None
    playback_position_ticks: WireTicks = 0
    play_count: int = 0
    is_favorite: bool = False
    last_played_date: WireDateTime | None = None
    played: bool = False
    key: str
    item_id: str


class NameGuidPair(AtriumModel):
    """A related name and the row it merges into - `GenreItems`, `Studios`, `AlbumArtists`.

    `Id` is absent for the one case 004 made nullable: a track performer who is nobody's album
    artist has a name a client renders and no item to click through to (behaviours section 5.3).
    """

    name: str
    id: str | None = None


class MediaUrl(AtriumModel):
    """A trailer address and its label - `RemoteTrailers`' element type `[spec: BaseItemDto]`.

    Declared rather than approximated because the property is a list and a list has an element
    type even when it is always empty here: 004 stores no remote trailer, so nothing ever fills
    one, and a `list[str]` would be a different shape the day something does.
    """

    url: str
    name: str | None = None


class BaseItemPerson(AtriumModel):
    """One person on one item: who, playing whom, in what capacity."""

    name: str
    id: str | None = None
    role: str | None = None
    type: str | None = None


class ExternalUrl(AtriumModel):
    """A link a client offers beside an item - "IMDb", "TMDB", the MusicBrainz family."""

    name: str
    url: str


class BaseItemDto(AtriumModel):
    """One item on the wire, whichever of the three widths the route calls for.

    Which fields are *set* is `api.item_dto`'s decision, driven by the registry and the call
    site's shape (spec section 3.2): the model declares the union and an unset field is absent.
    """

    #: `ChannelId` is always emitted and always null - the measured exception to behaviours
    #: section 1.7, and the reason `NULL_KEPT` exists on the base model.
    NULL_KEPT: ClassVar[frozenset[str]] = frozenset({"ChannelId"})

    name: str | None = None
    original_title: str | None = None
    server_id: str | None = None
    id: str
    #: **Immediately after `Id`, and equal to it** - the measured wire position and the measured
    #: value, on a route that is the only one to send the property at all: a `/Items` row carrying
    #: the same track has thirty properties and this is not one of them
    #: `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`. Declared here rather
    #: than on a subclass because the position is part of the contract and a subclass's own fields
    #: serialise last; which rows *set* it is `api.item_dto`'s decision, as for every other name.
    #: 009 spec section 3.1 is why the value is not an identifier of its own.
    playlist_item_id: str | None = None
    etag: str | None = None
    date_created: WireDateTime | None = None
    date_last_media_added: WireDateTime | None = None
    #: Whether the effective user may delete this item and download its file. Both are the
    #: account's policy **and** a property of the item: a library root answers `false` to both to
    #: an administrator who may do either, and a film answers the policy
    #: `[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-03]`. `CanDelete` is
    #: not emitted here - see the note in `api/item_dto.py`.
    can_download: bool | None = None
    #: Emitted only when true, which is the reference's own shape - a video with no subtitle
    #: stream carries no property rather than `false`
    #: `[source: Emby.Server.Implementations/Dto/DtoService.cs:1107-1110 @ v10.11.11]`.
    has_subtitles: bool | None = None
    #: **The item-level container is not always one container.** It is the reference's normalised
    #: demuxer string - `mkv` for a Matroska file, the whole `mov,mp4,m4a,3gp,3g2,mj2` for every
    #: member of the mp4 family - and the single name a *media source* reports is derived from it
    #: per response (008 spec section 3.1, AC-28).
    container: str | None = None
    sort_name: str | None = None
    premiere_date: WireDateTime | None = None
    external_urls: list[ExternalUrl] | None = None
    media_sources: list[MediaSourceInfo] | None = None
    path: str | None = None
    #: Position 29 of the pinned document, between `Path` and `OfficialRating`. Always `true`
    #: here: it is a server-wide display switch the reference defaults on and Atrium has no knob
    #: for `[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-03]`.
    enable_media_source_display: bool | None = None
    official_rating: str | None = None
    channel_id: str | None = None
    overview: str | None = None
    taglines: list[str] | None = None
    genres: list[str] | None = None
    community_rating: float | None = None
    cumulative_run_time_ticks: WireTicks | None = None
    run_time_ticks: WireTicks | None = None
    #: `Full` or `None`, following the account's `EnableMediaPlayback` - measured both ways
    #: `[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-03]`.
    play_access: str | None = None
    production_year: int | None = None
    index_number: int | None = None
    parent_index_number: int | None = None
    #: Always empty: 004 stores no remote trailer, so there is none to name.
    remote_trailers: list[MediaUrl] | None = None
    provider_ids: dict[str, str] | None = None
    #: Emitted only when true, like `HasSubtitles`: the reference sets it on nothing shorter than
    #: 720 lines and leaves the property absent otherwise
    #: `[source: Emby.Server.Implementations/Dto/DtoService.cs:1316-1323 @ v10.11.11]`.
    is_hd: bool | None = None
    is_folder: bool | None = None
    parent_id: str | None = None
    type: str
    people: list[BaseItemPerson] | None = None
    studios: list[NameGuidPair] | None = None
    genre_items: list[NameGuidPair] | None = None
    #: Before the tags it pairs with, which is the pinned document's own order - and the two are
    #: emitted from one ancestor walk, so they can never name different items (006 spec section
    #: 3.1). `ParentLogoItemId` sits between them upstream and stays out here (Principle VI).
    parent_backdrop_item_id: str | None = None
    parent_backdrop_image_tags: list[str] | None = None
    #: Always `0`: 003 discovers no local trailer, so the count of what this server holds is
    #: exactly zero rather than a stand-in.
    local_trailer_count: int | None = None
    user_data: UserItemDataDto | None = None
    recursive_item_count: int | None = None
    child_count: int | None = None
    series_name: str | None = None
    series_id: str | None = None
    season_id: str | None = None
    #: Always `0`, for `LocalTrailerCount`'s reason: v1 models no extras at all.
    special_feature_count: int | None = None
    tags: list[str] | None = None
    primary_image_aspect_ratio: float | None = None
    artists: list[str] | None = None
    artist_items: list[NameGuidPair] | None = None
    album: str | None = None
    collection_type: str | None = None
    album_id: str | None = None
    album_primary_image_tag: str | None = None
    series_primary_image_tag: str | None = None
    album_artist: str | None = None
    album_artists: list[NameGuidPair] | None = None
    season_name: str | None = None
    #: The **first** source's streams, which is the reference's own rule: the item-level list is
    #: the streams of the source whose id is the item's
    #: `[source: Emby.Server.Implementations/Dto/DtoService.cs:1151-1170 @ v10.11.11]`.
    media_streams: list[MediaStream] | None = None
    video_type: str | None = None
    image_tags: dict[str, str] | None = None
    backdrop_image_tags: list[str] | None = None
    series_thumb_image_tag: str | None = None
    image_blur_hashes: dict[str, dict[str, str]] | None = None
    parent_thumb_item_id: str | None = None
    parent_thumb_image_tag: str | None = None
    location_type: str | None = None
    media_type: str
    #: Always empty, and `LockData` always `false`: nothing in v1 locks a field against a
    #: rescan, so there is no locked field to name. Positions 109 and 119 of the pinned document,
    #: which is why they sit either side of nothing and immediately before `Width`.
    locked_fields: list[str] | None = None
    lock_data: bool | None = None
    #: Last, because the pinned document puts them last - after `LockData`. Both are the primary
    #: video stream's, and both are absent rather than zero when the
    #: item has no video `[source: Emby.Server.Implementations/Dto/DtoService.cs:1298-1314 @
    #: v10.11.11]`.
    width: int | None = None
    height: int | None = None


class UserViewDto(BaseItemDto):
    """A `/UserViews` row: the same item surface, one more explicit null.

    The reference sends `"ParentId": null` on a view row that hangs off nothing - measured on the
    rows whose parent is absent, where every other route simply omits the property
    `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`. Atrium's views all hang
    off nothing (there is no user root folder item), so the null travels on every row - the same
    mechanism as `ChannelId`, scoped to the one route whose shape carries it.
    """

    NULL_KEPT: ClassVar[frozenset[str]] = frozenset({"ChannelId", "ParentId"})


class BaseItemDtoQueryResult(AtriumModel):
    """The three-field envelope every list endpoint returns except the two that do not.

    `StartIndex` is present - the reference includes it where Emby does not (behaviours
    section 1.5) - and `TotalRecordCount` is the pre-paging count, or the honest `0` when the
    caller switched counting off (plan section 6.6).
    """

    items: list[BaseItemDto] = Field(default_factory=list)
    total_record_count: int = 0
    start_index: int = 0


class UserViewQueryResult(AtriumModel):
    """The envelope again, typed to the view row - a sibling, not a subclass.

    Not cosmetic: pydantic serialises a nested model by the **declared** field's schema, so a
    `UserViewDto` inside `list[BaseItemDto]` would serialise with the base class's `NULL_KEPT`
    and the measured `ParentId` null would quietly vanish. The field type is the mechanism, and
    a subclass could not narrow it - a `list` field is invariant, and mypy is right to say so.
    """

    items: list[UserViewDto] = Field(default_factory=list)
    total_record_count: int = 0
    start_index: int = 0


class QueryFiltersLegacy(AtriumModel):
    """`/Items/Filters`: the distinct values a scope offers to filter by (plan section 6.6)."""

    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    official_ratings: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)


class SearchHint(AtriumModel):
    """One search hit, flattened - **not** an item (spec section 3.10, AC-14).

    The declared set and its order are the measured wire: `Artists` travels on **every** hint,
    empty list included, and `ChannelId` is the same explicit null every item body carries.
    `MatchedTerm` stays declared and was **never observed** - seventeen hints across three terms
    arrived without it - so nothing here emits it; the spec records the contradiction.
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`
    """

    NULL_KEPT: ClassVar[frozenset[str]] = frozenset({"ChannelId"})

    item_id: str
    id: str
    name: str
    matched_term: str | None = None
    index_number: int | None = None
    production_year: int | None = None
    parent_index_number: int | None = None
    primary_image_tag: str | None = None
    thumb_image_tag: str | None = None
    thumb_image_item_id: str | None = None
    backdrop_image_tag: str | None = None
    backdrop_image_item_id: str | None = None
    type: str
    is_folder: bool | None = None
    run_time_ticks: WireTicks | None = None
    media_type: str | None = None
    series: str | None = None
    album: str | None = None
    album_id: str | None = None
    album_artist: str | None = None
    artists: list[str] = Field(default_factory=list)
    song_count: int | None = None
    episode_count: int | None = None
    channel_id: str | None = None
    primary_image_aspect_ratio: float | None = None


class SearchHintResult(AtriumModel):
    """The fourth shape: `{SearchHints, TotalRecordCount}` and nothing else."""

    search_hints: list[SearchHint] = Field(default_factory=list)
    total_record_count: int = 0


__all__ = [
    "BaseItemDto",
    "BaseItemDtoQueryResult",
    "BaseItemPerson",
    "ExternalUrl",
    "MediaUrl",
    "NameGuidPair",
    "QueryFiltersLegacy",
    "SearchHint",
    "SearchHintResult",
    "UserItemDataDto",
    "UserViewDto",
    "UserViewQueryResult",
]
