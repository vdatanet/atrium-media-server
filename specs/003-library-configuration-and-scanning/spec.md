---
feature: 003-library-configuration-and-scanning
title: Library configuration and scanning
status: Draft
created: 2026-08-26
updated: 2026-08-26
depends_on: []
---

# 003 — Library configuration and scanning

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Turn directories of files into a hierarchy of items with stable identifiers.

This feature has **no HTTP surface of its own**, which is why it can be built in parallel with 001
and 002. Everything it produces becomes observable through feature 005, and every mistake it makes
becomes a wrong answer there.

**Client behaviour unlocked:** nothing directly — and everything indirectly. A client cannot show a
library that was never scanned.

## 2. Scope

**In scope**

- Library roots: what an operator configures, and what a collection type means.
- File discovery: which files are considered, which are ignored, and why.
- Resolution: turning paths into item types and parent-child structure for movies, series and
  music.
- Naming: extracting titles, years, season and episode numbers, disc and track numbers from paths.
- Identity: deriving identifiers that survive a rescan.
- Change detection: what an incremental scan must notice.
- Sort names: the normalisation that decides ordering everywhere else.

**Out of scope**

- Fetching metadata from anywhere, local or remote — that is 004. This feature produces *structure*
  and whatever the path itself tells us, nothing more.
- Inspecting media with a prober for codecs, duration and resolution — that is 008, and it is
  triggered by this feature but specified there.
- Filesystem watching. v1 rescans on demand and on a schedule.
- Books, photos, home videos, mixed-content folders.

## 3. Behaviour

### 3.1 Libraries

An operator configures one or more libraries. Each has a name, one or more root paths, and a
**collection type** from: `movies`, `tvshows`, `music`.

The collection type is not a hint. It selects which resolution rules apply, and a file under a
`music` root is never resolved as a movie no matter what it is called. Mixed-content roots are not
supported in v1: this is a real limitation of the reference too, and an operator with mixed content
is expected to split the root.

Each library becomes a `CollectionFolder` item, and each user sees it as a `UserView` (005) if
policy permits (002 §3.5).

### 3.2 What is considered a media file

A file is a candidate when its extension is on the type list for its library's collection type.
Everything else is ignored silently — a library root contains artwork, subtitles, `.nfo` sidecars
and operating-system detritus, and none of that is an error.

Ignored regardless of extension:

| Rule | Reason |
|---|---|
| Any path component beginning with `.` | Hidden files and macOS resource forks |
| A directory containing a `.ignore` file | The operator's explicit exclusion |
| Files matching the trailer, sample and extra suffixes | They are extras, not the work; §3.4 |
| Zero-byte files | Incomplete copies |
| Files being written, detected by size change between two passes | Downloads in progress |

> ⚠️ **OQ-1.** The exact extension lists the reference honours. Getting these wrong is directly
> observable — a library missing items a client's user knows are there. Until measured, v1 uses the
> conservative union of what a prober can open.

### 3.3 Movies

| Layout | Resolves to |
|---|---|
| `Movies/The Film (1999).mkv` | One `Movie` |
| `Movies/The Film (1999)/The Film (1999).mkv` | One `Movie`, folder-per-film |
| `Movies/The Film (1999)/The Film (1999) - part1.mkv`, `- part2.mkv` | **One** `Movie` with two parts, not two movies |

**Title and year** are extracted from the name by stripping a trailing or bracketed four-digit year
in the 1900–2099 range, then removing release-tag noise — resolution, source, codec, audio format,
language, release-group brackets. Both are documented regex sets upstream.
`[source: Emby.Naming/Common/NamingOptions.cs:147-161 @ v10.11.11]`

Atrium reimplements the *rules*, not the expressions (Principle IV). The acceptance test is
behavioural: given a corpus of real-world names, the same title and year come out.

**Multi-part files** are grouped into one item when they differ only by a part marker
(`part1`/`pt1`/`cd1`/`disc1`, and the `-a`/`-b` form). The parts become one item's media sources,
in order. Getting this wrong doubles a user's library, which is the most visible possible scanning
bug.

### 3.4 Series, seasons and episodes

Three levels, and the middle one is often not a directory.

| Layout | Resolves to |
|---|---|
| `Shows/The Series/Season 01/The Series - S01E02 - Title.mkv` | `Series` → `Season 1` → `Episode 2` |
| `Shows/The Series/The Series - S01E02.mkv` | Same, with the season **inferred** from the episode |
| `Shows/The Series/Specials/…` | `Season 0` — `Specials` is an alias for season zero `[source: Emby.Naming/TV/SeasonPathParser.cs:82 @ v10.11.11]` |
| `…S01E02-E03…` | **One** episode item spanning two numbers, not two items |

**Season and episode numbers** come from a family of patterns: `S01E02` and its separators,
`1x02`, `E02`/`EP02`, and date-based naming (`2024-01-31`) for daily shows. The reference carries
about thirty expressions plus eight for multi-episode files.
`[source: Emby.Naming/Common/NamingOptions.cs:320-360, 754-763 @ v10.11.11]`

**Ambiguity is resolved by position**, not by preference: the pattern is matched against the
filename first, then against the parent directory. A series called `24` must not have its title
read as an episode number, and this is exactly where naive scanners fail.

**Extras** — trailers, featurettes, deleted scenes, interviews, behind-the-scenes — are recognised
by suffix and by containing-folder name, and are attached to their parent rather than becoming
episodes. `[source: Emby.Naming/Common/NamingOptions.cs:160, 697 @ v10.11.11]`

**A missing season directory is normal.** So is a season directory with no episodes, and an episode
whose number exceeds any real count. None of these is an error; all of them appear in real
libraries.

### 3.5 Music

| Layout | Resolves to |
|---|---|
| `Music/Artist/Album/01 Track.flac` | `MusicArtist` → `MusicAlbum` → `Audio` |
| `Music/Artist/Album/CD1/01 Track.flac` | One album; tracks carry a disc number |
| `Music/Artist/Album (2001)/…` | Album with a year |

Music inverts the priority of the other two types: **embedded tags outrank the path**. A file's
`albumartist`, `album`, `title`, `track` and `disc` tags are authoritative where present, and the
directory layout is the fallback. This is not a preference — a well-tagged library with a flat
directory structure must produce the right albums, and a compilation must not become one album per
track.

Reading those tags is feature 004. This feature produces the structure and *asks* 004 for the
identity; the ordering of that conversation is a plan concern.

**Album artist versus track artist** is the distinction that makes compilations work: an album's
identity comes from its album artist, so a compilation with a different artist on every track is
one album, not many. Where no album artist is present, the album is attributed to `Various
Artists` only if the track artists actually differ.

### 3.6 Identity

Every item gets an identifier that is **32 lowercase hexadecimal characters** and **stable across
rescans** — including a rescan into an empty database.

Stability is the whole requirement. Clients key their caches, favourites and resume positions on
these strings; an identifier that changes when a library is rescanned silently discards a user's
state. Identifiers are therefore **derived from the item's stable identity**, never allocated.

The stable identity is:

| Item type | Derived from |
|---|---|
| Movie, Episode, Audio | The item's path, relative to its library root |
| Season | Its series' identity plus its season number |
| Series, MusicAlbum, MusicArtist | The library root plus the normalised name |
| CollectionFolder | The library's configured identity |

**Reproducing the reference's exact identifiers for the same file is not a goal**, and the reasoning
is in [behaviours §1.4](../../docs/compatibility/behaviours.md#14-item-identifiers-are-32-lowercase-hex-characters).

**Relative to the root, not absolute.** An operator who moves a library from `/mnt/a` to `/mnt/b`,
or who runs the same library from a container with a different mount point, must not lose every
identifier. The reference has this problem; Atrium does not have to inherit it.

> ⚠️ **OQ-2.** Whether path normalisation is case-sensitive. The reference lowercases by default and
> exposes a setting. Case-sensitivity changes every identifier, so the choice is permanent for a
> given library and must be recorded with it.

### 3.7 Sort names

Every item has a sort name, derived from its display name, that decides ordering in every list
feature 005 returns.

| Rule | `Name` | `SortName` |
|---|---|---|
| Leading articles are moved or dropped | `The Matrix` | `matrix` |
| Diacritics are folded | `Amélie` | `amelie` |
| Case is normalised | `iRobot` | `irobot` |
| Leading numbers sort numerically, not lexically | `2 Fast 2 Furious` | sorts before `10 Things…` |
| Punctuation is ignored | `Wall·E` | `walle` |

An explicit `SortName` from metadata (004) overrides all of it.

> ⚠️ **OQ-3.** The reference's article list is language-dependent and its exact behaviour is
> unverified. Ordering differences are visible in every list a client shows, so this is the
> highest-value single probe in the feature.

### 3.8 Scanning and change detection

A scan is **incremental by default** and **deterministic**: the same tree scanned twice produces
the same items, the same identifiers and the same ordering.

| Change on disk | The scan must |
|---|---|
| New file | Add the item, creating ancestors as needed |
| File modified (size or mtime) | Re-inspect and update, **preserving identity and user data** |
| File deleted | Remove the item, **preserving user data** in case it returns |
| File renamed | Treated as delete plus add — identity is path-derived, so it changes |
| Directory emptied | Remove the container item |

**User data outlives items.** A file that disappears and comes back — a re-download, a remount, a
temporarily unavailable network share — must not cost the user their favourites and resume
position. This is why user data is keyed by identity and retained after the item is gone.

**An unavailable root is not an empty root.** If a library root cannot be read at all, the scan for
that library fails loudly and changes nothing. Treating an unmounted share as "every item was
deleted" is the single most destructive thing a scanner can do.

A scan reports progress and a summary: items added, updated, removed, and files skipped with the
reason.

## 4. Data the feature owns

| State | Observable as (via 005) | Lifetime |
|---|---|---|
| Library configuration | `UserViews`, `CollectionFolder` items | Until the operator changes it |
| The item hierarchy | Every `/Items` response | Until the underlying files change |
| Item identity | The `Id` of every item | Permanent for a given path and library |
| Sort names | The ordering of every list | Recomputed on rescan |
| Scan state | Scan progress and summary | Per scan |

## 5. Acceptance criteria

1. The fixture library scans to exactly the expected set of items, with the expected parent-child
   structure, for all three collection types.
2. Scanning twice produces byte-identical item identifiers, and the second scan reports no changes.
3. Scanning into an empty database produces the same identifiers as the first scan did.
4. A multi-part film resolves to **one** item with two media sources, not two items.
5. `S01E02-E03` resolves to **one** episode item spanning both numbers.
6. A `Specials` folder resolves to season 0.
7. A series named with digits (`24`) keeps its title and does not acquire an episode number.
8. A two-disc album resolves to one album whose tracks carry the right disc numbers.
9. A compilation with a different artist per track resolves to **one** album.
10. Moving the library root to a different path leaves every identifier unchanged.
11. Deleting a file removes the item but leaves its user data recoverable; restoring the file
    restores the association.
12. A root that cannot be read fails the scan for that library and removes nothing.
13. Sort ordering matches the table in §3.7 for the fixture's awkward names.

## 6. Conformance

This feature has no endpoints, so L0/L1 do not apply. It is proven at **L2** against the fixture
library, and its results reach L3 through feature 005.

| Behaviour | Level | How it is proven |
|---|---|---|
| Resolution for all three types | **L2** | Fixture library with the awkward cases of §5 |
| Identity stability | **L2** | Scan, rescan, and scan-into-empty comparison (AC-2, AC-3) |
| Sort normalisation | **L2** | Table-driven, plus L3 through `/Items` ordering |
| Change detection | **L2** | Fixture mutated between scans |
| Destructive-failure safety | **L2** | Scan with a root made unreadable (AC-12) |

The fixture library is checked in as **metadata only** — directory trees, sidecars, and synthetic
media generated at build time. No copyrighted media, ever.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | The exact extension lists the reference honours | Nothing; conservative union until then | `tools/probe_library_extensions.py` |
| OQ-2 | Case sensitivity of path normalisation for identity | The identity rule of §3.6; permanent per library | A decision plus a recorded per-library setting |
| OQ-3 | The reference's sort-name normalisation, especially articles by language | Ordering parity in 005 | **`tools/probe_sort_names.py` — written, awaiting a run** |
| OQ-4 | Does the reference merge a folder-per-film layout when the folder and file names disagree? | An edge in §3.3 | Fixture comparison via the differential harness |
| OQ-5 | What the reference does with a file whose embedded tags contradict its path | §3.5 precedence | `tools/probe_music_precedence.py` |

## 8. References

- [docs/compatibility/behaviours.md §1.4](../../docs/compatibility/behaviours.md#14-item-identifiers-are-32-lowercase-hex-characters)
- [docs/glossary.md](../../docs/glossary.md) — item types and by-name items
- Jellyfin v10.11.11: `Emby.Naming/Common/NamingOptions.cs`, `Emby.Naming/TV/SeasonPathParser.cs`,
  `Emby.Naming/Video/`, `Emby.Naming/Audio/` — read for **rules**, never copied
