# SPDX-License-Identifier: GPL-3.0-or-later
"""MusicBrainz, and the request budget that is the whole point of it.

**The assertion this suite exists for**: refreshing an album of fourteen tracks costs one search,
one release-group fetch and one artist lookup - *three* requests - and **never one per track**. At
one request per second, the difference between three and seventeen is the difference between a
first scan of a large library taking minutes and taking ninety.

The fixtures are synthetic and say so (`tests/fixtures/metadata/musicbrainz/README.md`).
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
from atrium.metadata.model import Ambiguous, Field, Identity, NoMatch, Subject
from atrium.metadata.musicbrainz import (
    ALBUM,
    ARTIST,
    NAME,
    RATE,
    RECORDING,
    MusicBrainzProvider,
    user_agent,
)
from atrium.metadata.remote import ProviderCredentials, RemoteAccess
from tests.conftest import data_dir

RESPONSES = Path(__file__).resolve().parents[1] / "fixtures" / "metadata" / "musicbrainz"
GROUP = "00000000-0000-4000-8000-000000000002"
ENSEMBLE = "00000000-0000-4000-8000-000000000003"


def recorded(name: str) -> object:
    return json.loads((RESPONSES / f"{name}.json").read_text(encoding="utf-8"))


class Transport(httpx.BaseTransport):
    def __init__(self, replies: dict[str, object] | None = None) -> None:
        self.replies = replies or {}
        self.asked: list[str] = []
        self.agents: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = str(request.url.path).removeprefix("/ws/2")
        self.asked.append(path)
        self.agents.append(request.headers.get("user-agent", ""))
        reply = self.replies.get(path)
        if reply is None:
            return httpx.Response(404, json=None)
        return httpx.Response(200, json=reply)

    @property
    def searches(self) -> list[str]:
        return [one for one in self.asked if one == "/release-group"]


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def provider(
    engine: Engine,
    transport: Transport,
    *,
    contact: str = "operator@example.invalid",
    clock: Clock | None = None,
) -> Iterator[MusicBrainzProvider]:
    ticker = clock or Clock()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        access = RemoteAccess(
            NAME,
            session=db,
            base_url="https://musicbrainz.org/ws/2",
            rate=RATE,
            credentials=ProviderCredentials(contact=contact),
            headers={"User-Agent": user_agent(contact)} if contact else {},
            transport=transport,
            clock=ticker,
            sleep=ticker.sleep,
        )
        yield MusicBrainzProvider(access)


REPLIES: dict[str, object] = {
    "/release-group": recorded("search-one"),
    f"/release-group/{GROUP}": recorded("release-group"),
    f"/artist/{ENSEMBLE}": recorded("artist"),
}


def an_album(**kwargs: object) -> Subject:
    return Subject(kind=ItemType.MUSIC_ALBUM, **kwargs)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------------------------
# The budget: the reason this module is album-shaped
# ----------------------------------------------------------------------------------------------


def test_a_fourteen_track_album_costs_three_requests(engine: Engine) -> None:
    """**Never one per track.** The tracks contribute nothing to the request count: a track's
    recording id comes from its own tags, and a lookup per track at one request per second is the
    ninety-minute first scan this whole design exists to avoid."""
    transport = Transport(REPLIES)
    tracks = [
        Subject(
            kind=ItemType.AUDIO, name=f"Track {index}", provider_ids={RECORDING: f"rec-{index}"}
        )
        for index in range(1, 15)
    ]
    for one in provider(engine, transport):
        identity = one.identify(
            an_album(name="The Fixture Album", album_artist="The Fixture Ensemble")
        )
        assert isinstance(identity, Identity)
        one.fetch(identity)
        one.fetch_artist(ENSEMBLE)
        recordings = [one.recording_of(track) for track in tracks]

    assert transport.asked == ["/release-group", f"/release-group/{GROUP}", f"/artist/{ENSEMBLE}"]
    assert len(transport.asked) == 3, "one search, one release group, one artist"
    assert recordings == [f"rec-{index}" for index in range(1, 15)], "and every track kept its id"


def test_a_track_is_never_searched_for(engine: Engine) -> None:
    transport = Transport(REPLIES)
    for one in provider(engine, transport):
        found = one.identify(Subject(kind=ItemType.AUDIO, name="A Track"))
    assert isinstance(found, NoMatch)
    assert transport.asked == [], "not even a request that would have failed"


def test_a_track_with_no_recording_tag_simply_has_none(engine: Engine) -> None:
    transport = Transport(REPLIES)
    for one in provider(engine, transport):
        assert one.recording_of(Subject(kind=ItemType.AUDIO, name="A Track")) is None
    assert transport.asked == []


def test_a_second_album_by_the_same_artist_costs_no_second_artist_request(
    engine: Engine,
) -> None:
    """An artist with forty albums is one request, because the cache answers the other
    thirty-nine - and an id never expires, so it is one for the life of the install."""
    transport = Transport(REPLIES)
    for one in provider(engine, transport):
        one.fetch_artist(ENSEMBLE)
        one.fetch_artist(ENSEMBLE)
    assert transport.asked == [f"/artist/{ENSEMBLE}"]


def test_the_one_per_second_bucket_is_engaged(engine: Engine) -> None:
    """Three requests at one per second cost two seconds of waiting. Proved against a clock the
    test owns rather than by waiting."""
    transport = Transport(REPLIES)
    clock = Clock()
    for one in provider(engine, transport, clock=clock):
        identity = one.identify(
            an_album(name="The Fixture Album", album_artist="The Fixture Ensemble")
        )
        assert isinstance(identity, Identity)
        one.fetch(identity)
        one.fetch_artist(ENSEMBLE)
    assert clock.slept == [pytest.approx(1.0), pytest.approx(1.0)]


# ----------------------------------------------------------------------------------------------
# The identifying User-Agent, which is a requirement rather than a courtesy
# ----------------------------------------------------------------------------------------------


def test_every_request_carries_an_identifying_user_agent(engine: Engine) -> None:
    transport = Transport(REPLIES)
    for one in provider(engine, transport):
        one.fetch_artist(ENSEMBLE)
    assert transport.agents == ["Atrium/1.0 ( operator@example.invalid )"]


def test_without_a_contact_the_provider_sits_out_with_a_reason(engine: Engine) -> None:
    """AC-9. MusicBrainz refuses traffic that does not identify itself, so sending anonymous
    requests would be a scan of rejections rather than a scan."""
    transport = Transport(REPLIES)
    for one in provider(engine, transport, contact=""):
        reason = one.enabled()
    assert isinstance(reason, str)
    assert "musicbrainz_contact" in reason
    assert transport.asked == []


def test_with_a_contact_it_is_enabled(engine: Engine) -> None:
    for one in provider(engine, Transport(REPLIES)):
        assert one.enabled() is True


# ----------------------------------------------------------------------------------------------
# The exactly-one rule, again
# ----------------------------------------------------------------------------------------------


def test_one_survivor_is_a_match(engine: Engine) -> None:
    for one in provider(engine, Transport(REPLIES)):
        found = one.identify(
            an_album(name="The Fixture Album", album_artist="The Fixture Ensemble")
        )
    assert found == Identity(provider=NAME, key=GROUP)


def test_a_title_that_matches_under_a_different_artist_does_not(engine: Engine) -> None:
    """The fixture offers one candidate with the right artist and the wrong title, and one with
    the right title and the wrong artist. Neither is this album."""
    transport = Transport({**REPLIES, "/release-group": recorded("search-none")})
    for one in provider(engine, transport):
        found = one.identify(
            an_album(name="The Fixture Album", album_artist="The Fixture Ensemble")
        )
    assert isinstance(found, NoMatch)


def test_two_survivors_leave_the_album_unidentified(engine: Engine) -> None:
    transport = Transport({**REPLIES, "/release-group": recorded("search-many")})
    for one in provider(engine, transport):
        found = one.identify(
            an_album(name="The Fixture Album", album_artist="The Fixture Ensemble")
        )
    assert isinstance(found, Ambiguous)
    assert len(found.candidates) == 2


def test_a_carried_id_makes_no_search(engine: Engine) -> None:
    transport = Transport(REPLIES)
    for one in provider(engine, transport):
        found = one.identify(an_album(name="Whatever", provider_ids={NAME: GROUP}))
    assert found == Identity(provider=NAME, key=GROUP)
    assert transport.asked == []


def test_an_album_id_from_a_tag_is_accepted_as_the_carried_id(engine: Engine) -> None:
    """`musicbrainz_albumid` is what every tagger writes, and it is the id a sidecar carries too."""
    transport = Transport(REPLIES)
    for one in provider(engine, transport):
        found = one.identify(an_album(name="Whatever", provider_ids={ALBUM: GROUP}))
    assert found == Identity(provider=NAME, key=GROUP)
    assert transport.asked == []


def test_the_query_quotes_a_title_so_a_colon_is_a_title(engine: Engine) -> None:
    """Lucene reads a bare colon as a field separator, so an unquoted `Album: Live` would search
    for a field called `Album`."""
    transport = Transport(REPLIES)
    for one in provider(engine, transport):
        one.identify(an_album(name='The Fixture: Live "1998"', album_artist="The Ensemble"))
    assert transport.searches == ["/release-group"]


# ----------------------------------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------------------------------


def fetched(engine: Engine) -> dict[Field, object]:
    for one in provider(engine, Transport(REPLIES)):
        return dict(one.fetch(Identity(NAME, GROUP)))
    raise AssertionError


def test_a_release_group_maps_onto_the_field_vocabulary(engine: Engine) -> None:
    from datetime import UTC, datetime

    values = fetched(engine)
    assert values[Field.NAME] == "The Fixture Album"
    assert values[Field.PREMIERE_DATE] == datetime(1998, 5, 4, tzinfo=UTC)
    assert values[Field.YEAR] == 1998
    assert values[Field.GENRES] == ["electronic", "ambient"]


def test_the_credits_become_artists_and_the_join_phrases_do_not(engine: Engine) -> None:
    """MusicBrainz gives a credit as parts with join phrases between them - `Artist A`, `" & "`,
    `Artist B`. Keeping the phrases would put ` & ` in a list of artists."""
    assert fetched(engine)[Field.ALBUM_ARTISTS] == ["The Fixture Ensemble", "A Guest"]


def test_the_provider_ids_carry_the_group_and_the_first_artist(engine: Engine) -> None:
    assert fetched(engine)[Field.PROVIDER_IDS] == {NAME: GROUP, ARTIST: ENSEMBLE}


def test_an_artist_lookup_maps_its_own_fields(engine: Engine) -> None:
    for one in provider(engine, Transport(REPLIES)):
        values = dict(one.fetch_artist(ENSEMBLE))
    assert values[Field.NAME] == "The Fixture Ensemble"
    assert values[Field.SORT_NAME] == "Fixture Ensemble, The"
    assert values[Field.OVERVIEW] == "the synthetic one"
    assert values[Field.PROVIDER_IDS] == {ARTIST: ENSEMBLE}


def test_a_partial_date_is_a_year_rather_than_a_guess(engine: Engine) -> None:
    """MusicBrainz dates are as precise as it knows: `1998`, `1998-05`, `1998-05-04`. Only the
    full form becomes a date; the others still supply the year."""
    from datetime import UTC, datetime

    transport = Transport(
        {
            **REPLIES,
            f"/release-group/{GROUP}": {"id": GROUP, "title": "x", "first-release-date": "1998"},
        }
    )
    for one in provider(engine, transport):
        values = dict(one.fetch(Identity(NAME, GROUP)))
    assert values[Field.YEAR] == 1998
    assert values[Field.PREMIERE_DATE] == datetime(1998, 1, 1, tzinfo=UTC)


# ----------------------------------------------------------------------------------------------
# No artwork, which is a stronger statement than a disabled one
# ----------------------------------------------------------------------------------------------


def test_the_module_has_no_artwork_code_path_at_all() -> None:
    """The spec scopes MusicBrainz to names, dates and relationships; music art comes from files
    and embedded covers. Asserted on the source, because "we do not call it" is a promise and
    "there is nothing to call" is a property."""
    import ast

    module = Path(__file__).resolve().parents[2] / "src" / "atrium" / "metadata" / "musicbrainz.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)} | {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    assert not names & {"get_bytes", "download", "ImageAssociation", "ImageKind", "describe_bytes"}
