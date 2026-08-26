# SPDX-License-Identifier: GPL-3.0-or-later
"""The boundary: domain objects out, never rows.

The first test in this file is a **sweep**, not an example. It walks every public method of the
module and resolves its return annotation, so a method added next year that returns a row fails
here without anybody remembering that it should. Checking three representative methods by hand
would pass for exactly as long as somebody kept doing it.
"""

from __future__ import annotations

import inspect
import types
import typing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession

from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db import models, repositories, schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import (
    SessionRepository,
    TokenRepository,
    UserRepository,
    normalise_name,
    token_digest,
)
from atrium.domain.session import AccessToken, IssuedToken, Session
from atrium.domain.user import User
from tests.conftest import data_dir

#: Where a returned type is allowed to come from. `types` is `NoneType`; `atrium.domain` is the
#: point of the module.
ALLOWED_MODULES = {"builtins", "datetime", "types", "atrium.domain.user", "atrium.domain.session"}

REPOSITORIES = (UserRepository, TokenRepository, SessionRepository)


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def engine(prepared: DataPaths) -> Engine:
    built = create_database_engine(prepared)
    schema.ensure_current(built, prepared)
    yield built
    built.dispose()


@pytest.fixture
def session(engine: Engine) -> OrmSession:
    factory = session_factory(engine)
    opened = factory()
    yield opened
    opened.rollback()
    opened.close()


@pytest.fixture
def users(session: OrmSession) -> UserRepository:
    return UserRepository(session)


@pytest.fixture
def tokens(session: OrmSession) -> TokenRepository:
    return TokenRepository(session)


@pytest.fixture
def sessions(session: OrmSession) -> SessionRepository:
    return SessionRepository(session)


@pytest.fixture
def joan(users: UserRepository) -> User:
    return users.add(User(id=new_id(), name="Joan"))


# --------------------------------------------------------------------------------------------
# The sweep
# --------------------------------------------------------------------------------------------


def leaf_types(annotation: Any) -> list[Any]:
    """Every concrete type inside an annotation - `list[User | None]` gives `list`, `User`, None.

    The origin is kept only when it is a real container: `list[...]` contributes `list`. A union's
    origin is skipped - on Python 3.14 `typing.Union` **is** a class, so `isinstance(origin, type)`
    is not enough to tell a container from a special form, and every `X | None` in the module would
    fail the sweep for coming from `typing`.
    """
    arguments = typing.get_args(annotation)
    if not arguments:
        return [annotation]
    origin = typing.get_origin(annotation)
    is_union = origin is typing.Union or origin is types.UnionType
    found: list[Any] = [origin] if isinstance(origin, type) and not is_union else []
    for argument in arguments:
        found.extend(leaf_types(argument))
    return found


def defined_here(function: Any) -> bool:
    """Written in this module, rather than imported into it.

    Without this the sweep walks `select` and `delete` too - a module's imported names are part of
    its surface unless something says otherwise - and then fails on SQLAlchemy's own annotations
    rather than on anything this project wrote.
    """
    return getattr(function, "__module__", None) == repositories.__name__


def public_methods() -> list[tuple[str, Any]]:
    found = []
    for repository in REPOSITORIES:
        for name, method in inspect.getmembers(repository, inspect.isfunction):
            if not name.startswith("_") and defined_here(method):
                found.append((f"{repository.__name__}.{name}", method))
    for name, function in inspect.getmembers(repositories, inspect.isfunction):
        if not name.startswith("_") and defined_here(function):
            found.append((f"repositories.{name}", function))
    return found


def test_the_sweep_actually_finds_the_methods() -> None:
    """A sweep over nothing passes. This is the assertion that it is sweeping."""
    names = {name for name, _ in public_methods()}
    assert {"UserRepository.by_id", "TokenRepository.issue", "SessionRepository.all"} <= names
    assert len(names) > 15


@pytest.mark.parametrize("name,method", public_methods(), ids=[n for n, _ in public_methods()])
def test_no_orm_type_escapes(name: str, method: Any) -> None:
    """Architecture section 1: no SQLAlchemy type crosses out of `db/`.

    Return annotations only - a repository is *given* a unit of work, which is how it has a
    transaction at all, and that is an input rather than something escaping.
    """
    hints = typing.get_type_hints(method)
    returned = hints.get("return")
    for leaf in leaf_types(returned):
        module = getattr(leaf, "__module__", "builtins")
        assert module in ALLOWED_MODULES, (
            f"{name} returns {leaf!r} from {module}. Repositories hand out domain objects; a row "
            f"that leaves this module is one whose session may already be closed."
        )


def test_the_sweep_rejects_what_it_exists_to_reject() -> None:
    """A sweep that cannot fail is decoration.

    This is the method somebody writes on a tired afternoon: it works, every test passes, and a
    row is now loose above `db/` where reading one attribute after the session closes raises.
    """

    class Careless:
        def by_id(self, user_id: str) -> models.User | None:  # the row, not the domain object
            raise NotImplementedError

        def rows(self) -> list[models.Session]:
            raise NotImplementedError

    for method in (Careless.by_id, Careless.rows):
        returned = typing.get_type_hints(method, globalns={"models": models}).get("return")
        modules = {getattr(leaf, "__module__", "builtins") for leaf in leaf_types(returned)}
        assert not modules <= ALLOWED_MODULES, f"{method.__name__} should have been rejected"


def test_what_comes_back_at_runtime_is_a_domain_object(
    users: UserRepository, tokens: TokenRepository, sessions: SessionRepository, joan: User
) -> None:
    """The annotations say so; this asserts the objects agree with them."""
    issued = tokens.issue(joan.id, device_id="phone")
    stored = sessions.upsert(Session(id=new_id(), user_id=joan.id, device_id="phone"))

    assert isinstance(users.by_id(joan.id), User)
    assert isinstance(users.by_name("joan"), User)
    assert all(isinstance(one, User) for one in users.all())
    assert all(isinstance(one, User) for one in users.visible_on_login_screens())
    assert isinstance(issued, IssuedToken)
    assert isinstance(issued.record, AccessToken)
    assert isinstance(tokens.resolve(issued.secret), AccessToken)
    assert all(isinstance(one, AccessToken) for one in tokens.for_user(joan.id))
    assert isinstance(stored, Session)
    assert isinstance(sessions.by_device(joan.id, "phone"), Session)
    assert all(isinstance(one, Session) for one in sessions.all())


def test_the_dictionaries_that_come_back_are_copies(users: UserRepository) -> None:
    """A caller that mutated one would be editing the session's idea of what is in the database."""
    configured = {"AudioLanguagePreference": "cat"}
    user = users.add(User(id=new_id(), name="Ada", configuration=configured))
    fetched = users.by_id(user.id)
    assert fetched is not None
    fetched.configuration["AudioLanguagePreference"] = "eng"
    again = users.by_id(user.id)
    assert again is not None
    assert again.configuration == {"AudioLanguagePreference": "cat"}


# --------------------------------------------------------------------------------------------
# The token never exists in storage
# --------------------------------------------------------------------------------------------


def test_a_token_is_returned_once_and_stored_as_a_hash(tokens: TokenRepository, joan: User) -> None:
    issued = tokens.issue(joan.id, device_id="phone")
    assert len(issued.secret) == 32
    assert issued.record.token_sha256 == token_digest(issued.secret)
    assert issued.record.token_sha256 != issued.secret

    for record in tokens.for_user(joan.id):
        for value in vars(record).values() if hasattr(record, "__dict__") else ():
            assert value != issued.secret
        assert issued.secret not in repr(record)


def test_reading_a_token_back_never_yields_the_original(
    tokens: TokenRepository, joan: User
) -> None:
    """There is no field to read it from, which is the point rather than an accident."""
    issued = tokens.issue(joan.id, device_id="phone")
    resolved = tokens.resolve(issued.secret)
    assert resolved is not None
    assert not [name for name in AccessToken.__slots__ if "secret" in name or name == "token"]
    assert issued.secret not in str(resolved)


def test_the_secret_is_not_in_the_repr_of_the_thing_that_holds_it(
    tokens: TokenRepository, joan: User
) -> None:
    """`IssuedToken` is handed to the code that builds an authentication response, which is
    exactly where somebody eventually adds a debug log line."""
    issued = tokens.issue(joan.id, device_id="phone")
    assert issued.secret not in repr(issued)


def test_an_unknown_token_resolves_to_nothing(tokens: TokenRepository) -> None:
    assert tokens.resolve("0" * 32) is None


def test_two_tokens_are_never_the_same(tokens: TokenRepository, joan: User) -> None:
    secrets_issued = {tokens.issue(joan.id, device_id=f"d{index}").secret for index in range(16)}
    assert len(secrets_issued) == 16


# --------------------------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", ["joan", "Joan", "JOAN", "  joan  "])
def test_a_login_matches_whatever_case_it_arrives_in(
    users: UserRepository, joan: User, spelling: str
) -> None:
    found = users.by_name(spelling)
    assert found is not None
    assert found.id == joan.id


def test_normalisation_folds_rather_than_lowercases() -> None:
    """`STRASSE` and `Straße` are one login. `lower` leaves them as two, one unreachable."""
    assert normalise_name("STRASSE") == normalise_name("Straße")
    assert normalise_name("Ünïcödé") == normalise_name("ÜNÏCÖDÉ")


def test_two_accounts_cannot_share_a_normalised_name(users: UserRepository, joan: User) -> None:
    with pytest.raises(IntegrityError):
        users.add(User(id=new_id(), name="JOAN"))


def test_a_hidden_user_is_not_on_the_login_screen(users: UserRepository, joan: User) -> None:
    users.add(User(id=new_id(), name="Ghost", is_hidden=True))
    assert {one.name for one in users.visible_on_login_screens()} == {"Joan"}
    assert {one.name for one in users.all()} == {"Joan", "Ghost"}


def test_every_user_hidden_is_an_empty_list_not_an_error(users: UserRepository) -> None:
    """Spec section 3.4: a legitimate `200` with `[]`."""
    users.add(User(id=new_id(), name="Ghost", is_hidden=True))
    assert users.visible_on_login_screens() == []


def test_failed_attempts_count_up_and_one_success_resets_them(
    users: UserRepository, joan: User
) -> None:
    assert users.record_failed_attempt(joan.id) == 1
    assert users.record_failed_attempt(joan.id) == 2
    users.record_success(joan.id, when=datetime(2026, 8, 26, 12, tzinfo=UTC))
    after = users.by_id(joan.id)
    assert after is not None
    assert after.invalid_login_attempt_count == 0
    assert after.last_login_date == datetime(2026, 8, 26, 12, tzinfo=UTC)


def test_configuration_is_replaced_not_merged(users: UserRepository, joan: User) -> None:
    """`POST /Users/Configuration` replaces the document (spec section 3.6)."""
    users.replace_configuration(joan.id, {"A": 1, "B": 2})
    users.replace_configuration(joan.id, {"B": 3})
    after = users.by_id(joan.id)
    assert after is not None
    assert after.configuration == {"B": 3}


def test_a_policy_property_v1_never_heard_of_survives(users: UserRepository) -> None:
    unknown = {"SomethingFromTheFuture": {"nested": [1, 2]}}
    user = users.add(User(id=new_id(), name="Ada", policy_extra=unknown))
    fetched = users.by_id(user.id)
    assert fetched is not None
    assert fetched.policy_extra == unknown


# --------------------------------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------------------------------


def test_one_device_keeps_one_session(sessions: SessionRepository, joan: User) -> None:
    first = sessions.upsert(
        Session(id=new_id(), user_id=joan.id, device_id="phone", client="Android")
    )
    second = sessions.upsert(
        Session(id=new_id(), user_id=joan.id, device_id="phone", client="Android 2")
    )
    assert second.id == first.id, "a second login from one device replaced rather than added"
    assert [one.client for one in sessions.for_user(joan.id)] == ["Android 2"]


def test_two_devices_are_two_sessions(sessions: SessionRepository, joan: User) -> None:
    sessions.upsert(Session(id=new_id(), user_id=joan.id, device_id="phone"))
    sessions.upsert(Session(id=new_id(), user_id=joan.id, device_id="tablet"))
    assert len(sessions.for_user(joan.id)) == 2


def test_capabilities_are_stored_whole_and_read_back(
    sessions: SessionRepository, joan: User
) -> None:
    stored = sessions.upsert(Session(id=new_id(), user_id=joan.id, device_id="phone"))
    posted = {"PlayableMediaTypes": ["Video"], "SupportedCommands": ["Play"], "Unknown": {"x": 1}}
    sessions.set_capabilities(stored.id, posted)
    again = sessions.by_id(stored.id)
    assert again is not None
    assert again.capabilities == posted


def test_sessions_come_back_most_recently_active_first(
    sessions: SessionRepository, joan: User
) -> None:
    old = datetime(2026, 8, 26, 9, tzinfo=UTC)
    sessions.upsert(
        Session(id=new_id(), user_id=joan.id, device_id="tablet", last_activity_date=old)
    )
    sessions.upsert(
        Session(
            id=new_id(),
            user_id=joan.id,
            device_id="phone",
            last_activity_date=old + timedelta(hours=1),
        )
    )
    assert [one.device_id for one in sessions.all()] == ["phone", "tablet"]


def test_revoking_a_device_leaves_no_working_token(
    tokens: TokenRepository, sessions: SessionRepository, joan: User
) -> None:
    """Spec section 3.8: re-authenticating invalidates the previous token, with no window."""
    first = tokens.issue(joan.id, device_id="phone")
    second = tokens.issue(joan.id, device_id="tablet")

    assert tokens.revoke_device(joan.id, "phone") == 1
    assert tokens.resolve(first.secret) is None
    assert tokens.resolve(second.secret) is not None
