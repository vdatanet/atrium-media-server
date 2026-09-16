---
feature: 015-user-administration
title: User administration — tasks
status: Draft
created: 2026-09-16
updated: 2026-09-16
plan_status_required: Accepted
---

# 015 — Tasks

Ordered. Each task is a reviewable change on its own, and states how you know it worked.

## What the gate changed

**Five things, and every one is a sentence of the plan read against the modules it names.** Each is
amended into [plan.md](plan.md) in the same change as this list.

### 1. The administrator's writes can be `L3` without touching anybody's server, and the mechanism already exists

OQ-2 made four of the five routes `L3`, which means the differential asks them of **both** servers:
`test_the_l3_rows_name_both_seats` asserts `{"administrator", "restricted"} <= seats` for every
`level: L3` row (`tests/unit/test_allowlist.py:730-743`). But three of the four are
administrator-only **writes about accounts**, and `request-cases.yaml`'s own rule is *"nothing here
is a write to an account this project does not own"* — the administrator's seat is whatever `.env`
points at, which is an operator's own account. 014 escaped this by naming `restricted` alone, since
its five setup writes are refusals to a non-administrator; **that escape is not available here**,
because a row whose cases name one seat cannot be `L3` under the test above.

**The escape that is available was built for this argument and is already used twice.**
`NEEDS_THE_INSTANCE = ("fixture", "rescan", "wait")` in `tools/differential.py:1205`, whose
docstring says why `rescan` and `wait` are in it: *"a rescan is a write to a library, and the
paused-session reading is a write held open for ten minutes, which is the one thing an operator's
server must not be asked for."* A case with `needs: [fixture]` is askable only against the
single-use instance the run stands up and destroys. So **the administrator-seat cases for
`POST /Users/New`, `POST /Users/{userId}/Policy` and `DELETE /Users/{userId}` carry
`needs: [fixture]`**, the restricted-seat cases are the refusals and carry nothing, and the file's
rule holds without being widened. `GET /Users` is a read and needs none of this.

**If that is wrong, the other answer is to reverse OQ-2** and make the four `L2` with `L3` owed to
the same change 014 owes it to. It is written here rather than chosen quietly because it is the one
finding that would change the shape of T1 and T9.

### 2. Two counted assertions move, and they are in different files

`test_every_surface_endpoint_has_at_least_one_case` asserts the surface has exactly **65** rows and
that every one has a case (`tests/unit/test_allowlist.py:720`); `test_the_l3_rows_name_both_seats`
asserts exactly **10** `L3` rows (`:737`). Five rows and four `L3`s make them **70** and **14**, in
T1, or T1 is red. Plan §8 named neither.

### 3. Tokens are not sessions, and the plan said the wrong repository

Plan §6.4 and §6.6 revoke through `SessionRepository.remove_for_user`. There is no such method and
there should not be: `SessionRepository` removes by session and by device (`repositories.py:500,
503`), and the thing a revocation revokes lives in **`TokenRepository`**, which already has
`for_user(user_id)`, `revoke(token_sha256)` and `revoke_device(user_id, device_id)` (`:377-394`).
*"Every token this account holds, except the caller's own"* is a new method there and nowhere else.
Plan §3, §6.4 and §6.6 amended.

### 4. `set_policy` already exists, and what is missing is smaller than the plan said

`UserRepository.set_policy(user_id, columns, extra)` is at `repositories.py:306`. The plan's
`replace_policy` is that call plus `set_library_access`, which also exists — so T5 adds a route and
no repository method at all, and the plan's module table overstated it. Plan §3 amended.

### 5. The disclosure rule moves three goldens, and the fourth is a defect it must not absorb

`Users.Public.json`, `Users.ById.json` and `Users.Me.json` all carry a 13-property `Policy` today;
the first two lose it entirely under §3.1.1 and the third keeps it. **The fourth, `Users.AuthenticateByName.json`,
is the finding**: it carries a `Policy` whose `EnabledFolders` is `[]` where the same account's
other three roads answer `["aaaa…"]`, because `api/users.py:159` calls `to_wire(result.user, state)`
with **no access argument at all**. So this server already tells a client two different things about
one account's library access depending on which road it asks.

T3 has to touch that line — `to_wire` gains a required caller — and **it passes the caller and not
the access**, leaving the difference exactly where it is. It is 002's, it is not this feature's
subject, and absorbing it would change an implemented feature's wire output inside a task about
something else (012's rule, and 012's own zero-length-file finding is the precedent). It goes to
§*What this feature owes the next ones* and to 002.

---

## T1 — Five rows in the surface, their cases, and nothing served

**What changes.** `docs/compatibility/surface.yaml` gains the five rows — four `L3`, one `L2` —
with `consumers: [atrium-admin]`. `docs/compatibility/request-cases.yaml` gains their cases: one
per row at minimum, both seats for the four `L3` rows, and the administrator's three writing cases
carry `needs: [fixture]` (gate finding 1). `docs/compatibility/api-surface-v1.md` gains the section
they belong to. The two counted assertions move to 70 and 14 (gate finding 2). `INTERIM_015` is
created empty beside `IMPLEMENTED_FEATURES` in `tests/conformance/test_routes.py`, the pattern 009
and 014 both used.

**No route is served by this task.**

**How you know it worked.** `uv run python tools/extract_v1_surface.py` passes;
`uv run pytest tests/unit/test_allowlist.py tests/conformance/test_routes.py` passes with the two
new counts; and the whole suite is green — the L2 coverage hook counts served rows only since
2026-09-14, so five declared-and-unserved rows do not fail it.

## T2 — The policy document as a declared model, and the filter both ways

**What changes.** `users/policy.py` gains `DECLARED` — the 44 property names of the pinned
`UserPolicy` `[spec: UserPolicy]` — and both `split` and `assemble` filter to it (plan §4). A new
`api/users.py::UserPolicyDto` declares all 44 with the reference's measured defaults, two of them
required. No route uses it yet.

**How you know it worked.** `tests/unit/test_user_policy.py`: a document carrying a property outside
`DECLARED` round-trips **without** it; an account whose stored blob holds one stops answering it
without the row being touched; `split(assemble(x)) == x` still holds for the 42; and the model
refuses a body missing either provider identifier while accepting one missing any other property,
which arrives carrying the measured default.

## T3 — The disclosure rule, on all three roads at once

**What changes.** `to_wire` gains a **required** caller parameter (`User | None`), `UserDto`'s two
mappings become nullable, and the four call sites pass what plan §6.1's table says. `Users.Public`
and `Users.ById` goldens lose `Configuration` and `Policy`; `Users.Me` keeps them.
`Users.AuthenticateByName` passes the caller and **not** the access (gate finding 5).

**How you know it worked.** `tests/conformance/test_user_disclosure.py` asserts spec §3.1.1's five
rows — every combination of caller and subject on the three roads — and the golden test passes with
the three moved files. A test asserts that `to_wire` has no default for the caller, so a fifth road
cannot forget it.

## T4 — `GET /Users` and `POST /Users/New`

**What changes.** Two routes. The creation's name validation is the reference's expression, its
duplicate check is `by_name` inside the transaction with the unique index behind it, and both
refusals are the same `controller_error(400)` (spec §3.2.1). Both paths join `INTERIM_015`.

**How you know it worked.** `tests/conformance/test_user_administration.py` covers criteria 1, 3, 4
and 5: the created document, the four refusal envelopes including the `415`, the ordering, the two
filters, and that no refusal leaves an account. Every added path is requested by a test in this
change, or the L2 coverage hook fails the run.

## T5 — `POST /Users/{userId}/Policy`

**What changes.** One route: the all-zeros guard, the `404`, the two reachable guards with their
JSON-encoded sentences, `set_policy` plus `set_library_access`, and the token revocation on a
disabling that succeeds (gate findings 3 and 4). The third guard is not written, and §3.3 says why.

**How you know it worked.** Criteria 7, 8, 15, 16 and 19: each refusal by status and body, a policy
round-tripped whole, each of the fourteen enforced properties changing what the account can do
**asserted at the HTTP boundary**, and one of the 28 carried and inert.

## T6 — `POST /Users/Password`

**What changes.** One route and the three paths of plan §6.5, the asymmetry included.

**How you know it worked.** Criteria 9, 10 and 11: an administrator changing another's without the
current one, a wrong current password refused `403` with its body, the reset leaving an account that
signs in with none, and the two requests that differ only in a query parameter naming the caller's
own account answering `403` and `204`.

## T7 — `DELETE /Users/{userId}`

**What changes.** One route, in plan §6.6's order: the guard, then the revocations, then the private
playlists, then the account. `TokenRepository` gains the revoke-all method (gate finding 3);
`PlaylistRepository` gains `owned_by(user_id, public=False)`; `UserRepository` gains `remove` and
`count_administrators`.

**How you know it worked.** Criteria 12 and 20: the tokens gone, the private playlist gone, the
public one still readable by an administrator, the second deletion `404` — and, for the divergence,
a refused deletion of the last administrator after which **the caller's token still works and the
playlists are still there**, which is the assertion behaviours §3.34 exists for.

## T8 — The client

**What changes.** Five subcommands under `user` in `cli/commands.py` and `cli/client.py`, per plan
§6.7: `policy` reads the account's policy back and posts it whole, `--libraries` resolves names
through `GET /Library/VirtualFolders`, and `add` lists the accounts first so it can name which
refusal the six words meant.

**How you know it worked.** `tests/cli/test_user_commands.py`, recording every request the client
makes against a fake server, as 014's do. Criterion 13.

## T9 — The harness stops building its seat by hand

**What changes.** `tools/differential.py` creates the restricted seat through `POST /Users/New`,
restricts it through `POST /Users/{userId}/Policy` and destroys it through `DELETE /Users/{userId}`
when the server under test serves them, instead of refusing with *"Provision the seat yourself and
hand it in"* (`differential.py:298-307`). `tools/README.md` steps 3 and 4 lose the paragraphs that
say it cannot. `docs/compatibility/allowlist.yaml` gains the entries for the withheld
`Policy` and `Configuration` on the three read routes, citing behaviours §3.5 and §3.22.

**How you know it worked.** Criteria 14 and 18: the harness's own tests, and a `--fixture` run
whose report shows the seat created and destroyed and the withholding excused rather than reported
as a difference. **The run is the operator's to take**, like every other reading in this repository.

## T10 — What this feature owes other documents

**What changes.** behaviours §3.5, §3.22, §3.33 and §3.34 gain their *implemented* dates and the
tests that assert them. 002's spec §3.4, §3.7 and AC-6 are amended for the disclosure rule, and its
§3.5 for the unknown-property correction — **in this change, because the code is in it**.
`api-surface-v1.md`, the roadmap's v2 section and `specs/README.md` are brought level.

**How you know it worked.** Every behaviours entry this feature touched names a test that exists;
`tests/unit/test_allowlist.py` passes; and no document says 015 is unimplemented.

## T11 — Close it

**What changes.** `INTERIM_015` is deleted and 015 joins `IMPLEMENTED_FEATURES`; `FEATURE_015`
maps all twenty criteria to tests by name; the three documents move to `Implemented`.

**How you know it worked.** The whole suite green with the interim list gone, `test_acceptance.py`
naming twenty criteria, and the definition of done below ticked line by line — including the one
line that is not a task.

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all **twenty** —
      has a passing test, by name, in `FEATURE_015`.
- [ ] The five routes are in `docs/compatibility/surface.yaml` at the levels §6 declares, served,
      and counted by `test_routes.py` against the file.
- [ ] The four `L3` rows have cases from both seats, and the three that write carry
      `needs: [fixture]`.
- [ ] **A `--fixture` differential run builds its restricted seat through this feature's routes**
      and reports the withheld `Policy` and `Configuration` as declared rather than as differences —
      the operator's run, recorded here with its date.
- [ ] Anything learned during implementation is back in `spec.md` and `plan.md`, in the same change.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

- **`Users.AuthenticateByName` answers a different `EnabledFolders` than the other three roads**
  (gate finding 5), because `api/users.py:159` builds that user object with no library access. It is
  002's, it is measured against nothing yet, and T3 leaves it exactly as it found it.
- **The third guard of spec §3.3** — *"there must be at least one enabled user"* — is unreachable
  from a running start and has no code and no test. A server that could reach it is one whose only
  enabled account is not an administrator, which the second guard prevents.
- **`POST /Users/Password`'s `404`** is the one refusal of these five routes the measurement gate
  did not read.
- **Concurrent demotion and deletion can leave a server with no administrator** (plan §9): both
  paths read the count in their own transaction and WAL does not serialise them.
- **`GET /Users`'s ordering is SQLite's, not .NET's**, and the two are not guaranteed to agree on
  names differing only in case or accent.
- **014's owed L3 change is still owed.** This feature pays 010's *"the restricted seat is built by
  hand"* and does not touch the six first-time-setup rows.
