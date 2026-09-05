---
feature: 004-metadata-resolution
title: Metadata resolution — tasks
status: Implemented
created: 2026-08-27
updated: 2026-09-05
implemented: 2026-08-27
accepted: 2026-08-27
plan_status_required: Accepted
plan_status_actual: Implemented
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

- [x] **Changes:** `tests/fixtures/metadata/` — sidecar fixtures (full, sparse, id-bearing,
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
- **Done (2026-08-27):** 56 files, 20,718 bytes, in `tests/fixtures/metadata/` with a
  [README](../../tests/fixtures/metadata/README.md) carrying every generation command.
  Three things the task did not expect.
  **The entity fixture disproved [plan §6.2](plan.md#62-sidecars).** The plan said stdlib
  `ElementTree` "refuses DTDs and entity definitions outright, which turns the whole XXE class
  into the malformed-sidecar path". It does not. Measured: an internal entity **parses and
  expands**; an external one raises, so file disclosure is genuinely impossible but by *failing*
  rather than refusing; and five nested levels expand 400 bytes into 200,000 characters, which is
  a scan-memory hole the plan believed was already closed. One fixture became three, one per
  shape, and §6.2 now names the handler T5 has to install — expat with `StartDoctypeDeclHandler`
  raising — which was verified to work before being written down rather than after.
  **The artwork was generated wrong the first time and looked right.** Fourteen images came out
  320×240 — lavfi's default — because in zsh `$4:s=` is a substitution modifier on `$4`, so
  everything after `:s=` was eaten and `ffmpeg` never saw a size. Nothing failed; the files
  existed, opened, and were the wrong size. AGENTS.md's "verify that an edit landed" turns out to
  cover fixtures too.
  **Every byte was checked against the tools that will read it**, before being committed rather
  than at T5, T7 and T8: mutagen opens all four templates and round-trips multi-valued tags in
  each; Pillow identifies all 39 images at their intended dimensions and refuses exactly the one
  meant to be refused. Two toolchain facts are recorded in the README because they will bite
  whoever regenerates: this `ffmpeg` has no `libvorbis` (its own Vorbis encoder takes stereo
  only, so the Ogg template is the one stereo file) and no webp encoder (`cwebp` made that one).
  **And the task list did not mention that 003 forbids exactly this.**
  `test_the_generator_is_the_only_source_of_media` asserted that `tests/fixtures` holds nothing
  but `.py` files — 003's way of keeping "no fixture file is a copyrighted work" a property
  rather than a list, since a list of extensions passes for whichever extension nobody thought
  of. The first committed sidecar failed it. It is now scoped to `tests/fixtures/library`, where
  it is unchanged and still true, and 004's tree holds the same property from the other side:
  `inventory.py` declares every file by digest, `tests/metadata/test_fixture_tree.py` holds the
  tree to it **in both directions**, and two size caps read from disk mean that whatever anybody
  adds later is too small to be a recognisable piece of somebody's work even if they update the
  table in the same commit. Both directions were checked by breaking them — a stowaway `.jpg`
  and one appended byte each fail the suite.

## T3 — `metadata/model.py`

- [x] **Changes:** the field vocabulary, `FieldValues`, `RefreshMode`, the identify results —
  pure, no I/O.
- **Depends on:** nothing
- **Verified by:** the value-ness rules as a table — `None`, `""`, `[]` and whitespace-only are
  not values ([spec §3.1](spec.md#31-the-provider-model)), while the seam's
  present-and-empty tag distinction survives; an import-direction test (`metadata/model` imports
  nothing from `db/`, `api/`, `library/`); mypy strict.
- **Plan reference:** §3, §5
- **Done (2026-08-27):** the vocabulary turned out to be **two** vocabularies, and finding that
  out meant reading the reference's merge — which then contradicted the plan twice more.
  **`Field` is not what a lock names.** A lock is one of nine `MetadataField` values
  `[spec: MetadataField]`; a merge field is one of this feature's twenty-one. `LOCK_OF` is the
  map, partial in both directions: eight of the nine guard exactly one field each, and thirteen of
  the twenty-one cannot be locked at all. The trap is `Name`, which does **not** cover the sort
  name or the original title — the reference overwrites the original title on the line after the
  name lock, so grouping them would be kinder and a divergence.
  **AC-10 had no way to happen.** Spec §3.6 gives locks no HTTP route, and nothing in the feature
  read one from anywhere — so "a locked field survives a Replace refresh" was a criterion about a
  state no code could produce. The channel is the sidecar: `<lockdata>` and `<lockedfields>`,
  pipe-separated, matched case-insensitively, unknown tokens dropped rather than refused. Both are
  now in [plan §6.2](plan.md#62-sidecars)'s field map for T5 to parse.
  **Two more the same reading disproved**, both now in [plan §6.1](plan.md#61-the-merge) for T6:
  the reference **union-merges `Studios` and `Tags`** while whole-replacing `Genres` and `People`,
  so plan §10's blanket rejection of union-merge was right about half the list fields and wrong
  about the other half; and a `Runtime` **from metadata is discarded for audio and video items**,
  because a media file's runtime comes from probing it — so honouring `<runtime>` on a film would
  give Atrium's films a runtime the reference's do not have.
  The import-direction rule is written for the three modules plan §3 calls pure — `model.py`,
  `merge.py`, `byname.py` — and names the two that do not exist yet rather than iterating over a
  directory, so it starts guarding each on the day it lands. Checked by breaking it.

## T4 — Migration `0003_metadata_and_by_name`, the models, and the by-name identity rule

- [x] **Changes:** revision 0003 exactly as [plan §4](plan.md#4-data-model) lays it out: the
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
- **Done (2026-08-27):** the task's warning about the containment map was right, and it was not
  the expensive one. `domain/items.py` gained `BY_NAME` and `IN_THE_TREE`, and the four map
  assertions are scoped to the tree with the exemption argued once and stated positively in a
  test of its own — a by-name type has no chain **and** no collection type produces it. The
  tempting fix, mapping the five to `None` in `PARENT_OF`, passes and makes
  "every chain ends at the library" mean nothing.
  **Four things the task did not anticipate.**
  *The rebuild would have thrown away three constraints and two indexes, silently.* `items` has
  to be copied because SQLite cannot alter a check constraint in place, and SQLAlchemy's SQLite
  dialect **does not reflect check constraints** — so a batch operation that trusted reflection
  drops `ck_items_type` and 0002's two indexes, and every test in the suite still passes.
  `copy_from` carries the whole 0002 definition, indexes included.
  *Nothing compared the migrations against the models.* A column added to one and forgotten in
  the other passed the entire sweep. `test_the_migrations_and_the_models_describe_the_same_schema`
  builds both databases and compares columns, indexes, primary keys, foreign keys and check
  constraints; it covers every revision, not only this one, and it was checked by breaking it.
  *Adding five enum members broke a scan at import time.* `library/scan.py` built its depth map
  over `ItemType` and `PARENT_OF` is now total over the tree only — six test modules failed to
  collect. Scoped, with the `KeyError` left as the honest failure if a scan ever does produce one.
  *0002's "the check constraint lists exactly the types the domain has" had to be scoped, not
  widened.* Widening it to today's `ItemType` would have made it assert that a list equals
  itself, forever. A migration is a record of a point in time: 0002 compares against
  `IN_THE_TREE`, and the whole-vocabulary assertion moved to 0003 where the five arrive.
  **And the fold moved.** [Plan §6.7](plan.md#67-by-name-rows) put it in `metadata/byname.py`
  (T9), but the *identity* is derived from it, so `library/identity.py` owns it and T9 will call
  it. Two definitions of one fold is how a spelling merges into one row and derives another's id.
  Its order is the reference's and matters: trim, then strip trailing dots, and **no second
  trim** — so `Drama. . .` and `Drama. .` are two rows there and two here.

## T5 — `metadata/nfo.py`

- [x] **Changes:** sidecar discovery per the [spec §3.2](spec.md#32-nfo-sidecars) table; the
  parser on stdlib expat feeding an `ElementTree.TreeBuilder`, refusing document type
  declarations outright (plan §6.2); the field map including `sorttitle` routed through 003 §3.7.3's
  explicit-sort-title treatment; provider ids; the size cap.
- **Depends on:** T2, T3
- **Verified by:** the fixture sidecars parse to their expected `FieldValues`; the malformed and
  the three entity-bearing fixtures each produce a warning naming the file and nothing else
  (AC-4's parser half — but **not** because `ElementTree` refuses DTDs, which T2 measured it does
  not do: it expands internal entities, expands an entity bomb, and fails only on the external
  case. The refusal is a handler T5 installs, and there are three fixtures because the default
  parser treats the three shapes three different ways — [plan §6.2](plan.md#62-sidecars)); a
  single
  `<genre>` containing ` / ` **is split into two**, which is the opposite of what this line said
  before T5 read the parser both documents were citing; `runtime` minutes become ticks at
  ingestion and nowhere else.
- **Plan reference:** §6.2
- **Done (2026-08-27):** `metadata/nfo.py`, and every rule in it was measured rather than
  reasoned. Four of them contradict a document.
  **The genre split.** [Plan §6.2](plan.md#62-sidecars) said a single `<genre>` containing ` / `
  is *not* split, "the reference's parser does not, and inventing a splitter here is how two
  servers disagree about one file". Its parser splits on a bare `/`, trims each part and drops the
  empties. Not splitting would have given Atrium a genre called `Science Fiction / Fantasy` that
  no reference server has, on a file both of them read — the exact disagreement the sentence was
  written to prevent, produced by following it. The cost of the rule, a genre that legitimately
  contains a slash becoming two, is the reference's to own.
  **A `<year>` at or below 1850 is discarded**, which matters because `<year>0</year>` is what
  generators write for "unknown" — under a naive parse a film gets filed under the year zero.
  **A premiere date is parsed in exactly one format and *fills* the year rather than setting it**,
  so a sidecar with both keeps its `<year>` even when the two disagree. `date.fromisoformat`
  accepts four more formats than the reference does, so the shape is checked before parsing.
  **`<director>` and `<writer>` choose their separator from their content** — `|` or `;` if either
  appears, otherwise `,` — which is what keeps `Matthew, Jr.` one person in a list written with
  pipes, and splits them into two in a list written with commas.
  Two things the task did not list and the feature needed anyway: `<lockdata>` and
  `<lockedfields>` (T3 found that AC-10 had no other channel), and the `<id TMDB= IMDB=>` element
  Kodi wrote before `<uniqueid>` existed — whose text content is read as an IMDb id **only** when
  it starts with `tt`, because Kodi's own documentation says that content is arbitrary.
  The DOCTYPE refusal T2 specified works: all three entity fixtures — which the stdlib expands,
  raises on, and expands enormously — land on one warning, and the bomb is refused before
  anything is allocated.

## T6 — `metadata/merge.py`

- [x] **Changes:** the per-field precedence walk, the mode × locked × empty matrix, the
  per-field list rules — **four of them, not one**, which T3 measured and this task built. Pure.
- **Depends on:** T3
- **Verified by:** every cell of the [plan §6.1](plan.md#61-the-merge) matrix as a table test —
  AC-10 and AC-11 are held here first, at engine level, and again end-to-end at T14; the provider
  chains of [spec §3.1](spec.md#31-the-provider-model) asserted as data, music's inversion
  included; a provider that returns nothing for a field can never blank it.
- **Note:** this is the first structural decision landing: the thing that constrains overwriting
  exists, tested, before anything capable of overwriting does.
- **Plan reference:** §6.1
- **Done (2026-08-27):** the nine cells of the matrix are a table, AC-10 and AC-11 are held by
  name, and the three things T3 measured are what the module is actually shaped by.
  **"Lists whole from one provider" is one rule where the reference has four.** `Genres` is taken
  whole; `Studios` and `Tags` are **unioned** with what the item already has, case-insensitively,
  the item's own spelling surviving; `People` has existing entries **enriched** — a missing role
  filled in, nobody added, nobody removed, matched by name with diacritics stripped; and
  `ProviderIds` accumulates key by key, with a default refresh **not** replacing an id the item
  already carries. That last asymmetry is the right one and is the reference's: an id is the
  user's decision about what this thing is, and a default refresh that overwrote one would undo a
  correction without being asked.
  **`Local only` is not a third behaviour.** It is `Default` over a chain with the remote sources
  removed, which is why the matrix has three rows and the code has one branch.
  **A file-backed item ignores a runtime from metadata**, because its runtime comes from probing
  the file — `FILE_BACKED` turns out to be exactly the reference's `is not Audio && is not Video`.
  **And spec §3.1's table has an ambiguity**, now written down in [plan §6.1](plan.md#61-the-merge)
  rather than quietly resolved: the film column lists *Path-derived* twice, at positions 3 and 5.
  A repeated source in a first-value-wins walk is a no-op, so `CHAIN_OF` reproduces it literally
  and nothing behaves differently — but the two readings differ in one observable way, and it is
  worth settling: with `PATH` ahead of `REMOTE`, **a `Replace` refresh cannot take a film's name
  from TMDB**. T14 measures it.

## T7 — `metadata/tags.py`, and the seam goes live

- [x] **Changes:** mutagen enters `[project.dependencies]` with plan §3's reasoning; the
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
- **Done (2026-08-27):** the seam is live. A tagged FLAC under `Some Folder/Another Folder/` now
  becomes a track on `The Real Album` by `The Real Artist`, and the same tree scanned with
  `PATH_ONLY` still becomes `Another Folder` by `Some Folder` — which is what makes that a
  statement about the seam rather than about the fixture. 003's whole suite is green, and the
  gating constraint is asserted rather than assumed: a source handed to a second scan reports
  **zero** files opened, and `deep` reports one.
  **The default had to change, and it cost a layering deviation** — the first this feature has
  taken, recorded in [plan §2](plan.md#2-inherited-decisions). `scan()` now builds a `TagSource`
  when no source is given, which means `library/` imports `metadata/`, two packages architecture
  §1 draws side by side. Leaving the injection to a composition point was tried first: a scan
  whose reader has to be supplied resolves a well-tagged music library from its directory names
  the first time anybody forgets, and *albums named after folders* reads as a scanning bug rather
  than a missing argument.
  **`tags_for` and `values` are deliberately different shapes**, and it took writing both to see
  why. The seam maps a key to **one string** and keeps an empty one, because 003's contract says a
  present-and-empty tag is not an absent tag and the reference copies both; `values` keeps lists
  and drops empties, because there an empty string is not a value. A multi-valued artist therefore
  gives the seam its first value and the merge the whole list — AC-6 is unaffected, since what a
  client renders as three artists comes from `values`.
  **Four containers, one vocabulary, measured before it was written.** Vorbis comments, ID3
  frames, MP4 atoms and free-form `----` atoms were each read back with mutagen before the mapping
  existed, which is how the `trkn`/`disk` pair-of-integers shape and the `UFID` recording id got
  handled rather than discovered later. Three artists stay three in every container and
  `Earth, Wind & Fire; Live` stays one in every container.
  **T2's deferred assertion is closed**: all four templates carry no tags at all, checked with the
  reader rather than by searching the bytes for field names.

## T8 — `metadata/artwork.py`

- [x] **Changes:** Pillow enters the dependencies; the name tables of
  [spec §3.4](spec.md#34-local-artwork); ordering for numbered backdrops; dimensions and the
  content tag at association time; embedded cover art as `Primary` only when no file-based one
  exists.
- **Depends on:** T2, T7
- **Verified by:** every name in the tables resolves to the right image type and index on
  fixtures; a file Pillow cannot identify is skipped with a warning, and **no association row
  exists without dimensions and a tag**; the tag is unchanged across a rescan of an unchanged file
  and changes when the bytes do — 006 AC-2's ancestor, cheaper to hold now than to retrofit.
- **Plan reference:** §6.4
- **Done (2026-08-27):** the tables in [spec §3.4](spec.md#34-local-artwork) and
  [plan §6.4](plan.md#64-local-artwork) were a **subset of the reference's with two orderings
  reversed**, and both are corrected in this change.
  **Reversed:** `thumb` before `landscape` — the reference tries `landscape` first — and `disc`
  before `cdart` for a music album, where the reference prefers `cdart` because that is what
  every ripper writes.
  **Missing:** the Primary list is **five lists, not one** (an album and an artist try `folder`
  first and answer to `jacket` and `albumart`; a series to `show`; a film to `movie`; a person to
  neither); the per-item form is the **bare file name**, tried before every folder name, as well
  as the `<stem>-<name>` prefix, which applies to every name and not only `poster`; there is a
  fourth backdrop family (`art`) and an `extrafanart` folder taken whole; `clearart` is an `Art`
  image; and an episode, a track and a person get a Primary and **nothing else**.
  **And the numbered rule is not the one T2's fixture was built for.** Variants use a dash
  (`fanart-1`) except `backdrop`, which does not (`backdrop1`), and the scan **stops after three
  consecutive misses** rather than at the first gap — so a library that lost `fanart-3` keeps
  `fanart-4` onwards. The fixture holds `fanart3` and `fanart-10` expecting a
  lexicographic-versus-numeric trap; neither is found, and the fixture proves the real rule just
  as well, so it stays with its expectation corrected.
  **Readability is part of the first-match rule rather than a check after it.** One corrupt
  `poster.jpg` must not leave an item with no image while a good `folder.png` sits beside it, so
  a file Pillow cannot identify is skipped with a warning **and the next name wins** — asserted
  on the `unreadable/` fixture.

## T9 — The write path: `MetadataRepository` and the by-name rows

- [x] **Changes:** `metadata/byname.py` — **calling** T4's fold rather than defining a second one;
  `MetadataRepository` in `db/repositories.py` — `apply`,
  `ensure_by_name`, garbage collection; join-table writes preserving people's role and order and
  artists' credit kind.
- **Depends on:** T4, T6
- **Verified by:** AC-14 at repository level — two spellings, one row, first spelling displays;
  the fold's envelope (case folds, diacritics distinct, `Drama/Romance` meets `Drama Romance`);
  GC removes a row nothing references and a later reference recreates it **with the same id**;
  `apply` is transactional — a failure mid-apply leaves no half-written item.
- **Plan reference:** §5, §6.7
- **Done (2026-08-27):** AC-14 holds at repository level, the fold's envelope is a table, garbage
  collection recreates a row with the same identifier, and a deliberate failure mid-apply leaves
  the item exactly as it was. Three things the task did not anticipate, and the first is a gap in
  a *previous* feature that only became visible here.
  **A track's performers are frequently not anybody's album artist**, and the schema forbade
  saying so. `item_genres`, `item_studios` and `item_people` point at by-name rows a refresh
  creates on demand; `item_artists` points at a `MusicArtist`, which is a **tree item the scanner
  owns** ([behaviours §5.3](../../docs/compatibility/behaviours.md#53-an-artist-in-two-music-libraries-is-two-rows))
  and which the scanner creates one of, per *album artist*. So the first credit naming a guest
  performer failed a foreign key. Creating the missing item from the refresh would put a tree item
  outside the scan that builds the tree, and the next scan would mark it removed — a row that
  appears and disappears every other scan; dropping the credit loses the performer's name, which
  is what AC-6 exists to keep. **Revision 0004** makes that one link nullable, and §5.3 carries
  the whole argument: a client sees everyone who played and a shorter list of artists to browse.
  **The migration sweep could not see the change it made.** `schema_of` recorded column and index
  *names*, so a revision that only changes nullability "changed nothing" — and, worse, its
  reversibility could not be proved either. Nullability is now part of what the sweep compares.
  **A premiere date is a date-time, not a date.** `PremiereDate` is a date-time on the wire and
  the column is one, so `.nfo` and tag reading now convert at ingestion — architecture §4's rule
  for durations, applied to dates.
  **And the image write path was duck-typed and silently wrong.** It read `source_kind` off the
  presence of an attribute that `ArtworkFile` does not have, so every file-based poster was
  recorded as *embedded*. `metadata/artwork.associate` is now the one place a path becomes
  relative to something and the row gets a real type, `ImageAssociation`; the repository ignores
  anything else rather than guessing.
  The fold did **not** get a second definition here: `byname.py` calls `library/identity`'s, which
  cost the module its place in the pure-metadata import rule — the guarantee followed the code
  rather than evaporating, and `library/identity.py` is now held to the no-I/O half of it.

## T10 — Local refresh: orchestration without a network

- [x] **Changes:** `metadata/refresh.py`, local slice only — sidecar, tags, artwork, through the
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
- **Done (2026-08-27):** AC-15 lands and was checked by breaking it — a byte written into a
  library root fails the suite. AC-1, AC-2, AC-4, AC-5, AC-6, AC-7, AC-10, AC-11 and AC-14 hold
  at integration level. **Wiring the pieces together disproved more than any single piece had.**
  **Spec §3.1's duplicated *Path-derived* is settled: position 5.** T6 recorded the ambiguity;
  T10 measured it. The reference merges what an item already had **after** every provider has
  spoken, so a path-derived name is the last fallback rather than an early source — and AC-1 is
  unreachable the other way round, because a filename-derived name would be a value a default
  refresh must not overwrite. `items.name`, `index_number` and `parent_index_number` are read as
  the *path source*; the subject is what a **previous refresh** resolved.
  **The scan and the refresh were fighting over one column.** With both writing `items.name`,
  every rescan re-derived `The Matrix` from the filename and every refresh restored
  `The Matrix (1999)` from the sidecar — for ever, with every item reported as updated. The
  scanner now names an item when it **creates** it and 004 owns the name afterwards, which is the
  reference's own shape. Three of 003's tests moved to the layer that now owns the behaviour.
  **Three fields were rewritten on every refresh because nothing read them back**, and one of
  them had nowhere to be read back *from*: `<tag>` elements are in spec §3.2 and were in no
  column at all. Revision 0005 adds `tags` and `forced_sort_name` — the latter because a
  `sort_name` derived from a sort title cannot be compared against the title it came from.
  `item_images` is now read back too. A `Subject` gained `stored` beside `values`: *has the item
  got a value here* and *is this already what the row says* are two questions, and answering the
  second with the first makes a rescan rewrite the library.
  **A `PATH_ONLY` scan was reading tags anyway.** The refresh built a reader of its own, so an
  opt-out worked for half the scan. One `MemoisedSource` now answers both the resolver's question
  and the refresh's, for any `MetadataSource`, asked **once per file** — which also stopped a
  caller's own reader being consulted twice for every changed file.
  **And the library item was wearing its first film's poster**, because a `CollectionFolder` has
  no directory of its own and borrowed a descendant's. It is not refreshed: spec §3.2 and §3.4
  describe items *in* a library.
  One mistake worth recording because it cost real time: an edit script reused a variable and
  wrote a test file's contents over `refresh.py`. AGENTS.md's "verify that an edit landed" covers
  the file you did not mean to edit as well as the one you did.

## T11 — `metadata/remote.py`: the one HTTP door, sealed before anyone walks through it

- [x] **Changes:** httpx moves from the dev group to `[project.dependencies]`; per-provider token
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
- **Done (2026-08-27):** the bucket, the cache and the door are green with no provider in
  existence, and the import-direction test that says **no other module under `metadata/` may
  import an HTTP library** is what turns "no test reaches the network" from a discipline into a
  property: a provider that wanted its own client would have to change that test to get one.
  **One design flaw the tests found, and it was the one thing caching a 404 is for.** The cache
  returned a bare payload, so a stored `None` — which is how "this provider does not know that
  id" is remembered — was indistinguishable from a miss, and the request was made again every
  time. `get` returns a `CacheEntry`, and `CacheEntry` stopped being a class nothing used.
  **And T9's boundary guard was stated too broadly to survive this task.** It forbade any module
  under `metadata/` reaching `atrium.db`, which architecture §1 does not say: the rule is that
  `metadata/` must not write **the item table**. `remote.py` owns `provider_cache`, its own table
  whose rows promise nothing. The guard now names the two modules that may reach the database and
  why, and a second one says that **none** of them may import the item models — including the two
  that may, since holding `models.Item` is one edit away from writing an item row without the
  repository knowing.
  Two decisions worth naming: the bucket is consulted **after** the cache, so a hit costs no
  token and a retry of a partly-cached refresh is cheap rather than a second full budget; and a
  `429` **halves** the bucket for the rest of the scan rather than resetting it, because a bucket
  that recovers immediately asks to be told again.
  `providers` joins the configuration file — a TMDB key, a MusicBrainz contact, and the country
  whose certification becomes an official rating. Empty is the normal case, not an error.

## T12 — `metadata/tmdb.py`

- [x] **Changes:** identify under the exactly-one rule; fetch mapping to the spec §3.2 field
  vocabulary; bounded artwork download into the data directory, recorded as `remote`
  associations.
- **Depends on:** T10, T11
- **Verified by:** recorded response fixtures — one, zero and many surviving candidates produce
  match, unidentified and unidentified (AC-12); a subject already carrying a TMDB id makes **zero
  search requests**, held by the counting transport (AC-3); artwork respects the five-file /
  20 MB bounds and a re-refresh with tags already present downloads nothing; `enabled()` returns
  the reason when no key is configured.
- **Plan reference:** §6.5
- **Done (2026-08-27):** AC-3 holds as **zero requests of any kind**, not merely no search — a
  carried id has nothing to ask about, so nothing is asked. AC-12 holds in all three shapes.
  **The recorded fixtures are synthetic and say so.** This repository has no TMDB key and its
  suite reaches no network, so they were written to TMDB's documented shape rather than captured.
  They pin the **parser**; they do not pin the **API**, and [plan §8](plan.md#8-testing-strategy)'s
  opt-in live test at T14 is the thing that can see drift. Recorded in a README beside them rather
  than left as an impression the word "recorded" would give.
  Two rules the task did not name and the payloads forced: **only the crew jobs the vocabulary
  has a kind for** are kept — TMDB's crew runs to hundreds of entries and an item carrying every
  gaffer is one no client renders usefully — and **the official rating is the configured
  country's and no other**, skipping an empty certification listed before the real one, because a
  film carries a rating in forty territories and they do not mean the same thing.
  Image bytes go **through the bucket and past the JSON cache**: `provider_cache` is a JSON column
  and a poster is two megabytes of it. Re-downloading is prevented by the content tag instead,
  which is the bound that keeps the data directory from growing on every scan.
  `DataPaths` gained `metadata/artwork`, which broke two tests that knew the layout — one listing
  the root's directories, one deleting them one level deep. Both are updated; the second now
  deletes trees, since the layout has a nested directory for the first time.

## T13 — `metadata/musicbrainz.py`

- [x] **Changes:** album-level identify and fetch; artist lookups; the mandatory identifying
  `User-Agent`; recording ids taken from tags only.
- **Depends on:** T10, T11
- **Verified by:** recorded response fixtures; the request budget asserted — refreshing an
  N-track album costs one release-group request plus one per new artist, **never one per track**;
  the 1-per-second bucket engaged; no artwork code path exists (the spec scopes MusicBrainz to
  names, dates and relationships).
- **Plan reference:** §6.6
- **Done (2026-08-27):** the budget is asserted as a **list of the three paths asked for**, not a
  total: an album of fourteen tracks costs one search, one release-group fetch and one artist
  lookup, and the fourteen tracks contribute nothing. A count that did not separate "few" from
  "not one per track" could not say the thing that matters — at one request per second the
  difference is a first scan taking minutes or ninety.
  Two things the payloads forced. **Artist credits are parts with join phrases between them** —
  `Artist A`, `" & "`, `Artist B` — and keeping the phrases would put ` & ` in a list of artists.
  And a **first release date is as precise as MusicBrainz knows**: `1998`, `1998-05` or
  `1998-05-04`, so only the full form becomes a date while the others still supply the year.
  "No artwork" is asserted on the source rather than promised: the module contains no reference to
  a download, an image kind or an association. *We do not call it* is a promise; *there is nothing
  to call* is a property.
  The fixtures are synthetic, like T12's, and their README says so.

## T14 — Remote refresh end-to-end: modes, failures, and the zero-network rescan

- [x] **Changes:** `refresh.py` gains the remote steps behind mode, `enabled()` and
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
- **Done (2026-08-27):** the six criteria hold, and **AC-1 is the interesting one** — the gate was
  right that T10's zero was vacuous, and writing the clause exposed two ways to get it wrong that
  both look correct.
  **"Wanting" has to be per type.** Written the obvious way, a film wanted an `ALBUM_ARTISTS` it
  can never have, so *every* film asked TMDB and AC-1 failed against a test that had passed in
  T10's empty world. A file-backed item's `RUNTIME` is the same shape of mistake: the merge
  discards it because a runtime comes from probing the file, so wanting it is wanting something
  that could never be applied.
  **And the chain order was still wrong.** Inserting the remote source "before the last local
  one" left the *second* `PATH` — the film chain lists it twice — ahead of the provider, so a
  sidecar carrying nothing but an id kept its filename as a name while TMDB's title sat unused
  behind it. Locals, then remote, then every path source.
  **A name collision worth a rename rather than an alias**: `merge.Subject` (what an item already
  has) met `model.Subject` (what a provider is *told*) in this module. The first is now
  `merge.Current`.
  The opt-in live test [plan §8](plan.md#8-testing-strategy) promised is here — one film against
  TMDB, one album against MusicBrainz, asserting the **shape** rather than the values, skipped
  unless credentials are in the environment. It is the first user of the `needs_reference` marker,
  whose docstring in `tests/conftest.py` said *"Nothing does yet."*

## T15 — Cultures: measure, generate, serve

- [x] **Changes:** measure the live reference's `GET /Localization/Cultures` first and record
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
- **Done (2026-08-27):** the task said measure first, and measuring first was the whole task.
  **[Plan §6.9](plan.md#69-cultures) named the wrong source.** The Library of Congress ISO 639-2
  registry has 508 rows; the reference returns **192**, under three rules — only languages with a
  two-letter code, terminological code first (the registry's file lists them the other way round,
  so 24 languages would have come out backwards), and **eight rows the registry does not contain
  at all**. The last settles it: no filtering produces `pt-br`, so a generator reading the
  registry ships a list missing rows a client can ask for. The source is the reference, read
  through its own API like every probe here — and the generator *is* a probe, reporting what it
  measured and exiting non-zero if the shape changes. (The registry was tried first; `loc.gov`
  answers a scripted request with a bot challenge, which is a second reason rather than the one.)
  **The byte-compare found a divergence that is not this endpoint's.** Atrium's response parses
  identically to the reference's and is sixteen bytes shorter: the reference escapes non-ASCII as
  `\u00E7` and Atrium sends `ç`. Same JSON string, every parser agrees — and matching it means
  re-encoding every body and upper-casing each escape's hex, a substitution that is unsafe on a
  string containing a literal backslash. Recorded as a deliberate exception with that argument in
  [behaviours §4.4](../../docs/compatibility/behaviours.md#44-non-ascii-characters-are-sent-as-themselves-not-as-uxxxx--withdrawn-2026-08-28),
  and it belongs to `compat/responses.py` for every endpoint at once if 010 ever finds a client
  that reads raw bytes. **This is the first response in the project to contain a non-ASCII
  character at all**, which is why nothing had noticed.

## T16 — The acceptance map, and Implemented

- [x] **Changes:** `FEATURE_004` in `tests/conformance/test_acceptance.py`, mapping **all
  sixteen** criteria of [spec §5](spec.md#5-acceptance-criteria) to named tests;
  `specs/README.md`'s table; `spec.md`, `plan.md` and this file to `Implemented` with dates;
  AGENTS.md's where-the-project-is paragraph.
- **Depends on:** everything above
- **Verified by:** `test_every_implemented_feature_has_a_map` passes **with** 004 marked
  `Implemented` — the check that would have failed 003 at its gate, kept doing its job; the full
  local gate (`ruff check`, `ruff format --check`, `mypy`, `pytest`) green; the definition of
  done below closed line by line.
- **Plan reference:** §8; 003 T21 is the precedent
- **Done (2026-08-27):** the map names sixteen criteria and **nine of them twice** — once where
  the rule is proved and once where it is proved to be the rule a scan uses. That is not
  belt-and-braces: 004's own task list says so out loud for AC-1, whose engine-level zero was
  vacuous until a provider existed that could have answered.
  The definition of done is closed line by line above. Two things in it were not true when the
  list was written and are recorded rather than quietly satisfied: the feature needed **two more
  schema revisions** after T4, and the golden for `/Localization/Cultures` is parse-identical to
  the reference's rather than byte-identical — a divergence argued in
  [behaviours §4.4](../../docs/compatibility/behaviours.md#44-non-ascii-characters-are-sent-as-themselves-not-as-uxxxx--withdrawn-2026-08-28)
  rather than hidden by a comparison that would not have seen it.

### Amended — 2026-09-05: the third refresh mode had tests and no criterion

**The map T16 wrote can only name a behaviour §5 names first**, and §3.6's table has three rows
where §5 had two: AC-10 is Replace's lock half, AC-11 is Default, and **`Local only` had nothing**.
Four dedicated tests — two in `tests/metadata/test_merge.py`, one in `test_local_refresh.py` and
one in `test_remote_refresh.py`, plus three rows of `THE_MATRIX` — asserted a mode no criterion
mentioned, so every one of them could have been weakened or renamed without a criterion failing.
Found as M3 of the [2026-09-04 audit](../../docs/audits/2026-09-04.md), one of a class of ten
across six features.

**It needed §3 before it could have §5**, the M4 shape one feature along. The table row says
*"Sidecars, tags and local artwork; no network"* — which sources, and nothing about the rule that
runs over them — and the rule itself has lived since T6 in `_apply`'s own docstring in
`metadata/merge.py`: *"`Local only` is `Default` over a shorter chain, not a fourth behaviour: the
remote sources are already gone by the time this runs."* A docstring is not somewhere §5 can
reach. §3.6 now carries that sentence as a paragraph, with the half the code makes true one layer
up — the refresh reports the provider it did not consult, `local-only refresh` as the reason, in
the list a missing credential fills — and **AC-20** is that paragraph.

**Every mapped test was read against the criterion first**, and one of them is named twice on
purpose: `test_the_matrix` is AC-11's whole nine-cell matrix and is also the only test that asserts
a **lock** under `Local only`, which is the clause that makes the mode Default's rule rather than
its own. The discriminating test is the merge one that offers a local source *and* a remote source
in the same call: it is what separates dropping the remote sources from behaving differently with
them. One clause is narrower than it reads and is named here rather than relied on: the report test
configures **one** provider, so *"names the provider it did not consult"* is asserted for one, and
the per-provider width belongs to `_usable` rather than to a test.

**Nothing under `src/` was touched.** §5 now numbers twenty criteria and `FEATURE_004` names tests
for all of them.

---

## Definition of done

Closed line by line at T16, on 2026-08-27.

- [x] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all twenty —
      has a passing test, by name, in `FEATURE_004` (T16). *(Count corrected on 2026-09-05 by the 2026-09-04 audit's C9, which found it stale in 10 of the 12 features: this is a live claim about §5, not a record of the tick — 007 T13's precedent, and it is held by a test now.)* **Nine are named twice**, once at
      engine level and once end to end, because a correct rule and a rule the caller actually
      uses are two claims.
- [x] `GET /Localization/Cultures` reaches **L2** with a reviewed golden, and no route exists
      outside `docs/compatibility/surface.yaml` (T15). The golden is the whole 192-row list, and
      it is parse-identical to the live reference's — the sixteen bytes it differs by are
      [behaviours §4.4](../../docs/compatibility/behaviours.md#44-non-ascii-characters-are-sent-as-themselves-not-as-uxxxx--withdrawn-2026-08-28).
- [x] The lock matrix holds twice: at engine level (T6) and end-to-end through `Replace` (T14),
      the second time against a provider that would have overwritten the field.
- [x] **No file inside any library root is created, modified or deleted** — the AC-15 tree hash,
      green with the remote code present and downloading (T10, re-held at T14), and **checked by
      breaking it**: a byte written into a library root fails the suite.
- [x] No test in the suite reaches the network (AC-16). The standing guard is complemented by an
      import-direction test that no module under `metadata/` may construct an HTTP client except
      `remote.py`, which is what makes it a property rather than a discipline.
- [x] The three new runtime dependencies — mutagen (T7), Pillow (T8), httpx (T11) — are in
      `pyproject.toml` with plan §3's reasoning inline, each arriving in the task that first
      needs it, `uv.lock` moving in the same change.
- [x] Anything learned is back in `spec.md` or `plan.md` in the same change. The `amended:` lines
      name **eleven** tasks between them.
- [x] Newly measured reference behaviour is in
      [`behaviours.md`](../../docs/compatibility/behaviours.md) with provenance: §4.4 (non-ASCII
      escaping), §5.4 (no loudness scan) and a second consequence added to §5.3 (a performer who
      is nobody's album artist has a name and no artist item).
- [x] Every open question in [`spec.md` §7](spec.md#7-open-questions) is resolved with provenance
      or open with a written reason — OQ-5 resolved at T1, OQ-4 given partial evidence and left
      open on 010, OQ-1 and OQ-2 unchanged and still 010's, and 003's OQ-8 updated at T7 with
      which half moved.
- [x] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

**Two schema revisions were added after T4 wrote the schema**, which is worth recording because
neither was foreseeable from the plan: 0004 made `item_artists.artist_item_id` nullable (T9 —
a track's performers are frequently not anybody's album artist), and 0005 added `items.tags` and
`items.forced_sort_name` (T10 — a column the write path stores and never reads back is rewritten
on every refresh, for ever).

## What 010 T10 left this feature, and what answering it found

010 T10 fixed the **ordering** half of a container's borrowed directory on 2026-09-02 — the
descendant is chosen in relative-path order rather than in identifier order, because an identifier
is a hash of the absolute path and the choice therefore moved with the mount point — and recorded
the rest as 004's: *"it does not make the borrowing correct - a two-disc album still borrows a disc
directory"*. Answered on 2026-09-03, and the answer is three findings rather than one.

**The proposed rule was wrong, and worse than what it would have replaced.** The handover named the
common ancestor of a container's file-backed descendants as the likely fix. It does answer the
two-disc album, and it was measured over the fixture tree against the recorded reference reading:
**12 of 17 containers against the standing rule's 15, and this rule's 17**. A series with one season
borrows that season's directory under it, an artist with one album borrows that album's, and a
season whose episodes are split between its own directory and the series folder borrows the series
folder — because a container whose files all sit in one subdirectory has that subdirectory as its
common ancestor, which is the ordinary shape and not an edge. It is
`test_a_season_missing_one_episode_keeps_its_own_directory` that rejects it.

**What the reference actually does is count down from the root, not up from a file.** Of the 26
container rows it makes of this repository's fixture tree, the 18 that carry a directory and a kind
this item tree also has sit at exactly their own kind's depth below the library root — 18 of 18,
disc directories included `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`.
So a container is given the directory `_depth(its type)` components below the root, and an extra
directory the item tree has no level for stops moving anything. Recorded in
[behaviours §2.27](../../docs/compatibility/behaviours.md#227-a-containers-directory-is-its-own-depth-below-the-library-root),
stated in [spec §3.2](spec.md#32-nfo-sidecars) and asserted by **AC-19**, which is new.

**The defect was two containers wide, not one, and a third shape read outside the library.** The
album borrowing `Artist/Album/CD1` was the reported half; the artist above it was borrowing
`Artist/Album` — a level that is not theirs at all — so `artist.nfo` and an artist's own artwork
were unreachable for *every* artist with a disc-split album anywhere beneath them. And
`Artist/01.flac`, a track directly in an artist's directory, which 003's `parse_audio` resolves as
an artist with no album, gave that artist the **parent of the library root**: measured, a refresh
took an artist's name from an `artist.nfo` outside the library it was scanning.
`metadata/artwork.py`'s `associate` already refused a file outside the root and warned, so the
poster beside that sidecar was declined; `find_sidecar` had no such guard, and that asymmetry is
why the escape was invisible.

**Nothing on the wire moved, and that is what made it invisible.** The fixture tree has no
`album.nfo` beside its two-disc album and no `artist.nfo` at all, so the reference-reading
comparison saw the same names before and after and the recorded reading did not need re-running.
The two container rows that comparison declares are the *other* album's — `First Album (2001)`
against `album`, the sidecar the reference does not read — and they are unchanged. **AC-19 has no
engine-level half** for the same reason the defect survived four features: `nfo.py` and
`artwork.py` are handed a directory and never choose one, so the choice is only observable in a
scan.

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
