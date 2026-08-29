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
| [006](006-images/) | Images | **Implemented** | **Implemented** | **Implemented** |
| [007](007-user-data-and-playstate/) | User data and playstate | **Implemented** | **Implemented** | **Implemented** |
| [008](008-playback-negotiation-and-delivery/) | Playback negotiation and delivery | **Accepted** | **Accepted** | — |
| [009](009-playlists/) | Playlists | Draft | — | — |
| [010](010-conformance-harness/) | Conformance harness | Draft | — | — |

**001 through 007 are implemented**, 007 on 2026-08-28 across thirteen tasks. **008's spec and
plan were accepted on 2026-08-29** at a review that wrote and ran the five probes its open
questions had been citing prospectively — all twelve OQs answered, five claims overturned (the
policy story, the body's `EnableTranscoding` switch, `static=true` as an error, `enableRedirection`'s
`302`, and the HLS half of the §3.5 divergence, which measured as parity), and two defects found
that nobody was looking for (behaviours §3.7 and §3.8: the Opus rate ladder applied to every
codec, and the codec-less empty `200`). **008's tasks are next**; 009 and 010 remain drafts, and
their open questions are the standing review agenda
([007's tasks](007-user-data-and-playstate/tasks.md#what-this-feature-owes-the-next-ones) names
what 008 inherits).

**007's thirteen tasks found something in seven of them, and two were features that did not
exist.** The sharpest is T11's: **the container `PlayedPercentage` had never been implemented.**
`PlayedPercentage` was position-over-runtime for every item — the *leaf* reading — so AC-20's
first half ("a bare container row carries no percentage") passed because there was no percentage
to gate. The second half was unreachable. T8's is the same class seen from the wire: **this
project's first typed request body answered `{"item_id": …}`**, snake_case, because the framework
keys validation errors on the model's Python field — behaviours §1.1's exact failure, in a body
nothing had ever sent, since 002's only body is read with `request.json()` and never bound. The
routes now name their body parameters after the reference's and the handler files a body failure
under `""` or `"$"` beside `The <parameter> field is required.`, measured byte for byte.

**Three findings came from measuring rather than reasoning.** T1's probe run found that
`NowPlayingItem`'s **width is the item's, not the shape's** — two movies measured 41 and 40
properties, the difference being a null `IsHD` — which is a false positive waiting for 010's
differential if it compares counts. T9 measured the property *list* rather than the count and
replaced the plan's design with it: the shape is a **subtraction**, a full item body minus a named
fifteen, so 005's existing `omit` mechanism expresses it exactly and `MediaSources` is already
excluded for the day 008 emits it. And T2, implementing the six-branch rule, found that
**row 4's second clause decides nothing** under the reference's own thresholds: "within one second
of the end" implies "past 90%" for anything longer than ten seconds, and anything shorter is
completed by the runtime floor — the spec's paragraph explaining why the clause was *not*
redundant had the arithmetic backwards.

**And two were about this repository rather than about Jellyfin**: `last_playback_check_in` had
**no writer at all** — 002 created the column, reflected it back and never moved it, so a session
that had played something reported `0001-01-01` for ever (T7) — and three of T8's route tests were
passing for the *fixture's* reasons rather than the route's, because the seeded films carry a
resume position and "nothing was written" was reading numbers the world had put there.

**OQ-7 was resolved with an answer the question did not anticipate** (T11): for four of the five
container types it cannot be asked at all, because an empty `Series`, `Season`, `MusicArtist` or
`MusicAlbum` does not earn its place and is not offered. The one exemption is a library folder,
where Atrium reads `Played: false` and the reference's source reads vacuously played —
[behaviours §5.7](../docs/compatibility/behaviours.md), owed to 010.

**007's task-list gate changed four things**, on 2026-08-28, and the first is the class 006's
gate taught, back for the very next feature. **The seeded world has exactly one runtime** —
`tests/fixtures/query.py` gives one to a single film and to nothing else — so §3.7's rule, which
is a function of runtime, had one item to run on at route level, and **row 5, the short-item
branch OQ-6 opened and measured, had no world at all**. **Nothing has ever written
`last_playback_check_in`**: the plan hands the column to 002's activity flusher, whose `touch`
writes `last_activity_date` alone, so "the flusher's existing pass writes both columns" is a
change to make rather than a property to lean on. **OQ-7 belongs to this list**, not to 010 —
the fixture library can build an empty container, so the empty-subtree answer is a decision to
take here, and today it lives in a docstring, which is exactly how 006 found an exception
withdrawn three features earlier. And **AC-16 needs no new test**: 003's own AC-11 already
plants a favourite and a resume position, deletes the file, rescans and restores it, from the
other side of the same guarantee. Each is recorded in
[007's tasks](007-user-data-and-playstate/tasks.md#what-the-gate-changed).

**007's plan gate measured before accepting, and the sharpest answer was an absence**, on
2026-08-28. The gate ran plan §6.8's four catalogued batteries as hand requests against the
live reference: a playing session's `NowPlayingItem` — a `BaseItemDto` width nothing had ever
captured — carries 41 properties and **no `UserData`**, sits between `DeviceName` and
`DeviceId`, and includes nine media-derived properties v1 cannot yet emit, now a named gap in
the spec rather than a silent one; `PlayState` is **replaced whole by each report** — a
progress omitting `CanSeek` reads back `false` — where the draft plan had left merge-or-replace
to the implementer; the error shapes all landed on behaviours §1.11's existing taxonomy
(problem-details `404`, validation `400`, the `text/plain` controller refusal for a negative
position, the empty `401`); a `Start` carrying 30% leaves the stored position at 0; and a
movie's `UserData.Key` measured as the item's own GUID **in dashed form** beside the 32-hex
`ItemId` — one object spelling one identity two ways. Spec §3.6 gained the playing-session
block and AC-21/AC-22; nothing measured contradicted the plan's structure, and the plan moved
to `Accepted` the same day.

**007's plan stores nothing new**, on 2026-08-28: `item_user_data` has been complete since 003
— the deliberately absent foreign key *is* the survival guarantee — so the plan is five
decisions about writers. The measured semantics become pure functions in `domain/playstate.py`;
live playback state stays in memory with the reference's ticking position computed at read time
rather than by a per-second timer; the cascade is a write-time sweep over the leaves through
005's visibility scope; the mark responses are built by the same hydration path as list rows;
and the controller split mirrors the reference's. Plan §6.8 catalogues what no probe has
measured — sharpest, the playing session's `NowPlayingItem`: a `BaseItemDto` width nothing has
captured, which is 005 T1's lesson pointed at `/Sessions` — for the gate to answer before
accepting.

**007's spec review measured first and corrected four accepted-draft claims**, on 2026-08-28.
Reading the reference's source predicted all four and the extended `tools/probe_playstate.py`
confirmed each on the wire: a bare `POST /UserPlayedItems` is **`max(count, 1)`** — only the
`datePlayed` form increments, so AC-3's "increments" was wrong; **nothing guards against an
older position** — a progress at 40% then 20% reads back 20%, reversing AC-10, because a
deliberate seek backwards arrives as exactly that report; **a play is counted at `Start`**,
which also sets `Played` to *false* on a previously played item, while a positionless stop
counts a second time; and **the six-branch rule runs on every position-bearing report**, so a
progress past the ceiling marks played mid-playback. The `--reap` battery answered OQ-4 with
more than the question asked: the session cleared after 8.6 minutes of silence and the stored
position was **48.5%, not the reported 40%** — a per-session one-second ticker extrapolates the
unpaused position in real time and the reap commits the extrapolated value, so AC-15's "last
position intact" came back 8.6 minutes richer (spec §3.8). Also pinned: strict boundaries at
tick precision, the cascade that writes leaves and never the container's own row, favourites
that do not cascade, the field-gated container `PlayedPercentage`, and OQ-1's survey — no
analysed client reads `UserData.Key`. One question opened: OQ-7, the empty container the
source reads as vacuously played where 005 shipped unplayed.

**006's thirteen tasks found something in nine of them, and three were in documents that had
already been accepted.** The sharpest is T12's: **the image tag could never change.**
`Field.IMAGES` merged under the rule that keeps whatever an item already has unless the refresh
mode is `Replace` — and v1 has no refresh route through which anything could ask for `Replace` —
so an item that had ever been given artwork could never be given different artwork, at any scan
depth. AC-2's second half was unreachable and client-side cache invalidation with it: a tag that
cannot change is a poster that can never be corrected. The field is `REDERIVED` now (004's plan
§6.1 carries the amendment), and the residual limitation is recorded rather than hidden —
a *default* scan reads an item's artwork only when its media file changed, so a replaced poster
needs a deep scan
([behaviours §5.6](../docs/compatibility/behaviours.md#56-a-default-rescan-does-not-notice-a-replaced-poster)).

**T6 deleted a universal the spec had stated three times**: "never upscale" is a property of
*which parameter was sent*, not of the server. `maxWidth`, `maxHeight` and the fill pair are
capped at the source; `width` and `height` are honoured past it — `width=4000` of a 2000×3000
source measured **4000×6000**. Implemented literally, Atrium would have answered a *smaller*
image than a client asked for by name, on the one path whose entire meaning is "this size".

**T1's probe found what its own output had been printing since the spec review**: a forgiven
parameter is not a dropped one. `maxWidth=-100` answers `200` at the source's dimensions and
**three times its bytes** — the reference re-encodes — while a bare `quality` does *not* transform
at all, where the plan had made it a reason to re-encode every poster for the clients that append
one out of habit ([behaviours §1.17](../docs/compatibility/behaviours.md)).

And three that are about this repository rather than about Jellyfin: **behaviours §4.4 had been
withdrawn for three features without anybody saying so** — 005 T4 reversed it and 006's task list
still cited it as standing (T3); **T5's hostile-path test passed with the containment check
deleted**, because `../../../../etc/passwd` from a `tmp_path` root reaches nothing, so the
refusal it asserted was the wrong refusal; and **T8's AC-8 failed against the obvious
implementation**, because deciding the transform from the file's dimensions rather than the
row's makes the cache key move whenever the file does.

**006's task-list gate changed four things**, on 2026-08-28 — two of them the exact classes
earlier gates taught, back for the very next feature. [Spec §6](006-images/spec.md#6-conformance)'s
"Indexed form" conformance row had no task holding its **positive** case — every index test in
the draft was an error test, and nothing asserted that `/Backdrop/1` returns backdrop 1; AC-14's
discriminating fixture **does not exist** — no seeded episode carries artwork of its own, because
005 never needed one, so "inheritance does not gate on the child's own images" was a criterion
with no world to prove it in, 005's fixture lesson one feature later; the draft cited an
all-routes PascalCase canonicalisation test **that does not exist in that shape** — found by
opening `tests/unit/test_compat_query_params.py`, not by re-reading the list, which is 003's
method paying again; and AC-12's "over the mechanism list itself" now names the importable
enumeration, so "not a copy" is an import rather than an aspiration. Each is recorded in
[006's tasks](006-images/tasks.md#what-the-gate-changed).

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
