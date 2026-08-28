# SPDX-License-Identifier: GPL-3.0-or-later
"""From an item id to the bytes on disk: the one lookup, the three readings, and the refusals.

Nothing here goes near HTTP. `images/source.py` owns bytes and `ImageRepository` owns the query,
and the split between them is the one thing worth stating twice: the repository reports **what it
found**, and this module decides which of the reference's two `404` bodies that becomes. A
repository that raised would be `db/` deciding a wire shape.

The world is `tests/fixtures/images.py`: real files under two `tmp_path` roots, real rows written
through the repositories, a FLAC that carries a picture and an MP3 that does not.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.compat.errors import ImageNotFoundError, ItemNotFoundError
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import ImageRepository, MetadataRepository
from atrium.images import source
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind
from atrium.metadata.merge import MetadataChanges
from atrium.metadata.model import Field
from tests.conftest import data_dir
from tests.fixtures.images import BACKDROP_SIZES, REFRESHED_AT, ImageWorld, build_image_world


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
def images(session: OrmSession) -> ImageRepository:
    return ImageRepository(session)


def carrier(
    images: ImageRepository, paths: DataPaths, item_id: str, kind: str = "Primary", index: int = 0
) -> source.Carrier:
    """The whole path a request takes, minus HTTP: locate, require, read."""
    located = source.require(images.locate(item_id, kind, index), kind)
    return source.read(located, data_dir=paths.root)


# ------------------------------------------------------------------------------------------
# The three readings
# ------------------------------------------------------------------------------------------


def test_a_file_row_resolves_to_the_drawn_bytes(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    assert carrier(images, paths, world.small).payload == world.drawn.small


def test_a_file_row_resolves_through_the_root_that_has_the_file(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    """The poster is under the **second** root and under no other.

    A reading that stopped at `roots[0]` would answer the absent-image `404` here and pass every
    other test in this file, which is why the fixture gives this library two roots.
    """
    assert carrier(images, paths, world.poster).payload == world.drawn.poster


def test_an_embedded_row_reads_the_art_out_of_the_audio_file(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    """Through `metadata/tags`, the same reader the scan used - not a second parser."""
    assert carrier(images, paths, world.embedded).payload == world.drawn.embedded


def test_a_remote_row_resolves_against_the_data_directory(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    assert carrier(images, paths, world.remote).payload == world.drawn.remote


def test_each_backdrop_index_reads_its_own_file(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    """Three sizes, three indexes. Asserted on the bytes rather than on the row that was chosen,
    because "the query returned index 1" and "index 1's file was opened" are two claims."""
    for index, expected in enumerate(world.drawn.backdrops):
        found = carrier(images, paths, world.backdrops, "Backdrop", index)
        assert found.payload == expected, f"backdrop {index} served the wrong file"


def test_the_carrier_reports_the_files_own_modification_time(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    """The only truthful clock this feature has (behaviours section 2.17), and it has to be the
    **carrier's**: an embedded row's variant is as old as the audio file it came out of."""
    on_disk = world.second_root / "The Poster" / "poster.jpg"
    found = carrier(images, paths, world.poster)
    assert found.last_modified.timestamp() == pytest.approx(on_disk.stat().st_mtime)


# ------------------------------------------------------------------------------------------
# The lookup itself
# ------------------------------------------------------------------------------------------


def test_the_lookup_carries_the_roots_and_the_part_zero_source(
    images: ImageRepository, world: ImageWorld
) -> None:
    """One query, everything the reading needs. A second query for either of these would be a
    second chance to disagree with the first."""
    located = images.locate(world.embedded, "Primary", 0).location
    assert located is not None
    assert located.source_kind is SourceKind.EMBEDDED
    assert located.relative_path is None
    assert located.carrier_path == "The Tagged One/track.flac"
    assert set(located.library_roots) == {
        world.first_root.as_posix(),
        world.second_root.as_posix(),
    }


def test_the_stored_dimensions_and_tag_come_back_with_the_row(
    images: ImageRepository, world: ImageWorld
) -> None:
    """The never-upscale question is answerable before a file is opened, and the cache key's
    content half is already here (plan section 6.1)."""
    located = images.locate(world.backdrops, "Backdrop", 1).location
    assert located is not None
    assert (located.width, located.height) == BACKDROP_SIZES[1]
    assert len(located.tag) == 32


def test_the_image_type_matches_case_insensitively(
    images: ImageRepository, world: ImageWorld
) -> None:
    """It arrives as a path segment, and paths match case-insensitively (behaviours section
    1.14)."""
    for spelling in ("Primary", "primary", "PRIMARY", "PrImArY"):
        located = images.locate(world.poster, spelling, 0).location
        assert located is not None, spelling
        assert located.image_type == "Primary", "the row's own spelling, not the request's"


# ------------------------------------------------------------------------------------------
# The refusals, and which is which
# ------------------------------------------------------------------------------------------


def test_an_unknown_item_is_the_item_refusal(images: ImageRepository, world: ImageWorld) -> None:
    with pytest.raises(ItemNotFoundError):
        source.require(images.locate("0" * 32, "Primary", 0), "Primary")


def test_a_removed_item_is_the_item_refusal_too(images: ImageRepository, world: ImageWorld) -> None:
    """The world a client browses has no removed items in it, and an image route that disagreed
    would answer `200` for an item every list says is gone."""
    with pytest.raises(ItemNotFoundError):
        source.require(images.locate(world.removed, "Primary", 0), "Primary")


def test_an_item_with_no_rows_is_the_image_refusal_naming_it(
    images: ImageRepository, world: ImageWorld
) -> None:
    """The other `404`, and the difference is the whole of behaviours section 1.11's fourth
    shape: this one names the item and the type on the wire."""
    with pytest.raises(ImageNotFoundError) as refused:
        source.require(images.locate(world.imageless, "Primary", 0), "Primary")

    assert refused.value.item_name == "The Bare One"
    assert refused.value.image_type == "Primary"
    assert not isinstance(refused.value, ItemNotFoundError)


def test_an_item_that_lacks_this_type_is_the_image_refusal(
    images: ImageRepository, world: ImageWorld
) -> None:
    """The logo item exists, has artwork, and has no `Primary`."""
    with pytest.raises(ImageNotFoundError):
        source.require(images.locate(world.logo, "Primary", 0), "Primary")


def test_an_index_past_the_last_backdrop_is_the_image_refusal(
    images: ImageRepository, world: ImageWorld
) -> None:
    with pytest.raises(ImageNotFoundError):
        source.require(images.locate(world.backdrops, "Backdrop", len(BACKDROP_SIZES)), "Backdrop")


def test_a_vanished_carrier_is_the_image_refusal(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    """The row still promises a file and the file is gone. A refusal plus a warning naming the
    path, never a `5xx`: the next scan removes or re-associates the row (plan section 7)."""
    (world.second_root / "The Poster" / "poster.jpg").unlink()

    with pytest.raises(ImageNotFoundError):
        carrier(images, paths, world.poster)


def test_an_embedded_row_whose_art_was_stripped_is_the_image_refusal(
    images: ImageRepository, paths: DataPaths, world: ImageWorld
) -> None:
    """The one failure no file-based row can express: the carrier is there and carries nothing."""
    with pytest.raises(ImageNotFoundError):
        carrier(images, paths, world.stripped)


# ------------------------------------------------------------------------------------------
# The hostile row
# ------------------------------------------------------------------------------------------


#: Three spellings of one escape, and **every one of them resolves to a file that exists**. That
#: is what makes this test able to fail: `../../../../etc/passwd` was the obvious first case and it
#: passed with the containment check deleted, because four `..` from a `tmp_path` root reach
#: nothing - a refusal for the wrong reason reads exactly like a refusal for the right one.
ESCAPES = (
    "../outside/poster.jpg",
    "The Poster/../../outside/poster.jpg",
    "./../outside/poster.jpg",
)


@pytest.mark.parametrize("crafted", ESCAPES)
def test_a_row_whose_path_escapes_its_root_is_refused_not_resolved(
    session: OrmSession,
    images: ImageRepository,
    paths: DataPaths,
    world: ImageWorld,
    tmp_path: Path,
    crafted: str,
) -> None:
    """Plan section 9's hostile row, and the file it points at **exists**.

    The rows are server-written, so this cannot happen - which is exactly why the check is worth
    asserting rather than trusting. Pointing the crafted row at a real file outside the root is
    what makes the test able to fail: against a path that does not exist, a resolver with no
    containment check answers the same refusal for the wrong reason.
    """
    outside = tmp_path / "libraries" / "outside" / "poster.jpg"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(world.drawn.small)
    assert (world.first_root / crafted).resolve() == outside.resolve(), (
        "this case does not reach the planted file, so it would refuse whether or not the "
        "containment check exists"
    )

    metadata = MetadataRepository(session)
    metadata.apply(
        world.small,
        MetadataChanges(
            values={
                Field.IMAGES: [
                    ImageAssociation(
                        kind=ImageKind.PRIMARY,
                        index=0,
                        source_kind=SourceKind.FILE,
                        relative_path=crafted,
                        width=400,
                        height=600,
                        tag="d" * 32,
                    )
                ]
            }
        ),
        refreshed_at=REFRESHED_AT,
    )

    with pytest.raises(ImageNotFoundError):
        carrier(images, paths, world.small)


def test_the_hostile_path_test_can_fail(world: ImageWorld, tmp_path: Path) -> None:
    """The other half of the one above: the escape it crafts really does escape.

    Without this, a containment check that had been deleted and a `..` that resolved to nothing
    would look the same from the test that matters.
    """
    outside = (world.first_root / "../outside/poster.jpg").resolve()
    assert world.first_root.resolve() not in outside.parents
