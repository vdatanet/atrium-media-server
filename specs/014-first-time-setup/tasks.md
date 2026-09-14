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
- **Done** (2026-09-14). **Every test passed and the suite still failed**: the L2 coverage check
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

- [ ] **Changes:** `config/settings.py` — `NetworkSettings.trusted_proxies: list[str] =
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

## T4 — The first account and the window

- [ ] **Changes:** `config/state.py` — `setup_recorded`, and the carried-over rule run in
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

## T5 — A library of any declared type, and a name that is settled

- [ ] **Changes:** `domain/items.py` — five members and `SCANNED_TYPES`; `domain/library.py` —
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

## T6 — The scanner, and the lock it may hold

- [ ] **Changes:** `library/scanner.py` as plan §6.5 describes it with gate finding 1's start;
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
- **Spec reference:** §3.5, §3.6, §3.7; AC-8; plan §6.5, §9 row one

## T7 — Listing, adding and refreshing libraries

- [ ] **Changes:** `api/library_structure.py` — the three routes, `VirtualFolderInfo` with
      `LibraryOptions` carrying `PathInfos` only, and the key presence T1 read. `server.py` — the
      router. `test_routes.py` — `INTERIM_014` gains the three paths.
- **Depends on:** T4, T6
- **Verified by:**
  - `pytest tests/conformance/test_library_structure.py` — AC-6; AC-7 over every row of §3.6.1's
    table, `Movies` twice, `movies`, `Movies?`, the validation `400`; the path rules T1's decisions
    settled — a path given twice listed once, no `paths` and no body paths added and listed with
    none, the body's `PathInfos` used when `paths` is absent and ignored when it is present, a
    relative path and two nested paths each `400` `Error processing request.` and adding no
    library; `Movies` and `movies` listed with two different `ItemId`s, each its own view's; no
    listed row carrying `PrimaryImageItemId`; `LibraryOptions` with exactly one key; every body
    property other than `PathInfos` changing nothing.
  - `pytest tests/conformance/test_setup_window.py` — the seven rows over these three routes, and
    `POST /Library/Refresh` refused `401` to a local caller with no token **during** setup.
  - `pytest tests/library/test_scanner.py::test_ac8_*` — added with `refreshLibrary=true`, then
    browsed through `/UserViews` and `/Items` as the first account; the same through
    `POST /Library/Refresh`; each `204` returned before `idle()` resolves.
- **Spec reference:** §3.5–§3.7; AC-5–AC-8

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
  write to the store — and then compares the setup sequence against the reference's.
- **The restricted seat** the differential needs is still built by hand, because a second account is
  `POST /Users/New` and the next slice (spec §2).
- **What started the scan of a library added with `refreshLibrary=false`** on the reference was not
  isolated (spec §3.6), and this server starts none.
