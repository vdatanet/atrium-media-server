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
import re
from collections.abc import Iterable
from pathlib import Path

import pytest
from pydantic import Field
from pydantic.alias_generators import to_pascal

from atrium.compat.aliases import IRREGULAR, atrium_alias
from atrium.compat.model import AtriumModel, declares_ordinals
from atrium.compat.registry import import_model_modules, iter_models

INDEX = Path(__file__).resolve().parents[2] / "docs" / "compatibility" / "property-names.json"


def snake_case_names(names: Iterable[str]) -> list[str]:
    """Names Jellyfin could not have serialised. Separate so the rule can be shown to reject."""
    return [name for name in names if "_" in name]


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


def test_index_is_internally_consistent() -> None:
    """The index describes itself, and the description has to be true.

    Its freshness against the pinned document can only be checked where the document is, and the
    document is fetched rather than vendored - so CI checks what is checkable without one. This is
    that: sorted, unique, and counted correctly. A hand-edited index shows up here.
    """
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    names = data["names"]
    assert data["count"] == len(names), "the index's own count disagrees with its contents"
    assert len(set(names)) == len(names), "the index repeats a name"
    assert names == sorted(names), "the index is not sorted; it is generated, so it should be"


def test_no_index_name_is_snake_case() -> None:
    """The invariant that would have caught a plugin's names in the index, with no document.

    Jellyfin serialises PascalCase, and camelCase in its package and error schemas. It never
    serialises snake_case: of the 1026 names in the 10.11.11 document, none contains an
    underscore. So an underscore in the index cannot have come from Jellyfin.

    Something did. The index carried `not_found` from its first commit until 2026-09-01, along
    with eighteen more Trakt names - a Jellyfin's OpenAPI document is the core API plus whatever
    plugins are installed, and the server the index was extracted from had one the reference
    server does not (docs/compatibility/reference-target.md section 1).

    Nothing could see it. The freshness check needs the document, which CI has not got and which
    for that pin nobody had at all; the assertions that run without one - sorted, unique,
    self-counting - are all true of a polluted index. This one is not, and it needs no document.
    """
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    snake = snake_case_names(data["names"])
    assert not snake, (
        f"the index carries {snake}, and Jellyfin serialises no name with an underscore. A "
        "document extracted from a server with plugins installed carries their schemas too - "
        "regenerate from a stock server."
    )


def test_the_snake_case_rule_rejects_the_name_it_was_written_for() -> None:
    """`not_found` sat in the index for the life of the project. The rule has to reject it."""
    assert snake_case_names(["Name", "imageUrl", "not_found", "GenreItems"]) == ["not_found"]


def test_index_and_surface_pin_the_same_document() -> None:
    """Two committed artefacts, one pinned version, and nothing was checking they agreed.

    The index is extracted from the pinned OpenAPI document and `surface.yaml` is validated
    against it. If those two ever name different versions, one of them was regenerated against a
    server somebody had upgraded - which is exactly how a "pinned" reference stops being one.
    """
    surface = (
        Path(__file__).resolve().parents[2] / "docs" / "compatibility" / "surface.yaml"
    ).read_text(encoding="utf-8")
    pinned = re.search(r'jellyfin_openapi_version:\s*"([^"]+)"', surface)
    assert pinned is not None, "surface.yaml no longer pins an OpenAPI version"

    indexed = json.loads(INDEX.read_text(encoding="utf-8"))["reference_version"]
    assert indexed == pinned.group(1), (
        f"the property-name index was extracted from {indexed} and surface.yaml pins "
        f"{pinned.group(1)}. Moving the pin has a procedure - see "
        f"docs/compatibility/conformance.md."
    )


def test_every_alias_is_pascal_case() -> None:
    """Acceptance criterion 10, asserted directly rather than left to follow from the sweep below.

    It does follow: every name in the reference's index is PascalCase, so an alias that is not
    cannot be in it. But the two say different things when they fail - this one says *the casing
    rule broke*, which is a mistake in `atrium.compat.model`, and the other says *this field has a
    name the reference does not use*, which is a mistake in one field. Conflating them would send
    the next reader to the wrong file.
    """
    import_model_modules()
    wrong = []
    for model in iter_models():
        for field_name, field in model.model_fields.items():
            alias = field.serialization_alias or field.alias or field_name
            if not alias[:1].isupper() or "_" in alias:
                wrong.append(f"{model.__qualname__}.{field_name} serialises as {alias!r}")
    assert not wrong, "not PascalCase on the wire:\n  " + "\n  ".join(wrong)


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


# ------------------------------------------------------------------------------------------------
# Every vocabulary a body binds has a declared ordinal table (012 T7)
# ------------------------------------------------------------------------------------------------


def test_every_vocabulary_a_model_binds_declares_its_ordinals() -> None:
    """The same sweep, asked about enumerations instead of names.

    The reference reads every enumerated property of a body through one converter, so an ordinal
    binds wherever a name does `[probe: tools/probe_playback_info.py, Jellyfin 10.11.11,
    2026-09-04]`. An enumeration with no registered table binds no ordinal at all - a `400` where
    the reference answers `200`, on a property nobody remembered - and the table cannot be
    counted off the declaration: `CodecType` declares `Video = 0` where this project declares its
    audio member first, and `ProfileConditionValue` skips 15.

    So the rule is the one the sweep above uses for names: a model author cannot forget, because
    forgetting fails here rather than on somebody's client.
    """
    import_model_modules()
    unregistered = sorted(
        f"{model.__module__}.{model.__qualname__}.{field} binds {vocabulary.__name__}"
        for model in iter_models()
        for field, vocabulary in model._vocabularies().items()
        if not declares_ordinals(vocabulary)
    )
    assert not unregistered, (
        "these fields are bound to an enumeration with no declared ordinal table, so a client "
        f"sending the number the reference accepts is refused here: {unregistered}. Read the "
        "reference's own enum, write the numbers it declares, and apply @wire_ordinals."
    )


def test_the_sweep_finds_the_vocabularies_it_is_written_for() -> None:
    """A path or an import that stopped finding models would make the test above vacuous."""
    import_model_modules()
    bound = {
        vocabulary.__name__
        for model in iter_models()
        for vocabulary in model._vocabularies().values()
    }
    assert bound >= {
        "ProfileType",
        "CodecKind",
        "ConditionType",
        "ConditionProperty",
        "SubtitleMethod",
    }, f"the five vocabularies a device profile carries are the sweep's subject; it found {bound}"
