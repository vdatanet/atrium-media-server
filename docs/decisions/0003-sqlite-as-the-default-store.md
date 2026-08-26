# ADR-0003 — SQLite as the default store

**Status:** Accepted · **Date:** 2026-08-26

## Context

A media server's database is small and read-heavy. A large personal library is on the order of
10⁵–10⁶ item rows; queries are `/Items` with filters, sorts and pagination; writes are bursts during
a scan and a trickle of user data afterwards. Concurrency is a handful of clients, not a crowd.

## Decision

**SQLite in WAL mode, accessed through SQLAlchemy 2.0, migrated with Alembic.** One file inside the
data directory. No external service.

The ORM boundary is respected precisely so this can change: repositories return domain objects, not
ORM rows, and no SQLAlchemy type crosses into `domain/`.

## Consequences

- Installation is copying a directory. No service to run, secure or back up separately.
- A bug report can carry the whole database. Reproducing a user's problem means opening their file.
- Tests run against the real engine, in-memory or in a temp directory. No fixture service, no
  container, no skipped tests in CI.
- **WAL mode is required**, not optional: without it, a scan writing blocks every read, and the
  server appears to hang during library updates.
- The write path is effectively single-threaded. Scanning batches its writes; it does not interleave
  them with query traffic row by row.
- Full-text search uses FTS5, which SQLite ships. `/Search/Hints` does not need an external index.
- **Ceiling accepted:** heavy concurrent writes would need Postgres. v1 does not have them, and if
  it turns out to, that is what the repository boundary is for.

## Alternatives rejected

**PostgreSQL as the default.** Better under concurrent writes, and the wrong default: it turns
"install a media server" into "administer a database". Kept as a documented v2 option behind the
repository boundary.

**A document store.** The data is relational — items with parents, people, genres, per-user state.
Modelling that in documents means either duplication or hand-rolled joins.

**Files plus an in-memory index.** Tempting for a scanner, and it fails on the first real query:
`/Items` with filters, sorts and pagination over 10⁵ items is a database query, and writing a query
planner is not the exercise here.
