#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What shape is the HLS playlist, and are the segments deterministic, sized and seekable?

specs/008 OQ-3 and §3.7's four rules. One re-encoding session and one stream-copy session are
negotiated; their media playlists are fetched **before any segment is produced** - if the whole
playlist arrives complete and marked ended in well under a second, the boundaries are being
predicted up front, not derived from produced output. Then the first segment is fetched twice
(same bytes?), and one is fetched out of order.

Needs --allow-writes: fetching segments starts real encodes in the reference's scratch space.
The probe fetches three segments per session and stops both - including on failure.

Usage:
    python3 tools/probe_hls.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import time

from _playback import (
    base_profile,
    fetch_main_playlist,
    negotiate,
    pick_video_source,
    stop_encoding,
)
from _probe import Probe, ProbeError, Server, main


def _session(server: Server, source, profile, label: str, probe: Probe):
    """Negotiate, fetch the media playlist, and report its shape. Returns what the caller needs."""
    _status, data = negotiate(server, source.item_id, profile)
    one = data["MediaSources"][0]
    url = one.get("TranscodingUrl")
    if not url:
        raise ProbeError(f"the {label} profile produced no TranscodingUrl")
    started = time.monotonic()
    text, segments, durations = fetch_main_playlist(server, source.item_id, url)
    elapsed = time.monotonic() - started
    lines = text.splitlines()
    complete = "#EXT-X-ENDLIST" in lines
    vod = "#EXT-X-PLAYLIST-TYPE:VOD" in lines
    body_uniform = len(set(durations[:-1])) == 1 if len(durations) > 2 else True
    last_shorter = durations[-1] <= durations[0] if len(durations) > 1 else True
    probe.observe(
        f"{label}: playlist",
        f"{len(segments)} segments in {elapsed:.2f}s, VOD={vod}, ENDLIST={complete}, "
        f"body duration {durations[0] if durations else '?'}s uniform={body_uniform}, "
        f"last {durations[-1] if durations else '?'}s",
    )
    per_segment = "runtimeTicks=" in segments[0] and "actualSegmentLengthTicks=" in segments[0]
    probe.observe(
        f"{label}: per-segment query", f"runtime+actualSegmentLength ticks: {per_segment}"
    )
    ok = complete and vod and body_uniform and last_shorter and per_segment and elapsed < 5.0
    return data["PlaySessionId"], segments, ok


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_hls.py",
        question="is the playlist complete up front, uniform, and are segments the same bytes "
        "on a retry and served out of order?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.7 and 6",
        expectation=(
            "the media playlist arrives complete and ENDLIST-marked before any segment is "
            "produced (boundaries are predicted, not derived); every body segment shares one "
            "duration with only the last shorter; each segment URL carries runtimeTicks and "
            "actualSegmentLengthTicks; a re-requested segment is byte-identical within the "
            "session; an out-of-order segment is served; and segments carry Content-Length "
            "and Accept-Ranges: bytes"
        ),
    )

    source = pick_video_source(server)
    probe.observe("measured source", f"{source.container}, video {source.video_codec}")

    # The transcoding target deliberately excludes the source's own codec, so the session
    # cannot degenerate into a stream copy: this half of the probe is about re-encoded output.
    reencode = base_profile(
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
    copy = base_profile(
        [
            {
                "Container": source.other_container(),
                "Type": "Video",
                "VideoCodec": source.video_codec,
                "AudioCodec": ",".join(source.audio_codecs),
            }
        ],
        transcoding=[
            {
                "Container": "ts",
                "Type": "Video",
                "VideoCodec": f"{source.video_codec},h264",
                "AudioCodec": ",".join(source.audio_codecs) + ",aac",
                "Protocol": "hls",
                "Context": "Streaming",
                "MinSegments": 1,
                "BreakOnNonKeyFrames": True,
            }
        ],
    )

    checks: list[bool] = []
    sessions: list[str] = []
    try:
        play_session_id, segments, shape_ok = _session(server, source, reencode, "re-encode", probe)
        sessions.append(play_session_id)
        checks.append(shape_ok)

        status, headers, first = server._request("GET", segments[0], raw=True)
        probe.observe(
            "re-encode: first segment",
            f"{status}, {len(first)} bytes, Content-Length {headers.get('Content-Length')}, "
            f"Accept-Ranges {headers.get('Accept-Ranges')}",
        )
        checks.append(
            status == 200
            and headers.get("Content-Length") == str(len(first))
            and headers.get("Accept-Ranges") == "bytes"
        )

        status, _, again = server._request("GET", segments[0], raw=True)
        probe.observe("re-encode: same segment re-requested", f"identical: {first == again}")
        checks.append(first == again)

        out_of_order = min(10, len(segments) - 1)
        status, headers, body = server._request("GET", segments[out_of_order], raw=True)
        probe.observe(
            f"re-encode: segment {out_of_order} out of order",
            f"{status}, {len(body)} bytes",
        )
        checks.append(status == 200 and len(body) > 0)

        play_session_id, segments, shape_ok = _session(server, source, copy, "copy", probe)
        sessions.append(play_session_id)
        checks.append(shape_ok)
    finally:
        for play_session_id in sessions:
            stopped = stop_encoding(server, play_session_id)
            probe.observe("cleanup DELETE /Videos/ActiveEncodings", stopped)

    probe.note(
        "The two sessions' segment durations differ (the re-encode's boundaries are the "
        "forced-keyframe cadence, the copy's follow the source), which is why the assertion is "
        "uniformity within a session, never a particular number of seconds."
    )

    if all(checks):
        probe.conclude(
            "as documented: predicted complete playlists, uniform bodies with a short tail, "
            "per-segment tick parameters, sized range-capable segments, byte-identical "
            "retries, out-of-order service",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
