# SPDX-License-Identifier: GPL-3.0-or-later
"""Eleven properties this server acts on, and 31 it carries.

The set of names below is measured, not invented: it is what the reference sent for a real account
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`. Testing the split
against a document of
three properties would prove the mechanism and nothing about the shape a client actually posts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select

from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db import models, schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import UserRepository
from atrium.domain.user import LibraryAccess, User
from atrium.users.policy import (
    DELETION_FOLDERS,
    ENABLED_FOLDERS,
    HONOURED,
    HONOURED_COLUMNS,
    PolicyError,
    assemble,
    split,
)
from tests.conftest import data_dir

#: The 31 properties the reference sends that v1 stores and never reads.
CARRIED = (
    "AccessSchedules",
    "AllowedTags",
    "AuthenticationProviderId",
    "BlockUnratedItems",
    "BlockedChannels",
    "BlockedMediaFolders",
    "BlockedTags",
    "EnableAllChannels",
    "EnableAllDevices",
    "EnableAudioPlaybackTranscoding",
    "EnableCollectionManagement",
    "EnableContentDownloading",
    "EnableLiveTvAccess",
    "EnableLiveTvManagement",
    "EnableLyricManagement",
    "EnableMediaConversion",
    "EnablePlaybackRemuxing",
    "EnablePublicSharing",
    "EnableRemoteAccess",
    "EnableRemoteControlOfOtherUsers",
    "EnableSharedDeviceControl",
    "EnableSubtitleManagement",
    "EnableSyncTranscoding",
    "EnableUserPreferenceAccess",
    "EnableVideoPlaybackTranscoding",
    "EnabledChannels",
    "EnabledDevices",
    "ForceRemoteSourceTranscoding",
    "PasswordResetProviderId",
    "RemoteClientBitrateLimit",
    "SyncPlayAccess",
)

LIBRARY_ONE = "1" * 32
LIBRARY_TWO = "2" * 32


def reference_document() -> dict[str, Any]:
    """A policy in the shape the reference sends one, with plausible values."""
    document: dict[str, Any] = {
        "IsAdministrator": True,
        "IsDisabled": False,
        "IsHidden": False,
        "EnableAllFolders": False,
        "EnableMediaPlayback": True,
        "EnableContentDeletion": False,
        "LoginAttemptsBeforeLockout": -1,
        "InvalidLoginAttemptCount": 0,
        "MaxActiveSessions": 0,
        ENABLED_FOLDERS: [LIBRARY_ONE, LIBRARY_TWO],
        DELETION_FOLDERS: [LIBRARY_TWO],
    }
    listish = ("Tags", "Channels", "Devices", "Schedules")
    for index, name in enumerate(CARRIED):
        document[name] = [] if name.endswith(listish) else index
    return document


@pytest.fixture
def prepared(tmp_path: Path) -> DataPaths:
    return data_dir(tmp_path / "atrium")


@pytest.fixture
def engine(prepared: DataPaths) -> Engine:
    built = create_database_engine(prepared)
    schema.ensure_current(built, prepared)
    yield built
    built.dispose()


# --------------------------------------------------------------------------------------------
# The counts, pinned
# --------------------------------------------------------------------------------------------


def test_the_reference_sends_forty_two_and_eleven_are_honoured() -> None:
    """Three numbers the documents used interchangeably until T4 measured them apart."""
    document = reference_document()
    assert len(document) == 42
    assert len(HONOURED) == 11
    assert len(HONOURED_COLUMNS) == 9
    assert len(CARRIED) == 31
    assert set(document) - HONOURED == set(CARRIED)


def test_the_remote_access_flag_is_carried_and_never_read() -> None:
    """The one carried property whose feature this server *has*. behaviours 4.5.

    The other 27 gate something v1 does not do, so storing them and reading none of them is
    unobservable. This one gates being reachable, which v1 does, and it is accepted as a
    deliberate exception rather than as a gap - which means the split has to keep putting it on
    the side nothing enforces, deliberately, and a future contributor promoting it to `HONOURED`
    has to come past this line.
    """
    assert "EnableRemoteAccess" in CARRIED
    assert "EnableRemoteAccess" not in HONOURED
    assert "EnableRemoteAccess" not in HONOURED_COLUMNS


# --------------------------------------------------------------------------------------------
# The round trip
# --------------------------------------------------------------------------------------------


def test_a_policy_from_a_newer_server_gets_its_own_data_back(engine: Engine) -> None:
    """Through the database, not just through the two functions.

    A property this server has never heard of has to survive being taken apart, written into a
    blob, read back and reassembled - which is where a split that quietly dropped the unknown half
    would show up and a pure round-trip test would not.
    """
    original = reference_document()
    original["SomethingFromTheFuture"] = {"nested": [1, 2, 3], "deep": {"x": None}}

    factory = session_factory(engine)
    with factory.begin() as opened:
        users = UserRepository(opened)
        user = users.add(User(id=new_id(), name="Joan"))
        update = split(original)
        users.set_policy(user.id, update.columns, update.extra)
        users.set_library_access(user.id, update.access)

    with factory.begin() as opened:
        users = UserRepository(opened)
        stored = users.by_id(user.id)
        assert stored is not None
        rebuilt = assemble(stored, users.library_access(user.id))

    assert rebuilt == original
    assert rebuilt["SomethingFromTheFuture"] == {"nested": [1, 2, 3], "deep": {"x": None}}


def test_the_key_order_is_this_servers_own_and_that_is_the_point() -> None:
    """Byte-identity would mean echoing the client's key order, and the reference does not.

    A C# object serialises its properties in a fixed order whatever arrived, so preserving a
    client's ordering would be the delta rather than the fidelity. What round-trips is the set of
    properties and their values.
    """
    shuffled = dict(reversed(list(reference_document().items())))
    update = split(shuffled)
    user = User(id=new_id(), name="Joan", policy_extra=update.extra, **update.columns)
    rebuilt = assemble(user, update.access)

    assert rebuilt == shuffled
    assert list(rebuilt) != list(shuffled)
    assert list(rebuilt)[:9] == list(HONOURED_COLUMNS)


def test_split_puts_the_honoured_properties_where_they_are_enforced() -> None:
    update = split(reference_document())
    assert set(update.columns) == set(HONOURED_COLUMNS.values())
    assert update.access.enabled_folders == (LIBRARY_ONE, LIBRARY_TWO)
    assert update.access.deletion_folders == (LIBRARY_TWO,)
    assert not HONOURED & set(update.extra), "an honoured property was left in the blob"


def test_a_partial_document_only_writes_what_it_carries() -> None:
    """An operator's file that names three properties should not reset the other eight."""
    update = split({"IsHidden": True, "MaxActiveSessions": 2})
    assert update.columns == {"is_hidden": True, "max_active_sessions": 2}
    assert update.access == LibraryAccess()
    assert update.extra == {}


# --------------------------------------------------------------------------------------------
# The nine are columns, which is the whole reason for the split
# --------------------------------------------------------------------------------------------


def test_the_honoured_flags_are_queryable(engine: Engine) -> None:
    """A blob would make this a scan and a filter in Python. That is what 005 cannot afford."""
    factory = session_factory(engine)
    with factory.begin() as opened:
        users = UserRepository(opened)
        for name, hidden in (("Joan", False), ("Ghost", True), ("Ada", False)):
            user = users.add(User(id=new_id(), name=name))
            update = split({"IsHidden": hidden})
            users.set_policy(user.id, update.columns, update.extra)

    with factory.begin() as opened:
        visible = opened.execute(
            select(models.User.name).where(models.User.is_hidden.is_(False))
        ).scalars()
        assert set(visible) == {"Joan", "Ada"}


def test_the_library_lists_come_back_from_the_join_table(engine: Engine) -> None:
    factory = session_factory(engine)
    with factory.begin() as opened:
        users = UserRepository(opened)
        user = users.add(User(id=new_id(), name="Joan"))
        users.set_library_access(
            user.id,
            LibraryAccess(
                enabled_folders=(LIBRARY_ONE, LIBRARY_TWO), deletion_folders=(LIBRARY_TWO,)
            ),
        )

    with factory.begin() as opened:
        users = UserRepository(opened)
        access = users.library_access(user.id)
    assert access.enabled_folders == (LIBRARY_ONE, LIBRARY_TWO)
    assert access.deletion_folders == (LIBRARY_TWO,)


def test_replacing_the_lists_removes_what_is_no_longer_in_them(engine: Engine) -> None:
    """A library absent from `EnabledFolders` is one the user may not see, so a merge is wrong."""
    factory = session_factory(engine)
    with factory.begin() as opened:
        users = UserRepository(opened)
        user = users.add(User(id=new_id(), name="Joan"))
        users.set_library_access(user.id, LibraryAccess(enabled_folders=(LIBRARY_ONE, LIBRARY_TWO)))
        users.set_library_access(user.id, LibraryAccess(enabled_folders=(LIBRARY_TWO,)))

    with factory.begin() as opened:
        access = UserRepository(opened).library_access(user.id)
    assert access.enabled_folders == (LIBRARY_TWO,)


# --------------------------------------------------------------------------------------------
# Promoting a property from the blob to a column
# --------------------------------------------------------------------------------------------


def test_a_property_promoted_to_a_column_is_read_from_the_column(engine: Engine) -> None:
    """The migration plan section 6.4 describes: honouring a twelfth property moves a key.

    A blob written before that migration still holds the old key. The column has to win, and the
    stale copy has to disappear rather than shadowing it - otherwise the flag a server enforces and
    the flag it reports come from two different places.
    """
    factory = session_factory(engine)
    with factory.begin() as opened:
        users = UserRepository(opened)
        user = users.add(User(id=new_id(), name="Joan"))
        # The state a pre-migration database is in: the value is in the blob, under a name that
        # this build now honours.
        users.set_policy(user.id, {"is_hidden": True}, {"IsHidden": False, "Kept": 1})

    with factory.begin() as opened:
        users = UserRepository(opened)
        stored = users.by_id(user.id)
        assert stored is not None
        document = assemble(stored, users.library_access(user.id))

    assert document["IsHidden"] is True, "the stale blob copy shadowed the column"
    assert document["Kept"] == 1
    assert list(document).count("IsHidden") == 1


def test_splitting_again_strips_the_stale_copy(engine: Engine) -> None:
    """One write through `split` is enough to clean it up, with no migration of its own."""
    update = split({"IsHidden": True, "Kept": 1})
    assert "IsHidden" not in update.extra
    assert update.extra == {"Kept": 1}


# --------------------------------------------------------------------------------------------
# What a typed column cannot hold
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "document",
    [
        {"IsHidden": "true"},
        {"IsHidden": 1},
        {"IsAdministrator": None},
        {"MaxActiveSessions": "2"},
        {"MaxActiveSessions": True},
        {"LoginAttemptsBeforeLockout": 1.5},
    ],
)
def test_a_value_the_column_cannot_hold_is_refused(document: dict[str, Any]) -> None:
    """SQLite types nothing: a string in a boolean column comes back a string, and the flag is
    then true for every value except the empty one."""
    with pytest.raises(PolicyError):
        split(document)


@pytest.mark.parametrize("value", ["not-a-list", 3, {"a": 1}])
def test_a_library_list_that_is_not_a_list_is_refused(value: Any) -> None:
    with pytest.raises(PolicyError):
        split({ENABLED_FOLDERS: value})


def test_an_absent_list_is_not_an_empty_one(engine: Engine) -> None:
    """A document that says nothing about libraries changes nothing about them."""
    assert split({}).access == LibraryAccess()
