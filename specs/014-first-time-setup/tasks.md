---
feature: 014-first-time-setup
title: First-time setup — tasks
status: Accepted
created: 2026-09-14
updated: 2026-09-14
accepted: 2026-09-14
plan_status_required: Accepted
---

# 014 — Tasks

Ordered. Each task is a reviewable change on its own, and states how you know it worked.

## What the gate changed

**Five things, and every one is a sentence of the plan that the code it describes would not let
stand.** The plan was read against the modules it names before a task was written, and each finding
below is amended into [plan.md](plan.md) in the same change as this list. **A sixth was found by T2
running the whole suite**, and it is recorded here beside them because it changes what T4 and T7
must do.

### 1. The test transport never starts the scanner the plan put in the lifespan

Plan §5 gave the scanner an `async def run()` for *"the lifespan's task"*. The `app` fixture says in
its own docstring that these tests *"drive the application through a transport that does not run
one"* (`tests/conftest.py:330-340`), and `httpx.ASGITransport` has no lifespan support. So every
test of AC-8 and AC-9 would have awaited `scanner.idle()` on a worker nobody started, and hung.

**The worker starts on the first `request()`**, on the running loop, and the lifespan only stops
it. That is also the honest shape for production: a server that is never asked to scan runs no
scanning task. Plan §5 and §6.5 amended.

### 2. The setup policy cannot be a dependency *on* `require_administrator`

Plan §6.1 said step 2 was `await require_administrator(...)`. `require_administrator` declares
`Depends(require_user)` (`api/deps.py:158-160`), and FastAPI solves that sub-dependency **before**
the body of anything that depends on it — so a local caller with no token would be refused `401`
before step 1 was ever evaluated. **`require_setup_or_administrator` takes only the request, calls
`require_user(request)` itself when step 1 does not admit, and applies the administrator check
inline**, raising the same `EmptyForbiddenError`. Two lines duplicated, and the refusal is the same
object. Plan §6.1 amended.

### 3. Routes cannot land across tasks without an interim list

`test_no_route_ships_ahead_of_its_feature` asserts **equality** between what is served and
`surface_paths(IMPLEMENTED_FEATURES)` (`tests/conformance/test_routes.py:132-155`), and 014 joins
that set only when it is finished. The startup routes land in T4 and the library routes in T7, so
**`INTERIM_014`** — the routes that have landed — sits beside the set from T4 and is deleted by T10,
the pattern `INTERIM_009` followed until 009 T14. And `LEVELS_DECLARED` counts `L2` rows: it moves
from `48` to `54` in the task that adds the six rows. Neither was in plan §8.

### 4. The six surface rows come before any route, not with each

`AGENTS.md`'s *Adding an endpoint* puts the `surface.yaml` row and a passing
`tools/extract_v1_surface.py` **before** code. So T2 adds all six rows at once, with
`consumers: [atrium-admin]` — the named consumer Principle VI asks for is this feature's own client —
and `api-surface-v1.md` gains the section they belong to. No route is served by T2; the interim list
of finding 3 starts empty.

### 5. A surface row with no request case fails the suite, and so does the count

`test_every_surface_endpoint_has_at_least_one_case` asserts that every `surface.yaml` row has at
least one case in `docs/compatibility/request-cases.yaml` **and** that the surface has exactly 59
rows (`tests/unit/test_allowlist.py:709-716`). Plan §8 called the differential half owed and said
nothing about the cases, so T2 would have been red. **Six cases arrive with the six rows**, and the
file's own rule decides their shape: *"nothing here is a write to an account this project does not
own"*. Against a reference whose setup is finished, five of the six are refusals when asked as the
restricted seat — `GET` and `POST /Startup/User`, `POST /Startup/Complete`, `POST
/Library/VirtualFolders` and `POST /Library/Refresh` — so those name `restricted` alone and write
nothing; `GET /Library/VirtualFolders` is a read and names both seats. The count becomes 65.

### 6. The L2 coverage check counted rows nothing serves

`pytest_sessionfinish` fails a whole-suite run on any `surface.yaml` row no test request reached
(`tests/conftest.py`), and it read **every** row of the file. With T2's six rows in and no route
served, the suite passed every test and still exited `1`: *"6 endpoint(s) declared in surface.yaml
and asked by no test"*. No feature had added rows ahead of its routes since that check landed on
2026-09-09, so nothing had met it.

**The operator decided on 2026-09-14 to count served rows only** — `surface_paths(IMPLEMENTED_FEATURES)`
plus `INTERIM_014` — because a route of an unimplemented feature cannot have paid for L2, and the
check's own docstring is about a row *declared, served, and asked by no test*. The computation is
`test_routes.py::unasked_endpoints`, tested without a session. **So T4 and T7 must request every
path they add to `INTERIM_014`** in a test of the same change, or the suite goes red; and at T10,
when the list goes, all six are counted against the file. Plan §8 amended.

---

## T1 — The readings the plan could not take from a desk

- [x] **Changes:** `tools/probe_first_time_setup.py` gains a second walk on the same unconfigured
      instance, after the first finishes, and `notes/first-time-setup-readings.md` records it. It
      reads:
      1. **`/UserViews` as the first account**, after a refresh has gone idle, for one library of
         each of `musicvideos`, `homevideos`, `boxsets`, `books`, `mixed`, an omitted type and
         `photos` — each over a directory holding one film file — recording whether each has a
         row, its `CollectionType` key **as present, `null` or absent**, and its `ChildCount`;
      2. **the raw key set** of every `GET /Library/VirtualFolders` row, distinguishing absent from
         `null` for `CollectionType`, `PrimaryImageItemId` and `RefreshProgress`;
      3. `POST /Library/VirtualFolders` with a **relative** path, with **two paths one inside the
         other**, with **the same path twice**, and with **no `paths` at all** — status, body, and
         what the listing then holds;
      4. `POST /Startup/User` with an invalid `Name` **and** a new password, then
         `POST /Users/AuthenticateByName` with the old password and with the new — which says
         whether a refused rename leaves the password, as plan §6.4 inferred from the order.
- **Depends on:** nothing
- **Verified by:** the probe's run against the pinned image, its output in the notes; and **each
  reading that differs from the spec or the plan is amended into them in this change**, with the
  date. Plan §6.5's `CollectionFolder` decision and §6.6's path refusals are **not written before
  this task lands**. A run that cannot look (the instance does not answer) is retried on that exit
  alone, as on 2026-09-13.
- **Spec reference:** §3.5, §3.6, §3.6.1, §3.3; plan §9 rows two to four
- **Done** (2026-09-14, [PR #363](https://github.com/vdatanet/atrium-media-server/pull/363)).
  **Plan §6.6's refusals were the reference's in neither case they named**, and three readings
  were not what the documents assumed. Every library of every type is a view — over one film or
  over nothing — and `mixed` is a type of the listing and not of the view. The reference refuses
  nested paths, a path given twice, a relative path that names a directory, and no path at all
  with nothing: each is `204`, and with no `paths` the body's `PathInfos` — which OQ-13 had
  ignored — become the paths. `PrimaryImageItemId` is not "no value because no artwork" but the
  library's own id once a scan has generated it an image. And the listing gives `Movies` and
  `movies` one `ItemId`, found by reading raw keys rather than asked for. Plan §6.4's inference —
  a refused rename leaves the password — held. **Four decisions, all the operator's, the same
  day**: duplicate kept once and no path an empty library, nested and relative refused
  (behaviours §3.31), the body's `PathInfos` used (OQ-13 amended), `PrimaryImageItemId` never sent
  (behaviours §5), each library its own `ItemId` (behaviours §3.32). The fixture tree gained
  `FirstTimeSetup/`, through the 003 generator. Readings and the trail in
  [the note](notes/first-time-setup-readings.md).

## T2 — Six rows in the surface, and nothing served

- [x] **Changes:** `docs/compatibility/surface.yaml` gains `GET /Startup/User`, `POST /Startup/User`,
      `POST /Startup/Complete`, `GET /Library/VirtualFolders`, `POST /Library/VirtualFolders` and
      `POST /Library/Refresh`, `feature: "014"`, `level: L2`, `consumers: [atrium-admin]`.
      `docs/compatibility/api-surface-v1.md` gains a section for them, with the reason for each and
      a pointer to spec §2.0. `docs/compatibility/request-cases.yaml` gains one case per row, shaped
      as gate finding 5 says, and its header's counts move from 59. `tests/unit/test_allowlist.py`'s
      surface count becomes `65`. `tests/conformance/test_routes.py` gains an empty `INTERIM_014` and
      `LEVELS_DECLARED["L2"]` becomes `54`.
- **Depends on:** T1 (a reading could remove a route; none is expected to)
- **Verified by:** `python3 tools/extract_v1_surface.py` passes against the pinned document;
  `pytest tests/unit/test_allowlist.py` — green, and red with any one of the six cases removed;
  `pytest tests/conformance/test_routes.py` — green, which proves nothing is served ahead of the
  interim list; and it fails if `LEVELS_DECLARED` is left at `48`.
- **Spec reference:** §2.0, §6
- **Done** (2026-09-14, [PR #364](https://github.com/vdatanet/atrium-media-server/pull/364)). **Every test passed and the suite still failed**: the L2 coverage check
  counted all 65 rows, so six nobody serves made the run red — gate finding 6, decided by the
  operator the same day, and the check now counts served rows. Two counts the gate had not listed
  moved with the surface: `test_differential.py` asserts the endpoint count too, and
  `request-cases.yaml`'s floor section and its 764 declared query parameters (768 over 65). Three
  documents said `POST /Library/Refresh` *"is not in surface.yaml"* — `conformance.md`,
  behaviours, and the `NO_SECOND_SCAN` reason `tools/differential.py` prints — and now say it is a
  row no implemented feature serves. The five refusals joined `THE_RUNS_OWN_ACCOUNT`, so
  *restricted alone* is asserted rather than written. And `api-surface-v1.md` and `README.md` said
  58 where the file had 59. Removing any one of the six cases, leaving `LEVELS_DECLARED` at `48`,
  and serving nothing behind an interim entry each went red, tried and reverted.

## T3 — The address a request is from

- [x] **Changes:** `config/settings.py` — `NetworkSettings.trusted_proxies: list[str] =
      ["127.0.0.1"]`, with the comment an operator reads: what it is, and that a proxy on this
      machine that forwards no address cannot be told from a local client, so setup is finished
      before one is put in front. `compat/client_address.py` — `ClientAddressMiddleware` and
      `is_this_machine`. `server.py` — the middleware added outside every layer that reads the
      address, and `uvicorn.run(..., proxy_headers=False)`.
- **Depends on:** nothing
- **Verified by:** `pytest tests/unit/test_client_address.py` — `is_this_machine` over IPv4
  loopback, IPv6 loopback, IPv4-mapped IPv6 loopback, a LAN address; a loopback peer with no header
  (local); a loopback peer that is **not** trusted carrying `X-Forwarded-For: 127.0.0.1` (not
  local); a trusted peer forwarding a remote address (not local, and `request.client` is that
  address); a trusted peer forwarding loopback (local); a remote peer claiming loopback in the
  header (not local, header ignored). **And `pytest tests/unit/test_server.py` asserting that
  `uvicorn.run` is called with `proxy_headers=False`**, because resolving twice would apply the
  trust list to an address that has already been resolved. `LocalAddress` (001) is unchanged under
  the default list, asserted by 001's existing tests staying green.
- **Spec reference:** §3.1, AC-5; plan §6.1
- **Done** (2026-09-14, [PR #365](https://github.com/vdatanet/atrium-media-server/pull/365)). **Trusted is not believed, and plan §6.1 said it was.** Its condition
  admitted a loopback request carrying a forwarding header whenever the peer was a trusted proxy,
  *"so the header was consumed"* — but uvicorn's resolver reads `X-Forwarded-For` alone, so a
  declared proxy naming its client in `X-Real-IP` or `Forwarded` leaves every request at its own
  loopback address, and would have opened the window to everything behind it. The condition now
  asks for the header the resolution applied, which is spec §3.1's *"did not believe"*; plan §5
  and §6.1 amended. Two more the plan did not say: `ipaddress` calls `::ffff:127.0.0.1` loopback
  only from Python 3.13, so the mapped form is unwrapped by hand for the 3.12 floor; and
  `FORWARDED_ALLOW_IPS`, which `uvicorn.run` read, is read by nothing now. The scheme is unchanged
  under the default list, asserted through `LocalAddress` under `use_request_host` over
  `create_app`. Removing the untrusted clause, the `X-Forwarded-For` clause, the middleware in
  `create_app` and `proxy_headers=False` each went red, tried and reverted.

## T4 — The first account and the window

- [x] **Changes:** `config/state.py` — `setup_recorded`, and the carried-over rule run in
      `create_app` after `ensure_current` (plan §6.2). `db/repositories.py` —
      `UserRepository.first()` ordered by `rowid`, and `rename`. `users/first_account.py`.
      `api/deps.py` — `require_setup_or_administrator` as gate finding 2 shapes it.
      `api/startup.py` — the three routes. `server.py` — the router, before `items.router`.
      `test_routes.py` — `INTERIM_014` gains the three paths.
- **Depends on:** T2, T3
- **Verified by:**
  - `pytest tests/unit/test_config_state.py` — an old state file on a server with an account comes
    back `startup_wizard_completed: true` and `setup_recorded: true`, logged; an old file with no
    account stays `false`; a file this build wrote, with an account and the flag `false` — a
    restart mid-setup — stays `false`. Each case fails if the key check is removed.
  - `pytest tests/conformance/test_startup.py` — AC-1 (across two `create_app` on one data
    directory), AC-2, AC-3 (the three `400` bodies byte for byte, the refused rename leaving the
    name and — per T1's reading — the password), AC-4.
  - `pytest tests/unit/test_username_rule.py` — the reference's categories, a combining mark and a
    connector, leading and trailing whitespace, `/` and `:`.
  - `pytest tests/conformance/test_setup_window.py` — §3.1's seven rows over the three routes, each
    with an explicit `client=`; a helper that **requires** the address argument.
- **Spec reference:** §2.1, §3.1–§3.4; AC-1–AC-5; plan §6.1–§6.4
- **Done** (2026-09-14, [PR #366](https://github.com/vdatanet/atrium-media-server/pull/366)). **The test the task asked for could not see the order it was written
  about.** Plan §6.4 puts the rename before the password so that a refused rename keeps the
  password, and it does — but the update is one transaction here, so a refusal rolls back whatever
  was written before it, and swapping the two stays green; the test goes red only when the password
  is committed ahead of the rename, which is the reference's own shape of two saves. Two more the
  plan did not say: the reference's username rule closes on an anchor that also matches before a
  final line feed, so `joan\n` is a valid name there and here, read and not measured; and a request
  with **no body** never reaches the blank-password step — the body is required, declared as on
  the three reporting routes whose `415` behaviours §1.11 measured, so the content-type gate answers
  it. And the race §6.3 settles moved out of the route into `read_first_account`, because a route
  module imports no `sqlalchemy`. Plan §6.4 amended with all three, and §3 and §5 with what the carried-over rule needed to be
  written at all: the data directory and an account count (`carry_over_setup`,
  `UserRepository.count`), and a `Password` that may be `None`. **"Each case fails if the key check
  is removed" is true of no single removal**: running the rule on every file reds the mid-setup
  restart, in the unit test and in `test_startup.py`, and the no-account case; running it on none
  reds the with-accounts case, in both places, and the no-account case. Every case is red under one
  of the two, tried and reverted, as were dropping the locality clause
  (18 window and startup tests red), dropping the unfinished clause (10), a transliterated `\w`
  pattern (4 username cases) and setting the flag before the file is saved (the `500` case).

## T5 — A library of any declared type, and a name that is settled

- [x] **Changes:** `domain/items.py` — five members and `SCANNED_TYPES`; `domain/library.py` —
      `collection_type: CollectionType | None`. Revision `0013` and `db/models.py`.
      `library/identity.py` — a declaration with no type. `library/walker.py`,
      `library/resolver.py` and `PRODUCED_BY` keyed on `SCANNED_TYPES`, with no `else` that means
      music. `library/config.py` — `settle_name`, and `create` accepting any member or `None`
      **and no roots at all**, which `_require_roots` refuses today, while it keeps refusing two
      roots one inside the other (T1's decision A). The `CollectionFolder` for an unscannable
      library as T1 found it: created like any other's, so every library is a view.
- **Depends on:** T1
- **Verified by:**
  - `pytest tests/unit/test_migrations.py` — the generic walk, plus
    `test_0013_keeps_every_library_and_its_roots` and
    `test_0013_downgrade_refuses_a_library_it_cannot_hold`.
  - `pytest tests/unit/test_library_identity.py` — every library the fixtures declare keeps the
    identifier it had before this task, computed from a table committed in the test rather than
    from the code under test.
  - `pytest tests/unit/test_library_naming.py` — §3.6.2's four steps and the two observable
    consequences of their order; numbering from `2`; `movies` beside `Movies`.
  - `pytest tests/library/test_config.py` — `test_a_library_with_no_roots_is_refused` becomes a
    test that `create` with no roots stores a library with none; `test_a_root_inside_another_root_is_refused`
    and `test_the_same_root_twice_is_one_root` stay green unchanged.
  - `pytest tests/library/test_scan.py` — a `books` library over the music fixture tree scans to no
    item (and fails today, where the resolver's `else` makes music of it); a library with no type
    likewise.
  - `mypy` — clean, which is the proof every match on the old three was found.
- **Spec reference:** §3.6, §3.6.1, §3.6.2; AC-7
- **Done** (2026-09-14, [PR #367](https://github.com/vdatanet/atrium-media-server/pull/367)). **`create` stripped the name, and the strip undid the one
  step of §3.6.2's order a client can see**: `Movies?` settles to `Movies `, which `create` stored
  as `Movies` — and the identity key stripped it too, so `Movies ` over `Movies`'s roots derived
  `Movies`'s identifier and would have been refused as a second copy of a library the reference
  adds. The name is now stored and hashed as given; no fixture declaration pads one, and the
  committed table of thirteen known identifiers holds, through `for_library_configuration` and
  through `create`. A declaration with no type hashes an empty part where the type goes. Three
  more the task did not say: `libraries` has **three** cascading children — roots, items and
  inspections — and `test_migration_0003.py`'s rollback downgraded on a connection enforcing
  foreign keys, which 0013 would have emptied in silence, so the revision refuses a populated
  rebuild there and the harness uses `migration_connection`; the reference's trim is the
  platform's whitespace, not Python's `strip`, which also takes U+001C to U+001F (read, not
  measured); and **a library with no roots gets no `CollectionFolder`**, because `scan()`'s guard
  one refuses it, so it is in no `/UserViews` — left to T6 and T7 with the question in plan §6.5.
  An unscannable library's view is the scan's folder like any other's, its missing
  `CollectionType` is `api/items.py:view_collection_type`, asserted over `/UserViews` for all six
  cases. `test_a_library_round_trips` reads back `Movies ` as given. The books and untyped scans
  were red before the change (`create` refused both). Tried and reverted: the resolver's `else`
  restored (3 red; the scan test stays green behind the walker, and goes red with the walker
  falling back to audio as well), the walker falling back (6), `produced_by` falling back to music
  (6), the name stripped in the key (2) or in `create` (2), no type hashed as `movies` (14), no
  roots refused (1), the nesting refusal removed (1), trimming with `str.strip` (1), replacing
  before trimming (3), numbering from 1 (4), a casefolded compare (4), `mixed` kept on the view
  (1), 0013's foreign-key guard (1), its downgrade refusal (1), its check left at three (2).

## T6 — The scanner, and the lock it may hold

- [x] **Changes:** `library/scanner.py` as plan §6.5 describes it with gate finding 1's start;
      providers built from `settings.providers`; `server.py` — the scanner on `app.state` and
      stopped in the lifespan.
- **Depends on:** T5
- **Verified by:**
  - `pytest tests/library/test_scanner.py` — two requests during a pass make exactly one more pass;
    a `ScanRefusedError` on one library does not stop the next; `refresh_state` reads `Active` with
    progress during a pass started by `ADDED` and `Idle` during one started by `REFRESH`; `stop()`
    rolls the library back and a later request rescans it.
  - **The measurement plan §9 owes, before this task is merged**: a sign-in and a playback progress
    report issued while the fixture tree's music library is mid-scan, each timed. If either fails
    or waits past a second, this task commits per scan phase inside the scanner's session handling,
    leaves `scan()`'s contract alone, and amends plan §6.5 and §9 with the numbers.
    **Outcome**: both failed `database is locked` after 5.4 s with the scan paused mid-write, and
    per-phase commits changed nothing; **accepted as a residual risk by the operator on
    2026-09-14**, with the readings in plan §9 and the bound on the owes list below.
- **Spec reference:** §3.5, §3.6, §3.7; AC-8; plan §6.5, §9 row one
- **Done** (2026-09-14, [PR #368](https://github.com/vdatanet/atrium-media-server/pull/368)). **The mitigation the plan prescribed could not reach the lock it was for.**
  Paused after 9 of the music library's 18 rows, a sign-in and a progress report each failed
  `database is locked` after 5.4 s — and a `GET /System/Info/Public` sent alongside waited 5.40 s
  too, because both routes write on the event loop and the engine sets no busy timeout. Per-phase
  commits were tried and removed: the sink sees no boundary inside the writes and 004's refresh,
  which is the whole stretch holding the lock, and a commit mid-write would leave committed rows
  that the next scan finds unchanged and never refreshes. Unpaused, the fixture holds the lock for
  about 35 ms and eight overlapping requests succeeded, the slowest in 33 ms. The operator accepted
  it as a residual risk the same day (plan §9). Two more the plan did not say: **a stop raised as
  an `Exception` stops nothing**, because `scan()` calls its sink through a reporter that swallows
  one and lets the scan commit — the sink raises a `BaseException`; and a library asked for by both
  triggers before its pass is scanned once as `ADDED`. **Operator decision, 2026-09-14**: a
  library's `CollectionFolder` is created with it — `config.create_with_view`, which T7's route
  calls — so every library is a view before any scan and the scan after it finds the folder
  unchanged; the worker skips a library with no roots silently. Tried and reverted, each red: the
  stop as an `Exception`, the every-library request not merged into the pending ids, a refresh
  shown `Active`, the latest trigger winning, a rootless library scanned, an unexpected failure
  uncaught, a refusal logged with a traceback, no commit, the lifespan not stopping the worker, and
  the folder not written, or written with another name, sort name or identifier.

## T7 — Listing, adding and refreshing libraries

- [x] **Changes:** `api/library_structure.py` — the three routes, `VirtualFolderInfo` with
      `LibraryOptions` carrying `PathInfos` only, and the key presence T1 read. **`POST
      /Library/VirtualFolders` creates the library through `library.config.create_with_view`**, so
      its `CollectionFolder` exists before any scan *(operator decision, 2026-09-14; the helper
      landed in T6)*. `server.py` — the router. `test_routes.py` — `INTERIM_014` gains the three
      paths.
- **Depends on:** T4, T6
- **Verified by:**
  - `pytest tests/conformance/test_library_structure.py` — AC-6; AC-7 over every row of §3.6.1's
    table, `Movies` twice, `movies`, `Movies?`, the validation `400`; the path rules T1's decisions
    settled — a path given twice listed once, no `paths` and no body paths added and listed with
    none, the body's `PathInfos` used when `paths` is absent and ignored when it is present, a
    relative path and two nested paths each `400` `Error processing request.` and adding no
    library; **every library added with `refreshLibrary=false` — of a scanned type, an unscanned
    type, no type, and no paths — in the first account's `/UserViews` with no scan having run**,
    with the `CollectionType` key T5 settled *(operator decision, 2026-09-14)*;
    `Movies` and `movies` listed with two different `ItemId`s, each its own view's; no
    listed row carrying `PrimaryImageItemId`; `LibraryOptions` with exactly one key; every body
    property other than `PathInfos` changing nothing.
  - `pytest tests/conformance/test_setup_window.py` — the seven rows over these three routes, and
    `POST /Library/Refresh` refused `401` to a local caller with no token **during** setup.
  - `pytest tests/library/test_scanner.py::test_ac8_*` — added with `refreshLibrary=true`, then
    browsed through `/UserViews` and `/Items` as the first account; the same through
    `POST /Library/Refresh`; each `204` returned before `idle()` resolves.
- **Spec reference:** §3.5–§3.7; AC-5–AC-8
- **Done** (2026-09-14, [PR #369](https://github.com/vdatanet/atrium-media-server/pull/369)). **The whole suite failed with every test passing, on a route the new tests
  asked in nearly every case.** `GET /Library/VirtualFolders` was *"asked by no test"* because the L2
  recorder wraps `atrium.server.create_app` in `pytest_configure`, after `conftest.py` has bound the
  original name — so nothing sent to the shared `app` fixture is recorded, T4's window tests
  included, and T7's module only counts because it builds its server through the attribute. Handed
  on rather than fixed here. Two more the plan did not say. **Plan §6.6 step 1 would have sent
  two wrong sentences**: a required `Query` makes an absent name `The value 'None' is not valid.`
  and an empty one `The value '' is not valid.`, where the reference's binder answers all three
  cases as one — so `name` is optional, as the pinned document declares it, and the route raises
  the refusal keyed `name` with `The name field is required.`, read and not measured because the
  reading elided it (plan §6.6 amended). And **every row of `surface.yaml` is now served**, so
  `test_routes.py`'s check that an unserved row is not counted had no row left to use; it puts the
  interim list back without `POST /Library/Refresh` for its own length. `settle_name`'s whitespace
  test is public as `config.is_blank` and `_require_roots` as `require_roots`, `LibraryRepository`
  gained `names()`, `collectionType` is matched ignoring case, and an empty `paths=` falls back to
  the body. Four documents said Atrium serves no library-refresh route — `conformance.md`,
  behaviours, the roadmap and `NO_SECOND_SCAN` — and now say the runners were not taught to ask it.
  Tried and reverted, each red: the name tested with `str.isspace`, a relative path admitted, the
  nesting check or the existence check skipped, the body's paths dropped or preferred to the
  query's, `PrimaryImageItemId` sent, `RefreshProgress` on an idle row, the type matched exactly,
  `create` without the view, the name not settled, the refresh behind the setup window,
  `refreshLibrary` ignored, and either route awaiting `idle()` before its `204`.

## T8 — The client

- [ ] **Changes:** `src/atrium/cli/` and `pyproject.toml`'s `atrium-admin`.
      `tests/unit/test_import_directions.py` gains the rule that `atrium.cli` imports nothing from
      `atrium` outside itself, and nothing outside it imports `atrium.cli`.
- **Depends on:** T7
- **Verified by:**
  - `pytest tests/cli/test_end_to_end.py` — AC-9: the four commands against a fresh app through a
    recording transport at `127.0.0.1`, the recorded `(method, path)` set equal to §3.8's, and
    `library scan` recording exactly one request.
  - `pytest tests/cli/test_refusals.py` — AC-10: a finished server; a LAN address during setup,
    refused with no setup operation recorded; a server refusal per command, printed with its status
    and reason and exit `1`; no `--password` option exists; a sentinel password absent from stdout,
    stderr and every recorded request except the two bodies that carry it.
  - `pytest tests/unit/test_import_directions.py` — and it fails when `import atrium.db` is added
    to `atrium/cli/client.py`, tried once and reverted.
- **Spec reference:** §3.8; AC-9, AC-10; plan §6.7

## T9 — What this feature owes other documents

- [ ] **Changes:**
  - `docs/compatibility/behaviours.md` — §4.6, §4.7, §3.30, §3.31 and §3.32 lose *"not yet
    implemented"*; the three §5 rows 014 added lose it too.
  - `specs/001-server-identity-and-discovery/spec.md` — OQ-3's row points at 014 §2.1 as where it
    was answered.
  - `docs/architecture.md` — the module table gains `cli/` and `library/scanner.py`, and §5's
    deployment shape says a scan now runs inside the server process.
  - `tools/README.md` — *"The Atrium half of that is yours to arrange, and there is no command for
    it"* stops being true for libraries and the administrator: `atrium-admin` does both. The
    restricted seat stays hand-built, because creating a second account is the next slice.
  - `docs/roadmap.md` — v2's table records the first slice as landed.
- **Depends on:** T8
- **Verified by:** `pytest tests/conformance/test_acceptance.py tests/unit/test_allowlist.py` green,
  and every relative link and anchor in the touched files resolving.
- **Spec reference:** §2.1, §8

## T10 — Close it

- [ ] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_014`, mapping all **ten**
      criteria to tests by name. `IMPLEMENTED_FEATURES` gains `"014"` and `INTERIM_014` is deleted.
      The three 014 documents and `specs/README.md`'s row to `Implemented`.
- **Depends on:** T1–T9
- **Verified by:** `pytest` — the whole suite, which now includes
  `test_no_route_ships_ahead_of_its_feature` counting the six routes against the file rather than
  against a list, and the acceptance map naming tests that exist.
- **Spec reference:** §5, §6

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all **ten** —
      has a passing test, by name, in `FEATURE_014`.
- [ ] The six routes are in `docs/compatibility/surface.yaml` at `L2`, served, and counted by
      `test_routes.py` against the file.
- [ ] A fresh server, started on an empty data directory, reaches a first administrator and a first
      scanned library through `atrium-admin` alone, and an unmodified Jellyfin client signs in to it
      and browses — the sentence spec §1 opens with, run once by hand and recorded here with its
      date.
- [ ] Anything learned during implementation is back in `spec.md` and `plan.md`, in the same change —
      T1's readings first among them.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

- **L3 for the six routes** (spec §6, OQ-10): the change that teaches `tools/differential.py` to
  start an Atrium on an empty data directory — which `atrium-admin` is what makes possible without a
  write to the store — and then compares the setup sequence against the reference's. The same change
  can teach 010's two `rescan` runners to ask Atrium for the second scan: they ask the reference
  alone, because they were written when Atrium served no `POST /Library/Refresh`, and it has served
  one since T7.
- **The restricted seat** the differential needs is still built by hand, because a second account is
  `POST /Users/New` and the next slice (spec §2).
- **Bounding the scan's write lock** (plan §9 row one, accepted as a residual risk on 2026-09-14):
  `scan()`'s contract changed so a scanner can commit per inspected file and run 004's refresh in
  short transactions (003, 004), and the request side given an explicit busy timeout with route
  database work moved off the event loop (002, 007). The starting point is T6's readings: paused
  mid-write, a sign-in and a progress report fail `database is locked` after 5.4 s and an unrelated
  read waits as long; unpaused, the fixture holds the lock about 35 ms.
- **What started the scan of a library added with `refreshLibrary=false`** on the reference was not
  isolated (spec §3.6), and this server starts none.
