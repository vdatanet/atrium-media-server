#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What shape is the HLS playlist, where does its cadence come from, and are the segments
deterministic, sized and seekable?

specs/008 OQ-3 and section 3.7's four rules, plus the reading plan section 6.8 left owed to 008
T10: **the exact rounding rule behind the measured 3.004 s**. One re-encoding session and one
stream-copy session are negotiated; their media playlists are fetched **before any segment is
produced** - if the whole playlist arrives complete and marked ended in well under a second, the
boundaries are being predicted up front, not derived from produced output. Then the first segment
is fetched twice (same bytes?), and one is fetched out of order.

Four batteries were added at T10, all of them playlist-only and therefore free of encoding cost:

* **the cadence matrix** - the same source negotiated at five requested segment lengths, so the
  scaling is measured as a function rather than read off one number;
* **the verbatim playlists** - the master's variant line and the media playlist's header, because
  a renderer is judged on bytes and not on a summary of them;
* **the copy bucketing question** - whether a stream copy's boundaries follow the source's own
  keyframes or an equal-length grid, asked of one container and then of another;
* **the refusal shapes** of both playlist routes, which plan section 6.8 leaves owed to the task
  that lands them.

Needs --allow-writes: fetching segments starts real encodes in the reference's scratch space.
The probe fetches three segments and stops every session it opened - including on failure.

Usage:
    python3 tools/probe_hls.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import time
import urllib.parse
import uuid
from typing import Any

from _playback import (
    VideoSource,
    base_profile,
    fetch_playlists,
    negotiate,
    pick_video_source,
    stop_encoding,
)
from _probe import Probe, ProbeError, Server, main

#: The requested segment lengths the cadence matrix asks for. `None` is "state none", which is
#: what every real client sends and what the measured 3.004 s came from.
REQUESTED_LENGTHS: tuple[int | None, ...] = (None, 1, 2, 5, 10)

#: How many characters of a playlist body an observation prints. The media playlists here run to
#: thousands of segments; the header and the first two entries are what the shape lives in.
EXCERPT = 420


def _fresh_device() -> str:
    """A device nobody has used before.

    The reference names its transcode output from the media path, the user agent, the device and
    the play session, so a request that cannot be produced at all can be answered with a
    *neighbouring* request's bytes. Every hand-built query below therefore carries its own device
    (behaviours section 3.2's probe notes)."""
    return f"atrium-probe-{uuid.uuid4().hex[:12]}"


def _encode_profile(source: VideoSource, segment_length: int | None = None) -> dict[str, Any]:
    """A profile whose only playable answer is a re-encode into ts/h264.

    The transcoding target deliberately excludes the source's own codec, so the session cannot
    degenerate into a stream copy: this half of the probe is about re-encoded output.
    """
    target: dict[str, Any] = {
        "Container": "ts",
        "Type": "Video",
        "VideoCodec": source.other_video_codec(),
        "AudioCodec": "aac",
        "Protocol": "hls",
        "Context": "Streaming",
        "MinSegments": 1,
        "BreakOnNonKeyFrames": True,
    }
    if segment_length is not None:
        target["SegmentLength"] = segment_length
    return base_profile(
        [
            {
                "Container": source.other_container(),
                "Type": "Video",
                "VideoCodec": source.other_video_codec(),
                "AudioCodec": "aac",
            }
        ],
        transcoding=[target],
    )


def _copy_profile(source: VideoSource, segment_length: int | None = None) -> dict[str, Any]:
    """A profile that rejects the container and accepts every codec: the stream-copy path."""
    target: dict[str, Any] = {
        "Container": "ts",
        "Type": "Video",
        "VideoCodec": f"{source.video_codec},h264",
        "AudioCodec": ",".join(source.audio_codecs) + ",aac",
        "Protocol": "hls",
        "Context": "Streaming",
        "MinSegments": 1,
        "BreakOnNonKeyFrames": True,
    }
    if segment_length is not None:
        target["SegmentLength"] = segment_length
    return base_profile(
        [
            {
                "Container": source.other_container(),
                "Type": "Video",
                "VideoCodec": source.video_codec,
                "AudioCodec": ",".join(source.audio_codecs),
            }
        ],
        transcoding=[target],
    )


def _session(server: Server, source: VideoSource, profile, label: str, probe: Probe):
    """Negotiate, fetch both playlists, and report their shape. Returns what the caller needs."""
    _status, data = negotiate(server, source.item_id, profile)
    one = data["MediaSources"][0]
    url = one.get("TranscodingUrl")
    if not url:
        raise ProbeError(f"the {label} profile produced no TranscodingUrl")
    started = time.monotonic()
    playlists = fetch_playlists(server, source.item_id, url)
    elapsed = time.monotonic() - started
    durations = playlists.durations
    lines = playlists.main.splitlines()
    complete = "#EXT-X-ENDLIST" in lines
    vod = "#EXT-X-PLAYLIST-TYPE:VOD" in lines
    body_uniform = len(set(durations[:-1])) == 1 if len(durations) > 2 else True
    last_shorter = durations[-1] <= durations[0] if len(durations) > 1 else True
    probe.observe(
        f"{label}: playlist",
        f"{len(playlists.segments)} segments in {elapsed:.2f}s, VOD={vod}, ENDLIST={complete}, "
        f"body duration {durations[0] if durations else '?'}s uniform={body_uniform}, "
        f"last {durations[-1] if durations else '?'}s",
    )
    per_segment = (
        "runtimeTicks=" in playlists.segments[0]
        and "actualSegmentLengthTicks=" in playlists.segments[0]
    )
    probe.observe(
        f"{label}: per-segment query", f"runtime+actualSegmentLength ticks: {per_segment}"
    )
    ok = complete and vod and body_uniform and last_shorter and per_segment and elapsed < 5.0
    return data["PlaySessionId"], playlists, ok


def _record(probe: Probe, label: str, playlists) -> None:
    """Both playlists verbatim, and whether each response's own length agrees with its body.

    A renderer is judged on bytes, so the line ending is measured rather than assumed: the count
    of carriage returns is the whole question, and a `Content-Length` that equals the character
    count settles that the body is ASCII as well.
    """
    variants = [
        line for line in playlists.master.splitlines() if line.startswith("#EXT-X-STREAM-INF")
    ]
    probe.observe(f"{label}: master, whole", playlists.master)
    probe.observe(f"{label}: master variants", f"{len(variants)} #EXT-X-STREAM-INF lines")
    probe.observe(
        f"{label}: master headers",
        f"{playlists.master_headers.get('Content-Type')}, Content-Length "
        f"{playlists.master_headers.get('Content-Length') or 'absent'}, Expires "
        f"{playlists.master_headers.get('Expires')}, {len(playlists.master)} characters, "
        f"{playlists.master.count(chr(13))} carriage returns",
    )
    probe.observe(
        f"{label}: master header names",
        ", ".join(sorted(playlists.master_headers)),
    )
    header = playlists.main.split("#EXTINF", 1)[0]
    probe.observe(f"{label}: media playlist header", header.replace("\n", " | "))
    first_entry = "\n".join(playlists.main.splitlines()[5:7])
    probe.observe(f"{label}: media playlist first entry", first_entry)
    probe.observe(
        f"{label}: media headers",
        f"{playlists.main_headers.get('Content-Type')}, Content-Length "
        f"{playlists.main_headers.get('Content-Length') or 'absent'}, Expires "
        f"{playlists.main_headers.get('Expires')}, {len(playlists.main)} characters, "
        f"{playlists.main.count(chr(13))} carriage returns, ends "
        f"{playlists.main[-20:]!r}",
    )
    probe.observe(
        f"{label}: media header names",
        ", ".join(sorted(playlists.main_headers)),
    )


def _url_query(transcoding_url: str) -> dict[str, str]:
    query = urllib.parse.urlsplit(transcoding_url).query
    return {k: v[0] for k, v in urllib.parse.parse_qs(query, keep_blank_values=True).items()}


def _cadence_matrix(
    server: Server, source: VideoSource, probe: Probe, sessions: list[str]
) -> list[tuple[int | None, str | None, float | None]]:
    """The body segment duration a re-encode plans, at five requested segment lengths.

    Playlists only: the reference builds a media playlist from the source's runtime without
    starting anything, so this whole matrix costs five negotiations and five reads.
    """
    rows: list[tuple[int | None, str | None, float | None]] = []
    for requested in REQUESTED_LENGTHS:
        _status, data = negotiate(server, source.item_id, _encode_profile(source, requested))
        url = data["MediaSources"][0].get("TranscodingUrl")
        if not url:
            raise ProbeError("the cadence profile produced no TranscodingUrl")
        sessions.append(data["PlaySessionId"])
        parameters = _url_query(url)
        playlists = fetch_playlists(server, source.item_id, url)
        body = playlists.durations[0] if playlists.durations else None
        stated = parameters.get("SegmentLength")
        rows.append((requested, parameters.get("MaxFramerate"), body))
        probe.observe(
            f"  SegmentLength={requested if requested is not None else 'unstated'}",
            f"URL says SegmentLength={stated or 'absent'} MaxFramerate="
            f"{parameters.get('MaxFramerate') or 'absent'}, body segment {body}s, "
            f"{len(playlists.durations)} segments",
        )
    return rows


def _pick_container(server: Server, container: str) -> VideoSource | None:
    """The first video item whose single container is the one named, or None.

    The copy path's boundaries are the question this exists for, and the reference answers it
    per **file extension** - so one container cannot answer it.
    """
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes="Movie,Episode",
        Recursive="true",
        Fields="MediaSources",
        Limit=100,
    )
    for row in found.get("Items", []):
        for source in row.get("MediaSources", []):
            if (source.get("Container") or "").lower() != container:
                continue
            item = server.get(f"/Items/{row['Id']}", userId=server.user_id)
            sources = item.get("MediaSources") or []
            if not sources:
                continue
            try:
                return VideoSource(row["Id"], sources[0])
            except ProbeError:
                continue
    return None


def _refusals(server: Server, source: VideoSource, probe: Probe) -> list[bool]:
    """How the two playlist routes refuse. Plan section 6.8 leaves these owed to this task."""
    checks: list[bool] = []
    common = {
        "UserId": server.user_id or "",
        "DeviceId": _fresh_device(),
        "MediaSourceId": source.item_id,
        "VideoCodec": "h264",
        "AudioCodec": "aac",
        "SegmentContainer": "ts",
        "api_key": server.token or "",
    }
    query = urllib.parse.urlencode(common)

    unknown = uuid.uuid4().hex
    status, headers, body = server.get_streaming(
        f"/Videos/{unknown}/master.m3u8?{query}", max_bytes=512
    )
    probe.observe(
        "refusal: an item nothing holds, master.m3u8",
        f"{status}, {headers.get('Content-Type')}, {body[:120]!r}",
    )
    checks.append(status >= 400)

    status, headers, body = server.get_streaming(
        f"/Videos/{unknown}/main.m3u8?{query}", max_bytes=512
    )
    probe.observe(
        "refusal: the same on main.m3u8",
        f"{status}, {headers.get('Content-Type')}, {body[:120]!r}",
    )
    checks.append(status >= 400)

    tokenless = urllib.parse.urlencode({k: v for k, v in common.items() if k != "api_key"})
    status, headers, body = server.get_streaming(
        f"/Videos/{source.item_id}/master.m3u8?{tokenless}", max_bytes=512, send_token=False
    )
    probe.observe(
        "refusal: no credential at all",
        f"{status}, {headers.get('Content-Type')}, {len(body)} bytes, {body[:120]!r}",
    )
    checks.append(status == 401)

    status, headers, body = server.get_streaming(
        f"/Videos/{source.item_id}/main.m3u8", max_bytes=512
    )
    probe.observe(
        "refusal: main.m3u8 with no query at all",
        f"{status}, {headers.get('Content-Type')}, {body[:120]!r}",
    )

    unknown_source = urllib.parse.urlencode({**common, "MediaSourceId": uuid.uuid4().hex})
    status, headers, body = server.get_streaming(
        f"/Videos/{source.item_id}/master.m3u8?{unknown_source}", max_bytes=512
    )
    probe.observe(
        "refusal: a MediaSourceId naming no source",
        f"{status}, {headers.get('Content-Type')}, {body[:120]!r}",
    )
    return checks


def _universal_master(server: Server, probe: Probe) -> None:
    """What `/Audio/{itemId}/universal` with `transcodingProtocol=hls` actually hands back.

    T8 recorded the first 48 bytes of it and left the rest to this task, which is the task that
    has to serve one.
    """
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
    rows = found.get("Items", [])
    if not rows:
        probe.observe("/universal hls", "no audio track in the library to ask with")
        return
    track = rows[0]
    container = (track.get("MediaSources") or [{}])[0].get("Container") or "mp3"
    query = urllib.parse.urlencode(
        {
            "UserId": server.user_id or "",
            "DeviceId": _fresh_device(),
            "Container": container,
            "TranscodingContainer": "ts",
            "TranscodingProtocol": "hls",
            "AudioCodec": "aac",
            "MaxAudioSampleRate": 22050,
            "api_key": server.token or "",
        }
    )
    status, headers, body = server.get_streaming(
        f"/Audio/{track['Id']}/universal?{query}", max_bytes=2048
    )
    probe.observe(
        "/universal transcodingProtocol=hls",
        f"{status}, {headers.get('Content-Type')}, Content-Length "
        f"{headers.get('Content-Length') or 'absent'}, Expires {headers.get('Expires')}",
    )
    probe.observe("  its body", body.decode(errors="replace")[:EXCERPT])


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_hls.py",
        question="is the playlist complete up front, where does its segment cadence come from, "
        "and are segments the same bytes on a retry and served out of order?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.7 and 6",
        expectation=(
            "the media playlist arrives complete and ENDLIST-marked before any segment is "
            "produced (boundaries are predicted, not derived); every body segment shares one "
            "duration with only the last shorter; each segment URL carries runtimeTicks and "
            "actualSegmentLengthTicks; a re-requested segment is byte-identical within the "
            "session; an out-of-order segment is served; segments carry Content-Length "
            "and Accept-Ranges: bytes; the re-encode cadence is the requested segment length "
            "scaled by the frame rate; and a stream copy's boundaries are the source's own "
            "keyframes"
        ),
    )

    source = pick_video_source(server)
    probe.observe("measured source", f"{source.container}, video {source.video_codec}")
    video = next(
        (one for one in source.source.get("MediaStreams", []) if one.get("Type") == "Video"), {}
    )
    probe.observe(
        "  its frame rate",
        f"RealFrameRate {video.get('RealFrameRate')}, AverageFrameRate "
        f"{video.get('AverageFrameRate')}, ReferenceFrameRate {video.get('ReferenceFrameRate')}",
    )
    encoding = server.get("/System/Configuration/encoding")
    allowed = encoding.get("AllowOnDemandMetadataBasedKeyframeExtractionForExtensions")
    probe.observe("  keyframe extraction allowed for", f"{allowed}")

    checks: list[bool] = []
    sessions: list[str] = []
    try:
        play_session_id, playlists, shape_ok = _session(
            server, source, _encode_profile(source), "re-encode", probe
        )
        sessions.append(play_session_id)
        checks.append(shape_ok)
        _record(probe, "re-encode", playlists)
        segments = playlists.segments

        probe.observe("cadence matrix", "the same source, five requested segment lengths")
        rows = _cadence_matrix(server, source, probe, sessions)
        checks.append(all(body is not None for _requested, _fps, body in rows))

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

        play_session_id, playlists, shape_ok = _session(
            server, source, _copy_profile(source), "copy", probe
        )
        sessions.append(play_session_id)
        checks.append(shape_ok)
        _record(probe, "copy", playlists)

        # Does a copy bucket the source's own keyframes, or lay an equal grid over the runtime?
        # An off-grid requested length separates the two: buckets drift off it, a grid does not.
        _status, data = negotiate(server, source.item_id, _copy_profile(source, 5))
        sessions.append(data["PlaySessionId"])
        off_grid = fetch_playlists(
            server, source.item_id, data["MediaSources"][0]["TranscodingUrl"]
        )
        probe.observe(
            f"copy at SegmentLength=5, container {source.container}",
            f"first ten {off_grid.durations[:10]}, distinct body durations "
            f"{len(set(off_grid.durations[:-1]))}, "
            f"{off_grid.main.splitlines()[3]}",
        )

        other = _pick_container(server, "mkv")
        if other is None:
            probe.observe("copy in mkv", "the library holds no mkv item to ask with")
        else:
            _status, data = negotiate(server, other.item_id, _copy_profile(other, 5))
            sessions.append(data["PlaySessionId"])
            mkv = fetch_playlists(server, other.item_id, data["MediaSources"][0]["TranscodingUrl"])
            probe.observe(
                f"copy at SegmentLength=5, container {other.container}",
                f"first ten {mkv.durations[:10]}, distinct body durations "
                f"{len(set(mkv.durations[:-1]))}, {mkv.main.splitlines()[3]}",
            )

        probe.observe("refusals", "both playlist routes, each with its own device")
        checks.extend(_refusals(server, source, probe))
        _universal_master(server, probe)
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
