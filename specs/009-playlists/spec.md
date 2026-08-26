---
feature: 009-playlists
title: Playlists
status: Draft
created: 2026-08-26
updated: 2026-08-26
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
- Playlist entries, their identity, and why it differs from item identity.
- Ownership and visibility.

**Out of scope**

- `POST /Playlists/{playlistId}` (rename and update), `/Playlists/{playlistId}/Users` (sharing).
  No analysed client uses either.
- Smart or rule-based playlists.
- Reading or writing `.m3u` files on disk. v1's playlists live in the server's own store — writing
  into a library root is forbidden (004 §2).
- Deleting **media** through `DELETE /Items/{itemId}`. §3.6.

## 3. Behaviour

### 3.1 Entries are not items

The distinction that governs this whole feature: **a playlist contains entries, and an entry
references an item.**

The same track can appear three times in one playlist. Each occurrence is a distinct entry with its
own identifier, and reordering or removing "the second one" is only expressible if entries are
addressable.

Entries surface as `PlaylistItemId` on each item returned by `GET /Playlists/{playlistId}/Items`.

> **In `POST /Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}` and in
> `DELETE /Playlists/{playlistId}/Items`, the identifier is the *entry* id, not the media item id.**
> This is the single most common client-side bug against this API, and a server that accepted either
> would work by accident until a playlist contained a duplicate — at which point it would move the
> wrong row.

### 3.2 `POST /Playlists` — `CreatePlaylist`

**Consumers:** music-client.

**Body:** `Name` (required), `Ids` (initial items, may be empty), `UserId`, `MediaType`, `IsPublic`.
`[spec: CreatePlaylistDto]`

**Response — 200:** `{"Id": "<32 hex>"}` — the new playlist's item id. `[spec: PlaylistCreationResult]`

A playlist is a first-class item of `Type: Playlist`, so it appears in `/Items` queries filtered by
that type, carries `UserData`, and can be a favourite.

**Errors:** `400` for a missing or empty `Name`; `401` unauthenticated; ids in `Ids` that do not
exist or are not visible are **skipped**, not fatal. Failing the whole creation because one of
fifty ids went stale is worse for a client than creating the playlist with forty-nine.

### 3.3 `GET /Playlists/{playlistId}/Items` — `GetPlaylistItems`

**Consumers:** music-client, video-client.

Returns the standard list envelope (005 §3.1), with each item carrying its `PlaylistItemId`.

**Order is the playlist's order**, and it is the point of the endpoint. `sortBy` is accepted and
applies as a view over that order; without it, playlist order is what comes back — never
`SortName`, never insertion time.

Accepts `startIndex`, `limit`, `fields`, `userId`. `404` for unknown or invisible playlists.

### 3.4 `POST /Playlists/{playlistId}/Items` — `AddItemToPlaylist`

**Consumers:** music-client.

Appends items, identified by media item id, to the end. `204`.

**Duplicates are allowed.** Adding a track already present adds a second entry. A user building a
DJ set puts the same track in twice on purpose, and de-duplicating silently is a server deciding
something that is not its decision.

**Adding a container adds its children, in order** — adding an album adds its tracks. This is what
a client's "add album to playlist" does.

`404` for an unknown playlist. Unknown item ids are skipped, as in §3.2.

### 3.5 Removing and reordering

**`DELETE /Playlists/{playlistId}/Items`** removes entries by **entry id**, several at once. `204`.
Removing an entry id that is not in the playlist is `204`, not an error — clients retry, and a
retry after a successful removal must not fail.

**`POST /Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}`** moves one entry to an absolute
index. `204`.

| Case | Behaviour |
|---|---|
| `newIndex` beyond the end | Clamped to the end |
| `newIndex` negative | `400` |
| Moving to its current index | `204`, nothing changes |
| Entry id not in the playlist | `404` |

**Indices are zero-based and refer to the state *before* the move.** A client that computes "move
item from 5 to 2" from a list it is displaying must get what it drew. Interpreting the target index
post-removal shifts every downward move by one — an off-by-one that looks like a rendering glitch
and is very hard for a client author to attribute to the server.

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
> and working on playlists. The cost of not diverging is a bug in a new server destroying somebody's
> library. Those are not comparable.
>
> Media deletion is revisited when there is a trash with a retention window to put things in.
> Recorded in [behaviours.md](../../docs/compatibility/behaviours.md).

`404` for unknown or invisible items. `403` for a playlist the user does not own and is not an
administrator over.

### 3.7 Ownership and visibility

A playlist has an owner. `IsPublic` makes it visible to other users; otherwise only the owner and
administrators see it, and it does not appear in their `/Items` results.

Only the owner and administrators may modify or delete one. A public playlist is readable by
everyone and writable by its owner.

**A playlist entry referencing an item the reader cannot see is omitted from the response**, and
the remaining entries keep their order and their entry ids. The alternative — showing an
unreachable item, or failing the whole request — leaks the existence of restricted content or
breaks the playlist entirely.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Playlists | `Type: Playlist` items in `/Items` | Until deleted |
| Entries and their order | `GET /Playlists/{id}/Items` | Until modified |
| Entry identity | `PlaylistItemId` | For the life of the entry |
| Ownership and visibility | Whether another user sees the playlist | With the playlist |

Playlists are the **only** structural state in v1 that does not come from the filesystem, and
therefore the only thing in the server's store that cannot be rebuilt by a rescan. That makes them
the only thing whose loss is unrecoverable, and the plan has to treat them accordingly.

## 5. Acceptance criteria

1. `POST /Playlists` returns an id; the playlist then appears in `/Items?IncludeItemTypes=Playlist`.
2. Creating with an empty `Name` answers `400`; creating with a mix of valid and unknown ids
   succeeds with the valid ones.
3. Every item from `GET /Playlists/{id}/Items` carries a `PlaylistItemId`.
4. Adding the same track twice yields two entries with **different** `PlaylistItemId`s.
5. Removing one of two duplicate entries by entry id removes exactly that one.
6. Adding an album adds its tracks in track order.
7. Default order is playlist order, not `SortName`; passing `sortBy` overrides it.
8. Moving an entry from index 5 to index 2 produces the order a client drawing the pre-move list
   would expect.
9. `newIndex` beyond the end clamps; negative answers `400`.
10. Removing an entry id that is not present answers `204`.
11. `DELETE /Items/{id}` on a playlist deletes it; on a movie it answers `403` and the file remains
    on disk.
12. A non-public playlist is invisible to another non-administrator user in `/Items` and answers
    `404` on direct fetch.
13. A playlist containing an item the reader cannot see returns the remaining entries, in order,
    with unchanged entry ids.
14. Playlist state survives a full library rescan.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| `POST /Playlists` | **L2** | Golden response; creation then query |
| `GET /Playlists/{id}/Items` | **L2** | Golden response including `PlaylistItemId`; order assertions |
| `POST`/`DELETE .../Items` | **L2** | Duplicate and idempotency cases (AC-4, AC-5, AC-10) |
| `.../Move/{newIndex}` | **L2** | Table-driven over source × target, including the boundaries |
| `DELETE /Items/{itemId}` | **L2** | Playlist path plus the media refusal, with an on-disk assertion (AC-11) |

The move test is table-driven because off-by-one errors in reordering pass every hand-written case
and fail the one nobody wrote. Every (source, target) pair on a five-entry playlist is 25 rows and
catches all of them.

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Does the reference interpret `newIndex` pre- or post-removal? | AC-8, the highest-risk parity claim here | `tools/probe_playlist_move.py` — worth doing before implementing |
| OQ-2 | Does the reference de-duplicate on add? §3.4 assumes not | AC-4 | `tools/probe_playlists.py` |
| OQ-3 | Does adding a container expand it, or add the container itself? | AC-6 | `tools/probe_playlists.py` |
| OQ-4 | What the reference does with entries the reader cannot see | AC-13 | Fixture comparison via the differential harness |
| OQ-5 | Whether any client relies on `DELETE /Items/{itemId}` deleting media | The scope of the §3.6 divergence | Survey of client code plus differential |

## 8. References

- [docs/compatibility/api-surface-v1.md §6](../../docs/compatibility/api-surface-v1.md#6-playlists)
- [specs/005 §3.1](../005-item-query-api/spec.md) — the list envelope
- `[spec: CreatePlaylist, CreatePlaylistDto, PlaylistCreationResult, GetPlaylistItems, AddItemToPlaylist, RemoveItemFromPlaylist, MoveItem, DeleteItem]`
