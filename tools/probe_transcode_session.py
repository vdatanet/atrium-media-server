#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does production start at the seek point, follow the throttle configuration, and stop when
told?

specs/008 OQ-6, OQ-10 and OQ-11, measured on one re-encoding session:

- fetch the first segment, then stop fetching and watch the session's CompletionPercentage.
  Throttling is an **operator setting, off as shipped**: `EnableThrottling` defaults to false
  `[source: MediaBrowser.Model/Configuration/EncodingOptions.cs:23 @ v10.11.11]`, and when an
  operator enables it the transcoder is paused once it leads the last downloaded position by
  `max(ThrottleDelaySeconds, 60)` seconds, 180 by default `[source:
  MediaBrowser.Controller/MediaEncoding/TranscodingThrottler.cs:118-171 @ v10.11.11]`. The
  probe reads `/System/Configuration/encoding` when its account is an administrator and
  asserts the branch the server is actually configured for; otherwise it reports which of the
  two shapes it observed;
- request a segment near the end: the transcoder is restarted at that position - observable as
  the time to first byte and as CompletionPercentage jumping to the seek point;
- `DELETE /Videos/ActiveEncodings` without `playSessionId` refuses `400` naming the field;
  with `deviceId` and `playSessionId` it answers `204` and the session's TranscodingInfo is
  gone from /Sessions.

Needs --allow-writes: this probe deliberately makes the reference encode for about a minute.
It stops the session at the end - including on failure.

Usage:
    python3 tools/probe_transcode_session.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import json
import time

from _playback import (
    base_profile,
    fetch_main_playlist,
    negotiate,
    pick_video_source,
    stop_encoding,
)
from _probe import Probe, ProbeError, Server, main

#: The reference's throttle threshold when an operator turns throttling on, in seconds.
THROTTLE_GAP_SECONDS = 180


def completion(server: Server) -> float | None:
    for session in server.get("/Sessions"):
        if session.get("DeviceId") == "atrium-probe-0000" and session.get("TranscodingInfo"):
            return session["TranscodingInfo"].get("CompletionPercentage")
    return None


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_transcode_session.py",
        question="does production follow the throttle configuration, restart at a seek, and stop "
        "on DELETE /Videos/ActiveEncodings?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.4 and 3.8",
        expectation=(
            "with no client fetching, production runs unbounded when EnableThrottling is off "
            "(the shipped default) and pauses ThrottleDelaySeconds ahead of the last download "
            "when the operator turned it on - whichever the server's own configuration says; "
            "a request near the end restarts production at that position; DELETE without "
            "playSessionId is a validation 400 naming the field, and with both parameters a "
            "204 that removes the session's TranscodingInfo"
        ),
    )

    source = pick_video_source(server)
    if source.runtime_ticks < 600 * 10_000_000:
        raise ProbeError(
            "the picked source is under ten minutes; the gap observation needs a "
            "longer film to be meaningful"
        )
    duration_seconds = source.runtime_ticks / 10_000_000
    probe.observe("measured source", f"video {source.video_codec}, {duration_seconds:.0f}s long")

    profile = base_profile(
        [
            {
                "Container": source.other_container(),
                "Type": "Video",
                "VideoCodec": source.other_video_codec(),
                "AudioCodec": "aac",
            }
        ],
        transcoding=[
            {
                "Container": "ts",
                "Type": "Video",
                "VideoCodec": source.other_video_codec(),
                "AudioCodec": "aac",
                "Protocol": "hls",
                "Context": "Streaming",
                "MinSegments": 1,
                "BreakOnNonKeyFrames": True,
            }
        ],
    )
    status, data = negotiate(server, source.item_id, profile)
    url = data["MediaSources"][0].get("TranscodingUrl")
    if not url:
        raise ProbeError("the codec-rejecting profile produced no TranscodingUrl")
    play_session_id = data["PlaySessionId"]
    checks: list[bool] = []
    try:
        _, segments, _durations = fetch_main_playlist(server, source.item_id, url)
        status, _, _ = server._request("GET", segments[0], raw=True)
        if status != 200:
            raise ProbeError(f"first segment answered {status}")

        # OQ-10: stop fetching; where does production go?
        throttling = None
        try:
            config = server.get("/System/Configuration/encoding")
            throttling = bool(config.get("EnableThrottling"))
            gap = max(int(config.get("ThrottleDelaySeconds") or 180), 60)
            probe.observe(
                "server encoding configuration",
                f"EnableThrottling={throttling}, ThrottleDelaySeconds={gap}",
            )
        except ProbeError:
            gap = THROTTLE_GAP_SECONDS
            probe.observe(
                "server encoding configuration",
                "not readable by this account; asserting only the observed shape",
            )
        samples = []
        for _ in range(4):
            time.sleep(15)
            percent = completion(server)
            samples.append(percent)
        probe.observe(
            "completion, sampled every 15s, nothing fetched",
            " -> ".join("?" if p is None else f"{p:.1f}%" for p in samples),
        )
        produced = [p / 100.0 * duration_seconds for p in samples if p is not None]
        if not produced:
            raise ProbeError(
                "the session stopped reporting CompletionPercentage; the gap question cannot "
                "be answered on this run"
            )
        drift = max(produced) - min(produced)
        stalled_at_gap = drift < 60 and gap - 60 <= max(produced) <= gap + 180
        ran_past_gap = max(produced) > gap + 60
        probe.observe(
            "media seconds produced unfetched",
            f"{max(produced):.0f}s, drift {drift:.0f}s over the window "
            f"(a throttled server pauses {gap}s ahead of the last download)",
        )
        if throttling is None:
            checks.append(stalled_at_gap or ran_past_gap)
        elif throttling:
            checks.append(stalled_at_gap)
        else:
            checks.append(ran_past_gap)

        # OQ-11: seek near the end.
        target = int(len(segments) * 0.9)
        started = time.monotonic()
        status, _, body = server._request("GET", segments[target], raw=True)
        elapsed = time.monotonic() - started
        time.sleep(2)
        percent = completion(server)
        probe.observe(
            f"segment {target} of {len(segments)} (~90%)",
            f"{status}, {len(body)} bytes in {elapsed:.1f}s; completion now "
            f"{'?' if percent is None else f'{percent:.1f}%'}",
        )
        checks.append(status == 200 and elapsed < 60)
        checks.append(percent is not None and percent > 80)

        # OQ-6: the stop route's parameters and its effect.
        status, _, body = server.delete_raw("/Videos/ActiveEncodings", deviceId="atrium-probe-0000")
        errors = json.loads(body).get("errors", {}) if body else {}
        probe.observe(
            "DELETE without playSessionId", f"{status}, errors keys {sorted(errors) or 'none'}"
        )
        checks.append(status == 400 and "playSessionId" in errors)

        status = stop_encoding(server, play_session_id)
        time.sleep(2)
        remaining = completion(server)
        probe.observe(
            "DELETE with deviceId and playSessionId",
            f"{status}; TranscodingInfo afterwards: "
            f"{'gone' if remaining is None else f'{remaining:.1f}%'}",
        )
        checks.append(status == 204 and remaining is None)
    finally:
        stop_encoding(server, play_session_id)

    if all(checks):
        probe.conclude(
            "as documented: production follows the server's throttle configuration, restarts "
            "at the requested position, and the stop route validates its parameters and "
            "actually stops the work",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
