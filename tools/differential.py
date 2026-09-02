#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The identities a differential run authenticates as, created and destroyed by the run.

**A run that authenticates once measures one row of a two-row table, and its report says nothing
about the other.** Twelve of the twenty-three reads of the surface answer differently to a
restricted non-administrator, and two of them differ as *shorter lists* rather than as refusals -
a `200` that differs only in how many rows it holds
`[probe: tools/probe_restricted_surface.py, Jellyfin 10.11.11, 2026-09-01]`. Every probe written
before 2026-09-01 authenticated as an administrator, and an administrator lacks no permission, so
no measurement in this repository had ever been taken from a seat that could be refused anything
([010 spec section 3.9](../specs/010-conformance-harness/spec.md)).

So the seats come **before** the loop that consumes them. This module is the file
[conformance.md](../docs/compatibility/conformance.md) publishes as the harness command line, and
T7 lands the part of it that has to exist first: `Role`, `Identity`, and the lifecycle that
creates the seats, refuses to start when one is already there, and destroys what it made. The run
loop, the report and the two-server guard are T8's, and until they land this file has a `--help`
and no sweep.

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

Usage:
    python3 tools/differential.py --help
"""

from __future__ import annotations

import argparse
import secrets
import sys
from dataclasses import dataclass
from enum import Enum
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
# The command line, which is T8's
# --------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        prog="differential.py",
        description=(
            "The L3 differential harness. T7 has landed the identities a run authenticates as - "
            "the administrator, a restricted non-administrator and a seat with the three "
            "playback-processing permissions denied - together with the pre-flight that refuses "
            "a run whose seats are already on the server and the teardown that destroys what the "
            "run made. The run loop, the report and the two-server guard are T8's, so there is "
            "no sweep to ask for yet."
        ),
        epilog=(
            "See docs/compatibility/conformance.md for the invocation this file will adopt, and "
            "specs/010-conformance-harness/tasks.md for what has landed."
        ),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    build_parser().parse_args(argv)
    print(
        "differential.py: the identities are in place and the run loop is not (010 T8). "
        "Nothing was contacted.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
