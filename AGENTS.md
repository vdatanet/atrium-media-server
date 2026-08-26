# AGENTS.md

Guidance for anyone — human or agent — making changes in this repository.

## Read first, in this order

1. **[docs/constitution.md](docs/constitution.md)** — ten principles that override everything else,
   including this file.
2. The **`spec.md`** of the feature you are touching, under [specs/](specs/).
3. **[docs/compatibility/behaviours.md](docs/compatibility/behaviours.md)** — the measured
   behaviours you must reproduce, including the defects we reproduce on purpose.

## Where the project is

**Implementing feature 001.** The specification phase is over for the dependency root: 001, 002 and
003 are specified, planned and broken into tasks; the other seven features are specified only.

**The state is in the files, not here**, so it cannot go stale:

| Question | Read |
|---|---|
| Which features have a spec, a plan, tasks? | [`specs/README.md`](specs/README.md) — the status table |
| Which tasks are done? | The feature's `tasks.md`. Finished ones are `[x]` and carry a **Done** note saying what the task got wrong |
| What is next? | The first unticked task in the lowest-numbered feature |

The **Done** notes are worth reading before starting the next task. Most of them record something
the task statement or the plan asserted that turned out to be false, and the same class of mistake
tends to recur.

## The working rhythm

One task, one branch, one pull request, reviewed and merged before the next begins.

```
git checkout main && git pull && git checkout -b feat/001-tNN-short-name
# … the task …
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
git commit && git push -u origin <branch> && gh pr create --base main
```

**Never commit to `main`.** It has happened once in this project, caught only because opening the
pull request failed with *"No commits between main and …"*. Merge with `--delete-branch`: a stacked
pull request is only retargeted when its base branch is deleted, and three of them once merged into
each other instead of into `main` because the branches were kept.

Every gate is a real gate. A plan does not start until its spec is `Accepted`; tasks do not start
until the plan is; code does not start until the tasks are (Principle III).

## The habit that has produced every real finding

**Measure the reference before implementing anything, even when the task looks trivial.**

Every task since T4 has found something the specification had wrong, and none of them were found by
reasoning:

| Task | Looked like | Turned out |
|---|---|---|
| T11 | Write one `Server` header | Three headers; two of them unknown to the project |
| T13 | Raise a 401 | Two error shapes, split by *where* the refusal happens |
| T14 | Serialise seven fields | Nulls are omitted globally by one setting — resolving an "UNVERIFIED" entry that was waiting for a whole harness |
| T16 | Check in three response bodies | One of the three declared content types serialises differently. The spec, an acceptance criterion and a *passing test* all said otherwise — the test compared Atrium against itself |
| T17 | Assert the routes are registered | Four routing differences, including one the documentation had described as done since T13: an unmatched path was answering `{"detail": "Not Found"}` |

The tools for it are in [`tools/`](tools/): `.env` carries the credentials, the probes answer one
question each, and a plain `urllib` request answers the rest.

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

**Verify that an edit landed.** A `pyproject.toml` change once matched nothing and reported success
because another tool had rewritten the block underneath it. A scripted edit that cannot fail is a
scripted edit that will silently not happen.

## Where things live

| You want to… | Go to |
|---|---|
| Understand a decision | [docs/decisions/](docs/decisions/) |
| Know if an endpoint is in scope | [docs/compatibility/surface.yaml](docs/compatibility/surface.yaml) |
| Know what a Jellyfin term means | [docs/glossary.md](docs/glossary.md) |
| Know how a behaviour gets proven | [docs/compatibility/conformance.md](docs/compatibility/conformance.md) |
| Know what comes next | [docs/roadmap.md](docs/roadmap.md) |

## Contributing a fix upstream

Sometimes the right response to a reference defect is to fix it in the reference. Two things make
that harder than it looks, and both are worth knowing before starting:

- **Jellyfin does not accept contributions authored with AI assistance**, and every commit in this
  repository carries a `Co-Authored-By` trailer. An upstream patch has to be a separate,
  hand-authored artefact — not a cherry-pick from here.
- **An issue is often the better artefact anyway.** A hand-written issue describing the behaviour,
  proposing no code, gets the defect judged on its merits. That judgement is what
  [behaviours §3.0.1](docs/compatibility/behaviours.md#301-the-tie-breaks) tie-break 2 needs, and a
  closed pull request does not supply it.

Either way, **upstream is not a dependency**. A defect is decided here, on the evidence available
here, using the procedure in
[behaviours §3.0](docs/compatibility/behaviours.md#30-how-the-decision-is-made). Waiting for
upstream is not a plan.

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
