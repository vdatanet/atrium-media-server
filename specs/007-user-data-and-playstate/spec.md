---
feature: 007-user-data-and-playstate
title: User data and playstate
status: Draft
created: 2026-08-26
updated: 2026-08-26
depends_on: [002, 005]
---

# 007 — User data and playstate

> **This document describes WHAT and WHY only.** No technology names, no storage decisions.

## 1. Purpose

Remember, per user and per item: whether it is a favourite, whether it has been played, how many
times, and where the user stopped.

**Client behaviour unlocked:** a heart that stays filled, a "continue watching" row that is
correct, and an episode that resumes at the right second on a different device from the one that
paused it.

## 2. Scope

**In scope**

- `POST` and `DELETE /UserFavoriteItems/{itemId}`, `POST` and `DELETE /UserPlayedItems/{itemId}`.
- `POST /Sessions/Playing`, `/Sessions/Playing/Progress`, `/Sessions/Playing/Stopped`.
- The `UserData` object 005 returns on every item.
- Aggregation: how a season's played state follows from its episodes.
- The completion threshold that turns "stopped near the end" into "played".

**Out of scope**

- `POST`/`DELETE /UserItems/{itemId}/Rating` and `/UserItems/{itemId}/UserData` — no analysed client
  uses them.
- Remote control: v1 records what a session reports, it does not command sessions.
- Watch history as a queryable log. v1 keeps aggregate state, not a timeline.
- SyncPlay.

## 3. Behaviour

### 3.1 The `UserData` object

Returned inline on **every** item in every 005 response, with no `Fields` or `EnableUserData`
needed.

| Field | Type | Notes |
|---|---|---|
| `PlaybackPositionTicks` | integer | Ticks; `0` when not started |
| `PlayCount` | integer | |
| `IsFavorite` | boolean | |
| `Played` | boolean | |
| `PlayedPercentage` | number | Present when a position exists |
| `UnplayedItemCount` | integer | Containers only |
| `LastPlayedDate` | date | Absent until first played |
| `Key` | string | Jellyfin-specific; §3.2 |
| `ItemId` | string | Jellyfin-specific |

`[prior-probe: Jellyfin 10.11.11, 2026-06-13]` — `Key` and `ItemId` inside `UserData` are present in
the Jellyfin dialect and absent in Emby's, so a client using them to tell the servers apart would
see the wrong answer if Atrium omitted them.

**Every field is per user.** Two users watching the same file share nothing.

### 3.2 `Key`

A stable string identifying the item *for user-data purposes*, distinct from its `Id`.

It exists because user data should survive things an item id does not. In the reference it is
derived from the item's provider identity or its name, so a re-identified or moved item can keep
its state.

**v1 derives `Key` from the item's stable identity** (003 §3.6), which gives the same survival
property for the cases v1 can produce. It is opaque to clients — they store it and send it back —
so its derivation is not observable.

> ⚠️ **OQ-1.** Whether any client parses `Key` rather than treating it as opaque. If one does, its
> format is part of the contract and this section is wrong.

### 3.3 Favourites

`POST /UserFavoriteItems/{itemId}` marks; `DELETE` unmarks. Both return the updated `UserData`
object.

**These are the Jellyfin routes.** Emby's user-scoped `/Users/{userId}/FavoriteItems/{itemId}` was
removed in 10.11 and Atrium does not serve it ([ADR-0004](../../docs/decisions/0004-pin-to-jellyfin-10-11.md)).

**Idempotent.** Marking a favourite twice is `200` both times, not an error. Clients retry.

`404` for unknown or invisible items. `401` unauthenticated.

Any item type may be a favourite — an artist, an album, a series, a single track.

### 3.4 Played state

`POST /UserPlayedItems/{itemId}` marks played; `DELETE` marks unplayed. Both return the updated
`UserData`.

| Action | Effect |
|---|---|
| Mark played | `Played` true, `PlayCount` incremented, `LastPlayedDate` set, **`PlaybackPositionTicks` reset to 0** |
| Mark unplayed | `Played` false, `PlayCount` 0, position 0, `LastPlayedDate` cleared |

The position reset matters: an item that is played *and* has a resume position appears in "continue
watching" forever.

**Marking a container marks its children.** Marking a season played marks its episodes; marking an
album played marks its tracks. A client offering "mark season watched" expects exactly this.

### 3.5 Aggregation

A container's user data is derived from its children, never stored independently:

| Container field | Derived as |
|---|---|
| `UnplayedItemCount` | Count of unplayed descendants |
| `Played` | True when every child is played |
| `PlayedPercentage` | Fraction of children played |

Derived, not cached-and-updated. Cached aggregates drift — a rescan adds an episode, a file is
removed, a user marks a child directly — and a drifted count is visible on every series poster.
Where derivation is too slow, the plan may cache it, but the specified behaviour is that a client
can never observe a stale aggregate.

### 3.6 Playback reporting

Three endpoints, all answering **`204`**, all used by both analysed clients.

| Endpoint | When | Body |
|---|---|---|
| `POST /Sessions/Playing` | Playback starts | `ItemId`, `PlaySessionId`, `MediaSourceId`, `PlayMethod`, `CanSeek`, `AudioStreamIndex`, `SubtitleStreamIndex`, `PositionTicks` |
| `POST /Sessions/Playing/Progress` | Periodically, and on pause, seek and track change | Same, plus `IsPaused`, `IsMuted`, `VolumeLevel` |
| `POST /Sessions/Playing/Stopped` | Playback ends | `ItemId`, `PlaySessionId`, `PositionTicks`, `Failed` |

`[spec: PlaybackStartInfo, PlaybackProgressInfo, PlaybackStopInfo]`

**`MediaSourceId` is not required on `Progress`.** Emby requires it; Jellyfin does not, and a server
that rejected reports without it would silently lose the resume positions of any client written
against the Jellyfin dialect. `[prior-probe: Jellyfin 10.11.11, 2026-06-13]`

**Effects**

| Report | Effect |
|---|---|
| Start | Session shows `NowPlayingItem` and `PlayState` (002 §3.8); `LastPlaybackCheckIn` advances |
| Progress | `PlaybackPositionTicks` updated; session `PlayState` updated |
| Stopped | Final position stored, subject to §3.7; `NowPlayingItem` cleared |

**Robustness rules, because these arrive over unreliable networks from clients that crash:**

1. **Unknown `ItemId` is `204`, not an error.** A report for an item removed mid-playback is not
   worth failing; the client cannot act on the failure anyway.
2. **Out-of-order reports are handled by position, not arrival.** A progress report older than the
   stored position for the same play session does not rewind it.
3. **A missing `Stopped` must not lose the position.** Clients are killed by the operating system
   mid-playback. The last `Progress` stands on its own, and a session that stops reporting is
   eventually reaped with its last known position intact.
4. **`Failed: true` records no position and no play count.** A playback that never started is not
   progress.

### 3.7 The completion threshold

When a `Stopped` report arrives near the end, the item becomes **played** rather than resumable,
and the position is reset.

Two rules, both needed:

- Past a **percentage** of the runtime, treat as complete — the user watched it.
- Below a **minimum** position, discard the position entirely — thirty seconds into a film is not a
  resume point, it is a mis-click, and it should not fill "continue watching" with noise.

An item marked complete this way is excluded from `/UserItems/Resume` (005 §3.7).

> ⚠️ **OQ-2.** The reference's exact thresholds. They are directly observable — an item that
> reappears in "continue watching" when it should not, or vanishes when it should not — so this is
> a probe worth doing before the feature is called done.

## 4. Data the feature owns

| State | Observable as | Lifetime |
|---|---|---|
| Per-user, per-item favourite state | `UserData.IsFavorite` | Until changed |
| Per-user played state and count | `UserData.Played`, `PlayCount`, `LastPlayedDate` | Until changed |
| Per-user resume position | `UserData.PlaybackPositionTicks` | Until played or reset |
| Live playback state per session | `NowPlayingItem`, `PlayState` in `/Sessions` | While playing |

**User data outlives items** (003 §3.8). A file that disappears and returns keeps its state,
because the alternative is a user losing their library's history to a temporarily unmounted share.

## 5. Acceptance criteria

1. `UserData` is present on every item in every 005 response, with `Key` and `ItemId` inside it.
2. Marking a favourite twice answers `200` twice and leaves one favourite.
3. Marking played resets `PlaybackPositionTicks` to 0 and increments `PlayCount`.
4. Marking unplayed clears played, count, position and `LastPlayedDate`.
5. Marking a season played marks every episode played.
6. A season's `UnplayedItemCount` matches its unplayed episodes after: marking one episode,
   rescanning with a new episode added, and removing an episode.
7. Two users' state on the same item is fully independent.
8. All three reporting endpoints answer `204`.
9. `Progress` without `MediaSourceId` is accepted.
10. A progress report with a position **older** than the stored one does not rewind it.
11. A report for an unknown item answers `204`.
12. A `Stopped` past the completion threshold marks played and clears the position; the item leaves
    `/UserItems/Resume`.
13. A `Stopped` below the minimum position stores no position; the item never enters
    `/UserItems/Resume`.
14. `Failed: true` records neither position nor play count.
15. Progress reports with no `Stopped` leave the last position intact after the session is reaped.
16. Deleting an item's file and rescanning preserves its user data; restoring the file restores the
    association.

## 6. Conformance

| Endpoint | Level | How it is proven |
|---|---|---|
| Favourite mark/unmark | **L2** | Round-trip plus idempotency (AC-2) |
| Played mark/unmark | **L2** | Including the position reset (AC-3) and cascade (AC-5) |
| The three reporting endpoints | **L2** | Status, effect on `UserData`, effect on `/Sessions` |
| `UserData` shape | **L3** | Golden plus differential — it appears on every item, so an error is everywhere |
| Aggregation | **L2** | Fixture mutated between assertions (AC-6) |
| Threshold behaviour | **L2** | Table-driven over position × runtime |

## 7. Open questions

| # | Question | Blocks | Resolved by |
|---|---|---|---|
| OQ-1 | Does any client parse `UserData.Key`, or is it opaque? | §3.2's freedom to derive it | Survey of client code, plus differential |
| OQ-2 | The reference's completion percentage and minimum-position thresholds | AC-12, AC-13 | **`tools/probe_playstate.py` — written, awaiting a run** |
| OQ-3 | Does the reference cascade a container mark to children, or only report aggregates? | AC-5, which may be a divergence | `tools/probe_playstate.py` |
| OQ-4 | How long the reference waits before reaping a silent session | AC-15 | A probe that starts playback and stops reporting |
| OQ-5 | Does the reference count a play at start, at stop, or at the threshold? | `PlayCount` parity | `tools/probe_playstate.py` |

## 8. References

- [docs/compatibility/api-surface-v1.md §5, §9](../../docs/compatibility/api-surface-v1.md#5-user-data)
- [docs/compatibility/behaviours.md §2.1](../../docs/compatibility/behaviours.md#21-userdata-is-always-present)
- [specs/003 §3.8](../003-library-configuration-and-scanning/spec.md) — user data outliving items
- `[spec: MarkFavoriteItem, UnmarkFavoriteItem, MarkPlayedItem, MarkUnplayedItem, ReportPlaybackStart, ReportPlaybackProgress, ReportPlaybackStopped, UserItemDataDto]`
