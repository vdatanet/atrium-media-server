---
feature: 013-artist-registry
title: Artist registry — implementation plan
status: Draft
created: 2026-09-07
updated: 2026-09-07
spec_status_required: Accepted
---

# 013 — Implementation plan

> **This document describes HOW.** It may not restate WHAT: the spec is the authority on behaviour,
> and a plan that repeats it will disagree with it eventually.

**Written at the measurement gate, and the gate moved the spec.** Two of its open questions were
closed by three requests and one of them **falsified an acceptance criterion**: AC-4 called
`/Artists/AlbumArtists` a subset of `/Artists`, and `a-ha` — spelled with a U+2010 — is named as a
performer by no track and as an album artist by one album. The two routes are two populations built
from two credit fields, neither containing the other. AC-4 and §3.2 are restated, and this plan is
written against the corrected reading rather than around it
`[probe: tools/probe_artist_registry.py, Jellyfin 10.11.11, 2026-09-07]`.

## 1. Approach

**The population already exists as names; what it lacks is rows.** Every credit this server scans is
stored as a name with a nullable link — `item_artists(item_id, credit, position, name,
artist_item_id)`, revision 0004 — and the link is null exactly when the scanner made no tree artist
for that name. So the registry is not a new store: it is `ensure_by_name` applied to a field the map
in `metadata/byname.py` deliberately omits, and the link pointed at what it makes.

That one line is the whole of the behaviour change:

```python
BY_NAME_FIELD: Mapping[Field, ItemType] = {
    Field.GENRES: ItemType.GENRE,
    Field.STUDIOS: ItemType.STUDIO,
    Field.PEOPLE: ItemType.PERSON,
}
```

**What is not one line is that `MusicArtist` becomes the first type that is both.** Every other
by-name type is by-name and nothing else, and three mechanisms in this repository take that as
given. Each is listed in §4, §5 and §9, and each is a place where getting it wrong is worse than not
shipping: one of them decides **who may see an item**.

**The two decisions that were not obvious:**

1. **The registry artist carries the same type as the tree artist**, rather than a new
   `MusicArtistByName`. The wire says `MusicArtist` on both populations on the reference, and a
   type is a value a client switches on — inventing a second one to keep the schema comfortable
   would put an internal distinction on the wire. The cost lands in the constraint, where it is
   this project's to carry.
2. **`ChildCount` on a registry artist is the true count — `0` — and not the reference's number.**
   This was drafted the other way round and the measurement corrected it twice.
   [OQ-2](spec.md#7-open-questions) first read `2` on a row credited on one track and no album, and
   the draft called it [behaviours §3.25](../../docs/compatibility/behaviours.md)'s random number
   and chose to send nothing. **Both halves were wrong.** Asked twice it answers `2` then `2`, so it
   is stable and not §3.25's; and sending nothing is *"inventing a third behaviour"*, which
   [behaviours §3.0.2](../../docs/compatibility/behaviours.md#302-what-is-never-acceptable) names
   first among the things that are never acceptable.

   §3.0.2 leaves two branches, replicate or be correct, and **replicate is not available**: the
   rule behind that `2` is unknown to this reading, and a rule nobody knows cannot be reproduced —
   only guessed at. So the correct branch is taken, and correctness here is not a judgement call:
   the reference's own answer to *what is under this row* is **zero rows**, measured. A registry
   artist has no children, its child count is `0`, and this project's aggregate machinery answers
   that without being asked to.

   It is therefore a **declared divergence with a written argument**, which this plan owes
   behaviours a row for — not an allowlist entry, because an allowlist excuses a difference neither
   server chose and this one is chosen.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| A by-name identifier is derived from the type and the folded name, never allocated | [003 plan §7](../003-library-configuration-and-scanning/plan.md), `library/identity.py` |
| The fold is case plus the characters a filename cannot carry, and nothing else | [004 §3.7](../004-metadata-resolution/spec.md), `metadata/byname.py` |
| A by-name row is **derivable**: it may be deleted and recreated, and only the first-seen spelling is lost | 004, `ItemRepository.collect_by_name_garbage` |
| An identifier this project has derived is never rewritten | [003 plan §1](../003-library-configuration-and-scanning/plan.md) |
| The item builder issues no query; everything an emitter reads arrives with the page | [005 plan §5](../005-item-query-api/plan.md) |
| Schema changes are Alembic revisions, forward-only in effect and reversible in form | [architecture](../../docs/architecture.md) |

**Deviations:** none.

## 3. Modules

| Module | Change | Responsibility |
|---|---|---|
| `metadata/byname.py` | `BY_NAME_FIELD` gains `ARTISTS` and `ALBUM_ARTISTS`, both mapping to the artist type; the comment that cites §5.3 as the reason for their absence is replaced by the reading that closed it | Which by-name row a field's names become |
| `library/identity.py` | The artist type gains a **second** derivation, used by the registry, beside the per-library one the scanner keeps. `RULE_OF` stays total and one-valued: the second is reached through `for_by_name`, which the by-name writer already calls | Two derivations, one per population, neither reachable by accident |
| `db/repositories.py` | The credit writer calls `ensure_by_name` and stores the identifier it returns, so `artist_item_id` is **never null again**; `collect_by_name_garbage` is scoped to rows with no library and gains the credit table as a fifth referencing column | Writing the registry, and collecting it |
| `db/item_queries.py` | The two artist routes list the registry rather than the tree: `/Artists` over the performer credit, `/Artists/AlbumArtists` over the album-artist credit. The by-name visibility clause learns to speak about a type that is also a tree type | What each route lists, and who may see it |
| `db/migrations/versions/0009_*.py` | The constraint, and the backfill | One revision, described in §4 |
| `api/item_dto.py` | `ChildCount` stays absent on a registry artist, which the aggregate emitter already does for an item with no aggregates — asserted rather than added | Decision 2 above |

No new module. The registry is a population inside machinery that exists, which is the whole reason
this feature is small enough to be worth doing.

## 4. Data model

**One revision, `0009_artist_registry`** — the next after `0008_playlists`.

**The constraint is the change.** `ck_items_by_name_has_no_library` is a biconditional —
`(library_id IS NULL) = (type IN (…))` — and the artist type breaks it in both directions: a tree
artist has a library and a registry artist has none. The revision replaces it with the two
implications it was standing in for:

- a row of a **strictly** by-name type has no library — unchanged for `Genre`, `MusicGenre`,
  `Studio`, `Person`, `Year`;
- a row of a tree type has one — unchanged for every tree type **but the artist**, which is
  exempted by name and is the only exemption.

Written as two constraints rather than one, because a single expression naming an exemption is one a
later reader rewrites into a biconditional again.

**`item_artists.artist_item_id` becomes `NOT NULL`.** It is the column revision 0004 made nullable
with §5.3's argument written into it, and that argument is what this feature removes: every credit
name now has a row. The revision backfills it by calling the same derivation the writer will —
which is safe precisely because a by-name identifier is derived and not allocated, so the backfill
and the next scan agree without either reading the other.

**Reversible in form and lossy in effect**, which the revision says in its own docstring: `down`
restores the biconditional and the nullable column, and the registry rows it then deletes are
rebuilt by the next scan. Nothing authored is lost because nothing here is authored.

**One index**, on `item_artists (credit, artist_item_id)`: both routes group by it, and it is a
query-pattern column rather than a fact.

## 5. Contracts

```python
# metadata/byname.py — unchanged signatures, one wider map
BY_NAME_FIELD: Mapping[Field, ItemType]   # gains ARTISTS and ALBUM_ARTISTS

# db/repositories.py
def ensure_by_name(self, kind: ItemType, spelling: str) -> str: ...   # unchanged
def collect_by_name_garbage(self) -> int: ...                        # scoped to library_id IS NULL

# db/item_queries.py
ALBUM_ARTIST_CREDIT = "album_artist"
PERFORMER_CREDIT = "artist"          # exists already, beside ALBUM_ARTIST_CREDIT
```

**The invariant the rest of the system may assume:** a credit's `artist_item_id` names a row that
exists, is of the artist type, and has no library. What it may **not** assume is that the row is the
one an album hangs off — that is the tree artist, it keeps its own identifier, and the two are
different rows for the same name whenever both exist. The reference's are too.

## 6. Algorithms

**Which credit feeds which route** — the correction this gate made:

| Route | Population |
|---|---|
| `/Artists` | distinct folded names over credits whose kind is the performer credit |
| `/Artists/AlbumArtists` | distinct folded names over credits whose kind is the album-artist credit |

Neither filters the other. A name in both is one row, because the fold and the type are the key and
the credit kind is not part of it — so the two listings **share rows** without either being a subset.

**The fold is `fold_by_name` and nothing new.** Case, plus the characters a filename cannot carry,
replaced by a space. It is the fold that makes `AC/DC` and `AC DC` one registry row here — and the
reference's own two spellings, measured, are one row there and two items.

**Removal.** A registry artist is collected when no credit names it. The collector already walks the
genre, studio and person link tables and the production year; the credit table joins them, and the
walk is scoped to rows with no library so that a **tree** artist can never be collected by it. That
scoping is not an optimisation: without it, the first run of the collector after this feature would
delete every tree artist nothing references, which is 003's data.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| A credit name folds to a row of the wrong type | The type is part of the key; a wrong type is a different identifier | Impossible by construction, and asserted by a test that folds one name into two types | — |
| The backfill and the scanner disagree on an identifier | Two derivations of one fold — the failure 004 T4 recorded | Both call `for_by_name`; nothing derives a by-name identifier a second way | A rescan rewrites the links |
| The collector deletes a tree artist | An album with no parent, and a scan that recreates it | Prevented by the library scoping of §6, asserted directly | A rescan |
| A restricted account reaches an artist through a library it may not open | The by-name visibility clause is *referenced by a visible item*; the registry row has no library of its own | The clause is what decides it, and the test is adversarial | — |

## 8. Testing strategy

| Criterion | Where it becomes a test |
|---|---|
| AC-1 one row per folded performer name, including a performer who is nobody's album artist | `tests/unit/test_by_name_routes.py`, on the fixture world's guest performer — the case that module's docstring already names as §5.3's consequence |
| AC-2 one row for an artist credited in two music libraries | A second music library in the query world, which it has not got: the fixture gains one, and this is the only fixture change the feature needs |
| AC-3 two spellings, one row, first spelling shown | `tests/unit/test_by_name_routes.py`, with a name differing by case and one by a path-invalid character |
| AC-4 the album-artist listing is not a subset | The same two, asserted **both ways**: a performer with no album, and an album artist no track names |
| AC-5 the identifier answers as an item with no parent, and is the one the credits carry | `tests/unit/test_item_dto.py` and a golden body |
| AC-6 reached by credit, not by parent | `tests/unit/test_items_route.py`: `artistIds` and `albumArtistIds` answer, `parentId` answers empty |
| AC-7 **the library tree does not move** | `tests/library/test_identity.py` — every tree artist identifier unchanged — and `tests/library/test_reference_reading.py`, whose fifty declared differences are the tree and must not gain or lose a row |
| AC-8 collected when nothing credits it, and reproducible | `tests/unit/test_item_queries.py`, over two scans |

**L3 is the differential**, and the two routes carry two request cases each for both seats already
— which is what made the promotion payable on the day it was declared. The sweep's own report is
where AC-1 and AC-4 are proven against the server they were measured from.

**The goldens that move are named in the pull request**, and every one of them is a listing whose
population changed. A golden that changes for another reason is a defect this plan did not foresee.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **The visibility clause is widened, and an account reaches an artist of a library it may not open** | Low | **Severe** — a disclosure, and the one risk here that is not cosmetic | The clause is per type today and becomes per **population**; the test is adversarial and written before the clause, the way 009's playlist leak was |
| The collector's scoping is missed and tree artists are deleted | Low | Severe, and silent until the next listing | §6 states it; a test deletes nothing and asserts the tree artist survives a collection |
| Two derivations of one fold drift | Low | Rows that split in half on a rescan | Both call `for_by_name`; 004 T4 is the precedent and the reason nothing derives a second way |
| The registry's size on a real library | Certain | 684 rows where the tree holds 210 — three times, and it is the point rather than a risk | Stated so nobody reads the growth as a defect |
| `ChildCount` answers `0` where the reference sends a stable number nobody has attributed | Certain | A differential difference on every registry row | Decision 2, declared in behaviours as a divergence with its argument, not excused in the allowlist as a derivation. **The attribution was owed here and was taken at the tasks gate**: three registry artists all answer `2` while their four candidate counts differ, and the eleven album-artist rows of the same run carry `1`, `2` and `13` — so it is stable per artist, varies between artists, and matches nothing. [tasks.md](tasks.md) carries the table, and the argument is now *"replicate is unavailable because somebody looked"* rather than *"because nobody did"* |

## 10. Alternatives considered

**The identity migration §5.3 names.** Make the artist type by-name and stop the scanner creating
tree artists. It closes a third consequence nobody has been able to observe — the tree artist being
per library — and it rewrites identifiers 003 derived, which is the one operation this project does
not perform. **It also copies a shape the reference has not got:** the reference keeps both
populations, measured. Lost on both counts.

**A distinct type for the registry artist.** Comfortable in the schema and wrong on the wire: the
reference answers `MusicArtist` for both populations, and a client switches on the type. Lost.

**Rows synthesised by the route, with no items behind them.** Cheapest, and it makes `/Items/{id}`
answer nothing for a row a client just listed — which is the *"two 404s counted as coverage"* shape
010's register refuses. Measured out: a registry row **is** an item there. Lost.

**Building `/Artists` from every credit rather than the performer credit.** Simpler, a superset, and
arguably more useful to a client — and it answers eleven rows the reference does not on the library
this was measured on. A divergence chosen for convenience is the one thing Principle I does not
allow, so it is the corrected AC-4 that decides this and not the shape of the query. Lost.
