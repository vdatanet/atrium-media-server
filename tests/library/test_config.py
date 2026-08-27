# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuring a library, and refusing the two edits that would rewrite every identifier in it.

The test that matters is `test_changing_the_case_flag_is_refused`. Everything else here fails
visibly - a bad root, a missing library, a name that did not save. That one fails **silently and
irreversibly**: the operator sees a success, and every client's favourites and resume positions for
that library are gone, with nothing storing the old identifiers to undo it.

So it is asserted three ways: the service refuses, the repository has nowhere to put the value, and
the identifiers really do all change when the flag differs.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import LibraryRepository
from atrium.domain.items import CollectionType, ItemType
from atrium.library import config
from atrium.library.identity import for_file, for_library
from tests.conftest import data_dir


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def repositories(engine: Engine) -> Iterator[LibraryRepository]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        yield LibraryRepository(db)


# ------------------------------------------------------------------------------------------
# The refusal
# ------------------------------------------------------------------------------------------


def test_changing_the_case_flag_is_refused(repositories: LibraryRepository) -> None:
    """Refused, not accepted with a warning. A warning arrives after the damage and there is no
    undo: the old identifiers were derived, so nothing stored them.
    """
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    assert library.case_sensitive_identity is False

    with pytest.raises(config.FrozenAtCreationError, match="frozen at creation"):
        config.update(repositories, library.id, case_sensitive_identity=True)

    assert repositories.by_id(library.id).case_sensitive_identity is False  # type: ignore[union-attr]


def test_the_refusal_says_what_to_do_instead(repositories: LibraryRepository) -> None:
    """An error an operator cannot act on is an error that gets worked around."""
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    with pytest.raises(config.FrozenAtCreationError) as raised:
        config.update(repositories, library.id, case_sensitive_identity=True)
    message = str(raised.value)
    assert "Create a new library" in message
    assert "favourites" in message


def test_passing_the_value_it_already_has_is_not_a_change(repositories: LibraryRepository) -> None:
    """A caller round-tripping a library it just read is not asking for anything."""
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    config.update(repositories, library.id, case_sensitive_identity=False, name="Films")
    assert repositories.by_id(library.id).name == "Films"  # type: ignore[union-attr]


def test_the_repository_has_no_way_to_change_the_flag() -> None:
    """The other half of the enforcement: nowhere to put the value, not a rule to remember.

    A guard in the service is a guard one new caller can go around. This asserts the shape rather
    than the discipline.
    """
    editable = {name for name in vars(LibraryRepository) if not name.startswith("_")}
    assert editable == {"by_id", "all", "add", "rename", "set_roots", "remove"}
    for method in ("rename", "set_roots"):
        annotations = getattr(LibraryRepository, method).__annotations__
        assert "case_sensitive_identity" not in annotations


def test_changing_the_collection_type_is_refused(repositories: LibraryRepository) -> None:
    """The same class of damage: it re-resolves every file under different rules."""
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    with pytest.raises(config.FrozenAtCreationError, match="collection_type"):
        config.update(repositories, library.id, collection_type="music")


def test_the_flag_really_does_change_every_identifier(repositories: LibraryRepository) -> None:
    """Why the refusal exists, asserted rather than asserted-about.

    Same library id, same paths, one flag apart - and not one identifier survives.
    """
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    paths = ["The Film (1999).mkv", "Amelie (2001).mkv", "Sub/Dir/Another (2005).mkv"]

    insensitive = [for_file(ItemType.MOVIE, library.id, path) for path in paths]
    sensitive = [for_file(ItemType.MOVIE, library.id, path, case_sensitive=True) for path in paths]
    assert not set(insensitive) & set(sensitive)


# ------------------------------------------------------------------------------------------
# What a library is
# ------------------------------------------------------------------------------------------


def test_a_library_round_trips(repositories: LibraryRepository) -> None:
    library = config.create(repositories, "  Movies  ", "movies", ("/mnt/a", "/mnt/b"))
    read_back = repositories.by_id(library.id)
    assert read_back is not None
    assert read_back.name == "Movies"
    assert read_back.collection_type is CollectionType.MOVIES
    assert read_back.roots == ("/mnt/a", "/mnt/b")


def test_a_library_becomes_a_collection_folder_item(repositories: LibraryRepository) -> None:
    """Spec section 3.1: each library becomes a `CollectionFolder`."""
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    assert library.item_id == for_library(library.id)


def test_two_libraries_with_the_same_name_are_two_libraries(
    repositories: LibraryRepository,
) -> None:
    """The id is allocated, not derived, so a name is a label rather than an identity."""
    one = config.create(repositories, "Movies", "movies", ("/mnt/a",))
    other = config.create(repositories, "Movies", "movies", ("/mnt/b",))
    assert one.id != other.id


def test_renaming_a_library_keeps_every_identifier(repositories: LibraryRepository) -> None:
    """Which is the whole reason the id is allocated rather than derived from the name."""
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    before = for_file(ItemType.MOVIE, library.id, "The Film (1999).mkv")
    config.update(repositories, library.id, name="Films")
    after = for_file(ItemType.MOVIE, library.id, "The Film (1999).mkv")
    assert before == after


def test_moving_a_root_keeps_every_identifier(repositories: LibraryRepository) -> None:
    """AC-10 at the configuration level: the root is not part of any key."""
    library = config.create(repositories, "Movies", "movies", ("/mnt/a",))
    before = for_file(ItemType.MOVIE, library.id, "The Film (1999).mkv")
    config.update(repositories, library.id, roots=("/mnt/b",))
    assert repositories.by_id(library.id).roots == ("/mnt/b",)  # type: ignore[union-attr]
    assert for_file(ItemType.MOVIE, library.id, "The Film (1999).mkv") == before


# ------------------------------------------------------------------------------------------
# Roots
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("/mnt/films/", "/mnt/films"),
        ("/mnt//films", "/mnt/films"),
        ("/mnt/./films", "/mnt/films"),
        ("  /mnt/films  ", "/mnt/films"),
    ],
)
def test_one_directory_has_one_spelling(written: str, expected: str) -> None:
    """Three spellings of one directory would let an operator configure the same tree twice."""
    assert config.normalise_root(written) == expected


def test_a_relative_root_is_refused() -> None:
    with pytest.raises(ValueError, match="absolute"):
        config.normalise_root("films")


def test_an_empty_root_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        config.normalise_root("   ")


def test_a_library_with_no_roots_is_refused(repositories: LibraryRepository) -> None:
    with pytest.raises(ValueError, match="at least one root"):
        config.create(repositories, "Movies", "movies", ())


def test_a_root_inside_another_root_is_refused(repositories: LibraryRepository) -> None:
    """Every file under the inner one would be found twice, under two identifiers."""
    with pytest.raises(ValueError, match="is inside"):
        config.create(repositories, "Movies", "movies", ("/mnt/films", "/mnt/films/2024"))


def test_the_same_root_twice_is_one_root(repositories: LibraryRepository) -> None:
    library = config.create(repositories, "Movies", "movies", ("/mnt/films", "/mnt/films/"))
    assert repositories.by_id(library.id).roots == ("/mnt/films",)  # type: ignore[union-attr]


def test_a_collection_type_the_resolver_cannot_scan_is_refused(
    repositories: LibraryRepository,
) -> None:
    with pytest.raises(ValueError):
        config.create(repositories, "Books", "books", ("/mnt/books",))


def test_updating_a_library_that_does_not_exist_says_so(repositories: LibraryRepository) -> None:
    with pytest.raises(LookupError, match="no library"):
        config.update(repositories, "0" * 32, name="Anything")


def test_removing_a_library_removes_it(repositories: LibraryRepository) -> None:
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    repositories.remove(library.id)
    assert repositories.by_id(library.id) is None
    assert repositories.all() == []
