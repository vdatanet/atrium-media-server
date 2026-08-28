---
feature: 006-images
title: Images — implementation plan
status: Implemented
created: 2026-08-28
updated: 2026-08-28
accepted: 2026-08-28
implemented: 2026-08-28
amended: 2026-08-28 by T9 — §6.6's conditional paragraph (the two promises that cannot both hold) and the `Last-Modified` divergence on a transformed response; and 2026-08-28 by T8 — §5's `accepts_webp` and the row-derived decision AC-8 needs; and 2026-08-28 by T6 — §6.3 step 3's never-upscale cap deleted, measured; and 2026-08-28 by T3 — §5's two exception names gain the `Error` suffix the linter requires; and 2026-08-28 by T1 — §6.3 steps 1 and 5, §6.4's `quality` bullet, §6.8 row 3 discharged, behaviours §1.17 added; and 2026-08-28 at the gate, which measured the six §6.8 edges before accepting — §1, §5, §6.1, §6.3, §6.4, §6.5, §6.6, §6.8, §7, §8, §9, §10; two measurements went back into the spec (AC-6 corrected, AC-15 added) and one into behaviours §1.11 (the fourth error shape)
spec_status_required: Accepted
spec_status_actual: Implemented
---

# 006 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour.

## 1. Approach

Two routes, and almost everything they need already exists. Five decisions carry the rest.

**Serving is a read of 004's rows, never a second discovery.** Which file is which image was
decided at scan time — name tables, dimensions, content tag — and stored in `item_images` with
nothing optional (004 plan §4). The serve path opens exactly the file the row names, through the
three `source_kind` readings, and never re-runs discovery. The stored `width`/`height` answer the
never-upscale question before any file is opened, and the stored `tag` is already the cache
contract 005's goldens pinned.

**Two delivery paths, and the verbatim one is the anchor.** A request that requires no
transformation — no effective resize and no format change — answers the source bytes
exactly as they sit on disk. *(`quality` was in that list until T1 measured it out of one: a
`quality` with nothing to resize comes back byte-identical to the file — §6.3 step 5.)* That is what makes AC-8's byte-identity trivial, and it is why the
measured "3200px asked of an 800px source returns the source"
`[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]` falls out of the design
instead of being a special case. Everything else goes through one pure transform (Pillow, already
a dependency — the pyproject comment under 004 T8 promised it to this feature) and lands in a
disposable disk cache under the data directory.

**The framework fight this feature brings is a header that must not exist.** The obvious way to
serve a file — Starlette's `FileResponse` — computes and sends an `ETag` on every response, and
the measured reference sends no image etag at all (spec §3.4). So responses are plain `Response`
objects with the header set built explicitly, and the test suite asserts the *absence* of
`ETag` and `Accept-Ranges` as firmly as the presence of the rest — a convenience class or a
framework upgrade that starts adding either must fail a test, not ship a delta.

**No authentication code runs on these routes at all.** The spec's rule — a token accepted, none
required, no per-user branch (§3.2, behaviours §2.10) — is implemented by absence: the routes
declare no dependency and never read the token, so every mechanism is "accepted" trivially and an
item id is the capability the spec says it is. The one edge where "never reads" and "validates
when present" diverge — a request carrying an *invalid* token — was measured at the gate: unknown
and malformed tokens, through every mechanism, answer the identical `200`
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. "Never reads" is
what the reference does too.

**The sequencing gap is named, not papered over.** `Chapter` is wired generically and answers
`404` for every request in v1, structurally: no v1 writer creates a `Chapter` row — 004's tables
do not know the type, generation is out of v1 in its own right, and the `Chapters` field itself
sits in 005's `UNPROBED` set until 008 probes media. That is the same wire a client sees from a
reference that has not generated chapter images yet (spec §3.5), and when chapter data arrives
the route is already correct.

**One DTO reconciliation, ordered by the spec.** §3.1 pairs every inherited tag with an owning
id, and the emitter registry has `ParentThumbItemId` but not `ParentBackdropItemId` — 005 left it
out deliberately, and the spec review moved it in here. It is added with the same per-type set as
the tags it pairs with, and AC-14's test asserts the pairing row for row.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–005 | [005 plan §2](../005-item-query-api/plan.md#2-inherited-decisions) |
| `item_images`: the key, the three `source_kind` readings, `width`/`height`/`tag` never null | [004 plan §4](../004-metadata-resolution/plan.md#4-data-model), `db/models.py` |
| The tag is the first 16 bytes of the SHA-256 of the image bytes, computed at association | 004 (`metadata/artwork.py`), spec AC-2 |
| The data-directory layout; `cache/` is disposable; downloads land under `metadata/artwork/` | [001 plan §4](../001-server-identity-and-discovery/plan.md#4-data-model), `config/paths.py` |
| A `remote` row's `relative_path` resolves against the data directory | [004 plan §6.5](../004-metadata-resolution/plan.md#6-algorithms), `metadata/tmdb.py` |
| Problem-details `400`/`404` bodies and the extended validation handler | behaviours §1.11, `compat/errors.py` |
| Parameter canonicalisation, `api_key` seeding, the ignored-parameter recorder | [005 plan §6.12](../005-item-query-api/plan.md#612-parameter-plumbing), `compat/query_params.py` |
| Image routes accept a token and require none | behaviours §2.10, spec §3.2 |
| Repositories return domain objects; no ORM row crosses the boundary | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |

**Deviations:** none.

## 3. Modules

```
src/atrium/
├── images/
│   ├── source.py      a row's bytes: the three source_kind readings, root search, containment
│   ├── transform.py   pure: (bytes, TransformSpec) -> (bytes, format, dimensions). All Pillow here
│   ├── cache.py       the disposable disk cache under <data-dir>/cache/images/
│   └── service.py     orchestration: verbatim or transform-and-cache; returns an ImageReply
├── api/
│   └── images.py      the two routes: parameter parsing, headers, conditional requests
└── db/
    └── repositories.py grows ImageRepository: the one lookup query (§6.1)
```

`architecture.md` §3 reserved `images/` in the layout from the start; this feature fills it.
`api/images.py` owns the wire — headers, `304`, the two error statuses — and `images/` owns bytes
and knows nothing about HTTP. The repository is the only reader, as everywhere else.
`api/item_dto.py` grows the `ParentBackdropItemId` emitter (§1); that is an entry in an existing
table, not a module.

## 4. Data model

**No table, no column, no migration.** The rows are 004's, unchanged. The resize cache is files,
not schema:

```
<data-dir>/cache/images/<k[:2]>/<k>.<ext>     k = sha256 over (item, type, index, tag, transform)
```

The `tag` in the key means a changed image never serves a stale variant — its old entries become
unreachable garbage rather than wrong answers. The transform tuple carries the **resolved** output
format, so a negotiated WebP and a bare JPEG of the same geometry are two entries (§6.4). The
extension is the output format, so a cache hit recovers its `Content-Type` without sniffing. Writes are tmp-file-plus-atomic-rename in the same
directory, so concurrent identical requests converge on identical bytes and a crash leaves no
half-written entry. Unbounded in v1 and disposable by contract (spec §4): deleting it costs CPU,
which AC-13's test proves, and eviction is future work an operator does with `rm` until measured
need says otherwise.

## 5. Contracts

**`images.service`** — the one entry point the routes call:

```python
@dataclass(frozen=True)
class ImageQuery:                  # parsed and canonical; the route owns parsing
    item_id: str
    image_type: str                # a member of the reference vocabulary, already validated
    index: int = 0
    max_width: int | None = None   # and max_height, width, height, fill_width, fill_height
    quality: int | None = None
    image_format: RequestedFormat | None = None   # a vocabulary member or None; §6.4 resolves it
    accepts_webp: bool = False     # the Accept offer, reduced to the token that changes an
                                   # answer. Added at T8: the gate measured the negotiation
                                   # (AC-15) after this listing was written, and a boolean is
                                   # what keeps `images/` from parsing a header

@dataclass(frozen=True)
class ImageReply:
    payload: bytes
    media_type: str                # from the bytes served, never from a file extension
    last_modified: datetime        # the carrier file's mtime, UTC (§6.6)

def get(query: ImageQuery) -> ImageReply    # raises ItemNotFoundError, ImageNotFoundError
```

Two refusals, because the measured wire has two `404` bodies *(amended at the gate — the draft
had one exception mapped to problem details)*: `ItemNotFoundError` for an unknown or soft-removed
item — the world 005 serves has no removed items, and this route must not disagree with it —
mapping to the problem-details `404`; and `ImageNotFoundError(item_name, image_type)` for an item
that exists but has no such image — no row, index out of range, a vanished carrier (§7) — mapping
to behaviours §1.11's fourth shape, the JSON-encoded string that names the item and the type.
*(Both were spelled without the `Error` suffix until T3, where the linter refused them: every
exception in `compat/errors.py` carries one, `NotFoundError` included, and a contract name is not
a reason to exempt a module from the project's own rule.)*

Invariants callers may assume, and tests enforce: the payload is complete (`Content-Length` is
its length — there is no streaming here; posters are small and 008 owns streaming); the same
query answers byte-identical payloads whether served from cache or recomputed (AC-8, AC-13); the
service never upscales **on the box parameters** (`width`/`height` are exact, T6); alpha never
leaves through an implicit path (spec §3.3).

**The transform decision is computed from the row's `width`/`height`, never from the file's**
(§6.1) — and AC-8 is why, not performance. The cache key derives from the decision, so a file that
changed under a row nothing has rescanned yet answers the *same* key and the same bytes; deciding
from the bytes on disk turns that hit into a silent miss, which is the exact case AC-8 exists to
pin. *(T8: found by AC-8's test failing against a service that had described the bytes and decided
from them.)* The output **format** still comes from the bytes, because no row stores one.

The **`tag` request parameter never reaches the service.** It selects nothing — a stale tag
serves the current image, measured
`[probe: tools/probe_image_tags.py, Jellyfin 10.11.11, 2026-08-28]` — so it is not a field of
`ImageQuery`; its presence flips one `Cache-Control` value in the route (§6.6), and that is its
whole life.

## 6. Algorithms

### 6.1 The lookup

One repository query resolves everything the request needs: the item (exists, not removed, its
`library_id`), the `(image_type, index)` row, the library's roots, and — for an `embedded` row —
the part-zero source path. The unindexed form is index 0; the pinned document also declares an
`imageIndex` *query* parameter on the unindexed route `[spec: GetItemImage]`, honoured as the
index — measured at the gate on an item whose backdrops differ: `?imageIndex=1` returns backdrop
1's bytes `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.

**`imageType` parses against the full thirteen-member reference vocabulary
`[spec: ImageType]`, not §3.2's eight.** The measurement behind the spec's error row makes the
distinction: a string outside the vocabulary is `400`, while `Box` — a member v1 never stores —
is `404` `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`. The five members
no v1 writer creates (`Box`, `BoxRear`, `Menu`, `Screenshot`, `Profile`) answer `404`
structurally, the same as a type the item merely lacks. The match is case-insensitive: paths
match case-insensitively as a rule (behaviours §1.14), and the type token is a path segment.

### 6.2 Resolving bytes — the three readings

| `source_kind` | The carrier file |
|---|---|
| `file` | the first configured root of the item's library under which `relative_path` exists — the same first-that-exists reading `metadata/refresh.py` already uses for its own root search |
| `embedded` | the item's part-zero source file; the art is extracted through `metadata/tags`, the same reader the scan used |
| `remote` | the data directory root joined with `relative_path` (the row spells `metadata/artwork/…`, 004 plan §6.5) |

Before any open, the resolved path is checked for containment under its base — the library root,
or the data directory's artwork area. The rows are server-written, so escape is "impossible";
the check turns impossible into asserted, and a crafted row in a test proves the refusal.

An `embedded` Primary is re-extracted per request on the verbatim path — a tag parse per open.
That is deliberate: materialising it to disk duplicates bytes the library already holds, and
nothing has measured the parse as a problem (§10). Transformed variants of it land in the cache
like every other source.

### 6.3 The transform decision

From the parsed parameters, in order:

1. **Drop non-positive dimension values.** `maxWidth=-100` parses and is forgiven with `200`,
   measured `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]` — the lenient
   shape of behaviours §1.12 on the one route whose *unparseable* values refuse (spec §3.2).
   **The reference forgives it without dropping it**: `maxWidth=-100`, `maxWidth=0` and
   `fillWidth=-5` each come back re-encoded at the source's own size — 282,225 bytes where the
   file is 84,351 — measured at T1 (same probe,
   [behaviours §1.17](../../docs/compatibility/behaviours.md#117-a-forgiven-dimension-re-encodes-a-bare-quality-does-not)).
   v1 drops the value and stays on the verbatim path, which is a divergence in `Content-Length`
   and in nothing else: two encoders never agree on bytes, so re-encoding here would deliver a
   *different* wrong number at the cost of CPU and a generation of quality. The argument is in
   behaviours §1.17, not here, so a reader who disagrees has one place to argue with.
2. **`fillWidth`/`fillHeight` present** → scale to **cover** the box, aspect intact, overflow
   kept — there is no crop on this path, whatever this step's draft said *(amended at the gate:
   the draft scaled-and-cropped, and the measurement returned 400×600 for a 300×600 box on a
   2000×3000 source — spec §3.3, AC-6 corrected)*. The scale is capped at 1, and a box the
   source cannot cover delivers the source unchanged (measured). A lone fill axis scales that
   axis, aspect intact (measured).
3. **`width`/`height` present** → each given axis is honoured **exactly, with no never-upscale
   cap at all**; a lone axis scales the other by aspect ratio; both at once honour both,
   distorting when they disagree — 300×300 measured of the same 2000×3000 source *(the gate
   measured what this step had flagged)*. *(Amended at T6: the draft said "after the
   never-upscale cap", and the measurement says there is none on this path. `width=4000` of that
   source returns **4000×6000**, `width=2500&height=1000` returns exactly that, and
   `width=4000&maxWidth=1000` returns 1000×1500 — the exact size, capped afterwards by step 4.
   Never-upscaling belongs to the box parameters; `width`/`height` mean exactly.
   `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`)*
4. **`maxWidth`/`maxHeight` present** → fit inside the box, aspect preserved (measured). Sent
   together with the fill pair, the constraints compose to the tightest aspect-true size — a
   300×300 fill under `maxWidth=200` measured 200×300, which every aspect-preserving reading
   produces; there is nothing left to choose between them.
5. **No effective change** — the computed target equals the source dimensions and the resolved
   format equals the source format → **the verbatim path**: the carrier's bytes as they are.
   *(Amended at T1: the draft added "and no `quality` was given", and the measurement removed it.
   `quality=90` with nothing resized comes back byte-identical to the file; `quality` moves the
   byte count only once something else has already put the request on the encoder — `quality=10`
   at `maxWidth=400` measured 4,039 bytes against 119,366 unqualified. A `quality` that
   transformed on its own would have made Atrium re-encode where the reference does not, on every
   client that appends one out of habit.* `[probe: tools/probe_image_formats.py, Jellyfin
   10.11.11, 2026-08-28]`)

EXIF orientation is not applied: 004 stored the header's dimensions, and whether the reference
rotates on resize is unmeasured — flagged (§6.8) rather than guessed.

### 6.4 Format selection

Spec §3.3's rule, operationalised:

- **Explicit `format`, one of the three measured** — `Jpg`, `Png`, `Webp` — is encoded as asked,
  `Jpg` on a transparent source included: the alpha is flattened, measured behaviour, onto white
  — the matte colour is the one part no remote request can see and the differential will.
- **`Bmp` and `Gif`** parse — they are vocabulary members `[spec: ImageFormat]` — and fall back
  to the source format **with the transform still applied**: `format=Bmp` at `maxWidth=200`
  measured a 200px JPEG out of a JPEG source *(the gate measured what this bullet had guessed)*.
  The fallback is recorded through the drop recorder (behaviours §1.12's pattern), promotable if
  the differential ever shows the reference encoding them.
- **`Svg` short-circuits the whole request**: the source bytes verbatim, the resize ignored — an
  800px source measured back whole against `maxWidth=200` *(measured at the gate; the draft had
  it falling back like the other two)*. Reproduced as measured: `format=Svg` routes to the
  verbatim path.
- **A `format` value outside the vocabulary drops** — `format=Banana` measured `200` with the
  value ignored, so behaviours §1.12's pattern wins the collision this bullet used to flag
  against spec §3.2's dimension refusals, and the parse is written lenient.
- **No `format`, a transform running, and `Accept` offering `image/webp`** → **WebP out**, with
  `Vary: Accept` on every image response either way (spec §3.3, AC-15) *(added at the gate: the
  draft rejected content negotiation in §10 and the measurement reversed it — the earlier
  probe's offer rode a request nothing transformed, and the verbatim path negotiates nothing)*.
  The offer is read as the `image/webp` token's presence in the header; `image/avif` measured
  un-negotiated; an explicit `format` beats the offer (measured).
- **No `format` otherwise** → the source format survives, measured. The spec permits serving an
  opaque source as JPEG "when materially smaller"; v1 does not take the option —
  source-format-when-unnegotiated is what the reference measurably does, and one rule fewer.
- `quality` maps to the encoder's quality for `Jpg` and `Webp` and is ignored for `Png`, whose
  encoder has no lossy knob; values outside 0–100 clamp — `quality=150` measured forgiven with
  `200`. It never puts a request on the encoder by itself (§6.3 step 5, measured at T1).
  Absent, the encoder defaults stand — goldens assert headers and dimensions, never
  encoder bytes (spec §6).
- Modes convert minimally: palette and CMYK sources convert to RGB(A) for encoding; an
  RGBA-to-RGB flatten happens only under explicit `Jpg` (above).

### 6.5 The cache, read and written

Hit: open by key, serve the bytes with the `Content-Type` its extension names, the
`Last-Modified` of the *source* carrier (§6.6) — a variant is as old as what it derives from.
Miss: resolve, transform, write via tmp-and-rename, serve from memory. An unwritable cache —
disk full, permissions — computes and serves anyway with one warning per process: degraded, never
a `5xx`, because a cache that is allowed to be deleted at any moment (spec §4) is a cache that is
allowed to never be there.

### 6.6 Headers and conditional requests

The `200` header set, explicit and complete: `Content-Type` from the payload, `Content-Length`,
`Last-Modified` — the carrier file's mtime in RFC 1123 form, the only truthful clock this feature
has (items and sources carry no wire modification time, behaviours §2.17, and the reference
demonstrably serves this pair) — `Cache-Control`: `public` bare, `public, max-age=31536000`
when the URL carries a `tag`, both values measured verbatim
`[probe: tools/probe_image_tags.py, Jellyfin 10.11.11, 2026-08-28]` — and the four constants the
gate's full dump added to this paragraph *(the draft's set was the deployment's minus everything
the probe had not asked to see)*: `Vary: Accept`, `Content-Disposition: attachment`,
`transferMode.dlna.org: Interactive`, `realTimeInfo.dlna.org: DLNA.ORG_TLAG=*` (spec §3.2, §3.4)
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
`X-Response-Time-ms` arrives from 001's middleware like everywhere else. **No `ETag`, no
`Accept-Ranges`** (spec §3.4) — and §8's header sweep asserts the set exactly, absences included.

`If-Modified-Since` parses leniently — an unparseable date is ignored, the ordinary HTTP reading,
unmeasured and low-stakes — and compares at whole-second granularity; not earlier than
`Last-Modified` answers `304` with an empty body and the `200`'s header set minus
`Content-Length` — measured in full at the gate, `Content-Type` and the DLNA pair included
(same manual-requests probe).

*(Amended at T9: this paragraph also said the conditional check "runs after the lookup and the
carrier `stat` but **before** any bytes are read or transformed — a `304` never opens an image".
That and the sentence before it cannot both hold. The `200`'s `Content-Type` is a property of the
payload that would have been sent, so a `304` carrying it has to know what that payload is — and
the reference does exactly that: a conditional request offering `image/webp` on a resized image
answers `304` with `Content-Type: image/webp`, and the same request without the offer answers
`image/jpeg` `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. So the
answer is resolved and the body is dropped, which after the first request is a cache read rather
than an encode. The refusals still come first: a conditional header cannot turn a `404` into a
`304`. The lenient parse is measured now too — `If-Modified-Since: banana` answers `200`.)*

**One measured header is deliberately not reproduced: `Last-Modified` on a *transformed*
response.** The reference sends the variant's own creation time — a resized poster whose source
file dates from 2026-08-11 came back with `Last-Modified` one second **after** that response's own
`Date`, because the value is the cache entry's mtime and the entry had just been written
`[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`. Atrium sends the
**carrier's** mtime on every path, variants included. The argument is behaviours §3.0.3's shape of
a safe divergence: both are valid validators for the same entity, no client compares a server's
`Last-Modified` against an expectation, and Atrium's is strictly the more useful one — it survives
a cache wipe, so a client's stored copy stays valid where the reference's would force a
re-download of every poster. Reproducing the reference's would also make the header
**non-deterministic**, which is the one thing spec §6 pins goldens against.

### 6.7 The wire and the recorder

The routes declare, with the pinned spellings: `maxWidth`, `maxHeight`, `width`, `height`,
`fillWidth`, `fillHeight`, `quality`, `format`, `tag`, and `imageIndex` on the unindexed form
`[spec: GetItemImage]`. Canonicalisation and the `api_key` seeding arrive from 005 §6.12 for free
— the startup walk covers every registered route, and its all-routes test already enforces that.

**The five decoration parameters stay undeclared on purpose.** `percentPlayed`, `unplayedCount`,
`blur`, `backgroundColor` and `foregroundLayer` are the spec's declared v1 gap (§3.2), and an
undeclared parameter is exactly what the ignored-parameter recorder counts per
`(route, parameter)` — so OQ-4's measurable trail exists without one line of image code, and
010's differential reads the same record it reads for every other Tier-3-shaped promise.

Unparseable declared values — `maxWidth=banana`, `quality=banana` — fail validation into
`compat/errors`' problem-details `400`, which is the measured refusal (spec §3.2, the one
non-lenient path). **No range constraints on the dimension parameters**: `-100` must parse and be
forgiven (§6.3 step 1), so a `ge=0` bound would manufacture a `400` the reference does not send.

### 6.8 Measured at the gate, and what stays owed

This section listed six edges no probe had covered. The gate measured them before accepting the
plan `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`, and the
answers are folded into §§6.1–6.6 and back into the spec: invalid tokens change nothing (§1
stands as written), `format` outside the vocabulary drops while `Bmp`/`Gif` fall back
mid-transform and `Svg` goes verbatim, both-axes `width`+`height` distorts, **fill covers and
never crops** (AC-6 corrected), a transformed response **negotiates `Accept: image/webp`**
(AC-15 added — the finding the draft's own §10 had argued against), the error bodies split into
problem details and behaviours §1.11's fourth shape, the `304`'s header set is the `200`'s minus
`Content-Length`, and the query-spelling `imageIndex` selects the backdrop it names.

What the sweep could not reach stays owed:

1. **EXIF orientation** on resize needs a planted file in a controlled library — a task with the
   fixture library, or 010's differential, owns it.
2. **A disabled account's token** is entailed by the unknown-token result — a route that
   validated anything would have refused that too — and stays on 002's standing list (its OQ-5
   reason: measuring it costs somebody an account) rather than being re-argued here.
3. ~~**The two cells `probe_image_formats.py` was blind to** — non-square fill and the `Accept`
   offer on a transformed request — are owed to the committed probe by the task list, so the
   next measurement of this route does not depend on this gate's scratch scripts.~~ **Paid at
   T1**, 2026-08-28: the script grew both batteries, confirmed both against this document, and
   found a third thing nobody had asked for — §6.3 steps 1 and 5, behaviours §1.17. The spec's
   fill and negotiation citations now name the script.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| Malformed `itemId`, unparseable dimension or `quality` | Validation | Problem-details `400` (measured status; body §6.8) | Client fixes the request |
| `imageType` outside the vocabulary | Route validation | `400` (measured) | — |
| Unknown or soft-removed item | §6.1 lookup | Problem-details `404` (measured) | — |
| Item found, image absent: no row, index out of range, a vocabulary member v1 never stores, a chapter without a thumbnail | §6.1 lookup | `404`, behaviours §1.11's fourth shape — the JSON string naming the item and the type, the measured split of one route's two lookups | — |
| Row exists, carrier file missing or unreadable | The open fails | The absent-image `404` above, plus a structured warning naming the path | The next scan removes or re-associates the row |
| Decode fails at transform time — corrupt since scan, or Pillow's decompression-bomb guard | Pillow raises | Serve the **source bytes verbatim**, with a warning: a full-size poster beats a hole in the grid, and the bytes were good enough to associate | Operator sees the log; rescan heals |
| Cache unwritable, disk full | `OSError` on write | Compute and serve; warn once per process | Free space; the cache rebuilds itself |
| Embedded row whose art was stripped since the scan | Extraction returns none | `404` plus warning | Next scan drops the row |
| Stale `tag` on the URL | Not a failure | `200`, current image (measured; AC-10) | Client refreshes its `ImageTags` |
| Concurrent identical transforms | — | Both compute; atomic rename converges on identical bytes | — |

## 8. Testing strategy

Fixtures are **generated, not checked in**: Pillow draws deterministic images at test time — a
1000×1500 JPEG poster, whose 2:3 ratio is what discriminates cover from fit and exact from
aspect-true, a 400px-wide one for the no-upscale case, a PNG logo with alpha, and three
backdrops of three different sizes so index selection is assertible by dimensions. Rows are seeded through the repositories with the files placed under a `tmp_path` library
root — no scan runs, 003 and 004 proved that half — except AC-2's test, which runs the real scan
twice on purpose. Embedded-art fixtures reuse 004's tag-writing helpers.

| Spec AC | Test |
|---|---|
| 1 | Seeded item with and without a poster: `ImageTags.Primary` present / `{}` — 005's emitters, reasserted as this spec's criterion |
| 2 | Scan, record the tag; touch mtime only, rescan → unchanged; change bytes, rescan → changed |
| 3 | `GET .../Images/Primary`: the bytes, `Content-Type` from content, `Content-Length` exact |
| 4 | `maxWidth=300` on 1000×1500 → decoded reply is 300×450 |
| 5 | `maxWidth=2000` on the 400px source → byte-identical to the source file |
| 6 | Fill 300×300 of the 1000×1500 poster → 300×450, cover with the overflow kept; a box past the source → the source verbatim; `width=300&height=300` → the distorted exact box beside it |
| 7 | The PNG logo resized → PNG, alpha intact; with `format=Jpg` → JPEG, opaque (explicit wins) |
| 8 | Same request twice → byte-identical; then overwrite the source file *without rescanning* and request again → still the first bytes, proving the hit never recomputed |
| 9 | `If-Modified-Since` at the sent `Last-Modified` → `304`, empty body |
| 10 | A stale `tag` → `200`, current bytes |
| 11 | Unknown item → the problem-details `404`; absent type, out-of-range index and `Box` → the string-shape `404` naming item and type (behaviours §1.11's split, held by golden bodies); a non-member string → `400` |
| 12 | Parameterised over 002 §3.1's mechanisms plus no token, an unknown and a malformed token included: `200` every time, identical bytes |
| 13 | Delete `cache/images/` between requests → same body bytes |
| 14 | An episode *with its own artwork* under a series with poster and backdrops: `SeriesPrimaryImageTag` + `SeriesId` present, `ParentBackdropImageTags` + `ParentBackdropItemId` paired row for row |
| 15 | The resized request with `Accept: image/webp` → WebP with `Vary: Accept`; the same with `format=Png` → PNG (explicit wins); the un-transformed request with the offer → source format |

Cross-cutting: a **header-set sweep** asserts the exact set on every `200` and `304` this suite
produces — `ETag` and `Accept-Ranges` absent; `Cache-Control` values verbatim; `Vary: Accept`,
`Content-Disposition: attachment` and the two DLNA constants present (§6.6) — so a framework
upgrade that adds or drops a header fails a test instead of shipping a delta. The resize matrix of spec §6
is table-driven over §6.3's branches. Goldens store **headers and dimensions, never encoder
bytes** (spec §6); the byte-identity ACs (8, 13) compare within one run, where the encoder is
constant. `Chapter` answers `404` today by construction, and the test that pins it is the tripwire
that fails when something starts writing chapter rows — the signal to extend this feature, 005's
`UNPROBED` pattern. The L0 surface test picks both routes up from `surface.yaml` unchanged, and
the acceptance map grows its 006 rows when the feature flips to Implemented — the lesson 003 T21
paid for. The suite's no-TCP guard already applies; every measurement in §6.8 is a `tools/` probe
or a hand request, never a test.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Encoder output drifts across Pillow versions | High | Low — goldens pin headers and dimensions, not bytes | Spec §6 chose this shape; within-run ACs cover identity |
| A convenience response class reintroduces `ETag` | Medium | High — a validator delta on every image | Plain `Response` only; the header-set sweep fails any addition |
| CPU-bound transforms stall the event loop | Medium | Medium | Sync-`def` routes run in the framework's threadpool; the cache bounds repeat cost; pool tuning waits for a measurement, not a fear |
| Unbounded cache growth | Medium | Low — disk, disposable | AC-13 proves deleting is free; eviction is recorded future work |
| A crafted row escapes a root | Low | High | §6.2's containment check, with a hostile-row test proving the refusal |
| The §6.8 leftovers land wrong by assumption | Low | Medium | The list shrank to what a remote request cannot reach; EXIF and the probe's two owed cells are named task-list items |
| mtime granularity makes `304` flap around an edit | Low | Low | Whole-second compare; the tag mechanism, not the validator, carries real invalidation |

## 10. Alternatives considered

**`FileResponse` / a static mount.** Free streaming, zero-copy sends — and it emits the exact
validator the reference never sends, plus its own `Content-Disposition` habits. Suppressing
headers across a convenience class is more code and less legible than building a four-header set
explicitly on a route that serves complete small payloads anyway.

**An `ETag` beside `Last-Modified`.** Better HTTP, strictly — and a delta by construction on
every image response. The tag-in-URL mechanism already gives clients immutability where they want
it, and spec §3.4 records the reference sending none. A non-improvement in the behaviours §6
sense: good idea, wrong project.

**Ignoring `Accept`.** The draft of this paragraph rejected content negotiation — §3.3's rule
read as parameter-driven only, and a server that varies where the reference does not is a delta —
which was the right argument pointed at the wrong server. Measured at the gate, the reference
**does** negotiate: a transformed response comes back WebP when the header offers it, under a
`Vary: Accept` it sends on every image response. The rejected alternative was the delta — every
browser-based client makes the offer on every poster it loads. The measured rule lives in §6.4;
this paragraph stays as the record of a rejection reversed by one request, which is what §10
exists to catch.

**Deriving `Last-Modified` from the database.** No image row stores a timestamp, items carry no
modification time at all (behaviours §2.17), and inventing a column would add schema for a value
the filesystem already answers truthfully. The carrier's mtime survives rescans that change
nothing, which is exactly the stability the validator wants.

**Materialising embedded art to disk at scan time.** Uniform serving, one reading fewer — and it
duplicates bytes the library already holds, adds a write path 004 deliberately does not have, and
optimises a per-request tag parse nothing has measured as slow. Revisit with numbers, per §9's
threadpool row.

**Caching resized variants in the database.** One store, transactional — and megabytes of
disposable blobs in the WAL, backup weight for state the spec says may vanish at any moment. The
filesystem is already a byte store with atomic rename; the cache needs nothing more.

**Recomputing tags at serve time.** Self-healing if a file changes under a stale row — and it
reads every byte of every image on every miss to defend against a state the next scan repairs
anyway. The stored tag is the contract 005 already emitted; serving disagrees with it never.
