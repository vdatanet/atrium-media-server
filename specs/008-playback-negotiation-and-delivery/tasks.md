---
feature: 008-playback-negotiation-and-delivery
title: Playback negotiation and delivery — tasks
status: Implemented
created: 2026-08-29
updated: 2026-09-05
accepted: 2026-08-29
implemented: 2026-08-29
amended: 2026-08-29 by T3 — the `ETag` lead T2 carried forward was wrong in two ways, and four of the eight properties T3 emits had no registry entry to fill; and 2026-08-29 at the gate — the fixture world turned out to have no files behind any item, CI has no ffmpeg, the negotiation error table's first two rows are uncited, and the MediaSources emitters already exist as declared gaps; see "What the gate changed"; and 2026-08-29 by T4 — the empty profile answers the opposite of what this list said, the reasons are ordered by flag value and describe only why direct play failed, and the HDR rule the task asked for has no range type to condition on; and 2026-08-29 by T5 — a `POST` carrying no `DeviceProfile` is negotiated against the profile the *device* stored, so "no profile at all" is not a property of the body; the error table's two uncited rows hold as written; and the three playback permissions 002 moved into the enforced set on 2026-08-27 had never been read by anything; and 2026-08-29 by T6 — this list's "a tokenless request refuses" is the opposite of what the four `stream` routes do and of what 002 §3.1 had already recorded, so the credential decision lands as spec AC-32 and behaviours §2.10; the delivery routes' own refusal is behaviours §1.11's third shape rather than problem details; and the range matrix gained five rows the spec named and the probe had never sent; and 2026-08-29 by T7 — httpx's ASGI transport cannot drop a connection, so AC-26 needed a client written for it and the `TranscodeManager` this list names does not exist until T11; a `StreamPlan` states every ceiling and passing them all to the encoder is what breaks it; `StreamPlan` gained `bit_depth`; and the `mediaSourceId` `500` is decided as behaviours §3.9; and 2026-08-29 by T8 — the codec-less hole is not a codec-less transcoding profile but a streaming request inferring a codec from a path with no extension, so behaviours §3.8's divergence is narrower than it read; synthesising the device profile *exactly* as the reference does scopes its ceilings to the direct-play containers and would have honoured none of them; AC-19's bit-depth clause is a copy refusal rather than an output target; `transcodingProtocol` must not be typed; and this route's three refusals are none of the `stream` pair's; and 2026-08-29 by T9 — the two WAV prior-probe claims both moved when the battery was written: symptom 1 has two causes rather than one, and symptom 2 comes from the *transcoding* container, so AC-20's `Container=wav` named a request that answers mp3; a WAV states its length inside the body and cannot be produced to a pipe at all, so "a `Content-Length` computed from sample count" is a file's size instead; the wav container has to name its own codec, because the muxer accepts a FLAC stream and writes a real RIFF header over it; and behaviours §3.8's "with or without a `transcodingContainer`" is container-dependent; and 2026-08-29 by T10 — both of §3.7's cadence numbers were attributed to the wrong thing, and the fixture T1 built for this task answers 3.003 s rather than the 3.004 s this list told it to make a golden of: the scaling divides by the rate the request carries at 32-bit precision, and 6.0 s is the copy default's equal grid rather than the source's keyframes, which a copy follows only for a container the operator has permitted on-demand extraction for; the playlist routes require a token where the four `stream` routes require none; and the `/universal` HLS handoff this task was to land cannot be, because its master playlist names an audio `main.m3u8` that is on no surface; and 2026-08-29 by T11 — a segment's index is ffmpeg's `-start_number` and the URI's `runtimeTicks` is where production starts, so "restart at `plan_segments()[index]`" names the wrong number; the supervised set is two modules rather than three, because the manager starts everything through the ledger; a segment carries a `Last-Modified` where the progressive routes carry none; the reference states the scaled cadence only to its playlist and the unscaled integer to its encoder, which is behaviours §3.10; and the segment route's six refusals split across two shapes by where they happen; and 2026-08-29 by T12 — the stop route's key is the play session alone and the `deviceId` it requires decides nothing, so `stop(device_id, play_session_id)` would have leaked an encoder for every client that respells its device; the well-formed call does *not* remove the session's `TranscodingInfo`, which the spec had asserted in both directions and no probe had separated from the completion percentage going null; the kill timer is 60 000 ms because the job is not progressive, measured at 58 s and 60 s; and the unread `stderr` pipe T11 handed on had to be drained by block rather than by line, because `readline` gives up on an over-long line and stops reading; and 2026-08-29 by T13 — `SegmentKeepSeconds` is a distance behind the client rather than a file age, so this list's "aged produced segments" and AC-29's "older than the configured window" both named a rule the reference has not got: measured, segment 29 went and segment 33 stayed on one 720-second window, forty-five seconds after both were produced; the delivery half of the policy rule is per stream and reached only from a video request, so `/universal` consults no permission and `EnablePlaybackRemuxing` has no delivery-time reader at all; and the reference's own refusal beside the force-copy is unreachable, because the same permission has already rewritten the codec to a copy; and 2026-08-29 by T14 — the definition of done's "no other response differs observably from the measured reference" was false when it was written down: a progressive re-encode produced to a pipe loses the frame the container describes itself in, which is a fourth delivery divergence and is now recorded as behaviours §3.3's last paragraph. Two acceptance criteria were also wrong rather than merely unproven (AC-6, AC-11) and two were mapped to tests that proved less than their names — the advertised `Size` against the served bytes, and `audioStreamIndex` against the audio that came back; and 2026-08-30 by T15 — the list finished without ever reaching the master playlist's one conditional branch: an HDR stream copy is offered a standard-range entrance, and the probe that answered OQ-7 takes whatever video the library lists first and never asks what its range is. Two of the three measured variants are an operator's permissions rather than the reference's shape, the `hvc1` the audit read as a missing `dvh1` is parity (the tag is a muxer argument, not a playlist field), and the fixture matrix had no HDR source for the branch to be proven against — nor could it have had a Matroska one, because that muxer drops the transfer characteristics the whole answer turns on; and 2026-09-02 by the negotiation policy-gate fix — T5's route carried the all-three gate and not the rule beside it: with **no** `DeviceProfile` the reference reaches no stream builder to gate and reads one permission per media kind off the source instead, so a single denial is observable on the `GET` and on a bare `POST` where it is invisible against a profile. Implementing what the reported difference looked like would have answered `true` for a seat denied video transcoding alone. The named comparison's own delivery prediction was unreachable through the route it asks, `tools/_playback.py`'s picker measured 011's subtitle rule as a ladder finding, and the listing half of the same reference function is left to 005 as an accepted gap. See "Amended — 2026-09-02" under T5; and 2026-09-05 by the 2026-09-04 audit's corrective task C5 — spec §5 gains AC-33 and AC-34 for the two refusal tables that had a full battery of tests and no criterion, and AC-32's *"three delivery routes that refuse without a token"* becomes four: T11 added the segment route's table to §3.7 and extended nothing, so `FEATURE_008` named that route's test under a criterion whose text excluded it
plan_status_required: Accepted
plan_status_actual: Implemented
---

# 008 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries five structural decisions.** The world is built first: no fixture item in
this repository has ever had a file behind it (the query world is *a seeded database, not a
filesystem*, by its own docstring), and every delivery test needs bytes on disk that ffprobe and
ffmpeg can actually read — so T1 makes the synthetic media, the scanned world over it, and
teaches CI ffmpeg, before any code leans on any of them.

**Storage lands before semantics, and semantics are green before any route exists.** T2 is the
probe rows, T4 is the whole of [spec §3.3](spec.md#33-the-decision)'s ladder — the all-three
policy gate, the honoured and the ignored switch, the ceilings that clamp to the source — as
pure functions with a table-driven test, 007 T2's shape. The route tasks then prove *wiring*
once each rather than re-proving the ladder per route.

**The negotiation lands before any delivery, and static delivery before any produced output.**
T5's `PlaybackInfo` is what every delivery request means; T6's static path plus the range
matrix is delivery with no process behind it, which is where `compat/ranges.py` and the
`Content-Type`-label rule are proven before ffmpeg complicates anything. Produced output then
arrives in cost order: progressive (T7), the two audio specials (T8, T9), predicted playlists
(T10 — pure arithmetic, no process), and only then the one genuinely new mechanism, a
supervised encoder with an owner (T11), its lifecycle (T12) and its operator knobs (T13).

**Routes land across seven tasks, so the exact-set check carries an interim list.**
`test_no_route_ships_ahead_of_its_feature` asserts the served routes equal the surface of the
implemented features; T5 through T12 each add to an explicit `INTERIM_008` — the device 002,
005, 006 and 007 all used — and T14 deletes it by putting `"008"` in `IMPLEMENTED_FEATURES`.

**Every owed reading from [plan §6.8](plan.md#68-measured-at-the-gate-and-what-stays-owed) has
an owner here.** The `ETag` derivation is T3's, the cadence-rounding rule behind the measured
3.004 s is T10's, the kill-timer constants are T12's — discharged, and reading them found two
things beside the numbers: the stop route is keyed on the play session alone, and it does not
clear the session's `TranscodingInfo` — the per-route refusal shapes are measured
by the task that lands each route — folded into a probe battery, never left as a hand request
(the L2 fold's rule) — and the two `[prior-probe:]` WAV citations in behaviours §3.2 are
upgraded by T9, the task that implements what they describe.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files they
reference on 2026-08-29 before being accepted. Four things changed:

| The draft said | It was |
|---|---|
| Delivery tests run against the seeded query world | **The world has no files.** `tests/fixtures/query.py` opens with "a seeded database, not a filesystem": no item it creates has a path that exists on disk, so a delivery route handed any of its ids would 404 at the filesystem, not exercise delivery. The scan tests do use real paths — full of dummy bytes no demuxer can open. T1 therefore builds a second world: real synthetic media, scanned by the real pipeline, session-scoped so the encode cost is paid once |
| The suite gains transcode tests | **CI cannot run them.** No job in [`ci.yml`](../../.github/workflows/ci.yml) installs ffmpeg or ffprobe — nothing has needed either before. T1 adds the install to the suite jobs (both Python ends), and defines the `ffmpeg` marker so the handful of real-encode tests are one `-m` away from being skipped locally |
| A task adds `MediaSources` emission to the item DTO | **The emitters already exist as declared gaps.** `api/item_dto.py` registers `MediaSources` and `MediaStreams` as `lambda: None` with the comment "the 008 gap", and `NOT_IN_NOW_PLAYING` in `api/sessions.py` has carried `MediaSources` since 007 exactly so this feature cannot leak it into a session entry. T3 *fills* slots and rewrites goldens; it does not add fields — and the tripwire test it must not break already exists |
| The spec's negotiation error table is measured | **Its first two rows are not.** "Unknown or invisible item → `404`" and "Unauthenticated → `401`" carry no citation — the review that overturned the other two rows never measured these, because no open question named them. T5 measures both against the reference, folds them into `probe_playback_info.py` as a refusal battery, and the spec's table gains its citations in the same change |

And one thing the review confirmed rather than changed, worth a line because a task would
otherwise re-derive it: **multi-part films are already modelled.** `item_sources` stores one row
per part with the change signal on each (003), and [spec §3.1](spec.md#31-media-sources)'s "one
media source per part" is a join over what exists, not new schema — the probe table keys off the
same paths.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — The world gets files: synthetic media, a scanned world, and ffmpeg in CI

- [x] **Changes:** new `tests/fixtures/media.py` — a session-scoped builder that generates the
  plan §8 matrix into a cached directory with ffmpeg (seconds of colour bars and a tone):
  `mp4/h264+aac`, `mkv/h264+ac3`, `mkv/hevc+ac3` (the codec no browser profile accepts — forces
  step 3), one file whose video a common profile accepts beside an audio it rejects (AC-7's
  shape), a 96 kHz `flac` (AC-19's), and a two-part film (spec §3.1). A `scanned media world`
  fixture runs the real 003 scan over them. `pyproject.toml` declares the `ffmpeg` marker;
  `.github/workflows/ci.yml`'s suite jobs install ffmpeg; `conftest.py` skips marked tests with
  a message when the binary is absent rather than failing them.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_media_fixtures.py -q` — every generated file
  ffprobes to the codec/container/rate the matrix names it for (the fixture's invariant test,
  the 007 T4 pattern: the property asserted against the constant, not a number written twice);
  the scanned world contains one item per fixture film with the right type; and a run with the
  marker deselected (`-m "not ffmpeg"`) stays green, which is what proves the marker fences
  everything that needs the binary.
- **Spec reference:** §6 (fixtures); plan §8

**Done (2026-08-29).** Eight files, and the encoder produced every one of them first time. What did
not survive the measurement was the assumption underneath the word *cached*: that "generated by
ffmpeg" means "the same twice".

**The bit-exact flags have to sit on the output side of the command line, and only Matroska says
so.** Written where they read naturally — before the first `-i`, next to the `lavfi` inputs they
look like they belong to — `-fflags +bitexact` configures the *input* format context, and the
Matroska muxer goes on writing a random `SegmentUID` and a wall-clock `DateUTC`: two identical
invocations produced files differing in sixty bytes **at the same size**. The same size is what
makes it dangerous rather than untidy. 003's change signal is `(size, mtime_ns)`, so a cache
rebuilt after an ffmpeg upgrade — or by a second checkout racing the first — would have been
invisible to every staleness path T2 is about to write, while every content-derived value under it
moved, `ETag` included. Measured rather than reasoned, and the reasoning would have got it wrong:
the mp4 output of exactly the same mistake is byte-identical, so a matrix without a Matroska entry
would have "proved" determinism it did not have.

**Plan §8's matrix has six entries and the Changes above name five.** *A multi-keyframe file long
enough to segment* is in [plan §8](plan.md#8-testing-strategy) and dropped out of this task's list —
and T10's `plan_segments` asserts copy-bucket alignment "against fixture keyframes", of which there
would have been none: every other entry is four to six seconds with one keyframe at the start. It
is in the matrix as `long_take`, twelve seconds at 23.976 fps with a forced keyframe every two
(six of them, measured), the cadence [OQ-3](spec.md#resolved) took the reference's 3.004 s from. It
is also the only 720p source, so AC-9's "a 720p source under a 1080p ceiling" is that source rather
than a smaller one standing in for it.

**[`conformance.md`](../../docs/compatibility/conformance.md)'s L2 section already claimed this
existed.** It described the fixture library as "directory trees, `.nfo` sidecars, and tiny synthetic
media files generated by ffmpeg at build time" — while `tests/fixtures/library/generate.py` opens by
saying the opposite in its own words, *"these are not decodable media, and 003 has no use for one"*.
The document had been describing this task since before 003 was written. It now says there are two
fixture worlds and what each is for.

The music entry's directories are deliberately **not** its album and artist, which is what makes the
scanned world prove the scan opened the file: 003 T18's lesson is that an unexamined audio file
resolves from its path and hangs under an album named after its folder, so a fixture whose folders
agreed with its tags could not tell the two scans apart.

## T2 — Inspection lands in rows: `media/probe.py`, migration 0006, the repository

- [x] **Changes:** new `src/atrium/media/probe.py` — `inspect(path) -> MediaInspection`, the
  ffprobe invocation and parse ([plan §5](plan.md#5-contracts)), raising on an unreadable or
  unparseable file; new migration `0006_media_probes` with the two tables of
  [plan §4](plan.md#4-data-model) (`media_probes` keyed by path with the denormalised change
  signal and the keyframe list, `media_streams` with the condition columns); `db/models.py` and
  `db/repositories.py` grow `MediaProbeRepository` (`get`, `put`, staleness by `size`/
  `mtime_ns`), returning domain records per ADR-0003.
- **Depends on:** T1
- **Verified by:** `uv run pytest tests/unit/test_media_probe.py tests/unit/test_repositories.py -q`
  — each fixture file inspects to its known streams (marked `ffmpeg`); a text file raises; a
  round-trip through the repository preserves every column including the keyframe list; a
  changed `mtime_ns` reads back stale; and `alembic downgrade` of 0006 leaves the schema the
  0005 tests assert. The repository joins the no-ORM-escape sweep `tests/unit/test_repositories.py`
  runs over its `REPOSITORIES` tuple.
- **Spec reference:** §3.1; plan §4, §5

**Done (2026-08-29).** Two tables, forty-four columns, and the one column that cannot exist.

**`container` — "the resolved single container (`mp4`)" — is not a property of a file.**
Plan §4 asked for two container columns, a demuxer list and a resolved single form, and spec §3.1
said the single form was "only resolved against a profile". Measured across a real library, the
reference derives it **twice, differently, and once without a profile at all**: on a listing the
single form is the file's own *extension* where the stored list contains it — the same
`mov,mp4,m4a,3gp,3g2,mj2` answers `mp4` for a `.mp4` and `m4a` for a `.m4a` — and the list's first
member where it does not
`[source: Emby.Server.Implementations/Dto/DtoService.cs:320-353 @ v10.11.11]`; in a negotiation it
is the first member the profile accepts, and a profile-less negotiation passes the list through.
The same `.m4a` therefore answers `m4a` on `/Items` and the whole six-name list on `PlaybackInfo`
`[probe: tools/probe_media_container.py, Jellyfin 10.11.11, 2026-08-29]`. Stored, either answer
would have been wrong on the other route.

**And the half of that sentence nobody doubted was also wrong.** "Item-level `Container` is a
demuxer list, not a container" holds for the mp4 family and for nothing else: a `.mkv` answers
`mkv`, a `.flac` answers `flac`, because what the reference stores is a *normalised* string —
`matroska` renamed, `webm` dropped where the streams disqualify it — and not ffprobe's
`format_name`
`[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:124,270-315 @ v10.11.11]`.
Reproducing the sentence literally would have put `matroska,webm` on the wire for 702 of the
library's 1 200 items.

**The primary key moved from `path` to `(library_id, relative_path)`.** An absolute path would have
been the one key in this schema a remount invalidates: `library/identity.py` derives every
identifier from the path *relative* to its root, on purpose, so that moving a root changes nothing.
Keyed absolutely, a move would leave every item, favourite, image and resume position intact and
silently orphan every probe row.

**Three columns were missing from plan §4's list, each beside one it had.** `average_framerate` —
the reference carries two frame rates and they differ on variable-frame-rate content, so one column
could not emit both; `color_range`, beside the three other colour fields; `is_hearing_impaired`,
beside the two other disposition flags. Found in T3 instead, they would have cost migration 0007.

Measured rather than assumed, and the assumptions would have been wrong: a Matroska stream reports
**no bitrate at all** and no language tag where the same content in mp4 carries `und`; a flac track
states its bit depth in `bits_per_raw_sample` and zero in `bits_per_sample`; a file ffprobe opens
happily can have **no duration** (a still image); and **ffprobe 9.0.1 does not report `refs`** —
the field the reference reads for `RefFrames` — so `ref_frames` is empty wherever that build
inspects. What an older build answers is not measured here and no test asserts the column either
way, which is why the suite is green on 9.0.1 locally and on 6.1.1 in CI.

## T3 — The scan probes, and the wire finally says what a file contains

- [x] **Changes:** `library/scan.py` grows the inspection step behind 003's change signal — the
  prober **injectable** on the scan, defaulting to the real one, so the hundreds of dummy-byte
  files in the existing library tests keep a stub and their speed; an inspection failure records
  the file the way 003 §3.7 records unexamined ones and never blocks the item.
  `media/info.py` (new) assembles `MediaSourceInfo`/`MediaStream` wire shapes from stored rows —
  one source per `item_sources` part, the stored `container` verbatim at item level, and the
  source's single container **derived here rather than read from a column** (T2's finding: on a
  listing it is the file's extension where the stored list contains it, the list's first member
  where it does not, and no profile is consulted — spec §3.1, plan §6.1), and the **`ETag`
  derivation read from the reference's source first** and cited in the module (plan §6.8's first
  debt). `api/item_dto.py`'s `MediaSources`, `MediaStreams`,
  `Container`, `Width`, `Height` gap-emitters fill from the same assembly, and the measured
  `NowPlayingItem` gaps 007 left — `HasSubtitles`, `IsHD`, `VideoType` — emit with them.
- **Depends on:** T2
- **Verified by:** `uv run pytest tests/ -q` — the goldens rewritten by this change show
  `MediaSources` exactly where [`probe_item_shapes`](../../tools/probe_item_shapes.py)'s widths
  put them and nowhere else; the standing `NOT_IN_NOW_PLAYING` conformance test **still passes
  unchanged**, which is the tripwire firing as designed (a session entry carries the nine
  media-derived properties now, and still no `MediaSources`); a scanned two-part film answers
  two sources in part order; and the library tests run on the stub prober with no timing change.
- **Spec reference:** §3.1, AC-28; plan §6.1; 007's owed list

**Done (2026-08-29).** The owed reading was owed twice over, and the naive answer is a
well-formed tag that is wrong for every file.

**`ETag` is not the hexadecimal of an MD5 digest, and it is not a hash of ASCII either.** The
assignment is one line — `item.DateModified.Ticks.ToString().GetMD5().ToString("N")`
`[source: MediaBrowser.Controller/Entities/BaseItem.cs:1164 @ v10.11.11]` — and it hides two
conventions. `GetMD5` hashes `Encoding.Unicode`, which is **UTF-16 little-endian**
`[source: MediaBrowser.Common/Extensions/BaseExtensions.cs @ v10.11.11]`, and the sixteen bytes
are then handed to a `Guid` constructor, whose `"N"` form reverses the first three groups before
writing them. Either taken at face value still produces 32 lowercase hexadecimal characters, so
no shape check and no golden regenerated from Atrium would have caught it. It was settled by
*inverting* the derivation rather than restating it: three files of three item types, each tag
matched against the ten million ticks inside the second its `Last-Modified` header names, all
three tick counts recovered exactly `[probe: tools/probe_media_source.py, Jellyfin 10.11.11,
2026-08-29]`. The unit test pins the tag the reference sent, not the one this code computes.

**"It fills slots and does not add fields" was true of two names of eight.** `MediaSources` and
`MediaStreams` were registered gaps; `Container`, `HasSubtitles`, `VideoType` and `IsHD` had no
registry entry at all, because [005's shape notes](../005-item-query-api/notes/item-shapes.md)
listed all four among the properties *deliberately not added* — measured on the wire, read by
neither analysed client, declined under Principle VI. What changed is that a client now reads
them: 007's owed list names three among the nine a `NowPlayingItem` is missing, and AC-28 makes
`Container` the observable half of a rule. So [005 §3.2](../005-item-query-api/spec.md#32-the-item-representation)
gains three per-type rows and one gated name, in the tiers the T1 measurement put them in.

**Spec §3.1's "one media source per part" is a divergence, not parity.** The reference builds one
source per *item* — itself and its linked and local alternate versions — and a stacked film's
later parts are none of those: they are a `PartCount` and a separate `GET
/Videos/{id}/AdditionalParts`, an endpoint outside v1's surface `[source:
MediaBrowser.Controller/Entities/Video.cs:533-563 @ v10.11.11]`. 003 §3.3 merged the parts into
one item with a source each, so the sentence describes Atrium's model reaching the wire; no
library reachable from here has a multi-part film to measure the reference on. Recorded in §3.1
and in [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1).

**Three of a stream's unconditional properties cannot be answered from migration 0006**, and
finding that here rather than at T2 is the cost of the split: `IsAVC`, `TimeBase` and
`NalLengthSize` are read from the demuxer and have no column, and the six-property `DisplayTitle`
family is a *localised* string — `Español - MP3 - Stereo - Predeterminado` on a Spanish server —
that needs the localisation table. Absent rather than approximated, because an English
`DisplayTitle` differs from the reference on every track where an absent one differs on none that
reads it. Four gaps recorded rather than four guesses.

**The wire's numbers are 32-bit, and a double is visible in them.** `AverageFrameRate`,
`RealFrameRate`, `ReferenceFrameRate` and `Level` are singles upstream, and .NET writes the
shortest decimal that round-trips as one: `24000/1001` arrives as `23.976025`, not as the
seventeen digits a double prints, and a whole rate arrives as `25`, not `25.0`. No parser sees
either difference and every byte comparison does — which is what the goldens are for, and it
would have been 010's finding on every video item instead.

Two smaller corrections. The task statement cited **003 §3.7** for how an unexamined file is
recorded; §3.7 is sort names, and the reporting rule is §3.8 — while [003 plan §7](../003-library-configuration-and-scanning/plan.md)
had already named this arrival in advance ("a file whose contents cannot be read … 008 finds it
when it goes to probe"). And staleness here is **not** 003's `unchanged_paths`: those compare
against `item_sources`, which agrees with the disk long before any probe row exists, so a scan
that reused them would leave every existing library permanently uninspected. `MediaProbeRepository.current`
is the comparison, which is what it was written for.

The scan grew a fourth phase, `INSPECTING`, because opening every changed file is now the slowest
thing it does and a progress bar that sat on "writing 400 of 400" for several minutes would be
worse than the three-phase vocabulary it replaces.

## T4 — `media/decision.py`: the ladder, pure, and the table that proves it

- [x] **Changes:** new `src/atrium/media/decision.py` with the contracts
  [plan §5](plan.md#5-contracts) declares — `Outcome`, `StreamAction`, `StreamPlan`, `Decision`,
  `decide()`. Every measured semantic is a branch here and nowhere else: direct play → remux →
  transcode → `NONE` stopping at first success; CSV container membership; codec conditions off
  the stored columns; `MaxStreamingBitrate`; ceilings clamped to `min(profile, source)`; the
  all-three policy gate (video) and the single audio permission; `EnableDirectPlay` honoured,
  `EnableTranscoding` ignored; `SupportsDirectStream` mirroring; `TranscodeReason`s accumulated
  in enum order; the §3.3 HDR rule on the copy path.
- **Depends on:** T2 (the stream records it reads)
- **Verified by:** `uv run pytest tests/unit/test_media_decision.py -q` — the table: every spec
  §5 negotiation criterion as a row (AC-1..AC-7, AC-9's clamps, AC-31's three policy shapes),
  plus the measured oddities as their own rows — `EnableTranscoding: false` changing nothing,
  a single denied permission changing nothing, the empty profile object answering `NONE`, the
  nothing-plays profile answering `NONE` with no reasons for a URL. No HTTP, no database, no
  process: `tests/unit/test_import_directions.py`'s `PURE_WHEREVER_THEY_LIVE` — the tuple that
  already holds `library/identity.py` to the no-I/O rule outside `domain/` — gains
  `media/decision.py` (and T10 adds `media/hls.py` beside it).
- **Spec reference:** §3.2, §3.3, §3.4; plan §5, §6.2

**Done (2026-08-29).** Fifty-six cases, an eighth probe, and three of the task statement's own
clauses turned out to be wrong.

**"The empty profile answering direct play" is the opposite of what happens.** [Spec
§3.3](spec.md#33-the-decision)'s rule 1 read "an empty or absent `DeviceProfile`", and only the
absent half had ever been measured — `probe_playback_info.py` posts no profile, never an empty
one. Posted, `DeviceProfile: {}` answers **every capability flag false**, no `TranscodingUrl`, no
`ErrorCode`: it is a profile whose lists are empty, which is a client that has named no container,
no codec and no target, and it lands on the same refusal a nothing-plays profile does. Written to
the task statement, Atrium would have direct-played a file to a client that had said nothing about
being able to open it. Rule 1, AC-1, [plan §5](plan.md#5-contracts)'s "callers may assume" and this
task's own verification list all now say which half is which.

**`TranscodeReason`s are not accumulated "in enum order", and they do not describe the rung.**
Two separate corrections from one battery. The order is **ascending flag value**, which the
reference's `[Flags]` enum declares in subject groups rather than in value order — so
`VideoRangeTypeNotSupported` (1 << 24) is written above `VideoLevelNotSupported` (1 << 7) and
arrives below it, and a profile failing both conditions at once is what tells the two orders apart.
And the reasons are the *direct-play* analysis alone: a profile that rejects a codec for direct
play while its own transcoding target accepts that codec answers `VideoCodecNotSupported` over a
stream that is then copied, so `TranscodeReasons=ContainerNotSupported` is the common case rather
than the rule spec §3.3 stated it as. A refusal with nothing to blame — no direct-play entry at
all, or `EnableDirectPlay: false` against a profile the source satisfies — answers
`DirectPlayError`, a member of the vocabulary's "Errors" group arriving on an ordinary `200`.

**A ceiling is compared against a number the wire never prints.** The reference's frame rate is a
32-bit field, and the two things done with it are different numbers: the wire writes the shortest
decimal that reads back as the same value, and the negotiation compares the value. A client
declaring a `VideoFramerate` ceiling of exactly the `23.975988` it read is answered with a
**transcode**, because the value is `23.975988388…`; a hair more direct-plays. The narrowing is
`domain/media.py`'s now, so the wire and the ladder cannot drift apart, and the table asserts the
disagreement itself rather than the row that depends on it.

**Two more the next tasks need.** `SupportsTranscoding` cannot be derived from the outcome — one
accepting profile answered direct play with the flag true and false depending only on whether it
declared a transcoding target, so `Decision` carries it. And the **URL carries the profile's
ceilings, not the plan's**: `Height <= 4320` on an 816-line source reaches the query as
`MaxHeight=4320`, because only `MaxFramerate` is seeded from the stream before being minimised
against the condition. T5 renders what was *allowed*; a `StreamPlan` holds what to *produce*
([plan §6.3](plan.md#63-the-transcodingurl)).

**And one branch the task asked for cannot exist yet.** The §3.3 HDR rule on the copy path keys on
a `DOVIWithHDR10Plus` declaration, and T2's inspection cannot produce that range type at all —
`VideoRangeType` carries the three members a stream listing yields, by its own docstring. The copy
path therefore strips nothing, which is [behaviours §3.4](../../docs/compatibility/behaviours.md#34-hdr10-metadata-stripped-from-clients-that-asked-for-it--class-b-no-compensation)'s
divergence in the only shape v1 can reach; the conditional half arrives with the probe that reads
Dolby Vision side data. A test asserts the vocabulary rather than a branch nothing could enter.

The rest of the ladder confirmed the documents: the four containment rules including the leading
`-` and the split-both-sides that makes `mov,mp4,m4a,3gp,3g2,mj2` match `mp4`, `EnableDirectPlay`
honoured and `EnableTranscoding` changing nothing, the all-three policy gate and the single audio
permission, `SupportsDirectStream` mirroring, no upscaling, and a sample-rate ceiling honoured
exactly rather than from the Opus ladder. One thing the plan did not name and the code needs:
`decide` takes the **item's** kind as `is_video` rather than reading it off the file, because a
track with cover art has a video stream and is still negotiated as audio.

## T5 — `PlaybackInfo`: the negotiation routes, and the URL a client parses

- [x] **Changes:** new `src/atrium/api/media_info.py` — `POST` and
  `GET /Items/{itemId}/PlaybackInfo` — and new `src/atrium/media/urls.py` rendering
  [plan §6.3](plan.md#63-the-transcodingurl)'s measured anatomy verbatim (the `?&`, the
  PascalCase parameters, `ApiKey`, `Tag`, the source-codec triplet, `TranscodeReasons`).
  `PlaySessionId` issued per negotiation, GET included; `ErrorCode` emitted in exactly the
  empty-source-list case. **Measured first:** the error table's uncited rows — unknown item,
  invisible item, no token — against the reference, folded into `probe_playback_info.py` as a
  refusal battery, the citations landing in [spec §3.2](spec.md#32-post-itemsitemidplaybackinfo--getpostedplaybackinfo)'s
  table in this same change. `INTERIM_008` begins.
- **Depends on:** T3, T4
- **Verified by:** new `tests/conformance/test_playback_info.py` — goldens per profile class
  over the scanned world (no profile at all and an empty profile object, which T4 measured as
  opposite answers; accepts-all, container-reject, codec-reject, nothing-plays), each pinning
  flags, `TranscodingUrl` presence and its exact query-string
  anatomy; the switch cases (`EnableDirectPlay: false` flips per request; `EnableTranscoding:
  false` does not); the policy cases through a user whose policy the test sets (all-three
  denied → flags down, no URL, no `ErrorCode`); and the refusal shapes as the battery measured
  them. `python3 tools/probe_playback_info.py --allow-writes` stays green with its new battery.
- **Spec reference:** §3.2, §3.3; AC-1..AC-6, AC-31 (negotiation half), AC-30's first hop

**Done (2026-08-29).** The two uncited rows were both right. The row nobody had doubted — this
list's own "no profile at all" — was not.

**A `POST` carrying no `DeviceProfile` is not a negotiation without a profile.** The reference
falls back to the profile the *device* stored through `POST /Sessions/Capabilities/Full`, and the
same bare request answers direct play before a client posts its capabilities and a
`TranscodingUrl` after — measured on one session, both ways, in the same minute `[probe:
tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`. So "no profile at all" is a
property of the *device*, not of the body, and only the `GET` is profile-less by construction
(measured on the same session, still answering all three flags true). Implemented as written,
Atrium would have direct-played a file to a client that had described itself once and then
negotiated with a bare body — the exact shape of client Principle I exists for. 002 stores the
capabilities document whole and unread, so the profile was already there to find.

**The measurement nearly reported the opposite of the row it was written for.** The refusal
battery's first run answered `400`, `text/plain` for "unknown item" on both routes — because the
identifier it used was all zeros, which is the reference's `Guid.Empty` and is refused by a guard
before any lookup happens `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1359-1362
@ v10.11.11]`. With an identifier that reaches a lookup, both routes answer the problem-details
`404` the table claimed, byte-identical to `/Items/{itemId}`'s own refusal; a request with no
token is the empty `401`. The all-zeros edge is a row of its own in the battery now, and it is the
one 006 §3.2 already records as deliberately not reproduced.

**Two things the response is not.** §3.2's own sample carried `"ErrorCode": null`, and the
reference never sends it: a successful negotiation has exactly `MediaSources` and `PlaySessionId`,
the null suppressed globally like every other. And the answer that *does* carry the code carries
**no `PlaySessionId`** — one is issued only where there is something to play. The v1 route into
that answer is a `MediaSourceId` naming no part of the item, which is what makes AC-5's one
`ErrorCode` reachable by a test at all.

**An unrecognised token inside the body is a `400`**, which is the opposite of behaviours §1.12's
query rule and had to be measured rather than assumed: `"Property": "NotAThing"` inside a codec
profile is refused, not dropped. The profile vocabulary is therefore declared as enums — and the
DTO's profile type carries all five of `DlnaProfileType`'s members, because a real browser profile
lists `Photo` entries and refusing those would be a `400` on every request such a client makes.
The whole body is optional in the same measurement (`EmptyBodyBehavior.Allow`): a required one
would refuse a request the reference answers with a full negotiation.

**AC-31 was unreachable, because nothing had ever read the three permissions.** [002
§3.5](../002-authentication-users-and-sessions/spec.md#35-the-user-object) moved
`EnableVideoPlaybackTranscoding`, `EnableAudioPlaybackTranscoding` and `EnablePlaybackRemuxing`
into the enforced set on 2026-08-27 — "any flag whose feature arrives must be enforced in the same
change" — and the code never followed: `users/policy.py` still declared eleven honoured properties
and 31 carried, with these three in the carried blob. They are honoured now, read there rather
than promoted to columns, and the reason is written where the column rule is: that rule buys
visibility for what a *query* touches, and these touch none. Both counts, in four modules and in
002's own spec paragraph, said eleven and 31; they now say fourteen and 28.

**Two additions to T4's contracts, because the URL repeats the client's own words back.**
`Decision` gained `target` — the transcoding entry the answer was built from — and
`TranscodingProfile` gained the five fields that decide nothing in the ladder and are read
straight out of the `TranscodingUrl`: `MinSegments`, `SegmentLength`, `BreakOnNonKeyFrames`,
`MaxAudioChannels`, `EnableAudioVbrEncoding`. Re-deriving which entry was chosen in order to read
them would have been a second copy of `_choose_target`'s ranking. `decision.ceiling` is public for
the same reason: the ladder clamps a limit against the source and the URL reports it unclamped, so
they are two answers from one derivation.

The rest of the anatomy confirmed [plan §6.3](plan.md#63-the-transcodingurl) exactly, including
the pair of booleans four parameters apart — `BreakOnNonKeyFrames=True` beside `RequireAvc=false`
— the `-audiochannels` option qualified by the **video** codec, and the h264 profile name arriving
as `constrainedbaseline`, spaces stripped rather than encoded. One rule the plan did not name and
the route needs: `AudioStreamIndex` is honoured only when `MediaSourceId` names the source it is
about `[source: Jellyfin.Api/Helpers/MediaInfoHelper.cs:206-211 @ v10.11.11]`. And one narrow gap
left for the tasks that produce the audio: an audio stream that reports **no** bitrate takes no
share of the cap here, where the reference substitutes a default from a table keyed on the target
codec and the channel count - so `AudioBitrate` is absent from the URL and `VideoBitrate` is the
whole cap. Recorded in `media/urls.py` beside the arithmetic it belongs to.

### Amended — 2026-09-02: the all-three gate is the profile path's, and the other path had none

**The first difference 010's harness found in Atrium rather than in a document was this route's**,
and the rule it turned out to be about is not the one every document here stated. A seat with
`EnableVideoPlaybackTranscoding`, `EnableAudioPlaybackTranscoding` and `EnablePlaybackRemuxing` all
denied — read back denied on both servers — negotiated a video item and was answered
**`SupportsTranscoding: true` here and `false` there**
`[probe: tools/differential.py --named delivery-time-policy-refusal, Jellyfin 10.11.11,
2026-09-02]`.

**What was missing was not the all-three gate.** That gate was implemented here at T5 and is
correct; the comparison negotiates with an **empty body**, and against no profile the reference
never reaches the stream builder the gate is applied to — its controller runs the whole per-device
step only when a profile arrived `[source:
Jellyfin.Api/Controllers/MediaInfoController.cs:189 @ v10.11.11]`. What a client sees then is the
account's own permissions written onto the **source**, one per media kind `[source:
Emby.Server.Implementations/Library/MediaSourceManager.cs:355-372 @ v10.11.11]`: a video item's
`SupportsTranscoding` is `EnableVideoPlaybackTranscoding` and its `SupportsDirectStream` is
`EnablePlaybackRemuxing`, an audio item's `SupportsTranscoding` is
`EnableAudioPlaybackTranscoding`, and `SupportsDirectPlay` is untouched by all three. So a
**single** denial is observable on the `GET` and on a bare `POST` and invisible one branch away,
which is the opposite of what [spec §3.3](spec.md#33-the-decision), AC-31,
[plan §4](plan.md) and
[behaviours §2.21](../../docs/compatibility/behaviours.md) all said. **Implementing what the
difference looked like** — the all-three gate on the profile-less branch — **would have made the
comparison agree and answered `true` for a seat denied video transcoding alone, where the
reference answers `false`.** All six policy shapes were measured on both branches before anything
was written `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-02]`.

Three smaller things came with it. **The named comparison's own prediction was unreachable**: it
asks `/Videos/{itemId}/stream.mp4`, one of the four `stream` routes, which take no user here at
all (behaviours §2.10), so the delivery-time refusal Atrium substitutes for the force-copy lives on
the segment route and the row's *"two different statuses"* could never happen. It now asserts the
gate on both servers and a delivery neither refuses, and the force-copy edge stays uncompared —
reaching it needs a segment request built by hand, because a denied seat's own negotiation hands
over no address. **`tools/_playback.py`'s picker took the library's first film**, which in the
fixture tree is a file of dummy bytes and then one carrying two subtitle tracks — so the probe
refused to run, and then measured 011's subtitle rule as a ladder finding; it now skips what it
cannot negotiate about and prefers a source with no subtitle stream. And **the listing half is not
reproduced**: the reference builds an item body's `MediaSources` through the same function, so a
denied seat sees the same flags on `/Items?fields=MediaSources`, and closing that means the
caller's policy reaching a build context every route fills — recorded as an accepted gap
(behaviours §5) and left to 005 rather than smuggled into a fix to this route.

## T6 — `compat/ranges.py` and static delivery: the measured matrix, one function

- [x] **Changes:** new `src/atrium/compat/ranges.py` — `negotiate_range(header, size)`
  answering exactly the [spec §3.5](spec.md#35-delivery-the-rules-that-apply-to-every-route)
  table (multi, reversed and every unreadable shape → full body, suffix honoured, `416` with
  `Content-Length: 0`); new `src/atrium/media/labels.py` (the measured container →
  `Content-Type` table) and `src/atrium/api/delivery.py` (the lookup, the range answer and the
  measured four-header set the two controllers share); new `src/atrium/api/audio.py` and
  `src/atrium/api/videos.py` carrying the four `stream` routes' **static** halves: the untouched
  source bytes, `Content-Length` equal to the file size, `Accept-Ranges: bytes`, the path suffix
  choosing the `Content-Type` label and nothing else, and **no authentication dependency at all**
  — every mechanism accepted, none required, which is what these routes measure to and what 002
  §3.1 deferred here (spec AC-32, behaviours §2.10). `db/repositories.py` grows a
  `MediaFileRepository` that takes no user, `compat/errors.py` a `DeliveryNotFoundError` for the
  third error shape at `404` and the reference's pattern-mismatch message. A
  non-static request answers behaviours §1.11's controller refusal *in this task only* — an
  explicitly temporary state, safe because `"008"` is not yet in `IMPLEMENTED_FEATURES` and no
  conformance is claimed for the route; T7 replaces it with the real behaviour.
- **Depends on:** T1, T3
- **Verified by:** new `tests/unit/test_compat_ranges.py` — the whole measured matrix as a table,
  including the five rows RFC 9110 would have answered differently; new
  `tests/conformance/test_static_delivery.py` over the scanned world (AC-11..AC-14:
  `bytes=100-199` is `206` with exactly 100 bytes; the full-body and `416` rows byte-exact;
  the header set asserted as a **set**, so an `ETag` the framework adds is a failure);
  `stream.mkv?static=true` on the mp4 fixture serves mp4 magic bytes behind `video/x-matroska`
  (AC-18, behaviours §2.20); a tokenless request and an unknown-token request both **succeed**
  and answer identical bytes, with `GET /Items/{itemId}` through the same transport answering
  `401` so the assertion cannot pass vacuously (AC-32); the unknown-item `404` measured against
  `PlaybackInfo`'s problem-details `404` on the same identifier; and item-level `Container` vs the
  source's asserted on the same item (AC-28). `tests/conformance/test_auth_mechanisms.py` loses
  the delivery stub 002 left, the way 006 T9 removed the image one.
- **Spec reference:** §3.5, §3.6, §3.7 (static halves); AC-11..AC-14, AC-18, AC-28, AC-32

**Done (2026-08-29).** The matrix held on every row it had. The sentence beside it — this task's
own "a tokenless request refuses and `?api_key=` the working case" — is the opposite of what these
routes do, and 002 had already said so.

**The four `stream` routes require no token, and `/universal` does.** A request carrying nothing at
all, one carrying a token nothing issued, and one carrying `?api_key=` answer the identical `200` on
all four — while `/Audio/{itemId}/universal`, in the same probe run and the same minute, answers
`401` to the first two `[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`. The
split is **per action**: the two `stream` actions of each controller carry no authorization attribute
and the universal one carries `[Authorize]` `[source:
Jellyfin.Api/Controllers/AudioController.cs:89, Jellyfin.Api/Controllers/VideosController.cs:312,
Jellyfin.Api/Controllers/UniversalAudioController.cs:94 @ v10.11.11]`. This was not an open
question and did not need to be: [002 §3.1](../002-authentication-users-and-sessions/spec.md#31-how-a-client-presents-a-token)
measured it on 2026-08-26, wrote "accepted and none is required" into AC-3, and deferred *the
decision* to the feature that owns the routes — which is this task. Implemented as written, Atrium
would have refused the bare URL handed to an external player, which is the entire reason these
routes take a token in the query string at all. Recorded in
[behaviours §2.10](../../docs/compatibility/behaviours.md#210-the-image-and-delivery-routes-accept-a-token-and-require-none)
as decided rather than deferred, and in spec §3.5 with a new **AC-32**.

**The delivery stub 002 left behind had become a test asserting nothing, and its deletion cost a
row.** `tests/conformance/test_auth_mechanisms.py` carried a stub `/Videos/{itemId}/stream`
demanding a token — the exact shape 006 T9 had already removed for images, with the file's own
docstring saying a shadowed stub proves nothing about either route. Removing it takes with it the
half of AC-3 that proved the **precedence chain** on a delivery route: a route that reads no token
cannot demonstrate which of two tokens wins. That row is gone rather than rewritten, and what
replaces it is the failure it was written to catch — a stale header beside a fresh URL cannot
break delivery, because neither is read.

**An unknown item on a delivery route is the third error shape, not problem details.** `404`,
`text/plain` with no charset, and the fixed 25 bytes, on all four routes — where the *same*
identifier on `GET /Items/{itemId}/PlaybackInfo` answers RFC 9457. One feature, one identifier, two
bodies. [Plan §7](plan.md#7-failure-handling)'s row said "the 007-measured refusal family", which is
the wrong family; behaviours §1.11 had only ever met the third shape at statuses that were not
`404`, so "an item that could not be found is problem details" read like a rule until this pair
broke it. `DeliveryNotFoundError` is deliberately **not** a `NotFoundError` subclass, because
inheriting would have made it problem details silently.

**Five rows the matrix did not have, and one of them is where a careful implementation goes
wrong.** [Spec §6](spec.md#6-conformance) named single-byte and whole-file cases the probe had
never sent. Measured: `bytes=0-{size-1}` is a `206` and never a `200`; an open-ended `bytes=a-` and
an overshooting end both clamp; `bytes=-0` is a `416` while a suffix longer than the file is the
whole file; and **every** unreadable shape — no unit at all, `bytes=`, `bytes=-`, `bytes=abc-def`,
`bytes=100-abc` — is a `200` with the entire body. RFC 9110 invites a `416` for most of those, so
the implementation that reads the standard rather than the table refuses requests the reference
serves.

**The label is a measured table, not a transcribed one, and it could not have been guessed.** The
sweep covers every extension `library/walker.py` admits, on video and on audio, plus `m3u8`:
`.opus` and `.oga` are `audio/ogg` rather than `audio/opus`, `.alac` and `.dff` are `audio/mp4`
beside `.dsf`'s `audio/dsf`, `.ogv` is `video/ogg` where `.ogg` is `audio/ogg`, `.rmvb` is not a
`video/` type at all, `.mpc` is `application/vnd.mophun.certificate`, and `.mts` is
**`model/vnd.mts`**. Copying the reference's own table would have been copying its code
(Principle IV); measuring it was cheaper and is the only reason those six rows are right.

Three smaller things the task statement did not name. The `container` **query** parameter is the
same lever as the path suffix and answers the same label. A container the table has no row for is
not an error — the label falls back to the file's own extension — while a container outside the
reference's spelling rule (`^[a-zA-Z0-9\-\._,|]{0,40}$`) is a validation `400` keyed `container`,
refused *before* the item lookup, whose message names the expression rather than the value and is
reproduced byte for byte. And a static response carries exactly four headers with **no conditional
handling at all**: `If-Modified-Since` in the future is answered with the whole film, which is why
the response is assembled by hand rather than with the framework's file response — the convenient
class ships an `ETag` and a `Content-Disposition` the reference does not send, the trap 006 met on
the image routes.

**What T7 and T8 inherit, measured here and not implemented.** `mediaSourceId` is deliberately
**undeclared** on these routes: T6 serves part zero, which is what the reference does when the
parameter is absent, and part selection belongs with the task that renders and consumes the
`TranscodingUrl` carrying it. Its two refusals are measured and waiting: a well-formed id naming no
source is a `400` in the third shape, and an id that is not an identifier at all is a **`500`** in
the same shape — a class-A defect T7 will have to decide about
`[probe: tools/probe_range_matrix.py, Jellyfin 10.11.11, 2026-08-29]`. T8 inherits the one row that
went the other way: `/universal` **does** require a token, and answers the empty `401` without one.

## T7 — Progressive delivery: the remux is sized, the re-encode is chunked

- [x] **Changes:** new `src/atrium/media/ffmpeg.py` — command construction from a `Decision`'s
  stream plans, our own design (Principle IV), copy flags for `COPY` plans, encoder/ceiling
  arguments for `ENCODE`, `-ss` for a start position. `api/audio.py` and `api/videos.py` grow
  their non-static halves: a remux is produced to session scratch and served **sized with
  `Range` support** — the §3.5 divergence, AC-15 — while a re-encode whose length is unknown
  streams chunked with `Accept-Ranges: none`, exactly the reference's progressive shape.
  Client disconnect cancels the process through the response lifecycle. The per-route refusal
  shapes are measured and folded into a probe battery before the routes land (plan §6.8).
- **Depends on:** T4, T6
- **Verified by:** `uv run pytest tests/conformance/test_progressive_delivery.py -q` (marked
  `ffmpeg`) — a remuxed fixture answers `Content-Length` and honours a mid-file `Range`
  (AC-15); a re-encode answers chunked with no length and never a wrong one (AC-17); the
  delivered bytes ffprobe to the negotiated codecs with the accepted stream copied (AC-7 at
  the wire) and dimensions never above the source (AC-8, AC-9); a start position lands the
  output at that position, asserted by decoding the first frames' timestamps (AC-10's
  progressive half); and killing the client connection mid-body stops the process within the
  grace, asserted on the manager's state (AC-26's first appearance).
- **Spec reference:** §3.4, §3.5; AC-7, AC-8, AC-9, AC-15, AC-17

**Done (2026-08-29).** The shapes were all as documented. Three things this list assumed the
project already had were not there, and one of them made a passing test impossible rather than
merely wrong.

**`httpx`'s ASGI transport cannot drop a connection**, so AC-26 had nothing to assert against. It
drives the application to completion, collects every body message and hands back a buffered
response `[source: httpx/_transports/asgi.py, httpx 0.28]` — which means every "streaming" test in
this repository is really a buffered one, and the obvious version of this test (open a stream, read
one chunk, break) was asserting against a response that had already finished: it saw an empty
ledger and an exited process and would have passed with the cancellation path deleted. Plan §6.8
had asked for "a fixture client that drops mid-body" and nobody had written one. It is nine lines
of ASGI in the test file: call the application directly, and return `http.disconnect` from
`receive` the moment the first body chunk is sent, which is what a dropped connection *is* at that
boundary.

**The task statement's "asserted on the manager's state" names something that does not exist yet** —
`TranscodeManager` is T11's and T11 depends on this task. What the assertion needed was a place that
holds the live processes, so `media/ffmpeg.py` grew a `ProductionLedger`: one per application, the
set T11 keys sessions on top of rather than replaces. It also settles the ordering of its own
cleanup, which is not obvious: the ledger discards **before** it kills, because the kill runs from
the `finally` of a body a disconnect has just cancelled and in a cancelled task the very next
`await` raises `CancelledError` again — a version that waited first signalled nothing and left the
ledger claiming the server was still producing.

**A `StreamPlan` states every ceiling, and passing them all to the encoder is what breaks it.** The
plan carries `min(profile, source)` and therefore *the source's own number* wherever the profile
stated no limit — so a faithful command line tells `libmp3lame` to produce 96 kHz and to spend the
FLAC source's lossless bitrate, and both are outside what that encoder has. Two `500`s on the
fixture matrix before the rule existed. Every ceiling is now stated only where it is **below** what
arrived, which is spec §3.4's "limits, not targets" read as an instruction, is what the reference
gets by leaving the same arguments off, and is AC-9 made structural: a plan equal to the source
emits no `-vf` at all, so there is nothing that could upscale.

**And one condition the ladder was already reading had nowhere to go.** `VideoBitDepth` is in
`_REASON_FOR` — a profile that rejects ten-bit h264 refuses direct play over it — and `StreamPlan`
had no field for the answer, so the transcode that refusal produced would have handed the same
client ten-bit h264 again, because libx264 keeps the source's depth. `StreamPlan.bit_depth` is T4's
contract grown by one field, derived by the same `ceiling` as the other five.

**The `mediaSourceId` decision, made by the written procedure.** T6 measured the pair and left it
here: a well-formed identifier naming no source is a `400` in the third shape, one that is not an
identifier at all is a `500`. Re-measured on both halves of the route, four requests, and the split
holds on `static=true` as well as on a produced request. It is class A, so [behaviours
§3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made)'s default is to diverge;
what settles it against §3.0.2's ban on a third behaviour is that the `400` is **not** a third
behaviour — it is the reference's own answer to the same sentence one value away, in the same shape,
on the same parameter — and that replicating costs a parse whose only purpose is to throw (§3.0.0).
Upstream still has the `Guid.Parse` on `master` at 2026-08-07, so tie-break 2 weighs nothing.
Recorded as behaviours §3.9 and asserted as one parametrised row, so the two values are visibly one
answer.

Three smaller things measured rather than assumed. A `Range` on a chunked response is not merely
unhonoured but **unread** — every shape, readable or not, is one `200` from the first byte, so the
sized case's five-row table has no counterpart at all (plan §6.8's second owed reading, discharged).
A produced request into a container nothing can mux is a `500` in the third shape *carrying
`Accept-Ranges: none`*, because the header is written before the encoder is asked for anything —
three shapes of it, including `stream.mp3` on a film. And the output container a bare request falls
back to is the **first member of the source's stored container string**, a third derivation of "the
container" beside T2's two: a bare `/Audio/{id}/stream` on an `.m4a` answers `video/quicktime`.

The probe itself needed two corrections before it measured anything, and both would have reported
the reference as more forgiving than it is. A negotiated `TranscodingUrl` replayed verbatim finds
the job the first request started and answers from *its* media source, so `mediaSourceId` is never
read and every value answers `200`; and an appended `&mediaSourceId=` is a duplicate query name,
which binds to the **first** value — the negotiated one. Replacing both parameters is what turned
three serene `200`s into the measured pair.

## T8 — `/universal`: synthesised profiles and three recorded divergences

- [x] **Changes:** new `src/atrium/api/universal_audio.py` — the parameter set synthesised into
  a device profile exactly as [plan §6.6](plan.md#66-universal) describes, flowing through the
  same `decide()`. The three divergences behaviours already argues land here: the output sample
  rate is the stated ceiling, never the Opus ladder step (behaviours §3.7); a codec-less http
  transcode takes the transcoding container's own codec instead of answering an empty `200`
  (behaviours §3.8); `enableRedirection` binds and never fires for a local source. The HLS
  protocol variant hands off to T10's playlists once they exist — until then `transcodingProtocol=hls`
  is the one refusal this task leaves, listed in `INTERIM_008`'s notes.
- **Depends on:** T7
- **Verified by:** `uv run pytest tests/conformance/test_universal_audio.py -q` — the direct
  case answers the file sized with `Accept-Ranges: bytes`; the 96 kHz fixture under
  `maxAudioSampleRate=22050` delivers **22 050 Hz** — asserted with the same STREAMINFO parse
  the probe uses, against the reference's measured 24 000 (AC-19); the codec-less case answers
  a real stream whose codec is the container's; `enableRedirection=true` on a local file is
  `200` with bytes and no `Location` (AC-21).
- **Spec reference:** §3.6; AC-19, AC-21

**Done (2026-08-29).** All three divergences were as documented on the wire. **The mechanism
behind one of them was not**, and the difference decides how narrow the divergence is — plus
this route turned out to share none of its three refusals with the two `stream` routes beside it.

**"A transcoding profile with no codec in it" is not what happens.** The controller builds its
transcoding profile with `audioCodec ?? "mp3"`, so a codec-less request negotiates perfectly well
and resolves its container — the empty `200` arrives behind `Content-Type: audio/mpeg` when no
`transcodingContainer` is named, which is that default on the wire. What carries no codec is the
**streaming request** built after it, and a streaming request with none infers one from the part
of the request path after its last dot. `/Audio/{itemId}/universal` has no dot, and the helper's
answer to a missing separator is the whole string `[source:
Jellyfin.Api/Helpers/StreamingHelpers.cs:71-75, src/Jellyfin.Extensions/StringExtensions.cs
RightPart @ v10.11.11]`, so the path becomes the encoder name. Measured with a
`transcodingContainer` and without one, both empty `[probe: tools/probe_universal_audio.py,
Jellyfin 10.11.11, 2026-08-29]`. That makes behaviours §3.8's divergence far smaller than it read:
the reference *has* this inference table and Atrium hands it the container rather than a dotless
path, so `mp3` in and `mp3` out on both servers and the difference exists only where a client
named a transcoding container and no codec.

**Synthesising the profile "exactly as the reference does" would have honoured no ceiling at
all.** Its `GetDeviceProfile` scopes the one codec profile it builds to the **direct-play**
container list — the containers it will not be transcoding into — so on the transcoding path
those conditions apply to nothing, and the ceiling reaches the encoder only because the
controller *also* passes `maxAudioSampleRate` straight into the streaming request, outside the
profile entirely. Atrium has one path and it is the profile, and the probe settles which
observable to reproduce: `container=ogg` with `transcodingContainer=flac` and a 22 050 Hz ceiling
really is answered at a constrained rate. The conditions are therefore stated unscoped, and a
transcription of the reference's profile would have delivered the full 96 kHz.

**AC-19 named three ceilings and the reference honours two.** A `maxAudioBitDepth` below the
source's refuses a *stream copy* and nothing else: no sample-format argument is emitted anywhere
in the reference's builder, on any route `[source:
MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs CanStreamCopyAudio @ v10.11.11]`. Adding
one would be a third behaviour, and one that breaks every encoder whose sample format is not a
choice — `aac` takes `fltp` and nothing else. So the criterion is corrected rather than
implemented: the bit depth is a trigger, the rate and the channel count are targets.

**Three refusals, and this route shares none of them with its siblings.** An item nothing holds
is **problem details** here — byte-identical to `GET /Items/{itemId}`'s, trace identifier aside —
where `/Audio/{itemId}/stream` answers the third error shape on the same identifier in the same
run. And both `mediaSourceId` shapes answer one `400` here, where the `stream` pair splits them
`400`/`500`: [behaviours §3.9](../../docs/compatibility/behaviours.md)'s divergence turns out to
be a choice between two answers the reference itself already gives the same parameter, which is a
stronger argument than the one recorded when it was decided. The token requirement was the one
row T6 had already measured, and it holds.

**`transcodingProtocol` is a nullable enumeration upstream and declaring one here would have been
a `400` the reference never sends.** `HLS` reaches the playlists and `banana` reaches the
progressive body — both `200`, neither refused — so the parameter binds as text and is compared
case-insensitively (behaviours §1.12, on a typed parameter for the first time). `container` needed
measuring from the source rather than guessing too: it is split on **commas before bars**, so a
music client's `opus,webm|opus,mp3,aac,m4a|aac,flac` is six direct-play entries, and splitting it
the other way round would have produced one nonsense container and transcoded everything.

**The audio-bitrate default table 008 T5 left owed is not this task's**, and the reason is worth
recording so T9 does not go looking either. That gap is in the *`TranscodingUrl`'s* arithmetic —
a total cap split between a video share and an audio share, where a stream reporting no bitrate
takes none. `/universal` renders no URL and has no video half: `audioBitRate ?? maxStreamingBitrate`
is a plain audio ceiling here, stated as a condition like every other and passed to the encoder
only when it is below what arrived. The table stays owed by whichever task needs the split.

## T9 — WAV: both symptoms answered with a real header, and the prior-probe debt paid

- [x] **Changes:** the PCM path in `media/ffmpeg.py` and the two routes: `stream.wav` (and
  `stream` with a `pcm_*` codec) and `/universal` with `Container=wav` both answer valid RIFF —
  real header, `Content-Length` computed from sample count, `Range` support — the behaviours
  §3.2 decision, both symptoms. **The probe debt is paid in the same change:**
  `probe_universal_audio.py` grows a WAV battery measuring the reference's two broken shapes
  (`stream.wav` → `500`; `Container=wav` → the malformed body), and behaviours §3.2's two
  `[prior-probe: 2026-08-03]` citations upgrade to the script — after which behaviours §3.2
  carries no prior-probe citation at all.
- **Depends on:** T8
- **Verified by:** `uv run pytest tests/conformance/test_wav_delivery.py -q` (marked `ffmpeg`)
  — both routes' bodies start `RIFF….WAVE`, ffprobe reads them as `pcm_s16le` at the requested
  rate, the declared `Content-Length` equals the body, and a mid-file `Range` answers `206`
  (AC-20); `python3 tools/probe_universal_audio.py --allow-writes` prints the new battery's
  finding against the reference and exits 0.
- **Spec reference:** §3.6, AC-20; behaviours §3.2

**Done (2026-08-29).** The debt was the task, and paying it moved **both** of the claims it was
supposed to confirm. Neither symptom is a property of the route it was recorded against; both are
properties of one parameter.

**Symptom 1 has two causes.** [Behaviours §3.2](../../docs/compatibility/behaviours.md#32-pcmwav-output--one-bug-two-symptoms-two-classes)
recorded one — `-ar` built from an absent `AudioBitRate` — and that is only the second way in. A
bare `stream.wav` never reaches the PCM block at all: the codec is inferred from the path
extension, the reference's inference table has no `wav` row, and it hands `wav` to `-acodec`
because it is a well-formed container name. Two `500`s that look identical on the wire, one of
which the entry had never seen, and only one of which the upstream fix addresses.

**Symptom 2 was recorded against a parameter that does not produce it.** `/universal` with
`Container=wav` answers **mp3** — `container` is the direct-play list, and the headerless PCM
comes from `transcodingContainer=wav`. AC-20 said `Container=wav`, so the criterion as written
was unreachable; it now names the transcoding container and the two `stream` spellings beside it.
The same run showed symptom 2 on `stream.wav` too, which the §3.2 split had assigned to
`/universal` alone: the real split is *whether an `audioBitRate` was sent*, and it cuts across
both route families.

**And "a `Content-Length` computed from sample count" is the wrong shape.** A WAV states its own
length **inside the body**, twice, and a muxer writing to a pipe fills both fields with
`ffffffff` and exits `0` — two invocations of one conversion differ in exactly those eight bytes.
So there is no chunked WAV answer to compute a header for: the output goes to scratch like a
remux and the length is the file's. `media/ffmpeg.py` refuses to build the piped invocation, and
that refusal is the assertion, because httpx's ASGI transport could never have shown the
difference (T7's finding, met from the other side).

**One row had to be added rather than transcribed.** ffmpeg's wav muxer *accepts* a FLAC stream
under a codec tag and writes a genuine `RIFF` header over it, so a bare `stream.wav` falling back
to the source's codec — the rule that makes a bare `stream.mkv` a remux — would have passed every
"is it RIFF" assertion in the new test file and played nowhere. The wav container names its own
codec, in `media/ffmpeg.py` rather than in `api/universal_audio.py`'s transcribed inference table,
so that table's citation stays true about what the reference contains.

**Two findings outside §3.2.** [Behaviours §3.8](../../docs/compatibility/behaviours.md#38-universal-without-audiocodec-answers-an-empty-200--class-a-diverged)
said the empty `200` arrives "with or without a `transcodingContainer`"; it does not. A codec-less
streaming request does not become the request path — `GetAudioEncoder` guards its input with the
container-validation pattern and substitutes `aac` — so the empty body is `aac` meeting a muxer
that cannot hold it, and a `wav` target, which can, answers a real RIFF. And the probe needed a
fresh `DeviceId` on every row: the reference names its transcode output from the media path, the
user agent, the device and the play session and nothing else, so a request that **cannot be
produced at all** is answered `200` with a neighbouring request's bytes. Four rows of the first
battery passed for that reason. Atrium keys its scratch on the whole command plus the file's
change signal (T7), so the same pair of requests answers two bodies.

The audio-bitrate default table T5 left owed was **not** needed: nothing in this task renders a
`TranscodingUrl`, and PCM has no bitrate to default — `-b:a` at a `pcm_*` encoder is accepted and
ignored, measured. It stays owed to whichever task splits that cap.

## T10 — `media/hls.py`: predicted playlists, and the two cadences

- [x] **Changes:** new `src/atrium/media/hls.py` — `plan_segments` (uniform cadence for an
  encode, keyframe buckets off the stored list for a copy), `media_playlist` (VOD, v3,
  `MEDIA-SEQUENCE:0`, `ENDLIST`, `, nodesc`, `runtimeTicks` + `actualSegmentLengthTicks` per
  URI), `master_playlist` (exactly one variant, the negotiated `CODECS`/`RESOLUTION`/
  `FRAME-RATE`/`BANDWIDTH`). **The cadence-rounding rule is read from the reference's playlist
  generator first** and its citation lands in the module (plan §6.8's second debt); the
  measured 3.004 s / 6.0 s pairs become the golden. New `src/atrium/api/dynamic_hls.py` serves
  `master.m3u8` and `main.m3u8` from the plan alone — no process — sized, and instant on a
  cold session. T8's `transcodingProtocol=hls` refusal is replaced by the real master playlist.
- **Depends on:** T4, T2 (keyframes)
- **Verified by:** `uv run pytest tests/unit/test_hls_planning.py tests/conformance/test_hls_playlists.py -q`
  — the golden: an encode plan over a 23.976 fps fixture reproduces the measured cadence and
  the copy plan reproduces keyframe alignment (asserted against the fixture's ffprobe-read
  keyframes); every body duration equal, last ≤ body (AC-22's boundary half); the playlist
  routes answer complete with `ENDLIST` and `Content-Length` **before any segment has ever
  been produced**, and twice identically (AC-22's playlist half); the master carries one
  variant and the full forwarded query.
- **Spec reference:** §3.7; AC-22 (boundaries and playlists); plan §6.4

**Done (2026-08-29).** **Both published cadence numbers were attributed to the wrong thing, and
the golden this task was told to write would have failed on the fixture built for it.** The
rounding rule is `ceil(milliseconds × ceil(rate) ÷ rate)` over the rate the *request* carries, at
32-bit precision — so 3.004 s is a fact about one film's **stored** 23.975988, and T1's
`long_take`, built at an exact `24000/1001` precisely so "T10's rounding arithmetic has a source
that actually runs at it", answers **3.003 s**. What is pinned is therefore the rule at five
requested lengths (1 s → 1.002, 2 s → 2.003, 3 s → 3.004, 5 s → 5.006, 10 s → 10.011) and at both
rates, which is also what separates `ceil` from `round`: a single row cannot.

The 6.0 s copy cadence is **not** "the source's own keyframes" either. A copy follows real
keyframes only where the operator has permitted on-demand keyframe extraction for that container,
shipped and running as Matroska alone — so the measured mp4 film got the equal-length grid at the
copy default. Asked at an off-grid five seconds the same mp4 answers ten segments of exactly 5.0 s
and a Matroska file answers 5.045, 5.0, 5.0 …, which is what the conformance test now asserts
against ffprobe-read keyframes, over a Matroska sibling generated for it (the fixture matrix has
no keyframed mkv).

Three smaller things. **Forwarding the query string verbatim needed the bytes from before
`compat/query_params.py`'s case-insensitive rewrite**, which would otherwise have handed clients
`maxFramerate` where the reference writes `MaxFramerate`; the middleware now stashes them.
**These two routes require a token where the four `stream` routes require none** — behaviours
§2.10's split is per action, not per feature — and their other refusals are the `stream` pair's
third error shape rather than `/universal`'s problem details, `main.m3u8` with no query at all
being no refusal at all. And **`BANDWIDTH` is this server's own encoder target**, where the
reference advertises a rate scaled between the input and output codecs; with one variant there is
nothing to select on it.

**One bullet of this task is not done, and it needs a decision that is not an implementation
one.** "T8's `transcodingProtocol=hls` refusal is replaced by the real master playlist" cannot be
carried out inside the accepted surface: the reference answers that request with a master playlist
whose single variant URI is a relative `main.m3u8`, which resolves to `/Audio/{itemId}/main.m3u8`
— a path [surface.yaml](../../docs/compatibility/surface.yaml) does not carry, [§3.7](spec.md#37-video-delivery)'s
route table does not describe, and no task lands. Serving that master would advertise a route that
answers nothing, which is Principle VI's plausible-looking stub. The refusal therefore stands in
`INTERIM_008` with its reason now measured rather than deferred, and adding the audio playlist
pair is a scope decision under AGENTS.md's "Adding an endpoint" procedure — spec first.

## T11 — The `TranscodeManager` and the segment route: production with an owner

- [x] **Changes:** new `src/atrium/media/sessions.py` —
  [plan §5](plan.md#5-contracts)'s `TranscodeManager`: one supervised ffmpeg per session keyed
  by `PlaySessionId`, sequential production into per-session scratch, `segment()` serving from
  disk inside the produced window and killing + restarting at `plan_segments()[index]` outside
  it, injectable clock, every request a `ping`. `api/dynamic_hls.py` grows the segment route —
  `GET /Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}` is the reference's
  `DynamicHlsController` like the playlists, not `HlsSegmentController` as the name suggests —
  serving finished segments sized with `Accept-Ranges: bytes`. `server.py` wires the manager
  into the lifespan beside the flusher and reaper.
- **Depends on:** T7 (the command builder), T10 (the plan)
- **Verified by:** `uv run pytest tests/conformance/test_hls_segments.py -q` (marked `ffmpeg`,
  fixture films seconds long) — segment 0 arrives sized; the same segment re-requested is
  byte-identical (AC-23); an out-of-order segment is served (AC-24); a segment near the end of
  the fixture arrives having produced nothing before it — asserted on the scratch directory's
  contents, the work-not-done form of AC-10; a delivered mixed-plan segment carries the copied
  video codec and the re-encoded audio (AC-7, AC-8 at the segment level); and a new guard in
  `tests/unit/test_import_directions.py` asserts `subprocess` is named only by
  `media/probe.py`, `media/ffmpeg.py` and `media/sessions.py` — the supervised set, so "every
  ffmpeg has an owner" (architecture §4) is a sweep rather than a discipline.
- **Spec reference:** §3.4, §3.7; AC-7, AC-8, AC-10, AC-16, AC-23, AC-24

**Done (2026-08-29).** **"Restarting at `plan_segments()[index]`" would have produced the wrong
film.** The index in a segment's path is ffmpeg's `-start_number` and decides nothing but the
produced file's name; where production *starts* is the `runtimeTicks` the URI carries, which the
playlist happens to fill with that segment's cumulative start — so the two agree for every URI a
playlist writes and disagree the moment anything hand-writes one. Measured rather than reasoned:
segment 0's own path asked for at the middle of a film answers the middle of the film, two
digests from one path. A manager that seeked to `index × cadence` would have been right on every
test that followed a playlist and wrong on the one request that matters, a client that kept a URL.

**The task named three modules that may start a process and there are two.** The manager starts
everything through the `ProductionLedger`, so exempting it from
`tests/unit/test_import_directions.py`'s new sweep would have been a hole rather than a
permission: a manager that grew its own `create_subprocess_exec` is a manager whose processes the
ledger does not list, which is the exact failure "every ffmpeg has an owner" exists to prevent.
The sweep therefore exempts `media/probe.py` and `media/ffmpeg.py`, asserts that both really do
start processes, and asserts separately that `media/sessions.py` starts none of its own.

**A segment carries a `Last-Modified` where the progressive routes carry none**, which behaviours
§3.3's "the produced answer carries no `Last-Modified`" had generalised one route too far: the
reference serves a finished segment the way it serves any file — `Content-Length`, its container's
type, `Accept-Ranges: bytes`, a modification time, no `ETag` — and an honoured `Range` on top.
That is AC-16 and AC-11 in one measurement, and parity rather than divergence.

**The encoder had to be told a cadence the reference never tells it.** The reference scales the
segment length for the playlist and states the unscaled integer to ffmpeg — `-hls_time 3` under
`#EXTINF:3.004000` — so its segments hold four milliseconds less than they declare and a 2h22
film's playlist claims eleven seconds it does not have. Spec §3.7 rule 2 asks for the opposite;
the divergence is now argued in [behaviours §3.10](../../docs/compatibility/behaviours.md), and it
is safe because the playlist is byte-identical on both servers and what moves is inside produced
media §6 already declines to compare.

Three smaller things. **The decision belongs to the request, not to the session**: the reference
rebuilds its whole streaming state per segment, so a client changing audio track mid-film is
answered about the new one — `obtain` therefore takes only the key and `segment` takes the plan.
**Two of the route's three path parameters decide nothing**: `playlistId` is unused, and the
path's own container is not what the segment is muxed into, `0.mp4` under `SegmentContainer=ts`
answering MPEG-TS labelled `video/mp2t`. And **the six refusals split across two shapes by where
they happen**: the `stream` pair's third shape for everything a controller throws, including a
`400` for a segment carrying `startTimeTicks`, and the framework's own problem details for a
segment URI stripped of its query — because `runtimeTicks` and `actualSegmentLengthTicks` are
required, which is the opposite of what the same treatment of `main.m3u8` answers.

**`run()` is not wired, deliberately.** The lifespan gains the manager's construction and its
`shutdown()`; the sweep arrives at T12 with the ping timeout it enforces, because a task looping
over nothing is dead code with a schedule.

## T12 — The kill paths: a stop that stops, and scratch that dies with its session

- [x] **Changes:** new `src/atrium/api/hls_segment.py` — the reference's `HlsSegmentController`
  is where `DELETE /Videos/ActiveEncodings` actually lives — both parameters mandatory (`400`
  naming the missing one), `204` always, the named session's process killed and its scratch
  removed, unknown session a no-op `204`. The manager's sweep gains the
  **ping-timeout** — its constants read from the reference's `TranscodeManager.cs` first
  (plan §6.8's third debt) — and `shutdown()`/startup clear scratch wholesale.
  `api/sessions.py` grows `TranscodingInfo` on playing sessions read from the manager (the
  measured shape the probes themselves branched on), suppressed when nothing transcodes.
- **Depends on:** T11
- **Verified by:** `uv run pytest tests/unit/test_transcode_lifecycle.py -q` — injected clock,
  no sleeping: the stop route kills exactly the named session (a second session survives) and
  its scratch is gone (AC-25); a missing `playSessionId` is the validation `400` naming it; a
  session unpinged past the timeout dies with its scratch (AC-26's server half, AC-29);
  shutdown leaves the scratch root empty and a synthetic orphan is cleared at startup;
  `/Sessions` during a transcode carries `TranscodingInfo` with the negotiated codecs and
  loses it after the stop; and a `PlaySessionId` from a T5 negotiation is accepted by the
  segment route and by this one (AC-30).
- **Spec reference:** §3.8; AC-25, AC-26, AC-29, AC-30

**Done (2026-08-29).** **The stop route is keyed on the play session, and the `deviceId` it
requires decides nothing.** This list and [plan §5](plan.md#5-contracts) both wrote `stop(device_id,
play_session_id)`, and the reference selects the jobs to kill by `playSessionId` whenever one was
given — measured rather than reasoned: a `DELETE` carrying a device the server has never seen
still stopped the named session, and one carrying a play session nothing issued left a live one
running and still answered `204`. A manager that had required both to match would have leaked an
encoder for every client that spells its device differently between the negotiation and the stop,
which is the one failure this route exists to prevent.

**And the well-formed call does not remove the session's `TranscodingInfo`**, which [spec
§3.8](spec.md#38-session-lifecycle) and OQ-6 had both asserted since the gate. The reference
reports one last time as the process exits, with every number null, so the object stays on the
session with two fewer keys — `Framerate` and `CompletionPercentage` — until playback is reported
stopped. Nobody had noticed because the probe's own helper read `CompletionPercentage` straight
off the session and returned `None` for "absent object" and "absent number" alike; the kill
battery separates them, and behaviours §3.11 carries Atrium's decision to drop the report with
the work.

**The kill-timer reading was the smaller half of the owed reading.** The numbers are 60 000 ms and
10 000 ms, split by nothing but whether the job is progressive, and everything a session here owns
is the former. Measured end to end at 58 s and 60 s on two runs — worth the two minutes, because
"the sweep uses the number in `TranscodeManager.cs`" and "a real server really kills at that
number" are different claims and only one of them was owed.

**The hazard T11 handed on was real and its first fix was not.** `ProductionLedger.start` gave
every process an unread `stderr` pipe; a pipe fills at some tens of kilobytes and a process
blocked writing into a full one never reaches its own exit, so it can neither finish nor be
reaped by waiting. The drain that fixes it had to read by *block*: written with `readline` it
gave up on any line longer than the stream's limit and stopped reading from that moment on, which
is the same hang with more code — and the test written for the hazard caught it, having been
written to fail by timing out rather than by hanging. **The second version was wrong on a slower
machine only**: `finish` cancelled the reader instead of waiting for it, so the encoder's last
words were discarded in the very call that logs them. It passed locally every time and failed in
CI, which is the whole argument for asserting that the words survive as well as that the process
does.

Two smaller things. **The measured `TranscodingInfo` is thirteen properties and Atrium sends
eleven**: the two missing are the ones read out of the encoder's progress output, which this
server does not parse, and the shape without them is one the reference itself sends every time a
job stops. And **the battery's first draft measured its own confound**: `TranscodingInfo` hangs
off the *device's* session, so two of the probe's own jobs were two writers of one property and a
row that killed its job read the survivor's percentage — the rows now start and end one job each.

## T13 — The operator knobs, and policy at delivery

- [x] **Changes:** `config/settings.py` grows the encoding section with the reference's names
  and defaults — `enable_throttling` (false), `throttle_delay_seconds` (180),
  `enable_segment_deletion` (false), `segment_keep_seconds` (720) ([plan §6.7](plan.md#67-session-lifecycle-and-configuration)).
  The manager honours all four: production pauses at `max(gap, 60)` ahead of the last-requested
  position when throttling is on and runs to the end when off; aged produced segments are
  removed while the session lives when deletion is on. And the delivery half of the policy
  rule: a session whose plan re-encodes a stream the user's policy forbids refuses that
  delivery rather than force-copying an incompatible stream — the one non-replicated edge,
  behaviours §2.21's argument.
- **Depends on:** T12
- **Verified by:** `uv run pytest tests/unit/test_transcode_throttle.py -q` — injected clock
  and a fake producer: with throttling on, production halts at the configured gap after the
  client stops fetching and resumes on the next fetch (AC-27's enabled half); with it off —
  the default, asserted as the default — production continues (AC-27's shipped half); with
  deletion on, a segment older than the window disappears while the session lives and the
  playlist still serves it back through the restart path; and the policy-refusal case answers
  an error, never bytes that violate the negotiated profile (AC-31's delivery half).
- **Spec reference:** §3.4, §3.8, §3.3 (policy at delivery); AC-27, AC-29, AC-31

**Done (2026-08-29).** **`SegmentKeepSeconds` is not an age, and every document here said it
was.** This list asked for "aged produced segments", [spec §3.8](spec.md#38-session-lifecycle)
reclaimed scratch "by age", and AC-29 said "produced segments older than the configured window".
The reference removes produced segments by **index**, computed from how far the *client* has
fetched: everything below `(furthest-fetched seconds − keep seconds) ÷ segment seconds`, and
nothing at all until the client's position has passed the window. Measured rather than only read,
because the two rules agree on the easy cases and disagree on the one that matters: a 720-second
window, a client whose furthest segment ended 811 seconds in, and forty-five seconds later —
with nothing requested in between — segment 29 was gone and segment 33 was still there, two
files written seconds apart on either side of `(811 − 720) ÷ 3`. Implemented as an age, a session
whose viewer paused for thirteen minutes would have thrown away exactly the segments the resume
asks for, and every resumed playback would have been a re-encode of material already on disk.

**The delivery half of the policy rule is per stream, and it is video-only.** AC-31 read as
though a denied account met one gate at delivery; the reference reads two of the three
permissions there and reads each against its own stream — video transcoding forces the video
stream to a copy, audio transcoding forces the audio stream — from a branch that runs **only for
a video request**, so `/Audio/{itemId}/universal` consults neither and re-encodes for a denied
account exactly as for a permitted one. `EnablePlaybackRemuxing` has no delivery-time reader at
all. So Atrium's refusal is scoped to the two streams of a video delivery, which is the one route
in this feature with both a user and a production; refusing on the audio route would have been an
invention with no force-copy behind it to justify it, and refusing on the playlists would have
been a difference on a request that costs nothing.

**And the reference's own delivery-time refusal cannot fire**, which is worth recording because
reading it alone would have made the divergence look like parity. `TranscodeManager.StartFfMpeg`
throws "User does not have access to video transcoding" when a video job's output codec is not a
copy — and the same permission on the same user has already rewritten that codec to `copy` two
calls earlier, in the state builder. The force-copy is the behaviour; the refusal beside it is
unreachable code.

Two smaller things. **The throttle's pause had to be asserted on the files rather than on a
flag**: the first version of the test checked `paused is True`, which a `suspend()` that sent no
signal at all satisfies — the assertion that matters is that a real child stops writing and
starts again, and it fails against a no-op. And **`actualSegmentLengthTicks` turned out to be the
whole point of both knobs**: T11 bound it and called it unread, T12 left it alone, and it is one
half of the download position the throttle stays ahead of and the deletion pass falls behind.

## T14 — The acceptance map, the exact route set, and 008 is Implemented

- [x] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_008` — thirty-one
  rows, each naming its test; `IMPLEMENTED_FEATURES` gains `"008"` and `INTERIM_008` is
  deleted; `spec.md`, `plan.md` and this file are marked `Implemented`; `specs/README.md`'s
  table and narrative, `docs/roadmap.md` and `AGENTS.md`'s "where the project is" say so; and
  this file gains **what 008 owes 009 and 010** — at minimum: the differential questions the
  spec already routes there (OQ-5's parameter coverage, the progressive-remux sizing
  divergence a differential will flag, behaviours §3.7/§3.8's divergent answers), and whatever
  the thirteen tasks above have added to that list by then.
- **Depends on:** T1–T13
- **Verified by:** the full gate — `uv run ruff check . && uv run ruff format --check . &&
  uv run mypy && uv run pytest` — with `test_every_implemented_feature_has_a_map`,
  `test_the_specification_still_has_the_criteria_this_map_expects` and
  `test_no_route_ships_ahead_of_its_feature` green: the map is complete, the criteria count
  matches the spec's thirty-one, and exactly the eleven 008 routes of
  [`surface.yaml`](../../docs/compatibility/surface.yaml) are served — counted against the
  file, not against this list's prose (007 T13's lesson).
- **Spec reference:** §5, §6

**Done (2026-08-29).** **The definition of done below said "no other response differs observably
from the measured reference", and that was false on the day it was written.** There is a fourth
delivery divergence, it is the only one in this feature that runs *away* from the reference, and
nothing in this repository recorded it.

**A progressive re-encode produced to a pipe loses the frame its container describes itself in.**
Measured here rather than taken from the client contract that reported it: the same three seconds
through `libmp3lame` written to a file carries an `Info` frame at byte 65 and the encoder string
`Lavc` at 185, and written to `pipe:` carries neither — the two bodies differ by 417 bytes, which
is one frame at 128 kbps. The same pipe leaves a FLAC's `STREAMINFO` declaring `total_samples = 0`
with an all-zero MD5, which `ffprobe` reads back as no duration at all against `3.000000` for the
identical encode to a file. ffmpeg reserves that frame and seeks back to fill it in; to a pipe it
cannot, so it writes none. The reference produces progressive output to a *file* and streams it as
it grows, so **its** body has the frame and ours does not — a parity gap, not an improvement, and
the one place a fix would move towards the reference rather than away from it. `NEEDS_SEEKING`
correctly did not catch it: its rule is "a body that would lie about its own length", and a piped
MP3 does not lie, it omits. Recorded as the last paragraph of
[behaviours §3.3](../../docs/compatibility/behaviours.md#33-progressive-transcoding-responses-carry-no-content-length-or-accept-ranges--class-c),
and the definition of done says four rather than three.

**Two acceptance criteria said something the tests that prove them contradict**, which is what
putting a criterion and its test on one line is for. **AC-11 needed a measurement to settle**:
"every delivery route whose body has a known size answers `Accept-Ranges: bytes`" is false of the
two playlist routes, and `probe_hls.py` grew a header-name battery to say so — the reference's
master answers `Content-Length, Content-Type, Expires` and its media playlist `Content-Length,
Content-Type`, neither with a range unit, where its segments carry both `[probe: tools/probe_hls.py,
Jellyfin 10.11.11, 2026-08-29]`. Implemented as the criterion read it, Atrium would have sent a
header the reference does not send on the one delivery family a client parses as text. **AC-6
needed only a reading**: it derived `SupportsTranscoding` from the negotiated answer, where §3.3
and T4's measurement both have it as a property of the *profile* — one accepting profile with a
transcoding entry and the same profile without one are both direct play, and only the first says
`true`.

**Two more criteria were mapped to tests that proved less than their names**, the failure this
project keeps meeting, and both are now written and both were proven able to fail by breaking the
code underneath them. **Nothing had ever compared `MediaSources[].Size` with the bytes a delivery
route serves**: the size is stated beside the inspection and the stream route stats the file again
on arrival, and every golden here carries a fixture size, so the two numbers had never met — while
a client reads that field as the length of what it is about to fetch and bounds every range request
with it. And **nothing proved `audioStreamIndex` changes the produced audio**: only the negotiated
URL's *spelling* of it was asserted. Sabotaging it to find out where it is read turned up two
readers, of which a client can observe one: `_audio_stream` in `api/delivery.py` decides the
**codec fallback**, and `Switches.audio_stream_index` decides the **mapping** — a change to the
first passes every test in the repository. The fixture matrix has one audio track per file, so the
test builds a two-track sibling the way T10 built its Matroska one.

**And two halves of two more were unasserted for one reason**: every segment test in
`test_hls_segments.py` uses a re-encoding query, so AC-16's *"whether it was remuxed or
re-encoded"* and AC-22's *"identical segment bytes"* were each proven over half their subject. One
copied segment, fetched twice, closes both.

**The client contracts left six behaviours entries owed and three of them are this feature's.**
[§5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s subtitle row said subtitles are
"delivered as files" and v1 delivers none at all — owed since 2026-08-28, and a feature marked
`Implemented` over it would have been exactly the false claim this map exists to catch; §5 gains a
row for a media source with **no stored inspection**, which 008 ships and neither client can ask a
rescan for; and §3.3 gains the pipe's cost above. The other three are not 008's and are named in
"what this feature owes the next ones" with their owners: subtitle delivery itself and
`SubtitleStreamIndex` are [011](../011-subtitle-delivery/)'s, and behaviours §4.2's missing sentence
about an operator who publishes an HTTPS URL is 001's field and a deployment-guidance change.

The rest of the definition of done was as it said. The eleven routes are served and counted against
[`surface.yaml`](../../docs/compatibility/surface.yaml) rather than against this list's prose, all
five owed readings carry their citations, and `INTERIM_008` is gone the way its four predecessors
went.

## T15 — The variant OQ-7 never saw: an SDR entrance beside an HDR copy

*Appended after the feature was `Implemented`, because the answer it corrects is 008's own.*

- [x] **Changes:** `tools/probe_transcode_decision.py` gains a second half that negotiates the
  same audio-only rejection against a **high-dynamic-range** source and reports the master
  playlist's variants, their attributes and the entrances' addresses; `media/hls.py`'s
  `master_playlist` appends the h264 SDR entrance where the video is copied and the source is
  HDR; `tests/fixtures/media.py` gains the one HDR entry the matrix lacked; and
  [spec §3.7](spec.md#37-video-delivery), OQ-7 and
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) say what was
  measured.
- **Depends on:** T10, T14
- **Verified by:** `python3 tools/probe_transcode_decision.py --allow-writes` against a library
  that holds an HDR film — the run names the source's own range, so it says on its face whether
  it reached the branch — and `uv run pytest tests/unit/test_hls_planning.py
  tests/conformance/test_hls_playlists.py -q`, where two files differing only in colour are
  negotiated the same way and answer one variant and two.
- **Spec reference:** §3.7, OQ-7

**Done (2026-08-30).** **OQ-7 measured a branch it could not reach, and wrote the miss down as
the shape of the route.** "Exactly one `#EXT-X-STREAM-INF`, never a ladder" came from a probe that
takes whatever video the library lists first and never asks what it is; that film was standard
range, and the entrance beside a stream copy fires only on an HDR source. Re-measured against one:
**three variants**, at the same `BANDWIDTH` and `AVERAGE-BANDWIDTH`, the same `RESOLUTION` and the
same `FRAME-RATE`, differing only in `VIDEO-RANGE` and `CODECS` — which is the entire mechanism,
since a client with nothing to choose on rate chooses on colour. The probe now reports the source's
`VideoRange` beside the count, so the next reader can tell a measurement from a miss.

**Two of the three are an operator's, not the reference's.** `AllowHevcEncoding` and
`AllowAv1Encoding` both ship `false`; the measured server had the first on, which is where the
hevc entrance came from. A shipped reference answers the copy and the h264 entrance, which is what
this server now answers — and adding the two knobs would have been half a knob, because the same
permissions also reorder the codec a transcode targets, so the name would have promised more than
it did.

**The third finding was mislocated, and the measurement is what showed it.** The audit that raised
this read `media/hls.py`'s unconditional `hvc1.` as the missing Dolby Vision `dvh1` tag. It is not:
the reference writes `hvc1` into *its* master playlist for every HEVC output, copy or not, and the
`dvh1` is a **muxer argument**, visible only in the sample entry of a produced fMP4 segment — read
back from one with `ffprobe` in the same run. So that line is parity and always was.

**Its sibling, `SUPPLEMENTAL-CODECS`, is absent here for a reason no emission can fix.** Both it
and the `dvh1` tag turn on a range *flavour* — the eight Dolby Vision spellings, or HDR10+ — and
[§3.1](spec.md#31-media-sources)'s inspection derives a range from a stream's colour transfer
characteristics, which can produce three answers and none of those. On every source this server
can describe, the reference sends no `SUPPLEMENTAL-CODECS` either, so writing one would have been
a branch nothing reaches. The real divergence is one layer down and is recorded as
[behaviours §5.10](../../docs/compatibility/behaviours.md): a Dolby Vision file is inspected here
as the HDR10 file its colour metadata claims.

**And the fixture world had no HDR source at all**, which is why the branch had nowhere to be
proven in the suite either. Generating one costs about a tenth of a second and two details that
each cost a run to find: the colour statement has to reach the *encoder* as well as the muxer — an
`-color_trc` alone leaves libx264 writing no transfer, so ffprobe reports the primaries and the
matrix and not the one field that decides the answer — and **the Matroska muxer drops it**, so an
HDR fixture has to be mp4 or it probes back as standard range. The entry is h264 rather than hevc
on purpose: the branch reads the transfer and nothing about the codec, and `rejected_video` is the
matrix's one entry whose codec nothing else has.

### Amended — 2026-09-05: two refusal tables that had tests and no criterion, and AC-32's count

**§5 could not name a single one of the eight tests under this feature's two refusal tables**, so
every one of them could have been weakened or renamed and nothing would have failed. Found as M7
and M8 of the [2026-09-04 audit](../../docs/audits/2026-09-04.md), which reports them as one class
of ten across six features: the acceptance map checks that a named test *exists* and never that a
behaviour *has* a name.

**Both tables state their rule already**, with the probe run that measured them, so neither needed
§3 before it could have §5. **AC-33** is §3.7's six rows for the segment route restated as a claim —
six rows and five refusals: the empty `401`, three in the delivery family's third shape, the
framework's own problem details for the two required parameters, and the row that is *not* a
refusal ending it, because a `playlistId` nothing named decides nothing and validating it would be
an invented refusal. **AC-34** is §3.3's
two, on both the `POST` and the `GET`: the `404` that agrees with `GET /Items/{itemId}`'s own body
and the `401` that has no body at all because it is refused before the route runs. The table's
other two rows are AC-31's and AC-5's and are named as such rather than restated.

**M7 also made a neighbouring criterion false, and that is the part worth remembering.** T11 added
the segment route's table to §3.7 and extended nothing, so AC-32 went on saying `/universal` and
the two playlist routes are *"the three delivery routes that refuse without a token"* while
`FEATURE_008`'s row 32 named `test_the_segment_route_requires_a_token` — a test the criterion's own
text excluded. **A map row can be populated and dishonest at the same time**, and the check that
would have caught it is the one this file's own T14 note describes: read the criterion against the
tests, not the tests against each other. AC-32 now says four, and names the three HLS routes as a
family so the count moves with §3.7 rather than with a list somebody remembered.

**No behaviour changed and no `src/` file was touched.** §5 now numbers thirty-four criteria.

---

## Definition of done

The feature is done when **all** of these hold:

- [x] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all
      thirty-four — has a passing test, by name, in `FEATURE_008`. *(Count corrected on 2026-09-05 by the 2026-09-04 audit's C9, which found it stale in 10 of the 12 features: this is a live claim about §5, not a record of the tick — 007 T13's precedent, and it is held by a test now.)*
- [x] Every endpoint reaches the level [spec §6](spec.md#6-conformance) declares: the four L3
      routes carry goldens (per profile class, per constraint class, headers and the range
      matrix), and transcoded output is asserted against the profile it was negotiated for —
      never byte-compared with the reference. **The differential half of L3 is
      [010](../010-conformance-harness/)'s**, as it is for every feature before this one; what
      it will be asked is below.
- [x] The eleven routes are served, `"008"` is in `IMPLEMENTED_FEATURES`, `INTERIM_008` is
      gone, and no route exists outside
      [`surface.yaml`](../../docs/compatibility/surface.yaml).
- [x] Every ffmpeg the server can start is owned by a session in the `TranscodeManager`, with
      a stop route, a ping timeout, a disconnect path and a shutdown sweep each proven by a
      test — and scratch space survives none of them.
- [x] The **four** delivery divergences ship as behaviours records them (§2.20 static bytes,
      §3.7 the honoured ceiling, §3.8 the answered codec-less request, and §3.3's last
      paragraph — a progressive re-encode produced to a pipe carries no MP3 `Xing`/`Info` frame
      and no completed FLAC `STREAMINFO`, where the reference's file-backed body carries both),
      and no other response differs observably from the measured reference, **except a Dolby
      Vision or HDR10+ source's master playlist and copied segments**, which
      [behaviours §5.10](../../docs/compatibility/behaviours.md) records as a gap in what a file
      can be inspected *as* rather than as a decision about what to emit. **This bullet said
      three and it was wrong when it was written**: the fourth is the only divergence in this
      feature that runs away from the reference rather than towards it, and T14 found it by
      checking the sentence rather than by trusting it. T15 found the exception the same way,
      by measuring the one branch of the master playlist nothing had reached.
- [x] The owed readings are paid with citations in place: the `ETag` derivation (T3), the
      cadence rule (T10), the kill-timer constants (T12), the WAV prior-probes upgraded (T9),
      and the negotiation error table's first two rows cited (T5).
- [x] Anything learned during implementation is back in `spec.md`, `plan.md` or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) in the same change that
      learned it, with provenance.
- [x] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

---

## What this feature owes the next ones

**010** collects the most, because a differential is the only thing that can ask most of these.
Every row is a place where a request answered here and a request answered there differ on purpose,
or where nothing has yet compared them:

* **The progressive-remux sizing divergence.** A remux whose size is knowable answers
  `Content-Length` and honours `Range` here; the reference answers chunked with
  `Accept-Ranges: none`
  ([behaviours §3.3](../../docs/compatibility/behaviours.md#33-progressive-transcoding-responses-carry-no-content-length-or-accept-ranges--class-c)).
  A differential comparing headers will flag it on the first remuxed request, and the entry is the
  answer.
* **The piped re-encode's missing self-description**, the same section's last paragraph and the one
  divergence pointing the wrong way: no `Xing`/`Info` frame on a progressive MP3, no completed
  `STREAMINFO` on a progressive FLAC. A differential over *bodies* will not see it — spec §6
  declines to byte-compare produced media — so it is a **named** comparison rather than one the
  harness finds: parse the first frames of both servers' progressive MP3 and compare the header
  frame's presence, not the bytes after it.
* **The delivery-time policy refusal** ([behaviours §2.21](../../docs/compatibility/behaviours.md#221-playback-policy-permissions-are-negotiation-inert)).
  On any account with a denied playback-processing permission, a video delivery that would
  re-encode the denied stream is **refused** here and **force-copied** there — the reference
  rewrites the codec to a copy two calls before the refusal it also carries, which is why that
  refusal is unreachable upstream. A differential run as a restricted user sees a `500` in the
  third error shape where the reference sends bytes, and this is the row to check it against.
  **Still owed on 2026-09-02, and now with the reason it is hard.** The named comparison that
  exists asks `/Videos/{itemId}/stream.mp4`, which takes no user here at all, so both servers
  answer `200` and the refusal is not in that answer. Reaching it means asking the **segment**
  route, whose URI has to be built by hand: the reference's own negotiation hands a denied seat no
  `TranscodingUrl` to follow, which is precisely why this edge has survived unmeasured.
* ~~**A listing's `MediaSources` carry no playback permissions**~~ — **paid on 2026-09-02 by
  005**, one change across all fifteen places that build the item context rather than on the route
  it was noticed on. `api/item_dto.py`'s `BuildContext` gained a **required** `policy`, and its
  emitter calls this feature's own `unnegotiated_transcoding` and `unnegotiated_direct_stream`
  rather than restating them, so the listing and the profile-less negotiation cannot drift apart.
  The measurement that closed it added three facts to
  [behaviours §2.21](../../docs/compatibility/behaviours.md#221-playback-policy-permissions-are-negotiation-inert):
  an un-inspected source is not exempt, the policy is the **effective** user's, and a request
  naming no user is the token holder's rather than none.
* **behaviours §3.7 and §3.8's divergent answers** — a sample-rate ceiling met exactly rather than
  from the Opus ladder, and a codec-less `/universal` transcode answered with a real stream rather
  than an empty `200`. Both narrow: §3.8's difference exists only where a client names a
  transcoding container and no codec (T8).
* **behaviours §3.9, §3.10, §3.11** — an unparseable `mediaSourceId` answered `400` where the
  reference answers `500`; a segment whose declared duration is the duration it holds, where the
  reference declares the scaled cadence and produces the unscaled one; and a stopped transcode that
  drops its `TranscodingInfo`, where the reference leaves the object in place less two keys until
  playback is reported stopped. `TranscodingInfo` is eleven properties here and thirteen there, the
  two missing being the ones read out of the encoder's progress output.
* **`BANDWIDTH` in the master playlist is this server's own encoder target**, where the reference
  advertises a rate scaled between the input and output codecs (T10). With one variant nothing
  selects on it, so it is a number a differential will report and no client reads.
* **A multi-part film answers one media source per part**, where the reference answers one source, a
  `PartCount` and a separate `GET /Videos/{id}/AdditionalParts` that is not on the surface (T3,
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)). No library
  reachable from here has one, so a differential needs a fixture built for it.
* **OQ-5, which was moved here at the spec review**: which `/universal` parameters clients actually
  send. It is a question about clients, and the harness is where clients are watched.
* **The four stream properties v1 does not emit** — the localised `DisplayTitle` family, `IsAVC`,
  `TimeBase` and `NalLengthSize` — will be a key-set difference on every stream of every item.

**011 — [subtitle delivery](../011-subtitle-delivery/)** takes the two findings the video client's
own table grouped, and 008 leaves it three things:

* **`SubtitleStreamIndex` is not a delivery parameter at all.** It binds on the `PlaybackInfo` body
  and on the playstate reports and appears nowhere in `api/delivery.py`, so a delivery request
  carrying it is dropped in silence ([behaviours §1.12](../../docs/compatibility/behaviours.md#112-an-unrecognised-query-value-is-ignored-not-rejected)).
  It costs nothing today only because there is no subtitle to select, and it will not announce
  itself the day there is: whoever announces the tracks owns this line.
* **The master playlist announces one variant and no `#EXT-X-MEDIA` tag**, and
  `EnableSubtitlesInManifest` is not a field of the profile model, so it is dropped on arrival. The
  manifest is the only lever that reaches the video client, and it costs the WebVTT extraction 008
  excluded.
* **[behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s subtitle row is
  corrected but not closed.** It now says what v1 does — embedded tracks survive a direct play or an
  on-device remux because they are inside the bytes, server HLS carries none, and a sidecar file is
  unreachable — and 011 is the mechanism named in it.

**009 — playlists** inherits almost nothing, and the one thing it must not do is add a second
negotiation. A playlist's items are items: they negotiate through `POST /Items/{itemId}/PlaybackInfo`
and deliver through the same eleven routes, and a queue that built its own `TranscodingUrl` would be
the fork the ladder was made pure to prevent. The one operation the music client calls that is
outside the 55 — `POST /Items/{itemId}`, how it renames a playlist — is
[handed to 009's spec review](../../docs/compatibility/client-embeat-mobile.md#7-where-these-findings-go),
not promoted here.

**A feature whose first act is a measurement session** — the one the two client traces route their
remaining findings to — inherits four things 008 measured and did not act on, plus one it shipped:

* **A media source with no stored inspection is skipped whole**, keeps the model's default
  `SupportsDirectPlay: true` and gets no `TranscodingUrl`: a dead end for the video client and four
  silently absent features for the music one. Shipped by 008 and now recorded as a §5 gap; the
  branch decision is not.
* **`transcodingProtocol` is compared case-insensitively on `/universal` and case-sensitively on the
  video path**, so a profile spelling its protocol `"Hls"` gets a progressive URL. Whether the
  reference binds that property to an enum — .NET matches enum names case-insensitively — is one
  `PlaybackInfo` request away and decides whether this is a gap or a nicety.
* **`GET /Sessions` declares no `deviceId`**, so the parameter is dropped and an administrator
  matching on `NowPlayingItem.Id` alone can read another device's `TranscodingInfo` as its own.
  Whether the reference filters on it, and how it behaves for a non-administrator, is unmeasured.
* **The fMP4 initialisation segment restarts a running encoder** — faithfully, which is the
  expensive kind: `media/sessions.py`'s first restart branch is `index == INITIALISATION_INDEX`
  with no condition, so every resumed fMP4 playback pays for a wasted transcode start. A
  [behaviours §3.0](../../docs/compatibility/behaviours.md#30-how-the-decision-is-made) decision,
  taken on a probe.
* **Where a progressive re-encode is produced** — the pipe — is one question the music client asks
  three ways: the missing `Xing` frame, an honest `Content-Length` on a capped stream, and caching a
  transcode on a client-supplied `PlaySessionId`. Only the first is a parity gap; the other two are
  Principle I questions and are recorded as such.

**Two things are owed to nobody in this list, and they should not be lost.** The audio HLS pair —
`/Audio/{itemId}/master.m3u8` and `/main.m3u8` — is what `/universal` with
`transcodingProtocol=hls` needs before it can answer anything, and adding it is a surface decision
under AGENTS.md's "Adding an endpoint" procedure, spec first (T10). And **the audio-bitrate default
table** T5 left owed is still owed: a stream reporting no bitrate takes no share of the cap here,
where the reference substitutes a default keyed on the target codec and the channel count, so
`AudioBitrate` is absent from the `TranscodingUrl` and `VideoBitrate` is the whole cap. T8 and T9
each established it was not theirs.

**The starting inventory this feature leaves behind:** the whole ladder is one pure function in
`media/decision.py` with a fifty-six-row table behind it and no I/O; command construction is
`media/ffmpeg.py` and every process the server can start is owned by a `ProductionLedger` a sweep
enforces (`tests/unit/test_import_directions.py`); playlists and segment boundaries are arithmetic
in `media/hls.py` with no process behind them; and the fixture world is **real media** —
`tests/fixtures/media.py`'s matrix, generated bit-exactly and scanned by the real 003 pipeline, so
"the delivered bytes" is a measurement rather than a fixture's word.
