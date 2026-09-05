---
feature: 003-library-configuration-and-scanning
title: Library configuration and scanning — tasks
status: Implemented
created: 2026-08-26
updated: 2026-08-27
accepted: 2026-08-27
started: 2026-08-27
implemented: 2026-08-27
plan_status_required: Accepted
plan_status_actual: Implemented
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

## T3 — `domain/items.py`  ✅

- [x] **Changes:** the item model and its types, with no I/O of any kind.
- **Depends on:** 001 complete
- **Verified by:** an import-direction test — `domain/` imports nothing from `library/`, `db/` or
  `api/`.
- **Plan reference:** §3, architecture §1

### Done — 2026-08-27

**The plan's data model could not hold two of the acceptance criteria, and the same mistake made
both.** [plan §4](plan.md#4-data-model) described `items` as though every item had at most one file
and occupied at most one number:

- `relative_path` — singular — cannot hold a **two-part film**, which AC-4 and
  [spec §3.3](spec.md#33-movies) require to be *one* `Movie` with two media sources. The plan never
  mentioned a media source anywhere. T6 would have written the migration exactly as specified, and
  T11 would have discovered at the point of writing part two that there was nowhere to put it.
- `index_number` alone cannot hold `S01E02-E03`, which AC-5 requires to be **one** episode spanning
  both numbers rather than two items.

Both are corrected in [plan §4](plan.md#4-data-model) in this change: an `item_sources` child table,
and `end_index_number`. Neither correction was expensive here. Both would have been a migration
rewrite at T6 and a resolver rewrite at T11.

**Moving `size` and `mtime_ns` onto the source is the same correction continued.**
[plan §6.4](plan.md#64-change-detection) makes them the change-detection signal, and a film whose
*second* part was replaced has changed — an item-level pair cannot say so. It also deletes a
nullability that would otherwise have been everywhere, because a `Series` has no path at all and
under this shape simply has no sources.

**The parent of a film is its library, not nothing.** The first draft of `PARENT_OF` had `Movie`,
`Series` and `MusicArtist` all hanging from `None`, which reads fine until you notice
[spec §3.1](spec.md#31-libraries) says each library *is* an item. With `CollectionFolder` at the
root of every chain, the leaves of the hierarchy are exactly the file-backed types — and a test
asserts that equivalence, because the two drifting apart is how a scanner ends up creating a
container that owns a container.

**A `tags` field was written and then removed.** It looked reasonable — the metadata seam of
[plan §5](plan.md#5-contracts) hands tags back, so why not carry them? Because nothing persists
them: 003 uses tags to *resolve* a name and a number, and what the item stores is the result. A
field on the object a repository hands out, holding something no repository ever loads, is a lie
with a docstring. The fixture manifest carries the tags, which is where the stub reads them.

**The import-direction test asserts the strong form** — a domain module imports the standard
library and other domain modules, and nothing else — rather than the three packages the task named.
`compat/` would be just as wrong as `db/`: it exists to know the wire format is Jellyfin's, and a
domain object that knew would make the conformance sweep unenforceable. The test was checked by
adding `from atrium.db.engine import build` to `items.py`, watching it fail with the package named,
and reverting.

## T4 — `domain/sorting.py`: both derivations  ✅

- [x] **Changes:** the base six-step derivation, the three type overrides, and the **dispatcher**
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

### Done — 2026-08-27

**Step 6 asserts something nobody measured, and it took writing it to notice.**
[spec §3.7.1](spec.md#371-the-base-derivation) step 6 is "fold diacritics; transliterate anything
still outside ASCII" — and the whole measured set contains exactly one non-ASCII name, `Amélie`,
whose `é` **decomposes**. Folding alone reaches it. Not one crafted case needed a transliteration,
so the second half of that step is a claim with no measurement under it. `ø`, `ß`, `æ` and every
non-Latin script were never sent. Now **OQ-7**, with the spec and
[behaviours §2.6](../../docs/compatibility/behaviours.md#26-sortname-has-two-derivations-and-three-types-use-the-second)
both saying which half is reproduced and which half is a decision: v1 folds, applies a short table
of the obvious Latin readings, and drops what remains. Dropping is at least stable — the same name
always sorts to the same place — which a partial guess would not be.

**The algorithm now exists twice, and something checks the copies agree.**
[`tools/probe_sort_names.py`](../../tools/probe_sort_names.py) carries its own derivation and
**cannot import this one**: a probe is standard-library only and runs on a 3.9 with no environment
built. So `tests/unit/test_sorting_matches_the_probe.py` asserts the two produce the same answer
for all fifteen cases, both override formulas, and all four configured defaults. What drift would
cost is specific rather than tidy: the probe is the regression suite for the project's *beliefs*,
and a probe that has drifted from `domain/sorting.py` stays green while the reference and the
server we ship disagree — the one failure it exists to prevent. Checked by changing the pad width
to 9 and watching it name the three rows that diverged.

**`isdigit` is the wrong predicate and the probe had it too.** C#'s `char.IsDigit` is the Unicode
`Nd` category exactly; Python's `str.isdigit` also accepts superscripts, so `R²` would pad to
something no ordering wants. Both sides now use `isdecimal`. Unmeasured either way — no probe case
carried one — but a deliberate choice beats an inherited one, and the drift test would otherwise
have been asserting agreement between two things deliberately made different.

**`Season` is not "the prefix plus the name" with an empty name.** The first version of the
"does not fall through to the base rule" test parametrised all three overriding types and asserted
each keeps its raw name. `Season` fails that, correctly: its formula is
[the number alone and nothing else](spec.md#372-the-three-types-that-replace-it). The test was
wrong, not the code — and it is exactly the misreading that would later have somebody "fix" the
function by appending the name.

**Fifteen rows, not fourteen.** [spec §3.7.1](spec.md#371-the-base-derivation)'s table prints
fourteen; the probe sent fifteen. The extra one is `Amelie`, the ASCII control for the diacritic
row, which says nothing on its own and is what makes the row below it mean something. The tests
carry all fifteen, and one of them asserts the probe still sends fifteen — a shrinking case list
means a row of §3.7.1 quietly stopped being measured.

## T5 — `library/identity.py`  ✅

- [x] **Changes:** the NUL-separated, relative-path derivation; path normalisation; the
  `case_sensitive_identity` flag.
- **Depends on:** T3
- **Verified by:** 32 lowercase hex; deterministic across processes; type-separated (the same path
  as two types gives two ids); NFC and separator normalisation; a collision aborts rather than
  merging.
- **Plan reference:** §6.3

### Done — 2026-08-27

**The plan's contract described one of the four identity rules and called it the contract.**
[plan §5](plan.md#5-contracts) named a single `derive(item_type, library_id, relative_path)`. That
is right for a `Movie`, an `Episode` and an `Audio`, and wrong for the other five types:
[spec §3.6](spec.md#36-identity) gives a `Season` its *series' identity plus a number*, gives a
`Series`, `MusicAlbum` and `MusicArtist` their *library plus a normalised name*, and gives a
`CollectionFolder` the library alone. Two of those are not paths at all.

The dangerous part is that the wrong signature still *works*: passing a series identity as the
`relative_path` argument satisfies it and returns a perfectly valid identifier for the wrong thing.
Nothing raises, nothing looks odd, and the symptom arrives much later as an item that does not
match its file. There are now four functions, each refusing a type that belongs to another rule,
and a `RULE_OF` map a test checks covers every type exactly once. [plan §5](plan.md#5-contracts) is
corrected in this change.

**Half of this task's verification was already 001's, and rewriting it would have been worse than
skipping it.** "32 lowercase hex", "deterministic across processes" and the NUL separation are
properties of `atrium.compat.guids.derive`, which has existed since 001 with a docstring saying
*"feature 003 is its first real caller"* — and 001 already tests the cross-process run, which is
the only way to catch an identifier that depends on hash randomisation. Asserting them again in
`tests/library/` would have been testing somebody else's function, and the copy would have drifted
towards agreeing with itself. What is tested here is what 003 adds: the four keys, the
normalisation, and the collision. One cross-process test remains, for the normalisation wrapped
around the hash rather than the hash.

**"The normalised name" was never defined anywhere.** [spec §3.6](spec.md#36-identity) used the
phrase for three item types and left it to the reader. Since the identity of every series and album
in a library depends on it, the definition is now in the spec: the same three steps a path gets —
separators, Unicode form, and case — so that a series whose directory is renamed from `the series`
to `The Series` is the same series, for the same reason a file whose path changed case is the same
file.

**A collision needed something to abort.** [plan §7](plan.md#7-failure-handling) says two files
deriving one identifier abort and name both paths, and the task's verification asks for it — but
nobody can exhibit a real truncated-SHA-256 collision, so there was nothing to test. `ensure_unique`
is that abort as a pure function over `(id, path)` pairs, which the scan will call at T16 and which
a test exercises today with a forced duplicate. It also had to learn that **the same path twice is
not a collision**: a rescan sees every file again, and an abort there would make the second scan of
any library fail.

**`for_season(series, None)` returns an identity rather than raising.** A season whose number could
not be read still has to be *something*, and the alternative — refusing — would make one unparseable
directory abort a library. It is a different identity from season zero, which matters because
`Specials` is season zero and an unreadable name is not.

## T6 — Migration `0002_library_and_items`  ✅

- [x] **Changes:** `libraries` and roots; `items` with `relative_path`, `sort_name` and
  `removed_at`; `item_user_data` keyed on the derived identity **with no foreign key to `items`**.
- **Depends on:** **002 T4** (migration `0001_users_and_sessions`)
- **Verified by:** up and down; the indexes 005 needs exist; **deleting an item row leaves its
  user data intact** — asserted directly, because a cascade added later would silently break
  [spec §3.8](spec.md#38-scanning-and-change-detection) and nothing else would notice. Extends
  `tests/unit/test_migrations.py` rather than adding a second harness beside it.
- **Plan reference:** §4

### Done — 2026-08-27

**This task's own description was stale, and the plan is the authority.** It asks for "`items` with
`relative_path`" — which T3 had already corrected: [plan §4](plan.md#4-data-model) moved the path,
size and mtime into an `item_sources` child table, because AC-4 needs one film with two of them.
The task text is left as written, as every finished task's is; the schema follows the plan.

**The ORM did not know that items depend on libraries, and the schema did.**
`Base.metadata.sorted_tables` already ordered `libraries` before `items` — the foreign key says so.
But the session's unit of work orders inserts from **mapper relationships**, not from foreign-key
columns, and there was no relationship between the two. Writing a library and its items in one
transaction — which is exactly what [plan §6.7](plan.md#67-scan-orchestration) says a scan does —
failed on the foreign key. `Library.items`, `Item.library` and the self-referential
`Item.parent`/`Item.children` are declared for the *ordering*, not for the traversal: a series, its
seasons and its episodes are written in one transaction too. They carry `lazy="raise"` like every
other relationship here and `passive_deletes=True`, so the cascade stays in the database rather
than loading every descendant into memory to delete it a row at a time.

This would have arrived at T16 as an intermittent-looking foreign-key error in a batched write.

**`sort_name NOT NULL` cannot be demonstrated through the ORM.** The column carries a Python-side
default, so assigning `None` inserts the empty string rather than failing — which is the right
behaviour for the scanner and also means the ORM can never show the constraint. The test issues the
insert in SQL instead. Found by writing the test the obvious way and watching it report
`DID NOT RAISE`; a version that had asserted something weaker would have passed and proved nothing.

**The foreign key that looked obvious would have broken 002.** `user_library_access.library_id`
carried a comment saying it had no foreign key "yet, because the table it would point at does not
exist" — and this task creates that table. Adding it is wrong, permanently: 002 spec §3.7
guarantees a policy round-trips whole, `EnabledFolders` arrives from the client, and a client may
name a library this server has not configured. Under a foreign key that policy write **fails**
instead of round-tripping, which is a difference a client can see. The comment now says permanent,
and says why.

**Two tests elsewhere pinned `0001` as the head, and one of them meant to.**
`test_db_schema.py::test_a_fresh_database_is_brought_to_the_shipped_head` had already survived this
once — its docstring records that its predecessor "named the day the assumption expired instead of
leaving a stale one passing". It has now done so twice, and is pinned to `0002` rather than taught
to read the head: a test that looks the head up in the same place the code does asserts only that
two functions agree, which they always will. The other, in `test_migration_0001.py`, is about
zero-byte database files and pinned the head incidentally — it reads it now.

**The generic sweep needed no change**, which is what it promised: `test_migrations.py` walks
whatever the script directory holds, so `0002` was applied, rolled back and schema-compared without
anybody extending it. `test_the_migration_and_the_models_agree` likewise compares the *whole*
metadata, so it covers this revision already.

## T7 — `library/config.py`  ✅

- [x] **Changes:** libraries, roots, collection types; the `case_sensitive_identity` flag frozen at
  creation.
- **Depends on:** T6
- **Verified by:** an attempt to change the flag on an existing library is **refused**, not accepted
  with a warning — flipping it rewrites every identifier in that library.
- **Note:** this task is what resolves **OQ-2**. The question is not measured but decided, and the
  decision is only real once the setting is recorded per library and the edit is refused. Move OQ-2
  to the resolved table of [spec §7](spec.md#7-open-questions) in this change, not a later one.
- **Plan reference:** §6.3

### Done — 2026-08-27

**There were two frozen fields, not one.** The task names `case_sensitive_identity`, and the same
argument applies word for word to a library's **collection type**: it selects which resolution
rules apply, so changing it re-resolves every file under a different set of rules and gives every
item a new type and a new identifier. Both are now refused, and [spec §3.6](spec.md#36-identity)
says so.

**And a third thing behaves the same way without being a field at all.** A library's identity is
*allocated* when it is declared, not derived from its name or its roots — which is deliberate, and
is what makes renaming a library or moving its roots free. The consequence nobody had written down
is the mirror image: **deleting a library and declaring another one with the same name and the same
roots is not the same library**, and every item under it gets a new identifier. It is the same
destruction the frozen flag exists to prevent, reachable by an operator who thinks they are tidying
up, and no code can refuse it because nothing can tell the two intentions apart. So it is in the
spec instead. Two tests hold the other half: renaming a library and moving its roots both leave
every identifier unchanged.

**The refusal is enforced twice, in two different shapes.** `library/config.py` raises with an
explanation and a way forward; `LibraryRepository` has **no method that can change the flag at
all** — `rename` and `set_roots` take the fields an operator may edit and the flag is not among
them. A guard in a service is a guard one new caller can go around; a repository with nowhere to
put the value is not. A test asserts the repository's public surface by name, so adding a setter
fails rather than being reviewed.

**`update` accepts the frozen arguments in order to refuse them.** Leaving them out of the
signature would have produced `TypeError: unexpected keyword argument`, which tells an operator
they typed something wrong rather than that they asked for something destructive. It also lets a
caller round-tripping a library it just read pass the values unchanged, which is not a request for
anything and is allowed through.

**Two roots where one contains the other are refused**, which nothing had said. Every file under
the inner root would be found twice, under two relative paths, and therefore under two
identifiers — a doubled library, which is the failure AC-4 exists to prevent arriving by a
different door. Root spellings are normalised for the same reason: `/mnt/films`, `/mnt/films/` and
`/mnt/./films` are one directory written three ways, and left alone an operator could configure the
same tree twice.

**Symbolic links are deliberately not resolved.** An operator who mounted a share at a stable path
and expects that path to be the root is right, and resolving would put the mount target in the
configuration — where the next remount changes it, and with it every relative path underneath.

**OQ-2 is resolved**, in the resolved table of [spec §7](spec.md#7-open-questions). The question
was never what the reference does — it has the setting and defaults it off — but whether Atrium
should treat it as a global decision or a per-library fact. Per-library: a server-wide switch would
mean one flip rewrote every identifier in every library at once.

## T8 — `library/walker.py`  ✅

- [x] **Changes:** traversal, extension filtering, the ignore rules, and detection of files still
  being written.
- **Depends on:** T7, T1 — the extension lists are measured and in
  [spec §3.2](spec.md#32-what-is-considered-a-media-file); the conservative union stands only for
  extensions that measurement did not reach.
- **Verified by:** hidden files, `.ignore` directories, zero-byte files and trailer/sample suffixes
  are all skipped; a file whose size changes between two passes is skipped **this** scan and picked
  up the next.
- **Plan reference:** [spec §3.2](spec.md#32-what-is-considered-a-media-file)

### Done — 2026-08-27

**`os.walk` discards directory errors by default, and that default is the dangerous one here.** A
directory the scan cannot list would simply not appear — no candidate, no skip, nothing said. Every
file below it would then look *deleted* to the next scan's diff: a partial loss too small for
[plan §6.5](plan.md#65-the-guard-against-a-mass-delete)'s emptiness guard to catch and quite large
enough for a user to notice their favourites went missing. The walk now passes an error handler and
reports the directory. Found because the test written for it did not fail.

**A `chmod 000` on a *file* proves nothing about a walk**, which is how that was found. `stat`
needs execute permission on the containing directory, not read permission on the file, so the
unreadable-file test walked straight past its own premise and the file became a candidate. A walk
never reads contents — an unreadable *file* is 008's problem, at the point something opens it. The
case that belongs here is an unreadable directory.

**`Specials` is not an extras folder, and nothing but a comment stops somebody making it one.**
Both lists in this module — suffixes and directory names — are the kind that grow by someone adding
the obvious next entry, and `specials` is the obvious next entry: it sits beside `Extras` and
`Featurettes` in real libraries and it is not one of them. It is an alias for season zero
([spec §3.4](spec.md#34-series-seasons-and-episodes), AC-6). A walker that filed it under extras
would **drop every special episode in every series while producing a scan that looks entirely
correct**. It has its own test, on its own, rather than a row in a table, and the constant says why
it is absent.

**The two passes are two functions, so no test sleeps.** Detecting a file still being written means
looking at its size twice, and the gap in production is the traversal itself. Exposing `found` and
`settle` separately lets a test change a file between them; a single `walk()` that slept would have
put a sleep in the suite for every run, forever, to catch something that takes one line to arrange.

**The walk reports *why*, not just *what***, and that is T20's requirement arriving eight tasks
early. It costs nothing here — the reason is known at the moment the file is refused — and
retrofitting it later would have meant re-deriving each reason from a path, which is the same
decision made twice.

**The extension lists carry their provenance inline.** The measured extensions are marked as
measured and the rest are marked as [spec §3.2](spec.md#32-what-is-considered-a-media-file)'s
conservative union, so a reader can tell a fact from a reasonable guess without leaving the file.
A test asserts the measured ones are still all present — shrinking that set would be discarding a
measurement — and another asserts the video and audio lists **do not overlap**, because the
overlap *is* the fallback the reference was measured not to have.

## T9 — The naming corpus and its harness  ✅

- [x] **Changes:** `tests/corpus/naming.yaml` — rows of path, collection type and expected
  resolution, **each with a one-line reason it exists**; the table-driven harness; a YAML parser in
  the `dev` dependency group, which had none until this task added `pyyaml`.
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

### Done — 2026-08-27

**The reference can validate the corpus's numbers and cannot validate its titles.**
[plan §6.1](plan.md#61-the-naming-corpus) says the corpus is written from observed conventions
*"and from what the reference produces for each case"* — so the reference's 1,557 films and 917
episodes were read to check the rows against. The numbers held up completely: `1x02` agreed with
the resolved season and episode **902 times out of 902**, `S01E02` **15 out of 15**, zero
disagreements. The titles did not survive the same test, and not because they were wrong:

| Of 1,557 film names | |
|---|---|
| match their own de-yeared filename | 344 |
| match their folder | 12 |
| match **neither** | **1,201** |

**The reference's item names measure 004, not 003.** Metadata had already replaced them, so the
second half of plan §6.1's sentence is not achievable through the API against any library with
metadata enabled. The title rows here are ours, and the corpus header says which half of it is
measured and which half is not, so nobody later mistakes one for the other.

**`1x02` is not the exotic form. It is the dominant one** — 902 of 917 episodes on a real library,
against 15 for `S01E02`. Written from intuition, this corpus would have had `SxxExx` as the main
case and `1x02` as a footnote, and T12 would have optimised for the wrong shape. The rows now
weight them the way a real library does, and the ones that were measured say so.

**The reference has no multi-episode filenames at all**, so AC-5's `S01E02-E03` is unmeasured
there. Its rows are ours, and they are marked as such.

**88 rows, not the "several hundred" the plan estimates.** The rule that a row is never removed
because a pattern fails makes padding permanent: a row that isolates nothing cannot be acted on
when it fails and cannot be deleted either. Each of these isolates one convention, AC-4 to AC-9 are
named in the reasons that carry them, and a test asserts [plan §6.1](plan.md#61-the-naming-corpus)'s
own list of naive-scanner cases is still covered — so shrinking the corpus past those fails rather
than passing quietly.

**`strict=True` was verified rather than assumed.** A throwaway `naming` module satisfying one row
was dropped in, and the run reported `XPASS(strict)` — a failure — for exactly the rows it
satisfied. That is the mechanism T10 to T13 depend on: a row cannot start passing while its group
is still listed in `AWAITING`, so each of those tasks has to delete its own line to go green.

**PyYAML was already installed**, transitively, through `uvicorn[standard]`. The harness would have
worked without declaring it and would have broken on the day that extra changed its own
dependencies — a test suite failing for a reason nobody could see in this repository. Declaring it
adds two lines to the lock and no packages.

**The "every row states a reason" guard caught three rows on its first run** — `"bracketed tag
runs"`, `"a space between them"`, `"and with underscores"`. All three were mine, written minutes
earlier, and all three were expanded rather than the threshold lowered.

## T10 — `library/naming/clean.py`  ✅

- [x] **Changes:** title and year extraction; release-tag stripping. Removes the `xfail` markers
  from the `clean` rows.
- **Depends on:** T9
- **Verified by:** the corpus rows tagged `clean` pass with no marker left on them. Written from the
  rules, not transcribed from the reference's expressions — Principle IV.
- **Plan reference:** §1, §6.1

### Done — 2026-08-27

**The corpus passed on the first run, which is exactly when a corpus proves nothing.** All 25
`clean` rows went green before any of them had met a real filename — unsurprising, because the same
person wrote the rows and the rules within an hour of each other. So the parser was run over the
**1,557 real film filenames** on the reference. It found three defects the corpus could not:

| | before | after |
|---|---|---|
| crashes | 0 | 0 |
| **empty titles** | **1** | **0** |
| titles still carrying release noise | **46** | **8** |

1. **A leading bracketed year emptied the title.** `(2015) The Film …` is a real convention, and
   "the title is everything before the year" returns nothing for it. An item with **no name** is
   worse than one with a wrong name, because nothing can find it — and it would have reached a
   client as a blank row.
2. **Bracket groups are glued together with no space between them.** `[1080p][Castellano][wWw…]`
   is *one whitespace token whose brackets balance*, so the first implementation — which counted
   bracket depth across tokens — never saw three groups and cut nothing. The second attempt cuts on
   the text, and that is the whole of the difference between 46 and 8.
3. **"Does the name contain a space" is not how you tell a dot-separated name from a space-
   separated one.** Real names mix both. The test is which character is *doing the separating* —
   whichever there are more of.

**The eight that remain are recorded, not chased.** Both residual shapes would need a looser rule,
and looser is the direction that damages real titles: breaking the dot/space tie towards dots
changes how every space-separated name tokenises, and stripping tags from the middle of a name
would gut every title that legitimately contains one of these words. `Hard Candy` and `Web of Lies`
are in the corpus to hold that line. 0.5% of one library, and 004 replaces those titles anyway.

**Seven rows were added, and none was written from what the code does.** Each expected value was
decided first and then checked — the corpus is the specification, so a row recording whatever the
parser happened to output would turn it into a description of the code and quietly delete the only
thing keeping the two honest.

**Language names became tags, which sounds dangerous and is not.** `spanish`, `english` and the
rest appear inside the bracket runs and had to be recognised there. Titles are only ever trimmed of
tags **from the end**, so `The English Patient` keeps its middle — and it is now a corpus row for
exactly that reason.

**`AWAITING` lost its `clean` line**, which is what makes those 32 rows count. With `strict=True`
still on them they would fail as `XPASS(strict)` — verified at T9 — so the line could not have been
left behind by accident.

## T11 — `library/naming/movies.py`  ✅

- [x] **Changes:** bare file, folder-per-film, and multi-part grouping. Removes the `xfail` markers
  from the `movies` rows.
- **Depends on:** T10
- **Verified by:** the `movies` corpus rows pass, including **a multi-part film resolving to one
  item with two sources, not two items** — the most visible possible scanning bug, since it doubles
  a user's library.
- **Note:** **OQ-4** — whether the reference merges a folder-per-film layout when the folder and
  file names disagree — is decided here. Either the differential harness answers it or the corpus
  records the choice with a reason; it does not stay open past this task without one.
- **Plan reference:** [spec §3.3](spec.md#33-movies)

### Done — 2026-08-27

**OQ-4 asked the wrong question, and the corpus row answering it had the answer backwards.** The
question was what the reference does when a folder and a file *disagree*. Measured across 1,480
one-film directories: a folder and a file naming two genuinely **different works did not occur
once**. What occurs constantly is the folder naming the *same* work more cleanly — and there the
folder wins by a wide margin.

| Whose cleaned name matched what the reference resolved | |
|---|---|
| the **folder** only | **635** |
| the **file** only | **3** |
| both | 452 |
| neither (metadata had replaced the title) | 390 |

Taking the folder outright scores **1,087 of 1,557** against taking the file's **457**. The
corpus row said *"the file wins, because it is the more specific name"*, which was written from
intuition and is wrong. It is corrected, with the measurement in its reason — a failing row is
either a bug or a corpus error, and this was the second kind.

**The reason is mechanical rather than aesthetic**, which is why it generalises: the tools that
fetch films mangle filenames and leave directories alone. Of 1,557 films, **135 had a filename with
no spaces at all** while its directory had them, and others were truncated mid-word or suffixed
with the site that served them.

**A cleverer rule was tried and scored worse.** Preferring the folder only when the two names look
like the same work — a containment test on the folded names — scored **1,038 against 1,087**,
because the cleaner mangles one side often enough that the similarity test fails on films where the
folder is still right. The simplest rule that the data supports is the one that shipped.

**One part of it genuinely cannot be decided from a single path.** A *genre* directory holding
forty films would give all forty the title `Action`. Nothing in one path distinguishes a category
from a film — only what else is in the directory does — so `group` makes that call, and a directory
holding several different titles names none of them. That is the same function AC-4 needed anyway.

**There are no multi-part films on the reference at all** — zero in 1,557 — so AC-4 is unmeasured
there and its rows and tests are ours. The `-a`/`-b` marker [spec §3.3](spec.md#33-movies) names is
the ambiguous one: unanchored it eats hyphenated titles, and `Vitamin-C` would become part three.
It is recognised only after a closing bracket or a digit, which is what `The Film (1999)-a` looks
like and what a hyphenated title does not.

**The whole pipeline was run over the reference's 1,557 paths**: 1,557 in, 1,557 out — nothing
merged that should not have been — 0 empty names, and the resolved name matched the reference's for
**69.9%**, against 29.4% for the file alone. The remaining 30% are titles metadata replaced, which
T9 established the API cannot show us.

## T12 — `library/naming/series.py`  ✅

- [x] **Changes:** season and episode extraction across the naming conventions, including
  date-based; multi-episode files; specials; extras. Removes the `xfail` markers from the `series`
  rows.
- **Depends on:** T10
- **Verified by:** the `series` corpus rows pass, including `S01E02-E03` as **one** item spanning
  two numbers, `Specials` as season 0, and **a series named `24` keeping its title**. The last one
  is where naive scanners fail: the pattern is matched against the filename first, then the parent
  directory.
- **Plan reference:** [spec §3.4](spec.md#34-series-seasons-and-episodes)

### Done — 2026-08-27

**917 of 917.** Run over every episode of a real library, the parser produced the same season and
episode number the reference resolved for **all 917** — no crashes, none missing, none wrong — and
derived a series name for every one `[read: Jellyfin 10.11.11, 2026-08-27]`. That is the strongest
result any task here has had, and it is worth saying why it was available: T9 measured the ground
truth *before* this was written, so the numbering had a real target to hit rather than a corpus
written by the same hand an hour earlier.

**The pattern order is load-bearing, not tidiness.** `S01E02-E03` **contains** `S01E02`, so a
scanner that tries the simple pattern first finds it, stops, and discards the second number with
nothing to show for it. That is AC-5 failing silently, and the only thing preventing it is that the
span patterns are tried first. The module says so where the patterns are declared, because the
obvious tidy-up is to sort them by how common they are.

**The spec contradicted itself about extras, and this task is where it had to be settled.**
[§3.2](spec.md#32-what-is-considered-a-media-file) lists them as ignored;
[§3.4](spec.md#34-series-seasons-and-episodes) said they are *"attached to their parent"*. Those
are different behaviours and T8 had already implemented the first. v1 ignores them, and §3.4 now
says so with the argument: an extra is not structure — it has its own title, artwork and duration,
which are 004's, 006's and 008's — and there is **nowhere to attach one**, because an item's files
are the parts of the work itself and a trailer among them would play as part of the film. An
operator loses nothing they can currently see, and a later feature that adds a surface for extras
starts from a rule rather than from two paragraphs that disagree.

**`1x02` shaped the implementation because T9 measured it.** 902 of 917 episodes used it against
`S01E02`'s 15. Written from intuition this module would have had `SxxExx` as the main path and
`1x02` as an afterthought, and been the slow way round on 98% of a real library.

**Two guards exist because the numbers are ambiguous, not because a test wanted them.** A second
number that is not *larger* than the first is not a span — `12-00 AM` is an episode title, and
`24 - S01E01 - 12-00 AM` would otherwise become an episode spanning 1 to 0. And season **zero is
not the same as no season**: a falsy check conflates `Specials` with a directory that says nothing,
and there is a test for each.

## T13 — `library/naming/music.py` and the metadata seam  ✅

- [x] **Changes:** path-based structure; the `MetadataSource` protocol 004 implements, with a
  path-only implementation for now. Removes the `xfail` markers from the `music` rows.
- **Depends on:** T10, T1 — the precedence is measured, in
  [spec §3.5](spec.md#35-music). Note what it does **not** cover: a flat directory of well-tagged
  files, which the measured library had none of.
- **Verified by:** the `music` corpus rows pass, including a two-disc album as one album and **a
  compilation with a different artist per track as one album**; the seam is exercised by a stub
  returning tags, proving 004 can override the path without 003 changing.
- **Plan reference:** §5, [spec §3.5](spec.md#35-music)

### Done — 2026-08-27

**A track with no disc marker is on disc one, not on an unknown disc.** Measured across 5,814 real
tracks: the reference reports disc 1 for **5,152** of them. Treating an unmarked track as *unknown*
— which is what the first implementation did, and what "the path did not say" naturally suggests —
scored **21.2%** against **98.0%** for defaulting to one.

[spec §3.7.2](spec.md#372-the-three-types-that-replace-it) corroborates it from the other side, and
nobody had noticed: an `Audio` sort name is `0001 - 0003 - The Song`, and **that leading `0001` is
this default**. Without it every track in the library would sort with a prefix one segment short of
what the specification shows.

**Path-only resolution, measured on the same 5,814 tracks:**

| | |
|---|---|
| disc | **98.0%** |
| album artist | 89.3% |
| album | 84.9% |
| track number | 77.9% |
| title | **4.9%** |

That last figure is not a defect — it is T9's finding again, from the other end. Titles come from
tags, which is exactly what the seam is for, and a module scoring 4.9% on titles while scoring 98%
on discs is a module doing the half of the job it owns.

**A single directory level is an artist, not an album**, and the first implementation had it the
other way round. `Artist/Track.flac` read the one directory as the album, which would file every
loose track in a library under an album named after the person who made it. Caught by a corpus row
whose whole reason was that sentence.

**A trailing year in an album directory stays in the album's name.** `Live 1999` is an album
called `Live 1999`, while `The Album (2001)` is `The Album` from 2001 — so only a *bracketed* year
is a year here, unlike a film's. The bare form is part of how albums are named.

**An empty tag is a tag, not an absence.** A file that says its album is the empty string has said
something, and the reference copies it — 129 of 5,814 resolved names keep whitespace a path could
not produce, which is how T1 identified them as tags at all. Treating empty as absent would put
that track back under its directory's name, silently.

**The seam is proven substitutable rather than described as such.** A stub source overrules the
path in **every** field the parse carries, one test per field: if any of them could not be
overridden, 004 would have to change this module to add it, and music identification would land
there as a rewrite. `PathOnly` is not a placeholder either — a server with no metadata provider
configured runs on exactly it, forever.

**The corpus is now green in full: `AWAITING` is empty and no `xfail` remains.** The mechanism T9
built worked exactly as designed — each of T10 to T13 had to delete its own line to go green, and
`strict=True` meant none of them could have been left behind.

## T14 — `library/resolver.py`  ✅

- [x] **Changes:** path → resolved item with parent-child structure, dispatched by collection type.
- **Depends on:** T11, T12, T13
- **Verified by:** the full corpus passes **and no `xfail` marker remains in it** — asserted, so
  that a row cannot be parked rather than fixed; a file under a `music` root is never resolved as a
  movie regardless of its name.
- **Plan reference:** §3

### Done — 2026-08-27

**Every item leaves through one function, and that is the whole design.** `_finished` is where a
sort name is attached, so there is no branch that can build an item and forget to sort
it — and, more to the point, none that can reach the base derivation directly.
[plan §9](plan.md#9-risks) rates *"the base sort rule applied to audio"* as its most likely and most
expensive mistake, and the reason is that it fails without a symptom: nothing raises, nothing logs,
and every album in the library is simply in the wrong order. Eleven construction sites would have
been eleven chances to get it wrong; there is one.

**A `Season`'s number is `index_number`, and every other type's is `parent_index_number`.** That
asymmetry is real — [spec §3.7.2](spec.md#372-the-three-types-that-replace-it)'s override reads a
season's own number from `index_number` while an episode reads its *season* from
`parent_index_number` — and the two are trivially easy to swap, because the season is the parent of
the episode and "parent index" is the natural place to look. A comment sits on that line, and the
sort-name tests would catch it: a season would sort as `Season` rather than as `0000`.

**"A file under a music root is never resolved as a movie" is enforced, not dispatched.** Every
item is checked against `PRODUCED_BY` before it is returned, so a resolver that grew a wrong branch
fails **here**, in this feature, rather than in 005 three months later as an item a client cannot
make sense of. The dispatch is already correct; the check is for the version of this file that
somebody edits next year.

**The library's `CollectionFolder` exists even when the library is empty.** A library that vanished
from a client because its last file was deleted is a worse answer than an empty one, and it would
have been the natural consequence of building items only from candidates.

**No row can be parked behind an `xfail` any more**, which this task's verification asked for and
which turned out to be worth stating carefully: there are two ways to make a failing corpus row
green, and only one of them is fixing it. The other is putting its group back into `AWAITING`,
which turns the failure into an *expected* failure and the run back to green with the row no longer
asserting anything. A task that genuinely introduces a new parser group now has to change that test
on purpose and say why.

**Nothing here invents a timestamp.** `date_created` and `date_modified` are left to the scan,
because a resolver that stamped them would give a different answer on every run — which is exactly
what [spec §3.8](spec.md#38-scanning-and-change-detection) forbids, and the kind of impurity that
makes a determinism test flake rather than fail.

## T15 — `library/scan.py`, **additive only**  ✅

- [x] **Changes:** walk, resolve, diff, write — with **no removal code path at all**. Writes batched
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

### Done — 2026-08-27

**"Incapable" is enforced by shape, not by discipline.** A scan that merely *chooses* not to delete
is one refactor away from deleting, so `ItemRepository` has **no removal method at all** — its
public surface is `by_library`, `add`, `update`, and a test asserts that list by name. `update`
cannot reach `removed_at` either: clearing it is a *revival* and setting it is a removal, and a
method that could write it either way would be a removal path wearing another name.

The two tests that matter here assert an **absence**: delete a file and rescan, nothing changes;
empty the entire root and rescan, nothing changes. Both will be *rewritten* at T17, and that is the
point — they record what this scanner is, so that the day it gains the ability is a visible change
rather than a silent one.

**The unit of work does not order rows within a table either.** T6 found that SQLAlchemy needs a
mapper relationship to know `items` depends on `libraries`; this needed the same fact one level
down. `parent_id` is written as a **column**, not through the `Item.parent` relationship, so
nothing tells the session that a season's row has to go in before its episodes'. Items are sorted
by their depth in `PARENT_OF` before writing, which is a static property of the type and does not
depend on the ORM being clever. It would have surfaced as a foreign-key error on a tree deeper than
one level, which is every library that is not films.

**AC-13 is asserted from the database, and that is the whole reason it is here rather than at T4.**
T4 proved the two derivations are right; this proves the **scanner uses them**. They are different
claims, and a green sort-name table beside a library ordered by the wrong rule looks exactly like
success — which is why [plan §9](plan.md#9-risks) rates it most likely to break.

**The batching test counts transactions, not seconds.** A timing threshold either flakes on a busy
runner or is so generous it catches nothing, while *how many transactions* is the actual decision
[plan §6.7](plan.md#67-scan-orchestration) made. 1,501 items, one commit — and `scan` never commits
at all, so the batching is structural: a caller that opens one unit of work per library gets one
transaction per library, and one that opens one per item gets what it asked for.

**`_differs` deliberately does not compare `date_modified`.** It is set *because* something changed,
so comparing it would make every item differ from itself and turn every rescan into a full rewrite
of the library — which AC-2 would have caught, but only after somebody wondered why a rescan of an
unchanged tree reported thousands of updates.

**`ScanReport.removed` exists from this task and is always zero.** The task asked for it so that
T16's threshold and T17's removals report into one type rather than each inventing half of one, and
a field that is structurally zero is a better statement of what this scanner is than a missing one.

**A 002 test was flaky and this task is what exposed it.** `test_the_background_task_flushes_on_its
_interval` waited for **200 iterations of `sleep(0.01)`** and then asserted regardless. That cannot
tell *"the task never flushed"* from *"this runner was busy and two hundred sleeps took less than
two seconds of its attention"* — and on a loaded CI runner it took the second path, failing with a
message about a `datetime` rather than about a timeout. It is now a wall-clock deadline with an
assertion that says which of the two happened. Fixed here rather than left: a test that fails for a
reason its own message denies is worse than one that fails.

## T16 — The safety guards and the destructive tests  ✅

- [x] **Changes:** the three guards of [plan §6.5](plan.md#65-the-guard-against-a-mass-delete) —
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

### Done — 2026-08-27

**A refusal message promised an escape the code did not provide.** Guards two and three both end by
telling the operator to *"scan again with removals confirmed"*, and `confirm_removals` only lifted
guard three. An operator who really had emptied a directory would have followed the instruction in
the message, been refused again by the same guard, and had no way forward but to delete the library
— which loses every identifier under it. Found by the test written *for the message*, not for the
code path. Guard one is still not liftable, and should not be: it refuses a root that is **broken**
rather than one that is empty, and nobody confirms a broken mount.

**The guards refuse rather than report.** A returned report can be ignored by a caller in a hurry;
an exception cannot, and it rolls the caller's transaction back on its way out — so "removes
nothing" is a property of the **transaction**, not of this function remembering to stop before the
write. Every assertion in the destructive tests reads the database afterwards, never the report.

**Each test removes exactly one guard and asserts the damage that arrives**, which is what the task
asked for and which is only possible because the guards are three separate functions. A single
`_check_everything` would have made every one of those tests prove that *some* guard fired.

The middle one is the one worth reading: with guard two removed and the threshold raised out of the
way, an emptied root makes the scan report **every file in the library** as missing. That count is
what T17 turns into soft deletions — which is precisely why the guard is written and proven before
the capability exists.

**They are removed by monkeypatching, not by a flag.** A scanner that shipped an off switch for its
safety guards would eventually be run with the switch off.

**T15's `test_a_root_that_lost_everything_still_removes_nothing` was rewritten here, and the rewrite
is the record.** Until the guards existed it asserted that the scan *completed and changed nothing*,
because the scanner had no removal path to take. It now asserts a refusal before anything is looked
at, which is a stronger guarantee — and the change is visible in the diff rather than silent.

**`ScanReport.missing` exists because guard three has to count it.** A number computed to make a
decision and then thrown away is a number nobody can check, and the same count is what T17 acts on.
It sits beside `removed`, which is still structurally zero.

**Guard three counts file-backed items only.** Containers come and go as their children do, so
counting them would make a renamed series look like a mass deletion and refuse a scan that was
doing exactly what it should.

## T17 — Removal and soft deletion  ✅

- [x] **Changes:** `removed_at` on a missing file; revival on return; the maintenance action that
  purges, which a scan never does.
- **Depends on:** **T16 green**
- **Verified by:** **AC-11** — delete a file, rescan, the item disappears from queries and its user
  data survives; restore the file and the item revives **with the same id**.
- **Note:** this task is what grants the scanner the ability to remove. It does not start before
  T16 passes.
- **Plan reference:** §6.6

### Done — 2026-08-27

**An already-removed item is not missing again**, and getting that wrong would have disarmed T16's
third guard permanently. The first version counted every item without a file as missing, including
the ones a previous scan had already marked — so after one large removal the guard would have fired
on **every subsequent scan, forever**, refusing to act on a loss that had already happened and with
nothing left to protect. A test holds it: rescan after a removal reports `(removed=0, missing=0)`.

**Purging lives in its own module, and a test asserts `scan.py` does not import it.** The same
shape argument as T15's repository having no delete method: a scan that merely *chose* not to purge
would be one refactor away from purging, and purging is the one operation here that a mount coming
back cannot undo.

**It has a grace period, which nothing asked for.** Thirty days, because the failure this really
protects against is an operator running a purge to tidy up *on the same afternoon* a share was slow
to mount — at which point the rows are gone and the next scan re-adds them with the same
identifiers but no record of ever having been away. `grace=0` is available for somebody who has
just cleared a library on purpose; nobody should get it by accident.

**Purging does not delete anybody's history, and that is the point of the missing foreign key**
arriving at the one moment a row really is deleted. It removes the thing a user pointed at, not
what they did with it — so if that file ever returns, the association returns with it. There is a
test for exactly that: purge, restore the file, and the play count is still three. That is what
makes purging safe enough to exist at all.

**Three tests from T15 and T16 were rewritten here, and the rewrites are the record.** One asserted
that a deleted file changed nothing; one asserted the repository's surface was three methods; one
asserted `removed` was zero. All three were true statements about a scanner that could not remove,
and all three are now different — visibly, in the diff, rather than by quietly ceasing to be
checked. The surface assertion still holds the line that matters: the six methods include two that
*mark* and none that *delete*.

**`update` still cannot reach `removed_at`.** Changing what an item **is** and changing whether it
is **there** stayed separate operations, so the T15 test that asserts it needed no change at all.

## T18 — Change detection  ✅

- [x] **Changes:** the `(size, mtime_ns)` signal and a `--deep` mode that ignores it.
- **Depends on:** T17
- **Verified by:** a modified file is re-examined and **keeps its identity and user data**; an
  unchanged file is skipped; `--deep` re-examines everything.
- **Note:** mtime is not trustworthy on every filesystem. The default is fast, the escape hatch
  exists, and neither pretends to be the other.
- **Plan reference:** §6.4

### Done — 2026-08-27

**Skipping the read was the easy half; not writing what the skip resolved to was the whole task.**
An unexamined music file resolved from its path alone hangs from an album named after its
*directory*, and the fixture's `spandau_ballet-through_the_barricades` track — the shape T1
measured on 413 of 5,814 real tracks — is exactly that case. The first working version skipped the
tag read, kept the stored row, and **still wrote the invented album beside the real one**, because
the resolver had produced it and nothing dropped it. So the reconciliation is two steps: keep the
stored row, then rebuild the set upwards from the file-backed items and drop any container nothing
ends up under. Without the second step, the second scan of every music library silently doubles
its albums. A test asserts the album name and that `added == 0`; removing either step fails it.

**The skip is safe for one reason, and it is worth naming: no file-backed identity depends on a
tag.** A `Movie`, an `Episode` and an `Audio` are identified by their path, so an unexamined file
resolves to the *same* item it did last time and the resolution is only ever used to decide which
row to keep. If 004 ever derives an identifier from a tag, this optimisation becomes unsound in a
way that is invisible until somebody's favourites move.

**A new signal has to be written back even when nothing else changed.** A file whose modification
time moved on its own — a `touch`, a restore, a metadata tool — is re-examined, finds nothing
different, and would be re-examined on *every* scan from then on if the report's "nothing changed"
were allowed to mean "nothing to write". A library full of those is an incremental scan doing a
full scan's work with nothing to show for it. Two rescans in one test hold it.

**The blind spot is measured, not hypothetical.** Writing new bytes of the same length and
restoring the time with `os.utime` produces a byte-for-byte identical `(size, mtime_ns)` on an
ordinary local filesystem — which is what `cp -p`, `rsync -a` and an unpacked archive all do. The
test reproduces it and then shows `deep` catching what the default misses. `shutil.copy` does not
preserve the time and `shutil.copy2` does, which is the difference between a copy that is noticed
and a copy that is not.

**Measured on the reference, and it settled what the signal is allowed to be.** No library item and
no media source carries a modification time: 120 `Movie`, `Episode` and `Audio` items requested
with `Fields=MediaSources` had no such property, and the pinned document has `DateModified` on
`FontFile` and `LogFile` only. `[probe: manual requests, Jellyfin 10.11.11, 2026-08-27]` So the
signal is private and creates no delta whatever it is — but `Size` **is** on the wire, which is why
an examined file's size is always written back. behaviours §2.17.

**The plan's contract named a `mode` argument.** It is one boolean. `confirm_removals` and
`removal_threshold` had already arrived at T16 as the guards' own arguments, and a single
enumeration would have had to carry every combination of the three. Plan §5 is corrected.

**`deep` does not lift the guards, and there is a test for it.** An operator reaching for a deep
scan because a share looked wrong is the last person who should thereby disarm the guard that
catches a share being wrong. It says how hard to look, not what to believe.

**One gap found and deliberately not closed here.** Spec §3.8's table says an emptied directory
removes the container item, and containers are never removed: `missing` counts file-backed items
only, by T16's design, because a renamed series would otherwise look like a mass deletion. A
childless `Series` or `MusicAlbum` therefore stays in the database for ever. That is a removal
question rather than a change-detection one, it has no acceptance criterion, and T21 has to either
give it one or record it as an accepted gap.

## T19 — The root-move test  ✅

- [x] **Changes:** `tests/library/test_root_move.py`.
- **Depends on:** T18
- **Verified by:** **AC-10** — scan at one path, move the whole tree, reconfigure the root, rescan:
  every identifier unchanged and no user data orphaned.
- **Note:** this is the test that proves the relative-path decision, and it fails loudly against an
  absolute-path derivation. It is the difference between a remount costing nothing and costing every
  client's favourites.
- **Plan reference:** §1, §8.2

### Done — 2026-08-27

**The claim this whole feature is built on had no provenance.** Plan §1 and spec §3.6 both said
"the reference derives item ids from the absolute path" and neither cited anything; behaviours §1.4
had the derivation with a `[source: …]` citation, which is the weakest of the three forms — it says
what the code appears to do, not what the server did, and T16 is the task that learned what happens
when those differ. So the task began by measuring it, and the measurement is now
`tools/probe_item_identity.py`: recomputing the documented expression from each item's own reported
path reproduced **448 of 448** live ids across `Movie`, `Episode`, `Audio`, `Series` and
`MusicAlbum`. The claim was right. It is now measured rather than believed, and it stays measured.

**Containers are path-keyed on the reference too**, which nobody here had said. A `Series` and a
`MusicAlbum` derive from their *directory*, not from their name — so on the reference a root move
takes the containers with it, while under Atrium's rules those two derive from names and were never
at risk. The test favourites both an `Episode` and a `Series` for exactly that reason: a test that
favourited only the container would pass against the bug.

**A measurement that says what it cannot answer.** The reference used has
`EnableCaseSensitiveItemIds` **set**, which is why its ids reproduce from the path *verbatim* — 447
of the 447 paths containing an uppercase character. That confirms behaviours §1.4's description
exactly, and it also means this server cannot tell us the reference's **default**, which is what
spec §3.6 and OQ-2 asserted without provenance when they said Atrium's case-insensitive default was
"what the reference does". T19 replaced that with a hedged claim carrying a `⚠️ UNVERIFIED` marker,
which **T21 corrected again** — the claim is not made at all now, and the unmeasured half is OQ-8.
The probe still says in its own output that a server with the flag set cannot answer it.

**The move is not merely survivable, it is invisible.** The report is asserted whole:
`added`, `updated`, `removed`, `revived` and `missing` are all zero. A scanner that produced the
right identifiers by adding every item again and removing every old one would satisfy "the
identifiers are unchanged" and would still have discarded the user's state, because the removal is
what user data is keyed against surviving. `examined == 0` is the T18 half — renaming a directory
does not touch the files' modification times, so a remount re-reads nothing either.

**Two controls, because a test that cannot fail proves nothing.** One computes what the identifiers
would be under an absolute-path key over both locations and asserts the two sets are disjoint, so
"unchanged" is a result rather than an observation that nothing was asked. The other asserts that
joining the root to each stored path lands on a real file — a scanner can derive from a relative
path and still *store* an absolute one, and everything else would pass until somebody used the
stored path to rebuild identity. The first version of that test asserted a string property instead
and **survived the mutation**; the version that asserts the invariant does not.

**Verified by mutation, not by passing.** Keying identity on the absolute path fails 9 of the 10
tests here; the tenth is the pure computation, which is supposed to be independent of the
implementation. Worth recording: under that mutation the rescan does not quietly rewrite the
library — guard three refuses it, because a root move looks exactly like a mass deletion. The
guards were written for an unmounted share and they catch this too.

**A library with two roots has two independent relative namespaces**, and one test moves only one
of them. A derivation that happened to be relative to the *first* configured root would pass every
other test in the file.

## T20 — Scan reporting  ✅

- [x] **Changes:** progress and the summary `ScanReport` carries — added, updated, removed, and
  files skipped **with the reason**.
- **Depends on:** T17
- **Verified by:** a scan over a fixture containing an unreadable file and an unparseable name
  reports both, each with its reason, and neither aborts the scan.
- **Plan reference:** §3, §7

### Done — 2026-08-27

**"Reports both, each with its reason" cannot be one list, and that is the task.** An unreadable
file produced **no item**; an unparseable name produced one that is sitting in the library now. An
operator told "2 files skipped" goes looking for two missing films and finds one, having spent the
search on something that is not missing. So the summary has two lists — `skipped` and `noticed` —
and `library/report.py` opens by saying why. The vocabulary for each lives with whatever produces
it: `Skip` is the walker's and `Notice` is the resolver's.

**The fixture caught a real bug before any test did.** The first version computed notices in
`report.py` from the finished items — every `Episode` with no `index_number` — which looked clean
and kept the resolver pure. Adding one unparseable name to the fixture reported **two** notices,
and the second was `The Daily Show - 2024-01-31.mkv`. A daily show's episodes are ordered by their
date and need no number; an `Item` carries no date, so from the items alone "the name said nothing"
and "the name said a date" are the same thing. Only the module that read the name can tell them
apart. Left uncaught, every scan of a library with a daily show in it would have reported every one
of its episodes as unparseable — the kind of noise that gets a whole category ignored.

**Plan §7 named a failure that does not happen.** It said an unreadable file inside a readable root
is skipped, counted and reported. It is not: a `chmod 000` file **stats perfectly well**, and stat
is all the walk does, so it becomes a candidate, becomes an item, and is found to be unreadable by
whoever first opens it — 008. What *is* detectable is a file whose stat raises (a dangling symlink)
and a directory that cannot be listed. A test holds all three, including the one that is scanned,
because a row that is wrong in this direction is one an implementer writes a check for and never
sees fire.

**Progress reports roots during the walk, not files, because it does not know how many files there
are** — that is the number the walk is computing. `Progress.total` is `None`-able and `fraction`
returns `None` rather than a number, since a progress bar that invents a denominator jumps
backwards, which is worse than one that admits it does not know. Resolution is reported once, after
the fact: `resolve` is a single pure call, and animating a made-up gradient across it would be the
exact dishonesty this module exists to avoid.

**A scan must not be destroyed by its own instrumentation.** A progress sink is somebody else's
code, and a scan that died because a terminal went away would roll back a transaction that had
nothing wrong with it. A sink that raises is **disabled for the rest of that scan and logged
once** — once, because a sink that fails on the first call fails on all of them, and a scan of a
large library would otherwise write one traceback per file to explain one broken callback.

**A refused scan returns no summary and reports no progress.** There is no summary of a scan that
did not happen, and the guards refuse before the walk, so a sink hears nothing at all rather than
hearing a phase begin and then silence.

**`ScanReport` moved to `library/report.py`**, which plan §3 has listed since the plan was written
and which did not exist until now. `scan.py` imports it; the tests import it from where it lives
rather than through a re-export, so the module boundary is real rather than decorative.

**Verified by mutation.** Noticing every numberless episode, calling a broken sink more than once,
letting a broken sink raise, and reporting a file count during the walk each fail at least one
test.

## T21 — The acceptance map for 003  ✅

- [x] **Changes:** `FEATURE_003` in `tests/conformance/test_acceptance.py`, and its entry in the
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
- **Note:** T18 left one row of [spec §3.8](spec.md#38-scanning-and-change-detection) unimplemented
  on purpose — an emptied directory does not remove its container item, because `missing` counts
  file-backed items only and a renamed series would otherwise look like a mass deletion. No
  acceptance criterion covers it. This task either gives it one or records it in
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) as an accepted gap;
  closing it without an answer is what the definition of done exists to prevent.
- **Plan reference:** §8, [002 T18](../002-authentication-users-and-sessions/tasks.md)

### Done — 2026-08-27

**The restructure paid off, and that is worth checking rather than assuming.** 002 T18 turned this
file from one feature's map into a table of them on the bet that 003 would then be one entry and one
dictionary. It was: `FEATURES` gained a line, `FEATURE_003` was written, and **not one check below
them changed**. A refactor whose payoff nobody verifies is a refactor that might have been a waste,
so the file now says so in its own docstring.

**Thirteen criteria, forty-nine test names, and the map is the widest of the three** — because 003
has no HTTP surface, so its criteria are proven at four levels instead of one: the naming corpus
(pure), the resolver (pure, fixture paths), a scan into a real database, and the sort-name table.
AC-4 to AC-9 each name `test_the_corpus` **and** a resolver test, because the corpus proves the
parser and the resolver proves the scanner uses it — the same gap AC-13 exists for.

**The corpus and the map cannot drift apart silently**, which was luck rather than design and is
worth naming: `test_the_acceptance_criteria_that_live_here_are_covered` asserts that every one of
AC-4 to AC-9 is named in some row's *reason*, so a criterion that lost its rows fails in the corpus
before anybody reads this map.

**The gap T20 found is closed the third way.** Spec §3.8's table said "directory emptied → remove
the container item" from the day the specification was written; no acceptance criterion covered it,
and nothing implemented it. Three ways out: implement it now, in a feature whose removal semantics
were settled at T17 and whose guards do not watch below the root; delete the row and pretend it had
never claimed anything; or say plainly what happens and name who closes it. The third. The reason it
is not a bug is the argument itself — **removing a container is the judgement §3.8 refuses to make
about a root, made one level down where no guard is watching**, and the observable half is a query
deciding not to return an empty container, which is 005's and costs one predicate.
[behaviours §5.2](../../docs/compatibility/behaviours.md#52-a-container-that-has-lost-every-file-is-not-removed),
and 005's debt is written down.

**Two open questions stay open, and the definition of done required a written reason rather than an
answer.** OQ-6 and OQ-7 each need a *measurement this repository cannot take today* — a library with
explicit sort titles, and names carrying characters the measured set does not contain. Both change
the **ordering** of names that are already scanned, found and playable, so a wrong answer is a list
in a slightly wrong order rather than a missing item. Closing either by guessing would turn
"unmeasured" into "asserted", which is the whole failure the provenance rule exists to prevent. §7
now says that, in the specification, rather than leaving it to be inferred from two blank cells.

**One claim in the definition of done was checked rather than ticked**, and it is the one that could
have been quietly false: the naming corpus's `AWAITING` table is **empty**, so no row is parked
behind an `xfail` — T10 to T13 each deleted their own line as the task list required. `strict=True`
is what made that visible: a lenient `xfail` that started passing would have been green and silent.

**Two provenance defects were found in this feature's own work, and both were T21's to fix.**
Writing an audit of the project's claims meant re-reading them, and the two worst kinds turned up
in what T19 and T21 had just written:

* **A fabricated citation.** behaviours §5.2 carried
  `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` beside a claim **nobody has measured** — the
  version and date copied off a neighbouring entry. That is worse than no citation at all: no
  citation is visible, and a real-looking one turns "we believe this" into "somebody measured this
  in June" for every future reader. It is gone; the entry now says it is unmeasured, why it cannot
  be measured read-only, and what would answer it.
* **A hedged claim where an open question belonged.** T19 wrote "believed to be what the reference
  defaults to … `⚠️ UNVERIFIED`" into spec §3.6, and the constitution says an unverified claim
  *blocks the specification from leaving draft status* — so marking 003 `Implemented` in this very
  task would have contradicted it. The resolution is not to delete the marker but to stop making
  the claim: §3.6 states Atrium's own default as the decision it is, and **OQ-8** records the
  reference's default as unmeasured. A question you have not answered is a supported state; a claim
  you cannot support is not.

Both were introduced by this session and caught by this session, which is the argument for the
audit existing rather than for trusting the next reader to notice.

**`spec_status_actual` moved with the status.** Both `plan.md` and `tasks.md` carry a gate field
naming what they were written against; leaving those at `Accepted` while the artefact above them
said `Implemented` would make the gate record a state that no longer existed.

---

## Definition of done

- [x] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing
      test — all fifteen, by name, in `FEATURE_003` (T21). *(Count corrected on 2026-09-05 by the 2026-09-04 audit's C9, which found it stale in 10 of the 12 features: this is a live claim about §5, not a record of the tick — 007 T13's precedent, and it is held by a test now.)*
- [x] The naming corpus passes in full, **carries no `xfail` marker**, and every row states the
      reason it exists. Checked rather than assumed: `AWAITING` is empty, which is what
      `test_no_row_is_parked_behind_an_xfail` asserts.
- [x] The three destructive-failure tests pass, and each fails when its guard is removed —
      `test_without_guard_one…`, `…two…`, `…three…` in `tests/library/test_scan_guards.py`.
- [x] Scanning twice, and scanning into an empty database, produce byte-identical identifiers
      (AC-2, AC-3).
- [x] Moving a library root changes no identifier (AC-10, `tests/library/test_root_move.py`).
- [x] No fixture file is a copyrighted work, and the fixture generator needs nothing outside the
      locked dependency set — `test_the_generator_needs_nothing_outside_the_standard_library`.
- [x] The scanner writes sort names **through the dispatcher**, asserted against the database and
      not only against the derivation table (AC-13's three `test_scan` entries).
- [x] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same change.
      The `amended:` lines in both name the tasks that changed which sections.
- [x] Any newly measured reference behaviour is in `docs/compatibility/behaviours.md` with
      provenance — §2.15 (T8), §2.16 (T18), §1.4's outside confirmation (T19), §5.2 (T21, marked
      `⚠️ UNVERIFIED` because it cannot be measured read-only).
- [x] **Every open question in [`spec.md` §7](spec.md#7-open-questions) is either resolved with
      provenance or still open with a written reason** — **OQ-1 and OQ-5 resolved at T1**, OQ-2 at
      T7, OQ-3 at the sort-name probe, OQ-4 at T11. **OQ-6, OQ-7, OQ-8 and OQ-9 stay open**, each
      with the reason written into §7: all four need a measurement this repository cannot take
      today, and none of them changes what is found — two change ordering, one waits on 004 to read
      tags, and one is a fact about the reference that §3.6 no longer claims. OQ-9 exists because
      T19 wrote a hedged claim into §3.6
      instead of an open question; a question that is closed without an answer is the failure this
      line exists to prevent, and a claim that is asserted without one is the same failure with
      better manners.
- [x] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

004 needs the `MetadataSource` seam to be genuinely substitutable, or music identification lands as
a rewrite rather than an implementation — and, from T18, it needs to know that the seam is **not
asked about a file whose `(size, mtime_ns)` has not moved**, so a provider whose answer can change
without the file changing will not be consulted, and an identifier derived from a tag would make
the skip unsound. 005 needs `sort_name` indexed and library visibility
joinable. 008 needs somewhere to record that a file wants probing without 003 probing it — and, from
T2, it needs to generate its own decodable fixtures, because 003 generates none. All four are cheap
here and expensive later.

**005 also inherits the one thing 003 decided not to do.** A container whose files have all gone
keeps its row, so `/Items` has to decline to return a container with no visible children
([behaviours §5.2](../../docs/compatibility/behaviours.md#52-a-container-that-has-lost-every-file-is-not-removed)).
A predicate in one query, rather than a removal written into the database at scan time by a scanner
with none of §6.5's guards watching it.
