# SPDX-License-Identifier: GPL-3.0-or-later
"""Every acceptance criterion of every implemented feature, mapped to the test that asserts it.

Every feature's definition of done says some version of *"every acceptance criterion has a passing
test, by name"* - fourteen of them for 001, fourteen for 002, fifteen for 003. That is a claim
somebody has to check, and checking it by reading two documents side by side is a thing nobody does
twice. This file is the map, and it fails four ways:

* an acceptance criterion in the specification with no test named here — the box cannot be ticked;
* a test named here that no longer exists — a rename or a deletion that silently orphaned a
  criterion;
* a count that no longer matches the specification — a criterion added or removed;
* a definition of done whose count no longer matches this map — the last one added, on 2026-09-05,
  because the counts in the sentence above were themselves three of the stale ones, and ten of the
  twelve definitions of done were wrong before an audit's corrective task read them together.

It asserts that the tests **exist**, not that they pass; the suite they are in does that. What it
protects is the *mapping*, which is the part that rots quietly.

**It was written for one feature and now carries twelve.** 002 T18 turned one specification path and
one map into a table of them, betting that adding 003 would then be one entry and one dictionary
rather than a third copy of this file. It was: nothing below changed shape for 003, and the diff
that added it is a dictionary and a line in `FEATURES`. That is the whole of what the restructure
was for, and it is recorded here because a restructure nobody checks the payoff of is a refactor
that might have been a waste. **011 was the ninth and the first that was not the next number**: 009
and 010 were specified and unimplemented when its map landed, and
`test_every_implemented_feature_has_a_map` reads the status table rather than a list here, so the
gap cost nothing — and both closed it themselves, on 2026-09-01 and 2026-09-02.

**012 is the twelfth and the last, and it is the one feature whose map is the only thing carrying
the claim.** Every closing task before it also added its number to `IMPLEMENTED_FEATURES`; 012 owns
no row of `surface.yaml`, so there was nothing for it to add and nothing else that would have
noticed a criterion left unasserted.

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
#:
#: AC-14 is audit 2026-09-04's M1: section 3.2's value table had two tests and a golden and no
#: criterion, so nothing here could name them. It is the one criterion in this feature whose last
#: clause is a *golden* rather than a field - which is what makes it a claim about the whole body.
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
    12: (
        "tests.unit.test_lifecycle:test_a_request_while_starting_is_refused",
        "tests.unit.test_lifecycle:test_the_gate_is_server_wide",
        "tests.unit.test_lifecycle:test_retry_after_is_full_seconds",
        "tests.unit.test_lifecycle:test_the_message_header_says_why",
        "tests.unit.test_lifecycle:test_the_body_is_html_not_json",
    ),
    13: (
        "tests.unit.test_net_address:test_the_request_host_is_used_when_configured",
        "tests.unit.test_net_address:test_the_default_port_is_omitted",
    ),
    14: (
        # The two values a client acts on - a capability claimed and a property absent - and then
        # the whole body, which is where the other eighteen live. AC-5 asserts the two statuses and
        # the seven *shared* fields; every value of section 3.2's table is one of the twenty that
        # are not shared, so none of these three was reachable from it.
        "tests.conformance.test_system_routes:test_system_info_claims_no_capability_it_lacks",
        "tests.conformance.test_system_routes:test_system_info_omits_the_null_property",
        "tests.conformance.test_golden:test_system_info",
    ),
    15: (
        # Audit 2026-09-04's H1, closed by accepting the divergence (behaviours 4.5) rather than
        # by building the gate. The criterion asserts *Atrium's* answer, which is what makes it
        # writable at all: C1 was right that a criterion for section 3.2's refusal row could only
        # assert a refusal no route performs, and that is a claim about the row, not about the
        # decision the row was waiting for.
        #
        # Four tests for three clauses. The two wire tests are the divergence and its cost - the
        # account is served, and its own policy goes on announcing the restriction - on both
        # routes the probe measured, because the gate is not this route's. The two unit tests are
        # the structural half: no honoured flag to read and no setting to read it against, so an
        # exception that lives only in a document cannot quietly become one nobody chose.
        "tests.conformance.test_system_routes:test_the_remote_access_flag_refuses_nobody_on_either_route",
        "tests.conformance.test_system_routes:test_the_address_a_request_arrives_from_gates_nothing",
        "tests.unit.test_policy:test_the_remote_access_flag_is_carried_and_never_read",
        "tests.unit.test_net_address:test_there_is_no_local_network_to_gate_on",
    ),
}


#: Feature 002. Three criteria are asserted at the HTTP boundary rather than against the function
#: behind the route, because Principle VIII does not accept them anywhere else.
#:
#: AC-14 is audit 2026-09-04's M2, and it is the opposite case on purpose: the grammar is a
#: property of the parser every route calls, and the boundary tests AC-3 names prove the routes
#: call it. Section 6 said the grammar table was proven under AC-3 - it was proven by nothing, and
#: none of AC-3's six tests reads a header's grammar at all.
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
        "tests.conformance.test_auth_mechanisms:test_every_mechanism_authenticates_the_api_route",
        "tests.conformance.test_auth_mechanisms:test_the_precedence_chain_resolves_as_it_was_measured",
        "tests.conformance.test_auth_mechanisms:test_neither_optional_class_demands_a_token",
        # Renamed twice, and for the same reason each time: at 006 T9 the image stub became a real
        # route, and at 008 T6 the delivery stub did - so "every mechanism reaches it" stopped
        # being the surviving claim and "no mechanism changes the answer" replaced it. This map is
        # what noticed both: a rename that left the criterion unasserted fails here rather than
        # quietly. The delivery half of AC-3's precedence pairs is gone with the stub, because a
        # route that reads no token cannot show which of two tokens wins.
        "tests.conformance.test_auth_mechanisms:test_a_token_never_changes_a_token_optional_routes_answer",
        "tests.conformance.test_auth_mechanisms:test_the_query_forms_are_the_only_ones_a_player_can_use",
        "tests.conformance.test_auth_mechanisms:test_a_stale_header_beside_a_fresh_url_cannot_break_delivery",
    ),
    4: (
        "tests.unit.test_require_user:test_no_token_is_the_empty_401_that_001_measured",
        "tests.unit.test_require_user:test_a_token_whose_account_was_disabled_is_403",
        # The third name here was `/Users/{userId}`'s refusal until 2026-09-01, when that route
        # was measured and turned out to refuse nobody. The criterion's second half - a valid
        # token lacking permission is `403` - is proven on the route where the reference really
        # does refuse: `/Items?userId=<somebody else>`, in the measured 25 bytes.
        "tests.unit.test_items_route:test_user_id_of_somebody_else_is_the_controller_403",
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
    # Rewritten on 2026-09-01, when the criterion it maps stopped asserting a refusal. Every
    # cell of the route is named here rather than the three it had, because the measurement that
    # overturned it measured a matrix and one pair of it is not the route
    # `[probe: tools/probe_user_read.py, Jellyfin 10.11.11, 2026-09-01]`.
    7: (
        "tests.conformance.test_user_routes:test_a_user_may_always_read_themselves",
        "tests.conformance.test_user_routes:test_an_ordinary_user_reads_another_whole",
        "tests.conformance.test_user_routes:test_a_non_administrator_reads_an_administrator_whole",
        "tests.conformance.test_user_routes:test_an_administrator_reading_another_is_200",
        "tests.conformance.test_user_routes:test_an_identifier_nobody_has_is_the_fourth_shape",
        "tests.conformance.test_user_routes:test_an_administrator_gets_the_same_body_for_an_identifier_nobody_has",
        "tests.conformance.test_user_routes:test_a_malformed_identifier_is_the_validation_400",
        "tests.conformance.test_user_routes:test_reading_a_user_without_a_token_is_the_empty_401",
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
    12: (
        "tests.conformance.test_golden_users:test_current_user",
        "tests.conformance.test_golden_users:test_current_user_under_the_camel_case_profile",
    ),
    13: (
        "tests.unit.test_session_registry:test_the_least_recently_used_session_is_the_one_evicted",
        "tests.unit.test_session_registry:test_an_evicted_session_loses_its_token_too",
        "tests.unit.test_session_registry:test_a_flush_writes_both_the_session_and_the_token",
        "tests.conformance.test_session_routes:test_posting_replaces_rather_than_merges",
        "tests.conformance.test_golden_users:test_post_capabilities_answers_with_no_body",
    ),
    14: (
        # The measured table itself, fifteen rows, and the strictness spelled out again at the
        # parser beneath it - `Token = "x"` yields no components at all, which is the difference
        # between refusing a header and reading nothing out of one.
        "tests.unit.test_compat_auth:test_the_grammar_matches_the_reference_row_for_row",
        "tests.unit.test_compat_auth:test_being_kinder_than_the_reference_would_be_the_delta",
        "tests.unit.test_compat_auth:test_a_header_with_no_scheme_reads_as_nothing",
        "tests.unit.test_compat_auth:test_the_four_components_are_read",
        "tests.unit.test_compat_auth:test_an_unknown_component_is_ignored_rather_than_rejected",
        "tests.unit.test_compat_auth:test_the_client_header_is_read_from_either_name",
        # The `DeviceId` half, which is a rule about *where* rather than about spelling: fatal on
        # one route and on no other. Both directions, because a parser that raised would have
        # refused requests the reference serves.
        "tests.unit.test_compat_auth:test_a_missing_device_id_is_not_fatal_in_general",
        "tests.unit.test_compat_auth:test_authentication_requires_a_device_id_and_refuses_without_one",
        "tests.unit.test_compat_auth:test_a_good_header_passes_the_authentication_rule",
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
    14: (
        "tests.library.test_change_detection:test_only_the_modified_file_is_examined",
        "tests.library.test_change_detection:test_a_modified_file_keeps_its_identity_and_its_user_data",
        "tests.library.test_change_detection:test_a_new_file_on_a_rescan_is_added",
        "tests.library.test_change_detection:test_a_rename_is_a_delete_plus_an_add",
    ),
    15: (
        "tests.unit.test_sorting:test_an_explicit_sort_title_is_lowercased_and_padded_but_keeps_its_articles",
        "tests.unit.test_sorting:test_an_explicit_sort_title_replaces_the_override_too",
    ),
    16: (
        "tests.library.test_creation_dates:test_a_file_backed_item_carries_its_files_modification_time",
        "tests.library.test_creation_dates:test_a_container_carries_the_scans_moment_and_not_its_directorys",
        "tests.library.test_creation_dates:test_a_two_part_item_takes_the_time_of_the_part_its_path_names",
        "tests.library.test_creation_dates:test_a_modification_time_that_moves_moves_the_creation_date",
        "tests.library.test_creation_dates:test_a_date_left_by_an_older_scan_is_corrected_without_a_metadata_refresh",
    ),
    17: (
        # The two that build one declaration twice, which no other test in this suite does: every
        # fixture world pins its library identifiers, so nothing here could ever have seen this.
        "tests.library.test_identity_across_builds:test_two_databases_from_one_declaration_hold_the_same_identifiers",
        "tests.library.test_identity_across_builds:test_the_window_over_a_tied_ordering_holds_still_across_two_builds",
        # And the declaration-level half: one declaration is one library, and editing one moves
        # nothing - which is the promise the minted identifier used to keep on its own.
        "tests.library.test_config:test_declaring_one_library_twice_is_refused",
        "tests.library.test_config:test_the_roots_are_a_set_rather_than_a_sequence",
        "tests.library.test_config:test_the_case_flag_is_part_of_the_declaration",
        "tests.library.test_config:test_renaming_a_library_keeps_every_identifier",
        "tests.library.test_config:test_moving_a_root_keeps_every_identifier",
    ),
}

#: Feature directory -> its map. Adding 003 was one entry here and one dictionary above, which is
#: the whole reason this file changed shape at 002 T18 rather than being copied.
#: 004's nineteen. **Nine of them are asserted twice on purpose** - once at engine level, where the
#: rule is proved, and once end to end, where the rule is proved to be the one a scan uses. The
#: gap between those two claims is where a correct merge sitting behind a caller that never asks
#: it lives, and 004's own task list says so out loud for AC-1: T10's zero network requests was
#: vacuous in a world with no remote code, so T14 holds it again with a provider that would have
#: answered.
#:
#: AC-19 is the exception to the pairing and says why: **where a container's metadata lives has no
#: engine level**. `metadata/nfo.py` and `metadata/artwork.py` are handed a directory and never
#: choose one, so the only place the choice is observable is a scan - which is why it was wrong for
#: two of the shapes this project's own fixture already had (2026-09-03).
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
    17: ("tests.conformance.test_golden:test_cultures",),
    18: (
        "tests.metadata.test_nfo:test_the_cast_keeps_its_billing_order_and_its_roles",
        "tests.metadata.test_write_path:test_a_cast_keeps_its_order_and_its_roles",
    ),
    19: (
        "tests.metadata.test_local_refresh:test_a_two_disc_album_reads_the_sidecar_beside_its_discs",
        "tests.metadata.test_local_refresh:test_an_artist_whose_tracks_have_no_album_directory_reads_their_own_sidecar",
        "tests.metadata.test_local_refresh:test_a_season_missing_one_episode_keeps_its_own_directory",
        "tests.metadata.test_local_refresh:test_a_container_never_borrows_a_directory_above_the_library_root",
    ),
    # Audit 2026-09-04's M3: section 3.6's third row, where the other two are AC-10 and AC-11. The
    # pairing holds here as it does above - the engine proves the rule, the scan proves it is the
    # rule being used - and `test_the_matrix` is named twice, under AC-11 for its whole nine cells
    # and here for the three that are this mode, which are the only assertion anywhere that a
    # **lock** is honoured under `Local only`.
    20: (
        "tests.metadata.test_merge:test_local_only_drops_the_remote_sources_rather_than_behaving_differently",
        "tests.metadata.test_merge:test_local_only_still_fills_from_a_local_source_under_replace_semantics",
        "tests.metadata.test_merge:test_the_matrix",
        "tests.metadata.test_local_refresh:test_local_only_is_the_whole_of_this_slice",
        "tests.metadata.test_remote_refresh:test_a_local_only_refresh_names_the_providers_it_did_not_consult",
    ),
}


#: 005's twenty-five - sixteen at T17, six at the 2026-08-28 audit, three at the 2026-09-04 one.
#: Several criteria are named twice - once where the rule is proved at
#: repository or builder level and once where the route is proved to use it - for 004's recorded
#: reason: a correct rule and a rule the caller actually uses are two claims. AC-11 and AC-13
#: map to tests that assert the *measured* wire, which reversed one drafted criterion and
#: restated another; the spec carries both corrections with provenance.
#:
#: AC-23, AC-24 and AC-25 are audit 2026-09-04's M4, M5 and M6: three behaviours with a full test
#: file each and no criterion, so nothing here could name them and nothing would have failed if
#: they had been weakened.
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
        "tests.unit.test_played_state_routes:test_the_most_recently_played_series_leads",
    ),
    11: ("tests.unit.test_tv_routes:test_ac11_season_zero_sorts_first_as_measured",),
    # **The three names below are the determinism half only, and the second half of this criterion
    # is asserted nowhere** - found by audit 2026-09-04's C10 while sweeping for L15's shape, and
    # recorded here rather than mapped dishonestly. *"`Similar` returns exactly `limit` rows for
    # every seed type"* is 010's gate decision and the observable side of behaviours section 3.24,
    # where the reference answers `limit + 4` on a movie seed. The seeded world cannot discriminate
    # it: `Similar` answers an empty pool for a series, an album, an artist and a track seed, and a
    # one-row pool for a movie, so any `limit` a test could ask for is satisfied by a route that
    # ignores the parameter entirely. Closing it is a fixture question - which items share a genre
    # row - and that world is load-bearing for the query goldens and the by-name counts, so it is
    # named here for a decision rather than taken in a corrective task.
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
        "tests.unit.test_filters_and_search_routes:test_matching_folds_case_and_diacritics",
    ),
    15: (
        "tests.unit.test_items_route:test_ac15_a_tier_3_parameter_is_ignored_answered_and_recorded",
    ),
    16: (
        "tests.unit.test_item_filters:test_a_predicate_selects_something_and_less_than_everything",
        "tests.unit.test_items_route:test_every_parameter_changes_the_answer_and_survives_mangled_casing",
        "tests.unit.test_items_route:test_the_battery_matches_its_label_list",
        "tests.unit.test_items_route:test_the_battery_covers_the_specifications_tier_1_and_2",
    ),
    17: (
        "tests.unit.test_by_name_routes:test_genre_rows_carry_no_user_data_and_year_rows_do",
        "tests.unit.test_by_name_routes:test_artist_rows_carry_no_is_folder",
    ),
    18: (
        "tests.unit.test_item_dto:test_full_width_emits_the_gated_fields_unasked",
        "tests.unit.test_items_route:test_the_item_route_emits_everything_unasked",
    ),
    19: (
        "tests.unit.test_user_world_routes:test_a_group_of_several_surfaces_as_its_container_and_a_singleton_as_itself",
        "tests.unit.test_user_world_routes:test_each_group_appears_once_and_newest_first",
        "tests.unit.test_user_world_routes:test_an_excluded_library_contributes_nothing_unscoped",
        "tests.unit.test_user_world_routes:test_played_items_stay_out_by_default_and_come_back_when_asked",
        "tests.unit.test_user_world_routes:test_hide_played_in_latest_false_lets_played_items_in",
    ),
    20: (
        "tests.unit.test_played_state_routes:test_resume_is_the_stored_positions_newest_first",
        "tests.unit.test_played_state_routes:test_resume_reports_the_position_it_resumes",
        "tests.unit.test_played_state_routes:test_resume_pages_and_narrows",
        "tests.unit.test_played_state_routes:test_resume_is_per_user",
    ),
    21: (
        "tests.unit.test_items_route:test_an_unrecognised_sort_token_drops_and_is_recorded",
        "tests.unit.test_items_route:test_a_real_kind_this_version_cannot_produce_narrows_to_nothing",
        "tests.unit.test_items_route:test_a_malformed_id_inside_a_list_parameter_is_a_400_too",
        "tests.unit.test_user_world_routes:test_an_unknown_parent_is_the_problem_details_404",
    ),
    22: (
        "tests.unit.test_item_ordering:test_a_year_with_no_date_sorts_at_january_the_first",
        "tests.unit.test_item_ordering:test_the_dateless_and_yearless_do_not_displace_the_dated",
        "tests.unit.test_item_ordering:test_a_search_is_ordered_by_match_quality_first",
    ),
    23: (
        "tests.unit.test_filters_and_search_routes:test_the_summary_always_answers_all_four_keys_sorted",
        "tests.unit.test_filters_and_search_routes:test_genres_are_the_items_spellings_not_the_by_name_row",
        "tests.unit.test_filters_and_search_routes:test_the_scope_narrows_the_summary",
        "tests.unit.test_filters_and_search_routes:test_the_summary_is_the_visible_worlds",
        "tests.unit.test_filters_and_search_routes:test_an_unknown_parent_is_the_same_404",
    ),
    24: (
        "tests.conformance.test_item_wide_widths:test_the_wide_only_tier_is_what_was_measured",
        "tests.conformance.test_item_wide_widths:test_a_full_body_carries_all_eight",
        "tests.conformance.test_item_wide_widths:test_a_user_view_row_carries_all_eight",
        "tests.conformance.test_item_wide_widths:test_a_bare_list_row_carries_none_of_them",
        "tests.conformance.test_item_wide_widths:test_a_folder_is_not_downloadable_however_permissive_the_account",
        "tests.conformance.test_item_wide_widths:test_the_two_permissions_follow_the_effective_account",
        "tests.conformance.test_item_wide_widths:test_an_episode_names_its_season",
        "tests.conformance.test_item_wide_widths:test_every_item_building_route_names_the_access_it_emits_under",
        "tests.conformance.test_item_wide_widths:test_the_context_refuses_to_be_built_without_an_access",
    ),
    25: (
        "tests.conformance.test_item_media_source_policy:test_the_full_body_carries_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_the_item_list_carries_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_latest_carries_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_resume_carries_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_episodes_carry_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_next_up_carries_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_similar_carries_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_instant_mix_carries_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_playlist_entries_carry_the_accounts_flags",
        "tests.conformance.test_item_media_source_policy:test_the_policy_is_the_named_users_and_not_the_callers",
        "tests.conformance.test_item_media_source_policy:test_a_source_nothing_inspected_carries_the_flags_too",
        "tests.conformance.test_item_media_source_policy:test_every_item_building_route_fills_the_policy",
        "tests.conformance.test_item_media_source_policy:test_the_context_refuses_to_be_built_without_a_policy",
    ),
    26: (
        # The presences and, harder, the absences: a field added to WIDE_ONLY rather than to
        # WIDE_PER_TYPE passes every presence check and puts `Trickplay` on an album.
        "tests.unit.test_item_dto:test_the_wide_widths_gate_by_type_too",
        "tests.unit.test_item_dto:test_the_three_wide_constants_carry_the_measured_empty_value",
        # And on the wire, where a client reads them: the goldens for the three bodies that moved.
        "tests.conformance.test_golden_items:test_the_full_body_per_type",
        "tests.conformance.test_golden_items:test_the_list_row_per_type",
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
        "tests.conformance.test_image_routes:test_an_unparseable_dimension_or_quality_is_the_validation_400",
        "tests.conformance.test_image_routes:test_the_dimension_400_is_the_measured_body",
        "tests.unit.test_image_service:test_the_two_refusals_are_the_only_thing_raised",
    ),
    12: (
        "tests.conformance.test_image_routes:test_ac12_every_mechanism_is_accepted_and_none_changes_the_answer",
        "tests.conformance.test_auth_mechanisms:test_a_token_never_changes_a_token_optional_routes_answer",
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
    16: (
        "tests.unit.test_image_transform:test_the_delivered_size_is_the_measured_one",
        "tests.conformance.test_image_routes:test_the_resize_matrix_delivers_what_it_decided",
    ),
    17: (
        "tests.conformance.test_image_routes:test_the_header_set_on_a_bare_200_is_exactly_the_measured_one",
        "tests.conformance.test_image_routes:test_the_header_set_holds_across_the_whole_request_battery",
        "tests.conformance.test_image_routes:test_a_tagged_url_is_immutable_and_only_a_tagged_one",
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
    23: ("tests.unit.test_favourite_routes:test_a_favourite_does_not_cascade_to_the_children",),
    24: (
        "tests.conformance.test_session_routes:test_a_report_lands_on_the_callers_session_whatever_it_names",
    ),
}


#: 008's map is the first that carries a **marker**. Half of these tests need ffmpeg and ffprobe
#: on the machine, so on a run with `-m "not ffmpeg"` the criterion is mapped and deselected -
#: which is why the checks below assert that the names *exist*, not that they ran. Deselection is
#: visible; a criterion nothing names is not.
#:
#: Two rows here are the ones an audit found missing rather than wrong, and both are the failure
#: this repository keeps meeting - a test that proves less than its name suggests. AC-14 had a
#: `Content-Length` asserted on one route and a `Size` asserted in a golden, and nothing that put
#: the two numbers side by side; AC-8's `audioStreamIndex` was asserted as a string in a URL and
#: never as a property of the audio that came back.
#:
#: AC-33 and AC-34 are audit 2026-09-04's M7 and M8: two refusal tables with a full battery of
#: tests and no criterion. M7 is also the one finding of that class that made a **neighbouring
#: criterion false** - AC-32 counted three delivery routes refusing without a token where section
#: 3.7 has made it four since T11, while row 32 below named the segment route's test anyway. The
#: criterion now says four, and the row is honest rather than merely populated.
FEATURE_008: dict[int, tuple[str, ...]] = {
    1: (
        "tests.unit.test_media_decision:test_every_rung_of_the_ladder",
        "tests.conformance.test_playback_info:test_ac1_no_profile_at_all_answers_direct_play",
        "tests.conformance.test_playback_info:test_ac1_an_empty_profile_object_answers_the_opposite",
        # "Absent" is a property of the device, not of the body (T5): a bare `POST` from a device
        # that has posted its capabilities is negotiated against those, so the criterion's first
        # half is only true of a device that has said nothing.
        "tests.conformance.test_playback_info:test_a_post_with_no_profile_falls_back_to_the_devices_stored_one",
    ),
    2: (
        "tests.unit.test_media_decision:test_every_rung_of_the_ladder",
        "tests.conformance.test_playback_info:test_ac2_a_profile_that_accepts_the_source_answers_direct_play",
    ),
    3: (
        "tests.unit.test_media_decision:test_every_rung_of_the_ladder",
        "tests.conformance.test_playback_info:test_ac3_a_rejected_container_answers_a_url_with_both_streams_copied",
    ),
    4: (
        "tests.unit.test_media_decision:test_every_rung_of_the_ladder",
        "tests.conformance.test_playback_info:test_ac4_a_rejected_codec_answers_a_url_and_not_an_error",
    ),
    5: (
        "tests.unit.test_media_decision:test_every_rung_of_the_ladder",
        "tests.unit.test_media_decision:test_a_refusal_carries_no_reasons_because_it_carries_no_url",
        "tests.conformance.test_playback_info:test_ac5_a_profile_that_can_play_nothing_is_flags_and_no_error_code",
        "tests.conformance.test_playback_info:test_a_media_source_id_naming_nothing_is_the_one_error_code",
    ),
    6: (
        "tests.unit.test_media_decision:test_supports_transcoding_is_about_the_profile_not_about_the_answer",
        "tests.conformance.test_playback_info:test_ac6_supports_transcoding_is_about_the_profile_and_not_the_answer",
    ),
    7: (
        "tests.unit.test_media_decision:test_ac7_a_refused_audio_track_costs_an_audio_encode_and_not_a_video_one",
        "tests.conformance.test_playback_info:test_ac7_an_accepted_video_beside_a_rejected_audio_copies_the_video",
        "tests.conformance.test_progressive_delivery:test_ac7_the_accepted_video_stream_is_copied_while_the_audio_is_re_encoded",
        "tests.conformance.test_hls_segments:test_ac7_a_mixed_plan_copies_the_video_and_re_encodes_the_audio",
    ),
    8: (
        "tests.conformance.test_progressive_delivery:test_ac8_a_ceiling_below_the_source_is_honoured_on_the_delivered_bytes",
        # The parameter that reaches the encoder's stream mapping and had only ever been asserted
        # as a string in the negotiated URL. T14 wrote it, and proved it can fail by taking the
        # parameter out of the ladder's switches.
        "tests.conformance.test_progressive_delivery:test_ac8_audio_stream_index_changes_the_audio_that_is_produced",
        "tests.conformance.test_hls_segments:test_ac7_a_mixed_plan_copies_the_video_and_re_encodes_the_audio",
    ),
    9: (
        "tests.unit.test_media_decision:test_ac9_nothing_is_upscaled",
        "tests.unit.test_media_decision:test_ac9_a_ceiling_below_the_source_is_the_ceiling",
        "tests.unit.test_media_ffmpeg:test_ac9_no_scale_filter_appears_when_the_plan_is_the_size_the_source_already_is",
        "tests.conformance.test_progressive_delivery:test_ac9_a_720p_source_under_a_1080p_ceiling_is_delivered_at_720p",
    ),
    10: (
        "tests.conformance.test_progressive_delivery:test_ac10_a_start_position_begins_production_there",
        "tests.conformance.test_hls_segments:test_ac10_a_segment_near_the_end_produces_nothing_before_it",
    ),
    # The criterion's boundary is a row of this map too: the two playlist routes are sized and
    # carry no range unit, on both servers, which is why the last name here asserts an absence.
    11: (
        "tests.conformance.test_static_delivery:test_the_response_carries_the_measured_header_set_and_no_more",
        "tests.conformance.test_universal_audio:test_the_direct_play_answer_carries_exactly_the_measured_header_set",
        "tests.conformance.test_progressive_delivery:test_ac15_a_remux_carries_a_length_and_a_range_unit",
        "tests.conformance.test_hls_segments:test_a_segment_arrives_sized_and_labelled",
        "tests.conformance.test_hls_playlists:test_ac11_a_playlist_is_sized_and_carries_no_range_unit",
    ),
    12: (
        "tests.unit.test_compat_ranges:test_the_measured_matrix",
        "tests.conformance.test_static_delivery:test_ac12_a_mid_file_range_is_exactly_those_bytes",
        "tests.conformance.test_hls_segments:test_a_segment_honours_a_range",
    ),
    13: (
        "tests.unit.test_compat_ranges:test_the_measured_matrix",
        "tests.unit.test_compat_ranges:test_a_zero_byte_body_can_satisfy_nothing",
        "tests.conformance.test_static_delivery:test_ac13_an_unsatisfiable_range_is_a_416_with_nothing_in_it",
    ),
    14: (
        "tests.conformance.test_static_delivery:test_ac14_no_range_is_the_whole_file_with_its_length",
        # The join nothing made until T14: the `Size` the negotiation advertises, the
        # `Content-Length` the delivery route sends, and the bytes on the wire, from three
        # independent reads of one file.
        "tests.conformance.test_static_delivery:test_ac14_the_size_the_negotiation_advertises_is_the_body_the_route_serves",
        "tests.conformance.test_static_delivery:test_ac14_a_track_advertises_its_own_size_too",
    ),
    15: (
        "tests.conformance.test_progressive_delivery:test_ac15_a_remux_carries_a_length_and_a_range_unit",
        "tests.conformance.test_progressive_delivery:test_ac15_a_remux_honours_a_mid_file_range",
    ),
    16: (
        "tests.conformance.test_hls_segments:test_a_segment_arrives_sized_and_labelled",
        "tests.conformance.test_hls_segments:test_ac16_and_ac22_a_copied_segment_is_sized_and_identical_twice",
    ),
    17: (
        "tests.conformance.test_progressive_delivery:test_ac17_a_re_encode_is_chunked_with_no_length",
        "tests.conformance.test_progressive_delivery:test_a_range_on_a_chunked_answer_is_ignored_whatever_shape_it_has",
    ),
    18: (
        "tests.conformance.test_static_delivery:test_ac18_a_wrong_container_changes_the_label_and_nothing_else",
        "tests.conformance.test_static_delivery:test_the_suffixed_and_unsuffixed_routes_answer_the_same_bytes",
        "tests.conformance.test_wav_delivery:test_a_static_wav_request_is_still_the_source_bytes",
    ),
    19: (
        "tests.conformance.test_universal_audio:test_ac19_a_sample_rate_ceiling_is_answered_at_the_ceiling",
        "tests.conformance.test_universal_audio:test_ac19_a_channel_ceiling_below_the_source_is_honoured_too",
        "tests.unit.test_universal_profile:test_every_stated_ceiling_becomes_one_unscoped_audio_condition",
        "tests.unit.test_media_decision:test_a_sample_rate_ceiling_is_honoured_exactly_rather_than_from_the_opus_ladder",
    ),
    20: (
        "tests.conformance.test_wav_delivery:test_ac20_the_suffixed_route_answers_a_real_wav",
        "tests.conformance.test_wav_delivery:test_ac20_the_container_parameter_answers_the_same_wav",
        "tests.conformance.test_wav_delivery:test_ac20_universal_with_a_wav_transcoding_container_answers_a_real_wav",
        "tests.conformance.test_wav_delivery:test_ac20_a_mid_file_range_on_a_wav_answer_is_honoured",
        "tests.unit.test_media_ffmpeg:test_a_self_sizing_container_is_refused_to_a_pipe_rather_than_left_to_lie",
    ),
    21: (
        "tests.conformance.test_universal_audio:test_ac21_a_satisfied_constraint_set_is_the_file_with_no_location",
    ),
    22: (
        "tests.conformance.test_hls_playlists:test_ac22_the_playlist_is_complete_and_sized_before_any_segment_exists",
        "tests.conformance.test_hls_playlists:test_ac22_the_same_request_twice_is_the_same_list",
        "tests.unit.test_hls_planning:test_an_equal_grid_is_uniform_with_a_short_tail",
        "tests.conformance.test_hls_segments:test_ac16_and_ac22_a_copied_segment_is_sized_and_identical_twice",
    ),
    23: ("tests.conformance.test_hls_segments:test_ac23_the_same_segment_twice_is_the_same_bytes",),
    24: ("tests.conformance.test_hls_segments:test_ac24_a_segment_out_of_order_is_served",),
    25: (
        "tests.unit.test_transcode_lifecycle:test_ac25_the_stop_route_kills_exactly_the_named_session",
        "tests.unit.test_transcode_lifecycle:test_a_stop_leaves_the_remux_beside_it_alone",
    ),
    26: (
        "tests.conformance.test_progressive_delivery:test_ac26_a_disconnected_client_stops_the_encoder",
        "tests.unit.test_transcode_lifecycle:test_ac29_a_session_unpinged_past_the_timeout_dies_with_its_scratch",
        "tests.unit.test_transcode_lifecycle:test_a_session_pinged_inside_the_timeout_survives_the_sweep",
    ),
    27: (
        "tests.unit.test_transcode_throttle:test_ac27_production_runs_to_the_end_when_throttling_is_off",
        "tests.unit.test_transcode_throttle:test_ac27_production_pauses_at_the_gap_and_resumes_on_the_next_fetch",
        "tests.unit.test_transcode_throttle:test_the_gap_is_measured_from_the_furthest_segment_the_client_took",
        "tests.unit.test_transcode_throttle:test_the_shipped_configuration_has_both_features_off",
    ),
    28: (
        "tests.conformance.test_media_shapes:test_ac28_the_item_carries_the_demuxer_list_and_the_source_resolves_it",
        "tests.conformance.test_static_delivery:test_ac28_item_container_is_the_list_and_the_source_is_the_single_form",
        "tests.conformance.test_static_delivery:test_ac28_the_two_forms_agree_wherever_the_stored_string_is_one_name",
        "tests.unit.test_media_info:test_the_source_container_is_derived_per_response",
    ),
    29: (
        "tests.unit.test_transcode_lifecycle:test_ac29_a_session_unpinged_past_the_timeout_dies_with_its_scratch",
        "tests.unit.test_transcode_lifecycle:test_shutdown_stops_everything_and_leaves_the_scratch_root_empty",
        "tests.unit.test_transcode_lifecycle:test_an_orphan_a_crash_left_behind_is_cleared_at_startup",
        "tests.unit.test_transcode_throttle:test_ac29_segments_a_window_behind_the_client_are_removed_while_it_plays",
        "tests.unit.test_transcode_throttle:test_ac29_nothing_is_deleted_until_the_client_has_fetched_past_the_window",
        "tests.unit.test_transcode_throttle:test_ac29_a_deleted_segment_is_produced_again_when_it_is_asked_for",
    ),
    # Both halves of the "and", after audit 2026-09-04's L15 found only the second named. The
    # unit test mints the id with the function the negotiation calls and hands it to the stop
    # route; the conformance one is the identifier itself as a subject, followed from the
    # negotiated body through the segment route's session key to the same stop route.
    30: (
        "tests.unit.test_transcode_lifecycle:test_ac30_a_play_session_id_from_a_negotiation_is_accepted",
        "tests.conformance.test_hls_playlists:test_ac30_the_negotiated_id_keys_the_delivery_session_and_names_it_to_the_stop_route",
    ),
    31: (
        "tests.unit.test_media_decision:test_ac31_a_video_policy_needs_all_three_denials",
        "tests.unit.test_media_decision:test_ac31_an_audio_item_turns_on_the_audio_permission_alone",
        "tests.conformance.test_playback_info:test_ac31_one_denied_permission_negotiates_exactly_as_a_permitted_user",
        "tests.conformance.test_playback_info:test_ac31_all_three_denied_is_flags_down_and_no_error_code",
        # The profile-absent half, added 2026-09-02 with the fix for the difference
        # `tools/differential.py --named delivery-time-policy-refusal` found: the three rows
        # above are all against a profile, and the criterion's other branch reads **one**
        # permission per media kind (behaviours section 2.21).
        "tests.unit.test_media_decision:test_ac31_with_no_profile_a_single_denial_is_the_whole_gate",
        "tests.unit.test_media_decision:test_ac31_an_unnegotiated_audio_item_reads_the_audio_permission_alone",
        "tests.conformance.test_playback_info:test_ac31_a_video_negotiated_against_no_profile_reads_one_permission_per_flag",
        "tests.conformance.test_playback_info:test_ac31_a_denied_video_permission_moves_nothing_on_an_audio_item",
        # The delivery half, which T13 measured as per stream and video-only: the rule table is
        # the unit file's and the two wire shapes are the segment route's.
        "tests.unit.test_transcode_throttle:test_ac31_the_delivery_gate_is_per_stream",
        "tests.unit.test_transcode_throttle:test_ac31_an_account_denied_everything_is_refused_before_anything_is_planned",
        "tests.conformance.test_hls_segments:test_ac31_a_denied_re_encode_is_refused_rather_than_force_copied",
        "tests.conformance.test_hls_segments:test_ac31_a_denial_over_a_stream_that_is_copied_anyway_changes_nothing",
    ),
    32: (
        "tests.conformance.test_static_delivery:test_a_delivery_route_requires_no_token",
        "tests.conformance.test_static_delivery:test_the_credential_check_can_still_fail",
        "tests.conformance.test_universal_audio:test_ac32_universal_refuses_without_a_token_where_stream_does_not",
        "tests.conformance.test_hls_playlists:test_the_playlists_require_a_token_where_their_siblings_require_none",
        "tests.conformance.test_hls_segments:test_the_segment_route_requires_a_token",
    ),
    # The segment route's own table (M7). The token row is AC-32's too, because which routes
    # refuse without one is that criterion's whole subject and this is one of the four.
    33: (
        "tests.conformance.test_hls_segments:test_the_segment_route_requires_a_token",
        "tests.conformance.test_hls_segments:test_an_item_nothing_holds_is_the_third_error_shape",
        "tests.conformance.test_hls_segments:test_a_media_source_id_naming_no_source_is_the_same_body_at_400",
        "tests.conformance.test_hls_segments:test_a_segment_carrying_a_start_position_is_refused",
        "tests.conformance.test_hls_segments:test_a_segment_with_no_query_at_all_is_the_frameworks_refusal",
        # The row that is not a refusal, and the reason it is in the criterion: a `playlistId`
        # nothing named decides nothing, so validating it would be an invented refusal.
        "tests.conformance.test_hls_segments:test_a_playlist_id_nothing_named_still_answers_the_segment",
    ),
    34: (
        "tests.conformance.test_playback_info:test_an_unknown_item_is_the_same_404_as_the_item_route",
        "tests.conformance.test_playback_info:test_a_request_with_no_token_is_the_empty_401",
    ),
}


#: 011's map, and the first that carries a **traversal**. Three criteria - AC-4, AC-8 and AC-11 -
#: are about an address leading somewhere, so the tests they name follow a manifest to a playlist
#: to a document of cues rather than comparing strings; a manifest and a playlist can both be
#: well formed and lead nowhere, and only following them says so.
#:
#: **Four rows here are the ones T12 found unasserted**, each a criterion whose named tests proved
#: something narrower than the criterion said. AC-1 said *a listing row and a bare item* and only
#: the bare item had ever been asked; AC-11's `HasSubtitles` was asserted on a film that carries an
#: embedded track as well, so it passed with every discovered stream filtered out; AC-12's *"affects
#: neither the item nor its user data"* had nothing at all; and two rows of the section 3.7 table
#: AC-13 is written against had no test - the fetch routes' `500` for an item that exists with
#: nothing servable, which is the row the lookup's whole shape turns on, and the playlist's refusal
#: of a source that states no runtime.
#:
#: Like 008's, this map carries a **marker**: most of these tests need ffmpeg and ffprobe on the
#: machine, so on a run with `-m "not ffmpeg"` the criterion is mapped and deselected. The checks
#: below assert that the names exist, not that they ran.
FEATURE_011: dict[int, tuple[str, ...]] = {
    1: (
        "tests.conformance.test_media_shapes:test_the_two_file_facts_are_answered_on_every_stream_of_every_kind",
        # The half the criterion names first and nothing asked for until T12: a list row carries
        # its streams only when the request asks, so this is the request that can fail.
        "tests.conformance.test_media_shapes:test_the_two_file_facts_are_on_a_listing_row_too",
        "tests.conformance.test_media_shapes:test_a_subtitle_track_reaches_the_wire_under_the_renamed_spelling",
        "tests.unit.test_media_info:test_the_split_and_the_servable_rule_are_lookups_on_the_spelling",
        "tests.unit.test_media_info:test_the_two_renamed_spellings_that_invert_are_the_reason_the_rename_exists",
        "tests.unit.test_media_info:test_a_stream_that_is_not_a_subtitle_answers_false_to_both",
        "tests.conformance.test_playback_info:test_ac1_a_negotiated_source_states_a_delivery_method_on_every_subtitle_stream",
        "tests.conformance.test_playback_info:test_ac1_the_delivery_address_is_written_for_the_external_streams_alone",
        "tests.conformance.test_playback_info:test_ac1_a_bare_read_states_neither_the_method_nor_the_address",
    ),
    2: (
        "tests.conformance.test_playback_info:test_ac2_an_index_is_read_only_where_the_body_also_names_the_source",
        "tests.conformance.test_playback_info:test_ac2_an_index_naming_no_stream_is_restated_rather_than_refused",
        "tests.conformance.test_playback_info:test_the_address_carries_the_index_and_the_method_at_their_measured_positions",
        # The two subtractions T9 measured, which is why the criterion no longer says the address
        # names the track unconditionally - and the request that puts the index back.
        "tests.conformance.test_playback_info:test_the_external_method_drops_the_index_from_the_address",
        "tests.conformance.test_playback_info:test_an_index_of_minus_one_is_dropped_from_the_address_where_a_missing_one_is_not",
        "tests.conformance.test_playback_info:test_always_burn_in_keeps_the_index_and_appends_its_own_flag",
        "tests.unit.test_media_decision:test_no_track_named_proposes_no_default_at_all",
        "tests.unit.test_media_decision:test_an_index_naming_no_stream_costs_nothing_and_is_still_restated",
    ),
    3: (
        "tests.conformance.test_playback_info:test_ac3_a_profile_that_declares_no_subtitle_handling_answers_encode_on_every_track",
        "tests.conformance.test_playback_info:test_ac3_the_unconvertible_format_reaches_encode_under_a_vtt_only_profile",
        "tests.unit.test_media_decision:test_a_delivery_method_is_answered_for_every_subtitle_stream",
        "tests.unit.test_media_decision:test_convertibility_is_not_the_same_question_as_being_text",
    ),
    4: (
        "tests.conformance.test_subtitle_manifest:test_ac4_the_index_in_the_address_selects_the_track_that_is_served",
    ),
    5: (
        "tests.conformance.test_subtitle_manifest:test_ac5_an_announcement_is_the_measured_line_verbatim",
        "tests.conformance.test_subtitle_manifest:test_ac5_every_variant_of_a_multi_variant_master_ends_in_the_group",
        "tests.conformance.test_subtitle_manifest:test_a_sidecars_announcement_carries_the_external_word_and_its_own_language",
        # The index's whole job, measured at T11 against a criterion that had it as half the lever.
        "tests.conformance.test_subtitle_manifest:test_the_index_is_not_part_of_the_lever_and_only_decides_the_default",
        "tests.unit.test_hls_planning:test_an_announcement_is_the_measured_line_and_the_address_carries_thirty_and_a_token",
        "tests.unit.test_hls_planning:test_the_group_goes_on_every_variant_including_the_sdr_entrance",
    ),
    6: (
        "tests.conformance.test_subtitle_manifest:test_ac6_a_request_that_names_no_manifest_method_answers_the_same_bytes",
        "tests.conformance.test_subtitle_manifest:test_the_method_binds_in_any_case_and_by_ordinal_and_refuses_nothing",
        "tests.conformance.test_subtitle_manifest:test_a_source_with_no_text_subtitle_stream_is_never_given_a_group",
        "tests.unit.test_hls_planning:test_a_master_with_nothing_announced_is_the_playlist_it_was_before",
    ),
    7: (
        "tests.conformance.test_subtitle_manifest:test_ac7_an_image_index_still_announces_every_text_track_with_no_default",
    ),
    8: (
        "tests.conformance.test_subtitle_manifest:test_ac8_every_announced_address_and_every_window_is_fetched_as_written",
        "tests.conformance.test_subtitle_playlist:test_ac8_every_entry_is_fetched_by_following_it_as_written",
        "tests.conformance.test_subtitle_fetch:test_both_spellings_of_the_route_answer_the_same_bytes",
    ),
    9: (
        "tests.conformance.test_subtitle_fetch:test_ac9_a_whole_file_fetch_answers_the_declared_cues_with_the_files_timings",
        "tests.unit.test_subtitle_extract:test_an_embedded_text_track_comes_back_as_the_declared_cue_list",
        "tests.unit.test_subtitle_cues:test_every_readable_writer_round_trips_the_cues_and_their_timings",
    ),
    10: (
        "tests.conformance.test_subtitle_fetch:test_ac10_a_window_answers_its_own_cues_and_the_copy_switch_decides_their_timings",
        # The exception T7 measured and the user took into the criterion: the requested format is
        # the one the track is already in, so the readable file is handed back unwindowed.
        "tests.conformance.test_subtitle_fetch:test_a_window_on_the_format_the_track_is_already_in_answers_the_whole_track",
        "tests.conformance.test_subtitle_fetch:test_the_short_circuit_hands_back_the_artefact_and_not_a_rendered_document",
        "tests.unit.test_subtitle_cues:test_the_windows_of_a_track_concatenate_back_to_the_track",
        "tests.unit.test_subtitle_cues:test_a_cue_that_starts_on_a_window_boundary_is_answered_by_two_windows",
    ),
    11: (
        "tests.library.test_sidecar_discovery:test_a_sidecar_appears_and_disappears_and_the_indices_follow_it",
        "tests.unit.test_external_naming:test_the_filename_matrix",
        "tests.unit.test_subtitle_extract:test_a_sidecar_in_a_covered_format_is_read_without_a_process",
        "tests.unit.test_subtitle_extract:test_the_command_copies_a_copyable_codec_and_maps_the_demuxer_index",
        # "Fetchable through the same routes as an embedded one", asserted by fetching it: both
        # traversals below end on the sidecar's own cues rather than on the container's.
        "tests.conformance.test_subtitle_manifest:test_ac4_the_index_in_the_address_selects_the_track_that_is_served",
        "tests.conformance.test_subtitle_manifest:test_ac8_every_announced_address_and_every_window_is_fetched_as_written",
    ),
    12: (
        "tests.library.test_sidecar_discovery:test_a_sidecar_appears_and_disappears_and_the_indices_follow_it",
        # The clause nothing asserted until T12. The identifier is derived from the path and user
        # data hangs off it with no foreign key, so a scan that re-created the item around the
        # file would orphan a history and pass every other assertion in that file.
        "tests.library.test_sidecar_discovery:test_the_film_and_a_viewers_progress_survive_the_file_arriving_and_leaving",
        "tests.unit.test_domain_media:test_removing_a_sidecar_puts_every_index_back_where_it_was",
    ),
    13: (
        "tests.conformance.test_subtitle_playlist:test_a_caller_with_no_token_and_one_with_an_unknown_token_are_the_same_empty_401",
        "tests.conformance.test_subtitle_playlist:test_an_item_that_names_nothing_is_the_problem_details_404",
        "tests.conformance.test_subtitle_playlist:test_an_item_that_exists_and_is_not_a_video_is_the_same_404",
        "tests.conformance.test_subtitle_playlist:test_the_all_zero_identifier_is_the_controller_refusal_at_400",
        "tests.conformance.test_subtitle_playlist:test_an_identifier_that_is_not_one_names_this_routes_own_parameter",
        "tests.conformance.test_subtitle_playlist:test_a_media_source_that_names_nothing_is_the_500",
        # The row marked "read, not measured" on the reference, asserted here on a state this
        # server can be put into. Written at T12, which found the row untested.
        "tests.conformance.test_subtitle_playlist:test_a_source_that_states_no_runtime_is_the_controller_refusal",
        "tests.conformance.test_subtitle_playlist:test_an_index_naming_no_subtitle_is_still_a_whole_playlist",
        "tests.conformance.test_subtitle_playlist:test_a_window_length_that_will_not_bind_is_problem_details_naming_it",
        "tests.conformance.test_subtitle_playlist:test_a_window_length_of_zero_is_the_controller_refusal",
        "tests.conformance.test_subtitle_fetch:test_neither_credential_changes_the_answer",
        "tests.conformance.test_subtitle_fetch:test_an_item_that_names_nothing_is_the_controller_refusal_at_400",
        # The third row of the table, and the one the fetch routes' lookup is shaped by: an item
        # that is there with nothing servable is the `500` where an identifier naming nothing is
        # the `400`. Written at T12, which found it unasserted.
        "tests.conformance.test_subtitle_fetch:test_an_item_that_exists_with_nothing_servable_is_the_500",
        "tests.conformance.test_subtitle_fetch:test_an_identifier_that_is_not_one_is_problem_details_naming_the_route_parameter",
        "tests.conformance.test_subtitle_fetch:test_a_media_source_that_names_nothing_is_the_500",
        "tests.conformance.test_subtitle_fetch:test_an_index_that_names_no_text_subtitle_is_the_500",
        "tests.conformance.test_subtitle_fetch:test_an_image_track_asked_for_as_text_is_refused_at_400_without_a_process",
        "tests.conformance.test_subtitle_fetch:test_a_format_nothing_writes_is_refused_before_any_file_is_opened",
        "tests.conformance.test_subtitle_fetch:test_a_window_whose_end_precedes_its_start_is_a_body_with_no_cues",
    ),
    14: (
        "tests.conformance.test_subtitle_fetch:test_ac14_a_subtitle_fetched_twice_answers_the_same_bytes",
        "tests.unit.test_subtitle_extract:test_a_second_call_for_the_same_key_starts_no_process",
        "tests.unit.test_subtitle_cues:test_the_same_cues_render_to_the_same_bytes_twice",
    ),
    15: (
        "tests.conformance.test_playback_info:test_ac15_a_direct_played_file_answers_what_it_answered_before",
        # The narrowing T9 measured, on both sides of the discrimination: the same file and the
        # same profile, one index kept and one lost.
        "tests.conformance.test_playback_info:test_naming_a_track_the_profile_cannot_take_costs_the_source_its_direct_play",
        "tests.unit.test_media_decision:test_naming_a_track_the_client_cannot_take_costs_the_source_its_direct_play",
        "tests.unit.test_media_decision:test_the_manifest_method_cannot_save_a_direct_play_because_it_is_not_reachable_there",
    ),
    16: (
        "tests.conformance.test_subtitle_playlist:test_ac16_a_partial_window_is_written_with_a_decimal_point",
        "tests.unit.test_hls_planning:test_ac16_the_decimal_point_survives_a_locale_that_writes_a_comma",
        "tests.unit.test_hls_planning:test_a_window_duration_is_written_with_a_point_and_no_trailing_zeros",
    ),
    # Audit 2026-09-04's M10: section 3.5's format table, where AC-13 is section 3.7's rows. The
    # discriminating name is the byte-order-mark one - it is what says `subrip` is a *rendered*
    # document where `srt` is the short circuit's artefact, which is the table's own claim that
    # a spelling with no media type answers a different body from its canonical one.
    17: (
        "tests.conformance.test_subtitle_fetch:test_every_writable_spelling_answers_its_measured_label",
        "tests.conformance.test_subtitle_fetch:test_the_byte_order_mark_is_on_every_rendered_document_but_the_json_one",
        "tests.conformance.test_subtitle_fetch:test_the_json_answer_is_the_cue_list_as_an_object_of_track_events",
        # The other half of "a different body from its canonical spelling", for the alias whose
        # writer *is* `vtt`'s: the switch is read against one spelling and not the other.
        "tests.conformance.test_subtitle_fetch:test_the_time_map_switch_prepends_a_line_and_drops_the_mark",
        "tests.conformance.test_subtitle_fetch:test_the_time_map_is_read_against_vtt_and_not_against_its_alias",
    ),
}


#: 009's map, twenty rows, and **the closing task found the class this file exists for three
#: times**. AC-20 — *"playlist state survives a full library rescan"* — had no test of any kind:
#: the only `ac20` name in the playlist file is about a **rename**, which T13 said out loud and
#: nothing acted on. It is a criterion nobody could have noticed passing, because a playlist is
#: the one item a rescan cannot rebuild, and it is proven now in `tests/library/test_removal.py`,
#: where a real scan runs over a real library — with a deletion check behind it: remove the two
#: independent clauses that keep a playlist out of the removal pass and all three rows fail, the
#: purge taking the playlist row with it.
#:
#: Two more proved less than their names. **AC-5 says "on both the creation and the addition
#: paths"** and every assertion under it went through the add route; `create` reduces its batch in
#: a different place from `append`, so the path the measured answer belongs to — `Ids` naming
#: A B A creating A B — was the one nothing asked. **AC-13 says "the same three routes answer
#: `404`"** and one of the three had been asked; the move is the route whose refusals are ordered
#: `404`, `403`, index, entry, so it is the one where an ordering change discloses a playlist.
#: AC-9's *"every entry keeps its `PlaylistItemId`"* was compared on `Id`, which AC-4 makes equal
#: and does not make the same claim.
#:
#: **And AC-15 said something its own tests contradict**, which is 008 T14's finding again: it
#: read *"answers `404` on direct fetch — including when the request names its owner in
#: `userId`"*, and naming another user is the 25-byte `403` of AC-16 and AC-19, on every route in
#: this project that takes the parameter. The criterion is amended rather than the code.
FEATURE_009: dict[int, tuple[str, ...]] = {
    1: (
        "tests.conformance.test_playlists:test_a_created_playlist_appears_in_items_filtered_by_its_type",
    ),
    2: (
        "tests.conformance.test_playlists:test_an_empty_or_blank_name_creates_a_playlist_carrying_it",
        "tests.conformance.test_playlists:test_a_body_with_no_name_is_the_deserialisers_refusal_keyed_on_the_dollar",
        # The second layer, and the request nobody had asked about until T8: `Name` present and
        # null is a different body from `Name` absent, so "the validation shape" is two shapes.
        "tests.conformance.test_playlists:test_a_null_name_is_a_different_refusal_keyed_on_the_property",
        "tests.conformance.test_playlists:test_the_two_refusals_of_this_route_are_not_the_same_shape",
    ),
    3: (
        "tests.conformance.test_playlists:test_an_unknown_id_before_any_resolvable_one_is_the_controllers_refusal",
        "tests.conformance.test_playlists:test_an_unknown_id_after_a_resolvable_one_is_skipped",
        "tests.conformance.test_playlists:test_a_media_type_makes_the_same_unknown_id_harmless",
    ),
    4: (
        "tests.conformance.test_playlists:test_ac4_every_row_carries_a_playlist_item_id_equal_to_its_id",
        "tests.conformance.test_playlists:test_the_property_sits_immediately_after_id_and_on_no_other_route",
    ),
    5: (
        # T14 added the creation half to this test: the criterion names two paths and this asked
        # one, and `create` reduces the batch somewhere `append` does not.
        "tests.conformance.test_playlists:test_ac5_a_repeat_adds_nothing_and_moves_nothing_expansions_included",
        "tests.unit.test_playlist_repository:test_create_de_duplicates_the_id_list_and_keeps_the_first_occurrence",
        "tests.unit.test_playlist_repository:test_appending_something_already_there_adds_nothing_and_moves_nothing",
        # The divergence's own half: "every time" is the claim, and the hole a conflict-only
        # de-duplication would leave in the ordinals is what makes it a reduction and not a key.
        "tests.unit.test_playlist_repository:test_a_batch_of_duplicates_and_new_ids_leaves_no_hole_in_the_ordinals",
    ),
    6: (
        "tests.conformance.test_playlists:test_ac6_removing_by_entry_id_removes_exactly_that_row",
        "tests.conformance.test_playlists:test_ac6_a_removal_that_names_nothing_present_is_still_204",
        "tests.unit.test_playlist_repository:test_removing_from_the_middle_closes_the_gap",
    ),
    7: (
        "tests.conformance.test_playlists:test_ac7_an_album_expands_to_its_tracks_in_the_albums_own_order",
        "tests.conformance.test_playlists:test_ac7_every_container_expands_and_two_of_them_were_never_named",
        "tests.conformance.test_playlists:test_the_expansion_lands_where_the_container_was_named",
        "tests.conformance.test_playlists:test_creation_expands_too_and_the_media_type_follows_the_expansion",
        # The artist's ordering, which the seeded world cannot tell from a plain sort name at the
        # boundary (T10) - so it is asserted as the key function, and says so.
        "tests.unit.test_playlist_expansion_order:test_the_albums_are_grouped_where_a_sort_by_name_would_interleave_them",
        "tests.unit.test_playlist_expansion_order:test_the_album_artist_outranks_the_album_and_the_id_closes_the_order",
    ),
    8: (
        "tests.conformance.test_playlists:test_ac8_the_order_is_the_playlists_and_no_sort_parameter_is_declared",
    ),
    9: (
        "tests.conformance.test_playlists:test_ac9_the_thirty_measured_pairs_over_http",
        "tests.unit.test_playlists_domain:test_every_source_and_target_matches_the_reference",
        "tests.unit.test_playlists_domain:test_the_pair_that_distinguishes_the_two_readings",
        "tests.unit.test_playlists_domain:test_every_entry_survives_a_move",
    ),
    10: (
        "tests.conformance.test_playlists:test_ac10_and_ac11_every_row_of_the_boundary_table",
        "tests.unit.test_playlists_domain:test_an_index_one_past_the_count_is_the_last_position",
        "tests.unit.test_playlists_domain:test_an_index_outside_the_clamp_is_refused",
    ),
    11: (
        "tests.conformance.test_playlists:test_ac10_and_ac11_every_row_of_the_boundary_table",
        "tests.unit.test_playlists_domain:test_an_absent_entry_with_an_index_in_range_changes_nothing",
        "tests.unit.test_playlists_domain:test_the_index_is_judged_before_the_entry_is_looked_up",
    ),
    12: (
        "tests.conformance.test_playlists:test_ac12_the_owner_deletes_their_playlist_and_it_is_gone",
        "tests.conformance.test_playlists:test_ac12_a_caller_who_may_not_delete_is_the_401_with_its_body",
        "tests.conformance.test_playlists:test_ac12_anything_that_is_not_a_playlist_is_refused",
        "tests.conformance.test_playlists:test_ac12_a_film_is_refused_and_the_file_is_still_on_disk",
        "tests.conformance.test_playlists:test_an_unknown_identifier_is_the_problem_details_404",
        "tests.conformance.test_playlists:test_an_item_this_caller_cannot_see_is_404_before_the_refusal",
        # The clause T12 added: "including one they may not read" is a disclosure, and the reason
        # this route holds a disclosing refusal and a non-disclosing one at once.
        "tests.conformance.test_playlists:test_the_deletion_refusal_discloses_a_playlist_every_other_route_hides",
    ),
    13: (
        "tests.conformance.test_playlists:test_ac13_and_ac14_the_edit_refusal_is_the_other_403",
        "tests.conformance.test_playlists:test_ac13_and_ac14_the_move_refusal_is_the_body_less_403",
        # Widened at T14 from the add route alone to all three, which is what the criterion says.
        "tests.conformance.test_playlists:test_an_administrator_is_answered_404_before_the_edit_refusal",
        "tests.conformance.test_playlists:test_ac13_an_administrator_deletes_a_playlist_they_neither_own_nor_may_read",
        "tests.unit.test_playlists_domain:test_only_delete_reads_the_administrator_flag",
    ),
    14: (
        "tests.conformance.test_playlists:test_a_share_with_can_edit_may_write",
        "tests.conformance.test_playlists:test_ac13_and_ac14_the_edit_refusal_is_the_other_403",
        "tests.conformance.test_playlists:test_ac13_and_ac14_the_move_refusal_is_the_body_less_403",
        "tests.conformance.test_playlists:test_the_create_body_stores_its_shares_and_its_public_flag",
        "tests.unit.test_playlists_domain:test_a_share_never_grants_deletion",
    ),
    15: (
        # Through `/Items` and not only through a direct fetch: `_visible_to`'s library clause
        # exempts a row with no library, and a playlist has none (T6, the tasks gate's finding 2).
        "tests.unit.test_items_route:test_ac15_a_private_playlist_is_absent_from_another_users_items",
        "tests.unit.test_items_route:test_ac15_an_unreachable_playlist_answers_404_by_id",
        "tests.unit.test_items_route:test_an_administrator_gets_no_read_on_a_playlist_they_do_not_own",
        # The clause T14 corrected: naming the owner is refused, and the refusal is a `403`.
        "tests.conformance.test_playlists:test_ac16_naming_another_user_is_the_controllers_own_twenty_five_bytes",
    ),
    16: (
        "tests.conformance.test_playlists:test_ac16_naming_another_user_is_the_controllers_own_twenty_five_bytes",
        "tests.conformance.test_playlists:test_an_administrator_may_name_a_user_and_gets_that_users_view",
        "tests.conformance.test_playlists:test_ac19_naming_another_user_on_the_add_route_is_the_twenty_five_bytes",
        "tests.unit.test_items_route:test_an_administrator_naming_a_user_sees_that_users_playlists",
    ),
    17: (
        "tests.conformance.test_playlists:test_ac17_a_reader_is_shown_only_the_entries_they_can_reach",
        "tests.conformance.test_playlists:test_ac17_a_readers_move_indexes_the_list_that_reader_was_given",
        "tests.conformance.test_playlists:test_ac17_an_entry_the_reader_cannot_see_is_answered_as_an_absent_one",
        "tests.conformance.test_playlists:test_a_readers_index_is_bounded_by_what_that_reader_was_given",
        "tests.unit.test_playlists_domain:test_the_entry_lands_where_the_caller_asked_in_the_callers_own_list",
        "tests.unit.test_playlists_domain:test_the_hidden_entry_is_not_addressable_by_a_caller_who_cannot_see_it",
    ),
    18: (
        "tests.conformance.test_playlists:test_ac18_an_administrator_renames_a_playlist",
        "tests.conformance.test_playlists:test_ac18_the_non_administrator_owner_is_the_empty_403",
        "tests.conformance.test_playlists:test_the_policy_refuses_before_anything_about_the_item_is_read",
    ),
    19: (
        "tests.conformance.test_playlists:test_ac19_naming_another_user_on_the_add_route_is_the_twenty_five_bytes",
        "tests.conformance.test_playlists:test_a_user_id_naming_somebody_else_is_the_reference_403_with_its_bytes",
        # The 005 route that shares the rule, which is where the correction had to be taken (T2).
        "tests.unit.test_items_route:test_user_id_of_somebody_else_is_the_controller_403",
    ),
    20: (
        # Written at T14, because until then this criterion had nothing at all. A real scan over a
        # real library, which is what `tests/library/` is and `tests/conformance/` is not.
        "tests.library.test_removal:test_ac20_a_playlist_and_its_entries_survive_a_rescan_that_changes_nothing",
        "tests.library.test_removal:test_ac20_an_entry_whose_file_goes_and_returns_keeps_its_place",
        "tests.library.test_removal:test_ac20_a_purge_does_not_take_the_playlist_row_with_it",
        # The rename's half of "state": three columns of one row, and nothing else about it.
        "tests.conformance.test_playlists:test_ac20_a_renamed_playlist_keeps_its_entries",
    ),
    # Audit 2026-09-04's M9. The first two of the four bodies are AC-2's above; the two named
    # here are the converter's and the binder's, which had tests and no criterion at all - and
    # section 6 said "the two `400` shapes" where T8 had counted four.
    21: (
        "tests.conformance.test_playlists:test_an_unrecognised_media_type_in_the_body_is_the_converters_refusal",
        "tests.conformance.test_playlists:test_the_media_type_refusals_position_follows_the_token_and_not_the_request",
        "tests.conformance.test_playlists:test_a_malformed_identifier_is_the_binders_refusal_keyed_on_the_empty_string",
        # The structural half, and what makes this a claim about every refusal of the route: the
        # row behaviours section 1.11 states of every body refusal is a *required* body's.
        "tests.conformance.test_playlists:test_no_refusal_of_this_body_names_the_action_parameter",
    ),
}


#: Feature 010. **The eighteen, and one of them was mapped to tests that contradicted it.**
#:
#: AC-2 **said** *"both servers, pointed at the same built fixture, produce libraries with the same
#: item count and the same structure"*, and the tests named for it assert the opposite: Atrium's
#: scan of the fixture differs from the reference's recorded reading in **forty-seven declared
#: places**, one of them an item count. That is not a harness defect - the comparison exists, runs
#: in the default job with no Jellyfin, and writes every difference down with its reason - it was
#: the criterion asserting a conformance property that spec section 2 puts outside this feature:
#: *"deciding what Atrium does about a difference this feature finds"* belongs to the feature that
#: owns the endpoint. Every other criterion here is about the harness; AC-2 alone was about Atrium.
#: The row was mapped so the tests could not rot while the call was reserved as **D-7** in
#: [010's tasks](../../specs/010-conformance-harness/tasks.md); **D-7 was taken on 2026-09-02 and
#: AC-2 now states the comparison these four tests make** - the record and its citation, the item
#: count of every library, the declared count, and the two failure directions (an undeclared
#: difference, and a declared one that has gone away). 010 is Implemented from that date. The
#: forty-seven differences are unchanged and still belong to 003 and 004.
#:
#: Two other rows say less than they look, and both say so in their own entry rather than in a
#: paragraph nobody reads: AC-15's *"created and destroyed by the run"* is true of the reference
#: and **unsatisfiable on Atrium by design** (010 T12, plan section 6.7), and AC-3's *"covers every
#: endpoint"* is a property of the declared cases, not of what any run has issued.
FEATURE_010: dict[int, tuple[str, ...]] = {
    # Two builds of each world, byte for byte: the paths-and-filler tree and the media one.
    1: (
        "tests.library.test_fixture_library:test_two_builds_are_byte_identical",
        "tests.unit.test_media_fixtures:test_two_builds_of_one_entry_are_byte_identical",
        "tests.unit.test_media_fixtures:test_two_builds_of_a_planted_entry_are_byte_identical",
    ),
    # **Read the comment above before reading this row.** These tests assert the declared
    # differences between the two readings, which is the comparison AC-2 states since D-7 and not
    # the equality it stated when it was written.
    2: (
        "tests.library.test_reference_reading:test_atriums_scan_of_the_fixture_matches_the_recorded_reference_reading",
        "tests.library.test_reference_reading:test_the_reading_states_the_item_count_of_every_library",
        "tests.library.test_reference_reading:test_the_declared_differences_are_the_number_this_module_claims",
        "tests.library.test_reference_reading:test_the_record_carries_its_own_citation",
    ),
    3: (
        "tests.unit.test_allowlist:test_every_surface_endpoint_has_at_least_one_case",
        "tests.conformance.test_differential:test_every_endpoint_of_the_surface_is_reachable_by_at_least_one_declared_case",
        "tests.conformance.test_differential:test_the_endpoints_come_from_the_surface_and_carry_the_level_it_declares",
        "tests.conformance.test_differential:test_the_declared_conformance_level_is_printed_beside_every_endpoint",
    ),
    # Spec section 6's mutation table, one row per class, every assertion a count.
    4: (
        "tests.conformance.test_differential:test_a_removed_field_is_exactly_one_missing_key",
        "tests.conformance.test_differential:test_an_added_field_is_exactly_one_extra_key",
        "tests.conformance.test_differential:test_an_integer_sent_as_a_string_is_exactly_one_type_difference",
        "tests.conformance.test_differential:test_a_changed_title_is_exactly_one_value_difference",
        "tests.conformance.test_differential:test_a_reordered_thousand_row_array_is_exactly_one_order_and_no_values",
        "tests.conformance.test_differential:test_a_shorter_array_is_exactly_one_length_and_no_findings_from_its_rows",
    ),
    5: (
        "tests.conformance.test_differential:test_the_report_ranks_missing_keys_first",
        "tests.conformance.test_differential:test_the_report_ranks_missing_keys_first_in_its_own_table",
    ),
    # AC-6 proven by making it fire: the bad entry is constructed and the loader must refuse it.
    6: (
        "tests.unit.test_allowlist:test_an_entry_with_no_because_fails_the_load",
        "tests.unit.test_allowlist:test_an_entry_whose_because_is_an_excuse_fails_the_load",
        "tests.unit.test_allowlist:test_a_fifth_derivation_class_fails_the_load",
        "tests.unit.test_allowlist:test_a_behaviours_section_is_a_because_and_a_bare_section_number_is_not",
        "tests.unit.test_allowlist:test_every_behaviours_section_cited_exists",
    ),
    # Two claims joined by "and", and the first had no test at all until 010 T15.
    7: (
        "tests.unit.test_probe_convention:test_a_report_prints_the_citation_in_the_documented_form",
        "tests.unit.test_probe_convention:test_report_returns_one_on_a_contradiction",
        "tests.unit.test_probe_convention:test_every_probe_reaches_the_shared_entry_point",
    ),
    8: (
        "tests.unit.test_probe_convention:test_a_contradiction_names_the_document_and_the_section",
        "tests.unit.test_probe_convention:test_every_probe_names_a_document_and_a_section",
    ),
    9: (
        "tests.unit.test_probe_convention:test_every_register_row_names_a_script_that_exists_or_says_why_not",
        "tests.unit.test_probe_convention:test_the_prose_count_matches_the_table",
        "tests.unit.test_probe_convention:test_every_prior_probe_citation_belongs_to_a_row_of_the_register",
    ),
    # D-5: the fourth column, the file it is written to, and the route it must never become.
    10: (
        "tests.unit.test_compat_query_params:test_the_tally_names_the_client_that_sent_the_parameter",
        "tests.unit.test_compat_query_params:test_a_dropped_token_carries_the_client_too",
        "tests.unit.test_compat_query_params:test_the_tally_is_written_to_the_data_directory_at_shutdown_and_to_no_route",
        "tests.conformance.test_differential:test_the_ignored_parameter_report_lists_parameter_endpoint_count_and_client",
        "tests.conformance.test_differential:test_the_ignored_parameter_report_is_read_from_a_file_and_never_asked_of_a_route",
    ),
    # AC-11 was mapped to "CI, unchanged" and asserted nowhere. 010 T15 wrote the three.
    11: (
        "tests.conformance.test_differential:test_a_test_that_opens_a_tcp_connection_fails_rather_than_skipping",
        "tests.conformance.test_differential:test_nothing_this_feature_adds_needs_a_reference",
        "tests.conformance.test_differential:test_no_ci_job_contacts_or_starts_a_jellyfin",
    ),
    12: (
        "tests.unit.test_version_bump:test_a_failed_step_stops_the_procedure_and_the_later_steps_do_not_run",
        "tests.unit.test_version_bump:test_no_flag_skips_step_two_when_the_running_reference_changed",
        "tests.unit.test_version_bump:test_only_passed_and_skipped_let_the_procedure_reach_the_next_step",
    ),
    13: (
        "tests.library.test_fixture_library:test_the_generator_is_the_only_source_of_media",
        "tests.unit.test_media_fixtures:test_every_file_in_the_media_tree_is_generated_by_a_declared_entry",
    ),
    14: (
        "tests.conformance.test_differential:test_a_report_built_from_one_identity_says_one_identity",
        "tests.conformance.test_differential:test_a_one_identity_run_is_a_shorter_loop_and_not_a_different_code_path",
        "tests.conformance.test_differential:test_an_endpoint_compared_from_one_seat_of_two_is_partly_and_never_yes",
    ),
    # The pre-flight and the teardown. **On the reference only** - the three routes a seat is made
    # with are not in surface.yaml, so on Atrium a seat is handed in (010 T12, plan section 6.7).
    15: (
        "tests.conformance.test_differential:test_a_seat_that_already_exists_refuses_the_run_and_names_it",
        "tests.conformance.test_differential:test_a_run_that_created_a_seat_tears_it_down_on_the_exception_path",
        "tests.conformance.test_differential:test_a_seat_whose_policy_is_refused_stops_the_run_and_leaves_nothing_behind",
        "tests.conformance.test_differential:test_the_administrator_is_never_torn_down",
    ),
    16: (
        "tests.unit.test_allowlist:test_the_register_is_spec_310s_table",
        "tests.unit.test_allowlist:test_the_register_counts_twenty_two",
        "tests.conformance.test_differential:test_the_named_comparisons_are_all_reported_even_though_none_can_run",
        "tests.conformance.test_differential:test_a_run_with_an_outstanding_named_comparison_is_not_clean",
        "tests.conformance.test_differential:test_an_outstanding_row_says_which_need_was_missing_and_not_merely_that_it_did_not_run",
    ),
    17: (
        "tests.conformance.test_differential:test_a_key_removed_from_a_drawn_array_is_reported_and_a_changed_value_is_not",
        "tests.conformance.test_differential:test_a_drawn_array_excuses_its_rows_and_never_the_envelope_around_them",
        "tests.conformance.test_differential:test_a_drawn_arrays_length_is_reported_and_the_shape_walk_still_runs",
        "tests.conformance.test_differential:test_a_drawn_arrays_shape_walk_is_position_free_because_a_draw_holds_other_items",
    ),
    18: (
        "tests.conformance.test_differential:test_a_reordered_unordered_array_reports_nothing_at_all",
        "tests.conformance.test_differential:test_an_unordered_array_reordered_and_changed_reports_exactly_the_change",
        "tests.conformance.test_differential:test_an_unordered_page_that_lost_a_row_and_repeated_another_is_the_residue_only",
    ),
}


#: 012's map, and **the first whose feature adds itself to no set any test reads**. Every closing
#: task before this one put its number into `IMPLEMENTED_FEATURES`, which `surface_paths()` filters
#: `surface.yaml` by; 012 owns no row there — it is the first feature to change what an
#: already-listed route answers without adding one — so nothing but the status table in
#: `specs/README.md` and this dictionary carries the claim that its criteria are asserted.
#:
#: **T11 found the class this file exists for twice.** Spec section 3.4's
#: fourth row — an item whose file has **gone from disk** since the scan, answered fully annotated
#: from what the scan stored — had no test at any level, and it is the row that tells this
#: feature's trigger from the one it is easily mistaken for: written as *"the file cannot be read"*
#: the trigger fires there, the inspection fails on bytes that are gone, and a client is handed the
#: empty annotation for an item the scan had fully described. It is proven now, and its red run
#: needed **two** mutations rather than one, which is the second finding: the row is held by the
#: trigger *and* by `api/media_info.py:_opened` skipping a part that already carries a probe, and
#: either alone lets it through.
#:
#: **That is a fact about that row, and it was written here as a fact about the two lines** - audit
#: 2026-09-04's M17 deleted the guard alone and watched the whole suite pass, so nothing held it.
#: AC-9 below names the test that holds it now, and the lesson is the one this file exists for: a
#: mutation proves the row it reddens, and "both were needed together" never implied "each is
#: caught somewhere".
#:
#: **And AC-9 said something two of its neighbours contradict**, which is 010 T15's AC-2 again:
#: *"nothing in this feature changes what a negotiation answers for an item that has been opened,
#: for any profile"* is a prohibition AC-7 and AC-8 break on purpose, so no test could have passed
#: both. The criterion is amended to the file side it was written about — the ninth amendment on
#: that document — and the tests named below are what it is left claiming.
FEATURE_012: dict[int, tuple[str, ...]] = {
    # The flags are an answer and not a default, on a file nothing opened and nothing can open.
    1: (
        "tests.conformance.test_playback_info:test_ac1_a_source_nothing_opened_answers_flags_that_were_decided",
        "tests.conformance.test_playback_info:test_ac1_the_empty_annotation_is_still_the_files_own_container_and_size",
        "tests.conformance.test_playback_info:test_ac1_a_file_that_can_never_be_read_is_reopened_on_every_negotiation",
        "tests.unit.test_library_inspection:test_the_trigger_is_the_references_condition",
        "tests.unit.test_library_inspection:test_opening_answers_none_for_either_failure",
    ),
    2: (
        "tests.conformance.test_playback_info:test_ac2_the_negotiation_that_opens_the_file_is_the_one_that_answers",
        "tests.unit.test_library_inspection:test_opening_a_real_file_and_a_real_refusal",
    ),
    3: (
        "tests.conformance.test_playback_info:test_ac3_the_next_listing_carries_what_the_negotiation_learned",
        "tests.unit.test_library_inspection:test_the_probe_row_and_the_source_row_describe_the_same_bytes",
        "tests.unit.test_library_inspection:test_storing_twice_replaces_the_streams_rather_than_duplicating_them",
        # D-1's half of the write, which is the scan's rather than the wire's: without the change
        # signal the rescan after a heal rewrites the item for ever, one claimed update per file.
        "tests.unit.test_library_inspection:test_a_healed_file_is_neither_reopened_nor_rewritten_by_the_next_scan",
        "tests.unit.test_library_inspection:test_only_the_probe_row_leaves_the_next_scan_rewriting_the_item",
        "tests.unit.test_repositories:test_the_narrow_write_moves_two_columns_of_one_part",
    ),
    # **AC-4 is about the negotiation answering with an address, not about the address answering.**
    # A test that followed it would be asserting behaviours section 3.13's reference defect, which
    # is deferred to the feature that gives v1 a live path. Both names below stop at the answer.
    4: (
        "tests.conformance.test_playback_info:test_ac1_a_source_nothing_opened_answers_flags_that_were_decided",
        "tests.conformance.test_playback_info:test_a_part_the_trigger_never_fires_for_is_still_decided_rather_than_advertised",
    ),
    # Asked against a source the profile **can** direct-play, because against one it cannot both
    # answers refuse and the comparison passes while asserting nothing (plan section 8, T5).
    5: ("tests.conformance.test_playback_info:test_ac5_the_second_opinion_is_a_different_answer",),
    6: (
        "tests.conformance.test_playback_info:test_ac6_an_audio_item_with_no_audio_stream_refuses_the_whole_request",
        "tests.conformance.test_playback_info:test_ac6_the_same_request_with_no_profile_answers_the_un_annotated_source",
        "tests.conformance.test_playback_info:test_ac6_a_stored_device_profile_is_a_profile_in_play",
        # The two that separate the refusal's real condition from the one it is confused with: a
        # readable file with no audio stream is refused, and a film with no video stream is not.
        "tests.conformance.test_playback_info:test_the_refusal_is_the_missing_audio_stream_and_not_the_unreadable_file",
        "tests.conformance.test_playback_info:test_a_film_with_no_video_stream_is_answered_rather_than_refused",
    ),
    7: (
        "tests.conformance.test_playback_info:test_ac7_any_case_of_hls_answers_a_playlist_and_the_enumerations_own_spelling",
        "tests.conformance.test_playback_info:test_ac7_any_case_of_http_answers_a_progressive_address",
        "tests.unit.test_media_decision:test_the_delivery_protocol_is_lower_case_by_declaration_with_declared_ordinals",
        "tests.unit.test_media_decision:test_the_string_compared_against_and_the_string_echoed_are_one",
    ),
    # Four classes and four rows, because a criterion written over "a value that is neither
    # spelling" would have asserted one answer where the reference gives three (spec section 3.3).
    8: (
        "tests.conformance.test_playback_info:test_ac8_absent_null_and_empty_take_the_declared_default",
        "tests.conformance.test_playback_info:test_ac8_a_number_binds_to_the_ordinals_member",
        "tests.conformance.test_playback_info:test_ac8_an_ordinal_no_member_has_survives_to_the_wire_as_a_number",
        "tests.conformance.test_playback_info:test_ac8_a_value_that_binds_to_no_member_refuses_the_whole_body",
        "tests.unit.test_compat_model:test_an_ordinal_binds_by_the_declared_number_and_not_by_position",
        "tests.unit.test_compat_model:test_a_bool_is_not_an_ordinal",
        "tests.unit.test_compat_model:test_a_union_with_a_number_keeps_an_ordinal_no_member_has",
        # The key the refusal carries, which is what a client's error display shows.
        "tests.unit.test_compat_errors:test_a_nested_vocabulary_refusal_is_keyed_by_its_json_path",
        "tests.unit.test_compat_errors:test_the_position_is_an_offset_into_the_body_and_not_into_the_token",
        "tests.conformance.test_playback_info:test_a_nested_refusal_is_keyed_by_the_propertys_own_json_path",
    ),
    # **The criterion's own words are "the existing conformance suite is the proof", and a map
    # entry saying that is 010's AC-11 shape**: a claim about a suite with nothing named. These are
    # the tests that fail if a negotiation of an opened item moves - 008's own ladder rows, 011's
    # AC-15, the mechanism underneath (the trigger does not fire for an annotated source zero) and
    # the row T11 wrote, which asserts two whole bodies either side of the file's disappearance.
    9: (
        "tests.unit.test_media_decision:test_every_rung_of_the_ladder",
        "tests.conformance.test_playback_info:test_ac2_a_profile_that_accepts_the_source_answers_direct_play",
        "tests.conformance.test_playback_info:test_ac3_a_rejected_container_answers_a_url_with_both_streams_copied",
        "tests.conformance.test_playback_info:test_ac5_a_profile_that_can_play_nothing_is_flags_and_no_error_code",
        "tests.conformance.test_playback_info:test_ac15_a_direct_played_file_answers_what_it_answered_before",
        "tests.conformance.test_playback_info:test_a_file_gone_from_disk_since_the_scan_is_answered_from_what_the_scan_stored",
        "tests.unit.test_library_inspection:test_a_scanned_source_that_was_opened_does_not_fire_it",
        # The other half of that mechanism, and the one nothing held until audit 2026-09-04's M17:
        # where the trigger *does* fire on an item the scan opened, the file side still does
        # nothing - the prober is invoked zero times for a part that already carries an inspection.
        "tests.conformance.test_playback_info:test_a_part_the_scan_already_opened_is_not_re_opened_when_the_trigger_fires",
    ),
    # The prohibition, asserted on the response **bytes** of three routes rather than on the fields
    # a test remembered to name - and on the guard underneath, which is six functions and not one.
    10: (
        "tests.conformance.test_media_shapes:test_ac10_a_negotiation_of_another_item_moves_nothing_on_any_listing",
        "tests.conformance.test_media_shapes:test_ac10_negotiating_the_unopenable_item_itself_moves_nothing_either",
        "tests.unit.test_library_inspection:test_every_reader_of_an_inspection_answers_the_same_either_way",
        "tests.unit.test_library_inspection:test_the_transient_inspection_serialises_as_no_inspection_at_all",
        "tests.unit.test_library_inspection:test_the_one_source_row_that_cannot_answer_identically_is_one_no_scan_writes",
        # The invariant the prohibition rests on, asserted by making the wrong call fail: a stored
        # transient inspection makes the next scan skip the file for ever and empties the report.
        "tests.unit.test_library_inspection:test_store_refuses_the_inspection_unopened_produced",
        "tests.unit.test_library_inspection:test_what_storing_it_would_have_cost_is_the_file_never_being_opened_again",
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
    "008-playback-negotiation-and-delivery": FEATURE_008,
    "009-playlists": FEATURE_009,
    "010-conformance-harness": FEATURE_010,
    "011-subtitle-delivery": FEATURE_011,
    "012-negotiation-inputs": FEATURE_012,
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


#: English for the counts a definition of done can currently carry. Spelled out because that is how
#: every one of the twelve writes it, and a digit there would be the one spelling this cannot read
#: - which the assertion below says in its message rather than passing quietly.
NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight",
    9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    21: "twenty-one", 22: "twenty-two", 23: "twenty-three", 24: "twenty-four", 25: "twenty-five",
    26: "twenty-six", 27: "twenty-seven", 28: "twenty-eight", 29: "twenty-nine", 30: "thirty",
    31: "thirty-one", 32: "thirty-two", 33: "thirty-three", 34: "thirty-four", 35: "thirty-five",
}  # fmt: skip


def definition_of_done_opening(feature: str) -> str:
    """The first bullet of the feature's definition of done - the one that counts the criteria."""
    body = (SPECS / feature / "tasks.md").read_text(encoding="utf-8")
    section = body.split("## Definition of done", 1)[1].split("\n## ", 1)[0]
    bullets = re.split(r"^- \[[ x]\] ", section, flags=re.MULTILINE)
    return bullets[1] if len(bullets) > 1 else ""


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_the_definition_of_done_counts_the_criteria_that_exist(feature: str) -> None:
    """The count in a definition of done is a live claim, and this is what holds it to the map.

    Audit 2026-09-04's corrective task C9 found it stale in **ten of the twelve features** - 001
    said eleven against fourteen, 005 sixteen against twenty-five, 008 thirty-one against
    thirty-four - because the number is written once, by the closing task, and every criterion
    added afterwards moves it without anybody rereading that line. Three earlier corrective tasks
    each noticed and each left it, reading it as a record of the tick rather than as a claim.

    It is a claim: the box is `[x]` and the sentence is *"every acceptance criterion has a passing
    test - all N"*, which a reader checks coverage by. 007 T13 had already settled it in this
    repository's own voice, correcting its own route count from five to seven with a parenthetical
    saying so. This assertion is what stops the next criterion re-opening the class.
    """
    count = len(FEATURES[feature])
    word = NUMBER_WORDS[count]
    opening = definition_of_done_opening(feature)
    assert opening, f"{feature} has no definition of done bullet to check"
    #: Longest first, so "twenty-one" is read as itself and not as "twenty" followed by a stray
    #: word - which is the one way a wrong count could slip past a substring test.
    spellings = sorted(NUMBER_WORDS.values(), key=len, reverse=True)
    said = set(re.findall(r"\b(?:" + "|".join(spellings) + r")\b", opening.lower()))
    assert word in said, (
        f"{feature} has {count} acceptance criteria and the bullet that counts them says "
        f'{sorted(said) or "no number at all"} rather than "{word}":\n\n{opening.strip()}\n\n'
        f"A criterion was added or removed and that line still carries the old number. Correct "
        f"the count - it is a live claim about section 5, not a record of when the box was ticked."
    )
