---
feature: 003-library-configuration-and-scanning
title: Library configuration and scanning — tasks
status: Accepted
created: 2026-08-26
updated: 2026-08-27
accepted: 2026-08-27
started: 2026-08-27
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 003 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries one structural decision.** The scanner is built **additive-only** at T15 —
it can add and update but has no code path that removes anything. Removal arrives at T17, *after*
the safety guards and their destructive tests are green at T16.

That is not a suggestion about test discipline. It means that for the whole middle of this feature,
**the scanner is incapable of destroying a library**, and the capability is only granted once the
thing that constrains it exists. Everything else here fails visibly; this one fails quietly and
irreversibly.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md) and [`plan.md`](plan.md) on 2026-08-27 before
being accepted. Six things it asserted were wrong, and all six were found by checking the list
against files in this repository rather than by reading it:

| The draft said | It was |
|---|---|
| Start at the fixture generator | **No task measured anything.** [spec §7](spec.md#7-open-questions) names two probes as the resolvers for OQ-1 and OQ-5, and neither exists in [`tools/`](../../tools/). The extension filter and the music precedence rule were both scheduled to be built on a guess — the one mistake every feature so far has made and caught. Now T1 |
| Nineteen tasks, ending at scan reporting | **The definition of done could not be met.** `tests/conformance/test_acceptance.py::test_every_implemented_feature_has_a_map` reads the status table in [`specs/README.md`](../README.md) and fails for any feature marked `Implemented` with no map. Marking 003 done would have failed the suite. 002 had T18 for this; 003 had nothing. Now T21 |
| T8: the corpus harness lands with **every row failing** | **That pull request cannot merge.** [CI](../../.github/workflows/ci.yml) runs `uv run pytest` on every one. The intent — corpus as specification, not description — survives as `xfail(strict=True)` per row, and `strict` carries weight because `pyproject.toml` sets no `xfail_strict`: without it a row that starts passing is an `xpass` nobody sees. Now T9, which also has to add a YAML parser, since the `dev` group has none |
| T1: mux synthetic media into each container | **003 never opens a media file.** Probing is 008 ([plan §8.4](plan.md#84-what-is-not-tested-here)), and T13 ships a path-only `MetadataSource`. The task's own criterion — byte-identical across two builds — would have rested on whichever muxer version a runner image carried, and the test job installs only Python dependencies. [plan §8.1](plan.md#81-the-fixture-library) is amended in this change. Now T2 |
| AC-13 is covered by the sort-name table | **Half of it.** The table proves the two derivations; nothing proved that `scan.py` writes `sort_name` **through the type dispatcher**. That is [plan §9](plan.md#9-risks)'s one High/High risk — the base rule applied to audio reorders every album — and it lived in the gap between a unit test and a scan. Now asserted at T15 |
| T5 depends on `002 T3` | `002 T3` is Argon2id password hashing. Migration `0001_users_and_sessions` is **`002 T4`**. Now T6 |

The first two are the ones worth remembering: **both are about a task that was missing, not a task
that was wrong.** Reading a list tells you whether the steps in it are right. It does not tell you
which step is not in it.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — The two probes: measure before implementing  ✅

- [x] **Changes:** `tools/probe_library_extensions.py` (OQ-1 — which extensions the reference
  honours) and `tools/probe_music_precedence.py` (OQ-5 — what it does when embedded tags contradict
  the path). Both on the [`tools/_probe.py`](../../tools/_probe.py) skeleton; both listed in
  [`tools/README.md`](../../tools/README.md#probes); both exit non-zero when the finding contradicts
  what this repository currently claims.
- **Depends on:** nothing
- **Verified by:** both run against a live reference and their findings are recorded in
  [`spec.md`](spec.md) with `[probe: …]` provenance, and in
  [`behaviours.md`](../../docs/compatibility/behaviours.md) where a client can observe the
  difference. `python tools/probe_library_extensions.py --help` and its pair start on 3.9, which is
  the floor the `tools` CI job holds them to.
- **Note:** first because every feature so far has been taught something here that reading could not
  produce, and because **these two probes gate real decisions**: OQ-1 is the extension list T8
  filters on, OQ-5 is the precedence rule T13 implements. Building either from the conservative
  guess in [spec §3.2](spec.md#32-what-is-considered-a-media-file) means building it twice.
- **Note:** **these two need something no previous probe has needed — files placed under a library
  root on the reference**, because both questions are about what the scanner does with a file that
  is not there yet. That is a heavier ask than credentials. If it cannot be arranged, this task is
  `[!]`, OQ-1 and OQ-5 **stay open in [spec §7](spec.md#7-open-questions)**, and T8 and T13 proceed
  on the conservative union the spec already states — explicitly, and marked as such, rather than
  quietly closing a question nobody answered. The rest of the list is not blocked by it.
- **Plan reference:** [spec §3.2](spec.md#32-what-is-considered-a-media-file),
  [spec §3.5](spec.md#35-music), [tools/README.md](../../tools/README.md#probes)

### Done — 2026-08-27

**The obstacle this task was hedged against did not exist.** Both notes above say the probes need
files placed under a library root on the reference — "a heavier ask than credentials" — and set out
what to do when that could not be arranged. Neither probe writes anything. `/Environment/…` exposes
a **read-only view of the server's filesystem**, which is the half the task thought was missing:
census what the server admitted from its item list, census what is on disk through that view, and
the difference is what it walked past. OQ-5 needed even less — the library it already has contains
5,814 tracks, and 413 of them disagree with their own directory.

The lesson is not that the guess was pessimistic. It is that **the task predicted a blocker instead
of spending ten minutes finding out**, and the ten minutes would have produced a better plan for
both probes, not just a cheaper one.

**The real blocker was the harness, and it looked exactly like a server fault.** The probe died on
`CERTIFICATE_VERIFY_FAILED` against a server `curl` reached fine. The reference is healthy and its
certificate is publicly valid; the Python that runs the probes ships **no CA bundle at all** —
`ssl.create_default_context().get_ca_certs()` returns zero. `/etc/ssl/cert.pem` is not a fix
either: it lacks roots the keychain supplies to `curl`. Recorded in
[tools/README.md](../../tools/README.md), because the next person will read that error as "the
server is down".

**`Server.get()` cannot send a query parameter named `path`** — Python binds it to the positional
argument and raises. `/Environment/DirectoryContents`, the only read-only filesystem view there is,
takes exactly `path`. `_probe.py` gains `get_where(path, params)` and a comment naming the other
five names with the same problem.

**Censusing extensions from item paths naively produces nonsense**, and it is the kind of nonsense
that looks like data. Container items — `Series`, `Season`, `MusicAlbum`, `MusicArtist`, `BoxSet` —
carry a **directory** path, and directory names are full of full stops, so a census over all types
returned 25 confident rows including `.1-castellano+subs]`, `. rex` and `. bean`. Leaf types only,
and the constant says why so nobody widens it back.

**The finding neither document had:** under `movies` and `tvshows` roots, 89 `.mp3` and 3 `.mka`
files produced **no item of any type** — not a film, not an episode, and not a track either, on a
server that admits three audio extensions under its music root. The extension lists do not fall
back to one another. A scanner that admitted every audio extension everywhere would invent items
the reference does not have, which is a delta in the direction nothing tests for.
[behaviours §2.15](../../docs/compatibility/behaviours.md#215-an-audio-file-under-a-video-root-is-not-an-item),
[spec §3.2](spec.md#32-what-is-considered-a-media-file), [spec §3.5](spec.md#35-music), and OQ-1
and OQ-5 are in the resolved table of [spec §7](spec.md#7-open-questions).

**What is measured and what is not** is stated in both probes and in the spec, because the honest
version of this finding is narrower than the useful-sounding one: these are the extensions *one
real library contained*. An extension nobody has a file of was not measured. The same applies to
OQ-5 — every album on that server lives in one directory, so a genuinely flat, well-tagged
structure remains unproven and [spec §3.5](spec.md#35-music) says so.

## T2 — The fixture library generator  ✅

- [x] **Changes:** `tests/fixtures/library/` holding directory trees and `.nfo` sidecars; a
  generator producing the files at build time — **deterministic placeholder bytes with the right
  extension and a non-zero size**, no external muxer.
- **Depends on:** 001 complete
- **Verified by:** two builds produce **byte-identical** files; the tree covers the awkward cases of
  [spec §5](spec.md#5-acceptance-criteria); **no file is a copyrighted work**, asserted by the
  generator being the only source of media; the generator needs nothing outside the locked
  dependency set, asserted by the test job installing nothing else.
- **Note:** the draft called for a second of colour bars or a tone muxed into each container.
  **Nothing in 003 opens these files.** Probing is 008
  ([plan §8.4](plan.md#84-what-is-not-tested-here)), music tags are 004, and T13 ships a path-only
  `MetadataSource`. What the tests need from a fixture
  file is its path, its extension, and a size that changes when they change it — which is exactly
  what T8's walker reads. A muxer would have added a dependency this feature has no use for and made
  "byte-identical across two builds" depend on its version rather than on ours.
- **Note:** when 008 needs a decodable file, it generates one **there**, where something decodes it.
- **Plan reference:** §8.1

### Done — 2026-08-27

**The determinism hazard was the clock, not the bytes.** This task's verification line asks for
files that are byte-identical across two builds, and that part was never in doubt: content derived
from a path is deterministic by construction. What would actually have made scans irreproducible is
**`mtime`** — [plan §6.4](plan.md#64-change-detection) makes `(size, mtime_ns)` the change-detection
signal, so a fixture written at the current time hands every scan a different signal and quietly
makes [spec §3.8](spec.md#38-scanning-and-change-detection)'s "the same tree scanned twice produces
the same items" untestable. The generator pins every file to one timestamp, and a test asserts
there is exactly one. Nothing in the task said so; the byte-identity criterion reads like the whole
of determinism and is about half of it.

**Five of the thirteen acceptance criteria cannot live in a tree**, and this task was written as
though §5 were a list of tree contents. AC-2, AC-3, AC-10, AC-11 and AC-12 are **mutations
performed on the tree at scan time** — scan it twice, move the root, delete a file, make a
directory unreadable. A fixture can no more hold them than it can hold a second scan. The test
carries the map of which criteria the fixture is responsible for and says why the rest are absent,
so that "covers the awkward cases of §5" is not later read as a claim that all thirteen are
covered here.

**A tree of files cannot declare an empty directory**, and one of the cases is exactly that:
[spec §3.4](spec.md#34-series-seasons-and-episodes) says a season directory with no episodes is
normal. The manifest gained a trailing-slash form for it. Small, and it would have been found much
later — by a walker test that had nothing to walk.

**"No fixture file is a copyrighted work" had to become a property, not a list.** Asserting it by
checking extensions would pass for whatever extension nobody thought of, so the test asserts that
**tests/fixtures holds nothing but `.py` files**. The first thing it caught was `__pycache__`,
which is the interpreter's output for the very modules being checked and is the one exemption.

**T1's findings are in the tree already**, which is the argument for having measured first: a
`theme.mp3` and a `commentary.mka` sit beside a film and are declared to produce nothing
([behaviours §2.15](../../docs/compatibility/behaviours.md#215-an-audio-file-under-a-video-root-is-not-an-item)),
and a music entry carries an album tag bearing no resemblance to its directory — the shape 413 of
the reference's 5,814 tracks had. Neither would have been in a fixture designed a day earlier.

The whole tree is 54 files across three libraries and 54 KiB, generated, with a reason on every
entry.

## T3 — `domain/items.py`

- [ ] **Changes:** the item model and its types, with no I/O of any kind.
- **Depends on:** 001 complete
- **Verified by:** an import-direction test — `domain/` imports nothing from `library/`, `db/` or
  `api/`.
- **Plan reference:** §3, architecture §1

## T4 — `domain/sorting.py`: both derivations

- [ ] **Changes:** the base six-step derivation, the three type overrides, and the **dispatcher**
  that chooses between them — `sort_name(item)`, one entry point, so that no caller can reach the
  base rule directly.
- **Depends on:** T3
- **Verified by:** the fifteen measured rows of
  [spec §3.7.1](spec.md#371-the-base-derivation), **including the whitespace artefacts** —
  `Rock & Roll` → `rock␣␣roll` and `S.W.A.T.` → `s␣w␣a␣t␣`; plus the three override formulas, with
  the asymmetric episode widths; plus one row per overriding type asserting the dispatcher does not
  fall through to the base rule.
- **Note:** those two artefact rows exist to **fail when someone tidies the function**, which is the
  natural thing to do and which silently reorders every name containing a removed character. The
  test says so in a comment, or it will be deleted as an obvious bug.
- **Note:** one entry point is the design, not a convenience. [plan §9](plan.md#9-risks) rates the
  base rule reaching audio as High likelihood and every-album-reordered impact; a private base
  function with no public caller is what makes that unreachable rather than merely tested.
- **Plan reference:** §6.2, §9

## T5 — `library/identity.py`

- [ ] **Changes:** the NUL-separated, relative-path derivation; path normalisation; the
  `case_sensitive_identity` flag.
- **Depends on:** T3
- **Verified by:** 32 lowercase hex; deterministic across processes; type-separated (the same path
  as two types gives two ids); NFC and separator normalisation; a collision aborts rather than
  merging.
- **Plan reference:** §6.3

## T6 — Migration `0002_library_and_items`

- [ ] **Changes:** `libraries` and roots; `items` with `relative_path`, `sort_name` and
  `removed_at`; `item_user_data` keyed on the derived identity **with no foreign key to `items`**.
- **Depends on:** **002 T4** (migration `0001_users_and_sessions`)
- **Verified by:** up and down; the indexes 005 will need exist; **deleting an item row leaves its
  user data intact** — asserted directly, because a cascade added later would silently break
  [spec §3.8](spec.md#38-scanning-and-change-detection) and nothing else would notice. Extends
  `tests/unit/test_migrations.py` rather than adding a second harness beside it.
- **Plan reference:** §4

## T7 — `library/config.py`

- [ ] **Changes:** libraries, roots, collection types; the `case_sensitive_identity` flag frozen at
  creation.
- **Depends on:** T6
- **Verified by:** an attempt to change the flag on an existing library is **refused**, not accepted
  with a warning — flipping it rewrites every identifier in that library.
- **Note:** this task is what resolves **OQ-2**. The question is not measured but decided, and the
  decision is only real once the setting is recorded per library and the edit is refused. Move OQ-2
  to the resolved table of [spec §7](spec.md#7-open-questions) in this change, not a later one.
- **Plan reference:** §6.3

## T8 — `library/walker.py`

- [ ] **Changes:** traversal, extension filtering, the ignore rules, and detection of files still
  being written.
- **Depends on:** T7, T1 — the extension lists are measured and in
  [spec §3.2](spec.md#32-what-is-considered-a-media-file); the conservative union stands only for
  extensions that measurement did not reach.
- **Verified by:** hidden files, `.ignore` directories, zero-byte files and trailer/sample suffixes
  are all skipped; a file whose size changes between two passes is skipped **this** scan and picked
  up the next.
- **Plan reference:** [spec §3.2](spec.md#32-what-is-considered-a-media-file)

## T9 — The naming corpus and its harness

- [ ] **Changes:** `tests/corpus/naming.yaml` — rows of path, collection type and expected
  resolution, **each with a one-line reason it exists**; the table-driven harness; a YAML parser in
  the `dev` dependency group, which currently has none.
- **Depends on:** T3
- **Verified by:** the harness enumerates every row and **the suite is green**, because each row
  carries `xfail(strict=True)` naming the parser it is waiting for. The corpus is complete and the
  code is not, and both facts are visible.
- **Note:** the draft had this task land with every row failing, which says the right thing and
  cannot merge: [CI](../../.github/workflows/ci.yml) runs `uv run pytest` on every pull request.
  `strict=True` is what preserves the meaning — `pyproject.toml` sets no `xfail_strict`, so a
  lenient `xfail` that starts passing is an `xpass`, which is green and silent. Strict, a row cannot
  start passing without the task that claims it deleting its marker, and each of T10–T13 does
  exactly that for its group.
- **Note:** rows are added when a case is met and **never removed because a pattern fails**. A
  failing row is either a bug or a corpus error, and telling them apart is the work.
- **Plan reference:** §6.1

## T10 — `library/naming/clean.py`

- [ ] **Changes:** title and year extraction; release-tag stripping. Removes the `xfail` markers
  from the `clean` rows.
- **Depends on:** T9
- **Verified by:** the corpus rows tagged `clean` pass with no marker left on them. Written from the
  rules, not transcribed from the reference's expressions — Principle IV.
- **Plan reference:** §1, §6.1

## T11 — `library/naming/movies.py`

- [ ] **Changes:** bare file, folder-per-film, and multi-part grouping. Removes the `xfail` markers
  from the `movies` rows.
- **Depends on:** T10
- **Verified by:** the `movies` corpus rows pass, including **a multi-part film resolving to one
  item with two sources, not two items** — the most visible possible scanning bug, since it doubles
  a user's library.
- **Note:** **OQ-4** — whether the reference merges a folder-per-film layout when the folder and
  file names disagree — is decided here. Either the differential harness answers it or the corpus
  records the choice with a reason; it does not stay open past this task without one.
- **Plan reference:** [spec §3.3](spec.md#33-movies)

## T12 — `library/naming/series.py`

- [ ] **Changes:** season and episode extraction across the naming conventions, including
  date-based; multi-episode files; specials; extras. Removes the `xfail` markers from the `series`
  rows.
- **Depends on:** T10
- **Verified by:** the `series` corpus rows pass, including `S01E02-E03` as **one** item spanning
  two numbers, `Specials` as season 0, and **a series named `24` keeping its title**. The last one
  is where naive scanners fail: the pattern is matched against the filename first, then the parent
  directory.
- **Plan reference:** [spec §3.4](spec.md#34-series-seasons-and-episodes)

## T13 — `library/naming/music.py` and the metadata seam

- [ ] **Changes:** path-based structure; the `MetadataSource` protocol 004 will implement, with a
  path-only implementation for now. Removes the `xfail` markers from the `music` rows.
- **Depends on:** T10, T1 — the precedence is measured, in
  [spec §3.5](spec.md#35-music). Note what it does **not** cover: a flat directory of well-tagged
  files, which the measured library had none of.
- **Verified by:** the `music` corpus rows pass, including a two-disc album as one album and **a
  compilation with a different artist per track as one album**; the seam is exercised by a stub
  returning tags, proving 004 can override the path without 003 changing.
- **Plan reference:** §5, [spec §3.5](spec.md#35-music)

## T14 — `library/resolver.py`

- [ ] **Changes:** path → resolved item with parent-child structure, dispatched by collection type.
- **Depends on:** T11, T12, T13
- **Verified by:** the full corpus passes **and no `xfail` marker remains in it** — asserted, so
  that a row cannot be parked rather than fixed; a file under a `music` root is never resolved as a
  movie regardless of its name.
- **Plan reference:** §3

## T15 — `library/scan.py`, **additive only**

- [ ] **Changes:** walk, resolve, diff, write — with **no removal code path at all**. Writes batched
  into one transaction per library. Introduces the `ScanReport` type of
  [plan §5](plan.md#5-contracts), which T16 and T17 populate and T21 completes.
- **Depends on:** T9, T14
- **Verified by:** AC-1 — the fixture scans to the expected item set; AC-2 and AC-3 — rescan and
  scan-into-empty give byte-identical ids; **AC-13 — a scanned episode, track and season carry the
  §3.7.2 sort names and a scanned movie carries the §3.7.1 one**, read back from the database; a
  large synthetic tree completes in a time that makes the batching decision visible.
- **Note:** deliberately incapable of deleting anything. T17 grants that, after T16 constrains it.
- **Note:** the AC-13 assertion is here rather than at T4 on purpose. T4 proves the derivations are
  right; this proves the **scanner uses them**, which is a different claim and the one
  [plan §9](plan.md#9-risks) rates most likely to break. A green sort-name table beside a library
  ordered by the wrong rule is the failure it exists to catch.
- **Note:** `ScanReport` exists from this task so that T16's threshold and T17's removals report
  into one type rather than each inventing a partial one.
- **Plan reference:** §6.7, §5

## T16 — The safety guards and the destructive tests

- [ ] **Changes:** the three guards of [plan §6.5](plan.md#65-the-guard-against-a-mass-delete) —
  root readable and a directory; a root that previously yielded files and now yields none aborts;
  removal beyond a configured proportion stops and reports.
- **Depends on:** T15
- **Verified by:** **AC-12** and the two beyond it — an unreadable root removes nothing, a root that
  mounts empty removes nothing, and a scan that would remove a third of a library stops. Each
  asserted against the database, not against a log line. **Each fails when its guard is removed** —
  asserted by the test, not by a reviewer's word.
- **Note:** guard 2 is the one that matters. An unmounted share and an emptied directory are
  indistinguishable by a readability check.
- **Note:** these guards constrain a scanner that cannot yet delete. That is the point: they are
  written and proven against the thing they will constrain **before** it can do the damage they
  prevent.
- **Plan reference:** §6.5, §8.3, §9

## T17 — Removal and soft deletion

- [ ] **Changes:** `removed_at` on a missing file; revival on return; the maintenance action that
  purges, which a scan never does.
- **Depends on:** **T16 green**
- **Verified by:** **AC-11** — delete a file, rescan, the item disappears from queries and its user
  data survives; restore the file and the item revives **with the same id**.
- **Note:** this task is what grants the scanner the ability to remove. It does not start before
  T16 passes.
- **Plan reference:** §6.6

## T18 — Change detection

- [ ] **Changes:** the `(size, mtime_ns)` signal and a `--deep` mode that ignores it.
- **Depends on:** T17
- **Verified by:** a modified file is re-examined and **keeps its identity and user data**; an
  unchanged file is skipped; `--deep` re-examines everything.
- **Note:** mtime is not trustworthy on every filesystem. The default is fast, the escape hatch
  exists, and neither pretends to be the other.
- **Plan reference:** §6.4

## T19 — The root-move test

- [ ] **Changes:** `tests/library/test_root_move.py`.
- **Depends on:** T18
- **Verified by:** **AC-10** — scan at one path, move the whole tree, reconfigure the root, rescan:
  every identifier unchanged and no user data orphaned.
- **Note:** this is the test that proves the relative-path decision, and it fails loudly against an
  absolute-path derivation. It is the difference between a remount costing nothing and costing every
  client's favourites.
- **Plan reference:** §1, §8.2

## T20 — Scan reporting

- [ ] **Changes:** progress and the summary `ScanReport` carries — added, updated, removed, and
  files skipped **with the reason**.
- **Depends on:** T17
- **Verified by:** a scan over a fixture containing an unreadable file and an unparseable name
  reports both, each with its reason, and neither aborts the scan.
- **Plan reference:** §3, §7

## T21 — The acceptance map for 003

- [ ] **Changes:** `FEATURE_003` in `tests/conformance/test_acceptance.py`, and its entry in the
  `FEATURES` table; the status table in [`specs/README.md`](../README.md) moved to `Implemented`;
  the three artefacts marked `Implemented`.
- **Depends on:** T20
- **Verified by:** all thirteen criteria of [spec §5](spec.md#5-acceptance-criteria) name tests that
  exist, and `test_every_implemented_feature_has_a_map` passes with 003 in the status table — which
  it cannot do until this task exists.
- **Note:** the draft list had no such task, and its definition of done required marking 003
  `Implemented`. `test_every_implemented_feature_has_a_map` reads the status table and asserts every
  `Implemented` feature has a map, so that combination **fails the suite**. The test's own docstring
  says it: *"finishing 003 fails this until its map is written — which is the moment somebody is in
  a position to write it."* That moment is this task.
- **Note:** 002 T18 reshaped that file from one feature to a table of them precisely so 003 would be
  one entry rather than a third copy. If this task turns out to need more than one entry and one
  dictionary, the reshape did not work and that is the finding.
- **Plan reference:** §8, [002 T18](../002-authentication-users-and-sessions/tasks.md)

---

## Definition of done

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing
      test — all thirteen, by name, in `FEATURE_003` (T21).
- [ ] The naming corpus passes in full, **carries no `xfail` marker**, and every row states the
      reason it exists.
- [ ] The three destructive-failure tests pass, and each fails when its guard is removed.
- [ ] Scanning twice, and scanning into an empty database, produce byte-identical identifiers.
- [ ] Moving a library root changes no identifier.
- [ ] No fixture file is a copyrighted work, and the fixture generator needs nothing outside the
      locked dependency set.
- [ ] The scanner writes sort names **through the dispatcher**, asserted against the database and
      not only against the derivation table.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same change.
- [ ] Any newly measured reference behaviour is in `docs/compatibility/behaviours.md` with
      provenance.
- [ ] **Every open question in [`spec.md` §7](spec.md#7-open-questions) is either resolved with
      provenance or still open with a written reason** — **OQ-1 and OQ-5 resolved at T1**, OQ-2 at
      T7, OQ-4 at T11, and OQ-6 once the override formulas are read against a larger library. A
      question that is
      closed without an answer is the failure this line exists to prevent.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

004 needs the `MetadataSource` seam to be genuinely substitutable, or music identification lands as
a rewrite rather than an implementation. 005 needs `sort_name` indexed and library visibility
joinable. 008 needs somewhere to record that a file wants probing without 003 probing it — and, from
T2, it needs to generate its own decodable fixtures, because 003 generates none. All four are cheap
here and expensive later.
