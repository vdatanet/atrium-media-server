---
feature: 004-metadata-resolution
title: Metadata resolution
status: Implemented
created: 2026-08-26
updated: 2026-09-05
implemented: 2026-08-27
accepted: 2026-08-27
amended: 2026-08-27 by T1 - section 3.3, OQ-4 and OQ-5; by T8 - section 3.4;
  2026-09-03 by the container-directory fix - section 3.2 and AC-19;
  2026-09-05 by the 2026-09-04 audit's corrective task C6 - section 3.6 states what `Local only`
  does with the rule the other two modes share, where that rule had lived in `metadata/merge.py`'s
  own docstring, and section 5 gains AC-20 for it
depends_on: [003]
---

# 004 — Metadata resolution

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Give the items produced by 003 their titles, dates, overviews, people, genres, ratings, provider
identifiers and artwork — from local sources first, then from online providers.

**Client behaviour unlocked:** a library that looks like a library instead of a list of filenames.

## 2. Scope

**In scope**

- Local sources: `.nfo` sidecars, embedded audio tags, local artwork files.
- Remote sources: TMDB for movies and series, MusicBrainz for music.
- The provider interface: how sources are ordered, how their results merge, and what wins.
- Field-level locking, so a manual correction survives the next refresh.
- Caching of remote responses, and behaviour when a provider is unreachable.
- `GET /Localization/Cultures`, because language codes on tracks and metadata come from here.

**Out of scope**

- Editing metadata over HTTP. v1 reads; it has no `POST /Items/{id}` update route.
- Provider search endpoints (`/Items/RemoteSearch/*`) and manual identification from a client.
- Subtitle and lyric providers.
- Image *generation* — trickplay, chapter thumbnails. Existing chapter images are served (006).
- Writing metadata back to disk. Atrium never modifies the user's files.

> **Atrium never writes into a library root.** Not sidecars, not artwork, not tags. A media server
> that edits the user's files can destroy an irreplaceable collection through one bug, and no
> feature in v1 is worth that risk. Everything derived is stored outside the library.

## 3. Behaviour

### 3.1 The provider model

A provider answers one question: *given what we know about this item, what else can you tell us?*

Providers are ordered, and the order is the precedence. For each item type the chain is:

| Position | Movies and series | Music |
|---|---|---|
| 1 | Locked fields (§3.6) | Locked fields |
| 2 | `.nfo` sidecar | Embedded tags |
| 3 | Path-derived (from 003) | `.nfo` sidecar |
| 4 | TMDB | MusicBrainz |
| 5 | Path-derived (from 003) | |

**Music inverts the first two on purpose.** A music file carries its own metadata; a video file
almost never does. Reading a well-tagged FLAC and then overwriting its album name with a guess from
the directory would be a regression a user notices immediately.

**Merging is per field, not per provider.** A movie can take its title from a sidecar, its overview
from TMDB and its year from the path, and this is the normal case rather than an edge. A provider
that returns nothing for a field does not blank it; only a provider that returns a *value* sets it.

**Empty string is not a value.** A provider returning `""` for an overview leaves the overview to
the next provider in the chain. Otherwise a sparse sidecar erases everything below it.

### 3.2 `.nfo` sidecars

The de-facto standard shared with Kodi, and the reason it matters is that a large fraction of
existing libraries already have these files. Reading them is the difference between "Atrium found
my library" and "Atrium lost my metadata".

| Item | Sidecar |
|---|---|
| `Film (1999).mkv` | `Film (1999).nfo` |
| Folder-per-film | `movie.nfo` in the folder |
| Series | `tvshow.nfo` in the series folder |
| Season | `season.nfo` in the season folder |
| Episode | `Episode.nfo` beside the file |
| Album | `album.nfo` |
| Artist | `artist.nfo` |

Fields read: title, original title, sort title, year, premiere date, overview, tagline, runtime,
official rating, community rating, genres, studios, tags, people with their roles and ordering, and
provider identifiers.

**Provider identifiers in a sidecar are authoritative.** An `.nfo` naming a TMDB id means the user
has already decided what this film is, and no matching heuristic may second-guess it. This single
rule removes most wrong-match complaints.

**A malformed sidecar is a warning, not a failure.** The item still resolves from the remaining
providers, and the parse error is reported with the file path so the user can fix it.

**A container's sidecar is in the container's own directory, and that directory is the one the
library's shape gives it.** A series, a season, an album and an artist are not files, so none of
them has a directory to be read from the way a film has; each takes the place its position in the
library implies, counted from the library root **down**. An album's directory is the album's, not a
disc directory inside it, so a record split across `CD1` and `CD2` reads the `album.nfo` beside
those discs; an artist's is the artist's, not one of their albums'. The same directory is where
§3.4's artwork is looked for.

Counted the other way — up from a track — an extra directory the library's shape has no place for
moves every container above it, which is how a two-disc album came to look for its sidecar inside
one of its discs and its artist inside the album. Measured on a reference server over this
project's own fixture tree: of its 26 container rows, the 18 that carry a directory and a kind this
model has all sit exactly that deep below the library root — disc directories included, since the
reference lists a disc as a plain folder of its own and still resolves the album from the directory
above it `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`.

Where the library holds no directory that deep — a season whose only episode sits loose in the
series folder, which the reference answers with a season carrying no directory at all — the deepest
one beneath the root that the container's own files offer is used instead. **Nothing above a
library root is ever read**, whatever the shape.

### 3.3 Embedded tags

For music, read from the file itself: title, artist, album artist, album, track and disc numbers
and totals, year, genre, composer, MusicBrainz identifiers, the track's replay-gain adjustment, and
embedded cover art.

**One replay-gain value, not four.** The reference reads the *track gain* and nothing else — not
track peak, not album gain, not album peak
`[source: MediaBrowser.Providers/MediaInfo/AudioFileProber.cs:362-375 @ v10.11.11]` — and serves
it as a single number on the item, the
adjustment in decibels a player applies to level this track against others. The other three
values have nowhere in the reference's item shape to go, so reading them would be storage no
response can ever carry (OQ-5, §7).

**Multi-valued tags stay multi-valued.** A track with three artists has three artists, not one
string containing semicolons. Clients render them as separate links, and joining them destroys
that.

The container formats differ in how they store all of this. Atrium reads the common ones and treats
an unreadable tag block the way it treats a malformed sidecar: warn, continue.

### 3.4 Local artwork

Files beside the media, recognised by name, before any provider is consulted:

| Image | Names, in the order they are tried |
|---|---|
| Primary | the item's own file name; then `poster`, `folder`, `cover`, `default` — **but a music album or artist tries `folder` first** and also answers to `jacket` and `albumart`, a series to `show`, a film to `movie`, and a person only to `folder` and `poster` |
| Backdrop | `fanart`, `background`, `art`, `backdrop`, each with numbered variants, and an `extrafanart` folder taken whole |
| Logo | `logo`, `clearlogo` |
| Art | `clearart` |
| Thumb | `landscape`, `thumb` |
| Banner | `banner` |
| Disc | `disc`, `cdart`, `discart` — **but a music album tries `cdart` first**, and only a film answers to `discart` |

Each name may also be prefixed with the item's own file name, which is what lets two films in one
folder have different posters.

**Backdrops accumulate; every other type is first-match-wins.** An item has one poster and as many
backdrops as it has files for, in that order.

**An episode, a track and a person get a Primary and nothing else** — no logo, no banner, no
backdrop, no disc.

Embedded cover art in an audio file is a Primary image when no file-based one exists. Delivery,
resizing and cache tags are feature 006; this feature only decides **which file is which image**.

> **Corrected at T8**, which read the reference's tables rather than reasoning from this one. Two
> orderings here were backwards — `thumb` before `landscape`, and `disc` before `cdart` for an
> album — and the list was a subset: the per-type names, the bare-file-name form, the `art` family
> and the `extrafanart` folder were all missing
> `[source: MediaBrowser.LocalMetadata/Images/LocalImageProvider.cs:18-400 @ v10.11.11]`.

### 3.5 Remote providers

**TMDB** for movies and series: identification by title and year, then metadata and artwork by id.
**MusicBrainz** for music: release-group and recording identification, then canonical names, dates
and relationships.

Rules that apply to both:

1. **A provider identifier short-circuits identification.** If the item already has one — from a
   sidecar, from embedded tags, from a previous refresh — it is used directly and no search runs.
2. **Ambiguous matches are not guessed.** A search returning several plausible candidates with no
   clear winner leaves the item unidentified rather than picking one. A wrong match is worse than a
   missing one: it is confidently wrong, it is hard for a user to notice, and correcting it needs a
   manual-identification flow v1 does not have.
3. **Providers are rate-limited and cached.** A rescan of an unchanged library makes no network
   requests at all.
4. **A provider being down is not a scan failure.** The item keeps whatever local metadata it has,
   is marked as needing a refresh, and is retried later. Items are never blanked because a network
   call failed.
5. **Provider credentials are the operator's.** Absent credentials disable that provider with a
   clear message, and everything local still works. A v1 install with no internet must produce a
   usable library.

> **Why online providers are in v1 at all.** They add network, credentials, caching and
> non-deterministic tests, all of which are real costs. They are in because a library of films
> without posters, overviews and cast is not a library a client can render usefully, and because
> the provider *interface* is much harder to retrofit than to design. The determinism requirement
> (Principle VII) is preserved by making every test use recorded responses; no test in this project
> reaches the network.

### 3.6 Locks and refresh

A field can be **locked**, meaning no provider may change it. An item can be locked entirely.

This exists because identification is imperfect: when a user corrects something, the correction has
to survive the next refresh, or they will correct it forever.

| Refresh mode | Behaviour |
|---|---|
| **Default** | Fill only fields that are empty. Never overwrite an existing value |
| **Replace** | Re-query providers and overwrite unlocked fields |
| **Local only** | Sidecars, tags and local artwork; no network |

Locks are honoured in every mode, including Replace.

**`Local only` is `Default` over a shorter chain, not a fourth behaviour** *(the rule was written
at T6 and has lived in `metadata/merge.py`'s own docstring ever since; this paragraph is where a
criterion can reach it — added 2026-09-05 by the 2026-09-04 audit's M3)*. The remote sources are
dropped **before** the merge runs, and what is left is Default's rule over what remains: an empty
field is filled from a sidecar, tags, the path or local artwork, a field that already has a value
is kept, and a locked field is refused as it is in the other two modes. So the mode is a choice of
*sources*, not a third arithmetic — and with no remote provider to ask, `Local only` and `Default`
produce the same library, which is the honest statement of the difference between them. The
refresh also **says** it consulted nobody: each configured provider is reported as having sat out
with `local-only refresh` as its reason, in the same list of the report that a missing credential
fills (§3.5).

A refresh is triggered by a scan finding a changed file, by an item having no metadata yet, or by
an operator asking. v1 has no HTTP route for the last one; it is a configuration and command-line
concern.

### 3.7 People, genres and studios

People, genres, studios and years become **by-name items** — items in their own right, so that
`/Genres`, `/MusicGenres`, `/Artists` and person queries in 005 have something to return.

Two rules:

1. **Names are folded for identity, preserved for display.** `Sci-Fi` and `sci-fi` are one genre;
   the display name is the first spelling seen. Without this a library grows a long tail of
   near-duplicate genres — and it is the reference's own behaviour, not an improvement: 97 of 97
   live genre ids reproduce from the case-folded name, a library carrying `Electronic` and
   `electronic` on its items holds one row for each, and no two by-name rows differ only by case
   `[probe: tools/probe_by_name_normalisation.py, Jellyfin 10.11.11, 2026-08-27]`. The fold is
   **case only** — spellings differing in diacritics stay separate items — plus the characters a
   filename cannot carry; the first-spelling-wins half is source-backed rather than measured.
   Mechanism and limits in
   [behaviours §2.18](../../docs/compatibility/behaviours.md#218-two-spellings-of-one-genre-are-one-item).
2. **People carry role and ordering.** A cast list is ordered, and the order is part of the
   metadata, not an accident of insertion. Clients display "starring" from the first few entries.

### 3.8 `GET /Localization/Cultures` — `GetCultures`

**Consumers:** video-client. Returns the known cultures, each with its two- and three-letter codes
and display name, so a client can label an audio or subtitle track as "Català" rather than `cat`.

Static data. Authenticated, `200`, no parameters.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Resolved item metadata | Every field of an item in 005 | Until the next refresh |
| Field locks | That a refresh does not change a field | Until unlocked |
| Provider identifiers | `ProviderIds` on an item | With the item |
| Artwork associations | `ImageTags` and 006's responses | Until the next refresh |
| Cached provider responses | Nothing directly; absence of network traffic | Until expiry |
| By-name items | `/Genres`, `/Artists`, `/MusicGenres` | Until no item references them |

## 5. Acceptance criteria

1. A film with a full `.nfo` resolves entirely from it, with no network request made.
2. A film with a sparse `.nfo` takes the named fields from it and the rest from the next provider,
   per field.
3. An `.nfo` containing a provider id causes identification to be skipped entirely.
4. A malformed `.nfo` produces a warning naming the file, and the item still resolves.
5. A well-tagged audio file takes its album and artist from tags even when the directory disagrees.
6. A track with three artists yields three artists.
7. Local artwork is used without consulting a provider, and the right file becomes the right image
   type.
8. With every provider unreachable, a full scan completes and every item keeps its local metadata.
9. With no provider credentials configured, a scan completes and reports which providers were
   disabled.
10. A locked field survives a Replace refresh.
11. A default refresh never overwrites a non-empty field.
12. An ambiguous remote match leaves the item unidentified rather than choosing.
13. Rescanning an unchanged library makes **zero** network requests.
14. `Sci-Fi` and `sci-fi` in two files produce one genre item.
15. No file inside any library root is created, modified or deleted by any operation in this
    feature.
16. No test in this feature's suite reaches the network.
17. `GET /Localization/Cultures` answers `200` for an authenticated caller with the generated
    table, each row carrying its two- and three-letter codes and display name, golden body byte
    for byte (§3.8). *(Added at the 2026-08-28 audit — M33: an entire endpoint with no
    criterion, whose golden test could appear nowhere in the acceptance map.)*
18. A cast keeps its billing order and its roles from source to storage: the first rows are what
    a client shows as "starring", so the order is part of the metadata, not an accident of
    insertion (§3.7 rule 2). *(Added at the same audit — M34.)*
19. A container reads its sidecar and its artwork from its own directory: a two-disc album from
    the directory holding its discs rather than from one of them, an artist from theirs rather
    than from an album's, a season from its own rather than from the series folder — and no
    container ever reads a directory above the library root (§3.2). *(Added 2026-09-03 by the
    container-directory fix, which found the borrowing wrong for two shapes the project's own
    fixture already has and reaching outside the library for a third.)*
20. A **Local only** refresh reads sidecars, tags, the path and local artwork, asks no provider
    anything, and resolves the item from what it found (§3.6). It is not a third arithmetic: the
    remote sources are dropped before the merge, so the rule that then runs is AC-11's — an empty
    field is filled, a field that already has a value is kept — and AC-10's lock refuses a value in
    this mode exactly as it does under Replace. The run reports the provider it did not consult,
    with `local-only refresh` as its reason, in the same list of the report that a missing
    credential fills (AC-9); and with no remote provider to ask, the library it produces is the one
    `Default` produces, which is what makes this a claim about the *sources* a mode consults rather
    than about a behaviour of its own. *(Added at the 2026-09-04 audit — M3: the third row of
    §3.6's table had four dedicated tests and no criterion, where the other two rows have AC-10 and
    AC-11.)*

## 6. Conformance

| Endpoint / behaviour | Level | How it is proven |
|---|---|---|
| `GET /Localization/Cultures` | **L2** | Golden response |
| Sidecar parsing | **L2** | Fixture sidecars: full, sparse, malformed, id-bearing |
| Embedded tags | **L2** | Synthetic files generated at build time with known tags |
| Provider precedence and merging | **L2** | Table-driven per field, with recorded provider responses |
| Locks and refresh modes | **L2** | Matrix of mode × locked × empty |
| Offline and credential-less behaviour | **L2** | Providers stubbed to fail (AC-8, AC-9) |
| Read-only guarantee | **L2** | Fixture tree hashed before and after a full scan (AC-15) |

Remote providers are exercised through **recorded responses**, checked in. A live-provider test
exists but is opt-in, skipped by default, and never gates CI — Principle VII forbids tests that
depend on network availability.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Which `.nfo` dialect the reference accepts, and how it handles fields Kodi writes but Jellyfin ignores | Field coverage in §3.2 | Fixture comparison via the differential harness |
| OQ-2 | The reference's exact ambiguity threshold for remote matching | Nothing; v1 is deliberately more conservative | Comparison against a real server on a deliberately ambiguous fixture |
| OQ-4 | Which `ProviderIds` keys clients read | Nothing; all known keys are emitted | Differential harness (010) |

**OQ-4 has partial evidence and stays open.** The same client reading that resolved OQ-5 found
**neither client reads `ProviderIds` at all** — no reference to the property, and no reference to
any provider's name, in either codebase (2026-08-27, by role only). That is evidence about two
clients, not about the population, and it is the wrong shape to close the question with: it says
nothing about which keys *other* clients read, and a floor of zero cannot tell us which keys to
emit. The differential harness (010) still owns the answer, and until then all known keys are
emitted.

### Resolved

| # | Question | Answer | Resolved by |
|---|---|---|---|
| OQ-5 | Whether ReplayGain values are exposed anywhere a client reads | **One of them is exposed, and no client reads it.** The reference reads exactly one tag — the track gain — strips a trailing unit suffix, and serves the number as `NormalizationGain` on every item `[source: MediaBrowser.Providers/MediaInfo/AudioFileProber.cs:362-375 @ v10.11.11]` `[spec: BaseItemDto]`; a separate opt-in loudness scan, when it has run, overrides that value with one computed from the file `[source: Emby.Server.Implementations/Dto/DtoService.cs:1000-1007 @ v10.11.11]`. Track peak, album gain and album peak reach no response. **Neither surveyed client consumes it**: the music-client has no code path for it and its own scope documents place volume levelling beyond its current version, with a note that it must first establish whether the value arrives over the API at all; the video-client carries the property only because its API layer is generated wholesale from the reference's document, and no hand-written code reads it. So the value is real surface with no observed consumer — which is why §3.3 reads one value rather than four, and why [plan §4](plan.md#4-data-model) stores one number rather than a map | Survey of the two clients of [api-surface-v1 §1](../../docs/compatibility/api-surface-v1.md#1-how-this-set-was-derived), by role, 2026-08-27 |
| OQ-3 | Does the reference re-normalise genre names, or does its by-name list grow duplicates? | **It folds case into the by-name identity, so the list cannot grow case duplicates** — 97 of 97 live ids reproduce from the case-folded name, and a library carrying `Electronic` and `electronic` on items holds one row for each. §3.7 rule 1 is a reproduction with provenance, not a divergence; the fold's limits are in [behaviours §2.18](../../docs/compatibility/behaviours.md#218-two-spellings-of-one-genre-are-one-item) | `tools/probe_by_name_normalisation.py`, 2026-08-27 |

## 8. References

- [docs/compatibility/api-surface-v1.md §2](../../docs/compatibility/api-surface-v1.md#2-identity-and-discovery)
- [specs/003](../003-library-configuration-and-scanning/spec.md) — structure, which this feature annotates
- [specs/006](../006-images/spec.md) — delivery of the artwork this feature locates
- `[spec: GetCultures]`
