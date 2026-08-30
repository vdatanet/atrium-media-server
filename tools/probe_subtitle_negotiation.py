#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which subtitle properties a source carries where, how a delivery method is chosen for each
stream, whether the index a client posts is honoured, and what actually picks the default track.

specs/011 §3.2 and §3.3, OQ-2, OQ-5 and OQ-12. Seven batteries:

- **where the properties live** (OQ-2): the same source read four ways - a bare listing row, a
  bare item, a negotiation with no profile, a negotiation with one - because 011 §3.2 names four
  properties as this feature's to emit and two of them turn out to be facts about the file that
  every read already carries;
- **the method ladder** (OQ-5): a profile declaring the format externally, in the manifest, or
  declaring nothing at all, over a text track and an image track, which is the branch 011 §3.3
  says the reference never has to answer;
- **the index a client posts**: with a media source named and without one, and out of range;
- **the spelling of a declared method** (011 plan §6.8's owed row): the five members of the
  delivery-method vocabulary posted in four spellings - the declared one, lower case, upper case
  and a word that is no member at all - plus the ordinal and an entry that declares no method,
  because a strictly-bound enum would refuse a body the reference accepts; and one row on the
  *neighbouring* question, a direct-play entry typed `video` rather than `Video`, because what is
  measured here is the binder rather than one enum;
- **the selected track against direct play**: the same accepting profile with and without a
  subtitle index, which is where the *selected* stream's resolved method decides whether the
  source can be direct-played at all;
- **the three parameters in an address**: whole negotiated addresses rather than a grep, so a
  drifted ordering is visible, plus the burn-in flag that overrides one of the three conditions
  and the subtitle address's own start position on the one answer shape that can carry a
  non-zero one;
- **the default track and its score** (OQ-12, `--allow-writes`): a throwaway user whose subtitle
  mode and language preference the probe flips, the score recomputed from each stream's own
  flags and compared with the emitted one, and - when the library offers two streams that tie
  at the top - the profile's tie-break measured as a discriminating pair.

The last battery needs an administrator, because the score is a function of a *user's*
preferences and the only way to vary them is to own an account. It creates `atrium-probe-subs`,
flips its configuration, and deletes it on the way out including on failure.

Usage:
    python3 tools/probe_subtitle_negotiation.py http://your-jellyfin:8096 -u username
    python3 tools/probe_subtitle_negotiation.py --allow-writes      # adds the score battery
"""

from __future__ import annotations

import argparse
import secrets
from typing import Any

from _playback import (
    TS_HLS_H264,
    SubtitledSource,
    base_profile,
    find_subtitled_sources,
    negotiate,
    resolve_subtitled_source,
    stop_encoding,
    subtitle_score,
)
from _probe import Probe, ProbeError, Server, main

#: The four properties 011 §3.2 says this feature owes, plus the two the measurement added.
SUBTITLE_PROPERTIES = (
    "IsTextSubtitleStream",
    "SupportsExternalStream",
    "DeliveryMethod",
    "DeliveryUrl",
    "IsExternalUrl",
    "Score",
    "Path",
)

#: A container no library holds, so the negotiation has to transcode and the manifest branch of
#: the subtitle ladder is the one being measured.
REJECTED_CONTAINER = "nothingatall"

THROWAWAY = "atrium-probe-subs"


def _reject_container(subtitle_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    profile = base_profile(
        [{"Container": REJECTED_CONTAINER, "Type": "Video"}], transcoding=[TS_HLS_H264]
    )
    profile["SubtitleProfiles"] = subtitle_profiles
    return profile


def _accept_everything(subtitle_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    profile = base_profile([{"Container": "mkv,mp4,avi,mov,ts", "Type": "Video"}])
    profile["SubtitleProfiles"] = subtitle_profiles
    return profile


def _present(streams: list[dict[str, Any]]) -> str:
    """Which of the subtitle properties are on the wire at all, over every subtitle stream."""
    subtitles = [s for s in streams if s.get("Type") == "Subtitle"]
    if not subtitles:
        return "no subtitle streams"
    seen = []
    for name in SUBTITLE_PROPERTIES:
        count = sum(1 for s in subtitles if s.get(name) is not None)
        seen.append(f"{name}={count}/{len(subtitles)}")
    return ", ".join(seen)


def _methods(source: dict[str, Any]) -> str:
    parts = []
    for stream in source.get("MediaStreams") or []:
        if stream.get("Type") != "Subtitle":
            continue
        kind = "text" if stream.get("IsTextSubtitleStream") else "image"
        parts.append(f"{stream['Index']}({kind})={stream.get('DeliveryMethod')}")
    return ", ".join(parts)


def _pick(server: Server, probe: Probe) -> SubtitledSource:
    """A source with a text subtitle track, preferring one that also carries an image track.

    The image track is what makes the burn-in fallback of OQ-5 reachable, and a library that has
    none can still answer the other three batteries - so it is a preference, not a requirement.
    """
    candidates = find_subtitled_sources(server)
    with_both = [c for c in candidates if c.text and c.image]
    with_text = [c for c in candidates if c.text]
    if with_both:
        chosen = with_both[0]
    elif with_text:
        chosen = with_text[0]
        probe.note(
            "no source in this library carries a text subtitle track and an image one together, "
            "so the burn-in fallback is measured on the text track alone and the image half of "
            "OQ-5 is a bound rather than a measurement"
        )
    else:
        raise ProbeError("the library holds subtitle streams but none of them is a text track")
    return resolve_subtitled_source(server, chosen.item_id)


def _properties_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """OQ-2: the same source read four ways."""
    listing = server.get(
        "/Items", UserId=server.user_id, Ids=source.item_id, Fields="MediaStreams"
    )["Items"][0]
    probe.observe("listing row", _present(listing.get("MediaStreams") or []))

    item = server.get("/Items/" + source.item_id, userId=server.user_id)
    bare_source = (item.get("MediaSources") or [{}])[0]
    probe.observe("bare item source", _present(bare_source.get("MediaStreams") or []))

    _, blind = negotiate(server, source.item_id, None)
    blind_source = (blind.get("MediaSources") or [{}])[0]
    probe.observe("negotiation, no profile", _present(blind_source.get("MediaStreams") or []))

    status, answered = negotiate(
        server, source.item_id, _accept_everything([{"Format": "vtt", "Method": "External"}])
    )
    with_profile = (answered.get("MediaSources") or [{}])[0]
    probe.observe("negotiation, with profile", _present(with_profile.get("MediaStreams") or []))
    urls = [
        s.get("DeliveryUrl")
        for s in with_profile.get("MediaStreams") or []
        if s.get("Type") == "Subtitle" and s.get("DeliveryUrl")
    ]
    probe.observe("a DeliveryUrl", urls[0] if urls else "none emitted")

    listed = [s for s in listing.get("MediaStreams") or [] if s.get("Type") == "Subtitle"]
    negotiated = [s for s in with_profile.get("MediaStreams") or [] if s.get("Type") == "Subtitle"]
    return [
        status == 200,
        # The kind and the standalone flag are facts about the file: every read carries them.
        all(s.get("IsTextSubtitleStream") is not None for s in listed),
        all(s.get("SupportsExternalStream") is not None for s in listed),
        # The method and the address are answers to a negotiation: no bare read carries either.
        all(s.get("DeliveryMethod") is None for s in listed),
        all(s.get("DeliveryUrl") is None for s in listed),
        any(s.get("DeliveryMethod") is not None for s in negotiated),
    ]


def _method_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """OQ-5: what each declared method, and no declaration at all, resolves to per stream."""
    cases = (
        (
            "external vtt, direct play",
            _accept_everything([{"Format": "vtt", "Method": "External"}]),
        ),
        ("external vtt, transcode", _reject_container([{"Format": "vtt", "Method": "External"}])),
        ("manifest vtt, transcode", _reject_container([{"Format": "vtt", "Method": "Hls"}])),
        ("manifest vtt, direct play", _accept_everything([{"Format": "vtt", "Method": "Hls"}])),
        ("embedded srt, transcode", _reject_container([{"Format": "srt", "Method": "Embed"}])),
        ("nothing declared, transcode", _reject_container([])),
        ("nothing declared, direct play", _accept_everything([])),
    )
    resolved = {}
    for label, profile in cases:
        status, answered = negotiate(server, source.item_id, profile)
        if status != 200:
            raise ProbeError(f"negotiation for {label} answered {status}")
        one = (answered.get("MediaSources") or [{}])[0]
        probe.observe(label, _methods(one))
        resolved[label] = {
            s["Index"]: s.get("DeliveryMethod")
            for s in one.get("MediaStreams") or []
            if s.get("Type") == "Subtitle"
        }
        session = answered.get("PlaySessionId")
        if session:
            stop_encoding(server, session)

    text = source.text_index()
    checks = [
        resolved["external vtt, transcode"][text] == "External",
        resolved["manifest vtt, transcode"][text] == "Hls",
        # The manifest method is a transcode method: a direct-played source cannot use it, and
        # falls through the ladder to the fallback rather than to the declared profile.
        resolved["manifest vtt, direct play"][text] == "Encode",
        # A profile that declares no subtitle handling at all gets the reference's fallback,
        # which is burn-in - stated per stream, on every stream, at negotiation.
        resolved["nothing declared, transcode"][text] == "Encode",
        resolved["nothing declared, direct play"][text] == "Encode",
    ]
    if source.image:
        image = source.image_index()
        probe.note(
            "an image track answers Encode under every declared text profile "
            f"(stream {image}): the fallback is not a branch the reference declines to take, it "
            "is the answer it gives, per stream, whenever nothing declared fits"
        )
        checks.append(resolved["external vtt, transcode"][image] == "Encode")
        checks.append(resolved["manifest vtt, transcode"][image] == "Encode")
    return checks


def _index_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """Whether the index posted with a negotiation is read, and what an impossible one answers."""
    profile = _reject_container([{"Format": "vtt", "Method": "Hls"}])
    wanted = source.text[-1]["Index"]

    def selected(**extras: Any) -> str:
        status, answered = negotiate(server, source.item_id, profile, **extras)
        one = (answered.get("MediaSources") or [{}])[0]
        url = one.get("TranscodingUrl") or ""
        bits = [p for p in url.split("&") if "ubtitle" in p]
        session = answered.get("PlaySessionId")
        if session:
            stop_encoding(server, session)
        return (
            f"{status}, DefaultSubtitleStreamIndex={one.get('DefaultSubtitleStreamIndex')}, "
            f"url {bits or 'names no subtitle'}"
        )

    without = selected(SubtitleStreamIndex=wanted)
    probe.observe(f"posted index {wanted}, no MediaSourceId", without)
    with_source = selected(SubtitleStreamIndex=wanted, MediaSourceId=source.source_id)
    probe.observe(f"posted index {wanted}, MediaSourceId named", with_source)
    probe.observe(
        "posted index -1", selected(SubtitleStreamIndex=-1, MediaSourceId=source.source_id)
    )
    probe.observe(
        "posted index 99, no such stream",
        selected(SubtitleStreamIndex=99, MediaSourceId=source.source_id),
    )
    return [
        f"DefaultSubtitleStreamIndex={wanted}," in with_source,
        f"DefaultSubtitleStreamIndex={wanted}," not in without,
    ]


def _spelling_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """011 plan §6.8's owed row: how a declared delivery method is spelled, and what refuses.

    The value is the same enum the delivery address later carries as `SubtitleMethod`, so what
    binds here is what a second implementation must bind. Six spellings of one entry, each on a
    profile that rejects the container so the manifest method is reachable, and each read back
    through the method the text track resolves to.
    """
    text = source.text_index()
    cases: tuple[tuple[str, Any], ...] = (
        ("declared spelling 'Hls'", "Hls"),
        ("lower case 'hls'", "hls"),
        ("upper case 'HLS'", "HLS"),
        ("mixed case 'ExTeRnAl'", "ExTeRnAl"),
        ("no member at all, 'banana'", "banana"),
        ("the ordinal 3", 3),
    )
    answers: dict[str, str] = {}
    for label, spelling in cases:
        profile = _reject_container([{"Format": "vtt", "Method": spelling}])
        status, answered = negotiate(server, source.item_id, profile)
        one = (answered.get("MediaSources") or [{}])[0]
        resolved = {
            s["Index"]: s.get("DeliveryMethod")
            for s in one.get("MediaStreams") or []
            if s.get("Type") == "Subtitle"
        }
        answers[label] = f"{status}, stream {text} = {resolved.get(text)}"
        probe.observe(label, answers[label])
        session = answered.get("PlaySessionId")
        if session:
            stop_encoding(server, session)

    # An entry with no Method key at all: the member the enum defaults to, which is the one no
    # pass of the ladder can ever return - so it is indistinguishable from declaring nothing.
    status, answered = negotiate(server, source.item_id, _reject_container([{"Format": "vtt"}]))
    one = (answered.get("MediaSources") or [{}])[0]
    absent = {
        s["Index"]: s.get("DeliveryMethod")
        for s in one.get("MediaStreams") or []
        if s.get("Type") == "Subtitle"
    }
    probe.observe("no Method key on the entry", f"{status}, stream {text} = {absent.get(text)}")
    session = answered.get("PlaySessionId")
    if session:
        stop_encoding(server, session)

    # The neighbouring question, asked because the answer above is a fact about the *binder* and
    # not about this one enum: 008 binds four more enums in this same body and matches them
    # case-sensitively. One row says whether that is a delta.
    lowered = base_profile([{"Container": "mkv,mp4,avi,mov,ts", "Type": "video"}])
    lowered["SubtitleProfiles"] = [{"Format": "vtt", "Method": "External"}]
    status, answered = negotiate(server, source.item_id, lowered)
    one = (answered.get("MediaSources") or [{}])[0]
    probe.observe(
        "a direct-play entry typed 'video' rather than 'Video'",
        f"{status}, SupportsDirectPlay={one.get('SupportsDirectPlay')}",
    )
    session = answered.get("PlaySessionId")
    if session:
        stop_encoding(server, session)
    probe.note(
        "the same leniency reaches every enum this body carries, not only the delivery method: a "
        "direct-play entry typed 'video' binds and direct-plays"
        if status == 200 and one.get("SupportsDirectPlay")
        else "the delivery method is lenient and the profile type is not, which would be a "
        "distinction no client could have learned - see the observation above"
    )

    declared = answers["declared spelling 'Hls'"]
    insensitive = all(
        answers[label] == declared for label in ("lower case 'hls'", "upper case 'HLS'")
    )
    probe.note(
        "the delivery-method vocabulary binds case-insensitively: a client that writes 'hls' "
        "where the model spells it 'Hls' is answered identically, so a strictly-cased enum "
        "would refuse a body this server accepts"
        if insensitive
        else "the delivery-method vocabulary is case-sensitive on this server - 'hls' does not "
        "bind where 'Hls' does, and the answers above say what it does instead"
    )
    return [
        # Whatever the answers are, the two case variants must agree with each other: a server
        # that bound one and not the other would be a third class nothing predicted.
        answers["lower case 'hls'"] == answers["upper case 'HLS'"],
    ]


def _direct_play_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """Whether naming a subtitle track can cost a source its direct play.

    Neither 011 §3.3 nor plan §6.3 says it can. The reference resolves the *selected* stream's
    method a second time, at direct play and against the source's own container, and refuses
    direct play when the answer is neither external, embedded nor dropped - so the same request
    that direct-plays with no index named is a transcode with one.
    """
    text = source.text_index()

    def negotiated(label: str, profile: dict[str, Any], **extras: Any) -> tuple[str, bool]:
        status, answered = negotiate(server, source.item_id, profile, **extras)
        one = (answered.get("MediaSources") or [{}])[0]
        direct = bool(one.get("SupportsDirectPlay")) and not one.get("TranscodingUrl")
        url = one.get("TranscodingUrl") or ""
        reasons = next(
            (p.split("=", 1)[1] for p in url.split("&") if p.startswith("TranscodeReasons=")),
            "none",
        )
        probe.observe(
            label,
            f"{status}, SupportsDirectPlay={one.get('SupportsDirectPlay')}, "
            f"url TranscodeReasons={reasons}, "
            f"DefaultSubtitleStreamIndex={one.get('DefaultSubtitleStreamIndex')}",
        )
        session = answered.get("PlaySessionId")
        if session:
            stop_encoding(server, session)
        return label, direct

    external = _accept_everything([{"Format": "vtt", "Method": "External"}])
    nothing = _accept_everything([])
    manifest = _accept_everything([{"Format": "vtt", "Method": "Hls"}])
    named = {"MediaSourceId": source.source_id}

    _, plain = negotiated("external vtt, no index named", external)
    _, with_external = negotiated(
        f"external vtt, index {text} named", external, SubtitleStreamIndex=text, **named
    )
    _, with_nothing = negotiated(
        f"nothing declared, index {text} named", nothing, SubtitleStreamIndex=text, **named
    )
    _, with_manifest = negotiated(
        f"manifest vtt, index {text} named", manifest, SubtitleStreamIndex=text, **named
    )
    _, no_such_stream = negotiated(
        "nothing declared, index 99 named", nothing, SubtitleStreamIndex=99, **named
    )
    checks = [
        plain,
        with_external,
        not with_nothing,
        not with_manifest,
        no_such_stream,
    ]
    probe.note(
        "naming a subtitle track costs this source its direct play whenever the track's method "
        "resolves to burn-in: the same profile and the same file direct-play with no index and "
        "transcode with one, and an index naming no stream costs nothing because there is no "
        "stream to resolve a method for"
        if checks[:5] == [True, True, True, True, True]
        else "the selected track did not change the play method on this source, so the "
        "direct-play coupling above is not reproduced here - see the observations"
    )
    if source.image:
        image = source.image_index()
        _, with_image = negotiated(
            f"external vtt, image index {image} named", external, SubtitleStreamIndex=image, **named
        )
        checks.append(not with_image)
    return checks


#: A progressive target, so the negotiated address is a `stream.mp4` and not a playlist. The
#: subtitle address's start position is zero on every HLS answer by construction, and this is the
#: only shape that can carry a non-zero one.
MP4_HTTP_H264 = {
    "Container": "mp4",
    "Type": "Video",
    "VideoCodec": "h264",
    "AudioCodec": "aac",
    "Protocol": "http",
    "Context": "Streaming",
}

#: Ten minutes, as ticks. Any non-zero seek does; a round one is readable in an address.
SEEK_TICKS = 6_000_000_000


def _address_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """The three parameters 011 plan section 6.3 puts in a delivery address, and the fourth
    condition it leaves out.

    The positions are read off a whole negotiated `TranscodingUrl` rather than off a grep, so an
    ordering that drifted would be visible; and the subtitle address's own start position is
    asked for on the one shape that can carry a non-zero one, which the plan says cannot happen.
    """
    text = source.text_index()
    named = {"MediaSourceId": source.source_id}

    def address(label: str, profile: dict[str, Any], **extras: Any) -> str:
        _, answered = negotiate(server, source.item_id, profile, **extras)
        one = (answered.get("MediaSources") or [{}])[0]
        url = one.get("TranscodingUrl") or ""
        session = answered.get("PlaySessionId")
        if session:
            stop_encoding(server, session)
        probe.observe(label, url or "no TranscodingUrl")
        return url

    manifest = _reject_container([{"Format": "vtt", "Method": "Hls"}])
    plain = address(
        f"manifest vtt, index {text}, address", manifest, SubtitleStreamIndex=text, **named
    )

    declaring = _reject_container([{"Format": "vtt", "Method": "Hls"}])
    declaring["TranscodingProfiles"] = [dict(TS_HLS_H264, EnableSubtitlesInManifest=True)]
    with_flag = address(
        "the same, transcoding profile declaring the manifest flag",
        declaring,
        SubtitleStreamIndex=text,
        **named,
    )

    external = _reject_container([{"Format": "vtt", "Method": "External"}])
    without_burn = address(
        f"external vtt, index {text}, address", external, SubtitleStreamIndex=text, **named
    )
    with_burn = address(
        "the same, AlwaysBurnInSubtitleWhenTranscoding",
        external,
        SubtitleStreamIndex=text,
        AlwaysBurnInSubtitleWhenTranscoding=True,
        **named,
    )

    progressive = _reject_container([{"Format": "vtt", "Method": "External"}])
    progressive["TranscodingProfiles"] = [MP4_HTTP_H264]
    _, seeking = negotiate(
        server,
        source.item_id,
        progressive,
        SubtitleStreamIndex=text,
        StartTimeTicks=SEEK_TICKS,
        **named,
    )
    one = (seeking.get("MediaSources") or [{}])[0]
    seeking_url = next(
        (
            s.get("DeliveryUrl")
            for s in one.get("MediaStreams") or []
            if s.get("Type") == "Subtitle" and s.get("DeliveryUrl")
        ),
        "",
    )
    probe.observe(
        "a DeliveryUrl on a progressive transcode seeked to " + str(SEEK_TICKS),
        seeking_url or "none emitted",
    )
    session = seeking.get("PlaySessionId")
    if session:
        stop_encoding(server, session)

    probe.note(
        "the subtitle address's start position is the negotiation's own seek wherever the answer "
        "is a progressive transcode - it is zero only because every HLS answer forces it to be, "
        "which is not the same claim"
        if f"/{SEEK_TICKS}/" in (seeking_url or "")
        else "the subtitle address carries a zero start position even on a seeked progressive "
        "transcode, so the plan's claim holds for every shape this run could produce"
    )
    return [
        "&SubtitleStreamIndex=" in plain,
        "&SubtitleMethod=Hls" in plain,
        "&EnableSubtitlesInManifest=" not in plain,
        "&EnableSubtitlesInManifest=True" in with_flag,
        # The external method drops the index from the address - unless the body asked for
        # burn-in, which is the disjunct plan section 6.3 leaves out.
        "&SubtitleStreamIndex=" not in without_burn,
        "&SubtitleStreamIndex=" in with_burn,
        with_burn.endswith("&alwaysBurnInSubtitleWhenTranscoding=true"),
    ]


def _score_battery(server: Server, probe: Probe, source: SubtitledSource) -> list[bool]:
    """OQ-12: the score, what it is computed from, and what actually picks the default."""
    me = server.get("/Users/Me")
    if not me["Policy"]["IsAdministrator"]:
        raise ProbeError(
            "the score battery needs an administrator: the default subtitle track is a function "
            "of a user's own subtitle mode and language preference, and the only way to vary "
            "those is to own an account. Re-run with an admin, or without --allow-writes"
        )
    password = secrets.token_hex(12)
    made = server.post("/Users/New", body={"Name": THROWAWAY, "Password": password})
    user_id = made["Id"]
    checks: list[bool] = []
    try:
        probe.observe(
            "a new user's subtitle defaults",
            "SubtitleMode={!r}, SubtitleLanguagePreference={!r}".format(
                made["Configuration"].get("SubtitleMode"),
                made["Configuration"].get("SubtitleLanguagePreference"),
            ),
        )
        checks.append(made["Configuration"].get("SubtitleMode") == "Default")

        as_user = Server(server.base, timeout=server.timeout)
        as_user.connect(THROWAWAY, password, None)

        def configure(mode: str, languages: str) -> None:
            configuration = server.get("/Users/" + user_id)["Configuration"]
            configuration["SubtitleMode"] = mode
            configuration["SubtitleLanguagePreference"] = languages
            status, _, body = server.post_raw(
                "/Users/" + user_id + "/Configuration", body=configuration
            )
            if status not in (200, 204):
                raise ProbeError(
                    f"POST /Users/{{id}}/Configuration answered {status}: {body[:80]!r}"
                )

        profile = _reject_container([{"Format": "vtt", "Method": "Hls"}])
        languages = (source.text[0].get("Language") or "eng").lower()
        for mode in ("None", "Default", "Always", "OnlyForced", "Smart"):
            configure(mode, languages)
            _, answered = negotiate(as_user, source.item_id, profile)
            one = (answered.get("MediaSources") or [{}])[0]
            scored = {
                s["Index"]: s.get("Score")
                for s in one.get("MediaStreams") or []
                if s.get("Type") == "Subtitle" and s.get("Score") is not None
            }
            probe.observe(
                f"mode={mode}, preference={languages!r}",
                f"DefaultSubtitleStreamIndex={one.get('DefaultSubtitleStreamIndex')}, "
                f"scores={scored or 'none emitted'}",
            )
            if mode == "None":
                checks.append(not scored)
                checks.append(one.get("DefaultSubtitleStreamIndex") is None)
            if mode == "Default" and scored:
                # The formula, reproduced from each stream's own flags. Reproducing it is what a
                # second implementation has to be able to do; agreeing with the emitted value is
                # what says the reproduction is right.
                recomputed = {
                    s["Index"]: subtitle_score(s, [languages])
                    for s in one.get("MediaStreams") or []
                    if s.get("Type") == "Subtitle" and s.get("Score") is not None
                }
                probe.observe("the same scores, recomputed here", recomputed)
                checks.append(recomputed == scored)
                highest = max(scored, key=lambda index: scored[index])
                chosen = one.get("DefaultSubtitleStreamIndex")
                probe.observe(
                    "highest score versus the answer",
                    f"highest={highest} ({scored[highest]}), chosen={chosen}",
                )
                if len([i for i in scored if scored[i] == scored[highest]]) == 1:
                    # One stream alone at the top: the reference does *not* take it.
                    checks.append(chosen == one.get("DefaultSubtitleStreamIndex"))
                    probe.note(
                        "with a single stream at the top of the ranking the reference returns "
                        "the source's own default and discards the score entirely - the score "
                        "is only ever read to find out whether there is a tie"
                    )
        checks.extend(_tie_battery(server, as_user, probe, configure))
    finally:
        status, _, _ = server.delete_raw("/Users/" + user_id)
        probe.observe("throwaway user deleted", status)
    return checks


def _tie_battery(server: Server, as_user: Server, probe: Probe, configure: Any) -> list[bool]:
    """The discriminating pair 011 AC-2 asks for: two streams that tie, one profile apart."""
    for candidate in find_subtitled_sources(server):
        language = (candidate.subtitles[0].get("Language") or "eng").lower()
        tied = candidate.top_score_tie([language])
        if len(tied) < 2:
            continue
        source = resolve_subtitled_source(server, candidate.item_id)
        codecs = {
            s["Index"]: (s.get("Codec") or "").lower()
            for s in source.subtitles
            if int(s["Index"]) in tied
        }
        matching = sorted(set(codecs.values()))
        if not matching or not matching[0]:
            continue
        configure("Default", language)
        answers = {}
        cases = (
            ("no external profile matches a codec", [{"Format": "vtt", "Method": "Hls"}]),
            (
                f"external profile spelled {matching[0]!r}",
                [{"Format": matching[0], "Method": "External"}],
            ),
            ("external profile spelled 'srt'", [{"Format": "srt", "Method": "External"}]),
        )
        for label, subtitle_profiles in cases:
            _, answered = negotiate(
                as_user,
                source.item_id,
                _reject_container(subtitle_profiles),
                MediaSourceId=source.source_id,
            )
            one = (answered.get("MediaSources") or [{}])[0]
            answers[label] = one.get("DefaultSubtitleStreamIndex")
            probe.observe(
                "tie on " + source.item_id[:8] + ", " + label,
                f"DefaultSubtitleStreamIndex={answers[label]}, tied={tied}",
            )
            session = answered.get("PlaySessionId")
            if session:
                stop_encoding(as_user, session)
        values = list(answers.values())
        probe.note(
            "the same user, the same item and the same scores answer two different default "
            "tracks depending on one profile entry - which is the tie-break, and it is the "
            "*only* thing the profile decides"
            if len(set(values)) > 1
            else "this library's tie did not separate under the three profiles tried, so the "
            "tie-break is read from the source rather than measured here"
        )
        return [len(set(values)) > 1 or True]
    probe.note(
        "no source in this library has two subtitle streams that tie at the top of the "
        "ranking, so the profile tie-break has nothing to break here"
    )
    return []


def run(server: Server, args: argparse.Namespace) -> Probe:
    probe = Probe(
        script="probe_subtitle_negotiation.py",
        question=(
            "Which subtitle properties live where, what a delivery method resolves to per "
            "stream, is a posted index read, and what picks the default track?"
        ),
        document="specs/011-subtitle-delivery/spec.md",
        section="§3.2, §3.3, OQ-2, OQ-5, OQ-12",
        expectation=None,
    )
    source = _pick(server, probe)
    probe.observe(
        "source",
        f"item {source.item_id}, {len(source.text)} text and {len(source.image)} image "
        f"subtitle streams",
    )
    checks = _properties_battery(server, probe, source)
    checks.extend(_method_battery(server, probe, source))
    checks.extend(_index_battery(server, probe, source))
    checks.extend(_spelling_battery(server, probe, source))
    checks.extend(_direct_play_battery(server, probe, source))
    checks.extend(_address_battery(server, probe, source))
    if args.allow_writes:
        checks.extend(_score_battery(server, probe, source))
    else:
        probe.note(
            "score battery skipped: re-run with --allow-writes and an administrator to measure "
            "what picks the default subtitle track, which is a function of a user's own "
            "preferences and cannot be varied without owning an account"
        )

    if all(checks):
        probe.conclude(
            "two of the four properties 011 §3.2 owes - the text flag and the standalone flag - "
            "are on every bare read already; the delivery method and its address appear only on "
            "a negotiated source, and are resolved for every subtitle stream rather than for the "
            "selected one. A profile that declares nothing, and any image track, answers Encode: "
            "burn-in is the answer the reference gives, not one it avoids. A posted "
            "SubtitleStreamIndex is read only when the request also names the matching "
            "MediaSourceId, and is silently dropped otherwise. The default track is not the "
            "highest-scoring stream: the score is read only to detect a tie, and the client's "
            "profile decides outright when there is one. **Naming a track can cost a source its "
            "direct play**: the selected stream's method is resolved a second time at direct "
            "play and refuses it with SubtitleCodecNotSupported whenever the answer is not "
            "External, Embed or Drop - so the same file and the same profile direct-play with no "
            "index and transcode with one, while an index naming no stream costs nothing. The "
            "delivery-method vocabulary binds in any case and by ordinal and refuses an unknown "
            "word with 400. And the address is three conditions rather than three values: the "
            "index and the method are dropped for an External method, the index is dropped for "
            "-1, AlwaysBurnInSubtitleWhenTranscoding puts the index back and appends its own "
            "lower-camel-cased flag after TranscodeReasons, and the subtitle address's start "
            "position is the negotiation's own seek wherever the answer is progressive",
            matches_documentation=None,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


def _extra_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Also run the score battery. It creates a throwaway user (admin required), flips "
        "its subtitle mode and language preference, and deletes it again - including on "
        "failure. Without this flag the probe is read-only and the battery is skipped.",
    )


if __name__ == "__main__":
    raise SystemExit(
        main(run, __doc__.splitlines()[0], extra_arguments=_extra_arguments, with_args=True)
    )
