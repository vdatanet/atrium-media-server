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
from atrium.db.repositories import ItemRepository, LibraryRepository
from atrium.domain.items import CollectionType, ItemType
from atrium.library import config
from atrium.library.identity import for_file, for_library
from atrium.library.scan import scan
from tests.conftest import data_dir, not_media
from tests.fixtures.library import BuiltFixture


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
    assert editable == {"by_id", "all", "names", "add", "rename", "set_roots", "remove"}
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
    """**The name comes back exactly as it was given**, surrounding space included, since 014 T5.

    This declared `"  Movies  "` and read back `"Movies"` until 2026-09-14. A name is cleaned by
    `settle_name` now, in 014 spec section 3.6.2's order, and a strip in `create` afterwards would
    undo the step a client can see: `Movies?` settles to `Movies `, and would have been stored as
    `Movies`.
    """
    library = config.create(repositories, "Movies ", "movies", ("/mnt/a", "/mnt/b"))
    read_back = repositories.by_id(library.id)
    assert read_back is not None
    assert read_back.name == "Movies "
    assert read_back.collection_type is CollectionType.MOVIES
    assert read_back.roots == ("/mnt/a", "/mnt/b")


def test_a_library_becomes_a_collection_folder_item(repositories: LibraryRepository) -> None:
    """Spec section 3.1: each library becomes a `CollectionFolder`."""
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    assert library.item_id == for_library(library.id)


def test_two_libraries_with_the_same_name_are_two_libraries(
    repositories: LibraryRepository,
) -> None:
    """Two roots are two libraries, whatever they are called.

    The reason changed on 2026-09-06 and the answer did not: this passed because the identifier was
    minted and a name was a label, and it passes now because the **roots** are in the key. The
    stronger half of the same claim is the test below, which the old rule could not have made.
    """
    one = config.create(repositories, "Movies", "movies", ("/mnt/a",))
    other = config.create(repositories, "Movies", "movies", ("/mnt/b",))
    assert one.id != other.id


def test_declaring_one_library_twice_is_refused(repositories: LibraryRepository) -> None:
    """AC-17's other half. The same declaration is the same library, so this is not a second one.

    Under the minted identifier this made two libraries that looked alike, and every file under
    them was found twice under two identifiers - which nothing refused and nothing reported.
    """
    config.create(repositories, "Movies", "movies", ("/mnt/films",))
    with pytest.raises(config.LibraryAlreadyDeclaredError) as refusal:
        config.create(repositories, "Movies", "movies", ("/mnt/films",))
    assert "found twice" in str(refusal.value)
    assert len(repositories.all()) == 1


def test_the_roots_are_a_set_rather_than_a_sequence(repositories: LibraryRepository) -> None:
    """Declaring the same two directories in the other order is the same library, not a second."""
    one = config.create(repositories, "Movies", "movies", ("/mnt/a", "/mnt/b"))
    with pytest.raises(config.LibraryAlreadyDeclaredError):
        config.create(repositories, "Movies", "movies", ("/mnt/b", "/mnt/a"))
    assert len(repositories.all()) == 1
    assert one.roots == ("/mnt/a", "/mnt/b"), "what is stored is what the operator declared"


def test_the_case_flag_is_part_of_the_declaration(repositories: LibraryRepository) -> None:
    """It is an input to every identifier under the library, so it is one to the library's own."""
    one = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    other = config.create(
        repositories, "Movies", "movies", ("/mnt/films",), case_sensitive_identity=True
    )
    assert one.id != other.id


def test_renaming_a_library_keeps_every_identifier(repositories: LibraryRepository) -> None:
    """The half of the old rule that survives deriving the identifier: it is derived **once**.

    `update` writes the new name and never recomputes the key, so an edit still moves nothing.
    """
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    before = for_file(ItemType.MOVIE, library.id, "The Film (1999).mkv")
    config.update(repositories, library.id, name="Films")
    after = for_file(ItemType.MOVIE, library.id, "The Film (1999).mkv")
    assert before == after


def test_moving_a_root_keeps_every_identifier(repositories: LibraryRepository) -> None:
    """AC-10 at the configuration level: the root is not part of any **item's** key.

    It is part of the library's own, since 2026-09-06 - and that is why this asserts an `update`
    and not a re-declaration: the derivation happens once, at creation, and moving a mount
    afterwards leaves every identifier where it was.
    """
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


def test_a_library_with_no_roots_is_stored_with_none(repositories: LibraryRepository) -> None:
    """Refused until 014 T5. The reference adds a library with no path, and 014 decided to do the
    same, as an empty library (014 spec section 3.6, behaviours section 3.31) - the nesting refusal
    below is the half of the old rule that protects identity, and it stays."""
    library = config.create(repositories, "Movies", "movies", ())
    read_back = repositories.by_id(library.id)
    assert read_back is not None
    assert read_back.roots == ()
    assert read_back.id == library.id


def test_a_root_inside_another_root_is_refused(repositories: LibraryRepository) -> None:
    """Every file under the inner one would be found twice, under two identifiers."""
    with pytest.raises(ValueError, match="is inside"):
        config.create(repositories, "Movies", "movies", ("/mnt/films", "/mnt/films/2024"))


def test_the_same_root_twice_is_one_root(repositories: LibraryRepository) -> None:
    library = config.create(repositories, "Movies", "movies", ("/mnt/films", "/mnt/films/"))
    assert repositories.by_id(library.id).roots == ("/mnt/films",)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "collection_type", ["musicvideos", "homevideos", "boxsets", "books", "mixed", None]
)
def test_a_library_of_a_type_this_server_does_not_scan_is_stored_with_that_type(
    repositories: LibraryRepository, collection_type: str | None
) -> None:
    """Refused until 014 T5, for `books`. Every declared type is created as the reference creates
    it, and so is a library with none (014 spec section 3.6.1); what is scanned did not widen."""
    library = config.create(repositories, "Shelf", collection_type, ("/mnt/shelf",))
    read_back = repositories.by_id(library.id)
    assert read_back is not None
    expected = None if collection_type is None else CollectionType(collection_type)
    assert read_back.collection_type is expected


def test_a_type_the_reference_does_not_declare_is_refused(repositories: LibraryRepository) -> None:
    """`photos` is stored as no type, and that mapping is the route's, taken before the domain sees
    the value (014 plan section 4) - so the domain still refuses the spelling itself."""
    with pytest.raises(ValueError):
        config.create(repositories, "Photos", "photos", ("/mnt/photos",))
    assert repositories.all() == []


def test_a_name_that_settled_to_a_trailing_space_is_its_own_library(
    repositories: LibraryRepository,
) -> None:
    """`Movies?` settles to `Movies ` (014 spec section 3.6.2) and is added beside `Movies` over the
    same roots - the reference's answer. A name stripped by `create` refused it as a second copy."""
    plain = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    padded = config.create(
        repositories, config.settle_name("Movies?", ["Movies"]), "movies", ("/mnt/films",)
    )
    assert plain.id != padded.id
    assert sorted(one.name for one in repositories.all()) == ["Movies", "Movies "]


def test_a_library_with_no_type_and_one_with_a_type_are_two_libraries(
    repositories: LibraryRepository,
) -> None:
    """The declaration with no type derives an identifier no typed one does."""
    typed = config.create(repositories, "Shelf", "movies", ("/mnt/shelf",))
    untyped = config.create(repositories, "Shelf", None, ("/mnt/shelf",))
    assert typed.id != untyped.id
    assert len(repositories.all()) == 2


def test_updating_a_library_that_does_not_exist_says_so(repositories: LibraryRepository) -> None:
    with pytest.raises(LookupError, match="no library"):
        config.update(repositories, "0" * 32, name="Anything")


def test_removing_a_library_removes_it(repositories: LibraryRepository) -> None:
    library = config.create(repositories, "Movies", "movies", ("/mnt/films",))
    repositories.remove(library.id)
    assert repositories.by_id(library.id) is None
    assert repositories.all() == []


# ------------------------------------------------------------------------------------------
# A library and its view, created together (014, operator decision 2026-09-14)
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "with_roots"),
    [("music", True), ("books", True), (None, True), ("movies", False)],
    ids=["scannable", "unscannable", "untyped", "no-roots"],
)
def test_a_library_is_created_with_its_folder_and_a_scan_leaves_the_folder_alone(
    engine: Engine, fixture_library: BuiltFixture, kind: str | None, with_roots: bool
) -> None:
    """`create_with_view` writes the one row a scan would have written for the library itself -
    the same identifier, name and sort name - so the scan after it **neither adds a second folder
    nor re-identifies this one**: the folder is reported unchanged and keeps its creation date.

    A library with no roots is not scanned by the scanner at all; `scan` itself refuses it, so the
    folder is all it will ever have, and it is there.
    """
    factory = session_factory(engine)
    roots = (str(fixture_library.of("music").root),) if with_roots else ()
    with session_scope(factory) as db:
        library = config.create_with_view(db, "Shelf", kind, roots)

    with session_scope(factory) as db:
        before = ItemRepository(db).by_library(library.id)
    assert list(before) == [library.item_id]
    (folder,) = before.values()
    assert folder.type is ItemType.COLLECTION_FOLDER
    assert (folder.name, folder.parent_id) == ("Shelf", None)
    if not with_roots:
        return

    with session_scope(factory) as db:
        report = scan(library, db, prober=not_media)
    with session_scope(factory) as db:
        after = ItemRepository(db).by_library(library.id)

    folders = [one for one in after.values() if one.type is ItemType.COLLECTION_FOLDER]
    assert [one.id for one in folders] == [library.item_id], "one folder, the same identifier"
    assert folders[0].date_created == folder.date_created
    assert folders[0].sort_name == folder.sort_name
    assert report.added == len(after) - 1, "everything but the folder is new"
    assert report.unchanged == 1, "the folder is the one row the scan found as it left it"
    assert report.updated == 0


def test_a_library_and_its_folder_are_one_unit_of_work(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A folder that cannot be written leaves no library behind it: the caller's transaction holds
    both, so a failure in the second rolls back the first."""
    factory = session_factory(engine)

    def refuse(_repository: ItemRepository, _item: object) -> None:
        raise RuntimeError("the folder could not be written")

    monkeypatch.setattr(ItemRepository, "add", refuse)
    with pytest.raises(RuntimeError), session_scope(factory) as db:
        config.create_with_view(db, "Movies", "movies", ("/mnt/films",))

    with session_scope(factory) as db:
        assert LibraryRepository(db).all() == []
