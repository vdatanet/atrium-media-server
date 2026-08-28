---
feature: 005-item-query-api
title: Item query API — tasks
status: Implemented
created: 2026-08-27
updated: 2026-08-28
accepted: 2026-08-27
implemented: 2026-08-28
plan_status_required: Accepted
plan_status_actual: Implemented
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

- [x] **Changes:** `tests/fixtures/query.py` — the [plan §8](plan.md#8-testing-strategy) fixture:
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
- **Done (2026-08-27):** four things the list did not say, one of which would have made every
  golden response unreproducible.

  **`MetadataRepository.apply` stamps `utc_now()` unless `refreshed_at` is passed.** A world built
  without it differs between two builds in a column, and plan §8 checks golden bodies in against
  this world — so the fixture would have been non-deterministic in exactly the way Principle VII
  forbids, and the symptom would have been a suite that fails on a machine rather than on a
  change. Every `apply` call here passes a constant. The invariants test builds the world twice
  into two databases and compares every identifier, so a clock reaching into it later fails
  loudly.

  **"003's awkward names" and "a 100-item paging corpus" cannot be two sets.** As separate lists
  they would both sit in the movies library, and plan §8 row 4's test — page *the corpus* and
  assert each id seen exactly once — would be paging a different set than the library holds. They
  are one corpus of 100, the first eight of which carry the awkward names. `CORPUS_SIZE` is
  asserted indivisible by 7 and 97, the plan's own page sizes, because a corpus that divides
  evenly never exercises the short final page.

  **The list does not name images, and 004 spent a task owing them.** `ImageTags` emittable from
  `item_images` alone is one of the four things
  [004 wrote down for this feature](../004-metadata-resolution/tasks.md#what-this-feature-owes-the-next-ones),
  and a world where every item has an empty tag map cannot tell an emitter that works from one
  that returns `{}`. One film carries a primary image, people and a studio. Recorded here rather
  than added quietly.

  **A resumable item must not also be played**, or the Resume fixture and the NextUp fixture are
  the same rows and neither test proves what it says. Asserted.

  One alignment worth keeping: the multi-episode `S01E02-E03` file is exactly what NextUp must
  answer with for its series, so the odd-shaped episode is the tested case rather than a shape
  sitting unused beside the one that gets exercised.

## T4 — The three framework fights, once, in `compat/`

- [x] **Changes:** `compat/query_params.py` — the startup walk building each route's
  case-insensitive spelling map; the middleware rewriting incoming keys to their declared
  spellings, values untouched, unmatched keys passing through; the ignored-parameter recorder,
  counting per `(route, parameter)` and logging each distinct pair once per process; the
  list-of-enum helper keeping known tokens and dropping-and-recording unknown ones.
  `compat/errors.py` grows the problem-details shape of
  [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one):
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
- **Done (2026-08-27):** there were **four** fights, and the fourth is the one that matters
  outside this task.

  Getting the validation `400` byte-exact meant measuring the reference's body, and the body
  came back **escaped**: `28 años después` is sent as `28 a\u00F1os despu\u00E9s`, and
  `Abraham's` as `Abraham\u0027s`. ASP.NET Core's HTML-safe `JavaScriptEncoder` escapes every
  non-ASCII character and seven ASCII ones — `"` `&` `'` `+` `<` `>` `` ` `` — as `\uXXXX` with
  **uppercase** hex, while leaving `/` `=` `:` and the space alone. Python writes all of them
  literally. That is a byte difference on **every response containing an accented character**,
  which in the measured library is most of them.

  No client can tell — a JSON parser decodes both forms identically — so this is not Principle I.
  It is Principle VIII: the goldens compare bytes. Settled in `compat/responses.py` and recorded
  as [behaviours §1.16](../../docs/compatibility/behaviours.md#116-every-non-ascii-character-in-a-body-is-escaped-and-so-are-seven-ascii-ones).
  The blast radius was exactly one golden, `Localization.Cultures.json`, whose `ç` and `ü` now
  match the reference's bytes rather than Python's.

  **How the escape set was measured is the reusable part.** Item names prove only what the library
  contains — a Spanish catalogue gives `\u00F1` and says nothing about a backtick. The exact set
  came from **echoing arbitrary characters through a validation error**: the `errors` map quotes
  the value back, so `?limit=a<b>c\`d'e&f+g"h/i=j:k` is a request that renders any character you
  like into a response body.

  **Two more measurements the plan did not have.** The problem-details content type is
  `application/json; charset=utf-8`, **not** `application/problem+json` — which is what both
  frameworks default to, so matching means overriding rather than accepting. And the `errors` key
  is the parameter's **declared** spelling, not the client's: `Limit=abc` against a route
  declaring `limit` answers `{"limit": [...]}`, which is §1.15's canonicalisation seen from the
  other side.

  **And the recorder had a blind spot the plan's own sentence created.** "Keys that match no
  declared parameter of the route" is true of `ApiKey` and `api_key` — one of the five
  authentication mechanisms, read straight off the query string by `compat/auth.py` and present in
  no route's signature. Uncorrected, the ignored-parameter tally would have been dominated by
  `api_key` on every request a media player makes, which is precisely the client that cannot send
  headers. They are seeded into every route's map, asserted for every registered route.

  Counting is keyed on the route **template**: `/Items/{itemId}` is one route, and tallying per
  concrete path would make the table as long as the library.

## T5 — `db/item_queries.py`: one predicate, one count, complete hydration — and the counter that keeps them honest

- [x] **Changes:** `ItemQueryRepository.run` over scope and visibility:
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
- **Done (2026-08-27):** the visibility predicate was **wrong in the direction that shows too
  much**, and nothing about the SQL looked wrong.

  "Containers earn their place" is a correlated `EXISTS`. Written the obvious way, SQLAlchemy puts
  the item table in the subquery's *own* `FROM` and the correlation silently becomes a **cross
  join** — so the clause asks "does any visible file exist at all" rather than "beneath this
  container", and every container in a non-empty library passes. An explicit `.correlate()` is the
  whole difference. It was found by emptying a series and watching it stay visible; no amount of
  reading the statement would have shown it, because the statement is valid and reads correctly.
  Plan §6.1 now carries the warning.

  **Plan §5's `.items: list[Item]` could not be `Item`.** Genres, credits, images and *another
  user's* play state are not properties of the file 003's scanner saw. Putting them on `Item`
  would give the scanner five fields it can never fill and a reader no way to tell "empty" from
  "not loaded". `HydratedItem` wraps the item; the property the plan actually wanted — the DTO
  builder receives plain values with no session — is now literally true rather than nearly true.
  §5 amended.

  **The task's own claim was false when written.** "No module under `api/` imports `sqlalchemy` or
  `atrium.db.models` — true today" is not true today: `api/deps.py` imports `Session` and
  `sessionmaker`, and always will, because it is the module that hands a route its session
  factory. The rule is now about **route** modules, and `deps.py` is held by a *stricter* test
  instead of an exemption: it may name the session types and nothing that builds a statement.
  Both rules were checked by breaking them.

  **By-name rows are visible to everyone at T5**, because a genre has no library and the library
  clause cannot speak about it. That is plan §6.1's design — the by-name clause arrives with T8 —
  and it is pinned with a test so the day it narrows, this says so rather than a `/Genres` test
  failing for reasons nobody connects to this predicate.

  One small trap for whoever writes T9: `item_people` spells its document order `sort_order` while
  the other three join tables spell it `position`.

## T6 — The filter battery

- [x] **Changes:** every filtering predicate `ItemQuery` names, in the repository:
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
- **Done (2026-08-27):** the first predicate written found a **defect in 003's write path**.

  `searchTerm` matched nothing, on any item, because **`ItemRepository.add` never wrote
  `name_folded`.** `name`, `sort_name` and `name_folded` are three derivations of one string; the
  first two were written there and the third was left to `MetadataRepository.apply`, which sets it
  only when a refresh *changes* the name. So an item that had been scanned and not yet refreshed
  carried an empty folded name — **invisible to `searchTerm` and `nameStartsWith`**, silently,
  while looking perfectly correct in every list it appeared in. 004 wrote the column and nothing
  read it until now, which is exactly how it survived two features. Fixed in `add` and in the
  branch of `update` that owns the name before a refresh does.

  **The two artist parameters were measurable and guessable-wrong.** The first version of the test
  asserted that `artistIds` finds performers and `albumArtistIds` finds album artists, as disjoint
  sets. Measured: `artistIds` is the **superset** — it matches any credit, the album's own
  album-artist row included — and one artist on the reference answers 6 items to `albumArtistIds`'
  2, while a performer who is nobody's album artist answers 2 to 0
  `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]`.

  **T3's world could not exercise four of these predicates**, and two of them would have passed
  anyway. No film carried a `ProductionYear` or a `CommunityRating`, so `years` and
  `minCommunityRating` had nothing to narrow — a predicate over a column that is null on every row
  narrows nothing and passes every assertion about the rows it returned. And every item's
  performer *was* its album artist, so the two artist filters returned identical rows: "the credit
  distinction, leaned on for the first time" would have been leaned on and proved nothing. The
  world now carries ten rated films and a **guest album** — a second artist's record with one
  track performed by the first — which is the only shape in which the two can disagree.

  Three decisions the plan did not contain, now in §6.2: related-row filters are `EXISTS` and not
  joins, because a join needs a `DISTINCT` that then has to survive every `ORDER BY` T7 adds; an
  **empty collection means "asked for nothing"** while `None` means "did not ask", which is the
  difference between answering no items and answering the whole library to a request whose tokens
  were all dropped (behaviours §1.12); and absence of a user-data row **is a state**, so unplayed
  is `NOT EXISTS(played)` rather than `EXISTS(NOT played)` — the second finds only items somebody
  has already touched, which on a fresh account is none of them.

  `MediaType` turned out to need a measured table rather than a derivation: `MusicAlbum` is
  `Unknown`, which any rule built on "does it hold audio" would call `Audio`. It is
  `domain.items.MEDIA_TYPE_OF`, and T9 needs it too — it is in §3.2's always-present set.

## T7 — Ordering is total; `Random` is seeded

- [x] **Changes:** [plan §6.3](plan.md#63-order-by)'s table — `SortName`, `DateCreated`,
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
- **Done (2026-08-27):** **AC-4 as written would have passed while testing nothing for the two
  sorts it exists to protect.**

  The criterion says to page *the 100-item corpus*, and the corpus is films. Films have no artist
  credits, so under `AlbumArtist` and `Artist` every row's key is null and the property test
  exercises the id tail and nothing else. Those two are precisely the sorts
  [behaviours §3.6](../../docs/compatibility/behaviours.md#36-ties-are-engine-resolved-and-paging-the-artist-sorts-loses-rows--class-b-diverged)
  measured **losing rows** on the reference — the whole reason the tail exists. The test now pages
  the whole world as well, and a second test asserts the artist keys actually order something, so
  a null-keyed run cannot masquerade as a passing one. Plan §8 row 4 amended.

  **Two of plan §6.3's expressions were written portably rather than literally.**
  `COALESCE(premiere_date, jan1(production_year))` needs a database function that builds a
  timestamp out of an integer, and every dialect spells that differently; ordering by the
  *effective year* first, with the date second, puts a year-only item exactly where January 1
  would — and `extract` compiles on both stores. The fixture was shaped to catch the difference:
  one film's premiere date is **older than its own production year**, so a dateless-clumping
  implementation puts it on the wrong side of a year-only film, whichever end it clumps at.

  The artist keys are **lower-cased, not folded**: `fold_for_search` strips diacritics and no
  dialect does that portably. There is nothing measured to be wrong against — the reference's key
  for those two lives in a joined table the API does not return, which is why
  `probe_sort_stability.py` reports rather than concludes on them — so it is recorded as a known
  approximation rather than a claim.

  **The seed had to be a field of the query.** Plan §6.4 said "tests inject it" without saying
  where. Passing it beside the query would mean two equal `ItemQuery` values describing different
  pages, for the one ordering where that matters most, so `random_seed` is on `ItemQuery` with a
  docstring saying it is never client-supplied. §5 and §6.4 amended.

## T8 — By-name queries

- [x] **Changes:** `ItemQueryRepository.run_by_name` — `Genre`, `MusicGenre` and `Year` rows,
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
- **Done (2026-08-28):** **nothing had ever created a `Year` row.**

  `MetadataRepository.apply` writes a by-name row for every genre, studio and person it sees, and
  none for the year — while `collect_by_name_garbage` has always protected `Year` rows on the
  assumption that something made them, and its docstring explains at length *why* a `Year` is
  checked separately. So the collection half of a feature existed, carefully documented, with no
  creation half at all. `/Years` would have listed nothing, and `GET /Items/{yearId}` would have
  answered `404` for a year the library plainly has. Fixed in the write path rather than by
  deriving `/Years` from a `DISTINCT`, because a `Year` **is** an item and the item route has to
  answer for it.

  **The membership clause belongs in §6.1's predicate, not in `run_by_name`.** A by-name row is an
  item, so `/Items?includeItemTypes=Genre` has to give the same answer as `/Genres` — two
  predicates in two places is how they stop agreeing, and a test now asserts the two routes agree
  on a user who may see neither. What `run_by_name` adds is only what these routes ask that
  `/Items` does not: the `parentId` scope and the credit reading.

  **T5's pinned test came good.** It asserted by-name rows were visible to everyone and said in
  its own docstring that T8 would narrow it. It did, and the test needed only its reason rewritten
  — which is the whole argument for pinning a deliberate gap rather than leaving it implicit.

  The adversarial half is the one worth keeping: a genre whose every film sits in a library the
  user cannot see is **not** a leak of the films. It is a leak of what the library contains, which
  is the only thing a by-name row can disclose — and it is tested by making one row unreachable
  for one user and reachable for another out of the same database, so an implementation that hid
  every by-name row could not pass.

## T9 — The item surface: models, the DTO builder, and the `Fields` registry

- [x] **Changes:** `api/item_models.py` — `BaseItemDto`, `UserItemDataDto`, `NameGuidPair`, the
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
- **Done (2026-08-28):** the registry is data, the three widths are a parameter of the call site,
  and AC-2 and AC-3 hold at builder level. **Most of the task was discovering that the builder had
  nothing to build from.**

  **Hydration carried no metadata and no ancestors.** `HydratedItem` had genres and images and not
  one of 004's scalar columns — no overview, no year, no rating reached the domain — and an
  episode had no way to say its series' name. The columns ride the row the page already fetched
  (a mapping gap, zero new statements); the ancestors are two summarised levels on `HydratedItem`
  itself, **not** the "parent rows in ctx" plan §5 promised, which would have made every route
  re-associate rows the repository had already associated. §5 amended. The statement budget moved
  9 → 15, page-independent, and both counter tests were updated as the decision their docstrings
  say they exist to force.

  **A container's `UserData` is a statement about its subtree.** Measured: a bare `Series` row
  carries `UnplayedItemCount`, and a fully-watched season answers `Played: true` with
  `PlayCount: 0` — the rollup, not the stored row. Hydration now computes both per page (two
  grouped statements); spec §3.2's `UserData` row says it. And two smaller holes the same
  measuring pass found: **a by-name row has no `IsFolder`, anywhere**, and `/Genres` rows carry
  no `UserData` while the same genre through `/Items` does — a per-route omission left for T14
  to measure against `/Years` and reproduce.

  **T1's own prediction came due one task later.** `GenreItems` is emitted by the server, declared
  by the 10.11.11 document, and absent from the pinned 10.11.10 document — so the alias sweep
  refused the field. It is now a measured exception in the sweep with the argument recorded in
  reference-target §1: the index's version *is* the pin, and regenerating it from the newer
  document would move the pin as a side effect of a test.

  **`extra="ignore"` eats a typo'd registry name, emitter and all.** `BaseItemDto(**values)` with
  a key the model does not declare drops it silently — found when `AlbumPrimaryImageTag` had an
  emitter, a registry row and no field, and every test around it passed. A guard test now compares
  the emitted names against the model's declared aliases; it caught the bug on its first run.

  **Three emitters answer for values 004 never stored**, each recorded in plan §6.5 rather than
  guessed: `Etag` as a hash of identity plus the two change clocks, `ExternalUrls` as a measured
  table over `ProviderIds` (the `Tmdb` URL depends on the item's type), and `ImageBlurHashes` as
  the always-empty map — an accepted gap with its closing mechanism, behaviours §5.5.

  **And the spec's per-type table was still the draft's.** T1 corrected the always-present set and
  the Common group and left the type families as written; row by row they were wrong — a `Series`
  list row carries no `ChildCount` and no `IndexNumber`, a `Season` carries the series context, an
  album carries the artist lists. §3.2 now holds the measured matrix, and the registry test
  compares against it verbatim, so the next drift fails by name.

## T10 — `GET /Items` and `GET /Items/{itemId}`

- [x] **Changes:** `api/items.py` — parameter binding with the pinned document's spellings;
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
- **Done (2026-08-28):** both routes, thirty-four bound parameters, sixteen reviewed goldens, and
  the pipeline held: the route module contains parsing, the choice of shape, and refusals — no
  SQL, no session, which the T5 import rule enforced the moment this task tried to annotate a
  helper with one. Helpers take repositories, as the rule's own message says.

  **The drop rule inverts an answer if applied naively, and no document had said so.**
  `includeItemTypes=Playlist` under behaviours §1.12 alone would *drop* the token — `Playlist` is
  no `ItemType` of this domain — and dropping the only token un-filters the query: a client asking
  for playlists would receive **the whole library**. But `Playlist` is a real `BaseItemKind` the
  reference filters by; only a token that is no kind at all drops. The route carries the
  reference's kind vocabulary verbatim to tell the two apart — a kind v1 cannot produce keeps the
  filter and matches nothing, riding T6's empty-means-asked-for-nothing contract. Spec §3.3 and
  plan §6.12 now say it.

  **The identical `404` is the pipeline's, not a comparison's.** `/Items/{itemId}` is one `ids=`
  query under the same visibility predicate as every list; unknown and invisible are the same
  empty page and the same `NotFoundError`, and the AC-8 test masks only the per-request `traceId`.
  A malformed id never reaches the query — `WireGuid` refuses it into the validation `400` — and a
  malformed identifier *inside* `ids=` is the same `400` raised by hand in the binder's own error
  shape, so the measured body falls out of the one handler.

  **Two `userId` decisions are recorded as unmeasured** rather than silently chosen: an
  administrator naming an unknown user gets the problem-details `404`, and an administrator naming
  a real one queries with the **named user's visibility** (the tier-1 description, taken
  literally). The non-administrator refusal is the empty `403` through the 002 seam, as plan §7
  rows both. The differential owns all three.

  **The battery runs every case twice**, once with the declared spellings and once case-mangled,
  asserting byte-identical bodies — behaviours §1.15 re-held on a real route, which is what T4's
  scratch-route test could not do. And the goldens needed **no placeholder at all**: the world is
  deterministic by construction and `Etag` hashes only pinned clocks, so all sixteen files are
  byte-stable — the first goldens in the project with nothing masked.

  One consequence for the tasks after this one, recorded in `server.py` too: `items.router` owns
  `/Items/{itemId}` and sits **last** in `ROUTERS`, so T11's `/Items/Latest` and T15's
  `/Items/Filters` must register before it or their literals are read as identifiers.

## T11 — The user's world: `GET /UserViews` and `GET /Items/Latest`

- [x] **Changes:** `api/user_views.py` — the libraries after policy, each with
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
- **Done (2026-08-28):** the task ordered the measurement first, and **the measurement overturned
  the plan's grouping rule in one response**: an episode does *not* always surface as its series.
  A group surfaces as its container only when it holds more than one recent item — the measured
  list carried a `Series` beside a lone `Episode`, and a lone `Audio` beside grouped
  `MusicAlbum`s. Implemented as measured, and the world's guest album — one track — is exactly
  the singleton the rule needs, so the test that holds it asserts both shapes in one body.
  Spec §3.7 and plan §6.8 corrected.

  **The exclusion key came with a sibling nothing had named.** `LatestItemsExcludes` is the
  measured key — view identifiers, so the match is against the derived folder identity — and
  beside it sat `HidePlayedInLatest`, `true` on a configuration never edited, which is why every
  entry in the measured Latest was unplayed. Ignoring it would have made Atrium's Latest show
  played items the reference hides, on every default account, for ever. Both keys are honoured
  from the stored configuration; exclusions bite only the unscoped request, because a client that
  named a view by `parentId` asked for that view. `isPlayed=true` overrides the hiding, measured.

  **`ParentId` is an explicit null on a view row**, and pydantic nearly swallowed it: a
  `UserViewDto` inside `list[BaseItemDto]` serialises with the *declared* class's schema, so the
  subclass's `NULL_KEPT` never runs. `UserViewQueryResult` types its rows to the view class — a
  sibling envelope rather than a subclass, because a `list` field is invariant and mypy said so
  before a test had to.

  **Grouping cannot know its fetch size**, so the route pages the repository — fixed page size,
  first-seen order, until `limit` groups exist or the world runs out — and the containers that
  surface are fetched through the same pipeline, arriving with the rollups every container row
  carries. The shared parameter parsing moved to public names in `api/items.py` rather than being
  duplicated; the three `GetUserViews` parameters v1 has nothing to act on
  (`includeExternalContent`, `presetViews`, `includeHidden`) stay undeclared on purpose, so a
  client that sends them shows up in the ignored-parameter record instead of being half-honoured.

## T12 — Series navigation: `GET /Shows/{seriesId}/Seasons` and `/Episodes`

- [x] **Changes:** `api/tv_shows.py`, first half — Seasons ordered by the specials-last
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
- **Done (2026-08-28):** the task said measure the specials order first because the claim carried
  no provenance, and **the measurement reversed it**: a live series with a specials season answers
  `[Specials, Season 1]` — season 0 sorts **first**, plain index order, and the spec's "every
  client expects it last" was an expectation about clients presented as a fact about the wire.
  AC-11 is corrected to the measured order (spec §3.8 and §5 amended), and the implementation
  shrank by the exact amount the wrong claim had cost: plan §6.9's specials-last expression is
  deleted, because 003's zero-padded sort names already produce the measured order by themselves.
  The default pipeline ordering *is* the answer.

  Everything else held as written. Unknown and invisible series — and an unknown `seasonId` —
  are the identical problem-details `404` through the same typed refusal as every scoped query;
  `seasonId` scopes with its own query while the `season` number narrows in process;
  `startIndex`/`limit` page with the pre-paging count in the envelope; the `S01E02-E03` item
  appears once; `isSpecialSeason` filters both ways; and `isMissing` narrows to the placeholders
  v1 honestly does not have, which is `DisplayMissingEpisodes`' trivial honour written down
  (plan §6.9). `adjacentTo` and `startItemId` stay undeclared, so a client that sends them lands
  in the ignored-parameter record rather than being half-served.

## T13 — The played-state pair: `GET /Shows/NextUp` and `GET /UserItems/Resume`

- [x] **Changes:** `api/tv_shows.py` completed with NextUp — per series with a played episode,
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
- **Done (2026-08-28):** the probe ran first and, for once, **confirmed the documents** — with
  the discriminating case they could not have confirmed themselves. Marking E02 played and then
  E01 *afterwards* reads E03 back both times: "next" follows the **highest-numbered** played
  episode, and a rewatch of an early one moves nothing. One row per series and
  most-recently-played-first held too. The probe writes to answer at all — there is no play
  state to measure until something is played — so it refuses series whose episodes carry any
  user data, deletes every mark in `finally`, and verifies the episodes pristine before
  concluding; `tools/README.md` carries its row in both tables.

  **What the probe could not answer, it says out loud**: the measured library has no pristine
  specials season, so whether a played special drives the chain is still unmeasured — flagged
  ⚠️ in spec §3.7 rather than silently assumed, with the rule implemented as specified and a
  test holding that a finished regular season answers nothing rather than promoting season 0.

  **One deviation from the plan's shape, recorded in §6.8**: the window function it promised
  became one played-episodes query plus a bounded per-watched-series pass through the pipeline.
  The pipeline hands hydrated episodes with play state and ancestors attached, and the
  multi-episode file anchors **as far as it spans** — `S01E02-E03` played means next is E04 —
  which a window function outside the one reader would have had to reimplement. Resume came out
  the other way: exactly the one query the plan described, `IsResumable` ordered by
  `DatePlayed` descending in the envelope, with nothing route-specific but parameter parsing.

## T14 — The by-name endpoints

- [x] **Changes:** `api/artists.py`, `api/genres.py`, `api/years.py` — five routes over
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
- **Done (2026-08-28):** five routes over one helper, and **AC-13 as drafted could not be
  satisfied by any Atrium world** — which is a consequence this project had already recorded and
  nobody had connected to the criterion. An Atrium `MusicArtist` is a per-library item the
  scanner creates per *album artist* (behaviours §5.3), so an artist who only ever performs has a
  name on every credit and **no row to list**, and `/Artists` therefore coincides with
  `/Artists/AlbumArtists` as a row set, structurally. The strict containment the criterion
  imagined lives on the reference, whose artists are by-name rows. AC-13 is restated at the level
  where the distinction measurably bites — `artistIds` finds the guest track, `albumArtistIds`
  does not — and the coincidence itself is asserted *with its reason*, so the day it breaks,
  somebody rereads §5.3 rather than shrugging.

  **The per-route omissions were measured before the routes were written**: `/Genres` and
  `/MusicGenres` rows carry no `UserData`, the two artist routes no `IsFolder`, `/Years` keeps
  both — while the same rows through `/Items` carry everything. One `omit` switch on the builder
  context reproduces all three, and a test walks the family asserting each against `/Items`.

  **And behaviours §3.1 turned out to have a face nobody had measured**: `/Years` without a
  `limit` answers a count that is neither zero nor the row count — `9754` beside 97 rows on the
  measured library. The entry now carries the measurement; Atrium answers the true count on all
  five (AC-5, held with and without `limit` across the family).

## T15 — The two other shapes: `GET /Items/Filters` and `GET /Search/Hints`

- [x] **Changes:** `api/filters.py` — `{Genres, Tags, OfficialRatings, Years}` for a parent:
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
- **Done (2026-08-28):** both measurements the gate ordered came back, and **both went against
  the spec**.

  **The name-versus-sort-name disagreement is settled: the name wins.** The discriminating item
  the measurement needed actually existed on the live library — a title whose padded sort form
  shares no substring with its folded name — and searching by that sort fragment finds
  **nothing**. Spec §3.10 loses its "and sort name"; plan §6.11's `name_folded` reading was
  right all along. The corpus' own awkward names hold it at endpoint level: "The Mat" (an
  article the sort name dropped) finds The Matrix, "00002" (a padding only the sort name has)
  finds nothing.

  **And `MatchedTerm` does not exist on the wire.** Seventeen measured hints across three terms,
  not one carrying it — the spec's "populates `MatchedTerm` so a client can highlight it"
  described the schema, not the wire, and AC-14 required populating a field the reference never
  sends. AC-14 is restated; Atrium, like the reference, leaves it out. What the measurement
  *added*: `Artists` travels on every hint (empty list included), `ChannelId`'s explicit null
  reaches hints too, and the three image-tag pairs resolve through the ancestors — a track's
  hint carries its album's cover — all of which the hydration already had in hand.

  **The filter summary behaved as the gate's amendment guessed, with two details measured in**:
  all four keys always (empty lists included), each list **sorted ascending**, and the genres
  are the items' own spellings — `Acción` and `Action` are two entries, because this list is
  what items carry and the merged row is `/Genres`' business. `searchTerm` on `/Search/Hints`
  is the one required parameter in the feature: missing, it is the validation `400`.

## T16 — The deterministic pair: `Similar` and `InstantMix`

- [x] **Changes:** `api/similar.py` — candidates of the seed's type, visible, not the seed;
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
- **Done (2026-08-28):** the quiet task of the feature — the formulas landed as the plan wrote
  them, the weights are named constants with the §6.10 table cited beside them, and AC-12 holds
  with the mix's order **recomputed in the test from the same hash**, which is what proves the
  order a pure function of seed and library rather than a cached accident. Two refinements the
  plan gained rather than fought: a **track** seed borrows its album's genres — a music genre
  lives on the album row where the sidecar put it, so a track-seeded mix under the plan's literal
  wording would always have been empty — and "sharing" is by the **by-name row**, so `sci-fi`
  and `Sci-Fi` relate two films whatever their spellings say, which is exactly the world's
  two-spellings fixture doing its job on the Similar side. The guest album, carrying no genre,
  mixes honestly to nothing rather than to the whole library.

## T17 — The acceptance map, and Implemented

- [x] **Changes:** `FEATURE_005` in `tests/conformance/test_acceptance.py`, mapping **all
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
- **Done (2026-08-28):** the map names sixteen criteria, **ten of them at two or three levels**
  — repository or builder once, the route once more — for 004's recorded reason: a correct rule
  and a rule the caller actually uses are two claims. The gate's own addition earned its place:
  the shape roll-up walks the seventeen 005 rows of `surface.yaml` itself, so a list route added
  to the surface without a row in the roll-up fails by name — AC-1's *every* is a property now,
  not six tasks' habit. `LANDED_EARLY` is deleted and `"005"` is in `IMPLEMENTED_FEATURES`,
  which is what finishing looks like in that file, twice over now.

  Worth counting at the close: **four acceptance criteria and two plan algorithms did not
  survive contact with the measured reference** — AC-11 reversed (specials first), AC-13
  restated (behaviours §5.3 forbids the drafted containment), AC-14 restated (`MatchedTerm`
  does not exist on the wire), AC-1's "one representation" split into three widths at T1 — and
  every correction is in the spec with provenance, in the same change that learned it. The
  definition of done below is closed line by line.

---

## Definition of done

Closed line by line at T17, on 2026-08-28.

- [x] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all sixteen
      — has a passing test, by name, in `FEATURE_005` (T17). Ten are named at more than one
      level, once where the rule is proved and once where the route is proved to use it.
- [x] Every endpoint reaches the conformance level [spec §6](spec.md#6-conformance) declares —
      with the L3 debt stated rather than hidden: `GET /Items` and `GET /Items/{itemId}` carry
      sixteen reviewed goldens per item type (T10), placeholder-free because the world is
      deterministic, and join the differential when 010 lands, which is the debt
      [plan §8](plan.md#8-testing-strategy) acknowledges and 010 pays.
- [x] All seventeen routes are served, `"005"` is in `IMPLEMENTED_FEATURES`, and no route exists
      outside [`surface.yaml`](../../docs/compatibility/surface.yaml) — the seventeen rows were
      in the file before this list was written, so the check was registration, not listing.
- [x] The feature ends owning **no state**: no table, no column, no cache
      ([plan §4](plan.md#4-data-model)), and no index was needed — 004's pattern-named indexes
      carried every query. The one write this feature made is T8's fix to 004's write path,
      which created the `Year` rows 004 had promised and never made.
- [x] The query counter is green across the suite: hydration is 15 statements whatever the page
      size (T9's deliberate move from 9, recorded in the counter test's own docstring), and the
      route-level parity test holds it over HTTP.
- [x] Anything learned during implementation is back in `spec.md` or `plan.md` in the same
      change. The `amended:` lines name **eight** tasks and the gate between them.
- [x] Every measurement a task took against the reference is in the spec or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) with provenance — T1's three
      widths and the `ChannelId` null (behaviours §1.7 amended), T9's by-name row shapes and
      §5.5 (no BlurHash), T11's grouping and the two configuration keys, T12's specials order,
      T13's NextUp chain (`tools/probe_next_up.py`, in both `tools/README.md` tables), T14's
      per-route omissions and §3.1's `/Years` face, T15's hint fields and the name-only match.
      One thing could not be measured and says so ⚠️ in spec §3.7: whether a played special
      drives the NextUp chain — no pristine specials existed to play.
- [x] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

**006** inherits the image surface 005 emits: `ImageTags`, `BackdropImageTags` and the per-type
parent tags are computed from `item_images` rows alone, and the bytes those tags identify are
006's to serve — the tag values in the sixteen goldens are the contract. `ImageBlurHashes` is
the empty map on every row (behaviours §5.5): computing real hashes belongs where the bytes are
open, and the differential will show the gap on every item until it closes.

**007** owns what the stored user-data columns mean, and 005 built two things on top it should
know about: a container's `Played`/`UnplayedItemCount` are a **per-page rollup of the subtree**
computed in hydration (measured, `db/item_queries._rolled`), and `PlayedPercentage` is derived
from position over runtime at DTO level. If 007 changes what a stored row means, those two are
where the change surfaces.

**008** has a failing-test-in-waiting: `MediaSources`, `MediaStreams`, `Chapters`, `Width` and
`Height` are the `UNPROBED` set in `api/item_dto.py`, undeclared on the model on purpose, and
`test_the_unprobed_five_stay_absent_even_when_asked` asserts the absence — 008's first emission
breaks that test, which is the intended signal to declare the fields and delete the tripwire.

**009** flips one behaviour by existing: `includeItemTypes=Playlist` narrows to nothing today
because `Playlist` is a `BaseItemKind` v1 cannot produce (`api/items.py`, `BASE_ITEM_KINDS`) —
the day playlists exist, that same filter must find them, and `PlaylistItemId` is declared in
spec §3.2's table waiting for its emitter.

**010** collects the flags this feature raised for the differential: the `userId` guard's `403`
and the administrator's `404` for an unknown user (both unmeasured, `api/items.py`), the
specials half of NextUp's chain (⚠️ spec §3.7), the `GenreItems`/`LockedFields` pinned-document
gap (reference-target §1 — the alias sweep's measured exception empties if the pin moves), and
OQ-1/OQ-2, whose answers are the ignored-parameter record and the field-by-field diff this
feature built the events for.
