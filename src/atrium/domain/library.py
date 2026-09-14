# SPDX-License-Identifier: GPL-3.0-or-later
"""What an operator configured: a name, some roots, and what to make of what is in them.

Separate from `domain/items.py` because it is a different kind of thing. An item is discovered; a
library is *declared*. Nothing here is derived from a filesystem - it is the input that decides how
the filesystem gets read.

**Two of these fields cannot be changed after creation**, and both for the same reason: every
identifier under a library is derived from the library's own id and from how its paths are
normalised (003 spec section 3.6), so changing either one rewrites all of them and discards every
client's favourites and resume positions for everything in that library. `library/config.py`
refuses the edits rather than accepting them with a warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atrium.domain.items import CollectionType


@dataclass(frozen=True, slots=True)
class Library:
    """One configured library. Frozen, like everything a repository hands out."""

    id: str
    """**Derived once from the declaration, then stored** - by
    `library.identity.for_library_configuration`.

    This said *"allocated, not derived"* until 2026-09-14, which stopped being true on 2026-09-06
    (003 spec section 3.6, AC-17): a library recreated from the same declaration is the same
    library. What survived is that the derivation happens once, so editing a name or moving a root
    afterwards changes no identifier.
    """

    name: str
    collection_type: CollectionType | None
    """Any of the eight declared types, or `None` for a library created with none - which is also
    what an undeclared type such as `photos` is stored as (014 spec section 3.6.1). Only
    `SCANNED_TYPES` are scanned; every library is a view whatever this holds."""

    roots: tuple[str, ...] = ()
    """Absolute paths. A library may have several - the reference had one with two in the OQ-1
    measurement - and everything an item stores is relative to one of them. **Or none**, since 014:
    a library added with no path is a library with no roots, listed and empty (014 spec section
    3.6).
    """

    case_sensitive_identity: bool = False
    """**Frozen at creation.** Whether two paths differing only in case are two items.

    Unset by default, which matches the reference. This resolves 003 OQ-2: the question was never
    what the reference does - it exposes a setting and defaults it off - but whether Atrium should
    make it a decision or a per-library fact. It is a per-library fact, because it cannot be
    changed afterwards: flipping it rewrites every identifier in the library.
    """

    item_id: str = field(default="", repr=False)
    """The `CollectionFolder` item this library becomes, when one has been derived.

    Empty until the library is written: it comes from `library.identity.for_library`, and a domain
    module derives nothing. Carried here so that a caller holding a library does not have to reach
    for the identity module to find the item that represents it.
    """
