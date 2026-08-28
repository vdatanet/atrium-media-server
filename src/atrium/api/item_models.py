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

**What is deliberately not declared.** `MediaSources`, `MediaStreams`, `Chapters`, `Width` and
`Height` are in the gated registry with emitters that yield nothing - they describe what probing
a file finds, 008 owns probing, and a plausible-looking stub would violate "it never lies"
(plan section 1). Leaving the fields undeclared makes the gap structural: nothing can emit them
by accident, and 008 adds the fields in the change that makes them true.

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


class UserItemDataDto(AtriumModel):
    """The requesting user's state, present on every tree item (behaviours section 2.1).

    `Key` and `ItemId` are both the item's derived identity (plan section 5). For a container,
    `Played` and `UnplayedItemCount` are a statement about the subtree, not this row - see
    `db.item_queries.UserItemData`. The declared set is exactly the union a live 10.11.11 was
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
    etag: str | None = None
    date_created: WireDateTime | None = None
    date_last_media_added: WireDateTime | None = None
    sort_name: str | None = None
    premiere_date: WireDateTime | None = None
    external_urls: list[ExternalUrl] | None = None
    path: str | None = None
    official_rating: str | None = None
    channel_id: str | None = None
    overview: str | None = None
    taglines: list[str] | None = None
    genres: list[str] | None = None
    community_rating: float | None = None
    cumulative_run_time_ticks: WireTicks | None = None
    run_time_ticks: WireTicks | None = None
    production_year: int | None = None
    index_number: int | None = None
    parent_index_number: int | None = None
    provider_ids: dict[str, str] | None = None
    is_folder: bool | None = None
    parent_id: str | None = None
    type: str
    people: list[BaseItemPerson] | None = None
    studios: list[NameGuidPair] | None = None
    genre_items: list[NameGuidPair] | None = None
    parent_backdrop_image_tags: list[str] | None = None
    user_data: UserItemDataDto | None = None
    recursive_item_count: int | None = None
    child_count: int | None = None
    series_name: str | None = None
    series_id: str | None = None
    season_id: str | None = None
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
    image_tags: dict[str, str] | None = None
    backdrop_image_tags: list[str] | None = None
    series_thumb_image_tag: str | None = None
    image_blur_hashes: dict[str, dict[str, str]] | None = None
    parent_thumb_item_id: str | None = None
    parent_thumb_image_tag: str | None = None
    location_type: str | None = None
    media_type: str


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

    `ItemId` and `Id` are both set; `MatchedTerm` is what matched, so a client can highlight it.
    The declared set is spec section 3.10's; T15 measures which of them a live server actually
    sends and amends there.
    """

    item_id: str
    id: str
    name: str
    matched_term: str | None = None
    primary_image_tag: str | None = None
    thumb_image_tag: str | None = None
    backdrop_image_tag: str | None = None
    type: str
    is_folder: bool | None = None
    run_time_ticks: WireTicks | None = None
    media_type: str | None = None
    series: str | None = None
    album: str | None = None
    album_artist: str | None = None
    song_count: int | None = None
    episode_count: int | None = None


class SearchHintResult(AtriumModel):
    """The fourth shape: `{SearchHints, TotalRecordCount}` and nothing else."""

    search_hints: list[SearchHint] = Field(default_factory=list)
    total_record_count: int = 0


__all__ = [
    "BaseItemDto",
    "BaseItemDtoQueryResult",
    "BaseItemPerson",
    "ExternalUrl",
    "NameGuidPair",
    "QueryFiltersLegacy",
    "SearchHint",
    "SearchHintResult",
    "UserItemDataDto",
    "UserViewDto",
    "UserViewQueryResult",
]
