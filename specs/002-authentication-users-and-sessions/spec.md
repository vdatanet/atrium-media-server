---
feature: 002-authentication-users-and-sessions
title: Authentication, users and sessions
status: Draft
created: 2026-08-26
updated: 2026-08-26
depends_on: [001]
---

# 002 — Authentication, users and sessions

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Turn a username and a password into a token, recognise that token on every later request, and know
which device is holding it.

Everything after this feature is user-scoped: an item's `UserData`, a library's visibility, a resume
position. None of it can be specified until "who is asking" has an answer.

**Client behaviour unlocked:** a login screen that works, and a session that survives the app being
closed.

## 2. Scope

**In scope**

- `POST /Users/AuthenticateByName`, `GET /Users/Public`, `GET /Users/Me`, `GET /Users/{userId}`,
  `POST /Users/Configuration`, `POST /Sessions/Capabilities/Full`, `GET /Sessions`.
- The four token-presentation mechanisms, on every authenticated route in the project.
- The client-identification header, and the device identity it establishes.
- User accounts, their configuration and the parts of their policy v1 honours.
- Session lifecycle: creation, activity tracking, expiry.

**Out of scope**

- Creating, editing and deleting users over HTTP (`POST /Users/New`, `/Users/Password`,
  `/Users/{userId}/Policy`). v1 manages accounts through configuration, not an admin API.
- Quick Connect, forgotten-password flows, external authentication providers.
- Remote control of one session by another; `GET /Sessions` reports, it does not command.
- API keys not belonging to a user.

## 3. Behaviour

### 3.1 How a client presents a token

Four mechanisms, all accepted, on **every** authenticated route:

| Mechanism | Form |
|---|---|
| Header | `X-Emby-Token: {token}` |
| Header | `Authorization: MediaBrowser Token="{token}"` |
| Query | `?ApiKey={token}` |
| Query | `?api_key={token}` |

`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

All four are required, not a choice. Clients use headers for API calls and the query forms for URLs
handed to media players and image loaders, which do not set headers. Supporting only the headers
breaks playback and artwork while leaving browsing intact — a failure that looks like a bug in the
client.

**Rejection is uniform:** a request to an authenticated route with no token, an unknown token, or a
token belonging to a disabled user is `401`. A valid token whose user lacks the required permission
is `403`. The distinction matters: clients re-authenticate on `401` and show an error on `403`, so
returning the wrong one produces either a login loop or a dead end.

### 3.2 How a client identifies itself

`X-Emby-Authorization: MediaBrowser Client="…", Device="…", DeviceId="…", Version="…"`

**Mandatory on `POST /Users/AuthenticateByName`.** The `Emby` in the name is historical.

| Component | Meaning |
|---|---|
| `Client` | Application name, e.g. `Jellyfin Android` |
| `Device` | Human-readable device name shown in session lists |
| `DeviceId` | Stable per-installation identifier. **This is what identifies a session** |
| `Version` | Client version string |

Parsing must be lenient in the ways clients are actually sloppy: any order, optional whitespace
around `=` and after commas, values quoted or bare, and unknown components ignored rather than
rejected.

> ⚠️ **OQ-1.** Whether the reference server accepts this header on routes other than
> authentication, and whether it treats a request differently when it carries both this header and
> a token. Blocks nothing: Atrium accepts it anywhere and uses `DeviceId` to attribute the session
> when present.

### 3.3 `POST /Users/AuthenticateByName` — `AuthenticateUserByName`

**Consumers:** music-client, video-client.

**Request**

| Part | Name | Required | Notes |
|---|---|---|---|
| header | `X-Emby-Authorization` | yes | §3.2 |
| body | `Username` | yes | Matched case-insensitively |
| body | `Pw` | yes | May be empty when the account has no password |

**Response — 200**

```json
{
  "User": { },
  "SessionInfo": { },
  "AccessToken": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "ServerId": "3f9c1a7e5b2d4e8091a6c3f70d5e2b14"
}
```

| Field | Notes |
|---|---|
| `User` | The full user object of §3.5 |
| `SessionInfo` | The session created by this authentication, §3.8 |
| `AccessToken` | 32 lowercase hex characters `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` |
| `ServerId` | The server identity from 001 §3.1 |

**Errors**

| Condition | Status |
|---|---|
| Wrong username or password | `401` |
| Disabled account, or one locked out by failed attempts | `401` — indistinguishable from wrong credentials, on purpose |
| Missing or unparseable `X-Emby-Authorization` | `400` |
| Malformed body | `400` |

The `401`/`400` split is load-bearing for clients: `401` means "your credentials are wrong", any
`4xx` other than `401` means "something else went wrong, do not tell the user their password is
bad".

**Behaviour beyond the response**

1. A session is created for `(user, DeviceId, Client)`. Authenticating again from the **same
   `DeviceId`** replaces that session rather than accumulating one per login.
2. Failed attempts are counted per user. After the configured threshold the account locks and
   further attempts answer `401` regardless of credentials. A success resets the count.
3. Passwords are never recoverable from the server's stored state, and never appear in logs — not
   at any log level, not in a request trace, not in an error message.

### 3.4 `GET /Users/Public` — `GetPublicUsers`

**Consumers:** video-client. Unauthenticated.

Returns the users the server shows on login screens: an array of §3.5 objects, each carrying
**only** `Name`, `Id`, `ServerId`, `PrimaryImageTag` and `HasPassword`. Configuration and policy
are omitted — this is pre-authentication, and it must not disclose what a user is allowed to do.

**An empty array is a valid `200`.** Users flagged hidden from login screens are excluded, and an
installation where every user is hidden legitimately returns `[]`.
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

### 3.5 The user object

Returned by §3.3, §3.4, §3.6 and §3.7.

| Field | Type | Notes |
|---|---|---|
| `Name` | string | |
| `Id` | string | 32 hex |
| `ServerId` | string | |
| `ServerName` | string | |
| `PrimaryImageTag` | string | Present only when the user has an avatar |
| `PrimaryImageAspectRatio` | number | Same condition |
| `HasPassword` | boolean | |
| `HasConfiguredPassword` | boolean | |
| `HasConfiguredEasyPassword` | boolean | Always `false`; v1 has no PIN concept |
| `EnableAutoLogin` | boolean | |
| `LastLoginDate` | date | Absent until first login |
| `LastActivityDate` | date | |
| `Configuration` | object | §3.6. Omitted from `/Users/Public` |
| `Policy` | object | Omitted from `/Users/Public` |

`[spec: UserDto]`

**Policy in v1.** The reference carries about forty policy flags. v1 stores and returns the whole
set so clients see the shape they expect, but **honours only these**:

| Flag | Effect |
|---|---|
| `IsAdministrator` | Reserved; v1 has no admin surface to gate |
| `IsDisabled` | Authentication always fails |
| `IsHidden` | Excluded from `/Users/Public` |
| `EnableAllFolders`, `EnabledFolders` | Which libraries the user sees |
| `EnableMediaPlayback` | Whether delivery routes answer |
| `EnableContentDeletion`, `EnableContentDeletionFromFolders` | Whether deletion is permitted |
| `LoginAttemptsBeforeLockout`, `InvalidLoginAttemptCount` | §3.3 |
| `MaxActiveSessions` | Cap on concurrent sessions; `0` means unlimited |

The rest are stored and echoed unchanged. **This is a known, bounded gap**, not an oversight: a
flag returned but unenforced is a delta a client could observe by testing the restriction. It is
accepted for v1 because the unenforced flags all gate features v1 does not have (Live TV, sync,
transcoding limits, remote control) — enforcing "you may not transcode" on a server that never
transcodes is not observable. Any flag whose feature arrives must be enforced in the same change.

### 3.6 `POST /Users/Configuration` — `UpdateUserConfiguration`

**Consumers:** video-client.

Replaces the authenticated user's configuration: audio and subtitle language preferences, subtitle
mode, whether missing episodes are displayed, view ordering and exclusions, next-episode autoplay.
`[spec: UserConfiguration]`

`204` on success. `401` unauthenticated. Unknown properties are ignored, not rejected.

**v1 stores and returns every property faithfully but acts on only those that change something v1
does:** language preferences (which influence default track selection in 008) and
`DisplayMissingEpisodes` (which changes what 005 returns). The same bounded-gap reasoning as §3.5
applies.

### 3.7 `GET /Users/Me` and `GET /Users/{userId}`

**Consumers:** video-client (`Me`), music-client (`{userId}`).

Both return the §3.5 object in full, including configuration and policy.

`GET /Users/{userId}` returns `403` when the token belongs to a different, non-administrator user.
A user may always read themselves.

### 3.8 Sessions

A session is a `(user, device, client)` triple, created at authentication and identified by the
`DeviceId` of §3.2.

**`POST /Sessions/Capabilities/Full` — `PostFullCapabilities`.** Included by design; clients post
their playable media types, supported commands and device profile after logging in. v1 stores the
declaration and reflects it in §3.9. It does not act on `SupportedCommands`, because v1 has no
remote control — but a client that posts capabilities and then sees them missing from `/Sessions`
has observed a difference, which is why storing it is not optional.

**`GET /Sessions` — `GetSessions`.** Returns the sessions the caller may see: their own always, and
all sessions for an administrator. Each carries the identity fields (`Id`, `UserId`, `UserName`,
`Client`, `DeviceId`, `DeviceName`, `ApplicationVersion`, `RemoteEndPoint`), activity timestamps,
the declared capabilities, and — while something is playing — `NowPlayingItem` and `PlayState`,
which feature 007 populates. `[spec: SessionInfoDto]`

`SupportsMediaControl` and `SupportsRemoteControl` are `false` in v1. This is honest rather than a
gap: a client that saw `true` would offer the user a remote-control UI that does nothing.

**Lifecycle**

| Event | Effect |
|---|---|
| Authentication from a known `DeviceId` | Existing session is replaced, its token invalidated |
| Any authenticated request | `LastActivityDate` advances |
| Playback reporting (007) | `LastPlaybackCheckIn` advances |
| Inactivity beyond the configured window | Session and token expire; next request is `401` |
| `MaxActiveSessions` exceeded | Oldest session is evicted |

> ⚠️ **OQ-2.** The reference's inactivity window and whether it is observable to a client. If a
> client caches a token for weeks and Atrium expires it sooner, users see spurious logouts. Until
> measured, v1 does not expire tokens on inactivity at all — the safe direction, since a token that
> outlives the reference's is invisible to a client, whereas one that dies sooner is not.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| User accounts | `/Users/*` responses | Until removed by an operator |
| Password verifier | `HasPassword`, and whether authentication succeeds | With the account |
| Failed-attempt counter | `InvalidLoginAttemptCount`; lockout behaviour | Reset on success |
| Access tokens | Whether a request is `401` | Until replaced, evicted or revoked |
| Sessions | `/Sessions` responses | See §3.8 |
| Per-user configuration | `Configuration` in §3.5 | Until replaced |

## 5. Acceptance criteria

1. Authenticating with valid credentials answers `200` with a 32-hex `AccessToken`, a full user
   object and a session.
2. Wrong password answers `401`; a disabled user answers `401` **indistinguishably**; a missing
   `X-Emby-Authorization` answers `400`.
3. All four token mechanisms of §3.1 authenticate the same request identically, on an API route, an
   image route and a delivery route.
4. No token on an authenticated route is `401`; a valid token lacking permission is `403`.
5. Re-authenticating from the same `DeviceId` replaces the session and invalidates the prior token.
6. `/Users/Public` omits `Configuration` and `Policy`, excludes hidden users, and answers `200`
   with `[]` when all users are hidden.
7. `GET /Users/{userId}` for another user answers `403` for a non-administrator and `200` for an
   administrator.
8. `POST /Users/Configuration` round-trips every property, including ones v1 does not act on.
9. Capabilities posted to `/Sessions/Capabilities/Full` appear in the caller's `/Sessions` entry.
10. After `LoginAttemptsBeforeLockout` failures the account answers `401` even with correct
    credentials, and one success afterwards resets the counter.
11. A password never appears in any log record at any level, and never in an error body.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `POST /Users/AuthenticateByName` | **L3** | Golden response plus differential. Everything downstream depends on this being byte-right |
| `GET /Users/Public` | **L2** | Golden response; fixture with a hidden user |
| `GET /Users/Me`, `GET /Users/{userId}` | **L2** | Golden response, permission matrix |
| `POST /Users/Configuration` | **L2** | Round-trip test |
| `GET /Sessions` | **L2** | Fixture with two sessions on two devices |
| `POST /Sessions/Capabilities/Full` | **L1** | Shape only; its effect is asserted through `/Sessions` |
| The four token mechanisms | **L2** | Table-driven across three route classes (AC-3) |

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Is `X-Emby-Authorization` accepted outside authentication, and does it change behaviour alongside a token? | Nothing | `tools/probe_auth_mechanisms.py` |
| OQ-2 | The reference's token inactivity window, and whether it is observable | The expiry row of §3.8. v1 defaults to no inactivity expiry | A probe holding a token idle |
| OQ-3 | Does the reference answer `401` or `403` for a disabled user? §3.3 assumes `401` | The uniformity claim in AC-2 | `tools/probe_auth_mechanisms.py` |
| OQ-4 | Are `HasConfiguredPassword` and `HasConfiguredEasyPassword` read by any client? | Nothing; honest values are sent | Differential harness (010) |

## 8. References

- [docs/compatibility/api-surface-v1.md §3](../../docs/compatibility/api-surface-v1.md#3-authentication-users-and-sessions)
- [docs/compatibility/behaviours.md §2.2, §2.4](../../docs/compatibility/behaviours.md)
- `[spec: AuthenticateUserByName, AuthenticationResult, UserDto, UserConfiguration, UserPolicy, SessionInfoDto, ClientCapabilitiesDto]`
