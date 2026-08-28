# SPDX-License-Identifier: GPL-3.0-or-later
"""A library with real image files in it, drawn rather than checked in.

Feature 006 serves bytes, so its world cannot be the seeded rows 005 works from: something has to
be on disk for the three `source_kind` readings to read. This builds that - Pillow draws the
images at test time, the builder places them under `tmp_path` roots, and the rows are written
**through the repositories**, the same discipline `tests/fixtures/query.py` follows and for the
same reason (plan section 8).

**Drawn, not checked in.** A binary fixture is a file nobody reviews, and the four properties this
feature's tests actually need are properties of the *drawing*: a 2:3 poster whose ratio tells a
cover from a fit and an exact box from an aspect-true one, a source small enough that asking for
more than it has is the never-upscale case, an image with a genuinely transparent region, and
three backdrops of three different sizes so index selection is assertible **by dimensions** rather
than by trusting the row it came from.

**Deterministic.** Every image is a fixed pattern scaled up with nearest-neighbour, so two builds
draw identical bytes and the content tag - which is a hash of exactly those bytes
(`metadata.artwork.tag_of`) - is stable within a run. Nothing here calls a clock or a random
source, and the identifiers are derived by `library/identity` like everywhere else.

**No users.** This route has none: it accepts a token, requires none, and has no per-user
visibility branch (spec section 3.2). A fixture that seeded a user would invite a test that
filtered by one, which is the branch the specification forbids.
"""

from __future__ import annotations

import io
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3
from PIL import Image
from sqlalchemy.orm import Session as OrmSession

from atrium.db.repositories import ItemRepository, LibraryRepository, MetadataRepository
from atrium.domain.items import CollectionType, Item, ItemType, MediaSource
from atrium.domain.library import Library
from atrium.domain.sorting import sort_name
from atrium.library import identity
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind, describe_bytes
from atrium.metadata.merge import MetadataChanges
from atrium.metadata.model import Field

#: The audio templates 004 T2 checked in: silent containers with no tags at all, so an embedded
#: fixture is one picture frame on a known-empty file rather than somebody's tagged MP3.
AUDIO_TEMPLATES = Path(__file__).resolve().parent / "metadata" / "audio"

#: Fixed, like every identifier in a fixture world. Not one of `query.py`'s, so a test that mixes
#: the two worlds fails on a collision rather than quietly sharing a library.
LIBRARY_ID = "6" * 32

#: Passed to every `apply`, because `apply` stamps `utc_now()` otherwise and a fixture that reads
#: a clock is a fixture two builds of which differ (`query.py` learned this at 005 T3).
REFRESHED_AT = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)

#: The poster's shape. **2:3 on purpose**: it is what discriminates cover from fit and the exact
#: box from an aspect-true one, and 006 T1 measured the reference on a source of exactly this
#: ratio `[probe: tools/probe_image_formats.py, Jellyfin 10.11.11, 2026-08-28]`.
POSTER_SIZE = (1000, 1500)

#: Small enough that `maxWidth=2000` is the never-upscale case (AC-5).
SMALL_SIZE = (400, 600)

#: The logo, with a transparent region. AC-7 is about what happens to that region.
LOGO_SIZE = (600, 200)

#: Three backdrops, three widths. Index selection is asserted by **decoding the reply** and
#: reading its size, which is a claim about the bytes served rather than about the row chosen.
BACKDROP_SIZES = ((1920, 1080), (1280, 720), (960, 540))


# ------------------------------------------------------------------------------------------
# Drawing
# ------------------------------------------------------------------------------------------


def _pattern(alpha: bool) -> Image.Image:
    """A 4x6 block of distinct colours - the seed every drawing is scaled up from.

    Small and scaled with nearest-neighbour rather than drawn pixel by pixel: a 1000x1500 Python
    loop costs a second per fixture, and blocks are what the assertions here need. The pattern is
    asymmetric in both axes so an image that came back rotated or mirrored would be visible.
    """
    colours = [
        (200, 30, 30),
        (30, 200, 30),
        (30, 30, 200),
        (200, 200, 30),
        (30, 200, 200),
        (200, 30, 200),
        (240, 240, 240),
        (15, 15, 15),
    ]
    image = Image.new("RGBA" if alpha else "RGB", (4, 6))
    pixels = image.load()
    assert pixels is not None
    for y in range(6):
        for x in range(4):
            red, green, blue = colours[(x + y * 4) % len(colours)]
            if alpha:
                # A quarter of the picture is fully transparent, and it is a *region* rather than
                # scattered pixels: a flatten onto white is then visible as a solid corner, which
                # is what AC-7's assertion looks at.
                opacity = 0 if (x < 2 and y < 3) else 255
                pixels[x, y] = (red, green, blue, opacity)
            else:
                pixels[x, y] = (red, green, blue)
    return image


def draw(width: int, height: int, image_format: str, *, alpha: bool = False) -> bytes:
    """The pattern at this size, encoded. Deterministic for a given Pillow build."""
    canvas = _pattern(alpha).resize((width, height), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    if image_format == "JPEG":
        canvas.convert("RGB").save(buffer, format="JPEG", quality=90)
    else:
        canvas.save(buffer, format=image_format)
    return buffer.getvalue()


@dataclass(frozen=True, slots=True)
class Drawn:
    """The bytes, before they are a file or a row.

    `images/transform.py` is pure and takes bytes, so its tests want these and nothing else -
    no database, no library root, no `tmp_path`.
    """

    poster: bytes
    """1000x1500 JPEG. The 2:3 source every resize assertion is written against."""

    small: bytes
    """400x600 JPEG. Asking for more than it has must return it unchanged."""

    logo: bytes
    """A PNG with a fully transparent quadrant."""

    backdrops: tuple[bytes, ...]
    """Three, at `BACKDROP_SIZES`, so `/Backdrop/1` is assertible by the size it decodes to."""

    embedded: bytes
    """What the FLAC carries. A JPEG, because that is what a ripper embeds."""

    remote: bytes
    """What a provider download would have left under the data directory."""


def drawn() -> Drawn:
    """Every image this feature's tests use, drawn once."""
    return Drawn(
        poster=draw(*POSTER_SIZE, "JPEG"),
        small=draw(*SMALL_SIZE, "JPEG"),
        logo=draw(*LOGO_SIZE, "PNG", alpha=True),
        backdrops=tuple(draw(width, height, "JPEG") for width, height in BACKDROP_SIZES),
        embedded=draw(500, 500, "JPEG"),
        remote=draw(680, 1000, "JPEG"),
    )


# ------------------------------------------------------------------------------------------
# The world
# ------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImageWorld:
    """Handles into the built world. Every field is an identifier, a path or bytes."""

    library: Library
    """One library, **two roots**. The `file` reading takes the first root the relative path
    exists under, and a library with one root cannot tell that from `roots[0]`."""

    first_root: Path
    second_root: Path
    data_dir: Path
    """Where a `remote` row resolves against - `<data-dir>/metadata/artwork/...`."""

    drawn: Drawn

    poster: str
    """A film whose `Primary` is a `file` row under the **second** root."""

    small: str
    """A film whose `Primary` is the 400px source, under the first root."""

    logo: str
    """A film carrying a `Logo` with alpha, and no `Primary` - so "this item has no image of that
    type" is reachable on an item that certainly exists."""

    backdrops: str
    """A series carrying three `Backdrop` rows and nothing else."""

    embedded: str
    """A track whose `Primary` is an `embedded` row: no path, the bytes inside the FLAC named by
    its part-zero source."""

    stripped: str
    """A track with an `embedded` row whose carrier carries **no** picture - the "art was stripped
    since the scan" failure of plan section 7, which no other item can express."""

    remote: str
    """A film whose `Primary` is a `remote` row under the data directory."""

    imageless: str
    """An item with no image rows at all."""

    removed: str
    """A soft-removed item. Its refusal is the *other* `404`, and only a removed item can tell
    `ItemNotFoundError` from `ImageNotFoundError` on an id that is in the table."""

    def path_of(self, root: Path, relative: str) -> Path:
        return root / relative


def build_image_world(session: OrmSession, tmp_path: Path, data_dir: Path) -> ImageWorld:
    """Draw, place, seed. Idempotent only on a fresh database."""
    art = drawn()
    first_root = tmp_path / "library-one"
    second_root = tmp_path / "library-two"
    for root in (first_root, second_root):
        root.mkdir(parents=True, exist_ok=True)

    libraries = LibraryRepository(session)
    items = ItemRepository(session)
    metadata = MetadataRepository(session)

    library = libraries.add(
        Library(
            id=LIBRARY_ID,
            name="Pictures",
            collection_type=CollectionType.MOVIES,
            roots=(first_root.as_posix(), second_root.as_posix()),
        )
    )

    poster = _film(items, library, "The Poster", "The Poster/The Poster.mkv")
    small = _film(items, library, "The Small One", "The Small One/The Small One.mkv")
    logo = _film(items, library, "The Logo", "The Logo/The Logo.mkv")
    remote = _film(items, library, "The Download", "The Download/The Download.mkv")
    imageless = _film(items, library, "The Bare One", "The Bare One/The Bare One.mkv")
    removed = _film(items, library, "The Gone One", "The Gone One/The Gone One.mkv")
    backdrops = _series(items, library, "The Backdrops")
    embedded = _track(items, library, "The Tagged One", "The Tagged One/track.flac")
    stripped = _track(items, library, "The Stripped One", "The Stripped One/track.mp3")

    # -- files on disk ------------------------------------------------------------------------
    # The poster sits under the **second** root and nothing sits under the first for that item,
    # which is the only shape that can tell a root search from `roots[0]`.
    _place(second_root, "The Poster/poster.jpg", art.poster)
    _place(first_root, "The Small One/poster.jpg", art.small)
    _place(first_root, "The Logo/logo.png", art.logo)
    for index, (payload, (width, _height)) in enumerate(
        zip(art.backdrops, BACKDROP_SIZES, strict=True)
    ):
        _place(first_root, f"The Backdrops/fanart-{index}-{width}.jpg", payload)
    _place(data_dir, "metadata/artwork/the-download/poster.jpg", art.remote)
    _flac(first_root / "The Tagged One" / "track.flac", art.embedded)
    _mp3(first_root / "The Stripped One" / "track.mp3", None)

    # -- rows, through the repository ---------------------------------------------------------
    _images(metadata, poster, [_file_row(ImageKind.PRIMARY, "The Poster/poster.jpg", art.poster)])
    _images(metadata, small, [_file_row(ImageKind.PRIMARY, "The Small One/poster.jpg", art.small)])
    _images(metadata, logo, [_file_row(ImageKind.LOGO, "The Logo/logo.png", art.logo)])
    _images(
        metadata,
        backdrops,
        [
            _file_row(
                ImageKind.BACKDROP,
                f"The Backdrops/fanart-{index}-{width}.jpg",
                payload,
                index=index,
            )
            for index, (payload, (width, _height)) in enumerate(
                zip(art.backdrops, BACKDROP_SIZES, strict=True)
            )
        ],
    )
    _images(
        metadata,
        remote,
        [
            _row(
                ImageKind.PRIMARY,
                SourceKind.REMOTE,
                "metadata/artwork/the-download/poster.jpg",
                art.remote,
            )
        ],
    )
    for item_id in (embedded, stripped):
        _images(
            metadata,
            item_id,
            [_row(ImageKind.PRIMARY, SourceKind.EMBEDDED, None, art.embedded)],
        )

    items.mark_removed([removed], REFRESHED_AT)
    session.flush()

    return ImageWorld(
        library=library,
        first_root=first_root,
        second_root=second_root,
        data_dir=data_dir,
        drawn=art,
        poster=poster,
        small=small,
        logo=logo,
        backdrops=backdrops,
        embedded=embedded,
        stripped=stripped,
        remote=remote,
        imageless=imageless,
        removed=removed,
    )


# ------------------------------------------------------------------------------------------
# Seeding helpers
# ------------------------------------------------------------------------------------------


def _film(items: ItemRepository, library: Library, name: str, relative: str) -> str:
    item = Item(
        id=identity.for_file(ItemType.MOVIE, library.id, relative),
        type=ItemType.MOVIE,
        name=name,
        library_id=library.id,
        sources=(MediaSource(relative_path=relative, size=1024),),
        date_created=REFRESHED_AT,
    )
    items.add(_sorted(item))
    return item.id


def _series(items: ItemRepository, library: Library, name: str) -> str:
    item = Item(
        id=identity.for_name(ItemType.SERIES, library.id, name),
        type=ItemType.SERIES,
        name=name,
        library_id=library.id,
        date_created=REFRESHED_AT,
    )
    items.add(_sorted(item))
    return item.id


def _track(items: ItemRepository, library: Library, name: str, relative: str) -> str:
    item = Item(
        id=identity.for_file(ItemType.AUDIO, library.id, relative),
        type=ItemType.AUDIO,
        name=name,
        library_id=library.id,
        sources=(MediaSource(relative_path=relative, size=2048),),
        date_created=REFRESHED_AT,
    )
    items.add(_sorted(item))
    return item.id


def _sorted(item: Item) -> Item:
    """The real derivation - `ItemRepository.add` writes whatever it is handed, and a fixture that
    set the sort name to the name would seed a world ordered by a rule the server does not use."""
    return replace(item, sort_name=sort_name(item))


def _images(
    metadata: MetadataRepository, item_id: str, associations: list[ImageAssociation]
) -> None:
    metadata.apply(
        item_id, MetadataChanges(values={Field.IMAGES: associations}), refreshed_at=REFRESHED_AT
    )


def _file_row(
    kind: ImageKind, relative: str, payload: bytes, *, index: int = 0
) -> ImageAssociation:
    return _row(kind, SourceKind.FILE, relative, payload, index=index)


def _row(
    kind: ImageKind,
    source_kind: SourceKind,
    relative: str | None,
    payload: bytes,
    *,
    index: int = 0,
) -> ImageAssociation:
    """A row whose `width`, `height` and `tag` are read from the bytes, never asserted onto them.

    004 computes all three at association time from the file it associated, and a fixture that
    typed the numbers in by hand would let a serve path that ignores the row still pass: the
    dimensions would agree because somebody made them agree.
    """
    described = describe_bytes(payload)
    assert described is not None, "the fixture drew something Pillow cannot read"
    width, height, tag = described
    return ImageAssociation(
        kind=kind,
        index=index,
        source_kind=source_kind,
        relative_path=relative,
        width=width,
        height=height,
        tag=tag,
    )


def _backdrops(art: Drawn) -> list[tuple[bytes, tuple[int, int]]]:
    return list(zip(art.backdrops, BACKDROP_SIZES, strict=True))


def _backdrop_path(index: int, size: tuple[int, int]) -> str:
    """Named for the width it holds, so a failure reads as a wrong file rather than a wrong row."""
    return f"The Backdrops/fanart-{index}-{size[0]}.jpg"


def _place(root: Path, relative: str, payload: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _flac(path: Path, art: bytes | None) -> Path:
    """A copy of 004's silent template, carrying one picture frame and nothing else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(AUDIO_TEMPLATES / "template.flac", path)
    if art is not None:
        opened = FLAC(path)
        picture = Picture()
        picture.data, picture.type, picture.mime = art, 3, "image/jpeg"
        opened.add_picture(picture)
        opened.save()
    return path


def _mp3(path: Path, art: bytes | None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(AUDIO_TEMPLATES / "template.mp3", path)
    if art is not None:
        frames = ID3()
        frames.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=art))
        frames.save(path)
    return path


__all__ = [
    "AUDIO_TEMPLATES",
    "BACKDROP_SIZES",
    "LIBRARY_ID",
    "LOGO_SIZE",
    "POSTER_SIZE",
    "REFRESHED_AT",
    "SMALL_SIZE",
    "Drawn",
    "ImageWorld",
    "build_image_world",
    "draw",
    "drawn",
]
