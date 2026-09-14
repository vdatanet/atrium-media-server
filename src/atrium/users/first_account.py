# SPDX-License-Identifier: GPL-3.0-or-later
"""The first account: created by a read, named by a rule, updated in the reference's order.

**Nothing else in this server creates an account.** The reference's first-time setup has exactly one
operation that does, `GET /Startup/User`, which creates an administrator when no account exists and
answers its name `[source: Jellyfin.Api/Controllers/StartupController.cs:110-119 and
Jellyfin.Server.Implementations/Users/UserManager.cs:700-727 @ v10.11.11]` - so the order of an
unattended setup is fixed: read first, then update, because the update cannot create
(014 spec sections 3.2 and 3.3).

**The name is always `MyJellyfinUser`.** The reference names the account after the operating-system
account it runs as and falls back to that string; this server always takes the fallback, which is
the deliberate exception in behaviours section 4.7.

**The update runs in the reference's order**, and the order is what a client can observe: the
account must exist, then the password must not be blank, then a rename is checked and applied, and
only then does the password change - so a refused rename leaves the password as it was, which T1
measured `[probe: tools/probe_first_time_setup.py, Jellyfin 10.11.11, 2026-09-14]`. Here the whole
update is also one transaction, so a refusal writes nothing whatever order the writes were in.

See specs/014-first-time-setup/plan.md sections 6.3 and 6.4.
"""

from __future__ import annotations

import unicodedata
from typing import Final, NamedTuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from atrium.compat.guids import new_id
from atrium.db.engine import session_scope
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.users.passwords import Passwords

#: The reference's own fallback name, taken on every host (behaviours section 4.7).
FIRST_ACCOUNT_NAME: Final = "MyJellyfinUser"

#: The one permission the first account is given that has no column, in the reference's spelling
#: `[source: Jellyfin.Server.Implementations/Users/UserManager.cs:722 @ v10.11.11]`. Carried in the
#: policy blob like every other property nothing here queries (users/policy.py).
REMOTE_CONTROL_OF_OTHER_USERS: Final = "EnableRemoteControlOfOtherUsers"

#: The general categories the reference's word class admits: every letter, the non-spacing marks,
#: the decimal digits and the connector punctuation. **Python's `\w` is not this set** - it admits
#: the other numeric categories and no mark or connector but `_` - which is why the rule is written
#: as a category test rather than as a pattern (014 plan section 6.4).
WORD_CATEGORIES: Final = frozenset({"Lu", "Ll", "Lt", "Lm", "Lo", "Mn", "Nd", "Pc"})

#: The characters the rule admits beside the word characters.
OTHER_USERNAME_CHARACTERS: Final = frozenset(" -'._@+")

#: What the reference's blank-password test counts as white space beside the three separator
#: categories: the five ASCII control whitespace characters and the next line character.
_CONTROL_WHITESPACE: Final = frozenset("\t\n\v\f\r\x85")
_SEPARATOR_CATEGORIES: Final = frozenset({"Zs", "Zl", "Zp"})


class NoAccountError(LookupError):
    """There is no account to update. Answered `404` in problem details."""


class EmptyPasswordError(ValueError):
    """The password is missing, empty or white space. Answered `400` with the bare JSON string."""


class InvalidUsernameError(ValueError):
    """The new name is not a valid username. Answered `400` with `Error processing request.`"""


class UsernameTakenError(ValueError):
    """Another account holds the new name. Answered `400` with `Error processing request.`"""


class StartupUserUpdate(NamedTuple):
    """What `POST /Startup/User` carries: a name that may be absent and a password that may be."""

    name: str | None
    password: str | None


def ensure_first_account(repository: UserRepository) -> User:
    """The first account, created as the reference creates it if no account exists.

    An administrator, hidden from the sign-in screen, allowed to delete content and to control
    other users' sessions, and with no password `[source:
    Jellyfin.Server.Implementations/Users/UserManager.cs:720-722 and
    Jellyfin.Data/UserEntityExtensions.cs:174 @ v10.11.11]` (014 spec section 3.2). Nothing is
    created when any account exists, so a second call answers the same account.
    """
    existing = repository.first()
    if existing is not None:
        return existing
    return repository.add(
        User(
            id=new_id(),
            name=FIRST_ACCOUNT_NAME,
            is_administrator=True,
            is_hidden=True,
            enable_content_deletion=True,
            policy_extra={REMOTE_CONTROL_OF_OTHER_USERS: True},
        )
    )


def read_first_account(sessions: sessionmaker[OrmSession]) -> User:
    """`ensure_first_account` in a transaction of its own, settling two first reads at once.

    The unique name is what settles them: the loser's insert fails, and it reads again and answers
    the account the winner made (014 plan section 6.3). Here rather than in the route, because a
    route module owns no SQL and catching the database's refusal is SQL.
    """
    try:
        with session_scope(sessions) as opened:
            return ensure_first_account(UserRepository(opened))
    except IntegrityError:
        with session_scope(sessions) as opened:
            found = UserRepository(opened).first()
        if found is None:
            raise
        return found


def is_blank(value: str | None) -> bool:
    """Missing, empty, or nothing but white space - the reference's test for a password."""
    if not value:
        return True
    return all(
        character in _CONTROL_WHITESPACE or unicodedata.category(character) in _SEPARATOR_CATEGORIES
        for character in value
    )


def _is_username_character(character: str) -> bool:
    return (
        character in OTHER_USERNAME_CHARACTERS or unicodedata.category(character) in WORD_CATEGORIES
    )


def is_valid_username(name: str) -> bool:
    """Whether `name` is a username the reference would accept, restated rather than transcribed.

    Non-empty; every character a word character (`WORD_CATEGORIES`) or one of space, `-`, `'`,
    `.`, `_`, `@` and `+`; and neither the first nor the last of them a space
    `[source: Jellyfin.Server.Implementations/Users/UserManager.cs:116-120, 899-907 @ v10.11.11]`.
    A space is the only white space character the set admits, so "no leading or trailing white
    space" is "no leading or trailing space".

    **One final line feed is admitted after an otherwise valid name**, because the end anchor the
    reference's rule closes with matches before a string's final line feed as well as at its end -
    read from the rule and the anchor's documented meaning, not measured (plan section 6.4,
    amended 2026-09-14).
    """
    body = name[:-1] if name.endswith("\n") else name
    if not body or body[0] == " " or body[-1] == " ":
        return False
    return all(_is_username_character(character) for character in body)


def _same_ignoring_case(one: str, other: str) -> bool:
    return one.lower() == other.lower()


def update_first_account(
    sessions: sessionmaker[OrmSession], passwords: Passwords, update: StartupUserUpdate
) -> None:
    """Rename the first account if asked and set its password, in the reference's order.

    Synchronous and hashing, so a route runs it off the event loop. Every refusal is raised before
    this transaction commits, so none of them leaves a write behind (014 plan section 6.4).
    """
    with session_scope(sessions) as opened:
        users = UserRepository(opened)
        account = users.first()
        if account is None:
            raise NoAccountError
        if update.password is None or is_blank(update.password):
            raise EmptyPasswordError
        if update.name is not None and not _same_ignoring_case(update.name, account.name):
            if not is_valid_username(update.name):
                raise InvalidUsernameError
            if not users.rename(account.id, update.name):
                raise UsernameTakenError
        users.set_password_hash(account.id, passwords.hash(update.password))


__all__ = [
    "FIRST_ACCOUNT_NAME",
    "OTHER_USERNAME_CHARACTERS",
    "REMOTE_CONTROL_OF_OTHER_USERS",
    "WORD_CATEGORIES",
    "EmptyPasswordError",
    "InvalidUsernameError",
    "NoAccountError",
    "StartupUserUpdate",
    "UsernameTakenError",
    "ensure_first_account",
    "is_blank",
    "is_valid_username",
    "read_first_account",
    "update_first_account",
]
