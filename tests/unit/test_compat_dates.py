# SPDX-License-Identifier: GPL-3.0-or-later
"""Dates on the wire: seven fractional digits, always UTC, always `Z`."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from atrium.compat.dates import WireDateTime, from_wire, to_wire, utc_now
from atrium.compat.model import AtriumModel


class Sample(AtriumModel):
    premiere_date: WireDateTime


# --------------------------------------------------------------------------------------------
# Emitting
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2025, 6, 19, tzinfo=UTC), "2025-06-19T00:00:00.0000000Z"),
        (datetime(2025, 6, 19, 0, 0, 0, 123456, tzinfo=UTC), "2025-06-19T00:00:00.1234560Z"),
        (datetime(2025, 12, 31, 23, 59, 59, 999999, tzinfo=UTC), "2025-12-31T23:59:59.9999990Z"),
        # A non-UTC input is converted, not relabelled.
        (
            datetime(2025, 6, 19, 2, tzinfo=timezone(timedelta(hours=2))),
            "2025-06-19T00:00:00.0000000Z",
        ),
        # A naive input is read as UTC rather than as local time. DTZ001 is suppressed because
        # the naive datetime IS the case under test - the rule is right about production code.
        (datetime(2025, 6, 19, 12, 34, 56), "2025-06-19T12:34:56.0000000Z"),  # noqa: DTZ001
        # Years below 1000 must stay zero-padded; `%Y` does not guarantee that on every platform.
        (datetime(1, 2, 3, tzinfo=UTC), "0001-02-03T00:00:00.0000000Z"),
    ],
)
def test_to_wire(value: datetime, expected: str) -> None:
    assert to_wire(value) == expected


def test_the_seventh_digit_is_always_zero() -> None:
    """A .NET tick is 100ns; Python resolves to the microsecond.

    The seventh digit could only ever carry precision this project does not have. If this test is
    failing because someone made it "real", they are inventing data - read the module docstring
    before changing it.
    """
    for microsecond in (0, 1, 999999, 500000):
        assert to_wire(datetime(2025, 1, 1, microsecond=microsecond, tzinfo=UTC)).endswith("0Z")


def test_the_fraction_is_exactly_seven_digits() -> None:
    fraction = to_wire(datetime(2025, 1, 1, tzinfo=UTC)).split(".")[1].removesuffix("Z")
    assert len(fraction) == 7


# --------------------------------------------------------------------------------------------
# Accepting
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "2025-06-19T00:00:00.0000000Z",  # what the reference emits
        "2025-06-19T00:00:00.000Z",  # three digits, what most clients emit
        "2025-06-19T00:00:00Z",  # none at all
        "2025-06-19T00:00:00",  # no timezone: read as UTC
        "2025-06-19T02:00:00+02:00",  # an offset
        "2025-06-19T00:00:00.123456789Z",  # more precision than anyone has
    ],
)
def test_from_wire_accepts(text: str) -> None:
    """Parsing is deliberately more forgiving than emitting."""
    parsed = from_wire(text)
    assert isinstance(parsed, datetime)
    assert parsed.tzinfo is not None, "a parsed date is never naive"
    assert parsed.date().isoformat() == "2025-06-19"


def test_a_naive_string_is_utc_not_local() -> None:
    assert from_wire("2025-06-19T12:00:00") == datetime(2025, 6, 19, 12, tzinfo=UTC)


def test_a_naive_datetime_is_utc_not_local() -> None:
    naive = datetime(2025, 6, 19, 12)  # noqa: DTZ001 - the naive value is the case under test
    assert from_wire(naive) == datetime(2025, 6, 19, 12, tzinfo=UTC)


def test_unparseable_input_is_left_for_pydantic() -> None:
    """Returning the value unchanged lets pydantic raise with the field name attached."""
    assert from_wire("not a date") == "not a date"
    assert from_wire(None) is None


# --------------------------------------------------------------------------------------------
# Through a model, which is where it matters
# --------------------------------------------------------------------------------------------


def test_round_trip_through_json() -> None:
    original = "2025-06-19T00:00:00.1234560Z"
    body = json.loads(Sample.model_validate({"PremiereDate": original}).model_dump_json())
    assert body["PremiereDate"] == original


def test_json_mode_emits_the_wire_string() -> None:
    body = json.loads(Sample(premiere_date=datetime(2025, 6, 19, tzinfo=UTC)).model_dump_json())
    assert body["PremiereDate"] == "2025-06-19T00:00:00.0000000Z"


def test_python_mode_keeps_a_datetime() -> None:
    """JSON is the wire and must be exact; a Python dump keeps a value callers can compute with."""
    dumped = Sample(premiere_date=datetime(2025, 6, 19, tzinfo=UTC)).model_dump()
    assert isinstance(dumped["PremiereDate"], datetime)


def test_a_plain_datetime_field_would_not_match_the_reference() -> None:
    """The reason `WireDateTime` exists, asserted rather than asserted-in-a-comment.

    The unit sweep (T7) is what catches a field that forgets the annotation; this records what it
    is catching.
    """

    class Unannotated(AtriumModel):
        premiere_date: datetime

    body = json.loads(
        Unannotated(premiere_date=datetime(2025, 6, 19, tzinfo=UTC)).model_dump_json()
    )
    assert body["PremiereDate"] != "2025-06-19T00:00:00.0000000Z"


def test_utc_now_is_aware() -> None:
    assert utc_now().tzinfo is not None
