# SPDX-License-Identifier: GPL-3.0-or-later
"""Walk, resolve, diff, write — and **nothing else**.

This module is deliberately incapable of removing an item. Not "careful about it", not "guarded":
there is no code path here that deletes a row, and `ItemRepository` has no method that would let
one. Removal arrives at T17, *after* the guards of
[plan section 6.5](../../../specs/003-library-configuration-and-scanning/plan.md) and their
destructive tests are green at T16.

The reason for that ordering is worth stating, because it looks like test ceremony and is not.
Everything else in a scanner fails *visibly*: a wrong title, a missing item, an ugly sort order.
Deleting a library because a network share mounted empty fails **quietly and irreversibly** - the
identifiers were derived, so nothing stored the old ones, and the first symptom is a user saying
their favourites look wrong weeks later. So for the whole middle of this feature the capability
simply does not exist, and it is granted only once the thing that constrains it does.

**A file that has gone is therefore left exactly as it was.** That is not the final behaviour - 003
spec section 3.8 says it should be soft-deleted and its user data kept - it is the behaviour of a
scanner that has not yet been given the ability, and `ScanReport.removed` stays zero to say so.

**One transaction per library** (plan section 6.7). SQLite has a single writer, so a commit per
item would make a first scan of a large library take orders of magnitude longer than the walk that
found it. `scan` never commits: it writes inside the transaction its caller opened, which is what
makes the batching structural rather than a habit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.db.repositories import ItemRepository
from atrium.domain.items import PARENT_OF, Item, ItemType
from atrium.domain.library import Library
from atrium.library.identity import ensure_unique
from atrium.library.naming import PATH_ONLY, MetadataSource
from atrium.library.resolver import resolve
from atrium.library.walker import Candidate, Skipped, WalkResult, walk


@dataclass(frozen=True, slots=True)
class ScanReport:
    """What one scan of one library did.

    Carries `removed` from the start even though this module can never make it non-zero, so that
    T16's threshold and T17's removals report into one type rather than each inventing half of one.
    """

    library_id: str
    added: int = 0
    updated: int = 0
    unchanged: int = 0

    removed: int = 0
    """**Always zero here.** This scanner has no removal code path at all - see the module
    docstring. T17 grants the capability, after T16 constrains it."""

    skipped: tuple[Skipped, ...] = field(default_factory=tuple)
    """Every file the walk went past, each with its reason (plan section 7)."""

    @property
    def changed(self) -> int:
        return self.added + self.updated

    def reasons(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for one in self.skipped:
            counts[one.reason.value] = counts.get(one.reason.value, 0) + 1
        return counts


#: How deep each type sits, so that a parent is always written before its children.
#:
#: Explicit rather than left to the unit of work. `parent_id` is set as a column here rather than
#: through the `Item.parent` relationship, and a self-referential foreign key set that way tells
#: SQLAlchemy nothing about which row has to go first - T6 found the same thing between tables.
def _depth_of(item_type: ItemType) -> int:
    depth, current = 0, PARENT_OF[item_type]
    while current is not None:
        depth, current = depth + 1, PARENT_OF[current]
    return depth


_DEPTH: dict[ItemType, int] = {one: _depth_of(one) for one in ItemType}


def scan(
    library: Library,
    session: OrmSession,
    roots: Iterable[Path] | None = None,
    source: MetadataSource = PATH_ONLY,
) -> ScanReport:
    """Bring the database into line with what is on disk, **adding and updating only**.

    Writes inside the caller's transaction and never commits, so a caller that opens one unit of
    work per library gets one transaction per library, and a caller that opens one per item gets
    what it asked for and deserves.
    """
    walked = _walk_every_root(library, roots)
    resolution = resolve(library, walked.candidates, source)

    # A collision is a bug in the derivation, not user error, and merging two files into one item
    # would hide it until somebody reported a film playing the wrong file (plan section 7).
    ensure_unique(
        (item.id, item.relative_path or item.name)
        for item in resolution.items
        if item.is_file_backed
    )

    repository = ItemRepository(session)
    existing = repository.by_library(library.id)
    now = utc_now()
    added = updated = unchanged = 0

    for item in sorted(resolution.items, key=lambda one: (_DEPTH[one.type], one.id)):
        before = existing.get(item.id)
        if before is None:
            repository.add(replace(item, date_created=now, date_modified=now))
            added += 1
        elif _differs(before, item):
            repository.update(replace(item, date_modified=now))
            updated += 1
        else:
            unchanged += 1

    # Whatever is in `existing` and not in the resolution stays exactly where it is. There is no
    # branch here for it, deliberately.
    return ScanReport(
        library_id=library.id,
        added=added,
        updated=updated,
        unchanged=unchanged,
        skipped=walked.skipped,
    )


def _walk_every_root(library: Library, roots: Iterable[Path] | None) -> WalkResult:
    """Every configured root, walked in a fixed order and merged into one result.

    Roots are sorted so that two scans of the same library produce the same order whatever order
    the configuration happened to list them in (spec section 3.8).
    """
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    paths = sorted(Path(root) for root in (roots if roots is not None else library.roots))
    for root in paths:
        result = walk(root, library.collection_type)
        candidates.extend(result.candidates)
        skipped.extend(result.skipped)
    return WalkResult(candidates=tuple(candidates), skipped=tuple(skipped))


def _differs(before: Item, after: Item) -> bool:
    """Whether a rescan found anything worth writing.

    `date_modified` is not compared - it is set *because* something changed, so comparing it would
    make every item differ from itself and turn every rescan into a full rewrite.
    """
    return (
        before.name != after.name
        or before.sort_name != after.sort_name
        or before.parent_id != after.parent_id
        or before.index_number != after.index_number
        or before.parent_index_number != after.parent_index_number
        or before.end_index_number != after.end_index_number
        or before.sources != after.sources
    )


__all__ = ["ScanReport", "scan"]
