---
feature: 001-server-identity-and-discovery
title: Server identity and discovery
status: Accepted
created: 2026-08-26
updated: 2026-08-26
accepted: 2026-08-26
depends_on: []
---

# 001 — Server identity and discovery

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Every client's first request is "is there a server here, and what is it?". This feature answers it.

It is first not because it is large — it is the smallest feature in v1 — but because it is the
first thing that can be wrong, and because it forces the wire-format decisions (property casing,
version string, identifier shape, the meaning of `ProductName`) that everything else will encode.
A client that mis-identifies the server here takes an unknown-server path and never reaches the
rest of the API.

**Client behaviour unlocked:** entering a server address in a client and getting "connected to
<name>" instead of "cannot find a server".

## 2. Scope

**In scope**

- `GET /System/Info/Public` — unauthenticated identity.
- `GET /System/Info` — authenticated, fuller identity.
- `GET /System/Ping` and `POST /System/Ping` — liveness.
- The rules for choosing the advertised address.
- The project-wide wire-format rules that these responses are the first to exercise.

**Out of scope**

- `GET /Users/Public` — the login-screen user list, which belongs with authentication (002).
- `GET /Localization/Cultures` — belongs with item metadata (004).
- `/System/Info/Storage`, `/System/Restart`, `/System/Shutdown`, `/System/Logs`,
  `/System/Endpoint` — administrative surface, not in v1.
- UDP autodiscovery on the local network — not in v1; clients take an address.

## 3. Behaviour

### 3.0 Rules that apply to every response in this specification

These are stated once here and inherited by every later specification. They come from
[behaviours.md §1](../../docs/compatibility/behaviours.md#1-wire-format).

1. **Property names are PascalCase.** Non-negotiable, project-wide.
2. **Content type is `application/json`.** The server additionally accepts requests specifying
   `application/json; profile="CamelCase"` or `profile="PascalCase"`, and answers all three
   identically with PascalCase. `[spec: directly observable in the 10.11.10 document]`
3. **Absent optional values are omitted or null exactly as the reference server does**, verified per
   field rather than by rule.
4. **Identifiers are 32 lowercase hexadecimal characters**, no dashes.

### 3.1 `GET /System/Info/Public` — `GetPublicSystemInfo`

**Consumers:** music-client, video-client. The single most important response in the API: it is what
a multi-server client uses to decide which dialect it is speaking.

**Request:** no authentication, no parameters. Must answer before any user exists and before any
library is configured.

**Response — 200**

```json
{
  "LocalAddress": "http://192.168.1.20:8096",
  "ServerName": "atrium",
  "Version": "10.11.11",
  "ProductName": "Jellyfin Server",
  "OperatingSystem": "",
  "Id": "3f9c1a7e5b2d4e8091a6c3f70d5e2b14",
  "StartupWizardCompleted": true
}
```

| Field | Type | Value |
|---|---|---|
| `LocalAddress` | string | The address this server advertises for the requester's network. §3.4 |
| `ServerName` | string | Operator-chosen friendly name. Default `atrium` |
| `Version` | string | `10.11.11` — the pinned reference version, not Atrium's own |
| `ProductName` | string | **Exactly `Jellyfin Server`** |
| `OperatingSystem` | string | **Always the empty string** |
| `Id` | string | Stable 32-hex server identity, generated once and persisted |
| `StartupWizardCompleted` | boolean | Whether initial setup is finished |

**Compatibility notes**

- `ProductName` is the documented discriminator multi-server clients use to tell Emby from
  Jellyfin. It must be the literal `Jellyfin Server`. The reasoning, and why this does not conflict
  with being honest about what Atrium is, is in
  [reference-target.md §4](../../docs/compatibility/reference-target.md#4-server-identity-what-atrium-tells-clients-it-is).
  `[prior-probe: Jellyfin 10.11.11, 2026-06-13]`
- `OperatingSystem` is empty because the reference implementation marks the field obsolete and
  never assigns it, leaving its default empty-string value.
  `[source: MediaBrowser.Model/System/PublicSystemInfo.cs:37-38 @ v10.11.11]`
- The reference builds this response from exactly six assignments and never sets
  `OperatingSystem`. Atrium sends the same seven fields and no others.
  `[source: Emby.Server.Implementations/SystemManager.cs:112-125 @ v10.11.11]`
- `Id` must survive restarts and database rebuilds. A server whose identity changes makes every
  client treat it as a new server and re-authenticate.

**Errors**

| Condition | Status |
|---|---|
| Server still starting | `503`; see §3.5 |

### 3.2 `GET /System/Info` — `GetSystemInfo`

**Consumers:** music-client.

**Request:** authenticated. The reference also permits this during first-time setup, before any
user exists.
`[source: Jellyfin.Api/Controllers/SystemController.cs:67-71 @ v10.11.11]`

**Response — 200:** a superset of §3.1. In addition to the seven public fields, the reference
returns paths, capability flags and update state.
`[spec: SystemInfo]`

Atrium returns the superset with these values:

| Field group | Atrium's answer |
|---|---|
| `HasPendingRestart`, `IsShuttingDown`, `CanSelfRestart`, `CanLaunchWebBrowser`, `HasUpdateAvailable` | `false` — Atrium has no self-update or restart capability |
| `SupportsLibraryMonitor` | `false` in v1 — filesystem watching is not implemented |
| `WebSocketPortNumber` | The server's own port; v1 serves no WebSocket, but the field is a number clients read unconditionally |
| `ProgramDataPath`, `CachePath`, `LogPath`, `InternalMetadataPath`, `ItemsByNamePath`, `TranscodingTempPath`, `WebPath` | Real paths from the running configuration |
| `CompletedInstallations`, `CastReceiverApplications` | Empty arrays |
| `PackageName`, `OperatingSystemDisplayName`, `SystemArchitecture`, `EncoderLocation` | Real values where meaningful, empty string otherwise |

> ⚠️ **Open question OQ-1.** Whether any client branches on `SupportsLibraryMonitor` or
> `WebSocketPortNumber`. Neither analysed client reads them. Answering it needs the differential
> harness (010) or a survey of other clients. It does not block this feature: the fields are sent
> with honest values either way.

**Errors**

| Condition | Status |
|---|---|
| No or invalid token, and setup already complete | `401` |
| Valid token without permission | `403` |

### 3.3 `GET /System/Ping`, `POST /System/Ping` — `GetPingSystem`, `PostPingSystem`

**Consumers:** none of the two analysed clients; included by design (health checks, reverse proxies,
and clients that probe before a full request).

**Request:** no authentication, no parameters, both methods.

**Response — 200:** a bare JSON string — **the product name, not the friendly server name**:

```json
"Jellyfin Server"
```

**Compatibility note.** The reference's documentation comment says "the server name", but the code
returns the application's product name.
`[source: Jellyfin.Api/Controllers/SystemController.cs:102-106 @ v10.11.11, returning
_appHost.Name; ApplicationHost.cs:260 defines Name => ApplicationProductName]`
Following the comment instead of the code would return the operator's chosen name and produce a
delta. **The code is the specification.**

### 3.4 Choosing `LocalAddress`

The reference resolves this in three tiers, and the tiers are observable, so Atrium reproduces
them. `[source: Emby.Server.Implementations/ApplicationHost.cs:871-949 @ v10.11.11]`

1. **A configured published URL wins**, returned verbatim with any trailing `/` removed. This is
   what an operator behind a reverse proxy sets, and it must not be second-guessed.
2. **Otherwise, if configured to derive the address from the request**, build it from the request's
   own host and scheme, omitting the port when it is the default for that scheme (80/http,
   443/https).
3. **Otherwise, match the requester's address against the server's bound addresses** and return the
   one on the same network, with the port it is bound to. A request arriving over a VPN gets the
   VPN-side address.

**Deliberate divergence.** In tier 3 the reference overrides the scheme to HTTPS, with the HTTPS
port, whenever a certificate is configured — regardless of the scheme the request arrived on. This
has a measured cost: clients that hand this address to a device with no TLS stack (a DLNA renderer)
break. `[prior-probe: Jellyfin 10.11.11, 2026-08-14]`

**Atrium reports the scheme and port the server is actually reachable on for that network.** Logged
as a deliberate divergence in
[behaviours.md §4.2](../../docs/compatibility/behaviours.md#42-localaddress-does-not-get-an-https-override).

### 3.5 What the server says while it is starting

Not an error path of one endpoint but a property of the whole server: **every one of the
reference's 395 operations declares a `503`**, so nothing is exempt — not even a liveness probe.
`[spec: every operation's 503 response in the pinned 10.11.10 document]`

**Response — 503**

| Part | Value |
|---|---|
| `Retry-After` | Full seconds, as an integer. Not an HTTP-date |
| `Message` | A short plain-text reason |
| Body | `text/html` — **not** JSON |

`Retry-After` is what separates "starting" from "broken" for a client. Without it a `503` is
indistinguishable from a server that is down, and a client that cannot tell will either give up or
hammer.

The same response serves a deliberate withdrawal from service — a long rebuild, say — with a
different message and a longer hint, without stopping the process.

> The `503` responses are also where the reference's OpenAPI document declares `allowEmptyValue`
> on header objects, which is invalid there and makes strict parsers reject the whole document. See
> [reference-target.md §2](../../docs/compatibility/reference-target.md#2-sources-of-truth-in-precedence-order).

## 4. Data the feature owns

Observable, and surviving restart:

| State | Observable as | Lifetime |
|---|---|---|
| Server identity | `Id` in §3.1 and §3.2 | Generated once on first start; never changes |
| Friendly name | `ServerName` | Operator-configurable |
| Setup completion | `StartupWizardCompleted` | Set once initial configuration is done |

Everything else in these responses is derived at request time.

## 5. Acceptance criteria

1. `GET /System/Info/Public` answers `200` with exactly the seven fields of §3.1, in PascalCase,
   with no user configured and no library present.
2. `ProductName` is exactly `Jellyfin Server` and `OperatingSystem` is exactly `""`.
3. `Version` matches the pinned reference version.
4. `Id` is 32 lowercase hex characters and is **identical across a restart and across a rebuild of
   the store from empty**.
5. `GET /System/Info` answers `401` without a token and `200` with a valid one, and its body is a
   superset of `/System/Info/Public` agreeing on every shared field.
6. `GET /System/Ping` and `POST /System/Ping` both answer `200` with the JSON string
   `"Jellyfin Server"`.
7. A configured published URL is returned verbatim in `LocalAddress`, trailing slash removed.
8. With no published URL, two requests from two different networks receive two different
   `LocalAddress` values, each on the requester's network.
9. Requests sent with `Accept: application/json; profile="PascalCase"` and with
   `profile="CamelCase"` receive byte-identical bodies.
10. No response in this feature contains a property name that is not PascalCase.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `GET /System/Info/Public` | **L3** | Golden response, plus differential against a real reference server. It is the first request every client makes; a difference here costs everything downstream |
| `GET /System/Info` | **L2** | Golden response and the superset assertion of AC-5 |
| `GET /System/Ping` (both methods) | **L2** | Exact-body test |
| `LocalAddress` selection | **L2** | Table-driven test over the three tiers with synthesised requester addresses |

The two cross-cutting sweeps described in
[conformance.md](../../docs/compatibility/conformance.md#l1--shape) — PascalCase over every
response model, and units over every `*Ticks` and `*Date` field — are **delivered by this feature**,
because it is the first one with a response model to sweep.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Does any real client branch on `SupportsLibraryMonitor` or `WebSocketPortNumber`? | Nothing. Honest values are sent either way | Differential harness (010), or surveying additional clients |
| OQ-3 | Is `StartupWizardCompleted` meaningful for Atrium, which has no wizard? | Nothing; `true` after first configuration | A decision in 002, where user creation happens |
| OQ-4 | Whether a running reference actually emits both headers, or only declares them | Nothing; both are sent | `tools/probe_startup.py`, which has to catch a server mid-start |

### Resolved

| # | Question | Answer | Resolved by |
|---|---|---|---|
| OQ-2 | Does the reference emit `503` with `Retry-After` while starting? | **Yes, and it is server-wide** — all 395 operations declare it, with `Retry-After` **and** a `Message` header, and a `text/html` body. §3.5 records it; §3.1's one-line error row was incomplete | The pinned document, 2026-08-26 |

## 8. References

- [docs/compatibility/reference-target.md](../../docs/compatibility/reference-target.md) — the pin, and server identity
- [docs/compatibility/behaviours.md](../../docs/compatibility/behaviours.md) — §1 wire format, §2.3 and §4.2 `LocalAddress`
- [docs/compatibility/api-surface-v1.md §2](../../docs/compatibility/api-surface-v1.md#2-identity-and-discovery)
- Jellyfin v10.11.11: `Jellyfin.Api/Controllers/SystemController.cs`,
  `Emby.Server.Implementations/SystemManager.cs`,
  `Emby.Server.Implementations/ApplicationHost.cs`,
  `MediaBrowser.Model/System/PublicSystemInfo.cs`
