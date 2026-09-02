# SPDX-License-Identifier: GPL-3.0-or-later
"""The differential engine, proven by mutation — 010 spec §6.

This feature is the thing that proves conformance, so it cannot be proven the way everything else
in this repository is. It is proven by **injecting defects on purpose**: the harness is correct if
it catches the ones that are put in front of it, and — the half that is easier to forget — if it
reports nothing when there is nothing to report. *"A harness with false positives gets ignored
within a week, and an ignored harness is worse than none."*

Every assertion here is a **count**. A substring assertion passes when the engine emits the right
finding buried in four hundred wrong ones, which is exactly the failure the `LENGTH` and `ORDER`
classes exist to prevent — so the two cases that guard against a cascade assert that the cascade is
not there, and both fail loudly when their guard is deleted.

No server, no socket, no clock: the engine is pure, which is why these run in the default CI job
where there is no Jellyfin and must not be one (010 plan §3, §6.11).

The four **paired bodies** under `differential_pairs/` are hand-written and not captured. A
captured pair proves the engine agrees with whatever the capture happened to hold, and anything
captured from the reference is somebody's library.

T4 extends this file with the two array kinds — `drawn` and `unordered`; T7 and T8 with the
identities, the report and the two-server guard.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.conformance

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIRS = Path(__file__).resolve().parent / "differential_pairs"


def _load_engine() -> Any:
    """`tools/` is a directory of standalone programs, not an importable package.

    Deliberately so: the probes and the harness keep working before any environment exists. Loading
    the module by path is the price, and it is the pattern `tests/conformance/test_routes.py` and
    `tests/conformance/test_universal_audio.py` already use.

    One line further than either of them, and it is not optional: the module is registered in
    `sys.modules` **before** it executes. `dataclasses` resolves a field's annotation by looking the
    defining module up by name, so a module that is not there yet fails on the first `@dataclass`
    — which neither existing by-path load hits, because neither module declares one.
    """
    path = REPO_ROOT / "tools" / "_differential.py"
    name = "atrium_differential_engine"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


engine = _load_engine()


# --------------------------------------------------------------------------------------------
# The paired bodies
# --------------------------------------------------------------------------------------------


def _pair(name: str) -> tuple[Any, Any, Any]:
    """One checked-in pair, as `(atrium, reference, rules)`."""
    document = json.loads((PAIRS / f"{name}.json").read_text(encoding="utf-8"))
    rules = engine.Rules(
        excused_fields=document.get("rules", {}).get("excused_fields", {}),
        drawn_arrays=document.get("rules", {}).get("drawn_arrays", {}),
        unordered_arrays=document.get("rules", {}).get("unordered_arrays", {}),
    )
    return _response(document["atrium"]), _response(document["reference"]), rules


def _response(side: dict[str, Any]) -> Any:
    return engine.Response(
        status=side["status"],
        headers=side.get("headers", {}),
        body=side.get("body"),
        raw=side.get("raw", "").encode("utf-8"),
    )


def _row(name: str, index: int) -> dict[str, Any]:
    """One row of a synthetic thousand-row page, distinct from every other by `Name`."""
    return {
        "Name": name,
        "Id": f"{index:032x}",
        "IndexNumber": index,
        "Type": "Movie",
        "IsFolder": False,
    }


def _page(count: int, server: str) -> dict[str, Any]:
    """A list envelope of `count` rows, whose identifiers are this server's own."""
    return {
        "Items": [_row(f"Film {index:04d}", index) for index in range(count)],
        "TotalRecordCount": count,
        "StartIndex": 0,
    }


#: What the page above needs excused: the identifiers, which the two servers derive differently by
#: design (behaviours §1.4) and which nothing in this project matches by bytes.
PAGE_RULES_POINTER = "/Items/-/Id"


# --------------------------------------------------------------------------------------------
# Does not cry wolf
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["bare_object", "list_envelope"])
def test_a_pair_that_differs_only_in_what_is_excused_reports_nothing(name: str) -> None:
    ours, theirs, rules = _pair(name)
    assert engine.compare(ours, theirs, rules) == ()


def test_the_delivery_pair_reports_nothing_under_its_own_rules() -> None:
    ours, theirs, rules = _pair("delivery_headers")
    assert engine.compare_headers(ours, theirs, rules) == ()
    assert engine.compare(ours, theirs, rules) == ()


def test_a_body_that_is_bytes_on_both_sides_is_not_byte_compared() -> None:
    """Spec §6 declines to byte-compare produced media, so `raw` is a named comparison's input.

    Three rows of spec §3.10 exist precisely because the difference is in the bytes — a progressive
    re-encode's header frame, burn-in, a subtitle playlist's decimal point. An engine that
    byte-compared `raw` would report every one of them as a sweep finding it cannot explain.
    """
    ours = engine.Response(200, {}, None, b"one stream of bytes")
    theirs = engine.Response(200, {}, None, b"a different stream entirely")
    assert engine.compare(ours, theirs) == ()


# --------------------------------------------------------------------------------------------
# The mutation table — one row per class
# --------------------------------------------------------------------------------------------


def test_a_removed_field_is_exactly_one_missing_key() -> None:
    ours, theirs, rules = _pair("bare_object")
    mutated = copy.deepcopy(ours.body)
    del mutated["ProductionYear"]
    found = engine.compare(engine.Response(200, {}, mutated), theirs, rules)
    assert [(one.klass, one.pointer) for one in found] == [
        (engine.Class.MISSING_KEY, "/ProductionYear")
    ]


def test_an_added_field_is_exactly_one_extra_key() -> None:
    ours, theirs, rules = _pair("bare_object")
    mutated = copy.deepcopy(ours.body)
    mutated["AtriumOnly"] = "a delta a client could discover"
    found = engine.compare(engine.Response(200, {}, mutated), theirs, rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.EXTRA_KEY, "/AtriumOnly")]


def test_an_integer_sent_as_a_string_is_exactly_one_type_difference() -> None:
    ours, theirs, rules = _pair("bare_object")
    mutated = copy.deepcopy(ours.body)
    mutated["ProductionYear"] = "1949"
    found = engine.compare(engine.Response(200, {}, mutated), theirs, rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.TYPE, "/ProductionYear")]
    assert found[0].note == "string against integer"


def test_a_changed_title_is_exactly_one_value_difference() -> None:
    ours, theirs, rules = _pair("bare_object")
    mutated = copy.deepcopy(ours.body)
    mutated["Name"] = "The Fourth Man"
    found = engine.compare(engine.Response(200, {}, mutated), theirs, rules)
    assert [(one.klass, one.pointer, one.atrium, one.reference) for one in found] == [
        (engine.Class.VALUE, "/Name", "The Fourth Man", "The Third Man")
    ]


def test_a_reordered_thousand_row_array_is_exactly_one_order_and_no_values() -> None:
    """The finding the whole design exists for.

    OQ-1 killed every join key the wire could have offered, so rows are compared by position — and
    a positional comparison that only knew about values would report this as a thousand value
    differences and say nothing about the one thing that actually differs. Delete the fingerprint
    step and this case reports hundreds of findings, which is why the assertion is a count.
    """
    rules = engine.Rules(excused_fields={PAGE_RULES_POINTER: "derived-identifier"})
    theirs = _page(1000, "reference")
    ours = _page(1000, "atrium")
    ours["Items"] = ours["Items"][500:] + ours["Items"][:500]
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [one.klass for one in found] == [engine.Class.ORDER]
    assert found[0].pointer == "/Items"
    assert engine.counts(found)[engine.Class.VALUE] == 0
    assert "1000 moved" in found[0].note


def test_a_shorter_array_is_exactly_one_length_and_no_findings_from_its_rows() -> None:
    """The cascade guard. Delete the length check and this case reports hundreds of findings.

    AC-2's very first run is this shape — one server resolves a multi-part film as two media
    sources and the other as one — and without the guard every real finding is buried under
    positional noise.
    """
    rules = engine.Rules(excused_fields={PAGE_RULES_POINTER: "derived-identifier"})
    theirs = _page(1000, "reference")
    ours = _page(999, "atrium")
    ours["TotalRecordCount"] = 1000
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.LENGTH, "/Items")]
    assert (found[0].atrium, found[0].reference) == (999, 1000)


def test_the_report_ranks_missing_keys_first() -> None:
    """AC-5, asserted on a mixed finding set rather than on a set that was already in order."""
    mixed = [
        engine.Difference(engine.Class.VALUE, "/Name"),
        engine.Difference(engine.Class.ORDER, "/Items"),
        engine.Difference(engine.Class.EXTRA_KEY, "/AtriumOnly"),
        engine.Difference(engine.Class.LENGTH, "/Items"),
        engine.Difference(engine.Class.MISSING_KEY, "/ProductionYear"),
        engine.Difference(engine.Class.TYPE, "/IsFolder"),
    ]
    assert [one.klass for one in engine.rank(mixed)] == [
        engine.Class.MISSING_KEY,
        engine.Class.EXTRA_KEY,
        engine.Class.TYPE,
        engine.Class.LENGTH,
        engine.Class.ORDER,
        engine.Class.VALUE,
    ]
    assert engine.counts(mixed)[engine.Class.MISSING_KEY] == 1
    assert set(engine.counts([])) == set(engine.Class), "a report should never guess a zero"


# --------------------------------------------------------------------------------------------
# What the measured documents force
# --------------------------------------------------------------------------------------------


def test_an_explicit_null_is_a_key_that_is_present() -> None:
    """`ChannelId` is an explicit `null` on every item — 208 of 208 — against the reference's own
    null-suppression setting `[probe: tools/probe_item_shapes.py, Jellyfin 10.11.11, 2026-08-27]`.

    So null-versus-absent is a measured distinction on the one endpoint the whole surface hangs
    off, and an engine that normalised a null away would report nothing on it.
    """
    ours = engine.Response(200, {}, {"Name": "x"})
    theirs = engine.Response(200, {}, {"Name": "x", "ChannelId": None})
    found = engine.compare(ours, theirs)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.MISSING_KEY, "/ChannelId")]


def test_a_boolean_is_not_an_integer() -> None:
    """`bool` is a subclass of `int` in Python, so an `isinstance` ladder in the obvious order
    reports `true` and `1` as the same type — on a surface whose flags are exactly what a decoder
    breaks on."""
    ours = engine.Response(200, {}, {"IsFolder": 1})
    theirs = engine.Response(200, {}, {"IsFolder": False})
    found = engine.compare(ours, theirs)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.TYPE, "/IsFolder")]
    assert found[0].note == "integer against boolean"


def test_an_integer_is_not_a_number() -> None:
    """Principle VIII: numeric type is part of the contract and only visible in the serialised
    form, which is where `0` and `0.0` differ."""
    found = engine.compare(
        engine.Response(200, {}, {"CommunityRating": 8}),
        engine.Response(200, {}, {"CommunityRating": 8.0}),
    )
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.TYPE, "/CommunityRating")]


def test_a_masked_field_still_reports_a_missing_key_under_a_reordering() -> None:
    """The mask keeps the key present and keeps its type, and this is why.

    Mask by deleting the key instead — the obvious reading of *"the row after the allowlist's
    masking"* — and a row where Atrium omits `Id` entirely fingerprints identically to the
    reference's row that carries it. The two arrays then compare **equal**, and the class the
    report ranks first is never reported at all.
    """
    rules = engine.Rules(excused_fields={PAGE_RULES_POINTER: "derived-identifier"})
    theirs = _page(4, "reference")
    ours = _page(4, "atrium")
    del ours["Items"][2]["Id"]
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [
        (engine.Class.MISSING_KEY, "/Items/2/Id")
    ]


def test_an_excused_field_still_reports_a_type_difference() -> None:
    """A `field` entry excuses the value. The key's presence and its JSON type are still compared
    (010 plan §6.3's table), so an identifier that became a number is still a finding."""
    rules = engine.Rules(excused_fields={"/Id": "derived-identifier"})
    found = engine.compare(
        engine.Response(200, {}, {"Id": 12345}),
        engine.Response(200, {}, {"Id": "c5a7b3d6e0843a7f1c92b4e8460d9f21"}),
        rules,
    )
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.TYPE, "/Id")]


def test_an_excused_field_excuses_its_subtree_and_never_a_longer_sibling_name() -> None:
    """Two halves of the same scoping rule.

    `ImageTags` is a map of content hashes, so the entry has to reach every value under it. And
    matching is segment by segment and never by string prefix, or an entry on `/Item` would
    silently excuse `/Items` — which is the whole surface.
    """
    rules = engine.Rules(excused_fields={"/ImageTags": "content-hash", "/Item": "not this one"})
    found = engine.compare(
        engine.Response(200, {}, {"ImageTags": {"Primary": "a"}, "Items": ["x"]}),
        engine.Response(200, {}, {"ImageTags": {"Primary": "b"}, "Items": ["y"]}),
        rules,
    )
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.VALUE, "/Items/0")]


# --------------------------------------------------------------------------------------------
# Totality, and the two things the pointer is not
# --------------------------------------------------------------------------------------------


def test_a_list_against_an_object_is_a_type_at_the_root() -> None:
    """The engine is total: any two decoded bodies compare, and it never raises on a difference."""
    found = engine.compare(engine.Response(200, {}, []), engine.Response(200, {}, {"Items": []}))
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.TYPE, "")]


def test_a_status_difference_is_one_finding_and_the_bodies_are_not_compared() -> None:
    """Plan §7 files this as *"a `VALUE` difference on the status"*, singular, and it has to be.

    A `404`'s problem details against a `200`'s item body share almost no keys, so walking on would
    bury the one fact that explains every other finding under fifty that do not.
    """
    _ours, theirs, rules = _pair("bare_object")
    refusal = engine.Response(404, {}, {"type": "about:blank", "status": 404})
    found = engine.compare(refusal, theirs, rules)
    assert [(one.klass, one.pointer, one.atrium, one.reference) for one in found] == [
        (engine.Class.VALUE, engine.STATUS_POINTER, 404, 200)
    ]


def test_header_names_are_matched_case_insensitively() -> None:
    """The delivery pair spells `Accept-Ranges` in two cases on purpose. HTTP says the name is
    case-insensitive and the two servers are different stacks, so an engine matching by bytes
    would report a finding about nothing on every delivery route."""
    ours, theirs, rules = _pair("delivery_headers")
    assert "accept-ranges" in ours.headers
    assert "Accept-Ranges" in theirs.headers
    assert engine.compare_headers(ours, theirs, rules) == ()


def test_a_header_one_server_sends_and_the_other_does_not_is_a_key_difference() -> None:
    ours, theirs, rules = _pair("delivery_headers")
    without = dict(ours.headers)
    del without["accept-ranges"]
    found = engine.compare_headers(engine.Response(200, without), theirs, rules)
    assert [(one.klass, one.pointer) for one in found] == [
        (engine.Class.MISSING_KEY, "header:accept-ranges")
    ]


def test_a_header_entry_excuses_a_header_and_never_the_body() -> None:
    """A `header:` pointer is not a JSON Pointer, and must never be matched as one.

    Parsed as one it yields **no** segments, which prefix-matches every pointer there is — so a
    single `header:Date` row would excuse the entire body of every case in the sweep, silently and
    on the class the report ranks first. The same entry is matched case-insensitively on both
    sides, because HTTP names are and an allowlist row is written by a person.
    """
    rules = engine.Rules(excused_fields={"header:Date": "wall-clock"})
    body = engine.compare(
        engine.Response(200, {}, {"Name": "here"}),
        engine.Response(200, {}, {"Name": "there"}),
        rules,
    )
    assert [(one.klass, one.pointer) for one in body] == [(engine.Class.VALUE, "/Name")]
    headers = engine.compare_headers(
        engine.Response(200, {"date": "Wed, 02 Sep 2026 09:14:03 GMT"}),
        engine.Response(200, {"Date": "Wed, 02 Sep 2026 09:41:57 GMT"}),
        rules,
    )
    assert headers == ()


def test_the_server_header_differs_on_every_response_and_spec_33_has_no_row_for_it() -> None:
    """A finding about the allowlist, asserted here because T2 is where it surfaces.

    `Server` is `Atrium/<version>` here against the reference's `Kestrel`, measured
    `[probe: tools/probe_routing.py, Jellyfin 10.11.11, 2026-08-28]` and recorded as a deliberate
    divergence in behaviours §4.1 — and 010 spec §3.3's allowlist carries no row for it. Without
    one, every case in the sweep reports the same value difference. T3 owns the entry; this asserts
    that it is needed, so the pair's own rule cannot be mistaken for decoration.
    """
    ours, theirs, _rules = _pair("delivery_headers")
    unexcused = engine.Rules(
        excused_fields={
            "header:date": "wall-clock",
            "header:x-response-time-ms": "behaviours 1.9",
            "header:etag": "content-hash",
        }
    )
    found = engine.compare_headers(ours, theirs, unexcused)
    assert [(one.klass, one.pointer, one.atrium, one.reference) for one in found] == [
        (engine.Class.VALUE, "header:server", "Atrium/0.1.0", "Kestrel")
    ]


# --------------------------------------------------------------------------------------------
# The excused arrays — `drawn` (AC-17)
# --------------------------------------------------------------------------------------------


def test_a_drawn_arrays_length_is_reported_and_the_shape_walk_still_runs() -> None:
    """**T2's finding, answered.** Plan §6.2 orders the length check first and says the rows are
    then *"not compared at all"*; step 4 says a `drawn` array still compares *"the row count, and
    every row's key set and types"*. On `/Items/{itemId}/Similar` — the only `drawn` array the
    project has measured — the two lengths **always** differ: the reference answers `limit + 4` on
    a movie seed where Atrium answers exactly `limit`, measured at 1, 5 and 20 on two seeds
    (behaviours §3.24). Applied in the plan's order the guard would delete AC-17 on the one
    endpoint AC-17 was written for.

    **The split T4 lands: the length difference suppresses the positional comparison and nothing
    else.** The count is still reported, because it is the only quantity of a drawn array L3 can
    still check and the divergence behind it is a known one (behaviours §3.24) rather than noise;
    the shape walk runs anyway, which is the next test.
    """
    ours, theirs, rules = _pair("drawn_array")
    assert len(ours.body["Items"]) + 4 == len(theirs.body["Items"]), "the measured N + 4"
    assert rules.drawn("/Items"), "the pair declares the array drawn"
    found = engine.compare(ours, theirs, rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.LENGTH, "/Items")]
    assert (found[0].atrium, found[0].reference) == (2, 6)
    assert "shape only" in found[0].note


def test_a_key_removed_from_a_drawn_array_is_reported_and_a_changed_value_is_not() -> None:
    """AC-17's mutation row, on the pair whose lengths differ on every real run.

    Delete the shape walk and the first assertion fails: the `LENGTH` finding alone comes back,
    and a `Similar` row that had stopped carrying `ProductionYear` would be invisible for ever.
    Delete the *value* suppression instead and the second fails, because every row of a draw
    carries a different film.
    """
    ours, theirs, rules = _pair("drawn_array")
    body = copy.deepcopy(ours.body)
    for row in body["Items"]:
        del row["ProductionYear"]
    body["Items"][0]["Name"] = "a title neither server sent"
    found = engine.compare(engine.Response(200, {}, body), theirs, rules)
    assert [(one.klass, one.pointer) for one in found] == [
        (engine.Class.LENGTH, "/Items"),
        (engine.Class.MISSING_KEY, "/Items/-/ProductionYear"),
    ]
    assert engine.counts(found)[engine.Class.VALUE] == 0


def test_a_drawn_arrays_shape_walk_is_position_free_because_a_draw_holds_other_items() -> None:
    """The correction inside the correction: the shape walk cannot pair row 0 with row 0.

    A null property is absent everywhere, on both servers, by one setting (behaviours §1.7
    `[source: src/Jellyfin.Extensions/Json/JsonDefaults.cs:33 @ v10.11.11]`), so a row's key set
    depends on **which item it holds** — `ProductionYear` is simply absent from an item that has
    none — and a draw guarantees the two sides hold different items (behaviours §3.23: four
    identical requests shared none).
    Pair by index and this case reports one `MISSING_KEY` and one `EXTRA_KEY` about nothing at
    all, on an array where every row is legitimately a different film. Reduced across the rows
    instead, the two shapes are the same and nothing is reported.
    """
    rules = engine.Rules(drawn_arrays={"/Items": "behaviours §3.23"})
    ours = {"Items": [{"Name": "a", "ProductionYear": 1967}, {"Name": "b"}]}
    theirs = {"Items": [{"Name": "c"}, {"Name": "d", "ProductionYear": 1958}]}
    assert (
        engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
        == ()
    )


def test_a_drawn_array_excuses_its_rows_and_never_the_envelope_around_them() -> None:
    """AC-17's *"the envelope's own properties"*: excusing an array excuses no part of the
    response around it."""
    ours, theirs, rules = _pair("drawn_array")
    body = copy.deepcopy(ours.body)
    body["TotalRecordCount"] = 41
    del body["StartIndex"]
    found = engine.compare(engine.Response(200, {}, body), theirs, rules)
    assert [(one.klass, one.pointer) for one in found] == [
        (engine.Class.MISSING_KEY, "/StartIndex"),
        (engine.Class.LENGTH, "/Items"),
        (engine.Class.VALUE, "/TotalRecordCount"),
    ]


def test_a_drawn_array_still_reports_a_type_difference_inside_a_row() -> None:
    """*"Same key, different JSON type"* is the pass that breaks decoders (spec §3.2), and a draw
    excuses no part of it: `"1967"` against `1967` is a finding on any endpoint."""
    rules = engine.Rules(drawn_arrays={"/Items": "behaviours §3.23"})
    ours = {"Items": [{"Name": "a", "ProductionYear": "1967"}]}
    theirs = {"Items": [{"Name": "b", "ProductionYear": 1958}]}
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [
        (engine.Class.TYPE, "/Items/-/ProductionYear")
    ]
    assert found[0].note == "string against integer"


def test_a_drawn_row_compares_the_type_of_a_nested_element_and_not_its_presence() -> None:
    """An empty `Genres` on one side and three genres on the other is *content* under a draw: the
    element pointer exists only because some row held a non-empty array. Its **type** is still
    compared, which is what catches a list of genre objects against a list of strings."""
    rules = engine.Rules(drawn_arrays={"/Items": "behaviours §3.23"})
    ours = {"Items": [{"Name": "a", "Genres": []}]}
    theirs = {"Items": [{"Name": "b", "Genres": ["Film Noir", "Crime"]}]}
    assert (
        engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
        == ()
    )
    typed = {"Items": [{"Name": "a", "Genres": [{"Name": "Film Noir"}]}]}
    found = engine.compare(engine.Response(200, {}, typed), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.TYPE, "/Items/-/Genres/-")]


# --------------------------------------------------------------------------------------------
# The excused arrays — `unordered` (AC-18)
# --------------------------------------------------------------------------------------------


def test_a_reordered_unordered_array_reports_nothing_at_all() -> None:
    """AC-18, and not even an `ORDER` finding.

    The ordering being compared is one the reference does not have: it appends no further key
    after most orderings, so its ties are engine-resolved (behaviours §3.6). Reporting the
    difference would be reporting Atrium doing what §3.6 says it does.
    """
    rules = engine.Rules(
        excused_fields={PAGE_RULES_POINTER: "derived-identifier"},
        unordered_arrays={"/Items": "behaviours §3.6"},
    )
    theirs = _page(200, "reference")
    ours = _page(200, "atrium")
    ours["Items"] = ours["Items"][100:] + ours["Items"][:100]
    assert (
        engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
        == ()
    )


def test_an_unordered_array_reordered_and_changed_reports_exactly_the_change() -> None:
    """The other half of the mutation row: excusing the order excuses nothing else."""
    rules = engine.Rules(
        excused_fields={PAGE_RULES_POINTER: "derived-identifier"},
        unordered_arrays={"/Items": "behaviours §3.6"},
    )
    theirs = _page(200, "reference")
    ours = _page(200, "atrium")
    ours["Items"] = ours["Items"][100:] + ours["Items"][:100]
    ours["Items"][0]["Name"] = "Film 0100 (renamed)"
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.VALUE, "/Items/0/Name")]


def test_an_unordered_page_that_lost_a_row_and_repeated_another_is_the_residue_only() -> None:
    """**The question plan §6.2 leaves open, and T4's answer to it.**

    Plan §9's risk row names *"the `LENGTH` cascade guard and the `ORDER` class"* as the mitigation
    for a positional comparison drowning the report, and neither fires on a page whose length is
    unchanged and whose rows are not a permutation. That page is measured rather than
    hypothetical: paging the reference's artist sorts *"loses and duplicates rows"* (behaviours
    §3.6), so one row arrives twice and another not at all, **at the same length**.

    The rows that match are removed and only the residue is compared, which is what makes this
    exactly two findings. Delete that and the positional fallback reports **ten** — every row of a
    rotated page differing in `Name` and `IndexNumber` — which is the noise the report cannot
    survive and the reason the assertion is a count.
    """
    rules = engine.Rules(
        excused_fields={PAGE_RULES_POINTER: "derived-identifier"},
        unordered_arrays={"/Items": "behaviours §3.6"},
    )
    theirs = _page(5, "reference")
    ours = _page(5, "atrium")
    ours["Items"] = [*ours["Items"][1:], copy.deepcopy(ours["Items"][1])]
    assert len(ours["Items"]) == len(theirs["Items"]), "the same length, which is the whole point"
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [
        (engine.Class.VALUE, "/Items/4/IndexNumber"),
        (engine.Class.VALUE, "/Items/4/Name"),
    ]


def test_an_unordered_array_of_another_length_is_one_length_and_the_rows_that_matched_nothing() -> (
    None
):
    """A lost row is a real difference and a `LENGTH` says so — and it suppresses no comparison,
    because a multiset needs no alignment to be compared."""
    rules = engine.Rules(
        excused_fields={PAGE_RULES_POINTER: "derived-identifier"},
        unordered_arrays={"/Items": "behaviours §3.6"},
    )
    theirs = _page(5, "reference")
    ours = _page(5, "atrium")
    del ours["Items"][2]
    ours["TotalRecordCount"] = 5
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.LENGTH, "/Items")]
    assert (found[0].atrium, found[0].reference) == (4, 5)
    assert found[0].note.endswith("against 1 the other way")


def test_a_drawn_entry_outranks_an_unordered_one_on_the_same_array() -> None:
    """A draw has no comparable values, which is strictly more than having no comparable order —
    so where both cover an array, the rows are not value-compared."""
    rules = engine.Rules(
        drawn_arrays={"/Items": "behaviours §3.23"},
        unordered_arrays={"/Items": "behaviours §3.6"},
    )
    ours = {"Items": [{"Name": "a"}, {"Name": "b"}]}
    theirs = {"Items": [{"Name": "c"}, {"Name": "d"}]}
    assert (
        engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
        == ()
    )


def test_an_excused_array_is_excused_where_it_is_and_nowhere_else() -> None:
    """The scoping rule of plan §6.3, on an array rather than on a field: `/Items` excused here is
    not `/MediaSources` excused there, and an entry on one endpoint's array is not an entry on
    another's. `resolve` is what keys them by endpoint; this is what the engine does with the
    mapping it is handed."""
    rules = engine.Rules(unordered_arrays={"/Items": "behaviours §3.6"})
    ours = {"Items": [{"N": 2}, {"N": 1}], "MediaSources": [{"N": 2}, {"N": 1}]}
    theirs = {"Items": [{"N": 1}, {"N": 2}], "MediaSources": [{"N": 1}, {"N": 2}]}
    found = engine.compare(engine.Response(200, {}, ours), engine.Response(200, {}, theirs), rules)
    assert [(one.klass, one.pointer) for one in found] == [(engine.Class.ORDER, "/MediaSources")]


def test_an_array_entry_names_the_array_and_never_a_row_inside_it() -> None:
    """`drawn` and `unordered` match the array whole. A prefix match would let an excused envelope
    excuse every row in it, which is the opposite of AC-17."""
    rules = engine.Rules(drawn_arrays={"/Items": "a fresh draw per request"})
    assert rules.drawn("/Items")
    assert rules.drawn("/Items/0") is None
    assert rules.drawn("/Items/0/Name") is None
