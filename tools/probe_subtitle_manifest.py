#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What makes the HLS master playlist announce a subtitle track, what each announcement says
verbatim, and where the name it carries comes from.

specs/011 §3.4, OQ-1, OQ-3 and OQ-4. Five batteries:

- **the lever** (OQ-1): the same master playlist fetched with nothing added, with
  `EnableSubtitlesInManifest=true`, and with each `SubtitleMethod` beside a stream index -
  including an image stream's index, and including the parameter the reference's *own*
  negotiation writes into the address it hands the client;
- **the vocabulary** (011 plan §6.8, owed to T11): the same word in five more spellings -
  altered case, the member's ordinal, an ordinal that is no member, a word that is no member,
  and an empty value - plus the same address with **no index at all**, because the index turned
  out not to be part of the lever;
- **the anatomy** (OQ-3): the `#EXT-X-MEDIA` lines and **every** `#EXT-X-STREAM-INF` line
  verbatim, because a manifest is compared as text by nothing in this repository and as bytes by
  010's differential;
- **the multi-variant case** (011 tasks gate, 2026-08-30): an HDR source whose video is copied is
  offered SDR entrances beside the copy, and the group belongs to every one of them. The gate
  could not see this, because this script's own `_variant_line` returned the **first**
  `#EXT-X-STREAM-INF` and only that one; it is `_variant_lines` now, and the battery reports a
  miss on a library that holds no HDR source with a text subtitle track;
- **the name** (OQ-4): what each announcement is called, beside every property that name is
  built from - the stream's title, its language, its flags, its codec - and beside the server's
  own interface culture, which is what decides the language the name is written in.

The traversal of 011 AC-8 starts here: every announced address is resolved against the master
playlist's own base and fetched, because an announcement that leads nowhere is the failure this
feature exists to prevent.

It makes the reference open a play session per negotiation and stops each one on the way out,
including on failure. It never fetches a segment. **The two batteries added at T11 build the
master address by hand and negotiate nothing**, which is what lets the question they answer -
which spellings of one query value announce a track - be asked without opening a session at all.

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

#: The group every announcement is put in and every variant line names.
GROUP = "subs"

#: The exact opening of an announcement, which is half of what OQ-3 asks.
MEDIA_PREFIX = f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="{GROUP}",NAME="'

#: What a hand-built master address states about the output, so that the two batteries which
#: negotiate nothing still describe a stream the route can plan. `VideoCodec` is the one that
#: moves: `copy` is what puts an SDR entrance beside an HDR source.
HAND_BUILT = "&AudioCodec=aac&SegmentContainer=ts&MinSegments=1"

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


def _variant_lines(playlist: str) -> list[str]:
    """**Every** `#EXT-X-STREAM-INF`, which is what this was missing when the gate read it.

    It returned the first one and only the first one, so a master carrying an SDR entrance beside
    an HDR stream copy looked like a master carrying one variant - and the question *does every
    variant carry the subtitle group* could not be asked, let alone answered.
    """
    return [line for line in playlist.splitlines() if line.startswith("#EXT-X-STREAM-INF")]


def _every_variant_names_the_group(playlist: str) -> bool:
    lines = _variant_lines(playlist)
    return bool(lines) and all(line.endswith(f'SUBTITLES="{GROUP}"') for line in lines)


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
            variants = _variant_lines(playlist)
            named = sum(1 for line in variants if f'SUBTITLES="{GROUP}"' in line)
            probe.observe(
                label,
                f"{len(lines)} media entries, {named} of {len(variants)} variants name the group",
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


def _master_address(source: SubtitledSource, video_codec: str = "h264") -> str:
    """A master playlist address built by hand, which negotiates nothing and opens no session.

    `mediaSourceId` is declared **required** on this route, so an address without it is problem
    details naming it rather than the broken announcement 011 plan §6.5 predicted - measured in
    the same run as the vocabulary below.
    """
    return (
        f"/videos/{dashed(source.item_id)}/master.m3u8"
        f"?MediaSourceId={source.source_id}&VideoCodec={video_codec}{HAND_BUILT}"
    )


def _vocabulary_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """011 plan §6.8's owed row: `SubtitleMethod=hls` as a **query** parameter.

    T9 measured the same word on a request body and found four classes - altered case binds, the
    ordinal binds, an absent key takes the default, a word that is no member is a `400`. Three of
    those four carry across and the fourth does not, which is why the row was owed rather than
    inferred: here a word that is no member is a `200` announcing nothing.

    **And a comma-separated value is one value whose parts are OR-ed**, which the last four cases
    below discriminate rather than assume: `Embed,External` is `1 | 2`, the manifest method's own
    ordinal, so it announces where `External,External` does not - and a server reading only the
    first name would answer the opposite on both.

    The address is built by hand, so this battery costs the server one master playlist per case
    and opens no play session.
    """
    text = source.text_index()
    base = _master_address(source)
    cases = [
        ("Hls", f"&SubtitleStreamIndex={text}&SubtitleMethod=Hls"),
        ("hls", f"&SubtitleStreamIndex={text}&SubtitleMethod=hls"),
        ("HLS", f"&SubtitleStreamIndex={text}&SubtitleMethod=HLS"),
        ("hLs", f"&SubtitleStreamIndex={text}&SubtitleMethod=hLs"),
        ("the ordinal 3", f"&SubtitleStreamIndex={text}&SubtitleMethod=3"),
        ("the ordinal 9, no member", f"&SubtitleStreamIndex={text}&SubtitleMethod=9"),
        ("banana, no member", f"&SubtitleStreamIndex={text}&SubtitleMethod=banana"),
        ("an empty value", f"&SubtitleStreamIndex={text}&SubtitleMethod="),
        ("Hls with no index at all", "&SubtitleMethod=Hls"),
        ("Hls with the index -1", "&SubtitleStreamIndex=-1&SubtitleMethod=Hls"),
        ("Hls with an index naming nothing", "&SubtitleStreamIndex=999&SubtitleMethod=Hls"),
        ("an index that is not a number", "&SubtitleStreamIndex=banana&SubtitleMethod=Hls"),
        (
            "Embed,External, which is 1|2",
            f"&SubtitleStreamIndex={text}&SubtitleMethod=Embed%2CExternal",
        ),
        ("1,2", f"&SubtitleStreamIndex={text}&SubtitleMethod=1%2C2"),
        (
            "External,External, which is 2",
            f"&SubtitleStreamIndex={text}&SubtitleMethod=External%2CExternal",
        ),
        (
            "Hls,banana, one part unreadable",
            f"&SubtitleStreamIndex={text}&SubtitleMethod=Hls%2Cbanana",
        ),
    ]
    answers = {}
    for label, extra in cases:
        status, _, payload = server.get_streaming(base + extra, 8000)
        body = payload.decode("utf-8", "replace")
        answers[label] = (status, _media_lines(body))
        defaults = [_attribute(line, "DEFAULT") for line in answers[label][1]]
        probe.observe(
            "method " + label,
            f"{status}, {len(answers[label][1])} media entries, DEFAULT={defaults or '-'}",
        )

    status, _, payload = server.get_streaming(
        f"/videos/{dashed(source.item_id)}/master.m3u8?VideoCodec=h264{HAND_BUILT}"
        f"&SubtitleMethod=Hls",
        300,
    )
    probe.observe("no MediaSourceId at all", f"{status}, {payload[:90]!r}")

    announced = len(source.text)
    return [
        # The three classes that bind, each answering exactly what the declared spelling answers.
        answers["Hls"][0] == 200 and len(answers["Hls"][1]) == announced,
        answers["hls"][1] == answers["Hls"][1],
        answers["HLS"][1] == answers["Hls"][1],
        answers["hLs"][1] == answers["Hls"][1],
        answers["the ordinal 3"][1] == answers["Hls"][1],
        # The two that do not, and neither of them refuses: this is the half of T9's answer that
        # does not carry across from a request body.
        answers["the ordinal 9, no member"] == (200, []),
        answers["banana, no member"] == (200, []),
        answers["an empty value"] == (200, []),
        # The index is not part of the lever. It decides `DEFAULT` and nothing else.
        len(answers["Hls with no index at all"][1]) == announced,
        len(answers["Hls with the index -1"][1]) == announced,
        len(answers["Hls with an index naming nothing"][1]) == announced,
        all(
            _attribute(line, "DEFAULT") == "NO"
            for label in (
                "Hls with no index at all",
                "Hls with the index -1",
                "Hls with an index naming nothing",
            )
            for line in answers[label][1]
        ),
        # An index that will not bind is the framework's refusal, where a method that will not
        # bind is not - the asymmetry an implementation has to reproduce.
        answers["an index that is not a number"][0] == 400,
        status == 400,
        # The comma list, on both sides of the discrimination.
        answers["Embed,External, which is 1|2"][1] == answers["Hls"][1],
        answers["1,2"][1] == answers["Hls"][1],
        answers["External,External, which is 2"] == (200, []),
        answers["Hls,banana, one part unreadable"] == (200, []),
    ]


def _hdr_with_text(server: Server) -> SubtitledSource | None:
    """A source that is high dynamic range **and** carries a text subtitle track, or None.

    Both halves are needed and neither is common: an HDR source with no text track cannot show
    the group on its entrances, and a subtitled SDR source has no entrances.
    """
    for candidate in find_subtitled_sources(server):
        if not candidate.text:
            continue
        video = [s for s in candidate.source.get("MediaStreams", []) if s.get("Type") == "Video"]
        if video and (video[0].get("VideoRange") or "").upper() == "HDR":
            return resolve_subtitled_source(server, candidate.item_id)
    return None


def _multi_variant_battery(server: Server, probe: Probe) -> list[bool]:
    """The group on **every** variant line, which needs a master that has more than one.

    An HDR source whose video is stream-copied is offered SDR entrances beside the copy, and the
    reference hands its subtitle group to every playlist line it appends `[source:
    Jellyfin.Api/Helpers/DynamicHlsHelper.cs:213-315, 325-345 @ v10.11.11]`. Written as one line,
    the entrance - which exists precisely so that a client unable to render the copy has somewhere
    to go - would be the one variant offering no subtitles.

    Reports a **miss** rather than inferring anything when the library holds no such source: the
    question is then unanswered, not answered in the negative.
    """
    source = _hdr_with_text(server)
    if source is None:
        probe.note(
            "no source in this library is high dynamic range *and* carries a text subtitle "
            "track, so whether every variant of a multi-variant master names the subtitle group "
            "is unmeasured on this run - it needs both halves at once, and neither is common"
        )
        return []
    address = _master_address(source, video_codec="copy")
    address += f"&SubtitleStreamIndex={source.text_index()}&SubtitleMethod=Hls"
    status, _, payload = server.get_streaming(address, 8000)
    playlist = payload.decode("utf-8", "replace")
    variants = _variant_lines(playlist)
    named = sum(1 for line in variants if 'SUBTITLES="' + GROUP + '"' in line)
    probe.observe(
        "an HDR source, video copied",
        f"item {source.item_id}, {status}, {len(variants)} variants, "
        f"{named} of them naming the group",
    )
    for line in variants:
        probe.observe("variant line", line)
    return [
        status == 200,
        len(variants) > 1,
        _every_variant_names_the_group(playlist),
    ]


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
        for line in _variant_lines(playlist):
            probe.observe("variant line", line)

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
            _every_variant_names_the_group(playlist),
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
    checks.extend(_vocabulary_battery(server, probe, source))
    checks.extend(_anatomy_battery(server, probe, source))
    checks.extend(_multi_variant_battery(server, probe))

    if all(checks):
        probe.conclude(
            "the master playlist has exactly one lever, and it is neither the profile flag nor "
            "the stream index: the route does not bind EnableSubtitlesInManifest at all, so the "
            "parameter the reference's own negotiation writes into the address changes nothing, "
            "and SubtitleMethod=Hls announces every text track of the source on its own - with "
            "no index, with -1, and with an index naming no stream alike. The index decides "
            "which entry carries DEFAULT=YES and nothing else, which is why selecting an image "
            "track announces every text track with DEFAULT=NO on all of them. The word binds in "
            "any case and by ordinal, and a word that is no member is a 200 announcing nothing "
            "rather than the 400 the same word answers on a request body. Every entry carries "
            "the stream's localised display title as its name, a hard-coded SegmentLength=30 and "
            "the caller's own token; every variant line of the master ends in the group, the SDR "
            "entrances beside an HDR stream copy included",
            matches_documentation=None,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], needs_writes=True))
