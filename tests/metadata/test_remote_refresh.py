# SPDX-License-Identifier: GPL-3.0-or-later
"""A scan with providers wired in: modes, failures, and the zero-request rescan.

Six acceptance criteria hold here, and two of them could not hold before this task existed:

* **AC-1 is re-held now that providers exist.** T10 proved a fully-sidecared film makes zero
  network requests in a world with no remote code, which is a vacuous zero. Here there is a
  counting transport and a provider that would answer, and the film still makes no request -
  because [plan §6.8](../../specs/004-metadata-resolution/plan.md)'s third clause says remote is
  consulted only for fields the local pass left wanting.
* **AC-13** - scan, refresh, rescan of the unchanged library, and the transport shows **zero**.

The other four are AC-8 (every provider unreachable), AC-9 (no credentials), AC-10 (a lock
survives `Replace`) and AC-12 (an ambiguous match) at integration level, plus AC-15 re-run with
the remote code present and downloading.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, select

from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.db.repositories import LibraryRepository
from atrium.domain.items import ItemType
from atrium.domain.library import Library
from atrium.library import config
from atrium.library.scan import scan
from atrium.metadata.model import RefreshMode
from atrium.metadata.musicbrainz import NAME as MUSICBRAINZ
from atrium.metadata.musicbrainz import RATE as MUSICBRAINZ_RATE
from atrium.metadata.musicbrainz import MusicBrainzProvider, user_agent
from atrium.metadata.remote import ProviderCredentials, RemoteAccess
from atrium.metadata.tmdb import NAME as TMDB
from atrium.metadata.tmdb import RATE as TMDB_RATE
from atrium.metadata.tmdb import TmdbProvider
from tests.conftest import data_dir

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata"
TMDB_RESPONSES = FIXTURES / "tmdb"
MB_RESPONSES = FIXTURES / "musicbrainz"
POSTER = (FIXTURES / "artwork" / "names-first" / "poster.jpg").read_bytes()


def recorded(directory: Path, name: str) -> object:
    return json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))


class Counting(httpx.BaseTransport):
    """Answers from a table, counts everything, and can be told to be unreachable."""

    def __init__(self, replies: dict[str, object] | None = None, *, down: bool = False) -> None:
        self.replies = replies or {}
        self.down = down
        self.asked: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = str(request.url.path).removeprefix("/3").removeprefix("/ws/2")
        self.asked.append(path)
        if self.down:
            raise httpx.ConnectError("the provider is unreachable")
        if request.url.host and "image" in request.url.host:
            return httpx.Response(200, content=POSTER)
        reply = self.replies.get(path)
        if reply is None:
            return httpx.Response(404, json=None)
        return httpx.Response(200, json=reply)


TMDB_REPLIES: dict[str, object] = {
    "/search/movie": recorded(TMDB_RESPONSES, "search-movie-one"),
    "/movie/11111": recorded(TMDB_RESPONSES, "movie-11111"),
}
MB_REPLIES: dict[str, object] = {
    "/release-group": recorded(MB_RESPONSES, "search-one"),
    "/release-group/00000000-0000-4000-8000-000000000002": recorded(MB_RESPONSES, "release-group"),
}


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


def a_film(root: Path, name: str, *, sidecar: str | None = None, xml: str | None = None) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.mkv").write_bytes(b"atrium synthetic fixture\n" + b"\0" * 600)
    if sidecar is not None:
        shutil.copy(FIXTURES / "nfo" / sidecar, folder / f"{name}.nfo")
    if xml is not None:
        (folder / f"{name}.nfo").write_text(xml, encoding="utf-8")
    return folder


def scanned(
    engine: Engine,
    library: Library,
    *,
    tmdb: Counting | None = None,
    api_key: str = "a-key",
    contact: str = "",
    musicbrainz: Counting | None = None,
    artwork_root: Path | None = None,
    **options: object,
) -> object:
    """One scan, with whichever providers the test wants, over transports it can count."""
    factory = session_factory(engine)
    with session_scope(factory) as db:
        providers: list[object] = []
        if tmdb is not None:
            providers.append(
                TmdbProvider(
                    RemoteAccess(
                        TMDB,
                        session=db,
                        base_url="https://api.themoviedb.org/3",
                        rate=TMDB_RATE,
                        credentials=ProviderCredentials(api_key=api_key),
                        transport=tmdb,
                        sleep=lambda _: None,
                    ),
                    artwork_root=artwork_root or Path("/nowhere"),
                )
            )
        if musicbrainz is not None:
            providers.append(
                MusicBrainzProvider(
                    RemoteAccess(
                        MUSICBRAINZ,
                        session=db,
                        base_url="https://musicbrainz.org/ws/2",
                        rate=MUSICBRAINZ_RATE,
                        credentials=ProviderCredentials(contact=contact),
                        headers={"User-Agent": user_agent(contact)} if contact else {},
                        transport=musicbrainz,
                        sleep=lambda _: None,
                    )
                )
            )
        return scan(library, db, providers=providers, **options)  # type: ignore[arg-type]


def items(engine: Engine) -> list[models.Item]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        return list(db.execute(select(models.Item)).scalars())


def the_film(engine: Engine) -> models.Item:
    found = [row for row in items(engine) if row.type == ItemType.MOVIE]
    assert len(found) == 1
    return found[0]


def digest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ----------------------------------------------------------------------------------------------
# AC-1, re-held now that a provider exists to be consulted
# ----------------------------------------------------------------------------------------------


def test_a_fully_sidecared_film_makes_zero_network_requests(engine: Engine, tmp_path: Path) -> None:
    """**AC-1, non-vacuously.** T10 proved this in a world with no remote code, which proves
    nothing. Here TMDB is enabled and would answer, and it is still not asked - because the local
    pass left nothing wanting, which is plan §6.8's third clause doing its job rather than a cache
    absorbing a fetch.
    """
    root = tmp_path / "films"
    a_film(root, "The Fixture", sidecar="movie-full.nfo")
    transport = Counting(TMDB_REPLIES)
    scanned(engine, a_library(engine, root, "movies"), tmdb=transport)

    assert transport.asked == [], "a fully-sidecared film asked TMDB nothing"
    assert the_film(engine).overview == "A film that exists so a parser has something to read."


def test_a_film_with_a_sparse_sidecar_does_ask(engine: Engine, tmp_path: Path) -> None:
    """The other half of the same clause: a film **is** missing things, so the provider is
    consulted. Without this, the test above would pass for a provider nothing ever consults."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title><year>1999</year></movie>")
    transport = Counting(TMDB_REPLIES)
    scanned(engine, a_library(engine, root, "movies"), tmdb=transport)

    assert "/search/movie" in transport.asked
    assert the_film(engine).overview is not None, "and it learned something"


def test_a_sidecar_id_is_fetched_without_a_search(engine: Engine, tmp_path: Path) -> None:
    """AC-3 end to end. The sidecar names a TMDB id, so identification is skipped entirely."""
    root = tmp_path / "films"
    a_film(
        root,
        "Some Careless Filename",
        xml='<movie><uniqueid type="tmdb">11111</uniqueid></movie>',
    )
    transport = Counting(TMDB_REPLIES)
    scanned(engine, a_library(engine, root, "movies"), tmdb=transport)

    assert [one for one in transport.asked if one.startswith("/search/")] == []
    assert transport.asked == ["/movie/11111"]
    assert the_film(engine).name == "The Fixture"


# ----------------------------------------------------------------------------------------------
# AC-13: a rescan of an unchanged library makes zero requests
# ----------------------------------------------------------------------------------------------


def test_rescanning_an_unchanged_library_makes_zero_requests(
    engine: Engine, tmp_path: Path
) -> None:
    """**Because nothing asks, not because a cache answers.** 003's change detection means the
    second scan hands the refresh no items at all, so the providers are never reached."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title><year>1999</year></movie>")
    library = a_library(engine, root, "movies")

    first = Counting(TMDB_REPLIES)
    scanned(engine, library, tmdb=first)
    assert first.asked, "the first scan did ask"

    second = Counting(TMDB_REPLIES)
    scanned(engine, library, tmdb=second)
    assert second.asked == [], "a rescan of an unchanged library asked nothing"


def test_even_a_deep_rescan_re_asks_nothing_it_already_knows(
    engine: Engine, tmp_path: Path
) -> None:
    """`deep` hands every item to the refresh, so the providers *are* consulted - and the cache
    answers, which is the other case it exists for."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title><year>1999</year></movie>")
    library = a_library(engine, root, "movies")

    first = Counting(TMDB_REPLIES)
    scanned(engine, library, tmdb=first)

    second = Counting(TMDB_REPLIES)
    scanned(engine, library, tmdb=second, deep=True)
    assert second.asked == [], "the cache answered, so nothing reached the transport"


# ----------------------------------------------------------------------------------------------
# AC-8: every provider unreachable
# ----------------------------------------------------------------------------------------------


def test_with_every_provider_down_the_scan_completes_and_nothing_is_blanked(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-8. The item keeps every local value it had, and is marked for another go."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title><plot>Local.</plot></movie>")
    library = a_library(engine, root, "movies")

    report = scanned(engine, library, tmdb=Counting(down=True))
    film = the_film(engine)

    assert film.name == "The Fixture", "the local metadata survived"
    assert film.overview == "Local."
    assert film.refresh_pending is True, "and the item wants another go"
    assert report.refreshed.pending == (film.id,)  # type: ignore[attr-defined]
    assert report.refreshed.warnings  # type: ignore[attr-defined]


def test_the_next_scan_retries_a_pending_item_whose_files_did_not_change(
    engine: Engine, tmp_path: Path
) -> None:
    """The channel AC-8 leaves behind, and the one case the change-detection signal cannot see:
    the file is unchanged, so nothing would normally look at it again."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title></movie>")
    library = a_library(engine, root, "movies")

    scanned(engine, library, tmdb=Counting(down=True))
    assert the_film(engine).refresh_pending is True

    recovered = Counting(TMDB_REPLIES)
    scanned(engine, library, tmdb=recovered)
    assert recovered.asked, "the pending item was retried although its file had not moved"
    assert the_film(engine).refresh_pending is False, "and it is no longer pending"


def test_a_provider_that_is_down_does_not_stop_the_others(engine: Engine, tmp_path: Path) -> None:
    """One unreachable host must not cost a scan the providers that *are* reachable."""
    root = tmp_path / "music"
    path = root / "The Fixture Ensemble" / "The Fixture Album" / "01 - First.flac"
    path.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "audio" / "template.flac", path)
    library = a_library(engine, root, "music")

    report = scanned(
        engine,
        library,
        tmdb=Counting(down=True),
        musicbrainz=Counting(MB_REPLIES),
        contact="operator@example.invalid",
    )
    assert report.refreshed is not None  # type: ignore[attr-defined]
    albums = [row for row in items(engine) if row.type == ItemType.MUSIC_ALBUM]
    assert albums, "the music library still resolved"


# ----------------------------------------------------------------------------------------------
# AC-9: no credentials
# ----------------------------------------------------------------------------------------------


def test_without_credentials_the_scan_completes_and_names_what_sat_out(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-9. **Once per scan**, not once per item: an operator who has configured no key should be
    told that once, not four thousand times."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title></movie>")
    transport = Counting(TMDB_REPLIES)

    report = scanned(engine, a_library(engine, root, "movies"), tmdb=transport, api_key="")

    assert transport.asked == [], "a disabled provider asks nothing"
    disabled = report.refreshed.disabled  # type: ignore[attr-defined]
    assert len(disabled) == 1
    assert "tmdb_api_key" in disabled[0]
    assert the_film(engine).name == "The Fixture", "and everything local still worked"


def test_a_local_only_refresh_names_the_providers_it_did_not_consult(
    engine: Engine, tmp_path: Path
) -> None:
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title></movie>")
    transport = Counting(TMDB_REPLIES)

    report = scanned(
        engine,
        a_library(engine, root, "movies"),
        tmdb=transport,
        refresh_mode=RefreshMode.LOCAL_ONLY,
    )
    assert transport.asked == []
    assert any("local-only" in one for one in report.refreshed.disabled)  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------------------------
# AC-10 and AC-12
# ----------------------------------------------------------------------------------------------


def test_a_locked_field_survives_a_replace_refresh_against_a_provider(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-10 end to end, with something that would actually have overwritten it."""
    root = tmp_path / "films"
    a_film(
        root,
        "The Fixture",
        xml=(
            "<movie><title>The User's Title</title><year>1999</year>"
            "<lockedfields>Name</lockedfields></movie>"
        ),
    )
    library = a_library(engine, root, "movies")
    scanned(engine, library, tmdb=Counting(TMDB_REPLIES))
    assert the_film(engine).name == "The User's Title"

    scanned(
        engine,
        library,
        tmdb=Counting(TMDB_REPLIES),
        deep=True,
        refresh_mode=RefreshMode.REPLACE,
    )
    assert the_film(engine).name == "The User's Title", "TMDB's title was refused"


def test_an_ambiguous_match_leaves_the_item_unidentified_and_says_so(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-12 at integration. The item keeps its local metadata and the report counts it."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title><year>1999</year></movie>")
    replies = {**TMDB_REPLIES, "/search/movie": recorded(TMDB_RESPONSES, "search-movie-many")}

    report = scanned(engine, a_library(engine, root, "movies"), tmdb=Counting(replies))

    film = the_film(engine)
    assert film.name == "The Fixture", "nothing was guessed at"
    assert film.provider_ids == {}
    assert report.refreshed.unidentified == (film.id,)  # type: ignore[attr-defined]
    assert any("candidates" in one for one in report.refreshed.warnings)  # type: ignore[attr-defined]


def test_replace_re_queries_where_default_would_not(engine: Engine, tmp_path: Path) -> None:
    """The clause AC-1 rests on is lifted under `Replace`: re-querying is what that mode is for."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", sidecar="movie-full.nfo")
    library = a_library(engine, root, "movies")

    quiet = Counting(TMDB_REPLIES)
    scanned(engine, library, tmdb=quiet)
    assert quiet.asked == []

    loud = Counting(TMDB_REPLIES)
    scanned(engine, library, tmdb=loud, deep=True, refresh_mode=RefreshMode.REPLACE)
    assert loud.asked, "Replace asked even though nothing was missing"


# ----------------------------------------------------------------------------------------------
# AC-15, re-run with the remote code present and downloading
# ----------------------------------------------------------------------------------------------


def test_downloads_land_under_the_data_directory_and_the_library_is_untouched(
    engine: Engine, tmp_path: Path
) -> None:
    """**AC-15 with something that actually writes.** T10's version ran in a world where nothing
    could write anywhere; this one downloads a poster and then hashes the library tree."""
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title><year>1999</year></movie>")
    library = a_library(engine, root, "movies")
    artwork = tmp_path / "atrium" / "metadata" / "artwork"

    before = digest(root)
    scanned(engine, library, tmdb=Counting(TMDB_REPLIES), artwork_root=artwork)
    scanned(
        engine,
        library,
        tmdb=Counting(TMDB_REPLIES),
        artwork_root=artwork,
        deep=True,
        refresh_mode=RefreshMode.REPLACE,
    )

    assert digest(root) == before, "a refresh wrote inside a library root"
    assert not any(path.suffix in {".jpg", ".png"} for path in root.rglob("*")), (
        "no image was created in the library"
    )


def test_nothing_writes_into_a_library_when_a_provider_is_down(
    engine: Engine, tmp_path: Path
) -> None:
    root = tmp_path / "films"
    a_film(root, "The Fixture", xml="<movie><title>The Fixture</title></movie>")
    library = a_library(engine, root, "movies")

    before = digest(root)
    scanned(engine, library, tmdb=Counting(down=True))
    assert digest(root) == before


# ----------------------------------------------------------------------------------------------
# The opt-in live test plan section 8 promised and no task had delivered
# ----------------------------------------------------------------------------------------------


@pytest.mark.needs_reference
def test_the_live_providers_still_answer_in_the_shape_the_fixtures_claim(
    engine: Engine, tmp_path: Path
) -> None:
    """**Skipped by default, never gating CI.** The first user of the marker `tests/conftest.py`
    declared for exactly this, whose docstring said "Nothing does yet."

    The fixtures in `tests/fixtures/metadata/tmdb/` and `.../musicbrainz/` are synthetic: they pin
    the *parser*, not the *API*. This is the test that can tell the difference. It needs real
    credentials in the environment, and it asserts the **shape** rather than the values - a film's
    overview changes, its having one does not.

        ATRIUM_TMDB_API_KEY=... ATRIUM_MUSICBRAINZ_CONTACT=you@example.com \\
            uv run pytest -m needs_reference

    Principle VII forbids a test that depends on network availability, which is why this is opt-in
    rather than skipped-when-offline: a test that quietly skips is a test that stopped running.
    """
    import os

    from atrium.metadata.model import Field, Identity, Subject

    api_key = os.environ.get("ATRIUM_TMDB_API_KEY", "")
    contact = os.environ.get("ATRIUM_MUSICBRAINZ_CONTACT", "")
    if not api_key or not contact:
        pytest.skip("set ATRIUM_TMDB_API_KEY and ATRIUM_MUSICBRAINZ_CONTACT to run this")

    factory = session_factory(engine)
    with session_scope(factory) as db:
        tmdb = TmdbProvider(
            RemoteAccess(
                TMDB,
                session=db,
                base_url="https://api.themoviedb.org/3",
                rate=TMDB_RATE,
                credentials=ProviderCredentials(api_key=api_key),
            ),
            artwork_root=tmp_path / "artwork",
        )
        found = tmdb.identify(Subject(kind=ItemType.MOVIE, name="The Matrix", year=1999))
        assert isinstance(found, Identity), f"TMDB no longer identifies a famous film: {found}"
        values = tmdb.fetch(found, ItemType.MOVIE)
        for field in (Field.NAME, Field.OVERVIEW, Field.GENRES, Field.PEOPLE):
            assert field in values, f"TMDB stopped supplying {field}"

        brainz = MusicBrainzProvider(
            RemoteAccess(
                MUSICBRAINZ,
                session=db,
                base_url="https://musicbrainz.org/ws/2",
                rate=MUSICBRAINZ_RATE,
                credentials=ProviderCredentials(contact=contact),
                headers={"User-Agent": user_agent(contact)},
            )
        )
        album = brainz.identify(
            Subject(
                kind=ItemType.MUSIC_ALBUM,
                name="Kind of Blue",
                album_artist="Miles Davis",
            )
        )
        assert isinstance(album, Identity), f"MusicBrainz no longer identifies an album: {album}"
        record = brainz.fetch(album, ItemType.MUSIC_ALBUM)
        for field in (Field.NAME, Field.ALBUM_ARTISTS):
            assert field in record, f"MusicBrainz stopped supplying {field}"


def test_the_marker_is_registered_so_the_live_test_can_be_selected() -> None:
    """A marker pytest does not know about is a `-m` selector that silently matches nothing."""
    config = Path(__file__).resolve().parents[2] / "pyproject.toml"
    assert "needs_reference" in config.read_text(encoding="utf-8")
