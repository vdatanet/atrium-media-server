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
        self.video_stream: dict[str, Any] = video[0]
        self.video_range: str = video[0].get("VideoRange") or ""
        """`SDR` or `HDR`, the reference's own two-valued answer - which is what the master
        playlist's SDR-entrance branch turns on, and what no probe asked about until now."""

        self.video_range_type: str = video[0].get("VideoRangeType") or ""
        """The flavour: `SDR`, `HDR10`, `HDR10Plus`, `HLG` or one of the eight Dolby Vision
        spellings. Only the Dolby Vision and HDR10+ members produce a `SUPPLEMENTAL-CODECS`."""

    @property
    def is_hdr(self) -> bool:
        return self.video_range.upper() == "HDR"

    @property
    def is_dolby_vision(self) -> bool:
        return self.video_range_type.upper().startswith("DOVI")

    def other_container(self) -> str:
        return "mp4" if self.container != "mp4" else "mkv"

    def other_video_codec(self) -> str:
        return "h264" if self.video_codec != "h264" else "hevc"

    def other_audio_codec(self) -> str:
        for candidate in ("vorbis", "flac", "mp3"):
            if candidate not in self.audio_codecs:
                return candidate
        raise ProbeError("could not name an audio codec the source does not already contain")


#: How many rows `pick_video_source` reads before giving up. A library of dummy files is not a
#: library with nothing in it, and a probe that cannot tell them apart reports the wrong finding.
PLAYABLE_SEARCH_LIMIT = 50


def pick_video_source(server: Server, kind: str = "Movie") -> VideoSource:
    """The first video item the library offers, with its measured media source.

    Read from `/Items/{id}` rather than from a profile-less negotiation on purpose: a
    negotiation without a profile reports the source's `Container` as the raw demuxer list
    (`mov,mp4,m4a,...`) - normalisation to the single resolved container happens only against a
    profile - and a probe building a container-rejecting profile from the list form would
    reject nothing. `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11, 2026-08-28]`
    """
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes=kind,
        Recursive="true",
        Limit=PLAYABLE_SEARCH_LIMIT,
        SortBy="SortName",
    )
    rows = found.get("Items", [])
    if not rows and kind == "Movie":
        return pick_video_source(server, kind="Episode")
    if not rows:
        raise ProbeError("the library holds no movie or episode to negotiate against")
    # **The first row is not necessarily playable, and taking it is how a probe reports a library
    # instead of a server.** Measured 2026-09-02 against the single-use reference instance: the
    # fixture tree's first movie is a file of dummy bytes, so `VideoSource` refused the whole
    # probe over a source that carries no stream at all. The same trap the HDR search below was
    # written for - "the first item" - one question earlier.
    refusals: list[str] = []
    fallback: VideoSource | None = None
    for row in rows:
        item_id = row["Id"]
        item = server.get(f"/Items/{item_id}", userId=server.user_id)
        sources = item.get("MediaSources") or []
        if not sources:
            refusals.append(f"{item_id} carries no media source")
            continue
        try:
            candidate = VideoSource(item_id, sources[0])
        except ProbeError as unusable:
            refusals.append(str(unusable))
            continue
        # **A film with an embedded subtitle track is not a neutral source for a ladder
        # question.** A named or defaulted track that resolves to anything but External, Embed or
        # Drop refuses direct play on its own (011 spec section 3.3), so a probe building a
        # profile with no `SubtitleProfiles` would measure that rule and report it as a
        # container or codec finding. Measured 2026-09-02: the fixture tree's first playable
        # film carries a `subrip` and a `PGSSUB` track, and an accepting profile is answered
        # `SupportsDirectPlay: false`. One without is preferred; one with is better than none.
        if not [one for one in sources[0].get("MediaStreams", []) if one.get("Type") == "Subtitle"]:
            return candidate
        if fallback is None:
            fallback = candidate
    if fallback is not None:
        return fallback
    raise ProbeError(
        f"none of the first {len(rows)} {kind} rows can be negotiated about: "
        + "; ".join(refusals[:5])
    )


#: How many items `pick_hdr_video_source` reads before giving up. High dynamic range is a
#: minority of any library, so "the first item" - which is what `pick_video_source` takes, and
#: what left OQ-7 measuring a branch it could not reach - answers SDR almost everywhere.
HDR_SEARCH_LIMIT = 400


def pick_hdr_video_source(
    server: Server, kind: str = "Movie", *, dolby_vision: bool = False
) -> VideoSource | None:
    """The first high-dynamic-range video the library holds, or None if it holds none.

    **This is the helper OQ-7 needed and did not have.** The master playlist grows extra
    `#EXT-X-STREAM-INF` entrances only where the video is stream-copied *and* the source is HDR
    `[source: Jellyfin.Api/Helpers/DynamicHlsHelper.cs:218-268 @ v10.11.11]`, so a probe that
    takes whatever item the library lists first measures the branch's absence and learns nothing
    about the branch.

    Returns None rather than raising: a library with no HDR video cannot answer this question,
    and saying so is the honest report. The caller decides whether that is a skip or a failure.
    """
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes=kind,
        Recursive="true",
        Fields="MediaSources",
        Limit=HDR_SEARCH_LIMIT,
    )
    rows = found.get("Items", [])
    if not rows and kind == "Movie":
        return pick_hdr_video_source(server, kind="Episode", dolby_vision=dolby_vision)
    for row in rows:
        for source in row.get("MediaSources") or []:
            video = [s for s in source.get("MediaStreams", []) if s.get("Type") == "Video"]
            if not video or (video[0].get("VideoRange") or "").upper() != "HDR":
                continue
            if dolby_vision and not (video[0].get("VideoRangeType") or "").upper().startswith(
                "DOVI"
            ):
                continue
            # Re-read through `/Items/{id}` for the reason `pick_video_source` documents: only
            # that route reports the single resolved container a rejecting profile needs.
            item = server.get(f"/Items/{row['Id']}", userId=server.user_id)
            sources = item.get("MediaSources") or []
            if sources:
                return VideoSource(row["Id"], sources[0])
    return None


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
        # This connection's own device, never the module constant: a device is per account
        # since 010 T13, and a stop naming somebody else's device stops nothing.
        deviceId=server.device_id,
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


# ------------------------------------------------------------------------------------------
# Subtitles
# ------------------------------------------------------------------------------------------


#: The score the reference holds on each subtitle stream, recomputed from the stream's own
#: properties. Six digits, each a decision, read left to right as language rank then five flags
#: `[source: Emby.Server.Implementations/Library/MediaStreamSelector.cs:181-192 @ v10.11.11]`.
#: A probe recomputes it rather than trusting the emitted value, because reproducing the ranking
#: is what a second implementation has to be able to do.
def subtitle_score(stream: dict[str, Any], preferred_languages: list[str]) -> int:
    language = (stream.get("Language") or "").lower()
    ranked = [str(x).lower() for x in preferred_languages]
    index = ranked.index(language) if language in ranked else -1
    score = 1 if index == -1 else 101 - index
    score = (score * 10) + (2 if stream.get("IsForced") else 1)
    score = (score * 10) + (2 if stream.get("IsDefault") else 1)
    score = (score * 10) + (2 if stream.get("SupportsExternalStream") else 1)
    score = (score * 10) + (2 if stream.get("IsTextSubtitleStream") else 1)
    score = (score * 10) + (2 if stream.get("IsExternal") else 1)
    return score


class SubtitledSource:
    """One item whose media source carries subtitle streams, split by kind."""

    def __init__(self, item_id: str, source: dict[str, Any]) -> None:
        self.item_id = item_id
        self.source = source
        self.source_id: str = source.get("Id") or item_id
        self.runtime_ticks: int = source.get("RunTimeTicks") or 0
        streams = source.get("MediaStreams") or []
        self.subtitles = [s for s in streams if s.get("Type") == "Subtitle"]
        self.text = [s for s in self.subtitles if s.get("IsTextSubtitleStream")]
        self.image = [s for s in self.subtitles if not s.get("IsTextSubtitleStream")]
        self.external = [s for s in self.subtitles if s.get("IsExternal")]
        self.embedded = [s for s in self.subtitles if not s.get("IsExternal")]

    def text_index(self) -> int:
        return int(self.text[0]["Index"])

    def image_index(self) -> int:
        return int(self.image[0]["Index"])

    def top_score_tie(self, preferred_languages: list[str]) -> list[int]:
        """The indices sharing the highest recomputed score, when more than one does.

        The reference's own default only consults the client's profile when this list has more
        than one member, so a probe that wants to measure the tie-break has to find one first.
        """
        if not self.subtitles:
            return []
        scored = [(subtitle_score(s, preferred_languages), int(s["Index"])) for s in self.subtitles]
        best = max(score for score, _ in scored)
        return [index for score, index in scored if score == best]


def find_subtitled_sources(
    server: Server,
    limit: int = 400,
) -> list[SubtitledSource]:
    """Every movie or episode in the library whose source carries at least one subtitle stream.

    Read from the listing with `Fields=MediaStreams` rather than item by item: the four probes
    that need one of these each want a *different* shape - text and image together, an external
    file, two streams that tie on score - and one listing answers all of them.
    """
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes="Movie,Episode",
        Recursive="true",
        Limit=limit,
        Fields="MediaStreams",
    )
    sources: list[SubtitledSource] = []
    for row in found.get("Items", []):
        streams = row.get("MediaStreams") or []
        if not any(s.get("Type") == "Subtitle" for s in streams):
            continue
        sources.append(
            SubtitledSource(
                row["Id"],
                {"Id": row["Id"], "RunTimeTicks": row.get("RunTimeTicks"), "MediaStreams": streams},
            )
        )
    if not sources:
        raise ProbeError(
            "the library holds no movie or episode with a subtitle stream, so nothing here can "
            "be measured. Point the probe at a library that has one"
        )
    return sources


def resolve_subtitled_source(server: Server, item_id: str) -> SubtitledSource:
    """The full media source of one item, which is where `Id` and `RunTimeTicks` are honest.

    A listing row carries `MediaStreams` but not the media source's own identifier, and every
    subtitle address names both.
    """
    item = server.get("/Items/" + item_id, userId=server.user_id)
    sources = item.get("MediaSources") or []
    if not sources:
        raise ProbeError("item " + item_id + " carries no media source")
    return SubtitledSource(item_id, sources[0])
