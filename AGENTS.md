# AGENTS.md

Guidance for anyone — human or agent — making changes in this repository.

## Read first, in this order

1. **[docs/constitution.md](docs/constitution.md)** — ten principles that override everything else,
   including this file.
2. The **`spec.md`** of the feature you are touching, under [specs/](specs/).
3. **[docs/compatibility/behaviours.md](docs/compatibility/behaviours.md)** — the measured
   behaviours you must reproduce, including the defects we reproduce on purpose.

## Project phase

**Documentation.** No server code exists yet, deliberately. The workflow is
`spec.md → plan.md → tasks.md → code`, and each arrow is a review gate
([specs/README.md](specs/README.md)).

**Licence: GPL-3.0-or-later** ([ADR-0005](docs/decisions/0005-licence.md)). Every source file
carries `# SPDX-License-Identifier: GPL-3.0-or-later` from its first commit. The licence is a
backstop for an honest mistake, not permission to translate Jellyfin's code — Principle IV still
binds.

## Rules that bite immediately

**English, everywhere.** Code, comments, identifiers, commit messages, branch names, docs. No
exceptions (Principle IX).

**Documentation moves with the code, in the same commit.** A behaviour change whose spec is updated
"in a follow-up" is an incomplete change, not a fast one (Principle III).

**No technology names in `spec.md`.** No Python, no library, no table, no module, no function. Those
belong in `plan.md`. This is the rule most often broken and the one whose breach destroys the
method.

**Every claim about Jellyfin carries provenance**, inline, in one of three forms (Principle II):

| Form | Use it for |
|---|---|
| `[probe: tools/probe_x.py, Jellyfin 10.11.11, 2026-08-26]` | Measured by a script in this repository |
| `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` | Measured against a real server before this repository existed. Real, not reproducible from here — a debt, not a licence to skip writing the probe |
| `[source: path/File.cs:123 @ v10.11.11]` | Anything read from Jellyfin's code |
| `[spec: OperationId]` | Anything taken from the pinned OpenAPI document |

**Never cite a path outside this repository.** Provenance names a *version and a date*, or a file
inside Jellyfin's own tree. Private repositories, internal documents and local paths do not appear
in citations — they are neither verifiable by a reader nor ours to publish.

A claim with no provenance is marked `⚠️ UNVERIFIED` and keeps its spec in draft.

**Never copy Jellyfin's code** (Principle IV). Read it to learn *what it does*; write your own
implementation. Transliterating a C# method into Python is a licence problem and a design problem
at once.

**Zero delta** (Principle I). No endpoint, field, casing or unit that Jellyfin does not have. A good
idea that creates a delta goes in
[behaviours.md §6](docs/compatibility/behaviours.md#6-non-improvements) and is then not done.

**Dates are absolute.** `2026-08-26`, never "recently".

## Where things live

| You want to… | Go to |
|---|---|
| Understand a decision | [docs/decisions/](docs/decisions/) |
| Know if an endpoint is in scope | [docs/compatibility/surface.yaml](docs/compatibility/surface.yaml) |
| Know what a Jellyfin term means | [docs/glossary.md](docs/glossary.md) |
| Know how a behaviour gets proven | [docs/compatibility/conformance.md](docs/compatibility/conformance.md) |
| Know what comes next | [docs/roadmap.md](docs/roadmap.md) |

## Reference material

Not vendored — fetched into a git-ignored `reference/` directory:

```bash
python3 tools/fetch_reference_spec.py http://your-jellyfin:8096
python3 tools/extract_v1_surface.py --spec reference/openapi.json --print-summary
```

A local checkout of Jellyfin's source at `v10.11.11` is the second reference input. Neither is
required to work on documentation, and neither may be copied into this repository.

## Adding an endpoint

1. It has a named consumer, or a written reason under Principle VI.
2. It is in `docs/compatibility/surface.yaml`, with its consumers, feature and conformance level.
3. `tools/extract_v1_surface.py` passes.
4. It is specified in the owning feature's `spec.md`, with request, response, error paths and
   provenance.
5. Only then, code.

## Adding a compatibility claim

1. Measure it — probe script, or a cited source line with a version tag.
2. Record it in `docs/compatibility/behaviours.md` with the three required fields: what Jellyfin
   does, whether a client depends on it, what Atrium does.
3. If Atrium diverges, the entry carries the argument for why no client can observe the difference.
