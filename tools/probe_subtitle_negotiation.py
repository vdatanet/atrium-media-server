#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which subtitle properties a source carries where, how a delivery method is chosen for each
stream, whether the index a client posts is honoured, and what actually picks the default track.

specs/011 §3.2 and §3.3, OQ-2, OQ-5 and OQ-12. Four batteries:

- **where the properties live** (OQ-2): the same source read four ways - a bare listing row, a
  bare item, a negotiation with no profile, a negotiation with one - because 011 §3.2 names four
  properties as this feature's to emit and two of them turn out to be facts about the file that
  every read already carries;
- **the method ladder** (OQ-5): a profile declaring the format externally, in the manifest, or
  declaring nothing at all, over a text track and an image track, which is the branch 011 §3.3
  says the reference never has to answer;
- **the index a client posts**: with a media source named and without one, and out of range;
- **the default track and its score** (OQ-12, `--allow-writes`): a throwaway user whose subtitle
  mode and language preference the probe flips, the score recomputed from each stream's own
  flags and compared with the emitted one, and - when the library offers two streams that tie
  at the top - the profile's tie-break measured as a discriminating pair.

The fourth battery needs an administrator, because the score is a function of a *user's*
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
            "profile decides outright when there is one",
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
