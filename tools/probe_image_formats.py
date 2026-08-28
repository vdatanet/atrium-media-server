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

**Two cells were added on 2026-08-28**, when 006's plan gate measured them with scratch requests
and the task list refused to let the provenance depend on scripts nobody committed
(006 tasks T1, plan section 6.8 row 3):

* **the non-square fill battery.** The first version of this probe asked for a square fill box of
  a source that was itself square, where covering and cropping deliver the same pixels - so it
  reported "exactly the box" and the specification wrote down a crop that does not happen. A box
  off the source's ratio tells the two apart, and this probe now finds a poster whose sides
  differ before asking. `width`+`height` together rides the same battery, because it is the one
  path that is allowed to distort.
* **the `Accept` negotiation battery.** The offer was made once, on a request nothing transformed
  - and a request served verbatim negotiates nothing, so the measurement said "no negotiation"
  about a server that negotiates. The offer now rides a *transformed* request, a verbatim one, and
  one carrying an explicit `format`, plus `image/avif` for the format that is not negotiated.

A **third** battery came out of writing those two, and it was not owed by anybody: comparing the
delivered payload to the source's own bytes rather than to a byte *count*. The answer had been in
this probe's own output since the OQ-5 trial - `maxWidth=-100` returns 200, the source's
dimensions, the source's format and three times the source's bytes - and nobody had subtracted
the two numbers. A forgiven value is not a dropped value, and a bare `quality` is dropped where
the plan had it transforming. See 006 plan section 6.3 and behaviours section 1.17.

What this probe cannot see, and says so: a library with no PNG logo leaves the transparency
question unexercised - JPEG posters have no alpha channel to lose - and the probe reports which
half of the matrix its sample actually covered. The same is true of the fill battery on a library
whose posters are all square: it reports itself unexercised rather than guessing. Dimension
parsing reads the four container formats the reference serves (JPEG, PNG, WebP, GIF) and names
AVIF when it sees one; anything else is reported as unreadable rather than guessed at. EXIF
orientation stays out of reach entirely - it needs a planted file in a controlled library, and it
is owed to 010's differential (plan section 6.8 row 1).

Writes: nothing.

Usage:
    python3 tools/probe_image_formats.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import struct
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from _probe import Probe, ProbeError, Server, main

#: How many items to page through looking for a poster and a logo. A bound, not the library.
PAGE = 400

#: JPEG start-of-frame markers, the segments that carry dimensions.
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}

#: How many posters the fill battery will download looking for one whose sides differ. A bound,
#: not a library: a collection of square album covers has to end the search and say so.
NON_SQUARE_TRIES = 12

#: What an image loader in a browser offers. The token is what the reference reads (plan
#: section 6.4); the rest of the header is here so the request looks like the one clients send.
WEBP_OFFER = "image/webp,image/*;q=0.8,*/*;q=0.5"
AVIF_OFFER = "image/avif,image/*;q=0.8,*/*;q=0.5"

#: Delivered dimensions are compared with a pixel of slack per axis. The rounding rule at the
#: reference's scaler is not measured and is not what any of these cells is about - a crop and a
#: cover differ by hundreds of pixels, not by one.
SLACK = 1


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
    # AVIF is here to be recognised, not measured: the negotiation battery asks whether the
    # reference answers an `image/avif` offer with one, and "unknown" would be a weaker no.
    # Its dimensions live several boxes deep and nothing needs them.
    if payload[4:8] == b"ftyp" and payload[8:12] in (b"avif", b"avis"):
        return "avif", None, None, None
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


def find_items(server: Server) -> Tuple[Optional[str], Optional[str], List[str]]:
    """(an item with a Primary image, an item with a Logo image, every posterful item's id).

    The third value is what the fill battery searches: the first poster on the page may well be
    square, and a square source is the sample that produced the wrong answer the first time.
    """
    page = server.get("/Items", userId=server.user_id, Recursive="true", Limit=str(PAGE))
    poster: Optional[str] = None
    logo: Optional[str] = None
    posters: List[str] = []
    for item in (page or {}).get("Items") or []:
        tags = item.get("ImageTags") or {}
        if tags.get("Primary"):
            posters.append(item["Id"])
            if poster is None:
                poster = item["Id"]
        if logo is None and tags.get("Logo"):
            logo = item["Id"]
    return poster, logo, posters


def find_non_square(server: Server, posters: List[str]) -> Optional[Tuple[str, int, int]]:
    """The first poster whose sides differ, as `(item id, width, height)`, or None.

    Bounded by `NON_SQUARE_TRIES` downloads. Returning None is a real answer - "this library
    cannot exercise the fill rule" - and the probe reports it as unexercised rather than
    concluding anything from a square source, which is the mistake this battery exists to undo.
    """
    for item_id in posters[:NON_SQUARE_TRIES]:
        status, _headers, payload = fetch(server, f"/Items/{item_id}/Images/Primary")
        if status != 200:
            continue
        _kind, width, height, _alpha = sniff(payload)
        if width and height and width != height:
            return item_id, width, height
    return None


# --------------------------------------------------------------------------------------------
# The two batteries the plan gate measured by hand
# --------------------------------------------------------------------------------------------


class Verdicts:
    """One row per battery, so a probe with three claims does not have one opinion.

    `Probe` carries a single finding, which is right for a script that asks one question. This
    one now asks three - the error paths, the fill rule, the `Accept` rule - and each has its own
    documented claim to agree or disagree with. The rows are printed, and the probe's overall
    verdict is their conjunction: any battery that contradicts the specification fails the run.
    A battery this library could not exercise records nothing and says so instead.
    """

    def __init__(self) -> None:
        self.rows: List[Tuple[str, bool, str]] = []

    def record(self, battery: str, holds: bool, detail: str) -> None:
        self.rows.append((battery, holds, detail))

    def all_hold(self) -> bool:
        return all(holds for _, holds, _ in self.rows)

    def summary(self) -> str:
        return "; ".join(
            f"{battery}: {'as documented' if holds else 'CONTRADICTED'} - {detail}"
            for battery, holds, detail in self.rows
        )


def cover(width: int, height: int, box_width: int, box_height: int) -> Tuple[int, int]:
    """What `fillWidth`/`fillHeight` deliver under spec section 3.3's cover-and-keep rule.

    Scale to the larger of the two ratios, so the box is covered on both axes and the overflow
    rides along; capped at 1, because nothing upscales. The delivered size equals the box only
    when the source's ratio already matches it.
    """
    scale = min(max(box_width / width, box_height / height), 1.0)
    return round(width * scale), round(height * scale)


def fit(width: int, height: int, max_width: int) -> Tuple[int, int]:
    """What `maxWidth` delivers: inside the box, aspect intact, never upscaled."""
    scale = min(max_width / width, 1.0)
    return round(width * scale), round(height * scale)


def close(got: Tuple[Optional[int], Optional[int]], want: Tuple[int, int]) -> bool:
    got_width, got_height = got
    if got_width is None or got_height is None:
        return False
    return abs(got_width - want[0]) <= SLACK and abs(got_height - want[1]) <= SLACK


def fill_battery(
    probe: Probe, verdicts: Verdicts, server: Server, path: str, width: int, height: int
) -> None:
    """Does a fill box cover and keep the overflow, or crop to the box? (spec section 3.3, AC-6)

    Four cells, and the first is the one the earlier version of this probe already asked - the
    square box - now judged against the cover rule rather than against "exactly the box". The
    others are the box off the source's ratio, the box the source cannot cover, and the box
    composed with a `maxWidth`. `width`+`height` together rides along: it is the one path the
    specification allows to distort, and it is measured beside the paths that may not.
    """
    square = min(width, height) // 2 or 1
    off_ratio = (max(width // 4, 1), max(height // 2, 1))
    covered = cover(width, height, *off_ratio)
    narrower = max(covered[0] // 2, 1)
    exact = (max(width // 3, 1), max(height // 4, 1))

    cells = [
        (
            f"fillWidth={square}&fillHeight={square}",
            {"fillWidth": str(square), "fillHeight": str(square)},
            cover(width, height, square, square),
        ),
        (
            f"fillWidth={off_ratio[0]}&fillHeight={off_ratio[1]}  (off the source ratio)",
            {"fillWidth": str(off_ratio[0]), "fillHeight": str(off_ratio[1])},
            cover(width, height, *off_ratio),
        ),
        (
            f"fillWidth={width * 2}&fillHeight={height * 2}  (past the source)",
            {"fillWidth": str(width * 2), "fillHeight": str(height * 2)},
            (width, height),
        ),
        (
            f"fillWidth={off_ratio[0]}&fillHeight={off_ratio[1]}&maxWidth={narrower}",
            {
                "fillWidth": str(off_ratio[0]),
                "fillHeight": str(off_ratio[1]),
                "maxWidth": str(narrower),
            },
            fit(covered[0], covered[1], narrower),
        ),
        (
            f"width={exact[0]}&height={exact[1]}  (both axes, distorting)",
            {"width": str(exact[0]), "height": str(exact[1])},
            exact,
        ),
    ]

    disagreed = []
    for label, params, expected in cells:
        status, headers, payload = fetch(server, path, params)
        _kind, got_width, got_height, _alpha = sniff(payload)
        probe.observe(label, described(status, headers, payload))
        holds = status == 200 and close((got_width, got_height), expected)
        probe.observe(
            f"  expected {expected[0]}x{expected[1]}",
            "yes" if holds else "NO - the rule does not",
        )
        if not holds:
            asked = label.split("  ")[0]
            disagreed.append(
                f"{asked} -> {got_width}x{got_height}, not {expected[0]}x{expected[1]}"
            )

    verdicts.record(
        "fill",
        not disagreed,
        (
            f"every cell delivered the covered size on a {width}x{height} source"
            if not disagreed
            else "; ".join(disagreed)
        ),
    )


def accept_battery(
    probe: Probe, verdicts: Verdicts, server: Server, path: str, source_kind: str, half: int
) -> None:
    """Does the reference negotiate `Accept: image/webp`, and where? (spec section 3.3, AC-15)

    The cell that matters is the first: the offer on a request that **transforms**. The earlier
    version of this probe made the offer once, on a request nothing transformed, and read the
    source format coming back as "no negotiation" - which is why the plan's section 10 argued
    against content negotiation until the gate measured it the other way.
    """
    transformed = {"maxWidth": str(half)}
    cells = [
        ("resized, Accept offers webp", transformed, WEBP_OFFER, "webp"),
        ("verbatim, Accept offers webp", None, WEBP_OFFER, source_kind),
        (
            "resized with format=Png, Accept offers webp",
            {"maxWidth": str(half), "format": "Png"},
            WEBP_OFFER,
            "png",
        ),
        ("resized, Accept offers avif", transformed, AVIF_OFFER, source_kind),
    ]

    disagreed = []
    for label, params, offer, expected in cells:
        status, headers, payload = fetch(server, path, params, accept=offer)
        kind, _width, _height, _alpha = sniff(payload)
        probe.observe(label, described(status, headers, payload))
        probe.observe("  Vary", headers.get("Vary", "absent"))
        holds = status == 200 and kind == expected
        probe.observe("  expected " + expected, "yes" if holds else "NO - came back " + kind)
        if not holds:
            disagreed.append(f"{label} -> {kind}, not {expected}")

    # `Vary: Accept` rides every image response, negotiated or not (spec section 3.4). Read from
    # the verbatim cell, which is the response the header is least obviously about.
    _status, headers, _payload = fetch(server, path, accept=WEBP_OFFER)
    varies = "accept" in headers.get("Vary", "").lower()
    if not varies:
        disagreed.append("no Vary: Accept on an image response")

    verdicts.record(
        "Accept",
        not disagreed,
        (
            "a transformed response negotiates webp, a verbatim one does not, an explicit format "
            "beats the offer, avif is not negotiated, and Vary: Accept rides along"
            if not disagreed
            else "; ".join(disagreed)
        ),
    )


def verbatim_battery(
    probe: Probe,
    verdicts: Verdicts,
    server: Server,
    path: str,
    source: bytes,
    width: int,
    height: int,
) -> None:
    """Which requests come back as the source's own bytes? (006 plan section 6.3 step 5)

    Not one of the two cells the task list owed - this battery exists because the answer was
    already sitting in this probe's output and nobody had subtracted two numbers. The OQ-5 trial
    prints `maxWidth=-100  200  jpeg  800x800  282225B` three lines under
    `source, no parameters  200  jpeg  800x800  84351B`: same status, same dimensions, same
    format, and three times the bytes. A forgiven value is not a dropped value.

    The cells are the plan's verbatim conditions, compared by identity rather than by size, plus
    the one that is measurably not verbatim.
    """
    half = max(width // 2, 1)
    cells = [
        (f"maxWidth={width} (the source width)", {"maxWidth": str(width)}, True),
        (f"maxWidth={width * 4} (past the source)", {"maxWidth": str(width * 4)}, True),
        ("quality=90, nothing resized", {"quality": "90"}, True),
        (f"format=Svg&maxWidth={half}", {"format": "Svg", "maxWidth": str(half)}, True),
        ("maxWidth=-100 (forgiven, not dropped)", {"maxWidth": "-100"}, False),
    ]

    disagreed = []
    for label, params, expected in cells:
        status, headers, payload = fetch(server, path, params)
        _kind, got_width, got_height, _alpha = sniff(payload)
        identical = payload == source
        probe.observe(label, described(status, headers, payload))
        probe.observe(
            "  the source's own bytes",
            ("yes" if identical else "no, re-encoded") + ("" if identical == expected else "  <-"),
        )
        if identical != expected:
            disagreed.append(
                f"{label} -> {'verbatim' if identical else 're-encoded'}, expected the other"
            )
        if not expected and not close((got_width, got_height), (width, height)):
            disagreed.append(f"{label} -> {got_width}x{got_height}, not the source's size")

    verdicts.record(
        "verbatim",
        not disagreed,
        (
            "a resize the source cannot satisfy, a bare quality and format=Svg all serve the "
            "source's own bytes, and a non-positive value re-encodes at the source's size"
            if not disagreed
            else "; ".join(disagreed)
        ),
    )


# --------------------------------------------------------------------------------------------
# The probe
# --------------------------------------------------------------------------------------------


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_image_formats.py",
        question=(
            "what format comes back, does a fill box crop, and does a malformed parameter "
            "refuse or forgive?"
        ),
        document="specs/006-images/spec.md",
        section="section 3.2 error table, section 3.3 (OQ-3, OQ-5, AC-6, AC-15)",
        expectation=(
            "an unparseable dimension or quality is refused with 400 (section 3.2); a fill box "
            "covers and keeps the overflow rather than cropping (AC-6); a transformed response "
            "negotiates image/webp and a verbatim one does not (AC-15); and a request that "
            "changes nothing serves the source's own bytes (plan section 6.3 step 5)"
        ),
    )
    verdicts = Verdicts()

    poster, logo, posters = find_items(server)
    if poster is None:
        raise ProbeError("no item on this server carries a Primary image; nothing can be measured")
    path = f"/Items/{poster}/Images/Primary"

    # -- OQ-3: what comes back ---------------------------------------------------------------

    status, headers, original = fetch(server, path)
    if status != 200:
        raise ProbeError(f"GET {path} answered {status}; the baseline itself is unreadable")
    kind, width, height, _ = sniff(original)
    probe.observe("source, no parameters", described(status, headers, original))

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

    # -- AC-6: the fill rule, on a source that can tell cover from crop -----------------------

    shaped = find_non_square(server, posters)
    if shaped is None:
        probe.note(
            "AC-6: no poster among the first "
            + str(min(len(posters), NON_SQUARE_TRIES))
            + " has sides that differ, so the fill battery was not exercised. Covering and "
            "cropping deliver the same pixels on a square source - which is exactly how this "
            "probe's first version reported 'exactly the box' for a rule that keeps the "
            "overflow. Unexercised, not answered."
        )
    else:
        shaped_id, shaped_width, shaped_height = shaped
        shaped_path = f"/Items/{shaped_id}/Images/Primary"
        same = "the baseline poster" if shaped_id == poster else "another item"
        probe.observe("fill source", f"{shaped_width}x{shaped_height}, {same}")
        fill_battery(probe, verdicts, server, shaped_path, shaped_width, shaped_height)

    # -- AC-15: the Accept offer, on a request that transforms --------------------------------

    if width and height:
        accept_battery(probe, verdicts, server, path, kind, width // 2)
        verbatim_battery(probe, verdicts, server, path, original, width, height)
    else:
        probe.note(
            f"AC-15: the source dimensions were unreadable ({kind}), so no request could be "
            "guaranteed to transform and the negotiation battery was not exercised."
        )

    # -- OQ-5: the error paths --------------------------------------------------------------

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
    spelling = ", ".join(f"{label} -> {status}" for label, status in statuses.items())
    if all(status == 400 for status in unparseable):
        verdicts.record("error paths", True, "an unparseable dimension or quality is 400")
    elif any(status < 400 for status in unparseable):
        verdicts.record(
            "error paths",
            False,
            "an unparseable parameter is forgiven, not refused: "
            + spelling
            + " - the lenient pattern of behaviours section 1.12",
        )
    else:
        verdicts.record(
            "error paths",
            False,
            "an unparseable parameter is refused, but not with 400: " + spelling,
        )

    for battery, holds, detail in verdicts.rows:
        word = "as documented" if holds else "CONTRADICTED"
        probe.observe(f"verdict: {battery}", f"{word} - {detail}")

    probe.conclude(verdicts.summary(), matches_documentation=verdicts.all_hold())
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
