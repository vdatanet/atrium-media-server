#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the two subtitle addresses answer: to a caller with no credential, to a window, to a
format the server cannot make, and to every way of naming a stream that is not there.

specs/011 §3.5 and §3.7, OQ-6, OQ-8 and OQ-11. Seven batteries:

- **the credential** (OQ-6): both routes with no token, with an unknown token, with the token in
  the header and with it in the query string. The reference declares a requirement on one route
  and none on the other, and 008 T6 found the declared and the measured answers differ on
  exactly this class;
- **the playlist**: its whole text, the addresses it names, and what each entry answers when it
  is followed as written - which is 011 AC-8's traversal and the reason the fetch route is in
  this feature at all;
- **the window** (OQ-11): the two timestamp switches the playlist's own entries set, measured as
  the difference they make to the cues and to the first bytes of the body;
- **the boundary** (AC-10): whether a cue that starts *exactly* where one window ends and the next
  begins is answered by both of them. T5 read that off the reference's own selection - both ends
  inclusive, and consecutive windows handed the same position - and a reading is not a
  measurement, so this battery asks the server. It reports which form it reached: the boundary
  can always be constructed from a cue's own start, and whether the reference's *own* grid ever
  lands on one depends on the library, so the run says which of the two it proved;
- **the formats**: every spelling a client can put in the address, including one the server
  cannot produce and one that turns the cue list into JSON;
- **the extracted artefact**: what an embedded `ass` track answers when the format asked for is
  the one it is already in - which is the extraction itself, handed back by the same-format short
  circuit. It is the only way from outside to see what the reference's extraction wrote, and it
  carries the thing no format specification predicts: the font substitution the reference performs
  on a `.ass` after extracting it, and the byte order mark that arrives with it and only with it;
- **the refusals** (OQ-8): each row of 011 §3.7 on each route, as bytes rather than as a status.

Read-only by default. `--allow-writes` adds the one case that makes the reference work: asking
for an *image* subtitle track as text, which it attempts with ffmpeg for some tens of seconds
before refusing.

Usage:
    python3 tools/probe_subtitle_delivery.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import argparse
from typing import Any

from _playback import (
    SubtitledSource,
    dashed,
    find_subtitled_sources,
    resolve_subtitled_source,
)
from _probe import Probe, ProbeError, Server, main

#: An identifier no library holds, and deliberately not all zeros: the all-zero form is the
#: reference's `Guid.Empty`, which a guard refuses before any lookup, so it measures the guard
#: rather than the miss (008 T5's finding, reused here).
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"
EMPTY_GUID = "00000000000000000000000000000000"
UNKNOWN_TOKEN = "0123456789abcdef0123456789abcdef"  # noqa: S105 - a probe input, not a credential

#: The formats a client can name in the address. `js` is the reference's own alias for `json`.
FORMATS = ("vtt", "srt", "ass", "ssa", "json", "js", "sub", "xyz")

TICKS_PER_SECOND = 10_000_000


def _shape(status: int, headers: dict[str, str], body: bytes) -> str:
    kind = headers.get("Content-Type") or "no Content-Type"
    length = headers.get("Content-Length") or "no Content-Length"
    ranges = headers.get("Accept-Ranges") or "no Accept-Ranges"
    return f"{status}, {kind}, {length}, {ranges}: {body[:110]!r}"


def _pick(server: Server) -> SubtitledSource:
    """A source with a text subtitle track and a runtime, preferring one that has an image one.

    The runtime is not optional: the playlist route lays windows across it and refuses a source
    that has none, which is a row of §3.7 rather than a probe input.
    """
    candidates = [c for c in find_subtitled_sources(server) if c.text]
    if not candidates:
        raise ProbeError("the library holds no source with a text subtitle stream")
    candidates.sort(key=lambda c: (1 if c.image else 0, len(c.text)), reverse=True)
    for candidate in candidates:
        source = resolve_subtitled_source(server, candidate.item_id)
        if source.runtime_ticks > 0 and source.text:
            return source
    raise ProbeError("no source with a text subtitle stream states a runtime")


class Address:
    """The two addresses of one subtitle track, built the way the reference writes them."""

    def __init__(self, item_id: str, source_id: str, index: Any) -> None:
        self.base = f"/Videos/{dashed(item_id)}/{source_id}/Subtitles/{index}"

    @classmethod
    def of(cls, source: SubtitledSource, index: Any) -> Address:
        return cls(source.item_id, source.source_id, index)

    def playlist(self, segment_length: Any = 30) -> str:
        if segment_length is None:
            return self.base + "/subtitles.m3u8"
        return self.base + "/subtitles.m3u8?SegmentLength=" + str(segment_length)

    def whole(self, fmt: str = "vtt") -> str:
        return self.base + "/Stream." + fmt

    def window(self, start: int, end: int, switches: str = "") -> str:
        return f"{self.base}/stream.vtt?StartPositionTicks={start}&EndPositionTicks={end}{switches}"


def _credential_battery(server: Server, probe: Probe, address: Address) -> list[bool]:
    """OQ-6: whether either route wants a caller, measured rather than read off an attribute."""
    checks = []
    for label, path in (("playlist", address.playlist()), ("fetch", address.whole())):
        joiner = "&" if "?" in path else "?"
        cases = (
            ("header token", {}, True),
            ("no token at all", {}, False),
            ("unknown token", {"X-Emby-Token": UNKNOWN_TOKEN}, False),
        )
        answers = {}
        for case, headers, send in cases:
            status, got, body = server.get_streaming(
                path, 200, extra_headers=headers or None, send_token=send
            )
            answers[case] = status
            probe.observe(f"{label}, {case}", _shape(status, got, body))
        status, got, body = server.get_streaming(
            path + joiner + "ApiKey=" + str(server.token), 200, send_token=False
        )
        answers["query token"] = status
        probe.observe(f"{label}, token in the query string", _shape(status, got, body))
        if label == "playlist":
            checks.extend(
                [
                    answers["header token"] == 200,
                    answers["no token at all"] == 401,
                    answers["unknown token"] == 401,
                    answers["query token"] == 200,
                ]
            )
        else:
            checks.extend(
                [
                    answers["header token"] == 200,
                    answers["no token at all"] == 200,
                    answers["unknown token"] == 200,
                    answers["query token"] == 200,
                ]
            )
    return checks


def _playlist_battery(
    server: Server, probe: Probe, source: SubtitledSource, address: Address
) -> list[bool]:
    """The playlist's own text, and AC-8's traversal of every entry it names."""
    status, headers, body = server.get_streaming(address.playlist(), 400)
    body.decode("utf-8")
    probe.observe("playlist head", _shape(status, headers, body))
    status, headers, whole = server.get_streaming(address.playlist(), 1_000_000)
    lines = whole.decode("utf-8").splitlines()
    entries = [line for line in lines if line and not line.startswith("#")]
    durations = [line for line in lines if line.startswith("#EXTINF")]
    expected = -(-source.runtime_ticks // (30 * TICKS_PER_SECOND))
    probe.observe(
        "playlist shape",
        f"{len(entries)} entries for a runtime of "
        f"{source.runtime_ticks / TICKS_PER_SECOND:.1f}s at 30s windows (expected {expected}), "
        f"last {durations[-1] if durations else 'none'!r}, "
        f"ends with {lines[-1]!r}",
    )
    probe.observe("first entry", entries[0] if entries else "none")

    # The window duration is written with `StringBuilder.Append(double)`, which formats in the
    # *server's* culture rather than the invariant one - so a partial last window comes out with
    # whatever decimal separator the operator's locale uses, inside a file whose grammar wants a
    # point. Every full window is an integer and hides it; only the remainder shows.
    fractional = [line[len("#EXTINF:") : -1] for line in durations if line[-2:-1].isdigit()]
    probe.observe(
        "window duration formatting",
        "durations {}; the partial window reads {!r}".format(
            "are all whole seconds" if not fractional else "include a fraction",
            fractional[-1] if fractional else "no partial window",
        ),
    )
    if fractional and "," in fractional[-1]:
        probe.note(
            "the partial window's duration carries a comma as its decimal separator, which is "
            "this server's locale leaking into a machine-readable playlist: an HLS parser reads "
            "#EXTINF:7,851, as a duration of 7 followed by a title of '851'. The number is "
            "formatted in the server's culture and not in the invariant one, so the same "
            "reference answers a different playlist on a differently configured host"
        )

    followed = []
    for entry in entries[:3] + entries[-1:]:
        status, got, payload = server.get_streaming(
            address.base + "/" + entry, 400, send_token=False
        )
        followed.append(status)
        probe.observe(
            "follow " + entry.split("?")[0] + " " + entry.split("StartPositionTicks=")[1][:20],
            _shape(status, got, payload),
        )
    return [
        lines[0] == "#EXTM3U",
        "#EXT-X-PLAYLIST-TYPE:VOD" in lines,
        lines[-1] == "#EXT-X-ENDLIST",
        len(entries) == expected,
        all(
            entry.startswith("stream.vtt?CopyTimestamps=true&AddVttTimeMap=true")
            for entry in entries
        ),
        all("&ApiKey=" in entry for entry in entries),
        all(status == 200 for status in followed),
    ]


def _window_battery(
    server: Server, probe: Probe, source: SubtitledSource, address: Address
) -> list[bool]:
    """OQ-11: what the two switches the playlist sets actually change."""
    whole_status, _, whole = server.get_streaming(address.whole(), 400_000, send_token=False)
    cues = whole.decode("utf-8", "replace")
    first = _first_cue_seconds(cues)
    if first is None:
        raise ProbeError("the whole-file fetch answered no cue, so a window cannot be compared")
    start = int((first - 5) * TICKS_PER_SECOND)
    start = max(start, 0)
    end = start + 30 * TICKS_PER_SECOND
    cases = (
        ("plain", ""),
        ("CopyTimestamps=true", "&CopyTimestamps=true"),
        ("AddVttTimeMap=true", "&AddVttTimeMap=true"),
        ("both, as the playlist sets them", "&CopyTimestamps=true&AddVttTimeMap=true"),
    )
    bodies = {}
    for label, switches in cases:
        status, headers, body = server.get_streaming(
            address.window(start, end, switches), 400, send_token=False
        )
        bodies[label] = body
        probe.observe("window " + label, _shape(status, headers, body))
    probe.observe(
        "the whole track, for comparison",
        f"{whole_status}, first cue at {first:.3f}s, {len(whole)} bytes read",
    )
    empty_status, _, empty = server.get_streaming(address.window(end, start), 400, send_token=False)
    probe.observe("a window whose end precedes its start", f"{empty_status}, {len(empty)} bytes")

    plain_first = _first_cue_seconds(bodies["plain"].decode("utf-8", "replace"))
    copied_first = _first_cue_seconds(bodies["CopyTimestamps=true"].decode("utf-8", "replace"))
    return [
        whole_status == 200,
        # Without the switch a window is rebased on itself; with it the cue keeps the time it
        # has in the file. Both are measured against the same cue.
        plain_first is not None and abs(plain_first - (first - start / TICKS_PER_SECOND)) < 0.01,
        copied_first is not None and abs(copied_first - first) < 0.01,
        # The time map is prepended into the WEBVTT header, and re-encoding the body drops the
        # byte order mark the plain answer starts with.
        bodies["plain"].startswith(b"\xef\xbb\xbfWEBVTT"),
        bodies["AddVttTimeMap=true"].startswith(b"WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:"),
        empty_status == 200,
    ]


def _stamp_ticks(stamp: str) -> int | None:
    """One `hh:mm:ss.fff` timestamp as ticks, read as integers so no float rounds a boundary."""
    cleaned = stamp.strip().replace(",", ".")
    parts = cleaned.split(":")
    if len(parts) == 3:
        hours, minutes, rest = parts
    elif len(parts) == 2:
        hours, minutes, rest = "0", parts[0], parts[1]
    else:
        return None
    seconds, _, fraction = rest.partition(".")
    try:
        whole = (int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * TICKS_PER_SECOND
        return whole + int((fraction or "0").ljust(3, "0")[:3]) * 10_000
    except ValueError:
        return None


def _cue_starts(body: bytes) -> list[int]:
    """Every cue's start position, in ticks, off a WebVTT body."""
    starts = []
    for line in body.decode("utf-8", "replace").splitlines():
        if "-->" not in line:
            continue
        start = _stamp_ticks(line.split("-->")[0])
        if start is not None:
            starts.append(start)
    return starts


def _clock(ticks: int) -> str:
    seconds = ticks / TICKS_PER_SECOND
    return f"{int(seconds) // 60:02d}:{seconds % 60:06.3f}"


def _boundary_battery(
    server: Server, probe: Probe, source: SubtitledSource, address: Address
) -> list[bool]:
    """AC-10: is a cue that starts exactly on a window boundary answered by **both** windows?

    011 T5 read this off the selection - the skip keeps a cue whose start equals the window's
    start, the take keeps one whose start equals its end, and the playlist hands consecutive
    windows the same position - and AGENTS.md's rule is that a claim about the reference is
    measured before it is acted on. So this battery asks.

    **Two forms, and the run says which it reached.** The first constructs the boundary from a
    cue's own start, which any track with a cue after zero can reach: it measures the selection
    rule itself. The second uses the reference's *own* generated playlist, which only lands on a
    cue when the library has one starting on a whole second, because the grid is whole seconds -
    that one measures whether a real client meets the case, and a run that misses it says so
    rather than inferring it.
    """
    length = 30 * TICKS_PER_SECOND
    copy = "&CopyTimestamps=true"

    status, _, whole = server.get_streaming(address.whole(), 400_000, send_token=False)
    starts = _cue_starts(whole)
    if status != 200 or len(starts) < 2:
        raise ProbeError(
            "the whole-file fetch answered fewer than two cues, so no boundary can be built"
        )

    # The framing of the document these cues arrive in, which the shapes above cut off at 110
    # bytes: a converted answer declares a region and puts a placement setting on every timing
    # line, and a check that compared only cues would pass on a document that placed them
    # somewhere else.
    timings = [line for line in whole.decode("utf-8", "replace").splitlines() if "-->" in line]
    probe.observe("the first cue's timing line, whole", repr(timings[0]) if timings else "none")

    # Not the first cue: the window before a boundary has to have somewhere to start.
    boundary = next((start for start in starts[1:] if start > length), None)
    if boundary is None:
        boundary = next((start for start in starts[1:] if start > 0), None)
    if boundary is None:
        raise ProbeError("every cue of this track starts at zero, so no boundary can be built")
    probe.observe(
        "boundary chosen",
        f"a cue starting at {boundary} ({_clock(boundary)}), which is where one window "
        f"ends and the next begins",
    )

    def answered(start: int, end: int) -> list[int]:
        _, _, body = server.get_streaming(
            address.window(start, end, copy), 400_000, send_token=False
        )
        return _cue_starts(body)

    before = answered(max(boundary - length, 0), boundary)
    after = answered(boundary, boundary + length)
    probe.observe(
        "the window ending on it",
        "{} cues, last at {}".format(len(before), _clock(before[-1]) if before else "none"),
    )
    probe.observe(
        "the window starting on it",
        "{} cues, first at {}".format(len(after), _clock(after[0]) if after else "none"),
    )
    repeated = boundary in before and boundary in after
    probe.observe(
        "the cue on the boundary",
        "answered by BOTH windows"
        if repeated
        else f"answered by {(boundary in before) + (boundary in after)} window(s)",
    )

    # The contrast that says it is the exact hit and not a rounding: one millisecond later the
    # same cue straddles the boundary rather than starting on it, and the later window's skip
    # drops it for ending before its start.
    inside = boundary + 10_000
    straddle_before = answered(max(inside - length, 0), inside)
    straddle_after = answered(inside, inside + length)
    straddled = boundary in straddle_before and boundary not in straddle_after
    probe.observe(
        "the same cue, one millisecond off the boundary",
        f"in the earlier window: {boundary in straddle_before}, "
        f"in the later window: {boundary in straddle_after}",
    )

    # The reference's own grid is whole seconds, so it only lands on a cue that starts on a
    # multiple of the segment length - and the longest segment that divides one of this track's
    # cue starts is the one to ask for, because it is also the shortest playlist.
    on_a_second: int | None = None
    segment = 0
    for candidate in range(30, 0, -1):
        step = candidate * TICKS_PER_SECOND
        if source.runtime_ticks // step > 1500:
            continue  # a playlist of thousands of entries measures nothing this does not
        landed = next((s for s in starts if s > 0 and s % step == 0), None)
        if landed is not None:
            on_a_second, segment = landed, candidate
            break
    grid_checks: list[bool] = []
    if on_a_second is None:
        shortest = next(
            (n for n in range(1, 31) if source.runtime_ticks // (n * TICKS_PER_SECOND) <= 1500),
            30,
        )
        probe.note(
            f"no cue of this track starts on a whole multiple of any segment length between "
            f"{shortest} and 30 seconds - shorter lengths are skipped because they would ask "
            f"this {source.runtime_ticks / TICKS_PER_SECOND:.0f}s runtime for a playlist of more "
            f"than 1500 entries - so the reference's OWN grid has no boundary to land on here and "
            f"the playlist form of this case was NOT reached. What reaches it is a track with a "
            f"cue starting on such a multiple. The constructed windows above measure the same "
            f"selection rule, on the same route, with the same two positions the playlist writes"
        )
        probe.observe("the reference's own playlist grid", "not reached on this track")
    else:
        seconds = on_a_second // TICKS_PER_SECOND
        _, _, playlist = server.get_streaming(address.playlist(segment), 4_000_000)
        entries = [
            line
            for line in playlist.decode("utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        pair = [
            entry
            for entry in entries
            if f"StartPositionTicks={on_a_second}&" in entry
            or f"EndPositionTicks={on_a_second}&" in entry
        ]
        probe.observe(
            "the reference's own playlist grid",
            f"a cue starts at {seconds}s, so at SegmentLength={segment} the grid has a "
            f"boundary on it; "
            f"{len(pair)} of {len(entries)} entries share that position",
        )
        seen = []
        for entry in pair:
            _, _, body = server.get_streaming(address.base + "/" + entry, 400_000, send_token=False)
            found = on_a_second in _cue_starts(body)
            seen.append(found)
            probe.observe(
                "follow " + entry.split("&ApiKey")[0],
                "the boundary cue is {}".format("present" if found else "absent"),
            )
        grid_checks = [len(pair) == 2, all(seen)]

    return [repeated, straddled, *grid_checks]


def _first_cue_seconds(text: str) -> float | None:
    for line in text.splitlines():
        if "-->" not in line:
            continue
        stamp = line.split("-->")[0].strip().replace(",", ".")
        parts = stamp.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
        except ValueError:
            return None
    return None


def _format_battery(server: Server, probe: Probe, address: Address) -> list[bool]:
    answers = {}
    for fmt in FORMATS:
        status, headers, body = server.get_streaming(address.whole(fmt), 200, send_token=False)
        answers[fmt] = status
        probe.observe("Stream." + fmt, _shape(status, headers, body))
    lower_status, _, lower = server.get_streaming(
        address.base + "/stream.vtt", 200, send_token=False
    )
    upper_status, _, upper = server.get_streaming(address.whole("vtt"), 200, send_token=False)
    probe.observe(
        "stream.vtt against Stream.vtt",
        f"{lower_status} and {upper_status}, "
        + ("same first bytes" if lower == upper else "different first bytes"),
    )
    return [
        answers["vtt"] == 200,
        answers["srt"] == 200,
        answers["json"] == 200,
        answers["js"] == 200,
        answers["xyz"] == 400,
        # The manifest and the playlist both write the route in lower case; the reference's own
        # declaration spells it with a capital. A client following either has to be served.
        lower_status == 200 and upper_status == 200 and lower == upper,
    ]


#: How many tracks the artefact battery is allowed to make the reference extract. Each miss is a
#: full demux of a film for a few kilobytes of text - 33 to 40 seconds each, measured - and the
#: battery stops as soon as it has seen both forms of the answer.
ARTEFACT_CANDIDATES = 3


def _artefact_battery(server: Server, probe: Probe) -> list[bool]:
    """What the reference's own extraction wrote, read back through the same-format short circuit.

    `Stream.ass` on an **embedded** `ass` track is answered before anything is parsed - the
    requested format equals the format the readable file is in, so the file's bytes are handed
    back whole. Those bytes are the artefact, which is the only thing about extraction a client
    can see, and they are not what ffmpeg wrote: the reference replaces `,Arial,` with
    `,Arial Unicode MS,` in a freshly extracted `.ass` and rewrites the file **only if that
    changed something**, through a writer that emits the UTF-8 preamble.

    So the claim measured here is a biconditional rather than a byte string: the substituted font
    and the byte order mark arrive **together or not at all**. A run says which forms it reached,
    because whether a library holds a track whose style names Arial is a fact about the library.
    """
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes="Movie,Episode",
        Recursive="true",
        Limit=400,
        Fields="MediaStreams",
    )
    candidates = []
    for row in found.get("Items", []):
        streams = row.get("MediaStreams") or []
        subtitles = [one for one in streams if one.get("Type") == "Subtitle"]
        embedded = [
            one
            for one in subtitles
            if not one.get("IsExternal") and str(one.get("Codec", "")).lower() == "ass"
        ]
        if not embedded:
            continue
        # The reference extracts *every* extractable track of a source in one invocation, so the
        # cheapest candidate is the one with fewest of them rather than the first one seen.
        extractable = [
            one
            for one in subtitles
            if one.get("IsTextSubtitleStream") or str(one.get("Codec", "")).upper() == "PGSSUB"
        ]
        candidates.append((len(extractable), row["Id"], int(embedded[0]["Index"])))
    if not candidates:
        probe.note(
            "no item in this library carries an embedded `ass` subtitle track, so the extracted "
            "artefact could not be read back: the same-format short circuit needs a track whose "
            "own format is one a client can ask for by name, and `srt` is not one - an embedded "
            "subrip track is extracted to `srt` too, so `Stream.srt` on it reaches the same "
            "shortcut and the same reading. What this battery did NOT measure is the font "
            "substitution and the byte order mark that comes with it"
        )
        probe.observe("the extracted artefact", "not reached: no embedded `ass` track")
        return []

    candidates.sort()
    seen = []
    for _, item_id, index in candidates[:ARTEFACT_CANDIDATES]:
        source = resolve_subtitled_source(server, item_id)
        address = Address(item_id, source.source_id, index)
        status, _, body = server.get_streaming(address.whole("ass"), 100_000, send_token=False)
        style = next(
            (
                line
                for line in body.decode("utf-8", "replace").splitlines()
                if line.startswith("Style:")
            ),
            "no Style line",
        )
        substituted = b",Arial Unicode MS," in body
        marked = body.startswith(b"\xef\xbb\xbf")
        seen.append((substituted, marked, b",Arial," in body))
        probe.observe(
            "Stream.ass on embedded ass " + item_id[:8] + "/" + str(index),
            f"{status}, {len(body)} bytes; font substituted: {substituted}; "
            f"byte order mark: {marked}; {style[:96]}",
        )
        if len({one[0] for one in seen}) == 2:
            break

    forms = {one[0] for one in seen}
    probe.observe(
        "the two forms of the artefact",
        "reached {}".format(
            "both - one track whose style named Arial and one whose style did not"
            if len(forms) == 2
            else (
                "only the substituted form; no track here has a style naming another font, so "
                "'no substitution, no mark' is NOT measured by this run"
                if forms == {True}
                else "only the unsubstituted form; no track here has an Arial style, so "
                "'substitution brings the mark' is NOT measured by this run"
            )
        ),
    )
    return [
        # The whole claim: the mark is on exactly the files the substitution rewrote, and no
        # answer still carries the font the reference replaces.
        all(substituted == marked for substituted, marked, _ in seen),
        not any(original for _, _, original in seen),
    ]


def _refusal_battery(
    server: Server, probe: Probe, source: SubtitledSource, address: Address, allow_writes: bool
) -> list[bool]:
    """OQ-8: each row of §3.7, on each route."""
    unknown = Address(UNKNOWN_ITEM, UNKNOWN_ITEM, source.text_index())
    empty = Address(EMPTY_GUID, EMPTY_GUID, source.text_index())
    bad_source = Address(source.item_id, "deadbeef", source.text_index())
    no_stream = Address.of(source, 99)
    negative = Address.of(source, -1)
    video = [s for s in source.source.get("MediaStreams") or [] if s.get("Type") == "Video"]
    cases = [
        ("unknown item, fetch", unknown.whole()),
        ("unknown item, playlist", unknown.playlist()),
        ("empty identifier, fetch", empty.whole()),
        ("empty identifier, playlist", empty.playlist()),
        ("malformed identifier, fetch", "/Videos/not-a-guid/x/Subtitles/0/Stream.vtt"),
        ("media source names nothing, fetch", bad_source.whole()),
        ("media source names nothing, playlist", bad_source.playlist()),
        ("index names no stream, fetch", no_stream.whole()),
        ("index names no stream, playlist", no_stream.playlist()),
        ("negative index, fetch", negative.whole()),
        ("window length absent", address.playlist(None)),
        ("window length zero", address.playlist(0)),
        ("window length not a number", address.playlist("abc")),
    ]
    if video:
        cases.append(
            ("index names a video stream, fetch", Address.of(source, video[0]["Index"]).whole())
        )
    answers = {}
    for label, path in cases:
        status, headers, body = server.get_streaming(path, 300)
        answers[label] = status
        probe.observe(label, _shape(status, headers, body))
    if source.image and allow_writes:
        path = Address.of(source, source.image_index()).whole()
        status, headers, body = server.get_streaming(path, 300)
        answers["image track asked for as text"] = status
        probe.observe("image track asked for as text", _shape(status, headers, body))
    elif source.image:
        probe.note(
            "the image-subtitle case is skipped without --allow-writes: the reference does not "
            "refuse it up front, it starts an extraction and refuses tens of seconds later"
        )
    return [
        # Two different refusals for two different misses: an unknown identifier is a 500 on the
        # fetch route, while the empty one is refused by a guard before any lookup.
        answers["unknown item, playlist"] == 404,
        answers["empty identifier, fetch"] == 400,
        answers["empty identifier, playlist"] == 400,
        answers["malformed identifier, fetch"] == 400,
        answers["media source names nothing, fetch"] == 500,
        answers["media source names nothing, playlist"] == 500,
        answers["index names no stream, fetch"] == 500,
        # The playlist route never reads the index: it answers a full playlist of addresses that
        # every one of them refuses.
        answers["index names no stream, playlist"] == 200,
        answers["window length absent"] == 400,
        answers["window length zero"] == 400,
        answers["window length not a number"] == 400,
    ]


def run(server: Server, args: argparse.Namespace) -> Probe:
    probe = Probe(
        script="probe_subtitle_delivery.py",
        question=(
            "What do the subtitle playlist and the subtitle fetch answer - to a caller with no "
            "token, to a window, to a format, and to every way of naming nothing?"
        ),
        document="specs/011-subtitle-delivery/spec.md",
        section="§3.5, §3.7, OQ-6, OQ-8, OQ-11",
        expectation=None,
    )
    source = _pick(server)
    address = Address.of(source, source.text_index())
    probe.observe(
        "source",
        f"item {source.item_id}, stream {source.text_index()} "
        f"({source.text[0].get('Codec')}), runtime "
        f"{source.runtime_ticks / TICKS_PER_SECOND:.1f}s",
    )
    checks = _credential_battery(server, probe, address)
    checks.extend(_playlist_battery(server, probe, source, address))
    checks.extend(_window_battery(server, probe, source, address))
    checks.extend(_boundary_battery(server, probe, source, address))
    checks.extend(_format_battery(server, probe, address))
    checks.extend(_artefact_battery(server, probe))
    checks.extend(_refusal_battery(server, probe, source, address, args.allow_writes))

    if all(checks):
        probe.conclude(
            "the two routes do not share a rule: the playlist refuses a caller with no token "
            "and one with an unknown token alike, with an empty 401, while the fetch route "
            "serves the cues to anybody who asks. The playlist's entries name a lower-case "
            "stream.vtt with both timestamp switches set and the caller's token appended, and "
            "the switches are not decoration - without CopyTimestamps a window is rebased on "
            "itself, and AddVttTimeMap rewrites the header and drops the byte order mark. The "
            "playlist never reads the stream index it is given, so a playlist for a stream that "
            "does not exist is a 200 whose every entry is a 500. And a cue that starts exactly "
            "where one window ends and the next begins is answered by BOTH of them: both ends of "
            "the selection are inclusive and consecutive windows are handed the same position, "
            "so the windows of a track concatenate to the track plus one repeat per such cue - "
            "one millisecond off the boundary the same cue is answered once. And the extraction "
            "behind all of it does not hand back what ffmpeg wrote: an extracted .ass has "
            ",Arial, replaced with ,Arial Unicode MS, and is rewritten only where that changed "
            "something, so the substituted font and the byte order mark arrive together or not "
            "at all",
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
        help="Also ask for an image subtitle track as text. The reference answers it by "
        "starting an extraction and refusing tens of seconds later, so it is the one case here "
        "that makes the server work.",
    )


if __name__ == "__main__":
    raise SystemExit(
        main(run, __doc__.splitlines()[0], extra_arguments=_extra_arguments, with_args=True)
    )
