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
    LibraryRepository,
    MediaProbeRepository,
    SessionRepository,
    TokenRepository,
    UserDataRepository,
    UserRepository,
    normalise_name,
    token_digest,
)
from atrium.domain.items import CollectionType
from atrium.domain.library import Library
from atrium.domain.media import InspectedStream, MediaInspection, StreamKind
from atrium.domain.playstate import UserItemData
from atrium.domain.session import AccessToken, IssuedToken, Session
from atrium.domain.user import User
from tests.conftest import data_dir

#: Where a returned type is allowed to come from. `types` is `NoneType`; `atrium.domain` is the
#: point of the module.
ALLOWED_MODULES = {
    "builtins",
    "datetime",
    "types",
    "atrium.domain.user",
    "atrium.domain.session",
    "atrium.domain.playstate",
    "atrium.domain.media",
}

REPOSITORIES = (
    UserRepository,
    TokenRepository,
    SessionRepository,
    UserDataRepository,
    MediaProbeRepository,
)


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


# ------------------------------------------------------------------------------------------
# User data (007 T3)
# ------------------------------------------------------------------------------------------


@pytest.fixture
def user_data(session: OrmSession) -> UserDataRepository:
    return UserDataRepository(session)


@pytest.fixture
def jordi(users: UserRepository) -> User:
    """A second account. Every claim about "per user" needs one to be a claim at all."""
    return users.add(User(id=new_id(), name="jordi"))


def test_a_user_with_no_row_reads_the_default_rather_than_nothing(
    user_data: UserDataRepository, joan: User
) -> None:
    """Absence is a state: never played, never favourited, no position. A `None` here would make
    every caller decide what that means, and one of them would decide differently."""
    assert user_data.get(joan.id, new_id()) == UserItemData()


def test_a_written_row_round_trips_every_stored_column(
    user_data: UserDataRepository, joan: User
) -> None:
    item_key = new_id()
    written = UserItemData(
        is_favorite=True,
        played=True,
        play_count=3,
        playback_position_ticks=12_345_670_000,
        last_played_date=datetime(2026, 8, 28, 9, 30, tzinfo=UTC),
    )
    user_data.put(joan.id, item_key, written)
    assert user_data.get(joan.id, item_key) == written


def test_writing_twice_replaces_rather_than_duplicating(
    user_data: UserDataRepository, session: OrmSession, joan: User
) -> None:
    """The primary key is `(user, item_key)`, so a second write is an update. A repository that
    added a row instead would be caught by the key here rather than by a user seeing two states."""
    item_key = new_id()
    user_data.put(joan.id, item_key, UserItemData(played=True, play_count=1))
    user_data.put(joan.id, item_key, UserItemData(play_count=2))
    stored = user_data.get(joan.id, item_key)
    assert (stored.played, stored.play_count) == (False, 2)
    rows = session.query(models.ItemUserData).filter_by(item_key=item_key).all()
    assert len(rows) == 1


def test_two_users_hold_one_items_state_independently(
    user_data: UserDataRepository, joan: User, jordi: User
) -> None:
    """AC-7 at the storage layer: two people watching the same file share nothing."""
    item_key = new_id()
    user_data.put(joan.id, item_key, UserItemData(played=True, play_count=1))
    assert user_data.get(jordi.id, item_key) == UserItemData()
    user_data.put(jordi.id, item_key, UserItemData(is_favorite=True))
    assert user_data.get(joan.id, item_key).played is True
    assert user_data.get(jordi.id, item_key).is_favorite is True


def test_the_rollup_is_not_stored(user_data: UserDataRepository, joan: User) -> None:
    """`unplayed_count` is computed per page from the subtree and has no column. Passing a
    rolled-up record through `put` must not invent one - a stored aggregate is the cache
    spec section 3.5 forbids, and this is where somebody would add it."""
    item_key = new_id()
    user_data.put(joan.id, item_key, UserItemData(played=True, unplayed_count=4))
    assert user_data.get(joan.id, item_key).unplayed_count is None


def test_a_row_survives_the_item_it_describes(
    user_data: UserDataRepository, session: OrmSession, joan: User
) -> None:
    """The absent foreign key, asserted rather than trusted: `item_key` names an item that has
    never existed, and the write succeeds. Under a cascade this row could not be written at all,
    and a slow-mounting share would delete a user's history (003 spec section 3.8)."""
    user_data.put(joan.id, new_id(), UserItemData(is_favorite=True))
    session.flush()


def test_deleting_the_user_takes_their_rows_with_them(
    user_data: UserDataRepository, session: OrmSession, joan: User
) -> None:
    """The one cascade there *is*: the user. Their data is theirs, and an account that is gone
    leaves nothing behind to be restored to somebody else with the same identifier."""
    item_key = new_id()
    user_data.put(joan.id, item_key, UserItemData(played=True))
    session.delete(session.get(models.User, joan.id))
    session.flush()
    assert session.query(models.ItemUserData).filter_by(item_key=item_key).all() == []


# ------------------------------------------------------------------------------------------
# Media probes (008 T2)
# ------------------------------------------------------------------------------------------

#: The rest of this repository's behaviour - staleness, cascades, the keyframe list, a real file
#: inspected and stored - lives in tests/unit/test_media_probe.py, beside the prober that produces
#: the records. What belongs *here* is that it takes part in the sweep at the top of this file,
#: which is a claim about the boundary rather than about media.


@pytest.fixture
def probes(session: OrmSession) -> MediaProbeRepository:
    return MediaProbeRepository(session)


@pytest.fixture
def films(session: OrmSession, tmp_path: Path) -> Library:
    return LibraryRepository(session).add(
        Library(
            id=new_id(),
            name="Films",
            collection_type=CollectionType.MOVIES,
            roots=(str(tmp_path / "films"),),
        )
    )


def test_an_inspection_comes_back_as_a_domain_object(
    probes: MediaProbeRepository, films: Library
) -> None:
    """The annotations say `MediaInspection`; this asserts the objects agree with them, streams
    included - a row that escaped inside the tuple would satisfy the annotation sweep and fail
    the moment its session closed."""
    written = MediaInspection(
        size=10,
        mtime_ns=20,
        container="mkv",
        format_names="matroska,webm",
        probed_at=datetime(2026, 8, 29, 12, tzinfo=UTC),
        streams=(InspectedStream(index=0, kind=StreamKind.VIDEO, codec="h264"),),
    )
    probes.put(films.id, "A Film (2026).mkv", written)

    read = probes.get(films.id, "A Film (2026).mkv")
    assert isinstance(read, MediaInspection)
    assert all(isinstance(one, InspectedStream) for one in read.streams)
    assert isinstance(probes.current(films.id, "A Film (2026).mkv", 10, 20), MediaInspection)
