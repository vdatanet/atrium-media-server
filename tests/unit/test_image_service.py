# SPDX-License-Identifier: GPL-3.0-or-later
"""The four pieces wired together, over the drawn world and a real cache directory.

Still no HTTP. What is under test here is the *order* — lookup, read, decide, verbatim or
cache-through — and the invariants that order buys: byte-identity whether a reply was computed or
recovered, an embedded Primary re-extracted per verbatim request while its variants cache like any
other source, and two refusals leaving the service with nothing else escaping it.
"""

from __future__ import annotations

import io
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.compat.errors import ImageNotFoundError, ItemNotFoundError
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import ImageRepository
from atrium.images.cache import DIRECTORY, ImageCache
from atrium.images.service import ImageQuery, ImageService
from atrium.images.transform import RequestedFormat
from tests.conftest import data_dir
from tests.fixtures.images import (
    BACKDROP_SIZES,
    POSTER_SIZE,
    SMALL_SIZE,
    ImageWorld,
    build_image_world,
)


@pytest.fixture
def paths(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def engine(paths: DataPaths) -> Iterator[Engine]:
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[OrmSession]:
    with session_factory(engine).begin() as opened:
        yield opened


@pytest.fixture
def world(session: OrmSession, tmp_path: Path, paths: DataPaths) -> ImageWorld:
    return build_image_world(session, tmp_path / "libraries", paths.root)


@pytest.fixture
def cache_root(paths: DataPaths) -> Path:
    return paths.cache / DIRECTORY


@pytest.fixture
def service(session: OrmSession, paths: DataPaths, cache_root: Path) -> ImageService:
    return ImageService(ImageRepository(session), ImageCache(cache_root), paths.root)


def decoded(payload: bytes) -> Image.Image:
    return Image.open(io.BytesIO(payload))


def entries(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


# ------------------------------------------------------------------------------------------
# The verbatim path
# ------------------------------------------------------------------------------------------


def test_a_request_that_changes_nothing_serves_the_file_and_caches_nothing(
    service: ImageService, world: ImageWorld, cache_root: Path
) -> None:
    """Plan §1's anchor. There is nothing to cache that the file is not already."""
    reply = service.get(ImageQuery(item_id=world.poster, image_type="Primary"))

    assert reply.payload == world.drawn.poster
    assert reply.media_type == "image/jpeg"
    assert not entries(cache_root)


def test_ac5_never_upscaling_holds_end_to_end(service: ImageService, world: ImageWorld) -> None:
    """`maxWidth=2000` of the 400px source is byte-identical to the source file."""
    reply = service.get(ImageQuery(item_id=world.small, image_type="Primary", max_width=2000))

    assert reply.payload == world.drawn.small
    assert decoded(reply.payload).size == SMALL_SIZE


def test_the_last_modified_is_the_carriers_own(service: ImageService, world: ImageWorld) -> None:
    on_disk = world.second_root / "The Poster" / "poster.jpg"

    reply = service.get(ImageQuery(item_id=world.poster, image_type="Primary"))

    assert reply.last_modified.timestamp() == pytest.approx(on_disk.stat().st_mtime)


def test_a_transformed_variant_keeps_the_carriers_clock(
    service: ImageService, world: ImageWorld
) -> None:
    """A variant is as old as what it derives from — not as old as the moment it was encoded,
    which would move the validator on every cache miss (plan §6.6)."""
    verbatim = service.get(ImageQuery(item_id=world.poster, image_type="Primary"))
    resized = service.get(ImageQuery(item_id=world.poster, image_type="Primary", max_width=300))

    assert resized.last_modified == verbatim.last_modified


# ------------------------------------------------------------------------------------------
# The transformed path and the cache
# ------------------------------------------------------------------------------------------


def test_a_resize_writes_one_entry_and_the_second_request_reads_it(
    service: ImageService, world: ImageWorld, cache_root: Path
) -> None:
    query = ImageQuery(item_id=world.poster, image_type="Primary", max_width=300)

    first = service.get(query)
    written = entries(cache_root)
    second = service.get(query)

    assert decoded(first.payload).size == (300, 450)
    assert len(written) == 1
    assert entries(cache_root) == written, "the second request wrote nothing new"
    assert second.payload == first.payload


def test_ac8_a_hit_never_recomputes_even_when_the_file_underneath_has_changed(
    service: ImageService, world: ImageWorld
) -> None:
    """The honest version of "served from cache": overwrite the source **without rescanning** and
    ask again. The row still names the old content, so the old bytes are the right answer — and a
    reply that had recomputed would be visibly different."""
    query = ImageQuery(item_id=world.poster, image_type="Primary", max_width=300)
    first = service.get(query)

    (world.second_root / "The Poster" / "poster.jpg").write_bytes(world.drawn.remote)
    second = service.get(query)

    assert second.payload == first.payload


def test_ac13_deleting_the_cache_between_requests_changes_no_body(
    service: ImageService, world: ImageWorld, cache_root: Path
) -> None:
    query = ImageQuery(item_id=world.poster, image_type="Primary", max_width=300)
    first = service.get(query)

    shutil.rmtree(cache_root)
    recomputed = service.get(query)

    assert recomputed.payload == first.payload
    assert entries(cache_root), "and it wrote itself back"


def test_a_negotiated_webp_and_a_bare_jpeg_are_two_entries(
    service: ImageService, world: ImageWorld, cache_root: Path
) -> None:
    plain = ImageQuery(item_id=world.poster, image_type="Primary", max_width=300)
    negotiated = ImageQuery(
        item_id=world.poster, image_type="Primary", max_width=300, accepts_webp=True
    )

    first = service.get(plain)
    second = service.get(negotiated)

    assert first.media_type == "image/jpeg"
    assert second.media_type == "image/webp"
    assert len(entries(cache_root)) == 2


def test_an_unwritable_cache_still_serves_the_right_bytes(
    session: OrmSession, paths: DataPaths, world: ImageWorld, tmp_path: Path
) -> None:
    """Degraded, never a refusal: a cache that may be deleted at any moment may also never have
    existed (spec §4)."""
    nowhere = ImageService(
        ImageRepository(session), ImageCache(tmp_path / "does" / "not" / "exist" / "x"), paths.root
    )
    query = ImageQuery(item_id=world.poster, image_type="Primary", max_width=300)

    first = nowhere.get(query)
    second = nowhere.get(query)

    assert decoded(first.payload).size == (300, 450)
    assert second.payload == first.payload


# ------------------------------------------------------------------------------------------
# The embedded source
# ------------------------------------------------------------------------------------------


def test_an_embedded_primary_is_re_extracted_per_verbatim_request(
    service: ImageService, world: ImageWorld, cache_root: Path
) -> None:
    """Deliberate (plan §6.2): materialising it to disk duplicates bytes the library already
    holds, and nothing has measured the tag parse as a problem."""
    first = service.get(ImageQuery(item_id=world.embedded, image_type="Primary"))
    second = service.get(ImageQuery(item_id=world.embedded, image_type="Primary"))

    assert first.payload == second.payload == world.drawn.embedded
    assert not entries(cache_root), "a verbatim reply is never cached, embedded or not"


def test_a_transformed_embedded_variant_caches_like_any_other_source(
    service: ImageService, world: ImageWorld, cache_root: Path
) -> None:
    query = ImageQuery(item_id=world.embedded, image_type="Primary", max_width=200)

    reply = service.get(query)

    assert decoded(reply.payload).size == (200, 200)
    assert len(entries(cache_root)) == 1
    assert service.get(query).payload == reply.payload


# ------------------------------------------------------------------------------------------
# The rest of the matrix, through the whole stack
# ------------------------------------------------------------------------------------------


def test_ac4_a_resized_poster_decodes_to_the_expected_size(
    service: ImageService, world: ImageWorld
) -> None:
    reply = service.get(ImageQuery(item_id=world.poster, image_type="Primary", max_width=300))

    assert decoded(reply.payload).size == (300, 450)
    assert POSTER_SIZE == (1000, 1500), "the row above is written against this source"


def test_ac6_a_fill_box_covers_and_keeps_the_overflow(
    service: ImageService, world: ImageWorld
) -> None:
    reply = service.get(
        ImageQuery(item_id=world.poster, image_type="Primary", fill_width=300, fill_height=300)
    )

    assert decoded(reply.payload).size == (300, 450)


def test_ac7_a_resized_logo_keeps_its_alpha_and_an_explicit_jpg_takes_it(
    service: ImageService, world: ImageWorld
) -> None:
    kept = service.get(ImageQuery(item_id=world.logo, image_type="Logo", max_width=300))
    flattened = service.get(
        ImageQuery(
            item_id=world.logo,
            image_type="Logo",
            max_width=300,
            image_format=RequestedFormat.JPG,
        )
    )

    assert kept.media_type == "image/png"
    assert decoded(kept.payload).mode == "RGBA"
    assert flattened.media_type == "image/jpeg"
    assert decoded(flattened.payload).mode == "RGB"


def test_each_backdrop_index_serves_its_own_image(service: ImageService, world: ImageWorld) -> None:
    for index, size in enumerate(BACKDROP_SIZES):
        reply = service.get(ImageQuery(item_id=world.backdrops, image_type="Backdrop", index=index))
        assert decoded(reply.payload).size == size


def test_an_unencodable_format_is_reported_as_a_drop(
    service: ImageService, world: ImageWorld
) -> None:
    """The signal the route feeds to the recorder. `Bmp` reaches the service; `Banana` never
    parses this far."""
    reply = service.get(
        ImageQuery(
            item_id=world.poster,
            image_type="Primary",
            max_width=300,
            image_format=RequestedFormat.BMP,
        )
    )

    assert reply.dropped == ("format=Bmp",)
    assert reply.media_type == "image/jpeg", "the transform still ran"


# ------------------------------------------------------------------------------------------
# What leaves this service
# ------------------------------------------------------------------------------------------


def test_the_two_refusals_are_the_only_thing_raised(
    service: ImageService, world: ImageWorld
) -> None:
    """Plan §7's split, verified by **type** rather than by reading a body."""
    with pytest.raises(ItemNotFoundError):
        service.get(ImageQuery(item_id="f" * 32, image_type="Primary"))
    with pytest.raises(ItemNotFoundError):
        service.get(ImageQuery(item_id=world.removed, image_type="Primary"))

    for item_id, image_type in (
        (world.imageless, "Primary"),
        (world.logo, "Primary"),
        (world.stripped, "Primary"),
    ):
        with pytest.raises(ImageNotFoundError) as refused:
            service.get(ImageQuery(item_id=item_id, image_type=image_type))
        assert not isinstance(refused.value, ItemNotFoundError)


def test_a_decode_failure_serves_the_source_and_is_not_cached(
    service: ImageService, world: ImageWorld, cache_root: Path
) -> None:
    """The corrupted-since-the-scan case, end to end. Caching the fallback would serve a full-size
    JPEG to every later request for a small WebP, for as long as the file survived."""
    poster = world.second_root / "The Poster" / "poster.jpg"
    poster.write_bytes(world.drawn.poster[:400])

    reply = service.get(ImageQuery(item_id=world.poster, image_type="Primary", max_width=300))

    assert reply.payload == world.drawn.poster[:400]
    assert not entries(cache_root)


def test_bytes_that_are_no_longer_an_image_at_all_are_still_served(
    service: ImageService, world: ImageWorld
) -> None:
    """Not a `404` and not a `5xx`: the row names this file and these are its bytes. The media
    type is the honest one, because nothing here can name a format it could not read."""
    poster = world.second_root / "The Poster" / "poster.jpg"
    poster.write_bytes(b"not an image any more")

    reply = service.get(ImageQuery(item_id=world.poster, image_type="Primary"))

    assert reply.payload == b"not an image any more"
    assert reply.media_type == "application/octet-stream"
