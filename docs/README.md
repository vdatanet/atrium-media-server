# Documentation map

This project is documented before it is built. Everything here exists to answer one of three
questions: *what are we not allowed to do*, *what exactly is the target*, and *what are we
building next*.

## Reading order

For someone arriving cold:

1. **[constitution.md](constitution.md)** — the ten principles. Everything else is downstream of
   these. Ten minutes, and they explain most of the decisions you will see later.
2. **[roadmap.md](roadmap.md)** — the scope boundary of v1 and the order of work.
3. **[compatibility/reference-target.md](compatibility/reference-target.md)** — what "compatible"
   means concretely, which Jellyfin version is pinned, and which sources are authoritative.
4. **[compatibility/api-surface-v1.md](compatibility/api-surface-v1.md)** — the endpoint table.
5. **[architecture.md](architecture.md)** — the shape of the system and the runtime stack.
6. **[specs/](../specs/)** — the feature specifications, in numbered order.

For someone about to write code, the mandatory pre-read is: the constitution, the spec of the
feature, and [compatibility/behaviours.md](compatibility/behaviours.md).

## The tree

```
docs/
├── constitution.md              Non-negotiable principles
├── roadmap.md                   v1 scope, milestones, explicit non-goals
├── architecture.md              Module decomposition and runtime stack
├── glossary.md                  The MediaBrowser/Jellyfin vocabulary, defined once
├── audits/
│   └── YYYY-MM-DD.md            One audit each: findings kept as open debts, ticked by the pull
│                                request that resolves them, in the same commit
├── compatibility/
│   ├── reference-target.md      Pinned version, sources of truth, what parity means
│   ├── api-surface-v1.md        The endpoints v1 serves, with provenance per endpoint
│   ├── surface.yaml             The same set, machine-readable and CI-validated
│   ├── client-atrium-tvos.md    One real client's requirements, traced against v1
│   ├── behaviours.md            Measured Jellyfin behaviours, quirks and defects to replicate
│   └── conformance.md           How parity is proven, including differential testing
└── decisions/
    ├── README.md                Index of architecture decision records
    └── NNNN-*.md                One decision each, immutable once accepted
```

## How SDD is practised here

The workflow, the directory conventions and the templates live in **[../specs/README.md](../specs/README.md)**.

The short version: each feature gets a numbered directory containing `spec.md` (what and why),
`plan.md` (how) and `tasks.md` (verifiable steps). A spec is written and reviewed *before* its
plan; a plan is written and reviewed *before* its tasks; code comes last. Principle III forbids
short-circuiting that order.

## Conventions

**Every compatibility claim carries its provenance.** Inline, in one of these forms:

- `[probe: tools/probe_x.py, Jellyfin 10.11.11, 2026-08-26]` — measured against a running server by
  a script in this repository, which anyone can re-run.
- `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` — measured against a running server *before this
  repository existed*, carried forward with its version and date. Real, but not reproducible from
  here; each one is a debt to be discharged by writing the equivalent probe script.
- `[source: Emby.Server.Implementations/Library/LibraryManager.cs:636 @ v10.11.11]` — read from
  Jellyfin's code, with the version tag.
- `[spec: GetItems]` — taken from the pinned OpenAPI document, by operation id.

A claim with no provenance is marked `⚠️ UNVERIFIED` and keeps its specification in draft
(Principle II).

**Dates are absolute.** `2026-08-26`, never "last week" or "recently".

**Documents are dated at the top** with a `Last verified` line where they contain measured claims,
so a reader knows how stale the measurement is.
