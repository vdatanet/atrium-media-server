---
feature: 003-library-configuration-and-scanning
title: Library configuration and scanning — tasks
status: Draft
created: 2026-08-26
updated: 2026-08-26
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 003 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries one structural decision.** The scanner is built **additive-only** at T14 —
it can add and update but has no code path that removes anything. Removal arrives at T16, *after*
the safety guards and their destructive tests are green at T15.

That is not a suggestion about test discipline. It means that for the whole middle of this feature,
**the scanner is incapable of destroying a library**, and the capability is only granted once the
thing that constrains it exists. Everything else here fails visibly; this one fails quietly and
irreversibly.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — The fixture library generator

- [ ] **Changes:** `tests/fixtures/library/` holding directory trees and `.nfo` sidecars; a
  generator producing synthetic media at build time — a second of colour bars or a tone, muxed into
  each container the tests need.
- **Depends on:** 001 complete
- **Verified by:** two builds produce **byte-identical** files; the tree covers the awkward cases of
  [spec §5](spec.md#5-acceptance-criteria); **no file is a copyrighted work**, asserted by the
  generator being the only source of media.
- **Note:** first because almost every later task needs it, and because determinism here is what
  lets a difference in a scan result mean a difference in the scanner.
- **Plan reference:** §8.1

## T2 — `domain/items.py`

- [ ] **Changes:** the item model and its types, with no I/O of any kind.
- **Depends on:** 001 complete
- **Verified by:** an import-direction test — `domain/` imports nothing from `library/`, `db/` or
  `api/`.
- **Plan reference:** §3, architecture §1

## T3 — `domain/sorting.py`: both derivations

- [ ] **Changes:** the base six-step derivation and the three type overrides.
- **Depends on:** T2
- **Verified by:** the fifteen measured rows of
  [spec §3.7.1](spec.md#371-the-base-derivation), **including the whitespace artefacts** —
  `Rock & Roll` → `rock␣␣roll` and `S.W.A.T.` → `s␣w␣a␣t␣`; plus the three override formulas, with
  the asymmetric episode widths.
- **Note:** those two artefact rows exist to **fail when someone tidies the function**, which is the
  natural thing to do and which silently reorders every name containing a removed character. The
  test says so in a comment, or it will be deleted as an obvious bug.
- **Plan reference:** §6.2, §9

## T4 — `library/identity.py`

- [ ] **Changes:** the NUL-separated, relative-path derivation; path normalisation; the
  `case_sensitive_identity` flag.
- **Depends on:** T2
- **Verified by:** 32 lowercase hex; deterministic across processes; type-separated (the same path
  as two types gives two ids); NFC and separator normalisation; a collision aborts rather than
  merging.
- **Plan reference:** §6.3

## T5 — Migration `0002_library_and_items`

- [ ] **Changes:** `libraries` and roots; `items` with `relative_path`, `sort_name` and
  `removed_at`; `item_user_data` keyed on the derived identity **with no foreign key to `items`**.
- **Depends on:** 002 T3
- **Verified by:** up and down; the indexes 005 will need exist; **deleting an item row leaves its
  user data intact** — asserted directly, because a cascade added later would silently break
  [spec §3.8](spec.md#38-scanning-and-change-detection) and nothing else would notice.
- **Plan reference:** §4

## T6 — `library/config.py`

- [ ] **Changes:** libraries, roots, collection types; the `case_sensitive_identity` flag frozen at
  creation.
- **Depends on:** T5
- **Verified by:** an attempt to change the flag on an existing library is **refused**, not accepted
  with a warning — flipping it rewrites every identifier in that library.
- **Plan reference:** §6.3

## T7 — `library/walker.py`

- [ ] **Changes:** traversal, extension filtering, the ignore rules, and detection of files still
  being written.
- **Depends on:** T6
- **Verified by:** hidden files, `.ignore` directories, zero-byte files and trailer/sample suffixes
  are all skipped; a file whose size changes between two passes is skipped **this** scan and picked
  up the next.
- **Plan reference:** [spec §3.2](spec.md#32-what-is-considered-a-media-file)

## T8 — The naming corpus and its harness

- [ ] **Changes:** `tests/corpus/naming.yaml` — rows of path, collection type and expected
  resolution, **each with a one-line reason it exists**; the table-driven harness.
- **Depends on:** T2
- **Verified by:** the harness runs and **every row fails**, because no parser exists yet. That is
  the expected state and it is what makes the corpus the specification rather than a description of
  whatever the code happens to do.
- **Note:** rows are added when a case is met and **never removed because a pattern fails**. A
  failing row is either a bug or a corpus error, and telling them apart is the work.
- **Plan reference:** §6.1

## T9 — `library/naming/clean.py`

- [ ] **Changes:** title and year extraction; release-tag stripping.
- **Depends on:** T8
- **Verified by:** the corpus rows tagged `clean` pass. Written from the rules, not transcribed
  from the reference's expressions — Principle IV.
- **Plan reference:** §1, §6.1

## T10 — `library/naming/movies.py`

- [ ] **Changes:** bare file, folder-per-film, and multi-part grouping.
- **Depends on:** T9
- **Verified by:** the `movies` corpus rows pass, including **a multi-part film resolving to one
  item with two sources, not two items** — the most visible possible scanning bug, since it doubles
  a user's library.
- **Plan reference:** [spec §3.3](spec.md#33-movies)

## T11 — `library/naming/series.py`

- [ ] **Changes:** season and episode extraction across the naming conventions, including
  date-based; multi-episode files; specials; extras.
- **Depends on:** T9
- **Verified by:** the `series` corpus rows pass, including `S01E02-E03` as **one** item spanning
  two numbers, `Specials` as season 0, and **a series named `24` keeping its title**. The last one
  is where naive scanners fail: the pattern is matched against the filename first, then the parent
  directory.
- **Plan reference:** [spec §3.4](spec.md#34-series-seasons-and-episodes)

## T12 — `library/naming/music.py` and the metadata seam

- [ ] **Changes:** path-based structure; the `MetadataSource` protocol 004 will implement, with a
  path-only implementation for now.
- **Depends on:** T9
- **Verified by:** the `music` corpus rows pass, including a two-disc album as one album and **a
  compilation with a different artist per track as one album**; the seam is exercised by a stub
  returning tags, proving 004 can override the path without 003 changing.
- **Plan reference:** §5, [spec §3.5](spec.md#35-music)

## T13 — `library/resolver.py`

- [ ] **Changes:** path → resolved item with parent-child structure, dispatched by collection type.
- **Depends on:** T10, T11, T12
- **Verified by:** the full corpus passes; a file under a `music` root is never resolved as a movie
  regardless of its name.
- **Plan reference:** §3

## T14 — `library/scan.py`, **additive only**

- [ ] **Changes:** walk, resolve, diff, write — with **no removal code path at all**. Writes batched
  into one transaction per library.
- **Depends on:** T7, T13
- **Verified by:** AC-1 — the fixture scans to the expected item set; AC-2 and AC-3 — rescan and
  scan-into-empty give byte-identical ids; a large synthetic tree completes in a time that makes the
  batching decision visible.
- **Note:** deliberately incapable of deleting anything. T16 grants that, after T15 constrains it.
- **Plan reference:** §6.7

## T15 — The safety guards and the destructive tests

- [ ] **Changes:** the three guards of [plan §6.5](plan.md#65-the-guard-against-a-mass-delete) —
  root readable and a directory; a root that previously yielded files and now yields none aborts;
  removal beyond a configured proportion stops and reports.
- **Depends on:** T14
- **Verified by:** **AC-12** and the two beyond it — an unreadable root removes nothing, a root that
  mounts empty removes nothing, and a scan that would remove a third of a library stops. Each
  asserted against the database, not against a log line.
- **Note:** guard 2 is the one that matters. An unmounted share and an emptied directory are
  indistinguishable by a readability check.
- **Plan reference:** §6.5, §8.3, §9

## T16 — Removal and soft deletion

- [ ] **Changes:** `removed_at` on a missing file; revival on return; the maintenance action that
  purges, which a scan never does.
- **Depends on:** **T15 green**
- **Verified by:** **AC-11** — delete a file, rescan, the item disappears from queries and its user
  data survives; restore the file and the item revives **with the same id**.
- **Note:** this task is what grants the scanner the ability to remove. It does not start before
  T15 passes.
- **Plan reference:** §6.6

## T17 — Change detection

- [ ] **Changes:** the `(size, mtime_ns)` signal and a `--deep` mode that ignores it.
- **Depends on:** T16
- **Verified by:** a modified file is re-examined and **keeps its identity and user data**; an
  unchanged file is skipped; `--deep` re-examines everything.
- **Note:** mtime is not trustworthy on every filesystem. The default is fast, the escape hatch
  exists, and neither pretends to be the other.
- **Plan reference:** §6.4

## T18 — The root-move test

- [ ] **Changes:** `tests/library/test_root_move.py`.
- **Depends on:** T17
- **Verified by:** **AC-10** — scan at one path, move the whole tree, reconfigure the root, rescan:
  every identifier unchanged and no user data orphaned.
- **Note:** this is the test that proves the relative-path decision, and it fails loudly against an
  absolute-path derivation. It is the difference between a remount costing nothing and costing every
  client's favourites.
- **Plan reference:** §1, §8.2

## T19 — Scan reporting

- [ ] **Changes:** progress and a summary — added, updated, removed, and files skipped **with the
  reason**.
- **Depends on:** T16
- **Verified by:** a scan over a fixture containing an unreadable file and an unparseable name
  reports both, each with its reason, and neither aborts the scan.
- **Plan reference:** §3, §7

---

## Definition of done

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing
      test — all thirteen, by name.
- [ ] The naming corpus passes in full, and every row states the reason it exists.
- [ ] The three destructive-failure tests pass, and each fails when its guard is removed.
- [ ] Scanning twice, and scanning into an empty database, produce byte-identical identifiers.
- [ ] Moving a library root changes no identifier.
- [ ] No fixture file is a copyrighted work.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same change.
- [ ] Any newly measured reference behaviour is in `docs/compatibility/behaviours.md` with
      provenance — 003 OQ-6 in particular, once the override formulas are checked against a real
      library.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

004 needs the `MetadataSource` seam to be genuinely substitutable, or music identification lands as
a rewrite rather than an implementation. 005 needs `sort_name` indexed and library visibility
joinable. 008 needs somewhere to record that a file wants probing without 003 probing it. All three
are cheap here and expensive later.
