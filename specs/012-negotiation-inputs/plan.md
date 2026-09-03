---
feature: 012-negotiation-inputs
title: Negotiation inputs — implementation plan
status: Draft
created: 2026-09-03
updated: 2026-09-03
spec_status_required: Accepted
spec_status_actual: Accepted
---

# 012 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour, and it was measured
> before this plan started: all nine of its open questions were answered by four probes on
> 2026-08-29 and the answers moved it. Where this plan states a reference behaviour, the citation
> lives in the spec section it names — or inline, where this plan read something the spec did not.
> **Five things below are inline for that reason**, and one of them contradicts an open question's
> own summary of itself.

## 1. Approach

The spec is one rule seen from two sides, and the code is two changes that do not touch each
other: one in the negotiation's item half (`api/media_info.py` and a new `library/inspection.py`),
one in the request model that every body in the project inherits (`compat/model.py`). Nothing in
`media/decision.py`'s ladder moves, which is what AC-9 asks for.

Six decisions carry it, and the two that decide the most were settled by reading files rather
than by reasoning: the trigger is not the condition the defect looks like, and the binder's default
clause does not generalise the way the open question that owns it says it does.

**The trigger is the reference's, and it is not "this source has no stored inspection".** The
condition is a property of **source zero and of the item's own kind**: a negotiation refreshes with
probing when the item's path ends `.strm`, *or* the item is a video whose first source carries no
video stream, *or* the item is audio whose first source carries no audio stream
`[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:175-178 @ v10.11.11]`. Written
as "every part with no inspection" — the shape the defect presents as — this feature would probe a
second part the reference never opens and would *not* probe an item whose first file was inspected
successfully and holds no video stream, which the reference re-probes on **every** negotiation for
ever. The two conditions coincide on the one fixture the gate built and diverge on the two the
suite has to add. §6.1 is the condition; §8 is the two fixtures that tell it from the naive one.

**A source that cannot be opened is negotiated against an inspection that is never stored.** The
ladder takes a `MediaInspection`, so the flags cannot be decided without one; the reference pays
its probe on every negotiation of an unreadable file, measured at 0.18–0.20 s three runs running
(spec §3.2), which is exactly what a stored failure would stop doing. So `library/inspection.py`
answers a **transient** empty inspection for the ladder to refuse against, and writes nothing.
That single choice satisfies AC-1 and AC-4 without a negative cache, keeps AC-10 true by
construction (nothing was written, so no listing changes), and reproduces the reference's cost
model rather than improving on it.

**The audio `400` is not this feature's refusal.** It is the platform's: the reference's audio
builder asserts the selected stream is non-null
`[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:104 @ v10.11.11]`, its exception middleware
maps every `ArgumentException` to `400` with `Content-Type: text/plain`, and outside a Development
environment the body is the fixed 25 bytes `Error processing request.`
`[source: Jellyfin.Api/Middleware/ExceptionMiddleware.cs:93, 98, 127 @ v10.11.11]`. That is the
body `compat/errors.py` has shipped as `CONTROLLER_ERROR_BODY` since 002, so AC-6 is a raise and a
handler that already exists, not a new error shape. It also fixes the condition exactly: **the
refusal is about the source having no audio stream, not about the file being unreadable** — an
audio item whose file opens cleanly and holds no audio track is refused the same way, and that is
a second fixture rather than a second rule.

**The protocol half is one change to `compat/model.py` for the *case* class and is not one change
for the *empty* class.** OQ-4 concluded that "closing it is one change to the shared request-model
behaviour rather than five". Read at the converter, that is right about three of the four classes
and wrong about one: case-insensitive names and ordinals — including ordinals no member has — come
from the globally registered `JsonStringEnumConverter` and `NumberHandling =
AllowReadingFromString`, which reach every enumerated value in every body
`[source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:34, 42 @ v10.11.11]`. **The empty string and
the explicit null take a declared default only for an enumeration that declares one**, because the
converter that implements it is created by a factory whose `CanConvert` requires the type to carry
`[DefaultValue]`
`[source: src/Jellyfin.Extensions/Json/Converters/JsonDefaultStringEnumConverterFactory.cs:20 @ v10.11.11]`,
`[source: src/Jellyfin.Extensions/Json/Converters/JsonDefaultStringEnumConverter.cs:30-38 @ v10.11.11]`.
`MediaStreamProtocol` carries `[DefaultValue(http)]`; `DlnaProfileType`, `ProfileConditionType`,
`ProfileConditionValue`, `CodecType` and `SubtitleDeliveryMethod` — the five other enumerations
this body binds — carry none. So `""` is the protocol's default *and* is a `400` on the other five,
and a binder that generalised all four classes would answer `200` where the reference answers
`400`, on five properties, in the name of parity. §6.7 is the binder, parameterised by exactly that
attribute.

**The out-of-range ordinal is reproduced, and it is already decided.** `2` answers `200`, a
progressive address and `TranscodingSubProtocol: 2` — a number in a field the enumeration spells
as a word — and [behaviours §2.24](../../docs/compatibility/behaviours.md) states in as many words
that Atrium reproduces it: *"it is a `200` a client can act on, so it is class B and there is
nothing to gain by tidying it"*. This plan therefore does not reserve it as a question; it prices
it (§6.5), and the price is that one wire field and one internal value are `str | int` rather than
a member.

**The negotiation writes to a table a request has never written to, and one sentence in an
implemented plan says it must not.** [008 plan §6.1](../008-playback-negotiation-and-delivery/plan.md#61-inspection-and-the-cache)
reads *"a stale row triggers re-inspection at the next scan, not at request time"*, and
`MediaProbeRepository`'s own docstring repeats it. That was a correct statement of 008's design and
is the exact invariant this feature exists to retire; §2 records it as a deviation and names the
document that moves with the code.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Ticks are the internal unit; conversion happens once, at ingestion | [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions) |
| Serialisation is opt-out: `AtriumModel` is PascalCase, null-suppressing, case-insensitive on the way in | [architecture §4](../../docs/architecture.md#4-cross-cutting-decisions), [001 plan §5](../001-server-identity-and-discovery/plan.md) |
| `ffprobe`/`ffmpeg` are external processes | [ADR-0002](../../docs/decisions/0002-python-and-the-runtime-stack.md) |
| `media/` performs inspection and evaluates profiles; it decides no policy and imports no `db` | [architecture §1](../../docs/architecture.md#module-responsibilities), enforced in practice — no module under `media/` imports `atrium.db` today |
| `library/` owns filesystem walking, path resolution and change detection, and may write through repositories | [architecture §1](../../docs/architecture.md#module-responsibilities), `library/scan.py` |
| `(size, mtime_ns)` is the change signal; a `deep` scan is the escape hatch | [003 plan §6.4](../003-library-configuration-and-scanning/plan.md#64-change-detection) |
| The ladder, its reasons, its ceilings and its refusals | [008 plan §6.2](../008-playback-negotiation-and-delivery/plan.md#62-the-decision), [008 §3.3](../008-playback-negotiation-and-delivery/spec.md#33-the-decision) |
| The `TranscodingUrl` anatomy and the `hls`/`http` split inside it | [008 plan §6.3](../008-playback-negotiation-and-delivery/plan.md#63-the-transcodingurl), `media/urls.py` |
| A body's refusal is problem details keyed as the reference keys it | [007 plan](../007-user-data-and-playstate/plan.md), `compat/errors.py`, [behaviours §1.11](../../docs/compatibility/behaviours.md) |
| `asyncio.to_thread` is how blocking work leaves the event loop | `users/sessions.py:186`, `users/playing.py:232` |

**Deviations: one, and it is the feature.**

| Deviation | What it was | What it becomes |
|---|---|---|
| [008 plan §6.1](../008-playback-negotiation-and-delivery/plan.md#61-inspection-and-the-cache): *"a stale row triggers re-inspection at the next scan, not at request time"* — said again in that plan's §7 (*"re-inspect at next scan — **never inline**"*) and a third time in `MediaProbeRepository`'s own docstring | True of every read path in the project, and the reason that repository has two readers and no request-time writer | **One route may open one file**: `POST`/`GET /Items/{itemId}/PlaybackInfo`, under the reference's own trigger, writing through the scan's own repository. Every other read path keeps the rule |

**No ADR.** [specs/README](../README.md) requires an ADR for a deviation from a
*project-level* choice — `architecture.md` or an ADR — and this is neither: `architecture.md` says
nothing about when a file may be opened, and 008's sentence is a feature plan's. What it needs is
the amendment, and all three sentences — 008 plan §6.1, 008 plan §7's failure row and
`MediaProbeRepository`'s docstring — move in the commit that lands it (Principle III:
documentation moves with the code). Three copies of one invariant is also why the deviation is
worth a table row: a reader who finds only one of them will believe the feature broke it by
accident.

## 3. Modules

| Module | Change | Responsibility |
|---|---|---|
| `library/inspection.py` | **New**, ~120 lines | The reference's trigger, evaluated against stored inspections; opening one file now; storing what it says; and the transient empty inspection for a file that cannot be opened. The counterpart of `library/scan.py`'s `_inspect_media` for a single file and a single request |
| `api/media_info.py` | Changed | `_negotiation` becomes `async`, resolves before the profile branch, and raises the audio refusal. `TranscodingProfileDto.protocol` becomes an enumerated value |
| `compat/model.py` | Changed | The enum binder every request model inherits: case, ordinal, out-of-range ordinal, and — only where the enumeration declares one — the default for an empty string or a null |
| `compat/errors.py` | Changed | A body refusal inside a nested property is keyed by its **JSON path** rather than by `$`; and `NegotiationRefusedError`, a twenty-fifth row in `EXCEPTION_HANDLERS`, answering `controller_error(400)` |
| `media/decision.py` | Changed, narrowly | `StreamProtocol` and its ordinal table, beside `SubtitleMethod` and its own — the second vocabulary read from two sides. `TranscodingProfile.protocol` takes that type. No ladder logic moves |
| `media/urls.py` | Changed, one line | `HLS` becomes `StreamProtocol.HLS.value` rather than a second literal `"hls"` |
| `api/media_info.py` (models) | Changed | `_bound_subtitle_method` is **deleted**: 011 T9's narrow binder is what §6.7 generalises, and leaving both would be two answers to one question |

**Why the resolution lives in `library/` and not in `media/`.** It writes, and writing means a
repository, and no module under `media/` imports `atrium.db` — a boundary that is true today and
worth keeping true, because `media/decision.py` is the one module in this project that is a pure
function of its inputs and is tested as one. `library/` already owns the only other place a probe
row is written and already owns the change signal that decides whether one is stale. The API module
supplies the session, as it does for every other repository it uses.

**Why not a method on `MediaProbeRepository`.** The repository's contract is "what is stored"; the
trigger is a fact about *the item and its kind*, and the transient inspection is not stored at all.
A repository that could answer "open this file" would be the fourth reader of a class whose
docstring exists to say there are two.

## 4. Data model

**No migration. No new table, no new column, no new index.** Everything this feature writes is
already written by `library/scan.py` through `MediaProbeRepository.put`, into `media_probes` and
`media_streams` (revision `0006_media_probes`), and everything it reads is already read by
`ItemQueryRepository._probes`.

What changes is **when** a row is written, and by whom:

| Row | Written today by | Written after this feature by |
|---|---|---|
| `media_probes` / `media_streams` for one file | `library/scan.py`, during a scan | The same repository, additionally from one route, for one file, when the reference's trigger fires and the file opens |
| `item_sources.(size, mtime_ns)` | `library/scan.py` | **Unchanged — see below** |
| Anything else | — | Nothing |

**`item_sources` is not touched, and the consequence is one wire field.** `MediaSourceInfo.ETag` is
derived from `item_sources.mtime_ns` (`media/info.py:media_etag`), while `Size`, `RunTimeTicks`,
`Bitrate` and `MediaStreams` come from the inspection. A file whose bytes changed after the scan is
therefore healed in four fields and keeps the tag of the bytes the scan saw, until the next scan.
The reference's on-demand path is a **full metadata refresh**, which updates its own change signal
too. Two ways to close it, and this plan takes neither without the owner: writing `(size,
mtime_ns)` from the same `stat()` the inspection already read — the honest option, and a second
003-owned table written from a request — or leaving it and recording the difference. **D-1.**

**The write is idempotent and the transaction is the request's.** `put` deletes and rewrites the
file's streams inside the caller's session, and `session_scope` commits at the end of the request
(`db/engine.py`). Two concurrent negotiations of the same file both probe and both write; the
second write replaces the first with an identical row. No lock — see §6.2 and §9.

**One column that is not this feature's, found while reading for it.** `items.runtime_ticks` is
written only by the metadata merge, and the merge deliberately refuses `Field.RUNTIME` for a
file-backed item because *"a film's runtime comes from probing the file"*
(`metadata/merge.py:_applies_to`, `metadata/refresh.py:_wanted_from_remote`). **Nothing writes it
from a probe.** Measured in this repository on 2026-09-03: a real 003 scan of the generated media
matrix leaves `runtime_ticks` `NULL` on all eleven films and on the audio item beside them, while
each item's media source carries the value — so `RunTimeTicks` is `null` at item level on every
film, episode and track a real Atrium serves, and 007's `PlayedPercentage` (position over that
runtime) is `null` with it. That is a divergence in implemented code, adjacent to this feature
because it is the item-level half of what the reference's refresh heals and what this feature's
write does **not**. It is not 012's to fix — **D-2, taken on 2026-09-03: out of 012**.

## 5. Contracts

```python
# library/inspection.py — the on-demand half of 003's inspection, for one file, in one request.

def wanted(
    sources: Sequence[MediaSource],
    inspections: Sequence[MediaInspection | None],
    *,
    is_video: bool,
) -> bool:
    """Whether this item's sources must be opened before a profile is applied.

    The reference's condition exactly: source **zero** carries no stream of the item's own kind,
    or its path ends `.strm` - which is source zero's path here, an item's own `Path` being that
    file's on the reference too. A property of the item, answered once, not a filter over parts
    `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:175-178 @ v10.11.11]`.
    """


def opened(path: Path, prober: MediaProber = inspect) -> MediaInspection | None:
    """Open one file now, or `None` when it cannot be opened. Never raises.

    Touches no session and no ORM object, because it is what the route runs in a thread.
    `ProberUnavailableError` and `UnreadableMediaError` are both `None` here: the caller cannot
    act on the difference inside one request, and `library/scan.py` keeps the distinction where
    it decides something (003 §3.7).
    """


def store(session: Session, library_id: str, relative_path: str, found: MediaInspection) -> None:
    """Write one inspection through the scan's own repository. `MediaProbeRepository.put`, and
    nothing else: the streams are replaced, not merged."""


def unopened(part: MediaSource) -> MediaInspection:
    """The transient inspection a file that would not open is negotiated against.

    Size and change signal from the stored source row, an empty container - so
    `media/info.py:source_container` still answers the file's extension - no runtime, no bitrate,
    no streams. **Never stored.** It exists so the ladder can decide the three capability flags
    for a source with nothing in it, which is what the reference's answer carries (012 AC-1).
    """
```

```python
# media/decision.py — one more vocabulary, beside SubtitleMethod's.

class StreamProtocol(Enum):
    """How a produced stream is delivered. Two members, lower-case by declaration
    `[source: Jellyfin.Data/Enums/MediaStreamProtocol.cs @ v10.11.11]`."""
    HTTP = "http"
    HLS = "hls"

STREAM_PROTOCOL_ORDINALS: Final[dict[int, StreamProtocol]] = {0: HTTP, 1: HLS}

@dataclass(frozen=True, slots=True)
class TranscodingProfile:
    protocol: StreamProtocol | int = StreamProtocol.HTTP
    """A member, or the raw ordinal for a number no member has - which the reference accepts and
    echoes back as a number (behaviours §2.24). Read for one comparison and copied to the wire."""
```

```python
# api/media_info.py

async def _negotiation(...) -> PlaybackInfoResponse:
    """Unchanged in shape. Two things happen before the per-source loop: the sources are resolved
    (§6.2) and an audio item with no audio stream is refused (§6.4)."""
```

**Invariants this feature adds, stated so a later reader cannot break them silently:**

1. `unopened()`'s result is never passed to `store()`. The only value `store` ever receives is one
   `opened()` returned, and the harm is sharper than "a row that says nothing": the transient
   inspection carries the source row's own `(size, mtime_ns)`, so a stored one would satisfy
   `MediaProbeRepository.current()` against the file's real stat and **the next scan would skip
   the file** — for ever, on a library nothing can play, with only a `deep` scan left as the cure.
   That is this feature making the listing permanently worse, which AC-10 forbids, and it is one
   line away at every call site.
2. `wanted()` reads source **zero** and the item's kind, and nothing else. It is not "is this part
   inspected".
3. The resolution runs on both routes, before the profile is consulted. The reference's `GET` calls
   the same helper with the same `allowMediaProbe`
   `[source: Jellyfin.Api/Controllers/MediaInfoController.cs:87 @ v10.11.11]`, so a profile-less
   negotiation heals the item too.

## 6. Algorithms

### 6.1 The trigger

Evaluated once per negotiation, before anything else looks at the body:

```
open the item's files when   item.path ends with ".strm"                      (v1 has none)
                        or   item is video and source[0] has no video stream
                        or   item is audio and source[0] has no audio stream
```

`[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:175-178 @ v10.11.11]`

Three things follow that the shape of the bug does not suggest.

**A source with no stored inspection is a special case of the condition, not the condition.** An
item whose file was inspected successfully and holds no stream of its own kind — an audio item that
is a video file, a video item that is an audio file — satisfies it too, and pays the probe on
**every** negotiation for ever, exactly as an unreadable file does. Atrium reproduces that: the
trigger is re-evaluated per request and the answer for such a file never changes.

**It reads source zero, and the refresh it triggers re-reads all of them.** The reference asks
`mediaSources[0].MediaStreams` and then refreshes *the item*. A two-part film whose first part is
annotated and whose second is not is therefore **not** probed there, and one whose first part is
not annotated has both re-read. This plan reproduces the trigger exactly and opens **every part
whose stored inspection is absent** once it fires — which is the same answer for every fixture in
this repository and is a *reading* of what a full refresh does to a multi-part item rather than a
measurement of it. Named as owed in §6.8.

**`.strm` is in the condition and out of v1.** No library extension configured by 003 admits one,
so the clause is written, unreachable, and cited — rather than silently dropped, which is how a
later reader learns the condition was three and not two.

### 6.2 Resolving inside the request

```
resolved = list(stored inspections)
if wanted(sources, resolved, is_video=is_video):
    for index, part in enumerate(sources):
        if resolved[index] is not None:
            continue
        found = await asyncio.to_thread(inspection.opened, absolute(root, part.relative_path))
        if found is None:
            resolved[index] = inspection.unopened(part)     # transient, never stored
        else:
            resolved[index] = found
            inspection.store(session, item.library_id, part.relative_path, found)
```

**Off the event loop.** `media/probe.py:inspect` is `subprocess.run`, and a negotiation is served by
an `async def`; 0.2 s of blocked loop on the measured happy path and up to `TIMEOUT_SECONDS` on a
pathological file would stall every other request in the process. `asyncio.to_thread` is the
project's existing idiom for exactly this (`users/sessions.py`, `users/playing.py`), and it is
enough here because `opened()` touches no session — the write happens back on the loop thread,
through the request's own session, where every other write in this route already happens.

**The timeout is inherited and is a divergence in the safe direction.** `media/probe.py` bounds an
inspection at 60 s; the reference bounds its probe only by the request's cancellation token
(`MediaEncoder.GetMediaInfoInternal` takes one and sets no timer). A file that takes longer than a
minute is answered here as un-inspectable where the reference would still be reading. Keeping one
timeout for both callers is the recommendation — a second, shorter, request-only deadline is a knob
whose only justification is a file nobody has measured. **D-3.**

**No lock.** Two negotiations of the same file at the same time run two `ffprobe`s and write the
same row twice, the second replacing the first. 011's extraction takes a lock because its artefact
is a *file* two writers would corrupt; a row is not, and the reference takes no request-level lock
either. The cost is a duplicated probe on a burst, which is bounded by the same 0.2 s the single
case pays. Recorded in §9 rather than mitigated, because the mitigation — a per-path lock in a
process that may have several workers — is a bigger claim than the problem.

**What the listing sees afterwards.** Nothing in the listing path changes (AC-10). It reads
`media_probes`, so the *next* listing of a healed item carries the streams, the runtime, the
bitrate and the corrected size (AC-3) because the row is there, not because anything on that path
learned to probe. That is the mechanism the spec's §3.1 row four names, and it is the whole of the
music client's cure.

**But AC-10's second clause was overtaken by a change to implemented code after 012's spec was
accepted, and this plan cannot write a test that asserts it.** The criterion reads *"the flags it
carries there stay `true`: they are not a negotiation and nothing decides them"*. Something does,
since 2026-09-02: a listed source's `SupportsTranscoding` and `SupportsDirectStream` are the
**account's own permissions**, one per media kind, because the reference builds an item body's
`MediaSources` and a profile-less negotiation's from one function — measured across six policy
shapes on `/Items/{itemId}`, `/Items` and `/Items/Latest`, and measured on a video item nothing
ever inspected `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-02]`,
`[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:355-372 @ v10.11.11]`. So on
both servers the flags are `true` for an unrestricted seat and not for every seat, and 008's fix
already implements it (`api/item_dto.py`, `media/decision.py:unnegotiated_transcoding`). What AC-10
is *for* is untouched — this feature must not change what a listing answers — and its wording was
one clause too strong. **D-5, taken on 2026-09-03: the accepted spec is amended**, in this same
change, and AC-10 now prohibits without also claiming which values the flags hold.

### 6.3 What an un-inspectable source answers

`unopened()` hands the ladder a `MediaInspection` with no streams. Everything below then happens in
code that already exists, and the answer it produces was checked against `media/decision.py` rather
than assumed:

* `_selected_audio` and `source.video` answer `None`, so `_producible` admits every transcoding
  target of the item's kind — a target that names no video codec cannot carry a video stream, and
  there is no video stream to carry;
* `_direct_play_reasons` refuses, because the source's container matches no direct-play entry of a
  profile that plays neither the container nor the codec, so `SupportsDirectPlay` is `false` and
  `SupportsDirectStream` mirrors it — the mirror holds for a negotiation that *has* a profile,
  which this one does ([behaviours §2.22](../../docs/compatibility/behaviours.md));
* `_choose_target` returns the first admitted target with **no stream plans at all**, so `outcome`
  is `TRANSCODE` (the remux test requires at least one plan) and `supports_transcoding` is `true`;
* `_annotate` therefore writes `TranscodingContainer`, `TranscodingSubProtocol` and a
  `TranscodingUrl` — AC-4 — and the address carries none of the codec ceilings, because
  `media/urls.py` reads them off streams that are not there.

**AC-1 is satisfied by deleting a branch, not by adding one — and the branch is no longer empty.**
`if inspection is None: … continue` in `_negotiation` is what leaves `SupportsDirectPlay` at its
model default with no address; since 2026-09-02 it also writes the two flags the *account's*
permissions decide (`ladder.unnegotiated_transcoding` and `ladder.unnegotiated_direct_stream`,
008's policy-gate fix). Removing it loses neither, and that was checked rather than assumed:
`decide()`'s rule 1 — the profile-less branch — calls the same two functions itself, and the
profiled branch reaches the ladder's own gate. So a `GET` on a source that could not be read
answers exactly what it answers today, and a `POST` answers what AC-1 asks for.

**What this feature does not do is follow the address.** The reference's own answer for this source
names `live.m3u8` and that playlist answers `500`
([behaviours §3.13](../../docs/compatibility/behaviours.md)); v1 has no live path, its
`TranscodingUrl` names `master.m3u8`, and AC-4 is explicitly about answering *with* an address. The
byte-level difference between the two addresses is what the L3 case in §8 exists to record rather
than to resolve.

### 6.4 The audio refusal

```
for each source this request negotiates about, in order:
    if not is_video and a profile is in play and its selected audio stream is None:
        raise NegotiationRefusedError   →  controller_error(400)
                                        →  400, text/plain, b"Error processing request."
```

**Inside the loop, on the first offending source, and it abandons the whole answer** — which is
what the reference does by throwing out of a builder called per source, after the source list has
already been narrowed by `MediaSourceId`. A two-part audio item whose second part has no audio
stream is therefore refused even though its first part could have been played, and a body naming
the first part is answered normally.

A class of its own in `compat/errors.py` with a row in `EXCEPTION_HANDLERS`, which is the
convention every refusal in this project follows and the reason 009 T10 gave for it: the class is
read at the raise site, and reusing `DeliverySourceError` would put "no such media source" on a
request that named one. The bytes are `CONTROLLER_ERROR_BODY`'s, unchanged since 002.

Three properties of that line, each measured or read:

**It is the generic refusal, not a specific one.** `ArgumentNullException` escapes the audio
builder `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:104 @ v10.11.11]`, the middleware maps
`ArgumentException` to `400`, sets `text/plain`, and — outside Development — writes the fixed
sentence `[source: Jellyfin.Api/Middleware/ExceptionMiddleware.cs:93, 98, 127 @ v10.11.11]`. The
probe measured `400 text/plain` and the first 60 bytes of the body; the sentence is read rather
than measured, and it is the same 25 bytes `compat/errors.py:CONTROLLER_ERROR_BODY` already sends
on the delivery routes. §6.8 names the confirmation that is owed.

**Its condition is the audio stream, not the file.** `GetDefaultAudioStream(null)` returning null
is the whole of it, so a readable audio file with no audio track is refused identically. Writing
the condition as "the inspection failed" would pass every test built on the gate's fixture and be
wrong about the item the fixture is named after.

**It is gated on a profile and on nothing else.** The reference reaches the builder only inside
`if (profile is not null)`, so the same request with no `DeviceProfile` — and with no stored device
profile to fall back on — is the `200` and the un-annotated source that AC-6's second clause names.
`options.ForceDirectPlay` and `options.ForceDirectStream` short-circuit ahead of the null check and
are set from nothing on this path, so no body can dodge the refusal.

### 6.5 The protocol, in four classes

The vocabulary moves into `media/decision.py` beside `SubtitleMethod`, for the reason that module
already gives for the delivery method's ordinals: **both** binders read it. `media/urls.py`'s
`HLS = "hls"` becomes `StreamProtocol.HLS.value`, so the string a comparison is made against and
the string an answer echoes cannot come apart.

| The profile says | Binds to | Answered |
|---|---|---|
| `hls`, `Hls`, `HLS`, `hLs` | `StreamProtocol.HLS` | An HLS address, `TranscodingSubProtocol: "hls"` |
| `http`, `Http`, `HTTP` | `StreamProtocol.HTTP` | A progressive address, `"http"` |
| absent, `null`, `""` | `StreamProtocol.HTTP`, the declared default | A progressive address, `"http"` |
| `0`, `"0"`, `1`, `"1"` | The ordinal's member | As above |
| `2`, `"2"` | The raw ordinal `2` | A progressive address, `TranscodingSubProtocol: 2` |
| `dash`, `" "`, `true` | Nothing | `400`, problem details (§6.6) |

`[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`, spec §3.3

**The two defects the spec counts are closed by two different lines.** The wrong branch is closed
by the comparison reading a member instead of a string; the contradicting echo is closed by
`_annotate` writing `decided.sub_protocol`, which is now the enumeration's spelling and not the
client's, because nothing carries the client's spelling any further than the binder.

**The out-of-range ordinal costs one union.** `TranscodingProfile.protocol` is
`StreamProtocol | int`; `Decision.sub_protocol` and `MediaSourceInfo.TranscodingSubProtocol` become
`str | int`. Every comparison in the project is `== StreamProtocol.HLS` (or its value), which an
`int` fails, so a `2` takes the progressive branch by falling through — which is precisely how the
reference reaches the same answer. `AtriumModel` serialises the int as a JSON number without help.

### 6.6 The refusal's key is a JSON path

The measured key is `$.DeviceProfile.TranscodingProfiles[0].Protocol` — one entry in `errors`, with
the property's full path `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`.
`compat/errors.py:_body_error` cannot produce it: it keys a vocabulary mismatch under
`DESERIALISATION_KEY` (`"$"`), which is what was measured for a **top-level** property of
`POST /Playlists` `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`. Both are the same converter throwing during deserialisation and being keyed by
its path; `$` is the path of a top-level failure as that route reports it, and the nested one is
this one.

So `_body_error` gains a path builder rather than a special case: from pydantic's `loc`, drop the
leading `body`, map each name through its owning model's alias, render a list index as `[n]`, and
join with `.` after a leading `$`. `("body", "device_profile", "transcoding_profiles", 0,
"protocol")` becomes `$.DeviceProfile.TranscodingProfiles[0].Protocol`. Two rules keep it from
changing anything that already passes:

* a failure whose location is **one level deep** keeps the key it has today — `"$"` for a
  vocabulary mismatch, the property's own name for a null, `""` for anything else — because that is
  what 007 and 009 measured on the routes that have one;
* the path is built from **aliases**, per level, through the nested model's own `model_fields`,
  which is `_wire_name` applied at each step rather than only at the last.

**The message is owed.** The gate's probe recorded the key alone (`sorted(document["errors"])`).
Whether the sentence is `VOCABULARY_MESSAGE` with `Path: $.DeviceProfile…` in it, and what
`BytePositionInLine` counts for a nested token, is one request away and is not answerable from the
files. §6.8, and T-level work in §8.

### 6.7 The general enum binder

`AtriumModel` gains a `mode="before"` validator beside `_accept_any_casing`, applied per field
whose annotation is an `Enum` subclass:

```
value is an Enum member                     → unchanged
value is a bool                             → unchanged  (a bool is an int in Python and is a 400 there)
value is an int, or a str of ASCII digits   → the ordinal's member, else the raw int
value is a str matching a member's value    → that member, folded
value is None or ""                         → the declared default, when the enumeration declares one
anything else                               → unchanged, and the model's validation answers 400
```

**"Declares one" is a registration, and it is declared where the enumeration is.** What the
reference reads is `[DefaultValue]` on the *enum type*, so the Python equivalent is a property of
the type and not a table in the binder: `compat/model.py` exposes a one-line class decorator
(`@wire_default(...)`) that records the member in a registry the validator consults, and
`media/decision.py` applies it to `StreamProtocol` — the only enumeration in v1 that carries one.
The direction is the existing one: `media/` already imports `compat/model.py`, and `compat/` learns
nothing about a route by holding a registry.

**Not an attribute inside the enum body**, which is the trap this design is chosen to avoid:
`WIRE_DEFAULT = "http"` written between the members would be an *alias* of `HTTP` rather than a
class variable, and `StreamProtocol.WIRE_DEFAULT` would then be a third name for a member that a
`for one in StreamProtocol` loop does not yield and an `is` comparison does. It would work, and it
would be wrong in a way nothing fails on.

That registration is the whole of the difference between the protocol's four classes and the other
five enumerations' three, and it is why this validator is general and its default clause is not.

**A bool must stay a bool on the way in.** Python's `isinstance(True, int)` is the trap: `true` is
a measured `400` and the ordinal `1` is a measured HLS, and a binder that folded the two would
answer HLS to a client that sent a boolean. The same trap is already avoided by
`_bound_subtitle_method`'s first line, which is the code this replaces.

**What it makes right beyond the protocol.** `ProfileType`, `ConditionType`, `ConditionProperty`
and `CodecKind` are matched case-sensitively today and are each a `400` where the reference answers
`200` — measured while 011 was implementing its own vocabulary
`[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`, spec OQ-4. They are
fixed by inheritance, and `_bound_subtitle_method` is deleted in the same change rather than left
beside its own generalisation.

**What it must not make right.** Nothing outside a request body. A query parameter that names no
member is a `200` that ignores the value, not a `400`
([behaviours §1.12](../../docs/compatibility/behaviours.md), `media/decision.py:method_named`), and
that asymmetry is measured on both sides. `AtriumModel` is the base of response models too; the
validator runs on construction from a client's mapping and costs a well-formed body nothing,
because — like `_accept_any_casing` — it only does work when a value does not already fit.

### 6.8 What this plan read and did not measure

Written as a section rather than as footnotes, because [011 plan §6.8](../011-subtitle-delivery/plan.md)
and [008 plan §6.8](../008-playback-negotiation-and-delivery/plan.md) both exist and both were
where the next feature's first task started.

1. **The audio refusal's body is read, not measured.** `Error processing request.` is the
   middleware's non-Development string; the probe stored 60 bytes of the answer and asserted only
   the status. A run that prints the body settles it, and it is one line in
   `tools/probe_uninspected_source.py`.
2. **The nested refusal's *message* is unmeasured.** §6.6 has the key and not the sentence.
3. **The multi-part case is read from what a full refresh means, not measured.** Whether the
   reference's refresh re-probes a second part whose first sibling was already annotated — and
   whether it probes parts at all beyond the one the trigger read — needs a two-file item in the
   gate's fixture. It is the one place this plan's "open every part with no inspection" could be
   wrong in the direction of doing more than the reference.
4. **The `GET` route's probe is read, not measured.** The controller calls the same helper
   `[source: Jellyfin.Api/Controllers/MediaInfoController.cs:87 @ v10.11.11]`; the gate exercised
   the `POST` only. It matters because it decides whether a profile-less negotiation heals a
   listing.
5. **Concurrency is not measured on either server.** Two simultaneous negotiations of one
   unreadable file: this plan says two probes, no lock, and nothing has watched the reference do it.
6. **`item_sources.(size, mtime_ns)` after the reference's refresh is unmeasured**, which is half
   of D-1: the `ETag` of a healed item was not compared before and after.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| The file cannot be opened (absent, zero-length, not the container its extension claims) | `opened()` returns `None` | The ladder decides against a transient inspection: flags decided, an address, `200` (AC-1, AC-4) | None stored, so the next negotiation tries again — the reference's own cost model |
| `ffprobe` is not installed | `ProberUnavailableError`, caught in `opened()` | Identical to the row above | An operator's problem; `library/scan.py` keeps the distinction where it decides something |
| The inspection exceeds 60 s | `subprocess.TimeoutExpired` → `UnreadableMediaError` | Identical to the row above | The next negotiation tries again |
| An audio item has no audio stream and a profile is in play | The selected audio stream is `None` after resolution | `400`, `text/plain`, `Error processing request.` (AC-6) | None. It is the answer |
| The same item is negotiated twice at once | Not detected | Two probes, two identical writes | Idempotent by construction |
| The write fails (disk, lock, constraint) | The session raises | `session_scope` rolls the request back — including the negotiation's own answer | The client retries; nothing partial is stored |
| A profile's protocol names no member | The model's validation | `400`, problem details keyed on the property's JSON path (AC-8) | The client fixes its profile |
| A profile's protocol is an ordinal no member has | Nothing — it binds | `200`, a progressive address, `TranscodingSubProtocol: 2` | None needed; parity |
| A **stored** device profile will not bind | `_stored_profile`'s `ValidationError` | Treated as absent, as today | Unchanged by this feature — and the generalised binder makes fewer stored profiles unbindable |

**The rollback row is the one worth reading twice.** The answer and the write share a transaction,
so a failed write means no answer rather than an answer whose inspection was lost. The alternative
— committing the probe in its own session before rendering — would let a client see an annotated
listing for a negotiation that then failed. Not worth it: the reference's refresh and its answer
are in one request too.

## 8. Testing strategy

**The fixtures come first, because none of them exists and the first cannot be built by a library
at all.**

| Fixture | What it is | Why |
|---|---|---|
| `unreadable.mkv` | Four kibibytes that are not a container, in the movies tree, scanned | The state the whole feature is about. `tools/probe_uninspected_source.py` builds the same thing the same way — the scan that creates an item is the scan that probes it, so the state exists only where the probe *failed* |
| `latent.mkv` | The same, replaced with real bytes **after** the scan, in the test | AC-2 and AC-3: the only thing that has ever read those bytes successfully is the negotiation |
| `soundless.m4a` | A readable audio item whose file holds **no audio stream** | AC-6's real condition. The gate's fixture conflates "unreadable" with "no audio stream" and this one separates them |
| `videoless.mkv` | A readable **video** item whose file holds no video stream | §6.1's trigger, in the case where "no inspection" and "no stream of the item's kind" disagree. Nothing else in the suite tells the naive trigger from the right one |
| A two-part film with part zero annotated and part one not | Built from the existing multi-part film | The negative case for §6.1: the trigger must not fire |

All of them are `tests/fixtures/media.py`'s to declare and `media_world.py`'s to scan, which puts
them in front of the real 003 pipeline and the real prober — the only world in this repository
where a row and a file are known to agree, and the reason the first fixture is a *subtraction*: the
scan that creates an item is the scan that probes it, so the state exists only where the probe
failed. **A truncated file is not one of them**: the first
kibibyte of a Matroska probes cleanly (spec §7.1), and a fixture built on that mistake would assert
the empty shape against a file that answers a full annotation.

| Criterion | How it is proven | Where |
|---|---|---|
| AC-1 flags decided for a never-opened source | `unreadable.mkv` + a profile that plays neither container nor codec → `false`/`false`/`true` | `tests/conformance/test_playback_info.py` |
| AC-2 a readable file annotated by the request that asked | `latent.mkv`: listing (empty), negotiate (two streams, runtime, bitrate, corrected `Size`) | conformance |
| AC-3 what it learned is written down | the same fixture, read three times: listing, negotiate, listing — asserting the **second** listing carries what the negotiation answered | conformance |
| AC-4 an advertised capability has an address | `unreadable.mkv` answers a `TranscodingUrl`; asserted **including** for the source that could not be read | conformance |
| AC-5 the switches reach the ladder | `latent.mkv` with `EnableDirectPlay`/`EnableDirectStream` false against a profile that **direct-plays** it — first answer direct play, second a transcode with reasons | conformance |
| AC-6 the audio `400` | `soundless.m4a` with a profile → `400`, `text/plain`, 25 bytes; without a profile → `200` and the un-annotated source | conformance + golden bytes |
| AC-7 any case answers the same address, echoing the enumeration's spelling | table over `hls`/`Hls`/`HLS`/`hLs` and the three `http` spellings: one address shape per pair, `TranscodingSubProtocol` always the member's value | conformance |
| AC-8 by class, not by rule | the four classes of §6.5, including `2` → `TranscodingSubProtocol: 2`, and `dash`/`" "`/`true` → `400` keyed on the JSON path | conformance + `tests/unit/test_compat_errors.py` |
| AC-9 nothing else in a negotiation moves | the existing 008 and 011 suites, unchanged and passing | whole suite |
| AC-10 no listing changes | `unreadable.mkv` on `/Items`, `/Items/{itemId}` and `/Items/Latest` before and **after a negotiation of a different item**, byte for byte — and the flags asserted as the account's own rather than as `true`, on two seats, which is what 008's policy-gate fix made them and what the amended AC-10 no longer contradicts (D-5) | conformance |

**AC-5 is the criterion most likely to be proved by a test that proves less than its name**, which
is what 008 T14, 009 T14, 010 T15 and 011 T12 each found in their closing task. Asked against
`unreadable.mkv` and a profile that plays nothing, the two answers are identical — both refuse —
and the test would pass while asserting nothing. It is therefore written against a source the
profile *can* direct-play, where the switches change the answer, and the criterion's own wording
("answers something different from the first answer") is asserted as a difference between two
recorded bodies rather than as a property of one.

**Conformance levels (spec §6).** The two negotiation rows are L3, which means the differential
harness 010 built, which means rows in two files:

* `docs/compatibility/request-cases.yaml` — four new cases under
  `POST /Items/{itemId}/PlaybackInfo`: `protocol-in-an-unexpected-case`,
  `protocol-that-binds-to-nothing`, `protocol-by-ordinal`, and
  `a-source-the-world-never-opened` (anchored on the fixture item, both identities);
* `docs/compatibility/named-comparisons.yaml` — two rows a sweep cannot raise:
  `uninspectable-source-address`, because the reference's address names `live.m3u8` and answers
  `500` where v1's names `master.m3u8` ([behaviours §3.13](../../docs/compatibility/behaviours.md)),
  and `on-demand-probe-heals-the-listing`, because the comparison is *two requests and their
  order*, which the engine compares one response at a time.

Both L2 rows (the listing, and the inspection an on-demand probe writes) are the fixture read
twice, in `tests/conformance/`, needing no reference.

**One test that is not about this feature and belongs to it anyway**: a unit assertion that
`unopened()`'s result never reaches `store()` — the §5 invariant, asserted by making the wrong call
fail rather than by trusting a docstring. 011 T12's finding was a contract stated in a plan, obeyed
nowhere, and asserted about the wrong function.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The trigger is implemented as "this part has no inspection" | **High** — it is the shape of the bug and the shape of the gate's fixture | A second part probed the reference never opens; an inspected-but-streamless file never re-probed | `videoless.mkv` and the two-part fixture in §8. Neither can pass under the naive trigger |
| A transient inspection is stored | Medium — `store()` and `unopened()` are one line apart | An unreadable file looks inspected for ever, and the listing gets worse: AC-10 fails silently, and a rescan is the only cure | §5 invariant 1, asserted by a test; `store()` takes `MediaInspection` from `opened()` only |
| The probe blocks the event loop | Medium — `inspect()` is sync and the call site is not | Every request in the process waits behind one file, for up to a minute | `asyncio.to_thread`, and a test that asserts the route yields (a slow stub prober and a second request answered while it runs) |
| AC-5's test asserts nothing | **High** — see §8 | A criterion that reads as proven and is not | The case is named in §8 and the assertion compares two bodies |
| The generalised binder makes a `400` into a `200` where the reference refuses | Medium | Five vocabularies answering `200` to a value the reference rejects — parity lost in the name of parity | The default clause is gated on a registered default (`@wire_default`), which only `StreamProtocol` carries; the other five keep their refusal, asserted per enumeration |
| A bool binds as the ordinal `1` | Medium — `isinstance(True, int)` | `true` answers HLS where the reference answers `400` | The bool clause is first, and it has a test of its own |
| The JSON-path key changes an existing refusal | Low | 007's and 009's measured bodies break | The path is built only for a location more than one level deep; every existing case is one level deep |
| The write races the scan | Low | Two writers to one row | `put` replaces; the scan's own change detection re-reads the file next time either way |

## 10. Alternatives considered

**Answer an un-inspected source with every flag `false` instead of opening the file.** The spec
weighed and rejected it (§3.2): it is the refusal rung 4 already specifies, for a source the server
could have played, and it is a delta from a reference that would have played it. The measurement
removed its only argument — the cost is a fifth of a second, bounded by one file read.

**Probe on the listing path too, so a listing is never empty.** This is the cure both client traces
proposed and it is the one the measurement withdrew: the reference's listing answers the same empty
source Atrium's does (OQ-3), so probing there would be a delta invented to fix a symptom that is
parity. What closes the music client's half is the negotiation's write, which every listing then
reads.

**Cache the failure, so an unreadable file is not re-probed on every negotiation.** Rejected as a
divergence measured in the wrong direction: the reference pays it every time (0.18–0.20 s, three
runs), a client that fixes its file expects the next negotiation to notice, and the only thing a
negative cache buys is CPU on a library nobody can play. If it is ever wanted, it wants a
`behaviours §6` non-improvement entry, not a plan section.

**Keep `protocol` a string and compare it case-insensitively.** One line, closes AC-7's first half,
and leaves three of the four classes wrong: no default for an empty string, no ordinals, and no
refusal for a word — which is three `200`s where the reference answers a default, a member and a
`400`. It also leaves the client's own spelling in `TranscodingSubProtocol`, which is the second of
the two defects the spec counts.

**Fix the five vocabularies one at a time, as 011 T9 fixed its own.** That is what 011 T9
deliberately did *not* do — it fixed the vocabulary it added and pointed here — and doing it five
times would put one question about the reference's binder in five places, which is the shape
`SUBTITLE_METHOD_ORDINALS`' own comment argues against.

**Put the resolution in `media/`.** It writes, and `media/` imports no `db`. The alternative is
handing `media/` a repository, which makes the one pure module in the project take a session.

## 11. The decisions this plan reserves, and the one already taken

Reserved rather than taken, because each changes something outside this feature's own files.
**Two were taken on 2026-09-03** — D-2 at this plan's drafting and D-5 at its gate — and both are
recorded below with the rest.

### D-1 — the healed item's `ETag`

`item_sources.(size, mtime_ns)` is 003's row and this feature does not write it, so a file whose
bytes changed after the scan is healed in `Size`, `RunTimeTicks`, `Bitrate` and `MediaStreams` and
keeps the `ETag` of the bytes the scan saw. The reference's on-demand path is a full refresh and
updates its own signal.

*Options:* (a) write `(size, mtime_ns)` from the same `stat()` the inspection already read — one
more line, a second 003-owned table written from a request, and the `ETag` matches the bytes;
(b) leave it, and record the difference in `behaviours §5` with a rescan as its closing mechanism.

*Recommendation:* (a), with §6.8's item 6 measured first — the `ETag` before and after a healed
negotiation on the reference is one probe run, and it decides whether (a) is parity or an
improvement.

### D-2 — the item-level `RunTimeTicks`, which is not this feature's

Measured in this repository on 2026-09-03 (§4): after a real scan, `items.runtime_ticks` is `NULL`
on every file-backed item, because the metadata merge refuses `Field.RUNTIME` for exactly those
types on the grounds that the value comes from probing the file — and nothing writes it from a
probe. Every film, episode and track a real Atrium serves therefore answers `RunTimeTicks: null` at
item level while its media source carries the value, and 007's `PlayedPercentage` is `null` with it.

*Options:* (a) a defect fixed in its owning feature (004's merge rule and 003's scan, or 008's
inspection write), specified there and out of 012; (b) folded into this feature, because this
feature is where an inspection is written from a second place.

*Recommendation:* (a). It is a scan-time defect that predates this feature and would be a defect if
this feature were never built; folding it in would make 012's diff the place a reader has to look
for why a film has a runtime.

**Taken on 2026-09-03: (a) — out of 012.** The finding is recorded here, in
[specs/README](../README.md) and in [AGENTS.md](../../AGENTS.md)'s register so it cannot be lost
with this branch, and it is specified and fixed in its owning feature rather than here. Nothing in
this plan depends on the outcome: 012 writes a probe row, and what reads `items.runtime_ticks` is
the same before and after.

### D-3 — the inspection timeout on a request path

`media/probe.py` bounds an inspection at 60 s for both callers; the reference bounds its probe only
by the request's cancellation token.

*Options:* (a) one timeout, unchanged — a file that takes longer is answered as un-inspectable
where the reference keeps reading; (b) a shorter deadline for the request path, which invents a
refusal the reference has not got and a knob nobody has measured a need for.

*Recommendation:* (a).

### D-4 — whether §6.8's six owed measurements are this feature's or its first task's

Four of the six are one run of an extended `tools/probe_uninspected_source.py` — the audio
refusal's body, the nested refusal's message, the `GET` route's probe, and the `ETag` before and
after a heal; the other two need something the probe's fixture has not got (a multi-part item, and
two requests at once).

*Options:* (a) extend the probe at T1, before any behaviour is written, as 011 did with its
sidecar fixture; (b) let each task measure what it needs, as 008 did.

*Recommendation:* (a) for the four, because three of them are inputs to code written in T2 and T4
rather than checks on it; (b) for concurrency, which is a property of the finished thing.

### D-5 — AC-10's second clause, which its own subject has outrun

Added by this plan and not by the spec's gate, because what makes it wrong landed after the spec was
accepted (§6.2). AC-10 says a listed source's capability flags *"stay `true`: they are not a
negotiation and nothing decides them"*; since 008's policy-gate fix on 2026-09-02 the account's
permissions decide two of the three, on both servers, measured.

*Options:* (a) amend the accepted spec — AC-10 keeps its prohibition (*nothing this feature does
changes what a listing answers*) and drops the clause about which values those are, which is 008's
to state and does state; (b) leave the criterion and let its test assert the code, which is how a
criterion comes to mean whatever passes.

*Recommendation:* (a), in the same change that lands the AC-10 test — the pattern
[010 took at D-6 and D-7](../010-conformance-harness/plan.md), where an accepted criterion was
amended rather than reinterpreted.

**Taken on 2026-09-03: (a), and taken here rather than at the test.** The spec moves in this same
change — earlier than the recommendation asked, because a criterion nobody can write a test for is
a criterion the task list would have to work around, and the task list is the next artefact. AC-10
keeps its prohibition and loses the clause naming the values; the front matter records why, and
that the three `true`s §3.1 and §3.2 report are an administrator's. **No code changes with it**:
008's policy-gate fix had already implemented the rule the clause denied.

## 12. What moves with the code

Documentation moves in the commit that changes the behaviour, not after it (Principle III).

| Document | Change | With which task |
|---|---|---|
| [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1), the never-opened-source row | Struck: the gap closes. Its "Atrium does" half becomes the behaviour, and its closing mechanism was already corrected at 012's gate | The task that lands §6.2 |
| [behaviours §2.23](../../docs/compatibility/behaviours.md) | "Atrium does" stops saying *"until it lands"* | The same |
| [behaviours §2.24](../../docs/compatibility/behaviours.md) | "Atrium does" stops being a promise | The task that lands §6.5 and §6.7 |
| [008 plan §6.1](../008-playback-negotiation-and-delivery/plan.md#61-inspection-and-the-cache) | The "not at request time" sentence gains this feature's exception | The task that lands §6.2 |
| `MediaProbeRepository`'s docstring | "Two readers rather than one" gains the writer | The same |
| [surface.yaml](../../docs/compatibility/surface.yaml) | **Nothing.** No route enters or leaves v1 (spec §7.2) | — |
| [request-cases.yaml](../../docs/compatibility/request-cases.yaml), [named-comparisons.yaml](../../docs/compatibility/named-comparisons.yaml) | Four cases, two comparisons (§8) | The task that lands the L3 half |
| [008 plan §7](../008-playback-negotiation-and-delivery/plan.md), the *"never inline"* failure row | The same exception as §6.1's | The same |
| [012 §5 AC-10](spec.md#5-acceptance-criteria) | **Amended, D-5, in this same change**: the prohibition stands, the clause naming the flags' values goes to 008 | Done |
| [specs/README](../README.md) status table, [roadmap](../../docs/roadmap.md) | 012's plan row, and then its task row | This plan's acceptance, and the list's |
