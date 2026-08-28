---
feature: 007-user-data-and-playstate
title: User data and playstate — implementation plan
status: Accepted
created: 2026-08-28
updated: 2026-08-28
accepted: 2026-08-28
amended: 2026-08-28 at the gate, which measured §6.8's catalogue before accepting — §1's sequencing note, §5's replacement semantics, §6.1's error floor, §6.4 rewritten around the measured session shape, §6.7, §6.8, §7, §9; the playing-session block and AC-21/AC-22 went back into the spec
spec_status_required: Accepted
spec_status_actual: Accepted
---

# 007 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour.

## 1. Approach

Everything this feature stores was already waiting for it. Five decisions carry the rest.

**No table, no column, no migration.** `item_user_data` has existed since 003, complete —
favourite flag, played flag, count, position, last-played date — keyed on `(user_id, item_key)`
with **deliberately no foreign key to `items`**, because the row outliving the item *is* spec
§4's survival guarantee (003 §3.8; the docstring on `db/models.py:ItemUserData` carries the
argument). 005 already reads these rows into every response. 007 adds the first writers, and a
writer that finds the schema finished should treat that as the design telling it where the
boundaries are: `item_key` is the derived identity, never a row reference, which is why AC-16
needs no code at all beyond not breaking it.

**Every state transition is a pure function, and the wire rules live in exactly one place.**
The measured semantics — the six-branch resolution, start-counts-the-play, the bare mark's
`max(count, 1)`, last-writer-wins — go in `domain/playstate.py` as functions from
`UserItemData` to `UserItemData`, no I/O, no clock of their own. The spec's sharpest findings
(§3.6's effects table, §3.7's strict-at-tick boundaries) become table-driven unit tests against
pure code, and the route layer shrinks to load-apply-store. This is `domain/`'s charter in
`architecture.md` §1 — "user-data semantics" was listed there before this feature existed.

**Live playback state is memory, and the ticking position is computed at read time.** The
reference runs a per-session one-second timer to extrapolate the position (spec §3.8); the
observable is the *value*, not the timer. So `users/playing.py` keeps one in-memory record per
session — last report, its monotonic timestamp, paused flag — and every read (a `/Sessions`
response, the reaper's commit) computes *last reported + unpaused elapsed, capped at runtime*.
Same wire, no per-second churn, nothing to persist: a restart loses only what the reference
loses (`domain/session.py` already documents the decision). The reaper is a lifespan task
beside the 002 activity flusher, sweeping on the reference's own cadence and committing through
the same stop transition every real report uses.

**The cascade is a write-time sweep over the leaves, resolved by the query layer that already
knows visibility.** Marking a container played fans out to its leaf descendants — the measured
shape: episodes written, the season's own row never touched — and the leaf set comes from
`ItemQueryRepository`'s scope machinery (005 plan §6.2's `_descendants`), not from a second
subtree walk. Reads stay derived: 005's per-page rollup keeps answering `Played` and
`UnplayedItemCount`, so AC-6's rescan cases cost nothing here.

**The mark routes answer with the same object the list rows carry.** `POST /UserFavoriteItems`
returns a `UserItemDataDto`, and it is built by the same code path that fills `UserData` on a
005 row — stored row plus rollup plus runtime — so the mark response can never drift from what
the next list request shows. The measured field order (spec §3.1) is 005's declared order; there
is nothing new to serialise.

**The sequencing note, paid at the gate:** `api/sessions.py`'s `PlayState` model was declared
by 002 with five fields and a docstring saying "Feature 007 fills it". The gate measured what a
playing session actually carries before T1 writes a line — 005 T1's lesson, pointed at
`/Sessions` — and the measurement earned its keep three times over: `PlayState` is **replaced
whole by each report**, not merged (a progress omitting `CanSeek` reads back `false`);
`NowPlayingItem` sits in a specific slot and is the one measured item shape with **no
`UserData` inside**; and nine of its 41 properties are media-derived facts v1 cannot yet say
(§6.4). All of it is spec §3.6's playing-session block now.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–006 | [006 plan §2](../006-images/plan.md#2-inherited-decisions) |
| `item_user_data`: the key, the no-FK survival rule, ticks as the unit | 003 ([spec §3.8](../003-library-configuration-and-scanning/spec.md)), `db/models.py` |
| `item_key` equals the item's derived identity | 003 §3.6, [behaviours §1.4](../../docs/compatibility/behaviours.md#14-item-identifiers-are-32-lowercase-hex-characters) |
| `UserData` hydration, the per-page rollup, `enable_user_data` | [005 plan](../005-item-query-api/plan.md), `db/item_queries.py` (`_rolled`, `_user_data`) |
| The scope machinery for subtrees (`_descendants`, the CollectionFolder fast path) | 005 plan §6.2, `db/item_queries.py` |
| Sessions: the registry, the 30-second activity flush, `last_playback_check_in` stored | [002 plan §6.5](../002-authentication-users-and-sessions/plan.md), `users/sessions.py` |
| `PlayState` and `Capabilities` are objects-not-nulls; the 23-field session order | 002 T12, `api/sessions.py` |
| Problem-details errors and the extended validation handler | behaviours §1.11, `compat/errors.py` |
| Parameter canonicalisation, `api_key` seeding, the ignored-parameter recorder | [005 plan §6.12](../005-item-query-api/plan.md#612-parameter-plumbing), `compat/query_params.py` |
| Request models ignore unknown properties | `compat/model.py` (`extra="ignore"`), behaviours §1.12's lenient direction |
| Repositories return domain objects; no ORM row crosses the boundary | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |

**Deviations:** none.

## 3. Modules

```
src/atrium/
├── domain/
│   └── playstate.py     pure: the six-branch resolve and every transition (start, report,
│                        stop, mark, unmark). No I/O, no clock — time arrives as arguments
├── users/
│   └── playing.py       NowPlayingRegistry: live per-session playback in memory,
│                        extrapolated position reads, the five-minute reaper task
├── api/
│   ├── playstate.py     the reference's PlaystateController: POST/DELETE /UserPlayedItems,
│   │                    the three /Sessions/Playing* routes
│   ├── user_library.py  grows the favourite pair — the reference's UserLibraryController
│   └── sessions.py      to_wire grows NowPlayingItem and PlayState read from the registry
└── db/
    └── repositories.py  grows UserDataRepository: read and upsert one row, resolve the
                         leaf set for a cascade
```

The controller split mirrors the reference on purpose — `api/` is one module per Jellyfin
controller (`architecture.md` §1), and favourites live in `UserLibraryController` there while
the played mark and the reports live in `PlaystateController`. `users/playing.py` sits beside
`users/sessions.py` because they are the two halves of a session's life the same way tokens and
sessions were in 002 — created together, read together — but playback state is *ephemeral on
purpose*, so it gets its own module rather than rows in the registry that flushes.

## 4. Data model

**No table, no column, no migration.** The columns 003 created are given their meaning:

| Column | Written by | Meaning after 007 |
|---|---|---|
| `is_favorite` | The favourite pair | Spec §3.3; on containers it is the container's own flag, never an aggregate |
| `played` | Marks, and rows 2/4/5 of the resolution | Spec §3.4, §3.7 — cleared by a start (spec §3.6) |
| `play_count` | Start reports, positionless stops, `datePlayed` marks; a bare mark only raises it to 1 | Spec §3.6's effects table |
| `playback_position_ticks` | Every position-bearing report, through the resolution; zeroed by marks | Spec §3.7, last-writer-wins |
| `last_played_date` | Start reports and marks; cleared by unmark | "When playback last began", not ended |

Nothing about live playback is stored, deliberately: `NowPlayingItem` and `PlayState` change
several times a minute, die with the session, and the reference loses them on restart too
(`domain/session.py`). What must survive — the resume position — is already persisted on every
progress report, so a crash costs at most the extrapolation accrued since the last report,
which is exactly what the reference's own restart loses.

No new index. `/UserItems/Resume` filters `playback_position_ticks > 0` per user and sorts by
`last_played_date`; the primary key already serves the per-user probe, and a resume list is as
long as the films a person is in the middle of. A pattern-driven index here would be 004's
lesson applied to a query with single-digit rows; it waits for a measurement.

## 5. Contracts

**`domain/playstate.py`** — pure, and the only place the semantics live:

```python
class Outcome(Enum):          # what a resolved position decided
    DISCARDED = ...           # below the floor: store 0, Played untouched
    RESUMABLE = ...           # store P, Played untouched (how played-with-position happens)
    COMPLETED = ...           # store 0, Played True

def resolve(position_ticks: int | None, runtime_ticks: int | None) -> Outcome
    # rows 2-6 of spec §3.7: None runtime → COMPLETED; the strict 5/90 comparisons at tick
    # precision; the one-second-of-the-end clause; the 300s runtime floor. Row 1 (a stop with
    # no position) is the caller's branch, because only stops have it.

def on_start(data: UserItemData, when: datetime) -> UserItemData
    # count += 1, last_played = when, played = False, position untouched (spec §3.6)
def on_report(data: UserItemData, position_ticks: int | None, runtime: int | None) -> UserItemData
    # progress or stop-with-position: resolve and apply; no count change
def on_stop_without_position(data: UserItemData) -> UserItemData
    # played to the end: count += 1 again, played True, position 0
def on_mark_played(data: UserItemData, when: datetime, date_played: datetime | None) -> UserItemData
    # max(count,1) bare, increment dated; keep-or-set last_played; position 0 (spec §3.4)
def on_mark_unplayed(data: UserItemData) -> UserItemData
```

Callers may assume: no function reads a clock or touches storage; `on_report` with
`Failed: true` is never called (the route drops the report before the domain sees it, spec
§3.6 rule 4); thresholds are module constants named for the reference's
(`MIN_RESUME_PCT = 5`, `MAX_RESUME_PCT = 90`, `MIN_RESUME_DURATION_SECONDS = 300`).

**`users/playing.py`**:

```python
@dataclass(frozen=True)
class PlayingNow:             # a snapshot; position already extrapolated
    item_id: str
    position_ticks: int       # last reported + unpaused elapsed, capped at runtime
    is_paused: bool
    can_seek: bool
    play_method: str | None
    play_session_id: str | None
    media_source_id: str | None
    audio_stream_index: int | None
    subtitle_stream_index: int | None
    is_muted: bool
    volume_level: int | None
    last_check_in: datetime

class NowPlayingRegistry:
    def start(self, session_id, report) -> None
    def update(self, session_id, report) -> None      # progress; remembers paused-at
    def clear(self, session_id) -> PlayingNow | None  # stop; the final snapshot
    def snapshot(self, session_id) -> PlayingNow | None
    def reap(self, older_than: timedelta) -> list[tuple[str, PlayingNow]]
    async def run(self) -> None                       # the sweep loop; commits via callback
```

`start` and `update` **replace the whole record** — fields the new report omits are gone,
because that is what the reference's `PlayState` measurably does *(amended at the gate: the
draft had left merge-versus-replace to the implementer, which is exactly the decision a plan
exists to take)*. Time is injectable (`now` and `monotonic` callables, like
`SessionRegistry`), so the reap and the extrapolation are tested without sleeping. The
registry holds no database handle; the
reaper's commit callback is wired in `server.py`, and it routes through the exact function the
`Stopped` handler uses — one code path for "a stop arrived" and "we gave up waiting", which is
what the reference does by literally calling its own stop handler.

**`db.repositories.UserDataRepository`**:

```python
def get(self, user_id: str, item_key: str) -> UserItemData        # default row when absent
def put(self, user_id: str, item_key: str, data: UserItemData) -> None   # upsert
```

The cascade's leaf set comes from `ItemQueryRepository` with a recursive scoped query filtered
to leaf types — the same visibility the reference applies by passing the user into its own
sweep — so `UserDataRepository` stays a two-method row store and never learns the item tree.

## 6. Algorithms

### 6.1 The report routes

All three: authenticate (`require_user` — a report is an API route, tokens required as
everywhere outside images), parse the body as an `AtriumModel` with every field optional
(unknown properties ignored, `compat/model.py`), resolve the item **by id, visible to the
caller, not removed** through the 005 lookup. An unknown item answers `204` having recorded
nothing (spec §3.6 rule 1, measured on a well-formed id that names nothing) — and the gate
measured where the leniency stops, exactly where the plan had suspected the binding would
refuse: a non-GUID `ItemId` or a non-JSON body is `400` validation problem details, which
Pydantic validation through `compat/errors`' extended handler reproduces the *shape* of for
free — **and only the shape**: T1's probe read the `errors` keys, and a body failure names the
binder's own key (`$` or the empty string) beside **the body parameter the route declares**
(`playbackStartInfo`, `playbackProgressInfo`, `playbackStopInfo`), where
`compat/errors.validation_errors` keys on the model's field. **T8 measured what that actually
produced and reproduced the reference instead**: the framework keys on the *Python* field name,
so the answer was `{"item_id": …}` — snake_case on the wire, behaviours §1.1's exact failure, on
this project's first typed request body. The routes now name their body parameter after the
reference's and `validation_errors` files a body failure under `""` or `"$"` beside
`The <parameter> field is required.`; the `"$"` message stays this parser's and is a recorded
divergence (behaviours §1.11). `ItemId` binds as `WireGuid | None`, optional like everything
else, so an *absent* id still skips rather than refuses — measured `204`. A `Stopped` with a **negative** position refuses `400` with behaviours
§1.11's `text/plain` controller shape — one explicit guard in the route, mapped to the
existing `compat/errors` body (spec §3.6's error floor). Then:

| Route | Does |
|---|---|
| `Playing` | `on_start`; registry `start`; session `last_playback_check_in` advances |
| `Progress` | `on_report` when the body carries a position, nothing to the row otherwise; registry `update`; check-in advances |
| `Stopped` | `Failed: true` → registry `clear` only. A position → `on_report`. No position → `on_stop_without_position`. Registry `clear` |

`204` with an empty body in every case. The stored write happens per report, exactly as the
reference does at its check-ins — which is what makes rule 3 (a missing stop loses nothing but
the extrapolation) structural rather than clever.

### 6.2 The mark routes

`POST /UserPlayedItems/{itemId}?datePlayed=` parses the date through the wire-date parser
(`compat/dates`); the item resolves through the same visible-item lookup, the measured
problem-details `404` when it does not. A **leaf** applies
`on_mark_played` to its own row. A **container** resolves its leaf descendants — one recursive
scoped query, leaf types only, the caller's visibility — applies the transition to every leaf
row, and *does not touch its own row* (spec §3.4, measured). `DELETE` is the same sweep with
`on_mark_unplayed`. The favourite pair writes exactly one row — the item's own, container or
not (spec §3.3) — and never sweeps.

Every mark answers the item's fresh `UserItemDataDto` built by §6.3, which for a container
means the aggregate is recomputed *after* the sweep in the same transaction — the measured
response (`UnplayedItemCount: 0` the instant the season is marked) requires it.

### 6.3 One item's `UserData`, on demand

The mark responses need what 005 computes per page for one item: stored row, subtree rollup
when the item is a container, `PlayedPercentage` from position over runtime for a leaf. The DTO
built here must be byte-identical to the same item's `UserData` in the next list response —
asserted by a test, not by discipline.

**Which is why there is no `user_data_for(item_id, user)`** *(amended at T4, which was the task
that would have written it)*. A method answering a `UserItemData` answers the stored row and the
rollup and **not the runtime**, so the caller would still compute `PlayedPercentage` itself — a
second place where position-over-runtime is spelled out, which is the exact drift this section
exists to prevent. The mark routes instead resolve the item through `ItemQueryRepository.run` with
its id, the same call `GET /Items/{itemId}` makes, and hand the `HydratedItem` to the same DTO
builder a list row goes through. Identity is then structural rather than asserted, and the cost is
one hydration per mark — a route that has already written a row. The mark response never carries a container
`PlayedPercentage` (spec §3.5's field-gating: this path has no `Fields`), which falls out of
reusing the gated code rather than special-casing.

### 6.4 Extrapolation, and what `/Sessions` shows

A `snapshot` computes `position = reported + (monotonic_now - reported_at)` in ticks while not
paused, capped at the item's runtime when known; a paused session's position is frozen at its
report. No playing session → the empty `PlayState` 002 already sends, absent `NowPlayingItem`.

The measured shape (spec §3.6's playing-session block) pins the rest:

- **`SessionInfo` grows `now_playing_item` in the measured slot** — declared between
  `device_name` and `device_id` in `api/sessions.py`, `None` and therefore absent when nothing
  plays, so the not-playing 23-field order 002 pinned is untouched.
- **`PlayState` serialises the snapshot's fields and only those** — the nullable ones
  (`PositionTicks`, `VolumeLevel`, `AudioStreamIndex`, `SubtitleStreamIndex`,
  `MediaSourceId`, `PlayMethod`) suppress when the last report omitted them, which together
  with §5's replace-whole rule reproduces the measured `CanSeek: false` after a bare progress.
- **`NowPlayingItem` builds through 005's DTO builder at `Width.FULL` with
  `enable_user_data=False` and `omit=NOT_IN_NOW_PLAYING`** *(amended at T9, which measured the
  property list rather than the count)*. The shape is a **subtraction**: the measured 41
  properties are a full `/Items/{itemId}` body's 56 minus a named fifteen, so 005's existing
  `omit` mechanism expresses it exactly and no bespoke selection is needed. Five of the fifteen
  are properties v1 emits today; the other ten name properties no v1 emitter produces, and they
  are declared anyway as a **tripwire** — 008 adds `MediaSources`, and this set is what keeps it
  out of a session entry the reference does not put it in. The media-derived nine
  (`MediaStreams`, `Chapters`, `Width`, `Height`, `HasSubtitles`, `IsHD`, `VideoType`,
  `Trickplay`, `Container`) and `CriticRating` have no v1 source, stay absent, and are the spec's
  recorded gap — 006's `Chapter` pattern: the route is correct the day 008 gives the emitters
  data, and the differential sees the gap until then, named rather than silent.

`LastPlaybackCheckIn` reads from the registry (live over stored, §6.6) — a `/Sessions` poller
watches the position advance between reports exactly as against the reference (spec §3.8).

### 6.5 The reaper

A lifespan task beside the activity flusher: every **five minutes**, `reap(older_than=5min)`
returns the playing sessions whose last check-in is stale; each commits through the stop path
with its extrapolated snapshot position — the same `on_report` call a real stop makes — and
clears from the registry. The cadence and threshold are the reference's own constants (spec
§3.8), named in one place. On clean shutdown the reaper commits nothing extra, matching the
reference: what a restart loses is the extrapolation since each session's last report, which
the stored row never contained anywhere.

### 6.6 What the session row stores

`last_playback_check_in` is already a column, flushed rather than written per report: the
`NowPlayingRegistry` holds the live value, `GET /Sessions` reads it from there (the same
live-over-stored rule 002 plan §6.5 set for `LastActivityDate`), and the activity flusher's
existing 30-second cycle writes both columns in its one pass — a per-report synchronous write
would reintroduce the write-per-request that flush exists to avoid. The bounded cost is the
same one 002 stated: an unclean shutdown loses up to one interval of *timestamps*, never a
position, because positions are rows written per report (§6.1).

### 6.7 Parameter and body plumbing

The five routes declare their pinned spellings; canonicalisation and `api_key` seeding arrive
from 005 §6.12's startup walk unchanged. Bodies are Pydantic models with PascalCase aliases and
every field optional; `datePlayed` is the one query parameter with a value worth parsing, and
`datePlayed=banana` measured `400` validation problem details naming the parameter *(the gate
measured what this sentence had deferred)* — a `WireDateTime`-typed query parameter produces
exactly that through the extended handler. The ignored-parameter recorder keeps counting
anything undeclared, as everywhere.

### 6.8 Measured at the gate, and what stays owed

This section catalogued four batteries while the plan was written; the gate measured all four
before accepting, and **007 T1 folded all four into `tools/probe_playstate.py`**, so every claim
below is now reproducible by one command `[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-28]` rather than by a scratch script that
no longer exists. The answers are folded into §§6.1–6.7 and back into the spec (§3.2, §3.3,
§3.6, AC-21, AC-22):

1. **A playing session's wire shape** — the `NowPlayingItem` slot and 41-property width, the
   11-field `PlayState` and its replace-whole semantics, `NowPlayingQueue`/`FullItems` as
   empty arrays when the client sent none. The sharpest finding was the *absence*:
   `NowPlayingItem` carries no `UserData`.
2. **The mark routes' error shapes** — unknown item: problem-details `404`; `itemId=banana`:
   validation `400` naming the parameter; tokenless: the empty `401`; `datePlayed=banana`:
   validation `400`, nothing stored. Every one an existing behaviours §1.11 shape.
3. **Report edges** — a negative-position `Stopped` answers `400` `text/plain`
   `Error processing request.` (the controller-refusal shape, not a `500`); a positionless
   `Progress` leaves the stored position alone; a `Start` carrying 30% leaves it at 0; a
   non-GUID `ItemId` and a non-JSON body refuse `400` validation problem details — binding
   before leniency, as suspected.
4. **A favourite on a by-name item** — an artist: `200`, the DTO, restored clean; its `Key`
   measured as the dashed GUID (spec §3.2's second calibration).

What the sweep cannot reach stays owed: **OQ-7** (the empty container needs a library with
one — the fixture library can build it, so the task list owns it as an Atrium-side decision
with the source reading recorded); the paused-session ticker freeze (another ten-minute reap
against a paused session; the source is explicit and the cost is real — cited, not measured);
and cross-user visibility of marks (AC-7 is an Atrium-side test; the reference needs a second
account nothing here wants to create).

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Mark route: unknown, invisible or removed item | 005 lookup | Problem-details `404` (measured) | — |
| Mark route: `itemId` not a GUID | Path validation | Validation `400` naming the parameter (measured) | — |
| Report: body not JSON, or `ItemId` not a GUID | Body binding | Validation `400` (measured) | — |
| Report: `Stopped` with a negative position | Route guard | `400` `text/plain` `Error processing request.` (measured; behaviours §1.11's controller shape) | — |
| Report: well-formed `ItemId` naming nothing — unknown, invisible or removed | Lookup | **`204`**, nothing recorded (spec §3.6 rule 1) | — |
| Report: `Failed: true` | Body | `204`; registry cleared, row untouched | — |
| Report: no position on `Progress` | Body | `204`; stored position untouched, registry keeps ticking from its last report | Next positioned report |
| Reports arriving out of order | — | Not a failure: last writer wins (spec §3.6 rule 2) | — |
| Client dies silently | Reaper: check-in older than 5 min | Synthetic stop at the extrapolated position | The row already held the last report |
| Two sessions of one user playing the same item | — | Each report resolves independently against the shared row; last writer wins, same as the reference | — |
| Server restart mid-playback | — | Registry empty; the row keeps the last reported position; no reap commit for dead sessions (their loss is the extrapolation only, matching the reference's restart) | Client's next report re-establishes |
| Cascade target with thousands of leaves | — | One query, one transaction of upserts; bounded by library size like a scan | — |

## 8. Testing strategy

The pure core takes the table: every §3.7 branch, the strict boundaries at exact tick values
(AC-12, AC-13), and every transition's field effects (AC-3, AC-4, AC-17, AC-18) run against
`domain/playstate.py` with hand-built rows — no HTTP, no database, no clock. Route tests then
prove the wiring once per route rather than once per branch.

Fixtures: the 003/005 fixture library already holds a series with seasons and episodes and a
music tree; the reap tests inject `now`/`monotonic` into the registry and never sleep. AC-16
runs 003's scan-delete-rescan machinery with a favourite planted first.

| Spec AC | Test |
|---|---|
| 1 | 005's goldens already pin `UserData` presence; one assertion adds `Key`/`ItemId` equality to the item id |
| 2 | POST twice → `200`/`200`, one favourite; DELETE twice → `200`/`200`, none |
| 3 | Bare mark on a played-with-position row → position 0, count `max(1)`; twice → still 1; with `datePlayed` → 2 |
| 4 | Unmark → all four fields cleared |
| 5 | Mark the season → every episode row written, season's own row absent/default; response `UnplayedItemCount: 0` |
| 6 | Mark one episode; scan a new file in; delete one and rescan — count tracked through all three (005's rollup, re-asserted as this spec's criterion) |
| 7 | Two users, one item: every write for one, read back for both |
| 8 | Three routes → `204`, empty body |
| 9 | Progress without `MediaSourceId` and without a prior Start → position lands |
| 10 | 40% then 20% → 20% |
| 11 | Unknown id to all three → `204`, no row created |
| 12–13 | The domain table, exact ticks each side of both boundaries |
| 14 | Start, then `Failed: true` stop at 50% → count 1, position 0, played false |
| 15 | Registry with injected clock: report, advance 6 min, run one sweep → `NowPlayingItem` gone, row position = report + elapsed, capped case included |
| 16 | Favourite an item; delete its file, rescan, restore, rescan — `IsFavorite` intact throughout (003's machinery, this spec's criterion) |
| 17 | Start on a played item → count +1, played false, `LastPlayedDate` fresh |
| 18 | Stop with position → count unchanged; positionless stop → +1 |
| 19 | Progress at 95% → played, position 0 |
| 20 | Season row bare vs `Fields=RecursiveItemCount` — percentage absent/present |

Cross-cutting: the mark-response-equals-list-row test (§6.3) requests the same item both ways
and compares the serialised `UserData` byte for byte; the L0 surface test picks the five routes
from `surface.yaml` unchanged; the PascalCase sweep and the auth-mechanism matrix cover the new
routes by construction; and the acceptance map grows its 007 rows when the feature flips to
Implemented (003 T21's lesson). Every gate measurement in §6.8 is a `tools/` probe or a hand
request — the suite still opens no TCP connection.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `NowPlayingItem`'s width guessed wrong | ~~High without the gate~~ measured | High — every `/Sessions` reader | §6.8 row 1 measured it at the gate; the DTO builder reuses 005's emitters so a wrong width is a wrong *list*, not wrong values, and the named-gap set is the spec's |
| The cascade sweeps virtual/soft-removed rows the reference would skip | Low | Medium | The leaf query runs through the 005 visibility scope; a test seeds a soft-removed episode and asserts it untouched |
| Registry and row disagree during playback (row behind by one report) | Certain, by design | Low — the reference's check-in cadence has the same gap | `/Sessions` reads the registry, list rows read the row — same split as the reference; documented in §6.4 |
| The reaper commits through a different path than stops and drifts | Low | High | One function, called by both; the reap test asserts the same outcome as an explicit stop at that position |
| A flood of progress reports makes a write per second per viewer | Medium | Low–medium (SQLite WAL) | Same write rate as the reference's check-ins; measured need decides any batching, not fear (002 §6.5's argument, inverted) |
| `datePlayed` parsing diverges from the reference's binder | ~~Medium~~ measured | Low | The gate measured the error path (§6.8 row 2): validation `400` naming the parameter, which the typed query parameter produces for free |

## 10. Alternatives considered

**Stored aggregates for containers.** A `played`/`unplayed_count` column per container row,
updated on every write — faster reads, and the exact drift the spec forbids: a rescan, a
removal or a direct child mark silently invalidates it. 005 already paid for the rollup; reads
stay derived. Rejected by spec §3.5's one sentence.

**A per-second ticker for live positions, like the reference's.** Fidelity by imitation — and
an alarm per playing session doing nothing observable between reads. The extrapolate-on-read
formula produces the identical wire value with arithmetic. Rejected as mechanism-copying where
the spec pins behaviour (Principle I is about the wire, not the threads).

**An ordering guard on reports** — reject or ignore positions older than stored. The draft
spec required it; the measurement reversed it (spec §3.6 rule 2). Kept here as the record: the
"robustness" a guard buys is a viewer who cannot seek backwards, and the reference has none.

**A foreign key from `item_user_data` to `items`.** Referential hygiene — and the exact
mechanism that would delete a user's history on a slow-mounting share. 003 decided this;
`db/models.py` documents it; nothing in 007 weakens it. Re-litigated here only because a
writer touching the table for the first time is when someone "fixes" it.

**Persisting `NowPlayingItem`/`PlayState`.** Restart resilience for state whose half-life is
seconds, at a write per progress report of serialised DTO — and the reference demonstrably
does not (its restart empties `/Sessions` playback too). The resume position is the durable
part and it is already a row.

**Putting the favourite routes in `api/playstate.py`.** One module for the whole feature —
and a mapping that stops mirroring the reference's controllers, which is the property that has
made every route audit against the pinned document mechanical. The split costs an import.
