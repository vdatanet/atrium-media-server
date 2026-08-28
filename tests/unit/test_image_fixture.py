# SPDX-License-Identifier: GPL-3.0-or-later
"""The invariants of the drawn image world, so nothing else has to assume them.

`tests/fixtures/images.py` has no consumer yet - `images/` does not exist. That is precisely when
a fixture's invariants are worth writing down: a builder that quietly stopped placing the poster
under the second root would weaken every root-search test written after it and fail none of them,
which is the failure mode `tests/unit/test_query_fixture.py` exists for one feature earlier.

**The load-bearing invariant is that nothing here was typed in twice.** A row's `width`, `height`
and `tag` are read from the bytes that were drawn, exactly as 004 reads them from the file it
associated - so a serve path that ignored the row and re-measured the file would agree, and one
that served a *different* file would not.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession

from atrium.config.paths import DataPaths
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.metadata.artwork import SourceKind, describe_bytes
from atrium.metadata.tags import read_tags
from tests.conftest import data_dir
from tests.fixtures.images import (
    BACKDROP_SIZES,
    LOGO_SIZE,
    POSTER_SIZE,
    SMALL_SIZE,
    ImageWorld,
    build_image_world,
    drawn,
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


def rows(session: OrmSession) -> list[models.ItemImage]:
    return list(session.query(models.ItemImage).all())


# ------------------------------------------------------------------------------------------
# The drawings
# ------------------------------------------------------------------------------------------


def test_the_drawings_have_the_sizes_the_assertions_are_written_against() -> None:
    """Read back through Pillow, not asserted against the numbers that were passed in."""
    art = drawn()
    assert Image.open(io.BytesIO(art.poster)).size == POSTER_SIZE
    assert Image.open(io.BytesIO(art.small)).size == SMALL_SIZE
    assert Image.open(io.BytesIO(art.logo)).size == LOGO_SIZE
    assert tuple(Image.open(io.BytesIO(one)).size for one in art.backdrops) == BACKDROP_SIZES


def test_the_poster_is_not_square_which_is_the_whole_point_of_it() -> None:
    """A square source cannot tell a cover from a crop - 006 T1 measured the reference wrong
    once for exactly that reason, on a library whose posters happened to be square."""
    width, height = POSTER_SIZE
    assert width != height
    assert abs(width / height - 2 / 3) < 0.01


def test_the_three_backdrops_are_three_different_sizes() -> None:
    """Which is what makes `/Backdrop/1` assertible by decoding the reply rather than by trusting
    the row it came from."""
    assert len(set(BACKDROP_SIZES)) == len(BACKDROP_SIZES)
    assert len({width for width, _ in BACKDROP_SIZES}) == len(BACKDROP_SIZES)


def test_the_logo_really_carries_transparency() -> None:
    """AC-7 is a claim about an alpha channel, and a fixture that drew an opaque PNG would make
    every assertion about it pass for the wrong reason."""
    logo = Image.open(io.BytesIO(drawn().logo))
    assert logo.mode == "RGBA"
    alpha = logo.getchannel("A")
    assert alpha.getextrema() == (0, 255), "some pixels fully transparent, some fully opaque"


def test_two_draws_are_byte_identical() -> None:
    """Principle VII. The tag is a hash of these bytes, so a drawing that varied would give the
    same fixture a different content tag on every run."""
    first, second = drawn(), drawn()
    assert first == second


# ------------------------------------------------------------------------------------------
# The seeded world
# ------------------------------------------------------------------------------------------


def test_every_row_describes_the_bytes_that_were_drawn(
    session: OrmSession, world: ImageWorld
) -> None:
    """The invariant everything else leans on: the stored dimensions and tag are what
    `metadata.artwork.describe` reports for the bytes - AC-2's serve-side half.

    The tag **is** the content hash. Nothing in 006 recomputes it at serve time (plan section 10),
    so a row whose tag did not come from its bytes would make the cache key a lie.
    """
    art = world.drawn
    by_tag = {}
    for payload in (art.poster, art.small, art.logo, art.embedded, art.remote, *art.backdrops):
        described = describe_bytes(payload)
        assert described is not None
        by_tag[described[2]] = described

    for row in rows(session):
        assert row.tag in by_tag, f"{row.item_id}/{row.image_type} has a tag no drawing produced"
        width, height, _tag = by_tag[row.tag]
        assert (row.width, row.height) == (width, height)


def test_all_three_source_kinds_are_present(session: OrmSession, world: ImageWorld) -> None:
    """The three readings of plan section 6.2 each have a row to be read through."""
    kinds = {row.source_kind for row in rows(session)}
    assert kinds == {SourceKind.FILE.value, SourceKind.EMBEDDED.value, SourceKind.REMOTE.value}


def test_the_two_root_split_is_real(world: ImageWorld) -> None:
    """The poster is under the **second** root and under no other, so a reading that stopped at
    `roots[0]` finds nothing rather than finding it anyway."""
    assert len(world.library.roots) == 2
    assert (world.second_root / "The Poster" / "poster.jpg").is_file()
    assert not (world.first_root / "The Poster" / "poster.jpg").exists()
    assert (world.first_root / "The Small One" / "poster.jpg").is_file()


def test_the_embedded_carrier_really_holds_the_art_and_the_stripped_one_does_not(
    world: ImageWorld,
) -> None:
    """Read back through `metadata/tags`, which is the reader the serve path will use.

    The stripped track is the only item that can express plan section 7's "embedded row whose art
    was stripped since the scan": the row promises a picture and the file has none.
    """
    carried = read_tags(world.first_root / "The Tagged One" / "track.flac")
    stripped = read_tags(world.first_root / "The Stripped One" / "track.mp3")

    assert carried.art is not None
    assert carried.art.data == world.drawn.embedded
    assert stripped.art is None


def test_the_remote_row_sits_under_the_data_directory_not_a_library_root(
    world: ImageWorld,
) -> None:
    """004's structural guarantee, from this side: a download never lands inside somebody's
    collection (004 AC-15, `config/paths.py`)."""
    landed = world.data_dir / "metadata" / "artwork" / "the-download" / "poster.jpg"
    assert landed.is_file()
    assert landed.read_bytes() == world.drawn.remote
    for root in (world.first_root, world.second_root):
        assert root not in landed.parents


def test_the_bare_item_has_no_image_rows_and_the_removed_one_is_removed(
    session: OrmSession, world: ImageWorld
) -> None:
    """Two different refusals need two different items, and neither is an unknown id."""
    with_rows = {row.item_id for row in rows(session)}
    assert world.imageless not in with_rows

    removed = session.get(models.Item, world.removed)
    assert removed is not None and removed.removed_at is not None


def test_two_builds_derive_the_same_world(tmp_path: Path) -> None:
    """Fixed identifiers, fixed bytes, no clock. The same discipline `query.py` is held to."""
    built = []
    for run in ("one", "two"):
        paths = data_dir(tmp_path / run / "atrium")
        engine = create_database_engine(paths)
        schema.ensure_current(engine, paths)
        with session_factory(engine).begin() as opened:
            world = build_image_world(opened, tmp_path / run / "libraries", paths.root)
            built.append(
                (
                    [world.poster, world.small, world.logo, world.backdrops, world.embedded],
                    sorted((row.item_id, row.image_type, row.tag) for row in rows(opened)),
                    world.drawn,
                )
            )
        engine.dispose()

    assert built[0] == built[1]
