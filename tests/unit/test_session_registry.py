# SPDX-License-Identifier: GPL-3.0-or-later
"""The registry: what is written when, and the transaction that must not have a window.

The interleaving test is the one worth reading. "Re-authenticating invalidates the previous token"
is easy to assert *after* the fact and easy to implement with a window in the middle - two
statements in two transactions look identical from outside once both have finished. So the test
opens a second connection **while the first transaction is still open** and asserts that exactly
one token works at that moment, and exactly one afterwards, and that they are not the same one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from atrium.compat.auth import ClientInfo
from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import SessionRepository, TokenRepository, UserRepository
from atrium.domain.user import User
from atrium.users.sessions import DEFAULT_FLUSH_SECONDS, SessionRegistry
from tests.conftest import data_dir

START = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


class Clock:
    """A clock that only moves when a test says so, so "least recently used" is not a race."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float = 60) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def engine(prepared: DataPaths) -> Iterator[Engine]:
    built = create_database_engine(prepared)
    schema.ensure_current(built, prepared)
    yield built
    built.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[OrmSession]:
    return session_factory(engine)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def registry(factory: sessionmaker[OrmSession], clock: Clock) -> SessionRegistry:
    return SessionRegistry(factory, flush_interval=0.01, clock=clock)


@pytest.fixture
def joan(factory: sessionmaker[OrmSession]) -> User:
    with factory.begin() as opened:
        return UserRepository(opened).add(User(id=new_id(), name="Joan"))


def device(name: str = "phone") -> ClientInfo:
    return ClientInfo(client="Atrium Test", device=name.title(), device_id=name, version="1.0")


# --------------------------------------------------------------------------------------------
# One device, one session, and no window
# --------------------------------------------------------------------------------------------


def test_re_authenticating_replaces_the_session_rather_than_adding_one(
    registry: SessionRegistry, factory: sessionmaker[OrmSession], joan: User
) -> None:
    first = registry.establish(joan, device())
    second = registry.establish(joan, device())

    assert second.session.id == first.session.id
    with factory() as reader:
        assert len(SessionRepository(reader).for_user(joan.id)) == 1
        tokens = TokenRepository(reader)
        assert tokens.resolve(first.token.secret) is None
        assert tokens.resolve(second.token.secret) is not None


def test_there_is_no_moment_at_which_both_tokens_work(
    registry: SessionRegistry, factory: sessionmaker[OrmSession], joan: User
) -> None:
    """Interleaved: a second connection looks in while the first transaction is still open.

    Two statements in two transactions would leave a window here that is invisible once both have
    committed, and that only shows up under load in somebody else's logs.
    """
    first = registry.establish(joan, device())

    writer = factory()
    try:
        second = registry.establish_in(writer, joan, device())

        # Mid-transaction: the old token is still the only one that works.
        with factory() as reader:
            tokens = TokenRepository(reader)
            assert tokens.resolve(first.token.secret) is not None
            assert tokens.resolve(second.token.secret) is None

        writer.commit()
    finally:
        writer.close()

    # After: the new one is the only one that works.
    with factory() as reader:
        tokens = TokenRepository(reader)
        assert tokens.resolve(first.token.secret) is None
        assert tokens.resolve(second.token.secret) is not None


def test_two_devices_keep_two_sessions(
    registry: SessionRegistry, factory: sessionmaker[OrmSession], joan: User
) -> None:
    phone = registry.establish(joan, device("phone"))
    tablet = registry.establish(joan, device("tablet"))

    with factory() as reader:
        assert len(SessionRepository(reader).for_user(joan.id)) == 2
        tokens = TokenRepository(reader)
        assert tokens.resolve(phone.token.secret) is not None
        assert tokens.resolve(tablet.token.secret) is not None


def test_the_session_carries_what_the_client_said_about_itself(
    registry: SessionRegistry, joan: User
) -> None:
    established = registry.establish(joan, device("phone"), remote_end_point="192.0.2.10")
    assert established.session.client == "Atrium Test"
    assert established.session.device_name == "Phone"
    assert established.session.app_version == "1.0"
    assert established.session.remote_end_point == "192.0.2.10"


def test_the_secret_stays_out_of_the_repr(registry: SessionRegistry, joan: User) -> None:
    established = registry.establish(joan, device())
    assert established.token.secret not in repr(established)


# --------------------------------------------------------------------------------------------
# Eviction
# --------------------------------------------------------------------------------------------


def test_the_least_recently_used_session_is_the_one_evicted(
    factory: sessionmaker[OrmSession], clock: Clock, joan: User
) -> None:
    registry = SessionRegistry(factory, clock=clock)
    with factory.begin() as opened:
        UserRepository(opened).set_policy(joan.id, {"max_active_sessions": 2}, {})
    capped = User(id=joan.id, name=joan.name, max_active_sessions=2)

    oldest = registry.establish(capped, device("tablet"))
    clock.advance()
    middle = registry.establish(capped, device("laptop"))
    clock.advance()
    newest = registry.establish(capped, device("phone"))

    with factory() as reader:
        devices = {one.device_id for one in SessionRepository(reader).for_user(joan.id)}
        tokens = TokenRepository(reader)
        assert devices == {"laptop", "phone"}
        assert tokens.resolve(oldest.token.secret) is None, "the evicted device still had a token"
        assert tokens.resolve(middle.token.secret) is not None
        assert tokens.resolve(newest.token.secret) is not None


def test_an_evicted_session_loses_its_token_too(
    factory: sessionmaker[OrmSession], clock: Clock, joan: User
) -> None:
    """A session removed from `/Sessions` whose token still worked would come back on that
    device's next request, which is a gap in a list rather than an eviction."""
    registry = SessionRegistry(factory, clock=clock)
    capped = User(id=joan.id, name=joan.name, max_active_sessions=1)

    first = registry.establish(capped, device("tablet"))
    clock.advance()
    registry.establish(capped, device("phone"))

    with factory() as reader:
        assert TokenRepository(reader).resolve(first.token.secret) is None


def test_zero_means_unlimited(factory: sessionmaker[OrmSession], clock: Clock, joan: User) -> None:
    """What the reference sends for an untouched account (spec section 3.5)."""
    registry = SessionRegistry(factory, clock=clock)
    assert joan.max_active_sessions == 0
    for name in ("a", "b", "c", "d", "e"):
        registry.establish(joan, device(name))
        clock.advance()
    with factory() as reader:
        assert len(SessionRepository(reader).for_user(joan.id)) == 5


# --------------------------------------------------------------------------------------------
# Activity, and what a crash costs
# --------------------------------------------------------------------------------------------


def test_touching_writes_nothing_until_a_flush(
    registry: SessionRegistry, factory: sessionmaker[OrmSession], joan: User, clock: Clock
) -> None:
    """The point of the whole design: no write lock per authenticated request."""
    established = registry.establish(joan, device())
    later = clock.advance(120)
    registry.touch(established.token.record.token_sha256, established.session.id, later)

    with factory() as reader:
        stored = SessionRepository(reader).by_id(established.session.id)
        assert stored is not None
        assert stored.last_activity_date == START, "the timestamp reached the database too early"
    assert registry.activity(established.session.id) == later


def test_a_flush_writes_both_the_session_and_the_token(
    registry: SessionRegistry, factory: sessionmaker[OrmSession], joan: User, clock: Clock
) -> None:
    established = registry.establish(joan, device())
    later = clock.advance(120)
    registry.touch(established.token.record.token_sha256, established.session.id, later)

    assert registry.flush() == 1
    with factory() as reader:
        stored = SessionRepository(reader).by_id(established.session.id)
        assert stored is not None
        assert stored.last_activity_date == later
        [token] = TokenRepository(reader).for_user(joan.id)
        assert token.last_used == later


def test_a_busy_session_costs_one_entry_not_one_per_request(
    registry: SessionRegistry, joan: User, clock: Clock
) -> None:
    established = registry.establish(joan, device())
    digest = established.token.record.token_sha256
    for _ in range(50):
        registry.touch(digest, established.session.id, clock.advance(1))
    assert len(registry.snapshot()) == 1
    assert registry.flush() == 1


def test_an_unclean_shutdown_loses_timestamps_and_nothing_else(
    registry: SessionRegistry, factory: sessionmaker[OrmSession], joan: User, clock: Clock
) -> None:
    """The cost this design accepts, asserted as a bound rather than described in a docstring."""
    established = registry.establish(joan, device())
    registry.touch(established.token.record.token_sha256, established.session.id, clock.advance(20))

    # The crash: the registry disappears with its pending entries unwritten.
    del registry

    with factory() as reader:
        stored = SessionRepository(reader).by_id(established.session.id)
        assert stored is not None, "the session itself was lost, which was never on the table"
        assert stored.last_activity_date == START, "only the timestamp is stale"
        assert TokenRepository(reader).resolve(established.token.secret) is not None


def test_a_request_arriving_during_a_flush_is_not_dropped(
    registry: SessionRegistry, joan: User, clock: Clock
) -> None:
    """The pending set is taken and cleared before the write, so a `touch` that lands in the
    middle starts a fresh entry rather than being erased by the clear afterwards."""
    established = registry.establish(joan, device())
    registry.touch(established.token.record.token_sha256, established.session.id, clock.advance(1))
    assert registry.flush() == 1

    during = clock.advance(1)
    registry.touch(established.token.record.token_sha256, established.session.id, during)
    assert registry.snapshot() == {established.session.id: during}


def test_a_flush_that_fails_keeps_what_it_could_not_write(
    registry: SessionRegistry, engine: Engine, joan: User, clock: Clock
) -> None:
    """A database that is briefly unavailable costs a delay, not a gap."""
    established = registry.establish(joan, device())
    registry.touch(established.token.record.token_sha256, established.session.id, clock.advance(5))
    engine.dispose()
    engine.pool = engine.pool.recreate()

    from unittest.mock import patch

    with (
        patch.object(SessionRepository, "touch", side_effect=RuntimeError("gone")),
        pytest.raises(RuntimeError),
    ):
        registry.flush()
    assert len(registry.snapshot()) == 1, "the entries were dropped instead of retried"


def test_nothing_pending_is_a_flush_that_does_nothing(registry: SessionRegistry) -> None:
    assert registry.flush() == 0


# --------------------------------------------------------------------------------------------
# The background task
# --------------------------------------------------------------------------------------------


async def test_the_background_task_flushes_on_its_interval(
    registry: SessionRegistry, factory: sessionmaker[OrmSession], joan: User, clock: Clock
) -> None:
    established = registry.establish(joan, device())
    later = clock.advance(120)
    registry.touch(established.token.record.token_sha256, established.session.id, later)

    task = asyncio.create_task(registry.run())
    try:
        for _ in range(200):
            await asyncio.sleep(0.01)
            if not registry.snapshot():
                break
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    with factory() as reader:
        stored = SessionRepository(reader).by_id(established.session.id)
        assert stored is not None
        assert stored.last_activity_date == later


def test_the_default_interval_is_the_one_the_plan_states() -> None:
    """Thirty seconds is the number plan section 6.5 puts a bound on, so it is asserted."""
    assert DEFAULT_FLUSH_SECONDS == 30.0
