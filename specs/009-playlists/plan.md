---
feature: 009-playlists
title: Playlists — implementation plan
status: Accepted
created: 2026-08-31
updated: 2026-08-31
accepted: 2026-08-31
spec_status_required: Accepted
spec_status_actual: Accepted
---

# 009 — Implementation plan

> **This document describes HOW.** The spec is the authority on behaviour, and it was measured
> before this plan started: all six of its open questions are answered by five probes that now
> exist in `tools/`, and thirteen claims died. Where this plan states a reference behaviour, the
> citation lives in the spec section it names, or inline where this plan read something the spec
> did not.

## 1. Approach

Five decisions carry the feature, and three of them are the gate's findings turned into schema
rather than into code.

**A playlist is a row in `items`, and everything 005 already does is the reason.** `Type: Playlist`
has to appear in `/Items` filtered by type, carry `UserData`, be favouritable and answer
`GET /Items/{id}` — all of which the item machinery does today for thirteen types. A second table
of playlist-shaped things would need a second query path, a second serialiser and a second
visibility predicate, and the third of those is where 009's two divergences live. So the cost of
this decision is paid in migration 0008 and nowhere else: two check constraints on `items` were
written when `Playlist` did not exist, and both have to be rebuilt (§4).

**The entry identifier is the item identifier, so de-duplication is a primary key.** This is spec
§3.1 turned into the only schema that can hold it: `playlist_entries` is keyed
`(playlist_id, item_key)` and has **no entry-identifier column**, because there is no such value on
the wire and inventing one would mean carrying a column whose only job is to be hidden. The
consequence is the feature's cheapest correctness: *adding an item already in the playlist adds
nothing* is not a rule the code applies twice (spec §3.4's two stages), it is what the key permits,
and a batch naming the same item twice collapses in the same place. The reference reached the same
behaviour by a different road — it de-duplicates in code because its identifiers left it no choice
— and both roads end at the same wire.

**The two disclosure divergences are two calls to code that already exists, and that is the whole
of them.** Spec §3.7 diverges twice: `userId` is honoured only for an administrator, and entries
the reader cannot reach are omitted. `api/items.py`'s `effective_user` is the first rule already —
it is what 005 does with the same parameter — and `ItemQueries._library_permitted` is the second,
the clause 005 puts on every listing. Neither is written here. What this plan must not do is let a
playlist read reach the database by any path that skips them, which is why §5 gives the repository
one read entry point that takes a `User` and has no variant that does not.

**The identifier is minted, not derived, and that is not a deviation.** Every other item's id comes
from `library/identity.py`'s five rules over stable facts, so that a rescan or a rebuild from an
empty database reproduces it (Principle VII). A playlist has no path, no library and no scan: spec
§4 says it is the one thing in the store that a rescan cannot rebuild, so there is nothing to
reproduce and no rule to write. `compat/guids.new_id()` is the existing answer for exactly this —
it already mints the server id, library ids, user ids and session ids, and `IdentityRule.FROM_LIBRARY`
already derives collection folders *from* a minted library id, so the chain has had a minted root
since 003. Principle VII's forbidden list is about identifiers a scan re-derives; this is not one.

**The rename is one field of one type, and the plan's job is to keep it that.** Spec §3.8 brings
`POST /Items/{itemId}` in for a rename the music client performs by posting a whole item back. The
reference's counterpart edits every field of every type; v1 reads `Name`, on a `Playlist`, for an
administrator. §6.6 says what the other two cases answer and why neither is a stub.

## 2. Inherited decisions

| Decision | Source |
|---|---|
| Everything inherited by 001–008 and 011 | [011 plan §2](../011-subtitle-delivery/plan.md#2-inherited-decisions) |
| One `items` table for everything a library holds; no path column | [003 plan §4](../003-library-configuration-and-scanning/plan.md), `db/models.py` |
| Identifiers are derived from stable facts, and the few that are not use `new_id()` | Principle VII, `compat/guids.py` |
| Per-user state is keyed on the derived identity and carries **no** foreign key to `items` | [007 plan §4](../007-user-data-and-playstate/plan.md), `db/models.py` |
| Every listing is scoped by `_library_permitted`, and by-name rows are exempt | [005 plan §6.1](../005-item-query-api/plan.md), `db/item_queries.py` |
| `userId` naming another user is an administrator-only parameter | 005 plan §7, `api/items.py` `effective_user` |
| `api/` is one module per Jellyfin controller | [architecture §1](../../docs/architecture.md#1-shape-of-the-system) |
| The four error shapes, and which layer decides which | behaviours §1.11, `compat/errors.py` |
| Repositories return domain objects; no ORM row crosses the boundary | [ADR-0003](../../docs/decisions/0003-sqlite-as-the-default-store.md) |
| Items are soft-deleted so a file that vanishes and returns costs no user state | 003 plan §6.6 |
| Never copy Jellyfin's code — the index arithmetic of §6.4 included | Principle IV |

**Deviations:** none architectural. The two divergences this feature ships are behaviours entries —
[§3.16](../../docs/compatibility/behaviours.md) (the named reader) and
[§3.17](../../docs/compatibility/behaviours.md) (the unreachable entry) — plus
[§3.15](../../docs/compatibility/behaviours.md), the two unhandled failures the reference's move
arithmetic produces. All three were measured at the spec gate and are specified in 009 §3.5 and
§3.7.

**One inherited decision is contradicted by this gate's measurement, and it is not ours to fix
quietly.** `compat/errors.py`'s `ForbiddenError` is documented as *"answered with an empty 403"*
with a `⚠️` saying the shape is unmeasured, held by [002 §7 OQ-5](../002-authentication-users-and-sessions/spec.md#7-open-questions):
no refusal of that class could be produced from an administrator account. The visibility probe
produced one — a non-administrator naming another user on `POST /Playlists/{id}/Items` — and the
reference answered `403` with the **25-byte `Error processing request.` body**, the same bytes
behaviours §2.11 measured for the authentication refusals, not an empty one
`[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`. That makes 005's
`effective_user` refusal wrong in its body today, on a route already shipped.

**Decided at this gate: 009 fixes it, where it is decided.** `ForbiddenError` gains the reference's
body, its `⚠️` docstring goes with the change that makes it false, and the spec carries the shape as
§3.7's last paragraph and AC-19. The alternative — reproducing the empty body on 009's own two
routes and leaving the handler to 002 — was rejected for the reason it was put to the user: this
feature needs that refusal twice, and a third wrong copy is worse than one changed handler. What
does **not** move is 002 OQ-5's three authentication refusals: they are a different class, each
needs a real account to fail against, and no probe here will do that to somebody's installation.

## 3. Modules

```
src/atrium/
├── api/
│   ├── playlists.py      new: the five /Playlists routes. One module per reference controller,
│   │                     so the rename does not live here — it is an ItemUpdateController route
│   └── items.py          grows two routes: DELETE /Items/{itemId} (spec §3.6) and
│                         POST /Items/{itemId} (spec §3.8), and nothing else changes
├── compat/
│   └── errors.py         one changed body: ForbiddenError answers the reference's 25 bytes
│                         instead of nothing, and loses the ⚠️ that said so (§2). It is the
│                         only file here that 005's routes also read
├── domain/
│   └── playlists.py      new, pure: Playlist, PlaylistEntry, Share, and the two index rules of
│                         §6.4. No session, no ORM, no HTTP — the arithmetic is unit-testable
│                         without a database, which is what a 25-row matrix needs
├── db/
│   ├── models.py         three new tables (§4) and `Playlist` added to two check constraints
│   ├── repositories.py   PlaylistRepository: the one read entry point, and the four writes
│   └── migrations/versions/0008_playlists.py
└── api/item_dto.py       one new emission: PlaylistItemId, on the rows of one route
```

**Why `domain/playlists.py` exists at all.** The move arithmetic is the one place this feature can
be wrong in a way no hand-written test catches (spec §6: every off-by-one passes the cases somebody
thought of). Keeping it pure means the 25-row matrix and the hidden-entry matrix run as unit tests
over lists of strings, at no database cost, and the repository is left with nothing to get wrong
but the write.

**Why not a `playlists/` package.** Three tables and one arithmetic rule do not make a subsystem.
Every other feature of this size — 007's playstate, 006's images cache — put its logic in one
domain module and its routes in one API module, and the plan that grows a package for four
functions is the plan that later has to explain the boundary.

## 4. Data model

Migration **0008**, reversible, and it does two unrelated-looking things for one reason: `Playlist`
is a type the `items` table was written to forbid.

### 4.1 The two check constraints, rebuilt

`items` carries two constraints from 0002 that both name types by hand:

- `ck_items_type` — the thirteen-value type list, which has no `Playlist`.
- `ck_items_by_name_has_no_library` — `(library_id IS NULL) = (type IN (five by-name types))`. A
  playlist has no library either, so it must join that set or the insert fails.

SQLite cannot alter a constraint in place, so both are a table rebuild:
`op.batch_alter_table("items", copy_from=..., recreate="always")`, which
[migration 0004](../../src/atrium/db/migrations/versions/0004_artist_link_is_optional.py) already
does for `item_artists`. **This is the first rebuild of a populated `items` table**, and it is the
risk row §9 opens with: a rebuild copies every row, and `items` is the table a real library fills.

> **Why a playlist joins the no-library set rather than getting one.** A playlist belongs to a
> *user*, not to a library, and the constraint's own comment says what the alternative costs: a row
> with a library appears under that library and belongs to all of them. It would also make every
> playlist visible to `_library_permitted`'s library clause, which is the predicate 009 must keep
> answering *by ownership* — the exact confusion §6.5 exists to prevent.

### 4.2 `playlists`

One row per playlist item, keyed by its item id. A side table rather than four nullable columns on
`items`, for the reason that table's own docstring gives about paths: a column that is null for
every row but one type is a column every reader has to know is null.

| Column | Type | Notes |
|---|---|---|
| `item_id` | `ID` PK, FK → `items.id` `ON DELETE CASCADE` | The playlist's own identifier, minted (§1) |
| `owner_user_id` | `ID` FK → `users.id` `ON DELETE CASCADE` | Spec §3.7's first class. A playlist without an owner cannot be reached by any rule, so the deletion cascades |
| `is_public` | `bool` not null, default false | Spec §3.7's fourth class |
| `media_type` | `str` not null | Inferred at creation when the client sends none (spec §3.2, §6.2) |

### 4.3 `playlist_entries`

| Column | Type | Notes |
|---|---|---|
| `playlist_id` | `ID` PK, FK → `playlists.item_id` `ON DELETE CASCADE` | |
| `item_key` | `ID` PK | The referenced item's identity — **and the entry's identifier** (spec §3.1) |
| `ordinal` | `int` not null | Contiguous from 0, rewritten inside the transaction that changes it |

**The primary key is the de-duplication** (§1), and it is why spec AC-5 needs no code to pass.

**No foreign key on `item_key`, deliberately, and the argument is 007's.** `item_user_data` carries
the same shape for the same reason: a file that disappears and comes back must not cost the user
anything, and under a cascade the first slow mount would empty their playlists permanently. An
entry whose item is missing or soft-deleted is dropped **at read time** by the join in §6.5, which
is also what the reference does — it drops entries whose item does not resolve before anything else
looks at them `[source: MediaBrowser.Controller/Entities/Folder.cs:1637-1643 @ v10.11.11]`.

**`ordinal` is a query pattern, not a fact.** It exists so a read is one indexed scan instead of a
recursive walk; the fact it encodes is the order of a list. It is **not** unique-constrained:
a move rewrites a contiguous range, and a unique index would force that single `UPDATE` into a
two-phase dance around a constraint that no read depends on. The index is `(playlist_id, ordinal)`,
which is the read.

### 4.4 `playlist_shares`

| Column | Type | Notes |
|---|---|---|
| `playlist_id` | `ID` PK, FK → `playlists.item_id` `ON DELETE CASCADE` | |
| `user_id` | `ID` PK, FK → `users.id` `ON DELETE CASCADE` | |
| `can_edit` | `bool` not null, default false | Spec §3.7's second and third classes |

Shares exist because the **create body** can set them (spec §3.2's `Users`), not because the
sharing routes are in scope — they are not. A table rather than a JSON column on `playlists`: the
read that needs it asks *"may this user edit this playlist"*, which is a key lookup, and the same
question inside a JSON blob is a scan of every playlist the server has.

### 4.5 What is not stored

**No `Path`, and no directory.** Spec §4 and behaviours §5's new row: the reference builds a
playlist as a directory and reports it, Atrium has nothing to report, and reporting a path no file
backs would be the worse answer.

**No entry identifier.** §4.3.

**No soft delete.** Every other item sets `removed_at` and keeps its row so its derived identity
stays associated with user data. A playlist's identity is minted, not derived, so a returning row
is not a thing that can happen: `DELETE /Items/{id}` on a playlist is a user destroying state they
created, and the row goes. Its entries and shares cascade. Its `item_user_data` rows do not — 007
owns that table and its rule is that user data outlives the item — which leaves at most a few
orphan rows per deleted playlist, keyed on an identifier no future playlist can mint. Named here
rather than fixed: it is the same shape as every other item's orphan user data, and it belongs to
whatever maintenance task eventually purges those.

## 5. Contracts

```python
# domain/playlists.py — pure
@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    owner_user_id: str
    is_public: bool
    media_type: str
    shares: tuple[Share, ...]

@dataclass(frozen=True)
class Share:
    user_id: str
    can_edit: bool

def may_read(playlist: Playlist, user: User) -> bool
def may_edit(playlist: Playlist, user: User) -> bool
def may_delete(playlist: Playlist, user: User) -> bool
def moved(order: Sequence[str], entry: str, new_index: int, visible: Sequence[str]) -> tuple[str, ...]
```

**The three permission functions are the whole of spec §3.7's table**, and they are pure so that
AC-13 and AC-14 are unit rows rather than five-request integration tests. `may_delete` is the only
one that reads `user.is_administrator`; that asymmetry is the gate's finding, and stating it as
three functions rather than one flag makes it hard to get wrong twice.

**`moved` is §6.4**, and it takes both lists on purpose: the full order and the sub-list the caller
can see. A caller who sees everything passes the same sequence twice, which is the owner's case and
almost every test's.

```python
# db/repositories.py
class PlaylistRepository:
    def by_id(self, playlist_id: str, user: User) -> Playlist | None
    def entries(self, playlist_id: str, user: User) -> list[str]      # item ids, in order
    def create(self, playlist: Playlist, item_keys: Sequence[str]) -> Playlist
    def append(self, playlist_id: str, item_keys: Sequence[str]) -> int
    def remove(self, playlist_id: str, item_keys: Sequence[str]) -> None
    def reorder(self, playlist_id: str, order: Sequence[str]) -> None
    def rename(self, playlist_id: str, name: str) -> None
    def delete(self, playlist_id: str) -> None
```

**Every read takes a `User` and there is no variant that does not.** That is the invariant this
feature is most likely to lose: a helper added later that reads entries "just for the count" is how
§3.17's divergence stops applying to one route. `entries` returns what that user may see, in order,
already filtered by `_library_permitted`; a caller that wants the unfiltered order for the move
arithmetic asks `reorder` to compute it, which is why `reorder` takes the whole order and not an
index.

**`append` returns the number of entries actually added**, which is zero for a batch that was all
duplicates. Nothing on the wire reads it — the route answers `204` either way (spec §3.4) — but the
tests for AC-5 do, and a repository that returns nothing makes them assert through a second read.

## 6. Algorithms

### 6.1 Creation, and the two refusals that are not the same shape

Spec §3.2's table, in the order the route applies it:

1. **The body binds or it does not.** A body with no `Name` property is refused by the model layer
   before the route runs, in the validation shape — problem details, `errors` keyed on the property
   (behaviours §1.11). This is not a check this feature writes: `Name` is a required field of the
   create model, and the shape follows from that. It is the first `400`.
2. **An empty or blank `Name` is accepted**, and stored as sent. There is no second check, and
   writing one would be the delta: the reference creates the playlist (spec §3.2, AC-2).
3. **`MediaType` decides whether the id list is walked at all.** When the client sends one, the ids
   are never resolved here and an unknown id is simply skipped at step 5. When it does not, the
   list is walked in order: the first id that resolves settles the media type and **stops the
   walk**; an id that does not resolve, reached before that, refuses the whole request with the
   second `400` — the bare-text shape, not the validation one. Reproduced exactly, including its
   order-dependence, because it is observable: the same two ids in the other order answer `200`.
4. **An empty playlist with no `MediaType` is `Audio`.** The reference's fallback (spec §3.2).
5. **The ids become entries** through §6.2, which is where expansion, de-duplication and unknown
   ids are handled uniformly for both paths.

> The two `400`s are two shapes on one route, and behaviours §1.11 already records that pattern for
> three others. A single "invalid request" helper would collapse them, which is why neither is one:
> step 1 belongs to the model and step 3 raises the bare-text refusal explicitly.

### 6.2 Adding: expansion first, then the key

One function serves creation and addition, because the reference reaches the same behaviour on both
paths and the gate measured both (spec §3.4).

```
for each requested id, in the order given:
    resolve it; if it resolves to nothing, skip it
    if it is a container, replace it with its playable descendants in the container's own order
    otherwise take it as itself
append each resulting id to the entry table, ordinals continuing from the current maximum
```

**Expansion is a 005 query, not a new one.** A container's playable descendants in its own order is
what `ItemQueries` answers for `/Items?parentId=`, and the gate measured that the reference's
expansion produces exactly the album's own order (spec §3.4, AC-7). Album, artist, series, season
and collection all expand; the rule is *"is this a container"*, not a list of five types, because
the measurement found the reference expanding every one of them through the same branch.

**De-duplication needs no step.** The insert is `INSERT … ON CONFLICT DO NOTHING` against
`(playlist_id, item_key)`, which drops both an item already present and a repeat inside the batch —
the reference's two stages, in one place, for the reason §1 gives.

### 6.3 Removing

By entry id, several at once, and an entry id that is not present is not an error (spec §3.5).
A `DELETE` over the key, then a single renumbering pass so `ordinal` stays contiguous. Both inside
one transaction, because a reader between them would see a gap and page over it.

### 6.4 Moving: two lists, one of which is the caller's

The one piece of arithmetic this feature cannot simplify, and the reason it is pure.

The reference removes the entry, then inserts it so that it ends at `newIndex` **of the list the
caller can see**, while the list it actually rewrites is the full one — which is why it computes
the item *before* the target position in the visible list and translates that back into the full
order `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:289-345 @ v10.11.11]`.
Atrium reproduces the observable result and not the code (Principle IV):

```
visible  = the entries this caller may see, in order        (§6.5)
full     = every entry, in order
if the entry's index within `visible` is already `new_index`: nothing changes
if `new_index` is negative or greater than len(visible):    refuse — §6.4.1
remove the entry from `full`
if new_index == len(visible):    the entry goes last in `full`
else:                            it goes immediately before `visible[new_index]`'s position in `full`
renumber `full`
```

**"Immediately before the visible neighbour" is the whole translation**, and it is what makes the
owner's case and the shared reader's case one rule: when `visible` is `full`, the neighbour's
position *is* `new_index`, and the algorithm collapses to *"insert at `new_index` after removing"* —
which is spec §3.5's measured reading, `B C D A E`.

#### 6.4.1 The two refusals, which are this feature's third divergence

Spec §3.5's table: the reference answers `500` for an index past the entry count and `204` for a
negative one, having silently moved the entry to position 1. Atrium refuses both with `400` and
moves nothing (behaviours §3.15). Two properties of the refusal are parity and must stay:

- **The index is judged before the entry is looked up.** An entry id that is not in the playlist
  with an out-of-range index is the refusal, not the silent success — the reference's arithmetic
  reaches the bounds first, and the gate measured it.
- **An entry id that is not in the playlist, with an index in range, is `204` and changes
  nothing.** Not a `404`. This is the row the spec had wrong for the longest.

### 6.5 Reading, and the one door

`GET /Playlists/{playlistId}/Items` is where both divergences live, and the plan's requirement is
that neither can be skipped:

1. **Who is asking** — `effective_user(users, caller, userId)`. An administrator may name anyone;
   anybody else naming another user is refused. This is 005's helper, unchanged, and it is
   behaviours §3.16.
2. **May they read it** — `may_read`, over the playlist's owner, shares and `is_public`. A playlist
   they may not read is `404`, not `403`: the reference's own visibility test in front of the
   permission test makes the `403` unreachable for anything the store holds (spec §3.3).
3. **Which entries** — the join drops entries whose item is missing or soft-deleted, and
   `_library_permitted` drops those in a library this reader may not open. That second clause is
   behaviours §3.17, and it is why `entries()` takes a `User`.
4. **The envelope** — 005's, with `TotalRecordCount` counting what survived step 3 and
   `StartIndex` echoed, then `startIndex`/`limit` applied. **The count is taken before paging and
   after filtering**, which is the reference's own order and the only one that lets a client page.
5. **`PlaylistItemId` on every row** — equal to `Id` (spec §3.1). Emitted in `api/item_dto.py`,
   for this route only, because it is a property of a row *in a playlist* and not of the item.

**No sort parameter is accepted** (spec §3.3): the route does not declare one, and the ignored-
parameter recorder that 005 uses for tier 3 has nothing to record, because there is nothing here to
ignore.

### 6.6 Deleting, and renaming

**`DELETE /Items/{itemId}`** answers three ways, and only one of them is this feature's invention:

| The item | Answer | Whose rule |
|---|---|---|
| A playlist the caller may delete (`may_delete`: owner or administrator) | `204`, the row and its cascades go | Parity |
| A playlist the caller may not delete | `401`, body `Unauthorized access` | Parity, measured at the gate (spec §3.6) |
| Anything whose deletion would remove a file | `403` | The divergence, behaviours §4.3 |
| Unknown, or invisible to the caller | `404` | Parity |

The `401` is the row worth naming: it is a status this project associates with *no credential*, and
here it is the reference's answer to a perfectly authenticated caller. `compat/errors.py` has no
class for it, and the route raises the refusal explicitly rather than teaching `ForbiddenError` a
second status.

**`POST /Items/{itemId}`** reads `Name`, on a `Playlist`, for an administrator:

| The request | Answer |
|---|---|
| An administrator, on a playlist | `204`; only `Name` is applied |
| Any non-administrator, on any item | `403` — the reference's own answer, from an elevated controller (spec §3.8) |
| An administrator, on an item that is not a playlist | `403`, and §9 carries it |
| An unknown item | `404` |

The third row is the one this plan decides rather than inherits. The reference would apply the
whole body to any item; v1 has no consumer for that (Principle VI) and could not honour it if it
did — 004 T10 found the scan and the refresh fighting over `Item.name`, so a renamed film would be
un-renamed by the next scan, which is precisely the plausible-looking stub Principle VI forbids.
Refusing is the honest answer, and it is bounded: it is a refusal where the reference succeeds, for
a request no analysed client sends.

## 7. Failure handling

| Failure | Detection | Response | Recovery |
|---|---|---|---|
| The `items` rebuild in 0008 fails part-way | Alembic raises; the transaction rolls back | The migration is one transaction, so the table is either old or new | Re-run; nothing partial can persist |
| An entry references an item that has been removed | The read join finds no row | The entry is omitted, exactly as an unreachable one is | The row stays; if the item returns under the same identity, so does the entry |
| Two writes to one playlist race | SQLite's write lock serialises them | The second sees the first's ordinals | None needed; every mutation renumbers inside its own transaction |
| A move whose visible list is empty | `visible` is empty and any index is out of range | `400` — §6.4.1 | — |
| The owner is deleted | `ON DELETE CASCADE` on `playlists.owner_user_id` | The playlist goes with them | Deliberate: a playlist with no owner is reachable by no rule in §3.7 |
| A container that expands to nothing is added | The expansion yields no ids | `204`, nothing added — the reference's answer for the same case | — |

## 8. Testing strategy

Nineteen acceptance criteria, and the two that need the most machinery are the two matrices.

| AC | Where | Shape |
|---|---|---|
| 1, 2, 3 | `tests/conformance/test_playlists.py` | Creation: the id, the item appearing in `/Items`, the two `400` shapes as **bytes**, the empty name, the three id-list orders |
| 4 | conformance | Every row's `PlaylistItemId` **equals** its `Id` — asserted on the serialised body, because the claim is about two fields of one object |
| 5, 6 | conformance + `tests/unit/test_playlists.py` | Duplicate on both paths; removal by entry id; removing an absent one |
| 7 | conformance | An album's tracks in the album's own order, the album absent; a series' episodes |
| 8 | conformance | No sort parameter changes the order |
| 9, 10, 11 | unit, table-driven | **The 25-row matrix**: every (source, target) pair on a five-entry playlist, plus the four boundary rows. Pure, over lists of strings |
| — | unit, table-driven | **The second matrix**: the same 25 pairs on a playlist with one entry the caller cannot see, which is the case §6.4's translation exists for and the one no client will report |
| 12, 13 | conformance | Deletion by owner, by administrator, by neither (`401` with its body); the media refusal with an on-disk assertion |
| 14 | unit + conformance | `may_edit` over the four classes; one end-to-end reorder by a shared editor |
| 15, 16 | conformance | The private playlist invisible in `/Items`, `404` direct — **and `404` when the request names its owner**, which is the divergence and needs two users |
| 17 | conformance | A playlist holding an item in a library the reader cannot open: the row absent, the order and ids of the rest unchanged, `TotalRecordCount` counting only the survivors |
| 18 | conformance | Rename by an administrator; `403` for the owner who is not one |
| 19 | conformance + unit | The refusal's **bytes**, on a 009 route and on `/Items?userId=`. The second is 005's route, and `tests/unit/test_items_route.py::test_user_id_of_somebody_else_is_the_empty_403` asserts `content == b""` today — that assertion and the test's own name move in the same change |
| 20 | `tests/library/` | A playlist survives a full rescan — the one criterion that is about the scanner not touching something |

**Fixtures — and the users this feature needs already exist.** `tests/fixtures/query.py` seeds
three: `everyone` (all three libraries), `restricted` (the movies library and nothing else) and
`nobody`. That is exactly the shape AC-15 and AC-17 want — a second non-administrator who can see
one library and not another — so the divergence tests are reachable in the world 005 built, and
this plan's first draft was wrong to budget a fixture task for them. What the world does **not**
have is playlists, which is one seeding helper: a playlist owned by `everyone`, one shared with
`restricted` with and without `CanEdit`, and one holding items from two libraries, which is AC-17's
whole case.

*This paragraph read "two users beyond the existing set … the first thing the task list should
build" until the fixtures were opened. Five criteria were said to be unreachable; none of them
were.*

**No probe runs in the suite.** The five that measured this feature live in `tools/` and are run by
hand; CI never contacts a Jellyfin.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The `items` rebuild in 0008 is slow or lossy on a real library | Medium | High — it is every item the server has | `copy_from` with the model's own definition, as 0004 did; a test that populates `items` with one row of **every** type, migrates, and asserts the rows and their indexes survive |
| A later reader adds an entries query without a `User` | Medium | High — §3.17's divergence stops applying, silently, on whichever route uses it | §5's single entry point, and a test that asserts the repository exposes no read that does not take one |
| The move translation is right for the owner and wrong for a shared reader | Medium | Medium — invisible until somebody shares a playlist across libraries | The second matrix in §8, which is the only thing that exercises it |
| Changing `ForbiddenError`'s body moves bytes on routes outside this feature | **Decided** (§2) | Medium — 005's `/Items?userId=` and any later refusal of that class | The change is one handler and one test assertion, and AC-19 covers both sides. The risk that remains is a *test* asserting the old empty body somewhere the grep misses, which is why AC-19 asserts bytes on both routes rather than one |
| The rename's `403` for a non-playlist item is a delta nobody measured | Low | Low | It is a refusal where the reference succeeds, for a request no analysed client sends; recorded in behaviours §5 when it ships |
| A client sends `Users` in the create body and expects the sharing routes | Low | Low | Shares are stored and honoured (§4.4); the routes that *read* them stay out of scope, which is spec §2 |

## 10. Alternatives considered

**A separate `playlists` table not joined to `items`.** Rejected: `Type: Playlist` has to answer
`/Items`, `UserData` and favourites, and every one of those would need a second path. The migration
cost of §4.1 is paid once; a parallel item world is paid at every query.

**An entry identifier column, hidden from the wire.** Rejected, and it was the shape this feature
was designed around until 2026-08-31. It would have bought the ability to hold one item twice — a
capability the reference does not have and a client cannot ask for — at the price of a column whose
value never leaves the server, plus the de-duplication logic the primary key now gives for free.

**A gapped `ordinal`** (1000, 2000, 3000) so a move is one `UPDATE` with no renumbering. Rejected:
it needs a rebalance pass when the gaps run out, which is more code than the renumbering it avoids,
and a playlist is tens to hundreds of rows, not millions.

**Deriving the playlist id from owner and name.** Rejected by measurement: the gate found two
playlists may carry the same name, so the derivation would collide on the reference's own permitted
input, and breaking the tie needs a discriminator that is either insertion order or a timestamp —
both of which Principle VII forbids more clearly than it forbids minting.

**Replicating the reference's `500`s on the move boundaries.** Rejected under behaviours §3.0: it is
§3.9's shape exactly — an unhandled exception on malformed input, where the well-formed input one
step away is a clean answer — and that entry diverged. A `500` teaches a client nothing, and the
negative index is worse than a `500` because it succeeds at something nobody asked for.

**Filtering entries in Python after the read.** Rejected: `_library_permitted` is a clause, the
count has to be taken after filtering and before paging (§6.5 step 4), and a Python filter over a
paged read would produce short pages and a wrong total — which is the bug the reference has, in the
one direction it does filter.
