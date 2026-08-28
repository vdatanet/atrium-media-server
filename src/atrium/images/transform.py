# SPDX-License-Identifier: GPL-3.0-or-later
"""What size and what format the reply should be, and the encoder that produces it.

Two halves, and the first is pure arithmetic. `decide` takes the request's numbers and what the
source is, and answers with a `Decision` — a target size, a resolved output format, a quality, and
whether any of that is a change at all. `render` is the only thing here that touches a pixel.

**The verbatim answer is the anchor** (006 plan section 1). A request that changes nothing — the
computed target equals the source and the resolved format equals the source's — answers the
carrier's bytes as they sit on disk, which is what makes byte-identity across a cache hit
(AC-8) and across a deleted cache (AC-13) true by construction rather than by an encoder being
deterministic.

Every rule below was measured, and three of them measured differently from how the plan's draft
had them `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`:

* **`fillWidth`/`fillHeight` cover the box and keep the overflow.** They do not crop. A 500x1500
  box of a 2000x3000 poster comes back **1000x1500** - not the box, and not the fit.
* **A transformed response negotiates `Accept: image/webp`**; a verbatim one negotiates nothing,
  and an explicit `format` beats the offer.
* **A bare `quality` is not a transform.** `quality=90` with nothing to resize comes back
  byte-identical to the file; `quality` moves the byte count only once something else has already
  put the request on the encoder (behaviours section 1.17).
* **"Never upscale" is a property of three parameters, not of the server.** `maxWidth`,
  `maxHeight` and the fill pair are capped at the source; `width` and `height` are honoured past
  it - `width=4000` of a 2000x3000 source measured 4000x6000. Asking for a box means *at most*;
  asking for a dimension means *exactly*
  `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`.

**Nothing here imports HTTP or the database**, and a test asserts it: the `Accept` offer arrives
as a boolean, the source's dimensions arrive as numbers, and the whole matrix of spec section 3.3
is therefore a table of values.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from enum import StrEnum

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


class RequestedFormat(StrEnum):
    """The reference's `ImageFormat`, all six members `[spec: ImageFormat]`.

    All six **parse**; three of them encode. `Bmp` and `Gif` fall back to the source format with
    the transform still applied - `format=Bmp` at `maxWidth=200` measured a 200px JPEG out of a
    JPEG source - and `Svg` short-circuits the request to verbatim, measured on an 800px source
    that came back whole against `maxWidth=200`.
    """

    BMP = "Bmp"
    GIF = "Gif"
    JPG = "Jpg"
    PNG = "Png"
    WEBP = "Webp"
    SVG = "Svg"


#: The three the reference measurably encodes, mapped to Pillow's own format names.
ENCODABLE: dict[RequestedFormat, str] = {
    RequestedFormat.JPG: "JPEG",
    RequestedFormat.PNG: "PNG",
    RequestedFormat.WEBP: "WEBP",
}

#: What each format is called on the wire. `Content-Type` comes from the payload that is served,
#: never from a file extension (plan section 5).
MEDIA_TYPES: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}

#: What a cache entry of each format is called on disk (plan section 4): the extension is the
#: output format, so a hit recovers its `Content-Type` without sniffing the bytes again.
EXTENSIONS: dict[str, str] = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
    "GIF": "gif",
    "BMP": "bmp",
    "TIFF": "tiff",
}

#: Served when the bytes are not an image this build can identify at all. 004 refuses to associate
#: such a file, so reaching this means the file changed under a row that still names it - and the
#: bytes go out either way (plan section 7). ⚠️ **Unmeasured**: no request could make the reference
#: serve a file it had itself refused to catalogue.
UNKNOWN_MEDIA_TYPE = "application/octet-stream"

#: The parameter whose value the drop recorder is told about when a `format` token parses and
#: this build cannot encode it (behaviours section 1.12's pattern, 005 section 6.12's recorder).
#: Recorded as `format=<value>`, which is the recorder's own convention.
FORMAT_PARAMETER = "format"

#: The encoder's own defaults stand when no `quality` was given: goldens assert headers and
#: dimensions, never encoder bytes (spec section 6).
QUALITY_RANGE = (0, 100)


@dataclass(frozen=True, slots=True)
class Source:
    """What the carrier's bytes turn out to be. Read from the header; no pixel is decoded."""

    width: int
    height: int
    image_format: str
    """Pillow's name for the container - `JPEG`, `PNG`, `WEBP`."""

    has_alpha: bool

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES.get(self.image_format, UNKNOWN_MEDIA_TYPE)


@dataclass(frozen=True, slots=True)
class TransformSpec:
    """The request's numbers, canonical. The route parses; this module decides.

    `accepts_webp` is the `Accept` header reduced to the one thing that changes an answer - the
    presence of the `image/webp` token (plan section 6.4). A boolean rather than the header,
    because a module that parsed `Accept` would be a module that knows about HTTP.
    """

    max_width: int | None = None
    max_height: int | None = None
    width: int | None = None
    height: int | None = None
    fill_width: int | None = None
    fill_height: int | None = None
    quality: int | None = None
    image_format: RequestedFormat | None = None
    accepts_webp: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    """What to do with the carrier's bytes, and what to call the result.

    `verbatim` is the whole first branch: the bytes go out untouched, and no cache entry is
    written because there is nothing to cache that the file is not already.
    """

    verbatim: bool
    target: tuple[int, int]
    image_format: str
    """Pillow's name for the **resolved** output format. Inside the cache key, so a negotiated
    WebP and a bare JPEG of the same geometry are two entries (plan section 4)."""

    quality: int | None
    dropped: tuple[str, ...] = field(default=())
    """Parameters that parsed and were not acted on, for the recorder (behaviours 1.12)."""

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES.get(self.image_format, UNKNOWN_MEDIA_TYPE)

    @property
    def extension(self) -> str:
        return EXTENSIONS.get(self.image_format, "bin")

    @property
    def cache_key_parts(self) -> tuple[str, ...]:
        """The canonical transform tuple, resolved format included (plan section 4)."""
        return (
            str(self.target[0]),
            str(self.target[1]),
            self.image_format,
            "" if self.quality is None else str(self.quality),
        )


@dataclass(frozen=True, slots=True)
class Rendered:
    """The encoded result, or the source bytes when encoding was not possible."""

    payload: bytes
    media_type: str
    size: tuple[int, int]
    fell_back: bool = False
    """True when a decode failed and the source's own bytes are what is being returned."""


# ------------------------------------------------------------------------------------------
# Reading what the source is
# ------------------------------------------------------------------------------------------


def describe(payload: bytes) -> Source | None:
    """The source's size, container and alpha, from the header alone. `None` if unreadable.

    The same header-only read `metadata/artwork.describe_bytes` does at scan time, and for the
    same reason: this runs on every miss, and decoding a poster to learn its width would make a
    grid of two hundred of them a decode of two hundred.
    """
    try:
        with Image.open(io.BytesIO(payload)) as image:
            width, height = image.size
            return Source(
                width=width,
                height=height,
                image_format=image.format or "",
                has_alpha=image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info,
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("image bytes cannot be identified: %s", exc)
        return None


# ------------------------------------------------------------------------------------------
# The decision (plan sections 6.3 and 6.4)
# ------------------------------------------------------------------------------------------


def decide(spec: TransformSpec, source: Source) -> Decision:
    """What the reply should be, from the request's numbers and the source's own.

    In plan section 6.3's order: drop non-positive values, then fill, then exact, then fit, then
    ask whether any of it changed anything.
    """
    dropped: list[str] = []
    resolved, verbatim_format = _format_of(spec, source, dropped)

    if verbatim_format:
        # `format=Svg` short-circuits the whole request: the source bytes, the resize ignored.
        return Decision(
            verbatim=True,
            target=source.size,
            image_format=source.image_format,
            quality=None,
            dropped=tuple(dropped),
        )

    target = _target(spec, source)
    quality = _quality(spec, resolved)
    # **A bare `quality` is not a transform** (behaviours section 1.17): if nothing else moved,
    # the file goes out as it is and the quality is not acted on. The recorder is not told - the
    # reference forgives it silently and `quality` is an implemented parameter, not an ignored one.
    unchanged = target == source.size and resolved == source.image_format
    if unchanged:
        return Decision(
            verbatim=True,
            target=source.size,
            image_format=source.image_format,
            quality=None,
            dropped=tuple(dropped),
        )
    return Decision(
        verbatim=False,
        target=target,
        image_format=resolved,
        quality=quality,
        dropped=tuple(dropped),
    )


def _format_of(spec: TransformSpec, source: Source, dropped: list[str]) -> tuple[str, bool]:
    """`(the resolved Pillow format, whether the request short-circuits to verbatim)`.

    Spec section 3.3's order, measured: an explicit `format` if it is one of the three that
    encode; otherwise the `image/webp` offer **when a transform runs**; otherwise the source's own
    format. `Bmp` and `Gif` parse and fall back with the transform still applied; `Svg` goes
    verbatim; anything outside the vocabulary never reaches here, because the route drops it.
    """
    asked = spec.image_format
    if asked is RequestedFormat.SVG:
        return source.image_format, True
    if asked in ENCODABLE:
        return ENCODABLE[RequestedFormat(asked)], False
    if asked is not None:
        # `Bmp` and `Gif`: vocabulary members this build does not encode. Recorded, not refused -
        # and recorded as `format=Bmp` rather than as `format`, because what was dropped is the
        # **value**. That is 005 section 6.12's own convention, which `known_tokens` follows for
        # the token it drops one line earlier in the same request's life.
        dropped.append(f"{FORMAT_PARAMETER}={asked.value}")
        return source.image_format, False
    if spec.accepts_webp and _asks_for_a_resize(spec):
        return "WEBP", False
    return source.image_format, False


def _asks_for_a_resize(spec: TransformSpec) -> bool:
    """Whether any dimension parameter survived step 1.

    The negotiation rides a request that **transforms**, and this is what "transforms" means
    before the arithmetic runs: a request with no positive dimension at all negotiates nothing,
    which is the verbatim path the earlier probe made its offer on and misread.
    """
    return any(
        _positive(value) is not None
        for value in (
            spec.max_width,
            spec.max_height,
            spec.width,
            spec.height,
            spec.fill_width,
            spec.fill_height,
        )
    )


def _target(spec: TransformSpec, source: Source) -> tuple[int, int]:
    """The delivered size, in plan section 6.3's order.

    **Never upscaling is a property of three parameters, not of the module.** `maxWidth`,
    `maxHeight` and the fill pair are capped at the source; `width` and `height` are not, and the
    reference honours them past it - `width=4000` of a 2000x3000 source measured **4000x6000**,
    `width=2500&height=1000` measured exactly that, and `width=4000&maxWidth=1000` measured
    1000x1500, which is the exact size fitted afterwards. Asking for a *box* means at most; asking
    for a *dimension* means exactly.
    `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`
    """
    width, height = source.size

    fill_width, fill_height = _positive(spec.fill_width), _positive(spec.fill_height)
    if fill_width is not None or fill_height is not None:
        width, height = _cover(source, fill_width, fill_height)

    exact_width, exact_height = _positive(spec.width), _positive(spec.height)
    if exact_width is not None and exact_height is not None:
        # Both axes at once are honoured exactly **even against the source's ratio** - the one
        # path that is allowed to distort (spec section 3.3, measured).
        width, height = exact_width, exact_height
    elif exact_width is not None:
        width, height = _by_width(source, exact_width)
    elif exact_height is not None:
        width, height = _by_height(source, exact_height)

    max_width, max_height = _positive(spec.max_width), _positive(spec.max_height)
    if max_width is not None or max_height is not None:
        width, height = _fit((width, height), max_width, max_height)

    return max(width, 1), max(height, 1)


def _cover(source: Source, box_width: int | None, box_height: int | None) -> tuple[int, int]:
    """Scale to **cover** the box, aspect intact, overflow kept, capped at 1.

    The measured rule, and not the one the plan's draft had: there is no crop on this path. The
    delivered size equals the box only when the ratios already match, and a box the source cannot
    cover without upscaling delivers the source unchanged.
    """
    scales = []
    if box_width is not None:
        scales.append(box_width / source.width)
    if box_height is not None:
        scales.append(box_height / source.height)
    scale = min(max(scales), 1.0)
    return round(source.width * scale), round(source.height * scale)


def _fit(size: tuple[int, int], max_width: int | None, max_height: int | None) -> tuple[int, int]:
    """Inside the box, aspect intact, never upscaled."""
    width, height = size
    scales = [1.0]
    if max_width is not None:
        scales.append(max_width / width)
    if max_height is not None:
        scales.append(max_height / height)
    scale = min(scales)
    return round(width * scale), round(height * scale)


def _by_width(source: Source, width: int) -> tuple[int, int]:
    return width, max(round(source.height * width / source.width), 1)


def _by_height(source: Source, height: int) -> tuple[int, int]:
    return max(round(source.width * height / source.height), 1), height


def _positive(value: int | None) -> int | None:
    """Step 1: a non-positive dimension parses, is forgiven with `200`, and is dropped.

    Not recorded through the drop recorder: the parameter is implemented, and what was refused is
    a value rather than a feature. The reference forgives it too - and it does **not** take the
    verbatim path afterwards, which is the one thing here Atrium does not reproduce
    (behaviours section 1.17).
    """
    if value is None or value <= 0:
        return None
    return value


def _quality(spec: TransformSpec, resolved: str) -> int | None:
    """Clamped to 0-100, and meaningless for PNG, whose encoder has no lossy knob.

    `quality=150` is forgiven with `200`, measured, so it clamps rather than refusing.
    """
    if spec.quality is None or resolved not in ("JPEG", "WEBP"):
        return None
    low, high = QUALITY_RANGE
    return max(low, min(high, spec.quality))


# ------------------------------------------------------------------------------------------
# The encoder
# ------------------------------------------------------------------------------------------


def render(payload: bytes, decision: Decision, source: Source) -> Rendered:
    """The decision, applied. A decode failure serves the source bytes rather than raising.

    Pillow's decompression-bomb guard raises on an image whose declared dimensions are absurd,
    and a file can also have been corrupted since the scan associated it. Either way a full-size
    poster beats a hole in the grid, and the bytes were good enough to associate: the source goes
    out with a warning, never a `5xx` (plan section 7).
    """
    if decision.verbatim:
        return Rendered(payload=payload, media_type=source.media_type, size=source.size)

    try:
        with Image.open(io.BytesIO(payload)) as image:
            image.load()
            resized = (
                image
                if image.size == decision.target
                else image.resize(decision.target, Image.Resampling.LANCZOS)
            )
            encoded = _encode(resized, decision)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        logger.warning("image cannot be transformed, serving the source: %s", exc)
        return Rendered(
            payload=payload, media_type=source.media_type, size=source.size, fell_back=True
        )

    return Rendered(payload=encoded, media_type=decision.media_type, size=decision.target)


def _encode(image: Image.Image, decision: Decision) -> bytes:
    """Convert as little as possible, then write.

    **Alpha leaves only through an explicit `Jpg`.** JPEG has no alpha channel, so an image with
    one is flattened onto **white** - the measured behaviour, and the matte colour is the one part
    of it no remote request can see. Every other path keeps the channel: a logo silently served as
    JPEG acquires a white box, immediately visible on any dark client theme (spec section 3.3).
    """
    buffer = io.BytesIO()
    prepared = _prepare(image, decision.image_format)
    options: dict[str, object] = {}
    if decision.quality is not None:
        options["quality"] = decision.quality
    prepared.save(buffer, format=decision.image_format, **options)
    return buffer.getvalue()


def _prepare(image: Image.Image, image_format: str) -> Image.Image:
    """Palette and CMYK sources convert to RGB(A); alpha is flattened only for JPEG."""
    if image_format == "JPEG":
        if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
            flattened = Image.new("RGB", image.size, (255, 255, 255))
            converted = image.convert("RGBA")
            flattened.paste(converted, mask=converted.getchannel("A"))
            return flattened
        return image if image.mode == "RGB" else image.convert("RGB")
    if image.mode in ("P", "CMYK", "LA", "I", "F"):
        return image.convert("RGBA" if image.mode in ("P", "LA") else "RGB")
    return image


__all__ = [
    "ENCODABLE",
    "EXTENSIONS",
    "FORMAT_PARAMETER",
    "MEDIA_TYPES",
    "QUALITY_RANGE",
    "UNKNOWN_MEDIA_TYPE",
    "Decision",
    "Rendered",
    "RequestedFormat",
    "Source",
    "TransformSpec",
    "decide",
    "describe",
    "render",
]
