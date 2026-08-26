# SPDX-License-Identifier: GPL-3.0-or-later
"""Ticks: 100-nanosecond integers, converted exactly and rounded predictably."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from atrium.compat.model import AtriumModel
from atrium.compat.ticks import (
    TICKS_PER_SECOND,
    WireTicks,
    from_milliseconds,
    from_seconds,
    from_timedelta,
    to_seconds,
    to_timedelta,
)


class Sample(AtriumModel):
    run_time_ticks: WireTicks


def test_the_unit_is_a_hundred_nanoseconds() -> None:
    assert TICKS_PER_SECOND == 10_000_000


# --------------------------------------------------------------------------------------------
# Exactness
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "ticks"),
    [
        (1, 10_000_000),
        (0, 0),
        ("5763.999", 57_639_990_000),  # the string form ffprobe reports
        (Decimal("8.7"), 87_000_000),
        (timedelta(hours=2).total_seconds(), 72_000_000_000),
    ],
)
def test_from_seconds(seconds: object, ticks: int) -> None:
    assert from_seconds(seconds) == ticks  # type: ignore[arg-type]


def test_decimal_conversion_beats_the_obvious_float_version() -> None:
    """The reason this module does not just multiply by 1e7.

    float("1234.5678901") * 10_000_000  ->  12345678901.000002
    """
    assert float("1234.5678901") * TICKS_PER_SECOND != 12_345_678_901
    assert from_seconds("1234.5678901") == 12_345_678_901


def test_a_float_argument_does_not_inherit_the_float_s_own_error() -> None:
    """`Decimal(float)` would carry the binary error; going via `str` does not."""
    assert from_seconds(1234.5678901) == 12_345_678_901


# --------------------------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------------------------


def test_rounds_rather_than_truncates() -> None:
    """1.5 ticks. Truncation gives 1, and the rule this project uses gives 2."""
    assert from_seconds("0.00000015") == 2


def test_rounds_half_away_from_zero_not_to_even() -> None:
    """Python's own `round()` is banker's rounding: `round(0.5)` is 0, and `round(1.5)` is 2.

    That is a defensible rule and it is not the one a reader assumes, so this module does not use
    it. Determinism means the rule is stated and tested, not inherited (Principle VII).
    """
    assert round(0.5) == 0, "if this fails, Python changed and the paragraph above is stale"
    assert from_seconds("0.00000005") == 1  # 0.5 ticks -> 1, where round() would give 0
    assert from_seconds("0.00000025") == 3  # 2.5 ticks -> 3, where round() would give 2


@pytest.mark.parametrize(
    ("milliseconds", "ticks"), [(1, 10_000), (0, 0), ("1500.5", 15_005_000), (1000, 10_000_000)]
)
def test_from_milliseconds(milliseconds: object, ticks: int) -> None:
    assert from_milliseconds(milliseconds) == ticks  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# timedelta
# --------------------------------------------------------------------------------------------


def test_from_timedelta_is_exact_on_long_durations() -> None:
    """`total_seconds()` is a float and loses precision on large values; the components do not."""
    long = timedelta(days=400, microseconds=1)
    assert from_timedelta(long) == (400 * 86_400 * 1_000_000 + 1) * 10


def test_to_timedelta_truncates_the_last_digit_and_says_so() -> None:
    """A `timedelta` resolves to the microsecond, so one tick digit cannot survive the trip."""
    assert to_timedelta(19) == timedelta(microseconds=1)
    assert from_timedelta(to_timedelta(19)) == 10


# --------------------------------------------------------------------------------------------
# On the wire
# --------------------------------------------------------------------------------------------


def test_serialises_as_a_json_integer() -> None:
    body = Sample(run_time_ticks=57_639_990_000).model_dump_json()
    assert '"RunTimeTicks":57639990000' in body
    assert json.loads(body)["RunTimeTicks"] == 57_639_990_000
    assert isinstance(json.loads(body)["RunTimeTicks"], int)


def test_a_float_is_refused_with_the_reason() -> None:
    """The mistake this module exists to prevent, caught where it is still visible.

    A caller holding `5763.999` has seconds. Silently taking the whole part would be wrong by a
    factor of ten million - a bug that looks like a wildly incorrect duration, not a type error.
    """
    with pytest.raises(ValidationError) as raised:
        Sample(run_time_ticks=5763.999)  # type: ignore[arg-type]
    assert "looks like seconds, not ticks" in str(raised.value)
    assert "from_seconds" in str(raised.value)


def test_a_whole_float_is_refused_too() -> None:
    """`5764.0` is the same mistake wearing a rounder number."""
    with pytest.raises(ValidationError):
        Sample(run_time_ticks=5764.0)  # type: ignore[arg-type]


def test_round_trip_through_json() -> None:
    original = Sample(run_time_ticks=from_seconds("5763.999"))
    assert Sample.model_validate_json(original.model_dump_json()) == original


def test_to_seconds_is_for_display_only() -> None:
    assert to_seconds(57_639_990_000) == pytest.approx(5763.999)
