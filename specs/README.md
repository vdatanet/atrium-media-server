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
| [001](001-server-identity-and-discovery/) | Server identity and discovery | Draft | — | — |
| 002 | Authentication, users and sessions | — | — | — |
| 003 | Library configuration and scanning | — | — | — |
| 004 | Metadata resolution | — | — | — |
| 005 | Item query API | — | — | — |
| 006 | Images | — | — | — |
| 007 | User data and playstate | — | — | — |
| 008 | Playback negotiation and delivery | — | — | — |
| 009 | Playlists | — | — | — |
| 010 | Conformance harness | — | — | — |

The order and rationale are in [../docs/roadmap.md](../docs/roadmap.md#feature-order).
