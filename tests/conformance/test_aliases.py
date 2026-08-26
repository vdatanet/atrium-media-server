# SPDX-License-Identifier: GPL-3.0-or-later
"""Every alias this project produces is a property name the reference actually uses.

This is the sweep that makes Principle I enforceable rather than aspirational. It asks a stricter
question than "is this PascalCase?": a generator turns `is_hd` into `IsHd`, which is PascalCase and
is not what the reference calls that property, so a casing rule would pass it and a client would
receive a field it does not know.

The index it checks against is committed, so this runs with no network and no fetched document -
see tools/extract_property_names.py for why that matters.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Iterable
from pathlib import Path

import pytest
from pydantic import Field
from pydantic.alias_generators import to_pascal

from atrium.compat.aliases import IRREGULAR, atrium_alias
from atrium.compat.model import AtriumModel
from atrium.compat.registry import import_model_modules, iter_models

INDEX = Path(__file__).resolve().parents[2] / "docs" / "compatibility" / "property-names.json"


@pytest.fixture(scope="module")
def reference_names() -> frozenset[str]:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    return frozenset(data["names"])


def find_problems(
    models: Iterable[type[AtriumModel]], reference_names: frozenset[str]
) -> list[str]:
    """Report every field whose wire name the reference does not have."""
    problems: list[str] = []
    for model in models:
        for field_name, field in model.model_fields.items():
            alias = field.serialization_alias or field.alias or field_name
            if alias in reference_names:
                continue
            near = difflib.get_close_matches(alias, reference_names, n=1)
            suggestion = f" Did you mean {near[0]!r}?" if near else ""
            problems.append(
                f"{model.__module__}.{model.__qualname__}.{field_name} serialises as {alias!r}, "
                f"which the reference never uses.{suggestion}"
            )
    return problems


def test_index_is_present_and_plausible(reference_names: frozenset[str]) -> None:
    """A missing or truncated index would make every other assertion here vacuous."""
    assert len(reference_names) > 900, (
        f"the property-name index holds {len(reference_names)} names, which is too few to be the "
        "pinned document's. Regenerate it with tools/extract_property_names.py."
    )


def test_every_alias_is_a_reference_property_name(reference_names: frozenset[str]) -> None:
    import_model_modules()
    problems = find_problems(iter_models(), reference_names)
    assert not problems, (
        "These fields would reach a client under a name the reference does not have:\n  "
        + "\n  ".join(problems)
        + "\n\nEither the field is misspelled, or its wire name needs an entry in "
        "atrium.compat.aliases.IRREGULAR."
    )


# --------------------------------------------------------------------------------------------
# The sweep is worth nothing if it cannot reject what it exists to reject. These three assert
# that it fails on the exact mistakes it was written for, rather than passing because nothing has
# been built yet.
# --------------------------------------------------------------------------------------------


def test_it_rejects_a_generated_acronym(reference_names: frozenset[str]) -> None:
    """`IsHd` is PascalCase, looks right, and is not what the reference calls that property."""

    class _Generated(AtriumModel):
        is_hd: bool = Field(serialization_alias=to_pascal("is_hd"))

    problems = find_problems([_Generated], reference_names)
    assert len(problems) == 1
    assert "'IsHd'" in problems[0]
    assert "Did you mean 'IsHD'?" in problems[0], (
        "the failure must name the real spelling; a bare rejection sends the reader hunting"
    )


def test_it_rejects_an_invented_field(reference_names: frozenset[str]) -> None:
    class _Invented(AtriumModel):
        atrium_only_extension: str = "x"

    problems = find_problems([_Invented], reference_names)
    assert len(problems) == 1, "a field the reference has no name for is a delta (Principle I)"


def test_it_accepts_what_the_reference_uses(reference_names: frozenset[str]) -> None:
    class _Correct(AtriumModel):
        local_address: str = ""
        is_hd: bool = False
        three_letter_iso_language_name: str = ""

    assert find_problems([_Correct], reference_names) == []


def test_the_irregular_table_is_load_bearing(reference_names: frozenset[str]) -> None:
    """Each entry exists because the generator gets that name wrong, and the right name is real."""
    for field_name, wire_name in IRREGULAR.items():
        assert atrium_alias(field_name) == wire_name
        assert wire_name in reference_names, f"{wire_name!r} is not a name the reference uses"
        assert to_pascal(field_name) != wire_name, (
            f"{field_name!r} does not need an entry: the generator already produces {wire_name!r}"
        )
