# SPDX-License-Identifier: GPL-3.0-or-later
"""The one entry point the image routes call: a query in, the bytes out.

Four pieces, already built and already tested on their own — the lookup (`db.repositories`), the
readings (`images.source`), the decision and the encoder (`images.transform`), and the disposable
store (`images.cache`). This is the order they go in, and the two invariants that order buys
(006 plan section 5):

* **the payload is complete.** `Content-Length` is its length; there is no streaming here.
  Posters are small and 008 owns streaming.
* **the same query answers byte-identical payloads whether it was served from cache or
  recomputed** (AC-8, AC-13). The verbatim path makes that trivial for the requests that change
  nothing, and for the rest it comes from the cache key: a hit is the image the row still names,
  because the row's content tag is part of the name.

**Two refusals leave here and nothing else does.** `ItemNotFoundError` and `ImageNotFoundError`
are the reference's two `404` bodies on this route (behaviours section 1.11), and every other
failure is absorbed: a cache that cannot be written computes and serves, a decode that fails
serves the source bytes. A `5xx` from an image route would be a hole in a grid where the
reference shows a picture.

**A fallback is never cached.** When `render` cannot decode, the source's own bytes come back -
and writing those under a key that claims "300x450, WebP" would serve a full-size JPEG to every
later request for a small WebP, for as long as the file survived. The miss is repeated instead,
which costs a decode attempt and stays correct.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from atrium.db.repositories import ImageRepository
from atrium.images import cache as cache_module
from atrium.images import source as source_module
from atrium.images import transform
from atrium.images.cache import ImageCache

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ImageQuery:
    """One request, parsed and canonical. The route owns parsing; this owns everything after.

    `image_type` is already a member of the reference's vocabulary and `image_format` is already a
    member or `None` - a token outside either was refused or dropped before it got here
    (plan section 6.1, 6.4).

    **The `tag` parameter is not a field**, and its absence is the design. A stale tag serves the
    current image, measured, so it selects nothing: its whole life is flipping one `Cache-Control`
    value in the route (plan section 5, spec section 3.4).
    """

    item_id: str
    image_type: str
    index: int = 0
    max_width: int | None = None
    max_height: int | None = None
    width: int | None = None
    height: int | None = None
    fill_width: int | None = None
    fill_height: int | None = None
    quality: int | None = None
    image_format: transform.RequestedFormat | None = None
    accepts_webp: bool = False
    """Whether the request's `Accept` offered `image/webp` - a boolean rather than the header,
    because nothing below `api/` parses one. Added to plan section 5's contract when the gate
    measured the negotiation and added AC-15."""

    def spec(self) -> transform.TransformSpec:
        return transform.TransformSpec(
            max_width=self.max_width,
            max_height=self.max_height,
            width=self.width,
            height=self.height,
            fill_width=self.fill_width,
            fill_height=self.fill_height,
            quality=self.quality,
            image_format=self.image_format,
            accepts_webp=self.accepts_webp,
        )


@dataclass(frozen=True, slots=True)
class ImageReply:
    """The bytes and the two things the route needs to describe them."""

    payload: bytes
    media_type: str
    """From the bytes being served, never from a file extension."""

    last_modified: datetime
    """The **carrier's** mtime, in UTC. A variant is as old as what it derives from, which is what
    keeps the validator stable across rescans that change nothing (plan section 6.6)."""

    dropped: tuple[str, ...] = ()
    """Parameters that parsed and were not acted on, for the route's recorder (behaviours 1.12).
    `format=Bmp` is the one that gets here; `format=Banana` never parses this far."""


class ImageService:
    """Plan section 5's `get`, with its three dependencies bound.

    The plan writes the entry point as a bare `get(query)`; the dependencies are constructor
    arguments because they have different lifetimes - the repository is a request's session, the
    cache is the application's, and the data directory is the instance's. Binding them at the call
    site instead would put the wiring in every route that serves an image.
    """

    def __init__(self, images: ImageRepository, cache: ImageCache, data_dir: Path) -> None:
        self._images = images
        self._cache = cache
        self._data_dir = data_dir

    def get(self, query: ImageQuery) -> ImageReply:
        """The bytes for this request. Raises `ItemNotFoundError` or `ImageNotFoundError`."""
        located = source_module.require(
            self._images.locate(query.item_id, query.image_type, query.index), query.image_type
        )
        carrier = source_module.read(located, data_dir=self._data_dir)

        described = transform.describe(carrier.payload)
        if described is None:
            # The file changed under a row that still names it. 004 refuses to associate what it
            # cannot identify, so this is corruption since the scan - and the bytes go out anyway
            # (plan section 7), because they are what the item has.
            logger.warning(
                "image %s/%s of %s is no longer an image this build can read; serving it as it is",
                located.image_type,
                located.index,
                located.item_id,
            )
            return ImageReply(
                payload=carrier.payload,
                media_type=transform.UNKNOWN_MEDIA_TYPE,
                last_modified=carrier.last_modified,
            )

        # **The decision comes from the row, not from the file.** 004 stored `width` and `height`
        # at association time and plan section 6.1 says they are what answer the never-upscale
        # question - and the consequence is AC-8: the cache key is derived from this decision, so
        # a file that changed under a row nothing has rescanned yet still answers the *same* key
        # and the same bytes. Deciding from the bytes on disk turns every such hit into a silent
        # miss, which is the case AC-8 exists to pin. The format and the alpha come from the bytes
        # because no row stores them.
        stored = transform.Source(
            width=located.width,
            height=located.height,
            image_format=described.image_format,
            has_alpha=described.has_alpha,
        )
        decision = transform.decide(query.spec(), stored)
        if decision.verbatim:
            # The anchor: the carrier's bytes as they sit on disk. Nothing is cached, because
            # there is nothing to cache that the file is not already.
            return ImageReply(
                payload=carrier.payload,
                media_type=described.media_type,
                last_modified=carrier.last_modified,
                dropped=decision.dropped,
            )

        key = cache_module.key_for(
            item_id=located.item_id,
            image_type=located.image_type,
            index=located.index,
            tag=located.tag,
            decision=decision,
        )
        hit = self._cache.read(key)
        if hit is not None:
            return ImageReply(
                payload=hit.payload,
                media_type=hit.media_type,
                last_modified=carrier.last_modified,
                dropped=decision.dropped,
            )

        rendered = transform.render(carrier.payload, decision, described)
        if not rendered.fell_back:
            self._cache.write(key, rendered.payload)
        return ImageReply(
            payload=rendered.payload,
            media_type=rendered.media_type,
            last_modified=carrier.last_modified,
            dropped=decision.dropped,
        )


__all__ = ["ImageQuery", "ImageReply", "ImageService"]
