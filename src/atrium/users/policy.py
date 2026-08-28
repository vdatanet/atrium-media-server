# SPDX-License-Identifier: GPL-3.0-or-later
"""The policy document: eleven properties this server acts on, and 31 it carries.

The reference sends **42** policy properties
`[probe: tools/probe_auth_mechanisms.py, Jellyfin 10.11.11, 2026-08-28]`. v1 honours eleven of
them, and the split is structural rather than conventional -
nine are typed columns, two are the library join table, and the remaining 31 live in a blob that
nothing in this project ever reads inside. A reader can therefore tell enforcement from storage by
looking at the schema, and honouring a twelfth means moving a key out of the blob into a column,
which is a migration and therefore a decision somebody makes on purpose.

**Assembling is not "return what was stored".** The document a client receives is built from three
places, and the order is the reference's own: a C# object serialises its properties in a fixed
order regardless of what any client sent, so echoing a client's key order would be the delta rather
than the fidelity. What round-trips is the **set of properties and their values**, which is what
`split(assemble(x)) == x` means here.

**A known property never lives in the blob.** Splitting strips the eleven out of `policy_extra`
before storing the rest, and assembling reads each of them from its column. That is what makes the
promotion of a property from blob to column - the migration described above - lossless in both
directions: a stale copy left in an old blob is ignored rather than fighting the column, and a
newer server's unknown property is preserved rather than dropped.

See specs/002-authentication-users-and-sessions/plan.md section 6.4 and spec section 3.5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from atrium.domain.user import LibraryAccess, User

#: Reference property name -> the column that holds it. Nine of the eleven honoured properties.
HONOURED_COLUMNS: Mapping[str, str] = {
    "IsAdministrator": "is_administrator",
    "IsDisabled": "is_disabled",
    "IsHidden": "is_hidden",
    "EnableAllFolders": "enable_all_folders",
    "EnableMediaPlayback": "enable_media_playback",
    "EnableContentDeletion": "enable_content_deletion",
    "LoginAttemptsBeforeLockout": "login_attempts_before_lockout",
    "InvalidLoginAttemptCount": "invalid_login_attempt_count",
    "MaxActiveSessions": "max_active_sessions",
}

#: The two honoured properties that are lists of libraries rather than flags. These are why eleven
#: honoured properties are nine columns.
ENABLED_FOLDERS = "EnabledFolders"
DELETION_FOLDERS = "EnableContentDeletionFromFolders"
HONOURED_LISTS = (ENABLED_FOLDERS, DELETION_FOLDERS)

#: Everything this server acts on. Anything else is carried, not read.
HONOURED = frozenset(HONOURED_COLUMNS) | frozenset(HONOURED_LISTS)

#: Which of the nine are booleans, so a value of the wrong shape is caught before it reaches a
#: typed column rather than being coerced into one by SQLite, which types nothing.
BOOLEAN_COLUMNS = frozenset(
    {
        "IsAdministrator",
        "IsDisabled",
        "IsHidden",
        "EnableAllFolders",
        "EnableMediaPlayback",
        "EnableContentDeletion",
    }
)


class PolicyError(ValueError):
    """A policy document this server cannot store as written."""


@dataclass(frozen=True, slots=True)
class PolicyUpdate:
    """A document taken apart, ready for the three places it goes."""

    #: Column name -> value, for the nine.
    columns: dict[str, Any] = field(default_factory=dict)
    access: LibraryAccess = field(default_factory=LibraryAccess)
    #: The other 31, or however many a newer server sent.
    extra: dict[str, Any] = field(default_factory=dict)


def assemble(user: User, access: LibraryAccess | None = None) -> dict[str, Any]:
    """The policy document a client receives.

    The nine columns and the two lists first, then everything carried - which is a canonical order
    of this server's choosing, exactly as the reference's is of its own.
    """
    reachable = access or LibraryAccess()
    document: dict[str, Any] = {
        name: getattr(user, column) for name, column in HONOURED_COLUMNS.items()
    }
    document[ENABLED_FOLDERS] = list(reachable.enabled_folders)
    document[DELETION_FOLDERS] = list(reachable.deletion_folders)
    for name, value in user.policy_extra.items():
        if name not in HONOURED:
            document[name] = value
    return document


def split(document: Mapping[str, Any]) -> PolicyUpdate:
    """Take a policy document apart into columns, library rows and the blob.

    A property in neither the column set nor the list set is preserved untouched: a client that
    round-trips a policy from a newer server must get its own data back, and this server has no way
    to tell a property it has not heard of from one that does not exist.
    """
    columns: dict[str, Any] = {}
    for name, column in HONOURED_COLUMNS.items():
        if name in document:
            columns[column] = _checked(name, document[name])

    access = LibraryAccess(
        enabled_folders=_library_ids(document.get(ENABLED_FOLDERS)),
        deletion_folders=_library_ids(document.get(DELETION_FOLDERS)),
    )
    extra = {name: value for name, value in document.items() if name not in HONOURED}
    return PolicyUpdate(columns=columns, access=access, extra=extra)


def _checked(name: str, value: Any) -> Any:
    """Refuse a value the column cannot hold, rather than letting SQLite decide what it meant.

    SQLite has no types to speak of: a string in a boolean column is stored and comes back as a
    string, and the flag it was supposed to be is then true for every value except the empty one.
    """
    if name in BOOLEAN_COLUMNS:
        if not isinstance(value, bool):
            raise PolicyError(f"{name} must be true or false, not {value!r}")
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(f"{name} must be a whole number, not {value!r}")
    return value


def _library_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise PolicyError(f"a list of library identifiers was expected, not {value!r}")
    return tuple(str(one) for one in value)


__all__ = [
    "BOOLEAN_COLUMNS",
    "DELETION_FOLDERS",
    "ENABLED_FOLDERS",
    "HONOURED",
    "HONOURED_COLUMNS",
    "HONOURED_LISTS",
    "PolicyError",
    "PolicyUpdate",
    "assemble",
    "split",
]
