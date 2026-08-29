#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the two subtitle addresses answer: to a caller with no credential, to a window, to a
format the server cannot make, and to every way of naming a stream that is not there.

specs/011 §3.5 and §3.7, OQ-6, OQ-8 and OQ-11. Five batteries:

- **the credential** (OQ-6): both routes with no token, with an unknown token, with the token in
  the header and with it in the query string. The reference declares a requirement on one route
  and none on the other, and 008 T6 found the declared and the measured answers differ on
  exactly this class;
- **the playlist**: its whole text, the addresses it names, and what each entry answers when it
  is followed as written - which is 011 AC-8's traversal and the reason the fetch route is in
  this feature at all;
- **the window** (OQ-11): the two timestamp switches the playlist's own entries set, measured as
  the difference they make to the cues and to the first bytes of the body;
- **the formats**: every spelling a client can put in the address, including one the server
  cannot produce and one that turns the cue list into JSON;
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
    checks.extend(_format_battery(server, probe, address))
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
            "does not exist is a 200 whose every entry is a 500",
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
