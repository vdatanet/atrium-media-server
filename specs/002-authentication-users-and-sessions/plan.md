---
feature: 002-authentication-users-and-sessions
title: Authentication, users and sessions — implementation plan
status: Implemented
created: 2026-08-26
updated: 2026-09-05
amended: 2026-08-26 by the T1 probe - sections 6.1, 6.2, 7 and 8; by T2 - sections 3 and 7; by T3 - section 6.2; by T4 - sections 1, 3, 4 and 10; by T6 - section 6.4; by T7 - sections 5, 6.1 and 6.3; by T8 - sections 6.5 and 6.6; by T9 - section 7; by T14 - sections 8.2 and 9; by T15 - sections 8.1 and 9; by T16 - section 8.3; and 2026-09-05 by the 2026-09-04 audit's M16, the first amendment here that no task of this feature made - section 3's tree omitted two modules this feature's own tasks created, `domain/session.py` (T5, `fb4df84`) and `logs.py` (T14, `54fd132`), the second of which appeared in no plan's tree in the repository at all. Both are drawn now, with the reconciliation sentence 001's plan set the style for. No code moves
spec_status_required: Accepted
spec_status_actual: Implemented
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

**The policy object is two things wearing one name.** The reference's `UserPolicy` carries **42**
properties `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`; v1 honours **eleven** ([spec §3.5](spec.md#35-the-user-object)). Storing 42
typed columns to enforce eleven would be dishonest about which ones mean anything. **The honoured
ones get real columns; the other 31 are kept in a JSON blob and echoed back unchanged.**

Eleven honoured properties become **nine columns**, because two of the eleven — `EnabledFolders`
and `EnableContentDeletionFromFolders` — are lists of libraries rather than flags, and those are
the join table below. Three counts, all correct, all different: it is worth writing down which one
a sentence means. The split is visible in
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
├── logs.py               the engine logger's level, and the credential a URL puts in a log line
├── db/
│   ├── engine.py         session factory, WAL pragmas, lifecycle
│   ├── types.py          the column types SQLite does not have
│   ├── schema.py         which revision this build expects, and what it does when it is wrong
│   ├── models.py         ORM tables
│   ├── repositories.py   the boundary: domain objects in and out
│   └── migrations/       Alembic, starting at revision 0001
├── domain/
│   └── session.py        AccessToken, IssuedToken and Session — the seam's other return types
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

**Two of those modules are not in the tree this plan was accepted with, and both are this
feature's own** — added on 2026-09-05 by the 2026-09-04 audit's M16, in 001's style for a tree that
outgrew its acceptance rather than as a silent edit. `domain/session.py` arrived with **T5**
(`fb4df84`) beside the repositories, because ADR-0003 sends domain objects across that boundary and
never rows, and a `Session` is what `/Sessions` reports where an `AccessToken` is what a request is
authenticated against — one module because they are created, replaced and deleted together. It is
named in **007's** plan twice (`plan.md:45,130`) and drawn in no tree until now, which is
`domain/media.py`'s shape one audit finding earlier (L2). `logs.py` arrived with **T14**
(`54fd132`), out of §9's risk table rather than out of a route: the two leaks it closes are library
defaults, not anything this project wrote, and the section below and that table have named
`atrium.logs` since the day it landed while §3 did not. Neither is a change to the module set this
plan chose; both are the record catching up with it.

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
| `is_administrator`, `is_disabled`, `is_hidden`, `enable_all_folders`, `enable_media_playback`, `enable_content_deletion`, `login_attempts_before_lockout`, `invalid_login_attempt_count`, `max_active_sessions` | **The nine honoured columns**, typed and queryable. `login_attempts_before_lockout` defaults to the reference's own **-1**, which is a sentinel — this schema stores the reference's vocabulary and does not decide what it means |
| `policy_extra` | JSON: the other 31 policy properties, echoed unchanged |
| `configuration` | JSON: the whole `UserConfiguration`, echoed unchanged |

**`user_library_access`** — one row per `(user_id, library_id)`, with `can_view` for
`EnabledFolders` and `can_delete` for `EnableContentDeletionFromFolders`. A join table rather than
a JSON list because 005 filters queries on it, on every request. `library_id` carries **no foreign
key**: the table it would point at arrives with 003.

**Every table declares its children as relationships**, not only as foreign-key columns. The unit
of work orders inserts by relationship and not by `ForeignKey`, so a user and its first token
created in one flush go in child-first and the database rejects them — which it only does at all
because the engine turns the foreign-key pragma on. The relationships are `lazy="raise"`, since no
ORM object crosses the repository boundary and a lazy load would mean one had.

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

**`users.service.Authenticator.authenticate(username, password, info, remote_end_point=None) ->
AuthResult`** — the only entry
point that verifies a password. It owns the lockout counter, the timing guarantee of §6.2 and
session creation, because splitting those across callers is how one of them gets forgotten.

**`api.deps.require_user`** — the 001 seam, now implemented. Signature unchanged, which was the
point of defining it early.

```python
async def require_user(request: Request) -> User:
    """Resolve any of the five token mechanisms to a user, or refuse."""
```

**`compat.auth.extract_token(request) -> str | None`** and
**`compat.auth.parse_client_authorization(value) -> ClientInfo | None`** — pure functions over a
request and a header, with no I/O, so the five mechanisms and the grammar are table-testable
without a server. The `| None` is T7's correction: an unreadable header is not this function's
error to raise, because whether it matters depends on the route (§6.3).

**`users.sessions.SessionRegistry`** — the in-memory activity layer, with
`touch(token_sha256, session_id, when=None)`, `snapshot()` and `flush()`; 007 grew it
`touch_playback` and `touch_session`. *(The accepted plan's one-argument `touch(token)` was a
contract no caller could follow — corrected at the 2026-08-28 audit, M18 in
[the record](../../docs/audits/2026-08-28.md).)*

## 6. Algorithms

### 6.1 Token extraction

**Five** sources, checked in this order, first hit wins: the `Token=` component of
`Authorization`, then of `X-Emby-Authorization`, then `X-Emby-Token`, then `?ApiKey=`, then
`?api_key=`.

The second was missing from this plan and from the specification until T7 measured it: the
reference reads both header names with the grammar of §6.3, and a token in either authenticates.
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`

**The order is the reference's, measured, not ours.** `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]` This plan first fixed the
opposite one — `X-Emby-Token` ahead of `Authorization` — and argued that the order only had to be
deterministic, since a client sending two identical tokens cannot tell. That argument is sound and
the premise is wrong: a client that sends two sends them from **different places**, a header set
once when the connection was built and a URL assembled from a template, and those two disagree
exactly when one of them is stale. Resolving in the other order turns a request the reference
answers `200` into a `401`, for the clients most likely to do it.

The chain was measured pair by pair, in both directions each time. `Authorization` against a query
parameter is **inferred** from it rather than measured, and the two query spellings were never set
against each other. Both gaps are cheap to close if a client is ever seen to depend on them.

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

`MediaBrowser Client="…", Device="…", DeviceId="…", Version="…"`. Three things this plan said
about it were wrong, and all three were measured in T7 rather than reasoned about. `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`

**The scheme word is required**, not "optional in practice": it must be `MediaBrowser` or `Emby`,
case-insensitively, and without one nothing is read out of the header.

**Whitespace around the `=` is refused.** `Token = x` is a `401` at the reference. Atrium refuses
it too — being kinder lets a client be built against Atrium that fails against Jellyfin
([behaviours §6](../../docs/compatibility/behaviours.md#6-non-improvements)) — and component names
are matched case-sensitively for the same reason.

**A missing `DeviceId` is fatal on one route, not in the parser.** An ordinary authenticated route
serves a header without it. So `parse_client_authorization` reports what it found and returns
`None` for a header it cannot read, and `require_client_authorization` carries
`AuthenticateByName`'s rule — absent, unreadable or no `DeviceId` is a `400` there, and
deliberately not a `401`.

What is genuinely lenient, all measured: any order, values quoted or bare, no space after a comma
or a space before one, extra spaces after the scheme, a trailing comma, and unknown components
ignored rather than rejected.

### 6.4 Policy: enforced versus echoed

Reading assembles a policy object from the nine columns plus the `policy_extra` blob. Writing
splits it back. A property that is in neither the column set nor a known key list is still
preserved — a client that round-trips a policy from a newer server must get its own data back.

**What round-trips is the set of properties and their values, not the byte order.** Assembling
emits this server's own order — the nine columns, the two lists, then everything carried — because
the reference emits its own too: a C# object serialises its properties in a fixed order whatever a
client sent, so echoing a client's key order would be the delta rather than the fidelity.

**An honoured property never lives in the blob.** Splitting strips the eleven out before storing
the rest, and assembling reads each from its column. That is what makes promoting a property from
blob to column lossless in both directions: a stale copy left in an old blob is ignored rather than
shadowing the column, and one write through `split` removes it without a migration of its own.

The same shape applies to `UserConfiguration`, except that **all** of it is stored as a blob: v1
acts on two properties and there is no query that filters on any of them, so there is nothing to
gain from columns.

### 6.5 Session activity without a write per request

`LastActivityDate` and `last_used` advance in an in-memory registry. A background task flushes
dirty rows every 30 seconds, and a flush also happens on clean shutdown.

`/Sessions` reads **through** the registry rather than out of the database: reporting the flushed
value would tell a client that a session it is using right now was last active half a minute ago.

The cost is bounded and stated: **an unclean shutdown loses up to 30 seconds of activity
timestamps.** Nothing else is at risk — the token itself, the session identity and every user
record are written synchronously. An activity timestamp is the only thing in this feature that can
be a little stale without anyone being able to tell.

### 6.6 Session lifecycle

Re-authentication from a known `device_id` replaces the session and deletes its token in one
transaction, so there is no window in which both are valid.

`max_active_sessions` evicts the least-recently-used session on creation, not on a timer, and
**an evicted session's tokens go with it**. A session removed from `/Sessions` whose token still
worked would reappear on that device's next request, which is a gap in a list rather than an
eviction. The reference's behaviour here is not measured; what is written down is that the two
halves have to agree, because a server whose session list and whose credentials disagree is
answering two different questions about the same device.

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
| Locked-out account whose policy carries the reference's `-1` sentinel | Counter, and no threshold to compare it to | **Not locked**, unless the operator sets `lockout_attempts` | — |

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
teaches everyone to ignore it. A ratio is scale-invariant: a runner three times slower moves both
branches together and the assertion does not notice.

**It is the backstop, not the guarantee.** The guarantee is counted — every failure path runs the
KDF exactly once, asserted by counting invocations (§6.2). That test fails for a precise reason and
never flakes. This one checks that the counting test is counting the thing that matters, and it
carries the failure it exists for: with the dummy verify removed, the ratio measured **19×**.

**The KDF has to dominate, or it measures the wrong thing.** Measured through `authenticate`:

| Argon2 memory | unknown | wrong password | ratio |
|---|---|---|---|
| 8 KiB — the suite's own setting | 0.139 ms | 0.493 ms | **3.55** |
| 1 MiB | 0.627 ms | 0.997 ms | 1.59 |
| 4 MiB | 2.132 ms | 2.510 ms | 1.18 |

The gap that does not close is **not** the KDF. It is the failed-attempt counter, which the
known-username path writes and the unknown path does not — a second channel, real, and shrinking
against the KDF as the parameters rise. At the shipped 64 MiB it is under one percent of a 41 ms
verify, so it is bounded and recorded rather than removed: not writing the counter would cost the
lockout the specification requires, and writing it on both paths would mean a table of failed
attempts for usernames that do not exist.

### 8.2 The log test

Authenticate with a known password, capture every log record emitted at every level, and assert the
password appears in none of them — nor in any exception message, nor in a request trace. It runs at
`DEBUG`, because that is where a password gets logged by accident.

**Two claims, two scopes.** The password must not appear *at any level, from any logger*: a promise
this project can keep, because a password never leaves `users/passwords.py`. The stored hash and the
access token must not appear under the logging a server **actually ships with** — asserting them
under force-everything-to-`DEBUG` would be promising that a debug-everything mode is safe, and
nobody can keep that.

Both of the shipped-configuration halves failed when they were written, and neither leak was
anything this project wrote: SQLAlchemy logs bound parameters at `INFO`, and an HTTP library logs
the request line. `atrium.logs` is what T14 added in answer, and it is called by the entry point
rather than left for an operator to discover.

### 8.3 Migrations

Every revision is applied and rolled back in a test — walked from the script directory rather than
named, so a revision added by feature 003 is covered without anybody remembering to extend it. The
first migration additionally runs against a database created from an empty file, which is the path
an operator actually takes.

**Reversible means the schema comes back**, not that a `downgrade()` exists. A downgrade that runs
without error and leaves a table behind passes any test that only checks it did not raise, so each
revision is applied, rolled back, and the schema compared against what was there before it. A
revision that does not restore must contain `irreversible` in its docstring and say why — which is
what turns §4's rule from a sentence into something that fails.

### 8.4 Fixtures

A user factory producing pristine, hidden, disabled and administrator users. The Argon2 parameters
are lowered **in tests only**, through configuration, because a suite that verifies dozens of
passwords at production parameters takes minutes — and a slow suite gets run less often, which
costs more security than the parameters buy.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A password reaches a log | Medium | **Severe** | §8.2, running at `DEBUG` |
| A **hash** reaches a log, because SQLAlchemy writes bound parameters once its logger reaches `INFO` | **Realised** — it did | Moderate | `atrium.logs` sets the engine logger to `WARNING`; an operator who wants SQL echoed turns it on |
| A **token** reaches a log, because two of the five mechanisms put it in a URL | **Realised** — it did | Moderate | `atrium.logs` redacts `api_key=` and `ApiKey=` from any record, leaving the rest of the line |
| Timing discloses valid usernames | **Medium** | Moderate | §6.2, verified by §8.1 |
| The **failed-attempt counter write** is a second timing channel: the known-username path writes it and the unknown path does not | **Measured, and small** | Low | Bounded rather than removed — at the shipped 64 MiB it is under 1% of a 41 ms verify. §8.1 has the numbers |
| Token stored in plain text | Low | Severe on database disclosure | SHA-256 at the repository boundary; a test asserts no column holds a value that authenticates |
| Session flush loses activity on crash | High | **Negligible, and stated** | §6.5 — bounded at 30 seconds, and nothing else is deferred |
| Policy blob loses unknown properties | Medium | Moderate | AC-8 round-trips properties v1 does not know |
| Enforcement and storage drift apart | Medium | Moderate | Honoured flags are columns, everything else is a blob; the schema shows which is which |
| Migration applied to a live database mid-request | Low | Severe | Refuse to start on a pending revision |

## 10. Alternatives considered

**Match the reference's PBKDF2 so a Jellyfin user database could be imported.** Argued and rejected
in [ADR-0006](../../docs/decisions/0006-password-hashing.md). The short version: importing is not a
goal, and it would fix the project to a KDF chosen for compatibility rather than for strength.

**Store tokens in plain text, as the reference does** `[source:
src/Jellyfin.Database/Jellyfin.Database.Implementations/Entities/Security/Device.cs:29,52 @
v10.11.11]` — a GUID generated at construction and held in an unconstrained `string` column, with
no hash and no transformation anywhere between. No compatibility cost either way, since a stored
token never reaches a client. Hashing is a few lines and it means a leaked database does not
hand over live sessions.

**42 typed policy columns.** Complete and honest about the shape, dishonest about the meaning: a
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
