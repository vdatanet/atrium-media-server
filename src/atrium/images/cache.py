# SPDX-License-Identifier: GPL-3.0-or-later
"""The disposable store for transformed images.

    <data-dir>/cache/images/<k[:2]>/<k>.<ext>

`k` is a hash over the item, the image type, the index, the stored **content tag** and the
canonical transform tuple — with the resolved output format inside it, so a negotiated WebP and a
bare JPEG of the same geometry are two entries (006 plan section 4). The extension is that
resolved format, so a hit recovers its `Content-Type` without opening the bytes again.

**The tag in the key is what makes a stale entry unreachable rather than wrong.** When an image
changes, its row gets a new tag, every key derived from it changes, and the old files become
garbage nobody can address. Nothing has to invalidate anything, and AC-8's honesty comes from the
same place: a request served from cache is the image the row still names, not the file that
happens to be on disk now.

**Disposable by contract** (spec section 4). Deleting the whole tree costs CPU and never
correctness, which AC-13 proves by doing it between two requests. An unwritable cache — a full
disk, a read-only mount, a container's user mapping — computes and serves anyway with one warning:
a cache that is allowed to vanish at any moment is a cache that is allowed to never be there, and
a `5xx` because a *cache* could not be written would be the wrong failure.

Two directories deep by the first byte of the digest, for the same reason every content-addressed
store does it: a quarter of a million posters in one directory is a directory listing nobody wants
to take.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from atrium.images.transform import EXTENSIONS, MEDIA_TYPES, UNKNOWN_MEDIA_TYPE, Decision

logger = logging.getLogger(__name__)

#: `<data-dir>/cache/images`. The parent is `DataPaths.cache`, which 001 already creates.
DIRECTORY = "images"

#: How many hex characters of the digest name the fan-out directory.
FANOUT = 2

#: Read back from the extension a hit was written under, which is why the extension is the
#: resolved format rather than the source's.
MEDIA_TYPE_BY_EXTENSION: dict[str, str] = {
    extension: MEDIA_TYPES[image_format] for image_format, extension in EXTENSIONS.items()
}


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Where one transformed variant lives, and what it is.

    Built from values only - no path, no clock - so two processes asking for the same variant of
    the same image compute the same name.
    """

    digest: str
    extension: str

    @property
    def relative(self) -> Path:
        return Path(self.digest[:FANOUT]) / f"{self.digest}.{self.extension}"

    @property
    def media_type(self) -> str:
        return MEDIA_TYPE_BY_EXTENSION.get(self.extension, UNKNOWN_MEDIA_TYPE)


@dataclass(frozen=True, slots=True)
class Cached:
    payload: bytes
    media_type: str


def key_for(*, item_id: str, image_type: str, index: int, tag: str, decision: Decision) -> CacheKey:
    """The name this variant is stored under.

    Every part is a value that changes the bytes: the item and the type and the index say which
    image, the tag says **which version** of it, and the decision's own tuple says what was done
    to it. A key that left the tag out would serve the previous poster after a rescan, for as long
    as the file survived.
    """
    parts = (item_id, image_type, str(index), tag, *decision.cache_key_parts)
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return CacheKey(digest=digest, extension=decision.extension)


class ImageCache:
    """Files under a directory, with every failure to write treated as a miss.

    **One per application.** The "warn once" below is per instance, and the application builds
    exactly one - which is what makes it once per process without a module-level flag that tests
    would have to reach into and reset.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._warned = False

    @property
    def root(self) -> Path:
        return self._root

    def path_of(self, key: CacheKey) -> Path:
        return self._root / key.relative

    def read(self, key: CacheKey) -> Cached | None:
        """The stored bytes, or `None` for anything at all that went wrong.

        A hit that cannot be read is a miss: the caller recomputes, which is always correct and
        never slower than a failure.
        """
        try:
            return Cached(payload=self.path_of(key).read_bytes(), media_type=key.media_type)
        except OSError:
            return None

    def write(self, key: CacheKey, payload: bytes) -> bool:
        """Store `payload` under `key`. `False` when the cache could not take it.

        Written to a temporary file **in the same directory** and renamed into place, so a reader
        sees either nothing or the whole entry, and two processes computing the same variant
        converge on one intact file rather than interleaving into a broken one. The rename is
        atomic only **within a filesystem**, which is why the temporary file cannot go to `/tmp`.
        """
        target = self.path_of(key)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".writing-")
            try:
                with os.fdopen(handle, "wb") as opened:
                    opened.write(payload)
                Path(temporary).replace(target)
            except OSError:
                Path(temporary).unlink(missing_ok=True)
                raise
        except OSError as exc:
            self._warn(exc)
            return False
        return True

    def _warn(self, exc: OSError) -> None:
        if self._warned:
            return
        self._warned = True
        logger.warning(
            "the image cache at %s cannot be written (%s); images will be computed on every "
            "request until this is fixed. This is a performance problem, not a correctness one: "
            "the cache is disposable by contract.",
            self._root,
            exc.strerror or exc,
        )


__all__ = [
    "DIRECTORY",
    "FANOUT",
    "MEDIA_TYPE_BY_EXTENSION",
    "CacheKey",
    "Cached",
    "ImageCache",
    "key_for",
]
