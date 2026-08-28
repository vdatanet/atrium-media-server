#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does the reference put in a TranscodingUrl, and does it copy the stream the profile
accepts?

specs/008 OQ-7, OQ-8 and OQ-9. A device profile that accepts the source's video codec but
rejects its audio codec is posted; the negotiation's TranscodingUrl is taken apart; the master
playlist is fetched (how many variants?); and one segment is produced, so that the session's
TranscodingInfo - and ffprobe, where the machine has one - can say whether the accepted video
stream was copied or re-encoded alongside the audio.

Needs --allow-writes: fetching a segment makes the reference start a real encode in its scratch
space. The probe fetches one segment, reads the answer, and stops the session - including on
failure.

Usage:
    python3 tools/probe_transcode_decision.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.parse

from _playback import (
    base_profile,
    dashed,
    fetch_main_playlist,
    negotiate,
    pick_video_source,
    stop_encoding,
)
from _probe import Probe, ProbeError, Server, main

#: Parameters the measured 10.11.11 URL always carries. PascalCase on the wire.
EXPECTED_PARAMS = (
    "DeviceId",
    "MediaSourceId",
    "VideoCodec",
    "AudioCodec",
    "SegmentContainer",
    "PlaySessionId",
    "ApiKey",
    "Tag",
    "TranscodeReasons",
)


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_transcode_decision.py",
        question="what goes into the TranscodingUrl, and is the accepted stream copied?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.3, 3.4 and 3.7",
        expectation=(
            "an audio-only rejection answers a master.m3u8 TranscodingUrl at "
            "/videos/{dashed-id}/master.m3u8 with PascalCase parameters, "
            "TranscodeReasons=AudioCodecNotSupported, TranscodingContainer ts and sub-protocol "
            "hls; the master playlist advertises exactly one variant; and the delivered "
            "segments carry the source's video codec untouched (the copy), with only the audio "
            "re-encoded"
        ),
    )

    source = pick_video_source(server)
    probe.observe(
        "measured source",
        f"{source.container}, video {source.video_codec}, audio {'/'.join(source.audio_codecs)}",
    )

    # Accept the container and the video codec; reject every audio codec the file has.
    profile = base_profile(
        [
            {
                "Container": source.container,
                "Type": "Video",
                "VideoCodec": source.video_codec,
                "AudioCodec": source.other_audio_codec(),
            }
        ],
        transcoding=[
            {
                "Container": "ts",
                "Type": "Video",
                "VideoCodec": f"{source.video_codec},h264",
                "AudioCodec": "aac",
                "Protocol": "hls",
                "Context": "Streaming",
                "MinSegments": 1,
                "BreakOnNonKeyFrames": True,
            }
        ],
    )
    status, data = negotiate(server, source.item_id, profile)
    one = data["MediaSources"][0]
    url = one.get("TranscodingUrl")
    if not url:
        probe.observe("negotiation", f"{status}, no TranscodingUrl")
        probe.conclude("the audio-only rejection produced no TranscodingUrl", False)
        return probe

    checks: list[bool] = []
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    probe.observe("TranscodingUrl path", parsed.path)
    checks.append(parsed.path == f"/videos/{dashed(source.item_id)}/master.m3u8")
    missing = [name for name in EXPECTED_PARAMS if name not in query]
    probe.observe("parameters", f"{len(query)} total, missing of the expected: {missing or 'none'}")
    checks.append(not missing)
    probe.observe("TranscodeReasons", query.get("TranscodeReasons", ["absent"])[0])
    checks.append(query.get("TranscodeReasons") == ["AudioCodecNotSupported"])
    probe.observe("Tag equals the source ETag", query.get("Tag", [None])[0] == one.get("ETag"))
    probe.observe(
        "TranscodingContainer / SubProtocol",
        f"{one.get('TranscodingContainer')!r} / {one.get('TranscodingSubProtocol')!r}",
    )
    checks.append(one.get("TranscodingContainer") == "ts")
    checks.append(one.get("TranscodingSubProtocol") == "hls")
    probe.observe("leading '?&'", url.split("master.m3u8", 1)[1][:2] == "?&")

    play_session_id = data["PlaySessionId"]
    try:
        status, _, master = server._request("GET", url, raw=True)
        variants = [
            line for line in master.decode().splitlines() if line.startswith("#EXT-X-STREAM-INF")
        ]
        images = [
            line
            for line in master.decode().splitlines()
            if line.startswith("#EXT-X-IMAGE-STREAM-INF")
        ]
        probe.observe(
            "master playlist", f"{len(variants)} variant(s), {len(images)} image stream(s)"
        )
        checks.append(len(variants) == 1)

        _, segments, _ = fetch_main_playlist(server, source.item_id, url)
        status, headers, segment = server._request("GET", segments[0], raw=True)
        probe.observe(
            "first segment",
            f"{status}, {len(segment)} bytes, Content-Length {headers.get('Content-Length')}",
        )
        checks.append(status == 200 and headers.get("Content-Length") is not None)

        time.sleep(2)
        info = None
        for session in server.get("/Sessions"):
            if session.get("DeviceId") == "atrium-probe-0000" and session.get("TranscodingInfo"):
                info = session["TranscodingInfo"]
        if info is None:
            raise ProbeError("no TranscodingInfo appeared for the probe's device")
        probe.observe(
            "TranscodingInfo",
            f"IsVideoDirect={info.get('IsVideoDirect')}, IsAudioDirect={info.get('IsAudioDirect')}"
            f", VideoCodec={info.get('VideoCodec')!r}, AudioCodec={info.get('AudioCodec')!r}",
        )
        checks.append(info.get("IsVideoDirect") is True and info.get("IsAudioDirect") is False)
        checks.append(info.get("VideoCodec") == source.video_codec)

        ffprobe = shutil.which("ffprobe")
        if ffprobe:
            result = subprocess.run(  # noqa: S603 - inspecting bytes this probe fetched
                [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", "-"],
                input=segment,
                capture_output=True,
                check=False,
            )
            names = {
                stream.get("codec_type"): stream.get("codec_name")
                for stream in json.loads(result.stdout or b"{}").get("streams", [])
            }
            probe.observe("ffprobe on the segment", names or "unparseable")
            if names:
                checks.append(names.get("video") == source.video_codec)
                checks.append(names.get("audio") == "aac")
        else:
            probe.note(
                "ffprobe not on PATH: the byte-level codec check fell back to the "
                "session's TranscodingInfo alone."
            )
    finally:
        stopped = stop_encoding(server, play_session_id)
        probe.observe("cleanup DELETE /Videos/ActiveEncodings", stopped)

    if all(checks):
        probe.conclude(
            "as documented: one variant, the measured URL anatomy, and the compatible video "
            "stream copied while only the audio is re-encoded",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
