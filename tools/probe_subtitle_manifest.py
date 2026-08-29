#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What makes the HLS master playlist announce a subtitle track, what each announcement says
verbatim, and where the name it carries comes from.

specs/011 §3.4, OQ-1, OQ-3 and OQ-4. Three batteries:

- **the lever** (OQ-1): the same master playlist fetched with nothing added, with
  `EnableSubtitlesInManifest=true`, and with each `SubtitleMethod` beside a stream index -
  including an image stream's index, and including the parameter the reference's *own*
  negotiation writes into the address it hands the client;
- **the anatomy** (OQ-3): the `#EXT-X-MEDIA` lines and the `#EXT-X-STREAM-INF` line verbatim,
  because a manifest is compared as text by nothing in this repository and as bytes by 010's
  differential;
- **the name** (OQ-4): what each announcement is called, beside every property that name is
  built from - the stream's title, its language, its flags, its codec - and beside the server's
  own interface culture, which is what decides the language the name is written in.

The traversal of 011 AC-8 starts here: every announced address is resolved against the master
playlist's own base and fetched, because an announcement that leads nowhere is the failure this
feature exists to prevent.

It makes the reference open a play session per negotiation and stops each one on the way out,
including on failure. It never fetches a segment.

Usage:
    python3 tools/probe_subtitle_manifest.py http://your-jellyfin:8096 -u username --allow-writes
"""

from __future__ import annotations

from typing import Any

from _playback import (
    TS_HLS_H264,
    SubtitledSource,
    base_profile,
    dashed,
    find_subtitled_sources,
    negotiate,
    resolve_subtitled_source,
    stop_encoding,
)
from _probe import Probe, ProbeError, Server, main

REJECTED_CONTAINER = "nothingatall"

#: The exact opening of an announcement, which is half of what OQ-3 asks.
MEDIA_PREFIX = '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="'

#: The six properties a stream's display title is assembled from, all of which the reference
#: localises. 008 §3.1 leaves every one of them absent on purpose.
LOCALISED = (
    "LocalizedUndefined",
    "LocalizedDefault",
    "LocalizedForced",
    "LocalizedExternal",
    "LocalizedHearingImpaired",
    "DisplayTitle",
)


def _profile(subtitle_profiles: list[dict[str, Any]], manifest_flag: bool) -> dict[str, Any]:
    transcoding = dict(TS_HLS_H264)
    if manifest_flag:
        transcoding["EnableSubtitlesInManifest"] = True
    profile = base_profile(
        [{"Container": REJECTED_CONTAINER, "Type": "Video"}], transcoding=[transcoding]
    )
    profile["SubtitleProfiles"] = subtitle_profiles
    return profile


def _media_lines(playlist: str) -> list[str]:
    marker = "#EXT-X-MEDIA:TYPE=SUBTITLES"
    return [line for line in playlist.splitlines() if line.startswith(marker)]


def _variant_line(playlist: str) -> str:
    for line in playlist.splitlines():
        if line.startswith("#EXT-X-STREAM-INF"):
            return line
    return ""


def _attribute(line: str, name: str) -> str:
    """One attribute of an `#EXT-X-MEDIA` line, quotes stripped.

    Written by hand rather than with a parser: the point of OQ-3 is the exact spelling, and a
    tolerant parser is exactly what would hide a difference in it.
    """
    marker = name + "="
    at = line.find(marker)
    if at == -1:
        return ""
    rest = line[at + len(marker) :]
    if rest.startswith('"'):
        return rest[1 : rest.find('"', 1)]
    end = rest.find(",")
    return rest if end == -1 else rest[:end]


def _pick(server: Server) -> SubtitledSource:
    """The source with the most text subtitle streams, preferring one that also has an image one.

    More text streams means more of the anatomy is measured at once - the language attribute, the
    forced attribute and the default attribute all vary across a real track list - and the image
    stream is what proves the filter.
    """
    candidates = [c for c in find_subtitled_sources(server) if c.text]
    if not candidates:
        raise ProbeError("the library holds no source with a text subtitle stream")
    candidates.sort(key=lambda c: (1 if c.image else 0, len(c.text)), reverse=True)
    return resolve_subtitled_source(server, candidates[0].item_id)


def _fetch(server: Server, url: str) -> str:
    status, _, payload = server._request("GET", url, raw=True)
    if status != 200:
        raise ProbeError(f"master.m3u8 answered {status}")
    return payload.decode("utf-8")


def _lever_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """OQ-1: which of the two conditions the source joins with an `or` is reachable here."""
    text = source.text_index()
    status, answered = negotiate(
        server,
        source.item_id,
        _profile([{"Format": "vtt", "Method": "Hls"}], manifest_flag=True),
        MediaSourceId=source.source_id,
    )
    if status != 200:
        raise ProbeError(f"negotiation answered {status}")
    one = answered["MediaSources"][0]
    url = one.get("TranscodingUrl")
    if not url:
        raise ProbeError("the negotiation answered no TranscodingUrl to follow")
    session = answered.get("PlaySessionId")
    try:
        probe.observe(
            "the address the negotiation hands the client",
            ", ".join(
                p for p in url.split("&") if "ubtitle" in p or "EnableSubtitlesInManifest" in p
            )
            or "names neither a subtitle nor a manifest flag",
        )
        cases = [
            ("as handed over", ""),
            ("+ EnableSubtitlesInManifest=true", "&EnableSubtitlesInManifest=true"),
            ("+ EnableSubtitlesInManifest=false", "&EnableSubtitlesInManifest=false"),
            (f"+ index {text} & method Hls", f"&SubtitleStreamIndex={text}&SubtitleMethod=Hls"),
            (
                f"+ index {text} & method External",
                f"&SubtitleStreamIndex={text}&SubtitleMethod=External",
            ),
            (
                f"+ index {text} & method Encode",
                f"&SubtitleStreamIndex={text}&SubtitleMethod=Encode",
            ),
            (f"+ index {text}, no method", f"&SubtitleStreamIndex={text}"),
        ]
        if source.image:
            cases.append(
                (
                    f"+ image index {source.image_index()} & method Hls",
                    f"&SubtitleStreamIndex={source.image_index()}&SubtitleMethod=Hls",
                )
            )
        announced = {}
        for label, extra in cases:
            playlist = _fetch(server, url + extra)
            lines = _media_lines(playlist)
            announced[label] = lines
            probe.observe(
                label,
                f"{len(lines)} media entries, variant "
                + (
                    "names the group"
                    if 'SUBTITLES="subs"' in _variant_line(playlist)
                    else "does not"
                ),
            )
        checks = [
            # The address the reference builds carries the manifest flag; the route it addresses
            # cannot read it. Both halves matter, and the second is the finding.
            not announced["as handed over"],
            not announced["+ EnableSubtitlesInManifest=true"],
            not announced["+ EnableSubtitlesInManifest=false"],
            len(announced[f"+ index {text} & method Hls"]) == len(source.text),
            not announced[f"+ index {text} & method External"],
            not announced[f"+ index {text} & method Encode"],
            not announced[f"+ index {text}, no method"],
        ]
        if source.image:
            image_case = announced[f"+ image index {source.image_index()} & method Hls"]
            # The filter is on the stream kind, not on the selection: selecting an image track
            # still announces every text track, with none of them marked as the default.
            checks.append(len(image_case) == len(source.text))
            checks.append(all(_attribute(line, "DEFAULT") == "NO" for line in image_case))
        return checks
    finally:
        if session:
            stop_encoding(server, session)


def _anatomy_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """OQ-3 and OQ-4: the lines verbatim, the name's ingredients, and the addresses resolved."""
    text = source.text_index()
    status, answered = negotiate(
        server,
        source.item_id,
        _profile([{"Format": "vtt", "Method": "Hls"}], manifest_flag=False),
        MediaSourceId=source.source_id,
        SubtitleStreamIndex=text,
    )
    if status != 200:
        raise ProbeError(f"negotiation answered {status}")
    one = answered["MediaSources"][0]
    url = one.get("TranscodingUrl") or ""
    session = answered.get("PlaySessionId")
    try:
        playlist = _fetch(server, url)
        lines = _media_lines(playlist)
        if not lines:
            raise ProbeError(
                "the negotiation's own address announced no subtitle track, so there is no "
                "anatomy to measure - see the lever battery for which parameter is missing"
            )
        for line in lines:
            probe.observe("media entry", line)
        probe.observe("variant line", _variant_line(playlist))

        by_index = {int(s["Index"]): s for s in source.subtitles}
        for line in lines:
            address = _attribute(line, "URI")
            index = int(address.split("/Subtitles/")[1].split("/")[0])
            stream = by_index[index]
            probe.observe(
                f"name of stream {index}",
                "NAME={!r} <- Title={!r}, Language={!r}, IsDefault={}, IsForced={}, "
                "IsHearingImpaired={}, Codec={!r}, IsExternal={}".format(
                    _attribute(line, "NAME"),
                    stream.get("Title"),
                    stream.get("Language"),
                    stream.get("IsDefault"),
                    stream.get("IsForced"),
                    stream.get("IsHearingImpaired"),
                    stream.get("Codec"),
                    stream.get("IsExternal"),
                ),
            )
        sample = by_index[int(_attribute(lines[0], "URI").split("/Subtitles/")[1].split("/")[0])]
        probe.observe(
            "the localised properties behind that name",
            ", ".join(f"{name}={sample.get(name)!r}" for name in LOCALISED),
        )
        try:
            configuration = server.get("/System/Configuration")
            probe.observe(
                "the server's own interface culture",
                "UICulture={!r}, PreferredMetadataLanguage={!r}".format(
                    configuration.get("UICulture"),
                    configuration.get("PreferredMetadataLanguage"),
                ),
            )
        except ProbeError:
            probe.note(
                "the server's interface culture needs an administrator, so the language the "
                "announced names are written in is a bound here rather than a measurement"
            )

        # AC-8, first hop: the address is relative to the master playlist's own directory.
        base = "/videos/" + dashed(source.item_id) + "/"
        followed = []
        for line in lines:
            status, headers, payload = server.get_streaming(base + _attribute(line, "URI"), 400)
            followed.append(status)
            probe.observe(
                "follow " + _attribute(line, "URI").split("?")[0],
                f"{status}, {headers.get('Content-Type')}, {payload[:40]!r}",
            )

        checks = [
            len(lines) == len(source.text),
            all(line.startswith(MEDIA_PREFIX) for line in lines),
            all("AUTOSELECT=YES" in line for line in lines),
            all(",LANGUAGE=" in line for line in lines),
            all("SegmentLength=30" in _attribute(line, "URI") for line in lines),
            all("ApiKey=" in _attribute(line, "URI") for line in lines),
            _variant_line(playlist).endswith('SUBTITLES="subs"'),
            all(status == 200 for status in followed),
        ]
        missing = [s for s in source.text if not s.get("Language")]
        if missing:
            names = [
                _attribute(line, "LANGUAGE")
                for line in lines
                if int(_attribute(line, "URI").split("/Subtitles/")[1].split("/")[0])
                == int(missing[0]["Index"])
            ]
            probe.observe("a stream with no language", f"LANGUAGE={names}")
            checks.append(names == ["Unknown"])
        else:
            probe.note(
                "every text track of this source states a language, so the manifest's literal "
                "Unknown fallback is read from the source rather than measured here"
            )
        return checks
    finally:
        if session:
            stop_encoding(server, session)


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_subtitle_manifest.py",
        question=(
            "What makes the master playlist announce a subtitle track, what does each "
            "announcement say, and where does the name come from?"
        ),
        document="specs/011-subtitle-delivery/spec.md",
        section="§3.4, OQ-1, OQ-3, OQ-4",
        expectation=None,
    )
    source = _pick(server)
    probe.observe(
        "source",
        f"item {source.item_id}, {len(source.text)} text and {len(source.image)} image "
        f"subtitle streams",
    )
    checks = _lever_battery(server, probe, source)
    checks.extend(_anatomy_battery(server, probe, source))

    if all(checks):
        probe.conclude(
            "the master playlist has exactly one lever, and it is not the profile flag: the "
            "route does not bind EnableSubtitlesInManifest at all, so the parameter the "
            "reference's own negotiation writes into the address changes nothing. What "
            "announces a track is SubtitleMethod=Hls in the address, which the negotiation "
            "writes only when a track was selected. One entry per *text* stream then appears, "
            "whatever the selection is - selecting an image track announces every text track "
            "with DEFAULT=NO on all of them - each carrying the stream's localised display "
            "title as its name, a hard-coded SegmentLength=30, and the caller's own token in "
            "the address",
            matches_documentation=None,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
