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

**`cli/` is not in the drawing because it is not in the server.** It sits among the HTTP clients on
the left, ships in the same package as a second program, and reaches the server only through the
routes any client could call ([roadmap, v2](roadmap.md#v2--the-management-cli)).

### Module responsibilities

| Module | Owns | Must not |
|---|---|---|
| `api/` | Route registration, request parsing, status codes | Contain business rules or touch the database directly |
| `compat/` | Serialisation, casing, ticks, dates, GUID formatting, auth header parsing, `Range` handling, and the address a request came from — resolved inside the application from a declared list of trusted proxies (`compat/client_address.py`, 014) | Know about specific endpoints |
| `domain/` | Item types, the item model, user-data semantics, sort normalisation | Perform I/O of any kind |
| `library/` | Filesystem walking, path resolution, naming rules, identifier derivation, change detection; and since 014 the **scanner** (`library/scanner.py`) — the one worker inside the server that runs scans a route asked for, one library at a time, without the route waiting | Fetch from the network |
| `metadata/` | Provider interface, local (NFO, tags) and remote (TMDB, MusicBrainz) providers, merge and precedence, response cache | Write to the item table directly |
| `media/` | `ffprobe` inspection, `MediaSource` construction, `DeviceProfile` evaluation, direct-play and remux decisions, `ffmpeg` process lifecycle | Decide policy about who may play what |
| `users/` | Accounts, password hashing, tokens, policy, session tracking, and the first account the setup operations create and name (`users/first_account.py`, 014) | Serve HTTP |
| `images/` | Selection, resizing, disk cache, content-hash tags | Fetch remote artwork (that is `metadata/`) |
| `db/` | Schema, repositories, migrations | Leak ORM objects past the repository boundary |
| `cli/` | `atrium-admin`, the command-line client an operator sets a server up and manages its libraries with (014) — **a client of the HTTP API and not a part of the server** | Import anything from `atrium` outside `atrium.cli`, or be imported by it — both directions held by `tests/unit/test_import_directions.py` |

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
| Reference instance, **development only** | A container runtime — Docker or Podman, CLI-invoked | [0007](decisions/0007-a-container-runtime-for-the-reference-instance.md) |

The last row is not part of what a user installs. The conformance harness in `tools/` stands up a
single-use Jellyfin of the pinned version over this repository's own fixture and destroys it
([ADR-0007](decisions/0007-a-container-runtime-for-the-reference-instance.md)); no CI job has the
runtime, because no CI job may contact or start a Jellyfin, and the harness degrades without it —
an instance somebody else stood up is accepted by URL, and every comparison that needed a fixture
instance is then reported outstanding rather than skipped.

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
│   ├── cli/                     atrium-admin: a client of the API, not part of the server
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

**External processes are supervised.** Every `ffmpeg` invocation is held by the one ledger that
lists what this server is running, with an owner, a timeout and a kill path.
`DELETE /Videos/ActiveEncodings` must actually stop something. **The ledger is the lower layer and
a session is not the only owner**: a playback session owns its encoder *through* the ledger (008),
and a subtitle extraction, which has no session at all, is listed there just the same (011).
`tests/unit/test_import_directions.py` sweeps for the rule rather than trusting it.

**Configuration is a file, not an environment.** A single config file plus a data directory, so an
instance is reproducible and a bug report can carry its configuration.

## 5. Deployment shape

A single process serving HTTP, plus `ffmpeg` child processes; one data directory holding the
SQLite database, the image cache and the transcode scratch space. No message broker, no external
cache, no second service. If v1 needs one of those, the design has gone wrong somewhere earlier.

**A scan runs inside that process, since 014.** Until then a scan was code only a test or a script
called; `POST /Library/VirtualFolders` and `POST /Library/Refresh` now hand libraries to one
worker that runs `scan()` in a thread, one library at a time, and answer before it finishes
([014 plan §6.5](../specs/014-first-time-setup/plan.md#65-the-scanner)). It is still one process:
the worker is a task inside it, and `atrium-admin` is a client that asks for a scan over HTTP and
exits. **What that costs is recorded rather than solved.** A scan writes its library inside one
transaction, and while its writes and 004's refresh hold SQLite's write lock, a request that writes
— a sign-in, a progress report — waits out SQLite's default five-second busy timeout and fails, and
because those routes do their database work on the event loop an unrelated read waits as long:
5.4 s each on a scan paused mid-write, against about 35 ms of lock on the unpaused fixture library. The
operator accepted it as a residual risk on 2026-09-14
([014 plan §9](../specs/014-first-time-setup/plan.md#9-risks)), and bounding it is on
[014's owes list](../specs/014-first-time-setup/tasks.md#what-this-feature-owes-the-next-ones).

**A development machine running the conformance harness is the one place a second server appears**,
and it is a tool's dependency rather than a deployment one: 010's fixture runs start a reference
Jellyfin, compare against it, and destroy it
([ADR-0007](decisions/0007-a-container-runtime-for-the-reference-instance.md)). Nothing a user
installs gains a second process, and nothing in this section moves.
