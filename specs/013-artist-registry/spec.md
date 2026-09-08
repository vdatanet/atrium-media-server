---
feature: 013-artist-registry
title: Artist registry
status: Implemented
created: 2026-09-07
updated: 2026-09-08
implemented: 2026-09-08
depends_on: [003, 004, 005]
---

# 013 — Artist registry

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Make `/Artists` and `/Artists/AlbumArtists` list **every credited artist, once per name**.

Today they list the artists the library tree carries — one per album artist, per library, created
by the scan from an album's own tags — reached through the credit that points at one. Two things
follow, and both are visible to a client:

- an artist credited in two music libraries is **two rows**, each listing that library's albums;
- a performer who is nobody's album artist has a **name on the track and no row at all**, so a
  client renders the name and cannot follow it.

Both are the two halves of the accepted gap at
[behaviours §5.3](../../docs/compatibility/behaviours.md#53-an-artist-in-two-music-libraries-is-two-rows),
which has named *"a deliberate identity migration"* as their closing mechanism since it was
written.

**The measurement says the migration is larger than the gap.** Read from outside on 2026-09-07,
both halves are properties of **what these two routes list** and neither needs an identifier this
project has already derived to be rewritten
`[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]`. The reference lists a
second population from these routes — one row per credited name, each an item of its own with no
parent — and keeps its per-library tree artists beside it, carrying the very duplication §5.3
records as this project's. So what closes the gap is a population this server does not have, and
not a rewrite of one it does.

**Client behaviour unlocked:** an artist screen reachable from any credit on any track, and one
entry per artist rather than one per library. The music client browses by artist first.

## 2. Scope

**In scope:**

- A **registry artist**: one row per credited artist name, server-wide, derived from the credits
  themselves rather than from a directory.
- What `/Artists` and `/Artists/AlbumArtists` list, and in what order.
- What a registry artist answers to `GET /Items/{itemId}`, and what a client sends to reach the
  albums and tracks credited to one.
- When a registry artist stops existing.

**Out of scope:**

- **The artist the library tree carries** — the item an album hangs off, identified per library
  since 003. It is not migrated, not renumbered and not removed. The reference carries the same
  two populations, with the same duplication, measured 2026-09-07: an artist can be a tree item
  *and* a registry row there, under two identifiers.
- Rewriting any identifier 003 already derived, which
  [003 plan §1](../003-library-configuration-and-scanning/plan.md) treats as the one operation
  this project does not perform.
- A `Person` row per artist name, and `/Persons` — adjacent, different, and
  [004's](../004-metadata-resolution/tasks.md).
- Fetching artist metadata or artwork from a provider — 004's.
- `/Genres`, `/MusicGenres`, `/Years` and `/Studios`: this feature adds a population to the
  machinery those already use and changes nothing about theirs.

## 3. Behaviour

Every claim in this section was measured from outside on a library with real music
`[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]`, on the same server whose
sizes were counted a day earlier
`[probe: tools/probe_real_library_shapes.py, Jellyfin 10.11.11, 2026-09-06]`.

### 3.1 What a registry artist is

**It is an item, not a row invented for one route.** Asked for by identifier, the reference answers
it as an item of the same type as a tree artist, with:

| Property | Value |
|---|---|
| type | the artist type — the same one the tree artist carries |
| parent | **none**. A registry artist hangs off nothing: it has credits, not a place in a tree |
| location | the ordinary one; nothing marks it as a different kind of thing |
| child count | present, **stable, and not a count**: `2` on a row credited on one track and no album, answering `2` again when asked a second time. So it is not [behaviours §3.25](../../docs/compatibility/behaviours.md)'s random number either — it is a number whose rule this reading could not attribute, and [OQ-2](#7-open-questions) is what this server answers instead |
| path | the server's **own metadata directory**, named after the artist — which is §5.3's source citation seen from outside for the first time |

The last row is the reference's identity rule made visible: its by-name identity is derived from a
path it would have to be able to create, which is why the fold replaces the characters a filename
cannot carry. This project derives no such path and reproduces the *fold*, which it has done for
genres, studios, people and years since 004 — so a registry artist's identifier is the by-name
identifier this server already knows how to derive, and nothing new is invented for it.

**A registry artist carries no path of its own here.** The reference's is a directory it writes
metadata into; this project keeps no such directory, and answering one would name a place that does
not exist ([behaviours §1.4](../../docs/compatibility/behaviours.md)'s neighbour: a value one server
derives from its own installation is not a value to copy).

### 3.2 What the two routes list

`/Artists` lists **one row per credited artist name**. Measured: 684 rows against 210 tree artists
on that library, 519 of the rows being names no tree artist carries, and **every one of the 75
distinct credit identifiers on 100 sampled tracks is one of those rows** — the credits and the
listing are one population.

`/Artists/AlbumArtists` lists **the names credited as album artists**, and it is **not a subset**
of the listing above. Measured: **506** rows, of which **495 are `/Artists` rows and eleven are
not** — and the eleven are what says which of the two readings of that residue is right. `a-ha`,
spelled there with a U+2010 rather than a hyphen-minus, is named as a performer by **no track** and
as an album artist by **one album**.

**So the two routes are two populations built from two credit fields, and neither contains the
other.** A track names its performers and an album names its album artists, and the two spellings
need not agree: the eleven are `Hall & Oates` against the pair the tracks name, `a-ha` against
`a-ha` in another hyphen, `The B-52s`, a diacritic and a CJK name. Ten of the eleven are registry
artists and one is a tree artist.

This server already keeps the two credits apart on every track it scans, so reproducing two
populations costs it the column it has rather than a second store.

**One row per name is the fold's doing and not a de-duplication step.** Two credits spelling one
artist two ways are one row, and the row's display name is the first spelling seen — the rule this
server applies to a genre today, and the reference's own
`[probe: tools/probe_by_name_normalisation.py, Jellyfin 10.11.11, 2026-08-27]`.

### 3.3 How a client reaches an artist's music

**By credit, and not by parent.** Measured on a registry row: asking for the items *under* it
answered **zero**; asking for the tracks *credited to* it answered the track it appears on. So the
two identifier filters a client sends after listing artists are what this population is reached
through, and a registry artist is never anybody's parent.

That is a difference from the tree artist, which **is** an album's parent and stays one.

### 3.4 Two populations, and both are the reference's

A tree artist and a registry artist may exist for one real artist, under two identifiers. Measured
on three tree artists the registry does not list by identifier: two of the three have a registry row
carrying the same folded name — one of them spelled `AC/DC` in the tree and `AC DC` in the registry,
which is the path-invalid substitution seen from outside for the first time — and the third has
none.

**So this feature does not make the two populations one, because the reference has not.** What it
changes is which of them these two routes list.

### 3.5 When a registry artist stops existing

A registry artist is **derivable**: it exists because something credits it, and nothing about it is
authored. One that nothing credits any more goes, and the next scan that reads that credit brings
it back under the same identifier, losing only which spelling was seen first — which is what the
reference loses too, and the rule this server already applies to the by-name rows it has.

## 4. Data the feature owns

*Observable state only.*

| What | Survives a restart | Notes |
|---|---|---|
| The set of artists `/Artists` lists | yes | Derived from the credits, so a rescan reproduces it exactly |
| Each one's display spelling | yes | The first spelling seen, as for a genre. Not authored and not editable |
| Each one's identifier | yes | Derived from the folded name, so it is the same identifier on every install of the same library — and the same one across a rescan, a move and a restore |

Nothing here is user data, nothing is authored, and nothing is lost by deleting all of it: the next
scan rebuilds it.

## 5. Acceptance criteria

1. `/Artists` answers **one row per distinct folded artist credit name** in the libraries the
   reading account may see — including the name of a performer who is nobody's album artist, which
   answers no row today.
2. An artist credited in two music libraries is **one row**, whose identifier does not name either
   library.
3. Two credits spelling one artist two ways — differing in case, or in a character a filename
   cannot carry — are **one row**, whose display name is the first spelling seen.
4. `/Artists/AlbumArtists` answers **one row per distinct folded album-artist credit name**, and
   answers no row for a performer who is nobody's album artist. It is **not a subset** of what
   `/Artists` answers and must not be implemented as one: an album artist no track names as a
   performer has a row there and none here, which is 11 of 506 rows on the library this was
   measured on.
   *(Restated 2026-09-07 at the plan gate, which measured the residue this criterion had assumed
   away: as drafted it called the listing a subset, and one request showed it is not.)*
5. A row's identifier answers `GET /Items/{itemId}` as an artist with **no parent**, and the same
   identifier is the one every credit on every track carries for that name.
6. Asking for the albums and tracks **credited to** a row's identifier answers that artist's music;
   asking for the items **under** it answers an empty list.
7. **The library tree does not move.** Every identifier 003 derived for a tree artist is unchanged,
   every album keeps the parent it had, and a listing of artists by item type still answers the
   tree's — which is what the reference answers there too.
8. A registry artist that nothing credits any more is gone by the end of the scan that removed the
   last credit, and a rescan of the same library reproduces the same rows with the same identifiers.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `GET /Artists` | **L3** | Golden responses on the fixture, plus the differential — this feature exists because a sweep measured the two populations apart |
| `GET /Artists/AlbumArtists` | **L3** | The same, narrowed to the album-artist credit |
| `GET /Items/{itemId}` on a registry artist | L2 | Golden response: a body with no parent |
| `GET /Items` filtered by an artist identifier | L2 | Fixture with a performer who is nobody's album artist |

**Both artist routes were declared `L2` in the v1 surface and are `L3` from 2026-09-07**, which
is a decision taken with this document rather than deferred to the plan gate. The population they
answer is the whole of what this feature changes, and a level that stayed at L2 would leave the
change proven against a fixture and unproven against the server it was measured from.

The promotion arrived payable rather than owed, which is what
[conformance.md](../../docs/compatibility/conformance.md#l3--differential) asks of one: both routes
already carry two request cases each, for both seats, so the sweep compares them the day the level
moves. The declared count goes from **eight to ten**, and the two tests that hold it —
`tests/conformance/test_routes.py`'s named set and `tests/unit/test_allowlist.py`'s per-identity
gate — move with it.

Levels are defined in [../../docs/compatibility/conformance.md](../../docs/compatibility/conformance.md).

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | **Answered and closed at the plan gate.** The two routes are two populations, built from the two credit fields, and neither contains the other: `a-ha` is named as a performer by no track and as an album artist by one album. AC-4 is restated, and §3.2 says so | — | Closed 2026-09-07 `[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]` |
| OQ-2 | **Answered and decided at the plan gate.** The number is **stable** — `2` twice — so it is not §3.25's random one; its rule is unattributed, so replicating it is not available; and answering nothing would be [§3.0.2](../../docs/compatibility/behaviours.md#302-what-is-never-acceptable)'s forbidden third behaviour. This server answers the true count, `0`, which is what the reference's own *"what is under this row"* answers | AC-5's body | Closed 2026-09-07; the divergence is [plan §1](plan.md) decision 2 and owes behaviours a row |
| OQ-3 | **Open, and it blocks nothing.** What does a registry artist answer for images, and what does a client render where a tree artist has a folder image and a registry row has no directory? The differential raised no image finding on either route, so nothing observed is wrong today — what is unmeasured is the case this repository's fixture has not got: an artist with artwork | Nothing. AC-5 is proven on the body's shape, and an image tag is 006's surface | A reading of a registry row's image tags on a library whose artists have artwork |
| OQ-4 | **Answered by the differential run, and it found a defect.** A registry artist carries **no** subtree statement: it has nothing beneath it, so `UnplayedItemCount` and the played rollup do not apply. This server sent `UnplayedItemCount: 0` on every row where the reference sends nothing — four findings on each artist route — and the rollup now stops at the population rather than the type | — | Closed 2026-09-07 `[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-07]` |
| OQ-5 | **Answered by the same run: the order and the count agree.** Neither route produced a `LENGTH` or an `ORDER` finding against the reference's own listing, on either seat and with a limit and without — so the ordering key and the by-name count behaviour of [§3.1](../../docs/compatibility/behaviours.md) are already what this server does, and no clause was needed for either | — | Closed 2026-09-07, same run |

## 8. References

- [behaviours §5.3](../../docs/compatibility/behaviours.md#53-an-artist-in-two-music-libraries-is-two-rows)
  — the gap, both halves, and the 2026-09-07 reading that reshaped its closing mechanism.
- `[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]` — what a row is, that
  the credits are the registry, how a row navigates, and the two populations on the reference.
- `[probe: tools/probe_real_library_shapes.py, Jellyfin 10.11.11, 2026-09-06]` — the sizes: 684
  rows, 210 tree artists, and every one of 134 sampled performer names having a row.
- `[probe: tools/probe_by_name_normalisation.py, Jellyfin 10.11.11, 2026-08-27]` — the fold, and
  the 97 of 97 identifiers it reproduces.
- `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1030-1075 @ v10.11.11]`,
  `[source: Emby.Server.Implementations/ServerApplicationPaths.cs:59 @ v10.11.11]` — the
  by-name identity §5.3 read from the source, whose observable half §3.1 measures.
- [004 §3.7](../004-metadata-resolution/spec.md) — the by-name machinery this population joins.
- [005 §3.9](../005-item-query-api/spec.md) — the two artist routes as they answer today.
