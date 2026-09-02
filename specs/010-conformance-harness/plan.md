---
feature: 010-conformance-harness
title: Conformance harness — implementation plan
status: Accepted
accepted: 2026-09-01
created: 2026-09-01
updated: 2026-09-02
amended: 2026-09-02 at the tasks gate — reviewing the list against the code this plan names found two things it got wrong about this repository, and both are corrected above rather than left to a task's Done note. **§8's AC-2 row could not be written:** it maps the criterion to a probe run "by hand", and `tests/conformance/test_acceptance.py` resolves every entry as `module:function` through `importlib` while §2 of this plan inherits the rule that a `tools/` module is reached by path and never as a package — so the row would fail on import the day 010 flips to `Implemented`, which is 009 T14's *"a criterion with no test at all"* arriving one feature early. The probe now **records** the reference's reading of the fixture and the test compares Atrium's scan against that record, so AC-2 is checkable in the default job with no Jellyfin anywhere. **And §4.3's floor was the right floor for the surface and the wrong one for eight rows:** `surface.yaml` declares eight endpoints at `level: L3` and nothing in the repository has ever checked that a declared level is reached, while every feature's definition of done has been deferring exactly that half here — those eight are seeded first, per identity, and the report prints the declared level beside the coverage. A third finding is recorded in the task list rather than here, because it is a scope call on an accepted spec and is reserved for its owner as D-6: §3.10's sixteen named comparisons do not carry four debts that need precisely what D-1's instance provides, including the only surviving `⚠️ UNVERIFIED` in the compatibility documents (behaviours §5.2), whose own text names a disposable library as the remedy. **Amended again on 2026-09-02, hours later, by D-6 being taken:** the recommendation was accepted, so **§3.10 is twenty named comparisons and not sixteen**, and every place this plan counted them moves with it — §3's file tree, §3's argument for machine-readable registers, §4.2's register, §6.4's runner shapes and §8's row 16. §4.2's `needs` vocabulary gains `rescan` and `wait`, and §6.4 grows from four shapes to six: **the library changed underneath a rescan** (behaviours §5.2 and §5.6, where the signal is the difference between two scans) and **a reading after a deliberate wait** (007's paused-session ticker). The clause above recording D-6 as reserved is what this supersedes; 009's plan §8 went stale in exactly this way and the audit of 2026-09-01 caught it **Amended again on 2026-09-02 by T3, which wrote §4.1's file.** The allowlist has a **seventh field, `case`**: two rows of spec §3.3 are conditioned on the request and not on the route — `TotalRecordCount` on a by-name call carrying no limit, and the rows of a listing ordered at random — and with six columns each would have been strictly wider than the prose it came from, the second excusing the rows of every listing on every request. §6.3's `resolve(endpoint, case, identity)` already took the dimension; only the column was missing. It never widens: `*` is what an entry with no condition says, and an id no request case declares matches nothing, so the failure direction is under-excusing. §4.1's table carries the field. **Amended again on 2026-09-02 by T4, which landed the two array kinds.** §6.2's steps 1, 3 and 4 each said less than the code needs. **Step 1's cascade guard suppresses the *positional* comparison and never the comparison an array's own kind still owes**, or it deletes step 4 on the only endpoint step 4 exists for: `Similar` answers `limit + 4` rows on a movie seed (behaviours §3.24), so that array's two lengths differ on every run. **Step 3 did not say what an `unordered` array does when the multisets genuinely differ**, and the shape that asks is measured — the reference's artist paging duplicates rows as well as losing them, so a page holds one row twice and another not at all at an unchanged length, which neither the `LENGTH` guard nor the `ORDER` class catches; the rows that match are removed and only the residue is compared, and §9's risk row is corrected to say so. **Step 4's row walk is position-free**: the reference suppresses nulls globally, so a row's key set depends on which item it holds and a draw guarantees the two sides hold different items — pairing row 0 with row 0 would report content as shape. No acceptance criterion moves: AC-17 keeps the row count compared, which makes `Similar`'s `limit + 4` a difference the report states on every run rather than one the allowlist excuses. **Amended again on 2026-09-02 by T5, which wrote §4.2's register.** The named-comparison rows have a **seventh field, `written_at`**, because `behaviours` — *"the section that is the answer"* — cannot be filled on a quarter of them: **five of the twenty have no `behaviours.md` entry at all**, which is what that document is (an entry records what the reference *does*, and nobody has watched it do these — the same sentence as *"a sweep cannot raise it"*), and four more are answered by a row of §5's table, which carries no anchor of its own. `behaviours` therefore takes `none` and `written_at` names the document the row was collected from. It measured something the field was not asked for: **nineteen of the twenty came from one of the six inherited lists and behaviours §5.2 came from none of them**, which is precisely what the task list meant by *"the six lists **and** the compatibility documents"*. §4.2 also records that an **empty `needs` is a value**: the last two rows of §3.10 are ordinary request cases and need nothing at all, and a reader treating `[]` as an absence would drop two rows out of AC-16's twenty. No acceptance criterion moves.
spec_status_required: Accepted
spec_status_actual: Accepted
---

# 010 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour, and it was measured
> before this plan started: its four open questions are answered by four probes that now exist in
> `tools/`, and none of the four survived unchanged. Where this plan states a reference behaviour,
> the citation lives in the spec section it names, or inline where this plan read something the
> spec did not.
>
> **What this plan measured is this repository**, not the reference: the only reachable Jellyfin is
> an operator's production server, and nothing here writes to it. Every claim below about
> `tools/`, `tests/` or `docs/` was read out of the files it names, and §6.12 lists the four that
> came back false.

## 1. Approach

Six decisions carry the feature. Three are the spec gate's findings turned into a mechanism, one is
the thing that does not exist yet, and two were settled by reading this repository rather than by
reading either document — the first and the last, and both of them turned out to be smaller than
the spec makes them sound.

**The harness is a program, not a test, and the architecture already said where it lives.**
[architecture §3](../../docs/architecture.md#3-repository-layout) reserves `tools/` for *"probe
scripts, spec fetcher, differential harness"* and `reference/` for *"fetched OpenAPI, differential
reports"*, and [conformance.md](../../docs/compatibility/conformance.md#l3--differential) already
publishes the command line — `tools/differential.py --atrium … --jellyfin … --surface … --report
…`. So the placement is inherited rather than chosen, and with it the two constraints `tools/`
carries: **standard library only, on a Python 3.9 floor**, because a probe has to run on the
interpreter a machine already has and before any environment is built. That is not a hardship
here — 53 probes and `tools/extract_v1_surface.py`'s hand-written `parse_surface` already prove
that HTTP, JSON and this project's own YAML subset are reachable from the standard library — and it
buys the property the feature is about: **the thing that decides whether the server is right does
not depend on the server's own dependency set.** It is nonetheless a project-level constraint on a
component the size of this one, so it was put to its owner as D-2 in §11 — and **decided on
2026-09-01 as no change**: `tools/`, standard library, the 3.9 floor.

**Rows are compared by position, and a difference in order is its own class.** OQ-1 killed every
join key the wire could have offered (spec §3.2), so position is what is left — which promotes the
ordering into the contract under test. A comparison that only knew about *values* would then report
a reordered list as N value differences and say nothing about the one thing that actually differs,
so the engine has **five classes, not three**: keys, types, **length**, **order**, values. Length
and order exist because a positional comparison without them cascades: one inserted row at the top
of a thousand-row page is a thousand findings, and a report with a thousand findings is a report
nobody reads (spec §6, *"does not cry wolf"*). §6.2.

**The allowlist gains a second kind of entry and loses its global scope.** The spec's §3.3 already
says the first half — an excused *array* is a different mechanism from an excused *field*, because
what `/Items/{itemId}/Similar` needs is the whole array excused. The second half is this plan's,
and it is measured: a field-level entry that names a bare field name would excuse that field
**everywhere**, and `ChildCount` is not only the reference's random number on a library view — it is
a real computed aggregate over a container's subtree in this server (`db/item_queries.py`'s
`ContainerAggregates`, gated by `api/items.py`'s `_AGGREGATE_FIELDS`), asserted by L2 on the album
that has two discs. Excusing the name would excuse the value L2 exists to check. **So every entry
is scoped by endpoint and by JSON path**, and the allowlist stops being a list of names. §6.3.

**The reference instance is the bulk of the feature, and it is a subprocess with a bind mount and a
`finally`.** Nothing like it exists. A run that needs the fixture on both servers starts a
container of the pinned version, hands it the built fixture tree read-only, drives the first-time
setup over HTTP — the operations that exist for exactly this, which declare a **first-time-setup**
authorization policy where `POST /Users/New` beside them declares elevation `[spec: the security
requirement declared on UpdateInitialConfiguration, UpdateStartupUser, CompleteWizard,
AddVirtualFolder and CreateUserByName]` — waits for the scan, runs the comparison, and destroys the
instance and everything it wrote. Single use, so a leak inside it is harmless; owned by the run, so its
destruction is a `finally` and a startup sweep rather than a discipline. §6.5, §6.6. **The runtime
this introduces is adopted, and it has a record of its own** — D-1 in §11, taken on 2026-09-01 as
[ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md).

**Identity is a dimension of every request, not a mode of the run.** Spec §3.9 measured 12 of 23
reads answering differently to a restricted non-administrator, two of them as *shorter lists*. A
harness with a `--restricted` flag would make the second identity a thing somebody remembers; a
harness whose request loop is `for identity in identities` makes a single-identity run something
the **report says out loud** (AC-14). The seats are created and destroyed by the run, and a run
that finds one already present refuses to start (AC-15) — which is the 28-playlist lesson turned
into a precondition rather than a promise. §6.7.

**The probe convention is already code, and what 010 owes is enforcement and the debt.** Spec §3.5
reads as a specification for something to be built; `tools/_probe.py` has been it since 002. Its
`Probe(script, question, document, section, expectation)` prints the finding, prints the citation
in the documented form, and returns `1` from `report()` when the finding contradicts the
expectation — AC-7 and AC-8, in a file 53 probes already share. So the work is not writing the
convention: it is a sweep that no probe can escape it, the cleanup contract §3.5 states and the
server disproved, and the prior-measurement register — which is stale in four rows, three of them
because the debt was *paid* under a different script name and nobody struck the row. §6.10, §6.12.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–009 and 011 | [009 plan §2](../009-playlists/plan.md#2-inherited-decisions) |
| `tools/` holds the probes, the spec fetcher and the differential harness; `reference/` is git-ignored and holds fetched documents and reports | [architecture §3](../../docs/architecture.md#3-repository-layout) |
| `tools/` is standard library only, on a Python 3.9 floor, and CI runs `--help` on every non-underscore script at both ends of the range | [tools/README.md](../../tools/README.md), [.github/workflows/ci.yml](../../.github/workflows/ci.yml) |
| A probe answers one question, prints its citation, and exits non-zero on a contradiction | `tools/_probe.py`, spec §3.5 |
| No job in CI contacts a Jellyfin server, and the suite fails any test that opens a TCP connection | `tests/conftest.py`, [AGENTS.md](../../AGENTS.md) |
| `@pytest.mark.needs_reference` is the declared exit from that guard, and was added for this feature | `pyproject.toml`, `tests/conftest.py` |
| A `tools/` module is reached from the suite by path, never as a package | `tests/conformance/test_routes.py`, `tests/conformance/test_universal_audio.py` |
| The four provenance forms, and that a claim without one keeps a document in draft | Principle II |
| The fixture worlds are built from a declared manifest, deterministically, and never checked in | `tests/fixtures/library/generate.py`, `tests/fixtures/media.py` |
| An acceptance criterion is bound to the test that proves it by a map the suite reads | `tests/conformance/test_acceptance.py` (001 T19, 003 T21) |
| Never copy Jellyfin's code; running its published server is reading the reference, not forking it | Principle IV |

**Deviations:** one, and it is D-1, decided on 2026-09-01.
[architecture §5](../../docs/architecture.md#5-deployment-shape) says the deployment shape is one
process and *"no second service"*. A fixture run starts a second service — a Jellyfin — for the
length of one comparison. That is a **development-time** dependency of a tool and not a deployment
decision, and nothing a user installs gains anything by it; the runtime it needs is nonetheless a
project-level choice with an ADR's shape, and it now has one:
[ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md), with
`architecture.md` §2 and §5 carrying the cross-reference.

## 3. Modules

```
tools/
├── _differential.py       new, pure: the comparison engine. No HTTP, no files, no clock -
│                          two decoded responses and a rule set in, a tuple of Differences out.
│                          Pure because the mutation proofs of spec §6 have to run in CI, where
│                          there is no server, and because a comparison that cannot be unit-tested
│                          is the one thing this feature must not ship
├── _allowlist.py          new: reads docs/compatibility/allowlist.yaml and the named-comparison
│                          register; resolves an entry against (endpoint, identity, JSON path)
├── _reference.py          new: the single-use reference instance - stand up, configure, scan-wait,
│                          destroy, and the sweep that destroys what a crashed run left
├── differential.py        new, the CLI conformance.md already documents. Adds --identity,
│                          --fixture and --named; writes the §3.4 report into reference/
├── reference_instance.py  new, the same instance stood up on its own and left running, for a
│                          human debugging a difference by hand. Its --help must not start one
├── bump_reference_version.py  new: §3.8's four steps in order, refusing to continue past a failure
├── probe_reference_scan.py    new: the first question the instance answers - what does a reference
│                          make of the fixture tree (§6.6). The one probe this plan adds
└── _probe.py              unchanged, and the reason §3.5 is mostly already done

docs/compatibility/
├── allowlist.yaml         new: the allowlist, both kinds, scoped. The single source; the prose
│                          tables in conformance.md and spec §3.3 are checked against it
├── named-comparisons.yaml new: the twenty rows of spec §3.10, each with what it needs and the
│                          behaviours section that is its answer
└── request-cases.yaml     new: the request cases per endpoint (AC-3), seeded from what the two
                           analysed clients send

tests/
├── conformance/test_differential.py  new: the mutation proofs of spec §6, driving _differential.py
│                          by path, with no server anywhere
└── unit/test_allowlist.py new: the registers are well-formed, and every prose table matches them
```

**Why the engine is a module and the CLI is a file.** Spec §6 proves this feature by mutation —
inject a removed field, assert it is reported in the key-set pass — and those proofs have to run in
the default CI job, which has no Jellyfin and must not have one. A comparison engine that takes two
decoded bodies and returns findings can be driven from `tests/` with two dictionaries;
one that takes two URLs cannot be driven at all. The split is what makes AC-4 a test rather than a
manual exercise.

**Why the registers are files and not tables in a document.** The audit of 2026-09-01 found 009's
plan §8 stale in four places and named the reason: *"a table of tests is the section most prone to
this: nothing reads it, so nothing fails when it drifts"* (M1). This feature would otherwise ship
three such tables — the allowlist in two documents, the twenty named comparisons in one — each
being the thing a run is measured against. So each is one machine-readable file that the tool
reads, with a test asserting the prose says what the file says. The prose stays, because the
*reasons* are the part worth reading; what it stops being is the source.

**Why no `src/atrium/` module.** Nothing here ships to a user. The harness compares a running
Atrium from outside, exactly as it compares a running Jellyfin, and a comparison that imported the
server's own code could agree with it by construction — which is 008 T16's lesson in this
feature's own shape: *a test that compared Atrium against itself passed while the contract was
broken*. The one place the server is touched is §6.8's ignored-parameter report, which is D-5 —
**taken**, in the smallest shape that report allows.

## 4. Data model

No database and no migration. What this feature owns is four checked-in files and two git-ignored
outputs, and their shapes are the data model.

### 4.1 `docs/compatibility/allowlist.yaml`

One entry per excused thing, in the same hand-written YAML subset `surface.yaml` uses, so
`tools/` parses it with no dependency.

| Field | Meaning |
|---|---|
| `kind` | `field`, `drawn` or `unordered` — the three of §6.3 |
| `endpoint` | The `surface.yaml` path and method it applies to, or `*` for a genuinely global one |
| `pointer` | JSON Pointer to the field or array, relative to the body; `header:<name>` for a header. RFC 6901's `-` stands for an array index, so a row of a list envelope is `/Items/-/Id` |
| `case` | A request-case id from `request-cases.yaml`, or `*`. **Added by T3**, because two rows of spec §3.3 are conditioned on the *request* and not on the route — `TotalRecordCount` without a limit, and a listing ordered at random — and with the six columns below each was strictly wider than the prose it came from: the second would have excused the rows of every listing on every request. `resolve(endpoint, case, identity)` in §6.3 already took the dimension; only the column was missing. It never widens — `*` is what an entry with no condition says, and an id no case declares matches nothing |
| `reason` | One sentence, in the prose the documents render |
| `because` | A `behaviours.md` section, or one of four declared derivation classes (§6.3) |
| `since` | The date the entry was added. The allowlist is a metric (spec §3.3) and a metric needs a clock |

**`endpoint`, `pointer` and `case` are what stop this file from being a list of names**, and they
are the columns a later reader will try to normalise away — a single global `ChildCount` row looks
like the same information, and it is the version that excuses the aggregate this server computes.

### 4.2 `docs/compatibility/named-comparisons.yaml`

Twenty rows, one per row of spec §3.10 — sixteen when this plan was written, twenty since D-6 —
each with `id`, `what`, `why_the_sweep_misses_it`,
`needs` (one or more of `identity:restricted`, `identity:playback-denied`, `fixture`, `rescan`,
`wait`, `latency`,
`bytes`, `twice`), `behaviours` (the section that is the answer), `written_at` and `runner` (the
callable in `tools/differential.py` that runs it, or `none` while it is outstanding).

**`needs` is the field that earns the file.** It is what lets the report say *"four outstanding, and
three of them because no fixture instance was available"* rather than *"four outstanding"*, and it
is what a run consults to decide whether a row is even askable before it counts it as a miss. Two
rows carry an **empty** `needs` and are still counted: the last two of §3.10 are ordinary request
cases (§6.4), so a reader that treated `[]` as an absence would drop two rows out of AC-16's twenty.

**`written_at` is the seventh field, added by T5**, because `behaviours` cannot be filled on a
quarter of the rows. **Five of the twenty have no `behaviours.md` entry at all** — the image
track's latency, the media source with no runtime, EXIF orientation, 005's OQ-7 and the paused
ticker — and that is what `behaviours.md` *is*: an entry there records what the reference does, and
nobody has watched it do any of these, which is the same sentence as *"a sweep cannot raise it"*.
Four more are answered by a **row of §5's table** rather than a numbered subsection, and those rows
have no anchor. So `behaviours` takes `none`, and `written_at` names the document the row was
collected from — one of the six inherited lists, or the compatibility document that carries the
question where no list does. It measured something too: **nineteen came from a list and
behaviours §5.2 came from none of them**, which is what the task list meant by *"the six lists
**and** the compatibility documents"*.

### 4.3 `docs/compatibility/request-cases.yaml`

Per endpoint, one or more cases: a name, the query, the body, the **anchor** that fills each path
parameter (§6.1.1), the identities it is meaningful for, and a sentence saying what the case is for. AC-3's floor is one case per endpoint — 59, measured
against `surface.yaml`, which holds exactly 59 endpoints today (40 `GET`, 14 `POST`, 5 `DELETE`;
one at L1, 50 at L2, 8 at L3). OQ-2's answer says that floor is *measurably not enough*: the two
differences the spec's own gate found on `/Items/{itemId}/Similar` are both invisible to a bare
request. So the file starts at the floor plus the cases the two analysed clients actually send, and
it grows by measurement rather than by combinatorics — 764 declared query parameters across those
59 operations is the number that makes "one case per parameter" not a plan.

**And the eight `level: L3` rows are seeded first.** *(Found at the tasks gate on 2026-09-02.)* That
column is a **required** conformance level and nothing has ever checked that one is reached:
`tools/extract_v1_surface.py` validates only that the value is one of `L0..L3`, and
`tests/conformance/test_routes.py` reads `feature` and `consumers` and never `level`. Meanwhile
every feature's definition of done ticks *"every endpoint reaches the conformance level declared in
spec §6"* with the differential half deferred to this feature — [009's](../009-playlists/tasks.md)
says so in as many words. So those eight are the only rows in the repository whose declared level
this feature is the only thing that can pay for: they get their cases before the other 51, one per
identity they are meaningful for, and §3.4's coverage line prints the declared level beside what a
run actually compared.

### 4.4 The outputs

`reference/differential-<date>-<sha>.md` and `reference/ignored-parameters-<date>.md`, both
git-ignored, both regenerable, neither ever the input to anything. The report's shape is spec
§3.4's, plus the per-identity coverage line AC-14 asks for.

## 5. Contracts

```python
# tools/_differential.py - pure

@dataclass(frozen=True)
class Response:             # what a case got back, from either server, already decoded
    status: int
    headers: Mapping[str, str]
    body: object | None     # the parsed JSON, or None where the body is bytes
    raw: bytes              # kept: three named comparisons parse or byte-compare instead

class Class(Enum):          # ordered by severity: the report ranks by this (AC-5)
    MISSING_KEY = 1         # b has it, a does not
    EXTRA_KEY = 2
    TYPE = 3
    LENGTH = 4              # an array whose lengths differ; suppresses its children (§6.2)
    ORDER = 5               # same multiset of rows, different order
    VALUE = 6

@dataclass(frozen=True)
class Difference:
    klass: Class
    pointer: str            # JSON Pointer into the body, or "header:Content-Length"
    atrium: object | None
    reference: object | None
    note: str = ""          # for ORDER, the permutation; for LENGTH, both counts

@dataclass(frozen=True)
class Rules:
    """Everything the comparison consults, resolved for one (endpoint, case, identity)."""
    excused_fields: Mapping[str, str]      # pointer -> reason
    drawn_arrays: Mapping[str, str]
    unordered_arrays: Mapping[str, str]

def compare(atrium: Response, reference: Response, rules: Rules) -> tuple[Difference, ...]
def compare_headers(atrium: Response, reference: Response, rules: Rules) -> tuple[Difference, ...]
```

Callers may assume: `compare` opens no socket, reads no file and consults no clock; it is total —
any two decoded bodies compare, including a list against an object, which is a `TYPE` at the root;
and **it never raises on a difference**, because a comparison that throws on the first surprise
reports one finding per run. A `Difference` names a pointer that can be pasted into the report and
read against either body.

```python
# tools/_reference.py

@dataclass(frozen=True)
class InstanceSpec:
    image: str              # the pinned reference version, by digest
    fixture_root: Path      # bind-mounted read-only
    label: str              # the sweep's handle on it, fixed across runs

class ReferenceInstance:
    """A Jellyfin that this project owns, uses once, and destroys.

    A context manager, because the destruction is the invariant: __exit__ runs on the exception
    path and on the success path, and the sweep in __enter__ removes whatever a killed run left.
    """
    def __enter__(self) -> "ReferenceInstance"   # start, wizard, library, scan, ready
    def __exit__(self, *exc: object) -> None     # destroy the container and its data directory
    url: str
    administrator: "Identity"
    def create_identity(self, role: Role) -> Identity   # §6.7; removed by __exit__
    @staticmethod
    def sweep() -> int      # containers and directories from earlier runs; returns how many
```

```python
# tools/differential.py

class Role(Enum):           # what §6.7 asks an instance for
    ADMINISTRATOR = "administrator"
    RESTRICTED = "restricted"
    PLAYBACK_DENIED = "playback-denied"

@dataclass(frozen=True)
class Identity:
    name: str               # Role.value
    token: str
    user_id: str
    created_by_the_run: bool

@dataclass(frozen=True)
class Case:                 # one row of request-cases.yaml, resolved
    endpoint: str           # the surface.yaml path
    method: str
    name: str
    query: Mapping[str, str]
    body: object | None
    anchors: Mapping[str, "Anchor"]  # path parameter -> how to resolve it per server (§6.1.1)
    identities: tuple[str, ...]      # the roles it is meaningful for; empty means all

@dataclass(frozen=True)
class RunReport:
    identities: tuple[str, ...]
    cases: int
    differences: tuple[tuple[Case, Identity, Difference], ...]
    named_run: tuple[str, ...]
    named_outstanding: tuple[tuple[str, str], ...]   # id, why
    def is_clean(self) -> bool
```

**`is_clean` is the contract that makes AC-16 real.** It is false while any difference is untriaged
**and** while any named comparison is outstanding, and the two are not separable: a run that swept
59 endpoints and skipped nine named comparisons has proved that the questions it asked have the
same answers, which spec §3.10 says is a smaller claim than it sounds. `created_by_the_run` is on
`Identity` and not on the run, because it is what the teardown iterates and what AC-15's refusal
tests.

## 6. Algorithms

### 6.1 The run

```
sweep whatever an earlier run left            (§6.5)
resolve identities                            (§6.7)
for identity in identities:
    for endpoint in surface.yaml:
        for case in request-cases.yaml for that endpoint:
            if the case is not meaningful for this identity: skip, and say so in the coverage line
            a = atrium(case, identity);  b = reference(case, identity)
            rules = allowlist.resolve(endpoint, case, identity)
            differences += compare(a, b, rules) + compare_headers(a, b, rules)
for row in named-comparisons.yaml:
    if its `needs` are met: run it; else record it outstanding, with which need was missing
report
```

The identity loop is **outermost** on purpose: a report grouped by identity is one a reader can
scan for *"what does the restricted seat see that the administrator does not"*, which is the
question spec §3.9 exists to make askable. It also makes the degenerate run — one identity —
structurally the same run with a shorter loop, rather than a different code path that could quietly
become the only one anybody uses.

**The two servers are asked back to back, one case at a time**, rather than one server's whole
sweep and then the other's. `/Items/{itemId}/Similar` is a fresh draw per request (spec §7 OQ-4), so
seconds matter to it and minutes matter to every clock-derived field. A harness that swept one
server and then the other would compare answers taken minutes apart, which manufactures differences
rather than finding them.

#### 6.1.1 Filling a path parameter, which OQ-1 also decides

Most of the surface takes an identifier in the path, and **the two servers' identifiers are
different by design** (behaviours §1.4) — so a case cannot carry one. It carries an **anchor**: a
named listing, a sort, and a position. `GET /Items/{itemId}` becomes *"the item at position 3 of
`/Items?sortBy=SortName&includeItemTypes=Movie&recursive=true`"*, resolved against each server
separately, immediately before the case runs.

This is OQ-1's answer applied one level up, and it inherits OQ-1's consequence honestly: **an anchor
is only as sound as the ordering it indexes**, so an anchor over a listing the allowlist marks
`unordered` is an anchor over an arbitrary row, and the register refuses one. A case that needs a
particular *kind* of item — a multi-part film, a track with a subtitle file beside it — anchors on a
listing narrow enough that position 0 is that item, which is a property of the fixture and is
asserted where the fixture is declared rather than hoped for at run time.

`userId` is not an anchor: it is the identity's own, which is why `Identity` carries `user_id` and
why a case naming *another* user's id is a case that belongs to a named comparison rather than to
the sweep (behaviours §3.16).

### 6.2 The comparison, in five classes

Objects compare by key set first, then per key by type, then by value. Arrays are where the design
lives:

1. **Lengths first.** Different lengths are one `LENGTH` finding, and the array's rows are then not
   compared **by position**. This is the cascade guard, and without it AC-2's very first run — where
   one server resolves a multi-part film as two sources and the other as one — buries every real
   finding under positional noise. **Corrected by T2 and landed by T4:** what a length difference
   suppresses is the *positional* comparison and nothing else, never the comparison an array's own
   kind still owes. As first written — *"the rows are not compared at all"* — step 1 deleted step 4
   on the only endpoint step 4 exists for, because `/Items/{itemId}/Similar` answers `limit + 4`
   rows on a movie seed (behaviours §3.24) and its two lengths therefore differ on **every** run.
2. **Then order.** Each row is reduced to a *fingerprint*: the row after the allowlist's masking,
   serialised canonically. When the two fingerprint sequences are equal, the array is identical and
   nothing more is said. When they are equal **as multisets** but not as sequences, that is exactly
   one `ORDER` finding, carrying the permutation, and no `VALUE` findings are emitted for that
   array. When they are neither, rows are aligned by index and compared.
3. **An array the allowlist marks `unordered` skips step 2 entirely** and compares as a multiset
   (AC-18): a difference in row order alone is not reported, which is the reference's own
   non-total ordering (behaviours §3.6) not being reported as Atrium's defect. **What this section
   did not say, and T4 decided:** when the multisets *genuinely differ*, the rows that match are
   removed and only the **residue** is aligned and compared. The shape that forces it is measured
   rather than hypothetical — paging the reference's artist sorts loses **and duplicates** rows
   (behaviours §3.6), so a page can hold one row twice and another not at all at an unchanged
   length, which is the one array shape neither the `LENGTH` guard nor the `ORDER` class catches
   (§9's risk row claims they do). Pairing rows arbitrarily is legitimate **only** here, where the
   entry says this array has no ordering to lose; an ordinary array keeps step 2's index alignment,
   because pairing equal rows across positions would silently discard the ordering the sweep is
   testing.
4. **An array the allowlist marks `drawn` compares the envelope, the row count, and each row's key
   set and types — and no row's values** (AC-17). The rows are still walked, because a key missing
   from a row of `/Items/{itemId}/Similar` is a real finding and excusing the array must not excuse
   the shape of what is in it. **And the walk is position-free, which T4 found and this sentence
   did not say:** rows reduce to one map of *generalised pointer → the JSON types seen there across
   every row*, and the two maps are compared. Row 0 against row 0 would report content as shape,
   since the reference suppresses nulls globally — a row's key set depends on which item it holds —
   and a draw guarantees the two sides hold different items. A difference at a node prunes its own
   subtree, the way a `TYPE` does in an object; the presence of *an element of* a nested array is
   not compared at all, because one item having three genres where another has none is content.

**The fingerprint exists to serve a query pattern**, in the plan-template's sense: the ordering
comparison could be done by O(n²) matching, and the fingerprint is what makes it a sort. It is
derived, never stored, and it is masked by the same allowlist the value comparison uses — otherwise
two rows differing only by `Id` would look like a reordering to the very mechanism that exists to
excuse `Id`.

Headers are compared on the delivery routes only (spec §3.2), by name set and then by value, with
`header:` pointers so one report holds both.

### 6.3 The allowlist, scoped, in three kinds

`resolve(endpoint, case, identity)` walks `allowlist.yaml` and returns the `Rules` for this one
comparison. An entry applies when its `endpoint` matches and its `pointer` prefixes the pointer
under comparison; `*` is permitted and is exactly as wide as it looks, which is why review sees it.

The three kinds and what each still compares:

| Kind | Not compared | Still compared |
|---|---|---|
| `field` | The value | The key's presence and its JSON type |
| `drawn` | Every row's values | The envelope, the row count, every row's key set and types |
| `unordered` | The order | Everything, as a multiset of rows |

**AC-6 says an entry without a behaviours.md reference fails the run, and the allowlist the spec
ships would fail it.** Read against spec §3.3: three of the eight field rows name a behaviours
section (`Id` → §1.4, `LocalAddress` → §4.2, `TotalRecordCount` → §3.1) and one of the three array
rows does (`§3.6`). The other seven name a *reason* — scan wall-clock time, a content hash, a
different mount point — or they name this spec's own §7. Two of those seven have a behaviours
section already and are simply not citing it (`X-Response-Time-ms` is §1.9; the `Similar` array is
now §3.23 and §3.24), and one has none at all: **the random `ChildCount` is recorded in
`conformance.md`'s allowlist table and in spec §3.3, and nowhere in `behaviours.md`.** So AC-6
needed either seven new entries or a rule that distinguishes a *divergence* from a *derivation*.
This plan proposed the second, and **D-3 took it on 2026-09-01** — which is an amendment to an
accepted spec, dated and recorded in its frontmatter.

Where the entry is a divergence, `because` is the behaviours section and AC-6 is unchanged. Where it
is a derivation, `because` is one of four declared classes, each of which is a fact about how the
two servers are built rather than a difference either one chose: `derived-identifier`,
`wall-clock`, `content-hash`, `installation-path`. A fifth class is not added without review, which
is the discipline AC-6 was written for.

**And the row that was neither was written rather than reclassified.** The reference's random
`ChildCount` on a library view is now
[behaviours §3.25](../../docs/compatibility/behaviours.md) — class B, diverged, on §3.0's first
escape hatch, because a number redrawn on every request is one no client can have compensated for.
It is also the entry that argues this section's scoping rule where a reader will look for it: the
same property on a series, a season or the two-disc album is a real subtree aggregate on both
servers. Spec §3.3's two tables now carry a `because` on every row of both, and so does
[conformance.md](../../docs/compatibility/conformance.md#l3--differential)'s rendering of the same
list.

### 6.4 The named comparisons

Each row of `named-comparisons.yaml` names a `runner` — a function in `tools/differential.py` with
one signature, `(instances, identities) -> NamedResult` — so the twenty are *code beside the
sweep*, not prose beside the report. Six shapes cover all twenty:

| Shape | Rows | What it does |
|---|---|---|
| **A second seat** | the named reader, the unreachable entries, the delivery-time policy refusal | Issues one request as a created identity and compares the two answers, where the whole signal is a status or a row count |
| **The same request twice** | the de-duplication that misses | Runs it twice against each server and reports the *reference's* disagreement with itself as the finding (behaviours §3.18), never as a flake to retry |
| **Something that is not in a body** | the progressive header frame, burn-in, the image track's latency, the subtitle playlist's bytes, the manifest's `NAME` | Parses or times rather than compares: first frames, cue pixels, elapsed milliseconds, raw bytes with one attribute masked |
| **A library the reference has to be given** | the multi-part film, the legacy-encoded subtitle, EXIF orientation, the empty library, the media source with no runtime, the pristine specials season (005 OQ-7) | Needs `fixture`, and is reported outstanding by name when no instance was available |
| **The library changed underneath a rescan** | the container that has lost every file (behaviours §5.2), the replaced poster (behaviours §5.6) | Needs `fixture` and `rescan`: scan, change the tree, rescan, and compare the second reading rather than the first. Added by D-6 |
| **A reading after a deliberate wait** | the paused-session ticker freeze | Needs `wait`: report a paused session to both, stay silent past the reap threshold, compare the position each committed. Added by D-6 |

The last two rows of §3.10 — the `"$"` message and the four unmeasured content-type refusals — are
ordinary cases in `request-cases.yaml` with a `named-comparisons.yaml` row pointing at them, which
is what spec §3.10 means by *"here to be recognised, not discovered"*: the register makes them
countable, and the sweep is what finds them.

**A row whose `needs` cannot be met is outstanding, not skipped, and the run is not clean.** The
difference is the entire value of §3.10: a green run that quietly dropped nine comparisons is the
failure this feature exists to prevent, one directory away from the CI job that reported green
because it ran nothing (008 T18's finding, and `pyproject.toml`'s own comment about it).

### 6.5 The single-use reference instance

Nothing about this exists yet, and it is the largest thing in the feature. The lifecycle, in the
order `ReferenceInstance.__enter__` performs it:

1. **Sweep.** Anything labelled from an earlier run — a container by label, a data directory under
   the harness's own scratch root — is destroyed first. 008 §6.7 does exactly this to the transcode
   scratch root at startup, for the same reason: the only cleanup that survives a killed process is
   the one the *next* run performs.
2. **Start.** One container of the pinned version from a pinned digest, no published port beyond a
   loopback one the run picks, an **ephemeral** data directory created under the scratch root, and
   the fixture tree bind-mounted **read-only**. `--rm` so that even a lost `finally` leaves nothing
   but the directory the sweep takes.
3. **Wait for the API, not the process.** Readiness is `GET /System/Info/Public` answering with a
   `ProductName` naming Jellyfin — the same check `tools/_probe.py`'s `connect` already makes, and
   the reason it is that check rather than a port probe is that a listening socket is not a
   configured server.
4. **Configure, with no human.** `POST /Startup/Configuration`, `POST /Startup/User`, `POST
   /Startup/Complete` `[spec: UpdateInitialConfiguration, UpdateStartupUser, CompleteWizard]`, then
   `POST /Library/VirtualFolders` naming the fixture root, its collection type and
   `refreshLibrary=true` `[spec: AddVirtualFolder]`. All four declare the **first-time-setup**
   policy where `POST /Users/New` declares elevation `[spec: the security requirement declared on
   those operations]`, which is what makes an unattended sequence plausible at all.

   **What that policy admits before a wizard completes is read from a document and not measured**,
   and it is the one assumption in this section that a server can refuse. The task that writes
   `_reference.py` verifies it against the instance in its first run and, if a credential is
   required earlier than this reads, the sequence gains nothing worse than an extra step — the
   wizard creates the administrator either way. It is named here so that it is checked rather than
   discovered.
5. **Wait for the scan, on the server's own answer.** `GET /ScheduledTasks` until the library scan
   reports itself idle `[spec: GetTasks]`, with a deadline. Not a sleep, and not an item count that
   has stopped changing: a count that has stopped changing is indistinguishable from a scan that has
   not started.
6. **Hand back the administrator identity**, and create the other seats §6.7 asks for.

`__exit__` destroys the container and removes the data directory, on the exception path and on the
success path, and it does **not** first delete the accounts, playlists or libraries the run created:
they die with the instance, which is precisely the property spec §3.1 wanted — *"the difference
between a cleanup that must be perfect and one that only has to be tidy"*.

**When it cannot start**, the run does not fail and does not pass. Every case and every named row
that declared `needs: fixture` is reported **outstanding with the reason** — the runtime is absent,
the image could not be pulled, the wizard refused, the scan timed out — and `is_clean()` is false.
The sweep-only run against an operator's own server stays available and is exactly what the
harness did before this existed: it covers what a stock library can answer, and its coverage line
says so.

### 6.6 The fixture on the other server

**The tree is built by the code that already builds it**, and the harness does not gain a third
world (spec §3.1). `tests/fixtures/library/generate.py`'s `build(destination)` materialises the
003 tree — 56 declared entries across three libraries, 27 films, 15 series rows and 14 music —
deterministically, and
`tests/fixtures/media.py` builds the 008/011 world of real, ffmpeg-encoded media into a cache
directory named after a digest of the matrix and the ffmpeg version, published with an atomic
rename. Both are importable from a Python that has the dev environment; the harness therefore
builds the tree through a small entry point in `tests/` and mounts the result, rather than
reimplementing a generator that would then disagree with the one the suite uses.

**The fixed modification time is load-bearing across the mount.**
`tests/fixtures/library/generate.py` stamps every file with one `FIXED_MTIME_NS`, so that the same
tree is the same tree to a change signal. A **bind mount** preserves it; a copy into a volume does
not unless the copy preserves times, and a fixture whose timestamps moved between the two servers
would put a difference into `DateCreated` on every item — a field the allowlist excuses, which is
worse, because the noise would be invisible.

**Which world the reference is given is not decided here, and the first measurement decides it.**
The 003 tree is paths and filler bytes by design — its own generator says *"these are not decodable
media, and 003 has no use for one"* — and **whether a reference server makes items out of a file
its prober cannot open is unmeasured**. `tools/probe_library_extensions.py` measured which
extensions a real library's items carry, which is a lower bound over files that are real media; it
says nothing about this. So `tools/probe_reference_scan.py` is the first thing the instance is
built for, and it asks one question: *given the fixture tree, what does a reference server's library
contain?* Its answer chooses between two paths this plan has already priced — the fixture is the
media world plus the structural cases ported into it entry by entry (the mechanism §3.1 already
uses for the five it owes), or the fixture is both trees as two libraries and AC-2's item count
compares both. **D-4** in §11 records it — decided on 2026-09-01 **with its dependency stated**: the
measurement cannot be taken before D-1's instance exists, because the only reachable Jellyfin is an
operator's production server and adding a library to it is a write this project does not own. So the
default holds until the instance can answer, and the answer changes what the fixture task in the
task list is.

**The order is therefore fixed, and it is the one thing about D-4 that must not be lost.** The task
that lands `tools/_reference.py` comes first; `tools/probe_reference_scan.py` is that instance's
**first run** and is the task that performs this measurement; the fixture task that ports the
structural entries §3.1 owes reads the probe's answer and is written after it. Until then this is an
open measurement with a default, not a measured result.

### 6.7 Identities

Three roles, of which the run creates two:

| Role | Obtained | Needed by |
|---|---|---|
| `administrator` | The wizard's own first user on an instance; `.env` credentials against an operator's server | Everything; the only seat every measurement before 2026-09-01 used |
| `restricted` | `POST /Users/New`, then `POST /Users/{userId}/Policy` narrowing `EnabledFolders` to one library `[spec: CreateUserByName, UpdateUserPolicy]` | The 12 reads of spec §3.9, and three named comparisons |
| `playback-denied` | The same, with the playback-processing permission denied | The delivery-time policy refusal (behaviours §2.21) |

**The refusal AC-15 asks for is a precondition, not a cleanup.** Before creating anything, the run
lists the users and refuses to start if a seat with its own fixed name is already there — because a
seat that is already there is either another run in flight or the wreckage of one, and reusing it
would mean measuring against a policy somebody else set. `tools/probe_restricted_surface.py`
already builds a seat this way, under a fixed name, and it is the shape to lift rather than invent.

**Against an operator's server the created seats are removed in a `finally`; against an instance
they are not removed at all**, because the instance is. Both are correct and only one of them can
leak, which is the argument spec §3.1 makes for the instance in one sentence.

### 6.8 The ignored-parameter report

Spec §3.6 asks for a report of parameter, endpoint, count and client (AC-10). Two thirds of it
exist: `compat/query_params.py`'s `IgnoredParameters` counts every ignored `(route, parameter)`
pair and logs each pair **once**. The other third does not, and this plan measured it rather than
assuming it:

* **Nothing reads the counts.** `IgnoredParameters.counts` and `total()` have no reader anywhere in
  `src/atrium/` — the recorder is constructed in `server.py` onto `app.state` and consulted only by
  the routes that write to it. The count exists in a live process and reaches nothing.
* **There is no client.** `record(route, parameter)` takes no third argument, and AC-10 names four
  columns. The client is available at the moment of the record — every authenticated request
  carries it in the client header 002 already parses — but it is not passed.
* **The log line is once per pair per process**, deliberately, so the count never reaches the log
  even in principle.

So the report is not a matter of reading what is already written down. It is a change to a shipped
module every request passes through, for the benefit of a report — which is a scope call rather
than a task-level one, and it is **D-5**, **taken on 2026-09-01**. The shape is the smallest one:
`record` gains the client from the header `users/` already parses, and the tally is **written into
the data directory** when the server stops, where the harness reads it beside the report it is
writing anyway. AC-10's four columns are therefore met rather than reduced to three.

**Never a route, and this is where the reason is recorded so nobody reaches for one later.** An
endpoint that served the tally would be an endpoint Jellyfin does not have — Principle I's first
forbidden line, and an "optional" extension is still a delta because a client can discover it. The
tally is diagnostic output of this server about itself; it leaves the process as a file in the data
directory, which is a place `config/` already owns and no client can see, or it does not leave the
process at all. A file also survives the shutdown that a route could not answer after, which is when
the count is complete.

### 6.9 The version-bump command

`tools/bump_reference_version.py` runs [conformance.md's four
steps](../../docs/compatibility/conformance.md#when-the-reference-version-moves) in order and
refuses to continue past a failure (AC-12): fetch and validate the document, run the differential
**and** the named comparisons, re-run every probe, and only then write the version. It is a
sequencer, not a new mechanism — each step is a program that already exists or is one of the two
this feature adds — and the refusal is the point: *"a bump that skips step 2 has not been done, it
has been declared."*

**It also enforces the two-row distinction reference-target §1 records.** When only the contract row
moves — the same server, a different document of it — step 2 has no input and the command says so
and skips it, which is the move that was actually made on 2026-09-01. When the running reference
changed, step 2 is mandatory and no flag skips it.

### 6.10 The probe convention, and the debt

**§3.5's convention is `tools/_probe.py`, and all 53 probes already use it** — every one imports
`main` from it, and every one constructs a `Probe` with the document and section its finding bears
on. AC-7 and AC-8 are therefore properties this repository already has; what it does not have is
anything that would notice a 54th probe printing its own output. So the work is a sweep in
`tests/unit/`, in the shape `tests/unit/test_import_directions.py` already uses for the production
ledger: every `tools/probe_*.py` reaches `_probe.main`, names a document and a section, and — where
it declares `needs_writes` — removes what it created. Twenty-five of the 53 declare it.

**The cleanup contract is a requirement the server disproved.** Spec §3.5 records 28 playlists left
behind by 009's runs on 2026-09-01, where `tools/README.md` says of every writing probe that it
deletes what it made including on failure. A concurrent change is fixing the leak; what this
feature owes is the part that outlives one fix — a shared *created-and-owned* register in
`_probe.py` whose teardown runs in a `finally`, so that "cleans up" stops being a thing each of
twenty-five scripts implements separately. **This plan does not edit `tools/_probe.py`**; the task
that does will land after the leak fix, and its first job is to check that the fix did not already
do it.

**The prior-measurement register is the input to AC-9, and it is stale in four rows** (§6.12). AC-9
is therefore a reconciliation before it is eight new probes: for each of the eight open rows, find
whether a script under a different name already answers it and has been run, upgrade the citations
that are still `prior-probe` where it has, and write a probe where it has not. Two of the eight
cannot be answered against an operator's server at all and are the instance's to answer: `/Users/Public`
returning `[]` needs every user hidden, and the `LocalAddress` HTTPS override needs a server
configured for HTTPS. Both are writes to a configuration, which is exactly what a disposable
instance is for.

### 6.11 What runs where, and why none of it runs in CI

Spec §3.7's table says what runs when; this says on which machine, because the answer is not the
usual one.

| Job | Where it runs | What it needs |
|---|---|---|
| Surface validation, L0, L1, L2, and this feature's own mutation proofs | **CI, every change** | Nothing beyond the repository — and this is the half that grows |
| The L3 sweep against a reachable server | A contributor's machine, on demand | `.env` credentials and a Jellyfin somebody already has |
| The fixture runs, the named comparisons that need one, and AC-2 | A contributor's machine, on demand | The runtime of D-1 ([ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md)); **an instance this project stands up and destroys** |
| Every probe, and the version bump | A contributor's machine, on demand and at a bump | The same |

**No CI job contacts a Jellyfin server, and none starts one.** That is not a limitation this
feature works around: a gate whose result depends on somebody else's uptime is not a gate, and the
suite already fails any test that opens a TCP connection. The consequence is stated rather than
hidden — **the strongest check in the project is the one that is never automatic** — and the two
mechanisms that answer it are `bump_reference_version.py`, which makes the run mandatory at the one
moment it matters most, and `is_clean()`, which makes a run that skipped things say so.

A machine that has the runtime gains the fixture rows; a machine that has only a reachable Jellyfin
gains the sweep; a machine that has neither still runs everything in the first row above. Each of
the three reports what it covered, which is AC-14 generalised from identities to inputs.

### 6.12 What this plan measured, and what came back false

Every claim this plan makes about the repository was read out of the file it names. Four were
false, and each changes something in the task list rather than in the prose:

1. **`tools/differential.py` does not exist, and `conformance.md` documents its command line** —
   including a `--surface` flag and a `--report` path. The harness is a published interface before
   it is a program; this plan adopts the documented invocation rather than inventing a second one,
   and the task that lands the tool updates that block in the same commit.
2. **`ATRIUM_JELLYFIN_URL` is named in `conformance.md` as the switch that makes L3 opt-in, and it
   appears nowhere in the repository.** No code reads it and no test skips on it. The mechanism it
   describes is real — the differential is opt-in, and no default test touches the network — but
   the name is a claim about an implementation that does not exist yet. The probes reach their
   server through `JELLYFIN_URL` in the git-ignored `.env` (`tools/_probe.py`), and the harness
   uses the same name rather than a second one; `conformance.md`'s sentence is corrected by the
   task that makes it true.
3. **The prior-measurement register in `reference-target.md` is stale in four rows.** Its prose says
   *"six down, nine to go"*; the table holds fifteen rows of which **seven** are struck and
   **eight** open. Three of the eight open rows are debts that have in fact been paid under another
   script's name: the authentication mechanisms are measured by `tools/probe_auth_mechanisms.py` —
   which is what turned four mechanisms into five, behaviours §2.4 — while the register still calls
   that row *"not written"* and `api-surface-v1.md`'s own table still cites `prior-probe:
   2026-06-13` for four of the five; the item-level `Container` row is measured by
   `tools/probe_media_container.py` and behaviours §1.6 carries the `[probe:]` citation; and the
   item-identity row names a `probe_item_ids.py` that does not exist beside a
   `probe_item_identity.py` that does and that ran at 003 T19. AC-9's real size is smaller than its
   register says, and its first task is the reconciliation.
4. **AC-6, applied to the allowlist the spec ships, failed it.** Three of eight field rows and one
   of three array rows named a `behaviours.md` section; the random `ChildCount` had no entry there at
   all. **Fixed on 2026-09-01 by D-3**: AC-6 refined to take a behaviours section or one of four
   derivation classes, every row of both tables given a `because`, and behaviours §3.25 written.
   §6.3.

**And one thing this plan got wrong while writing it, kept because the next reader will reach for
it too.** The obvious way for a harness to check that it has been pointed at the right two servers
is `ProductName` on `GET /System/Info/Public`, which is what `tools/_probe.py`'s `connect` does —
and it **cannot tell Atrium from Jellyfin**, because Atrium answers `"Jellyfin Server"` there on
purpose (reference-target §4, behaviours §4.1). `_probe.py`'s guard is right for its own job, which
is refusing an Emby; it is the wrong guard for this one. The discriminator is the `Server` **header**
— `Atrium/<version>` here against the reference's `Kestrel` `[probe: tools/probe_routing.py,
Jellyfin 10.11.11, 2026-08-28]` — which is the one place Principle X wins over Principle I, and
therefore the only place a tool may look.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| No container runtime on the machine | The binary is absent | Every `needs: fixture` case and named row is **outstanding**, with that reason; the sweep against a reachable server still runs; `is_clean()` is false | Install it, or run with `--reference-url` |
| The image cannot be pulled | Non-zero exit from the runtime | The same, naming the image and the digest | — |
| The instance starts and the wizard refuses | A non-2xx from a startup operation | Abort the fixture half, print the status and the body, destroy the instance | The body is the finding: a wizard that refuses is a version difference |
| The scan does not finish inside the deadline | `GET /ScheduledTasks` still busy | Destroy, report outstanding with the elapsed time | Raise the deadline; a fixture that cannot be scanned in minutes is a fixture problem |
| The run is killed between start and teardown | Nothing at the time | The **next** run's sweep removes the container and the data directory, and says how many it removed | Automatic, and the count is printed so a leak is visible |
| A seat the run wants already exists | The pre-flight user list | **Refuse to start** (AC-15), naming the seat | Delete it, or wait for the other run |
| The reference answers `5xx` where Atrium answers a body | Status comparison | A `VALUE` difference on the status, triaged like any other — several are already known divergences (behaviours §3.9, §3.19) | — |
| One server is slow and the two responses are minutes apart | Per-case pairing (§6.1) | Cannot happen by construction; the pairing is per case, not per sweep | — |
| An array's lengths differ | Length check before rows | One `LENGTH` finding; the rows are not compared (§6.2) | — |
| An allowlist entry matches nothing on any run | Counted per entry | Reported at the end: an entry that excuses nothing is either wrong or a converged difference | Delete it — the allowlist is a metric that should shrink |
| A named comparison's runner raises | The runner | The row is **outstanding**, with the exception, and the run continues | A runner that cannot run is not a comparison that passed |
| The harness is pointed at an Atrium as its reference, or vice versa | The `Server` **header**, never `ProductName` | Refuse, naming what was found. Measuring the wrong server files the answer under Jellyfin's name, which is `_probe.py`'s reason for its own guard | — |

## 8. Testing strategy

Eighteen acceptance criteria. **This feature's tests run without a reference**, which is not a
compromise: spec §6 proves the harness by *mutation*, and a mutation proof needs a controlled input,
not a server.

| AC | Where | Shape |
|---|---|---|
| 1 | `tests/unit/test_media_fixtures.py` (extended) | Two builds byte-identical — the assertion `tests/fixtures/media.py` already carries, extended to the tree the instance is given |
| 2 | `tools/probe_reference_scan.py`, **and a test over what it wrote down** | *This row said "by hand — the one criterion that cannot be a test", and the acceptance map cannot express that.* `tests/conformance/test_acceptance.py` resolves every entry as `module:function` through `importlib`, and §2 above inherits the rule that a `tools/` module is reached by path and never as a package — so the row would fail on import the day `"010"` joins `IMPLEMENTED_FEATURES`, for the right reason: a criterion whose only proof is a command somebody remembers to run is a criterion with no proof. **The probe therefore records the reference's reading of the fixture** — item count per collection type, and the structure, with its own citation in the file — and the test compares Atrium's scan of the same tree against that record. Both servers are still needed to *make* the reading; only one is needed to check it, so it runs in the default job. Found at the tasks gate on 2026-09-02 |
| 3 | `tests/unit/test_allowlist.py` | Every endpoint of `surface.yaml` has at least one case in `request-cases.yaml`, and the coverage line counts what it ran |
| 4 | `tests/conformance/test_differential.py` | The mutation table: a removed field → `MISSING_KEY`; an integer as a string → `TYPE`; a changed title → `VALUE`; a reordered array → `ORDER` and **not** N values; a shorter array → one `LENGTH` and no children |
| 5 | `tests/conformance/test_differential.py` | The report's own ordering, asserted on a report built from a mixed finding set |
| 6 | `tests/unit/test_allowlist.py` | An entry whose `because` names neither a behaviours section nor one of the four declared derivation classes fails the load, and a class outside the four fails it too — AC-6 as D-3 refined it |
| 7, 8 | `tests/unit/test_probe_convention.py` | The sweep over `tools/probe_*.py`: reaches `_probe.main`, names a document and a section, declares `needs_writes` if it writes. `_probe.Probe.report` returning 1 on a contradiction is asserted directly |
| 9 | `tests/unit/test_probe_convention.py` | Every open row of `reference-target.md`'s register names a script that exists, or carries a recorded reason it cannot — which is the assertion that would have caught §6.12's finding three |
| 10 | `tests/conformance/test_differential.py` | The report's four columns, over a recorder seeded by hand. The fourth is the client, which D-5 took: the recorder gains it, and the tally is asserted as a file in the data directory rather than a response |
| 11 | CI, unchanged | The default job passes with no Jellyfin and no network — already true, enforced by `tests/conftest.py`'s socket guard, and the property the new tests must not cost. Nothing this feature adds carries `needs_reference`: the mutation proofs run on checked-in pairs |
| 12 | `tests/unit/test_version_bump.py` | Each step made to fail in turn; the command stops and the later steps did not run |
| 13 | `tests/unit/test_media_fixtures.py` (extended) | Every fixture file is generated by a declared entry — the existing rule, restated for the entries §3.1 owes |
| 14, 15 | `tests/conformance/test_differential.py` | A report built from one identity says one identity; a run whose pre-flight finds the seat refuses, and the refusal names it |
| 16 | `tests/unit/test_allowlist.py` + `test_differential.py` | The register has **twenty** rows and they are spec §3.10's — sixteen until D-6 widened both, 2026-09-02; a run with one outstanding is not clean |
| 17 | `tests/conformance/test_differential.py` | A key removed from a row of a `drawn` array is still reported; a value changed in the same row is not |
| 18 | `tests/conformance/test_differential.py` | A reordered `unordered` array produces nothing; the same array reordered *and* changed produces the change |

**The fixtures this feature needs.** Not a library: four *paired bodies*, checked in beside the
mutation tests, one per shape the engine has to get right — a bare object, a list envelope, a
`drawn` array, and a delivery response's headers. They are hand-written rather than captured, because
a captured pair proves the engine agrees with whatever the capture happened to hold, and because
anything captured from the reference is somebody's library.

**This table is the section most likely to rot, and the audit of 2026-09-01 said so in this
project's own words.** 009's plan §8 counted nineteen criteria where there were twenty and named a
test file nobody wrote, while its §6 stayed current. The protection is
`tests/conformance/test_acceptance.py`: when this feature flips to `Implemented`, its map entry is
written and the suite then fails on a criterion with no test, a test that was renamed, and a count
that moved. Until then this table is prose, and it should be read as prose.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The reference will not build a library from the fixture tree at all | **Medium** | High — AC-2 and five named comparisons hang off it | It is the first measurement the instance is built for (§6.6), taken before anything is written against either answer, and both answers have a priced path |
| A positional comparison drowns the report in noise on the first real run | High without the guard | High — an unread report is worse than none (spec §6) | The `LENGTH` cascade guard and the `ORDER` class (§6.2), and both are mutation-tested rather than argued. **Amended by T4: those two do not cover the shape that is measured.** Neither fires on a page whose length is unchanged and whose rows are not a permutation, which is exactly what paging the reference's artist sorts produces — one row twice, another lost (behaviours §3.6). An `unordered` array now compares the multiset **residue** and nothing else, which is that page's mitigation; an ordinary array still aligns by index, deliberately, because matching equal rows across positions would discard the ordering under test |
| The allowlist grows to make runs green | Medium | High — it is the mechanism that can silently delete the feature's value | Every entry carries a date and is counted per run; an entry that excuses nothing is reported; review is the gate, and AC-6 is the automated half |
| The container runtime differs between contributors, or between a contributor and a maintainer | Medium | Medium — a difference that reproduces on one machine only | The image is pinned by digest and the run prints it in the report header, beside the Atrium sha the report already names |
| The instance's teardown is skipped by a kill signal | Medium | Low — the instance holds nothing but the fixture | `--rm`, plus the next run's sweep, plus the count printed so it is visible rather than silent |
| The two servers disagree because of the *mount*, not the server | Low | High — an invisible false positive | The fixed modification time is preserved by a bind mount and asserted before the comparison; the fixture root is mounted read-only so neither server can change it |
| Nobody runs it, because it needs infrastructure | **Medium** | High — the whole feature | The sweep against a reachable server needs nothing new and is the common case; the instance is needed only by the rows that name it; the version bump is where it is mandatory, and `bump_reference_version.py` is what makes that not optional |
| `tools/` grows a program large enough that the 3.9 stdlib floor hurts | Medium | Medium | D-2; and the engine is pure, so if the floor ever has to move, the part that would move is the part with no I/O |
| A concurrent change to `tools/` collides with this one | **Certain** | Low | The probe-cleanup fix is in flight; this feature adds files rather than editing `_probe.py`, and the task that does edit it lands after |

## 10. Alternatives considered

**Compare rows by a key rather than by position.** This is OQ-1, and it died at the gate: `Path` is
absent from every default list row — 0 of 1000 — so joining on it changes the request under
comparison, and asking for it by name still leaves a virtual season, a remote channel and every
by-name row unjoinable, with the paths those rows do carry naming the reference installation's own
data directory. `(Type, Name)` is 976 distinct of 1000. Rejected by measurement, and the consequence
— the ordering becomes part of the contract — is §6.2 rather than a regret.

**Run the differential against a recorded session.** OQ-3 answered yes for the bodies and no for the
feature: 16 of 19 reads are byte-stable across identical requests, so a recording replays faithfully
— and a recording answers only the requests it recorded, while the defect class L3 exists to find is
the field nobody thought to ask for. Kept as what it is: a regression net that could run in CI,
listed here so that a later reader does not rediscover the idea and mistake it for the gate.

**Put the harness in `tests/` and run it as an opt-in pytest suite.** Tempting — it would get the
project's dependencies, its fixtures and its runner for free, and `needs_reference` already exists
for it. Rejected on two grounds: `architecture.md` §3 already places it in `tools/`, and a harness
that lives in the suite is one that can import the server it is measuring, which is exactly how a
test comes to compare Atrium against itself (008 T16). The mutation proofs live in `tests/` and
reach the engine by path, which is the existing pattern in two files.

**Reuse the operator's server for the fixture runs, with a fixture library added beside the real
one.** This is what AC-2 was blocked on, and it was rejected on 2026-09-01 for a reason that has
not changed: adding a library means writing to data this project does not own, and the writing
probes had already left 28 playlists behind. The instance is the answer, and its second benefit is
the one that repays its cost every run.

**Keep the instance alive between runs, to save the scan.** Rejected, and it is the decision spec
§3.1 makes for a reason worth restating: a surviving instance accumulates what each run wrote, so
the second run measures a library the first one changed — and the property that makes a fixture
comparison mean anything is that the fixture is the only library either server has ever seen.

**A single global allowlist keyed on field name**, which is what both documents describe today.
Rejected by measurement: `ChildCount` is a computed subtree aggregate in this server, and the entry
that excuses the reference's random one would excuse Atrium's real one on every container.

**Let the harness decide what to do about a difference it finds.** Rejected by spec §2: the harness
triages, and the answer belongs to the feature that owns the endpoint, through behaviours §3.0. The
gate that accepted the spec found two such differences and left both to 005 — which is the procedure
working, and a harness that had "fixed" them would have made a Principle I decision in a tool.

## 11. The five decisions this plan reserved, taken on 2026-09-01

**All five are decided.** Each was written here as a project-level call with a recommendation, and
their owner accepted every recommendation on 2026-09-01. This section is now the record of what was
taken, not a request. Nothing in this plan or in 010's spec is waiting on a decision; what the plan
is still waiting on is its own gate.

| # | The call | Decided | Where it is written |
|---|---|---|---|
| D-1 | The runtime the reference instance needs | **Adopt a container runtime, with an ADR** | [ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md), [architecture §2 and §5](../../docs/architecture.md#2-runtime-stack), [reference-target §1](../../docs/compatibility/reference-target.md#1-the-pinned-version) |
| D-2 | Where the harness lives, and under which floor | **No change** — `tools/`, standard library, Python 3.9 | Unchanged: [architecture §3](../../docs/architecture.md#3-repository-layout), §1 and §2 of this plan |
| D-3 | AC-6, against the allowlist the spec ships | **Refine AC-6, and write the missing entry** | [010 spec AC-6 and §3.3](spec.md), [behaviours §3.25](../../docs/compatibility/behaviours.md), [conformance.md](../../docs/compatibility/conformance.md#l3--differential), §6.3 here |
| D-4 | Which fixture world the reference instance is given | **Measure first — and the measurement waits on D-1** | §6.6 here |
| D-5 | The ignored-parameter report's fourth column | **Take it**, written to the data directory and never to a route | §6.8 here |

**D-1 · The runtime the reference instance needs — adopted.** A container runtime, Docker or
Podman, invoked as a subprocess through its command line so that `tools/` keeps its
standard-library-only rule. It is a **development** dependency: nothing a user installs is affected,
and **no CI job has it, because no CI job may contact or start a Jellyfin**. The image is pinned by
**digest**, recorded in [reference-target §1](../../docs/compatibility/reference-target.md#1-the-pinned-version)
beside the two version rows it already pins and printed in the report header beside the Atrium sha;
the digest is written into that row by the task that lands `tools/_reference.py`, which is the first
run that has one. **The harness degrades rather than fails without the runtime**: `--reference-url`
takes an instance somebody else stood up, a machine with neither still runs the sweep against a
reachable server and everything in the default CI job, and every case and named row that declared
`needs: fixture` is then reported **outstanding with the reason** rather than skipped — so a run
without the dependency loses coverage and says so. What the dependency buys, what it costs, and the
four alternatives rejected — an SDK, a hand-installed Jellyfin per contributor, a virtual machine,
and running it in CI — are
[ADR-0007](../../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md).

**D-2 · Where the harness lives, and under which floor — no change, and that is the decision.**
The harness stays in `tools/`, standard library only, on the Python 3.9 floor, which is what
[architecture §3](../../docs/architecture.md#3-repository-layout) and `tools/README.md` already say
and what CI already runs the scripts under at both ends of the range. It was put here because the
component is an order of magnitude larger than a probe and the constraint is project-level, not
because anything was wrong with it: the floor is what lets the harness run on a machine that has no
environment, the parsers it needs already exist there, and the one part that would suffer — the pure
comparison engine — has no I/O and could move later at no cost to anything else. **Recorded as
decided-and-unchanged** so that a later reader does not read silence as an open question.

**D-3 · AC-6, against the allowlist the spec ships — refined, and the missing entry written.**
This one **edits an accepted spec, deliberately**, which is why it was reserved: AC-6 as accepted
failed the allowlist its own document ships, and a criterion that cannot pass is not a gate. Every
allowlist row now cites **either** the behaviours.md section that argues a difference a server chose
**or** one of four declared derivation classes for a difference neither server chose —
`derived-identifier`, `wall-clock`, `content-hash`, `installation-path` — with a fifth class
reviewable and never a substitute for an argument somebody owes. Spec §3.3's two tables gained a
`because` column and every row of both carries one;
[conformance.md](../../docs/compatibility/conformance.md#l3--differential)'s rendering of the same
list carries it too, so the two prose copies cannot drift apart while §6.3's file is being written.
**The one row that was neither a divergence with an argument nor a derivation was written rather
than reclassified:** the reference's random `ChildCount` on a library view is
[behaviours §3.25](../../docs/compatibility/behaviours.md), class B, diverged. The spec's frontmatter
carries the amendment, dated, because the document is `Accepted` and an amendment to one of those is
recorded rather than silent. It also carries this plan's measurement about the mechanism: **an entry
is scoped to an endpoint and a JSON path, never to a bare field name**, because `ChildCount` here is
a real computed subtree aggregate and a name-keyed row would excuse, on every container, the value
L2 exists to check.

**D-4 · Which fixture world the reference instance is given — measure first, and the measurement
has a prerequisite.** The default stands: **the media world extended with the structural entries
§3.1 already owes** — one tree, real media throughout, one library per collection type — because
that is the world every fixture-dependent named comparison needs anyway. If the reference does make
items out of the 003 tree, both worlds go across and AC-2 compares two libraries instead of one.

**What must not be fudged is that this is still unmeasured, and why it cannot be measured yet.**
Answering it needs a library scan on a reference server, and a scan is a **write**. The only
reachable Jellyfin is an operator's production instance, which this project does not write to —
that is the whole reason D-1 exists. **So D-4's measurement is possible only once D-1's disposable
instance does**, and the sequence is fixed (§6.6):

1. the task that lands `tools/_reference.py` — the instance itself, from D-1's runtime;
2. **`tools/probe_reference_scan.py`, which is the task that performs this measurement**, and is the
   instance's first run: *given the fixture tree, what does a reference server's library contain?*;
3. the fixture task that ports the structural entries §3.1 owes, written against the probe's answer.

Until step 2 has run, the default above is a **default, not a finding**, and no document may cite it
as measured. Both branches are priced (§6.6), so the answer changes the shape of step 3 and nothing
earlier.

**D-5 · The ignored-parameter report's fourth column — taken, in the smallest shape.**
`compat/query_params.py`'s recorder gains the client, read from the header 002 already parses, and
the tally is **written into the data directory** when the server stops, where the harness reads it
beside the report it is writing anyway. AC-10's four columns are met rather than reduced to three,
which matters because the bounded delta [005 §3.3](../005-item-query-api/spec.md) accepted was
accepted **in exchange for** this report: a three-column report cannot name the client whose
parameter should be promoted, and a delta with no closing mechanism is a permanent excuse.

**The tally is a file and never a route, and the reasoning belongs next to the report** (§6.8) so
that nobody reaches for the tidier option later. An endpoint serving the tally would be an endpoint
Jellyfin does not have — Principle I's first forbidden line — and "optional, behind a flag" does not
save it, because an extension a client can discover is still a delta. The tally is this server's
diagnostic output about itself: it leaves the process as a file in the data directory, which
`config/` already owns and no client can see, or it does not leave the process at all. The file is
also the only form that can carry the *complete* count, since it is written at shutdown, which is
after the last request a route could have answered.

### D-6, reserved by the task list rather than by this plan, and taken on 2026-09-02

The sixth decision is not one of the five above: this plan raised it in its own frontmatter and left
it to the [task list](tasks.md) to state, because it is a scope call on an **accepted** spec and the
list is where it was found. It is recorded here so that no reader of this document has to reach the
task list to learn that it is settled.

**Taken 2026-09-02, the recommendation accepted.** The four readings that §3.10 did not carry —
[behaviours §5.2](../../docs/compatibility/behaviours.md) (the container that has lost every file,
and the only surviving `⚠️ UNVERIFIED` in the compatibility documents),
[behaviours §5.6](../../docs/compatibility/behaviours.md) (the replaced poster a default rescan does
not notice), [005 §7 OQ-7](../005-item-query-api/spec.md) (Next Up and a pristine specials season)
and [007's paused-session ticker freeze](../007-user-data-and-playstate/tasks.md#what-this-feature-owes-the-next-ones)
— are **§3.10 rows**, so the register is twenty and AC-16 counts twenty. Every one of them needs
precisely what D-1's instance provides: three want the library changed between two scans, and the
fourth wants ten minutes of deliberate silence against a paused session — none of which may be
asked of an operator's server. [010 spec §7](spec.md#7-open-questions) records the decision and its
frontmatter carries the amendment, dated, exactly as D-3's did. **Behaviours §5.2 keeps its
`⚠️ UNVERIFIED` marker**: `behaviours.md` is not a specification and may carry one, and a §3.10 row
is an owner and a method rather than the reading that discharges it.
