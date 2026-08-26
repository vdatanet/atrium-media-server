---
feature: 008-playback-negotiation-and-delivery
title: Playback negotiation and delivery
status: Draft
created: 2026-08-26
updated: 2026-08-26
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
- Device-profile evaluation and the direct-play / remux decision.
- `GET /Audio/{itemId}/stream[.{container}]`, `GET /Audio/{itemId}/universal`.
- `GET /Videos/{itemId}/stream[.{container}]`.
- `GET /Videos/{itemId}/master.m3u8`, `/main.m3u8`, `/hls1/{playlistId}/{segmentId}.{container}`.
- `DELETE /Videos/ActiveEncodings`.
- Byte-range delivery, and the session lifecycle behind a remux.

**Out of scope**

- **Transcoding.** Codec conversion, adaptive ladders, hardware acceleration, subtitle burn-in,
  throttling. v1 stops at remux. A client whose profile cannot be satisfied by direct play or remux
  is told so, and told honestly.
- Live streams, `/LiveStreams/Open`, `/LiveStreams/Close`.
- Subtitle extraction, conversion and delivery as a separate route.
- Trickplay.

> **Why remux and not transcode.** Remuxing copies the elementary streams into a different
> container: no decode, no encode, near-zero CPU, and an output whose size is computable. It covers
> the large majority of real playback — most incompatibilities are container mismatches, not codec
> ones. Transcoding is the single largest component of the reference and would multiply v1's scope;
> its absence is visible only to clients that genuinely cannot decode what the user's files
> contain.

## 3. Behaviour

### 3.1 Media sources

Each playable item has one or more **media sources**. A single-file movie has one; a multi-part
film (003 §3.3) has one per part.

A source is built by inspecting the actual file, never by trusting its extension, and carries:

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

> **Item-level `Container` is a demuxer list, not a container.** The reference reports ffprobe's
> `format_name` at item level — `"mov,mp4,m4a,3gp,3g2,mj2"` — while the resolved single container
> lives on the media source. `[prior-probe: Jellyfin 10.11.11, 2026-06-13]` Atrium reproduces both.
> A client reading the item-level field expects the list form, and "fixing" it would be a delta.

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

**`PlaySessionId` ties everything together** — this negotiation, the delivery request that follows,
and the three reports of 007. It is what makes `DELETE /Videos/ActiveEncodings` able to stop the
right thing.

**Errors**

| Condition | Status / body |
|---|---|
| Unknown or invisible item | `404` |
| Unauthenticated | `401` |
| User lacks `EnableMediaPlayback` | `403` |
| No source can be played by this profile | `200` with an `ErrorCode`, **not** a `4xx` |

That last row is the important one. The reference answers `200` with an error code in the body, and
clients branch on that code to show a useful message. A `4xx` would be read as a transport failure
and produce the wrong message.

**`GET /Items/{itemId}/PlaybackInfo`** is the profile-less variant, included by design. Without a
profile there is nothing to negotiate against, so it returns the sources with their intrinsic
capabilities and leaves the choice to the client.

### 3.3 The decision

Given a media source and a device profile, exactly one outcome:

| Outcome | Meaning | Cost |
|---|---|---|
| **Direct play** | Client fetches the original file | Nothing |
| **Direct stream (remux)** | Container rewritten, streams copied | Near zero |
| **Not playable** | Neither works and transcoding is out of scope | — |

**Evaluation order**, and it stops at the first success:

1. **Direct play** — the profile lists this container with these codecs, and every codec condition
   (profile, level, bit depth, channels, sample rate, bitrate, resolution) holds. Also requires the
   source bitrate to be within `MaxStreamingBitrate`.
2. **Remux** — a container the profile accepts exists into which these elementary streams can be
   copied unchanged. Codec conditions still have to hold: remuxing does not fix an unsupported
   codec, it only fixes the wrapper.
3. **Not playable** — say so, in the body, with the reason.

**Three rules that prevent the classic failures:**

- **A profile that says nothing means "anything".** An empty or absent `DeviceProfile` is not a
  profile that permits nothing; it is a client that has not told us, and the answer is direct play.
  Reading absence as prohibition is how a server ends up refusing to play anything to a simple
  client.
- **Never claim a capability that is not there.** `SupportsTranscoding` is `false` in v1, always.
  Advertising it and then failing at delivery time turns a clear "cannot play this" into a spinner
  that never resolves.
- **Never remove what the client said it can handle.** A stream copy alters the container, not the
  content. Where a profile declares support for a metadata format — a dynamic HDR variant, a
  coexistence range type — that declaration is honoured, and nothing is filtered out of the
  bitstream on the client's behalf. Stripping metadata a client explicitly asked for is how the
  reference breaks Dolby Vision playback on one whole client platform
  ([behaviours §3.4](../../docs/compatibility/behaviours.md#34-hdr10-metadata-stripped-from-clients-that-asked-for-it--class-b-no-compensation)),
  and it is a defect Atrium would have to write on purpose in order to have.

### 3.4 Delivery: the rules that apply to every route

**Byte ranges are mandatory.**

| Requirement | Behaviour |
|---|---|
| `Accept-Ranges: bytes` | On every delivery response |
| `Range: bytes=a-b` | `206` with a correct `Content-Range` |
| Multiple ranges | Single range honoured; multi-range may be answered as the full body |
| Unsatisfiable range | `416` with `Content-Range: bytes */total` |
| No `Range` | `200` with the full body |

**`Content-Length` is sent whenever the size is known** — always for direct play, and for remuxed
output whenever it can be computed or the output is produced to a seekable location first.

> **This is a deliberate divergence, and the most useful one in v1.** The reference's transcoding
> and remuxing routes answer chunked, with no size and no range support. That single gap is why
> every client that casts to a DLNA renderer has to run a local proxy: a renderer will not touch a
> stream whose size it does not know. Recorded in
> [behaviours §3.3](../../docs/compatibility/behaviours.md#33-transcoding-responses-carry-no-content-length-or-accept-ranges--class-c).
> A client cannot branch on a response being *more* correct, so Principle I is not violated.

**`static=true`** requests the original bytes with no processing. Honoured exactly: if the source
cannot be served untouched, the answer is an error, not a silent remux. A client asking for static
is usually downloading, and silently handing it a rewritten container corrupts what it saves.

**Authentication** is via any of the four mechanisms (002 §3.1), in practice `?api_key=`, because
these URLs go to media players that do not set headers.

### 3.5 Audio delivery

| Route | Behaviour |
|---|---|
| `GET /Audio/{itemId}/stream` | The source, with `static=true` for direct play or remuxed to the requested container |
| `GET /Audio/{itemId}/stream.{container}` | Same, container from the path |
| `GET /Audio/{itemId}/universal` | The server decides, from the client's stated constraints |

`/universal` accepts `container`, `audioCodec`, `maxAudioChannels`, `maxStreamingBitrate`,
`maxAudioSampleRate`, `maxAudioBitDepth`, `transcodingContainer`, `transcodingProtocol`,
`startTimeTicks`, `deviceId`, `userId`, `mediaSourceId` and `enableRedirection`. `[spec: GetUniversalAudioStream]`

**In v1 `/universal` can only answer with direct play or remux**, because that is all v1 does. When
the constraints cannot be met without re-encoding — a sample-rate ceiling below the source, a
bit-depth ceiling, a codec the client cannot decode — it answers with an error rather than serving
something that violates the constraint. A client that asked for at most 48 kHz and received 96 kHz
will fail at its own decoder, further from the cause.

**`enableRedirection`** may answer `302` to the direct-play URL rather than proxying, which is
strictly better for the client. It is honoured when the client asks for it and direct play was the
decision.

> ⚠️ **The reference's PCM/WAV routes are broken at 10.11.11**: `stream.wav` with any PCM codec
> answers `500`, and `/universal` with `Container=wav` answers `200` with a body that has no RIFF
> header. `[prior-probe: Jellyfin 10.11.11, 2026-08-03; upstream jellyfin/jellyfin#17537, merged to
> master, not in any 10.11.x]` Producing PCM requires re-encoding, so it is outside v1's scope. When
> transcoding lands, Atrium serves valid WAV with a real header and a real length — recorded in
> [behaviours §3.2](../../docs/compatibility/behaviours.md#32-pcmwav-output--one-bug-two-symptoms-two-classes) so the
> intent is not lost.

### 3.6 Video delivery

`GET /Videos/{itemId}/stream` and `/stream.{container}` behave as their audio equivalents.

**Remuxed video is delivered over HLS**, through three routes:

| Route | Returns |
|---|---|
| `/Videos/{itemId}/master.m3u8` | The master playlist: one variant, since v1 has no ladder |
| `/Videos/{itemId}/main.m3u8` | The media playlist: the segment list |
| `/Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}` | One segment |

Rules:

1. **Segments are deterministic.** The same source with the same parameters yields the same segment
   boundaries every time, so a segment can be re-requested after a network failure and be the same
   bytes. A server that re-derives boundaries per session cannot serve a retry.
2. **Segment duration is uniform** except for the last, and the playlist's declared duration matches
   what is delivered. Players build their seek bar from this.
3. **A segment requested out of order is served.** Players seek; they do not walk the playlist.
4. **The playlist is complete and marked ended** for a finite source. A live-style rolling playlist
   would make the file appear unseekable.

### 3.7 Session lifecycle

Every remux belongs to a **playback session**, keyed by `PlaySessionId`, with an owning user and
device.

| Event | Effect |
|---|---|
| Delivery request with a `PlaySessionId` | Session created or reused |
| `DELETE /Videos/ActiveEncodings` with the id | Session and its work stopped |
| Client stops requesting segments | Session reaped after an idle timeout |
| Client disconnects mid-response | Work stopped immediately |
| Server shutdown | All sessions stopped, scratch space cleared |

**`DELETE /Videos/ActiveEncodings` must actually stop something.** Clients call it when the user
stops. The reference is called by real clients for exactly this reason, and a server that answers
`204` while leaving work running accumulates processes until the machine dies. Answering `204`
without acting is worse than not implementing the route, because it looks correct.

**Scratch space is bounded and reclaimed**: by session on stop, by age on a sweep, and by total
size when a ceiling is reached. A remux that fills the disk takes the server down with it.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Probe results per file | `MediaSources`, `MediaStreams` in 005 and here | Until the file changes |
| Playback sessions | Whether a delivery request succeeds; `/Sessions` via 007 | Until stopped or reaped |
| Remux scratch output | Response latency only | Disposable |

## 5. Acceptance criteria

1. `PlaybackInfo` with an empty profile answers direct play, not "not playable".
2. `PlaybackInfo` with a profile accepting the source's container and codecs answers direct play.
3. A profile rejecting the container but accepting the codecs answers remux, with a
   `TranscodingUrl`.
4. A profile rejecting the codecs answers `200` with an `ErrorCode` — never a `4xx`.
5. `SupportsTranscoding` is `false` on every media source in v1.
6. Every delivery route answers `Accept-Ranges: bytes`.
7. `Range: bytes=100-199` answers `206` with a correct `Content-Range` and exactly 100 bytes.
8. An unsatisfiable range answers `416` with `Content-Range: bytes */total`.
9. Direct-play responses carry a `Content-Length` equal to the file size.
10. **Remuxed responses carry a `Content-Length` and honour `Range`** (the §3.4 divergence).
11. `static=true` on a source that cannot be served untouched answers an error, never a remux.
12. `/universal` with a constraint that cannot be met without re-encoding answers an error, not a
    violating stream.
13. `/universal` with `enableRedirection` and a direct-play decision answers `302`.
14. The same HLS source requested twice yields identical segment boundaries and identical segment
    bytes.
15. An HLS segment requested out of order is served correctly.
16. `DELETE /Videos/ActiveEncodings` terminates the work, verified by the absence of the process and
    the reclamation of its scratch space.
17. A client disconnecting mid-remux causes the work to stop within the timeout.
18. Item-level `Container` is the demuxer list; the media source's `Container` is the single
    resolved container.
19. Scratch space never exceeds its configured ceiling under repeated remux requests.
20. A `PlaySessionId` from `PlaybackInfo` is accepted by the delivery route and by
    `ActiveEncodings`.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `POST /Items/{itemId}/PlaybackInfo` | **L3** | Golden per profile class, plus differential. The negotiation is where clients diverge |
| `GET /Audio/{itemId}/stream` | **L3** | Golden headers, byte-identity against the source, plus differential |
| `GET /Audio/{itemId}/universal` | **L3** | Golden per constraint class, plus differential |
| `GET /Videos/{itemId}/stream` | **L3** | Golden headers and range matrix, plus differential |
| Container-suffixed forms | **L2** | Same assertions, path-derived container |
| HLS routes | **L2** | Playlist shape, segment determinism (AC-14), out-of-order fetch |
| `DELETE /Videos/ActiveEncodings` | **L2** | Process and scratch-space observation (AC-16) |

**The range matrix is table-driven** over: no range, prefix, suffix, mid-file, single byte, exactly
the whole file, one past the end, and a reversed range. These are where range implementations
actually break, and each is one line of test.

Media fixtures are **synthetic, generated at build time** — a few seconds of colour bars and a tone,
muxed into each container the tests need. No copyrighted media, and the repository stays small.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | The reference's `ErrorCode` vocabulary and which code it uses for each failure | AC-4's exact value | `tools/probe_playback_info.py` |
| OQ-2 | Does the reference set `SupportsDirectPlay` per source or per request? | Annotation semantics in §3.2 | `tools/probe_playback_info.py` |
| OQ-3 | The reference's HLS segment duration and boundary rule | Segment-level parity | `tools/probe_hls.py` |
| OQ-4 | Does the reference honour `enableRedirection`, and with which status? | AC-13 | `tools/probe_universal_audio.py` |
| OQ-5 | Which of the 19 `/universal` parameters clients actually send | Parameter coverage | Differential harness (010) |
| OQ-6 | Does `DELETE /Videos/ActiveEncodings` take the session id as a query parameter or apply to all of the caller's? | AC-16, AC-20 | `[spec: StopEncodingProcess]` plus a probe |

## 8. References

- [docs/compatibility/api-surface-v1.md §8](../../docs/compatibility/api-surface-v1.md#8-playback-negotiation-and-delivery)
- [docs/compatibility/behaviours.md §1.6, §3.2, §3.3](../../docs/compatibility/behaviours.md)
- [docs/glossary.md](../../docs/glossary.md) — direct play, direct stream, transcoding, PlaySessionId
- `[spec: GetPostedPlaybackInfo, GetPlaybackInfo, PlaybackInfoDto, PlaybackInfoResponse, MediaSourceInfo, MediaStream, DeviceProfile, GetAudioStream, GetUniversalAudioStream, GetVideoStream, GetMasterHlsVideoPlaylist, GetVariantHlsVideoPlaylist, GetHlsVideoSegment, StopEncodingProcess]`
