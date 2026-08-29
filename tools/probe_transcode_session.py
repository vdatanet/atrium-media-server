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
  with `deviceId` and `playSessionId` it answers `204` and the session stops reporting a
  completion percentage.

and, since 008 T12, the **kill-timer battery**: how long a session nobody pings survives, what
the stop route actually keys on, and what the session carries afterwards - the three readings
plan section 6.8 left owed to the task that builds the sweep.

and, since 008 T13, the **segment-deletion battery**: what `SegmentKeepSeconds` is a window
of. The specification and the task list both read it as a file age; the reference deletes the
segments whose *index* falls below `(downloadPositionSeconds - SegmentKeepSeconds) /
segmentSeconds` `[source:
MediaBrowser.Controller/MediaEncoding/TranscodingSegmentCleaner.cs:100-113 @ v10.11.11]`, so
nothing goes at all until the client has fetched past the window and then what goes is decided
by position rather than by when the file was written. The battery produces two segments either
side of that boundary, leaves the session alone for two of the cleaner's ticks, and asks for
both again.

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
from _probe import DEVICE_ID, Probe, ProbeError, Server, main

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

#: The reference's kill timer, read at the tag rather than guessed: a job is killed this long
#: after the request that last touched it, and the only thing the interval depends on is whether
#: the job is progressive - 10 000 ms there, 60 000 ms for everything else `[source:
#: MediaBrowser.MediaEncoding/Transcoding/TranscodeManager.cs:153-160 @ v10.11.11]`. Every job
#: behind a segment route is one of the latter, which is why the battery below waits a minute.
HLS_PING_TIMEOUT_SECONDS = 60
PROGRESSIVE_PING_TIMEOUT_SECONDS = 10

#: How long the kill-timer battery is prepared to watch, and how often it looks. The upper bound
#: is two timer periods and a little: the reference restarts its timer once if a ping arrived
#: while it was waiting, so a second period is a shape this run should still call a pass.
KILL_WATCH_SECONDS = 190
KILL_POLL_SECONDS = 3

#: How long the segment-deletion battery leaves a session alone. The reference's cleaner runs on
#: a twenty-second timer and delays its own deletion by 1.5 s `[source:
#: MediaBrowser.Controller/MediaEncoding/TranscodingSegmentCleaner.cs:51,111 @ v10.11.11]`, so
#: this is two of its ticks - and under the sixty-second kill timer, which is what keeps the
#: session alive to be asked afterwards.
DELETION_WATCH_SECONDS = 45


def transcoding_info(server: Server) -> dict[str, Any] | None:
    """The probe's own session's `TranscodingInfo`, or `None` when it carries none at all.

    **`None` here means the property is absent**, not that the numbers inside it are: every
    response passes through the reference's global null suppression (behaviours section 1.7), so
    a `TranscodingInfo` the session manager cleared is a missing key while a `TranscodingInfo`
    whose completion percentage went null is a present object with one fewer key. Collapsing the
    two - which is what reading `CompletionPercentage` straight off the session does - is how a
    stop that leaves the object behind reads as a stop that removed it.
    """
    for session in server.get("/Sessions"):
        if session.get("DeviceId") == DEVICE_ID:
            found = session.get("TranscodingInfo")
            if found:
                return dict(found)
    return None


def completion(server: Server) -> float | None:
    info = transcoding_info(server)
    return None if info is None else info.get("CompletionPercentage")


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


# --------------------------------------------------------------------------------------------
# The segment-deletion battery (008 T13)
# --------------------------------------------------------------------------------------------


def with_session(uri: str, device: str, play_session_id: str) -> str:
    """One segment URI addressed to a chosen device and play session.

    Unlike `freshened`, every row of this battery must land in the **same** transcode directory:
    what is being measured is which of the files already in it survive, so the device and the
    play session are fixed for the whole row rather than made new for each request. The device is
    the probe's own, because the completion percentage this battery reads is reported against the
    device's session and a device that never authenticated has no session to report on.
    """
    head, _, query = uri.partition("?")
    pairs = []
    for name, value in urllib.parse.parse_qsl(query, keep_blank_values=True):
        lowered = name.lower()
        if lowered == "deviceid":
            value = device
        elif lowered == "playsessionid":
            value = play_session_id
        pairs.append((name, value))
    return f"{head}?&{urllib.parse.urlencode(pairs)}"


def timed_fetch(server: Server, uri: str) -> tuple[int, float, int]:
    """One segment, and how long it took - which is how a deleted file makes itself visible.

    A segment already on disk is served without starting anything; a segment that is *not* there
    and lies behind the producing index restarts production. So the same request answers in
    milliseconds or in seconds depending on whether the file still exists, and the completion
    percentage falls back to the restart position in the second case.
    """
    started = time.monotonic()
    status, _headers, body = server.get_streaming(uri, SEGMENT_BYTES)
    return status, time.monotonic() - started, len(body)


def deletion_battery(
    server: Server, probe: Probe, source: VideoSource, sessions: set[str], keep: int | None
) -> list[bool]:
    """Is `SegmentKeepSeconds` a file age or a distance behind the client?

    Both documents said age - "aged produced segments", "produced segments older than the
    configured window" - and the reference deletes by **index**, computed from the furthest
    position the client has fetched: `[0 .. (downloadSeconds - keepSeconds) / segmentSeconds]`
    `[source: MediaBrowser.Controller/MediaEncoding/TranscodingSegmentCleaner.cs:100-113 @
    v10.11.11]`. The two rules only disagree observably in one place, and this is it: two
    segments produced seconds apart, on either side of that boundary, watched over one window in
    which nothing is requested at all.

    Needs a server with the feature enabled, and says so rather than asserting the other half
    when it is off - the same rule the throttle observation follows.
    """
    checks: list[bool] = []
    if keep is None:
        probe.observe(
            "segment deletion",
            "not measured: EnableSegmentDeletion is off on this server, or its configuration "
            "is not readable by this account",
        )
        return checks

    duration_seconds = source.runtime_ticks / 10_000_000
    if duration_seconds < keep + 300:
        probe.observe(
            "segment deletion",
            f"not measured: the picked source is {duration_seconds:.0f}s and the keep window is "
            f"{keep}s, so no client position can get a whole window behind itself",
        )
        return checks

    _status, data = negotiate(server, source.item_id, video_profile(source))
    url = data["MediaSources"][0].get("TranscodingUrl")
    if not url:
        raise ProbeError("the codec-rejecting profile produced no TranscodingUrl")
    sessions.add(data["PlaySessionId"])
    lists = fetch_playlists(server, source.item_id, url)
    cadence = lists.durations[0]

    # A client that has fetched a segment ending well past the window, and the two segments its
    # position puts on either side of the boundary.
    far_index = int((keep + 90) / cadence)
    ending = (far_index + 1) * cadence
    segment_seconds = round(cadence)
    boundary = int((ending - keep) // segment_seconds)
    doomed, survivor = boundary - 1, boundary + 3
    play_session_id = uuid.uuid4().hex
    sessions.add(play_session_id)

    def fetch(index: int) -> tuple[int, float, int]:
        return timed_fetch(server, with_session(lists.segments[index], DEVICE_ID, play_session_id))

    for index in (doomed, survivor, far_index):
        status, _elapsed, _size = fetch(index)
        if status != 200:
            raise ProbeError(f"the deletion battery's segment {index} answered {status}")
    probe.observe(
        "produced, then the client stops",
        f"segments {doomed} and {survivor} are on disk, and the furthest fetched segment "
        f"{far_index} ends {ending:.0f}s in against a {keep}s window - so the reference's own "
        f"arithmetic puts the boundary at index {boundary}",
    )

    before = [fetch(survivor), fetch(doomed)]
    settled = completion(server)
    probe.observe(
        "before the cleaner has ticked",
        f"segment {survivor} in {before[0][1]:.2f}s, segment {doomed} in {before[1][1]:.2f}s; "
        f"completion {'?' if settled is None else f'{settled:.1f}%'}",
    )
    checks.append(all(status == 200 and elapsed < 1 for status, elapsed, _size in before))

    time.sleep(DELETION_WATCH_SECONDS)
    kept_status, kept_elapsed, _size = fetch(survivor)
    after_survivor = completion(server)
    gone_status, gone_elapsed, _size = fetch(doomed)
    time.sleep(2)
    after_doomed = completion(server)
    probe.observe(
        f"after {DELETION_WATCH_SECONDS}s with nothing requested",
        f"segment {survivor} in {kept_elapsed:.2f}s (completion "
        f"{'?' if after_survivor is None else f'{after_survivor:.1f}%'}), segment {doomed} in "
        f"{gone_elapsed:.2f}s (completion "
        f"{'?' if after_doomed is None else f'{after_doomed:.1f}%'})",
    )
    checks.append(kept_status == 200 and kept_elapsed < 1)
    checks.append(gone_status == 200 and gone_elapsed > kept_elapsed * 3)
    # The second signal, and the decisive one: serving a file that is there restarts nothing,
    # so the completion percentage only falls when the file had to be produced again.
    checks.append(
        after_survivor is not None
        and after_doomed is not None
        and after_doomed < after_survivor / 2
    )
    stop_encoding(server, play_session_id)
    return checks


# --------------------------------------------------------------------------------------------
# The kill-timer battery (008 T12)
# --------------------------------------------------------------------------------------------


def begin_session(server: Server, source: VideoSource, sessions: set[str]) -> tuple[str, str]:
    """Negotiate one HLS session and fetch its first segment, so a job is really running.

    Returns the play session id and the first segment's URI. Each call negotiates afresh, which
    is what makes each row of this battery a different transcode directory: the reference names
    the directory from the play session id among other things, and two rows sharing one would be
    two rows watching a single job.
    """
    _status, data = negotiate(server, source.item_id, video_profile(source))
    url = data["MediaSources"][0].get("TranscodingUrl")
    if not url:
        raise ProbeError("the codec-rejecting profile produced no TranscodingUrl")
    play_session_id = data["PlaySessionId"]
    sessions.add(play_session_id)
    lists = fetch_playlists(server, source.item_id, url)
    status, _headers, _body = server.get_streaming(lists.segments[0], SEGMENT_BYTES)
    if status != 200:
        raise ProbeError(f"the kill-timer battery's first segment answered {status}")
    return play_session_id, lists.segments[0]


def await_progress(server: Server, seconds: int = 30) -> float | None:
    """Wait until the running job reports a completion percentage, which is when it is alive.

    A job reports one `TranscodingInfo` before ffmpeg has said anything, with every number in it
    null, so "the percentage is a number" is the first moment the session can be told apart from
    a session whose job has already stopped.
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        percent = completion(server)
        if percent is not None:
            return percent
        time.sleep(KILL_POLL_SECONDS)
    return None


def await_stop(server: Server, seconds: int) -> tuple[float | None, dict[str, Any] | None]:
    """Watch until the job stops reporting, and hand back when that was and what was left.

    The observable is the completion percentage going away rather than the whole
    `TranscodingInfo` doing so, which is the thing this battery exists to separate.
    """
    started = time.monotonic()
    deadline = started + seconds
    while time.monotonic() < deadline:
        info = transcoding_info(server)
        if info is None or info.get("CompletionPercentage") is None:
            return time.monotonic() - started, info
        time.sleep(KILL_POLL_SECONDS)
    return None, transcoding_info(server)


def kill_battery(
    server: Server, probe: Probe, source: VideoSource, sessions: set[str]
) -> list[bool]:
    """When does a session nobody asks about die, what does the stop route key on, and what is
    left on the session afterwards?

    Three questions plan section 6.8 left owed to the task that builds the sweep, and one the
    specification had answered without measuring.

    **Every row starts one job and ends it before the next begins**, which is not tidiness.
    `TranscodingInfo` hangs off the *device's* session and the session manager writes it by
    device id `[source: Emby.Server.Implementations/Session/SessionManager.cs:1866-1875 @
    v10.11.11]`, so two jobs of this probe are two writers of one property: a row that killed
    its own job while another was still reporting would read the survivor's percentage and
    call the kill a failure. The battery's first draft did exactly that.
    """
    checks: list[bool] = []

    # The three rows that need no encoder at all, first: what the stop route refuses, and how.
    status, headers, body = server.delete_raw(
        "/Videos/ActiveEncodings",
        deviceId=DEVICE_ID,
        playSessionId=uuid.uuid4().hex,
        send_token=False,
    )
    probe.observe(
        "DELETE /Videos/ActiveEncodings with no credential",
        f"{status}, Content-Type={headers.get('Content-Type')}, body {body[:40]!r}",
    )
    checks.append(status == 401 and not body)

    status, _headers, body = server.delete_raw(
        "/Videos/ActiveEncodings", playSessionId=uuid.uuid4().hex
    )
    errors = json.loads(body).get("errors", {}) if body else {}
    probe.observe("DELETE without deviceId", f"{status}, errors keys {sorted(errors) or 'none'}")
    checks.append(status == 400 and "deviceId" in errors)

    status, _headers, body = server.delete_raw("/Videos/ActiveEncodings")
    errors = json.loads(body).get("errors", {}) if body else {}
    probe.observe("DELETE with neither parameter", f"{status}, errors keys {sorted(errors)}")
    checks.append(status == 400 and {"deviceId", "playSessionId"} <= set(errors))

    # Row 1: the kill timer itself. Nothing is fetched after the first segment, and nothing
    # reports playback, so the only thing that can end this job is the timer.
    _play_session_id, _first = begin_session(server, source, sessions)
    if await_progress(server) is None:
        raise ProbeError("the kill-timer session never reported a completion percentage")
    elapsed, left = await_stop(server, KILL_WATCH_SECONDS)
    probe.observe(
        "an HLS session nobody pings",
        f"stopped reporting after {'never' if elapsed is None else f'{elapsed:.0f}s'} "
        f"(the source says {HLS_PING_TIMEOUT_SECONDS}s for HLS, "
        f"{PROGRESSIVE_PING_TIMEOUT_SECONDS}s for progressive)",
    )
    checks.append(elapsed is not None and elapsed <= 2 * HLS_PING_TIMEOUT_SECONDS + 30)
    probe.observe(
        "the session's TranscodingInfo once the job is gone",
        "absent" if left is None else f"present, keys {sorted(left)}",
    )

    # Row 2: the shape itself, on a live job, because the sweep's caller has to emit it.
    play_session_id, _first = begin_session(server, source, sessions)
    if await_progress(server) is None:
        raise ProbeError("the shape row's session never reported a completion percentage")
    live = transcoding_info(server) or {}
    probe.observe("TranscodingInfo while transcoding", json.dumps(live, sort_keys=False))
    checks.append(bool(live) and live.get("VideoCodec") is not None)
    stop_encoding(server, play_session_id)
    time.sleep(3)

    # Row 3: what the stop route keys on. Both parameters are mandatory at the binder, and the
    # reference then matches on the play session alone - so a device id nothing owns must still
    # stop the named session, or a client spelling its device differently leaks an encoder.
    play_session_id, _first = begin_session(server, source, sessions)
    if await_progress(server) is None:
        raise ProbeError("the wrong-device row's session never reported a percentage")
    status, _headers, _body = server.delete_raw(
        "/Videos/ActiveEncodings",
        deviceId=f"atrium-probe-{uuid.uuid4().hex[:12]}",
        playSessionId=play_session_id,
    )
    time.sleep(3)
    after = transcoding_info(server)
    stopped = after is None or after.get("CompletionPercentage") is None
    probe.observe(
        "DELETE with a deviceId nothing owns and the right playSessionId",
        f"{status}; the job {'stopped' if stopped else 'is still running'}; "
        f"TranscodingInfo {'absent' if after is None else 'present'}",
    )
    checks.append(status == 204 and stopped)
    stop_encoding(server, play_session_id)
    time.sleep(3)

    # Row 4: an unknown play session is a no-op, and is not allowed to take a live one with it.
    play_session_id, _first = begin_session(server, source, sessions)
    if await_progress(server) is None:
        raise ProbeError("the unknown-session row's session never reported a percentage")
    status, _headers, _body = server.delete_raw(
        "/Videos/ActiveEncodings",
        deviceId=DEVICE_ID,
        playSessionId=uuid.uuid4().hex,
    )
    time.sleep(3)
    survivor = completion(server)
    probe.observe(
        "DELETE naming a playSessionId nothing issued",
        f"{status}; the live session is "
        f"{'still transcoding' if survivor is not None else 'gone too'}",
    )
    checks.append(status == 204 and survivor is not None)

    stop_encoding(server, play_session_id)
    return checks


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_transcode_session.py",
        question="does production follow the throttle configuration, restart at a seek, stop on "
        "DELETE /Videos/ActiveEncodings, die on its own kill timer, and what does one segment "
        "answer?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.4, 3.7 and 3.8",
        expectation=(
            "with no client fetching, production runs unbounded when EnableThrottling is off "
            "(the shipped default) and pauses ThrottleDelaySeconds ahead of the last download "
            "when the operator turned it on - whichever the server's own configuration says; "
            "a request near the end restarts production at that position; DELETE without "
            "playSessionId is a validation 400 naming the field, and with both parameters a "
            "204 after which the session reports no completion percentage; a session nobody "
            "pings dies on its own about sixty seconds later; the stop route matches on the "
            "play session alone, so a deviceId nothing owns still stops the named session and "
            "a playSessionId nothing issued stops nothing; and a segment is a finished file "
            "served with a Content-Length, a Last-Modified and an honoured Range, identical "
            "when re-requested inside its session, served out of order, and refused with the "
            "third error shape except where the framework's own binding refuses first; and "
            "with segment deletion enabled, the produced segment a whole keep-window behind "
            "the client's furthest fetch is gone while the one just inside it is not"
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
        keep: int | None = None
        try:
            config = server.get("/System/Configuration/encoding")
            throttling = bool(config.get("EnableThrottling"))
            gap = max(int(config.get("ThrottleDelaySeconds") or 180), 60)
            deleting = bool(config.get("EnableSegmentDeletion"))
            if deleting:
                keep = max(int(config.get("SegmentKeepSeconds") or 720), 20)
            probe.observe(
                "server encoding configuration",
                f"EnableThrottling={throttling}, ThrottleDelaySeconds={gap}, "
                f"EnableSegmentDeletion={deleting}, SegmentKeepSeconds={keep}",
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

        # 008 T12's battery, before the segment one: every row of it watches the probe's own
        # session row, and a dozen jobs encoding beside it would be a dozen chances for one of
        # them to report over the row this is reading.
        checks += kill_battery(server, probe, source, started_sessions)

        # 008 T13's, and it goes here for the same reason the one above does: it watches one
        # session's completion percentage, so it must be the only job running while it does.
        checks += deletion_battery(server, probe, source, started_sessions, keep)

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
