#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which constraints does /Audio/{id}/universal actually meet, and when does it redirect?

specs/008 OQ-4 and §3.6. Four questions against one short track:

- a constraint the source already satisfies: what do the direct-play headers look like?
- a sample-rate ceiling below the source: the answer is re-encoded, but the target rate comes
  from the five-step ladder Opus needs - `<=8000, <=12000, <=16000, <=24000, else 48000` -
  applied to **every** codec, so a 22050 ceiling is answered at 24000 and a 44100 ceiling at
  48000: above what the client stated. The restructure that scopes the ladder to Opus is
  merged upstream as `jellyfin/jellyfin#17537` and is in no 10.11.x - stated as prose rather
  than as a `[prior-probe:]`, which it never was: nobody measured a patched server;
- the same request without `AudioCodec`: the reference's codec-less transcoding profile
  produces a broken ffmpeg invocation and the route answers `200` with an empty body;
- `enableRedirection` on a local file: no `302` - the redirect exists only for remote HTTP
  sources with EnableRemoteMedia `[source: Jellyfin.Api/Controllers/
  UniversalAudioController.cs:175 @ v10.11.11]`.

008 T8 added three batteries, because the task that lands a route measures that route's own
shapes rather than borrowing a sibling's:

- **the direct-play header set**, whole rather than two named headers, so a conformance test can
  assert it as a set the way the four `stream` routes' is asserted;
- **the codec-less request with no `TranscodingContainer` at all**, which separates "the codec
  falls back to something" from "the codec falls back to the *container's*" - the distinction
  the divergence of behaviours section 3.8 is written in terms of;
- **the refusals**: no credential, an unknown item, and the two `mediaSourceId` shapes, since
  this is the one delivery route that requires a token and its 404 had never been read.

And one reading left for 008 T10: what `TranscodingProtocol=hls` answers here.

008 T9 added a **WAV battery**, which is where the two `[prior-probe: 2026-08-03]` citations of
behaviours section 3.2 are discharged. It measures both symptoms on both route families, and it
corrects the shapes those citations recorded:

- symptom 1, the `500`, has **two causes**, not one: `stream.wav` naming no codec infers an
  encoder called `wav`, and any `pcm_*` codec sent without an `AudioBitRate` builds `-ar ` from
  an empty field. The second reaches `/universal` too;
- symptom 2, the headerless body, needs that bitrate, and appears on `stream.wav` as readily as
  on `/universal`. On `/universal` it is the **transcoding** container that has to be `wav`:
  `Container=wav` is the direct-play list and answers mp3;
- and one wav shape is not broken at all - a `wav` transcoding container with *no* codec answers
  a real `RIFF`, which narrows behaviours section 3.8.

**Every request in that battery carries a fresh `DeviceId`**, and it has to. The reference names
its transcode output `md5(media path - user agent - device id - play session id)` `[source:
Jellyfin.Api/Helpers/StreamingHelpers.cs GetOutputFilePath @ v10.11.11]`, which does not include
the parameters that decide whether the command is valid - so a request that cannot be produced
at all answers `200` with a **neighbouring** request's bytes. Measured: the broken shape answers
`500`, the working shape answers `200`, and the broken shape on that same device then answers
`200` as well. The first draft of this battery reported four false passes from exactly that.

Needs --allow-writes: the constraint cases make the reference start real audio encodes. The
probe reads only the first bytes of each answer and closes, which is the same signal a
disconnecting client sends and triggers the reference's own kill path.

Usage:
    python3 tools/probe_universal_audio.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import urllib.parse
import uuid

from _probe import Probe, ProbeError, Server, main

#: A codec from the raw-sample family, which is what makes a request a PCM request at all.
PCM_CODEC = "pcm_s16le"

#: A bitrate, whose only job is to be present. It is fed to `-ar` as though it were a sample rate
#: - so the number is never the output's rate, and stating it is the difference between a `500`
#: and a body (behaviours section 3.2).
SOME_BITRATE = 128000


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


def header_names(headers: dict) -> str:
    """The header set, sorted and joined - a set is what a conformance test asserts."""
    return ", ".join(sorted(headers))


def body_shape(headers: dict, payload: bytes) -> str:
    """A refusal in the terms behaviours section 1.11 splits them by: type, and the bytes."""
    return f"{headers.get('Content-Type') or 'no content type'}, {payload[:80]!r}"


def riff(payload: bytes) -> bool:
    """Whether these bytes begin the way a WAVE file has to."""
    return payload[:4] == b"RIFF" and payload[8:12] == b"WAVE"


def wav_shape(status: int, headers: dict, payload: bytes) -> str:
    """One WAV answer in the three terms behaviours section 3.2 turns on."""
    if status != 200:
        return f"{status}, {headers.get('Content-Type')}, {payload[:24]!r}"
    body = "a real RIFF header" if riff(payload) else "headerless, " + repr(payload[:8])
    return (
        f"200, {headers.get('Content-Type')}, {body}, "
        f"Content-Length {headers.get('Content-Length') or 'absent'}, "
        f"Accept-Ranges {headers.get('Accept-Ranges') or 'absent'}"
    )


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
            "an empty body (the codec-less transcoding profile breaks ffmpeg); "
            "enableRedirection never redirects a local file - 200, not 302; and every PCM "
            "request answers either a 500 (no codec at all, or a PCM codec with no AudioBitRate) "
            "or a 200 whose body has no RIFF header, on stream.wav and on a wav transcoding "
            "container alike (behaviours section 3.2)"
        ),
    )

    track_id, container, rate = pick_track(server)
    probe.observe("measured track", f"{container}, {rate} Hz")
    checks: list[bool] = []

    common = {
        "UserId": server.user_id or "",
        "DeviceId": server.device_id,
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
    probe.observe("  its whole header set", header_names(headers))
    checks.append(
        status == 200
        and headers.get("Content-Length") is not None
        and headers.get("Accept-Ranges") == "bytes"
    )

    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=32, extra_headers={"Range": "bytes=8-15"}
    )
    probe.observe(
        "  a mid-file Range on it",
        f"{status}, Content-Range {headers.get('Content-Range')}, {len(body)} bytes",
    )
    checks.append(status == 206 and len(body) == 8)

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

    query = urllib.parse.urlencode(
        {**common, "Container": "ogg", "TranscodingProtocol": "http", "MaxAudioSampleRate": ceiling}
    )
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=64
    )
    probe.observe(
        "  and without TranscodingContainer either",
        f"{status}, {len(body)} bytes, Content-Length {headers.get('Content-Length')}, "
        f"Content-Type {headers.get('Content-Type')}",
    )
    checks.append(status == 200 and len(body) == 0)

    query = urllib.parse.urlencode(
        {
            **common,
            "Container": "ogg",
            "TranscodingContainer": "flac",
            "TranscodingProtocol": "hls",
            "MaxAudioSampleRate": ceiling,
        }
    )
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=512
    )
    probe.observe(
        "TranscodingProtocol=hls",
        f"{status}, Content-Type {headers.get('Content-Type')}, {body[:48]!r}",
    )
    probe.note(
        "The hls variant hands off to the master playlist rather than to a progressive body, "
        "which is 008 T10's route; T8 refuses it rather than answering a playlist it cannot "
        "yet produce segments for."
    )

    # TranscodingProtocol is a nullable enumeration upstream, so the obvious implementation
    # declares one - and a declared enumeration refuses values this route serves.
    for stated in ("HLS", "banana"):
        query = urllib.parse.urlencode(
            {
                **common,
                "Container": "ogg",
                "TranscodingContainer": "flac",
                "AudioCodec": "flac",
                "TranscodingProtocol": stated,
                "MaxAudioSampleRate": ceiling,
            }
        )
        status, headers, body = server.get_streaming(
            f"/Audio/{track_id}/universal?{query}", max_bytes=64
        )
        probe.observe(
            f"  spelled {stated!r}",
            f"{status}, Content-Type {headers.get('Content-Type')}, {len(body)} bytes",
        )
        # `HLS` reaches the playlist and `banana` is ignored rather than refused: neither is a
        # `400`, which is what makes a typed parameter here the wrong shape.
        checks.append(status == 200)

    query = urllib.parse.urlencode({**common, "Container": container, "EnableRedirection": "true"})
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{query}", max_bytes=16
    )
    probe.observe(
        "enableRedirection on a local file",
        f"{status}, Location {headers.get('Location') or 'absent'}",
    )
    checks.append(status == 200 and headers.get("Location") is None)

    # The refusals. This is the one delivery route that requires a credential, which the range
    # matrix measured from the other side; what had never been read is what it refuses *with*,
    # nor what an unknown item or an unknown media source answers here.
    unknown_item = "deadbeefdeadbeefdeadbeefdeadbeef"
    bare = urllib.parse.urlencode({"Container": container, "DeviceId": common["DeviceId"]})
    status, headers, body = server.get_streaming(
        f"/Audio/{track_id}/universal?{bare}", max_bytes=256, send_token=False
    )
    probe.observe("no credential at all", f"{status}, {body_shape(headers, body)}")
    checks.append(status == 401 and not body)

    query = urllib.parse.urlencode({**common, "Container": container})
    status, headers, body = server.get_streaming(
        f"/Audio/{unknown_item}/universal?{query}", max_bytes=256
    )
    probe.observe("an item that does not exist", f"{status}, {body_shape(headers, body)}")
    checks.append(status == 404)

    for label, named in (
        ("a well-formed MediaSourceId naming no source", "beefdeadbeefdeadbeefdeadbeefdead"),
        ("a MediaSourceId that is not an identifier", "banana"),
    ):
        query = urllib.parse.urlencode({**common, "Container": container, "MediaSourceId": named})
        status, headers, body = server.get_streaming(
            f"/Audio/{track_id}/universal?{query}", max_bytes=256
        )
        probe.observe(label, f"{status}, {body_shape(headers, body)}")

    probe.note(
        "The redirect branch requires SupportsDirectPlay, protocol Http, IsRemote and the "
        "user's EnableRemoteMedia all at once [source: Jellyfin.Api/Controllers/"
        "UniversalAudioController.cs:175 @ v10.11.11]; a library file is protocol File, so the "
        "branch is unreachable for everything a v1 library contains."
    )

    checks.extend(_wav_battery(server, probe, track_id))

    if all(checks):
        probe.conclude(
            "as documented: the ceiling is answered from the Opus ladder - which can exceed "
            "it - the codec-less request is an empty 200, no local file is ever redirected, and "
            "every PCM request is either a 500 or a body with no RIFF header, on both route "
            "families, split by whether an AudioBitRate was sent",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


def _wav_battery(server: Server, probe: Probe, track_id: str) -> list[bool]:
    """Behaviours section 3.2's two symptoms, measured on both route families (008 T9).

    The battery this repository owed since the section was written: its two claims carried
    `[prior-probe: 2026-08-03]`, and a prior probe is a debt. Discharging it moved both of them -
    symptom 1 turns out to have two causes and symptom 2 turns out to name the wrong parameter.
    """
    checks: list[bool] = []
    stream = f"/Audio/{track_id}/stream"
    universal = f"/Audio/{track_id}/universal"

    def ask(label: str, path: str, params: dict, headers: dict | None = None) -> tuple:
        """One request, on a device that has never asked for anything (see the docstring)."""
        query = urllib.parse.urlencode(
            {
                "UserId": server.user_id or "",
                "DeviceId": f"atrium-probe-{uuid.uuid4().hex[:12]}",
                "api_key": server.token or "",
                **params,
            }
        )
        status, got, body = server.get_streaming(
            f"{path}?{query}", max_bytes=64, extra_headers=headers
        )
        probe.observe(label, wav_shape(status, got, body))
        return status, got, body

    # Symptom 1, and it has two causes. The first is not the one behaviours section 3.2 records:
    # `stream.wav` naming no codec never reaches the PCM path at all, because the codec inferred
    # from the extension is `wav` and `GetAudioEncoder` hands an unlisted name straight to
    # `-acodec` [source: MediaBrowser.Controller/MediaEncoding/EncodingHelper.cs:746-806 @
    # v10.11.11].
    status, _, _ = ask("stream.wav, no codec named", f"{stream}.wav", {})
    checks.append(status == 500)
    status, _, _ = ask(
        "stream.wav, a PCM codec, no bitrate", f"{stream}.wav", {"AudioCodec": PCM_CODEC}
    )
    checks.append(status == 500)
    status, _, _ = ask(
        "  the same by the container parameter",
        stream,
        {"Container": "wav", "AudioCodec": PCM_CODEC},
    )
    checks.append(status == 500)

    # Symptom 2, which the bitrate unlocks - on the `stream` pair, where the section had recorded
    # only a 500.
    status, headers, body = ask(
        "stream.wav, a PCM codec and a bitrate",
        f"{stream}.wav",
        {"AudioCodec": PCM_CODEC, "AudioBitRate": SOME_BITRATE},
    )
    checks.append(status == 200 and not riff(body) and headers.get("Content-Length") is None)

    status, _, body = ask(
        "  a Range on that body",
        f"{stream}.wav",
        {"AudioCodec": PCM_CODEC, "AudioBitRate": SOME_BITRATE},
        {"Range": "bytes=100-199"},
    )
    checks.append(status == 200)

    # And on /universal, where the section had recorded it - but against the wrong parameter.
    status, headers, body = ask(
        "universal, wav transcoding container",
        universal,
        {
            "Container": "ogg",
            "TranscodingContainer": "wav",
            "AudioCodec": PCM_CODEC,
            "AudioBitRate": SOME_BITRATE,
        },
    )
    checks.append(status == 200 and not riff(body) and headers.get("Content-Length") is None)

    status, _, _ = ask(
        "  the same without the bitrate",
        universal,
        {"Container": "ogg", "TranscodingContainer": "wav", "AudioCodec": PCM_CODEC},
    )
    checks.append(status == 500)

    status, headers, body = ask(
        "universal, Container=wav alone",
        universal,
        {"Container": "wav", "AudioBitRate": SOME_BITRATE},
    )
    checks.append(status == 200 and headers.get("Content-Type") == "audio/mpeg" and not body)

    status, _, body = ask(
        "universal, a wav target and no codec",
        universal,
        {"Container": "ogg", "TranscodingContainer": "wav", "AudioBitRate": SOME_BITRATE},
    )
    checks.append(status == 200 and riff(body))

    probe.note(
        "The last row is the one wav shape that is not broken, and it narrows behaviours "
        "section 3.8: a codec-less streaming request does not become its own path, it becomes "
        "`aac` - the container-validation regex rejects a string with slashes in it and "
        "GetAudioEncoder substitutes aac [source: MediaBrowser.Controller/MediaEncoding/"
        "EncodingHelper.cs:41,746-752 @ v10.11.11]. So the empty 200 is `aac` meeting a muxer "
        "that cannot hold it - flac, mp3 - and a wav target, which can, answers a real body."
    )

    # Why every row above is a fresh device. Ordered deliberately: the working shape first, then
    # the shape that cannot be produced, on the same device.
    shared = f"atrium-probe-{uuid.uuid4().hex[:12]}"
    common = {"UserId": server.user_id or "", "DeviceId": shared, "api_key": server.token or ""}
    for label, extra in (
        ("a device asks for the working shape", {"AudioBitRate": SOME_BITRATE}),
        ("  then the same device asks for the broken one", {}),
    ):
        query = urllib.parse.urlencode({**common, "AudioCodec": PCM_CODEC, **extra})
        status, headers, body = server.get_streaming(f"{stream}.wav?{query}", max_bytes=64)
        probe.observe(label, wav_shape(status, headers, body))
        checks.append(status == 200)

    probe.note(
        "Both answer 200, and the second cannot be produced at all - it is the first request's "
        "output being served again. The transcode file is named md5(media path - user agent - "
        "device id - play session id) [source: Jellyfin.Api/Helpers/StreamingHelpers.cs "
        "GetOutputFilePath @ v10.11.11], which is why nothing that decides whether the encoder "
        "can start changes the name. Atrium keys its own scratch on the whole command plus the "
        "file's change signal (008 T7), so the same pair of requests answers two bodies."
    )
    return checks


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
