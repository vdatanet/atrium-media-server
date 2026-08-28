---
feature: 005-item-query-api
title: Item query API — implementation plan
status: Accepted
created: 2026-08-27
updated: 2026-08-27
amended: 2026-08-27 by the tasks gate - sections 6.6 and 8; 2026-08-28 by T9 - sections 5 and 6.5; by T10 - section 6.12; by T11 - section 6.8; by T12 - sections 6.9 and 8
spec_status_required: Accepted
spec_status_actual: Accepted
accepted: 2026-08-27
---

# 005 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour.

## 1. Approach

Seventeen endpoints, and the design's whole job is to make them one thing. Four decisions carry
it.

**Every list endpoint compiles into the same query.** A typed `ItemQuery` describes scope,
filters, ordering and paging; one repository turns it into SQL and returns hydrated domain items
with the pre-paging count; one DTO builder turns those into the wire shape. The per-endpoint code
that remains is parameter parsing and the choice among the four response shapes — which is the
size of code that seventeen endpoints can keep honest. A bespoke query per endpoint is how
`/Genres` and `/MusicGenres` come to disagree about visibility.

**The wire mechanics this feature forces get solved once, in `compat/`.** 005 is where query
parameters start carrying the API's weight, and three measured behaviours have to hold for every
route at once: parameter **names** match case-insensitively
([behaviours §1.15](../../docs/compatibility/behaviours.md#115-query-parameter-names-match-case-insensitively)),
an unrecognised **token** in an enum-valued parameter drops that filter while an unparseable
**type** is a `400` (behaviours §1.12), and the `400`/`404` bodies are the problem-details shape
(behaviours §1.11) — which the framework answers with a `422` and a different body unless told
otherwise. All three are framework-default fights, and all three land in `compat/` rather than in
any route.

**Ordering is total, built from the reference's own keys.** The requested keys, then `Name` where
the reference chains it, then the id — the divergence-from-a-defect argued in
[behaviours §3.6](../../docs/compatibility/behaviours.md#36-ties-are-engine-resolved-and-paging-the-artist-sorts-loses-rows--class-b-diverged)
and measured before this plan was written. Visibility is likewise one predicate used by every
query: 002's policy, 003's soft deletion, and the §5.2 container rule this feature inherited.

**What must be deterministic is deterministic by construction, not by luck.** `Random` is a
per-request seed shuffling ids in process, so a test can inject the seed; `Similar` and
`InstantMix` are explicit formulas (§6.10) with total tie-breaks. The reference's `Random` is a
fresh engine shuffle per request `[probe: tools/probe_sort_stability.py, Jellyfin 10.11.11,
2026-08-27]`, which a per-request seed is indistinguishable from.

**One sequencing gap, named rather than papered over:** `Fields=MediaSources` and `MediaStreams`
cannot be truthfully populated until 008 probes media. Until then those two fields serialise as
absent — the same as a server that has not probed yet — and 008 closes the gap where the data is
born. Emitting a plausible-looking stub would violate Principle VI's "it never lies".

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–004 | [004 plan §2](../004-metadata-resolution/plan.md#2-inherited-decisions) |
| The authentication seam and its refusal shapes | [002 plan §5](../002-authentication-users-and-sessions/plan.md#5-contracts), `api/deps.py` |
| Repositories return domain objects; no ORM row crosses the boundary | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |
| PascalCase via the compat base model; nulls omitted globally | [001 plan](../001-server-identity-and-discovery/plan.md), behaviours §1.7 |
| The metadata columns, join tables and `name_folded` this feature queries | [004 plan §4](../004-metadata-resolution/plan.md#4-data-model) |
| Containers that lost every file are filtered here, not removed there | [behaviours §5.2](../../docs/compatibility/behaviours.md#52-a-container-that-has-lost-every-file-is-not-removed) |

**Deviations:** none.

## 3. Modules

```
src/atrium/
├── domain/
│   └── queries.py        ItemQuery, SortBy, Filter, SortOrder — pure vocabulary
├── db/
│   └── item_queries.py   ItemQueryRepository: compile ItemQuery -> SQL, hydrate, count
├── compat/
│   ├── query_params.py   case-canonicalisation (§6.12), enum-token dropping, the
│   │                     ignored-parameter recorder (spec §3.3, AC-15)
│   └── errors.py         grows the problem-details shape for 400/404 (behaviours §1.11)
└── api/
    ├── item_models.py    BaseItemDto, UserItemDataDto, NameGuidPair, the envelope, SearchHint
    ├── item_dto.py       domain Item -> BaseItemDto: field gating, UserData, image tags
    ├── items.py          GET /Items, GET /Items/{itemId}
    ├── user_library.py   GET /Items/Latest
    ├── user_views.py     GET /UserViews
    ├── resume.py         GET /UserItems/Resume
    ├── tv_shows.py       GET /Shows/{seriesId}/Seasons, /Episodes, GET /Shows/NextUp
    ├── artists.py        GET /Artists, GET /Artists/AlbumArtists
    ├── genres.py         GET /Genres, GET /MusicGenres
    ├── years.py          GET /Years
    ├── filters.py        GET /Items/Filters
    ├── similar.py        GET /Items/{itemId}/Similar
    ├── instant_mix.py    GET /Items/{itemId}/InstantMix
    └── search.py         GET /Search/Hints
```

Route modules keep the one-module-per-controller habit. `item_models.py` and `item_dto.py` are
shared by all of them and belong to `api/`, not `compat/`: they are the item surface, and
`compat/` stays ignorant of specific endpoints.

## 4. Data model

**None.** The spec says this feature owns no state, and the plan keeps it: no table, no column,
no cache. The columns and indexes it leans on were declared in
[004's revision 0003](../004-metadata-resolution/plan.md#4-data-model) with their query patterns
named. If implementation finds a missing index, the index arrives as a revision in *this* feature
with its pattern written down — not as a quiet addition to 004's.

## 5. Contracts

**`domain.queries.ItemQuery`** — the request, as data:

```python
@dataclass(frozen=True)
class ItemQuery:
    user: User                        # visibility is not optional; there is no "as nobody" query
    parent_id: str | None = None
    recursive: bool = False
    include_types: frozenset[ItemType] | None = None
    exclude_types: frozenset[ItemType] | None = None
    media_types: frozenset[str] | None = None
    ids: tuple[str, ...] | None = None
    exclude_ids: tuple[str, ...] | None = None
    search_term: str | None = None
    name_starts_with: str | None = None            # and the two range variants
    genres: tuple[str, ...] | None = None          # by name; genre_ids is by identifier
    genre_ids / studio_ids / artist_ids / album_artist_ids / album_ids / person_ids / years
    filters: frozenset[Filter] = ...               # IsFavorite, IsPlayed, IsUnplayed, IsResumable
    is_played: bool | None = None
    is_favorite: bool | None = None
    min_community_rating: float | None = None
    sort: tuple[tuple[SortBy, SortOrder], ...] = ()
    start_index: int = 0
    limit: int | None = None
    count: bool = True                             # enableTotalRecordCount
```

**`genres` was missing from this contract until T2 built it**, and spec §3.3 promises it in
tier 2 beside `genreIds`. The two are not interchangeable: a name arrives from a client that never
fetched the by-name row it belongs to, so a query that could only take identifiers would answer
nothing for a request the reference serves. T6 implements "every filtering predicate `ItemQuery`
names", which is exactly why the omission would have been silent — no task was going to notice a
promise this contract did not carry.

**`db.item_queries.ItemQueryRepository`**:

```python
def run(self, query: ItemQuery) -> QueryPage        # .items: tuple[HydratedItem, ...], .total: int
def run_by_name(self, kind: ItemType, query: ItemQuery) -> QueryPage
```

**A page carries `HydratedItem`, not `Item`.** This paragraph said `list[Item]` until T5 built it,
and `Item` cannot hold what the sentence below requires: genres, credits, images and *another
user's* play state are not properties of the file the scanner saw. Putting them on `Item` would
give 003's scanner five fields it can never fill and a reader no way to tell "empty" from "not
loaded". `HydratedItem` wraps the item and carries the rest, so the DTO builder still receives
plain values — which is the property that mattered, and it is now literally true.

Two invariants callers may assume, and tests enforce: **the count is the pre-paging count** under
exactly the query's predicates, and **hydration is complete** — items arrive with their genres,
people, artists, images and the requesting user's user data attached, so the DTO builder issues
no query of its own, ever. The N+1 ban is a contract here, not a hope: the builder takes plain
domain objects and has no session to misuse.

**`api.item_dto.build_dtos(items, ctx) -> list[BaseItemDto]`** — `ctx` carries the resolved
`Fields` set, the image options, the libraries' collection types and roots, and — when the
resolved fields need the subtree numbers — the container aggregates from
`ItemQueryRepository.aggregates_for`. The ancestor context (series names, the parent image tags,
an album's artists) rides `HydratedItem` itself rather than `ctx`, summarised as two bounded
levels per item *(amended by T9: the draft said "parent rows in ctx", which would have made every
route re-associate rows to items the repository had already associated)*. `UserData` is always
attached (behaviours §2.1) with `Key` and `ItemId` set to the item's derived identity — a value
the differential allowlist already covers alongside every other id — and on a container its
`Played`/`UnplayedItemCount` are the subtree rollup the reference sends on every bare row
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.

**`compat.query_params`** exposes one dependency and one middleware, described in §6.12; route
modules declare parameters with the pinned document's spellings and never see the mechanics.

## 6. Algorithms

### 6.1 Visibility, in one predicate

Every query — items and by-name alike — is filtered by `visible_to(user)`:

1. **Library access**: the item's library is permitted by 002's policy (`enable_all_folders` or a
   `user_library_access` row with `can_view`).
2. **Not removed**: `removed_at IS NULL` (003's soft deletion).
3. **Containers earn their place**: a `Series`, `Season`, `MusicArtist` or `MusicAlbum` is
   visible only while a visible file-backed item exists beneath it — the closing half of
   behaviours §5.2. The tree's depth is fixed by `PARENT_OF`, so this is a correlated `EXISTS`
   through at most two parent hops, not a recursive query. A `CollectionFolder` is exempt: an
   empty library is still a library, and `/UserViews` shows it.

   > **The correlation is the whole clause, and losing it fails open.** Written without an
   > explicit `correlate`, the ORM puts the item table in the subquery's *own* `FROM` and the
   > `EXISTS` becomes a cross join — the clause then asks "does any visible file exist at all",
   > which every container in a non-empty library passes. It is a one-word difference that turns
   > a visibility rule into a tautology, and nothing about the resulting SQL looks wrong. T5
   > found it by emptying a series and watching it stay visible.

By-name rows add their own clause: a `Genre` exists for a user while a visible item references it
(`EXISTS` over the join table against the item predicate above), so `/Genres` never lists a genre
whose every film sits in a library the user cannot see.

### 6.2 Scope and recursion

`parentId` absent → the user's whole world. `recursive=false` → direct children
(`parent_id = X`). `recursive=true` under a `CollectionFolder` → `library_id` match, which is the
fast path and the common one; under any other container → parent-chain joins, bounded because the
tree's depth is a constant of the domain model. An unknown or invisible `parentId` is the
identical `404` of §6.13 before any query runs.

**The filters**, which this plan had nowhere else to put and T6 therefore had to decide:

- **Every one is a clause on the same statement**, never a second query or a walk in Python. The
  related-row filters are `EXISTS` rather than joins: a join multiplies the result set by the
  number of matching rows and needs a `DISTINCT` to undo it, which then has to survive every
  `ORDER BY` §6.3 adds. `EXISTS` asks the question the filter is asking — *is there one* — and
  leaves the row count alone.
- **`None` means "the client did not ask"; an empty collection means "it asked for nothing".**
  `includeItemTypes=` with every token unrecognised drops to an empty tuple (behaviours §1.12),
  and the honest answer to *items of no type* is no items. Collapsing the two returns the whole
  library to a request that filtered for something the server does not know.
- **Absence of a `item_user_data` row is a state**, not a gap. "Unplayed" is `NOT EXISTS(played)`
  and not `EXISTS(NOT played)`: the second finds only items somebody has already touched, which on
  a fresh account is none of them.
- **`mediaTypes` has no column.** `MediaType` is a property of the item *type*, measured once into
  `domain.items.MEDIA_TYPE_OF` `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]` — and the
  measurement disagrees with anything derived from `FILE_BACKED`: a `MusicAlbum` is `Unknown`,
  which a rule built on *does it hold audio* would call `Audio`.
- **`genres` matches by name through the identity fold**, not as a string. Two spellings of one
  genre merge to one by-name row whose id is derived from the folded name (behaviours §2.18), so a
  client filtering by `Sci-Fi` finds the film tagged `sci-fi`. Both `Genre` and `MusicGenre` are
  offered, because a client filtering by `Rock` does not know which table its films and its tracks
  landed in.
- **`artistIds` is the superset, `albumArtistIds` the subset**, and the direction was measured
  rather than reasoned: `artistIds` matches any credit and `albumArtistIds` only `album_artist`.
  On the reference one artist answers 6 items to the other parameter's 2, and a performer who is
  nobody's album artist answers 2 to 0
  `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`.
- **`albumIds` is `parent_id`.** A track's album is its parent; there is no album column, and
  inventing one would be a second home for a fact the tree already states.

### 6.3 ORDER BY

Per `SortBy`, the primary expression:

| SortBy | Expression |
|---|---|
| `SortName` | `sort_name` |
| `DateCreated` | `date_created` |
| `PremiereDate` | the **effective year** — `COALESCE(extract(year, premiere_date), production_year)` — then the date itself. The reference's own fallback, spec §3.4 |
| `PlayCount` / `DatePlayed` | `LEFT JOIN item_user_data` for the requesting user; `COALESCE(play_count, 0)`, null last-played first |
| `AlbumArtist` / `Artist` | the minimum **lower-cased** name over the item's credits of that kind, as a correlated subquery |
| `Random` | not SQL at all — §6.4 |

`sortBy` accepts a comma list zipped with `sortOrder` (missing orders default `Ascending`).
The tail, always: `Name` when the first key is `SortName` — the one chain the reference has —
then `id` ascending, which makes every ordering total (spec §3.4 rule 2, behaviours §3.6).

When `searchTerm` is present, match quality is prepended ahead of everything: a `CASE` over
`name_folded` ranking exact, prefix-at-word-boundary, prefix, contains — the reference's
relevance order (spec §3.4).

**Two expressions in that table were written portably rather than literally, and T7 says why.**

- `PremiereDate` reads *"January 1 of `ProductionYear`"*, and building a timestamp out of an
  integer is spelled differently in every dialect. Ordering by the **effective year** first, with
  the date as the second key, puts a year-only item exactly where January 1 would put it — ahead
  of every dated item of the same year — and `extract` is one SQLAlchemy construct that compiles
  on SQLite and on Postgres alike.
- The artist keys are **lower-cased, not folded**. `fold_for_search` also strips diacritics and no
  dialect does that portably, so `Ángel` and `Angel` sort apart here where the search fold would
  put them together. There is nothing measured to be wrong against: the reference's own key for
  those two sorts lives in a joined table the API does not return, which is why
  `probe_sort_stability.py` reports rather than concludes on them. Recorded as a known
  approximation, not a claim.

### 6.4 Random

Fetch the matching **ids only**, shuffle in process with `random.Random(seed)`, slice the page,
hydrate the slice in shuffled order. The seed is fresh entropy per request and never exposed;
tests inject it — through `ItemQuery.random_seed`, because a query is the whole of what produced a
result and two equal queries must describe the same page. A seed passed beside the query would
break that quietly, for the one ordering where it matters most. Cost: one id-list query — tens of thousands of 32-byte strings at worst — which
is cheaper than teaching SQLite a seeded shuffle and exactly as observable as the reference's
per-request shuffle. `TotalRecordCount` still reports the full count.

### 6.5 The `Fields` registry

One table in `item_dto.py` drives field emission: for each `ItemFields` token, the emitter and
whether it is always-on, per-type, or gated (the three tiers of spec §3.2). The always-present
set and the per-type sets are data, so the test that pins spec §3.2 is a comparison of two
tables, not twenty hand-written assertions.

**The table is a rule about list rows, and there are two other shapes.** Measurement put
`/Items/{itemId}` at up to 39 properties more than a bare list row of the same item, with no
`Fields` in the request, and `/UserViews` at 40 unasked
`[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`. So the builder takes the
emission tier as a **parameter of the call site**, not of the item: a list row applies the table,
the single-item route emits every field in the registry regardless of what was asked, and T11's
`/UserViews` applies its own set. One table, three entry points — not three tables, which would
drift, and not one entry point, which would make `/Items/{itemId}` wrong on every request.

`ChannelId` is the registry's one always-on `null`: it is emitted on every item with a null value
where every other null is suppressed (behaviours §1.7), so it cannot be produced by the base
model's exclusion rule and needs an explicit emitter.

Unknown tokens in `fields` are dropped and recorded
(behaviours §1.12). `enableUserData=false` suppresses `UserData` on request; nothing suppresses
it by default (behaviours §2.1). `enableImages=false` and `imageTypeLimit`/`enableImageTypes`
prune the image tag maps the DTO would otherwise carry.

Three gated emitters answer for values 004 never stored, and each is a recorded decision rather
than a guess *(added by T9)*: **`Etag`** is a 32-hex hash of the item's identity and its two
change clocks — opaque and stable is all an etag promises, and no client compares etags across
servers; **`ExternalUrls`** is a table over `ProviderIds` reproducing the reference's measured URL
patterns, `Tmdb` being the one key whose URL depends on the item's type
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`; and
**`ImageBlurHashes`** is always the empty map (behaviours §5.5). `MediaSources`, `MediaStreams`,
`Chapters`, `Width` and `Height` — everything probing a file would fill — stay **undeclared on
the model**, so the §1 sequencing gap is structural rather than remembered, and a test asserts
the absence so 008's arrival changes a failing test rather than nothing.

### 6.6 The four shapes

`item_models.py` defines them once: the three-field envelope (`Items`, `TotalRecordCount`,
`StartIndex` — behaviours §1.5), the bare array of `/Items/Latest` (behaviours §1.8), the filter
summary of `/Items/Filters`, and the hint envelope of `/Search/Hints`. `enableTotalRecordCount=
false` skips the count query and reports `0` — the one case where `0` is honest, because the
caller asked for it. By-name endpoints report the true count with or without `limit`: the
recorded divergence of behaviours §3.1, held by AC-5.

The filter summary is computed, never stored: the distinct `Genres`, `Tags`, `OfficialRatings`
and `Years` over the §6.1-visible items in scope, `parentId` and `includeItemTypes` narrowing it
like any query, each list ordered as the reference orders it — which T15 measures before the
model freezes. *(Added by the tasks gate, 2026-08-27: the shape was defined here and the
computation nowhere, which is this plan failing its own §10 test — a task was about to invent a
design decision.)*

### 6.7 By-name endpoints

The same pipeline with `kind` pinned: `/Genres` → `Genre` rows, `/MusicGenres` → `MusicGenre`,
`/Artists` → `MusicArtist` rows holding **any** credit, `/Artists/AlbumArtists` → those holding
an `album_artist` credit — the credit distinction from 004, which is what makes a
compilation-heavy fixture separate the two (AC-13). `/Years` → `Year` rows with a visible item
carrying that `production_year`. `parentId` scopes the membership `EXISTS`, `searchTerm` matches
the folded name, and paging and sorting are §6.3's, unchanged.

**The membership clause lives in §6.1's predicate, not here.** A by-name row *is* an item:
`/Items?includeItemTypes=Genre` has to give the same answer as `/Genres`, and two predicates in
two places is how they stop agreeing. What `run_by_name` adds on top is only what these routes ask
that `/Items` does not — the `parentId` scope and the credit reading.

**The five kinds do not reach their items the same way**, so the clause is a `CASE` over the type
rather than one join. Three have a join table; `Person` and `Studio` have their own; and **`Year`
has none at all** — it is referenced by `items.production_year`, a column, which is the one branch
that could have been written and forgotten.

> **Nothing created a `Year` row until T8.** `MetadataRepository.apply` wrote a by-name row for
> every genre, studio and person it saw and none for the year, while `collect_by_name_garbage` had
> always protected `Year` rows on the assumption that something made them. `/Years` would have
> listed nothing, and `GET /Items/{yearId}` would have answered `404` for a year the library
> plainly has. Fixed in the write path rather than by deriving the list from a `DISTINCT`, because
> a `Year` is an item and the item route has to answer for it too.

### 6.8 Discovery endpoints

**`/Items/Latest`**: visible file-backed items, `date_created` descending, the user's
latest-items exclusions from 002 §3.6 applied, grouped upward, and returned as the bare array.
*(Corrected by T11's measurement — this paragraph first said an episode always surfaces as its
series.)* A group surfaces as its container only when it holds **more than one** recent item; a
group of one is the item itself, and `groupItems=false` switches grouping off (spec §3.7).
`HidePlayedInLatest` — default true, measured — keeps played items out of the pool unless the
caller's `isPlayed` overrides it. Grouping collapses an unknown number of rows per entry, so the
route pages the repository — a fixed page size, first-seen order, until `limit` groups exist or
the world runs out — and then fetches the surfacing containers through the same pipeline, so a
container row arrives with the rollups every container row has.

**`/UserItems/Resume`**: items whose user data holds `playback_position_ticks > 0`, most recently
played first. 007's six-branch rule (007 §3.7) already guarantees a stored position is a
mid-playback one, so the exclusion the spec names is structural: a position past the threshold
was never stored.

**`/Shows/NextUp`**: for each series with at least one played episode, the first unplayed
episode in `(season, episode)` order after the highest played one, specials excluded from the
chain; series ordered by their latest `last_played_date` descending; one row per series by
construction (AC-10), which the query produces via a per-series window rather than post-filtering.

### 6.9 Series navigation

`/Shows/{seriesId}/Seasons` orders by the index, **specials first** — *(corrected by T12: this
paragraph carried a specials-last expression built for the drafted AC-11, and the measurement
reversed the criterion, spec §3.8)*. No expression is needed at all: season 0's sort name
(003's zero-padded prefix) places it first, which **is** the measured wire order, so the default
ordering serves it. `/Shows/{seriesId}/Episodes` scopes by `seasonId` (its own query, and an
unknown one is the identical `404`) or by the `season` number, otherwise the series' episodes
arrive in `(season, episode)` order — again 003's sort names verbatim. `DisplayMissingEpisodes`
is honoured trivially in v1: 004 creates no missing-episode placeholders, so both settings serve
the same rows — recorded here so nobody hunts for a bug when a client toggles it; `isMissing`
narrows to the same honest absence.

### 6.10 Similar and InstantMix

**Similar**: candidates of the seed's own type, visible, not the seed; score
`3·|shared genres| + 2·|shared people| + 1·|shared studios|`; order by score descending, then
`sort_name`, then id; zero-score candidates excluded. The weights are constants in one place with
this table cited beside them.

**InstantMix**: the pool is visible `Audio` sharing a music genre with the seed (for an artist or
album seed, the union over its tracks' genres); ordered by `sha256(seed_id ‖ item_id)` — a keyed
shuffle that is total, stable for a given seed and library (AC-12), and needs no stored state.

Both diverge from the reference into determinism deliberately; the spec argues why that is
invisible (spec §3.7).

### 6.11 Search hints

`/Search/Hints` matches `name_folded` by containment, relevance-ordered per §6.3, over the item
types v1 serves; each hit becomes a `SearchHint` — `Id` and `ItemId` both set, `MatchedTerm` the
name that matched, and the type extras (`Series`, `Album`, `AlbumArtist`, counts) resolved from
the hydrated item. The shape is the fourth envelope, never `BaseItemDto` (AC-14).

### 6.12 Parameter plumbing

**Case-canonicalisation** (behaviours §1.15): at startup, `compat.query_params` walks the route
table and builds, per route, a case-insensitive map of declared parameter spellings. The
middleware rewrites each incoming query key to its declared spelling when one matches — values
untouched — before the framework binds. Unmatched keys pass through unmodified, which is what
lets the recorder see them.

**The ignored-parameter record** (spec §3.3, AC-15): after canonicalisation, keys that match no
declared parameter of the route are counted per `(route, parameter)` and logged structurally once
per distinct pair per process — the measurable trail the spec's Tier-3 promise requires. 010 §3.6
owns turning that into a report; this feature owns making the events exist.

**Two keys no route declares are accepted on every route**, and they are not an exception to the
rule above so much as its blind spot. `ApiKey` and `api_key` are one of the five authentication
mechanisms (002 §3.1); `compat/auth.py` reads them straight off the query string, so they appear
in no route's signature and "matches no declared parameter of the route" is true of both. Left
alone, the recorder would report `api_key` as an ignored parameter on **every** authenticated
request a media player makes — and media players are exactly the clients that cannot set headers.
They are seeded into every route's spelling map, and a test asserts it for every registered route
rather than for the ones that came to mind.

**Counting is keyed on the route template, not the request path.** `/Items/{itemId}` is one route;
tallying per concrete path would produce a table as long as the library instead of as long as the
parameter set.

**Enum-token dropping** (behaviours §1.12): list-of-enum parameters parse through one helper that
keeps known tokens, drops unknown ones, and records the drop alongside the Tier-3 counter.
The type parameters are the one three-way case *(added by T10)*: a token of the reference's
`BaseItemKind` vocabulary that this version cannot produce keeps the filter and matches nothing
— an empty set means "asked for nothing", `None` means "did not ask" (§6.2) — while a token that
is no kind at all drops and is recorded. `api/items.py` carries the vocabulary verbatim with its
`[spec: BaseItemKind]` provenance; spec §3.3 states the observable half. Scalar
type failures — `limit=abc`, a malformed GUID — keep failing validation, which the extended
handler in `compat/errors.py` answers as the reference does: `400`, problem-details body,
`errors` map, `traceId` (behaviours §1.11) — served as `application/json; charset=utf-8` rather
than the `application/problem+json` both frameworks default to, and keyed on the **declared**
parameter spelling rather than the client's, both measured at implementation time.

**A fourth fight was found while settling the third**, and it is not scoped to errors: the
reference escapes every non-ASCII character and seven ASCII ones as `\uXXXX` with uppercase hex
(behaviours §1.16). It surfaced because the validation body is the first response whose bytes had
to match exactly, and it turned out to apply to every response there will ever be. It is settled
in `compat/responses.py`, in the same package and for the same reason as the other three: the
framework's default is silently different, and the difference is invisible until a golden compares
bytes.

### 6.13 The identical 404

`GET /Items/{itemId}` resolves the id and applies §6.1 in one query; "no row" and "row the user
may not see" produce the **same** problem-details `404` from the same line of code, so the two
are byte-identical by construction rather than by test alone (AC-8 still checks the bytes). An id
that does not parse as 32 hex answers the validation `400` — which of the two a caller gets
depends only on the id's shape (spec §3.5).

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Unknown / invisible `parentId` or item id | §6.1 lookup | Problem-details `404`, identical for both | — |
| Malformed id or unparseable number | Validation | Problem-details `400` with `errors` map (behaviours §1.11) | Client fixes the request |
| Unrecognised enum token | §6.12 parser | Dropped; filter vanishes; recorded; `200` (behaviours §1.12) | Visible in the ignored-parameter record |
| Unimplemented (Tier 3) parameter | §6.12 recorder | Ignored; recorded; `200` (spec §3.3) | Promotion via the record |
| `userId` naming another user, caller not administrator | Route guard | Empty `403` via the 002 seam — unmeasured against the reference, flagged for the differential | — |
| No visible libraries | §6.1 | Empty envelope, not an error (AC-9) | — |
| Huge `limit` | None — deliberate | Serve it; the reference imposes no ceiling and inventing one is a delta | Operator-level concern |
| Query slower than a client timeout | 010's differential timing | Not handled here; index work happens against measurements, not fear | — |

## 8. Testing strategy

The fixture is a **seeded database, not a filesystem**: a builder inserts a known world through
the repositories — three libraries (movies, shows, music), a restricted user and an unrestricted
one, 003's awkward names (whitespace artefacts included), three series — row 10 below proves
NextUp on three watched ones, a need this paragraph originally forgot to seed *(amended by the
tasks gate, 2026-08-27)* — one of them with specials and a multi-episode file, a compilation
with per-track artists, case-variant genres, and a 100-item paging corpus. No scan runs in
these tests; 003 already proved scanning.

| Spec AC | Test |
|---|---|
| 1 | Golden bodies for all four shapes; every list endpoint asserted against its shape |
| 2 | `UserData` present with `Key`/`ItemId` on every item of every list, no parameters |
| 3 | The §6.5 registry: each gated field absent bare, present with `Fields` |
| 4 | Property test: for **every** supported `sortBy`, page the 100-item corpus at sizes 1, 7, 97 and assert each id seen exactly once, in the unpaged order — **and page the whole world too**, because the corpus is films and films have no artist credits, so `AlbumArtist` and `Artist` would be tested with a null key on every row *(amended at T7)* |
| 5 | By-name endpoints with and without `limit` report the true count (behaviours §3.1) |
| 6 | Ordering of the awkward-name fixture equals the 003 corpus expectation |
| 7 | Injected-seed `Random`: full set, no duplicates within a page |
| 8 | Unknown and invisible ids: byte-identical `404` bodies |
| 9 | The restricted user with nothing visible: empty `/UserViews` envelope |
| 10 | NextUp on a fixture with three watched series: one row each, correct episodes |
| 11 | Season 0 sorts first — index order, as measured — in `/Shows/{id}/Seasons` |
| 12 | `Similar` and `InstantMix` twice: identical bodies |
| 13 | `/Artists` ⊋ `/Artists/AlbumArtists` on the compilation fixture, in that direction |
| 14 | `/Search/Hints` shape, `MatchedTerm` populated |
| 15 | A Tier-3 parameter: `200`, unfiltered, and the recorder holds `(route, parameter)` |
| 16 | One parameterised test per Tier 1 and Tier 2 parameter, each against a fixture slice built to be narrowed by it — the test fails if the parameter changes nothing |

Cross-cutting: the casing and unit sweeps from 001 cover the ~seventy new fields for free; a
query-counter fixture fails any endpoint that issues per-item queries (the §5 hydration
contract); the §6.12 canonicalisation is tested by calling one route with every parameter
spelling mangled. `GET /Items` and `GET /Items/{itemId}` carry goldens per item type now and
join the differential when 010 lands — their L3 row is a debt this plan acknowledges and 010
pays.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A field serialises subtly wrong among seventy | High | Medium each, compounding | Byte goldens per type; sweeps; differential at 010 |
| An endpoint bypasses the shared pipeline and drifts | Medium | High — the §6.1 predicate is security-relevant | Route modules own no SQL; repository is the only reader; review gate on imports |
| N+1 hydration creeps in | High | Medium — quadratic lists | The query-counter fixture fails it in CI |
| Tie tail dropped in a refactor | Medium | High — AC-4 paging breaks at scale | The property test is the tripwire; behaviours §3.6 the reason it exists |
| Canonicalisation map misses a route added later | Medium | Medium — that route ignores PascalCase params | Startup check: every registered route's params resolve; test walks all routes |
| `Fields` registry and spec §3.2 drift apart | Medium | Medium | The registry is data; one test asserts it equals the spec's three lists verbatim |
| Query performance at 10× the fixture | Medium | Medium | 004's pattern-named indexes; measure before adding more (§7 last row) |

## 10. Alternatives considered

**A query builder per endpoint.** Seventeen honest little functions, each obvious alone — and
seventeen places the visibility predicate has to be remembered, which is one forgotten `EXISTS`
away from listing a hidden library's genres. Centralising is not elegance; it is making the
security predicate unforgettable.

**A closure table for recursion.** The general answer to subtree queries, and unnecessary here:
the domain fixes the tree at depth three, `library_id` answers the common recursive case in one
predicate, and a closure table is state 003's scan would have to maintain forever.

**SQL-side seeded random.** SQLite offers no seedable ordering function; registering a custom one
per connection is possible and makes the shuffle's determinism depend on connection lifecycle.
Shuffling ids in process is exact, testable, and its cost is one id-only query.

**Letting the framework's `422` stand.** It is nearly right and it is a delta twice over — status
and body shape — on the paths clients probe most carelessly. Measured, the reference answers
`400` problem details; behaviours §1.11 already owns the shape.

**Rejecting unknown parameters.** Tidier than recording them, and measured wrong: the reference
ignores unknown tokens and unimplemented parameters alike (behaviours §1.12), and the spec turned
that into the Tier-3 promotion mechanism. Rejection would be a delta *and* would blind the
measurement.

**Materialising `/UserViews`.** A view row per user per library, refreshed on policy change —
state this feature is forbidden to own, solving a performance problem nobody has measured. The
libraries table has tens of rows; the query is the cache.
