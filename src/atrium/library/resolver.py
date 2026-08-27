# SPDX-License-Identifier: GPL-3.0-or-later
"""Candidates in, a hierarchy of items out.

This is where the pieces meet: the walk found the files, the naming modules read their paths, and
identity turned those into identifiers that survive a rescan. What is left is the **shape** — a
film hangs from its library, an episode from a season from a series, a track from an album from an
artist — and the containers in the middle exist because their children need a parent, not because a
file was found for them.

**The collection type decides everything, and it cannot be talked round.** A file under a `music`
root is never resolved as a movie no matter what it is called (003 spec section 3.1). That is not
left to the dispatch being written correctly: every item this module produces is checked against
`PRODUCED_BY` before it is returned, so a resolver that grew a wrong branch fails here rather than
in feature 005 three months later.

**Sort names are written through the dispatcher**, never by calling the base derivation. `Audio`,
`Episode` and `Season` replace it entirely, and using one sort-name function for everything is the
mistake [plan section 9](../../../specs/003-library-configuration-and-scanning/plan.md) rates most
likely and most expensive: it reorders every album in the library.

**Pure.** Nothing here opens a file or touches a database, and it invents no timestamps - a
resolver that stamped `date_created` would give a different answer on every scan, which is exactly
what spec section 3.8 forbids.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from atrium.domain.items import (
    PRODUCED_BY,
    CollectionType,
    Item,
    ItemType,
    MediaSource,
)
from atrium.domain.library import Library
from atrium.domain.sorting import sort_name
from atrium.library import identity
from atrium.library.naming import (
    PATH_ONLY,
    MetadataSource,
    group,
    parse_audio,
    parse_episode,
    parse_movie,
)
from atrium.library.walker import Candidate

#: What a season with no number of its own is called. Season zero is `Specials` everywhere.
SPECIALS_NAME = "Specials"


@dataclass(frozen=True, slots=True)
class Resolution:
    """Every item a set of candidates resolves to, containers included."""

    items: tuple[Item, ...] = ()

    def of_type(self, item_type: ItemType) -> tuple[Item, ...]:
        return tuple(item for item in self.items if item.type is item_type)

    def by_id(self, item_id: str) -> Item | None:
        return next((item for item in self.items if item.id == item_id), None)


def resolve(
    library: Library,
    candidates: Iterable[Candidate],
    source: MetadataSource = PATH_ONLY,
) -> Resolution:
    """The items `candidates` describe, under `library`.

    The library's own `CollectionFolder` is always the first item, even for an empty library: it is
    what a user sees before anything has been scanned, and a library that vanished from a client
    because its last file was deleted would be a worse answer than an empty one.
    """
    collection_folder = _collection_folder(library)
    items: list[Item] = [collection_folder]

    ordered = sorted(candidates, key=lambda candidate: candidate.relative_path)
    if library.collection_type is CollectionType.MOVIES:
        items += _movies(library, collection_folder, ordered)
    elif library.collection_type is CollectionType.TVSHOWS:
        items += _series(library, collection_folder, ordered)
    else:
        items += _music(library, collection_folder, ordered, source)

    _refuse_foreign_types(library, items)
    return Resolution(items=tuple(sorted(items, key=lambda item: (item.type.value, item.id))))


# ----------------------------------------------------------------------------------------------
# Movies
# ----------------------------------------------------------------------------------------------


def _movies(library: Library, parent: Item, candidates: list[Candidate]) -> list[Item]:
    by_path = {candidate.relative_path: candidate for candidate in candidates}
    films = group([parse_movie(candidate.relative_path) for candidate in candidates])

    return [
        _finished(
            Item(
                id=identity.for_file(
                    ItemType.MOVIE,
                    library.id,
                    film.parts[0],
                    case_sensitive=library.case_sensitive_identity,
                ),
                type=ItemType.MOVIE,
                name=film.name,
                library_id=library.id,
                parent_id=parent.id,
                sources=tuple(_source(by_path[path]) for path in film.parts),
            )
        )
        for film in films
    ]


# ----------------------------------------------------------------------------------------------
# Series, seasons and episodes
# ----------------------------------------------------------------------------------------------


def _series(library: Library, parent: Item, candidates: list[Candidate]) -> list[Item]:
    items: dict[str, Item] = {}
    episodes: list[Item] = []

    for candidate in candidates:
        parsed = parse_episode(candidate.relative_path)
        series_name = parsed.series or parsed.name or candidate.relative_path
        series = _by_name(library, parent, ItemType.SERIES, series_name, items)

        season_number = parsed.season
        season_id = identity.for_season(series.id, season_number)
        if season_id not in items:
            items[season_id] = _finished(
                Item(
                    id=season_id,
                    type=ItemType.SEASON,
                    name=_season_name(season_number),
                    library_id=library.id,
                    parent_id=series.id,
                    # A Season's own number is `index_number`, which is what section 3.7.2's
                    # override reads. It is not `parent_index_number`, and the two are easy to
                    # swap because every other type uses the other one.
                    index_number=season_number,
                )
            )

        episodes.append(
            _finished(
                Item(
                    id=identity.for_file(
                        ItemType.EPISODE,
                        library.id,
                        candidate.relative_path,
                        case_sensitive=library.case_sensitive_identity,
                    ),
                    type=ItemType.EPISODE,
                    name=parsed.name or _fallback_name(candidate.relative_path),
                    library_id=library.id,
                    parent_id=season_id,
                    sources=(_source(candidate),),
                    index_number=parsed.episode,
                    parent_index_number=season_number,
                    end_index_number=parsed.end_episode,
                )
            )
        )

    return [*items.values(), *episodes]


def _season_name(number: int | None) -> str:
    if number == 0:
        return SPECIALS_NAME
    return f"Season {number}" if number is not None else "Season"


# ----------------------------------------------------------------------------------------------
# Music
# ----------------------------------------------------------------------------------------------


def _music(
    library: Library, parent: Item, candidates: list[Candidate], source: MetadataSource
) -> list[Item]:
    items: dict[str, Item] = {}
    tracks: list[Item] = []

    for candidate in candidates:
        parsed = parse_audio(candidate.relative_path, source)

        holder = parent
        if parsed.artist:
            holder = _by_name(library, parent, ItemType.MUSIC_ARTIST, parsed.artist, items)
        if parsed.album:
            # An album hangs from its **album artist**, which is what makes a compilation one
            # album rather than one per track (spec section 3.5, AC-9).
            holder = _by_name(library, holder, ItemType.MUSIC_ALBUM, parsed.album, items)

        tracks.append(
            _finished(
                Item(
                    id=identity.for_file(
                        ItemType.AUDIO,
                        library.id,
                        candidate.relative_path,
                        case_sensitive=library.case_sensitive_identity,
                    ),
                    type=ItemType.AUDIO,
                    name=parsed.title or _fallback_name(candidate.relative_path),
                    library_id=library.id,
                    parent_id=holder.id,
                    sources=(_source(candidate),),
                    index_number=parsed.track,
                    parent_index_number=parsed.disc,
                )
            )
        )

    return [*items.values(), *tracks]


# ----------------------------------------------------------------------------------------------
# Shared
# ----------------------------------------------------------------------------------------------


def _collection_folder(library: Library) -> Item:
    return _finished(
        Item(
            id=identity.for_library(library.id),
            type=ItemType.COLLECTION_FOLDER,
            name=library.name,
            library_id=library.id,
        )
    )


def _by_name(
    library: Library, parent: Item, item_type: ItemType, name: str, into: dict[str, Item]
) -> Item:
    """A container, created once per identity however many children ask for it."""
    item_id = identity.for_name(
        item_type, library.id, name, case_sensitive=library.case_sensitive_identity
    )
    if item_id not in into:
        into[item_id] = _finished(
            Item(
                id=item_id,
                type=item_type,
                name=name,
                library_id=library.id,
                parent_id=parent.id,
            )
        )
    return into[item_id]


def _finished(item: Item) -> Item:
    """Every item leaves through here, so every item's sort name comes from the dispatcher.

    One place rather than eleven. `Audio`, `Episode` and `Season` replace the base derivation
    entirely, and a branch that built an item and forgot to sort it would put that item first in
    every list a client draws - silently, and only for that type.
    """
    return replace(item, sort_name=sort_name(item))


def _source(candidate: Candidate) -> MediaSource:
    return MediaSource(
        relative_path=candidate.relative_path, size=candidate.size, mtime_ns=candidate.mtime_ns
    )


def _fallback_name(relative_path: str) -> str:
    """What an item is called when its own name said nothing. Never empty: an item with no name
    is one a user cannot find, and the path is the last thing that is always there.
    """
    return relative_path.rsplit("/", 1)[-1].rsplit(".", 1)[0] or relative_path


def _refuse_foreign_types(library: Library, items: list[Item]) -> None:
    """Spec section 3.1, enforced rather than trusted to the dispatch above being right."""
    allowed = PRODUCED_BY[library.collection_type]
    wrong = {item.type for item in items} - allowed
    if wrong:
        raise ValueError(
            f"a {library.collection_type.value} library resolved "
            f"{sorted(one.value for one in wrong)}, which it cannot produce. A file under a "
            f"{library.collection_type.value} root is never resolved as anything else, whatever "
            f"it is called (spec section 3.1)."
        )


__all__ = ["SPECIALS_NAME", "Resolution", "resolve"]
