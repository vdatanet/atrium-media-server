---
feature: 008-playback-negotiation-and-delivery
title: Playback negotiation and delivery — implementation plan
status: Implemented
created: 2026-08-29
updated: 2026-09-05
accepted: 2026-08-29
implemented: 2026-08-29
amended: 2026-08-29 by T3 — §6.1 records the `ETag` derivation and §6.8's first debt is discharged: MD5 over the modification time in .NET ticks, hashed as UTF-16 little-endian and rendered in .NET's GUID byte order, proven by recovering three files' tick counts from the tags the reference sent; and 2026-08-29 by T1 — §8 gains the bit-exactness the cached fixture directory rests on, measured where it fails; and 2026-08-29 by T4 — §5's contract gains `supports_transcoding` and `is_video` and loses "or empty" from rule 1, §6.2 records the containment rules, the reasons' order and subject, the comparison precision and the HDR rule's unreachability, and §6.3 records that the URL carries the profile's ceilings rather than the plan's; and 2026-08-29 by T6 — §3 gains `media/labels.py`, `api/delivery.py` and a `MediaFileRepository` that takes no user, §6.5 records that the four `stream` routes declare no authentication dependency at all and why the response is built header by header, §6.8's delivery-route error shape is discharged for those four (the third shape, not the problem details §7 implied), and §7 gains the container pattern's `400` and the missing-file case; and 2026-08-29 by T8 — §6.6's "exactly as the reference's controller does" is one clause too strong: its codec profile is scoped to the direct-play containers and therefore constrains nothing on the transcoding path, so the ceilings are stated unscoped here; and 2026-08-29 by T9 — §6.5's "a WAV re-encode, whose length is computable from sample count" is the wrong shape: a WAV states its own length inside the body and a piped one states `ffffffff`, so the output goes to scratch like a remux and the length is the file's, with `media/ffmpeg.py` refusing to build the piped invocation at all; and §6.6 gains the one inference row the reference has not got, kept out of the transcribed table; and 2026-08-29 by T10 — §6.4's two cadence claims both moved when the rounding rule was finally read: the scaling divides by the rate the *request* carries at 32-bit precision, so the published 3.004 s is a fact about one film's stored 23.975988 and the T1 fixture's exact `24000/1001` answers 3.003 s; and a copy buckets the source's keyframes only for a container the operator has permitted on-demand extraction for, shipped as Matroska alone, so the published 6.0 s was the equal grid at the copy default. §6.4 also records that forwarding a query string verbatim needed the pre-canonicalisation bytes, and that `BANDWIDTH` is this server's own encoder target rather than the reference's codec-scaled one; and 2026-08-29 by T11 — §5's `TranscodeManager` moved in three places: the decision belongs to the request rather than to the session, the restart position is the URI's `runtimeTicks` rather than `plan_segments()[index]`, and `run()` arrives with the policy it enforces at T12; §6.4's forced-keyframe grid is a divergence the reference does not share; and §6.8's segment refusal shapes are discharged; and 2026-08-29 by T12 — §5's `stop` takes the play session and not the device, because the reference keys on it alone and the `deviceId` the route requires decides nothing; §6.7 gains the measured kill-timer constants (§6.8's third debt), the reason the two clearing paths differ, and the diagnostic drain the ledger needed before any of them could reap a process at all — an unread `stderr` pipe fills and a process blocked on it never exits; and 2026-08-29 by T13 — §6.7 gains the four operator knobs' semantics and both of their floors: both measure against `runtimeTicks + actualSegmentLengthTicks`, the parameter the segment route bound and ignored; the encoder's position is read off the scratch directory rather than parsed out of its progress; the pause is `SIGSTOP` rather than the reference's stdin pause key, which `-nostdin` has already made unreachable; segment deletion is keyed on position rather than on age, measured; and policy at delivery is a per-stream refusal on the segment route answered with the `500` that route already has, never a `403`; and 2026-08-29 by T14 — nothing in this plan moved: the map is over `spec.md` §5 and the route set is over `surface.yaml`, and both were counted against the file rather than against prose. What T14 found belongs to the spec (AC-6 and AC-11) and to behaviours (the pipe destination's cost, §3.3); and 2026-08-30 by T15 — recorded late, by the audit of the same day (M1), because T15 amended `spec.md`, `tasks.md`, `behaviours.md` and the code and left this plan behind: §5's `media/hls.py` block is rewritten against the three signatures as they actually stand, and its **"exactly one variant"** is withdrawn in both places it survived — a stream-copied video whose source range is HDR gets an h264 SDR entrance beside the copy, at the copy's own `BANDWIDTH`, so one variant is a fact about the source and not about the route; and 2026-09-02 by the negotiation policy-gate fix — §1's *"the all-three policy gate"* and §4's *"the policy gate is the measured all-three rule for video and the single audio permission for audio items"* are both true of a negotiation **against a profile** and of no other. With none, the reference reaches no ladder answer to gate and reads one permission per media kind off the source instead, so `media/decision.py` gains `unnegotiated_transcoding` and `Decision.remuxing_denied` — the one place `SupportsDirectStream` stops mirroring `SupportsDirectPlay` — and rule 1 stops returning three unconditional `True`s. The contract sentence is therefore two rules and not one, still in this one module and nowhere else; and 2026-09-05 by the 2026-09-04 audit's L2 and L7–L12, the first amendments here that no task of this feature made — §3's tree gains `domain/media.py`, which this feature created and which no plan's tree drew, and §5's four blocks are read back against the modules. `Decision` had grown `target` (T5), `remuxing_denied` (the 2026-09-02 fix) and 011's `subtitles`/`subtitle_index`, and its `sub_protocol` is `str | int | None` since 012 T9; `StreamPlan.codec` is `str | None` on both branches; `master_playlist` grew 011's `subtitles`; `TranscodeManager.segment` grew T13's `length_ticks`; and the `RangeAnswer` comment described three variants of a class that is one dataclass with `status`/`start`/`length`/`total`. Every correction is additive or a type, each carries a dated note under the block it corrects, and no code moves
spec_status_required: Accepted
spec_status_actual: Implemented
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
├── domain/
│   └── media.py         MediaInspection and InspectedStream — what a file turned out to
│                        contain, so the repository can hand them out (ADR-0003, §4)
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

**`domain/media.py` is not in the tree this plan was accepted with, and this feature created it**
— added on 2026-09-05 by the 2026-09-04 audit's L2, which found it drawn in no plan's §3 at all
while §5 and §6.2 both name it and its own module docstring closes with *"See
specs/008-playback-negotiation-and-delivery/plan.md section 4"*, a section that does not draw it
either. It is where the two records the prober produces and the repository hands back have to
live, because ADR-0003 sends domain objects out and never rows; 011 §5 grows the same module and
its tree does not draw it either. Drawn here rather than restated there, in 001's own style for a
tree that outgrew its acceptance.

`db/repositories.py` also grows a `MediaFileRepository`, whose one query is an item id to the file
behind it. Separate from `ItemQueryRepository` because that one takes a **user** and applies 005's
visibility predicate, and the four `stream` routes have neither: they may be called with no token
at all (§6.5), so there is nobody to apply a predicate for. **`/universal` is the exception, and
it uses both**: it requires a token, and the reference resolves its item through the caller's user
`[source: Jellyfin.Api/Controllers/UniversalAudioController.cs:124 @ v10.11.11]`, so it runs the
visibility query first — which is also why an unknown item is problem details there and the third
error shape on its siblings (spec §3.6) — and reads the file through `MediaFileRepository` after.

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
    codec: str | None          # target; source codec when COPY, which can itself be unknown
    # ceilings already clamped to min(profile, source): §3.4 "limits, not targets"
    width: int | None
    height: int | None
    bitrate: int | None
    channels: int | None
    sample_rate: int | None
    bit_depth: int | None      # added at T7: the one condition the ladder read and could not carry

@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reasons: tuple[str, ...]   # TranscodeReason names, ascending flag value
    container: str | None      # negotiated output container ("ts")
    sub_protocol: str | int | None   # "hls" | "http"; the int is 012 T9's, below
    video: StreamPlan | None
    audio: StreamPlan | None
    supports_transcoding: bool # what this profile leaves producible, not what was answered
    subtitles: tuple[SubtitleAnswer, ...] = ()   # 011 T9; declared in 011 §5
    subtitle_index: int | None = None            # 011 T9; declared in 011 §5
    remuxing_denied: bool = False                # the 2026-09-02 policy-gate fix, above
    target: TranscodingProfile | None = None     # T5: the entry this answer was built from

    @property
    def supports_direct_play(self) -> bool       # outcome is DIRECT_PLAY
    @property
    def supports_direct_stream(self) -> bool     # the mirror, less `remuxing_denied`

def decide(source, profile, switches, policy, *, is_video) -> Decision
```

The profile vocabulary — `DeviceProfile`, `DirectPlayProfile`, `TranscodingProfile`,
`CodecProfile`, `ProfileCondition`, `Switches`, `PlaybackPolicy` — is declared here as plain
frozen records rather than as wire models, so the table test builds them without a framework;
`api/media_info.py` parses the request body into them (T5).

Callers may assume: an **absent** profile is `DIRECT_PLAY` (spec §3.3 rule 1) while an **empty**
one is `NONE`, which is the measured half the rule had not been tested on; the policy gate is the
measured all-three rule for video and the single audio permission for audio items **against a
profile**, and one permission per media kind when there is none — two rules, both implemented
here and nowhere else, because with no profile there is no ladder answer for the first one to
gate (spec §3.3, behaviours §2.21); `switches.enable_direct_play` is honoured and `switches.enable_transcoding`
is deliberately not consulted (spec §3.2); `REMUX` and `TRANSCODE` both produce a `TranscodingUrl`
downstream, and **nothing on the wire distinguishes them** — `reasons` says why *direct play*
failed, not which rung was reached; nothing in a `StreamPlan` ever exceeds the source (no
upscaling, AC-9) or the profile (AC-8), sample rate included — the ceiling itself, not the
reference's ladder step (behaviours §3.7).

`bit_depth` arrived at **T7**, and it is the field whose absence AC-8 could not survive.
`VideoBitDepth` is in the ladder's reason map — a profile that rejects ten-bit h264 refuses direct
play over it — and the plan had nowhere to carry the answer, so the transcode that refusal produced
would have handed the same client ten-bit h264 again: libx264 keeps the source's depth unless told
otherwise. Derived by the same `ceiling` the other five use, and stated to the encoder only where it
is below what arrived.

Two of those are not what the first draft of this section said, and both were measured rather
than reasoned `[probe: tools/probe_decision_ladder.py, Jellyfin 10.11.11, 2026-08-29]`.
`is_video` is the **item's** kind and not something read off the file, because a music track with
cover art carries a video stream and is still negotiated as audio — `media/info.py` takes the
same flag from the same caller. And `supports_transcoding` cannot be derived from `outcome`: one
accepting profile answered direct play with the flag true and false depending only on whether it
declared a transcoding target.

> **Corrected on 2026-09-05 by the 2026-09-04 audit's L7, L8 and L9**, which read this block
> against `src/atrium/media/decision.py:370-499` and found four declarations behind the class and
> one type behind it.
>
> * **`sub_protocol` is `str | int | None`** since 012 T9 (L7). An `int` is what the reference
>   answers when the profile named an ordinal no member has — behaviours §2.24, a number in this
>   field beside a progressive address. Recorded in 012's plan; this is the block a reader consults
>   for the dataclass, so it says so here too rather than only there.
> * **`codec` is `str | None`** (L8), and the audit named one branch where there are two: a COPY
>   carries the source's own codec and `InspectedStream.codec` is optional, *and* an ENCODE carries
>   `_first_codec(target.video_codec)`, which answers `None` for a transcoding entry that named no
>   codec at all. The block already annotated `width`/`height`/`bitrate` as optional, so the bare
>   `str` read as a decision rather than as drift.
> * **`target` was added at T5** (`f8893a6`) and named in no plan's text, this feature's amendment
>   log included — the `TranscodingUrl` repeats five of that entry's fields back to the client, and
>   re-deriving which entry won would be a second copy of `_choose_target`'s ranking (L9).
> * **`remuxing_denied`** is the same gap and the audit did not list it: the 2026-09-02 policy-gate
>   fix records it in this plan's frontmatter and in the *"Callers may assume"* paragraph above,
>   and never put it in the block.
> * **`subtitles` and `subtitle_index` are declared in [011 §5](../011-subtitle-delivery/plan.md#5-contracts)**,
>   so they are named here as a pointer rather than restated: 011 owns what a `SubtitleAnswer` is
>   and what "no default" means.
>
> The two properties are listed because `supports_direct_stream` stopped being a pure mirror at
> the same fix. `decide`'s signature is unchanged and was correct. No code moves.

**`media/hls.py`** — pure:

```python
@dataclass(frozen=True)
class Segment:
    index: int
    start_ticks: int
    duration_ticks: int

def plan_segments(runtime_ticks: int, milliseconds: int,
                  keyframes: Sequence[int] | None = None) -> tuple[Segment, ...]
    # ENCODE path: uniform cadence, last segment the remainder.
    # COPY path: keyframe-aligned buckets from the stored keyframe list, which is what
    # passing `keyframes` at all selects.
def media_playlist(segments: Sequence[Segment], *,
                   query: str,                            # VOD, v3, ENDLIST, ", nodesc",
                   container: str | None) -> str          # runtimeTicks + actualSegmentLengthTicks
def master_playlist(*, query: str,
                    video: StreamPlan | None, audio: StreamPlan | None,
                    source_video: InspectedStream | None, frame_rate: float | None,
                    options: Mapping[str, str] | None = None,
                    subtitles: Sequence[AnnouncedSubtitle] = ()) -> str
    # One variant for the negotiation, and an h264 SDR entrance beside an HDR stream copy.
    # Not "exactly one variant": see 6.4.
```

The same `plan_segments` output drives the playlist, the per-segment `-ss` restart points and
the tests — one derivation, so the playlist can never disagree with production (AC-22's shape).

> **Corrected on 2026-09-05 by the 2026-09-04 audit's L11.** `master_playlist` grew
> `subtitles: Sequence[AnnouncedSubtitle] = ()` at 011, which is the `#EXT-X-MEDIA` block and the
> `SUBTITLES` group on every variant. The parameter and `AnnouncedSubtitle` are declared in
> [011 §5](../011-subtitle-delivery/plan.md#5-contracts) and are named here as a pointer, not
> restated — but this block was **rewritten by T15 "against the three signatures as they actually
> stand"**, which is the sentence that makes a reader trust it, and it went behind again one
> feature later. Purely additive: every call this plan describes is still valid. No code moves.

**`media/sessions.py`**, as T11 landed it — three of these moved, and each of them for a measured
reason:

```python
class TranscodeManager:
    def obtain(self, key: SessionKey) -> TranscodeSession
        # keyed by (device, play session, media path); reused whether or not anything is running
    async def segment(self, session, plan: SegmentPlan, *, index: int, start_ticks: int,
                      length_ticks: int = 0) -> Path
        # on disk → return; behind or far ahead of production → kill, restart at start_ticks
        # length_ticks: T13's floors measure against runtimeTicks + actualSegmentLengthTicks
    async def stop(self, play_session_id: str) -> bool   # T12: the play session is the whole key
    def ping(self, session) -> None                  # every segment request
    def reporting(self, device_id: str) -> TranscodingReport | None   # T12, for /Sessions
    async def sweep(self) -> int                     # T12: the kill timer, one pass
    async def run(self) -> None                      # T12: that sweep on an interval
    async def shutdown(self) -> None                 # all sessions stopped, scratch root cleared
    def clear_scratch(self) -> None                  # T12: startup and shutdown, the root
```

* **`stop` takes the play session and not the device**, which is the third of these that moved
  for a measured reason. The route binds both — omitting either is a validation `400` naming it
  — and the reference then selects the jobs to kill by `playSessionId` whenever one was given
  `[source: MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:203-205 @ v10.11.11]`,
  measured on a `DELETE` carrying a device nothing owns `[probe:
  tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`. A signature taking both
  would have leaked an encoder for every client that spells its device differently between the
  negotiation and the stop. It is `async` for the reason `segment` is: ending a session waits on
  the process it owned.
* **`TranscodingReport` is what a session tells `/Sessions`**, recorded per request rather than
  per session for the same reason `SegmentPlan` is. Eleven of the reference's thirteen
  properties; the two it does not carry are `Framerate` and `CompletionPercentage`, which come
  from parsing the encoder's progress output (behaviours §3.11).

* **The decision is not part of a session**, it is part of a request. The reference rebuilds its
  whole streaming state from every segment request, so a client that changes audio track mid-film
  restarts with the new one; a manager holding the first request's answer would go on producing
  the track the client just left. `SegmentPlan` is that per-request bundle.
* **The restart position is the request's `runtimeTicks`, not `plan_segments()[index]`.** The
  index is ffmpeg's `-start_number` and decides only the produced file's name — measured, and the
  two agree for every URI a playlist writes `[probe: tools/probe_transcode_session.py, Jellyfin
  10.11.11, 2026-08-29]`.
* **`run()` arrives with the policy it enforces** (T12). A sweep loop that swept nothing would be
  a task in the lifespan doing nothing at all; what T11 wires is construction and `shutdown()`.

Callers may assume: every ffmpeg the server ever starts is owned by exactly one session in this
registry (architecture §4) and started through the `ProductionLedger`, which
`tests/unit/test_import_directions.py` sweeps for; `stop` on an unknown id is a no-op returning
`False` — the route still answers `204`, matching the reference's fire-and-forget contract; time
is injectable like `SessionRegistry`'s, so kill-timer and throttle tests never sleep.

> **Corrected on 2026-09-05 by the 2026-09-04 audit's L10.** `segment` takes a fifth argument,
> `length_ticks: int = 0`, added at T13 — and T13 amended §6.7 with the reason for it, *"both
> measure against `runtimeTicks + actualSegmentLengthTicks`, the parameter the segment route bound
> and ignored"*, without touching the signature it changed. The block above is where a reader
> looks for the shape, so the argument is in it now. Defaulted and purely additive; no code moves.

**`compat/ranges.py`**:

```python
@dataclass(frozen=True)
class RangeAnswer:         # one record, not a variant set — see the note below
    status: int            # 200, 206 or 416
    start: int
    length: int            # what to send, in every case, including none of it
    total: int
    @property
    def content_range(self) -> str | None    # None where the reference sends no header
    @property
    def is_refusal(self) -> bool

def negotiate_range(header: str | None, size: int) -> RangeAnswer
    # multi-range and reversed → whole body; suffix → 206 — the measured table, nothing else
```

> **Corrected on 2026-09-05 by the 2026-09-04 audit's L12.** The comment read
> *"`RangeAnswer` is one of: Full(200), Partial(206, start, end), Unsatisfiable(416)"*, and there
> are no such variants: it is **one** dataclass carrying `status`, `start`, `length` and `total`,
> and the field is a `length` rather than an `end`. That is not a naming accident — `start` and
> `length` describe what to send in every one of the three cases, *"so a caller never branches on
> the status to know how much to read"*, which is the opposite of what a variant set would make a
> caller do. The function's own signature was right and the comment under it described a shape
> nobody wrote. The record is declared here now instead. No code moves.

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
single comparison at read time; a stale row triggers re-inspection at the next scan, and at
request time on exactly one route — **012's negotiation**, for **one** file, when source zero
carries no stream of the item's own kind. That exception is the whole of 012's spec §3.2 and it is
narrow on purpose: it reads no other item, it opens no second part, and every listing and every
query still answers from stored rows alone. `media/info.py` assembles the wire shapes from rows
alone: the item-level `Container` is the stored `container` verbatim, and the single container a
**media source** reports is derived there rather than stored, because the two routes derive it
differently (spec §3.1, measured). On a listing it is the file's extension where the stored list
contains it and the list's first member where it does not — no profile is consulted. In a
negotiation it is the first member the `DeviceProfile` accepts, which is
`media/decision.py`'s to answer and T5's to emit; with no profile the list is passed through
untouched. `format_names` is read by neither: it is the record of what the demuxer said, kept so
that changing the normalisation costs a re-derivation rather than a rescan.

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

The encode cadence and the copy bucketing both come from `plan_segments` over stored data, in
`media/hls.py`, with `api/dynamic_hls.py` doing nothing but reaching the same `decide_delivery`
the `stream` pair reaches and rendering the answer. **The rounding rule this section owed is
read and cited in the module**, and it moved two things the draft had wrong (T10):

* **The re-encode cadence is `ceil(milliseconds × ceil(rate) ÷ rate)`**, over the rate the
  *request* carries in `MaxFramerate` — which the negotiation sets to the source's clamped rate
  and `media/urls.py` prints at 32-bit precision. So the module narrows the incoming float to a
  single before dividing, because the reference re-reads that decimal as one. The measured
  3.004 s is that arithmetic over a **stored** 23.975988; the T1 `long_take` fixture runs at an
  exact `24000/1001` and answers 3.003 s, which is the rule reproducing rather than failing. The
  golden pins the rule at five requested lengths and both rates.
* **A copy does not always bucket keyframes.** The reference reads a file's keyframes on demand
  only where the extension is in `AllowOnDemandMetadataBasedKeyframeExtractionForExtensions`,
  shipped as `["mkv"]` and confirmed as that on the operator's server; every other container
  gets the equal-length grid. The measured 6.0 s came from an mp4 film, so it was the grid at the
  copy default and not the source's keyframes. `media/hls.buckets_allowed` is that gate, keyed on
  the extension the way the reference keys it, and `video_keyframes` is still the input — for the
  containers that are allowed to use it.

The unrequested segment length is 3 s for a re-encode and 6 s for a copy. ffmpeg is instructed to
force keyframes at exactly the planned timestamps, so the playlist's promise and the produced
bytes cannot drift — **which the reference does not do**, and T11 found it by writing the encoder
arguments: it states the scaled cadence to the playlist and the unscaled integer to ffmpeg, so its
own segments hold four milliseconds less than they declare. The divergence is behaviours §3.10;
the playlist stays byte-identical. Segment requests inside the produced window serve the finished
file with `Content-Length`, `Accept-Ranges: bytes` and a `Last-Modified` (parity in all three,
behaviours §3.3); outside it the manager restarts production at the **request's `runtimeTicks`**,
which is what the reference seeks to and not the index in the path. Produced segments stay on disk
for the session's life, which is what makes AC-23's within-session byte identity structural.

**Both playlists forward the query string exactly as it arrived**, which needed a scope key
rather than a read of the request: `compat/query_params.py`'s case-insensitive rewrite has already
replaced every recognised parameter with *this* server's declared spelling by the time a handler
runs, so a forwarded `MaxFramerate` would reach a client's playlist as `maxFramerate`. The
middleware now stashes the original bytes under `ORIGINAL_QUERY_STRING` and these two routes are
the only readers.

**`BANDWIDTH` is the sum of the two stream plans' bitrates**, which is what this server will
produce. The reference advertises its own `OutputVideoBitrate`, and reaches it by scaling the
source's rate between the input and output codecs — so an h264 re-encode of an hevc source is
advertised higher there than here. Both servers advertise their own encoder's target; reproducing
the reference's number would mean advertising a rate `media/ffmpeg.py` is not aiming at — and
nothing selects on the rate here in any case, because **the master playlist is not always one
variant** (T15). Where the video is stream-copied and the source's own range is HDR, the reference
appends an h264 **SDR entrance** at the *same* `BANDWIDTH` as the copy, so a client selects on
colour rather than on rate `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:251-268 @
v10.11.11]`. The entrance is deliberately not a rung of a ladder: it carries the copy's own number.
The hevc and av1 entrances beside it need encoder permissions that ship `false` `[source:
MediaBrowser.Model/Configuration/EncodingOptions.cs:57-58 @ v10.11.11]`, and adaptive bitrate
streaming is disabled for a copy — so one variant is what a standard-range negotiation answers,
which is a fact about the source and not about the route.

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
is knowable, the §3.5 divergence: a remux produced to scratch first, and a WAV re-encode
(behaviours §3.2's decided divergence, both symptoms).

**The WAV length is read off the produced file, not predicted from a sample count**, and T9 found
the reason it has to be: a WAV states its own length *inside the body*, twice — the `RIFF` size
and the `data` chunk's — and a muxer writing to a pipe fills both with `ffffffff` and exits `0`.
So there is no chunked WAV answer to add a computed header to; the output goes to scratch like a
remux, and the length comes from the same `stat` that sizes one. `media/ffmpeg.py` names the
property (`NEEDS_SEEKING`) and **refuses to build the piped invocation**, so the impossibility is
structural rather than a rule each caller remembers.

**A `stream` request is a device profile with the client's own words in it** (T7). The query
parameters describe an output — these codecs, inside these ceilings — and `media/decision.py`
already turns exactly that into stream plans, so `api/delivery.py` synthesises a `DeviceProfile`
with one `TranscodingProfile` and the ceilings as `CodecProfile` conditions, and runs the same
`decide()`. That is §6.6's shape one task early, and it is what keeps copy-or-encode a single
rule: a codec the client did not name is the source's own, so a bare request remuxes; a codec it
named that the source does not have is an encode; a ceiling below the source is an encode. The
synthesised profile lists **no** direct-play entry, which is right — `static=true` is the direct
play on these routes, and everything else is a production. No policy gate is applied: these routes
take no user at all (§6.5's first paragraph), so there is no account whose permissions could be
read, and AC-31's delivery half stays T13's.

**Two destinations, decided by whether any stream is re-encoded — and, since T9, by whether the
container states its own length.** A `REMUX` is produced to a
scratch file named after the command and the file's `(size, mtime_ns)` — spec §3.4 makes a remux's
byte-identity global, so a second request for the same thing serves what the first produced, and
that is what makes `Range` on it cheap rather than an encode per seek. Published with a rename, so
a half-written file is never visible under the name anything serves. A `TRANSCODE` is written to a
**pipe** and streamed as it is produced — unless its container is one that cannot be piped, which
takes the same scratch path for a different reason (above); the first block is read before the
response is returned, so an encoder that dies on the way up answers the measured `500` instead of
an empty `200`. A piped
mp4 carries `-movflags frag_keyframe+empty_moov+default_base_moof`, because an index cannot be
written last to something that cannot be seeked — our own answer to our own choice of pipe, and one
no client can observe: spec §6 already declines to byte-compare produced output.

**Every ceiling is passed to the encoder only where it is below what arrived.** A `StreamPlan`
always states a number — `min(profile, source)`, and the source's own where the profile stated none
— so passing them all means telling the encoder to reproduce the source exactly. Measured on the
fixture matrix as two `500`s: `-ar 96000` at a `libmp3lame` that stops at 48 000, and `-b:a` at the
FLAC source's lossless rate. Left off, ffmpeg negotiates values the encoder supports, which is what
the reference's own invocation gets by leaving the same arguments off. The rule is uniform across
the scale filter, the pixel format, the bitrates, the channel count and the sample rate, and it is
also AC-9 read structurally: a plan equal to the source produces no `-vf` at all, so there is
nothing that *could* upscale.

`media/ffmpeg.py` holds a `ProductionLedger` — the set of live processes, one per application,
reached the way `api/images.py` reaches its cache. It exists because AC-26's "the work stops" is
only checkable against something that holds the live set, and T11's `TranscodeManager` keys
sessions on top of it rather than replacing it. `server.py`'s lifespan stops what is left.

### 6.6 `/universal`

The parameter set synthesises a device profile as the reference's controller does — `container`
becomes the direct-play list (split on **commas before bars**),
`transcodingContainer`/`transcodingProtocol` the transcoding profile, the ceilings codec
conditions — then flows through the same `decide()`. Three decided divergences, each recorded:
the output sample rate is the stated ceiling, not the Opus ladder step (behaviours §3.7); a
transcode naming no codec takes the one the reference's own inference table gives the
transcoding container, instead of the one it gives a request path with no extension in it —
which is the empty `200` (behaviours §3.8); and `enableRedirection` is bound and never fires —
v1 has no remote sources, so the measured "proxied `200` bytes" is the only reachable answer
(AC-21).

**One place the synthesis is deliberately not the reference's, found at T8.** Its
`GetDeviceProfile` gives the codec profile carrying the ceilings a container list of the
*direct-play* containers — the ones it will not be transcoding into — so those conditions apply
to nothing on the transcoding path, and the ceiling reaches the encoder only because the
controller passes `maxAudioSampleRate` into the streaming request outside the profile as well.
Here the profile is the only path, so the conditions are stated **unscoped**; that is what
reproduces the measured answer to `container=ogg` with `transcodingContainer=flac` and a
sample-rate ceiling, which a literal transcription would have delivered unconstrained.

**One row is added to the inference rather than to the transcribed table** (T9). The reference's
codec inference answers an unlisted container with the container's own name, so a `wav`
transcoding container asks for an encoder called `wav`; the missing row lives in
`media/ffmpeg.py` beside the muxer table, and `codec_for` consults it *after* the transcription,
which keeps the citation on that table honest about what the reference actually contains.

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

**Both knobs measure against one number, and it is `actualSegmentLengthTicks` plus
`runtimeTicks`** — the parameter the segment route bound and ignored until T13. The session
keeps the largest such sum any request has produced, which is the reference's own rule `[source:
Jellyfin.Api/Controllers/DynamicHlsController.cs:2029 @ v10.11.11]`, and both passes are one
comparison against it: the throttle asks how far the encoder leads it, and segment deletion asks
which indexes fall a whole window behind it. **Where the encoder has got to is read off the
scratch directory** rather than out of a progress parser — production began at a known position
numbering its files from a known index, so the newest file's name is the position — which is
what lets a server that runs its encoders at `-loglevel error` answer the same question the
reference answers by parsing them.

**The pause is a signal, not the reference's pause key.** The reference writes `p` (or `c` into
an unpatched build) on the encoder's standard input `[source:
MediaBrowser.Controller/MediaEncoding/TranscodingThrottler.cs:128-146 @ v10.11.11]`; this
server passes `-nostdin` and has no console to hand a child, so `SIGSTOP`/`SIGCONT` is what
produces the one observable the knob is about — the output stops growing, and starts again.
Safe against the kill paths because the ledger's stop is `SIGKILL`, which a stopped process
receives without being resumed first; a polite signal would have sat pending for ever.

**Segment deletion is keyed on position, and the reading that said "age" was wrong.** The
reference removes the indexes `0 … (downloadSeconds − keepSeconds) / segmentSeconds` and
removes nothing while the download position is inside the window `[source:
MediaBrowser.Controller/MediaEncoding/TranscodingSegmentCleaner.cs:100-113 @ v10.11.11]`,
measured on a live one at a 720-second window: index 29 gone, index 33 kept, forty-five seconds
after both were written and with nothing requested in between `[probe:
tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`. The divisor is the
**unscaled** requested segment length, the same integer the read-ahead tolerance uses, not the
scaled cadence the playlist states (§6.4). Both numbers carry a floor applied at the point of
use rather than at validation — 60 for the throttle gap, 20 for the keep window — because that
is where the reference applies them, and a value an operator can type into Jellyfin's own
configuration page must not stop this server from starting.

**Policy at delivery is a per-stream refusal on the video routes.** `media/decision.py` gains a
predicate over a `Decision` and a `PlaybackPolicy` — a stream planned as an encode against a
denied permission — and the segment route, the one delivery route that has both a user and a
production, raises the `500` it already answers for anything it cannot produce. Not a `403`: the
gate struck the spec's policy `403` as fiction once already, and inventing one here for a
different permission would put it back. The playlists are deliberately not gated, because they
produce nothing and the reference refuses neither.

**The ping timeout is sixty seconds**, discharging §6.8's third debt. The reference keeps one per
job and chooses it by a single property — `10000` ms for a progressive job, `60000` ms for
everything else — restarting the timer on every request that finishes and killing the job when
one fires with nothing newer to wait for `[source:
MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:145-190 @ v10.11.11]`. Sixty is the
number this registry uses, because a progressive response owns its encoder for its own lifetime
and stops it in a `finally`; nothing here is progressive. Measured as well as read: 58 s and 60 s
on two runs of a session whose client fetched one segment and went quiet `[probe:
tools/probe_transcode_session.py, Jellyfin 10.11.11, 2026-08-29]`. The sweep is one loop over
every session on a ten-second interval rather than a timer per job — 007's playback reaper's
shape — so a session dies inside a timeout plus a tick.

**The two clearing paths are not the same path**, and the difference is what the scratch root
holds. A session owns a *directory* named for its key; a remux owns a *file* named for the
command that produced it (§6.5), deliberately shared because spec §3.4 makes a remux
byte-identical for everyone who asks for it. So ending one session removes one directory and
never touches the files beside it, while startup and shutdown clear the root whole — which is the
reference's own startup behaviour, minus the empty directories it leaves `[source:
MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:717-736 @ v10.11.11]`.

**And the ledger reads its processes' diagnostics**, which is a lifecycle property rather than a
logging one: `ProductionLedger.start` gives every process a `stderr` pipe, and a pipe nobody
reads fills at some tens of kilobytes — a process blocked writing into a full one never reaches
its own exit, so it can neither finish nor be reaped by waiting. At `-loglevel error` a healthy
encode says nothing, which is why the hazard survived from T7 to here. Every production therefore
has exactly one reader task, started in the same statement that starts the process, keeping the
last twenty lines; a production that exits non-zero on its own logs them, and one that was killed
does not, because a signal is not a fault to report. Two details are load-bearing and neither was
obvious: the reader reads by **block**, because a line reader refuses a line longer than its
stream's limit and then stops reading — the same hang with more code — and `finish` **waits** for
the reader rather than cancelling it, because the process is already dead and the words it left
buffered are exactly the ones the log line wanted.

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
  that proved them. ~~**The exact cadence-rounding rule** behind the measured 3.004 s (§6.4)~~ —
  **discharged at T10**, and reading it moved the number: 3.004 s is the scaling over a *stored*
  23.975988 rather than over the nominal 23.976, so the same rule answers 3.003 s for a source at
  an exact `24000/1001`. The probe grew a five-row cadence matrix, which is what separates `ceil`
  from `round`, and the copy half of §6.4 moved with it.
* ~~**The reference's ping-timeout constants** (§6.7)~~ — **discharged at T12**, and reading
  them was the smaller half: the numbers are 60 000 ms and 10 000 ms, split by whether the job is
  progressive, and §6.7 records which one this registry uses and why. What the same battery found
  was that the *stop route* is keyed on the play session alone — the `deviceId` it requires
  decides nothing — and that the reference does **not** remove a stopped session's
  `TranscodingInfo`, which the spec had asserted in both directions without measuring either
  (behaviours §3.11).
* ~~**The delivery-route error shapes** (§7): an unknown item on `/stream`~~ — **discharged at T6
  for the four `stream` routes**, and it is the third shape rather than the problem details the
  §7 table's "007-measured refusal family" implied. ~~A **malformed range on a chunked response**~~
  — **discharged at T7**: on a chunked answer *every* `Range` is ignored, readable or not, so the
  sized case's five-shape table has no counterpart here at all (behaviours §3.3). The refusal
  shapes of `/universal` ~~, the playlists and the segments~~ remain owed to the tasks that land
  them, folded into a probe battery. **The playlists' four were discharged at T10**, into
  `probe_hls.py`: `401` empty with no credential — these two routes require a token where the four
  `stream` routes require none — and then the `stream` pair's own shapes, `404` and `400` in
  `text/plain`, rather than `/universal`'s problem details. The fourth is not a refusal: a
  `main.m3u8` with no query at all answers a playlist. **The segments' six were discharged at
  T11**, into `probe_transcode_session.py`'s segment battery: those same three, plus a `400` in
  the same shape for a request carrying `startTimeTicks`, plus the one that is *not* the third
  shape — `runtimeTicks` and `actualSegmentLengthTicks` are required, so a segment URI stripped of
  its query answers problem details where `main.m3u8` stripped of its query answers a playlist —
  and one that is not a refusal at all: a `playlistId` nothing named still serves the segment.
* ~~**AC-26's disconnect timing** needs a fixture client that drops mid-body~~ — **discharged at
  T7**, and the client had to be written rather than configured: **httpx's ASGI transport cannot
  drop a connection.** It drives the application to completion and hands back a buffered body, so
  every "streaming" test in this repository is really a buffered one, and a test that opened a
  stream and broke out of the loop would have been asserting against a response that had already
  finished. `tests/conformance/test_progressive_delivery.py` calls the application directly and
  returns `http.disconnect` from `receive` as soon as the first body chunk is sent, which is what
  a dropped connection *is* at the ASGI boundary.
* ~~**The two `[prior-probe: 2026-08-03]` WAV citations** of behaviours §3.2~~ — **discharged at
  T9**, into `probe_universal_audio.py`'s WAV battery, and both claims moved: the `500` has two
  causes rather than one (a `wav` extension inferred as a codec, and a `pcm_*` codec with no
  `audioBitRate`), and the headerless body comes from the **transcoding** container rather than
  from `Container`, which is `/universal`'s direct-play list. The battery also needed a fresh
  `DeviceId` on every row: the reference names its transcode output from the media path, the user
  agent, the device and the play session, so a request that cannot be produced at all is served a
  neighbouring request's bytes — four rows of the first draft passed for exactly that reason.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| ffprobe missing at startup | Launch check | Log loudly; scans proceed without inspection, items carry no sources | Install; rescan |
| ffprobe fails on one file | Non-zero exit / parse error | File recorded as uninspected (003 §3.7's report), item has no media source | Next scan retries |
| Unknown or invisible item on any delivery route | Item lookup by id, no user | **The third shape** — `404`, `text/plain`, the fixed 25 bytes — on the four `stream` routes, measured at T6; the remaining routes are measured as they land | — |
| A container outside the reference's spelling rule on a `stream` route | The declared pattern | `400` problem details keyed `container`, naming the expression; decided before the lookup (T6, measured) | — |
| An item whose file is gone since the scan | `stat` fails | The same third-shape `404`. ⚠️ Not measured: it needs a file deleted underneath a live reference | Rescan |
| A `mediaSourceId` naming no part of the item | Compared against the item's derived source ids | **The third shape at `400`** on both halves of the route, where the reference answers `400` to a well-formed value and `500` to an unparseable one (T7, measured; behaviours §3.9) | — |
| A produced request into a container nothing can mux | No muxer for the container, or a muxer the streams do not fit | **The third shape at `500`**, carrying `Accept-Ranges: none` — parity, measured on `stream.banana`, `?container=banana` and `stream.mp3` on a film (T7) | — |
| A produced request for a file nothing has inspected | No probe row for the part | The same `500`: there are no streams to copy, no codecs to compare and no indexes to map. `static=true` is unaffected | Rescan |
| ffmpeg dies mid-production | Process exit observed by the manager | In-flight segment requests answer `500`; session torn down, scratch removed. Before the first byte, the progressive routes answer the third shape at `500` (T7) | Client re-negotiates |
| Client disconnects mid-response | Response lifecycle | Production cancelled, session reaped after grace (spec §3.8) | — |
| Segment requested past the playlist | Bounds check on the plan | `404` | — |
| `DELETE /Videos/ActiveEncodings`, unknown session | Registry miss | `204` — fire-and-forget, nothing to stop | — |
| `DELETE /Videos/ActiveEncodings`, missing parameter | Validation | `400` problem details naming the field (measured) | — |
| Scratch partially deleted underneath a live session | Segment file missing | Treated as out-of-window: restart at that segment | Automatic |
| Server restart | — | Registry empty; startup sweep clears orphaned scratch; clients re-negotiate | — |
| Probe row stale (file changed since scan) | `size`/`mtime_ns` mismatch at read | Serve the stored answer (it is what 005 emitted); re-inspect at next scan, and inline on 012's negotiation alone — which then writes the file's `(size, mtime_ns)` beside it, so the healed source's `Size` and `ETag` describe one set of bytes ([012 plan D-1](../012-negotiation-inputs/plan.md#d-1--the-healed-items-etag)) | Rescan, or one negotiation |

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
