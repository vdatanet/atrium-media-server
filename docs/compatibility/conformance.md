# Proving parity

Principle VIII: a behaviour is done when a test asserts it **at the HTTP boundary**. This document
defines the four levels referenced throughout the specifications, and the machinery for each.

## The four levels

| Level | Question it answers | Needs a real Jellyfin? |
|---|---|---|
| **L0 — Routed** | Does the path exist and answer a sane status? | No |
| **L1 — Shape** | Are the fields, casing, types and units right? | No |
| **L2 — Semantic** | Are the *values* right for a known library? | No |
| **L3 — Differential** | Is it the same as what Jellyfin actually sends? | Yes |

v1 requires **L2 for every endpoint**, and **L3 for the authentication and playback paths** — the
two places where a wrong server makes a client misbehave rather than merely look wrong.

## L0 — Routed

The cheapest and most mechanical check, and it is generated, not hand-written:
`docs/compatibility/surface.yaml` lists every endpoint in v1, and the test suite asserts that each
one is registered and that no route exists outside the list.

The second half matters as much as the first — it is the automated enforcement of Principle VI. An
endpoint that appears in the router without appearing in the surface file fails CI.

Both halves are checked against **two views** of what the application serves — the OpenAPI document
the framework generates, and the route table the factory builds from its own list of routers — and
against each other. Each view has a blind spot the other covers: a route hidden from the document,
and a router included without being listed. See
[001 plan §8.5](../../specs/001-server-identity-and-discovery/plan.md#85-routes-against-surfaceyaml).

L0 also covers **what counts as the same path**. The reference matches case-insensitively and
accepts one trailing slash ([§1.14](behaviours.md#114-paths-match-case-insensitively-and-tolerate-one-trailing-slash)),
so a client that lowercases its URLs must not meet a `404` here.

## L1 — Shape

Golden-response tests. A request is issued against a fixture library, and the **raw response bytes**
are compared to a checked-in file under `tests/golden/`.

Two rules make these tests worth having:

1. **Compare bytes, not parsed objects.** Casing, `null`-versus-absent and integer-versus-string
   are all part of the contract and all invisible after parsing. A test that does
   `assert body["ItemId"] == ...` cannot fail on any of them.
2. **Golden files are reviewed, never blindly regenerated.** `--update-golden` exists, but a diff in
   a golden file is a contract change and gets read like one in review.

Two cross-cutting L1 checks apply to every route at once, because Principle I says a single lapse
breaks everything:

- **Casing sweep** — walk every registered response model and fail on any field name that is not
  PascalCase. Python's ecosystem defaults the wrong way; this makes forgetting impossible rather
  than unlikely.
- **Unit sweep** — every field whose name ends in `Ticks` must be an integer, and every field whose
  name ends in `Date` must serialise with seven fractional digits and a `Z`.

## L2 — Semantic

A fixture library with known content, checked into the repository as **metadata only**: directory
trees and `.nfo` sidecars, written from a declared manifest at test time. No copyrighted media,
ever.

**There are two fixture worlds, because they answer different questions.** The scanning library is
paths and filler bytes: 003 never opens a file, so a decodable one would have bought it nothing and
cost it a build tool. Feature 008 *does* open them — every delivery route reads bytes and every
decision reads a codec — so it brings a second world, tiny synthetic media that ffmpeg really
encodes into each container, codec and sample rate the delivery tests need, generated into a cached
directory and scanned by the real pipeline (`tests/fixtures/media.py`). Tests that reach the
binaries carry the `ffmpeg` marker; `pytest -m "not ffmpeg"` staying green is the check that they
all do.

The fixture library covers, deliberately, the cases that break naive scanners:

- A film in a folder, a film as a bare file, and a film with a year in the title.
- A series with specials (season 0), a multi-episode file, and an absolute-numbered season.
- An album split across discs, a compilation with per-track album artists, and a track whose
  embedded tags disagree with its filename.
- Non-ASCII names, names with brackets and dots, and a name that differs only by case.

L2 tests then assert real values: that the album with two discs yields one album and N tracks with
the right `ParentIndexNumber`, that resume position round-trips through ticks, that sort order
matches Jellyfin's normalisation.

## L3 — Differential

The strongest check, and the only one that can catch what we did not think to ask.

**Method:** issue the same request to Atrium and to a real Jellyfin, both pointed at libraries
built from the same fixture tree, and compare the JSON structurally.

```bash
python3 tools/differential.py \
    --atrium   http://localhost:8096 \
    --jellyfin http://your-jellyfin:8096 \
    --surface  docs/compatibility/surface.yaml \
    --report   reference/differential-report.md
```

**What it compares:** the set of keys at every level, the type of every value, and the value itself
for everything not on the allowlist.

**Which row is which row, and it is not the identifier.** The two servers derive identifiers
differently on purpose ([§1.4](behaviours.md#14-item-identifiers-are-32-lowercase-hex-characters)),
and the obvious way out — comparing by path — is not available either: the reference sends no
`Path` on a default list row at all, and asking for one changes the request under comparison and
still leaves a virtual season, a remote channel and every by-name row with nothing to join on.
`(Type, Name)` is not unique. So rows are compared **by position**, which makes the ordering part of
the contract — and where the reference's own ordering is not total
([§3.6](behaviours.md#36-ties-are-engine-resolved-and-paging-the-artist-sorts-loses-rows--class-b-diverged))
the comparison is of multisets rather than sequences.
`[probe: tools/probe_differential_join.py, Jellyfin 10.11.11, 2026-09-01]`

**A run states the identities it authenticated as.** Every probe written before 2026-09-01
authenticated as an administrator, and an administrator lacks no permission — measured, **12 of 23
reads of the surface answer differently to a restricted non-administrator**, and two of those differ
as *shorter lists* rather than as refusals, which no status comparison would see. A single-identity
run is reported as covering one identity.
`[probe: tools/probe_restricted_surface.py, Jellyfin 10.11.11, 2026-09-01]`

**And a sweep is not the whole method.** The differences a sweep cannot raise — because they need a
caller the run does not have, a library the reference cannot be given, or a comparison of something
that is not in a body — are enumerated as **named comparisons** in
[010 §3.10](../../specs/010-conformance-harness/spec.md), and an unrun one keeps a run from being
called clean.

**The allowlist** — fields that legitimately differ and are therefore compared by *shape* rather
than by value — is checked in beside the tool, and every entry needs a reason:

| Field | Why it may differ |
|---|---|
| `Id`, `ItemId`, `ServerId`, `ParentId`, `SeriesId`, … | Derivation differs by design (behaviours §1.4) |
| `DateCreated`, `DateLastSaved`, `DateLastMediaAdded` | Scan wall-clock time |
| `Etag`, `ImageTags.*` | Content hashes over differently-derived inputs |
| `Path` | Different mount points, and on the by-name rows a different installation's data directory |
| `LocalAddress` | Deliberate divergence (behaviours §4.2) |
| `X-Response-Time-ms`, and the response clock | Move on every response |
| `ChildCount` on a library view | The reference's value is a fresh random integer between 1 and 9 `[source: Emby.Server.Implementations/Dto/DtoService.cs:516-526 @ v10.11.11]` |

**A field is not the only unit a difference comes in.** Where the reference's whole answer is a
draw, no field of it is comparable: `/Items/{itemId}/Similar` and any listing ordered at random are
excused **as arrays** — their rows are not value-compared, while their key sets, types, envelope and
row count still are. Four identical `Similar` requests returned 48 distinct items with none in
common. `[probe: tools/probe_similar_ranking.py, Jellyfin 10.11.11, 2026-09-01]`

**Adding to the allowlist is a contract decision**, not a way to make a red test green. It happens
in review, with the reason written in the table.

The differential harness is **opt-in**: it needs a second server, so it is skipped when
`ATRIUM_JELLYFIN_URL` is unset, and it never runs in the default CI job. It runs on demand, and
after every bump of the pinned reference version — which is the moment its findings are worth most.

## When the reference version moves

Bumping the pinned Jellyfin version is a deliberate act with a fixed procedure:

1. Fetch the new OpenAPI document; run the surface validator. Any path or method that disappeared
   is a breaking change to record.
2. Run the full differential harness against the new server. Every new difference is triaged into
   [behaviours.md](behaviours.md) — replicate, diverge with an argument, or defer.
3. Re-run every probe script under `tools/`, and update the `Last verified` line of every document
   whose claims they support.
4. Only then change the version in [reference-target.md](reference-target.md).

A version bump that skips step 2 has not been done; it has been declared.

### The two rows move separately

[reference-target §1](reference-target.md#1-the-pinned-version) pins two things, and the procedure
above is written for moving the **behavioural** one — a *new server*, whose differences step 2
exists to find.

**When only the contract row moves — same server, a different document of it — step 2 has no
input.** Nothing behavioural changed, so there is no new difference for a differential harness to
triage; running it would compare a server against itself. The steps that do apply are 1, 3 and 4,
and they apply in full: the surface validator against the new document, every claim the repository
draws from a document re-measured against it, and only then the version changed.

This is not a licence to skip step 2 by declaring a move "document-only". The test is whether the
running reference server changed. If it did, step 2 is mandatory and no argument substitutes for
it. The one move made under this paragraph — `10.11.10` → `10.11.11` on 2026-09-01 — was made
against a server that had already been `10.11.11` for the whole project, with every one of the
repository's 515 provenance tags naming it and none naming `10.11.10`.
