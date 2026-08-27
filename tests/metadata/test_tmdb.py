# SPDX-License-Identifier: GPL-3.0-or-later
"""TMDB, against synthetic responses and a counting transport.

**AC-3 and AC-12 live here.** A subject that already carries a TMDB id makes *zero* search
requests, and a search that leaves two plausible candidates leaves the item unidentified rather
than choosing - which is the whole of what "ambiguous matches are not guessed" means.

The fixtures are synthetic and say so (`tests/fixtures/metadata/tmdb/README.md`). They pin the
parser; plan section 8's opt-in live test at T14 is what would notice TMDB changing shape.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine

from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.domain.items import ItemType
from atrium.metadata.artwork import ImageKind, SourceKind
from atrium.metadata.model import Ambiguous, Field, Identity, NoMatch, PersonKind, Subject
from atrium.metadata.remote import ProviderCredentials, RemoteAccess
from atrium.metadata.tmdb import MAX_IMAGE_BYTES, NAME, RATE, TmdbProvider
from tests.conftest import data_dir

RESPONSES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata" / "tmdb"
ARTWORK = Path(__file__).resolve().parents[1] / "fixtures" / "metadata" / "artwork"

#: A real, tiny PNG so `describe_bytes` can measure a download rather than being told its size.
POSTER = (ARTWORK / "names-first" / "poster.jpg").read_bytes()


def recorded(name: str) -> object:
    return json.loads((RESPONSES / f"{name}.json").read_text(encoding="utf-8"))


class Transport(httpx.BaseTransport):
    """Answers JSON from the fixtures and bytes for anything under the image host, and remembers
    every path it was asked for - which is how AC-3 and AC-13 are asserted at all."""

    def __init__(self, replies: dict[str, object] | None = None) -> None:
        self.replies = replies or {}
        self.asked: list[str] = []
        self.image_bytes = POSTER

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # `base_url` ends in `/3`, and httpx keeps it: the request path is `/3/search/movie`. The
        # version prefix is the client's business rather than the fixtures', so it comes off here.
        path = str(request.url.path).removeprefix("/3")
        self.asked.append(path)
        if request.url.host and "image" in request.url.host:
            return httpx.Response(200, content=self.image_bytes)
        reply = self.replies.get(path)
        if reply is None:
            return httpx.Response(404, json=None)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply)

    @property
    def searches(self) -> list[str]:
        return [one for one in self.asked if one.startswith("/search/")]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


def provider(
    engine: Engine,
    tmp_path: Path,
    transport: Transport,
    *,
    api_key: str = "a-key",
    country: str = "US",
) -> Iterator[TmdbProvider]:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        access = RemoteAccess(
            NAME,
            session=db,
            base_url="https://api.themoviedb.org/3",
            rate=RATE,
            credentials=ProviderCredentials(api_key=api_key),
            transport=transport,
            sleep=lambda _: None,
        )
        yield TmdbProvider(access, artwork_root=tmp_path / "artwork", country=country)


def a_film(**kwargs: object) -> Subject:
    return Subject(kind=ItemType.MOVIE, **kwargs)  # type: ignore[arg-type]


DEFAULT_REPLIES: dict[str, object] = {
    "/search/movie": recorded("search-movie-one"),
    "/movie/11111": recorded("movie-11111"),
    "/tv/66666": recorded("tv-66666"),
}


# ----------------------------------------------------------------------------------------------
# AC-9: no key, no provider, and a reason
# ----------------------------------------------------------------------------------------------


def test_without_a_key_the_provider_says_why_it_is_disabled(engine: Engine, tmp_path: Path) -> None:
    """A string rather than a bare `False`: the scan report names what sat out, once per scan, so
    an operator is told rather than left wondering why nothing has a poster."""
    transport = Transport()
    for one in provider(engine, tmp_path, transport, api_key=""):
        reason = one.enabled()
    assert isinstance(reason, str)
    assert "tmdb_api_key" in reason
    assert transport.asked == [], "a disabled provider asks nothing"


def test_with_a_key_it_is_enabled(engine: Engine, tmp_path: Path) -> None:
    for one in provider(engine, tmp_path, Transport()):
        assert one.enabled() is True


# ----------------------------------------------------------------------------------------------
# AC-3: an identifier ends the argument
# ----------------------------------------------------------------------------------------------


def test_a_carried_id_makes_zero_search_requests(engine: Engine, tmp_path: Path) -> None:
    """AC-3, on the counting transport. Not "fewer requests" - **none**: there is nothing to ask,
    so nothing is asked, not even a cached search."""
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        found = one.identify(a_film(name="Some Careless Filename", provider_ids={NAME: "11111"}))
    assert found == Identity(provider=NAME, key="11111")
    assert transport.asked == [], "a carried id asks nothing at all"


def test_a_carried_id_wins_over_a_name_that_would_have_matched(
    engine: Engine, tmp_path: Path
) -> None:
    """The sidecar's id is the user's decision about what this film is, and no heuristic may
    second-guess it (spec section 3.2)."""
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        found = one.identify(a_film(name="The Fixture", year=1999, provider_ids={NAME: "999"}))
    assert found == Identity(provider=NAME, key="999")
    assert transport.searches == []


# ----------------------------------------------------------------------------------------------
# AC-12: one, none, many
# ----------------------------------------------------------------------------------------------


def test_exactly_one_survivor_is_a_match(engine: Engine, tmp_path: Path) -> None:
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        found = one.identify(a_film(name="The Fixture", year=1999))
    assert found == Identity(provider=NAME, key="11111")
    assert transport.searches == ["/search/movie"]


def test_no_survivor_is_unidentified_rather_than_the_closest(
    engine: Engine, tmp_path: Path
) -> None:
    """Two plausible-looking candidates come back and **neither title matches**. A "top result"
    rule would take the first; this leaves the item alone."""
    transport = Transport({**DEFAULT_REPLIES, "/search/movie": recorded("search-movie-none")})
    for one in provider(engine, tmp_path, transport):
        found = one.identify(a_film(name="The Fixture", year=1999))
    assert isinstance(found, NoMatch)
    assert "none of which matched" in found.reason


def test_two_survivors_are_ambiguous_and_therefore_unidentified(
    engine: Engine, tmp_path: Path
) -> None:
    """AC-12. A wrong match is worse than a missing one: it is confidently wrong, hard to notice,
    and correctable only through a flow v1 does not have."""
    transport = Transport({**DEFAULT_REPLIES, "/search/movie": recorded("search-movie-many")})
    for one in provider(engine, tmp_path, transport):
        found = one.identify(a_film(name="The Fixture", year=1999))
    assert isinstance(found, Ambiguous)
    assert set(found.candidates) == {"44444", "55555"}


def test_an_empty_result_set_is_no_match(engine: Engine, tmp_path: Path) -> None:
    transport = Transport({**DEFAULT_REPLIES, "/search/movie": {"results": []}})
    for one in provider(engine, tmp_path, transport):
        assert isinstance(one.identify(a_film(name="Nothing At All", year=1999)), NoMatch)


def test_an_item_with_no_name_is_not_searched_for(engine: Engine, tmp_path: Path) -> None:
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        assert isinstance(one.identify(a_film(name=None)), NoMatch)
    assert transport.asked == []


def test_a_type_tmdb_does_not_know_is_not_searched_for(engine: Engine, tmp_path: Path) -> None:
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        found = one.identify(Subject(kind=ItemType.MUSIC_ALBUM, name="The Album"))
    assert isinstance(found, NoMatch)
    assert transport.asked == []


# ----------------------------------------------------------------------------------------------
# The match rule, which is the whole of the identification
# ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "year", "matches"),
    [
        ("The Fixture", 1999, True),
        # Both sides normalised: case, diacritics, punctuation, whitespace.
        ("the  fixture", 1999, True),
        ("THE FIXTURE!", 1999, True),
        # The original title counts too - a film released abroad under another name.
        ("El Atrezzo", 1999, True),
        # A year off by one is the same film: a release date and a filename disagree constantly
        # across territories.
        ("The Fixture", 2000, True),
        ("The Fixture", 1998, True),
        # Two years off is a different film.
        ("The Fixture", 2001, False),
        # A title that merely starts the same is not the same film.
        ("The Fixture Reloaded", 1999, False),
        ("Fixture", 1999, False),
    ],
)
def test_the_match_rule(
    engine: Engine, tmp_path: Path, name: str, year: int, matches: bool
) -> None:
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        found = one.identify(a_film(name=name, year=year))
    assert isinstance(found, Identity) is matches


def test_a_subject_with_no_year_matches_on_title_alone(engine: Engine, tmp_path: Path) -> None:
    """Refusing here would leave every undated file unidentified, and the exactly-one rule still
    guards the case where two candidates share a title."""
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        assert isinstance(one.identify(a_film(name="The Fixture")), Identity)


# ----------------------------------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------------------------------


def fetched(engine: Engine, tmp_path: Path, **kwargs: object) -> dict[Field, object]:
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport, **kwargs):  # type: ignore[arg-type]
        return dict(one.fetch(Identity(NAME, "11111"), ItemType.MOVIE))
    raise AssertionError


def test_a_fetched_film_maps_onto_the_field_vocabulary(engine: Engine, tmp_path: Path) -> None:
    from datetime import UTC, datetime

    values = fetched(engine, tmp_path)
    assert values[Field.NAME] == "The Fixture"
    assert values[Field.ORIGINAL_TITLE] == "El Atrezzo"
    assert values[Field.TAGLINE] == "Every field, once."
    assert values[Field.PREMIERE_DATE] == datetime(1999, 4, 23, tzinfo=UTC)
    assert values[Field.YEAR] == 1999
    assert values[Field.COMMUNITY_RATING] == pytest.approx(7.4)
    assert values[Field.GENRES] == ["Drama", "Science Fiction"]
    assert values[Field.STUDIOS] == ["Fixture Pictures", "Second Studio"]


def test_a_runtime_arrives_in_ticks(engine: Engine, tmp_path: Path) -> None:
    from atrium.compat.ticks import to_seconds

    assert to_seconds(int(fetched(engine, tmp_path)[Field.RUNTIME])) == pytest.approx(97 * 60)


def test_the_cast_arrives_in_billing_order_whatever_order_the_payload_used(
    engine: Engine, tmp_path: Path
) -> None:
    """The fixture lists them 1, 0, 2 on purpose: `order` is the billing, not the array index."""
    people = fetched(engine, tmp_path)[Field.PEOPLE]
    assert isinstance(people, list)
    actors = [one for one in people if one.kind is PersonKind.ACTOR]
    assert [one.name for one in actors] == ["First Billed", "Second Billed", "Third Billed"]
    assert actors[0].role == "The Lead"


def test_only_the_crew_jobs_the_vocabulary_has_a_kind_for_arrive(
    engine: Engine, tmp_path: Path
) -> None:
    """TMDB's crew runs to hundreds of entries per film. An item carrying every gaffer is an item
    no client renders usefully."""
    people = fetched(engine, tmp_path)[Field.PEOPLE]
    assert isinstance(people, list)
    crew = {one.kind: one.name for one in people if one.kind is not PersonKind.ACTOR}
    assert crew == {
        PersonKind.DIRECTOR: "A Director",
        PersonKind.WRITER: "A Writer",
        PersonKind.COMPOSER: "A Composer",
    }
    assert "A Gaffer" not in [one.name for one in people]


def test_the_official_rating_is_the_configured_countrys_and_no_other(
    engine: Engine, tmp_path: Path
) -> None:
    """A film carries a rating in forty territories and they do not mean the same thing. Picking
    one the operator did not choose puts `15` on a film an American client expects to see as
    `PG-13`."""
    assert fetched(engine, tmp_path, country="US")[Field.OFFICIAL_RATING] == "PG-13"
    assert fetched(engine, tmp_path, country="GB")[Field.OFFICIAL_RATING] == "15"
    assert Field.OFFICIAL_RATING not in fetched(engine, tmp_path, country="FR")


def test_an_empty_certification_is_skipped_rather_than_stored(
    engine: Engine, tmp_path: Path
) -> None:
    """The US entry lists an empty certification before the real one; taking the first would store
    an empty string, which spec section 3.1 says is not a value."""
    assert fetched(engine, tmp_path, country="US")[Field.OFFICIAL_RATING] == "PG-13"


def test_the_provider_ids_carry_the_id_that_was_fetched_and_the_imdb_one(
    engine: Engine, tmp_path: Path
) -> None:
    assert fetched(engine, tmp_path)[Field.PROVIDER_IDS] == {
        "Tmdb": "11111",
        "Imdb": "tt2222222",
    }


def test_a_series_fetches_from_its_own_endpoint(engine: Engine, tmp_path: Path) -> None:
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        values = dict(one.fetch(Identity(NAME, "66666"), ItemType.SERIES))
    assert values[Field.NAME] == "The Fixture Series"
    assert transport.asked == ["/tv/66666"]


def test_fetching_twice_asks_once(engine: Engine, tmp_path: Path) -> None:
    """An identity looked up by id never expires: an id does not change meaning."""
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        one.fetch(Identity(NAME, "11111"), ItemType.MOVIE)
        one.fetch(Identity(NAME, "11111"), ItemType.MOVIE)
    assert transport.asked == ["/movie/11111"]


# ----------------------------------------------------------------------------------------------
# Artwork
# ----------------------------------------------------------------------------------------------


def test_the_offered_images_are_a_poster_three_backdrops_and_a_logo(
    engine: Engine, tmp_path: Path
) -> None:
    """The fixture offers four backdrops; three is what a client cycles through, and a film with
    two hundred is not two hundred downloads."""
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        offered = one.images_for(Identity(NAME, "11111"), ItemType.MOVIE)
    kinds = [image.kind for image in offered]
    assert kinds.count(ImageKind.BACKDROP) == 3
    assert kinds.count(ImageKind.PRIMARY) == 1
    assert kinds.count(ImageKind.LOGO) == 1


def test_downloaded_artwork_lands_under_the_data_directory(engine: Engine, tmp_path: Path) -> None:
    """**Never inside a library root** - AC-15 is structural here, not a rule this module
    remembers. The stored path is relative to the data directory, which is what `remote` means."""
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        offered = one.images_for(Identity(NAME, "11111"), ItemType.MOVIE)
        associations, warnings = one.download("f" * 32, offered)

    assert not warnings
    assert all(image.source_kind is SourceKind.REMOTE for image in associations)
    assert all(
        image.relative_path is not None
        and image.relative_path.startswith(f"metadata/artwork/{'f' * 32}/")
        for image in associations
    )
    written = sorted((tmp_path / "artwork" / ("f" * 32)).iterdir())
    assert written, "the bytes reached the data directory"


def test_no_more_than_five_files_are_downloaded_for_one_item(
    engine: Engine, tmp_path: Path
) -> None:
    from atrium.metadata.tmdb import MAX_IMAGES_PER_ITEM, RemoteImage

    transport = Transport(DEFAULT_REPLIES)
    many = tuple(RemoteImage(ImageKind.BACKDROP, f"/b-{index}.jpg") for index in range(12))
    for one in provider(engine, tmp_path, transport):
        associations, _ = one.download("f" * 32, many)
    assert len(transport.asked) <= MAX_IMAGES_PER_ITEM
    assert len(associations) <= MAX_IMAGES_PER_ITEM


def test_an_image_over_the_cap_is_a_warning_rather_than_a_disc(
    engine: Engine, tmp_path: Path
) -> None:
    from atrium.metadata.tmdb import RemoteImage

    transport = Transport(DEFAULT_REPLIES)
    transport.image_bytes = b"\x89PNG\r\n\x1a\n" + b"\0" * (MAX_IMAGE_BYTES + 1)
    for one in provider(engine, tmp_path, transport):
        associations, warnings = one.download("f" * 32, (RemoteImage(ImageKind.PRIMARY, "/p.jpg"),))
    assert associations == ()
    assert any("cap" in warning for warning in warnings)


def test_an_image_already_present_by_tag_is_not_downloaded_again(
    engine: Engine, tmp_path: Path
) -> None:
    """A re-refresh of an unchanged film downloads nothing at all, which is the bound that keeps
    the data directory from growing on every scan."""
    from atrium.metadata.artwork import tag_of
    from atrium.metadata.tmdb import RemoteImage

    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        associations, _ = one.download(
            "f" * 32,
            (RemoteImage(ImageKind.PRIMARY, "/p.jpg"),),
            already={tag_of(POSTER)},
        )
    assert associations == (), "already present, so nothing was associated"


def test_something_that_is_not_an_image_is_a_warning(engine: Engine, tmp_path: Path) -> None:
    from atrium.metadata.tmdb import RemoteImage

    transport = Transport(DEFAULT_REPLIES)
    transport.image_bytes = b"<html>an error page</html>"
    for one in provider(engine, tmp_path, transport):
        associations, warnings = one.download("f" * 32, (RemoteImage(ImageKind.PRIMARY, "/p.jpg"),))
    assert associations == ()
    assert any("not an image" in warning for warning in warnings)


def test_nothing_offered_downloads_nothing(engine: Engine, tmp_path: Path) -> None:
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        associations, warnings = one.download("f" * 32, ())
    assert associations == () and warnings == ()
    assert not (tmp_path / "artwork").exists(), "no directory is created for nothing"


# ----------------------------------------------------------------------------------------------
# Failure
# ----------------------------------------------------------------------------------------------


def test_a_provider_that_is_down_raises_rather_than_returning_nonsense(
    engine: Engine, tmp_path: Path
) -> None:
    """The caller keeps the item's local metadata and marks it pending (AC-8). Nothing is ever
    blanked because a network call failed."""
    from atrium.metadata.remote import ProviderUnavailableError

    transport = Transport({"/search/movie": httpx.ConnectError("nothing there")})
    for one in provider(engine, tmp_path, transport):
        with pytest.raises(ProviderUnavailableError):
            one.identify(a_film(name="The Fixture", year=1999))


def test_an_id_tmdb_does_not_know_yields_no_values_rather_than_a_failure(
    engine: Engine, tmp_path: Path
) -> None:
    """A `404` is an answer: this provider does not know that id. The item keeps what it has, and
    plan section 7 is explicit that there is **no fallback search** - the id is the user's."""
    transport = Transport(DEFAULT_REPLIES)
    for one in provider(engine, tmp_path, transport):
        assert dict(one.fetch(Identity(NAME, "does-not-exist"), ItemType.MOVIE)) == {}
    assert transport.searches == [], "no fallback search"
