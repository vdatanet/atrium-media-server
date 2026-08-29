#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared plumbing for the playback probes.

The 008 probes all start from the same place: find a real video item, learn what its file
actually contains from a profile-less negotiation, and then build a device profile that rejects
exactly one property of it - the container, the video codec, the audio codec - so the answer the
reference gives is attributable to that one rejection. Building the profile relative to the
measured source is what lets these probes run against any library rather than one with known
fixtures.

Standard library only, like everything under tools/.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from _probe import ProbeError, Server

#: The transcoding target every video probe offers: what real browser profiles offer.
TS_HLS_H264 = {
    "Container": "ts",
    "Type": "Video",
    "VideoCodec": "h264",
    "AudioCodec": "aac",
    "Protocol": "hls",
    "Context": "Streaming",
    "MinSegments": 1,
    "BreakOnNonKeyFrames": True,
}


def dashed(item_id: str) -> str:
    """The 32-hex id in its dashed GUID form, as the reference's TranscodingUrl paths spell it."""
    return f"{item_id[:8]}-{item_id[8:12]}-{item_id[12:16]}-{item_id[16:20]}-{item_id[20:]}"


def base_profile(
    direct_play: list[dict[str, Any]],
    transcoding: list[dict[str, Any]] | None = None,
    codec_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "MaxStreamingBitrate": 120_000_000,
        "DirectPlayProfiles": direct_play,
        "TranscodingProfiles": [TS_HLS_H264] if transcoding is None else transcoding,
        "CodecProfiles": codec_profiles or [],
        "ContainerProfiles": [],
        "SubtitleProfiles": [],
    }


class VideoSource:
    """One playable video item and what its file measurably contains."""

    def __init__(self, item_id: str, source: dict[str, Any]) -> None:
        self.item_id = item_id
        self.source = source
        self.container: str = source.get("Container") or ""
        self.runtime_ticks: int = source.get("RunTimeTicks") or 0
        video = [s for s in source.get("MediaStreams", []) if s.get("Type") == "Video"]
        audio = [s for s in source.get("MediaStreams", []) if s.get("Type") == "Audio"]
        if not video or not audio:
            raise ProbeError(f"item {item_id} has no video+audio stream pair to negotiate about")
        self.video_codec: str = video[0].get("Codec") or ""
        self.audio_codecs: list[str] = sorted({s.get("Codec") or "" for s in audio})

    def other_container(self) -> str:
        return "mp4" if self.container != "mp4" else "mkv"

    def other_video_codec(self) -> str:
        return "h264" if self.video_codec != "h264" else "hevc"

    def other_audio_codec(self) -> str:
        for candidate in ("vorbis", "flac", "mp3"):
            if candidate not in self.audio_codecs:
                return candidate
        raise ProbeError("could not name an audio codec the source does not already contain")


def pick_video_source(server: Server, kind: str = "Movie") -> VideoSource:
    """The first video item the library offers, with its measured media source.

    Read from `/Items/{id}` rather than from a profile-less negotiation on purpose: a
    negotiation without a profile reports the source's `Container` as the raw demuxer list
    (`mov,mp4,m4a,...`) - normalisation to the single resolved container happens only against a
    profile - and a probe building a container-rejecting profile from the list form would
    reject nothing. `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28]`
    """
    found = server.get(
        "/Items", UserId=server.user_id, IncludeItemTypes=kind, Recursive="true", Limit=1
    )
    rows = found.get("Items", [])
    if not rows and kind == "Movie":
        return pick_video_source(server, kind="Episode")
    if not rows:
        raise ProbeError("the library holds no movie or episode to negotiate against")
    item_id = rows[0]["Id"]
    item = server.get(f"/Items/{item_id}", userId=server.user_id)
    sources = item.get("MediaSources") or []
    if not sources:
        raise ProbeError(f"item {item_id} carries no media source")
    return VideoSource(item_id, sources[0])


def negotiate(
    server: Server,
    item_id: str,
    profile: dict[str, Any] | None,
    **body_extras: Any,
) -> tuple[int, dict[str, Any]]:
    body: dict[str, Any] = {"UserId": server.user_id, "AutoOpenLiveStream": False}
    if profile is not None:
        body["DeviceProfile"] = profile
    body.update(body_extras)
    status, _, payload = server.post_raw(f"/Items/{item_id}/PlaybackInfo", body=body)
    return status, json.loads(payload) if payload else {}


def stop_encoding(server: Server, play_session_id: str) -> int:
    """Stop one transcoding session; the probes' cleanup path, called on failure too."""
    status, _, _ = server.delete_raw(
        "/Videos/ActiveEncodings",
        deviceId="atrium-probe-0000",
        playSessionId=play_session_id,
    )
    return status


@dataclass(frozen=True)
class Playlists:
    """Both playlists of one negotiation, with the headers each of them answered with.

    008 T10 measures the bytes rather than a summary of them - the field order of the variant
    line, the exact `#EXTINF` formatting, whether either response is sized - so the whole text
    of both is carried here instead of the three values `fetch_main_playlist` distils.
    """

    master: str
    master_headers: dict[str, str]
    variant: str
    """The `#EXT-X-STREAM-INF` line, verbatim, or `""` when the master carries none."""

    variant_url: str
    """The line beneath it: a relative `main.m3u8` and the whole forwarded query."""

    main: str
    main_headers: dict[str, str]
    segments: list[str]
    durations: list[float]


def fetch_playlists(server: Server, item_id: str, transcoding_url: str) -> Playlists:
    """Follow a negotiation's TranscodingUrl to its master and media playlists.

    The master playlist's relative `main.m3u8` line keeps the whole query string, which is how
    the parameters survive the hop.
    """
    status, master_headers, master = server._request("GET", transcoding_url, raw=True)
    if status != 200:
        raise ProbeError(f"master.m3u8 answered {status}")
    master_text = master.decode()
    main_lines = [line for line in master_text.splitlines() if line.startswith("main.m3u8")]
    if not main_lines:
        raise ProbeError("master playlist carries no main.m3u8 line")
    variant = next(
        (line for line in master_text.splitlines() if line.startswith("#EXT-X-STREAM-INF")), ""
    )
    status, main_headers, main = server._request(
        "GET", f"/videos/{dashed(item_id)}/{main_lines[0]}", raw=True
    )
    if status != 200:
        raise ProbeError(f"main.m3u8 answered {status}")
    text = main.decode()
    segments = [
        f"/videos/{dashed(item_id)}/{line}"
        for line in text.splitlines()
        if line and not line.startswith("#")
    ]
    durations = [
        float(line.split(":", 1)[1].split(",", 1)[0])
        for line in text.splitlines()
        if line.startswith("#EXTINF")
    ]
    return Playlists(
        master=master_text,
        master_headers=dict(master_headers),
        variant=variant,
        variant_url=main_lines[0],
        main=text,
        main_headers=dict(main_headers),
        segments=segments,
        durations=durations,
    )


def fetch_main_playlist(
    server: Server, item_id: str, transcoding_url: str
) -> tuple[str, list[str], list[float]]:
    """`fetch_playlists`' first three answers, for the probes that want nothing else."""
    playlists = fetch_playlists(server, item_id, transcoding_url)
    return playlists.main, playlists.segments, playlists.durations
