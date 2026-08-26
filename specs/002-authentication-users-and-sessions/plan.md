---
feature: 002-authentication-users-and-sessions
title: Authentication, users and sessions — implementation plan
status: Accepted
created: 2026-08-26
updated: 2026-08-26
amended: 2026-08-26 by the T1 probe - sections 6.1, 6.2, 7 and 8; by T2 - sections 3 and 7; by T3 - section 6.2
spec_status_required: Accepted
spec_status_actual: Accepted
accepted: 2026-08-26
---

# 002 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour.

## 1. Approach

002 is where the project acquires **state that outlives a request**, and most of the plan follows
from that rather than from authentication as such.

Four decisions carry it.

**The database arrives here** — SQLAlchemy 2.0, Alembic, SQLite in WAL mode, per
[ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md). 001 deliberately shipped
without one because acceptance criterion 4 forbade putting server identity in a rebuildable store.
That constraint does not move: **`state.json` keeps the server identity, and the database never
holds it.** The first Alembic migration creates users, tokens and sessions, and nothing else.

**Password storage is not a compatibility question**, which is unusual for this project and easy to
get wrong by reflex. A hash never reaches a client, so Principle I is silent and the choice is made
on security grounds alone: Argon2id, decided in
[ADR-0006](../../docs/decisions/0006-password-hashing.md).

**The policy object is two things wearing one name.** The reference's `UserPolicy` carries about
forty flags; v1 honours nine ([spec §3.5](spec.md#35-the-user-object)). Storing forty typed columns
to enforce nine would be dishonest about which ones mean anything. **The nine honoured flags get
real columns; the rest are kept in a JSON blob and echoed back unchanged.** The split is visible in
the schema, so a reader can tell enforcement from storage without reading the enforcement code —
and adding a tenth means moving a key out of the blob into a column, which is a migration and
therefore a decision someone makes on purpose.

**Session activity is not a write per request.** `LastActivityDate` advances on every authenticated
call, and persisting that would make SQLite take a write lock on every request — the exact
behaviour WAL mode exists to avoid needing. Sessions live in memory with periodic flushing; §6.5.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001 | [001 plan §2](../001-server-identity-and-discovery/plan.md#2-inherited-decisions) |
| SQLAlchemy 2.0 + Alembic, SQLite in WAL mode | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |
| Argon2id for passwords, SHA-256 for tokens | [ADR-0006](../../docs/decisions/0006-password-hashing.md) |
| `AtriumModel`, the alias and unit sweeps, the `require_user` seam | [001 plan §5](../001-server-identity-and-discovery/plan.md#5-contracts) |
| Repositories return domain objects; no ORM type crosses into `domain/` | [architecture §1](../../docs/architecture.md) |

**Deviations:** none.

## 3. Modules

```
src/atrium/
├── db/
│   ├── engine.py         session factory, WAL pragmas, lifecycle
│   ├── schema.py         which revision this build expects, and what it does when it is wrong
│   ├── models.py         ORM tables
│   ├── repositories.py   the boundary: domain objects in and out
│   └── migrations/       Alembic, starting at revision 0001
├── users/
│   ├── service.py        authenticate, lock out, resolve a token
│   ├── passwords.py      Argon2id hash, verify, rehash-on-login
│   ├── policy.py         the nine honoured flags, and the blob
│   └── sessions.py       lifecycle, in-memory activity, eviction
├── compat/
│   └── auth.py           token extraction; X-Emby-Authorization parsing
└── api/
    ├── users.py          the five user routes
    ├── sessions.py       /Sessions, /Sessions/Capabilities/Full
    └── deps.py           require_user — the 001 seam, now implemented
```

`alembic.ini` sits at the repository root for running migrations by hand. **The server does not
read it**, and no database URL appears in it: a path in an ini file is a path that disagrees with
`$ATRIUM_DATA_DIR` eventually, and `configparser` reads `%` in a path as interpolation, so a data
directory containing one would fail in a way nobody would guess. `db/schema.py` builds the same
configuration from `__file__`, because an installed server has no working directory worth trusting.

`compat/auth.py` holds **extraction**, not resolution: pulling a token out of four possible places
and parsing a client-identification header are wire-format concerns and belong beside the other
wire-format code. Turning a token into a user is `users/`.

## 4. Data model

First migration, `0001_users_and_sessions`.

**`users`**

| Column | Notes |
|---|---|
| `id` | 32-hex, generated (`compat/guids.py`) |
| `name`, `name_normalised` | Login is case-insensitive; the normalised form is unique-indexed |
| `password_hash` | The self-describing Argon2id string, nullable for passwordless accounts |
| `last_login_date`, `last_activity_date` | |
| `invalid_login_attempt_count` | Reset on success |
| `is_administrator`, `is_disabled`, `is_hidden`, `enable_all_folders`, `enable_media_playback`, `enable_content_deletion`, `login_attempts_before_lockout`, `max_active_sessions` | **The honoured flags**, typed and queryable |
| `policy_extra` | JSON: every other policy property, echoed unchanged |
| `configuration` | JSON: the whole `UserConfiguration`, echoed unchanged |

**`user_library_access`** — `(user_id, library_id)` for `EnabledFolders`, and
`enable_content_deletion_from_folders`. A join table rather than a JSON list because 005 filters
queries on it.

**`access_tokens`**

| Column | Notes |
|---|---|
| `token_sha256` | **The hash, never the token.** Primary lookup key |
| `user_id`, `device_id`, `client`, `device_name`, `app_version` | From `X-Emby-Authorization` |
| `created`, `last_used` | `last_used` is flushed, not written per request (§6.5) |

**`sessions`** — one row per `(user_id, device_id)`, carrying the declared capabilities as JSON and
the identity fields `/Sessions` returns. Live playback state is **not** here; 007 owns it and keeps
it in memory.

**Migrations are reversible**, and the test applies each one and rolls it back. A migration that
cannot be reversed is allowed, but it has to say so in its docstring and explain why — the point is
that irreversibility is a decision, not an oversight.

## 5. Contracts

**`users.service.authenticate(username, password, client_info) -> AuthResult`** — the only entry
point that verifies a password. It owns the lockout counter, the timing guarantee of §6.2 and
session creation, because splitting those across callers is how one of them gets forgotten.

**`api.deps.require_user`** — the 001 seam, now implemented. Signature unchanged, which was the
point of defining it early.

```python
async def require_user(request: Request) -> User:
    """Resolve any of the four token mechanisms to a user, or raise 401."""
```

**`compat.auth.extract_token(request) -> str | None`** and
**`compat.auth.parse_client_authorization(value) -> ClientInfo`** — pure functions over a request
and a header, with no I/O, so the four mechanisms and the lenient parsing are table-testable
without a server.

**`users.sessions.SessionRegistry`** — the in-memory activity layer, with `touch(token)`,
`snapshot()` and `flush()`.

## 6. Algorithms

### 6.1 Token extraction

Four sources, checked in this order, first hit wins: `Authorization: MediaBrowser Token="…"`,
`X-Emby-Token`, `?ApiKey=`, `?api_key=`.

**The order is the reference's, measured, not ours.** `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]` This plan first fixed the
opposite one — `X-Emby-Token` ahead of `Authorization` — and argued that the order only had to be
deterministic, since a client sending two identical tokens cannot tell. That argument is sound and
the premise is wrong: a client that sends two sends them from **different places**, a header set
once when the connection was built and a URL assembled from a template, and those two disagree
exactly when one of them is stale. Resolving in the other order turns a request the reference
answers `200` into a `401`, for the clients most likely to do it.

`Authorization` against a query parameter is **inferred** from the two pairs that were measured
rather than measured itself, and the two query spellings were never set against each other. Both
gaps are cheap to close if a client is ever seen to depend on them.

### 6.2 Authentication, and the timing guarantee

```
normalise the username
look up the user
if absent:            verify the password against a DUMMY Argon2id record, then 401
if disabled:          verify anyway, then 403
if locked out:        verify anyway, then 403
verify the password
if wrong:             increment the counter, 401
if right:             reset the counter, rehash if parameters are stale, create the session
```

**Every failure path runs the KDF.** Argon2id takes tens of milliseconds; skipping it for an
unknown username makes the response measurably faster and turns the login endpoint into a username
oracle. The dummy record is generated once at startup, never from a real password.

**The four failures do not return one status.** A disabled account is `403` and an unknown
username is `401` `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]` — measured, and the opposite of what this plan and the
specification both assumed. All four carry the *same body*, so the status is the entire difference;
[spec §3.3](spec.md#33-post-usersauthenticatebyname--authenticateuserbyname) has the table and
[behaviours §2.11](../../docs/compatibility/behaviours.md#211-a-disabled-account-is-refused-with-403-not-401)
has the argument.

The KDF still runs on the disabled and locked-out paths even though their status already discloses
the account's state. It costs one verify and it keeps the property true where it does matter —
between an unknown username and a wrong password, which are the two the status cannot separate.

**"Rehash if the parameters are stale" means below the policy, not different from it.** argon2-cffi's
`check_needs_rehash` means *different*, and reports true for a record made with **stronger**
parameters than the current ones. Taking that meaning would rewrite a strong record weaker at the
one moment the plaintext exists — so an operator who lowered these settings after moving to a
smaller machine would silently downgrade every account on its owner's next login, with nothing
saying so. [ADR-0006](../../docs/decisions/0006-password-hashing.md) says *below*, and Atrium
compares memory and time itself rather than delegating.

**Parallelism is deliberately not part of that comparison.** It divides the same work across lanes
rather than adding any — RFC 9106 sets it from the cores available, and the cost is carried by
memory and time. Rewriting a record because `p` moved would spend the plaintext moment on a change
with no security in it.

### 6.3 The `X-Emby-Authorization` grammar

`MediaBrowser Client="…", Device="…", DeviceId="…", Version="…"`, parsed leniently: any order,
optional whitespace, values quoted or bare, unknown components ignored, the `MediaBrowser` prefix
optional in practice. Missing `DeviceId` is the one fatal case, because it is what identifies the
session — and that is a `400`, not a `401`.

### 6.4 Policy: enforced versus echoed

Reading assembles a policy object from the nine columns plus the `policy_extra` blob. Writing
splits it back. A property that is in neither the column set nor a known key list is still
preserved — a client that round-trips a policy from a newer server must get its own data back.

The same shape applies to `UserConfiguration`, except that **all** of it is stored as a blob: v1
acts on two properties and there is no query that filters on any of them, so there is nothing to
gain from columns.

### 6.5 Session activity without a write per request

`LastActivityDate` and `last_used` advance in an in-memory registry. A background task flushes
dirty rows every 30 seconds, and a flush also happens on clean shutdown.

The cost is bounded and stated: **an unclean shutdown loses up to 30 seconds of activity
timestamps.** Nothing else is at risk — the token itself, the session identity and every user
record are written synchronously. An activity timestamp is the only thing in this feature that can
be a little stale without anyone being able to tell.

### 6.6 Session lifecycle

Re-authentication from a known `device_id` replaces the session and deletes its token in one
transaction, so there is no window in which both are valid.

`max_active_sessions` evicts the least-recently-used session on creation, not on a timer.

**v1 does not expire tokens on inactivity**, per [spec §3.8](spec.md#38-sessions) OQ-2: a token
that outlives the reference's is invisible to a client, whereas one that dies sooner produces
spurious logouts. The registry is built so a window can be added without a migration.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Unknown username | Lookup miss | `401`, after the dummy verify | — |
| Wrong password | Verify fails | `401`, counter incremented | Correct password resets it |
| Disabled user | Flag | **`403`**, whatever the password | Operator intervention |
| Locked-out user | Counter | **`403`**; the reference's answer here is unmeasured, [spec §7](spec.md#7-open-questions) OQ-5 | Operator intervention, or a success after the window |
| Missing `DeviceId` | Header parse | `400` | Client fixes its header |
| Token unknown or expired | Lookup miss | `401` | Client re-authenticates |
| Valid token, insufficient policy | Policy check | `403` | — |
| Database unavailable at startup | Connection check | **Refuse to start** | Operator fixes it |
| Migration pending | Alembic revision check | **Refuse to start**, naming the command | Operator migrates |
| Database **empty** — no tables at all | Same check | **Create it** and bring it to head | — |
| Tables but no revision stamp | Same check | **Refuse to start**, naming the tables | Operator moves the file aside |
| Stamped at a revision this build does not know | Same check | **Refuse to start** | Operator reinstalls the newer build |

**The empty database is not the pending-migration case, and the first draft of this table treated
it as one.** A first run has no schema, and answering "run a migration first" to somebody who has
just installed the server is a refusal with no decision behind it: creating a schema where there
was none cannot lose anything, because there is nothing to lose. Upgrading a database that already
holds data is the decision an operator makes, and that is the one this table refuses.

**A database from the future is not "behind".** Downgrading the server leaves a file a newer build
wrote, and reading that as pending would run migrations backwards over data this build cannot read.
It is the row nobody thinks of and everybody eventually reaches, so it is a row rather than a
surprise.
| Argon2 parameters unsupported | Verify raises | `401` plus a log line naming the user | Password reset |

**Refusing to start on a pending migration** matters more than it looks: serving requests against a
schema the code does not expect produces corrupt data rather than an error, and the corruption is
discovered much later.

## 8. Testing strategy

| Spec AC | Test |
|---|---|
| 1 | Golden response for `AuthenticateByName`, asserting a 32-hex token |
| 2 | The refusals compared as **bytes**: an unknown username is `401`, a disabled account is `403`, a missing header is `400`, and all three carry the reference's 25-byte `text/plain` body |
| 3 | The four mechanisms, table-driven, across an API route, an image route and a delivery route — the last two through stub routes until 006 and 008 exist — plus the four precedence pairs of §6.1. The stubs assert that all four are *accepted*, not that a token is required: the reference requires none on either class |
| 4 | `401` versus `403` matrix |
| 5 | Re-authentication replaces the session and invalidates the prior token |
| 6 | `/Users/Public` omits `Configuration` and `Policy`; all-hidden fixture returns `[]` |
| 7 | Cross-user read as ordinary user and as administrator |
| 8 | Configuration round-trips, **including properties v1 does not act on** |
| 9 | Capabilities posted, then read back through `/Sessions` |
| 10 | Lockout after N failures, reset after one success |
| 11 | **The log test** — §8.2 |

### 8.1 The timing test

Measure `authenticate` for an unknown username and for a known username with a wrong password;
assert the two distributions overlap. Written as a **ratio with a generous bound** rather than an
absolute time, because a timing test that asserts milliseconds fails on a loaded CI runner and
teaches everyone to ignore it.

### 8.2 The log test

Authenticate with a known password, capture every log record emitted at every level, and assert the
password appears in none of them — nor in any exception message, nor in a request trace. It runs at
`DEBUG`, because that is where a password gets logged by accident.

### 8.3 Migrations

Every revision is applied and rolled back in a test. The first migration additionally runs against a
database created from an empty file, which is the path an operator actually takes.

### 8.4 Fixtures

A user factory producing pristine, hidden, disabled and administrator users. The Argon2 parameters
are lowered **in tests only**, through configuration, because a suite that verifies dozens of
passwords at production parameters takes minutes — and a slow suite gets run less often, which
costs more security than the parameters buy.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A password reaches a log | Medium | **Severe** | §8.2, running at `DEBUG` |
| Timing discloses valid usernames | **Medium** | Moderate | §6.2, verified by §8.1 |
| Token stored in plain text | Low | Severe on database disclosure | SHA-256 at the repository boundary; a test asserts no column holds a value that authenticates |
| Session flush loses activity on crash | High | **Negligible, and stated** | §6.5 — bounded at 30 seconds, and nothing else is deferred |
| Policy blob loses unknown properties | Medium | Moderate | AC-8 round-trips properties v1 does not know |
| Enforcement and storage drift apart | Medium | Moderate | Honoured flags are columns, everything else is a blob; the schema shows which is which |
| Migration applied to a live database mid-request | Low | Severe | Refuse to start on a pending revision |

## 10. Alternatives considered

**Match the reference's PBKDF2 so a Jellyfin user database could be imported.** Argued and rejected
in [ADR-0006](../../docs/decisions/0006-password-hashing.md). The short version: importing is not a
goal, and it would fix the project to a KDF chosen for compatibility rather than for strength.

**Store tokens in plain text, as the reference does.** No compatibility cost either way, since a
stored token never reaches a client. Hashing is a few lines and it means a leaked database does not
hand over live sessions.

**Forty typed policy columns.** Complete and honest about the shape, dishonest about the meaning: a
column implies something reads it, and thirty-one of them nothing would. The split makes the
distinction structural.

**JSON columns for everything, including the honoured flags.** One less concept, and it puts library
visibility inside a blob — which 005 has to filter on, in a query, on every request. Rejected on
that alone.

**Writing activity timestamps synchronously.** Simplest, and it takes a write lock on SQLite for
every authenticated request. The cost of the alternative is thirty seconds of timestamp drift after
a crash, which no client can observe.

**A separate table per policy flag, or an entity-attribute-value design.** Infinitely flexible, and
it makes every read a join and every query unreadable. Rejected.
