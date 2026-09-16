---
feature: 015-user-administration
title: User administration
status: Draft
created: 2026-09-16
updated: 2026-09-16
amended: 2026-09-16 after the gate - OQ-15 decided (this server refuses a deletion that would leave no administrator before revoking or removing anything, which no client can see because the request refused before and refuses now: behaviours 3.34) and OQ-17 decided (a deleted account's public playlists are kept, as the reference keeps them); section 3.5 amended, AC-12 and AC-20 amended, and no question is left that is not the plan's. Earlier the same day at the measurement gate - the eight readings taken on a single-use instance of the pinned version and OQ-1, OQ-4, OQ-5, OQ-6 and OQ-8 to OQ-11 closed; two claims made from the source withdrawn (the last administrator can be refused its own deletion, and a deletion removes only the private playlists); sections 3 to 3.7 amended, AC-3, AC-4, AC-6, AC-7, AC-11 and AC-12 amended, AC-19 and AC-20 added; OQ-15 and OQ-17 raised for the operator and OQ-16 raised and decided (an unknown policy property is dropped, as the reference drops it, which corrects 002's reader). Earlier the same day - OQ-14 decided (the user disclosure is narrowed by withholding Policy and Configuration from a caller who is neither the account nor an administrator, on all three roads at once, rather than by refusing any of them); section 2 gains the two roads 002 serves, section 3.1 amended and 3.1.1 added, AC-5 amended, AC-17 and AC-18 added, behaviours 3.5 and 3.22 rewritten together. Earlier the same day - OQ-7 decided (this feature draws no split of its own: all 42 policy and 16 configuration properties stored and answered, 002's fourteen acted on, the other 28 a named gap) and OQ-12 decided (POST /Users and the four library-management operations stay out, which amends 014 section 2); sections 2 and 3.6 amended, AC-6 amended, AC-15 and AC-16 added. And the same day OQ-3 was decided by the operator - narrow the disclosure - and recorded as open rather than applied: behaviours 3.5 and 3.22 replicate the same disclosure on two other roads and each says a divergence is taken on every road in one change, which this question had not weighed. Section 3.1 unamended; OQ-14 raised with the three shapes the change could take
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
- **Who those two properties are answered to, on all three roads that publish them** — `/Users/Public`
  and `GET /Users/{userId}` as well as this feature's own `GET /Users` (§3.1.1, decided 2026-09-16
  as OQ-14). It is in scope here **because it cannot be anywhere else**: behaviours §3.5 and §3.22
  bind the three into one change, and this is the feature that adds the third road.
- **The client commands** that perform the five operations above, in the client 014 built (§3.7).

### Out of scope

- `POST /Users` — `UpdateUser`, which renames an account and rewrites its whole document. The
  roadmap's v2 row is *"create, list, update policy, reset password"* and a rename is not in it;
  it is also the one operation here whose body is the user document rather than a document of its
  own, so it carries every field this feature decides about in §3.6 **and** the identity questions
  a rename raises. It goes to the slice after this one — **decided 2026-09-16 as OQ-12**.
- **Renaming or removing a library, or changing its paths.** 014 §2 put these *"in the next slice
  with the users"*; this document narrows that, because they share nothing with an account but a
  release. They are the slice after this one — **decided 2026-09-16 as OQ-12**, which amends 014 §2
  rather than disagreeing with it.
- `POST /Users/ForgotPassword` and `POST /Users/ForgotPassword/Pin` — a password reset a user
  starts for themselves, which needs a reset provider and a pin file on disk. An administrator
  clearing a password is §3.4 and is a different operation.
- `POST /Users/{userId}/Authenticate`, `POST /Users/AuthenticateWithQuickConnect` — 002's, and
  quick connect is not in v1 at all.
- **Enforcing any policy property 002 does not already enforce.** This feature makes a policy
  **sayable and stored**; what acting on it means is 002's fourteen, unchanged (§3.6, OQ-7, decided
  2026-09-16). Promoting a twenty-ninth property into the enforced set is a migration and a
  decision of its own, and it is not this feature's.
- **Any operation Jellyfin does not have.** A convenience this client wants and the API lacks, the
  client does without.

## 3. Behaviour

**Every claim in this section was measured on 2026-09-16**, on a single-use instance of the pinned
version `[probe: tools/probe_user_administration.py, Jellyfin 10.11.11, 2026-09-16]`, and the
readings are in [notes/user-administration-readings.md](notes/user-administration-readings.md).
It opened the way 011, 012 and 014 opened — stated from the source and the document, measured by
nothing — and like all three it lost claims at its gate. **Two did not survive**: the last
administrator *can* be refused its own deletion, and a refusal on that route is not free. Both are
below, at the sections that made them.

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
every account on the server, with its policy. **This is the same object [behaviours §3.5](../../docs/compatibility/behaviours.md#35-userspublic-discloses-every-users-policy-to-anyone--class-b-diverged--decided-2026-09-16-not-yet-implemented)
and [§3.22](../../docs/compatibility/behaviours.md#322-any-authenticated-caller-reads-any-user-whole--class-b-diverged--decided-2026-09-16-not-yet-implemented)
publish on two other roads**, and both entries said, while they were replications, that a
divergence here is taken on every road in one change or it is *"the inconsistency, not the
protection"*. **Decided on 2026-09-16 as OQ-14, and taken on all three roads at once** — §3.1.1 is
the rule, and this feature carries it for 002's two roads as well as its own.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| No token | `401` | 002's shape |
| A filter that is not a boolean | `400` | The framework's validation document, keyed on the parameter: `{"type":"…#section-15.5.1","title":"One or more validation errors occurred.","status":400,"errors":{"isHidden":["The value 'banana' is not valid."]},"traceId":"…"}` |

**The order is by name**, and it was read rather than assumed: three accounts came back
alphabetically whatever order they were created in.

#### 3.1.1 The rule, on all three roads

**A user object carries `Policy` and `Configuration` only when the caller is that account or an
administrator. Otherwise both properties are absent** — not `null`, not an empty object, absent —
and every other property of the object is unchanged.

| Road | Caller | What the object carries |
|---|---|---|
| `GET /Users/Public` | nobody is authenticated here | never — the two properties are absent from every row |
| `GET /Users/{userId}` | the account itself, or an administrator | both |
| `GET /Users/{userId}` | any other authenticated caller | neither |
| `GET /Users` | an administrator | both, on every row |
| `GET /Users` | any other authenticated caller | both on that caller's own row, neither on the rest |
| `GET /Users/Me` | the caller is always that account | both |

**Why the fields and not the route.** Refusing what the reference answers is at the dangerous end
of [§3.0.3](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made)'s list, and
`GET /Users/Public` is the login screen of a named consumer. Withholding two properties is
*strictly less information* on a request that still succeeds, which §3.5 names in its own words as
*"the least dangerous kind of change to make and still not free"*. **It is not free**: omitting a
property is exactly the shape that breaks a decoder expecting one, and this document does not know
that no client decodes them — what it knows is that neither
[client-atrium-tvos.md](../../docs/compatibility/client-atrium-tvos.md) nor
[client-embeat-mobile.md](../../docs/compatibility/client-embeat-mobile.md) mentions either
property anywhere, which is evidence and not proof.

**It reinstates a criterion that was withdrawn, and the second time is not the first.** 002's AC-6
asserted that `/Users/Public` omits `Configuration` and `Policy` on a premise that had never been
measured, and [behaviours §3.5](../../docs/compatibility/behaviours.md) records its correction. It
comes back here as a **decision taken against a measurement**, not as an assumption standing in for
one, and the measurement it is taken against is the one that overturned it.

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
3. The account is created with the server's default policy and configuration (§3.6) — and
   `IsHidden` is **true** on it, so a new account does not appear on a login screen until something
   clears the flag `[probe: tools/probe_public_users.py, Jellyfin 10.11.11, 2026-09-02]`, which is
   002 §3.4's reading and the one measured claim this section does not owe to its own gate.
4. **Only then** is the password set, if one was sent — *"no need to authenticate password for new
   user"* is the source's own comment, and it means a creation that fails at the password leaves the
   account behind, without one.

**Step 4's failure was not reachable from the API, and that is recorded as *not reached* rather
than as impossible** (OQ-4). The password step takes any string the body carries and skips a `null`
one — a creation with `Password: null` answers `200` and leaves an account with `HasPassword`
false — so nothing this gate could send made the second step fail on an account the first had
already committed.

#### 3.2.1 What a name may be

The reference accepts a name that is not blank and matches its own expression — **unicode letters
and digits, space, dash, apostrophe, underscore, period, `@` and `+`, and neither a leading nor a
trailing space** `[source: UserManager.cs:119-120, 900-908 @ v10.11.11]`. Anything else raises with
a message that does not list the same characters as the expression does — the message names dashes,
underscores, apostrophes and periods and omits space, `@` and `+`.

**What an administrator sees when it raises is not in the document** `[spec: CreateUserByName]` —
the operation declares `200`, `401`, `403` and `503` and no refusal at all. Measured on 2026-09-16,
and **the answer is four envelopes rather than one**.

**Error responses** — all measured `[probe: tools/probe_user_administration.py, Jellyfin 10.11.11,
2026-09-16]`

| Condition | Status | Body |
|---|---|---|
| No token, or a token that is not an administrator's | `401` / `403` | 002's shapes, from the reference's elevation policy |
| A name that is empty, or only whitespace | `400` | The validation document, keyed on the property: `…"errors":{"Name":["The Name field is required."]}` |
| A name holding a character the expression refuses, **or a name another account already holds, in any case** | `400` | `text/plain`, the six words `Error processing request.` |
| A body with no `Name` | `400` | The validation document, keyed on `$`, quoting the deserialiser |
| A body that is not an object | `400` | The validation document, keyed on `$` |
| **No body at all** | **`415`** | `{"title":"Unsupported Media Type","status":415,…}` — not a `400` |

**The message the source carries never reaches the wire, and that is the finding of this section.**
`ThrowIfInvalidUsername` raises with a sentence naming which characters are allowed, and
`CreateUserAsync` raises with *"A user with the name '…' already exists."*
`[source: UserManager.cs:296-315, 900-908 @ v10.11.11]`. Both arrive as the **same six words**, so
**a client cannot tell an invalid name from one already taken** — and neither can an operator at a
terminal, which is §3.7's problem and not this section's to solve.

**And none of the eight refusals left an account behind**, which is the half of OQ-4 that could be
measured: the count on `GET /Users` was unchanged after every one.

### 3.3 `POST /Users/{userId}/Policy` — `UpdateUserPolicy`

**Request** — the whole policy document in the body `[spec: UpdateUserPolicy]`. It is a
**replacement, not a patch**, and that was measured rather than inferred: a property the caller
leaves out comes back as the **type's default** and not as its previous value. Each was moved off
its own default first, so *kept* and *reset* could be told apart
`[probe: tools/probe_user_administration.py, Jellyfin 10.11.11, 2026-09-16]`:

| left out of a whole document | was | came back |
|---|---|---|
| `EnableAllFolders` | `false` | `true` |
| `EnableMediaPlayback` | `false` | `true` |
| `LoginAttemptsBeforeLockout` | `7` | `-1` |
| `MaxActiveSessions` | `3` | `0` |
| `EnableContentDownloading` | `false` | `true` |

**Two properties are required and are refused rather than defaulted**: `PasswordResetProviderId`
and `AuthenticationProviderId`. Leaving either out of an otherwise whole document answers `400`
with the validation document keyed on that property — which means **a body naming one property is
refused before the route runs**, and so is an empty one. A caller that wants to change a single
property must read the account's policy back and send it whole; that is not a convenience, it is
the only thing the route accepts (§3.7).

**A property the reference has never heard of is accepted and dropped**: the update answers `204`
and the property does not come back. §3.6 says what this server does about that.

**Response — 204**, empty.

**The four refusals, in the order the reference tests them**
`[source: UserController.cs:438-478 @ v10.11.11]`, measured on 2026-09-16:

| Condition | Status | Body, as it arrived |
|---|---|---|
| No account with that id | `404` | The framework's `{"title":"Not Found","status":404,…}` — **and the document does not declare it** `[spec: UpdateUserPolicy]` |
| The **all-zeros** identifier | `400` | `text/plain`, `Error processing request.` — a different answer for an identifier that is well formed and belongs to nobody, and the shape 009 met on `POST /Playlists` |
| An identifier that is not one | `400` | The validation document, keyed on `userId` |
| Taking administrator away from the only administrator | `403` | `"There must be at least one user in the system with administrative access."`, JSON-encoded — [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s fourth shape |
| Disabling an account that is an administrator | `403` | `"Administrators cannot be disabled."`, the same shape |
| Disabling the only enabled account | — | **Not reached, and the reason is the row above it.** It fires only when the account being disabled is the last enabled one, and on a server reached from a running start that account is an administrator, which the previous guard refuses first. Stated here because a criterion cannot assert what no request can produce |

**A refused update changes nothing**: the administrator's `IsAdministrator` and `IsDisabled` were
read back after both refusals and neither had moved.

**A disabling that succeeds revokes that account's tokens**, every one but the caller's own
`[source: UserController.cs:471-472 @ v10.11.11]`, and OQ-6 measured what a client sees: the
update answers `204`, the token the account was holding answers `401` on its next request, and a
fresh sign-in answers `403`. The account stays on `GET /Users` and is found by
`GET /Users?isDisabled=true`. What a revoked token means for a session this server is tracking, and
for a playback report arriving on one, is 002's and 007's and is unchanged by this feature.

### 3.4 `POST /Users/Password` — `UpdateUserPassword`

**Request** — `userId` in the **query** and not in the path, and a body of four properties:
`CurrentPassword` (a hash, and legacy), `CurrentPw`, `NewPw`, `ResetPassword`
`[spec: UpdateUserPassword, UpdateUserPassword schema]`. An absent `userId` means the caller's own
account `[source: UserController.cs:273-281 @ v10.11.11]`.

**Response — 204**, empty.

**Three paths through one operation** `[source: UserController.cs:273-317 @ v10.11.11]`:

1. **`ResetPassword: true`** — the account's password is cleared, and nothing else in the body is
   read. This is *"reset password"* in the roadmap's v2 row, and OQ-8 measured exactly what it
   leaves: `204`, `HasPassword` and `HasConfiguredPassword` both `false`, **the account then signs
   in with no password at all and answers `200`**, and the old password answers `401`. So an
   administrator who resets a password leaves an account anybody who knows its name can enter.
   **Decided on 2026-09-16: this server does the same**, and the defect is recorded with its
   argument in [behaviours §3.33](../../docs/compatibility/behaviours.md) rather than quietly
   improved — refusing a request that succeeds against every Jellyfin there is is the dangerous end
   of [§3.0.3](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made)'s list, and a
   client that resets a password and then signs in with none is a client that works everywhere
   except here.
2. **An administrator changing another account's password** — `CurrentPw` is **not** checked, and
   it answers `204`. The condition is written as *"not an administrator, or the caller named itself
   in `userId`"*, so an administrator changing its own password **through an explicit `userId`**
   must give the current one, and the same administrator omitting `userId` need not. **The
   asymmetry is real and it is on the wire** (OQ-9): the same administrator, the same body, two
   requests differing only in a query parameter naming its own account, answered `403` *"Invalid
   user or password entered."* and `204`.
3. **Anyone changing their own password** — the current password is checked by authenticating it,
   and a wrong one answers `403` *"Invalid user or password entered."*

**A password that changes revokes that account's other tokens**, keeping the caller's
`[source: UserController.cs:309-313 @ v10.11.11]`.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| No account with that id | `404` | The document *describes* it as *"User not found."*; the source answers an empty refusal `[source: UserController.cs:277-281 @ v10.11.11]`. **Not measured** — the gate read this route's two `403`s and not its `404`, which is the one hole it left |
| A caller who is neither the account nor an administrator | `403` | `"User is not allowed to update the password."`, JSON-encoded — measured |
| A wrong current password | `403` | `"Invalid user or password entered."`, JSON-encoded — measured |

### 3.5 `DELETE /Users/{userId}` — `DeleteUser`

**Response — 204**, empty. `404` when no account has that id `[spec: DeleteUser]`.

**Deleting an account takes three things with it, in this order**
`[source: UserController.cs:155-167 @ v10.11.11]`:

1. **Every token that account holds** is revoked.
2. **Every playlist that account owns** is removed — which in this server is
   [009](../009-playlists/spec.md)'s structural state, and the only state in the store a rescan
   cannot rebuild ([roadmap](../../docs/roadmap.md)). **Measured, and it is not every playlist**
   (OQ-10): the owner's **private** playlist answered `404` afterwards and its **public** one
   answered `200` — still there, still named, owned by an account that no longer exists.
   **Decided on 2026-09-16 as OQ-17: this server reproduces the orphan.** A public playlist is
   content other accounts read, and removing it because whoever created it is gone destroys data
   they were using; the reference keeps it, and so does this. What such a playlist then answers for
   the field naming its owner is the plan's, and it lands in 009's store.
3. **The account itself**, which then answers `404` to a second deletion, and whose token answers
   `401`.

**What the reference does not refuse here was this document's sharpest claim from the source, and
it did not survive the gate.** Nothing in `DeleteUser` checks that an administrator is left
`[source: UserController.cs:155-167 @ v10.11.11]` — and the server refuses anyway:
**`400 text/plain Error processing request.`**, the guard being below the controller rather than
in it. A reading of a method is not a reading of a server, which is what Principle II's provenance
rule is about (OQ-11).

**And the refusal is not free — this is the finding.** The controller runs its first two steps
**before** the one that raises: every token the account holds is revoked, and its playlists are
removed, and only then does the deletion refuse. So a refused deletion of the last administrator
leaves that administrator **signed out of every session** on a server where it is the only one. The
account survives and signs in again, so nothing is lost; but the run that measured it first
reported the consequence as a cleanup failure, and only the third reading named it.

**Decided on 2026-09-16 as OQ-15: this server refuses first and touches nothing.** The check that an
administrator is left happens before anything is revoked or removed, so a refused deletion changes
no state at all. **It is a divergence, and what makes it takeable is that a client cannot see it**:
the request answered a refusal before and answers a refusal now, nothing that succeeds against a
reference server is refused here, and what goes away is an effect of a request that was already
failing. Argued in [behaviours §3.34](../../docs/compatibility/behaviours.md).

### 3.6 What an account answers, and what it acts on

**Today an account this server makes answers eleven of the reference's forty-two policy properties
and an empty configuration** `[probe: tools/differential.py --fixture, Jellyfin 10.11.11,
2026-09-07]` — 307 of that run's 1231 differences are that fact, on three routes 002 already
serves. The accounts were written by hand because no route made them; this feature makes the route,
and the document the route stores is the document the three read routes must answer.

**OQ-7 was decided on 2026-09-16, and the decision is that this feature draws no split of its
own.** [002 §3.5](../002-authentication-users-and-sessions/spec.md) drew one when it specified what
an account *is*, and it is the one this feature adopts:

- **Stored and answered in full** — all **42** policy properties and all **15** configuration
  properties, whatever this server does with each. A document sent here comes back from all three
  read routes with the same set of properties and the same values. *(Fifteen and not sixteen: the
  count was read off the instance on 2026-09-16 and [behaviours §3.5](../../docs/compatibility/behaviours.md)'s
  sixteen is a 2026-08-28 reading of a differently configured server.)*
- **A property this server has never heard of is dropped, as the reference drops it** — decided on
  2026-09-16 as OQ-16, on the reading that the reference answers `204` and does not send it back.
  **This corrects something that is already in the code**: 002's policy reader keeps an unknown
  property on purpose, reasoning that *"a client that round-trips a policy from a newer server must
  get its own data back"* — a sound argument for a behaviour nobody had measured, and the measured
  reference does the opposite. Principle V: replicate. 002's own claim is amended in the same change
  as the code.
- **Acted on — the fourteen 002 already enforces**, and not a property more. Whether the account
  is an administrator, disabled or hidden; whether it may play media, delete content and from
  which libraries; which libraries it may open at all; the lockout counts and the session ceiling;
  and the three a negotiation reads — whether video may be transcoded, whether audio may be, and
  whether a stream may be remuxed.
- **Carried and not acted on — the other 28**, which is an accepted gap and is named as one in
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) with the feature
  that would own each. A property stored and ignored is a gap; a property silently dropped is a
  divergence, and this feature intends the first.

**Why the decision is *adopt* rather than *choose*.** Honouring one more property is not a line of
policy code here — 002 made the enforced set structural, so a property anything *queries* has a
column of its own and promoting one is a migration somebody takes on purpose. A feature that
quietly widened the set from a route would undo exactly the visibility that choice bought. So
what 015 changes is **who can write the document**, and nothing about what reading it means.

**What this fixes is therefore a supply, not a semantics.** The eleven above are eleven because
nothing ever seeded the other 31: the columns and the two lists have defaults and the blob was
empty. A route that stores what the reference sends fills the blob, and the 307 differences go
away without a single property changing meaning.

### 3.7 The client

The client [014 §3.8](../014-first-time-setup/spec.md) built gains five commands, each one of the
five operations above and nothing else: creating an account, listing accounts, setting a policy,
setting a password, and removing an account. It signs in the way 014's commands sign in, asks for
passwords the way they ask, and reaches the server over the same addresses.

**What it must not do** is compose a policy the operator did not ask for. §3.3's body is a whole
document, so a command that sets one property has to send the other forty-one — and after the gate
this is not a preference: **a body naming one property is refused `400`**, so reading the account's
policy back and sending it whole is the only thing that works. Where the read goes in the command is
the plan's (OQ-13).

**And it must say which refusal it met**, which §3.2.1 makes harder than it sounds: an invalid name
and a name already taken arrive as the same six words. A command that prints `Error processing
request.` and stops has told the operator nothing; what it does instead — listing the accounts, or
naming the two possibilities — is the plan's (OQ-13).

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
3. A name another account holds, in any case, is refused `400` `text/plain` `Error processing
   request.`, and **no second account exists afterwards**.
4. A name that holds a character §3.2.1's expression refuses is refused the same way; a name that
   is empty or only whitespace is refused `400` with the validation document keyed on `Name`; a
   request with no body at all is refused **`415`**. After each, no account exists.
5. `GET /Users` answers every account the server holds, ordered by name; `isHidden` and
   `isDisabled` each narrow it as the reference narrows it. An **administrator** reads every row
   carrying the whole policy and configuration §3.6 requires; **any other authenticated caller**
   reads its own row whole and every other row with both properties **absent** (§3.1.1).
6. A policy sent for an account is stored whole and answered whole by all three read routes — the
   reference's **forty-two** properties and the configuration's **fifteen**, not eleven and an empty
   object — and a property this server has never heard of is **dropped**, as the reference drops it
   (§3.6).
7. Each of §3.3's refusals that a request can reach is refused, with its status and its body: an
   account that does not exist is `404`, the **all-zeros** identifier is `400` `text/plain`, an
   identifier that is not one is the validation `400`, the last administrator demoted and an
   administrator disabled are each `403` with the reference's sentence JSON-encoded. *The fourth
   guard of the source — the last enabled account — is unreachable and has no test, which §3.3
   states rather than leaves to be discovered.*
8. An account disabled by a policy update cannot sign in afterwards, and the tokens it held no
   longer authenticate — except the caller's own, per §3.3.
9. An administrator sets another account's password without giving the current one; that account
   signs in with the new password and not with the old one.
10. An account changing its own password must give the current one, and a wrong one is refused
    `403` with §3.4's body.
11. `ResetPassword: true` answers `204` and clears the password: the account's document carries
    `HasPassword` false, **a sign-in with no password answers `200`**, and the old password answers
    `401` — the reference's behaviour, reproduced on purpose and recorded in
    [behaviours §3.33](../../docs/compatibility/behaviours.md).
12. Deleting an account revokes its tokens, leaves it absent from `GET /Users`, and answers `404`
    to a second deletion of the same identifier. It removes the **private** playlists it owns and
    leaves the **public** ones, which is what the reference does (§3.5) and what OQ-17 is about.
13. The client performs all five operations against a server it set up, over HTTP alone, and a run
    of it on a fresh server produces a second account whose policy a Jellyfin client sees.
14. **The differential harness stops building its restricted seat by hand**: the run creates the
    seat through §3.2 and §3.3 and destroys it through §3.5, and `tools/README.md` steps 3 and 4
    lose the paragraphs that say it cannot.
15. **Each of the fourteen properties 002 enforces changes what the account can do when it is set
    through §3.3**, asserted at the HTTP boundary and not by reading the store: an account made an
    administrator may perform §3.2 and could not before; an account whose `EnabledFolders` names one
    library sees that library and no other; an account refused media playback is refused a
    negotiation; and the same for the rest of the fourteen, one assertion each.
16. **A property among the other 28 is carried and acts on nothing**: set through §3.3, it comes
    back unchanged from all three read routes, and the behaviour its name describes is unchanged —
    and [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) names the 28
    as a gap, each with the feature that would own it. A criterion that asserts the gap is what
    stops it from being a divergence nobody wrote down.
17. **The same rule holds on the two roads 002 already serves** (§3.1.1): `GET /Users/Public`
    answers no `Policy` and no `Configuration` to anybody, and `GET /Users/{userId}` answers both to
    the account itself and to an administrator and neither to any other caller — the properties
    absent rather than emptied, and every other property of the object unchanged.
18. **The harness reports the withholding as a declared divergence, not as a difference**: the
    restricted seat's readings of the three roads are excused by allowlist entries citing
    [behaviours §3.5](../../docs/compatibility/behaviours.md) and §3.22, and a run in which the
    fields come back to a caller who may not see them fails.
19. **A policy body is a whole document or it is refused**: a body naming one property, and an
    empty body, are each `400` with the validation document keyed on `PasswordResetProviderId`;
    an otherwise whole document missing either provider identifier is refused the same way; and a
    whole document with any other property left out is accepted, that property taking its default
    and not its stored value.
20. **The last administrator cannot delete itself, and the refusal changes nothing**: the deletion
    is refused, and afterwards the caller's token still works, the account's playlists are still
    there, and the account is still on `GET /Users` — which is §3.5's divergence from the
    reference, asserted rather than inherited.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `GET /Users` | L2 | The suite asks it and asserts the order, the filters and the document |
| `POST /Users/New` | L2 | The suite asserts the created document and every refusal of AC-3 and AC-4 |
| `POST /Users/{userId}/Policy` | L2 | The suite asserts the round trip and the four refusals |
| `POST /Users/Password` | L2 | The suite asserts the three paths of §3.4 |
| `DELETE /Users/{userId}` | L2 | The suite asserts AC-12 |

**Two rows that are not in this table are changed by this feature, and they keep their levels.**
`GET /Users/Public` and `GET /Users/{userId}` are 002's, at the levels 002 declared; what they gain
here is §3.1.1's rule and the assertions of AC-17 — a surface row is not re-levelled because a
feature changed what one of its callers sees.

**L3 is owed rather than claimed, and by less than 014 owed it.** The harness needs no new ability
to reach these five — it holds an administrator's token already, and AC-14 makes it *create* the
seat it compares. Whether that makes them L3 rows in this feature or in the change that pays 014's
own L3 debt is OQ-2.

Levels are defined in [../../docs/compatibility/conformance.md](../../docs/compatibility/conformance.md).

## 7. Open questions

**Fifteen of the seventeen are closed, and the two that are not are the plan's** — OQ-2 and
OQ-13, which is where 014 left four of its own.
The eight readings were taken on 2026-09-16, on a single-use instance of the pinned version, and
they are in [notes/user-administration-readings.md](notes/user-administration-readings.md)
`[probe: tools/probe_user_administration.py, Jellyfin 10.11.11, 2026-09-16]`. **Two claims this
document made from the source did not survive them** — the last administrator can be refused its
own deletion, and a deletion removes only the private playlists — and the readings raised **OQ-15,
OQ-16 and OQ-17**, all three decided by the operator the same day.

**The gate took four runs.** One died before answering, which is
[010 plan §7](../010-conformance-harness/plan.md)'s measured `SIGILL` start; after each of the
other three a close reading moved something, twice because the probe was measuring the wrong thing
— an absent account that was really the all-zeros identifier, and an omitted property that was
already sitting on its default. The note records all four, because a reading that had to be taken
three times is a reading whose first two answers were wrong in a way the next feature can repeat. OQ-3, OQ-7, OQ-12 and OQ-14 were
all taken on 2026-09-16, and **one of them was taken twice**: OQ-3's first answer — *narrow it, as
009 narrowed its own* — met an argument older than this feature, because the disclosure it narrows
is already replicated on two other roads by entries that bind all of them into one change. It was
restated as OQ-14 and decided in the shape that clears the collision: the **fields**, not the
routes, on all three roads. Nothing else in this document is settled — every refusal, every
default and every edge still waits on a reading — so **it stays `Draft`.**
Like 011, 012 and 014, this feature opens with its questions open and no measurements of its own,
and there is one place the readings can be taken: **the single-use reference instance**
`[tools/reference_instance.py]`, which runs the pinned version and is destroyed with everything it
wrote. The operator's own server cannot take them — it answers `12.0.0` since 2026-09-12 and a
reading from it is not a reading of the pinned contract — and every question below **writes**, which
is exactly what the disposable instance exists for.

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | ~~What do the refusals of §3.2, §3.2.1 and §3.3 answer on the wire?~~ **Answered on 2026-09-16, and there are four envelopes rather than one**: the framework's validation document for an empty name, a missing `Name`, a body that is not an object and a bad filter; `text/plain` `Error processing request.` for an invalid name **and for a duplicate**, which a client cannot tell apart; `415` for no body at all; and JSON-encoded bare strings for the policy guards. `POST /Users/{userId}/Policy` answers the `404` its document does not declare | §3.2, §3.3, AC-3, AC-4, AC-7 | Closed. §3.1 to §3.4 amended; AC-3, AC-4 and AC-7 amended |
| OQ-2 | Are these five rows `L3`, or `L2` with `L3` owed to 014's own L3 change? | §6 | The plan |
| OQ-3 | ~~`GET /Users` answers every account, with its policy, to **any** signed-in caller. Reproduce it, or narrow it to an administrator as 009 narrowed its own disclosure?~~ **Decided on 2026-09-16: narrow it** — and the decision took a second pass, because this document had not found what it collides with when it asked: [behaviours §3.5](../../docs/compatibility/behaviours.md#35-userspublic-discloses-every-users-policy-to-anyone--class-b-diverged--decided-2026-09-16-not-yet-implemented) and [§3.22](../../docs/compatibility/behaviours.md#322-any-authenticated-caller-reads-any-user-whole--class-b-diverged--decided-2026-09-16-not-yet-implemented) are the same disclosure on two roads, both **replicated** with an argument, and both say in their own words that a divergence is taken **on every road in one change** or it is *"the inconsistency, not the protection"*. `GET /Users` is a third road to the identical object. Restated as **OQ-14**, decided the same day, and applied to all three roads at once | §3.1, AC-5 | Closed by OQ-14 |
| OQ-4 | ~~Is §3.2's step 4 reachable — can a creation fail *after* the account exists — and what does it leave?~~ **Answered on 2026-09-16: not reachable from the API**, and recorded as not reached rather than impossible. A creation with `Password: null` answers `200` and leaves an account with no password; no refusal this gate could send failed the second step. And none of the eight refusals left an account behind | §3.2 | Closed. §3.2 amended |
| OQ-5 | ~~A policy body that omits properties: does the reference store the defaults, or keep what was there? And does it refuse a body that is not a whole document?~~ **Answered on 2026-09-16: the defaults, and yes.** An omitted property takes the type's default — each was moved off its default first, so the two answers could be told apart — and `PasswordResetProviderId` and `AuthenticationProviderId` are **required**, so a body naming one property is refused before the route runs | §3.3, §3.7, AC-19 | Closed. §3.3 and §3.7 amended; AC-19 added |
| OQ-6 | ~~What exactly does a disabling revoke, seen from a client?~~ **Answered on 2026-09-16**: the update answers `204`, the token the account held answers `401` on its next request, and a fresh sign-in answers `403`. A streaming session was not measured and is 008's | §3.3, AC-8 | Closed. §3.3 amended |
| OQ-7 | ~~Which policy properties does this server **act on**, and which are stored, answered and ignored as a named gap?~~ **Decided on 2026-09-16: 002's fourteen, unchanged** — this feature stores and answers all 42 and all 15, acts on exactly the set 002 made structural, and names the other 28 as a gap. Promoting a twenty-ninth is a migration and a decision of its own (§3.6) | — | Closed. §2 and §3.6 amended; AC-6 amended; AC-15 and AC-16 added |
| OQ-8 | ~~What does an account with a cleared password do — sign in with an empty password, with none, or refuse?~~ **Answered on 2026-09-16: it signs in with none, and answers `200`.** The old password answers `401`. **Decided the same day: replicate**, with the defect argued in behaviours §3.33 | §3.4, AC-11 | Closed. §3.4 amended; AC-11 amended |
| OQ-9 | ~~Is §3.4's asymmetry real on the wire?~~ **Answered on 2026-09-16: yes.** The same administrator, the same body, two requests differing only in a query parameter naming its own account: `403` *"Invalid user or password entered."* and `204` | §3.4, AC-9, AC-10 | Closed. §3.4 amended |
| OQ-10 | ~~Deleting an account removes the playlists it owns. What happens to one another account can see?~~ **Answered on 2026-09-16, and it is not every playlist**: the owner's private playlist answered `404` afterwards and its **public** one answered `200` — still there, owned by an account that no longer exists. What this server does about the orphan is **OQ-17** | §3.5, AC-12 | Closed. §3.5 and AC-12 amended; OQ-17 raised |
| OQ-11 | ~~Can the last administrator be deleted, leaving a server nobody can administer?~~ **Answered on 2026-09-16: no — and this document said yes.** The guard is below the controller and the refusal is `400` `text/plain`. **The refusal is not free**: the controller revokes the account's tokens and removes its playlists before the step that raises, so a refused deletion signs the administrator out. What this server does about *that* is **OQ-15** | §3.5, AC-20 | Closed. §3.5 amended; AC-20 added; OQ-15 raised |
| OQ-12 | ~~Does this slice keep `POST /Users` and the four library-management operations out, against 014 §2's *"the next slice with the users"*?~~ **Decided on 2026-09-16: yes, both stay out**, which amends 014 §2 rather than disagreeing with it | §2 | Closed. §2 amended |
| OQ-13 | Does the client's account commands' output name a policy property the operator did not set — and if so, how does a command set one property without composing the other forty-one? | §3.7 | The plan, after OQ-5 |
| OQ-14 | ~~**Narrowing the user disclosure — on how many roads?**~~ **Decided on 2026-09-16: the fields, not the routes, on all three.** `Policy` and `Configuration` are absent unless the caller is that account or an administrator (§3.1.1). It is *strictly less information* on a request that still succeeds, which is the shape §3.5 itself calls the least dangerous — and it reinstates the criterion 002 withdrew on 2026-09-01, this time taken **against** the measurement that overturned it rather than in place of one | §3.1, §3.1.1, AC-5, AC-17, AC-18 | Closed. §2 and §3.1 amended; behaviours §3.5 and §3.22 rewritten together as `diverged`, decided and not yet implemented |
| OQ-15 | ~~**A refused deletion has already revoked the account's tokens and removed its playlists** (§3.5). Reproduce the order, or refuse first and touch nothing?~~ **Decided on 2026-09-16: refuse first, touch nothing.** A client cannot see it — the request refused before and refuses now, and what goes away is an effect of an already-failing request | §3.5, AC-20 | Closed. §3.5 amended; AC-20 amended; [behaviours §3.34](../../docs/compatibility/behaviours.md) |
| OQ-16 | ~~What does this server do with a policy property it has never heard of?~~ **Decided on 2026-09-16: drop it, as the reference does.** It corrects 002's reader, which keeps one on an argument nobody had measured | §3.6, AC-6 | Closed. §3.6 and AC-6 amended; 002's claim amended with the code |
| OQ-17 | ~~**A deleted account's public playlists outlive it** (§3.5). Reproduce the orphan, or remove them with the account?~~ **Decided on 2026-09-16: reproduce it.** A public playlist is content other accounts read; removing it because its creator is gone destroys data they were using. What it answers for its owner field is the plan's, in 009's store | §3.5, AC-12 | Closed. §3.5 amended |

## 8. References

- [Roadmap, v2 — the management CLI](../../docs/roadmap.md#v2--the-management-cli): the left
  column's users row, and what *"what is left of v2"* names as the next slice.
- [014 §2](../014-first-time-setup/spec.md#2-scope): the out-of-scope rows this feature picks up,
  and §2.0's constraint, which is unchanged.
- [002 §3.5 and §3.7](../002-authentication-users-and-sessions/spec.md): the enforced fourteen
  §3.6 adopts, the three read routes it fills, the token shapes, and the `401`/`403` bodies.
- [009 §3](../009-playlists/spec.md): the playlists §3.5 deletes, and the disclosure divergence
  OQ-14 is argued against.
- [behaviours §3.5](../../docs/compatibility/behaviours.md#35-userspublic-discloses-every-users-policy-to-anyone--class-b-diverged--decided-2026-09-16-not-yet-implemented)
  and [§3.22](../../docs/compatibility/behaviours.md#322-any-authenticated-caller-reads-any-user-whole--class-b-diverged--decided-2026-09-16-not-yet-implemented):
  the same disclosure on two roads, replicated, and the clause that binds a divergence to all of
  them at once. OQ-14 is that clause meeting a third road.
- [`tools/README.md`](../../tools/README.md), steps 3 and 4: what the harness builds by hand, and
  the 2026-09-07 and 2026-09-08 sweeps that price it.
- Jellyfin at `v10.11.11`, neither file touched by the local fork:
  `Jellyfin.Api/Controllers/UserController.cs`, `Jellyfin.Api/Helpers/RequestHelpers.cs`,
  `Jellyfin.Server.Implementations/Users/UserManager.cs`.
- The `10.11.11` OpenAPI document: `CreateUserByName`, `GetUsers`, `UpdateUserPolicy`,
  `UpdateUserPassword`, `DeleteUser`, and the `CreateUserByName`, `UpdateUserPassword`,
  `UserPolicy` and `UserDto` schemas.
