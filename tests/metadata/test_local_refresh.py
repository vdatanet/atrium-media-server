# SPDX-License-Identifier: GPL-3.0-or-later
"""A scan and the refresh that follows it, over a library built for the purpose.

Eight acceptance criteria hold here at integration level - 1, 2, 4, 5, 6, 7, 11 and 14 - each of
them proved once more at the level where a user would notice it failing. The engine-level suites
prove the rules; this one proves the rules are the ones a scan uses.

**AC-15 lands here and stays.** Every byte of the library tree is hashed before and after a full
scan-and-refresh, and the test is written so that every task after this one runs under it: a write
path into a library root is the one failure in this feature that is quiet, and quiet failures get
their tests first.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from mutagen.flac import FLAC
from sqlalchemy import Engine, select

from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import LibraryRepository
from atrium.domain.items import ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.scan import scan
from atrium.metadata.model import RefreshMode
from tests.conftest import data_dir, not_media

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata"
NFO = FIXTURES / "nfo"
ART = FIXTURES / "artwork"
AUDIO = FIXTURES / "audio"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


def a_library(engine: Engine, root: Path, collection_type: str) -> Library:
    root.mkdir(parents=True, exist_ok=True)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return config.create(
            LibraryRepository(db), collection_type.title(), collection_type, (str(root),)
        )


def scanned(engine: Engine, library: Library, **options: object) -> object:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return scan(library, db, prober=not_media, **options)  # type: ignore[arg-type]


def items(engine: Engine) -> list[models.Item]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return list(db.execute(select(models.Item)).scalars())


def one(engine: Engine, kind: ItemType) -> models.Item:
    found = [row for row in items(engine) if row.type == kind]
    assert len(found) == 1, f"expected one {kind}, got {[row.name for row in found]}"
    return found[0]


def a_film(
    root: Path, name: str, *, sidecar: str | None = None, artwork: dict[str, str] | None = None
) -> Path:
    """A film in a folder of its own, optionally with a sidecar and some artwork."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    film = folder / f"{name}.mkv"
    film.write_bytes(b"atrium synthetic fixture - not media\n" + b"\0" * 600)
    if sidecar is not None:
        shutil.copy(NFO / sidecar, folder / f"{name}.nfo")
    for target, source in (artwork or {}).items():
        shutil.copy(ART / source, folder / target)
    return film


def a_track(root: Path, relative: str, **tags: object) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(AUDIO / "template.flac", path)
    opened = FLAC(path)
    for key, value in tags.items():
        opened[key] = list(value) if isinstance(value, list) else [str(value)]
    opened.save()
    return path


def digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ----------------------------------------------------------------------------------------------
# AC-15: nothing in a library root is created, modified or deleted
# ----------------------------------------------------------------------------------------------


def test_a_full_scan_and_refresh_leaves_the_library_byte_identical(
    engine: Engine, tmp_path: Path
) -> None:
    """**The guard, and it arrives before there is anything to guard against.**

    Zero network requests is trivial in this slice because no remote code exists - which is
    exactly why this lands now: it is cheap to hold before T11 and expensive to retrofit after.
    Every task after this one runs under it.
    """
    root = tmp_path / "films"
    a_film(
        root,
        "The Fixture",
        sidecar="movie-full.nfo",
        artwork={"poster.jpg": "names-first/poster.jpg"},
    )
    a_film(root, "The Sparse Fixture", sidecar="movie-sparse.nfo")
    a_film(root, "The Broken Fixture", sidecar="movie-malformed.nfo")
    library = a_library(engine, root, "movies")

    before = digest(root)
    scanned(engine, library)
    scanned(engine, library, deep=True)
    scanned(engine, library, refresh_mode=RefreshMode.REPLACE)

    after = digest(root)
    assert after == before, "a scan or a refresh wrote inside a library root"
    assert set(after) == set(before), "a file was created or deleted inside a library root"


def test_the_same_holds_for_a_music_library(engine: Engine, tmp_path: Path) -> None:
    """Music is where files are actually *opened*, so it is where a write would come from."""
    root = tmp_path / "music"
    a_track(root, "Some Folder/Another Folder/01 - First.flac", album="The Real Album", artist="A")
    library = a_library(engine, root, "music")

    before = digest(root)
    scanned(engine, library)
    scanned(engine, library, deep=True)
    assert digest(root) == before


# ----------------------------------------------------------------------------------------------
# AC-1, AC-2, AC-4: sidecars, end to end
# ----------------------------------------------------------------------------------------------


def test_a_film_with_a_full_sidecar_resolves_from_it(engine: Engine, tmp_path: Path) -> None:
    """AC-1. The name comes from the sidecar and **not** from the filename, which is only true
    because the path-derived values are the last source in the chain rather than the item's own."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", sidecar="movie-full.nfo")
    scanned(engine, a_library(engine, root, "movies"))

    film = one(engine, ItemType.MOVIE)
    assert film.name == "The Fixture"
    assert film.overview == "A film that exists so a parser has something to read."
    assert film.tagline == "Every field, once."
    assert film.original_title == "El Atrezzo"
    assert film.production_year == 1999
    assert film.official_rating == "PG-13"
    assert film.community_rating == pytest.approx(7.4)
    assert film.provider_ids == {"Tmdb": "11111", "Imdb": "tt2222222"}


def test_the_sidecar_beats_the_filename(engine: Engine, tmp_path: Path) -> None:
    """The measurement behind the whole ordering: a title in a sidecar replaces the name a scanner
    derived from a filename, because the reference folds what an item already had in **after**
    every provider has spoken."""
    root = tmp_path / "films"
    a_film(root, "Some Careless Filename", sidecar="movie-full.nfo")
    scanned(engine, a_library(engine, root, "movies"))
    assert one(engine, ItemType.MOVIE).name == "The Fixture"


def test_a_films_cast_genres_and_studios_reach_their_tables(engine: Engine, tmp_path: Path) -> None:
    root = tmp_path / "films"
    a_film(root, "The Fixture", sidecar="movie-full.nfo")
    scanned(engine, a_library(engine, root, "movies"))

    factory = session_factory(engine)
    with session_scope(factory) as db:
        genres = [one.name for one in db.execute(select(models.ItemGenre)).scalars()]
        studios = [one.name for one in db.execute(select(models.ItemStudio)).scalars()]
        people = sorted(
            db.execute(select(models.ItemPerson)).scalars(), key=lambda one: one.sort_order
        )
    assert genres == ["Drama", "Science Fiction", "Fantasy"], "the slash is split, as measured"
    assert studios == ["Fixture Pictures", "Second Studio"]
    assert [person.name for person in people][:3] == [
        "First Billed",
        "Second Billed",
        "Third Billed",
    ]
    assert people[0].role == "The Lead"


def test_a_sparse_sidecar_leaves_the_rest_to_the_next_source(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-2, per field. The title comes from the sidecar; the year comes from the sidecar; the
    overview is absent because `<plot></plot>` is present-and-empty and nothing below it has one."""
    root = tmp_path / "films"
    a_film(root, "Some Careless Filename", sidecar="movie-sparse.nfo")
    scanned(engine, a_library(engine, root, "movies"))

    film = one(engine, ItemType.MOVIE)
    assert film.name == "The Sparse Fixture"
    assert film.production_year == 2001
    assert film.overview is None
    assert film.tagline is None


def test_a_film_with_no_sidecar_keeps_its_path_derived_name(engine: Engine, tmp_path: Path) -> None:
    """The path source is last, not absent."""
    root = tmp_path / "films"
    a_film(root, "The Matrix (1999)")
    scanned(engine, a_library(engine, root, "movies"))
    assert one(engine, ItemType.MOVIE).name == "The Matrix"


def test_a_malformed_sidecar_warns_and_the_item_still_resolves(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-4. The warning names the file; the film resolves from its filename."""
    root = tmp_path / "films"
    a_film(root, "The Broken Fixture", sidecar="movie-malformed.nfo")
    report = scanned(engine, a_library(engine, root, "movies"))

    assert one(engine, ItemType.MOVIE).name == "The Broken Fixture"
    warnings = report.refreshed.warnings  # type: ignore[attr-defined]
    assert any("The Broken Fixture.nfo" in warning for warning in warnings)


def test_an_entity_bearing_sidecar_is_refused_before_anything_expands(
    engine: Engine, tmp_path: Path
) -> None:
    root = tmp_path / "films"
    a_film(root, "The Bomb", sidecar="movie-entity-bomb.nfo")
    report = scanned(engine, a_library(engine, root, "movies"))
    assert one(engine, ItemType.MOVIE).name == "The Bomb"
    assert any("document type" in warning for warning in report.refreshed.warnings)  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------------------------
# AC-5, AC-6: music
# ----------------------------------------------------------------------------------------------


def test_a_well_tagged_track_takes_its_album_and_artist_from_its_tags(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-5, end to end and through the real reader."""
    root = tmp_path / "music"
    a_track(
        root,
        "Some Folder/Another Folder/01 - First.flac",
        album="The Real Album",
        albumartist="The Real Artist",
        title="The Real Title",
    )
    scanned(engine, a_library(engine, root, "music"))

    assert one(engine, ItemType.MUSIC_ALBUM).name == "The Real Album"
    assert one(engine, ItemType.MUSIC_ARTIST).name == "The Real Artist"
    assert one(engine, ItemType.AUDIO).name == "The Real Title"


def test_a_track_with_three_artists_yields_three_artists(engine: Engine, tmp_path: Path) -> None:
    """AC-6, end to end: three rows with the `artist` credit, in order."""
    root = tmp_path / "music"
    a_track(
        root,
        "The Artist/The Album/01 - First.flac",
        album="The Album",
        albumartist="The Artist",
        artist=["First", "Second", "Third"],
    )
    scanned(engine, a_library(engine, root, "music"))

    factory = session_factory(engine)
    with session_scope(factory) as db:
        credits_ = sorted(
            db.execute(select(models.ItemArtist)).scalars(),
            key=lambda one: (one.credit, one.position),
        )
    performers = [one.name for one in credits_ if one.credit == "artist"]
    assert performers == ["First", "Second", "Third"]


def test_a_tracks_genre_becomes_a_music_genre_rather_than_a_genre(
    engine: Engine, tmp_path: Path
) -> None:
    root = tmp_path / "music"
    a_track(
        root,
        "The Artist/The Album/01 - First.flac",
        album="The Album",
        albumartist="The Artist",
        genre="Electronic",
    )
    scanned(engine, a_library(engine, root, "music"))
    assert [row.type for row in items(engine) if row.type in ("Genre", "MusicGenre")] == [
        "MusicGenre"
    ]


def test_a_tracks_gain_reaches_the_column(engine: Engine, tmp_path: Path) -> None:
    root = tmp_path / "music"
    a_track(
        root,
        "The Artist/The Album/01 - First.flac",
        album="The Album",
        albumartist="The Artist",
        replaygain_track_gain="-7.25 dB",
    )
    scanned(engine, a_library(engine, root, "music"))
    assert one(engine, ItemType.AUDIO).normalization_gain == pytest.approx(-7.25)


# ----------------------------------------------------------------------------------------------
# AC-7: local artwork
# ----------------------------------------------------------------------------------------------


def test_local_artwork_becomes_the_right_image_type(engine: Engine, tmp_path: Path) -> None:
    """AC-7. The dimensions say which file won, which is the thing under test."""
    root = tmp_path / "films"
    a_film(
        root,
        "The Fixture",
        artwork={
            "poster.jpg": "names-first/poster.jpg",
            "fanart.jpg": "names-first/fanart.jpg",
            "logo.jpg": "names-first/logo.jpg",
        },
    )
    scanned(engine, a_library(engine, root, "movies"))

    factory = session_factory(engine)
    with session_scope(factory) as db:
        images = {one.image_type: one for one in db.execute(select(models.ItemImage)).scalars()}
    assert set(images) == {"Primary", "Backdrop", "Logo"}
    assert (images["Primary"].width, images["Primary"].height) == (2, 3)
    assert images["Primary"].source_kind == "file"
    assert images["Primary"].relative_path == "The Fixture/poster.jpg"
    assert len(images["Primary"].tag) == 32


def test_an_unreadable_image_is_skipped_and_the_next_name_wins(
    engine: Engine, tmp_path: Path
) -> None:
    root = tmp_path / "films"
    film = a_film(root, "The Fixture", artwork={"folder.png": "unreadable/folder.png"})
    (film.parent / "poster.jpg").write_text("not an image", encoding="utf-8")
    report = scanned(engine, a_library(engine, root, "movies"))

    factory = session_factory(engine)
    with session_scope(factory) as db:
        images = list(db.execute(select(models.ItemImage)).scalars())
    assert [(one.image_type, one.width, one.height) for one in images] == [("Primary", 4, 6)]
    assert any("poster.jpg" in warning for warning in report.refreshed.warnings)  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------------------------
# AC-11, AC-14
# ----------------------------------------------------------------------------------------------


def test_two_spellings_of_one_genre_become_one_item(engine: Engine, tmp_path: Path) -> None:
    """AC-14, end to end, through two real sidecars."""
    root = tmp_path / "films"
    for name, spelling in (("First Film", "Sci-Fi"), ("Second Film", "sci-fi")):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / f"{name}.mkv").write_bytes(b"atrium synthetic fixture\n" + b"\0" * 600)
        (folder / f"{name}.nfo").write_text(
            f"<movie><title>{name}</title><genre>{spelling}</genre></movie>", encoding="utf-8"
        )
    scanned(engine, a_library(engine, root, "movies"))

    genres = [row for row in items(engine) if row.type == ItemType.GENRE]
    assert len(genres) == 1, f"two spellings made {[row.name for row in genres]}"
    assert genres[0].name in ("Sci-Fi", "sci-fi")

    # *Which* spelling displays is whichever item was refreshed first, and a scan hands its items
    # over in identifier order - so asserting one of the two here would be asserting a hash. The
    # first-spelling-wins rule is held deterministically at repository level in
    # `test_write_path.py`, where the order is the test's to choose.
    factory = session_factory(engine)
    with session_scope(factory) as db:
        on_the_items = sorted(one.name for one in db.execute(select(models.ItemGenre)).scalars())
    assert on_the_items == ["Sci-Fi", "sci-fi"], "each item keeps the spelling its own file used"


def test_a_default_refresh_does_not_overwrite_what_a_previous_one_resolved(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-11 at integration level: the sidecar changes, and a default refresh keeps the value it
    already has."""
    root = tmp_path / "films"
    film = a_film(root, "The Fixture", sidecar="movie-full.nfo")
    library = a_library(engine, root, "movies")
    scanned(engine, library)

    (film.parent / "The Fixture.nfo").write_text(
        "<movie><title>The Fixture</title><plot>Something else entirely.</plot></movie>",
        encoding="utf-8",
    )
    scanned(engine, library, deep=True)
    assert one(engine, ItemType.MOVIE).overview == (
        "A film that exists so a parser has something to read."
    )


def test_replace_does_overwrite_it(engine: Engine, tmp_path: Path) -> None:
    root = tmp_path / "films"
    film = a_film(root, "The Fixture", sidecar="movie-full.nfo")
    library = a_library(engine, root, "movies")
    scanned(engine, library)

    (film.parent / "The Fixture.nfo").write_text(
        "<movie><title>The Fixture</title><plot>Something else entirely.</plot></movie>",
        encoding="utf-8",
    )
    scanned(engine, library, deep=True, refresh_mode=RefreshMode.REPLACE)
    assert one(engine, ItemType.MOVIE).overview == "Something else entirely."


def test_a_locked_field_survives_a_replace_refresh(engine: Engine, tmp_path: Path) -> None:
    """AC-10 through the only channel a lock has in v1: the sidecar."""
    root = tmp_path / "films"
    film = a_film(root, "The Fixture")
    (film.parent / "The Fixture.nfo").write_text(
        "<movie><title>The User's Title</title><lockedfields>Name</lockedfields></movie>",
        encoding="utf-8",
    )
    library = a_library(engine, root, "movies")
    scanned(engine, library)
    assert one(engine, ItemType.MOVIE).name == "The User's Title"

    (film.parent / "The Fixture.nfo").write_text(
        "<movie><title>Something Else</title><lockedfields>Name</lockedfields></movie>",
        encoding="utf-8",
    )
    scanned(engine, library, deep=True, refresh_mode=RefreshMode.REPLACE)
    assert one(engine, ItemType.MOVIE).name == "The User's Title"


# ----------------------------------------------------------------------------------------------
# A rescan of an unchanged library
# ----------------------------------------------------------------------------------------------


def test_a_rescan_of_an_unchanged_library_refreshes_nothing(engine: Engine, tmp_path: Path) -> None:
    """AC-13's local half, and the reason it will hold once there is a network: **nothing asks.**
    003's change detection means no item is handed to the refresh at all."""
    root = tmp_path / "films"
    a_film(
        root,
        "The Fixture",
        sidecar="movie-full.nfo",
        artwork={"poster.jpg": "names-first/poster.jpg"},
    )
    library = a_library(engine, root, "movies")

    first = scanned(engine, library)
    assert first.refreshed.changed >= 1  # type: ignore[attr-defined]

    second = scanned(engine, library)
    assert second.refreshed.considered == 0, "an unchanged library handed the refresh nothing"  # type: ignore[attr-defined]
    assert second.refreshed.changed == 0  # type: ignore[attr-defined]


def test_a_second_refresh_of_the_same_item_changes_nothing(engine: Engine, tmp_path: Path) -> None:
    """Idempotence at integration level: `deep` re-reads every file and finds nothing to write."""
    root = tmp_path / "films"
    a_film(
        root,
        "The Fixture",
        sidecar="movie-full.nfo",
        artwork={"poster.jpg": "names-first/poster.jpg"},
    )
    library = a_library(engine, root, "movies")
    scanned(engine, library)

    again = scanned(engine, library, deep=True)
    assert again.refreshed.changed == 0, "a deep rescan rewrote an item whose files had not moved"  # type: ignore[attr-defined]


def test_a_genre_nothing_references_any_more_is_collected(engine: Engine, tmp_path: Path) -> None:
    root = tmp_path / "films"
    film = a_film(root, "The Fixture")
    (film.parent / "The Fixture.nfo").write_text(
        "<movie><title>The Fixture</title><genre>Drama</genre></movie>", encoding="utf-8"
    )
    library = a_library(engine, root, "movies")
    scanned(engine, library)
    assert [row.name for row in items(engine) if row.type == ItemType.GENRE] == ["Drama"]

    (film.parent / "The Fixture.nfo").write_text(
        "<movie><title>The Fixture</title><genre>Thriller</genre></movie>", encoding="utf-8"
    )
    scanned(engine, library, deep=True, refresh_mode=RefreshMode.REPLACE)
    assert [row.name for row in items(engine) if row.type == ItemType.GENRE] == ["Thriller"]


def test_local_only_is_the_whole_of_this_slice(engine: Engine, tmp_path: Path) -> None:
    """`Local only` and `Default` produce the same result while no remote provider exists, which
    is the honest statement of what this task built."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", sidecar="movie-full.nfo")
    library = a_library(engine, root, "movies")
    scanned(engine, library, refresh_mode=RefreshMode.LOCAL_ONLY)
    film = one(engine, ItemType.MOVIE)
    assert film.name == "The Fixture"
    assert film.overview is not None


def test_a_container_borrows_the_same_directory_wherever_the_library_is_mounted(
    engine: Engine, tmp_path: Path
) -> None:
    """A container has no directory of its own and borrows a descendant's, and **which** one it
    borrows used to be a hash of the absolute path.

    `_first_file_backed` walked the children in identifier order, and an identifier is derived from
    the absolute path (003 spec section 3.6), so the choice moved with the mount point. That is not
    the harmless tie the genre spelling above is: the descendants of one container sit at different
    depths — a series whose second season has no season directory has an episode one level below it
    and the rest two — and the caller walks up a **fixed** number of levels from whichever it is
    handed. Land on the wrong one and the series looks for its `tvshow.nfo` in the library root,
    finds none, and keeps the path-derived name. Measured while writing 010 T10's comparison
    against a real reference, which reads that sidecar every time: about one run in ten
    `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`.

    The series here is that shape deliberately, and the assertion is on the **name**, because the
    borrowed directory is only visible through what was read from it.
    """
    for mount in ("aaaa", "zzzz"):
        root = tmp_path / mount / "shows"
        nested = root / "The Series" / "Season 01"
        nested.mkdir(parents=True)
        (nested / "The Series - S01E01 - Pilot.mkv").write_bytes(b"atrium fixture\n" + b"\0" * 600)
        stray = root / "The Series" / "The Series - S02E01 - Elsewhere.mkv"
        stray.write_bytes(b"atrium fixture\n" + b"\0" * 600)
        (root / "The Series" / "tvshow.nfo").write_text(
            "<tvshow><title>Named By Its Sidecar</title></tvshow>", encoding="utf-8"
        )
        scanned(engine, a_library(engine, root, "tvshows"))

    series = sorted(row.name for row in items(engine) if row.type == ItemType.SERIES)
    assert series == ["Named By Its Sidecar", "Named By Its Sidecar"], (
        "the series took its name from `tvshow.nfo` under one mount point and not under the "
        "other, so the directory a container borrows still depends on where the library sits"
    )
