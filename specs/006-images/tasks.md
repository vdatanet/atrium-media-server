---
feature: 006-images
title: Images — tasks
status: Accepted
created: 2026-08-28
updated: 2026-08-28
accepted: 2026-08-28
amended: 2026-08-28 at the gate — T2's fixture note, T9's indexed-form tests and corrected test names; see "What the gate changed"
plan_status_required: Accepted
plan_status_actual: Accepted
---

# 006 — Tasks

Ordered. Each is a reviewable change on its own and states how you know it worked.

**The ordering carries three structural decisions.** The measurement debt is paid before any
transform code freezes: T1 gives the committed probe the two cells the plan gate answered with
scratch scripts, so the provenance that corrected AC-6 and added AC-15 is reproducible before the
code that leans on it exists. Bytes never meet HTTP until T9: the repository lookup, the three
source readings, the pure transform, the cache and the service are each green under unit tests
first ([plan §3](plan.md#3-modules)'s boundary — `images/` owns bytes and knows nothing about
HTTP), so the two routes land as parsing and headers over a proven core rather than as the place
the logic lives. And the wire's one novel refusal — the fourth error shape — lands in `compat/`
at T3, before any route can need it, for the same reason 005 put its framework fights at T4: a
shape settled once is a shape seventeen future routes cannot each get subtly wrong.

**The discovery half completes before the delivery half begins.** A client discovers an image in
005's responses and only then fetches it, and the task order says the same: T2 closes the one gap
the spec review ordered into §3.1 — `ParentBackdropItemId` paired with the tags 005 already
emits — before the first byte-serving module exists. It is the only task that touches 005's
surface, and doing it first keeps the golden churn in one reviewable place.

**Routes land in one task, and the exact-set check has the standing device for that.**
`test_no_route_ships_ahead_of_its_feature` asserts the served routes equal the surface of the
implemented features, so T9 carries the two 006 routes in that test's interim list — the device
002 and 005 both used, recorded in its docstring — and T13 deletes the list by putting `"006"`
in `IMPLEMENTED_FEATURES`.

**What 004 and 005 wrote down for this feature is the starting inventory, not work.** Complete
`item_images` rows — `width`, `height` and a content-derived `tag`, never null — with the three
`source_kind` readings defined (004 plan §4); `ImageTags`, `BackdropImageTags` and the parent
tags already computed from those rows alone, pinned by 005's sixteen goldens
([005's tasks](../005-item-query-api/tasks.md#what-this-feature-owes-the-next-ones)); the
first-root-that-exists reading in `metadata/refresh.py`; and the parameter canonicalisation,
`api_key` seeding and ignored-parameter recorder of 005 §6.12, which give this feature its OQ-4
trail without a line of image code. In each case the lean is a test.

## What the gate changed

This list was reviewed against [`spec.md`](spec.md), [`plan.md`](plan.md) and the files it
references on 2026-08-28 before being accepted. Four things changed — two of them the exact
classes earlier gates taught, back for the very next feature:

| The draft said | It was |
|---|---|
| Index errors in T10, index goldens in T9 | **[Spec §6](spec.md#6-conformance)'s "Indexed form" conformance row had no task holding its positive case.** Every index test in the draft was an error test — out of range, absent — and nothing asserted that `/Backdrop/1` returns backdrop 1. T9 now holds it, for the path form and the query spelling both, assertible by the three differing sizes T4 draws |
| AC-14's test runs over the seeded 005 world | **The world cannot express AC-14's precondition.** `tests/fixtures/query.py` seeds images on the first film and the first series only — no episode carries artwork of its own, because 005 never needed one — so "inheritance does not gate on the child's own images" had no discriminating fixture anywhere. T2 now extends the world and its invariant test. The 005 gate's fixture lesson, one feature later |
| "the existing all-routes canonicalisation test picks the new routes up with PascalCase spellings of every parameter" | **No such test exists in that shape.** The two standing all-routes tests are the table-coverage walk and the `api_key` seeding check; the PascalCase mangling was always per-route (005 §8). T9 now names the two real tests and carries the one-route mangling battery itself — found by opening `tests/unit/test_compat_query_params.py`, not by re-reading the list |
| AC-12 parameterises "over 002 §3.1's mechanism list itself" | **Executable only once the list has a name.** The enumeration exists — `mechanisms()` in `tests/conformance/test_auth_mechanisms.py` — and T9 now points at it, so "not a copy" is an import, not an aspiration |

## Legend

`[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked (say by what)

---

## T1 — The probe pays its debt: the two blind cells

- [x] **Changes:** `tools/probe_image_formats.py` grows the two cells the plan gate measured
  with scratch scripts ([plan §6.8](plan.md#68-measured-at-the-gate-and-what-stays-owed)):
  a **non-square fill battery** — the probe finds a poster whose width and height differ, asks
  for a fill box off the source's ratio, one past the source's size, and one beside a `maxWidth`,
  and reads the delivered dimensions against the cover-and-keep-overflow rule of
  [spec §3.3](spec.md#33-resizing) — and an **`Accept` negotiation battery**: the `image/webp`
  offer on a transformed request, on a verbatim request, and against an explicit `format`, plus
  `image/avif`. `width`+`height` together joins the battery. The probe's conclusions judge the
  amended spec (AC-6, AC-15), and where it now covers a claim cited as
  `[probe: manual requests via tools/_probe.py, …]`, the citation in `spec.md` and `plan.md`
  upgrades to the script in this same change. The script's row in
  [`tools/README.md`](../../tools/README.md) names the new cells.
- **Depends on:** nothing
- **Verified by:** run by hand against the live reference: every battery reports
  `matches_documentation=True` against the amended spec, and the output is recorded with version
  and date; a library with only square posters is reported as unexercised, not guessed; the
  tools CI job holds the script to the 3.9 floor like its siblings. No test opens a connection —
  the suite's TCP guard stands.
- **Note:** what the probe still cannot see, it must say: EXIF orientation needs a planted file
  in a controlled library and stays owed to 010's differential
  ([plan §6.8](plan.md#68-measured-at-the-gate-and-what-stays-owed) row 1).
- **Plan reference:** §6.8; spec §3.3, AC-6, AC-15
- **Done (2026-08-28):** both owed cells confirmed the amended documents — a 500×1500 fill box
  of a 2000×3000 poster came back **1000×1500**, which is neither the box (a crop) nor the fit
  (500×750); the composed `fillWidth=500&fillHeight=1500&maxWidth=500` came back 500×750; and a
  resized request offering `image/webp` came back WebP under `Vary: Accept` while the verbatim
  one came back JPEG, an explicit `format=Png` beat the offer, and `image/avif` was not
  negotiated. AC-6 and AC-15 are reproducible from a committed script, and the two spec citations
  that named the gate's scratch requests now name it. §3.3's fill claim, §3.3's negotiation
  claim, and §6.8 row 3 are discharged.

  **A third battery came out of writing them, and it was not owed by anybody.** Comparing the
  delivered payload to the source's *bytes* rather than to a byte **count** — which nobody had
  done, although the two numbers had been printed four lines apart since the OQ-5 measurement:
  `source, no parameters → 200 … 800x800 … 84351B` and `maxWidth=-100 → 200 … 800x800 …
  282225B`. Same status, same dimensions, same format, three times the bytes. **A forgiven
  parameter is not a dropped one**: `maxWidth=-100`, `maxWidth=0` and `fillWidth=-5` each put the
  request on the reference's encoder at its own default quality. And the other half of it went
  against the plan: **`quality=90` with nothing resized is byte-identical to the file**, where
  plan §6.3 step 5 made a bare `quality` a reason to transform — so Atrium would have re-encoded
  every poster for the clients that append one out of habit, on a route whose whole cache story
  is byte-identity. Step 5's clause is deleted, step 1 records the divergence, and
  [behaviours §1.17](../../docs/compatibility/behaviours.md#117-a-forgiven-dimension-re-encodes-a-bare-quality-does-not)
  carries the argument: matching the re-encode is not an option, because two encoders never agree
  on bytes — Atrium can only spend CPU to deliver a *different* wrong `Content-Length`.

  **And one thing that was simply stale.** [spec §3.2](spec.md#32-get-itemsitemidimagesimagetype--getitemimage)'s
  parameter table still read "Fill the box, cropping the overflow" — three amendments after §3.3
  stopped saying it and AC-6 was corrected. The gate had fixed the prose and left the table.

  Not measurable from here, unchanged: EXIF orientation (§6.8 row 1, owed to 010) and a disabled
  account's token (§6.8 row 2, on 002's list). The probe reports the fill battery **unexercised**
  rather than answered on a library whose posters are all square — the exact sample that produced
  the wrong answer the first time.

## T2 — `ParentBackdropItemId`, and inheritance unconditional

- [x] **Changes:** `api/item_dto.py` — the registry gains `ParentBackdropItemId` beside
  `ParentBackdropImageTags`, same per-type set, emitted from the same nearest-ancestor walk, so
  the id and the tags can never come from different items
  ([spec §3.1](spec.md#31-how-a-client-discovers-an-image); the gap 005 left deliberately and
  the spec review moved here). The 005 goldens that change are regenerated in this change —
  and only the rows [005's measurement](../005-item-query-api/notes/item-shapes.md) shows
  carrying the field may change, which is the review check.
- **Depends on:** nothing
- **Verified by:** a pairing test over the seeded 005 world: on every row of every list response,
  `ParentBackdropItemId` is present exactly when `ParentBackdropImageTags` is, and names the
  ancestor whose rows produced the tags; AC-14's test — an episode **with artwork of its own**
  under a series with poster and backdrops carries `SeriesPrimaryImageTag` + `SeriesId` and the
  paired backdrop fields, proving inheritance does not gate on the child's own images; AC-1
  reasserted by name for the map (`ImageTags.Primary` present with a poster, `{}` without —
  both halves the world already seeds); `ParentLogoImageTag`/`ParentLogoItemId` asserted
  **absent** — the pair stays out by Principle VI, and the test is what keeps a later reader
  from "completing" it.
- **Note (added at the gate):** `tests/fixtures/query.py` seeds images on the first film and the
  first series only — **no episode carries artwork of its own**, because 005 never needed one.
  AC-14's precondition does not exist in any fixture, so this task extends the world with an
  episode holding its own `Primary` under the imaged series, and the invariant test that pins
  the world's shape grows the same line. The 005 gate's fixture lesson, back for the very next
  feature: a criterion's discriminating case is seeded by the task that needs it, not assumed
  of a world built for someone else.
- **Plan reference:** §1 (the DTO reconciliation); spec §3.1, AC-1, AC-14
- **Done (2026-08-28):** measured first, and the measurement settled three things the list
  asserted. The pairing is exact — of 200 sampled episodes, **197 carried both fields and not one
  carried either alone**; fetching each named owner and comparing its own `BackdropImageTags` to
  the tags on the inheriting row agreed **12 of 12**. And AC-14's premise turned out to be the
  reference's ordinary case rather than an edge: **all 200 sampled episodes carried a `Primary`
  of their own**, every one of them still carrying `SeriesPrimaryImageTag` and `SeriesId`. What
  005's world could not express is what the reference does on every row it has.
  `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`

  **The obvious placement was the wrong one.** `item_models.py` declares fields in the pinned
  document's order, on purpose, and the natural guess — the id after the tags it pairs with —
  is not what the document says: it orders `GenreItems`, `ParentLogoItemId`,
  **`ParentBackdropItemId`, `ParentBackdropImageTags`**, `LocalTrailerCount`. The id goes
  *before*. Getting it wrong would have moved a key on every `Season` and `Episode` row and
  passed every test in this task, because pydantic serialises in declaration order and nothing
  here compares against the reference's bytes.

  **A track proved the walk is nearest-first, and an episode could not.** On the reference a
  track's `ParentBackdropItemId` is its **`MusicArtist`**, not its album — the album carries no
  backdrops and the artist does, on every sampled track. No sampled season had backdrops of its
  own, so an episode's owner was its series every time, which nearest-first and topmost-always
  both produce. `_backdrop_owner` says so in its docstring rather than claiming the distinction
  was measured where it was not.

  **The row this task adds belongs to an *Implemented* feature's specification.** The property is
  005's surface, `tests/unit/test_item_dto.py`'s per-type table mirrors 005 §3.2 rather than 006's
  spec, and the change is incomplete until that matrix says `ParentBackdropItemId` too — so
  [005's spec](../005-item-query-api/spec.md) is amended in this change and carries its own
  `amended:` line. A task that only touched 006's documents would have left a shipped feature's
  specification describing a narrower wire than the server sends.

  The gate's fixture prediction held exactly: no episode in the seeded world carried artwork of
  its own, so AC-14's precondition had to be built before it could be asserted. Four goldens
  changed and only four — `Season` and `Episode`, row and full body — which is the review check
  the task named: `MusicAlbum` and `Audio` are in the per-type set and their ancestors have no
  backdrops in this world, so the field is correctly absent there.

## T3 — The fourth error shape, in `compat/`

- [ ] **Changes:** `compat/errors.py` grows the message-string refusal of
  [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one):
  a raisable refusal that serialises as the **JSON-encoded bare string** —
  `"<item name> does not have an image of type <Type>"` — `404`,
  `application/json; charset=utf-8`, alongside the problem-details `404` that already exists.
  The two exceptions of [plan §5](plan.md#5-contracts) — `ItemNotFound` mapping to problem
  details, `ImageNotFound(item_name, image_type)` mapping to the string — defined where the
  shapes live, importable by the service before any route exists.
- **Depends on:** nothing
- **Verified by:** byte-level tests pin both shapes, the split included: one route raising each
  exception under a test app answers the measured bytes — the string's quoting exact, the
  content type exact; a non-ASCII item name serialises under the standing
  [behaviours §4.4](../../docs/compatibility/behaviours.md#44-non-ascii-characters-are-sent-as-themselves-not-as-uxxxx)
  exception, asserted so nobody re-fights it per route.
- **Note:** the shape carries the item's display name onto a tokenless route — the
  id-as-capability consequence, recorded in behaviours §1.11 and §2.10. The test names it so the
  disclosure is a decision with provenance, not an accident.
- **Plan reference:** §5, §7; behaviours §1.11

## T4 — The drawn fixtures and the seeded image world

- [ ] **Changes:** `tests/fixtures/images.py` — the [plan §8](plan.md#8-testing-strategy)
  fixture: Pillow draws deterministic images at test time — the 1000×1500 JPEG poster whose 2:3
  ratio discriminates cover from fit and exact from aspect-true, the 400px-wide source for the
  no-upscale case, a PNG logo with an alpha channel, three backdrops of three different sizes so
  index selection is assertible by dimensions — and a builder that places them under `tmp_path`
  library roots and seeds the rows **through the repositories**: `file` rows against a two-root
  library, an `embedded` row whose carrier is a real FLAC/MP3 built the way
  `tests/metadata/test_tags.py` already builds them, and a `remote` row whose file sits under
  the data directory's `metadata/artwork/`. No users: this route has none, and a fixture that
  seeded one would invite a visibility branch the spec forbids.
- **Depends on:** nothing
- **Verified by:** an invariant test on the world: the dimensions and tags stored equal what
  `metadata/artwork.describe` reports for the drawn bytes (the tag *is* the content hash —
  AC-2's serve-side half), all three source kinds present, the two-root split real; the builder
  is deterministic — fixed identifiers, fixed bytes — and the suite stays green with no
  consumer yet.
- **Plan reference:** §8

## T5 — `ImageRepository` and `images/source.py`: from item id to carrier bytes

- [ ] **Changes:** `db/repositories.py` grows `ImageRepository` — the one
  [plan §6.1](plan.md#61-the-lookup) query: the item (exists, not soft-removed, its
  `library_id`), the `(image_type, index)` row, the library's roots, and the part-zero source
  path for an `embedded` row, returned as a typed record. `images/source.py` — the three
  `source_kind` readings of [plan §6.2](plan.md#62-resolving-bytes--the-three-readings):
  `file` against the first root under which the relative path exists, `embedded` through
  `metadata/tags`' reader, `remote` against the data directory; the containment check before
  every open; the carrier's mtime read for §6.6's clock.
- **Depends on:** T4
- **Verified by:** unit tests over the seeded world: each kind resolves to the drawn bytes; the
  two-root library resolves through the root that has the file; a crafted row with `../` in its
  path is **refused**, not resolved — the hostile-row test [plan §9](plan.md#9-risks) promises;
  a vanished carrier and an embedded row whose art was stripped each raise `ImageNotFound`, and
  an unknown, removed or row-less item raises its typed refusal per
  [plan §7](plan.md#7-failure-handling); no reader is added anywhere else — route modules will
  own no SQL, and the repository is the only reader, as everywhere.
- **Plan reference:** §5, §6.1, §6.2, §7

## T6 — `images/transform.py`: the decision and the formats, pure

- [ ] **Changes:** the [plan §6.3](plan.md#63-the-transform-decision) decision and
  [§6.4](plan.md#64-format-selection) format resolution as one pure module: drop non-positive
  values; fill **covers** with the overflow kept, clamped at 1, the source verbatim past the
  clamp; `width`/`height` exact per axis, both at once distorting; `max` fits; the
  no-effective-change answer is the **verbatim signal**, `format=Svg` included; explicit
  `Jpg`/`Png`/`Webp` encoded as asked, `Jpg` flattening alpha onto white; `Bmp`/`Gif` falling
  back to the source format mid-transform with a **recorded-drop signal**, unknown tokens
  (`Banana`) likewise; the `image/webp` offer as an input deciding the resolved format when no
  explicit `format` is given; `quality` clamped to 0–100, encoder-mapped for `Jpg`/`Webp`,
  ignored for `Png`; palette and CMYK converting minimally; a decode failure — the
  decompression-bomb guard included — answering the **source-bytes signal** of plan §7, never
  an exception the route sees.
- **Depends on:** T4 (the drawn bytes)
- **Verified by:** the table-driven matrix of [spec §6](spec.md#6-conformance): every cell of
  §3.3 as measured — 300×300 fill of the 1000×1500 poster → 300×450; a box past the source →
  verbatim; `width=300&height=300` → the distorted exact box; 2000px of the 400px source →
  verbatim; alpha surviving every implicit path and dying under explicit `Jpg`; the resolved
  format per (source, `format`, offer) triple — with the provenance cited beside the cells it
  reproduces; mypy strict; the module imports neither HTTP nor the database.
- **Plan reference:** §6.3, §6.4; spec §3.3, AC-4–7 (unit half)

## T7 — `images/cache.py`: the disposable store

- [ ] **Changes:** the [plan §4](plan.md#4-data-model) layout —
  `<data-dir>/cache/images/<k[:2]>/<k>.<ext>`, the key a hash over item, type, index, tag and
  the canonical transform tuple **with the resolved output format inside** so a negotiated WebP
  and a bare JPEG are two entries; reads recover the `Content-Type` from the extension; writes
  are tmp-file-plus-atomic-rename; an unwritable cache computes and serves anyway, warning
  once per process.
- **Depends on:** T6 (the transform tuple it keys on)
- **Verified by:** unit tests: hit returns the written bytes with the right type; two concurrent
  writes of one key converge on one intact entry; a read-only cache directory degrades to
  compute-and-serve with exactly one warning; the key changes when tag, geometry or resolved
  format change and only then; deleting the tree between operations loses nothing but time
  (AC-13's unit half).
- **Plan reference:** §4, §6.5, §7

## T8 — `images/service.py`: the orchestration

- [ ] **Changes:** [plan §5](plan.md#5-contracts)'s one entry point: `ImageQuery` in, `ImageReply`
  out — lookup (T5), transform decision (T6), verbatim or cache-through (T7), the carrier's
  mtime as `last_modified`, the two typed refusals mapped and nothing else raised. The verbatim
  path serves the carrier's bytes exactly; the transformed path is cached by resolved key.
- **Depends on:** T5, T6, T7
- **Verified by:** service-level tests over the seeded world: the same query twice is
  byte-identical whether the second hit the cache or the tree was deleted between (the §5
  invariants); an embedded Primary re-extracts per verbatim request and its transformed variant
  caches like any other; never-upscale end to end; a transform-time decode failure serves the
  source bytes with a warning, not a `5xx`; the refusal split of plan §7 — unknown item versus
  image-absent family — verified by exception type.
- **Plan reference:** §5, §6.5, §7

## T9 — The two routes, the header contract, and the conditional pair

- [ ] **Changes:** `api/images.py` — `GET /Items/{itemId}/Images/{imageType}` and its indexed
  form, declared with the pinned spellings (`maxWidth`, `maxHeight`, `width`, `height`,
  `fillWidth`, `fillHeight`, `quality`, `format`, `tag`, and the query `imageIndex` on the
  unindexed route), **no authentication dependency at all**, plain `Response` objects carrying
  [plan §6.6](plan.md#66-headers-and-conditional-requests)'s explicit set — `Content-Type`,
  `Content-Length`, `Last-Modified`, `Cache-Control` by `tag` presence, `Vary: Accept`,
  `Content-Disposition: attachment`, the two DLNA constants — and the `If-Modified-Since`
  handling: lenient parse, whole-second compare, `304` empty with the `200`'s set minus
  `Content-Length`, decided before any bytes are read. The five decoration parameters stay
  undeclared on purpose. `test_no_route_ships_ahead_of_its_feature`'s interim list gains the two
  routes. Golden headers for the four shapes: bare `200`, tagged `200`, `304`, and the `404`
  pair.
- **Depends on:** T3, T8
- **Verified by:** the **header-set sweep** — the canonical request battery of
  [plan §8](plan.md#8-testing-strategy), asserting set-equality per response, `ETag` and
  `Accept-Ranges` absent by name; AC-3 (bytes, real `Content-Type`, exact `Content-Length`);
  **the indexed form and the query spelling each select the backdrop they name** —
  `/Backdrop/1` and `/Backdrop?imageIndex=1` return the same second backdrop, assertible by the
  three differing sizes T4 draws *(added at the gate: spec §6's "Indexed form" conformance row
  had no task holding its positive case — every index test in the draft was an error test)*;
  AC-9 (`304` at the sent `Last-Modified`); AC-10 (a stale `tag` answers `200` with the current
  bytes — the `tag` never reaches selection); AC-12 parameterised **over 002 §3.1's mechanism
  list itself** — the `mechanisms()` enumeration
  `tests/conformance/test_auth_mechanisms.py` already exports, not a copy — no token, every
  mechanism, an unknown and a malformed token — identical bytes each time, which is the "every"
  005's gate taught lists to actually hold; the recorder holds `(route, percentPlayed)` after a
  decorated request answers `200` unfiltered — OQ-4's trail exists; the two standing all-routes
  tests pick the new routes up by construction —
  `test_the_table_covers_every_route_of_the_real_application` and
  `test_every_route_accepts_the_authentication_parameters` *(corrected at the gate: the draft
  cited an all-routes PascalCase test that does not exist in that shape)* — and the `PascalCase`
  mangling battery lands here per 005 §8's pattern: one image route called with every declared
  parameter's spelling mangled; `X-Response-Time-ms` present via the standing sweep.
- **Note:** the routes own parsing and headers only — any logic found here in review belongs in
  `images/` (plan §3's boundary, the review check).
- **Plan reference:** §6.1, §6.6, §6.7; spec §3.2, §3.4, AC-3, AC-9, AC-10, AC-12

## T10 — The error matrix on the wire

- [ ] **Changes:** the route-level error handling that closes
  [spec §3.2](spec.md#32-get-itemsitemidimagesimagetype--getitemimage)'s table:
  `imageType` parsed case-insensitively against the full thirteen-member vocabulary — a
  non-member string is the validation `400`, a member the item lacks is the **string-shape**
  `404`, the five members v1 never stores included; an unknown or malformed `itemId` and an
  unparseable dimension or `quality` are the problem-details `400`/`404`; non-positive
  dimension values are forgiven; `imageIndex` past the last backdrop is the string `404`;
  `Chapter` answers the string `404` per chapter today, plus the **tripwire**: a test asserting
  no v1 writer creates a `Chapter` row, which fails the day one does — the signal to extend
  this feature, 005's `UNPROBED` pattern.
- **Depends on:** T9
- **Verified by:** AC-11's tests with the split held by golden bodies — unknown item →
  problem details; absent type, out-of-range index, `Box` → the string shape naming item and
  type; `maxWidth=banana` → the problem-details `400` with the `errors` map keyed on the
  declared spelling; `maxWidth=-100` → `200`; `format=Banana` → `200`, dropped and recorded;
  a request for each of the five never-stored members → the string `404`, proving the
  vocabulary parse admits them.
- **Plan reference:** §6.1, §6.4, §7; spec §3.2 errors, §3.5, AC-11

## T11 — The resize and format matrix on the wire

- [ ] **Changes:** the wire-level half of the T6 matrix — parameterised requests through the
  full stack proving the plumbing delivers what the pure module decided, and the negotiation
  criterion: the resized request with `Accept: image/webp` → WebP under `Vary: Accept`; the
  same with `format=Png` → PNG; the verbatim request with the offer → the source format
  untouched.
- **Depends on:** T9
- **Verified by:** AC-4 (300 of 1000×1500 → 300×450 decoded), AC-5 (2000 of 400 → 400,
  byte-identical to the source file), AC-6 (fill covers, overflow kept; a box past the source →
  the source verbatim; the distorted exact box beside it), AC-7 (the logo resized → PNG with
  alpha; `format=Jpg` → opaque JPEG), AC-15 (the three negotiation cells) — each test naming
  the measured cell it reproduces; `format=Svg` → the source verbatim with the resize ignored.
- **Plan reference:** §6.3, §6.4; spec §3.3, AC-4, AC-5, AC-6, AC-7, AC-15

## T12 — The byte-identity trio: rescan, cache hit, cache loss

- [ ] **Changes:** the three criteria that need the whole stack and the real scan:
  **AC-2** — 003's scan over a `tmp_path` library twice: touch the poster's mtime without
  changing bytes → the tag is unchanged; change the bytes → the tag changes; **AC-8** — the
  same request twice is byte-identical, and then the source file is overwritten *without
  rescanning* and asked again → still the first bytes, proving the hit never recomputed (the
  tag in the key is what makes this honest — the row still names the old content); **AC-13** —
  `cache/images/` deleted between requests → the same body bytes, recomputed.
- **Depends on:** T9
- **Verified by:** the three tests above, plus the warning path: after AC-8's overwrite, a
  *rescan* updates the row and the next request serves the new bytes — the cache's stale entry
  now unreachable garbage, asserted by key absence — closing the loop
  [spec §3.4](spec.md#34-caching-and-conditional-requests) promises.
- **Note:** the scan runs here and nowhere else in 006's tests; every other task seeds through
  the repositories (T4), which is 005's discipline for the same reason.
- **Plan reference:** §6.5; spec AC-2, AC-8, AC-13

## T13 — The acceptance map, and Implemented

- [ ] **Changes:** `FEATURE_006` in `tests/conformance/test_acceptance.py`, mapping **all
  fifteen** criteria of [spec §5](spec.md#5-acceptance-criteria) to named tests;
  `IMPLEMENTED_FEATURES` gains `"006"` and T9's interim landed-routes list is deleted;
  `specs/README.md`'s table; `spec.md`, `plan.md` and this file to `Implemented` with dates;
  AGENTS.md's where-the-project-is paragraph; anything a task learned that is not yet in the
  spec, the plan or `behaviours.md` lands in this change or the task that learned it — with
  the "what this feature owes the next ones" section written here, 004 and 005's precedent.
- **Depends on:** everything above
- **Verified by:** `test_every_implemented_feature_has_a_map` passes **with** 006 marked
  `Implemented`; `test_no_route_ships_ahead_of_its_feature` passes with the interim list gone;
  the full local gate — `ruff check`, `ruff format --check`, `mypy`, `pytest` — green; the
  definition of done below closed line by line.
- **Plan reference:** §8; 005 T17 is the precedent

---

## Definition of done

The feature is done when **all** of these hold:

- [ ] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all fifteen
      — has a passing test, by name, in `FEATURE_006`.
- [ ] Both routes reach the conformance level [spec §6](spec.md#6-conformance) declares — L2
      throughout, golden **headers and dimensions**, never encoder bytes; the byte-identity
      criteria compare within one run, where the encoder is constant.
- [ ] Both routes are served, `"006"` is in `IMPLEMENTED_FEATURES`, and no route exists outside
      [`surface.yaml`](../../docs/compatibility/surface.yaml) — the two rows were in the file
      before this list was written, so the check is registration, not listing.
- [ ] The feature ends owning **no schema**: no table, no column, no migration
      ([plan §4](plan.md#4-data-model)). The resize cache is files under the data directory,
      disposable by test (AC-13), and nothing else appeared.
- [ ] The header-set sweep is green across the suite: no image response carries `ETag` or
      `Accept-Ranges`, every one carries the seven-header contract of
      [plan §6.6](plan.md#66-headers-and-conditional-requests).
- [ ] The `Chapter` tripwire and the `UNPROBED`-style absences hold: no v1 writer creates a
      `Chapter` row, and the test that says so is the extension signal.
- [ ] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same
      change that learned it.
- [ ] Every measurement a task took against the reference is in the spec or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) with provenance — T1's probe
      cells first among them, and the manual-request citations it upgrades.
- [ ] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.
