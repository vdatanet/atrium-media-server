# SPDX-License-Identifier: GPL-3.0-or-later
"""Which file beside the media is which image, and what a response will need to say about it.

This module decides **which file is which image type** (spec section 3.4) and computes the two
things a response cannot be assembled without: the dimensions, for `PrimaryImageAspectRatio`, and
the content tag, for `ImageTags`. Delivery, resizing and caching are feature 006; nothing here
serves a byte.

**An association is never written without both.** 005 emits an item's aspect ratio and image tags
from these rows alone, before 006 exists to serve anything, so a row missing them is an item whose
aspect ratio is silently absent - the kind of gap a client renders as a subtly wrong grid and
nobody reports. A file Pillow cannot identify is therefore **skipped with a warning** rather than
associated without measurements.

**The tables here are the reference's, measured, and they are a superset of the spec's**
`[source: MediaBrowser.LocalMetadata/Images/LocalImageProvider.cs:18-400 @ v10.11.11]`. Four
differences are worth knowing before reading the tables, because none is reachable by reasoning:

* **The Primary names depend on the item's type.** A music album prefers `folder` over `poster`
  and also answers to `jacket` and `albumart`; a series answers to `show`; a film answers to
  `movie`. One list for everything would file a correctly-named album cover as nothing.
* **The per-item name is the bare stem**, `Film (1999).jpg`, and it beats every folder name.
  `Film (1999)-poster.jpg` also works, and is the form that matters when two films share a folder.
  Spec section 3.4 names only the second.
* **`landscape` beats `thumb`**, not the other way round, and for a music album **`cdart` beats
  `disc`** while for a film `disc` beats `cdart` beats `discart`. Spec section 3.4's table lists
  both pairs the other way.
* **Backdrops accumulate; every other type is first-match-wins.** Each backdrop family contributes
  a base name and then numbered variants, and the numbered scan **stops after three consecutive
  misses** rather than at the first gap - so `fanart-1`, `fanart-2`, `fanart-5` finds all three.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from atrium.domain.items import ItemType
from atrium.metadata.tags import EmbeddedArt

logger = logging.getLogger(__name__)

#: The extensions the name tables are matched over, case-insensitively (plan section 6.4).
EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")

#: How far a numbered backdrop scan looks, and how many consecutive misses end it. Both are the
#: reference's `[source: MediaBrowser.LocalMetadata/Images/LocalImageProvider.cs:355-380 @
#: v10.11.11]`: stopping at the first gap would lose every backdrop after a deleted one.
MAX_NUMBERED = 20
CONSECUTIVE_MISSES = 3

#: 32 lowercase hex - the first 16 bytes of the SHA-256 of the image bytes, the same width and
#: derivation as an item identifier (compat/guids.py). Computed at association time so 005 can
#: emit `ImageTags` before 006 exists, and **stable across a rescan because the bytes are**, which
#: is 006 AC-2's whole cache story decided here.
TAG_BYTES = 16


class ImageKind(StrEnum):
    """The reference's `ImageType`, restricted to what a *local file* can be
    `[spec: ImageType]`.

    The full enum has thirteen members; the eight absent ones are generated rather than found -
    chapter images, trickplay, screenshots - and generation is out of 004's scope (spec section 2).
    """

    PRIMARY = "Primary"
    BACKDROP = "Backdrop"
    LOGO = "Logo"
    THUMB = "Thumb"
    BANNER = "Banner"
    DISC = "Disc"
    ART = "Art"


@dataclass(frozen=True, slots=True)
class ArtworkFile:
    """One image, ready to be associated. **Dimensions and tag are not optional.**"""

    path: Path
    kind: ImageKind
    index: int
    width: int
    height: int
    tag: str


@dataclass(frozen=True, slots=True)
class ArtworkResult:
    files: tuple[ArtworkFile, ...] = ()
    warnings: tuple[str, ...] = ()


# ----------------------------------------------------------------------------------------------
# The name tables
# ----------------------------------------------------------------------------------------------

#: Primary, per item type, **in preference order**. The default list is the reference's
#: `_commonImageFileNames`; the others are its per-type arrays, and the differences are not
#: cosmetic - a music album prefers `folder`, because that is what every ripper writes.
PRIMARY_NAMES: Mapping[ItemType, tuple[str, ...]] = {
    ItemType.MUSIC_ALBUM: ("folder", "poster", "cover", "jacket", "default", "albumart"),
    ItemType.MUSIC_ARTIST: ("folder", "poster", "cover", "jacket", "default", "albumart"),
    ItemType.PERSON: ("folder", "poster"),
    ItemType.SERIES: ("poster", "folder", "cover", "default", "show"),
    ItemType.MOVIE: ("poster", "folder", "cover", "default", "movie"),
}

DEFAULT_PRIMARY_NAMES: tuple[str, ...] = ("poster", "folder", "cover", "default")

#: Disc, per item type. A music album prefers `cdart`; a film prefers `disc` and also answers to
#: `discart`, which nothing but a film does.
DISC_NAMES: Mapping[ItemType, tuple[str, ...]] = {
    ItemType.MUSIC_ALBUM: ("cdart", "disc"),
    ItemType.MOVIE: ("disc", "cdart", "discart"),
    ItemType.EPISODE: (),
    ItemType.AUDIO: (),
}

#: The single-image types that every container item answers to, in preference order.
SIMPLE_NAMES: Mapping[ImageKind, tuple[str, ...]] = {
    ImageKind.LOGO: ("logo", "clearlogo"),
    ImageKind.ART: ("clearart",),
    ImageKind.BANNER: ("banner",),
    # `landscape` first. The spec's table lists these the other way round; the reference does not.
    ImageKind.THUMB: ("landscape", "thumb"),
}

#: Backdrop families: the base name, and the prefix its numbered variants use. `backdrop` is the
#: odd one - its variants carry **no dash**, so `backdrop1` rather than `backdrop-1`.
BACKDROP_FAMILIES: tuple[tuple[str, str], ...] = (
    ("fanart", "fanart-"),
    ("background", "background-"),
    ("art", "art-"),
    ("backdrop", "backdrop"),
)

#: A folder of extra backdrops, taken whole. A long-standing Kodi convention the reference honours.
EXTRA_FANART = "extrafanart"

#: The types that get no images of their own beyond a Primary: an episode, a track and a person
#: are not given a logo, a banner or a backdrop by the reference
#: `[source: MediaBrowser.LocalMetadata/Images/LocalImageProvider.cs:190-255 @ v10.11.11]`.
PRIMARY_ONLY: frozenset[ItemType] = frozenset({ItemType.EPISODE, ItemType.AUDIO, ItemType.PERSON})


# ----------------------------------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------------------------------


def find_artwork(directory: Path, kind: ItemType, stem: str | None = None) -> ArtworkResult:
    """Every local image for an item of `kind` sitting in `directory`.

    `stem` is the item's first file's name without its extension, for the two per-item forms:
    `Film (1999).jpg`, which beats every folder name, and `Film (1999)-poster.jpg`, which is what
    lets two films share a folder without sharing a poster.
    """
    try:
        present = _by_name(directory)
    except OSError as exc:
        return ArtworkResult(warnings=(f"{directory}: {exc.strerror or exc}",))

    found: list[ArtworkFile] = []
    warnings: list[str] = []

    _primary(found, warnings, present, kind, stem)
    if kind not in PRIMARY_ONLY:
        for image_kind, names in SIMPLE_NAMES.items():
            _first_match(found, warnings, present, names, image_kind, stem)
        _first_match(found, warnings, present, _disc_names(kind), ImageKind.DISC, stem)
        _backdrops(found, warnings, present, directory, stem)

    return ArtworkResult(files=tuple(found), warnings=tuple(warnings))


def _by_name(directory: Path) -> Mapping[str, Path]:
    """Every image file in `directory`, keyed by its lowercased stem.

    One listing rather than a `stat` per candidate name: the tables try dozens of names per item,
    and a folder holding a season of a series would otherwise cost hundreds of syscalls.
    """
    found: dict[str, Path] = {}
    for entry in sorted(directory.iterdir()):
        if entry.is_file() and entry.suffix.lower() in EXTENSIONS:
            found.setdefault(entry.stem.lower(), entry)
    return found


def _primary(
    found: list[ArtworkFile],
    warnings: list[str],
    present: Mapping[str, Path],
    kind: ItemType,
    stem: str | None,
) -> None:
    """The per-item name first, then the type's own list.

    The bare stem beating every folder name is what makes a mixed folder work at all: two films in
    one directory each have `<their name>.jpg`, and neither takes the other's.
    """
    names = PRIMARY_NAMES.get(kind, DEFAULT_PRIMARY_NAMES)
    candidates = ([stem] if stem else []) + [f"{stem}-{name}" for name in names if stem]
    _first_match(found, warnings, present, (*candidates, *names), ImageKind.PRIMARY, None)


def _disc_names(kind: ItemType) -> tuple[str, ...]:
    return DISC_NAMES.get(kind, ("disc", "cdart"))


def _first_match(
    found: list[ArtworkFile],
    warnings: list[str],
    present: Mapping[str, Path],
    names: Sequence[str],
    image_kind: ImageKind,
    stem: str | None,
) -> None:
    """The first name that exists **and is readable** wins.

    Readability is part of the rule rather than a check after it: a `poster.jpg` that is a line of
    text must not stop `folder.png` from becoming the Primary, or one corrupt file leaves an item
    with no image at all while a perfectly good one sits beside it.
    """
    for name in _with_prefix(names, stem):
        path = present.get(name.lower())
        if path is None:
            continue
        described = describe(path)
        if described is None:
            warnings.append(f"{path}: not an image this build can identify")
            continue
        found.append(_file(path, image_kind, 0, described))
        return


def _backdrops(
    found: list[ArtworkFile],
    warnings: list[str],
    present: Mapping[str, Path],
    directory: Path,
    stem: str | None,
) -> None:
    """**Every** backdrop, in the reference's order, indexed from zero as they are found.

    Backdrops are the one type that accumulates. The index is the position in this list rather
    than the number in the file name, because the file names are sparse by nature - `fanart-1` and
    `fanart-5` with nothing between them is an ordinary library - and `BackdropImageTags` is a
    dense array.
    """
    images: list[Path] = []
    if stem:
        images.extend(_present(present, (f"{stem}-fanart",)))
    for base, prefix in BACKDROP_FAMILIES:
        images.extend(_present(present, (base,)))
        images.extend(_numbered(present, prefix))
    images.extend(_extra_fanart(directory))

    for path in _unique(images):
        described = describe(path)
        if described is None:
            warnings.append(f"{path}: not an image this build can identify")
            continue
        found.append(
            _file(
                path,
                ImageKind.BACKDROP,
                sum(1 for one in found if one.kind is ImageKind.BACKDROP),
                described,
            )
        )


def _numbered(present: Mapping[str, Path], prefix: str) -> Iterator[Path]:
    """`prefix1` … `prefix20`, stopping after three consecutive misses.

    Not at the first gap: a library that had `fanart-1` through `fanart-6` and lost the third
    would otherwise lose the last three as well.
    """
    misses = 0
    for number in range(1, MAX_NUMBERED + 1):
        path = present.get(f"{prefix}{number}".lower())
        if path is None:
            misses += 1
            if misses >= CONSECUTIVE_MISSES:
                return
            continue
        misses = 0
        yield path


def _extra_fanart(directory: Path) -> Iterator[Path]:
    folder = directory / EXTRA_FANART
    if not folder.is_dir():
        return
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.is_file() and entry.suffix.lower() in EXTENSIONS:
            yield entry


def _present(present: Mapping[str, Path], names: Iterable[str]) -> Iterator[Path]:
    for name in names:
        path = present.get(name.lower())
        if path is not None:
            yield path


def _with_prefix(names: Sequence[str], stem: str | None) -> Iterator[str]:
    if stem:
        for name in names:
            yield f"{stem}-{name}"
    yield from names


def _unique(paths: Iterable[Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            yield path


def _file(path: Path, kind: ImageKind, index: int, described: tuple[int, int, str]) -> ArtworkFile:
    width, height, tag = described
    return ArtworkFile(path=path, kind=kind, index=index, width=width, height=height, tag=tag)


# ----------------------------------------------------------------------------------------------
# Measuring
# ----------------------------------------------------------------------------------------------


def describe(path: Path) -> tuple[int, int, str] | None:
    """`(width, height, tag)`, or `None` if this is not an image.

    Pillow's `open` parses the header and stops; no pixel is decoded here, which is what keeps
    this cheap enough to run over every file in a library. The tag is hashed from the same bytes
    the dimensions were read from, so the two can never describe different files.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.debug("%s: %s", path, exc)
        return None
    return describe_bytes(raw)


def describe_bytes(raw: bytes) -> tuple[int, int, str] | None:
    """The same, for bytes that never were a file - embedded cover art."""
    import io

    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.debug("unidentifiable image: %s", exc)
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height, tag_of(raw)


def tag_of(raw: bytes) -> str:
    """The content tag: 32 lowercase hex, stable for as long as the bytes are."""
    return hashlib.sha256(raw).hexdigest()[: TAG_BYTES * 2]


# ----------------------------------------------------------------------------------------------
# Embedded cover art
# ----------------------------------------------------------------------------------------------


def with_embedded(result: ArtworkResult, art: EmbeddedArt | None) -> ArtworkResult:
    """Embedded cover art becomes a `Primary` **only when no file-based one exists**.

    Spec section 3.4, and the order is the point: a user who drops a `folder.jpg` beside an album
    has overridden whatever the files carry, and a reader that preferred the embedded copy would
    make that edit do nothing.
    """
    if art is None or any(one.kind is ImageKind.PRIMARY for one in result.files):
        return result

    described = describe_bytes(art.data)
    if described is None:
        return ArtworkResult(
            files=result.files,
            warnings=(*result.warnings, "embedded cover art is not an image this build can read"),
        )

    width, height, tag = described
    embedded = ArtworkFile(
        # No path: the bytes are inside the audio file, which is what `source_kind = 'embedded'`
        # means in the schema and why that row's `relative_path` is null.
        path=Path(),
        kind=ImageKind.PRIMARY,
        index=0,
        width=width,
        height=height,
        tag=tag,
    )
    return ArtworkResult(files=(embedded, *result.files), warnings=result.warnings)


__all__ = [
    "BACKDROP_FAMILIES",
    "DEFAULT_PRIMARY_NAMES",
    "DISC_NAMES",
    "EXTENSIONS",
    "PRIMARY_NAMES",
    "PRIMARY_ONLY",
    "SIMPLE_NAMES",
    "ArtworkFile",
    "ArtworkResult",
    "ImageKind",
    "describe",
    "describe_bytes",
    "find_artwork",
    "tag_of",
    "with_embedded",
]
