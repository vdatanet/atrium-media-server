# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuring a library, and the two things about one that can never change.

An operator declares a name, one or more root directories, and a collection type. Everything else
in feature 003 follows from those three: the collection type selects which resolution rules apply
(003 spec section 3.1), and the roots decide what gets read at all.

**Two fields are frozen at creation, and this module refuses to change them rather than accepting
the change and warning.** A warning is the wrong shape for this: the operator would see a line in a
log after the damage, and the damage is that every identifier under the library has been rewritten
and every client's favourites and resume positions for everything in it are gone. There is no
undo - the old identifiers are not stored anywhere, because they were derived.

* **`case_sensitive_identity`** decides whether two paths differing only in case are one item or
  two, and it is an input to every identifier in the library (003 plan section 6.3).
* **`id`** is the other input. It is **derived from the declaration this module was given** - the
  collection type, the name, the roots and that flag - and then stored, never recomputed.

Changing either means creating a new library and rescanning, which is a decision an operator makes
with their eyes open rather than a side effect of an edit that looked cosmetic.

**The identifier was allocated rather than derived until 2026-09-06, and the sentence that used to
stand here said why: so that renaming a library or moving its roots costs nothing, and so that
deleting a library and creating another with the same name is not the same library.** The first
half still holds and is why the derivation happens once: `update` writes a new name or new roots
and does not touch the identifier, so an edit still moves nothing. The second half is what was
given up, deliberately, and it is the whole point of the change - **a library recreated from one
declaration is one library**, and its items keep the identifiers a client cached. What forced it is
that every file-backed identifier hangs off this one, so a minted value made a rebuilt install a
different library holding different items with a different ordering, for no reason a client or an
operator could see. Two servers cannot be compared through that, and 010's differential is what
found it. 003 section 3.6 and AC-17 carry the argument.

**The cost is that one declaration is now one library, and a second attempt at it is refused**
rather than quietly making a duplicate that would find every file twice.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Collection
from dataclasses import replace
from pathlib import PurePath
from typing import Final

from sqlalchemy.orm import Session as OrmSession

from atrium.compat.dates import utc_now
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import CollectionType
from atrium.domain.library import Library
from atrium.library.identity import for_library, for_library_configuration
from atrium.library.resolver import resolve


class LibraryAlreadyDeclaredError(ValueError):
    """The declaration names a library that already exists, and would be a second copy of it.

    Possible only since the identifier became a derivation of the declaration (2026-09-06): with a
    minted one this was two libraries that happened to look alike, and every file under them was
    found twice, under two identifiers, in two libraries a client would show side by side. A
    distinct type rather than the database's integrity error, because the useful thing to say is
    which library it already is.
    """


class FrozenAtCreationError(ValueError):
    """An attempt to change something that decides every identifier in a library.

    A distinct type rather than a bare `ValueError`, because the caller that has to handle this is
    an operator-facing one and the right response is not "retry" but "make a new library".
    """


def create(
    repository: LibraryRepository,
    name: str,
    collection_type: CollectionType | str | None,
    roots: tuple[str, ...] | list[str],
    *,
    case_sensitive_identity: bool = False,
) -> Library:
    """Declare a library. The only place `case_sensitive_identity` is ever accepted.

    `case_sensitive_identity` defaults to unset, which is what the reference does, and it is the
    answer to 003 OQ-2: the question was never what the reference does - it has the setting and
    defaults it off - but whether Atrium should treat it as a global decision or a per-library
    fact. Per-library, recorded with the library, and frozen. A server whose operator flipped a
    global switch would rewrite every identifier in every library at once.

    **Any of the eight declared types, or `None`**, and **no roots at all** - both since 014 (spec
    section 3.6.1 and 3.6). A string that names no member is still refused here: mapping an
    undeclared type such as `photos` to `None` is the route's decision, taken before the domain sees
    it (014 plan section 4). Two roots one inside the other are still refused.

    **The name is stored and hashed exactly as given**, and `settle_name` is where a name is
    cleaned. This stripped it until 2026-09-14, and a strip here undoes the one step of 014's order
    a client can see: `Movies?` settles to `Movies ` - trimmed first, replaced second - and a strip
    afterwards would store `Movies` and derive the identifier `Movies` over the same roots already
    has, refusing as a second copy a library the reference adds (014 spec section 3.6.2).
    """
    kind = None if collection_type is None else CollectionType(collection_type)
    cleaned = tuple(normalise_root(root) for root in roots)
    library = Library(
        id=for_library_configuration(kind, name, cleaned, case_sensitive=case_sensitive_identity),
        name=name,
        collection_type=kind,
        roots=cleaned,
        case_sensitive_identity=case_sensitive_identity,
    )
    _require_roots(library.roots)
    already = repository.by_id(library.id)
    if already is not None:
        raise LibraryAlreadyDeclaredError(
            f"this declaration is library {already.id} - {already.name!r} of type "
            f"{_type_of(already)} over {list(already.roots)}. Since the identifier is "
            f"derived from the declaration, creating it again would be a second copy of one "
            f"library: every file under it found twice, under two identifiers. Edit that library "
            f"with `update`, or declare this one with a different name or different roots."
        )
    stored = repository.add(library)
    return replace(stored, item_id=for_library(stored.id))


def create_with_view(
    session: OrmSession,
    name: str,
    collection_type: CollectionType | str | None,
    roots: tuple[str, ...] | list[str],
    *,
    case_sensitive_identity: bool = False,
) -> Library:
    """Declare a library **and write its `CollectionFolder`**, inside the caller's transaction.

    The folder is what makes a library a view, and until 014 T6 only a scan wrote it - so a library
    with no roots, which a scan refuses, was in no `/UserViews`, and every other library was absent
    from them until its first scan had finished. **Decided by the operator on 2026-09-14: a
    library's folder is created when the library is**, so every library is a view the moment it
    exists, as on the reference (014 spec section 3.6.1, plan section 6.5).

    The folder is the resolver's own - `resolve` over no candidates, which answers the library's
    folder and nothing else - so the identifier, the name and the sort name are the ones a scan
    derives, and the scan that follows finds the row already there and **unchanged**: it neither
    writes a second folder nor re-identifies this one. Its creation date is the moment it was
    written, which is what a scan stamps on a container it creates.

    Never commits, like `scan`: the library and its folder are one unit of work because the caller
    opened one, and a refusal from either rolls back both.
    """
    library = create(
        LibraryRepository(session),
        name,
        collection_type,
        roots,
        case_sensitive_identity=case_sensitive_identity,
    )
    (folder,) = resolve(library, ()).items
    now = utc_now()
    ItemRepository(session).add(replace(folder, date_created=now, date_modified=now))
    return library


def update(
    repository: LibraryRepository,
    library_id: str,
    *,
    name: str | None = None,
    roots: tuple[str, ...] | list[str] | None = None,
    collection_type: CollectionType | str | None = None,
    case_sensitive_identity: bool | None = None,
) -> Library:
    """Edit the parts of a library that can be edited, and refuse the parts that cannot.

    `collection_type` and `case_sensitive_identity` are accepted as arguments **so that they can be
    refused with an explanation**. Leaving them out of the signature would produce
    `TypeError: unexpected keyword argument`, which tells an operator that they typed something
    wrong rather than that they asked for something destructive - and a caller passing the value
    the library already has is not asking for anything at all, so that case is allowed through.
    """
    existing = repository.by_id(library_id)
    if existing is None:
        raise LookupError(f"no library {library_id}")

    if case_sensitive_identity is not None and case_sensitive_identity != (
        existing.case_sensitive_identity
    ):
        raise FrozenAtCreationError(
            f"case_sensitive_identity is frozen at creation and library {library_id} was created "
            f"with it {'set' if existing.case_sensitive_identity else 'unset'}. Changing it "
            f"rewrites every identifier in this library, which discards every client's favourites "
            f"and resume positions for everything in it, and nothing stores the old identifiers to "
            f"undo it. Create a new library with the setting you want and scan it."
        )

    if collection_type is not None and CollectionType(collection_type) != existing.collection_type:
        raise FrozenAtCreationError(
            f"collection_type is frozen at creation and library {library_id} is "
            f"{_type_of(existing)}. It selects which resolution rules apply, so "
            f"changing it re-resolves every file under a different set of rules and gives every "
            f"item a new type and a new identifier. Create a new library and scan it."
        )

    if name is not None:
        repository.rename(library_id, name.strip())
    if roots is not None:
        cleaned = tuple(normalise_root(root) for root in roots)
        _require_roots(cleaned)
        repository.set_roots(library_id, cleaned)

    updated = repository.by_id(library_id)
    assert updated is not None  # noqa: S101 - it existed three lines ago, in this transaction
    return replace(updated, item_id=for_library(updated.id))


def normalise_root(root: str) -> str:
    """One spelling per directory, so that two roots are two directories.

    A trailing separator, a doubled one, or a `.` segment are the same directory written three
    ways; left alone, an operator could configure the same tree twice and every file under it
    would be found twice. Symbolic links are **not** resolved: an operator who mounted a share at a
    stable path and expects that path to be the root is right, and resolving would put the target
    in the configuration where a remount would change it.
    """
    text = str(root).strip()
    if not text:
        raise ValueError("a library root cannot be empty")
    path = PurePath(text)
    if not path.is_absolute():
        raise ValueError(
            f"{root!r} is not an absolute path. A library root is the one absolute path in the "
            f"configuration; everything an item stores is relative to it (003 spec section 3.6)."
        )
    return str(path)


def _require_roots(roots: tuple[str, ...]) -> None:
    """Refuse two roots one inside the other. **No roots at all is not refused**, since 014.

    Until 2026-09-14 this refused an empty tuple too, on the grounds that a library with no root
    can never hold anything. That is still true and it is no longer a reason: the reference adds a
    library with no path, and 014 decided to do the same, as an empty library - which is what a
    library of a type this server does not scan already is (014 spec section 3.6, behaviours
    section 3.31). The nesting refusal is the half that protects identity, and it stays.
    """
    for one in roots:
        for other in roots:
            if one is not other and _contains(other, one):
                raise ValueError(
                    f"{one!r} is inside {other!r}. Two roots where one contains the other means "
                    f"every file under the inner one is found twice, under two relative paths and "
                    f"therefore under two identifiers."
                )


def _contains(outer: str, inner: str) -> bool:
    return PurePath(inner) != PurePath(outer) and PurePath(outer) in PurePath(inner).parents


def _type_of(library: Library) -> str:
    return library.collection_type.value if library.collection_type is not None else "none"


# ------------------------------------------------------------------------------------------------
# The name a library ends up with (014 spec section 3.6.2, behaviours section 3.30)
# ------------------------------------------------------------------------------------------------

#: Step 3's set: every character replaced by a space. The reference's own fixed list - the five
#: printable characters, the null character and the control characters 1 to 31, and the four path
#: characters - which does not depend on the host
#: `[source: Emby.Server.Implementations/IO/ManagedFileSystem.cs:21-28, 305-334 @ v10.11.11]`.
#:
#: The same set `library/identity.py` folds a by-name key with, written out again rather than
#: imported: that one is an identity rule and this one is a naming rule, and a change to either must
#: not move the other in silence.
REPLACED_IN_NAMES: Final[frozenset[str]] = frozenset('"<>|:*?\\/') | {
    chr(code) for code in range(0x00, 0x20)
}

#: The first number a name that collides is given. The count starts at one and is incremented
#: before it is used `[source: Emby.Server.Implementations/Library/LibraryManager.cs:3036-3044 @
#: v10.11.11]`, so `Movies` becomes `Movies2`.
FIRST_NUMBER: Final = 2

#: The whitespace outside the separator categories that steps 1 and 2 treat as whitespace. The
#: reference trims and checks emptiness by the platform's whitespace rule, which is the three
#: separator categories plus these six. Python's own `str.strip` also takes U+001C to U+001F,
#: which that rule does not, so the rule is written out rather than borrowed: `\x1fMovies` is
#: trimmed to itself there, and step 3 then makes it ` Movies` - read from the rule and not
#: measured, as 014 T4 read the username rule.
_OTHER_WHITESPACE: Final = frozenset("\t\n\v\f\r\x85")


def _is_whitespace(character: str) -> bool:
    return character in _OTHER_WHITESPACE or unicodedata.category(character) in {"Zs", "Zl", "Zp"}


def _trimmed(text: str) -> str:
    start, end = 0, len(text)
    while start < end and _is_whitespace(text[start]):
        start += 1
    while end > start and _is_whitespace(text[end - 1]):
        end -= 1
    return text[start:end]


def settle_name(requested: str, taken: Collection[str]) -> str:
    """The name a library asked for as `requested` is added under, beside libraries named `taken`.

    Spec section 3.6.2's four steps, each on the result of the one before:

    1. **refused** if empty or whitespace, on the name as sent - `ValueError`. The route answers
       this before it gets here, with the validation `400`; the step is kept so that this function
       is the order whole, and a caller that forgot the validation meets a refusal rather than a
       library called nothing;
    2. **trimmed**;
    3. every character of `REPLACED_IN_NAMES` **replaced by a space**;
    4. **compared exactly** - case, and every code point, included - against `taken`, and numbered
       from `FIRST_NUMBER` with nothing between the name and the number while it collides.

    Two consequences of the order are observable: `Movies?` is `Movies ` and does not collide with
    `Movies`, because the trim came first; and a name made only of replaced characters passes step
    1 and becomes spaces.
    """
    if not requested or all(_is_whitespace(character) for character in requested):
        raise ValueError("a library name cannot be empty or whitespace (014 spec section 3.6.2)")
    cleaned = "".join(
        " " if character in REPLACED_IN_NAMES else character for character in _trimmed(requested)
    )
    names = frozenset(taken)
    settled, number = cleaned, FIRST_NUMBER - 1
    while settled in names:
        number += 1
        settled = f"{cleaned}{number}"
    return settled


__all__ = [
    "FIRST_NUMBER",
    "REPLACED_IN_NAMES",
    "FrozenAtCreationError",
    "LibraryAlreadyDeclaredError",
    "create",
    "create_with_view",
    "normalise_root",
    "settle_name",
    "update",
]
