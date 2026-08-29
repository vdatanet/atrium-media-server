---
feature: 008-playback-negotiation-and-delivery
title: Playback negotiation and delivery
status: Accepted
created: 2026-08-26
updated: 2026-08-29
accepted: 2026-08-29
amended: 2026-08-29 at the spec review, which wrote the five probes the OQ table had been citing prospectively and ran all of them — all twelve open questions answered, and five claims did not survive: the policy story was fiction (no playback route consults `EnableMediaPlayback`, and a single denied permission moves nothing at negotiation — §3.2, §3.3, AC-31), `EnableTranscoding: false` in the request body is ignored (OQ-12), `static=true` on a mismatched container is not an error but the original bytes behind the wrong label (§3.5, AC-18), `enableRedirection` never redirects a local file (OQ-4, AC-21), and the reference's HLS segments already carry `Content-Length` — the §3.5 divergence shrank to the progressive routes. Plus one defect nobody was looking for: a sample-rate ceiling is answered from the Opus rate ladder and can be **exceeded** (§3.6, AC-19)
depends_on: [005, 007]
---

# 008 — Playback negotiation and delivery

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Decide how a given client should play a given file, tell it where to fetch the bytes, and then
serve those bytes correctly.

This is where a media server is judged. Every other feature can be slightly wrong and the user sees
a cosmetic defect; get this wrong and nothing plays.

**Client behaviour unlocked:** playback.

## 2. Scope

**In scope**

- `POST` and `GET /Items/{itemId}/PlaybackInfo`.
- Media inspection: what a file actually contains.
- Device-profile evaluation and the direct-play / remux / transcode decision.
- `GET /Audio/{itemId}/stream[.{container}]`, `GET /Audio/{itemId}/universal`.
- `GET /Videos/{itemId}/stream[.{container}]`.
- `GET /Videos/{itemId}/master.m3u8`, `/main.m3u8`, `/hls1/{playlistId}/{segmentId}.{container}`.
- `DELETE /Videos/ActiveEncodings`.
- **Software transcoding**: re-encoding video and/or audio when neither direct play nor remux
  satisfies the profile, within the profile's ceilings.
- Byte-range delivery, and the session lifecycle behind a remux or a transcode.

**Out of scope**

- **Hardware-accelerated encoding and decoding.** VAAPI, QSV, NVENC, VideoToolbox. Every frame in
  v1 goes through the CPU. This is a throughput decision, not a protocol one: the bytes a client
  receives are the same either way, which is why it can arrive later without any client noticing.
- **Subtitle burn-in.** Painting subtitles into frames needs a text-rendering stack and a second
  filter path. v1 delivers subtitle files; it does not draw them.
- Live streams, `/LiveStreams/Open`, `/LiveStreams/Close`.
- Subtitle extraction, conversion and delivery as a separate route.
- Trickplay.

> **Why the order is direct play, then remux, then transcode.** Direct play costs nothing. Remuxing
> copies the elementary streams into a different container: no decode, no encode, near-zero CPU, and
> an output whose size is computable — and it covers the large majority of real playback, because
> most incompatibilities are container mismatches, not codec ones. Transcoding costs a decode and an
> encode per frame, so it is *last*, reached only when the first two have failed. It is in v1
> because the alternative answer at that point is "cannot play this", and a file the user owns and
> cannot watch is the one failure that has no cosmetic version
> ([roadmap](../../docs/roadmap.md#in-scope)).

## 3. Behaviour

### 3.1 Media sources

Each playable item has one or more **media sources**. A single-file movie has one; a multi-part
film (003 §3.3) has one per part.

What a source says about the content — its codecs, streams, duration and dimensions — comes from
inspecting the actual file and never from its extension. The one field that is **not** a fact about
the content is `Container`, and the note below says what it is instead. A source carries:

| Group | Fields |
|---|---|
| Identity | `Id`, `Path`, `Protocol`, `Type`, `Name`, `ETag` |
| Container | `Container`, `Size`, `Bitrate`, `RunTimeTicks`, `Formats` |
| Streams | `MediaStreams`, `DefaultAudioStreamIndex`, `DefaultSubtitleStreamIndex` |
| Capability | `SupportsDirectPlay`, `SupportsDirectStream`, `SupportsTranscoding` |
| Delivery | `TranscodingUrl`, `TranscodingContainer`, `TranscodingSubProtocol` |

`[spec: MediaSourceInfo]`

**Streams** carry codec, profile, level, bit depth, frame rate, resolution, colour and HDR
information, channel layout, sample rate, language, and the default/forced/external flags.
`[spec: MediaStream]`

> **Item-level `Container` is sometimes a demuxer list.** The reference reports one normalised
> container string at item level, and whether it names one container depends on the format: a
> Matroska file answers `"mkv"`, and every member of the mp4 family answers the whole six-name
> list `"mov,mp4,m4a,3gp,3g2,mj2"` `[probe: tools/probe_media_container.py, Jellyfin 10.11.11,
> 2026-08-29]`. Atrium reproduces the string. A client reading the item-level field of an mp4
> expects the list form, and "fixing" it would be a delta.
>
> **The single container a source reports is not a property of the file.** It is derived from
> that string per response, and the two routes derive it differently. On `/Items` **no profile is
> involved**: the single form is the file's own extension where the list contains it — the same
> six-name list answers `mp4` for a `.mp4` and `m4a` for a `.m4a` — and the list's first member
> where it does not `[source: Emby.Server.Implementations/Dto/DtoService.cs:320-353 @ v10.11.11]`.
> In a negotiation it is the first member the `DeviceProfile` accepts, and a **profile-less**
> negotiation leaves the list alone: the same `.m4a` that answers `m4a` on a listing answers the
> full list on `GET /Items/{itemId}/PlaybackInfo` `[probe: tools/probe_media_container.py,
> Jellyfin 10.11.11, 2026-08-29]`, `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
> 2026-08-28]`. What inspecting a file can establish is the normalised string; each single form is
> the answer to a particular request and belongs to that response.

**Inspection is cached** and re-run only when the file changes. Probing an entire library on every
request is not viable, and probing on first playback makes the first play of every item slow.

### 3.2 `POST /Items/{itemId}/PlaybackInfo` — `GetPostedPlaybackInfo`

**Consumers:** video-client. The negotiation entry point.

**Request body:** `UserId`, `MaxStreamingBitrate`, `StartTimeTicks`, `AudioStreamIndex`,
`SubtitleStreamIndex`, `MaxAudioChannels`, `MediaSourceId`, `DeviceProfile`, and the
`EnableDirectPlay` / `EnableDirectStream` / `EnableTranscoding` / `AllowVideoStreamCopy` /
`AllowAudioStreamCopy` switches. `[spec: PlaybackInfoDto]`

**Response — 200**

```json
{
  "MediaSources": [ ],
  "PlaySessionId": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "ErrorCode": null
}
```

Each returned media source is **annotated with the decision** for this client: the support flags
set to what this profile can actually do, and `TranscodingUrl` populated when the answer is
"fetch it from here instead of directly".

**The annotation is per request, and the switches are not equals.** `EnableDirectPlay: false`
on a profile the source satisfies flips `SupportsDirectPlay` to `false` and produces a
`TranscodingUrl` — the flags describe *this* negotiation, not the source. `EnableTranscoding:
false` on a profile that forces a transcode changes **nothing**: the `TranscodingUrl` arrives
anyway. And `SupportsDirectStream` never answers independently — the reference disables its
direct-stream path outright ("direct-stream http streaming is currently broken"), so the flag
mirrors `SupportsDirectPlay` on every answer. `[probe: tools/probe_playback_info.py, Jellyfin
10.11.11, 2026-08-28; source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:251-268 @ v10.11.11]`
A client that branches on `SupportsDirectStream` is branching on direct play, and Atrium keeps
the mirror rather than resurrecting a distinction no reference answer draws.

**`PlaySessionId` ties everything together** — this negotiation, the delivery request that follows,
and the three reports of 007. It is what makes `DELETE /Videos/ActiveEncodings` able to stop the
right thing.

**Errors**

| Condition | Status / body |
|---|---|
| Unknown or invisible item | `404` |
| Unauthenticated | `401` |
| User lacks `EnableMediaPlayback` | `200`, **the negotiation unchanged** — see below |
| No source can be played by this profile | `200`, **not** a `4xx` — and **no** `ErrorCode`: the refusal is the source's own capability flags |

The last two rows are the important ones, and neither survived in its first wording.

The refusal row said an `ErrorCode` arrives, and none does. A profile that can play nothing gets
`200` with `SupportsDirectPlay`, `SupportsDirectStream` and `SupportsTranscoding` all `false`, no
`TranscodingUrl`, and no `ErrorCode` — measured in four request shapes, transcoding allowed and
forbidden `[probe: tools/probe_playback_refusal.py, Jellyfin 10.11.11, 2026-08-28]`. A `4xx`
would still be read as a transport failure; what a client actually branches on is the flags.

The `EnableMediaPlayback` row said `403`, and **no playback route consults the permission at
all**. A user whose policy denies playback negotiates exactly as anyone else — same flags, same
`TranscodingUrl`, no error `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
2026-08-28]`. The flag's only consumers at 10.11.11 are the item DTO's `PlayAccess` property and
the remote-control `Play` command `[source: MediaBrowser.Controller/Entities/BaseItem.cs:1057,
Emby.Server.Implementations/Session/SessionManager.cs:1321 @ v10.11.11]`. A `403` here would
have been an invented refusal — a delta a policy-restricted client would observe.

**`ErrorCode` has one real value.** The schema's vocabulary is `NotAllowed`,
`NoCompatibleStream` and `RateLimitExceeded` `[spec: PlaybackInfoResponse]`, but the reference
has exactly one assignment site: `NoCompatibleStream`, set when the **media source list is
empty** `[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:123 @ v10.11.11]`. The other two are
dead members no response can carry. Atrium emits `NoCompatibleStream` in the same one place and
nothing else anywhere.

**`GET /Items/{itemId}/PlaybackInfo`** is the profile-less variant, included by design. Without a
profile there is nothing to negotiate against, so it returns the sources with their intrinsic
capabilities — all three flags `true`, no `TranscodingUrl` — and still issues a `PlaySessionId`
`[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28]`.

### 3.3 The decision

Given a media source and a device profile, exactly one outcome:

| Outcome | Meaning | Cost |
|---|---|---|
| **Direct play** | Client fetches the original file | Nothing |
| **Direct stream (remux)** | Container rewritten, streams copied | Near zero |
| **Transcode** | At least one stream re-encoded to something the profile accepts | A decode and an encode per frame |
| **Not playable** | No output this server can produce satisfies the profile | — |

**Evaluation order**, and it stops at the first success:

1. **Direct play** — the profile lists this container with these codecs, and every codec condition
   (profile, level, bit depth, channels, sample rate, bitrate, resolution) holds. Also requires the
   source bitrate to be within `MaxStreamingBitrate`.
2. **Remux** — a container the profile accepts exists into which these elementary streams can be
   copied unchanged. Codec conditions still have to hold: remuxing does not fix an unsupported
   codec, it only fixes the wrapper.
3. **Transcode** — some output this server can produce satisfies the profile: a container it
   accepts, holding codecs it accepts, within every ceiling it declared. Only the streams that fail
   a condition are re-encoded (§3.4).
4. **Not playable** — the profile accepts no container, or no codec, that v1 can produce. The
   answer is the capability flags all `false` (§3.2) — not an error, and not an `ErrorCode`.

**On the wire, remux and transcode are one shape.** A remux answer is a `TranscodingUrl` like
any transcode's, with `TranscodeReasons=ContainerNotSupported` in its query and the elementary
streams copied at delivery; `SupportsDirectStream` stays `false` because it mirrors direct play
(§3.2). What separates the two outcomes is what the session does per frame, and a client sees it
only in the reasons list `[probe: tools/probe_transcode_decision.py, Jellyfin 10.11.11,
2026-08-28]`.

**"Not playable" is now a much smaller set**, and it is worth being precise about what is left in
it: a profile listing only containers or codecs this server cannot produce, a source whose streams
cannot be decoded at all, a source that is not readable, and a user whose policy forbids the step
that would have answered.

**The user's policy barely gates the ladder, and the spec's first draft said otherwise.** The
measured rule at 10.11.11: a **single** denied permission changes nothing at negotiation. For a
video item, `SupportsTranscoding` goes `false` only when `EnableVideoPlaybackTranscoding`,
`EnableAudioPlaybackTranscoding` **and** `EnablePlaybackRemuxing` are all denied at once; for an
audio item, `EnableAudioPlaybackTranscoding` alone decides `[probe:
tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28; source:
Jellyfin.Api/Helpers/MediaInfoHelper.cs:278-293 @ v10.11.11]`. Even the all-denied answer is
flags, never an `ErrorCode`. At **delivery** the enforcement is stranger still: a user denied
`EnableVideoPlaybackTranscoding` has the video stream **force-copied "regardless of whether it
will be compatible or not"** `[source:
MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:7142 @ v10.11.11]` — an output that can
violate the profile it was negotiated for. Atrium replicates the negotiation rule exactly (the
all-three gate, flags not errors); at delivery it honours the same gate by refusing the
re-encode step, but it never ships an output that violates the negotiated profile — a
force-copied incompatible stream fails at the client's decoder, and no client can *depend* on
receiving a broken stream. Of the request body's switches, `EnableDirectPlay` is honoured and
`EnableTranscoding` is ignored (§3.2); Atrium reproduces both.

**Three rules that prevent the classic failures:**

- **A profile that says nothing means "anything".** An empty or absent `DeviceProfile` is not a
  profile that permits nothing; it is a client that has not told us, and the answer is direct play.
  Reading absence as prohibition is how a server ends up refusing to play anything to a simple
  client.
- **Never claim a capability that is not there.** `SupportsTranscoding` is `true` on a source
  exactly when this server can produce, for *this* profile, a stream the profile accepts — and
  `false` otherwise, including when the profile's ceilings leave nothing producible. It is a claim
  about this negotiation, not a boast about the server. Advertising it and then failing at delivery
  time turns a clear "cannot play this" into a spinner that never resolves, which is strictly worse
  than the honest refusal v1 used to give.
- **Never remove what the client said it can handle.** A stream copy alters the container, not the
  content. Where a profile declares support for a metadata format — a dynamic HDR variant, a
  coexistence range type — that declaration is honoured, and nothing is filtered out of the
  bitstream on the client's behalf. Stripping metadata a client explicitly asked for is how the
  reference breaks Dolby Vision playback on one whole client platform
  ([behaviours §3.4](../../docs/compatibility/behaviours.md#34-hdr10-metadata-stripped-from-clients-that-asked-for-it--class-b-no-compensation)),
  and it is a defect Atrium would have to write on purpose in order to have.

### 3.4 Transcoding

Reached only when direct play and remux have both failed. Everything in this section is in service
of one idea: **do the least re-encoding that makes this source playable for this profile.**

**Only the streams that fail a condition are re-encoded.**

| Stream | v1 behaviour |
|---|---|
| Accepted by the profile, every condition holding | Copied, never re-encoded |
| Rejected: codec, profile, level or bit depth | Re-encoded to a codec the profile accepts |
| Rejected: resolution, frame rate or bitrate ceiling | Re-encoded down to the ceiling |
| Audio rejected: channel count or sample rate | Downmixed or resampled to the ceiling |

A file whose video the profile accepts and whose audio it does not is the common case — a modern
video track with a surround audio track a browser cannot decode — and it costs an audio encode, not
a video one. A server that re-encodes both because one was wrong burns two orders of magnitude more
CPU than the job needs.

**Ceilings are limits, not targets.** A profile permitting 1080p and 8 Mbps applied to a 720p
3 Mbps source produces 720p at approximately the source bitrate. Nothing is ever upscaled,
up-sampled or given more bits than it arrived with: that spends CPU to make the output larger and
no better.

**The output satisfies the profile it was built for.** This is the whole obligation of the feature.
An output that violates a condition the client declared is worse than "cannot play this", because
the refusal happens at the client's decoder, far from the cause, and looks like a broken file rather
than an unsupported one.

**Work starts where the client asked to start.** A request carrying a start position begins
production at that position; it does not produce from the beginning and discard. Measured: a
segment at ~90% of a 2h22 film arrives in 0.9 seconds, and the session's progress jumps to the
seek point — the transcoder is restarted at the requested position, and the same holds for a
segment requested far ahead of the produced window `[probe: tools/probe_transcode_session.py,
Jellyfin 10.11.11, 2026-08-28]`.

**Throttling is an operator setting, off as shipped.** The reference's `EnableThrottling`
defaults to `false` — an idle client leaves the encoder producing the whole file — and when an
operator enables it, production pauses once it leads the last downloaded position by
`max(ThrottleDelaySeconds, 60)` seconds, 180 by default, resuming when the gap closes `[source:
MediaBrowser.Model/Configuration/EncodingOptions.cs:23-24,
MediaBrowser.Controller/MediaEncoding/TranscodingThrottler.cs:118-171 @ v10.11.11]`. Measured on
a throttled server: production stalls ~180 seconds ahead of the one fetched segment and stays
there `[probe: tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-28]`. Atrium ships
the same two knobs with the same defaults and the same pause-at-gap behaviour — the draft's
"always throttled" would have been an observable difference in how much of a file exists after
an abandoned session, and the operator who wants the bound can turn it on in both servers.

**A transcode is bounded work with an owner**: it belongs to a playback session (§3.8), it stops
when the session stops, when the client disconnects, and when the server shuts down, and its output
lives in scratch space that dies with the session (§3.8).

**Determinism is per session.** For a remux, the byte-identity rule holds globally: the same source
and parameters give the same segments. For a re-encode the guarantee is narrower and is the one
players actually need — **within a session, a segment that has been produced is served identically
every time it is requested again**, so a retry after a network failure is the same bytes. Across
sessions, re-encoded bytes may differ; no client compares them.

**What the client is told about it.** `SupportsTranscoding`, `TranscodingUrl`,
`TranscodingContainer` and `TranscodingSubProtocol` on the negotiated source describe this answer
and nothing else: they are per source *and* per profile, decided by the negotiation that returned
them (§3.3).

> **Hardware acceleration is absent, and no client can tell.** The output of a CPU encode and a
> hardware encode are both just a stream that satisfies the profile. What differs is how many
> concurrent sessions a given machine survives — an operational property, not a protocol one. This
> is why it can arrive in a later version without touching this specification's observable
> behaviour, and it is the reason the exclusion is safe in a project whose first principle is that
> a client cannot tell.

### 3.5 Delivery: the rules that apply to every route

**Byte ranges are mandatory.**

| Requirement | Behaviour |
|---|---|
| `Accept-Ranges: bytes` | On every delivery response whose body has a known size |
| `Range: bytes=a-b` | `206` with a correct `Content-Range` and exactly the bytes asked for |
| Suffix range `bytes=-n` | `206` with the last `n` bytes |
| Multiple ranges | The full body as `200` — the reference does not split |
| Reversed range `bytes=b-a` | The full body as `200`, not a `416` |
| Unsatisfiable range | `416` with `Content-Range: bytes */total` and `Content-Length: 0` |
| No `Range` | `200` with the full body |

The whole table is measured, not designed: the matrix runs against a direct-play
`/Videos/{itemId}/stream?static=true` — `bytes=100-199` answers `206` with
`Content-Range: bytes 100-199/{size}` and a `Content-Length` of exactly `100`; the suffix form
answers the last bytes; the multi-range, reversed and no-`Range` shapes all answer `200` with
the full body; one byte past the end is the `416` with `Content-Length: 0`.
`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-28]`

**`Content-Length` is sent whenever the size is known** — always for direct play, for remuxed
output whenever it can be computed or the output is produced to a seekable location first, and for
every HLS segment, which is finished before it is served.

**For HLS this is parity, not a divergence.** The measurement narrowed the draft's claim: the
reference's finished segments already answer with `Content-Length`, `Accept-Ranges: bytes` and
byte-identical retries, and its playlists carry a length too `[probe: tools/probe_hls.py,
Jellyfin 10.11.11, 2026-08-28]`. What stays chunked and sizeless on the reference is the
**progressive** family — `/stream` remuxes and re-encodes, `/universal` over http — which
forces `Accept-Ranges: none` and no length even where the size is knowable, a remux to a
seekable location included ([behaviours §3.3](../../docs/compatibility/behaviours.md#33-progressive-transcoding-responses-carry-no-content-length-or-accept-ranges--class-c)).

**The one delivery in v1 that cannot carry a size** is a progressive (non-HLS) re-encode, where the
final length is not known until the last frame is produced. That response is chunked, exactly as the
reference's is. The rule is *send the size when it is known*, never *invent one*: a wrong
`Content-Length` truncates playback, which is a worse failure than the missing header this project
went out of its way to fix.

> **The deliberate divergence is now exactly one route family.** Where a progressive remux's
> size is knowable, Atrium sends it and honours `Range`; the reference answers chunked with
> `Accept-Ranges: none` `[source:
> Jellyfin.Api/Helpers/FileStreamResponseHelpers.cs:123-135 @ v10.11.11]`. That gap is why every
> client that casts to a DLNA renderer runs a local sizing proxy: a renderer will not touch a
> stream whose size it does not know. A client cannot branch on a response being *more* correct,
> so Principle I is not violated — and the HLS half of the draft's divergence dissolved into
> parity when it was measured.

**`static=true`** requests the original bytes with no processing, and the reference honours the
*bytes* absolutely — including past the URL. `stream.mp3?static=true` on a FLAC source answers
`200` with the untouched FLAC bytes behind a `Content-Type: audio/mpeg` label, and
`stream.mkv?static=true` on an mp4 film serves the mp4 bytes as `video/x-matroska`: the path's
container decides the label and nothing else, and no error, remux or re-encode ever happens on a
static request `[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-28]`
(behaviours §2.20). The draft said a mismatch would be an
error; it is not, and inventing one would break the client that names a wrong container while
downloading — it still receives, correctly, the original file. Atrium replicates: static always
serves the source bytes, whatever the path says.

**Authentication** is via any of the four mechanisms (002 §3.1), in practice `?api_key=`, because
these URLs go to media players that do not set headers.

### 3.6 Audio delivery

| Route | Behaviour |
|---|---|
| `GET /Audio/{itemId}/stream` | The source, with `static=true` for direct play, remuxed to the requested container, or re-encoded when the requested container or codec cannot hold the source's streams |
| `GET /Audio/{itemId}/stream.{container}` | Same, container from the path |
| `GET /Audio/{itemId}/universal` | The server decides, from the client's stated constraints |

`/universal` accepts `container`, `audioCodec`, `maxAudioChannels`, `maxStreamingBitrate`,
`maxAudioSampleRate`, `maxAudioBitDepth`, `transcodingContainer`, `transcodingProtocol`,
`startTimeTicks`, `deviceId`, `userId`, `mediaSourceId` and `enableRedirection`. `[spec: GetUniversalAudioStream]`

**`/universal` re-encodes to meet a constraint the source violates** — a sample-rate ceiling, a
bit-depth ceiling, a channel ceiling, a codec the client cannot decode — **and the reference
then misses the target it was aiming at.** At 10.11.11 the output sample rate is not the ceiling
but the nearest step of the ladder Opus needs — `≤8000, ≤12000, ≤16000, ≤24000, else 48000` —
applied to **every** codec: a stated ceiling of 22 050 Hz is answered at 24 000 Hz, above what
the client declared `[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11, 2026-08-28]`.
The restructure that scopes the ladder to Opus is merged upstream and in no 10.11.x — the same
family as behaviours §3.2's PCM fix. **Atrium honours the ceiling exactly**: a client that asked
for at most 22 050 Hz receives at most 22 050 Hz, because an output above a declared ceiling
fails at the client's decoder, far from the cause (recorded as the divergence in
[behaviours §3.7](../../docs/compatibility/behaviours.md#37-a-sample-rate-ceiling-is-answered-from-the-opus-ladder--class-b-diverged)).

**A codec-less transcode request is the reference's other hole here.** `/universal` with a
`transcodingProtocol` of `http` and no `audioCodec` builds a transcoding profile with no codec
in it, the encoder invocation dies at once, and the route answers `200` with a
`Content-Length: 0` empty body `[probe: tools/probe_universal_audio.py, Jellyfin 10.11.11,
2026-08-28]`. Nothing can be built on an empty body behind a `200`; Atrium answers the request
with a stream, choosing the transcoding container's own codec when the client names none
([behaviours §3.8](../../docs/compatibility/behaviours.md#38-universal-without-audiocodec-answers-an-empty-200--class-a-diverged)).

**`enableRedirection` never redirects a local file, and the draft said otherwise.** The `302`
branch requires a source that is **remote** over HTTP, direct-playable, and a user with
`EnableRemoteMedia` — all at once `[source:
Jellyfin.Api/Controllers/UniversalAudioController.cs:175 @ v10.11.11]`; a library file is
protocol `File`, so a direct-play answer for anything a v1 library holds is proxied bytes with a
`200`, redirection enabled or not — measured `[probe: tools/probe_universal_audio.py, Jellyfin
10.11.11, 2026-08-28]`. Atrium accepts the parameter and, having no remote sources in v1, never
answers `302` — exactly the reachable subset of the reference's rule.

> ⚠️ **The reference's PCM/WAV routes are broken at 10.11.11**: `stream.wav` with any PCM codec
> answers `500`, and `/universal` with `Container=wav` answers `200` with a body that has no RIFF
> header. `[prior-probe: Jellyfin 10.11.11, 2026-08-03; upstream jellyfin/jellyfin#17537, merged to
> master, not in any 10.11.x]` Producing PCM requires re-encoding, which v1 now does, so **this path
> is served in v1**: Atrium answers with valid WAV — a real RIFF header, a real `Content-Length`,
> `Range` support — on both routes. Both divergences, and the risk carried by the second, are
> reasoned in
> [behaviours §3.2](../../docs/compatibility/behaviours.md#32-pcmwav-output--one-bug-two-symptoms-two-classes).

### 3.7 Video delivery

`GET /Videos/{itemId}/stream` and `/stream.{container}` behave as their audio equivalents.

**Remuxed and re-encoded video are both delivered over HLS**, through the same three routes. Which
of the two a client is receiving is a property of the negotiation, not of the URL — and a client
that only follows the playlist cannot tell, which is the point:

| Route | Returns |
|---|---|
| `/Videos/{itemId}/master.m3u8` | The master playlist: **exactly one variant** for this negotiation |
| `/Videos/{itemId}/main.m3u8` | The media playlist: the segment list |
| `/Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}` | One segment |

**The measured shape** `[probe: tools/probe_hls.py, tools/probe_transcode_decision.py, Jellyfin
10.11.11, 2026-08-28]`:

- The master playlist advertises **one** `#EXT-X-STREAM-INF` variant — never a ladder — whose
  `CODECS`, `RESOLUTION`, `FRAME-RATE` and `BANDWIDTH` describe the negotiated output, and whose
  URI is a relative `main.m3u8` carrying the entire query string forward. (The reference adds an
  `#EXT-X-IMAGE-STREAM-INF` trickplay entry when it has trickplay images; v1 has none, and a
  master playlist without one is a server with nothing to advertise there, not a different
  shape.)
- The media playlist is `#EXT-X-PLAYLIST-TYPE:VOD`, `#EXT-X-VERSION:3`,
  `#EXT-X-MEDIA-SEQUENCE:0`, ends with `#EXT-X-ENDLIST`, and arrives **complete in a fraction of
  a second, before any segment exists** — 2 843 segments in 0.18 s. The boundaries are predicted
  from the source, not derived from produced output; this is what makes rule 1 below possible at
  all.
- Every `#EXTINF` line ends `, nodesc`, and every segment URI repeats the full query plus two
  per-segment parameters: `runtimeTicks` (the segment's cumulative start offset) and
  `actualSegmentLengthTicks` (its exact duration).

Rules:

1. **Segments are deterministic.** The same source with the same parameters yields the same segment
   boundaries every time, so a segment can be re-requested after a network failure and be the same
   bytes. A server that re-derives boundaries per session cannot serve a retry. For re-encoded
   output the byte-identity half of this holds **within the session** (§3.4); the boundaries hold
   always.
2. **Segment duration is uniform** except for the last, and the playlist's declared duration matches
   what is delivered. Players build their seek bar from this. The number itself depends on the
   path: the same film measured 3.004 s per segment re-encoded (the forced-keyframe cadence at
   23.976 fps) and 6.0 s per segment stream-copied (the source's own keyframes), each uniform
   within its session.
3. **A segment requested out of order is served.** Players seek; they do not walk the playlist.
4. **The playlist is complete and marked ended** for a finite source. A live-style rolling playlist
   would make the file appear unseekable.

### 3.8 Session lifecycle

Every remux and every transcode belongs to a **playback session**, keyed by `PlaySessionId`, with
an owning user and device. Nothing that costs CPU or disk exists outside one: that is what makes it
stoppable, countable and reapable.

| Event | Effect |
|---|---|
| Delivery request with a `PlaySessionId` | Session created or reused |
| `DELETE /Videos/ActiveEncodings` with the id | Session and its work stopped |
| Client stops requesting segments | Production pauses at the throttle margin, session reaped after an idle timeout |
| Client disconnects mid-response | Work stopped immediately |
| Server shutdown | All sessions stopped, scratch space cleared |

**`DELETE /Videos/ActiveEncodings` must actually stop something.** Clients call it when the user
stops. The reference is called by real clients for exactly this reason, and a server that answers
`204` while leaving work running accumulates processes until the machine dies. Answering `204`
without acting is worse than not implementing the route, because it looks correct.

**Its parameters are both mandatory, and it measurably acts.** `deviceId` and `playSessionId`
are each required — omitting either answers a validation `400` naming the missing field — and
the well-formed call answers `204` with the session's `TranscodingInfo` gone from `/Sessions`
immediately after `[spec: StopEncodingProcess; probe: tools/probe_transcode_session.py, Jellyfin
10.11.11, 2026-08-28]`. It stops one session, the named one, not everything the device owns.

**Scratch space is reclaimed the way the reference reclaims it**: by session — on the stop
route, and when a session goes unpinged past its kill timeout, the partial output is deleted
with the job `[source:
MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:145-275 @ v10.11.11]` — and by age
behind the operator's produced-segment knobs (`EnableSegmentDeletion`, off as shipped;
`SegmentKeepSeconds`, 720) `[source:
MediaBrowser.Model/Configuration/EncodingOptions.cs:25-26 @ v10.11.11]`. Atrium ships the same
knobs with the same defaults. A remux that fills the disk takes the server down with it, and a
transcode fills it faster — which is why the session-scoped reclamation is not optional even
though the age-based one is.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Probe results per file | `MediaSources`, `MediaStreams` in 005 and here | Until the file changes |
| Playback sessions | Whether a delivery request succeeds; `/Sessions` via 007 | Until stopped or reaped |
| Remux scratch output | Response latency only | Disposable |
| Transcode scratch output | Response latency, and whether a re-requested segment is the same bytes | Disposable, bounded, session-scoped |

## 5. Acceptance criteria

1. `PlaybackInfo` with an empty profile answers direct play, not "not playable".
2. `PlaybackInfo` with a profile accepting the source's container and codecs answers direct play.
3. A profile rejecting the container but accepting the codecs answers remux, with a
   `TranscodingUrl`.
4. A profile rejecting the codecs, but accepting at least one codec and container this server can
   produce, answers **transcode**, with a `TranscodingUrl` — not an error.
5. A profile accepting no container or codec this server can produce answers `200` with every
   capability flag `false`, no `TranscodingUrl`, and **no `ErrorCode`** — never a `4xx`. The one
   `ErrorCode` that exists, `NoCompatibleStream`, is emitted exactly when the media source list
   is empty (§3.2).
6. `SupportsTranscoding` is `true` exactly on the sources whose negotiated answer is a stream this
   server can produce, and `false` on the ones refused with every flag down.
7. A source whose video the profile accepts and whose audio it does not is delivered with its
   **video stream copied**: same codec, same resolution, same frame count as the source.
8. Delivered output satisfies **every** condition of the profile it was negotiated against —
   asserted table-driven over the profile classes, on the delivered bytes, not on the decision.
9. Nothing is upscaled or up-sampled: a 720p source under a 1080p ceiling is delivered at 720p.
10. A request carrying a start position begins production at that position: time to first byte for a
    seek near the end of a long source is of the same order as one near the beginning.
11. Every delivery route whose body has a known size answers `Accept-Ranges: bytes`.
12. `Range: bytes=100-199` answers `206` with a correct `Content-Range` and exactly 100 bytes.
13. An unsatisfiable range answers `416` with `Content-Range: bytes */total`.
14. Direct-play responses carry a `Content-Length` equal to the file size.
15. **Remuxed responses carry a `Content-Length` and honour `Range`** (the §3.5 divergence).
16. Every HLS segment carries a `Content-Length`, whether it was remuxed or re-encoded.
17. A progressive re-encode whose final size is unknown answers chunked, and never a
    `Content-Length` that is not the true length.
18. `static=true` always serves the untouched original bytes — never an error, a remux or a
    re-encode. A container-suffixed static URL that does not match the source changes only the
    `Content-Type` label, byte-for-byte identical body (§3.5).
19. `/universal` with a constraint that requires re-encoding — a sample-rate, bit-depth or channel
    ceiling below the source — answers a stream that **meets** the constraint: the target is the
    stated ceiling, not the reference's Opus-ladder step above it (§3.6, behaviours §3.7).
20. `/universal` with `Container=wav` answers a body with a valid RIFF header and a real length
    ([behaviours §3.2](../../docs/compatibility/behaviours.md#32-pcmwav-output--one-bug-two-symptoms-two-classes)).
21. `/universal` accepts `enableRedirection` and **never answers `302` for a local source**: the
    direct-play answer is the proxied bytes with a `200` (§3.6). The redirect branch exists only
    for remote HTTP sources, which v1 does not have.
22. The same **remuxed** HLS source requested twice yields identical segment boundaries and
    identical segment bytes.
23. Within one session, a **re-encoded** segment requested twice yields identical bytes.
24. An HLS segment requested out of order is served correctly.
25. `DELETE /Videos/ActiveEncodings` terminates the work, verified by the absence of the process and
    the reclamation of its scratch space.
26. A client disconnecting mid-remux or mid-transcode causes the work to stop within the timeout.
27. With throttling enabled in configuration, a client that fetches the first segments and then
    stops does not cause the whole source to be produced: production pauses at the configured
    gap. With it disabled — the shipped default, matching the reference — production continues
    to the end (§3.4).
28. Item-level `Container` is the demuxer list; the media source's `Container` is the single
    resolved container.
29. Scratch space is reclaimed with its session: after a stop, a kill-timeout or a shutdown,
    nothing of the session's output remains; with segment deletion enabled, produced segments
    older than the configured window are removed while the session still runs (§3.8).
30. A `PlaySessionId` from `PlaybackInfo` is accepted by the delivery route and by
    `ActiveEncodings`.
31. Policy shapes the negotiation exactly as measured (§3.3): a user denied **every**
    playback-processing permission negotiates `SupportsTranscoding: false` and no
    `TranscodingUrl`; a user denied only one of them negotiates exactly as a permitted user; and
    no policy shape produces an `ErrorCode` or a `4xx`. At delivery, a denied user's re-encode
    step is refused rather than force-copied into an output that violates the profile.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `POST /Items/{itemId}/PlaybackInfo` | **L3** | Golden per profile class — including the classes that force a transcode — plus differential. The negotiation is where clients diverge |
| `GET /Audio/{itemId}/stream` | **L3** | Golden headers, byte-identity against the source, plus differential |
| `GET /Audio/{itemId}/universal` | **L3** | Golden per constraint class, plus differential |
| `GET /Videos/{itemId}/stream` | **L3** | Golden headers and range matrix, plus differential |
| Container-suffixed forms | **L2** | Same assertions, path-derived container |
| HLS routes | **L2** | Playlist shape, segment determinism (AC-22, AC-23), out-of-order fetch |
| Transcoded output | **L2** | The delivered bytes are inspected and asserted against the profile they were negotiated for (AC-8, AC-9). **Not** byte-compared with the reference |
| Throttling and scratch reclamation | **L2** | Produced output observed against what was fetched (AC-27, AC-29) |
| `DELETE /Videos/ActiveEncodings` | **L2** | Process and scratch-space observation (AC-25) |

**Transcoded bytes are not compared with the reference, and never will be.** Two encoders given the
same instruction produce different bytes, and the difference is not a defect. What is asserted is
the property a client depends on: *the output satisfies the profile*. Levels above that would be
asserting that Atrium ships the reference's encoder, which is not a compatibility claim.

**The range matrix is table-driven** over: no range, prefix, suffix, mid-file, single byte, exactly
the whole file, one past the end, and a reversed range. These are where range implementations
actually break, and each is one line of test.

Media fixtures are **synthetic, generated at build time** — a few seconds of colour bars and a tone,
muxed into each container the tests need. No copyrighted media, and the repository stays small. The
transcode tests need two more of them: a source whose codecs no common profile accepts, to force
step 3 of the decision, and a source with an accepted video track beside a rejected audio track, for
AC-7. **They stay seconds long**, because every transcode test now spends real CPU, and a suite that
takes minutes is a suite that stops being run.

## 7. Open questions

None open. OQ-5 moved to the 010 differential, where it always belonged; the other eleven were
answered at the spec review on 2026-08-28, by the five probes the table had been citing
prospectively — every one of which now exists and runs.

### Resolved

| # | Question | Answer | Resolved by |
|---|---|---|---|
| OQ-1 | The `ErrorCode` vocabulary and which code fires for each failure | **Three enum members, one assignment site.** `NoCompatibleStream` when the source list is empty; `NotAllowed` and `RateLimitExceeded` are dead vocabulary. A profile refusal is flags, not a code — AC-5 rewritten | `tools/probe_playback_info.py` and source, 2026-08-28 |
| OQ-2 | `SupportsDirectPlay` per source or per request? | **Per request** — `EnableDirectPlay: false` flips the flag on a source the profile satisfies. And `SupportsDirectStream` mirrors `SupportsDirectPlay` always: the reference's direct-stream path is disabled outright | `tools/probe_playback_info.py`, 2026-08-28 |
| OQ-3 | The HLS segment duration and boundary rule | **Predicted up front, uniform except the last, `, nodesc`, per-segment `runtimeTicks` and `actualSegmentLengthTicks`.** 3.004 s re-encoded at 23.976 fps, 6.0 s stream-copied, same film — the complete VOD playlist (2 843 segments) arrives in 0.18 s, before any segment exists | `tools/probe_hls.py`, 2026-08-28 |
| OQ-4 | Does `enableRedirection` answer `302`? | **Never for a local file.** The redirect requires a remote HTTP source and `EnableRemoteMedia`; a library file is proxied `200` bytes — AC-21 rewritten | `tools/probe_universal_audio.py` and source, 2026-08-28 |
| OQ-5 | Which `/universal` parameters clients actually send | Moved to the 010 differential — a question about clients, not about the reference | — |
| OQ-6 | `DELETE /Videos/ActiveEncodings`: session id or all of the caller's? | **One session, both parameters mandatory.** Omitting `playSessionId` is a validation `400` naming it; the well-formed call is `204` and the session's `TranscodingInfo` is gone | `tools/probe_transcode_session.py`, 2026-08-28 |
| OQ-7 | One variant or several in the master playlist? | **Exactly one** `#EXT-X-STREAM-INF` (plus a trickplay `#EXT-X-IMAGE-STREAM-INF` when the reference has trickplay images; v1 has none) | `tools/probe_transcode_decision.py`, 2026-08-28 |
| OQ-8 | What goes into `TranscodingContainer`, `TranscodingSubProtocol` and the `TranscodingUrl` | **`ts` / `hls`, and a relative `/videos/{dashed-id}/master.m3u8?&…`** with PascalCase parameters: `DeviceId`, `MediaSourceId`, `VideoCodec`, `AudioCodec`, stream indexes and bitrates, `SegmentContainer`, `PlaySessionId`, `ApiKey` (the caller's token), `Tag` (the source `ETag`), source-codec condition triplets (`hevc-level`, `hevc-profile`, `hevc-videobitdepth`) and `TranscodeReasons` | `tools/probe_transcode_decision.py`, 2026-08-28 |
| OQ-9 | Copy the compatible stream, or re-encode both? | **Copy.** The accepted video codec survives byte-inspected in the segment (`IsVideoDirect: true`), only the rejected audio is re-encoded — §3.4's table is parity | `tools/probe_transcode_decision.py`, 2026-08-28 |
| OQ-10 | The throttle margin, and what happens when fetching stops | **An operator setting, off as shipped.** `EnableThrottling` defaults `false`; enabled, production pauses `max(ThrottleDelaySeconds, 60)` s (default 180) ahead of the last download — measured stalled at the gap. §3.4 and AC-27 rewritten around the configuration | `tools/probe_transcode_session.py` and source, 2026-08-28 |
| OQ-11 | Start at the requested position, or produce from zero? | **Restart at the position.** A segment at ~90% of a 2 h 22 film arrives in 0.9 s and the session's progress jumps to the seek point | `tools/probe_transcode_session.py`, 2026-08-28 |
| OQ-12 | What does `EnableTranscoding: false` in the body answer? | **It is ignored.** The `TranscodingUrl` arrives anyway — there is no error path to name, and inventing one would be a delta | `tools/probe_playback_info.py`, 2026-08-28 |

**And two things nobody asked** fell out of the same session: the reference's `/universal`
answers a sample-rate ceiling from the Opus ladder — above the ceiling when it falls between
steps — and answers a codec-less http transcode request with an empty `200` (§3.6, behaviours
§3.7 and §3.8).

## 8. References

- [docs/compatibility/api-surface-v1.md §8](../../docs/compatibility/api-surface-v1.md#8-playback-negotiation-and-delivery)
- [docs/compatibility/behaviours.md §1.6, §3.2, §3.3](../../docs/compatibility/behaviours.md)
- [docs/glossary.md](../../docs/glossary.md) — direct play, direct stream, transcoding, PlaySessionId
- `[spec: GetPostedPlaybackInfo, GetPlaybackInfo, PlaybackInfoDto, PlaybackInfoResponse, MediaSourceInfo, MediaStream, DeviceProfile, GetAudioStream, GetUniversalAudioStream, GetVideoStream, GetMasterHlsVideoPlaylist, GetVariantHlsVideoPlaylist, GetHlsVideoSegment, StopEncodingProcess]`
