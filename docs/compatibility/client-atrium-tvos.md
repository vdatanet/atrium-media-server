# One client's requirements, traced against v1

**Last verified: 2026-08-29**, against the client's conformance document as received from its
author on 2026-08-29, and this repository at `95a6b67` — 008 T1 through T12 merged.

[api-surface-v1.md](api-surface-v1.md) is written from the server's side: *these are the endpoints
v1 serves, and here is who asked for them*. This document asks the same question from the other
side, for one real client — **what must Atrium do so that this client cannot tell the
difference?** — which is Principle I with the consumer named. Its sibling
[client-embeat-mobile.md](client-embeat-mobile.md) does the same for the music client, and the two
disagree about almost everything structural; §2 of that document is the summary of how.

The client is the one `surface.yaml` calls **video-client**: a tvOS application for movies, series
and music. [api-surface-v1.md §1](api-surface-v1.md#1-how-this-set-was-derived) describes the two
analysed clients by role rather than by name, because their internals are not this repository's to
publish; this one is named here because its author published a conformance document *for* this
repository, written in English and meant to be quoted here. The tag stays `video-client`, so
nothing machine-readable moves.

Much of the v1 surface was derived from this client, so the endpoint half of the answer is
uninteresting and was always going to be: **every operation it calls is already in the 55.** The
useful half is behavioural, and on 2026-08-28 it was four gaps in specifications. It is now
**eight findings against merged code**, which is a different kind of document: not *what should
008 say*, but *what does this server do to this client today*.

## 1. How to read the evidence here

One provenance mark is used in addition to the ones in [../README.md](../README.md#conventions):

| Mark | Meaning |
|---|---|
| `[client-contract: 2026-08-29, §3]` | That section of the client's own conformance document, of that date |

**It ranks with `prior-probe`, with one difference that matters.** A `prior-probe` was a
measurement *of the reference* made by this project and carried forward; these are claims made by a
third party about their own software — and, in several places, about Jellyfin. Claims of the first
kind are authoritative for what *the client* does, because its author is the one who can know.
Claims of the second kind are **leads for probes, never measured behaviours** (Principle II), and
this document marks each one as such.

**Two editions, and the date in the mark is doing real work.** The contract has been received
twice: 2026-08-28, and a 2026-08-29 edition derived from the client at a later commit. The second
is **narrower, not a retraction**: it declares its scope as *video playback*, and discovery,
authentication and browsing appear in it only where playback depends on them. So the thirty
operations of §3, the seven hand-built URLs of §4, the exclusions of §7 and the UDP discovery of §1
are not restated there — and the rows below that rest on them keep `[client-contract: 2026-08-28,
§N]`, with its older date, rather than being silently re-dated to the newer document. Nothing was
withdrawn; a narrower document simply cannot renew what it does not mention.

What the newer edition adds is the part this repository could not have written for itself: the
client's playback paths, and **what each field of a `PlaybackInfo` response decides**. That is
where every new finding in §4 comes from.

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

| Contract section | What v1 does | Verdict |
|---|---|---|
| §0 `Authorization: MediaBrowser Client=…, DeviceId=…`, token appended | Either header spelling is read for the client identification ([`compat/auth.py:146-152`](../../src/atrium/compat/auth.py)) and for the token ([`:155-177`](../../src/atrium/compat/auth.py)) | ✅ |
| §1 The eleven-field `PlaybackInfo` body | Every one of them is bound ([`api/media_info.py:190-205`](../../src/atrium/api/media_info.py)); `EnableTranscoding: false` decides nothing, which is the reference's own behaviour and not a gap ([008 gate](../../specs/008-playback-negotiation-and-delivery/spec.md)) | ✅ |
| §1 `MediaSources[0]` exists and has `Id` | Emitted for every part of every item, inspection or no inspection ([`media/info.py:410-438`](../../src/atrium/media/info.py)) | ✅ |
| §1 `SupportsDirectPlay`/`SupportsDirectStream` reflect reality | Only where a stored inspection exists — see [§4.1](#41-a-source-with-no-stored-inspection-is-the-clients-documented-dead-end) | 🔴 [§4.1](#41-a-source-with-no-stored-inspection-is-the-clients-documented-dead-end) |
| §1 `TranscodingUrl` present whenever direct is refused | The reference's own condition, transcribed ([`api/media_info.py:381-388`](../../src/atrium/api/media_info.py)) — except in the case above, where nothing runs at all | ✅ / 🔴 |
| §1 Two round trips: the second sets both switches false and takes HLS | [008 §3.3](../../specs/008-playback-negotiation-and-delivery/spec.md): a step removed by the request is not silently substituted — the ladder falls through to transcode, with a `TranscodingUrl` | ✅ |
| §1 `Size` is the byte length of the file being served | Read from the stored part, so it survives a missing inspection ([`media/info.py:427`](../../src/atrium/media/info.py)) | ✅ |
| §1 `MediaStreams[].IsTextSubtitleStream` | Deliberately not emitted ([008 `spec.md:111`](../../specs/008-playback-negotiation-and-delivery/spec.md)) | 🔴 [§4.2](#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one) |
| §1 `DeviceProfile.TranscodingProfiles[].EnableSubtitlesInManifest: true` | Not a field of the bound model ([`api/media_info.py:134-152`](../../src/atrium/api/media_info.py)), so `extra="ignore"` drops it ([`compat/model.py:67`](../../src/atrium/compat/model.py)) | 🔴 [§4.2](#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one) |
| §1 `DeviceProfile.TranscodingProfiles[].Protocol` selects HLS | Compared case-sensitively against `"hls"` ([`media/urls.py:202`](../../src/atrium/media/urls.py), [`:236`](../../src/atrium/media/urls.py)) where `/universal` normalises ([`api/universal_audio.py:267`](../../src/atrium/api/universal_audio.py)) | 🟠 [§4.6](#46-two-spellings-of-hls-and-only-one-of-them-selects-hls) |
| §2 `Range` must answer `206`, never `200` | [`compat/ranges.py:87-140`](../../src/atrium/compat/ranges.py): a well-formed `bytes=lo-hi` inside the file is `PARTIAL_CONTENT`, always | ✅ |
| §2 `static=true` is the original container bytes | [behaviours §2.20](behaviours.md#220-statictrue-serves-the-original-bytes-the-urls-container-is-only-a-label), implemented at 008 T6 | ✅ |
| §3 The master carries `VIDEO-RANGE`, `CODECS`, `FRAME-RATE` | [`media/hls.py:306-319`](../../src/atrium/media/hls.py) writes all three | ✅ |
| §3 The master announces subtitle tracks | One `#EXT-X-STREAM-INF` and nothing else — no `#EXT-X-MEDIA` tag exists anywhere in `src/` | 🔴 [§4.2](#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one) |
| §3 `…/Subtitles/{index}/Stream.vtt` when the manifest carries none | Not a row of [`surface.yaml`](surface.yaml), and L0 forbids serving what is not listed | 🔴 [§4.2](#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one) |
| §3 `AudioStreamIndex`/`SubtitleStreamIndex` overridden on the stream URL | The audio half is a delivery parameter and is honoured ([`api/delivery.py:166`](../../src/atrium/api/delivery.py), [`:625`](../../src/atrium/api/delivery.py)); the subtitle half is not one at all | 🟠 [§4.3](#43-the-clients-track-override-works-for-audio-and-is-dropped-for-subtitles) |
| §3 `GET /Sessions?deviceId=…` for copy verification | The route takes no `deviceId` ([`api/sessions.py:287-293`](../../src/atrium/api/sessions.py)) | 🟠 [§4.4](#44-get-sessions-takes-no-deviceid-and-the-client-sends-one) |
| §3 `DELETE /Videos/ActiveEncodings` on every re-negotiation | 008 T12: keyed on the play session, and it stops the encoder rather than answering `204` and lying | ✅ |
| §3 Workaround 1 — the fMP4 init segment starts a second transcode | Reproduced ([`media/sessions.py:499-506`](../../src/atrium/media/sessions.py)) | 🔴 [§4.5](#45-the-fmp4-init-segment-restarts-the-encoder-which-is-the-defect-the-client-pre-warms-to-dodge) |
| §3 Workaround 2 — the session key contains the `User-Agent` | **Not** reproduced: device, play session and path ([`media/sessions.py:151-164`](../../src/atrium/media/sessions.py)) | ✅, and the workaround is unnecessary here |
| §4 Direct play of a track at `/Audio/{id}/stream?static=true` | Surface row, `video-client` among its consumers since [§5.2](#52-getaudiostream-is-tagged-with-one-consumer-and-has-two) | ✅ |
| §5 The four reports, `PlayMethod` included | 007, implemented — and `PlayMethod` is stored, never used to infer a path | ✅ |
| §1 (2026-08-28) UDP discovery on 7359 | Out of v1, by an accepted decision ([001 §2](../../specs/001-server-identity-and-discovery/spec.md)) | 🔴 [§4.7](#47-udp-discovery-is-out-of-v1-and-the-client-needs-it) |
| §2 (2026-08-28) Authentication without `X-Emby-Authorization` | Accepted: `AuthenticateByName` reads either header name | ✅, and [§5.1](#51-x-emby-authorization-is-not-the-only-spelling-authenticatebyname-accepts) corrects a document |
| §2 (2026-08-28) `401`/`403` mean "not authorised", and nothing else | A malformed client header is `400`, a disabled account `403`, an absent token `401` ([behaviours §2.11](behaviours.md#211-a-disabled-account-is-refused-with-403-not-401)) | ✅ |
| §3 (2026-08-28) The thirty operations | All thirty are in the 55 — see [§3](#3-the-thirty-operations-and-the-seven-urls) | ✅ |
| §4 (2026-08-28) Chapter images for the scrubbing UI | Served, never generated — now recorded as [behaviours §5.8](behaviours.md#58-a-chapter-image-can-never-be-served-in-v1) | 🟠 [§4.8](#48-chapter-images-are-served-never-generated) |
| §7 (2026-08-28) What the client does *not* need | Agrees with v1's exclusions, item for item — see [§3.1](#31-the-exclusions-agree) | ✅ |

**None of the eight findings is a missing route**, and only one of them (§4.2) needs one. That was
true on 2026-08-28 and it survived the re-verification, which is the single most useful thing this
document says to whoever scopes the work: the surface is not the problem.

## 3. The thirty operations, and the seven URLs

**All thirty operations of the contract's §3 are in [`surface.yaml`](surface.yaml)**, and the
cross-reference already exists in machine-readable form: `consumers: [video-client]`. Established
on 2026-08-28 and not restated by the 2026-08-29 edition, whose scope excludes browsing
`[client-contract: 2026-08-28, §3]`.

| Contract §3 group | Operations | Owning feature | Status today |
|---|---|---|---|
| Identity and configuration | 7 | 001, 002, 004 | Implemented |
| Library | 14 | 005, 009 | Implemented, except `GET /Playlists/{playlistId}/Items` (009, Draft) |
| User data | 4 | 007 | Implemented |
| Playback | 5 | 007, 008 | Implemented — `PlaybackInfo` at 008 T5, `DELETE /Videos/ActiveEncodings` at T12 |

The contract's §4 lists seven URLs the client builds by hand rather than through its generated
client. Four are surface rows; the other three are the interesting ones:

| Hand-built URL | v1 |
|---|---|
| `/Items/{id}/Images/{kind}` | `GetItemImage` (006, implemented) |
| `/Items/{id}/Images/Chapter/{index}` | `GetItemImageByIndex` (006, implemented) — but see [§4.8](#48-chapter-images-are-served-never-generated) |
| `/Videos/{id}/stream?static=true` | `GetVideoStream` (008, implemented at T6) |
| `/Audio/{id}/stream?static=true` | `GetAudioStream` (008, implemented at T6) — its consumer list was one name short until this document, [§5.2](#52-getaudiostream-is-tagged-with-one-consumer-and-has-two) |
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

**And one exclusion the newer edition adds, which is worth more than any of them.** Progressive
direct play of *video* is dead on the client side by design: whenever the server says a video
source can direct-play, the client immediately re-negotiates with both switches false and takes
the HLS answer, because the progressive path starves on that hardware at any bitrate
`[client-contract: 2026-08-29, §1]`. **For video there are two paths, not three.** Nothing in v1
changes, and no effort spent making progressive video smooth is spent on this client. Music still
uses it.

## 4. The eight findings

Four of these were the gaps of the 2026-08-28 trace, re-verified against merged code. Four are new,
and all four come from the newer edition's per-path detail.

### 4.1 A source with no stored inspection is the client's documented dead end

`PlaybackInfo` walks the item's sources beside whatever inspection is stored for each, and a source
whose inspection is `None` is **skipped entirely** — the ladder never runs and the annotation never
happens ([`api/media_info.py:479-483`](../../src/atrium/api/media_info.py)). What the client
receives is the intrinsic shape from [`media/info.py:410-438`](../../src/atrium/media/info.py):
`Id`, `Container` inferred from the path, `Size` from the stored part — and `SupportsDirectPlay:
true`, because that is the model's default
([`media/info.py:176`](../../src/atrium/media/info.py)) and nothing overwrote it. No
`TranscodingUrl`, because `_annotate` is where one would have been written.

Read that against the contract's own hard requirements
`[client-contract: 2026-08-29, §1]`: `TranscodingUrl` must be present whenever direct is refused,
or *"`isTranscoding` is false **and** there is no HLS → dead end"*. This server produces exactly
the shape the client names, from the opposite direction — direct play is *advertised* rather than
refused, so the client takes it, and then the second round trip sets both switches false, is
skipped again for the same reason, and comes back with the same answer and still no URL.

**What the user sees:** a title that never starts, with no on-screen reason. The rejection lines of
the contract's §6 are all source-side gates; none of them fires here, because the client got an
answer it believes.

**When it happens:** whenever a file is in the library and nothing has opened it — a scan that ran
before 008's inspection existed, a file added since the last scan, a probe that failed. The comment
at the `continue` says *"a rescan is what fixes it"*, which is true and is not something a client
can ask for.

This is the same root cause as
[client-embeat-mobile.md §5.1](client-embeat-mobile.md#51-a-source-with-no-stored-inspection-loses-the-music-clients-whole-negotiation),
with a different symptom: the music client keeps playing and silently loses hi-res detection and
its cast-to-a-capped-renderer path, because it never asked a question it could be dead-ended on.
**One skipped branch, two clients, two failures that look nothing alike.**

### 4.2 v1 has no way to deliver a subtitle, and this client has one way to receive one

This is the gap with consequences, and the 2026-08-28 trace called it correctly. What has changed
is that it is now four facts about merged code rather than three about specifications:

- `GetSubtitle` is not among the 55, and [008 §2](../../specs/008-playback-negotiation-and-delivery/spec.md)
  excludes *"subtitle extraction, conversion and delivery as a separate route"*. `Stream.vtt` is
  not a row of [`surface.yaml`](surface.yaml), and L0 forbids serving a route that is not listed;
- **the master playlist announces one variant and nothing else.**
  [`media/hls.py:306-319`](../../src/atrium/media/hls.py) writes `#EXTM3U`, one
  `#EXT-X-STREAM-INF` and one URI. No `#EXT-X-MEDIA` tag is written anywhere in `src/` — the only
  match for that prefix is `#EXT-X-MEDIA-SEQUENCE`, which is a different tag in a different
  playlist;
- **`EnableSubtitlesInManifest` is not a field of the profile model.**
  [`api/media_info.py:134-152`](../../src/atrium/api/media_info.py) declares eleven properties of a
  `TranscodingProfile` and that is not one of them, so `extra="ignore"`
  ([`compat/model.py:67`](../../src/atrium/compat/model.py)) drops it on arrival. The client sends
  it `true` on every transcoding profile and this server never sees it;
- `IsTextSubtitleStream` is deliberately not emitted on any stream
  ([008 `spec.md:111`](../../specs/008-playback-negotiation-and-delivery/spec.md)), which removes
  the client's own input to *which* subtitle indexes it would put in the manifest query.

The client's side of it `[client-contract: 2026-08-29, §1, §3]`: for a server it has identified as
Jellyfin it expects `EXT-X-MEDIA:TYPE=SUBTITLES` in the master, requested through the
`DeviceProfile`, and it rewrites the master before AVPlayer sees it but **does not add anything the
server left out**. It has a whole-file WebVTT fallback and that path is wired for the other
flavour — so a Jellyfin-identifying server that serves HLS without subtitle tracks in the manifest
shows no subtitles at all, and the client will not compensate.

**The blast radius is smaller than it first looks, and the shape of it decides the fix:**

| Playback path | Subtitles |
|---|---|
| On-device remux, embedded tracks | Fine — the tracks are inside the file the client is reading byte for byte |
| Anything delivered over server HLS (remux or transcode) | None |
| External sidecar files (`.srt` beside the media), any path | None, and none reachable |

Which means the obvious fix is the wrong one: **adding `GetSubtitle` as a 56th endpoint would not
help this client**, because on the Jellyfin path it never asks. The only lever that reaches it is
the manifest, and the manifest costs the WebVTT extraction 008 excluded. Four pieces of work, in
dependency order: emit `IsTextSubtitleStream`; bind `EnableSubtitlesInManifest`; extract and serve
WebVTT; announce the tracks. The first two are cheap and buy nothing alone.

**One correction to this repository is still owed**, and it was owed on 2026-08-28 too: the
subtitle row of [behaviours §5](behaviours.md#5-accepted-gaps-in-v1) says subtitles are *"delivered
as files"*, and in v1 as implemented they are not delivered at all. That row is not edited here
because another change is in flight against that document; it belongs in **§5's gap table**, and
the wording it needs is the one in the table above.

### 4.3 The client's track override works for audio, and is dropped for subtitles

The 2026-08-28 trace recorded this as one gap — *"the track indices in a `TranscodingUrl`'s query
are unspecified"* — and asked for one acceptance criterion covering both. Implemented, it split in
half.

`AudioStreamIndex` **is** a delivery parameter: bound at
[`api/delivery.py:166`](../../src/atrium/api/delivery.py), read at
[`:212`](../../src/atrium/api/delivery.py), and honoured at
[`:625`](../../src/atrium/api/delivery.py), where `_audio_stream` picks the stream whose index the
client named and falls back to the first only when there is no match. That is the client's
workaround working exactly as it needs to.

`SubtitleStreamIndex` is not a delivery parameter at all. It appears on the `PlaybackInfo` body
([`api/media_info.py:194`](../../src/atrium/api/media_info.py)) and on the playstate reports, and
nowhere in [`api/delivery.py`](../../src/atrium/api/delivery.py). A delivery request carrying it is
silently dropped, which is the reference's documented treatment of an unrecognised query value
([behaviours §1.12](behaviours.md#112-an-unrecognised-query-value-is-ignored-not-rejected)) and is
therefore invisible.

**Today this costs nothing**, and the reason is §4.2: there is no subtitle to select on the HLS
path, so a parameter naming one has nothing to decide. **It stops costing nothing the moment §4.2
is closed**, and it will not announce itself when it does — the manifest work will look finished
and the "change the subtitle track" path will silently keep the default. Whoever does §4.2 owns
this line.

The contract's own claim about the reference — that it builds `TranscodingUrl` from the source's
*default* tracks and ignores the indexes posted in `PlaybackInfo`, which is why the client rewrites
them on the URL `[client-contract: 2026-08-29, §3]` — remains a third-party claim about Jellyfin
and is **a lead, not a measured behaviour**. `tools/probe_transcode_decision.py`, which [008
OQ-8](../../specs/008-playback-negotiation-and-delivery/spec.md) already names, is where it gets
settled. Atrium reads the body's `AudioStreamIndex` when the body names the source
([`api/media_info.py:312`](../../src/atrium/api/media_info.py)), so it may well not have the
behaviour the workaround exists for — which is safe either way, because the client overrides with
the same values.

### 4.4 `GET /Sessions` takes no `deviceId`, and the client sends one

The client verifies that a stream copy really is a copy by asking `GET /Sessions?deviceId=…` and
reading `TranscodingInfo.IsVideoDirect`, `.VideoCodec` and `.TranscodeReasons` off the session
whose `NowPlayingItem.Id` matches `[client-contract: 2026-08-29, §3]`.

[`api/sessions.py:287-293`](../../src/atrium/api/sessions.py) declares no `deviceId`, so the
parameter is dropped and the caller gets the unfiltered set it is allowed to see: its own sessions,
or every session if it is an administrator.

**This is a degradation, not a break, and the contract says why:** *"Returning nothing is safe: the
caller only acts on an explicit 'I am not copying'."* The client matches on `NowPlayingItem.Id`
anyway, so a wider list still finds the right row — on a single-user server it is the same row. It
gets worse exactly where the list gets long: an administrator on a busy server matching by item id
alone can find *another device's* session playing the same film, and read that session's
`TranscodingInfo` as its own.

Two things this is not. It is not a missing route — the row is in `surface.yaml`, tagged
`video-client`, implemented at 002. And it is not a delta to fix casually: whether the reference
filters on that parameter, and how it behaves when the caller is not an administrator, is
unmeasured here. A probe answers it in one request.

### 4.5 The fMP4 init segment restarts the encoder, which is the defect the client pre-warms to dodge

The contract names two Jellyfin behaviours under the heading **"do not reproduce them"**. This
server reproduces the first and avoids the second.

The first: requesting the `EXT-X-MAP` initialisation segment while the file is absent starts a
transcode from segment 0 unconditionally, and the positioned segment that follows kills it and
restarts with `-ss` — **two transcodes per resumed playback**. The client pre-warms the session to
dodge it `[client-contract: 2026-08-29, §3]`.

Atrium's restart rule is [`media/sessions.py:499-506`](../../src/atrium/media/sessions.py), whose
docstring is *"The reference's five branches, in its order"*, and whose first branch is
`index == INITIALISATION_INDEX` → restart, with no condition attached. The playlist puts that
segment in front of every fMP4 variant
([`media/hls.py:266-268`](../../src/atrium/media/hls.py)), so every resumed fMP4 playback pays for
it: the init request starts production from zero, and the positioned segment that follows exceeds
the gap allowance and restarts it.

**This is faithful reproduction, and it is the expensive kind.** [behaviours
§3.0](behaviours.md#30-how-the-decision-is-made) is the procedure for deciding it, and the input it
needs is not in this document: the contract's claim is third-party and cites Jellyfin's own source
at a line this repository has not read, so it is a **lead for a probe**. What is measurable from
here is the cost, and it is the client's own number — one wasted transcode start per resumed
playback, on the path the client takes for everything.

Worth noting for whoever picks it up: the client's pre-warm is a *workaround*, so a server that
did not have the defect would still see the pre-warm request. The fix is not "make the pre-warm
unnecessary"; it is "make the init segment not restart a running encoder that is already producing
the right thing".

### 4.6 Two spellings of `hls`, and only one of them selects HLS

The client's `DeviceProfile` declares every transcoding profile as HLS
`[client-contract: 2026-08-29, §1]`. Which spelling of the protocol string arrives on the wire is
not stated in the contract, and it decides the whole answer.

[`media/urls.py:202`](../../src/atrium/media/urls.py) and
[`:236`](../../src/atrium/media/urls.py) compare `decision.sub_protocol` to the constant `"hls"`
with `==`, and `sub_protocol` is the client's own
`TranscodingProfile.Protocol` carried through unchanged
([`media/decision.py:1001`](../../src/atrium/media/decision.py) ←
[`api/media_info.py:145`](../../src/atrium/api/media_info.py), a bare `str`). A profile spelled
`"Hls"` or `"HLS"` therefore fails both comparisons, and the `TranscodingUrl` comes back as a
*progressive* `/videos/{id}/stream.{container}` — a valid URL to a shape this client has designed
itself out of (§3.1), with no master and no variants.

`/universal` does not have this problem, and the contrast is the finding:
[`api/universal_audio.py:267`](../../src/atrium/api/universal_audio.py) normalises with
`.strip().lower()` before comparing, under a docstring that calls it *"measured, not lenience"*. So
two routes in this repository read the same value with two rules.

**Whether the reference is case-insensitive here is unmeasured**, and it is the question that
decides whether this is a gap or a robustness nicety: if it binds the property to an enum, .NET's
JSON enum binding matches names case-insensitively and a `"Hls"` profile works there and not here,
which is a delta in the one direction Principle I has no tolerance for. One probe posting a
`PlaybackInfo` body with `"Protocol": "Hls"` settles it.

### 4.7 UDP discovery is out of v1, and the client needs it

[001 §2](../../specs/001-server-identity-and-discovery/spec.md) puts it in as many words: *"UDP
autodiscovery on the local network — not in v1; clients take an address."* The client listens for a
broadcast datagram on port **7359**, answers the payload `who is JellyfinServer?` with a unicast
JSON carrying `Id`, `Name` and `Address`, and connects to that `Address` verbatim
`[client-contract: 2026-08-28, §1]`. It gives the network two seconds.

**What the user sees:** the "find my server" screen finds nothing, for ever. Typing the address
works. This is the one requirement in the contract that v1 excludes rather than merely leaves
unwritten, and it is excluded by a specification that is already **Implemented** — so closing it is
an amendment to 001 or a feature of its own.

Two things it is *not*. It is not an endpoint, so [`surface.yaml`](surface.yaml) and the L0 sweep
are untouched by the decision either way — Principle VI is about routes, and this is a datagram. And
it is not a place where a well-meant improvement is available: the contract is explicit that the
second probe, `who is EmbyServer?`, **is not ours to answer**, because a server that answers it is
claiming to be something it is not.

Unchanged since 2026-08-28, and not restated by the newer edition, whose scope is playback.

### 4.8 Chapter images are served, never generated

[006 §3.5](../../specs/006-images/spec.md) is explicit and reasoned: v1 serves chapter images that
exist on disk, does not extract them, and answers `404` per chapter for the ones that do not exist.
The client requests `/Items/{id}/Images/Chapter/{index}` for its scrubbing UI, independently of
Trickplay `[client-contract: 2026-08-28, §4]`.

**What the user sees:** a scrubbing bar with no thumbnails, on a library where Jellyfin would show
them, since Jellyfin extracts them on a background sweep.

**This one has moved since 2026-08-28**, and in the right direction: it is now recorded as
[behaviours §5.8](behaviours.md#58-a-chapter-image-can-never-be-served-in-v1), with a measurement
(1,311 of 1,354 reference entries carry a tag), a named closing mechanism and a tripwire test that
notices if any v1 code path ever starts writing chapter rows. The 2026-08-28 trace asked for this
gap to be recorded so that *"missing" is not later confused with "broken"*; the 2026-08-28 audit
recorded it. Nothing here is owed.

## 5. Two corrections this trace forced on our own documents

**Both were applied on 2026-08-28**, in the change that first carried this document. Neither was a
code change: both were places where a document in this repository said something that this client's
existence contradicts, while the server did the right thing already. Kept here because the argument
is what makes the consumer list trustworthy, not the edit.

### 5.1 `X-Emby-Authorization` is not the only spelling `AuthenticateByName` accepts

[api-surface-v1.md §3](api-surface-v1.md#3-authentication-users-and-sessions) said the route
*"requires the `X-Emby-Authorization` header"*, and repeated it below the table as **mandatory**.
The client sends that header **never, on any request, including sign-in** — the device-identifying
components travel in `Authorization: MediaBrowser Client="…", Device="…", DeviceId="…", Version="…"`
and nowhere else `[client-contract: 2026-08-29, §0]`, which the newer edition restates as the one
precondition on every request. A server built from that sentence refuses this client at the login
screen, and the refusal reads to a user like a wrong password.

Atrium was fine: [`compat/auth.py:146-152`](../../src/atrium/compat/auth.py) reads either header
name, and [behaviours §2.4](behaviours.md#24-there-are-five-authentication-mechanisms-and-one-of-them-wins)
already establishes that the reference reads both with the same grammar. What was wrong was the
prose, now corrected to *a client-identification header in either spelling, carrying a `DeviceId`*.

**One thing was left alone deliberately, and the music client has now made it interesting.** Two
error strings in [`compat/auth.py:137`](../../src/atrium/compat/auth.py) and
[`:141`](../../src/atrium/compat/auth.py) name only the Emby spelling — a `400` whose message points
at a header this client was never going to send. It is still there. It is *correct* for the music
client, which sends exactly that header and only on that route
([client-embeat-mobile.md §4](client-embeat-mobile.md#4-the-answer)), and misleading for this one.
Which makes it a wording change for whoever next opens 002, not a documentation edit, and now with
two clients' evidence rather than one's.

**And there is a measurement hiding in this.** Whether the *reference* accepts an
`Authorization`-only sign-in was never probed: `tools/probe_auth_mechanisms.py` set
`X-Emby-Authorization` and only that header on this route, every time it called it, so the question
was never put. **It was turned into a probe on 2026-08-28**: the probe now signs in with the
components in `Authorization` and the reference answers `200`
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`, so the corrected
paragraph rests on a measurement of this repository's own rather than on this client's word. It is
the one row of this document that has stopped being third-party evidence.

### 5.2 `GetAudioStream` is tagged with one consumer and has two

[`surface.yaml`](surface.yaml) recorded `consumers: [music-client]` for
`GET /Audio/{itemId}/stream`. The tvOS client builds that URL by hand for music playback
`[client-contract: 2026-08-28, §4]`, so the row now carries `video-client` as well, in both the
YAML and [§8 of the prose table](api-surface-v1.md#8-playback-negotiation-and-delivery).

The contract's own *rationale* — that `/Videos/…` answers `404` for a track — did not survive
measurement: the video route serves the track's bytes whole, under `Content-Type:
video/quicktime` `[probe: tools/probe_video_stream_for_a_track.py, Jellyfin 10.11.11,
2026-08-28]`. The client's choice stands anyway, on the correct content type rather than on a
refusal — and the consumer fact this section exists for is unchanged. The 2026-08-29 edition
repeats the `404` rationale `[client-contract: 2026-08-29, §4]`, so the correction has not reached
the client's author; it is theirs to make or not, and it changes nothing on either side.

Counting the same way in the other direction: 33 rows of `surface.yaml` carried `video-client`
before that change and the client touches **34**. The count still agrees on 2026-08-29.

## 6. Where these findings go

**They are not 008 defects, and they are not amendments to it.** 008 closes on its accepted scope;
every finding above was measured against code that does what its spec, plan and tasks say it does.
Six of the eight are gaps between *that scope* and *this client*, which is a different question and
belongs to a different feature — the next one after 010. §4.7 belongs to 001 or to a feature of its
own, and §4.8 is closed.

Grouped as a scope would take them:

| Finding | Shape of the work |
|---|---|
| [§4.1](#41-a-source-with-no-stored-inspection-is-the-clients-documented-dead-end) | Decide what an un-inspected source advertises. One branch, one acceptance criterion, and a behaviours entry it does not yet have |
| [§4.2](#42-v1-has-no-way-to-deliver-a-subtitle-and-this-client-has-one-way-to-receive-one) + [§4.3](#43-the-clients-track-override-works-for-audio-and-is-dropped-for-subtitles) | Subtitle delivery, end to end. The largest of them, and §4.3 is a line inside it rather than work of its own |
| [§4.4](#44-get-sessions-takes-no-deviceid-and-the-client-sends-one), [§4.6](#46-two-spellings-of-hls-and-only-one-of-them-selects-hls) | One probe each, then one parameter each. Both are cheap and neither is safe to guess |
| [§4.5](#45-the-fmp4-init-segment-restarts-the-encoder-which-is-the-defect-the-client-pre-warms-to-dodge) | A [behaviours §3.0](behaviours.md#30-how-the-decision-is-made) decision, taken on a probe, before any code |
| [§4.7](#47-udp-discovery-is-out-of-v1-and-the-client-needs-it) | An amendment to 001, or its own small feature. Not a route |

The two behaviours entries owed — §4.2's correction to the [§5](behaviours.md#5-accepted-gaps-in-v1)
subtitle row, and §4.1's missing entry — are recorded here rather than made, because a change is in
flight against that document.

## 7. What this document does not do

**It does not grow the surface.** No requirement here promotes an endpoint into v1: the thirty are
already in, the three unserved hand-built URLs are one client defect, one agreed exclusion and one
open decision, and the open one (§4.2) is not answered by adding a route.

**It does not become a second endpoint table.** [`surface.yaml`](surface.yaml) is the surface, and
`consumers: [video-client]` is where this client is already named; §3 above deliberately rolls up
rather than restating rows that would then drift.

**It is a floor, not a ceiling.** The contract says so of itself: absence from it means *not
measured*, never *not needed*. It describes the client at one commit on 2026-08-29, from its own
source — not from Jellyfin's documentation and not from a differential run. When the client
changes, this document is stale and nothing in CI will notice. It went stale once already, in a
day.

The mechanism that turns any of this into something measured is the same one the constitution
already names: the differential harness of
[010](../../specs/010-conformance-harness/spec.md), run request by request against both servers.
What this document contributes to that is a much smaller suite than 322 paths would suggest — **the
thirty-four rows above, and the eight behaviours of §4** — and the observation that the eight are
exactly the places where a server can pass every JSON comparison and still leave the user staring at
a video with no subtitles, a title that never starts, or a list of servers that stays empty.
