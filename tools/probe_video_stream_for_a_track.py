#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a `/Videos/{id}/stream` URL answer when the id names an audio track?

docs/compatibility/api-surface-v1.md §4 carried this on a `[client-contract:]` citation — the
video client's own conformance document, which that document itself calls "a lead, not a
measurement". The claim matters because it is why the client builds `/Audio/{id}/universal` by
hand for music instead of reusing its video path. This is the measurement.

Read-only: the request is expected to refuse, and carries a one-byte Range so that even an
unexpected success cannot stream a file into the probe.

Usage:
    python3 tools/probe_video_stream_for_a_track.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from _probe import Probe, ProbeError, Server, main


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_video_stream_for_a_track.py",
        question="what does /Videos/{id}/stream answer when the id names an audio track?",
        document="docs/compatibility/api-surface-v1.md",
        section="section 4",
        expectation="404 — the video route does not serve a music track",
    )

    found = server.get(
        "/Items", UserId=server.user_id, IncludeItemTypes="Audio", Recursive="true", Limit=1
    )
    rows = found.get("Items", [])
    if not rows:
        raise ProbeError("the library holds no audio track to ask about")
    track_id = rows[0]["Id"]

    status, headers, body = server._request(
        "GET",
        f"/Videos/{track_id}/stream",
        extra_headers={"Range": "bytes=0-0"},
        raw=True,
    )
    probe.observe("GET /Videos/{trackId}/stream", f"{status}, {len(body)} byte body")
    content_type = headers.get("Content-Type")
    probe.observe("Content-Type", content_type or "absent")

    if status == 404:
        probe.conclude(
            "404, as the client-contract lead said - the video route refuses a track, so a "
            "music client must build /Audio/{id}/universal itself",
            matches_documentation=True,
        )
    else:
        probe.conclude(f"answered {status}, not the documented 404", matches_documentation=False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
