---
feature: 001-server-identity-and-discovery
title: Server identity and discovery — tasks
status: Draft
created: 2026-08-26
updated: 2026-08-26
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 001 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**These are the first lines of code in the project**, so the early tasks carry more scaffolding
than their size suggests — and the two sweeps land before the first response model, deliberately.
A sweep added afterwards checks what already exists; a sweep added first makes the wrong thing
impossible to write.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

Every command below is run through `uv`, per
[ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md).

---

## T1 — Project skeleton  ✅

- [x] **Changes:** `pyproject.toml` (name, `requires-python = ">=3.12"`, `license = "GPL-3.0-or-later"`, dependencies, ruff/mypy/pytest configuration), `src/atrium/__init__.py` carrying `__version__`, empty package directories per [plan §3](plan.md#3-modules), `tests/` root.
- **Depends on:** —
- **Verified by:** `uv sync` resolves; `uv run ruff check .` and `uv run mypy src` pass on an empty tree; `uv run pytest` exits 0 collecting nothing.
- **Also:** every file carries `# SPDX-License-Identifier: GPL-3.0-or-later` from this commit, not retrofitted ([ADR-0005](../../docs/decisions/0005-licence.md)).
- **Plan reference:** §2, §3

### Done — 2026-08-26

Three notes, because each is a decision the task statement did not settle.

**The console entry point is deferred to T15.** `pyproject.toml` was to declare
`atrium = "atrium.server:main"`, and `server.py` is T15's. Declaring an entry point to a module
that does not exist fails the build, and a broken one is worse than none.

**Dependencies are 001's only** — `fastapi` and `uvicorn`. SQLAlchemy, Alembic and `argon2-cffi`
are decided but unused until 002 and 003, and a dependency set that lists what the roadmap intends
rather than what the code imports stops being reviewable. Each feature adds its own.

**The security lint rules went in now.** `flake8-bandit` (`S`) was enabled at the skeleton because
its noise on the existing tree was **three findings**, all in `tools/`, all explicable in a line.
Enabled later it would have been a backlog. The two `S105` hits are variable *names*
(`ENV_PASSWORD = "JELLYFIN_PASSWORD"`); the `S310` is an operator-supplied URL, which is the
probes' entire purpose.

**The linter earned its place on the first run.** `RUF034` caught a real defect in
`probe_sort_names.py` — `"IndexNumber" if item_type != "Season" else "IndexNumber"`, a ternary
whose branches were identical. The surrounding logic was right, so the probe's published findings
stand, but the dead condition would have misled the next reader about what varies by type.

**Markdown is excluded from the formatter.** `ruff format .` reformatted the fenced Python blocks
inside `plan.md` on its first run — silently rewriting reviewed prose, where the aligned comment
columns are a deliberate readability choice rather than un-formatted code. `extend-exclude`
keeps the formatter about code. A tool that edits documentation as a side effect of a lint task is
a tool nobody will trust to run unattended.

## T2 — `compat/model.py`: the base every response inherits  ✅

- [x] **Changes:** `AtriumModel` with the alias generator, `populate_by_name`, `extra="ignore"`; `compat/aliases.py` with the five-entry irregular table and `atrium_alias()`.
- **Depends on:** T1
- **Verified by:** a unit test where a model with fields `local_address` and `is_hd` serialises to `LocalAddress` and `IsHD`, and accepts **both** spellings on input.
- **Plan reference:** §5, §6.1

### Done — 2026-08-26

**The plan's justification for `populate_by_name` did not hold, and the gap was real.**
[plan §5](plan.md#5-contracts) annotated it *"the reference's binder is case-insensitive on
input"* — but `populate_by_name` accepts exactly two spellings, the field name and the alias. The
reference is an ASP.NET Core application whose JSON binder matches **case-insensitively**, so a
client posting `{"username": …}` where the property is declared `Username` is served by the
reference and would have been rejected here.

`AtriumModel` therefore carries a `mode="before"` validator that remaps keys case-insensitively.
The fast path is untouched: the lookup is only built when a key does not already match something
the model knows, which for a well-behaved client is never.

**`serialize_by_alias=True` was added beyond the plan's snippet.** Without it `model_dump()` is
correct only when the caller remembers `by_alias=True`, and the one place someone forgets is the
one place a client sees snake_case. FastAPI passes `by_alias` on its own; nothing else does.

## T3 — The property-name index and the alias sweep  ✅

- [x] **Changes:** `tools/extract_property_names.py` producing `docs/compatibility/property-names.json` from the pinned OpenAPI document; the index itself, committed; `tests/conformance/test_aliases.py` walking every `AtriumModel` subclass and asserting each alias appears in the index.
- **Depends on:** T2
- **Verified by:** the sweep passes; renaming a field so its alias becomes `IsHd` makes it **fail**, naming the model, the field, the alias produced and the nearest real name. `uv run pytest tests/conformance/test_aliases.py` needs no network and no `reference/` directory.
- **Note:** the flat check first — is this alias *any* name the reference uses. Per-schema strictness follows the models, per [plan §8.3](plan.md#83-the-two-cross-cutting-sweeps).
- **Plan reference:** §6.1, §8.3

### Done — 2026-08-26

`docs/compatibility/property-names.json` holds **1043 names, 21 KB**, extracted from the pinned
10.11.10 document. `--check` regenerates and diffs, naming what appeared and what vanished.

**The sweep passes vacuously today, because no models exist yet** — which is exactly the state in
which a sweep is worth nothing. So four tests assert that it *fails* on the mistakes it was written
for, rather than passing because nothing has been built:

```
Broken.is_hd       serialises as 'IsHd' … Did you mean 'IsHD'?
Broken.server_nane serialises as 'ServerNane' … Did you mean 'ServerName'?
```

A generated acronym, an invented field, a typo — each rejected, each naming the real spelling,
because a bare rejection sends the reader hunting. A fourth test asserts every entry in `IRREGULAR`
is load-bearing: the generator gets it wrong **and** the replacement is a name the reference really
has, so a stale entry cannot sit there unnoticed.

**`compat/registry.py` walks the model registry, not the router**, so a model is checked whether or
not a route returns it yet.

## T4 — `compat/dates.py`: .NET round-trip datetimes  ✅

- [x] **Changes:** the datetime type: serialises `%Y-%m-%dT%H:%M:%S.ffffff0Z` after normalising to UTC; parses any ISO-8601, three or seven fractional digits, timezone optional and read as UTC when absent.
- **Depends on:** T2
- **Verified by:** table-driven round-trip tests including a zero fraction (`.0000000Z`), a non-UTC input, a naive input, and a seven-digit input. The seventh digit is always `0` and a test says so, so nobody later "fixes" it.
- **Plan reference:** §6.2

### Done — 2026-08-26

**No normaliser was needed.** The plan allowed for one, on the assumption that `fromisoformat`
would reject seven fractional digits. Measured on the **3.12 floor** rather than on the interpreter
that happens to be installed: it accepts seven digits, nine digits, a bare `Z`, an offset and no
timezone at all, truncating to microseconds. Fifteen lines of defensive string surgery that the
plan reserved space for do not exist.

**Formatting is built from components, not `strftime`.** `%Y` does not zero-pad years below 1000
consistently across platforms, and a date field is not the place to inherit a platform difference.
A test asserts `0001-02-03`.

**`when_used="json"` rather than `"always"`.** JSON is what reaches a client and must be exact; a
Python-mode dump keeps a real `datetime` so callers can compute with it. Both halves are asserted.

**The last test records what the sweep is for.** A field annotated plain `datetime` serialises in
pydantic's own format — `+00:00`, six digits — and the test asserts that it does *not* match the
reference. T7 is what will catch such a field; this says out loud what it is catching.

**Two lint findings worth the distinction.** `UP017` applies to `src/` — 3.12 has `datetime.UTC` —
but not to `tools/`, which keeps `timezone.utc` for its 3.9 floor and is exempted by path. And
`DTZ001` fired on two *deliberate* naive datetimes in the tests: the naive value is the case under
test, so each carries a `noqa` saying so rather than being "fixed" into meaninglessness.

## T5 — `compat/ticks.py`: the internal duration unit  ✅

- [x] **Changes:** the `Ticks` type and conversions to and from seconds and milliseconds, rounding rather than truncating.
- **Depends on:** T2
- **Verified by:** conversion tests including a value that truncation would get wrong; a test that a `Ticks` field serialises as a JSON integer, never a float or string.
- **Plan reference:** §6.3, architecture §4

### Done — 2026-08-26

**Conversion goes through `Decimal`, because the obvious version is wrong.** Measured rather than
assumed:

```
float("1234.5678901") * 10_000_000  ->  12345678901.000002
```

`from_seconds` also accepts a **string** first-class, because that is how `ffprobe` reports a
duration — turning it into a float on the way past would discard the precision the function exists
to keep. A float argument is converted via `str`, so it does not inherit the float's own binary
error either.

**Rounding is half away from zero, not Python's.** `round(0.5)` is `0` — banker's rounding, a
defensible rule and not the one a reader assumes. Determinism means the rule is stated and tested,
not inherited (Principle VII), so a test asserts both that `round()` behaves that way and that this
module does not.

**A float where ticks are expected is refused, with the reason.** This is the mistake the module
exists to prevent: a caller holding `5763.999` has seconds, and silently taking the whole part
would be wrong by a factor of ten million — a bug that looks like a wildly incorrect duration
rather than like a type error. `5764.0` is refused too, since it is the same mistake wearing a
rounder number.

**`from_timedelta` goes via the integer components, not `total_seconds()`**, which is a float and
loses precision on long durations. A test uses 400 days plus one microsecond. And `to_timedelta`
truncates the last tick digit, because a `timedelta` resolves to the microsecond — asserted, so it
is a documented cost rather than a surprise.

## T6 — `compat/guids.py`: identifiers  ✅

- [x] **Changes:** `Guid32` validated against `^[0-9a-f]{32}$`; generation from `secrets.token_hex(16)`; the deterministic derivation helper 003 will use.
- **Depends on:** T2
- **Verified by:** rejection tests for uppercase, dashes, wrong length; the derivation helper returns the same value for the same key across processes.
- **Plan reference:** §6.3

### Done — 2026-08-26

**The task said "rejection tests for uppercase, dashes" and the reference accepts both.** Checked
before implementing: routes bind .NET `Guid` parameters, which `Guid.TryParse` reads in the dashed
form, the braced form and any casing, while output is always `ToString("N")`.
`[source: Jellyfin.Api/Controllers/ItemsController.cs:974,
Jellyfin.Api/Helpers/MediaInfoHelper.cs:142 @ v10.11.11]`

Rejecting a dashed identifier would break a client that stored one and sent it back — so the type
is **lenient on the way in and canonical on the way out**. What is rejected is what is not an
identifier at all: wrong length, non-hexadecimal, empty. The task's wording was written from the
output side; the input side needed measuring.

**The rejection message says what an identifier looks like.** A pattern constraint would produce
`String should match pattern '\A[0-9a-f]{32}\Z'`, which tells a reader what was wanted only if
they can read a regular expression under time pressure. A test asserts the message contains
`32 hexadecimal`, so a later refactor to a bare constraint fails.

**Determinism across processes is tested in a subprocess**, not asserted twice in one. The failure
mode it protects against — an identifier depending on per-process state such as hash randomisation
— is invisible to a same-process comparison, so a same-process assertion would pass while the
guarantee was broken.

**Parts are NUL-joined**, so `("a", "bc")` and `("ab", "c")` cannot collide. Tested, along with the
two separations 003 depends on: the same path as two item types is two identifiers, and the same
path in two libraries is two identifiers.

## T7 — The unit sweep  ✅

- [x] **Changes:** `tests/conformance/test_units.py` — every field whose name ends in `Ticks` serialises as an integer; every field whose name ends in `Date` serialises with seven fractional digits and a `Z`.
- **Depends on:** T4, T5
- **Verified by:** passes; a deliberately float-typed `*Ticks` field fails it.
- **Plan reference:** §8.3

### Done — 2026-08-26

**Two of the task's own assumptions were wrong, and the sweep found them while being written.**

*"A deliberately float-typed `*Ticks` field fails it."* A plain `int` field **already rejects**
`5763.999`, because a fractional float is not an integer — so the obvious probe reports that `int`
is safe. It is not: `int` accepts `5764.0`, the same caller with the same mistake and a rounder
number. The probe uses a whole float, and the test says why.

*"Every field whose name ends in `Date`."* The reference uses both spellings — `PremiereDate` and
`DateCreated` — and `endswith` alone covers 13 of the 20 date fields in the pinned document. The
rule is now start-or-end, and it stops there: "contains" would gain one real field and three false
positives, since `ReleaseDateFormat` is an enum and `UseFileCreationTimeForDateAdded` is a boolean.
Two tests assert those two are **not** flagged, because a sweep with false positives gets switched
off within a week — which costs more than the field it would have caught.

**Checked by behaviour, not by structure.** Each field is rebuilt into a single-field probe model
and actually serialised, so the sweep tests what a client would receive. Inspecting metadata for a
`PlainSerializer` would pass a field that carried the annotation and the wrong serialiser.

**The type rule is primary and the name rule secondary.** Any `datetime`-mentioning annotation must
serialise in the reference's format, nullable unions included — which is most date fields upstream.

Both halves of `compat/` now have a sweep. The plan's wording for both was refined by measuring
rather than by reasoning, which is the same method the probes used on the reference.

## T8 — `config/`: paths and operator configuration  ✅

- [x] **Changes:** `config/paths.py` with the data-directory layout; `config/settings.py` loading `config.toml` with defaults for `server_name`, bind address and port, `published_url`, `use_request_host`.
- **Depends on:** T1
- **Verified by:** missing file → defaults plus one log line; malformed file → **refuses to start**, naming file, line and key; unwritable data directory → refuses to start. Each is a test, because each is a failure mode an operator will actually hit.
- **Plan reference:** §4, §7

### Done — 2026-08-26

**`extra="forbid"` does more work here than the validation it looks like.** A typo in a key —
`use_request_hosts` for `use_request_host` — would otherwise be accepted and ignored. The operator's
setting does nothing, the server looks healthy, and the only symptom is a wrong address in a
response nobody thinks to read. That is a support ticket nobody can diagnose, and it is now a
startup refusal naming the key. Tested at both levels of the file.

**Writability is proven by writing, not by reading permission bits.** Bits are one of the ways a
directory can be unwritable; the others — a read-only mount, a full disk, a container's user
mapping — are the ones an operator actually hits and a bit-check misses. `prepare()` writes a probe
file and removes it, and a test asserts nothing is left behind.

**The refusal message says what is at stake**, not just what failed: without somewhere to keep
state, the server would generate a new identity on every run and every client would re-authenticate
every time. An operator who reads "not writable" may shrug; one who reads the consequence will not.

**`data_dir` cannot come from the config file**, since the file lives inside it. Command line, then
`ATRIUM_DATA_DIR`, then `$XDG_DATA_HOME/atrium`. The precedence is tested rather than described.

**The default port is 8096**, the reference's. Not a protocol requirement — but following the
convention costs nothing and saves every client a manual step. Running both on one host means
changing one of them, which is the operator's business and is what `config.toml` is for.

Two small correctness notes. `Settings` is a plain `BaseModel` and deliberately **not** an
`AtriumModel`: it is not a wire type, and inheriting would PascalCase an operator's TOML keys and
put it in front of the conformance sweeps. And the permission test's skip conditions avoid
referencing `os.geteuid` directly, because `skipif` expressions are evaluated at collection time on
every platform and it does not exist on Windows.

## T9 — `config/state.py`: server identity  ✅

- [x] **Changes:** `state.json` read and write; atomic write (temp file, `fsync`, `os.replace`); identity generated once on first start.
- **Depends on:** T6, T8
- **Verified by:** **the AC-4 test** — start and record the id; restart, unchanged; delete everything *except* `state.json`, restart, unchanged. Plus: a corrupt `state.json` refuses to start rather than regenerating, and a write interrupted before `os.replace` leaves the previous file intact.
- **Note:** the third phase passes trivially today because there is no store. That is exactly why it must exist before there is one.
- **Plan reference:** §4, §7, §8.1

### Done — 2026-08-26

**The AC-4 third phase does pass trivially, and the test says so in its own docstring** — including
what it is for: 002 introduces a database, and the moment someone moves the identity into it for
tidiness, this test is what says no. Simulated to confirm it would actually catch that: an identity
kept in a rebuildable store changes across a rebuild, which is the failure the test exists to name.
A test written afterwards would have been written to fit whatever the code had already done.

**Three refusal messages say what is at stake, not just what failed.** A corrupt `state.json` does
not regenerate — the message explains that generating a new identity would make every client treat
this as a different server and re-authenticate, and offers the two real options (restore a backup,
or delete the file to accept that cost). A test asserts both halves are in the message, so a later
"simplification" of the wording fails.

**A corrupt file is left alone.** Refusing to start must not also destroy the evidence a backup
could be compared against.

**`extra="allow"`, deliberately.** A newer Atrium may write keys this version does not know, and a
downgrade hands them back untouched. Dropping them is a data-loss bug that surfaces only after
someone has already downgraded to escape a different problem — the worst possible moment to lose
something. Tested by round-tripping an unknown key.

**Two things the linter improved.** `server_id` started as a bare `str` with a pattern, which
pydantic rejected outright — its regex engine is Rust's and does not accept `\A`/`\Z`. The fix was
not a different anchor but reusing `WireGuid`: one definition of what an identifier is, carrying the
error message that says so in words rather than in a regex. And `PTH105` moved the rename from
`os.replace` to `Path.replace`, which the atomicity tests now patch instead.

**Durability is not only the file.** After the rename, the containing directory is `fsync`ed on
POSIX — without that, a power loss can leave the rename unrecorded even though the data was synced.

## T10 — `lifecycle.py` and the readiness gate  ✅

- [x] **Changes:** `Readiness`; middleware answering `503` with `Retry-After` while not ready.
- **Depends on:** T1
- **Verified by:** a request during startup gets `503` with the header; after readiness the same request is served.
- **Plan reference:** §5, §7

### Done — 2026-08-26

**Checking the contract before implementing it answered an open question and corrected the spec.**
The pinned document declares a `503` on **all 395 operations** — so the gate is server-wide rather
than an error path of one endpoint — and the response carries **two** headers, `Retry-After` and
`Message`, with a **`text/html`** body. `spec.md` said "`503` with a `Retry-After` header"; it now
has a §3.5, and OQ-2 moves to Resolved. `[spec: every operation's 503 response in the pinned 10.11.10 document]`

A new OQ-4 replaces it, narrower and honest: the document *declares* both headers, and only a probe
catching a server mid-start would confirm a running one *sends* them.

**A raw ASGI middleware, not `BaseHTTPMiddleware`.** Starlette's wraps every response in a
queue-backed stream. That is harmless for JSON and wrong for the byte-range and HLS delivery
feature 008 adds — choosing the convenient one here would put a buffer in front of every media
stream this server ever serves, and by then the reason would be untraceable. The docstring says so,
because the next person to touch this file will not have 008 in mind.

**`Readiness` is an object, not a module-level flag**, so two instances in one process do not share
it. A test asserts that, because the failure it prevents is a test leaking into the next one.

**`mark_unavailable` came for free and is worth having**: the same response withdraws the server
from service during a long rebuild, with its own message and hint, without stopping the process.

## T11 — `compat/middleware.py`: the `Server` header  ✅

- [x] **Changes:** middleware setting `Server: Atrium/{__version__}` on every response.
- **Depends on:** T1
- **Verified by:** the header is present and carries **Atrium's** version, not the reference's — asserted against both constants so a future edit cannot silently swap them.
- **Plan reference:** §6.5

### Done — 2026-08-26

**One real request turned a one-header task into a three-header one.** Before writing a `Server`
header it was worth knowing what the reference sends, so a request went to a live 10.11.11:

```
Server              'Kestrel'
X-Response-Time-ms  '2.1329'
Content-Type        'application/json; charset=utf-8'
```

Two of those three were unknown to this project, and **neither specification mentioned either**.

**`X-Response-Time-ms` is the reference's, on every response.** Confirmed in its source rather than
assumed from one observation: the middleware is registered unconditionally, and the configuration
flags beside it gate a slow-response log line rather than the header. `[source: Jellyfin.Api/Middleware/ResponseTimeMiddleware.cs:17, Jellyfin.Server/Startup.cs:163 @ v10.11.11]` Omitting it would be a
difference on every response in the project — 55 rows of noise in the first differential run — for
fifteen lines of middleware. Now [behaviours §1.9](../../docs/compatibility/behaviours.md).

**JSON carries `charset=utf-8`.** Starlette appends it only to `text/*`, so its `JSONResponse`
sends a bare `application/json`. Fixed through a response class rather than a middleware, so the
content type belongs to the thing that produced the body. This added `compat/responses.py`, which
[plan §3](plan.md#3-modules) did not list; T15 wires it as the default response class. Now
[behaviours §1.10](../../docs/compatibility/behaviours.md).

**And the `Server` header itself is now a measured divergence rather than a hypothetical one.** The
reference sends `Kestrel`. A client cannot usefully branch on that — it identifies a .NET web
server, not Jellyfin — so this stays the one header where the honest answer costs nothing.
[behaviours §4.1](../../docs/compatibility/behaviours.md) records it with the measurement.

**One observation was deliberately not recorded.** The same response carried
`Transfer-Encoding: chunked` and `Connection: close`, which would mean the reference sends no
`Content-Length` on JSON. That server may sit behind a reverse proxy, and attributing a
proxy's framing to the reference would put a false claim in the compatibility documents. It needs
isolating before it can be written down.

## T12 — `net/address.py`: `LocalAddress`  ✅

- [x] **Changes:** `resolve_local_address(request, settings)`, three tiers, first match wins; loopback fallback.
- **Depends on:** T8
- **Verified by:** the nine-row table of [plan §8.2](plan.md#82-localaddress) — published URL with and without a trailing slash; request-host mode on default and non-default ports, http and https; two requesters on different networks; a requester matching nothing. No test touches a real interface.
- **Note:** the reference's HTTPS override is **not** implemented ([behaviours §4.2](../../docs/compatibility/behaviours.md#42-localaddress-does-not-get-an-https-override)). A test asserts the scheme follows what the server is reachable on, so the divergence is deliberate in code as well as in prose.
- **Plan reference:** §6.4

### Done — 2026-08-26

**Tier 3 asks the operating system instead of enumerating interfaces.** The plan said "enumerate
the server's bound addresses, pick the one on the same network as the requester". Doing that
properly needs netmasks, which the standard library does not expose — the honest options were a
dependency or a heuristic.

Neither was necessary. Opening a UDP socket towards the peer and reading back the local address the
kernel chose sends no packets, needs no arithmetic, and is **more** correct than matching prefixes
by hand: it honours the real routing table. Checked against five peers before committing to it,
including loopback and a VPN-shaped range.

That also makes the behaviour the reference is *praised* for in
[behaviours §2.3](../../docs/compatibility/behaviours.md) — a requester arriving over a VPN getting
the VPN-side address — fall out for free, because it is the kernel's answer rather than ours.

**The divergence is now structural, not documentary.** Two tests: one asserts a request arriving as
HTTPS does not produce an `https://` answer in tier 3, and the other is a **tripwire** —
`NetworkSettings` has no field whose name could reach the scheme. When TLS support lands, that test
fails and forces the decision to be made deliberately rather than inherited. A divergence that only
lives in a document is one refactor away from disappearing.

**Tier 1 keeps a path.** A reverse proxy may serve Atrium under a sub-path, and `rstrip("/")` on a
published URL must not become "take the origin". Tested.

**The loopback fallback is never an empty string.** A client receiving `""` has no way to recover;
one receiving a wrong-but-well-formed address fails visibly.

The function takes the request's parts rather than a `Request`, so the table runs without a server
and without touching a real interface. T14 supplies the adapter that pulls those parts out.

## T13 — `api/deps.py`: the authentication seam  ✅

- [x] **Changes:** `require_user()` with the signature 002 will keep, raising `401` unconditionally.
- **Depends on:** T1
- **Verified by:** a route depending on it answers `401`; a test overriding it through `app.dependency_overrides` reaches the route body.
- **Note:** no credential of any kind ships. The `200` path is exercised by the override, per [plan §1](plan.md#1-approach).
- **Plan reference:** §1, §5

### Done — 2026-08-26

**Asking what a refusal looks like before writing one found two shapes, not one.** FastAPI's
`HTTPException` sends `{"detail": "Not authenticated"}` as JSON. The reference sends **nothing** —
status line, `Content-Length: 0`, no `Content-Type`, no `WWW-Authenticate`. That would have been a
difference on every gated route in the project.

And the split turned out to be structural rather than per-endpoint: refusals decided **before** the
controller pipeline are empty, while errors the pipeline produced carry **RFC 9457 problem
details** with a `traceId`. Four cases measured, now [behaviours §1.11](../../docs/compatibility/behaviours.md).
Only the empty shape is implemented, because only it is reachable in 001; the JSON shape belongs to
the features that raise it and is written down so it does not have to be rediscovered.

**The absent `WWW-Authenticate` is kept absent deliberately.** RFC 7235 says a 401 SHOULD carry
one; adding `Basic` would make a browser open a credentials dialog on routes no browser was meant
to drive. Matching the reference is the safer behaviour here, which is a pleasant change.

**A fifth measurement, unasked for, confirmed a decision already taken.**
`/Genres?SortBy=NotASortOption` answers `200` with a full result — the reference **ignores** an
unrecognised query value rather than rejecting it. [005 §3.3](../005-item-query-api/spec.md)
argued for exactly that behaviour from first principles; this is the evidence.
[behaviours §1.12](../../docs/compatibility/behaviours.md).

**Two modules the plan did not list.** `compat/errors.py`, because the wire shape of an error
belongs beside the wire shape of everything else; and `domain/user.py`, because a seam needs a
return type and 002 needs somewhere to grow one. A test asserts the signature — return type and
parameters — so 002 changing it is a finding for this plan rather than a quiet edit.

**One thing left unmeasured on purpose.** `/Items/<32 zeros>` answers `200`, not `404`: .NET treats
an all-zero GUID as a special value. Interesting for [005 §3.5](../005-item-query-api/spec.md), and
not chased here — it needs isolating before it can be claimed.

## T14 — `api/system.py`: the three routes  ✅

- [x] **Changes:** the `PublicSystemInfo` and `SystemInfo` models; `GET /System/Info/Public`, `GET /System/Info`, `GET` and `POST /System/Ping`.
- **Depends on:** T3, T9, T12, T13
- **Verified by:** each route answers; `/System/Ping` returns the JSON string `"Jellyfin Server"` — the **product** name, not the operator's server name ([spec §3.3](spec.md#33-get-systemping-post-systemping--getpingsystem-postpingsystem)); `/System/Info` is `401` without a token and a superset of the public payload with one.
- **Plan reference:** §3

### Done — 2026-08-26

**Fetching the real payload before writing the models found four things the spec had wrong.**
[probe: manual request, Jellyfin 10.11.11, 2026-08-26]

*`PackageName` is declared and not sent.* Chasing that to its cause resolved
[behaviours §1.7](../../docs/compatibility/behaviours.md), which had been marked ⚠️ UNVERIFIED and
assumed the absent-versus-null choice was per-property and inconsistent. **It is one line of
configuration** — `DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull` on the whole JSON
pipeline. [source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:33, Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs:148 @ v10.11.11] That now lives in `AtriumModel` rather than in a per-route flag, because a per-route
flag is one someone eventually forgets, and the one they forget is the one a client sees a stray
`null` on. The assumption was more complicated than the truth.

*The field order is derived-first.* `SystemInfo` serialises its own properties **before** the
inherited ones, as a derived .NET class does. So the two models are declared **independently
rather than by inheritance**: subclassing would put them the other way round. No client cares
about key order, but a byte-comparing golden test does, and the superset relationship is now
asserted by a test — which is the stronger check anyway, since it fails if a field is added to one
and forgotten in the other.

*`CastReceiverApplications` is not empty upstream*, and the spec said it was. Atrium's is, honestly.

*`EncoderLocation` and `SystemArchitecture` are populated* despite being deprecated. Matched;
`platform.machine()` is mapped to the reference's `Architecture` names.

**Two capability flags are deliberately honest rather than faithful.** The reference reports
`SupportsLibraryMonitor: true` and `CanSelfRestart: true`; v1 has neither. A client told a
capability exists behaves differently from one told it does not, and only one of those is
recoverable.

**The sweeps stopped being vacuous.** Three models, 36 fields, checked for alias and unit on every
run — the first real work T3 and T7 have done since they were written.

## T15 — `server.py`: the application factory  ✅

- [x] **Changes:** `create_app(settings)` wiring routers, middleware and lifecycle; an entry point.
- **Depends on:** T10, T11, T14
- **Verified by:** the app starts against a temporary data directory and serves `/System/Info/Public`; two instances in one test process do not share state.
- **Plan reference:** §3

### Done — 2026-08-26

**The server runs.** Started as a subprocess against a temporary directory, on a real port:

```
GET /System/Info/Public -> 200
   Server           Atrium/0.1.0.dev0
   X-Response-Time  24.4647
   Content-Type     application/json; charset=utf-8
   ProductName      'Jellyfin Server'   Version '10.11.11'
   LocalAddress     http://127.0.0.1:59040
GET /System/Info       -> 401 (no token), body=b''
GET /System/Ping       -> 200 "Jellyfin Server"
```

**Middleware order was checked, not assumed.** Starlette makes the *last* middleware added the
outermost, so response headers wrap the readiness gate — and a `503` served while starting still
carries `Server` and `X-Response-Time-ms`, as the reference's does. A test asserts it, because the
order is invisible from reading the two `add_middleware` lines.

**The test fixtures now build a real instance through the factory.** They had been assembling the
same pieces by hand, which tests a composition nobody runs. All 186 existing tests passed against
the real one unchanged, which is the useful part of the answer.

**No documentation routes are served.** The reference serves its OpenAPI document at
`/api-docs/openapi.json`; that route is not in `surface.yaml` and no analysed client asks for it
(Principle VI). The document is still *generated* — `app.openapi()` builds it — which is what
[ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md) chose FastAPI for. A test
asserts both halves.

**Two process notes.** The `pyproject.toml` edit that restores the entry point deferred from T1
**silently did nothing** the first time: `uv add` had rewritten the dependencies block and the
replacement matched nothing. The retry asserts the edit landed, which is the only reason it was
caught rather than shipped.

And warnings are now errors in the test configuration. The first one to matter was a deprecated
test client reaching a code path the server never uses; it is replaced by Starlette's own lifespan
context, which is closer to what a server actually does anyway.

## T16 — Golden responses and the content-type variants  ✅

- [x] **Changes:** `tests/golden/` for all three endpoints; the harness comparing **raw bytes**; `--update-golden`.
- **Depends on:** T15
- **Verified by:** AC-1, AC-2, AC-3 and AC-6 pass against a fresh instance; **AC-9** — the same request with `Accept: application/json`, `; profile="PascalCase"` and `; profile="CamelCase"` returns three byte-identical bodies.
- **Note:** compare bytes, not parsed objects. Casing, `null`-versus-absent and numeric type are the contract and all three vanish after parsing.
- **Plan reference:** §8

### Done — 2026-08-26

**AC-9 was false, and the test that covered it was passing.** The reference does not answer the
three declared content types identically: `profile="CamelCase"` really does emit **camelCase
property names**, and the response's content type echoes whichever profile matched.
[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]

The old test asserted that Atrium's three answers agree **with each other**. They did. Nobody had
asked the reference, and the claim it was written from carried a `[spec: …]` citation that was
accurate about the schema and silent about the serialisation. Three content types pointing at one
schema is exactly what a document can say and a server can contradict.

The measurement is in [behaviours §1.13](../../docs/compatibility/behaviours.md), with the four
details a reimplementation needs and none of which are in the document: the profile is matched
leniently on the media type parameter but **not when a `charset` sits beside it**; ranking is
ordinary `q=` negotiation; names convert at every depth while **dictionary keys do not convert at
all**; and the conversion is .NET's policy, not "lower the first letter" — `UICulture` becomes
`uiCulture`, measured.

**Not implemented here, and that is the deliberate part.** Doing it correctly means the profile has
to reach the serialisation layer, because only there is a property distinguishable from a
dictionary key — by the time the body is bytes, renaming `ProviderIds`' keys would look identical
to renaming a property. That is a change to [plan §5](plan.md#5-contracts), so it is **T19** rather
than a paragraph in this task. The gap is recorded in
[behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) and **pinned by a
test that fails when T19 lands**, which is the only mechanism that makes a documented gap
self-closing.

**Both analysed clients were checked rather than assumed.** Neither sends the profile: music-client
decodes with a PascalCase strategy of its own, and video-client deletes the `profile=` content
types from the OpenAPI document during its build — its generated code cannot ask for one. The
comment explaining that build step gives the same reason this repository did. Two projects, the
same inference, from the same document.

**The golden instance is pinned, not normalised.** Three values differ between two hosts running
the same code, and each is fixed at its source: the identity comes from a `state.json` written
before startup, `LocalAddress` from `use_request_host` so it is a function of the request, and the
architecture from a fixed `platform.machine()`. That leaves **one** substitution, the temporary
data directory. Pinning beats substituting because a substituted value is a value nobody is
checking any more — `SystemArchitecture` would have been replaced by a placeholder along with the
mapping bug that produced it, so the mapping got its own test instead.

**The harness proved itself on a type change.** Turning `false` into `"false"` in a golden file
produces a failure naming the byte offset and both spellings. Every assertion in the rest of the
suite would have passed through it unchanged — which is the argument for comparing bytes, made
concretely rather than as a principle.

## T17 — Route registration against `surface.yaml`  ✅

- [x] **Changes:** `tests/conformance/test_routes.py` asserting every 001 route in `surface.yaml` is registered, and that **no route exists outside the file**.
- **Depends on:** T15
- **Verified by:** passes; adding an unlisted route fails it. This is the automated half of Principle VI.
- **Plan reference:** conformance L0

### Done — 2026-08-26

**Asking how the reference routes a path found four differences, and the server had all four.**
[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]

| A client sends | Reference | Atrium was |
|---|---|---|
| `/system/info/public` | `200` | `404` — routing is case-sensitive |
| `/System/Info/Public/` | `200` | `307` to the stripped path |
| `/System/Info/Public//` | `404` | `307` **to a URL that works** |
| `PUT /System/Ping` | `405`, `Allow: GET, POST`, empty | `405`, `Allow: POST`, `{"detail": …}` |
| A path matching no route | `404`, empty, no content type | `{"detail": "Not Found"}` |

The last row is the uncomfortable one. [behaviours §1.11](../../docs/compatibility/behaviours.md)
has said since T13 that an unmatched path answers with an empty body, and it named
`{"detail": "…"}` as the shape that is neither of the reference's two — and that is exactly what
the server was sending. The module that owns refusals said so in its docstring and registered a
handler for one exception. Nothing had noticed, because until this feature had routes there was no
path to get wrong, and no test had ever asked for one. **A documented behaviour with no test is a
plan.**

**`Allow` was wrong in a way only a two-route path can be.** `/System/Ping` is two registrations,
`GET` and `POST`, and the framework fills `Allow` from the *first* route whose path matched — so it
advertised `POST` and not `GET`. A path with one method would never have shown it, and 001 has
exactly one path with two.

**The casing fix went through the routers, not through the framework's internals.** The first
version relaxed each compiled route pattern in place: five lines, all tests green, and wrong -
FastAPI 0.141 includes routers lazily and rebuilds the matching structures from an internal cache,
so the mutation applied to objects nothing routes through. It failed loudly, which was luck.
What replaced it builds a table from the routers the factory declares, using Starlette's own
`compile_path`, and rewrites a request's path to the canonical spelling before routing. Only the
literal segments are respelled; a path parameter reaches the handler exactly as it arrived, which
002's `/Users/{userId}` is the first route to care about.

**The registration test uses two views and asserts they agree.** The generated OpenAPI document
knows every route the framework will route, and misses one registered with
`include_in_schema=False`. The factory's route table knows what path matching and `Allow` are built
from, and misses a router included without being listed. Each covers the other's blind spot, and
both were checked by making the two disagree on purpose. That pair is also the reason none of this
reaches into the framework to enumerate routes - it does not have to.

**A tripwire, deliberately.** `IMPLEMENTED_FEATURES` is `{"001"}`, so a 002 route that ships before
002 fails the suite even though it is in `surface.yaml`. The next feature changes that line on
purpose.

**And the surface validator's version gate had never run.** Reusing its parser in the test meant
running the tool, and the tool passed a document it should have refused: it reads the pinned
version out of `surface.yaml`'s `reference:` block, and the field pattern required four leading
spaces where that block uses two. Every reference field was silently dropped, `pinned` was always
`None`, and the check was `if pinned and …`. One character of indentation, and a gate that could
not fail. It now also refuses a surface file whose reference block did not parse, because that is
the failure this hid. What the working gate immediately reported is recorded in
[reference-target §1](../../docs/compatibility/reference-target.md#1-the-pinned-version): the
contract pins the `10.11.10` document and the reachable server serves `10.11.11`. The two agree on
all 55 endpoints; moving the pin is a version move with its own procedure, and is not this task's
to make.

## T18 — CI  ✅

- [x] **Changes:** a workflow running `ruff`, `mypy --strict`, `pytest`, `tools/extract_v1_surface.py`, and a freshness check that `property-names.json` matches the pinned document when one is available.
- **Depends on:** T17
- **Verified by:** green on the branch; **no job touches the network**, and the suite passes with no Jellyfin reachable (Principle VII).
- **Plan reference:** §8

### Done — 2026-08-26

**Two of the four things the task lists could not run in CI as written**, and both for the same
reason: the pinned OpenAPI document is fetched, never vendored, so the runner has none.

`tools/extract_v1_surface.py` *required* `--spec`, which made it a tool CI cannot run. It now runs
without one, doing every check that needs no document — levels, duplicates, the shape of each
entry, the version pin's presence — and its **last line names the checks that did not happen**.
Silence there would read as a pass, which is the failure mode of every conditional gate.

The `property-names.json` freshness check genuinely needs the document, so in CI it is conditional
and says which branch it took. What holds without one moved into the suite, where it is a hard
gate: the index is sorted, unique, self-counting, and **pins the same version `surface.yaml`
does** — two committed artefacts that nothing had ever compared.

**"No network" was a claim, and is now a gate.** The suite fails any test that opens a TCP
connection, naming the address it dialled (Principle VII). Datagram sockets stay allowed, because
`address_facing` opens one to ask the routing table which local address faces a peer and sends no
packet. The exemption for feature 010's differential harness is a registered marker rather than
something that will be improvised under pressure.

Writing that guard turned up a test that was already reaching the network: the routing lookup's
"returns None rather than raising" case used the hostname `not-an-address`, which a resolver with
a search domain — or a provider that answers every name with its own advertising host — resolves
happily. It is now `.invalid`, which RFC 6761 reserves for exactly this and which no resolver may
answer.

**The gates were each made to fail before being believed.** A modified golden file, a `level: L9`,
a removed version pin, a test that opens a socket, an acceptance criterion whose test was renamed:
five deliberate breakages, five red gates. This is the task where "the check runs" is the whole
deliverable, and T17 had just found a gate that had never once run.

**CI runs the tools on Python 3.9 and 3.14.** `tools/README.md` claims a probe works on the
interpreter a machine already has — macOS and Xcode ship 3.9 — and on the newest. Every tool is
compiled and its `--help` executed under both, which exercises the imports and the whole argument
parser. The suite itself runs on 3.12, the floor the package declares, and on 3.14.

**The first run failed, on the one thing that could not be checked locally.** Three jobs never
started: `astral-sh/setup-uv@v10` does not resolve, because that action publishes floating major
tags only up to `v7` and is pinned to a full version from `v8` on. The two jobs that use nothing
beyond `checkout` passed, which is what said which half was wrong. Every action version here was
read from the API rather than remembered — and the version that was *correct* was still
unusable in the form everyone writes it.

**And the acceptance criteria are now mapped to their tests, in a file that fails three ways.**
The definition of done below says *by name*, which until now nobody could check without reading
two documents side by side. `tests/conformance/test_acceptance.py` reads the criteria out of
[spec §5](spec.md#5-acceptance-criteria) and fails if one has no test, if a named test no longer
exists, or if the count changed. Writing it found that AC-10 had only indirect coverage — the
alias sweep implies PascalCase without ever asserting it — so the casing assertion the
[conformance document](../../docs/compatibility/conformance.md#l1--shape) promises now exists as
itself.

## T19 — The `CamelCase` content-type profile

- [ ] **Changes:** profile selection from the request's `Accept`, a camelCase serialisation of every response model, and the matched profile echoed in the response's content type.
- **Depends on:** T16
- **Verified by:** the three declared content types produce the two bodies the reference produces; a response carrying a dictionary keeps that dictionary's keys unconverted; `UICulture` serialises as `uiCulture`; and T16's pinning test — which asserts the gap — is deleted in the same change.
- **Note:** added by T16, which measured that the three declared content types are **two**
  behaviours rather than three names for one. Everything needed to build it is in
  [behaviours §1.13](../../docs/compatibility/behaviours.md#113-the-camelcase-profile-really-is-camelcase): the matching rule, the ranking rule and the two conversion rules. The one design constraint is that the conversion has to happen **where a model is still a model** — dictionary keys are not converted, and finished bytes cannot tell a property from a dictionary key. That decision amends [plan §5](plan.md#5-contracts), which is why it is a task and not a paragraph in T16.
- **Plan reference:** §5, and the amendment it makes to it

---

## Definition of done

The feature is done when **all** of these hold:

- [x] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing test — all **eleven** now, by name, and the mapping is itself a test (T18).
- [x] Every endpoint reaches the level declared in [`spec.md` §6](spec.md#6-conformance): L3 for `/System/Info/Public` is deferred until the differential harness (010) exists; **L2 is met now and the gap is recorded**, not silently skipped.
- [x] `docs/compatibility/surface.yaml` lists every route added, and no route exists outside it (T17).
- [x] The two cross-cutting sweeps run in CI and fail on a deliberately introduced violation of each — each sweep carries the tests that prove it rejects what it exists to reject.
- [x] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same change.
- [x] Any newly measured reference behaviour is in `docs/compatibility/behaviours.md` with provenance.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

**Six of the seven hold. The last one waits on T19**, which is this feature's own §3.0 rule 2 and
the only open task in the file: the reference answers `profile="CamelCase"` in camelCase and Atrium
does not. It is recorded as a gap with a closing mechanism
([behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)) and pinned by a
test, so nothing about it is silent — but a feature is not `Implemented` while a task of its own
is open, and moving that task out of 001 is a scope decision rather than a tidy-up. **002 does not
have to wait for it**: what it inherits from 001 — the base model, the sweeps, the data directory,
the persisted identity, the authentication seam, the byte-comparing harness — is all delivered, and
none of it changes when the profile lands.

## What this feature owes the next one

Not a checklist item, but the reason 001 is sized the way it is. When these tasks are done, 002
inherits: a base model that cannot serialise the wrong casing, two sweeps that fail on the wrong
unit or the wrong name, a configuration and data directory, a persisted server identity, an
authentication seam with the signature it needs, and a test harness that compares bytes.

If any of that is missing when 002 starts, it gets built under deadline pressure inside a feature
that has other work to do. That is the argument for the size of T1 to T7.
