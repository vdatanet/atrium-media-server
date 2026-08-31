---
feature: 009-playlists
title: Playlists
status: Accepted
created: 2026-08-26
updated: 2026-08-31
amended: 2026-08-31 at the plan gate — §3.7 and a new AC-19 state the *bytes* of the refusal a caller gets for naming another user, which the spec gate had measured and recorded only as a status. The reference answers the 25-byte `text/plain` body every controller-level refusal carries; this server answered an empty `403` for that whole class, on the argument that it is decided where the empty `401` is, with a `⚠️` in the code saying the shape was unmeasured because no non-administrator account existed to produce one. The visibility probe made one. It is a wire difference on a route 005 already ships, so the correction is taken where the refusal is decided rather than on 009's own two routes — decided by the user at the plan gate; and 2026-08-31 by T1 — §3.5 stated the move's arithmetic for a caller who sees the whole playlist and left the other caller to §3.7. It now says both: the index is judged against the list that reader was given and the entry lands at `newIndex` **of it**, where the reference is off by one on every downward move and will reorder an entry that reader was never shown. Neither difference is reachable against a reference server — what it hides is hidden by a parental-rating check — so both belong to §3.7's divergence, and AC-17 gains the clause. Plus the provenance: all thirty (source, `newIndex`) pairs are measured where one was
depends_on: [005]
---

# 009 — Playlists

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Let a user create an ordered list of items, read it, add to it, remove from it and reorder it.

Playlists are the only place in v1 where a client **writes structure** to the server. Everything
else it writes is per-user state.

**Client behaviour unlocked:** building and editing a playlist from the app.

## 2. Scope

**In scope**

- `POST /Playlists`, `GET /Playlists/{playlistId}/Items`,
  `POST` and `DELETE /Playlists/{playlistId}/Items`,
  `POST /Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}`,
  `DELETE /Items/{itemId}` for deleting a playlist.
- `POST /Items/{itemId}` for renaming a playlist — §3.8. Added at the spec-review gate on
  2026-08-31, because it has a named consumer: it is how the music client renames a playlist
  `[client-contract: 2026-08-29, §10]`, and it was the one operation that client calls which no
  feature owned.
- Playlist entries, their identity, and why that identity is not what it looks like.
- Ownership and visibility, including the two disclosures this feature diverges on.

**Out of scope**

- `POST /Playlists/{playlistId}` (`UpdatePlaylist`) and `/Playlists/{playlistId}/Users` (sharing).
  No analysed client calls either.

  > This exclusion cost something, and the cost is written down rather than discovered later.
  > `UpdatePlaylist` is the **only** route that renames a playlist for an owner who is not an
  > administrator: the route the client actually calls refuses that owner with `403`, and this one
  > answers `204` for the same user on the same playlist.
  > `[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-08-31]` Principle VI decides
  > it anyway — an endpoint with no named consumer is not added — and the consequence is §3.8's
  > last paragraph.

- Smart or rule-based playlists.
- Reading or writing playlist files on disk. The reference keeps a playlist as a directory, and
  what of that reaches the wire is §3.2's last paragraph and §4.
- Deleting **media** through `DELETE /Items/{itemId}`. §3.6.

## 3. Behaviour

### 3.1 An entry's identifier is the item's identifier

The distinction this feature was written around does not exist, and finding that out is what the
spec-review gate was for.

**`PlaylistItemId` equals the item's own `Id`, on every row.** Measured on the wire, and the
reference's reason is visible in its source: the field the response reads from is a *cache of the
resolved item's id*, filled in the first time the entry is looked up.
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`
`[source: MediaBrowser.Controller/Entities/BaseItem.cs:1797-1802 @ v10.11.11]`

> **This section said something different until it was measured, twice.** It first claimed that a
> track could appear several times, each occurrence a distinct entry. The 2026-08-26 probe
> established that **the reference de-duplicates** (§3.4), and the section was corrected to keep
> entry identity as a real thing addressed by `Move` and `Remove`. The 2026-08-31 probe took the
> remaining half: the identifier those routes address is the item's, so there was never a second
> identifier to be distinct from.
>
> The two findings are one fact seen from two sides. An entry that cannot be named apart from its
> item cannot appear twice in a list addressed by name — so de-duplication is not a policy the
> reference chose, it is the only shape its identifiers allow.

**Atrium reproduces this**, and it is not a free choice: a `PlaylistItemId` that differed from `Id`
would be a value no reference server sends, which is Principle I's first forbidden thing. The
consequence for the plan is that an entry is addressed by the item it references, and a playlist
therefore cannot hold one item twice.

> **What this costs a client.** The music client's contract asks for a `PlaylistItemId` "distinct
> from the track id" so that it can address duplicates `[client-contract: 2026-08-29, §10]`. Half
> of that is satisfiable and half is not: the field is there on every row, and it is not distinct,
> because against a reference server there are no duplicates for it to address.

### 3.2 `POST /Playlists` — `CreatePlaylist`

**Consumers:** music-client.

**Body:** `Name`, `Ids` (initial items, may be empty), `UserId`, `MediaType`, `IsPublic`, `Users`.
`[spec: CreatePlaylistDto]` The same four of them may be sent as query parameters, which take
precedence, and the body itself is optional `[spec: CreatePlaylist]`.

`Users` is the one to notice: it carries the shares that §3.7's third class of writer is made of,
so the sharing model is reachable from this body even though the sharing routes are out of scope.

**Response — 200:** `{"Id": "<32 hex>"}` — the new playlist's item id. `[spec: PlaylistCreationResult]`

A playlist is a first-class item of `Type: Playlist`, so it appears in `/Items` queries filtered by
that type, carries `UserData`, and can be a favourite.

**Errors, as measured** `[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`:

| Request | Answer |
|---|---|
| No `Name` property at all | `400`, and the body is the validation shape of [behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one) |
| `Name` empty, or only spaces | **`200`** — the playlist is created, and carries that name |
| An id in `Ids` that does not exist, with **no** `MediaType` and no resolvable id before it | **`400`**, and the body is the bare-text shape, not the validation one |
| An id in `Ids` that does not exist, after a resolvable id, or with `MediaType` given | `200`; the unknown id is skipped |
| Unauthenticated | `401` |

> **Two of those rows were the opposite way round in this document until they were measured.** It
> claimed `400` for a missing *or empty* name and an unconditional "unknown ids are skipped". The
> empty name creates a playlist, and the skipping is conditional: with no `MediaType`, the
> reference walks the id list to infer one and refuses on the first id that does not resolve,
> stopping as soon as one does. So whether a stale id is fatal depends on where it sits in the list
> and on whether the client named a media type — which the music client does only sometimes.
> `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:88-121 @ v10.11.11]`
>
> The two `400`s are also two *shapes* on one route, which is the pattern behaviours §1.11 already
> records for three other routes: the refusal a framework produces and the refusal the handler
> produces do not look alike.

**What creation decides for the client.** `MediaType` is inferred when it is not given — `Audio`
for a playlist created empty, and the media type of the first resolvable id otherwise. Two
playlists may carry the same `Name`; they are two items.
`[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`

**The reference builds a playlist as a directory**, and three of its fields say so: `Path` is a
filesystem path under the server's data directory, and `DateCreated` and `DateModified` come from
that directory. The parent is a playlists folder that **does not appear in `/UserViews`**, so this
feature adds no view to a 005 response. §4 says what Atrium does with the three fields.
`[probe: tools/probe_playlist_creation.py, Jellyfin 10.11.11, 2026-08-31]`

### 3.3 `GET /Playlists/{playlistId}/Items` — `GetPlaylistItems`

**Consumers:** music-client, video-client.

Returns the standard list envelope (005 §3.1), with each item carrying its `PlaylistItemId` (§3.1).

**Order is the playlist's order**, and it is the point of the endpoint. **No sort parameter is
accepted**: the route takes `userId`, `startIndex`, `limit`, `fields`, `enableImages`,
`enableUserData`, `imageTypeLimit` and `enableImageTypes`, and nothing else. `[spec: GetPlaylistItems]`

> **This section claimed a `sortBy` that does not exist**, and said it applied "as a view over that
> order". Honouring a parameter the reference ignores is the kind of extension Principle I forbids
> most plainly — a client could discover it — so the correction removes a capability rather than
> adding one.

`404` for an unknown playlist, and for one the reader may not see. The `403` the route declares is
reachable only for a playlist stored outside the server's own playlists folder, because everywhere
else the visibility test in front of it has already answered `404`.
`[source: Jellyfin.Api/Controllers/PlaylistsController.cs:520-531 @ v10.11.11]`

**`userId` names the reader, and Atrium diverges on who may name it.** §3.7.

### 3.4 `POST /Playlists/{playlistId}/Items` — `AddItemToPlaylist`

**Consumers:** music-client.

Appends items, identified by media item id, to the end. `204`.

**Duplicates are silently dropped.** Adding an item already in the playlist adds nothing, and a
single request naming the same item twice adds it once. The reference de-duplicates in two stages —
against the existing entries, then within the incoming batch. `[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:222-225 @ v10.11.11]`

Measured on both paths, because they are separate code paths: creating a playlist with the same id
twice yields one entry, and adding an id already present yields zero new entries. `[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`

Atrium does the same, and §3.1 is why it is not a policy choice.

**Adding a container adds its children, and every kind of container.** Measured: an album adds its
tracks **in the album's own order**, an artist adds their tracks, a series and a season add their
episodes, and a collection adds its films. The container itself never becomes an entry.
`[probe: tools/probe_playlist_expansion.py, Jellyfin 10.11.11, 2026-08-31]`

`404` for an unknown playlist. Unknown item ids are skipped — unconditionally here, unlike §3.2's
creation path.

### 3.5 Removing and reordering

**`DELETE /Playlists/{playlistId}/Items`** removes entries by entry id, several at once, named in
`entryIds`. `204`. Removing an entry id that is not in the playlist is `204`, not an error —
clients retry, and a retry after a successful removal must not fail. `[spec: RemoveItemFromPlaylist]`

**`POST /Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}`** moves one entry to an absolute
index. `204`.

**Indices are zero-based and name the entry's position in the list _after_ the move.** The entry is
removed first, then inserted so that it ends up at exactly `newIndex` in the resulting list.

Measured with the only case that distinguishes the two readings — a downward move, index 0 to
index 3 on `[A B C D E]`:

| Reading | Result |
|---|---|
| **Post-removal / final index** — what the reference does | `B C D A E` |
| Pre-removal — insert before whatever was at index 3 | `B C A D E` |

`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-26, re-measured 2026-08-31]`

Upward moves are identical under both readings, which is why a client author can build against the
wrong one and not notice until a user drags something down. This specification asserted the wrong
reading until it was measured; the probe existed precisely because getting it wrong is invisible
until it is expensive.

**The boundaries, measured on a five-entry playlist**
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`:

| Case | The reference answers | Atrium answers |
|---|---|---|
| `newIndex` equal to the entry count | `204`, the entry goes last | The same |
| `newIndex` greater than the entry count | **`500`**, and nothing moves | `400`, and nothing moves — [behaviours §3.15](../../docs/compatibility/behaviours.md) |
| `newIndex` negative | **`204`**, and the entry moves to index 1 | `400`, and nothing moves — the same entry |
| Moving to its current index | `204`, nothing changes | The same |
| Entry id not in the playlist, index in range | **`204`**, nothing changes | The same |
| Entry id not in the playlist, index out of range | **`500`** | `400` — the index is judged before the entry is looked up, in both servers |

> **This table had four rows and one of them was right.** It claimed a clamp for anything past the
> end, `400` for a negative index and `404` for an absent entry; only *moving to its current index*
> survived. What is really there is a clamp exactly one position wide, a negative index that moves
> the entry rather than refusing it, and an absent entry that is a silent success — and, on the two
> rows nobody had thought to write, an unhandled failure, which is the divergence recorded beside
> them.

**The index is judged against what the caller can see**, and so is the position the entry lands at.
For an owner the two lists are one and the table above is the whole story. For a reader who is
shown fewer entries (§3.7) the reference is off by one on every downward move — it takes the
neighbour's position in the stored order *before* removing the entry — and it moves entries that
reader was never shown. Atrium does neither: the entry ends up at `newIndex` of the list that
reader was given, and an entry omitted from it is answered as an entry that is not in the playlist
— `204`, nothing changes. Neither difference is reachable against a reference server, because the
entries it hides are hidden by a parental-rating check and never by library access
`[source: Emby.Server.Implementations/Playlists/PlaylistManager.cs:289-345 @ v10.11.11]`; both
belong to the divergence §3.7 already carries.

Entry identifiers survive a move: the row keeps its `PlaylistItemId` — which, by §3.1, it could
hardly fail to do.

**Every pair is measured, not modelled.** All thirty of source × `newIndex` 0–5 on `[A B C D E]`,
not the one pair that distinguishes the two readings: the post-removal reading reproduces the
reference on every one of them, and the one-position clamp is a property of every source rather
than of the one the boundary table asked about.
`[probe: tools/probe_playlist_move.py, Jellyfin 10.11.11, 2026-08-31]`

### 3.6 Deleting a playlist

Through `DELETE /Items/{itemId}`, which is why that route is in v1 at all.

**This route is dangerous, and its danger is asymmetric.** For a playlist it removes server-side
state the user created. For a media item it can delete the user's file.

v1's rule: **`DELETE /Items/{itemId}` succeeds only for items whose deletion removes no file from
disk.** Deleting a playlist is permitted. Deleting a movie, an episode or a track answers `403`,
regardless of the user's `EnableContentDeletion` policy.

> This is a **deliberate divergence**, and unlike the others in this project it is not argued from
> "no client can tell" — a client *can* tell, by deleting a movie and finding it still there.
>
> It is argued from consequence. v1 has no undo, no trash, and no confirmation flow of its own; it
> would be trusting a client's confirmation dialog with an irreversible operation on files the user
> may not have backed up. The cost of the divergence is a client's delete button failing on media
> and working on playlists, and the gate measured that cost at zero for both analysed clients:
> `DeleteItem` is named by one of them and only ever for playlists.
>
> Media deletion is revisited when there is a trash with a retention window to put things in.
> Recorded in [behaviours §4.3](../../docs/compatibility/behaviours.md#43-delete-itemsitemid-refuses-to-delete-media).

**A caller who may not delete the playlist is refused with `401`, not `403`** — measured on the
owner-and-administrator rule below, with the body `"Unauthorized access"`.
`[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`
`[source: Jellyfin.Api/Controllers/LibraryController.cs:380-383 @ v10.11.11]` This document said
`403` until the gate measured it. `404` for an unknown or invisible item.

Deletion is the **one** operation an administrator may perform on a playlist they do not own.
`[source: MediaBrowser.Controller/Playlists/Playlist.cs:261-264 @ v10.11.11]`

### 3.7 Ownership and visibility

A playlist has an owner, and three classes of caller can reach it:

| Class | May read | May edit | May delete |
|---|---|---|---|
| The owner | yes | yes | yes |
| A user the playlist is shared with, `CanEdit` | yes | yes | no |
| A user the playlist is shared with, without `CanEdit` | yes | no | no |
| Anybody, when `IsPublic` | yes | no | no |
| An administrator who is none of the above | no | **no** | **yes** |

Shares are set through the create body's `Users` (§3.2), which is what puts them in scope. Measured:
a shared reader with `CanEdit` moved an entry and the owner saw the new order.
`[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`

> **The administrator row is the one this document had wrong.** It said administrators may "modify
> or delete". Every editing route tests owner-or-share and has no administrator branch; deletion is
> the only route that has one.
> `[source: Jellyfin.Api/Controllers/PlaylistsController.cs:132-134, 422-424, 461-463 @ v10.11.11]`

A non-public playlist does not appear in another user's `/Items`, and a direct fetch answers `404`.
`[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`

**Two disclosures, and Atrium diverges on both.**

**The reader can be named.** `GET /Playlists/{playlistId}/Items` takes the identity it checks
permissions against from the `userId` query parameter, with no test that the caller is entitled to
name it — so a non-administrator reads any private playlist by naming its owner. Measured: `200`,
with the entries, to a restricted user who is answered `404` by every other route on that playlist.
The **same parameter on the same controller's add route answers `403`**, through the check this one
does not make. `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`

**Atrium honours `userId` for administrators and refuses it otherwise**, which is the rule the
reference applies on its own write routes. [behaviours §3.16](../../docs/compatibility/behaviours.md)
carries the argument; the short form is that a reference that refuses on one route what it permits
on another cannot have taught a client to depend on the permissive one.

**The refusal is the reference's own, bytes included.** It is `403` carrying the 25-byte
`text/plain` body `Error processing request.` — the shape
[behaviours §1.11](../../docs/compatibility/behaviours.md#111-there-are-four-error-shapes-not-one)
gives a controller that refuses a request itself, measured here for a policy refusal for the first
time `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`. This server
answered an **empty** `403` for every refusal of that class until 009 — a body no reference server
sends, on a route 005 already ships — and 009 corrects it where it is decided rather than on its
own two routes alone.

**An entry the reader has no access to is shown anyway.** The reference filters a playlist's
entries through a parental-rating and tag check, which has nothing to do with which libraries a
user may open. Measured: a reader restricted to one library, who can list **zero** items of another
and is answered `404` fetching one directly, is handed those items as playlist rows, counted in
`TotalRecordCount`. `[probe: tools/probe_playlist_visibility.py, Jellyfin 10.11.11, 2026-08-31]`
`[source: MediaBrowser.Controller/Entities/BaseItem.cs:1736-1741 @ v10.11.11]`

**Atrium omits entries the reader cannot reach**, and the remaining entries keep their order and
their entry ids. [behaviours §3.17](../../docs/compatibility/behaviours.md) carries the argument.
The count follows the omission: `TotalRecordCount` is what the reader may see, which is what the
reference does too, on the criterion it happens to be filtering.

> **This document already asserted the omission**, as though it were the reference's behaviour, and
> the gate found it was Atrium's alone. What was a description is now a divergence with an
> argument, which is the difference between a specification and a hope.

### 3.8 `POST /Items/{itemId}` — `UpdateItem`, for renaming a playlist

**Consumers:** music-client.

The client renames a playlist by fetching the item, changing `Name`, and posting the item back
`[client-contract: 2026-08-29, §10]`. `204` on success.

**The route is administrator-only**, and that is the whole of what this section had to measure. The
reference declares the controller elevated, so:

| Caller | Answer |
|---|---|
| An administrator, on any playlist | `204`, and the name changes |
| The playlist's own owner, not an administrator | **`403`**, with an empty body |

`[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-08-31]`
`[source: Jellyfin.Api/Controllers/ItemUpdateController.cs @ v10.11.11]`

**The directory does not move.** An administrator's rename changes the item's `Name` and leaves the
path it was created under, so the two disagree from the first rename onwards
`[probe: tools/probe_playlist_rename.py, Jellyfin 10.11.11, 2026-08-31]` — which is one more
reason §4 keeps `Path` out of what Atrium promises.

`404` for an unknown item.

> **v1 routes this operation for playlists.** Its reference counterpart edits every field of every
> item type, and v1 has no consumer for any of that (Principle VI): the music client posts it at
> playlists and nothing else does. An item type nobody names is not routed here rather than being
> answered with a lie.
>
> **What the client still cannot do.** A non-administrator using that client cannot rename their own
> playlist — not against Atrium, and not against a stock reference server either, which is where
> the refusal comes from. The route that would let them is `UpdatePlaylist`, excluded by §2 for
> having no named consumer. This is a gap in the client's own feature, reproduced exactly, and it
> is recorded in [behaviours §5](../../docs/compatibility/behaviours.md) rather than fixed here.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Playlists | `Type: Playlist` items in `/Items` | Until deleted |
| Entries and their order | `GET /Playlists/{id}/Items` | Until modified |
| Entry identity | `PlaylistItemId`, equal to the item's `Id` (§3.1) | For the life of the entry |
| Ownership, shares and visibility | Whether another user sees the playlist, and what they may do | With the playlist |

Playlists are the **only** structural state in v1 that does not come from the filesystem, and
therefore the only thing in the server's store that cannot be rebuilt by a rescan. That makes them
the only thing whose loss is unrecoverable, and the plan has to treat them accordingly.

> **The reference's playlists do come from the filesystem**, and three fields carry it to the wire:
> `Path`, `DateCreated` and `DateModified` (§3.2). Atrium has no directory to report, and inventing
> a path that no file backs would be a worse answer than the honest one — so a playlist item here
> carries no `Path`, and its two dates are the ones its own store records. This is the one place
> where 009 cannot be byte-identical, it is visible only to a client that asks for `Path` by name,
> and it is recorded in [behaviours §5](../../docs/compatibility/behaviours.md).

## 5. Acceptance criteria

1. `POST /Playlists` returns an id; the playlist then appears in `/Items?IncludeItemTypes=Playlist`.
2. Creating with an empty `Name` **succeeds**, and the playlist carries the empty name; creating
   with no `Name` property at all answers `400` in the validation shape.
3. Creating with an unknown id **after** a resolvable one succeeds and skips it; creating with an
   unknown id **first** and no `MediaType` answers `400`; supplying `MediaType` makes it succeed.
4. Every item from `GET /Playlists/{id}/Items` carries a `PlaylistItemId`, and it is equal to that
   item's `Id`.
5. Adding an item already in the playlist adds nothing, and one request naming it twice adds it
   once — on both the creation and the addition paths.
6. Removing by entry id removes exactly that row; removing an entry id that is not present
   answers `204`.
7. Adding an album adds its tracks in the album's own order, and the album itself is not an entry;
   adding a series adds its episodes.
8. `GET /Playlists/{id}/Items` accepts no sort parameter, and the order it returns is the
   playlist's.
9. Moving an entry from index 0 to index 3 on a five-entry playlist produces `B C D A E` — the
   entry ends up **at** `newIndex` in the resulting list — and every entry keeps its
   `PlaylistItemId`.
10. `newIndex` equal to the entry count puts the entry last; `newIndex` past the count answers
    `400` and moves nothing; a negative `newIndex` answers `400` and moves nothing.
11. Moving an entry id that is not in the playlist answers `204` and changes nothing when the
    index is in range, and `400` when it is not — the index is judged before the entry is looked
    up.
12. `DELETE /Items/{id}` on a playlist deletes it; on a movie it answers `403` and the file remains
    on disk; on a playlist the caller may not delete, it answers `401`.
13. An administrator who does not own a playlist may delete it and may not edit it: `Move`,
    `Add` and `Remove` are refused.
14. A user shared with `CanEdit` through the create body may reorder the playlist; one shared
    without it may not.
15. A non-public playlist is invisible to another non-administrator user in `/Items` and answers
    `404` on direct fetch — **including** when the request names its owner in `userId`, where the
    reference answers `200`.
16. `userId` naming another user is honoured for an administrator and refused otherwise.
17. A playlist containing an item the reader cannot reach returns the remaining entries, in order,
    with unchanged entry ids, and a `TotalRecordCount` that counts only those — and that reader's
    `Move` indexes the list they were given: the entry lands at `newIndex` of it, and naming the
    omitted entry answers `204` and changes nothing.
18. An administrator renames a playlist through `POST /Items/{id}`; its non-administrator owner is
    answered `403`.
19. A refusal for a caller naming another user carries `403` with the reference's 25-byte
    `text/plain` body — on this feature's routes and on the 005 route that shares the rule.
20. Playlist state survives a full library rescan.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `POST /Playlists` | **L2** | Golden response; creation then query; the two `400` shapes and the empty name (AC-2, AC-3) |
| `GET /Playlists/{id}/Items` | **L2** | Golden response including `PlaylistItemId`; order assertions; the `userId` divergence (AC-15, AC-16) |
| `POST`/`DELETE .../Items` | **L2** | Duplicate and idempotency cases (AC-5, AC-6); container expansion (AC-7) |
| `.../Move/{newIndex}` | **L2** | Table-driven over source × target, including the boundaries (AC-9 to AC-11) |
| `DELETE /Items/{itemId}` | **L2** | Playlist path plus the media refusal, with an on-disk assertion (AC-12) |
| `POST /Items/{itemId}` | **L2** | Rename by an administrator, refusal for a non-administrator owner (AC-18) |
| The shared refusal | **L2** | The `403` body, asserted as bytes on a 009 route and on `/Items?userId=` (AC-19) |

The move test is table-driven because off-by-one errors in reordering pass every hand-written case
and fail the one nobody wrote. Every (source, target) pair on a five-entry playlist is 25 rows and
catches all of them. **Two tables, not one:** the reference's move arithmetic indexes the entries
the caller can see while inserting into the entries the playlist has, so a playlist with one
unreachable entry is a second matrix — and under §3.7's divergence, the one Atrium has to get right
is the filtered view its own readers get.

## 7. Open questions

None. All six were answered at the spec-review gate on 2026-08-31.

### Resolved

| # | Question | Answer | Resolved by |
|---|---|---|---|
| OQ-1 | Does the reference interpret `newIndex` pre- or post-removal? | **Post-removal.** The entry ends up at `newIndex` in the resulting list. §3.5 and AC-9 said the opposite and are corrected | `tools/probe_playlist_move.py`, 2026-08-26, re-measured 2026-08-31 |
| OQ-2 | Does the reference de-duplicate on add? | **Yes, and on create too** — two stages. §3.1 and §3.4 are corrected, and §3.1 now carries the reason: an entry has no identifier of its own to be duplicated under | `tools/probe_playlist_move.py`, 2026-08-26 |
| OQ-3 | Does adding a container expand it, or add the container itself? | **It expands**, for every container kind — album, artist, series, season and collection — and an album arrives in the album's own order. AC-7 holds | `tools/probe_playlist_expansion.py`, 2026-08-31 |
| OQ-4 | What the reference does with entries the reader cannot see | **Nothing.** The filter it applies is a parental-rating check, so entries from libraries the reader cannot open are returned and counted. §3.7's omission rule is now Atrium's divergence rather than a description | `tools/probe_playlist_visibility.py`, 2026-08-31 |
| OQ-5 | Whether any client relies on `DELETE /Items/{itemId}` deleting media | **No.** The surface names one consumer for the route, its contract uses it only for playlists, and the other client's operation table does not carry it. The §3.6 divergence costs both analysed clients nothing | The two client contracts and `surface.yaml`, 2026-08-31 |
| OQ-6 | Whether `newIndex` beyond the end clamps or errors, and what a negative index does | **Both, and neither as written**: a clamp one position wide, then `500`; a negative index moves the entry to index 1. §3.5 carries the measured table | `tools/probe_playlist_move.py`, 2026-08-31 |

### Answered without having been asked

| Finding | Where it landed |
|---|---|
| `PlaylistItemId` is the item's own `Id` | §3.1, AC-4 — and it is the finding the feature was least prepared for |
| `GET /Playlists/{id}/Items` accepts no sort parameter | §3.3, AC-8 |
| `userId` names the reader, unchecked | §3.7, behaviours §3.16, AC-15 and AC-16 |
| An empty `Name` creates a playlist | §3.2, AC-2 |
| An unknown id is fatal to creation under one condition | §3.2, AC-3 |
| Refusing a deletion is `401`, not `403` | §3.6, AC-12 |
| Administrators may delete a playlist and may not edit one | §3.7, AC-13 |
| Shares are reachable from the create body | §3.2, §3.7, AC-14 |
| The rename route is administrator-only | §3.8, AC-18 |
| A playlist is a directory, and a rename does not move it | §3.2, §3.8, §4 |
| The playlists folder is not a view | §3.2 — 009 adds nothing to a 005 response |

## 8. References

- [docs/compatibility/api-surface-v1.md §6](../../docs/compatibility/api-surface-v1.md#6-playlists)
- [specs/005 §3.1](../005-item-query-api/spec.md) — the list envelope
- [docs/compatibility/client-embeat-mobile.md §3](../../docs/compatibility/client-embeat-mobile.md) — the named consumer for the rename
- [docs/compatibility/behaviours.md](../../docs/compatibility/behaviours.md) §2.7, §2.8, §2.26, §3.15, §3.16, §3.17, §4.3, §5
- `[spec: CreatePlaylist, CreatePlaylistDto, PlaylistCreationResult, GetPlaylistItems, AddItemToPlaylist, RemoveItemFromPlaylist, MoveItem, DeleteItem, UpdateItem]`
