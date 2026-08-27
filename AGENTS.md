# AGENTS.md

Guidance for anyone — human or agent — making changes in this repository.

## Read first, in this order

1. **[docs/constitution.md](docs/constitution.md)** — ten principles that override everything else,
   including this file.
2. The **`spec.md`** of the feature you are touching, under [specs/](specs/).
3. **[docs/compatibility/behaviours.md](docs/compatibility/behaviours.md)** — the measured
   behaviours you must reproduce, including the defects we reproduce on purpose.

## Where the project is

**Features 001, 002, 003 and 004 are implemented. 005 has passed all three gates** — spec, plan
and [task list](specs/005-item-query-api/tasks.md) accepted — **so the next thing is code:
005 T1**, the item-shapes probe. The other five features are specified only, their specs still
drafts.

**004 owes 005 four things**, written down in
[004's tasks](specs/004-metadata-resolution/tasks.md#what-this-feature-owes-the-next-ones) rather
than here so they cannot go stale: `name_folded` on every item it touched, the pattern-driven
indexes, `ImageTags` emittable from `item_images` alone, and the artist **credit** distinction —
`/Artists` versus `/Artists/AlbumArtists` is that column and nothing else.

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

[CI](.github/workflows/ci.yml) runs that same gate on every pull request, plus the surface and
property-name checks, the suite on the oldest and newest supported Python, and the `tools/` scripts
on the 3.9 floor they promise to run on. **No job contacts a Jellyfin server**, and the suite fails
any test that opens a TCP connection — so a probe belongs in `tools/`, run by hand, never in the
suite.

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
| T18 | Add a CI workflow | Two of the four checks it was to run could not run in CI at all, and the suite's "no network" was a claim with nothing enforcing it |
| T19 | Serialise names differently | Writing one constructor the obvious way — `*args, **kwargs` — silently broke OpenAPI generation, because the framework *inspects that signature* |
| 002 T1 | Answer two open questions | A **fifth** authentication mechanism nothing had listed, and a disabled account refused with `403` where the spec argued for `401` on purpose |
| 002 T7 | Parse a header leniently | Three of the plan's four claims about the grammar were wrong, including the one leniency both documents named |
| 002 T11 | Serve a login screen | `/Users/Public` sends every user's full policy and configuration to a caller with no token — the opposite of the acceptance criterion |
| 002 T14 | Assert no password is logged | The password never leaked; a library logged the password **hash** and another logged the token, both at `INFO`, from one `basicConfig` call |
| 003 tasks | Review a nineteen-item list | Two of the findings were items **missing** from it: no task measured the two questions the spec names probes for, and no task extended the acceptance map — which a test would have failed the day 003 was marked `Implemented` |
| 003 T18 | Store a signal and skip unchanged files | Skipping the read was the easy half. An unexamined music file resolves from its *path*, which hangs it under an album named after its directory — so the second scan of every music library would have silently doubled its albums |
| 003 T19 | Write one test | The claim it exists to prove — "the reference derives ids from the absolute path" — was asserted in two documents and cited in neither. Measured at last: 448 of 448 live ids reproduce from the path alone, **containers included** |
| 003 T20 | Report two things with their reasons | They cannot be one list. One file produced no item and the other produced one. And plan §7 named a failure that does not happen: a `chmod 000` file stats fine, so nothing in 003 ever notices it |
| 003 T21 | Write the acceptance map | A specification row nobody had implemented and no criterion covered — "directory emptied → remove the container item" — which had been there since the spec was written |
| 004–005 gate | Accept two specs, write two plans | The **accepted** 005 spec's error path for enum values does not exist — an unrecognised token is ignored, not `400` — and the reference's own artist-sort paging drops and duplicates rows, which turned "ordering is total" from assumed parity into a documented divergence |
| 004 T5 | Parse a sidecar | Plan §6.2 said the reference does **not** split a genre on ` / ` and cited the parser that does. Not splitting would have given Atrium a genre no reference server has — on a file both of them read, which is the exact disagreement the sentence was written to prevent |
| 004 T10 | Wire the pieces together | The scan and the refresh were **fighting over one column**: every rescan re-derived a name from the filename, every refresh restored the sidecar's, for ever, with every item reported as updated. And the path-derived name turned out to be merged **last**, not third — without which AC-1 is unreachable |
| 004 T15 | Generate a culture table | Plan §6.9's source was wrong three ways. The registry it named has 508 rows to the reference's 192, lists 24 languages' codes in the opposite order, and **cannot produce eight rows the reference has at all** |

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
