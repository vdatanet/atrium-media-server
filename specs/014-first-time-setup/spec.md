---
feature: 014-first-time-setup
title: First-time setup
status: Draft
created: 2026-09-13
updated: 2026-09-13
amended: 2026-09-13 at the spec gate - OQ-1 decided (the setup window is open to a loopback address only, by changing the reference's first branch and nothing else) and OQ-2 decided (the first account is always MyJellyfinUser); sections 3.1, 3.2 and 3.8, AC-2, AC-5 and AC-10 amended; OQ-11 raised by the first answer
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
  metadata language and a remote-access flag is not needed to sign in or browse; whether a setup
  sequence that omits them is one clients accept is OQ-7.
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

The exact bodies of the `401` and the `403` are OQ-4.

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

**Error responses:** the refusals of §3.1 once setup is finished. Their bodies are OQ-4.

### 3.3 `POST /Startup/User` — `UpdateStartupUser`

**Consumers:** the command-line client of §3.8.

**It updates the first account and never creates one.** A server with no account answers `404`
`[source: StartupController.cs:134-138 @ v10.11.11]` — so on a fresh server this operation fails
unless §3.2 ran first, and the order is part of the contract.

**Request — body**

| Name | Required | Type | Notes |
|---|---|---|---|
| `Name` | no | string | When present and different from the current name, ignoring case, the account is **renamed** `[source: StartupController.cs:147-151]` |
| `Password` | **yes** | string | Empty or whitespace is refused `[source: StartupController.cs:140-143]`; otherwise the account's password becomes this `[source: StartupController.cs:153-157]` |

**Response — 204**, no body.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| no account exists | `404` | OQ-4 |
| `Password` missing, empty or whitespace | `400` | carries the message `Password must not be empty` `[source: StartupController.cs:142]`; the envelope is OQ-4 |
| a `Name` that is not a valid username, or that another account holds | ⚠️ UNVERIFIED | OQ-5 |
| setup finished, caller not an administrator | §3.1 | OQ-4 |

After this operation the account can sign in through `POST /Users/AuthenticateByName`
([002](../002-authentication-users-and-sessions/spec.md)) with the name and password it was given.

### 3.4 `POST /Startup/Complete` — `CompleteWizard`

**Consumers:** the command-line client of §3.8.

**Closes the setup window**, and checks nothing before doing it: it does not require that an account
has a password, or that a library exists `[source: StartupController.cs:41-47 @ v10.11.11]`.

**Request:** none. **Response — 204**, no body.

From this response on, §3.1's second and third rows apply and `StartupWizardCompleted` is `true`.

**Error responses:** once setup is finished, the refusals of §3.1 — so a second call succeeds for an
administrator and is refused for anybody else. What the second call answers for an administrator,
and whether it changes anything, is ⚠️ UNVERIFIED (OQ-5).

### 3.5 `GET /Library/VirtualFolders` — `GetVirtualFolders`

**Consumers:** the command-line client of §3.8.

**Every library, one entry each.**

**Response — 200** — an array of `[spec: VirtualFolderInfo]`:

| Field | Type | Notes |
|---|---|---|
| `Name` | string | The library's name, as §3.6 settled it |
| `Locations` | array of string | The library's paths |
| `CollectionType` | string | One of §3.6's accepted types |
| `ItemId` | string | The library's own identifier, the one a client browses by |
| `LibraryOptions` | object | ⚠️ UNVERIFIED which of its properties this server can state truthfully — OQ-6 |
| `PrimaryImageItemId` | string | ⚠️ UNVERIFIED — OQ-6 |
| `RefreshProgress`, `RefreshStatus` | number, string | ⚠️ UNVERIFIED what either answers while a scan runs and after one — OQ-8 |

**Error responses:** the refusals of §3.1 once setup is finished.

### 3.6 `POST /Library/VirtualFolders` — `AddVirtualFolder`

**Consumers:** the command-line client of §3.8.

**Request**

| Part | Name | Required | Type | Notes |
|---|---|---|---|---|
| query | `name` | yes | string | Trimmed and made a valid file name before use `[source: Emby.Server.Implementations/Library/LibraryManager.cs:3032 @ v10.11.11]` |
| query | `collectionType` | no | string | `[spec: CollectionTypeOptions]` declares eight values; which of them this server accepts is §3.6.1 |
| query | `paths` | no | string, comma-separated | Each must be a directory that exists **on the server** |
| query | `refreshLibrary` | no | boolean, default `false` | Whether adding the library also scans it |
| body | `LibraryOptions` | no | object | `[spec: AddVirtualFolderDto]`; which properties are honoured is OQ-6 |

**Response — 204**, no body. The library appears in §3.5 and, once scanned, in a client's views.

**Two behaviours that are not what the operation's name suggests**, both reproduced unless OQ-3
decides otherwise:

- **A name already in use is not refused.** The reference appends a number and adds the library under
  the new name, and still answers `204`. **The first number is `2`**, with nothing between the name
  and it — `Movies` becomes `Movies2`, then `Movies3` — because the count starts at one and is
  incremented before it is used; the reference's own comment says *"first numbered name will be
  2"* `[source: LibraryManager.cs:3036-3044]`. The name a caller asked for is therefore not
  necessarily the name the library has, and §3.5 is how a caller finds out.

  **Whether `movies` collides with `Movies` is the reference's host filesystem's answer, not a
  rule.** The collision is decided by whether a directory of that name exists, so it is
  case-sensitive where the host's filesystem is and not where it is not — the pinned reference
  instance runs on a case-sensitive one. OQ-3 decides which this server reproduces.
- **A path is checked, a name is not.** A path that does not exist refuses the whole request; a name
  that collides does not.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| `name` missing, empty or whitespace | `400` | `[source: LibraryManager.cs:3027-3030, and ExceptionMiddleware.cs:127, which answers 400 for that failure]`; envelope OQ-4 |
| a path that does not exist on the server | `400` | carries `The specified path does not exist: <path>.` `[source: LibraryManager.cs:3049-3053]`; envelope OQ-4 |
| a `collectionType` this server does not accept | §3.6.1 | §3.6.1 |
| setup finished, caller not an administrator | §3.1 | OQ-4 |

#### 3.6.1 Which library types

This server scans **three** kinds of library — movies, series and music
([003](../003-library-configuration-and-scanning/spec.md), and the roadmap's *Media types* row). The
reference declares eight `[spec: CollectionTypeOptions — movies, tvshows, music, musicvideos,
homevideos, boxsets, books, mixed]`, and an omitted type is its own case.

**`movies`, `tvshows` and `music` are accepted.** What the other five and an omitted type answer is
OQ-6, and it is not decided here: refusing them is a shape the reference never answers for a legal
value, and accepting one creates a library this server will scan into nothing.

### 3.7 `POST /Library/Refresh` — `RefreshLibrary`

**Consumers:** the command-line client of §3.8.

**Scans every library.** Requires an administrator whether or not setup is finished (§3.1).

**Request:** none. **Response — 204**, no body.

Whether the response waits for the scan or is sent as it starts, and what a caller can observe
while it runs, is OQ-8.

**Error responses**

| Condition | Status | Body |
|---|---|---|
| no token | `401` | OQ-4 |
| authenticated, not an administrator | `403` | OQ-4 |

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
| **library scan** | §3.7 | the server refuses it |

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
3. `POST /Startup/User` on a server with no account answers `404`; with an empty or whitespace
   `Password` it answers `400`; otherwise it sets the password, renames the account when `Name`
   differs ignoring case, and the account then signs in with that name and password.
4. `POST /Startup/Complete` succeeds with no password set and no library, and closes the window.
5. While setup is unfinished, §3.2 to §3.6 admit a caller carrying no token **from a loopback
   address**, and treat a caller from any other address as they treat every caller once setup is
   finished: an administrator is admitted, an authenticated non-administrator refused `403`, and a
   caller with no token refused `401`. A client on the server's own machine that addresses it by a
   network address is a caller from elsewhere.
6. `POST /Library/Refresh` refuses a caller with no token `401` and a non-administrator `403` in both
   states, and admits an administrator.
7. `POST /Library/VirtualFolders` with an accepted type and existing paths adds a library that
   `GET /Library/VirtualFolders` then lists with that name, type and paths; a name already in use is
   added under that name followed by `2` (then `3`) and answers `204`; a missing name and a path that
   does not exist each answer `400` and add nothing.
8. A library added with `refreshLibrary=true`, or scanned through `POST /Library/Refresh`, is
   browsable by an unmodified Jellyfin client signed in as the first account.
9. The command-line client performs **setup**, **library add**, **library list** and **library
   scan** end to end against a fresh server, and a run of it issues only the operations §3.8 names —
   asserted by recording every request it makes, not by reading its source.
10. The client exits non-zero and prints the server's status and reason on every refusal, refuses
    **setup** on a server whose setup is finished without calling §3.2 to §3.4, refuses **setup**
    given a non-loopback address while setup is unfinished without calling §3.2 to §3.4 and says it
    must run on the server's machine, and prints no password in any output.

*Criteria 5, 7 and 8 have halves an open question can move — the refusal bodies (OQ-4), the
duplicate name (OQ-3), the types (OQ-6) and how a request's address is determined (OQ-11). Each is written against the reference's measured or
read behaviour and is amended at the gate that answers it, not quietly.*

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

**Two of the ten were decisions and both were taken on 2026-09-13**, OQ-1 and OQ-2; answering OQ-1
raised OQ-11. The rest are readings or decisions for the plan gate.

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
| OQ-3 | **Is a name already in use numbered, as the reference does, or refused?** A `204` for a request that did something other than it asked is a class-B shape, and a client that reads §3.5 afterwards is unaffected either way | §3.6, AC-7's second half | A behaviours §3.0 decision |
| OQ-4 | **What are the refusal bodies** — the `400`s, the `404`, and §3.1's `401` and `403` — on these routes? The messages are read from the source; the envelope they travel in is not measured on any of them | Every error table in §3, AC-3, AC-5, AC-6, AC-7 | A reading against the single-use instance |
| OQ-5 | **What do the edges answer** — a rename to an invalid name or to one another account holds, and a second `POST /Startup/Complete` by an administrator? | §3.3's and §3.4's unverified rows | A reading against the single-use instance |
| OQ-6 | **What does a library carry and accept that this server cannot scan into?** Five of the eight declared types, an omitted type, `LibraryOptions` on the way in and on the way out, and `PrimaryImageItemId` | §3.5's unverified rows, §3.6.1, AC-7 | A reading of what the reference answers for each, then a decision per type |
| OQ-7 | **Does a setup that skips `POST /Startup/Configuration` leave a server clients accept?** It sets a server name and a metadata language; this server already has a name | Whether §2's out-of-scope row stands | A reading: set the instance up without it and sign a client in |
| OQ-8 | **Is a scan waited for?** Whether `POST /Library/Refresh` and `refreshLibrary=true` answer when the scan starts or when it ends, and what `RefreshProgress` and `RefreshStatus` say meanwhile | §3.5's refresh rows, §3.7, what **library scan** can promise | A reading against the single-use instance over the repository's fixture |
| OQ-9 | **How does the client come by a password and keep a session?** A prompt, the environment, a file only its owner can read; and whether a token outlives one invocation | §3.8's signing-in paragraph | A decision at the plan gate — it is about the client, and the reference has nothing to say |
| OQ-10 | **L3 for the setup sequence?** The instance already runs it, so a differential over it is a comparison and no machinery | §6 | A decision at the plan gate |
| OQ-11 | **How does this server know the address a request came from, and what must an operator behind a reverse proxy do?** OQ-1's rule is only as good as that address. A proxy on the same machine forwards every request from a loopback address, so unless the original client's address is passed on **and believed**, the window reopens to the whole network behind it — and believing a passed-on address from anyone *other* than such a proxy would let a remote caller claim to be local. Today the answer is a default of a component the server is built on rather than a decision this project took, and a rule a security property rests on cannot be a default nobody chose | §3.1's meaning of *this machine*, AC-5 | A decision at the plan gate, asserted by a test that sends a request claiming a loopback origin from elsewhere and is refused, and one arriving through a local proxy that passes the address on and is refused |

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
