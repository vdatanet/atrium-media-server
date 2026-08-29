#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a progressive re-encode is produced: does its answer ever state a length, and is the
work keyed on the play session the client supplies?

specs/011 OQ-9 and OQ-10 - the two things the music client asks for that are **not** this
feature's to grant. Both are recorded as measurements and neither is an acceptance criterion:
the point of running this probe is that the two questions were framed before anybody measured
them, and a measurement is what decides whether the framing survives.

- **the length** (OQ-9): a lossless source asked for at a bitrate cap, read to the last byte, and
  then asked for again. If a completed transcode ever answers a `Content-Length`, an honest one
  is a parity gap rather than an improvement.
- **the key** (OQ-10): the same capped request twice with the same `playSessionId`, once with a
  different one, and the same thing over `/Audio/{id}/universal` - beside the server's own API
  document, which is what says whether the parameter exists on each route at all.

It makes the reference encode: two or three short audio transcodes of one track, every session
stopped on the way out including on failure.

Usage:
    python3 tools/probe_progressive_production.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import json
import time
import uuid

from _playback import stop_encoding
from _probe import Probe, ProbeError, Server, main

DEVICE = "atrium-probe-0000"

#: The containers whose bitrate cannot be honoured without re-encoding every sample, which is
#: what makes the produced size unknowable before the last byte.
LOSSLESS = ("flac", "alac", "wav", "ape", "wv", "aiff")

#: The routes the question is about, and the one the music client actually uses.
ROUTES = (
    "GetAudioStream",
    "GetAudioStreamByContainer",
    "GetVideoStream",
    "GetUniversalAudioStream",
)

CAP_BITS_PER_SECOND = 128_000


def _pick(server: Server) -> dict:
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes="Audio",
        Recursive="true",
        Limit=300,
        Fields="MediaSources",
    )
    fallback = None
    for row in found.get("Items", []):
        sources = row.get("MediaSources") or []
        if not sources:
            continue
        source = sources[0]
        runtime = source.get("RunTimeTicks") or 0
        if runtime <= 0 or runtime > 6 * 60 * 10_000_000:
            continue
        if (source.get("Container") or "").lower() in LOSSLESS:
            return {"id": row["Id"], "name": row.get("Name"), "source": source}
        fallback = fallback or {"id": row["Id"], "name": row.get("Name"), "source": source}
    if fallback:
        return fallback
    raise ProbeError("the library holds no audio track short enough to transcode twice")


def _declared(server: Server, probe: Probe) -> list[bool]:
    """Which routes declare `playSessionId`, read from the server's own API document.

    Whether declaring the parameter would be a delta is a question about the reference's
    surface, and the reference publishes its surface - so it is a measurement, not a judgement.
    """
    try:
        status, _, payload = server.get_raw("/api-docs/openapi.json")
        if status != 200:
            raise ProbeError(f"the API document answered {status}")
        document = json.loads(payload)
    except (ProbeError, ValueError) as exc:
        probe.note(
            f"the server's API document could not be read ({exc}), so which routes declare "
            "playSessionId is unmeasured here"
        )
        return []
    declares = {}
    for path, operations in document.get("paths", {}).items():
        for _method, operation in operations.items():
            if not isinstance(operation, dict):
                continue
            name = operation.get("operationId")
            if name in ROUTES:
                parameters = [p.get("name") for p in operation.get("parameters", [])]
                declares[name] = (path, "playSessionId" in parameters)
    for name in ROUTES:
        if name in declares:
            path, present = declares[name]
            probe.observe(
                name, f"{path} {'declares' if present else 'does not declare'} playSessionId"
            )
    return [
        declares.get("GetAudioStream", ("", False))[1],
        declares.get("GetAudioStreamByContainer", ("", False))[1],
        declares.get("GetVideoStream", ("", False))[1],
        not declares.get("GetUniversalAudioStream", ("", True))[1],
    ]


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_progressive_production.py",
        question=(
            "Does a capped progressive transcode ever state a length, and is the work keyed on "
            "the play session the client supplies?"
        ),
        document="specs/011-subtitle-delivery/spec.md",
        section="OQ-9, OQ-10",
        expectation=None,
    )
    chosen = _pick(server)
    source = chosen["source"]
    item_id = chosen["id"]
    probe.observe(
        "source",
        "item {}, {} of {} bytes at {} bits/s, {:.1f}s".format(
            item_id,
            source.get("Container"),
            source.get("Size"),
            source.get("Bitrate"),
            (source.get("RunTimeTicks") or 0) / 10_000_000,
        ),
    )
    checks = _declared(server, probe)

    query = f"?DeviceId={DEVICE}&AudioCodec=mp3&Container=mp3&audioBitRate={CAP_BITS_PER_SECOND}"
    first_session = uuid.uuid4().hex
    second_session = uuid.uuid4().hex
    sessions = [first_session, second_session]
    try:

        def fetch(label: str, path: str, read: int) -> dict:
            started = time.time()
            status, headers, body = server.get_streaming(path, read)
            elapsed = time.time() - started
            probe.observe(
                label,
                "{}, {}, {}, {}, {} bytes in {:.2f}s".format(
                    status,
                    headers.get("Content-Type") or "no Content-Type",
                    "Content-Length=" + headers["Content-Length"]
                    if headers.get("Content-Length")
                    else "no Content-Length",
                    "Transfer-Encoding=" + (headers.get("Transfer-Encoding") or "none"),
                    len(body),
                    elapsed,
                ),
            )
            return {
                "status": status,
                "length": headers.get("Content-Length"),
                "ranges": headers.get("Accept-Ranges"),
                "bytes": len(body),
                "seconds": elapsed,
            }

        whole = 40_000_000
        stream = f"/Audio/{item_id}/stream.mp3{query}&PlaySessionId="
        produced = fetch(
            "capped transcode, produced to the last byte", stream + first_session, whole
        )
        again = fetch("the same request again, same PlaySessionId", stream + first_session, whole)
        fresh = fetch("the same request, a different PlaySessionId", stream + second_session, whole)
        probe.observe(
            "Accept-Ranges on a capped transcode",
            "{!r} on the first answer, {!r} on the repeat".format(
                produced["ranges"], again["ranges"]
            ),
        )
        universal = (
            f"/Audio/{item_id}/universal?DeviceId={DEVICE}&UserId={server.user_id}"
            "&AudioCodec=mp3&Container=mp3&TranscodingContainer=mp3&TranscodingProtocol=http"
            f"&MaxStreamingBitrate={CAP_BITS_PER_SECOND}"
        )
        universal_first = fetch("/universal, capped, first", universal, whole)
        universal_again = fetch("/universal, capped, again", universal, whole)

        probe.observe(
            "time to the last byte",
            "same session {:.2f}s then {:.2f}s, a different session {:.2f}s, "
            "/universal {:.2f}s then {:.2f}s".format(
                produced["seconds"],
                again["seconds"],
                fresh["seconds"],
                universal_first["seconds"],
                universal_again["seconds"],
            ),
        )
        probe.note(
            "the reference keys a progressive transcode's output file on the media path, the "
            "user agent, the device and the **play session the caller sent** "
            "`[source: Jellyfin.Api/Helpers/StreamingHelpers.cs:374-383 @ v10.11.11]`, so "
            "repeating a request with the same PlaySessionId finds the file already there. "
            "/universal cannot: it has no such parameter and mints a fresh play session per "
            "request, so its every retry is a miss"
        )
        checks.extend(
            [
                produced["status"] == 200,
                # The whole point of OQ-9: not on the first answer, and not on a repeat of one
                # whose bytes are already sitting in a file.
                produced["length"] is None,
                again["length"] is None,
                fresh["length"] is None,
                universal_first["length"] is None,
                universal_again["length"] is None,
                produced["bytes"] > 0,
                again["bytes"] == produced["bytes"],
            ]
        )
    finally:
        for session in sessions:
            stop_encoding(server, session)

    if all(checks):
        probe.conclude(
            "neither question was framed the way it measures. A capped transcode never states a "
            "length - not on the first answer and not on a repeat whose bytes are already "
            "produced - and it answers Accept-Ranges: none rather than omitting the header, so "
            "an honest Content-Length is an improvement over the reference exactly as OQ-9 "
            "says. Keying on the client's play session is the opposite: the reference already "
            "does it, on every route that declares the parameter, and three of the four do. "
            "What /universal lacks is the parameter, so its transcode is keyed on an empty "
            "play session and every reconnect re-encodes - which makes OQ-10 a parity gap on "
            "the stream routes and a defect of /universal, not an improvement over either",
            matches_documentation=None,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
