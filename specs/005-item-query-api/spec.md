---
feature: 005-item-query-api
title: Item query API
status: Accepted
created: 2026-08-26
updated: 2026-08-27
accepted: 2026-08-27
depends_on: [002, 004]
---

# 005 — Item query API

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Let a client browse and search the library: list items, filter and sort them, page through them,
and fetch one in full.

This is the largest feature in v1 — seventeen endpoints, and one of them (`/Items`) is the endpoint
every client uses for almost everything. Getting the response shape right here decides whether
anything a client displays is correct.

**Client behaviour unlocked:** every screen except playback.

## 2. Scope

**In scope**

- `GET /Items`, `GET /Items/{itemId}`, `GET /UserViews`.
- `GET /Items/Latest`, `GET /Items/Filters`, `GET /Items/{itemId}/Similar`,
  `GET /Items/{itemId}/InstantMix`, `GET /UserItems/Resume`.
- `GET /Shows/{seriesId}/Seasons`, `GET /Shows/{seriesId}/Episodes`, `GET /Shows/NextUp`.
- `GET /Artists`, `GET /Artists/AlbumArtists`, `GET /Genres`, `GET /MusicGenres`, `GET /Years`.
- `GET /Search/Hints`.
- The item representation, its optional fields, and the list envelope.

**Out of scope**

- Writing: no item creation, update or deletion here. Playlist mutation is 009; deletion of a
  playlist goes through 009's use of `DELETE /Items/{itemId}`.
- User-data mutation — 007.
- Image bytes — 006. This feature emits image *tags*; 006 serves what they identify.
- Media sources and streams beyond echoing what 008 produced.
- Collections/box sets, Live TV, channels, `/Studios`, `/Persons` as endpoints.

## 3. Behaviour

### 3.1 The list envelope

Every list endpoint except `/Items/Latest` and `/Items/Filters` returns:

```json
{ "Items": [ ], "TotalRecordCount": 0, "StartIndex": 0 }
```

`StartIndex` is present — the reference includes it where Emby does not.

**`GET /Items/Latest` returns a bare array**, not this envelope. A client decoding it as an
envelope gets nothing, so this asymmetry is load-bearing rather than cosmetic.

**Measured, not assumed.** All twelve list endpoints of the v1 surface were probed against a live
reference: ten return the envelope with `StartIndex` present, `/Items/Latest` returns a bare
array, `/Items/Filters` returns `{Genres, Tags, OfficialRatings, Years}`, and `/Search/Hints`
returns `{SearchHints, TotalRecordCount}` — four shapes, and Atrium reproduces each per endpoint
rather than normalising them. `[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-26]`

**Paging** is `StartIndex` and `Limit` on the request. `TotalRecordCount` is the count *before*
paging, so a client can size a scrollbar.

### 3.2 The item representation

**There is not one representation. There are three**, and which one a client gets depends on the
route it asked, not on the item type.
`[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`

| Route | What comes back |
|---|---|
| A list row | The narrow shape below: always-present, plus what the type has, plus whatever `Fields` asked for |
| A single item by id | **Everything**, unasked. `Fields` has nothing left to add |
| The user's views | A third shape: as wide as a full body, unasked, for library roots |

Items are discriminated by `Type` (`Movie`, `Series`, `Season`, `Episode`, `MusicArtist`,
`MusicAlbum`, `Audio`, `Playlist`, `CollectionFolder`, `UserView`, `Folder`).

**Always present**, on every item, in every list:

| Field | Notes |
|---|---|
| `Id`, `ServerId`, `Name`, `Type` | |
| `MediaType` | `Video`, `Audio` or `Unknown` |
| `IsFolder` | |
| `LocationType` | `FileSystem` for everything v1 serves |
| `ChannelId` | **Always, and always `null`** — the one property that survives the null-omission of [behaviours §1.7](../../docs/compatibility/behaviours.md#17-a-null-property-is-absent-everywhere-by-one-setting) |
| `UserData` | **Always**, with no `Fields` or `EnableUserData` needed. Jellyfin's version carries `Key` and `ItemId` inside it `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` |
| `ImageTags` | Empty object when the item has no images |
| `ImageBlurHashes` | `ImageTags`' shape again, a BlurHash per image id. A client rendering placeholders reads it |
| `BackdropImageTags` | |

**Present in a list row when the item type has them:**

| Group | Fields |
|---|---|
| Common | `ProductionYear`, `PremiereDate`, `RunTimeTicks`, `OfficialRating`, `CommunityRating` |
| Episode | `IndexNumber`, `ParentIndexNumber`, `SeriesId`, `SeriesName`, `SeasonId`, `SeriesPrimaryImageTag`, `SeriesThumbImageTag`, `ParentThumbItemId`, `ParentThumbImageTag`, `ParentBackdropImageTags` |
| Season, Series | `ChildCount`, `IndexNumber` |
| Audio | `Album`, `AlbumId`, `AlbumArtist`, `AlbumArtists`, `AlbumPrimaryImageTag`, `Artists`, `ArtistItems`, `IndexNumber` (track), `ParentIndexNumber` (disc) |
| Library roots | `CollectionType` |
| Playlist entries | `PlaylistItemId` — see 009 |

**Only when a list row asks for them:** `MediaSources`, `MediaStreams`, `Path`, `Etag`,
`Chapters`, `DateCreated`, `DateLastMediaAdded`, `ProviderIds`, `Tags`, `Taglines`, `ExternalUrls`,
`OriginalTitle`, `ParentId`, `CumulativeRunTimeTicks`, `RecursiveItemCount`, `ChildCount`,
**`SortName`, `Overview`, `Genres`, `GenreItems`, `Studios`, `People`,
`PrimaryImageAspectRatio`**, `Width`, `Height`. `[spec: ItemFields]`

> **`SeriesThumbImageTag` was not observed at all** — not bare, not asked for, not in a full body,
> across twelve episodes. Whether it is gated, or simply absent because none of those episodes'
> series carries a Thumb, cannot be told apart from outside: a null property is omitted. It stays
> in the table, unconfirmed, rather than being deleted on one library's evidence.

> **The seven in bold were in the per-type group until they were measured**, and six of them are
> requestable tokens — which is what made the row wrong, because a token is gated by definition. A
> list of movies carries no overview, no genres, no cast and no aspect ratio unless the client
> asks. `PrimaryImageAspectRatio` is the one with a dependency behind it: 004 supplies the width
> and height it is computed from, and a list row still does not carry it.
> `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`

**Where this field set comes from.** It is the union of what the two analysed clients actually read
from a response, not the reference's full representation, which has over 150 properties. A field no
client reads is not observable, and Principle VI applies to fields as it does to endpoints.
Emitting the full set would mean specifying and testing a hundred fields whose correctness nobody
can check.

**The single-item route is the exception to that**, and it is not a choice: the reference emits
everything there whatever the request says, so a narrow answer is observable as a missing field
rather than as a smaller one. What v1 emits from it is the union above, and the differential
harness is what closes the rest.

> ⚠️ **This is a known, bounded delta.** A different client reading a field Atrium omits sees it as
> absent. The mitigation is measurement, not guessing: the differential harness (010) reports every
> field the reference sends that Atrium does not, and each gets added or explicitly declined.

### 3.3 `GET /Items` — `GetItems`

**Consumers:** music-client, video-client. The endpoint everything else is built on.

The reference declares **86 query parameters**. `[spec: GetItems]` v1 implements them in two tiers,
and refuses to pretend about the third.

**Tier 1 — observed in use, required.**

| Parameter | Effect |
|---|---|
| `userId` | Whose user data and visibility apply |
| `parentId` | Children of one container |
| `recursive` | Descend the whole subtree rather than one level |
| `startIndex`, `limit` | Paging |
| `sortBy`, `sortOrder` | Ordering; §3.4 |
| `fields` | Optional fields from §3.2 |
| `includeItemTypes` | Restrict by `Type` |
| `searchTerm` | Name match |
| `ids` | Fetch a specific set |
| `albumArtistIds` | Music navigation |
| `filters` | `IsFavorite`, `IsPlayed`, `IsUnplayed`, `IsResumable` |
| `isPlayed` | Played state |

**Tier 2 — implemented by design**, because they are cheap, they are the obvious next thing a
client asks for, and a filter that silently does nothing is worse than one that does not exist:
`excludeItemTypes`, `excludeItemIds`, `mediaTypes`, `isFavorite`, `genres`, `genreIds`, `years`,
`studioIds`, `artistIds`, `albumIds`, `personIds`, `nameStartsWith`, `nameStartsWithOrGreater`,
`nameLessThan`, `minCommunityRating`, `enableUserData`, `enableImages`, `imageTypeLimit`,
`enableImageTypes`, `enableTotalRecordCount`.

**Tier 3 — not implemented in v1.** The remaining parameters, covering Live TV, 3D, parental
ratings, adjacency, resolution bounds, air dates and provider-id presence.

**What happens when a Tier 3 parameter arrives** is a real decision, not an oversight, and neither
available answer is free:

- *Ignore it silently* — the client receives more items than it asked for and shows the user wrong
  results, with nothing to indicate why.
- *Reject with `400`* — the reference answers `200`, so this is itself a delta, and it breaks a
  client that sends a parameter harmlessly.

**v1 ignores the parameter and records it.** Rejecting turns a partial answer into no answer, which
is worse for the client and further from the reference. Every ignored Tier 3 parameter is counted
and reported, so the set that real clients actually send becomes measurable — and anything that
shows up gets promoted to Tier 2. This is the one place in v1 where a delta is accepted knowingly,
with a mechanism attached for closing it.

**Errors:** `401` unauthenticated. `parentId` naming an unknown or invisible item is `404`. An
unrecognised **token** in an enum-valued parameter is ignored, never rejected — the filter simply
drops, measured across `includeItemTypes`, `sortBy`, `fields` and `filters`
(behaviours §1.12) `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`. A value that cannot
parse as its declared **type** — `limit=abc`, a malformed identifier — is `400`, in the
problem-details shape of behaviours §1.11 `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`.
This spec previously claimed the first case was a `400`; it is not, and treating it as one would
have refused requests the reference serves.

### 3.4 Sorting

`sortBy` accepts `SortName`, `DateCreated`, `PremiereDate`, `PlayCount`, `DatePlayed`, `Random`,
`AlbumArtist`, `Artist`, and combinations, with `sortOrder` of `Ascending` or `Descending`.
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

Three rules make ordering reproducible:

1. **`SortName` uses the normalisation from 003 §3.7** — articles, diacritics, case, numeric
   prefixes. This is where ordering parity is won or lost, because it affects every list.
2. **Ordering is total.** After the requested keys — and after the name, which the reference
   chains behind a `SortName` ordering — ties break on the item id, so paging cannot show an item
   twice or skip one. **The reference's ordering is not total, and what that costs is measured**:
   its movie sorts arrive stable with ties in ascending id order, but under `AlbumArtist` and
   `Artist` the concatenation of a query's pages is **not** the one-shot list — a client paging a
   large audio library sees some items twice and never sees others
   `[probe: tools/probe_sort_stability.py, Jellyfin 10.11.11, 2026-08-27]`. Totality is therefore
   a deliberate divergence from a defect, argued in
   [behaviours §3.6](../../docs/compatibility/behaviours.md#36-ties-are-engine-resolved-and-paging-the-artist-sorts-loses-rows--class-b-diverged):
   within any tie Atrium's order is one the reference could have produced, and on the movie sorts
   it is the very order the measured server does produce.
3. **`Random` is seeded per request** and the seed is not exposed, so paging through a random
   ordering is not meaningful. Observably the reference's behaviour: a fresh shuffle on every
   request — two identical 97-row requests shared 4 items
   `[probe: tools/probe_sort_stability.py, Jellyfin 10.11.11, 2026-08-27]` — and clients use it
   for a single page.

Two further ordering behaviours, read from the source and reproduced:

- **An item with no `PremiereDate` sorts by January 1 of its `ProductionYear`** under
  `sortBy=PremiereDate`, rather than clumping with the dateless
  `[source: Jellyfin.Server.Implementations/Item/OrderMapper.cs:49 @ v10.11.11]`.
- **A request carrying `searchTerm` is ordered by match quality first** — exact match, then
  prefix at a word boundary, then prefix, then contains — ahead of whatever `sortBy` asked for
  `[source: Jellyfin.Server.Implementations/Item/BaseItemRepository.cs:1604-1611 @ v10.11.11]`
  `[source: Jellyfin.Server.Implementations/Item/OrderMapper.cs:76-93 @ v10.11.11]`.

### 3.5 `GET /Items/{itemId}` — `GetItem`

**Consumers:** music-client, video-client.

One item in full. **This is the Jellyfin route**; the Emby dialect's
`/Users/{userId}/Items/{itemId}` was removed in 10.11 and Atrium does not serve it
([ADR-0004](../../docs/decisions/0004-pin-to-jellyfin-10-11.md)).

`404` for unknown or invisible items — the same answer for both, so the endpoint does not disclose
the existence of items a user may not see. The `404` carries the problem-details shape of
behaviours §1.11, as does the `400` for an identifier that does not parse at all: which of the two
a caller gets depends only on whether the id is *shaped* like an id
`[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`.

### 3.6 `GET /UserViews` — `GetUserViews`

The libraries as this user sees them, after policy (002 §3.5). Each carries `CollectionType`, which
tells the client which navigation to offer.

A user with no permitted libraries gets an empty envelope, not an error.

### 3.7 Discovery endpoints

| Endpoint | Returns | Rule that matters |
|---|---|---|
| `GET /Items/Latest` | **Bare array** of recently added items | Honours the user's latest-items exclusions from 002 §3.6 |
| `GET /UserItems/Resume` | Items with a resume position | Ordered most-recently-played first; excludes items played past the completion threshold (007 §3.7) |
| `GET /Shows/NextUp` | The next unwatched episode per series | One item per series, never several |
| `GET /Items/{itemId}/Similar` | Related items | v1 scores on shared genres, people and studios. Deterministic |
| `GET /Items/{itemId}/InstantMix` | A radio-style queue from a seed | Deterministic for a given seed and library |
| `GET /Items/Filters` | `{Genres, Tags, OfficialRatings, Years}` for a parent | `[spec: QueryFiltersLegacy]` |

**Similar and InstantMix are deterministic on purpose.** The reference's are not obviously so, and
a non-deterministic endpoint cannot be tested at L2 or compared at L3. Determinism is invisible to a
client — it cannot tell a stable ranking from a lucky one — so this costs nothing under Principle I.

### 3.8 Series navigation

`GET /Shows/{seriesId}/Seasons` and `GET /Shows/{seriesId}/Episodes`, both returning the envelope.

Episodes accept a `seasonId` to scope them, and both honour `DisplayMissingEpisodes` from the
user's configuration.

**Season 0 is "Specials"** and sorts after the numbered seasons, not before — its number would
place it first, and every client expects it last.

### 3.9 By-name endpoints

`GET /Artists`, `GET /Artists/AlbumArtists`, `GET /Genres`, `GET /MusicGenres`, `GET /Years`.

All return the envelope, and all take `parentId`, `userId`, `startIndex`, `limit`, `sortBy`,
`sortOrder`, `searchTerm`.

> **The `TotalRecordCount` divergence.** The reference disables counting on these endpoints when
> the request carries no `limit`, returning `TotalRecordCount: 0` beside a non-empty `Items`.
> `[prior-probe: Jellyfin master, 2026-08-05; upstream jellyfin/jellyfin#17541]`
>
> **Atrium always returns the true count.** Argued and recorded in
> [behaviours §3.1](../../docs/compatibility/behaviours.md#31-totalrecordcount-is-0-on-by-name-endpoints-without-limit--class-b):
> no client can observe the difference in a way that changes its behaviour, and the upstream fix is
> approved.

`/Artists` versus `/Artists/AlbumArtists` is the distinction from 003 §3.5: every credited artist
versus only those credited on an album. A compilation-heavy library makes the difference large, and
a client offering "Artists" and "Album Artists" as separate views needs both to be right.

### 3.10 `GET /Search/Hints` — `GetSearchHints`

Included by design: the music-client searches through `/Items?searchTerm=`, but `/Search/Hints` is
what most clients use and its response shape is **not** the item envelope.

Returns `{"SearchHints": [...], "TotalRecordCount": n}`, where a hint is a flattened summary —
`ItemId`, `Id`, `Name`, `MatchedTerm`, `Type`, `MediaType`, image tags, and type-specific extras
like `Series`, `Album`, `AlbumArtist`, `SongCount`, `EpisodeCount`. `[spec: SearchHint]`

Matching is case- and diacritic-insensitive, against name and sort name, and `MatchedTerm` reports
what matched so a client can highlight it.

## 4. Data the feature owns

None. This feature is a read surface over what 003 and 004 produced, plus 007's user data. That is
the point of listing it: a query endpoint that owns state is a query endpoint with a cache bug.

## 5. Acceptance criteria

1. Every list endpoint except `/Items/Latest` and `/Items/Filters` returns the three-field envelope
   with `StartIndex` present; `/Items/Latest` returns a bare array.
2. `UserData` is present on every item without `Fields` or `EnableUserData`, and contains `Key` and
   `ItemId`.
3. A field listed as `Fields`-gated in §3.2 is **absent** without the parameter and present with it.
4. Paging with `startIndex`/`limit` over a fixture of 100 items visits each item exactly once
   across all pages, for every supported `sortBy`.
5. `TotalRecordCount` is the pre-paging count on every list endpoint, **including by-name endpoints
   called without `limit`**.
6. `SortName` ordering matches 003 §3.7 for the fixture's awkward names.
7. `Random` returns a full set with no duplicates within one page.
8. `/Items/{itemId}` answers `404` identically for unknown and invisible items.
9. A user seeing no libraries gets an empty `/UserViews` envelope, not an error.
10. `/Shows/NextUp` returns at most one item per series.
11. Season 0 sorts last in `/Shows/{seriesId}/Seasons`.
12. `Similar` and `InstantMix` return identical results for identical input on repeated calls.
13. `/Artists` and `/Artists/AlbumArtists` differ on a compilation fixture, in the expected
    direction.
14. `/Search/Hints` returns the hint shape, not the item shape, and populates `MatchedTerm`.
15. A Tier 3 parameter is ignored, the response is `200`, and the parameter is recorded in the
    ignored-parameter report.
16. Every Tier 1 and Tier 2 parameter measurably narrows or reorders results on a fixture built to
    exercise it.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `GET /Items` | **L3** | Golden responses per parameter class, plus differential. The most-called endpoint in the API |
| `GET /Items/{itemId}` | **L3** | Golden per item type, plus differential |
| `GET /UserViews` | **L2** | Fixture with a restricted user |
| Discovery endpoints (§3.7) | **L2** | Golden responses on the fixture |
| Series navigation (§3.8) | **L2** | Fixture with specials and a missing season |
| By-name endpoints (§3.9) | **L2** | Including the no-`limit` count case (AC-5) |
| `GET /Search/Hints` | **L2** | Golden response; shape distinct from the envelope |

The **casing and unit sweeps** delivered by 001 cover every response model added here — which for
this feature means about seventy fields, the largest single surface in the project.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Which fields the reference sends that §3.2 omits, and whether any client reads them | The bounded delta in §3.2 | Differential harness (010) — the single highest-value output it produces |
| OQ-2 | Which Tier 3 parameters real clients actually send | Promotion out of Tier 3 | The ignored-parameter report (AC-15) against real client traffic |
| OQ-5 | How the reference ranks `Similar` and `InstantMix` | Nothing; v1 diverges into determinism deliberately | Comparison, for interest rather than parity |
### Resolved

| # | Question | Answer | Resolved by |
|---|---|---|---|
| OQ-6 | Whether `/Items/Latest` really returns a bare array on a live server, or the spec is wrong | **Yes — bare array, and three other endpoints have three further shapes.** §3.1 now records all four | `tools/probe_query_envelope.py`, 2026-08-26 |
| OQ-3 | The reference's tie-breaking key for each `sortBy` | **Almost none: `Name` is chained after `SortName` only, and nothing — not even the id — after anything else.** Measured, its movie sorts arrive stable with ties in id order, while `AlbumArtist`/`Artist` repeat identically yet their pages do not reassemble the one-shot list. §3.4 rule 2 is therefore a divergence from a defect, argued in behaviours §3.6 | `tools/probe_sort_stability.py`, 2026-08-27 |
| OQ-4 | The reference's completion threshold for `Resume` eligibility | **90% ceiling, 5% floor, 300-second minimum runtime — one ordered rule with six branches**, measured at 007 OQ-2 and specified in 007 §3.7, which §3.7's exclusion follows. The `probe_resume_threshold.py` this row used to name was never needed: `probe_playstate.py` answered it | `tools/probe_playstate.py`, 2026-08-26 |

## 8. References

- [docs/compatibility/api-surface-v1.md §4](../../docs/compatibility/api-surface-v1.md#4-library-navigation-and-queries)
- [docs/compatibility/behaviours.md §1.5, §2.1, §2.5, §3.1](../../docs/compatibility/behaviours.md)
- [specs/003 §3.7](../003-library-configuration-and-scanning/spec.md) — sort-name normalisation
- `[spec: GetItems, GetItem, GetUserViews, GetLatestMedia, GetResumeItems, GetNextUp, GetSeasons, GetEpisodes, GetArtists, GetAlbumArtists, GetGenres, GetMusicGenres, GetYears, GetSearchHints, GetQueryFiltersLegacy, GetSimilarItems, GetInstantMixFromItem, BaseItemDto, BaseItemDtoQueryResult, ItemFields, SearchHint]`
