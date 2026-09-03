#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The L3 differential harness: the same request to both servers, compared, and a report.

This is the command line
[conformance.md](../docs/compatibility/conformance.md) published before it was written - `--atrium`,
`--jellyfin`, `--surface`, `--report` - adopted rather than reinvented, because the harness was a
published interface before it was a program. `--identity`, `--fixture`, `--named` and
`--reference-url` are added beside them.

**A run that authenticates once measures one row of a two-row table, and its report says nothing
about the other.** Twelve of the twenty-three reads of the surface answer differently to a
restricted non-administrator, and two of them differ as *shorter lists* rather than as refusals -
a `200` that differs only in how many rows it holds
`[probe: tools/probe_restricted_surface.py, Jellyfin 10.11.11, 2026-09-01]`. Every probe written
before 2026-09-01 authenticated as an administrator, and an administrator lacks no permission, so
no measurement in this repository had ever been taken from a seat that could be refused anything
([010 spec section 3.9](../specs/010-conformance-harness/spec.md)). The identity is therefore the
**outermost** loop and never a flag somebody remembers: a run with one seat is a shorter loop over
the same code, and the report says out loud that it covered one.

**The report is the deliverable and not a pass/fail line, so it is written to say what it did not
ask.** A case that could not be issued, a seat that could not be made, a named comparison with no
runner: each is named, with the reason, and each keeps `is_clean()` false. *Outstanding is not
green* - a run that swept 59 endpoints and skipped nine named comparisons has proved that the
questions it asked have the same answers, which spec section 3.10 says is a smaller claim than it
sounds.

**The two-server guard reads the `Server` header and never `ProductName`.** Atrium answers
`ProductName: "Jellyfin Server"` on purpose (behaviours section 4.1), so `_probe.py`'s `connect`
- which is right for its own job, refusing an Emby - cannot tell this project's server from the
one it imitates. `Server` is `Atrium/<version>` here against the reference's `Kestrel`
`[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-28]`, and it is the one place
Principle X wins over Principle I.

**Three things this module refuses to do, each for a reason somebody paid for.**

*It does not proceed with fewer seats than it was asked for.* A seat that cannot be made is a
refusal, not a smaller run: silently continuing is how a harness passes green while proving
nothing, which is the characteristic failure 010's task list is ordered against. A run that
*wants* one identity asks for one and is reported as covering one (AC-14); a run that wanted two
and got one is a run that has to stop.

*It does not reuse a seat it finds.* The names are fixed on purpose - fixed is what lets the next
run recognise the wreckage of a killed one - and a seat already under one of them is either
another run in flight or that wreckage. Reusing it means measuring against a policy somebody else
set, so the pre-flight is a **precondition** and not a cleanup (AC-15, plan section 6.7).

*It does not promise a cleanup it fails to enforce.* On 2026-09-01 the reference server 009's
probes had run against still held **28 playlists** they had created, under names those probes
create them with: the cleanup was written down in every one of them and verified after none of
them. So the teardown here runs on the success path and on the exception path, it attempts every
seat even after one fails, and a leak on the success path is **raised** rather than logged.

Standard library only, on the Python 3.9 floor, like everything under tools/ (D-2).

Usage:
    python3 tools/differential.py --help
    python3 tools/differential.py --atrium http://localhost:8096 \\
        --jellyfin http://your-jellyfin:8096 --report reference/differential.md
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import importlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

# --------------------------------------------------------------------------------------------
# The three seats
# --------------------------------------------------------------------------------------------


class Role(Enum):
    """What a run may authenticate as (plan section 6.7).

    **The values are load-bearing strings and not labels.** `docs/compatibility/request-cases.yaml`
    names them in 84 cases and `tools/_allowlist.py`'s `ROLES` is the vocabulary that validates
    those, so a value that drifts here silently narrows every case that named the seat it can no
    longer resolve. `tests/conformance/test_differential.py` compares the two tuples for that
    reason.
    """

    ADMINISTRATOR = "administrator"
    RESTRICTED = "restricted"
    PLAYBACK_DENIED = "playback-denied"


#: The seats a run makes for itself. The administrator is not one of them: it is the account
#: `.env` points at, or the first user an instance's own setup wizard creates (plan section 6.5),
#: and in neither case did this module create it.
CREATED_ROLES: Tuple[Role, ...] = (Role.RESTRICTED, Role.PLAYBACK_DENIED)


#: **Fixed, and that is the property, not a convenience.** A random name would make every run
#: unable to recognise what an earlier killed run left behind, which is the same argument
#: 008 section 6.7 makes for sweeping a scratch root by a fixed label and the reason the
#: pre-flight can exist at all.
SEAT_NAME_PREFIX = "atrium-differential-"


def seat_name(role: Role) -> str:
    """The account name a created seat is made under. Never used for the administrator."""
    return SEAT_NAME_PREFIX + role.value


# --------------------------------------------------------------------------------------------
# The policies the two created seats carry
# --------------------------------------------------------------------------------------------

#: The library-access pair. `EnabledFolders` alone decides nothing while `EnableAllFolders` is
#: true `[spec: UserPolicy]`, so both move together - which is the shape
#: `tools/probe_restricted_surface.py` already uses to build the seat spec section 3.9 measured.
ENABLE_ALL_FOLDERS = "EnableAllFolders"
ENABLED_FOLDERS = "EnabledFolders"

#: **The three permissions a denied-playback seat has to deny, by name.**
#:
#: [behaviours section 2.21](../docs/compatibility/behaviours.md) measured what each one does, and
#: the answer decides the seat rather than decorating it: at negotiation the three are **one
#: gate** - `SupportsTranscoding` drops to false only when all three are denied, and any single
#: denial changes nothing - while at delivery two of them are read per stream, and only from a
#: video request. A seat denying one permission is therefore observably identical to a permitted
#: one on every negotiation both servers answer, which would make the named comparison that owns
#: this seat a comparison of two identical answers.
PLAYBACK_PROCESSING_PERMISSIONS: Tuple[str, ...] = (
    "EnableVideoPlaybackTranscoding",
    "EnableAudioPlaybackTranscoding",
    "EnablePlaybackRemuxing",
)

#: **The permission whose name says it is the one, and which no playback route consults.**
#: `EnableMediaPlayback` is read only by the item DTO's `PlayAccess` property and by the
#: remote-control `Play` command (behaviours section 2.21), so denying it produces a seat that
#: plays exactly as a permitted one does on both servers. It is named here, and left alone, so
#: that nobody reaches for it on the strength of its name.
NEGOTIATION_INERT_PERMISSION = "EnableMediaPlayback"


class SeatError(RuntimeError):
    """A run cannot be seated as it was asked to be. Always fatal, never downgraded to a warning."""


@dataclass(frozen=True)
class Identity:
    """One authenticated seat (plan section 5).

    `created_by_the_run` is a field of the identity and not of the run because it is what the
    teardown iterates: the administrator handed in from `.env` is somebody's real account and
    must survive the run that borrowed it, and everything this module made must not.
    """

    name: str  # Role.value
    token: str
    user_id: str
    created_by_the_run: bool

    @property
    def role(self) -> Role:
        return Role(self.name)


#: What `Roster` needs of a client, stated here because `tools/` has no package to put a protocol
#: in and because the tests drive it with a stub rather than a socket: `get(path, **params)`,
#: `post(path, body=...)`, `post_raw(path, body=...) -> (status, headers, bytes)` and
#: `delete_raw(path) -> (status, headers, bytes)`. `tools/_probe.py`'s `Server` satisfies it.
Directory = Any

#: How a created seat obtains its own token: username and password in, `(token, user_id)` out.
SignIn = Callable[[str, str], Tuple[str, str]]


def device_for(username: str) -> str:
    """The `DeviceId` one account's requests carry. One per account, never one per run."""
    return DEVICE_ID + "-" + hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]


def sign_in_against(base_url: str, timeout: int = 30) -> SignIn:
    """The real `SignIn`, authenticating a created seat against the server that holds it.

    **Through this module's own `Wire` since 010 T12, and not through `tools/_probe.py`'s
    `Server`.** The reference binds a token to the device that signed in, so every account has to
    sign in on a device of its own - and `Server` has one fixed `DeviceId` for every probe there
    is, which put both created seats on one device and revoked the first one's token when the
    second signed in. The client that signs a seat in is now the client that uses it, on the same
    device, which is one fewer thing that can differ between the two.
    """

    def sign_in(username: str, password: str) -> Tuple[str, str]:
        wire = Wire(base_url, timeout=timeout, device=device_for(username))
        body = json.dumps({"Username": username, "Pw": password}).encode("utf-8")
        answer = wire.request(
            "POST", "/Users/AuthenticateByName", body=body, content_type="application/json"
        )
        if answer.status != 200 or not isinstance(answer.body, dict):
            raise SeatError(
                f"{username} could not authenticate against {base_url}: {answer.status} "
                f"{answer.raw[:200]!r}"
            )
        return str(answer.body["AccessToken"]), str(answer.body["User"]["Id"])

    return sign_in


def existing_seats(directory: Directory, roles: Sequence[Role]) -> Dict[str, str]:
    """The seats this run would create that are already on the server, as name -> user id.

    The listing is asked for **bare**. `GET /Users` takes `isHidden` and `isDisabled` as
    *optional filters* `[spec: GetUsers]`, and a pre-flight that passed either would be blind to
    exactly the leftover most likely to exist - a seat some earlier run disabled instead of
    deleting.
    """
    wanted = {seat_name(role): role for role in roles if role in CREATED_ROLES}
    found: Dict[str, str] = {}
    for user in directory.get("/Users"):
        name = str(user.get("Name", ""))
        if name in wanted:
            found[name] = str(user.get("Id", ""))
    return found


#: The environment names a seat is handed in under, per side and per role. Printed by the refusal
#: above, so an operator meeting it is told what to set rather than what went wrong.
_HANDED_ENVIRONMENT_NAMES = (
    "ATRIUM_RESTRICTED_USERNAME/PASSWORD",
    "ATRIUM_PLAYBACK_DENIED_USERNAME/PASSWORD",
    "JELLYFIN_RESTRICTED_USERNAME/PASSWORD",
    "JELLYFIN_PLAYBACK_DENIED_USERNAME/PASSWORD",
)


def handed_seats(prefix: str, roles: Sequence[Role]) -> Dict[Role, Tuple[str, str]]:
    """The seats the environment provides for one side, by role.

    **A seat handed in is a seat this run does not own** - it is signed in as, used, and left
    exactly where it was, which is what the administrator has always been. The pair has to be
    complete: a username with no password is a seat that cannot authenticate, and silently
    dropping it would give the run one identity where it asked for two.
    """
    handed: Dict[Role, Tuple[str, str]] = {}
    for role in roles:
        if role not in CREATED_ROLES:
            continue
        stem = prefix + role.value.upper().replace("-", "_") + "_"
        username = os.environ.get(stem + "USERNAME", "")
        password = os.environ.get(stem + "PASSWORD", "")
        if username and password:
            handed[role] = (username, password)
        elif username or password:
            raise SeatError(
                f"{stem}USERNAME and {stem}PASSWORD are a pair and only one of them is set: a "
                "seat that cannot authenticate is not a seat, and a run that quietly dropped it "
                "would cover one identity where it was asked for two"
            )
    return handed


def preflight(directory: Directory, roles: Sequence[Role]) -> None:
    """Refuse the run if a seat it would create is already there (AC-15).

    A precondition and not a cleanup: this runs before anything is created, and it names what it
    found, because the operator's next action is to look at that account and decide whether a run
    is in flight or a killed one left it.
    """
    try:
        clashes = existing_seats(directory, roles)
    except WireError as failure:
        # **Measured on the first run of this module against a real Atrium (010 T12).** `GET
        # /Users` is not in `docs/compatibility/surface.yaml` and neither are the two routes a
        # seat is made with, so a server that implements the v1 surface and nothing else cannot
        # be asked to make one. That is Principle VI working, not a gap - and the answer is to
        # hand the seat in rather than to widen the surface.
        raise SeatError(
            f"this server cannot be asked for its accounts ({failure}), so the run cannot create "
            "the seats it needs there. Three routes make a seat - GET /Users, POST /Users/New "
            "and POST /Users/{userId}/Policy - and none of them is in the v1 surface, because no "
            "analysed client administers accounts (Principle VI). Provision the seat yourself "
            "and hand it in: " + ", ".join(sorted(_HANDED_ENVIRONMENT_NAMES)) + "."
        ) from failure
    if not clashes:
        return
    named = ", ".join(f"{name} ({user_id})" for name, user_id in sorted(clashes.items()))
    raise SeatError(
        f"a seat this run creates is already on the server: {named}. "
        "That is either another differential run in flight or the wreckage of one that was "
        "killed, and reusing it would measure against a policy somebody else set. Remove the "
        "account, or wait for the run that owns it, and start again."
    )


def restricted_policy(policy: Mapping[str, Any], library_id: str) -> Dict[str, Any]:
    """The restricted seat's policy: the account's own, narrowed to one library.

    **Read then mutate, never a fresh object.** `POST /Users/{userId}/Policy` takes a whole
    `UserPolicy`, of which only `AuthenticationProviderId` and `PasswordResetProviderId` are
    required `[spec: UpdateUserPolicy, UserPolicy]` - so a body naming the two folder fields is a
    complete policy in which every other property is whatever the absent value binds to, and the
    seat would differ from a stock account in ways nobody chose and the report could not explain.
    """
    narrowed = dict(policy)
    narrowed[ENABLE_ALL_FOLDERS] = False
    narrowed[ENABLED_FOLDERS] = [library_id]
    return narrowed


def playback_denied_policy(policy: Mapping[str, Any]) -> Dict[str, Any]:
    """The denied seat's policy: the account's own, with the three processing permissions denied.

    Its folders are **not** narrowed. The comparison this seat exists for is a delivery of a video
    item (behaviours section 2.21), so a seat that could not open one would answer the same
    refusal on both servers for the wrong reason - which is 006 T5's hostile-path test passing
    with the check deleted, in this feature's own shape.
    """
    denied = dict(policy)
    for permission in PLAYBACK_PROCESSING_PERMISSIONS:
        denied[permission] = False
    return denied


POLICY_OF: Dict[Role, Callable[[Mapping[str, Any], Optional[str]], Dict[str, Any]]] = {
    Role.RESTRICTED: lambda policy, library_id: restricted_policy(policy, str(library_id)),
    Role.PLAYBACK_DENIED: lambda policy, _library_id: playback_denied_policy(policy),
}


# --------------------------------------------------------------------------------------------
# The roster
# --------------------------------------------------------------------------------------------


class Roster:
    """The identities one run authenticates as: entered before the sweep, destroyed after it.

    A context manager, because the destruction is the invariant - the same reason
    `ReferenceInstance` is one (plan section 5). `__exit__` runs on the success path and on the
    exception path, it attempts every seat it made even after one attempt fails, and a seat left
    behind by a successful run is an error and not a note.

    The order is fixed and it is the order of `roles`, so that `names` is stable across runs and a
    report's coverage line can be diffed against the previous one.
    """

    def __init__(
        self,
        directory: Directory,
        administrator: Identity,
        roles: Sequence[Role],
        library_id: Optional[str] = None,
        sign_in: Optional[SignIn] = None,
        make_password: Optional[Callable[[], str]] = None,
        handed: Optional[Mapping[Role, Tuple[str, str]]] = None,
    ) -> None:
        if not roles:
            raise SeatError("a run authenticates as at least one identity, and none was asked for")
        if Role.ADMINISTRATOR not in roles:
            raise SeatError(
                "the administrator seat is what creates the others, so a roster without it "
                "cannot be built: pass Role.ADMINISTRATOR among the roles"
            )
        if administrator.name != Role.ADMINISTRATOR.value:
            raise SeatError(
                f"the administrator identity is named {administrator.name!r}, which is not "
                f"{Role.ADMINISTRATOR.value!r}"
            )
        seen: List[Role] = []
        for role in roles:
            if role not in seen:
                seen.append(role)
        self.roles: Tuple[Role, ...] = tuple(seen)
        self._directory = directory
        self._administrator = administrator
        self._library_id = library_id
        self._sign_in = sign_in
        self._make_password = make_password or (lambda: secrets.token_hex(16))
        #: Seats this roster signs in as rather than creating, by role. **Added by 010 T12, and it
        #: is a measurement rather than a convenience**: the first run of this module against a
        #: real Atrium refused at the pre-flight with `GET /Users -> 404`, because none of the
        #: three routes a seat is made with - `GET /Users`, `POST /Users/New`,
        #: `POST /Users/{userId}/Policy` - is in `docs/compatibility/surface.yaml`. They are not
        #: missing: Principle VI keeps an endpoint out until a client is measured calling it, and
        #: no analysed client administers accounts. So on a server that cannot make a seat the
        #: seat is **handed in**, exactly as the administrator always was, and
        #: `created_by_the_run` is `False` for it - which is what keeps the teardown away from an
        #: account this run did not create.
        self._handed: Dict[Role, Tuple[str, str]] = dict(handed or {})
        self._usernames: Dict[Role, str] = {}
        self._identities: Dict[Role, Identity] = {}
        # **Kept, and it is not a widening of `Identity`.** One request case sends a body that
        # *is* the seat's own credentials - `POST /Users/AuthenticateByName`, the second of the
        # eight `level: L3` rows - through the `<identity.password>` substitution T6 declared, and
        # the four fields of `Identity` cannot carry a password. The map is the roster's own and
        # never leaves it except through `credentials_for`; nothing prints it, and `Roster` has no
        # repr that could. `tools/_probe.py`'s `Server.password_used` keeps one for the same
        # reason: a measurement that needs to authenticate again needs the credential again.
        self._passwords: Dict[Role, str] = {}
        self._entered = False

    # -- the roster a case is resolved against ------------------------------------------------

    @property
    def names(self) -> Tuple[str, ...]:
        """What `RequestCase.identities_for` is handed (plan section 5).

        A tuple of role values, so a run with one identity is a **shorter loop** in T8 and never a
        different code path: the case decides which of the seats the run actually has it is
        meaningful for, and a roster of one narrows the answer instead of bypassing it.
        """
        return tuple(role.value for role in self.roles)

    def __getitem__(self, role: Role) -> Identity:
        return self._identities[role]

    def credentials_for(self, role: Role) -> Tuple[str, str]:
        """The username and password a case may substitute into its own body, or `("", "")`.

        Empty for the administrator, whose credentials this roster never saw: it is handed in
        (`created_by_the_run=False`), and a run that authenticated it by token has no password to
        give at all. A case that needs one and cannot have it is reported **unreachable with the
        reason**, which is the whole difference between a question this run did not ask and a
        question it answered.
        """
        if role not in self._passwords:
            return ("", "")
        return (self._usernames.get(role, seat_name(role)), self._passwords[role])

    def __iter__(self) -> Iterator[Identity]:
        return iter(self._identities[role] for role in self.roles)

    @property
    def creates(self) -> Tuple[Role, ...]:
        """The roles this roster makes accounts for: the created ones it was not handed."""
        return tuple(
            role for role in self.roles if role in CREATED_ROLES and role not in self._handed
        )

    @property
    def created(self) -> Tuple[Identity, ...]:
        """Everything the teardown owns, in creation order."""
        return tuple(
            self._identities[role]
            for role in self.roles
            if role in self._identities and self._identities[role].created_by_the_run
        )

    # -- lifecycle ----------------------------------------------------------------------------

    def __enter__(self) -> Roster:
        self._check_askable()
        # **Only over the roles this roster creates.** A pre-flight is a check that this run is
        # not about to reuse an account somebody else made, and a seat handed in *is* an account
        # somebody else made, deliberately - so asking `GET /Users` for it would refuse the run
        # for the thing the operator just supplied, on a server that has no such route anyway.
        if self.creates:
            preflight(self._directory, self.creates)
        self._identities[Role.ADMINISTRATOR] = self._administrator
        self._entered = True
        try:
            for role in self.roles:
                if role in self._handed:
                    self._identities[role] = self._adopt(role)
                elif role in CREATED_ROLES:
                    self._identities[role] = self._create(role)
        except BaseException:
            # A half-built roster is not a smaller roster. Whatever was made before the failure is
            # destroyed here, so the refusal that reaches the caller does not also leave an
            # account behind for the next run's pre-flight to refuse.
            self._destroy(failed=True)
            raise
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self._destroy(failed=exc_type is not None)

    def _check_askable(self) -> None:
        """Refuse before anything is contacted, when a seat asked for cannot be made at all.

        **The refusal is the mechanism, not a fallback to a smaller run.** A roster that quietly
        dropped the seat it could not build would sweep as an administrator and report a surface
        of which 12 of 23 reads answer differently to somebody else - green, and about one row of
        a two-row table.
        """
        if Role.RESTRICTED in self.creates and not self._library_id:
            raise SeatError(
                "the restricted seat is a reader narrower than the library, so it needs the "
                "identifier of the one library it may open, and none was given. A run that "
                "cannot seat an identity it was asked for stops rather than proceeding with "
                "fewer"
            )
        if self._sign_in is None and any(role in CREATED_ROLES for role in self.roles):
            raise SeatError(
                "a created seat has to authenticate as itself, and the roster was given no way "
                "to sign one in. A run that cannot seat an identity it was asked for stops "
                "rather than proceeding with fewer"
            )

    def _adopt(self, role: Role) -> Identity:
        """Sign in as a seat somebody else provisioned, and never own it.

        The account, its policy and its lifetime are the operator's; what this run does with it is
        exactly what it does with the administrator - authenticate, use, and leave alone. A run
        that deleted a handed seat would be deleting somebody's account, which is why
        `created_by_the_run` decides the teardown and not the role.
        """
        username, password = self._handed[role]
        sign_in = self._sign_in
        if sign_in is None:
            raise SeatError(f"the {role.value} seat was handed in with no way to sign it in")
        token, user_id = sign_in(username, password)
        self._passwords[role] = password
        self._usernames[role] = username
        return Identity(name=role.value, token=token, user_id=user_id, created_by_the_run=False)

    def _create(self, role: Role) -> Identity:
        name = seat_name(role)
        self._usernames[role] = name
        password = self._make_password()
        made = self._directory.post("/Users/New", body={"Name": name, "Password": password})
        user_id = str(made["Id"])
        self._passwords[role] = password

        # Everything after the account exists can fail, and a failure past this line leaves an
        # account nobody asked for - so the seat is registered as created before its policy is
        # written, and the teardown of `__enter__` takes it.
        self._identities[role] = Identity(
            name=role.value, token="", user_id=user_id, created_by_the_run=True
        )

        current = self._directory.get("/Users/" + user_id).get("Policy", {})
        policy = POLICY_OF[role](current, self._library_id)
        status, _headers, body = self._directory.post_raw(
            "/Users/" + user_id + "/Policy", body=policy
        )
        if status not in (200, 204):
            raise SeatError(
                f"the {role.value} seat could not be given its policy: {status} {body[:200]!r}. "
                "A seat whose policy did not take is an ordinary account, and sweeping as one "
                "would report parity it did not measure"
            )

        sign_in = self._sign_in
        if sign_in is None:  # _check_askable refuses before anything is made; belt and braces
            raise SeatError(f"the {role.value} seat has no way to authenticate as itself")
        token, signed_in_id = sign_in(name, password)
        if signed_in_id != user_id:
            raise SeatError(
                f"the {role.value} seat authenticated as {signed_in_id!r} and was created as "
                f"{user_id!r}: a second account under the same name is the one case where "
                "measuring on would measure the wrong seat"
            )
        return Identity(name=role.value, token=token, user_id=user_id, created_by_the_run=True)

    def _destroy(self, failed: bool) -> None:
        """Delete every seat this run created, whatever happened, and say so when one survives."""
        leaked: List[str] = []
        for identity in reversed(self.created):
            self._identities.pop(identity.role, None)
            self._passwords.pop(identity.role, None)
            try:
                status, _headers, body = self._directory.delete_raw("/Users/" + identity.user_id)
            except Exception as failure:  # a teardown reports what it could not do
                leaked.append(f"{seat_name(identity.role)} ({identity.user_id}): {failure}")
                continue
            if status not in (200, 204, 404):
                leaked.append(
                    f"{seat_name(identity.role)} ({identity.user_id}): {status} {body[:120]!r}"
                )
        if not leaked:
            return
        message = (
            "the run created seats it could not destroy, and they are still on the server: "
            + "; ".join(leaked)
            + ". Delete them before the next run, whose pre-flight will refuse to start "
            "while they are there."
        )
        if failed:
            # Never mask the failure that is already on its way out. The leak is printed rather
            # than raised, because a teardown that replaces the real exception with its own hides
            # the reason the run stopped.
            print("differential.py: " + message, file=sys.stderr)
            return
        raise SeatError(message)


# --------------------------------------------------------------------------------------------
# The two modules this one reads, imported on first use and never at module scope
# --------------------------------------------------------------------------------------------
#
# `tools/` is a directory of standalone programs and not an importable package, so a sibling is
# reached through the directory this file sits in. Importing on first use keeps the property T7
# established and the CI job depends on: loading this module - or asking it for `--help` - costs
# no socket, no credential and no file read.

_ENGINE: Any = None
_REGISTERS: Any = None


def _sibling(module: str) -> Any:
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    return importlib.import_module(module)


def engine() -> Any:
    """`tools/_differential.py`: the pure comparison engine (T2, T4)."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _sibling("_differential")
    return _ENGINE


def registers() -> Any:
    """`tools/_allowlist.py`: the allowlist, the named comparisons and the request cases."""
    global _REGISTERS
    if _REGISTERS is None:
        _REGISTERS = _sibling("_allowlist")
    return _REGISTERS


# --------------------------------------------------------------------------------------------
# The two-server guard
# --------------------------------------------------------------------------------------------

#: The header that tells the two servers apart, and the only one that can.
SERVER_HEADER = "Server"

#: What this server says it is `compat/middleware.py`'s `SERVER_VALUE`, and what the reference
#: says instead is `Kestrel` `[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-28]`.
ATRIUM_SERVER_PREFIX = "Atrium/"


class GuardError(RuntimeError):
    """The run was pointed at the wrong pair of servers. Refused before anything is compared."""


def header_value(headers: Mapping[str, str], name: str) -> str:
    """One header by name, case-insensitively, or `""`. HTTP says the names are."""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return ""


def looks_like_atrium(headers: Mapping[str, str]) -> bool:
    """Whether the response came from this project's own server."""
    return header_value(headers, SERVER_HEADER).startswith(ATRIUM_SERVER_PREFIX)


def product_name(info: Mapping[str, Any]) -> str:
    """`ProductName` from `/System/Info/Public` - **the guard that cannot work**, kept visible.

    `tools/_probe.py`'s `connect` refuses a server whose `ProductName` does not name Jellyfin,
    which is right for its own job: the near miss it exists to catch is an Emby. It is the wrong
    guard for this one, because Atrium answers `"Jellyfin Server"` there **on purpose**
    (reference-target section 4, behaviours section 4.1) - so the obvious check passes a run
    pointed at two Atriums, which would compare this server with itself and report parity.
    `tests/conformance/test_differential.py` asserts exactly that: the pair the `Server` header
    refuses is a pair `ProductName` admits.
    """
    return str(info.get("ProductName", ""))


def check_two_servers(
    atrium_headers: Mapping[str, str], reference_headers: Mapping[str, str]
) -> None:
    """Refuse a run that is not pointed at one Atrium and one reference (plan section 6.12).

    Both directions are refused, because both produce a report that means nothing: two references
    compare the reference with itself, and two Atriums compare this project with itself - which is
    008 T16's finding, where *a passing test compared Atrium against itself while the contract was
    broken*.
    """
    ours = header_value(atrium_headers, SERVER_HEADER) or "no Server header at all"
    theirs = header_value(reference_headers, SERVER_HEADER) or "no Server header at all"
    if not looks_like_atrium(atrium_headers):
        raise GuardError(
            f"--atrium answers {SERVER_HEADER}: {ours!r}, which does not start with "
            f"{ATRIUM_SERVER_PREFIX!r}. That is not this project's server, and a sweep of two "
            "references would report parity about nothing. ProductName cannot be asked instead: "
            "Atrium answers 'Jellyfin Server' there on purpose (behaviours 4.1)"
        )
    if looks_like_atrium(reference_headers):
        raise GuardError(
            f"--jellyfin answers {SERVER_HEADER}: {theirs!r}, which is an Atrium and not the "
            "reference. A differential of this server against itself reports parity it never "
            "measured - and ProductName would not have caught it, because Atrium answers "
            "'Jellyfin Server' there on purpose (behaviours 4.1)"
        )


# --------------------------------------------------------------------------------------------
# The wire
# --------------------------------------------------------------------------------------------

#: What this harness calls itself on the wire. Distinct from `tools/_probe.py`'s `atrium-probe`
#: so that the ignored-parameter report D-5 adds - parameter, endpoint, count and **client** -
#: can tell a sweep's request from a probe's.
#: The one endpoint of the surface whose *effect* is on the caller rather than on the server's
#: content: it mints a session. Named here because the issuer has to give it a device of its own.
LOGIN_ENDPOINT = "POST /Users/AuthenticateByName"

CLIENT = "atrium-differential"
DEVICE_ID = "atrium-differential-0000"
CLIENT_VERSION = "0.1"


class WireError(RuntimeError):
    """A request could not be made at all. An inability to look, never a finding."""


#: What may stand unescaped in a query string, per RFC 3986 - the sub-delimiters, the two
#: separators, and `%` so that a case which already wrote an escape is not escaped twice.
_QUERY_SAFE = "/?:@!$&'()*+,;=%~-._"


def encode_query(query: str) -> str:
    """A request case's query, made legal to put in a request line.

    **Measured on the first live run of this module (010 T12).** `request-cases.yaml` writes what
    a client sends - `searchTerm=The Planted Poster`, `SortBy=ProductionYear,PremiereDate` - and
    `http.client` refuses a target carrying a space outright, so every case with one was
    unissuable and the run stopped before it compared anything. The stub wire the suite drives
    never built a target, which is why nothing had noticed.

    Percent-encoding rather than a re-encode through `parse_qsl`: the case is the request, and a
    round trip through a parser would decide the order of the parameters, the spelling of an empty
    value and whether a space becomes `+` or `%20` - three things a case is entitled to state.
    """
    return urllib.parse.quote(query, safe=_QUERY_SAFE)


class Wire:
    """One server, one seat, and **exactly the request a case declares**.

    Not `tools/_probe.py`'s `Server`, and the reason is measured rather than stylistic:
    `urllib.request` inserts `Content-type: application/x-www-form-urlencoded` into any request
    that carries a body and does not name one, in `AbstractHTTPHandler.do_request_`. So a client
    built on `urllib` **cannot send a body with no content type at all** - which is one of the two
    rows the named-comparison register calls *"here to be recognised, not discovered"*
    (`body-with-no-content-type`) and four request cases T6 wrote for it. `http.client` sends the
    headers it is given and nothing else, which is what those five rows need.

    A connection per request, deliberately: the sweep asks the two servers back to back per case
    (plan section 6.1) and a pooled connection would be one more thing that differs between them.
    """

    def __init__(
        self, base_url: str, token: str = "", timeout: int = 30, device: str = DEVICE_ID
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url if "://" in base_url else "http://" + base_url)
        self.base_url = base_url.rstrip("/")
        self.scheme = parsed.scheme or "http"
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port
        self.prefix = parsed.path.rstrip("/")
        self.token = token
        self.timeout = timeout
        #: **One device per account, and it is a measurement rather than tidiness.** The reference
        #: binds a token to the device that signed in: authenticating a second account under the
        #: same `DeviceId` logs the first one out, and its token then answers `401`. Measured on
        #: the first live run of this module (010 T12) - the seats were created, the sweep signed
        #: them in, and the teardown could not delete them because the administrator's own token
        #: had been revoked by its second seat's sign-in.
        self.device = device

    def as_seat(self, token: str, device: str = "") -> Wire:
        """The same server, held by another seat. One `Wire`, and one **device**, per identity."""
        return Wire(self.base_url, token=token, timeout=self.timeout, device=device or self.device)

    def request(
        self,
        method: str,
        path: str,
        query: str = "",
        body: Optional[bytes] = None,
        content_type: str = "",
    ) -> Any:
        """Issue one request and decode the answer into the engine's `Response`.

        The body is sent **verbatim**: a case whose body is not JSON is how behaviours 1.11's
        `"$"` message is asked for at all, and a JSON encoder would turn it into a valid document.
        """
        target = self.prefix + path + (("?" + encode_query(query)) if query else "")
        headers = {
            "Accept": "application/json",
            "X-Emby-Authorization": (
                f'MediaBrowser Client="{CLIENT}", Device="{CLIENT}", '
                f'DeviceId="{self.device}", Version="{CLIENT_VERSION}"'
            ),
        }
        if self.token:
            headers["X-Emby-Token"] = self.token
        if content_type:
            headers["Content-Type"] = content_type
        connection: Any
        if self.scheme == "https":
            connection = http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout)
        else:
            connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            connection.request(method, target, body=body, headers=headers)
            answer = connection.getresponse()
            payload = answer.read()
            received = dict(answer.getheaders())
            status = answer.status
        except OSError as failure:
            raise WireError(f"{method} {target} against {self.base_url}: {failure}") from failure
        finally:
            connection.close()
        return decode(status, received, payload)


def decode(status: int, headers: Mapping[str, str], payload: bytes) -> Any:
    """One answer, as the engine's `Response`: parsed where it is JSON, bytes where it is not.

    `body` stays `None` for a delivery response, which is what tells the comparison it is looking
    at bytes - the engine never compares `raw`, because spec section 6 declines to byte-compare
    produced media and three named comparisons exist precisely because their difference is there.
    """
    body: Any = None
    if payload and "json" in header_value(headers, "Content-Type").lower():
        try:
            body = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            body = None
    return engine().Response(status=status, headers=dict(headers), body=body, raw=payload)


class WireDirectory:
    """The four calls `Roster` makes of a client, over a `Wire` (plan section 6.7).

    `Roster` was written against a client rather than a base URL so the suite could drive it with
    a stub; this is the other half of that, and it is the whole of what a real run substitutes.
    """

    def __init__(self, wire: Wire) -> None:
        self.wire = wire

    @staticmethod
    def _query(params: Mapping[str, Any]) -> str:
        clean = {key: value for key, value in params.items() if value is not None}
        return urllib.parse.urlencode(clean, doseq=True) if clean else ""

    def get(self, path: str, **params: Any) -> Any:
        answer = self.wire.request("GET", path, query=self._query(params))
        if answer.status >= 400:
            raise WireError(f"GET {path} -> {answer.status} {answer.raw[:200]!r}")
        return answer.body

    def post(self, path: str, body: Any = None, **params: Any) -> Any:
        status, _headers, payload = self.post_raw(path, body=body, **params)
        if status >= 400:
            raise WireError(f"POST {path} -> {status} {payload[:200]!r}")
        return json.loads(payload) if payload else None

    def post_raw(self, path: str, body: Any = None, **params: Any) -> Tuple[int, Any, bytes]:
        encoded = json.dumps(body).encode("utf-8") if body is not None else None
        answer = self.wire.request(
            "POST",
            path,
            query=self._query(params),
            body=encoded,
            content_type="application/json" if encoded is not None else "",
        )
        return answer.status, answer.headers, answer.raw

    def delete_raw(self, path: str, **params: Any) -> Tuple[int, Any, bytes]:
        answer = self.wire.request("DELETE", path, query=self._query(params))
        return answer.status, answer.headers, answer.raw


def authenticate(wire: Wire, username: str, password: str, token: str) -> Identity:
    """The administrator seat on one server: a token it was given, or one it signs in for.

    Handed in and never created, which is what `created_by_the_run=False` is for: it is somebody's
    real account on the reference and the only thing keeping the teardown away from it.
    """
    if token:
        wire.token = token
        me = wire.request("GET", "/Users/Me")
        if me.status != 200 or not isinstance(me.body, dict):
            raise GuardError(
                f"the token given for {wire.base_url} does not authenticate: "
                f"GET /Users/Me answered {me.status}"
            )
        return Identity(
            name=Role.ADMINISTRATOR.value,
            token=token,
            user_id=str(me.body["Id"]),
            created_by_the_run=False,
        )
    if not username:
        raise GuardError(f"no credentials for {wire.base_url}: pass a username, or a token")
    body = json.dumps({"Username": username, "Pw": password}).encode("utf-8")
    answer = wire.request(
        "POST", "/Users/AuthenticateByName", body=body, content_type="application/json"
    )
    if answer.status != 200 or not isinstance(answer.body, dict):
        raise GuardError(
            f"{username} could not authenticate against {wire.base_url}: {answer.status}"
        )
    wire.token = str(answer.body["AccessToken"])
    return Identity(
        name=Role.ADMINISTRATOR.value,
        token=wire.token,
        user_id=str(answer.body["User"]["Id"]),
        created_by_the_run=False,
    )


def movies_library_id(directory: Any, user_id: str) -> str:
    """The one library a restricted seat may open, picked the way the probe already picks it.

    `tools/probe_restricted_surface.py` narrows its throwaway account to the `movies` view and
    refuses when there is none, because the measurement needs one item the seat may open and one
    it may not. The same choice here, for the same reason, and the same refusal.
    """
    views = directory.get("/UserViews", userId=user_id) or {}
    movies = [view for view in views.get("Items", []) if view.get("CollectionType") == "movies"]
    for view in movies:
        # **And it has to hold something, which 010 T12 found the hard way.** The composed fixture
        # has three `movies` libraries and one of them is deliberately empty (behaviours 5.7's
        # named comparison), so taking the first one narrowed the reader to a library with nothing
        # in it - a seat that can open nothing, which is exactly the refusal for the wrong reason
        # this function was written to avoid.
        listed = directory.get(
            "/Items", userId=user_id, parentId=str(view["Id"]), recursive="true", limit=1
        )
        if isinstance(listed, dict) and listed.get("Items"):
            return str(view["Id"])
    raise SeatError(
        "no movies library with anything in it on this server to restrict the created seat to, "
        "and a seat narrowed to nothing is not a narrower reader - it is an account that can "
        "open nothing, which "
        "answers a refusal on both servers for the wrong reason"
    )


# --------------------------------------------------------------------------------------------
# The surface
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Endpoint:
    """One row of `surface.yaml`, with the conformance level it **declares**.

    The level is carried because nothing has ever checked that one is reached: the surface
    validator checks only that the value is one of `L0..L3`, and the route test reads `feature`
    and `consumers`. The eight `level: L3` rows are the ones this program is the only thing that
    can pay for, so the report prints the declared level beside what the run actually compared.
    """

    method: str
    path: str
    level: str
    feature: str

    @property
    def key(self) -> str:
        """`"METHOD /path"`, which is how the three registers spell an endpoint."""
        return self.method + " " + self.path


def load_endpoints(path: Path) -> Tuple[Endpoint, ...]:
    """Read `surface.yaml` through the surface validator's own parser, never a second one."""
    parse_surface = _sibling("extract_v1_surface").parse_surface
    _reference, rows = parse_surface(Path(path).read_text(encoding="utf-8"))
    return tuple(
        Endpoint(
            method=str(row.get("method", "")),
            path=str(row.get("path", "")),
            level=str(row.get("level", "")),
            feature=str(row.get("feature", "")),
        )
        for row in rows
    )


# --------------------------------------------------------------------------------------------
# What a run has, which is what decides what it can ask
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Inputs:
    """The three things a `needs` token asks about, and the one flag that narrows the register.

    A run reports what it covered rather than what exists (AC-14 generalised to inputs, plan
    section 6.11): a machine with a reference instance gains the fixture rows, a machine with only
    a reachable Jellyfin gains the sweep, and each says which it was.
    """

    roles: Tuple[str, ...] = ()
    instance_url: str = ""
    fixture_asked: bool = False
    named_selected: Optional[Tuple[str, ...]] = None
    #: `--only-named`: attempt the named comparisons and **not** the sweep. Every declared case is
    #: then reported unasked with that reason and the run is not clean, which is the honest shape:
    #: it is a way to re-run one comparison without re-issuing every case, not a smaller run.
    only_named: bool = False
    #: Why this run has no instance, in the words of the thing that could not make one - the
    #: runtime is absent, the image would not pull, the wizard refused, the scan timed out. T9
    #: added it because *"outstanding"* with a generic reason is a skip wearing a longer word,
    #: and the four failures of plan section 7 are four different things to do next.
    instance_reason: str = ""


#: What each `needs` token of the two registers asks of a run, and what answers it. The tokens are
#: `_allowlist.NEEDS`; this is the only place that decides whether one is met.
#:
#: `rescan` and `wait` resolve to the **instance** and not to a capability of the harness, and
#: that is spec section 3.10's own reading rather than a convenience: a rescan is a write to a
#: library, and the paused-session reading is *"a write held open for ten minutes, which is the
#: one thing an operator's server must not be asked for"*. `bytes`, `twice` and `latency` need
#: nothing a run does not already have - they describe what the runner does, not what it needs.
NEEDS_THE_INSTANCE = ("fixture", "rescan", "wait")


def unmet_need(need: str, inputs: Inputs) -> str:
    """Why this run cannot meet `need`, or `""` when it can. Never a silent skip."""
    if need.startswith("identity:"):
        role = need.split(":", 1)[1]
        if role in inputs.roles:
            return ""
        return f"this run has no {role} seat, and the comparison is only visible from one"
    if need in NEEDS_THE_INSTANCE:
        # One sentence for all three tokens, because one absence blocks them all and a row that
        # declares two of them has one problem and not two.
        if inputs.instance_url:
            return ""
        if not inputs.fixture_asked:
            return (
                "it needs a reference instance over this repository's own fixture, and --fixture "
                "was not asked for"
            )
        head = "it needs a reference instance over this repository's own fixture, and none was "
        if inputs.instance_reason:
            return head + "available: " + inputs.instance_reason
        return (
            head + "stood up: --reference-url named none, and --fixture-root named no tree for "
            "this run to stand one up over"
        )
    return ""


def unmet_needs(needs: Sequence[str], inputs: Inputs) -> Tuple[str, ...]:
    """Every reason this run cannot ask for something, in the order the register declares them.

    Distinct reasons only: two tokens of one row can be blocked by one absence - `fixture` and
    `rescan` both want the instance - and a report that said it twice would read like two problems.
    """
    reasons: List[str] = []
    for need in needs:
        reason = unmet_need(need, inputs)
        if reason and reason not in reasons:
            reasons.append(reason)
    return tuple(reasons)


# --------------------------------------------------------------------------------------------
# Issuing one case
# --------------------------------------------------------------------------------------------


class UnreachableError(Exception):
    """A declared case this run cannot issue, with the reason. Reported, never skipped."""


#: How deep an anchor may reach through other cases before the run calls it a cycle. Three is one
#: more than anything the register declares, and the limit exists so a mistake in a file is a
#: named failure rather than a recursion this program dies of.
ANCHOR_DEPTH = 3


@dataclass(frozen=True)
class Seat:
    """One role, and the **two accounts** behind it - one per server.

    Plan section 5 gives the run loop one `Identity` per iteration, which is one account; the two
    servers do not share accounts, so a role is two of them and the loop's unit is the role. It
    matters beyond bookkeeping: the restricted seat is created on **each** side, narrowed to that
    side's own movies library, and destroyed by that side's own roster.
    """

    role: str
    atrium: Identity
    reference: Identity
    atrium_credentials: Tuple[str, str] = ("", "")
    reference_credentials: Tuple[str, str] = ("", "")

    def identity(self, side: str) -> Identity:
        return self.atrium if side == "atrium" else self.reference

    def credentials(self, side: str) -> Tuple[str, str]:
        return self.atrium_credentials if side == "atrium" else self.reference_credentials


def substitute(text: str, seat: Seat, side: str) -> str:
    """Fill `<identity.username>`, `<identity.password>` and `<identity.user_id>` for one side.

    The three are T6's whole substitution vocabulary, and they exist because plan section 6.1.1
    says `userId` *"is not an anchor: it is the identity's own"* and gives no way to write that
    down - and because `POST /Users/AuthenticateByName`'s body **is** the seat's own credentials,
    which no anchor can supply.
    """
    if "<" not in text:
        return text
    username, password = seat.credentials(side)
    identity = seat.identity(side)
    values = {
        "identity.username": username,
        "identity.password": password,
        "identity.user_id": identity.user_id,
    }
    for token, value in values.items():
        placeholder = "<" + token + ">"
        if placeholder in text:
            if not value:
                raise UnreachableError(
                    f"the case substitutes {placeholder} and this run has no value for it on the "
                    f"{side}: the administrator's credentials are the operator's own, and a run "
                    "that authenticated by token never saw a password"
                )
            text = text.replace(placeholder, value)
    return text


def pointer_into(document: Any, pointer: str) -> Any:
    """RFC 6901, in the two escapes it defines. Raises `Unreachable` rather than guessing."""
    current = document
    if pointer in ("", "/"):
        return current
    for segment in pointer.lstrip("/").split("/"):
        key = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if key not in current:
                raise UnreachableError(f"the response carries nothing at {pointer!r}")
            current = current[key]
        elif isinstance(current, list):
            if not key.isdigit() or int(key) >= len(current):
                raise UnreachableError(f"the response carries nothing at {pointer!r}")
            current = current[int(key)]
        else:
            raise UnreachableError(f"the response carries nothing at {pointer!r}")
    return current


def rows_of(body: Any) -> List[Any]:
    """The rows of a listing, whether it came in an envelope or as a bare array."""
    if isinstance(body, dict):
        rows = body.get("Items")
        return list(rows) if isinstance(rows, list) else []
    return list(body) if isinstance(body, list) else []


class Issuer:
    """Issues a case against one server as one seat, resolving its anchors first.

    The cache is per (side, role) and per case, because an anchor over `/Items` resolves to a
    different row for a restricted seat than for an administrator - that is the 12-of-23 finding
    spec section 3.9 measured, and a cache shared across seats would quietly compare the
    administrator's row while claiming to be the other seat.
    """

    def __init__(self, side: str, wires: Mapping[str, Wire], cases: Sequence[Any]) -> None:
        self.side = side
        self.wires = wires
        self.cases = cases
        self._answers: Dict[Tuple[str, str], Any] = {}

    def case_named(self, endpoint: str, case_id: str) -> Any:
        for case in self.cases:
            if case.endpoint == endpoint and case.id == case_id:
                return case
        raise UnreachableError(f"no case {case_id!r} is declared for {endpoint!r}")

    def issue(self, case: Any, seat: Seat, depth: int = 0) -> Any:
        """One request, or `Unreachable` with the reason it could not be made."""
        wire = self.wires.get(seat.role)
        if wire is None:
            raise UnreachableError(f"this run has no {seat.role} seat on the {self.side}")
        if case.endpoint == LOGIN_ENDPOINT:
            # **A login is the one case that changes the session it is sent on.** The reference
            # binds a token to a device and mints a fresh one for every authentication on that
            # device, so sweeping `POST /Users/AuthenticateByName` as a seat, on that seat's own
            # device, revokes the token the rest of the run is holding - measured on the first
            # live run (010 T12), where the sweep completed and the teardown then answered `401`
            # on every account it had created. The case is issued on a device of its own, which
            # changes nothing about the request under comparison.
            wire = wire.as_seat(
                wire.token, device=device_for(seat.credentials(self.side)[0] + "-login")
            )
        path = self.fill(case, seat, depth)
        query = substitute(case.query, seat, self.side)
        body = None
        if case.has_body:
            body = substitute(case.body, seat, self.side).encode("utf-8")
        content_type = "" if case.content_type == registers().NONE else case.content_type
        return wire.request(case.method, path, query=query, body=body, content_type=content_type)

    def answer_of(self, endpoint: str, case_id: str, seat: Seat, depth: int) -> Any:
        """A case's response, cached: an anchor over a listing asks for it once per seat."""
        key = (seat.role, endpoint + "#" + case_id)
        if key not in self._answers:
            target = self.case_named(endpoint, case_id)
            if depth >= ANCHOR_DEPTH:
                raise UnreachableError(
                    f"the anchor chain through {endpoint}#{case_id} is more than "
                    f"{ANCHOR_DEPTH} deep, which is a cycle in request-cases.yaml"
                )
            self._answers[key] = self.issue(target, seat, depth=depth + 1)
        return self._answers[key]

    def fill(self, case: Any, seat: Seat, depth: int = 0) -> str:
        """The path with every parameter filled, against **this** server (plan section 6.1.1)."""
        path = case.path
        for parameter in re.findall(r"\{(\w+)\}", path):
            path = path.replace("{" + parameter + "}", self.value_for(parameter, case, seat, depth))
        return path

    def value_for(self, parameter: str, case: Any, seat: Seat, depth: int) -> str:
        if parameter == registers().IDENTITY_PATH_PARAMETER:
            return seat.identity(self.side).user_id
        for anchor in case.anchors:
            if anchor.parameter != parameter:
                continue
            return self.resolve(anchor, seat, depth)
        raise UnreachableError(
            f"{{{parameter}}} has no anchor in request-cases.yaml, so this case cannot name an "
            "item on either server"
        )

    def resolve(self, anchor: Any, seat: Seat, depth: int) -> str:
        """One anchor, in the three kinds T6 found where plan section 6.1.1 described one."""
        if anchor.kind == "literal":
            return anchor.at
        answer = self.answer_of(anchor.endpoint, anchor.case, seat, depth)
        if answer.status >= 400 or answer.body is None:
            raise UnreachableError(
                f"the anchor listing {anchor.endpoint}#{anchor.case} answered {answer.status} "
                f"on the {self.side}, so the row it names does not exist there"
            )
        if anchor.kind == "response":
            return str(pointer_into(answer.body, anchor.at))
        rows = rows_of(answer.body)
        position = int(anchor.at)
        if position >= len(rows):
            raise UnreachableError(
                f"the anchor listing {anchor.endpoint}#{anchor.case} holds {len(rows)} rows on "
                f"the {self.side} and the anchor names position {position}"
            )
        row = rows[position]
        if not isinstance(row, dict) or "Id" not in row:
            raise UnreachableError(
                f"row {position} of {anchor.endpoint}#{anchor.case} carries no Id on the "
                f"{self.side}"
            )
        return str(row["Id"])


# --------------------------------------------------------------------------------------------
# One comparison
# --------------------------------------------------------------------------------------------

#: The one header compared on a response that carries a body this program can read.
#:
#: **Headers on every response would report a `Content-Length` on every one of them**, since the
#: two bodies legitimately differ in length wherever an identifier does - which is the cascade
#: spec section 6 calls crying wolf, arriving through the door the `LENGTH` class was shut on.
#: Spec section 3.2 asks for headers *"on the delivery routes, where `Content-Length`,
#: `Accept-Ranges`, `Content-Range` and `Content-Type` are the contract"*, and a delivery route is
#: recognised here by its answer rather than by a list of paths somebody maintains: a response
#: whose body is not JSON. On the others the content type is still compared, because 008 T16's
#: finding was exactly a declared content type that serialised differently.
JSON_HEADERS_COMPARED = ("Content-Type",)


def header_view(response: Any, everything: bool) -> Any:
    """What the header comparison sees: everything on a delivery route, one name elsewhere."""
    if everything:
        return response
    kept = {
        name: value
        for name, value in response.headers.items()
        if name.lower() in {wanted.lower() for wanted in JSON_HEADERS_COMPARED}
    }
    return engine().Response(
        status=response.status, headers=kept, body=response.body, raw=response.raw
    )


def compare_pair(ours: Any, theirs: Any, rules: Any) -> Tuple[Any, ...]:
    """Body and headers, in one tuple of findings, under one rule set."""
    findings = list(engine().compare(ours, theirs, rules))
    if ours.status != theirs.status:
        # The engine already said the bodies were not compared; comparing the headers of a `404`
        # against a `200` adds noise to a finding that already explains itself.
        return tuple(findings)
    delivery = ours.body is None or theirs.body is None
    findings.extend(
        engine().compare_headers(header_view(ours, delivery), header_view(theirs, delivery), rules)
    )
    return tuple(findings)


@dataclass(frozen=True)
class Comparison:
    """What one (endpoint, case, identity) produced - including nothing at all, and including why.

    `unreachable` is the field that keeps this feature honest. A case that could not be issued is
    not a case that passed, and a report that dropped it would be reporting the absence of a
    question rather than the presence of an answer.
    """

    endpoint: str
    level: str
    case: str
    identity: str
    differences: Tuple[Any, ...] = ()
    attributed: Tuple[Tuple[Any, str], ...] = ()
    excused: int = 0
    unreachable: str = ""

    @property
    def ran(self) -> bool:
        return not self.unreachable

    @property
    def identical(self) -> bool:
        return self.ran and not self.differences and not self.attributed


def attribute(finding: Any, entries: Sequence[Any]) -> str:
    """The written argument that already covers this finding, or `""`.

    **Exactly one shape qualifies, and the narrowness is the safeguard.** A `LENGTH` on an array
    the allowlist marks `drawn` or `unordered`, whose `because` is a **behaviours section** rather
    than a derivation class, is a difference somebody has already triaged: spec section 3.4's
    *Diverge* row is *"a behaviours.md entry with the argument, and an allowlist row"*, and both
    exist. `/Items/{itemId}/Similar` is the case that forces it - the reference answers `limit + 4`
    rows on a movie seed where Atrium answers exactly `limit`, so that count differs on **every**
    run (behaviours 3.24), and T4 decided deliberately that it stays compared and permanently
    reported rather than excused.

    So the count is reported, every run, with the argument printed beside it - which is what T4
    asked for, *"a reader who does not see behaviours 3.24 next to it will try to fix it"* - and
    it does not by itself keep the run from being clean. Nothing else is attributed: a
    `MISSING_KEY` inside a drawn array is the finding AC-17 exists for, and no allowlist row makes
    it somebody's decision.
    """
    if finding.klass is not engine().Class.LENGTH:
        return ""
    for entry in entries:
        if entry.kind not in ("drawn", "unordered"):
            continue
        if entry.pointer != finding.pointer:
            continue
        if entry.is_derivation:
            # A derivation class is a fact about two installations, and the number of rows in an
            # answer is never one. An entry that tried would be excusing a value somebody chose
            # with a reason nobody argued (AC-6's whole distinction).
            continue
        return entry.because
    return ""


# --------------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunReport:
    """One run, and everything its report says - including what it did not ask.

    Plan section 5 declares `differences` as `(Case, Identity, Difference)` triples. It is a
    `(Comparison, Difference)` pair here, because a `Comparison` is the case **and** the endpoint
    and the declared conformance level, and because an `Identity` cannot be one thing: a seat is
    an account, the two servers do not share accounts, and the loop's unit is the role.
    """

    identities: Tuple[str, ...]
    cases: int
    comparisons: Tuple[Comparison, ...]
    named_run: Tuple[NamedResult, ...] = ()
    named_outstanding: Tuple[Tuple[str, str], ...] = ()
    endpoints: Tuple[Endpoint, ...] = ()
    provenance: Tuple[Tuple[str, str], ...] = ()
    unused_entries: Tuple[Tuple[str, str, str], ...] = ()
    #: What went wrong with the RUN rather than with a comparison: a sweep that could not finish,
    #: a seat the teardown could not delete, a reference that stopped answering. **Added on
    #: 2026-09-03, after the first full sweep produced no report at all.** The sweep had completed
    #: and `run()` had returned, and then the roster teardown raised on a `DELETE /Users` the dead
    #: reference could not answer - and because `main()` writes the report only after `_execute`
    #: returns, 154 comparisons went in the bin to report one failed delete. A run that dies still
    #: has findings, so the failure is carried here and the report is written anyway.
    incidents: Tuple[str, ...] = ()

    # -- what the summary counts -------------------------------------------------------------

    @property
    def differences(self) -> Tuple[Tuple[Comparison, Any], ...]:
        """Every untriaged finding, with the comparison that produced it."""
        return tuple(
            (comparison, finding)
            for comparison in self.comparisons
            for finding in comparison.differences
        )

    @property
    def known_divergences(self) -> Tuple[Tuple[Comparison, Any, str], ...]:
        """Findings a written argument already covers, reported every run (`attribute`)."""
        return tuple(
            (comparison, finding, because)
            for comparison in self.comparisons
            for finding, because in comparison.attributed
        )

    @property
    def unasked(self) -> Tuple[Comparison, ...]:
        """Every declared case this run did not issue, with the reason it could not."""
        return tuple(comparison for comparison in self.comparisons if not comparison.ran)

    @property
    def identical(self) -> int:
        return sum(1 for comparison in self.comparisons if comparison.identical)

    @property
    def excused(self) -> int:
        return sum(comparison.excused for comparison in self.comparisons)

    @property
    def endpoints_compared(self) -> Tuple[str, ...]:
        return tuple(
            sorted({comparison.endpoint for comparison in self.comparisons if comparison.ran})
        )

    def endpoints_compared_by(self) -> Dict[str, Tuple[str, ...]]:
        """Endpoint -> the seats that actually compared it, in the roster\'s own order.

        **Found at 010 T15, and it is the level table\'s version of AC-14.** The table printed
        `Compared: yes` from a flat set, so an endpoint reached by the administrator alone read
        exactly like one reached by both seats - on a surface where **12 of 23 reads answer
        differently to a restricted non-administrator** (spec section 3.9), two of them as shorter
        lists rather than as refusals. A conformance level claimed from the one seat that can be
        refused nothing is claimed from half the table, which is the overstatement this whole
        feature exists to catch, arriving in its own report.
        """
        reached: Dict[str, List[str]] = {}
        for comparison in self.comparisons:
            if not comparison.ran:
                continue
            seats = reached.setdefault(comparison.endpoint, [])
            if comparison.identity not in seats:
                seats.append(comparison.identity)
        order = {identity: position for position, identity in enumerate(self.identities)}
        return {
            endpoint: tuple(sorted(seats, key=lambda seat: order.get(seat, len(order))))
            for endpoint, seats in reached.items()
        }

    def coverage(self) -> Tuple[Tuple[str, int, int], ...]:
        """Per identity: cases issued, and cases that were not (AC-14).

        In the roster's own order, so one run's coverage line can be diffed against the last.
        """
        rows = []
        for identity in self.identities:
            mine = [c for c in self.comparisons if c.identity == identity]
            rows.append(
                (identity, sum(1 for c in mine if c.ran), sum(1 for c in mine if not c.ran))
            )
        return tuple(rows)

    @property
    def named_undocumented(self) -> Tuple[NamedResult, ...]:
        """Named comparisons that ran and measured something their own entry does not predict."""
        return tuple(result for result in self.named_run if not result.as_documented)

    def is_clean(self) -> bool:
        """False while this run has an unanswered question of any kind.

        Four conditions, where spec section 3.4 states two. *An untriaged difference blocks the
        run from being called clean. So does an unrun named comparison* - and so does **a declared
        case this run could not issue**, which is the same fact wearing the sweep's clothes: a
        comparison that did not happen is not a comparison that agreed. A run that reported clean
        having quietly dropped nine cases is one directory away from the CI job that reported
        green because it ran nothing (008 T18).

        **The fourth is 010 T12's, and it is the first three read the other way round.** A named
        comparison that *ran* and measured something the entry it cites does not predict is an
        untriaged difference too - the sweep's own class, arriving through a runner rather than
        through `compare`. Without it the twenty could all run, every one of them contradict its
        own citation, and the report say `20 run, 0 outstanding` (spec section 3.4's *Fix* row).

        **The fifth is 2026-09-03's**: a run with an incident is a run that did not finish, and a
        report written out of the wreckage must not be able to say it is clean.
        """
        return (
            not self.differences
            and not self.named_outstanding
            and not self.unasked
            and not self.named_undocumented
            and not self.incidents
        )


def sweep(
    endpoints: Sequence[Endpoint],
    cases: Sequence[Any],
    entries: Sequence[Any],
    seats: Sequence[Seat],
    issuers: Mapping[str, Issuer],
    inputs: Inputs,
    used: set,
) -> Tuple[Comparison, ...]:
    """Plan section 6.1's loop, with the identity outermost and the two servers back to back.

    **The identity loop is outermost on purpose.** A report grouped by identity is one a reader
    can scan for *"what does the restricted seat see that the administrator does not"*, which is
    the question spec section 3.9 exists to make askable - and it makes the degenerate run
    structurally the same run with a shorter loop, rather than a different code path that could
    quietly become the only one anybody uses.

    **The two servers are asked back to back, one case at a time.** A harness that swept one
    server and then the other would compare answers taken minutes apart, which manufactures
    differences rather than finding them: `/Items/{itemId}/Similar` is a fresh draw per request
    (spec section 7 OQ-4) and every clock-derived field moves with the minute.
    """
    roster_names = tuple(seat.role for seat in seats)
    cases_for = registers().cases_for
    comparisons: List[Comparison] = []
    if inputs.only_named:
        # Not a skip: every declared case is a question this run did not ask, `is_clean()` is
        # false for it, and the report lists them all with this sentence beside them.
        return tuple(
            Comparison(
                endpoint=endpoint.key,
                level=endpoint.level,
                case=case.id,
                identity="-",
                unreachable="--only-named was asked for, so the sweep did not run",
            )
            for endpoint in endpoints
            for case in cases_for(cases, endpoint.key)
        )
    for seat in seats:
        for endpoint in endpoints:
            for case in cases_for(cases, endpoint.key):
                if seat.role not in case.identities_for(roster_names):
                    continue
                comparisons.append(
                    compare_case(endpoint, case, seat, entries, issuers, inputs, used)
                )
    for endpoint in endpoints:
        for case in cases_for(cases, endpoint.key):
            if case.identities_for(roster_names):
                continue
            comparisons.append(
                Comparison(
                    endpoint=endpoint.key,
                    level=endpoint.level,
                    case=case.id,
                    identity="-",
                    unreachable=(
                        "no seat in this run is one this case is meaningful for; it declares "
                        + (", ".join(case.identities) or "every identity")
                    ),
                )
            )
    return tuple(comparisons)


def compare_case(
    endpoint: Endpoint,
    case: Any,
    seat: Seat,
    entries: Sequence[Any],
    issuers: Mapping[str, Issuer],
    inputs: Inputs,
    used: set,
) -> Comparison:
    """One case, one seat, both servers - or one `Comparison` saying why it could not be asked."""
    blocked = unmet_needs(case.needs, inputs)
    if blocked:
        return Comparison(
            endpoint=endpoint.key,
            level=endpoint.level,
            case=case.id,
            identity=seat.role,
            unreachable="; ".join(blocked),
        )
    try:
        ours = issuers["atrium"].issue(case, seat)
        theirs = issuers["reference"].issue(case, seat)
    except (UnreachableError, WireError) as failure:
        return Comparison(
            endpoint=endpoint.key,
            level=endpoint.level,
            case=case.id,
            identity=seat.role,
            unreachable=str(failure),
        )
    except Exception as failure:
        # **Anything else is still one case and not the run** (2026-09-03). The two declared
        # classes above are the ones a request is expected to fail with; a socket module raising
        # its own, or a decoder tripping over a body a dying server half-wrote, used to take the
        # loop out and every case after it with no row to show for any of them. One unreached
        # comparison is a row here; the run carries on and the report says so.
        return Comparison(
            endpoint=endpoint.key,
            level=endpoint.level,
            case=case.id,
            identity=seat.role,
            unreachable=f"{type(failure).__name__}: {failure}",
        )

    # The rules come from `_allowlist.resolve`, which is the one reader of that file. `in_force`
    # applies the same scoping rule to get the *entries* behind them, because the resolver returns
    # pointers and reasons and two things here need the entry itself: `attribute`, which reads
    # `because`, and the per-entry accounting plan section 7 asks for. If `resolve` ever gains a
    # dimension - an eighth column, an identity scope - this filter gains it in the same commit.
    resolution = registers().resolve(entries, endpoint.key, case.id, seat.role)
    in_force = tuple(
        entry
        for entry in entries
        if entry.endpoint in ("*", endpoint.key) and entry.case in ("*", case.id)
    )
    rules = engine().Rules(**resolution.mappings())
    findings = compare_pair(ours, theirs, rules)
    # The same pair again with nothing excused, which is where spec section 3.4's `allowlisted`
    # line comes from: the engine masks without counting, being pure, so the count is a
    # subtraction taken from outside rather than a ledger threaded through it.
    bare = compare_pair(ours, theirs, engine().NO_RULES)
    excused = max(0, len(bare) - len(findings))
    if excused:
        note_entries_that_excused(ours, theirs, in_force, findings, used)

    untriaged: List[Any] = []
    attributed: List[Tuple[Any, str]] = []
    for finding in engine().rank(findings):
        because = attribute(finding, in_force)
        if because:
            attributed.append((finding, because))
        else:
            untriaged.append(finding)
    return Comparison(
        endpoint=endpoint.key,
        level=endpoint.level,
        case=case.id,
        identity=seat.role,
        differences=tuple(untriaged),
        attributed=tuple(attributed),
        excused=excused,
    )


def note_entries_that_excused(
    ours: Any, theirs: Any, in_force: Sequence[Any], findings: Sequence[Any], used: set
) -> None:
    """Mark the entries that actually suppressed something, by taking each one away in turn.

    Plan section 7 wants *"an allowlist entry that matches nothing on any run"* reported, because
    the allowlist is a metric that should shrink and an entry that excuses nothing is either wrong
    or a converged difference. The engine masks without counting - it is pure and returns findings,
    not a ledger - so the count is taken here, from outside, by comparing again without the entry.
    An entry already known to have excused something is never re-checked, which is what keeps this
    from being quadratic in practice.
    """
    for entry in in_force:
        key = (entry.kind, entry.endpoint, entry.pointer, entry.case)
        if key in used:
            continue
        kept = [other for other in in_force if other is not entry]
        without = engine().Rules(**_mappings(kept))
        if len(compare_pair(ours, theirs, without)) > len(findings):
            used.add(key)


def _mappings(entries: Sequence[Any]) -> Dict[str, Dict[str, str]]:
    """The three `Rules` mappings from a list of entries, without going back to the file."""
    buckets: Dict[str, Dict[str, str]] = {
        "excused_fields": {},
        "drawn_arrays": {},
        "unordered_arrays": {},
    }
    names = {"field": "excused_fields", "drawn": "drawn_arrays", "unordered": "unordered_arrays"}
    for entry in entries:
        buckets[names[entry.kind]][entry.pointer] = entry.reason
    return buckets


# --------------------------------------------------------------------------------------------
# The named comparisons: six runner shapes over twenty rows (spec section 3.10, plan section 6.4)
# --------------------------------------------------------------------------------------------


class NamedError(RuntimeError):
    """A named comparison this run could not make, with the reason.

    **Raised rather than returned, and caught rather than fatal.** A runner that cannot reach what
    it needs - a seat, an item, a stream, a binary - leaves its row *outstanding with the
    exception* and the run carries on to the other nineteen, because a harness that stopped at the
    first unaskable question would report nothing about the questions after it.
    """


@dataclass(frozen=True)
class NamedResult:
    """What one named comparison found. The report prints all five fields.

    `as_documented` is the field that makes a run of the twenty worth having. A named comparison
    is not a pass: every one of these rows exists because two servers are **expected** to differ,
    and the entry that owns the row says how. So a runner reports what it measured and whether it
    is what the citation predicts - and a row that measured something else is an untriaged
    difference, which keeps the run from being clean exactly as a sweep finding does (spec
    section 3.4).
    """

    row: str
    finding: str
    atrium: str
    reference: str
    as_documented: bool = True


@dataclass(frozen=True)
class Instances:
    """The two servers a named comparison compares, and what this run knows about them.

    Plan section 6.4 gives every runner one signature, `(instances, identities) -> NamedResult`.
    `instances` is this: the two wires, the run's inputs, the sweep's own comparisons - which is
    what the two *"here to be recognised, not discovered"* rows read rather than re-issuing a
    request the sweep has already made - and the fixture tree on disk, which the two `rescan` rows
    need because changing a library means changing files and not calling a route.
    """

    atrium: Wire
    reference: Wire
    inputs: Inputs = Inputs()
    swept: Tuple[Comparison, ...] = ()
    fixture_root: Optional[Path] = None

    def wire(self, side: str) -> Wire:
        return self.atrium if side == "atrium" else self.reference

    def seated(self, side: str, seat: Seat) -> WireDirectory:
        """One server, held by one seat, through the four calls `Roster` already needed."""
        return WireDirectory(self.wire(side).as_seat(seat.identity(side).token))


#: The two sides, in the order a report prints them. Named once so a runner cannot compare
#: `atrium` with `atrium` by writing the string twice.
SIDES = ("atrium", "reference")


def seat_of(identities: Sequence[Seat], role: str) -> Seat:
    """The seat this run holds for `role`, or the reason it holds none."""
    for seat in identities:
        if seat.role == role:
            return seat
    raise NamedError(
        f"this run has no {role} seat, and the comparison is only visible from one "
        f"(it has {', '.join(seat.role for seat in identities) or 'nothing'})"
    )


def administrator_of(identities: Sequence[Seat]) -> Seat:
    return seat_of(identities, Role.ADMINISTRATOR.value)


#: How many rows a runner asks a listing for when it is looking for one item by name. The composed
#: fixture is 74 items on the reference and 78 here, so one page holds the tree twice over; the
#: number is a ceiling against a real library rather than a page size anybody tunes.
LOOKUP_LIMIT = 500


def items_of(directory: WireDirectory, user_id: str, **params: Any) -> List[Any]:
    """One listing, as rows. Never an identifier: every runner resolves per server."""
    body = directory.get("/Items", userId=user_id, recursive="true", **params) or {}
    rows = body.get("Items", []) if isinstance(body, dict) else []
    return list(rows)


def item_named(
    directory: WireDirectory, user_id: str, name: str, item_type: str = ""
) -> Dict[str, Any]:
    """The one item whose name carries `name`, resolved **on this server** (plan section 6.1.1).

    A named comparison joins the two servers the way the sweep's anchors do - by asking each of
    them for the thing, never by carrying an identifier across - because the two derive
    identifiers differently by design and a run that passed one over would be comparing a `404`.
    """
    params: Dict[str, Any] = {"limit": LOOKUP_LIMIT, "sortBy": "SortName"}
    if item_type:
        params["includeItemTypes"] = item_type
    wanted = name.lower()
    for row in items_of(directory, user_id, **params):
        if wanted in str(row.get("Name", "")).lower():
            return dict(row)
    raise NamedError(
        f"no {item_type or 'item'} whose name carries {name!r} on this server: the comparison "
        "needs this repository's own fixture on both sides, and this library is not it"
    )


def one_of(rows: Sequence[Any], what: str) -> Dict[str, Any]:
    if not rows:
        raise NamedError(f"this library has no {what}, so the comparison has nothing to ask about")
    return dict(rows[0])


def elapsed_request(wire: Wire, method: str, path: str, **kwargs: Any) -> Tuple[Any, float]:
    """One request and how long it took, in seconds. The payload is not the signal here."""
    started = time.monotonic()
    answer = wire.request(method, path, **kwargs)
    return answer, time.monotonic() - started


def status_line(answer: Any) -> str:
    """A refusal or an answer, in the shape a report can put in a table cell."""
    length = len(answer.raw)
    kind = header_value(answer.headers, "Content-Type") or "no content type"
    return f"{answer.status} {kind} {length}B"


# -- shape 1: a second seat --------------------------------------------------------------------
#
# Three rows, and two of them are why this whole register exists: they are invisible to a run that
# authenticates the way every probe in this repository did before 2026-09-01, because an
# administrator lacks no permission (spec section 3.9).

#: Every playlist a runner creates carries this, so a killed run leaves something recognisable.
#: 009's probes left 28 playlists on an operator's server under names like these; here they are on
#: a single-use instance that dies with the run, and they are still deleted in a `finally`.
PLAYLIST_PREFIX = "atrium differential - "


def make_playlist(
    owner: WireDirectory, owner_id: str, name: str, ids: Sequence[str], shared_with: str = ""
) -> str:
    """One playlist, created by its owner, optionally shared with one other account."""
    body: Dict[str, Any] = {
        "Name": PLAYLIST_PREFIX + name,
        "Ids": list(ids),
        "UserId": owner_id,
        "IsPublic": False,
    }
    if shared_with:
        body["Users"] = [{"UserId": shared_with, "CanEdit": True}]
    made = owner.post("/Playlists", body=body)
    if not isinstance(made, dict) or not made.get("Id"):
        raise NamedError(f"POST /Playlists answered {made!r} rather than an object with an Id")
    return str(made["Id"])


def drop_playlist(owner: WireDirectory, playlist_id: str) -> None:
    """Delete it, and never mask the failure that is already on its way out."""
    with contextlib.suppress(WireError):
        owner.delete_raw("/Items/" + playlist_id)


def named_playlist_read_names_its_reader(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 3.16: a private playlist read by a stranger who names its owner.

    **The whole signal is a status, and only a restricted seat can see it.** The reference takes
    the identity it checks permissions against from the `userId` query parameter with no test that
    the caller may name it, so a non-administrator reads any private playlist by naming its owner;
    Atrium honours the parameter for an administrator and refuses it otherwise. Two administrators
    agree on this request, which is why the row is here rather than in the sweep.
    """
    reader = seat_of(identities, Role.RESTRICTED.value)
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, int, int]] = {}
    for side in SIDES:
        owner = instances.seated(side, admin)
        owner_id = admin.identity(side).user_id
        tracks = items_of(owner, owner_id, includeItemTypes="Audio", limit=2, sortBy="SortName")
        one_of(tracks, "audio track to put in a playlist")
        held = instances.wire(side).as_seat(reader.identity(side).token)
        playlist = make_playlist(
            owner, owner_id, "the named reader", [str(row["Id"]) for row in tracks]
        )
        try:
            blind = held.request("GET", "/Playlists/" + playlist + "/Items")
            named = held.request(
                "GET",
                "/Playlists/" + playlist + "/Items",
                query=urllib.parse.urlencode({"userId": owner_id}),
            )
        finally:
            drop_playlist(owner, playlist)
        rows = len(named.body.get("Items", [])) if isinstance(named.body, dict) else 0
        answers[side] = (blind.status, named.status, rows)
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="playlist-read-names-its-reader",
        finding=(
            "the restricted reader is answered "
            f"{ours[0]} here and {theirs[0]} there without the parameter, and "
            f"{ours[1]} here and {theirs[1]} there when the request names the owner"
        ),
        atrium=f"userId=<owner> -> {ours[1]}, {ours[2]} entries",
        reference=f"userId=<owner> -> {theirs[1]}, {theirs[2]} entries",
        # behaviours 3.16: the reference hands the entries over, Atrium refuses the parameter.
        as_documented=theirs[1] == 200 and theirs[2] > 0 and ours[1] == 403,
    )


def named_playlist_entries_a_reader_cannot_reach(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 3.17: **the row count is the whole signal**, and it needs both halves.

    Over a stock library the two servers *agree*, because what the reference hides in a playlist
    is hidden by a parental-rating check and never by library access - so the comparison says
    nothing at all unless the reader is restricted to one library and the playlist holds items
    from two. The restriction is checked rather than assumed: an item the reader can in fact open
    would make this a comparison of two identical answers passing for parity, which is 006 T5's
    hostile-path test in this feature's shape.
    """
    reader = seat_of(identities, Role.RESTRICTED.value)
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, int, int]] = {}
    for side in SIDES:
        owner = instances.seated(side, admin)
        owner_id = admin.identity(side).user_id
        held = instances.wire(side).as_seat(reader.identity(side).token)
        reader_id = reader.identity(side).user_id

        visible = one_of(
            items_of(
                WireDirectory(held), reader_id, includeItemTypes="Movie", limit=1, sortBy="SortName"
            ),
            "movie the restricted reader may open",
        )
        beyond = items_of(owner, owner_id, includeItemTypes="Audio", limit=2, sortBy="SortName")
        one_of(beyond, "audio track outside the reader's one library")
        refused = held.request("GET", "/Items/" + str(beyond[0]["Id"]))
        if refused.status == 200:
            raise NamedError(
                "the restricted seat can open the item this comparison needs it not to reach on "
                f"the {side}: GET /Items/{beyond[0]['Id']} answered 200, so a playlist holding it "
                "would compare two identical answers and report parity it never measured"
            )
        playlist = make_playlist(
            owner,
            owner_id,
            "entries a reader cannot reach",
            [str(visible["Id"])] + [str(row["Id"]) for row in beyond],
            shared_with=reader_id,
        )
        try:
            seen = held.request(
                "GET",
                "/Playlists/" + playlist + "/Items",
                query=urllib.parse.urlencode({"userId": reader_id}),
            )
        finally:
            drop_playlist(owner, playlist)
        body = seen.body if isinstance(seen.body, dict) else {}
        total = int(body.get("TotalRecordCount", -1))
        answers[side] = (seen.status, len(body.get("Items", [])), total)
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="playlist-entries-a-reader-cannot-reach",
        finding=(
            "a playlist of three entries spanning two libraries, read by a seat that can open "
            f"one of them: {ours[1]} rows here against {theirs[1]} there"
        ),
        atrium=f"{ours[0]}, {ours[1]} rows, TotalRecordCount={ours[2]}",
        reference=f"{theirs[0]}, {theirs[1]} rows, TotalRecordCount={theirs[2]}",
        # behaviours 3.17: the reference hands over every row, Atrium omits what the reader
        # cannot reach and counts only what it returns.
        as_documented=theirs[1] > ours[1] and theirs[2] > ours[2],
    )


def named_delivery_time_policy_refusal(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 2.21: the seat with the three playback-processing permissions denied.

    T7 built the seat and could not measure it - the only reachable Jellyfin was an operator's
    server and creating an account is a write - and T9 measured the three denials *reading back*
    denied. What neither could ask is whether they are **observable**, which is a negotiation and
    a delivery rather than a policy object, and that is this row.

    **The delivery half of what this row predicted was never reachable through the request it
    makes, and 2026-09-02's run is what showed it.** `/Videos/{id}/stream.mp4` is one of the four
    `stream` routes, and those take **no user at all** on either server's contract as this project
    records it (behaviours 2.10) - Atrium reads no policy there, so the refusal it substitutes for
    the reference's force-copy (behaviours 2.21's *"one edge not replicated"*) lives on the HLS
    segment route and nowhere else. Both servers therefore answer this request `200`, with
    different bytes behind it, and a predicate demanding two different statuses was asserting
    something the entry it cites does not claim. What is asserted now is what the entry does
    claim and what this request can reach: the negotiation gate, on both servers, and a delivery
    neither of them refuses. The force-copy edge itself is still uncompared - reaching it needs a
    segment request built by hand, because a denied seat's own negotiation hands over no address
    to follow.

    **The listing is asked here too, since 2026-09-02.** The same reference function builds an item
    body's `MediaSources` and a profile-less negotiation's [source:
    Emby.Server.Implementations/Dto/DtoService.cs:261,
    Emby.Server.Implementations/Library/MediaSourceManager.cs:355-372 @ v10.11.11], so this seat
    reads its own flags on `GET /Items/{itemId}` as well - and that half was an accepted gap
    between the 008 fix that recorded it and the 005 fix that closed it. It is one more request on
    a seat this row already holds, against the item it already resolved, which is the whole reason
    it is here rather than in a row of its own: a seat with a denied playback permission is what no
    sweep has, and building a second one to ask one more question of it would be the expensive way
    to ask it.
    """
    denied = seat_of(identities, Role.PLAYBACK_DENIED.value)
    answers: Dict[str, Tuple[Any, int, str, Any, Any]] = {}
    for side in SIDES:
        held = instances.wire(side).as_seat(denied.identity(side).token)
        directory = WireDirectory(held)
        user_id = denied.identity(side).user_id
        film = item_named(directory, user_id, "Rejected Video", "Movie")
        negotiated = directory.post(
            "/Items/" + str(film["Id"]) + "/PlaybackInfo", body={}, userId=user_id
        )
        sources = negotiated.get("MediaSources", []) if isinstance(negotiated, dict) else []
        supports = one_of(sources, "media source on the negotiation").get("SupportsTranscoding")
        delivered = held.request(
            "GET",
            "/Videos/" + str(film["Id"]) + "/stream.mp4",
            query="static=false&videoCodec=h264&audioCodec=aac",
        )
        body = directory.get("/Items/" + str(film["Id"]), userId=user_id)
        listed = one_of(
            body.get("MediaSources", []) if isinstance(body, dict) else [],
            "media source on the item body",
        )
        answers[side] = (
            supports,
            delivered.status,
            status_line(delivered),
            listed.get("SupportsTranscoding"),
            listed.get("SupportsDirectStream"),
        )
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="delivery-time-policy-refusal",
        finding=(
            "with all three processing permissions denied, the negotiation answers "
            f"SupportsTranscoding={ours[0]!r} here and {theirs[0]!r} there, the item body's own "
            f"media source answers SupportsTranscoding={ours[3]!r}/{theirs[3]!r} and "
            f"SupportsDirectStream={ours[4]!r}/{theirs[4]!r}, and a delivery that would have to "
            f"re-encode answers {ours[1]} here and {theirs[1]} there - a route with no user on "
            "either contract, so neither server refuses it"
        ),
        atrium=(
            f"SupportsTranscoding={ours[0]!r}; listing {ours[3]!r}/{ours[4]!r}; delivery {ours[2]}"
        ),
        reference=(
            f"SupportsTranscoding={theirs[0]!r}; listing {theirs[3]!r}/{theirs[4]!r}; "
            f"delivery {theirs[2]}"
        ),
        # behaviours 2.21: the negotiation gates to `false` on both servers, the listing carries
        # the same per-kind rule on a video item - transcoding off, direct stream off - and this
        # delivery route reads no policy on either. See the docstring for why the force-copy edge
        # is not what these two statuses can measure.
        as_documented=(
            ours[0] is False
            and theirs[0] is False
            and ours[1] == 200
            and theirs[1] == 200
            and ours[3] is False
            and theirs[3] is False
            and ours[4] is False
            and theirs[4] is False
        ),
    )


# -- shape 2: the same request twice ------------------------------------------------------------

#: How many identical adds the de-duplication row issues per server. Eight, because eight is what
#: `tools/probe_playlist_writes.py` measured the reference disagreeing with itself over - 6 of 8 -
#: and a smaller number could not tell a race that missed from a server that never duplicates.
DE_DUPLICATION_ATTEMPTS = 8


def named_playlist_de_duplication_misses(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 3.18: the reference disagrees with **itself**, so one run proves nothing.

    A disagreement is the entry and never a flake to retry. Eight identical adds per server, each
    against a playlist of its own, and what is reported is how many of them the server let
    through.
    """
    admin = administrator_of(identities)
    duplicated: Dict[str, int] = {}
    for side in SIDES:
        owner = instances.seated(side, admin)
        owner_id = admin.identity(side).user_id
        track = one_of(
            items_of(owner, owner_id, includeItemTypes="Audio", limit=1, sortBy="SortName"),
            "audio track to add twice",
        )
        seen = 0
        for attempt in range(DE_DUPLICATION_ATTEMPTS):
            playlist = make_playlist(
                owner, owner_id, f"de-duplication {attempt}", [str(track["Id"])]
            )
            try:
                owner.post_raw(
                    "/Playlists/" + playlist + "/Items", ids=str(track["Id"]), userId=owner_id
                )
                after = owner.get("/Playlists/" + playlist + "/Items", userId=owner_id) or {}
                if len(after.get("Items", [])) > 1:
                    seen += 1
            finally:
                drop_playlist(owner, playlist)
        duplicated[side] = seen
    ours, theirs = duplicated["atrium"], duplicated["reference"]
    return NamedResult(
        row="playlist-de-duplication-misses",
        finding=(
            f"the same add, issued {DE_DUPLICATION_ATTEMPTS} times against each server: the "
            f"reference duplicated on {theirs} of them and Atrium on {ours}"
        ),
        atrium=f"{ours}/{DE_DUPLICATION_ATTEMPTS} adds duplicated",
        reference=f"{theirs}/{DE_DUPLICATION_ATTEMPTS} adds duplicated",
        # Only Atrium's half can be asserted: the reference's is a race, and a run reported unclean
        # because a coin came up the other way is the crying wolf spec section 6 forbids.
        as_documented=ours == 0,
    )


# -- shape 3: something that is not in a body ---------------------------------------------------
#
# Five rows whose difference is in the bytes, the frames or the clock. Spec section 6 declines to
# byte-compare produced media, which is right for a sweep and is exactly why these are named: what
# is compared here is one attribute of the bytes, never the bytes after it.


#: A delivery that has to run an encoder is not a JSON read, and the sweep's 30 s is written for
#: the latter. Twice the reference's own measured worst case for a subtitle extraction (011's
#: twenty seconds) plus the encode of a four-second fixture film.
PRODUCTION_TIMEOUT = 120


def patient(wire: Wire, seconds: int = PRODUCTION_TIMEOUT) -> Wire:
    """The same server and seat, given time to produce. Never used for a read."""
    return Wire(wire.base_url, token=wire.token, timeout=seconds)


def source_of(directory: WireDirectory, item_id: str, user_id: str) -> Dict[str, Any]:
    """The first media source a negotiation answers, which is where the stream numbers live."""
    negotiated = directory.post("/Items/" + item_id + "/PlaybackInfo", body={}, userId=user_id)
    sources = negotiated.get("MediaSources", []) if isinstance(negotiated, dict) else []
    return one_of(sources, "media source on the negotiation")


def stream_index(source: Mapping[str, Any], **wanted: Any) -> int:
    """The `Index` of the first stream matching every named property, or a reason there is none."""
    for stream in source.get("MediaStreams", []) or []:
        if all(stream.get(key) == value for key, value in wanted.items()):
            return int(stream["Index"])
    raise NamedError(
        f"no stream matching {wanted!r} on this source, so the comparison has no track to name"
    )


def named_progressive_re_encode_header_frame(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 3.3, and 008 T14's fourth divergence: the self-description a pipe cannot write.

    An encoder writing to a **pipe** cannot go back and fill in what it only knows at the end, so
    a progressive re-encode's first frames carry no `Xing`/`Info` header. Nothing in a decoded body
    says so, and spec section 6 declines to byte-compare produced media - so the comparison is of
    one attribute of the first frames and never of the bytes after it.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, bool, int]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        track = item_named(directory, user_id, "Ninety Six Kilohertz", "Audio")
        answer = patient(instances.wire(side).as_seat(admin.identity(side).token)).request(
            "GET",
            "/Audio/" + str(track["Id"]) + "/stream.mp3",
            query="static=false&audioCodec=mp3",
        )
        head = answer.raw[:8192]
        answers[side] = (answer.status, b"Xing" in head or b"Info" in head, len(answer.raw))
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="progressive-re-encode-header-frame",
        finding=(
            "the first frames of a progressive mp3 re-encode carry a Xing/Info header frame: "
            f"{ours[1]} here, {theirs[1]} there"
        ),
        atrium=f"{ours[0]}, header frame {ours[1]}, {ours[2]}B",
        reference=f"{theirs[0]}, header frame {theirs[1]}, {theirs[2]}B",
        as_documented=ours[1] != theirs[1],
    )


def frame_hashes(payload: bytes) -> str:
    """The decoded frames of a produced body, as one hash. `ffmpeg`, or a reason there is none.

    Comparing the produced **bytes** would compare two encoders and two containers; comparing the
    decoded frames compares the picture, which is what burn-in changes and what nothing else here
    does.
    """
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise NamedError(
            "burn-in is a difference in the pixels and this machine has no ffmpeg to decode them "
            "with; the row is a comparison of frames rather than of a body"
        )
    finished = subprocess.run(  # noqa: S603 - the arguments are this module's own
        [binary, "-v", "error", "-i", "pipe:0", "-map", "0:v:0", "-f", "framemd5", "-"],
        input=payload,
        capture_output=True,
        timeout=PRODUCTION_TIMEOUT,
    )
    if finished.returncode != 0:
        raise NamedError(
            "ffmpeg could not decode what this server produced: "
            + finished.stderr.decode("utf-8", "replace").strip()[:200]
        )
    decoded = finished.stdout.decode("ascii", "replace").splitlines()
    lines = [line for line in decoded if line[:1] != "#"]
    if not lines:
        raise NamedError("the produced body decoded to no video frames at all")
    return hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()[:16]


def named_subtitle_burn_in(instances: Instances, identities: Sequence[Seat]) -> NamedResult:
    """behaviours 5's subtitle row: the reference paints the cues in and Atrium does not.

    The two answers agree on status, headers and shape, so the only comparison that says anything
    is of the **frames**. Each server produces the same four seconds twice - once naming the track
    whose negotiated delivery method is `Encode`, once naming none - and what is compared is
    whether its own two answers decode to the same picture. A server that burns in differs from
    itself; a server that does not is identical to itself, and the difference between the two
    servers is that answer rather than a byte count.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[bool, str, str]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "The Unconvertible", "Movie")
        source = source_of(directory, str(film["Id"]), user_id)
        track = stream_index(source, Type="Subtitle", Codec="ass")
        held = patient(instances.wire(side).as_seat(admin.identity(side).token))
        base = "/Videos/" + str(film["Id"]) + "/stream.mp4"
        common = "static=false&videoCodec=h264&audioCodec=aac&mediaSourceId=" + str(source["Id"])
        plain = held.request("GET", base, query=common)
        with_cues = held.request(
            "GET",
            base,
            query=common + "&subtitleStreamIndex=" + str(track) + "&subtitleMethod=Encode",
        )
        if plain.status != 200 or with_cues.status != 200:
            raise NamedError(
                f"the {side} would not produce the pair this row compares: "
                f"{plain.status} without the track and {with_cues.status} with it"
            )
        without_hash, with_hash = frame_hashes(plain.raw), frame_hashes(with_cues.raw)
        answers[side] = (without_hash != with_hash, without_hash, with_hash)
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="subtitle-burn-in",
        finding=(
            "naming a track whose delivery method is Encode changes the decoded frames: "
            f"{ours[0]} here, {theirs[0]} there"
        ),
        atrium=f"frames changed by the named track: {ours[0]} ({ours[1]} -> {ours[2]})",
        reference=f"frames changed by the named track: {theirs[0]} ({theirs[1]} -> {theirs[2]})",
        as_documented=theirs[0] and not ours[0],
    )


#: The tag a subtitle playlist writes a window's duration under. Its own syntax ends in a comma,
#: which is why behaviours 3.12's decimal separator can only be read from the duration token.
EXTINF = "#EXTINF:"

#: The attribute an HLS media entry names a track with, and the one attribute of the manifest that
#: is a *localised string* rather than a protocol value (011 section 6).
MEDIA_NAME = re.compile(r'NAME="([^"]*)"')


def named_manifest_announced_track_name(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """011 section 6: the announced name differs by the reference *host's* culture.

    So the comparison is the manifest with the name masked - which must agree - and the name
    itself beside it, which is a reading of where the reference is installed rather than of what
    it serves. A comparison that diffed the attribute would report the operator's locale as a
    defect on every run.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, str, Tuple[str, ...]]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "The Unconvertible", "Movie")
        held = patient(instances.wire(side).as_seat(admin.identity(side).token))
        manifest = held.request(
            "GET",
            "/Videos/" + str(film["Id"]) + "/master.m3u8",
            query="videoCodec=h264&audioCodec=aac&segmentContainer=ts",
        )
        text = manifest.raw.decode("utf-8", "replace")
        media = [line for line in text.splitlines() if line.startswith("#EXT-X-MEDIA")]
        found = [MEDIA_NAME.search(line) for line in media]
        names = tuple(match.group(1) for match in found if match)
        masked = "\n".join(MEDIA_NAME.sub('NAME="<masked>"', line) for line in media)
        if manifest.status != 200:
            raise NamedError(
                f"the {side} answered {manifest.status} for the master playlist of the film this "
                "row announces tracks on, so there are no announced entries to compare"
            )
        answers[side] = (manifest.status, masked, names)
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="manifest-announced-track-name",
        finding=(
            f"{len(ours[2])} announced entries here and {len(theirs[2])} there; with NAME masked "
            f"the entries {'agree' if ours[1] == theirs[1] else 'DIFFER'}, and the names are "
            f"{list(ours[2])} against {list(theirs[2])}"
        ),
        atrium=f"{ours[0]}, names {list(ours[2])}",
        reference=f"{theirs[0]}, names {list(theirs[2])}",
        # The masked entries are the comparison; the names are reported and never asserted, because
        # asserting them would assert the reference host's interface culture.
        as_documented=ours[1] == theirs[1],
    )


def named_subtitle_playlist_decimal_point(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 3.12: the decimal separator a parser normalises away.

    Byte-compared, because that is the only place it survives - and reported with the separator
    each server actually wrote, since the reference's is a property of its **host** and an
    English-configured one writes the same point Atrium does.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, bytes, str]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "The Unconvertible", "Movie")
        source = source_of(directory, str(film["Id"]), user_id)
        track = stream_index(source, Type="Subtitle")
        held = instances.wire(side).as_seat(admin.identity(side).token)
        answer = held.request(
            "GET",
            "/Videos/"
            + str(film["Id"])
            + "/"
            + str(source["Id"])
            + "/Subtitles/"
            + str(track)
            + "/subtitles.m3u8",
            query="segmentLength=10",
        )
        durations = [
            line
            for line in answer.raw.decode("utf-8", "replace").splitlines()
            if line.startswith(EXTINF)
        ]
        # **`#EXTINF:<duration>,<title>` ends in a comma by syntax**, so a reader that looked for
        # one anywhere on the line would call every playlist ever written a comma-decimal one.
        # What is read is the duration alone, which is the token behaviours 3.12 is about.
        values = [line[len(EXTINF) :].strip().rstrip(",") for line in durations]
        separator = "comma" if any("," in value for value in values) else "point"
        answers[side] = (answer.status, "\n".join(durations), separator)
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="subtitle-playlist-decimal-point",
        finding=(
            "the two playlists' window lines are "
            + ("identical" if ours[1] == theirs[1] else "different")
            + f"; the durations use a decimal {ours[2]} here and a decimal {theirs[2]} there"
        ),
        atrium=f"{ours[0]}, decimal {ours[2]}, {ours[1].splitlines()[-1:]}",
        reference=f"{theirs[0]}, decimal {theirs[2]}, {theirs[1].splitlines()[-1:]}",
        # behaviours 3.12 says the separator is the *host's*, so parity on an English-configured
        # instance is the entry holding rather than the divergence disappearing. What must not
        # happen is Atrium writing a comma, which it has no locale to write one from.
        as_documented=ours[2] == "point",
    )


#: How slow the reference has to be for this row's difference to be the one 011 described. One
#: second is two orders of magnitude below the twenty it claims and two above a local answer, so
#: it separates *"the wait happened"* from *"one of them was a little slower"*.
SLOW_ENOUGH_TO_BE_THE_WAIT = 1.0


def named_image_subtitle_track_latency(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """011: the `400` that arrives after twenty seconds of waiting, and the one that does not.

    Nothing in a body carries elapsed time - the status and the bytes are the same on both - so
    what is compared is the clock.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, float, int]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "Both Subtitle Kinds", "Movie")
        source = source_of(directory, str(film["Id"]), user_id)
        track = stream_index(source, Type="Subtitle", IsTextSubtitleStream=False)
        held = patient(instances.wire(side).as_seat(admin.identity(side).token))
        answer, seconds = elapsed_request(
            held,
            "GET",
            "/Videos/"
            + str(film["Id"])
            + "/"
            + str(source["Id"])
            + "/Subtitles/"
            + str(track)
            + "/Stream.vtt",
        )
        answers[side] = (answer.status, seconds, len(answer.raw))
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="image-subtitle-track-latency",
        finding=(
            "an image subtitle track asked for as text answers "
            f"{ours[0]} in {ours[1]:.2f}s here and {theirs[0]} in {theirs[1]:.2f}s there"
        ),
        atrium=f"{ours[0]} in {ours[1]:.2f}s, {ours[2]}B",
        reference=f"{theirs[0]} in {theirs[1]:.2f}s, {theirs[2]}B",
        # 011's claim is *twenty seconds of waiting*, so the comparison is of an order of
        # magnitude and never of two floats: a reference that answered 40 ms slower has not
        # reproduced the difference this row exists for, and saying it has would be the harness
        # agreeing with a document rather than measuring it.
        as_documented=ours[0] == theirs[0] and theirs[1] >= SLOW_ENOUGH_TO_BE_THE_WAIT,
    )


# -- shape 4: a library the reference has to be given -------------------------------------------
#
# Six rows that no reachable library can answer, and every one of them is askable for the first
# time because 010 T11 composed a tree and T9 built a server this project may write to.


def series_with_specials(
    directory: WireDirectory, user_id: str
) -> Tuple[Dict[str, Any], List[Any], List[Any]]:
    """A series holding both a season 0 and ordinary episodes, found by **shape** and not by name.

    010 T12 wrote this by name first and the reference and Atrium disagree about that name: the
    003 tree's series comes back as `The Series` there and as `tvshow` here, because Atrium reads
    the `tvshow.nfo` beside it and the reference names the container after its directory. A
    comparison keyed on a name would have been outstanding on one server for a difference the
    reading already declares, so the series is the one whose episodes have the shape the question
    needs.
    """
    for row in items_of(
        directory, user_id, includeItemTypes="Series", limit=LOOKUP_LIMIT, sortBy="SortName"
    ):
        episodes = (
            directory.get("/Shows/" + str(row["Id"]) + "/Episodes", userId=user_id) or {}
        ).get("Items", [])
        ordinary = [one for one in episodes if one.get("ParentIndexNumber") not in (0, None)]
        specials = [one for one in episodes if one.get("ParentIndexNumber") == 0]
        if ordinary and specials:
            return dict(row), ordinary, specials
    raise NamedError(
        "no series on this server has both a season 0 and ordinary episodes, which is the shape "
        "this question needs and the shape the fixture was built to have"
    )


def named_multi_part_film_media_sources(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 5's multi-part row (008 section 3.1): two sources here, one and a count there."""
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, Any, Any]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "The Two Parter", "Movie")
        body = (
            directory.get("/Items/" + str(film["Id"]), userId=user_id, fields="MediaSources") or {}
        )
        sources = body.get("MediaSources") or []
        answers[side] = (len(sources), body.get("PartCount"), body.get("Name"))
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="multi-part-film-media-sources",
        finding=(
            f"the two-part film answers {ours[0]} media source(s) here and {theirs[0]} there, "
            f"with PartCount {ours[1]!r} against {theirs[1]!r}"
        ),
        atrium=f"{ours[0]} sources, PartCount={ours[1]!r}",
        reference=f"{theirs[0]} sources, PartCount={theirs[1]!r}",
        as_documented=ours[0] != theirs[0] or ours[1] != theirs[1],
    )


def named_media_source_no_runtime_and_zero_length_cue(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """011: a source stating no runtime - **reported as a miss rather than inferred**.

    Spec section 3.10 asks for this one to be reported by its own probe on every run rather than
    assumed, because no reference library can be put into the state from outside. The composed
    fixture can: the 003 tree is paths and filler, so a file nothing can decode is an item with a
    source and no runtime on both servers, and the comparison is what each one puts in the empty
    slots.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[str, Any, Any, Any]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        without = [
            row
            for row in items_of(
                directory, user_id, includeItemTypes="Movie", limit=LOOKUP_LIMIT, sortBy="SortName"
            )
            if row.get("RunTimeTicks") in (None, 0)
        ]
        if not without:
            answers[side] = ("MISS: no item with no runtime in this library", None, None, None)
            continue
        item = dict(without[0])
        body = (
            directory.get("/Items/" + str(item["Id"]), userId=user_id, fields="MediaSources") or {}
        )
        sources = body.get("MediaSources") or []
        first = sources[0] if sources else {}
        answers[side] = (
            str(body.get("Name")),
            first.get("RunTimeTicks", "absent"),
            first.get("Bitrate", "absent"),
            len(first.get("MediaStreams") or []),
        )
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="media-source-no-runtime-and-zero-length-cue",
        finding=(
            "over a file neither server can decode, the media source answers RunTimeTicks "
            f"{ours[1]!r} here and {theirs[1]!r} there, with {ours[3]} streams against {theirs[3]}"
        ),
        atrium=f"{ours[0]}: RunTimeTicks={ours[1]!r}, Bitrate={ours[2]!r}, {ours[3]} streams",
        reference=(
            f"{theirs[0]}: RunTimeTicks={theirs[1]!r}, Bitrate={theirs[2]!r}, {theirs[3]} streams"
        ),
        # behaviours 5's un-inspected-source row: on a listing the two agree, which is what this
        # asserts. A zero-length cue has no reachable state on either server and is the miss the
        # finding names.
        as_documented=ours[1] == theirs[1] and ours[3] == theirs[3],
    )


def named_legacy_encoded_subtitle_file(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 5.11: a sidecar in a legacy single-byte encoding, decoded by a rule.

    `cp1251` and `cp1252` share every byte position, so the words decode to *different letters*
    rather than to an error - which is the half a client sees directly, and the reason the fixture
    entry is Cyrillic rather than something that would merely refuse.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, str]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "The Legacy Encoding", "Movie")
        source = source_of(directory, str(film["Id"]), user_id)
        track = stream_index(source, Type="Subtitle", IsExternal=True)
        held = patient(instances.wire(side).as_seat(admin.identity(side).token))
        answer = held.request(
            "GET",
            "/Videos/"
            + str(film["Id"])
            + "/"
            + str(source["Id"])
            + "/Subtitles/"
            + str(track)
            + "/Stream.vtt",
        )
        cues = " ".join(
            line
            for line in answer.raw.decode("utf-8", "replace").splitlines()
            if line
            and not line.startswith(("WEBVTT", "NOTE", "STYLE", "Region:", "\ufeff"))
            and "-->" not in line
            and not line.strip().isdigit()
        )
        answers[side] = (answer.status, cues[:80])
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="legacy-encoded-subtitle-file",
        finding=(
            "a cp1251 sidecar served as WebVTT decodes to "
            + ("the same text" if ours[1] == theirs[1] else "DIFFERENT text")
            + " on the two servers"
        ),
        atrium=f"{ours[0]}: {ours[1]!r}",
        reference=f"{theirs[0]}: {theirs[1]!r}",
        as_documented=ours[0] == theirs[0],
    )


def jpeg_size(payload: bytes) -> Tuple[int, int]:
    """A JPEG's pixel dimensions, read from its own start-of-frame marker.

    Read rather than asked of an image library, for the reason `tests/fixtures/media.py` splices
    an EXIF segment by hand: `tools/` is the standard library on a 3.9 floor, and a dependency
    added to measure two numbers is a dependency every contributor then installs.
    """
    at = 2
    while at + 9 < len(payload):
        if payload[at] != 0xFF:
            at += 1
            continue
        marker = payload[at + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(payload[at + 5 : at + 7], "big")
            width = int.from_bytes(payload[at + 7 : at + 9], "big")
            return width, height
        at += 2 + int.from_bytes(payload[at + 2 : at + 4], "big")
    raise NamedError("what came back is not a JPEG this reader can find a frame header in")


def named_exif_orientation_on_resize(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """006: whether a resize honours an EXIF orientation, against a control produced the same way.

    The planted poster is 2:3 and tagged *rotate 90*; the backdrop beside it is the same encoder,
    the same splice and the tag set to normal. A server that honours the tag answers the poster
    landscape and the control unchanged; one that ignores it answers both portrait-as-written. One
    image alone could not tell an honoured tag from a resize that behaves differently.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[Tuple[int, int], Tuple[int, int]]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "The Planted Poster", "Movie")
        held = instances.wire(side).as_seat(admin.identity(side).token)
        sizes = []
        for kind in ("Primary", "Backdrop"):
            answer = held.request(
                "GET", "/Items/" + str(film["Id"]) + "/Images/" + kind, query="maxWidth=200"
            )
            if answer.status != 200:
                raise NamedError(
                    f"the {side} answered {answer.status} for the {kind} image of the planted "
                    "film, so there is nothing to measure the orientation on"
                )
            sizes.append(jpeg_size(answer.raw))
        answers[side] = (sizes[0], sizes[1])
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="exif-orientation-on-resize",
        finding=(
            f"the tagged poster resizes to {ours[0]} here and {theirs[0]} there, against an "
            f"untagged control of {ours[1]} and {theirs[1]}"
        ),
        atrium=f"tagged {ours[0]}, control {ours[1]}",
        reference=f"tagged {theirs[0]}, control {theirs[1]}",
        as_documented=ours[0] == theirs[0],
    )


#: The library `tests/fixtures/reference_tree.py` makes with nothing in it. Spelled here rather
#: than imported, because `tools/` runs on the 3.9 floor where this repository's test package is
#: not importable - and asserted against that module by the suite, which can import both.
EMPTY_LIBRARY_NAME = "Empty"


def named_empty_library_played_state(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 5.7: the one shape where "vacuously played" is observable at all.

    A `Series`, `Season`, `MusicArtist` or `MusicAlbum` with nothing under it is not offered, so a
    `CollectionFolder` is the only row a client can read the flag off - and no reachable library
    has one, because making one means writing into somebody's server.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[str, Any, Any]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        views = directory.get("/UserViews", userId=user_id) or {}
        rows = [row for row in views.get("Items", []) if str(row.get("Name")) == EMPTY_LIBRARY_NAME]
        if not rows:
            answers[side] = ("MISS: no empty library in this server's views", None, None)
            continue
        view = dict(rows[0])
        data = view.get("UserData") or {}
        answers[side] = (str(view.get("Name")), data.get("Played"), data.get("UnplayedItemCount"))
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="empty-library-played-state",
        finding=(
            f"an empty library reads Played={ours[1]!r} here and {theirs[1]!r} there, with "
            f"UnplayedItemCount {ours[2]!r} against {theirs[2]!r}"
        ),
        atrium=f"{ours[0]}: Played={ours[1]!r}, UnplayedItemCount={ours[2]!r}",
        reference=f"{theirs[0]}: Played={theirs[1]!r}, UnplayedItemCount={theirs[2]!r}",
        # behaviours 5.7 reads the reference's source as vacuously played and says so is unmeasured.
        # This is the measurement, so the row is as-documented when Atrium answers what it says it
        # answers; what the reference answers is the finding.
        as_documented=ours[1] is False,
    )


def named_next_up_pristine_specials_season(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """005 section 7 OQ-7: does Next Up offer a series whose only unplayed episodes are season 0's?

    The library measured on 2026-08-28 had no such series and the probe said so in its own output.
    This one is made rather than found: every episode outside season 0 is marked played on both
    servers, the route is read, and the marks are taken back off.
    """
    admin = administrator_of(identities)
    answers: Dict[str, Tuple[int, bool, str]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        series, ordinary, _specials = series_with_specials(directory, user_id)
        marked = []
        try:
            for row in ordinary:
                directory.post_raw("/UserPlayedItems/" + str(row["Id"]), userId=user_id)
                marked.append(str(row["Id"]))
            next_up = (
                directory.get("/Shows/NextUp", userId=user_id, seriesId=str(series["Id"])) or {}
            )
            rows = next_up.get("Items", [])
            offered = [str(row.get("Name")) for row in rows]
            answers[side] = (
                len(rows),
                any(row.get("ParentIndexNumber") == 0 for row in rows),
                ", ".join(offered) or "nothing",
            )
        finally:
            for item_id in marked:
                directory.delete_raw("/UserPlayedItems/" + item_id, userId=user_id)
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="next-up-pristine-specials-season",
        finding=(
            "with every ordinary episode played and season 0 pristine, Next Up offers "
            f"{ours[0]} row(s) here and {theirs[0]} there"
        ),
        atrium=f"{ours[0]} rows ({ours[2]}), a special among them: {ours[1]}",
        reference=f"{theirs[0]} rows ({theirs[2]}), a special among them: {theirs[1]}",
        as_documented=ours[0] == theirs[0] and ours[1] == theirs[1],
    )


# -- shape 5: the library changed underneath a rescan -------------------------------------------
#
# Two rows, both added by D-6, and both of them measure something this repository has never seen.
# behaviours 5.2 carried the only surviving UNVERIFIED marker in the compatibility documents
# until this runner took its reading on 2026-09-02, and 5.6 said in as many words that it was
# *"unmeasured from here"*. Both readings are in that document now.

#: What counts as an episode when a container is emptied on disk. The declared media extensions of
#: `tests/fixtures/library/manifest.py`'s Shows tree, spelled here rather than imported for the
#: reason `EMPTY_LIBRARY_NAME` is: `tools/` runs where this repository's test package need not be.
EPISODE_SUFFIXES = (".mkv", ".avi", ".mp4", ".ts", ".m4v")

#: The reference's own library-scan task, asked for by name after the tree has changed. Spelled the
#: way `tools/_reference.py` spells it, because the two are the same task.
SCAN_TASK_KEY = "RefreshLibrary"

#: How long a runner waits for a rescan of the composed fixture. 010 T11 measured that tree
#: scanning in 3 s with the fetchers off; a minute is a deadline against a wedged task rather than
#: a guess at the cost.
RESCAN_TIMEOUT = 120.0


def reference_rescan(wire: Wire, timeout: float = RESCAN_TIMEOUT) -> str:
    """Ask the reference to scan again and wait for the completion, not for the state.

    The trap is the one 010 T9 paid for: the scan task reads `Idle` *before* it starts as well as
    after it finishes, so what is waited for is a completion that did not exist a moment ago
    `[spec: GetTasks, TaskResult]`.
    """

    def finished_at() -> str:
        answer = wire.request("GET", "/ScheduledTasks")
        tasks = answer.body if isinstance(answer.body, list) else []
        for task in tasks:
            if isinstance(task, dict) and task.get("Key") == SCAN_TASK_KEY:
                result = task.get("LastExecutionResult") or {}
                return str(result.get("EndTimeUtc", "")) if isinstance(result, dict) else ""
        raise NamedError("the reference declares no library-scan task to wait on")

    before = finished_at()
    asked = wire.request("POST", "/Library/Refresh")
    if asked.status >= 400:
        raise NamedError(f"POST /Library/Refresh answered {asked.status}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        current = finished_at()
        if current and current != before:
            return current
    raise NamedError(f"the reference's rescan did not finish within {timeout:g}s")


#: Why neither `rescan` row is a comparison, measured against `surface.yaml` rather than assumed:
#: the reference's `POST /Library/Refresh` has no Atrium counterpart, so the second scan can be
#: asked of one server and not of the other.
NO_SECOND_SCAN = (
    "Atrium exposes no library-refresh route - `POST /Library/Refresh` is not in "
    "docs/compatibility/surface.yaml and has no named consumer (Principle VI) - so the second "
    "scan this row compares can be asked of the reference and not of Atrium. The instance was "
    "necessary and is not sufficient"
)


def _fixture_tree(instances: Instances) -> Path:
    if instances.fixture_root is None:
        raise NamedError(
            "this row changes a library between two scans, which means changing files: it needs "
            "--fixture-root naming the tree the instance is mounted over"
        )
    return Path(instances.fixture_root)


def named_container_that_lost_every_file(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 5.2, which carried the last UNVERIFIED claim in the compatibility documents.

    *"A disposable library on a server somebody owns - scanned, emptied of one series' episodes,
    scanned again"* is what that entry asks for, and it is what this does. The files are put back
    before the runner returns, whichever way the reading goes - and the reading taken on
    2026-09-02 was that the reference keeps the row, which is what Atrium does, so what the marker
    was hiding was a parity rather than a difference.
    """
    admin = administrator_of(identities)
    tree = _fixture_tree(instances)
    held = instances.wire("reference").as_seat(admin.identity("reference").token)
    directory = WireDirectory(held)
    user_id = admin.identity("reference").user_id
    series, ordinary, specials = series_with_specials(directory, user_id)
    episodes = ordinary + specials

    emptied = sorted(
        path
        for path in (tree / "Shows" / "The Series").rglob("*")
        if path.is_file() and path.suffix.lower() in EPISODE_SUFFIXES
    )
    if not emptied:
        raise NamedError(
            f"no episode files under {tree}/Shows/The Series: this row empties a container on "
            "disk, and the tree it was pointed at does not hold one"
        )
    saved = [(path, path.read_bytes()) for path in emptied]
    try:
        for path, _ in saved:
            path.unlink()
        reference_rescan(held)
        after = directory.get("/Items/" + str(series["Id"]), userId=user_id)
        still_there = isinstance(after, dict) and after.get("Id")
        children = (
            directory.get("/Shows/" + str(series["Id"]) + "/Episodes", userId=user_id) or {}
        ).get("Items", [])
        listed = [
            row
            for row in items_of(
                directory, user_id, includeItemTypes="Series", limit=LOOKUP_LIMIT, sortBy="SortName"
            )
            if str(row.get("Id")) == str(series["Id"])
        ]
    finally:
        for path, payload in saved:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        with contextlib.suppress(NamedError, WireError):
            reference_rescan(held)
    raise NamedError(
        "the reference half is measured and the comparison is not one. "
        f"MEASURED: a series of {len(episodes)} episode(s) emptied of every file and rescanned is "
        f"{'still fetchable' if still_there else 'GONE'} on the reference, with {len(children)} "
        f"episode(s) under it and {len(listed)} row(s) in a Series listing. NOT COMPARED: "
        + NO_SECOND_SCAN
    )


def named_replaced_poster_default_rescan(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 5.6: artwork replaced beside an untouched film, and a rescan at default depth."""
    admin = administrator_of(identities)
    tree = _fixture_tree(instances)
    held = instances.wire("reference").as_seat(admin.identity("reference").token)
    directory = WireDirectory(held)
    user_id = admin.identity("reference").user_id
    film = item_named(directory, user_id, "The Planted Poster", "Movie")
    posters = sorted(tree.glob("Decodable/Movies/The Planted Poster (2011)/poster.jpg"))
    if not posters:
        raise NamedError(f"no poster beside the planted film under {tree}")
    poster = posters[0]
    original = poster.read_bytes()
    before_tag = (film.get("ImageTags") or {}).get("Primary")
    before = held.request("GET", "/Items/" + str(film["Id"]) + "/Images/Primary")
    try:
        # The same encoder's other image, so the bytes really are different artwork rather than a
        # truncation the scan could notice for another reason.
        replacement = tree / "Decodable/Movies/The Planted Poster (2011)/backdrop.jpg"
        poster.write_bytes(replacement.read_bytes())
        reference_rescan(held)
        again = directory.get("/Items/" + str(film["Id"]), userId=user_id) or {}
        after_tag = (again.get("ImageTags") or {}).get("Primary")
        after = held.request("GET", "/Items/" + str(film["Id"]) + "/Images/Primary")
    finally:
        poster.write_bytes(original)
        with contextlib.suppress(NamedError, WireError):
            reference_rescan(held)
    raise NamedError(
        "the reference half is measured and the comparison is not one. "
        f"MEASURED: replacing the artwork beside an untouched film and rescanning at default "
        f"depth {'CHANGED' if before_tag != after_tag else 'did not change'} the image tag "
        f"({before_tag!r} -> {after_tag!r}) and "
        f"{'changed' if before.raw != after.raw else 'did not change'} the bytes it identifies "
        f"({len(before.raw)}B -> {len(after.raw)}B). NOT COMPARED: " + NO_SECOND_SCAN
    )


# -- shape 6: a reading after a deliberate wait -------------------------------------------------

#: How long the paused-session row stays silent. Longer than either server's reap threshold -
#: Atrium's is five minutes and 007's list prices the reference's at ten - because what is being
#: compared is the position each one commits **after** giving up on the session, and a wait that
#: reached only one of the two would compare a commit with a live ticker.
PAUSED_SESSION_SILENCE = 660.0

#: Where the paused report says the viewer is. Far enough in that a ticker that kept running is
#: unmistakable and short enough to sit inside every fixture film's runtime.
PAUSED_POSITION_TICKS = 10_000_000


def named_paused_session_ticker_freeze(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """007's list: ten minutes of deliberate silence against a paused session.

    Cited from the reference's source `[source: MediaBrowser.Controller/Session/SessionInfo.cs:23,
    373-451 @ v10.11.11]` and never seen on the wire, because nothing in a body carries elapsed
    time and because holding a write open for ten minutes is the one thing an operator's server
    must not be asked for.
    """
    admin = administrator_of(identities)
    sessions: Dict[str, Tuple[str, str]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        film = item_named(directory, user_id, "The Long Take", "Movie")
        play_session = "atrium-differential-paused-" + secrets.token_hex(4)
        body = {
            "ItemId": str(film["Id"]),
            "PlaySessionId": play_session,
            "PositionTicks": 0,
            "CanSeek": True,
        }
        directory.post_raw("/Sessions/Playing", body=body)
        paused = dict(body)
        paused.update({"PositionTicks": PAUSED_POSITION_TICKS, "IsPaused": True})
        directory.post_raw("/Sessions/Playing/Progress", body=paused)
        sessions[side] = (str(film["Id"]), play_session)

    print(
        f"differential.py: the paused-session row is staying silent for "
        f"{PAUSED_SESSION_SILENCE:.0f}s against both servers",
        file=sys.stderr,
    )
    time.sleep(PAUSED_SESSION_SILENCE)

    answers: Dict[str, Tuple[Any, Any]] = {}
    for side in SIDES:
        directory = instances.seated(side, admin)
        user_id = admin.identity(side).user_id
        item_id, _ = sessions[side]
        body = directory.get("/Items/" + item_id, userId=user_id) or {}
        data = body.get("UserData") or {}
        answers[side] = (data.get("PlaybackPositionTicks"), data.get("PlayedPercentage"))
    ours, theirs = answers["atrium"], answers["reference"]
    return NamedResult(
        row="paused-session-ticker-freeze",
        finding=(
            f"a session paused at {PAUSED_POSITION_TICKS} ticks and left silent for "
            f"{PAUSED_SESSION_SILENCE:.0f}s committed {ours[0]!r} here and {theirs[0]!r} there"
        ),
        atrium=f"PlaybackPositionTicks={ours[0]!r}, PlayedPercentage={ours[1]!r}",
        reference=f"PlaybackPositionTicks={theirs[0]!r}, PlayedPercentage={theirs[1]!r}",
        # The source reading says a paused session's ticker freezes, so the position committed is
        # the one that was reported. Atrium's extrapolation stops at a pause for the same reason.
        as_documented=ours[0] == PAUSED_POSITION_TICKS,
    )


# -- here to be recognised, not discovered ------------------------------------------------------
#
# The last two rows of spec section 3.10 are ordinary request cases (plan section 6.4). Their
# runner reads what the **sweep** did with them rather than issuing the request a second time: a
# row that re-asked would be a second measurement of one question, and the register's job for
# these two is to make them countable so nobody triages them twice.


def from_the_sweep(instances: Instances, row: str, case: str, what: str) -> NamedResult:
    """One register row answered out of the sweep's own comparisons."""
    mine = [comparison for comparison in instances.swept if comparison.case == case]
    if not mine:
        raise NamedError(
            f"the sweep issued no comparison of the request case {case!r}, which is where this "
            "row is found; it is a case of docs/compatibility/request-cases.yaml and not a "
            "request of this runner's own"
        )
    asked = [comparison for comparison in mine if comparison.ran]
    if not asked:
        raise NamedError(
            f"every comparison of {case!r} was unasked this run: "
            + "; ".join(sorted({comparison.unreachable for comparison in mine}))
        )
    findings = [
        (comparison.endpoint, finding) for comparison in asked for finding in comparison.differences
    ]
    endpoints = sorted({comparison.endpoint for comparison in asked})
    return NamedResult(
        row=row,
        finding=(
            f"{what}: the sweep asked {len(asked)} comparison(s) of {case!r} over "
            f"{len(endpoints)} endpoint(s) and reported {len(findings)} difference(s)"
        ),
        atrium=f"{len(asked)} comparisons issued over {', '.join(endpoints)}",
        reference=(
            ", ".join(f"{endpoint} {finding.pointer}" for endpoint, finding in findings[:4])
            or "no difference on any of them"
        ),
        as_documented=True,
    )


def named_body_binding_dollar_message(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """behaviours 1.11: the `"$"` key in a body-binding refusal, on the first malformed body."""
    return from_the_sweep(
        instances,
        "body-binding-dollar-message",
        "malformed-body",
        "the sentence a body-binding refusal names the whole body with",
    )


def named_body_with_no_content_type(
    instances: Instances, identities: Sequence[Seat]
) -> NamedResult:
    """009: the four routes of the five where a body with no `Content-Type` has never been asked."""
    return from_the_sweep(
        instances,
        "body-with-no-content-type",
        "body-with-no-content-type",
        "a required body arriving with no Content-Type at all",
    )


#: Every runner the register may name, by the name it names. **A dictionary and not `getattr`**,
#: because a register that could reach any callable in this module by writing its name is a
#: register that can call something that is not a runner; `tests/unit/test_allowlist.py` resolves
#: all twenty against this mapping, so a row naming a runner nobody wrote fails before a run.
RUNNERS: Dict[str, Callable[[Instances, Sequence[Seat]], NamedResult]] = {
    "named_playlist_read_names_its_reader": named_playlist_read_names_its_reader,
    "named_playlist_entries_a_reader_cannot_reach": named_playlist_entries_a_reader_cannot_reach,
    "named_playlist_de_duplication_misses": named_playlist_de_duplication_misses,
    "named_progressive_re_encode_header_frame": named_progressive_re_encode_header_frame,
    "named_subtitle_burn_in": named_subtitle_burn_in,
    "named_manifest_announced_track_name": named_manifest_announced_track_name,
    "named_subtitle_playlist_decimal_point": named_subtitle_playlist_decimal_point,
    "named_delivery_time_policy_refusal": named_delivery_time_policy_refusal,
    "named_image_subtitle_track_latency": named_image_subtitle_track_latency,
    "named_multi_part_film_media_sources": named_multi_part_film_media_sources,
    "named_media_source_no_runtime_and_zero_length_cue": (
        named_media_source_no_runtime_and_zero_length_cue
    ),
    "named_legacy_encoded_subtitle_file": named_legacy_encoded_subtitle_file,
    "named_exif_orientation_on_resize": named_exif_orientation_on_resize,
    "named_empty_library_played_state": named_empty_library_played_state,
    "named_container_that_lost_every_file": named_container_that_lost_every_file,
    "named_replaced_poster_default_rescan": named_replaced_poster_default_rescan,
    "named_next_up_pristine_specials_season": named_next_up_pristine_specials_season,
    "named_paused_session_ticker_freeze": named_paused_session_ticker_freeze,
    "named_body_binding_dollar_message": named_body_binding_dollar_message,
    "named_body_with_no_content_type": named_body_with_no_content_type,
}


def named_outcomes(
    register: Sequence[Any],
    inputs: Inputs,
    instances: Optional[Instances] = None,
    identities: Sequence[Seat] = (),
) -> Tuple[Tuple[NamedResult, ...], Tuple[Tuple[str, str], ...]]:
    """Every row of the register, run or **outstanding by name with its reason** (AC-16).

    Four gates, in this order, and the order is what makes a report readable. A row `--named` did
    not select is outstanding first, because nothing else about it was attempted. Then its
    `needs`, because *"four outstanding, and three of them because no fixture instance was
    available"* is a different sentence from *"four outstanding"* - the sentence plan section 4.2
    says `needs` earns the file for. Then the register's own `runner`, which is `none` while
    nobody has written one. Only then is the runner called.

    **A runner that raises leaves its row outstanding with the exception and the run continues.**
    Twenty comparisons that stopped at the first unaskable one would report nothing about the
    nineteen after it, and the nineteen are the point.
    """
    run: List[NamedResult] = []
    outstanding: List[Tuple[str, str]] = []
    for row in register:
        if inputs.named_selected is not None and row.id not in inputs.named_selected:
            outstanding.append((row.id, "not selected by --named"))
            continue
        blocked = unmet_needs(row.needs, inputs)
        if blocked:
            outstanding.append((row.id, "; ".join(blocked)))
            continue
        if row.is_outstanding:
            outstanding.append((row.id, "the register names no runner for it"))
            continue
        runner = RUNNERS.get(row.runner)
        if runner is None:
            outstanding.append(
                (row.id, f"the register names a runner {row.runner!r} this module does not have")
            )
            continue
        if instances is None:
            outstanding.append(
                (row.id, "this run has no servers to ask: a named comparison needs both of them")
            )
            continue
        try:
            run.append(runner(instances, identities))
        except Exception as failure:  # a runner that raises never stops the other nineteen
            outstanding.append((row.id, f"{type(failure).__name__}: {failure}"))
    return tuple(run), tuple(outstanding)


# --------------------------------------------------------------------------------------------
# The report
# --------------------------------------------------------------------------------------------


def repository_sha(root: Path) -> str:
    """The checked-out commit, read from `.git` rather than asked of a subprocess.

    The report names the Atrium it measured, because a difference is only reproducible against a
    commit. A worktree, a detached head or an archive answers `unknown`, which is the honest
    value: a report that invented a sha would be worse than one that admits it has none.
    """
    head = root / ".git" / "HEAD"
    try:
        content = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if content.startswith("ref:"):
        reference = content.split(" ", 1)[1].strip()
        try:
            return (root / ".git" / reference).read_text(encoding="utf-8").strip()[:12]
        except OSError:
            return "unknown"
    return content[:12] if content else "unknown"


def _class_lines(counts: Mapping[Any, int]) -> List[str]:
    """The five classes in severity order, missing keys first and labelled as such (AC-5)."""
    kinds = engine().Class
    labels = [
        (kinds.MISSING_KEY, "Missing keys", "   <-- read these first"),
        (kinds.EXTRA_KEY, "Extra keys", ""),
        (kinds.TYPE, "Type mismatches", ""),
        (kinds.LENGTH, "Length mismatches", ""),
        (kinds.ORDER, "Order mismatches", ""),
        (kinds.VALUE, "Value mismatches", ""),
    ]
    return [f"  {label:<20}({counts.get(klass, 0)}){note}" for klass, label, note in labels]


def _value(value: Any) -> str:
    """One side of a difference, short enough for a table and never a whole body."""
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    text = text.replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 80 else text[:77] + "..."


#: What the server writes its tally into, relative to its own data directory. Named here so that
#: `--ignored-parameters` can be pointed at a data *directory* as well as at the file itself,
#: which is what an operator has to hand.
IGNORED_PARAMETERS_FILE = "ignored-parameters.json"


def read_ignored_parameters(location: Path) -> Dict[str, Any]:
    """The tally Atrium wrote when it last stopped, from a file or from a data directory.

    **It is never this run\'s own sweep**, and the report says so rather than implying otherwise.
    The tally is complete only at shutdown - which is the whole reason 010 plan section 6.8 puts
    it there and not on a route - so a differential against a server that is still answering reads
    the tally of that server\'s *previous* run. Making it fresher would mean asking the server for
    it, and an endpoint serving it is the delta Principle I forbids.
    """
    path = location / IGNORED_PARAMETERS_FILE if location.is_dir() else location
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
        raise WireError(
            f"{path} is not an ignored-parameter tally: it has no `rows`. Atrium writes one into "
            f"its data directory when it stops (010 section 3.6)"
        )
    payload["source"] = str(path)
    return payload


def render_ignored_parameters(tally: Dict[str, Any]) -> str:
    """Spec section 3.6\'s report: parameter, endpoint, count and client (AC-10).

    005 section 3.3 accepts a bounded delta - a Tier 3 parameter is ignored rather than refused,
    and counted - and this is the closing mechanism it was accepted with. A parameter that appears
    here is promoted to Tier 2 or declined in writing; one that never appears is a delta nobody is
    paying for. The **client** column is what makes either decision possible, and it is the column
    D-5 added: a count with no name says how loud a parameter is and not who would notice it going
    away.
    """
    rows = list(tally.get("rows", []))
    lines = [
        "# Ignored parameters",
        "",
        f"    tally written        {tally.get('generated', 'unknown')}",
        f"    read from            {tally.get('source', 'unknown')}",
        f"    distinct rows        {len(rows)}",
        f"    requests counted     {tally.get('total', 0)}",
        "",
        "**This is the tally the server wrote when it last stopped, and never this run's own "
        "sweep.** The count is complete only after the last request a route could have answered, "
        "which is why it is a file in the data directory and not an endpoint: an endpoint serving "
        "it would be one Jellyfin does not have (Principle I).",
        "",
        "Every row is 005 section 3.3's accepted delta, still open. Promote the parameter to "
        "Tier 2, or decline it in writing.",
        "",
    ]
    if not rows:
        lines.append(
            "No client sent a parameter this server does not implement. That is a finding and "
            "not an empty report: the bounded delta cost nothing over the life of that process."
        )
        return "\n".join(lines) + "\n"
    lines.append("| Parameter | Endpoint | Count | Client |")
    lines.append("|---|---|---:|---|")
    for row in rows:
        lines.append(
            "| `{parameter}` | `{endpoint}` | {count} | {client} |".format(
                parameter=row.get("parameter", ""),
                endpoint=row.get("endpoint", ""),
                count=row.get("count", 0),
                client=row.get("client", "unknown"),
            )
        )
    return "\n".join(lines) + "\n"


def render(report: RunReport) -> str:
    """Spec section 3.4\'s report, and the sections that keep it from reading like a clean one."""
    counts: Dict[Any, int] = dict.fromkeys(engine().Class, 0)
    for _comparison, finding in report.differences:
        counts[finding.klass] = counts.get(finding.klass, 0) + 1

    lines: List[str] = []
    header = dict(report.provenance)
    lines.append(
        "# Differential run - Atrium {atrium} vs Jellyfin {reference} - {date}".format(
            atrium=header.get("atrium sha", "unknown"),
            reference=header.get("reference version", "unknown"),
            date=header.get("date", "unknown"),
        )
    )
    lines.append("")
    lines.append("```")
    for name, value in report.provenance:
        lines.append(f"  {name:<24}{value}")
    lines.append("")
    lines.append(f"  {'identities':<24}{len(report.identities)} ({', '.join(report.identities)})")
    lines.append(
        f"  {'endpoints compared':<24}{len(report.endpoints_compared)} of {len(report.endpoints)}"
    )
    lines.append(f"  {'request cases':<24}{report.cases} declared")
    lines.append(f"  {'comparisons':<24}{len(report.comparisons)}")
    lines.append(f"  {'identical':<24}{report.identical}")
    lines.append(f"  {'allowlisted':<24}{report.excused} findings suppressed by an entry")
    lines.append(f"  {'NOT ASKED':<24}{len(report.unasked)}")
    lines.append(f"  {'DIFFERENCES':<24}{len(report.differences)}")
    lines.append(
        f"  {'known divergences':<24}{len(report.known_divergences)} "
        "(argued in behaviours.md, reported every run)"
    )
    lines.append("")
    lines.extend(_class_lines(counts))
    lines.append("")
    lines.append(
        f"  {'Named comparisons':<20}({len(report.named_run)} of the section 3.10 list run, "
        f"{len(report.named_outstanding)} outstanding)"
    )
    if report.incidents:
        lines.append("")
        lines.append(f"  {'INCIDENTS':<24}{len(report.incidents)} - THIS RUN DID NOT FINISH")
    lines.append("")
    lines.append("  " + ("THIS RUN IS CLEAN." if report.is_clean() else "THIS RUN IS NOT CLEAN."))
    lines.append("```")
    lines.append("")

    lines.extend(_incidents_section(report))
    lines.extend(_conclusions(report))
    lines.extend(_coverage_section(report))
    lines.extend(_unasked_section(report))
    lines.extend(_named_section(report))
    lines.extend(_differences_section(report))
    lines.extend(_known_section(report))
    lines.extend(_entries_section(report))
    return "\n".join(lines) + "\n"


def _incidents_section(report: RunReport) -> List[str]:
    """What went wrong with the run itself, at the top, before any table of zeros.

    A report that exists because the run was salvaged has to say so in its first paragraph. The
    numbers below it are real - they were measured before whatever this section names - and every
    comparison the incident cost is in *Cases this run did not ask* with its own reason.
    """
    if not report.incidents:
        return []
    lines = ["## This run did not finish", ""]
    lines.append(
        "**The report below is what the run had measured when it stopped, and not a complete "
        "sweep.** It is written rather than discarded because a run that dies still found what "
        "it found; every case it never reached is listed as not asked, with the reason."
    )
    lines.append("")
    for incident in report.incidents:
        lines.append(f"- {incident}")
    lines.append("")
    return lines


def _conclusions(report: RunReport) -> List[str]:
    """What a reader may and may not conclude from this run, computed from the run itself.

    **This section exists because the report is where this feature can lie.** A run that could not
    reach a server, could not seat an identity or skipped a case produces a document that looks
    exactly like a clean one unless it says otherwise in its own words, at the top, before the
    reader reaches a table of zeros.
    """
    lines = ["## What this report does and does not say", ""]
    missing = [role for role in registers().ROLES if role not in report.identities]
    if report.is_clean():
        lines.append(
            "Every declared case was issued to both servers as every seat it is meaningful for, "
            "every difference is accounted for, and every named comparison ran. That is the "
            "strongest thing this project can say."
        )
    else:
        lines.append("**This run is not clean, and these are the reasons.**")
        lines.append("")
    if report.incidents:
        lines.append(
            f"- {len(report.incidents)} **incidents**: the run did not finish. Nothing below is "
            "evidence about a case the run never reached, and the coverage table is a table of "
            "what this run managed rather than of what the register declares."
        )
    if report.differences:
        lines.append(
            f"- {len(report.differences)} differences are untriaged. Each belongs to the feature "
            "that owns its endpoint, through behaviours.md section 3.0 - the harness triages, it "
            "does not decide (spec section 2)."
        )
    if report.unasked:
        lines.append(
            f"- {len(report.unasked)} declared cases were **not issued**. A case that was not "
            "issued did not agree; it was not asked. They are listed below with the reason."
        )
    if report.named_outstanding:
        registered = len(report.named_run) + len(report.named_outstanding)
        lines.append(
            f"- {len(report.named_outstanding)} of the {registered} named comparisons are "
            "outstanding. These are the differences a sweep cannot raise at all (spec section "
            "3.10), so their absence here is not evidence of their absence there."
        )
    if report.named_undocumented:
        lines.append(
            f"- {len(report.named_undocumented)} named comparisons **ran and measured something "
            "the entry they cite does not predict**. That is an untriaged difference arriving "
            "through a runner rather than through the comparison engine, and it is either a "
            "defect or a compatibility document that has gone stale."
        )
    if missing:
        lines.append(
            "- This run authenticated as "
            f"{len(report.identities)} of {len(registers().ROLES)} seats and did not have: "
            f"{', '.join(missing)}. Twelve of twenty-three reads of this surface answer "
            "differently to a restricted non-administrator, two of them as *shorter lists* "
            "rather than as refusals "
            "`[probe: tools/probe_restricted_surface.py, Jellyfin 10.11.11, 2026-09-01]`."
        )
    lines.append("")
    lines.append(
        "In every case: **an agreement here is an agreement about the requests in "
        "`docs/compatibility/request-cases.yaml`, from the seats named above, on the libraries "
        "the two servers happened to hold.** It is not a statement about the endpoints those "
        "cases do not exercise."
    )
    lines.append("")
    return lines


def _coverage_section(report: RunReport) -> List[str]:
    lines = ["## Coverage, per identity and per declared level", ""]
    lines.append("| Identity | Cases issued | Cases not issued |")
    lines.append("|---|---|---|")
    for identity, issued, skipped in report.coverage():
        lines.append(f"| {identity} | {issued} | {skipped} |")
    lines.append("")
    by_seat = report.endpoints_compared_by()
    lines.append("| Endpoint | Declared level | Compared | By which seats |")
    lines.append("|---|---|---|---|")
    for endpoint in report.endpoints:
        seats = by_seat.get(endpoint.key, ())
        if not seats:
            reached, who = "**no**", "-"
        elif len(seats) == len(report.identities):
            reached, who = "yes", ", ".join(seats)
        else:
            reached, who = "**partly**", ", ".join(seats)
        lines.append(f"| `{endpoint.key}` | {endpoint.level} | {reached} | {who} |")
    lines.append("")
    lines.append(
        "**`partly` is not `yes`.** Twelve of twenty-three reads of this surface answer "
        "differently to a restricted non-administrator (spec section 3.9), two of them as shorter "
        "lists rather than as refusals - so an endpoint compared from the administrator's seat "
        "alone has been compared from the one seat that can be refused nothing, and its declared "
        "level is a claim this run did not pay for."
    )
    lines.append("")
    return lines


def _unasked_section(report: RunReport) -> List[str]:
    if not report.unasked:
        return []
    lines = ["## Cases this run did not ask, and why", ""]
    lines.append("| Endpoint | Case | Identity | Why not |")
    lines.append("|---|---|---|---|")
    for comparison in report.unasked:
        lines.append(
            f"| `{comparison.endpoint}` | {comparison.case} | {comparison.identity} | "
            f"{comparison.unreachable} |"
        )
    lines.append("")
    return lines


def _named_section(report: RunReport) -> List[str]:
    lines = ["## The named comparisons (spec section 3.10)", ""]
    lines.append(
        f"{len(report.named_run)} run, {len(report.named_outstanding)} outstanding. "
        "An outstanding one keeps this run from being clean: these are the twenty differences a "
        "sweep cannot raise, so a report without them is reporting the absence of the questions "
        "it did not ask."
    )
    lines.append("")
    if report.named_run:
        lines.append("| Ran | What it found | Atrium | Reference | As documented |")
        lines.append("|---|---|---|---|---|")
        for result in report.named_run:
            lines.append(
                f"| {result.row} | {result.finding} | {_value(result.atrium)} | "
                f"{_value(result.reference)} | {'yes' if result.as_documented else '**NO**'} |"
            )
        lines.append("")
        if report.named_undocumented:
            lines.append(
                "**"
                + str(len(report.named_undocumented))
                + " of the rows that ran measured something the entry they cite does not "
                "predict**, which is an untriaged difference and keeps this run from being "
                "clean: " + ", ".join(result.row for result in report.named_undocumented)
            )
            lines.append("")
    if report.named_outstanding:
        lines.append("| Outstanding | Why |")
        lines.append("|---|---|")
        for row, why in report.named_outstanding:
            lines.append(f"| {row} | {why} |")
        lines.append("")
    return lines


def _differences_section(report: RunReport) -> List[str]:
    if not report.differences:
        return []
    lines = ["## Differences, missing keys first", ""]
    lines.append("| Class | Endpoint | Case | Identity | Pointer | Atrium | Reference |")
    lines.append("|---|---|---|---|---|---|---|")
    ordered = sorted(
        report.differences,
        key=lambda pair: (pair[1].klass.value, pair[0].endpoint, pair[0].case, pair[1].pointer),
    )
    for comparison, finding in ordered:
        lines.append(
            f"| {finding.klass.name} | `{comparison.endpoint}` | {comparison.case} | "
            f"{comparison.identity} | `{finding.pointer}` | {_value(finding.atrium)} | "
            f"{_value(finding.reference)} |"
        )
    lines.append("")
    return lines


def _known_section(report: RunReport) -> List[str]:
    if not report.known_divergences:
        return []
    lines = ["## Known divergences, reported every run", ""]
    lines.append(
        "Each of these has a written argument and an allowlist row. They are reported rather "
        "than excused because the number itself is the regression check: `Similar` answers "
        "`limit + 4` rows on a movie seed, and the day it stops being exactly four this line "
        "changes."
    )
    lines.append("")
    lines.append("| Endpoint | Case | Pointer | Atrium | Reference | Argued in |")
    lines.append("|---|---|---|---|---|---|")
    for comparison, finding, because in report.known_divergences:
        lines.append(
            f"| `{comparison.endpoint}` | {comparison.case} | `{finding.pointer}` | "
            f"{_value(finding.atrium)} | {_value(finding.reference)} | {because} |"
        )
    lines.append("")
    return lines


def _entries_section(report: RunReport) -> List[str]:
    if not report.unused_entries:
        return []
    lines = ["## Allowlist entries that excused nothing on this run", ""]
    lines.append(
        "The allowlist is a metric and it should shrink (spec section 3.3). An entry that "
        "excuses nothing is either wrong, or a difference that has converged and can be deleted "
        "- or a scope this run never reached, which the coverage table above says."
    )
    lines.append("")
    lines.append("| Kind | Endpoint | Pointer |")
    lines.append("|---|---|---|")
    for kind, endpoint, pointer in report.unused_entries:
        lines.append(f"| {kind} | `{endpoint}` | `{pointer}` |")
    lines.append("")
    return lines


# --------------------------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------------------------

#: The environment variable that points at the reference. **`JELLYFIN_URL`, and not a second
#: name.** `conformance.md` published a different, longer name as the switch that makes L3
#: opt-in, and it appeared nowhere in this repository - no code read it and no test skipped on it
#: - while the 53 probes and `.env.example` have used this one since 002. The mechanism that
#: sentence described was real and its name was a claim about an implementation that did not
#: exist; the name here is the one that does, and `conformance.md` is corrected in the same
#: commit that makes it true.
ENV_REFERENCE_URL = "JELLYFIN_URL"
ENV_REFERENCE_USERNAME = "JELLYFIN_USERNAME"
ENV_REFERENCE_PASSWORD = "JELLYFIN_PASSWORD"  # noqa: S105
ENV_REFERENCE_TOKEN = "JELLYFIN_TOKEN"  # noqa: S105

#: Atrium's own seat. The reference's four names already existed; these three did not, because
#: nothing in `tools/` had ever authenticated against **this** server.
#: The two stems `handed_seats` builds a seat's environment names from. A seat handed in is one
#: this run signs in as and never owns, which is what a server implementing only the v1 surface
#: needs: `POST /Users/New` is not in it (010 T12).
ENV_ATRIUM_SEAT_PREFIX = "ATRIUM_"
ENV_REFERENCE_SEAT_PREFIX = "JELLYFIN_"

ENV_ATRIUM_USERNAME = "ATRIUM_USERNAME"
ENV_ATRIUM_PASSWORD = "ATRIUM_PASSWORD"  # noqa: S105
ENV_ATRIUM_TOKEN = "ATRIUM_TOKEN"  # noqa: S105

#: What the report header says where an instance goes, when this run has none.
_NO_INSTANCE = "none was stood up, so every row that needs one is outstanding"

#: And the line beside the Atrium sha that names **which** reference was measured. The image is
#: pinned by digest and the run prints it, so that a difference reproducing on one machine and not
#: on another has somewhere to be looked up (plan section 9's risk row).
_NO_DIGEST = "no instance was stood up by this run"

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SURFACE = REPOSITORY_ROOT / "docs" / "compatibility" / "surface.yaml"
DEFAULT_REPORT_DIRECTORY = REPOSITORY_ROOT / "reference"

#: Where a `--fixture` run builds and mounts the tree when the caller names no other. Git-ignored,
#: regenerable, and outside `tempfile`'s directory - which on macOS is a path the container runtime
#: does not share, so an instance mounted from there starts, finds nothing, and times out three
#: minutes later with `--rm` having already removed the evidence (010 T10).
DEFAULT_FIXTURE_TREE = REPOSITORY_ROOT / "reference" / "fixture-tree"


def fixture_entry_point() -> Any:
    """`tests/fixtures/reference_tree.py`, the entry point plan section 6.6 names.

    **Imported rather than reimplemented, and this is what 010 T12 found missing.** A `--fixture`
    run stood the instance up with `_reference.DEFAULT_LIBRARIES` - *one mixed-content library
    over the whole tree* - where D-4 chose **six typed** ones and 010 T11 composed them. The
    difference is not cosmetic: a mixed library has no `CollectionType`, so the run could not find
    a movies view to narrow the restricted seat to and refused to start, and AC-2's own world was
    not the world a fixture run was comparing. The same import `tools/probe_reference_scan.py`
    makes, for the same reason: a second declaration would disagree with the first the day either
    changed.
    """
    root = str(REPOSITORY_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tests.fixtures import reference_tree

    return reference_tree


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="differential.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "L3, the differential layer: issue the same request to Atrium and to a real "
            "Jellyfin, as each identity, and compare the answers structurally. The report is the "
            "deliverable and not a pass/fail line - it names every difference, every case this "
            "run could not issue and every named comparison it did not run, because outstanding "
            "is not green."
        ),
        epilog=(
            "Exit codes: 0 the run is clean, 1 the run is not clean (differences, unasked cases "
            "or outstanding named comparisons), 2 the run could not start.\n"
            "No CI job runs this: no job may contact a Jellyfin, and a gate that depends on "
            "somebody else's uptime is not a gate (010 plan section 6.11).\n"
            f"Credentials come from .env: {ENV_REFERENCE_URL}, {ENV_REFERENCE_USERNAME}, "
            f"{ENV_REFERENCE_PASSWORD}, {ENV_REFERENCE_TOKEN} for the reference and "
            f"{ENV_ATRIUM_USERNAME}, {ENV_ATRIUM_PASSWORD}, {ENV_ATRIUM_TOKEN} for Atrium."
        ),
    )
    parser.add_argument("--atrium", help="Base URL of the Atrium under test")
    parser.add_argument(
        "--jellyfin", help=f"Base URL of the reference. Defaults to ${ENV_REFERENCE_URL}"
    )
    parser.add_argument("--surface", type=Path, default=DEFAULT_SURFACE)
    parser.add_argument(
        "--report",
        type=Path,
        help="Where to write the report. Defaults to reference/differential-<date>-<sha>.md, "
        "which is git-ignored, regenerable, and the input to nothing",
    )
    parser.add_argument(
        "--identity",
        action="append",
        choices=[role.value for role in Role],
        help="A seat to authenticate as; repeatable. Defaults to the administrator and a "
        "restricted non-administrator, which is spec section 3.9's minimum. A run with one is "
        "reported as covering one",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
        help="Ask the half that needs a reference instance over this repository's own fixture. "
        "Without one, every case and named row that needs it is reported OUTSTANDING with the "
        "reason rather than skipped",
    )
    parser.add_argument(
        "--named",
        action="append",
        help="Run only these named comparisons, by id; repeatable. The others are still listed, "
        "outstanding, because AC-16 counts all twenty either way",
    )
    parser.add_argument(
        "--only-named",
        action="store_true",
        help="Attempt the named comparisons and not the sweep. Every declared request case is "
        "then reported NOT ASKED with that reason and the run is not clean - it is a way to "
        "re-run one comparison without re-issuing every case, never a smaller kind of run",
    )
    parser.add_argument(
        "--reference-url",
        default="",
        help="A reference instance somebody else stood up, for the --fixture half. Given one, "
        "this run does not stand up its own",
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=None,
        help="Where the fixture tree lives, mounted read-only. Defaults to "
        f"{DEFAULT_FIXTURE_TREE}, built through tests.fixtures.reference_tree when it is not "
        "there. Which world that is, and in how many libraries, is D-4 - measured by "
        "tools/probe_reference_scan.py and composed by 010 T11 into six typed libraries",
    )
    parser.add_argument(
        "--ignored-parameters",
        type=Path,
        default=None,
        help="Atrium's data directory, or the ignored-parameters.json in it. Given one, the run "
        "also writes reference/ignored-parameters-<date>.md - spec section 3.6's report, with "
        "parameter, endpoint, count and client. The tally is the one that server wrote when it "
        "last stopped, which is the only moment it is complete",
    )
    parser.add_argument("--timeout", type=int, default=30)
    return parser


class FixtureInstance:
    """The single-use reference instance a run stands up around its own sweep, or the reason not.

    **It never fails the run**, which is ADR-0007's degradation and not politeness: a machine with
    no runtime still sweeps a reachable server and runs everything in the default CI job, and what
    it loses is reported outstanding with the reason rather than skipped. So `__enter__` catches
    what `tools/_reference.py` raises and turns it into `reason`, which `unmet_need` prints
    against every `needs: fixture`, `rescan` and `wait` row.

    A context manager wrapping the sweep and nothing else (plan section 6.5): the seats die with
    the roster inside it, and the instance dies after them.
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.url = args.reference_url or ""
        self.digest = ""
        self.reason = ""
        #: The account the instance's own wizard created, when this run stood one up. `None` for a
        #: reference somebody else is running, whose administrator is in `.env` and not here -
        #: which is 010 T9's correction to plan section 5 arriving where it is consumed.
        self.administrator: Any = None
        self._instance: Any = None

    def __enter__(self) -> FixtureInstance:
        if self.url or not self.args.fixture:
            return self
        module = _sibling("_reference")
        try:
            tree = fixture_entry_point()
        except ImportError as failure:
            self.reason = (
                f"the fixture tree is built by tests.fixtures.reference_tree and it could not be "
                f"imported from {REPOSITORY_ROOT}: {failure}"
            )
            return self
        root = Path(self.args.fixture_root) if self.args.fixture_root else DEFAULT_FIXTURE_TREE
        try:
            if not root.is_dir() or not any(root.iterdir()):
                tree.build(root)
            libraries = tuple(
                module.Library(
                    name=library.name,
                    collection_type=library.collection_type,
                    subpath=library.subpath,
                )
                for library in tree.libraries()
            )
        except Exception as failure:  # building the tree encodes media, which needs ffmpeg
            self.reason = f"the fixture tree at {root} could not be built: {failure}"
            return self
        spec = module.InstanceSpec(fixture_root=root, libraries=libraries)
        instance = module.ReferenceInstance(spec)
        try:
            instance.__enter__()
        except module.InstanceError as failure:
            self.reason = str(failure)
            return self
        self._instance = instance
        self.url = instance.url
        self.digest = instance.digest
        self.administrator = instance.administrator
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if self._instance is not None:
            self._instance.__exit__(exc_type, exc, traceback)
            self._instance = None


def run(
    atrium: Wire,
    reference: Wire,
    endpoints: Sequence[Endpoint],
    cases: Sequence[Any],
    entries: Sequence[Any],
    named: Sequence[Any],
    seats: Sequence[Seat],
    inputs: Inputs,
    provenance: Sequence[Tuple[str, str]] = (),
    fixture_root: Optional[Path] = None,
) -> RunReport:
    """The sweep, the named comparisons and the report, over servers that are already seated.

    **The sweep runs first and the named comparisons second, and the order is load-bearing.** Two
    of the twenty rows are ordinary request cases (plan section 6.4) whose runner reads what the
    sweep did with them rather than asking again, and every runner that writes - a playlist, a
    played mark, a paused session - writes after the sweep has read, so that nothing the sweep
    compares was put there by a runner.
    """
    # One wire, one token and **one device** per seat per side: the reference binds a token to the
    # device that holds it, so two accounts sharing a `DeviceId` are one session and the older of
    # them is logged out (010 T12).
    issuers = {
        side: Issuer(
            side,
            {
                seat.role: wire.as_seat(
                    seat.identity(side).token,
                    device=device_for(seat.credentials(side)[0] or seat.role),
                )
                for seat in seats
            },
            cases,
        )
        for side, wire in (("atrium", atrium), ("reference", reference))
    }
    # Filled by the sweep as it goes: an entry that suppressed a finding on any comparison is one
    # this run can say excused something, and the rest are reported (plan section 7).
    used: set = set()
    incidents: List[str] = []
    try:
        comparisons = sweep(endpoints, cases, entries, seats, issuers, inputs, used)
    except Exception as failure:
        # `compare_case` catches per case, so reaching here is the loop's own scaffolding failing
        # and not a request. Every comparison the run declared becomes an unreached row with this
        # reason, which is the difference between a report that is short and a report that lies.
        incidents.append(f"the sweep did not finish: {type(failure).__name__}: {failure}")
        comparisons = unreached(endpoints, cases, seats, f"the sweep did not finish: {failure}")
    try:
        ran, outstanding = named_outcomes(
            named,
            inputs,
            Instances(
                atrium=atrium,
                reference=reference,
                inputs=inputs,
                swept=comparisons,
                fixture_root=fixture_root,
            ),
            seats,
        )
    except Exception as failure:
        incidents.append(f"the named comparisons did not run: {type(failure).__name__}: {failure}")
        ran, outstanding = (), tuple((row.id, str(failure)) for row in named)
    return RunReport(
        identities=tuple(seat.role for seat in seats),
        cases=len(cases),
        comparisons=comparisons,
        named_run=ran,
        named_outstanding=outstanding,
        endpoints=tuple(endpoints),
        provenance=tuple(provenance),
        unused_entries=unused_entries(entries, used),
        incidents=tuple(incidents),
    )


def unreached(
    endpoints: Sequence[Endpoint],
    cases: Sequence[Any],
    seats: Sequence[Seat],
    why: str,
) -> Tuple[Comparison, ...]:
    """Every comparison this run declared, as a row saying it did not happen and why.

    The salvage path's version of the sweep: same three loops, same order, no request. It exists
    so that a run which died still reports the shape of what it was going to ask, rather than an
    empty table a reader would mistake for a small surface.
    """
    roster_names = tuple(seat.role for seat in seats)
    cases_for = registers().cases_for
    return tuple(
        Comparison(
            endpoint=endpoint.key,
            level=endpoint.level,
            case=case.id,
            identity=seat.role,
            unreachable=why,
        )
        for seat in seats
        for endpoint in endpoints
        for case in cases_for(cases, endpoint.key)
        if seat.role in case.identities_for(roster_names)
    )


def unused_entries(entries: Sequence[Any], used: Sequence[Any]) -> Tuple[Tuple[str, str, str], ...]:
    """Every allowlist entry that excused nothing on this run (plan section 7)."""
    seen = set(used)
    return tuple(
        (entry.kind, entry.endpoint, entry.pointer)
        for entry in entries
        if (entry.kind, entry.endpoint, entry.pointer, entry.case) not in seen
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # **What the run had measured when it stopped, if it stopped after measuring anything.**
    # Filled the moment `run()` returns, so that everything after it - the roster teardown, the
    # instance teardown - can fail without taking the findings with it. The first full sweep
    # (2026-09-03) completed 64 comparisons, met a reference that had died, and wrote no report at
    # all, because a failed `DELETE /Users` came out of a context manager `main()` was standing
    # outside of. A report is the deliverable (spec section 3.4); losing it to a teardown is the
    # one failure this program must not have.
    salvage: List[Tuple[RunReport, Path]] = []
    try:
        report, destination = _execute(args, salvage)
    except (GuardError, SeatError, WireError, UnreachableError) as failure:
        print(f"differential.py: {failure}", file=sys.stderr)
        if not salvage:
            return 2
        report, destination = _salvaged(salvage, failure)
    except Exception as failure:  # a harness that dies silently is worse than one that says so
        print(f"differential.py: the run could not start: {failure}", file=sys.stderr)
        if not salvage:
            return 2
        report, destination = _salvaged(salvage, failure)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(report), encoding="utf-8")
    print(f"differential.py: report written to {destination}")
    if args.ignored_parameters is not None:
        try:
            tally = read_ignored_parameters(Path(args.ignored_parameters))
        except (OSError, ValueError, WireError) as unread:
            print(f"differential.py: no ignored-parameter report: {unread}", file=sys.stderr)
        else:
            beside = destination.parent / (
                f"ignored-parameters-{datetime.now(timezone.utc).date().isoformat()}.md"
            )
            beside.write_text(render_ignored_parameters(tally), encoding="utf-8")
            print(f"differential.py: ignored-parameter report written to {beside}")
    print(
        f"differential.py: {len(report.differences)} differences, {len(report.unasked)} cases not "
        f"asked, {len(report.named_outstanding)} named comparisons outstanding."
    )
    return 0 if report.is_clean() else 1


def _salvaged(
    salvage: Sequence[Tuple[RunReport, Path]], failure: BaseException
) -> Tuple[RunReport, Path]:
    """The report the run had produced, with what killed the run recorded on it.

    Exit code 1 and not 2: a run that measured 64 comparisons and then lost its reference did
    *not* fail to start, and calling it that would file a report full of findings under the code
    that means there is nothing to read. `incidents` is what keeps it from ever reading clean.
    """
    report, destination = salvage[-1]
    return (
        replace(
            report,
            incidents=(
                *report.incidents,
                f"the run stopped after the sweep: {type(failure).__name__}: {failure}",
            ),
        ),
        destination,
    )


def reference_credentials(instance: FixtureInstance) -> Tuple[str, str, str]:
    """Whose account this run holds on the reference: the environment's, or the instance's own.

    **An instance the run stood up has no operator**, and its administrator is the one its own
    setup wizard created seconds ago (plan section 6.5). `.env`\'s credentials belong to somebody
    else\'s server and would authenticate against nothing here, so the run takes the wizard\'s -
    which is 010 T9\'s correction to plan section 5 arriving at the caller it was written for.
    """
    if instance.administrator is not None:
        return instance.administrator.username, instance.administrator.password, ""
    return (
        os.environ.get(ENV_REFERENCE_USERNAME, ""),
        os.environ.get(ENV_REFERENCE_PASSWORD, ""),
        os.environ.get(ENV_REFERENCE_TOKEN, ""),
    )


def _execute(
    args: argparse.Namespace, salvage: Optional[List[Tuple[RunReport, Path]]] = None
) -> Tuple[RunReport, Path]:
    """Everything a real run does, from the environment to the seated servers.

    `salvage` is the caller's out-parameter and not a return value, because the failures it exists
    for happen on the way *out* of this function - a roster teardown, an instance teardown - where
    a return value no longer has anywhere to go.
    """
    probe = _sibling("_probe")
    probe.load_env_file()
    with FixtureInstance(args) as instance:
        return _run_against(args, instance, salvage)


def _run_against(
    args: argparse.Namespace,
    instance: FixtureInstance,
    salvage: Optional[List[Tuple[RunReport, Path]]] = None,
) -> Tuple[RunReport, Path]:
    """One run, inside the instance\'s own context so the instance outlives everything it holds.

    **The instance is stood up before the reference is authenticated, not around the sweep**, and
    010 T12 moved it there because the earlier order compared the wrong server. `--fixture` means
    *the fixture on both servers* (AC-2); every `needs: fixture` request case resolves its anchor
    against the reference under comparison, and every fixture-dependent named comparison asks that
    same reference for a film by name. With the instance stood up beside a `--jellyfin` pointing
    somewhere else, all of them would have been asked of a server that has never seen this
    repository\'s tree - and answered `404` rather than reporting a difference. So when a run has
    an instance, **the instance is the reference**.
    """
    atrium_url = args.atrium or ""
    reference_url = instance.url or args.jellyfin or os.environ.get(ENV_REFERENCE_URL, "")
    if not atrium_url or not reference_url:
        raise GuardError(
            "a differential needs both servers: pass --atrium and --jellyfin (or set "
            f"{ENV_REFERENCE_URL} in .env). One server is not a differential"
        )
    if instance.url and args.jellyfin and args.jellyfin.rstrip("/") != instance.url.rstrip("/"):
        raise GuardError(
            f"--fixture stood up a reference instance at {instance.url} and --jellyfin names "
            f"{args.jellyfin}: a fixture run compares Atrium with the server holding the fixture, "
            "and asking one server for the anchors while comparing another is how a run reports "
            "404s as coverage"
        )

    atrium = Wire(
        atrium_url,
        timeout=args.timeout,
        device=device_for(os.environ.get(ENV_ATRIUM_USERNAME, "") or "atrium-administrator"),
    )
    reference = Wire(
        reference_url,
        timeout=args.timeout,
        device=device_for(reference_credentials(instance)[0] or "reference-administrator"),
    )
    check_two_servers(
        atrium.request("GET", "/System/Info/Public").headers,
        reference.request("GET", "/System/Info/Public").headers,
    )

    reference_username, reference_password, reference_token = reference_credentials(instance)
    administrators = {
        "atrium": authenticate(
            atrium,
            os.environ.get(ENV_ATRIUM_USERNAME, ""),
            os.environ.get(ENV_ATRIUM_PASSWORD, ""),
            os.environ.get(ENV_ATRIUM_TOKEN, ""),
        ),
        "reference": authenticate(
            reference, reference_username, reference_password, reference_token
        ),
    }
    credentials = {
        "atrium": (
            os.environ.get(ENV_ATRIUM_USERNAME, ""),
            os.environ.get(ENV_ATRIUM_PASSWORD, ""),
        ),
        "reference": (reference_username, reference_password),
    }

    roles = tuple(
        Role(value)
        for value in (args.identity or [Role.ADMINISTRATOR.value, Role.RESTRICTED.value])
    )
    if Role.ADMINISTRATOR not in roles:
        roles = (Role.ADMINISTRATOR, *roles)

    entries = registers().load()
    named = registers().load_named()
    cases = registers().load_cases(entries=entries)
    endpoints = load_endpoints(args.surface)

    directories = {
        "atrium": WireDirectory(atrium),
        "reference": WireDirectory(reference),
    }
    handed = {
        "atrium": handed_seats(ENV_ATRIUM_SEAT_PREFIX, roles),
        "reference": handed_seats(ENV_REFERENCE_SEAT_PREFIX, roles),
    }
    rosters = {
        side: Roster(
            directories[side],
            administrators[side],
            roles,
            library_id=(
                movies_library_id(directories[side], administrators[side].user_id)
                if Role.RESTRICTED in roles and Role.RESTRICTED not in handed[side]
                else None
            ),
            sign_in=sign_in_against(url, timeout=args.timeout),
            handed=handed[side],
        )
        for side, url in (("atrium", atrium_url), ("reference", reference_url))
    }

    public = reference.request("GET", "/System/Info/Public")
    version = public.body.get("Version", "unknown") if isinstance(public.body, dict) else "unknown"
    ours_says = header_value(atrium.request("GET", "/System/Ping").headers, SERVER_HEADER)
    theirs_says = header_value(public.headers, SERVER_HEADER)

    # **The rosters are entered inside the instance's context** (010 T8's note, plan section 6.5):
    # the seats die before the server that holds them, and the instance dies after them on both
    # paths - which is why `_execute` opens the context and this function is called inside it. An
    # instance that could not be stood up is not a failure here: `FixtureInstance` carries the
    # reason, and every case and named row that needed one says it.
    inputs = Inputs(
        roles=tuple(role.value for role in roles),
        instance_url=instance.url,
        fixture_asked=bool(args.fixture),
        named_selected=tuple(args.named) if args.named else None,
        instance_reason=instance.reason,
        only_named=bool(args.only_named),
    )
    provenance = [
        ("date", datetime.now(timezone.utc).date().isoformat()),
        ("atrium sha", repository_sha(REPOSITORY_ROOT)),
        ("atrium", atrium_url + "  " + ours_says),
        ("reference", reference_url + "  " + theirs_says),
        ("reference version", str(version)),
        ("reference instance", instance.url or _NO_INSTANCE),
        ("reference image digest", instance.digest or _NO_DIGEST),
        ("surface", str(args.surface)),
    ]
    today = datetime.now(timezone.utc).date().isoformat()
    default = (
        DEFAULT_REPORT_DIRECTORY / f"differential-{today}-{repository_sha(REPOSITORY_ROOT)}.md"
    )
    destination = Path(args.report or default)

    # **The report is handed to the caller the instant it exists, and again at the end.** Where
    # the two teardowns below can raise - and the roster's does, by design, on a seat it could not
    # delete - a `return` has nowhere to go, so the findings leave through `salvage` first.
    report: Optional[RunReport] = None
    try:
        with rosters["atrium"] as ours, rosters["reference"] as theirs:
            seats = [
                Seat(
                    role=role.value,
                    atrium=ours[role],
                    reference=theirs[role],
                    atrium_credentials=(
                        credentials["atrium"]
                        if role is Role.ADMINISTRATOR
                        else ours.credentials_for(role)
                    ),
                    reference_credentials=(
                        credentials["reference"]
                        if role is Role.ADMINISTRATOR
                        else theirs.credentials_for(role)
                    ),
                )
                for role in roles
            ]
            report = run(
                atrium,
                reference,
                endpoints,
                cases,
                entries,
                named,
                seats,
                inputs,
                provenance,
                fixture_root=Path(args.fixture_root) if args.fixture_root else None,
            )
            if salvage is not None:
                salvage.append((report, destination))
    except (SeatError, WireError) as failure:
        # A teardown that could not finish is an incident and not the end of the report. It stays
        # loud - it is printed, it is in the report, and `is_clean()` is false for it - because
        # the seats it names are still on the server and the next run's pre-flight will refuse.
        if report is None:
            # Nothing was measured, so there is nothing to salvage: a run that could not seat its
            # identities is the "could not start" this program has always exited 2 for.
            raise
        print(f"differential.py: {failure}", file=sys.stderr)
        report = replace(
            report, incidents=(*report.incidents, f"the teardown did not finish: {failure}")
        )

    if salvage is not None:
        if salvage:
            salvage[-1] = (report, destination)
        else:
            salvage.append((report, destination))
    return report, destination


if __name__ == "__main__":
    raise SystemExit(main())
