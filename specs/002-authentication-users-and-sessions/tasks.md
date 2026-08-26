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

## T2 — `db/`: engine, session factory, Alembic  ✅

- [x] **Changes:** `db/engine.py` with WAL and foreign-key pragmas applied per connection and a
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

### Done — 2026-08-26

**"Refuses when the database is behind" was one row of a table that turned out to have five.** The
task, and [plan §7](plan.md#7-failure-handling), had two states: current, or behind. Writing the
check made the missing ones obvious the moment a first run was considered. **An empty database is
not a pending migration** — answering "run a migration first" to somebody who has just installed
the server is a refusal with no decision behind it, since creating a schema where there was none
cannot lose anything. And **a database from the future is not behind**: downgrading the server
leaves a file a newer build wrote, and treating that as pending runs migrations backwards over data
this build cannot read. Two more rows — tables with no stamp, and a stamp this build has never heard
of — fall out of the same question. The plan now carries all five.

**The check runs in the factory, not in the lifespan, and that reverses what 001 expected.** The
comment 001 left on its lifespan said 002's migrations would go there. They do not: both refusals
have to reach the operator as the sentence [plan §7](plan.md#7-failure-handling) promises, and a
lifespan that raises delivers `Application startup failed` and a traceback instead. The gate keeps
its purpose — 003's scan is slow and belongs there; opening a SQLite file is not.

**The suite caught a leak the server never would have.** `create_app` opens an engine and the
lifespan disposes it, and most tests here deliberately never run a lifespan — so nothing did. A
pooled SQLite connection reaching the garbage collector unclosed emits a `ResourceWarning`, 001's
`filterwarnings = ["error"]` turns that into a failure, and the failure lands in whichever test
happened to be running when the collector got round to it, which is never the test that opened it.
The fix is a fixture that wraps the factory and disposes what it built, in the same spirit as the
network guard beside it: enforced rather than intended. A server would never have shown this,
because a server exits.

**Three pysqlite behaviours were measured before the module was written**, each with a plausible
wrong answer. `PRAGMA journal_mode=WAL` inside the `connect` event takes and reports `wal` back —
it is refused inside a transaction, and a `connect` handler is the one place there is certainly not
one. `foreign_keys=ON` applied there is enforced. And the default pool for a file database hands
connections between threads without a `ProgrammingError`, so SQLAlchemy already passes
`check_same_thread=False`: adding it would have been a spell rather than a decision.

**T2 has no migrations, so the check it adds could not be exercised by anything it ships.** A guard
that cannot fail until the thing it guards exists is a guard nobody knows is broken, so the tests
build a two-revision history in a temporary directory and point the module at it. One of those
revisions reads `PRAGMA foreign_keys` back and refuses if it is off, which is the assertion behind
`upgrade_to_head` reusing the server's engine: Alembic will open its own connection from a URL
given the chance, and that one migrates with foreign keys disabled.

**`db/schema.py` was not in the plan's module list, and `db/models.py` arrived early.** The schema
check is not engine plumbing and not a migration, so it is its own module; the plan's §3 now says
so. `models.py` ships with a `Base` and no tables because the migration environment needs one piece
of metadata to compare against — T4 adds tables rather than also rewiring Alembic.

**The wheel was checked, not assumed.** `env.py`, `script.py.mako` and `versions/` are data files
inside a Python package, and a build backend that skipped them would produce a server that cannot
migrate itself, with nothing in this repository noticing. They are in the wheel.

## T3 — `users/passwords.py`: Argon2id  ✅

- [x] **Changes:** hash, verify, and `needs_rehash`; the self-describing stored format; the dummy
  record generated once at startup; parameters read from configuration.
- **Depends on:** T2
- **Verified by:** a hash round-trips; a wrong password fails; a record written with lower
  parameters verifies **and** reports `needs_rehash`; the stored string parses back to its
  algorithm and parameters. The dummy record is never derived from a real password — asserted.
- **Plan reference:** [ADR-0006](../../docs/decisions/0006-password-hashing.md), §6.2

### Done — 2026-08-26

**The library's `needs_rehash` and the decision's `needs_rehash` are different functions.**
argon2-cffi's `check_needs_rehash` means *different from the current parameters*; ADR-0006 says
*below* them. It reports true for a record made with **stronger** parameters, so delegating to it
would rewrite that record weaker — at the one moment the plaintext exists. An operator who lowered
these settings after moving to a smaller machine would silently downgrade every account on its
owner's next login, and nothing anywhere would say so. Atrium compares memory and time itself.
[plan §6.2](plan.md#62-authentication-and-the-timing-guarantee) records it, and a test asserts the
downgrade does not happen.

**Parallelism is not in that comparison**, which is a decision and not an omission. It divides the
same work across lanes rather than adding any — RFC 9106 sets it from the cores available, and the
cost is carried by memory and time. Rewriting a record because `p` moved would spend the plaintext
moment on a change with no security in it.

**One line would have run the KDF twice on every login, forever.** `extract_parameters` returns the
library's enum, whose member name is `ID` — not `argon2id`, which is what the record says and what
`ALGORITHM` holds. `type.name.lower()` gives `id`, which never equals `argon2id`, so `needs_rehash`
short-circuited to true for **every** record including one written a microsecond earlier. Verifying
still worked perfectly, so the round-trip test passed; what failed was `needs_rehash` against a
record made by the same hasher, which is a test that only exists because the task statement asked
for one.

**The suite lowers the parameters through `config.toml`, which is the mechanism an operator has.**
Measured on this machine: **41 ms** per hash at the shipped parameters against **0.06 ms** at the
test ones, and the factory hashes a dummy record once per server it builds — of which this suite
builds dozens. Patching a default would have been shorter and would not have exercised the setting.
The shipped defaults are written out in `settings.py` rather than inherited from argon2-cffi, and a
test ties them to RFC 9106's low-memory profile: a library default can move under a project without
anybody deciding it should, and these are a security parameter.

**The dummy record carries the policy's own parameters**, which is the part a refactor would
quietly break. A dummy built at different parameters is verified in a different amount of time,
which puts back precisely the signal it exists to remove: how long the refusal took would say
whether the username was real. That is now a test rather than a property somebody remembers.

## T4 — Migration `0001_users_and_sessions`  ✅

- [x] **Changes:** `users` with the **nine honoured policy columns** plus `policy_extra` and
  `configuration` blobs; `user_library_access`; `access_tokens` keyed on `token_sha256`; `sessions`.
- **Depends on:** T2
- **Verified by:** upgrade then downgrade leaves an empty database; upgrade from an empty file
  works, which is the path an operator actually takes; `access_tokens` has **no column holding a
  usable token** — asserted by name and by a value test.
- **Plan reference:** §4

### Done — 2026-08-26

**"Nine honoured policy columns" is one of three counts, and the documents used all three.** The
reference sends **42** policy properties, not "about forty"; v1 honours **eleven** of them; and
those eleven are **nine columns**, because two are lists of libraries and live in the join table.
[spec §3.5](spec.md#35-the-user-object), [plan §1](plan.md#1-approach) and §4 now each say which
number they mean. The 31 in plan §10 was right all along — 42 minus 11 — which is how the intended
counting was recoverable at all. A test pins the nine.

**`LoginAttemptsBeforeLockout` is `-1`, and -1 is not a count.** It is what the reference sends,
so it is what most accounts carry, and [spec §3.3](spec.md#33-post-usersauthenticatebyname--authenticateuserbyname)
reads that field as a threshold. The column stores the reference's own vocabulary and this schema
decides nothing about it; the meaning is now OQ-6, to be measured alongside OQ-5 against the same
throwaway account.

**SQLite drops a timezone and keeps the wall clock.** Measured before the schema was written:
storing `2026-08-26 23:30:00+02:00` yields `'2026-08-26 23:30:00.000000'`, read back naive — so the
instant moves two hours into the future and nothing raises. `DateTime(timezone=True)` changes
nothing on this dialect. Since `compat/dates.py` says naive datetimes have no place in this project
and `utc_now()` returns an aware one, every timestamp column would have carried that error, on
every installation not running in UTC — which is not the one this was written on. `db/types.py`
converts on the way in, restores on the way out, and **refuses a naive value** rather than guessing
which zone somebody meant.

**Alembic generated a migration that would have failed on the first operator who ran it.** It
renders a user-defined column type with its module path — `atrium.db.types.UtcDateTime()` — and
imports nothing: `autogenerate/render.py` calls `imports.add` only for types from
`sqlalchemy.dialects`. Autogenerate reports success and the file is a `NameError` waiting to
happen. `env.py` now carries a `render_item` hook that registers the import for any type from this
project, so the next custom type does not repeat it, and the template's import order is the one
ruff wants so a generated migration passes lint unedited.

**A foreign-key column does not tell the ORM the insert order.** Creating a user and its first
token in one flush inserted the token first, and the database rejected it — which it only did
because T2 turned the foreign-key pragma on. Without that pragma the row would have gone in with a
dangling reference and nothing would have said so. The tables now declare relationships, which is
what the unit of work sorts by; they are `passive_deletes=True` so the cascade stays in the
database where the migration declares it, and `lazy="raise"` so an accidental lazy load past the
repository boundary is an error rather than a surprise query.

**T2's "no revisions yet" test failed, which is what it was for.** It asserted that a build with no
migrations leaves an unstamped database — true, and true only until this task. It failed the moment
`0001` landed and named the day the assumption expired, instead of sitting there passing against a
state that no longer existed.

**The strongest test here reads the database file as bytes.** "No column holds a usable token" can
be asserted from column names, and that only proves nobody called a column `token`. So a real token
is written through the code that stores one, and the assertion is that the plaintext appears
nowhere in `atrium.db` **or its write-ahead log** — while the hash does, so a test that stored
nothing cannot pass by accident.

## T5 — `db/repositories.py`: the boundary  ✅

- [x] **Changes:** user, token and session repositories returning **domain objects**, never ORM
  rows; token hashing happens here, so no caller can store a plaintext token.
- **Depends on:** T4
- **Verified by:** a test asserting no SQLAlchemy type escapes the module's public functions;
  storing a token and reading it back never yields the original string.
- **Plan reference:** §3, architecture §1

### Done — 2026-08-26

**"No caller can store a plaintext token" is a shape, not a rule.** There is no method that accepts
a token to store. `issue` generates the secret, writes only its SHA-256, and hands the plaintext
back once in an `IssuedToken` whose `repr` omits it — so a caller never holds a token this module
has not already reduced to a hash, and there is nothing for a future caller to forget. The same
reasoning put `password_hash` out of `User`'s `repr`: a domain object reaches a log line
eventually, and it gets there because somebody wrote `logger.debug("%s", user)` rather than because
they meant to.

**The sweep found two things about itself before it found anything about the code.** A module's
*imported* names are part of its surface: walking `repositories` picked up `select` and `delete`,
and the sweep then failed on SQLAlchemy's own annotations rather than on anything this project
wrote. And on Python 3.14 `typing.Union` **is a class**, so `isinstance(origin, type)` no longer
separates a container from a special form, and every `X | None` in the module failed for coming
from `typing`. Both are now handled, and the sweep carries the test that proves it still rejects a
method returning a row — a sweep that cannot fail is decoration.

**Names normalise with `casefold`, not `lower`.** A German account named `STRASSE` and one named
`Straße` are the same login; `lower` leaves them as two accounts, one of which cannot be reached,
and the unique index would not stop it because the two normalised forms differ. This is the sort of
thing that is free to get right here and expensive to notice later.

**Every dictionary that leaves is a copy.** `policy_extra` and `configuration` come out of the
identity map, so handing the row's own dict to a caller would let a route edit the session's idea
of what is in the database. Asserted, because it is invisible until it is not.

## T6 — `users/policy.py`: enforced versus echoed  ✅

- [x] **Changes:** assembling a policy object from nine columns plus the blob, and splitting it back
  on write.
- **Depends on:** T5
- **Verified by:** the shape AC-8 asks of configuration, applied to policy — a policy containing
  properties v1 has never heard of round-trips byte-identically; the nine honoured flags land in
  columns and are queryable; a property moved from blob to column in a later migration is not lost.
  **AC-8 itself is asserted over HTTP in T11**, because Principle VIII does not accept a criterion
  proven against the function behind the route.
- **Plan reference:** §6.4

### Done — 2026-08-26

**"Byte-identically" is the wrong requirement, and asking for it would have produced a delta.**
This task asked that a policy round-trip byte-identically. It cannot, and it should not: assembling
a document from nine columns, two lists and a blob emits *this server's* key order, and the
reference emits *its own* — a C# object serialises its properties in a fixed order whatever a
client sent. Echoing a client's ordering would be the difference from the reference rather than
fidelity to it. What round-trips is the **set of properties and their values**, which is now what
the test asserts and what [plan §6.4](plan.md#64-policy-enforced-versus-echoed) says.

**An honoured property must never live in the blob, and that is what makes the promotion
lossless.** The task asked that a property moved from blob to column in a later migration not be
lost; the sharper question is which of the two wins while both exist. The column does: splitting
strips the eleven before storing the rest, assembling reads each from its column, and a stale copy
left behind by a pre-migration write is ignored rather than shadowing it — otherwise the flag a
server *enforces* and the flag it *reports* would come from two different places. One write through
`split` removes the stale copy, with no migration of its own.

**The refusal of a wrong-typed value is not defensive programming, it is SQLite.** A string in a
boolean column is stored as a string and comes back as one, and the flag is then true for every
value except the empty string. `split` refuses rather than letting the storage layer decide what
somebody meant, and `True` is refused for an integer column for the same reason — in Python a bool
*is* an int, so `MaxActiveSessions: true` would silently become 1.

**The test document is the reference's, not an invention.** All 42 property names, measured
`[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`. A round-trip over three properties would
have proven the mechanism and nothing about the shape a client posts, and the eleven/nine/31 counts
are asserted against it rather than restated.

T6 also added the half of the repository it needed: `library_access` and `set_library_access`,
which turn the two honoured list properties into join-table rows and back. Replacing rather than
merging, because a library absent from `EnabledFolders` is a library the user may not see.

## T7 — `compat/auth.py`: extraction and parsing  ✅

- [x] **Changes:** `extract_token` over the four mechanisms in a fixed order; `parse_client_authorization`
  for `X-Emby-Authorization`, lenient about order, whitespace, quoting and unknown components.
- **Depends on:** 001 complete
- **Verified by:** a table over the four mechanisms including a request carrying **two**, which
  resolves deterministically; a parser table with reordered, unquoted, whitespace-padded and
  extra-component headers; a header missing `DeviceId` is the one fatal case.
- **Note:** pure functions over a request. No I/O, so the whole table runs without a server.
- **Plan reference:** §5, §6.1, §6.3

### Done — 2026-08-26

**There is a fifth mechanism, and the specification had four.** `X-Emby-Authorization` carrying a
`Token=` component authenticates: the reference reads that header and `Authorization` with the same
grammar. It is the **historical Emby form**, which a great many clients send, so a server built to
this specification would have refused clients that have worked against the reference for years —
the worst class of finding this project can produce, and it took one request to find.

**Three of the four claims in [plan §6.3](plan.md#63-the-x-emby-authorization-grammar) were wrong.**
The `MediaBrowser` prefix is not "optional in practice": it is required, and it may be
`MediaBrowser` or `Emby`, case-insensitively — `Bearer`, anything else, or nothing at all reads as
an empty header. Whitespace around the `=` is **refused**, which is the one leniency both documents
claimed. Component names are case-sensitive while the scheme is not. And a missing `DeviceId` is
fatal on **one route**, not in the parser: an ordinary authenticated route answers `200` without
it, so a parser that raised — as the plan described — would have refused requests the reference
serves.

**Atrium refuses the two forms the reference refuses, and that is a decision.** Accepting
`Token = x` costs nothing today, because no working client can be sending it. What it costs is
later: somebody builds a client against Atrium and it fails against Jellyfin. That is the direction
of delta that matters, and it is now in
[behaviours §6](../../docs/compatibility/behaviours.md#6-non-improvements) so it stops being
re-proposed.

**The precedence chain is complete and measured**, pair by pair and in both directions each time:
`Authorization` > `X-Emby-Authorization` > `X-Emby-Token` > query. Only two rungs of it were known
before this task, and the new mechanism landed in the **middle** rather than at either end — which
is exactly where a guess would not have put it.

**The third error shape got its implementation.** `compat/errors.py` documented two shapes and T1
measured a third; the module still said "two". It now carries `ClientAuthorizationError` and the
`text/plain` refusal with the reference's fixed 25-byte sentence, so T11's route has nothing left
to invent.

The tests are two tables, and each row carries the status the reference answered. A change that
made this parser kinder than the reference fails there rather than in somebody's client.

## T8 — `users/sessions.py`: the registry  ✅

- [x] **Changes:** `SessionRegistry` with in-memory activity, a 30-second flush, flush on clean
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

### Done — 2026-08-26

**"No window in which both work" needed a seam to be testable at all.** Asserting it *after* the
fact proves nothing: two statements in two transactions look identical from outside once both have
finished, and the window they leave only appears under load in somebody else's logs. So the work
lives in `establish_in`, which runs inside a transaction the caller owns, and the test opens a
**second connection while the first is still open** — the old token works and the new one does not
exist, then the swap commits and it is the other way round. There is no third state to observe.

**Eviction has to take the tokens with it, and that is a decision rather than a reading.** A
session removed from `/Sessions` whose token still worked would reappear on that device's next
request — a gap in a list, not an eviction. The reference's behaviour here is not measured;
[plan §6.6](plan.md#66-session-lifecycle) now records that the two halves must agree, because a
server whose session list and whose credentials disagree is answering two different questions about
the same device.

**A flush takes its entries before writing them, not after.** Clearing afterwards would erase a
`touch` that arrived mid-flush — a lost timestamp for the busiest sessions, which are exactly the
ones whose timestamps matter. And a flush that fails puts its entries back rather than dropping
them, so a database that is briefly unavailable costs a delay instead of a gap. Both are tests.

**`/Sessions` has to read through the registry.** Reporting the flushed value would tell a client
that the session it is using right now was last active half a minute ago. `activity()` exists for
T12 to overlay, and the plan says so.

**The clean-shutdown flush is separate from the crash bound.** Losing thirty seconds to a crash is
the cost this design accepts; losing them to an orderly stop is just not writing something there
was every opportunity to write. The lifespan cancels the background task, awaits it, and flushes —
and swallows a database error there rather than turning a shutdown into a traceback.

The bound itself is now a test rather than a sentence: after a simulated crash the session row, its
token and every user record are intact, and only the timestamp is stale.

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

## T13 — The five mechanisms across route classes

- [ ] **Changes:** `tests/conformance/test_auth_mechanisms.py`, table-driven over mechanism ×
  route class.
- **Depends on:** T11
- **Verified by:** **AC-3** — all **five** authenticate an API route identically (T7 measured the
  fifth, `X-Emby-Authorization` carrying a token), and the precedence chain resolves the way T1 and
  T7 measured it. Image and delivery routes use stub routes
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
