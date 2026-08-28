#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which constraints does /Audio/{id}/universal actually meet, and when does it redirect?

specs/008 OQ-4 and §3.6. Four questions against one short track:

- a constraint the source already satisfies: what do the direct-play headers look like?
- a sample-rate ceiling below the source: the answer is re-encoded, but the target rate comes
  from the five-step ladder Opus needs - `<=8000, <=12000, <=16000, <=24000, else 48000` -
  applied to **every** codec, so a 22050 ceiling is answered at 24000 and a 44100 ceiling at
  48000: above what the client stated. The restructure that scopes the ladder to Opus is
  merged upstream and in no 10.11.x `[prior-probe: upstream jellyfin/jellyfin#17537]`;
- the same request without `AudioCodec`: the reference's codec-less transcoding profile
  produces a broken ffmpeg invocation and the route answers `200` with an empty body;
- `enableRedirection` on a local file: no `302` - the redirect exists only for remote HTTP
  sources with EnableRemoteMedia `[source: Jellyfin.Api/Controllers/
  UniversalAudioController.cs:175 @ v10.11.11]`.

Needs --allow-writes: the constraint cases make the reference start real audio encodes. The
probe reads only the first bytes of each answer and closes, which is the same signal a
disconnecting client sends and triggers the reference's own kill path.

Usage:
    python3 tools/probe_universal_audio.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import urllib.parse

from _probe import Probe, ProbeError, Server, main


def opus_ladder(ceiling: int) -> int:
    """The rate the reference's -ar actually lands on for any codec, not only Opus."""
    for step in (8000, 12000, 16000, 24000):
        if ceiling <= step:
            return step
    return 48000


def flac_sample_rate(payload: bytes) -> int | None:
    """The sample rate a FLAC stream declares, from its STREAMINFO block. None if not FLAC."""
    if payload[:4] != b"fLaC" or len(payload) < 26:
        return None
    streaminfo = payload[8:]
    return (streaminfo[10] << 12) | (streaminfo[11] << 4) | (streaminfo[12] >> 4)


def pick_track(server: Server) -> tuple[str, str, int]:
    """A short audio track: (item id, container, sample rate)."""
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes="Audio",
        Recursive="true",
        SortBy="Runtime",
        SortOrder="Ascending",
        Fields="MediaSources",
        Limit=25,
    )
    for row in found.get("Items", []):
        for source in row.get("MediaSources", []):
            streams = [s for s in source.get("MediaStreams", []) if s.get("Type") == "Audio"]
            if streams and streams[0].get("SampleRate") and source.get("Container"):
                return row["Id"], source["Container"], streams[0]["SampleRate"]
    raise ProbeError("the library holds no audio track with a measurable sample rate")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_universal_audio.py",
        question="does /universal meet a stated ceiling, when is it empty, and does "
        "enableRedirection ever answer 302 for a local file?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="section 3.6",
        expectation=(
            "a satisfied constraint set answers the file with Content-Length and Accept-Ranges; "
            "a sample-rate ceiling below the source is re-encoded chunked with no "
            "Content-Length, but to the Opus ladder value (8/12/16/24/48 kHz), which can "
            "exceed the stated ceiling; the same request without AudioCodec answers 200 with "
            "an empty body (the codec-less transcoding profile breaks ffmpeg); and "
            "enableRedirection never redirects a local file - 200, not 302"
        ),
    )

    track_id, container, rate = pick_track(server)
    probe.observe("measured track", f"{container}, {rate} Hz")
    checks: list[bool] = []

    common = {
        "UserId": server.user_id or "",
        "DeviceId": "atrium-probe-0000",
        "api_key": server.token or "",
    }

    query = urllib.parse.urlencode({**common, "Container": container})
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=64
    )
    probe.observe(
        "satisfied constraints",
        f"{status}, Content-Length {headers.get('Content-Length')}, "
        f"Accept-Ranges {headers.get('Accept-Ranges')}",
    )
    checks.append(
        status == 200
        and headers.get("Content-Length") is not None
        and headers.get("Accept-Ranges") == "bytes"
    )

    ceiling = rate // 2
    query = urllib.parse.urlencode(
        {
            **common,
            "Container": "ogg",  # a container the track is not in, so direct play is off the table
            "TranscodingContainer": "flac",
            "TranscodingProtocol": "http",
            "AudioCodec": "flac",
            "MaxAudioSampleRate": ceiling,
        }
    )
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=65536
    )
    delivered = flac_sample_rate(body)
    expected = opus_ladder(ceiling)
    probe.observe(
        f"sample-rate ceiling {ceiling}",
        f"{status}, {len(body)}+ bytes, Content-Length {headers.get('Content-Length')}, "
        f"delivered rate {delivered} (ladder predicts {expected})",
    )
    if delivered is not None and delivered > ceiling:
        probe.note(
            f"The delivered rate exceeds the stated ceiling ({delivered} > {ceiling}): the "
            "Opus rate ladder is applied to every codec at 10.11.11, which is the defect "
            "recorded in behaviours section 3.2's family - fixed upstream by the same "
            "restructure, in no 10.11.x. Atrium honours the ceiling instead."
        )
    checks.append(status == 200 and headers.get("Content-Length") is None and delivered == expected)

    query = urllib.parse.urlencode(
        {
            **common,
            "Container": "ogg",
            "TranscodingContainer": "flac",
            "TranscodingProtocol": "http",
            "MaxAudioSampleRate": ceiling,
        }
    )
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=64
    )
    probe.observe(
        "same, without AudioCodec",
        f"{status}, {len(body)} bytes, Content-Length {headers.get('Content-Length')}",
    )
    checks.append(status == 200 and len(body) == 0)

    query = urllib.parse.urlencode({**common, "Container": container, "EnableRedirection": "true"})
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=16
    )
    probe.observe(
        "enableRedirection on a local file",
        f"{status}, Location {headers.get('Location') or 'absent'}",
    )
    checks.append(status == 200 and headers.get("Location") is None)

    probe.note(
        "The redirect branch requires SupportsDirectPlay, protocol Http, IsRemote and the "
        "user's EnableRemoteMedia all at once [source: Jellyfin.Api/Controllers/"
        "UniversalAudioController.cs:175 @ v10.11.11]; a library file is protocol File, so the "
        "branch is unreachable for everything a v1 library contains."
    )

    if all(checks):
        probe.conclude(
            "as documented: the ceiling is answered from the Opus ladder - which can exceed "
            "it - the codec-less request is an empty 200, and no local file is ever redirected",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
