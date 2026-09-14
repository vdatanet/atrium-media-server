---
feature: 014-first-time-setup
title: First-time setup — implementation plan
status: Accepted
created: 2026-09-14
updated: 2026-09-14
accepted: 2026-09-14
spec_status_required: Accepted
---

# 014 — Implementation plan

> **This document describes HOW.** It may not restate WHAT: the spec is the authority on behaviour,
> and a plan that repeats it will disagree with it eventually.

**Written at the plan gate, and four of its decisions were the operator's, taken on 2026-09-14.**
The spec left four questions to this document. Three of them — OQ-9, OQ-11 and OQ-13 — were put to
the operator with a recommendation and answered as recommended, and a fifth question nobody had
asked turned up while reading the code and was put the same way: **a server that already holds
accounts from before this feature would open its setup window on upgrade**, and the first account's
password could then be reset by any process on the machine (§6.2). OQ-10 is proposed here and is
decided by accepting this plan. Every answer that changes what a client can observe went back into
the spec in the same change — §3.1, §3.5, §3.6, §3.8 and §6, AC-1, AC-5, AC-7 and AC-10 — and the spec's §7 rows
for the four questions are closed with a pointer here.

## 1. Approach

**Almost nothing this feature needs exists yet, and almost everything it touches does.** The server
has an account store and a hash (002), a library store with a derived identity and a scan (003), a
persisted `StartupWizardCompleted` that nothing sets (001), and an empty-bodied `401` and `403`
(002). What it does not have is **any caller for three of those from inside the server**:
`library.config.create` and `library.scan.scan` are called only by tests and by the throwaway script
`tools/README.md` describes, and no route creates a user. So the feature is five things:

1. **A policy** — *setup unfinished and the caller is this machine, or an administrator* — as one
   dependency beside `require_administrator`, and the client address it rests on made a property of
   the application rather than of how the process was launched (§6.1).
2. **Six routes** in two new routers, each a thin translation onto code that exists or is added
   beside it (§5).
3. **A scanner that runs inside the server.** This is the one piece of new machinery, and the one
   with a real risk (§6.5, §9).
4. **A widened library type**: a library may now be created with any of the eight declared types or
   none, and only three of them are scanned (§4).
5. **A command-line client** that imports nothing of the server's and is tested by recording every
   request it makes (§6.7).

**The two decisions that were not obvious:**

1. **The scan runs in the server process, on one worker, and the routes that start it do not
   wait.** The spec's measurement is that neither `204` waits (§3.6, §3.7), and a scan here is
   synchronous code that writes one library inside one transaction. So a route hands the request to
   a single asyncio task that runs `scan()` in a thread, one library at a time, and answers at once.
   A second request while one runs is **coalesced** into one more pass rather than queued per
   request or refused (§6.5).
2. **The client address is resolved inside the application, from a trusted-proxy list in
   `config.toml`, and the setup window refuses a loopback request that carries a forwarding header
   the server did not believe.** Today the address comes from uvicorn's own default, applied by
   `uvicorn.run` and therefore invisible to every test in this repository, which builds the
   application without uvicorn. A security rule cannot rest on a default nobody chose and no test
   can see (OQ-11, §6.1).

## 2. Inherited decisions

| Decision | Source |
|---|---|
| A route declares its authorisation as a FastAPI dependency; there is no policy registry | `api/deps.py:111-183` (`require_user`, `require_administrator`) |
| The empty `401` and `403` are `UnauthenticatedError` and `EmptyForbiddenError`; the 25-byte `403` is `ForbiddenError`, which a disabled account still receives | `compat/errors.py:86, 373, 1192, 1268` |
| `Error processing request.` as `text/plain` is `controller_error`; problem details and the validation map are the existing handlers | `compat/errors.py:1196`; behaviours §1.11 |
| A null property is absent | behaviours §1.7 |
| `StartupWizardCompleted` lives in `state.json`, written atomically by `config.state.save` | `config/state.py:55, 88` |
| Passwords are Argon2id through `app.state.passwords`, and hashing runs off the event loop | ADR-0006; `users/passwords.py:131` |
| A user's name is unique by `name_normalised`, strip plus casefold | `db/models.py:65-116`; `db/repositories.py:84` |
| Signing in again from the same device revokes that device's previous token | `users/sessions.py:218` |
| A library's identity is derived from its declaration — type, name, roots, case flag — and a second identical declaration is refused | `library/config.py:67-104`; 003 §3.6 |
| A scan is synchronous, writes inside its caller's transaction and never commits; its guards raise `ScanRefusedError` before writing | `library/scan.py:122, 171` |
| The database is WAL; the engine is synchronous and database work runs in a thread pool | ADR-0003; `db/engine.py:1-25` |
| A schema behind this build is refused at startup, naming the upgrade command | `db/schema.py:8-25` |
| A route exists only if `surface.yaml` lists it, and `IMPLEMENTED_FEATURES` gains a feature in the change that implements it | `tests/conformance/test_routes.py:52` |
| A runtime dependency is added only when code needs it, with its reason, alternatives and licence | `pyproject.toml:21-22` |
| Configuration is a file, not an environment | `docs/architecture.md` §4 |

## 3. Modules

```
src/atrium/
├── api/
│   ├── deps.py                  changed   require_setup_or_administrator
│   ├── startup.py               new       GET/POST /Startup/User, POST /Startup/Complete
│   └── library_structure.py     new       GET/POST /Library/VirtualFolders, POST /Library/Refresh
├── cli/
│   ├── __init__.py              new
│   ├── __main__.py              new       python -m atrium.cli
│   ├── client.py                new       the HTTP half: one method per operation §3.8 names
│   └── commands.py              new       argument parsing, the four commands, output, exit codes
├── compat/
│   └── client_address.py        new       the trusted-proxy resolution and "is this machine"
├── config/
│   ├── settings.py              changed   network.trusted_proxies
│   └── state.py                 changed   the carried-over-setup rule on load
├── db/
│   ├── models.py                changed   libraries.collection_type nullable, check widened
│   ├── repositories.py          changed   UserRepository.first, rename; LibraryRepository.names
│   └── migrations/versions/
│       └── 0013_a_library_of_any_declared_type.py   new
├── domain/
│   ├── items.py                 changed   CollectionType gains five members; SCANNED_TYPES
│   └── library.py               changed   collection_type: CollectionType | None
├── library/
│   ├── config.py                changed   settle_name; any declared type, or none
│   ├── identity.py              changed   a declaration with no type
│   └── scanner.py               new       the in-process worker, its state, coalescing
├── users/
│   └── first_account.py         new       create-if-none, the username rule, update
└── server.py                    changed   routers, middleware, the scanner in the lifespan,
                                           proxy_headers=False
pyproject.toml                     changed   [project.scripts] atrium-admin
```

| Module | Change | Responsibility |
|---|---|---|
| `api/deps.py` | changed | `require_setup_or_administrator`: during setup a local caller is admitted before any token is read; otherwise it defers to `require_administrator` unchanged, so the fall-through refusals are the existing ones (§6.1) |
| `api/startup.py` | new | Three routes; the `404`, the bare-string `400` and the rename `400` are raised here and nowhere else |
| `api/library_structure.py` | new | Three routes and the `VirtualFolderInfo` model; `POST /Library/Refresh` depends on `require_administrator`, not on the setup policy |
| `cli/` | new | The client. **Imports nothing from `atrium` outside `atrium.cli`**, asserted by `tests/unit/test_import_directions.py` |
| `compat/client_address.py` | new | An ASGI middleware that keeps the peer as it arrived beside the address uvicorn's `ProxyHeadersMiddleware` resolves, and `is_this_machine(request)` |
| `config/settings.py` | changed | `NetworkSettings.trusted_proxies: list[str]`, default `["127.0.0.1"]` — uvicorn's own default, so an existing install resolves addresses exactly as it did |
| `config/state.py` | changed | `setup_carried_over(state, has_accounts)` and the key that marks a state file as written by this feature or later (§6.2) |
| `db/models.py`, migration `0013` | changed / new | §4 |
| `db/repositories.py` | changed | `UserRepository.first()` in insertion order; `rename(user_id, name)` refusing a name `name_normalised` already holds; `LibraryRepository.names()` |
| `domain/items.py`, `domain/library.py` | changed | §4 |
| `library/config.py` | changed | `settle_name(requested, taken)` in §3.6.2's order; `create` accepts any `CollectionType` or `None`, and **no roots** — `_require_roots` keeps refusing nested ones (§6.6, amended 2026-09-14) |
| `library/identity.py` | changed | `for_library_configuration` with `None` — **every existing library's identifier unchanged**, asserted (§8) |
| `library/scanner.py` | new | §6.5 |
| `users/first_account.py` | new | §6.3 and §6.4 |
| `server.py` | changed | Two routers before `items.router`; `ClientAddressMiddleware` wrapping uvicorn's `ProxyHeadersMiddleware`, outside every layer that reads the address; the scanner started and stopped in the lifespan; `uvicorn.run(..., proxy_headers=False)` so the resolution is not applied twice. `pyproject.toml` gains `[project.scripts] atrium-admin = "atrium.cli.commands:main"` |

**No new runtime dependency.** The client uses `httpx`, which the server already depends on, and
`argparse` and `getpass` from the standard library. `ProxyHeadersMiddleware` is imported from
`uvicorn`, which is already a runtime dependency; its constructor takes `trusted_hosts` and it reads
`X-Forwarded-For` and `X-Forwarded-Proto` (verified against the locked 0.52.4 on 2026-09-14).

## 4. Data model

**One revision, `0013`, on `libraries` only.**

| Column | Before | After |
|---|---|---|
| `collection_type` | `NOT NULL`, `CHECK (collection_type IN ('movies', 'tvshows', 'music'))` | nullable, `CHECK (collection_type IS NULL OR collection_type IN ('movies', 'tvshows', 'music', 'musicvideos', 'homevideos', 'boxsets', 'books', 'mixed'))` |

SQLite cannot alter a check constraint, so the revision rebuilds the table with Alembic's batch
mode. `library_roots` references it with `ON DELETE CASCADE` and foreign keys are on, so the rebuild
runs with them suspended for its duration and verified with `PRAGMA foreign_key_check` before
commit. **Downgrade refuses** if any row holds a type outside the three or none, naming the rows,
rather than deleting a library an operator created.

**Nothing about users changes in the schema.** The first account is an ordinary row: administrator,
hidden, content deletion enabled, and `EnableRemoteControlOfOtherUsers` in `policy_extra`
`[source: Jellyfin.Server.Implementations/Users/UserManager.cs:720-722 @ v10.11.11]`. "First" is
insertion order — the reference's own query has no ordering `[source: UserManager.cs:147-152]`, and
on a server with one account the two agree.

**The domain.** `CollectionType` gains `MUSICVIDEOS`, `HOMEVIDEOS`, `BOXSETS`, `BOOKS` and `MIXED`,
and `SCANNED_TYPES = frozenset({MOVIES, TVSHOWS, MUSIC})` is what every scan-side mapping is keyed on
— `walker.EXTENSIONS`, `resolver`'s dispatch and `PRODUCED_BY` — so `mypy` finds every place that
assumed three. `Library.collection_type` becomes `CollectionType | None`. `photos` is not a member:
§3.6.1 stores it as no type, and the route maps any value outside the eight to `None` before the
domain sees it.

**The server's state file.** `ServerState` gains `setup_recorded: bool`, written `true` by every
state file this build creates. Its absence is how a file written before this feature is recognised
(§6.2).

## 5. Contracts

```python
# compat/client_address.py
class ClientAddressMiddleware:            # wraps ProxyHeadersMiddleware; stores scope["state"]["peer"]
    def __init__(self, app: ASGIApp, trusted_proxies: Sequence[str]) -> None: ...
class Peer(NamedTuple): host: str | None; trusted: bool   # trusted by the resolver's own matching
FORWARDING_HEADERS: Final = ("x-forwarded-for", "forwarded", "x-real-ip")
def is_loopback(host: str | None) -> bool: ...
def is_this_machine(request: Request) -> bool: ...
    # loopback (IPv4, IPv6, and IPv4-mapped IPv6) AND no forwarding header the resolution did not
    # consume - a header present while the peer was not a trusted proxy means "not believed", and
    # so does `forwarded` or `x-real-ip` without `x-forwarded-for`, which it never reads
    # (amended at T3, 2026-09-14); no recorded peer means not this machine

# api/deps.py
async def require_setup_or_administrator(request: Request) -> User | None: ...
    # None only for the admitted-during-setup branch; routes must not assume a caller

# users/first_account.py
FIRST_ACCOUNT_NAME: Final = "MyJellyfinUser"
def ensure_first_account(repository: UserRepository) -> User: ...
def is_valid_username(name: str) -> bool: ...
class StartupUserUpdate(NamedTuple): name: str | None; password: str
class NoAccountError(LookupError): ...          # -> 404 problem details
class EmptyPasswordError(ValueError): ...       # -> 400 "Password must not be empty"
class InvalidUsernameError(ValueError): ...     # -> 400 Error processing request.
class UsernameTakenError(ValueError): ...       # -> 400 Error processing request.
def update_first_account(sessions, passwords: Passwords, update: StartupUserUpdate) -> None: ...

# library/config.py
REPLACED_IN_NAMES: Final[frozenset[str]]        # §3.6.2 step 3
def settle_name(requested: str, taken: Collection[str]) -> str: ...

# library/scanner.py
class ScanTrigger(Enum): ADDED = "added"; REFRESH = "refresh"
@dataclass(frozen=True)
class LibraryRefresh: status: Literal["Idle", "Active"]; progress: float | None
class Scanner:
    def __init__(self, sessions: sessionmaker, settings: Settings, paths: DataPaths) -> None: ...
    def request(self, library_ids: Collection[str] | None, trigger: ScanTrigger) -> None: ...
    def refresh_state(self, library_id: str) -> LibraryRefresh: ...
    async def stop(self) -> None: ...           # the lifespan stops it; nothing starts it there
    async def idle(self) -> None: ...           # for tests; the client never sees it

# api/library_structure.py
class VirtualFolderInfo(PascalModel):
    name: str; locations: list[str]; collection_type: str | None; item_id: str
    library_options: LibraryOptionsOut; refresh_status: str | None; refresh_progress: float | None
class LibraryOptionsOut(PascalModel):
    path_infos: list[PathInfo]                  # OQ-13: what this server honours, and only that

# cli/client.py
class AdminClient:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None: ...
    async def public_info(self) -> PublicInfo: ...
    async def sign_in(self, username: str, password: str) -> None: ...
    async def first_user(self) -> str: ...
    async def update_first_user(self, name: str, password: str) -> None: ...
    async def complete(self) -> None: ...
    async def add_library(self, name: str, kind: str | None, paths: Sequence[str]) -> None: ...
    async def libraries(self) -> list[LibraryRow]: ...
    async def refresh(self) -> None: ...
class Refused(Exception): status: int; reason: str

# cli/commands.py
async def run(argv: Sequence[str], *, stdin: TextIO, stdout: TextIO, stderr: TextIO,
              transport: httpx.AsyncBaseTransport | None = None) -> int: ...
def main() -> None: ...
```

## 6. Algorithms

### 6.1 The window, and the address it rests on

`require_setup_or_administrator`, in order — the spec's three branches with the first narrowed:

| Step | Test | Outcome |
|---|---|---|
| 1 | `not state.startup_wizard_completed and is_this_machine(request)` | admit, **before any token is read** — the reference admits a caller with a bad token too |
| 2 | otherwise | `await require_user(request)`, then the administrator check inline raising `EmptyForbiddenError` — the existing `401`, empty `403`, and the 25-byte `403` for a disabled account. **Not a `Depends` on `require_administrator`**: its own `Depends(require_user)` is solved before this dependency's body, and would refuse a local caller with no token before step 1 ran *(amended at the task gate, 2026-09-14)* |

**Resolution, in the order the layers see a request.** `ClientAddressMiddleware` records the peer
exactly as uvicorn handed it over, then delegates to `ProxyHeadersMiddleware(trusted_hosts=
settings.network.trusted_proxies)`, which replaces `scope["client"]` with the forwarded address only
when the peer is trusted. `is_this_machine` then admits only if the resolved address is loopback
**and** one of two holds: no forwarding header is present, or the recorded peer was a trusted proxy
**and one of the headers is `X-Forwarded-For`** (so the header was consumed and the loopback address
is the originating client's). A loopback peer that is *not* trusted and carries a forwarding header
is a proxy the operator did not declare, and is refused as from elsewhere.

*(Amended at T3, 2026-09-14.)* This paragraph first said *"or the recorded peer was a trusted proxy"*
alone, and gave as its reason that the header was then consumed. **That reason is true of one header
in three**: `ProxyHeadersMiddleware` reads `X-Forwarded-For` for the address and never `Forwarded` or
`X-Real-IP` `[verified against the locked uvicorn 0.52.4, 2026-09-14]`. A declared proxy on this
machine that names its client in `X-Real-IP` alone — a common way to configure one — leaves every
request at its own loopback address, and the first wording would have admitted all of them to the
window. That is spec §3.1's *"a forwarded address the server did not believe"*, so the condition now
asks for the header the resolution applied. Whether the peer was trusted is decided by the
resolver's own trust object, recorded before it runs, so the two cannot disagree about a network or
`"*"`.

**What this cannot see**, and the operator documentation says so beside `trusted_proxies`: a proxy
on the same machine that forwards nothing. Its requests are indistinguishable from a local client's,
so setup has to be finished before such a proxy is put in front. `LocalAddress` (001) and the
authentication remote address (002) read `request.client` today and keep reading it: this change
makes the address they already get explicit, and with the default list it is the same address.
**And the same scheme**: `X-Forwarded-Proto` is believed from `127.0.0.1` alone before and after,
which is the one input `LocalAddress` reads under `use_request_host` — asserted at T3 over
`create_app`. The one thing an install loses is uvicorn's `FORWARDED_ALLOW_IPS` environment
variable, which `uvicorn.run` read when it resolved the address and nothing reads now; this server
never documented it, its configuration is a file (§2), and `trusted_proxies` is its replacement
*(T3, 2026-09-14)*.

### 6.2 A state file written before this feature

On load, after the database is known current:

```
if "setup_recorded" not in the file's keys:
    if the users table holds any row and not startup_wizard_completed:
        startup_wizard_completed = True        # logged at WARNING, naming the account count
    setup_recorded = True
    save
```

**Once, and only on a file this build did not write.** A fresh server writes `setup_recorded: true`
on its first start, so a restart in the middle of setup — an account created by `GET /Startup/User`
and the window still open — is never mistaken for an old install. An old install with no account is
left unfinished, which is correct: nobody can sign in to it anyway. `extra="allow"` already keeps
the key through a downgrade and back.

### 6.3 `GET /Startup/User`

In one transaction: `first()`; if none, `add` the §4 account with no password hash. The race of two
concurrent first reads is settled by `name_normalised`'s unique index — the loser's insert fails,
its transaction is retried once as a read, and both answer the same name.

### 6.4 `POST /Startup/User`

In the reference's order `[source: Jellyfin.Api/Controllers/StartupController.cs:131-160 @
v10.11.11]`, which is what makes a refused rename leave the password too:

1. no first account → `NoAccountError`;
2. `Password` null, empty or whitespace → `EmptyPasswordError`;
3. `Name` not null and not equal to the current name ignoring case → `is_valid_username`, then
   `rename` — either refusal raises before anything is written;
4. hash the password off the event loop, `set_password_hash`, commit.

`is_valid_username` is the reference's rule restated: non-empty after the whitespace check, no
leading or trailing whitespace, and every character a word character, space, `-`, `'`, `.`, `_`,
`@` or `+` `[source: UserManager.cs:116-120, 899-907]`. **Python's `\w` and .NET's differ at the
edges** — .NET admits the connector-punctuation and non-spacing-mark categories whole — so the rule
is written as an explicit Unicode-category test, not a transliterated pattern, and tested on a
combining mark and a connector.

### 6.5 The scanner

**One worker, one library at a time, one transaction per library.**

- `request(ids, trigger)` adds the ids (every library for `None`) to a pending set and wakes the
  worker — **starting it on the running loop if this is the first request**. It never blocks and
  never raises, which is what lets both routes answer at once. *(Amended at the task gate,
  2026-09-14: the worker was the lifespan's task, and the transport every test here uses runs no
  lifespan, so AC-8's tests would have waited on a worker nobody started. A server that is never
  asked to scan now runs no scanning task.)*
- The worker takes the whole pending set, and for each library opens a session, runs `scan()` in
  `asyncio.to_thread` with the providers built from `settings.providers` and a `ProgressSink` that
  records progress, and commits. A `ScanRefusedError` is logged at WARNING with the library's name
  and the pass continues; any other exception is logged with its traceback and the pass continues.
- **A request during a pass is coalesced**: its ids join the pending set and the worker runs one
  more pass after the current one. Nothing is cancelled, so the reference's `Cancelling` (§3.7) is
  not reproduced, and the spec records it without requiring it.
- `refresh_state(id)` answers `Active` with the recorded progress **only while a pass started by
  `ScanTrigger.ADDED` is scanning that library**, and `Idle` with no progress otherwise — the
  reference's own asymmetry (§3.5), which a client can wait on and Atrium's own client does not.
- `stop()` sets a flag the progress sink checks; the sink raises, the library's transaction rolls
  back, and the next start rescans it.
- A library whose type is not in `SCANNED_TYPES`, or is `None`, is handed to `scan()` like any
  other, and the walker admits no candidate for it. **Its `CollectionFolder` row is created like
  any other's, so it appears in `/UserViews`** — on the reference every library of every type is a
  view, over one film or over nothing `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-14]` — and the view's `CollectionType` is the stored
  type except for `MIXED` and `None`, which emit no key: `mixed` is a type of the library listing
  and not of a view. *(Amended by T1, 2026-09-14: this bullet left the row to that reading.)*

`refreshLibrary=false` starts nothing. The reference scanned such a library anyway and the spec
records that the trigger was not isolated (§3.6); starting an unrequested scan here would be
inventing a trigger nobody measured.

### 6.6 `POST /Library/VirtualFolders`

1. Validation `400` keyed `name` for a missing, empty or whitespace name — FastAPI's own required
   `Query` with a whitespace validator, so the existing handler produces §1.11's map.
2. `collectionType`: one of the eight → that member; absent or anything else → `None`.
3. **The paths.** `paths` split on `,`; when the query carries no `paths`, each
   `LibraryOptions.PathInfos[].Path` of the body instead. Then, in this order, each refusal
   `controller_error` and adding nothing: a path that is not absolute (`normalise_root`'s own
   check); a path that is not an existing directory; and two that are one inside the other
   (`_require_roots`' check). A path given more than once is stored once, which `create` already
   does for two spellings of one directory (`test_the_same_root_twice_is_one_root`). None at all is not a refusal: the library is created with no
   roots. *(Amended 2026-09-14.)* This step said relative and nested paths were refused *"on 003's
   grounds, neither measured"*; **T1 measured them and the reference refuses neither** — a relative
   path that names a directory from `/`, two nested paths, the same path twice and no `paths` at
   all each answer `204` and are listed as given, and with no `paths` the body's `PathInfos` become
   the library's paths `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-14]`. **The operator decided the same day**: the duplicate kept once, no
   path an empty library, the body's paths used, and the nested and relative refusals kept as a
   divergence ([behaviours §3.31](../../docs/compatibility/behaviours.md)). `create` therefore
   accepts an empty tuple of roots, which 003's `_require_roots` refuses today, and keeps refusing
   nested ones (T5).
4. `settle_name(name, LibraryRepository.names())` — trim, replace, number from `2`, exact compare.
5. `library.config.create` in one transaction, then `scanner.request({id}, ADDED)` if
   `refreshLibrary`.
6. `204`. The body is parsed, and nothing in it is applied **except the `PathInfos` step 3 reads
   when the query has no `paths`** — OQ-13 as amended on 2026-09-14, on the reference's own
   behaviour. A listed library carries no `PrimaryImageItemId` (an accepted gap, behaviours §5), and
   its `ItemId` is its own even beside a library whose name differs only in case, where the
   reference's listing gives both one ([behaviours §3.32](../../docs/compatibility/behaviours.md)) —
   which `for_library`'s derivation from the library's own identifier already guarantees.

### 6.7 The client

- **Password (OQ-9).** On a terminal, `getpass`; otherwise `--password-stdin` reads one line and
  anything else is refused before a request is sent. There is no `--password` option at all.
- **No token is kept.** Each command that needs one signs in with a fixed `DeviceId` of
  `atrium-admin-<host name>` — so repeated invocations replace their own token (`sessions.py:218`)
  rather than accumulating sessions.
- **Order.** Every command first reads `GET /System/Info/Public`. `setup` then refuses a finished
  server, refuses a non-loopback address while unfinished (the address is parsed and resolved
  locally, a courtesy the server's rule decides), and runs `GET` then `POST /Startup/User`, then
  `POST /Startup/Complete`. `library add` sends `refreshLibrary=true`, because during setup it is
  the only way to start a scan: `POST /Library/Refresh` needs an administrator.
- **Output.** A refusal prints `<status> <reason>` to stderr — the body's `title`, a bare string, or
  the plain text — and exits `1`; a local refusal exits `2`; success exits `0`. No output path
  receives the password, asserted by feeding a sentinel password and scanning every stream.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| `state.json` cannot be written by `POST /Startup/Complete` | `ConfigurationError` from `save` | `500`, logged; the in-memory flag is set only after the write succeeds | retry the call; it is idempotent |
| Two first reads at once | unique `name_normalised` | the loser re-reads | none needed |
| Rename collides | `rename` sees the name held | `400` before the password is touched | caller retries with another name |
| A root vanishes or empties between add and scan | `ScanRefusedError` | logged; library stays listed and empty | fix the disk, `library scan` |
| A scan raises unexpectedly | the worker's handler | logged with traceback; pass continues | `library scan` |
| Server stops mid-scan | `stop()` → sink raises | the library's transaction rolls back | the next scan request rescans it |
| A write from a request waits behind a scan's transaction | SQLite busy timeout | see §9's first row | measured by the scanner's task |
| Downgrade below `0013` with an unscannable library | the revision's own check | refuses, naming the rows | remove the libraries, or stay |
| The client is pointed at a server that is not Atrium or Jellyfin | `GET /System/Info/Public` fails or lacks `ProductName` | exit `1`, printing what answered | — |

## 8. Testing strategy

**Two things the suite counts move with the surface, and neither was here until the task gate**
(2026-09-14): `test_routes.py` asserts that what is served **equals** the implemented features'
rows, so routes that land before the feature closes are held in an `INTERIM_014` list, and
`LEVELS_DECLARED` gains six `L2`; and `test_allowlist.py` requires a request case for every surface
row and counts the rows, so six cases — five of them refusals asked as the restricted seat, which
write nothing — arrive with the six rows. **A third was found by T2 on 2026-09-14**: the suite's L2
coverage check failed a run on any row no test request reached, over the whole file, so six rows
with no route made the suite red with every test passing. The operator decided the same day that
it counts **served** rows only — the implemented features' plus `INTERIM_014` — so a route is owed
a request from the change that adds it to the interim list, and from T10 every row is counted
against the file ([tasks, gate finding 6](tasks.md#6-the-l2-coverage-check-counted-rows-nothing-serves)).

**Every new route is tested through the ASGI transport with an explicit `client=` address**, because
`httpx.ASGITransport` defaults to `127.0.0.1` and the shared fixture uses `192.168.1.50`: a test that
forgets the address is testing the other branch. The helper takes the address as a required
argument.

| Criterion | Where it becomes a test |
|---|---|
| AC-1 | `tests/conformance/test_startup.py` — a fresh `create_app`, `POST /Startup/Complete`, a second `create_app` on the same data directory reading `true`; plus `tests/unit/test_config_state.py` for §6.2's three cases: an old file with accounts, an old file without, a new file mid-setup |
| AC-2 | `test_startup.py` — two reads, one row, `is_hidden`, `/Users/Public` `[]`, name `MyJellyfinUser` with `getpass.getuser` patched to a valid name |
| AC-3 | `test_startup.py` — the `404` before the read; the three `400` bodies byte for byte; a refused rename leaving name **and** password; sign-in after success; `tests/unit/test_username_rule.py` for §6.4's edges |
| AC-4 | `test_startup.py` — complete with no password and no library; a second complete as administrator |
| AC-5 | `tests/conformance/test_setup_window.py` — §3.1's seven rows as a parametrised table over the five setup routes; the LAN-address-from-this-machine case; a loopback peer with an untrusted `X-Forwarded-For`; a trusted proxy forwarding a remote address; a trusted proxy forwarding loopback |
| AC-6 | `tests/conformance/test_library_structure.py` — `POST /Library/Refresh` `401`/`403` in both states, admitted as administrator |
| AC-7 | `test_library_structure.py` — every row of §3.6.1's table stored and listed; `Movies` twice, `movies`, `Movies?`; the validation `400`; the missing-path, relative-path and nested-paths `400`s; no library added by any of them; a path given twice listed once; no `paths` and no body paths listed with none; the body's `PathInfos` used when `paths` is absent and ignored when it is present; `Movies` and `movies` listed with two `ItemId`s; no row carrying `PrimaryImageItemId`; `LibraryOptions` carrying `PathInfos` and nothing else; `tests/unit/test_library_naming.py` for `settle_name`; `tests/unit/test_library_identity.py` asserting every existing fixture library's identifier is unchanged |
| AC-8 | `tests/library/test_scanner.py` — add with `refreshLibrary=true` over the generated fixture tree, `await scanner.idle()`, then `/UserViews` and `/Items` as the first account; the same through `POST /Library/Refresh`; the `204` measured to return before `idle()` resolves |
| AC-9 | `tests/cli/test_end_to_end.py` — the four commands against a fresh app through a recording transport at `127.0.0.1`; the recorded `(method, path)` set equal to §3.8's list; `library scan` recording exactly one request |
| AC-10 | `tests/cli/test_refusals.py` — a finished server, a LAN address, a refusal per command, the sentinel-password sweep; `tests/unit/test_import_directions.py` gaining `atrium.cli` |

**Migration `0013`** joins `tests/unit/test_migrations.py`'s generic walk and gains
`test_0013_keeps_every_library_and_its_roots` and
`test_0013_downgrade_refuses_a_library_it_cannot_hold`.

**OQ-10: L2, and L3 is owed rather than taken.** A differential over the setup sequence needs an
Atrium started on an empty data directory for every run, which the harness does not do — it points
at a running Atrium someone arranged. **This feature is what makes arranging it possible without a
database write**, so the L3 row is written into the task list's *"what this feature owes"* and
belongs to the change that teaches `tools/differential.py` to stand its own Atrium up.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **A scan's single transaction holds SQLite's write lock for minutes**, and a sign-in (which writes `last_login_date`) or a playstate flush waits past the busy timeout and fails | High on a real library | High: the server looks broken during every scan | The scanner's task measures a sign-in and a progress report during a scan of the fixture tree. If either fails, the mitigation is a commit per scan phase inside `scanner.py`'s session handling — **not** a change to `scan()`'s contract, which its tests depend on — and the plan is amended with the measurement |
| A library of an unscannable type is in `/UserViews` on the reference and not here, or the reverse | Medium | Low: a view row more or fewer | The task list's first task is a reading on the single-use instance: `/UserViews` for such libraries and for one with no type, before any code decides the `CollectionFolder`. **Read on 2026-09-14: every library is a view** (§6.5) |
| `CollectionType` in `VirtualFolderInfo` is JSON `null` on the reference where §1.7 predicts absence | Low | Low | The same reading takes the raw key set rather than `dict.get`. **Read on 2026-09-14: absent, as §1.7 predicts, and `PrimaryImageItemId` and `RefreshProgress` likewise** |
| Relative, nested or duplicate paths are answered differently by the reference | Medium | Low: an edge no client sends | The same reading takes the three; a difference goes back into spec §3.6. **Read on 2026-09-14, and all three are answered differently: `204`, where §6.6 refused.** Decided by the operator the same day: the duplicate kept once, nested and relative refused as a divergence (§6.6) |
| A proxy on the same machine forwards no address | Low for an operator following the documentation | High: the window is open to the proxy's network until setup finishes | Documented beside `trusted_proxies` and in the client's refusal text; §6.1 says it cannot be detected |
| Widening `CollectionType` reaches code that matched on three values with an `else` | Medium | Medium: an unscannable library resolved as music (`resolver.py:120-125` today) | `SCANNED_TYPES` keys every scan-side map, and a test scans a `books` library over a music tree and asserts no item |
| The `\w` difference admits or refuses a username the reference would not | Low | Low | §6.4's explicit category test |

## 10. Alternatives considered

**A local-only authentication path for the CLI** — a socket, a token file the server writes on first
start. The roadmap names *"a second authentication path for 'local' callers"* as out of v2. The
setup window is not that: it is the reference's own first branch narrowed, and it closes for good.

**Scanning inside the request.** Simple, and wrong twice: the spec measured that neither `204`
waits, and a request held for the length of a scan meets every proxy's and client's timeout.

**A queue of scan requests, one entry per request.** Three `POST /Library/Refresh` in a row would
scan everything three times. Coalescing does what the caller meant.

**Cancelling a running scan on refresh, as the reference's `Cancelling` suggests.** The spec records
that the library reached all its films either way and does not say which happened; implementing a
cancellation would be choosing a reading that was not taken, and rolling back a library's
transaction halfway costs the work already done.

**Starting a scan for `refreshLibrary=false`**, to match what was observed. What started that scan
was not isolated, and a trigger nobody can name is not one this server should invent.

**All 37 `LibraryOptions` properties at the reference's defaults** (OQ-13). Identical in shape, and
every property but the paths would state a behaviour this server does not have — Principle VI's
plausible-looking stub. Rejected by the operator on 2026-09-14 in favour of the honoured subset.

**Accepting nested and relative paths as the reference does** (T1's reading). Nested roots give a
file under the inner one two identifiers here, because an item's identifier hashes its path relative
to its root, and a relative path names whatever the working directory is. Rejected by the operator
on 2026-09-14 in favour of refusing both ([behaviours §3.31](../../docs/compatibility/behaviours.md)).

**Trusting only the TCP peer** (OQ-11). A proxy on the same machine would make every request local
and open the window to its whole network. **Keeping uvicorn's default and documenting it** leaves a
security rule on a library default no test in this repository can see. Both rejected by the
operator on 2026-09-14.

**An environment variable for the password, or a stored token** (OQ-9). The first is readable by
other processes of the same user; the second needs a location, an expiry and a sign-out this
feature's surface does not have. Rejected by the operator on 2026-09-14.

**Leaving an upgraded server's window open, or refusing to start.** The first lets any local process
reset the first account's password on a server that has been in use; the second breaks a working
install until someone intervenes by hand. Rejected by the operator on 2026-09-14 in favour of §6.2.

**A subcommand of `atrium` instead of a second script.** The server's entry point would import the
client, and the import-direction test is simpler to state as *"nothing in `atrium.cli` imports the
server, and nothing in the server imports `atrium.cli`"* when they are two programs.
