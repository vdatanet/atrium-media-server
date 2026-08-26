# ADR-0002 — Python and the runtime stack

**Status:** Accepted · **Date:** 2026-08-26

## Context

The language was given: Python, chosen for the didactic purpose. The rest of the stack was not.

The workload has a specific mix that constrains the choice:
- Almost entirely **I/O-bound** — filesystem walking, HTTP, database, subprocess supervision.
- Two CPU-bound pockets: image resizing and hashing. Both delegate to C libraries.
- Heavy **media processing that must not happen in-process** — remuxing is `ffmpeg`'s job, and
  Python's role is to build the command line and supervise the process.
- A **large, legacy, precisely-specified HTTP contract** that must be reproduced exactly and
  verified continuously.

That last point is the unusual one, and it drives the framework choice more than performance does.

## Decision

| Concern | Choice |
|---|---|
| Language | **Python 3.12+** |
| Packaging and environments | **uv** |
| HTTP | **FastAPI** on **Uvicorn** |
| Models and serialisation | **Pydantic v2** with PascalCase aliases |
| Persistence | **SQLAlchemy 2.0** + **Alembic** |
| Media inspection and remux | **`ffprobe` / `ffmpeg` as external processes** |
| Tests | **pytest**, **httpx**, **pytest-asyncio** |
| Lint and types | **ruff**, **mypy** in strict mode |

## Consequences

**FastAPI generates an OpenAPI document from the running application.** This is the deciding
property, not the ergonomics: it makes Atrium's own contract machine-readable, so it can be diffed
against Jellyfin's pinned document per path, per parameter, per schema. Contract drift becomes a
failing test rather than something noticed by a user.

**Pydantic v2's defaults point the wrong way**, and that is handled once. Field aliases give
PascalCase on the wire while keeping snake_case in Python; `populate_by_name` accepts both on input,
matching Jellyfin's case-insensitive model binder. All of it lives in a base model in `compat/`, so
a route author cannot forget — and the conformance sweep fails the build if one does.

**`ffmpeg` stays a subprocess, always.** No Python bindings, no in-process decoding. Every
invocation belongs to a supervised session with an owner, a timeout and a kill path, because
`DELETE /Videos/ActiveEncodings` has to actually stop something.

**mypy strict from the first commit**, not retrofitted. On a codebase whose whole job is getting
field types exactly right, gradual typing would leave the errors that matter most unchecked.

**Python 3.12+**, not the 3.9 that ships with macOS. `uv` provides the interpreter, so the host's
Python is irrelevant.

## Alternatives rejected

**Litestar or Starlette alone.** Both are good; neither offers the generated-OpenAPI diff that
makes contract conformance mechanical here. Starlette alone would also mean hand-rolling
validation — more code in the layer where mistakes are most expensive.

**Django or Django REST Framework.** Built for a different shape of application: a heavy ORM and
admin layer this project does not need, and awkward handling of long-lived streaming responses,
which are the core of the playback path.

**Async ORM (SQLModel, Tortoise, async SQLAlchemy).** SQLite does not benefit — it is a local file
with a global write lock, so async gains nothing and costs a harder debugging story. Database work
runs in a thread pool. Revisit only alongside [ADR-0003](0003-sqlite-as-the-default-store.md).

**`msgspec` or `orjson` models instead of Pydantic.** Faster, and the wrong trade: this project
needs validation, aliasing and schema generation far more than it needs serialisation throughput.
`orjson` as Pydantic's encoder is a reasonable later optimisation.

**Python bindings for ffmpeg (PyAV).** Would put decoding in-process, where a media file crashes
the server rather than a child process. Subprocess isolation is the point.
