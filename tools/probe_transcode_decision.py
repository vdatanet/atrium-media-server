#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does the reference put in a TranscodingUrl, and does it copy the stream the profile
accepts?

specs/008 OQ-7, OQ-8 and OQ-9. A device profile that accepts the source's video codec but
rejects its audio codec is posted; the negotiation's TranscodingUrl is taken apart; the master
playlist is fetched (how many variants?); and one segment is produced, so that the session's
TranscodingInfo - and ffprobe, where the machine has one - can say whether the accepted video
stream was copied or re-encoded alongside the audio.

**The same request is then made twice, once against a standard-range source and once against a
high-dynamic-range one**, because OQ-7's first answer - "exactly one variant" - was generalised
from a run that could not reach the branch it was answering about. The reference appends SDR
entrances beside a stream copy only when the *source* is HDR
`[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:218-268 @ v10.11.11]`, and this probe took
whatever item the library listed first, which is standard range in almost any library. The HDR
half picks a source by its measured `VideoRange` and reports the range back, so the run says on
its face whether it reached the branch.

Needs --allow-writes: fetching a segment makes the reference start a real encode in its scratch
space. The probe fetches one segment per half, reads the answer, and stops both sessions -
including on failure. The HDR half asks for fMP4 segments, because the Dolby Vision codec tag it
measures lives in the sample entry of an initialisation segment and MPEG-TS has nowhere to put
one; an HDR film is usually 4K, so that segment is tens of megabytes rather than hundreds of
kilobytes.

Usage:
    python3 tools/probe_transcode_decision.py http://your-jellyfin:8096 -u user --allow-writes
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.parse
from typing import Any

from _playback import (
    base_profile,
    dashed,
    fetch_main_playlist,
    fetch_playlists,
    negotiate,
    pick_hdr_video_source,
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
            "hls; the master playlist advertises one variant for a standard-range copy and one "
            "SDR entrance per enabled encoder beside it for a high-dynamic-range one, every "
            "variant at the same BANDWIDTH; and the delivered segments carry the source's video "
            "codec untouched (the copy), with only the audio re-encoded"
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
        # The source's own range is what makes that count attributable. Recorded rather than
        # assumed, because assuming it is exactly how OQ-7 came to answer for a branch this half
        # of the probe cannot reach.
        probe.observe("source range", f"{source.video_range}/{source.video_range_type}")
        if source.is_hdr:
            probe.note(
                "the library's first video is itself HDR, so this half reached the entrance "
                "branch as well: 'exactly one variant' is a claim about a standard-range copy, "
                "and this run has no standard-range source to check it against."
            )
            checks.append(len(variants) > 1)
        else:
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
            if session.get("DeviceId") == server.device_id and session.get("TranscodingInfo"):
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

    checks += _hdr_master(server, probe)

    if all(checks):
        probe.conclude(
            "as documented: one variant for a standard-range copy and an SDR entrance per "
            "enabled encoder beside an HDR one, the measured URL anatomy, and the compatible "
            "video stream copied while only the audio is re-encoded",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


def _attributes(line: str) -> dict[str, str]:
    """The `#EXT-X-STREAM-INF` attribute list, split on the commas that are not inside quotes.

    `CODECS="hvc1.2.4.L150.B0,mp4a.40.2"` is one attribute containing a comma, so a plain split
    would read it as two and lose the audio half of every variant.
    """
    found: dict[str, str] = {}
    quoted = False
    current = ""
    for character in line.split(":", 1)[1]:
        if character == '"':
            quoted = not quoted
        if character == "," and not quoted:
            found.update(_one_attribute(current))
            current = ""
            continue
        current += character
    found.update(_one_attribute(current))
    return found


def _one_attribute(text: str) -> dict[str, str]:
    name, separator, value = text.partition("=")
    return {name.strip(): value.strip('"')} if separator else {}


def _hdr_master(server: Server, probe: Probe) -> list[bool]:
    """The half OQ-7 was missing: the same rejection against a high-dynamic-range source.

    Reaching the branch takes three things at once, and the probe reports all three so a reader
    can tell a real measurement from a run that missed: the source must be HDR, the video must
    be **copied** rather than re-encoded, and the operator's encoder permissions decide how many
    entrances stand beside the copy. The proof that the copy happened is on the wire - the
    reference labels a re-encoded variant `VIDEO-RANGE=SDR` and only a copy carries `PQ` or
    `HLG` `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:364-397 @ v10.11.11]`.
    """
    encoding: dict[str, Any] = server.get("/System/Configuration/encoding")
    probe.observe(
        "encoder permissions",
        f"AllowHevcEncoding={encoding.get('AllowHevcEncoding')}, "
        f"AllowAv1Encoding={encoding.get('AllowAv1Encoding')} "
        f"(both ship false)",
    )

    source = pick_hdr_video_source(server, dolby_vision=True) or pick_hdr_video_source(server)
    if source is None:
        probe.note(
            "this library holds no high-dynamic-range video, so the entrance branch could not "
            "be reached and nothing here was measured. Point the probe at a library that has "
            "one before citing it for OQ-7."
        )
        return []

    probe.observe(
        "HDR source",
        f"{source.container}, {source.video_codec} "
        f"{source.video_range}/{source.video_range_type}, "
        f"DvProfile={source.video_stream.get('DvProfile')}, "
        f"DvLevel={source.video_stream.get('DvLevel')}",
    )

    # fMP4 rather than MPEG-TS: the Dolby Vision codec tag is a sample-entry four-character code,
    # and MPEG-TS has no sample entry to carry one. The range-type condition is what puts
    # `{codec}-rangetype` in the negotiated URL, and the tag branch reads it back: a client that
    # does not name DOVI is given the plain `hvc1` even on a Dolby Vision copy `[source:
    # Jellyfin.Api/Controllers/DynamicHlsController.cs:1838-1866 @ v10.11.11]`.
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
                "Container": "mp4",
                "Type": "Video",
                "VideoCodec": f"{source.video_codec},h264",
                "AudioCodec": "aac",
                "Protocol": "hls",
                "Context": "Streaming",
                "MinSegments": 1,
                "BreakOnNonKeyFrames": True,
            }
        ],
        codec_profiles=[
            {
                "Type": "Video",
                "Codec": source.video_codec,
                "Conditions": [
                    {
                        "Condition": "EqualsAny",
                        "Property": "VideoRangeType",
                        "Value": f"SDR|HDR10|HLG|HDR10Plus|DOVI|{source.video_range_type}",
                        "IsRequired": False,
                    }
                ],
            }
        ],
    )
    status, data = negotiate(server, source.item_id, profile)
    url = (data.get("MediaSources") or [{}])[0].get("TranscodingUrl")
    if not url:
        probe.observe("HDR negotiation", f"{status}, no TranscodingUrl")
        probe.note("the HDR source direct-plays under this profile, so no copy was planned.")
        return [False]

    checks: list[bool] = []
    play_session_id = data["PlaySessionId"]
    try:
        playlists = fetch_playlists(server, source.item_id, url)
        lines = playlists.master.splitlines()
        variants = [line for line in lines if line.startswith("#EXT-X-STREAM-INF")]
        uris = [line for line in lines if line.startswith("main.m3u8")]
        probe.observe("HDR master playlist", f"{len(variants)} variant(s)")
        checks.append(len(variants) > 1)

        if len(variants) != len(uris):
            raise ProbeError("a variant line without a URI beneath it")
        attributes = [_attributes(line) for line in variants]
        queries = [_query_of(uri) for uri in uris]
        for index in range(len(variants)):
            fields, query = attributes[index], queries[index]
            probe.observe(
                f"variant {index}",
                f"BANDWIDTH={fields.get('BANDWIDTH')}, "
                f"VIDEO-RANGE={fields.get('VIDEO-RANGE')}, "
                f"CODECS={fields.get('CODECS')!r}, "
                f"SUPPLEMENTAL-CODECS={fields.get('SUPPLEMENTAL-CODECS')!r}, "
                f"VideoCodec={query.get('VideoCodec', ['absent'])[0]}, "
                f"AllowVideoStreamCopy={query.get('AllowVideoStreamCopy', ['absent'])[0]}",
            )

        # The first variant is the copy, and only a copy is labelled from the source's transfer.
        # This is the run's own proof that it reached the branch rather than describing it.
        checks.append(attributes[0].get("VIDEO-RANGE") in {"PQ", "HLG"})
        # "HACK: Use the same bitrate so that the client can choose by other attributes" - so
        # every entrance is offered at the copy's own rate and the client selects on colour.
        checks.append(len({fields.get("BANDWIDTH") for fields in attributes}) == 1)
        checks.append(len({fields.get("AVERAGE-BANDWIDTH") for fields in attributes}) == 1)
        # RESOLUTION and FRAME-RATE describe the output size and rate, neither of which an
        # entrance changes - so they are identical on every variant.
        checks.append(len({fields.get("RESOLUTION") for fields in attributes}) == 1)
        checks.append(len({fields.get("FRAME-RATE") for fields in attributes}) == 1)
        # Each entrance is an SDR re-encode, addressed with the copy switched off, and one of
        # them is always h264 - the entrance the reference appends whatever the encoders allow.
        for index in range(1, len(variants)):
            checks.append(attributes[index].get("VIDEO-RANGE") == "SDR")
            checks.append(queries[index].get("AllowVideoStreamCopy") == ["false"])
            checks.append("SUPPLEMENTAL-CODECS" not in attributes[index])
        checks.append(any(query.get("VideoCodec") == ["h264"] for query in queries[1:]))

        supplemental = attributes[0].get("SUPPLEMENTAL-CODECS")
        probe.observe("SUPPLEMENTAL-CODECS on the copy", supplemental or "absent")
        checks.append(bool(supplemental) == source.is_dolby_vision)

        checks += _dolby_vision_tag(server, probe, source, playlists.main)
    finally:
        stopped = stop_encoding(server, play_session_id)
        probe.observe("HDR cleanup DELETE /Videos/ActiveEncodings", stopped)
    return checks


def _query_of(uri: str) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(uri.split("?", 1)[1])


def _dolby_vision_tag(server: Server, probe: Probe, source: Any, main: str) -> list[bool]:
    """The four-character code the reference writes into a Dolby Vision copy's sample entry.

    Not a playlist field: the master's `CODECS` says `hvc1` for every HEVC output, copy or not
    `[source: Jellyfin.Api/Helpers/HlsCodecStringHelpers.cs GetH265String @ v10.11.11]`. The
    `dvh1` is an encoder argument, so it is only visible in the produced bytes - and only in an
    fMP4 initialisation segment, which is why this half asks for `SegmentContainer=mp4`
    `[source: Jellyfin.Api/Controllers/DynamicHlsController.cs:1838-1866 @ v10.11.11]`.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        probe.note("ffprobe not on PATH: the Dolby Vision sample-entry tag was not read.")
        return []
    base = f"/videos/{dashed(source.item_id)}/"
    initialisation = [line for line in main.splitlines() if line.startswith("#EXT-X-MAP")]
    segments = [line for line in main.splitlines() if line and not line.startswith("#")]
    if not initialisation or not segments:
        probe.note("no #EXT-X-MAP in the media playlist: this negotiation is not fMP4.")
        return []
    _, _, header = server._request(
        "GET", base + initialisation[0].split('URI="', 1)[1].rstrip('"'), raw=True
    )
    status, _, segment = server._request("GET", base + segments[0], raw=True)
    result = subprocess.run(  # noqa: S603 - inspecting bytes this probe fetched
        [ffprobe, "-v", "quiet", "-print_format", "json", "-show_streams", "-"],
        input=header + segment,
        capture_output=True,
        check=False,
    )
    streams = json.loads(result.stdout or b"{}").get("streams", [])
    video = [one for one in streams if one.get("codec_type") == "video"]
    if not video:
        probe.note("ffprobe could not parse the initialisation segment plus the first segment.")
        return [status == 200]
    tag = video[0].get("codec_tag_string")
    probe.observe(
        "sample entry of the copied video",
        f"{video[0].get('codec_name')} tag={tag!r}, transfer={video[0].get('color_transfer')!r}",
    )
    # `hvc1` for a Dolby Vision stream with an HLG base layer, `dvh1` for every other, and
    # `hvc1` for HEVC that is not Dolby Vision at all.
    expected = "dvh1" if source.is_dolby_vision else "hvc1"
    return [tag == expected]


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
