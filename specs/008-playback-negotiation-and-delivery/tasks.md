---
feature: 008-playback-negotiation-and-delivery
title: Playback negotiation and delivery — tasks
status: Accepted
created: 2026-08-29
updated: 2026-08-29
accepted: 2026-08-29
amended: 2026-08-29 at the gate — the fixture world turned out to have no files behind any item, CI has no ffmpeg, the negotiation error table's first two rows are uncited, and the MediaSources emitters already exist as declared gaps; see "What the gate changed"
plan_status_required: Accepted
plan_status_actual: Accepted
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
3.004 s is T10's, the kill-timer constants are T12's, the per-route refusal shapes are measured
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

- [ ] **Changes:** `library/scan.py` grows the inspection step behind 003's change signal — the
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

## T4 — `media/decision.py`: the ladder, pure, and the table that proves it

- [ ] **Changes:** new `src/atrium/media/decision.py` with the contracts
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
  a single denied permission changing nothing, the empty profile answering direct play, the
  nothing-plays profile answering `NONE` with no reasons for a URL. No HTTP, no database, no
  process: `tests/unit/test_import_directions.py`'s `PURE_WHEREVER_THEY_LIVE` — the tuple that
  already holds `library/identity.py` to the no-I/O rule outside `domain/` — gains
  `media/decision.py` (and T10 adds `media/hls.py` beside it).
- **Spec reference:** §3.2, §3.3, §3.4; plan §5, §6.2

## T5 — `PlaybackInfo`: the negotiation routes, and the URL a client parses

- [ ] **Changes:** new `src/atrium/api/media_info.py` — `POST` and
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
  over the scanned world (empty profile, accepts-all, container-reject, codec-reject,
  nothing-plays), each pinning flags, `TranscodingUrl` presence and its exact query-string
  anatomy; the switch cases (`EnableDirectPlay: false` flips per request; `EnableTranscoding:
  false` does not); the policy cases through a user whose policy the test sets (all-three
  denied → flags down, no URL, no `ErrorCode`); and the refusal shapes as the battery measured
  them. `python3 tools/probe_playback_info.py --allow-writes` stays green with its new battery.
- **Spec reference:** §3.2, §3.3; AC-1..AC-6, AC-31 (negotiation half), AC-30's first hop

## T6 — `compat/ranges.py` and static delivery: the measured matrix, one function

- [ ] **Changes:** new `src/atrium/compat/ranges.py` — `negotiate_range(header, size)`
  answering exactly the [spec §3.5](spec.md#35-delivery-the-rules-that-apply-to-every-route)
  table (multi and reversed → full body, suffix honoured, `416` with `Content-Length: 0`); new
  `src/atrium/api/audio.py` and `src/atrium/api/videos.py` carrying the four `stream` routes'
  **static** halves: the untouched source bytes, `Content-Length` equal to the file size,
  `Accept-Ranges: bytes`, the path suffix choosing the `Content-Type` label and nothing else,
  authentication by any of the four mechanisms with `?api_key=` the working case. A
  non-static request answers behaviours §1.11's controller refusal *in this task only* — an
  explicitly temporary state, safe because `"008"` is not yet in `IMPLEMENTED_FEATURES` and no
  conformance is claimed for the route; T7 replaces it with the real behaviour.
- **Depends on:** T1, T3
- **Verified by:** new `tests/conformance/test_static_delivery.py` — the range matrix
  table-driven over one fixture film (AC-11..AC-14: `bytes=100-199` is `206` with exactly 100
  bytes; the matrix's full-body and `416` rows byte-exact); `stream.mkv?static=true` on the mp4
  fixture serves mp4 magic bytes behind `video/x-matroska` (AC-18, behaviours §2.20); a
  tokenless request refuses and `?api_key=` succeeds; item-level `Container` vs the source's
  asserted on the same item (AC-28).
- **Spec reference:** §3.5, §3.6, §3.7 (static halves); AC-11..AC-14, AC-18, AC-28

## T7 — Progressive delivery: the remux is sized, the re-encode is chunked

- [ ] **Changes:** new `src/atrium/media/ffmpeg.py` — command construction from a `Decision`'s
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

## T8 — `/universal`: synthesised profiles and three recorded divergences

- [ ] **Changes:** new `src/atrium/api/universal_audio.py` — the parameter set synthesised into
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

## T9 — WAV: both symptoms answered with a real header, and the prior-probe debt paid

- [ ] **Changes:** the PCM path in `media/ffmpeg.py` and the two routes: `stream.wav` (and
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

## T10 — `media/hls.py`: predicted playlists, and the two cadences

- [ ] **Changes:** new `src/atrium/media/hls.py` — `plan_segments` (uniform cadence for an
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

## T11 — The `TranscodeManager` and the segment route: production with an owner

- [ ] **Changes:** new `src/atrium/media/sessions.py` —
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

## T12 — The kill paths: a stop that stops, and scratch that dies with its session

- [ ] **Changes:** new `src/atrium/api/hls_segment.py` — the reference's `HlsSegmentController`
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

## T13 — The operator knobs, and policy at delivery

- [ ] **Changes:** `config/settings.py` grows the encoding section with the reference's names
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

## T14 — The acceptance map, the exact route set, and 008 is Implemented

- [ ] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_008` — thirty-one
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

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all
      thirty-one — has a passing test, by name, in `FEATURE_008`.
- [ ] Every endpoint reaches the level [spec §6](spec.md#6-conformance) declares: the four L3
      routes carry goldens (per profile class, per constraint class, headers and the range
      matrix), and transcoded output is asserted against the profile it was negotiated for —
      never byte-compared with the reference.
- [ ] The eleven routes are served, `"008"` is in `IMPLEMENTED_FEATURES`, `INTERIM_008` is
      gone, and no route exists outside
      [`surface.yaml`](../../docs/compatibility/surface.yaml).
- [ ] Every ffmpeg the server can start is owned by a session in the `TranscodeManager`, with
      a stop route, a ping timeout, a disconnect path and a shutdown sweep each proven by a
      test — and scratch space survives none of them.
- [ ] The three delivery divergences ship as behaviours records them (§2.20 static bytes,
      §3.7 the honoured ceiling, §3.8 the answered codec-less request), and no other response
      differs observably from the measured reference.
- [ ] The owed readings are paid with citations in place: the `ETag` derivation (T3), the
      cadence rule (T10), the kill-timer constants (T12), the WAV prior-probes upgraded (T9),
      and the negotiation error table's first two rows cited (T5).
- [ ] Anything learned during implementation is back in `spec.md`, `plan.md` or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) in the same change that
      learned it, with provenance.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.
