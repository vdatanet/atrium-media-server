# SPDX-License-Identifier: GPL-3.0-or-later
"""The write path: by-name rows, the join tables, and what a failure part-way leaves behind.

**AC-14 is held here first** - two spellings of one genre produce one item, and the first spelling
displays - and again end-to-end at T10. Twice on purpose: this suite proves the rule, that one
proves the rule is the one a scan uses.

The other thing this suite is for is the property no single method states: `apply` writes one item
**completely or not at all**. An item's genres live in a second table, and an item carrying its new
name with its old genres is worse than an item nothing touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select

from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import ItemRepository, LibraryRepository, MetadataRepository
from atrium.domain.items import Item as DomainItem
from atrium.domain.items import ItemType, MediaSource
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.identity import for_by_name, for_file, for_name
from atrium.metadata.artwork import ImageAssociation, ImageKind, SourceKind
from atrium.metadata.byname import fold_for_search
from atrium.metadata.merge import MetadataChanges
from atrium.metadata.model import Field, MetadataField, PersonCredit, PersonKind
from tests.conftest import data_dir


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def library(engine: Engine, tmp_path: Path) -> Library:
    root = tmp_path / "films"
    root.mkdir()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return config.create(LibraryRepository(db), "Films", "movies", (str(root),))


def a_film(engine: Engine, library: Library, name: str = "The Fixture") -> str:
    """One film in the database, so there is something to apply metadata to."""
    relative = f"{name}.mkv"
    item_id = for_file(ItemType.MOVIE, library.id, relative)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        ItemRepository(db).add(
            DomainItem(
                id=item_id,
                type=ItemType.MOVIE,
                name=name,
                library_id=library.id,
                sources=(MediaSource(relative_path=relative),),
            )
        )
    return item_id


def applied(engine: Engine, item_id: str, changes: MetadataChanges, **kwargs: object) -> None:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        MetadataRepository(db).apply(item_id, changes, **kwargs)  # type: ignore[arg-type]


def rows(engine: Engine, model: object) -> list[object]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return list(db.execute(select(model)).scalars())  # type: ignore[arg-type]


# ----------------------------------------------------------------------------------------------
# AC-14: two spellings, one row, first spelling displays
# ----------------------------------------------------------------------------------------------


def test_two_spellings_of_one_genre_produce_one_item(engine: Engine, library: Library) -> None:
    first = a_film(engine, library, "First Film")
    second = a_film(engine, library, "Second Film")

    applied(engine, first, MetadataChanges(values={Field.GENRES: ["Sci-Fi"]}))
    applied(engine, second, MetadataChanges(values={Field.GENRES: ["sci-fi"]}))

    genres = [one for one in rows(engine, models.Item) if one.type == ItemType.GENRE]  # type: ignore[attr-defined]
    assert len(genres) == 1
    assert genres[0].name == "Sci-Fi", "the first spelling seen is the one that displays"  # type: ignore[attr-defined]


def test_each_item_keeps_the_spelling_its_own_file_used(engine: Engine, library: Library) -> None:
    """Two facts, two homes. An item's own response carries its own spelling; `/Genres` shows the
    first anybody used. Deriving either from the other loses the other."""
    first = a_film(engine, library, "First Film")
    second = a_film(engine, library, "Second Film")
    applied(engine, first, MetadataChanges(values={Field.GENRES: ["Sci-Fi"]}))
    applied(engine, second, MetadataChanges(values={Field.GENRES: ["sci-fi"]}))

    spellings = {one.item_id: one.name for one in rows(engine, models.ItemGenre)}  # type: ignore[attr-defined]
    assert spellings == {first: "Sci-Fi", second: "sci-fi"}


def test_a_genre_and_a_music_genre_of_one_name_are_two_rows(
    engine: Engine, library: Library, tmp_path: Path
) -> None:
    """What keeps `/Genres` and `/MusicGenres` disjoint, decided at write time by what referred to
    the name rather than by a query guessing from context."""
    film = a_film(engine, library, "A Film")
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Electronic"]}))

    music_root = tmp_path / "music"
    music_root.mkdir()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        music = config.create(LibraryRepository(db), "Music", "music", (str(music_root),))
    track_id = for_file(ItemType.AUDIO, music.id, "01 - A Track.flac")
    with session_scope(factory) as db:
        ItemRepository(db).add(
            DomainItem(
                id=track_id,
                type=ItemType.AUDIO,
                name="A Track",
                library_id=music.id,
                sources=(MediaSource(relative_path="01 - A Track.flac"),),
            )
        )
    applied(engine, track_id, MetadataChanges(values={Field.GENRES: ["Electronic"]}))

    kinds = sorted(
        one.type
        for one in rows(engine, models.Item)
        if one.type in ("Genre", "MusicGenre")  # type: ignore[attr-defined]
    )
    assert kinds == ["Genre", "MusicGenre"]


@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("Sci-Fi", "sci-fi", True),
        ("Sci-Fi", "SCI-FI", True),
        ("  Rock  ", "Rock", True),
        # Path-invalid characters become spaces, so these two names are one genre.
        ("Drama/Romance", "Drama Romance", True),
        # Diacritics are **not** folded. Merging these would lose a genre the reference keeps.
        ("Elektro", "Elektró", False),
        ("Drama", "Romance", False),
    ],
)
def test_the_folds_envelope(
    engine: Engine, library: Library, first: str, second: str, same: bool
) -> None:
    one = a_film(engine, library, "One")
    two = a_film(engine, library, "Two")
    applied(engine, one, MetadataChanges(values={Field.GENRES: [first]}))
    applied(engine, two, MetadataChanges(values={Field.GENRES: [second]}))

    genres = [row for row in rows(engine, models.Item) if row.type == ItemType.GENRE]  # type: ignore[attr-defined]
    assert len(genres) == (1 if same else 2)


def test_a_by_name_row_has_no_library_and_no_parent(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Drama"]}))
    genre = next(row for row in rows(engine, models.Item) if row.type == ItemType.GENRE)  # type: ignore[attr-defined]
    assert genre.library_id is None  # type: ignore[attr-defined]
    assert genre.parent_id is None  # type: ignore[attr-defined]


def test_a_by_name_row_carries_a_folded_name_for_005_to_search(
    engine: Engine, library: Library
) -> None:
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Électronique"]}))
    genre = next(row for row in rows(engine, models.Item) if row.type == ItemType.GENRE)  # type: ignore[attr-defined]
    assert genre.name_folded == "electronique", "diacritics folded for search, kept for identity"  # type: ignore[attr-defined]
    assert genre.name == "Électronique"  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------------------------
# The join tables
# ----------------------------------------------------------------------------------------------


def test_a_cast_keeps_its_order_and_its_roles(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    applied(
        engine,
        film,
        MetadataChanges(
            values={
                Field.PEOPLE: [
                    PersonCredit("First Billed", role="The Lead"),
                    PersonCredit("Second Billed", role="The Other One"),
                    PersonCredit("A Director", kind=PersonKind.DIRECTOR),
                ]
            }
        ),
    )
    people = sorted(rows(engine, models.ItemPerson), key=lambda one: one.sort_order)  # type: ignore[attr-defined]
    assert [(one.name, one.person_type, one.role) for one in people] == [  # type: ignore[attr-defined]
        ("First Billed", "Actor", "The Lead"),
        ("Second Billed", "Actor", "The Other One"),
        ("A Director", "Director", None),
    ]


def test_a_person_is_a_by_name_row_and_the_role_is_not(engine: Engine, library: Library) -> None:
    """The same actor is a different character in every film, which is exactly why the role
    belongs to the association rather than to the person."""
    first = a_film(engine, library, "First Film")
    second = a_film(engine, library, "Second Film")
    applied(
        engine, first, MetadataChanges(values={Field.PEOPLE: [PersonCredit("An Actor", role="A")]})
    )
    applied(
        engine, second, MetadataChanges(values={Field.PEOPLE: [PersonCredit("An Actor", role="B")]})
    )

    assert len([row for row in rows(engine, models.Item) if row.type == ItemType.PERSON]) == 1  # type: ignore[attr-defined]
    assert sorted(one.role for one in rows(engine, models.ItemPerson)) == ["A", "B"]  # type: ignore[attr-defined]


def test_an_artists_credit_kind_survives(engine: Engine, library: Library, tmp_path: Path) -> None:
    """`/Artists` and `/Artists/AlbumArtists` are this column and nothing else."""
    music_root = tmp_path / "music"
    music_root.mkdir()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        music = config.create(LibraryRepository(db), "Music", "music", (str(music_root),))
    track_id = for_file(ItemType.AUDIO, music.id, "01 - A Track.flac")
    with session_scope(factory) as db:
        ItemRepository(db).add(
            DomainItem(
                id=track_id,
                type=ItemType.AUDIO,
                name="A Track",
                library_id=music.id,
                sources=(MediaSource(relative_path="01 - A Track.flac"),),
            )
        )
    applied(
        engine,
        track_id,
        MetadataChanges(
            values={
                Field.ARTISTS: ["First", "Second"],
                Field.ALBUM_ARTISTS: ["The Album Artist"],
            }
        ),
    )
    credits_ = {(one.credit, one.position): one.name for one in rows(engine, models.ItemArtist)}  # type: ignore[attr-defined]
    assert credits_ == {
        ("artist", 0): "First",
        ("artist", 1): "Second",
        ("album_artist", 0): "The Album Artist",
    }


def test_reapplying_replaces_a_list_rather_than_appending(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Drama", "Romance"]}))
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Thriller"]}))
    assert [one.name for one in rows(engine, models.ItemGenre)] == ["Thriller"]  # type: ignore[attr-defined]


def test_a_field_no_change_mentions_is_left_alone(engine: Engine, library: Library) -> None:
    """`MetadataChanges` carries only what changed, so applying an empty one twice must not blank
    a list that a previous refresh wrote."""
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Drama"]}))
    applied(engine, film, MetadataChanges(values={Field.OVERVIEW: "Something"}))
    assert [one.name for one in rows(engine, models.ItemGenre)] == ["Drama"]  # type: ignore[attr-defined]


def test_images_are_written_with_their_dimensions_and_tags(
    engine: Engine, library: Library
) -> None:
    film = a_film(engine, library)
    applied(
        engine,
        film,
        MetadataChanges(
            values={
                Field.IMAGES: [
                    ImageAssociation(
                        ImageKind.PRIMARY, 0, SourceKind.FILE, "poster.jpg", 2, 3, "a" * 32
                    ),
                    ImageAssociation(
                        ImageKind.BACKDROP, 0, SourceKind.FILE, "fanart.jpg", 16, 9, "b" * 32
                    ),
                ]
            }
        ),
    )
    images = {one.image_type: one for one in rows(engine, models.ItemImage)}  # type: ignore[attr-defined]
    assert set(images) == {"Primary", "Backdrop"}
    assert (images["Primary"].width, images["Primary"].height) == (2, 3)  # type: ignore[attr-defined]
    assert images["Primary"].source_kind == "file"  # type: ignore[attr-defined]


def test_an_embedded_image_is_stored_with_no_path(engine: Engine, library: Library) -> None:
    """`source_kind = 'embedded'` and a null path: the bytes are inside the audio file, which the
    schema's own check constraint says from the other side."""
    film = a_film(engine, library)
    applied(
        engine,
        film,
        MetadataChanges(
            values={
                Field.IMAGES: [
                    ImageAssociation(
                        ImageKind.PRIMARY, 0, SourceKind.EMBEDDED, None, 1, 1, "c" * 32
                    )
                ]
            }
        ),
    )
    image = rows(engine, models.ItemImage)[0]
    assert image.source_kind == "embedded"  # type: ignore[attr-defined]
    assert image.relative_path is None  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------------------------
# Scalars, names and locks
# ----------------------------------------------------------------------------------------------


def test_the_scalar_columns_are_written(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    applied(
        engine,
        film,
        MetadataChanges(
            values={
                Field.OVERVIEW: "A film.",
                Field.TAGLINE: "Every field, once.",
                Field.ORIGINAL_TITLE: "El Atrezzo",
                Field.YEAR: 1999,
                Field.PREMIERE_DATE: datetime(1999, 4, 23, tzinfo=UTC),
                Field.OFFICIAL_RATING: "PG-13",
                Field.COMMUNITY_RATING: 7.4,
                Field.NORMALIZATION_GAIN: -7.25,
            }
        ),
    )
    row = next(one for one in rows(engine, models.Item) if one.id == film)  # type: ignore[attr-defined]
    assert row.overview == "A film."  # type: ignore[attr-defined]
    assert row.production_year == 1999  # type: ignore[attr-defined]
    assert row.community_rating == pytest.approx(7.4)  # type: ignore[attr-defined]
    assert row.normalization_gain == pytest.approx(-7.25)  # type: ignore[attr-defined]
    assert row.metadata_refreshed_at is not None  # type: ignore[attr-defined]


def test_a_new_name_brings_a_new_sort_name_and_a_new_folded_name(
    engine: Engine, library: Library
) -> None:
    """The two columns cannot be allowed to disagree with the name, so they are recomputed here
    rather than by the caller."""
    film = a_film(engine, library, "The Fixture")
    applied(engine, film, MetadataChanges(values={Field.NAME: "An Amélie Sequel"}))
    row = next(one for one in rows(engine, models.Item) if one.id == film)  # type: ignore[attr-defined]
    assert row.name == "An Amélie Sequel"  # type: ignore[attr-defined]
    assert row.name_folded == fold_for_search("An Amélie Sequel")  # type: ignore[attr-defined]
    assert row.sort_name and row.sort_name != "the fixture"  # type: ignore[attr-defined]


def test_an_explicit_sort_title_replaces_the_derivation(engine: Engine, library: Library) -> None:
    film = a_film(engine, library, "The Fixture")
    applied(
        engine,
        film,
        MetadataChanges(values={Field.NAME: "The Fixture", Field.SORT_NAME: "Fixture, The"}),
    )
    row = next(one for one in rows(engine, models.Item) if one.id == film)  # type: ignore[attr-defined]
    assert "fixture, the" in row.sort_name.lower()  # type: ignore[attr-defined]


def test_locks_round_trip_in_the_references_spelling(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    applied(
        engine,
        film,
        MetadataChanges(),
        is_locked=True,
        locked_fields=[MetadataField.NAME, MetadataField.PRODUCTION_LOCATIONS],
    )
    factory = session_factory(engine)
    with session_scope(factory) as db:
        locked, fields = MetadataRepository(db).locks_of(film)
    assert locked
    assert fields == {MetadataField.NAME, MetadataField.PRODUCTION_LOCATIONS}


def test_a_lock_this_build_does_not_know_is_dropped_on_the_way_out(
    engine: Engine, library: Library
) -> None:
    """Written by a newer build, read by this one. Refusing the whole list would throw away the
    locks that *are* understood - the same rule the sidecar parser follows."""
    film = a_film(engine, library)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        row = db.get(models.Item, film)
        assert row is not None
        row.locked_fields = ["Name", "Sparkle"]
    with session_scope(factory) as db:
        _, fields = MetadataRepository(db).locks_of(film)
    assert fields == {MetadataField.NAME}


def test_what_the_item_already_has_comes_back_in_the_merges_vocabulary(
    engine: Engine, library: Library
) -> None:
    """The merge's whole left-hand column is "is this field empty?", and this is what answers it."""
    film = a_film(engine, library)
    applied(
        engine,
        film,
        MetadataChanges(
            values={
                Field.OVERVIEW: "A film.",
                Field.GENRES: ["Drama"],
                Field.PEOPLE: [PersonCredit("An Actor", role="The Lead")],
                Field.PROVIDER_IDS: {"Tmdb": "11111"},
            }
        ),
    )
    factory = session_factory(engine)
    with session_scope(factory) as db:
        found = MetadataRepository(db).values_of(film)
    assert found[Field.OVERVIEW] == "A film."
    assert found[Field.GENRES] == ["Drama"]
    assert found[Field.PROVIDER_IDS] == {"Tmdb": "11111"}
    people = found[Field.PEOPLE]
    assert isinstance(people, list)
    assert (people[0].name, people[0].role) == ("An Actor", "The Lead")


# ----------------------------------------------------------------------------------------------
# Garbage collection
# ----------------------------------------------------------------------------------------------


def test_a_by_name_row_nothing_references_is_collected(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Drama"]}))
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Thriller"]}))

    factory = session_factory(engine)
    with session_scope(factory) as db:
        collected = MetadataRepository(db).collect_by_name_garbage()
    assert collected == 1
    assert [row.name for row in rows(engine, models.Item) if row.type == ItemType.GENRE] == [  # type: ignore[attr-defined]
        "Thriller"
    ]


def test_a_referenced_row_survives(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Drama"]}))
    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert MetadataRepository(db).collect_by_name_garbage() == 0


def test_a_recreated_row_has_the_same_identifier(engine: Engine, library: Library) -> None:
    """Which is what makes collection safe here and not for 003's containers: a by-name row is
    **derivable**, so the only thing lost is which spelling came first - exactly what the
    reference loses too."""
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Drama"]}))
    before = next(row.id for row in rows(engine, models.Item) if row.type == ItemType.GENRE)  # type: ignore[attr-defined]

    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Thriller"]}))
    factory = session_factory(engine)
    with session_scope(factory) as db:
        MetadataRepository(db).collect_by_name_garbage()

    applied(engine, film, MetadataChanges(values={Field.GENRES: ["drama"]}))
    after = [row.id for row in rows(engine, models.Item) if row.type == ItemType.GENRE]
    assert before in after
    assert before == for_by_name(ItemType.GENRE, "Drama")


def test_collection_does_not_touch_items_in_the_tree(engine: Engine, library: Library) -> None:
    film = a_film(engine, library)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        MetadataRepository(db).collect_by_name_garbage()
    assert any(row.id == film for row in rows(engine, models.Item))  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------------------------
# All or nothing
# ----------------------------------------------------------------------------------------------


def test_a_failure_part_way_through_leaves_no_half_written_item(
    engine: Engine, library: Library
) -> None:
    """An item's genres live in a second table. An item with its new name and its old genres is
    worse than an item nothing touched, so `apply` flushes as a whole inside the caller's
    transaction and the caller's rollback takes all of it.
    """
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.NAME: "Before", Field.GENRES: ["Drama"]}))

    factory = session_factory(engine)
    with pytest.raises(RuntimeError, match="deliberate"), session_scope(factory) as db:
        MetadataRepository(db).apply(
            film, MetadataChanges(values={Field.NAME: "After", Field.GENRES: ["Thriller"]})
        )
        raise RuntimeError("deliberate: something later in the refresh failed")

    row = next(one for one in rows(engine, models.Item) if one.id == film)  # type: ignore[attr-defined]
    assert row.name == "Before"  # type: ignore[attr-defined]
    assert [one.name for one in rows(engine, models.ItemGenre)] == ["Drama"]  # type: ignore[attr-defined]


def test_applying_to_an_item_that_is_not_there_is_a_lookup_error(engine: Engine) -> None:
    factory = session_factory(engine)
    with pytest.raises(LookupError), session_scope(factory) as db:
        MetadataRepository(db).apply("f" * 32, MetadataChanges(values={Field.NAME: "x"}))


def test_pending_items_are_the_ones_a_scan_retries(engine: Engine, library: Library) -> None:
    """AC-8's channel: the next scan retries these even when their files did not change."""
    first = a_film(engine, library, "First Film")
    second = a_film(engine, library, "Second Film")
    applied(engine, first, MetadataChanges(), refresh_pending=True)
    applied(engine, second, MetadataChanges(), refresh_pending=False)

    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert MetadataRepository(db).pending(library.id) == [first]


#: Modules under `metadata/` that may reach `db/` at all, and what each is allowed to reach for.
#:
#: The rule architecture section 1 states is that `metadata/` must not write **the item table**
#: directly - not that it may not know a database exists. Two modules legitimately do:
#:
#: * `refresh.py` is the orchestrator and the only caller of the write repository, which is the
#:   shape the rule asks for rather than an exception to it;
#: * `remote.py` owns `provider_cache`, which is **its own** table and promises nothing - its rows
#:   are what somebody else's server said and are evictable at any time.
#:
#: Everything else in the package is a reader that returns values. A module that grew an import
#: of the item models would be writing rows from the wrong side of the boundary, and that is what
#: this test is for.
MAY_REACH_THE_DATABASE = {"refresh.py": "the write repository", "remote.py": "provider_cache"}


def test_no_reader_under_metadata_reaches_the_database() -> None:
    """Asserted on the source rather than by convention."""
    import ast

    package = Path(__file__).resolve().parents[2] / "src" / "atrium" / "metadata"
    offenders = []
    for module in sorted(package.glob("*.py")):
        if module.name in MAY_REACH_THE_DATABASE:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        if any(one.startswith("atrium.db") for one in imported):
            offenders.append(module.name)
    assert not offenders, (
        f"{offenders} reach atrium.db. Only {sorted(MAY_REACH_THE_DATABASE)} may, and each for "
        f"the reason named beside it."
    )


def test_nothing_under_metadata_imports_the_item_models_directly() -> None:
    """Not even the two that may reach the database: `refresh.py` goes through the repository, and
    `remote.py` touches one table it owns. A module holding `models.Item` would be one edit away
    from writing an item row without the repository ever knowing."""
    import ast

    package = Path(__file__).resolve().parents[2] / "src" / "atrium" / "metadata"
    for module in sorted(package.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "atrium.db.models"
            for alias in node.names
        }
        assert not names & {"Item", "ItemGenre", "ItemStudio", "ItemPerson", "ItemArtist"}, (
            f"{module.name} imports {sorted(names)} - item rows are the repository's"
        )


def test_the_item_count_is_what_it_should_be(engine: Engine, library: Library) -> None:
    """A guard against the join-table writes quietly creating extra items: one film, one genre."""
    film = a_film(engine, library)
    applied(engine, film, MetadataChanges(values={Field.GENRES: ["Drama"]}))
    factory = session_factory(engine)
    with session_scope(factory) as db:
        assert db.execute(select(func.count()).select_from(models.Item)).scalar() == 2


def test_a_credit_naming_somebody_who_is_not_an_item_keeps_the_name_and_drops_the_link(
    engine: Engine, library: Library, tmp_path: Path
) -> None:
    """The consequence of behaviours section 5.3 that nobody had followed down.

    The scanner creates one `MusicArtist` per **album artist**. A track's performers are
    frequently other people, so a credit naming one has a name and no item behind it. The name is
    what a client renders; the link is what makes it clickable.
    """
    music_root = tmp_path / "music"
    music_root.mkdir()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        music = config.create(LibraryRepository(db), "Music", "music", (str(music_root),))

    artist_id = for_name(ItemType.MUSIC_ARTIST, music.id, "The Album Artist")
    track_id = for_file(ItemType.AUDIO, music.id, "01 - A Track.flac")
    with session_scope(factory) as db:
        repository = ItemRepository(db)
        repository.add(
            DomainItem(
                id=artist_id,
                type=ItemType.MUSIC_ARTIST,
                name="The Album Artist",
                library_id=music.id,
            )
        )
        repository.add(
            DomainItem(
                id=track_id,
                type=ItemType.AUDIO,
                name="A Track",
                library_id=music.id,
                sources=(MediaSource(relative_path="01 - A Track.flac"),),
            )
        )

    applied(
        engine,
        track_id,
        MetadataChanges(
            values={
                Field.ALBUM_ARTISTS: ["The Album Artist"],
                Field.ARTISTS: ["A Guest Performer"],
            }
        ),
    )
    links = {one.name: one.artist_item_id for one in rows(engine, models.ItemArtist)}  # type: ignore[attr-defined]
    assert links == {"The Album Artist": artist_id, "A Guest Performer": None}


def test_the_refresh_does_not_invent_a_music_artist(
    engine: Engine, library: Library, tmp_path: Path
) -> None:
    """Creating the missing item here would put a tree item outside the scan that builds the tree,
    and the next scan - which reconciles what it resolved against what exists - would mark it
    removed. A row that appears and disappears every other scan."""
    music_root = tmp_path / "music"
    music_root.mkdir()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        music = config.create(LibraryRepository(db), "Music", "music", (str(music_root),))
    track_id = for_file(ItemType.AUDIO, music.id, "01 - A Track.flac")
    with session_scope(factory) as db:
        ItemRepository(db).add(
            DomainItem(
                id=track_id,
                type=ItemType.AUDIO,
                name="A Track",
                library_id=music.id,
                sources=(MediaSource(relative_path="01 - A Track.flac"),),
            )
        )
    applied(engine, track_id, MetadataChanges(values={Field.ARTISTS: ["Nobody's Album Artist"]}))
    assert not [one for one in rows(engine, models.Item) if one.type == ItemType.MUSIC_ARTIST]  # type: ignore[attr-defined]
