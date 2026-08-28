# One client's requirements, traced against v1

**Last verified: 2026-08-28**, against `server-contract.md` as received from the client's author on
2026-08-28, and this repository at `9bcc193`.

[api-surface-v1.md](api-surface-v1.md) is written from the server's side: *these are the endpoints
v1 serves, and here is who asked for them*. This document asks the same question from the other
side, for one real client — **what must Atrium do so that this client cannot tell the
difference?** — which is Principle I with the consumer named.

The client is the one `surface.yaml` calls **video-client**: a tvOS application for movies, series
and music. [api-surface-v1.md §1](api-surface-v1.md#1-how-this-set-was-derived) describes the two
analysed clients by role rather than by name, because their internals are not this repository's to
publish; this one is named here because its author published a conformance document *for* this
repository, written in English and meant to be quoted here. The tag stays `video-client`, so
nothing machine-readable moves.

Much of the v1 surface was derived from this client, so the endpoint half of the answer is
uninteresting and was always going to be: **every operation it calls is already in the 55.** The
useful half is behavioural, and it is where the four gaps of §4 live — none of which is a missing
route.

## 1. How to read the evidence here

One provenance mark is used in addition to the ones in [../README.md](../README.md#conventions):

| Mark | Meaning |
|---|---|
| `[client-contract: 2026-08-28, §4]` | That section of the client's own conformance document, of that date |

**It ranks with `prior-probe`, with one difference that matters.** A `prior-probe` was a
measurement *of the reference* made by this project and carried forward; these are claims made by a
third party about their own software — and, in two places, about Jellyfin. Claims of the first kind
are authoritative for what *the client* does, because its author is the one who can know. Claims of
the second kind are **leads for probes, never measured behaviours** (Principle II), and this
document marks each one as such: §4.3 is the only place they carry weight, and it carries them as
open work.

**No line of the client's source is cited here, and that is deliberate.** The contract traces each
of its own rows to a `file:line` of the client; this document traces to the contract instead. A
path in a repository the reader of this one cannot open is neither verifiable by them nor ours to
publish ([AGENTS.md](../../AGENTS.md), *never cite a path outside this repository*) — the same
policy that keeps [api-surface-v1.md §1](api-surface-v1.md#1-how-this-set-was-derived) describing
its two clients by role. Whoever holds both documents can walk the last step; whoever holds only
this one loses nothing they could have checked anyway.

Everything asserted about *Atrium* below is checkable from this repository, and cites a
specification section, a document line or a source line.

## 2. The answer

| Contract section | What v1 says | Verdict |
|---|---|---|
| §0 Identity — `ProductName` must contain `jellyfin` | `REFERENCE_PRODUCT_NAME = "Jellyfin Server"` ([`src/atrium/__init__.py:26`](../../src/atrium/__init__.py)), argued in [behaviours §4.1](behaviours.md#41-atrium-identifies-as-jellyfin-on-the-fields-clients-parse) | ✅ |
| §0 The flattened routes, and not the pre-10.9 ones | The 10.9+ spellings are in the surface; their `/Users/{userId}/…` predecessors are not, and L0 forbids serving a route that is not listed | ✅ |
| §1 UDP discovery on 7359 | Out of v1, by an accepted decision ([001 §2](../../specs/001-server-identity-and-discovery/spec.md)) | 🔴 [§4.1](#41-udp-discovery-is-out-of-v1-and-the-client-needs-it) |
| §2 Authentication without `X-Emby-Authorization` | Accepted: `AuthenticateByName` reads either header name ([`api/users.py:141`](../../src/atrium/api/users.py)) | ✅, and [§5.1](#51-x-emby-authorization-is-not-the-only-spelling-authenticatebyname-accepts) corrects a document |
| §2 `401`/`403` mean "not authorised", and nothing else | A malformed client header is `400`, a disabled account `403`, an absent token `401` ([002 §3.3](../../specs/002-authentication-users-and-sessions/spec.md), [behaviours §2.11](behaviours.md#211-a-disabled-account-is-refused-with-403-not-401)) | ✅ |
| §3 The thirty operations | All thirty are in the 55 — see [§3](#3-the-thirty-operations-and-the-seven-urls) | ✅ |
| §3 `Fields=Overview,Genres,SortName` | Gated fields, all three served on request ([005 §3.2](../../specs/005-item-query-api/spec.md), [`api/item_dto.py:533`](../../src/atrium/api/item_dto.py)) | ✅ |
| §4 Hand-built image and stream URLs | Four are surface rows; three are not, deliberately — see [§3](#3-the-thirty-operations-and-the-seven-urls) | ✅ / 🔴 |
| §5a The two direct-play switches decide the mode | [008 §3.3](../../specs/008-playback-negotiation-and-delivery/spec.md): a step removed by the request is not silently substituted — the ladder falls through to transcode, with a `TranscodingUrl` | ✅ specified |
| §5b The client rewrites the track indices in the returned `TranscodingUrl` | Nowhere | 🟠 [§4.3](#43-the-track-indices-in-a-transcodingurls-query-are-unspecified) |
| §6 `Range`, `206`, and byte-exact `static=true` | [008 §3.5](../../specs/008-playback-negotiation-and-delivery/spec.md) and acceptance criteria 11–14 and 18 — stricter than the reference, deliberately ([behaviours §3.3](behaviours.md#33-transcoding-responses-carry-no-content-length-or-accept-ranges--class-c)) | ✅ specified |
| §6 Subtitle tracks announced in the HLS master | Nowhere. Subtitle delivery of every kind is out of 008 | 🔴 [§4.2](#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one) |
| §7 What the client does *not* need | Agrees with v1's exclusions, item for item — see [§3.1](#31-the-exclusions-agree) | ✅ |

Three of the four gaps sit in specifications that are still **Draft**, which is the cheapest moment
to close them. The fourth sits in an accepted one.

## 3. The thirty operations, and the seven URLs

**All thirty operations of the contract's §3 are in [`surface.yaml`](surface.yaml)**, and the
cross-reference already exists in machine-readable form: `consumers: [video-client]`.

| Contract §3 group | Operations | Owning feature | Status today |
|---|---|---|---|
| Identity and configuration | 7 | 001, 002, 004 | Implemented |
| Library | 14 | 005, 009 | Implemented, except `GET /Playlists/{playlistId}/Items` (009, Draft) |
| User data | 4 | 007 | Specification accepted; implementation in flight as this was written |
| Playback | 5 | 007, 008 | `PlaybackInfo` and `DELETE /Videos/ActiveEncodings` are 008, still Draft; the three reports are 007, specified and landing with it |

The contract's §4 lists seven URLs the client builds by hand rather than through its generated
client. Four are surface rows; the other three are the interesting ones:

| Hand-built URL | v1 |
|---|---|
| `/Items/{id}/Images/{kind}` | `GetItemImage` (006, implemented) |
| `/Items/{id}/Images/Chapter/{index}` | `GetItemImageByIndex` (006, implemented) — but see [§4.4](#44-chapter-images-are-served-never-generated) |
| `/Videos/{id}/stream?static=true` | `GetVideoStream` (008, Draft) |
| `/Audio/{id}/stream?static=true` | `GetAudioStream` (008, Draft) — its consumer list was one name short until this document, [§5.2](#52-getaudiostream-is-tagged-with-one-consumer-and-has-two) |
| ~~`/Users/{id}/Images/Primary`~~ | **Not in v1, and must not be.** The contract marks it a defect in the client — the route does not exist in 10.11 — and asks that it not be served. It is not, and neither is its replacement `GET /UserImage`, which no analysed client calls |
| `/Videos/{id}/{sourceId}/Subtitles/{index}/Stream.vtt` | Not in v1 — [§4.2](#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one) |
| `/Videos/{id}/Trickplay/{width}/tiles.m3u8` | Not in v1, and the client has parked the feature `[client-contract: 2026-08-28]`. Agreed on both sides |

**Query parameter names and casing are part of this contract**, because these URLs arrive as the
client wrote them: `quality` is always `90`; the trickplay URL uses `MediaSourceId`/`ApiKey` while
the stream URLs use `mediaSourceId`/`api_key` `[client-contract: 2026-08-28, §4]`. Atrium already
matches parameter names case-insensitively ([behaviours §1.15](behaviours.md#115-query-parameter-names-match-case-insensitively)),
so the mixed casing costs nothing.

### 3.1 The exclusions agree

Stated because a matching exclusion is worth as much as a matching feature, and because each of
these would otherwise look like something v1 owes somebody:

| Feature | The client | v1 |
|---|---|---|
| Quick Connect | Never calls it | Excluded ([api-surface-v1.md §10](api-surface-v1.md#10-deliberately-excluded-from-v1)) |
| Live TV / DVR | Out of its roadmap | Excluded |
| The `/emby` path prefix | Not used, measured against Emby | Not served |
| Trickplay | Asked for, but parked | Generation excluded |
| Emby's pre-flattening routes | Only used when the server fails the `jellyfin` test | Not served — [roadmap](../roadmap.md), "Emby dialect" |

## 4. The four gaps

### 4.1 UDP discovery is out of v1, and the client needs it

[001 §2](../../specs/001-server-identity-and-discovery/spec.md) puts it in as many words: *"UDP
autodiscovery on the local network — not in v1; clients take an address."* The client listens for a
broadcast datagram on port **7359**, answers the payload `who is JellyfinServer?` with a unicast
JSON carrying `Id`, `Name` and `Address`, and connects to that `Address` verbatim
`[client-contract: 2026-08-28, §1]`. It gives the network two seconds.

**What the user sees:** the "find my server" screen finds nothing, for ever. Typing the address
works. This is the one requirement in the contract that v1 excludes rather than merely leaves
unwritten, and it is excluded by a specification that is already **Implemented** — so closing it is
an amendment to 001 or a feature of its own, not an edit to a draft.

Two things it is *not*. It is not an endpoint, so [`surface.yaml`](surface.yaml) and the L0 sweep
are untouched by the decision either way — Principle VI is about routes, and this is a datagram. And
it is not a place where a well-meant improvement is available: the contract is explicit that the
second probe, `who is EmbyServer?`, **is not ours to answer**, because a server that answers it is
claiming to be something it is not.

### 4.2 v1 has no way to deliver a subtitle, and this client has one way to receive one

This is the gap with consequences. Three exclusions that are each defensible alone compose into a
server that cannot put a subtitle on a screen:

- `GetSubtitle` is not among the 55, and [008 §2](../../specs/008-playback-negotiation-and-delivery/spec.md)
  excludes *"subtitle extraction, conversion and delivery as a separate route"*;
- subtitle burn-in is out of v1, and recorded as such ([behaviours §5](behaviours.md#5-accepted-gaps-in-v1));
- **nothing anywhere requires the HLS master playlist to announce subtitle tracks.**
  `EnableSubtitlesInManifest` appears in this repository exactly once, as a name in
  [`property-names.json`](property-names.json).

The client's side of it `[client-contract: 2026-08-28, §6]`: for a server it has identified as
Jellyfin it expects `EXT-X-MEDIA:TYPE=SUBTITLES` in the master, requested through the
`DeviceProfile`. It *has* a whole-file WebVTT fallback, but that path is wired for the other
flavour — **so a Jellyfin-identifying server that serves HLS without subtitle tracks in the
manifest shows no subtitles at all, and the client will not compensate**.

**The blast radius is smaller than it first looks, and the shape of it decides the fix:**

| Playback path | Subtitles |
|---|---|
| Direct play / on-device remux, embedded tracks | Fine — the tracks are inside the file the client is already reading byte for byte |
| Anything delivered over HLS (remux or transcode) | None |
| External sidecar files (`.srt` beside the media), any path | None, and none reachable |

Which means the obvious fix is the wrong one: **adding `GetSubtitle` as a 56th endpoint would not
help this client**, because on the Jellyfin path it never asks. The only lever that reaches it is
the manifest. That is a real cost — announcing a track means producing WebVTT for it, which is the
extraction and conversion 008 excluded — and it is a scope decision for 008 while 008 is still
Draft, not something to settle here.

Until it is settled, this belongs in [behaviours §5](behaviours.md#5-accepted-gaps-in-v1) as a gap
wider than the burn-in row records as of 2026-08-28: that row says subtitles are *"delivered as
files"*, and in v1 as specified, they are not delivered at all.

### 4.3 The track indices in a `TranscodingUrl`'s query are unspecified

The contract records two measured behaviours of Jellyfin that the client depends on. The first is
covered: with `EnableDirectPlay` and `EnableDirectStream` false the reference hands back a
`TranscodingUrl` even for a file the profile can play, and 008 §3.3's rule — *a step removed by the
request falls through, and is never silently substituted* — produces the same answer.

The second is not. `[client-contract: 2026-08-28, §5b]` **the reference builds `TranscodingUrl`
from the source's default audio and subtitle tracks, ignoring the `AudioStreamIndex` and
`SubtitleStreamIndex` the client posted** — so the client rewrites those two parameters in the
returned URL's query, which the transcoder does honour. The contract's own summary of the risk is
the precise one: if a server honours the indices in the body, the client still works, because it
overrides with the same values; if a server stops honouring them **in the query**, it breaks.

Nothing in 008 says the delivery routes read those parameters. [008 OQ-8](../../specs/008-playback-negotiation-and-delivery/spec.md)
is adjacent but asks a different question — what the reference *puts into* that URL, not what it
does with one a client has edited.

Both halves are third-party claims about Jellyfin and neither is measured here, which makes this
gap two pieces of work rather than one:

1. a probe that answers whether the reference honours the body's indices, the query's, or both —
   `tools/probe_transcode_decision.py`, which OQ-8 already names;
2. an acceptance criterion in 008 saying that a delivery request carrying `AudioStreamIndex` or
   `SubtitleStreamIndex` is served with those streams.

Without the second, the client's "change the audio language" path breaks against Atrium and no test
in this repository fails.

### 4.4 Chapter images are served, never generated

[006 §3.5](../../specs/006-images/spec.md) is explicit and reasoned: v1 serves chapter images that
exist on disk, does not extract them, and answers `404` per chapter for the ones that do not exist.
The client requests `/Items/{id}/Images/Chapter/{index}` for its scrubbing UI, independently of
Trickplay `[client-contract: 2026-08-28, §4]`.

**What the user sees:** a scrubbing bar with no thumbnails, on a library where Jellyfin would show
them, since Jellyfin extracts them on a background sweep. 006 already anticipates the `404` and the
client already tolerates it, so this is a degradation and not a break — recorded here so that
"missing" is not later confused with "broken", and so the decision to add extraction, if it is ever
taken, has this client's name attached to it.

## 5. Two corrections this trace forced on our own documents

**Both were applied on 2026-08-28**, in the change that carries this line. Neither was a code
change: both were places where a document in this repository said something that this client's
existence contradicts, while the server did the right thing already.

### 5.1 `X-Emby-Authorization` is not the only spelling `AuthenticateByName` accepts

[api-surface-v1.md §3](api-surface-v1.md#3-authentication-users-and-sessions) said the route
*"requires the `X-Emby-Authorization` header"*, and repeated it below the table as **mandatory**.
The client sends that header **never, on any request, including sign-in** — the device-identifying
components travel in `Authorization: MediaBrowser Client="…", Device="…", DeviceId="…", Version="…"`
and nowhere else `[client-contract: 2026-08-28, §2]`. A server built from that sentence refuses this
client at the login screen, and the refusal reads to a user like a wrong password.

Atrium was fine: [`api/users.py:141`](../../src/atrium/api/users.py) reads either header name, and
[behaviours §2.4](behaviours.md#24-there-are-five-authentication-mechanisms-and-one-of-them-wins)
already establishes that the reference reads both with the same grammar. What was wrong was the
prose, now corrected to *a client-identification header in either spelling, carrying a `DeviceId`*.

**One thing was left alone deliberately.** Two error strings in
[`compat/auth.py:137`](../../src/atrium/compat/auth.py) still name only the Emby spelling — a `400`
whose message points at a header the client was never going to send. That is code, and its wording
travels to a client, so it is a change for whoever next opens 002, not a documentation edit.

**And there is a measurement hiding in this.** Whether the *reference* accepts an
`Authorization`-only sign-in was never probed: `tools/probe_auth_mechanisms.py` sets
`X-Emby-Authorization` and only that header on this route, every time it calls it
([line 130](../../tools/probe_auth_mechanisms.py)), so the question was never put. The client
signs into real Jellyfin servers today, which is evidence that it does — third-party evidence, not
reproducible from here, and therefore exactly the shape of lead that Principle II says to turn into
a probe rather than into a sentence.

**It was turned into one, the same day.** The probe now signs in with the components in
`Authorization` and the reference answers `200`
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`, so the corrected
paragraph in api-surface-v1.md §3 rests on a measurement of this repository's own rather than on
this client's word. It is the one row of this document that has stopped being third-party
evidence.

### 5.2 `GetAudioStream` is tagged with one consumer and has two

[`surface.yaml`](surface.yaml) recorded `consumers: [music-client]` for
`GET /Audio/{itemId}/stream`. The tvOS client builds that URL by hand for music playback, because
`/Videos/…` answers `404` for a track `[client-contract: 2026-08-28, §4]`, so the row now carries
`video-client` as well, in both the YAML and
[§8 of the prose table](api-surface-v1.md#8-playback-negotiation-and-delivery).

This changes nothing about what v1 serves — the endpoint was in either way — but the consumer list is
the provenance that [api-surface-v1.md §1](api-surface-v1.md#1-how-this-set-was-derived) rests on,
and a row whose consumers are understated is a row that looks droppable when it is not.

Counting the same way in the other direction: 33 rows of `surface.yaml` carried `video-client`
before this change and the client touches **34** — the thirty operations of its §3, plus the two
image routes, plus `GetVideoStream` and `GetAudioStream`. The thirty-fourth was this row, and the
count now agrees.

## 6. What this document does not do

**It does not grow the surface.** No requirement here promotes an endpoint into v1: the thirty are
already in, the three unserved hand-built URLs are one client defect, one agreed exclusion and one
open decision, and the open one (§4.2) would not be answered by adding a route.

**It does not become a second endpoint table.** [`surface.yaml`](surface.yaml) is the surface, and
`consumers: [video-client]` is where this client is already named; §3 above deliberately rolls up
rather than restating rows that would then drift.

**It is a floor, not a ceiling.** The contract says so of itself: absence from it means *not
measured*, never *not needed*. It describes the client on `main` on 2026-08-28, from its own source
— not from Jellyfin's documentation and not from a differential run. When the client changes, this
document is stale and nothing in CI will notice.

The mechanism that turns any of this into something measured is the same one the constitution
already names: the differential harness of
[010](../../specs/010-conformance-harness/spec.md), run request by request against both servers.
What this document contributes to that is a much smaller suite than 322 paths would suggest — **the
thirty-four rows above, and the four behaviours of §4** — and the observation that the four are
exactly the places where a server can pass every JSON comparison and still leave the user staring at
a video with no subtitles, a scrubbing bar with no thumbnails, or a list of servers that stays
empty.
