---
feature: 009-playlists
title: Playlists — implementation plan
status: Implemented
created: 2026-08-31
updated: 2026-09-04
accepted: 2026-08-31
amended: 2026-08-31 at the tasks gate — §1 priced "a playlist is a row in `items`" at one migration; it is one migration, three maps that assert themselves total over a type set, and one clause. The clause is the finding: `_visible_to` exempts rows with no library, a playlist has none, so `/Items?includeItemTypes=Playlist` would have answered every user's private playlists to everybody. §6.5 gains it, and 005's own `MEDIA_TYPE_OF` docstring turns out to have said why `Playlist` was left out of `ItemType` in the first place; and 2026-08-31 by T1 — §6.4's block, executed as written, produces the reading spec §3.5 measured as **wrong**: it removed the entry from `full` and not from `visible`, so the visible neighbour is one too early and the discriminating pair gives `B C A D E`. Both removals now, and `>=` where it said `==`. And its claim to *"reproduce the observable result"* is true only where the caller sees everything: the reference takes the neighbour's position **before** the removal, so on a list with anything hidden a downward move lands one short of where the caller asked — unreachable for the set Atrium hides, which makes the two-list rule Atrium's own rather than a reproduction, and makes an entry the caller cannot see unaddressable. The thirty (source, target) pairs the 25-row matrix was modelling from one measured pair are measured; and 2026-08-31 by T3 — §1's *three* structures total over the type set are **five**, and the two it missed are assertions rather than maps: the domain's two-way partition of `ItemType`, and `test_migration_0003.py` inserting one row of every type against the constraint 0008 replaces. §4.2 gains why `media_type` is a column rather than a lookup — measured, the reference fixes the value at creation and never revises it — and the one reader that cannot use the column: `mediaTypes=` filters playlists by the row on the reference and by the type here, which T4 hands to T6; and 2026-08-31 by T4 — §4's rebuild is not merely "a risk", it is a **measured** loss: with the foreign-key pragma on, batch mode's `DROP TABLE` cascades every child row of `items` away in silence, and two module docstrings said the opposite. Migrations now run with foreign keys off and an explicit orphan check, §9's first risk is marked fired, and the two clauses T3 could not place have owners: the stored `media_type` preference is T4's (§4.2) and the `mediaTypes=` filter is T6's; and 2026-08-31 by T8 — §6.1's step 1 said a body with no `Name` is refused *"in the validation shape, keyed on the property"*. It is keyed **`$`**: the deserialiser refuses the document before any property is validated, and the property key is a different refusal the section did not have (`Name` present and null), with a third key — the empty string — for a malformed identifier. None of the three carries the action-parameter row behaviours §1.11 attributed to every body refusal; that row belongs to a **required** body and this route's is optional. §6.1 also gains the four inputs it never mentioned: `name`, `ids`, `userId` and `mediaType` are query parameters as well as body properties, the query wins, and a request naming a name in neither is the reference's `500` — refused here as a `400` in the same bytes, behaviours §3.19 and 2026-09-01 by T10 — §6.2's expansion is written, and it is three queries and a predicate rather than the one line the block describes. The predicate is `FILE_BACKED`: the three types a file produces are the leaves and everything else holds something, which is wider than the five kinds spec §3.4 listed — a plain folder, a library root and another playlist expand too. The three shapes are a folder's children query in the folder's own order, a by-name link query for an artist or a music genre whose middle ordering key **cannot** be a `sortBy` token and is therefore applied to the rows after they are read, and `PlaylistRepository.entries` for a nested playlist. And the expansion decides the media type at creation, which §6.1 step 3 did not know: the walk settles from what an id expanded to, with four containers answering from their kind first — the only way `Video` can be settled by a container that expands to nothing and 2026-09-01 by T11 — §6.4.1 named two properties of the refusal that are parity and missed the one that decides where the block runs: the caller is judged **before** the index, measured, so a reader without `CanEdit` naming an index the reference crashes on is answered `403` and not `500`. §6.4.1 says so, and adds the third class of entry id it did not have — the segment is never parsed, so an all-zeros, a malformed and a dashed entry id are all entries the playlist does not hold rather than refusals; and 2026-09-01 at the closing audit — §8's table had gone stale in four places while §6 was kept current: it counted nineteen criteria where there are twenty, named a `tests/unit/test_playlists.py` that was never written (the unit half of AC-5 and AC-6 is `test_playlist_repository.py`), still described the move matrix as the twenty-five rows this plan modelled rather than the thirty T1 measured, and still planned a `404` for a request naming the playlist's owner — which is the 25-byte `403` AC-15 was corrected to at T14. Corrected in place; no behaviour is affected, and the rows are the record of what the plan expected; and 2026-09-04 by the 2026-09-04 audit's H3, the first amendment here that no task of this feature made — §5 stated *"Every read takes a `User` and there is no variant that does not"* and listed eight methods where the class has nine, while §6.6 had described the ninth correctly since T12 wrote it. The invariant is restated with its one named exception rather than deleted, `by_id_for_deletion` joins §5's block, and §2's and §9's copies of the same sentence move with it. No code and no acceptance criterion moves; the test module's own summary of the invariant is corrected in the same commit
spec_status_required: Accepted
spec_status_actual: Implemented
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
this decision is paid in migration 0008, in three maps and in one clause: two check constraints on
`items` were written when `Playlist` did not exist and both have to be rebuilt (§4); three
structures assert themselves total over a type set and all three break when the enum gains a
member; and `_visible_to`'s library clause **exempts rows with no library**, which a playlist is.

> *This paragraph said "migration 0008 and nowhere else" until the task list was written against
> the code it names. The exemption is the one that mattered: left alone, `/Items?includeItemTypes=Playlist`
> would have answered every user's private playlists to everybody, and AC-15 would have failed in
> the leaking direction. `tasks.md`'s gate section carries all three.*
>
> *And the count moved again at T3, which is the task that added the member.* **Five** structures
> assert themselves total over the type set, not three. The two the gate did not enumerate are both
> assertions rather than maps, which is why reading the maps did not find them: the domain's own
> partition — *every type is in the tree or is a by-name row, and nothing is in both* — has no room
> for a third kind of thing, and `test_migration_0003.py` inserts **one row of every `ItemType`**
> against 0003's type constraint, which is the constraint 0008 replaces. The first becomes a
> three-way partition over a named `USER_CREATED` set; the second splits into *0003 accepts the
> thirteen it lists and refuses the one it does not*, so the accounting stays total instead of
> shrinking. A fifteenth type still breaks both.*

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
one entries read, it takes a `User`, and the one door that skips the filter is named there and
argued for in §6.6 — it reads no entries, and the route it serves is the one the reference itself
makes disclose.

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
§3.7. **A fourth was measured at T7**: [§3.18](../../docs/compatibility/behaviours.md), the
de-duplication that misses about a third of the time, specified in 009 §3.1 and §3.4.

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

> **T2 measured the change's blast radius and it is wider than this section assumed (2026-08-31).**
> Three corrections, none of which reverse the decision above:
>
> 1. **The reference has two `403` shapes**, and this section describes one. The refusal spec §3.8
>    measures — an elevated controller turning a non-administrator away — carries **no content type
>    and no body**, because an authorization policy answers it before any controller runs
>    `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`. §6's rename
>    (T13) therefore cannot raise `ForbiddenError` once `ForbiddenError` carries the sentence, and
>    the definition of done's *"`ForbiddenError`'s body is the reference's"* is true of the
>    controller shape alone.
> 2. **The content type was unmeasured on both** until T2 asked for it. The probe this section
>    cites printed forty bytes of body and no headers, which cannot tell an empty body from a
>    body-less refusal — so the shape this gate decided to copy was two thirds measured.
> 3. **One of 002 OQ-5's three does share the handler.** `api/deps.py`'s refusal of a live token
>    whose account was disabled afterwards is OQ-5's third row, and it moved from the empty shape
>    to the sentence with the handler — one analogy for another, still unmeasured. Beside it,
>    `api/users.py` refuses one user reading another where **the reference answers `200`** with
>    that user's whole object. Both are recorded in behaviours §1.11 and neither is 009's to
>    decide.

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

**`media_type` is a column and not a lookup, and T3 measured why.** The reference decides the value
at creation and never revises it — a playlist created empty answers `Audio` after a film is added
to it — so the column reproduces the reference exactly, where a value derived from the entries at
read time would not `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`.
The type-level fallback in `MEDIA_TYPE_OF` is the answer for a playlist created empty and wrong for
every other, so the item body prefers this column and the map is the default behind it. **Which
task writes that preference was an ordering question, and the answer is T4**: T3 was to write it
and could not — the column it reads is T4's — so it moved to the task that creates the column.
`HydratedItem` carries the stored value and `api/item_dto.py`'s `MediaType` emitter prefers it,
with the map as the fallback behind it; T7's repository is what fills it in.

**One reader is left on the fallback, and it is named rather than fixed here.** `mediaTypes=` is
answered by inverting `MEDIA_TYPE_OF` into a list of item types, which cannot express a value that
varies per row: measured, the reference returns an audio playlist for `mediaTypes=Audio` and a
video one for `mediaTypes=Video`, where Atrium would claim every playlist for `Audio` and none for
`Video`. Nothing can observe it before this table exists, and no analysed client sends the pair.
**T6 owns it as of T4**: it is the task that already edits `_visible_to` in that same module, and
it sits before every route that could expose the difference. Whether it closes the gap with a
clause or accepts it stays that task's call — spec §4 states both.

> **T6 closed it, and found that "the item body prefers this column" had no writer on the listing
> path.** The preference §4.2 describes is real and `api/item_dto.py` makes it, but the field it
> prefers is filled by *the repository that produced the row* — and this paragraph's "T7's
> repository is what fills it in" is true only of the playlist routes. `/Items` hydrates through
> `ItemQueries._hydrate`, which nobody told, so every playlist listed there fell through to
> `MEDIA_TYPE_OF[Playlist]` and reported `Audio`. The filter and the body would then have
> disagreed on the same response, which is a worse answer than either gap alone: `_hydrate` gains
> one statement for the page, unconditional like its neighbours, and the hydration budget moves
> from eighteen to nineteen.
>
> **And the clause compares the row rather than the two values the row is expected to hold**,
> because the reference has a third: measured, `mediaTypes=Unknown` over playlists returns one
> `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`. Spec §4 carries
> where that value comes from and why Atrium's column cannot hold it.

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
    def __init__(self, session: OrmSession, queries: ItemQueryRepository) -> None
    def by_id(self, playlist_id: str, user: User) -> Playlist | None
    def by_id_for_deletion(self, playlist_id: str) -> Playlist | None  # no filter at all (§6.6)
    def entries(self, playlist_id: str, user: User) -> list[str]      # item ids, in order
    def create(self, playlist: Playlist, item_keys: Sequence[str]) -> Playlist
    def append(self, playlist_id: str, item_keys: Sequence[str]) -> int
    def remove(self, playlist_id: str, item_keys: Sequence[str]) -> None
    def reorder(self, playlist_id: str, entry: str, new_index: int, visible: Sequence[str]) -> None
    def rename(self, playlist_id: str, name: str) -> None
    def delete(self, playlist_id: str) -> None
```

> **Two of those lines are T7's corrections, and both were forced by this section's own rule
> (2026-08-31).**
>
> **`reorder` takes the move, not the moved order.** The block first read
> `reorder(playlist_id, order)`, with the caller computing `moved(...)` and passing the result in —
> and the caller cannot, because `moved`'s first argument is the **stored** order, which is
> precisely the read this section forbids handing out. Adding "the whole order, unfiltered" to the
> surface next to a read that filters is the risk in §9 spelled out. So the arithmetic runs inside
> the repository, which also makes the read and the write it depends on one transaction rather than
> two requests apart.
>
> **The constructor is given the one visibility predicate rather than writing a second one.**
> `db/item_queries.py` imports this module, so importing it back is a cycle; the repository is
> handed an `ItemQueryRepository` and asks it `visible_ids`, which is that module's only public
> door onto `_visible_to`. The alternative — "not removed, and in a library this user may open",
> written again here — is the two-predicates-in-two-places failure `item_queries.py`'s own
> docstring opens with.

**And `by_id`'s `User` is an existence filter, not the decision.** It answers spec §3.3's `404`
before `403` for a caller who may not read the playlist — **and it hands the row to an
administrator anyway**, which looks like a hole and is what makes §6.6 writable: deletion is the
one operation an administrator may perform on a playlist they neither own nor are shared (spec
§3.6), so a door filtered by `may_read` alone would answer `404` to the one caller who must
succeed. Every read route still applies `may_read` to what comes back.

**Every read takes a `User` except `by_id_for_deletion`, which is named here, argued for in §6.6,
and the only one there will ever be without another argument.** That is the invariant this feature
is most likely to lose: a helper added later that reads entries "just for the count" is how §3.17's
divergence stops applying to one route. The exception is not that helper and could not become one —
it reads no entries, it serves the single route entitled to it, and the reason it takes no reader
is that `DELETE /Items/{itemId}` applies no visibility test to a playlist, so a `User` on that
signature would be either unused or a divergence
`[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`. `entries` returns what that
user may see, in order, already filtered by `_library_permitted`; the stored order never leaves the
class, which is why `reorder` takes the move rather than the result of one. The classification is
asserted by reflection in `tests/unit/test_playlist_repository.py` in **three** sets — `READS`,
`WRITES` and `UNFILTERED_READS` — so a tenth method has to declare which of the three it is before
the suite is green, and the third set is held as tightly as the first: a method in it that grew a
`User` would fail just as a read that lost one does.

> **Corrected on 2026-09-04 by the 2026-09-04 audit's H3.** The paragraph above read *"Every read
> takes a `User` and there is no variant that does not"*, and the block above it listed eight
> methods where the class has nine — `by_id_for_deletion` was in neither, though §6.6 has described
> it correctly since T12 wrote it and its own docstring calls it *"the third read, and the only one
> that takes no reader"*. **The code is right and this section was wrong**: the unfiltered door is a
> measured parity behaviour, not a visibility leak, and it discloses nothing `by_id` would have
> hidden except on the one route the reference itself makes disclose. The sentence is restated
> rather than deleted, because §9 nominates this invariant as the feature's likeliest loss and a
> reader who is told the watch has been kept stops watching — which is the failure the audit
> weighted it high for. The exception is now visible where a reader looks for the rule, and the
> three sets it is classified into are named where the two were.

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

> **Step 1 belongs to the model and its key does not follow from that, which is T8's finding
> (2026-08-31).** *"The shape follows from `Name` being a required field"* is the sentence that was
> wrong: the framework here keys a missing body property on the property, and the reference keys it
> on **`$`** — the deserialiser refusing the whole document, with a sentence naming the type it was
> building. The property key is a *different* refusal, `Name` present and `null`, which neither
> document had asked about; and a malformed identifier is a third, keyed with the empty string.
> None of the three carries the action-parameter row behaviours §1.11 attributed to every body
> refusal, because that row belongs to a **required** body and this route's is optional. So the
> model layer still produces all three and `compat/errors.py` spells them: the two reference type
> names are declared on the model (`WIRE_TYPE`, `WIRE_ENUM_TYPES`) and the handler stays global.
> `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`
>
> **And the route has four inputs the section did not mention.** `name`, `ids`, `userId` and
> `mediaType` are query parameters as well as body properties, the query wins, and `?name=` with no
> body at all creates a playlist — so the route declares all four and merges them **after** the body
> binds, which is the order the reference has: a query `name` does not rescue a body that fails to
> deserialise. A request naming no name in either source is the reference's `500` and Atrium's
> `400` in the same bytes (behaviours §3.19), and `?mediaType=Nonsense` is dropped and recorded
> where the body's is refused.
>
> **Step 5's expansion is not here yet.** §6.2's one function serves creation and addition, and it
> arrives with the addition route at T10 — so until then a container named in `Ids` becomes an entry
> of its own and settles the media type from itself. The `403` for a `UserId` naming another user
> **is** here: it is `effective_user`, the same helper 005 uses, measured on this route rather than
> inferred from the add route beside it
> `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`.

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

> **Written at T10, and it is three queries rather than one — plus the predicate, which is
> `FILE_BACKED` (2026-09-01).** *"Is this a container"* has an answer already in the domain: the
> three types a **file** produces are the leaves, and everything else this server can name holds
> something. That matters, because the five kinds the spec listed are not the width: measured, a
> plain folder, **a library root** and **another playlist** expand too
> `[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-09-01]`, and a rule written
> from the list would have put a whole library in a playlist as one row.
>
> The three shapes are the reference's own
> `[source: MediaBrowser.Controller/Playlists/Playlist.cs:193-231 @ v10.11.11]`:
>
> - **a folder** — `ItemQuery(parent_id=…, recursive=True, media_types={Audio, Video})`, whose
>   default ordering *is* `/Items?parentId=`'s and therefore the album's own. Recursive, so a
>   series answers episodes and not seasons, and the media-type filter is what drops the
>   containers among the descendants;
> - **an artist or a music genre** — the by-name link query, `artist_ids` or `genre_ids` with
>   `include_types={Audio}`, ordered album artist, then album, then sort name. **The middle key is
>   not a `sortBy` token**, and adding a ninth member to that enum would put an ordering on the
>   wire that no reference server has, so the rows are ordered after they are read, off the
>   grandparent and parent an audio row already carries. Measured against the reference's own
>   query and against the tree walk it is *not*: forty-two rows to forty;
> - **a playlist** — `PlaylistRepository.entries`, the one container whose children are not in the
>   item tree. It filters by the reader, like every other read on that class.
>
> **And expansion decides the media type at creation**, which §6.1 step 3 did not know: the walk
> settles from what an id **expanded to** rather than from the id, because a series' own media
> type is `Unknown` and a series in `Ids` creates a `Video` playlist. Four containers answer from
> their kind first — three music ones `Audio` and a `Genre` `Video`
> `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:95-114 @ v10.11.11]` — which
> is the only way `Video` can be settled by a container that expands to nothing.
>
> **One identifier is refused before any of this**: an id of all zeros, on both write routes and
> on creation, in the bare-text `400` (spec §3.4). It sits in the resolve step rather than in
> either route, which is where the reference has it too.

**De-duplication needs no step.** The insert is `INSERT … ON CONFLICT DO NOTHING` against
`(playlist_id, item_key)`, which drops both an item already present and a repeat inside the batch —
the reference's two stages, in one place, for the reason §1 gives.

> **It needs one, and the column that pays for it is `ordinal` (T7, 2026-08-31).** A conflicting
> insert that does nothing also does nothing with the ordinal it was going to occupy, so a playlist
> that de-duplicated by the key alone develops a **hole** in the column §6.3, §6.4 and the read all
> assume is contiguous — on the first repeated add. The batch is therefore reduced before the
> ordinals are handed out, which is also what lets `append` answer AC-5's "how many were added"
> without a second read. The key stays, and what it is for is stated correctly: it makes a
> duplicate impossible under a concurrent writer, where the reduction alone would let two requests
> race. Written without either, the reference's "silently dropped" is an `IntegrityError` — the
> constraint **refuses**, it does not drop.
>
> **First occurrence wins**, within the batch and against what is stored, and the entry already
> there keeps its position: measured, where the one-entry playlist §3.4 was measured on could not
> tell "kept" from "removed and appended"
> `[probe: tools/probe_playlist_writes.py, Jellyfin 10.11.11, 2026-08-31]`.
>
> **And the reference does not always manage it**, which is spec §3.4's fourth divergence and
> behaviours §3.18: its first stage reads an id cache that is empty until an entry has been
> resolved, so 6 of 8 identical requests duplicated. Atrium's key makes that unreachable rather
> than unlikely.

### 6.3 Removing

By entry id, several at once, and an entry id that is not present is not an error (spec §3.5).
A `DELETE` over the key, then a single renumbering pass so `ordinal` stays contiguous. Both inside
one transaction, because a reader between them would see a gap and page over it.

### 6.4 Moving: two lists, one of which is the caller's

The one piece of arithmetic this feature cannot simplify, and the reason it is pure.

The reference bounds `newIndex` against **the list the caller can see**, and rewrites the full one
`[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:289-345 @ v10.11.11]`. Atrium
reproduces the observable result and not the code (Principle IV):

```
visible  = the entries this caller may see, in order        (§6.5)
full     = every entry, in order
if `new_index` is negative or greater than len(visible):    refuse — §6.4.1
if the entry is not in `visible`:                           nothing changes
if the entry's index within `visible` is already `new_index`: nothing changes
remove the entry from `full` and from `visible`
if new_index >= len(visible):    the entry goes last in `full`
else:                            it goes immediately before `visible[new_index]`'s position in `full`
renumber `full`
```

**Both removals, and `>=` rather than `==`.** This block said *"remove the entry from `full`"* and
tested `new_index == len(visible)` until T1 ran it: with the entry still in `visible`, the visible
neighbour is one too early and the discriminating pair gives `B C A D E` — the pre-removal reading
spec §3.5 measured as **wrong**, and the exact answer `probe_playlist_move.py` exists to rule out.
The paragraph below was already assuming the reduction the block did not do.

**"Immediately before the visible neighbour" is the whole translation**, and it is what makes the
owner's case and the shared reader's case one rule: when `visible` is `full`, the neighbour's
position *is* `new_index`, and the algorithm collapses to *"insert at `new_index` after removing"* —
which is spec §3.5's measured reading, `B C D A E`. Measured on **all thirty** (source, target)
pairs of `[A B C D E]`, targets past the end included, rather than on the one pair OQ-1 asked
about `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`.

**Where the caller sees less than the whole, there is no reference answer to reproduce**, and
saying there was is the other thing this section had wrong. The reference takes the neighbour's
position in the order *before* the entry is removed and inserts after it, so a downward move of an
entry that precedes that neighbour lands one position short of where the caller asked — moving `A`
to index 2 of a list whose `C` is hidden leaves the caller looking at `A` in position 1. It fires
only for the entries *it* hides, which is a parental-rating check and never a library one
(behaviours §3.17), so it cannot fire on the set Atrium hides. The rule above is therefore Atrium's,
argued from §3.17 and from spec §6's *"the one Atrium has to get right is the filtered view its own
readers get"*, and not a reproduction of anything.

**An entry the caller cannot see is not addressable**, which the block now says in a line of its
own: it is answered exactly as an entry that is not in the playlist — `204`, nothing changes. The
reference would move it, because the list it looks the entry up in is not the list it bounded the
index against. Under §3.17 that entry is one this reader was never shown, so a client cannot have
been built on reordering it.

#### 6.4.1 The two refusals, which are this feature's third divergence

Spec §3.5's table: the reference answers `500` for an index past the entry count and `204` for a
negative one, having silently moved the entry to position 1. Atrium refuses both with `400` and
moves nothing (behaviours §3.15). Two properties of the refusal are parity and must stay:

- **The index is judged before the entry is looked up.** An entry id that is not in the playlist
  with an out-of-range index is the refusal, not the silent success — the reference's arithmetic
  reaches the bounds first, and the gate measured it.
- **An entry id that is not in the playlist, with an index in range, is `204` and changes
  nothing.** Not a `404`. This is the row the spec had wrong for the longest.
- **And "not in the playlist" is wider than it looks**, which T11 measured: the entry segment is
  never parsed, so an id of all zeros, a malformed one and a dashed spelling of a real entry's id
  are all entries the playlist does not hold. None of the three is a refusal, and the all-zeros
  guard the add route needs (`EmptyIdentifierError`) must not be reached from here.

**Two refusals happen before any of this, and their order is measured rather than deduced.** A
playlist this caller cannot see is the read route's `404`, and a caller who may not edit it is the
body-less `403` — *even with an index the reference answers `500`*
`[probe: tools/probe_playlist_shares.py, Jellyfin 10.11.11, 2026-09-01]`. So the route calls
`_editable` first and the block above second: the `400` is a refusal only a caller who may edit
can reach. The reference makes the same two tests in the same order, in the controller rather than
in the manager `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:409-431 @ v10.11.11]`.

### 6.5 Reading, and the one door

`GET /Playlists/{playlistId}/Items` is where both divergences live, and the plan's requirement is
that neither can be skipped:

1. **Who is asking** — `effective_user(users, caller, userId)`. An administrator may name anyone;
   anybody else naming another user is refused. This is 005's helper, unchanged, and it is
   behaviours §3.16.
2. **May they read it** — `may_read`, over the playlist's owner, shares and `is_public`. A playlist
   they may not read is `404`, not `403`: the reference's own visibility test in front of the
   permission test makes the `403` unreachable for anything the store holds (spec §3.3).

   **And the `404` is the fourth error shape, which this step did not say and T9 measured.** The
   body is the JSON-encoded bare string `"Playlist not found"`, 20 bytes, not the problem details
   every other `404` this project raises answers with — one body for an unknown id, for a real item
   that is not a playlist, and for a playlist this reader may not see. `compat/errors.py` gains a
   class of its own for it, deliberately **not** a `NotFoundError` subclass, because Starlette
   resolves a handler by walking the MRO and inheriting would silently restore problem details.
3. **Which entries** — the join drops entries whose item is missing or soft-deleted, and
   `_library_permitted` drops those in a library this reader may not open. That second clause is
   behaviours §3.17, and it is why `entries()` takes a `User`.

   **And the playlist row itself needs a clause of its own, one level up.** `_visible_to` composes
   four predicates, and its library one exempts a row with no library — a by-name row is not *in* a
   library, and neither is a playlist. So `/Items` needs a fourth sibling clause, written the way
   `_by_name_is_referenced` is: not a playlist, or one this caller owns, is shared with, or that is
   public. Without it the playlist route above is careful and the general listing beside it is not,
   which is the worse of the two halves to get wrong. T6.

   **The clause has no administrator branch**, and that is spec §3.7's last row rather than an
   omission: an administrator who is none of the three classes gets no read, so the predicate is
   the same for every caller and the one thing an administrator may do to a playlist they do not
   own is delete it (§6.6). `userId` therefore moves the whole predicate rather than bypassing it —
   an administrator naming a user sees that user's playlists, which is 005's rule unchanged.
4. **The envelope** — 005's, with `TotalRecordCount` counting what survived step 3 and
   `StartIndex` echoed, then `startIndex`/`limit` applied. **The count is taken before paging and
   after filtering**, which is the reference's own order and the only one that lets a client page.
5. **`PlaylistItemId` on every row** — equal to `Id` (spec §3.1). Emitted in `api/item_dto.py`,
   for this route only, because it is a property of a row *in a playlist* and not of the item.

   **The row is otherwise a list row exactly, and that is measured rather than assumed** (spec
   §3.3): the property sets differ by this one name and by nothing in the other direction. So the
   mechanism is a flag on `BuildContext` and a one-name fourth tier beside `ALWAYS`, `PER_TYPE` and
   `GATED` — not a fourth member of `Width`, which would assert a fourth measured shape where the
   measurement says there are still three. The field is declared on `BaseItemDto` immediately after
   `Id`, which is where the reference sends it and where a subclass's own fields could not go.

**No sort parameter is accepted** (spec §3.3): the route does not declare one, and the ignored-
parameter recorder that 005 uses for tier 3 has nothing to record, because there is nothing here to
ignore.

### 6.6 Deleting, and renaming

**`DELETE /Items/{itemId}`** answers six ways, and only one of them is this feature's invention:

| The item | Answer | Whose rule |
|---|---|---|
| An identifier of all zeros | `400`, the fixed 25 bytes | Parity, measured at T12 |
| A malformed identifier | `400`, the binder's validation shape keyed `itemId` | Parity, measured at T12 |
| A playlist the caller may delete (`may_delete`: owner or administrator) | `204`, no body, the row and its cascades go | Parity |
| A playlist the caller may not delete — **including one they may not read** | `401`, the 21-byte body `"Unauthorized access"` | Parity, measured at the gate and at T12 (spec §3.6) |
| Anything that is not a playlist, and the caller can see it | `403` | The divergence, behaviours §4.3 |
| Unknown, or **media** invisible to the caller | `404`, problem details | Parity |

The `401` is the row worth naming twice. It is a status this project associates with *no
credential*, and here it is the reference's answer to a perfectly authenticated caller — in the
**fourth** error shape, so one route answers `401` two ways: empty when no token reached it, and
`"Unauthorized access"` when one did. `compat/errors.py` has no class for either half of this
route, so T12 adds two — `DeletionNotPermittedError` for the parity `401` and
`MediaDeletionRefusedError` for the divergence's `403` — rather than teaching `ForbiddenError` a
second status or reusing it for its bytes.

**The order of the first two lookups is the reference's, and it is not this feature's usual one.**
A playlist is fetched through a door with **no visibility filter** (`by_id_for_deletion`, the
repository's third read and the only one that takes no `User`), because the reference applies none:
a caller who cannot read the playlist is answered `401` and not `404`, so the deletion route
discloses that it exists where §6.5's read route refuses to
`[probe: tools/probe_item_deletion.py, Jellyfin 10.11.11, 2026-09-01]`
`[source: Jellyfin.Api/Controllers/LibraryController.cs:374-383 @ v10.11.11]`. Only when the id
names no playlist does the media path run, and *that* one is filtered by the caller — which is why
one route has a disclosing refusal and a non-disclosing one at the same time.

**`POST /Items/{itemId}`** reads `Name`, on a `Playlist`, for an administrator:

| The request | Answer |
|---|---|
| Any non-administrator, on **anything** — including an id that names nothing and one that is not an id | `403`, empty — the reference's own answer, from an elevated controller, and it is refused **first** (spec §3.8) |
| An administrator, on a playlist, with a complete body | `204`; only `Name` is applied, where the reference applies seven fields more |
| An administrator, on an item that is not a playlist | `403`, empty, and §9 carries it |
| An unknown item | `404`, problem details — before the body is read |
| An id of all zeros | The bare-text `400`, as on every route that resolves an identifier |
| A body omitting `Genres`, `Tags` or `ProviderIds`, or sending one as `null` | The bare-text `400` — parity, and measured at T13 |
| A body omitting `Name`, or sending it as `null` | The same bare-text `400`, where the reference answers `204` and erases the name (behaviours §3.21) |

**Both `403`s here are the *empty* shape, and `ForbiddenError` is no longer that** (T2's finding,
§2). The reference answers this controller's refusal with no body and no content type, because an
authorization policy decides it before the controller runs
`[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]` — where the class this
plan changed now carries the 25-byte sentence. **Decided on 2026-08-31: a second exception class**,
and T10 wrote it — `EmptyForbiddenError`, because the playlist controller's own editing test sends
the same bytes for the same reason.

> **T13's three corrections, and the first makes the row above's "only `Name`" a divergence rather
> than a description (2026-09-01).**
>
> **The body is a whole item and three of its properties are required.** Dropping each of the
> thirty-nine properties a read of a playlist emits, one at a time, the reference refuses exactly
> `Genres`, `Tags` and `ProviderIds` — absent or `null` — with the controller's 25 bytes, and
> accepts a body of those three and a `Name`
> `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-09-01]`. Those three are
> checked in the route rather than declared required on the model: a required field here would
> answer the *validation* shape, which is a different refusal from the measured one.
>
> **The elevation is a dependency and not a line in the route.** A non-administrator posting to a
> path segment that is not an identifier is answered the empty `403` where an administrator is
> answered the binder's `400`, so the refusal precedes model binding — reproduced by the only
> ordering the framework offers, a sub-dependency solved before the route's own parameters
> (`api/deps.py`'s `require_administrator`). Written inside the route instead, the malformed
> identifier answers `400` and the test that says so fails.
>
> **The two new classes are `ItemUpdateError` and `MediaUpdateRefusedError`**, beside T12's pair on
> the other method of this path. The second is the *empty* `403` where the deletion's invented
> refusal is the third shape, and the asymmetry is deliberate: this route's other refusal is empty,
> so a caller cannot tell "you are not an administrator" from "that is not a playlist", and the
> deletion route has no such neighbour.

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

Twenty acceptance criteria, and the two that need the most machinery are the two matrices.

| AC | Where | Shape |
|---|---|---|
| 1, 2, 3 | `tests/conformance/test_playlists.py` | Creation: the id, the item appearing in `/Items`, the two `400` shapes as **bytes**, the empty name, the three id-list orders |
| 4 | conformance | Every row's `PlaylistItemId` **equals** its `Id` — asserted on the serialised body, because the claim is about two fields of one object |
| 5, 6 | conformance + `tests/unit/test_playlist_repository.py` | Duplicate on both paths; removal by entry id; removing an absent one |
| 7 | conformance | An album's tracks in the album's own order, the album absent; a series' episodes |
| 8 | conformance | No sort parameter changes the order |
| 9, 10, 11 | unit, table-driven | **The measured matrix**: every (source, target) pair on a five-entry playlist, plus the boundary rows. Pure, over lists of strings. T1 measured **thirty** pairs against the reference rather than the twenty-five this row planned, targets past the end included, and the test table is that transcription |
| — | unit, table-driven | **The second matrix**: the same 25 pairs on a playlist with one entry the caller cannot see, which is the case §6.4's translation exists for and the one no client will report |
| 12, 13 | conformance | Deletion by owner, by administrator, by neither (`401` with its body); the media refusal with an on-disk assertion |
| 14 | unit + conformance | `may_edit` over the four classes; one end-to-end reorder by a shared editor |
| 15, 16 | conformance | The private playlist invisible in `/Items`, `404` direct. The **`404` when the request names its owner** this row planned does not exist: that request is the 25-byte `403` `effective_user` answers everywhere, which AC-16 and AC-19 already assert, and AC-15 was corrected to it at T14. Still needs two users |
| 17 | conformance | A playlist holding an item in a library the reader cannot open: the row absent, the order and ids of the rest unchanged, `TotalRecordCount` counting only the survivors |
| 18 | conformance | Rename by an administrator; `403` for the owner who is not one, and the same `403` for that owner on an unknown and on a malformed id; the four identifier classes; the three properties the body may not omit, absent and `null`; the `Name` it may not omit; the seven fields the reference applies and this server does not |
| 19 | conformance + unit | The refusal's **bytes and content type**, on a 009 route and on `/Items?userId=`. The second is 005's route, and its test moved at T2: `test_user_id_of_somebody_else_is_the_controller_403`, asserting the 25 bytes and `text/plain`. AC-18's `403` is the **other** shape and is asserted apart |
| 20 | `tests/library/` | A playlist survives a full rescan — the one criterion that is about the scanner not touching something |

*The four rows above that read differently from what was built were corrected on 2026-09-01,
at the audit that closed the feature: the criterion count, the unit file for AC-5 and AC-6, the
size of the move matrix, and AC-15's refusal. §6 had been kept current as each was measured and
this section had not, which is the failure mode a table of tests is most prone to.*

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

> **T5 seeded five, and the two corrections are what the four could not express (2026-08-31).**
> The list above has no **public** playlist, so §3.7's fourth class — the one caller who may read a
> playlist through neither ownership nor a share — had no row in the world, and T6's own
> verification asks for one. And the two-library playlist has to be **shared with `restricted`,
> with `CanEdit`**: that reader is the only one who cannot reach every library, so without the
> share AC-17's first half has no reader at all and its second half — a `Move` indexing the list
> that reader was given — is unreachable. The public one holds the tracks and therefore carries
> `media_type` `Audio`, which is the second value §4.2's `mediaTypes=` gap needs to be visible at
> all. There is still **no administrator** in this world: AC-13, AC-16 and AC-18 build one, the way
> `tests/unit/test_items_route.py` already does, and the fixture must not claim that id.

**No probe runs in the suite.** The five that measured this feature live in `tools/` and are run by
hand; CI never contacts a Jellyfin.

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The `items` rebuild in 0008 is slow or lossy on a real library | **Fired, T4** | High — it is every item the server has | It was lossy, and not in `items`: with `PRAGMA foreign_keys=ON`, which every connection carries, a batch rebuild's `DROP TABLE` performs an implicit `DELETE FROM` that cascades **all six** child tables away in silence — measured, with `foreign_key_check` clean afterwards. Every migration now runs through `db/schema.py`'s `migration_connection`, which turns the pragma off and checks for orphans before committing; `tests/unit/test_migrations.py` asserts the loss with the guard removed |
| A later reader adds an entries query without a `User` | Medium | High — §3.17's divergence stops applying, silently, on whichever route uses it | §5's single entries read, and a test that classifies **every** public method by reflection and holds each class to its signature: a read must take a `User`, and the one unfiltered door has to be argued into `UNFILTERED_READS` on purpose rather than joining it by omission |
| The move translation is right for the owner and wrong for a shared reader | Medium | Medium — invisible until somebody shares a playlist across libraries | The second matrix in §8, which is the only thing that exercises it |
| Changing `ForbiddenError`'s body moves bytes on routes outside this feature | **Fired, T2** | Medium — 005's `/Items?userId=` and any later refusal of that class | It reached more routes than one handler's worth: the grep found a **second** test asserting the empty body (`tests/unit/test_require_user.py`, 002's disabled-token refusal), which is the exact failure this row named, and one route it reaches is one the reference does not refuse at all. AC-19 covers the measured side; §2's note carries the rest |
| The rename's `403` for a non-playlist item is a delta nobody measured | **Fired as written, T13** | Low | It shipped as described — a refusal where the reference succeeds, for a request no analysed client sends, recorded in behaviours §5. What the row did not predict is that the *playlist* case is a delta too: the reference applies seven fields beside `Name` from the same body, so the narrowing is a second gap in the same §5 row rather than a full stop after "not a playlist" |
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
