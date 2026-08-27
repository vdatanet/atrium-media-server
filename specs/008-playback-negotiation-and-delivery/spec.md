---
feature: 008-playback-negotiation-and-delivery
title: Playback negotiation and delivery
status: Draft
created: 2026-08-26
updated: 2026-08-27
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
4. **Not playable** — the profile accepts no container, or no codec, that v1 can produce. Say so, in
   the body, with the reason.

**"Not playable" is now a much smaller set**, and it is worth being precise about what is left in
it: a profile listing only containers or codecs this server cannot produce, a source whose streams
cannot be decoded at all, a source that is not readable, and a user whose policy forbids the step
that would have answered.

**The user's policy gates the ladder.** `EnableVideoPlaybackTranscoding`,
`EnableAudioPlaybackTranscoding` and `EnablePlaybackRemuxing` remove their step from the evaluation
for that user (002 §3.5); the request body's `EnableDirectPlay` / `EnableDirectStream` /
`EnableTranscoding` switches remove it for that request. A step that is removed is not silently
substituted: the decision falls through to the next one, and to "not playable" if none is left.

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
production at that position; it does not produce from the beginning and discard. Seeking to the last
minute of a long film must not cost the whole film.

**Production is throttled, not unbounded.** Work runs ahead of the player by a bounded margin and
then waits. Without a ceiling, one client seeking repeatedly through a film has the server encoding
several copies of it at once, and the machine is lost to a user who is not even watching.

**A transcode is bounded work with an owner**: it belongs to a playback session (§3.8), it stops
when the session stops, when the client disconnects, and when the server shuts down, and its output
lives in scratch space with a ceiling.

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
| `Accept-Ranges: bytes` | On every delivery response |
| `Range: bytes=a-b` | `206` with a correct `Content-Range` |
| Multiple ranges | Single range honoured; multi-range may be answered as the full body |
| Unsatisfiable range | `416` with `Content-Range: bytes */total` |
| No `Range` | `200` with the full body |

**`Content-Length` is sent whenever the size is known** — always for direct play, for remuxed
output whenever it can be computed or the output is produced to a seekable location first, and for
every HLS segment, which is finished before it is served.

**The one delivery in v1 that cannot carry a size** is a progressive (non-HLS) re-encode, where the
final length is not known until the last frame is produced. That response is chunked, exactly as the
reference's is. The rule is *send the size when it is known*, never *invent one*: a wrong
`Content-Length` truncates playback, which is a worse failure than the missing header this project
went out of its way to fix.

> **This is a deliberate divergence, and the most useful one in v1.** The reference's transcoding
> and remuxing routes answer chunked, with no size and no range support, *including where the size
> is perfectly knowable* — a finished HLS segment, a remux to a seekable location. That single gap
> is why
> every client that casts to a DLNA renderer has to run a local proxy: a renderer will not touch a
> stream whose size it does not know. Recorded in
> [behaviours §3.3](../../docs/compatibility/behaviours.md#33-transcoding-responses-carry-no-content-length-or-accept-ranges--class-c).
> A client cannot branch on a response being *more* correct, so Principle I is not violated.

**`static=true`** requests the original bytes with no processing. Honoured exactly: if the source
cannot be served untouched, the answer is an error, not a silent remux. A client asking for static
is usually downloading, and silently handing it a rewritten container corrupts what it saves.

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

**`/universal` meets the constraints it is given, re-encoding where it must.** A sample-rate
ceiling below the source, a bit-depth ceiling, a channel ceiling, a codec the client cannot decode:
each is a reason to convert, and the answer is a stream that satisfies every stated constraint. The
rule that does not bend is the one that was already here — **it never serves something that violates
a constraint the client stated.** A client that asked for at most 48 kHz and received 96 kHz fails
at its own decoder, further from the cause. Only a constraint set that v1 cannot produce at all
answers with an error.

**`enableRedirection`** may answer `302` to the direct-play URL rather than proxying, which is
strictly better for the client. It is honoured when the client asks for it and direct play was the
decision.

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
| `/Videos/{itemId}/master.m3u8` | The master playlist: the variant this negotiation decided on |
| `/Videos/{itemId}/main.m3u8` | The media playlist: the segment list |
| `/Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}` | One segment |

Rules:

1. **Segments are deterministic.** The same source with the same parameters yields the same segment
   boundaries every time, so a segment can be re-requested after a network failure and be the same
   bytes. A server that re-derives boundaries per session cannot serve a retry. For re-encoded
   output the byte-identity half of this holds **within the session** (§3.4); the boundaries hold
   always.
2. **Segment duration is uniform** except for the last, and the playlist's declared duration matches
   what is delivered. Players build their seek bar from this.
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

**Scratch space is bounded and reclaimed**: by session on stop, by age on a sweep, and by total
size when a ceiling is reached. A remux that fills the disk takes the server down with it, and a
transcode fills it faster — the output of a re-encode is written wholesale, and a user who seeks
around a long film produces far more of it than they watch.

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
5. A profile accepting no container or codec this server can produce answers `200` with an
   `ErrorCode` — never a `4xx`.
6. `SupportsTranscoding` is `true` exactly on the sources whose negotiated answer is a stream this
   server can produce, and `false` on the ones that answered with an `ErrorCode`.
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
18. `static=true` on a source that cannot be served untouched answers an error, never a silent remux
    or re-encode.
19. `/universal` with a constraint that requires re-encoding — a sample-rate, bit-depth or channel
    ceiling below the source — answers a stream that **meets** the constraint.
20. `/universal` with `Container=wav` answers a body with a valid RIFF header and a real length
    ([behaviours §3.2](../../docs/compatibility/behaviours.md#32-pcmwav-output--one-bug-two-symptoms-two-classes)).
21. `/universal` with `enableRedirection` and a direct-play decision answers `302`.
22. The same **remuxed** HLS source requested twice yields identical segment boundaries and
    identical segment bytes.
23. Within one session, a **re-encoded** segment requested twice yields identical bytes.
24. An HLS segment requested out of order is served correctly.
25. `DELETE /Videos/ActiveEncodings` terminates the work, verified by the absence of the process and
    the reclamation of its scratch space.
26. A client disconnecting mid-remux or mid-transcode causes the work to stop within the timeout.
27. Production is throttled: a client that fetches the first segments and then stops does not cause
    the whole source to be produced.
28. Item-level `Container` is the demuxer list; the media source's `Container` is the single
    resolved container.
29. Scratch space never exceeds its configured ceiling under repeated remux and transcode requests.
30. A `PlaySessionId` from `PlaybackInfo` is accepted by the delivery route and by
    `ActiveEncodings`.
31. A user whose policy denies transcoding never receives one: the same request that answers
    transcode for a permitted user answers `200` with an `ErrorCode` for this one.

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
| Throttling and scratch ceiling | **L2** | Produced output observed against what was fetched (AC-27, AC-29) |
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

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | The reference's `ErrorCode` vocabulary and which code it uses for each failure | AC-5's exact value | `tools/probe_playback_info.py` |
| OQ-2 | Does the reference set `SupportsDirectPlay` per source or per request? | Annotation semantics in §3.2 | `tools/probe_playback_info.py` |
| OQ-3 | The reference's HLS segment duration and boundary rule | Segment-level parity | `tools/probe_hls.py` |
| OQ-4 | Does the reference honour `enableRedirection`, and with which status? | AC-21 | `tools/probe_universal_audio.py` |
| OQ-5 | Which of the 19 `/universal` parameters clients actually send | Parameter coverage | Differential harness (010) |
| OQ-6 | Does `DELETE /Videos/ActiveEncodings` take the session id as a query parameter or apply to all of the caller's? | AC-25, AC-30 | `[spec: StopEncodingProcess]` plus a probe |
| OQ-7 | Does the reference's master playlist advertise one variant or several when the answer is a transcode? | §3.7's master-playlist row | `tools/probe_transcode_decision.py` |
| OQ-8 | Which container and codecs the reference picks for a given profile, and what it puts in `TranscodingContainer`, `TranscodingSubProtocol` and the `TranscodingUrl` parameters | Whether a client that parses that URL sees what it expects | `tools/probe_transcode_decision.py` |
| OQ-9 | Does the reference copy the compatible stream and re-encode only the other, or re-encode both? | §3.4's stream table, AC-7 | `tools/probe_transcode_decision.py` |
| OQ-10 | The reference's throttle margin and what it does when a client stops fetching | AC-27's threshold | `tools/probe_transcode_session.py` |
| OQ-11 | Does the reference start work at the requested position, or produce from zero and discard? | AC-10's threshold | `tools/probe_transcode_session.py` |
| OQ-12 | What the reference answers when transcoding is refused by `EnableTranscoding: false` in the request body | An error path §3.2 does not yet name | `tools/probe_playback_info.py` |

**OQ-7 to OQ-12 arrived with the scope change on 2026-08-27** and none of them blocks the *decision*
this specification makes — they block the *parity* of the values it reports. That is the honest
statement of where this feature stands: what Atrium does is specified, what the reference puts in
four fields while doing it is measured before the plan, not guessed after it (Principle II).

## 8. References

- [docs/compatibility/api-surface-v1.md §8](../../docs/compatibility/api-surface-v1.md#8-playback-negotiation-and-delivery)
- [docs/compatibility/behaviours.md §1.6, §3.2, §3.3](../../docs/compatibility/behaviours.md)
- [docs/glossary.md](../../docs/glossary.md) — direct play, direct stream, transcoding, PlaySessionId
- `[spec: GetPostedPlaybackInfo, GetPlaybackInfo, PlaybackInfoDto, PlaybackInfoResponse, MediaSourceInfo, MediaStream, DeviceProfile, GetAudioStream, GetUniversalAudioStream, GetVideoStream, GetMasterHlsVideoPlaylist, GetVariantHlsVideoPlaylist, GetHlsVideoSegment, StopEncodingProcess]`
