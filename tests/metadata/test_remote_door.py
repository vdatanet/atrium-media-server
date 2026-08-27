# SPDX-License-Identifier: GPL-3.0-or-later
"""The one HTTP door, before either provider walks through it.

This is 004's second structural decision, and the whole point of it is the order: the limiter and
the cache are green **before** anything exists that could make a request. A provider written after
this cannot produce an unthrottled loop against somebody's API without first changing a test that
says it may not.

**Nothing here opens a socket**, and that is by construction rather than by mocking: `httpx` takes
a transport, a test hands in one that answers from a dictionary and counts what it was asked for,
and the suite's own network guard is watching the whole time.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine

from atrium.compat.dates import utc_now
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory, session_scope
from atrium.metadata.remote import (
    DEFAULT_TTL,
    ProviderCredentials,
    ProviderUnavailableError,
    RateLimitedError,
    RemoteAccess,
    ResponseCache,
    TokenBucket,
)
from tests.conftest import data_dir


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


class CountingTransport(httpx.BaseTransport):
    """Answers from a table and remembers every request.

    The counting half is what T12, T13 and T14 need: AC-3 is "zero search requests", AC-13 is
    "zero requests", and neither can be asserted against a transport that only answers.
    """

    def __init__(self, replies: dict[str, object] | None = None, status: int = 200) -> None:
        self.replies = replies or {}
        self.status = status
        self.asked: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        target = str(request.url.path)
        if request.url.query:
            target += "?" + request.url.query.decode()
        self.asked.append(target)
        if isinstance(self.replies.get(target), Exception):
            raise self.replies[target]  # type: ignore[misc]
        payload = self.replies.get(target, {"asked": target})
        return httpx.Response(self.status, json=payload)


class Clock:
    """A monotonic clock a test moves by hand, and a sleep that moves it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# ----------------------------------------------------------------------------------------------
# The bucket honours its rate, under a clock a test owns
# ----------------------------------------------------------------------------------------------


def test_a_burst_up_to_capacity_costs_nothing() -> None:
    """A scan is bursty: a hundred items resolve locally and ask nothing, then one asks three
    times. A bucket lets that through at the published rate; a sleep between calls would not."""
    clock = Clock()
    bucket = TokenBucket(rate=4.0, now=clock, sleep=clock.sleep)
    for _ in range(4):
        bucket.take()
    assert clock.slept == []


def test_the_fifth_request_waits_for_a_quarter_of_a_second() -> None:
    clock = Clock()
    bucket = TokenBucket(rate=4.0, now=clock, sleep=clock.sleep)
    for _ in range(5):
        bucket.take()
    assert clock.slept == [pytest.approx(0.25)]


def test_a_one_per_second_bucket_waits_a_second() -> None:
    """MusicBrainz's published etiquette, which is why the album is the unit of identification."""
    clock = Clock()
    bucket = TokenBucket(rate=1.0, now=clock, sleep=clock.sleep)
    bucket.take()
    bucket.take()
    assert clock.slept == [pytest.approx(1.0)]


def test_time_passing_refills_the_bucket() -> None:
    clock = Clock()
    bucket = TokenBucket(rate=4.0, now=clock, sleep=clock.sleep)
    for _ in range(4):
        bucket.take()
    clock.now += 1.0
    for _ in range(4):
        bucket.take()
    assert clock.slept == [], "a second of waiting bought four more requests"


def test_the_rate_holds_over_a_long_run() -> None:
    """The property that matters: twenty requests at four per second take about five seconds,
    however they are spaced."""
    clock = Clock()
    bucket = TokenBucket(rate=4.0, now=clock, sleep=clock.sleep)
    for _ in range(20):
        bucket.take()
    assert clock.now == pytest.approx(4.0, abs=0.3)


def test_a_429_halves_the_bucket_for_the_rest_of_the_scan() -> None:
    """The published rate was not the real one. Halved rather than reset, because a bucket that
    recovers immediately asks to be told again."""
    clock = Clock()
    bucket = TokenBucket(rate=4.0, now=clock, sleep=clock.sleep)
    bucket.halve()
    assert bucket.rate == pytest.approx(2.0)
    bucket.take()
    assert clock.slept, "a halved bucket starts empty"


def test_a_rate_of_zero_is_refused_rather_than_blocking_for_ever() -> None:
    with pytest.raises(ValueError, match="disable the provider"):
        TokenBucket(rate=0.0)


# ----------------------------------------------------------------------------------------------
# The cache: hit, miss, expired, bypassed
# ----------------------------------------------------------------------------------------------


def test_the_cache_table(engine: Engine) -> None:
    """Four cases, one table, because the fourth is the one a `Replace` refresh depends on."""
    factory = session_factory(engine)
    with session_scope(factory) as db:
        cache = ResponseCache(db)
        now = utc_now()

        assert cache.get("Tmdb", "movie/1") is None, "miss"

        cache.put("Tmdb", "movie/1", {"title": "First"}, now=now)
        hit = cache.get("Tmdb", "movie/1", now=now)
        assert hit is not None and hit.payload == {"title": "First"}, "hit"

        later = now + DEFAULT_TTL + timedelta(seconds=1)
        assert cache.get("Tmdb", "movie/1", now=later) is None, "expired reads as a miss"

        cache.put("Tmdb", "identity/1", {"id": 1}, ttl=None, now=now)
        forever = cache.get("Tmdb", "identity/1", now=later)
        assert forever is not None and forever.payload == {"id": 1}, "an id never expires"

        # **A payload of `None` is an answer, not a miss.** It is how a `404` is remembered, and
        # returning it bare made a cached "this provider does not know that id" look like nothing
        # at all - so the request was made again every time.
        cache.put("Tmdb", "movie/999", None, now=now)
        unknown = cache.get("Tmdb", "movie/999", now=now)
        assert unknown is not None and unknown.payload is None


def test_two_providers_do_not_share_a_key(engine: Engine) -> None:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        cache = ResponseCache(db)
        cache.put("Tmdb", "search", {"who": "tmdb"})
        cache.put("MusicBrainz", "search", {"who": "mb"})
        first = cache.get("Tmdb", "search")
        second = cache.get("MusicBrainz", "search")
        assert first is not None and first.payload == {"who": "tmdb"}
        assert second is not None and second.payload == {"who": "mb"}


def test_a_second_put_replaces_rather_than_duplicating(engine: Engine) -> None:
    factory = session_factory(engine)
    with session_scope(factory) as db:
        cache = ResponseCache(db)
        cache.put("Tmdb", "movie/1", {"v": 1})
        cache.put("Tmdb", "movie/1", {"v": 2})
        latest = cache.get("Tmdb", "movie/1")
        assert latest is not None and latest.payload == {"v": 2}
        assert cache.count("Tmdb") == 1


# ----------------------------------------------------------------------------------------------
# The door
# ----------------------------------------------------------------------------------------------


def test_a_cached_request_costs_no_request_and_no_token(engine: Engine) -> None:
    transport = CountingTransport({"/movie/1": {"title": "First"}})
    clock = Clock()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb",
            session=db,
            base_url="https://example.invalid",
            rate=4.0,
            transport=transport,
            clock=clock,
            sleep=clock.sleep,
        )
        first = door.get("/movie/1")
        second = door.get("/movie/1")

    assert first.payload == {"title": "First"}
    assert not first.cached
    assert second.cached
    assert transport.asked == ["/movie/1"], "the second ask never reached the transport"


def test_replace_bypasses_the_cache_and_refills_it(engine: Engine) -> None:
    """It re-fetches and **refills** rather than ignoring the entry, so the next default refresh
    benefits from what the deliberate one paid for."""
    transport = CountingTransport({"/movie/1": {"v": 1}})
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        door.get("/movie/1")
        transport.replies["/movie/1"] = {"v": 2}
        again = door.get("/movie/1", bypass_cache=True)
        assert again.payload == {"v": 2}
        assert door.get("/movie/1").cached, "and the entry was refilled"
    assert transport.asked == ["/movie/1", "/movie/1"]


def test_the_request_key_does_not_depend_on_parameter_order(engine: Engine) -> None:
    transport = CountingTransport()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        door.get("/search", params={"query": "The Fixture", "year": "1999"})
        second = door.get("/search", params={"year": "1999", "query": "The Fixture"})
    assert second.cached
    assert len(transport.asked) == 1


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_server_error_is_unavailable_rather_than_a_scan_failure(
    engine: Engine, status: int
) -> None:
    transport = CountingTransport(status=status)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        with pytest.raises(ProviderUnavailableError):
            door.get("/movie/1")


def test_a_429_raises_its_own_error_and_halves_the_bucket(engine: Engine) -> None:
    transport = CountingTransport(status=429)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        with pytest.raises(RateLimitedError):
            door.get("/movie/1")
        assert door.bucket.rate == pytest.approx(2.0)


def test_a_transport_error_is_unavailable(engine: Engine) -> None:
    """The provider is down, the mount is gone, DNS failed - all one answer to the caller: keep
    the local metadata and mark the item pending (AC-8)."""
    transport = CountingTransport({"/movie/1": httpx.ConnectError("nothing there")})
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        with pytest.raises(ProviderUnavailableError):
            door.get("/movie/1")


def test_a_404_is_an_answer_and_is_cached(engine: Engine) -> None:
    """This provider does not know that id. Asking again tomorrow gets the same answer and costs
    a request, so it is cached like any other."""
    transport = CountingTransport(status=404)
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        assert door.get("/movie/999").payload is None
        assert door.get("/movie/999").cached
    assert len(transport.asked) == 1


def test_a_reply_that_is_not_json_is_unavailable(engine: Engine) -> None:
    class Garbage(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<html>not json</html>")

    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=Garbage()
        )
        with pytest.raises(ProviderUnavailableError):
            door.get("/movie/1")


def test_headers_reach_the_request(engine: Engine) -> None:
    """MusicBrainz refuses traffic without an identifying `User-Agent`. Not decoration."""
    seen: list[str] = []

    class Watching(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("user-agent", ""))
            return httpx.Response(200, json={})

    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "MusicBrainz",
            session=db,
            base_url="https://example.invalid",
            rate=1.0,
            headers={"User-Agent": "Atrium/1.0 ( operator@example.invalid )"},
            transport=Watching(),
        )
        door.get("/release-group/1")
    assert seen == ["Atrium/1.0 ( operator@example.invalid )"]


def test_credentials_are_falsey_when_absent() -> None:
    assert not ProviderCredentials()
    assert ProviderCredentials(api_key="k")
    assert ProviderCredentials(contact="operator@example.invalid")


# ----------------------------------------------------------------------------------------------
# The property this whole ordering exists for
# ----------------------------------------------------------------------------------------------


def test_no_module_under_metadata_constructs_a_client_except_this_one() -> None:
    """**The reason T11 comes before T12 and T13.** "No test reaches the network" is a property of
    the code rather than a discipline only while this holds: a provider that built its own client
    would have to change this test to get one, which is a decision somebody makes on purpose.
    """
    import ast

    package = Path(__file__).resolve().parents[2] / "src" / "atrium" / "metadata"
    offenders = []
    for module in sorted(package.glob("*.py")):
        if module.name == "remote.py":
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
        }
        if {"httpx", "urllib", "requests", "http"} & imports:
            offenders.append(module.name)
    assert not offenders, (
        f"{offenders} import an HTTP library. Every request this feature makes goes through "
        f"metadata/remote.py, which is what makes the rate limit and the cache impossible to "
        f"route around."
    )


def test_the_suites_network_guard_is_still_watching(engine: Engine) -> None:
    """Exercised with the module imported and used: a transport that answered by opening a socket
    would fail here rather than silently working on a machine with internet."""
    transport = CountingTransport()
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        door.get("/anything")
    assert transport.asked == ["/anything"]


def test_the_payload_survives_a_round_trip_through_the_column(engine: Engine) -> None:
    """`provider_cache.payload` is JSON, and a provider's reply is arbitrarily nested."""
    nested = {"results": [{"id": 1, "genres": [{"name": "Drama"}]}], "page": 1}
    transport = CountingTransport({"/search": nested})
    factory = session_factory(engine)
    with session_scope(factory) as db:
        door = RemoteAccess(
            "Tmdb", session=db, base_url="https://example.invalid", rate=4.0, transport=transport
        )
        door.get("/search")
        again = door.get("/search")
    assert again.cached
    assert json.loads(json.dumps(again.payload)) == nested
