# SPDX-License-Identifier: GPL-3.0-or-later
"""Argon2id: the round trip, the rehash rule, and the dummy record.

Every test here runs at parameters far below the shipped ones - `memory_cost = 8` KiB rather than
64 MiB - because verifying dozens of passwords at the real cost takes minutes and a slow suite gets
run less often (plan section 8.4). One test ties the *shipped* defaults to RFC 9106's profile, so
lowering them here cannot quietly become lowering them everywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argon2 import profiles

from atrium.config.paths import DataPaths
from atrium.config.settings import PasswordSettings
from atrium.config.settings import load as load_settings
from atrium.users.passwords import (
    ALGORITHM,
    PasswordPolicy,
    PasswordRecordError,
    Passwords,
    build,
    describe,
)

CHEAP = PasswordPolicy(memory_cost=8, time_cost=1, parallelism=1)
COSTLIER = PasswordPolicy(memory_cost=16, time_cost=2, parallelism=1)

#: Not a credential. It is the string these tests hash, and tests/security asserts that a string
#: like it never reaches a log record.
PASSWORD = "correct horse battery staple"


@pytest.fixture
def passwords() -> Passwords:
    return Passwords(CHEAP)


# --------------------------------------------------------------------------------------------
# The round trip
# --------------------------------------------------------------------------------------------


def test_a_hash_round_trips(passwords: Passwords) -> None:
    assert passwords.verify(passwords.hash(PASSWORD), PASSWORD) is True


def test_a_wrong_password_fails(passwords: Passwords) -> None:
    stored = passwords.hash(PASSWORD)
    assert passwords.verify(stored, "correct horse battery stapl") is False
    assert passwords.verify(stored, "") is False
    assert passwords.verify(stored, PASSWORD.upper()) is False


def test_an_empty_password_is_a_password(passwords: Passwords) -> None:
    """An account with no password is a different thing, and it is not this. Spec section 3.3."""
    stored = passwords.hash("")
    assert passwords.verify(stored, "") is True
    assert passwords.verify(stored, PASSWORD) is False


def test_the_same_password_twice_gives_two_records(passwords: Passwords) -> None:
    """The salt does its job. Two equal records would say which users share a password."""
    assert passwords.hash(PASSWORD) != passwords.hash(PASSWORD)


# --------------------------------------------------------------------------------------------
# The record describes itself
# --------------------------------------------------------------------------------------------


def test_the_record_has_the_shape_the_decision_documents(passwords: Passwords) -> None:
    """ADR-0006 writes the format out. This asserts the library agrees with the document."""
    stored = passwords.hash(PASSWORD)
    assert stored.startswith(f"${ALGORITHM}$v=19$m=8,t=1,p=1$")


def test_a_record_parses_back_to_its_algorithm_and_parameters(passwords: Passwords) -> None:
    record = describe(passwords.hash(PASSWORD))
    assert record.algorithm == ALGORITHM
    assert (record.memory_cost, record.time_cost, record.parallelism) == (8, 1, 1)
    assert record.version == 19


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "not a record at all",
        "$argon2id$",
        "$pbkdf2-sha512$iterations=210000$0011$aabb",
        "$2b$12$KIXQJp1s0Zx7YfQb0mZ8ue",
    ],
)
def test_an_unreadable_record_is_not_a_wrong_password(passwords: Passwords, stored: str) -> None:
    """Reporting it as one sends an operator looking for a user who forgot theirs.

    The PBKDF2 line is the reference's own format: ADR-0006 closed the door on importing a Jellyfin
    user database, and this is what walking into that door looks like.
    """
    with pytest.raises(PasswordRecordError):
        passwords.verify(stored, PASSWORD)
    with pytest.raises(PasswordRecordError):
        describe(stored)


# --------------------------------------------------------------------------------------------
# Raising the parameters later
# --------------------------------------------------------------------------------------------


def test_a_record_below_the_policy_still_verifies_and_asks_to_be_rewritten() -> None:
    """The whole of ADR-0006's "parameters can be raised without a mass reset", in one test."""
    old = Passwords(CHEAP)
    stored = old.hash(PASSWORD)

    raised = Passwords(COSTLIER)
    assert raised.verify(stored, PASSWORD) is True
    assert raised.needs_rehash(stored) is True

    rewritten = raised.hash(PASSWORD)
    assert raised.needs_rehash(rewritten) is False
    assert describe(rewritten).memory_cost == COSTLIER.memory_cost


def test_a_record_at_the_policy_is_left_alone(passwords: Passwords) -> None:
    assert passwords.needs_rehash(passwords.hash(PASSWORD)) is False


def test_a_record_from_another_algorithm_needs_rehashing(passwords: Passwords) -> None:
    """There is one algorithm here, so anything else is older than this decision or foreign."""
    with pytest.raises(PasswordRecordError):
        passwords.needs_rehash("$pbkdf2-sha512$iterations=210000$0011$aabb")


def test_lowering_the_policy_does_not_ask_for_a_rewrite() -> None:
    """Below the policy, not different from it - and argon2-cffi means different.

    Its `check_needs_rehash` reports True for a *stronger* record. Taking that meaning would
    rewrite a strong record weaker at the one moment the plaintext exists, so an operator who
    lowered these settings after moving to a smaller machine would silently downgrade every
    account on its owner's next login, with nothing to say so.
    """
    strong = Passwords(COSTLIER)
    stored = strong.hash(PASSWORD)
    assert Passwords(CHEAP).needs_rehash(stored) is False


def test_a_record_short_on_either_cost_is_rewritten() -> None:
    """Each on its own, because a policy can be raised in one of them and not the other."""
    policy = PasswordPolicy(memory_cost=16, time_cost=2, parallelism=1)
    current = Passwords(policy)
    thin_memory = Passwords(PasswordPolicy(memory_cost=8, time_cost=2, parallelism=1))
    quick = Passwords(PasswordPolicy(memory_cost=16, time_cost=1, parallelism=1))
    assert current.needs_rehash(thin_memory.hash(PASSWORD)) is True
    assert current.needs_rehash(quick.hash(PASSWORD)) is True


def test_parallelism_alone_does_not_trigger_a_rewrite() -> None:
    """It distributes the same work rather than adding any, so moving it is not a downgrade."""
    two_lanes = Passwords(PasswordPolicy(memory_cost=16, time_cost=1, parallelism=2))
    one_lane = Passwords(PasswordPolicy(memory_cost=16, time_cost=1, parallelism=1))
    assert one_lane.needs_rehash(two_lanes.hash(PASSWORD)) is False
    assert two_lanes.needs_rehash(one_lane.hash(PASSWORD)) is False


# --------------------------------------------------------------------------------------------
# The dummy record
# --------------------------------------------------------------------------------------------


def test_the_dummy_record_is_a_password_nobody_has(passwords: Passwords) -> None:
    """Built from `secrets`, and the plaintext is not kept - so there is nothing to disclose."""
    assert passwords.verify_dummy(PASSWORD) is False
    assert passwords.verify_dummy("") is False
    assert passwords.verify_dummy(passwords.dummy_record) is False


def test_two_instances_do_not_share_a_dummy_record() -> None:
    """A constant would be one value an attacker could precompute against, forever, everywhere."""
    assert Passwords(CHEAP).dummy_record != Passwords(CHEAP).dummy_record


def test_the_dummy_record_costs_what_a_real_one_costs(passwords: Passwords) -> None:
    """This is the whole point of it, and it is the part a refactor would quietly break.

    A dummy carrying different parameters is verified in a different amount of time, which puts
    back exactly the signal it was built to remove: how long the answer took would say whether the
    username exists.
    """
    dummy = describe(passwords.dummy_record)
    real = describe(passwords.hash(PASSWORD))
    assert (dummy.algorithm, dummy.memory_cost, dummy.time_cost, dummy.parallelism) == (
        real.algorithm,
        real.memory_cost,
        real.time_cost,
        real.parallelism,
    )


# --------------------------------------------------------------------------------------------
# Where the parameters come from
# --------------------------------------------------------------------------------------------


def test_the_shipped_defaults_are_rfc_9106s_low_memory_profile() -> None:
    """Written out in `settings.py` rather than inherited, so this ties the two together.

    A library default can move under a project without anybody deciding it should, and these are a
    security parameter. If argon2-cffi's profile changes, this fails and somebody chooses.
    """
    shipped = PasswordSettings()
    profile = profiles.RFC_9106_LOW_MEMORY
    assert shipped.memory_cost == profile.memory_cost
    assert shipped.time_cost == profile.time_cost
    assert shipped.parallelism == profile.parallelism


def test_the_parameters_are_read_from_the_operators_file(tmp_path: Path) -> None:
    """The mechanism this suite itself uses to stay fast, asserted rather than assumed."""
    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.config_file.write_text(
        "[passwords]\nmemory_cost = 16\ntime_cost = 2\nparallelism = 1\n", encoding="utf-8"
    )
    built = build(load_settings(paths).passwords)
    assert built.policy == PasswordPolicy(memory_cost=16, time_cost=2, parallelism=1)
    assert describe(built.hash(PASSWORD)).memory_cost == 16


def test_a_nonsense_parameter_refuses_to_start(tmp_path: Path) -> None:
    """Same policy as every other malformed setting: refuse, do not silently use a default."""
    from atrium.config.paths import ConfigurationError

    paths = DataPaths(tmp_path / "atrium")
    paths.prepare()
    paths.config_file.write_text("[passwords]\ntime_cost = 0\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_settings(paths)
