# Architecture

> **This document describes HOW.** Per Principle III, technology choices belong in plans, not in
> specifications. This file is the project-level plan that individual feature plans inherit from;
> the reasoning behind each choice is in [decisions/](decisions/).

## 1. Shape of the system

```
                    ┌──────────────────────────────────────────┐
   HTTP clients ───▶│  api/         routes, one module per      │
   (unmodified      │               Jellyfin controller         │
    Jellyfin        └────────────────────┬─────────────────────┘
    clients)                             │
                    ┌────────────────────▼─────────────────────┐
                    │  compat/      the wire contract:          │
                    │               PascalCase, ticks, GUID     │
                    │               format, .NET dates, auth    │
                    │               header parsing              │
                    └────────────────────┬─────────────────────┘
                                         │
        ┌────────────────┬───────────────┼───────────────┬────────────────┐
        │                │               │               │                │
   ┌────▼─────┐  ┌───────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐  ┌──────▼─────┐
   │ library/ │  │  metadata/   │  │  media/    │  │  users/    │  │  images/   │
   │ scan,    │  │  providers,  │  │  probe,    │  │  auth,     │  │  resize,   │
   │ resolve, │  │  merge,      │  │  profiles, │  │  policy,   │  │  cache,    │
   │ identify │  │  cache       │  │  delivery  │  │  sessions  │  │  tags      │
   └────┬─────┘  └───────┬──────┘  └─────┬──────┘  └─────┬──────┘  └──────┬─────┘
        └────────────────┴───────────────┼───────────────┴────────────────┘
                                    ┌────▼─────┐
                                    │  domain/ │   items, types, user data
                                    └────┬─────┘   — no I/O, no HTTP
                                    ┌────▼─────┐
                                    │   db/    │   models, repositories, migrations
                                    └──────────┘
```

**The rule that keeps this honest:** `domain/` knows nothing about HTTP, and `api/` knows nothing
about SQL. `compat/` is the only place allowed to care that the wire format is Jellyfin's — which
is what makes the PascalCase sweep in [conformance](compatibility/conformance.md) enforceable
rather than aspirational.

### Module responsibilities

| Module | Owns | Must not |
|---|---|---|
| `api/` | Route registration, request parsing, status codes | Contain business rules or touch the database directly |
| `compat/` | Serialisation, casing, ticks, dates, GUID formatting, auth header parsing, `Range` handling | Know about specific endpoints |
| `domain/` | Item types, the item model, user-data semantics, sort normalisation | Perform I/O of any kind |
| `library/` | Filesystem walking, path resolution, naming rules, identifier derivation, change detection | Fetch from the network |
| `metadata/` | Provider interface, local (NFO, tags) and remote (TMDB, MusicBrainz) providers, merge and precedence, response cache | Write to the item table directly |
| `media/` | `ffprobe` inspection, `MediaSource` construction, `DeviceProfile` evaluation, direct-play and remux decisions, `ffmpeg` process lifecycle | Decide policy about who may play what |
| `users/` | Accounts, password hashing, tokens, policy, session tracking | Serve HTTP |
| `images/` | Selection, resizing, disk cache, content-hash tags | Fetch remote artwork (that is `metadata/`) |
| `db/` | Schema, repositories, migrations | Leak ORM objects past the repository boundary |

## 2. Runtime stack

| Concern | Choice | ADR |
|---|---|---|
| Language | Python 3.12+ | [0002](decisions/0002-python-and-the-runtime-stack.md) |
| Packaging / envs | `uv` | [0002](decisions/0002-python-and-the-runtime-stack.md) |
| HTTP framework | FastAPI on Uvicorn | [0002](decisions/0002-python-and-the-runtime-stack.md) |
| Models / serialisation | Pydantic v2, PascalCase aliases | [0002](decisions/0002-python-and-the-runtime-stack.md) |
| Persistence | SQLAlchemy 2.0 + Alembic, SQLite (WAL) | [0003](decisions/0003-sqlite-as-the-default-store.md) |
| Media inspection and remux | `ffprobe` / `ffmpeg`, as external processes | [0002](decisions/0002-python-and-the-runtime-stack.md) |
| Tests | pytest, httpx, pytest-asyncio | — |
| Lint / types | ruff, mypy (strict) | — |

### Why FastAPI specifically

Beyond the obvious (async, mature, well understood), one property decides it: **FastAPI generates
an OpenAPI document from the running application.** That makes a check possible that is otherwise
laborious — diffing Atrium's own generated contract against Jellyfin's pinned one, per path, per
parameter, per response schema. A framework without that would leave contract drift to be caught by
hand.

The cost is that FastAPI's defaults point the wrong way for this project: snake_case fields,
`camelCase` conventions in examples, and Pydantic's own JSON encoders. `compat/` exists to invert
those defaults once, centrally, instead of at 55 call sites.

## 3. Repository layout

```
atrium-media-server/
├── docs/                        See docs/README.md
├── specs/                       Feature specifications
├── src/atrium/
│   ├── api/
│   ├── compat/
│   ├── domain/
│   ├── library/
│   ├── metadata/
│   ├── media/
│   ├── users/
│   ├── images/
│   ├── db/
│   ├── config/
│   └── server.py
├── tests/
│   ├── conformance/             L0 and L1
│   ├── golden/                  Checked-in response bytes
│   ├── fixtures/                The fixture library (metadata only)
│   └── unit/
├── tools/                       Probe scripts, spec fetcher, differential harness
└── reference/                   Git-ignored: fetched OpenAPI, differential reports
```

## 4. Cross-cutting decisions

These bind every feature and are stated once here rather than repeated in nine plans.

**Ticks are the internal unit.** Durations and positions are stored and passed as .NET ticks
(100 ns). Conversion from a source unit happens exactly once, at ingestion. No function signature
takes "seconds" unless its name says so.

**Identifiers are derived, never allocated.** No autoincrement column reaches a client. See
[behaviours §1.4](compatibility/behaviours.md#14-item-identifiers-are-32-lowercase-hex-characters).

**Serialisation is opt-out, not opt-in.** The base response model emits PascalCase; producing a
non-conforming body requires a deliberate override, which the conformance sweep then fails.

**External processes are supervised.** Every `ffmpeg` invocation belongs to a tracked session with
an owner, a timeout and a kill path. `DELETE /Videos/ActiveEncodings` must actually stop something.

**Configuration is a file, not an environment.** A single config file plus a data directory, so an
instance is reproducible and a bug report can carry its configuration.

## 5. Deployment shape

A single process serving HTTP, plus `ffmpeg` child processes; one data directory holding the
SQLite database, the image cache and the transcode scratch space. No message broker, no external
cache, no second service. If v1 needs one of those, the design has gone wrong somewhere earlier.
