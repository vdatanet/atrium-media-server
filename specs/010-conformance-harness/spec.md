---
feature: 010-conformance-harness
title: Conformance harness
status: Accepted
created: 2026-08-26
updated: 2026-09-01
amended: 2026-09-01 at the measurement gate — the spec was written before the thing it compares existed, and four probes moved it. §7's four open questions are answered and closed. **OQ-1's premise survives and its remedy does not:** identifiers cannot join two servers, but neither can a path — the reference sends none on a default list row at all, so a run that joins on one is comparing requests no client sends; asking for it still leaves a virtual season, a remote channel and every by-name row with nothing to join on, and the paths those rows do carry name the reference installation's own data directory. **OQ-3 is answered yes for reads and no for the feature:** every read of the surface but three answers byte-identical bodies on repeated identical requests, and the only header values that move are the response time and the clock — but a recording answers only the requests it recorded, which is the class of defect L3 exists to find, so a recorded session is a regression net and never the gate. **OQ-4's two non-deterministic endpoints are three, and the third is not an endpoint:** `/UserViews` answers a fresh random `ChildCount` between 1 and 9 on every request, because the reference declines to count a top-level folder and substitutes a number so clients will not think it empty. **The allowlist §3.3 describes cannot express any of them:** it is a list of fields compared by shape, and what these need is a whole array excused, which is a second mechanism and now a stated one. Plus the three things the gate found that nobody asked about: `/Items/{itemId}/Similar` is not a ranking at all but a fresh draw whose successive answers share **nothing**, and on a **movie** seed it answers `limit + 4` rows where the pinned document calls `limit` a maximum — both new divergences against an implemented feature, and both owner decisions; and a differential that authenticates once measures half the table — **12 of 23 reads of the surface answer differently to a restricted non-administrator**, two of them not as refusals but as shorter lists. §3.9 and §3.10 are new sections, §5 gains five criteria, and the fixture-differential AC-2 is recorded as unreachable from the only reference this project can reach.
depends_on: [001, 002, 003, 004, 005, 006, 007, 008, 009, 011]
---

# 010 — Conformance harness

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.
>
> This feature has no HTTP surface. Its "clients" are the project's own contributors, and its
> observable outputs are reports and CI results. It is specified rather than left as scaffolding
> because Principle VIII makes it the thing that decides when any other feature is done.

## 1. Purpose

Prove that Atrium behaves like Jellyfin, and — more valuable — **find the places where it does
not, that nobody thought to ask about.**

Levels L0 through L2 test Atrium against what this project *believes* about Jellyfin. They cannot
catch a belief that is wrong. **L3, the differential layer, is the only thing in the project that
can**, and delivering it is what this feature is for.

**Unlocked:** the ability to say "compatible" and mean something measurable.

**And one thing this feature must not pretend.** A differential is a sweep, and a sweep finds only
what a request under comparison exposes. Six implemented features have each handed this one a list
of differences a sweep will **not** raise — because they need a caller the run does not have, a
library the reference cannot be given, or a comparison of something that is not in a body. Those
are §3.10, they are named rather than discovered, and a harness that reports a clean run without
them is reporting the absence of the questions it did not ask.

## 2. Scope

**In scope**

- The differential harness: same request to both servers, structural comparison, triaged report.
- The **identities** a run authenticates as, and what the second one buys (§3.9).
- The **named comparisons** (§3.10): the differences the sweep cannot raise, run deliberately.
- The allowlist of legitimately-varying fields *and arrays*, and the discipline around changing it.
- The fixture library as a build artifact reproducible on both servers.
- The probe-script convention, and discharging the prior-measurement debts.
- The ignored-parameter report from 005 §3.3.
- The version-bump procedure of `conformance.md`, as an executable process.
- CI wiring: what runs always, what runs on demand.

**Out of scope**

- L0 and L1 machinery, delivered by 001 — this feature consumes them.
- Performance benchmarking. Correctness only.
- Testing Jellyfin. When a difference is Jellyfin's defect, it is recorded, not fixed here.
- **Deciding what Atrium does about a difference this feature finds.** The harness triages
  (§3.4); the answer belongs to the feature that owns the endpoint, through
  [behaviours §3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made). The gate
  that accepted this document found two such differences and left both to 005 (§7).

## 3. Behaviour

### 3.1 The fixture library

One directory tree, checked in as **metadata only**, from which both servers build a library.

| Content | Form |
|---|---|
| Directory structure and filenames | Checked in |
| `.nfo` sidecars | Checked in |
| Artwork | Tiny generated images, built at build time |
| Media files | Synthetic — seconds of colour bars and a tone, muxed at build time |

**No copyrighted media, ever.** Not a clip, not a sample, not "just for testing".

Building it is deterministic: the same generator inputs produce byte-identical files, so both
servers probe the same thing and a difference in output is a difference in the server.

**Two of these worlds already exist**, built by the features that needed them rather than by this
one — a paths-and-filler world for scanning and a real-media world for delivery, described in
[conformance.md](../../docs/compatibility/conformance.md#l2--semantic). What this feature adds is
not a third world. It is the part neither of them has: **the same tree on the other server.**

The fixture deliberately contains the cases that break naive implementations — the ones enumerated
across 003 §5, 005 §5 and 009 §5: multi-part films, `S01E02-E03`, specials, a series named `24`,
multi-disc albums, compilations, tags that contradict paths, non-ASCII names, names differing only
by case, and a playlist with duplicate entries. Five more are owed by features that landed after
this document was written, each because the difference it exposes is unreachable without it: a
**multi-part film** (008 — one media source per part here, one source and a part count there), a
film with a **subtitle file beside it** and one with an **image subtitle track** (011), a subtitle
file in a **legacy encoding** (behaviours §5.11), and a **playlist holding items from two
libraries** (§3.10).

**AC-2 needs a reference this project controls, and the reachable one is not it.** The only
Jellyfin this repository can measure is an operator's own server, holding an operator's own
library, on another machine. Both halves of "point both servers at the same built fixture" are
refused by that: the fixture tree is not on the reference's filesystem, and adding a library to it
would be writing to data this project does not own. **AC-2 is therefore unreachable until a
reference instance exists that the project may configure and discard**, and that is an
infrastructure decision recorded here rather than a step a run can take. Everything in §3.9, §3.10
and §7 was measured without one, against the real library, which is why each of those is a *named*
measurement and not a sweep.

### 3.2 The differential run

```
for each identity in the identities of §3.9:
    for each endpoint in surface.yaml:
        for each request case defined for it:
            response_a = atrium(request)
            response_b = jellyfin(request)
            compare(response_a, response_b)
```

**Comparison is structural, in three passes**, because the three failures are not equally serious:

| Pass | Finds | Severity |
|---|---|---|
| **Key sets** | A field one server sends and the other does not | Highest — a missing field is invisible to L1 and L2, which only check what we knew to check |
| **Types** | Same key, different JSON type | High — `"5"` versus `5` breaks decoders |
| **Values** | Same key and type, different content | Triaged; many are legitimate |

**Key-set differences are the entire point of the exercise.** They are the only class of defect
that this project structurally cannot find any other way, and the report ranks them first.

Headers are compared too, on the delivery routes, where `Content-Length`, `Accept-Ranges`,
`Content-Range` and `Content-Type` are the contract.

**Three things the passes above cannot do on their own, all measured at this document's gate.**

1. **A row has to be found before it can be compared, and nothing on the wire identifies it.**
   Identifiers cannot: the two servers derive them differently and matching the reference's bytes
   is explicitly not a goal ([behaviours §1.4](../../docs/compatibility/behaviours.md)). The path
   is the only value two servers scanning one tree could agree on, and it is **absent from every
   default list row** — 0 of 1000 — so a run that joins on it has changed the request it is
   comparing. Asked for by name it still covers only what is file-backed: a virtual season and a
   remote channel carry none, and every by-name row carries one naming *the reference
   installation's own data directory*, which no fixture reproduces. `(Type, Name)` is not a key
   either — 976 distinct of 1000 rows on a real library.
   `[probe: tools/probe_differential_join.py, Jellyfin 10.11.11, 2026-09-01]`
   **So arrays are compared as ordered sequences and rows by position**, which makes the ordering
   part of the contract under test rather than a convenience.
2. **Position is only a comparison where the ordering is total, and the reference's is not.** Its
   ties are engine-resolved and its artist sorts lose and duplicate rows across pages, which is a
   recorded divergence ([behaviours §3.6](../../docs/compatibility/behaviours.md)). A positional
   comparison of any response ordered by a key with ties reports differences that are Atrium doing
   what §3.6 says it does. Those responses are compared **as multisets of rows**, and the ordering
   difference is the allowlist row rather than the finding.
3. **Three read shapes are draws rather than readings**, and no comparison of their rows means
   anything (§3.3, and OQ-4 in §7).

### 3.3 The allowlist

Fields compared by **shape** rather than by value, each with a written reason.

| Field | Why it may differ |
|---|---|
| `Id`, `ItemId`, `ServerId`, `ParentId`, `SeriesId`, `SeasonId`, `AlbumId`, … | Derivation differs by design (behaviours §1.4) |
| `DateCreated`, `DateLastSaved`, `DateLastMediaAdded`, `LastActivityDate` | Scan wall-clock time |
| `Etag`, `ImageTags.*`, `PlaySessionId`, `AccessToken` | Content hashes and generated identifiers |
| `Path` | Different mount points, and on the by-name rows a different installation's data directory (§3.2) |
| `LocalAddress` | Deliberate divergence (behaviours §4.2) |
| `TotalRecordCount` on by-name endpoints without `limit` | Deliberate divergence (behaviours §3.1) |
| `X-Response-Time-ms`, and the response clock | Move on every response, measured on 19 of 19 read cases (§7 OQ-3) |
| `ChildCount` on a library view | **The reference's value is a fresh random integer** (§7 OQ-4) |

**A field is not the only unit a difference comes in**, and the gate found three that this table
cannot express. Where the reference's *whole answer* is a draw, no field of it is comparable and
excusing them one by one would excuse the response. Those get a **second kind of entry — an
excused array** — which states the endpoint, the request shape that triggers it, and what is still
compared when the rows are not:

| Array | Why it may differ | What is still compared |
|---|---|---|
| The rows of `/Items/{itemId}/Similar` | A fresh draw per request; four identical requests shared **no** item (§7 OQ-4) | Key sets and types of each row, the envelope's own properties, and the row **count** |
| The rows of any listing ordered at random | The same, by the caller's own request | The same |
| The rows of a listing ordered by a key with ties | The reference's ordering is not total (behaviours §3.6) | Everything, as a multiset rather than a sequence |

**Adding an entry of either kind is a contract decision, not a way to make a red run green.** It
happens in review, the reason goes in the table, and an entry justified by "we do it differently"
without a behaviours.md entry backing it is rejected.

The allowlist is also **a metric**: it should shrink over time as derivations converge, and a run
that grows it is worth a second look. The excused arrays are the exception that proves it — none of
the three can ever be removed, because none of them is Atrium's to converge with.

### 3.4 The report

One document per run, and it is the deliverable — not a pass/fail line.

```
Differential run — Atrium <sha> vs Jellyfin 10.11.11 — <date>

  identities             <n>
  endpoints compared     59
  request cases          <n>
  identical              <n>
  allowlisted            <n>
  DIFFERENCES            <n>

  Missing keys        (n)    <-- read these first
  Extra keys          (n)
  Type mismatches     (n)
  Value mismatches    (n)

  Named comparisons   (n of the §3.10 list run, n outstanding)
```

Each difference carries the endpoint, the request case, **the identity that sent it**, the JSON
path, both values, and — where it matches a known entry — a link to the behaviours.md section that
explains it.

**Every difference is triaged into one of four outcomes**, and none of them is "ignore":

| Outcome | Meaning |
|---|---|
| **Fix** | Atrium is wrong. A defect, against the owning feature |
| **Replicate** | Jellyfin's behaviour is odd; we match it. A behaviours.md entry |
| **Diverge** | We deliberately differ. A behaviours.md entry with the argument, and an allowlist row |
| **Defer** | Out of v1 scope. Recorded with the feature that will resolve it |

An untriaged difference blocks the run from being called clean. **So does an unrun named
comparison**: the §3.10 list is part of the report's coverage line, not a footnote to it.

### 3.5 Probe scripts, and the debt

Every probe under `tools/` follows one convention:

1. Takes a server URL and credentials.
2. Makes the minimum requests needed to answer **one** question.
3. Prints its finding **and its own citation**, in the form the documentation uses:
   `[probe: tools/probe_x.py, Jellyfin 10.11.11, 2026-08-26]`.
4. Exits non-zero if the finding contradicts what the documentation currently claims.

That last point turns the probes into a regression suite for the project's *beliefs*, not just its
code. When a server upgrade changes a behaviour, the probe says so instead of the documentation
quietly becoming false.

**A probe that writes creates what it needs and removes it, including on failure**, and never
touches anything the operator owns. Three of them now build a throwaway account, because the
question they answer is invisible from an administrator's seat (§3.9).

**This feature discharges the prior-measurement debts** registered in
[reference-target.md](../../docs/compatibility/reference-target.md): each becomes a probe script,
and its citation changes from `prior-probe` to `probe`. A claim that fails to reproduce is not
deleted — it becomes a behaviours.md entry recording that the behaviour *changed*, with both dates.

### 3.6 The ignored-parameter report

005 §3.3 accepts a bounded delta: Tier 3 query parameters are ignored rather than rejected, and
counted.

This feature turns that counter into a report — parameter, endpoint, count, and the client that
sent it — so the accepted delta has a closing mechanism instead of being a permanent excuse. Any
parameter that appears gets promoted to Tier 2 or explicitly declined in writing.

### 3.7 What runs when

| Job | Runs | Requires |
|---|---|---|
| Surface validation | Every change | Nothing beyond the repository |
| L0 route registration | Every change | Atrium |
| L1 sweeps and golden responses | Every change | Atrium |
| L2 fixture tests | Every change | Atrium and a built fixture |
| **L3 differential** | On demand, and on every reference-version bump | A real Jellyfin |
| **The §3.10 named comparisons** | On demand, and on every reference-version bump | A real Jellyfin, and for most of them a second identity |
| Probe scripts | On demand, and on every bump | A real Jellyfin |
| Live-provider tests (004) | On demand only | Network and credentials |

**L3 is opt-in and never gates the default CI job.** It needs a second server, so making it
mandatory would make the build depend on infrastructure a contributor may not have. It is *the*
gate on a version bump, where it matters most.

**No test that runs by default touches the network.** Principle VII.

### 3.8 The version-bump procedure

[conformance.md](../../docs/compatibility/conformance.md#when-the-reference-version-moves) defines
it; this feature makes it executable as a single command that runs the steps in order and refuses
to continue past a failure:

1. Fetch the new OpenAPI document; validate the surface. Disappeared paths are breaking changes.
2. Run the full differential, and the §3.10 named comparisons. Triage every new difference into
   behaviours.md.
3. Re-run every probe. Update the `Last verified` line of every document they support.
4. Only then change the pinned version.

**A bump that skips step 2 has not been done, it has been declared.** The command enforces the
order so that the shortcut is not available.

### 3.9 The identities a run authenticates as

**A run that authenticates once measures one row of a two-row table, and its report says nothing
about the other.** Every probe written before this document was accepted authenticated as an
administrator, and an administrator lacks no permission — so no measurement in this repository had
ever been taken from a seat that could be refused something.

Measured, on the same twenty-three reads of the surface issued twice — once as the administrator,
once as a throwaway non-administrator restricted to one library — **twelve answer differently**:

| The answer changes as | Endpoints |
|---|---|
| **A refusal** | an item in a library the reader cannot open; a playlist read that does not name its owner |
| **A narrower object** | the caller's own user record — twelve properties to an administrator, ten to everybody else |
| **A shorter list** | the views; the item listing and its total; resume; next up; the artists; the genres; the music genres; the years; the sessions |

`[probe: tools/probe_restricted_surface.py, Jellyfin 10.11.11, 2026-09-01]`

**The second row is the dangerous one and the third is the expensive one.** A refusal is a status
code and any comparison sees it. A *shorter list* is a `200` that differs only in how many rows it
holds, which is exactly the shape §3.10's two playlist comparisons take — and exactly what a run
looking for missing keys will pass over.

So: **a run states its identities, and a run with one identity is reported as covering one.** The
minimum is two — an administrator and a restricted non-administrator whose library access is
narrower than the library — and the restricted seat is **created and destroyed by the run**, never
borrowed from the operator.

### 3.10 What a differential cannot find on its own

Six implemented features each ended with a list of what it leaves the next ones, and 010 collects
most of them. **The rows below are the ones a sweep will not raise**, each for one of three
reasons, and each is run deliberately with its own written comparison:

| The difference | Why the sweep misses it | What the named comparison is |
|---|---|---|
| A playlist read that **names its own reader** (behaviours §3.16) | It needs a caller the run does not have | Issue the read naming the owner **as a restricted non-administrator**: entries there, a refusal here |
| **Entries a reader cannot reach** (behaviours §3.17) | Over a stock library the two servers *agree*: what the reference hides is hidden by a rating check, never by library access | A reader restricted to one library, a playlist holding items from two. **The row count is the whole signal** |
| The **de-duplication that misses** (behaviours §3.18) | The reference disagrees with *itself* — 6 of 8 identical requests behaved differently | Run the add twice; a disagreement is the entry, not a flake to retry |
| A progressive re-encode's **missing self-description** (behaviours §3.3) | §6 declines to byte-compare produced media | Parse the first frames of both servers' progressive output and compare the header frame's presence, not the bytes after it |
| **Burn-in** (behaviours §5, subtitle row) | The same: the difference is in the pixels | Negotiate a track that resolves to an encode on both, produce a few seconds, look for the cues in the frames |
| The manifest's announced **track name** (011 §6) | It differs by the reference host's culture, not by the server | Compare the announced entries with the name masked, and the name against the invariant form |
| A subtitle playlist's **decimal point** (behaviours §3.12) | A parser normalises it away | Byte-compare the two playlists |
| The **delivery-time policy refusal** (behaviours §2.21) | It needs an account with a denied playback permission | The §3.9 restricted seat, with that permission denied: bytes there, a refusal here |
| An image track's `400` arriving **without twenty seconds of waiting** (011) | Nothing in a body carries elapsed time | Measure the latency of both, not the payload |
| A **multi-part film**'s media sources (008) | No reachable library has one | Needs the fixture of §3.1 |
| A media source stating **no runtime**, and a zero-length cue's millisecond (011) | No reference library can be put into either state from outside | Reported as a **miss** by its own probe on every run, rather than inferred |
| A subtitle file in a **legacy encoding** (behaviours §5.11) | An all-UTF-8 library never raises it | Needs the fixture of §3.1 |
| **EXIF orientation on resize** (006) | No remote request reaches the edge | Needs a planted file in a controlled library |
| An **empty library**'s played state (behaviours §5.7) | The only shape where the question is askable | A server with an empty library — a differential's job rather than a probe's |
| The **`"$"` message** in a body-binding refusal (behaviours §1.11) | Nothing; it *will* be found — on the first malformed body | Listed so it is recognised rather than triaged twice |
| A **body with no content type** on five routes (009) | Measured on one of the five | The other four, one request each |

**The last two rows are here to be recognised, not discovered.** The rest are the feature's real
inheritance: a harness that reports a clean run without them has proved that the questions it asked
have the same answers, which is a smaller claim than it sounds.

## 4. Data the feature owns

| Artefact | Where | Lifetime |
|---|---|---|
| Fixture library sources | Repository | Permanent |
| Built fixture media | Build output | Disposable, regenerable |
| Golden responses | Repository | Changed only by review |
| The allowlist, of both kinds | Repository | Changed only by review |
| The named-comparison list | Repository, and this document's §3.10 | Changed only by review |
| Differential reports | Git-ignored output | Per run |
| Ignored-parameter reports | Git-ignored output | Per run |
| Throwaway accounts a run creates | The reference server, briefly | Destroyed by the run that made them, including on failure |

## 5. Acceptance criteria

1. The fixture library builds deterministically: two builds produce byte-identical media files.
2. Both servers, pointed at the same built fixture, produce libraries with the same item count and
   the same structure. *(**Blocked**, and recorded as such in §3.1: it needs a reference instance
   the project may configure, and the only reachable reference is an operator's own server.)*
3. The differential covers every endpoint in `surface.yaml`, with at least one request case each,
   and reports its coverage.
4. A deliberately introduced defect — a renamed field, a changed type, an omitted field — is caught,
   and classified into the right pass.
5. The report ranks missing keys first.
6. An allowlist entry without a corresponding behaviours.md reference fails the run.
7. Every probe prints a citation in the documented form and exits non-zero when its finding
   contradicts the documentation.
8. A probe whose finding contradicts the documentation produces a message naming the document and
   section to update.
9. Every prior-measurement debt in reference-target.md has a probe script, or a recorded reason it
   cannot have one.
10. The ignored-parameter report lists parameter, endpoint, count and client.
11. The default CI job passes with no Jellyfin available and no network access.
12. The version-bump command refuses to advance past a failed step.
13. No fixture file is a copyrighted work.
14. **A run states the identities it authenticated as, and its coverage line is per identity.** A
    single-identity run is reported as covering one identity, not as covering the surface.
15. **The restricted identity is created and destroyed by the run**, and a run that finds one
    already present refuses to start rather than reusing it.
16. **Every §3.10 named comparison is either run or reported outstanding**, by name, in the same
    report. An outstanding one blocks the run from being called clean (§3.4).
17. **An excused array is excused as an array**: its rows are not value-compared, and its key sets,
    types, envelope and row count still are.
18. **A response whose ordering is not total is compared as a multiset**, and a difference in row
    order alone is not reported as a difference.

## 6. Conformance

This feature is the thing that proves conformance, so it is proven by **mutation**: the harness is
correct if it catches defects that are injected on purpose.

| Property | How it is proven |
|---|---|
| Catches missing keys | Inject a removed field; assert it is reported in the key-set pass |
| Catches type changes | Inject an integer-as-string; assert the type pass |
| Catches value changes | Inject a changed title; assert the value pass |
| Does not cry wolf | Run against itself; assert zero differences outside the allowlist |
| Allowlist discipline | Add an unbacked entry; assert the run fails (AC-6) |
| Probe self-checking | Contradict a probe's expectation; assert non-zero exit (AC-7) |
| Excuses an array without excusing its shape | Remove a key from a row of an excused array; assert it is still reported (AC-17) |
| Reports what it did not ask | Run with one identity and an unrun named comparison; assert the run is not clean (AC-14, AC-16) |

**"Does not cry wolf" is not a formality.** A harness with false positives gets ignored within a
week, and an ignored harness is worse than none — it provides the feeling of coverage without the
coverage.

**It is also the reason the two mutation rows above were added.** The three excused arrays and the
random `ChildCount` are false positives on every single run, on endpoints a client uses constantly;
a harness that reports them is one nobody reads by the second week.

## 7. Open questions

All four questions this document was written with are answered. None survived unchanged.

### Resolved

| # | Question | Answer |
|---|---|---|
| OQ-1 | How to make both servers derive the same library from one fixture, given different identifier derivations | **The premise holds and the remedy does not.** Comparison by path was the proposed way out, and the path is not on the wire: 0 of 1000 default list rows carry one, so a run that joins on it is comparing a request no client sends. Asked for by name it covers the file-backed items only — a virtual season and a remote channel carry none — and every by-name row's path names *the reference installation's own data directory*. `(Type, Name)` is not a key either: 976 distinct of 1000. **Rows are therefore compared by position** (§3.2), which promotes the ordering into the contract and pulls in behaviours §3.6. `[probe: tools/probe_differential_join.py, Jellyfin 10.11.11, 2026-09-01]` |
| OQ-2 | How many request cases per endpoint are enough | **Not a question about the reference, and its measured input is 764.** That is the number of query parameters the pinned document declares across the 59 endpoints of the surface `[spec: the query parameters declared for the 59 operations of surface.yaml]`, so "one case per parameter class" is a three-figure number and "at least one each" (AC-3) is 59. What settles the floor is not a count but a demonstration: the two differences this gate found on an implemented endpoint are both invisible to a bare request — one appears only when `limit` is sent, and only for one seed type. **One case per endpoint is measurably not enough**; the growth rule of AC-3 stands, seeded by the cases the analysed clients actually send. |
| OQ-3 | Can the differential run against a recorded session instead of a live one? | **Yes for the bodies, no for the feature.** 16 of 19 reads of the surface answered byte-identical bodies on three identical requests, and the only header values that moved are the response time and the clock — so a recording is faithful enough to replay. But a recording answers only the requests it recorded, and the defect class L3 exists to find is *the field nobody thought to ask for*; a request nobody thought to record cannot find it. It also cannot carry a write: the playlist routes change what the next read reports, and one of them disagrees with itself (behaviours §3.18). **A recorded session is a regression net for CI, never the gate on a version bump.** `[probe: tools/probe_reference_determinism.py, Jellyfin 10.11.11, 2026-09-01]` |
| OQ-4 | What to do when Jellyfin's own response is non-deterministic (`Random`, `Similar`) | **Compare by shape — and the two endpoints are three.** `/UserViews` answers a fresh random `ChildCount` between 1 and 9 on every request, on every view, with the row order and every other property unchanged: the reference declines to count a top-level folder and substitutes a number so that clients "won't think the folders are empty" `[source: Emby.Server.Implementations/Dto/DtoService.cs:516-526 @ v10.11.11]`, reached because that route asks for every field `[source: Jellyfin.Api/Controllers/UserViewsController.cs:89 @ v10.11.11]`. And the mechanism §3.3 proposed does not fit: excusing a *field* cannot excuse `Similar`, whose whole array is redrawn — four identical requests returned 48 distinct items with **none** in common. §3.3 now carries two kinds of entry. `[probe: tools/probe_reference_determinism.py and tools/probe_similar_ranking.py, Jellyfin 10.11.11, 2026-09-01]` |

### Raised by the gate, and owned elsewhere

Two differences against an **implemented** feature, found by hand while answering OQ-4. Neither is
this feature's to decide (§2): both are 005's, through
[behaviours §3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made).

| # | What was measured | The decision that is owed |
|---|---|---|
| G-1 | **`/Items/{itemId}/Similar` is not a ranking.** The reference filters on the seed's own genres and tags and orders the result at random `[source: Jellyfin.Api/Controllers/LibraryController.cs:790-801 @ v10.11.11]`; four identical requests shared no item. 005 §3.7 chose determinism deliberately and argued it costs nothing under Principle I — that argument is now standing on a measurement rather than on "not obviously so" | Whether the divergence gets its own behaviours.md entry, now that it is measured rather than assumed |
| G-2 | **`limit` is not a maximum on a movie seed.** `limit=N` answers **N + 4** rows — measured at 1, 5 and 20, on two seeds — where a series, an album and an artist seed answer exactly N. The reference adds four to any limited query that groups by metadata key `[source: Jellyfin.Server.Implementations/Item/BaseItemRepository.cs:1427-1429 @ v10.11.11]` and this route sets that flag for the movie case alone `[source: Jellyfin.Api/Controllers/LibraryController.cs:795 @ v10.11.11]`; nothing de-duplicates afterwards. The reference's `TotalRecordCount` is the number of rows it returned; Atrium's is the size of the pool before the limit | Replicate the four, or diverge with the argument — and the same question for `TotalRecordCount`. Both are observable by a client that counts what it asked for. `[probe: tools/probe_similar_ranking.py, Jellyfin 10.11.11, 2026-09-01]` |

### Still open

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-5 | Whether a reference instance this project may configure and discard can exist | AC-2, and every §3.10 row that needs a planted file or an empty library | An infrastructure decision, recorded in the roadmap rather than improvised by a run |

## 8. References

- [docs/compatibility/conformance.md](../../docs/compatibility/conformance.md) — the four levels
- [docs/compatibility/reference-target.md](../../docs/compatibility/reference-target.md) — the prior-measurement debts
- [docs/constitution.md](../../docs/constitution.md) — Principles II, VII and VIII
- [specs/005 §3.3](../005-item-query-api/spec.md) — the ignored-parameter delta this feature closes
- The six lists this feature collects: [005](../005-item-query-api/tasks.md#what-this-feature-owes-the-next-ones),
  [006](../006-images/tasks.md#what-this-feature-owes-the-next-ones),
  [007](../007-user-data-and-playstate/tasks.md#what-this-feature-owes-the-next-ones),
  [008](../008-playback-negotiation-and-delivery/tasks.md#what-this-feature-owes-the-next-ones),
  [009](../009-playlists/tasks.md#what-this-feature-owes-the-next-ones) and
  [011](../011-subtitle-delivery/tasks.md#what-this-feature-owes-the-next-ones)
