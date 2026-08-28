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

**It was written for one feature and now carries four.** 002 T18 turned one specification path and
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
        "tests.conformance.test_system_routes:test_a_published_url_is_the_local_address_on_the_wire",
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
        "tests.conformance.test_auth_mechanisms:test_the_stub_is_not_asserted_to_demand_a_token",
        # Renamed at 006 T9, when the image stub became the real route and its assertion changed
        # from "every mechanism reaches it" to "no mechanism changes the answer". This map is what
        # noticed: a rename that left the criterion unasserted fails here rather than quietly.
        "tests.conformance.test_auth_mechanisms:test_a_token_never_changes_the_image_routes_answer",
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
#: 004's sixteen. **Nine of them are asserted twice on purpose** - once at engine level, where the
#: rule is proved, and once end to end, where the rule is proved to be the one a scan uses. The
#: gap between those two claims is where a correct merge sitting behind a caller that never asks
#: it lives, and 004's own task list says so out loud for AC-1: T10's zero network requests was
#: vacuous in a world with no remote code, so T14 holds it again with a provider that would have
#: answered.
FEATURE_004: dict[int, tuple[str, ...]] = {
    1: (
        "tests.metadata.test_local_refresh:test_a_film_with_a_full_sidecar_resolves_from_it",
        "tests.metadata.test_remote_refresh:test_a_fully_sidecared_film_makes_zero_network_requests",
        "tests.metadata.test_remote_refresh:test_a_film_with_a_sparse_sidecar_does_ask",
    ),
    2: (
        "tests.metadata.test_nfo:test_a_sparse_sidecar_says_nothing_about_what_it_leaves_empty",
        "tests.metadata.test_local_refresh:test_a_sparse_sidecar_leaves_the_rest_to_the_next_source",
        "tests.metadata.test_merge:test_the_first_source_with_a_value_wins_per_field",
    ),
    3: (
        "tests.metadata.test_nfo:test_provider_ids_come_from_both_spellings",
        "tests.metadata.test_tmdb:test_a_carried_id_makes_zero_search_requests",
        "tests.metadata.test_remote_refresh:test_a_sidecar_id_is_fetched_without_a_search",
    ),
    4: (
        "tests.metadata.test_nfo:test_a_malformed_sidecar_warns_and_yields_nothing",
        "tests.metadata.test_nfo:test_all_three_entity_shapes_land_on_the_same_path",
        "tests.metadata.test_local_refresh:test_a_malformed_sidecar_warns_and_the_item_still_resolves",
    ),
    5: (
        "tests.metadata.test_tags_in_a_scan:test_a_tagged_track_hangs_under_the_album_its_tags_name",
        "tests.metadata.test_local_refresh:test_a_well_tagged_track_takes_its_album_and_artist_from_its_tags",
    ),
    6: (
        "tests.metadata.test_tags:test_a_track_with_three_artists_has_three_artists",
        "tests.metadata.test_tags:test_a_semicolon_inside_one_value_stays_one_artist",
        "tests.metadata.test_local_refresh:test_a_track_with_three_artists_yields_three_artists",
    ),
    7: (
        "tests.metadata.test_artwork:test_the_first_name_of_every_type_wins_when_all_fourteen_are_present",
        "tests.metadata.test_artwork:test_landscape_beats_thumb_which_is_the_opposite_of_the_specs_table",
        "tests.metadata.test_local_refresh:test_local_artwork_becomes_the_right_image_type",
        "tests.metadata.test_remote_refresh:test_local_artwork_wins_without_asking_the_image_host",
    ),
    8: (
        "tests.metadata.test_remote_refresh:test_with_every_provider_down_the_scan_completes_and_nothing_is_blanked",
        "tests.metadata.test_remote_refresh:test_the_next_scan_retries_a_pending_item_whose_files_did_not_change",
        "tests.metadata.test_remote_door:test_a_transport_error_is_unavailable",
    ),
    9: (
        "tests.metadata.test_remote_refresh:test_without_credentials_the_scan_completes_and_names_what_sat_out",
        "tests.metadata.test_tmdb:test_without_a_key_the_provider_says_why_it_is_disabled",
        "tests.metadata.test_musicbrainz:test_without_a_contact_the_provider_sits_out_with_a_reason",
    ),
    10: (
        "tests.metadata.test_merge:test_a_locked_field_survives_replace",
        "tests.metadata.test_local_refresh:test_a_locked_field_survives_a_replace_refresh",
        "tests.metadata.test_remote_refresh:test_a_locked_field_survives_a_replace_refresh_against_a_provider",
    ),
    11: (
        "tests.metadata.test_merge:test_a_default_refresh_never_overwrites_a_non_empty_field",
        "tests.metadata.test_merge:test_the_matrix",
        "tests.metadata.test_local_refresh:test_a_default_refresh_does_not_overwrite_what_a_previous_one_resolved",
    ),
    12: (
        "tests.metadata.test_tmdb:test_two_survivors_are_ambiguous_and_therefore_unidentified",
        "tests.metadata.test_musicbrainz:test_two_survivors_leave_the_album_unidentified",
        "tests.metadata.test_remote_refresh:test_an_ambiguous_match_leaves_the_item_unidentified_and_says_so",
    ),
    13: (
        "tests.metadata.test_remote_refresh:test_rescanning_an_unchanged_library_makes_zero_requests",
        "tests.metadata.test_local_refresh:test_a_rescan_of_an_unchanged_library_refreshes_nothing",
        "tests.metadata.test_remote_door:test_a_cached_request_costs_no_request_and_no_token",
    ),
    14: (
        "tests.library.test_identity:test_two_spellings_of_one_genre_are_one_item",
        "tests.metadata.test_write_path:test_two_spellings_of_one_genre_produce_one_item",
        "tests.metadata.test_local_refresh:test_two_spellings_of_one_genre_become_one_item",
    ),
    15: (
        "tests.metadata.test_local_refresh:test_a_full_scan_and_refresh_leaves_the_library_byte_identical",
        "tests.metadata.test_local_refresh:test_the_same_holds_for_a_music_library",
        "tests.metadata.test_remote_refresh:test_downloads_land_under_the_data_directory_and_the_library_is_untouched",
    ),
    16: (
        # The standing guard, which every test in the suite runs under rather than one asserting
        # it. The counting transports complement it; they do not replace it.
        "tests.metadata.test_remote_door:test_the_suites_network_guard_is_still_watching",
        "tests.metadata.test_remote_door:test_no_module_under_metadata_constructs_a_client_except_this_one",
    ),
}


#: 005's sixteen. Several criteria are named twice - once where the rule is proved at
#: repository or builder level and once where the route is proved to use it - for 004's recorded
#: reason: a correct rule and a rule the caller actually uses are two claims. AC-11 and AC-13
#: map to tests that assert the *measured* wire, which reversed one drafted criterion and
#: restated another; the spec carries both corrections with provenance.
FEATURE_005: dict[int, tuple[str, ...]] = {
    1: (
        "tests.conformance.test_shapes:test_every_005_route_answers_its_declared_shape",
        "tests.unit.test_user_world_routes:test_latest_is_a_bare_array",
    ),
    2: (
        "tests.unit.test_item_dto:test_ac2_user_data_is_on_every_item_with_key_and_item_id",
        "tests.unit.test_items_route:test_ac2_every_list_row_carries_user_data_with_key_and_item_id",
    ),
    3: (
        "tests.unit.test_item_dto:test_ac3_a_gated_field_is_absent_bare_and_present_when_asked",
        "tests.unit.test_items_route:test_ac3_gated_fields_are_absent_bare_and_present_asked_over_http",
    ),
    4: (
        "tests.unit.test_item_ordering:test_paging_reassembles_the_unpaged_list_exactly",
        "tests.unit.test_item_ordering:test_paging_the_whole_world_reassembles_it_too",
        "tests.unit.test_items_route:test_ac4_paging_over_http_visits_every_movie_exactly_once",
    ),
    5: (
        "tests.unit.test_item_by_name:test_the_count_is_true_with_and_without_a_limit",
        "tests.unit.test_by_name_routes:test_ac5_the_count_is_true_with_and_without_limit",
    ),
    6: ("tests.unit.test_item_ordering:test_the_awkward_names_sort_the_way_003_derived_them",),
    7: (
        "tests.unit.test_item_ordering:test_random_returns_the_whole_set_with_no_duplicates",
        "tests.unit.test_item_ordering:test_a_random_page_has_no_duplicates_either",
    ),
    8: (
        "tests.unit.test_items_route:test_ac8_unknown_and_invisible_ids_answer_byte_identical_404s",
    ),
    9: (
        "tests.unit.test_item_queries:test_the_user_permitted_nothing_sees_nothing",
        "tests.unit.test_user_world_routes:test_ac9_a_user_permitted_nothing_gets_the_empty_envelope",
    ),
    10: (
        "tests.unit.test_played_state_routes:test_ac10_one_row_per_series_and_each_is_the_right_episode",
        "tests.unit.test_played_state_routes:test_the_chain_follows_the_highest_played_episode_not_the_latest_click",
    ),
    11: ("tests.unit.test_tv_routes:test_ac11_season_zero_sorts_first_as_measured",),
    12: (
        "tests.unit.test_deterministic_pair_routes:test_ac12_similar_answers_identically_on_repeated_calls",
        "tests.unit.test_deterministic_pair_routes:test_the_mix_is_the_keyed_shuffle_of_the_shared_genre_pool",
        "tests.unit.test_deterministic_pair_routes:test_two_seeds_shuffle_differently_but_each_stably",
    ),
    13: (
        "tests.unit.test_item_by_name:test_any_credit_strictly_contains_the_album_credit",
        "tests.unit.test_item_filters:test_artist_ids_is_the_superset_and_album_artist_ids_the_subset",
        "tests.unit.test_by_name_routes:test_ac13_the_two_artist_routes_coincide_for_the_recorded_reason",
    ),
    14: (
        "tests.unit.test_filters_and_search_routes:test_ac14_the_hint_shape_is_not_the_item_shape",
        "tests.unit.test_filters_and_search_routes:test_matching_is_against_the_name_not_the_sort_name",
    ),
    15: (
        "tests.unit.test_items_route:test_ac15_a_tier_3_parameter_is_ignored_answered_and_recorded",
    ),
    16: (
        "tests.unit.test_item_filters:test_a_predicate_selects_something_and_less_than_everything",
        "tests.unit.test_items_route:test_every_parameter_changes_the_answer_and_survives_mangled_casing",
    ),
}


#: Feature 006. Nearly every criterion is asserted **twice**, and the pairing is the point rather
#: than belt and braces: once against the pure module or the service, where the answer is a value,
#: and once on the wire, where the plumbing has to deliver it. A route that dropped a parameter
#: would pass the first and fail the second; a decision that was wrong would fail both.
#:
#: The three that are asserted once are the ones with only one place to be: AC-3 and AC-9 are
#: statements about headers, and AC-14 is about a map 005 emits.
FEATURE_006: dict[int, tuple[str, ...]] = {
    1: (
        "tests.conformance.test_image_discovery:test_ac1_a_poster_is_advertised_and_its_absence_is_an_empty_map",
    ),
    2: (
        "tests.conformance.test_image_identity:test_ac2_a_touch_that_changes_no_bytes_changes_no_tag",
        "tests.conformance.test_image_identity:test_ac2_changing_the_bytes_changes_the_tag",
        "tests.conformance.test_image_identity:test_the_tag_is_the_content_hash_and_not_something_weaker",
        # The limitation AC-2 now names: a default scan does not read artwork of an unchanged item.
        "tests.conformance.test_image_identity:test_a_default_rescan_does_not_notice_an_artwork_only_change",
    ),
    3: (
        "tests.conformance.test_image_routes:test_ac3_the_bytes_come_back_with_a_real_type_and_an_exact_length",
    ),
    4: (
        "tests.unit.test_image_transform:test_ac4_a_resized_poster_decodes_to_the_size_that_was_decided",
        "tests.unit.test_image_service:test_ac4_a_resized_poster_decodes_to_the_expected_size",
        "tests.conformance.test_image_routes:test_the_resize_matrix_delivers_what_it_decided",
    ),
    5: (
        "tests.unit.test_image_service:test_ac5_never_upscaling_holds_end_to_end",
        "tests.conformance.test_image_routes:test_ac5_a_box_past_the_source_is_the_source_file_byte_for_byte",
    ),
    6: (
        "tests.unit.test_image_transform:test_the_delivered_size_is_the_measured_one",
        "tests.unit.test_image_service:test_ac6_a_fill_box_covers_and_keeps_the_overflow",
        "tests.conformance.test_image_routes:test_ac6_a_fill_box_the_source_cannot_cover_returns_it_unchanged",
    ),
    7: (
        "tests.unit.test_image_transform:test_ac7_alpha_survives_every_implicit_path",
        "tests.unit.test_image_transform:test_ac7_an_explicit_jpg_flattens_the_alpha_onto_white",
        "tests.unit.test_image_service:test_ac7_a_resized_logo_keeps_its_alpha_and_an_explicit_jpg_takes_it",
        "tests.conformance.test_image_routes:test_ac7_a_resized_logo_keeps_its_alpha",
        "tests.conformance.test_image_routes:test_ac7_an_explicit_jpg_takes_the_alpha_and_that_is_measured",
    ),
    8: (
        "tests.unit.test_image_service:test_ac8_a_hit_never_recomputes_even_when_the_file_underneath_has_changed",
        "tests.conformance.test_image_identity:test_ac8_the_same_request_twice_is_byte_identical",
        "tests.conformance.test_image_identity:test_ac8_a_hit_never_recomputes_even_after_the_file_changes",
        "tests.conformance.test_image_identity:test_a_rescan_after_that_overwrite_serves_the_new_bytes",
    ),
    9: (
        "tests.conformance.test_image_routes:test_ac9_if_modified_since_at_the_sent_date_is_an_empty_304",
        "tests.conformance.test_image_routes:test_the_304_carries_the_type_the_200_would_have",
    ),
    10: (
        "tests.conformance.test_image_routes:test_ac10_a_stale_tag_answers_200_with_the_current_image",
    ),
    11: (
        "tests.conformance.test_image_routes:test_ac11_an_unknown_item_is_the_problem_details_404",
        "tests.conformance.test_image_routes:test_ac11_an_item_that_lacks_the_type_is_the_message_shape",
        "tests.conformance.test_image_routes:test_ac11_an_index_past_the_last_backdrop_names_the_type_not_the_index",
        "tests.conformance.test_image_routes:test_ac11_a_type_outside_the_vocabulary_is_the_validation_400",
        "tests.unit.test_image_service:test_the_two_refusals_are_the_only_thing_raised",
    ),
    12: (
        "tests.conformance.test_image_routes:test_ac12_every_mechanism_is_accepted_and_none_changes_the_answer",
        "tests.conformance.test_auth_mechanisms:test_a_token_never_changes_the_image_routes_answer",
    ),
    13: (
        "tests.unit.test_image_cache:test_deleting_the_tree_between_operations_loses_nothing_but_time",
        "tests.unit.test_image_service:test_ac13_deleting_the_cache_between_requests_changes_no_body",
        "tests.conformance.test_image_identity:test_ac13_deleting_the_whole_cache_changes_no_response_body",
    ),
    14: (
        "tests.conformance.test_image_discovery:test_ac14_an_episode_with_its_own_artwork_still_inherits_its_series",
        "tests.conformance.test_image_discovery:test_the_inherited_backdrop_id_and_tags_travel_together_on_every_row",
    ),
    15: (
        "tests.conformance.test_image_routes:test_ac15_a_resized_response_negotiates_webp_under_vary_accept",
        "tests.conformance.test_image_routes:test_ac15_an_explicit_format_beats_the_offer",
        "tests.conformance.test_image_routes:test_ac15_a_verbatim_request_negotiates_nothing",
        "tests.unit.test_image_transform:test_the_resolved_format_is_the_measured_one",
    ),
}


FEATURE_007: dict[int, tuple[str, ...]] = {
    1: (
        "tests.conformance.test_user_data_identity:test_ac1_every_row_carries_user_data_with_key_and_item_id",
        "tests.conformance.test_user_data_identity:test_ac1_the_single_item_route_carries_them_too",
    ),
    2: (
        "tests.unit.test_favourite_routes:test_ac2_marking_twice_answers_200_twice_and_leaves_one_favourite",
        "tests.unit.test_favourite_routes:test_ac2_unmarking_twice_answers_200_twice_and_leaves_none",
    ),
    3: (
        "tests.unit.test_domain_playstate:test_ac3_a_bare_mark_is_max_count_one_and_marking_twice_does_not_move_it",
        "tests.unit.test_domain_playstate:test_ac3_only_the_dated_form_increments_and_its_date_wins",
        "tests.unit.test_played_mark_routes:test_ac3_marking_played_resets_the_position_and_sets_the_count_to_one",
        "tests.unit.test_played_mark_routes:test_ac3_marking_twice_leaves_the_count_at_one",
        "tests.unit.test_played_mark_routes:test_ac3_only_the_dated_form_increments_and_its_date_wins",
    ),
    4: (
        "tests.unit.test_domain_playstate:test_ac4_unmarking_clears_played_the_count_the_position_and_the_date",
        "tests.unit.test_played_mark_routes:test_ac4_unmarking_clears_all_four_fields",
    ),
    5: (
        "tests.unit.test_played_mark_routes:test_ac5_marking_a_season_writes_every_episode_and_not_the_season",
        "tests.unit.test_played_mark_routes:test_ac5_the_response_is_the_rollup_the_writes_just_created",
    ),
    6: (
        "tests.conformance.test_user_data_aggregation:test_ac6_the_count_follows_a_mark_an_addition_and_a_removal",
        "tests.conformance.test_user_data_aggregation:test_removing_the_only_unplayed_episode_makes_the_season_played",
    ),
    7: (
        "tests.conformance.test_user_data_identity:test_ac7_every_write_is_per_user",
        "tests.conformance.test_user_data_identity:test_ac7_a_second_users_writes_do_not_reach_the_first",
        "tests.conformance.test_user_data_identity:test_ac7_a_container_rollup_is_per_user_too",
    ),
    8: (
        "tests.unit.test_playback_report_routes:test_ac8_every_report_answers_204_with_an_empty_body",
    ),
    9: (
        "tests.unit.test_playback_report_routes:test_ac9_a_progress_without_a_media_source_or_a_start_still_lands",
    ),
    10: (
        "tests.unit.test_domain_playstate:test_ac10_a_report_older_than_the_stored_position_rewinds_it",
        "tests.unit.test_playback_report_routes:test_ac10_a_later_report_carrying_an_older_position_rewinds_it",
    ),
    11: (
        "tests.unit.test_playback_report_routes:test_ac11_a_report_for_an_unknown_item_is_204_and_writes_nothing",
    ),
    12: (
        "tests.unit.test_domain_playstate:test_ac12_every_branch_of_the_rule",
        "tests.unit.test_playback_report_routes:test_ac12_every_branch_of_the_rule_reaches_the_wire",
    ),
    13: (
        "tests.unit.test_domain_playstate:test_ac13_the_first_tick_reaching_the_floor_keeps_its_position",
        "tests.unit.test_domain_playstate:test_ac13_the_last_tick_not_past_the_ceiling_keeps_its_position",
    ),
    14: (
        "tests.unit.test_playback_report_routes:test_ac14_a_failed_stop_records_nothing_and_the_start_keeps_its_effects",
    ),
    15: (
        "tests.unit.test_session_reaping:test_ac15_a_silent_session_is_reaped_and_keeps_the_viewers_place",
        "tests.unit.test_now_playing_registry:test_the_reaped_position_carries_the_silence",
        "tests.unit.test_session_reaping:test_the_reap_and_an_explicit_stop_agree",
    ),
    # 003's own AC-11, seen from the other side: it plants a favourite *and* a resume position,
    # unlinks the file, rescans, restores it and rescans again. The gate found this rather than
    # writing a second one (see 007's tasks, "What the gate changed").
    16: (
        "tests.library.test_removal:test_a_deleted_file_disappears_from_queries_and_its_user_data_survives",
        "tests.library.test_removal:test_restoring_the_file_revives_the_item_with_the_same_identifier",
    ),
    17: (
        "tests.unit.test_domain_playstate:test_ac17_a_start_counts_the_play_and_un_marks_a_played_item",
        "tests.unit.test_playback_report_routes:test_ac17_a_start_counts_the_play_sets_the_date_and_clears_played",
    ),
    18: (
        "tests.unit.test_domain_playstate:test_ac18_a_stop_with_a_position_does_not_count_and_one_without_counts_again",
        "tests.unit.test_playback_report_routes:test_ac18_a_stop_with_a_position_does_not_count_and_one_without_counts_again",
    ),
    19: (
        "tests.unit.test_domain_playstate:test_ac19_a_report_past_the_ceiling_marks_played_and_clears_the_position",
        "tests.unit.test_playback_report_routes:test_ac19_a_progress_past_the_ceiling_marks_played_mid_playback",
    ),
    20: (
        "tests.conformance.test_user_data_aggregation:test_ac20_a_bare_container_row_carries_no_percentage",
        "tests.conformance.test_user_data_aggregation:test_ac20_asking_for_recursive_item_count_produces_the_percentage",
    ),
    21: (
        "tests.unit.test_favourite_routes:test_ac21_an_unknown_item_is_the_problem_details_404",
        "tests.unit.test_favourite_routes:test_ac21_a_path_that_is_not_a_guid_is_the_validation_400",
        "tests.unit.test_favourite_routes:test_ac21_no_token_is_the_empty_401",
        "tests.unit.test_played_mark_routes:test_ac21_an_unparseable_date_played_refuses_and_stores_nothing",
        "tests.unit.test_playback_report_routes:test_ac21_a_stop_with_a_negative_position_is_the_text_plain_400",
        "tests.unit.test_playback_report_routes:test_ac21_a_body_that_is_not_json_is_the_validation_400",
        "tests.unit.test_playback_report_routes:test_ac21_an_item_id_that_is_not_a_guid_is_the_validation_400",
    ),
    22: (
        "tests.conformance.test_session_routes:test_ac22_now_playing_sits_between_device_name_and_device_id",
        "tests.conformance.test_session_routes:test_ac22_the_now_playing_item_carries_no_user_data",
        "tests.conformance.test_session_routes:test_ac22_play_state_mirrors_exactly_the_last_report",
    ),
}


FEATURES: dict[str, dict[int, tuple[str, ...]]] = {
    "001-server-identity-and-discovery": FEATURE_001,
    "002-authentication-users-and-sessions": FEATURE_002,
    "003-library-configuration-and-scanning": FEATURE_003,
    "004-metadata-resolution": FEATURE_004,
    "005-item-query-api": FEATURE_005,
    "006-images": FEATURE_006,
    "007-user-data-and-playstate": FEATURE_007,
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
