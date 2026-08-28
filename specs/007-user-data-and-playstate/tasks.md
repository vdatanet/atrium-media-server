---
feature: 007-user-data-and-playstate
title: User data and playstate — tasks
status: Accepted
created: 2026-08-28
updated: 2026-08-28
accepted: 2026-08-28
amended: 2026-08-28 at the gate — the fixture's single runtime, the check-in column nobody writes, OQ-7's owner and AC-16's existing tests; see "What the gate changed"
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 007 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries four structural decisions.** The measurement debt is paid first: T1 folds
the four batteries the plan gate ran as hand requests into the committed probe, so the citations
that added AC-21 and AC-22 are reproducible before any code leans on them — 006 T1's rule, and
the reason the `[probe: manual requests via tools/_probe.py, …]` citations in an accepted spec are
a debt rather than a finish.

**The semantics are green before any route exists.** T2 is the whole of
[spec §3.7](spec.md#37-what-a-reported-position-does-to-the-stored-one)'s six-branch rule and
[§3.6](spec.md#36-playback-reporting)'s effects table as pure functions with a table-driven test,
and no route lands until it passes. Every finding this feature's measurements produced — the count
that moves at `Start`, `max(count, 1)`, the strict boundaries at tick precision, the positionless
stop that counts twice — is a row in that table, asserted against code that has no clock, no
database and no HTTP ([plan §8](plan.md#8-testing-strategy)). The route tasks then prove the
*wiring* once each rather than re-proving the rule five times.

**The write path lands before the live path.** Marks (T5, T6) are load-apply-store against a
finished schema; reports (T8) additionally need the in-memory registry (T7), which needs a clock
it does not own. Splitting them that way keeps the one genuinely new mechanism — extrapolated
positions and a sweep that commits them — behind a boundary that is unit-testable without
sleeping, and it means `/Sessions` (T9) reads a registry that already answers correctly.

**Routes land across three tasks, so the exact-set check carries an interim list.**
`test_no_route_ships_ahead_of_its_feature` asserts the served routes equal the surface of the
implemented features; T5, T6 and T8 each add to an explicit interim list — the device 002, 005 and
006 all used — and T13 deletes it by putting `"007"` in `IMPLEMENTED_FEATURES`.

**What this feature inherits is a finished schema, and that is the point.** `item_user_data` has
carried every column 007 needs since 003, with **no foreign key to `items`** on purpose
([plan §4](plan.md#4-data-model)); 005 already reads those rows into every response, rolls
containers up per page and gates `PlayedPercentage` on `Fields`. 007 adds the first *writers*. The
one thing that inheritance costs is stated in T3: a writer touching this table for the first time
is exactly when somebody "fixes" the missing foreign key, and the fix deletes a user's history the
first time a share mounts slowly.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files it
references on 2026-08-28 before being accepted. Four things changed, and the first is the class
006's gate taught, back for the very next feature:

| The draft said | It was |
|---|---|
| The §3.7 branches are proven at route level against the seeded world | **The world has exactly one runtime.** `tests/fixtures/query.py` gives `RUNTIME_TICKS` to a single film — the one at `DATED_OFFSET`, one hour, which is also the only item carrying a resume position — and to nothing else: no episode, no track, no album. A rule that is a function of runtime therefore had one item to run on, and **row 5 — the short-item branch OQ-6 opened and measured — had no world at all**, because nothing in the fixture is shorter than five minutes. T4 now extends the world with the 215-second track the probe measured and a runtime on the episodes, and T8's table names the item each branch needs |
| `/Sessions` reads `LastPlaybackCheckIn` live from the registry ([plan §6.6](plan.md#66-what-the-session-row-stores)) | **Nothing has ever written the stored column.** `last_playback_check_in` has one reader (`api/sessions.py:to_wire`) and one writer that only copies it back (`SessionRepository.upsert`); `SessionRepository.touch` — the flusher's call — writes `last_activity_date` alone. "The activity flusher's existing 30-second cycle writes both columns in its one pass" is a change to 002's flusher, not a property of it, and the draft had no task making it. T7 carries it, with the test that a report advances the stored column only after a flush |
| OQ-7 is mentioned in the ordering as a thing 010 will settle | **[Plan §6.8](plan.md#68-measured-at-the-gate-and-what-stays-owed) gives it to this list**: the fixture library can build an empty container, so the empty-subtree answer is an Atrium-side decision to take here with the source reading recorded — not a differential's finding later. It is T11, and the decision lands in [behaviours](../../docs/compatibility/behaviours.md) rather than in the `_rolled` docstring where it lives today. A decision recorded only in a docstring is 006 T3's class exactly: an exception nobody could see had been withdrawn |
| A task writes AC-16's delete-rescan-restore test | **003 already wrote it.** `tests/library/test_removal.py` holds both halves — `test_a_deleted_file_disappears_from_queries_and_its_user_data_survives` and `test_restoring_the_file_revives_the_item_with_the_same_identifier` — each with a favourite *and* a resume position planted before the file is unlinked, because 003's AC-11 is this criterion seen from the other side. AC-16 is a map entry, which is what [plan §1](plan.md#1-approach) meant by "AC-16 needs no code at all beyond not breaking it" |

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — The probe pays the gate's debt: four batteries, one script

- [x] **Changes:** `tools/probe_playstate.py` grows the four batteries the plan gate ran as hand
  requests ([plan §6.8](plan.md#68-measured-at-the-gate-and-what-stays-owed)): a **playing-session
  battery** that starts a playback and reads `/Sessions` back — the `NowPlayingItem` slot between
  `DeviceName` and `DeviceId`, its property width, the absence of `UserData` inside it, and
  `PlayState` replaced rather than merged after a progress that omits `CanSeek` and `VolumeLevel`;
  a **refusal battery** over the mark routes — unknown item, non-GUID `itemId`, no token,
  `datePlayed=banana`; a **report-edge battery** — negative-position `Stopped`, positionless
  `Progress`, a `Start` carrying 30%, a non-JSON body, a non-GUID `ItemId`; and a **by-name
  favourite battery** — an artist marked, its `Key` read, restored. Where the probe now covers a
  claim cited as `[probe: manual requests via tools/_probe.py, …]`, `spec.md` and `plan.md` change
  the citation to name the script. `tools/README.md`'s row and its writes table say what the new
  batteries touch and how they clean up.
- **Depends on:** —
- **Verified by:** `python3 tools/probe_playstate.py --allow-writes` against the reference prints
  every battery's conclusion and leaves the library pristine (the script's own final check); and
  `uv run pytest tests/` plus the 3.9 floor job stay green, because the probe is
  standard-library-only and the suite opens no connection. The citations changed in `spec.md` and
  `plan.md` are grep-checkable: no `manual requests via tools/_probe.py` remains for a claim this
  script now measures.
- **Spec reference:** §3.2, §3.3, §3.6, AC-21, AC-22

**Done (2026-08-28).** Four batteries, one run, and the debt is paid: every claim the plan gate
took with a scratch script is now `python3 tools/probe_playstate.py --allow-writes`. Two of them
came back with more than the question asked.

**`NowPlayingItem`'s width is the item's, not the shape's.** Two runs picked two different movies
and measured **41 and 40 properties** — the difference being `IsHD`, null on one of them and
therefore omitted like every null. [Spec §3.6](spec.md#36-playback-reporting) had recorded "a
measured movie carried 41 properties" as if it were the shape's width; it is one item's, and 010's
differential comparing property *counts* would have reported a difference that was only the item
talking. The spec now says so.

**The plan's "reproduces for free" is half free.** The gate had measured that a non-JSON body and
a non-GUID `ItemId` answer `400` validation problem details and stopped there. Read at the key
level, the reference's `errors` map names **two** things: the binder's own key — `"$"` with the
parser's byte position, or the **empty string** with `The supplied value is invalid.` — beside
**the body parameter the route declares**, which is `playbackStartInfo`, `playbackProgressInfo`
or `playbackStopInfo`. One failure, three spellings, none of them anything the client sent, where
`compat/errors.validation_errors` keys on the model's field (`ItemId`). A path parameter's
refusal already matches byte for byte (`itemId`, `The value 'banana' is not valid.`); a body's
does not. Recorded in [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)
with the body, amended in [plan §6.1](plan.md#61-the-report-routes), and the reproduction is now
an explicit T8 decision rather than an inherited assumption.

Everything else confirmed the accepted documents: the `NowPlayingItem` slot between `DeviceName`
and `DeviceId`, no `UserData` inside it, `PlayState` replaced whole (`CanSeek: false` and no
`VolumeLevel` after a progress omitting both), the position advancing +2.0s over two seconds of
silence, the four mark refusals on behaviours §1.11's existing shapes, the negative-position
`text/plain` `400`, a positionless `Progress` leaving the stored position alone, a `Start` at 30%
leaving it at 0, and an artist's `Key` measuring the dashed form of its own 32-hex `ItemId`.
`tools/_probe.py` grew one thing to make this possible: `raw_body`, because `json.dumps` turns
`{not json` into a valid JSON *string* and measures a different refusal than the one asked about.

## T2 — `domain/playstate.py`: every semantic, pure, and the table that proves it

- [x] **Changes:** new `src/atrium/domain/playstate.py` with the contracts
  [plan §5](plan.md#5-contracts) declares — `Outcome`, `resolve`, `on_start`, `on_report`,
  `on_stop_without_position`, `on_mark_played`, `on_mark_unplayed`, and the three constants
  `MIN_RESUME_PCT = 5`, `MAX_RESUME_PCT = 90`, `MIN_RESUME_DURATION_SECONDS = 300`. No I/O, no
  clock: `when` arrives as an argument. New `tests/unit/test_domain_playstate.py` is the
  table: every row of [§3.7](spec.md#37-what-a-reported-position-does-to-the-stored-one) with the
  tick each side of both boundaries, and every row of
  [§3.6](spec.md#36-playback-reporting)'s effects table.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_domain_playstate.py -q` — the six branches, the
  strict comparisons at exact ticks (5% keeps, one tick below discards; 90% keeps, one tick above
  plays), `on_start` raising the count while clearing `played`, the bare mark's `max(count, 1)`
  against a dated mark's increment, and the positionless stop counting a second time. Plus
  `uv run mypy` and `tests/unit/test_import_directions.py`, which is what says `domain/` imports
  no HTTP and no SQL.
- **Spec reference:** §3.4, §3.6, §3.7; AC-3, AC-4, AC-12, AC-13, AC-17, AC-18

**Done (2026-08-28).** Forty-three cases, and two things the task statement did not have.

**`UserItemData` moved into the domain.** [Plan §5](plan.md#5-contracts) says these are functions
"from `UserItemData` to `UserItemData`", and that record lived in `db/item_queries.py` — which
`domain/` may not import, asserted by `test_a_domain_module_imports_nothing_above_it`. So the
choice was a second record or the right home, and the record is a domain record: 005 defined it
inside the query module because 007 did not exist yet to own it. It is now
`domain/playstate.py`'s, `db/item_queries.py` imports it, and the one docstring that named its old
home says the new one. No behaviour moved with it.

**Row 4's second clause decides nothing.** [Spec §3.7](spec.md#37-what-a-reported-position-does-to-the-stored-one)
called the "within one second of the end" clause "not redundant" and explained that a long item's
90% can still be minutes from its end — which is true and points the *other* way: a position
within one second of the end of anything longer than ten seconds is far *above* 90%, so the
percentage clause has already fired, and anything shorter than five minutes is completed by row 5
regardless. Checked exhaustively over runtimes from one second to two hours at every boundary
position, **no report distinguishes the rule with the clause from the rule without it**. The
clause is implemented because the reference has it and because lowering
`MinResumeDurationSeconds` would give it something to decide; the spec's paragraph now says that
instead of the reverse.

The rest of the table confirmed the measurements: the strict boundaries at exact ticks — computed
as integers, because `position / runtime * 100` moves the boundary by a tick on awkward runtimes —
the count moving at `Start` while `Played` goes false, the `Start` position that is not written,
`max(count, 1)` against the dated increment, the positionless stop counting twice, and the
mid-range branch leaving `Played` alone, which is how "played with a resume position" is reachable
at all. Two sweeps run over every transition: none of them touches the favourite flag, and none
mutates the record it was given.

## T3 — `UserDataRepository`: two methods, and the foreign key that stays absent

- [x] **Changes:** `src/atrium/db/repositories.py` grows `UserDataRepository` with `get` (the
  default row when absent — absence is a state, not a gap) and `put` (upsert), returning and
  taking the domain record rather than an ORM row (ADR-0003). Its docstring carries the argument
  the model's already does, pointed at writers: the missing foreign key is
  [spec §4](spec.md#4-data-the-feature-owns)'s survival guarantee, and a writer is who deletes it.
- **Depends on:** T2 (the record it stores is the one the transitions produce)
- **Verified by:** `uv run pytest tests/unit/test_repositories.py -q` — a `get` for a user with no
  row answers the default; a `put` then `get` round-trips every column; a second `put` replaces
  rather than duplicating; and two users' rows for one `item_key` are independent. Plus the
  standing `tests/unit/test_db_schema.py`: no migration appeared.
- **Spec reference:** §4; plan §4, §5

**Done (2026-08-28).** Two methods, and the tests are mostly about what the class must *not*
grow.

**The sweep had never been extended.** `tests/unit/test_repositories.py` opens with a walk over
every public method of every repository asserting that no ORM row escapes `db/` — and its
`REPOSITORIES` tuple had held the same three classes since 002, so `LibraryRepository`,
`ItemRepository` and `MetadataRepository` are all outside it. `UserDataRepository` is in it now,
with `atrium.domain.playstate` in the allowed-module set; the three older ones are a separate
change and are noted here rather than smuggled in.

Four of the seven tests assert absences rather than behaviour, because that is where this table
gets damaged: a `put` carrying a rolled-up `unplayed_count` stores nothing (a stored aggregate is
the cache [spec §3.5](spec.md#35-aggregation) forbids, and `put` is where somebody would add it);
a row can be written for an `item_key` no item has ever had, which is the missing foreign key
asserted rather than trusted; deleting the user *does* take their rows, which is the one cascade
there is; and two users' rows for one key stay independent (AC-7's floor).

## T4 — The query layer's two additions, and the world that can prove them

- [x] **Changes:** `src/atrium/db/item_queries.py` grows `leaf_descendants(item_id, user)`,
  the cascade's target set: one recursive scoped query through the existing visibility scope,
  file-backed types only, never the container's own row
  ([plan §6.2](plan.md#62-the-mark-routes)). `tests/fixtures/query.py` gains what the gate found
  missing: a **short track** at the probe's measured 215 seconds, runtimes on the first series'
  episodes, and handles for both.
- **Depends on:** T3
- **Verified by:** `uv run pytest tests/unit/test_item_queries.py tests/unit/test_query_fixture.py -q`
  — `leaf_descendants` of a season is its episodes, of a series is every episode through its
  seasons, of a film is empty, and a soft-removed episode and another user's invisible library are
  both absent from it. The fixture's invariant test asserts the short track's runtime is under
  `MIN_RESUME_DURATION_SECONDS` and the film's is over it, so the two branches cannot silently
  become the same case.
- **Spec reference:** §3.4, §3.5; plan §6.2, §6.3

**Done (2026-08-28).** One query method, not two, and the fixture change turned out to pin
something 005 never had.

**`user_data_for` was not written, and [plan §6.3](plan.md#63-one-items-userdata-on-demand) now
says why.** A method answering a `UserItemData` answers the stored row and the rollup and **not
the runtime** — so a mark route holding one would still have to compute `PlayedPercentage` from
position over runtime itself, which is a second place that expression is spelled out and exactly
the drift §6.3 exists to prevent. The mark routes will instead resolve the item through
`ItemQueryRepository.run` — the same call `GET /Items/{itemId}` makes — and hand the
`HydratedItem` to the same DTO builder a list row goes through, so the identity is structural
rather than asserted. The plan is amended in this change rather than in a follow-up.

**`CumulativeRunTimeTicks` had no golden coverage at all.** Giving the first series' episodes and
the first track a runtime rewrote eight goldens, and the diff is not only the two `RunTimeTicks`
that were asked for: `CumulativeRunTimeTicks` appears for the first time on the season, the
series, the album and the artist. It was absent from every golden in the repository, because
nothing under a container had a runtime for it to sum — a 005 emitter with a golden-shaped hole
in it, closed by a fixture change made for another reason.

The world now answers three runtime shapes that the resolution rule needs and had one of: the
215-second track the probe measured OQ-6 on (the only item under the floor, asserted against
`MIN_RESUME_DURATION_SECONDS` itself rather than a number written twice), forty-five-minute
episodes on the first series, and **no runtime at all** on the other two series, which keeps row
2's "the runtime is unknown" reachable in the same world.

## T5 — The favourite pair: two routes, idempotent both ways, no cascade

- [ ] **Changes:** `src/atrium/api/user_library.py` grows `POST` and
  `DELETE /UserFavoriteItems/{itemId}` — the reference's `UserLibraryController`, which is why
  they are here and not in `api/playstate.py` ([plan §3](plan.md#3-modules)). Each resolves the
  item through the 005 visible-item lookup, writes **one row — the item's own, container or
  not** — and answers the `UserItemDataDto` built by `user_data_for`. The route list in
  `tests/conformance/test_routes.py` gains its interim entries.
- **Depends on:** T4
- **Verified by:** new `tests/unit/test_favourite_routes.py` — `POST` twice answers `200` twice
  and leaves one favourite; `DELETE` twice answers `200` twice and leaves none; favouriting a
  season leaves every episode unfavourited (§3.3, measured); an unknown or invisible item is the
  problem-details `404`, a non-GUID path the validation `400`, no token the empty `401`; and the
  response body's `UserData` equals the same item's `UserData` in a `GET /Items/{itemId}`.
- **Spec reference:** §3.3; AC-2, AC-21

## T6 — The played pair: the mark, the date that changes more than the date, and the cascade

- [ ] **Changes:** new `src/atrium/api/playstate.py` — the reference's `PlaystateController` —
  with `POST /UserPlayedItems/{itemId}?datePlayed=` and `DELETE /UserPlayedItems/{itemId}`. A leaf
  applies the transition to its own row; a **container applies it to every leaf descendant and
  never to itself** ([spec §3.4](spec.md#34-played-state), measured). `datePlayed` binds as a
  `WireDateTime` query parameter, which is what makes `datePlayed=banana` the measured validation
  `400`. The response is the item's fresh `UserItemDataDto`, recomputed after the sweep in the
  same transaction. `server.py` includes the router — before `items.router`, like every literal
  path — and the interim route list grows.
- **Depends on:** T5
- **Verified by:** new `tests/unit/test_played_mark_routes.py` — marking played resets the
  position and sets the count to one, marking twice leaves it at one, `datePlayed` increments and
  moves the date; unmarking clears all four; marking a season writes every episode's row and
  **leaves the season's own row absent**, with the response reading `UnplayedItemCount: 0`
  immediately; unmarking a season sweeps the same set back; the four refusal shapes answer as
  T1's battery measured them.
- **Spec reference:** §3.4; AC-3, AC-4, AC-5, AC-21

## T7 — `users/playing.py`: live playback, extrapolated on read, and the column nobody wrote

- [ ] **Changes:** new `src/atrium/users/playing.py` with `PlayingNow` and `NowPlayingRegistry`
  exactly as [plan §5](plan.md#5-contracts) declares them — `start` and `update` **replace the
  whole record**, `snapshot` computes *last reported + unpaused elapsed, capped at the runtime*,
  `reap(older_than)` returns the stale playing sessions, and `now`/`monotonic` are injected like
  `SessionRegistry`'s clock. `SessionRegistry.flush` and `SessionRepository.touch` grow the second
  column so `last_playback_check_in` finally has a writer
  ([plan §6.6](plan.md#66-what-the-session-row-stores)); the registry supplies the live value.
- **Depends on:** T2
- **Verified by:** new `tests/unit/test_now_playing_registry.py`, with an injected clock and no
  sleeping — a report then 90 seconds of wall clock reads a position 90 seconds further on; a
  paused session's position does not move; the extrapolation stops at the runtime; a progress
  omitting `CanSeek` after a start carrying it reads back `False`; `reap` returns exactly the
  sessions past the threshold. `tests/unit/test_session_registry.py` gains the flush assertion:
  a recorded check-in reaches the database on the flush and not before.
- **Spec reference:** §3.6, §3.8; plan §6.4, §6.6

## T8 — The three reporting routes: `204` everywhere, and the rule on every position

- [ ] **Changes:** `src/atrium/api/playstate.py` grows `POST /Sessions/Playing`,
  `/Sessions/Playing/Progress` and `/Sessions/Playing/Stopped` — bodies as `AtriumModel`s with
  every field optional, `ItemId` as `WireGuid | None`, the item resolved through the same visible
  lookup, `204` and an empty body in every case including an id that names nothing. `Start`
  applies `on_start` and registers; `Progress` applies `on_report` only when a position arrives;
  `Stopped` branches on `Failed`, then on whether a position came, and clears the registry. The
  one guard past binding is the negative position, answering behaviours §1.11's `text/plain`
  refusal. The interim route list grows to the full five.
- **Depends on:** T6, T7
- **Verified by:** new `tests/unit/test_playback_report_routes.py` — all three answer `204` with
  an empty body; a `Progress` with no `MediaSourceId` and no `Start` before it lands its position;
  40% then 20% reads back 20%; an unknown id answers `204` and creates no row; a `Start` raises
  the count, sets the date and clears `played`; a stop with a position leaves the count alone
  while a positionless one raises it again; a `Progress` at 95% marks the item played mid-playback
  and clears the position; a `Failed: true` stop writes nothing; a negative position is the
  `text/plain` `400`; a non-JSON body and a non-GUID `ItemId` are the validation `400`. The
  branch table runs over T4's items — the hour-long film for the percentage branches, the
  215-second track for the short-runtime one, an episode with no runtime for the unknown case.
- **Spec reference:** §3.6, §3.7; AC-8, AC-9, AC-10, AC-11, AC-14, AC-17, AC-18, AC-19, AC-21

## T9 — `/Sessions` grows what is playing

- [ ] **Changes:** `src/atrium/api/sessions.py` — `PlayState` grows the six measured fields with
  `PositionTicks` **first**, the eleven in the measured order, the nullable ones suppressed when
  the last report omitted them; `SessionInfo` grows `now_playing_item` **between `device_name` and
  `device_id`**, absent when nothing plays; `to_wire` reads the snapshot and the live check-in
  from the registry. `NowPlayingItem` is built through 005's DTO builder with
  `enable_user_data=False` — the one measured item shape with no `UserData` — and the nine
  media-derived properties v1 cannot say stay absent as
  [spec §3.6](spec.md#36-playback-reporting)'s named gap.
- **Depends on:** T8
- **Verified by:** `tests/conformance/test_session_routes.py` — the not-playing entry's
  twenty-three fields are unchanged (nulls are suppressed, so growing the model moves nothing);
  during playback the entry carries `NowPlayingItem` in the measured slot with no `UserData`
  inside it, and `PlayState` mirrors exactly the last report — a progress omitting `CanSeek`
  reads back `CanSeek: false`; and a second `/Sessions` read seconds later shows the position
  advanced without a report in between.
- **Spec reference:** §3.6, §3.8; AC-22

## T10 — The reaper: one commit path, shared with the stop that never came

- [ ] **Changes:** `server.py` starts a reaping task beside the activity flusher, sweeping on the
  reference's five-minute cadence for sessions silent past five minutes
  ([plan §6.5](plan.md#65-the-reaper)); the commit goes through **the same function the `Stopped`
  handler uses**, with the extrapolated snapshot position, so "a stop arrived" and "we gave up
  waiting" cannot drift apart. The cadence and threshold are named constants in one place.
- **Depends on:** T8, T9
- **Verified by:** new `tests/unit/test_session_reaping.py` with an injected clock — a start, a
  progress at 40%, six minutes of silence, one sweep: `NowPlayingItem` is gone and the stored
  position is the report **plus the silence**, capped at the runtime in the case that reaches it;
  a paused session's reaped position is its last reported one; and the reaped outcome is asserted
  equal to an explicit `Stopped` at that same position, which is what says both paths are one.
- **Spec reference:** §3.8; AC-15

## T11 — Aggregation through mutation, the gated percentage, and OQ-7

- [ ] **Changes:** no production change is expected to the rollup — 005 computes it — so this task
  is the criterion and the one decision left open. New
  `tests/conformance/test_user_data_aggregation.py` mutates the world between assertions, and
  **OQ-7 is decided**: an empty container answers `Played: false` here, where the reference's
  source reads it as vacuously played. The argument (an emptied series must not read watched) moves
  out of `_rolled`'s docstring into
  [behaviours](../../docs/compatibility/behaviours.md) as a recorded divergence with the source
  citation, [spec §3.5](spec.md#35-aggregation)'s OQ-7 block closes naming it, and 010 gets the
  measurement as an owed differential rather than an open question.
- **Depends on:** T6
- **Verified by:** `uv run pytest tests/conformance/test_user_data_aggregation.py -q` — a season's
  `UnplayedItemCount` tracks a single episode mark, a rescan that adds an episode and a removal;
  a bare container row carries `UnplayedItemCount` and `Played` and **no** `PlayedPercentage`,
  while `Fields=RecursiveItemCount` carries it; and an empty season answers `Played: false` with
  `UnplayedItemCount: 0`.
- **Spec reference:** §3.5; AC-6, AC-20, OQ-7

## T12 — One object, two paths: the mark response is the list row

- [ ] **Changes:** new `tests/conformance/test_user_data_identity.py` — the cross-cutting
  assertions [plan §8](plan.md#8-testing-strategy) asks for, which are about *agreement* rather
  than about any one route: the serialised `UserData` of a mark response and of the same item in
  a list request compare byte for byte; `Key` and `ItemId` are present on every item of every
  005 response and both equal the item's id; and two users' state on one item is fully
  independent through every write this feature owns.
- **Depends on:** T8
- **Verified by:** `uv run pytest tests/conformance/test_user_data_identity.py -q` — the byte
  comparison over a leaf and a container, the `Key`/`ItemId` sweep over a list, an item and a
  by-name row, and the two-user matrix: favourite, mark, report and unmark for one user, read
  back for both after each.
- **Spec reference:** §3.1, §3.2; AC-1, AC-7

## T13 — The acceptance map, the routes' exact set, and 007 is Implemented

- [ ] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_007` — twenty-two rows,
  AC-16's naming 003's two existing removal tests; `IMPLEMENTED_FEATURES` in
  `tests/conformance/test_routes.py` gains `"007"` and the interim list is deleted;
  `spec.md`, `plan.md` and this file are marked `Implemented`; `specs/README.md`'s status table
  and narrative, `docs/roadmap.md` and `AGENTS.md`'s "where the project is" say so; and this file
  gains **what 007 owes 008, 009 and 010**.
- **Depends on:** T1–T12
- **Verified by:** the full gate — `uv run ruff check . && uv run ruff format --check . && uv run
  mypy && uv run pytest` — with `test_every_implemented_feature_has_a_map`,
  `test_the_specification_still_has_the_criteria_this_map_expects` and
  `test_no_route_ships_ahead_of_its_feature` green, which together say the map is complete, the
  criteria count matches the specification and exactly the five 007 routes are served.
- **Spec reference:** §5, §6

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all
      twenty-two — has a passing test, by name, in `FEATURE_007`.
- [ ] Every endpoint reaches the level [spec §6](spec.md#6-conformance) declares, and the
      `UserData` shape's L3 is the goldens 005 already pins plus the byte comparison of T12.
- [ ] The five routes are served, `"007"` is in `IMPLEMENTED_FEATURES`, and no route exists
      outside [`surface.yaml`](../../docs/compatibility/surface.yaml) — the five rows were in the
      file before this list was written, so the check is registration, not listing.
- [ ] The feature ends owning **no schema**: no table, no column, no migration
      ([plan §4](plan.md#4-data-model)), and `item_user_data` still has no foreign key to `items`.
- [ ] Nothing about live playback is persisted: a restart empties `/Sessions`' playback and costs
      at most the extrapolation since each session's last report.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same change
      that learned it.
- [ ] Every measurement a task took against the reference is in the spec or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) with provenance — T1's four
      batteries first among them, and the manual-request citations they upgrade.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.
