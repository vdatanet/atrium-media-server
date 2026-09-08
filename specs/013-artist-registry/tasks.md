---
feature: 013-artist-registry
title: Artist registry — tasks
status: Draft
created: 2026-09-07
updated: 2026-09-07
plan_status_required: Accepted
---

# 013 — Tasks

Ordered. Each task is a reviewable change on its own, and states how you know it worked.

## What the gate changed

**Three things, and the first is a test somebody wrote to fail on exactly this change.**

### 1. `005 AC-13` is a tripwire for this feature, and it has already fired in prose

`tests/unit/test_by_name_routes.py::test_ac13_the_two_artist_routes_coincide_for_the_recorded_reason`
ends with:

```python
assert album == every, "if these ever differ, behaviours 5.3's argument needs rereading"
```

That is 005 AC-13 — *"the album-credit set is a subset of the any-credit set, the two coincide as
row sets for exactly §5.3's reason"* — and **013 is the change that makes it false**, in both
clauses:

- the two stop coinciding, because a performer who is nobody's album artist gains a row;
- and the subset relation goes with it, because [the plan gate measured](plan.md) the reference's
  two routes to be two populations, neither containing the other.

So 013 owes 005 an amendment to AC-13, and it is **T8**'s, not a line in a diff. The criterion was
written honestly about the world it had — *"the strict containment the criterion first imagined has
no row to show it"* — and this feature builds the row.

### 2. The reading [plan §9](plan.md#9-risks) owed was taken, and the plan's decision survives it

The plan takes the correct branch of behaviours §3.0.2 because the reference's `ChildCount` rule is
**unattributed**, and §9 recorded that one more reading was owed before that could be written down
as a divergence. Taken 2026-09-07, on three registry artists and four candidate counts each
`[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]`:

| artist | `ChildCount` | performed | albums as album artist | tracks as album artist | distinct albums of its tracks |
|---|---|---|---|---|---|
| `2 In A Room` | **2** | 1 | 0 | 0 | 1 |
| `5th Dimension, The` | **2** | 1 | 1 | 1 | 1 |
| `49ers` | **2** | 1 | 0 | 0 | 1 |

**All three answer `2` while their contents differ, and no candidate is `2` on all three** — nor is
any sum of them. It is not a constant either: the eleven album-artist rows read in the same run
carry `1`, `2` and `13`. So the number is stable per artist, varies between artists, and matches
nothing this reading could name.

That is the strongest form the plan's argument can take: **replicate is unavailable because the
rule is unknown after somebody tried to find it**, rather than because nobody looked. Decision 2
stands, and the behaviours row T8 writes says so with this table under it.

### 3. The fixture has no performer who is nobody's album artist — **and this was wrong**

*As written at this gate:* AC-1's discriminating case is exactly that item, and the query world has
not got one, because `guest_track` is performed by `ALBUM_ARTIST`, who is an album artist elsewhere.

**It has had one all along.** `SOLO_PERFORMER` is declared in `tests/fixtures/query.py` with a
comment saying precisely why it is there — *"`SOLO_PERFORMER` is nobody's album artist, so its
credit row carries a name and a null `artist_item_id`"* — and T2 used it. The gate read one seeded
shape and generalised from it.

**What was actually missing is the mirror**, and T6 found it by trying to write AC-4's second
half: an album artist **no track performs**. Without one, `/Artists/AlbumArtists` is a subset of
`/Artists` in this world, every assertion about the two listings passes, and the thing 013 measured
on the reference — two populations, *neither containing the other* — has no row to show it. T6
seeds a record fronted by a name whose track is credited to a session player, which is the shape
eleven of the reference's 506 album artists have.

**And the second music library was missing too**, which AC-2 needs and nothing had noticed: with
one music library, *"an artist credited in two of them is one row"* passes on a world that could
not have made it two. T6 seeds a second, sharing `SHARED_ARTIST` with the first, so the tree
carries two artists of that name under two identifiers — behaviours §5.3's first consequence,
which 013 does **not** change and the reference carries too — while the registry carries one.

---

## T1 — Revision `0009`: a `MusicArtist` may have no library

- [x] **Changes:** `src/atrium/db/migrations/versions/0009_artist_registry.py` and
      `src/atrium/db/models.py` — the biconditional `ck_items_by_name_has_no_library` becomes the
      two implications it stood for, with the artist type exempted **by name** and no other
      exemption. `src/atrium/library/identity.py` gains `ALSO_BY_NAME`, which is how `for_by_name`
      accepts the artist type while `RULE_OF` stays total and one-valued.
- **Depends on:** —
- **Verified by:** `pytest tests/unit/test_migrations.py tests/unit/test_db_schema.py` — an artist
  inserts **with** a library and **without** one, while a genre with a library and a film without
  one both still fail, each on the half that now says so by itself; the rollback deletes what the
  restored biconditional would refuse; and the shipped head is `0009`.
- **Spec reference:** §3.4 of `spec.md`, §4 of `plan.md`

### What T1 was, and why it is smaller

**As listed, T1 could not be merged green, and the list's own first line is what says so** — *each
task is a reviewable change on its own*. Built as written — the constraint, the column to
`NOT NULL`, the backfill and therefore the writer — it left **33 failures**: twenty
`NOT NULL constraint failed` from the writer still returning `None` for a performer the scanner
made no tree artist for, and thirteen more from the world the change moves, six of them the
`artistIds` and `albumArtistIds` filters, which resolve **tree** identifiers today and would have
had to resolve registry ones.

So T1 is the **capacity** and T2 is the **population**, which are two reversible ideas rather than
one: a schema that *allows* a row and a database that *has* one. Nothing observable changes here,
which is why it merges on its own.

**Three things were found on the way, and two of them nearly shipped silently.**

1. **The `copy_from` was five columns short.** The revision rebuilds `items`, and the first draft
   of that table was written from memory - a rebuild that would have dropped `end_index_number`,
   `sort_name`'s default and three more without a word. `tests/unit/test_migrations.py` caught it
   and **not on this revision**: it failed replaying `0008`, whose own `copy_from` then found a
   column the database no longer had. The list is copied from `0008` by script now.
2. **The migration sweep had a third blind spot and one word for two of them.** It reads the
   schema, so a revision that rewrites rows declares itself a `data migration`; SQLAlchemy's
   SQLite dialect does not reflect **check constraints** either - the fact every `copy_from` here
   exists for - so a constraint-only revision is invisible for a different reason. Calling `0009`
   a data migration would have been the shorter fix and a false one. `CONSTRAINT_ONLY` is the
   second word, and *"changed nothing"* stays a failure everywhere else.
3. **The backfill has to repoint every link, not only the null ones**, which is in neither the plan
   nor this list. The column will name the *registry* row, and a link pointing at a tree artist
   points at the right artist and the wrong population; leaving those would make `/Artists` list a
   mixture of the two. It is written down here because T2 is where it lands.

## T2 — The population: the rows, the links, and the column that stops being nullable

- [ ] **Changes:** revision `0010` — every distinct credit name gets a registry row, **every**
      link is repointed at it, and `item_artists.artist_item_id` becomes `NOT NULL`.
      `src/atrium/db/repositories.py` — the credit writer calls `ensure_by_name`, and
      `_artist_item` goes. `src/atrium/metadata/byname.py` — `BY_NAME_FIELD`'s comment citing §5.3
      as the reason `ARTISTS` and `ALBUM_ARTISTS` are absent from it is replaced by the reading
      that closed §5.3; **whether the two fields belong in that map is T2's to decide**, because
      the credit writer has a path of its own and adding them would create each row twice over.
      One index on `item_artists (credit, artist_item_id)`, which is what the two populations
      group by.
- **Depends on:** T1
- **It brings the rest of the world with it, and T1 measured how much.** Thirteen tests assert the
  world this task changes: two fixture assertions about §5.3's shape, two about a performer with
  no item, six on the `artistIds`/`albumArtistIds` filters — which resolve tree identifiers today
  and registry ones after — and the three artist-route ones including AC-13's tripwire. They are
  **not** collateral to be edited quietly: each is a statement about the gap, and each moves with
  a reason written where it moves.
- **Verified by:** `pytest tests/unit/test_migrations.py tests/unit/test_by_name_items.py
  tests/library/` — the three migration tests T1 wrote and moved here: the backfill gives every
  credit a row **and repoints the one that had one**, it derives the same identifier `for_by_name`
  does, and a scan of the query world reproduces exactly what the backfill made. And **the tree
  artists are untouched**: every identifier 003 derived is still there, which is AC-7's first half.
- **Spec reference:** §3.1, §3.4, AC-3, AC-7

## T3 — The collector, scoped so it can never take a tree artist

- [x] **Changes:** `src/atrium/db/repositories.py` — `collect_by_name_garbage` gains the credit
      table as a referencing column and is scoped to rows with `library_id IS NULL`.
- **Depends on:** T2
- **Verified by:** `pytest tests/metadata/test_write_path.py` — a collection over a world holding a
  tree artist nothing references **deletes nothing**, and the same collection after a credit is
  removed takes the registry row.

  **Both assertions were written first and the second failed first**, which is not what this task
  expected: a `MusicArtist` was in no collectable set at all, so a registry row outlived every
  credit that made it. The tree-artist assertion passed on the day it was written, so it was
  **proved to be able to fail**: the scoping was taken out, it failed with *"the collector took a
  tree item 003 owns"*, and it was put back. An assertion that has never failed is decoration, and
  this one had to be shown not to be.
- **Spec reference:** §3.5, AC-8

## T4 — Visibility: per population, not per type

- [ ] **Changes:** `src/atrium/db/item_queries.py` — the by-name clause of `_visible_to` and
      `_referenced` stops keying on the type alone. A registry artist is visible when a **visible**
      item credits it; a tree artist stays visible by its library.
- **Depends on:** T2
- **Verified by:** `pytest tests/unit/test_item_queries.py -k visib` — the adversarial test first,
  in the shape 009's playlist leak was found by: a restricted account narrowed to one library must
  not reach a registry artist credited only by items of another. Written and asserted to **fail**
  before the clause moves.
- **Spec reference:** §3.1; `plan.md` §9's first risk

## T5 — What each of the two routes lists

- [ ] **Changes:** `src/atrium/db/item_queries.py` — `run_by_name` for the artist type lists the
      registry: `/Artists` over `PERFORMER_CREDIT`, `/Artists/AlbumArtists` over
      `ALBUM_ARTIST_CREDIT`. Neither filters the other.
- **Depends on:** T4
- **Verified by:** `pytest tests/unit/test_by_name_routes.py` — and this is where 005 AC-13's
  tripwire fires. Both directions asserted: a performer with no album has a row in one listing and
  not the other, and an album artist no track performs has the mirror.
- **Spec reference:** §3.2, AC-1, AC-4

## T6 — The fixture gains the two shapes it cannot currently fail on

- [x] **Changes:** `tests/fixtures/query.py` — a performer who is **nobody's** album artist, and a
      **second music library** sharing one artist name with the first. `GENERATOR_VERSION` moves
      with it if the media world is touched.
- **Depends on:** —
- **Verified by:** `pytest tests/` — the world builds, and the two new handles are asserted to be
  what they claim: the performer appears in no album-artist credit anywhere, and the shared name
  resolves to **two tree artists and one registry row**.
- **Spec reference:** AC-1, AC-2

## T7 — The body, and the goldens

- [x] **Changes:** `tests/golden/` — the registry artist's list row and full body, regenerated and
      **read**. `ChildCount` is `0` on it, which the aggregate machinery answers without being
      asked; `ParentId` is absent.
- **Depends on:** T5, T6
- **Verified by:** `pytest tests/conformance/test_golden_items.py` and `git diff tests/golden` read
  in review. Every golden that moves is a listing whose population changed; one that moves for
  another reason is a defect this plan did not foresee.
- **Spec reference:** §3.1, AC-5, AC-6

## T8 — What this feature owes three other documents

- [x] **Changes:**
      - `docs/compatibility/behaviours.md` §5.3 — the gap **closes**, with the date, what closed it
        and what did not: the tree artist is still per library, on both servers.
      - `docs/compatibility/behaviours.md` — a **new** row for the `ChildCount` divergence, with
        the table above under it: stable, unattributed, and answered `0` here on §3.0.2's correct
        branch.
      - `specs/005-item-query-api/spec.md` — **AC-13 amended**. Its two clauses are false after
        T5, and it was written honestly about a world with no row to show the difference.
        `tests/conformance/test_acceptance.py`'s `FEATURE_005` entry moves with it.
- **Depends on:** T5
- **Verified by:** `pytest tests/conformance/test_acceptance.py tests/unit/test_allowlist.py` — and
  the amendment is dated and argued in place, never a silent edit.
- **Spec reference:** §1; `plan.md` §1 decision 2

## T9 — Close it

- [x] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_013`, which maps all
      **eight** criteria to tests by name — **done**. The three 013 documents to `Implemented`,
      `specs/README.md`'s row and the definition of done's counts — **not done, and deliberately
      not**: one line of that definition is unticked.

  **What is open is the differential run, and it is open because of a decision rather than an
  oversight.** Both artist routes were raised from `L2` to `L3` on 2026-09-07, so this is the
  first closing task in this repository that **cannot tick its conformance line from the fixture
  alone** — every feature before it deferred the differential half to 010, and
  [010's own list](../010-conformance-harness/tasks.md) still records that *no `level: L3` row has
  been shown to reach L3*.

  Marking the documents `Implemented` with that line unticked was tried and undone in the same
  change. A status word that means *"the tasks are done"* while a criterion of the same document
  says otherwise is precisely what 010 T15 found in three features and what
  `test_the_definition_of_done_counts_the_criteria_that_exist` exists to stop.

  **What the run costs, so whoever takes it is not surprised.** A reference instance over the
  fixture (`--fixture`, one container of the pinned digest, which dies with `SIGILL` on roughly
  half of its starts on arm64) **and an Atrium under test built by hand** — `tools/README.md`'s
  four steps: the fixture's libraries by the same names, an administrator, a restricted seat
  handed in under `ATRIUM_RESTRICTED_*` narrowed to the library `movies_library` picks, and the
  policy and configuration seeded from the reference's own documents. Then
  `tools/differential.py --fixture`, and the two artist routes read in its report.

  **The run was taken on 2026-09-07 and the conformance line is ticked.** It cost what this
  paragraph said it would: the `--fixture` run's own instance died with `SIGILL` and **refused to
  fall back** on another server, which is the protection 012 T10 bought; an instance stood up by
  hand makes **one** library where the fixture declares six, so `movies_library` found no movies
  library with anything in it and the run refused a seat narrowed to nothing; and the six have to
  be passed to `reference_instance.py --library` from the same declaration the fixture uses.

  **What it found on the two routes is twelve differences and not one of them is a population.**
  No `LENGTH`, no `ORDER`, no row that one server has and the other has not: `/Artists` and
  `/Artists/AlbumArtists` answer the reference's own rows. Two fields differ, four findings each:

  | class | pointer | here | there |
  |---|---|---|---|
  | `MISSING_KEY` | `/Items/0/IsFolder` | absent | `true` |
  | `EXTRA_KEY` | `/Items/*/UserData/UnplayedItemCount` | `0` | absent |

  Both are **new and belong to 013**, and neither is the gap this feature closed:

  * **`IsFolder` was measured on 2026-09-08 and both readings were right**
    `[probe: tools/probe_by_name_row_shape.py, Jellyfin 10.11.11, 2026-09-08]`. It is on an
    `/Artists` row **exactly when that row is also an item of the library tree**: 165 of 684 rows
    carry it, all 165 are tree items, and every tree-backed row has it — a perfect correlation in
    both directions. So it is neither the route's rule (005's `OMITTED`) nor the by-name row's
    (005 §3.2's sentence), and the two disagreeing readings are **one rule seen on two
    libraries**: this one's artists are mostly registry-only, and over the fixture every artist
    has a directory.

    **Atrium cannot reproduce it, and not because of anything 013 chose.** On the reference one
    artist is one *item* that may appear in both listings under one identifier, which is what
    makes *"this row is also a tree item"* a question about a row at all. Here the two populations
    are two rows with two identifiers by construction — [behaviours §5.3](../../docs/compatibility/behaviours.md)'s
    first consequence, the half 013 does **not** close — so an `/Artists` row is never a tree item.
    It is recorded there, against the consequence that owns it, rather than as a defect of these
    routes.
  * **`UnplayedItemCount` was 013's own defect and is fixed in this change.** A container's
    `UserData` is a statement about its subtree here, and a registry artist has no subtree at all -
    nothing hangs off it and it hangs off nothing - so the rollup was a rollup of zero and the
    emitter sent `0` where the reference sends nothing. `_rolled` was reading the **type**
    where it meant the **population**, which is the same mistake the visibility clause and the
    collector each made once, and a test asserts the distinction both ways: no subtree count on a
    registry artist, and the tree artist still rolling up.

    **The first fix was wrong and the suite caught it, not the reasoning.** Dropping registry
    artists from `_rollups` altogether looked right and broke something else: those numbers carry
    the container **runtime** as well, which a music container's `RunTimeTicks` reads (005 AC-30)
    and which the reference answers as `0` on these very rows — so it would have fixed one
    difference by making another. The test that caught it is the one written the same day to fix
    the *price* of that field. What has no subtree statement is the user data alone, so that is
    the one line that changed.

  **And two things this run confirms that were built for it today**: the named anchor pairs
  `Ninety Six Kilohertz` at **row 3 here and row 0 there** — the two orderings genuinely disagree
  and the anchor no longer cares — and the restricted seat's `movies-by-sort-name@0` resolves to
  `Both Subtitle Kinds (of 15)` on **both** sides where the 2026-09-06 report had two different
  libraries. That seat's unasked cases went from 23 to 16.

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all **eight** —
      has a passing test, by name, in `FEATURE_013`.
- [ ] Both artist routes reach **L3**, proven by a differential run and not by the fixture alone.
- [ ] `docs/compatibility/surface.yaml` is unchanged in its rows and carries the two levels raised
      on 2026-09-07: no route is added or removed by this feature.
- [ ] Anything learned during implementation is back in `spec.md`, in the same change.
- [ ] The `ChildCount` divergence is in `behaviours.md` with its provenance and its argument, and
      §5.3 records what closed and what did not.
- [ ] 005 AC-13 is amended rather than left false, and its acceptance-map entry moves with it.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.
