# Specifications

This project practises **Spec-Driven Development**. This file defines the workflow, the directory
convention and the rules that keep the three artefacts from collapsing into one document with three
headings.

## The loop

```
   ┌──────────┐      ┌──────────┐      ┌───────────┐      ┌──────┐
   │ spec.md  │─────▶│ plan.md  │─────▶│ tasks.md  │─────▶│ code │
   │ WHAT/WHY │      │   HOW    │      │   STEPS   │      │      │
   └──────────┘      └──────────┘      └───────────┘      └───┬──┘
        ▲                                                     │
        └─────────────────────────────────────────────────────┘
            what implementation taught us goes back in the spec,
                          in the same change
```

Each arrow is a **review gate**. A plan is not written against a draft spec; tasks are not written
against a draft plan; code is not written against draft tasks. Principle III forbids
short-circuiting, and the reason is not ceremony: the value of SDD is entirely in the moments where
writing the spec makes you notice that you did not know what you wanted.

The loop closes. Implementation always teaches something the spec did not say — that goes back into
`spec.md` **in the same commit as the code**, not in a follow-up.

## The three artefacts, and what makes them different

### `spec.md` — WHAT and WHY

Observable behaviour. What a client sends, what it gets back, what changes on the server, what
happens on each error path.

**Test for a good spec:** two competent engineers could implement it in two different languages and
their servers would be indistinguishable to a client.

**Forbidden in `spec.md`:**
- Any technology name — Python, FastAPI, SQLite, a table name, a module name, a function name.
- "We will store…" — storage is a plan concern. Say what is *observable*, not where it lives.
- Any claim about Jellyfin without provenance (Principle II).

### `plan.md` — HOW

Architecture, data model, module boundaries, libraries, algorithms, migrations, failure handling.
This is where technology names finally appear.

**Test for a good plan:** an implementer never has to invent a design decision. If they do, the
decision belonged in the plan.

Project-level choices are inherited from [../docs/architecture.md](../docs/architecture.md) and the
[ADRs](../docs/decisions/); a plan restates them only where it deviates, and a deviation needs its
own ADR.

### `tasks.md` — verifiable steps

An ordered list. Each task states **what changes** and **how you know it worked** — a specific test
or command, not "verify it works".

**Test for a good task list:** each task is a reviewable change on its own, and the list has no step
that says "and then implement the feature".

## Directory convention

```
specs/
├── README.md                    this file
├── templates/
│   ├── spec-template.md
│   ├── plan-template.md
│   └── tasks-template.md
└── NNN-kebab-case-name/
    ├── spec.md
    ├── plan.md
    ├── tasks.md
    └── notes/                   optional: probe output, measurements, dead ends
```

Numbers are assigned in the order features are *started* and never reused. A gap in the sequence is
information — it means a feature was abandoned, and the directory says why.

## Status

Every artefact carries a status line in its front matter:

| Status | Meaning |
|---|---|
| `Draft` | Being written. Nothing downstream may start |
| `In review` | Complete, awaiting a gate |
| `Accepted` | Gate passed. The next artefact may start |
| `Implemented` | Code merged, conformance level reached |
| `Superseded by NNN` | Replaced. Kept, not deleted |

## Rules that are easy to break

**No technology in `spec.md`.** The most common failure, and the one that destroys the method: once
a spec names a library, it has started deciding *how*, and the review that was supposed to be about
*what* never happens.

**Every Jellyfin claim carries provenance.** `[probe: …]`, `[source: file:line @ tag]` or
`[spec: operationId]`. An unverified claim is marked `⚠️ UNVERIFIED` and keeps the spec in draft
(Principle II).

**Error paths are specified, not implied.** Absent item, wrong token, malformed profile, unreadable
file — each with its status code and its body. Clients branch on these more than on success.

**Every spec declares its conformance level** per endpoint, using L0–L3 from
[../docs/compatibility/conformance.md](../docs/compatibility/conformance.md). A spec that does not
say how it will be proven is not finished.

## Current specifications

| # | Feature | spec | plan | tasks |
|---|---|---|---|---|
| [001](001-server-identity-and-discovery/) | Server identity and discovery | **Implemented** | **Implemented** | **Implemented** |
| [002](002-authentication-users-and-sessions/) | Authentication, users and sessions | **Implemented** | **Implemented** | **Implemented** |
| [003](003-library-configuration-and-scanning/) | Library configuration and scanning | **Implemented** | **Implemented** | **Implemented** |
| [004](004-metadata-resolution/) | Metadata resolution | **Implemented** | **Implemented** | **Implemented** |
| [005](005-item-query-api/) | Item query API | **Implemented** | **Implemented** | **Implemented** |
| [006](006-images/) | Images | Draft | — | — |
| [007](007-user-data-and-playstate/) | User data and playstate | Draft | — | — |
| [008](008-playback-negotiation-and-delivery/) | Playback negotiation and delivery | Draft | — | — |
| [009](009-playlists/) | Playlists | Draft | — | — |
| [010](010-conformance-harness/) | Conformance harness | Draft | — | — |

**001, 002, 003, 004 and 005 are implemented.** The other five specs remain drafts, and their
open questions are the standing review agenda — **the next gate is 006's spec review**, probes
first, as every gate so far has taught.

**005's seventeen tasks kept the measured-first habit paying**, and the pattern sharpened: this
time the documents lost *acceptance criteria*, not only claims. AC-11 was **reversed** — season
0 sorts first on the measured wire, not last as the spec argued clients expect — AC-13 was
restated because a consequence already recorded in behaviours §5.3 makes the drafted containment
structurally unsatisfiable in Atrium, and AC-14 required populating `MatchedTerm`, a field
seventeen measured hints never carried. T1 had already split "one item representation" into
three route-dependent widths, T11's measurement overturned the Latest grouping rule (a group of
one surfaces as the item, not its container), and T13's probe confirmed the NextUp chain with
the one discriminating case reading could not settle. Each Done note in
[005's tasks](005-item-query-api/tasks.md) records one.

**005's task-list gate changed five things**, on 2026-08-27 — the two previous gates' class,
promises with no task holding them, plus a new one: two accepted documents disagreeing with
nothing measured between them. AC-1's "every list endpoint" was held one endpoint at a time,
with no test saying *every*; the spec and the plan disagree about whether search hints match the
sort name, which is now measured rather than arbitrated; a new probe had no row in
`tools/README.md` — the exact omission 004's gate caught, back for the very next script; the
filter summary's computation appeared in no accepted document; and the plan's own fixture
paragraph seeds one series where its own test table proves NextUp on three watched ones. Each is
recorded in [005's tasks](005-item-query-api/tasks.md#what-the-gate-changed).

**004's sixteen tasks contradicted eleven things the accepted documents asserted**, which is the
highest rate any feature has managed and the reason its ordering put measurement first. The three
that changed the most code: the reference **splits a genre on a slash** where plan §6.2 said it
does not and cited the parser that does; the **path-derived name is merged last, not third**,
without which AC-1 — "a film with a full `.nfo` resolves entirely from it" — is unreachable; and
the culture table is **not** the ISO 639-2 registry plan §6.9 named but a 192-row list only the
reference has. Each Done note in [004's tasks](004-metadata-resolution/tasks.md) records one.

**Its task-list gate had already changed three things** of the class 003's gate taught — promises
with no task holding them: AC-1 was only proven in a world with no remote code, the plan's opt-in
live test had no task, and a new tool had no row in `tools/README.md`. All three were delivered,
and the first turned out to be the most valuable thing on the list.

**002 measured more than it implemented.** Its eighteen tasks contradicted four things the accepted
specification asserted — a fifth authentication mechanism the surface had never listed, a disabled
account refused with `403` rather than the `401` the spec argued for on purpose, a client-header
grammar stricter than "lenient" in two ways, and `/Users/Public` disclosing every user's policy to
an unauthenticated caller. Each of them was one request away, and none was reachable by reading.

**All four probes have been run**, on 2026-08-26 against a live Jellyfin 10.11.11. Three confirmed
the documentation and one contradicted it:

| Question | Outcome |
|---|---|
| 005 OQ-6 — list envelope shapes | Confirmed, **plus three shapes** the original measurement never covered |
| 003 OQ-3 — sort-name derivation | Confirmed 15/15, **plus a second rule**: three item types bypass it entirely |
| 007 OQ-2 — completion thresholds | Answered: 90% / 5% / 300s, **and six branches** where the spec had two |
| 009 OQ-1 — `Move` semantics | **Contradicted.** The spec had the reading backwards; §3.5 and AC-8 corrected |

**Two more were written and run at the 004/005 spec gate**, on 2026-08-27, and the pattern held:

| Question | Outcome |
|---|---|
| 004 OQ-3 — genre re-normalisation | Confirmed: 97 of 97 by-name ids reproduce from the case-folded name, so §3.7 rule 1 is a reproduction, not a divergence — **and the merge was caught live**, two spellings on items collapsing into one row (behaviours §2.18) |
| 005 OQ-3 — sort tie-breaking | Answered: the reference appends almost nothing, **and its own artist-sort paging drops and duplicates rows** — the defect 005 §3.4 rule 2 now diverges from on the record (behaviours §3.6) |

The same gate found by hand-measurement that the accepted 005 spec's error path for enum values
was **wrong** — an unrecognised token is ignored, not `400` (behaviours §1.12) — and that query
parameter **names** match case-insensitively, which no route had needed before 005
(behaviours §1.15).

**003's task list changed at its gate**, on 2026-08-27, and the two changes that mattered were
tasks that were *not in it*: nothing measured the two open questions the specification names probes
for, and nothing extended the acceptance map — which `test_every_implemented_feature_has_a_map`
would have failed on the day 003 was marked `Implemented`. Reading a list tells you whether its
steps are right, not which step is missing; both were found by checking the list against files in
this repository. Four smaller corrections are recorded in
[003's tasks](003-library-configuration-and-scanning/tasks.md#what-the-gate-changed).

Every one returned more than it was sent to check. That is the argument for running a probe before
writing a plan rather than after. Running them is the cheapest work available and it
changes what the specs say, so it belongs before the plans, not after. See
[tools/README.md](../tools/README.md#probes).

The order and rationale are in [../docs/roadmap.md](../docs/roadmap.md#feature-order).
