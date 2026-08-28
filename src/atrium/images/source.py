# SPDX-License-Identifier: GPL-3.0-or-later
"""From a stored row to the bytes it names, through three different readings.

004 decided which file is which image at scan time and wrote it down; this opens exactly the file
the row names and never re-runs discovery (006 plan section 6.2). The three `source_kind` values
are three different places to look, and they are not interchangeable:

| `source_kind` | The carrier |
|---|---|
| `file` | the **first** configured root of the item's library under which `relative_path` exists |
| `embedded` | the item's part-zero source file, read through `metadata/tags` |
| `remote` | the data directory joined with `relative_path` (the row spells `metadata/artwork/`) |

**Every open is preceded by a containment check.** The rows are server-written, so an escape is
"impossible" - and the check is what turns impossible into asserted. A row carrying `../../etc`
is refused rather than resolved, and a test crafts one to prove the refusal happens (plan
section 9).

**The two refusals are decided here, not in `db/`.** Which of the reference's two `404` bodies a
request gets depends on *which* lookup failed (behaviours section 1.11), and that is a wire shape:
the repository reports what it found and this module names the refusal.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from atrium.compat.errors import ImageNotFoundError, ItemNotFoundError
from atrium.db.repositories import ImageLocation, ImageLookup
from atrium.metadata.artwork import SourceKind
from atrium.metadata.tags import read_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Carrier:
    """The bytes as they sit on disk, and when the file holding them last changed.

    `last_modified` is the **carrier's** mtime rather than the row's or the item's: no item and no
    media source carries a wire modification time at all (behaviours section 2.17), and the
    filesystem is the only truthful clock this feature has. A transformed variant is as old as
    what it derives from, which is what makes the validator stable across rescans that change
    nothing.
    """

    payload: bytes
    last_modified: datetime


def require(lookup: ImageLookup, image_type: str) -> ImageLocation:
    """The located row, or the refusal that says which half of the lookup failed.

    Two `404`s on one route, and the split is not cosmetic: an unknown item answers problem
    details, an item that exists and lacks the image answers the message shape naming it
    `[probe: manual requests via tools/_probe.py, Jellyfin 10.11.11, 2026-08-28]`.
    """
    if lookup.item_name is None:
        raise ItemNotFoundError
    if lookup.location is None:
        raise ImageNotFoundError(lookup.item_name, image_type)
    return lookup.location


def read(location: ImageLocation, *, data_dir: Path) -> Carrier:
    """The bytes this row names, whichever of the three readings it takes.

    Every way of failing to produce them is the **same** refusal - the absent-image `404` - and
    that is deliberate: a client cannot act on the difference between a row whose file was deleted,
    a row whose art was stripped and a row a test crafted to escape a root, and telling it which
    would describe the server's filesystem to anyone holding an item id.
    """
    if location.source_kind is SourceKind.EMBEDDED:
        return _embedded(location)
    if location.source_kind is SourceKind.REMOTE:
        return _remote(location, data_dir)
    return _file(location)


# ------------------------------------------------------------------------------------------
# The three readings
# ------------------------------------------------------------------------------------------


def _file(location: ImageLocation) -> Carrier:
    """The first root the relative path exists under.

    First-that-exists rather than `roots[0]`: a library may have several roots and an image lives
    under exactly one of them, which is the reading `metadata/refresh.py` already uses. A library
    with one root cannot tell the two apart, so the fixture gives this one two.
    """
    relative = location.relative_path
    if relative is None:
        raise _absent(location, "a file row with no path")
    for root in location.library_roots:
        candidate = _contained(Path(root), relative)
        if candidate is not None and candidate.is_file():
            return _open(location, candidate)
    raise _absent(location, f"no configured root holds {relative}")


def _remote(location: ImageLocation, data_dir: Path) -> Carrier:
    """Under the data directory, never inside a library root (004 AC-15, `config/paths.py`)."""
    relative = location.relative_path
    if relative is None:
        raise _absent(location, "a remote row with no path")
    candidate = _contained(data_dir, relative)
    if candidate is None or not candidate.is_file():
        raise _absent(location, f"{relative} is not under the data directory")
    return _open(location, candidate)


def _embedded(location: ImageLocation) -> Carrier:
    """Out of the audio file itself, through the reader the scan used.

    Re-extracted per request rather than materialised at scan time: writing it to disk duplicates
    bytes the library already holds, and nothing has measured the tag parse as a problem (plan
    section 10). The transformed variants of it cache like any other source.
    """
    carrier = location.carrier_path
    if carrier is None:
        raise _absent(location, "an embedded row on an item with no source")
    for root in location.library_roots:
        candidate = _contained(Path(root), carrier)
        if candidate is None or not candidate.is_file():
            continue
        art = read_tags(candidate).art
        if art is None:
            # The row promises a picture and the file has none: the art was stripped since the
            # scan. A warning rather than a `5xx`, and the next scan drops the row (plan 7).
            raise _absent(location, f"{candidate} carries no embedded art any more")
        return Carrier(payload=art.data, last_modified=_mtime(candidate))
    raise _absent(location, f"no configured root holds {carrier}")


# ------------------------------------------------------------------------------------------
# Opening, containment, refusing
# ------------------------------------------------------------------------------------------


def _contained(base: Path, relative: str) -> Path | None:
    """`base / relative`, or `None` if that lands outside `base`.

    The check is on the **resolved** paths, so `..` segments and a symlink pointing out of the
    tree are both caught - resolving first is what makes the second case reachable at all. A row
    that fails this is refused; nothing is opened and nothing about the filesystem is reported.
    """
    try:
        candidate = (base / relative).resolve()
        root = base.resolve()
    except OSError:
        return None
    if candidate != root and root not in candidate.parents:
        return None
    return candidate


def _open(location: ImageLocation, path: Path) -> Carrier:
    try:
        return Carrier(payload=path.read_bytes(), last_modified=_mtime(path))
    except OSError as exc:
        raise _absent(location, f"{path}: {exc.strerror or exc}") from exc


def _mtime(path: Path) -> datetime:
    """The carrier's modification time, in UTC. Whole seconds are what the validator compares at
    (plan section 6.6), and the truncation happens where the header is written rather than here."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)


def _absent(location: ImageLocation, why: str) -> ImageNotFoundError:
    """The one refusal, with the reason in the log rather than on the wire."""
    logger.warning(
        "image %s/%s of %s cannot be served: %s",
        location.image_type,
        location.index,
        location.item_id,
        why,
    )
    return ImageNotFoundError(location.item_name, location.image_type)


__all__ = ["Carrier", "read", "require"]
