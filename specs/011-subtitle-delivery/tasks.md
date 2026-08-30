---
feature: 011-subtitle-delivery
title: Subtitle delivery — tasks
status: Accepted
created: 2026-08-30
updated: 2026-08-30
accepted: 2026-08-30
amended: 2026-08-30 at the gate — 008's amendment of the same day gave the master playlist more than one variant and the subtitle group belongs on all of them; the codec spelling the text/image split reads is not the spelling this server stores; ffmpeg cannot encode the image subtitle track the fixture needs; and the sidecar language rule's "eight regional rows" are nine, two of which are not regional. See "What the gate changed"
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 011 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries six structural decisions.** The first is the one every feature since 008
has needed: **the world gets subtitles before anything reads one.** No file in
`tests/fixtures/media.py`'s matrix carries a subtitle track of any kind, so every criterion here
has nothing to run on until T1 builds one — and one of the three things T1 has to build cannot be
encoded at all (see "What the gate changed").

**The two numbers land before any address carries one.** An external subtitle stream is numbered
*ahead of* the container's own ([spec §3.6](spec.md#36-subtitles-beside-the-media)), so a file
dropped beside a film renumbers every audio and video index — and 008's delivery addresses already
carry those indices. T3 is the pure `renumber` and the filename rule with their tables; T4 is the
table, the migration and the scan's second change signal. Both land **before** any route that
names a stream index, so nothing in this feature is ever built on an index that means two things
on either side of a scan.

**The pure core is green before any process and before any route.** The filename rule (T3), the
cue list (T5) and the display title (T10) are functions over values with table tests, which is
what makes [spec §6](spec.md#6-conformance)'s *"asserted cue by cue"* a table rather than a server
test. `media/extract.py` (T6) is the one impure module and it exists only to make a file readable.

**The addresses land bottom-up, because each one addresses the next.** A manifest entry names a
playlist, a playlist entry names a fetch, and [plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)
is explicit that this ordering does not depend on the one open question §7.2 leaves to the video
client's author: the fetch routes (T7) are a prerequisite of a playlist that leads anywhere (T8),
which is a prerequisite of a manifest that leads anywhere (T11). AC-8's traversal is the last hop
and it belongs to the task that closes the loop.

**The manifest is the feature, not a line inside it.** The master playlist route does not accept
the manifest flag at all — OQ-1 died on that — so the **only** lever is `SubtitleMethod=Hls` beside
a `SubtitleStreamIndex` in the delivery address, which is the client-side track override
[client-atrium-tvos §4.3](../../docs/compatibility/client-atrium-tvos.md#43-the-clients-track-override-works-for-audio-and-is-dropped-for-subtitles)
sized as *"a line inside §4.2"*. Binding the two parameters (AC-4) and announcing the tracks
(AC-5) are therefore one task, T11, and it is the largest here.

**Routes land across three tasks, so the exact-set check carries an interim list.**
`test_no_route_ships_ahead_of_its_feature` asserts the served routes equal the surface of the
implemented features, and [`surface.yaml`](../../docs/compatibility/surface.yaml) already carries
the three 011 rows from the spec gate — so the check fails from the first route until the last
task. T7 and T8 each add to an explicit `INTERIM_011`, the device 002, 005, 006, 007 and 008 each
used and each deleted, and T12 deletes it by putting `"011"` in `IMPLEMENTED_FEATURES`.

**Every owed reading from [plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)
has an owner here.** The two that are corrections to the accepted spec rather than gaps in it are
T7's (the same-format short circuit against AC-10) and T8's (the playlist route's
malformed-identifier row naming `itemId` and not `routeItemId`), and each is settled by one row of
an existing probe battery in the change that lands the route it concerns. The five smaller ones
are T8's (a source with no runtime), T11's (the lower-case spelling of `SubtitleMethod`), T7's
(`ttml`, and the fetch formats' media types read off a run rather than off a paragraph) and T3's
(the `hin` branch of the sidecar name rule). `SubtitleCodec` and the reference's internal metadata
directory stay out and are recorded below as out of scope rather than owed.

**Two things are deliberately not here.** OQ-9 and OQ-10 are the author's to settle, they are not
requirements, and [spec §5](spec.md#5-acceptance-criteria) says so in the paragraph that follows
its sixteen criteria; no task below turns either into work. And the one open question
[§7.2](spec.md#72-the-one-question-no-probe-here-can-answer) leaves with the video client's author
— whether it fetches a whole-file subtitle when the manifest carries none — is answered by nobody
here and nothing below depends on it.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files they
reference on 2026-08-30 before being accepted. Four things changed, and the first is the one the
plan could not have accounted for because it landed after the plan was accepted:

| The draft said | It was |
|---|---|
| The `#EXT-X-MEDIA` block is announced and **the** variant line gains `,SUBTITLES="subs"` last ([plan §6.5](plan.md#65-the-manifest-extends-008-64), [spec §3.4](spec.md#34-the-manifest), AC-5) | **There is more than one variant line now.** 008 was amended on 2026-08-30 (its T15, merged as `cab9443`): against an HDR source whose video is stream-copied, `media/hls.py`'s `master_playlist` appends an h264 SDR entrance beside the copy, so the master carries **two** `#EXT-X-STREAM-INF` lines where it carried one. The reference hands its `subtitleGroup` to *every* one of its own `AppendPlaylist` calls — the copy, the h264 entrance, the two codec entrances, the level-5.0 rewrite and both adaptive-bitrate variants `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:213-315, 325-345 @ v10.11.11]`, confirmed on the wire against an HDR film negotiated for a copy: three variants, all three ending `,SUBTITLES="subs"` `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`. Written as one line, the SDR entrance — which exists precisely so that a client that cannot render HDR has somewhere to go — would be the one variant offering no subtitles. Plan §6.5, spec §3.4 and AC-5 are corrected to **every** variant line in this change; T11 renders it through `_variant` and folds the HDR case into `probe_subtitle_manifest.py`, whose `_variant_line` returns the **first** `#EXT-X-STREAM-INF` and only that one, which is why the gate's own probe could not have seen this |
| The text/image split is a lookup on the codec spelling, so no column and no migration is needed ([plan §6.1](plan.md#61-the-two-file-facts-extends-008-61), [spec §3.2](spec.md#32-which-streams-are-subtitles-and-which-of-those-are-text)) | **Not the spelling this server stores.** The reference **renames four subtitle codecs during inspection** — `dvb_subtitle`→`DVBSUB`, `dvb_teletext`→`DVBTXT`, `dvd_subtitle`→`DVDSUB`, `hdmv_pgs_subtitle`→`PGSSUB` `[source: MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:632-652, 765-768 @ v10.11.11]` — and only then does the substring rule read them. `media/probe.py` stores ffprobe's `codec_name` verbatim, and `"dvd_subtitle"` contains no `dvdsub`: applied as written, **every DVD and digital-broadcast bitmap subtitle track in a library is announced as text**, offered in a manifest and offered for conversion, which is AC-1 and AC-7 failing together. *(Corrected at T2 from "every DVD and DVB": only `dvd_subtitle` and `dvb_subtitle` invert. `hdmv_pgs_subtitle` already contains `pgs` and `dvb_teletext` is text either way - so the two that do not move are the two a fixture could have been built on, and the split alone cannot prove the rename.)* The four normalised spellings are also what `Codec` carries on the wire — `PGSSUB`, `DVDSUB` and `DVBTXT` all appear beside `subrip`, `ass` and `webvtt` on a real library `[probe: tools/probe_sidecar_subtitles.py, Jellyfin 10.11.11, 2026-08-30]` — so this is a property **008 already emits differently** and no fixture had a subtitle stream to catch it. T2 owns it, normalises where the reference does, and migration 0007 rewrites the four spellings in `media_streams` |
| The fixture gains an embedded **image** subtitle track ([plan §8](plan.md#8-testing-strategy)) | **ffmpeg cannot make one.** There is no PGS encoder, and a text-to-bitmap conversion is refused outright — `Subtitle encoding currently only possible from text to text or bitmap to bitmap` — so `-c:s dvdsub` over an `.srt` fails and the matrix's generate-with-ffmpeg rule has nothing to ask for. Measured at the gate: a **434-byte PGS bitstream written by hand** — five segment types, one 32×8 run-length object, four display sets (one that draws and one that erases, per cue; this row said two, and T1 reproduced the byte count exactly and counted them) — demuxes as `hdmv_pgs_subtitle` and muxes into Matroska beside a `subrip` track with `-c:s copy`. T1 builds it that way, and the entry that carries it is Matroska because mp4 accepts neither PGS nor DVD subtitles. It is still *generated, never checked in*, which is what the fixture module's own rule asks for |
| A sidecar's language is the culture row's `Name` when it contains a `-` — *"the eight regional rows, `zh-hk` and its siblings"* ([plan §6.2](plan.md#62-discovery-the-name-rule-and-the-two-numberings-extends-003-64-and-008-61) step 4) | **Nine of the 192 rows, and two of them are not regional tags at all**: `Greek, Modern (1453-)` and `Luba-Katanga`, both in `metadata/cultures.py` and both in what `/Localization/Cultures` serves. The rule is the reference's own `[source: Emby.Naming/ExternalFiles/ExternalPathParser.cs @ v10.11.11]` and reproducing it is parity — a Greek sidecar's language *is* written `Greek, Modern (1453-)` there — but "eight regional rows" describes a table this project does not have, and the two non-regional rows are table rows of T3's matrix rather than a footnote |

And two things the review confirmed rather than changed, each worth a line because a task would
otherwise re-derive it:

* **The two file facts change the golden of every stream of every item, not only of subtitles.**
  `IsTextSubtitleStream` and `SupportsExternalStream` are non-nullable on the reference and are
  emitted as `false` on video and audio streams too, while `Score`, `DeliveryMethod`,
  `DeliveryUrl`, `IsExternalUrl` and `Path` are absent from a bare read and fall to the global
  null suppression `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`.
  So T2 is one edit to `MediaStream` and a golden rewrite, which is what plan §6.1's *"one edit to
  the model rather than seven insertions"* buys.
* **The manifest's token is not in `request.state`.** `api/deps.py` stores `token_sha256` and
  nothing else, so the address of a `#EXT-X-MEDIA` entry — which carries the caller's own token,
  and needs it, because the playlist route requires a caller and a player following a `URI` sends
  no headers — comes from `compat/auth.extract_token(request)`. Named here because the obvious
  place to look holds the hash.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — The world gets subtitles: two entries, one sidecar, and a bitstream ffmpeg will not encode

- [x] **Changes:** `tests/fixtures/media.py`'s `MediaFile` grows a subtitle declaration — per
  track, the codec, the language, the title and the three flags — and the builder writes them:
  a **text** track from a generated `.srt` of a known, tiny cue list, and an **image** track from
  a PGS bitstream the module writes itself (there is no encoder for one; see "What the gate
  changed"), muxed with `-c:s copy`. Two new matrix entries: one Matroska film carrying the text
  track **beside** the image track, and a second carrying a text track in `ass` — the format that
  cannot be converted *from*, which is what reaches `Encode` under a `vtt`-only profile (AC-3).
  A **sidecar** `.srt` goes beside the second, named to exercise the right-to-left read: an
  unclaimed token that becomes the title, a language token and a forced token. `GENERATOR_VERSION`
  is bumped, because the shape of what is generated has changed in a way the declarations do not
  express.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_media_fixtures.py -q` — every declared subtitle
  track ffprobes back to the codec, language, title and flags the matrix declares it for (the
  fixture's invariant test, the 007 T4 pattern), the image track probes as `hdmv_pgs_subtitle` and
  the text one as `subrip`, and two builds of each entry compare **byte for byte** (T1 of 008's
  lesson: bit-exactness is a property of where the flags sit on the command line, and it has to be
  re-proven for a muxer that is now writing a subtitle track). Plus `uv run pytest tests/ -q -m
  "not ffmpeg"` staying green, which is what proves the marker still fences everything needing the
  binary.
- **Spec reference:** §6 (fixtures); plan §8

**The sidecar must not go beside a film 008's tests already assert about.** Placing it there
renumbers that film's streams — this feature working correctly — and 008's `audioStreamIndex`
assertions would fail for a reason that looks like a bug in T3's renumbering. That is why both
entries are new rather than tracks added to `direct_play` or `long_take`.

**Done (2026-08-30).** The bitstream was the part this task was warned about, and it was the part
that went right: 434 bytes, first time, `hdmv_pgs_subtitle` on the nose. What cost two runs was
the ordinary half — **the two hazards are both about a subtitle track being treated as a stream
like any other, and both land on a file nobody was editing.**

**`-shortest` means the shortest stream, and a subtitle track is one.** The flag has been on every
video entry since 008 T1, where it was belt-and-braces: both synthetic sources already carry an
explicit duration, so nothing was ever bounded by it. Give the same entry a subtitle track whose
cues stop at 3.0 s and the four-second film comes out **3.007 s**, video and audio truncated to the
last cue — `duration` failing against its own declaration, on an entry whose subtitle assertions
all pass. It is dropped for an entry that declares a subtitle, and the invariant test's existing
duration row is what caught it.

**A bitstream that does not start at zero moves, and takes a cue off the track beside it.** ffmpeg
rebases each input on that input's own start time, so a PGS whose first display set sits at 0.5 s
arrives half a second early — every cue of it — and, under `-shortest`, the `subrip` track muxed
beside it keeps **one cue out of two**; at 1.0 s it keeps one of three. Nothing warns, both tracks
probe to the right codec and the right flags, and the symptom is on the *other* track. `pgs_bitstream`
refuses a late cue list rather than trusting a caller to remember, and the cue list every embedded
track carries therefore starts at zero. The sidecar's does not — nothing muxes it — which is what
gives §3.5's two window switches a source they can be told apart on.

Three smaller things. The gate's *"two display sets"* is four in a 434-byte file, one that draws
and one that erases per cue; the byte count reproduced exactly, so plan §8 and the row above are
corrected on the count and not on the number. An entry with a subtitle needs `-map` per stream,
because ffmpeg's own selection takes the best video, the best audio and **one** subtitle — an
entry with two would have silently shipped one, which is why the per-entry test now asserts the
subtitle count in both directions. And `-disposition:s:N` is written even when no flag is set: left
unstated, ffmpeg carries the input file's own disposition through, so *"no flags"* would have been
a property of the generated `.srt` rather than of the declaration.

## T2 — The two file facts, and the codec spelling the split actually reads

- [x] **Changes:** `media/probe.py` normalises the four subtitle codec spellings the reference
  normalises at inspection `[source:
  MediaBrowser.MediaEncoding/Probing/ProbeResultNormalizer.cs:632-652, 765-768 @ v10.11.11]`, and
  migration `0007` rewrites those four values in `media_streams` so a library scanned by 008 does
  not keep a spelling the wire disagrees with (the rest of 0007 is T4's). `media/info.py` gains
  the whole contiguous run between `Index` and `PixelFormat` in the pinned document's order —
  `Score`, `IsExternal` (already emitted), `DeliveryMethod`, `DeliveryUrl`, `IsExternalUrl`,
  `IsTextSubtitleStream`, `SupportsExternalStream`, `Path` `[spec: MediaStream]` — filling the two
  file facts and leaving the rest to their owners: `DeliveryMethod` and `DeliveryUrl` to T9,
  `Path` to T4, `Score` to nothing at all (plan §6.1: the reference scores only the streams a
  user's subtitle *mode* selected, and v1 keeps no mode). `IsTextSubtitleStream` is the substring
  rule with `microdvd` exempted; `SupportsExternalStream` is `is_external or is_text_subtitle or
  is_pgs`. `tools/probe_sidecar_subtitles.py` gains a **codec-spelling battery** that reports the
  `Codec`, `IsTextSubtitleStream` and `SupportsExternalStream` of every subtitle stream it can
  reach, which is the debt the gate's hand requests left.
- **Depends on:** T1
- **Verified by:** `uv run pytest tests/unit/test_media_info.py tests/conformance/test_media_shapes.py -q`
  — T1's image track answers `IsTextSubtitleStream: false` and its text track `true`, both answer
  `SupportsExternalStream: true` (PGS is servable alone and text is), and every **video and audio**
  stream in the rewritten goldens carries both as `false`. `uv run pytest tests/unit/test_migrations.py -q`
  for 0007's rewrite, up and down. And `python3 tools/probe_sidecar_subtitles.py` against a library
  holding an image subtitle track: the battery has to report `PGSSUB` or `DVDSUB` rather than
  ffprobe's own spelling, or the normalisation is in the wrong place.
- **Spec reference:** §3.2, AC-1; plan §6.1

**Done (2026-08-30).** The rename was correct and the **verification above could not have caught
it being wrong.** *"T1's image track answers `IsTextSubtitleStream: false`"* passes with the whole
normalisation deleted: `hdmv_pgs_subtitle` already contains `pgs`, and `dvb_teletext` is text under
either spelling — so **only `dvd_subtitle` and `dvb_subtitle` move**, and neither is a codec this
matrix can produce (ffmpeg has both encoders and refuses text-to-bitmap, which is T1's finding). The one image format the fixture matrix can build is precisely the one of the four the
rename does not rescue. What proves it is the stored **value** — the wire says `PGSSUB` where the
file says `hdmv_pgs_subtitle` — and a table over the four spellings beside their renamed forms,
which is a unit test rather than a fixture. The gate's row, spec §3.2 and plan §6.1 are corrected
from *"every DVD and DVB subtitle track"* to the two bitmap names.

**The second file fact inverts too, and it is not "not an image".** `SupportsExternalStream` is
`false` on `DVDSUB` and `true` on `PGSSUB` — a Blu-ray bitmap track can be served on its own and a
DVD one cannot — so the unrenamed spelling would have made every DVD track claim it was servable
as well as text. Measured on 947 subtitle streams of a real library, every one of which reproduces
both facts from its codec alone; and both are answered on **every stream of every kind**, `false`
on the 1 021 beside them that are not subtitles, cover art included.

**A data migration is invisible to the migration sweep, which reports it as a revision that
changed nothing.** `0007` rewrites rows and no columns, and `tests/unit/test_migrations.py`'s
*"{revision} changed nothing"* fired on it — correctly, for a check that reads the schema.
`DATA_ONLY` is now the same device `IRREVERSIBLE` already was: the sweep cannot see the change, so
the revision declares it in its docstring, and a revision that does nothing and says nothing still
fails. That declaration **comes out at T4**, which adds the table to the same revision and makes
it untrue; the migration's docstring says so.

**Telling a row apart, and migrating twice.** There is no flag: the value is the marker, because
the two spellings are disjoint — `codec = 'dvd_subtitle'` on a subtitle row is a pre-0007 row and
`DVDSUB` is a post-0007 one, and the inspection tool never emits the second. So the rewrite is
idempotent - a second pass finds none of the four names it reads - and the downgrade is exact. All
three are tests, and the idempotence one is a claim about the **table** rather than about the
migration runner: Alembic stamps a revision, so nothing can apply `0007` twice in a row, and what
makes a database migrated twice a database migrated once is that what it writes is outside what it
reads.

Two smaller things. The file is `0007_external_subtitle_streams.py`, the name plan §4 gives it,
even though T2's half of it is the codec rewrite — the table T4 adds is what the name is for.
And the four properties this task declares and does not fill (`Score`, `DeliveryMethod`,
`DeliveryUrl`, `IsExternalUrl`) are **absent from a bare read on the reference too** — on 0 of
1 968 streams — so declaring them costs no wire bytes today, and `Path` is on the 14 that came
from a file.

## T3 — Two pure tables: the filename rule and the two numberings

- [ ] **Changes:** `library/naming/external.py` — pure — reproduces the stem match and the
  right-to-left read of [spec §3.6](spec.md#36-subtitles-beside-the-media): the default and forced
  vocabularies match by **containment**, the hearing-impaired one by **equality**, the language
  lookup runs before the hearing-impaired vocabulary and matches a culture's display name, its
  name, either three-letter code or the two-letter code case-insensitively, first row wins
  `[source: Emby.Server.Implementations/Localization/LocalizationManager.cs:172-199 @ v10.11.11]`;
  the language written down is the culture row's `Name` when it contains a `-` and its
  terminological three-letter code otherwise; and the `hin` branch is reproduced whole — a second
  token that resolves to a language behind a first that resolved to Hindi takes the language *and*
  sets the hearing-impaired flag. `domain/media.py` gains `file_index` and `external_path` on
  `InspectedStream` and the pure `renumber(container, externals)`. `tools/probe_sidecar_subtitles.py`'s
  own reproduction gains the `hin` branch **and reports whether the library it ran against reached
  it**, the way `probe_transcode_decision.py` now reports a source's video range: a probe that
  cannot distinguish a measurement from a miss is how 008's OQ-7 came to answer for a branch it
  never touched.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_external_naming.py tests/unit/test_domain_media.py -q`
  — the filename matrix asserts language, three flags and title over a bare stem, a stem with a dot
  suffix, each flag vocabulary, `film.hi.srt` as Hindi, `film.spa.hi.srt` as Spanish **and**
  hearing-impaired, `film.forcedspanish.srt` as forced (containment) beside `film.hix.srt` as *not*
  hearing-impaired (equality), a Greek token written as `Greek, Modern (1453-)` and a
  Luba-Katanga one as `Luba-Katanga`, a token nothing claims becoming the title, an extension
  outside the nine, and a stem that is a **prefix** of another film's. `renumber`'s table asserts
  the property `-map` depends on: **every container stream's `index` exceeds its `file_index` by
  exactly the number of external streams**, which is the assertion that catches the whole class
  where "the indices are contiguous" would not.
- **Spec reference:** §3.6, AC-11; plan §5, §6.2

## T4 — The sidecars land in rows, and a default scan notices them

- [ ] **Changes:** migration `0007_external_subtitle_streams` gains `media_external_streams` as
  [plan §4](plan.md#4-data-model) declares it, reversible. **T2 created that revision** and it
  holds the codec rewrite; adding the table means deleting the *"until it does, this is a data
  migration"* paragraph from its docstring, because `tests/unit/test_migrations.py` reads that
  sentence as the declaration that the revision changes no schema — and once the table is there it
  is not true. `library/walker.py` grows a third
  output — every file carrying one of the nine subtitle extensions, statted like a candidate,
  **still reported as skipped** so the operator-facing count does not move. `media/probe.py` gains
  `inspect_subtitle`, because `.sub` is a text format or an image one depending on the bytes and
  that is the split T2 turns on. `db/repositories.py`'s `MediaProbeRepository` gains
  `put_external` — replacing the whole set for one media file, never merging — and returns
  **renumbered** inspections from `get` and `current`, so a caller cannot obtain an un-renumbered
  one. `library/scan.py` gains the second comparison: the set of `(external_path, size, mtime_ns)`
  the walk found beside a candidate against the set stored, re-inspecting the sidecars when they
  differ **whatever the media file's own signal says**. `media/info.py`'s `Path` is filled for the
  discovered streams and stays absent on container ones.
- **Depends on:** T1, T2, T3
- **Verified by:** `uv run pytest tests/library/test_sidecar_discovery.py tests/unit/test_repositories.py tests/unit/test_migrations.py -q`
  — the mutation test in 003 AC-11's own shape. **T1 ships the sidecar inside the built tree**, so
  the "before" state is made rather than found: copy the tree out, delete the sidecar, scan, assert
  the indices; put it back, scan again with a **default** scan, assert the discovered stream at
  index 0, the video and audio each moved by one, `HasSubtitles` true and the film's own
  `(size, mtime_ns)` untouched; delete it again, scan again, assert every index back where it was
  and the item's user data unchanged (AC-11, AC-12). The middle scan being a default one is the
  whole point: run deep and the test passes with the second signal deleted. `BuiltMedia.copy_into`
  is the supported way to get a tree that may be written to, and `sidecar_path_of` names the file.
- **Spec reference:** §3.6, AC-11, AC-12; plan §4, §6.2

## T5 — `media/subtitles.py`: the cue list, and the labels beside it

- [ ] **Changes:** `media/subtitles.py` — pure — with `Cue`, `parse` over the three readable
  families, `window` (skip-while / take-while as **prefix** operations rather than predicates,
  which is what the reference does and what answers a different set of cues on a real file), and
  `render` answering **bytes** for the writable set, byte order mark included where the
  reference's stream writers emit one and absent from `json`. `media/labels.py` gains the subtitle
  rows rather than a second table beside it — it is already named in
  `tests/unit/test_import_directions.py`'s `PURE_WHEREVER_THEY_LIVE`, and `media/subtitles.py`
  joins it there.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_subtitle_cues.py -q` — the cue matrix: parse each
  readable format, window with and without the copy switch (a cue 36.1 s into the file at 6.1 s in
  a window starting at 30 s without it and at 36.1 s with it), an end position before a start
  answering no cues, the time-map rewrite **and the byte order mark it drops**, and every writer's
  output re-parsed back to the same cues (AC-9, AC-10, AC-14).
- **Spec reference:** §3.5, AC-9, AC-10, AC-14; plan §5, §6.7

## T6 — `media/extract.py`: one process, one cache entry, one lock

- [ ] **Changes:** `media/extract.py` — the one impure module — with `readable(...)`: an external
  stream in a covered format read from its own file with its **encoding detected** rather than
  assumed; an embedded stream, or an external `.mks`, extracted by one ffmpeg invocation to `srt`
  (or to its own spelling where the codec is `ass` or `ssa`); an external stream in a text format
  the parsers miss normalised to `srt`; and an **image** stream raising before any process starts.
  Every invocation goes through 008's `ProductionLedger`, so the module imports no `subprocess`
  and is named beside `media/sessions.py` in `test_import_directions.py`'s
  supervised-through-the-ledger check — a module that starts processes and is not named there
  passes the sweep by accident. The artefact lands in `cache/subtitles/<digest>.<format>`,
  published by rename, with a per-digest lock so a playlist's hundred windows fetched in a burst
  wait on one extraction rather than starting a hundred.
- **Depends on:** T2, T5
- **Verified by:** `uv run pytest tests/unit/test_subtitle_extract.py -q -m ffmpeg` — the embedded
  text track of T1's Matroska entry comes back as the cue list T1 declared; a second call for the
  same key starts no process (asserted against the ledger, not against a timing); a hundred
  concurrent calls for one key start **one**; the image track raises before the ledger is ever
  touched; and `uv run pytest tests/unit/test_import_directions.py -q` for the sweep.
- **Spec reference:** §3.5, AC-14; plan §6.7

## T7 — The two fetch routes, the format battery, and the short circuit that contradicts AC-10

- [ ] **Changes:** `api/subtitles.py` with `GetSubtitle` and `GetSubtitleWithTicks` sharing one
  handler, the path's start position taking the place of the query's. **Neither requires a
  caller** — measured `200` with no credential at all — so both resolve the item through
  `MediaFileRepository` by identifier alone and neither applies a visibility predicate; both
  accept the token in the query string, which is how every address this feature emits works at
  all. `js` is an alias for `json`, mapped first; a format outside the writable set is the
  controller refusal at `400` before any file is opened; `ttml` **is** in the writable set,
  because the reference writes it `[source:
  MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:259-302 @ v10.11.11]` and leaving it out
  would invent a refusal. Routes join `INTERIM_011`.
  **Two things the route settles that the plan handed to this gate**, both by one row of
  `tools/probe_subtitle_delivery.py`'s existing format battery and both correcting the accepted
  documents in this same change: the **same-format short circuit** — a windowed fetch whose
  requested format equals the format the track is already in answers the whole track, unwindowed
  and unrebased `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:144-155 @
  v10.11.11]` — so **AC-10 is amended** to say what is true of every window a client reaches by
  following an address and what is true of that one; and `ttml`, which the battery has never
  asked for. The battery also **prints the `Content-Type` of every format it fetches**, and the
  media types land in `media/labels.py` read off that run rather than off plan §6.8's paragraph.
  [Spec §3.7](spec.md#37-error-paths)'s image row gains what Atrium answers and when.
- **Depends on:** T4, T6
- **Verified by:** `python3 tools/probe_subtitle_delivery.py` — the battery's new rows answer, and
  the two readings become measurements. Then `uv run pytest tests/conformance/test_subtitle_fetch.py -q`:
  cue-level assertions against T1's known cues, whole and windowed, both timestamp switches, both
  spellings of the path, determinism (AC-14), and the fetch column of §3.7's table driven row by
  row — status, content type and body bytes, including the four `500`s and the `200` with no cues.
- **Spec reference:** §3.5, §3.7, AC-9, AC-10, AC-13, AC-14; plan §6.7, §6.8

## T8 — The playlist route, the invariant decimal point, and a refusal that names the wrong parameter

- [ ] **Changes:** `GetSubtitlePlaylist` in `api/subtitles.py`, requiring a caller and resolving
  the item **through 005's visibility query**, which is why its refusals are the negotiation's
  shapes and not the fetch routes'. `media/hls.py` gains `subtitle_playlist` — its **own**
  rendering, not `media_playlist`'s: different header order, different entry shape, and sharing
  them would make one of the two wrong. Windows are laid from zero in `segmentLength`-second steps
  until the runtime is covered, the last one clamped; `#EXTINF` is written **with a decimal
  point, always** — the divergence [behaviours §3.12](../../docs/compatibility/behaviours.md#312-a-subtitle-playlists-window-durations-are-written-in-the-servers-locale--class-b-diverged)
  argues and AC-16 asserts, whose "Atrium does" half stops being a promise in this change — while
  a whole window is written `30` and not `30.0`, so the divergence is visible on the last window
  and nowhere else. **The route never reads the index it is given**, reproduced rather than
  improved. The route joins `INTERIM_011`.
  **Two owed rows of [spec §3.7](spec.md#37-error-paths), both settled here by
  `tools/probe_subtitle_delivery.py`:** the malformed-identifier row says both routes name
  `routeItemId`, but only the fetch route was measured and **the playlist route declares its path
  parameter as `itemId`** `[source: Jellyfin.Api/Controllers/SubtitleController.cs:338-345 @
  v10.11.11]` — the probe measures it and the spec table is corrected in this change; and **a
  source with no runtime has no row at all**, which is the controller refusal at `400`, the same
  shape and status as a zero window length `[source:
  Jellyfin.Api/Controllers/SubtitleController.cs:355-368 @ v10.11.11]` — the probe's source
  selection excluded it deliberately, so the row is added with its measurement.
- **Depends on:** T7
- **Verified by:** `python3 tools/probe_subtitle_delivery.py` — the malformed-identifier row names
  `itemId` on the playlist route or the spec was right and the plan's reading was wrong, and the
  no-runtime row answers. Then `uv run pytest tests/conformance/test_subtitle_playlist.py -q`:
  playlist shape and header order, window coverage against a known runtime, a partial last window
  written with a decimal point under `LC_ALL=es_ES.UTF-8` (AC-16 — the test sets the locale, which
  is the only way it can fail), the playlist column of §3.7's table including the three rows that
  answer `200` for a stream that does not exist, and every entry of a real playlist fetched **as
  written**, lower-case `stream.vtt` included.
- **Spec reference:** §3.5, §3.7, AC-13, AC-16; plan §6.6, §6.8

## T9 — The negotiation's subtitle half: profiles, the ladder, and three parameters in an address

- [ ] **Changes:** `DeviceProfileDto` gains `SubtitleProfiles` — the fifth list it narrows to —
  and `TranscodingProfileDto` gains `EnableSubtitlesInManifest`; 008's comment on that model
  ("v1 negotiates nothing about subtitles, and a field bound here would be a field somebody later
  assumes is honoured") is discharged in the same edit. `media/decision.py` gains `SubtitleMethod`,
  `SubtitleProfile`, `SubtitleAnswer` and `subtitle_answers`, reproducing the reference's four-step
  ladder and its `Encode` fallback `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:1442-1590 @
  v10.11.11]` — with the two details that look skippable and are not: **convertibility is not
  "text"** (`ass` and `ssa` can be converted neither from nor to), and **the transcoder gate is a
  constant**, so it is not reproduced as a branch. `api/media_info.py` reads
  `subtitle_stream_index` **inside the existing `names_this_source` gate**, which is a field rather
  than a branch, and annotates `DeliveryMethod` on every subtitle stream and `DeliveryUrl` on the
  external ones only. `media/urls.py` gains `SubtitleStreamIndex`, `EnableSubtitlesInManifest` —
  the parameter the route it addresses cannot read, written because a client parses this URL — and
  `SubtitleMethod`, at their three measured positions. **No default is proposed**: with no index
  named, `DefaultSubtitleStreamIndex` is absent, which is the reference's own answer for a user
  whose subtitle mode is `None`.
- **Depends on:** T2, T4
- **Verified by:** `uv run pytest tests/unit/test_media_decision.py tests/conformance/test_playback_info.py -q`
  — the ladder's table runs per profile class (embed, external, manifest, nothing declared) crossed
  with text/image and direct play/transcode, asserting one `SubtitleAnswer` per stream and
  `ENCODE` wherever nothing fits (AC-3, and it is most of T1's track list under a `vtt`-only
  profile); a negotiation carrying an index **and** the matching `MediaSourceId` answers that
  index as the source's stated default and writes it into the address, the same negotiation
  without the source id answers as though no index had been sent, and one carrying neither answers
  **no** `DefaultSubtitleStreamIndex` (AC-2); and the direct-play goldens are unchanged except for
  the properties AC-1 and AC-3 add (AC-15).
- **Spec reference:** §3.2, §3.3, AC-2, AC-3, AC-15; plan §6.3

## T10 — `media/names.py`: the invariant display title, and what it costs 008

- [ ] **Changes:** `media/names.py` — pure — assembling the reference's own order joined with
  ` - `: the language name (or the undefined marker), a hearing-impaired word, a default word, a
  forced word, the **codec upper-cased**, an external word; and where the stream has a title of
  its own, the title leads and each attribute is appended only if the title does not already
  contain it as a case-insensitive substring `[source:
  MediaBrowser.Model/Entities/MediaStream.cs:390-465 @ v10.11.11]`. The five words and the
  undefined marker are the reference's own literals, so everything but the language name is
  parity. The language name is `metadata/cultures.py`'s display name, first letter upper-cased,
  falling back to the raw tag — the table this project has, **not** a second one, for the reason
  004 T15 is the record of. It takes a culture index as an argument rather than importing the
  table, so the matrix is a table test. `MediaStream.DisplayTitle` **stays absent**: a JSON
  property can be, a manifest attribute cannot, and the asymmetry is recorded in
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s
  localised-properties row in this change.
- **Depends on:** T2
- **Verified by:** `uv run pytest tests/unit/test_stream_names.py -q` — the matrix over the six
  pieces and the substring suppression, including the two costs §6.4 states exactly: a `spa` track
  reads `Spanish; Castilian - Forced - SUBRIP` where an English-configured reference writes
  `Spanish - Forced - SUBRIP`, and an unlanguaged one takes the undefined marker.
- **Spec reference:** §3.2 (the `NAME` box), OQ-4; plan §6.4

## T11 — The manifest: two bound parameters, the group on every variant, and AC-8's traversal

- [ ] **Changes:** `api/delivery.video_parameters` gains `subtitleStreamIndex` and
  `subtitleMethod`, **neither with a validation pattern**, because an unrecognised value is
  ignored and not refused: `SubtitleMethod=banana` is no method, not a `400`. The five members are
  matched case-insensitively, which is what an enum-typed parameter does on the other side — and
  the lower-case spelling is the row plan §6.8 leaves owed, folded into
  `tools/probe_subtitle_manifest.py` here. **`EnableSubtitlesInManifest` is deliberately not
  bound**, which is both the parity answer and the cheapest way to hold AC-6's third case.
  `media/hls.py` gains `AnnouncedSubtitle`, `subtitle_uri` and the `#EXT-X-MEDIA` block emitted
  **before** the first `#EXT-X-STREAM-INF`, and `_variant` gains the group so that **every**
  variant line ends in `,SUBTITLES="subs"` after the frame rate — the SDR entrance beside an HDR
  copy included (see "What the gate changed"). `api/dynamic_hls.py`'s master route builds one
  `AnnouncedSubtitle` per **text** subtitle stream, in stream order whatever the selection was,
  only when `subtitleMethod` is `Hls` and the source has at least one; `DEFAULT=YES` falls out of
  comparing indices rather than being a case, which is what makes AC-7 a property instead of a
  branch. The address is the hard-coded thirty-second window and the caller's own token from
  `compat/auth.extract_token`. `probe_subtitle_manifest.py`'s `_variant_line` becomes
  `_variant_lines`, and the lever battery gains the **HDR-copy** case the gate measured by hand.
- **Depends on:** T8, T9, T10
- **Verified by:** `python3 tools/probe_subtitle_manifest.py --allow-writes` against a library
  holding an HDR film — every variant of the multi-variant master carries the group, or the
  correction this gate made to plan §6.5 is wrong — and the lower-case `subtitlemethod=hls` case
  answers. Then `uv run pytest tests/conformance/test_subtitle_manifest.py tests/conformance/test_hls_playlists.py -q`:
  a golden per address class with `NAME` masked (spec §6's own rule), where **four** of them are
  byte-identical to the master playlist the same request answers today — the manifest flag alone,
  an index with no method, the external method and the burn-in method (AC-6); an image index still
  announcing every text stream with `DEFAULT=NO` on all of them (AC-7); a delivery request
  carrying a subtitle index served with that track (AC-4); and **AC-8's traversal**, one test that
  negotiates against a manifest profile, follows the `TranscodingUrl`, follows every
  `#EXT-X-MEDIA` `URI` **as written**, and follows every entry of each playlist it answers **as
  written**, asserting a `200` and a non-empty body at every hop. A manifest and a playlist can
  both be well formed and lead nowhere, and only following them says so.
- **Spec reference:** §3.4, AC-4, AC-5, AC-6, AC-7, AC-8; plan §6.5, §6.8

## T12 — The acceptance map, the exact route set, and 011 is Implemented

- [ ] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_011` — sixteen rows, each
  naming its test; `IMPLEMENTED_FEATURES` gains `"011"` and `INTERIM_011` is deleted; `spec.md`,
  `plan.md` and this file are marked `Implemented`; `specs/README.md`'s table and narrative,
  `docs/roadmap.md` and `AGENTS.md`'s "where the project is" say so; the
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) subtitle row and
  `HasSubtitles` row are **closed** rather than corrected again, and the no-per-user-preference row
  is confirmed as the one that stays; and this file gains **what 011 owes the next ones**.
- **Depends on:** T1–T11
- **Verified by:** the full gate — `uv run ruff check . && uv run ruff format --check . &&
  uv run mypy && uv run pytest` — with `test_every_implemented_feature_has_a_map`,
  `test_the_specification_still_has_the_criteria_this_map_expects` and
  `test_no_route_ships_ahead_of_its_feature` green: the map is complete, the criteria count matches
  the spec's sixteen, and exactly the three 011 routes of
  [`surface.yaml`](../../docs/compatibility/surface.yaml) are served — counted against the file,
  not against this list's prose (007 T13's lesson, and 008 T14's).
- **Spec reference:** §5, §6

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all sixteen —
      has a passing test, by name, in `FEATURE_011`.
- [ ] Every endpoint reaches the level [spec §6](spec.md#6-conformance) declares: the three L3
      surfaces carry goldens (the stream properties per kind, the negotiation per profile class,
      the manifest per address class) and the four L2 rows carry their shape, cue,
      fixture-mutation and table-driven error assertions. **The differential half of L3 is
      [010](../010-conformance-harness/)'s**, as it is for every feature before this one.
- [ ] The three routes are served, `"011"` is in `IMPLEMENTED_FEATURES`, `INTERIM_011` is gone,
      and no route exists outside [`surface.yaml`](../../docs/compatibility/surface.yaml).
- [ ] **Nothing burns anything in.** `media/ffmpeg.py` gains no subtitle filter and no second
      filter path; `Encode` is a word this server says, per stream, exactly where the reference
      says it.
- [ ] **The two numberings never meet outside `renumber`.** `media_streams.stream_index` is a
      demuxer index, `media_external_streams` has no wire column, `-map` reads `file_index` and
      has exactly one call site, and a unit test asserts the two differ wherever externals exist.
- [ ] The **two** divergences ship as behaviours records them: [§3.12](../../docs/compatibility/behaviours.md#312-a-subtitle-playlists-window-durations-are-written-in-the-servers-locale--class-b-diverged)
      (the invariant decimal point) and §5's localised-properties row (the `NAME` attribute's
      invariant assembly, now written in one place and withheld in another). **Every other
      response is byte-identical to the measured reference**, `LANGUAGE`, `FORCED`, `DEFAULT` and
      `URI` included — and the one place that sentence is knowingly weaker is latency: an image
      track's `400` arrives here without the reference's twenty seconds of attempted extraction.
- [ ] The owed readings are paid with citations in place: AC-10 against the same-format short
      circuit (T7), the playlist route's `itemId` (T8), the no-runtime row (T8), the lower-case
      `SubtitleMethod` (T11), `ttml` and the fetch formats' media types (T7), and the `hin` branch
      reported on rather than assumed (T3).
- [ ] Anything learned during implementation is back in `spec.md`, `plan.md` or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) in the same change that learned
      it, with provenance.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

---

## What is out of scope, recorded so it is not mistaken for an oversight

* **`SubtitleCodec` is never written into a delivery address.** The reference writes it for an
  `Embed` method with a declared codec list; v1 binds no such list and embeds nothing, so it is a
  missing parameter on a branch v1 cannot reach (plan §6.8).
* **The item's own internal metadata directory** — where the reference puts a subtitle it
  downloaded or extracted — is not looked in. v1 neither downloads nor stores extracted subtitles
  beside the media, so the discovered set is a lower bound on a reference server that has used the
  feature [spec §2](spec.md#2-scope) excludes.
* **OQ-9 and OQ-10** — an honest `Content-Length` on a capped transcode, and keying a transcode on
  a client-supplied play session — are measured, are not requirements, and belong to the *"where a
  progressive re-encode is produced"* question [spec §2.1](spec.md#21-why-this-is-one-feature-and-why-the-gaps-beside-it-are-not-in-it)
  hands on. No task here turns either into work, and no criterion here depends on either.
* **Whether the video client fetches a whole-file subtitle when the manifest carries none**
  ([spec §7.2](spec.md#72-the-one-question-no-probe-here-can-answer)) is a question for the
  trace's author. The route is in either way, every criterion is written against the manifest's
  traversal, and the ordering above does not depend on the answer (plan §6.8's last bullet).
