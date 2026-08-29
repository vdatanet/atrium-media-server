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

and, since 008 T11, the **segment battery**: what
`GET /Videos/{itemId}/hls1/{playlistId}/{segmentId}.{container}` answers, since that is the
route T11 lands and plan section 6.8 left its refusal shapes owed to the task that lands it.
Its headers, its two identity rules (AC-23, AC-24), the fMP4 initialisation segment numbered
-1, and its five refusals - each row on a **fresh `DeviceId` and `PlaySessionId`**, because
the reference names its transcode output `md5(media path - user agent - device id - play
session id)` `[source: Jellyfin.Api/Helpers/StreamingHelpers.cs:374-383 @ v10.11.11]` and a
row that reused either would be served the previous row's bytes.

Needs --allow-writes: this probe deliberately makes the reference encode for about a minute.
It stops every session it started at the end - including on failure.

Usage:
    python3 tools/probe_transcode_session.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import uuid
from typing import Any

from _playback import (
    VideoSource,
    base_profile,
    dashed,
    fetch_main_playlist,
    fetch_playlists,
    negotiate,
    pick_video_source,
    stop_encoding,
)
from _probe import Probe, ProbeError, Server, main

#: The reference's throttle threshold when an operator turns throttling on, in seconds.
THROTTLE_GAP_SECONDS = 180

#: What the controllers answer out of their own refusal path: `text/plain`, these 25 bytes.
CONTROLLER_ERROR = b"Error processing request."

#: An item identifier nothing holds.
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"

#: How much of a segment is read before the connection is closed. A segment is under a
#: megabyte at the measured bitrate, so this reads whole ones and the digests below compare
#: bodies rather than prefixes.
SEGMENT_BYTES = 8 * 1024 * 1024


def completion(server: Server) -> float | None:
    for session in server.get("/Sessions"):
        if session.get("DeviceId") == "atrium-probe-0000" and session.get("TranscodingInfo"):
            return session["TranscodingInfo"].get("CompletionPercentage")
    return None


# --------------------------------------------------------------------------------------------
# The segment battery (008 T11)
# --------------------------------------------------------------------------------------------


def video_profile(source: VideoSource, segment_container: str = "ts") -> dict[str, Any]:
    """A profile whose only answer is a re-encode into HLS, with the segments named."""
    return base_profile(
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
                "Container": segment_container,
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


def freshened(uri: str, sessions: set[str], *, credential: bool = True, **overrides: str) -> str:
    """One segment URI with a device and a play session nothing else has used.

    Every row of the battery goes through here. The reference derives its transcode output path
    from `md5(media path - user agent - device id - play session id)` and from nothing else, so
    two rows sharing those are two rows reading one directory: a request that could not be
    produced at all is then served the previous row's finished bytes and reads as a pass. Four
    rows of `probe_universal_audio.py`'s first draft did exactly that.

    `credential=False` also drops the `ApiKey` the negotiated URL carries, which is what makes
    "does this route require a token" a question about the route rather than about the header.
    """
    head, _, query = uri.partition("?")
    new_session = uuid.uuid4().hex
    sessions.add(new_session)
    pairs = []
    for name, value in urllib.parse.parse_qsl(query, keep_blank_values=True):
        lowered = name.lower()
        if lowered == "deviceid":
            value = f"atrium-probe-{uuid.uuid4().hex[:12]}"
        elif lowered == "playsessionid":
            value = new_session
        elif lowered in ("apikey", "api_key") and not credential:
            continue
        elif lowered in overrides:
            value = overrides.pop(lowered)
        pairs.append((name, value))
    pairs += list(overrides.items())
    return f"{head}?&{urllib.parse.urlencode(pairs)}"


def segment_battery(
    server: Server, probe: Probe, source: VideoSource, sessions: set[str]
) -> list[bool]:
    """What the segment route answers: its headers, its two identity rules, its refusals.

    Returns one check per row. The rows are ordered so the working shape is measured first: a
    refusal that answered `200` would otherwise be indistinguishable from a battery whose
    negotiation never worked at all.
    """
    checks: list[bool] = []

    status, data = negotiate(server, source.item_id, video_profile(source))
    url = data["MediaSources"][0].get("TranscodingUrl")
    if not url:
        raise ProbeError(f"the codec-rejecting profile produced no TranscodingUrl ({status})")
    sessions.add(data["PlaySessionId"])
    lists = fetch_playlists(server, source.item_id, url)
    first = lists.segments[0]

    status, headers, body = server.get_streaming(freshened(first, sessions), SEGMENT_BYTES)
    probe.observe(
        "segment 0",
        f"{status}, {len(body)} bytes, Content-Type={headers.get('Content-Type')}, "
        f"Content-Length={headers.get('Content-Length')}, "
        f"Accept-Ranges={headers.get('Accept-Ranges')}, "
        f"Last-Modified={'present' if headers.get('Last-Modified') else 'absent'}, "
        f"ETag={'present' if headers.get('ETag') else 'absent'}",
    )
    checks.append(
        status == 200
        and headers.get("Content-Type") == "video/mp2t"
        and headers.get("Content-Length") == str(len(body))
        and headers.get("Accept-Ranges") == "bytes"
        and headers.get("Last-Modified") is not None
    )

    # AC-23, within one session: the same segment twice is the same bytes. Deliberately *not*
    # freshened - this is the one row whose whole subject is asking the same session twice.
    repeated = server.get_streaming(first, SEGMENT_BYTES)[2]
    again = server.get_streaming(first, SEGMENT_BYTES)[2]
    probe.observe(
        "the same segment twice, one session",
        f"{len(repeated)} and {len(again)} bytes, "
        f"{'identical' if repeated == again else 'DIFFERENT'}",
    )
    checks.append(bool(repeated) and repeated == again)

    status, headers, ranged = server.get_streaming(
        first, SEGMENT_BYTES, extra_headers={"Range": "bytes=100-199"}
    )
    probe.observe(
        "Range: bytes=100-199 on a segment",
        f"{status}, {len(ranged)} bytes, Content-Range={headers.get('Content-Range')}",
    )
    checks.append(status == 206 and len(ranged) == 100 and headers.get("Content-Range") is not None)

    # AC-24: a player seeks rather than walking the playlist.
    ahead = lists.segments[min(len(lists.segments) - 1, 40)]
    started = time.monotonic()
    status, headers, body = server.get_streaming(freshened(ahead, sessions), SEGMENT_BYTES)
    probe.observe(
        "a segment 40 ahead, on a session that produced nothing",
        f"{status}, {len(body)} bytes in {time.monotonic() - started:.1f}s",
    )
    checks.append(status == 200 and len(body) > 0)

    # **What decides the bytes is the URI's `runtimeTicks`, not the index in the path.** The
    # index is only ffmpeg's `-start_number`, so the same path with two positions is two
    # different segments - which is the rule a restart has to be built on.
    middle = lists.segments[len(lists.segments) // 2]
    position = urllib.parse.parse_qs(middle.partition("?")[2]).get("runtimeTicks", ["0"])[0]
    at_zero = server.get_streaming(freshened(first, sessions), SEGMENT_BYTES)[2]
    at_middle = server.get_streaming(
        freshened(first, sessions, runtimeticks=position), SEGMENT_BYTES
    )[2]
    probe.observe(
        "segment 0's path at runtimeTicks=0 and at the middle",
        f"{hashlib.sha256(at_zero).hexdigest()[:12]} and "
        f"{hashlib.sha256(at_middle).hexdigest()[:12]} - "
        f"{'different content' if at_zero != at_middle else 'THE SAME'}",
    )
    checks.append(bool(at_zero) and bool(at_middle) and at_zero != at_middle)

    # The fMP4 shape: version 7, an `#EXT-X-MAP` naming segment -1, and that segment served.
    status, data = negotiate(server, source.item_id, video_profile(source, "mp4"))
    fragmented = (
        data["MediaSources"][0]
        .get("TranscodingUrl", "")
        .replace("SegmentContainer=ts", "SegmentContainer=mp4")
    )
    sessions.add(data["PlaySessionId"])
    fmp4 = fetch_playlists(server, source.item_id, fragmented)
    initialisation = [line for line in fmp4.main.splitlines() if line.startswith("#EXT-X-MAP")]
    uri = initialisation[0].split('URI="', 1)[1].rstrip('"') if initialisation else ""
    status, headers, body = (
        server.get_streaming(
            freshened(f"/videos/{dashed(source.item_id)}/{uri}", sessions), SEGMENT_BYTES
        )
        if uri
        else (0, {}, b"")
    )
    probe.observe(
        "the fMP4 initialisation segment",
        f"version {'7' if '#EXT-X-VERSION:7' in fmp4.main else 'not 7'}, "
        f"map URI {uri.partition('?')[0] or 'absent'} -> {status}, {len(body)} bytes, "
        f"{headers.get('Content-Type')}, starts {body[4:12]!r}",
    )
    checks.append(
        "#EXT-X-VERSION:7" in fmp4.main
        and uri.startswith("hls1/main/-1.mp4")
        and status == 200
        and headers.get("Content-Type") == "video/mp4"
        and body[4:8] == b"ftyp"
    )

    # The path's `{container}` is not what the segment is muxed into: `segmentContainer` is,
    # and the extension only has to be *a* container spelling for the route to match.
    status, headers, mislabelled = server.get_streaming(
        freshened(first, sessions).replace("/hls1/main/0.ts?", "/hls1/main/0.mp4?"), SEGMENT_BYTES
    )
    probe.observe(
        "the path says .mp4 where SegmentContainer says ts",
        f"{status}, {len(mislabelled)} bytes, {headers.get('Content-Type')}, "
        f"starts {mislabelled[:1]!r}",
    )
    checks.append(
        status == 200 and headers.get("Content-Type") == "video/mp2t" and mislabelled[:1] == b"G"
    )

    for label, uri, expected, kwargs in _refusals(first, sessions):
        wanted_status, wanted_type, wanted_body = expected
        status, headers, body = server.get_streaming(uri, SEGMENT_BYTES, **kwargs)
        probe.observe(
            label,
            f"{status}, Content-Type={headers.get('Content-Type')}, body {body[:40]!r}",
        )
        checks.append(
            status == wanted_status
            and headers.get("Content-Type") == wanted_type
            # `None` means the body is not part of the claim: the framework's problem details
            # name the missing parameters, and that list is the framework's rather than a
            # measured constant.
            and (wanted_body is None or body == wanted_body)
        )

    # Not a refusal, and worth a row for that reason: the reference marks `playlistId` unused
    # and means it, so a playlist nobody named still serves the segment.
    status, _headers, body = server.get_streaming(
        freshened(first, sessions).replace("/hls1/main/0.", "/hls1/banana/0."), SEGMENT_BYTES
    )
    probe.observe("a playlistId nothing named", f"{status}, {len(body)} bytes")
    checks.append(status == 200 and len(body) > 0)

    return checks


def _refusals(first: str, sessions: set[str]) -> list[tuple]:
    """The five refusals of the segment route, as (label, uri, expected triple, kwargs).

    Two shapes, and which one a request gets turns on **where** it is refused: the framework
    binds `runtimeTicks` and `actualSegmentLengthTicks` as required, so a request missing them
    never reaches a controller and answers problem details; everything the controller itself
    throws is the third shape `[source:
    Jellyfin.Api/Controllers/DynamicHlsController.cs:1106-1120,1448-1453 @ v10.11.11]`.
    """
    plain = "text/plain"
    query = first.partition("?")[2]
    unknown_item = f"/videos/{dashed(UNKNOWN_ITEM)}/hls1/main/0.ts?{query}"
    return [
        (
            "no credential at all",
            freshened(first, sessions, credential=False),
            (401, None, b""),
            {"send_token": False},
        ),
        (
            "an item nothing holds",
            freshened(unknown_item, sessions),
            (404, plain, CONTROLLER_ERROR),
            {},
        ),
        (
            "a mediaSourceId naming no source",
            freshened(first, sessions, mediasourceid=UNKNOWN_ITEM),
            (400, plain, CONTROLLER_ERROR),
            {},
        ),
        (
            "a segment carrying startTimeTicks",
            freshened(first, sessions, starttimeticks="600000000"),
            (400, plain, CONTROLLER_ERROR),
            {},
        ),
        (
            "no query string at all",
            first.partition("?")[0],
            (400, "application/json; charset=utf-8", None),
            {},
        ),
    ]


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_transcode_session.py",
        question="does production follow the throttle configuration, restart at a seek, stop on "
        "DELETE /Videos/ActiveEncodings, and what does one segment answer?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.4, 3.7 and 3.8",
        expectation=(
            "with no client fetching, production runs unbounded when EnableThrottling is off "
            "(the shipped default) and pauses ThrottleDelaySeconds ahead of the last download "
            "when the operator turned it on - whichever the server's own configuration says; "
            "a request near the end restarts production at that position; DELETE without "
            "playSessionId is a validation 400 naming the field, and with both parameters a "
            "204 that removes the session's TranscodingInfo; and a segment is a finished file "
            "served with a Content-Length, a Last-Modified and an honoured Range, identical "
            "when re-requested inside its session, served out of order, and refused with the "
            "third error shape except where the framework's own binding refuses first"
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

    status, data = negotiate(server, source.item_id, video_profile(source))
    url = data["MediaSources"][0].get("TranscodingUrl")
    if not url:
        raise ProbeError("the codec-rejecting profile produced no TranscodingUrl")
    play_session_id = data["PlaySessionId"]
    # Every session this run starts, so the `finally` stops all of them and not only the one the
    # throttle observation is made on. The battery below starts a dozen.
    started_sessions = {play_session_id}
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

        # 008 T11's battery, last because it starts a dozen sessions of its own and the
        # observation above is about a server with one.
        checks += segment_battery(server, probe, source, started_sessions)
    finally:
        for one in started_sessions:
            stop_encoding(server, one)

    if all(checks):
        probe.conclude(
            "as documented: production follows the server's throttle configuration, restarts "
            "at the requested position, the stop route validates its parameters and actually "
            "stops the work, and a segment is a sized, rangeable file whose bytes are decided "
            "by the URI's runtimeTicks rather than by the index in its path",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
