# SPDX-License-Identifier: GPL-3.0-or-later
"""Argon2id, and the dummy record that makes a failure cost what a success costs.

This is the only module that imports argon2. Everything else asks this one, which is what keeps
ADR-0006's "parameters can be raised later" a change to one file.

**A stored record is self-describing**, algorithm first:

    $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>

so raising the parameters later is a parse rather than a guess, and a record made with the old ones
still verifies. The rewrite happens on the next successful login, which is the one moment the
plaintext exists - `needs_rehash` is how a caller knows to do it.

**The dummy record is not an optimisation and not a placeholder.** Argon2id takes tens of
milliseconds; skipping it when the username does not exist makes that response measurably faster
and turns the login endpoint into an oracle for which accounts are real. So every failure path
verifies *something*, and for an unknown user that something is this record - built at startup from
`secrets`, never from anybody's password, and carrying **the same parameters as a real one** so it
costs the same to check.

Nothing here logs. A password reaches this module and goes no further, which is half of why
tests/security asserts it never appears in a log record (plan section 8.2).

See specs/002-authentication-users-and-sessions/plan.md section 6.2 and ADR-0006.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import ARGON2_VERSION, Type

from atrium.config.settings import PasswordSettings

#: What `$argon2id$` says. Kept as a constant because `needs_rehash` compares against it, and a
#: record naming any other algorithm is one this build cannot verify and must replace.
ALGORITHM = "argon2id"

#: The library's enum member names are `ID`, `I` and `D` - not what the record says it is. Reading
#: `type.name.lower()` and comparing it to `argon2id` gives `id`, which is never equal, so every
#: record including a freshly written one reports that it needs rehashing. That is a rewrite on
#: every single login: the KDF twice per authentication, forever, and no test of the round trip
#: would notice because verifying still works.
WIRE_NAMES = {Type.ID: "argon2id", Type.I: "argon2i", Type.D: "argon2d"}


class PasswordRecordError(RuntimeError):
    """The stored record cannot be checked at all - malformed, or an algorithm we do not have.

    Distinct from "the password was wrong" on purpose. The caller answers `401` either way, and it
    logs this one naming the account, because it means somebody has to reset a password rather than
    remember one (plan section 7).
    """


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    """The cost this build writes new records at."""

    memory_cost: int
    time_cost: int
    parallelism: int

    @classmethod
    def from_settings(cls, settings: PasswordSettings) -> PasswordPolicy:
        return cls(
            memory_cost=settings.memory_cost,
            time_cost=settings.time_cost,
            parallelism=settings.parallelism,
        )


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """What a stored string says about itself, without verifying anything against it."""

    algorithm: str
    version: int
    memory_cost: int
    time_cost: int
    parallelism: int


def describe(stored: str) -> StoredRecord:
    """Parse a record back into its algorithm and parameters.

    A record that cannot be parsed is not a wrong password, and reporting it as one would send an
    operator looking for a user who forgot theirs.
    """
    try:
        parameters = extract_parameters(stored)
    except InvalidHashError as exc:
        raise PasswordRecordError(f"not a password record this build can read: {exc}") from exc
    return StoredRecord(
        algorithm=WIRE_NAMES.get(parameters.type, parameters.type.name.lower()),
        version=parameters.version,
        memory_cost=parameters.memory_cost,
        time_cost=parameters.time_cost,
        parallelism=parameters.parallelism,
    )


class Passwords:
    """Hash, verify, and say when a record is out of date.

    One per instance rather than a module-level singleton: the parameters come from that instance's
    configuration, and two servers in one process - which the suite builds constantly - must not
    share a hasher or a dummy record.
    """

    def __init__(self, policy: PasswordPolicy) -> None:
        self.policy = policy
        self._hasher = PasswordHasher(
            memory_cost=policy.memory_cost,
            time_cost=policy.time_cost,
            parallelism=policy.parallelism,
        )
        # 32 bytes from the system CSPRNG, hashed once and then unreachable - the plaintext is not
        # kept, so there is nothing here that verifying against it could disclose.
        self._dummy = self._hasher.hash(secrets.token_urlsafe(32))

    @property
    def dummy_record(self) -> str:
        """A real record for a password nobody has. See this module's docstring."""
        return self._dummy

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, stored: str, password: str) -> bool:
        """True when the password matches. False when it does not. Raises when it cannot tell."""
        try:
            return self._hasher.verify(stored, password)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError) as exc:
            raise PasswordRecordError(f"cannot verify against this record: {exc}") from exc

    def verify_dummy(self, password: str) -> bool:
        """Spend a verify to learn nothing, so that failing costs what succeeding costs.

        Always False, and the return value exists so a caller cannot accidentally write code whose
        two branches take different amounts of time.
        """
        return self.verify(self._dummy, password)

    def needs_rehash(self, stored: str) -> bool:
        """Whether this record is **below** what this build writes now.

        Below, not different - and argon2-cffi's own `check_needs_rehash` means different. It
        reports True for a record made with *stronger* parameters than the current policy, which
        would rewrite it weaker at the one moment the plaintext exists. An operator who lowers
        these settings after moving to a smaller machine would silently downgrade every account's
        record on its owner's next login, and nothing would say so. ADR-0006 says "below" and this
        is what "below" has to mean.

        **Parallelism is not part of the comparison.** It divides the same work across lanes rather
        than adding any: RFC 9106 sets it from the cores available, and the cost is carried by
        memory and time. Rewriting a record because `p` moved would spend the plaintext moment on a
        change with no security in it.

        A record naming another algorithm needs one too - this build has exactly one, so anything
        else predates the decision or came from somewhere else.
        """
        record = describe(stored)
        if record.algorithm != ALGORITHM:
            return True
        if record.version < ARGON2_VERSION:
            return True
        return (
            record.memory_cost < self.policy.memory_cost or record.time_cost < self.policy.time_cost
        )


def build(settings: PasswordSettings) -> Passwords:
    """What the factory calls, so the startup path names configuration rather than argon2."""
    return Passwords(PasswordPolicy.from_settings(settings))


__all__ = [
    "ALGORITHM",
    "WIRE_NAMES",
    "PasswordPolicy",
    "PasswordRecordError",
    "Passwords",
    "StoredRecord",
    "build",
    "describe",
]
