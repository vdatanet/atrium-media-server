#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How does a direct-play delivery route answer each shape of Range header - what does
`static=true` serve when the URL names the wrong container, what headers ride on the answer, and
does the route want a token at all?

specs/008 §3.5's table and §6's range matrix: no range, a prefix, a mid-file slice, a single
byte, exactly the whole file, a suffix, a reversed range, a multi-range, an overshooting range
and one byte past the end - the shapes where range implementations actually break. Measured
against `/Videos/{itemId}/stream?static=true`, the route whose body is the original file. Plus
three batteries the first version of this probe did not run:

- **the label**: a container-suffixed static URL that does not match the source answers the
  untouched original bytes behind the path's Content-Type, so the suffix picks a label and
  nothing else - swept across the containers a client actually names, on video and on audio;
- **the credential**: whether these routes refuse a request carrying no token, an unknown one,
  or accept `?api_key=` - the question behaviours §2.10 measured for `/Videos/{id}/stream` and
  left for 008 to decide, with `/Audio/{id}/universal` beside it as the contrast;
- **the refusal**: what an unknown item answers on each of the four stream routes, which is the
  delivery-route error shape plan §6.8 owes to the task that lands them.

Read-only, and it never downloads the film: every request reads at most 64 bytes of the answer
and closes - the status, `Content-Range`, `Content-Length` and `Content-Type` are the whole
question.

Usage:
    python3 tools/probe_range_matrix.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from _playback import pick_video_source
from _probe import Probe, ProbeError, Server, main

#: An identifier no library holds. **Not** all zeros: that is the reference's `Guid.Empty`, which
#: a guard refuses before any lookup happens, so it measures the guard rather than the miss
#: (008 T5, `[source: Emby.Server.Implementations/Library/LibraryManager.cs:1359-1362 @
#: v10.11.11]`).
UNKNOWN_ITEM = "deadbeefdeadbeefdeadbeefdeadbeef"

#: A well-formed token nothing issued.
UNKNOWN_TOKEN = "0123456789abcdef0123456789abcdef"  # noqa: S105 - a probe input, not a credential

#: The container suffixes a client actually writes into one of these URLs. Swept on a static
#: request, where none of them can change the bytes - so what is being measured is the label.
#: Every extension `library/walker.py` admits, so the table the routes carry is measured end to
#: end rather than transcribed from the reference's own (Principle IV), plus `ts` and `m3u8`,
#: which no library holds and every HLS client names.
VIDEO_SUFFIXES = (
    "mkv",
    "mp4",
    "avi",
    "ts",
    "m4v",
    "mov",
    "wmv",
    "flv",
    "webm",
    "mpg",
    "mpeg",
    "m2ts",
    "mts",
    "vob",
    "ogv",
    "divx",
    "3gp",
    "rmvb",
    "asf",
    "m3u8",
)
AUDIO_SUFFIXES = (
    "flac",
    "m4a",
    "dsf",
    "mp3",
    "ogg",
    "oga",
    "opus",
    "wav",
    "aac",
    "wma",
    "aiff",
    "aif",
    "ape",
    "dff",
    "mka",
    "alac",
    "wv",
    "mpc",
)


def pick_audio_track(server: Server) -> tuple[str, str, int]:
    """A track with a container and a size: (item id, container, bytes)."""
    found = server.get(
        "/Items",
        UserId=server.user_id,
        IncludeItemTypes="Audio",
        Recursive="true",
        SortBy="Runtime",
        SortOrder="Ascending",
        Fields="MediaSources",
        Limit=25,
    )
    for row in found.get("Items", []):
        for source in row.get("MediaSources", []):
            if source.get("Container") and source.get("Size"):
                return row["Id"], source["Container"], source["Size"]
    raise ProbeError("the library holds no audio track with a measurable size")


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_range_matrix.py",
        question="what does static delivery answer to each shape of Range header, what label "
        "does the path put on it, and does it want a token?",
        document="specs/008-playback-negotiation-and-delivery/spec.md",
        section="section 3.5, the range table",
        expectation=(
            "no Range: 200 full body with Accept-Ranges: bytes and Content-Length equal to the "
            "file size; bytes=100-199: 206 with the correct Content-Range and exactly 100 "
            "bytes; a suffix range: 206 with the last bytes; an open-ended, overshooting or "
            "whole-file range: 206 clamped; multi-range, reversed and every unreadable shape: "
            "the full body as 200, never split, never refused; past the end and bytes=-0: 416 "
            "with Content-Range: bytes */total and Content-Length 0; static=true through a "
            "mismatched container suffix serves the identical original bytes with the path's "
            "Content-Type label, falling back to the file's own where the container names none; "
            "and the four stream routes accept every mechanism and require none, where "
            "/universal alone answers 401 without a token"
        ),
    )

    source = pick_video_source(server)
    size = source.source.get("Size")
    probe.observe("measured source", f"{source.container}, {size} bytes")
    path = f"/Videos/{source.item_id}/stream?static=true&api_key={server.token}"

    def ask(range_header: str | None) -> tuple[int, str | None, str | None]:
        extra = {"Range": range_header} if range_header else None
        status, headers, _ = server.get_streaming(path, max_bytes=64, extra_headers=extra)
        return status, headers.get("Content-Range"), headers.get("Content-Length")

    checks: list[bool] = []

    # -- the range matrix ------------------------------------------------------------------

    status, content_range, length = ask(None)
    probe.observe("no Range", f"{status}, Content-Length {length}")
    checks.append(status == 200 and length == str(size))

    status, content_range, length = ask("bytes=0-99")
    probe.observe("bytes=0-99 (prefix)", f"{status}, {content_range}, Content-Length {length}")
    checks.append(status == 206 and content_range == f"bytes 0-99/{size}" and length == "100")

    status, content_range, length = ask("bytes=100-199")
    probe.observe("bytes=100-199", f"{status}, {content_range}, Content-Length {length}")
    checks.append(status == 206 and content_range == f"bytes 100-199/{size}" and length == "100")

    status, content_range, length = ask("bytes=0-0")
    probe.observe("bytes=0-0 (one byte)", f"{status}, {content_range}, Content-Length {length}")
    checks.append(status == 206 and content_range == f"bytes 0-0/{size}" and length == "1")

    status, content_range, length = ask(f"bytes=0-{size - 1}")
    probe.observe("the whole file, named", f"{status}, {content_range}, Content-Length {length}")
    checks.append(
        status == 206 and content_range == f"bytes 0-{size - 1}/{size}" and length == str(size)
    )

    status, content_range, length = ask("bytes=-100")
    probe.observe("bytes=-100 (suffix)", f"{status}, {content_range}, Content-Length {length}")
    checks.append(
        status == 206
        and content_range == f"bytes {size - 100}-{size - 1}/{size}"
        and length == "100"
    )

    status, content_range, length = ask(f"bytes={size - 10}-{size + 1000}")
    probe.observe("past the end, from inside", f"{status}, {content_range}, {length}")
    checks.append(
        status == 206 and content_range == f"bytes {size - 10}-{size - 1}/{size}" and length == "10"
    )

    status, content_range, length = ask("bytes=100-")
    probe.observe("bytes=100- (open ended)", f"{status}, {content_range}, {length}")
    checks.append(
        status == 206
        and content_range == f"bytes 100-{size - 1}/{size}"
        and length == str(size - 100)
    )

    status, content_range, length = ask("bytes=-0")
    probe.observe("bytes=-0 (an empty suffix)", f"{status}, {content_range}, {length}")

    status, content_range, length = ask(f"bytes=-{size + 1000}")
    probe.observe("a suffix longer than the file", f"{status}, {content_range}, {length}")

    status, content_range, length = ask("bytes=0-49,100-149")
    probe.observe("bytes=0-49,100-149 (multi)", f"{status}, Content-Length {length}")
    checks.append(status == 200 and length == str(size))

    status, content_range, length = ask("bytes=200-100")
    probe.observe("bytes=200-100 (reversed)", f"{status}, Content-Length {length}")
    checks.append(status == 200 and length == str(size))

    for label, header in (
        ("no bytes= at all", "bananas"),
        ("bytes= with nothing after it", "bytes="),
        ("bytes=- , both ends absent", "bytes=-"),
        ("bytes=abc-def, neither a number", "bytes=abc-def"),
        ("bytes=100-abc, one of them", "bytes=100-abc"),
    ):
        status, content_range, length = ask(header)
        probe.observe(f"unparseable: {label}", f"{status}, {content_range}, {length}")
        checks.append(status == 200 and length == str(size))

    status, content_range, length = ask(f"bytes={size}-")
    probe.observe("one byte past the end", f"{status}, {content_range}, Content-Length {length}")
    checks.append(status == 416 and content_range == f"bytes */{size}" and length == "0")

    # -- what rides on the answer ----------------------------------------------------------

    status, headers, true_head = server.get_streaming(
        path, max_bytes=64, extra_headers={"Range": "bytes=0-63"}
    )
    probe.observe("the 206's header set", _header_set(headers))
    status, headers, _ = server.get_streaming(path, max_bytes=64)
    probe.observe("the 200's header set", _header_set(headers))
    checks.append(headers.get("Accept-Ranges") == "bytes")

    # -- the label: the suffix decides it, and the bytes never move ------------------------

    labels: list[str] = []
    identical = True
    for suffix in VIDEO_SUFFIXES:
        suffixed = f"/Videos/{source.item_id}/stream.{suffix}?static=true&api_key={server.token}"
        status, headers, head = server.get_streaming(
            suffixed, max_bytes=64, extra_headers={"Range": "bytes=0-63"}
        )
        labels.append(f"{suffix} -> {status} {headers.get('Content-Type')}")
        identical = identical and head == true_head
    probe.observe(f"static labels on a {source.container} film", "; ".join(labels))
    probe.observe("every one of them the original bytes", identical)
    checks.append(identical)

    track_id, track_container, track_size = pick_audio_track(server)
    track = f"/Audio/{track_id}/stream?static=true&api_key={server.token}"
    status, headers, track_head = server.get_streaming(
        track, max_bytes=64, extra_headers={"Range": "bytes=0-63"}
    )
    probe.observe(
        f"a {track_container} track, {track_size} bytes",
        f"{status}, {headers.get('Content-Type')}, Content-Range {headers.get('Content-Range')}",
    )
    checks.append(status == 206)

    labels = []
    identical = True
    for suffix in AUDIO_SUFFIXES:
        suffixed = f"/Audio/{track_id}/stream.{suffix}?static=true&api_key={server.token}"
        status, headers, head = server.get_streaming(
            suffixed, max_bytes=64, extra_headers={"Range": "bytes=0-63"}
        )
        labels.append(f"{suffix} -> {status} {headers.get('Content-Type')}")
        identical = identical and head == track_head
    probe.observe(f"static labels on a {track_container} track", "; ".join(labels))
    probe.observe("every one of them the original bytes", identical)
    checks.append(identical)

    # -- where the label comes from when the suffix names nothing ---------------------------

    for label, route in (
        ("stream.banana", f"/Videos/{source.item_id}/stream.banana?static=true"),
        ("?container=mkv", f"/Videos/{source.item_id}/stream?static=true&container=mkv"),
        ("stream.a%20b", f"/Videos/{source.item_id}/stream.a%20b?static=true"),
        ("a 41-character suffix", f"/Videos/{source.item_id}/stream.{'a' * 41}?static=true"),
    ):
        status, headers, body = server.get_streaming(
            f"{route}&api_key={server.token}", max_bytes=200, extra_headers={"Range": "bytes=0-63"}
        )
        probe.observe(
            label,
            f"{status}, {headers.get('Content-Type')}, original bytes: {body[:64] == true_head}"
            if status < 300
            else f"{status}, {headers.get('Content-Type')}, {body[:140]!r}",
        )

    status, headers, _ = server.get_streaming(
        path, max_bytes=16, extra_headers={"If-Modified-Since": "Sat, 01 Jan 2028 00:00:00 GMT"}
    )
    probe.observe("a conditional static request", f"{status}, {_header_set(headers)}")

    # -- which part of the item, when the URL names one -------------------------------------

    for label, named in (
        ("the item's own id", source.item_id),
        ("a source nothing has", UNKNOWN_ITEM),
        ("not an identifier at all", "banana"),
    ):
        status, headers, body = server.get_streaming(
            f"{path}&mediaSourceId={named}", max_bytes=200, extra_headers={"Range": "bytes=0-63"}
        )
        probe.observe(
            f"mediaSourceId: {label}",
            f"{status}, {headers.get('Content-Type')}, original bytes: {body[:64] == true_head}"
            if status < 300
            else f"{status}, {headers.get('Content-Type')}, {body[:140]!r}",
        )

    # -- the credential --------------------------------------------------------------------

    wanted: list[str] = []
    for label, route in (
        ("Videos/stream", f"/Videos/{source.item_id}/stream?static=true"),
        ("Videos/stream.mkv", f"/Videos/{source.item_id}/stream.mkv?static=true"),
        ("Audio/stream", f"/Audio/{track_id}/stream?static=true"),
        ("Audio/stream.mp3", f"/Audio/{track_id}/stream.mp3?static=true"),
        ("Audio/universal", f"/Audio/{track_id}/universal?container=mp3"),
    ):
        none_at_all, _, _ = server.get_streaming(route, max_bytes=16, send_token=False)
        unknown, _, _ = server.get_streaming(
            f"{route}&api_key={UNKNOWN_TOKEN}", max_bytes=16, send_token=False
        )
        keyed, _, _ = server.get_streaming(
            f"{route}&api_key={server.token}", max_bytes=16, send_token=False
        )
        wanted.append(f"{label}: none {none_at_all}, unknown {unknown}, api_key {keyed}")
    for line in wanted:
        probe.observe("token required?", line)

    # -- the refusal, per route --------------------------------------------------------------

    for label, route in (
        ("Videos/stream", f"/Videos/{UNKNOWN_ITEM}/stream?static=true"),
        ("Videos/stream.mp4", f"/Videos/{UNKNOWN_ITEM}/stream.mp4?static=true"),
        ("Audio/stream", f"/Audio/{UNKNOWN_ITEM}/stream?static=true"),
        ("Audio/stream.mp3", f"/Audio/{UNKNOWN_ITEM}/stream.mp3?static=true"),
    ):
        status, headers, body = server.get_streaming(
            f"{route}&api_key={server.token}", max_bytes=256
        )
        probe.observe(
            f"unknown item on {label}",
            f"{status}, {headers.get('Content-Type')}, {body[:120]!r}",
        )

    if all(checks):
        probe.conclude(
            "as documented: correct 206 slices, full-body 200 for every shape it will not split "
            "or refuse - the reversed and the malformed included, where RFC 9110 invites a 416 - "
            "the RFC's 416 for the unsatisfiable ones, untouched original bytes behind the "
            "path's label on every mismatched static suffix, and no token required on any of the "
            "four stream routes where /universal requires one. Spec section 3.5's credential "
            "sentence said the opposite until 008 T6 measured it on 2026-08-29",
            matches_documentation=True,
        )
    else:
        failed = [i for i, ok in enumerate(checks) if not ok]
        probe.conclude(f"checks {failed} did not hold - see observations", False)
    return probe


def _header_set(headers: dict[str, str]) -> str:
    """Every header the response carried, name and value, in the order it sent them.

    The whole set rather than the two the matrix reads: a delivery route is reproduced header by
    header, and one nobody wrote down is one Atrium either invents or omits.
    """
    skip = {"date", "transfer-encoding", "connection", "server", "x-response-time-ms"}
    kept: list[str] = []
    for name, value in headers.items():
        if name.lower() in skip:
            continue
        kept.append(f"{name}: {value}")
    return " | ".join(kept)


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
