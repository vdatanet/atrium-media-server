---
feature: 012-negotiation-inputs
title: Negotiation inputs — tasks
status: Accepted
created: 2026-09-03
updated: 2026-09-04
accepted: 2026-09-03
amended: 2026-09-03 at the gate — a zero-length file is not one of the two ways to reach this feature's subject on **this** server, because 003's walk skips it before it becomes an item; `SubtitleMethod` is the one vocabulary of five that already binds both ways, so T7's rows for it are a regression check and not a fix; the empty-string half of *"the default clause does not generalise"* is a reading of a converter and T1 measures it; `IMPLEMENTED_FEATURES` gains nothing, because 012 owns no row of `surface.yaml`; and the differential is run with the command `conformance.md` publishes. See "What the gate changed"
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 012 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries five structural decisions.**

**The measurement runs before any behaviour is written, and that is a decision this list inherits
rather than one it takes.** [Plan §11's D-4](plan.md#d-4--whether-68s-six-owed-measurements-are-this-features-or-its-first-tasks)
was taken on 2026-09-03: five of the six readings [plan §6.8](plan.md#68-what-this-plan-read-and-did-not-measure)
records as *read but not measured* are **inputs** to code written in T4, T6 and T7, not checks on
it — and one of them can send an accepted decision back to its owner. T1 is therefore a probe run
and nothing else, and it is the only task here that needs a reference server.

**The world gets files nothing can open before anything reads one.** Every criterion in this
feature is about a source whose file could not be inspected, and no entry in
`tests/fixtures/media.py`'s matrix is one — the module's whole shape is *ffmpeg writes it, ffprobe
verifies it*, which is the opposite of what four of these five fixtures are. T2 builds them, and
what it has to add to that module is a second kind of declaration rather than four more rows.

**The resolution lands in three tasks and not one, because the middle one writes.** T3 is
`library/inspection.py` as pure functions over values — the trigger, the transient inspection —
with table tests and no session. T4 is the write, which is the deviation this feature exists to
make and the one thing here that touches two tables 003 owns. T5 is the route, which is where
AC-1 through AC-5 become observable. A reviewer who disagrees with the deviation can say so at T4
without unpicking the trigger.

**The binder lands before the vocabulary it is needed for.** Typing `TranscodingProfile.Protocol`
as an enumeration *before* `compat/model.py` accepts the four measured classes would turn today's
wrong-shaped `200` into a `400` for `Hls` — a client that is correct against the reference, broken
between two commits. So T7 generalises the binder (and deletes 011 T9's narrow one), T8 gives a
nested refusal the key the reference gives it, and only then does T9 make the protocol an
enumeration. Each of the three is measurable on its own.

**Nothing here adds a route, so there is no interim list — and no entry in `IMPLEMENTED_FEATURES`
either.** [Spec §7.2](spec.md#72-the-dependencies-outside-this-document) is explicit that no row of
[`surface.yaml`](../../docs/compatibility/surface.yaml) changes, and `grep -c 'feature: "012"'`
over that file answers `0`. The exact-set route check is therefore green throughout, which is the
first time since 002 that has been true of a feature — and **012 is the first feature whose
closing task adds itself to no set any test reads**, which puts the whole weight of "every
criterion has a passing test" on the acceptance map (see T11).

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files they name
on 2026-09-03 before being accepted. **The first row was measured rather than read, and it takes
half of a sentence the accepted spec had said twice.**

| The draft said | It was |
|---|---|
| The state this feature is about is reached by *"a zero-length file, and bytes that are not the container the extension claims"* ([spec §3.2](spec.md#32-a-media-source-the-server-has-never-opened) and [§6](spec.md#6-conformance)) | **One of those two, here.** A real scan of a library holding a zero-length `.mkv` produces **no item at all** — not an item with an empty source, and not even an `Uninspected` report: `library/walker.py` skips a file of no length with `Skip.EMPTY` before it is ever a candidate. Measured in this repository on 2026-09-03 beside the case that does work: a 4 KiB junk `.mkv` in the same tree scans into a `Movie` with a source row of 4 095 bytes and **no probe row**, which is the state this feature exists for, reached. The reference admits the zero-length file and answers both a listing and a negotiation for it `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-08-29]`, so this is a **difference in an implemented feature and it is 003's** — handed on with its measurement rather than absorbed here, the way [D-2](plan.md#d-2--the-item-level-runtimeticks-which-is-not-this-features) was. Spec §3.2, spec §6 and plan §6.1 and §7 are corrected in this same change, and T2 declares no zero-length entry |
| T7 fixes five vocabularies that are each a `400` today where the reference answers `200` ([plan §6.7](plan.md#67-the-general-enum-binder)) | **Four.** `SubtitleMethod` is the fifth and it already binds in any case and by ordinal — that is exactly what 011 T9's `_bound_subtitle_method` does, and T7 **deletes** it. So its rows are a regression check: every `Method` assertion 011 shipped has to answer what it answers today, through the general binder instead of the private one. A task list that called it a fix would have counted a deletion as a feature |
| An empty string is still a `400` on all five, *"because none of those five enumerations declares a default"* (T7) | **True by reading and measured nowhere.** It is the load-bearing half of the plan's *"the default clause does not generalise"* — the argument that a binder generalising all four measured classes would answer `200` on five properties the reference refuses — and it rests on `JsonDefaultStringEnumConverterFactory.CanConvert` requiring `[DefaultValue]`. One request settles it, so T1 gains a sixth observation and T7 cites it |
| T11 adds `"012"` to `IMPLEMENTED_FEATURES` *"for the acceptance map's sake"* | **Neither half holds.** That set is read by `surface_paths()`, which filters `surface.yaml` by `feature`, and 012 owns **no** row there, so adding it changes nothing; and `test_every_implemented_feature_has_a_map` reads the **status table** in `specs/README.md`, not that set. 012 is therefore the first feature whose closing task adds itself to no set any test reads, which puts the whole weight of *"every criterion has a passing test"* on the map — said in T11 rather than discovered by whoever writes it |
| The differential is run as `python3 tools/differential.py` (T10) | **The command has four required flags and a fifth this feature needs.** [conformance.md's L3 section](../../docs/compatibility/conformance.md) publishes `--atrium`, `--jellyfin`, `--surface` and `--report`, and `--fixture` is what asks for the half that needs a single-use reference instance over this repository's own fixture — which is the only way either of 012's L3 rows can be compared, because the source they are about exists in no library but ours |

And one the review confirmed rather than changed, because a task would otherwise re-derive it:

* **Removing T5's `if inspection is None: continue` loses neither of the two flags it writes.**
  Since 008's policy-gate fix that branch sets `SupportsTranscoding` and `SupportsDirectStream`
  from the account's permissions. Traced through: `decide()`'s rule 1 calls the same two functions,
  `_annotate` writes all three flags off the answer, and a profile-less negotiation returns at the
  `supports_direct_play` guard before it can add an address. The answer for a never-opened source
  with no profile is identical before and after, field for field.

* **`_annotate`'s `decided.sub_protocol or wire.transcoding_sub_protocol` is a truthiness test on a
  field T9 makes able to hold an integer.** `0` is unreachable today because it binds to a member,
  which is exactly what makes it the kind of trap that survives review; T9 changes it to
  `is not None` in the same edit.

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — Measure the five things the plan read and could not check

- [x] **Changes:** `tools/probe_uninspected_source.py` gains a two-part film in its fixture (one
  readable part, one that ffprobe refuses) and five observations, each answering a numbered item
  of [plan §6.8](plan.md#68-what-this-plan-read-and-did-not-measure): **(1)** the whole body of the
  audio item's `400`, printed rather than truncated at 60 bytes, against the plan's reading that it
  is the middleware's fixed `Error processing request.`; **(2)** the `errors` **message** beside the
  key `$.DeviceProfile.TranscodingProfiles[0].Protocol`, which no run has recorded — the key alone
  is what the gate measured; **(4)** the same negotiation over `GET /Items/{itemId}/PlaybackInfo`,
  to confirm the profile-less route probes on demand and heals the listing as the `POST` does;
  **(6)** the `ETag` of a healed source before and after, which is what
  [D-1](plan.md#d-1--the-healed-items-etag) rests on; and **(3)** what a refresh does to the
  **second** part of a multi-part item whose first part is annotated and whose second is not. Plus
  a sixth the gate added, on `tools/probe_playback_info.py` rather than here: **an empty string
  against an enumeration that declares no default** — a codec profile's `Type`, say — which
  [plan §6.7](plan.md#67-the-general-enum-binder) predicts is a `400` there and which is the
  load-bearing half of *"the default clause does not generalise"*. It is read off a converter and
  measured nowhere, and T7 asserts it.
- **Depends on:** —
- **Verified by:** `python3 tools/probe_uninspected_source.py http://127.0.0.1:8097 -u admin
  --allow-writes --fixture-root "$PWD/fixture" --server-root /media` against a Jellyfin 10.11.11
  the probe's own docstring describes standing up, or the single-use instance
  [`tools/reference_instance.py`](../../tools/reference_instance.py) 010 T9 built. The run must
  print all five observations and conclude; each of the five is then written into
  [plan §6.8](plan.md#68-what-this-plan-read-and-did-not-measure) with its `[probe: …]` citation
  **in this same change**, whether it confirms the reading or contradicts it.
- **Spec reference:** §7 (the gate's four probes); plan §6.8, §11 D-4

**Two of the five could move a decision, and both did something.** D-1's condition is
**discharged**: the change signal moves across a heal, so writing it is parity and T4 keeps it. And
the multi-part question was retired rather than answered: there is no *"part zero annotated, part
one not"* on the reference to be faithful to.

**Done, 2026-09-03** — one run of each probe against a single-use instance of the pinned version,
six answers, four confirming the reading and two not.

* **The audio body is the middleware's sentence, exactly**: `400`, `text/plain`, **25 bytes**,
  `Error processing request.` — the `CONTROLLER_ERROR_BODY` this project has sent since 002, so
  T6's golden is a constant it already holds.
* **The `GET` route probes on demand and heals the listing**, in 0.23 s, answering flags all
  `true` and no address because nothing was negotiated. T5's *"both routes, before the profile
  branch"* is measured rather than read.
* **The change signal moves**: `ETag` `d430f79a…` → `58271a54…` and `Size` 4 096 → 148 301 across
  one heal. D-1 is parity.
* **There is no second part to re-read.** A two-part film whose `- part2` is 4 KiB of noise is
  **one item with one media source**: the unreadable part is neither a source of the grouped item
  nor an item of its own — where the *same bytes* alone in their own folder are an item with an
  empty source. The probe's own check had assumed two sources and failed, which is what a check is
  for; it now asserts the measured shape. T3 asks the same question of **Atrium's** resolver
  instead of assuming the answer.
* **The empty string is a `400` on an enumeration that declares no default** — a codec profile's
  `Type` and a direct-play entry's `Type`, both refused, against the protocol's own `200` as the
  control. §6.7's default clause stays registered per enumeration; generalising it would answer
  `200` on five properties the reference refuses.
* **The nested refusal's message is not the message this project sends**, and this is the finding
  that resizes a later task. It names the enumeration by its fully qualified name, repeats the
  property's JSON path in `Path:`, and its `BytePositionInLine` is the byte offset of the end of
  the offending token **in the body as sent** — 398, 395, 396 for three tokens in one body, and
  153 for a property earlier in it. The same failure on `POST /Playlists`, asked in the same run,
  is keyed `$`, says `Path: $`, and counts `len(token) + 2` wherever the property sits. One
  failure, two shapes, two routes: `compat/errors.py` ships the first as a single constant, T8 has
  to produce the second, and the integer inside it is **D-6**, reserved.

Plus one nobody asked for: a **zero-length** file is an item on the reference — `Size: 0`, a
listing with three `true` flags, a negotiation answering `false`/`false`/`true` with an address —
which is the other half of what [the task gate](#what-the-gate-changed) measured here. Both sides
of that difference are now measured, on the same day, and it is 003's.

**Two deviations from this task as written, both recorded rather than tidied.** The refusal's
message and the empty-string class were measured by `tools/probe_playback_info.py` and not by
`tools/probe_uninspected_source.py`, because that is where the protocol battery and its eighteen
spellings already live — a second copy of them would be a second answer to one question. And the
`GET` route needed a **second** latent file: once a negotiation has healed the first, the question
of which route did the healing cannot be asked again.

## T2 — The world gets files nothing can open

- [x] **Changes:** `tests/fixtures/media.py` gains a declaration kind it has not got: an entry
  whose bytes are **written directly** and whose invariant is that the prober *refuses* it — and
  never a **zero-length** one, which 003's walk skips before it can become an item (see "What the
  gate changed"). Four entries and one addition follow — `unreadable.mkv`, four kibibytes that are
  not a container, in the films root; `latent.mkv`, the same bytes, which a test replaces with a real file after the
  scan; `soundless` (an audio item in the music root whose file carries **no audio stream**), for
  which `MediaFile`'s audio fields become optional — every entry declares one today; `videoless`
  (a film whose file carries no video stream), which the declaration already expresses; and a
  **two-part** film whose first part is readable and whose second is not. `GENERATOR_VERSION` is
  bumped, because what the module generates has changed in a way the existing declarations do not
  express.
- **Depends on:** T1 (which decided what the two-part entry can be compared against: on the
  reference, nothing — so the entry exists to ask **this** server the question)
- **Verified by:** `uv run pytest tests/unit/test_media_fixtures.py -q` — the four unreadable
  entries make `media/probe.py:inspect` raise `UnreadableMediaError` and the two readable ones
  probe back to exactly what they declare, which is the module's own invariant read from both
  ends. **And a zero-length file in the same tree produces no item at all**, asserted as the
  boundary of what this feature can be tested against rather than left to be rediscovered. Then a new assertion in the same module, which is the only place `scanned_media_world` is exercised: after a real scan **each of these
  files is an item with a source row and no probe row** — the state this whole feature is about,
  asserted rather than assumed, because `library/scan.py` records an uninspectable file and carries
  on and nothing has ever checked that an item survives it. And `uv run pytest tests/ -q -m "not
  ffmpeg"` staying green.
- **Spec reference:** §6 (the fixture, which is *"a subtraction"*); plan §8

**Two of the three assertions above were run at the gate rather than left to this task**, because
the whole fixture premise rests on them: a 4 KiB junk `.mkv` scans into a `Movie` with a source row
of 4 095 bytes and **no probe row** — the state this feature is about, reached — and a zero-length
`.mkv` beside it produces nothing at all, not even an `Uninspected` report.

**The invariant test's premise is inverted here, which is why this is a declaration kind and not
four rows.** Every existing entry means *"ffmpeg wrote this and ffprobe agrees"*; these mean
*"these bytes are on disk and ffprobe will not have them"*. Writing them as `MediaFile` rows would
make the invariant test assert a codec against a file that has none.

**Done, 2026-09-04** — five entries, a second declaration kind, and **two differences nobody was
looking for**, both of them 003's.

* **The premise holds, and it is asserted now rather than assumed.** A 4 KiB junk `.mkv` scans
  into a `Movie` with a source row and **no probe row**; the scan records the refusal and carries
  on. Nothing had ever checked that an item survives a file the scan could not open, and every
  criterion of this feature runs on it.
* **Atrium keeps the unreadable second part of a film; the reference keeps it as nothing.** T1
  measured that side: there, `The Missing Half - part2` is neither a source of the grouped item
  nor an item of its own, and the item answers **one** media source. Here the grouping is a naming
  decision and the inspection is a separate step, so the item answers **two** sources and the
  second has no probe row — which is exactly the state [plan §6.1](plan.md#61-the-trigger) needs
  and the state the reference cannot show us. **It is a difference between the two servers**, in
  003's territory, and it is declared in the reference-reading comparison rather than designed
  around.
* **The reference names an artist off the path where Atrium reads it off the tags.** `soundless`
  is a readable mp4 with no audio stream and full artist and album tags. Atrium reads them and
  hangs the track under `Soundless Artist`; the reference hangs it under its **folder**,
  `Quiet Corner` — a file with no audio stream is one it has no audio metadata reader for, so it
  falls back to the path. Nobody was looking for this, it is 003's and 004's to decide, and it is
  declared with its reason.
* **Adding to the fixture costs a re-recording, which this task had not priced.** The fixture tree
  is what 010's AC-2 compares two servers over, so five new files invalidated
  `docs/compatibility/reference-fixture-reading.json`. It was **re-taken against a single-use
  instance of the pinned version** rather than edited — which is the order the failure message
  demands — and the declared differences moved from **forty-seven to fifty**: the two above plus a
  film named after its folder, year and all, which is a shape that table already had four of. The
  dated records of the 2026-09-02 measurement in 010's own documents are left as they are; what
  moved is the module that counts.
* **The suite defended its own invariant against this change.** `soundless` was first written
  under folders named after its tags, and
  `test_the_high_rate_track_scans_from_its_tags_and_not_its_folders` failed — a world where the
  two agree cannot tell a scan that opened the file from one that read the path. The fixture moved
  to `Quiet Corner/Unnamed Folder`, not the test.

**The task said "one module" and it was five.** `MediaFile`'s audio fields becoming optional
reaches `tests/unit/test_media_probe.py`; a world containing files nothing can open reaches
`tests/library/test_media_inspection.py` (a scan's refusals are no longer empty, and are
re-attempted on **every** scan because there is no stored inspection for a signal to compare
against) and `tests/library/test_sidecar_discovery.py`; and the fixture tree changing reaches
`tests/library/test_reference_reading.py`. Each was taught what is true rather than loosened.

## T3 — `library/inspection.py`: the trigger, and the inspection that is never stored

- [x] **Changes:** a new module with the four functions
  [plan §5](plan.md#5-contracts) declares — `wanted`, `opened`, `store`, `unopened` — of which
  this task lands `wanted` and `unopened` complete and `opened` as the thin, never-raising wrapper
  around `media/probe.py:inspect`. `wanted` is the reference's condition and not the shape of the
  defect: source **zero** carrying no stream of the item's own kind, or a path ending `.strm`
  `[source: Emby.Server.Implementations/Library/MediaSourceManager.cs:175-178 @ v10.11.11]`.
  `unopened` builds the transient `MediaInspection` from the stored source row — an empty
  container, so `media/info.py:source_container` still answers the file's extension.
- **Depends on:** T2
- **Verified by:** `uv run pytest tests/unit/test_library_inspection.py -q` — a table over the
  trigger with the two cases that separate it from the naive reading: a **video** item whose only
  file was inspected successfully and holds no video stream fires it (and fires it again on the
  next call, for ever), and a two-part item whose part zero is annotated and whose part one is not
  does **not**. **That second row also asks a question of 003 that T1 could not ask of the
  reference**, because the reference has no such item: whether Atrium's own resolver keeps an
  unreadable second part as a source with no probe row, where the reference keeps it as nothing at
  all. Whatever it answers is recorded — as a difference if it is one — and not designed around. Plus: `unopened()`'s result put through `media/info.py:source_of` answers byte for
  byte what a `None` inspection answers today, which is what keeps AC-10 true.
- **Spec reference:** §3.2, AC-1; plan §5, §6.1

**`opened` swallows both inspection failures on purpose.** `ProberUnavailableError` and
`UnreadableMediaError` mean opposite things to a scan and the same thing to one request, and
`library/scan.py` keeps the distinction where it decides something (003 §3.7).

**Done, 2026-09-04** — the module, the table, and four things the documents had incomplete rather
than wrong, two of them resizing what T4 writes; plus the question T1 could not ask, answered.

* **The condition is a conjunction and this feature had described a disjunction.** Beside the
  three clauses [plan §6.1](plan.md#61-the-trigger) lists there is a fourth in front of them: the
  reference declines to probe at all when source zero is a **placeholder** — the source of a
  recording in progress, or a source with no path
  `[source: MediaBrowser.Controller/Entities/BaseItem.cs:1103, 1159 @ v10.11.11]`. Nothing
  observable moves, because v1 has neither shape, and that is exactly why it is written and cited
  rather than dropped: the plan's own reason for keeping `.strm` — *"how a later reader learns the
  condition was three and not two"* — applies to the clause the plan itself did not have. Spec
  §3.2 and plan §6.1 say so now.
* **[Plan §6.2](plan.md#62-resolving-inside-the-request)'s call to `store` cannot write what D-1
  decided to write**, found by declaring the signature rather than by reasoning about it. The
  pseudocode passes a library and a path; `item_sources` is keyed `(item_id, part_index)`, and
  [§5](plan.md#5-contracts)'s contract has both. Written as it stood, T4 could satisfy the line
  only by dropping the change signal — the whole of D-1 — or by reaching for
  `ItemRepository.update`, which rewrites every part of the item from a whole `Item` and is the
  power [§4](plan.md#4-data-model) says a negotiation must not have. The pseudocode is corrected in
  this change.
* **The invariant T4 has to test now has something to test with.** *"`store` never receives what
  `unopened` produced"* was a rule with no observable difference between its two sides; the empty
  container `unopened` writes is one — `media/probe.py:inspect` raises rather than return an
  inspection whose container has no name, so no real inspection can carry it. It is a constant in
  the module (`UNOPENED_CONTAINER`) rather than a sentence in a docstring.
* **AC-10's guard is six functions and not one, and there is exactly one input on which it fails.**
  `source_of` is what the negotiation hands the transient record to; five more functions in
  `media/info.py` read the same sequence to build an *item* body and the listing routes call them.
  All six answer identically — `item_container` being the one that would not have, since only an
  **empty** container falls through to the extension the way a missing inspection does. The
  exception is a source row with **no size**: `Size: 0` against `Size: null`, because
  `item_sources.size` is nullable and an inspection's is not. No scan produces one —
  `library/walker.py`'s `Candidate.size` is an integer from a `stat()` and is the only writer of
  that column — and the boundary is a test naming it rather than a defence against it.
* **The question T1 could not ask of the reference is answered, and it confirms T2 from the other
  side.** A real scan of the generated tree makes the two-part film **one item with two sources**,
  the second carrying no probe row, where the reference keeps the unreadable part as neither a
  source nor an item `[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`.
  The item shapes differ — 003's difference, declared in the reference-reading comparison at T2 —
  and the trigger's answer does not: source zero is annotated, so nothing fires and 012 never opens
  that part, which is what the reference does with the item it has.

**One deviation from the task as written.** *"A video item whose file holds no video stream fires
it again on the next call, for ever"* is asserted by really opening the file and asking again with
what the inspection learned, rather than by calling a pure function twice with one value — the
second is true of any function of its arguments and asserts nothing about this one.

## T4 — The write: an inspection and a change signal, from a request

- [x] **Changes:** `library/inspection.py:store` writes the inspection through
  `MediaProbeRepository.put` — the scan's own repository, unchanged — and the file's `(size,
  mtime_ns)` beside it ([D-1](plan.md#d-1--the-healed-items-etag)), through a **new narrowly-scoped
  method** on `ItemRepository`: two columns of one part, updated in place. The existing writer
  deletes every part of the item and rewrites them from a whole `Item`, which is neither what a
  negotiation has nor a power it should hold. **The three sentences this retires move in this
  change**: [008 plan §6.1](../008-playback-negotiation-and-delivery/plan.md#61-inspection-and-the-cache),
  that plan's §7 failure row, and `MediaProbeRepository`'s own docstring, each gaining the one
  route that may open one file.
- **Depends on:** T3
- **Verified by:** `uv run pytest tests/unit/test_library_inspection.py tests/unit/test_repositories.py -q`
  — after `store`, the probe row and the source row describe the **same bytes** (the size and the
  modification time from one `stat`, which is why `inspect` reads one at all), a second `store` of
  the same file replaces rather than duplicates the streams, and the narrow method **cannot** reach
  a name, a parent or `removed_at`. And the invariant with a test of its own: `store` refuses a
  `MediaInspection` that `unopened` produced, asserted by making the wrong call fail rather than by
  a docstring — a stored transient inspection would satisfy `MediaProbeRepository.current()`
  against the file's real stat and the **next scan would skip the file for ever**.
- **Spec reference:** §4 (data the feature owns); plan §4, §5, §11 D-1

**Done, 2026-09-04** — the write, the narrow method, and four things the documents had incomplete
rather than wrong; one of them is a trap set for the next task and one amends the accepted spec.

* **The method that writes two columns takes three arguments, and the third one is a check.** The
  inspection is stored under `(library_id, relative_path)` and the change signal under `(item_id,
  part_index)`, and **nothing in those two keys says they name the same file** — which is exactly
  the pair [T3](#t3--libraryinspectionpy-the-trigger-and-the-inspection-that-is-never-stored)
  corrected [plan §6.2](plan.md#62-resolving-inside-the-request) to hand over. A `store` given a
  part index one out — a two-part film being the shape that produces one, and this feature ships
  one — writes the probe row for the file it opened and that file's change signal onto its
  **sibling**, and every assertion about either row on its own still passes: the probe row is
  right, the source row is a well-formed `(size, mtime_ns)`, and the wire answers a tag for the
  wrong bytes on two sources instead of one. `record_change_signal` therefore takes the part's
  `relative_path` and refuses when the row names another file, and refuses a part that is not
  there rather than doing nothing quietly. `store` makes that call **first**, so a refusal leaves
  neither row written instead of a healed probe row whose signal was never updated — the exact
  half-healed state D-1 exists to prevent. Plan §4 and §5 say so now.
* **D-1 buys a second thing, and it is the scan rather than the wire.** The decision was argued
  entirely on the entity tag. But `library/scan.py:_differs` compares `before.sources !=
  after.sources` and a `MediaSource` carries its own `(size, mtime_ns)`, so the change signal is
  what the **scan** compares an item against too. Measured both ways on a real scan of the
  generated tree: with the write, the rescan after a heal reports `updated == 0`; with only the
  probe row, it skips the inspection — the probe row is current — and **rewrites the item anyway**,
  one claimed update per healed file, for ever. Option (b) was never "the same behaviour with a
  stale tag". [D-1](plan.md#d-1--the-healed-items-etag) records it.
* **The trap this task found is in the task after it.** `api/media_info.py:_negotiation` builds
  its wire sources from `sources_for(found.item, …)` **before** the per-source loop, and
  `found.item` is a frozen object read before any of this ran; `store` writes `item_sources` and
  must not mutate it. So a T5 that inserts the resolution above that line and changes nothing else
  answers, **in the healed body itself**, a `Size` from the inspection beside an `ETag` from the
  part the scan recorded — `media/info.py:source_of` takes the two from different places on
  purpose — which is D-1's own failure occurring one line inside the request that fixed it. Plan
  §6.2 now says T5 rebuilds the part from what `store` wrote and asserts the negotiation's own
  answer and not only the listing after it.
* **The harm the invariant names is one line longer than the invariant says, and it is measured
  now rather than argued.** A stored transient inspection does make the next scan skip the file —
  confirmed on a real scan, and a deep scan is the only cure — but it also takes the file out of
  the scan's `uninspected` report, so the library's own record of what it could not read goes
  **empty** while nothing in it plays. That is the symptom an operator would have to debug, and it
  is the one the report exists to prevent.

* **003 has an exact-set guard on this class and it fired, which is the review this task wanted.**
  `test_the_repository_still_has_no_way_to_delete_a_row` asserts `ItemRepository`'s public surface
  as a **set**, not a subset — written at 003 T17 so that the scanner's inability to destroy a
  library is a shape rather than a discipline. Adding the narrow method turned the suite red until
  a human read what was being added to the one class whose whole argument is what it cannot do,
  which is exactly the gate 012's write should have to pass. The set now names it and says why.

**And the accepted spec gains a row.** [§4](spec.md#4-data-the-feature-owns) listed two pieces of
state and D-1 writes three: the opened file's **change signal** is observable as the healed
source's entity tag on the next listing, and the document promised only the streams, the runtime,
the bitrate and the size. The reference moves both across one heal
`[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`, so it is parity, no
criterion moves, and the amendment is recorded in the front matter with the others.

**One deviation from this task as written.** `tests/unit/test_repositories.py`'s boundary sweep
opens by calling itself a walk over *"every public method of the module"* and names six of the
eleven repository classes there; `ItemRepository` — the class this task gives a new writing method
— was one of the five outside it. It is in the sweep now, with `atrium.domain.items` admitted to
the allowed set, and the remaining four are noted in the list itself rather than swept blind: each
needs its own domain module admitted, and admitting one without reading it is how a sweep starts
passing for the wrong reason.

## T5 — The negotiation resolves before it reads the profile

- [x] **Changes:** `api/media_info.py`'s `_negotiation` becomes `async`, and before the source
  loop it resolves: `wanted` → `opened` in a thread (`asyncio.to_thread`, the project's idiom for
  blocking work) → `store` or `unopened`. The `if inspection is None: continue` branch **goes**,
  and with it the two policy flags it writes — checked, not assumed: `decide()`'s rule 1 calls the
  same two functions itself, so a profile-less negotiation answers exactly what it answers today.
  Both routes are covered, because the reference's `GET` calls the same helper with the same
  `allowMediaProbe` `[source: Jellyfin.Api/Controllers/MediaInfoController.cs:87 @ v10.11.11]`.
- **Depends on:** T4
- **Verified by:** `uv run pytest tests/conformance/test_playback_info.py tests/conformance/test_media_shapes.py -q`
  — AC-1: `unreadable.mkv` against a profile that plays neither its container nor its codec answers
  `false`/`false`/`true` **and** a `TranscodingUrl` (AC-4). AC-2 and AC-3: `latent.mkv` listed
  (empty), negotiated (two streams, a runtime, a bitrate, a corrected `Size`), listed again — the
  second listing carrying what the negotiation learned, with no scan in between. AC-5 against a
  source the profile **can** direct-play, comparing two whole bodies rather than one property:
  asked against `unreadable.mkv` and a profile that plays nothing, both answers refuse and the test
  would pass while asserting nothing. AC-10: the three listing routes byte-identical before and
  after a negotiation *of a different item*. Plus a test that the route yields — a slow stub prober
  and a second request answered while the first is still inspecting.
- **Spec reference:** §3.2, AC-1 to AC-5, AC-10; plan §6.2, §6.3

**Done, 2026-09-04** — the route, the ten tests its Verified-by line names, and three things the
documents had wrong rather than merely incomplete; one of them amends the accepted spec, and one
was a sentence about this route that was false about every clause it had.

* **The branch that goes was answering a source neither document had described, and deleting it
  had to answer that source too.** [Plan §6.2](plan.md#62-resolving-inside-the-request)'s
  pseudocode fills `resolved[index]` only inside `if wanted(...)`, so a part with no inspection in
  an item whose **source zero has one** keeps a `None` — and `if inspection is None: continue` was
  what used to answer it. This server ships that shape as a fixture: T2's two-part film is one
  item with two sources, the second with no probe row, where the reference keeps the unreadable
  part as neither a source nor an item. Both documents stopped at the **trigger**, which decides
  what is *opened*; nothing said what is *answered*. It is answered by §2.2's own rule — the flags
  decided and an address beside them — and the file is still never opened, because the trigger is
  a property of the item and source zero is annotated. So this feature's two halves come apart on
  one real source, which is worth a sentence in a document rather than a reader's inference: spec
  §3.2 gains it (recorded as an amendment) and plan §6.2 says so now.
* **"The write happens back on the loop thread, through the request's own session, where every
  other write in this route already happens" is false in both of its clauses.** There is no
  request session: `_negotiation` reads the item through `_found`, which opens a `session_scope`
  and **closes it before it returns**, and `api/media_info.py` has never written anything at all —
  it is a reader, which is the very reason 012 is a *deviation* from 008 plan §6.1 rather than one
  more write beside existing ones. Written to the sentence, the write would have had a closed
  session to reach for. `store` runs in a unit of work the resolution opens after the probing is
  done, which also keeps `opened()`'s *"touches no session"* promise meaningful rather than
  incidental.
* **T4's trap is real, and the assertion that catches it is not the one the listing makes.**
  Rebuilding the healed part (`dataclasses.replace` on the `MediaSource`, then on the `Item`) was
  written first and then **removed again to watch it fail**: without it the healed body answers
  `Size` from the inspection beside `ETag` from the row the scan wrote — two files in one answer,
  inside the request that fixed the file. The listing afterwards is correct in both worlds, so a
  test written only against it would have passed. The negotiation's own answer is asserted, as
  [plan §6.2](plan.md#62-resolving-inside-the-request) now requires.
* **The gate's traced claim is measured now rather than inherited.** *"Removing the branch loses
  neither of the two flags it writes"* is asserted over the **same five policy shapes** the
  inspected source's own table uses, on the never-opened source, on both routes: five identical
  triples, and no address on the profile-less path. The branch was not load-bearing, which is now
  a row rather than a paragraph.

**One deviation from this task as written.** *"A test that the route yields"* is written without a
clock (Principle VII): the stub prober blocks on an event, a second request is answered while the
first is still inside it, and the first is asserted **not done** before the event is released.
A duration assertion would have been a flake; this one fails on its own timeout if the inspection
ever stops leaving the event loop, and was checked by running the probe inline and watching it go
red.

## T6 — The audio refusal, which is the platform's and not this feature's

- [x] **Changes:** `compat/errors.py` gains `NegotiationRefusedError` and its row in
  `EXCEPTION_HANDLERS`, answering `controller_error(400)` — `text/plain` and the 25 bytes
  `CONTROLLER_ERROR_BODY` has held since 002. `api/media_info.py` raises it inside the source loop,
  on the first source of an **audio** item whose selected audio stream is `None` when a profile is
  in play. The condition is the missing audio stream, **not** the unreadable file: a readable
  `soundless` entry is refused identically.
- **Depends on:** T5
- **Verified by:** `uv run pytest tests/conformance/test_playback_info.py -q` and a golden — AC-6
  in both halves: with a profile, `400`, `Content-Type: text/plain` and the exact 25 bytes T1
  printed; with no profile and no stored device profile, `200` and the un-annotated source. Plus
  the row that separates the two conditions: `soundless` **after** a successful inspection is still
  a `400`, which is what a condition written as *"the inspection failed"* would get wrong while
  passing every other test here.
- **Spec reference:** §3.4, AC-6; plan §6.4

**Done, 2026-09-04** — the class, its row, the raise and six tests, and three things the documents
had wrong rather than merely incomplete; one of them decides what a multi-part audio item answers
and one is a fixture that does not exist.

* **The plan says the refusal happens in two places, and only one of them refuses the item this
  server can build.** [§5](plan.md#5-contracts)'s contract for `_negotiation` reads *"two things
  happen **before** the per-source loop … and an audio item with no audio stream is refused"*,
  where [§6.4](plan.md#64-the-audio-refusal) puts it **inside** the loop, on the first offending
  source, and says in the next sentence that a second part with no audio stream takes the whole
  answer down with it. Those are two different answers for one item, and the reference settles it
  from the other side: the builder is called once **per media source**, all of it inside
  `if (profile is not null)`
  `[source: Jellyfin.Api/Controllers/MediaInfoController.cs:189, 192 @ v10.11.11]`. Written to §5,
  a two-part audio item whose part zero carries audio would be answered where the reference
  refuses — and every test in this section would still pass, there being no such fixture. §5 is
  corrected and §6.4 now carries the citation for both of its halves at once.
* **AC-6's second clause had no world to be proven in, and building one is not this task's to
  spend.** The criterion and [plan §8](plan.md#8-testing-strategy)'s own row ask for *"`200` and
  the **un-annotated** source"* from `soundless.m4a` — which is **readable**, and whose
  profile-less answer therefore carries a video stream, a runtime and a bitrate. All four declared
  un-inspectable files are films ([T2](#t2--the-world-gets-files-nothing-can-open)), so an *audio*
  item nothing has opened exists nowhere in the matrix. A fifth declared file is not the cheap fix
  it looks like: T2 priced it, and it moves the fixture tree 010's AC-2 compares two servers over,
  which is a re-recording against a single-use reference instance rather than a test. The state is
  made in the test instead — `unreadable.mkv`'s junk bytes written over `soundless.m4a` **before**
  the scan, which reaches an `Audio` item with a source row and no probe row without adding a file
  to the tree. Plan §8's fixture table and its AC-6 row say so now.
* **The task named two files and the change is three, because the condition is the ladder's and
  not a stream count.** `media/decision.py:_selected_audio` is now public `selected_audio`: the
  refusal is what the reference's audio builder does when *that* selection answers nothing, and a
  second rule beside the ladder is the kind that drifts silently once an index or a default
  changes. It is asked with **no index** — `GetDefaultAudioStream(null)`
  `[source: MediaBrowser.Model/Dlna/StreamBuilder.cs:104 @ v10.11.11]` — so the body's
  `AudioStreamIndex` does not enter the refusal at all. Nothing observable moves either way, the
  selection being `None` exactly when there is no audio stream, which is precisely why passing the
  switch's index would have been a claim about the reference that the reference does not make.
  Plan §6.4 records it.
* **The three refusing tests were run red before they were run green.** The raise was deleted and
  the section re-run: the two `400`s and the stored-profile one fail with `200`, and the two
  controls — the profile-less `200` and the film with no video stream — stay green, which is what
  says they are controls. The film is `videoless.mkv` and it is the mirror image the refusal has
  to survive: the **video** builder has no `ThrowIfNull` beside the audio builder's, so a
  condition written as *"an item with no stream of its own kind"* would refuse a film the
  reference answers `200` for (spec §3.4, row one).

**One deviation from this task as written.** *"And a golden"* is not a shape this refusal has:
`tests/conformance/golden.py:path_for` writes `<name>.json` and every checked-in golden is a JSON
body, where this is 25 bytes of `text/plain`. The bytes are asserted as the **literal**
`b"Error processing request."` with its length and its content type, and deliberately **not**
against `CONTROLLER_ERROR_BODY` — a response compared with the constant it was built from is
Atrium compared with itself, which is [001 T16's](../001-server-identity-and-discovery/tasks.md)
finding and the reason the literal is written out. The value is T1's, printed off the reference
`[probe: tools/probe_uninspected_source.py, Jellyfin 10.11.11, 2026-09-03]`.

## T7 — One binder for every vocabulary a body carries

- [x] **Changes:** `compat/model.py` gains a validator beside `_accept_any_casing`, per field whose
  annotation is an `Enum`: a member unchanged; a **bool** unchanged (`isinstance(True, int)` is the
  trap — `true` is a measured `400` and the ordinal `1` a measured HLS); an integer or a digit
  string as the ordinal, keeping the raw number when no member has it; a name matched case-folded;
  and `None` or `""` as the **declared** default *only where one is registered* — a
  `@wire_default` class decorator, because what the reference reads is `[DefaultValue]` on the enum
  type `[source: src/Jellyfin.Extensions/Json/Converters/JsonDefaultStringEnumConverterFactory.cs:20
  @ v10.11.11]`. `api/media_info.py`'s `_bound_subtitle_method` is **deleted**: it is the narrow
  binder 011 T9 wrote and pointed here, and leaving both would be two answers to one question.
- **Depends on:** —
- **Verified by:** `uv run pytest tests/unit/test_compat_model.py tests/conformance/test_playback_info.py
  tests/conformance/test_subtitle_manifest.py -q` — `ProfileType`, `ConditionType`,
  `ConditionProperty` and `CodecKind` each bind in an altered case and by ordinal, where **each of
  those four** is a `400` today and a `200` on the reference
  `[probe: tools/probe_subtitle_negotiation.py, Jellyfin 10.11.11, 2026-08-30]`. **`SubtitleMethod`
  is the fifth and it is not one of them**: 011 T9 already binds it both ways through the private
  binder this task deletes, so its rows are a **regression** check and not a fix — every one of
  011's `Method` assertions has to answer what it answers today, through the general binder. A word
  no member has stays a `400` on all five; and — the row that proves the default clause is **not**
  general — an empty string stays a `400` on all five, because none of those five enumerations
  declares a default. That last row is a *reading* of the reference's converter factory until T1's
  sixth observation lands, and it is cited as one.
- **Spec reference:** §3.3, AC-8; plan §6.7, spec OQ-4

**This task makes no `400` into a `200` that the reference refuses, and the empty-string row is how
you know.** Generalising all four measured classes would answer `200` on five properties where the
reference answers `400`.

**Done, 2026-09-04** — the binder, the two registrations, the deletion, and **three things the
documents had incomplete rather than wrong**; one of them would have shipped the wrong member on a
correct request, and one is a decision this task does not take.

* **The ordinal is not a property of the enumeration this project declares, and two of the five
  vocabularies say so on the wire.** [Plan §6.7](plan.md#67-the-general-enum-binder)'s clause read
  *"the ordinal's member"*, which reads as `list(vocabulary).index(member)`; measured, `CodecType`
  declares `Video = 0, VideoAudio = 1, Audio = 2` — audio **last**, where `media/decision.py`
  declares it first — and `ProfileConditionValue` **skips 15**, so `NumStreams` is 25 where
  counting gives 24. A counted binder answers a codec profile typed `0` with `Audio`, leaves the
  video condition unapplied and **direct-plays a source the reference refuses direct play to**, on
  a request that carried nothing wrong. So the ordinals are a registration beside the default's —
  `@wire_ordinals({...})`, refused at import when it does not name every member — and
  `SUBTITLE_METHOD_ORDINALS` is now `ordinals_of(SubtitleMethod)`, one table for the body binder
  and the query reader. The test was run against the counted order to watch it fail
  `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-09-04]`.
* **The claim this task inherited was measured on one of the four and stated of all four**, and
  the ordinal half of it was stated of none: 011 T9 measured a *direct-play entry* typed `video`
  and the plan generalised it to `ProfileType`, `ConditionType`, `ConditionProperty` and
  `CodecKind`. All four are now measured one property at a time, every row read off
  `SupportsDirectPlay` because the answer echoes none of these values back — and a digit string
  binds in three forms, `1`, `+1` and ` 1 `, which is what the *query* reader already accepted and
  nothing had asked of a body. [Behaviours §2.28](../../docs/compatibility/behaviours.md) is the
  general rule, recorded where §2.24 recorded the protocol's.
* **A fifth class nobody asked about, and this server's answer to it is the one shape the defect
  procedure forbids.** An ordinal **no member has** is not one answer on the reference but three:
  the entry is ignored on `DlnaProfileType` and `CodecType`, the condition is *satisfied* on
  `ProfileConditionValue` (its switch's `default` returns true), and `ProfileConditionType` is a
  **`500`** in the middleware's 25 bytes, because an unexpected comparison throws
  `InvalidOperationException` past the `ArgumentException` mapping. Atrium answers `400` to all
  four, which [behaviours §3.0.2](../../docs/compatibility/behaviours.md#302-what-is-never-acceptable)
  names as *"a tidy `400`… worse than both"*. **It predates 012 and this task does not move it** —
  a field typed as an enumeration has refused a number since 008, and the binder keeps the number
  while the field refuses it — so it is recorded at
  [behaviours §3.26](../../docs/compatibility/behaviours.md) with both candidates and **left to its
  owner**: reproducing it is four more unions plus a rule about what an uninterpretable profile
  entry *does*, which is 008's ladder. A test names the boundary so it is not rediscovered as a
  surprise.
* **`SubtitleMethod`'s rows are a regression check and they earned it.** Running the suite with
  the binder disabled fails 011 T9's own
  `test_a_declared_method_binds_in_any_case_and_by_ordinal` alongside the three new ones, which is
  what says the deletion is covered by the general binder rather than by nothing.

**Two deviations from this task as written.** The empty-string and unbindable-word rows are
asserted on the **five enumerations** this body binds, the subtitle entry's `Method` among them —
but not on the delivery protocol, whose property is still a plain string until T9, so the `200`
its declared default answers is T9's control and not this task's. And the sweep in
`tests/conformance/test_aliases.py` gained a second question: every enumeration a model binds must
carry a declared ordinal table, so the next vocabulary somebody adds fails there rather than on a
client. The OpenAPI document was diffed either side of the change (001 T19's lesson: the framework
*inspects* what a model declares) — only docstrings moved, and the shapes that would have moved had
the binder been written per field are pinned in `tests/unit/test_server.py`.

## T8 — A nested refusal is keyed by its JSON path

- [x] **Changes:** `compat/errors.py:_body_error` builds the property's path from pydantic's
  `loc` — drop the leading `body`, map each level through its own model's alias, render a list
  index as `[n]`, join after a leading `$` — so a value inside a device profile is keyed
  `$.DeviceProfile.TranscodingProfiles[0].Protocol` as the reference keys it
  `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`. A failure **one level
  deep** keeps the key it has today, which is what 007 and 009 measured on the routes that have
  one. The message is whatever T1 recorded.
- **Depends on:** T1, T7 — and T1 **resized it**: the message is a second shape and not a
  constant. `Path:` carries the property's own path and `BytePositionInLine` is a byte offset into
  the raw body, reachable through the validation handler's `exc.body` and derivable from nothing
  the framework's error carries. The integer is **D-6**, reserved for its owner: reproduce it, or
  record one wrong number inside a message no client branches on.
- **Verified by:** `uv run pytest tests/unit/test_compat_errors.py tests/conformance/test_playlists.py
  tests/conformance/test_user_data_identity.py -q` — the nested key exactly, the one-level keys
  (`"$"`, the property's own name, `""`) unchanged byte for byte, and every measured body refusal
  007 and 009 asserted still passing.
- **Spec reference:** §3.4, AC-8; plan §6.6

**Done, 2026-09-04** — the path builder, the message beside it, and **three things the documents
had wrong rather than merely incomplete**; one of them meant the key this task exists for would
have appeared on no property at all, one answers D-6, and one is a trap set for T9.

* **The key was unreachable without a second registration, and building the path alone would have
  produced it nowhere.** `_body_error`'s vocabulary row needs the reference's own name for the
  enumeration, and a model that cannot supply one falls back to 007's `""` and
  `The supplied value is invalid.` — deliberately, so that no route invents a sentence.
  `CreatePlaylistDto` is the **only** model in the project that had ever declared
  `WIRE_ENUM_TYPES`, and every vocabulary this body carries lives on a *nested* one: five DTOs,
  six enumerated properties, five enumerations, none of them named. So the path builder would
  have shipped correct and unobservable. The five declare the map now, each name being the
  namespace its enumeration is already cited from `[source: MediaBrowser.Model/Dlna/ @ v10.11.11]`
  — and the reference's own spelling for the sixth,
  `Jellyfin.Data.Enums.MediaStreamProtocol`, is the one that was measured, which is what says the
  form is `namespace.TypeName` rather than a guess. A **sweep** over the body's whole model tree
  asserts it, in the shape T7 gave the same class of omission: a property that binds a vocabulary
  and names no type for its refusal fails there rather than on a client, and it is run red by
  removing one of the six. Scoped to this body rather than to every model in the project, because
  a *response* model's enumeration has no refusal to name and a rule demanding one would be
  demanding an unmeasurable string.
* **D-6's option (a) ships, and the source it named is the parsed document.** The decision says
  the offset comes from `exc.body`, *"which a validation handler holds"*. It holds the **parsed**
  JSON: the framework hands the exception what its own reader returned, so a position counted
  there would be a position in bytes nobody sent — different separators, different escapes, a
  different length. The document as sent is on the **request**, and the handler is given the same
  `Request` instance the route was called with, its body already read and cached, so asking for it
  costs nothing and touches no receive channel — measured, not assumed. It is asked for only when
  a failure is located in the body at all. So there is no divergence to record and no wrong
  integer: `398` for `"dash"` is the offset of the end of that token, and this server counts the
  same thing in the same units.
* **T9's own refusal is two keys where the reference sends one, and it is measurable today.** A
  `StreamProtocol | int` property that binds to neither member produces **two** framework errors —
  `enum` and `int_parsing` — each located one segment *deeper* than the property, at
  `(…, "protocol", "enum[StreamProtocol]")` and `(…, "protocol", "int")`. The path builder stops
  at the first segment no model declares, so the union tag never reaches a client and both errors
  are keyed by the measured path; but the second is not a vocabulary mismatch, so it falls to
  `""` and the answer names **two** keys where the reference's `errors` names exactly one
  `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`. Measured here while the
  key was being built, written into [plan §6.5](plan.md#65-the-protocol-in-four-classes), and left
  to the task that types the property — a T9 test asserting one key rather than the whole `errors`
  map would pass over it.

**Two deviations from this task as written.** The Verified-by line names three test files and the
change is four: the nested key is a property of the **negotiation's** body, and the only body in
this project with anything nested is that one, so `tests/conformance/test_playback_info.py` asserts
every one of the six enumerated properties at the HTTP boundary — the key, the type name and the
position — where `tests/unit/test_compat_errors.py` owns the mechanics. And the measured key names
`TranscodingProfiles[0].Protocol`, which is a plain string until T9: the unit file reproduces the
**measured** string on a body shaped like the reference's own, and the route asserts that same
list's `Type` at the same depth, so the exact measured key is pinned now rather than at T9.

**And two things nothing measures, said rather than left to be inferred.** `LineNumber` is `0` in
every measurement because every measured body was one line; a pretty-printed body is answered the
line the token ends on and the offset within it, which is the reader's own arithmetic and is the
only reading under which the measured numbers are what they are. And the path is built from the
model's **aliases**, per level ([plan §6.6](plan.md#66-the-refusals-key-is-a-json-path)), so a
client that spells a property in another case — which this binder accepts and the reference accepts
— is answered the reference's spelling of it rather than its own. Nothing measured that body; the
offset it carries is still the right one, because the reader that finds the token matches keys the
way the binder does.

## T9 — The delivery protocol is an enumeration, in every sense

- [x] **Changes:** `media/decision.py` gains `StreamProtocol` (`http`, `hls` — lower-case by
  declaration) and its ordinal table, beside `SubtitleMethod`'s and for the same reason: both
  binders read it. **T7 made both of those a registration**: `@wire_ordinals({0: "http", 1: "hls"})`
  and `@wire_default("http")` on the class, with
  `STREAM_PROTOCOL_ORDINALS = ordinals_of(StreamProtocol)` if anything outside the binder needs the
  table — and `wire_default` has no other user, so this is where its own test stops being a
  synthetic one. `TranscodingProfile.protocol` takes `StreamProtocol | int`,
  `TranscodingProfileDto.protocol` with it, and `Decision.sub_protocol` and
  `MediaSourceInfo.TranscodingSubProtocol` become `str | int` so the out-of-range ordinal survives
  to the wire as a number — and `api/media_info.py:_annotate`'s
  `decided.sub_protocol or wire.transcoding_sub_protocol` becomes an `is not None` test in the same
  edit, because a truthiness fallback on a field that can now hold an integer is one ordinal away
  from answering `"http"` to a client that asked for `0` — which [behaviours §2.24](../../docs/compatibility/behaviours.md) has
  already decided this server reproduces. `media/urls.py`'s `HLS = "hls"` becomes
  `StreamProtocol.HLS.value`, so the string a comparison is made against and the string an answer
  echoes cannot come apart.
- **Depends on:** T7, T8
- **Verified by:** `uv run pytest tests/conformance/test_playback_info.py tests/unit/test_media_decision.py -q`
  — the eighteen spellings of [spec §3.3](spec.md#33-a-delivery-protocol-the-negotiation-does-not-recognise)
  in their four classes: `hls`/`Hls`/`HLS`/`hLs` all answer an HLS address with
  `TranscodingSubProtocol: "hls"` (AC-7 — the **enumeration's** spelling, never the profile's);
  absent, `null` and `""` take the default; `0`/`"0"`/`1`/`"1"` bind by ordinal; `2`/`"2"` answers a
  progressive address beside the number `2`; `dash`, `" "` and `true` are `400` keyed on T8's path
  (AC-8). And AC-9: the whole 008 and 011 suite green, because nothing in the ladder moved.
- **Spec reference:** §3.3, AC-7, AC-8, AC-9; plan §6.5

**Done, 2026-09-04** — the enumeration, the union, the four classes and T8's two keys made one.
**The first task in this feature that found nothing wrong in the spec**, and three things wrong in
the code the union creates — one of them a `200` where the reference sends a `400`, on the exact
value both documents had already measured.

* **The union re-opens the boolean trap the binder was written to leave open on purpose.** T7's
  binder passes a `bool` through untouched *so that the field refuses it*: `true` is a measured
  `400` and the ordinal `1` a measured member, and `isinstance(True, int)` is Python's trap and
  not the reference's. A property annotated `StreamProtocol | int` **stops refusing it** — the
  union's `int` member takes `True` in the framework's lax mode and binds it to the raw ordinal
  `1` — so the request behaviours §2.24 records as a refusal would have been answered `200` with
  an HLS address. Measured by writing the row and watching it come back `200`; the `int` half is
  `StrictInt`, which costs nothing else because the binder has already turned a string of digits
  into an `int` before the annotation sees it. **The trap survived two documents naming the value
  and a task list naming the union**, which is what says it belongs to the shape rather than to
  anyone's inattention.
* **T8's second key is closed by a rule about properties, not about this union.** The framework
  reports one failure per union *member* — `enum` and `int_parsing`, each one segment deeper than
  the property — and the second is no vocabulary mismatch, so it filed itself under 007's `""` and
  answered two entries where every measurement of this route has one. `compat/errors.py` now
  groups a body's failures by the path they resolve to and reports one, keeping the vocabulary
  mismatch: written that way rather than as *"drop a trailing union tag"* because the tag is a
  spelling of the framework's and *"one entry per property"* is what the reference does. Run red
  by reporting every error, which fails all three refusal rows. **T8's warning was the reason it
  was found rather than shipped**: a test asserting `errors[key]` passes over an extra key, and
  these assert the whole map.
* **The truthiness fallback is a real trap and an unreachable one, and no test can tell the two
  spellings apart.** `decided.sub_protocol or wire.transcoding_sub_protocol` is `is not None` now,
  as the gate asked. But the only falsy integer is `0`, and `0` is a *declared* ordinal binding to
  `StreamProtocol.HTTP`, so the value that would take the `or` branch cannot be produced —
  `wire_protocol` answers a member's word or a number no member has, and `2` is truthy. The `0`
  row is in the suite as the row that *would* catch it, and it passes either way. Said plainly
  rather than dressed up as a caught bug: what makes the line worth changing is the next
  vocabulary that declares a member at an ordinal this one does not.

**Two things confirmed rather than found.** `wire_default` has a production reader at last, and it
answers what T1 measured: absent, `null` and `""` all take `http` on the one enumeration that
declares a default, against the same empty string being a `400` on the five beside it. And the
generated OpenAPI document survived the project's first union in a request model — `anyOf` with the
enumeration's default kept, pinned in `tests/unit/test_server.py` beside T7's (001 T19's lesson).
**Nothing in `docs/compatibility/behaviours.md` moves**: §2.24 already records all eighteen
spellings and says this server reproduces them, and every answer here is a reproduction rather than
a divergence. `surface.yaml` is untouched — 012 adds no route.

## T10 — The two L3 rows get their cases, and the two comparisons a sweep cannot raise

- [ ] **Changes:** [`docs/compatibility/request-cases.yaml`](../../docs/compatibility/request-cases.yaml)
  gains four cases under `POST /Items/{itemId}/PlaybackInfo` — `protocol-in-an-unexpected-case`,
  `protocol-that-binds-to-nothing`, `protocol-by-ordinal` and `a-source-the-world-never-opened` —
  each naming both identities, because twelve of twenty-three reads of this surface answer
  differently to a restricted non-administrator.
  [`named-comparisons.yaml`](../../docs/compatibility/named-comparisons.yaml) gains
  `uninspectable-source-address` (the reference's address names `live.m3u8` and answers `500` where
  v1's names `master.m3u8` — [behaviours §3.13](../../docs/compatibility/behaviours.md)) and
  `on-demand-probe-heals-the-listing`, whose subject is *two requests and their order* and which
  the engine, comparing one response at a time, cannot raise.
- **Depends on:** T9
- **Verified by:** `uv run pytest tests/unit/test_allowlist.py tests/conformance/test_differential.py -q`
  — the registers parse, every case names an endpoint in `surface.yaml` and an anchor that
  resolves, and each named comparison carries its reason and its owner. Then
  the command [conformance.md §L3](../../docs/compatibility/conformance.md) publishes —
  `python3 tools/differential.py --atrium … --jellyfin … --surface docs/compatibility/surface.yaml
  --report reference/differential-report.md --fixture`, the last flag being what asks for the half
  that needs a single-use reference instance over this repository's own fixture: the two L3 rows
  are compared for both identities, and any difference is declared or the run is not clean.
- **Spec reference:** §6 (conformance); plan §8

## T11 — The acceptance map, the levels, and three status lines

- [ ] **Changes:** `tests/conformance/test_acceptance.py` gains `FEATURE_012` — every criterion of
  [spec §5](spec.md#5-acceptance-criteria) on one line with the test that proves it — and `spec.md`,
  `plan.md` and this file are marked `Implemented` with the status table moving in the same change.
  **`IMPLEMENTED_FEATURES` does not gain `"012"`**, and the gate checked why rather than copying
  the previous nine features' closing task: that set is read by `surface_paths()`, which filters
  `surface.yaml` by `feature`, and 012 owns no row there — adding it would change nothing. The
  acceptance map's own guard reads the **status table** in `specs/README.md` and not that set.
  [Behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s
  never-opened-source row is **struck** — the gap closes — and §2.23's and §2.24's *"Atrium does"*
  halves stop being promises.
- **Depends on:** T1–T10
- **Verified by:** `uv run pytest tests/ -q` whole and green, and `uv run pytest
  tests/conformance/test_acceptance.py -q` in particular: the map's guard reads the criteria out of
  `spec.md` itself, so a criterion this list forgot fails here rather than passing silently — and
  the row that flips this feature to `Implemented` in `specs/README.md` is what makes that guard
  demand a map at all.
- **Spec reference:** §5, §6; plan §8

**This is the task that has found something in every feature since 008, and it is always the same
class: a criterion mapped to a test that proves less than its name.** 008 T14 found two whose tests
contradicted them, 009 T14 a criterion with no test at all, 011 T12 a plan-stated contract obeyed
nowhere, 010 T15 a criterion its own measurement contradicted. **Two here are already known to be
at risk**: AC-5, whose test asserts nothing unless it is asked against a source the profile can
direct-play (T5), and AC-4, which is about the negotiation answering *with* an address and not
about the address answering — a test that follows the address would be asserting
[behaviours §3.13](../../docs/compatibility/behaviours.md)'s reference defect.

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) has a passing
      test, named in `FEATURE_012`.
- [ ] Both `POST`/`GET /Items/{itemId}/PlaybackInfo` rows reach the **L3** declared in
      [`spec.md` §6](spec.md#6-conformance), and the three L2 rows their level.
- [ ] [`surface.yaml`](../../docs/compatibility/surface.yaml) is **unchanged**: no route enters or
      leaves v1 here, and the exact-set check has been green throughout.
- [ ] Anything learned during implementation is back in `spec.md` and `plan.md`, in the same
      change as the code.
- [ ] Every reading [plan §6.8](plan.md#68-what-this-plan-read-and-did-not-measure) records as
      *read* is either measured and cited, or restated as still owed with its owner.
- [ ] [Behaviours §5](../../docs/compatibility/behaviours.md#5-accepted-gaps-in-v1)'s
      never-opened-source row is gone, and §2.23 and §2.24 describe what this server does rather
      than what it will do.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.
