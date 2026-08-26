# The reference target

**Last verified: 2026-08-26, against Jellyfin 10.11.11 source and the 10.11.10 OpenAPI document.**

This document answers one question precisely: *when we say Atrium is compatible with Jellyfin,
compatible with what, exactly?*

## 1. The pinned version

**Atrium targets the Jellyfin `10.11.x` API.** Concretely:

| | Value |
|---|---|
| API contract | Jellyfin `10.11.10` OpenAPI document |
| Behavioural reference | Jellyfin `10.11.11` source and a running instance |
| Version Atrium reports | `10.11.11` — see §4 |

The reasoning for pinning, and for pinning to this particular line rather than `master`, is in
[ADR-0004](../decisions/0004-pin-to-jellyfin-10-11.md).

`master` (the 12.0.0 line) is explicitly **not** the target. It moves, it has already changed
behaviours that clients depend on, and no client ships against it.

## 2. Sources of truth, in precedence order

When two sources disagree, the higher one wins.

1. **A running Jellyfin 10.11.x** — probed by a script in `tools/`, with the result recorded.
   This is the only source that reflects what clients actually receive.
2. **The Jellyfin source at tag `v10.11.11`** — for behaviour that is hard to probe (error paths,
   ordering rules, identifier derivation).
3. **The OpenAPI document for 10.11.10** — for the shape of requests and responses, parameter
   names and enum vocabularies.

The OpenAPI document is last on purpose. It is generated from the C# controllers and is
**demonstrably not a complete description of behaviour**: it declares response headers with
`allowEmptyValue`, which is invalid for a Header object and makes strict parsers reject the whole
document; it declares every JSON response three times with `profile="CamelCase"` and
`profile="PascalCase"` variants; and it declares `required` and `additionalProperties: false` on
schemas that the server does not actually honour.
`[spec: directly observable in the 10.11.10 document]`

### Prior measurements, and the debt they carry

Some claims in this repository were measured against a real Jellyfin **before this repository
existed**, during the author's earlier client work. They are cited as
`[prior-probe: Jellyfin <version>, <date>]`.

They are real observations of a real server, and they are the reason the compatibility documents
start out substantive rather than speculative. But nobody can re-run them from here, which makes
each one a **standing debt**: it is discharged by writing the probe script under `tools/` that
reproduces the measurement, at which point the citation becomes a plain `[probe: …]`.

| Claim | Cited at | Discharged by | Script |
|---|---|---|---|
| The four accepted authentication mechanisms | 2026-06-13 | `tools/probe_auth_mechanisms.py` (feature 002) | not written |
| Item ids are 32 lowercase hex, stable across rescans | 2026-06-13 | `tools/probe_item_ids.py` (feature 003) | not written |
| `UserData` is returned without `Fields` | 2026-06-13 | `tools/probe_item_fields.py` (feature 005) | not written |
| Item-level `Container` is a demuxer list | 2026-06-13 | `tools/probe_media_sources.py` (feature 008) | not written |
| ~~`StartIndex` present in list envelopes~~ | 2026-06-13 | `tools/probe_query_envelope.py` (feature 005) | ✅ **discharged 2026-08-26** |
| `/Users/Public` may return `[]` | 2026-06-13 | `tools/probe_auth_mechanisms.py` (feature 002) | not written |
| The `SortBy` vocabulary | 2026-06-13 | `tools/probe_sort_vocabulary.py` (feature 005) | not written |
| Dates carry seven fractional digits | 2026-06-19 | `tools/probe_wire_format.py` (feature 001) | not written |
| `/Sessions/Playing/Progress` needs no `MediaSourceId` | 2026-06-13 | `tools/probe_playstate.py` (feature 007) | **written, not yet run** |
| PCM/WAV transcoding returns 500 | 2026-08-03 | Out of v1 scope; re-measure when transcoding lands | n/a |
| `LocalAddress` gets an HTTPS override | 2026-08-14 | `tools/probe_local_address.py` (feature 001) | not written |
| `TotalRecordCount` is 0 without `limit` | 2026-08-05 | `tools/probe_by_name_counts.py` (feature 005) | not written |

**Written is not discharged.** A script that exists but has never been pointed at a server has
proved nothing; the citation changes from `prior-probe` to `probe` only when it has been run and
its finding recorded.

**One down, eleven to go.** The `StartIndex` claim was re-measured on 2026-08-26 against a live
10.11.11 and held, along with three envelope shapes the original measurement had not covered. Its
citations are now plain `probe:` and it is struck from this register.

A claim that fails to reproduce when its probe is finally written is not quietly dropped: it goes
into [behaviours.md](behaviours.md) as a behaviour that *changed*, with both dates.

### Obtaining the reference documents

The OpenAPI document is **not vendored** into this repository — it is generated from GPL-licensed
source, and vendoring it would drag a licensing question into a repository that does not need one
(see [ADR-0005](../decisions/0005-licence.md)). Fetch it instead:

```bash
python3 tools/fetch_reference_spec.py http://<your-jellyfin>:8096 --out reference/openapi.json
```

`reference/` is git-ignored. A local checkout of the Jellyfin source at `v10.11.11` is the second
input; the probe scripts need neither.

## 3. What "compatible" means, in four levels

Parity is not one thing. Each endpoint in
[api-surface-v1.md](api-surface-v1.md) is assigned a level:

| Level | Meaning | How it is proven |
|---|---|---|
| **L0 — Routed** | The path exists and returns a plausible status code. | Route test |
| **L1 — Shape** | The response has the right fields, casing, types and units. | Golden-response test |
| **L2 — Semantic** | The response has the right *values* for a known library state. | Fixture library test |
| **L3 — Differential** | The response is byte-comparable to a real Jellyfin's, modulo a documented allowlist of legitimately-varying fields. | Differential harness |

**v1 requires L2 for every endpoint in the surface, and L3 for the endpoints on the playback and
authentication paths** — the two places where a client's behaviour actually diverges when the
server is wrong.

Full method in [conformance.md](conformance.md).

## 4. Server identity: what Atrium tells clients it is

This is the one place where Principle I (zero delta) and Principle X (honest about lineage) pull
against each other, so it is settled here rather than left to the implementation.

`GET /System/Info/Public` returns, among other fields:

```json
{
  "ServerName": "atrium",
  "Version": "10.11.11",
  "ProductName": "Jellyfin Server",
  "OperatingSystem": "",
  "Id": "<32 hex chars>",
  "LocalAddress": "http://host:8096",
  "StartupWizardCompleted": true
}
```
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**`ProductName` must be `"Jellyfin Server"` and `Version` must be a real 10.11.x version.** This
is not cosmetic: `ProductName` is the documented discriminator that multi-server clients use to
decide whether they are talking to Emby or Jellyfin, and the version string drives client-side
capability gating. A client that reads `"Atrium"` there takes an unknown-server path, and
Principle I is broken at the very first request.

Honesty is preserved where it costs nothing and where humans, not clients, are reading:

- The `ServerName` field is the operator's chosen name and defaults to `atrium`.
- The HTTP `Server` response header identifies Atrium and its own version.
- The README, the project page and every log line say plainly what this is.

**Decision:** identify as Jellyfin on the fields clients parse; identify as Atrium everywhere a
human looks. This is recorded as a deliberate, permanent exception in
[behaviours.md](behaviours.md).

## 5. What is *not* a target

- **Emby.** Emby's API is the ancestor of Jellyfin's and diverges in real ways: numeric item ids
  instead of GUIDs, `LocalAddresses[]` instead of `LocalAddress`, user-scoped write routes,
  `/universal.mp3`. Atrium implements the Jellyfin dialect only. Multi-server clients already carry
  an Emby driver; Atrium falls on the Jellyfin side of that split, which is exactly what makes its
  delta zero.
- **The Jellyfin web UI.** Serving it would pull in `DisplayPreferences`, `Branding`,
  `Configuration`, `QuickConnect`, `Localization` and a static asset pipeline — a large surface
  whose only consumer is a UI this project is not building. Revisit as a v2 goal.
- **Plugins.** Jellyfin's plugin API is a .NET assembly-loading contract. There is no Python
  equivalent and no reason to invent one.
- **`master`/12.0.0.** See §1.
