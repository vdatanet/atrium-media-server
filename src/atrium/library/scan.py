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

**A file whose size and modification time have not moved is not examined again** (plan
section 6.4). "Examined" means the only content-reading this feature does: asking a
`MetadataSource` what is embedded in the file. Everything else here reads paths, which are free.

The signal is not a guess about the file, it is a guess about *whether looking would tell us
anything new* - so getting it wrong is a missed update rather than a wrong item, and `deep=True`
is the escape hatch for a filesystem where the guess is unsafe. **It is measurably unsafe on an
ordinary one**: `cp -p`, `rsync -a` and an unpacked archive all restore the modification time, so
a file replaced by a same-sized copy is invisible to any signal built from `(size, mtime_ns)`.

Skipping the examination cannot produce a wrong item, and the reason is worth stating because it
is what makes the whole thing safe. **No file-backed identity depends on a tag** - a `Movie`, an
`Episode` and an `Audio` are all identified by their path - so an unexamined file resolves to the
*same* item it did last time, and that item is then thrown away in favour of the row already in
the database. The resolution of an unexamined file is never written; it exists only to find out
which row to keep.

**What it did and what it walked past are reported separately**, and `library/report.py` says
why at length: a skipped file produced no item and a noticed one did, so an operator told that two
files were skipped when one of them is sitting in their library has been told something false.

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

import logging
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from pathlib import Path

from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.db.repositories import ItemRepository, MediaProbeRepository, MetadataRepository
from atrium.domain.items import IN_THE_TREE, PARENT_OF, Item, ItemType
from atrium.domain.library import Library
from atrium.domain.media import MediaInspection
from atrium.library.identity import ensure_unique
from atrium.library.naming import MetadataSource
from atrium.library.report import Phase, Progress, ProgressSink, ScanReport, Uninspected, silent
from atrium.library.resolver import Resolution, resolve
from atrium.library.walker import Candidate, Skipped, WalkResult, walk
from atrium.media.probe import InspectionError, ProberUnavailableError
from atrium.media.probe import inspect as inspect_media
from atrium.metadata.model import RefreshMode
from atrium.metadata.refresh import pending_and_touched, refresh_items
from atrium.metadata.tags import MemoisedSource, TagSource

#: How much of a library may disappear before a scan refuses to believe it (plan section 6.5,
#: rule 3). A quarter: high enough that pruning a season or a few albums proceeds, low enough that
#: a half-mounted share is caught. An operator who really did delete a third of their films passes
#: `confirm_removals`, which is a decision somebody makes rather than a threshold nobody notices.
DEFAULT_REMOVAL_THRESHOLD = 0.25

#: What a scan calls to find out what is inside a media file. A seam rather than a direct call,
#: because the hundreds of dummy-byte files in the 003 and 004 fixtures are not media and every one
#: of them would cost a process launch and a refusal - so those suites pass a stub and keep their
#: speed, while a real server gets the real prober by default.
MediaProber = Callable[[Path], MediaInspection]

logger = logging.getLogger(__name__)


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


#: Over `IN_THE_TREE`, not over `ItemType`. 004's five by-name types have no parent and no depth,
#: and a scan never writes one - they are created by a refresh, from a name an item mentions. A
#: `KeyError` here would be the honest failure if that ever stopped being true.
_DEPTH: dict[ItemType, int] = {one: _depth_of(one) for one in IN_THE_TREE}


def scan(
    library: Library,
    session: OrmSession,
    roots: Iterable[Path] | None = None,
    source: MetadataSource | None = None,
    *,
    deep: bool = False,
    refresh: bool = True,
    refresh_mode: RefreshMode = RefreshMode.DEFAULT,
    providers: Sequence[object] = (),
    removal_threshold: float = DEFAULT_REMOVAL_THRESHOLD,
    confirm_removals: bool = False,
    prober: MediaProber | None = None,
    progress: ProgressSink = silent,
) -> ScanReport:
    """Bring the database into line with what is on disk.

    `deep` ignores the change-detection signal and examines every file (plan section 6.4). The
    default is fast and the escape hatch exists; neither pretends to be the other. Use it when the
    modification times cannot be trusted - a filesystem that rounds them, a restore that put them
    back, a library whose tags were rewritten in place by a tool that preserved both size and time.

    Writes inside the caller's transaction and never commits, so a caller that opens one unit of
    work per library gets one transaction per library, and a caller that opens one per item gets
    what it asked for and deserves.

    Raises `ScanRefusedError` before writing anything when one of the three guards of plan section
    6.5 fires. Raising rather than returning is deliberate: a returned report can be ignored by a
    caller in a hurry, and an exception rolls the caller's transaction back on its way out.

    `prober` is what opens a media file to find out what is inside it, and defaults to the real
    one (008 plan section 6.1). It is injectable because the fixture libraries of 003 and 004 are
    thousands of files of dummy bytes: a suite that ran the real prober over them would pay a
    process launch per file to be told, correctly, that none of them is media.

    `progress` is called as the scan moves through its four phases (plan section 6.7) and defaults
    to reporting to nobody. **A guard that refuses raises without a final report**, which is
    correct: there is no summary of a scan that did not happen, and a progress sink that had been
    told "walking, 3 of 3 roots" and then hears nothing more is being told the truth.
    """
    paths = _root_paths(library, roots)
    _require_readable_roots(library, paths)

    # **`None` means read the files**, and that is the default because the alternative failed
    # silently: a scan whose source has to be injected resolves a well-tagged music library from
    # its directory names the first time somebody forgets, and the symptom - albums named after
    # folders - looks like a scanning bug rather than a missing argument. `PATH_ONLY` is still
    # passable and still what a server with no reader runs on (003's `PathOnly`).
    if source is None:
        source = TagSource(paths)
    # **One ask per file per scan**, whatever the source is, and one object answering both the
    # resolver's question and the refresh's. `TagSource` memoises for its own reasons; an
    # arbitrary `MetadataSource` does not, and both halves ask - so without this a caller's reader
    # is consulted twice for every changed file, which is the cost 003 wrote the memo to avoid,
    # reintroduced by the feature the memo was written for.
    reader = MemoisedSource(source)

    report = _Reporter(progress, library.id)
    walked = _walk_every_root(library, paths, report)
    repository = ItemRepository(session)
    existing = repository.by_library(library.id)

    # `confirm_removals` lifts guards two and three and **not** guard one. Both of those refuse a
    # loss the operator may have meant, and both of their messages end by saying to scan again with
    # removals confirmed - so both have to honour it, or the message is a lie. Guard one refuses a
    # root that is broken rather than empty, which is not something anybody confirms.
    if not confirm_removals:
        _require_not_suddenly_empty(library, walked, existing)

    # Change detection, plan section 6.4. The classification is made **before** resolution
    # because what it gates is the examination itself: an unchanged file is never asked what is
    # inside it. `deep` empties the set, which is the whole of what `deep` does.
    unchanged_paths = frozenset() if deep else _unchanged_paths(walked, existing)
    examined = len(walked.candidates) - len(unchanged_paths)

    # Reported once, after the fact, because `resolve` is a single pure call with nothing to
    # interrupt it. Emitting a made-up gradient across it would be a progress bar animating while
    # nothing is measured, which is the failure this whole module is trying not to be.
    resolution = resolve(library, walked.candidates, _OnlyChanged(reader, unchanged_paths))
    kept = _reconcile(resolution, existing, deep=deep)
    report(
        Phase.RESOLVING,
        len(walked.candidates),
        len(walked.candidates),
        f"{len(kept)} item(s)",
    )

    found = set(kept)
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
        (item.id, item.relative_path or item.name) for item in kept.values() if item.is_file_backed
    )

    # **Inspection, behind the same idea as change detection and against a different table.**
    # After the three guards, because it is the slowest thing here and a scan that is about to
    # refuse should refuse before opening a thousand files. A file is opened when what is stored
    # about its bytes no longer describes them - or when
    # nothing is stored, which is every file the first time a library is scanned after 008. That
    # is `MediaProbeRepository.current`'s whole reason for existing, and it is deliberately not
    # `unchanged_paths`: those compare against `item_sources`, which is in step with the disk long
    # before any probe row exists, so reusing them would leave a library permanently uninspected.
    inspected, uninspected = _inspect_media(
        library, session, paths, walked, prober or inspect_media, deep=deep, report=report
    )

    now = utc_now()
    added = updated = unchanged = 0
    returning: list[str] = []
    # Asked once. An item 004 has resolved has a name the scanner must not re-derive over -
    # see `ItemRepository.update` and `_differs`.
    resolved = MetadataRepository(session).refreshed(library.id)

    ordered = sorted(kept.values(), key=lambda one: (_DEPTH[one.type], one.id))
    for written, item in enumerate(ordered, start=1):
        report(Phase.WRITING, written, len(ordered))
        before = existing.get(item.id)
        if before is None:
            repository.add(replace(item, date_created=now, date_modified=now))
            added += 1
            continue
        if before.is_removed:
            # The file came back. Same path, same derivation, same identifier - so the user data
            # keyed to it is still there and was never disturbed (spec section 3.8).
            returning.append(item.id)
        if _differs(before, item, names_are_the_scanners=item.id not in resolved):
            repository.update(replace(item, date_modified=now))
            updated += 1
        else:
            unchanged += 1

    revived = repository.revive(returning)

    removed = repository.mark_removed([item.id for item in missing], now)

    # **004's refresh, over what this scan touched.** Last, after every row is written, because a
    # refresh reads the tree it is annotating - a container's directory comes from its children,
    # and those children have to exist first. Inside the caller's transaction like everything else
    # here, so a scan and the refresh that follows it commit or roll back together.
    #
    # `deep` hands it everything: that mode exists for a library whose *contents* changed under
    # unchanged signals, and re-resolving the tree without re-reading the metadata would answer
    # only half the question it was asked.
    refreshed = None
    if refresh:
        touched = (
            list(kept)
            if deep
            else [item.id for item in ordered if _touched(existing, item, resolved)]
        )
        refreshed = refresh_items(
            library,
            session,
            pending_and_touched(session, library, touched),
            mode=refresh_mode,
            providers=providers,  # type: ignore[arg-type]
            # **The same reader, for both halves of the scan.** Passing `None` here would let the
            # refresh build one of its own, so a caller who asked for `PATH_ONLY` would get a
            # path-only tree and a tag-read refresh - an opt-out that worked for half the scan.
            tags=reader,
            roots=paths,
        )

    return ScanReport(
        library_id=library.id,
        added=added,
        updated=updated,
        unchanged=unchanged,
        examined=examined,
        inspected=inspected,
        uninspected=uninspected,
        removed=removed,
        revived=revived,
        missing=len(missing),
        skipped=walked.skipped,
        # Filtered to what was kept, so the report describes the **library** rather than the
        # resolution: a notice about an item this scan decided not to write would be a line an
        # operator could not go and look at.
        noticed=tuple(one for one in resolution.noticed if one.item_id in kept),
        refreshed=refreshed,
    )


def _inspect_media(
    library: Library,
    session: OrmSession,
    roots: Sequence[Path],
    walked: WalkResult,
    prober: MediaProber,
    *,
    deep: bool,
    report: _Reporter,
) -> tuple[int, tuple[Uninspected, ...]]:
    """Open every media file whose stored inspection no longer describes it, and store what it says.

    **An unreadable file costs itself and nothing else.** It is recorded and the walk continues,
    because the item exists either way: 003 gives it an identity from its path, and a scan that
    abandoned the library over one truncated download would lose every other file's inspection to
    a file nobody can play anyway.

    **A missing prober is not a library of unreadable files**, and telling them apart is the whole
    reason `media/probe.py` raises two exceptions. `ProberUnavailableError` is true of every file
    at once, so it stops the phase after the first one and is logged as the operator's problem it
    is - recording thousands of items as uninspectable would bury the one fact that explains them.

    Writes inside the caller's transaction, like everything else here.
    """
    probes = MediaProbeRepository(session)
    inspected = 0
    failed: list[Uninspected] = []
    total = len(walked.candidates)
    for done, candidate in enumerate(walked.candidates, start=1):
        report(Phase.INSPECTING, done, total)
        if not deep and probes.current(
            library.id, candidate.relative_path, candidate.size, candidate.mtime_ns
        ):
            continue
        try:
            probes.put(
                library.id,
                candidate.relative_path,
                prober(_absolute(roots, candidate.relative_path)),
            )
        except ProberUnavailableError as exc:
            logger.error(
                "library %s: no media inspection is possible, so no item will have a media "
                "source until this is fixed: %s",
                library.id,
                exc,
            )
            break
        except InspectionError as exc:
            failed.append(Uninspected(relative_path=candidate.relative_path, reason=str(exc)))
            continue
        inspected += 1
    return inspected, tuple(failed)


def _absolute(roots: Sequence[Path], relative_path: str) -> Path:
    """A candidate's path on disk, from a walk that merged several roots without recording which.

    The first root the file is actually under, and the first root otherwise - the same
    reconstruction `BaseItemDto`'s `Path` makes, so the two can never name different files. A
    library with one root, which is every library in practice, takes the first branch immediately.
    """
    for root in roots:
        candidate = root / relative_path
        if candidate.exists():
            return candidate
    return roots[0] / relative_path


def _touched(existing: Mapping[str, Item], item: Item, resolved: AbstractSet[str]) -> bool:
    """Whether this scan added or changed the item, which is what a refresh is for.

    An unchanged item is not refreshed, and that is not an optimisation: it is the same signal
    003's change detection uses, extended one step further. A rescan of an unchanged library
    therefore does no metadata work at all - which is what AC-13 will rest on once there is a
    network to count requests to.
    """
    before = existing.get(item.id)
    if before is None:
        return True
    # **A revival is not a change.** A file that disappeared and came back is byte-for-byte the
    # file it was; its row kept every column through the soft delete, so re-reading it would open
    # a file whose signal never moved - the one thing 003 wrote this rule to prevent. An item
    # whose refresh actually failed is picked up by `refresh_pending` instead.
    return _differs(before, item, names_are_the_scanners=item.id not in resolved)


# ----------------------------------------------------------------------------------------------
# Change detection (plan section 6.4)
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _OnlyChanged:
    """A `MetadataSource` that declines to look inside a file whose signal has not moved.

    It answers `{}` rather than the previous answer, which sounds wrong and is not: a file's
    **identity never depends on a tag**, so the item this produces has the same id it had last
    time, and `_reconcile` then keeps the stored row and discards this resolution entirely. The
    only thing the empty answer can affect is an item that is about to be thrown away.

    Wrapping the caller's source rather than checking a flag inside the resolver keeps 003's one
    piece of content-reading behind one object, so that when 004 supplies a real reader there is a
    single place where "do not open this file" is decided.
    """

    source: MetadataSource
    unchanged: frozenset[str]

    def tags_for(self, relative_path: str) -> Mapping[str, str]:
        if relative_path in self.unchanged:
            return {}
        return self.source.tags_for(relative_path)


def _unchanged_paths(walked: WalkResult, existing: Mapping[str, Item]) -> frozenset[str]:
    """The candidate files whose `(size, mtime_ns)` is exactly what was stored for them.

    Both halves, not either: size alone misses a re-encode of the same length, and a modification
    time alone misses a filesystem that rounds it. Together they are still a **guess**, and a
    measurably fallible one - `cp -p` and `rsync -a` restore the modification time, so a file
    replaced by a same-sized copy matches here and is skipped. That is what `deep` is for.

    A source with no recorded signal never matches, so a row written by something that did not
    stat the file is re-examined rather than trusted.
    """
    signals = {
        source.relative_path: (source.size, source.mtime_ns)
        for item in existing.values()
        if item.is_file_backed
        for source in item.sources
        if source.size is not None and source.mtime_ns is not None
    }
    return frozenset(
        candidate.relative_path
        for candidate in walked.candidates
        if signals.get(candidate.relative_path) == (candidate.size, candidate.mtime_ns)
    )


def _reconcile(
    resolution: Resolution, existing: Mapping[str, Item], *, deep: bool
) -> dict[str, Item]:
    """The items this scan will write, with an unexamined file's stored row kept in place.

    Two steps, and the second is the one that is easy to miss. **Keeping the stored row** is not
    enough on its own: an unexamined music file resolved from its path alone hangs from an album
    named after its *directory*, and that album is a container this scan invented and must not
    write. So after the substitution the set is rebuilt from the file-backed items upwards, and a
    container nothing ends up under is dropped.

    That pruning changes nothing when no row is kept - every container the resolver produces
    exists because a file asked for it - which is why a first scan, and a `deep` one, are
    unaffected.

    The test for "unchanged" is the whole source tuple rather than one path, so a two-part film
    with one rewritten part is re-examined as one item. Movies never consult a tag, so the two
    tests only ever disagree about an item that could not have been affected either way.
    """
    chosen = {item.id: item for item in resolution.items}
    if not deep:
        for item in resolution.items:
            stored = existing.get(item.id)
            if item.is_file_backed and stored is not None and stored.sources == item.sources:
                chosen[item.id] = stored

    lookup: dict[str, Item] = {**existing, **chosen}
    kept: dict[str, Item] = {}
    for item in chosen.values():
        if item.is_file_backed or item.type is ItemType.COLLECTION_FOLDER:
            _keep_with_ancestors(item, lookup, kept)
    return kept


def _keep_with_ancestors(item: Item, lookup: Mapping[str, Item], into: dict[str, Item]) -> None:
    """This item and every container above it. Stops at one already kept, whose own ancestors
    were kept with it - so the walk up is done once per chain rather than once per child."""
    current: Item | None = item
    while current is not None and current.id not in into:
        into[current.id] = current
        current = lookup.get(current.parent_id) if current.parent_id is not None else None


def _root_paths(library: Library, roots: Iterable[Path] | None) -> list[Path]:
    """Sorted, so that two scans of one library agree whatever order the configuration listed
    them in (spec section 3.8)."""
    return sorted(Path(root) for root in (roots if roots is not None else library.roots))


def _walk_every_root(
    library: Library, paths: Sequence[Path], report: _Reporter | None = None
) -> WalkResult:
    """Every configured root, walked and merged into one result.

    Progress here counts **roots**, not files, and `detail` says which one. How many files a tree
    holds is precisely what this loop is computing, so there is no denominator to report until it
    is over - see `Progress.total`.
    """
    candidates: list[Candidate] = []
    skipped: list[Skipped] = []
    for done, root in enumerate(paths, start=1):
        result = walk(root, library.collection_type)
        candidates.extend(result.candidates)
        skipped.extend(result.skipped)
        if report is not None:
            report(Phase.WALKING, done, len(paths), str(root))
    return WalkResult(candidates=tuple(candidates), skipped=tuple(skipped))


class _Reporter:
    """The only thing that calls the progress sink, so a sink that raises cannot take a scan down.

    A progress sink is somebody else's code - a log line, a websocket, a terminal - and a scan
    destroyed by its own instrumentation would roll back a transaction that had nothing wrong with
    it. So a sink that raises is **disabled for the rest of this scan** and logged once. Once,
    rather than per item: a sink that fails on the first call fails on all of them, and a scan of a
    large library would otherwise write one traceback per file to explain a single broken callback.
    """

    __slots__ = ("_library_id", "_sink", "_working")

    def __init__(self, sink: ProgressSink, library_id: str) -> None:
        self._sink = sink
        self._library_id = library_id
        self._working = True

    def __call__(self, phase: Phase, done: int, total: int | None, detail: str = "") -> None:
        if not self._working:
            return
        try:
            self._sink(Progress(self._library_id, phase, done, total, detail))
        except Exception:
            self._working = False
            logger.exception(
                "progress sink raised; progress for the scan of library %s is disabled for the "
                "rest of this scan. The scan itself continues.",
                self._library_id,
            )


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


def _differs(before: Item, after: Item, *, names_are_the_scanners: bool = True) -> bool:
    """Whether a rescan found anything worth writing.

    `date_modified` is not compared - it is set *because* something changed, so comparing it would
    make every item differ from itself and turn every rescan into a full rewrite.

    **The name is compared only while the scanner still owns it.** Once 004 has resolved a name
    from a sidecar or a tag, the scanner's path-derived one differs from it by design, and
    comparing them would report every item as updated on every scan while `ItemRepository.update`
    correctly declined to write either - a report that says a scan did work it did not do.
    """
    named_differently = names_are_the_scanners and (
        before.name != after.name or before.sort_name != after.sort_name
    )
    return (
        named_differently
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
    "TooManyRemovalsError",
    "scan",
]
