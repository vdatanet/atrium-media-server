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
import http.client
import importlib
import json
import os
import re
import secrets
import sys
import urllib.parse
from dataclasses import dataclass
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


def sign_in_against(base_url: str, timeout: int = 30) -> SignIn:
    """The real `SignIn`, authenticating a created seat against the server that holds it.

    `_probe` is imported inside the call and not at module scope: this module is loaded by path
    from the suite, where `tools/` is not on the import path and where opening a socket fails the
    no-network guard by design. Nothing in the seat lifecycle calls this unless a run is real.
    """

    def sign_in(username: str, password: str) -> Tuple[str, str]:
        from _probe import Server  # deliberately here and not at module scope

        seat = Server(base_url, timeout=timeout)
        seat.connect(username, password, None)
        return str(seat.token), str(seat.user_id)

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


def preflight(directory: Directory, roles: Sequence[Role]) -> None:
    """Refuse the run if a seat it would create is already there (AC-15).

    A precondition and not a cleanup: this runs before anything is created, and it names what it
    found, because the operator's next action is to look at that account and decide whether a run
    is in flight or a killed one left it.
    """
    clashes = existing_seats(directory, roles)
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
        return (seat_name(role), self._passwords[role])

    def __iter__(self) -> Iterator[Identity]:
        return iter(self._identities[role] for role in self.roles)

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
        preflight(self._directory, self.roles)
        self._identities[Role.ADMINISTRATOR] = self._administrator
        self._entered = True
        try:
            for role in self.roles:
                if role in CREATED_ROLES:
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
        if Role.RESTRICTED in self.roles and not self._library_id:
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

    def _create(self, role: Role) -> Identity:
        name = seat_name(role)
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
CLIENT = "atrium-differential"
DEVICE_ID = "atrium-differential-0000"
CLIENT_VERSION = "0.1"


class WireError(RuntimeError):
    """A request could not be made at all. An inability to look, never a finding."""


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

    def __init__(self, base_url: str, token: str = "", timeout: int = 30) -> None:
        parsed = urllib.parse.urlsplit(base_url if "://" in base_url else "http://" + base_url)
        self.base_url = base_url.rstrip("/")
        self.scheme = parsed.scheme or "http"
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port
        self.prefix = parsed.path.rstrip("/")
        self.token = token
        self.timeout = timeout

    def as_seat(self, token: str) -> Wire:
        """The same server, held by another seat. One `Wire` per identity per side."""
        return Wire(self.base_url, token=token, timeout=self.timeout)

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
        target = self.prefix + path + (("?" + query) if query else "")
        headers = {
            "Accept": "application/json",
            "X-Emby-Authorization": (
                f'MediaBrowser Client="{CLIENT}", Device="{CLIENT}", '
                f'DeviceId="{DEVICE_ID}", Version="{CLIENT_VERSION}"'
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
    for view in views.get("Items", []):
        if view.get("CollectionType") == "movies":
            return str(view["Id"])
    raise SeatError(
        "no movies library on this server to restrict the created seat to, and a seat narrowed "
        "to nothing is not a narrower reader - it is an account that can open nothing, which "
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
    named_run: Tuple[str, ...] = ()
    named_outstanding: Tuple[Tuple[str, str], ...] = ()
    endpoints: Tuple[Endpoint, ...] = ()
    provenance: Tuple[Tuple[str, str], ...] = ()
    unused_entries: Tuple[Tuple[str, str, str], ...] = ()

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

    def is_clean(self) -> bool:
        """False while this run has an unanswered question of any kind.

        Three conditions, where spec section 3.4 states two. *An untriaged difference blocks the
        run from being called clean. So does an unrun named comparison* - and so does **a declared
        case this run could not issue**, which is the same fact wearing the sweep's clothes: a
        comparison that did not happen is not a comparison that agreed. A run that reported clean
        having quietly dropped nine cases is one directory away from the CI job that reported
        green because it ran nothing (008 T18).
        """
        return not self.differences and not self.named_outstanding and not self.unasked


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


def named_outcomes(
    register: Sequence[Any], inputs: Inputs
) -> Tuple[Tuple[str, ...], Tuple[Tuple[str, str], ...]]:
    """Every row of the register, run or **outstanding by name with its reason** (AC-16).

    No row runs yet: the runners are 010 T12, and a row whose `runner` is `none` is outstanding
    for that reason. The needs are still resolved first, because *"four outstanding, and three of
    them because no fixture instance was available"* is a different sentence from *"four
    outstanding"* - and it is the sentence plan section 4.2 says `needs` earns the file for.
    """
    run: List[str] = []
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
            outstanding.append(
                (row.id, "no runner is written for it yet: the twenty runners are 010 T12")
            )
            continue
        run.append(row.id)
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


def render(report: RunReport) -> str:
    """Spec section 3.4's report, and the sections that keep it from reading like a clean one."""
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
    lines.append("")
    lines.append("  " + ("THIS RUN IS CLEAN." if report.is_clean() else "THIS RUN IS NOT CLEAN."))
    lines.append("```")
    lines.append("")

    lines.extend(_conclusions(report))
    lines.extend(_coverage_section(report))
    lines.extend(_unasked_section(report))
    lines.extend(_named_section(report))
    lines.extend(_differences_section(report))
    lines.extend(_known_section(report))
    lines.extend(_entries_section(report))
    return "\n".join(lines) + "\n"


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
    compared = set(report.endpoints_compared)
    lines.append("| Endpoint | Declared level | Compared |")
    lines.append("|---|---|---|")
    for endpoint in report.endpoints:
        reached = "yes" if endpoint.key in compared else "**no**"
        lines.append(f"| `{endpoint.key}` | {endpoint.level} | {reached} |")
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
        lines.append("| Ran |")
        lines.append("|---|")
        for row in report.named_run:
            lines.append(f"| {row} |")
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
        "--reference-url",
        default="",
        help="A reference instance somebody else stood up, for the --fixture half. Given one, "
        "this run does not stand up its own",
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        default=None,
        help="The fixture tree the single-use reference instance is given as its only library, "
        "mounted read-only. Which world that is, and in how many libraries, is D-4 - measured by "
        "tools/probe_reference_scan.py and built by 010 T11",
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
        self._instance: Any = None

    def __enter__(self) -> FixtureInstance:
        if self.url or not self.args.fixture:
            return self
        if self.args.fixture_root is None:
            self.reason = (
                "--fixture-root named no tree to mount, and an instance with nothing mounted "
                "would scan an empty library and compare two of them"
            )
            return self
        module = _sibling("_reference")
        spec = module.InstanceSpec(fixture_root=Path(self.args.fixture_root))
        instance = module.ReferenceInstance(spec)
        try:
            instance.__enter__()
        except module.InstanceError as failure:
            self.reason = str(failure)
            return self
        self._instance = instance
        self.url = instance.url
        self.digest = instance.digest
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
) -> RunReport:
    """The sweep, the named comparisons and the report, over servers that are already seated."""
    issuers = {
        "atrium": Issuer(
            "atrium", {seat.role: atrium.as_seat(seat.atrium.token) for seat in seats}, cases
        ),
        "reference": Issuer(
            "reference",
            {seat.role: reference.as_seat(seat.reference.token) for seat in seats},
            cases,
        ),
    }
    # Filled by the sweep as it goes: an entry that suppressed a finding on any comparison is one
    # this run can say excused something, and the rest are reported (plan section 7).
    used: set = set()
    comparisons = sweep(endpoints, cases, entries, seats, issuers, inputs, used)
    ran, outstanding = named_outcomes(named, inputs)
    return RunReport(
        identities=tuple(seat.role for seat in seats),
        cases=len(cases),
        comparisons=comparisons,
        named_run=ran,
        named_outstanding=outstanding,
        endpoints=tuple(endpoints),
        provenance=tuple(provenance),
        unused_entries=unused_entries(entries, used),
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
    try:
        report, destination = _execute(args)
    except (GuardError, SeatError, WireError, UnreachableError) as failure:
        print(f"differential.py: {failure}", file=sys.stderr)
        return 2
    except Exception as failure:  # a harness that dies silently is worse than one that says so
        print(f"differential.py: the run could not start: {failure}", file=sys.stderr)
        return 2
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render(report), encoding="utf-8")
    print(f"differential.py: report written to {destination}")
    print(
        f"differential.py: {len(report.differences)} differences, {len(report.unasked)} cases not "
        f"asked, {len(report.named_outstanding)} named comparisons outstanding."
    )
    return 0 if report.is_clean() else 1


def _execute(args: argparse.Namespace) -> Tuple[RunReport, Path]:
    """Everything a real run does, from the environment to the seated servers."""
    probe = _sibling("_probe")
    probe.load_env_file()
    atrium_url = args.atrium or ""
    reference_url = args.jellyfin or os.environ.get(ENV_REFERENCE_URL, "")
    if not atrium_url or not reference_url:
        raise GuardError(
            "a differential needs both servers: pass --atrium and --jellyfin (or set "
            f"{ENV_REFERENCE_URL} in .env). One server is not a differential"
        )

    atrium = Wire(atrium_url, timeout=args.timeout)
    reference = Wire(reference_url, timeout=args.timeout)
    check_two_servers(
        atrium.request("GET", "/System/Info/Public").headers,
        reference.request("GET", "/System/Info/Public").headers,
    )

    administrators = {
        "atrium": authenticate(
            atrium,
            os.environ.get(ENV_ATRIUM_USERNAME, ""),
            os.environ.get(ENV_ATRIUM_PASSWORD, ""),
            os.environ.get(ENV_ATRIUM_TOKEN, ""),
        ),
        "reference": authenticate(
            reference,
            os.environ.get(ENV_REFERENCE_USERNAME, ""),
            os.environ.get(ENV_REFERENCE_PASSWORD, ""),
            os.environ.get(ENV_REFERENCE_TOKEN, ""),
        ),
    }
    credentials = {
        "atrium": (
            os.environ.get(ENV_ATRIUM_USERNAME, ""),
            os.environ.get(ENV_ATRIUM_PASSWORD, ""),
        ),
        "reference": (
            os.environ.get(ENV_REFERENCE_USERNAME, ""),
            os.environ.get(ENV_REFERENCE_PASSWORD, ""),
        ),
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
    rosters = {
        side: Roster(
            directories[side],
            administrators[side],
            roles,
            library_id=(
                movies_library_id(directories[side], administrators[side].user_id)
                if Role.RESTRICTED in roles
                else None
            ),
            sign_in=sign_in_against(url, timeout=args.timeout),
        )
        for side, url in (("atrium", atrium_url), ("reference", reference_url))
    }

    public = reference.request("GET", "/System/Info/Public")
    version = public.body.get("Version", "unknown") if isinstance(public.body, dict) else "unknown"
    ours_says = header_value(atrium.request("GET", "/System/Ping").headers, SERVER_HEADER)
    theirs_says = header_value(public.headers, SERVER_HEADER)

    # **The instance wraps the sweep and nothing else** (010 T8's note, plan section 6.5): the two
    # rosters are entered inside it, so the seats die before the server that holds them, and the
    # instance dies after them on both paths. An instance that could not be stood up is not a
    # failure here - `FixtureInstance` carries the reason, and every row that needed one says it.
    with FixtureInstance(args) as instance:
        inputs = Inputs(
            roles=tuple(role.value for role in roles),
            instance_url=instance.url,
            fixture_asked=bool(args.fixture),
            named_selected=tuple(args.named) if args.named else None,
            instance_reason=instance.reason,
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
                atrium, reference, endpoints, cases, entries, named, seats, inputs, provenance
            )

    today = datetime.now(timezone.utc).date().isoformat()
    default = (
        DEFAULT_REPORT_DIRECTORY / f"differential-{today}-{repository_sha(REPOSITORY_ROOT)}.md"
    )
    destination = args.report or default
    return report, Path(destination)


if __name__ == "__main__":
    raise SystemExit(main())
