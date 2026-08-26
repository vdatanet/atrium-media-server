# Measured behaviours

**Last verified: 2026-08-26, against Jellyfin 10.11.11.**

This is the registry required by Principle V. Every entry has the same three fields:

- **Jellyfin does** — the observed behaviour, with provenance.
- **Depends on it** — whether a known client relies on it.
- **Atrium does** — our decision, and why if it differs.

The default answer in the third field is *the same thing*. Divergence needs an argument.

Entries are grouped by how deep they cut. §1 is the wire format — get one of these wrong and
nothing works. §2 is semantics. §3 is defects. §4 is the deliberate exceptions, §5 the gaps v1 accepts, §6 the good ideas we refuse.

---

## 1. Wire format

### 1.1 Property casing is PascalCase

**Jellyfin does:** serialises every JSON property in PascalCase — `ItemId`, `RunTimeTicks`,
`TotalRecordCount`, `IsFavorite`. It additionally advertises `application/json; profile="CamelCase"`
and `application/json; profile="PascalCase"` content types alongside plain `application/json`,
all pointing at the same schema. `[spec: every JSON response in the 10.11.10 document]`

The same schema, and **not** the same serialisation: the CamelCase profile really does emit
camelCase. That is §1.13, and this entry is about what a client gets when it asks for nothing in
particular — which is PascalCase.

**Depends on it:** everything. A camelCase body is not a lesser response, it is an empty object to
a client's decoder.

**Atrium does:** the same. This is a whole-project constraint, not a per-endpoint one: the
serialisation layer emits PascalCase by default and it must be impossible for a route author to
forget. Requests are parsed case-insensitively, because Jellyfin's model binder is.

> ⚠️ This is the single most likely source of a silent, total incompatibility, because Python's
> ecosystem defaults to snake_case everywhere. It gets a conformance test that walks every
> registered response model and fails on any non-PascalCase field name.

### 1.2 Dates carry up to seven fractional digits

**Jellyfin does:** emits .NET round-trip ISO-8601, e.g. `2025-06-19T00:00:00.0000000Z` — seven
fractional digits, which is more than the three that most ISO-8601 parsers accept. A strict parser
rejects it outright. `[prior-probe: Jellyfin 10.11.11, 2026-06-19]`

**Depends on it:** clients have already built tolerance for this (the tvOS client ships a custom
transcoder for exactly this reason), so emitting three digits would not break them. But emitting
*seven* is what the differential harness compares against.

**Atrium does:** emits seven fractional digits and a `Z` suffix. Accepts anything ISO-8601 on input,
with or without a timezone; a missing timezone is read as UTC.

### 1.3 Durations and positions are .NET ticks

**Jellyfin does:** expresses `RunTimeTicks`, `PositionTicks`, `PlaybackPositionTicks` and
`StartPositionTicks` in **ticks of 100 nanoseconds** — 10,000,000 ticks per second.

**Depends on it:** every progress bar and resume position.

**Atrium does:** the same. Internally, durations are stored in ticks, not seconds, so no conversion
can be forgotten at a boundary. Where a source (ffprobe) reports seconds as a float, the conversion
happens once, at ingestion, and rounds rather than truncates.

### 1.4 Item identifiers are 32 lowercase hex characters

**Jellyfin does:** serialises GUIDs in .NET's `"N"` format — 32 hex characters, no dashes, e.g.
`0d41983a5d18d53282f56e7460e2c2cd`. Ids are stable across rescans.
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

They are derived deterministically:

```
guid = DotNetGuidFromBytes( MD5( UTF16LE( type.FullName + key ) ) )
```

where `key` is the item's path, lowercased unless `EnableCaseSensitiveItemIds` is set, and
`DotNetGuidFromBytes` applies .NET's mixed-endian layout (first four bytes little-endian, then two,
then two, then the remaining eight in order).
`[source: Emby.Server.Implementations/Library/LibraryManager.cs:636 @ v10.11.11;
MediaBrowser.Common/Extensions/BaseExtensions.cs:30 @ v10.11.11]`

**Depends on it:** clients key their caches, favourites and resume positions on these strings. A
client's stored state survives a server rescan *because* the ids are derived, not sequential.

**Atrium does:** the same **shape** and the same **stability guarantee**, using a deterministic
derivation from the item's stable identity (Principle VII).

Reproducing Jellyfin's *exact* bytes for the same file is **not a goal** — it would require
matching a C# type's `FullName`, which is an implementation detail of a codebase we do not fork
(Principle IV). Atrium's derivation is its own, documented in the library specification. Any
client that assumes a particular id for a particular file is already broken against Jellyfin, which
changes ids when `EnableCaseSensitiveItemIds` flips.

### 1.5 List responses carry `StartIndex`

**Jellyfin does:** returns `{"Items": [...], "TotalRecordCount": n, "StartIndex": i}`. Emby omits
`StartIndex`. Confirmed across all ten envelope-returning endpoints of the v1 surface.
`[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** no known client reads it (pagination is driven by the request), but its absence
is a visible difference.

**Atrium does:** includes it.

### 1.6 `Container` at item level is a list, not a format

**Jellyfin does:** reports the *demuxer* string at item level, e.g.
`"mov,mp4,m4a,3gp,3g2,mj2"` — ffprobe's format-name list, not a single container. The real
container is on the `MediaSource`. `[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**Depends on it:** clients that pick a player by container have already learned to read the
`MediaSource`, and a client reading the item-level field expects the list form.

**Atrium does:** the same. ffprobe's `format_name` is passed through verbatim at item level; the
resolved single container goes on the `MediaSource`.

### 1.7 A null property is absent, everywhere, by one setting

**Jellyfin does:** omit any property whose value is null. Not per-property and not a judgement —
its whole JSON pipeline is configured with
`DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull`. [source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:33, Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs:148 @ v10.11.11]

Measured too: `/System/Info` declares `PackageName` in its schema and does not send it. [probe: manual request, Jellyfin 10.11.11, 2026-08-26]

**Depends on it:** decoders differ. A generated Swift client distinguishes "absent" from "null"
only when the schema is nullable; a hand-written Kotlin one usually does not.

**Atrium does:** the same, in the base model rather than per route. A `response_model_exclude_none`
flag on every route is one someone eventually forgets, and the one they forget is the one a client
sees a stray `null` on.

> **This entry previously read "per-property and not consistent", marked ⚠️ UNVERIFIED**, and
> planned to let the differential harness enumerate it. It is one line of configuration. The
> assumption was more complicated than the truth, which is worth remembering the next time
> something looks like it needs a harness to work out.

### 1.8 `GET /Items/Latest` returns a bare array

**Jellyfin does:** answers with a JSON array of items, **not** the `{Items, TotalRecordCount,
StartIndex}` envelope every other list endpoint uses. `/Items/Filters` is a third shape again
(`{Genres, Tags, OfficialRatings, Years}`), and `/Search/Hints` a fourth
(`{SearchHints, TotalRecordCount}`). `[probe: tools/probe_query_envelope.py, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** completely. A client decoding a bare array as an envelope gets nothing at all —
not a degraded result, an empty one. This asymmetry is the reason the probe that measured it was
worth writing before any code.

**Atrium does:** the same four shapes, per endpoint, never normalised into one.

---

## 2. Semantics

### 2.1 `UserData` is always present

**Jellyfin does:** returns `UserData` on every item without `Fields=UserData` or
`EnableUserData=true`, and includes `Key` and `ItemId` inside it (Emby does not).
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**Atrium does:** the same.

### 2.2 `/Users/Public` can legitimately be empty

**Jellyfin does:** honours each user's "hidden from login screens" policy flag and returns `200` with
`[]` when every user is hidden. `[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**Depends on it:** clients must fall back to a username field. This is client behaviour, not server
behaviour, but a server that "helpfully" returned hidden users would leak them.

**Atrium does:** the same, including the policy flag.

### 2.3 `LocalAddress` is one string, and may be HTTPS

**Jellyfin does:** returns a single `LocalAddress` string (Emby returns `LocalAddresses[]`), chosen
by matching the requester's network — so over a VPN it returns the VPN-side address. When a
certificate is configured it advertises the **HTTPS scheme and port**, regardless of the scheme the
request came in on. `[prior-probe: Jellyfin 10.11.11, 2026-08-14]`

**Depends on it:** clients that hand this address to a device without a TLS stack (a DLNA renderer)
break when it is HTTPS. This is a genuine footgun that has cost real debugging time.

**Atrium does:** returns a single string and selects by requester network, matching Jellyfin. It
does **not** replicate the HTTPS override: `LocalAddress` reflects the scheme the server is
actually reachable on for that network. ⚠️ **This is a deliberate divergence** — see §4.2.

### 2.4 There are five authentication mechanisms, and one of them wins

**Jellyfin does:** accept **five**, not the four
[api-surface-v1.md §3](api-surface-v1.md#3-authentication-users-and-sessions) lists. The fifth is
`X-Emby-Authorization` carrying a `Token=` component: the reference reads that header and
`Authorization` with the same grammar, and a token in either authenticates. `[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]` It is
the historical Emby form and it is what a great many clients send, so a server implementing only
the documented four would refuse clients that have worked against Jellyfin for years.

All five work on an authenticated API route, and on the image and streaming routes too, where the
query forms are the only practical option.
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`

When a request carries two that disagree, the order is **not** arbitrary. Measured pair by pair,
in both directions each time:

    Authorization  >  X-Emby-Authorization  >  X-Emby-Token  >  ?ApiKey= / ?api_key=

The two query spellings were never set against each other, and `Authorization` against a query
parameter is inferred from the chain rather than measured.

**Depends on it:** a client holding a stale token in one place and a fresh one in another, which
sounds contrived until you notice that clients set a header once when the connection is built and
assemble streaming and image URLs from a template. Resolving in a different order turns a working
request into a `401` for exactly those clients.

**Atrium does:** the same order. [002 plan §6.1](../../specs/002-authentication-users-and-sessions/plan.md#61-token-extraction)
fixed the opposite one and called it arbitrary, on the argument that it only had to be
deterministic. It had to be deterministic **and** the reference's.

### 2.12 The client header's grammar is stricter than "lenient" suggests

**Jellyfin does:** require a scheme word, and it is `MediaBrowser` or `Emby`, compared
case-insensitively. Anything else — `Bearer`, a made-up word, or no scheme at all — and nothing is
read out of the header. Within it, one row per variation, all measured: `[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]`

| Variation | Reference |
|---|---|
| Values quoted, or bare | accepted |
| No space after a comma, or a space *before* one | accepted |
| Extra spaces after the scheme | accepted |
| Components in any order | accepted |
| An unknown component alongside | accepted |
| A trailing comma | accepted |
| **Whitespace around the `=`** | **`401`** |
| **A lowercase component name** (`token=`) | **`401`** |

**Depends on it:** the two refusals are the interesting half. No working client can be sending
either form today, because the reference refuses both.

**Atrium does:** the same, including the two refusals. Being kinder costs nothing today and lets
somebody build a client against Atrium that fails against Jellyfin, which is the direction that
matters — see §6.

### 2.13 `DeviceId` is mandatory on one route, not on the header

**Jellyfin does:** answer `200` on an ordinary authenticated route for a client header carrying no
`DeviceId` at all, and `400` for one on `POST /Users/AuthenticateByName`. `[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]`
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** clients that set the header once and reuse it, minus the component, on routes
where nothing needs a session.

**Atrium does:** the same. [002 plan §6.3](../../specs/002-authentication-users-and-sessions/plan.md#63-the-x-emby-authorization-grammar)
called it "the one fatal case", which is true of one route and not of the parser: a parser that
raised would refuse requests the reference serves.

### 2.5 `SortBy` vocabulary

**Jellyfin does:** supports `SortName`, `DateCreated`, `PremiereDate`, `PlayCount`, `DatePlayed`,
`Random`, `AlbumArtist`, `Artist` — a superset of Emby's.
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**Atrium does:** the same set. How `SortName` itself is derived is §2.6.

### 2.6 `SortName` has two derivations, and three types use the second

**Jellyfin does:** derives a sort name in one of two entirely different ways depending on the item
type. `[probe: tools/probe_sort_names.py, Jellyfin 10.11.11, 2026-08-26]`

For movies, series, albums, artists and playlists: trim and lowercase, strip configured articles
at the start, in the middle and at the end, remove one configured character set, replace another
with spaces, **left-pad every digit run to ten characters**, then fold diacritics. Nothing trims or
collapses the whitespace this leaves behind, so `Rock & Roll` becomes `rock  roll` with two spaces
and `S.W.A.T.` becomes `s w a t ` with a trailing one.

For `Audio`, `Episode` and `Season`: a zero-padded numeric prefix followed by the **raw** name,
with none of the above applied. Audio pads disc and track to four; Episode pads season to
**three** and episode to **four**; Season is the number alone.
`[source: Audio.cs:94-98, Episode.cs:238-242, Season.cs:149-152 @ v10.11.11]`

**Depends on it:** every ordered list a client draws. This is not a field a client reads and
compares — it is the order items arrive in, which no client can correct and most will not even
recognise as wrong.

**Atrium does:** both, exactly, including the whitespace artefacts. Full specification in
[003 §3.7](../../specs/003-library-configuration-and-scanning/spec.md).

Two temptations to name, because both are what a careful implementer would otherwise do:

1. **Tidying the whitespace.** Collapsing `rock  roll` to `rock roll` changes the ordering of every
   name containing a removed character, quietly, and only for some names.
2. **Using one sort-name function for everything.** Applying the base rule to audio makes `The
   Song` sort under `s` instead of `T` and reorders every album in the library.

### 2.7 Playlists hold each item at most once

**Jellyfin does:** de-duplicates in two stages — dropping items already in the playlist, then
dropping repeats within the incoming batch. Measured on both code paths: creating a playlist with
the same id twice yields one entry, and adding an id already present yields zero new entries.
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-26]`
`[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:222-225 @ v10.11.11]`

**Depends on it:** a client adding a track already present sees the count stay the same. It is not
told anything — the request succeeds.

**Atrium does:** the same. The argument for allowing duplicates is real — a set list may want the
same track twice — and it loses to Principle I.

**Entry identity survives this.** A row is still addressed by its own `PlaylistItemId`, not by the
item's `Id`; uniqueness of items does not make the two the same thing.

### 2.8 `Move`'s `newIndex` is the entry's position after the move

**Jellyfin does:** removes the entry, then inserts it so it ends up at exactly `newIndex` in the
resulting list. On `[A B C D E]`, moving index 0 to index 3 gives `B C D A E`, not `B C A D E`.
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** every drag-and-drop reorder. Upward moves are identical under either reading,
so a client built against the wrong one works until a user drags something **down**.

**Atrium does:** the same. This project's specification asserted the opposite until it was
measured — which is the whole reason the probe was written before the code.

### 2.9 A stop report resolves through six branches, not two thresholds

**Jellyfin does:** decides between *discard the position*, *mark played* and *keep it resumable*
through an ordered rule. A stop with no position counts as played to the end; an unknown runtime
counts as played; below 5% of runtime the position is discarded; above 90%, or within one second of
the end, it is played; an item whose **runtime** is under 300 seconds is played rather than
resumable; otherwise the position is kept. The percentage comparisons are strict at both ends.
`[probe: tools/probe_playstate.py, Jellyfin 10.11.11, 2026-08-26]`
`[source: Emby.Server.Implementations/Library/UserDataManager.cs:296-352 @ v10.11.11]`

**Depends on it:** what appears in "continue watching", which is the most-used row in most clients.

**Atrium does:** the same, with the same defaults. Full rule in
[007 §3.7](../../specs/007-user-data-and-playstate/spec.md).

The branch most easily missed is the 300-second one: it is a floor on the **item's runtime**, not
on the position. A short clip stopped in the middle is *played*, not resumable. Reading it as a
position floor produces a server that keeps resume points for every short item.

### 2.10 The image and delivery routes accept a token and require none

**Jellyfin does:** answer `GET /Items/{id}/Images/Primary` and
`GET /Videos/{id}/stream?static=true` with `200` to a request carrying **no token at all**. All
four mechanisms are accepted there; not one of them is required. `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** yes, and in the shape that is hardest to see from inside a client. A bare URL
handed to an image loader or an external player is exactly what these routes are for, and a client
that has never sent a token on them is a client a server can break by starting to want one.

**Atrium does:** not decided here. Those routes belong to [006](../../specs/006-images/spec.md) and
[008](../../specs/008-playback-negotiation-and-delivery/spec.md); what 002 owns is the measurement
and the fact that a token is *accepted*. The decision is recorded and deferred per §3.0.1
tie-break 3 — taking it now would be taking it about code nobody writes for months, with the least
information it will ever have.

What 002 does record is the consequence, so that whoever takes it takes it knowingly: on the
reference **an item id is a capability**, and any divergence 006 or 008 chooses is one a client can
observe.

### 2.11 A disabled account is refused with `403`, not `401`

**Jellyfin does:** refuse a disabled account with `403` and an unknown username with `401`. The
bodies are identical — `text/plain`, 25 bytes, `Error processing request.` — so the **status** is
the whole of the difference. The disabled account answers `403` whether the password it was sent is
right or wrong, so the refusal discloses that the account exists and is disabled, and discloses
nothing about the password. `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** every client, in the direction that matters most. Clients re-authenticate on
`401` and show an error on `403`. A server answering `401` for a disabled account puts a client in
a login loop — prompt, correct password, `401`, prompt again — with the user's credentials correct
every single time.

**Atrium does:** the same. **This overturns a decision that was deliberate rather than an
oversight.** [002 §3.3](../../specs/002-authentication-users-and-sessions/spec.md#33-post-usersauthenticatebyname--authenticateuserbyname)
specified `401` for a disabled account and called it indistinguishable *on purpose*, on the
argument that disclosing account state is an enumeration risk. The risk was real and it does not
disappear; what changed is that the reference discloses it anyway, so refusing to would be a delta
that protects nobody — the reference is still there to be asked. The cost is bounded and now
written down: an unauthenticated caller can tell a disabled account from a name that was never
registered. It cannot tell a right password from a wrong one, which is the disclosure that would
matter more.

> **Three refusals remain unmeasured, and the probe declines to measure them.** An enabled account
> sent a wrong password, an account locked out by failed attempts, and a live token whose user was
> disabled after it was issued. Each needs a real account to fail against, and failing against one
> moves a lockout counter no probe can reset. They are
> [002 OQ-5](../../specs/002-authentication-users-and-sessions/spec.md#7-open-questions), to be
> measured against a throwaway enabled account, and until then the first is an assumption rather
> than a measurement.

### 1.9 Every response carries `X-Response-Time-ms`

**Jellyfin does:** stamps every response with the time it took, in fractional milliseconds —
`X-Response-Time-ms: 2.1329`. Its middleware is registered unconditionally; the two configuration
flags beside it gate a slow-response *log line*, not the header. `[probe: manual request, Jellyfin 10.11.11, 2026-08-26]` `[source: Jellyfin.Api/Middleware/ResponseTimeMiddleware.cs:17, Jellyfin.Server/Startup.cs:163 @ v10.11.11]`

**Depends on it:** no known client. It is a diagnostic.

**Atrium does:** the same. Omitting it would be a difference on **every** response in the project —
55 rows of noise in the first differential run — for a middleware that costs fifteen lines.

> **This project did not know the header existed.** Neither specification mentioned it, and no
> amount of reading either codebase would have surfaced it: it took issuing one real request and
> reading what came back. It is the smallest useful argument for the differential harness that
> feature 010 delivers.

### 1.10 JSON responses carry `charset=utf-8`

**Jellyfin does:** sends `Content-Type: application/json; charset=utf-8`, as ASP.NET Core's JSON
formatter does. `[probe: manual request, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** unlikely — a client parses JSON as UTF-8 regardless. But it is on every response.

**Atrium does:** the same, through a response class rather than a middleware, so the content type
belongs to the thing that produced the body. Starlette appends `charset=utf-8` only to `text/*`
media types, so its `JSONResponse` would send a bare `application/json`.

### 1.11 There are three error shapes, not one

**Jellyfin does:** answer a refusal in one of two forms, decided by **where** the refusal happened.
`[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]`

| Refusal | Shape |
|---|---|
| Unauthenticated request | `401`, **empty body**, `Content-Length: 0`, no `Content-Type`, **no `WWW-Authenticate`** |
| Path matching no route | `404`, **empty body**, no `Content-Type` |
| A method the path does not have | `405`, **empty body**, no `Content-Type`, and `Allow` naming every method that path has `[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]` |
| An item a handler could not find | `404`, **RFC 9457 problem details** as JSON |
| A malformed value the model binder rejected | `400`, **RFC 9457 problem details** with an `errors` map |
| A controller that refused the request itself | `4xx`, **`text/plain` with no `charset`**, and the fixed 25-byte body `Error processing request.` `[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-26]` |

```json
{"type": "https://tools.ietf.org/html/rfc9110#section-15.5.5",
 "title": "Not Found", "status": 404, "traceId": "00-b1be…-8a91…-00"}

{"type": "https://tools.ietf.org/html/rfc9110#section-15.5.1",
 "title": "One or more validation errors occurred.", "status": 400,
 "errors": {"itemId": ["The value 'not-a-guid' is not valid."]},
 "traceId": "00-0138…-3158…-00"}
```

The split is not arbitrary: the empty ones are produced before the framework's controller pipeline
runs, the JSON ones by that pipeline, and the third by a controller inside it.

**The absent `charset` on the third shape is the reference's, and it is easy to lose.** JSON
responses carry `charset=utf-8` (§1.10) and this one does not; web frameworks append it to any
`text/*` type unless told otherwise, so the natural way to write this handler produces
`text/plain; charset=utf-8` and a difference on every refusal in feature 002.

**The same status carries different bytes depending on which layer refused.** An unauthenticated
`GET /Users/Me` is the empty `401` in the first row; a `401` from `POST /Users/AuthenticateByName`
for an unknown username is 25 bytes of `text/plain`. The `400` for a missing
`X-Emby-Authorization` and the `403` for a disabled account (§2.11) are that same third shape. A
golden response that compares bytes catches this; a test that asserts a status code does not, and
002 has four acceptance criteria that would otherwise have been written against the status alone.

**Depends on it:** a client branching on a body it expects to be JSON. FastAPI's own
`HTTPException` sends `{"detail": "…"}`, which is neither shape.

**Atrium does:** all three, per refusal. `traceId` is a W3C trace-context identifier and is
per-request by definition, so it is compared by shape rather than by value.

> **The empty shapes were documented here and not implemented, for three tasks.** Until 001 had
> routes there was no path to get wrong, so nothing noticed that an unmatched path answered
> `{"detail": "Not Found"}` — the exact body two paragraphs above call neither shape. The
> route-registration work (001 T17) was the first thing to ask the question, and it asked it by
> issuing the request rather than by reading this file. A documented behaviour with no test is a
> plan, not a behaviour.

> **The absent `WWW-Authenticate` is worth keeping absent.** RFC 7235 says a 401 SHOULD carry one.
> Adding `Basic` would make a browser open a credentials dialog on routes no browser was meant to
> drive — so here, matching the reference is also the safer behaviour.

### 1.12 An unrecognised query value is ignored, not rejected

**Jellyfin does:** answer `200` with a full, unfiltered result for `/Genres?SortBy=NotASortOption`.
`[probe: manual requests, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** yes, and this is the measurement behind a decision already taken.
[005 §3.3](../../specs/005-item-query-api/spec.md) accepts a bounded delta — Tier 3 query
parameters are ignored rather than rejected — on the argument that rejecting turns a partial answer
into no answer *and is itself a delta*. That argument was reasoned; this is the evidence.

**Atrium does:** the same, and counts what it ignored (010 §3.6).

### 1.13 The `CamelCase` profile really is camelCase

**Jellyfin does:** answer `Accept: application/json; profile="CamelCase"` with **camelCase property
names**, and echo the matched profile in the response's content type. The other two declared types
answer in PascalCase. `[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]`

| Request `Accept` | Property names | Response `Content-Type` |
|---|---|---|
| `application/json` | PascalCase | `application/json; charset=utf-8` |
| `application/json; profile="PascalCase"` | PascalCase | `application/json; profile="PascalCase"; charset=utf-8` |
| `application/json; profile="CamelCase"` | **camelCase** | `application/json; profile="CamelCase"; charset=utf-8` |

Three declared content types, two behaviours. The profile selects an output formatter with a
different naming policy, and the registration comment says so in as many words — *"Allow requester
to change between camelCase and PascalCase"*.
`[source: Jellyfin.Server/Extensions/ApiServiceCollectionExtensions.cs:126-129,
Jellyfin.Api/Formatters/CamelCaseJsonProfileFormatter.cs:15-18,
src/Jellyfin.Extensions/Json/JsonDefaults.cs:21,55-58 @ v10.11.11]`

Four measured details that a reimplementation needs and that reading the document does not give:

- **The match is on the media type's parameter, leniently.** `profile=CamelCase` unquoted and
  `profile="camelcase"` both match; a **charset parameter alongside it does not** — that request
  falls back to plain `application/json`. An unknown profile falls back too.
- **Ranking is ordinary content negotiation.** `application/json, application/json;
  profile="CamelCase"` selects the first; with `q=` values the higher one wins.
- **Names are converted at every depth**, and **dictionary keys are not converted at all** —
  `ProviderIds`, `ImageTags` and `ImageBlurHashes` keep their keys, because the reference sets
  `PropertyNamingPolicy` and never sets `DictionaryKeyPolicy`.
- **The conversion is .NET's, not "lower the first letter".** A leading run of capitals lowers all
  but the last of them. Over the 1043 names of the pinned document the two rules disagree exactly
  **once** — `UICulture` becomes `uiCulture`, and lowering the first letter would give `uICulture` —
  and that one name is the one that was measured. The other name with a leading run, `ETag`,
  becomes `eTag` under both rules, which is why the difference is so easy to miss: a spot check
  almost certainly lands on a name where the wrong rule is right.

**Depends on it:** neither analysed client sends the profile, and both were checked rather than
assumed. music-client decodes with a PascalCase naming strategy of its own and sets no `Accept`
profile. video-client generates its API client from the OpenAPI document after a build step that
**deletes the `profile=` content types** — they produced unusable generated method names — so its
generated code cannot ask for one. That build step's comment gives the same reason this repository
did: all three point at the same schema. Both projects read the schema and inferred the behaviour.

But a client that did send it and got PascalCase would not get a degraded response; it would get an
**empty object** out of its decoder, which is the failure mode of §1.1 exactly.

**Atrium does:** the same, all of it — the lenient match, the charset that stops it, the ranking,
the echo, and the conversion at every depth with dictionary keys untouched. The conversion is
applied by the response models themselves rather than to the finished body, because that is the
only place a property name can still be told apart from a dictionary key; a conversion applied to
the bytes would rename `ProviderIds`' keys and be wrong the first time feature 005 returns one.

The rule was verified rather than reasoned: **293 property names were read from nine endpoints
under both profiles, and all 281 conversions agreed** with the implementation — the eight names
left alone being exactly the dictionary keys.
`[probe: tools/probe_content_type_profiles.py, Jellyfin 10.11.11, 2026-08-26]`

> **This is what reading a schema instead of a server costs.** The claim it replaces —
> "answers all three identically" — carried a `[spec: …]` citation, was true of the *schema*, and
> was wrong about the server. It also had a passing conformance test, which asserted that Atrium's
> three answers agree with each other. They did. Nobody had asked the reference.

### 1.14 Paths match case-insensitively, and tolerate one trailing slash

**Jellyfin does:** route `/system/info/public`, `/SYSTEM/INFO/PUBLIC` and `/System/info/Public` to
the same handler as `/System/Info/Public`, and answer `/System/Info/Public/` with the same body.
`/System/Info/Public//` is a `404`. ASP.NET Core's routing compares path segments without regard to
case; the trailing slash is one empty segment, and two are one too many.
`[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-26]`

**Depends on it:** any client that lowercases a URL before sending it, and there is a long tail of
reasons one might — a hand-written path literal typed in the wrong case, a URL normaliser, a proxy
that canonicalises, a configuration file someone edited. None of them are exotic, and a client
built against the reference has never had a reason to notice it was relying on this.

**Atrium does:** the same, by rewriting a request's path to the route's own spelling before routing
it. Only the segments a route declares literally are respelled; a path **parameter** is data and
reaches the handler exactly as it arrived, because lowercasing an identifier is invisible until
something case-sensitive reads one.

> **The framework's default here is not neutral, it is a third behaviour.** Starlette answers an
> unmatched trailing slash with a `307` redirect — a round trip the reference does not make — and
> answers the *doubled* slash with a `307` to a URL that works, where the reference refuses. So
> "leave the default alone" would not have meant "differ in one small way"; it would have meant
> differing in two directions at once.

---

## 3. Defects

Principle V: the default is to replicate. Each entry states what Atrium does and why — and this
section opens with the procedure that produces those answers, because "replicate unless you have a
good argument" is not a procedure, it is a preference with a disclaimer.

### 3.0 How the decision is made

One question decides it: **can a client have built something that being correct would break?**
Principle I is about what a client can observe, not about what is correct, and this is the form
that question takes for a defect.

The table below is a fast heuristic for answering it. **Direct evidence overrides the heuristic**
— see §3.0.1.

| Class | Shape of the defect | What clients do about it | Default |
|---|---|---|---|
| **A** | **Fails loudly** — 5xx, reset connection, unparseable body | They cannot build *on* it, only *around* it: a fallback, or an error to the user | **Diverge — be correct** |
| **B** | **Succeeds wrongly** — 200 with a wrong value, wrong unit, wrong content | They build *compensating* code that assumes the wrong value | **Replicate** |
| **C** | **Omits something** — absent field, absent header | They treat it as absent, which is what it is | **Supply it**, after checking |

The reasoning behind class A: nobody can depend on a failure in a way that a *success* breaks. A
client meeting a 500 either has a fallback — which stays unused, harmlessly — or shows an error,
which it now does not have to. A client using the failure as a capability probe gets a better
answer from a working response than from a broken one.

The reasoning behind class B is the mirror image, and it is the one that catches people out.
**Fixing a wrong-but-usable response invalidates the workaround built on top of it.** A client that
compensates for a wrong value by correcting it produces a doubly-corrected value once the server is
fixed. Being right is not automatically safe.

Class B has two escape hatches, and between them they are where most real cases land.

**If every plausible compensation is defect-tolerant, diverge.** A client that ignores a field it
knows to be unreliable is unaffected when the field becomes reliable. A client that *sniffs* rather
than assumes is unaffected either way.

**If no compensation is possible at all, diverge.** A class-B defect that a client cannot work
around behaves like class A in the only respect that matters: replicating it protects nobody,
because there is nobody to protect. §3.4 is exactly this case, and it is not rare — a defect that
forces a client into a corner is precisely the sort that gets noticed and reported.

### 3.0.0 Replication is not free, and for this project it is not the lazy option

For a fork, replicating a defect means leaving code alone. **For Atrium it means writing extra code
to reproduce a mistake**, and then a test to prove the mistake is faithfully reproduced, and then a
comment explaining to the next reader why it is there.

That cost is real and it belongs in the decision. It does not override Principle I — a client that
would break still outranks the tidiness of our source — but where the evidence is balanced, the
side that requires deliberately writing bug code needs the stronger argument, not the weaker one.

### 3.0.1 The tie-breaks

When the class does not settle it, in this order:

1. **Does a known client compensate, and does the compensation break?** Answerable for the clients
   this project can read, and for the rest it is what the differential harness is for. Absent
   evidence, assume a compensation exists.
2. **What is upstream's position?** Three answers, and they are not the same:

   | Upstream state | What it tells us | Weight |
   |---|---|---|
   | **Fixed** | The behaviour is a transient, not a contract. Replicating means matching something on its way out and undoing it at the next pin bump — and any client depending on it is already broken against the next release | Toward **diverge** |
   | **Judged and deliberately kept** | The behaviour is durable, and someone who knows the codebase decided it is right or that changing it costs too much | Toward **replicate** |
   | **Not judged** | Nothing at all | **None** |

   **"Not judged" includes a closed pull request.** A PR can be closed for scope, for process, for
   maintainer bandwidth, or because nobody got to it — none of which is a ruling on the behaviour.
   Reading a rejection as a verdict is the easiest mistake in this whole procedure, and §3.4 is a
   case where it would have produced exactly the wrong answer.

   [ADR-0004](../decisions/0004-pin-to-jellyfin-10-11.md) pins the contract to `10.11.x`; upstream
   head does not define the contract, but it does define the **direction**.

   ⚠️ **This tie-break must not become "wait for upstream".** This project cannot reliably move
   upstream state — see §3.4 — so a defect that is fixable in principle may be unfixable in
   practice, and a decision deferred on that basis is a decision never made.
3. **Is the defect in a code path v1 has at all?** If not, the decision is recorded and deferred
   rather than argued now. A decision made about code nobody will write for a year is a decision
   made with the least information it will ever have.

### 3.0.2 What is never acceptable

- **Inventing a third behaviour.** Where the reference 500s and correctness says 200, the choice is
  those two. A tidy `400` is worse than both: it is a delta from the reference *and* from correct.
- **Fixing a defect because it is obviously wrong.** Obviousness is not evidence. Principle V.
- **Replicating a defect without recording it**, so that a later contributor "fixes" it.
- **Deciding once for a whole endpoint.** Defects are per behaviour, and one endpoint can carry two
  that need opposite treatment — see §3.2, which is exactly that.
- **Treating a closed pull request as a ruling.** See tie-break 2.

### 3.0.3 The shape of a safe divergence

Where a divergence is unavoidable, its **shape** decides how much risk it carries. Best first:

1. **Gated on an explicit client declaration.** The new behaviour happens only for clients that
   said something specific about themselves. A client that never makes that declaration cannot
   observe any difference — the divergence is invisible to everyone who did not ask for it. §3.4 is
   this shape, and it is why that divergence is cheap.
2. **Strictly more correct on a path that previously failed.** Nothing to break, because nothing
   worked. §3.2 symptom 1.
3. **Strictly more information in a place clients read optionally.** A header that was absent, a
   size that was unknown. §3.3.
4. **Changing a value clients already read.** The dangerous shape. Needs evidence about
   compensations, not reasoning about correctness. §3.2 symptom 2.

Prefer 1. Where a defect can be diverged from *conditionally*, do that rather than diverging
unconditionally, even when the unconditional version looks cleaner.

### 3.1 `TotalRecordCount` is 0 on by-name endpoints without `limit` — class B

**Jellyfin does:** `/Artists`, `/Artists/AlbumArtists`, `/Genres`, `/MusicGenres` and `/Studios`
share the `GetItemValues` path, which **disables counting when the request has no `limit`**:

```
/Artists?UserId=…            -> TotalRecordCount=0  Items=7
/Artists?UserId=…&limit=500  -> TotalRecordCount=7  Items=7
```

`[prior-probe: Jellyfin master, 2026-08-05; upstream jellyfin/jellyfin#17541]`

**Depends on it:** no. Known clients map `Items` and ignore `TotalRecordCount` on these routes —
precisely because it is unreliable. A client that *paginated* on it would be broken today.

Class B, but through the escape hatch of §3.0: the only compensation anyone builds for an
unreliable field is to ignore it, and ignoring a field is defect-tolerant — it does not stop
working when the field starts being right.

**Atrium does:** **diverge — always return the true count.** The argument required by Principle V:
no client can observe the difference in a way that changes its behaviour, because a correct count
is what a client that reads the field already expects, and the clients that ignore the field are
unaffected. The upstream fix is approved, so replicating the defect would mean deliberately
matching a behaviour that is on its way out.

### 3.2 PCM/WAV output — one bug, two symptoms, two classes

The worked example for §3.0, and it is a good one because the naive answer — "be correct" — is
right for one symptom and wrong for the other.

**The cause is a single block** of `EncodingHelper.GetProgressiveAudioFullCommandLine`, which for
any `pcm_*` encoder forced the raw muxer `-f s16le` and fed `-ar` from `AudioBitRate` — the wrong
field, and an optional one.
`[prior-probe: Jellyfin 10.11.11, 2026-08-03; upstream jellyfin/jellyfin#17537, merged to master
2026-08-05, not in any 10.11.x]`

Two symptoms come out of it:

#### Symptom 1 — `GET /Audio/{id}/stream.wav` with a PCM codec returns 500

`-ar` fed from an absent `AudioBitRate` produces a malformed command line, and ffmpeg never starts.

**Class A.** A client cannot build on a 500. Whatever it does today — fall back to FLAC, show an
error — keeps working when the request succeeds instead.

**Atrium: diverge. Serve valid WAV**, with a RIFF header, a real `Content-Length` and `Range`
support.

#### Symptom 2 — `GET /Audio/{id}/universal` with `Container=wav` returns headerless PCM

`200`, `Content-Type: audio/wav`, and a body with no `RIFF` header, because the raw muxer was
applied regardless of the container the client asked for.

**Class B, and the trap is real.** A client compensating for this must **synthesise a RIFF header
and prepend it** — it has no other way to make the stream playable. Send a correct header to that
client and it produces **two**, which is corrupt audio. "Being correct" breaks it.

So the class default says replicate. The tie-breaks say otherwise, and both are needed:

1. **Does a known compensation break?** A workaround cannot assume which server version it is
   talking to, so a competent one sniffs for the `RIFF` magic bytes before prepending. A sniffing
   compensation is defect-tolerant and survives the fix. One that prepends blindly does not — and
   that client is **already broken against upstream head**, where the fix has landed.
2. **Is it fixed upstream?** Yes, in `master`. Replicating a headerless `audio/wav` would mean
   deliberately emitting a malformed body to match a version that no longer emits it, and undoing
   that at the next pin bump.

**Atrium: diverge. Serve a real RIFF header** — and record that this one carries a risk symptom 1
does not: a client that blindly prepends a header receives corrupt audio. If the differential
harness ever finds such a client, this decision is revisited, not defended.

#### Status in v1

Tie-break 3 applies: producing PCM requires re-encoding, which is transcoding, which is out of v1
([008 §2](../../specs/008-playback-negotiation-and-delivery/spec.md)). **v1 serves neither
symptom's path.** The decision is recorded now because the reasoning is fresh and the alternative
is re-deriving it in a year with less information — not because anything is being built.

### 3.3 Transcoding responses carry no `Content-Length` or `Accept-Ranges` — class C

**Jellyfin does:** streams transcoded output chunked, with no size and no range support.

**Depends on it:** negatively — DLNA renderers refuse a stream with no size, which is why clients
that cast run a local sizing proxy.

**Atrium does:** **diverge for remuxed output**, where the output size is computable or the file is
seekable: send `Content-Length` and honour `Range`. Same reasoning as §3.2 — a client cannot branch
on a response being more correct.

### 3.4 HDR10+ metadata stripped from clients that asked for it — class B, no compensation

The second worked example, and it is the one where the heuristic gives the wrong answer and the
evidence rescues it.

**Jellyfin does:** during a **stream copy**, plans removal of the HDR10+ SEI from any
`DOVIWithHDR10Plus` video stream as soon as the client's requested range types contain `DOVI` —
without considering that the client may have declared `DOVIWithHDR10Plus` itself. The removal is
carried out with `-bsf:v hevc_mp4toannexb,hevc_metadata=remove_hdr10plus=1`, and the rewritten
bitstream **breaks HLS fMP4 playback on AVPlayer**.
`[source: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs @ v10.11.11; the removal logic
is unchanged since jellyfin/jellyfin#13277 and still unchanged as of master post-#17571; related
upstream issue jellyfin/jellyfin#16687]`

**Class B by shape** — a `200` and a stream, not a failure.

**But no compensation exists.** No device profile combination avoids the strip while keeping Dolby
Vision remuxing, because the `dvh1` tagging in `DynamicHlsController` requires `DOVI` in the range
type. The client is cornered: declare `DOVI` and lose HDR10+ along with playback, or do not declare
it and lose Dolby Vision remuxing entirely. **Escape hatch 2 of §3.0 applies** — a class-B defect
nobody can work around protects nobody when replicated.

**Upstream position: not judged.** A fix was proposed and the pull request closed under the
project's LLM/AI development policy. The automated quality gate passed; no reviewer assessed the
behaviour. That is a process outcome, not a ruling, and tie-break 2 therefore contributes
**nothing** — reading it as "upstream considered this and declined" would invert the decision on
evidence that does not exist.

> This is the concrete case behind the warning in §3.0.1: **this project cannot reliably move
> upstream state.** Contributions authored with AI assistance are not accepted upstream, and every
> commit in this repository carries a `Co-Authored-By` trailer. A defect that is fixable in
> principle is therefore not fixable in practice by this route, and waiting for upstream is not a
> plan. The way to obtain a judgement is an **issue describing the behaviour**, hand-authored,
> proposing no code — a different artefact, subject to a different policy, and the one that gets
> the defect assessed on its merits.

**Atrium does: diverge, in the safest available shape.** Honour an explicit `DOVIWithHDR10Plus`
declaration: keep the metadata for clients that made it, strip it for clients that did not, exactly
as the reference already treats the neighbouring `DOVIWithELHDR10Plus` coexistence case. This is
shape 1 of §3.0.3 — **a client that never declares `DOVIWithHDR10Plus` cannot observe any
difference at all**, which is what makes the divergence cheap rather than merely justified.

**In scope for v1**, unlike §3.2. Stream copy is remuxing, and remuxing is v1's ceiling
([008 §3.3](../../specs/008-playback-negotiation-and-delivery/spec.md)). And §3.0.0 applies with
force here: Atrium never had this defect, so replicating it would mean writing a bitstream filter
whose only job is to remove something the client said it wanted.

---

## 4. Deliberate exceptions

Two, and both are listed here so they are never mistaken for oversights.

### 4.1 Atrium identifies as Jellyfin on the fields clients parse

`ProductName: "Jellyfin Server"` and a real `10.11.x` version string. Full reasoning in
[reference-target.md §4](reference-target.md#4-server-identity-what-atrium-tells-clients-it-is).
Humans see "Atrium" in the `Server` header, the `ServerName` field, the logs and the project page.

**The `Server` header is a measured divergence, not a hypothetical one.** The reference sends
`Server: Kestrel`. `[probe: manual request, Jellyfin 10.11.11, 2026-08-26]` Atrium sends `Server: Atrium/<version>`.

A client cannot usefully branch on it — `Kestrel` identifies a .NET web server, not Jellyfin, and
the discriminator multi-server clients actually read is `ProductName`. So this is the one header
where the honest answer costs nothing, and it is where a person looking at a `curl` dump, a proxy
log or a bug report finds out what they are really talking to.

### 4.2 `LocalAddress` does not get an HTTPS override

See §2.3. Jellyfin's behaviour here is not a contract clients rely on; it is a source of breakage
they work around. Atrium reports the scheme it is actually reachable on.

### 4.3 `DELETE /Items/{itemId}` refuses to delete media

**Jellyfin does:** deletes the item and its files, gated by the user's `EnableContentDeletion`
policy.

**Depends on it:** a client's delete button. This divergence **is** observable — a user deletes a
film and finds it still there.

**Atrium does:** permits deletion only for items whose removal takes no file off disk. Playlists
delete; movies, episodes and tracks answer `403`.

Unlike the other divergences in this document, this one is not argued from "no client can tell". It
is argued from consequence. v1 has no trash, no undo and no confirmation flow of its own, so
honouring the route means trusting a client's dialog with an irreversible operation on files the
user may not have backed up. The cost of diverging is a delete button that fails on media. The cost
of not diverging is a bug in a new server destroying somebody's library. Revisited when there is a
trash with a retention window to delete into. Specified in
[009 §3.6](../../specs/009-playlists/spec.md).

---

## 5. Accepted gaps in v1

Deltas that are **not** deliberate choices about what is right, but bounded shortfalls of a first
version. Each is listed with the mechanism that closes it, because a gap without one is just an
undocumented bug.

| Gap | What a client sees | Closing mechanism |
|---|---|---|
| **Tier 3 query parameters ignored** ([005 §3.3](../../specs/005-item-query-api/spec.md)) | A filter that does not narrow — more items than asked for | The ignored-parameter report ([010 §3.6](../../specs/010-conformance-harness/spec.md)); anything real clients send gets promoted |
| **Item fields outside the observed union omitted** ([005 §3.2](../../specs/005-item-query-api/spec.md)) | A field absent that the reference sends | The differential's key-set pass, which exists mainly for this |
| **Policy flags stored but unenforced** ([002 §3.5](../../specs/002-authentication-users-and-sessions/spec.md)) | A restriction that does not restrict | All of them gate features v1 lacks; each is enforced in the change that adds its feature |
| **Image decoration parameters ignored** ([006 §3.2](../../specs/006-images/spec.md)) | `percentPlayed`, `blur`, `foregroundLayer` have no effect | Implement if the differential shows a client sending them |
| **No transcoding** ([008 §2](../../specs/008-playback-negotiation-and-delivery/spec.md)) | "Cannot play this" where the reference would transcode | Out of v1 by decision, not by accident. A v2 candidate |
| **`Path`-derived identifiers differ from the reference's** ([§1.4](#14-item-identifiers-are-32-lowercase-hex-characters)) | Nothing — ids are opaque | Not a gap to close; a deliberate design choice |

The difference between this section and §4 is intent. §4 says *we thought about it and chose
differently*. This section says *we have not done it yet, and here is how we will know when it
matters*.

---

## 6. Non-improvements

Principle I requires that good ideas which would create a delta get written down and then not done.
This list exists so they stop being re-proposed.

| Idea | Why not |
|---|---|
| An aggregate endpoint returning an artist's full discography in one call | Solves a real N+1, but no client would call it. It is a new endpoint: delta. A well-indexed `/Items` query solves the same problem within the contract |
| snake_case JSON behind a content-negotiation header | Every client would still use PascalCase; the alternative would rot untested |
| A capability-advertisement endpoint so clients can use Atrium's better paths | The definition of a delta. If a client has to ask what server it is talking to, the project has failed |
| Richer error bodies than Jellyfin's | Clients parse status codes; a different body shape is a difference they can observe |
| Numeric ids because they are easier to debug | Breaks §1.4 and every client's id parsing |
| Accepting whitespace around `=` in the client header, since the intent is obvious | The reference answers `401` (§2.12). No working client sends it, so tolerating it protects nobody — and it lets a client be developed against Atrium and then fail against Jellyfin |
