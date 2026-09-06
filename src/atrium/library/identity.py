# SPDX-License-Identifier: GPL-3.0-or-later
"""Where an item's identifier comes from.

Stability is the whole requirement (spec 003 section 3.6). Clients key their caches, favourites and
resume positions on these strings, so an identifier that changes when a library is rescanned
silently discards a user's state - and nothing reports it, because from the client's side the old
item simply stopped existing and a new one appeared.

**The hashing is not here.** `atrium.compat.guids.derive` does the NUL-joined SHA-256 truncated to
sixteen bytes, and has since 001. What this module owns is the part 003 adds: *which* stable facts
go into the key for each type, and how a path is normalised before it becomes one of them.

**Relative to the root, never absolute.** The reference derives from the absolute path, so moving a
library from `/mnt/a` to `/mnt/b` - or running the same library from a container with a different
mount point - changes every identifier there. Atrium derives from the path relative to its library
root, so that move costs nothing. The identifiers differ from the reference's either way
(docs/compatibility/behaviours.md section 1.4), so being better here has no compatibility cost.

There are **six** identity rules, not one, and `RULE_OF` says which type uses which. Four came
from 003; the fifth is 004's by-name rule, and it is the only one with no library in the key. The
sixth is 009's, and it is the only one that derives nothing at all: a playlist's identifier is
minted when the user creates it, so every function here refuses to be asked for one.

**And one identifier here belongs to no item.** `for_library_configuration` is a *library's* own,
and it moved here on 2026-09-06 from being minted in `library/config.py` - because every
file-backed key hashes it, so a minted one made two installs of one declaration hold different
items. It has no row in `RULE_OF`, which is a map over `ItemType` and stays total over exactly
that.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping
from enum import StrEnum

from atrium.compat.guids import derive
from atrium.domain.items import CollectionType, ItemType


class IdentityRule(StrEnum):
    """The five shapes of spec 003 section 3.6's table, plus 004's and 009's. One per type.

    Five of the six name the stable facts that go into a hash. `MINTED` names the absence of any:
    it is a rule in this map so that the map stays **total** over `ItemType` - a type with no row
    would fail as a `KeyError` mid-scan - and so that `_require` refuses every derivation of a
    playlist by construction rather than by anybody remembering to check.
    """

    FROM_PATH = "the file's path, relative to its library root"
    FROM_NAME = "the library plus the normalised name"
    FROM_PARENT_AND_NUMBER = "the parent's identity plus a number"
    FROM_LIBRARY = "the library's configured identity"
    FROM_FOLDED_NAME = "the folded name alone, server-wide"
    MINTED = "nothing: it is allocated at creation"
    """009's. A playlist is the one item a rescan cannot rebuild (009 spec section 4): it has no
    path, no library and no scan, so there is no stable fact to hash and nothing to reproduce.
    `compat/guids.new_id()` allocates it, the way it already allocates the server, library, user
    and session identifiers - and Principle VII's forbidden list is about identifiers a scan
    re-derives, which this is not.
    """


#: Which rule each type uses. A test asserts this covers every `ItemType`, because a type with no
#: rule is a type the scanner cannot give an identifier to, and the failure would arrive as a
#: `KeyError` in the middle of a scan rather than as a missing row here.
RULE_OF: Mapping[ItemType, IdentityRule] = {
    ItemType.MOVIE: IdentityRule.FROM_PATH,
    ItemType.EPISODE: IdentityRule.FROM_PATH,
    ItemType.AUDIO: IdentityRule.FROM_PATH,
    ItemType.SERIES: IdentityRule.FROM_NAME,
    ItemType.MUSIC_ALBUM: IdentityRule.FROM_NAME,
    ItemType.MUSIC_ARTIST: IdentityRule.FROM_NAME,
    ItemType.SEASON: IdentityRule.FROM_PARENT_AND_NUMBER,
    ItemType.COLLECTION_FOLDER: IdentityRule.FROM_LIBRARY,
    # 004's five. Server-wide: no library in the key, which is the whole difference from
    # `FROM_NAME` and the reason `MusicArtist` above is a documented gap rather than a bug
    # (docs/compatibility/behaviours.md section 5.3).
    ItemType.GENRE: IdentityRule.FROM_FOLDED_NAME,
    ItemType.MUSIC_GENRE: IdentityRule.FROM_FOLDED_NAME,
    ItemType.STUDIO: IdentityRule.FROM_FOLDED_NAME,
    ItemType.PERSON: IdentityRule.FROM_FOLDED_NAME,
    ItemType.YEAR: IdentityRule.FROM_FOLDED_NAME,
    # 009's one. A row rather than an exemption, so the map stays total and every `for_*` function
    # below refuses a playlist through `_require` without a line of its own.
    ItemType.PLAYLIST: IdentityRule.MINTED,
}

#: What a filename cannot carry, and what the reference therefore replaces with a space before a
#: name becomes a by-name key
#: `[source: Emby.Server.Implementations/IO/ManagedFileSystem.cs:21-27 @ v10.11.11]`.
#:
#: This set is not "punctuation" or "anything awkward" - it is exactly Windows' invalid path
#: characters, because the reference's by-name identity is derived from a **path** it would have
#: to be able to create. Atrium creates no such path and derives nothing from one; it reproduces
#: the set because the *observable* consequence is which two spellings become one item, and
#: guessing at a wider or narrower set changes that.
_PATH_INVALID = frozenset('"<>|:*?\\/') | {chr(code) for code in range(0x00, 0x20)}


class IdentityCollisionError(RuntimeError):
    """Two different files derived the same identifier.

    Plan section 7: this aborts rather than merging, and it names both paths. A collision is a bug
    in the derivation, not user error - merging the two items would silently hide it, and the
    symptom a user would eventually report is a film that plays the wrong file.
    """


def normalise_path(relative_path: str, *, case_sensitive: bool = False) -> str:
    """A path reduced to the form the derivation hashes.

    Separators, then Unicode, then case. Each step exists because the *same file* would otherwise
    produce two identifiers:

    * **Separators.** A walker on one platform yields `a/b`, on another `a\\b`.
    * **NFC.** macOS filesystems hand back decomposed forms, so `Amélie` arrives as `e` plus a
      combining acute where Linux gives the precomposed character. Different bytes, same name, and
      without this, different identifiers for the same film on two machines.
    * **Case**, unless the library was created case-sensitive - see `case_sensitive` below.

    Absolute paths and `..` segments are refused rather than normalised away. Either one means the
    caller has a path that is not relative to the root it thinks it is, and an identifier derived
    from it would be quietly wrong rather than loudly absent.
    """
    if relative_path.startswith(("/", "\\")):
        raise ValueError(
            f"{relative_path!r} is absolute. Identity is derived from the path relative to its "
            f"library root, so that moving the root changes nothing (spec section 3.6)."
        )

    segments = [segment for segment in relative_path.replace("\\", "/").split("/") if segment]
    if any(segment == ".." for segment in segments):
        raise ValueError(
            f"{relative_path!r} climbs above its library root. A path reaching outside the root "
            f"it is relative to is a walker bug, not a name to be normalised."
        )

    joined = unicodedata.normalize("NFC", "/".join(s for s in segments if s != "."))
    return joined if case_sensitive else joined.lower()


def normalise_name(name: str, *, case_sensitive: bool = False) -> str:
    """The name form the by-name rule hashes: trimmed, NFC, and cased like a path.

    Section 3.6 says "the normalised name" without saying what normalised means; this is the
    definition, and it is deliberately the same one paths get. A series whose directory is renamed
    from `the series` to `The Series` is the same series, for exactly the reason a file whose path
    changed case is the same file.
    """
    normalised = unicodedata.normalize("NFC", name.strip())
    return normalised if case_sensitive else normalised.lower()


def fold_by_name(name: str) -> str:
    """The form a genre, studio, person or year name is reduced to before it becomes an identity.

    **One definition, used twice.** The identifier hashes this, and 004's by-name repository keys
    its rows on it, so the row a spelling merges into and the identifier that spelling produces
    cannot disagree. A second fold written next to the repository is how they would.

    The steps, in the reference's order
    `[source: MediaBrowser.Controller/Entities/Genre.cs:84-92 @ v10.11.11]`
    `[source: Emby.Server.Implementations/Library/LibraryManager.cs:636-658 @ v10.11.11]`:

    1. every character a filename cannot carry becomes a **space**, one for one;
    2. trim;
    3. remove trailing dots - the reference's comment says Windows dislikes them;
    4. lowercase.

    The order matters for names nobody sensible writes and somebody eventually does: the reference
    does not trim again after removing the dots, so `Drama. . .` folds with a trailing space and
    `Drama. .` does not fold to the same thing. Reproduced rather than tidied, because tidying it
    would merge two rows the reference keeps apart.

    **Case folds, diacritics do not** - the whole envelope of
    docs/compatibility/behaviours.md section 2.18. `Sci-Fi` and `sci-fi` are one genre; `Elektro`
    and `Elektró` are two.

    NFC is Atrium's own addition and observable nowhere: it unifies two byte encodings of the
    *same* character - macOS hands back decomposed forms where Linux gives precomposed - and
    leaves every genuinely different character alone. The reference has no equivalent because it
    derives from a path produced on one machine.
    """
    replaced = "".join(" " if character in _PATH_INVALID else character for character in name)
    return unicodedata.normalize("NFC", replaced.strip().rstrip(".")).lower()


def for_by_name(item_type: ItemType, name: str) -> str:
    """A `Genre`, `MusicGenre`, `Studio`, `Person` or `Year`: its folded name, and nothing else.

    **Server-wide on purpose.** No library takes part in the key, so the same genre on films in
    two libraries is one row with one identifier - which is what makes `/Genres` a list of genres
    rather than a list of genres per library.

    The type *is* in the key, so a `Genre` and a `MusicGenre` spelled the same are two items. That
    is what keeps `/Genres` and `/MusicGenres` disjoint without either endpoint filtering by
    guesswork (004 plan section 4).
    """
    _require(item_type, IdentityRule.FROM_FOLDED_NAME)
    return derive(item_type.value, fold_by_name(name))


def for_file(
    item_type: ItemType,
    library_id: str,
    relative_path: str,
    *,
    case_sensitive: bool = False,
) -> str:
    """A `Movie`, `Episode` or `Audio`: its path, relative to its library root.

    `case_sensitive` is the library's `case_sensitive_identity` flag, **frozen at creation**
    (plan section 6.3) because flipping it rewrites every identifier in that library. `library/
    config.py` is what refuses the edit; this function simply obeys whichever value it was given.
    """
    _require(item_type, IdentityRule.FROM_PATH)
    return derive(
        item_type.value, library_id, normalise_path(relative_path, case_sensitive=case_sensitive)
    )


def for_name(
    item_type: ItemType, library_id: str, name: str, *, case_sensitive: bool = False
) -> str:
    """A `Series`, `MusicAlbum` or `MusicArtist`: its library plus its normalised name.

    Not its path, deliberately. An album is one album whether its tracks sit in one directory or
    several, and a series survives its directory being renamed - which is the same reason
    section 3.5 lets a tag outrank a directory.
    """
    _require(item_type, IdentityRule.FROM_NAME)
    return derive(item_type.value, library_id, normalise_name(name, case_sensitive=case_sensitive))


def for_season(series_id: str, season_number: int | None) -> str:
    """A `Season`: its series' identity plus its number.

    Not a path, because a season very often has no directory of its own (section 3.4) - and when it
    does, that directory may be called `Season 01`, `Season 1` or `Specials`. The number is the
    stable fact; `None` is itself a stable fact and gets its own identity rather than an error,
    because a season whose number could not be read still has to be *something*.
    """
    return derive(
        ItemType.SEASON.value, series_id, "" if season_number is None else str(season_number)
    )


def for_library_configuration(
    collection_type: str,
    name: str,
    roots: Iterable[str],
    *,
    case_sensitive: bool = False,
) -> str:
    """A **library's own** identifier, from the configuration an operator declared it with.

    The one identifier here that is not an item's, and the last one in this project to stop being
    minted. It was `new_id()` until 2026-09-06, and the reason it changed is that every
    file-backed identifier hangs off it: `for_file` hashes `(type, library_id, relative_path)`, so
    a minted library identifier makes **every item in it different on a rebuilt install** even
    when the tree, the configuration and this software are identical. The ordering tail in
    `db/item_queries` is that identifier, so two builds of one library also order their ties
    differently - which is invisible to a client and fatal to a differential run comparing two
    servers by position (010's list).

    **What is in the key is the configuration `config.create` was given**, and nothing else: the
    collection type, the name, the roots as a set, and the case-sensitivity flag that is an input
    to every identifier under it. Roots are sorted, so declaring the same two directories in the
    other order is the same library rather than a second one.

    **It is derived once and then stored**, which is what keeps the promise the old comment made
    about renaming: `config.update` writes a new name or new roots and never recomputes this, so
    an edit still costs nothing and no identifier moves. What it gives up is the other half of
    that comment - deleting a library and creating it again from the same declaration now **is**
    the same library, and its items keep the identifiers a client cached. That is a reversal of a
    decision taken when OQ-2 closed, taken deliberately on 2026-09-06 and argued in
    [003 §3.6](../../../specs/003-library-configuration-and-scanning/spec.md), AC-17.
    """
    return derive(
        "Library",
        CollectionType(collection_type).value,
        name.strip(),
        "1" if case_sensitive else "0",
        *sorted(roots),
    )


def for_library(library_id: str) -> str:
    """The `CollectionFolder` that is the library itself."""
    return derive(ItemType.COLLECTION_FOLDER.value, library_id)


def ensure_unique(assignments: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Map identifier to path, refusing two paths that derived the same one.

    Plan section 7's abort, as a pure function so that the scan does not have to invent it and a
    test does not have to find a real SHA-256 collision to exercise it.

    Both paths are named, because the useful question when this fires is what the two inputs had
    in common - and the answer is never visible from the identifier.
    """
    seen: dict[str, str] = {}
    for item_id, path in assignments:
        if item_id in seen and seen[item_id] != path:
            raise IdentityCollisionError(
                f"{seen[item_id]!r} and {path!r} both derive {item_id}. Two files cannot be one "
                f"item: this is a bug in the derivation (plan section 6.3), not user error, and "
                f"merging them would hide it until somebody reported a film playing the wrong file."
            )
        seen[item_id] = path
    return seen


def _require(item_type: ItemType, rule: IdentityRule) -> None:
    actual = RULE_OF.get(item_type)
    if actual is not rule:
        raise ValueError(
            f"{item_type.value} takes its identity from {actual}, not from {rule}. Deriving it "
            f"the wrong way produces a perfectly valid identifier for the wrong thing, which is "
            f"why this refuses instead of obliging."
        )


__all__ = [
    "RULE_OF",
    "IdentityCollisionError",
    "IdentityRule",
    "ensure_unique",
    "fold_by_name",
    "for_by_name",
    "for_file",
    "for_library",
    "for_library_configuration",
    "for_name",
    "for_season",
    "normalise_name",
    "normalise_path",
]
