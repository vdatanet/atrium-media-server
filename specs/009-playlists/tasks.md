---
feature: 009-playlists
title: Playlists — tasks
status: Accepted
created: 2026-08-31
updated: 2026-09-01
accepted: 2026-08-31
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 009 — Tasks

Fourteen, ordered so that the two things most likely to be wrong — the move arithmetic and the
visibility of a row with no library — are proven before anything routes to them.

## What the gate changed

Reviewing this list against the code it names found three things, and the second is the one that
would have shipped a leak.

**1. `Playlist` joining `ItemType` is not free, and 005 said so in a docstring nobody re-read.**
Plan §1 prices the "a playlist is a row in `items`" decision at *"migration 0008 and nowhere else"*.
There are three structures that assert themselves total over a type set, and adding a member to the
enum breaks all three:

> *T3 found **five**, and the two missing ones are assertions rather than maps — the domain's own
> two-way partition of `ItemType`, six lines below the first assertion this list cites, and
> `test_migration_0003.py` inserting one row of every type against the constraint 0008 replaces.
> Its Done note carries both, and the list below is left as it was written.*

- `PARENT_OF` is total over `IN_THE_TREE`, asserted by `tests/unit/test_domain_items.py:138`, and
  `IN_THE_TREE` is *everything that is not a by-name row*. A playlist has no parent and the scanner
  never arranges one, so **`IN_THE_TREE` excludes it** — which is what that constant's own docstring
  already means by "everything the scanner arranges into a tree". `tests/unit/test_migration_0002.py`
  iterates the same set against 0002's type constraint, and excluding the playlist keeps that test
  honest: `Playlist` is 0008's value, not 0002's.
- `RULE_OF` is total over `ItemType` itself, asserted by `tests/library/test_identity.py:53`, and a
  playlist's identifier is minted rather than derived (plan §1). It gains a **sixth rule that says
  so** rather than an exemption, so the map stays total and the mapping keeps its meaning.
- `MEDIA_TYPE_OF` answers a type-level question that a playlist answers per instance. 005's own
  comment on that map is the finding: *"A `Playlist` answers `Audio` on the measured server —
  derived from its contents rather than from its type — which is 009's problem and is why
  `Playlist` is not a member of `ItemType` here."* The map gains the reference's own fallback and
  the emitter prefers the row's stored `media_type` (plan §4.2).

**2. Every playlist would have been visible to every user.** `ItemQueries._visible_to` is four
clauses, and the library one — `_library_permitted` — **exempts rows with no library**, because a
by-name row is not in one. A playlist has no library either (plan §4.1), so it would have passed
that clause for every caller, and `/Items?includeItemTypes=Playlist` would have listed every user's
private playlists to everybody. Plan §1's *"the two divergences are two calls to code that already
exists"* is true of the playlist route and false of `/Items`: `_visible_to` needs a **fourth sibling
clause**, written the way `_by_name_is_referenced` is, and AC-15 has to be asserted through `/Items`
and not only through a direct fetch. T6 is that clause, and it is placed before every route that
could expose it.

**3. Both corrections are in the plan in this same change**, §1 and §6.5. The plan said the cost was
one migration; it is one migration, four maps and a clause.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — `domain/playlists.py`: three permission functions and the move, pure

- [x] **Changes:** new module. `may_read`, `may_edit`, `may_delete` over an owner, a share list and
  `is_public` — three functions rather than one flag, because only `may_delete` reads
  `is_administrator` and that asymmetry is the spec gate's finding (spec §3.7). `moved(order,
  entry, new_index, visible)` implements plan §6.4: the entry lands immediately before the visible
  neighbour's position in the full order, which collapses to *"insert at `new_index` after
  removing"* when the caller sees everything. Refusals for a negative index and one past the
  visible length are raised here, not in the route (plan §6.4.1).
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_playlists_domain.py -q` — **the 25-row matrix**
  (every source × target on `[A B C D E]`), `moved(0 → 3) == B C D A E` among them, plus the
  boundary rows: `new_index == 5` last, `6` refused, `-1` refused, an absent entry with an in-range
  index returning the order unchanged. **And the second matrix**: the same 25 pairs where the
  caller cannot see `C`, asserting the moved entry's position in the *full* order.
- **Spec reference:** §3.5, §3.7; plan §5, §6.4

> **Done (2026-08-31).** *Plan §6.4's block, executed as written, produces the reading the probe
> exists to rule out.* It removed the entry from `full` and not from `visible`, so the visible
> neighbour is one position too early and the discriminating pair gives `B C A D E` — the
> pre-removal reading spec §3.5 measured as **wrong** — and its `new_index == len(visible)` has to
> be `>=` once the reduction happens. The paragraph directly under the block was already assuming
> the removal the block did not do. With the fix reverted, 23 rows of this task's test fail, 10 of
> them in the measured matrix.
>
> *And the second matrix has no reference answer, where the plan said it was reproducing one.*
> Plan §6.4 called the two-list rule *"the observable result"* of the reference's arithmetic. The
> reference bounds `newIndex` against the entries it shows — that part is parity, and it is why an
> index one past the count is the last position — but it takes the landing neighbour's position in
> the stored order **before** the entry is removed, so a downward move by a caller who sees less
> than the whole lands one position short of what they asked for (moving `A` to index 2 of a list
> whose `C` is hidden leaves `A` at index 1 of that caller's view), and it happily reorders an
> entry that caller was never shown. Neither is reachable against a reference server: the entries
> it hides are hidden by a parental-rating check and never by library access, which is
> behaviours §3.17's own finding. So the rule is Atrium's, argued from that divergence rather than
> transcribed, an omitted entry is answered as an absent one, and spec §3.5, AC-17, plan §6.4 and
> behaviours §3.17 say so.
>
> *The 25-row matrix was a model derived from one measured pair.* OQ-1 measured `0 → 3` and the
> boundary battery measured five more, all with source `A`; the other 24 pairs were arithmetic
> nobody had asked the server about. `probe_playlist_move.py` gains all thirty (source, target)
> pairs, targets 4 and 5 included, one fresh playlist each: the post-removal reading reproduces
> the reference on every one, and the one-position clamp is a property of every source rather than
> of `A`. The test table is that transcription rather than a re-derivation of the model
> `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`.
>
> *Two smaller things.* `moved` raises `MoveIndexOutOfRangeError` — a `ValueError` subclass the route
> catches by name, because the plain `ValueError` beside it is for a `visible` that is not a
> sub-sequence of `order`, which is T7 or T11 handing the two lists in the wrong order and is not a
> client's `400`. And `domain/playlists.py` is the first domain module in the project to raise
> anything at all.

## T2 — `ForbiddenError` answers the reference's body, and 005's test moves with it

- [x] **Changes:** `compat/errors.py`'s `forbidden_handler` returns `controller_error(403)` instead
  of `empty_error(403)` — the shape already exists in that module, written by 002 for the
  authentication refusals, down to setting the content type as a header so Starlette cannot append
  a `charset` the reference does not send. The `⚠️` in `ForbiddenError`'s docstring goes, because
  the thing it says is unmeasured has been measured
  `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`.
  `tests/unit/test_items_route.py::test_user_id_of_somebody_else_is_the_empty_403` asserts
  `content == b""` today: the assertion and the test's name both change.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_items_route.py tests/conformance -q`. The bytes are
  asserted, not the status: `answered.content == b"Error processing request."` and
  `answered.headers["content-type"] == "text/plain"`. A grep for `403` across `tests/` has to come
  back with no other assertion of an empty body.
- **Spec reference:** §3.7, AC-19; plan §2

> First on purpose, so every refusal test written after it asserts the right bytes from the start.

> **Done (2026-08-31).** *The cell this task's own verification asserts had never been measured,
> and measuring it split one `403` into two.* The task asks for
> `headers["content-type"] == "text/plain"` on the strength of a probe that printed
> `add_body[:40]` and threw the headers away — a forty-byte slice of a body cannot see a content
> type, and cannot tell an **empty** body from a **body-less** refusal. `probe_playlist_visibility`
> gains a `shape` helper and a three-row battery that prints status, content type, body length and
> body for every route Atrium answers through this one handler. The controller refusal is
> `403 · text/plain · 25 bytes` as claimed — and the elevated controller the music client renames
> through, spec §3.8, is **`403` · no content type · 0 bytes**, because an authorization policy
> refuses it before any controller runs
> `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`.
>
> So spec §3.7's *"every controller-level refusal"* and §3.8's *"with an empty body"* were never a
> contradiction — they are the two shapes — and the definition of done's *"`ForbiddenError`'s body
> is the reference's"* is true of the first only. **T13 is the task that changes:** its rename
> cannot raise `ForbiddenError` any more, because `ForbiddenError` now says the sentence and that
> route must say nothing.
>
> *Two of the four raise sites are not the refusal that was measured, and the plan promised one of
> them would not move.* Plan §2 says *"what does not move is 002 OQ-5's three authentication
> refusals"*, and OQ-5's third row — a live token whose account was disabled after it was issued —
> is `api/deps.py:132`, raising this very class. It moved: from the empty shape by analogy with the
> empty `401`, to the sentence by analogy with the measured `403`, still unmeasured either way, and
> its test asserted `content == b""`. That is a **second** test asserting the old body, where the
> task named one and plan §9's risk row predicted exactly this ("a *test* asserting the old empty
> body somewhere the grep misses"). The row is marked fired.
>
> *And the fourth site is a route the reference does not refuse at all.* `api/users.py` answers
> `403` to one user reading another; measured, a restricted non-administrator naming the
> administrator is answered **`200` with that administrator's whole object, `Policy` included** —
> the same disclosure 002 T11 found on `/Users/Public`, by a second road. 002 §3.7 states that
> `403` with no provenance. **A decision is needed and was not taken here:** whether Atrium
> replicates the disclosure (Principle I) or keeps the refusal belongs to 002's route and to the
> user, and so does how T13 gets the empty shape — a second exception class, or the route writing
> its own response the way the delete `401` does. Both are recorded in behaviours §1.11, spec §3.7,
> §3.8, AC-18, AC-19 and plan §2 and §6; neither is improvised.

## T3 — The type joins the enum, and the three maps that are total over it

- [x] **Changes:** `ItemType.PLAYLIST`. `IN_THE_TREE` excludes it (gate finding 1), so `PARENT_OF`
  needs no row and the tree assertions keep their meaning. `library/identity.py` gains
  `IdentityRule.MINTED` — *"allocated at creation; a playlist is the one item a rescan cannot
  rebuild"* — and `RULE_OF` maps `PLAYLIST` to it, with `derive` refusing to be called for that
  rule rather than silently producing something stable-looking. `MEDIA_TYPE_OF` gains `Audio`, the
  reference's own fallback for a playlist with nothing in it, and `api/item_dto.py` prefers the
  stored `media_type` for a playlist row (T4's column).
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_domain_items.py tests/library/test_identity.py
  tests/unit/test_migration_0002.py -q` — the three totality assertions pass **unchanged**, which
  is the point: a member was added and no test had to be weakened. Plus a row asserting `derive`
  raises for `MINTED`.
- **Spec reference:** §3.2, §4; plan §1, §4.2

> **Done (2026-08-31).** *There are **five** structures total over the type set, not three, and
> neither of the two nobody enumerated is a map.* That is why reading the maps did not find them:
> both are assertions.
>
> - **The domain's own partition.** `test_domain_items.py:212` asserts
>   `set(ItemType) == IN_THE_TREE | BY_NAME` — *"No third category, and nothing in both"* — six
>   lines below the assertion the gate cited, in the same file. `IN_THE_TREE` excluding the
>   playlist is exactly what makes a third category exist, so the two statements cannot both hold.
>   It is now a three-way partition over a named `USER_CREATED` set, which keeps it a partition: a
>   fifteenth type still has to be placed rather than excused, where
>   `IN_THE_TREE | BY_NAME | {PLAYLIST}` would have turned it into a list of exceptions.
> - **`test_migration_0003.py`'s constraint test**, which inserts **one row of every `ItemType`**
>   and asserts they all land. Its own docstring says *"0003 is now the revision that owns the
>   whole of `ItemType`"*, and 0008 is about to take that ownership away. It splits rather than
>   shrinks: every type 0003 lists inserts, and the one it does not is asserted **refused** with
>   `ck_items_type` named — so the accounting is still total, and a fifteenth type breaks it the
>   way the fourteenth did. It is the one test in the repository that would have failed at T4
>   instead, with a rebuild in flight.
>
> *The task's third structure needed no code at all, and the first two needed less than it says.*
> `PARENT_OF` and `PRODUCED_BY` need no row, as stated — but so does `_DEPTH` in `library/scan.py`
> and `CHAIN_OF` in `metadata/merge.py`, both of which are total over `IN_THE_TREE` and both of
> which the exclusion carries for free; that is what the exclusion buys. And `RULE_OF`'s new
> `MINTED` row does not need `derive` taught to refuse: `_require` already compares the type's rule
> against the rule the function implements, so one map row refuses all five derivations at once.
> There is no dispatcher called `derive` in that module to teach — `derive` is the hash primitive
> in `compat/guids.py`, which knows nothing about types.
>
> *`MEDIA_TYPE_OF`'s new value is right and the sentence that justified it was wrong.* 005's
> comment said a playlist's `Audio` is *"derived from its contents rather than from its type"*,
> which cannot be true of a value a type-level map holds. Measured: the value is decided **at
> creation** and never revised — a playlist created empty answers `Audio` after a film is added to
> it, one created from a film answers `Video` after a track is, and the body's own `MediaType`
> outranks the contents outright
> `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`. So the map's entry
> is the *fallback* — exact for a playlist created empty, wrong for every other — which is what
> makes plan §4.2's column the right shape rather than a convenience.
>
> *And that fallback has a reader the plan did not count.* `db/item_queries.py`'s `_types_of_media`
> inverts `MEDIA_TYPE_OF` to answer `mediaTypes=`, on the argument its own docstring states —
> *"there is no `media_type` column: it is a property of the type"* — which 009 makes false. The
> reference filters playlists by the stored row: `mediaTypes=Audio` returns the audio playlist and
> not the video one, and `mediaTypes=Video` the reverse. Reading the fallback claims **every**
> playlist for `Audio` and none for `Video`. Nothing observes it until T4 stores a playlist, and
> closing it needs T4's column — so it is named in the code, in spec §4 and in plan §4.2, and
> **left undecided**: it is an accepted gap or one more clause on the listing, and no task in this
> list owns it. **The same ordering blocks this task's last clause**: `api/item_dto.py` cannot
> prefer a column that T4 has not created, and T4 depends on T3. **Reassigned to T4 on 2026-08-31**, which is where it was written; plan §4.2 says so too.
>
> *Two smaller things, both about tests that would have passed for the wrong reason.*
> `test_a_real_kind_this_version_cannot_produce_narrows_to_nothing` asked `includeItemTypes=Playlist`
> and got zero rows because v1 could not produce the type; it now gets zero rows because the world
> holds no playlists, which is a different mechanism with the same answer. It asks `BoxSet`, and a
> new test asserts the other half — `Playlist` binds to a type and records no ignored token. And
> `MediaType: Nonsense` on creation is a **`400`** in the validation shape rather than a dropped
> token, which is a refusal spec §3.2's error table did not have and T8 has to answer.

## T4 — Migration 0008: two constraints rebuilt, three tables

- [x] **Changes:** `db/migrations/versions/0008_playlists.py` and `db/models.py`. The `items`
  rebuild through `batch_alter_table(copy_from=…, recreate="always")`, as 0004 did for
  `item_artists`: `ck_items_type` gains `'Playlist'`, and `ck_items_by_name_has_no_library` becomes
  *the five by-name types **or** a playlist*. Then `playlists`, `playlist_entries` and
  `playlist_shares` exactly as plan §4.2–§4.4 — no entry-identifier column, no foreign key on
  `item_key`, `ordinal` indexed and not unique. **And the two clauses T3 could not place**
  (reassigned 2026-08-31): `api/item_dto.py` prefers the stored `media_type`, which is this
  task's because it reads this task's column; the `mediaTypes=` filter goes to T6.
- **Depends on:** T3
- **Verified by:** `uv run pytest tests/unit/test_migrations.py -q`, up **and** down. The rebuild
  test seeds `items` with one row of every type *and* the rows that reference them —
  `item_user_data`, `item_genres`, `media_streams` — migrates, and asserts every row, every index
  and every foreign key survives. A rebuild that silently drops a child table's rows is the
  failure this task exists to make impossible.
- **Spec reference:** §4; plan §4, §9's first risk

> **Done (2026-08-31).** *The rebuild does drop a child table's rows — every one of them — and
> `PRAGMA foreign_key_check` comes back clean afterwards, so nothing anywhere says so.* Measured
> before a line of the revision was written. Batch mode rebuilds a table by `DROP TABLE`-ing the
> original, and SQLite performs an implicit `DELETE FROM` before the drop **when foreign keys are
> enforced** — which `db/engine.py` does on every connection. That fires `ON DELETE CASCADE` on all
> six tables pointing at `items.id`: seeded with one row of every type and one row in each child,
> a 0007 → 0008 upgrade comes out with `item_sources`, `item_genres`, `item_studios`,
> `item_people`, `item_artists` and `item_images` **empty**, no exception, no orphan.
>
> *Two module docstrings asserted the opposite, and neither had been measured.* `db/schema.py` said
> a migration with foreign keys off "is exactly the migration that leaves an orphan behind" and
> `env.py` said opening a second connection "would migrate a database with foreign keys off" as
> though that were the hazard — and `tests/unit/test_db_schema.py` had a purpose-built revision
> asserting `PRAGMA foreign_keys == 1` during the run, so the wrong claim had a passing test under
> it. Enforcement is the hazard. `schema.migration_connection` is the fix and every path that runs
> a migration goes through it — the server's startup, `uv run alembic upgrade head` (the command
> operators are told to run), and the test harness — with the pragma off, `PRAGMA foreign_key_check`
> **before** the commit so "off" does not trade a silent deletion for a silent orphan, and the
> restore in a `finally`. The restore has to be after the commit: the pragma is a no-op inside a
> transaction, so putting it back where it was turned off reads `0` and hands the pool a connection
> that enforces nothing for the rest of the process.
>
> *This was never 0008's bug alone.* 0003 rebuilds `items` the same way and `item_sources` exists
> from 0002, so any populated 0002 database upgraded to 0003 lost every item's file paths. Nothing
> caught it because `test_migrations.py` compares **schemas**, and rows are invisible to it.
>
> *The task's own list of "the rows that reference them" names two tables that cannot be affected
> and misses five that can.* `item_user_data` and `media_streams` carry no foreign key to `items`
> at all — 007's deliberate decision and 008's keying by path — so a test seeded with only the
> three named would have asserted survival of one at-risk table out of six. The seed is now the
> schema's own list, and the guard-removed test asserts **exactly** which six are emptied, so a
> seventh cascading child added later changes that set and fails.
>
> *And T3's split test would have inverted in silence, exactly as its note predicted.*
> `test_migration_0003.py`'s "0003 refuses `Playlist`" runs against the fixture that migrates to
> **head**, so it asserted 0003's constraint only for as long as head was `0007`. At `0008` it
> stopped raising. It now walks the database back to `0007` before asking, and says which revision
> it is asking.
>
> *Two smaller things.* The downgrade deletes the playlist rows, which is real data loss and the
> only honest option — a `Playlist` cannot exist under 0007's `ck_items_type`, and unlike every
> other association this project rolls back, a playlist is the one thing a rescan cannot rebuild;
> the docstring says so. And `ck_items_by_name_has_no_library` is an **equivalence**, so widening
> it needed both directions tested: a playlist with a library is refused, and a film without one
> still is.

## T5 — The fixture world gets playlists

- [x] **Changes:** `tests/fixtures/query.py` seeds four: one owned by `everyone`, one shared with
  `restricted` **with** `can_edit`, one shared **without** it, and one holding items from two
  libraries — which is AC-17's whole case. The users this needs already exist (`everyone`,
  `restricted`, `nobody`), which is the correction the plan gate made to plan §8. **Five were
  seeded**, and the fifth is the public one this line does not name — its Done note says why.
- **Depends on:** T4
- **Verified by:** `uv run pytest tests/unit -q` — the world builds, and a test asserts the
  two-library playlist really does hold an item `restricted` cannot see, because a fixture that
  quietly holds two visible items would make T6 and T9 pass for the wrong reason.
- **Spec reference:** §3.7; plan §8

> **Done (2026-08-31).** *Four playlists cannot hold five classes, and the missing one is the class
> T6's own verification asks for.* Spec §3.7's table has four ways to reach a playlist and the four
> this task lists cover three: an owner, a shared editor, a shared reader. **`IsPublic` has no
> row** — and T6's verification says *"the public one is present for both"*, which nothing in the
> world could have answered. The world seeds five. The public one holds the three tracks rather
> than films, so its stored `media_type` is `Audio` where the other four are `Video`: the
> `mediaTypes=` gap T4 handed T6 is a difference between a per-row value and a type-level map, and
> a world whose playlists were all one media type could not tell the two apart.
>
> *And the two-library playlist has to be **shared**, or AC-17 has no reader.* The task lists it
> beside the shared ones as though it were a fourth independent world. It is not: `restricted` is
> the only user who cannot reach every library, so a two-library playlist that is neither theirs,
> nor shared with them, nor public is a playlist they get `404` for — the omission has nobody to
> omit anything from. AC-17's second half is stricter still: *"that reader's `Move` indexes the
> list they were given"* needs that reader to be **allowed to move**, which is a share with
> `can_edit` and nothing else. It is the shape the reference itself produces
> `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`, and its hidden entries
> are **interleaved**: with the unreachable ones appended, both readings of §3.5's arithmetic give
> the same answer and AC-17's second half would pass against either.
>
> *The probe that checked those two also answered a third question and found a `403` nobody had
> measured.* A share with `CanEdit: false` **is** stored by the create body and **is** a reader who
> is refused the move — so AC-14's second half has a world — and the refusal is `403` with **no
> content type and no body**. That is the *body-less* shape, from a permission test the playlist
> controller makes **itself**, which contradicts behaviours §1.11's rule as T2 wrote it two commits
> ago: the split is not *controller versus policy* but *thrown versus returned* — an exception is
> rendered by the error middleware and carries the 25 bytes, a `Forbid()` result carries nothing,
> and both happen inside the same action
> `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:421-427 @ v10.11.11]`
> `[source: Jellyfin.Api/Helpers/RequestHelpers.cs:77-81 @ v10.11.11]`. **T10, T11 and T12 are the
> tasks that change:** every `may_edit` refusal they ship is the body-less shape, so they need
> T13's second exception class rather than `ForbiddenError`, whose body is now the sentence. Spec
> §3.7, AC-13, AC-14 and behaviours §1.11 say so; a note is on each of those tasks.
>
> *Two assertions elsewhere in the suite went red the moment the world held a playlist, and both
> are the leak rather than the fixture.* `test_the_restricted_user_sees_only_the_permitted_library`
> failed because a playlist's `library_id` is null and `_library_permitted` exempts a null — this
> list's gate finding 2, arriving one task earlier than expected and as a **failing test** rather
> than as a paragraph. It is not excluded: the rows are excluded from that assertion and a new one
> beside it states the leak out loud — every playlist reaches every user — for T6 to invert.
> `test_media_types_reads_the_measured_table` failed the same way for `mediaTypes=Audio`, which now
> returns all five playlists because the filter inverts the type map; that test now asserts the gap
> with its measurement beside it, so T6 has to come back to it rather than discover it.
>
> *What this world still cannot express, and it is one thing:* **there is no administrator in it.**
> AC-13, AC-16 and AC-18 all need an administrator who does not own the playlist, and adding a
> fourth user was tried and reverted — `tests/unit/test_items_route.py` already mints one at
> `"d" * 32`, so a world that claimed that id fails every test in that file on a unique
> constraint. Later tasks build their own, as that file does; the fixture must not claim `"d" * 32`.
>
> *Two smaller things.* The playlist rows go in through `ItemRepository` and the three playlist
> tables through the ORM, which is `_seed_user_data`'s exception and for its reason: T7 owns
> `PlaylistRepository` and does not exist yet. And the identifiers are fixed constants, not
> `new_id()` — a minted id in a deterministic world (Principle VII) is a constant or it is a golden
> nobody can check in.

## T6 — The clause without which every playlist is public

- [x] **Changes:** `db/item_queries.py`. `_visible_to` gains a fourth clause beside
  `_by_name_is_referenced`: a row that is not a playlist passes, and a playlist passes when the
  caller owns it, is shared with it, or it is public. Written as a clause and not as a filter in
  Python, for the reason plan §10's last paragraph gives about counts and paging.
  **And the `mediaTypes=` gap is this task's** (reassigned from nobody, 2026-08-31): T3 measured
  that a playlist's media type is fixed at creation and stored per row, so `_types_of_media` —
  which inverts the type-level `MEDIA_TYPE_OF` — claims every playlist for `Audio` and none for
  `Video`, where the reference filters by the stored row. T4 created the column; this task already
  edits this module and sits before every route that could expose the difference. Closing it with
  a clause or accepting it as a gap is this task's call, and spec §4 states both.
- **Depends on:** T5
- **Verified by:** `uv run pytest tests/unit/test_items_route.py tests/conformance -q` — a private
  playlist is absent from another user's `/Items?includeItemTypes=Playlist` and answers `404` on
  `GET /Items/{id}`, while the public one is present for both. **The test has to fail with the
  clause deleted**, and the task is not done until that has been checked by hand: the fixture's
  playlists must be owned by somebody other than the querying user, or the assertion passes on a
  world where nothing was hidden.
- **Spec reference:** §3.7, AC-15; plan §6.5, and this list's gate finding 2

> **Done (2026-08-31).** *Closing the `mediaTypes=` gap made a second one visible on the same
> response, and it was the older of the two: nothing on the `/Items` path ever filled the column
> the item body prefers.* T4 added `HydratedItem.media_type` and taught `api/item_dto.py` to
> prefer it over `MEDIA_TYPE_OF`, and plan §4.2 left the filling to *"T7's repository"* — which
> serves the playlist routes and not this one. `/Items` hydrates through `ItemQueries._hydrate`,
> which nobody told, so **every playlist listed there reported `MediaType: "Audio"`**, four of the
> world's five of them wrongly. On its own that is a wrong field; underneath this task's filter it
> is a response contradicting itself, because `mediaTypes=Video` would have returned four rows
> whose own bodies said `Audio`. `_hydrate` gains one statement for the page — unconditional, like
> the ancestors and the inspections beside it — and the hydration budget moves from eighteen to
> nineteen, which is the number `test_item_queries.py` writes down so that a new related table
> arrives as a decision rather than as drift. It was found by the parameter battery in
> `test_items_route.py`, not by reading: `mediaTypes=Video` stopped answering one media type.
>
> *The filter compares the row, and a two-value special case would have been wrong on the
> reference.* A playlist can answer **`Unknown`**: measured over the eight the reference held,
> `mediaTypes=Audio` returns five, `mediaTypes=Video` two and `mediaTypes=Unknown` one, and the
> probe now prints the census that says the three answers do not add up to the listing unless a
> third value exists `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`.
> Creation cannot produce it — an id list resolving to nothing falls back to `Audio`
> `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:124-126 @ v10.11.11]`, and a
> container in the list is expanded before the value is taken, so an album gives `Audio` and a
> series `Video`. It comes from the *scanner*: a playlist resolved from a directory is given no
> media type at all
> `[source: Emby.Server.Implementations/Library/Resolvers/PlaylistResolver.cs:40-45 @ v10.11.11]`
> and its own file cannot restore one, because `Unknown` is the single value the saver omits
> `[source: MediaBrowser.LocalMetadata/Savers/PlaylistXmlSaver.cs:52-55 @ v10.11.11]`. Atrium
> builds no playlist from a directory (spec §4), so its column holds `Audio` or `Video` — but that
> is now a fact the clause does not depend on.
>
> *The visibility clause itself is the one part of this task that was exactly what the gate said.*
> Four classes, no administrator branch — spec §3.7's last row gives an administrator who owns
> nothing and is shared nothing **no read**, and the test that holds it is in
> `test_items_route.py` because the fixture world has no administrator to hold it with (T5's Done
> note). Written as an `EXISTS` correlated to `items` for `_by_name_is_referenced`'s reason, and a
> playlist row with no `playlists` row fails it, which is the direction to fail in.
>
> *Both halves were checked by deletion, by hand, as the verification demanded.* With the clause
> removed, six tests fail — three of them at the HTTP boundary, which is the half the gate said a
> direct fetch could not prove. With `Playlist` put back into the type-level answer, the two
> `mediaTypes` tests fail. Neither passes on a world where nothing was hidden: all five playlists
> are owned by `everyone`, and the assertions run as `restricted`, as `nobody` and as an
> administrator who owns none of them.
>
> *One thing this task did not do, deliberately.* The reference server carries a leftover playlist
> from an earlier `probe_playlist_expansion.py` run — it is the `Unknown` row the census names,
> and deleting it is a write on somebody else's data that no question here needed. The probe that
> created it already asks for it to be removed by hand.

## T7 — `PlaylistRepository`: one read door, four writes

- [x] **Changes:** `db/repositories.py`. `by_id`, `entries`, `create`, `append`, `remove`,
  `reorder`, `rename`, `delete`, exactly plan §5's signatures. Every read takes a `User` and there
  is no variant that does not. `append` is `INSERT … ON CONFLICT DO NOTHING`, so de-duplication is
  the key rather than a step; `remove` and `reorder` renumber inside their own transaction.
  **`media_type` already has a writer on the `/Items` path** (added 2026-08-31 by T6): plan §4.2's
  *"T7's repository is what fills it in"* was true of the playlist routes only, and
  `ItemQueries._hydrate` now reads the column for every page. This task fills it for its own reads
  and must read the same column rather than re-deriving the value, or the two paths report
  different media types for one playlist.
- **Depends on:** T6
- **Verified by:** `uv run pytest tests/unit/test_playlist_repository.py -q` — duplicates on both
  paths add nothing, ordinals stay contiguous after every mutation, an entry whose item is
  soft-deleted disappears from `entries` and comes back if the item does, and a reflection test
  asserts **no public read on the class takes fewer arguments than a `User`** (plan §9's second
  risk).
- **Spec reference:** §3.4, §3.5; plan §5, §6.2, §6.3

> **Done (2026-08-31).** *The reference does not de-duplicate reliably, and a playlist there **can**
> hold one item twice.* Measured before a line was written, because §3.4's "duplicates are silently
> dropped" had only ever been asked of a playlist holding **one** entry — a shape that cannot tell
> "dropped" from "removed and appended", which is the half this task needed. It answered that half
> (the entry already there keeps its position, and `Ids` naming A B A creates A B) and then
> contradicted itself between two batteries of the same run. Repeated: **6 of 8 identical requests**
> added an item the playlist already held, seconds apart, on one server
> `[probe: tools/probe_playlist_writes.py, Jellyfin 10.11.11, 2026-08-31]`. The mechanism is spec
> §3.1's own field: the filter compares against `LinkedChildren.Select(c => c.ItemId)`
> `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:221-224 @ v10.11.11]`, that
> `ItemId` is a **cache** filled the first time an entry is resolved
> `[source: MediaBrowser.Controller/Entities/BaseItem.cs:1773-1805 @ v10.11.11]`, and the writer
> that creates entries never fills it
> `[source: MediaBrowser.Controller/Entities/LinkedChild.cs:26-40 @ v10.11.11]`. So the two stages
> §3.4 describes are one reliable and one cold-cache lottery — and what the lottery produces is the
> thing §3.1 said could not exist: two rows carrying **one** `PlaylistItemId`, which `Move`
> reorders by moving the first copy and `Remove` deletes both of at once. Measured, on a playlist
> the race had just made. **Atrium de-duplicates always** — a coin flip cannot be replicated
> (Principle VII) and no client can compensate for a duplicate it can neither predict nor delete —
> which is 009's **fourth** divergence: behaviours §3.18, spec §3.1, §3.4, AC-5, plan §1 and §6.2.
>
> *And "de-duplication is the key rather than a step" is wrong in both directions.* The key does
> not **drop** a repeat: with the reduction removed, three of this task's tests fail with
> `IntegrityError` — the constraint refuses, and only a dialect-specific `ON CONFLICT DO NOTHING`
> would make it drop. And even that would not be enough, because a conflicting insert leaves the
> **ordinal** it was going to occupy unused: a playlist de-duplicated by the key alone grows a hole
> in the one column `remove`, `reorder` and the read all assume is contiguous, on the first
> repeated add. The batch is reduced before the ordinals are handed out — which is also how
> `append` answers AC-5's count without a second read — and the constraint stays as what makes a
> duplicate impossible under a concurrent writer rather than merely unlikely. Plan §6.2 says so.
>
> *Two of plan §5's eight signatures could not be written as they stand, and the same sentence
> forbids both.* "Every read takes a `User`" is the rule; `reorder(playlist_id, order)` breaks it,
> because the caller can only produce that order by first reading the **stored** one — the one read
> the class exists to keep inside itself. `reorder` therefore takes the move (`entry`, `new_index`,
> `visible`) and runs `moved` internally, which also makes the read and the write it depends on one
> transaction instead of two requests apart. And `by_id`'s `User` cannot be a `may_read` filter:
> the one caller who needs it most is the **administrator**, who may delete a playlist they may not
> read (spec §3.6), and a strict door would have answered `404` to T12 and made that task
> unwritable. It is an existence filter with an administrator branch, the routes still call
> `may_read`, and a test asserts both halves — tightening the door fails loudly rather than in
> three tasks' time.
>
> *The visibility predicate is asked, not copied.* `entries` needs exactly what `/Items` filters
> by, and `db/item_queries.py` imports `db/repositories.py`, so the import cannot go the other way:
> the repository is **handed** an `ItemQueryRepository` and asks its new public `visible_ids`. The
> alternative — "not removed, and in a library this user may open" written a second time here — is
> the failure that module's own docstring opens with, and it would have been invisible until
> somebody changed library access and moved one of the two.
>
> *One thing this task did not do, deliberately.* T5's fixture says "when T7 lands, this function
> is one of its callers to reconsider". It is not: `create` takes `date_created` from the clock,
> where the fixture needs fixed dates for a deterministic world (Principle VII) — and a world built
> by the code under test cannot fail it, which is what four of this task's assertions rely on.
>
> *Two smaller things.* `rename` writes **three** columns, not one: `name`, `sort_name` and
> `name_folded` are three derivations of one string, and writing only the first leaves a playlist
> that sorts under its old name and that `searchTerm` cannot find at all — 005 T6's finding, on one
> row of the same table, and `ItemRepository.update` is not a door for it because it writes neither
> name once a refresh has touched the item. And every clause above was checked by deletion, by
> hand: removing the entry filter fails two tests, the `may_read` filter one, the administrator
> branch another, the name derivations a fifth, and the batch reduction three.

## T8 — `POST /Playlists`: two refusals that are not the same shape

- [x] **Changes:** new `api/playlists.py` with the create route. Plan §6.1 in order: a body with no
  `Name` is the model layer's validation `400`; an empty or blank name is accepted and stored; with
  no `MediaType` the id list is walked and the first unresolvable id **before** the first resolvable
  one is the bare-text `400`; an empty playlist with no media type is `Audio`. The response is
  `{"Id": …}`.
- **Depends on:** T7
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — the two `400`s asserted
  as **bytes**, the empty name creating a playlist, and the three id-list orders answering `400`,
  `200`, `200`. Then `/Items?includeItemTypes=Playlist` finds it (AC-1).
- **Spec reference:** §3.2, AC-1, AC-2, AC-3

> **Done (2026-08-31).** *This task's title undercounts by two, and the miscount is in the half the
> plan called settled.* Section 6.1's step 1 says the missing-`Name` refusal *"is not a check this
> feature writes"* and that its map is *"keyed on the property"*. The key is **`$`** — the
> deserialiser refusing the whole document before any property is validated, with a sentence naming
> the type it was building — and the property key belongs to a request nobody had asked about:
> `Name` present and **`null`**, which answers `{"Name": ["The Name field is required."]}` and is a
> different refusal from a different layer. A malformed identifier in `Ids` or `UserId` is a
> **third** key, the empty string. So the route answers four `400` bodies from three layers, and
> the "two refusals" of the title are the two the documents happened to name
> `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`.
>
> *And none of the four carries the key behaviours §1.11 said every body refusal carries.* That
> section states a body failure names the binder's key **beside the action parameter's name**,
> measured across 007's three routes. Measured here: one key, never two. What decides it is whether
> the body parameter is **required** — 007's three are, this route's is not — so `body_parameter_of`
> answers `None` for an optional body and the second row disappears with it. Without that, every
> refusal on this route would have shipped a `createPlaylistDto` row no reference server sends; with
> the guard removed, four of this task's tests fail.
>
> *Two of the reference's sentences name a .NET type, and both are reproduced rather than diverged
> from.* Section 1.11 already carries a recorded divergence for a `$` message on the argument that
> *"reproducing that sentence would mean writing a JSON parser to fail like another one"*. That is
> true of the **parser's** message and of nothing else here: the missing-property sentence is a
> template over the type name and the property, and the vocabulary sentence's
> `BytePositionInLine` is the offset **inside the quoted token** — `3` for a one-character value
> where an eight-character one gives `10`, measured on purpose to find out — so both are byte-exact.
> The two type names are wire facts declared on the model (`WIRE_TYPE`, `WIRE_ENUM_TYPES`) and
> nothing about how the reference computes them is carried over, which is the interface-versus-
> implementation line Principle IV draws. The divergence in §1.11 is narrowed to the parser message
> it was actually about.
>
> *The route has four inputs neither document mentioned, and refusing them would have been the
> larger delta.* `name`, `ids`, `userId` and `mediaType` are query parameters as well as body
> properties; the query wins; and `?name=` with **no body at all** creates a playlist. A route that
> required a body would refuse a request the reference serves. Measured with it: a query `name`
> does **not** rescue a body that fails to deserialise, so the merge happens after binding and plan
> §6.1's step 1 really does belong to the model layer even though the value has a second source.
> And the same token is refused two ways on one route — `MediaType: Nonsense` in the body is T3's
> validation `400`, `?mediaType=Nonsense` is dropped and recorded, which is behaviours §1.12 beside
> the refusal it is usually contrasted with.
>
> *Two requests the reference cannot serve it answers anyway, and both are refused here.* A request
> naming no `Name` in **either** source is a **`500`** — `text/plain`, the same 25 bytes — because
> "no name" is a property of the merged pair and the one combination the route does not survive. And
> a `UserId` naming **nobody at all** answers `200` and creates a playlist owned by a user that does
> not exist, which no rule in spec §3.7 can then reach: it is unreadable, uneditable and
> undeletable by every caller. Atrium refuses the first with `400` in the reference's own bytes and
> the second with the `404` `effective_user` already answers — 007 T10's Done note left that second
> case *chosen but unmeasured*, and it is measured now. Both are behaviours **§3.19**, argued from
> §3.15's reasoning one route away rather than improvised.
>
> *One decision taken rather than escalated.* `POST /Playlists` with `UserId` naming another user is
> `403` with T2's 25 bytes — measured on this route rather than inferred from the add route beside
> it, which is all §3.16 had `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11,
> 2026-08-31]`. It is `effective_user`, unchanged, so AC-19 holds on this feature's first route
> without a second copy of the rule.
>
> *One thing this task did not do, and the task list is why.* A container named in `Ids` becomes an
> entry of its own and settles the media type from itself: plan §6.2's expansion serves creation and
> addition through one function and arrives at **T10**, which is also where AC-7 asserts the album's
> own order. Named here rather than discovered there.
>
> *Two smaller things.* `INTERIM_009` is back in `tests/conformance/test_routes.py` — the seventh
> feature to need that device, deleted at T14 like the six before it — and the exact-set check would
> otherwise have failed on the first route 009 registered. And every clause above was checked by
> deletion, by hand: removing the wire-name normalisation fails three tests, the required-body guard
> four, and the no-name refusal one.

## T9 — `GET /Playlists/{playlistId}/Items`: the one door, and `PlaylistItemId`

- [x] **Changes:** the read route, through plan §6.5's five steps in that order — `effective_user`,
  `may_read`, the filtered join, the envelope with the count taken **after** filtering and before
  paging, and `PlaylistItemId` on every row. `api/item_dto.py` emits the property for this route
  only, equal to the row's `Id`. No sort parameter is declared.
- **Depends on:** T8
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — every row's
  `PlaylistItemId` **equals** its `Id`, asserted on the serialised body; a playlist read by
  `restricted` omits the items it cannot reach with the rest keeping their order and ids and a
  `TotalRecordCount` counting only the survivors; and `?userId=<the owner>` from a
  non-administrator answers `403` **with T2's bytes**, where the reference answers `200`.
- **Spec reference:** §3.1, §3.3, §3.7, AC-4, AC-8, AC-16, AC-17

> **Done (2026-09-01).** *The task measured the width it was told to and found the documents right;
> what it got wrong was a status it had never thought to call a shape.* Spec §3.3 said
> *"`404` for an unknown playlist, and for one the reader may not see"* and stopped there, and plan
> §6.5 step 2 said `404` and not `403` — both true, and neither a shape. Measured, this route
> answers the **JSON-encoded bare string** `"Playlist not found"`, `application/json; charset=utf-8`,
> 20 bytes: behaviours §1.11's fourth shape, which until now had exactly one route in the whole
> project. Every `404` this codebase raises from a handler is problem details, and `NotFoundError`
> is one import away in the module the route already uses — so the obvious implementation ships a
> body no reference server sends, on the feature's first read route
> `[probe: tools/probe_playlist_read.py, Jellyfin 10.11.11, 2026-09-01]`.
>
> *Three requests are one body and a fourth is a different status.* An id that addresses nothing,
> an id that addresses a real item which is **not** a playlist, and a playlist this reader may not
> see are the same 20 bytes — which is what makes a private playlist undisclosable, and it is why
> `PlaylistNotFoundError` interpolates nothing where the image route's template beside it
> interpolates a display name. A **malformed** id never reaches the route: it is the binder's
> validation `400`, and it carries the *path* parameter's sentence —
> `{"playlistId": ["The value 'not-an-identifier' is not valid."]}` — not the body's
> `The supplied value is invalid.` that T8's four refusals are made of. Typing `playlistId` as
> `WireGuid` rather than `str` is the whole of what produces that, and the first draft here had it
> as `str`. The class is deliberately **not** a `NotFoundError` subclass: Starlette resolves a
> handler by walking the exception's MRO, so inheriting would have restored problem details
> silently, which is the same trap the `ItemNotFoundError` comment in `compat/errors.py` describes
> from the other side.
>
> *The width the task was told to measure held, and measuring it was still the right call.* 005 T1
> says there is no single item representation, so this row could have been any of three shapes.
> Subtracting the property sets over the same items: **thirty-two names against thirty-one, the
> difference is `PlaylistItemId` and nothing else, the reverse subtraction is empty, and an
> `/Items` row carrying the same track does not have the property at all**. So the row is the
> list-row width plus one name. That shaped the mechanism: a flag on `BuildContext` and a
> one-name fourth tier beside `ALWAYS`, `PER_TYPE` and `GATED` — **not** a fourth member of
> `Width`, which would have asserted a fourth measured shape against a measurement that says there
> are three. The field is declared on `BaseItemDto` immediately after `Id`, because that is where
> the reference sends it and a subclass's own fields serialise last.
>
> *AC-8's second half cannot be proven by sending a `sortBy`.* A route that accepted the parameter
> and happened to sort by the playlist's order passes that test, and the client can still discover
> the capability — which is the thing Principle I forbids. The assertion is against the generated
> **OpenAPI document**, which is literally where a client discovers one: eight query parameters and
> no ninth. (Measured anyway, for the record: `sortBy=SortName&sortOrder=Descending` answers `200`
> in the playlist's own order.)
>
> *Two routine calls, taken rather than escalated.* **The `403` for a named reader is
> `effective_user`, unchanged** — §3.16's divergence shipped as one call to 005's helper rather
> than as a rule of this route's own, so there is no second copy to drift, and the refusal is the
> 25-byte `text/plain` T2 measured. Its other half is parity and worth naming: an administrator
> naming a user gets **that user's view**, and an administrator who is none of §3.7's three classes
> is answered `404` for a private playlist — the visibility clause has no administrator branch, so
> `may_read` has to be called *here* even though `by_id` already took a `User`, and there is a test
> that fails if a later change drops it. **`startIndex` is clamped at zero** rather than passed
> into a slice: a negative one wraps in Python and hands back the tail of the playlist, a shape no
> reference server produces.
>
> *One test assumption was wrong and the fixture was right.* The public playlist holds the three
> tracks and `restricted`'s one library is Films, so *"a public playlist is readable by anybody"*
> measured `TotalRecordCount: 0` — which is not a failure but §3.17's divergence and §3.7's fourth
> class firing at once. The test now uses both readers: the administrator proves `is_public` grants
> the read, `restricted` proves an empty `200` is a different answer from a private playlist's
> `404`.


## T10 — Adding and removing, and every container expands

- [x] **Changes:** the add and remove routes. Add resolves each id, expands a container to its
  playable descendants in the container's own order through the existing children query, and
  appends; unknown ids are skipped unconditionally here, unlike creation. Remove takes `entryIds`
  and answers `204` for an id that is not there. **The refusal for a caller who may not edit is
  `403` with no body and no content type** (added at T5): it is the body-less shape, not
  `ForbiddenError`'s sentence, so it uses T13's second exception class
  `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`.
- **Depends on:** T9
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — an album's tracks in the
  album's own order with the album itself absent, a series' episodes, a collection's films;
  duplicates dropped on both paths; removing an absent entry id answering `204`.
- **Spec reference:** §3.4, §3.5, AC-5, AC-6, AC-7

> **Done (2026-09-01).** *"Every kind of container" was a list of five, and the rule is a
> predicate over everything that is not a file.* Measured, three more kinds expand and none of the
> documents had named them: a **plain folder**, **the library root itself** — twenty-one entries
> from a view listing three children, because the expansion is recursive — and **another
> playlist**, which is the one container whose children are not in the item tree at all
> `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`. Written from the
> five kinds, the rule would have put a whole library into a playlist as a single row. What
> answers *"is this a container"* was already in the domain: `FILE_BACKED` is the three types a
> file produces, and everything else holds something. Two more properties no single-id request can
> show: the expansion lands **where the container was named** in a batch, and a folder's order and
> an **artist's** are different orders — a folder answers `/Items?parentId=`'s, an artist answers
> album artist, album, sort name over the tracks they are *credited* on, which was forty-two rows
> where the tree walk gives forty.
>
> *And the same function moves a value the create route had already shipped wrong.* Plan §6.2 says
> one expansion serves both paths, so creation expands too — and the media type it settles comes
> from **what the ids expanded to**, not from the id: a series in `Ids` creates a `Video` playlist
> where the series' own media type is `Unknown` and the fallback is `Audio`. T8's walk read
> `MEDIA_TYPE_OF[Series]` and would have stored `Unknown`, a value the reference's creation path
> cannot produce at all (spec §4). Four containers answer from their kind before their contents
> are consulted — three music ones `Audio`, a `Genre` `Video`
> `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:95-114 @ v10.11.11]` — and
> that map is the only way `Video` is reachable for a container that expands to nothing, which a
> genre always does.
>
> *The finding that nearly went the other way: one identifier is refused where every other unknown
> one is skipped.* The first run of the new probe measured *"an unknown id refuses the whole add
> request, in any position"* — flatly contradicting both documents — and it was wrong, because the
> id it called unknown was `00000000000000000000000000000000`. **`Guid.Empty` is a third class**:
> the reference rejects it in the item lookup rather than failing to find it
> `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1357-1362 @ v10.11.11]`, so it is
> the bare-text `400` on the add route wherever it sits, and on **creation** even in the position
> where an ordinary unknown id is skipped — while a *malformed* id is dropped in silence and a
> genuinely absent one is skipped exactly as documented
> `[probe: tools/probe_playlist_add_remove.py, Jellyfin 10.11.11, 2026-09-01]`. It is the id a
> client sends when a default-initialised field reaches the wire, and both probes now carry the
> pair side by side so it cannot be collapsed again. It is **not** a refusal on the removal, which
> looks nothing up: absent, malformed, all-zeros and no parameter at all are four `204`s.
>
> *Two shapes the task statement had not asked about.* Both write routes answer T9's twenty bytes —
> an absent playlist and a real item that is not a playlist are one body, so no write discloses a
> playlist a caller may not see — and a **malformed** playlist id is the binder's validation `400`
> on the add and an unhandled **`500`** on the removal, one path and two bindings, because that
> action takes the segment as text and parses it itself. Atrium answers the `400` on both:
> behaviours §3.19 gains its third row rather than a section of its own, since it is the same class
> and the same argument.
>
> *One condition AC-13 was missing.* The administrator's `403` is reachable only on a playlist that
> administrator can **see**. The lookup in front of every editing test filters by owner, share and
> `IsPublic` with no administrator branch, so a private playlist is `404` and never reaches the
> permission test — the criterion is corrected rather than the code.
>
> *Two routine calls, taken rather than escalated.* **`EmptyForbiddenError` is written now**, not at
> T13: the decision recorded on 2026-08-31 gave the policy-shaped `403` a second class answering
> `empty_error(403)`, and the editing refusal needs the same bytes for the reason spec §3.7 already
> states — the split is between a refusal the reference *returns* and one it *throws*, not between
> a controller and a policy, so one class serves both raise sites and T13 reuses it. **The artist's
> middle ordering key is applied after the read**, because `Album` is not one of the eight `sortBy`
> tokens and `SortBy`'s own docstring forbids a ninth: a key on the wire that no reference server
> orders by is exactly the delta that enum exists to prevent.
>
> *Two things this task could not prove at the HTTP boundary, named rather than hidden.* The
> artist ordering is asserted as a key function in `tests/unit/test_playlist_expansion_order.py` —
> the seeded world's one guest album sorts the same way under the three keys and under a plain
> `SortName`, so a boundary test would agree with itself, and a second album for that artist is a
> fixture change belonging to a fixture task. And the **music genre** branch is source-cited rather
> than proven: the world's music genre is carried by an album and not by its tracks, so the branch
> and the folder branch answer alike there. The **video** genre's `Video` is proven, and it is the
> row that makes the map load-bearing. Every other clause was checked by deletion, by hand: removing
> the expansion fails four tests, the all-zeros guard one, the `may_edit` test three, and the nested
> playlist branch one.

## T11 — `Move`, and the two refusals the reference does not make

- [x] **Changes:** the move route over T1's `moved`. `204` for a move, for a no-op, and for an entry
  id that is not in the playlist with an in-range index; `400` for an index past the visible length
  or below zero — behaviours §3.15 — **and the index is judged before the entry is looked up**, so
  an absent entry with an out-of-range index is the refusal. **And the caller who may not edit is
  `403` with no body and no content type** (added at T5) — measured on a shared reader without
  `can_edit` and on a public playlist's reader, both of which the world now holds
  `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-08-31]`.
- **Depends on:** T10
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — the five-entry
  `0 → 3` giving `B C D A E` over HTTP with entry ids unchanged, and each boundary row answering
  what spec §3.5's third column says.
- **Spec reference:** §3.5, AC-9, AC-10, AC-11

> **Done (2026-09-01).** *The task was written as one arithmetic behind one identifier, and the
> route has **three path segments that bind three different ways**.* The playlist id is parsed, so
> a dashed one addresses the playlist. The **entry** id is not parsed at all: the reference
> compares it as text against the plain 32-character spelling of each entry, case-insensitively,
> so an upper-case entry id moves the entry and a **dashed or braced one moves nothing**
> `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-09-01]`
> `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:308-323 @ v10.11.11]`. This
> is therefore the one route in the feature that must **not** canonicalise the identifier it is
> handed — `_identifiers()` and `WireGuid` are both the wrong tool here, and either would have
> reordered a playlist no reference server reorders, visibly, in the order the caller gets back.
> It is also why an entry id that is malformed or all zeros is a silent `204` and not a refusal:
> nothing on this route looks an item up, so `EmptyIdentifierError` must not be reachable from it.
>
> *And the two refusals the task did name are not the first two the route makes.* T10's open
> question — is a malformed playlist id the binder's `400` or the removal's `500` — is answered
> `500`: this action parses the segment itself, exactly as the removal does and unlike the
> addition on the same path `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:409-431 @
> v10.11.11]`. That is behaviours §3.19's **fourth** request, answered here with the validation
> `400` like the other two. And the order the whole route hangs on was measured rather than
> deduced: a shared reader without `CanEdit` naming an index the reference crashes on is answered
> **`403`**, not `500` `[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-09-01]`.
> So `_editable` runs before the arithmetic, "the index is judged before the entry" is a rule
> *inside* `moved` and not a rule of the route, and the `400` this feature makes its own is
> reachable only by a caller who may edit. Plan §6.4.1 said neither; it does now.
>
> *One test passed for the wrong reason, and it was the one test with no reference answer behind
> it.* AC-17's *"an entry the reader cannot see is answered as an absent one"* was first written
> as a move of the hidden entry to index 1 — and that entry is **stored** at index 1, so a route
> indexing the stored order would have answered it with a no-op and the assertion would have held.
> Caught by deletion, by hand: with the route reading the stored order in place of the caller's,
> two of the three AC-17 tests failed and that one did not. It names index 3 now, the last index
> that reader may name, which no reading can reach without moving something.
>
> *Two routine calls, taken rather than escalated.* **The `400` is a class of its own**
> (`PlaylistMoveError`) rather than `PlaylistCreationError` reused for its bytes: the classes in
> `compat/errors.py` are read where they are raised, and that one's docstring is a statement about
> `Ids` and a `Name`. **The route declares no `userId`**, which is the reference's own shape
> `[spec: MoveItem]` — the removal beside it declares none either, and a parameter this route does
> not have would be a lever no reference server offers, asserted against the generated document
> the way AC-8 is. Every clause was checked by deletion: normalising the entry id fails two tests,
> testing the caller after the index fails four, and reading the stored order in place of the
> caller's fails three.

## T12 — `DELETE /Items/{itemId}`: three refusals, one of them ours

- [x] **Changes:** `api/items.py` gains the route. A playlist the caller may delete goes, with its
  entries and shares; one they may not is `401` with the body `Unauthorized access` — a status this
  project associates with *no credential*, raised explicitly rather than by teaching
  `ForbiddenError` a second one. Anything whose deletion would remove a file is `403`
  (behaviours §4.3). Unknown or invisible is `404`.
- **Depends on:** T11
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — deletion by the owner
  and by an administrator who is not; `401` **with its body** for a shared reader; and the media
  refusal with an **on-disk assertion** that the file is still there afterwards. The administrator
  is built by the test: **the fixture world has none** (T5), the way
  `tests/unit/test_items_route.py` already does it, and AC-13's editing half is the body-less `403`
  that task measured.
- **Spec reference:** §3.6, AC-12, AC-13

> **Done (2026-09-01).** *The task was written around one refusal that discloses nothing, and this
> route's refusal discloses.* Spec §3.6 said *"`404` for an unknown or invisible item"*, and for a
> **playlist** the second half is false: `DELETE /Items/{itemId}` applies no visibility test to one
> at all. Measured, a caller who is answered the read route's twenty bytes and `GET /Items/{itemId}`'s
> problem details for a private playlist is answered **`401`** here — and so learns it exists
> `[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`. Written as the documents
> said, the route would have gone through `by_id` and answered that caller `404`, which is a body
> no reference server sends on a request any client can make. **Media is filtered the other way**,
> in the same run: an item in a library the caller cannot open is `404` before any permission is
> consulted. So one route holds a disclosing refusal and a non-disclosing one at once, and the
> repository grew a **third read** — `by_id_for_deletion`, the only one that takes no `User` —
> rather than a filter argument nobody could read the meaning of. It is replicated rather than
> corrected, and behaviours §3.20 carries the argument: the `401` is a refusal a delete button can
> act on where a `404` invites *"it is already gone"*, and the identifier has to be known before it
> can be asked about.
>
> *The row the task expected to be conditional is the one row in §3.7 that is not.* T10 had to
> correct AC-13 because an administrator's editing `403` is reachable only on a playlist they can
> **see**; the same reasoning predicts a `404` for a deletion, and the reference answers `204`. The
> administrator deletes a private playlist that every other route in the feature refuses them. That
> is what `by_id`'s deliberate administrator hole was written for — and it turned out not to be
> enough, because a *stranger* has to reach the playlist too.
>
> *Two identifiers neither document had asked about, and they are T10's two classes again.* An
> all-zeros id is the bare-text `400` here as it is on the write routes — the reference refuses
> `Guid.Empty` in the item lookup this route shares with them — and a malformed one is the binder's
> validation `400` keyed `itemId`, so `itemId` **is** a `WireGuid` where T11's entry id must not be.
> Three of the four 009 routes bind that segment differently and this is the fourth; asking was the
> whole of what made it right. The constant they share moved to `compat/guids.py` as `EMPTY`, since
> two routes in two modules refusing the same identifier for the same reason is one fact.
>
> *What 009 claims of this route, since the task asked.* Only the playlist. The rule was written as
> *"succeeds only for items whose deletion removes no file from disk"*, which reads as permission
> for the by-name rows — and deleting a genre this server rebuilds on the next scan is a deletion
> that does not stick, which is Principle VI's plausible-looking stub. Everything that is not a
> playlist is `403`. The reference refuses those rows too (`CanDelete()` is `IsFileProtocol`), with
> `401` rather than this `403`, and that is inside behaviours §4.3's existing exception rather than
> beside it.
>
> *Three routine calls, taken rather than escalated.* **The media `403` stays one status for every
> caller**, though the probe measured that a caller without `EnableContentDeletion` is refused
> `401` by the reference — narrowing the divergence there would make a refusal's shape depend on a
> permission v1 enforces nowhere else, and §4.3 now records the second observable cell rather than
> chasing it. **Two exception classes, not one**: `DeletionNotPermittedError` for the parity `401`
> and `MediaDeletionRefusedError` for the invented `403`, because a class in `compat/errors.py` is
> read where it is raised and `ForbiddenError`'s docstring is a statement about an account. **The
> `401` is the fourth error shape** — 21 bytes, `application/json; charset=utf-8` — so this route
> answers `401` two ways, empty when no token arrived and with a body when one did, which is
> recorded in behaviours §1.11 where that shape had been a `404` fact.
>
> *And the on-disk assertion needed a world.* Every library in the fixture world is rooted at a
> path that does not exist, so no test in it could tell *"the route refused"* from *"there was no
> file to remove"*. AC-12's media half now roots a fourth library inside `tmp_path` with real bytes
> in it and asserts them after the `403`. Every other clause was checked by deletion, by hand:
> replacing the unfiltered read with `by_id` fails two tests, removing the all-zeros guard one,
> removing the `may_delete` test five, and removing the media lookup three.

## T13 — `POST /Items/{itemId}`: the rename, and the two things it refuses

> **No longer blocked (2026-09-01).** It was: the reference's `403` here is the **empty** shape —
> no body, no content type, an authorization policy's refusal — and `ForbiddenError` stopped being
> that at T2, so the route needed the other shape by a road nobody had chosen. The decision taken
> on 2026-08-31 was a second exception class, and **T10 wrote it**: `EmptyForbiddenError` in
> `compat/errors.py`, answering `empty_error(403)`, because the playlist controller's own editing
> test sends the same bytes for the same reason (spec §3.7). Raise that class here and assert the
> empty body *and* the absent content type.

- [ ] **Changes:** `api/items.py` gains the route: an administrator renaming a playlist applies
  `Name` and nothing else; any non-administrator is `403` — the reference's own answer from an
  elevated controller; an administrator on an item that is not a playlist is `403`, which is v1's
  own answer and goes to behaviours §5 in this change (plan §6.6).
- **Depends on:** T12
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — the rename visible in
  `/Items` afterwards, the owner-who-is-not-an-administrator refused, and a film refused with
  nothing about it changed.
- **Spec reference:** §3.8, AC-18

## T14 — The acceptance map, the route set, and 009 is Implemented

- [ ] **Changes:** an acceptance map putting every one of spec §5's twenty criteria on one line
  with the test that proves it, in `specs/009-playlists/tasks.md`. `surface.yaml`'s seven 009 rows
  checked against the routes that actually exist. `spec.md`, `plan.md` and `tasks.md` to
  `Implemented`; `specs/README.md`, `AGENTS.md` and the two client contracts updated for what 009
  now serves.
- **Depends on:** T13
- **Verified by:** `python3 tools/extract_v1_surface.py --print-summary`, the full gate, and a test
  asserting the router serves exactly the seven 009 routes and no eighth.
- **Spec reference:** all of §5, §6

---

## Definition of done

- [ ] Every one of spec §5's twenty acceptance criteria has a passing test, named in T14's map.
- [ ] Every endpoint reaches the conformance level in spec §6.
- [ ] `surface.yaml` lists the seven routes and the router serves no eighth.
- [ ] The **four** divergences ship as specified: the named reader (§3.16), the unreachable entry
      (§3.17), the two refusals `Move` does not make (§3.15) and the de-duplication that never
      misses (§3.18, added at T7) — each with a test that fails if the reference's behaviour is
      reproduced instead.
- [ ] `ForbiddenError`'s body is the reference's 25-byte shape, on 009's routes **and** on 005's
  (AC-19) — and every **`may_edit`** refusal is the body-less one, which is a different set of
  bytes and not this class: the rename (AC-18, T2), and `Move`, `Add` and `Remove` for a caller who
  may read the playlist and not change it (AC-13, AC-14, T5). The line between the two shapes is
  *thrown versus returned*, not *controller versus policy* (T5).
- [ ] Anything learned during implementation is back in `spec.md` and `plan.md`, in the same change.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all `Implemented`.

## What is out of scope, recorded so it is not mistaken for an oversight

- **`UpdatePlaylist` and the sharing routes** (spec §2). The first is the only route that renames
  for an owner who is not an administrator, and no analysed client calls it.
- **Media deletion** (spec §3.6, behaviours §4.3), and the reference's refusal path for it, which
  cannot be probed against a real library without risking the file.
- **A playlist's `Path`** and the directory behind it (spec §4, behaviours §5).
- **002 OQ-5's three authentication refusals.** T2 fixes a *policy* refusal's body; the three that
  need a real account to fail against stay open.

## What this feature owes the next ones

*Written at T14, when it is known rather than guessed.*
