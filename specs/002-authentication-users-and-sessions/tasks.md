---
feature: 002-authentication-users-and-sessions
title: Authentication, users and sessions — tasks
status: Draft
created: 2026-08-26
updated: 2026-08-26
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 002 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The three security-shaped tasks — T2, T7 and T13 — are not "add hardening later" work.** The
timing guarantee is inside `authenticate`, not around it; the log test runs at `DEBUG` because that
is where a password gets logged by accident; and tokens are hashed at the repository boundary so no
caller can choose otherwise. Each of those is cheap now and a rewrite once code depends on the
looser shape.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — `db/`: engine, session factory, Alembic

- [ ] **Changes:** `db/engine.py` with WAL and foreign-key pragmas applied per connection and a
  session factory tied to the app lifecycle; Alembic scaffolding; a startup check that refuses to
  serve when the database revision is behind the code.
- **Depends on:** 001 complete
- **Verified by:** a fresh database is created in a temporary data directory; `PRAGMA journal_mode`
  reports `wal`; a database stamped at an older revision **refuses to start**, naming the command
  to run.
- **Note:** refusing beats warning. Serving against an unexpected schema produces corrupt data
  rather than an error, and the corruption surfaces much later.
- **Plan reference:** §3, §7

## T2 — `users/passwords.py`: Argon2id

- [ ] **Changes:** hash, verify, and `needs_rehash`; the self-describing stored format; the dummy
  record generated once at startup; parameters read from configuration.
- **Depends on:** T1
- **Verified by:** a hash round-trips; a wrong password fails; a record written with lower
  parameters verifies **and** reports `needs_rehash`; the stored string parses back to its
  algorithm and parameters. The dummy record is never derived from a real password — asserted.
- **Plan reference:** [ADR-0006](../../docs/decisions/0006-password-hashing.md), §6.2

## T3 — Migration `0001_users_and_sessions`

- [ ] **Changes:** `users` with the **nine honoured policy columns** plus `policy_extra` and
  `configuration` blobs; `user_library_access`; `access_tokens` keyed on `token_sha256`; `sessions`.
- **Depends on:** T1
- **Verified by:** upgrade then downgrade leaves an empty database; upgrade from an empty file
  works, which is the path an operator actually takes; `access_tokens` has **no column holding a
  usable token** — asserted by name and by a value test.
- **Plan reference:** §4

## T4 — `db/repositories.py`: the boundary

- [ ] **Changes:** user, token and session repositories returning **domain objects**, never ORM
  rows; token hashing happens here, so no caller can store a plaintext token.
- **Depends on:** T3
- **Verified by:** a test asserting no SQLAlchemy type escapes the module's public functions;
  storing a token and reading it back never yields the original string.
- **Plan reference:** §3, architecture §1

## T5 — `users/policy.py`: enforced versus echoed

- [ ] **Changes:** assembling a policy object from nine columns plus the blob, and splitting it back
  on write.
- **Depends on:** T4
- **Verified by:** **AC-8's shape** — a policy containing properties v1 has never heard of
  round-trips byte-identically; the nine honoured flags land in columns and are queryable; a
  property moved from blob to column in a later migration is not lost.
- **Plan reference:** §6.4

## T6 — `compat/auth.py`: extraction and parsing

- [ ] **Changes:** `extract_token` over the four mechanisms in a fixed order; `parse_client_authorization`
  for `X-Emby-Authorization`, lenient about order, whitespace, quoting and unknown components.
- **Depends on:** 001 complete
- **Verified by:** a table over the four mechanisms including a request carrying **two**, which
  resolves deterministically; a parser table with reordered, unquoted, whitespace-padded and
  extra-component headers; a header missing `DeviceId` is the one fatal case.
- **Note:** pure functions over a request. No I/O, so the whole table runs without a server.
- **Plan reference:** §5, §6.1, §6.3

## T7 — `users/service.py`: authenticate

- [ ] **Changes:** the single entry point that verifies a password, owning the lockout counter, the
  timing guarantee and session creation.
- **Depends on:** T2, T5, T6
- **Verified by:** correct credentials succeed; **every failure path runs the KDF** — unknown user,
  disabled user, locked-out user, wrong password — asserted by counting KDF invocations, not by
  timing; lockout after N failures; one success resets the counter.
- **Note:** the four failures return the same `401` with the same body. A test compares the four
  responses byte-for-byte.
- **Plan reference:** §5, §6.2

## T8 — `users/sessions.py`: the registry

- [ ] **Changes:** `SessionRegistry` with in-memory activity, a 30-second flush, flush on clean
  shutdown, LRU eviction at `max_active_sessions`, and replace-on-reauthentication in one
  transaction.
- **Depends on:** T4
- **Verified by:** re-authenticating from a known `device_id` leaves exactly one session and the
  prior token invalid, **with no window in which both work** — tested by interleaving; eviction
  removes the least recently used; an unclean shutdown loses at most one flush interval of
  timestamps **and nothing else**.
- **Plan reference:** §6.5, §6.6

## T9 — `api/deps.py`: `require_user`, implemented

- [ ] **Changes:** replace 001's always-`401` body. Signature unchanged.
- **Depends on:** T7
- **Verified by:** 001's tests still pass unmodified; a valid token reaches the route body; an
  unknown token is `401`; a valid token lacking permission is `403`.
- **Note:** if the signature needs changing, that is a finding for 001's plan, not a quiet edit.
- **Plan reference:** §5

## T10 — `api/users.py`: the five user routes

- [ ] **Changes:** `POST /Users/AuthenticateByName`, `GET /Users/Public`, `GET /Users/Me`,
  `GET /Users/{userId}`, `POST /Users/Configuration`, and their models.
- **Depends on:** T9
- **Verified by:** golden responses; `/Users/Public` omits `Configuration` and `Policy` and returns
  `[]` for an all-hidden fixture; cross-user reads are `403` for an ordinary user and `200` for an
  administrator.
- **Plan reference:** §3

## T11 — `api/sessions.py`

- [ ] **Changes:** `GET /Sessions`, `POST /Sessions/Capabilities/Full`.
- **Depends on:** T8, T9
- **Verified by:** capabilities posted then read back through `/Sessions`; a two-device fixture
  shows two sessions; `SupportsMediaControl` and `SupportsRemoteControl` are `false`, which is
  honest rather than a gap — a client seeing `true` would offer a remote-control UI that does
  nothing.
- **Plan reference:** §3

## T12 — The four mechanisms across route classes

- [ ] **Changes:** `tests/conformance/test_auth_mechanisms.py`, table-driven over mechanism ×
  route class.
- **Depends on:** T10
- **Verified by:** **AC-3** — all four authenticate an API route identically. Image and delivery
  routes use stub routes carrying the same dependency until 006 and 008 exist, and the stubs are
  replaced rather than duplicated when they do.
- **Note:** supporting only the headers leaves browsing working and every poster and stream broken.
  That failure looks like a client bug, which is why it gets its own test rather than being implied.
- **Plan reference:** §8

## T13 — The log test

- [ ] **Changes:** `tests/security/test_no_password_in_logs.py`.
- **Depends on:** T7
- **Verified by:** authenticate with a known password at `DEBUG`, capture every record from every
  logger, and assert the password appears in none — nor in an exception message, nor a request
  trace, nor a repr.
- **Note:** `DEBUG` is the point. Nobody logs a password at `INFO`.
- **Plan reference:** §8.2, §9

## T14 — The timing test

- [ ] **Changes:** `tests/security/test_login_timing.py`.
- **Depends on:** T7
- **Verified by:** unknown username and known-username-wrong-password produce **overlapping**
  distributions, asserted as a ratio with a generous bound.
- **Note:** a ratio, not milliseconds. A timing test that asserts absolute time fails on a loaded
  runner and teaches everyone to ignore it — which is worse than not having it.
- **Plan reference:** §8.1

## T15 — Migration tests

- [ ] **Changes:** apply and roll back every revision; upgrade from an empty file.
- **Depends on:** T3
- **Verified by:** green both directions. An irreversible migration is allowed but must say so in
  its docstring and say why.
- **Plan reference:** §4, §8.3

## T16 — Surface and golden responses

- [ ] **Changes:** golden files for all seven 002 endpoints; `surface.yaml` route-registration test
  extended to cover them.
- **Depends on:** T10, T11
- **Verified by:** every 002 route in `surface.yaml` is registered and **no route exists outside the
  file**; `tools/extract_v1_surface.py` passes.
- **Plan reference:** conformance L0/L1

---

## Definition of done

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing
      test — all eleven, by name.
- [ ] Every endpoint reaches the level declared in [`spec.md` §6](spec.md#6-conformance). **L3 for
      `AuthenticateByName` is deferred to 010** and the gap is recorded, not counted as met.
- [ ] No column in any table holds a value that would authenticate if disclosed.
- [ ] The three security tests — no password in logs, overlapping login timing, KDF on every failure
      path — pass, and each fails when its guarantee is deliberately removed.
- [ ] `surface.yaml` covers every route added, and no route exists outside it.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same change.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next one

005 filters every query on library visibility, so `user_library_access` has to be a real join table
and not a JSON list. 007 attaches play state to sessions, so the registry has to expose a session by
its id without a database round-trip. Both are cheap here and awkward to retrofit.
