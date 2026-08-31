---
feature: 009-playlists
title: Playlists — tasks
status: Accepted
created: 2026-08-31
updated: 2026-08-31
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

- [ ] **Changes:** `tests/fixtures/query.py` seeds four: one owned by `everyone`, one shared with
  `restricted` **with** `can_edit`, one shared **without** it, and one holding items from two
  libraries — which is AC-17's whole case. The users this needs already exist (`everyone`,
  `restricted`, `nobody`), which is the correction the plan gate made to plan §8.
- **Depends on:** T4
- **Verified by:** `uv run pytest tests/unit -q` — the world builds, and a test asserts the
  two-library playlist really does hold an item `restricted` cannot see, because a fixture that
  quietly holds two visible items would make T6 and T9 pass for the wrong reason.
- **Spec reference:** §3.7; plan §8

## T6 — The clause without which every playlist is public

- [ ] **Changes:** `db/item_queries.py`. `_visible_to` gains a fourth clause beside
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

## T7 — `PlaylistRepository`: one read door, four writes

- [ ] **Changes:** `db/repositories.py`. `by_id`, `entries`, `create`, `append`, `remove`,
  `reorder`, `rename`, `delete`, exactly plan §5's signatures. Every read takes a `User` and there
  is no variant that does not. `append` is `INSERT … ON CONFLICT DO NOTHING`, so de-duplication is
  the key rather than a step; `remove` and `reorder` renumber inside their own transaction.
- **Depends on:** T6
- **Verified by:** `uv run pytest tests/unit/test_playlist_repository.py -q` — duplicates on both
  paths add nothing, ordinals stay contiguous after every mutation, an entry whose item is
  soft-deleted disappears from `entries` and comes back if the item does, and a reflection test
  asserts **no public read on the class takes fewer arguments than a `User`** (plan §9's second
  risk).
- **Spec reference:** §3.4, §3.5; plan §5, §6.2, §6.3

## T8 — `POST /Playlists`: two refusals that are not the same shape

- [ ] **Changes:** new `api/playlists.py` with the create route. Plan §6.1 in order: a body with no
  `Name` is the model layer's validation `400`; an empty or blank name is accepted and stored; with
  no `MediaType` the id list is walked and the first unresolvable id **before** the first resolvable
  one is the bare-text `400`; an empty playlist with no media type is `Audio`. The response is
  `{"Id": …}`.
- **Depends on:** T7
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — the two `400`s asserted
  as **bytes**, the empty name creating a playlist, and the three id-list orders answering `400`,
  `200`, `200`. Then `/Items?includeItemTypes=Playlist` finds it (AC-1).
- **Spec reference:** §3.2, AC-1, AC-2, AC-3

## T9 — `GET /Playlists/{playlistId}/Items`: the one door, and `PlaylistItemId`

- [ ] **Changes:** the read route, through plan §6.5's five steps in that order — `effective_user`,
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

## T10 — Adding and removing, and every container expands

- [ ] **Changes:** the add and remove routes. Add resolves each id, expands a container to its
  playable descendants in the container's own order through the existing children query, and
  appends; unknown ids are skipped unconditionally here, unlike creation. Remove takes `entryIds`
  and answers `204` for an id that is not there.
- **Depends on:** T9
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — an album's tracks in the
  album's own order with the album itself absent, a series' episodes, a collection's films;
  duplicates dropped on both paths; removing an absent entry id answering `204`.
- **Spec reference:** §3.4, §3.5, AC-5, AC-6, AC-7

## T11 — `Move`, and the two refusals the reference does not make

- [ ] **Changes:** the move route over T1's `moved`. `204` for a move, for a no-op, and for an entry
  id that is not in the playlist with an in-range index; `400` for an index past the visible length
  or below zero — behaviours §3.15 — **and the index is judged before the entry is looked up**, so
  an absent entry with an out-of-range index is the refusal.
- **Depends on:** T10
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — the five-entry
  `0 → 3` giving `B C D A E` over HTTP with entry ids unchanged, and each boundary row answering
  what spec §3.5's third column says.
- **Spec reference:** §3.5, AC-9, AC-10, AC-11

## T12 — `DELETE /Items/{itemId}`: three refusals, one of them ours

- [ ] **Changes:** `api/items.py` gains the route. A playlist the caller may delete goes, with its
  entries and shares; one they may not is `401` with the body `Unauthorized access` — a status this
  project associates with *no credential*, raised explicitly rather than by teaching
  `ForbiddenError` a second one. Anything whose deletion would remove a file is `403`
  (behaviours §4.3). Unknown or invisible is `404`.
- **Depends on:** T11
- **Verified by:** `uv run pytest tests/conformance/test_playlists.py -q` — deletion by the owner
  and by an administrator who is not; `401` **with its body** for a shared reader; and the media
  refusal with an **on-disk assertion** that the file is still there afterwards.
- **Spec reference:** §3.6, AC-12, AC-13

## T13 — `POST /Items/{itemId}`: the rename, and the two things it refuses

- [!] **Blocked by a decision, from T2's measurement.** The reference's `403` here is the **empty**
  shape — no body, no content type, an authorization policy's refusal — and `ForbiddenError` stopped
  being that at T2. This route needs the other shape by a road nobody has chosen: a second exception
  class, or the route returning the response itself the way the delete `401` does (plan §6). The
  rest of the task is unchanged and is written below.
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
- [ ] The three divergences ship as specified: the named reader (§3.16), the unreachable entry
      (§3.17) and the two refusals `Move` does not make (§3.15) — each with a test that fails if the
      reference's behaviour is reproduced instead.
- [ ] `ForbiddenError`'s body is the reference's **controller** shape, on 009's routes **and** on
  005's (AC-19) — and the rename's `403` is the reference's **policy** shape, which is a
  different set of bytes and not this class (AC-18, T2's finding).
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
