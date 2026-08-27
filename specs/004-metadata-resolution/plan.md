---
feature: 004-metadata-resolution
title: Metadata resolution — implementation plan
status: Accepted
created: 2026-08-27
updated: 2026-08-27
amended: 2026-08-27 by the tasks gate - section 6.8; by T1 - section 4; by T2 - section 6.2; by T3 - sections 5, 6.1 and 6.2; by T4 - section 6.7; by T5 - section 6.2; by T6 - section 6.1; by T7 - section 2; by T8 - section 6.4
spec_status_required: Accepted
spec_status_actual: Accepted
accepted: 2026-08-27
---

# 004 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour.

## 1. Approach

004 is the feature where Atrium first opens a media file and first reaches the network, and both
of those firsts are kept at arm's length from everything that already works. Five decisions carry
it.

**The merge is a pure function, and providers are readers.** A provider returns *fields it can
supply* for one item; the merge folds an ordered list of such results into one set of changes,
honouring locks and the refresh mode; and a single repository call applies the changes. Nothing in
`metadata/` writes to the item table directly — the architecture already forbids it — so the whole
of precedence, which is where this feature's subtle bugs live, is testable as a table of plain
values with no database, no files and no network in sight.

**The reader 003's seam anticipated is mutagen, wired in once and read once.** 003 defined
`MetadataSource` and shipped it answering nothing; 004 supplies the real implementation, and the
same read serves both consumers — the resolver asking *what album is this file in* and the refresh
asking *everything else*. One open per file per scan, memoised for the scan's lifetime. The two
constraints 003 wrote down for this seam are restated in §5 because breaking either is silent:
the seam is **not consulted** for a file whose `(size, mtime_ns)` has not moved, and **no
identity may derive from a tag**, or that skip becomes unsound.

**Remote identification is conservative, and an identifier ends the argument.** A provider id — from
a sidecar, a tag, or a previous refresh — is used directly and no search runs (spec §3.5 rule 1).
Without one, a search match is accepted only under a rule strict enough to be boring: §6.5 accepts
exactly one candidate and otherwise leaves the item unidentified, because AC-12 values a missing
match over a confidently wrong one.

**A rescan of an unchanged library makes zero network requests because nothing asks, not because a
cache answers.** 003's change detection already refuses to re-examine an unchanged file, so no
refresh is triggered and no provider is consulted — AC-13 falls out of the scan, and the response
cache exists for a different reason: retrying after a provider was down, and `Replace` refreshes
that re-fetch deliberately.

**The read-only guarantee is structural first and tested second.** Everything derived — provider
responses, downloaded artwork, the tag cache — lives under the server's data directory; no code
path in this feature constructs a writable handle inside a library root, and AC-15's test hashes a
fixture tree before and after a full scan-and-refresh to prove it stayed byte-identical.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–003 | [003 plan §2](../003-library-configuration-and-scanning/plan.md#2-inherited-decisions) |
| SQLite, repositories returning domain objects | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |
| `metadata/` owns providers, merge and cache; it must not write the item table directly | [architecture §1](../../docs/architecture.md#1-shape-of-the-system) |
| Ticks are the internal duration unit; conversion at ingestion exactly once | [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions) |
| Identifiers are derived, never allocated | [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions) |
| Configuration is a file, not an environment | [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions) |

**Deviations:** one, taken at T7. **`library/scan.py` imports `metadata/tags.py`**, so `library/`
now depends on a sibling that [architecture §1](../../docs/architecture.md#1-shape-of-the-system)
draws beside it rather than under it. 003 built `MetadataSource` as a Protocol precisely so the
scanner would not need to, and the alternative — leaving `PATH_ONLY` as the default and injecting
the real reader at a composition point — was tried and rejected: a scan whose reader has to be
supplied resolves a well-tagged music library from its directory names the first time anybody
forgets, and the symptom (albums named after folders) reads as a scanning bug rather than a
missing argument. The Protocol still carries the weight it was written for — `PATH_ONLY` is
passable, and every test that wants a path-only scan says so — and the dependency is one import of
one class.

## 3. Modules

```
src/atrium/
├── metadata/
│   ├── model.py          Field vocabulary, FieldValues, RefreshMode, ProviderIdentity — pure
│   ├── nfo.py            sidecar discovery and parsing (stdlib expat, §6.2)
│   ├── tags.py           embedded tags via mutagen; implements 003's MetadataSource
│   ├── artwork.py        local artwork discovery and the §6.4 name tables
│   ├── merge.py          per-field precedence, locks, refresh modes — pure
│   ├── tmdb.py           TMDB identify + fetch, behind §5's RemoteProvider
│   ├── musicbrainz.py    MusicBrainz identify + fetch, same contract
│   ├── remote.py         the shared HTTP plumbing: rate limiter, response cache, credentials
│   ├── byname.py         genre / studio / person / artist / year rows: fold, get-or-create, GC
│   ├── refresh.py        orchestration — the only caller of the write repository
│   └── cultures.py       the generated culture table for GET /Localization/Cultures
├── api/
│   └── localization.py   GET /Localization/Cultures
├── db/
│   └── migrations/       revision 0003: metadata columns, by-name types, join tables, cache
└── tools/
    └── generate_cultures.py   regenerates metadata/cultures.py from the ISO 639-2 registry
```

`model.py`, `merge.py` and `byname.py`'s fold are pure: values in, values out. That is what makes
the precedence matrix a table test (§8) rather than an integration suite.

**Dependencies this feature adds**, all runtime:

| Library | For | Why this one |
|---|---|---|
| `mutagen` | Embedded tags: ID3, Vorbis/Opus, FLAC, MP4 atoms | Pure Python, mature, reads every container 003 admits, exposes multi-valued frames as lists and embedded art as bytes. GPL-2.0-or-later, compatible with this project's GPL-3.0-or-later. The alternative was shelling to `ffprobe`, rejected in §10 |
| `httpx` | The two remote providers | Already in the dev group for tests; promoting it beats carrying a second HTTP client. Used synchronously (§6.8) |
| `Pillow` | Reading image dimensions at association time | `PrimaryImageAspectRatio` needs width and height (005 §3.2); 006 needs Pillow anyway for resizing, so this is the same dependency arriving one feature early. Header-only reads — no pixel decoding here |

## 4. Data model

Revision `0003_metadata_and_by_name`, reversible.

**`items` grows the resolved-metadata columns**: `overview`, `tagline`, `original_title`,
`production_year`, `premiere_date`, `runtime_ticks`, `official_rating`, `community_rating`,
`provider_ids` (JSON map, echoed as `ProviderIds`), `normalization_gain` (float, nullable),
`locked_fields` (JSON list of the reference's nine `MetadataField` values, §5),
`is_locked` (boolean), `refresh_pending` (boolean),
`metadata_refreshed_at`, and `name_folded`.

**`normalization_gain` is one number, not the JSON map this plan first specified.** T1's survey
settled OQ-5 against both halves of the guess: the reference reads exactly one replay-gain tag,
the track gain, and serves it as `NormalizationGain` on the item — so a `replay_gain` map holding
four values would be three columns' worth of storage that no response in the reference's shape
can ever carry, and a *dropped* column would lose the one value that 005 has to emit. Nullable
because the tag is usually absent: the reference omits the property entirely when it has no value
([behaviours §1.7](../../docs/compatibility/behaviours.md#17-a-null-property-is-absent-everywhere-by-one-setting)),
and a track with no tag must serialise the same way. The
reference's second source for this number — an opt-in loudness scan of the file, which overrides
the tag when it has run — is **not** in v1: it needs a decoder pass per track, which is 008's
dependency and not this feature's, and the divergence it creates is recorded with its argument in
[behaviours §5.4](../../docs/compatibility/behaviours.md#54-no-loudness-scan-so-a-track-without-the-tag-has-no-gain).

Pattern-driven columns, named as such so nobody normalises them away:

- `name_folded` — case- and diacritic-folded name. Exists **only** for 005's `searchTerm`,
  `nameStartsWith` and `/Search/Hints` matching; nothing in 004 reads it back.
- `production_year`, `premiere_date`, `community_rating`, `date_created` get indexes because 005
  filters and sorts on them (`years`, `minCommunityRating`, `sortBy=PremiereDate`, `Latest`).
- `refresh_pending` is indexed because every scan asks for the set (§6.8).

**The by-name types become rows in `items`.** The type check constraint gains `Genre`,
`MusicGenre`, `Studio`, `Person` and `Year`; `library_id` becomes nullable with a check tying
`NULL` to exactly those five types. They are items because 005 serves them as items — one query
machinery, one envelope, `GET /Items/{id}` works on a genre — and their identity is derived from
`(type, folded name)` alone, server-wide, by a new rule in `library/identity.py` beside 003's
four (`RULE_OF` extended; each function still refuses types belonging to another rule).
`MusicArtist` deliberately keeps 003's per-library rule — see the gap recorded in
[behaviours §5.3](../../docs/compatibility/behaviours.md#53-an-artist-in-two-music-libraries-is-two-rows).

**Join tables**, one per association the spec names, each carrying the display string *and* the
by-name row:

| Table | Columns | Serves |
|---|---|---|
| `item_genres` | `item_id`, `position`, `name`, `genre_item_id` → by-name row | `Genres`, `GenreItems`, 005 `genres`/`genreIds` |
| `item_studios` | `item_id`, `position`, `name`, `studio_item_id` | `Studios`, 005 `studioIds` |
| `item_people` | `item_id`, `person_type`, `sort_order`, `name`, `role`, `person_item_id` | `People` with role and ordering (spec §3.7 rule 2), 005 `personIds` |
| `item_artists` | `item_id`, `credit` (`artist` \| `album_artist`), `position`, `name`, `artist_item_id` | `Artists`, `ArtistItems`, `AlbumArtists`, 005 `artistIds`/`albumArtistIds`, and the `/Artists` versus `/Artists/AlbumArtists` distinction — which is a distinction between credits, not rows |
| `item_images` | `item_id`, `image_type`, `image_index`, `source_kind` (`file` \| `embedded` \| `remote`), `relative_path`, `width`, `height`, `tag` | `ImageTags`, `BackdropImageTags`, `PrimaryImageAspectRatio`, and everything 006 serves |

The string is stored **on the join row**, not only on the by-name item, because an item's own
response carries its own spelling (`Genres: ["sci-fi"]`) while the by-name row displays the first
spelling seen — two facts, two homes. `genre_item_id` points at a `Genre` row for movie and
series genres and a `MusicGenre` row for audio genres, which is what keeps `/Genres` and
`/MusicGenres` disjoint without a filter guessing from context.

`item_images.relative_path` is interpreted by `source_kind`: relative to the item's library root
for `file`, absent for `embedded` (the bytes live in the audio file), relative to the data
directory for `remote` (§6.5). `tag` is 32 lowercase hex — the first 16 bytes of the SHA-256 of
the image bytes — computed at association time so 005 can emit `ImageTags` before 006 exists, and
stable across rescans because the bytes are (006 AC-2).

**`provider_cache`** — `provider`, `request_key`, `payload`, `fetched_at`, `expires_at`, primary
key `(provider, request_key)`. Rows are data somebody else's server sent; they are evictable at
any time and the schema promises nothing about them.

## 5. Contracts

**`metadata.model`** — the vocabulary:

```python
class Field(StrEnum): NAME, SORT_NAME, OVERVIEW, TAGLINE, ORIGINAL_TITLE, YEAR, PREMIERE_DATE,
    RUNTIME, OFFICIAL_RATING, COMMUNITY_RATING, GENRES, STUDIOS, PEOPLE, PROVIDER_IDS,
    ARTISTS, ALBUM_ARTISTS, INDEX_NUMBER, PARENT_INDEX_NUMBER, IMAGES, ...

FieldValues = Mapping[Field, object]   # absent key == "nothing to say"; None/""/[] are not values
class RefreshMode(StrEnum): DEFAULT, REPLACE, LOCAL_ONLY

class MetadataField(StrEnum): CAST, GENRES, PRODUCTION_LOCATIONS, STUDIOS, TAGS, NAME, OVERVIEW,
    RUNTIME, OFFICIAL_RATING                     # the reference's nine, spelled its way
LOCK_OF: Mapping[Field, MetadataField]           # partial in both directions - see 6.1
```

**`Field` and `MetadataField` are two vocabularies, not one renamed.** `Field` is what this
feature merges; `MetadataField` is what the reference locks, it is wire surface
`[spec: MetadataField]`, and it is what `locked_fields` stores — so a lock read from a sidecar
round-trips through Atrium unchanged, including a value like `ProductionLocations` that guards
nothing here. The relation between them is §6.1's first measured point.

**Local sources** are one function each, pure given their bytes:

```python
def read_nfo(path: Path, kind: ItemType) -> NfoResult          # FieldValues + warnings
def read_tags(path: Path) -> TagResult                          # FieldValues + warnings + art
def find_artwork(item_dir: Path, stem: str | None) -> list[ArtworkFile]
```

**`metadata.tags.TagSource`** — the implementation of 003's `MetadataSource`. Two clauses restated
from [003's tasks](../003-library-configuration-and-scanning/tasks.md#what-this-feature-owes-the-next-ones),
because they are load-bearing and invisible: the scan consults it **only** for files whose signal
moved, so nothing this source answers may feed an identifier; and its `tags_for` mapping keeps
003's key vocabulary exactly (`albumartist`, `album`, `title`, `track`, `disc`, `artist`, `year`),
including the rule that an empty string is a tag that is present and empty.

**Remote providers**:

```python
class RemoteProvider(Protocol):
    name: str                                        # "Tmdb", "MusicBrainz" — ProviderIds keys
    def enabled(self) -> bool | str                  # True, or the reason it is not (AC-9)
    def identify(self, subject: Subject) -> Identity | NoMatch | Ambiguous
    def fetch(self, identity: Identity) -> FieldValues
```

`identify` is skipped entirely when the subject already carries this provider's id (spec §3.5
rule 1). Both methods go through `metadata.remote`'s one HTTP door, which owns the rate limiter,
the cache, the timeout and the credentials — a provider module never constructs a client of its
own, which is what makes "no test reaches the network" enforceable by construction.

**The write path** — `MetadataRepository` in `db/repositories.py`:

```python
def apply(self, item_id: str, changes: MetadataChanges) -> None
def ensure_by_name(self, kind: ItemType, spelling: str) -> str        # folds, reuses, returns id
def collect_by_name_garbage(self) -> int                              # rows nothing references
```

`refresh.refresh_library(library, mode, providers, session)` is the orchestrator and the only
caller of `apply`. `library/scan.py` gains one call site: after a scan commits, it hands the
changed and new item ids to `refresh`, and `deep` hands everything.

**`GET /Localization/Cultures`** (`api/localization.py`) — authenticated via the existing
`require_user` seam, returns `metadata.cultures.CULTURES` serialised through the compat base
model. Static, no parameters, `[spec: GetCultures]`.

## 6. Algorithms

### 6.1 The merge

Inputs: the item's current values, its `locked_fields`, the mode, and the ordered provider
results (spec §3.1's chains; the order is data in `refresh.py`, not branching in `merge.py`).

For each field, walk the chain and take the **first value** — where None, `""`, `[]` and a
whitespace-only string are not values (spec §3.1) — then apply the mode:

| | field locked | field empty on item | field has a value |
|---|---|---|---|
| **Default** | keep | fill | keep |
| **Replace** | keep | fill | overwrite |
| **Local only** | keep | fill from local providers only | keep |

List-valued fields (genres, people, studios, artists) are taken **whole from one provider**, never
unioned across providers: a sidecar naming two genres and TMDB naming five is a film with two
genres. Union produces lists nobody wrote and nobody can fix — the same reasoning as per-field
merging, one level down.

**Three things T3 measured in the reference's own merge**
`[source: MediaBrowser.Providers/Manager/MetadataService.cs:1009-1140 @ v10.11.11]`, all of which
this section had wrong and two of which change what T6 builds:

1. **Locking is coarser than merging, and the two vocabularies are not the same size.** A lock is
   one of nine `MetadataField` values `[spec: MetadataField]`; a merge field is one of this
   feature's twenty-one. Eight of the nine guard a field 004 resolves, each guarding **exactly
   one** — `Name` does not cover the sort name or the original title, and the reference overwrites
   the original title unconditionally on the line after the name lock. Thirteen of the twenty-one
   fields cannot be locked at all. `metadata/model.py`'s `LOCK_OF` is that map, and the table above
   reads "field locked" through it rather than through a lock per field.
2. **`Studios` and `Tags` are union-merged when not replacing** — `Concat(...).Distinct(ordinal
   case-insensitive)` — while `Genres` and `People` are whole-replace. So §10's rejection of
   union-merge is right about genres and **wrong about two of the four list fields**, and the
   reference's shape wins: reproducing a list a client will read is Principle I, and the argument
   in §10 was about a design we do not get to choose. T6 implements per-field list behaviour, not
   one rule for all lists.
3. **A `Runtime` from metadata is discarded for audio and video items.** The reference guards the
   assignment with `target is not Audio && target is not Video`, because a media file's runtime
   comes from probing it. An `.nfo` `<runtime>97</runtime>` on a film therefore changes nothing in
   the reference, and honouring it here would be a delta — visible, because 004 has no prober and
   Atrium's films would carry a runtime the reference's do not. §6.2 keeps parsing the element;
   T6 applies it only to the types the reference applies it to.

Where the lock arrives from is §6.2's business, and it had no answer until T3 asked: spec §3.6
gives locks no HTTP route, so **the sidecar is the only channel in v1**.

**One ambiguity in spec §3.1's table, left visible rather than resolved.** The film column lists
*Path-derived* **twice**, at positions 3 and 5. In a first-value-wins walk a repeated source is a
no-op — the second occurrence can only win a field the first already lost — so `CHAIN_OF`
reproduces the table literally and behaves as though it did not. The two readings differ in
exactly one observable way, and it is worth settling before 005 serves the result: with `PATH` at
position 3, ahead of the remote provider, **a `Replace` refresh cannot take a film's name from
TMDB** — the filename always wins. If the intended reading was `[nfo, TMDB, path]`, the film's
name under `Replace` comes from the provider instead. T14 holds `Replace` end-to-end and is where
this gets measured against the reference rather than argued.

### 6.2 Sidecars

Discovery per the spec §3.2 table, tried in order beside the item's part-zero file. Parsing is
stdlib, and **the parser has to be built rather than called**, because the sentence this plan
first carried here — that `ElementTree` "refuses DTDs and entity definitions outright" — is not
true. Measured against the three fixtures T2 checked in for it (Python 3.14.6, expat 1.3.0):

| Input | `ElementTree.parse` as it comes |
|---|---|
| A document type declaration defining an entity | **Parses, and expands the entity into the value** |
| The same, but the entity is external (`SYSTEM "file:///…"`) | **Raises** `ParseError: undefined entity` — no external entity is ever fetched, so file disclosure is impossible, but by *failing* rather than by refusing the declaration |
| Nested entities, five levels of ten | **Parses, and expands 400 bytes into 200,000 characters** |

So the XXE class is closed by default and the **expansion** class is wide open: a `.nfo` a user
drops into a library can cost a scan an arbitrary amount of memory. What makes the original
sentence true is one handler, all stdlib — an `xml.parsers.expat` parser feeding an
`ElementTree.TreeBuilder`, with `StartDoctypeDeclHandler` raising and
`SetParamEntityParsing(XML_PARAM_ENTITY_PARSING_NEVER)` — after which **every** document carrying
a declaration is refused before a single entity is expanded, and all three fixtures land on the
same path: warn, name the file, continue (AC-4). No real `.nfo` has a DTD; refusing the whole
construct costs nothing a user will notice and removes the class rather than the instance.

A sidecar over 5 MB is treated as malformed rather than read, for the same reason one size up: no
real `.nfo` is megabytes, and a large file should cost a warning, not the scan.

Field mapping: `title`→name, `sorttitle`→sort-name override (through 003 §3.7.3's treatment),
`originaltitle`, `year`/`premiered`, `plot`→overview, `tagline`, `runtime` (minutes→ticks at
ingestion, per architecture §4), `mpaa`→official rating, `rating`→community rating, `genre`*,
`studio`*, `tag`*, `actor` (`name`, `role`, document order), `director`, `writer`, and
`uniqueid`/`tmdbid`/`imdbid`/`musicbrainz*` → `provider_ids`, and — **added by T3, because
nothing else in the feature could supply them** — `lockdata` → `is_locked` and `lockedfields` →
`locked_fields`, the latter pipe-separated, matched case-insensitively against the nine
`MetadataField` values, with an unknown token **dropped rather than refused**
`[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:374-391,434-436 @ v10.11.11]`. Spec
§3.6 gives locks no HTTP route, so without those two elements AC-10 — "a locked field survives a
Replace refresh" — had no way to get a lock onto an item at all. Multiple `<genre>` elements are the
multi-valued form, **and a single element containing `/` is split as well** — one genre per part,
each trimmed, empties dropped
`[source: MediaBrowser.XbmcMetadata/Parsers/BaseNfoParser.cs:566-583 @ v10.11.11]`. This section
said the opposite until T5 read the parser it was citing. Not splitting would give Atrium a genre
called `Science Fiction / Fantasy` that no reference server has, on a file both of them read; the
cost of splitting — a genre that legitimately contains a slash becomes two — is the reference's to
own. The rule applies to `<genre>` and `<credits>` and to nothing else.

Three more leniencies T5 measured, each one a reasonable implementation gets wrong by reasoning:
a `<year>` at or below **1850** is discarded, so the `<year>0</year>` that generators write for
"unknown" leaves the year to the next provider; `<premiered>` and its three synonyms are parsed in
**one exact format** (`yyyy-MM-dd`) and **fill** the year rather than overwriting it; and
`<director>` and `<writer>` split on `|` or `;` when either is present and on `,` otherwise, which
is what keeps `Matthew, Jr.` one person in a list written with pipes
`[source: MediaBrowser.Controller/Extensions/XmlReaderExtensions.cs @ v10.11.11]`.

### 6.3 Embedded tags

mutagen, by container: ID3v2 (MP3, and ID3-in-AIFF/WAV if 003 admits them), Vorbis comments
(FLAC, Ogg, Opus), MP4 atoms (M4A/ALAC). Read: title, artists, album artist(s), album, track and
disc as `n`/`n-of-m`, year/date, genre(s), composer, MusicBrainz ids, ReplayGain, and embedded
cover art.

**Multi-valued stays multi-valued** (spec §3.3, AC-6): Vorbis repeats keys, ID3v2.4 separates
with NUL, MP4 repeats atom entries — each read as a list, and nothing ever joins them with a
separator. The reverse also holds: a single value containing `;` stays one artist, because
guessing at separators is how `AC/DC` becomes two artists.

An unreadable tag block — truncated file, unknown ID3 version, mojibake that raises — is the
warn-and-continue path (spec §3.3), and the item resolves from what remains.

### 6.4 Local artwork

The spec §3.4 name tables, matched case-insensitively over `jpg`, `jpeg`, `png`, `webp`. Those
tables were **corrected at T8** against the reference's own
`[source: MediaBrowser.LocalMetadata/Images/LocalImageProvider.cs:18-400 @ v10.11.11]`; the
differences that change code rather than wording:

| This section said | It is |
|---|---|
| One Primary list for every type | **Five.** A music album and artist try `folder` first and answer to `jacket` and `albumart`; a series answers to `show`; a film to `movie`; a person only to `folder` and `poster` |
| The per-item form is `<stem>-poster` | **The bare `<stem>` as well, and it is tried first** — before every folder name. The prefixed form works for every name, not only `poster` |
| Thumb is `thumb`, `landscape` | **`landscape`, `thumb`** |
| Disc is `disc`, `cdart` | Type-dependent: an album tries **`cdart` first**, a film tries `disc`, `cdart`, `discart` |
| Backdrops are `fanart`/`backdrop`/`background` | Four families — `art` as well — plus an `extrafanart` folder taken whole. Their numbered variants use a dash (`fanart-1`) **except `backdrop`, which does not** (`backdrop1`) |
| Numbered backdrops keep their numeric order | They do, and the **scan stops after three consecutive misses** rather than at the first gap, so a library that lost `fanart-3` keeps `fanart-4` onwards |

First name that exists **and is readable** wins within each type — readability is part of the rule
rather than a check after it, or one corrupt `poster.jpg` leaves an item with no image while a
good `folder.png` sits beside it. Backdrops accumulate rather than first-winning, and their
`image_index` is the position in the found list rather than the number in the file name, because
those numbers are sparse in real libraries and `BackdropImageTags` is a dense array. An episode, a
track and a person get a Primary and nothing else.

Embedded cover art becomes `Primary` only when no file-based Primary exists (spec §3.4).
Dimensions are read with Pillow at association time — header parse, no decode — and the content
tag is hashed from the same bytes. A file Pillow cannot identify is skipped with a warning; an
association is never written without its dimensions and tag.

### 6.5 TMDB

**Identify:** already-carried id wins without a request. Otherwise one search request —
movie by (title, year), series by (title, year) — and the match rule: normalise both sides
(casefold, strip diacritics and punctuation), keep candidates whose title or original title
equals the query and whose year, when both sides have one, differs by at most 1. **Exactly one
survivor is a match; zero is unidentified; two or more is ambiguous and therefore unidentified**
(AC-12). No popularity weighting, no "top result" — a rule with a knob is a rule that guesses.

**Fetch:** one request per identified movie (`append_to_response=credits,images,release_dates`),
one per series plus one per season. Episodes map by `(season, episode)` from the season payload —
no per-episode requests. Fields per the spec §3.2 vocabulary; people from cast (ordered) and crew
(directors, writers); `official_rating` from the release-dates certification for the configured
country.

**Artwork:** the selected poster, up to three backdrops, and the logo are downloaded to
`<data>/metadata/artwork/<item id>/…` — never into a library root — recorded as `remote`
associations with tag and dimensions from the downloaded bytes. Bounded: at most five files per
item, 20 MB each, and a refresh that finds them already present by tag downloads nothing.

**Credentials:** an API key in the server configuration file. Absent key → `enabled()` returns
the reason, the provider sits out, and the scan report says so once per scan (AC-9).

### 6.6 MusicBrainz

Same contract, different budget. MusicBrainz's public etiquette is one request per second with an
identifying `User-Agent`, and a naive per-track lookup would turn a 5,000-track first scan into
ninety minutes of waiting. So the unit of identification is the **album**: release-group search by
(album artist, album title) under the same exactly-one rule as §6.5, then one release-group fetch
for canonical title, date and artist credits. Tracks take their MusicBrainz recording id **only**
from their own tags (spec §3.5 rule 1); v1 never searches per track. Artists get one lookup each,
by tag-carried id or by name within the album's credits.

No artwork: the spec scopes MusicBrainz to names, dates and relationships, and music art comes
from files and embedded covers.

### 6.7 By-name rows

`ensure_by_name` folds the spelling — lowercase, path-invalid characters (`" < > | : * ? \ /` and
controls) to spaces, trim, trailing dots off — derives the id from `(type, folded)`, and inserts
the row with the **incoming** spelling as display name only when no row exists. This reproduces
the reference's observable envelope exactly — one item per case-folded name, first spelling
displays, diacritics distinguish
([behaviours §2.18](../../docs/compatibility/behaviours.md#218-two-spellings-of-one-genre-are-one-item)) —
without reproducing its id derivation, which differs everywhere by design (behaviours §1.4).

**The fold itself lives in `library/identity.py`, not here** — moved by T4, because the identity
*is* the fold: `for_by_name` hashes exactly what `ensure_by_name` keys its rows on, and two
definitions of one fold is how a spelling ends up merging into one row and deriving another one's
id. `byname.py` calls `fold_by_name`; it does not define a second one. The order of the steps is
the reference's and matters for names nobody sensible writes — it trims, *then* removes trailing
dots, and does not trim again — so `Drama. . .` and `Drama. .` are two rows there and two here
`[source: MediaBrowser.Controller/Entities/Genre.cs:84-92 @ v10.11.11]`
`[source: Emby.Server.Implementations/IO/ManagedFileSystem.cs:21-27 @ v10.11.11]`.

Garbage collection runs at the end of a refresh transaction: a by-name row referenced by no join
row is deleted. Spec §4 gives their lifetime as "until no item references them"; deletion is safe
*here*, unlike 003's containers, because a by-name row is derivable — the next reference recreates
it, id and all, losing only which spelling came first, which is exactly what the reference loses.

**`Year` rows ride the same machinery** with the year's digits as the name. They are the one kind
with no join table: membership is `items.production_year`, and the row exists so `/Years` and
`GET /Items/{yearId}` have an item to return. Created on refresh, collected when no item carries
the year.

### 6.8 Refresh orchestration

A refresh processes a batch of item ids after the scan that produced them commits:

1. Local sources first, always: sidecar, tags, artwork. Cheap, offline, and they decide what is
   still missing.
2. Remote providers only where the mode allows, the provider is enabled, **the local pass left
   fields wanting that a provider could supply**, and either an id is carried or identification
   is worth attempting (a subject with a title). The third clause is where AC-1 lives — a
   fully-sidecared film makes zero network requests because nothing is missing, not because a
   cache absorbed the fetch — and it was implicit in step 1's "they decide what is still
   missing" until the tasks gate made it a condition rather than a remark.
3. Merge (§6.1), then one `apply` per item; writes batched per library like the scan's own.

Remote I/O runs on a small thread pool (four workers) feeding through `metadata.remote`, which
enforces per-provider token buckets — TMDB 4 requests/second, MusicBrainz 1/second — and the
response cache (14-day TTL; `Replace` bypasses freshness and refills it; identity lookups by id
cache indefinitely, an id does not change meaning). A provider failure marks the item
`refresh_pending` and never blanks anything (AC-8); the next scan retries pending items even when
their files did not change.

HTTP is synchronous httpx. The scan is synchronous, the pool gives the parallelism worth having,
and the rate limiters — not connection concurrency — are the throughput ceiling anyway; an async
client would complicate every test to speed up nothing.

### 6.9 Cultures

`metadata/cultures.py` is a generated table, committed, with a header naming its source and date.
`tools/generate_cultures.py` rebuilds it from the Library of Congress ISO 639-2 registry: rows of
`Name`, `DisplayName`, `TwoLetterISOLanguageName`, `ThreeLetterISOLanguageName`,
`ThreeLetterISOLanguageNames` per `[spec: CultureDto]`, with the B/T split (`fre`/`fra`) carried
in the plural list the way the reference carries it — it builds from its own embedded ISO 639-2
file `[source: Emby.Server.Implementations/Localization/LocalizationManager.cs:27,102-166 @ v10.11.11]`.
Membership differences against the reference's list are differential material for 010, not
guessed at here.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Malformed sidecar | Parser raises | Warn with the file path; item resolves from the rest (AC-4) | User fixes the file; next scan picks it up |
| Sidecar over the size cap | Size check before parse | Same as malformed, saying why | Same |
| Unreadable tag block | mutagen raises | Warn; continue with path-derived values (spec §3.3) | Same |
| Provider id the provider does not know | 404 on by-id fetch | Keep local metadata, warn naming file and id; **no fallback search** — the id is the user's decision (spec §3.2) | User corrects the sidecar |
| Ambiguous search | §6.5 rule | Item unidentified, counted in the report (AC-12) | Manual identification is post-v1; a sidecar id resolves it now |
| Provider down / timeout / 5xx | httpx error | Item keeps local metadata, marked `refresh_pending` (AC-8) | Retried next scan |
| Provider 429 | Status | Back off, requeue; bucket rate halves for the rest of the scan | Automatic |
| No credentials | `enabled()` | Provider sits out; report says so once (AC-9) | Operator adds the key |
| Corrupt or unidentifiable image | Pillow raises | Skip the association, warn | User replaces the file |
| Artwork download over the cap | Size check | Skip that image, warn | — |
| Cache row unreadable | Decode error | Treat as miss, overwrite | Automatic |

Warnings surface through 003's scan report vocabulary — they are notices in the sense of
[003 plan §7](../003-library-configuration-and-scanning/plan.md#7-failure-handling): the item
exists, and something about it deserves an operator's eye.

## 8. Testing strategy

| Spec AC | Test |
|---|---|
| 1, 2, 3, 4 | Fixture sidecars — full, sparse, id-bearing, malformed — against a counting fake provider that fails the test if consulted (1, 3) |
| 5 | A fixture track whose tags contradict its path, resolved through the real `TagSource` |
| 6 | A track with three artists in each container format |
| 7 | Fixture artwork of every name in §6.4's tables; assert type, index, dimensions, tag |
| 8 | Providers stubbed to raise; full scan; every item keeps local values, `refresh_pending` set |
| 9 | Providers constructed with no credentials; scan completes; report names them |
| 10, 11 | The §6.1 mode × locked × empty matrix, as a table test over the pure merge |
| 12 | Recorded search responses with two plausible candidates; item stays unidentified |
| 13 | Scan, refresh, rescan; a counting transport asserts **zero** HTTP calls in the rescan |
| 14 | Two fixture files spelling one genre two ways; one by-name row; first spelling displays |
| 15 | SHA-256 over every file in the fixture tree before and after scan-and-refresh |
| 16 | The existing no-network guard in `tests/conftest.py` covers the suite wholesale |

**Fixtures.** Sidecars and artwork are plain checked-in files. Tagged audio starts from four tiny
checked-in template containers — silent, generated once by us, a few KB each, with the generation
command recorded beside them — and each test case copies a template and writes its tags with
mutagen at test time: deterministic bytes in, deterministic tags on top. 003's placeholder files
stay untouched; they exercise scanning, these exercise reading.

**Recorded provider responses** are checked-in JSON keyed by request, served through the same
transport seam the real providers use. The opt-in live test (`needs_reference` marker) replays
one movie and one album against the real services and diffs the parsed fields — never in CI, per
the spec's conformance section.

**Golden**: `GET /Localization/Cultures` byte-compared, and the casing and unit sweeps pick up
every response model this feature adds.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A wrong remote match poisons an item's metadata | Medium | High — confidently wrong, user-visible | §6.5's exactly-one rule; sidecar ids authoritative; AC-12 pinned by test |
| Refresh overwrites a user's manual correction | Medium | High — trust, permanently | Locks honoured in every mode; the §8 matrix has a row for each combination |
| Provider API drift breaks parsing | Medium | Medium | Recorded fixtures pin the parser; the opt-in live test detects drift when run |
| Tag chaos: containers disagree about multi-values | High | Medium — joined artists, split artists | Per-format fixture tracks; the no-splitting rule of §6.3 tested both ways |
| MusicBrainz rate limit makes first scans crawl | High | Medium | Album-level budget (§6.6); pending queue continues across scans; report shows progress |
| Artwork downloads balloon the data directory | Low | Medium | Five files, 20 MB each, per item; re-downloads suppressed by tag |
| A write path into a library root appears later | Low | Catastrophic | AC-15's tree hash in CI; no writable-handle helper in `metadata/` at all |
| By-name GC deletes a row a concurrent scan needs | Low | Low — row recreated derivably | GC inside the refresh transaction; SQLite's single writer serialises the two |

## 10. Alternatives considered

**`ffprobe` for embedded tags.** 008 will ship it anyway, and it reads everything. But it is an
external process per file exactly where 003's scan is hot, its tag output normalises multi-values
into joined strings — destroying the thing AC-6 exists to keep — and it would put a subprocess
dependency inside the scan path 003 deliberately kept pure. mutagen reads the same tags in-process
and hands lists back as lists.

**Async providers.** The scan is synchronous and the rate limiter is the ceiling; async would buy
concurrency nothing can spend and cost every test a loop.

**Per-track MusicBrainz identification.** More correct for compilation edge cases, and it turns a
first scan into hours at the etiquette rate. The album-level budget covers the normal case;
track-level ids still work when tags carry them.

**Union-merge for list fields.** Feels generous — every source contributes — and produces genre
lists no single source wrote, which a user cannot correct by fixing any one file. First-provider-
wins keeps every list attributable.

**Corrected by T3, and the correction is the more interesting half.** This was never ours to
decide for all four lists: the reference unions `Studios` and `Tags` and whole-replaces `Genres`
and `People` `[source: MediaBrowser.Providers/Manager/MetadataService.cs:1113-1130 @ v10.11.11]`.
The argument above is sound and applies to the two the reference happens to agree with; for the
other two, Principle I says reproduce. §6.1 carries the per-field rule, and this entry stays
because the reasoning is still worth having when a list field with **no** reference behaviour
turns up.

**One JSON blob for all metadata.** One column, no migration churn — and 005 filters and sorts on
year, rating and genre, which would turn every query into JSON extraction over full scans. The
002 policy-blob precedent cuts the other way here: those properties are echoed, these are queried.

**Global artist rows, matching the reference.** The reference's artists are server-wide by-name
items; 003's are per-library, and rewriting that in 004 means migrating identity for rows 003
already wrote. Kept per-library, and the observable consequence — an artist in two music
libraries lists twice — is recorded as an accepted gap with its argument in
[behaviours §5.3](../../docs/compatibility/behaviours.md#53-an-artist-in-two-music-libraries-is-two-rows),
not silently shipped.

**Skipping remote artwork in v1.** Tempting — it removes downloads entirely — and it fails the
spec's own purpose: a library of films without posters is the "list of filenames" §1 promises to
end. Bounded downloads into the data directory keep the read-only guarantee whole.
