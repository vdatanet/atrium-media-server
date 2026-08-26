# Roadmap

## v1 — "a client cannot tell"

**The goal of v1 is one sentence:** an unmodified Jellyfin client points at Atrium, browses a
library of movies, series and music, and plays them, without knowing it is not talking to Jellyfin.

Everything below is either a step toward that sentence or explicitly out.

### In scope

| Area | What v1 delivers |
|---|---|
| **Media types** | Movies. Series → seasons → episodes. Music: artists, album artists, albums, tracks, playlists |
| **Library** | Multiple library roots per media type; filesystem scanning; incremental rescan; deterministic identifiers |
| **Identification** | Filename and folder parsing; `.nfo` sidecars; embedded tags (ID3, Vorbis, MP4); local artwork |
| **Metadata providers** | TMDB for movies and series; MusicBrainz for music; behind a provider interface with caching and field-level precedence |
| **Users** | Multiple accounts, password authentication, per-user policy, per-user library visibility |
| **User data** | Favourites, played/unplayed, play counts, resume positions, per-user and per-item |
| **Sessions** | Session tracking, capability registration, playback start/progress/stop reporting |
| **Images** | Primary, Backdrop, Thumb, Logo, Banner; on-the-fly resizing with a disk cache; content-hash tags |
| **Playback** | `PlaybackInfo` negotiation against a client `DeviceProfile`; direct play with full `Range` support; remuxing to a compatible container without re-encoding, delivered over HLS |
| **Conformance** | The four-level harness in [compatibility/conformance.md](compatibility/conformance.md) |

### Out of scope, and why

| Not in v1 | Reason |
|---|---|
| **Full transcoding** | The largest component of Jellyfin: codec conversion, adaptive ladders, throttling, hardware acceleration, subtitle burn-in. v1 stops at remux, which covers the large majority of real playback |
| **Live TV, DVR, tuners** | A separate product with its own hardware surface |
| **The Jellyfin web UI** | Would add a large endpoint surface whose only consumer is a UI this project is not building |
| **Plugins** | .NET assembly loading; no Python analogue worth inventing |
| **SyncPlay, WebSocket push** | Needs a session model v1 does not have; clients poll |
| **DLNA server** | Outside the client-facing contract |
| **Books, photos, home videos** | Outside the stated media scope |
| **Emby dialect** | Atrium is Jellyfin-shaped. See [compatibility/reference-target.md §5](compatibility/reference-target.md#5-what-is-not-a-target) |

## Feature order

Each row is one directory under [`specs/`](../specs/). The order is a dependency order, not a
priority order: each feature is testable the moment it lands, and each unlocks the next.

| # | Feature | Delivers | Depends on |
|---|---|---|---|
| **001** | Server identity and discovery | An unauthenticated client can find the server and identify it as Jellyfin | — |
| **002** | Authentication, users and sessions | A client can log in, hold a token, and be recognised on later requests | 001 |
| **003** | Library configuration and scanning | Files on disk become items with stable identifiers | — |
| **004** | Metadata resolution | Items get titles, dates, people, genres and artwork, from local and online sources | 003 |
| **005** | Item query API | `/Items` and the by-name endpoints: filtering, sorting, pagination, `Fields` | 002, 004 |
| **006** | Images | Artwork delivery, resizing, cache, tags | 004, 005 |
| **007** | User data and playstate | Favourites, played, resume, playback reporting | 002, 005 |
| **008** | Playback negotiation and delivery | `PlaybackInfo`, direct play, remux, `Range` | 005, 007 |
| **009** | Playlists | Create, read, add, remove, reorder | 005 |
| **010** | Conformance harness | The L0–L3 machinery as a deliverable, not a by-product | all |

**010 is last in the list but not last in time.** L0 and L1 exist from 001 — the casing sweep has
to be in place before the first response model, or Principle I is enforced by discipline instead of
by CI. What 010 delivers as a feature is the *differential* layer, which needs a server complete
enough to compare.

### The first three, concretely

- **001** is small and unglamorous, and it is first because it is the first request every client
  makes and because it forces the wire-format decisions — PascalCase, date format, GUID shape —
  before anything else can encode them wrongly.
- **002** is where the four authentication mechanisms and the `X-Emby-Authorization` header get
  settled.
- **003** can proceed in parallel with 001 and 002: it has no HTTP surface of its own and is
  validated entirely against the fixture library.

## Beyond v1

Not planned, not promised. Recorded so the shape of the ambition is visible:

- **v2 candidates** — full transcoding; the official Jellyfin web UI; WebSocket push for library
  changes; subtitle delivery and search; trickplay generation; Postgres as an alternative store.
- **Permanently out** — an Atrium-specific API dialect, in any form. Principle I.
