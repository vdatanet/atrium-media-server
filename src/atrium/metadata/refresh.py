# SPDX-License-Identifier: GPL-3.0-or-later
"""Orchestration: read the local sources, merge, and write once per item.

The only caller of the write repository (plan section 5). Everything else in `metadata/` reads
something and returns values; this module is where those values become rows.

**The path-derived values are a source, and they come last.** That is the one structural decision
here and it was measured rather than argued. The reference builds a scratch result, merges each
local provider into it, then the remote ones, and only **then** folds in what the item already had
`[source: MediaBrowser.Providers/Manager/MetadataService.cs:809,849-861 @ v10.11.11]` - so the
name a scanner derived from a filename is the *last* fallback, not the first. Spec section 3.1's
table lists *Path-derived* twice, at positions 3 and 5, and this is the measurement that says
which one it meant: **position 5**.

It matters because AC-1 depends on it. A film with a full `.nfo` "resolves entirely from it", and
it cannot if the name 003 derived from the filename counts as a value a default refresh must not
overwrite. So `items.name`, `index_number` and `parent_index_number` are read **as the path
source** rather than as the subject's own values, and the subject is what a *previous refresh*
resolved. One consequence falls out for free: a later scan that re-derives a name from a changed
filename is corrected by the refresh that follows it, rather than quietly winning.

**Nothing here writes into a library root** (AC-15). This module opens files to read them, and the
only path it ever constructs for writing is inside the data directory - which no local source
needs at all, so in this slice there is no write path outside the database whatsoever.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.db.repositories import ItemRepository, MetadataRepository
from atrium.domain.items import FILE_BACKED, PARENT_OF, Item, ItemType
from atrium.domain.library import Library
from atrium.metadata.artwork import associate, find_artwork, with_embedded
from atrium.metadata.merge import CHAIN_OF, Current, MetadataChanges, Source, SourceKind, merge
from atrium.metadata.model import (
    Ambiguous,
    Field,
    MetadataField,
    NoMatch,
    RefreshMode,
    RemoteProvider,
    Subject,
    is_value,
)
from atrium.metadata.nfo import NfoResult, find_sidecar, read_nfo
from atrium.metadata.remote import ProviderUnavailableError
from atrium.metadata.tags import ReadsTags, TagResult, TagSource

logger = logging.getLogger(__name__)

#: The library's own item. **Not refreshed**: spec section 3.2's sidecar table and section 3.4's
#: artwork tables both describe *items in* a library, and a library has no directory of its own in
#: this model - it would borrow its first film's, which it did once, and the library ended up
#: wearing that film's poster.
_THE_LIBRARY = ItemType.COLLECTION_FOLDER


@dataclass(frozen=True, slots=True)
class RefreshReport:
    """What one refresh of one library did."""

    library_id: str
    considered: int = 0
    changed: int = 0
    warnings: tuple[str, ...] = ()
    collected: int = 0
    """By-name rows nothing referenced any more, deleted at the end of the transaction."""

    unidentified: tuple[str, ...] = field(default_factory=tuple)
    """Items a remote provider could not place - no match, or too many (AC-12).

    Counted apart from a failure because they are different problems with different fixes: an
    unidentified item needs a better name or a sidecar id, a failed one needs the provider to come
    back.
    """

    disabled: tuple[str, ...] = field(default_factory=tuple)
    """Why each provider sat out, **once per scan** rather than once per item (AC-9).

    An operator who has configured no key should be told that once, not four thousand times.
    """

    pending: tuple[str, ...] = field(default_factory=tuple)
    """Items a provider failure left wanting another go (AC-8). Retried by the next scan even
    though their files did not change."""

    def summary(self) -> str:
        disabled = f", {len(self.disabled)} provider(s) disabled" if self.disabled else ""
        return (
            f"library {self.library_id}: {self.changed} of {self.considered} items updated, "
            f"{len(self.warnings)} warnings, {self.collected} by-name rows collected"
            f"{disabled}"
        )


def refresh_items(
    library: Library,
    session: OrmSession,
    item_ids: Sequence[str],
    *,
    mode: RefreshMode = RefreshMode.DEFAULT,
    tags: ReadsTags | None = None,
    roots: Sequence[Path] | None = None,
    providers: Sequence[RemoteProvider] = (),
) -> RefreshReport:
    """Resolve metadata for `item_ids` and write it, one `apply` per item.

    `tags` is **the scan's own reader**, so the file a scan already opened is not opened again -
    that memo is the whole reason the seam and this module can both ask - and so that a caller who
    supplied a reader of their own gets it used for both halves of the scan. `None` builds a
    `TagSource` over the roots, which is what a refresh run on its own needs.

    Writes inside the caller's transaction and never commits, exactly like `library/scan.py`.
    """
    paths = [Path(one) for one in (roots if roots is not None else library.roots)]
    reader: ReadsTags = tags if tags is not None else TagSource(paths)
    items = ItemRepository(session).by_library(library.id)
    repository = MetadataRepository(session)

    directories = _directories(items, paths)
    warnings: list[str] = []
    unidentified: list[str] = []
    pending: list[str] = []
    changed = 0

    # **Once per scan, not once per item** (AC-9). Asked before the loop so a provider with no key
    # is named once in the report and then never consulted again - four thousand identical lines
    # is a report nobody reads.
    usable, disabled = _usable(providers, mode)

    for item_id in item_ids:
        item = items.get(item_id)
        if item is None or item.is_removed or item.type is _THE_LIBRARY:
            continue
        located = directories.get(item_id)
        if located is None:
            # A container whose children are all gone, or an item whose root is not mounted. Not
            # an error: the next scan will either find the files or remove the item.
            continue
        outcome = _apply_one(repository, item, located, reader, mode, usable, warnings)
        changed += int(outcome.changed)
        if outcome.unidentified:
            unidentified.append(item_id)
        if outcome.failed:
            pending.append(item_id)

    collected = repository.collect_by_name_garbage()
    return RefreshReport(
        library_id=library.id,
        considered=len(item_ids),
        changed=changed,
        warnings=tuple(warnings),
        collected=collected,
        unidentified=tuple(unidentified),
        disabled=tuple(disabled),
        pending=tuple(pending),
    )


def _usable(
    providers: Sequence[RemoteProvider], mode: RefreshMode
) -> tuple[list[RemoteProvider], list[str]]:
    """Which providers this refresh may consult, and the reasons the others may not."""
    if not mode.consults_remote_providers:
        return [], [f"{one.name}: local-only refresh" for one in providers]
    usable: list[RemoteProvider] = []
    disabled: list[str] = []
    for provider in providers:
        available = provider.enabled()
        if available is True:
            usable.append(provider)
        else:
            disabled.append(f"{provider.name}: {available}")
    return usable, disabled


def refresh_library(
    library: Library,
    session: OrmSession,
    *,
    mode: RefreshMode = RefreshMode.DEFAULT,
    tags: ReadsTags | None = None,
    roots: Sequence[Path] | None = None,
    providers: Sequence[RemoteProvider] = (),
) -> RefreshReport:
    """Every item in the library."""
    items = ItemRepository(session).by_library(library.id)
    return refresh_items(
        library, session, list(items), mode=mode, tags=tags, roots=roots, providers=providers
    )


# ----------------------------------------------------------------------------------------------
# One item
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Located:
    """Where on disk an item's metadata is looked for."""

    root: Path
    directory: Path
    stem: str | None
    relative_file: str | None


@dataclass(frozen=True, slots=True)
class _Outcome:
    changed: bool = False
    unidentified: bool = False
    failed: bool = False


def _apply_one(
    repository: MetadataRepository,
    item: Item,
    located: _Located,
    reader: ReadsTags,
    mode: RefreshMode,
    providers: Sequence[RemoteProvider],
    warnings: list[str],
) -> _Outcome:
    """**Local sources first, always** (plan section 6.8 step 1).

    They are cheap, offline, and they decide what is still missing - which is the condition step 2
    turns on and the whole of why AC-1 holds: a fully-sidecared film makes zero network requests
    because **nothing is missing**, not because a cache absorbed the fetch.
    """
    sidecar = _read_sidecar(item, located, warnings)
    tag_result = _read_tags(item, located, reader, warnings)
    art = _read_artwork(item, located, tag_result, warnings)

    local = _chain(item, sidecar, tag_result, art)
    subject = _subject(repository, item)

    remote, unidentified, failed = _remote(item, subject, local, providers, mode, warnings)

    # **Every local source, then remote, then the path.** Not "before the last entry": the film
    # chain lists `PATH` twice, so slicing off one leaves the other ahead of the provider - and a
    # sidecar carrying nothing but an id would keep its filename as a name while TMDB's title sat
    # unused behind it. The path is the last word (plan section 6.8), so it is what comes last.
    ahead = [one for one in local if one.kind is not SourceKind.PATH]
    behind = [one for one in local if one.kind is SourceKind.PATH]
    sources = ahead + remote + behind

    changes = merge(subject, sources, mode)

    locked_fields = sidecar.locked_fields
    is_locked = sidecar.is_locked
    if not changes and locked_fields is None and is_locked is None and not failed:
        # Nothing to say and nothing to lock. Writing the item's own values back would touch every
        # row on every rescan, which is what makes "a rescan of an unchanged library changes
        # nothing" a property rather than a hope.

        return _Outcome(unidentified=unidentified)

    repository.apply(
        item.id,
        changes,
        is_locked=is_locked,
        locked_fields=locked_fields,
        # **A failure marks the item and never blanks it** (AC-8). The next scan retries it even
        # though its files did not change, which is the one case the change-detection signal
        # cannot see.
        refresh_pending=failed,
        refreshed_at=utc_now(),
    )
    return _Outcome(changed=True, unidentified=unidentified, failed=failed)


#: What a remote provider is asked to supply. A field outside this set is never a reason to make a
#: request: `IMAGES` is asked for separately (a provider offers, the caller decides), and
#: `PROVIDER_IDS` arrives with whatever else is fetched.
WANTED_FROM_REMOTE: frozenset[Field] = frozenset(
    {
        Field.NAME,
        Field.ORIGINAL_TITLE,
        Field.OVERVIEW,
        Field.TAGLINE,
        Field.YEAR,
        Field.PREMIERE_DATE,
        Field.RUNTIME,
        Field.OFFICIAL_RATING,
        Field.COMMUNITY_RATING,
        Field.GENRES,
        Field.STUDIOS,
        Field.PEOPLE,
        Field.ALBUM_ARTISTS,
    }
)


def _remote(
    item: Item,
    subject: Current,
    local: Sequence[Source],
    providers: Sequence[RemoteProvider],
    mode: RefreshMode,
    warnings: list[str],
) -> tuple[list[Source], bool, bool]:
    """The remote step, behind **four** conditions (plan section 6.8 step 2).

    The mode allows it, the provider is enabled, **the local pass left fields wanting that a
    provider could supply**, and either an id is carried or there is a title worth searching for.

    The third clause is where AC-1 lives, and it was a remark in the plan until the tasks gate
    made it a condition: a fully-sidecared film makes zero network requests because nothing is
    missing, **not** because a cache absorbed the fetch. On a `Replace` refresh the clause is
    lifted - re-querying is what that mode is for.
    """
    if not providers:
        return [], False, False

    if mode is not RefreshMode.REPLACE and not _still_wanting(item, subject, local):
        return [], False, False

    sources: list[Source] = []
    unidentified = False
    failed = False

    for provider in providers:
        if not provider.handles(item.type):
            continue
        try:
            found = provider.identify(_subject_for(item, subject, local))
        except ProviderUnavailableError as exc:
            warnings.append(str(exc))
            failed = True
            continue

        if isinstance(found, Ambiguous):
            unidentified = True
            warnings.append(
                f"{provider.name}: {item.name!r} matched {len(found.candidates)} candidates; "
                f"left unidentified rather than guessing"
            )
            continue
        if isinstance(found, NoMatch):
            unidentified = True
            continue

        try:
            values = provider.fetch(found, item.type)
        except ProviderUnavailableError as exc:
            warnings.append(str(exc))
            failed = True
            continue
        if values:
            sources.append(Source(SourceKind.REMOTE, dict(values), provider.name))

    return sources, unidentified, failed


def _wanted_for(kind: ItemType) -> frozenset[Field]:
    """What a provider could usefully supply **for this type**.

    Not the whole set: a film can never have an album artist, and a *file-backed* item's runtime
    is discarded by the merge because it comes from probing the file. Counting either as "still
    missing" makes every film want something for ever - which is how the first version of this
    asked TMDB about a fully-sidecared film and broke AC-1 while looking correct.
    """
    wanted = WANTED_FROM_REMOTE
    if kind not in (ItemType.MUSIC_ALBUM, ItemType.MUSIC_ARTIST, ItemType.AUDIO):
        wanted -= {Field.ALBUM_ARTISTS}
    if kind in FILE_BACKED:
        wanted -= {Field.RUNTIME}
    return wanted


def _still_wanting(item: Item, subject: Current, local: Sequence[Source]) -> bool:
    """Whether anything a provider could supply is still missing after the local pass.

    "Missing" means neither the item already has it nor a local source just supplied it. A film
    whose sidecar named every field is not missing anything, so nothing is asked - which is AC-1,
    stated as a condition rather than hoped for.
    """
    supplied = {key for source in local for key, value in source.values.items() if is_value(value)}
    held = {key for key, value in subject.values.items() if is_value(value)}
    return bool(_wanted_for(item.type) - supplied - held)


def _subject_for(item: Item, subject: Current, local: Sequence[Source]) -> Subject:
    """What a provider is told: the best name and year the local pass produced, and every id.

    The ids are the point. An id from a sidecar or a tag short-circuits identification entirely
    (spec section 3.5 rule 1), and a subject built from the item alone would have thrown it away.
    """

    def first(key: Field) -> object | None:
        for source in local:
            value = source.values.get(key)
            if is_value(value):
                return value
        return subject.values.get(key)

    ids: dict[str, str] = {}
    for source in reversed(local):
        found = source.values.get(Field.PROVIDER_IDS)
        if isinstance(found, Mapping):
            ids.update({str(name): str(value) for name, value in found.items()})
    existing = subject.values.get(Field.PROVIDER_IDS)
    if isinstance(existing, Mapping):
        for name, value in existing.items():
            ids.setdefault(str(name), str(value))

    name = first(Field.NAME)
    year = first(Field.YEAR)
    artists = first(Field.ALBUM_ARTISTS)
    return Subject(
        kind=item.type,
        name=str(name) if name is not None else None,
        year=int(year) if isinstance(year, int) else None,
        provider_ids=ids,
        album_artist=str(artists[0]) if isinstance(artists, Sequence) and artists else None,
    )


def _chain(
    item: Item, sidecar: NfoResult, tag_result: TagResult, images: Sequence[object]
) -> list[Source]:
    """Spec section 3.1's order for this item's type, as sources.

    `CHAIN_OF` lists `PATH` twice for a film, because the spec's table does. A repeated source in
    a first-value-wins walk is a no-op, so this builds one entry per kind and the duplicate costs
    nothing - see `metadata/merge.py`.
    """
    by_kind: dict[SourceKind, Source] = {
        SourceKind.NFO: Source(SourceKind.NFO, dict(sidecar.values), "sidecar"),
        SourceKind.TAGS: Source(SourceKind.TAGS, dict(tag_result.values), "tags"),
        SourceKind.PATH: Source(SourceKind.PATH, _path_values(item), "path"),
    }
    ordered = [
        by_kind[kind]
        for kind in CHAIN_OF.get(item.type, (SourceKind.NFO, SourceKind.PATH))
        if kind in by_kind
    ]
    if images:
        # Artwork is not in the precedence chain at all: no other source supplies `IMAGES` in this
        # slice, and a remote provider's artwork is a separate association kind (section 6.5).
        ordered.insert(0, Source(SourceKind.NFO, {Field.IMAGES: list(images)}, "artwork"))
    return ordered


def _path_values(item: Item) -> dict[Field, object]:
    """What 003 derived from the file's name and place. **The last word, not the first.**

    Read off the item because that is where the scanner put it, and treated as a source rather
    than as the item's own value - which is the difference between AC-1 holding and a `.nfo` title
    never being able to replace a filename.
    """
    values: dict[Field, object] = {Field.NAME: item.name}
    if item.index_number is not None:
        values[Field.INDEX_NUMBER] = item.index_number
    if item.parent_index_number is not None:
        values[Field.PARENT_INDEX_NUMBER] = item.parent_index_number
    return values


def _subject(repository: MetadataRepository, item: Item) -> Current:
    """What a *previous refresh* resolved, and what may not be changed about it.

    `stored` carries the path-derived values as well, and only so that a value which is already
    what the row says is not written again. Keeping the two apart is what lets a sidecar's title
    replace a filename **and** a second refresh of the same file write nothing.
    """
    is_locked, locked_fields = repository.locks_of(item.id)
    resolved = repository.values_of(item.id)
    return Current(
        kind=item.type,
        values=resolved,
        stored={**resolved, **_path_values(item)},
        locked_fields=locked_fields,
        is_locked=is_locked,
    )


def _read_sidecar(item: Item, located: _Located, warnings: list[str]) -> NfoResult:
    path = find_sidecar(located.directory, item.type, located.stem)
    if path is None:
        return NfoResult()
    result = read_nfo(path, item.type)
    warnings.extend(str(one) for one in result.warnings)
    return result


def _read_tags(item: Item, located: _Located, reader: ReadsTags, warnings: list[str]) -> TagResult:
    """Only for audio, and through **the reader the scan used**, asked once.

    `MemoisedSource` makes any `MetadataSource` answer this: a `TagSource` gives the whole read,
    anything else gives what 003's seven keys can supply, and `PATH_ONLY` gives nothing - which is
    exactly what a path-only scan means.
    """
    if item.type is not ItemType.AUDIO or located.relative_file is None:
        return TagResult()
    result = reader.result_for(located.relative_file)
    if result.warning:
        warnings.append(result.warning)
    return result


def _read_artwork(
    item: Item, located: _Located, tag_result: TagResult, warnings: list[str]
) -> Sequence[object]:
    found = find_artwork(located.directory, item.type, located.stem)
    found = with_embedded(found, tag_result.art)
    warnings.extend(found.warnings)
    return associate(found.files, root=located.root)


# ----------------------------------------------------------------------------------------------
# Where an item's metadata lives
# ----------------------------------------------------------------------------------------------


def _directories(items: Mapping[str, Item], roots: Sequence[Path]) -> dict[str, _Located]:
    """The directory each item's metadata is looked for in.

    A file-backed item's is its file's own. **A container has no path of its own** - a `Series`
    has no file and a tag-derived `MusicAlbum` may not correspond to any directory at all - so it
    borrows its first descendant's, walked up by the difference in depth. That is a best guess
    rather than a fact, and it is the right one for the ordinary layout: `Artist/Album/01.flac`
    puts the album at `Artist/Album` and the artist at `Artist`.

    The library's own item is excluded, or it would borrow its first film's directory.
    """
    located: dict[str, _Located] = {}
    for item in items.values():
        if item.type in FILE_BACKED and item.relative_path:
            root = _root_of(item.relative_path, roots)
            if root is None:
                continue
            absolute = root / item.relative_path
            located[item.id] = _Located(
                root=root,
                directory=absolute.parent,
                stem=absolute.stem,
                relative_file=item.relative_path,
            )

    children: dict[str, list[str]] = {}
    for item in items.values():
        if item.parent_id is not None:
            children.setdefault(item.parent_id, []).append(item.id)

    for item in items.values():
        if item.id in located or item.type not in PARENT_OF or item.type is _THE_LIBRARY:
            continue
        descendant = _first_file_backed(item.id, items, children)
        if descendant is None or descendant.id not in located:
            continue
        steps = _depth(descendant.type) - _depth(item.type) - 1
        directory = located[descendant.id].directory
        for _ in range(max(steps, 0)):
            directory = directory.parent
        located[item.id] = _Located(
            root=located[descendant.id].root,
            directory=directory,
            stem=None,
            relative_file=None,
        )
    return located


def _first_file_backed(
    item_id: str, items: Mapping[str, Item], children: Mapping[str, list[str]]
) -> Item | None:
    """Depth-first, in **path** order, so the answer does not depend on row order or on the mount.

    It sorted by identifier until 2026-09-02, and identifier order is a hash of the **absolute**
    path (003 spec section 3.6), so which descendant a container borrowed a directory from moved
    with the mount point. That is not a tie between two equal answers, which this project already
    tolerates for a genre's spelling: the descendants of one container sit at different depths in
    the tree, the caller walks up a fixed number of levels from whichever it is given, and only
    some of them land on the container's own directory. Measured on the fixture library, a series
    whose second season has no season directory borrowed that episode's directory about one run in
    ten and then looked for its `tvshow.nfo` one level too high - so the same tree, mounted
    somewhere else, gave the series a different **name**
    `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`, where the reference
    reads the sidecar every time.

    Relative-path order is a property of the tree and of nothing else, and for the ordinary layout
    it picks the deepest-nested branch first, which is the one the caller's arithmetic is written
    for. It does not make the borrowing *correct* - a two-disc album still borrows a disc
    directory - and that is 004's to decide, not this ordering's.
    """
    backed: list[Item] = []
    seen: set[str] = set()
    pending = [item_id]
    while pending:
        for child_id in children.get(pending.pop(), ()):
            if child_id in seen:
                continue
            seen.add(child_id)
            child = items.get(child_id)
            if child is None:
                continue
            if child.type in FILE_BACKED and child.relative_path:
                backed.append(child)
            else:
                pending.append(child_id)
    if not backed:
        return None
    # Every descendant is gathered before one is chosen, so the answer does not depend on which
    # branch was walked first either - which the recursion it replaced did.
    return min(backed, key=lambda child: (child.relative_path, child.id))


def _depth(kind: ItemType) -> int:
    depth, current = 0, PARENT_OF.get(kind)
    while current is not None:
        depth, current = depth + 1, PARENT_OF.get(current)
    return depth


def _root_of(relative_path: str, roots: Sequence[Path]) -> Path | None:
    """Which configured root holds this file. The first that does, as `TagSource` decides it."""
    for root in roots:
        if (root / relative_path).exists():
            return root
    return roots[0] if roots else None


def pending_and_touched(session: OrmSession, library: Library, touched: Iterable[str]) -> list[str]:
    """The items a scan should hand to a refresh: what it touched, plus what is still pending.

    The second half is AC-8's channel: a provider failure marks an item `refresh_pending`, and the
    next scan retries it **even though its files did not change** - which is exactly the case the
    change-detection signal cannot see.
    """
    seen = list(dict.fromkeys(touched))
    known = set(seen)
    still_pending = MetadataRepository(session).pending(library.id)
    return seen + [one for one in still_pending if one not in known]


__all__ = [
    "MetadataChanges",
    "MetadataField",
    "RefreshReport",
    "pending_and_touched",
    "refresh_items",
    "refresh_library",
]
