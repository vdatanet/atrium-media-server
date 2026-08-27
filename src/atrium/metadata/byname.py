# SPDX-License-Identifier: GPL-3.0-or-later
"""Genres, studios, people and years as items in their own right.

Spec section 3.7: these become items so that `/Genres`, `/MusicGenres`, `/Artists` and person
queries in 005 have something to return - one query machinery, one envelope, and `GET /Items/{id}`
works on a genre.

**Two rules, and both are the reference's rather than improvements on it:**

* **Names are folded for identity and preserved for display.** `Sci-Fi` and `sci-fi` are one
  genre, and the display name is the first spelling seen. 97 of 97 live genre ids reproduce from
  the case-folded name `[probe: tools/probe_by_name_normalisation.py, Jellyfin 10.11.11,
  2026-08-27]`. The fold is case only, plus the characters a filename cannot carry - spellings
  differing in diacritics stay separate items
  (docs/compatibility/behaviours.md section 2.18).
* **A genre on a film and a genre on a track are different items.** The type is part of the key,
  which is the whole of what keeps `/Genres` and `/MusicGenres` disjoint without either endpoint
  guessing from context.

**The fold itself is `library/identity.fold_by_name`**, not a second copy here. The identifier
hashes exactly what a row is keyed on, so a spelling cannot merge into one row and derive
another's id - which is what two definitions of one fold eventually produce (004 T4).

`name_folded` on the item table is a **different** fold and lives here too: it exists only for
005's `searchTerm`, `nameStartsWith` and `/Search/Hints`, so it folds diacritics as well - a user
typing `amelie` should find `Amélie`, while `Elektro` and `Elektró` must remain two genres.
Conflating the two would either break search or merge rows the reference keeps apart.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping

from atrium.domain.items import BY_NAME, ItemType
from atrium.library.identity import fold_by_name, for_by_name
from atrium.metadata.model import Field, PersonKind

#: Which by-name type a genre on an item of a given type becomes.
#:
#: Audio, albums and artists produce `MusicGenre`; everything else produces `Genre`. That single
#: distinction is what 005's two endpoints are, and it is decided **here**, at write time, rather
#: than by a query guessing from whatever referred to the name.
GENRE_TYPE_OF: Mapping[ItemType, ItemType] = {
    ItemType.AUDIO: ItemType.MUSIC_GENRE,
    ItemType.MUSIC_ALBUM: ItemType.MUSIC_GENRE,
    ItemType.MUSIC_ARTIST: ItemType.MUSIC_GENRE,
}

#: Which by-name type each list-valued field produces. `ARTISTS` and `ALBUM_ARTISTS` are absent on
#: purpose: an artist is a `MusicArtist`, which is **per-library** in Atrium rather than by-name -
#: the gap recorded in docs/compatibility/behaviours.md section 5.3.
BY_NAME_FIELD: Mapping[Field, ItemType] = {
    Field.GENRES: ItemType.GENRE,
    Field.STUDIOS: ItemType.STUDIO,
    Field.PEOPLE: ItemType.PERSON,
}


def genre_type(item_kind: ItemType) -> ItemType:
    """`Genre` or `MusicGenre`, decided by what the item is."""
    return GENRE_TYPE_OF.get(item_kind, ItemType.GENRE)


def identity_of(kind: ItemType, spelling: str) -> str:
    """The identifier a by-name row of this type and spelling has, derived and never allocated.

    A thin pass-through, and it is here so that nothing in `metadata/` reaches for the fold and
    the derivation separately and gets one of the two subtly wrong.
    """
    return for_by_name(kind, spelling)


def key_of(kind: ItemType, spelling: str) -> tuple[ItemType, str]:
    """What two spellings must share to be one row: the type, and the folded name."""
    return kind, fold_by_name(spelling)


def is_by_name(kind: ItemType) -> bool:
    return kind in BY_NAME


def fold_for_search(name: str) -> str:
    """`items.name_folded`: what 005 matches `searchTerm` and `nameStartsWith` against.

    **Case and diacritics both**, which is the difference from `fold_by_name`. A user typing
    `amelie` expects to find `Amélie`; two genres spelled `Elektro` and `Elektró` are still two
    genres. Different questions, different folds, and a row that misses this one is invisible to
    search rather than broken - which is why the column is not nullable and why every write path
    sets it.

    Written by 004, read by nobody until 005.
    """
    decomposed = unicodedata.normalize("NFD", name.strip())
    without_marks = "".join(one for one in decomposed if not unicodedata.combining(one))
    return unicodedata.normalize("NFC", without_marks).casefold()


def person_type_of(kind: PersonKind) -> str:
    """The string stored in `item_people.person_type` - the reference's own spelling."""
    return kind.value


__all__ = [
    "BY_NAME_FIELD",
    "GENRE_TYPE_OF",
    "fold_by_name",
    "fold_for_search",
    "genre_type",
    "identity_of",
    "is_by_name",
    "key_of",
    "person_type_of",
]
