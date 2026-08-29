#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a progressive delivery response look like, and what does `mediaSourceId` decide?

specs/008 sections 3.4 and 3.5, and the two readings plan section 6.8 leaves owed to the task
that lands the non-static half of the four `stream` routes:

- **the shape**: a remux and a re-encode delivered over http rather than HLS - the status, the
  `Content-Type`, and whether a size or a range unit rides on either;
- **a malformed `Range` on a chunked response**: the sized case is measured (every unreadable
  shape is a `200` with the whole body, 008 T6) and this one is not - a response that has
  already said `Accept-Ranges: none` still has to answer a client that asks anyway;
- **`mediaSourceId`**: the parameter T6 left undeclared, its two refusals, and whether the
  answer differs between the static and the produced halves of the same route;
- **the start position**: whether `StartTimeTicks` on a progressive URL begins production at
  the position or produces from zero and discards, which is spec section 3.4's rule measured
  where there is no playlist to seek in.

Needs --allow-writes: every non-static request here makes the reference start a real ffmpeg in
its scratch space. Each one reads at most a few hundred bytes and closes - which is also the
disconnect signal - and every session this probe opens is stopped through
`DELETE /Videos/ActiveEncodings`, including on failure.

Usage:
    python3 tools/probe_progressive_delivery.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import time
import urllib.parse
import uuid
from typing import Any

from _playback import base_profile, negotiate, pick_video_source, stop_encoding
from _probe import Probe, ProbeError, Server, main

#: A well-formed identifier no media source carries. Not all zeros, which is `Guid.Empty` and
#: measures a guard rather than a miss (008 T5).
UNKNOWN_ID = "deadbeefdeadbeefdeadbeefdeadbeef"

#: A `mediaSourceId` that is not an identifier at all, which is the half T6 measured as a `500`.
UNPARSEABLE_ID = "banana"

#: Ten minutes in .NET ticks - far enough into any feature-length source that producing from
#: zero and discarding could not answer within the probe's timeout.
TEN_MINUTES = 10 * 60 * 10_000_000


def _pick_track(server: Server) -> tuple[str, str]:
    """The shortest audio track the library offers, with its container.

    Shortest because every non-static request against it starts an encoder, and the cheapest
    question is the one asked of the smallest file.
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
    for row in found.get("Items", []):
        for source in row.get("MediaSources", []):
            if source.get("Container"):
                return row["Id"], source["Container"]
    raise ProbeError("the library holds no audio track to produce from")


def _replacing(url: str, **params: str) -> str:
    """The same URL with these parameters *replaced* rather than appended.

    Appending is the trap this probe fell into twice. A negotiated `TranscodingUrl` already
    carries `MediaSourceId` and `PlaySessionId`, and a duplicated query name binds to the
    **first** value on the reference's model binder - so an appended `&mediaSourceId=banana`
    measured the negotiated id and answered a serene `200`.
    """
    lowered = {name.lower() for name in params}
    kept = [part for part in url.split("&") if part.split("=", 1)[0].lower() not in lowered]
    return "&".join(kept + [f"{name}={value}" for name, value in params.items()])


def _with_fresh_session(url: str, opened: list[str]) -> str:
    """The same URL under a `PlaySessionId` no job holds, recorded so it can be stopped.

    Replaying a negotiated `TranscodingUrl` verbatim finds the job the first request started and
    answers from it, which silently skips every parameter that is only read while building a new
    one. A fresh identifier is what makes a second request a second *negotiation* of the URL.
    """
    fresh = uuid.uuid4().hex
    opened.append(fresh)
    return _replacing(url, PlaySessionId=fresh)


def _headers(headers: dict[str, str]) -> str:
    """The four names this question turns on, present or absent, in one line."""
    wanted = ("Content-Type", "Content-Length", "Accept-Ranges", "Transfer-Encoding")
    return ", ".join(f"{name}={headers.get(name, '-')}" for name in wanted)


def _http_profile(container: str, video_codec: str, audio_codec: str) -> dict[str, Any]:
    """A transcoding target delivered progressively rather than as a playlist.

    `Protocol: http` is what puts `/videos/{id}/stream.{container}` in the `TranscodingUrl`
    instead of `master.m3u8`, which is the only way to reach the progressive routes through a
    negotiation the way a client reaches them.
    """
    return {
        "Container": container,
        "Type": "Video",
        "VideoCodec": video_codec,
        "AudioCodec": audio_codec,
        "Protocol": "http",
        "Context": "Streaming",
    }


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_progressive_delivery.py",
        question="what shape is a progressive delivery response, and what does mediaSourceId do?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="sections 3.4 and 3.5",
        expectation=(
            "a progressive remux and a progressive re-encode both answer 200 chunked with "
            "Accept-Ranges: none and no Content-Length, whatever the Range header says; a "
            "mediaSourceId naming the item's own source is served; one naming no source at all "
            "is the third error shape at 400; and one that is not an identifier is the same "
            "shape at 500"
        ),
    )

    source = pick_video_source(server, kind="Episode")
    probe.observe(
        "measured source",
        f"{source.container}, video {source.video_codec}, "
        f"audio {'/'.join(source.audio_codecs)}, {source.runtime_ticks} ticks",
    )
    track_id, track_container = _pick_track(server)
    probe.observe("measured track", f"{track_id} ({track_container})")

    sessions: list[str] = []
    checks: list[bool] = []

    def follow(url: str, extra: dict[str, str] | None = None, read: int = 200) -> Any:
        return server.get_streaming(url, max_bytes=read, extra_headers=extra)

    try:
        # -- the shape of a progressive remux ------------------------------------------------

        remux_profile = base_profile(
            [
                {
                    "Container": source.other_container(),
                    "Type": "Video",
                    "VideoCodec": source.video_codec,
                    "AudioCodec": ",".join(source.audio_codecs),
                }
            ],
            transcoding=[_http_profile("mp4", source.video_codec, ",".join(source.audio_codecs))],
        )
        status, data = negotiate(server, source.item_id, remux_profile)
        remux_url = (data.get("MediaSources") or [{}])[0].get("TranscodingUrl")
        if not remux_url:
            raise ProbeError(
                f"the container-rejecting profile produced no TranscodingUrl ({status})"
            )
        sessions.append(data["PlaySessionId"])
        probe.observe("remux TranscodingUrl", urllib.parse.urlparse(remux_url).path)

        status, headers, body = follow(remux_url)
        probe.observe("a progressive remux", f"{status}, {_headers(headers)}")
        checks.append(status == 200 and headers.get("Accept-Ranges") == "none")
        checks.append("Content-Length" not in headers)
        remux_head = body[:64]

        # -- and of a progressive re-encode --------------------------------------------------

        encode_profile = base_profile(
            [
                {
                    "Container": source.container,
                    "Type": "Video",
                    "VideoCodec": source.other_video_codec(),
                    "AudioCodec": ",".join(source.audio_codecs),
                }
            ],
            transcoding=[_http_profile("mp4", "h264", "aac")],
        )
        status, data = negotiate(server, source.item_id, encode_profile)
        encode_url = (data.get("MediaSources") or [{}])[0].get("TranscodingUrl")
        if not encode_url:
            raise ProbeError(f"the codec-rejecting profile produced no TranscodingUrl ({status})")
        sessions.append(data["PlaySessionId"])

        status, headers, _ = follow(encode_url)
        probe.observe("a progressive re-encode", f"{status}, {_headers(headers)}")
        checks.append(status == 200 and headers.get("Accept-Ranges") == "none")
        checks.append("Content-Length" not in headers)

        # -- and of a produced audio answer, which is the cheapest of the three ---------------

        audio_url = (
            f"/Audio/{track_id}/stream.mp3?api_key={server.token}"
            "&audioCodec=mp3&audioBitRate=128000"
        )
        status, headers, _ = follow(audio_url)
        probe.observe("a produced /Audio/{id}/stream.mp3", f"{status}, {_headers(headers)}")
        checks.append(status == 200 and headers.get("Accept-Ranges") == "none")

        # -- what a bare non-static request answers -------------------------------------------

        status, headers, _ = follow(f"/Videos/{source.item_id}/stream?api_key={server.token}")
        probe.observe("a bare non-static /Videos/{id}/stream", f"{status}, {_headers(headers)}")
        status, headers, _ = follow(f"/Audio/{track_id}/stream?api_key={server.token}")
        probe.observe("a bare non-static /Audio/{id}/stream", f"{status}, {_headers(headers)}")

        # -- a container the muxer cannot be named from, and one that cannot hold the streams ---

        for label, route in (
            (
                "stream.banana",
                f"/Videos/{source.item_id}/stream.banana?api_key={server.token}",
            ),
            (
                "stream.mp3 on a film",
                f"/Videos/{source.item_id}/stream.mp3?api_key={server.token}",
            ),
            (
                "?container=banana",
                f"/Videos/{source.item_id}/stream?api_key={server.token}&container=banana",
            ),
        ):
            status, headers, body = follow(route, read=140)
            probe.observe(
                f"produced {label}",
                f"{status}, {_headers(headers)}, first bytes {body[:12]!r}",
            )

        # -- Range against a response that already said it has none ---------------------------

        for label, header in (
            ("bytes=100-199", "bytes=100-199"),
            ("bytes=-100 (suffix)", "bytes=-100"),
            ("bytes=abc-def (unreadable)", "bytes=abc-def"),
            ("bytes=0-0 (one byte)", "bytes=0-0"),
        ):
            status, headers, body = follow(remux_url, {"Range": header})
            probe.observe(
                f"Range {label} on the remux",
                f"{status}, {_headers(headers)}, Content-Range="
                f"{headers.get('Content-Range', '-')}, same first bytes: {body[:64] == remux_head}",
            )
            checks.append(status == 200)

        # -- which part of the item, on the produced half -------------------------------------
        #
        # **Every produced request below carries a PlaySessionId nothing has issued yet**, and
        # that is the whole reason this battery answers anything: a URL replayed with the
        # session id it was negotiated under finds a live job and takes that job's media source,
        # so `mediaSourceId` is never read at all and every value answers 200. The first run of
        # this probe measured exactly that and it is an artefact of the replay, not a property
        # of the route `[source: Jellyfin.Api/Helpers/StreamingHelpers.cs:118-141 @ v10.11.11]`.

        own_source_id = (data.get("MediaSources") or [{}])[0].get("Id") or source.item_id
        for label, named in (
            ("the source's own id", own_source_id),
            ("a source nothing has", UNKNOWN_ID),
            ("not an identifier at all", UNPARSEABLE_ID),
        ):
            for half, route in (
                ("static", f"/Videos/{source.item_id}/stream?static=true&api_key={server.token}"),
                ("produced", _with_fresh_session(remux_url, sessions)),
            ):
                status, headers, body = follow(_replacing(route, MediaSourceId=named), read=140)
                probe.observe(
                    f"mediaSourceId {label} ({half})",
                    f"{status}, {headers.get('Content-Type')}, {body[:60]!r}"
                    if status >= 300
                    else f"{status}, {headers.get('Content-Type')}, served",
                )

        # -- the start position, where there is no playlist to seek in -------------------------
        #
        # A fresh session per row for the same reason: replaying the negotiated one serves the
        # output the earlier request already produced, and both rows would answer instantly
        # whatever the start position did.

        for label, ticks in (("from zero", 0), ("ten minutes in", TEN_MINUTES)):
            began = time.monotonic()
            status, headers, _ = follow(
                f"{_with_fresh_session(remux_url, sessions)}&StartTimeTicks={ticks}"
            )
            probe.observe(
                f"StartTimeTicks {label}",
                f"{status}, first bytes after {time.monotonic() - began:.2f}s, {_headers(headers)}",
            )

        status, headers, body = follow(
            _with_fresh_session(remux_url, sessions), {"Range": "bytes=100-199"}
        )
        probe.observe(
            "Range bytes=100-199 on a cold remux",
            f"{status}, {_headers(headers)}, Content-Range={headers.get('Content-Range', '-')}",
        )
        checks.append(status == 200 and headers.get("Accept-Ranges") == "none")
    finally:
        for play_session_id in sessions:
            probe.observe(
                "cleanup DELETE /Videos/ActiveEncodings", stop_encoding(server, play_session_id)
            )

    if all(checks):
        probe.conclude(
            "as documented: every progressive answer is a chunked 200 with Accept-Ranges: none "
            "and no length, and a Range header of any shape - readable or not - changes nothing "
            "about it. See the observations for what mediaSourceId decides",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
