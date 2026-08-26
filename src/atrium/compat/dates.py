# SPDX-License-Identifier: GPL-3.0-or-later
"""Dates on the wire, in the shape the reference produces them.

The reference is a .NET application and serialises dates in round-trip format: **seven** digits of
fractional second, always UTC, always suffixed `Z`.

    2025-06-19T00:00:00.0000000Z

Seven is more than the three most ISO-8601 parsers accept, and a strict one rejects the whole body
over it - which is why clients written against Jellyfin carry their own date handling. Atrium emits
the same seven digits, because that is what the differential harness compares against and what a
client's tolerance was built for.

**The seventh digit is always zero, and that is correct rather than a compromise.** A .NET tick is
100 nanoseconds; Python's `datetime` resolves to the microsecond. The seventh digit could only ever
carry a value this project does not have, and the reference's own values are microsecond-derived in
practice. Anyone tempted to make it "real" would be inventing precision.

Parsing is deliberately more forgiving than emitting: anything ISO-8601, three or seven fractional
digits or none, timezone present or absent. A missing timezone reads as UTC.

See docs/compatibility/behaviours.md section 1.2 and
specs/001-server-identity-and-discovery/plan.md section 6.2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer


def utc_now() -> datetime:
    """The current time, timezone-aware. Naive datetimes have no place in this project."""
    return datetime.now(UTC)


def to_wire(value: datetime) -> str:
    """Format as the reference does: UTC, seven fractional digits, `Z`.

    Built from components rather than `strftime`, because `%Y` does not zero-pad years below 1000
    consistently across platforms and a date is not the place to inherit a platform difference.
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    utc = aware.astimezone(UTC)
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
        f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
        # Six digits from the microsecond, then the seventh - always zero. See the module docstring.
        f".{utc.microsecond:06d}0Z"
    )


def from_wire(value: Any) -> Any:
    """Accept a datetime or any ISO-8601 string; leave anything else for pydantic to reject."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return value

    text = value.strip()
    if not text:
        return value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value  # pydantic produces the error message, with the field name attached
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


#: The type every date-valued field uses. A plain `datetime` would serialise in pydantic's own
#: format - offset `+00:00`, six fractional digits - which is a delta a client can see. The unit
#: sweep exists to catch a field that forgets this annotation.
WireDateTime = Annotated[
    datetime,
    BeforeValidator(from_wire),
    # `when_used="json"` and not `"always"`: JSON is what reaches a client and must be exact, while
    # a Python-mode dump keeps a real datetime for callers doing arithmetic on it.
    PlainSerializer(to_wire, return_type=str, when_used="json"),
]

__all__ = ["WireDateTime", "from_wire", "to_wire", "utc_now"]
