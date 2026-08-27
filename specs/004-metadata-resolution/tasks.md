---
feature: 004-metadata-resolution
title: Metadata resolution — tasks
status: Accepted
created: 2026-08-27
updated: 2026-08-27
accepted: 2026-08-27
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 004 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries two structural decisions.** The merge engine and its lock matrix are green
at T6, before any remote provider exists — the capability to overwrite an item with somebody
else's data arrives only after the thing that constrains it is enforced by tests, the same shape
as 003 building its scanner additive-only. And every remote request in the feature goes through
one module, T11, which lands sealed — rate-limited, cached, transport-injectable — before either
provider is written, so no later task can accidentally produce an unthrottled loop against
somebody's API.

**The read-only guarantee is a guard, not a finale.** The tree-hash test (AC-15) lands at T10
with the first end-to-end refresh and runs under every task after it, because a write path into a
library root is the one failure here that is quiet, and quiet failures get their tests first.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files it
references on 2026-08-27 before being accepted. Three things changed, all of 003's gate's class —
promises with no task holding them:

| The draft said | It was |
|---|---|
| T10 proves AC-1 — a fully-sidecared film refreshes with zero network requests | **Only while there was nothing to prove it against.** T10's world has no remote code, so its zero is vacuous; nothing re-held AC-1 once T12–T14 wired providers, and [plan §6.8](plan.md#68-refresh-orchestration) step 2 never stated the condition that makes it true — remote is consulted only for fields the local pass left wanting. T14 now re-holds AC-1 on the counting transport, and the plan says the clause out loud |
| Recorded fixtures were the whole provider-test story | **[Plan §8](plan.md#8-testing-strategy) promises an opt-in live test** — one movie, one album, `needs_reference`, never gating CI — and no task delivered it. `tests/conftest.py` even documents the marker with *"Nothing does yet."* Now in T14 |
| T15 registers the route and the feature set | **`tools/generate_cultures.py` had no row in [`tools/README.md`](../../tools/README.md)** — the table every other script in that directory is held by. Now in T15's changes |

What was checked and held: all sixteen acceptance criteria are claimed by name (mechanically, not
by reading); every module in [plan §3](plan.md#3-modules) has a task; every file the list points
at exists — the migration sweep, the `needs_reference` marker, `IMPLEMENTED_FEATURES`, the
acceptance-map harness — and T1's two client checkouts are present on the machine that will run
it.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — The client survey: resolve OQ-5 before the schema freezes

- [x] **Changes:** no source. [spec §7](spec.md#7-open-questions) OQ-5 — whether ReplayGain values
  are exposed anywhere a client reads — moves to the resolved table with the survey's finding, or
  stays open with a written reason. The survey reads the two client checkouts
  [api-surface-v1 §1](../../docs/compatibility/api-surface-v1.md#1-how-this-set-was-derived)
  describes by role; findings are recorded **by role only**, because their internals are not this
  repository's to publish. Anything the same reading shows about which `ProviderIds` keys the
  clients consume is noted against OQ-4 as partial evidence — without closing it, since the
  differential harness (010) owns that answer.
- **Depends on:** nothing
- **Verified by:** [spec §7](spec.md#7-open-questions) updated in this change; the decision the
  finding gates is taken visibly at T4 — a `replay_gain` column that nothing will ever read is
  storage without a consumer, and the migration should know that before it exists, not after.
- **Note:** first because it is the only measurement 004 can take today that changes a schema
  decision, and every feature so far has paid for building on an unmeasured claim.
- **Plan reference:** §4; spec §3.3
- **Done (2026-08-27):** the task offered T4 two answers — a `replay_gain` map or its recorded
  absence — and **the finding is neither**. The reference reads exactly one of the four ReplayGain
  values, the track gain, and *does* serve it, as `NormalizationGain` on every item
  `[source: MediaBrowser.Providers/MediaInfo/AudioFileProber.cs:362-375 @ v10.11.11]` `[spec: BaseItemDto]`.
  So a map stores three values no response can carry, and dropping the column loses one that 005
  has to emit. T4 builds a single nullable float, `normalization_gain`
  ([plan §4](plan.md#4-data-model), amended in this change).
  Two more things the reading turned up, both recorded rather than left in a transcript. The
  reference has a **second** source for the same field — an opt-in loudness scan that decodes every
  audio file and overrides the tag — which v1 cannot afford before 008 owns a decoder, so it is an
  accepted gap with its closing mechanism
  ([behaviours §5.4](../../docs/compatibility/behaviours.md#54-no-loudness-scan-so-a-track-without-the-tag-has-no-gain)).
  And OQ-4's partial evidence came back **empty in the strongest sense**: neither client mentions
  `ProviderIds`, or any provider's name, anywhere. That is a floor of zero, which cannot tell us
  which keys to emit, so OQ-4 stays open on 010 with the evidence written beside it.

## T2 — Fixture groundwork: sidecars, artwork, and the four template containers

- [ ] **Changes:** `tests/fixtures/metadata/` — sidecar fixtures (full, sparse, id-bearing,
  malformed, entity-bearing), artwork files covering every name in
  [plan §6.4](plan.md#64-local-artwork)'s tables, and four tiny silent template containers (FLAC,
  MP3, M4A, Ogg) **checked in**, with the commands that generated them recorded in a README beside
  them.
- **Depends on:** nothing
- **Verified by:** the templates are checked-in bytes, so determinism is by construction; the tree
  stays small (tens of kilobytes); no file is a copyrighted work — silence we generated; the suite
  is still green with no consumer yet.
- **Note:** 003's placeholder files stay untouched — they exercise scanning; these exercise
  *reading*. Template-plus-retag keeps "generated at build time with known tags"
  ([spec §6](spec.md#6-conformance)) true without adding a muxer to CI — 003 T2's lesson,
  inherited rather than relearned.
- **Plan reference:** §8

## T3 — `metadata/model.py`

- [ ] **Changes:** the field vocabulary, `FieldValues`, `RefreshMode`, the identify results —
  pure, no I/O.
- **Depends on:** nothing
- **Verified by:** the value-ness rules as a table — `None`, `""`, `[]` and whitespace-only are
  not values ([spec §3.1](spec.md#31-the-provider-model)), while the seam's
  present-and-empty tag distinction survives; an import-direction test (`metadata/model` imports
  nothing from `db/`, `api/`, `library/`); mypy strict.
- **Plan reference:** §3, §5

## T4 — Migration `0003_metadata_and_by_name`, the models, and the by-name identity rule

- [ ] **Changes:** revision 0003 exactly as [plan §4](plan.md#4-data-model) lays it out: the
  metadata columns on `items` (including `name_folded` and, **per T1's finding**, the single
  nullable float `normalization_gain` rather than the map this list first named), the five join
  tables, `provider_cache`, the type check gaining `Genre`,
  `MusicGenre`, `Studio`, `Person`, `Year`, and `library_id` nullable with the check tying `NULL`
  to exactly those five. `db/models.py` to match. `domain/items.py` gains the five types **outside
  the containment tree**. `library/identity.py` gains the server-wide by-name rule beside 003's
  four, `RULE_OF` extended, each function still refusing types that belong to another rule.
- **Depends on:** T1, T3
- **Verified by:** the migration sweep (up, down, up — reversible in 002 T16's sense); constraint
  tests in both directions — a by-name row with a library refused, a file-backed row without one
  refused; identity tests — the same name as `Genre` and `MusicGenre` gives two ids, case folds,
  diacritics do not (the [behaviours §2.18](../../docs/compatibility/behaviours.md#218-two-spellings-of-one-genre-are-one-item)
  envelope); the pattern-driven indexes exist.
- **Note:** the trap is the containment map. `domain/items.py` asserts every chain ends at a
  `CollectionFolder` and that `PARENT_OF`'s leaves are exactly the file-backed types; the by-name
  types must be exempted **deliberately, in the test that holds the map**, or the assertion gets
  loosened in passing and stops guarding the tree it was written for.
- **Plan reference:** §4; spec §3.7

## T5 — `metadata/nfo.py`

- [ ] **Changes:** sidecar discovery per the [spec §3.2](spec.md#32-nfo-sidecars) table; the
  parser on stdlib `ElementTree`; the field map including `sorttitle` routed through 003 §3.7.3's
  explicit-sort-title treatment; provider ids; the size cap.
- **Depends on:** T2, T3
- **Verified by:** the fixture sidecars parse to their expected `FieldValues`; the malformed and
  the entity-bearing fixtures each produce a warning naming the file and nothing else (AC-4's
  parser half — `ElementTree` refuses DTDs, so the XXE class *is* the malformed path); a single
  `<genre>` containing ` / ` stays one genre; `runtime` minutes become ticks at ingestion and
  nowhere else.
- **Plan reference:** §6.2

## T6 — `metadata/merge.py`

- [ ] **Changes:** the per-field precedence walk, the mode × locked × empty matrix, the
  lists-whole-from-one-provider rule. Pure.
- **Depends on:** T3
- **Verified by:** every cell of the [plan §6.1](plan.md#61-the-merge) matrix as a table test —
  AC-10 and AC-11 are held here first, at engine level, and again end-to-end at T14; the provider
  chains of [spec §3.1](spec.md#31-the-provider-model) asserted as data, music's inversion
  included; a provider that returns nothing for a field can never blank it.
- **Note:** this is the first structural decision landing: the thing that constrains overwriting
  exists, tested, before anything capable of overwriting does.
- **Plan reference:** §6.1

## T7 — `metadata/tags.py`, and the seam goes live

- [ ] **Changes:** mutagen enters `[project.dependencies]` with plan §3's reasoning; the
  per-container readers; `TagSource` implementing 003's `MetadataSource`; the scan's music
  resolution pointed at it by default (`PATH_ONLY` remains the explicit no-reader fallback); a
  per-scan memo so one file is opened once for both the resolver's question and the refresh's.
- **Depends on:** T2, T3
- **Verified by:** per-format template-plus-retag fixtures — multi-valued tags stay lists in
  every container (AC-6's groundwork) and a `;` inside one value stays one artist; the seam's
  contract holds (keys of 003 §3.5's vocabulary, empty string present-and-empty); **003's whole
  suite still green**, the signal-gating tests included — the seam still not consulted for an
  unchanged file; a scan of a tagged fixture hangs tracks under tag-derived albums where the
  directory disagrees (AC-5's groundwork).
- **Note:** after this lands, re-read 003 §7 **OQ-8** and update it with what is now measurable:
  this reader makes the untagged-fraction question answerable against a *real* library, which
  this suite is not, and the question should say which half moved.
- **Plan reference:** §5, §6.3; spec §3.3

## T8 — `metadata/artwork.py`

- [ ] **Changes:** Pillow enters the dependencies; the name tables of
  [spec §3.4](spec.md#34-local-artwork); ordering for numbered backdrops; dimensions and the
  content tag at association time; embedded cover art as `Primary` only when no file-based one
  exists.
- **Depends on:** T2, T7
- **Verified by:** every name in the tables resolves to the right image type and index on
  fixtures; a file Pillow cannot identify is skipped with a warning, and **no association row
  exists without dimensions and a tag**; the tag is unchanged across a rescan of an unchanged file
  and changes when the bytes do — 006 AC-2's ancestor, cheaper to hold now than to retrofit.
- **Plan reference:** §6.4

## T9 — The write path: `MetadataRepository` and the by-name rows

- [ ] **Changes:** `metadata/byname.py` — the fold (lowercase, path-invalid characters to spaces,
  trim, trailing dots off); `MetadataRepository` in `db/repositories.py` — `apply`,
  `ensure_by_name`, garbage collection; join-table writes preserving people's role and order and
  artists' credit kind.
- **Depends on:** T4, T6
- **Verified by:** AC-14 at repository level — two spellings, one row, first spelling displays;
  the fold's envelope (case folds, diacritics distinct, `Drama/Romance` meets `Drama Romance`);
  GC removes a row nothing references and a later reference recreates it **with the same id**;
  `apply` is transactional — a failure mid-apply leaves no half-written item.
- **Plan reference:** §5, §6.7

## T10 — Local refresh: orchestration without a network

- [ ] **Changes:** `metadata/refresh.py`, local slice only — sidecar, tags, artwork, through the
  merge, one `apply` per item; `library/scan.py` hands changed-and-new item ids to it after a
  scan commits, `deep` hands everything; `Local only` mode complete.
- **Depends on:** T5, T6, T7, T8, T9
- **Verified by:** end-to-end on the fixture library — AC-1 and AC-2 (full and sparse sidecars,
  per field), AC-4, AC-5, AC-6, AC-7, AC-11 and AC-14 at integration level; **AC-15 lands here**:
  SHA-256 over every fixture byte before and after a full scan-and-refresh, byte-identical — and
  the test stays, so every later task runs under it; a rescan of the unchanged library refreshes
  nothing, extending 003's signal gating through this feature.
- **Note:** zero network is trivial in this task — no remote code exists yet — which is exactly
  why the guard arrives now: it is cheap to hold before T11 and expensive to retrofit after.
- **Plan reference:** §6.8, §8; spec AC-15

## T11 — `metadata/remote.py`: the one HTTP door, sealed before anyone walks through it

- [ ] **Changes:** httpx moves from the dev group to `[project.dependencies]`; per-provider token
  buckets; `provider_cache` read/write with TTL and the `Replace` bypass; credentials from the
  configuration file; the transport injectable, with a counting transport for tests.
- **Depends on:** T4
- **Verified by:** the bucket honours its rate under a fake clock; the cache's hit / miss /
  expired / bypassed cases as a table; an import-direction test that no module under `metadata/`
  constructs an HTTP client except this one; the suite's no-network guard green with the module
  imported and exercised.
- **Note:** the second structural decision: both providers arrive *behind* an already-tested
  limiter and cache, so no later task can write an unthrottled loop against somebody's API.
- **Plan reference:** §5, §6.8

## T12 — `metadata/tmdb.py`

- [ ] **Changes:** identify under the exactly-one rule; fetch mapping to the spec §3.2 field
  vocabulary; bounded artwork download into the data directory, recorded as `remote`
  associations.
- **Depends on:** T10, T11
- **Verified by:** recorded response fixtures — one, zero and many surviving candidates produce
  match, unidentified and unidentified (AC-12); a subject already carrying a TMDB id makes **zero
  search requests**, held by the counting transport (AC-3); artwork respects the five-file /
  20 MB bounds and a re-refresh with tags already present downloads nothing; `enabled()` returns
  the reason when no key is configured.
- **Plan reference:** §6.5

## T13 — `metadata/musicbrainz.py`

- [ ] **Changes:** album-level identify and fetch; artist lookups; the mandatory identifying
  `User-Agent`; recording ids taken from tags only.
- **Depends on:** T10, T11
- **Verified by:** recorded response fixtures; the request budget asserted — refreshing an
  N-track album costs one release-group request plus one per new artist, **never one per track**;
  the 1-per-second bucket engaged; no artwork code path exists (the spec scopes MusicBrainz to
  names, dates and relationships).
- **Plan reference:** §6.6

## T14 — Remote refresh end-to-end: modes, failures, and the zero-network rescan

- [ ] **Changes:** `refresh.py` gains the remote steps behind mode, `enabled()` and
  fields-still-wanting checks; `refresh_pending` set on failure and retried by the next scan; the
  per-scan report names disabled providers once; **the opt-in live replay test** — one movie
  against TMDB, one album against MusicBrainz, `@pytest.mark.needs_reference`, skipped by
  default, never gating CI ([plan §8](plan.md#8-testing-strategy)) — the first user of the marker
  `tests/conftest.py` declared for exactly this.
- **Depends on:** T12, T13
- **Verified by:** AC-8 — every provider stubbed unreachable, a full scan completes, every item
  keeps its local metadata, pending is set and the next scan retries; AC-9 — no credentials, scan
  completes, the report names what sat out; AC-10 — a locked field survives `Replace` end-to-end;
  AC-12 at integration; **AC-13 — scan, refresh, rescan of the unchanged library: the counting
  transport shows zero requests**; **AC-1 re-held now that providers exist** — a fully-sidecared
  film refreshes with zero requests on the counting transport, which is the §6.8 gate doing its
  job rather than an accident of T10's empty world; AC-15 re-run with remote code present —
  downloads land under the data directory and the library hash has not moved.
- **Plan reference:** §6.8, §7, §8

## T15 — Cultures: measure, generate, serve

- [ ] **Changes:** measure the live reference's `GET /Localization/Cultures` first and record
  what the shape and the B/T code handling actually are, with provenance, correcting
  [plan §6.9](plan.md#69-cultures) if it guessed wrong; `tools/generate_cultures.py` (3.9 floor,
  stdlib), listed in [`tools/README.md`](../../tools/README.md)'s reference-material table like
  every other script there; `metadata/cultures.py` committed with its source and date in the
  header; `api/localization.py`; the route registered; `IMPLEMENTED_FEATURES` in
  `tests/conformance/test_routes.py` gains `"004"` — the line that file's own comment promises.
- **Depends on:** 002 complete; independent of T3–T14
- **Verified by:** a golden byte-compare of the response; the routes-against-surface tests green
  in both views with 004 in the set; the casing and unit sweeps pick up the new model; running
  the generator twice produces byte-identical output, and the tools CI job holds it to 3.9.
- **Plan reference:** §6.9; spec §3.8

## T16 — The acceptance map, and Implemented

- [ ] **Changes:** `FEATURE_004` in `tests/conformance/test_acceptance.py`, mapping **all
  sixteen** criteria of [spec §5](spec.md#5-acceptance-criteria) to named tests;
  `specs/README.md`'s table; `spec.md`, `plan.md` and this file to `Implemented` with dates;
  AGENTS.md's where-the-project-is paragraph.
- **Depends on:** everything above
- **Verified by:** `test_every_implemented_feature_has_a_map` passes **with** 004 marked
  `Implemented` — the check that would have failed 003 at its gate, kept doing its job; the full
  local gate (`ruff check`, `ruff format --check`, `mypy`, `pytest`) green; the definition of
  done below closed line by line.
- **Plan reference:** §8; 003 T21 is the precedent

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all sixteen —
      has a passing test, by name, in `FEATURE_004` (T16).
- [ ] `GET /Localization/Cultures` reaches **L2** with a reviewed golden, and no route exists
      outside `docs/compatibility/surface.yaml` (T15; the file already lists it, so the change is
      the registration, not the surface).
- [ ] The lock matrix holds twice: at engine level (T6) and end-to-end through `Replace` (T14).
- [ ] **No file inside any library root is created, modified or deleted** — the AC-15 tree hash,
      green with the remote code present and downloading (T10, re-held at T14).
- [ ] No test in the suite reaches the network (AC-16 — the standing guard in
      `tests/conftest.py`, which the counting transport complements rather than replaces).
- [ ] The three new runtime dependencies — mutagen, Pillow, httpx — are in `pyproject.toml` with
      plan §3's reasoning, each arriving in the task that first needs it, `uv.lock` moving in the
      same change.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md` **in the same
      change**, with `amended:` lines naming the task and the section.
- [ ] Any newly measured reference behaviour is in `docs/compatibility/behaviours.md` with
      provenance.
- [ ] Every open question in [`spec.md` §7](spec.md#7-open-questions) is either resolved with
      provenance or still open with a written reason — OQ-5 at T1; OQ-1, OQ-2 and OQ-4 stay open
      naming the differential harness or the fixture comparison that resolves them; and 003's
      OQ-8 is updated at T7 with what this feature made measurable.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

**005** needs `name_folded` written for every item this feature touches — it is the search and
`nameStartsWith` column, and a row that misses it is invisible to search rather than broken;
the pattern-driven indexes of plan §4 to exist before its queries do; `ImageTags` emittable from
`item_images` rows alone; and the artist **credit** distinction (`artist` versus `album_artist`)
recorded faithfully, because `/Artists` versus `/Artists/AlbumArtists` is that distinction and
nothing else.

**006** needs `item_images` rows to be complete — dimensions and tag always present (T8's
invariant), `source_kind` saying where the bytes live, and the tag stable for unchanged bytes —
because its whole cache story hangs off tags this feature computes.

**008** inherits the `replay_gain` decision T1 makes, whichever way it goes, and the
`refresh_pending` retry channel if probing ever needs to request a metadata revisit.

All of these are cheap here and expensive later.
