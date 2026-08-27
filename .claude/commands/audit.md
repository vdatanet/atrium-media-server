---
description: Audit the claims this repository makes — provenance, documents against reality, and tests that cannot fail. Read-only.
argument-hint: "[all | provenance | documents | tests | delta | hygiene | <feature-dir> | diff]"
model: claude-fable-5
allowed-tools: Read, Glob, Grep, Bash(git log:*), Bash(git show:*), Bash(git diff:*), Bash(git status:*), Bash(grep:*), Bash(rg:*), Bash(ls:*), Bash(find:*), Bash(sed:*), Bash(head:*), Bash(tail:*), Bash(wc:*), Bash(python3 tools/extract_v1_surface.py:*)
---

# /audit — the claims, not the code

`uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` already proves
the code does what the tests say. **This audit is for the claims that gate cannot check**: claims
about Jellyfin, claims the documents make about each other, and claims the tests make about
themselves. Those are the ones that rot silently, and every real finding in this project's history
came from one of them.

Read [AGENTS.md](../../AGENTS.md) and [docs/constitution.md](../../docs/constitution.md) first if
they are not already in context. The ten principles override everything here.

**Read-only. Change nothing.** No `Edit`, no `Write`, no `git commit`, no branch, no network, no
probe run against a live server. An audit that fixes things is not an audit, and half of what
follows is only checkable because nobody has quietly tidied it first.

## Scope

`$ARGUMENTS` selects what to run. Empty means `all`.

| Argument | Scope |
|---|---|
| `all`, or empty | Every family below, whole repository |
| `provenance` / `documents` / `tests` / `delta` / `hygiene` | That family only |
| a feature directory, e.g. `003-library-configuration-and-scanning` | Every family, narrowed to that feature's three artefacts and the code and tests they name |
| `diff` | Every family, narrowed to what `git diff main...HEAD` touches |

Say at the top which scope you resolved and what you will skip because of it.

---

## Family A — Provenance (Principle II)

**The highest-yield family. Start here even under `diff`.** Every claim about Jellyfin carries one
of four forms, inline: `[probe: tools/x.py, Jellyfin <version>, <date>]`,
`[prior-probe: Jellyfin <version>, <date>]`, `[source: path/File.cs:123 @ v<version>]`,
`[spec: <what in the pinned document>]`.

**A1 — A claim about the reference with no citation.**
Sweep `specs/` and `docs/` for sentences asserting what the reference *does*: `grep -rn` for
`Jellyfin does`, `the reference`, `the reference's`, `Jellyfin `, `it defaults`, `the server
returns`. For each hit, read the surrounding paragraph. A finding is a sentence stating an
**observable behaviour of Jellyfin** with no citation in its paragraph and no `⚠️ UNVERIFIED`
marker. *This has been found twice: a claim two documents repeated and neither cited.*
Not a finding: a statement about **Atrium's** behaviour, a design decision, or a claim whose
citation is on the sentence before it in the same paragraph.

**A2 — A citation that does not resolve.**
Every `[probe: tools/<name>.py …]` names a file that exists in `tools/`. *Exclude the worked
examples*: `AGENTS.md`, `docs/README.md`, `specs/README.md` and
`docs/compatibility/reference-target.md` show the four forms with placeholder names like
`tools/probe_x.py`, and reporting those is the first false positive this check produced. Every `[source: …]` names
a path inside Jellyfin's own tree with an `@ v<version>` tag. Every version named matches the
pinned reference version — check `docs/compatibility/reference-target.md` for the pin and report
any citation naming a different one, with the reason if the document gives one.

**A3 — A citation that may have been copied from a neighbour.** *The worst class, and the least
visible.* A `[prior-probe:]` means "measured against a real server **before this repository
existed**". So a prior-probe citation introduced in a recent commit is a candidate for a citation
copied off another entry to make an unmeasured claim look measured.

```
grep -rn "prior-probe" docs/ specs/
git log --diff-filter=A --format="%ad %h %s" --date=short -S "<the claim's own words>" -- <file>
```

Report any citation whose date long precedes the commit that introduced the claim, and say what
would confirm it. Report as **high** severity: a fabricated citation is worse than no citation,
because no citation is visible and a fabricated one is not.

**A4 — `⚠️ UNVERIFIED` in a document that has left draft.**
`grep -rn "UNVERIFIED" specs/ docs/`. The constitution says an unverified claim *blocks the
specification from leaving draft status*. A spec whose frontmatter `status:` is `Accepted` or
`Implemented` and which carries a marker is a contradiction — resolve it by measuring, by dropping
the claim, or by turning it into an open question in §7, which is the mechanism for "we have not
measured this" and does not block anything. Say which of the three you think applies.
`docs/compatibility/behaviours.md` is not a specification and may carry markers.

**A5 — A behaviours entry missing one of its three fields.**
Every entry has **what Jellyfin does**, **whether a client depends on it**, and **what Atrium
does**. An entry where Atrium diverges also carries the argument for why no client can observe the
difference. Report entries missing a field.

**A6 — A citation naming somewhere unverifiable.** No private repository, no internal document, no
local absolute path (`/Users/`, `/home/`, `C:\`), no URL to something not public.

---

## Family B — The documents against reality (Principle III)

Each of these has been wrong at least once, and none of them is checked by anything.

**B1 — The plan's module list against `src/`.** `plan.md` §3 draws a tree. Compare it to
`find src -name '*.py'` both ways: a module drawn and absent, and a module present and undrawn.
*Found once: a module the plan had listed since the day it was written and which did not exist.*

**B2 — The plan's contracts against the real signatures.** `plan.md` §5 names functions and their
arguments. Read the actual `def`. *Found once: a contract naming a `mode` argument for something
that is a boolean.*

**B3 — A behavioural row nothing implements and no criterion covers.** Take each row of each spec's
behaviour tables (§3.x) and ask: which acceptance criterion in §5 covers it, and which test?
`tests/conformance/test_acceptance.py` maps criteria to tests, so the gap to look for is a row
covered by **no criterion at all**. *Found once, in a row that had been in the specification from
the day it was written and which nothing implemented.* Report the row, and whether the honest
resolution is a criterion, an implementation, or an entry in behaviours §5 as an accepted gap.

**B4 — Status fields that disagree.** Check all four against each other: each artefact's
frontmatter `status:`; the `spec_status_actual` / `plan_status_actual` gate fields; the status
table in `specs/README.md`; and AGENTS.md's "Where the project is". A gate field left at `Accepted`
under an artefact that says `Implemented` records a state that no longer exists.

**B5 — A finished task with no Done note.** In every `tasks.md`, each `[x]` task carries a
`### Done — <date>` section. AGENTS.md says those notes are the record of what the task statement
got wrong; a ticked task without one has thrown that away.

**B6 — Links and anchors that no longer resolve.** Every relative Markdown link resolves to a file
that exists, and every `#anchor` to a heading that exists in it. Slugs are lowercase, spaces to
hyphens, punctuation dropped.

**B7 — Relative dates.** `grep -rniE "\b(recently|currently|at the moment|nowadays|soon|lately|for now)\b" docs/ specs/ *.md`.
Dates are absolute (`2026-08-26`). A date that means something different next month is a date that
will be wrong next month.

---

## Family C — Tests that cannot fail

The project's own standard: a test that would pass against the bug is not a test.

**C1 — A test comparing Atrium against itself.** *The one that already happened: a specification,
an acceptance criterion and a passing test all agreed, and the test compared Atrium's output with
Atrium's output.* Look for a golden file regenerated from the server under test, an expected value
computed by the same function the test exercises, and a fixture built by the code being asserted.

**C2 — A test that asserts nothing, or asserts a tautology.** No `assert` in the body; `assert x ==
x`; `assert True`; a comparison of two calls to the same function with the same arguments; an
assertion on a value the test just set and nothing touched in between.

**C3 — Silently disabled tests.** `grep -rn "xfail\|skip" tests/`. An `xfail` without
`strict=True` becomes green and silent the moment it starts passing. A `skipif` whose condition is
always true on CI is a test that does not exist. A `pytest.skip()` inside a test body that fires on
the ordinary path is the same thing wearing a different hat.

**C4 — A safety mechanism with no removal test.** This repository's standard for a guard is that
**a test fails when the guard is deleted**. Find the guards — refusals, thresholds, checks that
abort — and find the test that proves each one bites. Report a guard that has only a test proving
it does not fire.

**C5 — A criterion whose named tests do not mention its subject.** Read `FEATURE_0NN` in
`tests/conformance/test_acceptance.py`. For each criterion, read the named tests and ask whether
they assert the criterion or merely live nearby. The map checks that the names *exist*; nothing
checks that they are the right names.

---

## Family D — Zero delta (Principle I)

**D1 — Surface.** Every route registered in `src/atrium/api/` is in
`docs/compatibility/surface.yaml`, with consumers, feature and conformance level.
`python3 tools/extract_v1_surface.py --print-summary` checks the file's internal consistency; what
it cannot check is a route in the code that nobody added to the file.

**D2 — A field, casing or unit the reference does not have.** Serialised property names, status
codes, header names, duration units. A good idea that creates a delta belongs in
[behaviours §6](../../docs/compatibility/behaviours.md) as a non-improvement and is then not done —
so an improvement in the code that is not recorded there is a finding, however sensible it is.

**D3 — A deliberate divergence with no argument.** Where Atrium differs on purpose, behaviours
carries the argument for why no client can observe the difference. Report a divergence whose entry
asserts that nobody can see it without saying why.

---

## Family E — Hygiene that bites

**E1 — SPDX.** Every source file carries `# SPDX-License-Identifier: GPL-3.0-or-later`.
`grep -rLn "SPDX-License-Identifier" --include='*.py' src tests tools`

**E2 — English everywhere** (Principle IX): code, comments, identifiers, docs, commit subjects.
`git log --format="%s%n%b" -n 50` for the recent ones.

**E3 — Secrets and paths.** `.env` is not tracked (`git ls-files | grep -i env`), no credential
literal in `src/`, `tools/` or `tests/`, no local absolute path anywhere outside a scratch
directory, and nothing under `reference/` committed.

**E4 — Commits on `main`.** `git log main --first-parent --format="%h %s" -n 30`: every commit
should be a merge of a reviewed pull request. A direct commit has happened once here and was caught
by luck.

---

## What is **not** a finding

Reporting these makes the real findings harder to see, which is the only way this audit fails.

- **A defect reproduced on purpose.** [behaviours §3](../../docs/compatibility/behaviours.md) lists
  Jellyfin defects Atrium reproduces deliberately. Never report one as a bug.
- **A non-improvement.** behaviours §6 records good ideas refused because they create a delta.
  Refusing them is the policy, not an oversight.
- **An accepted gap.** behaviours §5 entries name their closing mechanism. A gap with a mechanism
  is a decision.
- **An open question with a written reason.** `spec.md` §7. A question that says why it is open and
  what would answer it is doing its job.
- **Prose style, length, tone or comment density.** The documentation here is deliberately
  discursive and the comments deliberately explain *why*. Do not suggest trimming.
- **Anything ruff, mypy or pytest already catches.** Formatting, typing, unused imports, failures.
- **A `[prior-probe:]` debt on its own.** It is a recorded debt. It is only a finding under A3.
- **Test coverage as a number.** Report a specific unasserted claim or say nothing.

## Evidence

Every finding carries, in this order:

1. **severity** — `high` (a false claim, a fabricated citation, a test that cannot fail, a delta),
   `medium` (a document disagreeing with reality), `low` (hygiene, a stale link);
2. **`path:line`**, clickable;
3. **the text itself, quoted** — not paraphrased. A paraphrase is how a finding turns out on
   inspection to have been about something else;
4. **which principle or rule it breaches**, by number or name;
5. **the smallest thing that would resolve it** — one sentence. Do not write the fix.

If you are not sure something is a finding, say so in one clause and report it anyway under the
severity you think fits. **Do not invent a finding to have something to report** — a clean family
is a result, and the value of this audit is that its findings are believed.

## Output

```
scope: <what was audited, and what was skipped>

findings: <n> high, <n> medium, <n> low

<each finding, in severity order>

checked and clean: <the checks that ran and found nothing, by name — A1, A2, …>
not run: <checks skipped, and why — out of scope, needs a live server, needs a Jellyfin checkout>
```

Finish with **one paragraph** naming the single finding you would act on first and why. If there
are none, say that plainly in one sentence and stop — no summary of how thorough you were.
