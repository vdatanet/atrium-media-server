# SPDX-License-Identifier: GPL-3.0-or-later
"""Every acceptance criterion of every implemented feature, mapped to the test that asserts it.

Every feature's definition of done says some version of *"every acceptance criterion has a passing
test, by name"* - eleven of them for 001, eleven for 002, thirteen for 003. That is a claim somebody
has to check, and checking it by reading two documents side by side is a thing nobody does twice.
This file is the map, and it fails three ways:

* an acceptance criterion in the specification with no test named here — the box cannot be ticked;
* a test named here that no longer exists — a rename or a deletion that silently orphaned a
  criterion;
* a count that no longer matches the specification — a criterion added or removed.

It asserts that the tests **exist**, not that they pass; the suite they are in does that. What it
protects is the *mapping*, which is the part that rots quietly.

**It was written for one feature and now carries three.** 002 T18 turned one specification path and
one map into a table of them, betting that adding 003 would then be one entry and one dictionary
rather than a third copy of this file. It was: nothing below changed shape for 003, and the diff
that added it is a dictionary and a line in `FEATURES`. That is the whole of what the restructure
was for, and it is recorded here because a restructure nobody checks the payoff of is a refactor
that might have been a waste.

**003's map is the widest**, and the reason is that 003 has no HTTP surface: its criteria are proven
against fixtures at four different levels - the naming corpus, the resolver, a real scan into a real
database, and the sort-name table - and several criteria are asserted at more than one. A criterion
covered only by the corpus names `test_the_corpus`, which is the parametrised table that runs every
row of it.

It earned itself in 001 at T19: renaming a test made it fail and **name the criterion left
unasserted**, which nobody would have noticed by reading.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.conformance

SPECS = Path(__file__).resolve().parents[2] / "specs"

#: Criterion -> the tests that assert it. A criterion whose only coverage is indirect names the
#: test that covers it indirectly and says so, rather than being left out.
FEATURE_001: dict[int, tuple[str, ...]] = {
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
        "tests.conformance.test_golden:test_the_pascal_case_profiles_get_the_pascal_case_golden",
        "tests.conformance.test_golden:test_the_camel_case_profile_gets_its_own_golden",
        "tests.conformance.test_golden:test_the_response_echoes_the_profile_that_matched",
        "tests.unit.test_compat_profiles:test_negotiation",
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


#: Feature 002. Three criteria are asserted at the HTTP boundary rather than against the function
#: behind the route, because Principle VIII does not accept them anywhere else.
FEATURE_002: dict[int, tuple[str, ...]] = {
    1: (
        "tests.conformance.test_user_routes:test_valid_credentials_answer_with_a_token_a_user_and_a_session",
        "tests.conformance.test_user_routes:test_the_result_carries_the_reference_field_order",
        "tests.conformance.test_golden_users:test_authenticate_by_name",
    ),
    2: (
        "tests.conformance.test_user_routes:test_the_refusals_differ_only_in_their_status",
        "tests.conformance.test_user_routes:test_an_unknown_username_is_401",
        "tests.conformance.test_user_routes:test_a_disabled_account_is_403",
        "tests.conformance.test_user_routes:test_a_missing_client_header_is_400_and_specifically_not_401",
    ),
    3: (
        "tests.conformance.test_auth_mechanisms:test_every_mechanism_authenticates_every_route_class",
        "tests.conformance.test_auth_mechanisms:test_the_precedence_chain_resolves_as_it_was_measured",
        "tests.conformance.test_auth_mechanisms:test_the_stubs_are_not_asserted_to_demand_a_token",
        "tests.conformance.test_auth_mechanisms:test_the_query_forms_are_the_only_ones_a_player_can_use",
    ),
    4: (
        "tests.unit.test_require_user:test_no_token_is_the_empty_401_that_001_measured",
        "tests.unit.test_require_user:test_a_token_whose_account_was_disabled_is_403",
        "tests.conformance.test_user_routes:test_an_ordinary_user_reading_another_is_403",
    ),
    5: (
        "tests.conformance.test_user_routes:test_re_authenticating_invalidates_the_previous_token",
        "tests.unit.test_session_registry:test_there_is_no_moment_at_which_both_tokens_work",
        "tests.unit.test_session_registry:test_re_authenticating_replaces_the_session_rather_than_adding_one",
    ),
    6: (
        "tests.conformance.test_user_routes:test_public_users_answers_without_a_token",
        "tests.conformance.test_user_routes:test_public_users_sends_the_whole_object_as_the_reference_does",
        "tests.conformance.test_user_routes:test_a_hidden_user_is_not_on_the_login_screen",
        "tests.conformance.test_user_routes:test_every_user_hidden_is_an_empty_list_and_a_200",
        "tests.conformance.test_golden_users:test_public_users",
    ),
    7: (
        "tests.conformance.test_user_routes:test_a_user_may_always_read_themselves",
        "tests.conformance.test_user_routes:test_an_ordinary_user_reading_another_is_403",
        "tests.conformance.test_user_routes:test_an_administrator_reading_another_is_200",
    ),
    8: (
        "tests.conformance.test_user_routes:test_a_configuration_round_trips_including_what_v1_does_not_act_on",
        "tests.conformance.test_user_routes:test_posting_a_configuration_replaces_rather_than_merges",
        "tests.unit.test_policy:test_a_policy_from_a_newer_server_gets_its_own_data_back",
    ),
    9: (
        "tests.conformance.test_session_routes:test_capabilities_posted_appear_in_the_callers_session",
        "tests.conformance.test_session_routes:test_the_declaration_is_echoed_and_the_flag_is_the_servers_own",
    ),
    10: (
        "tests.unit.test_authenticate:test_after_the_threshold_even_the_right_password_is_refused",
        "tests.unit.test_authenticate:test_one_success_resets_the_counter",
        "tests.unit.test_authenticate:test_the_counter_survives_the_refusal_that_incremented_it",
    ),
    11: (
        "tests.security.test_no_password_in_logs:test_a_successful_authentication_logs_no_password",
        "tests.security.test_no_password_in_logs:test_a_wrong_password_is_not_logged_either",
        "tests.security.test_no_password_in_logs:test_a_refusal_does_not_echo_the_attempt_into_its_body",
        "tests.security.test_no_password_in_logs:test_the_password_does_not_reach_a_log_through_the_route",
    ),
}

#: Feature 003. It has no endpoints, so nothing here is asserted at the HTTP boundary; the levels
#: are the naming corpus (pure, no filesystem), the resolver (pure, fixture paths), a scan into a
#: real database, and the migration. AC-4 to AC-9 are the naming half and each has corpus rows,
#: which `test_the_corpus` runs - the corpus itself asserts that every one of those criteria is
#: named in some row's reason, so the row and the map cannot drift apart silently.
FEATURE_003: dict[int, tuple[str, ...]] = {
    1: (
        "tests.library.test_scan:test_a_library_scans_to_items",
        "tests.library.test_walker:test_every_media_entry_is_a_candidate",
        "tests.library.test_walker:test_nothing_declared_ignored_is_a_candidate",
        "tests.library.test_resolver:test_every_item_hangs_from_something_that_is_there",
        "tests.library.test_resolver:test_every_parent_is_the_type_the_hierarchy_says",
        "tests.library.test_scan:test_the_rows_reach_the_database",
    ),
    2: (
        "tests.library.test_scan:test_scanning_twice_changes_nothing",
        "tests.library.test_resolver:test_resolving_twice_gives_the_same_items",
        "tests.library.test_change_detection:test_a_second_scan_examines_nothing",
    ),
    3: (
        "tests.library.test_scan:test_scanning_into_an_empty_database_gives_the_same_identifiers",
        "tests.library.test_identity:test_the_whole_derivation_is_deterministic_across_processes",
    ),
    4: (
        "tests.library.test_naming_corpus:test_the_corpus",
        "tests.library.test_naming_movies:test_a_two_part_film_is_one_item_with_two_sources",
        "tests.library.test_resolver:test_a_two_part_film_is_one_item_with_two_sources",
        "tests.unit.test_domain_items:test_a_two_part_film_is_one_item_with_two_sources",
        "tests.unit.test_migration_0002:test_one_film_holds_two_sources_in_order",
    ),
    5: (
        "tests.library.test_naming_corpus:test_the_corpus",
        "tests.library.test_naming_series:test_a_multi_episode_file_is_one_item_spanning_both_numbers",
        "tests.library.test_resolver:test_a_multi_episode_file_is_one_episode",
        "tests.unit.test_migration_0002:test_one_episode_spans_two_numbers",
    ),
    6: (
        "tests.library.test_naming_corpus:test_the_corpus",
        "tests.library.test_naming_series:test_specials_is_season_zero",
        "tests.library.test_naming_series:test_an_episode_in_specials_is_in_season_zero",
        "tests.library.test_resolver:test_specials_becomes_season_zero",
        "tests.library.test_walker:test_specials_is_not_an_extras_folder",
    ),
    7: (
        "tests.library.test_naming_corpus:test_the_corpus",
        "tests.library.test_naming_series:test_a_series_named_with_digits_keeps_its_title",
        "tests.library.test_naming_series:test_the_title_digits_are_not_read_as_numbers_in_the_dominant_convention",
        "tests.library.test_resolver:test_a_series_named_with_digits_keeps_its_title",
    ),
    8: (
        "tests.library.test_naming_corpus:test_the_corpus",
        "tests.library.test_naming_music:test_two_discs_are_one_album_with_two_disc_numbers",
        "tests.library.test_naming_music:test_the_two_discs_derive_one_album_identity",
        "tests.library.test_resolver:test_a_two_disc_album_is_one_album",
    ),
    9: (
        "tests.library.test_naming_corpus:test_the_corpus",
        "tests.library.test_naming_music:test_a_compilation_is_one_album_however_many_artists_it_has",
        "tests.library.test_resolver:test_a_compilation_is_one_album",
    ),
    10: (
        "tests.library.test_root_move:test_moving_a_root_changes_no_identifier",
        "tests.library.test_root_move:test_the_move_is_invisible_to_the_scan",
        "tests.library.test_root_move:test_no_user_data_is_orphaned_by_the_move",
        "tests.library.test_root_move:test_moving_one_root_of_two_changes_no_identifier",
        "tests.library.test_identity:test_the_identifier_does_not_depend_on_where_the_library_is_mounted",
    ),
    11: (
        "tests.library.test_removal:test_a_deleted_file_disappears_from_queries_and_its_user_data_survives",
        "tests.library.test_removal:test_restoring_the_file_revives_the_item_with_the_same_identifier",
        "tests.unit.test_migration_0002:test_the_same_path_scanned_again_finds_its_user_data",
        "tests.unit.test_migration_0002:test_item_user_data_has_no_foreign_key_to_items",
    ),
    12: (
        "tests.library.test_scan_guards:test_an_unreadable_root_removes_nothing",
        "tests.library.test_scan_guards:test_a_root_that_is_not_there_removes_nothing",
        "tests.library.test_scan_guards:test_a_root_that_is_a_file_removes_nothing",
        "tests.library.test_scan_guards:test_without_guard_one_an_unreadable_root_looks_like_an_empty_one",
    ),
    13: (
        "tests.unit.test_sorting:test_the_measured_cases",
        "tests.unit.test_sorting:test_the_double_space_survives",
        "tests.unit.test_sorting:test_the_trailing_space_survives",
        "tests.library.test_scan:test_a_scanned_film_carries_the_base_sort_name",
        "tests.library.test_scan:test_a_scanned_episode_and_season_carry_the_override_sort_names",
        "tests.library.test_scan:test_a_scanned_track_keeps_its_raw_name_in_its_sort_name",
    ),
}

#: Feature directory -> its map. Adding 003 was one entry here and one dictionary above, which is
#: the whole reason this file changed shape at 002 T18 rather than being copied.
FEATURES: dict[str, dict[int, tuple[str, ...]]] = {
    "001-server-identity-and-discovery": FEATURE_001,
    "002-authentication-users-and-sessions": FEATURE_002,
    "003-library-configuration-and-scanning": FEATURE_003,
}


def specified_criteria(feature: str) -> list[int]:
    """The numbers of the criteria in spec section 5, read from the specification itself."""
    body = (SPECS / feature / "spec.md").read_text(encoding="utf-8")
    section = body.split("## 5. Acceptance criteria", 1)[1].split("\n## ", 1)[0]
    return [int(number) for number in re.findall(r"^(\d+)\. ", section, flags=re.MULTILINE)]


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_the_specification_still_has_the_criteria_this_map_expects(feature: str) -> None:
    """Numbered from one, with none missing in the middle."""
    criteria = specified_criteria(feature)
    mapped = FEATURES[feature]
    assert criteria == list(range(1, len(criteria) + 1)), (
        f"{feature} section 5 numbers its criteria {criteria}, which is not a list from 1"
    )
    assert set(criteria) == set(mapped), (
        f"{feature} has {sorted(set(criteria) - set(mapped))} that this map does not, and this map "
        f"has {sorted(set(mapped) - set(criteria))} that it does not. A criterion without a test "
        f"cannot be ticked off in the definition of done."
    )


CRITERIA = [
    (feature, criterion) for feature, mapped in sorted(FEATURES.items()) for criterion in mapped
]


@pytest.mark.parametrize(
    "feature,criterion",
    CRITERIA,
    ids=[f"{feature[:3]}-AC{criterion}" for feature, criterion in CRITERIA],
)
def test_every_criterion_names_tests_that_exist(feature: str, criterion: int) -> None:
    names = FEATURES[feature][criterion]
    assert names, f"{feature} AC-{criterion} names no test"
    for name in names:
        module_name, _, function = name.partition(":")
        module = importlib.import_module(module_name)
        assert hasattr(module, function), (
            f"{feature} AC-{criterion} names {name}, which does not exist. If it was renamed, "
            f"rename it here too; if it was deleted, the criterion it covered is now unasserted."
        )


def test_the_map_rejects_a_name_that_does_not_exist() -> None:
    """The first of the three ways this file fails, asserted rather than described.

    A renamed test is the common one: the suite still passes, and the criterion it covered is
    quietly unasserted. This is what catches that.
    """
    module = importlib.import_module("tests.conformance.test_user_routes")
    assert hasattr(module, "test_an_unknown_username_is_401"), "the fixture name went stale"
    assert not hasattr(module, "test_an_unknown_username_is_401_renamed_by_somebody")


def test_every_implemented_feature_has_a_map() -> None:
    """A feature marked Implemented whose criteria nothing maps is the gap this file exists for.

    Read from the status table rather than from a list here, so finishing 003 fails this until its
    map is written - which is the moment somebody is in a position to write it.
    """
    table = (SPECS / "README.md").read_text(encoding="utf-8")
    row = r"\[(\d{3})\]\([^)]+\)[^|]*\|[^|]*\|\s*\*\*Implemented\*\*"
    implemented = set(re.findall(row, table))
    mapped = {feature[:3] for feature in FEATURES}
    assert implemented <= mapped, (
        f"{sorted(implemented - mapped)} is marked Implemented in specs/README.md and has no "
        f"acceptance map. Its definition of done claims every criterion has a passing test, and "
        f"nothing here checks that claim."
    )
