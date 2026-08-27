---
feature: 005-item-query-api
title: Item query API — implementation plan
status: Draft
created: 2026-08-27
updated: 2026-08-27
spec_status_required: Accepted
spec_status_actual: Accepted
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

**`db.item_queries.ItemQueryRepository`**:

```python
def run(self, query: ItemQuery) -> QueryPage        # .items: list[Item], .total: int
def run_by_name(self, kind: ItemType, query: ItemQuery) -> QueryPage
```

Two invariants callers may assume, and tests enforce: **the count is the pre-paging count** under
exactly the query's predicates, and **hydration is complete** — items arrive with their genres,
people, artists, images and the requesting user's user data attached, so the DTO builder issues
no query of its own, ever. The N+1 ban is a contract here, not a hope: the builder takes plain
domain objects and has no session to misuse.

**`api.item_dto.build_dtos(items, ctx) -> list[BaseItemDto]`** — `ctx` carries the resolved
`Fields` set, the image options, and the parent rows the batch needs (series names, album
artists), pre-fetched by the repository. `UserData` is always attached (behaviours §2.1) with
`Key` and `ItemId` set to the item's derived identity — a value the differential allowlist
already covers alongside every other id.

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

By-name rows add their own clause: a `Genre` exists for a user while a visible item references it
(`EXISTS` over the join table against the item predicate above), so `/Genres` never lists a genre
whose every film sits in a library the user cannot see.

### 6.2 Scope and recursion

`parentId` absent → the user's whole world. `recursive=false` → direct children
(`parent_id = X`). `recursive=true` under a `CollectionFolder` → `library_id` match, which is the
fast path and the common one; under any other container → parent-chain joins, bounded because the
tree's depth is a constant of the domain model. An unknown or invisible `parentId` is the
identical `404` of §6.13 before any query runs.

### 6.3 ORDER BY

Per `SortBy`, the primary expression:

| SortBy | Expression |
|---|---|
| `SortName` | `sort_name` |
| `DateCreated` | `date_created` |
| `PremiereDate` | `COALESCE(premiere_date, jan1(production_year))` — the reference's own fallback, spec §3.4 |
| `PlayCount` / `DatePlayed` | `LEFT JOIN item_user_data` for the requesting user; `COALESCE(play_count, 0)`, null last-played first |
| `AlbumArtist` / `Artist` | the minimum folded name over the item's credits of that kind, as a correlated subquery |
| `Random` | not SQL at all — §6.4 |

`sortBy` accepts a comma list zipped with `sortOrder` (missing orders default `Ascending`).
The tail, always: `Name` when the first key is `SortName` — the one chain the reference has —
then `id` ascending, which makes every ordering total (spec §3.4 rule 2, behaviours §3.6).

When `searchTerm` is present, match quality is prepended ahead of everything: a `CASE` over
`name_folded` ranking exact, prefix-at-word-boundary, prefix, contains — the reference's
relevance order (spec §3.4).

### 6.4 Random

Fetch the matching **ids only**, shuffle in process with `random.Random(seed)`, slice the page,
hydrate the slice in shuffled order. The seed is fresh entropy per request and never exposed;
tests inject it. Cost: one id-list query — tens of thousands of 32-byte strings at worst — which
is cheaper than teaching SQLite a seeded shuffle and exactly as observable as the reference's
per-request shuffle. `TotalRecordCount` still reports the full count.

### 6.5 The `Fields` registry

One table in `item_dto.py` drives field emission: for each `ItemFields` token, the emitter and
whether it is always-on, per-type, or gated (the three tiers of spec §3.2). The always-present
set and the per-type sets are data, so the test that pins spec §3.2 is a comparison of two
tables, not twenty hand-written assertions. Unknown tokens in `fields` are dropped and recorded
(behaviours §1.12). `enableUserData=false` suppresses `UserData` on request; nothing suppresses
it by default (behaviours §2.1). `enableImages=false` and `imageTypeLimit`/`enableImageTypes`
prune the image tag maps the DTO would otherwise carry.

### 6.6 The four shapes

`item_models.py` defines them once: the three-field envelope (`Items`, `TotalRecordCount`,
`StartIndex` — behaviours §1.5), the bare array of `/Items/Latest` (behaviours §1.8), the filter
summary of `/Items/Filters`, and the hint envelope of `/Search/Hints`. `enableTotalRecordCount=
false` skips the count query and reports `0` — the one case where `0` is honest, because the
caller asked for it. By-name endpoints report the true count with or without `limit`: the
recorded divergence of behaviours §3.1, held by AC-5.

### 6.7 By-name endpoints

The same pipeline with `kind` pinned: `/Genres` → `Genre` rows, `/MusicGenres` → `MusicGenre`,
`/Artists` → `MusicArtist` rows holding **any** credit, `/Artists/AlbumArtists` → those holding
an `album_artist` credit — the credit distinction from 004, which is what makes a
compilation-heavy fixture separate the two (AC-13). `/Years` → `Year` rows with a visible item
carrying that `production_year`. `parentId` scopes the membership `EXISTS`, `searchTerm` matches
the folded name, and paging and sorting are §6.3's, unchanged.

### 6.8 Discovery endpoints

**`/Items/Latest`**: visible file-backed items, `date_created` descending, the user's
latest-items exclusions from 002 §3.6 applied, grouped upward — an episode surfaces as its
series, a track as its album, each group once, newest first — and returned as the bare array.

**`/UserItems/Resume`**: items whose user data holds `playback_position_ticks > 0`, most recently
played first. 007's six-branch rule (007 §3.7) already guarantees a stored position is a
mid-playback one, so the exclusion the spec names is structural: a position past the threshold
was never stored.

**`/Shows/NextUp`**: for each series with at least one played episode, the first unplayed
episode in `(season, episode)` order after the highest played one, specials excluded from the
chain; series ordered by their latest `last_played_date` descending; one row per series by
construction (AC-10), which the query produces via a per-series window rather than post-filtering.

### 6.9 Series navigation

`/Shows/{seriesId}/Seasons` orders by `(index_number = 0), index_number` — the specials-last rule
as an expression, because season 0's *sort name* (003's zero-padded prefix) would place it first
and AC-11 says last. `/Shows/{seriesId}/Episodes` scopes by `seasonId` when given, otherwise the
series' episodes in `(season, episode)` order. `DisplayMissingEpisodes` is honoured trivially in
v1: 004 creates no missing-episode placeholders, so both settings serve the same rows — recorded
here so nobody hunts for a bug when a client toggles it.

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

**Enum-token dropping** (behaviours §1.12): list-of-enum parameters parse through one helper that
keeps known tokens, drops unknown ones, and records the drop alongside the Tier-3 counter. Scalar
type failures — `limit=abc`, a malformed GUID — keep failing validation, which the extended
handler in `compat/errors.py` answers as the reference does: `400`, problem-details body,
`errors` map, `traceId` (behaviours §1.11).

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
one, 003's awkward names (whitespace artefacts included), a series with specials and a
multi-episode file, a compilation with per-track artists, case-variant genres, and a
100-item paging corpus. No scan runs in these tests; 003 already proved scanning.

| Spec AC | Test |
|---|---|
| 1 | Golden bodies for all four shapes; every list endpoint asserted against its shape |
| 2 | `UserData` present with `Key`/`ItemId` on every item of every list, no parameters |
| 3 | The §6.5 registry: each gated field absent bare, present with `Fields` |
| 4 | Property test: for **every** supported `sortBy`, page the 100-item corpus at sizes 1, 7, 97 and assert each id seen exactly once, in the unpaged order |
| 5 | By-name endpoints with and without `limit` report the true count (behaviours §3.1) |
| 6 | Ordering of the awkward-name fixture equals the 003 corpus expectation |
| 7 | Injected-seed `Random`: full set, no duplicates within a page |
| 8 | Unknown and invisible ids: byte-identical `404` bodies |
| 9 | The restricted user with nothing visible: empty `/UserViews` envelope |
| 10 | NextUp on a fixture with three watched series: one row each, correct episodes |
| 11 | Season 0 sorts last in `/Shows/{id}/Seasons` |
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
