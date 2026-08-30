---
feature: 001-server-identity-and-discovery
title: Server identity and discovery — implementation plan
status: Implemented
created: 2026-08-26
updated: 2026-08-26
spec_status_required: Accepted
spec_status_actual: Implemented
accepted: 2026-08-26
---

# 001 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour; where this document
> appears to restate it, the spec wins.

## 1. Approach

001 is three endpoints and roughly forty lines of business logic. It is first, and it is worth
planning carefully, because of what it drags in: **this is the feature that builds `compat/`**, the
layer that decides whether every response in the project is shaped correctly. Nine features will
inherit it without thinking about it, which is the point — Principle I has to be enforced by the
type system and by CI, not by each route author remembering.

Three decisions dominate the plan, and each came out of a fact rather than a preference.

**The wire format cannot be generated mechanically.** Pydantic can produce PascalCase from
snake_case with an alias generator, and for 988 of the reference's 1043 property names it produces
the right answer. For **55 it does not**, because the reference keeps acronyms uppercase:
`IsHD`, `IsAVC`, `TwoLetterISOLanguageName`. Five of those land inside v1's own schemas.
`[spec: measured across components.schemas of the pinned 10.11.10 document]`

A generator plus hand-written exceptions would work and would rot: nobody notices a missing
exception until a client does. So the plan inverts the check — **every alias is validated against
the pinned OpenAPI document in a test**, which turns "is this PascalCase?" into "is this the exact
property name the reference uses?". That is a strictly stronger question, it is mechanical, and it
is the natural sibling of `tools/extract_v1_surface.py`.

**Server identity cannot live in the database.** Acceptance criterion 4 requires `Id` to be
identical "across a restart **and across a rebuild of the store from empty**". Anything in the
rebuildable store fails that by construction. Identity therefore lives in a small state file the
server owns, beside the operator's configuration — which also means **001 introduces no database at
all**. SQLAlchemy and Alembic arrive with 002, where there are users to store.

**Authentication does not exist yet, and the plan must not invent it.** `/System/Info` requires a
token (spec §3.2), but tokens are 002's. 001 defines the dependency *seam* — a callable that yields
the authenticated user or raises `401` — with an implementation that always raises. Its own tests
exercise the `200` path by overriding that dependency, so both branches of acceptance criterion 5
are covered without shipping a placeholder credential.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Python 3.12+, managed by `uv` | [ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md) |
| FastAPI on Uvicorn | [ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md) |
| Pydantic v2 with PascalCase aliases | [ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md) |
| pytest, httpx; ruff, mypy strict | [ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md) |
| Reference pinned at Jellyfin 10.11.x | [ADR-0004](../../docs/decisions/0004-pin-to-jellyfin-10-11.md) |
| GPL-3.0-or-later, SPDX header per file | [ADR-0005](../../docs/decisions/0005-licence.md) |
| `compat/` is the only module that knows the wire format is Jellyfin's | [architecture §1](../../docs/architecture.md) |
| Ticks are the internal unit; identifiers are derived, never allocated | [architecture §4](../../docs/architecture.md) |

**Deviations:** one, and it is a narrowing rather than a change.
[ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) specifies SQLite as the store;
001 introduces **no** store, because §1 shows identity must not live in it. No new ADR: the decision
still stands for the features that have rows to keep.

## 3. Modules

```
src/atrium/
├── __init__.py          __version__ — Atrium's own version, not the reference's
├── server.py            application factory: settings -> app
├── lifecycle.py         readiness state; the 503 gate while starting
├── config/
│   ├── paths.py         data-directory layout
│   ├── settings.py      operator configuration (TOML), with defaults
│   └── state.py         server-owned persisted state, written atomically
├── compat/
│   ├── model.py         AtriumModel: the base every response inherits
│   ├── aliases.py       the irregular-alias table and its validator
│   ├── dates.py         .NET round-trip datetime
│   ├── ticks.py         Ticks type and conversions
│   ├── guids.py         32-hex identifier type and derivation
│   ├── registry.py      every model, for the two sweeps to walk
│   ├── responses.py     the JSON response class and its exact content type
│   ├── errors.py        the wire shape of a refusal
│   ├── routing.py       how a path is matched: casing, trailing slash, Allow
│   ├── profiles.py      which JSON serialisation was asked for, and the conversion
│   └── middleware.py    Server and X-Response-Time-ms headers
├── domain/
│   └── user.py          who is asking — the seam's return type; 002 grows it into the account
├── net/
│   └── address.py       LocalAddress resolution
└── api/
    ├── deps.py          the authentication seam
    └── system.py        the three routes of this feature
```

Six of those modules are not in the tree this plan was accepted with, and one that was is gone.
`registry.py`, `responses.py` and `errors.py` arrived with the tasks that needed them (T7, T12,
T13); `domain/user.py` arrived with T13 beside them — the seam's return type made real, which 002
grew into the account itself, and which no plan's tree drew until the 2026-08-28 audit (M11 in
[the record](../../docs/audits/2026-08-28.md)); `routing.py` arrived with T17, when the reference turned out to match paths more loosely than
the framework does; `profiles.py` with T19, when it turned out to have two serialisations.
`api/router.py` was never written: T15 put the assembly in the application factory, where the list
of routers reads as one of the decisions the factory makes, and a module whose whole content is
that list would have been indirection.

| Module | Owns | Must not |
|---|---|---|
| `compat/` | Serialisation, casing, units, formats, the `Server` header | Know that any specific endpoint exists |
| `config/` | Where things live on disk; what the operator set; what the server persists | Serve HTTP |
| `net/` | Turning a request into the address to advertise | Know what the value is used for |
| `api/` | Routing, status codes, dependency wiring | Contain business rules |
| `lifecycle.py` | Whether the server is ready to answer | Know which routes exist |

`compat/` deliberately has **no** dependency on `api/`. The sweep tests in §8 walk the model
registry, not the router, so a model that is never routed is still checked.

## 4. Data model

**No database.** Two files under the data directory, and the split is deliberate: humans edit one,
the server owns the other, and neither format is chosen to be convenient for the other party.

```
<data-dir>/
├── config.toml       operator-edited.  Read at startup, never written by the server
├── state.json        server-owned.     Written by the server, never edited by hand
├── cache/
├── logs/
└── transcodes/
```

**`config.toml`** — everything the operator decides. For 001: `server_name`, bind address and port,
`published_url`, `use_request_host`, `data_dir`. TOML because it is the format people can edit
without a linter, and `tomllib` is in the standard library from 3.11.

**`state.json`** — what the server must remember and nobody should type:

| Field | Purpose |
|---|---|
| `server_id` | The 32-hex identity of acceptance criterion 4 |
| `startup_wizard_completed` | Whether initial configuration is done |
| `created` | When the instance was first started, for support |

**Writes are atomic**: serialise to a temporary file in the same directory, `fsync`, then
`os.replace`. A crash halfway through writing `state.json` must not cost the server its identity —
that would make every client treat it as a new server and re-authenticate.

`server_id` is generated exactly once, from 16 random bytes rendered as 32 lowercase hex
characters, and never regenerated. Random rather than derived: there is nothing stable to derive it
from that an operator could not change, and it must survive them changing everything else.

## 5. Contracts

These are the seams the next nine features plug into. Getting them right here is most of the value
of doing 001 first.

**`compat.model.AtriumModel`** — the base class of every response model in the project.

```python
class AtriumModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=atrium_alias,   # §6.1: generator plus the irregular table
        populate_by_name=True,          # the reference's binder is case-insensitive on input
        serialize_by_alias=True,        # model_dump() is wire-shaped without the caller asking
        extra="ignore",                 # unknown request properties are ignored, not rejected
    )
```

Responses are returned through FastAPI's `response_model`, which serialises `by_alias=True` by
default. The base does **not** set `exclude_none`: absent-versus-null is per property in the
reference and currently unverified
([behaviours §1.7](../../docs/compatibility/behaviours.md#17-a-null-property-is-absent-everywhere-by-one-setting)),
so it is decided per model against a golden response rather than by a blanket rule.

> **Superseded by measurement, T14.** There is no per-property judgement: the reference omits every
> null, through one `DefaultIgnoreCondition` setting on its whole JSON pipeline. `AtriumModel`
> therefore drops nulls in its serialiser, and no route needs `response_model_exclude_none`.

> **Amended by T19: the serialiser also applies the content-type profile.** The reference answers
> `Accept: application/json; profile="CamelCase"` in camelCase, and it converts **property names at
> every depth while never touching dictionary keys**
> ([behaviours §1.13](../../docs/compatibility/behaviours.md#113-the-camelcase-profile-really-is-camelcase)).
> That single rule decides where the conversion may live. A response that has been rendered — to
> bytes, or even to a plain `dict` — has lost the distinction between a property and a key, so the
> only correct place is inside `AtriumModel`'s serialiser, where a field is still a field: a nested
> model renames itself, and a `dict[str, …]` field's keys are left alone by construction rather
> than by a list of exceptions.
>
> The negotiated profile reaches it through a **context variable** set by a middleware
> (`compat.profiles`), because the web framework's serialisation call takes no context to pass one
> through. The alternatives were worse in kind, not just in size: making every route call a helper
> puts the correctness of every response in the hands of whoever writes the next one, and dropping
> `response_model` to serialise by hand would have cost the generated OpenAPI document.

**`api.deps.require_user`** — the authentication seam.

```python
async def require_user(request: Request) -> User:
    """Raise 401 unless the request carries a valid token. 002 supplies the implementation."""
```

001 ships a version that always raises `401`. 002 replaces the body, not the signature. Tests
override it through `app.dependency_overrides` to exercise the authenticated path.

**`net.address.resolve_local_address(*, settings, request_host, request_scheme, request_port,
client_address, lookup=address_facing) -> str`** — the three tiers of spec §3.4 as one pure
function. It never sees a request object: the caller unpacks the four request facts, and `lookup`
is the one seam with the operating system, injectable so every tier is table-testable. *(The
accepted plan's `(request, settings)` was corrected at the 2026-08-28 audit — M15 in
[the record](../../docs/audits/2026-08-28.md).)*

**`lifecycle.Readiness`** — a small object with `ready: bool`, `retry_after_seconds: int` and the
`message` the 503 carries. Middleware consults it; nothing else does. *(The accepted plan's
`retry_after` named an attribute that never existed — corrected at the same audit, M16.)*

## 6. Algorithms

### 6.1 Alias resolution

```python
IRREGULAR = {
    "is_hd": "IsHD",                                  # BaseItemDto
    "is_avc": "IsAVC",                                # MediaStream
    "two_letter_iso_language_name": "TwoLetterISOLanguageName",     # CultureDto
    "three_letter_iso_language_name": "ThreeLetterISOLanguageName",  # CultureDto
    "three_letter_iso_language_names": "ThreeLetterISOLanguageNames",
}

def atrium_alias(field: str) -> str:
    return IRREGULAR.get(field, to_pascal(field))
```

Five entries today — every irregular name inside v1's schemas. The table is **not** the guarantee;
the validator in §8 is. A missing entry fails a test rather than reaching a client.

### 6.2 Date serialisation

The reference emits .NET round-trip format: seven fractional digits and a `Z`
(`2025-06-19T00:00:00.0000000Z`) ([behaviours
§1.2](../../docs/compatibility/behaviours.md#12-dates-carry-up-to-seven-fractional-digits), where
the measurement lives). Python's `datetime` carries **six**, so the seventh digit is
always zero — which is correct, not a compromise, because a hundred-nanosecond unit is not
representable in `datetime` and the reference's own values are microsecond-derived in practice.

```python
f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond:06d}0Z"     # value must be UTC before formatting
```

Parsing is deliberately lenient: any ISO-8601 input, with or without a timezone, three or seven
fractional digits; a missing timezone reads as UTC.

### 6.3 Identifiers

`Guid32` is a string type validated against `^[0-9a-f]{32}$`. Generation is
`secrets.token_hex(16)`. A derivation helper is written here — deterministic 32-hex from a stable
key — because 003 needs it for items, but 001 does not use it.

### 6.4 `LocalAddress`

The three tiers of spec §3.4, in order, first match wins:

1. `published_url` set → return it with trailing `/` stripped. No inspection, no second-guessing:
   an operator behind a reverse proxy knows something the server does not.
2. `use_request_host` set → build from the request's `Host` and scheme, omitting the port when it
   is the default for that scheme (80/http, 443/https).
3. Otherwise → enumerate the server's bound addresses, pick the one on the same network as the
   requester's address, and pair it with the port actually bound.

Tier 3's fallback when nothing matches is the loopback address, never an empty string: a client
receiving `""` has no way to recover, and one receiving a wrong-but-well-formed address fails
visibly.

**The reference's HTTPS override is not implemented** — the deliberate divergence of
[behaviours §4.2](../../docs/compatibility/behaviours.md#42-localaddress-does-not-get-an-https-override).

### 6.5 Version reporting

Two version numbers, and confusing them is a bug in both directions:

| Constant | Value | Where it appears |
|---|---|---|
| `REFERENCE_VERSION` | `10.11.11` | `Version` in the API responses |
| `__version__` | Atrium's own | The `Server` header, logs, `--version` |

`REFERENCE_VERSION` moves only through the version-bump procedure of
[conformance.md](../../docs/compatibility/conformance.md#when-the-reference-version-moves).

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Still starting up | `Readiness.ready` false | `503` with `Retry-After` | Client retries |
| `config.toml` missing | Not found at startup | Defaults, and a log line saying so | Runs with defaults |
| `config.toml` malformed | Parse error at startup | **Refuse to start**, naming file, line and key | Operator fixes it |
| `state.json` missing | Not found at startup | Generate identity, write it, log the new id | Normal first run |
| `state.json` malformed | Parse error at startup | **Refuse to start** | Operator restores or removes it |
| Data directory unwritable | Write check at startup | **Refuse to start** | Operator fixes permissions |
| Requester address unresolvable | Tier 3 finds nothing | Loopback address | Response is still well-formed |

**Refusing to start beats starting wrongly.** A server that boots with a fresh identity because it
could not read `state.json` looks healthy and silently invalidates every client's session. The one
thing 001 must never do is invent an identity when it had one.

## 8. Testing strategy

Every acceptance criterion in spec §5 maps to a named test.

| Spec AC | Test |
|---|---|
| 1, 2, 3 | Golden response for `/System/Info/Public` against a fresh instance |
| 4 | Restart and rebuild-from-empty identity test — §8.1 |
| 5 | Route test for `401`; dependency-override test for `200`; superset assertion |
| 6 | Exact-body test for both methods |
| 7, 8 | `LocalAddress` table — §8.2 |
| 9 | Three requests with the three `Accept` values: **two goldens**, because two of them are one serialisation and the third is the other — plus the negotiation table and the content-type echo |
| 10 | The casing sweep — §8.3 |
| 11 | The route table and the refusal shapes — §8.5 |

### 8.1 Identity persistence

Three phases in one test: start and record the id; restart and assert it is unchanged; delete
everything **except** `state.json`, restart, assert unchanged. The third phase is what proves the
identity is not in a rebuildable store — and today it passes trivially because there is no store,
which is exactly why the test must exist before there is one.

### 8.2 `LocalAddress`

Table-driven over the three tiers with synthesised requester addresses: published URL set and with
a trailing slash; request-host mode on default and non-default ports, http and https; two
requesters on different networks; a requester matching nothing. Nine rows, one behaviour each.

### 8.3 The two cross-cutting sweeps

**Delivered by this feature**, and they are the reason 001 is worth its size.

- **Alias validation.** Walk every `AtriumModel` subclass and assert that **every serialisation
  alias is a property name the reference actually uses**. This catches the 5.3% of names a
  generator gets wrong, catches a typo, and catches a field invented by accident. It fails with the
  model, the field, the alias produced and the nearest name that exists.

  **Against what, in CI.** The pinned OpenAPI document is fetched, not vendored, and CI has no
  Jellyfin to fetch it from — so the sweep runs against a **committed index of property names**
  extracted from it: 1043 names, about 15 KB, regenerated by a tool and diffed in CI when the
  document is available. The index is our own extraction rather than the document itself, it needs
  no network, and it makes the sweep a hard gate rather than a test that skips when a file is
  missing. A skipping guard would have exactly the same effect as not having written it.

  **Two strengths, in order.** First the flat check — is this alias *any* name the reference uses —
  which needs no mapping between our models and their schemas and already catches every irregular.
  Then, once models map cleanly onto schemas, the stronger per-schema check: is this alias a
  property of *this* schema. The second is better and the first is available immediately, so the
  first ships with 001 and the second follows the models.
- **Unit sweep.** Fields are checked **by behaviour, not by structure**: each is rebuilt into a
  single-field probe model and actually serialised, so the sweep tests what a client would receive
  rather than what an annotation appears to promise.

  Two rules, and the **type rule is the primary one**: any field whose annotation mentions
  `datetime` must serialise in the reference's format, which catches a plain `datetime` wherever it
  appears. The name rule is secondary and catches a date field typed as something else — a wire
  name that **starts or ends with** `Date` must be date-valued.

  Start *or* end, because the reference uses both spellings: `PremiereDate` and `DateCreated`.
  Measured over the 1043 names in the pinned document, `endswith` alone covers 13 and misses 7.
  Widening to "contains" would gain one real field and three false positives — `ReleaseDateFormat`
  is an enum and `UseFileCreationTimeForDateAdded` is a boolean — so it stops at start-or-end. A
  sweep with false positives gets switched off within a week, which costs more than the field it
  would have caught.

  Ticks are probed with a **whole** float. A plain `int` field already rejects `5763.999`, since a
  fractional float is not an integer, so probing with one would report that `int` is safe. It
  accepts `5764.0` — the same caller, the same mistake, a rounder number.

Both walk the model registry rather than the router, so a model reaches CI whether or not a route
returns it yet.

### 8.4 Fixtures

A fresh instance per test, with a temporary data directory. No shared state between tests, no
ordering dependencies. The whole suite runs with no network and no external service.

### 8.5 Routes, against `surface.yaml`

The L0 check, and the automated half of Principle VI: every endpoint the surface file marks as this
feature's is registered, and **no route exists outside the file**.

Both halves are asserted against **two independent views** of what the application serves, because
each has a blind spot the other covers:

- **the OpenAPI document the framework generates**, which knows every route it will route — and
  misses one registered with `include_in_schema=False`;
- **the route table the factory builds from its own list of routers**, which is what path matching
  and the `Allow` header are built from — and misses a router that was included without being on
  that list.

A route visible to one and not to the other is a wiring bug whichever way round it is, so their
agreement is asserted directly. The pair is also why none of this reaches into the framework's
internals to enumerate routes: two public views are enough, and they disagree loudly.

The same file covers **what counts as "this path"** — the casings and the trailing slash of
[spec §3.6](spec.md#36-how-a-request-is-matched-to-a-route) — and **how a path refuses**: the empty
`404`, the empty `405`, and an `Allow` header built from every route on the path rather than from
the first one that matched.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A response ships in camelCase | Low | **Total** — every client decodes nothing | Base model plus the alias validator; impossible to reach a route without inheriting it |
| An acronym alias is wrong | **Medium** | One field silently absent to clients | The alias validator compares against the reference, not against a casing rule |
| Date format drifts to three digits | Medium | Strict client parsers reject the whole body | Unit sweep; explicit serialiser rather than Pydantic's default |
| `state.json` lost or corrupted | Low | Every client re-authenticates | Atomic writes; refuse to start rather than regenerate |
| `REFERENCE_VERSION` and `__version__` confused | Medium | Clients gate capabilities on the wrong number | Separate constants, separate modules, asserted in the golden response |
| Address enumeration behaves differently per platform | Medium | Wrong `LocalAddress` on some hosts | Tier 3 is isolated behind one function and tested with synthesised inputs, not real interfaces |
| `compat/` grows endpoint knowledge | Medium | The one-place guarantee stops being one place | Import-direction test: `compat/` may not import `api/` |

## 10. Alternatives considered

**Explicit `Field(alias=...)` on every property, no generator.** Honest and unambiguous, and about
1000 hand-written aliases across the project — each a chance to typo, and none of them checked. The
generator plus the validator gets the same guarantee mechanically. Rejected.

**A custom JSON response class that PascalCases keys on the way out.** Would work without touching
the models, and would make the models lie about their own shape: the OpenAPI document FastAPI
generates would show snake_case, which destroys the contract diff that
[ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md) chose FastAPI for. Rejected.

**Server identity in SQLite from the start.** Establishes the migration chain earlier, and fails
acceptance criterion 4 by construction. Rejected on the requirement, not on taste.

**A bootstrap API key so `/System/Info` has a working `200` path in 001.** Would let the feature
test itself end-to-end without dependency overrides, at the cost of shipping an authentication
mechanism no specification describes — and it would outlive its purpose. Rejected;
`dependency_overrides` gives the same coverage and nothing ships.

**Serving `503` from a separate readiness process or a reverse proxy.** More operationally correct
and not available: 001 has to answer `/System/Info/Public` before anything is configured, which is
precisely when no proxy is in front of it. Rejected.
