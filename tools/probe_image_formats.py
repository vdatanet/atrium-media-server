#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What format does a resized image come back in, and does a malformed parameter refuse or forgive?

Answers 006 OQ-3 and OQ-5. The verdict is OQ-5's, because it is the one with a claim to
contradict: the error table of specs/006 section 3.2 says an unparseable dimension or quality is
refused with `400` - marked UNVERIFIED there precisely because every error path measured so far
leans the other way (an unrecognised enum token is ignored, not refused, behaviours section 1.12).
Whichever way this measurement lands, the table stops being an assumption.

OQ-3 - the format-selection rule - is measured by looking at what actually comes back: the
`Content-Type` and the first bytes of the payload, decoded just far enough to read the container's
own declaration of format, dimensions and alpha channel. That covers the source format untouched,
the format after a resize, an explicit `format=` in three spellings, whether `quality` moves the
byte count, whether `fillWidth`/`fillHeight` crop to exactly the box, and - section 3.3's sharpest
claim - whether an image with transparency survives in a format that keeps it. The same header
parse answers upscaling: a request for four times the source width either comes back source-sized
or it does not.

What this probe cannot see, and says so: a library with no PNG logo leaves the transparency
question unexercised - JPEG posters have no alpha channel to lose - and the probe reports which
half of the matrix its sample actually covered. Dimension parsing reads the four container
formats the reference serves (JPEG, PNG, WebP, GIF); anything else is reported as unreadable
rather than guessed at.

Writes: nothing.

Usage:
    python3 tools/probe_image_formats.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import struct
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

from _probe import Probe, ProbeError, Server, main

#: How many items to page through looking for a poster and a logo. A bound, not the library.
PAGE = 400

#: JPEG start-of-frame markers, the segments that carry dimensions.
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


# --------------------------------------------------------------------------------------------
# Reading what the payload says about itself
# --------------------------------------------------------------------------------------------


def sniff(payload: bytes) -> Tuple[str, Optional[int], Optional[int], Optional[bool]]:
    """(kind, width, height, has_alpha) from the container's own header; Nones when unreadable.

    PNG alpha is the colour type's word (an alpha channel, types 4 and 6); a palette image made
    transparent by a tRNS chunk would read as opaque here, which is why a False is reported as
    what the header *declares* rather than as ground truth.
    """
    if payload[:8] == b"\x89PNG\r\n\x1a\n" and len(payload) >= 26:
        width, height = struct.unpack(">II", payload[16:24])
        return "png", width, height, payload[25] in (4, 6)
    if payload[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(payload):
            if payload[i] != 0xFF:
                break
            marker = payload[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in SOF:
                height, width = struct.unpack(">HH", payload[i + 5 : i + 9])
                return "jpeg", width, height, False
            if 0xD0 <= marker <= 0xD9 or marker == 0x01:
                i += 2
                continue
            (length,) = struct.unpack(">H", payload[i + 2 : i + 4])
            i += 2 + length
        return "jpeg", None, None, False
    if payload[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", payload[6:10])
        return "gif", width, height, None
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP" and len(payload) >= 30:
        chunk = payload[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(payload[24:27], "little")
            height = 1 + int.from_bytes(payload[27:30], "little")
            return "webp", width, height, bool(payload[20] & 0x10)
        if chunk == b"VP8L" and payload[20] == 0x2F:
            bits = int.from_bytes(payload[21:25], "little")
            return "webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1, bool(bits >> 28 & 1)
        if chunk == b"VP8 " and payload[23:26] == b"\x9d\x01\x2a":
            (width,) = struct.unpack("<H", payload[26:28])
            (height,) = struct.unpack("<H", payload[28:30])
            return "webp", width & 0x3FFF, height & 0x3FFF, False
        return "webp", None, None, None
    return "unknown", None, None, None


def described(status: int, headers: dict, payload: bytes) -> str:
    kind, width, height, alpha = sniff(payload)
    size = f"{width}x{height}" if width else "?"
    alpha_word = {True: "alpha", False: "opaque", None: ""}[alpha]
    parts = [str(status), headers.get("Content-Type", "none"), kind, size, alpha_word]
    return "  ".join(part for part in parts if part) + f"  {len(payload)}B"


# --------------------------------------------------------------------------------------------
# Requests that ask for an image the way an image loader would
# --------------------------------------------------------------------------------------------


def fetch(
    server: Server,
    path: str,
    params: Optional[Dict[str, str]] = None,
    accept: str = "*/*",
) -> Tuple[int, Dict[str, str], bytes]:
    """GET with `Accept` under the caller's control, because the answer varies on it.

    The reference sends `Vary: Accept` on its image responses, so a measurement made with the
    shared client's `Accept: application/json` would be a measurement of a request no image
    loader ever sends. The default here is the loader's `*/*`; OQ-3's negotiation trial passes
    an Accept that offers WebP instead.
    """
    url = server.base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": accept}
    if server.token:
        headers["X-Emby-Token"] = server.token
    # S310: the URL is the operator's own server, given on the command line or in .env.
    request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=server.timeout) as response:  # noqa: S310
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except urllib.error.URLError as exc:
        raise ProbeError(f"GET {path} -> {exc.reason}") from exc


# --------------------------------------------------------------------------------------------
# Finding something to measure
# --------------------------------------------------------------------------------------------


def find_items(server: Server) -> Tuple[Optional[str], Optional[str]]:
    """(an item with a Primary image, an item with a Logo image), either of which may be None."""
    page = server.get("/Items", userId=server.user_id, Recursive="true", Limit=str(PAGE))
    poster: Optional[str] = None
    logo: Optional[str] = None
    for item in (page or {}).get("Items") or []:
        tags = item.get("ImageTags") or {}
        if poster is None and tags.get("Primary"):
            poster = item["Id"]
        if logo is None and tags.get("Logo"):
            logo = item["Id"]
        if poster and logo:
            break
    return poster, logo


# --------------------------------------------------------------------------------------------
# The probe
# --------------------------------------------------------------------------------------------


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_image_formats.py",
        question="what format comes back, and does a malformed parameter refuse or forgive?",
        document="specs/006-images/spec.md",
        section="section 3.2 error table (OQ-3, OQ-5)",
        expectation="an unparseable dimension or quality is refused with 400",
    )

    poster, logo = find_items(server)
    if poster is None:
        raise ProbeError("no item on this server carries a Primary image; nothing can be measured")
    path = f"/Items/{poster}/Images/Primary"

    # -- OQ-3: what comes back ---------------------------------------------------------------

    status, headers, original = fetch(server, path)
    if status != 200:
        raise ProbeError(f"GET {path} answered {status}; the baseline itself is unreadable")
    kind, width, height, _ = sniff(original)
    probe.observe("source, no parameters", described(status, headers, original))

    status, headers, offered = fetch(server, path, accept="image/webp,image/*;q=0.8,*/*;q=0.5")
    probe.observe("same, Accept offering webp", described(status, headers, offered))
    if headers.get("Vary"):
        probe.observe("  Vary", headers["Vary"])

    if width and height:
        half = width // 2
        status, headers, resized = fetch(server, path, {"maxWidth": str(half)})
        r_kind, r_width, r_height, _ = sniff(resized)
        probe.observe(f"maxWidth={half}", described(status, headers, resized))
        if r_width and r_height:
            held = abs(r_width / r_height - width / height) < 0.02
            probe.observe("  aspect ratio preserved", "yes" if held else "NO")
            if r_kind != kind:
                probe.note(f"OQ-3: resizing re-encodes - {kind} source came back as {r_kind}.")

        status, headers, enlarged = fetch(server, path, {"maxWidth": str(width * 4)})
        _, e_width, _, _ = sniff(enlarged)
        probe.observe(f"maxWidth={width * 4}", described(status, headers, enlarged))
        if e_width:
            grew = e_width > width
            probe.observe("  upscaled past the source", "YES" if grew else "no")

        box = min(width, height) // 2 or 1
        square = {"fillWidth": str(box), "fillHeight": str(box)}
        status, headers, filled = fetch(server, path, square)
        _, f_width, f_height, _ = sniff(filled)
        probe.observe(f"fillWidth={box}&fillHeight={box}", described(status, headers, filled))
        if f_width:
            exact = (f_width, f_height) == (box, box)
            probe.observe("  exactly the box", "yes" if exact else "NO")

        _, _, rough = fetch(server, path, {"maxWidth": str(half), "quality": "10"})
        moved = len(rough) != len(resized)
        probe.observe("quality=10 at the same width", f"{len(rough)}B, {len(resized)}B unqualified")
        probe.observe("  quality moves the byte count", "yes" if moved else "NO")
    else:
        probe.note(f"the source dimensions were unreadable ({kind}); the resize matrix skipped.")

    for wanted in ("Png", "Jpg", "Webp"):
        status, headers, payload = fetch(server, path, {"format": wanted})
        probe.observe(f"format={wanted}", described(status, headers, payload))

    if logo is not None:
        logo_path = f"/Items/{logo}/Images/Logo"
        status, headers, payload = fetch(server, logo_path)
        l_kind, l_width, _, l_alpha = sniff(payload)
        probe.observe("logo, no parameters", described(status, headers, payload))
        if l_alpha:
            if l_width:
                status, headers, payload = fetch(server, logo_path, {"maxWidth": str(l_width // 2)})
                _, _, _, kept = sniff(payload)
                probe.observe("logo resized", described(status, headers, payload))
                probe.observe("  transparency survives a resize", "yes" if kept else "NO")
            status, headers, payload = fetch(server, logo_path, {"format": "Jpg"})
            probe.observe("logo with format=Jpg", described(status, headers, payload))
        else:
            probe.note(
                f"OQ-3: the one logo found declares no alpha channel ({l_kind}), so whether "
                "transparency survives was not exercised on this library."
            )
    else:
        probe.note(
            "OQ-3: no sampled item carries a Logo, so the transparency half of the format rule "
            "was not exercised; the question needs a library with a PNG logo."
        )

    # -- OQ-5: the error paths, which are the verdict ----------------------------------------

    trials = [
        ("maxWidth=banana", {"maxWidth": "banana"}),
        ("quality=banana", {"quality": "banana"}),
        ("maxWidth=-100", {"maxWidth": "-100"}),
    ]
    statuses = {}
    for label, params in trials:
        status, headers, payload = fetch(server, path, params)
        statuses[label] = status
        probe.observe(label, described(status, headers, payload))

    status, _, payload = fetch(server, f"/Items/{poster}/Images/Box")
    probe.observe("imageType absent (Box)", f"{status}  {len(payload)}B")
    status, _, payload = fetch(server, f"/Items/{poster}/Images/NotAnImageType")
    probe.observe("imageType outside the enum", f"{status}  {len(payload)}B")

    unparseable = [statuses["maxWidth=banana"], statuses["quality=banana"]]
    if all(status == 400 for status in unparseable):
        probe.conclude(
            "an unparseable dimension or quality is refused with 400, as the error table says",
            matches_documentation=True,
        )
    elif any(status < 400 for status in unparseable):
        probe.conclude(
            "an unparseable parameter is forgiven, not refused: "
            + ", ".join(f"{label} -> {status}" for label, status in statuses.items())
            + " - the lenient pattern of behaviours section 1.12, and the error table's 400 "
            "does not hold",
            matches_documentation=False,
        )
    else:
        probe.conclude(
            "an unparseable parameter is refused, but not with 400: "
            + ", ".join(f"{label} -> {status}" for label, status in statuses.items()),
            matches_documentation=False,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
