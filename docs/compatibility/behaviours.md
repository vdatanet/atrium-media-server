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
`StartIndex`. `[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

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

### 1.7 Absent versus null

**Jellyfin does:** omits many optional properties entirely rather than sending `null`, and the
choice is per-property and not consistent.

**Depends on it:** decoders differ. A generated Swift client distinguishes "absent" from "null"
only when the schema is nullable; a hand-written Kotlin one usually does not.

**Atrium does:** matches Jellyfin per property, verified by the differential harness rather than
by rule. ⚠️ **UNVERIFIED** as a general rule — the per-property behaviour has not been enumerated.
This is a known gap and is the first thing the L3 harness will surface.

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

### 2.4 All four authentication mechanisms work

Listed in [api-surface-v1.md §3](api-surface-v1.md#3-authentication-users-and-sessions). All four
are accepted, on every authenticated route, including the streaming and image routes where the
query forms are the only practical option.

### 2.5 `SortBy` vocabulary

**Jellyfin does:** supports `SortName`, `DateCreated`, `PremiereDate`, `PlayCount`, `DatePlayed`,
`Random`, `AlbumArtist`, `Artist` — a superset of Emby's.
`[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**Atrium does:** the same set, and `SortName` sorting must reproduce Jellyfin's normalisation
(leading articles, diacritics, numeric prefixes) — specified in the item-query feature, not here.

---

## 3. Defects

Principle V: the default is to replicate. Each of these states what Atrium does and why.

### 3.1 `TotalRecordCount` is 0 on by-name endpoints without `limit`

**Jellyfin does:** `/Artists`, `/Artists/AlbumArtists`, `/Genres`, `/MusicGenres` and `/Studios`
share the `GetItemValues` path, which **disables counting when the request has no `limit`**:

```
/Artists?UserId=…            -> TotalRecordCount=0  Items=7
/Artists?UserId=…&limit=500  -> TotalRecordCount=7  Items=7
```

`[prior-probe: Jellyfin master, 2026-08-05; upstream jellyfin/jellyfin#17541]`

**Depends on it:** no. Known clients map `Items` and ignore `TotalRecordCount` on these routes —
precisely because it is unreliable. A client that *paginated* on it would be broken today.

**Atrium does:** **diverge — always return the true count.** The argument required by Principle V:
no client can observe the difference in a way that changes its behaviour, because a correct count
is what a client that reads the field already expects, and the clients that ignore the field are
unaffected. The upstream fix is approved, so replicating the defect would mean deliberately
matching a behaviour that is on its way out.

### 3.2 PCM/WAV transcoding returns 500

**Jellyfin does:** `GET /Audio/{id}/stream.wav` with any PCM `AudioCodec` returns **500**;
`/universal` with `Container=wav` returns **200** with `Content-Type: audio/wav` and a body with
**no RIFF header**. Cause: one block of `EncodingHelper.GetProgressiveAudioFullCommandLine` feeds
`-ar` from an optional `AudioBitRate` and forces the raw `-f s16le` muxer.
`[prior-probe: Jellyfin 10.11.11, 2026-08-03; upstream
jellyfin/jellyfin#17537, merged to master 2026-08-05, not in any 10.11.x]`

**Depends on it:** no client depends on the *failure*. Clients that need sized PCM have built local
proxies around it.

**Atrium does:** **diverge — serve valid PCM/WAV** with a correct RIFF header, a real
`Content-Length` and `Range` support. This is out of v1's transcoding scope (v1 stops at remux), so
the divergence is deferred, but the direction is recorded now because it is one of the few places
where Atrium can be genuinely better without a client being able to tell it is not Jellyfin — a
working response where Jellyfin 500s is not a delta a client has to branch on.

### 3.3 Transcoding responses carry no `Content-Length` or `Accept-Ranges`

**Jellyfin does:** streams transcoded output chunked, with no size and no range support.

**Depends on it:** negatively — DLNA renderers refuse a stream with no size, which is why clients
that cast run a local sizing proxy.

**Atrium does:** **diverge for remuxed output**, where the output size is computable or the file is
seekable: send `Content-Length` and honour `Range`. Same reasoning as §3.2 — a client cannot branch
on a response being more correct.

---

## 4. Deliberate exceptions

Two, and both are listed here so they are never mistaken for oversights.

### 4.1 Atrium identifies as Jellyfin on the fields clients parse

`ProductName: "Jellyfin Server"` and a real `10.11.x` version string. Full reasoning in
[reference-target.md §4](reference-target.md#4-server-identity-what-atrium-tells-clients-it-is).
Humans see "Atrium" in the `Server` header, the `ServerName` field, the logs and the project page.

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
