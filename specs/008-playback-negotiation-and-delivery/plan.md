---
feature: 008-playback-negotiation-and-delivery
title: Playback negotiation and delivery — implementation plan
status: Accepted
created: 2026-08-29
updated: 2026-08-29
accepted: 2026-08-29
amended: 2026-08-29 by T3 — §6.1 records the `ETag` derivation and §6.8's first debt is discharged: MD5 over the modification time in .NET ticks, hashed as UTF-16 little-endian and rendered in .NET's GUID byte order, proven by recovering three files' tick counts from the tags the reference sent; and 2026-08-29 by T1 — §8 gains the bit-exactness the cached fixture directory rests on, measured where it fails; and 2026-08-29 by T4 — §5's contract gains `supports_transcoding` and `is_video` and loses "or empty" from rule 1, §6.2 records the containment rules, the reasons' order and subject, the comparison precision and the HDR rule's unreachability, and §6.3 records that the URL carries the profile's ceilings rather than the plan's; and 2026-08-29 by T6 — §3 gains `media/labels.py`, `api/delivery.py` and a `MediaFileRepository` that takes no user, §6.5 records that the four `stream` routes declare no authentication dependency at all and why the response is built header by header, §6.8's delivery-route error shape is discharged for those four (the third shape, not the problem details §7 implied), and §7 gains the container pattern's `400` and the missing-file case
spec_status_required: Accepted
spec_status_actual: Accepted
---

# 008 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour, and the spec was
> re-measured before this plan started: every open question it carried is answered by a probe
> that now exists in `tools/`. Where this plan states a reference behaviour, the citation lives
> in the spec section it names.

## 1. Approach

Five decisions carry the feature; everything else is plumbing between them.

**The decision is a pure function, and it is the only place the ladder lives.** Profile
evaluation — direct play, remux, transcode, not-playable, with the per-stream copy/encode split
and every measured quirk (the all-three policy gate, the honoured `EnableDirectPlay` and the
ignored `EnableTranscoding`, `SupportsDirectStream` mirroring direct play) — goes in
`media/decision.py` as functions from *(measured source, device profile, request switches, user
policy)* to a `Decision` value. No I/O, no clock, no process. The spec's sharpest corrections
(§3.2's per-request annotation, §3.3's policy paragraph) become table-driven unit tests against
pure code, which is the same shape that made 007's six-branch resolution testable without a
server. The delivery routes *consume* a `Decision`; none of them re-derives any part of it.

**Inspection happens at scan time and lands in the database, streams as rows.** The spec pins
the two bad extremes (§3.1: not per request, not on first playback), so the probe step joins
003's scan pipeline behind its existing change signal: a new or changed file is inspected once,
and the result — resolved container, the demuxer list, bitrate, and one row per elementary
stream — is stored beside the item. 005's `MediaSources`/`MediaStreams` emission, the item-level
`Container`, and the nine media-derived `NowPlayingItem` properties 007 left named all read from
these rows; first playback reads what the scan already wrote.

**HLS is predicted, not observed.** The measured reference answers a complete, `ENDLIST`-marked
VOD playlist in 0.18 s, before any segment exists (spec §3.7) — boundaries are computed from the
source, uniform cadence for a re-encode, keyframe-derived for a copy. `media/hls.py` does the
same arithmetic as pure functions over the stored probe rows, so the playlist routes never touch
a process, and rule 1 (deterministic boundaries) is a property of the arithmetic rather than a
discipline imposed on ffmpeg.

**One supervised encoder per session, restarted at seeks.** A playback session owns at most one
ffmpeg process producing segments sequentially into its own scratch directory. A segment request
inside the produced window is served from disk (which gives within-session byte identity for
free); a request outside it kills the process and restarts at that segment's boundary — the
measured reference behaviour (OQ-11), and the reason seeking costs seconds, not the film. The
manager owns every kill path the spec's §3.8 table names: the stop route, the unpinged-session
timeout, client disconnect, shutdown. `architecture.md` §4's "external processes are supervised"
was written for exactly this module.

**Range handling is one function in `compat/`, measured shapes only.** The §3.5 table is now
fully measured (prefix, mid, single byte, the whole file named, open-ended, overshooting, suffix,
multi→full-body, reversed→full-body, every unreadable shape→full-body, `416` with
`Content-Length: 0`), and `architecture.md` §1 already assigns `Range` to `compat/`. One
`negotiate_range` used by every delivery route; the golden range matrix tests it table-driven
once, not per route. **The measured table and RFC 9110 disagree**, which is the reason it is one
function rather than a per-route reading: the reference answers a reversed or malformed `Range`
with the whole body where the RFC invites a `416`, and a route that reached for the standard
instead of the table would refuse requests the reference serves.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–007 | [007 plan §2](../007-user-data-and-playstate/plan.md#2-inherited-decisions) |
| `ffprobe`/`ffmpeg` as external processes, supervised, with an owner and a kill path | [ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md), [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions) |
| `media/` owns inspection, profiles, decisions, delivery; never policy about who may play | [architecture §1](../../docs/architecture.md#1-shape-of-the-system) |
| Ticks are the internal unit; conversion at ingestion only | architecture §4 |
| `api/` is one module per Jellyfin controller | architecture §1, 007 plan §3 |
| `Range` parsing/answering belongs to `compat/` | architecture §1, module table |
| Problem-details and controller-refusal error shapes | behaviours §1.11, `compat/errors.py` |
| Parameter canonicalisation, `api_key` seeding, the ignored-parameter recorder | [005 plan §6.12](../005-item-query-api/plan.md#612-parameter-plumbing), `compat/query_params.py` |
| Request models ignore unknown properties; bodies name the reference's parameter | `compat/model.py`, 007 T8 |
| `NOT_IN_NOW_PLAYING` keeps `MediaSources` out of session entries | [007 tasks](../007-user-data-and-playstate/tasks.md#what-this-feature-owes-the-next-ones), `api/sessions.py` |
| Delivery never writes playstate — reports do; `record_stop` stays the one resolution point | 007 tasks (what 007 owes), `api/playstate.py` |
| Repositories return domain objects; no ORM row crosses the boundary | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |
| Never copy Jellyfin's code — command lines included | Principle IV |

**Deviations:** none.

## 3. Modules

```
src/atrium/
├── media/
│   ├── probe.py         ffprobe invocation and parse into a domain MediaInspection;
│   │                    no database — the scan hands rows to the repository
│   ├── info.py          MediaSourceInfo / MediaStream wire assembly from stored rows,
│   │                    including the profile-less demuxer-list form (spec §3.1)
│   ├── decision.py      pure: (source, profile, switches, policy) → Decision
│   ├── urls.py          the TranscodingUrl anatomy — OQ-8's measured parameter list
│   ├── hls.py           pure: segment-boundary prediction and playlist rendering
│   ├── labels.py        pure: container → Content-Type, the measured table (T6)
│   ├── ffmpeg.py        command construction, our own design per stream plan
│   └── sessions.py      TranscodeManager: process supervision, scratch, ping/kill
│                        timers, restart-at-seek, the configurable throttle
├── compat/
│   └── ranges.py        negotiate_range: the §3.5 table, one place
├── api/
│   ├── media_info.py    MediaInfoController: POST and GET /Items/{itemId}/PlaybackInfo
│   ├── delivery.py      what the four stream routes share: the lookup, the range answer,
│   │                    the label and the measured header set (T6)
│   ├── audio.py         AudioController: /Audio/{itemId}/stream[.{container}]
│   ├── universal_audio.py  UniversalAudioController: /Audio/{itemId}/universal
│   ├── videos.py        VideosController: /Videos/{itemId}/stream[.{container}]
│   ├── dynamic_hls.py   DynamicHlsController: master.m3u8, main.m3u8, hls1 segments
│   └── hls_segment.py   HlsSegmentController: DELETE /Videos/ActiveEncodings
└── db/
    ├── models.py        MediaProbe and MediaStreamRow
    ├── repositories.py  grows MediaProbeRepository
    └── migrations/versions/0006_media_probes.py
```

`db/repositories.py` also grows a `MediaFileRepository`, whose one query is an item id to the file
behind it. Separate from `ItemQueryRepository` because that one takes a **user** and applies 005's
visibility predicate, and a delivery route has neither: it may be called with no token at all
(§6.5), so there is nobody to apply a predicate for.

Grows, not new: `library/scan.py` gains the inspection step behind the change signal;
`api/item_dto.py` gains `MediaSources`, `MediaStreams` and item-level `Container` emission (the
005 emitters, fed at last); `api/sessions.py` gains `TranscodingInfo` read from the
`TranscodeManager` (the measured session shape the probes themselves relied on); `config/` gains
the encoding options (§6.7).

The controller split again mirrors the reference on purpose — six controllers own these routes
there, `DELETE /Videos/ActiveEncodings` in `HlsSegmentController` and not where anyone would
guess, and keeping the mapping mechanical is what lets the surface audit stay mechanical.

## 4. Data model

Migration `0006_media_probes`, reversible (drop both tables).

**`media_probes`** — one row per inspected media file (one per part of a multi-part film):

| Column | Meaning |
|---|---|
| `library_id`, `relative_path` (PK) | The file inspected, named the way `item_sources` names it |
| `size`, `mtime_ns` | 003's change signal, denormalised here so staleness is one comparison |
| `container` | The reference's normalised container string — a single name for some formats, a demuxer list for others |
| `format_names` | What the demuxer answered, before that normalisation |
| `runtime_ticks`, `bitrate` | Whole-file facts |
| `video_keyframes` | Keyframe timestamps in ticks, serialised — §6.4's copy-cadence input |
| `probed_at` | Diagnostic, and read back rather than write-only |

**The key is the library and the relative path, not a path** — corrected at T2. An absolute path
would be the one key in this schema that a remount invalidates: `library/identity.py` derives
every identifier from the path *relative* to its root, deliberately, so that moving a root changes
nothing — and probe rows keyed absolutely would be orphaned by a move that leaves every item,
favourite, image and resume position intact. This shape is also the shape of the table these rows
join to.

**There is one container column, and it is not "the resolved single container"** — also corrected
at T2, and it is the finding that decided the table. A single container is not a property of a
file: the reference derives it per response, from the file's *extension* on a listing and from the
*device profile* in a negotiation, so the same `.m4a` answers `m4a` on `/Items` and the whole
`mov,mp4,m4a,3gp,3g2,mj2` on a profile-less `PlaybackInfo` `[probe:
tools/probe_media_container.py, Jellyfin 10.11.11, 2026-08-29]`. What is storable is the
normalisation the reference performs once, at inspection: `matroska,webm` becomes `mkv` where the
streams disqualify WebM, and the mp4 family survives whole `[source:
MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:124,270-315 @ v10.11.11]`.
`format_names` keeps what the demuxer said before that, so re-deriving the normalisation never
costs a rescan. §6.1 says who owns each derivation.

**`media_streams`** — one row per elementary stream:

`library_id`, `relative_path` (FK, cascade), `stream_index`, `type`, `codec`, `codec_tag`,
`profile`, `level`, `bit_depth`, `width`, `height`, `aspect_ratio`, `framerate`,
`average_framerate`, `channels`, `channel_layout`, `sample_rate`, `language`, `title`,
`is_default`, `is_forced`, `is_hearing_impaired`, `is_external`, `bitrate`, `video_range`,
`video_range_type`, `color_range`, `color_transfer`, `color_primaries`, `color_space`,
`pixel_format`, `ref_frames`, `is_interlaced`, `is_anamorphic`.

The column set is the wire `MediaStream`'s needs plus the condition inputs the decision reads
(profile, level, bit depth, resolution, channels, sample rate, and the HDR pair §3.3's
metadata rule needs). **Three of them were missing from this list until T2 wrote the migration**,
each of them beside one the list already had: `average_framerate`, because the reference carries
two frame rates and they differ on variable-frame-rate content; `color_range`, beside the three
other colour fields; and `is_hearing_impaired`, beside the two other disposition flags. Finding
them in T3 would have cost a second migration.

`video_keyframes` exists to serve a *query pattern* — predicting copy segment boundaries without
re-running ffprobe per playlist — and is the column a later reader will otherwise try to normalise
away; it is one ordered list per video file and lives with the probe, not in a table of its own.

Almost every stream column is nullable, and that is measured rather than cautious: a Matroska
stream reports no bitrate, no language tag and no codec tag; a lossless audio stream states its
bit depth in one field and zero in the other; and ffprobe 9.0.1 reports no `refs` at all, so
`ref_frames` is empty wherever that build inspects. Nothing may require it, and no test may assert
it either way — the suite runs against two different builds.

No index beyond the primary keys: every read is by `(library_id, relative_path)` for one item's
files.

**No table for sessions.** A transcode session is a process, scratch on disk and an in-memory
record — it dies with the server on restart exactly as the reference's does, and `/Sessions`
already reads live registries (007 §6.4's rule: live over stored).

## 5. Contracts

**`media/decision.py`** — pure, and the only place the semantics live:

```python
class Outcome(Enum):           # exactly the spec §3.3 table
    DIRECT_PLAY = ...
    REMUX = ...                # container change, every stream copied
    TRANSCODE = ...            # at least one stream re-encoded
    NONE = ...                 # flags all false; never an error

class StreamAction(Enum):
    COPY = ...
    ENCODE = ...

@dataclass(frozen=True)
class StreamPlan:              # one per output stream
    source_index: int
    action: StreamAction
    codec: str                 # target; source codec when COPY
    # ceilings already clamped to min(profile, source): §3.4 "limits, not targets"
    width: int | None
    height: int | None
    bitrate: int | None
    channels: int | None
    sample_rate: int | None

@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reasons: tuple[str, ...]   # TranscodeReason names, ascending flag value
    container: str | None      # negotiated output container ("ts")
    sub_protocol: str | None   # "hls" | "http"
    video: StreamPlan | None
    audio: StreamPlan | None
    supports_transcoding: bool # what this profile leaves producible, not what was answered

def decide(source, profile, switches, policy, *, is_video) -> Decision
```

The profile vocabulary — `DeviceProfile`, `DirectPlayProfile`, `TranscodingProfile`,
`CodecProfile`, `ProfileCondition`, `Switches`, `PlaybackPolicy` — is declared here as plain
frozen records rather than as wire models, so the table test builds them without a framework;
`api/media_info.py` parses the request body into them (T5).

Callers may assume: an **absent** profile is `DIRECT_PLAY` (spec §3.3 rule 1) while an **empty**
one is `NONE`, which is the measured half the rule had not been tested on; the policy gate is the
measured all-three rule for video and the single audio permission for audio items — implemented
here and nowhere else; `switches.enable_direct_play` is honoured and `switches.enable_transcoding`
is deliberately not consulted (spec §3.2); `REMUX` and `TRANSCODE` both produce a `TranscodingUrl`
downstream, and **nothing on the wire distinguishes them** — `reasons` says why *direct play*
failed, not which rung was reached; nothing in a `StreamPlan` ever exceeds the source (no
upscaling, AC-9) or the profile (AC-8), sample rate included — the ceiling itself, not the
reference's ladder step (behaviours §3.7).

Two of those are not what the first draft of this section said, and both were measured rather
than reasoned `[probe: tools/probe_decision_ladder.py, Jellyfin 10.11.11, 2026-08-29]`.
`is_video` is the **item's** kind and not something read off the file, because a music track with
cover art carries a video stream and is still negotiated as audio — `media/info.py` takes the
same flag from the same caller. And `supports_transcoding` cannot be derived from `outcome`: one
accepting profile answered direct play with the flag true and false depending only on whether it
declared a transcoding target.

**`media/hls.py`** — pure:

```python
@dataclass(frozen=True)
class Segment:
    index: int
    start_ticks: int
    duration_ticks: int

def plan_segments(runtime_ticks, keyframes: Sequence[int] | None,
                  cadence_ticks: int) -> list[Segment]
    # ENCODE path: uniform cadence, last segment the remainder.
    # COPY path: keyframe-aligned buckets from the stored keyframe list.
def media_playlist(segments, base_query: str) -> str      # VOD, v3, ENDLIST, ", nodesc",
                                                          # runtimeTicks + actualSegmentLengthTicks
def master_playlist(decision, stream_facts, main_query: str) -> str   # exactly one variant
```

The same `plan_segments` output drives the playlist, the per-segment `-ss` restart points and
the tests — one derivation, so the playlist can never disagree with production (AC-22's shape).

**`media/sessions.py`**:

```python
class TranscodeManager:
    def obtain(self, key: SessionKey, decision, source) -> TranscodeSession
        # keyed by PlaySessionId; reuse if live
    async def segment(self, session, index: int) -> Path
        # on disk → return; ahead of window → kill, restart at plan_segments()[index]
    def stop(self, device_id: str, play_session_id: str) -> bool
        # the DELETE route; kills the process, removes scratch
    def ping(self, session) -> None                  # every segment/playlist request
    async def run(self) -> None                      # kill-timer sweep, throttle check
    def shutdown(self) -> None                       # all sessions stopped, scratch cleared
```

Callers may assume: every ffmpeg the server ever starts is owned by exactly one session in this
registry (architecture §4); `stop` on an unknown id is a no-op returning `False` — the route
still answers `204`, matching the reference's fire-and-forget contract; time is injectable like
`SessionRegistry`'s, so kill-timer and throttle tests never sleep.

**`compat/ranges.py`**:

```python
def negotiate_range(header: str | None, size: int) -> RangeAnswer
    # RangeAnswer is one of: Full(200), Partial(206, start, end), Unsatisfiable(416)
    # multi-range and reversed → Full; suffix → Partial — the measured table, nothing else
```

**`media/probe.py`**: `inspect(path) -> MediaInspection` — a dataclass mirror of the two tables,
in `domain/media.py` so the repository can hand them out (ADR-0003). Raises on an unreadable or
unparseable file; the scan records the failure the way 003 §3.7 records unexamined files, and the
item simply has no media source until a rescan succeeds.

**Two failures, not one**, and a scan must tell them apart: `UnreadableMediaError` is a fact
about one file, while `ProberUnavailableError` — ffprobe is not installed — is true of *every*
file, and recording a whole library as unexaminable would hide an operator's problem behind its
own consequences. Both derive from `InspectionError` for a caller that does not care.

**`MediaProbeRepository`**: `get(library_id, relative_path)` reads whatever is stored;
`current(library_id, relative_path, size, mtime_ns)` reads it only while the change signal still
matches, and answers nothing when it does not. Two readers because the callers ask different
questions — a scan has the `stat` in hand and wants to know whether to re-inspect, and a wire
assembly must not touch the filesystem to answer a request (§6.1). `put` replaces the stream rows
rather than merging them: a file that lost a track between scans would otherwise keep it as a
track no file has, at an index a delivery command addresses.

## 6. Algorithms

### 6.1 Inspection and the cache

The scan pipeline, after 003's change detection says a media file is new or changed, runs
ffprobe once and upserts the two tables. The stored `size`/`mtime_ns` pair makes staleness a
single comparison at read time; a stale row triggers re-inspection at the next scan, not at
request time. `media/info.py` assembles the wire shapes from rows alone: the item-level
`Container` is the stored `container` verbatim, and the single container a **media source**
reports is derived there rather than stored, because the two routes derive it differently
(spec §3.1, measured). On a listing it is the file's extension where the stored list contains it
and the list's first member where it does not — no profile is consulted. In a negotiation it is
the first member the `DeviceProfile` accepts, which is `media/decision.py`'s to answer and T5's to
emit; with no profile the list is passed through untouched. `format_names` is read by neither: it
is the record of what the demuxer said, kept so that changing the normalisation costs a
re-derivation rather than a rescan.

**`ETag`, read at T3 and measured rather than reasoned.** It is `MD5` over the file's time of last
change expressed as a .NET tick count — 100-nanosecond units since year one, truncated — and then
two conventions that the assignment does not show: the decimal string is hashed as **UTF-16
little-endian**, and the sixteen bytes are rendered in .NET's **GUID byte order**, which reverses
the first three groups before writing them as hexadecimal `[source:
MediaBrowser.Controller/Entities/BaseItem.cs:1164, MediaBrowser.Common/Extensions/BaseExtensions.cs
GetMD5 @ v10.11.11]`. Either convention taken naively still produces 32 lowercase hexadecimal
characters, so no shape check catches it; both were proven by taking three real tags, reading each
file's `Last-Modified` from the static delivery route, and searching that second's ten million
ticks for the one that hashes to the tag — all three recovered exactly
`[probe: tools/probe_media_source.py, Jellyfin 10.11.11, 2026-08-29]`. The tag matters beyond the
source list: the `Tag` parameter in the TranscodingUrl must round-trip it.

**`media/info.py` emits the measured field set, constants included.** Fifteen of a source's
properties are booleans a local file always answers the same way, and the reference sends every one
of them on every source — so they are declared with those values rather than omitted, on 005's
`ChannelId` argument. Three stream families are *not* emitted and each is a different debt (spec
§3.1 names them): the localised `DisplayTitle` group, the demuxer fields 0006 has no column for,
and the subtitle-delivery group. The frame rates and `Level` are written the way .NET writes a
single-precision float — shortest round-trip, and no `.0` on a whole number.

### 6.2 The decision

Direct play, then remux, then transcode, stopping at the first success (spec §3.3): container
membership uses the reference's CSV-containment (a `DirectPlayProfile.Container` is a list);
codec conditions check the stored stream columns against the profile's `CodecProfiles`;
`MaxStreamingBitrate` bounds direct play. The remux step asks whether a transcoding profile's
container can hold every source stream copied; the transcode step builds `StreamPlan`s — copy
for every stream the profile accepts (AC-7, measured parity), encode-to-ceiling for the rest,
ceilings clamped to the source.

**CSV-containment is four rules, not one** `[source:
MediaBrowser.Model/Extensions/ContainerHelper.cs @ v10.11.11]`: an empty or absent list admits
everything; a list beginning with `-` inverts the whole answer; the **value** is split on commas
too, which is what lets the stored `mov,mp4,m4a,3gp,3g2,mj2` match a profile listing only `mp4`;
and an empty value is admitted by nothing, being refused before the empty-list rule is reached.
Members are not trimmed, because the reference does not trim them.

**Three things about the reasons**, all measured `[probe: tools/probe_decision_ladder.py,
Jellyfin 10.11.11, 2026-08-29]`. They are accumulated from the *direct-play* analysis alone, so
they never say which rung was reached. A refusal that has nothing to blame — no direct-play entry
to reject, or `EnableDirectPlay: false` against a profile the source satisfies — is
`DirectPlayError`. And they are emitted in **ascending flag value**, which is not the declaration
order: the reference's `[Flags]` enum is declared in subject groups and .NET's formatter sorts by
value. A condition whose property the reference maps to no reason at all — `IsAvc`,
`NumAudioStreams`, five others — fails **silently**, leaving direct play intact `[source:
MediaBrowser.Model/Dlna/StreamBuilder.cs GetTranscodeReasonForFailedCondition @ v10.11.11]`.

**A numeric condition is compared at the value's own precision, not the wire's.** The reference's
frame rate and level fields are 32-bit, and the wire prints the shortest decimal that reads back
as the same value; the comparison gets the value. `domain/media.py` owns the narrowing for both
readers (`narrow_to_single` and `InspectedStream.reference_frame_rate`) precisely so the
negotiation cannot come to disagree with the stream it negotiated about. Spec §3.3 carries the
observable consequence.

**The §3.3 HDR rule has nothing to condition on in v1, and says so rather than pretending.**
behaviours §3.4 diverges by honouring an explicit `DOVIWithHDR10Plus` declaration on the copy
path and stripping for clients that did not make one. Atrium's copy path strips nothing at all,
which is the same answer for every profile a v1 source can be negotiated against: `VideoRangeType`
carries only `SDR`, `HDR10` and `HLG`, the three a stream listing can produce (§4), so **no
inspection here ever answers `DOVIWithHDR10Plus`** and the conditional half of the divergence is
unreachable. It arrives with the inspection that reads Dolby Vision side data, and a branch
written now would be one no test could reach.

### 6.3 The TranscodingUrl

`media/urls.py` renders OQ-8's measured anatomy exactly: lowercase `/videos/{dashed-id}/`
prefix, `master.m3u8?&` with the leading ampersand, PascalCase parameters — `DeviceId`,
`MediaSourceId`, `VideoCodec` (the transcoding profile's list, verbatim), `AudioCodec`,
`AudioStreamIndex`, `VideoBitrate`/`AudioBitrate` (the negotiated split of the bitrate cap),
`MaxFramerate`, `SegmentContainer`, `MinSegments`, `BreakOnNonKeyFrames`, `PlaySessionId`,
`ApiKey` (the caller's own token — these URLs go to players that set no headers, spec §3.5),
`TranscodingMaxAudioChannels`, `RequireAvc`, `EnableAudioVbrEncoding`, `Tag` (the source
`ETag`), the source-codec condition triplet (`{codec}-level`, `{codec}-profile`,
`{codec}-videobitdepth`), and `TranscodeReasons` as a comma-joined list. A client that parses
this URL — and OQ-8 existed because some do — sees the reference's spelling.

**The URL carries what the profile permitted, not what the decision planned**, and T4 measured
the asymmetry so that T5 does not read the ceilings off a `StreamPlan` `[probe:
tools/probe_decision_ladder.py, Jellyfin 10.11.11, 2026-08-29]`. A `Height <= 4320` condition on
an 816-line source reaches the URL as `MaxHeight=4320`; `VideoBitrate` is the bitrate cap minus
the audio's share and stays far above the source's own; only `MaxFramerate` is clamped, because
it alone is seeded from the stream before the condition is minimised against it `[source:
MediaBrowser.Model/Dlna/StreamBuilder.cs:949, ApplyTranscodingConditions @ v10.11.11]`. The
clamped numbers in a `StreamPlan` are what to *produce* (§3.4, AC-9); these are what was
*allowed*, and they are two different sets of numbers on the same negotiation. Two more spellings
worth having before the task starts: `VideoCodec` is the transcoding profile's list verbatim even
when the video is being re-encoded, while `AudioCodec` narrows to the single codec chosen when
one can be copied and stays a list when none can.

### 6.4 HLS

The encode cadence and the copy bucketing both come from `plan_segments` over stored data. For
a re-encode, boundaries are the forced-keyframe cadence (the measured 3.004 s at 23.976 fps —
the exact rounding rule is read from the reference's playlist generator at task time and pinned
by a golden against these measured values); ffmpeg is instructed to force keyframes at exactly
those timestamps, so the playlist's promise and the produced bytes cannot drift. For a copy,
boundaries bucket the stored keyframe list at the copy cadence (measured 6.0 s), which is why
`video_keyframes` is a probe column. Segment requests inside the produced window serve the
finished file with `Content-Length` and `Accept-Ranges: bytes` (parity, behaviours §3.3);
outside it, §6.5 of the manager restarts production at `segments[index].start_ticks`. Produced
segments stay on disk for the session's life, which is what makes AC-23's within-session byte
identity structural.

### 6.5 Progressive delivery

**No authentication dependency on the four `stream` routes**, which is the measured rule and the
decision behaviours §2.10 had deferred to this feature: a request with no token, one with a token
nothing issued and one with `?api_key=` are one answer `[probe: tools/probe_range_matrix.py,
Jellyfin 10.11.11, 2026-08-29]`. `/universal` is the exception and declares one. The routes
therefore resolve an item **by identifier alone**, with no user and no visibility predicate — the
same shape `api/images.py` has, and for the same reason: a route that declared a dependency and
ignored its answer would still have to decide what an *invalid* token means.

The response is built header by header rather than with the framework's file response, because the
measured set is four headers and the convenient class ships an `ETag` and a `Content-Disposition`
the reference does not send — 006 met the identical trap on the image routes. There is no
conditional handling: `If-Modified-Since` is not read, measured.

An unknown item is the **third** error shape here (`404`, `text/plain`, the fixed 25 bytes), not
the problem details `PlaybackInfo` answers for the same identifier; the container path parameter
carries the reference's own spelling pattern, so an illegal container is a validation `400` keyed
on `container` decided before the lookup.

`/Audio/{id}/stream` and `/Videos/{id}/stream`: `static=true` serves the source bytes through
`negotiate_range` with the path suffix choosing only the `Content-Type` (behaviours §2.20) —
falling back to the file's own extension where the requested container names no label;
remuxes and re-encodes stream chunked with `Accept-Ranges: none` — except where the output size
is knowable, the §3.5 divergence: a remux produced to scratch first, and a WAV re-encode, whose
length is computable from sample count, so AC-20's valid-RIFF answer carries a real
`Content-Length` (behaviours §3.2's decided divergence, both symptoms).

### 6.6 `/universal`

The parameter set synthesises a device profile exactly as the reference's controller does —
`container` becomes the direct-play list, `transcodingContainer`/`transcodingProtocol` the
transcoding profile, the ceilings become codec conditions — then flows through the same
`decide()`. Three decided divergences, each recorded: the output sample rate is the stated
ceiling, not the Opus ladder step (behaviours §3.7); a codec-less http transcode picks the
transcoding container's own codec instead of answering an empty `200` (behaviours §3.8); and
`enableRedirection` is bound and never fires — v1 has no remote sources, so the measured
"proxied `200` bytes" is the only reachable answer (AC-21).

### 6.7 Session lifecycle and configuration

The manager's sweep enforces two clocks: a **ping timeout** — a session none of whose routes
have been called goes down with its scratch, the reference's kill-timer shape — and, when the
operator enables it, the **throttle**: production pauses (process suspension) once it leads the
last-requested position by `max(throttle_delay_seconds, 60)` and resumes when the gap closes.
`config/` grows `encoding` options named after the reference's: `enable_throttling` (false),
`throttle_delay_seconds` (180), `enable_segment_deletion` (false), `segment_keep_seconds`
(720) — same knobs, same defaults, same observable production curve (spec §3.4, §3.8). Client
disconnect on a progressive response cancels production through the response's own lifecycle;
`DELETE /Videos/ActiveEncodings` validates both parameters (`400` naming the missing one) and
stops exactly the named session. Server shutdown walks the registry and clears every scratch
directory; startup clears the scratch root of anything a crash left behind.

### 6.8 Measured at the gate, and what stays owed

Every §3 claim this plan builds on was measured on 2026-08-28 by the seven probes
(`probe_playback_info`, `probe_playback_refusal`, `probe_transcode_decision`, `probe_hls`,
`probe_universal_audio`, `probe_transcode_session`, `probe_range_matrix`) — the OQ table in the
spec carries the per-question answers. T4 added an eighth, `probe_decision_ladder`, because
none of the seven had asked what each *rung* answers: it overturned rule 1's untested half,
established the reasons' order and their subject, and separated the ceilings a URL carries from
the ceilings a plan holds. What stays owed to the task list:

* ~~**The `ETag` derivation** (§6.1)~~ — **discharged at T3**, and it took a search rather than a
  reading: the assignment carries two silent conventions, and §6.1 now records both with the probe
  that proved them. **The exact cadence-rounding rule** behind the measured 3.004 s (§6.4) is
  still one source-reading, cited with the task that implements it.
* **The reference's ping-timeout constants** (§6.7): the kill-timer shape is sourced
  (`TranscodeManager.cs`), the numbers are read when the sweep is built.
* ~~**The delivery-route error shapes** (§7): an unknown item on `/stream`~~ — **discharged at T6
  for the four `stream` routes**, and it is the third shape rather than the problem details the
  §7 table's "007-measured refusal family" implied. A **malformed range on a chunked response** is
  still owed, by T7, and the sized case is measured: every unreadable `Range` is a `200` with the
  whole body. The refusal shapes of `/universal`, the playlists and the segments remain owed to
  the tasks that land them, folded into a probe battery.
* **AC-26's disconnect timing** needs a fixture client that drops mid-body; it is an Atrium-side
  test, with the reference's own behaviour spot-checked by hand at the task.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| ffprobe missing at startup | Launch check | Log loudly; scans proceed without inspection, items carry no sources | Install; rescan |
| ffprobe fails on one file | Non-zero exit / parse error | File recorded as uninspected (003 §3.7's report), item has no media source | Next scan retries |
| Unknown or invisible item on any delivery route | Item lookup by id, no user | **The third shape** — `404`, `text/plain`, the fixed 25 bytes — on the four `stream` routes, measured at T6; the remaining routes are measured as they land | — |
| A container outside the reference's spelling rule on a `stream` route | The declared pattern | `400` problem details keyed `container`, naming the expression; decided before the lookup (T6, measured) | — |
| An item whose file is gone since the scan | `stat` fails | The same third-shape `404`. ⚠️ Not measured: it needs a file deleted underneath a live reference | Rescan |
| ffmpeg dies mid-production | Process exit observed by the manager | In-flight segment requests answer `500`; session torn down, scratch removed | Client re-negotiates |
| Client disconnects mid-response | Response lifecycle | Production cancelled, session reaped after grace (spec §3.8) | — |
| Segment requested past the playlist | Bounds check on the plan | `404` | — |
| `DELETE /Videos/ActiveEncodings`, unknown session | Registry miss | `204` — fire-and-forget, nothing to stop | — |
| `DELETE /Videos/ActiveEncodings`, missing parameter | Validation | `400` problem details naming the field (measured) | — |
| Scratch partially deleted underneath a live session | Segment file missing | Treated as out-of-window: restart at that segment | Automatic |
| Server restart | — | Registry empty; startup sweep clears orphaned scratch; clients re-negotiate | — |
| Probe row stale (file changed since scan) | `size`/`mtime_ns` mismatch at read | Serve the stored answer (it is what 005 emitted); re-inspect at next scan — never inline | Rescan |

## 8. Testing strategy

The pure core takes tables: `decide()` runs the profile classes — empty, accepts-all,
container-reject, video-codec-reject, audio-codec-reject, ceilings, nothing-plays, the policy
shapes — asserting outcome, reasons, flags and stream plans (AC-1..7, AC-9, AC-31);
`plan_segments` asserts uniformity, the short tail, and copy-bucket alignment against fixture
keyframes (AC-22's boundary half); `negotiate_range` runs the measured matrix (AC-11..13).

Fixtures are **synthetic, generated at build time** by ffmpeg into a cached directory: seconds
of colour bars and a tone. The matrix the tests need: `mp4/h264+aac` (direct play),
`mkv/h264+ac3` (container/audio rejections), `mkv/hevc+ac3` (video rejection — forces step 3),
one file with an accepted video track beside a rejected audio track (AC-7), a `flac` at 96 kHz
(AC-19), a multi-keyframe file long enough to segment. CI installs ffmpeg for the suite; the
fixtures stay seconds long because every transcode test spends real CPU (spec §6).

**Generation is bit-exact**, which is what makes the cached directory safe to reuse between runs:
two builds of one entry compare byte for byte, so a rebuilt tree is the same tree. It is not free —
the flags belong with the *output*, or Matroska writes a random segment identifier and the wall
clock at an unchanged file size, which the `(size, mtime_ns)` change signal cannot see (T1). The
cache is named after a digest of the matrix and the ffmpeg version line, because produced bytes are
a function of the encoder: a different ffmpeg is a different fixture, and gets a different
directory rather than a stale one.

Route tests prove the wiring once per route on those fixtures, asserting **properties of
delivered bytes, never reference byte-equality** (spec §6): the ffprobe-read codec of a
delivered segment equals the plan's (AC-7, AC-8), dimensions never exceed the source (AC-9),
the RIFF header and length are real (AC-20), a re-fetched segment is identical within a session
(AC-23), the playlist's `EXTINF` sum matches the fixture's duration (AC-22). Session tests
inject the clock: ping-timeout, throttle pause (enabled config), disconnect, stop-route kill,
scratch reclamation (AC-25..27, AC-29) — asserting on the manager's observable state and the
scratch directory, with the subprocess faked except in a small marked set that runs real
ffmpeg. Time-to-first-byte for a late seek (AC-10) is asserted as work-not-done — the restart
was issued with the right `-ss`, and no earlier segment file exists — not as wall-clock.

The L0 surface test picks the eleven routes from `surface.yaml` unchanged; the PascalCase sweep
covers the new DTOs by construction; the acceptance map grows its 008 rows when the feature
flips to Implemented (003 T21's lesson). The suite still opens no TCP connection: every
reference measurement in this feature is a `tools/` probe.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The decision engine disagrees with the reference's StreamBuilder on exotic profiles | Medium | High — wrong `TranscodingUrl` params or a wrong refusal | Golden per profile class now; the 010 differential replays real client profiles later; `decide()` is pure so a counter-example becomes a table row |
| Playlist prediction disagrees with produced segment durations | Medium | High — seek bar and retries break | One derivation feeds both (§6.4); a golden pins the measured 3.004 s/6.0 s values; a property test ffprobes produced segments against the plan |
| ffmpeg version drift changes produced bytes or capabilities | High over time | Low–medium | Tests assert properties, never bytes; the launch check logs the ffmpeg version; fixtures regenerate per environment |
| Process leaks: an ffmpeg outliving its session | Low | High — the machine dies slowly | Single ownership in the manager; kill paths are each a test; shutdown and startup sweeps clear scratch |
| Throttle suspension is platform-dependent | Medium | Low — off by default, operator-enabled | The mechanism is the manager's private choice; where suspension is unavailable it falls back to not reading ahead, and the observable (production stalls at the gap) is what the test asserts |
| The keyframe column grows large for long films | Low | Low | One ordered integer list per file, serialised compactly; measured before optimising (004's lesson) |
| CI cost of real-encode tests | Medium | Medium — a slow suite stops being run | Seconds-long fixtures, the fastest encoder settings, and the real-ffmpeg set kept small and marked |

## 10. Alternatives considered

**Probe on first playback instead of at scan.** Cheaper scans, and the spec names it as the
failure: the first play of every item — the moment a user is watching — pays the probe. The scan
already reads every new file; one ffprobe more is the right place. Rejected by spec §3.1.

**Streams as a JSON blob on the item.** One column, no second table — and every condition the
decision checks would parse JSON per negotiation, `NowPlayingItem`'s nine media-derived
properties would parse it per `/Sessions` poll, and nothing could ever be queried. Rows cost one
join keyed by path. Rejected.

**Per-segment ffmpeg invocations** (spawn one process per requested segment). Perfectly
seek-shaped, no restart logic — and a process spawn plus input seek per 3-second segment, with
boundary drift between invocations the exact thing rule 1 forbids. The reference runs one
sequential encoder per session and so does Atrium; the restart is the exception, not the unit.
Rejected.

**Deriving HLS boundaries from produced output** (serve what ffmpeg cut). No prediction
arithmetic — and the playlist cannot exist until production reaches its end, which the measured
reference disproves in 0.18 s, and out-of-order requests would have nothing to aim at. Rejected
by spec §3.7.

**An independent `SupportsDirectStream` remux flag** — "more correct" than the measured mirror.
A flag no 10.11.11 answer sets is a delta a differential flags on the first negotiation, and a
client that branched on it would take a path the reference never sends it down. Rejected
(behaviours §2.22); the remux reality lives in `TranscodeReasons`, where the reference puts it.

**Enforcing the draft's policy ladder** (a `403` for `EnableMediaPlayback`, per-step removal for
single denials). The measurement killed it: the reference does neither, and inventing refusals
is how a policy-restricted client that works against Jellyfin stops working against Atrium.
Rejected by spec §3.2/§3.3 as amended; the one non-replicated edge (delivery-time force-copy of
an incompatible stream) is argued in behaviours §2.21.

**A total-size scratch ceiling** (the draft's AC-29). The reference has no such knob — its
bounds are per-session reclamation and the optional age-based segment deletion — and a hard
ceiling that refuses mid-film is a new failure mode no client expects. Atrium ships the
reference's knobs; an operator who wants a bound gets it the same way a reference operator does.
Rejected with the spec's own amendment.
