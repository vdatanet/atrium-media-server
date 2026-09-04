---
feature: 012-negotiation-inputs
title: Negotiation inputs — tasks
status: Accepted
created: 2026-09-03
updated: 2026-09-03
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

- [ ] **Changes:** `tools/probe_uninspected_source.py` gains a two-part film in its fixture (one
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

**Two of the five can move a decision, and this task is where that is allowed to happen.** If the
reference leaves `item_sources`' own change signal alone, D-1's write is an *improvement* rather
than parity and goes back to its owner for a
[behaviours §6](../../docs/compatibility/behaviours.md) argument before T4 writes it. If a refresh
does **not** reach a second part, §6.1's *"open every part whose stored inspection is absent"* is
one part too many and T3's rule narrows to source zero. Neither is a defect in this list; both are
the reason the list starts here.

## T2 — The world gets files nothing can open

- [ ] **Changes:** `tests/fixtures/media.py` gains a declaration kind it has not got: an entry
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
- **Depends on:** T1 (which decides whether the two-part entry is a negative case or a positive
  one)
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

## T3 — `library/inspection.py`: the trigger, and the inspection that is never stored

- [ ] **Changes:** a new module with the four functions
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
  does **not**. Plus: `unopened()`'s result put through `media/info.py:source_of` answers byte for
  byte what a `None` inspection answers today, which is what keeps AC-10 true.
- **Spec reference:** §3.2, AC-1; plan §5, §6.1

**`opened` swallows both inspection failures on purpose.** `ProberUnavailableError` and
`UnreadableMediaError` mean opposite things to a scan and the same thing to one request, and
`library/scan.py` keeps the distinction where it decides something (003 §3.7).

## T4 — The write: an inspection and a change signal, from a request

- [ ] **Changes:** `library/inspection.py:store` writes the inspection through
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

## T5 — The negotiation resolves before it reads the profile

- [ ] **Changes:** `api/media_info.py`'s `_negotiation` becomes `async`, and before the source
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

## T6 — The audio refusal, which is the platform's and not this feature's

- [ ] **Changes:** `compat/errors.py` gains `NegotiationRefusedError` and its row in
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

## T7 — One binder for every vocabulary a body carries

- [ ] **Changes:** `compat/model.py` gains a validator beside `_accept_any_casing`, per field whose
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

## T8 — A nested refusal is keyed by its JSON path

- [ ] **Changes:** `compat/errors.py:_body_error` builds the property's path from pydantic's
  `loc` — drop the leading `body`, map each level through its own model's alias, render a list
  index as `[n]`, join after a leading `$` — so a value inside a device profile is keyed
  `$.DeviceProfile.TranscodingProfiles[0].Protocol` as the reference keys it
  `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-29]`. A failure **one level
  deep** keeps the key it has today, which is what 007 and 009 measured on the routes that have
  one. The message is whatever T1 recorded.
- **Depends on:** T1, T7
- **Verified by:** `uv run pytest tests/unit/test_compat_errors.py tests/conformance/test_playlists.py
  tests/conformance/test_user_data_identity.py -q` — the nested key exactly, the one-level keys
  (`"$"`, the property's own name, `""`) unchanged byte for byte, and every measured body refusal
  007 and 009 asserted still passing.
- **Spec reference:** §3.4, AC-8; plan §6.6

## T9 — The delivery protocol is an enumeration, in every sense

- [ ] **Changes:** `media/decision.py` gains `StreamProtocol` (`http`, `hls` — lower-case by
  declaration) and its ordinal table, beside `SubtitleMethod`'s and for the same reason: both
  binders read it. `TranscodingProfile.protocol` takes `StreamProtocol | int`,
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
