---
feature: 005-item-query-api
title: Item query API — tasks
status: Accepted
created: 2026-08-27
updated: 2026-08-27
accepted: 2026-08-27
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 005 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries three structural decisions.** The visibility predicate — the one
security-relevant piece of this feature — is green at T5, before the first route exists, and from
that task on no route module owns SQL: the repository is the only reader, so seventeen endpoints
inherit the predicate instead of each remembering it ([plan §9](plan.md#9-risks) row 2, and the
whole argument of [plan §10](plan.md#10-alternatives-considered)'s first alternative). The wire
mechanics every route needs — parameter-name canonicalisation, enum-token dropping, the
problem-details `400` that replaces the framework's `422` — land once, in `compat/`, at T4,
before seventeen routes multiply the cost of fighting the framework per route. And the N+1 ban is
a fixture before it is a discipline: the query counter arrives with the repository at T5, so
every endpoint task after it runs underneath the guard rather than promising to.

**One measurement precedes the code, because a data table is about to freeze.** The `Fields`
registry ([plan §6.5](plan.md#65-the-fields-registry)) is data — always-present, per-type, gated
— and [spec §3.2](spec.md#32-the-item-representation) assembled it from what two clients *read*,
not from a measurement of what the reference *sends*. T1 measures the per-type bodies before T9
turns the table into code, because a wrong row there is a field silently absent, or silently
present, on every response of an item type — the plan's first risk, compounding across roughly
seventy fields.

**Routes land across seven tasks, and the exact-set check has a device for that.**
`test_no_route_ships_ahead_of_its_feature` asserts that the served routes equal the surface of
the implemented features, so from T10 to T16 the test carries an explicit list of the 005 routes
that have landed — the device 002 used across its own two route tasks, recorded in that test's
docstring — and T17 deletes the list by putting `"005"` in `IMPLEMENTED_FEATURES`.

**What 004 wrote down for this feature is the starting inventory, not work.** `name_folded` on
every item, the pattern-named indexes, `ImageTags` emittable from `item_images` rows alone, and
the artist credit distinction
([004's tasks](../004-metadata-resolution/tasks.md#what-this-feature-owes-the-next-ones)) —
the indexes are leaned on from T5, the folded name and the credit distinction at T6 and T8, the
image rows at T9, and in each case the lean is the test.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files it
references on 2026-08-27 before being accepted. Five things changed — promises with no task
holding them, and twice, two accepted documents disagreeing with nothing measured between them:

| The draft said | It was |
|---|---|
| AC-1 was claimed where `/UserViews` and `/Items/Latest` land | **A criterion about *every* list endpoint, held one endpoint at a time.** Six tasks each assert their own shape and nothing asserts *every* — [plan §8](plan.md#8-testing-strategy) row 1 says "every list endpoint asserted against its shape", and an endpoint that drifted later would fail no sweep. T17 now carries the roll-up: one parameterised test walking every 005 list route in the surface and asserting its declared shape |
| T15 matches hints on the folded name, per plan §6.11 | **[Spec §3.10](spec.md#310-get-searchhints--getsearchhints) says name *and sort name*.** The accepted spec and the accepted plan disagree, the draft sided silently with the plan, and neither cites a measurement. T15 now measures which one the reference does — an article-prefixed title searched by its sort form answers it — and amends the losing document in the same change |
| T13 adds `tools/probe_next_up.py` | **With no row in [`tools/README.md`](../../tools/README.md)** — the exact omission 004's gate caught for `generate_cultures.py`, back for the very next new script. Now in T13's changes |
| T15 computes the filter summary as "distinct values over the visible items in scope" | **An algorithm no accepted document contains.** [Plan §6.6](plan.md#66-the-four-shapes) defines the shape only, and a task inventing the computation is the plan failing its own test — "an implementer never has to invent a design decision". §6.6 now says it, amended by this gate |
| T3 seeds "a series with specials and a multi-episode file", quoting plan §8's fixture list | **Plan §8's own row 10 proves NextUp on *three* watched series**, and its fixture paragraph never seeds them — an internal contradiction the draft copied faithfully. T3 now seeds three series, one of them carrying the specials and the multi-episode file; plan §8 is amended to match its own table |

What was checked and held: all sixteen acceptance criteria are claimed by name (mechanically,
not by reading); every module in [plan §3](plan.md#3-modules) has a task; all seventeen routes
were already in [`surface.yaml`](../../docs/compatibility/surface.yaml) before this list was
written; the four things 004 owes this feature exist in `db/models.py` — the folded-name column,
the pattern-named indexes, the complete `item_images` rows, the credit column and its check
constraint; `.env` and the live reference are present on the machine that will run T1's probe;
and no existing test asserts a `422`, so T4's global replacement breaks nothing that was right.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — Measure the item representation before the registry freezes

- [x] **Changes:** `tools/probe_item_shapes.py` — one question: which properties the reference
  actually emits, per item type, in a list and in full. For every type the live library can
  produce (`Movie`, `Series`, `Season`, `Episode`, `MusicArtist`, `MusicAlbum`, `Audio`,
  `CollectionFolder`, and `/UserViews`' own rows), fetch one item bare and once more with every
  [spec §3.2](spec.md#32-the-item-representation) gated field requested, from both `/Items` and
  `/Items/{itemId}`; record which of the three tiers each property lands in as measured, what
  `UserData` carries, the shape of `ImageTags`, and whether `PrimaryImageAspectRatio` appears
  unasked. A row in [`tools/README.md`](../../tools/README.md); the findings in
  `specs/005-item-query-api/notes/item-shapes.md`; spec §3.2 and
  [plan §6.5](plan.md#65-the-fields-registry) amended in this same change where the measurement
  contradicts them, with provenance.
- **Depends on:** nothing
- **Verified by:** the probe runs against the live reference and its output is committed with
  version and date; every §3.2 claim it touches is confirmed or amended in the same change; the
  tools CI job holds the script to the 3.9 floor like its siblings.
- **Note:** 004 T15 is the precedent — the task said measure first, and measuring first was the
  whole task. T9 copies this measurement into the registry rather than the spec's memory of it.
  A type the library cannot produce (`Playlist` before 009 exists) is recorded as unmeasured, not
  guessed.
- **Plan reference:** §6.5; spec §3.2
- **Done (2026-08-27):** the table was wrong in six ways, and the first one is structural: **there
  is no single item representation.** A bare `/Items/{itemId}` carries up to 39 properties a bare
  list row does not — `Overview`, `Genres`, `People`, `Studios`, `SortName`, `MediaSources`,
  `PrimaryImageAspectRatio` and the rest — with **no `Fields` in the request**, and `/UserViews` is
  a third shape at 40 unasked. §3.2 opened with "One representation for every item type" and T9's
  registry was going to be one table; it is now one table with the tier as a parameter of the call
  site, or `/Items/{itemId}` is wrong on every request.

  Then: **three properties are always present and were in no tier** — `ChannelId`,
  `ImageBlurHashes`, `LocationType`. **Seven of the twelve "Common" per-type names are gated on a
  list row** — `SortName`, `Overview`, `Genres`, `GenreItems`, `Studios`, `People`,
  `PrimaryImageAspectRatio` — six of them being `ItemFields` tokens, which is what made the row
  wrong, since a token is gated by definition. A list of movies carries no overview, no genres, no
  cast and no aspect ratio unless the client asks, and `PrimaryImageAspectRatio` is the one 004
  went out of its way to supply. `ChildCount` arrives unasked on `Playlist`.

  **And one finding that is not about 005 at all:** behaviours §1.7 says a null property is
  absent everywhere, by one line of configuration, with a source citation. `ChannelId` arrived as
  an explicit `null` **208 times** — every item of every type, both routes — and `ParentId` on the
  parentless `/UserViews` rows. The entry is amended with the exception and marked as a
  measurement with no mechanism: what defeats the setting cannot be established without a
  `reference/` checkout, which this machine does not have. It is the highest-traffic delta the
  project could have shipped, and nothing in 005 was looking for it.

  The probe's own first run was wrong in the same class of way the spec was: it folded
  `/UserViews` in with the content types, and one fat row promoted five gated names to "per-type"
  for every type at once. **The tiers are a property of the route, not of the item type.** Full
  findings in [notes/item-shapes.md](notes/item-shapes.md).

## T2 — `domain/queries.py`: the vocabulary

- [x] **Changes:** `ItemQuery`, `SortBy`, `SortOrder`, `Filter`, exactly as
  [plan §5](plan.md#5-contracts) declares them — frozen, pure, no I/O. Nothing else moves.
- **Depends on:** nothing
- **Verified by:** mypy strict; the `SortBy` members equal [spec §3.4](spec.md#34-sorting)'s
  vocabulary exactly
  ([behaviours §2.5](../../docs/compatibility/behaviours.md#25-sortby-vocabulary)); the defaults
  asserted as a table — `recursive` false, `start_index` 0, `count` true, empty sort; the
  standing domain sweep in `tests/unit/test_import_directions.py` picks the module up by
  construction, so a stray import upward fails with no new test written.
- **Plan reference:** §5
- **Done (2026-08-27):** the contract was missing a parameter its own specification promises.
  Plan §5's `ItemQuery` lists `genre_ids` and no `genres`, while [spec §3.3](spec.md#33-get-items--getitems)
  puts `genres` in tier 2 beside `genreIds` — and the two are not interchangeable, because a name
  arrives from a client that never fetched the by-name row it belongs to. T6's statement is "every
  filtering predicate `ItemQuery` names", so the omission would have been silent all the way to
  `Implemented`: no task was going to notice a promise the contract did not carry. `genres` is in
  the dataclass and plan §5 is amended in this change.

  Everything else held. All 32 parameters spec §3.3 promises across tiers 1 and 2 are either a
  field here or a DTO concern that plan §6.5 owns — `fields`, `enableUserData`, `enableImages`,
  `imageTypeLimit`, `enableImageTypes` are emission options, not predicates, and belong to the
  builder's context rather than to the query.

  **CI found a third thing, on the interpreter floor.** Asserting that a slotted query refuses an
  unknown attribute passed on 3.14 and failed on 3.12: a `@dataclass(frozen=True, slots=True)`
  answers `FrozenInstanceError` on 3.14 and `TypeError: super(type, obj)...` on 3.12, from the
  generated `__setattr__` reaching a stale `__class__` cell. Reproduced on 3.12.14 with a bare
  dataclass and no Atrium code in it. Every domain record is frozen-and-slotted, so this is the
  project's, not this module's — the test now asserts that it raises, not what.

  The tests are two tables rather than assertions. The `SortBy` set is compared **whole**, because
  containment would let a well-meaning `Name` member through — a key that would work against
  Atrium and do nothing against the reference. And every field's default is a row, with a test
  that fails on a field having *no* row: the default is what a client gets by sending nothing,
  which is the case least likely to be covered anywhere else.

## T3 — The seeded world

- [ ] **Changes:** `tests/fixtures/query.py` — the [plan §8](plan.md#8-testing-strategy) fixture:
  a builder that inserts a known world **through the repositories**, no scan, no filesystem.
  Three libraries (movies, shows, music); an unrestricted user, a user restricted to one library,
  and a user permitted nothing (AC-9's); 003's awkward names, whitespace artefacts included;
  **three series** — NextUp's one-row-per-series rule needs a choice among watched series to
  mean anything — one of them with specials and a multi-episode file; a compilation with
  per-track performers, one of
  them nobody's album artist (the revision-0004 shape); case-variant genres; a 100-item paging
  corpus; user data — played series for NextUp, mid-playback positions for Resume, favourites
  for the filters — written against `item_key`, the derived identity.
- **Depends on:** nothing
- **Verified by:** a test asserts the world's invariants — the counts, the compilation's credit
  split, the specials, the user-data rows — so a later edit to the builder that would quietly
  weaken a fixture fails loudly; the builder is deterministic, fixed identifiers and dates; the
  suite stays green with no consumer yet.
- **Note:** building through the repositories keeps the world honest against schema drift — a
  row the write path will not produce cannot be quietly relied on. 003's placeholder files stay
  untouched: they exercise scanning; this world exercises querying, and no scan runs in 005's
  tests.
- **Plan reference:** §8

## T4 — The three framework fights, once, in `compat/`

- [ ] **Changes:** `compat/query_params.py` — the startup walk building each route's
  case-insensitive spelling map; the middleware rewriting incoming keys to their declared
  spellings, values untouched, unmatched keys passing through; the ignored-parameter recorder,
  counting per `(route, parameter)` and logging each distinct pair once per process; the
  list-of-enum helper keeping known tokens and dropping-and-recording unknown ones.
  `compat/errors.py` grows the problem-details shape of
  [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-three-error-shapes-not-one):
  the validation `400` — status **and** body — where the framework answers `422`, and a
  problem-details `404` for handlers to raise. Both wired into the application factory.
- **Depends on:** nothing
- **Verified by:** a route called with every parameter spelling mangled binds them all
  ([behaviours §1.15](../../docs/compatibility/behaviours.md#115-query-parameter-names-match-case-insensitively));
  the startup check refuses a route whose declared parameters cannot resolve —
  [plan §9](plan.md#9-risks) row 5's mitigation, failing at boot rather than in a client;
  an unmatched key lands in the recorder; `limit=abc` answers `400` with `type`, `title`,
  `status`, `errors` and `traceId` asserted on the body, not the status alone; the enum helper's
  keep, drop and record cases as a table
  ([behaviours §1.12](../../docs/compatibility/behaviours.md#112-an-unrecognised-query-value-is-ignored-not-rejected));
  the whole existing suite green — the `422` replacement is global, and any test that relied on
  one was relying on the delta.
- **Plan reference:** §6.12; behaviours §1.11, §1.12, §1.15

## T5 — `db/item_queries.py`: one predicate, one count, complete hydration — and the counter that keeps them honest

- [ ] **Changes:** `ItemQueryRepository.run` over scope and visibility:
  [plan §6.2](plan.md#62-scope-and-recursion)'s three scope shapes — the whole world, direct
  children, recursive via `library_id` under a `CollectionFolder` and bounded parent hops under
  anything else; [plan §6.1](plan.md#61-visibility-in-one-predicate)'s predicate — 002's policy,
  `removed_at IS NULL`, containers earning their place through a correlated `EXISTS`,
  `CollectionFolder` exempt; the pre-paging count, and the `count` flag's honest `0`; hydration
  complete — genres, people, artists, images and the requesting user's user data, batched;
  `QueryPage`. The query-counter fixture lands in the same change and fails any path that issues
  per-item statements. `tests/unit/test_import_directions.py` gains the rule the plan's risk
  table asks for: no module under `api/` imports `sqlalchemy` or `atrium.db.models` — true
  today, and load-bearing from T10 on.
- **Depends on:** T2, T3
- **Verified by:** the restricted user never sees an item of an unpermitted library under any
  scope shape; a `Series` whose every episode is invisible is itself invisible while the emptied
  `CollectionFolder` remains
  ([behaviours §5.2](../../docs/compatibility/behaviours.md#52-a-container-that-has-lost-every-file-is-not-removed)'s
  closing half); the count is the pre-paging count under exactly the query's predicates, and
  `count=False` skips the count query and reports `0`; hydrated items answer genres, people,
  artists, images and user data with **zero** further statements, held by the counter; an unknown
  or invisible `parentId` raises the typed refusal §6.13 later turns into the identical `404`;
  the import rule was checked by breaking it.
- **Note:** the first structural decision, landed. From here on the repository is the only
  module that reads items, and a route that wanted its own SQL has a test to argue with.
- **Plan reference:** §5, §6.1, §6.2

## T6 — The filter battery

- [ ] **Changes:** every filtering predicate `ItemQuery` names, in the repository:
  `include_types` and `exclude_types`, `ids` and `exclude_ids`, `media_types`, `search_term` as
  containment on `name_folded`, the three `name_starts_with` variants on the folded name,
  `genre_ids`, `studio_ids`, `artist_ids`, `album_artist_ids`, `album_ids`, `person_ids`,
  `years`, `min_community_rating`, `is_favorite`, `is_played`, and the four `filters` values
  over the user-data join.
- **Depends on:** T5
- **Verified by:** [plan §8](plan.md#8-testing-strategy) row 16's repository half — one
  parameterised test per predicate, each against a world slice built to be narrowed by it,
  failing if the predicate changes nothing; `IsResumable` is `playback_position_ticks > 0`,
  which 007 §3.7's six-branch rule already guarantees is a mid-playback position;
  `artist_ids` and `album_artist_ids` differ on the compilation — the credit distinction,
  leaned on for the first time.
- **Plan reference:** §5, §6.3; spec §3.3

## T7 — Ordering is total; `Random` is seeded

- [ ] **Changes:** [plan §6.3](plan.md#63-order-by)'s table — `SortName`, `DateCreated`,
  `PremiereDate` with the reference's January-1-of-`ProductionYear` fallback, `PlayCount` and
  `DatePlayed` over the user-data join, `AlbumArtist` and `Artist` as the minimum folded credit
  name; the comma-list zip with `sortOrder`; the tail — `Name` when the first key is `SortName`,
  then id — that makes every ordering total; the `searchTerm` relevance `CASE` prepended ahead
  of everything; [plan §6.4](plan.md#64-random)'s `Random` — ids fetched, shuffled in process
  with an injectable seed, the page hydrated in shuffled order, the count still true.
- **Depends on:** T5, T6
- **Verified by:** AC-4 as the property test — for **every** supported `sortBy`, page the
  100-item corpus at sizes 1, 7 and 97 and assert each id is seen exactly once, in the unpaged
  order; AC-6 — the awkward-name fixture arrives in 003 §3.7's order, `sort_name` leaned on as
  004 wrote it; AC-7 — injected-seed `Random`: the full set, no duplicates within a page; an
  item with a year and no premiere date sorts under January 1 rather than clumping with the
  dateless; relevance order — exact, prefix at a word boundary, prefix, contains — ahead of
  whatever `sortBy` asked.
- **Note:**
  [behaviours §3.6](../../docs/compatibility/behaviours.md#36-ties-are-engine-resolved-and-paging-the-artist-sorts-loses-rows--class-b-diverged)
  is why the tail exists, and the property test is the tripwire [plan §9](plan.md#9-risks) names
  for a refactor that drops it.
- **Plan reference:** §6.3, §6.4

## T8 — By-name queries

- [ ] **Changes:** `ItemQueryRepository.run_by_name` — `Genre`, `MusicGenre` and `Year` rows,
  and `MusicArtist` rows under either credit reading (`/Artists`' any-credit,
  `/Artists/AlbumArtists`' album-credit); membership as an `EXISTS` over the join tables against
  the §6.1 item predicate, scoped by `parentId`; `searchTerm` on the folded name; §6.3's paging
  and sorting unchanged.
- **Depends on:** T5, T6, T7
- **Verified by:** a genre whose every item sits in a library the user cannot see is absent —
  the by-name clause of the predicate, adversarially; AC-13's repository half — the any-credit
  set strictly contains the album-credit set on the compilation, in that direction; `Year` rows
  answer to visible items' `production_year`; the pre-paging count is true with and without
  `limit`, which T14 re-holds on the wire
  ([behaviours §3.1](../../docs/compatibility/behaviours.md#31-totalrecordcount-is-0-on-by-name-endpoints-without-limit--class-b)).
- **Plan reference:** §6.7

## T9 — The item surface: models, the DTO builder, and the `Fields` registry

- [ ] **Changes:** `api/item_models.py` — `BaseItemDto`, `UserItemDataDto`, `NameGuidPair`, the
  three-field envelope, the filter summary, `SearchHint` and its envelope: all four shapes of
  [plan §6.6](plan.md#66-the-four-shapes), as models. `api/item_dto.py` — `build_dtos(items,
  ctx)`: the [plan §6.5](plan.md#65-the-fields-registry) registry as one data table seeded from
  T1's measurement; `UserData` always attached, `Key` and `ItemId` the derived identity;
  `ImageTags` and `BackdropImageTags` from `item_images` rows alone; `PrimaryImageAspectRatio`
  from the stored dimensions; `enableUserData`, `enableImages`, `imageTypeLimit` and
  `enableImageTypes` pruning; `ServerId` from the server state; `MediaSources` and
  `MediaStreams` serialising absent — the sequencing gap [plan §1](plan.md#1-approach) names,
  asserted so 008's arrival changes a failing test rather than nothing.
- **Depends on:** T1, T2, T5
- **Verified by:** the registry-equals-spec test — spec §3.2's three lists compared verbatim
  against the registry's data, the drift risk of [plan §9](plan.md#9-risks) row 6; AC-2 and AC-3
  at builder level; the casing and unit sweeps pick up every new model by construction — the
  registry walks `atrium.api` — which is the spec §6 sentence about seventy fields becoming
  true; the builder takes hydrated domain objects and has no session to misuse, so the counter
  fixture stays green through every later endpoint task.
- **Plan reference:** §5, §6.5, §6.6

## T10 — `GET /Items` and `GET /Items/{itemId}`

- [ ] **Changes:** `api/items.py` — parameter binding with the pinned document's spellings;
  Tier 1 and Tier 2 into `ItemQuery`; Tier 3 arriving at the recorder; the `userId` guard —
  another user's id from a non-administrator answers the empty `403` through the 002 seam
  ([plan §7](plan.md#7-failure-handling)); [plan §6.13](plan.md#613-the-identical-404)'s
  identical `404` from one line of code; both routes registered; `test_routes.py` gains the
  interim landed-routes list beside `IMPLEMENTED_FEATURES`, the 002 device, deleted at T17.
- **Depends on:** T4, T6, T7, T9
- **Verified by:** goldens per item type for both endpoints, reviewed bodies on the seeded
  world; AC-8 — unknown and invisible ids answer byte-identical problem-details `404`s, and a
  malformed id the validation `400`; AC-15 — a Tier 3 parameter: `200`, unfiltered, and the
  recorder holds `(route, parameter)`; AC-16's endpoint half — the parameterised battery: every
  Tier 1 and Tier 2 parameter narrows or reorders a fixture slice built for it, and the battery
  runs once more with every spelling mangled, re-holding §6.12 on a real route; AC-4 re-held
  through HTTP paging; AC-2 and AC-3 end to end; an oversized `limit` is served, not clamped
  ([plan §7](plan.md#7-failure-handling)); the query counter green under all of it.
- **Note:** the endpoint everything else is built on, and the task where the shared machinery
  first carries weight end to end. If this task needs something the pipeline cannot say, the fix
  is in the pipeline, not a bespoke query here.
- **Plan reference:** §6.13, §8; spec §3.3, §3.5

## T11 — The user's world: `GET /UserViews` and `GET /Items/Latest`

- [ ] **Changes:** `api/user_views.py` — the libraries after policy, each with
  `CollectionType`, the empty envelope for a user permitted nothing; `api/user_library.py` —
  the bare array, visible file-backed recency grouped upward — an episode surfaces as its
  series, a track as its album, each group once, newest first — and the user's latest-items
  exclusions from 002 §3.6 applied from the stored configuration.
- **Depends on:** T4, T5, T9
- **Verified by:** the upward grouping and the exclusion key are **measured against the live
  reference before the code is written** — [plan §6.8](plan.md#68-discovery-endpoints) asserts
  both and cites nothing, which is the class of claim every feature so far has caught being
  wrong — and the measurement lands in the spec with provenance in this change; AC-9 — the
  permitted-nothing user gets an empty envelope, not an error; AC-1's two halves here — the
  envelope with `StartIndex` at `/UserViews`, the bare array at `/Items/Latest`
  ([behaviours §1.8](../../docs/compatibility/behaviours.md#18-get-itemslatest-returns-a-bare-array));
  a new episode surfaces its series once; an excluded library's items are absent from Latest.
- **Plan reference:** §6.8; spec §3.6, §3.7

## T12 — Series navigation: `GET /Shows/{seriesId}/Seasons` and `/Episodes`

- [ ] **Changes:** `api/tv_shows.py`, first half — Seasons ordered by the specials-last
  expression, Episodes in `(season, episode)` order scoped by `seasonId` when given; an unknown
  or invisible `seriesId` answering the identical `404`; `DisplayMissingEpisodes` honoured
  trivially and recorded — v1 creates no missing-episode placeholders, so both settings serve
  the same rows ([plan §6.9](plan.md#69-series-navigation)), written down so nobody hunts for a
  bug when a client toggles it.
- **Depends on:** T5, T7, T9
- **Verified by:** the specials-last claim is measured against the live reference's Seasons
  response before the expression is written — spec §3.8 states it without provenance — and the
  spec gains the citation in this change; AC-11 — Season 0 sorts last on the seeded world;
  `seasonId` narrows; the multi-episode file appears once with its span; both endpoints
  envelope-shaped.
- **Plan reference:** §6.9; spec §3.8

## T13 — The played-state pair: `GET /Shows/NextUp` and `GET /UserItems/Resume`

- [ ] **Changes:** `api/tv_shows.py` completed with NextUp — per series with a played episode,
  the first unplayed in `(season, episode)` order after the highest played, specials excluded
  from the chain, series ordered by latest `last_played_date` descending, one row per series by
  a per-series window rather than post-filtering; `api/resume.py` — items whose user data holds
  a positive position, most recently played first; `tools/probe_next_up.py` — the measurement
  the verification below runs first — with its row in [`tools/README.md`](../../tools/README.md)
  like every script there.
- **Depends on:** T3, T5, T9
- **Verified by:** NextUp's semantics are measured first — `tools/probe_next_up.py` constructs
  played state on the live reference and asks what "next" means there: the
  highest-played-then-first-unplayed reading, the specials exclusion, and the one-row rule are
  [spec §3.7](spec.md#37-discovery-endpoints) and [plan §6.8](plan.md#68-discovery-endpoints)
  claims with no probe behind them, and whichever way the measurement lands it goes into the
  spec with provenance in this change; AC-10 — three watched series: one row each, the correct
  episodes, a rewatched early episode not resetting the chain; a series with nothing played
  contributes no row; Resume orders most-recently-played first, and a completed item cannot
  appear because 007 §3.7's rule means a stored position is structurally mid-playback.
- **Plan reference:** §6.8; spec §3.7

## T14 — The by-name endpoints

- [ ] **Changes:** `api/artists.py`, `api/genres.py`, `api/years.py` — five routes over
  `run_by_name`, each taking `parentId`, `userId`, paging, sorting and `searchTerm` with the
  pinned spellings.
- **Depends on:** T4, T8, T9
- **Verified by:** AC-5 — with and without `limit`, the true pre-paging count, which is the
  recorded divergence of
  [behaviours §3.1](../../docs/compatibility/behaviours.md#31-totalrecordcount-is-0-on-by-name-endpoints-without-limit--class-b)
  held on purpose; AC-13 — `/Artists` strictly contains `/Artists/AlbumArtists` on the
  compilation, direction asserted; the restricted user's `/Genres` never names a hidden
  library's genre, end to end; all five return the envelope.
- **Plan reference:** §6.7; spec §3.9

## T15 — The two other shapes: `GET /Items/Filters` and `GET /Search/Hints`

- [ ] **Changes:** `api/filters.py` — `{Genres, Tags, OfficialRatings, Years}` for a parent:
  the distinct values over the visible items in scope, each list in the reference's order as
  measured — the computation [plan §6.6](plan.md#66-the-four-shapes) gained at this list's gate;
  `api/search.py` — containment against the name, and against the sort name if that is what the
  measurement shows ([spec §3.10](spec.md#310-get-searchhints--getsearchhints) says both,
  plan §6.11 says the folded name alone, and they cannot both be right), relevance-ordered per
  §6.3, over the item types v1 serves; each hit a `SearchHint` with `Id` and `ItemId` both set,
  `MatchedTerm` the name that matched, and the type extras resolved from the hydrated item.
- **Depends on:** T5, T7, T8, T9
- **Verified by:** both bodies are measured against the live reference before the models
  freeze — which hint fields actually appear with nulls omitted, how the filter lists are
  ordered, and whether a hint matches on the sort name, which an article-prefixed title
  searched by its sort form answers — recorded in the spec with provenance in this change, and
  the losing document of the name-versus-sort-name disagreement amended in it too; AC-14 — the
  hint shape, not the item shape, with `MatchedTerm` populated;
  the filter summary reflects only the parent's visible items for the requesting user; both
  shapes match [plan §6.6](plan.md#66-the-four-shapes)'s models byte-for-byte as goldens.
- **Plan reference:** §6.6, §6.11; spec §3.7, §3.10

## T16 — The deterministic pair: `Similar` and `InstantMix`

- [ ] **Changes:** `api/similar.py` — candidates of the seed's type, visible, not the seed;
  the score `3·|shared genres| + 2·|shared people| + 1·|shared studios|`, descending, then
  `sort_name`, then id, zero-score candidates excluded, the weights constants in one place with
  [plan §6.10](plan.md#610-similar-and-instantmix)'s table cited beside them;
  `api/instant_mix.py` — the pool of visible `Audio` sharing a music genre with the seed, an
  artist or album seed taking the union over its tracks' genres, ordered by
  `sha256(seed_id ‖ item_id)`.
- **Depends on:** T5, T9
- **Verified by:** AC-12 — identical bodies on repeated calls, both endpoints, across two
  processes for InstantMix so the determinism is the hash's and not a cached accident; the
  ranking asserted on a constructed slice — two shared genres outrank one shared studio; the
  seed never appears in its own results; an unknown or invisible seed answers the identical
  `404`; both diverge from the reference into determinism deliberately, the argument spec §3.7
  already carries.
- **Plan reference:** §6.10; spec §3.7

## T17 — The acceptance map, and Implemented

- [ ] **Changes:** `FEATURE_005` in `tests/conformance/test_acceptance.py`, mapping **all
  sixteen** criteria of [spec §5](spec.md#5-acceptance-criteria) to named tests; the shape
  roll-up — one parameterised test walking every 005 list route in the surface and asserting
  its declared shape, which is what makes AC-1's *every* a property rather than six tasks'
  habit; `IMPLEMENTED_FEATURES` gains `"005"` and the interim landed-routes list is deleted;
  `specs/README.md`'s table; `spec.md`, `plan.md` and this file to `Implemented` with dates;
  AGENTS.md's where-the-project-is paragraph.
- **Depends on:** everything above
- **Verified by:** `test_every_implemented_feature_has_a_map` passes **with** 005 marked
  `Implemented`; `test_no_route_ships_ahead_of_its_feature` passes with the interim list gone,
  which is what finishing looks like in that file; the full local gate — `ruff check`,
  `ruff format --check`, `mypy`, `pytest` — green; the definition of done below closed line by
  line.
- **Plan reference:** §8; 004 T16 is the precedent

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all sixteen
      — has a passing test, by name, in `FEATURE_005`.
- [ ] Every endpoint reaches the conformance level [spec §6](spec.md#6-conformance) declares —
      with the L3 debt stated rather than hidden: `GET /Items` and `GET /Items/{itemId}` carry
      reviewed goldens per item type now and join the differential when 010 lands, which is the
      debt [plan §8](plan.md#8-testing-strategy) acknowledges and 010 pays.
- [ ] All seventeen routes are served, `"005"` is in `IMPLEMENTED_FEATURES`, and no route exists
      outside [`surface.yaml`](../../docs/compatibility/surface.yaml) — the seventeen rows were
      in the file before this list was written, so the check is registration, not listing.
- [ ] The feature ends owning **no state**: no table, no column, no cache
      ([plan §4](plan.md#4-data-model)). If implementation found a missing index, it arrived as
      a revision in this feature with its query pattern written down, or it does not exist.
- [ ] The query counter is green across the suite: no endpoint issues per-item statements.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same
      change that learned it.
- [ ] Every measurement a task took against the reference is in the spec or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) with provenance — T1's shapes,
      T11's grouping and exclusions, T12's specials ordering, T13's NextUp semantics, T15's
      hint fields.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.
