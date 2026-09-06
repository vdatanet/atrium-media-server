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

from dataclasses import replace
from pathlib import PurePath

from atrium.db.repositories import LibraryRepository
from atrium.domain.items import CollectionType
from atrium.domain.library import Library
from atrium.library.identity import for_library, for_library_configuration


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
    collection_type: CollectionType | str,
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
    """
    kind = CollectionType(collection_type)
    cleaned = tuple(normalise_root(root) for root in roots)
    library = Library(
        id=for_library_configuration(kind, name, cleaned, case_sensitive=case_sensitive_identity),
        name=name.strip(),
        collection_type=kind,
        roots=cleaned,
        case_sensitive_identity=case_sensitive_identity,
    )
    _require_roots(library.roots)
    already = repository.by_id(library.id)
    if already is not None:
        raise LibraryAlreadyDeclaredError(
            f"this declaration is library {already.id} - {already.name!r} of type "
            f"{already.collection_type.value} over {list(already.roots)}. Since the identifier is "
            f"derived from the declaration, creating it again would be a second copy of one "
            f"library: every file under it found twice, under two identifiers. Edit that library "
            f"with `update`, or declare this one with a different name or different roots."
        )
    stored = repository.add(library)
    return replace(stored, item_id=for_library(stored.id))


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
            f"{existing.collection_type.value}. It selects which resolution rules apply, so "
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
    if not roots:
        raise ValueError("a library needs at least one root; one with none can never hold anything")
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


__all__ = [
    "FrozenAtCreationError",
    "LibraryAlreadyDeclaredError",
    "create",
    "normalise_root",
    "update",
]
