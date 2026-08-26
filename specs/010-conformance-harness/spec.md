---
feature: 010-conformance-harness
title: Conformance harness
status: Draft
created: 2026-08-26
updated: 2026-08-26
depends_on: [001, 002, 003, 004, 005, 006, 007, 008, 009]
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

## 2. Scope

**In scope**

- The differential harness: same request to both servers, structural comparison, triaged report.
- The allowlist of legitimately-varying fields, and the discipline around changing it.
- The fixture library as a build artifact reproducible on both servers.
- The probe-script convention, and discharging the prior-measurement debts.
- The ignored-parameter report from 005 §3.3.
- The version-bump procedure of `conformance.md`, as an executable process.
- CI wiring: what runs always, what runs on demand.

**Out of scope**

- L0 and L1 machinery, delivered by 001 — this feature consumes them.
- Performance benchmarking. Correctness only.
- Testing Jellyfin. When a difference is Jellyfin's defect, it is recorded, not fixed here.

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

The fixture deliberately contains the cases that break naive implementations — the ones enumerated
across 003 §5, 005 §5 and 009 §5: multi-part films, `S01E02-E03`, specials, a series named `24`,
multi-disc albums, compilations, tags that contradict paths, non-ASCII names, names differing only
by case, and a playlist with duplicate entries.

### 3.2 The differential run

```
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

### 3.3 The allowlist

Fields compared by **shape** rather than by value, each with a written reason.

| Field | Why it may differ |
|---|---|
| `Id`, `ItemId`, `ServerId`, `ParentId`, `SeriesId`, `SeasonId`, `AlbumId`, … | Derivation differs by design (behaviours §1.4) |
| `DateCreated`, `DateLastSaved`, `DateLastMediaAdded`, `LastActivityDate` | Scan wall-clock time |
| `Etag`, `ImageTags.*`, `PlaySessionId`, `AccessToken` | Content hashes and generated identifiers |
| `Path` | Different mount points |
| `LocalAddress` | Deliberate divergence (behaviours §4.2) |
| `TotalRecordCount` on by-name endpoints without `limit` | Deliberate divergence (behaviours §3.1) |

**Adding an entry is a contract decision, not a way to make a red run green.** It happens in
review, the reason goes in the table, and an entry justified by "we do it differently" without a
behaviours.md entry backing it is rejected.

The allowlist is also **a metric**: it should shrink over time as derivations converge, and a run
that grows it is worth a second look.

### 3.4 The report

One document per run, and it is the deliverable — not a pass/fail line.

```
Differential run — Atrium <sha> vs Jellyfin 10.11.11 — <date>

  endpoints compared     55
  request cases          <n>
  identical              <n>
  allowlisted            <n>
  DIFFERENCES            <n>

  Missing keys        (n)    <-- read these first
  Extra keys          (n)
  Type mismatches     (n)
  Value mismatches    (n)
```

Each difference carries the endpoint, the request case, the JSON path, both values, and — where it
matches a known entry — a link to the behaviours.md section that explains it.

**Every difference is triaged into one of four outcomes**, and none of them is "ignore":

| Outcome | Meaning |
|---|---|
| **Fix** | Atrium is wrong. A defect, against the owning feature |
| **Replicate** | Jellyfin's behaviour is odd; we match it. A behaviours.md entry |
| **Diverge** | We deliberately differ. A behaviours.md entry with the argument, and an allowlist row |
| **Defer** | Out of v1 scope. Recorded with the feature that will resolve it |

An untriaged difference blocks the run from being called clean.

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
2. Run the full differential. Triage every new difference into behaviours.md.
3. Re-run every probe. Update the `Last verified` line of every document they support.
4. Only then change the pinned version.

**A bump that skips step 2 has not been done, it has been declared.** The command enforces the
order so that the shortcut is not available.

## 4. Data the feature owns

| Artefact | Where | Lifetime |
|---|---|---|
| Fixture library sources | Repository | Permanent |
| Built fixture media | Build output | Disposable, regenerable |
| Golden responses | Repository | Changed only by review |
| The allowlist | Repository | Changed only by review |
| Differential reports | Git-ignored output | Per run |
| Ignored-parameter reports | Git-ignored output | Per run |

## 5. Acceptance criteria

1. The fixture library builds deterministically: two builds produce byte-identical media files.
2. Both servers, pointed at the same built fixture, produce libraries with the same item count and
   the same structure.
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

**"Does not cry wolf" is not a formality.** A harness with false positives gets ignored within a
week, and an ignored harness is worse than none — it provides the feeling of coverage without the
coverage.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | How to make both servers derive the same library from one fixture, given different identifier derivations | AC-2; may need comparison by path rather than by id | Prototype against a real server |
| OQ-2 | How many request cases per endpoint are enough | Coverage claims in AC-3 | Start with one per parameter class; grow from what the report finds |
| OQ-3 | Can the differential run against a recorded Jellyfin session instead of a live one? | Whether L3 could ever gate default CI | Investigate after the live harness works |
| OQ-4 | What to do when Jellyfin's own response is non-deterministic (`Random`, `Similar`) | Comparison of those endpoints | Compare by shape only, and record it as an allowlist class |

## 8. References

- [docs/compatibility/conformance.md](../../docs/compatibility/conformance.md) — the four levels
- [docs/compatibility/reference-target.md](../../docs/compatibility/reference-target.md) — the prior-measurement debts
- [docs/constitution.md](../../docs/constitution.md) — Principles II, VII and VIII
- [specs/005 §3.3](../005-item-query-api/spec.md) — the ignored-parameter delta this feature closes
