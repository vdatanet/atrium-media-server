#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What do playback reports and played marks actually do to UserData?

First written for 007 OQ-2 - the thresholds that decide what appears in "continue watching" -
which it answered by bisection on 2026-08-26. Extended at the 007 spec review (2026-08-28) to
measure the rest of the draft's claims and open questions, because reading the reference's source
had contradicted four of them and a source reading is not a measurement:

* **OQ-5, when a play is counted.** The source counts it at *start* (SessionManager.cs
  OnPlaybackStart), not at stop - and a stop that carries no position counts it *again*.
* **OQ-3, the container cascade.** Folder.MarkPlayed sweeps the non-folder descendants; the
  container's own stored row is never written, its state being derived.
* **OQ-6, the short-item rule.** An item whose *runtime* is under MinResumeDurationSeconds is
  marked played when stopped mid-way, not left resumable.
* **The claims the draft got wrong, per the source.** `POST /UserPlayedItems` without `datePlayed`
  does not increment `PlayCount` (it is `max(count, 1)` - BaseItem.MarkPlayed); the six-branch
  stop rule runs on every *progress* report too (both call UserDataManager.UpdatePlayState); and
  nothing anywhere compares a report's position against the stored one, so an out-of-order
  progress report rewinds - the draft's robustness rule 2 and AC-10 say the opposite.

Every battery reads the result back from `/Items/{id}` rather than trusting the report's own
response, and every battery restores the state it touched, including on failure. Items are chosen
to have no user data at all, so restoring them is exact.

The reaping question (OQ-4) costs ten minutes of silence by construction, so it hides behind
`--reap`: start playback, report once, go silent, and poll `/Sessions` until the server gives up
- then read what position the reap committed. The source says the idle sweep runs every five
minutes and reaps sessions silent for more than five (SessionManager.cs), so the expected wait
is five to ten minutes - and the committed position is NOT the last reported one: a per-session
one-second ticker extrapolates the unpaused position in real time (SessionInfo.cs,
ProgressIncrement), so the reap stores the last report plus the silence, capped at the runtime.
Measured: 40% reported, 8.6 minutes silent, 48.5% stored.

Writes: playback reports and played/favourite marks against one long item, one short audio item
and one season whose episodes have no user data; all of it is restored, including on failure.

Usage:
    python3 tools/probe_playstate.py http://your-jellyfin:8096 -u username --allow-writes
    python3 tools/probe_playstate.py --allow-writes --reap    # adds the ten-minute OQ-4 battery
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone

from _probe import Probe, ProbeError, Server, main

TICKS_PER_SECOND = 10_000_000
MIN_RUNTIME_SECONDS = 600  # comfortably above the reference's 300s resume-eligibility floor

#: The short-item battery needs a runtime strictly under the 300s floor, but long enough that
#: half of it clears the 5% position floor by a wide margin.
SHORT_RUNTIME_BOUNDS = (60, 290)

#: The cascade battery marks a whole season. A bound on its size keeps the probe polite.
SEASON_MAX_EPISODES = 24

REFERENCE_DEFAULTS = "MinResumePct=5, MaxResumePct=90, MinResumeDurationSeconds=300"

#: The nine properties a measured `NowPlayingItem` carries that are derived from the media file
#: itself. v1 has no source for any of them, so the differential will show them absent until the
#: feature that owns them lands - a named gap rather than a silent one (spec section 3.6).
MEDIA_DERIVED = (
    "MediaStreams",
    "Chapters",
    "Width",
    "Height",
    "HasSubtitles",
    "IsHD",
    "VideoType",
    "Trickplay",
    "Container",
)

#: A GUID that parses and names nothing, versus a string that is not a GUID at all. The two
#: refuse differently, and the difference is the whole of the reports' error floor: leniency
#: starts *after* the body binds.
GHOST = uuid.uuid4().hex
NOT_A_GUID = "banana"


def pristine(item: dict) -> bool:
    data = item.get("UserData") or {}
    return (
        not data.get("Played")
        and not data.get("PlayCount")
        and not data.get("PlaybackPositionTicks")
        and not data.get("IsFavorite")
    )


def find_item(server: Server) -> dict:
    """A long item with no user data, so the probe is both meaningful and exactly reversible."""
    for item_type in ("Movie", "Episode", "Audio"):
        found = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes=item_type,
            Limit=100,
            SortBy="Random",
            UserId=server.user_id,
        )
        for item in found.get("Items", []):
            runtime = item.get("RunTimeTicks") or 0
            if runtime >= MIN_RUNTIME_SECONDS * TICKS_PER_SECOND and pristine(item):
                return item
    raise ProbeError(
        f"no item found that is at least {MIN_RUNTIME_SECONDS}s long and has no user data. "
        "The probe will not overwrite an existing play position, because it could not put it "
        "back exactly"
    )


def find_short_item(server: Server) -> dict | None:
    """An item whose runtime sits under the 300s floor - usually a music track."""
    low, high = SHORT_RUNTIME_BOUNDS
    for item_type in ("Audio", "Episode", "Movie"):
        found = server.get(
            "/Items",
            Recursive="true",
            IncludeItemTypes=item_type,
            Limit=200,
            SortBy="Random",
            UserId=server.user_id,
        )
        for item in found.get("Items", []):
            runtime = item.get("RunTimeTicks") or 0
            if low * TICKS_PER_SECOND <= runtime <= high * TICKS_PER_SECOND and pristine(item):
                return item
    return None


def find_pristine_season(server: Server) -> tuple[dict, list[dict]] | None:
    """A season of two or more episodes, every one of them - and the season - without user data."""
    seasons = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes="Season",
        Limit=60,
        SortBy="Random",
        UserId=server.user_id,
    )
    for season in seasons.get("Items", []):
        if not pristine(season):
            continue
        episodes = server.get(
            "/Items",
            ParentId=season["Id"],
            IncludeItemTypes="Episode",
            Recursive="true",
            UserId=server.user_id,
        ).get("Items", [])
        if 2 <= len(episodes) <= SEASON_MAX_EPISODES and all(pristine(e) for e in episodes):
            return season, episodes
    return None


class Trials:
    """Playback reports against one item, each result read back from `/Items/{id}`."""

    def __init__(self, server: Server, item_id: str, runtime: int) -> None:
        self.server, self.item_id, self.runtime = server, item_id, runtime
        self.count = 0

    def reset(self) -> None:
        self.server.delete(f"/UserPlayedItems/{self.item_id}")

    def read(self) -> dict:
        item = self.server.get(f"/Items/{self.item_id}", UserId=self.server.user_id)
        return item.get("UserData") or {}

    def start(self) -> int:
        status, _, _ = self.server.post_raw(
            "/Sessions/Playing",
            body={
                "ItemId": self.item_id,
                "PositionTicks": 0,
                "PlayMethod": "DirectPlay",
                "CanSeek": True,
                "IsPaused": False,
            },
        )
        return status

    def progress(self, ticks: int) -> int:
        status, _, _ = self.server.post_raw(
            "/Sessions/Playing/Progress",
            body={"ItemId": self.item_id, "PositionTicks": ticks, "IsPaused": False},
        )
        return status

    def stop(self, ticks: int | None = None, failed: bool | None = None) -> int:
        body: dict = {"ItemId": self.item_id}
        if ticks is not None:
            body["PositionTicks"] = ticks
        if failed is not None:
            body["Failed"] = failed
        status, _, _ = self.server.post_raw("/Sessions/Playing/Stopped", body=body)
        return status

    def ticks(self, pct: float) -> int:
        return int(self.runtime * pct / 100)

    def stop_at(self, pct: float) -> dict:
        """One bisection trial: reset, play, stop at a fraction, read the result back."""
        self.count += 1
        self.reset()
        self.start()
        self.stop(ticks=self.ticks(pct))
        return self.read()

    def stop_at_ticks(self, ticks: int) -> dict:
        self.count += 1
        self.reset()
        self.start()
        self.stop(ticks=ticks)
        return self.read()


def boundary(low: float, high: float, holds, precision: float = 0.5) -> float:
    """Smallest value in (low, high] where `holds` becomes true, by bisection."""
    while high - low > precision:
        middle = (low + high) / 2
        if holds(middle):
            high = middle
        else:
            low = middle
    return high


def described(data: dict, runtime: int) -> str:
    position = data.get("PlaybackPositionTicks", 0)
    pct = f" ({position / runtime * 100:.1f}%)" if runtime and position else ""
    return (
        f"Played={data.get('Played')} PlayCount={data.get('PlayCount')} "
        f"position={position}{pct} LastPlayedDate="
        f"{'set' if data.get('LastPlayedDate') else 'absent'}"
    )


class Findings:
    """Which batteries contradicted the draft, so the verdict can name them."""

    def __init__(self) -> None:
        self.contradictions: list[str] = []

    def check(self, holds: bool, claim: str) -> bool:
        if not holds:
            self.contradictions.append(claim)
        return holds


def report_cycle_battery(probe: Probe, trials: Trials, findings: Findings) -> None:
    """What each report does: the count at start, the rule on progress, the rewind."""
    runtime = trials.runtime

    trials.reset()
    status = trials.start()
    after_start = trials.read()
    probe.observe(f"Start report ({status})", described(after_start, runtime))
    counted_at_start = after_start.get("PlayCount", 0) == 1
    probe.observe(
        "  a play is counted at start",
        "yes" if counted_at_start else f"NO - PlayCount={after_start.get('PlayCount')}",
    )

    status = trials.progress(trials.ticks(40))
    after_forward = trials.read()
    probe.observe(f"Progress at 40% ({status})", described(after_forward, runtime))
    probe.observe(
        "  progress does not add a count",
        "yes" if after_forward.get("PlayCount") == after_start.get("PlayCount") else "NO",
    )

    trials.progress(trials.ticks(20))
    after_backward = trials.read()
    probe.observe("Progress at 20%, after the 40%", described(after_backward, runtime))
    rewound = after_backward.get("PlaybackPositionTicks", 0) == trials.ticks(20)
    probe.observe("  an older position rewinds the stored one", "YES" if rewound else "no")
    findings.check(
        rewound,
        "spec 3.6: reports resolve last-writer-wins - an older progress position rewinds",
    )

    trials.progress(trials.ticks(95))
    past_ceiling = trials.read()
    probe.observe("Progress at 95%", described(past_ceiling, runtime))
    rule_on_progress = (
        past_ceiling.get("Played") is True and past_ceiling.get("PlaybackPositionTicks", 0) == 0
    )
    probe.observe("  the stop rule fires on a progress report", "YES" if rule_on_progress else "no")
    findings.check(
        rule_on_progress,
        "spec 3.7: the six-branch rule runs on progress reports, not only on stops",
    )

    trials.progress(trials.ticks(40))
    poisoned = trials.read()
    probe.observe("Progress back at 40%, after the 95%", described(poisoned, runtime))
    probe.observe(
        "  played-with-a-position is reachable",
        "YES" if poisoned.get("Played") and poisoned.get("PlaybackPositionTicks") else "no",
    )

    status = trials.stop(ticks=trials.ticks(50))
    after_stop = trials.read()
    probe.observe(f"Stopped at 50% ({status})", described(after_stop, runtime))
    probe.observe(
        "  a stop with a position does not add a count",
        "yes" if after_stop.get("PlayCount") == after_start.get("PlayCount") else "NO",
    )

    trials.reset()
    trials.start()
    trials.stop()
    bare_stop = trials.read()
    probe.observe("Start, then Stopped with no position", described(bare_stop, runtime))
    probe.observe(
        "  a positionless stop adds a second count",
        "YES" if bare_stop.get("PlayCount") == 2 else f"no - {bare_stop.get('PlayCount')}",
    )

    trials.reset()
    trials.start()
    trials.stop(ticks=trials.ticks(50), failed=True)
    failed = trials.read()
    probe.observe("Start, then Stopped Failed=true at 50%", described(failed, runtime))
    probe.observe(
        "  the failed stop itself recorded nothing",
        "yes" if not failed.get("PlaybackPositionTicks") and not failed.get("Played") else "NO",
    )
    trials.reset()


def unknown_item_battery(server: Server, probe: Probe) -> None:
    ghost = uuid.uuid4().hex
    statuses = []
    for path, body in (
        ("/Sessions/Playing", {"ItemId": ghost, "PositionTicks": 0}),
        ("/Sessions/Playing/Progress", {"ItemId": ghost, "PositionTicks": 1000}),
        ("/Sessions/Playing/Stopped", {"ItemId": ghost, "PositionTicks": 2000}),
    ):
        status, _, _ = server.post_raw(path, body=body)
        statuses.append(status)
    probe.observe("reports for an unknown item", "/".join(str(s) for s in statuses))


def mark_battery(server: Server, probe: Probe, trials: Trials, findings: Findings) -> None:
    """The mark routes: idempotency, the count that does not move, and the one that does."""
    item_id = trials.item_id
    runtime = trials.runtime

    trials.reset()
    status, _, _ = server.post_raw(f"/UserPlayedItems/{item_id}")
    once = trials.read()
    probe.observe(f"POST /UserPlayedItems ({status})", described(once, runtime))
    status, _, _ = server.post_raw(f"/UserPlayedItems/{item_id}")
    twice = trials.read()
    probe.observe(f"POST /UserPlayedItems again ({status})", described(twice, runtime))
    unmoved = twice.get("PlayCount") == once.get("PlayCount") == 1
    probe.observe("  marking twice does not increment", "yes" if unmoved else "NO")
    findings.check(
        unmoved,
        "spec 3.4: a bare mark is max(count, 1) - only datePlayed increments",
    )

    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    server.post_raw(f"/UserPlayedItems/{item_id}", datePlayed=when)
    dated = trials.read()
    probe.observe("POST with datePlayed", described(dated, runtime))
    probe.observe(
        "  datePlayed is what increments",
        "yes" if dated.get("PlayCount") == 2 else f"NO - {dated.get('PlayCount')}",
    )

    trials.reset()
    trials.start()
    trials.progress(trials.ticks(40))
    trials.stop(ticks=trials.ticks(40))
    server.post_raw(f"/UserPlayedItems/{item_id}")
    marked = trials.read()
    probe.observe("mark played over a 40% resume position", described(marked, runtime))
    probe.observe(
        "  the mark resets the position",
        "yes" if marked.get("PlaybackPositionTicks", 1) == 0 else "NO",
    )

    status, _, _ = server.delete_raw(f"/UserPlayedItems/{item_id}")
    cleared = trials.read()
    probe.observe(f"DELETE /UserPlayedItems ({status})", described(cleared, runtime))

    first, _, _ = server.post_raw(f"/UserFavoriteItems/{item_id}")
    second, _, body = server.post_raw(f"/UserFavoriteItems/{item_id}")
    favourite = trials.read()
    probe.observe(
        "POST /UserFavoriteItems twice",
        f"{first}/{second}, IsFavorite={favourite.get('IsFavorite')}",
    )
    keyed = b"Key" in body and b"ItemId" in body
    probe.observe("  the mark response carries Key and ItemId", "yes" if keyed else "NO")
    first, _, _ = server.delete_raw(f"/UserFavoriteItems/{item_id}")
    second, _, _ = server.delete_raw(f"/UserFavoriteItems/{item_id}")
    favourite = trials.read()
    probe.observe(
        "DELETE /UserFavoriteItems twice",
        f"{first}/{second}, IsFavorite={favourite.get('IsFavorite')}",
    )


def boundary_battery(probe: Probe, trials: Trials) -> None:
    """The comparisons are strict: exactly at 5% and exactly at 90% the position is kept."""
    runtime = trials.runtime

    at_floor = -(-runtime * 5 // 100)  # ceil: the smallest position whose percentage is >= 5
    kept = trials.stop_at_ticks(at_floor)
    probe.observe(
        "stop exactly at the 5% floor",
        f"position {'kept' if kept.get('PlaybackPositionTicks') else 'DISCARDED'}",
    )
    below = trials.stop_at_ticks(at_floor - 1)
    probe.observe(
        "stop one tick below it",
        f"position {'KEPT' if below.get('PlaybackPositionTicks') else 'discarded'}",
    )

    at_ceiling = runtime * 90 // 100  # floor: the largest position whose percentage is <= 90
    kept = trials.stop_at_ticks(at_ceiling)
    probe.observe(
        "stop exactly at the 90% ceiling",
        f"position {'kept' if kept.get('PlaybackPositionTicks') else 'DISCARDED'}, "
        f"Played={kept.get('Played')}",
    )
    above = trials.stop_at_ticks(at_ceiling + 1)
    probe.observe(
        "stop one tick above it",
        f"position {'KEPT' if above.get('PlaybackPositionTicks') else 'discarded'}, "
        f"Played={above.get('Played')}",
    )
    trials.reset()


def bisection_battery(probe: Probe, trials: Trials) -> None:
    """The original 2026-08-26 measurement, kept: the thresholds found without assuming them."""
    seconds = trials.runtime / TICKS_PER_SECOND

    if trials.stop_at(99).get("Played") is not True:
        raise ProbeError(
            "stopping at 99% of the runtime did not mark the item played, so there is no "
            "upper threshold to find by this method"
        )
    if trials.stop_at(1).get("Played") is True:
        raise ProbeError("stopping at 1% marked the item played; the search assumes it does not")

    upper = boundary(1, 99, lambda pct: trials.stop_at(pct).get("Played") is True)
    probe.observe("upper threshold", f"{upper:.1f}% of runtime  ({upper * seconds / 100:.0f}s)")

    ceiling = min(upper - 1, 50)
    if trials.stop_at(ceiling).get("PlaybackPositionTicks", 0) <= 0:
        probe.observe("lower threshold", f"not found below {ceiling:.1f}%")
    else:
        lower = boundary(
            0,
            ceiling,
            lambda pct: trials.stop_at(pct).get("PlaybackPositionTicks", 0) > 0,
        )
        probe.observe("lower threshold", f"{lower:.1f}% of runtime  ({lower * seconds / 100:.0f}s)")

    probe.observe("bisection trials", trials.count)
    trials.reset()


def short_item_battery(server: Server, probe: Probe, findings: Findings) -> None:
    """OQ-6: an item whose runtime is under the floor is played, not resumable, mid-way."""
    item = find_short_item(server)
    if item is None:
        probe.observe("short item (OQ-6)", "NOT EXERCISED - no pristine item under 300s found")
        return
    runtime = item["RunTimeTicks"]
    trials = Trials(server, item["Id"], runtime)
    try:
        probe.observe(
            "short item", f"{item['Name'][:40]} ({item['Type']}, {runtime / TICKS_PER_SECOND:.0f}s)"
        )
        halfway = trials.stop_at(50)
        probe.observe("  stopped at 50%", described(halfway, runtime))
        played_not_resumable = halfway.get("Played") is True and not halfway.get(
            "PlaybackPositionTicks"
        )
        probe.observe(
            "  short runtime means played, not resumable",
            "yes" if played_not_resumable else "NO",
        )
        findings.check(
            played_not_resumable,
            "spec 3.7 row 5 (source-derived): a sub-300s item stopped mid-way is marked played",
        )
    finally:
        trials.reset()


def cascade_battery(server: Server, probe: Probe, findings: Findings) -> None:
    """OQ-3: the cascade, the derived aggregates, and the field-gated PlayedPercentage."""
    found = find_pristine_season(server)
    if found is None:
        probe.observe("cascade (OQ-3)", "NOT EXERCISED - no pristine season of 2+ episodes found")
        return
    season, episodes = found
    season_id = season["Id"]
    total = len(episodes)

    def season_row(fields: str | None = None) -> dict:
        rows = server.get_where(
            "/Items",
            {"Ids": season_id, "UserId": server.user_id, "Fields": fields},
        ).get("Items", [])
        return rows[0] if rows else {}

    try:
        probe.observe("season", f"{season.get('SeriesName', '?')} / {season['Name']} ({total} eps)")
        before = (season.get("UserData") or {}).get("UnplayedItemCount")
        probe.observe("  UnplayedItemCount before", before)

        status, _, body = server.post_raw(f"/UserPlayedItems/{season_id}")
        probe.observe(f"  POST /UserPlayedItems on the season ({status})", body[:160].decode())

        episode_rows = server.get(
            "/Items",
            ParentId=season_id,
            IncludeItemTypes="Episode",
            Recursive="true",
            UserId=server.user_id,
        ).get("Items", [])
        played = sum(1 for e in episode_rows if (e.get("UserData") or {}).get("Played"))
        cascaded = played == total
        probe.observe("  episodes now played", f"{played} of {total}")
        findings.check(cascaded, "spec 3.4 / AC-5: marking a season played marks its episodes")

        after = (season_row().get("UserData")) or {}
        probe.observe("  season after the mark", described(after, 0))
        probe.observe("  UnplayedItemCount after", after.get("UnplayedItemCount"))

        server.delete(f"/UserPlayedItems/{episode_rows[0]['Id']}")
        bare = (season_row().get("UserData")) or {}
        keyed = (season_row("RecursiveItemCount").get("UserData")) or {}
        probe.observe(
            "  one episode unmarked: bare season row",
            f"Played={bare.get('Played')} UnplayedItemCount={bare.get('UnplayedItemCount')} "
            f"PlayedPercentage={bare.get('PlayedPercentage', 'ABSENT')}",
        )
        probe.observe(
            "  same, Fields=RecursiveItemCount",
            f"PlayedPercentage={keyed.get('PlayedPercentage', 'ABSENT')}",
        )

        server.post(f"/UserFavoriteItems/{season_id}")
        episode = server.get(f"/Items/{episode_rows[0]['Id']}", UserId=server.user_id)
        episode_favourite = (episode.get("UserData") or {}).get("IsFavorite")
        season_favourite = ((season_row().get("UserData")) or {}).get("IsFavorite")
        probe.observe(
            "  season favourited",
            f"season IsFavorite={season_favourite}, episode IsFavorite={episode_favourite}",
        )
        probe.observe("  the favourite does not cascade", "yes" if not episode_favourite else "NO")
    finally:
        server.delete(f"/UserFavoriteItems/{season_id}")
        server.delete(f"/UserPlayedItems/{season_id}")
        leftovers = [
            e["Id"]
            for e in server.get(
                "/Items",
                ParentId=season_id,
                IncludeItemTypes="Episode",
                Recursive="true",
                UserId=server.user_id,
            ).get("Items", [])
            if not pristine(e)
        ]
        for episode_id in leftovers:
            server.delete(f"/UserPlayedItems/{episode_id}")
            server.delete(f"/UserFavoriteItems/{episode_id}")


def reap_battery(server: Server, probe: Probe, trials: Trials) -> None:
    """OQ-4: how long a silent session keeps playing, and what position the reap commits.

    Not the last reported one. The reference runs a one-second ticker per unpaused session that
    extrapolates the position in real time, and the reap's synthetic stop commits the
    extrapolated value - measured first as a plain "NO, the position moved", then read from
    SessionInfo.cs (ProgressIncrement) to learn it was wall-clock advancement, not noise.
    """
    runtime = trials.runtime
    trials.reset()
    trials.start()
    trials.progress(trials.ticks(40))
    probe.observe("reap battery", "started playback, reported 40%, went silent")

    begun = time.monotonic()
    elapsed = 0.0
    playing = True
    while playing and elapsed < 16 * 60:
        time.sleep(30)
        elapsed = time.monotonic() - begun
        sessions = server.get("/Sessions") or []
        playing = any(
            (one.get("NowPlayingItem") or {}).get("Id") == trials.item_id for one in sessions
        )

    if playing:
        probe.observe("  session still playing after", f"{elapsed / 60:.1f} min - gave up")
        trials.stop(ticks=trials.ticks(40))
    else:
        probe.observe("  NowPlayingItem cleared after", f"{elapsed / 60:.1f} min of silence")
        data = trials.read()
        probe.observe("  UserData after the reap", described(data, runtime))
        stored = data.get("PlaybackPositionTicks", 0)
        drift = (stored - trials.ticks(40)) / TICKS_PER_SECOND
        # The commit happens when the sweep fires; the poll notices up to a cycle later. Anything
        # between "advanced by most of the silence" and "advanced by all of it" is the ticker.
        extrapolated = 0 < drift <= elapsed + 60
        probe.observe(
            "  position advanced by the silent wall clock",
            f"{'yes' if extrapolated else 'NO'} - stored {drift:+.0f}s past the last report "
            f"after {elapsed:.0f}s of silence",
        )
    trials.reset()


def refusal(status: int, headers: dict, payload: bytes) -> str:
    """One line naming the *shape* of a refusal, not just its status.

    behaviours section 1.11 catalogues four of them and the whole point of this battery is which
    one arrives, so a status alone would measure the least interesting half.
    """
    kind = (headers.get("Content-Type") or "").split(";")[0].strip()
    text = payload.decode("utf-8", "replace")
    if not text:
        return f"{status}, empty body ({kind or 'no content type'})"
    if kind.endswith("problem+json") or text.lstrip().startswith("{"):
        try:
            document = json.loads(text)
        except ValueError:
            return f"{status} {kind} {text[:60]!r}"
        if isinstance(document, dict) and "errors" in document:
            # `repr` rather than the bare name: one of the measured keys is the empty string,
            # which a plain join renders as nothing at all.
            named = ", ".join(repr(key) for key in document["errors"])
            return f"{status} validation problem details naming {named}"
        if isinstance(document, dict):
            return f"{status} problem details, title={document.get('title')!r}"
    return f"{status} {kind} {text[:40]!r}"


def tokenless(server: Server, method, *args, **kwargs):
    """The same request with no token at all. Restored even if it raises."""
    held, server.token = server.token, None
    try:
        return method(*args, **kwargs)
    finally:
        server.token = held


def own_playing_session(server: Server, item_id: str) -> dict | None:
    """The caller's own session, if the reference thinks it is playing this item.

    A report binds to the authenticated device rather than to anything the body names
    (spec section 3.6), which is exactly what makes this findable: it is *our* session.
    """
    for session in server.get("/Sessions") or []:
        playing = session.get("NowPlayingItem") or {}
        if playing.get("Id") == item_id and session.get("UserId") == server.user_id:
            return session
    return None


def find_pristine_artist(server: Server) -> dict | None:
    """A by-name item nobody has favourited - the one item kind whose Key had two calibrations."""
    found = server.get("/Artists", Limit=40, UserId=server.user_id)
    for artist in found.get("Items", []):
        if pristine(artist):
            return artist
    return None


def playing_session_battery(probe: Probe, server: Server, trials: Trials, findings: Findings):
    """What /Sessions shows while something plays: the slot, the width, and what is absent.

    This is 005 T1's lesson pointed at /Sessions. `NowPlayingItem` is a `BaseItemDto` whose width
    nothing had ever captured, and the sharpest thing about it turned out to be an absence.
    """
    trials.reset()
    started, _, _ = server.post_raw(
        "/Sessions/Playing",
        body={
            "ItemId": trials.item_id,
            "MediaSourceId": trials.item_id,
            "PlaySessionId": uuid.uuid4().hex,
            "PositionTicks": 0,
            "PlayMethod": "DirectPlay",
            "CanSeek": True,
            "IsPaused": False,
            "IsMuted": False,
            "VolumeLevel": 80,
            "AudioStreamIndex": 1,
            "SubtitleStreamIndex": -1,
        },
    )
    session = own_playing_session(server, trials.item_id)
    if session is None:
        probe.note(
            f"the Start answered {started} and no session of this user reports the item as "
            "playing; the playing-session battery could not run"
        )
        trials.reset()
        return

    keys = list(session)
    where = keys.index("NowPlayingItem")
    follows = keys[where + 1] if where + 1 < len(keys) else "the end"
    probe.observe("NowPlayingItem's slot", f"after {keys[where - 1]}, before {follows}")
    playing = session["NowPlayingItem"]
    probe.observe("NowPlayingItem width", f"{len(playing)} properties")
    carries_user_data = "UserData" in playing
    probe.observe(
        "  it carries UserData",
        "YES - the spec says it does not" if carries_user_data else "no",
    )
    findings.check(
        not carries_user_data,
        "spec 3.6: NowPlayingItem is the one measured item shape with no UserData",
    )
    present = [name for name in MEDIA_DERIVED if name in playing]
    probe.observe(
        "  media-derived properties v1 cannot emit",
        f"{len(present)} of {len(MEDIA_DERIVED)} present: {', '.join(present) or 'none'}",
    )
    probe.observe("PlayState, as the Start left it", ", ".join(session.get("PlayState") or {}))

    # The whole question: does a report that omits a field clear it, or leave the old value?
    server.post_raw(
        "/Sessions/Playing/Progress",
        body={"ItemId": trials.item_id, "PositionTicks": trials.ticks(20), "IsPaused": False},
    )
    after = own_playing_session(server, trials.item_id) or {}
    state = after.get("PlayState") or {}
    replaced = state.get("CanSeek") is False and "VolumeLevel" not in state
    probe.observe("PlayState after a progress omitting CanSeek and VolumeLevel", ", ".join(state))
    probe.observe(
        "  replaced whole rather than merged",
        f"yes - CanSeek={state.get('CanSeek')}, VolumeLevel "
        f"{'absent' if 'VolumeLevel' not in state else state.get('VolumeLevel')}"
        if replaced
        else f"NO - CanSeek={state.get('CanSeek')}, VolumeLevel={state.get('VolumeLevel')}",
    )
    findings.check(
        replaced,
        "plan section 5: PlayState is replaced whole by each report, never merged",
    )

    ticking = state.get("PositionTicks")
    time.sleep(2)
    later = (own_playing_session(server, trials.item_id) or {}).get("PlayState") or {}
    moved = (later.get("PositionTicks") or 0) - (ticking or 0)
    probe.observe(
        "  the position advances between reports",
        f"{'yes' if moved > 0 else 'NO'} - {moved / TICKS_PER_SECOND:+.1f}s over 2s of silence",
    )

    trials.stop(ticks=trials.ticks(20))
    probe.observe(
        "NowPlayingItem after the Stopped",
        "cleared" if own_playing_session(server, trials.item_id) is None else "STILL PLAYING",
    )
    trials.reset()


def refusal_battery(probe: Probe, server: Server, trials: Trials) -> None:
    """The mark routes' four refusals. Every one should land on an existing behaviours shape."""
    probe.observe(
        "POST /UserPlayedItems, unknown item",
        refusal(*server.post_raw(f"/UserPlayedItems/{GHOST}")),
    )
    probe.observe(
        "POST /UserPlayedItems, itemId that is not a GUID",
        refusal(*server.post_raw(f"/UserPlayedItems/{NOT_A_GUID}")),
    )
    probe.observe(
        "POST /UserFavoriteItems, unknown item",
        refusal(*server.post_raw(f"/UserFavoriteItems/{GHOST}")),
    )
    probe.observe(
        "DELETE /UserFavoriteItems, unknown item",
        refusal(*server.delete_raw(f"/UserFavoriteItems/{GHOST}")),
    )
    probe.observe(
        "POST /UserPlayedItems, no token",
        refusal(*tokenless(server, server.post_raw, f"/UserPlayedItems/{trials.item_id}")),
    )
    probe.observe(
        "POST /UserPlayedItems?datePlayed=banana",
        refusal(*server.post_raw(f"/UserPlayedItems/{trials.item_id}", datePlayed="banana")),
    )
    probe.observe(
        "  and it stored nothing",
        "yes" if pristine({"UserData": trials.read()}) else "NO - the mark landed anyway",
    )
    trials.reset()


def report_edge_battery(probe: Probe, server: Server, trials: Trials, findings: Findings) -> None:
    """Where the reports' leniency starts, and what a well-formed report does not do.

    Rule 1 answers 204 for an id that names nothing - but a body that cannot *bind* refuses
    before any of that, and the difference is invisible from the spec's robustness rules alone.
    """
    probe.observe(
        "Stopped with a negative position",
        refusal(
            *server.post_raw(
                "/Sessions/Playing/Stopped",
                body={"ItemId": trials.item_id, "PositionTicks": -1},
            )
        ),
    )
    # Both binder failures on all three routes, because the *keys* differ per route: the
    # reference names its own action parameter in the errors dictionary, so this is where a
    # reproduction stops being free (plan section 6.1).
    for path in ("/Sessions/Playing", "/Sessions/Playing/Progress", "/Sessions/Playing/Stopped"):
        unparseable = refusal(*server.post_raw(path, raw_body=b"{not json"))
        unbindable = refusal(
            *server.post_raw(path, body={"ItemId": NOT_A_GUID, "PositionTicks": 1000})
        )
        probe.observe(f"{path}, a body that is not JSON", unparseable)
        probe.observe("  the same route, an ItemId that is not a GUID", unbindable)

    trials.reset()
    trials.start()
    trials.progress(trials.ticks(40))
    before = trials.read().get("PlaybackPositionTicks")
    status, _, _ = server.post_raw(
        "/Sessions/Playing/Progress", body={"ItemId": trials.item_id, "IsPaused": True}
    )
    after = trials.read().get("PlaybackPositionTicks")
    probe.observe(
        f"a Progress carrying no position ({status})",
        f"stored position {'unchanged' if after == before else f'moved to {after}'}",
    )
    findings.check(
        after == before,
        "plan section 6.1: a positionless Progress leaves the stored position alone",
    )

    trials.reset()
    server.post_raw(
        "/Sessions/Playing",
        body={"ItemId": trials.item_id, "PositionTicks": trials.ticks(30)},
    )
    started = trials.read()
    probe.observe("a Start carrying 30%", described(started, trials.runtime))
    findings.check(
        started.get("PlaybackPositionTicks") == 0,
        "spec 3.6: a Start's position is not written - the row stays where it was",
    )
    trials.reset()


def by_name_favourite_battery(probe: Probe, server: Server) -> None:
    """A favourite on an artist: Key's second calibration, on the item kind that has no file."""
    artist = find_pristine_artist(server)
    if artist is None:
        probe.note("no artist without user data; the by-name favourite battery did not run")
        return
    item_id = artist["Id"]
    try:
        status, _, payload = server.post_raw(f"/UserFavoriteItems/{item_id}")
        document = json.loads(payload or b"{}")
        probe.observe(
            f"POST /UserFavoriteItems on {artist['Name'][:30]!r} ({status})",
            f"IsFavorite={document.get('IsFavorite')}",
        )
        key, reported = document.get("Key"), document.get("ItemId")
        probe.observe(
            "  Key beside ItemId",
            f"Key={key!r} ItemId={reported!r} - "
            + (
                "the item's own GUID, dashed"
                if key and key.replace("-", "") == (reported or "")
                else "not the item id"
            ),
        )
    finally:
        server.delete_raw(f"/UserFavoriteItems/{item_id}")
        restored = server.get(f"/Items/{item_id}", UserId=server.user_id)
        if not pristine(restored):
            probe.note(f"artist {item_id} was NOT restored; clear its favourite by hand")


def run(server: Server, args) -> Probe:
    probe = Probe(
        script="probe_playstate.py",
        question="what do playback reports and played marks actually do to UserData?",
        document="specs/007-user-data-and-playstate/spec.md",
        section="sections 3.4, 3.6 and 3.7",
        expectation=(
            "as corrected at the 2026-08-28 review: a play is counted at Start; the six-branch "
            "rule runs on progress reports too; reports resolve last-writer-wins; a bare mark "
            "is max(count, 1); a sub-300s item stopped mid-way is played; a season mark "
            "cascades to its episodes and a favourite does not"
        ),
    )

    item = find_item(server)
    runtime = item["RunTimeTicks"]
    trials = Trials(server, item["Id"], runtime)
    findings = Findings()

    probe.observe("item", f"{item['Name'][:40]} ({item['Type']})")
    probe.observe("runtime", f"{runtime / TICKS_PER_SECOND / 60:.1f} min")

    try:
        # -- does Progress need MediaSourceId, and does it land without a Start? ----------------
        status = trials.progress(trials.ticks(20))
        landed = trials.read()
        probe.observe(f"Progress without MediaSourceId ({status})", described(landed, runtime))
        probe.observe(
            "  accepted, and it lands without any Start",
            "yes" if landed.get("PlaybackPositionTicks") == trials.ticks(20) else "NO",
        )
        trials.reset()

        report_cycle_battery(probe, trials, findings)
        unknown_item_battery(server, probe)
        mark_battery(server, probe, trials, findings)
        boundary_battery(probe, trials)
        bisection_battery(probe, trials)
        short_item_battery(server, probe, findings)
        cascade_battery(server, probe, findings)
        playing_session_battery(probe, server, trials, findings)
        refusal_battery(probe, server, trials)
        report_edge_battery(probe, server, trials, findings)
        by_name_favourite_battery(probe, server)
        if args.reap:
            reap_battery(server, probe, trials)
    finally:
        try:
            trials.reset()
            server.delete(f"/UserFavoriteItems/{trials.item_id}")
            restored = server.get(f"/Items/{trials.item_id}", UserId=server.user_id)
            if not pristine(restored):
                probe.note(
                    f"item {trials.item_id} was NOT restored to its original state; clear its "
                    "played status by hand"
                )
        except ProbeError:
            probe.note(f"could not restore item {trials.item_id}; clear its state by hand")

    probe.note(f"the reference's source defaults, for comparison: {REFERENCE_DEFAULTS}")
    probe.note(
        "These are server configuration rather than protocol, so record them in the "
        "documentation as the reference's defaults, not as fixed values. What Atrium must match "
        "is the shape of the rule and where it runs - on progress reports as well as stops."
    )

    if findings.contradictions:
        probe.conclude(
            "the measurement contradicts the reviewed documentation on: "
            + "; ".join(findings.contradictions),
            matches_documentation=False,
        )
    else:
        probe.conclude(
            "a play is counted at Start; the six-branch rule runs on progress reports too; "
            "reports resolve last-writer-wins, so an older progress position rewinds; a bare "
            "mark is max(count, 1) and only datePlayed increments; a sub-300s item stopped "
            "mid-way is played, not resumable; a season mark cascades to its episodes and a "
            "favourite does not",
            matches_documentation=True,
        )
    return probe


def _extra_arguments(parser) -> None:
    parser.add_argument(
        "--reap",
        action="store_true",
        help="Also measure OQ-4: go silent mid-playback and wait for the server to give up. "
        "Costs five to ten minutes of polling by construction.",
    )


if __name__ == "__main__":
    raise SystemExit(
        main(
            run,
            __doc__.splitlines()[0],
            needs_writes=True,
            extra_arguments=_extra_arguments,
            with_args=True,
        )
    )
