---
feature: 015-user-administration
title: User administration
status: Draft
created: 2026-09-16
updated: 2026-09-16
depends_on: [002, 005, 014]
---

# 015 — User administration

> **This document describes WHAT and WHY only.** No technology names. No storage decisions. No
> module or function names. If you need to write one, it belongs in `plan.md`.

## 1. Purpose

**A server that has one account can be given others, and each of them can be told what it may
do** — created, listed, given a password, given a policy, and removed — from a terminal, over
Jellyfin's own user operations and nothing else.

[014](../014-first-time-setup/spec.md) made the first administrator exist, and stopped there on
purpose: every operation below requires an administrator, which a fresh server did not have
([014 §2](../014-first-time-setup/spec.md#2-scope), *"they are the next slice"*). This is that
slice, and it is the second of [v2](../../docs/roadmap.md#v2--the-management-cli)'s left column.

**What it unlocks is not only an account.** A second account with a narrowed policy is what this
repository's own differential harness has been building **by hand**, through direct database
access, since it was written: `tools/README.md` steps 3 and 4 are two of the four things a run has
to arrange because *"Atrium cannot make one"*, and the cost of the second was measured — a sweep
that skipped it answered **1231 differences, 307 of them on the three user routes and every one of
them about how the account was made** `[probe: tools/differential.py --fixture, Jellyfin 10.11.11,
2026-09-07]`. When this feature lands, the harness asks the server for what it now writes behind
the server's back, and 010's owed *"the restricted seat is still built by hand"* is paid.

## 2. Scope

### 2.0 Why these operations, and why they are not a side door

The constraint is [014 §2.0](../014-first-time-setup/spec.md#20-why-these-operations-and-why-they-are-not-a-side-door)'s,
unchanged: **the client is a client**. Every operation below is one Jellyfin declares
`[spec: CreateUserByName, GetUsers, UpdateUserPolicy, UpdateUserPassword, DeleteUser]`, reached over
HTTP with a token obtained the way any client obtains one, and elevated the way the reference
elevates it. Nothing here is invented, and nothing here is reachable by a path a Jellyfin client
could not take.

The difference from 014 is that **this feature invents no window**. 014's operations answer before
there is anybody to authorise, which is why its §3.1 had to decide who may reach them; these answer
only to an administrator, and the reference's own elevation policy is the whole of the rule
`[source: Jellyfin.Api/Controllers/UserController.cs:538-541 @ v10.11.11]`.

### In scope

- `POST /Users/New` — a second account, and any later one (§3.2).
- `GET /Users` — every account the server holds, with the reference's two filters (§3.1).
- `POST /Users/{userId}/Policy` — what an account may do, including whether it is an administrator,
  whether it is disabled, and which libraries it may open (§3.3).
- `POST /Users/Password` — setting, changing and clearing an account's password (§3.4).
- `DELETE /Users/{userId}` — removing an account, and what removing it takes with it (§3.5).
- **The policy and configuration documents themselves** — an account this server makes answers the
  reference's whole `UserPolicy` and `UserConfiguration` on `GET /Users`, `GET /Users/Me` and
  `GET /Users/{userId}`, rather than the eleven properties an account written by hand answers today
  (§3.6). This is a change to three endpoints 002 already serves, and it adds no row to the surface.
- **The client commands** that perform the five operations above, in the client 014 built (§3.7).

### Out of scope

- `POST /Users` — `UpdateUser`, which renames an account and rewrites its whole document. The
  roadmap's v2 row is *"create, list, update policy, reset password"* and a rename is not in it;
  it is also the one operation here whose body is the user document rather than a document of its
  own, so it carries every field this feature decides about in §3.6 **and** the identity questions
  a rename raises. It goes to the slice after this one, unless the gate decides otherwise (OQ-12).
- **Renaming or removing a library, or changing its paths.** 014 §2 put these *"in the next slice
  with the users"*; this document narrows that, because they share nothing with an account but a
  release. They are the slice after this one (OQ-12).
- `POST /Users/ForgotPassword` and `POST /Users/ForgotPassword/Pin` — a password reset a user
  starts for themselves, which needs a reset provider and a pin file on disk. An administrator
  clearing a password is §3.4 and is a different operation.
- `POST /Users/{userId}/Authenticate`, `POST /Users/AuthenticateWithQuickConnect` — 002's, and
  quick connect is not in v1 at all.
- **Per-user library visibility being enforced** beyond what 002 and 005 already enforce. This
  feature makes a policy **sayable and stored**; which of its properties this server *acts on* is
  §3.6 and OQ-7, and every property it does not act on is an accepted gap with a named owner.
- **Any operation Jellyfin does not have.** A convenience this client wants and the API lacks, the
  client does without.

## 3. Behaviour

**Every claim in this section is from the pinned document or the pinned source, and none of it has
been measured.** 011, 012 and 014 each opened this way and each had claims withdrawn at its
measurement gate — 014 lost two of its own the day it was measured. §7 says where the readings come
from and which questions they answer; **no claim below may be implemented before its reading**
(Principle II).

### 3.1 `GET /Users` — `GetUsers`

**Consumers:** none in [api-surface-v1.md](../../docs/compatibility/api-surface-v1.md) — this is a
management route, and the client of §3.7 is its first consumer here.

**Request**

| Part | Name | Required | Type | Notes |
|---|---|---|---|---|
| query | `isHidden` | no | boolean | Absent means no filter |
| query | `isDisabled` | no | boolean | Absent means no filter |

**Response — 200.** The accounts the server holds, **ordered by name**, each as the same user
document `GET /Users/{userId}` answers `[source: UserController.cs:621-656 @ v10.11.11]`.

**Who may ask it.** The reference authorises this route for **any authenticated caller**, not for an
administrator `[source: UserController.cs:91-100 @ v10.11.11]`: a signed-in ordinary account reads
every account on the server, with its policy. That is a disclosure of the same class as the one
009 refused ([behaviours §3.19](../../docs/compatibility/behaviours.md)), and **whether this server
reproduces it or narrows it is OQ-3**, which is the operator's.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| No token | `401` | 002's shape |
| A filter that is not a boolean | ⚠️ UNVERIFIED — OQ-1 | |

### 3.2 `POST /Users/New` — `CreateUserByName`

**Request** — a body with `Name` (required) and `Password` (optional, nullable)
`[spec: CreateUserByName]`.

**Response — 200**, the new account's user document — not `201`, and not the empty body the other
four operations answer `[spec: CreateUserByName]`.

**What the reference does, in order** `[source: UserController.cs:541-556 @ v10.11.11]`:

1. The name is validated, and an invalid one raises rather than returns (§3.2.1).
2. A name already in use, **compared without case**, raises
   `[source: Jellyfin.Server.Implementations/Users/UserManager.cs:296-315 @ v10.11.11]`. 014 §3.6
   numbers a *library* name that collides; **an account name is not numbered**, and the two
   operations differ on purpose.
3. The account is created with the server's default policy and configuration (§3.6).
4. **Only then** is the password set, if one was sent — *"no need to authenticate password for new
   user"* is the source's own comment, and it means a creation that fails at the password leaves the
   account behind, without one.

**Whether step 4's failure is reachable, and what it leaves, is OQ-4.**

#### 3.2.1 What a name may be

The reference accepts a name that is not blank and matches its own expression — **unicode letters
and digits, space, dash, apostrophe, underscore, period, `@` and `+`, and neither a leading nor a
trailing space** `[source: UserManager.cs:119-120, 900-908 @ v10.11.11]`. Anything else raises with
a message that does not list the same characters as the expression does — the message names dashes,
underscores, apostrophes and periods and omits space, `@` and `+`.

**What an administrator sees when it raises is not in the document** `[spec: CreateUserByName]` —
the operation declares `200`, `401`, `403` and `503` and no refusal at all. 014 met the same class
and measured it: the reference's own error middleware turns this kind of refusal into one of
[behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s
four shapes ([014 §3.3](../014-first-time-setup/spec.md)). **Which shape, and with what body, is
OQ-1.**

**Error responses**

| Condition | Status | Body |
|---|---|---|
| No token, or a token that is not an administrator's | `401` / `403` | 002's shapes, from the reference's elevation policy |
| A name that is blank, or holds a character the expression refuses | ⚠️ UNVERIFIED — OQ-1 | |
| A name another account holds, in any case | ⚠️ UNVERIFIED — OQ-1 | |
| No body, or a body with no `Name` | ⚠️ UNVERIFIED — OQ-1 | |

### 3.3 `POST /Users/{userId}/Policy` — `UpdateUserPolicy`

**Request** — the whole policy document in the body `[spec: UpdateUserPolicy]`. It is a
**replacement, not a patch**: the reference takes the document it is given and stores it, so a
property the caller leaves out is the property's default and not its previous value. **Whether this
server reproduces that, and what it answers to a body that omits properties, is OQ-5.**

**Response — 204**, empty.

**The four refusals, in the order the reference tests them**
`[source: UserController.cs:438-478 @ v10.11.11]`:

| Condition | Status | The reference's words |
|---|---|---|
| No account with that id | `404` | empty — **and the document does not declare it** `[spec: UpdateUserPolicy]` |
| Taking administrator away from the only administrator | `403` | *"There must be at least one user in the system with administrative access."* |
| Disabling an account that is an administrator | `403` | *"Administrators cannot be disabled."* |
| Disabling the only enabled account | `403` | *"There must be at least one enabled user in the system."* |

**A disabling that succeeds revokes that account's tokens**, every one but the caller's own
`[source: UserController.cs:471-472 @ v10.11.11]`. What that means for a session this server is
tracking, and for a playback report arriving on a revoked token, is 002's and 007's; **the reading
that decides it is OQ-6.**

**The `403` bodies are quoted above as strings the reference passes to its own status helper, not
as bodies measured on the wire.** ⚠️ UNVERIFIED — OQ-1 covers their shape too.

### 3.4 `POST /Users/Password` — `UpdateUserPassword`

**Request** — `userId` in the **query** and not in the path, and a body of four properties:
`CurrentPassword` (a hash, and legacy), `CurrentPw`, `NewPw`, `ResetPassword`
`[spec: UpdateUserPassword, UpdateUserPassword schema]`. An absent `userId` means the caller's own
account `[source: UserController.cs:273-281 @ v10.11.11]`.

**Response — 204**, empty.

**Three paths through one operation** `[source: UserController.cs:273-317 @ v10.11.11]`:

1. **`ResetPassword: true`** — the account's password is cleared, and nothing else in the body is
   read. This is *"reset password"* in the roadmap's v2 row, and it leaves an account that signs in
   with no password at all. **What it answers, and what a cleared account then needs to sign in, is
   OQ-8.**
2. **An administrator changing another account's password** — `CurrentPw` is **not** checked. The
   condition is written as *"not an administrator, or the caller named itself in `userId`"*, so an
   administrator changing its own password **through an explicit `userId`** must give the current
   one, and the same administrator omitting `userId` need not. **That asymmetry is the reference's
   and this document does not yet know whether it is deliberate; it is OQ-9.**
3. **Anyone changing their own password** — the current password is checked by authenticating it,
   and a wrong one answers `403` *"Invalid user or password entered."*

**A password that changes revokes that account's other tokens**, keeping the caller's
`[source: UserController.cs:309-313 @ v10.11.11]`.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| No account with that id | `404` | The document *describes* it as *"User not found."*; the source answers an empty refusal `[source: UserController.cs:277-281 @ v10.11.11]`. ⚠️ UNVERIFIED — OQ-1 |
| A caller who is neither the account nor an administrator | `403` | *"User is not allowed to update the password."* `[source: UserController.cs:284-287 @ v10.11.11]` — a string handed to the status helper, not a body measured on the wire. ⚠️ UNVERIFIED — OQ-1 |
| A wrong current password | `403` | *"Invalid user or password entered."* `[source: UserController.cs:303-306 @ v10.11.11]`, and the same caveat. ⚠️ UNVERIFIED — OQ-1 |

### 3.5 `DELETE /Users/{userId}` — `DeleteUser`

**Response — 204**, empty. `404` when no account has that id `[spec: DeleteUser]`.

**Deleting an account takes three things with it, in this order**
`[source: UserController.cs:155-167 @ v10.11.11]`:

1. **Every token that account holds** is revoked.
2. **Every playlist that account owns** is removed — which in this server is
   [009](../009-playlists/spec.md)'s structural state, and the only state in the store a rescan
   cannot rebuild ([roadmap](../../docs/roadmap.md)). What it does to a playlist another account can
   see is OQ-10.
3. **The account itself.**

**What the reference does not refuse here is the interesting half**: nothing in this operation
checks that an administrator is left, or that the account is not the caller's own — the three
guards of §3.3 have no counterpart in deletion `[source: UserController.cs:155-167 @ v10.11.11]`.
**Whether a server can delete its own last administrator is a reading, and it is OQ-11.**

### 3.6 What an account answers, and what it acts on

**Today an account this server makes answers eleven of the reference's forty-two policy properties
and an empty configuration** `[probe: tools/differential.py --fixture, Jellyfin 10.11.11,
2026-09-07]` — 307 of that run's 1231 differences are that fact, on three routes 002 already
serves. The accounts were written by hand because no route made them; this feature makes the route,
and the document the route stores is the document the three read routes must answer.

**The split this feature draws, and OQ-7 is where it is decided:**

- **Stored and answered in full** — every property of the reference's policy and configuration
  documents, whatever this server does with it. A property that round-trips is a property the
  harness stops reporting.
- **Acted on** — the subset with a meaning in v1: whether the account is an administrator, whether
  it is disabled, whether it is hidden, and which libraries it may open. Everything else names a
  capability v1 does not have (live television, channels, sync, device control) or a limit nothing
  enforces yet.
- **An accepted gap, named** — every property in the first list and not the second, in
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1), with the feature
  that would own it. A property stored and ignored is a gap; a property silently dropped is a
  divergence, and this feature intends the first.

### 3.7 The client

The client [014 §3.8](../014-first-time-setup/spec.md) built gains five commands, each one of the
five operations above and nothing else: creating an account, listing accounts, setting a policy,
setting a password, and removing an account. It signs in the way 014's commands sign in, asks for
passwords the way they ask, and reaches the server over the same addresses.

**What it must not do** is compose a policy the operator did not ask for. §3.3's body is a whole
document, so a command that sets one property has to send the other forty-one, and where it gets
them from — the account's current policy, read back first — is the plan's, but *that* it reads them
rather than inventing them is this document's (OQ-5).

## 4. Data the feature owns

Observable, and surviving a restart:

- **Accounts beyond the first**: their names, their identifiers, and whether each holds a password.
- **Each account's policy document**, whole, as §3.6 decides it.
- **Each account's configuration document**, whole.
- **Nothing else.** An account's user data, its sessions and its playlists are 007's, 002's and
  009's; this feature deletes them through §3.5 and does not otherwise touch them.

## 5. Acceptance criteria

1. An administrator creates a second account by name, and the new account's document comes back
   with an identifier and a name, answering `200`.
2. The new account signs in with the password its creation set, and browses the libraries its
   policy allows — over the same operations any Jellyfin client uses.
3. A name another account holds, in any case, is refused with the shape and body OQ-1 settles, and
   **no second account exists afterwards**.
4. A name that is blank, or that holds a character §3.2.1's expression refuses, is refused with the
   same shape, and no account exists afterwards.
5. `GET /Users` answers every account the server holds, ordered by name, each carrying the whole
   policy and configuration §3.6 requires; `isHidden` and `isDisabled` each narrow it as the
   reference narrows it.
6. A policy sent for an account is stored whole and answered whole by all three read routes — the
   reference's forty-two properties, not eleven — and a property this server does not act on
   round-trips unchanged.
7. Each of §3.3's four refusals is refused, with its status and its body: no such account, the last
   administrator demoted, an administrator disabled, the last enabled account disabled.
8. An account disabled by a policy update cannot sign in afterwards, and the tokens it held no
   longer authenticate — except the caller's own, per §3.3.
9. An administrator sets another account's password without giving the current one; that account
   signs in with the new password and not with the old one.
10. An account changing its own password must give the current one, and a wrong one is refused
    `403` with §3.4's body.
11. `ResetPassword: true` clears an account's password, and what the account can then do is what
    OQ-8 settles — asserted as decided, not as implemented.
12. Deleting an account revokes its tokens, removes the playlists it owns, and leaves it absent from
    `GET /Users`; a second deletion of the same identifier answers `404`.
13. The client performs all five operations against a server it set up, over HTTP alone, and a run
    of it on a fresh server produces a second account whose policy a Jellyfin client sees.
14. **The differential harness stops building its restricted seat by hand**: the run creates the
    seat through §3.2 and §3.3 and destroys it through §3.5, and `tools/README.md` steps 3 and 4
    lose the paragraphs that say it cannot.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `GET /Users` | L2 | The suite asks it and asserts the order, the filters and the document |
| `POST /Users/New` | L2 | The suite asserts the created document and every refusal of AC-3 and AC-4 |
| `POST /Users/{userId}/Policy` | L2 | The suite asserts the round trip and the four refusals |
| `POST /Users/Password` | L2 | The suite asserts the three paths of §3.4 |
| `DELETE /Users/{userId}` | L2 | The suite asserts AC-12 |

**L3 is owed rather than claimed, and by less than 014 owed it.** The harness needs no new ability
to reach these five — it holds an administrator's token already, and AC-14 makes it *create* the
seat it compares. Whether that makes them L3 rows in this feature or in the change that pays 014's
own L3 debt is OQ-2.

Levels are defined in [../../docs/compatibility/conformance.md](../../docs/compatibility/conformance.md).

## 7. Open questions

**None of the thirteen is answered, and this document is `Draft` until the readings are taken.**
Like 011, 012 and 014, this feature opens with its questions open and no measurements of its own,
and there is one place the readings can be taken: **the single-use reference instance**
`[tools/reference_instance.py]`, which runs the pinned version and is destroyed with everything it
wrote. The operator's own server cannot take them — it answers `12.0.0` since 2026-09-12 and a
reading from it is not a reading of the pinned contract — and every question below **writes**, which
is exactly what the disposable instance exists for.

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | What do the refusals of §3.2, §3.2.1 and §3.3 answer on the wire — which of [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s four shapes, with what status and what body? The document declares none of them | §3.2, §3.3, AC-3, AC-4, AC-7 | A reading on the instance |
| OQ-2 | Are these five rows `L3`, or `L2` with `L3` owed to 014's own L3 change? | §6 | The plan |
| OQ-3 | `GET /Users` answers every account, with its policy, to **any** signed-in caller. Reproduce it, or narrow it to an administrator as 009 narrowed its own disclosure? | §3.1 | **The operator.** A Principle I decision |
| OQ-4 | Is §3.2's step 4 reachable — can a creation fail *after* the account exists — and what does it leave? | §3.2 | A reading on the instance |
| OQ-5 | A policy body that omits properties: does the reference store the defaults, or keep what was there? And does it refuse a body that is not a whole document? | §3.3, §3.7 | A reading on the instance |
| OQ-6 | What exactly does a disabling revoke, seen from a client — a session that was streaming, a report arriving afterwards? | §3.3 | A reading on the instance |
| OQ-7 | Which policy properties does this server **act on**, and which are stored, answered and ignored as a named gap? | §3.6, AC-6 | **The operator**, on a reading of the reference's own defaults |
| OQ-8 | What does an account with a cleared password do — sign in with an empty password, sign in with none, or refuse? | §3.4, AC-11 | A reading on the instance |
| OQ-9 | Is §3.4's asymmetry real on the wire: an administrator naming itself in `userId` must give its current password, and the same administrator omitting `userId` need not? | §3.4 | A reading on the instance |
| OQ-10 | Deleting an account removes the playlists it owns. What happens to one another account can see, and what does 009's store do about it here? | §3.5, AC-12 | A reading on the instance, then 009's owner |
| OQ-11 | Can the last administrator be deleted, leaving a server nobody can administer? | §3.5 | A reading on the instance, then **the operator** |
| OQ-12 | Does this slice keep `POST /Users` and the four library-management operations out, against 014 §2's *"the next slice with the users"*? | §2 | **The operator**, at this gate |
| OQ-13 | Does the client's account commands' output name a policy property the operator did not set — and if so, how does a command set one property without composing the other forty-one? | §3.7 | The plan, after OQ-5 |

## 8. References

- [Roadmap, v2 — the management CLI](../../docs/roadmap.md#v2--the-management-cli): the left
  column's users row, and what *"what is left of v2"* names as the next slice.
- [014 §2](../014-first-time-setup/spec.md#2-scope): the out-of-scope rows this feature picks up,
  and §2.0's constraint, which is unchanged.
- [002 §3](../002-authentication-users-and-sessions/spec.md): the three read routes §3.6 changes,
  the token shapes, and the `401`/`403` bodies.
- [009 §3](../009-playlists/spec.md): the playlists §3.5 deletes, and the disclosure divergence
  OQ-3 is measured against.
- [`tools/README.md`](../../tools/README.md), steps 3 and 4: what the harness builds by hand, and
  the 2026-09-07 and 2026-09-08 sweeps that price it.
- Jellyfin at `v10.11.11`, neither file touched by the local fork:
  `Jellyfin.Api/Controllers/UserController.cs`, `Jellyfin.Api/Helpers/RequestHelpers.cs`,
  `Jellyfin.Server.Implementations/Users/UserManager.cs`.
- The `10.11.11` OpenAPI document: `CreateUserByName`, `GetUsers`, `UpdateUserPolicy`,
  `UpdateUserPassword`, `DeleteUser`, and the `CreateUserByName`, `UpdateUserPassword`,
  `UserPolicy` and `UserDto` schemas.
