---
feature: 014-first-time-setup
title: First-time setup
status: Draft
created: 2026-09-13
updated: 2026-09-13
amended: 2026-09-13 at the spec gate - OQ-1 decided (the setup window is open to a loopback address only, by changing the reference's first branch and nothing else) and OQ-2 decided (the first account is always MyJellyfinUser); sections 3.1, 3.2 and 3.8, AC-2, AC-5 and AC-10 amended; OQ-11 raised by the first answer. And the same day, OQ-3 decided (a library name already in use is numbered as the reference numbers it); section 3.6 amended and section 3.6.2 added for the order a name is cleaned in; AC-7 amended; OQ-5 widened to confirm that names compare with case. And the same day, at the measurement gate, OQ-4, OQ-5, OQ-7 and OQ-8 answered and OQ-6 half answered by tools/probe_first_time_setup.py on an instance started unconfigured; two claims made from the source withdrawn (the missing-path body, and the empty-name refusal's origin); sections 3.1, 3.3 to 3.7 and 3.8 amended; AC-3, AC-4, AC-5, AC-7 and AC-8 amended; OQ-12 and OQ-13 raised. And the same day, OQ-6 decided (every library type answered and stored as the reference does, a library of a type this server cannot scan staying empty as an accepted gap) and OQ-12 decided (library scan does not wait); sections 3.6, 3.6.1, 3.7 and 3.8 amended; AC-7 and AC-9 amended
depends_on: [001, 002, 003]
---

# 014 — First-time setup

> **This document describes WHAT and WHY only.** No technology names. No storage decisions. No
> module or function names. If you need to write one, it belongs in `plan.md`.

## 1. Purpose

**A fresh server can be brought, from a terminal and with nobody running a wizard, to a first
administrator and a first library** — over Jellyfin's own first-time-setup operations, spoken by a
command-line client that has no other way into the server. After it, any unmodified Jellyfin client
can sign in and browse.

It is the first slice of [v2](../../docs/roadmap.md#v2--the-management-cli), and the smallest one
that makes the server usable at all. **Today nothing creates even the first account**: no operation
the server answers, no file it reads and no command it offers brings a user or a library into
existence, so a server started from scratch is one nobody can sign in to. Every account and every
library in this repository's history was written by a test.

## 2. Scope

### 2.0 Why these operations, and why they are not a side door

The roadmap fixes the one constraint that decides this feature: *"the CLI is a **client**. It speaks
HTTP to the same endpoints any other client could call, holds a token obtained the same way, and
has no access to the database or the configuration files that the API does not also give it"*, and
lists *direct database access* and *a second authentication path for "local" callers* as out of v2.

That constraint and a fresh server meet in a chicken-and-egg. **Creating a user requires an
administrator** — `CreateUserByName` declares elevation `[spec: CreateUserByName, the security
requirement declared on it]` — **and a fresh server has none.** A client with no side door therefore
cannot create the first account through the operation the roadmap names for creating accounts.

Jellyfin resolves exactly this with a separate authorisation policy, *first-time setup or
elevated*, which it declares on the startup operations and on the library-structure operations and
on nothing that creates a second user `[spec: GetFirstUser, UpdateStartupUser, CompleteWizard,
GetVirtualFolders, AddVirtualFolder, the security requirement declared on each]`. While setup is
unfinished, that policy admits any caller on the reference `[source:
Jellyfin.Api/Auth/FirstTimeSetupPolicy/FirstTimeSetupHandler.cs:29-32 @ v10.11.11]`.

**So the first administrator can only arrive through these operations**, and that is the whole
argument for serving them: they are Jellyfin's, a Jellyfin that is set up unattended is set up
through them, and this repository already sets the reference up through exactly this sequence with
nobody at a keyboard `[source: tools/_reference.py:681-770, which drives UpdateInitialConfiguration,
UpdateStartupUser, CompleteWizard and AddVirtualFolder against the pinned reference]`. It is not a
helper route added for a tool's convenience, which [Principle I](../../docs/constitution.md) and the
roadmap's v3 rule forbid in the same words.

The roadmap's v2 table names `GetVirtualFolders`, `AddVirtualFolder` and `RefreshLibrary` and does
**not** name the startup operations. This section is the argument for adding them, and the
roadmap's own rule admits it: *"The v1 endpoint set grows accordingly, under the same rule as every
other row in it: an endpoint enters the table with its provenance, or it does not enter."*

### 2.1 What this closes that was left open

**001's OQ-3 is answered here.** 001 asked whether `StartupWizardCompleted` is meaningful for a server
with no wizard, and resolved it as *"a decision in 002, where user creation happens"*. 002 does not
create users, so the decision was never taken, and the property has answered `false` on every
server for the life of the project — including servers a test had populated with accounts. After
this feature it answers what it says (§3.1).

### In scope

- The **setup window**: when the first-time-setup operations are open, when they close, and the one
  property that tells a client which (§3.1).
- `GET /Startup/User` and `POST /Startup/User` — the first account (§3.2, §3.3).
- `POST /Startup/Complete` — closing the window (§3.4).
- `GET /Library/VirtualFolders` and `POST /Library/VirtualFolders` — listing and adding a library
  (§3.5, §3.6).
- `POST /Library/Refresh` — scanning every library (§3.7).
- **A command-line client** that performs setup, adds, lists and scans libraries through the
  operations above and through operations already served, and through nothing else (§3.8).

### Out of scope

- **A second account, and every other user operation** — `POST /Users/New`, policy updates, password
  reset. They require an administrator, which this feature makes exist; they are the next slice.
- **Renaming or removing a library, or changing its paths** — `RenameVirtualFolder`,
  `RemoveVirtualFolder`, `AddMediaPath`, `RemoveMediaPath`. The next slice with the users.
- `GET`/`POST /Startup/Configuration` and `POST /Startup/RemoteAccess`. Setting a server name, a
  metadata language and a remote-access flag is not needed to sign in or browse. Measured on
  2026-09-13: a setup that omits them leaves a server its first account signs in to and browses,
  whose `ServerName` is then the host's own name (OQ-7).
- **Server configuration read and update** — the roadmap's v2 row for it is a later slice.
- **Any operation Jellyfin does not have.** A convenience this client wants and the API lacks, the
  client does without.
- The management UI, which is v3.

## 3. Behaviour

### 3.1 The setup window

**The reference** opens the first-time-setup operations of §3.2 to §3.6 **to any caller while setup
is unfinished** — with a token, without one, and from any address — and **requires an administrator
once it is finished** `[source: Jellyfin.Api/Auth/FirstTimeSetupPolicy/FirstTimeSetupHandler.cs:29-47
@ v10.11.11]`. Both controllers carry the policy whole `[source:
Jellyfin.Api/Controllers/StartupController.cs:19, LibraryStructureController.cs:30]`, and it is the
variant that **requires an administrator** — registered with no arguments, whose default is
`requireAdmin: true` `[source: Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs:77 and
Jellyfin.Api/Auth/FirstTimeSetupPolicy/FirstTimeSetupRequirement.cs:15]`, where its sibling
`FirstTimeSetupOrDefault` passes `false`.

**This server opens the window to this machine only** — a deliberate exception, decided on
2026-09-13 and argued in [behaviours §4.6](../../docs/compatibility/behaviours.md). The reference's
decision is three branches in order; this server changes **the first one and nothing else**:

```
reference     setup unfinished                                  -> admit
this server   setup unfinished  AND  the caller is this machine  -> admit
then, both    the caller is an administrator                    -> admit
              the caller is not                                 -> refuse
```

So a caller from elsewhere during setup is not refused by anything new. It falls through to the
branches the reference already takes once setup is finished, and **no refusal is invented**:

| Setup | Caller is | Caller | Outcome |
|---|---|---|---|
| unfinished | **this machine** | anyone, authenticated or not | admitted |
| unfinished | elsewhere | an administrator | admitted |
| unfinished | elsewhere | an authenticated non-administrator | refused, `403` |
| unfinished | elsewhere | no token | refused, `401` |
| finished | anywhere | an administrator | admitted |
| finished | anywhere | an authenticated non-administrator | refused, `403` |
| finished | anywhere | no token | refused, `401` |

**"This machine" means a loopback address, and only that.** A request that reaches the server
through one of the machine's network addresses is from elsewhere even when it was sent from the same
machine — so a client on the server that addresses it by its LAN address is refused during setup.
This is stricter than the reference's own notion of a *local network*, which admits a whole subnet
and is what [behaviours §4.5](../../docs/compatibility/behaviours.md) is about; the two must not be
confused, and the loopback rule is the one decided.

**The address is the one the request arrived from, as this server determines it**, which is not
always the machine that originated it: a reverse proxy on the same machine that does **not** pass
on the original client's address makes every request it forwards look local, and would reopen the
window to the network behind it. How the address is determined, and what an operator running
behind such a proxy has to configure, is OQ-11 — and it decides whether this rule is worth what it
says.

`POST /Library/Refresh` is **not** a first-time-setup operation: it requires an administrator in
both states `[spec: RefreshLibrary, the security requirement declared on it]`. It lives in a
different controller from the library-structure operations, carrying its own elevation policy and
no first-time-setup one `[source: Jellyfin.Api/Controllers/LibraryController.cs:331-334 @
v10.11.11]` — which is why a library can be added before setup finishes and cannot be scanned on
its own until afterwards.

**Which state the server is in is observable without a token**, through the property 001 already
serves: `StartupWizardCompleted` on `GET /System/Info/Public` is `false` until §3.4 runs and `true`
from then on, and **survives a restart**. It never goes back.

**Why it is not reproduced.** The reference's window is open to the whole network, and a server
listening on every interface — the default this server ships — could be claimed by whoever reaches
it first, between starting it and setting it up. That was OQ-1 and is closed.

**Both refusals carry no body and no `Content-Type`**: the `401` is [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s
unauthenticated shape, and the `403` is the empty one an authorisation policy answers — the shape
[behaviours §4.5](../../docs/compatibility/behaviours.md) records for a policy refusal of its own,
and not §1.11's 25-byte controller refusal. Both were measured once setup was finished `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`.

### 3.2 `GET /Startup/User` — `GetFirstUser`

**Consumers:** the command-line client of §3.8. No analysed client calls it.

**A read that writes.** If no account exists, this operation **creates one** before answering, and
this is the only thing in the reference that creates the first account
`[source: Jellyfin.Api/Controllers/StartupController.cs:110-119 and
Jellyfin.Server.Implementations/Users/UserManager.cs:700-727 @ v10.11.11]`. The reference marks it
as a debt in both places — *"Remove this method when startup wizard no longer requires an existing
user"* — and it is what every unattended setup has to call first, because §3.3 cannot create.

The account it creates:

| Property | Value |
|---|---|
| Name | **always `MyJellyfinUser`**. The reference uses the name of the operating-system account the server runs as, and falls back to `MyJellyfinUser` only where that name is empty or not a valid username `[source: UserManager.cs:711-715]`; this server always takes the fallback — a deliberate exception decided on 2026-09-13 ([behaviours §4.7](../../docs/compatibility/behaviours.md)), and not an invented name, because it is the reference's own |
| Administrator | yes `[source: UserManager.cs:720]` |
| May delete content, may control other users' sessions | yes `[source: UserManager.cs:721-722]` |
| Hidden from the sign-in screen | yes — which is why `GET /Users/Public` answers `[]` on a server nobody has configured ([002 §3.4](../002-authentication-users-and-sessions/spec.md)) |
| Password | none |

If an account already exists, nothing is created. Calling it twice creates one account.

**Request:** none.

**Response — 200**

```json
{ "Name": "MyJellyfinUser" }
```

| Field | Type | Notes |
|---|---|---|
| `Name` | string | The first account's name. `Password` is declared on the same shape `[spec: StartupUserDto]` and is never answered |

**Error responses:** the refusals of §3.1 once setup is finished, with the bodies §3.1 gives.

### 3.3 `POST /Startup/User` — `UpdateStartupUser`

**Consumers:** the command-line client of §3.8.

**It updates the first account and never creates one.** A server with no account answers `404`
`[source: StartupController.cs:134-138 @ v10.11.11]` — so on a fresh server this operation fails
unless §3.2 ran first, and the order is part of the contract. Measured on an instance whose setup
had not run: `404` before the read, and the read then answering `200` `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`.

**Request — body**

| Name | Required | Type | Notes |
|---|---|---|---|
| `Name` | no | string | When present and different from the current name, ignoring case, the account is **renamed** `[source: StartupController.cs:147-151]` |
| `Password` | **yes** | string | Empty or whitespace is refused `[source: StartupController.cs:140-143]`; otherwise the account's password becomes this `[source: StartupController.cs:153-157]` |

**Response — 204**, no body.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| no account exists | `404` | **problem details** ([behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s *item a handler could not find*), `title` `Not Found` `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| `Password` missing, empty or whitespace | `400` | the **JSON-encoded bare string** `"Password must not be empty"`, `application/json; charset=utf-8` — §1.11's *controller that refused with its own message*, and the first `400` of that shape measured `[source: StartupController.cs:142]` `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| a `Name` that is not a valid username — empty, or carrying `/` and `:` were read | `400` | `text/plain`, the fixed `Error processing request.` — §1.11's *controller that refused the request itself*. **The account keeps its name** `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| a `Name` another account holds | `400` | the same `Error processing request.` `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| setup finished, caller not an administrator | §3.1 | §3.1 |

After this operation the account can sign in through `POST /Users/AuthenticateByName`
([002](../002-authentication-users-and-sessions/spec.md)) with the name and password it was given.

### 3.4 `POST /Startup/Complete` — `CompleteWizard`

**Consumers:** the command-line client of §3.8.

**Closes the setup window**, and checks nothing before doing it: it does not require that an account
has a password, or that a library exists `[source: StartupController.cs:41-47 @ v10.11.11]`.

**Request:** none. **Response — 204**, no body.

From this response on, §3.1's rows for a finished setup apply and `StartupWizardCompleted` is `true`.

**Error responses:** once setup is finished, the refusals of §3.1. **A second call is harmless**: an
administrator is answered `204` again and a caller with no token `401` with an empty body
`[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`.

### 3.5 `GET /Library/VirtualFolders` — `GetVirtualFolders`

**Consumers:** the command-line client of §3.8.

**Every library, one entry each.**

**Response — 200** — an array of `[spec: VirtualFolderInfo]`:

| Field | Type | Notes |
|---|---|---|
| `Name` | string | The library's name, as §3.6 settled it |
| `Locations` | array of string | The library's paths |
| `CollectionType` | string | The type the library was added with. **No value where none was given — and no value where the one given is not a type the reference declares** (§3.6.1) `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| `ItemId` | string | The library's own identifier, the one a client browses by |
| `LibraryOptions` | object | The reference sends **37 properties** on every library read, whatever its type `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`. Which of them this server can state truthfully is OQ-13 |
| `PrimaryImageItemId` | string | No value on every library read, none of which had artwork `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| `RefreshProgress`, `RefreshStatus` | number, string | **They show some scans and not others**, read once a second `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`. While a library added with `refreshLibrary=true` was scanned, its row read `Active` with a partial, fractional progress — `10` in one run, `10.666…` in another — then `Idle` and no value once it finished. **While `POST /Library/Refresh`'s scan ran, the row read `Idle` throughout.** So the row can tell a caller a scan it started by adding the library has finished, and cannot tell it about a scan §3.7 started — which shows only on the server's scheduled-task list |

**Error responses:** the refusals of §3.1 once setup is finished.

### 3.6 `POST /Library/VirtualFolders` — `AddVirtualFolder`

**Consumers:** the command-line client of §3.8.

**Request**

| Part | Name | Required | Type | Notes |
|---|---|---|---|---|
| query | `name` | yes | string | Cleaned before use, in the order §3.6.2 gives `[source: Emby.Server.Implementations/Library/LibraryManager.cs:3027-3032 @ v10.11.11]` |
| query | `collectionType` | no | string | `[spec: CollectionTypeOptions]` declares eight values; which of them this server accepts is §3.6.1 |
| query | `paths` | no | string, comma-separated | Each must be a directory that exists **on the server** |
| query | `refreshLibrary` | no | boolean, default `false` | Whether adding the library also scans it |
| body | `LibraryOptions` | no | object | `[spec: AddVirtualFolderDto]`; which properties are honoured is OQ-13 |

**Response — 204**, no body. The library appears in §3.5 and, once scanned, in a client's views.

**The `204` does not wait for a scan, and `refreshLibrary=false` does not mean the library goes
unscanned** `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`:

- **`refreshLibrary=true` answers as the scan starts.** A library that did not exist a moment
  earlier — so could not have been scanned — answered `204` after 0.07 s with **none** of its
  episodes browsable and the scan task `Running`; all nine were browsable once it went idle.
- **A library added with `refreshLibrary=false` was scanned anyway.** Added during setup, it had films
  browsable before any refresh was asked for in every run — 11 of its 17 in two, all 17 in a third —
  so how many depends on how far a scan nobody requested had got, and **none** is never the answer.
  **What started that scan was not isolated**, and this document does not say it was the operation.

**Two behaviours that are not what the operation's name suggests**, both reproduced — the first
decided on 2026-09-13 as OQ-3, and argued in [behaviours §3.30](../../docs/compatibility/behaviours.md):

- **A name already in use is not refused.** The reference appends a number and adds the library under
  the new name, and still answers `204`. **The first number is `2`**, with nothing between the name
  and it — `Movies` becomes `Movies2`, then `Movies3` — because the count starts at one and is
  incremented before it is used; the reference's own comment says *"first numbered name will be
  2"* `[source: LibraryManager.cs:3036-3044]`. The name a caller asked for is therefore not
  necessarily the name the library has, and §3.5 is how a caller finds out.

  **Names collide exactly, case included.** On the reference a collision is whether a directory of
  that name already exists, so it follows the host's filesystem rather than a rule — and the pinned
  reference runs on one that does not ignore case. That pinned instance is what this server
  reproduces, so `movies` and `Movies` are two libraries — **confirmed by a reading**: `movies`
  added beside `Movies` is a library of its own, and `Movies?` became `Movies ` `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`.
- **A path is checked, a name is not.** A path that does not exist refuses the whole request; a name
  that collides does not.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| `name` missing, empty or whitespace | `400` | **problem details with an `errors` map keyed `name`** — [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s *malformed value the model binder rejected*. It is refused by validation of a required parameter **before the route runs**, so the library manager's own emptiness check `[source: LibraryManager.cs:3027-3030]` is not what answers: a name of spaces is refused the same way `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| a path that does not exist on the server | `400` | `text/plain`, the fixed `Error processing request.` — §1.11's *controller that refused the request itself*. **The message the source builds, `The specified path does not exist: <path>.` `[source: LibraryManager.cs:3049-3053]`, is not sent** `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| setup finished, caller not an administrator | §3.1 | §3.1 |

#### 3.6.1 Which library types

This server scans **three** kinds of library — movies, series and music
([003](../003-library-configuration-and-scanning/spec.md), and the roadmap's *Media types* row). The
reference declares eight `[spec: CollectionTypeOptions — movies, tvshows, music, musicvideos,
homevideos, boxsets, books, mixed]`, and an omitted type is its own case.

**`movies`, `tvshows` and `music` are accepted.** The reference accepts **every** other case, and one
more than its own declaration admits `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`:

| `collectionType` | The reference answers | Stored as |
|---|---|---|
| `musicvideos`, `homevideos`, `boxsets`, `books`, `mixed` | `204` | that type |
| omitted | `204` | no type |
| `photos` — **not a value the reference declares** | `204` | **no type**, as if it had been omitted |

So nothing a caller sends for this parameter is refused. **This server answers every one of those
cases as the reference does** — decided on 2026-09-13 as OQ-6: `204`, the five stored with the type
sent, an omitted type and an undeclared one stored with no type. Refusing them would be a status the
reference never answers on this route, and no caller that adds a library has met one.

**What that costs is a library that stays empty.** The reference scans at least three of the five
with resolvers of their own — `homevideos` and `musicvideos` are among the types its film resolver
takes, and `books` has a resolver that runs only there `[source:
Emby.Server.Implementations/Library/Resolvers/Movies/MovieResolver.cs:32-39, Emby.Server.Implementations/Library/Resolvers/Books/BookResolver.cs:24-29 @ v10.11.11]`.
This server's scan admits a candidate only by the rules of 003's three types
([003 §3.1, §3.2](../003-library-configuration-and-scanning/spec.md)), so a library of any other
type, or of none, is listed by §3.5, survives a restart and a scan, and has nothing in it. That is a
shortfall and not a choice, recorded as an accepted gap in
[behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1); **003's set of three
stays the set this server scans**, and what widens is only the set a library can be created with.
What the reference's scan puts in a library of no type was not read.

#### 3.6.2 How a name is cleaned

In this order, each step on the result of the one before:

1. **Refused if empty or whitespace** — `400`, checked on the name **as sent**, by validation of a
   required parameter before the route runs (§3.6's error table) `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`.
2. **Trimmed** `[source: LibraryManager.cs:3032]`.
3. **Every character of a fixed set replaced by a space**: `"`, `<`, `>`, `|`, `:`, `*`, `?`, `\`,
   `/`, the null character and the control characters 1 to 31
   `[source: Emby.Server.Implementations/IO/ManagedFileSystem.cs:21-28, 305-334 @ v10.11.11]`. The
   set is the reference's own list and does not depend on the host.
4. **Compared exactly** against every library's name, and numbered from `2` while it collides.

The order is observable in two places. Trimming comes before replacement, so a replaced character at
either end stays as a space — `Movies?` becomes `Movies ` and does not collide with `Movies`, which
was measured `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`. And the emptiness check comes before both, so a name made only of replaced
characters is accepted and becomes spaces — read from the source and not measured.

### 3.7 `POST /Library/Refresh` — `RefreshLibrary`

**Consumers:** the command-line client of §3.8.

**Scans every library.** Requires an administrator whether or not setup is finished (§3.1).

**Request:** none. **Response — 204**, no body.

**The `204` is sent as the scan starts, not when it ends**: it answered within 0.01 s `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`. A caller
that needs to know a scan has finished cannot learn it from this response, **nor from the library
row, which read `Idle` throughout the scan this operation started** (§3.5); the server's
scheduled-task list is where it shows, and that list is not an operation this feature serves.
**Nothing in this feature waits for one** — decided on 2026-09-13 as OQ-12, so the list stays
outside the surface (§3.8).

**What it does to a scan already running** was read twice: asked while one ran, the scan task read
`Cancelling` immediately after the `204`, and the library then reached all of its films; asked when
none ran, it read `Running`. This document records that and no more: it does not say whether a
running scan is restarted or allowed to finish.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| no token | `401` | no body, no `Content-Type` — measured **during** setup, which is where §3.1 says this operation differs from the rest `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| authenticated, not an administrator | `403` | no body, no `Content-Type` — **the same empty refusal as §3.1's**, measured on this route in its own right because it carries a different policy `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |

### 3.8 The command-line client

**A program an operator runs in a terminal**, pointed at one server.

**It has no way into the server except the operations a client has.** Everything it does is one of
§3.2 to §3.7, or an operation this server already serves: `GET /System/Info/Public` (001) to learn
whether setup is finished, and `POST /Users/AuthenticateByName` (002) to obtain a token. **It reads
and writes no file and no store belonging to the server** — which is the roadmap's constraint, and
it is a property this feature tests rather than asserts.

It does four things:

| Command | Does | Refuses when |
|---|---|---|
| **setup** | Given a name and a password: §3.2, then §3.3, then §3.4. Prints the administrator's name | setup is already finished — reported as such, never attempted; **or the server is not addressed on this machine** — see below |
| **library add** | Given a name, a type and one or more paths: §3.6. Prints the name the library **ended up with**, which §3.6 says need not be the one asked for | the server refuses it — the refusal is printed |
| **library list** | §3.5, one line per library: name, type, paths | the server refuses it |
| **library scan** | §3.7, and reports that a scan **was started**, then exits. It does not wait for the scan and issues nothing to learn whether it finished — decided on 2026-09-13 as OQ-12; an operator sees the result by browsing the library from a client | the server refuses it |

**Setup runs on the server's own machine.** §3.1 admits an unauthenticated caller during setup only
from a loopback address, so **setup** is run on the machine the server runs on — directly, or
through a tunnel that arrives there — against a loopback address. Pointed anywhere else it would be
refused `401` by §3.2 with nothing to say why, so the client does not send it: having learned from
`StartupWizardCompleted` that setup is unfinished, and given an address that is not a loopback
address, it stops **before any setup operation** and says that setup has to be run on the server's
machine. **That check is a courtesy and decides nothing**: the server's rule is the one that admits
or refuses, and a request the client believed local but the server does not — a tunnel whose far end
reaches the server by a network address — is refused by the server and the refusal is printed like
any other. Once setup is finished the restriction is gone, and the other three commands work from
anywhere with an administrator's credentials.

**Signing in.** Before setup is finished, `library add` and `library list` need no credentials
**from this machine** (§3.1). After it, they and `library scan` sign in as an administrator, from
anywhere. Whether the client keeps a token between invocations, and where, is OQ-9.

**What it guarantees an operator**, whatever the command:

- **A password is never printed**, and never accepted on the command line where other processes on
  the machine can read it. Where it comes from instead is OQ-9.
- **Every refusal is printed with the status the server answered and the reason it gave**, and the
  program exits non-zero. A success exits zero.
- **The server's address is required and is never guessed.** A client that fell back to a default
  address would set up whichever server happened to answer there.

## 4. Data the feature owns

What a client can observe change, and what survives a restart:

- **Whether setup is finished.** Observable as `StartupWizardCompleted`; survives a restart; never
  reverts.
- **The first account**: its name, its password, that it is an administrator and hidden. Survives a
  restart. Observable by signing in.
- **Each library**: its name, its type, its paths. Survives a restart. Observable through §3.5 and,
  once scanned, through every browsing operation the server already has.

## 5. Acceptance criteria

1. On a server nobody has set up, `StartupWizardCompleted` is `false`; after `POST /Startup/Complete`
   it is `true`, and it is still `true` after the server restarts.
2. `GET /Startup/User` on a server with no account creates exactly one, an administrator hidden from
   `GET /Users/Public`, and answers its name, which is `MyJellyfinUser` **whatever operating-system
   account the server runs as**; a second call creates nothing more.
3. `POST /Startup/User` on a server with no account answers `404` in problem details; with an empty
   or whitespace `Password` it answers `400` with the JSON string `"Password must not be empty"`;
   with a `Name` that is not a valid username, or that another account holds, it answers `400` with
   `Error processing request.` and leaves the name as it was; otherwise it sets the password, renames
   the account when `Name` differs ignoring case, and the account then signs in with that name and
   password.
4. `POST /Startup/Complete` succeeds with no password set and no library, and closes the window; a
   second call by an administrator answers `204` again.
5. While setup is unfinished, §3.2 to §3.6 admit a caller carrying no token **from a loopback
   address**, and treat a caller from any other address as they treat every caller once setup is
   finished: an administrator is admitted, an authenticated non-administrator refused `403`, and a
   caller with no token refused `401`, both refusals with no body and no `Content-Type`. A client on
   the server's own machine that addresses it by a network address is a caller from elsewhere.
6. `POST /Library/Refresh` refuses a caller with no token `401` and a non-administrator `403` in both
   states, and admits an administrator.
7. `POST /Library/VirtualFolders` with existing paths answers `204` and adds a library that
   `GET /Library/VirtualFolders` then lists with that name and paths, **whatever `collectionType`
   it carries**: one of `movies`, `tvshows` and `music`, or one of the five other declared types, is
   listed with that type, and an omitted type or `photos` is listed with none. A library of a type
   other than those three, or of none, has no item added to it by a scan. A name already in use is
   added under that name followed by `2` (then `3`) and answers `204`, where names are compared exactly,
   case included, after §3.6.2's trimming and replacement; an empty or whitespace name answers the
   validation `400` keyed `name`, a path that does not exist answers `400` with
   `Error processing request.`, and neither adds a library.
8. A library added with `refreshLibrary=true`, or scanned through `POST /Library/Refresh`, is
   browsable by an unmodified Jellyfin client signed in as the first account **once the scan the
   `204` started has finished** — and the `204` itself does not wait for it.
9. The command-line client performs **setup**, **library add**, **library list** and **library
   scan** end to end against a fresh server, and a run of it issues only the operations §3.8 names —
   asserted by recording every request it makes, not by reading its source. **library scan** issues
   exactly one request, `POST /Library/Refresh`, and exits zero on its `204` reporting that a scan was
   started.
10. The client exits non-zero and prints the server's status and reason on every refusal, refuses
    **setup** on a server whose setup is finished without calling §3.2 to §3.4, refuses **setup**
    given a non-loopback address while setup is unfinished without calling §3.2 to §3.4 and says it
    must run on the server's machine, and prints no password in any output.

*Criteria 3, 4, 5, 7 and 8 were amended on 2026-09-13 by the reading that answered OQ-4, OQ-5 and
OQ-8, and criteria 7 and 9 the same day by the decisions that closed OQ-6 and OQ-12. What can still
move them is OQ-11 (how a request's address is determined), amended at the gate that answers it, not
quietly.*

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `GET /Startup/User` | L2 | AC-2, AC-5 |
| `POST /Startup/User` | L2 | AC-3, AC-5 |
| `POST /Startup/Complete` | L2 | AC-1, AC-4, AC-5 |
| `GET /Library/VirtualFolders` | L2 | AC-5, AC-7 |
| `POST /Library/VirtualFolders` | L2 | AC-5, AC-7 |
| `POST /Library/Refresh` | L2 | AC-6, AC-8 |

**L2 and not L3, and L3 is within reach.** The single-use reference instance already runs this exact
sequence against a fresh reference every time it stands up, so a differential over it costs a
comparison and no new machinery. Whether to take it at the plan gate is OQ-10.

Levels are defined in [../../docs/compatibility/conformance.md](../../docs/compatibility/conformance.md).

## 7. Open questions

**Three of the ten were decisions and all three were taken on 2026-09-13** — OQ-1, OQ-2 and OQ-3;
answering OQ-1 raised OQ-11. **The five readings were taken the same day**, on the single-use
instance started unconfigured `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11,
2026-09-13]`: OQ-4, OQ-5, OQ-7 and OQ-8 are closed, OQ-6 was half closed, and the readings raised
OQ-12 and OQ-13. **The two decisions the readings left for the operator were taken the same day** —
OQ-6 (every type answered as the reference answers it) and OQ-12 (no scan is waited for). **Two claims this document had made from the source did not survive them** — see
OQ-4 — **and no claim it makes is left unverified.** The probe was run five times: once the pinned image
failed to start and nothing was measured, and after each of the other four a close reading moved a
claim — so every reading cited here is one the script as committed reproduces. The readings, and
what moved after each run, are in [notes/first-time-setup-readings.md](notes/first-time-setup-readings.md). Four questions remain, all for the plan gate (OQ-9, OQ-10, OQ-11, OQ-13), and **none is the
operator's**.

**This feature opened with its questions unanswered and no measurements of its own**, like 011 and
012. Every one is answered at the gate by a reading, and **there is exactly one place those readings
can be taken**: the single-use reference instance. The operator's server has finished setup and
cannot be put back, and it is no longer the pinned version; the instance starts unconfigured, runs
the pinned version, and is destroyed with everything it wrote — which makes a measurement that
**writes** an account and a library safe to take, and is precisely what it was built for.

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | ~~Is the setup window open to the network, as the reference's is, or to this machine only?~~ **Decided on 2026-09-13: this machine only**, meaning a loopback address and not the local network. Implemented as the smallest possible change to the reference's decision — only its first branch gains *"and the caller is this machine"* — so a caller from elsewhere falls through to refusals the reference already makes and none is invented (§3.1) | — | Closed. [behaviours §4.6](../../docs/compatibility/behaviours.md); AC-5 and AC-10 amended. What it depends on to be worth what it says is OQ-11 |
| OQ-2 | ~~What is the first account called?~~ **Decided on 2026-09-13: always `MyJellyfinUser`**, the reference's own fallback, and never the operating-system account the server runs as (§3.2) | — | Closed. [behaviours §4.7](../../docs/compatibility/behaviours.md); AC-2 amended |
| OQ-3 | ~~Is a name already in use numbered, as the reference does, or refused?~~ **Decided on 2026-09-13: numbered, as the reference does** — from `2`, with no separator, after the name is cleaned in §3.6.2's order, and compared exactly. Class B, replicated: a caller that treats `204` as *"added"* has never met a refusal from a Jellyfin (§3.6) | — | Closed. [behaviours §3.30](../../docs/compatibility/behaviours.md); AC-7 amended. Whether names compare with case is confirmed by OQ-5 |
| OQ-4 | ~~What are the refusal bodies?~~ **Answered on 2026-09-13, and they are four of [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)'s shapes rather than one**: the `404` is problem details; the empty-password `400` is a JSON-encoded bare string; the empty-name `400` is validation problem details keyed `name`; the missing-path and bad-rename `400`s are `text/plain` `Error processing request.`; and the `401` and `403` carry no body at all. **Two claims this document made from the source did not survive it**: the missing-path body is not the message the source builds, and the empty-name `400` is not the library manager's refusal but validation that runs first | — | Closed. §3.1, §3.3, §3.6 and §3.7, AC-3, AC-5 and AC-7 amended `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| OQ-5 | ~~What do the edges answer?~~ **Answered on 2026-09-13.** A rename to an unusable name (empty, or carrying `/` and `:`) or to one another account holds answers `400` `Error processing request.` and leaves the name; a second `POST /Startup/Complete` answers `204` to an administrator and `401` to a caller with no token; and `movies` added beside `Movies` is a library of its own, as §3.6 had stated from the platform | — | Closed. §3.3, §3.4 and §3.6, AC-3 and AC-4 amended `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| OQ-6 | ~~What does this server answer for a library type it cannot scan?~~ **Read on 2026-09-13, and decided the same day: as the reference answers.** The reading: the reference answers `204` for all five types this server cannot scan, for an omitted type, and for `photos`, which it does not declare — storing that one with no type, exactly as if it had been omitted `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]`. **The decision**: this server answers all seven cases the same way and stores the same type, and a library of such a type stays empty because its scan admits nothing there (§3.6.1) | — | Closed. §3.6 and §3.6.1, AC-7 amended; the empty library is an accepted gap in [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) |
| OQ-7 | ~~Does a setup that skips `POST /Startup/Configuration` leave a server clients accept?~~ **Answered on 2026-09-13, at the API**: the first account signs in and `/UserViews` answers its libraries, and `ServerName` falls back to the host's own name. Whether a client's interface accepts such a server is a question for a client and was not asked | — | Closed. §2's out-of-scope row stands `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| OQ-8 | ~~Is a scan waited for?~~ **Answered on 2026-09-13: no.** `POST /Library/Refresh` answers within 0.01 s and `refreshLibrary=true` after 0.07 s with nothing of the new library yet browsable; the library row's `RefreshStatus` showed the scan that adding a library started (`Active`, with a fractional progress) and **not** the one `POST /Library/Refresh` started, which appears only on the scheduled-task list. And **`refreshLibrary=false` did not leave a library unscanned** — what scanned it was not isolated | — | Closed. §3.5, §3.6 and §3.7, AC-8 amended; the consequence for the client is OQ-12 `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-13]` |
| OQ-9 | **How does the client come by a password and keep a session?** A prompt, the environment, a file only its owner can read; and whether a token outlives one invocation | §3.8's signing-in paragraph | A decision at the plan gate — it is about the client, and the reference has nothing to say |
| OQ-10 | **L3 for the setup sequence?** The instance already runs it, so a differential over it is a comparison and no machinery | §6 | A decision at the plan gate |
| OQ-11 | **How does this server know the address a request came from, and what must an operator behind a reverse proxy do?** OQ-1's rule is only as good as that address. A proxy on the same machine forwards every request from a loopback address, so unless the original client's address is passed on **and believed**, the window reopens to the whole network behind it — and believing a passed-on address from anyone *other* than such a proxy would let a remote caller claim to be local. Today the answer is a default of a component the server is built on rather than a decision this project took, and a rule a security property rests on cannot be a default nobody chose | §3.1's meaning of *this machine*, AC-5 | A decision at the plan gate, asserted by a test that sends a request claiming a loopback origin from elsewhere and is refused, and one arriving through a local proxy that passes the address on and is refused |
| OQ-12 | ~~Should `library scan` wait for the scan to finish?~~ **Decided on 2026-09-13: no.** It reports that a scan was started and exits, and the scheduled-task list stays outside this feature's surface (§3.7, §3.8). What was weighed: OQ-8 found the two scans differ. A scan started by **adding** a library shows on its row (§3.5), so a client can wait for that one with an operation this feature already serves. A scan started by `POST /Library/Refresh` does not: its `204` is sent as it starts and the row reads `Idle` throughout, and the one place it shows is the server's scheduled-task list, which is not an operation 014 serves. So **library scan** either reports *"a scan was started"* — which is what §3.8 now says — or this feature serves one more of Jellyfin's operations to let it wait | — | Closed. §3.7 and §3.8, AC-9 amended |
| OQ-13 | **What does this server state in `LibraryOptions`?** The reference sends 37 properties on every library read (§3.5), and most describe behaviour this server has no counterpart for. Stating one it does not honour is Principle VI's plausible-looking stub; omitting all of them is a shape the reference never sends | §3.5's `LibraryOptions` row | A decision at the plan gate, property by property |

## 8. References

- [Roadmap, v2 — the management CLI](../../docs/roadmap.md#v2--the-management-cli): the constraint in
  §2.0, and the rule under which the served surface grows.
- [001 §7 OQ-3](../001-server-identity-and-discovery/spec.md): the question §2.1 closes.
- [002 §3.4](../002-authentication-users-and-sessions/spec.md): the wizard's account is hidden, and
  `GET /Users/Public` is `[]` on an unconfigured server.
- [003](../003-library-configuration-and-scanning/spec.md): the three kinds of library this server
  scans.
- Jellyfin at `v10.11.11`, none of them touched by the local fork:
  `Jellyfin.Api/Auth/FirstTimeSetupPolicy/FirstTimeSetupHandler.cs`,
  `Jellyfin.Api/Controllers/StartupController.cs`,
  `Jellyfin.Server.Implementations/Users/UserManager.cs`,
  `Emby.Server.Implementations/Library/LibraryManager.cs`,
  `Jellyfin.Api/Middleware/ExceptionMiddleware.cs`.
- The `10.11.11` OpenAPI document: `GetFirstUser`, `UpdateStartupUser`, `CompleteWizard`,
  `GetVirtualFolders`, `AddVirtualFolder`, `RefreshLibrary`, `CreateUserByName`, `StartupUserDto`,
  `VirtualFolderInfo`, `AddVirtualFolderDto`, `CollectionTypeOptions`.
- `tools/_reference.py:681-770`: the same sequence, already run unattended against the reference.
- `tools/probe_first_time_setup.py`, and [notes/first-time-setup-readings.md](notes/first-time-setup-readings.md):
  the measurement gate's readings, on an instance started unconfigured.
