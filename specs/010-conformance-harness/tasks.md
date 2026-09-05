---
feature: 010-conformance-harness
title: Conformance harness — tasks
status: Implemented
accepted: 2026-09-02
created: 2026-09-02
updated: 2026-09-02
implemented: 2026-09-02
amended: 2026-09-02 — **D-6 is taken, and this list records the decision rather than the reservation.** The four readings of *"What the gate changed"* §3 — behaviours §5.2, behaviours §5.6, 005 §7 OQ-7 and 007's paused-session ticker — join spec §3.10 as named comparisons, so **§3.10 is twenty rows and AC-16 counts twenty**. The spec is amended and dated in its frontmatter the way D-3's was. T5 loses the `outstanding:` section it was to give the register, T12 grows from four runner shapes to six, and the definition of done counts twenty. Behaviours §5.2 keeps its `⚠️ UNVERIFIED` marker: a §3.10 row is an owner and a method, not the reading that discharges it. `status` stays `Draft` — this list's own gate is a separate act.
closing_review: 2026-09-02 — **all fifteen tasks are done, D-7 is taken, and 010 is `Implemented`.** T15 wrote the acceptance map, the ignored-parameter report (D-5) and the first reader of `surface.yaml`'s `level` column, and found the class its three predecessors found: a criterion with no test at all (AC-11, mapped to *"CI, unchanged"* and asserted nowhere), a criterion half with no test (AC-7's citation, the mechanism Principle II rests on), and a criterion whose own measurement contradicts it — **AC-2**, which claimed the two servers produce *"the same item count and the same structure"* where the comparison declares **forty-seven differences**, every one of them owned by 003 or 004 and therefore outside this feature by §2. Amending it was **D-7**, reserved for its owner below and **taken on 2026-09-02, the recommendation accepted**: AC-2 states the comparison that exists and runs, the spec is amended and dated the way D-3's and D-6's were, and the status line moves in all six documents. **What `Implemented` means here is stated rather than assumed**: the fifteen tasks are done and the eighteen criteria are proven by tests that assert what the criterion says — not that the harness has swept everything. Six of the twenty named comparisons are still outstanding with their owners, no `level: L3` row has been shown to reach L3, and both are on the owes list rather than inside the status word.
plan_status_required: Accepted
plan_status_actual: Implemented
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
failed the suite on the day 010 flips to `Implemented`; the third was a scope call, reserved for its
owner as **D-6** rather than taken by the list, and **taken on 2026-09-02** — the recommendation
accepted, the accepted spec amended for it, and the record below rewritten to say so.

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

### 3. §3.10's sixteen rows were not everything the six lists and the compatibility documents owe — they are twenty now

The sixteen are checked and they are right: every row of 005's, 006's, 007's, 008's, 009's and
011's *"what this feature owes the next ones"* that a sweep cannot raise is in the table, and the
rest of those rows are sweep-visible and are discharged by T6's request cases and T8's triage.
**Four things were not in it**, and each needs exactly what this feature has just acquired — all
four are rows of §3.10 since D-6:

| What | Where it is written | Why nothing sees it |
|---|---|---|
| **A container that has lost every file is not removed** | [behaviours §5.2](../../docs/compatibility/behaviours.md) | It carries the **only surviving `⚠️ UNVERIFIED`** in the compatibility documents, and its own text names the remedy: *"a disposable library on a server somebody owns — scanned, emptied of one series' episodes, scanned again."* The audits' A4 check reads **specifications** only, so a marker in `behaviours.md` is invisible to it |
| **A default rescan does not notice a replaced poster** | [behaviours §5.6](../../docs/compatibility/behaviours.md), and 006's owes list | *"Unmeasured from here — deciding it would mean writing into somebody's library and rescanning it"* |
| **Whether the reference's Next Up excludes a pristine specials season** | 005 §7 OQ-7, still open, and 005's owes list names 010 | It needs a library holding a series whose only unplayed episodes are season 0's. The library measured on 2026-08-28 had none |
| **The paused-session ticker freeze** | 007's owes list, [007 plan §6.8](../007-user-data-and-playstate/plan.md) | Cited from the reference's source and never measured on the wire; it costs ten minutes of deliberate silence against a paused session, which is a probe nobody wrote |

The first three are **writes into a library**, which is what the single-use instance is for, and all
four are askable the day T9 lands. **Whether they become rows of `named-comparisons.yaml` was a
scope call this list did not take**, because §3.10 is a table in an **accepted** spec and AC-16
counts it: adding rows widens an acceptance criterion, which is the shape of the decision plan §11
reserved as D-3 rather than took. It was recorded as **D-6** below, with a recommendation, and
**the recommendation was accepted on 2026-09-02**: all four are §3.10 rows now, inside AC-16's
count, and the register has no separate `outstanding` section for them.

## The decision this list reserved, taken on 2026-09-02

| # | The call | Decided |
|---|---|---|
| **D-6** | Whether the four debts above join `named-comparisons.yaml` as named comparisons, widening spec §3.10 and AC-16 from sixteen | **Yes, as four new §3.10 rows.** The spec is amended and the amendment is dated in its frontmatter the way D-3's was: §3.10 carries the four with their provenance and the reason each needs the instance, **AC-16 names twenty where it counted sixteen**, and [spec §7](spec.md#7-open-questions) records the decision. All four are differences a sweep cannot raise, which is exactly what §3.10 is for; behaviours §5.2's `⚠️` in particular is a claim this repository has carried unmeasured since it was written and can now be settled — **the marker itself stays**, because `behaviours.md` is not a specification and the reading that would discharge it has not been taken yet. The cost was one amendment to an accepted spec and four rows on a register; the cost of the alternative was a run reporting *"sixteen of sixteen"* while four questions with a written home went on being nobody's |

**Nothing in this list was waiting on a decision when it was accepted.** T5, T12 and the definition
of done are written against twenty, and the `outstanding:` section they described is gone rather
than empty.

## The decision T15 reserved on 2026-09-02, and taken by its owner the same day

| # | The call | The decision, taken 2026-09-02 |
|---|---|---|
| **D-7** | Whether **AC-2** is amended to state the comparison it turned out to be, or 010 stays open until the forty-seven differences its own measurement declares are closed by the features that own them | **Amend it, and amend nothing else — the recommendation, accepted.** AC-2 read *"both servers, pointed at the same built fixture, produce libraries with the same item count and the same structure"*, and the measurement says they produce **forty-seven declared differences** over the six libraries T11 composed — a zero-byte film that is an item there and not here (003 §3.2), twenty-five files named differently, an empty library that is nothing at all to the reference, and every library's own root row `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`. **This is not a harness defect and closing it is not 010's to do**: [spec §2](spec.md#2-scope) puts *"deciding what Atrium does about a difference this feature finds"* with the feature that owns the endpoint, and every one of the forty-seven is 003's or 004's. AC-2 was the only one of the eighteen that asserts a property of *Atrium's conformance* rather than of the harness, and it was written on 2026-08-26 before anything had been measured. **The wording it now carries is the thing that exists and runs**: *"the reference's reading of the built fixture is recorded, and Atrium's scan of the same tree is compared against it in the default job; every difference is declared with its reason and its owning feature, an undeclared difference fails, and a declared difference that has gone away fails too."* The alternative — holding 010 open — would have made this feature's status depend on work in two other features that this feature exists to **report** rather than to do, and left the harness unusable meanwhile. **`spec.md`, `plan.md`, `tasks.md`, [`specs/README.md`](../README.md), [`docs/roadmap.md`](../../docs/roadmap.md) and [AGENTS.md](../../AGENTS.md) moved together**, in the commit that took this decision; the spec's amendment is dated in its frontmatter the way D-3's and D-6's were, [spec §7](spec.md#7-open-questions) records the decision, and `tests/conformance/test_acceptance.py` already held the eighteen rows, so the flip was one line and not a task |

**D-7 is taken and 010 is `Implemented`.** That was the whole of what stood between the fifteen
tasks and the status line — and the status word says what it says here and nothing more: fifteen of
fifteen tasks done and eighteen of eighteen criteria proven. **It does not say the harness has swept
everything.** Six of the twenty named comparisons are outstanding with their owners, no `level: L3`
row has been shown to reach L3, and both are on the owes list at the end of this file.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — Reconcile the prior-measurement register before anything trusts it

- [x] **Changes:** `docs/compatibility/reference-target.md` §3. The register holds **fifteen** rows
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

> **Done (2026-09-02).** *Three rows are struck and five stay open, exactly as this task said — and
> one of the three is not the row it named.* Two of the eight open rows were read against the
> probes themselves rather than against the plan's summary of them, and both moved:
>
> - **`UserData` is returned without `Fields` was already paid, and nobody had noticed.**
>   `tools/probe_item_shapes.py` measured it at 005 T1: `UserData` present on the bare list row of
>   all nine content types and of `/UserViews`, 12 of 12 items each, with no `Fields` and no
>   `EnableUserData`, and its keys carrying `Key` and `ItemId`
>   `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`. It also **narrowed** the
>   claim, which no register row said either: a by-name row from `/Genres` carries no `UserData` at
>   all, where the same genre through `/Items?ids=` does. Struck, and 005 §3.2's cell upgraded from
>   `prior-probe` to the probe.
> - **The item-identity row is half paid, and the half that is missing is a write.**
>   `tools/probe_item_identity.py` reproduces 448 of 448 live ids from the item's own `Path`, so the
>   derivation is measured and *32 lowercase hex* follows from it by construction — but the probe
>   reads **one moment** and never sees a second scan, and *"stable across rescans"* needs a library
>   scanned twice. It stays open, named to the instance beside T10's scan, and
>   [behaviours §1.4](../../docs/compatibility/behaviours.md) keeps its `prior-probe` for that half
>   alone. **T13 therefore inherits two rows from this task and not three**: the two configuration
>   writes it already names. This one is not a configuration write and does not belong with them.
>
> *The `SortBy` row is not merely unmeasured — it is doubted, by a citation this repository already
> carries.* All eight members order rows and are honoured, `Random` included
> `[probe: tools/probe_sort_stability.py, Jellyfin 10.11.11, 2026-08-27]`, so what is open is the
> **closure** of the set; the reference's own enumeration names **thirty**
> `[source: Jellyfin.Data/Enums/ItemSortBy.cs @ v10.11.11]`, an unrecognised token is ignored rather
> than refused, and a shipping music client sends three tokens that are not among the eight. The row
> says so, and says the probe that settles it needs no writes — which makes it the cheapest of the
> five and the only one with a client waiting on it.
>
> *The register is not §3.* It is an unnumbered subsection of **§2**, *"Prior measurements, and the
> debt they carry"*; §3 is the four conformance levels. The test locates it by heading, so a
> renumbering breaks nothing and a moved heading fails `test_the_register_was_found_and_has_rows`
> rather than silently iterating over zero rows.
>
> *Struck is not the same as reproduced, and two of the three struck rows say so in their own cell.*
> The authentication row's claim was **four** mechanisms and the answer is five; the `Container`
> row's claim was *"a demuxer list"* and the answer is a list for the mp4 family and a single word
> for everything else. Both are kept with what changed, the way the PCM/WAV row already was.
>
> *A fourth test, not asked for, because the register can be wrong in the other direction too.*
> `test_every_prior_probe_citation_belongs_to_a_row_of_the_register` collects every dated
> `prior-probe` citation in the repository's Markdown — 22 of them across 14 documents, in five
> distinct dates — and fails on one whose date matches no row. That is the 2026-08-28 audit's M8
> finding, where three claims were carrying a prior measurement the register had never recorded,
> turned into something that cannot recur silently. It passes today: every date is a row.
>
> *Routine calls taken.* The four `prior-probe` cells in `api-surface-v1.md`'s mechanism table and
> the one in 005 §3.2 became `[probe:]` citations, because the register defines a discharge as *the
> citation becoming a plain `probe:`* — leaving them would have made the register's own definition
> false on the day it was reconciled. `tools/README.md`'s *"Planned"* row named `probe_item_ids.py`,
> a script this task has just established nobody needs; it names the two that are still unwritten
> and answerable, and says three of the five wait on the instance. Neither touches behaviour, and
> nothing was written to any server: every finding here came from reading the probes in this
> repository and the notes they produced.

## T2 — `tools/_differential.py`: the comparison engine, pure, in five classes

- [x] **Changes:** new `tools/_differential.py` — `Response`, `Class`, `Difference`, `Rules`,
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

> **Done (2026-09-02).** *The cascade guard, applied in the order [plan §6.2](plan.md#62-the-comparison-in-five-classes)
> writes it, deletes AC-17 on the only endpoint AC-17 was written for.* Step 1 says different
> lengths are one `LENGTH` finding and *"the array's rows are **not** compared at all"*; step 4 says
> a `drawn` array compares *"the envelope, the row count, and every row's key set and types"*.
> Those two are in conflict on the project's only measured `drawn` array, and always:
> `/Items/{itemId}/Similar` answers `limit + 4` rows on a **movie** seed where Atrium answers
> exactly `limit` — measured at 1, 5 and 20, on two seeds each
> `[probe: tools/probe_similar_ranking.py, Jellyfin 10.11.11, 2026-09-01]`,
> [behaviours §3.24](../../docs/compatibility/behaviours.md) — so the lengths differ on **every**
> run of that route, step 1 fires first, and the row walk AC-17 exists for never happens. It was
> not visible from either document because each states its half in its own paragraph. **The fix is
> T4's and the shape of it is fixed here:** a length difference suppresses the *positional*
> comparison, which is the thing that cascades, and never the shape walk a `drawn` array still
> owes. `tests/conformance/differential_pairs/drawn_array.json` is written two rows against six for
> that reason, and `test_the_cascade_guard_suppresses_the_row_walk_on_the_only_measured_drawn_array`
> asserts today's behaviour with the correction named in its own docstring, so T4 cannot land
> without meeting it.
>
> *Two more things the plan asserts that measure false, both found by making them fire rather than
> by reading.*
>
> - **The fingerprint's mask has to keep the key present and keep its type.** §6.2 says a row is
>   reduced to *"the row after the allowlist's masking, serialised canonically"*, and the natural
>   reading of masking is dropping the key. Do that, and a row where Atrium omits `Id` **entirely**
>   fingerprints identically to the reference's row that carries it: the two arrays compare equal,
>   *"nothing more is said"*, and `MISSING_KEY` — the class the report ranks first and the only
>   defect class this project cannot find any other way — is never emitted at all. Masking by
>   deletion makes `test_a_masked_field_still_reports_a_missing_key_under_a_reordering` report `[]`
>   against one expected finding. The engine masks to a marker naming the value's JSON type instead.
> - **`pointer` cannot address a single row of spec §3.3 without an array-index wildcard.** Plan
>   §4.1 defines it as *"JSON Pointer to the field or array, relative to the body"*, and every
>   field row of §3.3 — `Id`, `DateCreated`, `Etag`, `ImageTags`, `ChildCount` — lives inside a
>   **row of a list envelope**. A literal index is both unwritable across a thousand-row page and
>   wrong under a reordering, because the index moves. The engine reads RFC 6901's `-` as *"an
>   element of this array"*, and consults the mask under an index-generalised pointer so that a
>   fingerprint does not depend on where its row currently sits — without which reordering an array
>   changes the very values the ordering comparison exists to hold still. **T3 writes the entries in
>   that spelling**: `/Items/-/Id`, not `/Items/0/Id` and not `Id`.
>
> *And one finding that is T3's to fix rather than T2's.* **The `Server` header differs on every
> single response and spec §3.3 carries no row for it.** It is `Atrium/<version>` here against the
> reference's `Kestrel` `[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-28]`, recorded
> as a deliberate divergence in [behaviours §4.1](../../docs/compatibility/behaviours.md) and made
> the two-server discriminator by plan §6.12 — so until the allowlist has the entry, every case in
> the sweep reports the same header difference.
> `test_the_server_header_differs_on_every_response_and_spec_33_has_no_row_for_it` asserts that it
> is needed, by removing the excuse and counting the finding.
>
> *What T4 inherits beyond the split above.* **The equal-length, unequal-multiset array still
> cascades**, and plan §9's risk row claims otherwise: it names *"the `LENGTH` cascade guard and the
> `ORDER` class"* as the mitigation for a positional comparison drowning the report, and neither
> fires on a page whose length is unchanged and whose rows are not a permutation. That shape is
> measured, not hypothetical — paging the reference's artist sorts *"loses and duplicates rows"*
> ([behaviours §3.6](../../docs/compatibility/behaviours.md)), so a page can hold one row twice and
> another not at all at the same length. §6.2 does not say what an `unordered` array does when the
> multisets genuinely differ, and that is the question T4 answers. Relatedly, the `ORDER` note here
> counts multiplicities rather than collapsing them: a set-based answer would report a page that
> lost one row and repeated another as a pure reordering, which is the conflation this class exists
> to prevent, running backwards.
>
> *Routine calls taken, since none of them touches behaviour or an accepted document.*
> **The status is compared, inside `compare`, and a difference in it is one finding that stops
> there** — neither the task nor §6.2 mentions the status at all, while plan §7 files it as *"a
> `VALUE` difference on the status"*, singular; a `404`'s problem details walked against a `200`'s
> item body would bury the one fact that explains every other finding under fifty that do not. It is
> filed under `status`, which is neither a JSON Pointer nor a header and so cannot collide with one.
> **`json_type` separates `boolean` before `integer`**, because `bool` is a subclass of `int` in
> Python and the obvious `isinstance` ladder reports `true` and `1` as the same type — on exactly
> the flags a decoder breaks on — **and separates `integer` from `number`**, because Principle VIII
> says numeric type is part of the contract *and only visible in the serialised form*, which is
> where `0` and `0.0` differ. **A key holding an explicit `null` is present**, which is measured
> rather than tidy: the reference suppresses nulls globally and sends `ChannelId: null` on every
> item anyway, 208 of 208
> `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`. **Header names are matched
> case-insensitively and header order is not compared**, because HTTP says the first and the two
> servers are different stacks. **`raw` is never compared** — spec §6 declines to byte-compare
> produced media, and three §3.10 rows exist precisely because their difference is in the bytes.
> **A `TYPE` difference stops the walk at that node**, since a list against an object cannot be
> walked and walking anyway is a second cascade. Two helpers beyond the declared contract, `rank`
> and `counts`, because AC-5 is a property of an ordering and a report should not have to guess a
> zero; T8 consumes them. `Response`'s `headers`, `body` and `raw` and all three of `Rules`'
> mappings gained empty defaults, with a shared frozen `NO_RULES`, so a mutation case can be built
> from a status alone.
>
> *A gotcha the inherited pattern does not carry.* Loading a `tools/` module by path needs
> `sys.modules[name] = module` **before** `exec_module`: `dataclasses` resolves a field's annotation
> by looking the defining module up by name, so the first `@dataclass` raises without it. Neither
> `tests/conformance/test_routes.py` nor `test_universal_audio.py` hits this, because neither module
> they load declares one — so the pattern every later task will copy is one line short for anything
> under `tools/` that does, which is `_allowlist.py`, `_reference.py` and `differential.py`.
>
> *Nothing was written to any server, and nothing here opens a socket, reads a file or reads a
> clock.* The three guards were proven by deletion rather than by argument: remove the fingerprint
> step and the reordered thousand-row case reports **2000** findings instead of one `ORDER`; remove
> the length check and the shorter-array case reports its rows; mask by deletion and the missing key
> disappears. Every assertion is a count, so none of them can pass by accident.

## T3 — `docs/compatibility/allowlist.yaml` and `tools/_allowlist.py`: three kinds, scoped

- [x] **Changes:** new `docs/compatibility/allowlist.yaml` in the hand-written YAML subset
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

> **Done (2026-09-02).** *Writing spec §3.3's two tables into the file they describe cost four of
> their rows, and the sharpest is that one of them names nothing on the wire.* **`DateLastSaved` is
> not a property of an item body.** It is an `ItemFields` **token** — a thing a request asks for —
> and the pinned document's `BaseItemDto` carries 153 properties without it; it is likewise absent
> from `property-names.json`, this project's own extraction of all 1026 property names the
> reference uses `[spec: BaseItemDto, ItemFields]`. It has been in the wall-clock row of both prose
> copies since 010's spec was written, and an entry for it would have excused a field neither
> server can send. Withdrawn from both, and `test_datelastsaved_is_not_excused_because_it_is_not_a_property`
> is what keeps it out.
>
> *The second is that the ellipsis was hiding five identifiers.* `…` is not something a file can
> hold, so the row had to be enumerated against what Atrium actually serialises — and the
> enumeration named five the table had never listed: **`Key` and `ItemId` inside `UserData`**, which
> are both the item's own derived identity, **`ParentThumbItemId` and `ParentBackdropItemId`** on
> the rows that inherit an image, and **`PlaylistItemId`**, which 009's gate measured to *be* the
> item's `Id`. Four more come from the shapes that are not items — `ThumbImageItemId` and
> `BackdropImageItemId` on a search hint, `UserId` and `DeviceId` on a session. Fifteen names where
> the table listed seven and a full stop.
>
> *The third is that D-3's promise was already false on the day it was made.*
> [Plan §6.3](plan.md#63-the-allowlist-scoped-in-three-kinds) says conformance.md's rendering
> carries the `because` column *"so the two prose copies cannot drift apart while §6.3's file is
> being written"*. They had already drifted: **conformance.md was carrying seven of §3.3's nine
> field rows**, missing `PlaySessionId`/`AccessToken` and `TotalRecordCount` outright and
> `LastActivityDate` from the wall-clock row. Nothing read either table, which is the 2026-09-01
> audit's M1 finding exactly; `test_the_two_prose_tables_say_what_the_file_says` now reads both and
> compares them to the file, and it was proven by adding a row to the file and watching it fail.
>
> *And the fourth decides a mechanism.* **Plan §4.1's six fields cannot express two of §3.3's own
> rows**, because both are conditioned on the **request** and not on the route: `TotalRecordCount`
> *"on by-name endpoints without a limit"*, and *"the rows of any listing ordered at random"*.
> Written with six columns each is strictly wider than the prose it comes from — the first excuses
> a real count difference on every by-name request that *does* carry a limit, and the second
> excuses the rows of **every listing on every request**, which deletes L3 for the largest thing
> this harness compares. Plan §6.3's own resolver signature is `resolve(endpoint, case, identity)`,
> so the dimension was already promised and only the column was missing. **A seventh field, `case`,
> is the routine call taken**: it only ever narrows — `*` is what an entry with no condition says,
> and an id no case declares matches nothing, so its failure direction is under-excusing. **T6 owes
> three ids**: `by-name-without-limit`, `listing-ordered-at-random` and
> `listing-ordered-by-a-key-with-ties`. Until `request-cases.yaml` declares them those three
> entries excuse nothing, which is the safe half of being wrong.
>
> *T2's owed row is written, and it grew a second header.* `header:Server` is in, on `*`
> (behaviours §4.1) — `Atrium/<version>` against `Kestrel`
> `[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-28]`, a difference on every response
> of every case. Beside it, §3.3's *"and the response clock"* is now spelled `Date`, because a
> pointer is a name and a file cannot excuse a phrase.
>
> *Routine calls taken, none of which touches behaviour.* **`ETag` joins `Etag`**: a media source
> spells it with the uppercase T the reference gives it and the item property does not, so one name
> would have left the other compared. **`ChannelId` is deliberately not excused** although it is
> uuid-typed on both schemas — it is an explicit `null` on every item of every response, 208 of 208
> `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`, so excusing it would hide
> the day one server stopped sending it, and a missing key is the class the report ranks first;
> `test_no_entry_excuses_a_key_that_is_measured_identical_on_both_servers` holds it out.
> **`identity` is accepted by `resolve` and selects nothing**, said in the docstring and asserted
> rather than left to be discovered: no row of §3.3 is conditioned on who asked, and spec §3.9's
> twelve differing reads are *findings*, not excuses. **85 entries**, and `*` is used only where a
> pointer is precise enough to carry the scoping on its own — `ChildCount`, `TotalRecordCount` and
> `LocalAddress` name their endpoints, and the first of those is the test that would fail if the
> column were dropped.
>
> *What T4 and T8 inherit.* **§3.24 and AC-17 collide, and no allowlist row can settle it.**
> `Similar` answers `limit + 4` rows on a movie seed (behaviours §3.24) while AC-17 says a `drawn`
> array's **row count** is still compared — so that count differs on every single run of the one
> endpoint the `drawn` kind exists for, and the entry cannot say *"excuse the count, keep the
> shape"* without becoming the over-excusing this file is written against. T4 decides whether that
> is a permanently reported known divergence or an exception AC-17 owes. And **the sweep will
> report differences no row covers, which is the design and not a gap**: `/System/Info`'s seven
> installation paths (`ProgramDataPath`, `WebPath`, `ItemsByNamePath`, `CachePath`, `LogPath`,
> `InternalMetadataPath`, `TranscodingTempPath`), `ServerName` — an operator setting T9's instance
> can simply be given to match — `SupportsLibraryMonitor`, `LastLoginDate`, `LastPlaybackCheckIn`,
> and `DELETE /Items/{itemId}`'s `403` (behaviours §4.3). Each is §3.4's triage, and adding an
> entry for any of them is a contract decision made in review rather than by the task that first
> saw it red.
>
> *Nothing was written to any server, and nothing here opens a socket or reads a clock.* Every
> claim above came from the pinned OpenAPI document, `property-names.json`, this repository's own
> serialisation code and the probes already recorded. Both AC-6 tests construct the bad entry and
> assert the loader raises; the scoping test was proven by widening the `ChildCount` entry to `*`
> and watching it fail; the prose test by adding a row the tables do not have.

## T4 — The excused arrays, and an ordering that is not total

- [x] **Changes:** `tools/_differential.py` gains the two array kinds `Rules` already declares:
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

> **Done (2026-09-02).** *The decision T3 handed over is taken: the row count stays compared, no
> acceptance criterion is amended, and `Similar`'s `limit + 4` is a difference the report states on
> every run.* §3.24 and AC-17 collide on the one endpoint the `drawn` kind exists for — the
> reference answers `limit + 4` rows on a movie seed where Atrium answers exactly `limit`, measured
> at 1, 5 and 20 on two seeds each
> `[probe: tools/probe_similar_ranking.py, Jellyfin 10.11.11, 2026-09-01]` — so the count differs
> always. It is reported always, for three reasons. **The count is the last thing L3 can check
> there:** a drawn array's rows are excused by construction, so excusing the count too would leave
> the endpoint with nothing measured at all, and a run that compared nothing would report clean.
> **The entry could not be written narrowly:** *"excuse the count, keep the shape"* is not
> something a pointer says, and the widest reading of an array entry is the over-excusing
> `allowlist.yaml` is written against. **And a repeated known divergence is a regression check**,
> not noise: the line says `2 against 6` beside behaviours §3.24 every run, and it stops saying it
> the day the surplus stops being exactly four or Atrium's own count moves. The alternative reading
> — an AC-17 exception — would amend an accepted criterion to buy a quieter report, and this one
> did not need it. Recorded in [conformance.md](../../docs/compatibility/conformance.md#l3--differential)
> and in `allowlist.yaml`'s own comment, where the fourth entry would otherwise be written.
>
> *The finding is that a `drawn` array's shape walk cannot be positional, and the plan's own
> sentence for it says otherwise.* Plan §6.2 step 4 says *"the rows are still walked"*, which reads
> as row 0 against row 0. Do that and the walk reports **content as shape**: a null property is
> absent everywhere by one setting on both servers
> ([behaviours §1.7](../../docs/compatibility/behaviours.md)), so a row's key set depends on which
> item it holds — an item with no production year simply has no `ProductionYear` — and a *draw*
> guarantees the two sides hold different items (behaviours §3.23: four identical requests shared
> **none**). Measured on the two-row case now in the suite, the positional reading reports one
> `MISSING_KEY` and one `EXTRA_KEY` about nothing at all, on an array where every row is
> legitimately a different film. The rows are reduced instead to one map of *generalised pointer →
> the JSON types seen there across every row*, and the two maps compared;
> `test_a_drawn_arrays_shape_walk_is_position_free_because_a_draw_holds_other_items` is what holds
> it, and it fails under the obvious implementation rather than under a deleted guard.
>
> *T2's split is landed, and the ordering question it left open is answered.* A length difference
> suppresses the **positional** comparison and nothing else — `drawn` still walks the shape,
> `unordered` still compares the multiset — which is what keeps AC-17 alive on the one endpoint it
> was written for. And **plan §6.2 did not say what an `unordered` array does when the multisets
> genuinely differ**, while [plan §9's risk row](plan.md#9-risks) claimed the `LENGTH` guard and the
> `ORDER` class covered it: neither fires on a page whose length is unchanged and whose rows are not
> a permutation, which is exactly what paging the reference's artist sorts produces — one row twice
> and another lost, at the same length
> ([behaviours §3.6](../../docs/compatibility/behaviours.md)). **The answer: the rows that match are
> removed and only the residue is aligned and compared.** On the measured shape that is 2 findings
> where the positional fallback reports **10**, asserted as a count. Pairing rows arbitrarily is
> legitimate only under an `unordered` entry, which is a written statement that this array has no
> ordering to lose; an ordinary array keeps its index alignment on purpose, because matching equal
> rows across positions would silently discard the ordering the sweep is testing — plan §9's row now
> says so rather than claiming a mitigation it does not have.
>
> *And the second cascade arrives through the door the first one was shut on.* The shape walk emits
> one finding per differing pointer, so a row that lost a whole `UserData` object reported one
> `MISSING_KEY` per property inside it, and a `Genres` of objects against a `Genres` of strings
> reported the type difference **and** a key inside the object it could not have. A difference at a
> node now prunes its own subtree, which is what `_walk` already did with a `TYPE` and
> `_walk_object` with a missing key — found by writing the nested-array case, not by reading.
>
> *Routine calls taken, none of which touches an accepted document.* **The presence of *an element
> of* a nested array is not compared**, only its type: the pointer `/Items/-/Genres/-` exists on a
> side only because some row held a non-empty array, and one film having three genres where another
> has none is content, not shape. **An empty array has no shape**, so a `drawn` array that is empty
> on one side reports its count and stops, rather than reporting every key of every row as missing
> on an endpoint whose emptiness is a draw's own outcome. **`drawn` outranks `unordered`** where an
> entry of each covers one array, since having no comparable values is strictly more than having no
> comparable order. **An `unordered` array of a different length still reports one `LENGTH`**, with
> a note counting the rows that matched nothing on either side — a lost row is a real difference and
> a multiset needs no alignment to find it. And **no `zip`**: its `strict=` is 3.10 and `tools/` is
> on the 3.9 floor (D-2), where the existing `strict=False` in `probe_sidecar_subtitles.py` would
> raise if that line were ever reached.
>
> *Nothing was written to any server, and nothing here opens a socket, reads a file or reads a
> clock.* The allowlist needed no new row: T3 had already written all three arrays of spec §3.3 into
> the file, so this task is the engine that honours them. Both guards were proven by deletion —
> remove the shape walk and three `drawn` assertions fail, including AC-17's own mutation row;
> remove the residue and the artist-paging page reports 10 findings instead of 2 — and every
> assertion is a count.
>
> *What T5, T6 and T8 inherit.* **Two of the three array entries are keyed on a request case that
> does not exist yet**, so AC-18 is proven in the engine and excuses nothing on the wire until T6
> declares `listing-ordered-at-random` and `listing-ordered-by-a-key-with-ties` (with
> `by-name-without-limit`, T3's third). Until then a sweep of any listing compares its rows by
> position, which is the safe half of being wrong and is *not* a green run: it is findings nobody
> excused. **T8 must resolve the rules per `(endpoint, case)` and not per endpoint**, or those two
> entries are unreachable no matter what T6 declares. And the report should print an excused array's
> `LENGTH` beside its reason: on `Similar` that line is permanent, and a reader who does not see
> behaviours §3.24 next to it will try to fix it.

## T5 — `docs/compatibility/named-comparisons.yaml`: twenty rows, and what each needs

- [x] **Changes:** new `docs/compatibility/named-comparisons.yaml` — one row per row of spec §3.10,
  **twenty of them since D-6**, each with `id`, `what`, `why_the_sweep_misses_it`, `needs`
  (`identity:restricted`, `identity:playback-denied`, `fixture`, `rescan`, `wait`, `latency`,
  `bytes`, `twice`, `owned-seat`), `behaviours` and `runner`,
  which is `none` until the task that writes it. **`needs` is the field that earns the file**: it is
  what lets a report say *"four outstanding, and three of them because no fixture instance was
  available"*, and what a run consults to decide whether a row is even askable before it counts it
  as a miss. **There is no `outstanding:` section**: the four readings of *"What the gate changed"*
  §3 are ordinary rows of the register, because D-6 was taken on 2026-09-02 and put them inside
  AC-16's count rather than beside it. `tests/unit/test_allowlist.py` gains the register's
  assertions.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_allowlist.py -q`.
  `test_the_register_is_spec_310s_table` parses spec §3.10's rows and asserts the ids cover them
  one for one, so a row deleted from either side fails; `test_every_row_names_a_behaviours_section_that_exists`
  resolves each `behaviours` value against the anchors in `behaviours.md` and fails on a section
  that is not there — which is 006 T3's finding (a task citing an exception withdrawn three features
  earlier) turned into a check; and `test_the_register_counts_twenty` asserts AC-16's count reads
  **twenty** and that each of D-6's four rows is present by id, so a register that quietly dropped
  one of them back out of the count fails.
- **Spec reference:** §3.10, §4, AC-16; plan §4.2, §6.4

> **Done (2026-09-02).** *Writing spec §3.10's table into a file cost the register a field, because
> the field the plan named cannot be filled on a quarter of the rows.* [Plan §4.2](plan.md#42-docscompatibilitynamed-comparisonsyaml)
> gives every row a `behaviours` — *"the section that is the answer"* — and **five of the twenty
> have no behaviours.md entry at all**: the image track's latency, the media source with no runtime
> and the zero-length cue beside it, EXIF orientation on resize, 005's OQ-7, and the paused-session
> ticker. That is not an oversight in `behaviours.md`; it is what that document is. An entry there
> records **what the reference does**, and nobody has watched the reference do any of these — which
> is the same sentence as *"a sweep cannot raise it"*, seen from the other document. Four more are
> answered by a **row of behaviours §5's table** rather than by a numbered subsection, and those
> rows carry no anchor of their own, so they cite the chapter and let `what` say which row. So
> `behaviours` takes `none`, and the routine call taken is a **seventh field, `written_at`** — the
> document this row was collected from — which is T3's `case` in a different shape: the six columns
> could not state something true of every row, and the file would otherwise have carried five rows
> pointing nowhere. It is the checked half, too: `test_every_row_names_a_document_of_this_repository_that_exists`
> resolves all twenty and fails on a path that is not a file, which is the AGENTS.md rule that a
> citation never names a path outside this repository, made unable to rot.
>
> *And `written_at` measured something the task statement did not ask.* **Nineteen of the twenty
> came from one of the six inherited lists, and behaviours §5.2 came from none of them** — it is
> the one row collected from the compatibility documents alone, which is exactly what *"What the
> gate changed"* §3 meant by *"the six lists **and** the compatibility documents"* and is why D-6
> existed at all. The test asserts both halves: every one of the six lists is cited by at least one
> row, and the only other document cited is `behaviours.md`.
>
> *The second finding is that `needs` has no value for two of the twenty, and an empty list is a
> value rather than an absence.* Plan §4.2's eight tokens describe eighteen rows. The last two of
> §3.10 — the `"$"` message and the four unmeasured content-type refusals — are *"here to be
> recognised, not discovered"*: [plan §6.4](plan.md#64-the-named-comparisons) makes them ordinary
> request cases with a register row pointing at them, so they need no seat, no fixture, no wait and
> no second run. They are still inside AC-16's count, so a loader that read `[]` as a missing field
> would have dropped two rows out of the twenty on the day the register was first read.
> `check_named` therefore refuses a **missing** `needs` and accepts an **empty** one, and
> `test_an_empty_needs_is_a_value_and_a_missing_one_is_not` names the two rows.
>
> *The third is that a row's runner shape and a row's `needs` do not partition the same way, and
> only one of them is what a run reads.* Plan §6.4 files **the entries a reader cannot reach**
> under *a second seat*, with the named reader and the delivery-time refusal. It needs the seat and
> it also needs the **fixture**: what the reference hides there is hidden by a parental-rating
> check and never by library access ([behaviours §3.17](../../docs/compatibility/behaviours.md)),
> so the comparison only says anything against *a playlist holding items from two libraries* — which
> is one of the five entries [spec §3.1](spec.md) already owes the fixture, for this row. It is the
> only row of the twenty whose `needs` crosses its shape, and the two seat rows beside it are
> asserted by name in `test_the_two_rows_the_second_seat_is_the_whole_signal_for_declare_it`,
> because they are the reason this register exists: both are invisible to a run that authenticates
> the way every probe in this repository did before 2026-09-01.
>
> *Checked against what was measured rather than against the prose that collected it, which is what
> T3 found the hard way.* All twenty `what` cells reproduce spec §3.10 row for row **and in its
> order**, asserted as an ordered list; every behaviours section cited resolves against a heading of
> `behaviours.md`; and the two sharpest rows say what their entries say — §3.16's divergence is
> visible only to a restricted non-administrator because an administrator lacks no permission, and
> §3.17's is invisible to two servers whose test user can open everything. Nothing moved: unlike
> §3.3's two tables, §3.10's twenty survived being written into a file unchanged. What did not
> survive was the *shape* the plan gave them.
>
> *Routine calls taken, none of which touches an accepted document.* **The reader is in
> `tools/_allowlist.py` and not in a module of its own**, because [plan §3](plan.md#3-modules) puts
> it there — *"reads `docs/compatibility/allowlist.yaml` **and the named-comparison register**"* —
> and the two-regex parser was generalised into one `_parse_block(text, block, first_field)` so the
> two registers cannot end up read by two subsets of one format. **A second `because`-shaped regex,
> wider by one shape:** a register row may cite a whole chapter and an allowlist entry may not,
> because `behaviours §5` is a real answer here and would be an excuse that cites nothing there.
> **`test_both_registers_are_valid_yaml`**, over both files: the tools read them with two regexes
> and no dependency, which cannot tell a quoting mistake from a value, and a hand-written subset
> nothing else ever parses would keep one for ever. And **the L3 section of
> [conformance.md](../../docs/compatibility/conformance.md) now names the file** beside the
> allowlist it already named, with what `needs` buys a report.
>
> *Nothing was written to any server, and nothing here opens a socket or reads a clock.* Every one
> of the twenty rows came from spec §3.10, the six inherited lists and the behaviours entries they
> cite. The three gates were proven by breaking them: delete a row and the register stops being
> §3.10's table; point a `behaviours` at §5.99 and the section test fails; point a `written_at` at
> a file that is not there and the twenty stop resolving. The loader runs on the 3.9 floor, checked
> under `python3.9` and not inferred.
>
> *What T6 must know.* **T4's inheritance is unchanged and is now beside a second file that also
> waits on it**: `listing-ordered-at-random`, `listing-ordered-by-a-key-with-ties` and
> `by-name-without-limit` are still undeclared, so two of the three array entries excuse nothing on
> the wire. **A register id is not a request-case id**, and the two vocabularies must not be
> confused — but the last two rows of this register *are* request cases T6 owes: a malformed body,
> and a body with no content type on the **four** of the five routes nobody has asked (009 T13
> measured the fifth). And the eight `needs` tokens are what a case's `identities` must be able to
> satisfy: two seats, not one.

## T6 — `docs/compatibility/request-cases.yaml`: the eight L3 rows first, then the surface

- [x] **Changes:** new `docs/compatibility/request-cases.yaml` — per endpoint, a name, the query,
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

> **Done (2026-09-02).** *The register is 84 cases over all 59 endpoints, 23 of them on the eight
> `level: L3` rows, and the first finding is that the file cannot be seeded the way the plan says
> it is.*
>
> **84 was true on the day and is not a count of the file any more, which the owes list repeating
> it did not notice** (reconciled 2026-09-03, on the first complete sweep, which found the two
> numbers disagreeing): T11 added `the-planted-film` and `the-subtitled-film` — the two listings
> that name a fixture film by name, without which five anchors named the wrong film — taking it to
> **86**, and the anchor fix of 2026-09-03 added `no-body-on-the-subtitled-film`, taking it to
> **87**. Nothing was lost and nothing is missing; the count in this note is T6's file and every
> later count is a later file. `git log --follow docs/compatibility/request-cases.yaml` is the
> whole of the reconciliation.
>
> [Plan §4.3](plan.md#43-docscompatibilityrequest-casesyaml) says the file starts at the
> floor *"plus the cases the two analysed clients actually send"*. **Neither client document
> carries a request inventory, by policy and in the same words**: `client-atrium-tvos.md` §7 and
> `client-embeat-mobile.md` §8 each say the document *"does not become a second endpoint table"*,
> and neither cites a line of its client's source, because AGENTS.md forbids naming a path outside
> this repository. The video client's thirty operations are a **four-row count table** and the
> music client's a six-row one; `limit`, `recursive`, `startIndex`, `parentId`,
> `includeItemTypes`, `enableImages` and `sortOrder` appear **nowhere** in either file, and fifteen
> endpoints of the surface are not named in either. What the two documents *do* give is about a
> dozen concrete strings, and every one of them is a case here: the `{Username, Pw}` body,
> `Fields=MediaSources` *"on six listing routes"*, `SearchTerm=` instead of `/Search/Hints`,
> `static=true` on both stream routes, the capped FLAC with `AudioSampleRate=48000`, universal's
> progressive MP3 under a deterministic `PlaySessionId`, `quality=90` on every image, the
> lower-case `Stream.vtt`, `GET /Sessions?deviceId=` — a parameter neither server's route declares
> — the by-name routes with **no** `Limit`, and the rename body that must carry `Genres`, `Tags`
> and `ProviderIds`. The rest of the file is AC-3's floor and OQ-2's growth rule, which is what
> those two say it should be; what is not true is that a fuller seed was available and skipped.
>
> *The finding that cost the most is that plan §6.1.1's anchor is one kind and this file needs
> three.* A `listing:` anchor — a declared listing case and a row position — fills **32** of the
> file's 55 anchors and cannot fill the other 23. **`response:`** is the second: a created
> playlist's `Id` and a negotiated media source's `Id` are carried by a *response* and by no
> listing at all, which is five routes. **`literal:`** is the third and the one that looks like a
> shortcut: `{container}`, `{routeFormat}`, `{imageType}`, `{imageIndex}` and `{newIndex}` **do not
> name items**, so no listing and no response can supply them, and with only the plan's kind five
> more routes were unaskable. Plan §4.3 now carries all three, with the three fields T6 added —
> `content_type`, `needs` and `what_it_is_for` — and `content_type` is the one that earns its
> place: **a body with no `Content-Type` is not a query, not a body and not an identity**, and it
> is one of the two register rows plan §6.4 makes an ordinary request case.
>
> *The third came from reading the routes rather than the documents, and it moves the floor on
> three endpoints.* **Three routes have a required query parameter**, so a bare request there is
> the framework's problem details on both servers and AC-3's floor case would have compared a
> refusal and counted it as coverage: `searchTerm` on `GET /Search/Hints`, `deviceId` **and**
> `playSessionId` on `DELETE /Videos/ActiveEncodings` — where `deviceId` is read by nothing and
> declared anyway, so *"a route that took only what it uses would answer `204` to a call the
> reference refuses"* — and `segmentLength` on the subtitle playlist, which the reference marks
> required. Their floor cases carry the parameters.
>
> *The fourth is two shapes the plan's `Case` cannot express, and neither is a path parameter.* An
> **item id in a body** (007's three reporting routes) and an **item id in a query** (`ids` and
> `entryIds` on the playlist add and remove) are exactly as unfillable as an unanchored path
> parameter and have no field to say so, because an anchor fills a path parameter by construction.
> All four now carry `needs: [fixture]` with the reason written down. They were written first with
> a **placeholder** — the identity's own user id standing in for an item id — which would have
> compared two `404`s on every run and looked like coverage; that is the same shape as 006 T5's
> hostile-path test passing with the check deleted, and it was removed rather than kept.
>
> *And the fifth is a limitation this task did not fix and is not hiding.* **A case id is unique
> per endpoint and shared across endpoints on purpose** — that is what lets one allowlist entry
> keyed on a case id cover a family, `by-name-without-limit` across five endpoints and `static`
> across two stream routes. The cost is that one endpoint holds **one case per condition**, and
> `GET /Items` has two requests that meet the same condition: the artist sort, which behaviours
> §3.6 measured losing and duplicating rows across pages, and the **music client's year sort** —
> `SortBy=Year` goes on the wire as `ProductionYear,PremiereDate,SortName`, of which only
> `PremiereDate,SortName` is in the vocabulary, over albums that mostly have no premiere date.
> `listing-ordered-by-a-key-with-ties` is spent on the artist sort, because an excuse should point
> at the request its `because` was measured on. **The year sort is therefore not declared**:
> declaring it under a second id would ship a tie-prone case with no entry to excuse it, reporting
> row-order noise on every single run, which spec §6 says is how a harness stops being read by the
> second week. It is written here rather than shipped, and it is the first thing a fourth case id
> on that endpoint would resolve.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **The substitution
> vocabulary is delimited by angle brackets and not braces**, found by loading the file: `{...}` is
> what a path parameter uses *and* what a JSON object uses, so the first load rejected the video
> client's own `DeviceProfile` as an undeclared token. **`identities` empty means every seat**, per
> plan §5, and the shipped file names them anyway — the failure this feature is prone to is a case
> set naming one seat, so the value that says nothing has to mean all of them and never the first.
> **Every case that changes an account, or reads what one changed, names the created seat alone**
> — fifteen endpoints — because the administrator's seat is whatever `.env` points at, which
> before T9 is an operator's own; spec §3.5 asks a writing probe to clean up after itself and this
> asks the sweep not to write there at all. The one exception is the rename, which the reference
> declares administrator-only. **`_parse_block` now strips a matched pair of quotes** rather than
> one character off either end, because a JSON body makes a single-quoted YAML scalar the only
> spelling both readers agree on — and `test_the_three_registers_are_valid_yaml` earned itself
> immediately, catching that `{itemId}` inside an **unquoted** flow sequence is a YAML flow
> *mapping* while the two-regex reader saw a string.
>
> *Nothing was written to any server, and nothing here opens a socket or reads a clock.* Every
> query and body came from the two client documents, the pinned OpenAPI document's own spellings
> and this repository's route signatures, read rather than assumed. The three gates were proven by
> breaking them: an anchor over `listing-ordered-at-random` is refused and the same anchor over
> `movies-by-sort-name` is not; a path parameter with no anchor and no `fixture` fails; a second
> case with one id on one endpoint fails. `test_every_surface_endpoint_has_at_least_one_case`
> reads the surface through `extract_v1_surface.py`'s own `parse_surface`, and
> `test_every_l3_row_has_a_case_for_every_identity_it_is_meaningful_for` fails on any of the eight
> with one seat.
>
> *What T7 must know.* **The three ids T3 and T4 owed are declared and their entries now excuse
> something on the wire**: `by-name-without-limit` on all five by-name endpoints,
> `listing-ordered-at-random` and `listing-ordered-by-a-key-with-ties` on `GET /Items`. **The seat
> names are `ROLES` in `tools/_allowlist.py`** — `administrator`, `restricted`, `playback-denied`
> — and 84 cases are written against those three strings, so `differential.Role`'s values must be
> exactly them. **No sweep case names `playback-denied`**: that seat belongs to the named
> comparison behaviours §2.21 owns, and a sweep case naming it would run a §3.10 row under another
> name and let a run count it as swept. And `identities_for(roster)` is what T8's loop calls — the
> case decides which seats it is meaningful for, out of the ones the run actually has, so a
> one-identity run is a shorter loop and never a different code path.

## T7 — The identities a run authenticates as, created and destroyed by the run

- [x] **Changes:** `tools/differential.py` gains `Role`, `Identity` and the seat lifecycle of
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

> **Done (2026-09-02).** *The seats are in, the pre-flight refuses, the teardown is a test rather
> than a docstring — and the finding is that this task's own plan row names the wrong permission,
> in the one seat whose whole purpose is to have a permission denied.*
>
> [Plan §6.7](plan.md#67-identities) asks for `playback-denied` as *"the same, with the
> playback-processing permission denied"*, singular. There are **three**, and there is a fourth
> whose name reads like the one and which is inert.
> [Behaviours §2.21](../../docs/compatibility/behaviours.md) has measured all of it and nobody had
> read it against this row: `EnableMediaPlayback` is consulted by **no** playback route on either
> server — its only readers are the item DTO's `PlayAccess` property and the remote-control `Play`
> command — so a seat built by denying the permission whose name says *playback* plays exactly as a
> permitted one does, and the §3.10 comparison this seat exists for
> (`delivery-time-policy-refusal`) would have compared two identical answers and reported parity.
> The same entry decides how many to deny: at negotiation the three are **one gate**,
> `SupportsTranscoding` dropping to `false` only when `EnableVideoPlaybackTranscoding`,
> `EnableAudioPlaybackTranscoding` **and** `EnablePlaybackRemuxing` are all denied, with any single
> denial changing nothing; at delivery two of them are read **per stream** and only from a video
> request. So the seat denies all three — the only shape in which it is observably denied at both
> ends — and leaves `EnableMediaPlayback` alone, because denying it as well would move `PlayAccess`
> on every item body the sweep compares: a difference nobody argued for, arriving from the seat
> that exists to measure one. Plan §6.7's row is corrected in this commit and carries the
> reasoning.
>
> *The second finding is one line further down the same row, and it decides how a seat is built at
> all.* `POST /Users/{userId}/Policy` takes a **whole** `UserPolicy`, of which exactly two of its
> forty-four properties are required — `AuthenticationProviderId` and `PasswordResetProviderId`
> `[spec: UpdateUserPolicy, UserPolicy]`. A body naming only the fields a seat narrows is therefore
> not a patch: it is a complete policy in which every other property is whatever an absent value
> binds to, and the seat would differ from a stock account in ways nobody chose and no report could
> explain. The seat is built by reading the account's own policy and mutating it — which is what
> `tools/probe_restricted_surface.py` already does and what the plan's *"narrowing `EnabledFolders`
> to one library"* does not say. `test_the_restricted_seat_is_narrowed_from_its_own_policy_and_not_from_a_fresh_object`
> asserts a property nobody touched survives, and fails when the read is dropped. And the
> **denied** seat's folders are deliberately **not** narrowed: its comparison is a delivery of a
> video item, so a seat that could not open one would answer the same refusal on both servers for
> the wrong reason — 006 T5's hostile-path test, in this feature's shape.
>
> *The third is the pre-flight's own request.* `GET /Users` takes `isHidden` and `isDisabled` as
> **optional filters** `[spec: GetUsers]`, and the leftover most likely to be sitting there is the
> one an earlier run disabled instead of deleting — so the listing is asked for bare, and
> `test_the_pre_flight_asks_for_every_user_and_not_a_filtered_page` asserts the call is exactly
> `GET /Users`. The refusal names the account **and its identifier**, because the operator's next
> action is to look at it and decide whether a run is in flight or a killed one left it.
>
> *And the fourth is that "a run that cannot seat its identities refuses" needed three refusals,
> not one.* AC-15's is the seat already present. The other two are a seat that cannot be **made** —
> no library for the restricted reader, no way to sign a created seat in — which now refuses
> **before anything is contacted**, and a seat whose policy the server declines, which stops the
> run and deletes the account it had already created. The half-made account is the interesting
> one: an account created and not narrowed is an *ordinary* account, so a run that carried on would
> have swept as a second administrator and reported parity it never measured, and the next run's
> pre-flight would have refused on the leftover.
>
> *The cleanup is proven the way this repository proves a guard.* Every one of the six guards was
> deleted in turn and the suite was re-run: the pre-flight, the teardown, the `Role` values, the
> three-permission denial, the policy read, and the destruction of a half-made seat each have
> exactly one failing test. The teardown attempts **every** seat even after one attempt fails, and
> the two paths differ on purpose: a leak on the success path is **raised**, and a leak on the
> exception path is printed to stderr, because a teardown that replaced the exception already on
> its way out would hide why the run stopped. That is the 28-playlist lesson — the cleanup those
> probes each promised in their own docstring — asserted rather than promised.
>
> *What cannot be proven until T9 exists, stated plainly.* **Nothing was written to any server.**
> The only reachable Jellyfin is an operator's production instance, and creating and destroying
> users is a write; T9's single-use instance is what makes any of this measurable. So every claim
> here about the wire is from the pinned document or from an existing behaviours entry, and these
> six are **unmeasured**: that `POST /Users/New` answers `200` with an `Id` for an administrator
> `[spec: CreateUserByName]`; that `POST /Users/{userId}/Policy` answers `204` and that the
> narrowed policy takes `[spec: UpdateUserPolicy]`; that a bare `GET /Users` really does list a
> **disabled** leftover; that a freshly created seat can authenticate immediately under
> `POST /Users/AuthenticateByName`; that the wizard's first user on an instance is the
> administrator this roster is handed (plan §6.5 flags the same assumption); and that the three
> denials are observable on both servers in the shape behaviours §2.21 predicts, which is the
> named comparison T12 runs and not this task. The lifecycle is written against a client rather
> than a base URL precisely so that all six become one substitution when T9 lands — and so that
> the suite can drive it with a stub, since a test that opened a socket would fail the no-network
> guard by design.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **The seat names
> are `atrium-differential-restricted` and `atrium-differential-playback-denied`**, fixed and
> distinct from `probe_restricted_surface.py`'s `atrium-probe-restricted-surface`: fixed is the
> property the pre-flight needs, and distinct is what stops a probe run and a harness run refusing
> each other. **`Identity` keeps plan §5's four fields** and does not gain a username — the account
> name is `seat_name(role)` and adding a field would widen a contract T8 is written against.
> **The module has a `--help` and no sweep**: CI runs `--help` on every non-underscore script in
> `tools/` at both ends of the 3.9–3.14 range, so a file that exists must start, and running it
> exits `2` saying the run loop is T8's. `tools/README.md`'s *Planned* row is left alone, because
> what it promises — the command line — is what T8 lands. Verified under **3.9.6** and **3.9.25**:
> compiles, and `--help` reaches no server and reads no credentials.
>
> *What T8 must know.* **`Roster.names` is what `case.identities_for` takes** — a tuple of role
> values in the roster's own order — so `for identity in roster` over a one-seat roster is a
> shorter loop and never a different path, and `test_a_one_identity_run_is_a_shorter_loop_and_not_a_different_code_path`
> asserts exactly that against a real `RequestCase`. **`Role`'s values are asserted equal to
> `_allowlist.ROLES`**, so the 84 cases T6 wrote cannot be silently narrowed by a rename.
> **The roster is entered inside the reference instance's context, not beside it**, so the seats
> are destroyed before the instance is. **`differential.py` imports nothing from `tools/` at module
> scope** — `_probe` is imported inside `sign_in_against`, so loading the module by path costs no
> socket and no credential — and the suite's loader puts `tools/` on `sys.path` for the modules
> that do. And **the administrator is handed in, never created**: `created_by_the_run` is `False`
> for it, which is the only thing keeping a teardown that iterates identities away from somebody's
> real account.

## T8 — `tools/differential.py`: the CLI `conformance.md` already publishes, and the report

- [x] **Changes:** new `tools/differential.py` with the invocation
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

> **Done (2026-09-02).** *The finding is in the first line of the loop: **an identity is an
> account, and the two servers share none**, so a run holds two rosters and not one.*
> [Plan §6.1](plan.md#61-the-run) says *"resolve identities"* and [§5](plan.md#5-contracts) hands
> the loop one `Identity` per iteration — and `Roster` takes **one** client, because T7 built it
> against one server. A restricted reader is `POST /Users/New` on a server; the reader that exists
> on the reference does not exist on Atrium, its token is not valid there, its `user_id` is not
> the same string, and the library it is narrowed to is that server's own. So the loop's unit is
> the **role**, a `Seat` holds the two accounts behind it, and `{userId}` in a path resolves to a
> different identifier per side — which is plan §6.1.1's *"`userId` is the identity's own"* turning
> out to mean two things at once. Both rosters are entered together and the seats die before
> anything that holds them, which is T7's ordering rule generalised. §5 and §6.1 carry it.
>
> *The second is that `is_clean()` needed a third condition, and without it this feature's own
> characteristic failure is one flag away.* Spec §3.4 names two — an untriaged difference, an unrun
> named comparison — and both say *a question was not answered*. **A declared request case the run
> could not issue says a question was not asked**, which is strictly worse and looks identical in a
> summary of zeros. It is not a corner and the number is a property of the registers rather than of
> a server: **12 of the 84 cases declare `needs: fixture`**, on twelve distinct endpoints — every
> image and subtitle route whose anchor wants a kind of item no reachable library has — and **10 of
> the 20 named rows need the instance too**. Driven end to end over a stubbed pair with the two
> default seats, that is 21 unasked comparisons across 15 distinct cases; a run that called itself
> clean over those would be reporting the absence of the questions it skipped.
> `test_a_case_that_could_not_be_issued_is_not_a_case_that_agreed` fails when the condition is
> deleted, as do the other two halves when theirs are.
>
> *The third cost a client.* **`tools/_probe.py`'s `Server` cannot issue one of the two register
> rows plan §6.4 makes an ordinary request case.** `urllib.request` inserts
> `Content-type: application/x-www-form-urlencoded` into any request that carries a body and names
> no type — `AbstractHTTPHandler.do_request_`, read in the 3.9 standard library this floor runs on
> — so `body-with-no-content-type` and the four cases T6 wrote for it are **unissuable** through
> `urllib`, whatever the caller asks for. The harness's wire is `http.client`, which sends the
> headers it is given and nothing else; `_probe.py` is untouched, which is what
> [plan §9's](plan.md#9-risks) last risk row asks for while the probe-cleanup fix is in flight, and
> the finding is now [§6.12 finding 2](plan.md#612-what-this-plan-measured-and-what-came-back-false).
>
> *The fourth is one field short of a case that cannot run at all.* `POST /Users/AuthenticateByName`
> is the second of the eight `level: L3` rows, its body **is** the seat's own credentials through
> T6's `<identity.password>`, and T7's `Identity` keeps plan §5's four fields — deliberately, *"a
> field would widen a contract T8 is written against"*. The password is the **roster's**: it
> generated one per seat and threw it away. `Roster` now keeps it and hands it back through
> `credentials_for`, which widens nothing on the wire and nothing in `Identity`; the administrator
> has none, so that case is reported **unreachable with the reason** rather than sent with the
> literal text `<identity.password>` in its body.
>
> *And the fifth is the one that would have made the report unreadable by the second week.*
> Comparing every header on every response reports a **`Content-Length` difference on every JSON
> body**, because the two bodies legitimately differ in length wherever an identifier does — the
> cascade the `LENGTH` class exists to prevent, arriving through a door nobody had shut, on every
> case of every run. Spec §3.2's *"headers are compared too, on the delivery routes"* is therefore
> load-bearing and not a scope note: the whole header set is compared where the body is **not
> JSON**, which is exactly where `Content-Length`, `Accept-Ranges`, `Content-Range` and
> `Content-Type` are the contract, and elsewhere the content type alone — because 008 T16's finding
> was a declared content type that serialised differently. Plan §6.2 says so now.
>
> **What a reader of the report may conclude, and what they may not.** May: that the requests in
> `request-cases.yaml` which this run *issued*, from the seats it names, produced the differences it
> lists — each with its endpoint, case, identity, JSON pointer and both values, missing keys first.
> May not: anything about the surface. A run cannot be clean today and the report says so in its
> own first section: all twenty named comparisons are outstanding (their runners are T12), the
> fixture half is outstanding (its instance is T9), and every case that could not be issued is
> listed by name with the reason. The three numbers a reader must not read as coverage are
> *identical*, *allowlisted* and *endpoints compared* — the first counts comparisons that ran, the
> second counts findings an entry suppressed, and the third counts endpoints reached by **some**
> case for **some** seat. The report prints the declared conformance level beside every endpoint,
> including a `**no**` for each one this run compared not at all.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **A `LENGTH` on an
> array the allowlist marks `drawn` or `unordered`, whose `because` is a behaviours section, is
> reported with that argument beside it and does not by itself block the run.** It is T4's decision
> honoured rather than reopened — the count stays compared and permanently reported — and it is
> spec §3.4's own word: *"an **untriaged** difference blocks the run"*, where the *Diverge* row
> defines a triaged one as *"a behaviours.md entry with the argument, and an allowlist row"*, both
> of which exist for `Similar`'s `limit + 4`. The shape is as narrow as it can be made: only
> `LENGTH`, only at the entry's own pointer, and **never** for a derivation class, since a
> derivation is a fact about two installations and the number of rows in an answer is not one. Two
> tests fail if it is widened by either half. **The `allowlisted` line counts findings suppressed,
> computed from outside the engine** by comparing each pair a second time with no rules: the engine
> is pure and returns findings rather than a ledger, and plan §7 wants an entry that excused nothing
> reported — that one is leave-one-out, and an entry already known to have excused something is
> never re-checked. **A status difference stops before the headers as well as the bodies**, for the
> reason §6.2 already gives about the body. **`--named` narrows what is attempted and never what is
> reported**, because AC-16 counts twenty either way. **The report is Markdown at
> `reference/differential-<date>-<sha>.md`** (plan §4.4), the sha read out of `.git/HEAD` rather
> than asked of a subprocess, and `unknown` where there is none — a report that invented one would
> be worse than one that admits it has none. **Exit codes are 0 clean, 1 not clean, 2 could not
> start**, and `1` is the ordinary answer today.
>
> *A gotcha for anything else that loads two of these modules by path.* `tools/differential.py`
> imports the engine as `_differential` on first use, so a suite that had already loaded it under
> another name would hold **two copies of one module** — and `finding.klass is Class.LENGTH` is
> false across them, which is exactly what the attribution above turns on. The suite registers the
> engine under both names, in one line beside T2's `sys.modules` gotcha.
>
> *Nothing was written to any server.* The whole run is driven in the suite by a stub wire, which is
> what `Wire`/`Issuer` taking a client rather than a base URL buys, and the end-to-end path was
> exercised against two stub servers over the **real** registers — 59 endpoints, 84 cases, 85
> allowlist entries, 20 named rows — to prove the loop, the resolution, the report and the entry
> accounting run at all. Every claim about the wire in this note is from the pinned document, an
> existing behaviours entry, or the standard library read at the 3.9 floor. Verified under
> **3.9.25**: compiles, and `--help` reaches no server and reads no credentials.
>
> *What T9 must know.* **The degradation is already written and tested, and T9 only has to fill
> one field.** `Inputs.instance_url` is what every `needs: fixture`, `rescan` and `wait` row
> consults; `--reference-url` fills it today from an instance somebody else is running, and T9's
> `ReferenceInstance` fills it from one the run stands up. With it empty, every such case and row
> is **outstanding with the reason** and `is_clean()` is false — which is
> [ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md)'s *"the
> dependency buys coverage; its absence costs coverage and says so"*, already asserted. **`rescan`
> and `wait` resolve to the instance and not to a capability**, deliberately: a rescan is a write to
> a library, and the paused-session reading is *"a write held open for ten minutes, which is the one
> thing an operator's server must not be asked for"* (spec §3.10). **The report header already has
> both lines T9 fills** — `reference instance` and `reference image digest`, each saying at this
> point that no instance was stood up — so the digest ADR-0007 asks for lands beside the Atrium sha
> without the report changing shape. And **the roster is entered around the sweep in `_execute`**, so the
> instance's context manager wraps that call and nothing else moves.

## T9 — `tools/_reference.py`: a Jellyfin this project owns, uses once, and destroys

- [x] **Changes:** new `tools/_reference.py` — `InstanceSpec` and `ReferenceInstance`, a context
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

> **Done (2026-09-02).** *The instance starts, scans and dies — three full lifecycles, nothing left
> behind — and the finding is that the unattended sequence this plan wrote is one request short, in
> exactly the place plan §6.5 said to check rather than discover.*
>
> **`POST /Startup/User` answers `404` while no user exists.** It fetches the first user and
> returns `NotFound()` when there is none
> `[source: Jellyfin.Api/Controllers/StartupController.cs:130-137 @ v10.11.11]`; what makes one is
> the **`GET`** beside it, which runs the user manager's own initialisation before reading
> `[source: Jellyfin.Api/Controllers/StartupController.cs:107-114 @ v10.11.11]`. So the wizard's
> user operation is a **rename of the account the read created**, never a creation, and the
> sequence reads before it writes: `POST /Startup/Configuration`, **`GET /Startup/User`**, `POST
> /Startup/User`, `POST /Startup/Complete`, `POST /Library/VirtualFolders`. It was measured before
> it was read — the first real run stopped on that `404` — which is what
> [plan §6.5](plan.md#65-the-single-use-reference-instance) step 4 asked for in as many words, and
> the step it priced is the step it cost. `POST /Startup/RemoteAccess` is **not** needed: the
> wizard's own client sends it and three complete lifecycles never did. The first-time-setup
> authorization policy itself holds exactly as the document declares it — no credential is required
> before `CompleteWizard`.
>
> *The second is the same trap as the item count, one step nearer than the plan puts it.* §6.5 step
> 5 says to wait *"until the library scan reports itself idle"* because *"a count that has stopped
> changing is indistinguishable from a scan that has not started"* — and **the scan task is `Idle`
> before it starts, too**, so the literal reading returns on the first poll, before the library has
> been read at all. What is waited for is a **completion that did not exist a moment ago**, read
> from the task's own `LastExecutionResult` `[spec: GetTasks, TaskResult]`, with the scan asked for
> by name `[spec: StartTask]` when the task is idle and has never run.
> `refreshLibrary=true` does drive that task — every lifecycle saw it running without being asked —
> so that second path is a backstop and never the ordinary one. Measured: the Movies fixture
> library scans in 31–33 s.
>
> *The third is where the instance's own data lives, and it is the difference between a cleanup and
> a claim.* §6.5 step 2 asks for *"an ephemeral data directory created under the scratch root"* and
> the sweep for *"a data directory under the harness's own scratch root"*. The published image runs
> as **root**, so a host directory bind-mounted at the reference's data path comes back root-owned
> — and on Linux the sweep would then find wreckage it has no permission to remove, which is a leak
> reported as a cleanup, in the one task written to stop leaks being reported as cleanups. The data
> is therefore a pair of **labelled volumes** removed by the runtime that made them. The
> **fixture** stays a bind mount, read-only, because ADR-0007 wants it for a different reason
> entirely: the fixed modification time a copy would not preserve.
>
> *And the fourth is a contract line T8 had already made unnecessary.* [Plan §5](plan.md#5-contracts)
> gives `ReferenceInstance` a `create_identity(role)` and an `administrator: Identity`. T8
> established that **a seat is an account and the two servers share none**, so a run holds a roster
> per side; an instance that also made seats would make one of the two, on one server, and the loop
> would have two ways to obtain the same thing. The instance hands back a URL and the
> **credentials** its wizard created, `differential.py`'s own `authenticate` turns those into the
> `Identity`, and the roster is still entered **inside** the instance's context so the seats die
> first. §5 and §6.5 carry all four corrections.
>
> **T7's six unmeasured claims are settled, and every one held.** T7 wrote the seat lifecycle
> without a Jellyfin it was allowed to write to and listed what it could therefore not know;
> `tools/reference_instance.py --check --seats` drives T7's own `Roster` against a real instance and
> prints what each step answered
> `[probe: tools/reference_instance.py --check --seats, Jellyfin 10.11.11, 2026-09-02]`:
> `POST /Users/New` answers **200** with an `Id` in a nine-property body; `POST /Users/{userId}/Policy`
> answers **204**, the narrowing takes (`EnableAllFolders` false, `EnabledFolders` the one library)
> and a property nobody touched survives — which is T7's read-then-mutate rule measured rather than
> argued; a **bare** `GET /Users` does list an account an earlier run disabled instead of deleting,
> which is why the pre-flight sends no filter; a freshly created seat authenticates immediately
> under the same id; the wizard's first user **is** the administrator the roster is handed
> (`IsAdministrator` true, and its id is the one `POST /Users/AuthenticateByName` returned); and the
> three playback-processing permissions read back denied with `EnableMediaPlayback` untouched. The
> full roster then created two seats and left **only** the administrator behind. **What is still
> unmeasured is the sixth claim's other half** — that the three denials are *observable* at
> negotiation and delivery in the shape [behaviours §2.21](../../docs/compatibility/behaviours.md)
> predicts. That is the named comparison T12 runs, and it needs a runner rather than an instance.
>
> *The destruction is proven the way this repository proves a guard.* Nine guards were deleted in
> turn and the suite re-run, and each has exactly one failing test: `__exit__`'s teardown, the
> volume removal beside the container's, the raise on a success-path leak, the sweep in `__enter__`,
> the fixture mount's `:ro`, the wizard's read-before-rename, the scan's *did it actually run*
> clause, the destruction on `__enter__`'s own failure path, and the degradation branch that turns
> an absent runtime into a reason. Nothing in the suite starts a container or opens a socket: the
> runtime is a command line and the instance's client is injected, which is what lets a whole
> lifecycle be asserted where there is no Jellyfin and must not be one.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **The image is
> `jellyfin/jellyfin@sha256:aefb67e6…`, the multi-architecture *index* digest rather than one
> platform's**, so a contributor on arm64 and a maintainer on amd64 pin the same line — a
> per-platform digest would have introduced silently the very machine-to-machine difference the pin
> exists to rule out. It is in
> [reference-target §1](../../docs/compatibility/reference-target.md#1-the-pinned-version) and a test
> fails when the two copies drift. **Everything a run creates carries one label,
> `net.atrium.reference=single-use`** — container and volumes — and the sweep matches on the label
> and never on the name, because a name is a convenience and a label is a contract. **The published
> port is loopback-only and chosen by the kernel**; the fixture mounts at `/fixture`, deliberately
> outside the image's own two declared volumes. **`differential.py` gains `--fixture-root`**, since
> *which* world an instance is given is D-4 and T9 must not pre-empt it: a run that asks for
> `--fixture` without one reports the fixture rows outstanding with that reason, which is the same
> honest sentence as an absent runtime. **`Inputs` gains `instance_reason`** so the four failures of
> [plan §7](plan.md#7-failure-handling) reach the report as four different things to do next, and
> T8's *"the single-use instance is 010 T9"* is replaced by what this run could not do. Verified
> under **3.9.6**: both modules compile and `--help` reaches no server, starts nothing and does not
> even look for a runtime.
>
> *What T10 must know.* **`InstanceSpec.libraries` is how D-4 is asked either way** — a tuple of
> `Library(name, collection_type, subpath)`, defaulting to one mixed-content library over the whole
> tree, so *"one library"* and *"both worlds as two libraries"* are the same call with a different
> argument and no change to this module. **Nothing here has read what the reference makes of the
> fixture tree**, deliberately: the lifecycle was exercised over the 003 tree's `Movies` directory
> and the item count was not looked at, because that reading is D-4's and recording it here would
> file a measurement under the wrong task. **`tools/_reference.py` builds no tree** — the caller
> hands it a root — so T10 needs the entry point [plan §6.6](plan.md#66-the-fixture-on-the-other-server)
> names, and `tests/fixtures/library/generate.py`'s `build(destination)` is importable from a Python
> that has the repository root on its path. **A scan of the 003 movies tree takes about half a
> minute**, so the 900 s default deadline is generous rather than tight. **And a library's own
> identifier is reproducible across instances**: two separate containers, over the same mount path,
> gave the fixture library the identical id `f137a2dd21bbc1b99aa5c0f6bf02a805`
> `[probe: tools/reference_instance.py --check --seats, Jellyfin 10.11.11, 2026-09-02]` — 003 T19's
> *"ids derive from the absolute path"* holding for the virtual folder as well as for the items in
> it, which is worth knowing before AC-2 tries to join anything. And **the instance is the
> only writable Jellyfin this project has ever had**: three prior-measurement debts in
> reference-target and the two configuration debts ADR-0007 names (behaviours §2.2 and §2.3) are
> answerable from it now, and none of them is T10's.

## T10 — `tools/probe_reference_scan.py`: D-4's measurement, and the reading AC-2 is checked against

- [x] **Changes:** new `tools/probe_reference_scan.py`, the instance's **first run** and the task
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

> **Done (2026-09-02).** *D-4's default is wrong, and the two findings beside it are bigger than
> D-4.*
>
> **The reference makes 59 items out of the 003 tree** — 19 in `Movies`, 20 in `Shows`, 20 in
> `Music` — and **37 of them are backed by a file none of its probers can open**: an empty `.mkv`,
> a `.flac` of filler bytes, a `.ts` that is not a transport stream
> `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`. *Undecodable* is not
> *unresolvable*: the reference resolves an item from a **path** and probes it afterwards, and a
> probe that fails leaves an item with no streams rather than no item. So [plan §6.6](plan.md#66-the-fixture-on-the-other-server)'s
> **second** branch is the measured one — both trees go across as libraries of their own and AC-2
> compares both — and the default it stood on, *the media world extended with the structural entries
> §3.1 owes*, is withdrawn. The plan, §11 D-4 and §9's risk row say so, dated. It also settles the
> question T9 handed over: `InstanceSpec.libraries` is asked for **three typed libraries**, one per
> collection type the manifest declares, because Atrium's own libraries carry those types and a
> comparison that gave one server three typed libraries and the other one untyped library would be
> measuring the typing.
>
> *The first finding beside it is that the reading was not a reading of the tree at all.* A library
> added the way [plan §6.5](plan.md#65-the-single-use-reference-instance) step 4 described it — a
> `LibraryOptions` naming only its path — **fetches metadata from the internet**, and over this tree
> it answered with names no part of the tree contains: `WALL·E's Treasures & Trinkets` for
> `Wall-E (2008).mkv`, `Highlander: Reunion` for `The Series - S00E01 - A Special.mkv`,
> `12:00 A.M.-1:00 A.M.` for an episode of a series called `24`. **Nine of the fifty-nine names**,
> from a third party's database, moving whenever that database does — into the one comparison whose
> whole value is that a difference means a difference in a server. And the property that reads like
> the switch is not one: `LibraryOptions.EnableInternetProviders` is declared, is stored, reads back
> `false` — and is consulted by **nothing**, its declaration at
> `MediaBrowser.Model/Configuration/LibraryOptions.cs:64 @ v10.11.11` being its only occurrence in
> the reference's source. Set alone it changed not one of the nine names. What works is the
> library's own `TypeOptions`, which are an **allowlist** rather than a deny list
> `[source: MediaBrowser.Controller/BaseItemManager/BaseItemManager.cs:42 @ v10.11.11]`: an empty
> fetcher list per type takes the network out of the reading and leaves the local readers, so both
> servers still read the `.nfo` sidecars and can be compared on them. **The item set was identical
> either way** — only names moved — which is what makes this a contamination of the comparison and
> not a difference in the scan. `tools/_reference.py` sends it now, `Library.internet_providers`
> asks for the other shape, and the probe takes **both** readings by default because the difference
> between them is the finding and a citation a probe cannot reproduce is not one.
>
> *The second is Atrium's, and the comparison is what found it.* `tests/library/test_reference_reading.py`
> failed about **one run in ten**, on the series name: `metadata/refresh.py`'s `_first_file_backed`
> walked a container's children **in identifier order**, and an identifier is a hash of the
> **absolute** path (003 §3.6) — so which descendant a container borrowed its directory from moved
> with the mount point. That is not the harmless tie the genre spelling beside it already tolerates:
> the descendants of one container sit at different depths — a series whose second season has no
> season directory has an episode one level below it and the rest two — and the caller walks up a
> **fixed** number of levels from whichever it is handed. Land on the wrong one and the series looks
> for its `tvshow.nfo` in the library root, finds none, and keeps the path-derived name, where the
> reference reads that sidecar every time. It now gathers every file-backed descendant and takes the
> one whose **relative** path sorts first, which is a property of the tree; the guard is
> `test_a_container_borrows_the_same_directory_wherever_the_library_is_mounted`, and it fails on the
> old ordering. What is **not** fixed is that the borrowing is a guess at all — a two-disc album
> still borrows `CD1` and so never sees its own `album.nfo` — which is 004's to decide and is
> recorded here rather than taken.
>
> *So AC-2 is a test, and it is not an equality.* The probe writes
> `docs/compatibility/reference-fixture-reading.json` — 59 rows of `(type, name, file)` per library,
> with its own citation, the image digest and the nine fetched names inside it — and the test
> compares Atrium's scan of the same tree against it, in the default job, with no Jellyfin anywhere.
> **The two servers disagree in twenty-six places** and every one is declared with its reason: two
> files only the reference makes an item of, twenty files both make an item of under different
> names, and four container rows. Nothing is excused silently, a difference that is not declared
> fails, and a declared difference that has gone away fails too — so the table cannot outlive what
> it describes. Deciding what Atrium *does* about any of them is the owning feature's, per
> [spec §2](spec.md#2-scope).
>
> **The two sharpest of the twenty-six are worth naming here.** A **zero-byte** film is an item
> there and not here, which is 003 §3.2's deliberate rule meeting a server that has no such rule.
> And the `.ignore` exclusion **is not being exercised on the reference side at all**: an empty
> `.ignore` ignores the directory outright and one with content is read as gitignore-style rules
> `[source: Emby.Server.Implementations/Library/DotIgnoreIgnoreRule.cs:58-66 @ v10.11.11]`, and
> `generate.py` writes a banner and filler into every declared entry — so the fixture's marker is a
> file full of rules that match nothing. **That is a defect in the fixture**, it is T11's, and it is
> written into the declared table so that repairing it moves a row rather than surprising somebody.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **The reading is
> JSON and not YAML**, for the reason `property-names.json` is: a file a program writes is read by a
> program, and the prose that justifies a row belongs in the probe that took it. **The tree is built
> by a new entry point, `tests/fixtures/reference_tree.py`** — plan §6.6 asked for one — which names
> the tree, the three libraries and their collection types from 003's own manifest, so a renamed
> library moves both sides at once. **`tools/_probe.py` gained `connect_with`**, one parameter, so
> that the probe whose server does not exist until it makes one still reaches `_probe.main` and
> still prints the convention's citation and exit code; the instance is torn down *after* the
> report, because a report printed after the teardown would name a server that no longer exists.
> **The probe refuses a server argument**: its question cannot be asked without writing a library
> into the server being asked. And **the tree is built under the git-ignored `reference/`** and not
> under `tempfile`'s directory, which on macOS is a path the container runtime does not share — the
> container then starts, finds nothing at the mount, and exits, which arrives three minutes later as
> a readiness timeout with `--rm` having already removed the evidence.
>
> *What T11 must know.* **It builds both worlds, not one.** The 003 tree goes across as it stands —
> that is what this measurement bought — so what T11 owes is the media world beside it and the
> entries [spec §3.1](spec.md) still owes, and `reference_tree.py` is where the second world is
> named. **Fix the `.ignore` first**: `Excluded/.ignore` must be **empty** for the case to exist on
> either server, which means `Kind.IGNORED` is not the right kind for a marker file and
> `generate.py` needs to be able to write a zero-byte entry that is not `Kind.EMPTY`. **A scan of
> the whole three-library tree takes 26–34 s with the fetchers on and about 2 s with them off**, so
> the 900 s deadline is generous either way and the provider comparison is what costs a run its
> three minutes. **The instance's label is fixed across runs**, so two runs cannot overlap: the
> second sweeps the first's container out from under it, which is the design and is worth knowing
> before running two by hand.

## T11 — The fixture world gets what §3.1 owes, written against T10's answer

- [x] **Changes:** the fixture the instance is given, extended with the five entries spec §3.1 owes
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

> **Done (2026-09-02).** *The four entries were the small half. The big half is that composing both
> worlds moved five anchors that were already filled, and that a repaired fixture removed a
> difference nobody had been able to remove.*
>
> **`Excluded/.ignore` was fixed first, and it closed a declared difference.** T10 recorded it as a
> defect in the tree: an `.ignore` marker excludes a directory outright only when it is **empty**,
> and a non-empty one is read as gitignore-style rules
> `[source: Emby.Server.Implementations/Library/DotIgnoreIgnoreRule.cs:58-66 @ v10.11.11]`, so the
> banner `generate.py` writes into every declared entry made the fixture's marker a rule set
> matching nothing. `Kind.IGNORED` is the wrong kind for it and `Kind.EMPTY` is the wrong kind too
> — that one means *an incomplete copy*, which is a different case the same tree also carries — so
> the manifest has a fifth kind, `Kind.MARKER`, and `generate.py` writes zero bytes for both. The
> two servers now **agree** about `Excluded/An Excluded Film (2000).mkv`: the reference's Movies
> library is 18 items where it was 19, the declared difference is gone from
> `tests/library/test_reference_reading.py`, and the case the entry was written for is exercised
> for the first time on the side it was written for.
>
> **Both worlds go across, and the composition needed three things D-4's answer did not say.**
> `tests/fixtures/reference_tree.py` writes the 003 tree in place, copies the media world in under
> a `Decodable/` subtree and makes one directory with nothing in it — **six libraries, 72 files**.
> The two worlds both name a root `Movies` and a root `Music`, so a flat layout would have merged
> one into the other silently and a reading keyed on a library's name would have held one library
> where there were two; the media libraries take the names Atrium's own side already gives them,
> `Films` and `Tunes`. **`tests/fixtures/media.py` had to become importable without this project's
> runtime**, because that entry point is reached by `tools/probe_reference_scan.py` on the 3.9 floor
> where no environment exists, and it imported SQLAlchemy and the `atrium` package for the scanned
> world it also carried — that half is `tests/fixtures/media_world.py` now and nothing else moved.
> And **the prober follows the library**: Atrium's side of AC-2 scans the 003 tree with the stub
> that refuses, which its own generator says is the truth about those files, and the media world
> with the real one, because scanning real media with a stub would have compared Atrium's
> *unexamined* reading against a reference that examined everything.
>
> *What §3.1 actually owed was four files and one thing that is not a file.* `media.py` already
> carried the multi-part film, the film with a subtitle file beside it and the image subtitle
> track. What it did not have: a **subtitle file in a legacy encoding** — `SidecarFile.encoding` is
> a declared field now, and the one entry that uses it is `cp1251`, chosen because `cp1251` and
> `cp1252` share every byte position so the words decode to *different letters* rather than to an
> error, which is the half of behaviours §5.11 a client sees directly; an **EXIF orientation** on a
> planted image, written by splicing an APP1 segment into an mjpeg output because this module has
> no image library and must not grow one — the same move `pgs_bitstream` makes for a subtitle codec
> with no encoder — with a **second, untagged image beside it**, since a resize that honours the
> tag and one that ignores it are only distinguishable against a control produced the same way; and
> an **empty library**, which is a directory and a declaration in the entry point rather than an
> entry in either manifest. **A playlist is not a file**, so the fifth thing §3.1 lists cannot be in
> a tree at all: what a tree can owe is the two libraries and a reader who may open one of them, and
> the playlist itself is written through the API by the run — §3.10's row, T12's runner. Before this
> tree, every reachable library a seat could be restricted to held one collection type, so that row
> was unaskable for a reason nobody had written down.
>
> *The finding that cost the most is that filling the unfilled anchors was the easy half.* T6 left
> four shapes unfillable — an item id in a **body** (007's three reporting routes) and in a
> **query** (`ids` and `entryIds`) — and `<anchor.p>` fills them: one token, resolving to whatever
> the anchor named `p` resolves to, through the same three kinds and the same per-server
> resolution, so nothing new became resolvable and no case may carry an identifier. Two checks came
> with it, and the second is the one that matters: **an anchor that fills nothing** — neither a path
> parameter nor a token — is refused, because otherwise a case *looks* filled while it goes on
> sending what it sent before. **Six cases lost their `fixture` with it**, since for those six
> `fixture` had never meant the fixture; `test_a_fixture_run_with_no_runtime...` counts eight where
> it counted twelve. **But five anchors that were already filled were pointing at the wrong film.**
> T6 anchored the two image cases and the three subtitle cases on
> `GET /Items#movies-by-sort-name@0` under *"the fixture is what guarantees the anchored film HAS
> one"* — true of the world the plan defaulted to, and false the moment D-4 chose both worlds, since
> a movie listing sorted by `SortName` now spans the 003 tree and its first row is a film of filler
> bytes with no image, no subtitle stream and nothing a prober can open. Two listing cases narrowed
> by `searchTerm` name one fixture film each and the five anchor on those. **One anchor is still
> unfilled and is not dressed up**: `playlistId` on the HLS segment route is carried by an m3u8
> body, and addressing a text body is a fourth anchor kind — a mechanism, not a fixture.
>
> *Three differences nobody predicted, from the two libraries the reading gained.* Over files both
> servers can actually open the disagreement is **five names and nothing else** — same items, same
> files, same types — which is the sharpest thing in the record. The three that are new: the
> reference names a library's root `Folder` row after the **directory** and not after the library,
> so `Films` comes back as `Movies` where `/UserViews` answers `Films` — invisible in the 003 tree,
> where directory and library names are equal; it takes a `MusicArtist` from the **directory** even
> where the file's tags name another, while taking that same file's **album** from the tags, so the
> two readings are not simply "tags here, paths there"; and an **empty library is nothing at all to
> it** — zero rows, not even the root `Folder` it gives every other library — where Atrium carries
> its `CollectionFolder`. The reading is 74 items over six libraries and the comparison is
> **forty-seven** declared differences where it was twenty-six
> `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`.
>
> *Two things about the record itself, and the first was a false statement in it.* Its finding
> counted every file-backed row as *"backed by a file none of its probers can open"*, which was true
> of the 003 tree alone and would have described a real `h264` file as unopenable in the one
> document AC-2 is checked against; each library carries whether its files are decodable now and the
> finding counts the two apart — 74 items, 48 backed by a file, **36** of those over a file nothing
> can decode. And **no run of this task contacted a metadata provider**: the provider comparison
> exists to measure that a library added the obvious way fetches names from the internet, so taking
> it means standing up an instance whose whole purpose is to let a third party answer.
> `--skip-provider-comparison` is the ordinary way to re-take a reading now, and it **carries T10's
> list forward with the citation it was taken under** rather than dropping it — a record with no
> list would let the test that keeps the reading honest stop asserting anything.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **The empty library
> is declared in the entry point and not in either manifest**, because it belongs to the composition
> rather than to a world: adding it to `LIBRARIES` would have put an empty library into every 003
> test. **`test_reference_reading.py`'s two comparing tests carry the `ffmpeg` marker** — building
> the tree means encoding it — while the four that read only the record do not, so a machine without
> the binaries still checks the record's citation, its fetcher line and its own arithmetic; CI
> installs ffmpeg, so AC-2 runs there. **The declared-difference count is asserted rather than
> described**, because forty-seven in a docstring that nothing counts goes stale the way the
> prior-measurement register did. **`GENERATOR_VERSION` is 3**, so no cached tree from before the
> encoding field and the planted images can be read.
>
> *A failure worth knowing before T12, because T12 stands up instances for twenty rows.* **Two of
> five instance starts on this machine died before answering**, with the container exiting `132` —
> `SIGILL` — seconds after *"Core startup complete"*, on the pinned image, natively (an `arm64`
> image on an `arm64` host, no emulation), with nothing of the run's own having happened yet. Not
> the tree and not the configuration: the same tree and the same mounts came up on the next attempt
> and scanned in **3 s**. It costs the 180 s readiness deadline and nothing else, and `--rm` has
> already taken the container by the time the run asks for its logs — so the exit code is only
> visible to a watcher outside the run. Plan §7 carries the row.
>
> *What T12 must know.* **The tree it gets is six libraries and it is composed, not declared**:
> `reference_tree.libraries()` is the list, `ReferenceLibrary.decodable` says which side of the two
> worlds a library is on, and the media libraries are `Films` and `Tunes` rather than `Movies` and
> `Music`. **Every fixture-dependent row now has its input**: the multi-part film, the film with a
> subtitle file, the image subtitle track, the legacy-encoded sidecar, the planted EXIF poster with
> its untagged control, the two libraries a restricted seat can be split across, and the empty
> library — whose *scan* half is already measured (zero rows there, a `CollectionFolder` here) while
> its **played state**, which is what behaviours §5.7 asks, is still T12's to run. **`needs:
> [fixture]` on a request case means the fixture now**, not "waiting on T11": eight cases carry it
> and two of those are the listings that name a fixture film. And **a scan of the composed tree
> takes 3 s** with the fetchers off, against T10's 26–34 s with them on, so the deadline is not
> where a fixture run spends its time — the instance's start is.

## T12 — The named comparisons: six runner shapes over twenty rows

- [x] **Changes:** `tools/differential.py` gains a `runner` per row of `named-comparisons.yaml`, one
  signature, `(instances, identities) -> NamedResult`, so the twenty are code beside the sweep and
  not prose beside the report (plan §6.4). Six shapes cover all of them: **a second seat** — the
  named reader, the entries a reader cannot reach, the delivery-time policy refusal — where the whole
  signal is a status or a **row count**; **the same request twice** — the de-duplication that
  misses, where the *reference's* disagreement with itself is the finding and never a flake to
  retry (6 of 8 identical requests behaved differently, behaviours §3.18); **something that is not
  in a body** — the progressive header frame, burn-in, the image track's latency, the subtitle
  playlist's bytes, the manifest's `NAME` masked against its invariant form; **a library the
  reference has to be given** — the multi-part film, the legacy-encoded subtitle, EXIF orientation,
  the empty library, the media source with no runtime, and the specials series 005 OQ-7 needs; **the
  library changed underneath a rescan** — the emptied container (behaviours §5.2) and the replaced
  poster (behaviours §5.6), where the signal is the difference between two scans and not inside one
  answer; and **a reading after a deliberate wait** — the paused-session ticker freeze, ten minutes
  of silence against a paused session and then the position each server committed. The last three
  shapes are the ones D-6 widened the table for, and all three need the instance T9 lands. The last
  two rows of §3.10 stay ordinary request cases with a register row pointing at them. A runner that
  raises leaves its row **outstanding with the exception** and the run continues.
- **Depends on:** T7, T8, T11
- **Verified by:** `uv run pytest tests/conformance/test_differential.py -q` for the shapes that can
  be driven without a server: `test_a_runner_that_raises_leaves_its_row_outstanding_and_the_run_continues`,
  and `test_the_row_count_is_the_signal_for_the_unreachable_entries_row`, which asserts the runner
  compares **counts** and not bodies — the two servers agree on every field of every row they both
  show, so a runner that diffed bodies would report nothing and pass. Then by hand against an
  instance: `python3 tools/differential.py --named --fixture`, whose report must name **twenty** run
  or outstanding, with no separate list beside them.
- **Spec reference:** §3.10, AC-16; plan §6.4

> **Done (2026-09-02).** *Fourteen of the twenty ran against a real pair of servers, and the first
> thing they found was that a `--fixture` run had been comparing the wrong server.*
>
> **`--fixture` stood the instance up beside the reference instead of as it.** [Plan §6.5](plan.md#65-the-single-use-reference-instance)
> wraps it round the sweep, which is the right lifetime and the wrong *place*: every `needs:
> fixture` request case resolves its anchor against the reference **under comparison**, and every
> fixture-dependent runner asks that same reference for a film by name — so with an instance
> standing beside a `--jellyfin` pointing elsewhere, all of them would have been asked of a server
> that has never seen this repository's tree and answered `404` rather than reporting a difference.
> `--fixture` now *means* the fixture on both servers (AC-2): the instance is stood up before the
> reference is authenticated, it **is** the reference, the run takes its wizard's administrator
> rather than `.env`'s, and a `--jellyfin` naming anything else is refused. **And it was being
> given the wrong world**: `_reference.DEFAULT_LIBRARIES` is *one mixed-content library over the
> whole tree*, where D-4 chose six typed ones and T11 composed them — a mixed library has no
> `CollectionType`, so the run could not find a movies view to narrow the restricted seat to and
> stopped before comparing anything. `differential.py` imports `tests/fixtures/reference_tree.py`
> for the library list the way `probe_reference_scan.py` already does.
>
> ***And then the first run against a real Atrium stopped at `GET /Users -> 404`.*** **None of the
> three routes a seat is made with is in [surface.yaml](../../docs/compatibility/surface.yaml)** —
> `GET /Users`, `POST /Users/New`, `POST /Users/{userId}/Policy` are the reference's, and
> Principle VI keeps an endpoint out until a client is measured calling it. So a **two-identity run
> was impossible against the very server this harness exists to measure**, and nothing had noticed:
> T7 built the roster with no Atrium it was allowed to write to, T9 proved it against the
> reference, and T8 drove it end to end over stubs. `Roster` therefore takes a seat **handed in** —
> a username and a password per role, signed in as, used, and left exactly where it was, with
> `created_by_the_run` false so the teardown cannot touch it — which is what the administrator has
> always been. The pre-flight runs over the roles the roster actually creates, so it neither
> refuses the operator's own account nor asks a server for a listing it does not serve, and its
> refusal now names the four environment variables rather than the `404`. AC-15 is satisfied where
> the routes exist and is **unsatisfiable on Atrium by design**; [plan §6.7](plan.md#67-identities)
> says so.
>
> *Three more the stub wire could not have found, each one fatal to a real run.* **A space is not a
> request line**: `request-cases.yaml` writes what a client sends — `searchTerm=The Planted
> Poster` — and `http.client` refuses that target outright, so every case with one was unissuable
> and the run stopped before it compared anything; the query is percent-encoded now, and a test
> asserts every declared case is issuable. **The reference binds a token to a device**: two
> accounts under one `DeviceId` are one session, so signing the second seat in revoked the first's
> token and the teardown answered `401` on every account it had created — each account has a device
> of its own now, at sign-in and in use, and the sign-in goes through this module's own `Wire`
> rather than `_probe.py`'s one fixed device. **And a login is the one case whose effect is on the
> caller**: sweeping `POST /Users/AuthenticateByName` as a seat, on that seat's device, logged the
> seat out mid-run, so that case is issued on a device of its own.
>
> **What the thirteen found.** The two the register exists for both reproduce exactly:
> **behaviours §3.16** — a restricted reader naming the owner of a private playlist is answered
> `200` with its two entries by the reference and `403` here, where both answer `404` without the
> parameter; and **behaviours §3.17** — a playlist of three entries spanning two libraries, read by
> a seat that can open one of them, is **1 row here against 3 there**, `TotalRecordCount` 1 against
> 3, which is the row count being the whole signal. Beside them: the reference's progressive mp3
> re-encode carries a `Xing`/`Info` header frame and Atrium's does not (behaviours §3.3, 008 T14's
> fourth divergence, measured on the wire at last); a `cp1251` sidecar comes back
> `Çäðàâñòâóéòå` here and `Здравствуйте` there (§5.11); the two-part film answers two media sources
> and no `PartCount` here against one source and `PartCount: 2` there; and four are **parity** —
> the subtitle playlist's window lines are identical and both write a decimal **point** (§3.12
> holds: the defect is the reference *host's* locale), an empty library reads `Played: false` on
> both (§5.7, where the source reading said *vacuously played*), neither server honours an EXIF
> orientation on resize, and `Next Up` offers nothing on either when only season 0 is unplayed —
> which **closes [005 §7 OQ-7](../005-item-query-api/spec.md)**.
> `[probe: tools/differential.py --named, Jellyfin 10.11.11, 2026-09-02]`
>
> **The eleven-minute row ran and its answer is a smaller one than the question.** A session
> reported playing and then paused at 10 000 000 ticks, left silent for 660 s — past Atrium's
> five-minute reap and past the ten minutes 007's list prices the reference's at — commits
> `PlaybackPositionTicks: 0` on **both** servers. So the two agree, and what they agree on is that
> **neither commits the paused position at all**; the ticker freeze cited from
> `[source: MediaBrowser.Controller/Session/SessionInfo.cs:23, 373-451 @ v10.11.11]` cannot be
> read off a position nobody wrote. The row is reported **not as documented** for exactly that
> reason rather than passed: what it needs next is a reading that first proves the paused report
> was stored, which is one request more than this runner makes.
>
> **Three rows measured a claim and killed it, and one of them is Atrium's.** A seat with all three
> playback-processing permissions denied — read back denied on both — negotiates
> **`SupportsTranscoding: true` here and `false` there**, so
> [behaviours §2.21](../../docs/compatibility/behaviours.md)'s *"the same negotiation semantics —
> the all-three gate"* is false of this server: **the first difference this harness has found in
> Atrium rather than in a document**, and 008's to decide (spec §2). And the image track's `400`
> arrives in **10 ms** on the reference where 011 recorded twenty seconds, so that row is reported
> **not as documented**: the claim does not reproduce against a four-second fixture film, and what
> it needs is a source whose extraction is expensive. The paused-session row above is the third.
>
> **behaviours §5.2's `⚠️ UNVERIFIED` is discharged, and the belief was wrong.** A series emptied of
> every file and rescanned is **still fetchable** on the reference, with zero episodes under it and
> one row in a `Series` listing — the same thing Atrium does, so the *"accepted gap"* that entry
> recorded is a **measured parity**. **§5.6's *"unmeasured from here"* is discharged the other
> way**: replacing the artwork beside an untouched film and rescanning at default depth **changed**
> the reference's image tag and the bytes it identifies, where Atrium's signal is the media file's
> own size and time. Both entries carry the reading. **Both rows are still outstanding as
> comparisons**, and that is the fifth runner shape's finding: *the library changed underneath a
> rescan* needs a second scan on **both** servers and Atrium has no library-refresh route —
> `POST /Library/Refresh` is the reference's and is not in the surface — so the instance was
> necessary and is **not sufficient**. They take the reference half and report outstanding carrying
> it, which is the only honest shape: a one-server reading is not a differential.
>
> *One sentence in three documents is now historical rather than current, and it is left alone
> deliberately.* Spec §3.10's second column, this list's *"What the gate changed"* §3 and the
> register's `why_the_sweep_misses_it` all say behaviours §5.2 *"carries the only surviving
> `⚠️ UNVERIFIED` in the compatibility documents"*. That was true when D-6 was taken and is the
> reason the row exists; it stopped being true the moment the row ran. Rewriting it would mean
> amending an **accepted** spec to restate a justification rather than a criterion, so it stays as
> the record of why the row was added — and [behaviours §5.2](../../docs/compatibility/behaviours.md)
> itself carries the reading, which is where a reader looking for the claim goes. **T15 is where it
> is worth a line**, beside the acceptance map.
>
> *`is_clean()` gained a fourth condition, and it is the first three read the other way round.*
> Every one of these rows exists because two servers are **expected** to differ, so a row that ran
> and measured something its own citation does not predict is an untriaged difference arriving
> through a runner rather than through `compare`. Without it all twenty could run, every one
> contradict its entry, and the report still say *"20 run, 0 outstanding"*.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **`--only-named`**,
> which attempts the named comparisons and not the sweep — every declared case is then reported
> **not asked** with that reason and the run is not clean, so it is a way to re-run one comparison
> without re-issuing 250 and never a smaller kind of run. **`movies_library_id` now requires the
> library to hold something**: the composed fixture has three `movies` libraries and one of them is
> deliberately empty, so taking the first narrowed the reader to a library with nothing in it —
> the *"refusal for the wrong reason"* that function's own docstring was written against.
> **The series a rescan empties and a Next Up question needs is found by shape and not by name**,
> because the two servers disagree about that name — `The Series` there, `tvshow` here — and a
> comparison keyed on it would have been outstanding for a difference the AC-2 record already
> declares. And **`--fixture-root` defaults**: the tree is built through
> `tests/fixtures/reference_tree.py` into the git-ignored `reference/fixture-tree` when the caller
> names none.
>
> *What could not be run, and why, stated rather than skipped.* Six of the twenty: the two
> `rescan` rows above; **burn-in**, whose two transcodes per side killed the instance before it
> answered; the **manifest's announced track name**, where the reference answers `400` to the
> master playlist of the fixture film that has an `ass` track, so there are no announced entries to
> compare; and the last two of §3.10, which are ordinary request cases and need a **sweep** — under
> `--only-named` they report that they were not asked, which is true. Every one is named in the
> report with its reason and every one keeps the run from being clean.
>
> **The instance dies with `SIGILL`, and this task caught the exit code T11 could not.** `--rm` had
> always removed the container before anyone could ask, so T11 could only record *"two of five
> starts died"*; a `docker events` watch beside the run names it: **exit 132**, four times in eight
> starts on this machine, at startup and under the sweep alike, on the pinned image natively. Plan
> §7's row carries it. It is the reason the twenty were run in batches against an instance stood up
> by hand with `tools/reference_instance.py` and `--reference-url`, which is the degradation
> ADR-0007 already describes, working.
>
> *What T13 must know.* **`tools/_probe.py`'s `Server` has one fixed `DeviceId` for every probe
> there is**, and this task measured what that costs: two accounts on one device are one session on
> the reference, and the second sign-in revokes the first's token. Every writing probe that signs
> in as a throwaway user while holding an administrator's token is exposed to it, which is worth
> knowing before the shared created-and-owned register is built. **The teardown contract T13 is
> collecting already has a second failure mode measured**: a `DELETE` that answers `401` because
> the token was revoked, and one that answers `Connection refused` because the instance died — both
> reported as *"the run created seats it could not destroy"*, and neither is the probe forgetting
> to clean up. And **the two configuration debts T1 left for T13 are still the instance's**: it is
> the only writable Jellyfin this project has, and it stays that way.

## T13 — The probe convention enforced, the cleanup contract shared, and the last two debts paid

- [x] **Changes:** `tests/unit/test_probe_convention.py` gains its convention half — a sweep over
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

> **Done (2026-09-02).** *The cleanup contract is not where this task put it, and putting it there
> would have left the twenty-eight probes that write exactly as they were.*
>
> **A register a probe has to call is the promise those probes already made.** Every one of the 28
> playlists 009 left behind came from a script that had *already written its own teardown*; what
> none of them had was one that ran on the path out it was not written for. So `_probe.Server`
> records the creation **as the request happens** — `POST /Playlists` and `POST /Users/New` are the
> two routes in this repository that make something outliving the request — a removal the probe
> issues itself **de-registers** what it removed, and `main` tears down whatever is left in a
> `finally`. Nothing in the twenty-eight that already wrote had to be edited and the contract now
> holds for all of them, including the twenty-ninth nobody has written. Proven the way this
> repository proves a guard:
> `test_a_writing_probe_that_leaks_fails_the_sweep` registers an object, raises, and asserts the
> object was removed — **delete the `finally` and it fails**, checked by deleting it. And proven on
> a live server rather than only in the suite: `probe_public_users.py`'s first run printed
> *"the shared register removed 1 object(s) the probe had not removed itself"* over a real account.
>
> **The three teardown failures that are not leaks are three and not two.** T12 measured a revoked
> `401` and a connection refused; a `404` is the third — an object a probe removed through a path
> the register did not see. `ProbeError` carries `status` and `transport` now, so the classification
> reads the response rather than parsing our own prose, and only an unexplained failure exits `3`.
> Reporting the other three as leaks is exactly spec §6's *"does not cry wolf"* pointed at the
> teardown.
>
> ***The `needs_writes` sweep needed two shapes, and the first fix for it was wrong.*** It found
> three probes reaching a write route without declaring one. `probe_routing.py` is not one: it
> sends a `PUT` at a route serving `POST` and `DELETE` to read its `405`'s `Allow` header, so the
> exemption list is `(method, route)` **pairs** — exempting the route would have exempted the
> `POST` that writes. The other two, `probe_playback_info.py` and `probe_subtitle_negotiation.py`,
> create user accounts and **already declare `--allow-writes` themselves**, because for them the
> flag *adds a battery* rather than gating the run; `tools/README.md` has listed both with the flag
> all along. Adding `needs_writes=True` made argparse refuse the duplicate option — caught by CI's
> own 3.9 `--help` sweep, run locally. Two enforcement layers meeting is the reason the rule is
> *"declares it at the entry point **or** declares the option and branches on it"*.
>
> **The two register debts are paid, and one of them moved.** `tools/probe_public_users.py`:
> `/Users/Public` honours the flag in both directions — two un-hidden accounts, one hidden, none —
> and **`IsHidden` is `true` by default**, on the administrator the wizard creates and on every
> account `POST /Users/New` creates `[source: Jellyfin.Data/UserEntityExtensions.cs:174 @
> v10.11.11]`, so a reference nobody has configured already answers `200 []`. The empty answer is
> the default rather than a hardened configuration, which makes behaviours §2.2's client guidance
> matter far more than it read. The first draft of that probe sent the administrator's token and
> measured `[]` at **every** step: two of the route's four filters read the caller
> `[source: Jellyfin.Api/Controllers/UserController.cs:635-651 @ v10.11.11]`, so it is read with no
> credential now, which is who calls it. `tools/probe_local_address.py`: the HTTPS override
> reproduces exactly — `http://<address>:8096` before a certificate and `https://<address>:8920`
> after one, scheme *and* port, on a plain-HTTP request, on `/System/Info/Public` and `/System/Info`
> alike — which is the condition behaviours §4.2's whole argument rests on.
> `[probe: tools/probe_public_users.py and tools/probe_local_address.py, Jellyfin 10.11.11,
> 2026-09-02]` The register is **twelve down, three to go**, and the three left are one author's
> afternoon and one library scanned twice.
>
> ***And a difference against implemented 002, which is not this feature's to decide.*** Atrium's
> user record defaults `is_hidden` to `false` where the reference's is set, so the first account on
> each server answers a different `/Users/Public` — one row here, none there, on a login screen.
> Recorded in [behaviours §2.2](../../docs/compatibility/behaviours.md) in the shape T12 used for
> the `SupportsTranscoding` finding, and left to 002 through §3.0: the harness triages and the
> feature that owns the endpoint answers (spec §2). The flag's *effect* is parity — both servers
> exclude a hidden user and both answer `200 []` when every account is hidden.
>
> **T4's debt and T12's are paid, and T4's had a guard-shaped hole behind it.**
> `probe_sidecar_subtitles.py:284`'s `zip(..., strict=False)` is gone — and it survived because CI
> cannot see that class of breach: the `tools` job compiles on 3.9 and runs every `--help`, and a
> 3.10 *keyword argument* compiles and raises only when the line is reached. So the sweep has a
> fourth test over **every** `tools/*.py`, not only the probes.
> For T12's: `Server` derives a **device per account** now, so two accounts in one process are two
> sessions by construction. `probe_session_filters.py` had been swapping a module constant around
> its second sign-in and was the only probe that did; every other one that signs in twice was
> exposed.
>
> ***And that fix had a silent blast radius nobody would have seen.*** **Five files had copied the
> old device id out as a string literal** — `_playback.stop_encoding`, a
> `DELETE /Videos/ActiveEncodings`, a session lookup in `probe_transcode_decision.py`, and two
> query strings in `probe_progressive_production.py` and `probe_universal_audio.py`. Every one of
> them names *this run's own device*, so a derived one would have left all five naming a device
> nothing was signed in from — and the failure is invisible in both directions: a stop that names
> the wrong device stops nothing, and a session lookup that finds nothing reads as a session that
> ended. `stop_encoding` is the **cleanup path of every playback probe**, so the device fix would
> have left encoders running on the very server this task exists to stop leaking onto. All five go
> through `server.device_id` now, `test_no_tool_writes_the_device_id_out_by_hand` fails the sixth
> copy, and `probe_subtitle_negotiation.py`'s one `stop_encoding(as_user, …)` is *more* correct
> than before: it had been stopping the administrator's device while meaning the throwaway's.
>
> *Routine calls taken.* **The concurrent leak fix had not landed** — `main` was at T12's merge with
> nothing of it — so this task built on `_probe.py` as it stood and nothing was written beside it.
> **`_reference.py` gains `restart()` and an `auto_remove` flag**, because the reference reads its
> certificate at startup `[source: Emby.Server.Implementations/ApplicationHost.cs:457-458 @
> v10.11.11]` and a container started `--rm` does not survive the stop half of a restart — measured
> here first, as a 180-second readiness timeout over a container that no longer existed. `--rm`
> stays the default and the label sweep still covers a killed run. **`probe_local_address.py` shells
> out to `openssl`** for one PKCS#12, because the reference loads only a bundle carrying a private
> key and the standard library cannot write one; it says so and refuses to guess when `openssl` is
> absent. **The two `prior-probe` citations became `[probe:]`** in behaviours §2.2, §2.3,
> `api-surface-v1.md` and **001's accepted spec**, because the register defines a discharge as
> exactly that — the same call T1 took for its own three rows. Nothing was written to any server
> anybody owns: every reading here came from an instance this run created and destroyed, verified
> afterwards with `docker ps -a` and `docker volume ls` on the run's label, both empty.
>
> *What T14 must know.* A probe can now exit **`3`**, which is neither a finding nor an inability to
> look: it means the run created something it could not remove and nothing explains why.
> `bump_reference_version.py` re-runs every probe at step 3, so its step must treat `3` as a failure
> of the run and not as a contradiction to triage — and must not treat it as success because it is
> not `1`. And two of the probes it re-runs — `probe_public_users.py` and `probe_local_address.py`,
> beside `probe_reference_scan.py` — **refuse a server argument** and stand up their own instance,
> so a bump on a machine with no container runtime cannot run three of the probes at all and has to
> say so rather than skip them.

## T14 — `tools/bump_reference_version.py`: four steps in order, and no way past a failure

- [x] **Changes:** new `tools/bump_reference_version.py` running
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

> **Done (2026-09-02).** *Step 1 cannot pass. Not on this machine, not on any machine: the
> procedure's first step, run the way conformance.md words it, fails on every real bump — and it
> was measured rather than reasoned.*
>
> **`tools/extract_v1_surface.py` compares the document's own `info.version` with `surface.yaml`'s
> pin and errors when they differ**, before anything it reports is worth reading. Measured on
> 2026-09-02 against the `10.11.11` document with its version rewritten to `10.11.12`: exit 1,
> *"version mismatch: surface pins 10.11.11, document is 10.11.12"* as the **only** error, all 59
> path, method and operation checks having passed. So *"fetch the new document; run the surface
> validator"* is a step that answers `1` for a reason that has nothing to do with the surface, and
> a sequencer obeying its own rule would stop the procedure there, every time, before reporting the
> disappeared paths step 1 exists to report. The fix keeps step 4 the only writer: the surface is
> **copied** into the git-ignored output directory with the pin moved and the copy is validated —
> 59 endpoints consistent, and a deleted path then reported as *"GET /System/Info/Public: path not
> present in the pinned document"*, which is what a breaking change looks like from here.
>
> **The pin is in five files and nine places, and no document listed them.** `surface.yaml` holds
> the document version and the source tag; `property-names.json` records the document it was
> extracted from; `src/atrium/__init__.py`'s `REFERENCE_VERSION` is what the server *reports* to
> clients, which Principle I makes load-bearing; `tools/_reference.py` pins `IMAGE_VERSION` and
> `IMAGE_DIGEST`; reference-target §1 is the table all of them are supposed to agree with. Two
> tests already fail when a pair of them drift — which catches a half-done bump *after* it has been
> committed. So step 4 locates every one of the nine **before writing any**, reads each back
> afterwards, and refuses the set if one anchor matches zero lines or two: *"a scripted edit that
> cannot fail is a scripted edit that will silently not happen."* `--image` is required, because
> ADR-0007 pins by digest and a version this repository cannot stand up is one it cannot measure.
>
> **The move is measured, and an unreadable version is the false-bump path.** Which of
> reference-target §1's two rows is moving is decided by asking the reference its own version and
> comparing it with the **behavioural** row — so there is no flag to spell the answer with, which
> is what makes *"no flag skips step 2"* a property and not a promise. The dangerous case is the
> third one: a server that does not answer. Called contract-only, that is a bump that skips the
> differential and writes the pin having measured nothing, with every step green — so it is
> `UNDECIDED`, and the command stops **before step 1**. The same guard reads the `Server` header
> and refuses a `--jellyfin` answering `Atrium/…`: `ProductName` cannot make that distinction
> because Atrium answers `"Jellyfin Server"` there on purpose (behaviours §4.1), and a bump
> measured against Atrium confirms the pin against itself.
>
> ***A changed reference and a dead container arrive as the same non-zero exit, and separating them
> is the exit codes the children already promise.*** A probe's `1` is a contradiction, `2` is *it
> could not look*, `3` is T13's leak — a failure of the bump and emphatically not a success because
> it is not `1`. `differential.py`'s `1` covers **two** things and its own summary line separates
> them: zero differences with forty-one cases not asked is not a reference that changed, it is a
> reference that stopped answering, which is exactly what plan §7's mid-sweep `SIGILL` produces.
> The `SIGILL` itself reaches the command as `2` — because all three probes that stand up their own
> instance convert an `InstanceError` into a `ProbeError`, which `tests/unit/test_version_bump.py`
> now asserts on each of them: without that conversion the exception escapes `_probe.main`, the
> traceback exits `1`, and a container's death would be triaged as a difference nobody observed.
> **What is not distinguished, deliberately and in writing**: a reference that died mid-run from
> one that was never reachable. Both are `COULD_NOT_LOOK`, both mean nothing was measured, both are
> re-run — and the container's own exit code is not visible from here, because `--rm` has already
> taken it.
>
> *Proven the way this repository proves a guard.* Four were deleted in turn and the suite re-run:
> the `break` that stops the procedure (three parametrisations fail), the fail-closed `UNDECIDED`
> (two), the locate-before-write pass in `apply_all` (two), and one probe's `InstanceError`
> conversion (one). The four steps are each made to fail in turn and each asserts twice — that the
> command stopped, **and** that no later step's tool appears in the runner's record. Nothing in the
> suite opens a socket or starts a process: the child runner and the version reader are the two
> seams `Context` holds, and the nine pin edits are located against the real repository under
> `--dry-run`, which writes nothing.
>
> *Routine calls taken.* **Step 3 runs every probe and fails as a step, not at the first
> contradiction** — the probes are independent and nothing downstream consumes one's output, so
> stopping early would cost a day per finding and buy nothing; what stops is the *procedure*, and
> step 4 does not run. **The command line it builds is per probe**, read with `ast` rather than by
> importing: the three that refuse a server argument are handed none, and `--allow-writes` goes to
> the ones that accept it — cross-checked against every probe's own `--help`, **56 probes, 31
> accepting the flag, zero mismatches**. **Step 3 re-dates only the `Last verified` header of what
> a probe *said* it confirmed, read from the probe's own report**, and touches no citation: a
> `[probe: …, Jellyfin 10.11.11, 2026-08-27]` records what was measured and when, and rewriting the
> version inside it would turn a measurement into a claim (Principle II). A `spec.md` named by a
> probe has no such line and is reported as left alone. **`--dry-run` executes nothing and writes
> nothing**, and is also what lets the suite drive step 4 against the real repository. Verified
> under **3.9.25**: `--help`, and all five refusal paths end to end against a local stub that is
> not a Jellyfin. Nothing was written to any server, and no container was started. The spec needs
> no amendment — §3.8 is a WHAT and every one of these is a HOW — so [plan §6.9](plan.md#69-the-version-bump-command)
> carries all five, `tools/README.md` gains the command and loses the paragraph saying a runner
> over every probe was *"deliberately not here yet"*, and
> [conformance.md](../../docs/compatibility/conformance.md#when-the-reference-version-moves) says
> its four steps are now a program.
>
> *What T15 must know.* **This feature now has a tool that writes into `src/`**, which nothing else
> under `tools/` does — the acceptance map should not mistake `bump_reference_version.py` for a
> probe, and `test_probe_convention.py`'s sweeps are over `probe_*.py` and do not see it. **AC-12
> is a test and not a command**: `tests/unit/test_version_bump.py` holds it, with
> `test_a_failed_step_stops_the_procedure_and_the_later_steps_do_not_run` as the four-way
> parametrisation and `test_no_flag_skips_step_two_when_the_running_reference_changed` as the
> exhaustive sweep over the parser's own options — both resolvable as `module:function` by the map,
> since this file is under `tests/` and imports nothing from `tools/` as a package. **The count of
> probes is 56 and not the 53 the plan says**, which matters to §6.10's prose more than to
> anything else. And **the pin's nine places are now written down** in plan §6.9: if T15 moves any
> of them, `test_every_pin_this_step_writes_is_locatable_in_the_files_that_ship_today` fails, which
> is the intended way to find out.

## T15 — The ignored-parameter report, the acceptance map, the levels, and 010 is Implemented

- [x] **Changes:** two things, and the first is D-5. `src/atrium/compat/query_params.py`'s
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

> **Done (2026-09-02) — and the one thing this task must not do, it did not do: it did not flip a
> status line over an unproven criterion.** *An acceptance criterion says something its own
> measurement contradicts, and it is the criterion that is about this project rather than about
> this harness.* **Its owner took D-7 the same day and 010 is `Implemented`** — this note is the
> record of what the task measured and of the call it declined to make, and the paragraph below is
> read against the criterion as it stood before the amendment.
>
> **AC-2 is not satisfied, and it cannot be satisfied by anything 010 is allowed to do.** It reads
> *"both servers, pointed at the same built fixture, produce libraries with the same item count and
> the same structure"*. Measured, over the six libraries T11 composed: the reference makes **74
> items**, and the two readings differ in **forty-seven declared places**
> `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]` — a zero-byte film that is
> an item there and not here (003 §3.2), twenty-five files named differently, an empty library that is
> *nothing at all* to the reference, and every library's own root row. The harness did its half and
> did it well: `tests/library/test_reference_reading.py` compares Atrium's scan against the recorded
> reading in the default job with no Jellyfin anywhere, an undeclared difference fails and a
> declared one that has gone away fails too. What it cannot do is make the criterion true, because
> **deciding what Atrium does about a difference this feature finds is outside this feature**
> ([spec §2](spec.md#2-scope)) — every one of the forty-seven belongs to 003 or 004. AC-2 is the
> only one of the eighteen that asserts a property of *Atrium's conformance* rather than of the
> harness, and that asymmetry is the evidence: it was written on 2026-08-26, before anything had
> been measured, and it did not survive being measured. **Reserved as D-7 below with a
> recommendation, rather than taken here**, because amending an accepted criterion is the shape of
> D-3 and D-6 and belongs to its owner. Until it was taken, `spec.md`, `plan.md` and this file said
> `Accepted` and `specs/README.md`, `docs/roadmap.md` and AGENTS.md said the same thing — *a status
> line that overstates the work is the one thing this task exists to prevent.* **Taken 2026-09-02,
> the recommendation accepted**: AC-2 now states the recorded comparison this task built, and all
> six documents moved together in the commit that took it (the D-7 row above).
>
> **A criterion with no test at all, which is 009 T14's finding arriving in the feature least
> entitled to it.** **AC-11** — *"the default CI job passes with no Jellyfin available and no
> network access"* — was mapped by [plan §8](plan.md#8-testing-strategy) to *"CI, unchanged"*, a
> claim about a workflow file and a `conftest.py` fixture with **nothing asserting either**. 010 is
> the feature whose entire value is a second server, so it is the feature most likely to grow a
> test that needs one; three tests now hold it. The socket guard is proven by **making it fire**,
> because a guard nobody has watched refuse may already have been replaced by an earlier fixture.
> The `needs_reference` sweep asserts that the **only** test in the repository carrying the marker
> is 004's live-provider replay — a differential test that quietly became opt-in would be reported
> as coverage by a job that never ran it, which is 008 T18's finding one directory away. And the
> workflow is read for a container runtime, the harness, the instance command and a reference URL,
> which is ADR-0007's premise rather than its consequence.
>
> **A criterion half with no test, in the mechanism Principle II rests on.** **AC-7** is two claims
> joined by *and*: *"every probe prints a citation in the documented form"* **and** *"exits non-zero
> when its finding contradicts the documentation"*. T13 asserted the second. The first was asserted
> nowhere on either side of the run — the sweeps check that a probe reaches `_probe.main`, and both
> report tests read the exit code and the contradiction message and threw the output away, one of
> them calling `capsys.readouterr()` purely to discard it. A citation is what turns a finding into
> provenance; a finding printed in another shape is one no document can cite.
> `test_a_report_prints_the_citation_in_the_documented_form` asserts AGENTS.md's own three fields.
>
> ***And the levels check found the report saying `yes` where it had measured half a table.*** The
> coverage section printed `| Endpoint | Declared level | Compared |` from a **flat set** of
> endpoints, so a row reached by the administrator alone read exactly like one both seats reached —
> on a surface where **12 of 23 reads answer differently to a restricted non-administrator**, two of
> them as shorter lists rather than as refusals ([spec §3.9](spec.md)). That is this feature's own
> characteristic failure arriving inside its own report: a declared conformance level claimed from
> the one seat that can be refused nothing. It says `**partly**` and names the seats now, and
> `test_an_endpoint_compared_from_one_seat_of_two_is_partly_and_never_yes` fails when either half is
> dropped. **`surface.yaml`'s `level` column also has its first reader**:
> `tests/conformance/test_routes.py` — the module that had read `feature` and `consumers` and never
> `level` — now asserts the distribution (1 L1, 50 L2, 8 L3), names the eight L3 endpoints so a row
> promoted into or out of L3 fails rather than drifting, and checks each belongs to an implemented
> feature that serves it. `tests/unit/test_allowlist.py` already held the other half, that each of
> the eight has a case per seat.
>
> **What no run has done, stated rather than implied.** **The eight `level: L3` rows have not been
> shown to reach L3.** T12 ran fourteen of the twenty named comparisons against a real pair; no
> complete sweep of the 84 cases is recorded anywhere, and until this task the report could not have
> said which endpoints were compared *per identity* even if one had. And the reason is structural
> rather than incidental: **a running Atrium cannot be given a library at all.**
> `atrium.library.config.create` and `atrium.library.scan.scan` have **no caller** in `src/` or
> `tools/` — only the test suite calls them, and `config.toml` has no libraries section — so
> `--fixture`, which `tools/README.md` says *"means the fixture on **both** servers"*, can put it on
> only one of the two. That is a v1 condition the roadmap already files (*"Libraries: add, rename,
> remove, list, trigger a scan"* is v2's CLI, and v1's way is *"direct database access"*), not a
> defect found here — but it is why AC-2 had to become a recorded reading, and it is on the owes
> list below rather than left for the next person to rediscover.
>
> **Six of the twenty named comparisons are outstanding, and two of them are outstanding because
> they are not comparisons.** T12's numbers, restated because a report that counts them as run would
> be claiming coverage this feature does not have: the two `rescan` rows (behaviours §5.2 and §5.6)
> need a second scan on **both** servers and **Atrium has no library-refresh route** —
> `POST /Library/Refresh` is the reference's and Principle VI keeps it out — so only the reference
> half can be taken, and a one-server reading is not a differential. Both entries carry their
> reference-side reading and both rows stay outstanding, which is the only honest shape. The other
> four: burn-in, whose two transcodes per side killed the instance before it answered; the
> manifest's announced track name, where the reference answers `400` to the master playlist of the
> fixture film that has an `ass` track; and the last two rows of §3.10, which are ordinary request
> cases and need a **sweep**. AC-16 is satisfied — twenty rows, each run or reported outstanding by
> name — and the run is not clean, which is what AC-16 exists to make visible.
>
> **D-5 landed, and the client is read in two places rather than one.** `record` keys on
> `(route, parameter, client)`; the raw-ASGI middleware reads the client from the scope for an
> undeclared query key, and a route hands its own parsers a **client-bound recorder** for a dropped
> enum token, which happens three frames above the headers — so `known_tokens` takes a `Recorder`
> protocol and a parser never learns that a client exists. The tally is written in the lifespan's
> `finally`, to `<data dir>/ignored-parameters.json`, suppressed on `OSError` because losing a
> diagnostic on the way out must not turn a clean stop into a traceback. **The consequence nobody
> had written down**: a differential runs against a server that is still answering, so what
> `--ignored-parameters` reads is that server's **previous** run — the tally is complete only after
> the last request a route could have answered, which is the same sentence as *"it can never be a
> route"*. The report says which tally it read and when, rather than implying it covers the sweep
> beside it.
>
> *One sentence T12 left for this task, and it is left alone deliberately.* Spec §3.10, *"What the
> gate changed"* §3 and the named-comparison register all say behaviours §5.2 *"carries the only
> surviving `⚠️ UNVERIFIED` in the compatibility documents"*. It stopped being true the moment that
> row ran and the marker was discharged — the belief was wrong, and an emptied container is
> **still fetchable** on the reference, which is parity rather than a gap. The sentences are the
> record of why the row was added, and rewriting them would amend an accepted spec to restate a
> justification rather than a criterion. [behaviours §5.2](../../docs/compatibility/behaviours.md)
> carries the reading, which is where a reader looking for the claim goes.
>
> *Routine calls taken, none of which touches an accepted document's criteria.* **The acceptance map
> is written and 010 is in `FEATURES`** although it was not yet `Implemented` when this task ran:
> the map only *requires* implemented features, and writing the eighteen rows then is what makes
> every criterion's proof named and unable to rot, so taking D-7 was one line rather than a task —
> which is how it went, the same day. Three of its entries carry
> what they do **not** prove — AC-2's contradiction, AC-15's *"created and destroyed by the run"*
> being unsatisfiable on Atrium by design, and AC-3's *"covers every endpoint"* being a property of
> the declared cases and not of any run. **`recorded()` in `tests/conformance/test_image_routes.py`
> sums the client away** rather than three assertions gaining a column they are not about.
> **Plan §1's and §3's `53 probes` are 56**, which T14 flagged and §6.10's own note had already
> fixed in the place it mattered. **`bump_reference_version.py` is not a probe** and the map does not
> treat it as one: AC-12 resolves to `tests/unit/test_version_bump.py`, as `module:function`.
> **`surface.yaml` is unchanged and the router serves the same 59 routes** —
> `test_no_route_ships_ahead_of_its_feature` reports exactly what it reported before, which is the
> assertion that catches a harness that grew an endpoint, and 010 owns no row of the surface.
>
> *Nothing was written to any server, and no container was started.* Every finding above came from
> the files in this repository, the tests already here and the readings the fourteen tasks recorded.
> The full gate is green: `ruff check`, `ruff format --check`, `mypy` over 132 source files, the
> whole suite, and `tools/extract_v1_surface.py`.

---

## Definition of done

The feature is done when **all** of these hold. **One of them holds in part and says so rather than
rounding up**: the L3 line below. `Implemented` here means the fifteen tasks are done and the
eighteen criteria are proven by tests that assert what the criterion says — it does not mean the
harness has swept everything, and what it has not swept is on the owes list rather than inside the
status word.

- [x] Every one of spec §5's **eighteen** acceptance criteria has a passing test, named in
      `FEATURE_010`. **All eighteen are named, every named test exists, and the map is green.**
      **AC-2 was the one whose tests did not assert what the criterion said**: the reference's
      reading of the fixture is recorded by `probe_reference_scan.py` and checked in, and Atrium's
      scan is compared against the record in the default suite (*"What the gate changed"* §1) — and
      that comparison's answer is **forty-seven declared differences**, where the criterion claimed
      *"the same item count and the same structure"*. **D-7 was taken on 2026-09-02 and the
      criterion now states that comparison**, so the four tests named for AC-2 assert what it says:
      the record and its citation, the item count of every library, the declared count, and the two
      failure directions — an undeclared difference and a declared one that has gone away. The
      forty-seven themselves are 003's and 004's to decide (spec §2), and this box is not a claim
      that any of them is closed.
- [~] Every endpoint reaches the conformance level declared in `surface.yaml`, and for the **eight
      rows declared L3** that is a claim this feature is the first thing in the repository able to
      make. The report names them and says which were compared, per identity. **The machinery is in
      and the claim is not yet paid**: `surface.yaml`'s `level` column has its first reader
      (`tests/conformance/test_routes.py`), each of the eight has a request case per seat
      (`tests/unit/test_allowlist.py`), and the report says `**partly**` and names the seats where
      it used to say `yes` from a flat set — but **no complete sweep of the 84 cases against a real
      pair is recorded anywhere**, so no L3 row has been shown to reach L3. On the owes list below.
- [x] `surface.yaml` is unchanged and the router serves the same 59 routes. **This feature adds no
      endpoint**, and the ignored-parameter tally is a file in the data directory precisely so that
      it cannot become one — asserted by
      `test_the_tally_is_written_to_the_data_directory_at_shutdown_and_to_no_route`, which sweeps
      the router for a path that would serve it.
- [x] Every one of `§3.10`'s **twenty** named comparisons is run or reported outstanding **by
      name**, and an outstanding one keeps the run from being clean. The four D-6 added are inside
      that count and not beside it. **Fourteen ran on 2026-09-02 and six are outstanding**, two of
      them because they are not comparisons at all: the reference has `POST /Library/Refresh` and
      Atrium has no library-refresh route, so behaviours §5.2 and §5.6 can take only the reference
      half.
- [x] Every allowlist entry declares a `behaviours.md` section or one of the four derivation
      classes, is scoped by endpoint and JSON pointer, and carries a date — and an entry that
      excuses nothing on a run is reported, because the allowlist is a metric that should shrink.
- [x] The default CI job passes with no Jellyfin available and no network access, and **nothing this
      feature adds carries `needs_reference`**: the mutation proofs run on checked-in pairs, and
      `tests/conftest.py`'s socket guard is unchanged. **Asserted rather than claimed since T15**,
      in three tests — the guard proven by making it fire, the marker swept for across the whole
      suite, and the workflow read for a runtime, the harness, the instance command and a reference
      URL.
- [x] Every prior-measurement debt in `reference-target.md` has a probe script or a recorded reason
      it cannot have one, and the register's prose count matches its own table.
- [x] Anything learned during implementation is back in `spec.md` and `plan.md`, in the same change,
      and any decision a task escalates is taken by its owner rather than improvised. **D-7 was
      reserved and not improvised**, and its owner took it on 2026-09-02 — the recommendation
      accepted, the spec amended and dated in its frontmatter the way D-3's and D-6's were.
- [x] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`, with `specs/README.md`,
      `docs/roadmap.md` and `AGENTS.md` saying the same thing. **Done on 2026-09-02, in the commit
      that took D-7 and not before it.** A status line that overstates the work is the one thing
      this feature exists to prevent in others, and AC-2 was unproven until the criterion stated
      the comparison its own measurement supports. All six documents now say `Implemented`: fifteen
      of fifteen tasks done, eighteen of eighteen criteria proven — **and six of the twenty named
      comparisons still outstanding, with no L3 row shown to reach L3**, which is the line above
      and the owes list below rather than anything the status word covers.

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

## What this feature owes the next ones

Six lists fed into this one ([005](../005-item-query-api/tasks.md#what-this-feature-owes-the-next-ones),
[006](../006-images/tasks.md#what-this-feature-owes-the-next-ones),
[007](../007-user-data-and-playstate/tasks.md#what-this-feature-owes-the-next-ones),
[008](../008-playback-negotiation-and-delivery/tasks.md#what-this-feature-owes-the-next-ones),
[009](../009-playlists/tasks.md#what-this-feature-owes-the-next-ones),
[011](../011-subtitle-delivery/tasks.md#what-this-feature-owes-the-next-ones)) and this is what
comes back out. It is written here rather than in AGENTS.md so it cannot go stale.

**To 003, and it is the largest.** **A running Atrium cannot be given a library.**
`atrium.library.config.create` and `atrium.library.scan.scan` have no caller in `src/` or `tools/` —
only the test suite calls them, and `config.toml` has no libraries section. The roadmap already
files library administration under v2's CLI and names *"direct database access"* as v1's way, so
this is a recorded condition and not a defect found here; what is new is the price it puts on this
feature. `tools/differential.py --fixture` documents itself as *"the fixture on **both** servers"*
(AC-2) and can only put it on one of them, which is why AC-2 had to become Atrium's in-process scan
compared against a recorded reading, and why every `needs: fixture` request case resolves its
anchors against a reference holding the fixture and an Atrium holding whatever its operator loaded
by hand. Beside it: of the **forty-seven** declared differences in
`tests/library/test_reference_reading.py`, **twenty-five are one file named two ways** — 003's name
derivation against the reference's whole-filename and whole-directory rules — and **twenty-one are
container rows**, each written down with its reason; the forty-seventh is the zero-byte film that is
an item there and not here, which is 003 §3.2 meeting a server with no such rule.

**To 004 — answered on 2026-09-03, and the rule this row implied is not the one that holds.** **A
two-disc album still borrows `CD1`**, so it never reads its own `album.nfo`, where the reference
names the album after its directory — T10 fixed the *ordering* of `metadata/refresh.py`'s descendant
choice (relative path, not identifier, so a container borrows the same directory wherever the
library is mounted) and deliberately did not fix that the borrowing is a guess at all. 004 answered
it by measuring the container **paths** in this task's own recorded reading: of its 26 container
rows, the 18 carrying a directory and a kind Atrium's item tree also has sit at exactly that kind's
depth below the library root, so the rule is counted **down from the root** and not up from a file
([behaviours §2.27](../../docs/compatibility/behaviours.md#227-a-containers-directory-is-its-own-depth-below-the-library-root),
004 §3.2, AC-19). The common-ancestor rule the handover proposed was measured on the same tree and
scores **12 of 17** against the standing rule's 15 and the new one's 17 — it moves a series with one
season onto that season's directory. The defect was also wider than this row: the **artist** above
that album was borrowing the album's own directory, and a track sitting directly in an artist's
directory gave that artist the parent of the library root, which a refresh then read. **The
declared-difference table did not move**: the fixture has no `album.nfo` beside its two-disc album,
so the two rows this paragraph named are the *other* album's and they are still there.

**To 008 — answered on 2026-09-02, and the answer was not the one the row named.** A seat with all
three playback-processing permissions denied negotiated `SupportsTranscoding: true` here and
`false` there, measured against a real pair; it was the first difference this harness found in
Atrium rather than in a document, and per spec §2 it was 008's to decide. 008 decided it the same
day, and measuring first is what saved the fix: the comparison negotiates with an **empty body**,
and the all-three gate [behaviours §2.21](../../docs/compatibility/behaviours.md) describes belongs
to the profile path, which Atrium already had right. With no profile the reference reads **one**
permission per media kind off the source, so implementing the gate this row named would have made
the row agree and answered `true` for a seat denied video transcoding alone. **What this leaves the
harness** is one correction and one debt. The correction: `named_delivery_time_policy_refusal`
predicted two different delivery statuses from `/Videos/{itemId}/stream.mp4`, which takes no user
on either contract as this project records it, so the row could never have been *as documented* —
it now asserts the gate on both servers and a delivery neither refuses. The debt: **the
delivery-time force-copy edge is still uncompared**, and reaching it needs a **segment** URI built
by hand, because the reference hands a denied seat no address to follow.

**To 002.** **Atrium's user record defaults `is_hidden` to `false` where the reference's is set**
`[source: Jellyfin.Data/UserEntityExtensions.cs:174 @ v10.11.11]`, so the first account on each
server answers a different `/Users/Public` — one row here, none there, on a login screen. Recorded in
behaviours §2.2 by T13 and left to 002 for the same reason.

**To 011 and 005, and both are readings rather than decisions.** The image track's `400` arrives in
**10 ms** on the reference where 011 recorded twenty seconds, so that claim does not reproduce
against a four-second fixture film and needs a source whose extraction is expensive. And the
paused-session ticker freeze cannot be read at all yet: both servers commit
`PlaybackPositionTicks: 0` after eleven minutes of silence, so **neither commits the paused position**
and the freeze cited from the reference's source is invisible from the wire — what it needs is one
request more, proving the paused report was stored before the silence begins.

**To whoever runs the harness next, six things that are true of it today.**

1. **A full sweep has been run — on 2026-09-04, and it was not clean.** When this list was
   written, fourteen of the then-twenty named comparisons had run against a real pair on
   2026-09-02 and the 84 request cases had only ever been driven over stub wires, so **no
   `level: L3` row had been shown to reach L3** — the half of every feature's definition of done
   that was deferred here. [012 T10](../012-negotiation-inputs/tasks.md#t10--the-two-l3-rows-get-their-cases-and-the-two-comparisons-a-sweep-cannot-raise)
   swept both halves against a single-use instance of the pinned version: **seventeen of the now
   twenty-two named comparisons ran**, and `POST /Items/{itemId}/PlaybackInfo` came back
   `Compared: yes` from **both** seats, which is what its declared level had been claiming since
   008 and what nothing had checked. **What is still owed is a run that is clean**, and no figure
   from a past one is restated here: the report is `reference/differential-<date>-<sha>.md`,
   git-ignored and regenerable and never the input to anything ([plan §4.4](plan.md#44-the-outputs)),
   so the standing counts live in the run that produces them and nowhere else.
2. **The pinned image dies with `SIGILL`, exit 132, on about half of starts** on an `arm64` host
   with no emulation, at startup and mid-sweep alike (plan §7). It costs the readiness deadline and
   `--rm` has already removed the container before the run can read its logs, so the exit code is
   only visible to a watcher outside the run. Batching a run against an instance stood up by hand
   with `tools/reference_instance.py` and `--reference-url` is the working practice, and it is
   ADR-0007's degradation rather than a workaround.
3. **The sweep left rows on Atrium and not on the reference — fixed on 2026-09-05, and one
   comparison is reported unasked in its place.** Measured that day, after two completed runs
   against one Atrium: **four playlist rows** in its item table — `atrium-differential` twice and
   `atrium-differential-renamed` twice — and both names came back in a
   `GET /Search/Hints?searchTerm=a` comparison as rows the reference did not have, on a listing
   nothing about playlists was being asked of. The asymmetry is structural rather than careless:
   `--fixture` destroys its reference and everything it wrote (ADR-0007), and Atrium is whatever
   the operator is running.

   **The cleanup is declared and the route works; the leak is this program's own anchor cache.**
   `delete-a-playlist` says so in its own `what_it_is_for` — *"it is also how the sweep removes the
   one thing it created"* — and `DELETE /Items/{itemId}` answered `204` when it was issued by hand.
   What settles it is **who owns the rows**: the surviving `atrium-differential-renamed` belongs to
   the **administrator**, and `create-with-a-name` declares `identities: [restricted]`, so a seat
   that must never have issued that case has a playlist from it.

   `Issuer.answer_of` caches an anchor's answer under `(seat.role, endpoint#case)`, and **two leaks
   come out of that one key**:

   1. **The key carries the seat.** `rename-a-playlist` runs as the **administrator** and anchors on
      `response:POST /Playlists#create-with-a-name@/Id`. The administrator's key is not in the cache,
      so resolving the anchor **issues `POST /Playlists` again, as the administrator** — a playlist
      the register never asked that seat to make. `delete-a-playlist` is `restricted` and resolves
      through the restricted key, so nothing ever removes it.
   2. **The compared issue and the anchor issue are two issues.** The sweep issues
      `create-with-a-name` as the case it compares; anchor resolution issues it again to fill the
      cache. The delete removes the second. **Nothing removes the first.**

   One survivor of each per run, which is exactly the two rows and the two owners in the database.
   And a consequence that is not hygiene: **the sweep's create/delete pair is not a pair.** The
   delete removes a playlist the compared create did not make, so a server that leaked on creation
   and a server that did not would answer this case identically. The reference does the same thing
   and only its destruction hides it.

   **Both are closed.** `compare_case` asks for `issue_once`, so the sweep and the anchors share
   one answer and the delete now names what the compared create made; and a `response:` anchor
   whose case does not declare the referring seat is **refused** rather than issued, because which
   identity owns an anchor is `request-cases.yaml`'s question and not this program's. A `listing:`
   anchor still keeps the referring seat, and must: the row it names is that seat's own view.

   **What it costs, and it is owed to whoever picks this up: `rename-a-playlist` is now reported
   unasked on every run.** Widening `create-with-a-name` to the administrator does not settle it on
   its own — within a seat's phase this register runs `delete-a-playlist` before
   `rename-a-playlist`, so the rename would meet a playlist that had just been deleted. Re-anchoring
   or reordering is the register's call, and the latent ordering assumption is worth knowing about
   either way.

   Runs from before the fix are still not comparable with each other: what earlier runs left is
   still on whatever server they were pointed at.

4. **A `listing:…@0` anchor is not the same item on the two servers when their orderings differ,
   and one listing's already does.** Measured 2026-09-05
   `[probe: tools/differential.py's own client, by hand, Jellyfin 10.11.11, 2026-09-05]`:

   | anchor listing | Atrium row 0 | reference row 0 | |
   |---|---|---|---|
   | `movies-by-sort-name@0` | 2 Fast 2 Furious | 2 Fast 2 Furious | same (31 vs 32 rows) |
   | `audio-by-sort-name@0` | By One Artist | Ninety Six Kilohertz | **different** |
   | `series-by-sort-name@0` | 24 | 24 | same |
   | `albums-by-sort-name@0` | The Album | The Album | same |

   **This is the failure §4.2's anchor note was written to prevent, arriving by the other door.**
   That note keeps identifiers out of anchors because *"the two servers derive those differently by
   design, so a case that carried one would be comparing two different items"* — and a **position**
   does the same thing whenever the two orderings differ. All 43 listing anchors in
   `request-cases.yaml` name position `0`, so today it bites exactly one listing and the **twelve
   cases anchored on it**: the three audio delivery routes and the user-data routes the music client
   calls. `movies-by-sort-name` holds 31 rows here against 32 there, so it agrees at position 0 by
   one row.

   **What it cost on the run that found it:** the four audio comparisons reported `500` here against
   `200` there, which reads as a delivery defect and is not one — Atrium was asked for the fixture's
   filler-byte FLAC and the reference for a file it can decode. The `500` is real and is 008's; the
   *comparison* proves nothing about it.

   Not fixed here, because the remedy is a scope call: an anchor that names a row by something both
   servers agree on (a path is not available — §4.2 says so — and a name is 003's derivation), or a
   listing whose order cannot diverge, or a report that says when the two anchors resolved to
   different items. **The cheapest honest step is the last one**: the run already has both
   identifiers in hand when it resolves an anchor, and saying *"these two rows are not the same
   item"* costs one line and turns a silent mis-pairing into a stated one.

5. **Two of the twenty named comparisons are not comparisons.** behaviours §5.2 and §5.6 need a
   second scan on **both** servers; `POST /Library/Refresh` is the reference's and Principle VI
   keeps it out of the surface, so only the reference half can be taken. Both entries carry that
   half and both rows stay outstanding — a one-server reading is not a differential, and counting it
   as run would be this feature claiming coverage it does not have.

6. **The sweep writes to the server under test, and the next run reads what it wrote — this one
   changes results rather than leaving litter.** Two identical runs against one Atrium, nothing
   touched between them, measured 2026-09-05:

   ```
   run A  708 differences      run B  752
   identical in both  703      only in A  5      only in B  49
   ```

   **703 of 708 rows are stable**, so this is not noise: `listing-ordered-at-random` contributes
   exactly **one** row. Of the 49 new ones, **36 are one thing counted three times** — twelve
   `Configuration` keys reported missing on `/Users/Me`, `/Users/{userId}` and
   `POST /Users/AuthenticateByName`. The cause is in the database:

   ```
   atrium-differential-admin             442 bytes  {"CastReceiverId": "F007D354", …}
   atrium-differential-restricted         91 bytes  {"PlayDefaultAudioTrack": true, …}
   atrium-differential-playback-denied   442 bytes  {"CastReceiverId": "F007D354", …}
   ```

   `POST /Users/Configuration` is a declared case, the sweep issues it as the restricted seat, and
   the stock 442-byte configuration is replaced by the case's own 91-byte body. The single-use
   reference is destroyed and comes back stock; the server under test keeps it.

   **It is the asymmetry item 3 records, in a worse place.** A leaked playlist is a row in a
   listing; this changes what a comparison *concludes*, and it does so **within a run as well**:
   an endpoint compared before the write sees the stock configuration and one compared after sees
   the case's. Run A had the write land mid-sweep, which is the whole of its five-row difference
   from B.

   **Taken on 2026-09-05, and by none of the three shapes this entry first listed.** They were: the
   sweep restores what it overwrote, the run refuses to start against a server still holding an
   earlier run's writes, or the report names the comparisons taken after a write. What the register
   turned out to want was **none of them**, because it had already stated the rule in prose —
   `replace-configuration` is *"the restricted seat alone: … the only account a run may overwrite is
   the one it created and destroys"*. That premise holds on the reference, whose seats a run makes
   and destroys with it, and fails on the server under test, where every seat is handed in because
   the three account routes are outside the v1 surface.

   So the fix reads the sentence rather than adding a mechanism: `needs` gains **`owned-seat`**,
   `unmet_need` resolves it with the seat in hand and names only the side that was handed in, and
   the case is reported unasked with the reason — the machinery that was already there. The
   comparison still runs against the reference. §4.2's vocabulary moves with it, amended and dated
   in the plan's frontmatter.

**And one thing this feature hands back rather than forward.** The three remaining
prior-measurement debts in [reference-target.md](../../docs/compatibility/reference-target.md) are
*"one author's afternoon and one library scanned twice"*: the `SortBy` closure — the cheapest of the
three and the only one with a shipping client waiting on it, since a music client sends three tokens
outside the eight this project implements — and the item-identity row's second half, *stable across
rescans*, which needs the single-use instance and a library scanned twice rather than a new probe.
