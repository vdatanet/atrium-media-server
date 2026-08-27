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

**A file that has gone is now soft-deleted** (003 plan section 6.6): `removed_at` is set, the row
stays, and everything a user did with that item is still keyed to an identifier that derives again
the moment the file comes back. A re-download, a remount or a share that was slow to mount
therefore costs nobody their favourites - and a returning file **revives the same item**, because
the identifier comes from the path and the path has not changed.

**A scan never purges.** Hard deletion is an operator's decision and lives in
`library/maintenance.py`, which this module does not import - a test asserts that, because a scan
that merely *chose* not to purge would be one refactor away from purging.

**One transaction per library** (plan section 6.7). SQLite has a single writer, so a commit per
item would make a first scan of a large library take orders of magnitude longer than the walk that
found it. `scan` never commits: it writes inside the transaction its caller opened, which is what
makes the batching structural rather than a habit.

**Three guards run before anything is written**, and they *refuse* rather than report - raising
inside the caller's transaction, which rolls it back, so "removes nothing" is a property of the
transaction rather than of this function remembering to stop. They constrain a scanner that cannot
yet delete, which is the whole reason they are written first: the capability arrives at T17 into a
world where the thing that limits it already exists and is already proven.

Guard two is the one that matters. **An unmounted share and an emptied directory are
indistinguishable by a readability check** - both are a directory that lists nothing - so the only
way to tell them apart is to remember that this library used to have files in it.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
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

#: How much of a library may disappear before a scan refuses to believe it (plan section 6.5,
#: rule 3). A quarter: high enough that pruning a season or a few albums proceeds, low enough that
#: a half-mounted share is caught. An operator who really did delete a third of their films passes
#: `confirm_removals`, which is a decision somebody makes rather than a threshold nobody notices.
DEFAULT_REMOVAL_THRESHOLD = 0.25


class ScanRefusedError(RuntimeError):
    """A guard stopped the scan before it wrote anything.

    One base type because a caller's response is the same to all three: report it to the operator
    and change nothing. The subclasses exist so that a caller *can* tell them apart, and so that a
    test asserts which guard fired rather than that some guard did.
    """


class RootUnreadableError(ScanRefusedError):
    """Guard one: a root is missing, is not a directory, or cannot be listed (AC-12)."""


class RootSuddenlyEmptyError(ScanRefusedError):
    """Guard two: a root that used to hold files now holds none.

    **The one that matters.** An unmounted share and an emptied directory are indistinguishable by
    a readability check - both are a directory that lists nothing - so the only way to tell them
    apart is to remember that this library used to have files in it. Treating the first as the
    second is the single most destructive thing a scanner can do.
    """


class TooManyRemovalsError(ScanRefusedError):
    """Guard three: more of the library disappeared than a threshold allows.

    The slower version of the same accident: a root that is *partly* wrong. Guard two never fires
    for it, because the root still yields something.
    """


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
    """Items whose files are gone, marked `removed_at`. **Soft**: the row stays and so does the
    user data keyed to its identifier (spec section 3.8)."""

    revived: int = 0
    """Items whose files came back, brought out of removal **with the same identifier**."""

    missing: int = 0
    """Items in the database whose files are no longer on disk.

    The same number as `removed` in an ordinary scan; it stays a separate field because guard
    three counts it *before* deciding whether to act, and a scan that refuses reports a `missing`
    with a `removed` of zero.
    """

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
    *,
    removal_threshold: float = DEFAULT_REMOVAL_THRESHOLD,
    confirm_removals: bool = False,
) -> ScanReport:
    """Bring the database into line with what is on disk, **adding and updating only**.

    Writes inside the caller's transaction and never commits, so a caller that opens one unit of
    work per library gets one transaction per library, and a caller that opens one per item gets
    what it asked for and deserves.

    Raises `ScanRefusedError` before writing anything when one of the three guards of plan section
    6.5 fires. Raising rather than returning is deliberate: a returned report can be ignored by a
    caller in a hurry, and an exception rolls the caller's transaction back on its way out.
    """
    paths = _root_paths(library, roots)
    _require_readable_roots(library, paths)

    walked = _walk_every_root(library, paths)
    repository = ItemRepository(session)
    existing = repository.by_library(library.id)

    # `confirm_removals` lifts guards two and three and **not** guard one. Both of those refuse a
    # loss the operator may have meant, and both of their messages end by saying to scan again with
    # removals confirmed - so both have to honour it, or the message is a lie. Guard one refuses a
    # root that is broken rather than empty, which is not something anybody confirms.
    if not confirm_removals:
        _require_not_suddenly_empty(library, walked, existing)

    resolution = resolve(library, walked.candidates, source)

    found = {item.id for item in resolution.items}
    # Already-removed items are not missing *again*. Counting them would make the guard fire on
    # every scan after a large removal, forever, with nothing left to protect.
    missing = [
        item
        for item in existing.values()
        if item.id not in found and item.is_file_backed and not item.is_removed
    ]
    if not confirm_removals:
        _require_removals_under_threshold(library, missing, existing, removal_threshold)

    # A collision is a bug in the derivation, not user error, and merging two files into one item
    # would hide it until somebody reported a film playing the wrong file (plan section 7).
    ensure_unique(
        (item.id, item.relative_path or item.name)
        for item in resolution.items
        if item.is_file_backed
    )

    now = utc_now()
    added = updated = unchanged = 0
    returning: list[str] = []

    for item in sorted(resolution.items, key=lambda one: (_DEPTH[one.type], one.id)):
        before = existing.get(item.id)
        if before is None:
            repository.add(replace(item, date_created=now, date_modified=now))
            added += 1
            continue
        if before.is_removed:
            # The file came back. Same path, same derivation, same identifier - so the user data
            # keyed to it is still there and was never disturbed (spec section 3.8).
            returning.append(item.id)
        if _differs(before, item):
            repository.update(replace(item, date_modified=now))
            updated += 1
        else:
            unchanged += 1

    revived = repository.revive(returning)

    removed = repository.mark_removed([item.id for item in missing], now)
    return ScanReport(
        library_id=library.id,
        added=added,
        updated=updated,
        unchanged=unchanged,
        removed=removed,
        revived=revived,
        missing=len(missing),
        skipped=walked.skipped,
    )


def _root_paths(library: Library, roots: Iterable[Path] | None) -> list[Path]:
    """Sorted, so that two scans of one library agree whatever order the configuration listed
    them in (spec section 3.8)."""
    return sorted(Path(root) for root in (roots if roots is not None else library.roots))


def _walk_every_root(library: Library, paths: Sequence[Path]) -> WalkResult:
    """Every configured root, walked and merged into one result."""
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    for root in paths:
        result = walk(root, library.collection_type)
        candidates.extend(result.candidates)
        skipped.extend(result.skipped)
    return WalkResult(candidates=tuple(candidates), skipped=tuple(skipped))


# ----------------------------------------------------------------------------------------------
# The three guards of plan section 6.5
#
# Separate functions on purpose. Each destructive test removes exactly one of them and asserts the
# damage it was preventing - which is only possible if there is exactly one thing to remove.
# ----------------------------------------------------------------------------------------------


def _require_readable_roots(library: Library, paths: Sequence[Path]) -> None:
    """Guard one (AC-12). Every root exists, is a directory, and can actually be listed.

    Listed, not merely `is_dir`. A directory whose permissions forbid reading still stats as a
    directory, so the check that matters is whether an entry can be taken out of it.
    """
    if not paths:
        raise RootUnreadableError(
            f"library {library.id} has no roots configured, so a scan of it would find nothing "
            f"and could not tell that from a library whose files have all gone."
        )
    for root in paths:
        try:
            if not root.is_dir():
                raise RootUnreadableError(
                    f"{str(root)!r} is not a directory. The scan of library {library.id} is "
                    f"abandoned and nothing is changed: a root that is not there is not the same "
                    f"as a root with nothing in it (spec section 3.8)."
                )
            with os.scandir(root) as entries:
                next(entries, None)
        except OSError as exc:
            raise RootUnreadableError(
                f"{str(root)!r} cannot be read ({exc.strerror}). The scan of library "
                f"{library.id} is abandoned and nothing is changed."
            ) from exc


def _require_not_suddenly_empty(
    library: Library, walked: WalkResult, existing: dict[str, Item]
) -> None:
    """Guard two. A root that yields nothing, having previously yielded something, aborts.

    The condition is *previously*: a genuinely new and empty library scans happily, and so does one
    an operator has really emptied on purpose - the second time, once the first refusal has told
    them what happened and they have removed the library or confirmed the removals.
    """
    if walked.candidates:
        return
    had = [item for item in existing.values() if item.is_file_backed]
    if not had:
        return
    raise RootSuddenlyEmptyError(
        f"library {library.id} previously held {len(had)} file(s) and its roots now yield none. "
        f"That is what an unmounted share looks like, and it is indistinguishable from a directory "
        f"somebody emptied - so the scan is abandoned and nothing is changed. Check the mount; if "
        f"the files really are gone, scan again with removals confirmed."
    )


def _require_removals_under_threshold(
    library: Library, missing: Sequence[Item], existing: dict[str, Item], threshold: float
) -> None:
    """Guard three. More than `threshold` of a library disappearing stops the scan.

    Measured against the file-backed items only. Containers come and go as their children do, so
    counting them would make a renamed series look like a mass deletion.
    """
    held = [item for item in existing.values() if item.is_file_backed]
    if not held or not missing:
        return
    proportion = len(missing) / len(held)
    if proportion <= threshold:
        return
    raise TooManyRemovalsError(
        f"{len(missing)} of library {library.id}'s {len(held)} files are gone "
        f"({proportion:.0%}, over the {threshold:.0%} this scan will act on without being asked). "
        f"A root that is *partly* wrong looks exactly like this, and guard two does not fire for "
        f"it because the root still yields something. Nothing is changed. Check the mount; if the "
        f"files really are gone, scan again with removals confirmed."
    )


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


__all__ = [
    "DEFAULT_REMOVAL_THRESHOLD",
    "RootSuddenlyEmptyError",
    "RootUnreadableError",
    "ScanRefusedError",
    "ScanReport",
    "TooManyRemovalsError",
    "scan",
]
