---
feature: 003-library-configuration-and-scanning
title: Library configuration and scanning — implementation plan
status: Implemented
created: 2026-08-26
updated: 2026-08-27
amended: 2026-08-27 by T3 - section 4; by T5 - sections 5 and 6.3; by T18 - sections 5 and 6.4; by T19 - section 1; by T20 - sections 3 and 7
spec_status_required: Accepted
spec_status_actual: Implemented
accepted: 2026-08-26
implemented: 2026-08-27
---

# 003 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour.

## 1. Approach

003 has no HTTP surface, which makes it the one feature that can be built and proven entirely
against fixtures — and the one whose mistakes are least visible until 005 exposes them.

Four decisions carry it.

**Principle IV bites hardest here, and the answer is a corpus.** The reference's naming rules live
in a large table of regular expressions. Copying it is a licence problem and a design problem at
once, and reimplementing it from memory is guesswork. So the source of truth for naming becomes
**a checked-in corpus of `path → expected resolution` rows** — our own artefact, written from
observed conventions and from what the reference produces for each case. The patterns are then
whatever makes the corpus pass. This inverts the usual relationship: the tests are the
specification of the behaviour, and the implementation is free.

**Identity is derived, and derived from a *relative* path.** The reference derives item ids from
the absolute path — **measured**, not inferred: recomputing the documented expression from each
item's own reported path reproduced 448 of 448 live ids across five types, containers included
`[probe: tools/probe_item_identity.py, Jellyfin 10.11.11, 2026-08-27]`. So moving a library from
`/mnt/a` to `/mnt/b` — or running the same library from a container with a different mount point —
changes every id there and silently discards every client's favourites and resume positions.
Atrium derives from the path **relative to its library root**, so that move costs nothing, and
§8.2's test is what holds it. The ids differ from the reference's either way
([behaviours §1.4](../../docs/compatibility/behaviours.md#14-item-identifiers-are-32-lowercase-hex-characters)),
so there is no compatibility cost to being better here.

**A scan must be unable to mistake an unavailable root for an empty one.** This is the single most
destructive thing a scanner can do, and "check the root is readable" is not enough: a network share
can mount empty. §6.5 makes it a guard with a threshold rather than a check.

**Sort names are now fully specified**, from the probe run on 2026-08-26 — two derivations, three
item types bypassing the first
([spec §3.7](spec.md#37-sort-names)). The plan's job is to make the whitespace artefacts survive
contact with a tidy-minded implementer, which it does by testing for them explicitly.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001 and 002 | [001 plan §2](../001-server-identity-and-discovery/plan.md#2-inherited-decisions), [002 plan §2](../002-authentication-users-and-sessions/plan.md#2-inherited-decisions) |
| SQLite, repositories returning domain objects | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |
| Identifiers are derived, never allocated | [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions) |
| Ticks are the internal duration unit | [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions) |
| `domain/` performs no I/O | [architecture §1](../../docs/architecture.md#1-shape-of-the-system) |

**Deviations:** none.

## 3. Modules

```
src/atrium/
├── domain/
│   ├── items.py          BaseItem and its types — no I/O
│   ├── library.py        what an operator configured: a name, some roots, a collection type
│   └── sorting.py        both sort-name derivations
├── library/
│   ├── config.py         library roots and collection types
│   ├── walker.py         filesystem traversal, filtering, ignore rules
│   ├── naming/
│   │   ├── movies.py
│   │   ├── series.py
│   │   ├── music.py
│   │   └── clean.py      title and year extraction, release-tag stripping
│   ├── resolver.py       path -> resolved item, per collection type
│   ├── identity.py       the derivation
│   ├── scan.py           orchestration, change detection, the safety guard
│   ├── maintenance.py    the one operation that actually deletes, kept where a scan cannot reach it
│   └── report.py         progress, and the summary's three categories (§7)
└── db/
    └── migrations/       revision 0002: items, libraries, user data
```

`library/naming/` is pure: paths in, structured results out, no filesystem access. That is what
makes the corpus runnable as a plain table test with no fixtures on disk at all.

`domain/library.py` (T7) and `library/maintenance.py` (T17) postdate the accepted tree, and no
plan drew either until the 2026-08-28 audit (M12 and M13 in
[the record](../../docs/audits/2026-08-28.md)).

## 4. Data model

Revision `0002_library_and_items`.

**`libraries`** — id, name, collection type, and a `case_sensitive_identity` flag frozen at
creation (§6.3). Roots live in a child table, since a library can have several.

**`items`** — the single table behind every type
([glossary](../../docs/glossary.md)):

| Column | Notes |
|---|---|
| `id` | Derived, 32-hex, primary key |
| `library_id`, `parent_id` | |
| `type` | `Movie`, `Series`, `Season`, `Episode`, `MusicArtist`, `MusicAlbum`, `Audio`, `CollectionFolder` |
| `name`, `sort_name` | `sort_name` is indexed; it is the ordering key for nearly every query |
| `index_number`, `parent_index_number` | Episode and track numbers, disc and season numbers |
| `end_index_number` | Nullable. The last number a multi-episode file spans — see below |
| `date_created`, `date_modified` | |
| `removed_at` | Nullable. **Items are soft-deleted** (§6.6) |

**`item_sources`** — the file or files behind an item: `item_id`, `part_index`, `relative_path`,
`size`, `mtime_ns`. Ordered by `part_index`, and the item's identity is derived from part zero's
path.

This table and `end_index_number` are both **corrections made at T3**, and they are the same
mistake twice: this section described the item table as though every item had at most one file and
occupied at most one number, and two acceptance criteria say otherwise.

- A `relative_path` column on `items` cannot hold a **two-part film**, which AC-4 and
  [spec §3.3](spec.md#33-movies) require to be *one* `Movie` with two media sources. Nothing in this plan mentioned a
  media source at all; T6 would have written the migration as specified and T11 would have found
  there was nowhere to put part two.
- `index_number` alone cannot hold `S01E02-E03`, which AC-5 requires to be **one** episode
  spanning both numbers rather than two items.

Moving `size` and `mtime_ns` onto the source rather than the item is the same correction
continued: §6.4's change detection must notice a change to *either* part, and a film whose second
part was replaced and whose first was not has changed. It also removes a nullability that would
otherwise be everywhere — a `Series` has no path, and under this shape it simply has no sources.

Indexes are chosen for the queries 005 actually issues: `(library_id, type, sort_name)`,
`(parent_id, index_number)`, a unique index on `id`, and `(item_id, part_index)` on the sources. A
column exists to serve a query pattern or a fact; the ones above that are pattern-driven are marked
as such in the migration's docstring, because a later reader will otherwise try to normalise them
away.

**`item_user_data`** — keyed `(user_id, item_key)` where `item_key` is the derived identity, and
**with no foreign key to `items`**. This is deliberate and it is what makes
[spec §3.8](spec.md#38-scanning-and-change-detection)'s "user data outlives items" true rather than
aspirational: a cascade would delete a user's history the first time a network share was slow to
mount. 007 owns the table's contents; 003 owns the guarantee that it survives.

## 5. Contracts

**`library.naming`** — one function per media type, pure:

```python
def parse_movie(relative_path: str) -> MovieParse: ...
def parse_episode(relative_path: str) -> EpisodeParse: ...
def parse_audio(relative_path: str, source: MetadataSource = PATH_ONLY) -> AudioParse: ...
```

Each returns a structured result with everything the path can tell us and `None` where it cannot.
No exceptions for unparseable input: an unrecognised name is a result with a title and nothing else,
which is what the reference produces too.

**`library.identity`** — one function per identity *rule*, not one function. §6.3 describes the
hashing, and [spec §3.6](spec.md#36-identity) describes four different keys going into it:

```python
def for_file(item_type, library_id, relative_path, *, case_sensitive=False) -> str: ...
def for_name(item_type, library_id, name, *, case_sensitive=False) -> str: ...
def for_season(series_id, season_number) -> str: ...
def for_library(library_id) -> str: ...
```

**Corrected at T5.** This section previously named a single
`derive(item_type, library_id, relative_path)`, which is the rule for a `Movie`, an `Episode` and
an `Audio` and is wrong for the other five types: a `Season`'s key is its series' identity plus a
number, a `Series`, `MusicAlbum` or `MusicArtist` takes its library plus a normalised name, and a
`CollectionFolder` takes the library alone. Passing a series identity as the `relative_path`
argument would have satisfied the signature and produced a perfectly valid identifier for the wrong
thing. Each function now refuses a type belonging to another rule, and `RULE_OF` maps every type to
exactly one.

The hashing itself is **not** in `library/`: `atrium.compat.guids.derive` has done the NUL-joined,
truncated SHA-256 since 001, and 003 is the first caller its docstring anticipated.

**`domain.sorting.sort_name(item, *, forced=None, rules=DEFAULT_RULES) -> str`** — dispatches on
type, §6.2; `forced` is 004's explicit sort title (spec §3.7.3), `rules` the configured
derivation rules.

**`library.scan.scan(library, session, roots=None, source=None, *, deep=False, ...)
-> ScanReport`** — the orchestrator. The only thing in the feature that writes. *(The accepted
plan defaulted `source=PATH_ONLY`; the code's default is `None`, which means **read the files**,
because the quiet default failed silently — the correction the code has carried in a comment
since, brought back into this line at the 2026-08-28 audit, M20 in
[the record](../../docs/audits/2026-08-28.md). `PATH_ONLY` is still passable.)*

**Corrected at T18.** This section named a `mode` argument, which reads like a set of scanning
modes and is one boolean: `deep` decides whether the §6.4 signal is consulted, and nothing else
about a scan varies. `confirm_removals` and `removal_threshold` arrived at T16 as the guards' own
arguments rather than as values of a `mode`, and a single enumeration would have had to carry all
three combinations. The name `--deep` in the task list is what an operator eventually types; the
feature has no command line, so nothing here parses one.

**`MetadataSource`** — the seam for 004. 003 needs embedded tags to identify music
([spec §3.5](spec.md#35-music)) and 004 provides them. 003 defines the protocol and ships a
path-only implementation; 004 supplies the real one without 003 changing.

## 6. Algorithms

### 6.1 The naming corpus

`tests/corpus/naming.yaml`: rows of `path`, `collection_type`, and the expected resolution. Several
hundred rows, grouped by the convention they exercise, each with a one-line note saying **why** it
is there — a row without a reason is a row nobody dares delete when it becomes wrong.

The corpus covers what [spec §3.3](spec.md#33-movies) to §3.5 describe, and specifically the cases
that break naive scanners: multi-part films, `S01E02-E03`, `Specials`, a series named `24`,
date-based episodes, multi-disc albums, compilations, non-ASCII names, and names differing only by
case.

**Rows are added when a case is met, never removed because a pattern fails.** A failing row is
either a bug or a corpus error, and telling them apart is the work.

### 6.2 Sort names

Two functions, dispatched by type, exactly as
[spec §3.7](spec.md#37-sort-names) specifies.

The base derivation runs its six steps in order. **Nothing trims or collapses whitespace**, and the
table test asserts `Rock & Roll` → `rock␣␣roll` and `S.W.A.T.` → `s␣w␣a␣t␣` with the artefacts
intact. Those two rows exist to fail loudly when someone tidies the function, because tidying it is
the natural thing to do and it silently reorders every name containing a removed character.

`Audio`, `Episode` and `Season` take the override: a zero-padded numeric prefix and the **raw**
name. The widths are asymmetric — season 3, episode 4 — and a comment says so beside the constant,
since it reads like a typo.

### 6.3 Identity

```python
key = b"\0".join(x.encode("utf-8") for x in (item_type, library_id, relative_path))
item_id = sha256(key).digest()[:16].hex()          # 32 lowercase hex
```

Separated by a NUL so no concatenation collides, truncated to 16 bytes for the 32-character shape
clients expect. The path is normalised — separators, Unicode NFC — and lowercased when the
library's `case_sensitive_identity` flag is unset, which is the default and matches the reference's.

**The flag is frozen at library creation and cannot be changed in place**, because flipping it
rewrites every identifier in that library. Changing it means creating a new library, and the code
refuses the edit rather than accepting it and warning.

### 6.4 Change detection

The cheap signal is `(size, mtime_ns)`. Hashing every file on every scan is not viable for a library
of any size.

**mtime is not trustworthy everywhere** — some network filesystems round it, some restore it on
copy. So: a changed `(size, mtime_ns)` always means re-examine; an unchanged pair means skip *by
default*, and a `deep` mode ignores the pair and re-examines everything. The default is fast, the
escape hatch exists, and neither pretends to be the other.

**"Restore it on copy" is not a worry about exotic filesystems, it is the ordinary case.** `cp -p`,
`rsync -a` and an unpacked archive all put the modification time back, and a tag editor rewriting a
header in place can leave the size alone. Measured on an ordinary local filesystem: writing new
bytes of the same length and restoring the time yields a byte-for-byte identical signal —
measured on macOS APFS on 2026-08-27, and reproduced by `tests/library/test_change_detection.py`,
which is the right citation for a local-filesystem fact: the `[probe:]` form names measurements of
the reference. That is what `deep` is for.

**What "examine" means here is exactly one thing: asking the §5 metadata seam what is embedded in
the file.** Everything else a scan does reads paths, which is free. So the signal gates
`MetadataSource.tags_for` and nothing else — which is also why the skip is *safe*: no file-backed
identity depends on a tag, so an unexamined file resolves to the same identifier it did last time.

**Skipping the read is therefore not enough on its own, and this is the trap.** An unexamined music
file resolved from its path alone hangs from an album named after its *directory* — for the 413 of
5,814 measured tracks whose tags disagree with their path, a different album from the one it is
really in. Two steps, not one:

1. **Keep the stored row** for a file whose whole source tuple matches what is stored. The
   resolution of an unexamined file is used to find out *which row*, never written.
2. **Rebuild the item set upwards from the file-backed items** and drop any container nothing ends
   up under, so the album this scan invented is not written beside the one that is already there.

Step 2 changes nothing when no row is kept — every container the resolver produces exists because
some file asked for it — so a first scan and a `deep` scan are unaffected by it.

The signal is read across an item's **whole source tuple**, not per path, so a two-part film with
one rewritten part is re-examined as one item rather than left half-updated.

**None of this is observable to a client.** No item and no media source on the reference carries a
modification time ([behaviours §2.17](../../docs/compatibility/behaviours.md#217-no-item-and-no-media-source-carries-a-modification-time)),
so the choice of signal creates no delta. `Size` *is* observable, which is why an examined file's
size is always written back — and why a new signal is written back even when nothing else about
the item changed, or every scan from then on would re-examine the same file forever.

### 6.5 The guard against a mass delete

Before any removal is applied:

1. Every root must be readable and must be a directory.
2. **A root that yields no candidate files, having previously yielded some, aborts the scan for that
   library** and removes nothing.
3. A scan that would remove more than a configured proportion of a library's items — default a
   quarter — stops and reports instead, unless explicitly confirmed.

Rule 2 is the one that matters. An unmounted share and an emptied directory are indistinguishable
by a readability check, and treating the first as the second destroys a user's library state. Rule 3
catches the slower version of the same accident: a root that is *partly* wrong.

### 6.6 Soft deletion

A file that disappears sets `removed_at`. The item stops appearing in queries, its user data stays
untouched, and if the file returns the row is revived with the same id, because the id is derived
from the path and the path has not changed.

Rows are purged only by an explicit maintenance action, never by a scan.

### 6.7 Scan orchestration

Walk, resolve, diff, write — with **writes batched into one transaction per library**, not one per
item. SQLite has a single writer and WAL keeps readers going; a per-item transaction would make a
scan of a large library take orders of magnitude longer than the walk itself.

Parallelism is I/O-shaped: the walk can use a thread pool, resolution is pure and parallel-safe, and
the write is single-threaded by construction. Media probing — the genuinely slow part — is **not**
in this feature; 008 owns it and a scan only records that it is needed.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Root unreadable or not a directory | Pre-scan check | **Abort that library**, remove nothing | Operator fixes the mount |
| Root suddenly empty | §6.5 rule 2 | **Abort that library**, remove nothing | Operator fixes the mount |
| Removal exceeds the threshold | §6.5 rule 3 | Stop, report, require confirmation | Operator confirms or investigates |
| File that cannot be **stat**ed — a dangling symlink | Per-file, during the walk | Skip, count, report with the reason | Operator fixes the link |
| Directory that cannot be **listed** | Per-directory, during the walk | Skip it and everything under it, count, report | Operator fixes permissions |
| File whose **contents** cannot be read | **Not detected here** | Scanned like any other file, because nothing in 003 opens one | 008 finds it when it goes to probe or play it |
| Unparseable name | Resolver | Item with a title and nothing else, **and a notice in the report** | 004 may identify it |
| File still being written | Size changed between passes | Skip this scan, pick it up next | Automatic |
| Two files deriving the same id | Insert conflict | **Abort**, naming both paths | A collision is a bug in §6.3, not user error |

**Corrected at T20.** This table had one row reading *"unreadable file inside a readable root →
skip, count, report"*, and it is not what happens. A `chmod 000` file **stats perfectly well**, and
stat is all the walk does — so it becomes a candidate, becomes an item, and is discovered to be
unreadable by whoever first opens it, which is 008. The two cases that *are* detectable are a file
whose stat raises (a dangling symlink) and a directory that cannot be listed. All three are held by
`tests/library/test_report.py::test_a_file_is_only_unreadable_when_it_cannot_be_stat_ed`, including
the one that is scanned, because the row that was wrong is the one an implementer would otherwise
write a check for and never see fire.

**A skipped file and a noticed one are different things, and the report keeps them apart.** A
skipped file produced **no item**; a noticed one produced a thin one that is in the library now. An
operator told "2 files skipped" when one of the two was in fact scanned goes looking for something
that is not missing. `library/report.py` holds the argument; the vocabulary for each lives with the
thing that produces it, so `Skip` is the walker's and `Notice` is the resolver's.

**Only the resolver can raise a notice**, which is not a style choice. An `Episode` with no episode
number is either a name nothing could be read from or a daily show whose episodes are dated, and an
item carries no date to tell the two apart — so a notice computed from the finished items reports
every episode of every daily show as unparseable. The first version of T20 did exactly that and the
fixture caught it.

## 8. Testing strategy

| Spec AC | Test |
|---|---|
| 1 | Fixture library scans to the expected item set for all three collection types |
| 2, 3 | Identity stability: scan, rescan, and scan into an empty database, comparing every id |
| 4, 5, 6, 7 | The naming corpus (§6.1) |
| 8, 9 | Multi-disc and compilation rows in the corpus, plus a scan assertion |
| 10 | **The root-move test** — §8.2 |
| 11 | Delete a file, rescan, assert user data survives and the item revives on return |
| 12 | Unreadable root removes nothing |
| 13 | The sort-name table, including the whitespace artefacts |

### 8.1 The fixture library

Directory trees, `.nfo` sidecars and **placeholder files generated at build time** — deterministic
bytes carrying the right extension and a non-zero size, written by us with no external tool. No
copyrighted media, and the repository stays small.

Generation is deterministic, so two builds produce byte-identical files and a difference in a scan
result is a difference in the scanner.

**They are not decodable media, and they do not need to be.** This section previously called for a
second of colour bars or a tone muxed into each container, which was a requirement inherited from
what a fixture library *usually* is rather than from what 003 does with one. Nothing in this feature
opens a media file: probing is 008 (§8.4), embedded tags are 004, and the `MetadataSource` of §5
ships path-only here. What a 003 test reads from a fixture file is its path, its extension, and a
size that changes when the test changes it — §6.4's whole change-detection signal.

Muxing would have cost two things for that nothing. It adds a tool outside the locked dependency
set, which the [CI](../../.github/workflows/ci.yml) test job does not install and would have to. And
it makes *byte-identical across two builds* — the property that lets a difference in a scan result
mean a difference in the scanner — depend on a muxer's version rather than on our own code, which
is the one place determinism must not be borrowed.

When 008 needs a decodable file it generates one there, beside the thing that decodes it.

### 8.2 The root-move test

Scan a library at one path; move the whole tree to another path; reconfigure the root; rescan.
**Every identifier is unchanged, and no user data is orphaned.** This is the test that proves the
relative-path decision of §1, and it fails loudly against an absolute-path derivation.

### 8.3 The destructive-failure tests

Three, and they are the ones worth writing first, because everything else fails visibly and these
fail quietly:

- A root made unreadable mid-life removes nothing.
- A root that mounts empty removes nothing.
- A scan that would remove a third of a library stops and reports.

### 8.4 What is not tested here

Media probing, codecs, durations and resolutions belong to 008. A 003 test asserting a duration
would be asserting something this feature does not produce.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A scan deletes a library because a share was unmounted | **Medium** | **Catastrophic and irreversible for user data** | §6.5, three independent guards, tested at §8.3 |
| Identifiers change on a path change | Medium | Every client's state discarded | Relative-path derivation, tested at §8.2 |
| Someone tidies the sort-name whitespace | **High** | Silent reordering of many lists | Explicit artefact assertions in the table test |
| The base sort rule applied to audio | High | Every album reordered | Dispatch by type, with rows for all three overriding types |
| Corpus rows deleted to make a pattern pass | Medium | Regressions in naming | Every row carries the reason it exists |
| mtime unreliable on a network share | Medium | Changes missed | `--deep` mode, documented rather than assumed away |
| Per-item transactions make scans unusable | Medium | Feature unusable at real sizes | Batched writes, measured on a large synthetic tree |
| Identity collision | Very low | Two files become one item | NUL separation; a collision aborts rather than merging |

## 10. Alternatives considered

**Port the reference's naming expressions.** Fastest route to parity and forbidden by Principle IV —
they are the implementation, not the interface. The corpus gets the same behaviour with our own
code and, unlike a copied table, it says what each rule is *for*.

**Derive identity from an absolute path, matching the reference.** Would make ids match if
everything else matched, which it will not. It buys nothing and costs every id on a remount.

**Hard-delete missing items.** Simpler schema, no `removed_at`, no orphan rows — and it makes a
temporarily unavailable file cost a user their favourites and resume position permanently.

**Hash file contents for change detection.** Correct where mtime lies, and it means reading every
byte of the library on every scan. `--deep` offers it where it is needed rather than paying for it
always.

**Watch the filesystem instead of scanning.** Lower latency, and it is a different feature with its
own failure modes: watchers miss events under load, do not survive a restart, and behave differently
on every platform and network filesystem. Out of v1 by
[roadmap](../../docs/roadmap.md); a scan is the thing that must be correct first, because a watcher
is an optimisation over a scan and never a replacement for one.

**Probe media during the scan.** It is where the information is, and it would make a first scan of a
large library take hours instead of minutes while producing nothing 003 needs. 008 probes on demand
and caches.
