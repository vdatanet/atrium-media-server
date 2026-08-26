# SPDX-License-Identifier: GPL-3.0-or-later
"""Durations and positions, in the unit the reference uses.

Every duration and position the API carries - `RunTimeTicks`, `PositionTicks`,
`PlaybackPositionTicks`, `StartPositionTicks` - is expressed in **ticks of 100 nanoseconds**,
10,000,000 to the second. It is a .NET inheritance and it is not negotiable: a progress bar drawn
from seconds where the client expects ticks is wrong by a factor of ten million.

**Ticks are the internal unit**, not a serialisation detail. Durations are stored and passed as
ticks, so no boundary can forget to convert. Conversion happens once, where a value enters the
system from something that speaks another unit - `ffprobe`, a sidecar, a user - and this module is
where that once lives. See docs/architecture.md section 4.

Conversion goes through `Decimal`, because the obvious float version is wrong:

    float("1234.5678901") * 10_000_000  ->  12345678901.000002

and rounds **half away from zero**, not with Python's banker's rounding, so the rule is the one a
reader assumes and the same on every platform (Principle VII).

See specs/001-server-identity-and-discovery/plan.md section 6.3.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Annotated, Any, Final

from pydantic import BeforeValidator

#: 100-nanosecond units per second.
TICKS_PER_SECOND: Final = 10_000_000

#: 100-nanosecond units per millisecond.
TICKS_PER_MILLISECOND: Final = 10_000

#: What `timedelta` resolves to, and therefore what a round trip through one costs.
TICKS_PER_MICROSECOND: Final = 10

_Number = int | float | str | Decimal


def _decimal(value: _Number) -> Decimal:
    """Exactly, from whatever the caller has.

    `str` is accepted first-class because that is how `ffprobe` reports a duration, and turning it
    into a float on the way past would discard precision this function exists to keep.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        return Decimal(value.strip())
    return Decimal(str(value))  # via str: Decimal(float) would carry the float's own error


def _round(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_seconds(value: _Number) -> int:
    """Ticks from seconds. Accepts the string form `ffprobe` produces."""
    return _round(_decimal(value) * TICKS_PER_SECOND)


def from_milliseconds(value: _Number) -> int:
    return _round(_decimal(value) * TICKS_PER_MILLISECOND)


def from_timedelta(value: timedelta) -> int:
    # total_seconds() is a float and loses precision on large durations, so go via the exact
    # integer components timedelta already stores.
    microseconds = (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
    return microseconds * TICKS_PER_MICROSECOND


def to_seconds(ticks: int) -> float:
    """Seconds from ticks, for display and arithmetic. Lossy by nature; never store the result."""
    return ticks / TICKS_PER_SECOND


def to_timedelta(ticks: int) -> timedelta:
    """A `timedelta` resolves to the microsecond, so this truncates the last tick digit."""
    return timedelta(microseconds=ticks // TICKS_PER_MICROSECOND)


def _reject_fractional(value: Any) -> Any:
    """Refuse a float where ticks are expected.

    This is the mistake the module exists to prevent, caught at the one moment it is visible. A
    caller with `5763.999` has seconds, not ticks, and silently accepting the whole part would be
    wrong by a factor of ten million - a bug that looks like a wildly incorrect duration rather
    than like a type error.
    """
    if isinstance(value, float):
        raise ValueError(
            f"{value!r} looks like seconds, not ticks. Ticks are 100-nanosecond integers; "
            f"convert with atrium.compat.ticks.from_seconds()."
        )
    if isinstance(value, Decimal):
        try:
            return int(value) if value == value.to_integral_value() else value
        except InvalidOperation:
            return value
    return value


#: The type every tick-valued field uses. Ticks serialise as JSON integers, never floats and never
#: strings - the unit sweep exists to catch a field that gets that wrong.
WireTicks = Annotated[int, BeforeValidator(_reject_fractional)]

__all__ = [
    "TICKS_PER_MICROSECOND",
    "TICKS_PER_MILLISECOND",
    "TICKS_PER_SECOND",
    "WireTicks",
    "from_milliseconds",
    "from_seconds",
    "from_timedelta",
    "to_seconds",
    "to_timedelta",
]
