---
feature: 006-images
title: Images — tasks
status: Implemented
created: 2026-08-28
updated: 2026-08-28
accepted: 2026-08-28
implemented: 2026-08-28
amended: 2026-08-28 at the gate — T2's fixture note, T9's indexed-form tests and corrected test names; see "What the gate changed"
plan_status_required: Accepted
plan_status_actual: Implemented
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

- [x] **Changes:** `compat/errors.py` grows the message-string refusal of
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
  [behaviours §4.4](../../docs/compatibility/behaviours.md#44-non-ascii-characters-are-sent-as-themselves-not-as-uxxxx--withdrawn-2026-08-28)
  exception, asserted so nobody re-fights it per route.
- **Note:** the shape carries the item's display name onto a tokenless route — the
  id-as-capability consequence, recorded in behaviours §1.11 and §2.10. The test names it so the
  disclosure is a decision with provenance, not an accident.
- **Plan reference:** §5, §7; behaviours §1.11
- **Done (2026-08-28):** the shape is the gate's, measured again byte for byte before writing it:
  `GET /Items/{id}/Images/Box` on an item called `#1 to Infinity` answers **51 bytes** —
  `"#1 to Infinity does not have an image of type Box"`, quotes included — in
  `application/json; charset=utf-8`. `Backdrop/99` and `Chapter/0` answer the same sentence, and
  it names **the type, never the index**, which the task statement did not say and a message
  built from `f"...{index}"` would have got wrong on the one refusal a client sees most.

  **This task's own verification cited a withdrawn exception.** It asks for a non-ASCII name
  asserted "under the standing [behaviours §4.4] exception" — send the character itself.
  §4.4 was taken at 004 T15 and **reversed at 005 T4**, which implemented the reference's
  escaping in `compat/responses.py` and wrote it up as §1.16; nobody came back to §4.4, so for
  three features the registry said one thing and the code did the other. The measurement settles
  it in the reference's favour: `DW Español` comes back `"DW Espa\u00F1ol does not have an image
  of type Box"`, uppercase hex. Writing the test the task asked for would have asserted a raw
  `ñ` and failed against Atrium's own response class. §4.4 is now marked **withdrawn** with the
  date and the argument that answered it, and §1.16 points at what it reversed.

  **And one refusal on this route is not a `404` at all.** The **all-zeros identifier** is
  `Guid.Empty` on the reference: `/Items/000…0/Images/Primary` answers `400` in the *third*
  shape — `text/plain`, the fixed 25 bytes — because the empty GUID resolves to the user's root
  folder, an item v1 does not have. Every other unowned identifier answers problem details, which
  is what the first measurement of "unknown item" would have contradicted had it been taken with
  the obvious placeholder id. Recorded in [spec §3.2](spec.md#32-get-itemsitemidimagesimagetype--getitemimage)
  and behaviours §1.11 as measured and deliberately not reproduced.

  **The plan's two contract names do not lint.** `ItemNotFound` and `ImageNotFound` trip `N818`,
  which every exception in `compat/errors.py` already obeys — `NotFoundError`,
  `UnauthenticatedError`, `AccountUnavailableError`. Renamed to `ItemNotFoundError` and
  `ImageNotFoundError`, and [plan §5](plan.md#5-contracts) is amended rather than the module
  exempted. `ItemNotFoundError` subclasses `NotFoundError` and needs no handler of its own:
  Starlette resolves handlers by walking the MRO, so two names reach one shape — which is what
  plan §7's "verified by exception type" needs and what a bare alias could not give.

## T4 — The drawn fixtures and the seeded image world

- [x] **Changes:** `tests/fixtures/images.py` — the [plan §8](plan.md#8-testing-strategy)
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
- **Done (2026-08-28):** **the inventory in this task's statement cannot express three of the
  refusals the next tasks have to prove.** It names the poster, the small source, the logo, the
  three backdrops and the three `source_kind` readings — and T5's own verification asks for "an
  unknown, removed or row-less item" and "an embedded row whose art was stripped". An unknown id
  needs no fixture; the other three do, and none of them was in the list:

  * an item with **no image rows at all**, so "this item exists and has no image of that type" is
    reachable on an id that is in the table;
  * a **soft-removed** item, which is the only way to tell `ItemNotFoundError` from
    `ImageNotFoundError` on an id that exists — an unknown id proves nothing about the split;
  * a carrier that holds **no picture**, for plan §7's "embedded row whose art was stripped since
    the scan": the row promises a picture and the file has none, and no other item in the world
    can say that.

  The 005 gate's fixture lesson twice in one feature: T2 seeded AC-14's discriminating episode,
  and this seeds three refusals' discriminating items. A world built only from what the *changes*
  paragraph lists would have sent T5 back here.

  **The drawings are exposed as bytes, not only as files.** T6's module is pure and takes bytes,
  so `Drawn` is a value the transform tests can use with no database, no library root and no
  `tmp_path` — the fixture is two things, and only one of them is a world.

  Two smaller things. The poster is **1000×1500 rather than 1000×N**: the ratio is the fixture's
  whole discriminating power, and 2:3 is what T1 measured the reference on. And the images are a
  4×6 colour block scaled up with nearest-neighbour rather than a per-pixel loop — a 1.5-megapixel
  Python loop costs about a second per build, and the assertions here are about dimensions and
  alpha, not about gradients. Determinism is asserted rather than assumed: two draws are compared
  byte for byte, and two builds of the whole world are compared by identifier, tag and bytes.

## T5 — `ImageRepository` and `images/source.py`: from item id to carrier bytes

- [x] **Changes:** `db/repositories.py` grows `ImageRepository` — the one
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
- **Done (2026-08-28):** **the hostile-row test passed with the containment check deleted**, on
  the first path anybody would write. `../../../../etc/passwd` from a `tmp_path` library root
  reaches nothing — four `..` do not climb out of a pytest temporary directory — so the resolver
  refused it for the wrong reason and the assertion could not tell that from the right one. Every
  case now points at a **file that exists** outside the root, and the test asserts that it does
  before asserting the refusal; with the check removed all three fail. A security test that cannot
  fail is the class 001 T16 found in a passing golden and 003 T19 in a cited claim.

  **The repository does not raise.** Plan §7 gives this route two `404` bodies, and which one a
  request gets is a *wire* decision — so `ImageRepository.locate` returns an `ImageLookup` saying
  what it found and `images/source.py` names the refusal. A repository importing
  `compat/errors` would be `db/` deciding a wire shape, which is the inversion
  `architecture.md` §1 exists to prevent; it would also have passed every test in this task.

  **Every way of failing to produce bytes is the *same* refusal, deliberately.** A row whose file
  was deleted, an embedded row whose art was stripped, and a crafted row that escapes its root are
  three different logs and one `404`: a client cannot act on the difference, and telling it which
  would describe the server's filesystem to anyone holding an item id — the id-as-capability
  consequence of [spec §3.2](spec.md#32-get-itemsitemidimagesimagetype--getitemimage), from the
  other side.

  **The boundary is now a test, both ways.** `api/` owning no SQL was already asserted; `images/`
  knowing nothing about HTTP was a sentence in [plan §3](plan.md#3-modules). It is a rule in
  `tests/unit/test_import_directions.py` now — no `fastapi`, no `starlette`, no `sqlalchemy`, no
  `httpx` under `images/` — because the version of this that rots quietly is a transform reaching
  for a `Request` to read `Accept`: it would work, pass its own tests, and make T6's matrix
  impossible to write as values.

## T6 — `images/transform.py`: the decision and the formats, pure

- [x] **Changes:** the [plan §6.3](plan.md#63-the-transform-decision) decision and
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
- **Done (2026-08-28):** **"Never upscale" is not a property of the server.** It is a property of
  *which parameter was sent*, and the spec stated it as a universal for three amendments. Measured
  on a 2000×3000 poster
  `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`:

  | Asked | Delivered |
  |---|---|
  | `maxWidth=4000` | 2000×3000 — the source |
  | `fillWidth=4000&fillHeight=6000` | 2000×3000 — the source |
  | `width=4000` | **4000×6000** |
  | `height=6000` | **4000×6000** |
  | `width=2500&height=1000` | **2500×1000** |
  | `width=4000&maxWidth=1000` | 1000×1500 — the exact size, capped *afterwards* |

  A box parameter means **at most**; `width`/`height` mean **exactly**. The plan's step 3 said
  "honoured exactly after the never-upscale cap" and there is no cap on that path — so a literal
  implementation would have answered a *smaller* image than a client asked for by name, on the one
  path whose entire meaning is "this size". Found by writing the matrix row for it and checking
  the row against the reference rather than against the sentence it came from. Spec §3.3 and plan
  §6.3 step 3 are amended, and the probe grew an **exact battery** so the claim is reproducible
  rather than a session's scratch requests.

  The last cell settles the composition order too: `width=4000&maxWidth=1000` → 1000×1500 means
  step 4 caps step 3's result, which is what the module does. `fillWidth=500&width=300` → 300×450
  says the exact pair *replaces* a fill rather than composing with it — also measured, also what
  the module does, and neither was in any document.

  Everything else held as documented: the fill cover rule, the negotiation triple, `Svg`'s
  short-circuit, `Bmp`/`Gif` falling back mid-transform with a recorded drop, `quality` clamping
  and being ignored for PNG, and a bare `quality` not transforming at all (T1's finding, now a
  test). The decode-failure path is asserted twice — a truncated file and Pillow's own
  decompression-bomb guard — because plan §7 says both answer the source bytes and only one of
  them is an exception type anybody would think to catch.

## T7 — `images/cache.py`: the disposable store

- [x] **Changes:** the [plan §4](plan.md#4-data-model) layout —
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
- **Done (2026-08-28):** **"warn once per process" cannot be written as "warn once per process"
  and stay testable.** A module-level flag is one that every test after the first sees already
  set, so the assertion that there is exactly *one* warning passes or fails depending on test
  order — and the fix, a reset hook, is test-only API in production code. The counter is per
  `ImageCache` instead, and the application builds exactly one: the same guarantee, reachable by a
  test that constructs its own.

  **Two of these tests cannot fail as root**, and say so rather than passing. Taking a permission
  away and expecting it to bite is a green test proving nothing under a user that ignores
  permission bits — the class of "a test that compares Atrium against itself" (001 T16). Both are
  skipped with the reason named.

  **The key is the *decision*, not the request**, which fell out rather than being designed:
  `maxWidth=300` and `width=300` deliver the same 300×450 of a 2:3 source, so they are **one**
  entry. A key built from the request's parameters would cache a grid twice because two clients
  spell one size differently — and would still miss the case that matters, since the resolved
  format is not a request parameter at all when `Accept` decided it.

  The rest held as planned: the tag inside the key makes a stale entry unreachable rather than
  wrong, a negotiated WebP and a bare JPEG are two files, eight concurrent writes of one key
  converge on one intact entry with nothing left beside it, and deleting the tree costs a
  recompute.

## T8 — `images/service.py`: the orchestration

- [x] **Changes:** [plan §5](plan.md#5-contracts)'s one entry point: `ImageQuery` in, `ImageReply`
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
- **Done (2026-08-28):** **AC-8's test failed against the obvious implementation, and the reason
  is a design decision nothing had spelled out.** The service read the carrier's bytes, described
  *them*, and decided from that — so overwriting the source file without rescanning changed the
  source's dimensions, changed the decision, changed the cache **key**, and turned the hit into a
  silent miss. The second request came back with different bytes, which is exactly what AC-8
  forbids.

  The decision has to come from the **row**: 004 stored `width` and `height` at association time
  and [plan §6.1](plan.md#61-the-lookup) already said they answer the resize question before a
  file is opened — but nothing said *why it matters*, and the reason is not performance. A key
  derived from the file is a key that moves whenever the file does, and the whole point of the tag
  being in the key is that a request served from cache is the image **the row still names**. The
  format and the alpha still come from the bytes, because no row stores either. Plan §5 records it
  now, with the test that found it.

  **A fallback is never cached**, which the task statement did not say and which the wrong version
  of this passes every other test on. When a decode fails the source's own bytes come back —
  writing those under a key claiming "300×450, WebP" would serve a full-size JPEG to every later
  request for a small WebP, for as long as the file survived. The miss is repeated instead: one
  decode attempt, and correct.

  `accepts_webp` joins `ImageQuery` and plan §5's listing. The gate added AC-15 after that
  contract was written and the offer has to reach the decision somehow — as a boolean, so
  `images/` still parses no HTTP.

## T9 — The two routes, the header contract, and the conditional pair

- [x] **Changes:** `api/images.py` — `GET /Items/{itemId}/Images/{imageType}` and its indexed
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
- **Done (2026-08-28):** **[plan §6.6](plan.md#66-headers-and-conditional-requests) asks for two
  things that cannot both hold.** "The `304` carries the `200`'s header set minus
  `Content-Length`" and "the conditional check runs **before** any bytes are read" are
  incompatible: the `200`'s `Content-Type` is a property of the payload that would have been sent.
  The reference settles it by doing the work — a conditional request offering `image/webp` on a
  resized image answers `304` with `Content-Type: image/webp`, and the same request without the
  offer answers `image/jpeg`. So the answer is resolved and the body is dropped, which after the
  first request is a cache read rather than an encode. §6.6 is amended with the measurement.

  **One measured header is deliberately not reproduced**, and it took dumping a live response to
  see it: on a *transformed* response the reference's `Last-Modified` is the **variant's** own
  creation time, not the carrier's — one second *after* that same response's `Date`, because the
  value is the cache entry's mtime and the entry had just been written. Atrium sends the carrier's
  on every path. Recorded in [spec §3.4](spec.md#34-caching-and-conditional-requests) with the
  argument: both are valid validators, Atrium's survives a cache wipe where the reference's forces
  a client to re-download every poster, and reproducing it would make the header
  non-deterministic — the one thing spec §6 pins goldens against.

  **002's image stub could not simply be "replaced".** Its own docstring predicted the swap, and
  what it did not predict is that the *assertion* had to change: the stub answered `200` to
  anything, and the real route answers `200` only where there is an image, so "every mechanism
  reaches it" is not the claim that survives. The claim AC-12 actually makes is **presenting a
  token never changes the answer** — asserted against the tokenless response, byte for byte, with
  `traceId` masked because it is per request by definition. The `200` half lives here, where there
  is an image. The acceptance map is what caught the rename.

  Two smaller ones. The **type vocabulary is thirteen members, and parsing it needs a
  case-insensitive `BeforeValidator`**: the enum alone would answer `400` to `/images/primary`,
  which behaviours §1.14 says is the same request. And `_not_modified` takes a whole `ImageReply`
  rather than a date, which is the shape the first finding forces.

## T10 — The error matrix on the wire

- [x] **Changes:** the route-level error handling that closes
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
- **Done (2026-08-28):** **the recorder's convention is `parameter=value`, not `parameter`**, and
  the plan's "recorded-drop signal" does not say so. `known_tokens` — 005 §6.12's own helper, which
  drops `format=Banana` one line earlier in the same request's life — records the pair as
  `("/Items/{itemId}/Images/{imageType}", "format=Banana")`, because what was dropped is the
  **value**. The transform was recording a bare `"format"`, so one request's two drop paths would
  have produced two different shapes in one counter, and 010's differential would have read them
  as two different findings. `Decision.dropped` carries `format=Bmp` now.

  Everything else the matrix asks for was already true when the tests were written, which is what
  T9 landing the vocabulary parse and the two exception types bought: `Box`, `BoxRear`, `Menu`,
  `Screenshot` and `Profile` each answer the **string** `404` while `NotAnImageType` answers the
  problem-details `400` — the difference that proves the parse admits all thirteen members — and
  an out-of-range index names **the type**, not the index.

  **The tripwire is structural rather than empirical.** "No v1 writer creates a `Chapter` row"
  written as a scan that finds none would pass for exactly as long as nobody put one in a fixture.
  It is asserted against the vocabulary the write path *accepts* instead: `apply` takes an
  `ImageAssociation`, an `ImageAssociation` carries an `ImageKind`, and `ImageKind` is the seven
  types a local file can be — so the six that can never be written are named in one assertion, and
  the day that set shrinks this fails.

  Four golden bodies hold the split, with the `traceId` as the one substituted value: it is per
  request by definition (behaviours §1.11) and everything else in those bodies is fixed.

## T11 — The resize and format matrix on the wire

- [x] **Changes:** the wire-level half of the T6 matrix — parameterised requests through the
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
- **Done (2026-08-28):** every cell delivered what T6's pure module decided, first time — which
  is the answer this task exists to get, and it is worth saying that the answer being "nothing
  broke" is a **finding about the boundary**, not an absence of one. A route that dropped a
  parameter on the floor, mangled a spelling, or reached for the wrong field of `ImageQuery` would
  pass every test in `test_image_transform.py` and fail every row here; that none of them did is
  what plan §3's split buys, measured rather than assumed.

  The rows that carry the most weight are the ones the earlier documents had wrong and T1 and T6
  corrected: **fill 500×1500 of the 2:3 poster comes back 1000×1500** (neither the box nor the
  fit), **`width=2000&height=3000` upscales** while `fillWidth=4000&fillHeight=6000` returns the
  source untouched, and **`maxWidth` caps an exact size afterwards** — `width=2000&maxWidth=500`
  is 500×750. Each is a cell the reference was asked for directly.

  AC-15's three cells hold on the wire: the resized request with the offer comes back WebP under
  `Vary: Accept`, the same request with `format=Png` comes back PNG, and the **verbatim** request
  with the offer comes back JPEG — still carrying `Vary: Accept`, which is what `Vary` means and
  what the earlier probe's single blind cell had made look like "no negotiation". `image/avif` is
  offered and not taken, also measured.

## T12 — The byte-identity trio: rescan, cache hit, cache loss

- [x] **Changes:** the three criteria that need the whole stack and the real scan:
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
- **Done (2026-08-28):** **AC-2's second half was unreachable, and had been since 004.** "The tag
  changes when the file changes" is false of every scan at every depth: `Field.IMAGES` merged
  under the whole-replace rule, which routes through the scalar branch — *keep what the item
  already has unless the mode is `Replace`* — so an item that had ever been given artwork could
  never be given different artwork. And v1 has **no refresh route**, so nothing could ask for
  `Replace` either. Replacing a poster changed no tag, ever, which means a client's cached copy
  of a corrected poster is valid for ever: the exact failure [spec §3.1](spec.md#31-how-a-client-discovers-an-image)
  describes, arrived at from the opposite direction.

  The field has its own rule now — `ListRule.REDERIVED`, re-read every time and written only when
  it differs. The argument is that `IMAGES` has exactly **one** source, the directory walk, so
  "keep what we have" was never protecting a better answer from a worse one; it was protecting a
  stale index of a directory from the directory. [004's plan §6.1](../004-metadata-resolution/plan.md)
  carries the amendment, because the rule is 004's.

  **And the scan still has to look.** Even re-derived, a *default* scan re-examines an item only
  when its **media** file changed — 003's change-detection signal — so replacing `poster.jpg`
  beside an untouched film is picked up by a **deep** scan and not before. That is a real
  user-visible limitation and it is now a test that pins it plus
  [behaviours §5.6](../../docs/compatibility/behaviours.md#56-a-default-rescan-does-not-notice-a-replaced-poster),
  with the reason it is a gap rather than a fix: widening the signal means stat-ing dozens of
  candidate artwork names per item per scan, which is the cost 003's design was written to avoid.
  Spec AC-2 says so now instead of implying otherwise.

  AC-8 is asserted the honest way — the source overwritten **without** a rescan, so a reply that
  recomputed would be visibly different — and the loop closes: after a deep rescan the new bytes
  are served, the old entry is still on disk and **unreachable**, asserted by computing both keys
  from the two tags rather than by looking for a deletion nothing performs.

## T13 — The acceptance map, and Implemented

- [x] **Changes:** `FEATURE_006` in `tests/conformance/test_acceptance.py`, mapping **all
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
- **Done (2026-08-28):** the map went in with **all fifteen** criteria named and nothing had to be
  written to make one of them true, which is what the twelve tasks before it were for. Nearly every
  criterion is asserted **twice** — once where the answer is a value (the pure module, the service)
  and once on the wire — and the pairing is the point rather than belt and braces: a route that
  dropped a parameter passes the first and fails the second, and a decision that is wrong fails
  both. The three asserted once are the three with one place to be: AC-3 and AC-9 are statements
  about headers and AC-14 about a map 005 emits.

  Two entries are worth naming because they are **not** the criterion's happy path.
  AC-2's list includes `test_a_default_rescan_does_not_notice_an_artwork_only_change`, which pins
  the limitation the criterion now names rather than the behaviour it asks for — a criterion whose
  boundary is undocumented is a criterion somebody will later "fix" by accident. And AC-8's
  includes the rescan test, because "a hit never recomputes" is only safe next to "and a rescan
  makes it unreachable"; either alone is half a cache story.

  `IMPLEMENTED_FEATURES` gains `"006"` and T9's interim list is deleted, along with the test that
  guarded it — which is what finishing a feature looks like here, and the third time this file's
  own docstring has had to be corrected about how many such lists are gone.

---

## Definition of done

The feature is done when **all** of these hold:

- [x] Every acceptance criterion in [`spec.md` §5](spec.md#5-acceptance-criteria) — all fifteen
      — has a passing test, by name, in `FEATURE_006`.
- [x] Both routes reach the conformance level [spec §6](spec.md#6-conformance) declares — L2
      throughout, golden **headers and dimensions**, never encoder bytes; the byte-identity
      criteria compare within one run, where the encoder is constant.
- [x] Both routes are served, `"006"` is in `IMPLEMENTED_FEATURES`, and no route exists outside
      [`surface.yaml`](../../docs/compatibility/surface.yaml) — the two rows were in the file
      before this list was written, so the check is registration, not listing.
- [x] The feature ends owning **no schema**: no table, no column, no migration
      ([plan §4](plan.md#4-data-model)). The resize cache is files under the data directory,
      disposable by test (AC-13), and nothing else appeared.
- [x] The header-set sweep is green across the suite: no image response carries `ETag` or
      `Accept-Ranges`, every one carries the seven-header contract of
      [plan §6.6](plan.md#66-headers-and-conditional-requests).
- [x] The `Chapter` tripwire and the `UNPROBED`-style absences hold: no v1 writer creates a
      `Chapter` row, and the test that says so is the extension signal.
- [x] Anything learned during implementation is back in `spec.md` or `plan.md`, in the same
      change that learned it.
- [x] Every measurement a task took against the reference is in the spec or
      [`behaviours.md`](../../docs/compatibility/behaviours.md) with provenance — T1's probe
      cells first among them, and the manual-request citations it upgrades.
- [x] `spec.md`, `plan.md` and `tasks.md` are all marked `Implemented`.

## What this feature owes the next ones

**007** inherits nothing from here and is owed one warning: the image routes are the first in this
project that carry **no authentication dependency at all** (`api/images.py`), so a future change
that adds a global auth dependency to the application rather than to a router would break them
silently — `test_ac12_every_mechanism_is_accepted_and_none_changes_the_answer` is what catches it.

**008** gets two things and owes one back. It gets `compat/errors`' fourth shape — the
JSON-encoded message `404`, already byte-pinned — and the delivery stub in
`tests/conformance/test_auth_mechanisms.py`, which is now the **last** one: 006 T9 replaced the
image stub with the real route, and doing so changed the assertion from "every mechanism reaches
it" to "no mechanism changes the answer". 008 should expect the same when its stub goes. What it
owes back is `Chapter`: `test_no_v1_writer_can_create_a_chapter_row` fails the day something
writes one, and that failure is the signal to serve chapter images rather than a test to relax.

**009** is unaffected. Playlist items carry images through their item ids like everything else.

**010** collects five things this feature raised for the differential:

* **EXIF orientation on resize** — the one edge no remote request can reach (plan §6.8 row 1). It
  needs a planted file in a controlled library.
* **OQ-4** — whether any client sends `percentPlayed`, `unplayedCount`, `blur`, `backgroundColor`
  or `foregroundLayer`. The five stay undeclared on purpose and the ignored-parameter recorder
  counts them per `(route, parameter)`, so the trail exists and only needs reading.
* **Two recorded divergences**: `Last-Modified` on a transformed response is the carrier's mtime
  here and the variant's creation time on the reference (spec §3.4), and a forgiven non-positive
  dimension serves the file here and a re-encode there
  ([behaviours §1.17](../../docs/compatibility/behaviours.md)). Both are invisible through a
  parser and visible in `Content-Length`.
* **[behaviours §5.6](../../docs/compatibility/behaviours.md)** — a default rescan does not notice
  a replaced poster. Whether the reference does is unmeasured, and measuring it means writing into
  a library. **Owned since 2026-09-02**: a named comparison of
  [010 §3.10](../010-conformance-harness/spec.md), added by that list's D-6, and the library written
  into is the single-use reference instance 010 §3.1 stands up and destroys.
* **The empty-GUID edge** — `/Items/000…0/Images/Primary` is `Guid.Empty` on the reference and
  answers the controller's `400`; Atrium answers the `404` (spec §3.2).

**The starting inventory this feature leaves behind**, for whatever serves bytes next: `images/`
owns bytes and imports no HTTP and no SQL, asserted by
`tests/unit/test_import_directions.py`; the disposable cache under `<data-dir>/cache/images/` is
keyed on a content tag, so nothing ever needs invalidating; and `tests/fixtures/images.py` draws
its images rather than checking them in — a poster whose ratio discriminates, a source small
enough to prove no-upscale, a logo with a real alpha channel, and three backdrops of three sizes.
