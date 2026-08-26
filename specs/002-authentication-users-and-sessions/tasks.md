---
feature: 002-authentication-users-and-sessions
title: Authentication, users and sessions — tasks
status: Accepted
created: 2026-08-26
updated: 2026-08-26
accepted: 2026-08-26
started: 2026-08-26
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 002 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The three security-shaped tasks — T3, T9 and T14 — are not "add hardening later" work.** The
timing guarantee is inside `authenticate`, not around it; the log test runs at `DEBUG` because that
is where a password gets logged by accident; and tokens are hashed at the repository boundary so no
caller can choose otherwise. Each of those is cheap now and a rewrite once code depends on the
looser shape.

**The probe is T1, and it is not a formality.** [spec §7](spec.md#7-open-questions) leaves two
questions open, and OQ-3 — whether the reference refuses a disabled user with `401` or `403` —
decides AC-2, which four of these tasks assert. Every task in 001 from T4 onwards found something
the specification had wrong, and not one of them was found by reasoning. T1 does not block the
database work; it blocks the tasks whose behaviour it decides, and those say so.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

Every command below is run through `uv`, per
[ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md).

---

## T1 — `tools/probe_auth_mechanisms.py`: measure before implementing  ✅

- [x] **Changes:** a probe answering [spec §7](spec.md#7-open-questions) OQ-1 and OQ-3 — whether
  `X-Emby-Authorization` is accepted outside authentication and whether it changes anything
  alongside a token, and whether a disabled user is refused with `401` or `403`. While it has the
  server: the four mechanisms of [§3.1](spec.md#31-how-a-client-presents-a-token) on an API route,
  an image route and a delivery route; the status and body of a request whose
  `X-Emby-Authorization` is missing, and of one whose header omits `DeviceId`; and the shape of a
  refusal, which [001 T13](../001-server-identity-and-discovery/tasks.md) measured to be two shapes
  rather than one.
- **Depends on:** a reachable Jellyfin 10.11.11. Nothing in this feature.
- **Verified by:** it runs, prints each finding with the citation the documentation uses, and exits
  non-zero when a finding contradicts what this repository claims — the contract in
  [tools/README](../../tools/README.md#probes). OQ-1 and OQ-3 leave [spec §7](spec.md#7-open-questions)
  either resolved with provenance or recorded as a dated debt.
- **Note:** two things stop this being read-only in the way the other probes are, and the probe has
  to refuse rather than discover them. **It must never test lockout**, which would lock a real
  account on the operator's own server. And OQ-3 needs an account somebody has disabled: the probe
  takes that account's name as an argument and exits `2` saying so rather than guessing, because
  guessing here means failed logins against a stranger's account.
- **Plan reference:** [spec §7](spec.md#7-open-questions), [conformance L3](../../docs/compatibility/conformance.md)

### Done — 2026-08-26

**The first finding arrived before a single measurement did.** The `.env` pointed at a server
answering `/System/Info/Public` with `Version 4.9.5.0` and **no `ProductName` at all** — Emby, not
Jellyfin. The guard in `_probe.py` refused, which is exactly what it is for: measuring Emby and
filing the answer under Jellyfin's name would have put false provenance into an accepted
specification, and provenance is the one thing in this repository nothing else can check. Its
message said `ProductName=''`, which reads like a broken probe rather than the right refusal, so it
now names what it found and what a 4.x with no `ProductName` is.

**OQ-3 is contradicted, and it overturns a deliberate decision.** A disabled account is refused
with **`403`**, not `401`; an unknown username gets `401`. The specification did not merely assume
`401` — it argued for it, calling the two indistinguishable *on purpose* so that account state is
not disclosed. The argument was real and the reference does not make it: it discloses the state
anyway, so refusing to disclose it protects nobody who cannot simply ask the reference. What
settles it beyond Principle I is the client behaviour the specification itself describes two
sections earlier: a client re-authenticates on `401`. A disabled account answered `401` puts a user
in a login loop where the correct password fails forever. The security cost that remains is bounded
and written down in
[behaviours §2.11](../../docs/compatibility/behaviours.md#211-a-disabled-account-is-refused-with-403-not-401):
a caller can tell a disabled account from a name that was never registered, and cannot tell a right
password from a wrong one.

**The probe's first run answered the wrong comparison, and the probe was the thing that showed
it.** It measured the disabled account against *itself* — right password and wrong password, both
`403` — and reported them indistinguishable, which is true and is not what AC-2 claims. AC-2 is
about a disabled account being indistinguishable from **rejected credentials**, and that baseline
was never sent. An unknown username supplies it at no risk: no account exists, so no counter moves.
It is `401`, so the two are distinguishable, and the finding only exists because the first run's
output was read as a result rather than as an answer.

**Two findings nobody asked for.** The image and delivery route classes answer `200` **with no
token at all**, so AC-3's premise — that all four mechanisms authenticate an image route and a
delivery route — was asserting something about routes that authenticate nobody. And the mechanism
that wins when a request carries two is not arbitrary: `Authorization` beats `X-Emby-Token`, which
beats either query form. [plan §6.1](plan.md#61-token-extraction) had fixed the **opposite** order
and defended it on the grounds that it only had to be deterministic. The premise was wrong rather
than the reasoning: a client that sends two sends them from a header set once and a URL built from
a template, and they disagree precisely when one is stale.

**A third error shape.** Every refusal from `AuthenticateByName` — `400`, `401`, `403` — is 25 bytes
of `text/plain` with no charset, reading `Error processing request.`
[behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-three-error-shapes-not-one)
said there were two. The same status carries different bytes depending on which layer refused, so
four of this feature's acceptance criteria would have passed while sending the wrong body, had they
been written against status codes.

**Three refusals were not measured, by design.** An enabled account given a wrong password, a
locked-out account, and a live token whose user was disabled afterwards. Each needs a real account
to fail against and moves a counter no probe can reset, on somebody's own installation. They are
[spec §7](spec.md#7-open-questions) OQ-5, and the row in §3.3 for a wrong password says **assumed**
rather than carrying a citation it has not earned.

## T2 — `db/`: engine, session factory, Alembic

- [ ] **Changes:** `db/engine.py` with WAL and foreign-key pragmas applied per connection and a
  session factory tied to the app lifecycle; Alembic scaffolding; a startup check that refuses to
  serve when the database revision is behind the code. SQLAlchemy 2.0 and Alembic enter
  `pyproject.toml` here — the first change to the dependency set since 001 T1, which is where the
  entry-point trap lives: verify the edit landed.
- **Depends on:** 001 complete
- **Verified by:** a fresh database is created in a temporary data directory; `PRAGMA journal_mode`
  reports `wal`; a database stamped at an older revision **refuses to start**, naming the command
  to run.
- **Note:** refusing beats warning. Serving against an unexpected schema produces corrupt data
  rather than an error, and the corruption surfaces much later.
- **Plan reference:** §3, §7

## T3 — `users/passwords.py`: Argon2id

- [ ] **Changes:** hash, verify, and `needs_rehash`; the self-describing stored format; the dummy
  record generated once at startup; parameters read from configuration.
- **Depends on:** T2
- **Verified by:** a hash round-trips; a wrong password fails; a record written with lower
  parameters verifies **and** reports `needs_rehash`; the stored string parses back to its
  algorithm and parameters. The dummy record is never derived from a real password — asserted.
- **Plan reference:** [ADR-0006](../../docs/decisions/0006-password-hashing.md), §6.2

## T4 — Migration `0001_users_and_sessions`

- [ ] **Changes:** `users` with the **nine honoured policy columns** plus `policy_extra` and
  `configuration` blobs; `user_library_access`; `access_tokens` keyed on `token_sha256`; `sessions`.
- **Depends on:** T2
- **Verified by:** upgrade then downgrade leaves an empty database; upgrade from an empty file
  works, which is the path an operator actually takes; `access_tokens` has **no column holding a
  usable token** — asserted by name and by a value test.
- **Plan reference:** §4

## T5 — `db/repositories.py`: the boundary

- [ ] **Changes:** user, token and session repositories returning **domain objects**, never ORM
  rows; token hashing happens here, so no caller can store a plaintext token.
- **Depends on:** T4
- **Verified by:** a test asserting no SQLAlchemy type escapes the module's public functions;
  storing a token and reading it back never yields the original string.
- **Plan reference:** §3, architecture §1

## T6 — `users/policy.py`: enforced versus echoed

- [ ] **Changes:** assembling a policy object from nine columns plus the blob, and splitting it back
  on write.
- **Depends on:** T5
- **Verified by:** the shape AC-8 asks of configuration, applied to policy — a policy containing
  properties v1 has never heard of round-trips byte-identically; the nine honoured flags land in
  columns and are queryable; a property moved from blob to column in a later migration is not lost.
  **AC-8 itself is asserted over HTTP in T11**, because Principle VIII does not accept a criterion
  proven against the function behind the route.
- **Plan reference:** §6.4

## T7 — `compat/auth.py`: extraction and parsing

- [ ] **Changes:** `extract_token` over the four mechanisms in a fixed order; `parse_client_authorization`
  for `X-Emby-Authorization`, lenient about order, whitespace, quoting and unknown components.
- **Depends on:** 001 complete
- **Verified by:** a table over the four mechanisms including a request carrying **two**, which
  resolves deterministically; a parser table with reordered, unquoted, whitespace-padded and
  extra-component headers; a header missing `DeviceId` is the one fatal case.
- **Note:** pure functions over a request. No I/O, so the whole table runs without a server.
- **Plan reference:** §5, §6.1, §6.3

## T8 — `users/sessions.py`: the registry

- [ ] **Changes:** `SessionRegistry` with in-memory activity, a 30-second flush, flush on clean
  shutdown, LRU eviction at `max_active_sessions`, and replace-on-reauthentication in one
  transaction.
- **Depends on:** T5
- **Verified by:** replacing a session for a known `device_id` leaves exactly one session and the
  prior token invalid, **with no window in which both work** — tested by interleaving; eviction
  removes the least recently used; an unclean shutdown loses at most one flush interval of
  timestamps **and nothing else**. AC-5 is this behaviour seen from outside, and T11 asserts it
  there.
- **Note:** the registry lands **before** `authenticate` rather than after it, which is a change
  from the first draft of this list. Authentication creates a session, so writing it first means
  writing session creation twice: once against the repository and again against the registry. The
  dependency runs this way round in the plan too — [§6.2](plan.md#62-authentication-and-the-timing-guarantee)
  ends at "create the session", and [§6.6](plan.md#66-session-lifecycle) is what that means.
- **Plan reference:** §6.5, §6.6

## T9 — `users/service.py`: authenticate

- [ ] **Changes:** the single entry point that verifies a password, owning the lockout counter, the
  timing guarantee and session creation.
- **Depends on:** T3, T6, T7, T8. T1's findings are in: a disabled account is `403`
- **Verified by:** correct credentials succeed; **every failure path runs the KDF** — unknown user,
  disabled user, locked-out user, wrong password — asserted by counting KDF invocations, not by
  timing; lockout after N failures; one success resets the counter.
- **Note:** the four failures do **not** return one status — T1 measured `403` for a disabled
  account and `401` for an unknown username — but they do return one body, 25 bytes of
  `text/plain`. A test compares all four responses byte-for-byte, which is the only way the
  difference is visible.
- **Plan reference:** §5, §6.2

## T10 — `api/deps.py`: `require_user`, implemented

- [ ] **Changes:** replace 001's always-`401` body. Signature unchanged.
- **Depends on:** T9
- **Verified by:** 001's tests still pass unmodified; a valid token reaches the route body; an
  unknown token is `401`; a valid token lacking permission is `403`.
- **Note:** if the signature needs changing, that is a finding for 001's plan, not a quiet edit.
- **Plan reference:** §5

## T11 — `api/users.py`: the five user routes

- [ ] **Changes:** `POST /Users/AuthenticateByName`, `GET /Users/Public`, `GET /Users/Me`,
  `GET /Users/{userId}`, `POST /Users/Configuration`, and their models.
- **Depends on:** T10
- **Verified by:** golden responses; `/Users/Public` omits `Configuration` and `Policy` and returns
  `[]` for an all-hidden fixture; cross-user reads are `403` for an ordinary user and `200` for an
  administrator. Three criteria are asserted here because here is where a client can see them:
  **AC-8** — a configuration posted and read back over HTTP keeps every property, including ones v1
  does not act on; **AC-2** — an unknown username is `401`, a disabled account is `403`, a missing
  `X-Emby-Authorization` is `400`, and all three carry the reference's 25-byte `text/plain` body,
  compared as bytes; **AC-5** — authenticating twice from one `DeviceId` leaves one
  session and the first token now answers `401`.
- **Note:** `/Users/{userId}` is the project's first parameterised route. 001's route table already
  has the test that says an identifier is data and is not respelled — it is written and passing
  against a router built for it, and this is the task where it stops being hypothetical.
- **Plan reference:** §3

## T12 — `api/sessions.py`

- [ ] **Changes:** `GET /Sessions`, `POST /Sessions/Capabilities/Full`.
- **Depends on:** T8, T10
- **Verified by:** capabilities posted then read back through `/Sessions`; a two-device fixture
  shows two sessions; `SupportsMediaControl` and `SupportsRemoteControl` are `false`, which is
  honest rather than a gap — a client seeing `true` would offer a remote-control UI that does
  nothing.
- **Plan reference:** §3

## T13 — The four mechanisms across route classes

- [ ] **Changes:** `tests/conformance/test_auth_mechanisms.py`, table-driven over mechanism ×
  route class.
- **Depends on:** T11
- **Verified by:** **AC-3** — all four authenticate an API route identically, and the four
  precedence pairs resolve the way T1 measured them. Image and delivery routes use stub routes
  carrying the same dependency until 006 and 008 exist, and the stubs are replaced rather than
  duplicated when they do. The stubs assert that all four are **accepted**, not that a token is
  required: T1 measured that the reference requires none on either class, and asserting otherwise
  would pin a behaviour 006 and 008 have not chosen yet.
- **Note:** supporting only the headers leaves browsing working and every poster and stream broken.
  That failure looks like a client bug, which is why it gets its own test rather than being implied.
  A stub route is served by the application, so it has to stay out of the router that 001's
  "no route exists outside the surface file" check sees — T17 is where that collides if it is going
  to.
- **Plan reference:** §8

## T14 — The log test

- [ ] **Changes:** `tests/security/test_no_password_in_logs.py`.
- **Depends on:** T9
- **Verified by:** authenticate with a known password at `DEBUG`, capture every record from every
  logger, and assert the password appears in none — nor in an exception message, nor a request
  trace, nor a repr.
- **Note:** `DEBUG` is the point. Nobody logs a password at `INFO`.
- **Plan reference:** §8.2, §9

## T15 — The timing test

- [ ] **Changes:** `tests/security/test_login_timing.py`.
- **Depends on:** T9
- **Verified by:** unknown username and known-username-wrong-password produce **overlapping**
  distributions, asserted as a ratio with a generous bound.
- **Note:** a ratio, not milliseconds. A timing test that asserts absolute time fails on a loaded
  runner and teaches everyone to ignore it — which is worse than not having it.
- **Plan reference:** §8.1

## T16 — Migration tests

- [ ] **Changes:** apply and roll back every revision; upgrade from an empty file.
- **Depends on:** T4
- **Verified by:** green both directions. An irreversible migration is allowed but must say so in
  its docstring and say why.
- **Plan reference:** §4, §8.3

## T17 — Surface and golden responses

- [ ] **Changes:** golden files for all seven 002 endpoints; `tests/conformance/test_routes.py`
  extended to cover them — `IMPLEMENTED_FEATURES` gains `"002"`, and the check that names 001's
  four endpoints one by one gains the sibling that names these seven.
- **Depends on:** T11, T12
- **Verified by:** every 002 route in `surface.yaml` is registered and **no route exists outside the
  file**; `tools/extract_v1_surface.py` passes.
- **Note:** `IMPLEMENTED_FEATURES` is one line and it is the whole point of that check: a 002 route
  registered before 002 is implemented is in the surface file already, so nothing else would catch
  it. Changing that line is what declares this feature served.
- **Plan reference:** conformance L0/L1

## T18 — The acceptance map for 002

- [ ] **Changes:** `tests/conformance/test_acceptance.py` extended to a second feature. It is
  written for one today — one specification path, one map — so this is a change of shape, not an
  added dictionary.
- **Depends on:** T13, T14, T15, T16, T17
- **Verified by:** all eleven of [spec §5](spec.md#5-acceptance-criteria)'s criteria name tests that
  exist; a renamed test fails it; a criterion added to the specification and not to the map fails
  it; the 001 map keeps working unchanged.
- **Note:** in 001 this map was written at T18 and it earned itself at T19: renaming one test made
  it fail and **name the criterion left unasserted**, which nobody would have noticed by reading.
  The definition of done below claims eleven criteria have passing tests, and this is the only
  thing that makes that claim checkable.
- **Plan reference:** §8

---

## Definition of done

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing
      test — all eleven, by name, and the mapping is itself a test (T18).
- [ ] Every endpoint reaches the level declared in [`spec.md` §6](spec.md#6-conformance). **L3 for
      `AuthenticateByName` is deferred to 010** and the gap is recorded, not counted as met.
- [ ] OQ-1 and OQ-3 are resolved with provenance, or recorded in [`spec.md` §7](spec.md#7-open-questions)
      as a dated debt saying what was not reachable — never dropped because the code shipped anyway.
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
