# SPDX-License-Identifier: GPL-3.0-or-later
"""What a library holds: one model, fourteen types, and the structure between them.

Everything in a library is one type - a film, a season, a track, an album, a library root
(docs/glossary.md). That is the reference's design and not a simplification of it: `/Items` returns
heterogeneous results because there is only ever one kind of thing in the list, distinguished by
`type`. Modelling each type as its own class would produce a hierarchy that every query then has to
flatten again.

**No I/O of any kind happens here** (architecture section 1). Nothing in this module opens a file,
reaches a database or knows that HTTP exists; it is the vocabulary the layers above share, and the
reason `library/` and `db/` can both speak about an episode without speaking to each other.

**An item's file lives in a `MediaSource`, not on the item**, and that is not a stylistic choice -
see `MediaSource` for why the alternative cannot express a two-part film.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ItemType(StrEnum):
    """The eight types feature 003 produces, the five feature 004 adds, and 009's one.

    The values are the reference's spellings because they are the vocabulary, not a serialisation:
    the glossary, the specifications and every client call an episode an `Episode`. `compat/` still
    owns how one reaches the wire - this module simply does not invent a second name for a thing
    that already has one.

    `UserView` and `Folder` are real types nothing here creates: a user view is 005 deriving one
    per user from a `CollectionFolder`, and nothing produces a bare folder.
    """

    MOVIE = "Movie"
    SERIES = "Series"
    SEASON = "Season"
    EPISODE = "Episode"
    MUSIC_ARTIST = "MusicArtist"
    MUSIC_ALBUM = "MusicAlbum"
    AUDIO = "Audio"
    COLLECTION_FOLDER = "CollectionFolder"

    # The five 004 adds. They are items because 005 serves them as items - one query machinery,
    # one envelope, `GET /Items/{id}` works on a genre - and they are **not** in the containment
    # tree below: see `BY_NAME`.
    GENRE = "Genre"
    MUSIC_GENRE = "MusicGenre"
    STUDIO = "Studio"
    PERSON = "Person"
    YEAR = "Year"

    # 009's one, and the only type no scan can ever produce: a user creates it, and nothing on
    # disk describes it. See `USER_CREATED` for what that costs the maps below.
    PLAYLIST = "Playlist"


class CollectionType(StrEnum):
    """What an operator declares a library root to be [spec section 3.1].

    Not a hint. It selects which resolution rules apply, and `PRODUCED_BY` below is the whole of
    what "a file under a `music` root is never resolved as a movie" means.
    """

    MOVIES = "movies"
    TVSHOWS = "tvshows"
    MUSIC = "music"


#: The types that exist because a *file* does, and therefore the only ones that carry sources.
#: Everything else is a container the scanner creates because its children need a parent, which is
#: also why the others' identities are derived from a name rather than a path
#: [spec section 3.6].
FILE_BACKED: frozenset[ItemType] = frozenset({ItemType.MOVIE, ItemType.EPISODE, ItemType.AUDIO})

#: The types that exist because a **name** does: a genre, a studio, a person, a year
#: [004 spec section 3.7]. They are items so that 005 can serve them through one query machinery,
#: and they are outside everything below on purpose.
#:
#: **Three properties at once, and each one is why the containment maps exempt them explicitly
#: rather than being loosened to accommodate them:**
#:
#: * **No parent, and no chain to a `CollectionFolder`.** A genre is not *in* a library; it is
#:   referenced by items that are. Giving it a parent would make it appear under one library's
#:   tree and belong to all of them.
#: * **No library.** `items.library_id` is null for exactly these five, which the schema states as
#:   a check constraint rather than a convention (004 plan section 4).
#: * **No collection type produces them.** They are created by a refresh, not by a resolver, so
#:   `PRODUCED_BY` does not mention them and the assertion that every type is produced by some
#:   collection type is scoped to the tree.
#:
#: `MusicArtist` is deliberately **not** here. It is a by-name item in the reference and a
#: per-library one in Atrium, which is a real difference recorded with its argument in
#: docs/compatibility/behaviours.md section 5.3 - 003 derived those identifiers before the
#: consequence had a surface to show on, and rewriting identity is the one operation this project
#: treats as radioactive.
BY_NAME: frozenset[ItemType] = frozenset(
    {ItemType.GENRE, ItemType.MUSIC_GENRE, ItemType.STUDIO, ItemType.PERSON, ItemType.YEAR}
)

#: The types a **user** creates, which no scan produces and no file describes. One so far.
#:
#: A third category rather than a member of either other one, because `Playlist` has each half of
#: what defines them and neither whole: like a by-name row it has no library, no parent and no
#: collection type, and unlike one it is not derived from a name an item mentions - it is minted
#: when somebody asks for it, and a rescan of every library cannot rebuild it (009 spec section 4).
#: Folding it into `BY_NAME` would have given `db/item_queries.py`'s by-name reference clause a
#: row to reason about that nothing references, and folding it into `IN_THE_TREE` would have
#: demanded a parent, a depth, a collection type and a metadata chain for a row that has none.
USER_CREATED: frozenset[ItemType] = frozenset({ItemType.PLAYLIST})

#: Everything the scanner arranges into a tree: every type that is neither a by-name row nor
#: user-created. The three containment maps below are total over *this* set, never over `ItemType`.
IN_THE_TREE: frozenset[ItemType] = frozenset(ItemType) - BY_NAME - USER_CREATED

#: The type of an item's parent, or None for the one type that has none.
#:
#: Every chain ends at a `CollectionFolder`, because the library itself is an item
#: [spec section 3.1] - so a film's parent is its library rather than nothing, and the leaves of
#: this map are exactly `FILE_BACKED`. A test asserts both, since the two drifting apart is how a
#: scanner ends up creating a container that owns a container.
#:
#: **Total over `IN_THE_TREE`, not over `ItemType`.** The five by-name types have no parent and no
#: chain; mapping them to `None` would make them look like second roots, and widening the chain
#: assertion to let them end anywhere would stop it guarding the tree it was written for.
PARENT_OF: Mapping[ItemType, ItemType | None] = {
    ItemType.COLLECTION_FOLDER: None,
    ItemType.MOVIE: ItemType.COLLECTION_FOLDER,
    ItemType.SERIES: ItemType.COLLECTION_FOLDER,
    ItemType.MUSIC_ARTIST: ItemType.COLLECTION_FOLDER,
    ItemType.SEASON: ItemType.SERIES,
    ItemType.EPISODE: ItemType.SEASON,
    ItemType.MUSIC_ALBUM: ItemType.MUSIC_ARTIST,
    ItemType.AUDIO: ItemType.MUSIC_ALBUM,
}

#: The reference's `MediaType` for each type: what *kind of thing* an item is to a player, as
#: opposed to what kind of row it is. Always present on every item (005 spec section 3.2), and a
#: filterable value in its own right - `mediaTypes=Unknown` is a real query the reference answers.
#:
#: Measured rather than derived from `FILE_BACKED`, and the two do not agree: an `Audio` file is
#: `Audio` and a `Movie` is `Video`, but every container is `Unknown` including `MusicAlbum`, which
#: a rule built on "does it hold audio" would have called `Audio`.
#: `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-28]`
#:
#: **The five by-name types are `Unknown` by default here and were not measured.** No probe asked
#: what `MediaType` a `Genre` carries; `Unknown` is what every other non-file type answers, and the
#: gap is named rather than hidden.
#:
#: **A `Playlist`'s value is the one entry here that is not a property of the type**, and the
#: comment this replaced had the mechanism wrong: it said the reference derives the value from the
#: item's contents, which would make a type-level map unable to hold it at all. Measured, the value
#: is decided **at creation** - `Audio` for one created empty, the media type of the first
#: resolvable id otherwise, and the body's own `MediaType` over both - and then it does not move:
#: a playlist created empty and filled with films still answers `Audio`, and one created from a
#: film still answers `Video` after a track is added
#: `[probe: tools/probe_playlist_media_type.py, Jellyfin 10.11.11, 2026-08-31]`.
#:
#: So the entry below is the **fallback**, exact for a playlist created empty and wrong for any
#: other: 009 stores the value per row and the serialiser prefers the stored one (009 plan
#: section 4.2). What still reads this entry as though it were type-level is
#: `db/item_queries.py`'s `mediaTypes` filter - see the caveat there.
MEDIA_TYPE_OF: Mapping[ItemType, str] = {
    ItemType.MOVIE: "Video",
    ItemType.EPISODE: "Video",
    ItemType.AUDIO: "Audio",
    ItemType.SERIES: "Unknown",
    ItemType.SEASON: "Unknown",
    ItemType.MUSIC_ARTIST: "Unknown",
    ItemType.MUSIC_ALBUM: "Unknown",
    ItemType.COLLECTION_FOLDER: "Unknown",
    ItemType.GENRE: "Unknown",
    ItemType.MUSIC_GENRE: "Unknown",
    ItemType.STUDIO: "Unknown",
    ItemType.PERSON: "Unknown",
    ItemType.YEAR: "Unknown",
    ItemType.PLAYLIST: "Audio",
}


#: Which types a collection type may produce. The rule of spec section 3.1, written down once:
#: a resolver that consults this cannot turn a file under a `music` root into a movie however it
#: is named, and a test can assert that without running a scan. Every library produces its own
#: `CollectionFolder`, so that appears in all three.
#:
#: Total over `IN_THE_TREE`. A by-name row is created by a refresh finding a genre on an item, not
#: by a resolver looking at a file, so no collection type produces one.
PRODUCED_BY: Mapping[CollectionType, frozenset[ItemType]] = {
    CollectionType.MOVIES: frozenset({ItemType.COLLECTION_FOLDER, ItemType.MOVIE}),
    CollectionType.TVSHOWS: frozenset(
        {ItemType.COLLECTION_FOLDER, ItemType.SERIES, ItemType.SEASON, ItemType.EPISODE}
    ),
    CollectionType.MUSIC: frozenset(
        {
            ItemType.COLLECTION_FOLDER,
            ItemType.MUSIC_ARTIST,
            ItemType.MUSIC_ALBUM,
            ItemType.AUDIO,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class MediaSource:
    """One file backing an item. An item may have several, and a two-part film does.

    **This is why the file's details are not fields on `Item`.** Spec section 3.3 and AC-4 require
    `The Film - part1.mkv` and `- part2.mkv` to resolve to **one** `Movie` with two sources rather
    than two movies, and an item carrying a single `relative_path` has nowhere to put the second
    part. Splitting them also removes a nullability that would otherwise be everywhere: a `Series`
    has no path at all, and under this shape it simply has no sources.

    `size` and `mtime_ns` are per source, not per item, because section 6.4's change detection has
    to notice a change to *either* part. An item whose second part was replaced and whose first was
    not has changed.
    """

    relative_path: str
    """Relative to its library root, always with forward slashes.

    Relative, because an operator who moves a library from one mount to another must not lose
    every identifier - specs/003-library-configuration-and-scanning/plan.md section 1. The absolute
    path is reconstructed from the root; it is never stored.
    """

    size: int | None = None
    mtime_ns: int | None = None
    """Together, the change-detection signal of plan section 6.4."""


@dataclass(frozen=True, slots=True)
class Item:
    """Anything a library holds. Frozen: a repository hands these out and nothing upstream owns one.

    Nearly every field is optional because nearly every field is meaningful for only some types.
    A `Series` has no source and no index number; an `Episode` has both; a `CollectionFolder` has
    neither and exists so that the library itself can be an item.
    """

    id: str
    """32 lowercase hex, derived from the item's stable identity and never allocated
    [spec section 3.6]. Stability is the whole requirement: clients key their caches, favourites
    and resume positions on this string.
    """

    type: ItemType
    name: str

    library_id: str | None
    """The library this item belongs to - **null for the five `BY_NAME` types, and for a
    playlist**.

    A genre is not in a library; it is referenced by items that are, and its identity is
    server-wide (004 spec section 3.7). A playlist is not in one either - it belongs to a user
    (009 spec section 3.7). The schema states the correspondence as a check constraint rather than
    trusting this docstring: `library_id IS NULL` if and only if the type is one of the five, and
    009's migration widens that constraint to *the five or a playlist* rather than giving a
    playlist a library it would then appear under.
    """

    parent_id: str | None = None

    sort_name: str = ""
    """What every list is ordered by [spec section 3.7]. Derived, and by two different rules -
    `domain.sorting` owns which, because `Audio`, `Episode` and `Season` do not use the one the
    others use.
    """

    sources: tuple[MediaSource, ...] = ()
    """Empty for a container type, one entry for an ordinary file, several for a multi-part film.
    Ordered: part one first, and the order is what a player joins them in.
    """

    index_number: int | None = None
    """Episode number, or track number."""

    parent_index_number: int | None = None
    """Season number, or disc number."""

    end_index_number: int | None = None
    """The last number a multi-episode file spans, for `S01E02-E03` [spec section 3.4, AC-5].

    None for the ordinary case. Present, this item *is* both episodes rather than standing for
    them - which is the distinction AC-5 exists to protect.
    """

    date_created: datetime | None = None
    date_modified: datetime | None = None

    removed_at: datetime | None = None
    """Set when the file is gone. Items are soft-deleted [plan section 6.6]: the row stays, the
    item stops appearing in queries, and the user's favourites and resume position - which are
    keyed by identity and not by row - are still there when the file comes back.
    """

    @property
    def is_removed(self) -> bool:
        return self.removed_at is not None

    @property
    def is_file_backed(self) -> bool:
        return self.type in FILE_BACKED

    @property
    def is_by_name(self) -> bool:
        """A genre, music genre, studio, person or year: no library, no parent, no file."""
        return self.type in BY_NAME

    @property
    def relative_path(self) -> str | None:
        """The path this item's identity is derived from: its first source's.

        A multi-part film is identified by its first part, so adding a part three years later does
        not change the identifier of a film somebody has already favourited.
        """
        return self.sources[0].relative_path if self.sources else None

    @property
    def size(self) -> int | None:
        """Every source together, which is what a two-part film's size means to anybody asking."""
        sizes = [source.size for source in self.sources if source.size is not None]
        return sum(sizes) if sizes else None

    @property
    def spans(self) -> tuple[int, ...]:
        """Every index number this item covers: one, or the whole `S01E02-E03` run."""
        if self.index_number is None:
            return ()
        if self.end_index_number is None:
            return (self.index_number,)
        return tuple(range(self.index_number, self.end_index_number + 1))


__all__ = [
    "BY_NAME",
    "FILE_BACKED",
    "IN_THE_TREE",
    "MEDIA_TYPE_OF",
    "PARENT_OF",
    "PRODUCED_BY",
    "USER_CREATED",
    "CollectionType",
    "Item",
    "ItemType",
    "MediaSource",
]
