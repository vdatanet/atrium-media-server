#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a playback-stopped report do to UserData?

Answers 007 OQ-2 - the thresholds that decide what appears in "continue watching" - and along the
way discharges the prior-probe debt on whether /Sessions/Playing/Progress requires MediaSourceId,
since the probe has to send those reports anyway.

Two thresholds govern the outcome, and both are directly observable to a user as an item that
reappears in "continue watching" when it should not, or vanishes when it should not:

    upper   stopping past this fraction of the runtime marks the item played and clears
            the position, so it leaves the resume list
    lower   stopping below this fraction stores no position at all, so thirty seconds into a
            film does not fill the resume list with noise

The probe finds each by binary search: report a stop at a candidate position, read the item back,
reset, repeat. The lower threshold is searched only below the upper one, because above it the
position is cleared and the property stops being monotonic.

For comparison, the reference's defaults read from its source
[source: MediaBrowser.Model/Configuration/ServerConfiguration.cs:133-145 @ v10.11.11] are
MinResumePct=5, MaxResumePct=90 and MinResumeDurationSeconds=300. They are server configuration,
so an operator may have changed them.

Writes: reports playback against one item, then restores it. The item is chosen to have no user
data at all, so restoring it is exact.

Usage:
    python3 tools/probe_playstate.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from _probe import Probe, ProbeError, Server, main

TICKS_PER_SECOND = 10_000_000
MIN_RUNTIME_SECONDS = 600  # comfortably above the reference's 300s resume-eligibility floor

REFERENCE_DEFAULTS = "MinResumePct=5, MaxResumePct=90, MinResumeDurationSeconds=300"


def pristine(item: dict) -> bool:
    data = item.get("UserData") or {}
    return (
        not data.get("Played")
        and not data.get("PlayCount")
        and not data.get("PlaybackPositionTicks")
    )


def find_item(server: Server) -> dict:
    """A long item with no user data, so the probe is both meaningful and exactly reversible."""
    for item_type in ("Movie", "Episode", "Audio"):
        found = server.get(
            "/Items", Recursive="true", IncludeItemTypes=item_type,
            Limit=100, SortBy="Random", UserId=server.user_id,
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


class Trials:
    """One stop-report trial: reset, play, stop at a position, read the result back."""

    def __init__(self, server: Server, item_id: str, runtime: int) -> None:
        self.server, self.item_id, self.runtime = server, item_id, runtime
        self.count = 0

    def reset(self) -> None:
        self.server.delete(f"/UserPlayedItems/{self.item_id}")

    def stop_at(self, pct: float) -> dict:
        self.count += 1
        position = int(self.runtime * pct / 100)
        self.reset()
        self.server.post("/Sessions/Playing", body={
            "ItemId": self.item_id, "PositionTicks": 0, "PlayMethod": "DirectPlay",
            "CanSeek": True, "IsPaused": False,
        })
        self.server.post("/Sessions/Playing/Stopped", body={
            "ItemId": self.item_id, "PositionTicks": position,
        })
        item = self.server.get(f"/Items/{self.item_id}", UserId=self.server.user_id)
        return item.get("UserData") or {}


def boundary(low: float, high: float, holds, precision: float = 0.5) -> float:
    """Smallest value in (low, high] where `holds` becomes true, by bisection."""
    while high - low > precision:
        middle = (low + high) / 2
        if holds(middle):
            high = middle
        else:
            low = middle
    return high


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playstate.py",
        question="what does a playback-stopped report do to UserData?",
        document="specs/007-user-data-and-playstate/spec.md",
        section="section 3.7",
        expectation=None,  # the documentation states no numbers; there is nothing to contradict
    )

    item = find_item(server)
    runtime = item["RunTimeTicks"]
    seconds = runtime / TICKS_PER_SECOND
    trials = Trials(server, item["Id"], runtime)

    probe.observe("item", f"{item['Name'][:40]} ({item['Type']})")
    probe.observe("runtime", f"{seconds / 60:.1f} min")

    try:
        # -- does Progress need MediaSourceId? --------------------------------------------------
        try:
            server.post("/Sessions/Playing/Progress", body={
                "ItemId": item["Id"], "PositionTicks": int(runtime * 0.2), "IsPaused": False,
            })
            probe.observe("Progress without MediaSourceId", "accepted")
        except ProbeError as exc:
            probe.observe("Progress without MediaSourceId", f"REJECTED - {exc}")
        trials.reset()

        # -- upper threshold: where does it become played? --------------------------------------
        if trials.stop_at(99).get("Played") is not True:
            raise ProbeError(
                "stopping at 99% of the runtime did not mark the item played, so there is no "
                "upper threshold to find by this method"
            )
        if trials.stop_at(1).get("Played") is True:
            raise ProbeError("stopping at 1% marked the item played; the search assumes it does not")

        upper = boundary(1, 99, lambda pct: trials.stop_at(pct).get("Played") is True)
        probe.observe("upper threshold", f"{upper:.1f}% of runtime  ({upper * seconds / 100:.0f}s)")

        # -- lower threshold: below which is the position discarded? ----------------------------
        # Searched strictly below the upper threshold: above it the position is cleared, so the
        # property is not monotonic across the whole range.
        ceiling = min(upper - 1, 50)
        if trials.stop_at(ceiling).get("PlaybackPositionTicks", 0) <= 0:
            probe.observe("lower threshold", f"not found below {ceiling:.1f}%")
            lower = None
        else:
            lower = boundary(
                0, ceiling,
                lambda pct: trials.stop_at(pct).get("PlaybackPositionTicks", 0) > 0,
            )
            probe.observe(
                "lower threshold", f"{lower:.1f}% of runtime  ({lower * seconds / 100:.0f}s)"
            )

        probe.observe("trials", trials.count)
    finally:
        try:
            trials.reset()
            restored = server.get(f"/Items/{item['Id']}", UserId=server.user_id)
            if not pristine(restored):
                probe.note(
                    f"item {item['Id']} was NOT restored to its original state; clear its played "
                    "status by hand"
                )
        except ProbeError:
            probe.note(f"could not restore item {item['Id']}; clear its played status by hand")

    probe.note(f"the reference's source defaults, for comparison: {REFERENCE_DEFAULTS}")
    probe.note(
        "These are server configuration rather than protocol, so record them in the documentation "
        "as the reference's defaults, not as fixed values. What Atrium must match is the shape of "
        "the rule - a percentage ceiling and a floor - and its own defaults should be these."
    )

    lower_text = f"{lower:.1f}%" if lower is not None else "not detected"
    probe.conclude(
        f"stopping past {upper:.1f}% of the runtime marks the item played and clears its "
        f"position; below {lower_text} no position is stored. Between the two, the position is "
        "kept and the item is resumable",
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
