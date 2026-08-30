---
feature: 011-subtitle-delivery
title: Subtitle delivery — tasks
status: Implemented
created: 2026-08-30
updated: 2026-08-31
accepted: 2026-08-30
implemented: 2026-08-31
amended: 2026-08-30 at the gate — 008's amendment of the same day gave the master playlist more than one variant and the subtitle group belongs on all of them; the codec spelling the text/image split reads is not the spelling this server stores; ffmpeg cannot encode the image subtitle track the fixture needs; and the sidecar language rule's "eight regional rows" are nine, two of which are not regional. See "What the gate changed"; and 2026-08-30 by T11 — the gate's own row for T11, and the ordering paragraph above it, say the only lever is `SubtitleMethod=Hls` **beside a `SubtitleStreamIndex`**. Measured, the method announces on its own: no index, `-1` and an index naming no stream each announce every text track, and the index decides only which entry is the default. The wording came from spec §3.4, which is amended with AC-5 in T11's change; plan §6.5's condition never asked for the index and needed no correction there
plan_status_required: Accepted
plan_status_actual: Implemented
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
the manifest flag at all — OQ-1 died on that — so the **only** lever is `SubtitleMethod=Hls` in
the delivery address, which is the client-side track override
[client-atrium-tvos §4.3](../../docs/compatibility/client-atrium-tvos.md#43-the-clients-track-override-works-for-audio-and-is-dropped-for-subtitles)
sized as *"a line inside §4.2"*. Binding the two parameters (AC-4) and announcing the tracks
(AC-5) are therefore one task, T11, and it is the largest here. *(This paragraph said
`SubtitleMethod=Hls` **beside a `SubtitleStreamIndex`**, following spec §3.4; T11 measured that
the method announces on its own and the index decides only which entry is the default — so the
override works for a client that sends either, which is the point of the override.)*

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

- [x] **Changes:** `library/naming/external.py` — pure — reproduces the stem match and the
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

**Done (2026-08-30).** The rule reproduced, and **the reproduction that proved it was carrying a
second mistake of exactly the class this task was written to find.** Plan §6.8 owed one unmeasured
branch, the `hin` collision. The probe now says which branches a run took, and against the
reference library it reaches four and misses **three**: `default`, `hin`, and *a language written
as a name rather than as a code* — the last of which the gate's own reproduction got **wrong**, not
merely unexercised. `Cultures.find` returned the three-letter code for every row, which is right
for 183 of the 192 and wrong for the nine the tasks gate had just corrected the plan about; it
agreed with the server on all six items anyway, because no sidecar in that library names one of
the nine. A rule and its check were both wrong in the same direction, and only counting what ran
separated them. Each of the three is one filename away from measured — `Film.default.srt`,
`Film.spa.hi.srt`, `Film.ell.srt` — and plan §6.8 now names all three instead of one.

**"First row wins" is not a tie-break, it decides a spelling.** Five culture rows carry `zho` and
two carry `spa`, and the matrix row for it was written asserting `zh-hk` — the wrong answer, caught
by the table. `Chinese` is the first of the five and its name has no dash, so `film.zho.srt` is
`zho`; three of the other four are `zh-hk`, `zh-cn` and `zh-tw`, whose names *are* what gets
written down — so a lookup built last-wins answers `zh-tw` for a filename that never mentioned
Taiwan. The same shape sits behind `spa`, whose second row is `es-419`.

**The merge is three rules and plan §6.2 was wrong about all three** `[source:
MediaBrowser.Providers/MediaInfo/MediaInfoResolver.cs:117-125, 337-345 @ v10.11.11]`, read here
because T3 owns the rule the merge consumes and corrected in the plan rather than left for T4 to
re-derive: `IsDefault` is **assigned** from the filename where the other two flags are OR-ed, so a
sidecar the demuxer calls default and the name does not is not default; the **file's** title and
language win and the name's fill a gap, which is the opposite of *"the title from the name replaces
the file's own"*; and a sidecar holding more than one stream — an `.mks`, never an `.srt` — gets
none of the three flags at all. None of it is measurable on the reference library: its fourteen
external streams carry no internal title, language or disposition, so every merge rule there has
one input and agrees with itself. T4 implements them as read, and owes the reading a fixture.

**`file_index` is mirrored, not required, and the mirror is the honest value.** Plan §5 declares it
beside `index` with no default; required, it would have written the same number twice on thirty
construction sites and left the thirty-first free to write a different one. Unstated it reads back
as `index`, which is exactly what is true before anything renumbers — a container's fourth stream
*is* the wire's fourth stream until a file turns up beside it. The sentinel never survives
construction, so `-map 0:{file_index}` needs no guard. And because `renumber` reads `file_index`
rather than `index`, renumbering an already-renumbered list answers what renumbering once did,
which is what lets T4 renumber on **every** repository read without tracking whether it already
has.

Two smaller things. The stem guard rejects `film2.srt` and `film 2.eng.srt` for `film.mkv` and the
delimiter is the whole reason — a `startswith` would hand one film's subtitle to another, and the
row is in the matrix rather than in a comment. And `Title` has three values, not two: `None` for a
bare stem, `None` for a name whose every token was claimed, and the **empty string** for
`film..srt`, whose one token is empty and which nothing claims. Faithful rather than desirable; the
distinction is the reference's own and the matrix carries the row so nobody tidies it away.

## T4 — The sidecars land in rows, and a default scan notices them

- [x] **Changes:** migration `0007_external_subtitle_streams` gains `media_external_streams` as
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

**Done (2026-08-30).** The second change signal was the part this task was written around and it
worked first time. **What did not was a third reader nobody had counted, and the test that caught
it is a test about money rather than about subtitles.** A listing page hydrates its inspections in
statements that do not grow with the page, and `inspection_of` is the one conversion both readers
share — so renumbering inside it means `item_queries.py` must fetch the discovered rows too, or a
page answers a stream list that is short *and* misnumbered, with `HasSubtitles` false on exactly
the item AC-11 is about. Nothing in this task's statement mentions `item_queries.py`. What found it
was `test_the_statement_count_is_what_the_plan_says_it_is` failing 17 against 18: a guard written
for a different reason, spending its budget on the right thing. The count is now declared in both
places that hold it.

**`_walk_every_root` silently dropped the third output, and every assertion still passed.** The
merge across roots rebuilds `WalkResult` field by field, so a new field is absent by default rather
than by decision — the sidecar was found by the walk, discarded on the way out, and the scan
discovered nothing with no error anywhere. Four tests failed with an empty set and one line fixed
all four. **A dataclass that is reconstructed rather than copied has no protection against a field
being added to it**, which is worth knowing before the next output lands there.

**The merge is three rules and `put_external` takes files, not streams.** T3's reading is
implemented as read: `is_default` assigned from the filename, `is_forced` and `is_hearing_impaired`
OR-ed, the file's own title and language winning over the name's, and a multi-stream sidecar
getting no filename flags at all. Plan §5's contract says `put_external(..., streams)` and it is
`files` here — an `.mks` holds several tracks behind **one** `(size, mtime_ns)`, and a per-stream
argument carries that pair once per track with nothing keeping the copies equal. `DiscoveredSubtitles`
is the record; the table still denormalises the pair per row, because that is where the ordinal
lives.

**`put` was storing the wire index, and it had been right until this task.** `media_streams.stream_index`
is a demuxer index by declaration, and `put` wrote `one.index` — equal to it on a fresh inspection,
and *not* equal on an inspection that had been read back through `renumber`. Nothing round-trips one
today, so this is a hazard closed rather than a bug fixed; it is one line and the alternative was
leaving a loaded gun in the one place the two numberings are supposed to never meet.

Two smaller things. A subtitle file **settles** like a candidate — a half-copied `.srt` inspected
mid-write would store a cue list nobody wrote — but silently, with no second `Skipped` entry,
because it already has one for its extension and the operator's count must not move; there is a
test for the count in both directions. And the claim is scoped **per directory**, which is the
reference's own scope: a stem match across directories would let one film claim another's file for
having a longer name, and the test plants exactly that file one directory up.

## T5 — `media/subtitles.py`: the cue list, and the labels beside it

- [x] **Changes:** `media/subtitles.py` — pure — with `Cue`, `parse` over the three readable
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
  output re-parsed back to the same cues (AC-9, AC-10, AC-14). Plus
  `python3 tools/probe_subtitle_delivery.py` — its **sixth battery**, added here at the user's
  gate decision, which measures the boundary repeat the coverage row above found rather than
  leaving AC-10 amended on a reading.
- **Spec reference:** §3.5, AC-9, AC-10, AC-14; plan §5, §6.7

**Done (2026-08-30).** The task statement asked for a cue list and the cue list was the easy half.
**What the documents had wrong is what a document made of cues also carries — and one of the
sixteen criteria is false because of where a cue is allowed to sit.**

**AC-10 has a second contradiction and this one is on every window of every track.** Plan §6.8
already owed one — the same-format short circuit, which needs a hand-made request. This one needs
nothing: the skip keeps a cue whose start *equals* the window's start, the take keeps a cue whose
start *equals* the window's end, and [the playlist](plan.md#66-the-playlist-route) hands
consecutive windows the **same** boundary tick — one window's `EndPositionTicks` is the next
one's `StartPositionTicks` `[source:
MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:100-112,
Jellyfin.Api/Controllers/SubtitleController.cs:394-405 @ v10.11.11]`. So a cue starting on a
multiple of the window length is **delivered twice**, with the file's own timings both times
because the playlist sets the copy switch, and *"the concatenation of every window of a track is
the whole track"* is false by exactly those repeats. Found by the coverage row this task's
verification asks for, on a cue list whose third cue happened to sit at 60.0 s in a 30 s grid; it
would have passed on any other number.

**And then it was measured, because a reading is not a measurement and the spec is accepted.**
The first draft of this note amended AC-10 on a `[source:]` reading alone, which is precisely what
[AGENTS.md](../../AGENTS.md)'s *"measure the reference before implementing anything"* and plan
§6.8's *"the amendment is the user's to take"* exist to stop. `tools/probe_subtitle_delivery.py`
gained a **sixth battery** for it, and the run says the repeat is real, in both forms it can take
`[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`:

* **constructed** — a boundary built out of a cue's own start at 37.802 s: the window ending there
  answers 2 cues with the last at 37.802, the window starting there answers 8 with the first at
  37.802. The same cue **one millisecond off** the boundary is in the earlier window and not in
  the later one, which is what says this is the exact hit and not a rounding — a straddling cue is
  dropped by the next window's skip for ending before its start;
* **through the reference's own playlist** — a cue at 3 282 s, a `SegmentLength=6` grid that lands
  on it, 2 of the 902 generated entries sharing that position, and the cue present in **both**
  when they are followed as written, `ApiKey` and both switches included.

The battery reports which of the two forms it reached, the way `probe_sidecar_subtitles.py` and
`probe_transcode_decision.py` now do: the constructed form is reachable on any track with a cue
after zero, the playlist form needs a library whose cues land on a whole multiple of some segment
length, and a run that misses the second says so instead of inferring it. This one reached both.
AC-10 carries the clause with a `[probe:]` citation, and the repeat is reproduced, because
narrowing either end drops a cue the reference sends.

**A document is not only its cues, and neither document said so.** [Spec
§6](spec.md#6-conformance) makes converted text a cue-by-cue assertion on the argument that two
converters disagree only on whitespace and rounding. They do not. The reference's `vtt` writer
emits a **`Region:` declaration** in the header and ends **every** cue's timing line with
`region:subtitle line:90%` `[source: MediaBrowser.MediaEncoding/Subtitles/VttWriter.cs:23-40 @
v10.11.11]` — measured on the wire in the same run, header and cue line both, the first cue of a
real track arriving as `00:00:35.099 --> 00:00:37.185 region:subtitle line:90%` — and
`stream.vtt` is what [every playlist entry names](spec.md#35-fetching-a-subtitle), so that writer
is the entire subtitle path for the video client. A `WEBVTT\n\n` header with bare timing lines holds the same cues, parses identically,
passes a cue-by-cue check, and puts the text somewhere else on the screen. Two smaller ones from
the same read: the `vtt` writer is the only one that **edits a timing**, pushing a cue whose end
does not follow its start out by a millisecond, and the `srt` writer **renumbers from one**, so
*"every writer's output re-parsed back to the same cues"* is false of the identifier on the one
writer that had one to keep. Spec §3.5, spec §6 and plan §6.7 step 4 all carry it now, and the
framing is asserted as bytes.

**Plan §6.7's byte-order-mark list is four formats and it is five.** `ttml` writes through the
same text writer as `srt`, `vtt`, `ass` and `ssa` and emits the same preamble `[source:
MediaBrowser.MediaEncoding/Subtitles/TtmlWriter.cs:23 @ v10.11.11]`; only `json` writes bytes
directly. And step 5's *"replace the leading `WEBVTT`"* is a replacement over the **whole**
document, so a cue whose text contains the word gets a mapping line of its own — and the switch is
read against the spelling `vtt` and never against `webvtt` beside it, which shares the writer and
not the branch.

**Two spellings of the writable set can be written and cannot be fetched.** `subrip` and `webvtt`
reach a writer, and the label lookup a fetch resolves its `Content-Type` through has a row for
neither `[source: Jellyfin.Api/Controllers/SubtitleController.cs:261,274,
MediaBrowser.Model/Net/MimeTypes.cs:158-181 @ v10.11.11]` — so the reference renders the whole
document and then has nothing to send it under. `media/labels.py` gets **no row for either**,
because a row would answer a body where the reference answers none; the six that do have rows are
there, `ttml` among them, which plan §6.8's own list of media types had left out. What the
reference ends on for those two is T7's to measure: its format battery asked for six spellings and
never asked for these. **Five of the six rows are measured now** — `text/vtt`,
`application/x-subrip`, `text/x-ssa` on both SubStation spellings and `application/json` on both
of `json` and `js`, read off the same run — and `ttml` is the one still read, for the same reason:
nothing has asked for it.

**One thing the run paid that nobody asked it to.** `Stream.srt` on a `subrip` track answers
84 858 bytes with **no byte order mark**, `\r\n` inside a cue's text and the file's own numbering,
where every converted format on that same track carries the mark — which is the readable file's
own bytes handed back rather than a rendered document, and is the unwindowed half of [plan
§6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)'s **first** owed bullet
arriving for free. The windowed half — the same request with a `StartPositionTicks` on it, which
is what turns that bullet from a reading into a measurement — is not asked by this battery and
stays owed to T7.

Two smaller things. **The reference's parser table is keyed on a file *extension***, so `subrip`
and `webvtt` cannot arrive at `parse` there at all — `READABLE` naming them is a liberality
nothing can reach rather than a claim, and the plan says so now. And `Cue.identifier` is a
**number in string form on every path**, because it is built from a paragraph's number: `srt`
keeps its file's own (a document numbered from 311 answers `"311"`), `ass`, `ssa` and `vtt` are
numbered by position, and a WebVTT cue's free-text name has nowhere to go.

## T6 — `media/extract.py`: one process, one cache entry, one lock

- [x] **Changes:** `media/extract.py` — the one impure module — with `readable(...)`: an external
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

**Done (2026-08-30).** The four branches were the four the plan named and the module is the size it
said. **What was wrong is what the artefact those branches produce actually contains — and a
client can see it.**

**The extracted file is not what ffmpeg wrote.** After extracting a track to `.ass` the reference
replaces `,Arial,` with `,Arial Unicode MS,` in the finished file and rewrites it **only where that
changed something** `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:751, 928-957
@ v10.11.11]` — and the rewrite goes back out through a writer that emits the UTF-8 preamble where
ffmpeg's muxer emits none, so the substituted font and the **byte order mark** arrive together or
not at all — and the two callers of that substitution do not test the same thing, which is the
reference's own asymmetry and not a simplification: after an extraction it looks at the output's
name and passes `.ssa` over, and after a conversion it acts on the output whatever it is called
`[source: SubtitleEncoder.cs:452 @ v10.11.11]`. Read first, then measured, because a reading is not
a measurement and this one is
reachable from outside: the same-format short circuit hands the artefact straight back, so
`Stream.ass` on an *embedded* `ass` track is the only view a client has of what an extraction
wrote. `tools/probe_subtitle_delivery.py` gained a **seventh battery** for it and the run reached
**both** forms `[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`: a track
whose style named Arial answers `Style: Default,Arial Unicode MS,30,…` under a leading mark, and a
track whose style named `sans-serif` answers ffmpeg's own bytes with no mark. The battery asserts
the biconditional rather than a byte string, and says which forms a run reached, because whether a
library holds an Arial-styled track is a fact about the library.

**And the sentence that produced it was read as saying something it does not say.** *"Extracted by
one ffmpeg invocation to `srt` (or to its own spelling where the codec is `ass` or `ssa`)"* — this
task's own Changes bullet and [plan §6.7](plan.md#67-the-fetch-routes-readable-converted-windowed)
alike — names the **format of the artefact**. What `-c:s` is given is a *different rule* with a
different list: the reference copies the bitstream of anything copyable — `ass`, `ssa`, `srt`,
`subrip` — and encodes to SubRip only what it cannot `[source: SubtitleEncoder.cs:485-493, 629 @
v10.11.11]`. So an embedded `subrip` track is `-c:s copy` into an `.srt`; written as read, it would
have been `-c:s srt`, which decodes and re-encodes every cue of every track in a library for
nothing, and would have passed a cue comparison while changing the bytes of every `Stream.srt`
the short circuit answers. `tests/unit/test_subtitle_extract.py` asserts the argument, not only the
answer.

**Three smaller ones, all from the same read.** The reference extracts **every** extractable track
of a source in *one* invocation with a `-map`/output pair each `[source: SubtitleEncoder.cs:495-556,
608-654 @ v10.11.11]` where this module extracts the one it was asked for — the artefacts are
identical and the difference is what a first fetch pays for. A **non-zero exit is not by itself a
failure** there: a run fails only where its output is missing or empty `[source:
SubtitleEncoder.cs:704-763 @ v10.11.11]`, so the artefact is the test and the encoder's complaints
are logged. And the reference's parser table is built by **reflection over a subtitle library's
whole format set** `[source: MediaBrowser.MediaEncoding/Subtitles/SubtitleEditParser.cs:96-134 @
v10.11.11]`, so it parses some dozens of extensions natively where [plan §5](plan.md#5-contracts)'s
`READABLE` is three families: the ffmpeg fallback both servers have catches more files here than
there, on the same cues.

**And one line of the cache key addressed the wrong file.** [Plan
§6.7](plan.md#67-the-fetch-routes-readable-converted-windowed) keys the artefact on *the media
file's* `(size, mtime_ns)`, which is right for a track inside the container and wrong for the two
branches that read a file beside it: an `.mks` and a sidecar the ffmpeg fallback normalises are
extracted from the **sidecar's** bytes, and a sidecar can be replaced without the film being
touched at all — after which every fetch would answer the previous subtitle for as long as the
artefact survived. The key is the extracted file's own signal, which is the same argument
`images/cache.py`'s tag paragraph makes and which §6.7 now states; the `stat` that reads it is one
of the two places plan §7's *"a sidecar the scan recorded is gone at fetch time"* is noticed, the
other being the read itself on the branch that opens the sidecar directly.

**One thing is a decision rather than a finding, and it is recorded as owed.** *"Its encoding
detected rather than assumed"* is a statistical detector on the reference and three steps here — a
byte order mark, then strict UTF-8, then one declared single-byte fallback. Every file that is
UTF-8 or carries a mark is read identically on both, which is every file any fixture here holds; a
legacy file outside the fallback's range decodes differently, or not at all. The alternative is a
new runtime dependency, which is not an implementation detail, so it was put to the user rather
than taken here — and **the answer was the rule, no dependency, and the limit written down** as
[behaviours §5.11](../../docs/compatibility/behaviours.md#511-a-subtitle-file-in-a-legacy-encoding-is-decoded-by-a-rule-and-not-by-a-detector),
closed on the day a real library needs a detector by putting one behind the same function with its
dependency argued in an ADR. **§5 and not §3**, and that is the load-bearing half of the answer: a
§3 divergence has to carry the argument that no client can observe the difference, and what differs
here is the **cue text a player draws** — filing it as a safe divergence would have been claiming
something untrue. [Plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)'s row
now says decided rather than owed.

**And then CI failed where the local gate was green, on three tests, for a reason no reading would
have produced: an extracted cue's time is a function of the ffmpeg that extracted it.** Every cue
of the embedded track came back **21 ms late** on CI's ffmpeg 6.1.1 and on time on this machine's
9.0.1. Confirmed with `ffprobe` rather than assumed, and the cause is not the subtitles at all:
ffmpeg expresses an output on a timeline beginning at the **container's** start time, that start
time is the earliest of *all* the streams', and one AAC frame of encoder priming — 1024 samples at
the 48 kHz these entries declare, 21.33 ms — lands in Matroska as a first audio timestamp of
**-21 ms**. So the container starts before zero and every cue of the subtitle track **beside** the
audio is pushed forward by exactly that. It is [T1's own hazard](#t1--the-world-gets-subtitles-two-entries-one-sidecar-and-a-bitstream-ffmpeg-will-not-encode)
one feature on, from the other direction: there a bitstream that did not start at zero moved and
took the track beside it, here an *audio* track that does not start at zero moves the subtitles.

**It is a reading and not a writing, which is what decided the fix.** ffmpeg 6.1 reports the
negative start time and ffmpeg 9.0 reports zero **for the same bytes** — each build reads both
builds' files the same way as itself — and the same mux with `flac` audio, or with no audio at
all, starts at zero on both. So no fixture change would have been a fix; it would have been a
fixture chosen to stop a test failing.

**Reproduced rather than corrected, and the alternative was measured before that was decided.**
The reference's extraction passes no `-copyts` `[source:
MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:629-646 @ v10.11.11]`, so a reference
server on the same build answers the same 21 ms: this is **parity**, not a shortfall. And
`-copyts` — the one flag that fixes it — was tried on ffmpeg 6.1 and **breaks a worse case**: on a
container whose start time is *positive*, which is what a `.ts` recording with a PCR offset has,
it answers a cue an hour in at `01:00:00` where the reference answers `00:00:00`, so every window
a client follows comes back empty. Trading 21 ms on one file class for an hour on another is not a
correctness fix. The rule that would be right for both signs — subtract the start time, never let
a negative one push a cue forward — is no ffmpeg flag and needs a container start time nothing
here stores.

**So the assertion moved, and it moved to a derivation rather than to a tolerance.**
`tests/fixtures/media.py` gains `extraction_offset_seconds`, which reads the offset off the
container with `ffprobe`, and **one** test asserts cue timings: the declared list plus that offset,
exact on every build, still failing on a dropped cue, a mangled timing or the wrong stream mapped.
The two tests that asserted timings *in passing* now assert the cue **text**, which is what each
was actually for — the text is what says which of the two subtitle tracks was mapped. A test
loosened until it passes would have been the thing this repository calls not-a-test; this one
asserts more than it did, because the offset is now named and read rather than assumed to be zero.

**Two things checked while the two builds were both in hand, because nobody had had that
comparison before.** The fixture's byte-for-byte invariant **holds within a build and not across
them** — 59 237 bytes on 6.1 against 59 240 on 9.0 for one entry — which is exactly what
`digest_of` mixing the `ffmpeg -version` line into the cache directory name is for, so the digest
is doing what it claims and not less. And the **whole suite was run against ffmpeg 6.1.1-3ubuntu5**
in Ubuntu 24.04, CI's own build: the three cue assertions above were the only version-dependent
ones in it.

**One thing this leaves for a later gate.** AC-9's *"timings that match the source's"* is exact
only where the container starts at zero; where it does not, an extracted cue carries that offset —
here **and** on a reference running the same binary, so the criterion holds as the parity
statement it is written for and is short of absolute.
[Plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)
records it for T7, which owns AC-9's test, or for T12's acceptance map.

**And the sweep the task points at could not hold two names.**
`test_import_directions.py`'s `SUPERVISED_THROUGH_THE_LEDGER` was a single string with one test
reading it, and its second half looked for the literal `_ledger.start(` — the private attribute
008's manager happens to use. Naming a second module meant making it a tuple, parametrising, and
asserting `ledger.start(` so a module that is *handed* a ledger satisfies it too. Both halves stay:
reaching for no spawner of its own, **and** reaching the ledger's — the first alone would pass for
a module that had quietly stopped starting processes.

## T7 — The two fetch routes, the format battery, and the short circuit that contradicts AC-10

- [x] **Changes:** `api/subtitles.py` with `GetSubtitle` and `GetSubtitleWithTicks` sharing one
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

**Done (2026-08-30).** The two routes are the size the task said and every owed row of the battery
answered. **What both documents had wrong is what the reference does when it has nothing to call
an answer — and what the route has to know before it can refuse at all.**

**`subrip` and `webvtt` do not fail on the label. They answer a body.** [Plan
§6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed), T5's Done note and
`media/labels.py`'s own docstring all said the same thing in the same words: the two spellings
reach a writer, the label lookup has a row for neither, so *"the reference renders the whole
document and then has nothing to send it under"*. It has something: a lookup with no row and no
default hands back nothing, and the framework's file result **defaults the content type**.
Measured, both spellings: `200`, the whole rendered document, `application/octet-stream`
`[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. `media/labels.py`
still has no row for either and the answer is still right, for the opposite reason to the one it
was written for — the fetch route falls through to `DEFAULT_MEDIA_TYPE`, which *is* that string,
so adding a row would be choosing a label where the reference chooses none. And the pair is a
second view of the short circuit below: `Stream.subrip` **renders** where `Stream.srt` hands the
file back, so one format answers two different bodies under two spellings.

**AC-10's first contradiction is a measurement now, and the criterion states it.** The battery
asks `Stream.srt?StartPositionTicks=…&EndPositionTicks=…` on a SubRip track and gets the **whole
track** — 84 858 bytes, identical to the unwindowed request, on the ticks-in-path route too, with
and without the copy switch. [Plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)
says in as many words that amending an accepted criterion is the user's to take, so this task
measured it, reproduced it, wrote the test, wrote the clause out in
[spec §3.5](spec.md#35-fetching-a-subtitle) — **and put it to the user rather than taking it. The
answer was to take it here.** AC-10 carries *"…and no others, except where the requested format is
the one the track is already in, which answers the whole track, unwindowed and unrebased"*, under
the `[probe:]` citation it was measured with rather than the `[source:]` it was found with.

**AC-9 went the same way, and it is a narrowing rather than a widening.** §6.8 offered it to T7 or
to T12: *"timings that match the source's"* is exact only where the container begins at zero, and
where it does not an extracted cue carries the container's own start time — 21 ms on ffmpeg 6.1
and nothing on 9.0 for the same bytes (T6). The criterion now says so, and says it as the
**parity** it is: a reference server on the same build answers the same offset, because its own
extraction passes no `-copyts` either, so this is precision about what was always true rather than
a divergence being admitted. The test reads that offset with `tests/fixtures/media.py`'s
`extraction_offset_seconds` rather than asserting a literal, which is what makes it exact on both
builds and still failing on a dropped cue, a mangled timing or the wrong stream mapped.

**The deferral both of them were offered was declined, and the reason is a rule rather than a
preference.** [AGENTS.md](../../AGENTS.md) has documentation moving with the code *in the same
commit* — *"a behaviour change whose spec is updated in a follow-up is an incomplete change, not a
fast one"* — and this is the shape T5's boundary repeat already took: measured, then amended
inside its own change. Parking either would have left a knowingly false criterion standing across
T8, T9, T10 and T11, which are four tasks written by people reading it.

**One thing the amendments deliberately do not do.** Neither criterion names a module, a function
or a test file: [AGENTS.md](../../AGENTS.md)'s *"no technology names in `spec.md`"* outranks the
convenience of pointing at the helper, so AC-9 says the offset is *read off the container being
extracted* and `extraction_offset_seconds` is named in [plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)
and here, where it belongs.

**The address is not the last word, and the plan had one of its parameters backwards.** Four
deprecated query parameters — `itemId`, `mediaSourceId`, `index`, `format` — are bound on the
reference and **override the route values beside them**: `Stream.vtt?format=srt` answers SubRip
under `application/x-subrip`, and `?index=` naming no stream answers that index's `500`. Neither
document mentioned them. And [plan §6.7](plan.md#67-the-fetch-routes-readable-converted-windowed)
said the ticks-in-path route takes *"the path's start position … in place of the query's"*; it is
the other way round — `…/6000000000/Stream.vtt?StartPositionTicks=0` answers the track from its
first cue. Written as read, a client that sent both would have been served the wrong window. Same
probe.

**A row §3.7 did not have, and the route could not be written without it.** The table says an item
identifier naming nothing is `400` and a `mediaSourceId` naming nothing is `500` — which is the
reverse of the pair 008 measured on its delivery routes — and it does not say which side an item
that **exists and holds nothing servable** falls on. It is the `500`: a series identifier and an
audio track both answer it, measured. That is not a detail: `api/delivery.py`'s `locate` resolves
the source *before* the item, so reusing it answered `500` to an identifier nothing holds and
failed the first row of the table. The route does its own lookup, item first, through a new
`MediaFileRepository.present` — and the probe carries the row so the split is reproducible rather
than remembered.

**The short circuit hands back the artefact, so `readable` needed a bytes-level twin.** T6
measured that an extracted `.ass` carries the font substitution *and* the byte order mark the
rewrite put on it, and that the only view of it from outside is this short circuit. `readable`
answers **text**: decoding consumes the mark, and re-encoding the text would have shipped that
artefact without it — a divergence on the one request the artefact is visible through, and one the
fixture reaches, because ffmpeg's `ass` encoder names Arial. `media/extract.py` now answers bytes
at that boundary (`verbatim`) and text at the other (`readable`), which is the reference's own
split: it re-encodes a file beside the media and opens an artefact raw `[source:
MediaBrowser.MediaEncoding/Subtitles/SubtitleEncoder.cs:169-193 @ v10.11.11]`.

**Three smaller ones.** `ttml` answers `200`, `application/ttml+xml`, with the mark — so the
writable set was right to include it and all six media-type rows are measured rather than read.
The `srt` renumbering is measured too, through the spelling that renders: a window starting ten
minutes in comes back numbered from `1` where the same window's cue-list answer calls that cue
`131`. And the **millisecond end-bump could not be measured**: the battery reads twelve text
tracks from files beside the media, 5 983 cues, and not one states an end that does not follow its
start — so the run reports the miss and the reading stands, which is the honest half of a
[house rule](../../AGENTS.md) rather than a shortfall.

**And one thing that cost a test run rather than a document.** The image track's codec on the wire
is `PGSSUB` and not `hdmv_pgs_subtitle`: T2 normalises four subtitle spellings at inspection, so a
test naming the ffprobe spelling finds no stream at all. The fixture declares one and the wire
answers the other, which is exactly what T2's own amendment is about.

## T8 — The playlist route, the invariant decimal point, and a refusal that names the wrong parameter

- [x] **Changes:** `GetSubtitlePlaylist` in `api/subtitles.py`, requiring a caller and resolving
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

**Done (2026-08-30).** The playlist is the size the task said and the invariant decimal point cost
nothing. **What both documents had wrong is the lookup in front of it: they describe the visibility
query and the route has two more questions before it, and each one is a different refusal.**

**"Resolve the item through 005's visibility query" is half of it, and the other half is a `404`
nothing had written down.** The reference asks for a **video**, not for an item `[source:
Jellyfin.Api/Controllers/SubtitleController.cs:350-354 @ v10.11.11]`, so an item that exists, is
visible and is not one — a series, an audio track — is the same problem-details `404` as an
identifier nothing holds. [Spec §3.7](spec.md#37-error-paths) had a **dash** in that cell, and an
implementation cannot leave one there: something has to be answered. The cell says it now. Measured beside the fetch
route's `500` for the *same* series identifier in one run
`[probe: tools/probe_subtitle_delivery.py, Jellyfin 10.11.11, 2026-08-30]`. Written without it, an
audio item would have answered `500` here — the fetch routes' answer, on the route that shares
none of theirs.

**And the all-zero identifier is refused *before* the lookup, which is why it is not the `404`.**
The table says a well-formed identifier naming nothing is `404` on this route and the all-zero form
is `400`, and nothing said why: the reference's retrieval throws on an empty identifier ahead of any
lookup at all `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1357-1361 @
v10.11.11]`. The fetch routes cannot show that difference — both of *their* answers are that
`400` — so T7's `present()` collapsed the two correctly and the same shape here answered `404` to
a row measured at `400`. **The table caught it**: the row was written before the guard was, and it
failed on the first run.

**The malformed-identifier row is measured, and the plan's reading was right.** The same value
answers `400` on both routes and the problem details name **`itemId`** on the playlist where they
name `routeItemId` on the fetch, read out of the two bodies in one run rather than off either
declaration. Same probe.

**Which is where this task's own statement and [plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)
disagreed, and the disagreement was about whose decision it is.** This statement says *"the spec
table is corrected in this change"*; §6.8 calls the two owed rows *"corrections to the accepted
spec"*, and the standing rule in this feature — T5's amendment, T6's dependency question, T7's two
— is that an accepted document is amended by the user and not by the task that finds the reason to.
**So the measurements were taken, the rows were put to the user, and the answer was to apply them
here** — the third time this feature has asked and the third time with the same answer, for the
reason [AGENTS.md](../../AGENTS.md) gives: documentation moves with the code in the same commit,
and T9 through T12 are written by people reading this table. All three cells are in §3.7 now, two
as measurements and the no-runtime row marked ⚠️ read rather than measured.

**The no-runtime row could not be measured, and the reason is sharper than the plan's.** §6.8 said
*"the probe's own source selection excludes it deliberately"*, which reads as a limitation of the
probe. It is not: **the library has no such source to select.** The battery now searches every media
source of every video item and all 2 480 state a runtime — and the route asks for a video *before*
it reads one, so a source of any other type never reaches that check at all. A runtime is written by
the scan that creates the item, so the state cannot be built from outside a server; 012's own probe
had to construct a library to reach the neighbouring condition. The row stays a `[source:]` reading,
the run reports the miss every time, and Atrium answers the reading's `400`. §3.7 carries it with
that mark on the row itself, and the reason beside it, because a reader meets the table before
they meet a plan.

**AC-16's verification asked for a test that cannot exist, and writing it literally would have
broken a principle.** *"A partial last window written with a decimal point under `LC_ALL=es_ES.UTF-8` — the
test sets the locale, which is the only way it can fail"*: a duration rendered from an exact tick
count is not locale-sensitive in this language at all, so the locale cannot make it fail — and a
test that *required* `es_ES.UTF-8` would depend on the host having it, which Principle VII forbids
and which the CI image, generating no locales, would fail on. The test sets the first comma-decimal
locale the host can set (this machine sets `es_ES.UTF-8`; the runner sets none) and asserts
unconditionally either way. It
is a guard against the format ever becoming locale-sensitive rather than a reproduction of the
defect, which is what behaviours §3.12 argues in the first place.

**Two smaller ones.** The fixture's runtime is 4.021 s and not 4.0, so whether a window is
fractional is a fact about the extraction build — the conformance test therefore compares the whole
document against the runtime the wire states, and the *guaranteed* fractional case is pinned in a
unit test on the reference's own measured 5 407.851 s, whose last window reads `7,851` there and
`7.851` here. And `#EXT-X-TARGETDURATION` is the **requested** window length rather than the longest
entry, which is the opposite of `media_playlist` two functions away and the clearest single reason
the two renderers are not one.

## T9 — The negotiation's subtitle half: profiles, the ladder, and three parameters in an address

- [x] **Changes:** `DeviceProfileDto` gains `SubtitleProfiles` — the fifth list it narrows to —
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

**Done (2026-08-30).** The four-step ladder is the four steps the plan named and reproduced
first time. **What both documents had wrong is the direction the subtitle half runs in: they
describe it as something read off the ladder's answer, and it is also an input to it — so the one
criterion that says this feature changes nothing about a direct play is false of exactly the
request the feature exists to serve.**

**Naming a subtitle track can cost a source its direct play.** The reference resolves the
*selected* stream's delivery method a second time, at `PlayMethod.DirectPlay` against the source's
own stored container, and adds `SubtitleCodecNotSupported` to every direct-play entry's failures
when the answer is not `External`, `Embed` or `Drop` `[source:
MediaBrowser.Model/Dlna/StreamBuilder.cs:1297-1309 @ v10.11.11]`. Read first and then measured,
on both sides of the discrimination in one run: the same file and the same profile answer
`SupportsDirectPlay: true` for the `subrip` track and `false` for the image track beside it, a
profile that declares nothing loses it for either, an index naming **no** stream costs nothing at
all, and the address the loss produces carries `TranscodeReasons=SubtitleCodecNotSupported` and
nothing else `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`.
Implemented as the plan described it — `subtitle_answers` applied to a finished `Decision` — a
client that turns subtitles on for a track it cannot take would have been handed the file to read
byte for byte, with no subtitle and no transcode, which is the failure this whole feature is
about. **AC-15 is narrowed and AC-2 with it**, in this change and at the user's decision, for the
reason T5, T7 and T8 each took the same answer: documentation moves with the code in the same
commit, and T10 through T12 are written by people reading those criteria.

There is no circularity in asking twice, and that is what makes it implementable: the refusal reads
the method *at direct play*, where an `Hls` entry is skipped outright, and the answer the client is
finally given reads it again against the rung that was reached. So a manifest-only profile loses
its direct play **and then** answers `Hls` on the transcode it was pushed onto — one test, both
halves.

**AC-2's *"and a delivery address naming it"* was false in two directions, and a third put it
back.** The index and the method are both dropped from the address where the resolved method is
`External` — the client was already handed that track's own address — and the index is dropped
where it is `-1`. Then a body carrying `AlwaysBurnInSubtitleWhenTranscoding: true` writes the index
back beside an external method and leaves the method out, and appends
`&alwaysBurnInSubtitleWhenTranscoding=true` after `TranscodeReasons`, in a lower camel case nothing
else in that address uses. That field has been bound on the request body since 008 and read by
nothing — the exact shape `DeviceProfileDto`'s own comment warned about — and T9 is the task that
makes it readable, so it is read here rather than left as a delta on a parameter this task adds.
All four measured in one run. Same probe.

**And the subtitle address's start position is not always zero.** [Plan §6.3](plan.md#63-the-negotiations-subtitle-half-extends-008-62-and-63)
said it is `0` for every request this feature can produce. It is `0` for every **HLS** answer,
which forces it so because a playlist preserves timings, and it is the negotiation's own
`StartTimeTicks` on a progressive transcode — `…/Subtitles/9/6000000000/Stream.vtt` for a body
that asked to start ten minutes in. The reference's own ordering comment says as much: it writes
the subtitle addresses *after* the start position is set, on purpose. Same probe, one new battery.

**The owed row needed four classes where the plan expected two**, and it is the same shape 012's
gate found for a query value arriving on a request **body**: `hls` and `HLS` bind exactly as `Hls`
does, the member's **ordinal** binds to the same member, an entry with no `Method` key at all takes
`Encode` — the one member no pass of the ladder can ever return, so it is indistinguishable from
declaring nothing — and a word that is no member is a `400`. A pydantic enum is case-sensitive, so
the field carries a before-validator and the refusal stays the framework's. What is settled is the
side T9 owns, the value a *profile* declares; `SubtitleMethod=hls` as a query parameter of the
master playlist is still T11's, now with a strong prior rather than nothing.

**And the same run measured a delta this task did not take, because what is lenient is the
*binder* and not one enum.** A direct-play entry typed `"Type": "video"` rather than `"Video"`
binds and direct-plays on the reference — one row, asked precisely because the answer above is a
fact about how a body is read. `ProfileType`, `ConditionType`, `ConditionProperty` and `CodecKind`
are all matched **case-sensitively** here, so each of the four is a `400` on Atrium where the
reference answers `200`. Making that general is a change to `compat/model.py`, which every request
model in the project inherits, so T9 fixed only the vocabulary T9 added.

**Measured here, owned there, and it widened an answer that had already been accepted.** [012's
OQ-4](../012-negotiation-inputs/spec.md#7-open-questions-and-what-measuring-them-did) answers this
question for the **protocol** value alone — `Hls`, `HLS` and `hLs` all bind, and this server's
comparison does not — and 012 is accepted and unimplemented, so an implementer reading it would
have written the narrow fix and rediscovered the general case, which is this repository paying
twice for one measurement. At the user's decision OQ-4 is **widened rather than corrected**, in
this change, with an `amended:` line on 012's own frontmatter saying that the amendment came from
another feature's task. [Plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)
**points at** that row instead of restating it, so there is one description of this and not two.

Three smaller ones. **`Drop` is a member no answer can carry** — the two embedded passes return an
`Embed` profile and the two external passes an `External` or an `Hls` one, so a declared `Drop`
entry is a track the ladder falls past; it is in the vocabulary because a client sends it, not
because anything produces it. **The output container the `Embed` passes read is not one value**:
the transcoding target's on a produced answer and the source's own narrowed against the client's
direct-play entries on a direct play, which is a *different* rule from `media/info.py`'s
`source_container` (that one is a listing's answer and lets the file's extension win). And
`profile_of` mapped the subtitle list and **not** `EnableSubtitlesInManifest`, so the flag bound
cleanly on the model and reached no address at all — caught by the one test that asserts the
parameter's position rather than its presence, which is why that test compares neighbours and not a
substring.

**And one thing found while implementing the burn-in flag and deliberately not done.** Two sibling
suffixes come off the same three lines of the reference — `&allowVideoStreamCopy=false` and
`&allowAudioStreamCopy=false`, appended whenever the body denied that copy — and Atrium honours
both switches in the decision while repeating neither in the address. They are about audio and
video copying, they belong to 008, and they are recorded in
[plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed) rather than swept in
under this task's name.

**One test-side finding, on a helper this task only borrowed.** `tests/conformance/test_playback_info.py`'s
`_container` answered `mp4` for any demuxer list with a comma in it, which is right for the six-name
mp4 family and wrong for `matroska,webm` — the second family with a comma, and the one both of 011's
subtitled entries use. Inspection *renames* that family down to `mkv` where it leaves the mp4 one
six long, so a profile built by that helper refused the container and every subtitle answer would
have been attributable to a container rejection rather than to the rule under test. It refused
loudly rather than silently, because the first assertion each new case makes is that the file
direct-plays.

## T10 — `media/names.py`: the invariant display title, and what it costs 008

- [x] **Changes:** `media/names.py` — pure — assembling the reference's own order joined with
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

**Done (2026-08-30).** The assembly is the six pieces in the order the task gives, and the module
is thirty lines. **What was wrong is one of those pieces: the undefined marker is `Undefined`, and
`Und` — the word the task and plan §6.4 both name, on the argument that the six are "the
reference's own literals" — is a string no reference of any configuration writes.**

**The literal is real and unreachable, and only a measurement separates those.** `Und` is what the
assembly writes when the localised property behind it is empty `[source:
MediaBrowser.Model/Entities/MediaStream.cs:422 @ v10.11.11]`, which is exactly what plan §6.4
said. But every subtitle stream is filled with all five localised strings on the way out of the
repository `[source: Jellyfin.Server.Implementations/Item/MediaStreamRepository.cs:156-167 @
v10.11.11]`, so the fallback is dead code on a served stream: measured, all five present on
**910 of 910** subtitle streams of a real library `[probe:
tools/probe_stream_display_title.py, Jellyfin 10.11.11, 2026-08-30]`. What is written is the
**translation table's** word, and its English row for the marker is `Undefined` `[source:
Emby.Server.Implementations/Localization/Core/en-US.json:84 @ v10.11.11]` where the four flag
words agree with their fallbacks letter for letter. So `Und` would have been a **third** string —
neither the English reference's nor the Spanish one's — which is the precise failure §3.2's own
definition of the invariant form ("what the reference itself writes on an English-configured
host") and plan §6.4's language-name paragraph were both written to avoid. Spec §3.2, plan §6.4
and behaviours §5's localised-properties row are corrected in this change.

**A probe that only described the assembly could not have caught it.** What caught it is that
`probe_stream_display_title.py` **reproduces** the string instead — every subtitle stream rebuilt
from its own properties, with the one piece this project cannot compute, the language name, read
off the streams that state a language and carry no title of their own. 909 of 909 rebuilt exactly,
every branch of the assembly reached: no language, hearing impaired, default, forced, external,
and a title that swallows an attribute. Reading the source alone would have reproduced the
sentence plan §6.4 already had.

**The culture lookup existed and answers this question too, which is the part the task got right.**
T3's `LANGUAGE_TOKENS` — token to culture row, first row winning — is the reference's own
localisation lookup and needed no second table (004 T15). Its first-row-wins is load-bearing on
this side as well: five rows carry `zho` and only the first is the plain `Chinese`, so a last-wins
index would label every Chinese subtitle track `Chinese (Traditional)`. The index is passed in
rather than imported, which keeps `media/` free of any dependency on `library/`, and plan §5 is
corrected: it declared one function and a `CultureIndex` type that does not exist.

**Two things the run could not reach, reported rather than inferred.** The size of the
language-name divergence on an *English* host cannot be measured from here — the reference
reachable from this repository is Spanish-configured — so what is stated is a bound: five of the
29 language tags a real library carries have a display name with an alternate spelling or a
qualifier and therefore cannot equal a platform name in any culture, and the other 24 are a single
word. And every one of those 29 tags is a terminological three-letter code, so none of the three
tag *shapes* the reference resolves differently was exercised: a two-letter tag and a bibliographic
code name no platform culture at all and are written as the raw tag with the first letter raised
(`En`, `Ger`), where this project's index answers a name. That is read rather than measured, the
probe reports the miss on every run, and plan §6.4 records it as left standing — narrowing it
means a second and deliberately worse lookup, and the difference lands inside the `NAME` divergence
§3.2 already accepts.

## T11 — The manifest: two bound parameters, the group on every variant, and AC-8's traversal

- [x] **Changes:** `api/delivery.video_parameters` gains `subtitleStreamIndex` and
  `subtitleMethod`, **neither with a validation pattern**, because an unrecognised value is
  ignored and not refused: `SubtitleMethod=banana` is no method, not a `400`. The five members are
  matched case-insensitively, which is what an enum-typed parameter does on the other side — and
  the lower-case spelling is the row plan §6.8 leaves owed, folded into
  `tools/probe_subtitle_manifest.py` here. **T9 measured the same word on the body side**: a
  declared `Method` binds in any case *and by ordinal*, while a word that is no member is a `400`
  `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]` — a strong prior
  for this row rather than a substitute for it, because a query value and a body value are refused
  differently everywhere else in this project (behaviours §1.12). **`EnableSubtitlesInManifest` is deliberately not
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

**Done (2026-08-30).** The block, the group on every variant and the traversal are the shape the
task describes, and `_variant` was the right place for the group. **What was wrong is the lever
itself: this statement, spec §3.4, AC-5, the ordering paragraph at the top of this file and
`specs/README.md`'s narrative all say the lever is `SubtitleMethod=Hls` *beside a
`SubtitleStreamIndex`*, and the index is no part of it.**

**The method announces on its own.** An address naming the manifest method with **no index at
all** announces every text subtitle stream of the source, and so does one naming `-1` and one
naming a stream that does not exist; what the index decides is which entry carries `DEFAULT=YES`,
and nothing at all when it matches no announced stream `[probe: manual requests via
tools/_probe.py, Jellyfin 10.11.11, 2026-08-30]`, `[source:
Jellyfin.Api/Helpers/DynamicHlsHelper.cs:192-210, 603-612 @ v10.11.11]`. That is not a detail on
this route: **the whole reason this task exists is a client that rewrites the address it was
handed** ([client-atrium-tvos §4.3](../../docs/compatibility/client-atrium-tvos.md#43-the-clients-track-override-works-for-audio-and-is-dropped-for-subtitles)),
and a server requiring the pair would have announced **nothing** to a client that sent one of
them - the manifest would have looked finished and the failure would have been invisible, which is
the exact shape §4.3 warned about in a different place. Spec §3.4 and AC-5 are amended here, with
the four other documents that repeat the sentence swept with them.

**And [plan §6.5](plan.md#65-the-manifest-extends-008-64) had it right where the spec had it
wrong**, which is worth recording because the two disagreed and nothing said so: its condition is
*"only when `subtitleMethod` is `Hls` and the source has at least one text subtitle stream"*, with
no index in it. An implementer reconciling the two would have taken the accepted spec. The plan is
amended for two other things instead (below).

**The owed row needed the measurement it was owed, and the prior held for three classes of four.**
`SubtitleMethod=hls`, `HLS`, `hLs` and the ordinal `3` in a query string announce exactly what
`Hls` announces, as T9's body-side run predicted. **A word that is no member does not refuse**: it
is a `200` announcing nothing, and so are an ordinal naming no member and an empty value - where
the same word on a request **body** is a `400`. The reason is a binder rather than a rule about
query values: Jellyfin binds every *nullable enum* parameter through one of its own that catches
the conversion failure and leaves the value unset `[source:
Jellyfin.Api/ModelBinders/NullableEnumModelBinder.cs:26-46,
Jellyfin.Api/ModelBinders/NullableEnumModelBinderProvider.cs:14-25 @ v10.11.11]`. **And the
parameter beside it in the same address does refuse**: `SubtitleStreamIndex=banana` is the
framework's problem details naming it, because that one is typed. One address, two subtitle
parameters, two different answers to an unreadable value - which is why the row said *measure*
rather than *infer*. The ordinal table moves from `api/media_info.py` to `media/decision.py`
beside the enumeration, because both binders now read it.

**And the vocabulary had one more class in it than any document imagined, which is the row that
kept a crash out of the server.** A comma-separated value is **one** value whose parts are
combined: `Embed,External` is `1 | 2`, the manifest method's own ordinal, so the reference
announces every text track for it, while `External,External` announces none and one unreadable
part makes the whole value unreadable - measured on all four, so the combination is discriminated
rather than assumed. Reproducing it is ten lines and skipping it would have been a delta on a
request that is one hand-written address away. Asking those four questions is also what found the
first draft of this function reading an ordinal with a bare integer conversion: `--3` and a
non-ASCII digit each **raised** there, which is a `500` where the reference answers `200` with no
announcement. Both are rows of the table now.

**Two smaller corrections to plan §6.5, both measured in the same run.** It says an unrecognised
method is ignored *"because an unrecognised value must be ignored rather than refused (behaviours
§1.12)"* - the right answer from the wrong rule, and the right rule is narrower and stronger. And
it says a master playlist asked for with no `mediaSourceId` *"announces the reference's own broken
address"*: that parameter is declared **required** there, so it is problem details naming it and
no manifest is answered at all. The empty address is a branch only 008's optional binding makes
reachable here, on a request the reference refuses; the reference's `string.Format` of a null is
reproduced for it and narrowing 008's binding is left where it belongs.

**The multi-variant case is measured, and the gate's warning about this probe was right.**
`_variant_line` returned the first `#EXT-X-STREAM-INF` and only that one, so the question could
not be asked; it is `_variant_lines` now. Against an HDR source whose video is copied the
reference answers **three** variants - the copy, an hevc entrance and an h264 one, the operator
having permitted the encoder Atrium has no knob for - and **all three** end in `,SUBTITLES="subs"`.
Atrium answers two of those three and both carry it.

**No fixture can be both high dynamic range and subtitled, and the reason is a pair of container
facts already in the matrix.** `high_range` has to be mp4 because the Matroska muxer drops its
colour statement, and mp4 accepts neither image subtitle codec; `both_subtitle_kinds` has to be
Matroska for the mirror of that reason. So AC-5's second half is asserted on an HDR film with a
**sidecar** beside it, generated into this module's own tree the way
`tests/conformance/test_hls_playlists.py` generates its Matroska sibling - which paid for itself
twice, because it is also the assertion that a track discovered beside the media is announced like
one inside the container, at the wire index T3's renumbering gives it. Measured on the reference
first, on a source whose three announced entries are all files beside it.

**AC-8's traversal follows addresses and it had to be pointed at the right track to start.** The
negotiation cannot select the `ass` track for a manifest at all - `ass` converts neither from nor
to, so it answers `Encode` under a `vtt`-only profile, which is AC-3 - so the traversal negotiates
for the sidecar. The `ass` track is *announced* anyway, because the filter is on the stream kind
and not on the selection, so both entries are still walked: manifest entry, per-track playlist,
every window of it, cues at the end, each hop resolved with `httpx.URL.join` against the previous
document so the lower-case `stream.vtt` is asked for exactly as written. AC-4 is the same walk
twice on a source with **two** text tracks whose cues differ, once per index, asserting the cues
that come back are the named track's - which is a claim that can fail.

**The token is `compat/auth.extract_token`'s, as the gate's own note said, and reaching the branch
where there is none took work.** A negotiated address carries the caller's token in its own query
string (008's `ApiKey`), so even a request with no header presents one - which is the reassuring
half: every announced address a client actually walks is credentialled. The test strips the
parameter to reach the empty form at all.

**One thing this task did not run, and the reason.** `probe_subtitle_manifest.py` gates itself
behind `--allow-writes` because its lever and anatomy batteries negotiate, and this task was to
probe the reference **read-only**; the whole script was therefore not run. Both batteries added
here build the master address by hand and negotiate nothing, so both were run against the live
reference on their own - twenty-one checks, all green, no play session opened - and every new claim
above carries `[probe: manual requests via tools/_probe.py, …]`, which is the form the tasks gate
used for the same question. Nothing is inferred from a run that did not happen.

**And one row left alone deliberately.** [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s
subtitle row still says the master announces no `#EXT-X-MEDIA` tag, which stopped being true in
this change - as its sidecar clause stopped being true at T4 and its delivery clause at T7. T12
closes that row once rather than correcting it four times, which is what this list already says.

## T12 — The acceptance map, the exact route set, and 011 is Implemented

- [x] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_011` — sixteen rows, each
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

**Done (2026-08-31).** The map is sixteen rows and the three status lines are flipped. **What
writing it found is what this task exists to find, and the sharpest of it is not a criterion at
all: [plan §9](plan.md#9-risks)'s first risk had fired, and the mitigation it prescribed could not
have caught it.**

**`-map` was handed the wire index, so every film with a subtitle file beside it produced the
wrong streams.** [Plan §5](plan.md#5-contracts) states the contract in as many words — *"`file_index`
is only ever an ffmpeg number: `media/ffmpeg.py` maps `0:{stream.file_index}` and nothing else may
read it"* — and `media/ffmpeg.py` mapped `0:{plan.source_index}`, which is the **wire** number: what
a client sends as `AudioStreamIndex`, what `DefaultAudioStreamIndex` states back, what the
transcoding URL repeats. A discovered subtitle file is numbered *ahead of* the container's own
streams, so on `The Unconvertible` — the one matrix entry with a file beside it — the video is wire
1 and demuxer 0, and `-c:v copy` was given the audio. Measured rather than reasoned: a remux of that
film answers **`200` with no video stream in the body at all**, which is a client handed a video file
with no picture and no error to explain it. `media/extract.py` has read `file_index` since T6. The
two numberings meet in exactly two places and only one of them knew it.

**Nothing could have seen it, and the reason is two documents that were each right on their own.**
§9's risk is this failure spelled out to its symptom — *"a delivery command maps the wrong track,
silently, only on items that have a sidecar"* — and the mitigation beside it is a unit test that the
two numbers differ wherever externals exist. That test exists and passes: it is a claim about
`renumber`, and the class also holds everything that *reads* what `renumber` produced. Beside it,
[T1](#t1--the-world-gets-subtitles-two-entries-one-sidecar-and-a-bitstream-ffmpeg-will-not-encode)
put the sidecar beside a film 008 asserts nothing about — the right call, for a written reason —
which left every produced-bytes test in this repository running over a source with no external
stream. A correct rule, a correct precaution, and the defect between them. The fix is one
expression and the tests are two, both failing without it: a command row over a source whose two
numbers are **stated apart** — an `InspectedStream` mirrors an unstated `file_index` onto its
`index`, so a source built the ordinary way agrees with itself whichever number is read, which is
why the existing mapping test could not reach this — and a produced-bytes row over the sidecar'd
film. §8 and §9 of the plan say so now.

**Four criteria named tests that proved less than the criterion**, the failure this project keeps
meeting and the one 008 T14 met twice:

* **AC-1 says *a listing row and a bare item*** and only the bare item had ever been asked. A list
  row carries its streams only when the request asks for them, so the request the criterion is
  about was the one nothing sent.
* **AC-11's *"is counted by `HasSubtitles`"*** was asserted on a film that carries an embedded
  track as well, so it passed with every discovered stream filtered out. It is asserted on the
  discovered streams alone now, which is the claim OQ-7 measured.
* **AC-12's *"affects neither the item nor its user data"*** had no test of any kind. The
  identifier is the load-bearing half — 003 derives it from the path and user data hangs off it
  with no foreign key — so a scan that re-created the item around the file would orphan a history
  silently and pass every other assertion in that file.
* **Two rows of [§3.7](spec.md#37-error-paths) had nothing**, and they are on the two routes that
  answer differently for the same identifier: the fetch routes' `500` for an item that exists and
  holds nothing servable — the row T7 shaped the whole lookup around, where an identifier naming
  nothing is the `400` — and the playlist's refusal of a source that states **no runtime**, the row
  marked ⚠️ *read, not measured* because no reference library can be put into that state from
  outside. Atrium can, from a test.

**And the definition of done's *two* divergences are three.** Burn-in is the third and it is the
largest: `Encode` is the reference's per-stream answer for **every** track no declared profile fits
(§3.3, OQ-5), naming such a track costs the source its direct play on both servers (T9), and this
server then produces the frames without the cues. It is an accepted gap and not a divergence — a
bounded shortfall with a closing mechanism, which is the roadmap's text-rendering stack — so it is
[behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1) and not §3, and the
argument §3 would demand is one this feature could not make. **Which is why that row is narrowed
rather than closed.** This task's own statement says the subtitle row is *"closed rather than
corrected again"*, and closing it to nothing would have deleted the only record of the one thing
this server says and does not do — and made two accepted sentences false, spec §2 and OQ-5 both
calling this gap *"already recorded"*. The `HasSubtitles` row is closed outright, the
no-per-user-preference row stays as the statement says, and the localised-properties row stays
because `NAME` is written in one place and withheld in another.

**Two smaller ones.** [Spec §6](spec.md#6-conformance)'s *"golden per profile class"* and
*"golden manifest per address class"* are pinned whole-response assertions rather than
`tests/golden/` files, which is the reading 008 T14 ticked the same line under and the only one
available for a manifest whose numbers come from the machine's own encoder. And the definition of
done's *"`-map` … has exactly one call site"* is two, one per module: `media/extract.py`'s and
`media/ffmpeg.py`'s, both reading `file_index` now, and the bullet says so rather than being
ticked as written.

---

## Definition of done

The feature is done when **all** of these hold:

- [x] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all sixteen —
      has a passing test, by name, in `FEATURE_011`. **Four of the sixteen named tests that proved
      less than the criterion said**, and the assertions they were missing are written: AC-1's
      listing row, AC-11's `HasSubtitles` on the discovered streams alone, AC-12's item and user
      data, and two rows of §3.7 (T12's note).
- [x] Every endpoint reaches the level [spec §6](spec.md#6-conformance) declares: the three L3
      surfaces carry goldens (the stream properties per kind, the negotiation per profile class,
      the manifest per address class) and the four L2 rows carry their shape, cue,
      fixture-mutation and table-driven error assertions. **The differential half of L3 is
      [010](../010-conformance-harness/)'s**, as it is for every feature before this one. *"Golden"
      is a pinned whole-response assertion here and a `tests/golden/` file only for the stream
      properties, which is the reading 008 T14 ticked this line under: a manifest's numbers come
      from the machine's own encoder, so a file-based golden would fail in CI for a difference that
      is not one in behaviour.*
- [x] The three routes are served, `"011"` is in `IMPLEMENTED_FEATURES`, `INTERIM_011` is gone,
      and no route exists outside [`surface.yaml`](../../docs/compatibility/surface.yaml) —
      counted against the file rather than against this list's prose, the sixth and last of the
      interim lists to go.
- [x] **Nothing burns anything in.** `media/ffmpeg.py` gains no subtitle filter and no second
      filter path; `Encode` is a word this server says, per stream, exactly where the reference
      says it. **Saying it and not doing it is a client-visible gap**, and T12 records it as one:
      [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s subtitle row
      is narrowed to exactly this rather than closed.
- [x] **The two numberings never meet outside `renumber`.** `media_streams.stream_index` is a
      demuxer index and `media_external_streams` has no wire column. **The rest of this line was
      false until T12**: `-map` has **two** call sites, one per module, and `media/ffmpeg.py`'s read
      the *wire* index while `media/extract.py`'s read the demuxer one — so every produced body of a
      film with a file beside it mapped one stream too far. Both read `file_index` now, the unit
      test asserting the two differ wherever externals exist is joined by one asserting what the
      **command** reads, and a produced-bytes test runs over the sidecar'd film.
- [x] The **two** divergences ship as behaviours records them: [§3.12](../../docs/compatibility/behaviours.md#312-a-subtitle-playlists-window-durations-are-written-in-the-servers-locale--class-b-diverged)
      (the invariant decimal point) and §5's localised-properties row (the `NAME` attribute's
      invariant assembly, now written in one place and withheld in another). **Every other
      response is byte-identical to the measured reference**, `LANGUAGE`, `FORCED`, `DEFAULT` and
      `URI` included — and the one place that sentence is knowingly weaker is latency: an image
      track's `400` arrives here without the reference's twenty seconds of attempted extraction.
      **This bullet said two and there are three observable differences**: a produced video whose
      selected track resolved to `Encode` carries the cues on the reference and not here. It is an
      accepted gap rather than a divergence — §3 would demand the argument that no client can see
      it, and a viewer can — so it is
      [§5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s narrowed subtitle row
      and the roadmap's own exclusion, and the count above is left as it was written with the
      correction beside it (008 T14's shape).
- [x] The owed readings are paid with citations in place: AC-10 against the same-format short
      circuit (T7), the playlist route's `itemId` (T8), the no-runtime row (T8), the lower-case
      `SubtitleMethod` (T11), `ttml` and the fetch formats' media types (T7), and the `hin` branch
      reported on rather than assumed (T3). Three readings stay readings and each says so on its
      own row, and each is a fact about what a reference library can be put into rather than a gap
      in a probe: the reference's refusal of a source with no runtime, the millisecond a zero-length
      cue is pushed out by, and the three language-tag shapes T10's index resolves and the
      reference's platform lookup does not.
- [x] Anything learned during implementation is back in `spec.md`, `plan.md` or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) in the same change that learned
      it, with provenance — nine amendments on the spec's frontmatter, twelve on the plan's, and
      the user's decision taken on each of the six occasions a task asked for one.
- [x] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`, with
      [`specs/README.md`](../README.md)'s table and narrative, [`docs/roadmap.md`](../../docs/roadmap.md),
      [`README.md`](../../README.md) and [`AGENTS.md`](../../AGENTS.md) saying the same thing.

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

---

## What this feature owes the next ones

**010 collects most of it**, because a differential is the only thing that can ask these — and two
of the rows are ones a differential will *not* find on its own, so they are named comparisons
rather than sweeps:

* **The manifest's `NAME` attribute**, the one place this feature knowingly diverges. The
  differential compares `#EXT-X-MEDIA` entries with `NAME` **masked** and compares that attribute
  against the invariant form ([spec §6](spec.md#6-conformance)); a reference configured in any
  culture but English disagrees on every announced track, and
  [behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s
  localised-properties row is the answer. Its language-name half carries a **measured bound** and
  not a claim: five of the 29 language tags a real library holds have a display name no platform
  culture equals, and three tag *shapes* — a two-letter tag, a bibliographic code — name no
  platform culture at all there and do name a row here (T10). A run against a library holding one
  closes what T10's could not reach.
* **The subtitle playlist's decimal point**
  ([behaviours §3.12](../../docs/compatibility/behaviours.md#312-a-subtitle-playlists-window-durations-are-written-in-the-servers-locale--class-b-diverged)).
  A byte comparison of the two playlists flags every fractional last window against a
  comma-writing host, and the entry is the answer. With `NAME` above it is the second and last
  subtitle response that differs **by design**; the attributes a client branches on — `URI`,
  `LANGUAGE`, `FORCED`, `DEFAULT` — are byte-identical.
* **Burn-in, and a differential cannot see it** — [§5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s
  narrowed subtitle row. Spec §6 declines to byte-compare produced media, so comparing bodies will
  report nothing; what says it is a **named** comparison — negotiate a track whose method resolves
  to `Encode` on both servers, produce a few seconds, and look for the cues in the frames. The same
  request also loses direct play on both, so the shapes agree and only the pixels differ.
* **An image track's `400` arrives here without the reference's twenty seconds** of attempted
  extraction. Same status, same twenty-five bytes, and a differential that measures latency will
  see it; it is the one place this feature is knowingly faster.
* **The two rows that are still readings**, each reported as a miss by its own probe on every run
  rather than inferred: a media source that states **no runtime**, which no reference library can
  be put into from outside (T8), and the **millisecond** a zero-length cue is pushed out by, which
  needs a file whose cue ends before it starts — 5 983 cues of a real library hold none (T7).
* **A subtitle file in a legacy encoding**
  ([behaviours §5.11](../../docs/compatibility/behaviours.md#511-a-subtitle-file-in-a-legacy-encoding-is-decoded-by-a-rule-and-not-by-a-detector)):
  a rule of three steps here against a statistical detector there, closed by putting a detector
  behind the same function with its runtime dependency argued in an ADR, on the day a real library
  needs one. A differential over an all-UTF-8 library will never raise it.

**Two are another feature's, and both were measured here rather than guessed:**

* **The four enums 008 binds are case-sensitive here and lenient there** (T9). A direct-play entry
  typed `"video"` binds and direct-plays on the reference and is a `400` here; what is lenient is
  the *binder*, not one enum, so the fix is `compat/model.py` — which every request model in the
  project inherits — and it belongs to whoever owns that model. 011 fixed only the vocabulary 011
  added. [012's OQ-4](../012-negotiation-inputs/spec.md) was widened rather than corrected in the
  same change, so there is one description of this and not two.
* **`&allowVideoStreamCopy=false` and `&allowAudioStreamCopy=false`** come off the same three lines
  of the reference as the burn-in flag T9 implemented, and Atrium honours both switches in the
  decision while repeating neither in the address. They are about audio and video copying and they
  are 008's ([plan §6.8](plan.md#68-what-no-probe-here-has-measured-and-what-stays-owed)).

**And one lesson rather than a row, for whoever adds the filter path burn-in needs.** The wire
index and the demuxer index part company on exactly the items this feature creates, and T12 found
`-map` reading the wrong one on both command builders — after [plan §9](plan.md#9-risks) had named
that failure and prescribed a mitigation that proves a property of `renumber` instead. Any new
`-map`, any new `-vf` that names a stream, reads `file_index`; and the test that catches it is one
over a source whose two numbers are **stated apart**, because a stream built the ordinary way
mirrors one onto the other and agrees with itself either way.
