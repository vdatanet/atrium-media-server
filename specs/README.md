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
| [006](006-images/) | Images | **Accepted** | **Accepted** | Draft |
| [007](007-user-data-and-playstate/) | User data and playstate | Draft | — | — |
| [008](008-playback-negotiation-and-delivery/) | Playback negotiation and delivery | Draft | — | — |
| [009](009-playlists/) | Playlists | Draft | — | — |
| [010](010-conformance-harness/) | Conformance harness | Draft | — | — |

**001, 002, 003, 004 and 005 are implemented; 006 is accepted through its plan and its task
list is written** — thirteen tasks against the accepted plan, measurement first, bytes before
HTTP — awaiting **the task-list gate, the next artefact**, before T1 begins. The four specs
after it remain drafts, and their open questions are the standing review agenda.

**006's plan gate measured before accepting, and the measurements changed the accepted spec
twice**, on 2026-08-28. The plan's §6.8 had catalogued the edges no probe had covered; a
manual-request sweep answered them, and two answers contradicted accepted documents. **AC-6 was
corrected** — `fillWidth`/`fillHeight` do not crop: they scale to cover and keep the overflow,
300×600 asked of a 2000×3000 source returning 400×600. The earlier probe had measured "exactly
the box" on a source that was itself square, where covering and cropping are indistinguishable —
the second acceptance criterion this project has reversed by measurement, 005 AC-11's class.
**AC-15 was added** — a transformed response negotiates `Accept: image/webp` under a
`Vary: Accept` sent on every image response. The plan's own §10 had rejected content negotiation
as a delta, and the measurement reversed the rejection: the earlier probe's offer rode a request
nothing transformed, which negotiates nothing, so every browser-based client was quietly owed
WebP posters no document promised. The sweep also found a **fourth error shape**
([behaviours §1.11](../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)):
the route's absent-image `404`s answer a JSON-encoded string naming the item — on a tokenless
route — while its unknown-item `404` stays problem details, one route splitting its two lookups
across two shapes. The rest confirmed the plan as drafted: invalid tokens change nothing,
`format=Banana` drops, `Svg` short-circuits to the verbatim path, both-axes resizing distorts,
the `304` is the `200`'s header set minus `Content-Length`, and `?imageIndex` selects the
backdrop it names. Every answer is folded into [the spec](006-images/spec.md),
[the plan](006-images/plan.md) and behaviours §1.11, with EXIF orientation the one edge a remote
request cannot reach.

**Writing 006's plan changed one row of the accepted spec**, on 2026-08-28. §3.2's error table
read "`imageType` outside §3.2's set → `400`", and the measurement it cites distinguishes the
reference's thirteen-member **vocabulary** from an item's holdings: a string outside the
vocabulary is `400`, while `Box` — a member outside §3.2's eight — measured `404`. Implemented
literally, the eight-member reading would have manufactured a `400` where the reference answers
`404`, on the first request any probing client sends for a type this server does not carry. The
row now names the vocabulary. The plan's §6.8 lists the six edges no probe has measured — an
invalid token on the tokenless route, the format-vocabulary collision, both-axes resizing, the
error bodies, the `304`'s headers, the query-spelling index — each owed a measurement task before
its code lands.

**006's spec gate ran probes first, and both halves moved the document**, on 2026-08-28. The
review found the exact class 005's gate named — two documents disagreeing with a measurement
between them: §3.2 required authentication while 002 AC-3, the criterion it claimed to share,
records the measured opposite. The decision behaviours §2.10 had deferred to 006 is now taken
the way every prior collision resolved — a token accepted, none required, an item id a
capability. Two new probes answered five of the six open questions the same day, and the
sharpest finding was one no reading could reach: the reference sends **no `ETag` and no
`Accept-Ranges` on an image response** — `Last-Modified`/`If-Modified-Since` is the validator
pair it actually serves, so §3.4 and AC-9 now assert the pair that exists. The rest of the
measurement: a stale `tag` serves the current image byte-identically (AC-10 is a reproduction),
an unparseable dimension is `400` — the one measured error path that is **not** lenient, where
behaviours §1.12 would have predicted forgiveness — an explicit `format=Jpg` on a transparent
logo is honoured and discards the alpha, and chapters advertise `ImageTag` per `Chapters` entry.
OQ-4 stays open for 010's differential harness. The record is
[006's spec](006-images/spec.md) itself: every answer went back in with its citation, in the
same change.

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
