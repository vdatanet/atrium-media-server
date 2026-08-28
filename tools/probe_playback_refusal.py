#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""When no source can be played by the profile, is the answer `200` with an `ErrorCode`?

specs/008 §3's error table stated this without a citation: a profile that can play nothing gets
`200` with an `ErrorCode` in the body, **not** a `4xx`, because clients branch on the code to
show a useful message. This is the measurement: a `DeviceProfile` that supports nothing, with
direct play, direct stream and transcoding all disabled, posted against a real video item.

Read-only: `PlaybackInfo` negotiates and reserves nothing until a delivery request follows, and
none does.

Usage:
    python3 tools/probe_playback_refusal.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import json

from _probe import Probe, ProbeError, Server, main

#: A profile that can play nothing at all: no direct-play container, no transcoding target.
NOTHING_PLAYS = {
    "MaxStreamingBitrate": 1,
    "DirectPlayProfiles": [],
    "TranscodingProfiles": [],
    "CodecProfiles": [],
    "ContainerProfiles": [],
    "SubtitleProfiles": [],
}


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_playback_refusal.py",
        question="when no source can be played by the profile, is it 200 with an ErrorCode?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="section 3, the error table",
        expectation=(
            "200, never a 4xx; the refusal is the source's own capability flags - "
            "SupportsDirectPlay, SupportsDirectStream and SupportsTranscoding all false, no "
            "TranscodingUrl - and no ErrorCode is set"
        ),
    )

    found = server.get(
        "/Items", UserId=server.user_id, IncludeItemTypes="Movie", Recursive="true", Limit=1
    )
    rows = found.get("Items", [])
    if not rows:
        raise ProbeError("the library holds no movie to negotiate against")
    item_id = rows[0]["Id"]

    status, _, payload = server.post_raw(
        f"/Items/{item_id}/PlaybackInfo",
        body={
            "UserId": server.user_id,
            "DeviceProfile": NOTHING_PLAYS,
            "EnableDirectPlay": False,
            "EnableDirectStream": False,
            "EnableTranscoding": False,
            "AutoOpenLiveStream": False,
        },
    )
    probe.observe("POST /Items/{id}/PlaybackInfo", f"status {status}")

    body = json.loads(payload) if payload else {}
    error_code = body.get("ErrorCode")
    sources = body.get("MediaSources", [])
    probe.observe("ErrorCode", repr(error_code) if error_code is not None else "absent")
    probe.observe("MediaSources", f"{len(sources)} source(s)")
    if sources:
        one = sources[0]
        probe.observe(
            "source capabilities",
            ", ".join(
                f"{key}={one.get(key)}"
                for key in ("SupportsDirectPlay", "SupportsDirectStream", "SupportsTranscoding")
            ),
        )

    all_false = sources and not any(
        sources[0].get(key)
        for key in ("SupportsDirectPlay", "SupportsDirectStream", "SupportsTranscoding")
    )
    if status == 200 and error_code is None and all_false:
        probe.conclude(
            "200 with every capability flag false and no ErrorCode - the refusal is the flags, "
            "never a 4xx and never a code. (The 008 draft's first wording said an ErrorCode "
            "arrives here; measured 2026-08-28, none does, in four request shapes.)",
            matches_documentation=True,
        )
    elif status == 200:
        probe.conclude(
            f"200 but not the measured refusal shape: ErrorCode={error_code!r}, "
            f"flags all false={bool(all_false)}",
            matches_documentation=False,
        )
    else:
        probe.conclude(f"answered {status}, not 200", matches_documentation=False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
