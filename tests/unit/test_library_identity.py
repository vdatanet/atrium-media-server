# SPDX-License-Identifier: GPL-3.0-or-later
"""A library's own identifier, before and after 014 let a library have no type.

**The table below was computed on 2026-09-14 from `main` before 014 T5 changed a line**, and is
committed as literals. That is the point of it: a test that asked `for_library_configuration` for
the expected value would assert that the function agrees with itself, which it always does. Every
item identifier in a library hashes this one (003 plan section 6.3), so a derivation that moved
for a declaration that already existed would rebuild every install of it as different items -
favourites, resume positions and a differential run's ordering all gone, with nothing raised.

What 014 changed in the derivation is two things, and neither may reach a row of this table: a
declaration may carry **no type**, which hashes a part no typed declaration has, and the name is
hashed **as given** rather than stripped - which moves nothing for a name nobody padded, and no
fixture declaration pads one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import LibraryRepository
from atrium.domain.items import CollectionType
from atrium.library import config
from atrium.library.identity import for_library_configuration
from tests.conftest import data_dir
from tests.fixtures.reference_tree import libraries

#: Where the single-use reference instance mounts the fixture tree, and so the roots its libraries
#: are declared over. Atrium's own runs declare them under a temporary directory, which is why the
#: table fixes one root rather than reading wherever a run happened to build the tree.
MOUNT = "/fixture"

#: `(type, name, roots, case-sensitive) -> identifier`, as `main` derived them before 014 T5.
KNOWN: dict[tuple[str, str, tuple[str, ...], bool], str] = {
    # The fixture tree's libraries (tests/fixtures/reference_tree.py), every one of them.
    ("movies", "Movies", ("/fixture/Movies",), False): "844e40ecd6cdb451fb3e433d0d11b080",
    ("tvshows", "Shows", ("/fixture/Shows",), False): "c91a3bfc1583984bf5abb2c819b15ad0",
    ("music", "Music", ("/fixture/Music",), False): "641d6f97de582deb064292cc0de65534",
    ("movies", "Films", ("/fixture/Decodable/Movies",), False): "64167752a885644560c83c9e2259f228",
    ("music", "Tunes", ("/fixture/Decodable/Music",), False): "db534c79aa1371cc43c242a5137a189d",
    ("movies", "Empty", ("/fixture/Empty",), False): "6b740a4663f211b012c6167f8afbdcc2",
    # The query world's four, declared over its fixed roots (tests/fixtures/query.py).
    ("movies", "Films", ("/libraries/films",), False): "fe7c116f08ea07f5e7b8db0ae603d69d",
    ("tvshows", "Shows", ("/libraries/shows",), False): "5404ecab804aa11a3af63ef122beec12",
    ("music", "Music", ("/libraries/music",), False): "07805f9d2910ce22b2a7b5719c4b4547",
    ("music", "More Music", ("/libraries/more-music",), False): "a527131e6cfdbb061c385e8a15f342f5",
    # The two inputs besides a type and a name: the case flag, and roots as a set.
    ("movies", "Movies", ("/mnt/films",), True): "36da67d5047ea0b505036b0f44bc9fad",
    ("movies", "Movies", ("/mnt/a", "/mnt/b"), False): "005fee783f97b7e1a77e3791c78b6c4a",
    ("tvshows", "TV Shows", ("/mnt/b", "/mnt/a"), False): "2a2c86bd9fd07fa91b62e8170f8deb5e",
}


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


def test_the_table_covers_every_library_the_fixture_tree_declares() -> None:
    """A library added to the fixture tree later is a row this table has to gain, not a library it
    silently does not cover."""
    declared = {
        (one.collection_type, one.name, (f"{MOUNT}/{one.subpath}",), False) for one in libraries()
    }
    assert declared <= set(KNOWN)


@pytest.mark.parametrize(("declaration", "expected"), list(KNOWN.items()))
def test_every_known_declaration_keeps_its_identifier(
    declaration: tuple[str, str, tuple[str, ...], bool], expected: str
) -> None:
    kind, name, roots, case_sensitive = declaration
    assert for_library_configuration(kind, name, roots, case_sensitive=case_sensitive) == expected


@pytest.mark.parametrize(("declaration", "expected"), list(KNOWN.items()))
def test_every_known_declaration_is_stored_under_its_identifier(
    engine: Engine, declaration: tuple[str, str, tuple[str, ...], bool], expected: str
) -> None:
    """Through `config.create`, which is where a derivation reaches a row - so a change to what
    `create` hands the derivation (the roots' spelling, the name) is caught as well as a change to
    the derivation itself."""
    kind, name, roots, case_sensitive = declaration
    with session_scope(session_factory(engine)) as db:
        library = config.create(
            LibraryRepository(db), name, kind, roots, case_sensitive_identity=case_sensitive
        )
    assert library.id == expected


@pytest.mark.parametrize(("declaration", "expected"), list(KNOWN.items()))
def test_the_same_declaration_with_no_type_is_another_library(
    declaration: tuple[str, str, tuple[str, ...], bool], expected: str
) -> None:
    """The untyped declaration derives an identifier none of the typed ones has - of this row, or
    of any other type over the same name and roots."""
    _, name, roots, case_sensitive = declaration
    untyped = for_library_configuration(None, name, roots, case_sensitive=case_sensitive)
    typed = {
        for_library_configuration(kind, name, roots, case_sensitive=case_sensitive)
        for kind in CollectionType
    }
    assert untyped != expected
    assert untyped not in typed
    assert untyped not in KNOWN.values()


def test_a_declaration_with_no_type_hashes_an_empty_part_where_the_type_goes() -> None:
    """Derived, not minted, and derived the way the docstring says - asserted against a hash taken
    here with `hashlib` rather than through `compat.guids.derive`, so the shape of the key is what
    is under test: `Library`, an empty type, the name, the flag, the roots, NUL-joined."""
    one = for_library_configuration(None, "Shelf", ("/mnt/shelf",))
    key = b"\0".join((b"Library", b"", b"Shelf", b"0", b"/mnt/shelf"))
    assert one == hashlib.sha256(key).digest()[:16].hex() == "7178ca1473b47581f945164ca17b596d"


def test_a_padded_name_is_a_different_declaration() -> None:
    """`Movies?` settles to `Movies ` (014 spec section 3.6.2), a library of its own beside
    `Movies` over the same roots - which a stripped key refused as a second copy."""
    plain = for_library_configuration("movies", "Movies", ("/fixture/Movies",))
    assert plain == KNOWN[("movies", "Movies", ("/fixture/Movies",), False)]
    assert for_library_configuration("movies", "Movies ", ("/fixture/Movies",)) != plain
