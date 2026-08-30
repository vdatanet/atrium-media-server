---
feature: 011-subtitle-delivery
title: Subtitle delivery — implementation plan
status: Accepted
created: 2026-08-29
updated: 2026-08-30
accepted: 2026-08-30
amended: 2026-08-30 at the tasks gate — four things this plan could not have known or did not check. §6.5's "the variant line gains the group" was written while the master answered one variant and 008's T15 amended that the same day, so the group goes through `_variant` and every entrance carries it. §6.1's "lookup on the codec spelling" reads a spelling `media/probe.py` does not store: the reference renames four subtitle codecs inside its own probe normalisation, `dvd_subtitle` contains no `dvdsub`, and applied to ffprobe's own name the rule answers *text* for every DVD and DVB subtitle track there is — so the rename moves to inspection and migration 0007 rewrites the four values. §8's embedded image subtitle track cannot be encoded by ffmpeg at all, and the fixture writes a PGS bitstream itself. And §6.2's "eight regional rows" are nine, two of which are not regional tags; and 2026-08-30 by T1 — §8's hand-written bitstream is four display sets rather than two at the same 434 bytes, and building it found two hazards the plan states now rather than letting a later task meet them: a subtitle input that does not start at zero is rebased onto its own start time and costs the text track beside it every cue but the first, and `-shortest` lets a subtitle track bound the whole file
spec_status_required: Accepted
spec_status_actual: Accepted
---

# 011 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour, and it was measured
> before this plan started: all twelve of its open questions are answered by five probes that now
> exist in `tools/`, and four of them died. Where this plan states a reference behaviour, the
> citation lives in the spec section it names, or inline where this plan read something the spec
> did not.

## 1. Approach

Six decisions carry the feature. Four of them are the gate's four dead questions turned into
code, and the other two are what the measurement left for a plan to settle.

**Two of the four owed stream properties are facts and move into inspection; the other two are
answers and stay in the ladder.** OQ-2 moved work *out* of this feature: `IsTextSubtitleStream`
and `SupportsExternalStream` are on every bare read of the reference, so they belong in
`media/info.py` beside the thirty-odd properties 008 already emits, derived from the stored codec
by a lookup. `DeliveryMethod` and `DeliveryUrl` are per-negotiation and belong in
`media/decision.py` beside the ladder that produces them. The split is not stylistic: a property
emitted from the wrong side is either missing on a listing or invented on one, and 008's
`media/info.py` docstring already names all four as one group owed to "the feature that serves
them". They are two groups.

**The manifest has one lever and it is the delivery address, so the client-side track override is
the feature rather than a line inside it.** The master playlist route does not bind
`EnableSubtitlesInManifest` and must not start
`[probe: tools/probe_subtitle_manifest.py, Jellyfin 10.11.11, 2026-08-29]`; what makes it announce
anything is `SubtitleMethod=Hls` beside a `SubtitleStreamIndex` in the query string. So
`api/dynamic_hls.py` grows two bound parameters and `media/hls.py` grows the `#EXT-X-MEDIA` block
and the variant line's group, and every other route in 008's HLS trio is untouched. AC-6 — a
master playlist byte-identical to today's for any request that does not name the method — is a
property of that shape rather than a test that has to be defended: nothing else in the rendering
path moves, and `_forwarded()` already sends the query string as bytes that arrived, so a
parameter this server now binds still reaches a client's playlist in the client's own spelling.

**A subtitle file beside the media renumbers the source, so the wire index is derived and never
stored.** The reference adds external streams first, numbers them from zero, and renumbers the
container's own streams after them
`[source: MediaBrowser.Providers/MediaInfo/FFProbeVideoInfo.cs:200-215 @ v10.11.11]`. That makes
a stream index mean two things — the number a client sends, and the number `ffmpeg -map` takes —
and 008 has one number today. This plan stores neither wire index: `media_streams.stream_index`
stays the demuxer's own index inside the file it came from, a new table stores the discovered
files in their own order, and a pure function in `domain/media.py` composes the two into the wire
numbering **at the repository boundary and nowhere else**. `-map` then reads a different field
from the same record. Nothing can go stale, because nothing is written down twice.

**Burn-in is a word this server says and never a filter it runs.** `Encode` is the reference's
per-stream answer for every track no declared profile fits — every image track under a text
profile, every track for a profile that declares nothing (spec §3.3) — so answering it is parity,
not a shortfall. `media/decision.py` reproduces the four-step ladder that ends in it and
`media/ffmpeg.py` gains no subtitle filter, no `-vf subtitles=`, no second filter path. A client
that selects such a track and plays it gets what it gets today, which is
[behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s burn-in row
unchanged.

**Cues are a pure core; ffmpeg only ever makes a file readable.** Parsing, windowing, rebasing and
writing are pure functions over a cue list in `media/subtitles.py`, which is what makes spec §6's
"asserted cue by cue" a table test rather than a server test. The one thing ffmpeg does is turn a
track into a file this server can read — extracting an embedded one, or normalising a text format
the parsers do not cover, which is the reference's own fallback chain
`[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:195-254 @ v10.11.11]`. It runs
through 008's `ProductionLedger` because every process this server starts does, and it lands in
`cache/` keyed on the file's change signal — **not** in a `TranscodeSession`: a subtitle has no
play session, no ping timer, no throttle and no segment deletion, and giving it one would grow a
second lifecycle for something that finishes in a second and is worth keeping across a restart.

**The manifest's `NAME` is the reference's own invariant assembly.** OQ-4 is resolved in the spec
— write the invariant form, record the divergence — and what a plan owes is *which* invariant
form. It is not an approximation this project invents: the five flag words and the undefined
marker are string literals in the reference's own source, used whenever the localised properties
are empty `[source: MediaBrowser.Model/Entities/MediaStream.cs:390-465 @ v10.11.11]`. Only the
language name is a choice, and §6.4 takes it and states what it costs.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–008 | [008 plan §2](../008-playback-negotiation-and-delivery/plan.md#2-inherited-decisions) |
| The decision ladder is pure and lives in one module; delivery routes consume a `Decision` | [008 plan §1](../008-playback-negotiation-and-delivery/plan.md#1-approach) |
| Inspection happens at scan time and lands in the database, streams as rows | 008 plan §1, §6.1 |
| Probe rows are keyed `(library_id, relative_path)`, never by an absolute path | 008 plan §4 (T2) |
| Every ffmpeg the server starts is owned by exactly one `ProductionLedger` entry, with its `stderr` drained | 008 plan §5, §6.7 |
| A derived artefact of a file is cached under a digest of its inputs and published by rename | [006 plan §6](../006-images/plan.md), `images/cache.py` |
| `api/` is one module per Jellyfin controller | [architecture §1](../../docs/architecture.md#1-shape-of-the-system) |
| The four error shapes, and which layer decides which | behaviours §1.11, `compat/errors.py` |
| An unrecognised query **value** is ignored, not refused; parameter **names** match case-insensitively | behaviours §1.12, §1.15 |
| The culture table `/Localization/Cultures` serves is generated, not hand-edited | `metadata/cultures.py`, `tools/generate_cultures.py` |
| Repositories return domain objects; no ORM row crosses the boundary | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |
| Never copy Jellyfin's code — parsers, writers and command lines included | Principle IV |

**Deviations:** none. The two divergences this feature ships are behaviours entries rather than
architectural deviations: [§3.12](../../docs/compatibility/behaviours.md#312-a-subtitle-playlists-window-durations-are-written-in-the-servers-locale--class-b-diverged)
(the invariant decimal point, spec AC-16) and the `NAME` attribute of §6.4, which lives in
behaviours §5's localised-properties row.

## 3. Modules

```
src/atrium/
├── library/
│   ├── walker.py         grows a third output: every file carrying one of the nine subtitle
│   │                     extensions, statted like a candidate, still reported as skipped
│   └── naming/
│       └── external.py   pure: what a filename beside a media file says — language, the
│                         three flags, and the title made of what nothing claimed
├── media/
│   ├── probe.py          grows inspect_subtitle(path): a sidecar's own streams, so `.sub`
│   │                     and `.mks` are decided by the demuxer rather than by an extension
│   ├── info.py           emits IsTextSubtitleStream, SupportsExternalStream, DeliveryUrl,
│   │                     DeliveryMethod, IsExternalUrl and Path, in the pinned order
│   ├── names.py          pure: the invariant display title (§6.4) — the one string this
│   │                     feature writes that 008 decided not to emit
│   ├── subtitles.py      pure: the cue list, three readers, five writers, the window filter
│   ├── extract.py        making a track readable: a sidecar read as it is, an embedded one
│   │                     extracted, a format the parsers miss normalised — via the ledger
│   ├── decision.py       grows SubtitleProfile, the per-stream method ladder, and the
│   │                     selection rule that answers "no default"
│   ├── urls.py           grows SubtitleStreamIndex, SubtitleMethod and the unreadable
│   │                     EnableSubtitlesInManifest, at their three measured positions
│   └── hls.py            grows the #EXT-X-MEDIA block, the variant line's group, and the
│                         subtitle playlist's own rendering
├── api/
│   ├── media_info.py     binds SubtitleProfiles; annotates the subtitle half of a source
│   ├── delivery.py       `video_parameters` grows the two subtitle parameters
│   ├── dynamic_hls.py    master.m3u8 announces; main.m3u8 and the segments do not move
│   └── subtitles.py      SubtitleController: the three routes of surface.yaml §8.1
├── compat/
│   └── errors.py         two classes for shapes it already renders (§7)
└── db/
    ├── models.py         MediaExternalStreamRow
    ├── repositories.py   MediaProbeRepository grows the external half and the renumbering
    └── migrations/versions/0007_external_subtitle_streams.py
```

**`api/subtitles.py` is one module for three routes that do not share a credential rule**, which
is the reference's own arrangement: `SubtitleController` carries `[Authorize]` on the playlist
action alone and declares nothing on the two fetch actions
`[source: Jellyfin.Api/Controllers/SubtitleController.cs:208, 338-345 @ v10.11.11]`, measured as
an empty `401` on the first and a `200` with the cues on the other two (spec §3.5). Keeping the
controller mapping mechanical is what has kept the surface audit mechanical since 002, and the
split inside it is the same split `api/delivery.py` already holds for the four `stream` routes.

**`library/naming/external.py` is beside the other naming rules and not in `media/`**, because it
is a question about a filename and every filename question in this project is answered in that
package (003, 004). It is also where the culture table is reachable from without `media/`
importing `metadata/`.

**`media/subtitles.py` and `media/extract.py` are separate modules on purpose.** One is pure and
one starts processes, and 008's shape is what made its pure half table-testable while its impure
half needed a ledger. A single module would make the cue tests need a scratch directory.

## 4. Data model

Migration `0007_external_subtitle_streams`, reversible (drop the table). It carries one data
change beside the new table: the four subtitle codec spellings of §6.1 are rewritten in
`media_streams`, because a row a 008 scan stored holds ffprobe's own name and the media file's
change signal will never move to trigger a re-inspection.

**`media_external_streams`** — one row per subtitle stream found in a file beside the media:

| Column | Meaning |
|---|---|
| `library_id`, `relative_path` (FK → `media_probes`, cascade) | The **media** file the sidecar belongs to, keyed the way `media_streams` is keyed |
| `ordinal` (PK with the two above) | Position among this media file's discovered streams. This is what decides the wire index, and it is the only ordering there is |
| `external_path` | The subtitle file, relative to the library root — never absolute, for the reason 008 T2 gives: a remount must change nothing |
| `size`, `mtime_ns` | **The sidecar's own change signal**, and the reason AC-11 is reachable at all (§6.2) |
| `stream_index` | The demuxer's index **inside the sidecar**. Zero for a plain `.srt`; a `.mks` can hold several |
| `codec`, `language`, `title`, `is_default`, `is_forced`, `is_hearing_impaired` | The merged answer: what the demuxer said about the sidecar, with the filename's flags OR-ed over it (§6.2) |
| `probed_at` | When the sidecar was inspected. Required and read back, for the reason `media_probes.probed_at` is |

**`ordinal` exists to serve a query pattern rather than a fact**, and it is the column a later
reader will try to normalise away: the fact is a set of files, and the ordinal is the position
that turns that set into stream indices. It is written by the scan in sorted order of
`external_path` and read back by the renumbering; deleting it and sorting at read time would work
until two files sorted differently under two collations, and a stream index that moves between
reads is a delivery address that names two tracks.

**`put_external` replaces the whole set for one media file**, exactly as 008's `put` replaces
stream rows rather than merging them, and for a sharper version of the same reason: a merge would
leave a row for a file that is gone, at an ordinal that shifts every index after it — which is
AC-12 failing in the least visible way available.

**Nothing else changes shape.** `media_streams` gains no column: the demuxer index it stores is
already the right number for `-map`, and the wire index is derived. `media_probes` gains no
column either — the sidecar signal lives per row in the new table, because the question "has this
file's set of sidecars changed" is answered by comparing that set, not by one timestamp.

**No index beyond the primary key.** Every read is `(library_id, relative_path)` for one item's
files, which is the primary key's own prefix.

## 5. Contracts

**`domain/media.py`** — `InspectedStream` gains two fields and the class gains one function:

```python
@dataclass(frozen=True, slots=True)
class InspectedStream:
    index: int                      # the WIRE index: what a client sends, what a URL carries
    file_index: int                 # the demuxer index inside the file this stream came from
    external_path: str | None = None    # the sidecar it came from, or None for the container
    ...                             # everything 008 declared, unchanged

def renumber(
    container: Sequence[InspectedStream], externals: Sequence[InspectedStream]
) -> tuple[InspectedStream, ...]
    # externals first at 0 … k-1 in ordinal order, then the container's own at k + file_index
```

**The two numbers are the whole of the answer to "what stops an index meaning two things".**
`index` is only ever a wire number: it is what `MediaStream.Index` emits, what
`AudioStreamIndex`/`SubtitleStreamIndex` carry, what a `#EXT-X-MEDIA` address names, and what
`decide()` matches a requested track against. `file_index` is only ever an ffmpeg number:
`media/ffmpeg.py` maps `0:{stream.file_index}` and nothing else may read it. Neither is stored in
the other's role — `media_streams.stream_index` is a `file_index` and `media_external_streams`
has no wire column at all — so `renumber` is the only place the two meet, it is pure, and it runs
at the repository boundary on every read. This is the same discipline 008 used for the two frame
rates (`narrow_to_single` versus `as_single`), and for the same reason: two derivations of one
number eventually disagree, so there is one.

`MediaInspection.streams` therefore stays a single wire-ordered tuple and every 008 reader —
`has_subtitles`, `item_streams`, `source_of`, `_audio_stream`, `default_stream_indexes` — keeps
working unchanged, now over a list that includes the discovered files. That is AC-11's
`HasSubtitles` and AC-1's stream properties arriving without a caller being told about them.

**`media/decision.py`** — the negotiation's subtitle half, pure like the rest of it:

```python
class SubtitleMethod(Enum):        # the reference's five members, its own spellings
    ENCODE = "Encode"; EMBED = "Embed"; EXTERNAL = "External"; HLS = "Hls"; DROP = "Drop"

@dataclass(frozen=True)
class SubtitleProfile:             # one entry of a device profile's SubtitleProfiles
    format: str | None
    method: SubtitleMethod
    language: str | None = None    # a CSV list; empty admits every language
    container: str | None = None   # only Embed reads it

@dataclass(frozen=True)
class SubtitleAnswer:
    index: int                     # the wire index of the stream this is about
    method: SubtitleMethod
    format: str | None             # the profile's format, or the stream's codec on Encode

def subtitle_answers(
    source, profiles, *, outcome, container, sub_protocol
) -> tuple[SubtitleAnswer, ...]    # one per subtitle stream, in stream order
```

`Decision` gains `subtitles: tuple[SubtitleAnswer, ...]` and `subtitle_index: int | None`.

Callers may assume: there is an answer for **every** subtitle stream and not only for the
selected one (spec §3.2, measured); the answer is `ENCODE` wherever nothing declared fits, which
is most of a real track list under a text-only profile; `subtitle_index` is the index the request
named, restated even when it names no stream, and `None` when the request named none — v1
proposes no default, which is §6.3's scope answer and not a shortfall.

**`media/names.py`** — pure:

```python
def display_title(stream: InspectedStream, culture: CultureIndex) -> str
```

The invariant assembly of §6.4. Takes the culture index rather than importing
`metadata/cultures.py` directly, so the table is an argument in a table test.

**`media/subtitles.py`** — pure:

```python
@dataclass(frozen=True, slots=True)
class Cue:
    identifier: str
    text: str
    start_ticks: int
    end_ticks: int

READABLE = ("srt", "subrip", "vtt", "webvtt", "ass", "ssa")   # what parse() covers
WRITABLE = ("srt", "subrip", "vtt", "webvtt", "ass", "ssa", "json", "js", "ttml")

def parse(text: str, source_format: str) -> tuple[Cue, ...]
def window(cues, *, start_ticks: int, end_ticks: int, copy_timestamps: bool) -> tuple[Cue, ...]
def render(cues, target_format: str, *, add_vtt_time_map: bool = False) -> bytes
```

The **label** is not here: `media/labels.py` already holds this project's one extension → media
type table, and it gains the subtitle rows rather than growing a second table beside it (§6.8).

`render` answers **bytes** and not a string, because the byte order mark is part of the measured
answer and dropping it is what the time-map switch does (§6.7).

**`media/extract.py`** — the one impure module:

```python
async def readable(
    ledger: ffmpeg.ProductionLedger, cache: Path, file: DeliveredFile,
    inspection: MediaInspection, stream: InspectedStream,
) -> tuple[str, str]               # (the cue text, the format it is in)
```

Callers may assume: the answer is cached under a digest of the media file's `(library_id,
relative_path, size, mtime_ns)`, the stream's wire index and the format, so a second call runs no
process (AC-14); a concurrent call for the same key waits on the first rather than starting a
second ffmpeg (§6.7); an image track raises before any process starts; and every process it does
start is in the ledger, which `tests/unit/test_import_directions.py` already sweeps for.

**`media/hls.py`** — two additions, both pure:

```python
@dataclass(frozen=True, slots=True)
class AnnouncedSubtitle:
    index: int; name: str; language: str; is_forced: bool; is_default: bool; uri: str

def subtitle_uri(media_source_id: str | None, index: int, token: str | None) -> str
def subtitle_playlist(runtime_ticks: int, segment_seconds: int, token: str | None) -> str
```

and `master_playlist` gains `subtitles: Sequence[AnnouncedSubtitle] = ()`.

**`MediaProbeRepository`** gains `put_external(library_id, relative_path, streams)` and returns
renumbered inspections from `get` and `current` — the existing two readers, unchanged in
signature. A caller cannot obtain an un-renumbered inspection, which is the point.

## 6. Algorithms

### 6.1 The two file facts (extends 008 §6.1)

`IsTextSubtitleStream` is a **lookup on the codec spelling, not an inspection**: everything counts
as text except a codec containing `pgs`, `dvdsub` or `dvbsub`, or spelled exactly `sup` or `sub`
— with `microdvd` exempted from the whole rule, because that text format shares the `.sub`
extension with an image one `[source: MediaBrowser.Model/Entities/MediaStream.cs:751-761 @
v10.11.11]`. A stream with no codec at all is text only when it came from a file beside the media
`[source: MediaBrowser.Model/Entities/MediaStream.cs:639-654 @ v10.11.11]`. Both live in
`media/info.py` as functions of the stored row, so no column is needed for either.

**But the spelling that lookup reads is not the one `media/probe.py` stores, and the tasks gate
corrected this paragraph on 2026-08-30.** The reference renames four subtitle codecs *inside* its
own probe normalisation, before any consumer sees them — `dvb_subtitle`→`DVBSUB`,
`dvb_teletext`→`DVBTXT`, `dvd_subtitle`→`DVDSUB`, `hdmv_pgs_subtitle`→`PGSSUB` `[source:
MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:632-652, 765-768 @ v10.11.11]` — and
`"dvd_subtitle"` contains no `dvdsub`. Applied to ffprobe's own `codec_name`, the rule answers
*text* for every DVD and DVB subtitle track there is, which is AC-1 and AC-7 failing together on
any real library. The renamed spelling is also what `MediaStream.Codec` carries on the wire —
`PGSSUB`, `DVDSUB` and `DVBTXT` all appear beside `subrip`, `ass` and `webvtt` `[probe: manual
requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]` — so this is a property **008
already emits differently**, invisible until now because no fixture had a subtitle stream. The
rename therefore goes in `media/probe.py`, where the reference puts it and where one spelling then
reaches `media/info.py`, `media/decision.py` and `media/extract.py` alike; a rename applied only
at emission would leave the negotiation's `SupportsFormat` comparing a spelling no profile
declares. Migration 0007 rewrites the four values in `media_streams`, because a stored row from a
008 scan otherwise keeps a spelling the wire disagrees with and its media file's change signal
will never move.

`SupportsExternalStream` is `is_external or is_text_subtitle or is_pgs`, where PGS is a codec
containing `pgs` or spelled `sup` `[source:
Emby.Server.Implementations/Library/MediaSourceManager.cs:112-129,
MediaBrowser.Model/Entities/MediaStream.cs:765-771 @ v10.11.11]`. It is answered
for subtitle streams and left at the model's `false` for everything else, which is what the
reference's own two call sites do.

**`Score` is emitted by nothing.** The reference sets it only for the streams a user's subtitle
*mode* selected, and a mode of `None` sets none at all `[source:
Emby.Server.Implementations/Library/MediaStreamSelector.cs:97-152 @ v10.11.11]`. v1 keeps no
subtitle mode, so no stream is scored and the property falls to the global null suppression —
which is the same answer a `SubtitleMode: None` user gets from the reference, and the accepted gap
behaviours §5 now records.

**`Path` arrives with the discovered files and only with them.** It is the sidecar's absolute
path, rebuilt from the library root the way `api/item_dto.py` and `api/media_info.py` rebuild a
source's `Path`, and it is null on a container stream. Everything this section adds goes in the
pinned document's order, and the order is kind: `Score`, `IsExternal`, `DeliveryMethod`,
`DeliveryUrl`, `IsExternalUrl`, `IsTextSubtitleStream`, `SupportsExternalStream` and `Path` are
one contiguous run between `Index` and `PixelFormat` `[spec: MediaStream]`, with the one 008
already emits — `IsExternal` — sitting inside it. That is one edit to the model rather than
seven insertions, and the PascalCase sweep covers the new fields by construction.

### 6.2 Discovery, the name rule, and the two numberings (extends 003 §6.4 and 008 §6.1)

**The walk collects sidecars, and it costs nothing extra.** `library/walker.py` already stats
every file under every root and already reports a `.srt` as skipped with `Skip.EXTENSION`. It
gains a third output — every file whose extension is one of the nine the reference admits
(`.ass`, `.mks`, `.sami`, `.smi`, `.srt`, `.ssa`, `.sub`, `.sup`, `.vtt`) `[source:
Emby.Naming/Common/NamingOptions.cs:163-174 @ v10.11.11]` — with its relative path, size and
modification time, subject to the same pruning as everything else. **It stays in `skipped` as
well**, because the scan report counts files that produced no item and a subtitle produces none;
moving it would change an operator-facing number for no reason.

**The claim rule is a stem match and a right-to-left read**, reproduced in
`library/naming/external.py` from the behaviour rather than transliterated from the parser
`[source: Emby.Naming/ExternalFiles/ExternalPathParser.cs @ v10.11.11]`, and already reproduced
once against six items in directories of up to 259 files
`[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-29]`:

1. The filename without its extension must **begin with** the media file's own name without its
   extension, case-insensitively, and then either stop or continue with a `.`.
2. What follows is read one dot-delimited token at a time **from the right**. A token *containing*
   `default` sets the default flag; a token containing `foreign` or `forced` sets the forced flag;
   a token the culture table recognises sets the language, but only the first one; a token equal
   to `cc`, `hi` or `sdh` sets the hearing-impaired flag. Anything nothing claimed is prepended to
   the title.
3. **`hi` is Hindi first and a flag second**, and the resolution has a branch that is easy to miss.
   The language lookup runs before the hearing-impaired vocabulary, so `film.hi.srt` is Hindi. But
   when the language already claimed is `hin` and a *further* token also resolves to a language,
   that token wins the language **and** the hearing-impaired flag is set — so `film.spa.hi.srt`,
   read right to left, is Spanish and hearing-impaired. Both halves are reproduced, because a rule
   that made `hi` a flag outright would mislabel every Hindi sidecar in a library. This branch is
   **read, not measured**: the probe's own reproduction does not carry it and the library it ran
   against has no filename that reaches it (§6.8).
4. The language written down is the culture row's `Name` when it contains a `-` and its
   terminological three-letter code otherwise. `metadata/cultures.py` already carries all four
   fields for all 192 rows, so this is a lookup and not a new table — and the lookup itself is the
   reference's: a token matches a row's display name, its name, either three-letter code or the
   two-letter code, case-insensitively, first row in the table wins `[source:
   Emby.Server.Implementations/Localization/LocalizationManager.cs:172-199 @ v10.11.11]`.
   **This step said "the eight regional rows, `zh-hk` and its siblings" and the tasks gate
   corrected it**: **nine** of the 192 names contain a dash, and two of them are not regional tags
   at all — `Greek, Modern (1453-)` and `Luba-Katanga`, in this repository's generated table and
   in what `/Localization/Cultures` serves alike. A Greek sidecar's language is therefore written
   `Greek, Modern (1453-)` rather than `ell`, which is the reference's own answer and a row of the
   filename matrix rather than a footnote.

Note the asymmetry in step 2 and reproduce it: the default and forced vocabularies match by
**containment** and the hearing-impaired one matches by **equality**. It is not a tidiness
question — `film.forcedspanish.srt` is forced on the reference and `film.hix.srt` is not
hearing-impaired.

**Each claimed file is then inspected**, because its codec decides whether it is text at all and
the extension does not: `.sub` is `microdvd` or `dvd_subtitle` depending on the bytes, and that is
exactly the split §6.1 turns on. `media/probe.inspect_subtitle` runs the same prober 008 already
supervises and takes **every** subtitle stream the file holds, which is one for an `.srt` and
possibly several for an `.mks`. The filename's flags are OR-ed over the demuxer's — the reference
keeps a forced flag the file itself carries even when the name does not say so `[source:
MediaBrowser.Providers/MediaInfo/MediaInfoResolver.cs:117-125 @ v10.11.11]` — and the title from
the name replaces the file's own.

**Discovered files are ordered by `external_path`, and that is a decision rather than a copy.**
The reference's order is its directory enumeration's, which is the filesystem's; the probe's
reproduction sorted by name and matched on every item, so sorted order is what was measured, and
it is the only order that gives the same stream indices twice. An index that depends on a
filesystem's enumeration order is a delivery address that means different things on two servers
and, after a `mv`, on one.

**Sidecar discovery runs on its own change signal, and this is the trap the feature would
otherwise fall into.** Dropping an `.srt` beside a film changes nothing about the film's own
`(size, mtime_ns)`, so 008's `MediaProbeRepository.current` still answers "unchanged" and
`_inspect_media` skips the file — and AC-11 and AC-12 would both fail on a default scan while
every test that forced a deep scan passed. This is
[behaviours §5.6](../../docs/compatibility/behaviours.md)'s replaced-poster shape, one feature
later. So `library/scan.py` gains a second comparison beside the first: for each candidate, the
set of `(external_path, size, mtime_ns)` the walk found beside it is compared with the set stored
in `media_external_streams`, and the sidecars are re-inspected when the two differ — **whatever
the media file's own signal says**. The two are independent: a changed film re-inspects the film,
a changed sidecar set re-inspects the sidecars, and a deep scan does both.

**And the renumbering happens in exactly one place.** `MediaProbeRepository.get` and `.current`
read both tables and hand the result to `domain.media.renumber`, which puts the externals at
0…k-1 in ordinal order and the container's own at `k + file_index`. Nothing upstream of the
repository sees a wire index and nothing downstream sees anything else. The consequence AC-12
names — removing the file renumbers the remaining streams back — is then arithmetic and not a
cleanup path, because there was never a stored number to correct.

**An address minted before a rescan names a different track after one.** That is true of the
reference for the same reason, and it is not something this feature can fix without inventing a
stable per-stream identifier the reference has not got. It is recorded here rather than in
behaviours because it is a property of the reference's own model, not a divergence.

### 6.3 The negotiation's subtitle half (extends 008 §6.2 and §6.3)

**The posted index is read only where the body also names this source.** `api/media_info.py`
already has that rule and already applies it to `AudioStreamIndex` — `_switches(...,
names_this_source=...)` — so `subtitle_stream_index` joins it in the same gate, which is the
measured behaviour (spec §3.3) reached by adding a field rather than a branch. An index naming no
stream is not an error: it is restated as `DefaultSubtitleStreamIndex` and written into the
address, measured.

**`DeviceProfileDto` gains `SubtitleProfiles`**, the fifth list it narrows to, and
`profile_of()` maps it. 008's comment on that model — "v1 negotiates nothing about subtitles, and
a field bound here would be a field somebody later assumes is honoured" — is discharged in the
same edit.

**The method ladder is the reference's, four steps and a fallback**, reproduced in
`media/decision.py` `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1442-1590 @ v10.11.11]`:

1. When the stream is **not** external, and not (the play method is transcode **and** the
   sub-protocol is HLS): look for an `Embed` profile whose language matches, whose container list
   admits the output container, whose kind matches the stream's, and whose format equals the
   stream's codec. Under a transcode the output container must also be one embedding is supported
   for, which is `mkv`/`matroska` and nothing else — `ts`, `mpegts` and `mp4` are refused by name.
2. The same pass again, accepting any format the stream can be converted to.
3. An `External` or `Hls` profile whose language matches and whose format **equals** the stream's
   codec. `Hls` is skipped entirely unless the play method is transcode, which is the mechanical
   reason a direct-played source announces nothing — and the two methods gate on kind
   differently: `External` wants the profile's format to be the same kind as the stream, so an
   image track can match an image-format external profile, while `Hls` wants the stream to be
   text and does not look at the profile's format at all.
4. The same pass accepting conversion, which additionally requires the stream to be text, to
   support being served alone, and to be convertible to the profile's format.
5. Otherwise `Encode`, with the format set to the stream's own codec.

Two details that look like they can be skipped and cannot. **Convertibility is not "text":** a
track already in `ass` or `ssa` cannot be converted *from*, and `ass`/`ssa` cannot be converted
*to* `[source: MediaBrowser.Model/Entities/MediaStream.cs:773-805 @ v10.11.11]` — so an `ass`
track under a `vtt`-only external profile answers `Encode`, and that is a real row of a real track
list. And **the transcoder gate is a constant.** The reference asks whether it can extract a
codec and the answer is unconditionally `true` `[source:
MediaBrowser.MediaEncoding/Encoder/MediaEncoder.cs:1331-1335 @ v10.11.11]`, so it is not
reproduced as a branch; a branch there would be a refusal the reference never makes.

`SupportsLanguage` is the CSV containment `media/decision.py` already implements for containers,
with an empty list admitting everything and an absent stream language read as `und` `[source:
MediaBrowser.Model/Dlna/SubtitleProfile.cs:48-61 @ v10.11.11]`.

**`DeliveryUrl` is emitted only for `External`**, and it names `GetSubtitleWithTicks` — the third
route of §8.1, and the reason it is in the surface at all:
`/Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/{startPositionTicks}/Stream.{format}` with
`?ApiKey=` appended `[source: MediaBrowser.Model/Dlna/StreamInfo.cs:1252-1272 @ v10.11.11]`. The
start position is `0` for every request this feature can produce: it is non-zero only where the
play method is transcode and timestamps are not being copied, and the negotiation writes the
address before any of that applies to a selected track. `IsExternalUrl` is `false` on every one of
them, because the alternative branch serves a remote file and v1 has no remote sources.

**No default is proposed.** With no index named, `subtitle_index` is `None` and
`DefaultSubtitleStreamIndex` is absent — which is the reference's own answer for a
`SubtitleMode: None` user, and is a scope answer rather than an algorithm: the score exists, it is
reproducible from six of a stream's own properties, and it is *never taken* — it is read only to
detect a tie, and the tie-break and the fallback are both functions of two per-user settings §2
excludes (spec §3.3, OQ-12). Implementing the score without the settings would compute a number
nothing reads.

**`media/urls.py` gains three parameters at three measured positions** `[source:
MediaBrowser.Model/Dlna/StreamInfo.cs:960-963, 1067-1070, 1111-1114 @ v10.11.11]`:

* `SubtitleStreamIndex` immediately after `AudioStreamIndex`, written when an index was selected,
  the method is not `External`, and the index is not `-1`;
* `EnableSubtitlesInManifest` immediately after `TranscodingMaxAudioChannels` and before
  `RequireAvc`, written as .NET's `True` when the transcoding profile declares it — **the
  parameter the route it addresses cannot read**, reproduced because a client that parses this URL
  is the reason OQ-8 made it exact, and because writing it costs one bound boolean;
* `SubtitleMethod` immediately after `Tag` and before the source-codec triplet, written when an
  index was selected and the method is not `External`.

`SubtitleCodec` — the reference's fourth, written only for `Embed` with a declared codec list —
is not written, because `TranscodingProfileDto` binds no subtitle codec list and 011 embeds nothing.
Recorded in §6.8 rather than left silent.

### 6.4 The name, and what it costs 008 (OQ-4)

The `NAME` attribute is the stream's display title, assembled in `media/names.py` in the
reference's own order and joined with ` - ` `[source:
MediaBrowser.Model/Entities/MediaStream.cs:390-465 @ v10.11.11]`:

the **language name** (or the undefined marker when the stream states no language), then a
hearing-impaired word if the flag is set, a default word if it is set, a forced word if it is set,
the **codec upper-cased**, and an external word if the stream came from a file. When the stream
has a title of its own, the title leads and each of those attributes is appended only if the title
does not already contain it as a case-insensitive substring.

**The five words and the undefined marker are not an approximation.** They are the literals the
reference itself writes whenever the localised properties are empty — `Hearing Impaired`,
`Default`, `Forced`, `External`, `Und` — in that same source. Atrium writes exactly those, so
everything in the string but the language name is parity rather than a decision.

**The language name is the one piece that is not, and it is the only invention available.** The
reference reads the *platform's* culture data in the server's interface culture: `Español` on a
Spanish host, `Spanish` on an English one. Atrium has one language table, the generated
`metadata/cultures.py`, and its display name for that row is `Spanish; Castilian` — the ISO 639-2
English name, which is what `/Localization/Cultures` serves on both servers. **This plan writes
that table's display name, first letter upper-cased, and writes the raw language tag when no row
matches**, which is the reference's own fallback. It does not ship a second language table: a
table of CLDR English names cannot be generated from anything in this repository, and 004 T15 is
the record of what happens when a plan names a source for a table without checking that the source
produces the reference's rows.

**What that costs is precise and worth writing down.** On a language whose ISO name carries an
alternate spelling the announced name differs from an English-configured reference's by that
alternate — `Spanish; Castilian - Forced - SUBRIP` where the reference writes `Spanish - Forced -
SUBRIP` — and from a Spanish-configured one by the whole string, which is the divergence §3.2
accepted on the argument that `NAME` is a label a person reads and `LANGUAGE`, `FORCED`, `DEFAULT`
and `URI` are byte-identical.

**And it costs 008 an argument, not a decision.** 008 §3.1 withheld `DisplayTitle` because "an
English approximation would differ from the reference on every track rather than be missing on
it", and that reasoning still holds for the property: `MediaStream.DisplayTitle` stays absent,
because a JSON property can be, and an absent property is a smaller lie than a wrong one. A
manifest attribute cannot be absent — `NAME` is required — so the same string is now written in
one place and withheld in another, and 008's argument no longer applies uniformly. The asymmetry
is the honest form of the answer and it is recorded in behaviours §5's localised-properties row,
whose closing mechanism is unchanged: when the two localisations arrive, they close the row and
make `NAME` exact in the same change.

### 6.5 The manifest (extends 008 §6.4)

`api/delivery.video_parameters` gains `subtitleStreamIndex: int | None` and `subtitleMethod: str |
None`. **Neither carries a validation pattern**, because an unrecognised value must be ignored
rather than refused (behaviours §1.12): `SubtitleMethod=banana` is no method at all, not a `400`.
The value is matched against the five members case-insensitively, which is what the framework on
the other side does for an enum-typed query parameter.

**`EnableSubtitlesInManifest` is deliberately not bound.** The route does not accept it, measured,
and an unbound parameter is ignored on both servers — so not binding it is both the parity answer
and the cheapest way to hold AC-6's third case.

`api/dynamic_hls.py`'s master route then, and only when `subtitleMethod` is `Hls` and the source
has at least one text subtitle stream, builds one `AnnouncedSubtitle` per **text** subtitle stream
of the source — in stream order, whatever the selection was — and passes them to
`hls.master_playlist`. `media/hls.py` renders, verbatim `[source:
Jellyfin.Api/Helpers/DynamicHlsHelper.cs:596-632 @ v10.11.11]`,
`[probe: tools/probe_subtitle_manifest.py, Jellyfin 10.11.11, 2026-08-29]`:

```
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="…",DEFAULT=…,FORCED=…,AUTOSELECT=YES,URI="…",LANGUAGE="…"
```

with the attributes in that order, the group literally `subs`, `AUTOSELECT=YES` always,
`DEFAULT=YES` on the stream whose index equals the selected one and `NO` on every other,
`FORCED` from the stream's own flag, `LANGUAGE` falling back to the literal `Unknown`, and the
lines emitted **before** the first `#EXT-X-STREAM-INF` line.

**Every variant line gains `,SUBTITLES="subs"` last, after the frame rate — and this paragraph
said "the variant line" until the tasks gate corrected it on 2026-08-30.** It was written while
`master_playlist` answered exactly one variant, and 008's own T15 amended that on the same day:
an HDR source whose video is stream-copied is now offered an h264 SDR entrance beside the copy,
so the master carries two `#EXT-X-STREAM-INF` lines. The reference passes its subtitle group to
**every** playlist line it appends — the copy, the two codec entrances, the h264 entrance, the
level-5.0 rewrite and both adaptive-bitrate variants `[source:
Jellyfin.Api/Helpers/DynamicHlsHelper.cs:213-315, 325-345 @ v10.11.11]`, confirmed on the wire
against an HDR film negotiated for a copy: three variants, all three ending `,SUBTITLES="subs"`
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`. The group therefore
belongs to `_variant`, which is the one function both lines already go through, rather than to the
first line's construction — and a group on one variant only would take subtitles away from
exactly the client the entrance exists for.

**The filter is on the stream kind and not on the selection**, which AC-7 turns on: selecting an
image track still announces every text track, with `DEFAULT=NO` on all of them, because no
announced stream matches the selected index. Written as "compare the indices" rather than as
"mark the selected one", the branch falls out instead of being a case.

The address is `{mediaSourceId}/Subtitles/{index}/subtitles.m3u8?SegmentLength=30&ApiKey={token}`,
relative to the master playlist's own directory, with the **hard-coded** thirty and the caller's
own token — the token is load-bearing, because the route it addresses requires a caller and a
player following a `URI` out of a manifest sends no headers of its own. `mediaSourceId` is the
request's, written the way the reference writes it: a master playlist asked for without that
parameter announces the reference's own broken address, and it is unreachable from any address a
negotiation produces, so AC-8's traversal starts from a negotiated one. If a client is ever
measured sending it, that is a behaviours §3.0 defect decision and not a silent improvement here.

### 6.6 The playlist route

`GET /Videos/{itemId}/{mediaSourceId}/Subtitles/{index}/subtitles.m3u8`, in `api/subtitles.py`,
requiring a caller and resolving the item **through 005's visibility query** — the same
`ItemQueryRepository` path `api/media_info.py` uses — because the reference resolves it with the
user and answers a problem-details `404`, which is `NotFoundError` here. That is the one route in
this feature with a user, and the reason its refusals are the negotiation's shapes rather than the
delivery routes'.

`segmentLength` is a **required** query parameter, so an absent or unparseable one is the
framework's problem details naming it. A parsed value of zero or less, and a source whose runtime
is zero or less, are both the controller refusal at `400`.

The rendering is `hls.subtitle_playlist`, pure, and it is **not** `hls.media_playlist`: the two
have different header orders and different entry shapes, and sharing them would be a refactor that
makes one of them wrong `[source: Jellyfin.Api/Controllers/SubtitleController.cs:370-409 @
v10.11.11]`:

```
#EXTM3U
#EXT-X-TARGETDURATION:{segmentLength}
#EXT-X-VERSION:3
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:{seconds},
stream.vtt?CopyTimestamps=true&AddVttTimeMap=true&StartPositionTicks={a}&EndPositionTicks={b}&ApiKey={token}
…
#EXT-X-ENDLIST
```

Windows are laid from zero in `segmentLength`-second steps until the runtime is covered; the last
one is the remainder, and its end position is clamped to the runtime. **`#EXTINF` is written
with a decimal point**, always — the divergence of behaviours §3.12 and AC-16 — while a whole
window is written the way the reference writes it, `30` and not `30.0`, so the divergence is
visible on the last window and nowhere else.

**The route never reads the index it is given**, which is measured and reproduced: a playlist for
a stream that does not exist is a `200` listing every window, each of which answers `500`. It is
reproduced rather than improved because the whole surface of this feature is a client following
addresses it was handed, and a `404` here would refuse a request the reference serves. AC-8's
traversal is what catches the failure that matters — a playlist that is well formed and leads
nowhere — and it does it by following the addresses rather than by reading the playlist.

The entries name a **lower-case** `stream.vtt` where the route is declared `Stream.{format}`, so
both spellings must answer. `compat/routing.py`'s table already canonicalises a path
case-insensitively for every route in this project, so this is a property to assert rather than a
mechanism to add — and asserting it is AC-8's traversal doing its job.

### 6.7 The fetch routes: readable, converted, windowed

`GET …/Subtitles/{index}/Stream.{format}` and its ticks-in-path form share one handler, as the
reference's do, with the path's start position taking the place of the query's. **Neither
requires a caller** — measured `200` with no credential at all — so both resolve the item
through `MediaFileRepository` by identifier alone, exactly as 008's four `stream` routes do,
and neither applies a visibility predicate. Both accept the token in the query string, which is
how the addresses in §6.5 and §6.6 work at all.

`js` is an alias for `json`, mapped before anything else. A format outside the writable set is the
controller refusal at `400`, decided before any file is opened.

**The writable set is the reference's own six and not the five that were measured.** The probe
asked for `vtt`, `srt`, `ass`, `ssa`, `json` and `js` and got them, and asked for `xyz` and got
the refusal; it never asked for `ttml`, which the reference also writes `[source:
MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:259-302 @ v10.11.11]`. Leaving it out
would answer `400` where the reference answers `200`, on a request no analysed client sends but
any client may — a refusal invented rather than reproduced, which is the shape 008's own gate
struck twice. It is written, and it is one more row the format battery owes (§6.8).

**Making the track readable** is `media/extract.py`, and it is the reference's own chain:

* an **external** stream whose format the parsers cover is read from its own file, with its
  encoding detected rather than assumed — a subtitle file is the one input in this project that is
  routinely not UTF-8;
* an **embedded** stream, or an external `.mks`, is extracted by one ffmpeg invocation to `srt`
  (or to its own spelling where the codec is `ass` or `ssa`), which is the reference's rule
  `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:458-470 @ v10.11.11]`;
* an external stream in a text format the parsers do not cover is normalised to `srt` by one
  ffmpeg invocation, which is the reference's fallback for the same case;
* an **image** stream raises before any of that. The reference attempts the extraction and refuses
  about twenty seconds later with `400`; Atrium answers the same status and the same twenty-five
  bytes without starting a process. The only difference is latency, which is the shape 008's OQ-9
  already accepted — the same answer, byte for byte, sooner.

The produced text lands in `cache/subtitles/<digest>.<format>`, the digest over the media file's
`(library_id, relative_path, size, mtime_ns)`, the stream's wire index and the extracted format,
written to a temporary name and published by rename — `images/cache.py`'s shape, chosen over 008's
scratch root because an extracted subtitle is a derived artefact of a file rather than of a
session, and because clearing it at every startup would re-run ffmpeg for every restart. It is not
a `TranscodeSession`: no ping timer, no throttle, no segment deletion, no reap. **It is still in
the ledger**, because every process this server starts is, and because a client that opens a
playlist of a hundred windows fetches them in bursts: `readable` holds a per-digest lock so the
hundredth request waits on the first extraction instead of starting a hundredth ffmpeg. That
burst is the failure mode the image cache never faces and the reason the lock is specified here
rather than left to be discovered under load.

**Conversion, windowing and rendering** are then pure:

1. If the requested format equals the format the readable file is in, **the file's bytes are
   answered verbatim** — the window and both switches are ignored. That is the reference's own
   short circuit `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:145-155 @
   v10.11.11]`, and §6.8 records that it contradicts AC-10 read literally.
2. Otherwise parse, then filter: **skip** cues from the front while either end sits before the
   start position, then, when an end position above zero was given, **take** cues from the front
   while their start is at or before it. Both are prefix operations rather than predicates, so a
   cue list with an overlap keeps everything after the first match — reproduced as written,
   because a `filter` here answers a different set of cues on a real file.
3. When timestamps are not being copied, subtract the start position from both ends of every
   surviving cue. When they are, leave them: a cue 36.1 s into the file comes back at 6.1 s in a
   window starting at 30 s without the switch, and at 36.1 s with it (OQ-11, measured).
4. Render. `srt`, `vtt`, `ass` and `ssa` carry a UTF-8 byte order mark and `json` does not,
   because the reference's writers use a stream writer that emits the preamble and its JSON writer
   does not `[source: MediaBrowser.MediaEncoding/Subtitles/SrtWriter.cs,
   MediaBrowser.MediaEncoding/Subtitles/JsonWriter.cs @ v10.11.11]`.
5. With `AddVttTimeMap` on a `vtt` answer, replace the leading `WEBVTT` with
   `WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000` and write the result **without** a
   byte order mark — the drop is not a tidy-up, it is what re-encoding the rebuilt body does on
   the reference and it is measured.

Neither route answers `Accept-Ranges`; both state a `Content-Length`. That is the same shape 008
T14 measured on the two HLS playlists, and the response is built header by header for the reason
008 §6.5 gives: the convenient file response ships an `ETag` and a `Content-Disposition` the
reference does not send.

### 6.8 What no probe here has measured, and what stays owed

Every §3 claim this plan builds on was measured on 2026-08-29 by the five probes the gate wrote.
What follows is what this plan read rather than measured, or found and could not act on. Each is
owed a row in the task list, and the first two are corrections to the accepted spec rather than
gaps in it.

* **The same-format short circuit contradicts AC-10 as written.** A windowed fetch whose requested
  format equals the format the track is already in answers the **whole track**, unwindowed and
  unrebased, because the reference returns the readable file's bytes before it parses anything
  `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:144-155 @ v10.11.11]`. It is
  unreachable from a manifest — the playlist always names `stream.vtt` and an extracted track is
  `srt` or `ass` — and it is one request away by hand: `Stream.srt?StartPositionTicks=…` on a
  subrip track. AC-10's "a windowed fetch answers the cues of that window and no others" is true
  of every window a client reaches by following an address and false of that one. **The amendment
  is the user's to take**, at the tasks gate, because the spec is accepted and this is a reading
  rather than a measurement; the probe that settles it is one row in
  `tools/probe_subtitle_delivery.py`'s format battery.
* **The playlist route's malformed-identifier row names the wrong parameter.** Spec §3.7 says both
  routes answer problem details naming `routeItemId`; the probe measured only the fetch route
  (`tools/probe_subtitle_delivery.py`, the `malformed identifier, fetch` case), and the playlist
  route declares its path parameter as `itemId` `[source:
  Jellyfin.Api/Controllers/SubtitleController.cs:338-345 @ v10.11.11]`, so its refusal names
  `itemId`. The implementation follows the declaration, which is what `surface.yaml` already
  carries, and the row is owed a measurement and a correction.
* **A source with no runtime has no row in §3.7.** The reference raises on its own argument check,
  which is the controller refusal at `400` — the same shape and status as a zero window length
  `[source: Jellyfin.Api/Controllers/SubtitleController.cs:355-368,
  Jellyfin.Api/Middleware/ExceptionMiddleware.cs:123-136 @ v10.11.11]`. The probe's own source
  selection excludes it deliberately, so this is a reading; it is in §7 and owed a probe row.
* **The lower-case spelling of `SubtitleMethod` is unmeasured**, and it is the same class as the
  finding §2.1 hands on about `"Hls"` versus `"hls"` in a delivery address. This plan matches the
  five members case-insensitively, which is what an enum-typed parameter does on the other side;
  one probe row settles it either way.
* **`ttml` is written and has never been asked for**, which is the row above seen from the probe's
  side: the format battery covers six spellings and the reference's writer table has a seventh
  (§6.7). One row settles it.
* **The `hin` branch of the sidecar name rule is read, not measured.** A second language token
  behind a first that resolved to Hindi takes the language and sets the hearing-impaired flag
  `[source: Emby.Naming/ExternalFiles/ExternalPathParser.cs @ v10.11.11]`; the gate's own
  reproduction does not carry the branch and the library it ran against has no filename that
  reaches it, so the probe passed without exercising it (§6.2).
* **The fetch formats' media types are read, not measured**, and they land as new rows in
  `media/labels.py`'s existing table. `text/x-ssa` for `ass` and `ssa` is explicit `[source:
  MediaBrowser.Model/Net/MimeTypes.cs:82-83 @ v10.11.11]`; `text/vtt`, `application/x-subrip` and
  `application/json` come from the third-party table the reference's own falls through to, which
  is not a file this project can cite. The subtitle playlist's label is the `m3u8` row that table
  already has. The probe prints the `Content-Type` of every format it fetches, so the task that
  lands the route reads them off a run rather than off this paragraph.
* **`SubtitleCodec` is not written into a delivery address.** The reference writes it for an
  `Embed` method with a declared codec list, and v1 embeds nothing and binds no such list. It is a
  missing parameter on a branch v1 cannot reach, recorded so it is not mistaken for an oversight.
* **The reference looks in one more place than this feature can reach**: the item's own internal
  metadata directory, where it puts a subtitle it downloaded or extracted `[source:
  MediaBrowser.Providers/MediaInfo/MediaInfoResolver.cs:216-226 @ v10.11.11]`. No route exposes
  it, v1 neither downloads nor stores extracted subtitles beside the media, and the discovered set
  is therefore a lower bound on a reference server that has used the feature 011 excludes.
* **The order the work is worth doing in does not depend on the one open question.** Spec §7.2
  leaves it to the video client's author whether it fetches a whole-file subtitle when the
  manifest carries none, and says the answer changes the ordering. It does not change *this*
  ordering: the manifest addresses the playlist and the playlist addresses the fetch route, so the
  fetch route is a prerequisite of a manifest that leads anywhere and lands first either way. What
  the answer changes is whether the fetch route is *useful* before the manifest lands — and if it
  is, the intermediate state is a working subtitle for one client rather than a dead end, which is
  a reason to keep the routes in separate tasks rather than to reorder them.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Playlist route, item unknown or invisible | 005's visibility query returns nothing | `404`, problem details — the negotiation's shape, not the delivery routes' (measured) | — |
| Playlist route, `segmentLength` absent or unparseable | Framework binding of a required parameter | `400`, problem details naming `segmentLength` (measured) | — |
| Playlist route, `segmentLength` ≤ 0 | Route guard | `400`, `text/plain`, the fixed 25 bytes (measured) | — |
| Playlist route, source runtime ≤ 0 | Route guard, before laying windows | The same `400`. ⚠️ Read, not measured (§6.8) | Rescan |
| Playlist route, index names no stream | **Not detected** — the route never reads it | `200`, a full playlist whose every entry answers `500`. Reproduced (measured) | — |
| Either route, item id not an identifier | Path binding | `400`, problem details naming the route's own parameter — `routeItemId` on the fetch routes, `itemId` on the playlist (§6.8) | — |
| Either route, item id all zeros | Guard before the lookup | `400`, `text/plain` (measured) | — |
| Fetch route, item unknown | Lookup by identifier alone returns nothing | `400`, `text/plain` — an argument guard, not a miss, which is why it is not the `404` its sibling answers (measured) | — |
| Either route, `mediaSourceId` names no part | Compared against the item's derived source ids | `500`, `text/plain` (measured) | — |
| Fetch route, index names no stream, a non-subtitle stream, or is negative | Stream lookup returns nothing | `500`, `text/plain` (measured) | — |
| Fetch route, format outside the writable set | Checked before any file is opened | `400`, `text/plain` (measured) | — |
| Fetch route, index names an image subtitle | The text/image split of §6.1, before any process | `400`, `text/plain` — the reference's answer, without the twenty seconds (measured) | — |
| Fetch route, window end precedes its start | Not detected; the filter empties | `200`, a body with no cues (measured) | — |
| Extraction fails or ffmpeg is unavailable | Non-zero exit, or `ProberUnavailableError`'s sibling | `500`, `text/plain` — nothing could be produced, which is 008's own answer for that | Install ffmpeg |
| A sidecar the scan recorded is gone at fetch time | `stat` fails | The same `500` | Rescan |
| A sidecar cannot be inspected during a scan | Non-zero exit or parse failure | The file is skipped, the media file keeps its other streams, and the scan reports it the way 003 §3.7 reports an unexamined file | Next scan retries |
| A sidecar's text is not decodable in any encoding | Detection fails | The stream stays announced and the fetch answers `500`; a file nobody can read is not a reason to hide the track | Replace the file |
| The subtitle cache directory is unwritable | Write fails | `500`, and the failure is logged once as the operator's problem it is | Fix permissions |

## 8. Testing strategy

**The fixture matrix grows two entries and one file**, extending `tests/fixtures/media.py`'s
generated tree rather than adding a second world. One film carries an **embedded text** subtitle
track of a known, tiny cue list **beside an embedded image track**, which is one file giving the
whole of AC-1's text/image split, AC-7's filter and AC-3's `Encode`; a second carries a text track
in `ass`, the format that cannot be converted *from* and therefore the one that reaches `Encode`
under a `vtt`-only profile. The **sidecar** `.srt` goes beside the second, with a name that
exercises the right-to-left read — a language token, a forced token and an unclaimed token that
becomes the title.

**The image track cannot be encoded, and the tasks gate found that out by trying.** ffmpeg has no
Presentation Graphic Stream encoder at all, and its bitmap encoders refuse a text input outright —
*"Subtitle encoding currently only possible from text to text or bitmap to bitmap"* — so
`-c:s dvdsub` over the generated `.srt` fails and the matrix's generate-with-ffmpeg rule has
nothing to ask for. The entry therefore writes the **bitstream itself**: a 434-byte PGS of five
segment types, one 32×8 run-length object and **four display sets — one that draws the block and
one that erases it, for each of the two cues** (the gate's own sentence said two, which is half a
file; T1 reproduced the byte count exactly and counted the sets) — which demuxes as
`hdmv_pgs_subtitle` and muxes in with `-c:s copy` (measured at the gate, 2026-08-30, rebuilt by
T1 on the same day). It is still generated rather than checked in, which is the module's own rule,
and the entry carrying it is Matroska because mp4 accepts neither PGS nor DVD subtitles.

**Two things about muxing a subtitle track that T1 paid for, and that no later task should
rediscover.** Both are the class 008 T1 named — a muxer quietly not doing what it was asked — and
both are recorded in `tests/fixtures/media.py`'s own docstring:

* **A bitstream that does not start at zero moves, and takes a cue off the track beside it.**
  ffmpeg rebases each input on that input's own start time, so a PGS whose first display set sits
  at 0.5 s arrives 0.5 s early — every cue of it — and, under `-shortest`, the `subrip` track
  muxed beside it keeps only its first cue; at 1.0 s it keeps one of three. The symptom lands on
  the *other* track, which is why nothing downstream would have pointed at the bitstream. The
  writer refuses a late cue list rather than trusting a caller to remember.
* **`-shortest` means the shortest stream, and a subtitle track is one.** A four-second film whose
  cues stop at 3.0 s came out **3.007 s long**, video and audio truncated with them. The flag was
  belt-and-braces — both synthetic sources already carry an explicit duration — so it is simply
  dropped for an entry that declares a subtitle.

**The sidecar must not go beside a film 008's tests already assert about.** Placing it there
renumbers that film's streams, which is this feature working correctly and 008's `audioStreamIndex`
assertions failing for a reason that looks like a bug in the renumbering. It is the fixture trap
005 and 007 each met from the other direction, and the new entry exists to avoid it.

The cue list is small enough to assert in full, which is what spec §6 asks for, and everything is
generated with the same bit-exactness rule the rest of the matrix follows, so a rebuilt tree is the
same tree. Every subtitle test that mutates the world copies the file out first, as the existing
ones do.

**The pure core takes tables.** `library/naming/external.py` runs the filename matrix — a bare
stem, a stem with a dot suffix, each flag vocabulary, `hi` as Hindi, `hi` as a flag behind a
language, a token nothing claims, an extension outside the nine, and a stem that is a *prefix* of
another film's — asserting language, three flags and title (AC-11). `media/subtitles.py` runs the
cue matrix: parse each readable format, window with and without the copy switch, an end before a
start, the time-map rewrite and the byte order mark it drops, and every writer's output re-parsed
back to the same cues (AC-9, AC-10, AC-14). `media/names.py` runs the display-title matrix over
the six pieces and the title's substring suppression (§6.4). `media/decision.py` runs the method
ladder per profile class — embed, external, manifest, nothing declared, each crossed with
text/image and direct play/transcode — asserting one `SubtitleAnswer` per stream (AC-3).
`domain.media.renumber` runs its own table, and one of its cases is the property `-map` depends
on: **every container stream's `index` exceeds its `file_index` by exactly the number of external
streams**, and no external stream's `file_index` is ever read by a command. That is the assertion
that catches the whole class, and asserting only "the indices are contiguous" would not.

**The manifest is asserted as bytes, with `NAME` masked**, which is spec §6's own rule: a golden
per address class — the manifest method with a text index, with an image index, the external
method, the burn-in method, an index with no method, the manifest flag alone, and nothing at all —
where four of them must be **byte-identical to the master playlist the same request answers
today** (AC-6). Those four are the criterion that keeps 008 intact, and they are cheap: the golden
files already exist. A **ninth** class arrived with 008's own T15 and is the one this plan was
written before: the HDR fixture entry negotiated for a stream copy, whose master carries the copy
*and* the SDR entrance, where the assertion is that **both** variant lines end in the group
(§6.5). Two files differing only in colour are negotiated the same way and answer one variant and
two, which is already `tests/conformance/test_hls_playlists.py`'s shape.

**AC-8 is a traversal and not a comparison**, which is the sharpest thing the tasks inherit. One
conformance test negotiates against a profile declaring the manifest method, follows the
`TranscodingUrl`, parses the master playlist it answers, follows every `#EXT-X-MEDIA` `URI` as
written, parses the playlist each one answers, and follows every entry of those as written —
including the lower-case `stream.vtt` — asserting a `200` and a non-empty body at every hop. A
manifest and a playlist can both be well formed and lead nowhere, and only following them says so.

**The renumbering is proven by mutation**, in the shape 003's own AC-11 uses: scan, assert the
indices; place the sidecar, scan again, assert the discovered stream at 0 and the video and audio
moved by one and `HasSubtitles` true; remove it, scan again, assert every index back where it was
and the item's user data untouched (AC-11, AC-12). The middle scan is a **default** scan, not a
deep one, because that is the whole point of §6.2's second signal.

**Error paths are table-driven per route** over spec §3.7's fourteen rows plus §6.8's two readings
(AC-13), asserting status, content type and body bytes — the discipline behaviours §1.11 needs,
and the only way the two `200` rows read as deliberate rather than as a bug.

`surface.yaml` already carries the three routes against feature `011`, so
`test_no_route_ships_ahead_of_its_feature` fails from the first route until the last task adds
`"011"` to `IMPLEMENTED_FEATURES` — and the intermediate tasks use an explicit `INTERIM_011` list,
the device 002, 005, 006, 007 and 008 each used and each deleted. The suite still opens no TCP
connection: every reference measurement in this feature is a `tools/` probe.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The wire index and the ffmpeg index are confused somewhere | Medium | High — a delivery command maps the wrong track, silently, only on items that have a sidecar | Two named fields, one pure `renumber` at the repository boundary, and a unit test asserting the two differ wherever externals exist; `-map` has exactly one call site |
| Sidecar discovery runs behind the media file's change signal | Medium | High — AC-11 and AC-12 pass under a deep scan and fail for every real operator | The second signal is §6.2's own paragraph, and the mutation test scans **default** |
| Our parsers disagree with the reference's on a real file | Medium | Medium — cues shifted or dropped on formats the fixtures do not cover | Three readers only, ffmpeg normalises everything else — the reference's own fallback; cue-level assertions, never byte comparison |
| A playlist's hundred windows start a hundred extractions | Medium | High — one client stalls the machine | One cached artefact per (file, stream, format), a per-digest lock, and the ledger to see what is running |
| The subtitle cache grows without bound | Low | Low | One small text file per track, keyed on the file's change signal so a changed file replaces rather than adds; no knob, because the reference has none |
| `NAME` diverges more than §6.4 predicts | Medium | Low — a label, and no client branches on it | The differential masks the attribute and the golden pins the invariant form; the closing mechanism is behaviours §5's row |
| A sidecar in an unusual encoding is mis-decoded | Medium | Low | Encoding detection on external files only, which is where the reference does it; a file that cannot be decoded fails loudly rather than serving mojibake |
| The image-subtitle refusal is reached by a client that expected a wait | Low | Low | The status and the bytes are the reference's; only the latency differs, and it differs by being shorter |

## 10. Alternatives considered

**Storing the wire index.** One number per stream, no renumbering, no second table — and every
sidecar that appears or disappears rewrites every stream row of that file, which is a migration
of live data on a scan and a stored number that is wrong for the length of the write. Worse, it
puts the ffmpeg index nowhere: `-map` would have to subtract a count the row does not carry.
Rejected; the number that is derived is the one that cannot go stale.

**Putting the discovered streams in `media_streams`.** No new table, one query — and the primary
key is `(library_id, relative_path, stream_index)`, where a sidecar's own stream 0 collides with
the container's stream 0. Widening the key with a source-file column is the new table with extra
steps and a nullable column on every container row. Rejected.

**Deriving a sidecar's codec from its extension.** No ffprobe per sidecar, no process at scan
time — and `.sub` is a text format or an image one depending on the bytes, which is the exact
split every downstream decision turns on, and the reference inspects for that reason. A library
whose `.sub` files were guessed wrong announces image tracks as text and answers `400` to every
fetch of them. Rejected.

**Converting through ffmpeg on every fetch** instead of parsing cues. No parsers to write, no
writer set to maintain — and the window filter, the rebasing rule and the JSON form all need
cue-level access, spec §6 asks for cue-level assertions, and every window of every playlist would
be a process. Rejected; ffmpeg makes a file readable and nothing else.

**Giving extraction a `TranscodeSession`.** It would reuse 008's supervision whole — and it would
give a one-second job a ping timer, a throttle, a segment cleaner and a reap, none of which have
any meaning for a text file, and it would tie a cached artefact worth keeping to a scratch root
that is cleared at every startup. Rejected; the ledger is the part worth reusing and the session
is not.

**Announcing the manifest group when a profile asks for it**, as the spec's own opening draft read
the condition. The master playlist route does not bind the flag, measured — so this is not a
branch that was declined, it is a branch that does not exist. Rejected by the probe that killed
OQ-1.

**Improving the playlist route's unread index** into a `404`. More correct, and one line — and the
reference answers `200`, so a client that follows a manifest into a playlist it cannot use would
be refused by Atrium where it is served by the reference, which is Principle I exactly. Rejected;
AC-8's traversal is where that failure is caught, on the addresses rather than on the index.

**Shipping a table of English language names** to make `NAME` exact against an English-configured
reference. It is the only way to reach the reference's own string — and there is no source for it
in this repository, no way to generate one without the platform the reference reads, and 004 T15
is the record of a plan that named a source for a table without checking it produced the
reference's rows. Rejected in favour of the table that exists, with the cost stated (§6.4).

**Burning in.** Out by the roadmap since before 001, and the measurement did not reopen it: the
reference's `Encode` is a *statement about what would happen*, answered per stream at negotiation
for most of a real track list, and saying the same word costs a text-rendering stack and a second
filter path less than doing it. Rejected by spec §2 and confirmed by OQ-5.
