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

### 3. The fixture has no performer who is nobody's album artist

AC-1's discriminating case is exactly that item, and the query world has not got one: `guest_track`
is performed by `ALBUM_ARTIST`, who is an album artist elsewhere. Without a new one, AC-1 passes on
a world that cannot fail it — which is this project's own recurring finding, one feature at a time.
**T6 seeds it**, and it is the reason T6 exists as a task rather than as a line of T5.

---

## T1 — Revision `0009`: the constraint, the column, the backfill

- [ ] **Changes:** `src/atrium/db/migrations/versions/0009_artist_registry.py`, and
      `src/atrium/db/models.py` where the constraint is declared. The biconditional
      `ck_items_by_name_has_no_library` becomes the two implications it stood for, with the artist
      type exempted **by name** and no other exemption; `item_artists.artist_item_id` becomes
      `NOT NULL`, backfilled through `for_by_name`; one index on `item_artists (credit,
      artist_item_id)`.
- **Depends on:** —
- **Verified by:** `pytest tests/db/test_migrations.py` — up and down on a database holding a tree
  artist, a registry artist and a credit naming each, with the down path asserted to restore both
  the biconditional and the nullable column. The backfill is asserted to derive the same
  identifier the writer will, on the same name, without either reading the other.
- **Spec reference:** §4 of `spec.md`, §4 of `plan.md`

## T2 — The registry rows, written from the credits

- [ ] **Changes:** `src/atrium/metadata/byname.py` — `BY_NAME_FIELD` gains `ARTISTS` and
      `ALBUM_ARTISTS`, and the comment citing §5.3 as the reason for their absence is replaced by
      the reading that closed it. `src/atrium/db/repositories.py` — the credit writer calls
      `ensure_by_name` and stores what it returns, so `_artist_item` stops asking whether the
      scanner happened to make one.
- **Depends on:** T1
- **Verified by:** `pytest tests/unit/test_by_name_items.py tests/library/` — a scan of the query
  world leaves a row for every distinct folded credit name, two spellings of one name leave one
  row with the first spelling, and **the tree artists are untouched**: every identifier 003 derived
  is still there, which is AC-7's first half.
- **Spec reference:** §3.1, §3.4, AC-3, AC-7

## T3 — The collector, scoped so it can never take a tree artist

- [ ] **Changes:** `src/atrium/db/repositories.py` — `collect_by_name_garbage` gains the credit
      table as a referencing column and is scoped to rows with `library_id IS NULL`.
- **Depends on:** T2
- **Verified by:** `pytest tests/unit/test_by_name_items.py` — a collection over a world holding a
  tree artist nothing references **deletes nothing**, and the same collection after a credit is
  removed takes the registry row. Write the tree-artist assertion **first**: without the scoping it
  fails, and that failure is the whole reason this is a task.
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

- [ ] **Changes:** `tests/fixtures/query.py` — a performer who is **nobody's** album artist, and a
      **second music library** sharing one artist name with the first. `GENERATOR_VERSION` moves
      with it if the media world is touched.
- **Depends on:** —
- **Verified by:** `pytest tests/` — the world builds, and the two new handles are asserted to be
  what they claim: the performer appears in no album-artist credit anywhere, and the shared name
  resolves to **two tree artists and one registry row**.
- **Spec reference:** AC-1, AC-2

## T7 — The body, and the goldens

- [ ] **Changes:** `tests/golden/` — the registry artist's list row and full body, regenerated and
      **read**. `ChildCount` is `0` on it, which the aggregate machinery answers without being
      asked; `ParentId` is absent.
- **Depends on:** T5, T6
- **Verified by:** `pytest tests/conformance/test_golden_items.py` and `git diff tests/golden` read
  in review. Every golden that moves is a listing whose population changed; one that moves for
  another reason is a defect this plan did not foresee.
- **Spec reference:** §3.1, AC-5, AC-6

## T8 — What this feature owes three other documents

- [ ] **Changes:**
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

- [ ] **Changes:** the three 013 documents to `Implemented`, `specs/README.md`'s row, and the
      definition of done below with its counts made true.
- **Depends on:** T1–T8
- **Verified by:** `pytest` whole, `ruff`, `ruff format`, `mypy`, and a differential run against a
  single-use reference instance — the two routes are `L3` since 2026-09-07, so this is the first
  feature whose closing task cannot tick its conformance line from the fixture alone.
- **Spec reference:** §6

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
