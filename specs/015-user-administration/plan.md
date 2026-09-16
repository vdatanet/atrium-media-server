---
feature: 015-user-administration
title: User administration — implementation plan
status: Draft
created: 2026-09-16
updated: 2026-09-16
spec: spec.md
amended: 2026-09-16 at the tasks gate - five findings: the administrator's L3 writing cases carry needs: [fixture], which is the argument rescan and wait already carry; two counted assertions move with the rows; a revocation is TokenRepository's and not SessionRepository's; set_policy and set_library_access already exist, so T5 adds no repository method; and to_wire's fourth call site carries a defect this feature leaves where it found it
---

# 015 — User administration: plan

> **This document describes HOW.** Technology names, module boundaries, data model, algorithms.
> What and why is [`spec.md`](spec.md); a decision restated here that contradicts
> [../../docs/architecture.md](../../docs/architecture.md) or an [ADR](../../docs/decisions/)
> needs an ADR of its own.

## 1. Approach

**Almost everything this feature needs already exists, which is the opposite of 014.** The account
store has every column, blob and join table an account needs (002); the policy document already has
a reader and a writer that take it apart and put it back (`users/policy.py`); the four refusal
shapes are built and measured (002, 009); elevation is a dependency (`require_administrator`, 009);
and a client that speaks HTTP and nothing else exists with its own recorded tests (014). **What does
not exist is any route that writes an account, and nothing in this repository has ever deleted
one.**

So the feature is five things, and only two of them are new machinery:

1. **Five routes** in the router 002 already owns, each a thin translation onto repository calls
   (§5, §6.2 to §6.6).
2. **A policy document as a declared model.** The gate measured that the reference's body is a
   *replacement*: an omitted property takes the type's default, and two of them are required
   (spec §3.3). A model with 44 declared properties, 42 of them defaulted and two required, **is**
   that semantics — the replacement is the model rather than code that implements one (§6.4).
3. **The disclosure rule**, one function applied where the user object is built, so all three roads
   get it from one place and cannot drift (§6.1). This is the piece that touches 002's implemented
   routes.
4. **A deletion**, which is three effects and a guard, and whose **order** is a divergence this
   feature takes on purpose (§6.6).
5. **Five client commands**, and one of them cannot be written naively: a policy body must be whole
   or it is refused, so setting one property is a read and a write (§6.7).

**The three decisions that were not obvious:**

1. **The disclosure rule lives in `to_wire`, not in each route.** It needs the *caller*, which two
   of the three roads did not have a reason to know: `/Users/Public` has no caller at all and
   `GET /Users/{userId}` had no use for one. Making it a parameter of the one function that builds
   the object is what makes spec §3.1.1's five-row table a single `if`, and what makes
   behaviours §3.5 and §3.22 impossible to satisfy on one road and not the other — which is the
   failure mode those entries were written about (§6.1).
2. **The deletion checks before it writes, where the reference writes before it checks.** That is
   OQ-15, decided, and here it is one ordering inside one function rather than a mechanism (§6.6).
3. **An unknown policy property is dropped on the way in *and* on the way out.** OQ-16 decided the
   first half; the second half is this plan's, and it is not symmetry for its own sake — accounts
   written before this change may hold unknown keys in their blob, and a filter that only guards
   the entrance would let those keep coming back for the life of the account (§4).

## 2. Inherited decisions

| Decision | Source |
|---|---|
| A route declares its authorisation as a FastAPI dependency; there is no policy registry | `api/deps.py:110-176` (`require_user`, `require_administrator`) |
| The elevated refusal is `EmptyForbiddenError` — no body, no content type — and it is raised by a dependency so it precedes model binding | `api/deps.py:153-176`; 009 §3.8 |
| `Error processing request.` as `text/plain` is `controller_error`; the framework's validation document and the JSON-encoded bare string are the other two shapes | `compat/errors.py:1181-1245`; behaviours §1.11 |
| A null property is absent from the wire | behaviours §1.7 |
| A user's name is unique by `name_normalised` — strip plus casefold — and the repository asks before it writes | `db/models.py:65-116`; `db/repositories.py:186-215` |
| The policy document is nine columns, two library lists and a blob; honouring a property that anything *queries* means a migration, on purpose | `users/policy.py:1-30`; 002 §3.5 |
| `assemble` and `split` are the only readers of that shape, and `split(assemble(x)) == x` is what round-tripping means | `users/policy.py:98-150` |
| Signing in again from the same device revokes that device's previous token | `users/sessions.py:218` |
| Passwords are Argon2id through `app.state.passwords`, and hashing runs off the event loop | ADR-0006; `users/passwords.py:131` |
| The database is WAL; the engine is synchronous and database work runs in a thread pool | ADR-0003; `db/engine.py` |
| A route exists only if `surface.yaml` lists it, and the suite fails on a declared endpoint nothing asked | `tests/conformance/test_routes.py`; 010 |
| The client imports nothing of the server's and is tested by recording every request it makes | 014 plan §6.7 |
| A probe that writes creates what it needs and removes it, including on failure | 010 §3.5; `tools/_probe.py` |

## 3. Modules

```
src/atrium/
├── api/
│   ├── users.py                 changed   the five routes, the policy model, the disclosure rule
│   └── deps.py                  unchanged require_administrator is already what four of five need
├── users/
│   └── policy.py                changed   DECLARED, and the filter both ways (§4)
├── db/
│   └── repositories.py          changed   UserRepository.remove, .count_administrators
│                                          (.set_policy and .set_library_access already exist);
│                                          TokenRepository revokes every token an account holds;
│                                          PlaylistRepository.owned_by
└── cli/
    ├── commands.py              changed   five subcommands under `user`
    └── client.py                changed   five calls

tests/
├── conformance/
│   ├── test_user_administration.py   new  the routes, criteria 1 to 12 and 19, 20
│   ├── test_user_disclosure.py       new  §3.1.1 on all three roads, criteria 5, 17
│   └── test_routes.py                changed  five rows
├── cli/
│   └── test_user_commands.py         new  criterion 13
└── unit/
    └── test_user_policy.py           changed  the filter, the defaults, the round trip

docs/compatibility/surface.yaml       changed  five rows
tools/differential.py                 changed  the seat is created and destroyed, not built by hand
tools/README.md                       changed  steps 3 and 4 lose the paragraphs that say it cannot
```

**No new module, and that is a statement rather than an accident.** Every route here is about an
account, `api/users.py` is the module about accounts, and a `user_administration.py` beside it would
put the disclosure rule at a distance from the object it applies to. The file grows by about a
third.

## 4. Data model

**No migration.** The account store already holds everything: nine typed columns, the
`user_library_access` join table, `policy_extra` and `configuration` as blobs
(`db/models.py`). Nothing here promotes a property into a column, which is exactly what §2's
inherited decision says a migration would be for.

**What changes is what the blob is allowed to hold.** OQ-16 decided that a property the reference
has never heard of is dropped, as the reference drops it. So:

- `users/policy.py` gains `DECLARED` — the 44 property names of the pinned `UserPolicy` schema
  `[spec: UserPolicy]` — and `split` keeps only `DECLARED` minus the eleven that have a column or a
  list, which is 33 names, discarding anything else.
- **`assemble` filters too.** An account whose blob was written before this change may hold keys
  that are not in `DECLARED`; filtering only on the way in would leave those coming back on every
  read for the life of the account, and the first thing anybody would do about it is a migration
  this plan says it does not need. Filtering both ways makes the old rows correct without touching
  them.

**44 declared and 42 on the wire, 16 and 15**, and the difference is not a property missing: it is
behaviours §1.7. `MaxParentalRating` and `MaxParentalSubRating` are null on a new account, and so is
`AudioLanguagePreference` — the measured documents carry 42 and 15 for that reason and no other
`[probe: tools/probe_user_administration.py, Jellyfin 10.11.11, 2026-09-16]`.

**Deletion is the one new shape in the store.** `user_library_access` rows and the account's
sessions are removed with the account; `playlists` are 009's and §6.6 says which of them go.

## 5. Contracts

| Route | Authorisation | Request | Success | Refusals |
|---|---|---|---|---|
| `GET /Users` | `require_user` — **any** signed-in caller, as the reference has it | `isHidden`, `isDisabled`, both `bool \| None` | `200`, a list of `UserDto`, by name | `401` empty; the framework's `400` for a filter that is not a boolean |
| `POST /Users/New` | `require_administrator` | `CreateUserByName` — `Name` required, `Password` optional | `200`, the new `UserDto` | validation `400` for an empty `Name`, a missing one or a body that is not an object; `controller_error` `400` for a refused character **and for a duplicate**; `415` for no body |
| `POST /Users/{userId}/Policy` | `require_administrator` | `UserPolicyDto`, whole | `204`, empty | `404` for an absent account; `controller_error` `400` for the all-zeros id; validation `400` for a bad id, a partial body, a body that is not an object; `415` for none; `message_error(403)` for the two reachable guards |
| `POST /Users/Password` | `require_user` | `userId` in the **query**; `UpdateUserPassword` | `204`, empty | `404` absent; `message_error(403)` twice — not permitted, and a wrong current password |
| `DELETE /Users/{userId}` | `require_administrator` | — | `204`, empty | `404` absent; `controller_error` `400` when it would leave no administrator |

Every refusal names a shape that exists. **Nothing in this table is a new error class**, which is
the test that the gate's readings landed inside behaviours §1.11's four shapes rather than beside
them.

## 6. Algorithms

### 6.1 The disclosure rule, in one place

`to_wire(user, state, access)` gains a fourth parameter: **the caller, or `None`**. It decides one
thing:

```python
discloses = caller is not None and (caller.id == user.id or caller.is_administrator)
```

and when it is false the two properties are **left out of the model** rather than set empty —
`UserDto.configuration` and `.policy` become `dict[str, Any] | None = None`, and behaviours §1.7's
global null-omission does the rest. That is why absent rather than empty costs nothing: this
project already omits nulls everywhere, so the shape spec §3.1.1 asks for is the shape the existing
serialiser produces.

The four callers:

| Caller | passes |
|---|---|
| `GET /Users/Public` | `None` — there is no caller, so nothing discloses |
| `GET /Users/Me` | the authenticated user, which is always the subject |
| `GET /Users/{userId}` | `require_user`'s result, which that route already has and ignored |
| `GET /Users` | the same, once per row |

**One function, four call sites, and no route decides anything.** A fifth road added later that
forgets the rule cannot: `to_wire` has no default for the parameter.

### 6.2 `POST /Users/New`

1. `require_administrator`.
2. Bind `CreateUserByName`: `Name: str = Field(min_length=1)` with a validator that strips and
   refuses empty — which produces the framework's validation document keyed on `Name`, the shape
   measured for both an empty name and one of only whitespace.
3. `valid_username(name)` — the reference's expression, transcribed:
   `^(?!\s)[\w \-'._@+]+(?<!\s)$` `[source: UserManager.cs:119-120 @ v10.11.11]`. A miss is answered with `controller_error(400)`
   (`compat/errors.py:1196`), which is `text/plain` with no charset — the detail that took a test
   comparing headers to get right.
4. In one transaction: `UserRepository.by_name(name)` — a hit is the **same** `controller_error`
   `400`, because the reference cannot tell them apart on the wire and neither may this (spec
   §3.2.1).
5. `UserRepository.add(User(...))` with the reference's defaults — `is_hidden=True` among them,
   measured — then the password, hashed off the event loop, when the body carried one.
6. `to_wire(new, state, access, caller)` → `200`.

**Steps 4 and 5 are one transaction and the unique index is the real guard.** The read-then-write is
what lets the route answer the measured shape; the index is what makes two simultaneous creations
of one name safe. An `IntegrityError` from the index is caught and answered as step 4 would have.

### 6.3 `GET /Users`

`UserRepository.all()` already orders by name. The two filters are applied in the query, not in
Python, and `bool | None` binding gives the measured `400` for free. Each row goes through
`to_wire` with the caller (§6.1), so an ordinary caller's own row is whole and the rest are not.

**A residual, named:** the reference orders with .NET's `OrderBy` over `Username` and this orders
with SQLite's `ORDER BY name`. The two agree on the fixture's names and are not guaranteed to agree
on names differing only in case or accent. It is in §9 rather than silently assumed.

### 6.4 `POST /Users/{userId}/Policy`

**The model is the semantics.** `UserPolicyDto` declares all 44 properties. Two are required —
`PasswordResetProviderId` and `AuthenticationProviderId` — and 42 carry the reference's measured
defaults. A body that omits an optional property therefore arrives carrying that default, which is
precisely what the gate measured the reference doing; a body that omits a required one is the
framework's validation `400` keyed on that property; a body naming one property is refused by the
same mechanism, without a line of code about partial bodies.

Then, in one transaction:

1. `by_id` — `None` is `UserNotFoundError`'s `404`. **The all-zeros id is refused first**, with
   `EmptyIdentifierError`, whose handler already renders `controller_error`'s `400`
   (`compat/errors.py:353, 1407`). 009 raises it inside `api/playlists.py`; this is its second
   raise site and the class's docstring says it belongs to the identifier rather than to a route,
   so nothing about it moves.
2. The two reachable guards of spec §3.3, in the reference's order, each `message_error(403)` with
   the reference's sentence. The third is unreachable and has no code, with §3.3's paragraph as the
   reason.
3. `UserRepository.set_policy(user_id, columns, extra)` — which **already exists**
   (`repositories.py:306`) — and `set_library_access` for the two lists, which also does. T5 adds a
   route and no repository method; the tasks gate found this table overstating it.
4. A disabling that succeeds revokes that account's tokens except the caller's. **That is
   `TokenRepository` and not `SessionRepository`** — the tasks gate corrected this plan on it. A
   session and a credential are two tables: `SessionRepository` removes by session and by device
   (`repositories.py:500, 503`), and what a revocation revokes is in `TokenRepository`, which
   already has `for_user`, `revoke` and `revoke_device` (`:377-394`). *Every token this account
   holds, except the caller's own* is one new method there.
5. `204`.

### 6.5 `POST /Users/Password`

`userId` from the query or the caller's own id. Then the three paths spec §3.4 measured:

- `ResetPassword: true` → `set_password_hash(id, None)`, and nothing else in the body is read.
  The account then signs in with no password, which is behaviours §3.33 and is replicated.
- Otherwise, when the caller **is not** an administrator, or when it named **itself** in `userId`,
  the current password is checked by authenticating it — a miss is `message_error(403)` with
  *"Invalid user or password entered."* The condition is transcribed from the source and measured
  on the wire, asymmetry included (spec §3.4).
- Then the new password is hashed and stored, and the account's other tokens are revoked.

`AssertCanUpdateUser`'s rule — the caller is the account, or an administrator — is a helper beside
the route, refusing with *"User is not allowed to update the password."*

### 6.6 `DELETE /Users/{userId}`

```
by_id → None            → 404
would leave no administrator → 400 controller_error, AND NOTHING ELSE HAS HAPPENED
revoke every token the account holds
remove the private playlists it owns; leave the public ones
remove user_library_access, then the account
204
```

**The guard comes first, and that is the divergence.** The reference's controller revokes and
removes before the step that raises (behaviours §3.34), so its refusal signs the administrator out;
here the refusal is a read and a return. A client cannot tell: the status and the body are the
reference's, and the only difference is an effect of a request that was already failing.

*"Would leave no administrator"* is `count_administrators() <= 1 and user.is_administrator`, read in
the same transaction as the delete.

**The playlists are 009's and this route calls into them.** `PlaylistRepository.owned_by(user_id,
public=False)` returns the private ones; the public ones are left where they are, owned by an
account that will not exist (OQ-17, decided). What such a playlist answers for its owner field is
009's to state, and this plan's answer is *nothing changes* — the stored owner id is not rewritten,
because rewriting it would invent an owner the reference does not invent.

### 6.7 The client (OQ-13, decided here)

Five subcommands under `user`, beside 014's `library`:

```
atrium-admin user add      --server URL --username ADMIN NAME
atrium-admin user list     --server URL --username ADMIN
atrium-admin user policy   --server URL --username ADMIN NAME [--administrator yes|no]
                                                              [--disabled yes|no] [--hidden yes|no]
                                                              [--libraries NAME[,NAME...]|all]
atrium-admin user password --server URL --username ADMIN NAME
atrium-admin user remove   --server URL --username ADMIN NAME
```

**`user policy` reads before it writes, and that is forced rather than chosen.** A body naming one
property is refused `400`, so the command fetches the account's policy with `GET /Users/{id}`,
applies the flags the operator named, and posts it whole. Nothing is composed: every property the
operator did not name is the property the server just sent back.

**`--libraries` names libraries by name, not by identifier**, and resolves them through
`GET /Library/VirtualFolders` — 014's route, already served. `all` sets `EnableAllFolders`; a list
clears it and fills `EnabledFolders`.

**And the client says which refusal it met**, which spec §3.2.1 makes harder than it sounds: a
refused character and a name already taken are the same six words. `user add` therefore lists the
accounts **before** it creates one, and on a `400` with that body it can say *"that name is already
in use"* or *"that name cannot be used"* from what it already knows. It is the client compensating
for a server that cannot tell them apart, which is the right place for it — the server reproduces
the reference and the client is this project's own.

## 7. Failure handling

| Failure | Detected by | Answer | Why |
|---|---|---|---|
| Two creations of one name race | The unique index on `name_normalised` | The same `controller_error` `400` the read-then-write gives | One answer for one condition, whichever guard caught it |
| A policy names a library that does not exist | `set_library_access` writes a row for it | Accepted, as today | The reference stores the list it is given; a library added later makes the row meaningful |
| A deletion races another deletion | `by_id` inside the transaction | `404` from the loser | The measured answer for a second deletion |
| The last administrator is demoted and deleted concurrently | Both read `count_administrators()` in their own transaction | The store may end with none | **Recorded, not solved** (§9) |
| A password hash fails | Argon2 raises | `500` | Nothing here can answer better, and a hash that cannot be computed is not a client's fault |
| An account's blob holds a property `DECLARED` does not | `assemble`'s filter | It stops being answered | §4, and it is why the filter is on both sides |

## 8. Testing strategy

**Twenty acceptance criteria, all at the HTTP boundary.** The map in
`tests/conformance/test_acceptance.py` gains `FEATURE_015` and the feature joins
`IMPLEMENTED_FEATURES` in the change that implements it.

| Criteria | Where |
|---|---|
| 1–4, 19 | `test_user_administration.py` — creation, the four refusal envelopes, the policy body's required properties and its defaults |
| 5, 17 | `test_user_disclosure.py` — §3.1.1's five rows, on all three roads, for both kinds of caller |
| 6, 15, 16 | `test_user_policy.py` and `test_user_administration.py` — 42 and 15 round-tripped, the fourteen acted on, one of the 28 carried and inert |
| 7, 8, 20 | `test_user_administration.py` — the reachable guards, the revocation, the deletion that changes nothing |
| 9–11 | the password paths, including the asymmetry and the reset |
| 12 | the deletion's reach, private and public |
| 13 | `tests/cli/test_user_commands.py`, recording every request the client makes |
| 14, 18 | `tools/differential.py` and its own tests — the seat created and destroyed, the allowlist entries |

**Conformance (OQ-2, decided here): `L3` for four of the five, `L2` for the fifth.** AC-14 makes the
differential harness *create* its restricted seat through `POST /Users/New`, give it a policy
through `POST /Users/{userId}/Policy`, and destroy it through `DELETE /Users/{userId}` — and it
already lists accounts. Those four are therefore asked of both servers by a run that has to happen
anyway, which is what `L3` means. `POST /Users/Password` is not on that path and no comparison
needs it, so it is `L2` and says so. **This is the opposite of 014's answer** (`L2`, with `L3`
owed), and the difference is that 014 needed a harness change that did not exist while this needs
one the feature is delivering.

**The four `L3` rows need cases from both seats, and three of them write.** `request-cases.yaml`'s
rule is *"nothing here is a write to an account this project does not own"*, and the administrator's
seat is whatever `.env` names. The administrator-seat cases for the three writing rows therefore
carry **`needs: [fixture]`**, which makes them askable only against the single-use instance the run
stands up and destroys — the same argument `rescan` and `wait` already carry in
`NEEDS_THE_INSTANCE` (`tools/differential.py:1205`). The tasks gate found this, and it is the one
finding that would have changed OQ-2 had the mechanism not existed.

**Two counted assertions move with the rows**: the surface's 65 to 70, and the `L3` count's 10 to
14 (`tests/unit/test_allowlist.py:720, 737`).

**No test contacts a reference.** The probe is `tools/probe_user_administration.py`, run by hand,
and the suite fails any test that opens a TCP connection.

## 9. Risks

| Risk | Cost | Mitigation |
|---|---|---|
| **The username expression is .NET's, transcribed** | A name one server accepts and the other refuses | Python's `\w` is unicode by default as .NET's is with `RegexOptions`; the gate measured six refusals and a test asserts each. A residual: neither was measured against a name outside the Latin script |
| **`ORDER BY name` is not `OrderBy(Username)`** | Two orders that differ on case or accent | §6.3; the differential compares the list route on both servers, which is where a difference would show |
| **The disclosure rule changes two implemented routes** | A client reading `Policy` from `/Users/Public` breaks | Decided as OQ-14 with the argument in behaviours §3.5 and §3.22; neither client trace mentions either property |
| **Concurrent demotion and deletion can leave no administrator** | A server nobody can administer — the thing OQ-11 is about | Recorded rather than solved: both paths read the count in their own transaction, and SQLite's WAL does not serialise them. A single-writer store makes it unlikely and not impossible |
| **`Users.AuthenticateByName` already answers a different `EnabledFolders`** | One account, two answers, depending on the road | Found by the tasks gate reading the goldens; it is 002's and predates this feature, and §6.1 leaves it untouched rather than absorbing it into a task about something else |
| **`DECLARED` pins a property list to one reference version** | A newer reference's new property is dropped | That is OQ-16's decision working as intended, and `tools/bump_reference_version.py` is where a version move is noticed |

## 10. Alternatives considered

**A `user_administration.py` router of its own.** Rejected: §3. The disclosure rule has to sit
beside the object it applies to, and it applies to routes 002 owns.

**A `PATCH`-shaped policy update, merging what the caller sent onto what is stored.** Rejected: it
is not what the reference does, and the gate measured that precisely — an omitted property takes
the default. A merge would answer `204` to the same body and store something else.

**Refusing `ResetPassword` rather than replicating it.** Rejected by the operator on 2026-09-16;
behaviours §3.33 carries the argument, and §6.5 the code.

**Reproducing the reference's deletion order.** Rejected by the operator on 2026-09-16 as OQ-15.
The argument for reproducing it is Principle V; the argument against is that no client can observe
the difference, which makes it the cheapest divergence this project has taken.

**Teaching the client to set a policy property without reading first.** Not possible: the server
refuses a partial body. It is in this list because it was the plan's first shape, and the gate's
reading is what removed it.
