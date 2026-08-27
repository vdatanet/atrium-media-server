# The v1 API surface

**Last verified: 2026-08-26. Every path and method below was checked to exist in the Jellyfin
10.11.10 OpenAPI document; the `Operation` column is that document's `operationId`.**

Jellyfin exposes **322 paths**. v1 of Atrium serves **55**. This document explains which 55, and —
more importantly — *how that set was chosen*, because Principle VI forbids adding an endpoint
without a named consumer.

## 1. How this set was derived

Not by reading Jellyfin's documentation and picking what looked important. By reading the source
of clients that actually work, and extracting what they call.

Two consumers were analysed. Both are production clients maintained by this project's author,
which is what made a source-level analysis possible; they are described by role rather than by
name, because their internals are not this repository's to publish.

| Tag | Client | What it is | How the calls were extracted |
|---|---|---|---|
| **M** | **music-client** | Kotlin Multiplatform music client, multi-server (Emby and Jellyfin), iOS and Android | Path literals in its server-driver layer |
| **V** | **video-client** | tvOS client for movies, series and music | Operation ids invoked against a generated OpenAPI client |

Together they cover the full v1 domain: **M** is a demanding audio client (gapless playback,
playlists, instant mix, DLNA casting), **V** is a video-first client (series navigation, resume,
next-up, playback negotiation). An endpoint neither of them calls has to justify itself on other
grounds, and the `D` tag below marks the ones that did.

> **On the strength of this evidence.** Two clients are not the population of Jellyfin clients, and
> this document does not claim otherwise. What the analysis gives is a *floor* — a set known to be
> insufficient if any of it is missing — not a ceiling. The differential harness (feature 010) is
> what turns the floor into a measured surface, and endpoints promoted by it get added here with
> the same provenance discipline as everything else.

| Tag | Meaning |
|---|---|
| **M** | Called by music-client |
| **V** | Called by video-client |
| **D** | Not observed in either client; included by design, with the reason given |

## 2. Identity and discovery

| Method | Path | Operation | Used by | Notes |
|---|---|---|---|---|
| GET | `/System/Info/Public` | `GetPublicSystemInfo` | M V | Unauthenticated. `ProductName` is the server discriminator — see [reference-target.md §4](reference-target.md#4-server-identity-what-atrium-tells-clients-it-is) |
| GET | `/System/Info` | `GetSystemInfo` | M | Authenticated; superset of the public payload |
| GET | `/System/Ping` | `GetPingSystem` | D | Trivial liveness probe; several clients and reverse-proxy health checks use it |
| POST | `/System/Ping` | `PostPingSystem` | D | Same, POST form |
| GET | `/Users/Public` | `GetPublicUsers` | V | **May legitimately return `[]`** — users hidden from login screens are excluded, and that is a 200, not an error `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` |
| GET | `/Localization/Cultures` | `GetCultures` | V | Language list for audio/subtitle track labelling |

## 3. Authentication, users and sessions

| Method | Path | Operation | Used by | Notes |
|---|---|---|---|---|
| POST | `/Users/AuthenticateByName` | `AuthenticateUserByName` | M V | Requires the `X-Emby-Authorization` header; body is `{"Username","Pw"}` |
| GET | `/Users/Me` | `GetCurrentUser` | V | Resolves the token to a user |
| GET | `/Users/{userId}` | `GetUserById` | M | |
| POST | `/Users/Configuration` | `UpdateUserConfiguration` | V | Per-user display/playback preferences |
| POST | `/Sessions/Capabilities/Full` | `PostFullCapabilities` | D | Clients that support remote control post here after login; accepting and storing it costs nothing and its absence is visible in `/Sessions` |
| GET | `/Sessions` | `GetSessions` | V | |

Authentication mechanisms Atrium must accept — all four, because clients pick different ones for
headers versus for URLs embedded in media players:

| Mechanism | Form |
|---|---|
| Header | `X-Emby-Token: {token}` |
| Header | `Authorization: MediaBrowser Token="{token}"` |
| Query | `?ApiKey={token}` |
| Query | `?api_key={token}` |

`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

`X-Emby-Authorization: MediaBrowser Client="…", Device="…", DeviceId="…", Version="…"` is
**mandatory** on `AuthenticateByName` and identifies the device for session tracking.

## 4. Library navigation and queries

| Method | Path | Operation | Used by | Notes |
|---|---|---|---|---|
| GET | `/UserViews` | `GetUserViews` | V | The libraries as the user sees them |
| GET | `/Items` | `GetItems` | M V | The workhorse. Filtering, sorting, pagination, `Fields`, `SearchTerm` |
| GET | `/Items/{itemId}` | `GetItem` | M V | Single item. **This is the Jellyfin route**; Emby uses `/Users/{userId}/Items/{itemId}`, which 10.11 no longer serves |
| GET | `/Items/Latest` | `GetLatestMedia` | V | |
| GET | `/Items/Filters` | `GetQueryFiltersLegacy` | V | Available genres/years/tags for a parent |
| GET | `/Items/{itemId}/Similar` | `GetSimilarItems` | V | |
| GET | `/Items/{itemId}/InstantMix` | `GetInstantMixFromItem` | M V | Radio-style queue from a seed |
| GET | `/UserItems/Resume` | `GetResumeItems` | V | Continue watching/listening |
| GET | `/Shows/{seriesId}/Seasons` | `GetSeasons` | D | The canonical route for seasons; `GetItems` with a parent works too, but a client that uses the named route must not 404 |
| GET | `/Shows/{seriesId}/Episodes` | `GetEpisodes` | V | |
| GET | `/Shows/NextUp` | `GetNextUp` | V | |
| GET | `/Artists` | `GetArtists` | M | |
| GET | `/Artists/AlbumArtists` | `GetAlbumArtists` | V | |
| GET | `/Genres` | `GetGenres` | M V | |
| GET | `/MusicGenres` | `GetMusicGenres` | M | |
| GET | `/Years` | `GetYears` | V | |
| GET | `/Search/Hints` | `GetSearchHints` | D | The dedicated search route. music-client searches via `/Items?SearchTerm=`, but `/Search/Hints` is what most clients use and its response shape differs |

> ⚠️ **The `TotalRecordCount` trap.** `/Artists`, `/Artists/AlbumArtists`, `/Genres`,
> `/MusicGenres` and `/Studios` share one code path that **disables the count when the request
> carries no `limit`**, returning `TotalRecordCount: 0` alongside a non-empty `Items`. This is a
> Jellyfin defect ([#17541](https://github.com/jellyfin/jellyfin/pull/17541)) that Atrium must
> decide about explicitly — see [behaviours.md](behaviours.md).
> `[prior-probe: Jellyfin master, 2026-08-05]`

## 5. User data

| Method | Path | Operation | Used by |
|---|---|---|---|
| POST | `/UserFavoriteItems/{itemId}` | `MarkFavoriteItem` | M V |
| DELETE | `/UserFavoriteItems/{itemId}` | `UnmarkFavoriteItem` | M V |
| POST | `/UserPlayedItems/{itemId}` | `MarkPlayedItem` | M V |
| DELETE | `/UserPlayedItems/{itemId}` | `MarkUnplayedItem` | M V |

`UserData` is returned **on every item by default**, with no `Fields=UserData` needed, and
Jellyfin's version carries `Key` and `ItemId` inside the object.
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

## 6. Playlists

| Method | Path | Operation | Used by |
|---|---|---|---|
| POST | `/Playlists` | `CreatePlaylist` | M |
| GET | `/Playlists/{playlistId}/Items` | `GetPlaylistItems` | M V |
| POST | `/Playlists/{playlistId}/Items` | `AddItemToPlaylist` | M |
| DELETE | `/Playlists/{playlistId}/Items` | `RemoveItemFromPlaylist` | M |
| POST | `/Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}` | `MoveItem` | M |
| DELETE | `/Items/{itemId}` | `DeleteItem` | M |

Note that `{itemId}` in `MoveItem` and `RemoveItemFromPlaylist` is the **playlist entry id**, not
the media item id — the same track can appear twice in one playlist. This distinction is a common
source of client bugs and must be got right.

`DeleteItem` is in v1 solely because deleting a playlist goes through it. Deleting *media* is a
separate, dangerous capability gated by user policy.

## 7. Images

| Method | Path | Operation | Used by |
|---|---|---|---|
| GET | `/Items/{itemId}/Images/{imageType}` | `GetItemImage` | M V |
| GET | `/Items/{itemId}/Images/{imageType}/{imageIndex}` | `GetItemImageByIndex` | V |

Both accept `maxWidth`, `maxHeight`, `quality` and `tag`, and require authentication — typically
via `?api_key=` because these URLs are handed to image loaders that do not set headers.
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

Items advertise available images through `ImageTags`, e.g. `{"Primary": "<32 hex>"}`. The tag is a
content hash used for cache invalidation, so it must change when the image changes and only then.

## 8. Playback negotiation and delivery

| Method | Path | Operation | Used by | Notes |
|---|---|---|---|---|
| POST | `/Items/{itemId}/PlaybackInfo` | `GetPostedPlaybackInfo` | V | The real negotiation entry point: the client posts a `DeviceProfile`, the server answers with `MediaSources` and a delivery decision |
| GET | `/Items/{itemId}/PlaybackInfo` | `GetPlaybackInfo` | D | Profile-less variant; some clients still use it |
| GET | `/Audio/{itemId}/stream` | `GetAudioStream` | M | With `static=true` for direct play |
| GET | `/Audio/{itemId}/stream.{container}` | `GetAudioStreamByContainer` | M | |
| GET | `/Audio/{itemId}/universal` | `GetUniversalAudioStream` | M | Server-decides variant |
| GET | `/Videos/{itemId}/stream` | `GetVideoStream` | V | |
| GET | `/Videos/{itemId}/stream.{container}` | `GetVideoStreamByContainer` | D | Container-suffixed form, for players that sniff by extension |
| GET | `/Videos/{itemId}/master.m3u8` | `GetMasterHlsVideoPlaylist` | D | Remux and transcode path — see below |
| GET | `/Videos/{itemId}/main.m3u8` | `GetVariantHlsVideoPlaylist` | D | Remux and transcode path |
| GET | `/Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}` | `GetHlsVideoSegment` | D | Remux and transcode path |
| DELETE | `/Videos/ActiveEncodings` | `StopEncodingProcess` | V | Clients call this when the user stops; a server that ignores it leaks processes |

The three HLS routes are tagged `D` because the analysed clients direct-play. They are in v1
because v1's playback scope is **direct play, remuxing and software transcoding** (see
[../roadmap.md](../roadmap.md)), and both remuxed and re-encoded delivery are served over HLS. The
same three routes carry both: which one a client is being served is a property of the negotiation,
not of the URL. Hardware acceleration and subtitle burn-in are out of v1 — **no endpoint of this
table depends on either**, which is why they can arrive later without the surface moving.

**Range support is not optional.** Every delivery route must answer `Range` requests with `206`,
correct `Content-Range` and `Accept-Ranges: bytes`, and must send `Content-Length` on non-chunked
responses. Jellyfin's *transcoding* routes do not, and that single gap forces every client that
casts to a DLNA renderer to run a local sizing proxy. Atrium serving a correct `Content-Length` on
remuxed and transcoded output is one of the few places where being right costs nothing and helps a
lot.

## 9. Playback reporting

| Method | Path | Operation | Used by |
|---|---|---|---|
| POST | `/Sessions/Playing` | `ReportPlaybackStart` | M V |
| POST | `/Sessions/Playing/Progress` | `ReportPlaybackProgress` | M V |
| POST | `/Sessions/Playing/Stopped` | `ReportPlaybackStopped` | M V |

All three answer `204`. Jellyfin's `Progress` does **not** require `MediaSourceId` (Emby's does).
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

## 10. Deliberately excluded from v1

Each of these is a real Jellyfin capability that Atrium does not serve in v1. They are listed so
that "missing" is never confused with "forgotten".

| Area | Why not in v1 |
|---|---|
| Live TV, DVR, channels, tuners | A separate product domain with its own hardware surface |
| SyncPlay | Requires a WebSocket session model v1 does not have |
| Plugins, packages, repositories | .NET assembly loading; no Python analogue worth inventing |
| DLNA server and profiles | Out of the client-facing contract |
| Backup, scheduled tasks, activity log | Operations surface, not client surface |
| Quick Connect | Convenience auth; adds a second auth state machine |
| Subtitles: search, download, burn-in | Delivery of *existing* external subtitle files may land in v1; provider search does not |
| Hardware-accelerated transcoding | v1 re-encodes on the CPU; VAAPI/QSV/NVENC/VideoToolbox are a per-machine surface, not an endpoint |
| Trickplay / chapter images generation | Serving existing chapter images is in; generating them is not |
| WebSocket `/socket` | Push notification of library changes; clients poll instead in v1 |
| Books, photos, home videos | Out of the stated media scope |
| The Jellyfin web UI | See [reference-target.md §5](reference-target.md#5-what-is-not-a-target) |

Growing the surface is a roadmap decision, not something an implementer does opportunistically.

## 11. Keeping this table honest

The tables above have a machine-readable companion, [`surface.yaml`](surface.yaml), carrying the
same 55 entries with their consumers, owning feature and required conformance level.

```bash
python3 tools/extract_v1_surface.py --spec reference/openapi.json --print-summary
```

The validator checks every entry against the pinned OpenAPI document: that the path exists, that
the method exists on it, that the recorded `operationId` matches, that the conformance level is
valid, and that no entry is duplicated. It also refuses to run against a document whose version
does not match the pin, because moving the pin has a
[procedure](conformance.md#when-the-reference-version-moves).

It runs in CI, so this document cannot silently drift from the contract it claims to implement.
The same file is read by the route-registration test, which asserts the server exposes **exactly**
these routes and no others — the automated half of Principle VI.
