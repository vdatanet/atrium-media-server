#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the two subtitle addresses answer: to a caller with no credential, to a window, to a
format the server cannot make, and to every way of naming a stream that is not there.

specs/011 §3.5 and §3.7, OQ-6, OQ-8 and OQ-11. Eight batteries:

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
  cannot produce, one that turns the cue list into JSON, and the three the first draft of this
  battery never asked for - `ttml`, which the reference writes and nothing had requested, and
  `subrip` and `webvtt`, the two spellings that reach a writer and have no row in the label
  lookup. It reads the `Content-Type` and the byte order mark of every one of them off the run
  rather than off a paragraph, which is what plan §6.8 asks for;
- **the conversion** (AC-10): the same-format short circuit *with a window on it*, the SubRip
  renumbering, the deprecated query aliases that override the address, which of two start
  positions wins when both are given, and whether a cue whose end does not follow its start is
  pushed out by a millisecond. The last of those is a fact about the library rather than about
  the server, so the battery says whether it reached one;
- **the extracted artefact**: what an embedded `ass` track answers when the format asked for is
  the one it is already in - which is the extraction itself, handed back by the same-format short
  circuit. It is the only way from outside to see what the reference's extraction wrote, and it
  carries the thing no format specification predicts: the font substitution the reference performs
  on a `.ass` after extracting it, and the byte order mark that arrives with it and only with it;
- **the refusals** (OQ-8): each row of 011 §3.7 on each route, as bytes rather than as a status -
  plus the row T7 needed and the table did not have, an item that **is** there and holds nothing
  servable, which is what says whether the fetch route's `400` is about the identifier or about
  there being nothing to convert. T8 added the playlist column of three of them: the parameter a
  malformed identifier names, read out of the body rather than assumed, because the two routes
  declare that path segment under different names; the same existing-but-empty item, which the
  playlist route answers a `404` where the fetch route answers `500`; and a source with no
  runtime, which is searched for and **reported as a miss when the library holds none**.

Read-only by default. `--allow-writes` adds the one case that makes the reference work: asking
for an *image* subtitle track as text, which it attempts with ffmpeg for some tens of seconds
before refusing.

Usage:
    python3 tools/probe_subtitle_delivery.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import argparse
import json
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

#: The formats a client can name in the address. `js` is the reference's own alias for `json`;
#: `subrip` and `webvtt` are the two the writer table admits and the label lookup does not; `sub`
#: and `xyz` are the two nothing writes.
FORMATS = ("vtt", "srt", "ass", "ssa", "json", "js", "ttml", "subrip", "webvtt", "sub", "xyz")

#: What each format is expected to be labelled with, and whether its body is expected to begin
#: with the UTF-8 preamble. Written down so the run *checks* rather than only prints: five rows
#: were measured at 011 T5 and the other four are this battery's own.
LABELS = {
    "vtt": "text/vtt",
    "srt": "application/x-subrip",
    "ass": "text/x-ssa",
    "ssa": "text/x-ssa",
    "json": "application/json",
    "js": "application/json",
    "ttml": "application/ttml+xml",
    "subrip": "application/octet-stream",
    "webvtt": "application/octet-stream",
}

#: The UTF-8 preamble the reference's text writers emit. `json` writes bytes and has none, and
#: neither has an answer handed back by the same-format short circuit rather than rendered.
BYTE_ORDER_MARK = b"\xef\xbb\xbf"

TICKS_PER_SECOND = 10_000_000

#: How many external text tracks the conversion battery reads looking for a cue whose end does
#: not follow its start. External streams are read from their own file with no extraction, so
#: each is one cheap request - unlike an embedded track, whose first fetch demuxes a film.
BUMP_CANDIDATES = 12


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

    def whole(self, fmt: str = "vtt", query: str = "") -> str:
        return f"{self.base}/Stream.{fmt}{'?' + query if query else ''}"

    def at(self, start: int, fmt: str = "vtt", query: str = "") -> str:
        """The ticks-in-path form: `GetSubtitleWithTicks`, which the negotiation's own address
        names, so a client following what it was handed lands here and not on the other route."""
        return f"{self.base}/{start}/Stream.{fmt}{'?' + query if query else ''}"

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
    """Every spelling a client can put in the address: its status, its label and its first bytes.

    The label is the row `media/labels.py` carries and the mark is the row `media/subtitles.py`
    carries, and both are read **off this run** rather than off a paragraph, which is what plan
    §6.8 asks for. Three of the eleven spellings had never been asked for at all: `ttml`, which
    the reference writes, and `subrip` and `webvtt`, which reach a writer and have no row in the
    label lookup - so what they end on was a reading until now.
    """
    answers = {}
    labels = {}
    marks = {}
    for fmt in FORMATS:
        status, headers, body = server.get_streaming(address.whole(fmt), 200, send_token=False)
        answers[fmt] = status
        labels[fmt] = (headers.get("Content-Type") or "").split(";")[0]
        marks[fmt] = body.startswith(BYTE_ORDER_MARK)
        probe.observe("Stream." + fmt, _shape(status, headers, body))
    probe.observe(
        "the byte order mark, by format",
        ", ".join(f"{fmt}: {'yes' if marks[fmt] else 'no'}" for fmt in LABELS),
    )
    lower_status, _, lower = server.get_streaming(
        address.base + "/stream.vtt", 200, send_token=False
    )
    upper_status, _, upper = server.get_streaming(address.whole("vtt"), 200, send_token=False)
    probe.observe(
        "stream.vtt against Stream.vtt",
        f"{lower_status} and {upper_status}, "
        + ("same first bytes" if lower == upper else "different first bytes"),
    )
    _, whole_headers, _ = server.get_streaming(address.whole("vtt"), 200, send_token=False)
    named = sorted(whole_headers)
    probe.observe("the header set of a fetch", ", ".join(named))
    return [
        # Everything the writer table admits answers, including the three this battery had never
        # asked for - so `ttml` is not a refusal to invent, and `subrip` and `webvtt` are not one
        # either: the label falls back rather than failing.
        *(answers[fmt] == 200 for fmt in LABELS),
        answers["sub"] == 400,
        answers["xyz"] == 400,
        # The label of every one of them, measured. `subrip` and `webvtt` reach `MimeTypes` with
        # a name it has no row for, and the framework's file result defaults the type rather than
        # refusing - which is how a format with no media type still answers a body.
        *(labels[fmt] == LABELS[fmt] for fmt in LABELS),
        # The mark is on every *rendered* document but `json`'s, and absent from the one answer
        # that is not rendered at all: `Stream.srt` on a SubRip track is the readable file handed
        # back by the same-format short circuit.
        all(marks[fmt] for fmt in ("vtt", "ass", "ssa", "ttml", "subrip", "webvtt")),
        not any(marks[fmt] for fmt in ("json", "js", "srt")),
        # The manifest and the playlist both write the route in lower case; the reference's own
        # declaration spells it with a capital. A client following either has to be served.
        lower_status == 200 and upper_status == 200 and lower == upper,
        # No `Accept-Ranges` and no `Last-Modified`: a converted subtitle is a body built for the
        # request, and the reference offers nothing to range over or revalidate against.
        "Content-Length" in whole_headers,
        not {"Accept-Ranges", "ETag", "Last-Modified", "Content-Disposition"} & set(whole_headers),
    ]


def _numbering_of(document: bytes) -> list[str]:
    """The cue numbers a SubRip document states, in order."""
    text = document.decode("utf-8", "replace").removeprefix("﻿")
    lines = text.replace("\r\n", "\n").split("\n")
    return [
        line.strip()
        for index, line in enumerate(lines)
        if line.strip().isdigit() and index + 1 < len(lines) and "-->" in lines[index + 1]
    ]


def _cue_events(server: Server, path: str) -> list[dict[str, Any]]:
    """One track's cues as the `json` writer states them: identifiers and tick positions."""
    status, _, payload = server.get_streaming(path, 8_000_000, send_token=False)
    if status != 200:
        return []
    try:
        events = json.loads(payload.decode("utf-8"))["TrackEvents"]
    except (ValueError, KeyError, UnicodeDecodeError):
        return []
    return [one for one in events if isinstance(one, dict)]


def _bump_battery(server: Server, probe: Probe) -> list[bool]:
    """Whether a cue whose end does not follow its start is pushed out by one millisecond.

    Read off `VttWriter` at 011 T5 and owed a measurement since. **It is reachable only if a real
    file holds such a cue**, which is a fact about the library and not about the server, so this
    reports the miss rather than inferring the answer from the read.

    Only **external** text tracks are searched: they are read from their own file with no
    extraction, so each is one cheap request, where an embedded track's first fetch demuxes a
    whole film.
    """
    externals = []
    for candidate in find_subtitled_sources(server):
        for stream in candidate.subtitles:
            if stream.get("IsExternal") and stream.get("IsTextSubtitleStream"):
                externals.append((candidate.item_id, int(stream["Index"])))

    scanned = 0
    cues = 0
    for item_id, index in externals[:BUMP_CANDIDATES]:
        source = resolve_subtitled_source(server, item_id)
        address = Address(item_id, source.source_id, index)
        events = _cue_events(server, address.whole("json"))
        if not events:
            continue
        scanned += 1
        cues += len(events)
        found = [
            one for one in events if int(one["EndPositionTicks"]) <= int(one["StartPositionTicks"])
        ]
        if not found:
            continue
        start = int(found[0]["StartPositionTicks"])
        status, _, body = server.get_streaming(
            address.whole(
                "vtt",
                f"StartPositionTicks={start}&EndPositionTicks={start + TICKS_PER_SECOND}"
                "&CopyTimestamps=true",
            ),
            2_000,
            send_token=False,
        )
        timing = next(
            (line for line in body.decode("utf-8", "replace").splitlines() if "-->" in line),
            "no timing line",
        )
        probe.observe(
            "a cue whose end does not follow its start",
            f"{item_id[:8]}/{index} states {found[0]['StartPositionTicks']} -> "
            f"{found[0]['EndPositionTicks']}; the vtt of that window reads {timing!r} ({status})",
        )
        return [_millisecond_apart(timing)]

    probe.note(
        f"the one-millisecond end bump is NOT measured by this run: {scanned} external text "
        f"tracks holding {cues} cues between them were read and not one states a cue whose end "
        "does not follow its start, which is what the WebVTT writer edits. It stays a reading "
        "`[source: MediaBrowser.MediaEncoding/Subtitles/VttWriter.cs:34-38 @ v10.11.11]` until a "
        "library carries such a file - the miss is a fact about the library, not about the server"
    )
    probe.observe(
        "a cue whose end does not follow its start",
        f"not reached: none in {cues} cues across {scanned} external text tracks",
    )
    return []


def _millisecond_apart(timing: str) -> bool:
    """Whether a WebVTT timing line states an end exactly one millisecond after its start."""
    halves = timing.split("-->")
    if len(halves) != 2:
        return False
    try:
        start, end = (_clock_seconds(half.strip().split(" ")[0]) for half in halves)
    except ValueError:
        return False
    return abs((end - start) - 0.001) < 0.0005


def _clock_seconds(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    raise ValueError(stamp)


def _conversion_battery(server: Server, probe: Probe, address: Address) -> list[bool]:
    """What happens between the readable file and the document, measured from outside.

    Four things the plan and the spec had read rather than measured, and all four are one request
    each on a track whose own format a client can name:

    * **the same-format short circuit, with a window on it.** `Stream.srt` on a SubRip track is
      answered before anything is parsed, so the window and both switches are ignored - which is
      the clause AC-10 gained for it: *"a windowed fetch answers the cues of that window and no
      others, except where the requested format is the one the track is already in"*;
    * **the SubRip writer renumbers from one.** Invisible on the short-circuited spelling and
      visible on `subrip` beside it, which renders: a window starting ten minutes in comes back
      numbered `1` while the same window's `json` states the identifier the file wrote down;
    * **the deprecated query aliases override the address.** `?format=` and `?index=` are declared
      obsolete and are still bound, so a client sending one gets a different track or a different
      format than the path names;
    * **which of two start positions wins.** The ticks-in-path route takes the query's when both
      are given, which is the opposite of the direction plan §6.7 stated.
    """
    whole_status, _, whole = server.get_streaming(address.whole("srt"), 400_000, send_token=False)
    start = 600 * TICKS_PER_SECOND
    end = 660 * TICKS_PER_SECOND
    window = f"StartPositionTicks={start}&EndPositionTicks={end}&CopyTimestamps=true"
    short_status, _, shorted = server.get_streaming(
        address.whole("srt", window), 400_000, send_token=False
    )
    ticked_status, _, ticked = server.get_streaming(
        address.at(start, "srt", f"EndPositionTicks={end}&CopyTimestamps=true"),
        400_000,
        send_token=False,
    )
    probe.observe(
        "Stream.srt with a window on it",
        f"{short_status}, {len(shorted)} bytes against the whole track's {len(whole)} "
        f"({whole_status}): "
        + ("the window was ignored" if shorted == whole else "the window was applied"),
    )
    probe.observe(
        "the same window through the ticks-in-path route",
        f"{ticked_status}, {len(ticked)} bytes: "
        + ("the window was ignored" if ticked == whole else "the window was applied"),
    )

    rendered_status, rendered_headers, rendered = server.get_streaming(
        address.whole("subrip", window), 400_000, send_token=False
    )
    numbers = _numbering_of(rendered)
    events = _cue_events(server, address.whole("json", window))
    identifiers = [str(one.get("Id")) for one in events]
    probe.observe(
        "the same window under `subrip`, which renders",
        f"{rendered_status}, {rendered_headers.get('Content-Type')}, {len(rendered)} bytes, "
        f"numbered from {numbers[0] if numbers else 'nothing'!r} "
        f"({len(numbers)} cues); the `json` of the identical window calls the first cue "
        f"{identifiers[0] if identifiers else 'nothing'!r}",
    )

    alias_status, alias_headers, aliased = server.get_streaming(
        address.whole("vtt", "format=srt"), 400_000, send_token=False
    )
    index_status, _, _index_body = server.get_streaming(
        address.whole("vtt", "index=99"), 200, send_token=False
    )
    probe.observe(
        "Stream.vtt?format=srt",
        f"{alias_status}, {alias_headers.get('Content-Type')}, {len(aliased)} bytes: "
        + ("the query won" if aliased == whole else "the path won"),
    )
    probe.observe(
        "Stream.vtt?index=99, on a track that exists",
        f"{index_status}: " + ("the query won" if index_status == 500 else "the path won"),
    )

    both_status, _, both = server.get_streaming(
        address.at(
            start, "vtt", f"StartPositionTicks=0&EndPositionTicks={end}&CopyTimestamps=true"
        ),
        400_000,
        send_token=False,
    )
    path_only_status, _, path_only = server.get_streaming(
        address.at(start, "vtt", f"EndPositionTicks={end}&CopyTimestamps=true"),
        400_000,
        send_token=False,
    )
    both_first = _first_cue_seconds(both.decode("utf-8", "replace"))
    path_first = _first_cue_seconds(path_only.decode("utf-8", "replace"))
    probe.observe(
        "a start position in the path AND in the query",
        f"{both_status}: the first cue is at {both_first}s where the path alone answers "
        f"{path_first}s ({path_only_status}) - "
        + ("the query won" if (both_first or 0) < (path_first or 0) else "the path won"),
    )

    map_status, _, mapped = server.get_streaming(
        address.whole("webvtt", "AddVttTimeMap=true"), 400, send_token=False
    )
    probe.observe(
        "Stream.webvtt?AddVttTimeMap=true",
        f"{map_status}: mapping line {'present' if b'X-TIMESTAMP-MAP' in mapped else 'absent'}, "
        f"byte order mark {'kept' if mapped.startswith(BYTE_ORDER_MARK) else 'dropped'}",
    )

    return [
        # AC-10's first contradiction, measured: the short circuit ignores the window whichever
        # route asks for it.
        whole_status == 200 and short_status == 200 and shorted == whole,
        ticked_status == 200 and ticked == whole,
        # And the spelling beside it renders, which is what makes the first row a short circuit
        # rather than a track with no cues in that window.
        rendered_status == 200 and rendered != whole and len(rendered) < len(whole),
        bool(numbers) and numbers[0] == "1",
        bool(identifiers) and identifiers[0] != "1",
        # The obsolete aliases are bound and win.
        alias_status == 200
        and aliased == whole
        and alias_headers.get("Content-Type") == LABELS["srt"],
        index_status == 500,
        # And so does the query's start position, over the one in the path.
        both_status == 200 and path_only_status == 200 and both != path_only,
        both_first is not None and path_first is not None and both_first < path_first,
        # The time map is read against `vtt` and not against the alias sharing its writer.
        map_status == 200
        and b"X-TIMESTAMP-MAP" not in mapped
        and mapped.startswith(BYTE_ORDER_MARK),
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


#: The item types the playlist route can serve. Its own lookup asks for a *video* and answers the
#: framework's not-found result for anything else `[source:
#: Jellyfin.Api/Controllers/SubtitleController.cs:350-354 @ v10.11.11]`, so a source with no
#: runtime that is not one of these never reaches the runtime check at all - which is what the
#: search below has to say when it finds none.
VIDEO_TYPES = "Movie,Episode,Video,MusicVideo,Trailer"


def _a_video_without_a_runtime(server: Server) -> tuple[str, str] | tuple[None, int]:
    """One video source whose runtime is absent or not positive, or how many were checked.

    011 plan §6.8 leaves this owed: the reference refuses such a source on its own argument check
    and no row of §3.7 says so, because the probe's own source selection *requires* a runtime. The
    state cannot be constructed from outside - a runtime is written by the scan that created the
    item - so this either finds one in the library or reports that the library has none, which is
    a fact about the library rather than about the server.
    """
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes=VIDEO_TYPES,
        Recursive="true",
        Limit=5000,
        Fields="MediaSources",
    )
    checked = 0
    for row in found.get("Items") or []:
        for one in row.get("MediaSources") or []:
            checked += 1
            if not one.get("RunTimeTicks"):
                return str(row["Id"]), str(one.get("Id") or row["Id"])
    return None, checked


def _parameter_named(body: bytes) -> str | None:
    """The single key of a problem-details `errors` map, which is the parameter that would not bind.

    Read out of the body rather than assumed, because the whole point of the row is that the two
    routes name different parameters for the same malformed value.
    """
    try:
        errors = json.loads(body.decode("utf-8")).get("errors") or {}
    except (ValueError, UnicodeDecodeError):
        return None
    keys = list(errors)
    return keys[0] if len(keys) == 1 else None


def _a_series(server: Server) -> str | None:
    """One series identifier, which is an item that exists and has no media source of any kind."""
    found = server.get(
        "/Items", UserId=server.user_id, IncludeItemTypes="Series", Recursive="true", Limit=1
    )
    rows = found.get("Items") or []
    return str(rows[0]["Id"]) if rows else None


def _refusal_battery(
    server: Server, probe: Probe, source: SubtitledSource, address: Address, allow_writes: bool
) -> list[bool]:
    """OQ-8: each row of §3.7, on each route.

    One row is 011 T7's own: an item that **is** there and holds nothing servable - a series - is
    a different answer from an identifier nothing holds at all, and a route that resolved the two
    the same way would answer the wrong status to one of them.

    Three more are 011 T8's, and two of them are the rows plan §6.8 left owed to it: the
    malformed-identifier refusal on the **playlist** route, which §3.7 had recorded as naming
    `routeItemId` from a run that only ever asked the fetch route; and a source with no runtime,
    which the source selection at the top of this file excludes on purpose and which is therefore
    searched for here rather than assumed present. The third is the playlist column of the row T7
    added, which the table had left as a dash. All three rows of §3.7 were corrected at T8 from
    this battery, so what these cases now do is hold the corrected table rather than propose it.
    """
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
        (
            "malformed identifier, playlist",
            "/Videos/not-a-guid/x/Subtitles/0/subtitles.m3u8?SegmentLength=30",
        ),
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
    series = _a_series(server)
    if series is not None:
        cases.append(
            ("item exists and holds nothing servable, fetch", Address(series, series, 0).whole())
        )
        # The same identifier on the playlist route, whose own lookup asks for a video. This cell
        # was a dash in §3.7 until T8 measured it, and a dash is not something a route can answer.
        cases.append(
            (
                "item exists and holds nothing servable, playlist",
                Address(series, series, 0).playlist(),
            )
        )
    without_runtime, detail = _a_video_without_a_runtime(server)
    if without_runtime is not None:
        cases.append(
            (
                "source states no runtime, playlist",
                Address(without_runtime, str(detail), 0).playlist(),
            )
        )
    answers = {}
    bodies = {}
    for label, path in cases:
        # Long enough for a whole problem-details body, because two of these rows are about the
        # parameter *named* inside one; `_shape` still prints only its first hundred bytes.
        status, headers, body = server.get_streaming(path, 1500)
        answers[label] = status
        bodies[label] = body
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
    if series is None:
        probe.note(
            "this library holds no series, so 'an item that exists and holds nothing servable' "
            "is NOT measured by this run - which is the row that says whether the fetch route's "
            "400 is about the identifier naming nothing or about there being nothing to convert"
        )
    if without_runtime is None:
        probe.note(
            f"'a source with no runtime' is NOT measured by this run: all {detail} media sources "
            f"of the {VIDEO_TYPES} items in this library state one, and the playlist route asks "
            f"for a video before it reads a runtime, so a source of any other type never reaches "
            f"that check. A runtime is written by the scan that creates the item, so the state "
            f"cannot be constructed from outside; the row stays a reading `[source: "
            f"Jellyfin.Api/Controllers/SubtitleController.cs:356-363 @ v10.11.11]` until a "
            f"library carries such a file - a fact about the library, not about the server"
        )
    named = _parameter_named(bodies.get("malformed identifier, playlist", b""))
    probe.observe(
        "the parameter a malformed identifier names, per route",
        "playlist: {}, fetch: {}".format(
            named or "none", _parameter_named(bodies["malformed identifier, fetch"]) or "none"
        ),
    )
    if named != "itemId":
        probe.note(
            f"011 spec §3.7 says the playlist route answers problem details naming `itemId` and "
            f"the fetch routes `routeItemId`, each naming its own path segment; this run says the "
            f"playlist names `{named}`. That row was corrected at T8 from this battery, so a "
            f"disagreement here means the table has gone false rather than that it was never right"
        )
    return [
        # Two different refusals for two different misses: an unknown identifier is a 500 on the
        # fetch route, while the empty one is refused by a guard before any lookup.
        answers["unknown item, playlist"] == 404,
        answers["unknown item, fetch"] == 400,
        # And the split the two above cannot show on their own: an item that IS there with
        # nothing to convert is the 500, so the 400 is about the identifier naming nothing.
        *(
            [answers["item exists and holds nothing servable, fetch"] == 500]
            if series is not None
            else []
        ),
        answers["empty identifier, fetch"] == 400,
        answers["empty identifier, playlist"] == 400,
        answers["malformed identifier, fetch"] == 400,
        answers["malformed identifier, playlist"] == 400,
        # The row plan §6.8 predicted from the declaration: the playlist route names its own path
        # parameter, which is not the one the fetch routes name.
        named == "itemId",
        # And the cell §3.7 left as a dash until T8: the playlist route's lookup asks for a video,
        # so an item that exists and is not one is the negotiation's 404 rather than the fetch's
        # 500.
        *(
            [answers["item exists and holds nothing servable, playlist"] == 404]
            if series is not None
            else []
        ),
        *(
            [answers["source states no runtime, playlist"] == 400]
            if without_runtime is not None
            else []
        ),
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
    checks.extend(_conversion_battery(server, probe, address))
    checks.extend(_bump_battery(server, probe))
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
            "at all. And a window is not always a window: asking for the format the track is "
            "already in answers the WHOLE track, unwindowed, on both fetch routes - while the "
            "spelling beside it renders that same window and numbers it from 1, discarding the "
            "identifier the file wrote down. Every writable spelling answers, ttml included, and "
            "the two with no row in the label lookup - subrip and webvtt - answer a body under "
            "application/octet-stream rather than failing on it. The deprecated query parameters "
            "are bound and beat the address: ?format= changes the format, ?index= changes the "
            "track, and a start position in the query beats the one in the path. And the two "
            "routes do not name the same parameter for the same malformed identifier: the "
            "playlist route's problem details name itemId where the fetch route's name "
            "routeItemId, because each names its own path segment",
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
