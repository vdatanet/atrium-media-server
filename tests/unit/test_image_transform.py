# SPDX-License-Identifier: GPL-3.0-or-later
"""Spec §3.3's resize and format matrix, as a table of values.

This is the whole payoff of `images/transform.py` being pure: every cell the reference was
measured on is a row here, with the request's numbers on the left and the delivered size on the
right, and nothing in between needs a database, a file or a request object.

**Each row names the measurement it reproduces.** The three that overturned the plan's draft —
fill covers rather than crops, a transformed response negotiates WebP, and a bare `quality` is
not a transform — are marked, because a table of numbers with no provenance is a table somebody
will "correct" from first principles.

`[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from atrium.images.transform import (
    FORMAT_PARAMETER,
    RequestedFormat,
    Source,
    TransformSpec,
    decide,
    describe,
    render,
)
from tests.fixtures.images import BACKDROP_SIZES, POSTER_SIZE, SMALL_SIZE, drawn

#: The 2:3 poster every geometry row is written against, as a value.
POSTER = Source(width=POSTER_SIZE[0], height=POSTER_SIZE[1], image_format="JPEG", has_alpha=False)

#: The 400x600 source, for the never-upscale rows.
SMALL = Source(width=SMALL_SIZE[0], height=SMALL_SIZE[1], image_format="JPEG", has_alpha=False)

#: The PNG logo, whose alpha is what AC-7 is about.
LOGO = Source(width=600, height=200, image_format="PNG", has_alpha=True)


def spec(**values: object) -> TransformSpec:
    return TransformSpec(**values)  # type: ignore[arg-type]


def decoded(payload: bytes) -> Image.Image:
    return Image.open(io.BytesIO(payload))


# ------------------------------------------------------------------------------------------
# The geometry table — spec §3.3, plan §6.3
# ------------------------------------------------------------------------------------------

#: `(label, source, request, delivered size)`. Every row is a measured cell or the arithmetic the
#: measured cells pinned down.
GEOMETRY = [
    # -- fit: maxWidth / maxHeight ---------------------------------------------------------
    ("maxWidth=300 of 1000x1500", POSTER, {"max_width": 300}, (300, 450)),
    ("maxHeight=300 of 1000x1500", POSTER, {"max_height": 300}, (200, 300)),
    ("both, the tighter one wins", POSTER, {"max_width": 500, "max_height": 300}, (200, 300)),
    ("maxWidth past the source", POSTER, {"max_width": 4000}, POSTER.size),
    ("AC-5: 2000 of a 400px source", SMALL, {"max_width": 2000}, SMALL.size),
    # -- fill: covers, keeps the overflow, never crops (AC-6, measured) ---------------------
    ("AC-6: fill 300x300 covers", POSTER, {"fill_width": 300, "fill_height": 300}, (300, 450)),
    (
        "AC-6: fill 500x1500, off the ratio",
        Source(2000, 3000, "JPEG", False),
        {"fill_width": 500, "fill_height": 1500},
        (1000, 1500),
    ),
    (
        "AC-6: a box the source cannot cover",
        POSTER,
        {"fill_width": 4000, "fill_height": 6000},
        POSTER.size,
    ),
    ("a lone fill axis scales that axis", POSTER, {"fill_width": 500}, (500, 750)),
    (
        "fill composed with maxWidth: the tightest aspect-true size",
        Source(2000, 3000, "JPEG", False),
        {"fill_width": 500, "fill_height": 1500, "max_width": 500},
        (500, 750),
    ),
    # -- exact: width / height -------------------------------------------------------------
    ("width and height together distort", POSTER, {"width": 300, "height": 300}, (300, 300)),
    ("a lone width keeps the ratio", POSTER, {"width": 300}, (300, 450)),
    ("a lone height keeps the ratio", POSTER, {"height": 300}, (200, 300)),
    # **The exact path upscales**, measured, where every box parameter is capped at the source.
    # Asking for a box means at most; asking for a dimension means exactly.
    (
        "width and height past the source are honoured",
        SMALL,
        {"width": 4000, "height": 4000},
        (4000, 4000),
    ),
    ("a lone width past the source upscales, ratio intact", SMALL, {"width": 4000}, (4000, 6000)),
    ("a lone height past the source upscales too", SMALL, {"height": 6000}, (4000, 6000)),
    (
        "maxWidth caps the exact size afterwards",
        SMALL,
        {"width": 4000, "max_width": 200},
        (200, 300),
    ),
    # -- step 1: non-positive values are forgiven and dropped -------------------------------
    ("maxWidth=-100 changes nothing", POSTER, {"max_width": -100}, POSTER.size),
    ("maxWidth=0 changes nothing", POSTER, {"max_width": 0}, POSTER.size),
    ("a dropped axis leaves the other", POSTER, {"max_width": -100, "max_height": 300}, (200, 300)),
]


@pytest.mark.parametrize(
    "label,source,request_values,delivered",
    GEOMETRY,
    ids=[row[0] for row in GEOMETRY],
)
def test_the_delivered_size_is_the_measured_one(
    label: str,
    source: Source,
    request_values: dict[str, int],
    delivered: tuple[int, int],
) -> None:
    assert decide(spec(**request_values), source).target == delivered, label


@pytest.mark.parametrize(
    "label,source,request_values,delivered",
    [row for row in GEOMETRY if row[3] == row[1].size],
    ids=[row[0] for row in GEOMETRY if row[3] == row[1].size],
)
def test_a_request_that_changes_no_size_is_verbatim(
    label: str,
    source: Source,
    request_values: dict[str, int],
    delivered: tuple[int, int],
) -> None:
    """The anchor of plan §1: if the target equals the source and the format does not change,
    the carrier's own bytes go out. Every "unchanged" row of the table above is one of these."""
    assert decide(spec(**request_values), source).verbatim, label


# ------------------------------------------------------------------------------------------
# The format table — spec §3.3, plan §6.4
# ------------------------------------------------------------------------------------------

#: `(label, source format, requested format, webp offered, a resize asked for, resolved)`.
FORMATS = [
    ("the source format survives a resize", "JPEG", None, False, True, "JPEG"),
    ("a PNG resizes to PNG", "PNG", None, False, True, "PNG"),
    ("explicit Jpg", "PNG", RequestedFormat.JPG, False, True, "JPEG"),
    ("explicit Png", "JPEG", RequestedFormat.PNG, False, True, "PNG"),
    ("explicit Webp", "JPEG", RequestedFormat.WEBP, False, True, "WEBP"),
    ("AC-15: the offer on a transformed request", "JPEG", None, True, True, "WEBP"),
    ("AC-15: the offer on a verbatim request", "JPEG", None, True, False, "JPEG"),
    ("AC-15: an explicit format beats the offer", "JPEG", RequestedFormat.PNG, True, True, "PNG"),
    ("Bmp falls back to the source format", "JPEG", RequestedFormat.BMP, False, True, "JPEG"),
    ("Gif falls back too", "PNG", RequestedFormat.GIF, False, True, "PNG"),
    # An unencodable *explicit* format still beats the offer: the client named one, and the
    # fallback is to the source rather than to whatever `Accept` suggested.
    (
        "Gif beats the webp offer, falling back to the source",
        "JPEG",
        RequestedFormat.GIF,
        True,
        True,
        "JPEG",
    ),
]


@pytest.mark.parametrize(
    "label,source_format,asked,offered,resizing,resolved",
    FORMATS,
    ids=[row[0] for row in FORMATS],
)
def test_the_resolved_format_is_the_measured_one(
    label: str,
    source_format: str,
    asked: RequestedFormat | None,
    offered: bool,
    resizing: bool,
    resolved: str,
) -> None:
    source = Source(1000, 1500, source_format, has_alpha=False)
    decision = decide(
        spec(
            image_format=asked,
            accepts_webp=offered,
            **({"max_width": 300} if resizing else {}),
        ),
        source,
    )
    assert decision.image_format == resolved, label


def test_svg_short_circuits_the_whole_request() -> None:
    """Measured: an 800px source came back whole against `maxWidth=200`. `Svg` is not a fallback
    like `Bmp` and `Gif` — the resize is ignored, not applied."""
    decision = decide(spec(image_format=RequestedFormat.SVG, max_width=200), POSTER)

    assert decision.verbatim
    assert decision.target == POSTER.size
    assert decision.image_format == "JPEG"


def test_an_unencodable_format_is_recorded_as_a_drop() -> None:
    """behaviours §1.12's pattern: the value is forgiven and counted, never refused.

    OQ-4's trail is the same mechanism, and this is the one place a *value* rather than a whole
    parameter is what gets dropped."""
    decision = decide(spec(image_format=RequestedFormat.BMP, max_width=300), POSTER)

    assert decision.dropped == (f"{FORMAT_PARAMETER}=Bmp",), "the value, not the parameter"
    assert decision.image_format == "JPEG", "the transform still runs (measured)"
    assert decision.target == (300, 450)


def test_a_format_that_encodes_is_not_recorded_as_a_drop() -> None:
    assert decide(spec(image_format=RequestedFormat.PNG, max_width=300), POSTER).dropped == ()


# ------------------------------------------------------------------------------------------
# quality
# ------------------------------------------------------------------------------------------


def test_a_bare_quality_is_not_a_transform() -> None:
    """behaviours §1.17, measured: `quality=90` with nothing resized comes back byte-identical to
    the file. The plan's draft made a bare `quality` a reason to re-encode, which would have
    re-encoded every poster for the clients that append one out of habit."""
    decision = decide(spec(quality=90), POSTER)

    assert decision.verbatim
    assert decision.quality is None


@pytest.mark.parametrize("asked,clamped", [(0, 0), (50, 50), (100, 100), (150, 100), (-20, 0)])
def test_quality_clamps_rather_than_refusing(asked: int, clamped: int) -> None:
    """`quality=150` is forgiven with `200`, measured — so it clamps."""
    decision = decide(spec(quality=asked, max_width=300), POSTER)

    assert decision.quality == clamped


def test_quality_is_ignored_for_png_whose_encoder_has_no_lossy_knob() -> None:
    decision = decide(spec(quality=50, max_width=300, image_format=RequestedFormat.PNG), POSTER)

    assert decision.quality is None


# ------------------------------------------------------------------------------------------
# The encoder, over the drawn bytes
# ------------------------------------------------------------------------------------------


def test_the_source_is_described_from_its_header() -> None:
    art = drawn()
    poster = describe(art.poster)
    logo = describe(art.logo)

    assert poster is not None and (poster.size, poster.image_format) == (POSTER_SIZE, "JPEG")
    assert logo is not None and logo.image_format == "PNG" and logo.has_alpha


def test_bytes_that_are_not_an_image_describe_as_nothing() -> None:
    assert describe(b"this is not an image") is None


def test_ac4_a_resized_poster_decodes_to_the_size_that_was_decided() -> None:
    art = drawn()
    source = describe(art.poster)
    assert source is not None
    decision = decide(spec(max_width=300), source)

    rendered = render(art.poster, decision, source)

    assert decoded(rendered.payload).size == (300, 450)
    assert rendered.media_type == "image/jpeg"


def test_ac7_alpha_survives_every_implicit_path() -> None:
    """A resized logo keeps its channel. Transparency is never discarded implicitly — a logo
    silently served as JPEG acquires a white box, visible on any dark client theme."""
    art = drawn()
    source = describe(art.logo)
    assert source is not None
    decision = decide(spec(max_width=300), source)

    rendered = render(art.logo, decision, source)
    result = decoded(rendered.payload)

    assert rendered.media_type == "image/png"
    assert result.mode in ("RGBA", "LA", "PA")
    assert result.getchannel("A").getextrema()[0] == 0, "still transparent somewhere"


def test_ac7_an_explicit_jpg_flattens_the_alpha_onto_white() -> None:
    """Measured: the transparent logo comes back opaque under `format=Jpg`. Refusing what the
    client asked for by name would be the real divergence."""
    art = drawn()
    source = describe(art.logo)
    assert source is not None
    decision = decide(spec(max_width=300, image_format=RequestedFormat.JPG), source)

    rendered = render(art.logo, decision, source)
    result = decoded(rendered.payload)

    assert rendered.media_type == "image/jpeg"
    assert result.mode == "RGB"
    assert result.convert("RGB").getpixel((5, 5)) == pytest.approx((255, 255, 255), abs=8)


def test_the_negotiated_webp_really_encodes_as_webp() -> None:
    art = drawn()
    source = describe(art.poster)
    assert source is not None
    decision = decide(spec(max_width=300, accepts_webp=True), source)

    rendered = render(art.poster, decision, source)

    assert decoded(rendered.payload).format == "WEBP"
    assert rendered.media_type == "image/webp"


def test_a_verbatim_decision_returns_the_source_bytes_untouched() -> None:
    art = drawn()
    source = describe(art.small)
    assert source is not None
    decision = decide(spec(max_width=2000), source)

    rendered = render(art.small, decision, source)

    assert rendered.payload is art.small
    assert rendered.size == SMALL_SIZE


def test_a_decode_failure_serves_the_source_rather_than_raising() -> None:
    """Plan §7: a full-size poster beats a hole in the grid, and the bytes were good enough to
    associate. Never a `5xx`, and never an exception the route has to know about."""
    truncated = drawn().poster[:64]
    source = describe(drawn().poster)
    assert source is not None
    decision = decide(spec(max_width=300), source)

    rendered = render(truncated, decision, source)

    assert rendered.fell_back
    assert rendered.payload == truncated
    assert rendered.media_type == "image/jpeg"


def test_a_decompression_bomb_serves_the_source_rather_than_raising() -> None:
    """Pillow's own guard, which raises rather than returning: the same fallback covers it."""
    bomb = io.BytesIO()
    Image.new("RGB", (2, 2)).save(bomb, format="PNG")
    payload = bomb.getvalue()
    source = describe(payload)
    assert source is not None

    limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 1
    try:
        rendered = render(payload, decide(spec(width=1, height=1), source), source)
    finally:
        Image.MAX_IMAGE_PIXELS = limit

    assert rendered.fell_back
    assert rendered.payload == payload


# ------------------------------------------------------------------------------------------
# The cache key's transform half (plan §4)
# ------------------------------------------------------------------------------------------


def test_the_key_parts_change_with_geometry_format_and_quality_and_only_then() -> None:
    """A negotiated WebP and a bare JPEG of the same geometry are two entries, which is what the
    resolved format being *inside* the key buys."""
    base = decide(spec(max_width=300), POSTER)
    negotiated = decide(spec(max_width=300, accepts_webp=True), POSTER)
    smaller = decide(spec(max_width=200), POSTER)
    rougher = decide(spec(max_width=300, quality=10), POSTER)

    keys = {
        base.cache_key_parts,
        negotiated.cache_key_parts,
        smaller.cache_key_parts,
        rougher.cache_key_parts,
    }
    assert len(keys) == 4

    assert base.cache_key_parts == decide(spec(max_width=300), POSTER).cache_key_parts


def test_two_requests_for_the_same_size_by_different_routes_share_a_key() -> None:
    """`maxWidth=300` and `width=300` deliver the same 300x450 of this source, so they are one
    cache entry. The key is the *decision*, not the request."""
    assert (
        decide(spec(max_width=300), POSTER).cache_key_parts
        == decide(spec(width=300), POSTER).cache_key_parts
    )


def test_the_backdrops_are_distinguishable_by_the_sizes_the_fixture_draws() -> None:
    """The property T9's index tests lean on, asserted where the sizes are decided."""
    assert len(set(BACKDROP_SIZES)) == 3
