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
| [001](001-server-identity-and-discovery/) | Server identity and discovery | **Accepted** | **Accepted** | Draft |
| [002](002-authentication-users-and-sessions/) | Authentication, users and sessions | **Accepted** | **Accepted** | Draft |
| [003](003-library-configuration-and-scanning/) | Library configuration and scanning | **Accepted** | **Accepted** | Draft |
| [004](004-metadata-resolution/) | Metadata resolution | Draft | — | — |
| [005](005-item-query-api/) | Item query API | Draft | — | — |
| [006](006-images/) | Images | Draft | — | — |
| [007](007-user-data-and-playstate/) | User data and playstate | Draft | — | — |
| [008](008-playback-negotiation-and-delivery/) | Playback negotiation and delivery | Draft | — | — |
| [009](009-playlists/) | Playlists | Draft | — | — |
| [010](010-conformance-harness/) | Conformance harness | Draft | — | — |

**001, 002 and 003 are specified, planned and broken into tasks.** That is the whole dependency
root of v1: everything else needs at least one of them. The other seven specs remain drafts — no
plan may start until its spec is accepted, and no code until its plan is. The open questions across
the ten are the review agenda.

**All four probes have been run**, on 2026-08-26 against a live Jellyfin 10.11.11. Three confirmed
the documentation and one contradicted it:

| Question | Outcome |
|---|---|
| 005 OQ-6 — list envelope shapes | Confirmed, **plus three shapes** the original measurement never covered |
| 003 OQ-3 — sort-name derivation | Confirmed 15/15, **plus a second rule**: three item types bypass it entirely |
| 007 OQ-2 — completion thresholds | Answered: 90% / 5% / 300s, **and six branches** where the spec had two |
| 009 OQ-1 — `Move` semantics | **Contradicted.** The spec had the reading backwards; §3.5 and AC-8 corrected |

Every one returned more than it was sent to check. That is the argument for running a probe before
writing a plan rather than after. Running them is the cheapest work available and it
changes what the specs say, so it belongs before the plans, not after. See
[tools/README.md](../tools/README.md#probes).

The order and rationale are in [../docs/roadmap.md](../docs/roadmap.md#feature-order).
