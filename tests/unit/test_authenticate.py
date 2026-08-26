# SPDX-License-Identifier: GPL-3.0-or-later
"""The single entry point that verifies a password.

The timing guarantee is asserted by **counting KDF invocations**, not by measuring time. A count is
exact and fails for the right reason; a millisecond assertion fails on a loaded runner and teaches
everyone to ignore it (plan section 8.1). The separate timing test in tests/security is a ratio,
and it is a different claim: this one says the work happens, that one says it takes the same order
of time.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from atrium.compat.auth import ClientInfo
from atrium.compat.errors import (
    AccountUnavailableError,
    InvalidCredentialsError,
    account_unavailable_handler,
    client_authorization_handler,
    invalid_credentials_handler,
)
from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.config.settings import AuthenticationSettings
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import SessionRepository, TokenRepository, UserRepository
from atrium.domain.user import User
from atrium.users.passwords import PasswordPolicy, Passwords, describe
from atrium.users.service import Authenticator
from atrium.users.sessions import SessionRegistry
from tests.conftest import data_dir

PASSWORD = "correct horse battery staple"
CHEAP = PasswordPolicy(memory_cost=8, time_cost=1, parallelism=1)
COSTLIER = PasswordPolicy(memory_cost=16, time_cost=2, parallelism=1)


class CountingPasswords(Passwords):
    """Every KDF verification goes through `verify`, including the dummy one, so one counter does.

    `hash` is counted separately: it runs the KDF too, and the rehash-on-login rule is the only
    thing that calls it during an authentication.
    """

    def __init__(self, policy: PasswordPolicy = CHEAP) -> None:
        super().__init__(policy)
        self.verify_calls = 0
        self.hash_calls = 0

    def verify(self, stored: str, password: str) -> bool:
        self.verify_calls += 1
        return super().verify(stored, password)

    def hash(self, password: str) -> str:
        self.hash_calls += 1
        return super().hash(password)


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
def passwords() -> CountingPasswords:
    return CountingPasswords()


@pytest.fixture
def authenticator(factory: sessionmaker[OrmSession], passwords: CountingPasswords) -> Authenticator:
    return Authenticator(factory, passwords, SessionRegistry(factory))


def add_user(factory: sessionmaker[OrmSession], passwords: Passwords, **overrides: object) -> User:
    fields: dict[str, object] = {
        "id": new_id(),
        "name": "Joan",
        "password_hash": passwords.hash(PASSWORD),
    }
    fields.update(overrides)
    with factory.begin() as opened:
        return UserRepository(opened).add(User(**fields))  # type: ignore[arg-type]


@pytest.fixture
def joan(factory: sessionmaker[OrmSession], passwords: CountingPasswords) -> User:
    user = add_user(factory, passwords)
    passwords.hash_calls = 0
    return user


def phone() -> ClientInfo:
    return ClientInfo(client="Atrium Test", device="Phone", device_id="phone-1", version="1.0")


# --------------------------------------------------------------------------------------------
# Success
# --------------------------------------------------------------------------------------------


def test_correct_credentials_succeed_and_create_a_session(
    authenticator: Authenticator, factory: sessionmaker[OrmSession], joan: User
) -> None:
    result = authenticator.authenticate("Joan", PASSWORD, phone())

    assert result.user.id == joan.id
    assert result.session.device_id == "phone-1"
    assert len(result.token.secret) == 32
    with factory() as reader:
        assert TokenRepository(reader).resolve(result.token.secret) is not None
        assert len(SessionRepository(reader).for_user(joan.id)) == 1


def test_the_username_matches_in_any_case(authenticator: Authenticator, joan: User) -> None:
    assert authenticator.authenticate("JOAN", PASSWORD, phone()).user.id == joan.id


def test_a_success_records_the_login(
    authenticator: Authenticator, factory: sessionmaker[OrmSession], joan: User
) -> None:
    before = datetime.now(UTC)
    authenticator.authenticate("Joan", PASSWORD, phone())
    with factory() as reader:
        stored = UserRepository(reader).by_id(joan.id)
    assert stored is not None
    assert stored.last_login_date is not None
    assert stored.last_login_date >= before


def test_re_authenticating_from_one_device_replaces_the_session(
    authenticator: Authenticator, factory: sessionmaker[OrmSession], joan: User
) -> None:
    """AC-5 at this layer. T11 asserts the same thing where a client can see it."""
    first = authenticator.authenticate("Joan", PASSWORD, phone())
    second = authenticator.authenticate("Joan", PASSWORD, phone())

    assert second.session.id == first.session.id
    with factory() as reader:
        tokens = TokenRepository(reader)
        assert tokens.resolve(first.token.secret) is None
        assert tokens.resolve(second.token.secret) is not None


def test_an_account_with_no_password_opens_with_nothing(
    factory: sessionmaker[OrmSession], authenticator: Authenticator, passwords: CountingPasswords
) -> None:
    """Not the same as an empty password: it is opened by sending nothing."""
    add_user(factory, passwords, name="Ghost", password_hash=None)
    assert authenticator.authenticate("Ghost", "", phone()).user.name == "Ghost"


def test_an_account_with_no_password_still_refuses_one(
    factory: sessionmaker[OrmSession], authenticator: Authenticator, passwords: CountingPasswords
) -> None:
    add_user(factory, passwords, name="Ghost", password_hash=None)
    with pytest.raises(InvalidCredentialsError):
        authenticator.authenticate("Ghost", "something", phone())


# --------------------------------------------------------------------------------------------
# The four failures
# --------------------------------------------------------------------------------------------


def test_an_unknown_username_is_401(authenticator: Authenticator, joan: User) -> None:
    with pytest.raises(InvalidCredentialsError):
        authenticator.authenticate("nobody", PASSWORD, phone())


def test_a_wrong_password_is_401(authenticator: Authenticator, joan: User) -> None:
    with pytest.raises(InvalidCredentialsError):
        authenticator.authenticate("Joan", "wrong", phone())


def test_a_disabled_account_is_403_even_with_the_right_password(
    factory: sessionmaker[OrmSession], authenticator: Authenticator, passwords: CountingPasswords
) -> None:
    """Measured. `401` here loops a client through a login the correct password never completes."""
    add_user(factory, passwords, name="Gone", is_disabled=True)
    with pytest.raises(AccountUnavailableError):
        authenticator.authenticate("Gone", PASSWORD, phone())


def test_a_failure_creates_no_session(
    authenticator: Authenticator, factory: sessionmaker[OrmSession], joan: User
) -> None:
    with pytest.raises(InvalidCredentialsError):
        authenticator.authenticate("Joan", "wrong", phone())
    with factory() as reader:
        assert SessionRepository(reader).for_user(joan.id) == []
        assert TokenRepository(reader).for_user(joan.id) == []


async def test_the_four_refusals_carry_one_body_and_three_statuses() -> None:
    """The status is the entire difference between them, which is why goldens compare bytes."""
    responses = [
        await client_authorization_handler(None, None),  # type: ignore[arg-type]
        await invalid_credentials_handler(None, None),  # type: ignore[arg-type]
        await account_unavailable_handler(None, None),  # type: ignore[arg-type]
    ]
    bodies = {response.body for response in responses}
    types = {response.headers["content-type"] for response in responses}
    assert bodies == {b"Error processing request."}
    assert types == {"text/plain"}
    assert [response.status_code for response in responses] == [400, 401, 403]


# --------------------------------------------------------------------------------------------
# The timing guarantee, counted rather than timed
# --------------------------------------------------------------------------------------------


def test_every_failure_path_runs_the_kdf_exactly_once(
    factory: sessionmaker[OrmSession], passwords: CountingPasswords, joan: User
) -> None:
    """Unknown, disabled, locked out, wrong password. Skipping any of them makes that branch
    return in microseconds while every other one takes tens of milliseconds, which is a username
    oracle rather than a performance win."""
    add_user(factory, passwords, name="Gone", is_disabled=True)
    add_user(
        factory,
        passwords,
        name="Locked",
        login_attempts_before_lockout=1,
        invalid_login_attempt_count=5,
    )
    authenticator = Authenticator(factory, passwords, SessionRegistry(factory))

    for username, expected in (
        ("nobody", InvalidCredentialsError),
        ("Gone", AccountUnavailableError),
        ("Locked", AccountUnavailableError),
        ("Joan", InvalidCredentialsError),
    ):
        before = passwords.verify_calls
        with pytest.raises(expected):
            authenticator.authenticate(username, "wrong", phone())
        assert passwords.verify_calls == before + 1, f"{username} did not run the KDF exactly once"


def test_a_success_runs_the_kdf_too(
    authenticator: Authenticator, passwords: CountingPasswords, joan: User
) -> None:
    before = passwords.verify_calls
    authenticator.authenticate("Joan", PASSWORD, phone())
    assert passwords.verify_calls == before + 1


# --------------------------------------------------------------------------------------------
# Lockout
# --------------------------------------------------------------------------------------------


def test_the_counter_survives_the_refusal_that_incremented_it(
    authenticator: Authenticator, factory: sessionmaker[OrmSession], joan: User
) -> None:
    """The write is on a path that ends in an exception. Raising inside the transaction rolls it
    back, and a server whose counter never moves passes every "wrong password is 401" test."""
    for expected in (1, 2, 3):
        with pytest.raises(InvalidCredentialsError):
            authenticator.authenticate("Joan", "wrong", phone())
        with factory() as reader:
            stored = UserRepository(reader).by_id(joan.id)
        assert stored is not None
        assert stored.invalid_login_attempt_count == expected


def test_after_the_threshold_even_the_right_password_is_refused(
    factory: sessionmaker[OrmSession], passwords: CountingPasswords
) -> None:
    """AC-10."""
    add_user(factory, passwords, name="Joan", login_attempts_before_lockout=3)
    authenticator = Authenticator(factory, passwords, SessionRegistry(factory))

    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            authenticator.authenticate("Joan", "wrong", phone())

    with pytest.raises(AccountUnavailableError):
        authenticator.authenticate("Joan", PASSWORD, phone())


def test_one_success_resets_the_counter(
    factory: sessionmaker[OrmSession], passwords: CountingPasswords
) -> None:
    add_user(factory, passwords, name="Joan", login_attempts_before_lockout=3)
    authenticator = Authenticator(factory, passwords, SessionRegistry(factory))

    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            authenticator.authenticate("Joan", "wrong", phone())
    authenticator.authenticate("Joan", PASSWORD, phone())

    with factory() as reader:
        stored = UserRepository(reader).by_name("Joan")
    assert stored is not None
    assert stored.invalid_login_attempt_count == 0


def test_the_reference_sentinel_does_not_lock_anybody_out(
    factory: sessionmaker[OrmSession], passwords: CountingPasswords
) -> None:
    """`-1` is what the reference sends for an untouched account, and what it means is OQ-6.

    Locking somebody out of their own server on a guess is a failure they experience and cannot
    undo; not locking is invisible to every client and becomes correct the moment OQ-6 is answered.
    """
    add_user(factory, passwords, name="Joan", login_attempts_before_lockout=-1)
    authenticator = Authenticator(factory, passwords, SessionRegistry(factory))

    for _ in range(10):
        with pytest.raises(InvalidCredentialsError):
            authenticator.authenticate("Joan", "wrong", phone())
    assert authenticator.authenticate("Joan", PASSWORD, phone()).user.name == "Joan"


def test_an_operator_can_turn_lockout_on_for_sentinel_accounts(
    factory: sessionmaker[OrmSession], passwords: CountingPasswords
) -> None:
    add_user(factory, passwords, name="Joan", login_attempts_before_lockout=-1)
    authenticator = Authenticator(
        factory, passwords, SessionRegistry(factory), AuthenticationSettings(lockout_attempts=2)
    )

    for _ in range(2):
        with pytest.raises(InvalidCredentialsError):
            authenticator.authenticate("Joan", "wrong", phone())
    with pytest.raises(AccountUnavailableError):
        authenticator.authenticate("Joan", PASSWORD, phone())


def test_a_users_own_positive_threshold_beats_the_operators_setting(
    factory: sessionmaker[OrmSession], passwords: CountingPasswords
) -> None:
    add_user(factory, passwords, name="Joan", login_attempts_before_lockout=5)
    authenticator = Authenticator(
        factory, passwords, SessionRegistry(factory), AuthenticationSettings(lockout_attempts=2)
    )
    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            authenticator.authenticate("Joan", "wrong", phone())
    assert authenticator.authenticate("Joan", PASSWORD, phone()).user.name == "Joan"


# --------------------------------------------------------------------------------------------
# Rehash on login
# --------------------------------------------------------------------------------------------


def test_a_stale_record_is_rewritten_at_the_current_cost(factory: sessionmaker[OrmSession]) -> None:
    """The one moment the plaintext exists, which is what makes raising the cost possible."""
    weak = CountingPasswords(CHEAP)
    user = add_user(factory, weak, name="Joan")
    assert describe(user.password_hash or "").memory_cost == CHEAP.memory_cost

    strong = CountingPasswords(COSTLIER)
    authenticator = Authenticator(factory, strong, SessionRegistry(factory))
    authenticator.authenticate("Joan", PASSWORD, phone())

    with factory() as reader:
        stored = UserRepository(reader).by_name("Joan")
    assert stored is not None
    assert describe(stored.password_hash or "").memory_cost == COSTLIER.memory_cost


def test_a_current_record_is_left_alone(
    authenticator: Authenticator, passwords: CountingPasswords, joan: User
) -> None:
    authenticator.authenticate("Joan", PASSWORD, phone())
    assert passwords.hash_calls == 0, "a record at the current cost was rewritten anyway"


def test_an_unreadable_record_refuses_rather_than_crashing(
    factory: sessionmaker[OrmSession], passwords: CountingPasswords
) -> None:
    """A record from another algorithm - the door ADR-0006 closed on importing a user database."""
    add_user(
        factory, passwords, name="Joan", password_hash="$pbkdf2-sha512$iterations=210000$0011$aabb"
    )
    authenticator = Authenticator(factory, passwords, SessionRegistry(factory))
    with pytest.raises(InvalidCredentialsError):
        authenticator.authenticate("Joan", PASSWORD, phone())
