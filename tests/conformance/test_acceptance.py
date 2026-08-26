# SPDX-License-Identifier: GPL-3.0-or-later
"""Every acceptance criterion of feature 001, mapped to the test that asserts it.

The definition of done in `tasks.md` says *"every acceptance criterion has a passing test — all
eleven, by name"*. That is a claim somebody has to check, and checking it by reading two documents
side by side is a thing nobody does twice. This file is the map, and it fails three ways:

* an acceptance criterion in the specification with no test named here — the box cannot be ticked;
* a test named here that no longer exists — a rename or a deletion that silently orphaned a
  criterion;
* a count that no longer matches the specification — a criterion added or removed.

It asserts that the tests **exist**, not that they pass; the suite they are in does that. What it
protects is the *mapping*, which is the part that rots quietly.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.conformance

SPEC = Path(__file__).resolve().parents[2] / "specs" / "001-server-identity-and-discovery/spec.md"

#: Criterion -> the tests that assert it. A criterion whose only coverage is indirect names the
#: test that covers it indirectly and says so, rather than being left out.
ACCEPTANCE: dict[int, tuple[str, ...]] = {
    1: (
        "tests.conformance.test_golden:test_public_system_info",
        "tests.conformance.test_system_routes:test_public_info_answers_before_anything_is_configured",
        "tests.conformance.test_system_routes:test_public_info_has_exactly_the_seven_fields",
    ),
    2: (
        "tests.conformance.test_system_routes:test_product_name_is_the_discriminator",
        "tests.conformance.test_system_routes:test_operating_system_is_the_empty_string",
    ),
    3: ("tests.conformance.test_system_routes:test_version_is_the_reference_version_not_atriums",),
    4: (
        "tests.unit.test_config_state:test_identity_survives_a_restart",
        "tests.unit.test_config_state:test_identity_survives_a_rebuild_of_the_store_from_empty",
        "tests.conformance.test_system_routes:test_id_is_canonical",
    ),
    5: (
        "tests.conformance.test_system_routes:test_system_info_refuses_without_a_token",
        "tests.conformance.test_system_routes:test_system_info_answers_with_one",
        "tests.conformance.test_system_routes:test_system_info_is_a_superset_that_agrees",
    ),
    6: (
        "tests.conformance.test_system_routes:test_ping_returns_the_product_name",
        "tests.conformance.test_golden:test_ping_answers_both_methods_identically",
    ),
    7: (
        "tests.unit.test_net_address:test_a_published_url_is_returned_verbatim",
        "tests.unit.test_net_address:test_a_published_url_beats_everything_else",
    ),
    8: ("tests.unit.test_net_address:test_two_requesters_on_two_networks_get_two_answers",),
    9: (
        "tests.conformance.test_golden:test_every_profile_gets_the_pascal_case_golden",
        "tests.conformance.test_golden:test_the_camel_case_profile_is_a_known_gap",
    ),
    10: (
        "tests.conformance.test_aliases:test_every_alias_is_pascal_case",
        "tests.conformance.test_aliases:test_every_alias_is_a_reference_property_name",
    ),
    11: (
        "tests.conformance.test_routes:test_the_reference_spellings_all_reach_the_route",
        "tests.conformance.test_routes:test_two_trailing_slashes_are_not_one",
        "tests.conformance.test_routes:test_an_unknown_path_is_an_empty_404",
        "tests.conformance.test_routes:test_a_method_the_path_does_not_have_is_an_empty_405",
        "tests.conformance.test_routes:test_allow_lists_every_method_the_path_has",
    ),
}


def specified_criteria() -> list[int]:
    """The numbers of the criteria in spec section 5, read from the specification itself."""
    body = SPEC.read_text(encoding="utf-8")
    section = body.split("## 5. Acceptance criteria", 1)[1].split("\n## ", 1)[0]
    return [int(number) for number in re.findall(r"^(\d+)\. ", section, flags=re.MULTILINE)]


def test_the_specification_still_has_the_criteria_this_map_expects() -> None:
    """Numbered one to eleven, with none missing in the middle."""
    criteria = specified_criteria()
    assert criteria == list(range(1, len(criteria) + 1)), (
        f"spec section 5 numbers its criteria {criteria}, which is not a list from 1"
    )
    assert set(criteria) == set(ACCEPTANCE), (
        f"the specification has {sorted(set(criteria) - set(ACCEPTANCE))} that this map does not, "
        f"and this map has {sorted(set(ACCEPTANCE) - set(criteria))} that it does not. A criterion "
        f"without a test cannot be ticked off in the definition of done."
    )


@pytest.mark.parametrize("criterion", sorted(ACCEPTANCE))
def test_every_criterion_names_tests_that_exist(criterion: int) -> None:
    names = ACCEPTANCE[criterion]
    assert names, f"AC-{criterion} names no test"
    for name in names:
        module_name, _, function = name.partition(":")
        module = importlib.import_module(module_name)
        assert hasattr(module, function), (
            f"AC-{criterion} names {name}, which does not exist. If it was renamed, rename it "
            f"here too; if it was deleted, the criterion it covered is now unasserted."
        )
