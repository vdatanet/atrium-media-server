# SPDX-License-Identifier: GPL-3.0-or-later
"""Every field carries its value in the unit and format the reference uses.

The sibling of the alias sweep. That one asks whether a field arrives under the right *name*; this
one asks whether it arrives with the right *value shape* - an integer count of 100-nanosecond
ticks, a date with seven fractional digits and a `Z`.

Both failures are invisible to a reader of the code. `premiere_date: datetime` looks completely
correct and serialises as `2025-06-19T00:00:00+00:00`, which is a different string from the one
every Jellyfin client's date handling was built for.

**Fields are checked by behaviour, not by structure.** Each one is rebuilt into a single-field
probe model and actually serialised, so the sweep tests what a client would receive rather than
what the annotation appears to promise.
"""

from __future__ import annotations

import json
import types
import typing
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError, create_model
from pydantic.fields import FieldInfo

from atrium.compat.dates import WireDateTime, to_wire
from atrium.compat.model import AtriumModel
from atrium.compat.registry import import_model_modules, iter_models
from atrium.compat.ticks import WireTicks

SAMPLE_DATETIME = datetime(2025, 6, 19, 12, 34, 56, 123456, tzinfo=UTC)
SAMPLE_TICKS = 57_639_990_000


def _mentions(annotation: Any, wanted: type) -> bool:
    """Is `wanted` anywhere in this annotation, including inside a union or an Optional?"""
    if annotation is wanted:
        return True
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType) or origin is not None:
        return any(_mentions(arg, wanted) for arg in typing.get_args(annotation))
    return False


def _probe(field: FieldInfo) -> type[AtriumModel]:
    """A one-field model carrying this field's exact annotation, so it can be serialised."""
    annotation = field.rebuild_annotation()
    return create_model("Probe", __base__=AtriumModel, value=(annotation, ...))


def _serialise(field: FieldInfo, value: Any) -> Any:
    return json.loads(_probe(field)(value=value).model_dump_json())["Value"]


def check_field(label: str, name: str, field: FieldInfo) -> list[str]:
    """Every way this one field could carry the wrong shape."""
    problems: list[str] = []
    wire_name = field.serialization_alias or field.alias or name

    if _mentions(field.annotation, datetime):
        emitted = _serialise(field, SAMPLE_DATETIME)
        expected = to_wire(SAMPLE_DATETIME)
        if emitted != expected:
            problems.append(
                f"{label}.{name} is date-valued and serialises as {emitted!r}, not {expected!r}. "
                f"Annotate it `WireDateTime`, not `datetime`."
            )

    # Start OR end, case-sensitive. Measured against the 1043 names in the pinned document:
    # `endswith` alone covers 13 (EndDate, LastPlayedDate, ...) and misses the 7 that start with
    # it (DateCreated, DateLastMediaAdded, ...), which the plan's wording did not account for.
    # Widening further to "contains" would gain one real field (ImageDateModified) and three false
    # positives - ReleaseDateFormat is an enum, UseFileCreationTimeForDateAdded is a boolean - so
    # it stops here. ImageDateModified is covered by the type rule above whenever it is annotated
    # as a date, which is the only way it would be right anyway.
    if (wire_name.startswith("Date") or wire_name.endswith("Date")) and not _mentions(
        field.annotation, datetime
    ):
        problems.append(
            f"{label}.{name} is called {wire_name!r} but is not date-valued "
            f"({field.annotation!r}). The reference sends a date there."
        )

    if wire_name.endswith("Ticks"):
        if not _mentions(field.annotation, int):
            problems.append(
                f"{label}.{name} is called {wire_name!r} but is not integer-valued "
                f"({field.annotation!r}). Ticks are whole 100-nanosecond units."
            )
        else:
            emitted = _serialise(field, SAMPLE_TICKS)
            if not isinstance(emitted, int) or isinstance(emitted, bool):
                problems.append(
                    f"{label}.{name} serialises ticks as {type(emitted).__name__}, not an integer."
                )
            # A WHOLE float, deliberately. A plain `int` field already rejects 5763.999 - a
            # float with a fraction cannot be an integer - so probing with one would report that
            # `int` is safe. It is not: `int` accepts 5764.0, which is the same caller with the
            # same mistake and a rounder number. This probe catches the half that gets through.
            try:
                _probe(field)(value=5764.0)
            except ValidationError:
                pass
            else:
                problems.append(
                    f"{label}.{name} accepts a float where ticks are expected, so a caller passing "
                    f"seconds is wrong by a factor of ten million and nothing says so. "
                    f"Annotate it `WireTicks`, not `int`."
                )

    return problems


def test_every_field_carries_the_right_shape() -> None:
    import_model_modules()

    problems: list[str] = []
    for model in iter_models():
        label = f"{model.__module__}.{model.__qualname__}"
        for name, field in model.model_fields.items():
            problems.extend(check_field(label, name, field))

    assert not problems, "Fields whose value shape a client would not recognise:\n  " + "\n  ".join(
        problems
    )


# --------------------------------------------------------------------------------------------
# Like the alias sweep, this passes vacuously until models exist. These assert it fails on the
# mistakes it was written for, rather than on nothing.
# --------------------------------------------------------------------------------------------


def _problems_for(annotation: Any, name: str = "value") -> list[str]:
    model = create_model("Case", __base__=AtriumModel, **{name: (annotation, ...)})  # type: ignore[call-overload]
    return check_field("Case", name, model.model_fields[name])


def test_it_rejects_a_plain_datetime() -> None:
    """The mistake that looks most correct: `premiere_date: datetime`.

    Pydantic's own output is closer than it looks - `2025-06-19T12:34:56.123456Z`, right down to
    the `Z` - and differs only in carrying six fractional digits where the reference carries seven.
    That is precisely the kind of difference nobody spots by reading, and exactly what a client's
    date handling was built around.
    """
    problems = _problems_for(datetime, "premiere_date")
    assert len(problems) == 1
    assert ".123456Z" in problems[0], "the failure shows what a client would actually receive"
    assert ".1234560Z" in problems[0], "and what it should have received"
    assert "WireDateTime" in problems[0], "and what to write instead"


def test_it_accepts_an_annotated_datetime() -> None:
    assert _problems_for(WireDateTime, "premiere_date") == []


def test_it_accepts_a_nullable_annotated_datetime() -> None:
    """Most date fields in the reference are nullable; the check must see through the union."""
    assert _problems_for(WireDateTime | None, "premiere_date") == []


def test_it_rejects_a_nullable_plain_datetime() -> None:
    assert len(_problems_for(datetime | None, "premiere_date")) == 1


@pytest.mark.parametrize("name", ["premiere_date", "date_created", "last_played_date"])
def test_it_rejects_a_date_named_field_that_is_not_a_date(name: str) -> None:
    """Both spellings the reference uses: `PremiereDate` and `DateCreated`."""
    problems = _problems_for(str, name)
    assert len(problems) == 1
    assert "not date-valued" in problems[0]


@pytest.mark.parametrize("name", ["release_date_format", "use_file_creation_time_for_date_added"])
def test_it_does_not_flag_names_that_merely_contain_date(name: str) -> None:
    """Real property names from the reference: an enum and a boolean, neither of them dates.

    A "contains Date" rule would flag both. A sweep with false positives gets switched off.
    """
    assert _problems_for(str, name) == []


def test_it_rejects_ticks_that_accept_a_float() -> None:
    """`run_time_ticks: int` looks right and lets seconds through as a whole number.

    Measured while writing this: a plain `int` field rejects `5763.999` on its own, because a
    fractional float is not an integer. It accepts `5764.0`. So `int` catches the careless half of
    the mistake and passes the half that is indistinguishable from a correct value.
    """
    problems = _problems_for(int, "run_time_ticks")
    assert len(problems) == 1
    assert "ten million" in problems[0]
    assert "WireTicks" in problems[0]


def test_it_accepts_annotated_ticks() -> None:
    assert _problems_for(WireTicks, "run_time_ticks") == []
    assert _problems_for(WireTicks | None, "run_time_ticks") == []


def test_it_rejects_ticks_that_are_not_integers() -> None:
    problems = _problems_for(str, "run_time_ticks")
    assert len(problems) == 1
    assert "not integer-valued" in problems[0]


@pytest.mark.parametrize("annotation", [str, int, bool, list[str]])
def test_it_leaves_ordinary_fields_alone(annotation: Any) -> None:
    """A sweep that flags things it was not written for gets switched off within a week."""
    assert _problems_for(annotation, "name") == []
