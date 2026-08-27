# SPDX-License-Identifier: GPL-3.0-or-later
"""How long a refusal takes must not say whether the username was real.

**A ratio, never a number of milliseconds.** A timing test that asserts absolute time fails on a
loaded runner and teaches everyone to ignore it, which is worse than not having it (plan section
8.1). A ratio is scale-invariant: a runner three times slower moves both branches together and the
assertion does not notice.

## This is the backstop, not the guarantee

The guarantee is counted, in tests/unit/test_authenticate.py: every failure path runs the KDF
**exactly once**, asserted by counting invocations. That test fails for a precise reason and never
flakes. This one is the empirical check that the counting test is measuring the thing that matters
- and the last test in this file proves it can fail, by removing the dummy verify and watching the
ratio blow out.

## The KDF has to dominate, or this measures the wrong thing

Measured on the machine this was written on, comparing an unknown username against a known one with
a wrong password:

| Argon2 memory | unknown | wrong password | ratio |
|---|---|---|---|
| 8 KiB - the suite's own setting | 0.139 ms | 0.493 ms | **3.55** |
| 1 MiB | 0.627 ms | 0.997 ms | 1.59 |
| 4 MiB | 2.132 ms | 2.510 ms | 1.18 |

The gap that does not close is **not** the KDF: it is the failed-attempt counter, which the
known-username path writes and the unknown path does not. It is a second channel, it is real, and
it shrinks against the KDF as the parameters rise - at the shipped 64 MiB it is under one percent
of a 41 ms verify. Recorded in plan section 9 rather than left to be rediscovered.

So this file runs at parameters where the KDF dominates, as it does in production. Running it at
the suite's own cheap settings would measure SQLite's commit and call it a timing leak.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from atrium.compat.auth import ClientInfo
from atrium.compat.errors import InvalidCredentialsError
from atrium.compat.guids import new_id
from atrium.config.paths import DataPaths
from atrium.db import schema
from atrium.db.engine import create_database_engine, session_factory
from atrium.db.repositories import UserRepository
from atrium.domain.user import User
from atrium.users.passwords import PasswordPolicy, Passwords
from atrium.users.service import Authenticator
from atrium.users.sessions import SessionRegistry
from tests.conftest import data_dir

PASSWORD = "correct horse battery staple"

#: Enough that the KDF dominates the way it does in production - roughly 4 ms a verify here, next
#: to a counter write of a fraction of a millisecond. Not the shipped 64 MiB, which would make this
#: file take half a minute for no extra confidence.
TIMING_POLICY = PasswordPolicy(memory_cost=8192, time_cost=1, parallelism=1)

#: Odd, so the median is a sample rather than an average of two.
SAMPLES = 21

#: Generous on purpose. The structural failure this exists to catch - a branch that skips the KDF -
#: measured **19x** on the machine this was written on, so three is a wide margin either side of
#: the 1.1 that a correct implementation produces, and wide enough for a runner whose disk makes
#: the counter write expensive.
BOUND = 3.0


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    paths: DataPaths = data_dir(tmp_path / "atrium")
    built = create_database_engine(paths)
    schema.ensure_current(built, paths)
    yield built
    built.dispose()


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[OrmSession]:
    return session_factory(engine)


def build(factory: sessionmaker[OrmSession], passwords: Passwords) -> Authenticator:
    with factory.begin() as opened:
        UserRepository(opened).add(
            User(id=new_id(), name="Joan", password_hash=passwords.hash(PASSWORD))
        )
    return Authenticator(factory, passwords, SessionRegistry(factory))


def milliseconds(call: Callable[[], None]) -> float:
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1000


def refusals(authenticator: Authenticator, username: str, samples: int = SAMPLES) -> list[float]:
    """How long `samples` refusals took, in milliseconds, warmed up first."""
    info = ClientInfo(client="Atrium Test", device="Bench", device_id="bench-1", version="1")

    def once() -> None:
        with pytest.raises(InvalidCredentialsError):
            authenticator.authenticate(username, "the-wrong-password", info)

    for _ in range(3):  # the first calls pay for imports, page faults and a cold pool
        once()
    return sorted(milliseconds(once) for _ in range(samples))


def ratio(unknown: list[float], wrong: list[float]) -> float:
    return statistics.median(wrong) / statistics.median(unknown)


# --------------------------------------------------------------------------------------------
# The distributions overlap
# --------------------------------------------------------------------------------------------


def test_an_unknown_username_costs_what_a_wrong_password_costs(
    factory: sessionmaker[OrmSession],
) -> None:
    """The oracle this prevents: `nobody` returning in microseconds while `Joan` takes tens of
    milliseconds tells an attacker which usernames are real, one request at a time."""
    authenticator = build(factory, Passwords(TIMING_POLICY))

    unknown = refusals(authenticator, "nobody-at-all")
    wrong = refusals(authenticator, "Joan")

    observed = ratio(unknown, wrong)
    assert 1 / BOUND <= observed <= BOUND, (
        f"the two refusals took different amounts of time: unknown median "
        f"{statistics.median(unknown):.3f} ms, wrong password {statistics.median(wrong):.3f} ms, "
        f"ratio {observed:.2f}. Minima {min(unknown):.3f} / {min(wrong):.3f}."
    )


def test_a_disabled_account_costs_the_same_as_an_unknown_one(
    factory: sessionmaker[OrmSession],
) -> None:
    """The other branch that could have skipped the KDF, and the one whose status already
    discloses the account's state - so the timing must not disclose it a second time."""
    from atrium.compat.errors import AccountUnavailableError

    passwords = Passwords(TIMING_POLICY)
    authenticator = build(factory, passwords)
    with factory.begin() as opened:
        UserRepository(opened).add(
            User(
                id=new_id(),
                name="Gone",
                password_hash=passwords.hash(PASSWORD),
                is_disabled=True,
            )
        )

    info = ClientInfo(client="Atrium Test", device="Bench", device_id="bench-1", version="1")

    def disabled() -> None:
        with pytest.raises(AccountUnavailableError):
            authenticator.authenticate("Gone", "the-wrong-password", info)

    for _ in range(3):
        disabled()
    refused = sorted(milliseconds(disabled) for _ in range(SAMPLES))
    unknown = refusals(authenticator, "nobody-at-all")

    observed = statistics.median(refused) / statistics.median(unknown)
    assert 1 / BOUND <= observed <= BOUND, (
        f"a disabled account is refused in a different amount of time: "
        f"{statistics.median(refused):.3f} ms against {statistics.median(unknown):.3f} ms"
    )


# --------------------------------------------------------------------------------------------
# The test can fail
# --------------------------------------------------------------------------------------------


class OracleByOmission(Passwords):
    """What a reasonable person writes when they are optimising the unknown-username branch.

    It looks like a saving: there is no password to check, so why spend forty milliseconds
    checking one? Because the forty milliseconds *are* the answer.
    """

    def verify_dummy(self, password: str) -> bool:
        return False


def test_removing_the_dummy_verify_is_caught(factory: sessionmaker[OrmSession]) -> None:
    """A guard that cannot fail is decoration. This is the failure it exists for.

    Measured at roughly **19x** when it was written: the unknown branch returns in the time of one
    indexed lookup, and every other branch pays for the KDF.
    """
    authenticator = build(factory, OracleByOmission(TIMING_POLICY))

    unknown = refusals(authenticator, "nobody-at-all")
    wrong = refusals(authenticator, "Joan")

    observed = ratio(unknown, wrong)
    assert observed > BOUND, (
        f"the oracle was not detected: ratio {observed:.2f} is inside the bound of {BOUND}. "
        f"Either the KDF no longer dominates at these parameters, or the bound is too wide."
    )


def test_the_assertion_is_scale_invariant() -> None:
    """The property that keeps this test from being deleted after its third false failure.

    A runner three times slower moves both branches together, and a ratio does not notice. This
    asserts that directly rather than by inspecting the source for absolute numbers: the same
    measurements, all multiplied by any constant, give the same verdict.
    """
    unknown = [2.0, 2.1, 2.2, 2.3, 2.4]
    wrong = [2.3, 2.4, 2.5, 2.6, 2.7]
    baseline = ratio(unknown, wrong)

    for slowdown in (0.5, 3.0, 40.0):
        slower = ratio([one * slowdown for one in unknown], [one * slowdown for one in wrong])
        assert slower == pytest.approx(baseline), f"a {slowdown}x slower runner changed the verdict"

    assert 1 / BOUND <= baseline <= BOUND
    assert ratio(unknown, [one * 19 for one in wrong]) > BOUND, "the bound catches nothing"
