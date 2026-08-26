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

## T6 — `compat/guids.py`: identifiers

- [ ] **Changes:** `Guid32` validated against `^[0-9a-f]{32}$`; generation from `secrets.token_hex(16)`; the deterministic derivation helper 003 will use.
- **Depends on:** T2
- **Verified by:** rejection tests for uppercase, dashes, wrong length; the derivation helper returns the same value for the same key across processes.
- **Plan reference:** §6.3

## T7 — The unit sweep

- [ ] **Changes:** `tests/conformance/test_units.py` — every field whose name ends in `Ticks` serialises as an integer; every field whose name ends in `Date` serialises with seven fractional digits and a `Z`.
- **Depends on:** T4, T5
- **Verified by:** passes; a deliberately float-typed `*Ticks` field fails it.
- **Plan reference:** §8.3

## T8 — `config/`: paths and operator configuration

- [ ] **Changes:** `config/paths.py` with the data-directory layout; `config/settings.py` loading `config.toml` with defaults for `server_name`, bind address and port, `published_url`, `use_request_host`.
- **Depends on:** T1
- **Verified by:** missing file → defaults plus one log line; malformed file → **refuses to start**, naming file, line and key; unwritable data directory → refuses to start. Each is a test, because each is a failure mode an operator will actually hit.
- **Plan reference:** §4, §7

## T9 — `config/state.py`: server identity

- [ ] **Changes:** `state.json` read and write; atomic write (temp file, `fsync`, `os.replace`); identity generated once on first start.
- **Depends on:** T6, T8
- **Verified by:** **the AC-4 test** — start and record the id; restart, unchanged; delete everything *except* `state.json`, restart, unchanged. Plus: a corrupt `state.json` refuses to start rather than regenerating, and a write interrupted before `os.replace` leaves the previous file intact.
- **Note:** the third phase passes trivially today because there is no store. That is exactly why it must exist before there is one.
- **Plan reference:** §4, §7, §8.1

## T10 — `lifecycle.py` and the readiness gate

- [ ] **Changes:** `Readiness`; middleware answering `503` with `Retry-After` while not ready.
- **Depends on:** T1
- **Verified by:** a request during startup gets `503` with the header; after readiness the same request is served.
- **Plan reference:** §5, §7

## T11 — `compat/middleware.py`: the `Server` header

- [ ] **Changes:** middleware setting `Server: Atrium/{__version__}` on every response.
- **Depends on:** T1
- **Verified by:** the header is present and carries **Atrium's** version, not the reference's — asserted against both constants so a future edit cannot silently swap them.
- **Plan reference:** §6.5

## T12 — `net/address.py`: `LocalAddress`

- [ ] **Changes:** `resolve_local_address(request, settings)`, three tiers, first match wins; loopback fallback.
- **Depends on:** T8
- **Verified by:** the nine-row table of [plan §8.2](plan.md#82-localaddress) — published URL with and without a trailing slash; request-host mode on default and non-default ports, http and https; two requesters on different networks; a requester matching nothing. No test touches a real interface.
- **Note:** the reference's HTTPS override is **not** implemented ([behaviours §4.2](../../docs/compatibility/behaviours.md#42-localaddress-does-not-get-an-https-override)). A test asserts the scheme follows what the server is reachable on, so the divergence is deliberate in code as well as in prose.
- **Plan reference:** §6.4

## T13 — `api/deps.py`: the authentication seam

- [ ] **Changes:** `require_user()` with the signature 002 will keep, raising `401` unconditionally.
- **Depends on:** T1
- **Verified by:** a route depending on it answers `401`; a test overriding it through `app.dependency_overrides` reaches the route body.
- **Note:** no credential of any kind ships. The `200` path is exercised by the override, per [plan §1](plan.md#1-approach).
- **Plan reference:** §1, §5

## T14 — `api/system.py`: the three routes

- [ ] **Changes:** the `PublicSystemInfo` and `SystemInfo` models; `GET /System/Info/Public`, `GET /System/Info`, `GET` and `POST /System/Ping`.
- **Depends on:** T3, T9, T12, T13
- **Verified by:** each route answers; `/System/Ping` returns the JSON string `"Jellyfin Server"` — the **product** name, not the operator's server name ([spec §3.3](spec.md#33-get-systemping-post-systemping--getpingsystem-postpingsystem)); `/System/Info` is `401` without a token and a superset of the public payload with one.
- **Plan reference:** §3

## T15 — `server.py`: the application factory

- [ ] **Changes:** `create_app(settings)` wiring routers, middleware and lifecycle; an entry point.
- **Depends on:** T10, T11, T14
- **Verified by:** the app starts against a temporary data directory and serves `/System/Info/Public`; two instances in one test process do not share state.
- **Plan reference:** §3

## T16 — Golden responses and the content-type variants

- [ ] **Changes:** `tests/golden/` for all three endpoints; the harness comparing **raw bytes**; `--update-golden`.
- **Depends on:** T15
- **Verified by:** AC-1, AC-2, AC-3 and AC-6 pass against a fresh instance; **AC-9** — the same request with `Accept: application/json`, `; profile="PascalCase"` and `; profile="CamelCase"` returns three byte-identical bodies.
- **Note:** compare bytes, not parsed objects. Casing, `null`-versus-absent and numeric type are the contract and all three vanish after parsing.
- **Plan reference:** §8

## T17 — Route registration against `surface.yaml`

- [ ] **Changes:** `tests/conformance/test_routes.py` asserting every 001 route in `surface.yaml` is registered, and that **no route exists outside the file**.
- **Depends on:** T15
- **Verified by:** passes; adding an unlisted route fails it. This is the automated half of Principle VI.
- **Plan reference:** conformance L0

## T18 — CI

- [ ] **Changes:** a workflow running `ruff`, `mypy --strict`, `pytest`, `tools/extract_v1_surface.py`, and a freshness check that `property-names.json` matches the pinned document when one is available.
- **Depends on:** T17
- **Verified by:** green on the branch; **no job touches the network**, and the suite passes with no Jellyfin reachable (Principle VII).
- **Plan reference:** §8

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing test — all ten, by name.
- [ ] Every endpoint reaches the level declared in [`spec.md` §6](spec.md#6-conformance): L3 for `/System/Info/Public` is deferred until the differential harness (010) exists; **L2 is met now and the gap is recorded**, not silently skipped.
- [ ] `docs/compatibility/surface.yaml` lists every route added, and no route exists outside it (T17).
- [ ] The two cross-cutting sweeps run in CI and fail on a deliberately introduced violation of each.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same change.
- [ ] Any newly measured reference behaviour is in `docs/compatibility/behaviours.md` with provenance.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next one

Not a checklist item, but the reason 001 is sized the way it is. When these tasks are done, 002
inherits: a base model that cannot serialise the wrong casing, two sweeps that fail on the wrong
unit or the wrong name, a configuration and data directory, a persisted server identity, an
authentication seam with the signature it needs, and a test harness that compares bytes.

If any of that is missing when 002 starts, it gets built under deadline pressure inside a feature
that has other work to do. That is the argument for the size of T1 to T7.
