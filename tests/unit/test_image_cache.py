# SPDX-License-Identifier: GPL-3.0-or-later
"""The disposable store: what it keys on, what it survives, and what it refuses to fail on.

Three properties, and each of them is a promise made somewhere else. The **key** is what makes
AC-8 honest — a hit is the image the row still names, because the row's content tag is inside the
name. The **atomic write** is what makes two concurrent requests converge instead of interleaving.
And the **degradation** is what makes spec §4's "disposable at any moment" true in the direction
nobody thinks about: a cache that may vanish is a cache that may never have been there, so an
unwritable one has to compute and serve rather than refuse.
"""

from __future__ import annotations

import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from atrium.images.cache import FANOUT, CacheKey, ImageCache, key_for
from atrium.images.transform import RequestedFormat, Source, TransformSpec, decide

#: The two degradation tests take a permission away and expect it to bite. Root ignores permission
#: bits, so under root they would assert that a failure happened and watch it succeed - a green
#: test proving nothing. Skipped with the reason named rather than quietly passing.
needs_permissions = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores permission bits, so an unwritable directory is not unwritable",
)

POSTER = Source(width=1000, height=1500, image_format="JPEG", has_alpha=False)

TAG = "a" * 32
ITEM = "b" * 32


def key(
    *,
    tag: str = TAG,
    item: str = ITEM,
    image_type: str = "Primary",
    index: int = 0,
    **request: object,
) -> CacheKey:
    decision = decide(TransformSpec(**request), POSTER)  # type: ignore[arg-type]
    return key_for(item_id=item, image_type=image_type, index=index, tag=tag, decision=decision)


@pytest.fixture
def cache(tmp_path: Path) -> ImageCache:
    return ImageCache(tmp_path / "cache" / "images")


# ------------------------------------------------------------------------------------------
# Round trip
# ------------------------------------------------------------------------------------------


def test_a_hit_returns_the_written_bytes_with_the_type_the_extension_names(
    cache: ImageCache,
) -> None:
    """The `Content-Type` comes back from the **extension**, which is why the extension is the
    resolved output format rather than the source's (plan §4)."""
    written = key(max_width=300, accepts_webp=True)
    assert cache.write(written, b"webp bytes")

    found = cache.read(written)

    assert found is not None
    assert found.payload == b"webp bytes"
    assert found.media_type == "image/webp"


def test_a_miss_is_none_rather_than_an_error(cache: ImageCache) -> None:
    assert cache.read(key(max_width=300)) is None


def test_the_entry_lands_where_the_layout_says(cache: ImageCache) -> None:
    written = key(max_width=300)
    cache.write(written, b"jpeg bytes")

    landed = cache.path_of(written)

    assert landed.parent.name == written.digest[:FANOUT]
    assert landed.name == f"{written.digest}.jpg"
    assert landed.is_file()


def test_nothing_is_left_behind_by_a_write(cache: ImageCache) -> None:
    """The temporary file is renamed into place, not left beside it: a directory that accumulated
    `.writing-` files would fill a disk with something no read can ever find."""
    written = key(max_width=300)
    cache.write(written, b"jpeg bytes")

    entries = sorted(path.name for path in cache.path_of(written).parent.iterdir())

    assert entries == [f"{written.digest}.jpg"]


# ------------------------------------------------------------------------------------------
# The key
# ------------------------------------------------------------------------------------------


def test_the_same_request_computes_the_same_key(cache: ImageCache) -> None:
    assert key(max_width=300) == key(max_width=300)


@pytest.mark.parametrize(
    "label,changed",
    [
        ("the geometry", {"max_width": 200}),
        ("the resolved format", {"max_width": 300, "image_format": RequestedFormat.PNG}),
        ("the negotiated format", {"max_width": 300, "accepts_webp": True}),
        ("the quality", {"max_width": 300, "quality": 10}),
    ],
)
def test_the_key_changes_when_the_bytes_would(label: str, changed: dict[str, object]) -> None:
    assert key(**changed) != key(max_width=300), label


@pytest.mark.parametrize(
    "label,changed",
    [
        ("the tag", {"tag": "c" * 32}),
        ("the item", {"item": "d" * 32}),
        ("the image type", {"image_type": "Backdrop"}),
        ("the index", {"index": 1}),
    ],
)
def test_the_key_changes_with_the_image_it_names(label: str, changed: dict[str, object]) -> None:
    """The tag is the one that matters most: without it in the key, a rescan that changed a
    poster would keep serving the previous one for as long as the file survived."""
    assert key(max_width=300, **changed) != key(max_width=300), label


def test_the_key_does_not_change_for_a_request_that_asks_the_same_thing_differently() -> None:
    """`maxWidth=300` and `width=300` deliver the same 300x450 of this source, so they are one
    entry. The key is the *decision*, not the request — which is what keeps a grid of two hundred
    posters from being cached twice because two clients spell the same size differently."""
    assert key(max_width=300) == key(width=300)


def test_a_negotiated_webp_and_a_bare_jpeg_are_two_entries(cache: ImageCache) -> None:
    """Plan §4's own example, asserted end to end rather than on the digest alone."""
    plain, negotiated = key(max_width=300), key(max_width=300, accepts_webp=True)
    cache.write(plain, b"jpeg bytes")
    cache.write(negotiated, b"webp bytes")

    assert cache.read(plain) is not None
    assert cache.read(negotiated) is not None
    assert cache.read(plain).payload != cache.read(negotiated).payload  # type: ignore[union-attr]
    assert cache.path_of(plain) != cache.path_of(negotiated)


# ------------------------------------------------------------------------------------------
# Concurrency and disposability
# ------------------------------------------------------------------------------------------


def test_two_concurrent_writes_of_one_key_converge_on_one_intact_entry(
    cache: ImageCache,
) -> None:
    """Both compute, both write, and the rename picks a winner. Interleaved writes to one path
    would leave a file that is half of each — a corrupt image served forever, because nothing
    ever recomputes a hit."""
    written = key(max_width=300)
    payload = bytes(range(256)) * 400

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.write(written, payload), range(8)))

    assert all(results)
    found = cache.read(written)
    assert found is not None and found.payload == payload
    assert sorted(path.name for path in cache.path_of(written).parent.iterdir()) == [
        f"{written.digest}.jpg"
    ]


def test_deleting_the_tree_between_operations_loses_nothing_but_time(
    cache: ImageCache, tmp_path: Path
) -> None:
    """AC-13's unit half. The next write recreates everything it needs, directories included."""
    written = key(max_width=300)
    cache.write(written, b"jpeg bytes")
    shutil.rmtree(cache.root)

    assert cache.read(written) is None
    assert cache.write(written, b"jpeg bytes")
    found = cache.read(written)
    assert found is not None and found.payload == b"jpeg bytes"


@needs_permissions
def test_an_unwritable_cache_degrades_with_exactly_one_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Not a `5xx`, and not a warning per request either: a client that loads two hundred posters
    against a full disk would otherwise write two hundred identical lines."""
    root = tmp_path / "read-only" / "images"
    root.parent.mkdir(parents=True)
    root.parent.chmod(0o500)
    cache = ImageCache(root)

    try:
        with caplog.at_level(logging.WARNING, logger="atrium.images.cache"):
            refused = [cache.write(key(max_width=size), b"bytes") for size in (300, 200, 100)]
    finally:
        root.parent.chmod(0o700)

    assert refused == [False, False, False]
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1, "once per cache, and the application builds exactly one"
    assert "disposable" in warnings[0].getMessage()


@needs_permissions
def test_an_unreadable_entry_is_a_miss_rather_than_an_error(cache: ImageCache) -> None:
    """A hit that cannot be read is recomputed. Correct, and never slower than failing."""
    written = key(max_width=300)
    cache.write(written, b"jpeg bytes")
    cache.path_of(written).chmod(0o000)

    try:
        assert cache.read(written) is None
    finally:
        cache.path_of(written).chmod(0o600)
