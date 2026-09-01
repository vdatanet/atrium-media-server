---
feature: 010-conformance-harness
title: Conformance harness — tasks
status: Draft
created: 2026-09-02
updated: 2026-09-02
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 010 — Tasks

Fifteen, ordered by two things that are not the usual ones.

**First, the order is fixed by a physical dependency, and it is not negotiable.** Three of the
things this feature must measure cannot be measured until a reference instance this project owns
exists — and one of them is **D-4's own measurement**, *what does a reference server make of the
fixture tree*, which is a library scan and therefore a **write**. The only Jellyfin reachable today
is an operator's production server, which this project does not write to; that is the whole reason
[ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md) exists.
[Plan §6.6](plan.md#66-the-fixture-on-the-other-server) fixes the sequence and this list obeys it:
**T9** lands `tools/_reference.py`, **T10** is `tools/probe_reference_scan.py` and is that
instance's first run and the task that performs the measurement, and **T11** is the fixture task,
written against T10's answer. A list that put the fixture first would be a list nobody could run.

**Second, this feature can pass green while proving nothing, and that is its characteristic
failure.** A run that authenticates only as an administrator skips **12 of the 23 reads** of the
surface that answer differently to a restricted non-administrator (spec §3.9) — and two of those
differ as *shorter lists*, not as refusals, so nothing looks like an error. The two hardest of
§3.10's named comparisons are invisible for the same reason: what the reference hides in a playlist
is hidden by a **parental-rating check** and never by library access, so two servers whose test user
can open everything agree, and the row count is the whole signal (behaviours §3.17). So the
identity dimension is proven **before the sweep that consumes it exists**: **T7** creates and
destroys the seats and asserts the pre-flight refusal, and **T8** — the request loop — is written
`for identity in identities` on top of it, with no `--restricted` flag to forget. That is 009 T6's
placement applied to this feature's own failure mode: the thing most likely to be wrong is proven
before anything relies on it.

Everything provable **without a server** comes first for the same reason. The comparison engine and
its mutation proofs are T2, because a harness with false positives is one nobody reads by the second
week (spec §6, *"does not cry wolf"*), and because those proofs are the only part of this feature
that ever runs in CI. The three registers — the allowlist, the named comparisons, the request cases
— land before the runner that reads them, so the run is measured against a file rather than against
prose. And **T1 comes first of all**, because the prior-measurement register is an *input* to AC-9
and it is stale: nothing may trust it until it has been reconciled.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files they name on
2026-09-02, before being proposed for acceptance. It found three things. The first would have
failed the suite on the day 010 flips to `Implemented`; the third is a scope call and is **reserved
for its owner** rather than taken here.

### 1. AC-2 cannot be mapped the way plan §8 maps it, and the map's own test is what says so

[Plan §8](plan.md#8-testing-strategy) maps AC-2 to *"`tools/probe_reference_scan.py`, by hand —
the one criterion that cannot be a test: it needs both servers. The probe is what runs it, and the
acceptance map names the probe and says so."*

The acceptance map cannot name a probe. `tests/conformance/test_acceptance.py`'s
`test_every_criterion_names_tests_that_exist` resolves every entry as `module:function` through
`importlib.import_module` and `hasattr`, and this plan's own [§2](plan.md#2-inherited-decisions)
inherits the rule that *"a `tools/` module is reached from the suite by path, never as a package"*.
So the row would fail on import the moment `"010"` joins `IMPLEMENTED_FEATURES`, and it would fail
for the right reason: **a criterion whose only proof is a command somebody remembers to run is a
criterion with no proof.** That is 009 T14's finding — *"a criterion with no test at all"* — arriving
one feature early, and it is worth having arrived early because it changes T10 rather than T15.

**The fix is in T10, and it costs one file.** `probe_reference_scan.py` does not only print its
finding: it **writes the reference's reading of the fixture tree down** — the item count per
collection type and the structure, in a checked-in file with the probe's own citation in it — and
AC-2's test compares **Atrium's** scan of the same tree against that record. The comparison then
runs in the default CI job with no Jellyfin anywhere, it fails when Atrium's scan of the fixture
moves, and re-running the probe is what moves the record. Both servers are still needed to *make*
the reading, which is what the probe is for and what a bump re-runs (T14); what is no longer needed
to *check* it is a second server.

### 2. Eight endpoints declare `level: L3`, and nothing has ever checked that a level is reached

`docs/compatibility/surface.yaml` carries a `level` on all 59 rows — one L1, 50 L2 and **eight
L3** — and L3 is defined in [conformance.md](../../docs/compatibility/conformance.md) as *"the
response is byte-comparable to a real Jellyfin's, modulo a documented allowlist"*, proven by the
differential harness. Nothing checks it. `tools/extract_v1_surface.py` validates only that the
value is one of `L0..L3` (its `LEVELS` set); `tests/conformance/test_routes.py` reads `feature` and
`consumers` and never `level`. Meanwhile every feature's definition of done ticks *"every endpoint
reaches the conformance level declared in spec §6"* with the differential half deferred here — 009's
says so in as many words: *"**The differential half is 010's**, as it is for every feature before
this one."*

So AC-3's floor — *at least one request case each* — is the right floor for the surface and the
wrong one for those eight rows, which are the only rows in the repository whose **declared** level
this feature is the only thing that can pay for. T6 seeds `request-cases.yaml` with those eight
first, per identity, and T8's report prints the declared level beside the coverage so a run says
which L3 rows it actually compared. It is not a new criterion: it is AC-3's coverage line made able
to answer the question every other feature's definition of done has been deferring to it.

### 3. §3.10's sixteen rows are not everything the six lists and the compatibility documents owe

The sixteen are checked and they are right: every row of 005's, 006's, 007's, 008's, 009's and
011's *"what this feature owes the next ones"* that a sweep cannot raise is in the table, and the
rest of those rows are sweep-visible and are discharged by T6's request cases and T8's triage.
**Four things are not in it**, and each needs exactly what this feature has just acquired:

| What | Where it is written | Why nothing sees it |
|---|---|---|
| **A container that has lost every file is not removed** | [behaviours §5.2](../../docs/compatibility/behaviours.md) | It carries the **only surviving `⚠️ UNVERIFIED`** in the compatibility documents, and its own text names the remedy: *"a disposable library on a server somebody owns — scanned, emptied of one series' episodes, scanned again."* The audits' A4 check reads **specifications** only, so a marker in `behaviours.md` is invisible to it |
| **A default rescan does not notice a replaced poster** | [behaviours §5.6](../../docs/compatibility/behaviours.md), and 006's owes list | *"Unmeasured from here — deciding it would mean writing into somebody's library and rescanning it"* |
| **Whether the reference's Next Up excludes a pristine specials season** | 005 §7 OQ-7, still open, and 005's owes list names 010 | It needs a library holding a series whose only unplayed episodes are season 0's. The library measured on 2026-08-28 had none |
| **The paused-session ticker freeze** | 007's owes list, [007 plan §6.8](../007-user-data-and-playstate/plan.md) | Cited from the reference's source and never measured on the wire; it costs ten minutes of deliberate silence against a paused session, which is a probe nobody wrote |

The first three are **writes into a library**, which is what the single-use instance is for, and all
four are askable the day T9 lands. **Whether they become rows of `named-comparisons.yaml` is a
scope call and it is not taken here**, because §3.10 is a table in an **accepted** spec and AC-16
counts it: adding rows widens an acceptance criterion, which is the shape of the decision plan §11
reserved as D-3 rather than took. It is recorded as **D-6** below, with a recommendation. Until it
is decided, T12 carries all four as **outstanding readings** in the register's own `outstanding`
section — counted and named in every report, excluded from AC-16's sixteen — which is the reading
that neither loses them nor edits a criterion.

## Decisions this list reserves

| # | The call | Recommendation |
|---|---|---|
| **D-6** | Whether the four debts above join `named-comparisons.yaml` as named comparisons, widening spec §3.10 and AC-16 from sixteen | **Yes, as four new §3.10 rows**, with the spec amended and dated in its frontmatter the way D-3 was. All four are differences a sweep cannot raise, which is exactly what §3.10 is for; behaviours §5.2's `⚠️` in particular is a claim this repository has carried unmeasured since it was written and can now settle. The cost is one amendment to an accepted spec and four rows on a register; the cost of the alternative is that a run reports *"sixteen of sixteen"* while four questions with a written home go on being nobody's |

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — Reconcile the prior-measurement register before anything trusts it

- [ ] **Changes:** `docs/compatibility/reference-target.md` §3. The register holds **fifteen** rows
  of which **seven** are struck and **eight** open, and its prose says *"Six down, nine to go"* —
  counted, not inferred. **Three of the eight open rows are debts that were paid under another
  script's name and never struck:** the four authentication mechanisms are measured by
  `tools/probe_auth_mechanisms.py`, which is what turned four mechanisms into five
  ([behaviours §2.4](../../docs/compatibility/behaviours.md)); the item-identity row names a
  `probe_item_ids.py` that does not exist beside `tools/probe_item_identity.py` that does and that
  ran at 003 T19; the item-level `Container` row names a `probe_media_sources.py` beside
  `tools/probe_media_container.py`, whose finding [behaviours §1.6](../../docs/compatibility/behaviours.md)
  already carries with a `[probe:]` citation. Those three are struck with their real script and
  date. `docs/compatibility/api-surface-v1.md`'s four `prior-probe: 2026-06-13` citations for the
  mechanisms become `[probe: tools/probe_auth_mechanisms.py, …]`. **The five that stay open each
  gain the reason they are open**, and two of them name the instance rather than a missing author:
  `/Users/Public` returning `[]` needs every user hidden and the `LocalAddress` HTTPS override needs
  a server configured for HTTPS — both writes to a configuration, and both T13's. New
  `tests/unit/test_probe_convention.py` with its register half only.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_probe_convention.py -q` — `test_every_register_row_names_a_script_that_exists_or_says_why_not`
  parses §3's table and asserts, per row: a **struck** row names a file under `tools/` that exists,
  and an **open** row either names one that exists or carries a written reason in its own cell. It
  fails today on six rows and it fails again if the reconciliation is reverted — revert the three
  script names and three rows name files that are not there. Plus
  `test_the_prose_count_matches_the_table`, which recomputes struck-versus-open from the rows and
  compares it with the sentence, and fails on any future row added without moving it. And
  `uv run python tools/extract_v1_surface.py` for the surface document's citations.
- **Spec reference:** §3.5, AC-9; plan §6.10, §6.12 finding 3

> First on purpose: AC-9 is *"every prior-measurement debt has a probe script, or a recorded reason
> it cannot have one"*, and until the register says what is actually owed, AC-9's real size is
> unknown. The plan measured it as smaller than the register claims; this task is where that stops
> being a paragraph in a plan.

## T2 — `tools/_differential.py`: the comparison engine, pure, in five classes

- [ ] **Changes:** new `tools/_differential.py` — `Response`, `Class`, `Difference`, `Rules`,
  `compare` and `compare_headers` exactly as [plan §5](plan.md#5-contracts) declares them. Five
  classes and not three: `MISSING_KEY`, `EXTRA_KEY`, `TYPE`, `LENGTH`, `ORDER`, `VALUE`, ordered by
  severity so the report ranks missing keys first (AC-5). Arrays follow
  [plan §6.2](plan.md#62-the-comparison-in-five-classes): lengths first and the rows then **not**
  compared at all (the cascade guard), then the masked canonical fingerprint per row — equal
  sequences say nothing, equal multisets are exactly one `ORDER`, neither aligns by index. No HTTP,
  no filesystem, no clock; it never raises on a difference. New
  `tests/conformance/test_differential.py` and four **hand-written** paired bodies beside it — a bare
  object, a list envelope, a `drawn` array, and a delivery response's headers — hand-written because
  a captured pair proves the engine agrees with whatever the capture held, and because anything
  captured from the reference is somebody's library.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/conformance/test_differential.py -q`, the mutation table of
  spec §6 with one row per class: a removed field → one `MISSING_KEY`; an integer sent as a string →
  one `TYPE`; a changed title → one `VALUE`; a **reordered** thousand-row array → exactly one
  `ORDER` **and zero `VALUE`s**; a shorter array → exactly one `LENGTH` **and no findings from its
  rows**. The last two are the ones that fail when the guard is deleted: remove the length check and
  the shorter-array case reports hundreds of findings; remove the fingerprint step and the reordered
  case does the same. Both assert a **count**, not a substring, so neither can pass by accident.
  Plus `python3.9 -c "import ast,sys; ast.parse(open('tools/_differential.py').read())"` and the
  `tools` CI job, which runs every non-underscore tool's `--help` on 3.9 and 3.14.
- **Spec reference:** §3.2, §6, AC-4, AC-5; plan §5, §6.2

> Second on purpose, and it is the only part of this feature that ever runs in CI. A comparison that
> cannot be unit-tested is the one thing this feature must not ship (plan §3), and a comparison that
> cries wolf is a harness nobody reads by the second week.

## T3 — `docs/compatibility/allowlist.yaml` and `tools/_allowlist.py`: three kinds, scoped

- [ ] **Changes:** new `docs/compatibility/allowlist.yaml` in the hand-written YAML subset
  `surface.yaml` uses, with the six fields of [plan §4.1](plan.md#41-docscompatibilityallowlistyaml)
  — `kind` (`field`, `drawn`, `unordered`), `endpoint`, `pointer`, `reason`, `because`, `since`.
  Every row of spec §3.3's two tables becomes an entry, **scoped by endpoint and JSON pointer and
  never by a bare field name**: `ChildCount` is excused on `/UserViews`' rows and nowhere else,
  because the same property on a series, a season or the two-disc album is a real computed subtree
  aggregate in this server (`db/item_queries.py`'s `ContainerAggregates`, gated by `api/items.py`'s
  `_AGGREGATE_FIELDS`) and asserted by L2. New `tools/_allowlist.py` reads it and resolves an entry
  against `(endpoint, identity, pointer)`; a `because` that is neither a `behaviours.md` section nor
  one of the four declared derivation classes **fails the load** (AC-6, as D-3 refined it). New
  `tests/unit/test_allowlist.py`.
- **Depends on:** T2
- **Verified by:** `uv run pytest tests/unit/test_allowlist.py -q`. `test_an_entry_with_no_because_fails_the_load`
  and `test_a_fifth_derivation_class_fails_the_load` construct the bad entry and assert the loader
  raises — AC-6 proven by making it fire, not by asserting the good file passes.
  `test_childcount_is_excused_on_a_library_view_and_nowhere_else` resolves the same pointer on
  `/UserViews` and on `/Items/{itemId}` and asserts the second is **not** excused; deleting the
  `endpoint` scoping makes it fail, which is the whole of plan §6.3's argument turned into a test.
  `test_the_two_prose_tables_say_what_the_file_says` parses spec §3.3 and
  `conformance.md`'s L3 table and compares them row for row against the YAML — the protection the
  2026-09-01 audit's M1 finding asked for, *"a table of tests is the section most prone to this:
  nothing reads it, so nothing fails when it drifts"*.
- **Spec reference:** §3.3, AC-6, AC-17, AC-18; plan §4.1, §6.3

## T4 — The excused arrays, and an ordering that is not total

- [ ] **Changes:** `tools/_differential.py` gains the two array kinds `Rules` already declares:
  `drawn` compares the envelope, the **row count**, and every row's key set and types, and no row's
  values (AC-17); `unordered` compares as a multiset, so a difference in row order alone produces
  nothing (AC-18). The three excused arrays of spec §3.3 become entries in T3's file: the rows of
  `/Items/{itemId}/Similar` (behaviours §3.23), the rows of any listing ordered at random
  (behaviours §3.6), and the rows of a listing ordered by a key with ties (behaviours §3.6).
- **Depends on:** T2, T3
- **Verified by:** `uv run pytest tests/conformance/test_differential.py -q`, two mutation rows from
  spec §6 that exist to catch the over-excusing: **a key removed from a row of a `drawn` array is
  still reported** while a *value* changed in the same row is not — delete the "walk the rows for
  shape" branch and the first assertion fails, which is the difference between excusing an array and
  excusing what is in it; and a reordered `unordered` array produces nothing while the same array
  reordered **and** changed produces exactly the change.
- **Spec reference:** §3.3, §6, AC-17, AC-18; plan §6.2, §6.3

## T5 — `docs/compatibility/named-comparisons.yaml`: sixteen rows, and what each needs

- [ ] **Changes:** new `docs/compatibility/named-comparisons.yaml` — one row per row of spec §3.10,
  each with `id`, `what`, `why_the_sweep_misses_it`, `needs` (`identity:restricted`,
  `identity:playback-denied`, `fixture`, `latency`, `bytes`, `twice`), `behaviours` and `runner`,
  which is `none` until the task that writes it. **`needs` is the field that earns the file**: it is
  what lets a report say *"four outstanding, and three of them because no fixture instance was
  available"*, and what a run consults to decide whether a row is even askable before it counts it
  as a miss. The file also gains an `outstanding:` section carrying the four readings of *"What the
  gate changed"* §3 — counted and named in every report, and **not** part of AC-16's sixteen until
  D-6 is decided. `tests/unit/test_allowlist.py` gains the register's assertions.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_allowlist.py -q`.
  `test_the_register_is_spec_310s_table` parses spec §3.10's rows and asserts the ids cover them
  one for one, so a row deleted from either side fails; `test_every_row_names_a_behaviours_section_that_exists`
  resolves each `behaviours` value against the anchors in `behaviours.md` and fails on a section
  that is not there — which is 006 T3's finding (a task citing an exception withdrawn three features
  earlier) turned into a check; and `test_no_outstanding_row_is_counted_as_named` asserts the two
  lists are disjoint and that AC-16's count reads sixteen.
- **Spec reference:** §3.10, §4, AC-16; plan §4.2, §6.4

## T6 — `docs/compatibility/request-cases.yaml`: the eight L3 rows first, then the surface

- [ ] **Changes:** new `docs/compatibility/request-cases.yaml` — per endpoint, a name, the query,
  the body, the **anchor** that fills each path parameter, the identities the case is meaningful
  for, and a sentence saying what the case is for. Anchors, not identifiers: the two servers derive
  identifiers differently by design, so `GET /Items/{itemId}` is *"the item at position 3 of
  `/Items?sortBy=SortName&includeItemTypes=Movie&recursive=true`"*, resolved against each server
  immediately before the case runs (plan §6.1.1). **Seeded L3-first**, per *"What the gate changed"*
  §2: the eight `level: L3` rows of `surface.yaml` get their cases before the other 51, each for
  every identity it is meaningful for, because they are the rows whose declared level nothing has
  ever checked. Then the floor — one case per endpoint, 59 — then the cases the two analysed clients
  actually send. **A case whose anchor needs a particular kind of item declares `needs: fixture` and
  leaves its anchor unfilled**; T11 fills them, because the fixture world it anchors into is D-4's
  and is not chosen until T10.
- **Depends on:** T3, T5
- **Verified by:** `uv run pytest tests/unit/test_allowlist.py -q`.
  `test_every_surface_endpoint_has_at_least_one_case` reads `surface.yaml` through
  `tools/extract_v1_surface.py`'s own `parse_surface` rather than a second parser, and fails on the
  60th endpoint the day one is added; `test_every_l3_row_has_a_case_for_every_identity_it_is_meaningful_for`
  fails on any of the eight with one identity; and `test_an_anchor_over_an_unordered_listing_is_refused`
  builds a case anchored on a listing T3's allowlist marks `unordered` and asserts the loader
  rejects it — an anchor is only as sound as the ordering it indexes, and without that refusal every
  such case is a comparison of an arbitrary row.
- **Spec reference:** §3.2, AC-3; plan §4.3, §6.1.1

## T7 — The identities a run authenticates as, created and destroyed by the run

- [ ] **Changes:** `tools/differential.py` gains `Role`, `Identity` and the seat lifecycle of
  [plan §6.7](plan.md#67-identities): `administrator` from `.env` or from an instance's wizard;
  `restricted` from `POST /Users/New` then `POST /Users/{userId}/Policy` narrowing `EnabledFolders`
  to one library `[spec: CreateUserByName, UpdateUserPolicy]`; `playback-denied` the same with the
  playback-processing permission denied. The shape is lifted from
  `tools/probe_restricted_surface.py`, which already builds a seat under a fixed name and removes it
  in a `finally`, rather than invented. **The pre-flight refusal is a precondition, not a cleanup**:
  the run lists the users and **refuses to start** if a seat with its own fixed name is already
  there, because such a seat is either another run in flight or the wreckage of one, and reusing it
  means measuring against a policy somebody else set (AC-15).
- **Depends on:** —
- **Verified by:** `uv run pytest tests/conformance/test_differential.py -q`.
  `test_a_seat_that_already_exists_refuses_the_run_and_names_it` drives the pre-flight against a
  stubbed user list holding the fixed name and asserts the refusal message contains it; delete the
  pre-flight and it fails. `test_a_run_that_created_a_seat_tears_it_down_on_the_exception_path`
  raises inside the run and asserts the teardown was still called for every `Identity` whose
  `created_by_the_run` is true — which is the 28-playlist lesson, asserted rather than promised, and
  it is why `created_by_the_run` is a field of `Identity` and not of the run.
- **Spec reference:** §3.9, AC-14, AC-15; plan §5, §6.7

> **Before the sweep, deliberately.** This is the placement 009 gave its visibility clause: the
> thing most likely to be wrong is proven before anything routes to it. Here the thing most likely
> to be wrong is that nobody uses the second seat — 12 of 23 reads answer differently to it, two of
> them as shorter lists — so the seats exist before the loop that consumes them, and T8's loop is
> written over them rather than beside them.

## T8 — `tools/differential.py`: the CLI `conformance.md` already publishes, and the report

- [ ] **Changes:** new `tools/differential.py` with the invocation
  [conformance.md](../../docs/compatibility/conformance.md#l3--differential) already documents —
  `--atrium`, `--jellyfin`, `--surface`, `--report` — **adopted rather than reinvented**, because
  the harness is a published interface before it is a program, plus `--identity`, `--fixture` and
  `--named`. The run loop of [plan §6.1](plan.md#61-the-run) with **identity outermost**, the two
  servers asked **back to back per case** rather than one whole sweep and then the other, and
  `RunReport` with `is_clean()` false while any difference is untriaged **or** any named comparison
  is outstanding. The report is spec §3.4's, with the per-identity coverage line (AC-14), the
  declared conformance level beside each endpoint (*"What the gate changed"* §2), the pinned image
  digest beside the Atrium sha, and missing keys ranked first (AC-5). **The two-server guard reads
  the `Server` header and never `ProductName`**: `_probe.py`'s `connect` cannot tell Atrium from
  Jellyfin, because Atrium answers `"Jellyfin Server"` there on purpose (reference-target §4,
  behaviours §4.1), while `Server` is `Atrium/<version>` here (`compat/middleware.py`'s
  `SERVER_VALUE`) against the reference's `Kestrel`. **`conformance.md` is corrected in this same
  commit:** the `ATRIUM_JELLYFIN_URL` it names as the opt-in switch appears **nowhere** in this
  repository — no code reads it and no test skips on it — and the harness uses `JELLYFIN_URL`, the
  name `tools/_probe.py` and the `.env` already use, rather than a second one.
- **Depends on:** T2, T3, T4, T5, T6, T7
- **Verified by:** `uv run pytest tests/conformance/test_differential.py -q`.
  `test_a_report_built_from_one_identity_says_one_identity` asserts the coverage line names what ran
  rather than the surface (AC-14); `test_a_run_with_an_outstanding_named_comparison_is_not_clean`
  asserts `is_clean()` is false with every difference triaged and one row outstanding, and names the
  row and its missing `need` — delete the named half of `is_clean` and it passes, which is the
  failure this feature exists to prevent, one directory away from the CI job that reported green
  because it ran nothing (008 T18);
  `test_a_reference_that_is_actually_an_atrium_is_refused_by_the_server_header` asserts the refusal,
  and asserts that the same pair passes `ProductName` — the guard is only worth having if the wrong
  guard is shown to be wrong. Plus `grep -rn ATRIUM_JELLYFIN_URL docs/ tools/ src/ tests/` coming
  back empty, and `python3.9 tools/differential.py --help` reaching no server and reading no
  credentials.
- **Spec reference:** §3.2, §3.4, §3.7, AC-3, AC-5, AC-14, AC-16; plan §5, §6.1, §6.11, §6.12

## T9 — `tools/_reference.py`: a Jellyfin this project owns, uses once, and destroys

- [ ] **Changes:** new `tools/_reference.py` — `InstanceSpec` and `ReferenceInstance`, a context
  manager because the destruction is the invariant. `__enter__` performs
  [plan §6.5](plan.md#65-the-single-use-reference-instance) in order: **sweep** whatever a killed run
  left, by label and by scratch directory, and print how many; **start** one container of the pinned
  version **from a pinned digest**, `--rm`, a loopback port the run picks, an ephemeral data
  directory, and the fixture tree bind-mounted **read-only**; **wait for the API, not the process**,
  on `GET /System/Info/Public` answering a `ProductName` naming Jellyfin, because a listening socket
  is not a configured server; **configure with no human** over `POST /Startup/Configuration`,
  `POST /Startup/User`, `POST /Startup/Complete` and `POST /Library/VirtualFolders` with
  `refreshLibrary=true` `[spec: UpdateInitialConfiguration, UpdateStartupUser, CompleteWizard,
  AddVirtualFolder]`; **wait for the scan on the server's own answer**, `GET /ScheduledTasks` until
  the library scan reports itself idle `[spec: GetTasks]`, with a deadline — not a sleep and not an
  item count that has stopped changing, because a count that has stopped changing is
  indistinguishable from a scan that has not started. `__exit__` destroys the container and the data
  directory on the exception path and the success path alike, and deletes **nothing** inside the
  instance first: the accounts, playlists and libraries die with it. New `tools/reference_instance.py`
  stands one up and leaves it running for a human debugging a difference by hand, and its `--help`
  must not start one. The image digest is written into
  [reference-target §1](../../docs/compatibility/reference-target.md#1-the-pinned-version)'s waiting
  row by this task, which is the first run that has one. Runtime absent, image unpullable, wizard
  refusing or scan timing out: every case and named row declaring `needs: fixture` is **outstanding
  with the reason** and `is_clean()` is false — the run neither fails nor passes.
- **Depends on:** T8
- **Verified by:** By hand, once, and then by two things that run without one.
  `uv run pytest tests/conformance/test_differential.py -q`:
  `test_a_fixture_run_with_no_runtime_reports_every_fixture_row_outstanding_and_is_not_clean` stubs
  the runtime as absent and asserts each `needs: fixture` row is named with its reason and
  `is_clean()` is false — delete the degradation branch and the run reports clean having compared
  nothing, which is ADR-0007's *"the dependency buys coverage; its absence costs coverage and says
  so"*. `test_the_teardown_runs_on_the_exception_path` raises inside the `with` and asserts destroy
  was called. And `python3.9 tools/reference_instance.py --help` under the `tools` CI job, which
  starts nothing and must keep starting nothing. **By hand:** one full lifecycle against a real
  runtime, and the unattended sequence's one assumption checked rather than discovered — plan §6.5
  step 4 reads the first-time-setup authorization policy **from a document**, and if a credential is
  required earlier than that reads, the sequence gains a step and the plan says so in the same
  commit.
- **Spec reference:** §3.1, §4, AC-2, AC-15; plan §6.5, §7; [ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md)

> **The physical dependency starts here.** Everything above runs against a server somebody already
> has, or against no server at all. Everything below needs this one.

## T10 — `tools/probe_reference_scan.py`: D-4's measurement, and the reading AC-2 is checked against

- [ ] **Changes:** new `tools/probe_reference_scan.py`, the instance's **first run** and the task
  that performs the measurement D-4 reserved: *given the fixture tree, what does a reference
  server's library contain?* The 003 tree is paths and filler bytes by design — its own generator
  says *"these are not decodable media"* — and **whether a reference makes items out of a file its
  prober cannot open is unmeasured**; `tools/probe_library_extensions.py` measured which extensions
  a real library's items carry, which is a lower bound over files that are real media and says
  nothing about this. The probe answers it and **writes the answer down**: a checked-in reading —
  per collection type, the item count and the structure, with the probe's own
  `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, <date>]` citation inside it. Plan §6.6's
  two priced branches are then chosen between in the same commit, in the plan, dated: the media
  world extended with the structural entries §3.1 owes, or both trees as two libraries with AC-2
  comparing both. **Until this has run the default is a default and not a finding**, and no document
  may cite it as measured.
- **Depends on:** T9
- **Verified by:** `python3 tools/probe_reference_scan.py --allow-writes` against the instance,
  printing its finding and its citation and exiting non-zero if it contradicts what the plan says
  (AC-7, AC-8). Then, and this is the half that survives the run:
  `uv run pytest tests/library -q -k reference_reading` — `test_atriums_scan_of_the_fixture_matches_the_recorded_reference_reading`
  scans the same tree with the real 003 pipeline and compares against the checked-in file, which is
  **AC-2 as a test rather than as a command somebody remembers** (*"What the gate changed"* §1). It
  runs in the default CI job with no Jellyfin anywhere, it fails when Atrium's scan of the fixture
  moves, and re-running the probe is what moves the record.
- **Spec reference:** §3.1, AC-2, AC-7, AC-8; plan §6.6, §11 D-4

## T11 — The fixture world gets what §3.1 owes, written against T10's answer

- [ ] **Changes:** the fixture the instance is given, extended with the five entries spec §3.1 owes
  and the two the named comparisons need, through the generator that already builds it rather than a
  third world (plan §6.6). `tests/fixtures/media.py` already carries the **multi-part film**
  (`two_parter_first` / `two_parter_second`), a **film with a subtitle file beside it** and an
  **image subtitle track** (`pgs_bitstream`), so what is actually owed is smaller than §3.1 reads:
  a **subtitle file in a legacy encoding** — every sidecar in that module is written
  `encoding="utf-8"` today, so behaviours §5.11 is unreachable in the suite as well as in a
  differential — a **playlist holding items from two libraries**, an **empty library**, and the
  planted file **EXIF orientation** needs. The `needs: fixture` anchors T6 left unfilled are filled
  here, against the world T10 chose. `tests/unit/test_media_fixtures.py` extended for AC-1 and
  AC-13. **The fixed modification time is load-bearing across the mount**:
  `tests/fixtures/library/generate.py` stamps every file with one `FIXED_MTIME_NS`, a bind mount
  preserves it and a copy does not, and a fixture whose timestamps moved between the two servers
  would put a difference into `DateCreated` on every item — a field the allowlist excuses, which is
  worse than a visible failure because the noise would be invisible.
- **Depends on:** T10
- **Verified by:** `uv run pytest tests/unit/test_media_fixtures.py -q` — two builds byte-identical
  (AC-1), and every fixture file generated by a **declared entry** so no file is a copyrighted work
  (AC-13), the existing rule restated for the new entries. `test_the_mount_preserves_the_fixed_time`
  asserts every built file's mtime is `FIXED_MTIME_NS` after the tree has been handed across the
  mount; break the mount into a copy and it fails, which is the invisible false positive plan §9
  names. And `test_the_legacy_encoded_sidecar_is_not_utf8`, which fails the day somebody "fixes" the
  encoding — a fixture that is valid UTF-8 cannot exercise behaviours §5.11.
- **Spec reference:** §3.1, AC-1, AC-13; plan §6.6, §9

## T12 — The named comparisons: four runner shapes, and the outstanding readings

- [ ] **Changes:** `tools/differential.py` gains a `runner` per row of `named-comparisons.yaml`, one
  signature, `(instances, identities) -> NamedResult`, so the sixteen are code beside the sweep and
  not prose beside the report (plan §6.4). Four shapes cover all of them: **a second seat** — the
  named reader, the entries a reader cannot reach, the delivery-time policy refusal — where the whole
  signal is a status or a **row count**; **the same request twice** — the de-duplication that
  misses, where the *reference's* disagreement with itself is the finding and never a flake to
  retry (6 of 8 identical requests behaved differently, behaviours §3.18); **something that is not
  in a body** — the progressive header frame, burn-in, the image track's latency, the subtitle
  playlist's bytes, the manifest's `NAME` masked against its invariant form; and **a library the
  reference has to be given** — the multi-part film, the legacy-encoded subtitle, EXIF orientation,
  the empty library, the media source with no runtime. The last two rows of §3.10 stay ordinary
  request cases with a register row pointing at them. A runner that raises leaves its row
  **outstanding with the exception** and the run continues. The four **outstanding readings** of
  *"What the gate changed"* §3 are reported by name every run, with their reason, pending D-6.
- **Depends on:** T7, T8, T11
- **Verified by:** `uv run pytest tests/conformance/test_differential.py -q` for the shapes that can
  be driven without a server: `test_a_runner_that_raises_leaves_its_row_outstanding_and_the_run_continues`,
  and `test_the_row_count_is_the_signal_for_the_unreachable_entries_row`, which asserts the runner
  compares **counts** and not bodies — the two servers agree on every field of every row they both
  show, so a runner that diffed bodies would report nothing and pass. Then by hand against an
  instance: `python3 tools/differential.py --named --fixture`, whose report must name sixteen run or
  outstanding, and four outstanding readings beside them.
- **Spec reference:** §3.10, AC-16; plan §6.4

## T13 — The probe convention enforced, the cleanup contract shared, and the last two debts paid

- [ ] **Changes:** `tests/unit/test_probe_convention.py` gains its convention half — a sweep over
  every `tools/probe_*.py` in the shape `tests/unit/test_import_directions.py` already uses for the
  production ledger: each reaches `_probe.main`, names a document and a section, and declares
  `needs_writes` where it writes. Twenty-five of the 53 declare it today. `tools/_probe.py` gains a
  shared **created-and-owned register** whose teardown runs in a `finally`, so *"cleans up,
  including on failure"* stops being a thing twenty-five scripts implement separately —
  **and this task's first job is to check that the concurrent leak fix did not already do it**, and
  to build on it rather than beside it. The two register rows T1 left for the instance are paid
  here, because both are writes to a configuration and neither can be asked of an operator's server:
  `/Users/Public` returning `[]` needs every user hidden, and the `LocalAddress` HTTPS override needs
  a server configured for HTTPS (behaviours §2.2, §2.3).
- **Depends on:** T1, T9, and the concurrent probe-cleanup fix in `tools/`
- **Verified by:** `uv run pytest tests/unit/test_probe_convention.py -q`.
  `test_every_probe_reaches_the_shared_entry_point` fails on a 54th probe that prints its own
  output — which is the thing this repository does not have today; `test_report_returns_one_on_a_contradiction`
  drives `_probe.Probe.report` directly with a finding that contradicts its expectation and asserts
  the exit code, and `test_a_contradiction_names_the_document_and_the_section` asserts the message
  carries both (AC-7, AC-8). `test_a_writing_probe_that_leaks_fails_the_sweep` registers a created
  object, raises, and asserts the register tore it down — delete the `finally` and it fails, which
  is the requirement the server disproved on 2026-09-01 turned into a test.
- **Spec reference:** §3.5, AC-7, AC-8, AC-9; plan §6.10

## T14 — `tools/bump_reference_version.py`: four steps in order, and no way past a failure

- [ ] **Changes:** new `tools/bump_reference_version.py` running
  [conformance.md's four steps](../../docs/compatibility/conformance.md#when-the-reference-version-moves)
  in order and refusing to continue past a failure (AC-12): fetch and validate the document, run the
  differential **and** the named comparisons, re-run every probe and update each supported document's
  `Last verified` line, and only then write the version. A sequencer, not a new mechanism. It
  enforces the two-row distinction reference-target §1 records: when only the **contract** row moves
  — the same server, a different document of it — step 2 has no input, and the command says so and
  skips it; when the **running reference** changed, step 2 is mandatory and no flag skips it. New
  `tests/unit/test_version_bump.py`.
- **Depends on:** T8, T12, T13
- **Verified by:** `uv run pytest tests/unit/test_version_bump.py -q` — each of the four steps made
  to fail in turn, asserting both that the command stopped **and that the later steps did not run**,
  which is the half that catches a sequencer that reports a failure and carries on.
  `test_no_flag_skips_step_two_when_the_running_reference_changed` asserts the refusal by trying
  every flag the parser has; delete the guard and it passes, and *"a bump that skips step 2 has not
  been done, it has been declared"* becomes prose again. Plus
  `python3.9 tools/bump_reference_version.py --help`.
- **Spec reference:** §3.8, AC-12; plan §6.9

## T15 — The ignored-parameter report, the acceptance map, the levels, and 010 is Implemented

- [ ] **Changes:** two things, and the first is D-5. `src/atrium/compat/query_params.py`'s
  `IgnoredParameters.record` gains the **client**, read from the header `compat/auth.py` already
  parses — AC-10 names four columns and the recorder takes two, and nothing anywhere reads `counts`
  or `total()`, so the count exists in a live process and reaches nothing. The tally is written into
  the **data directory** in `server.py`'s lifespan `finally`, which is where it is complete because
  it is after the last request a route could have answered, and **never to a route**: an endpoint
  serving it would be an endpoint Jellyfin does not have, and "optional, behind a flag" does not save
  it, because an extension a client can discover is still a delta (Principle I). `differential.py`
  reads it beside the report it is writing anyway and emits `reference/ignored-parameters-<date>.md`
  with parameter, endpoint, count and client. Then the close:
  `tests/conformance/test_acceptance.py` gains `FEATURE_010` — eighteen rows, each naming tests that
  exist — and `"010"` joins `IMPLEMENTED_FEATURES`; the eight `level: L3` rows of `surface.yaml`
  checked against what T8's report actually compared, and the count of endpoints, cases and
  identities stated; `spec.md`, `plan.md` and this file to `Implemented`;
  [`specs/README.md`](../README.md), [`docs/roadmap.md`](../../docs/roadmap.md),
  [`AGENTS.md`](../../AGENTS.md) and `tools/README.md`'s planned-tools table updated for what 010
  now serves; and this file gains **what 010 owes the next ones**.
- **Depends on:** T14
- **Verified by:** `uv run python tools/extract_v1_surface.py --print-summary`, the full gate, and
  `test_every_criterion_names_tests_that_exist`, `test_the_specification_still_has_the_criteria_this_map_expects`,
  `test_every_implemented_feature_has_a_map` and `test_no_route_ships_ahead_of_its_feature` — 010
  adds no route, so that last one must report **exactly the 59 it reported before**, which is the
  assertion that catches a harness that grew an endpoint. Plus
  `uv run pytest tests/unit/test_compat_query_params.py -q`:
  `test_the_tally_names_the_client_that_sent_the_parameter` and
  `test_the_tally_is_written_to_the_data_directory_at_shutdown_and_to_no_route` — the second greps
  the router for a path serving it and asserts there is none, because the reason that is forbidden
  is a principle and not a preference.
- **Spec reference:** §3.6, all of §5, §6; plan §6.8, §11 D-5

> **This task exists to find what the other fourteen got wrong**, which is the shape 008 T14, 011
> T12 and 009 T14 each took and each earned: between them they found a criterion with no test at
> all, four mapped to tests that proved less than their names, two that said what their own tests
> contradict, and a definition of done that was false when it was written. Read those three Done
> notes before starting this one.

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every one of spec §5's **eighteen** acceptance criteria has a passing test, named in
      `FEATURE_010`. **AC-2 is a test and not a command** (*"What the gate changed"* §1): the
      reference's reading of the fixture is recorded by `probe_reference_scan.py` and checked in,
      and Atrium's scan is compared against the record in the default suite.
- [ ] Every endpoint reaches the conformance level declared in `surface.yaml`, and for the **eight
      rows declared L3** that is a claim this feature is the first thing in the repository able to
      make. The report names them and says which were compared, per identity.
- [ ] `surface.yaml` is unchanged and the router serves the same 59 routes. **This feature adds no
      endpoint**, and the ignored-parameter tally is a file in the data directory precisely so that
      it cannot become one.
- [ ] Every `§3.10` named comparison is run or reported outstanding **by name**, and an outstanding
      one keeps the run from being clean. The four outstanding readings are reported beside them,
      pending D-6.
- [ ] Every allowlist entry declares a `behaviours.md` section or one of the four derivation
      classes, is scoped by endpoint and JSON pointer, and carries a date — and an entry that
      excuses nothing on a run is reported, because the allowlist is a metric that should shrink.
- [ ] The default CI job passes with no Jellyfin available and no network access, and **nothing this
      feature adds carries `needs_reference`**: the mutation proofs run on checked-in pairs, and
      `tests/conftest.py`'s socket guard is unchanged.
- [ ] Every prior-measurement debt in `reference-target.md` has a probe script or a recorded reason
      it cannot have one, and the register's prose count matches its own table.
- [ ] Anything learned during implementation is back in `spec.md` and `plan.md`, in the same change,
      and any decision a task escalates is taken by its owner rather than improvised.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`, with `specs/README.md`,
      `docs/roadmap.md` and `AGENTS.md` saying the same thing.

## What is out of scope, recorded so it is not mistaken for an oversight

- **Deciding what Atrium does about a difference this feature finds** (spec §2). The harness
  triages; the answer belongs to the feature that owns the endpoint, through
  [behaviours §3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made). The gate
  that accepted the spec found two such differences and left both to 005, which is the procedure
  working — a harness that had "fixed" them would have made a Principle I decision inside a tool.
- **Any CI job that contacts or starts a Jellyfin.** ADR-0007 rejects it on the merits and not on
  cost: a gate whose result depends on pulling somebody else's image is not a gate. The consequence
  — *the strongest check in the project is the one that is never automatic* — is stated rather than
  worked around, and the two mechanisms that answer it are `bump_reference_version.py`, which makes
  the run mandatory at the moment it matters most, and `is_clean()`, which makes a run that skipped
  things say so.
- **A recorded session as the gate.** OQ-3 answered yes for the bodies and no for the feature: 16 of
  19 reads are byte-stable, so a recording replays faithfully — and a recording answers only the
  requests it recorded, while the defect class L3 exists to find is the field nobody thought to ask
  for. It is a regression net, recorded here so a later reader does not rediscover the idea and
  mistake it for the gate.
