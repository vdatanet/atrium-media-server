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

T4 extended this file with the two array kinds — `drawn` and `unordered` — and T7 with the
identities, which are the half of the harness that has to be right before the sweep exists: a run
that authenticates once passes green while saying nothing about the 12 of 23 reads that answer
differently to a seat that can be refused. The report and the two-server guard are T8's.
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
    # And registered under its own file name too, because `tools/differential.py` imports the
    # engine as `_differential` on first use. Without the alias the suite would hold **two**
    # copies of one module, and `Class.LENGTH is Class.LENGTH` would be false across them - which
    # is exactly what the attribution of a known divergence turns on.
    sys.modules.setdefault("_differential", module)
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


# --------------------------------------------------------------------------------------------
# The identities a run authenticates as — 010 T7, spec §3.9, AC-14 and AC-15
# --------------------------------------------------------------------------------------------
#
# The sweep is T8's and the seats are proven before it, because the failure this feature is prone
# to is not a wrong comparison: it is a run that authenticated once, passed green, and said
# nothing about the 12 of 23 reads that answer differently to somebody who can be refused.
#
# Nothing here opens a socket. The roster is driven against a stub directory, which is the whole
# reason the lifecycle takes a client rather than a base URL.


def _load_module(filename: str, name: str) -> Any:
    """One more `tools/` module by path, with `tools/` reachable for the ones that import it."""
    tools = str(REPO_ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    path = REPO_ROOT / "tools" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


differential = _load_module("differential.py", "atrium_differential_cli")
allowlist = _load_module("_allowlist.py", "atrium_allowlist_for_identities")


#: A stock policy, wide enough that narrowing it is visible and detailed enough that dropping the
#: fields nobody touched is visible too. Only the two required properties of `UserPolicy` are
#: required on the wire `[spec: UpdateUserPolicy, UserPolicy]`, which is exactly why the seat has
#: to be built by mutating the account's own policy rather than by posting a fresh object.
PROVIDER = "Jellyfin.Server.Implementations.Users."

STOCK_POLICY = {
    "AuthenticationProviderId": PROVIDER + "DefaultAuthenticationProvider",
    "PasswordResetProviderId": PROVIDER + "DefaultPasswordResetProvider",
    "IsAdministrator": False,
    "EnableAllFolders": True,
    "EnabledFolders": [],
    "EnableMediaPlayback": True,
    "EnableVideoPlaybackTranscoding": True,
    "EnableAudioPlaybackTranscoding": True,
    "EnablePlaybackRemuxing": True,
    "MaxActiveSessions": 3,
    "EnableContentDeletion": False,
}

LIBRARY = "f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1"


class FakeDirectory:
    """The four calls `Roster` makes of a client, and a log of every one of them.

    `tools/_probe.py`'s `Server` is what a real run passes; this is the same four methods over a
    dictionary, so the lifecycle can be asserted without a server the suite is forbidden to have.
    """

    def __init__(
        self,
        users: Any = (),
        policy_status: int = 204,
        delete_status: int = 204,
        create_raises: str = "",
    ) -> None:
        self.users = [dict(user) for user in users]
        self.policy_status = policy_status
        self.delete_status = delete_status
        self.create_raises = create_raises
        self.calls: list[tuple[str, str]] = []
        self.policies: dict[str, Any] = {}
        self.passwords: dict[str, str] = {}
        self._next = 0

    def get(self, path: str, **params: Any) -> Any:
        self.calls.append(("GET", path))
        if path == "/Users":
            return [dict(user) for user in self.users]
        user_id = path.rsplit("/", 1)[1]
        for user in self.users:
            if user["Id"] == user_id:
                return dict(user, Policy=dict(STOCK_POLICY))
        raise AssertionError(f"no such user: {user_id}")

    def post(self, path: str, body: Any = None, **params: Any) -> Any:
        self.calls.append(("POST", path))
        assert path == "/Users/New", path
        if self.create_raises:
            raise RuntimeError(self.create_raises)
        self._next += 1
        user_id = f"{self._next:032x}"
        self.users.append({"Id": user_id, "Name": body["Name"]})
        self.passwords[body["Name"]] = body["Password"]
        return {"Id": user_id, "Name": body["Name"]}

    def post_raw(self, path: str, body: Any = None, **params: Any) -> Any:
        self.calls.append(("POST", path))
        assert path.endswith("/Policy"), path
        self.policies[path.split("/")[2]] = body
        return self.policy_status, {}, b"" if self.policy_status == 204 else b"refused"

    def delete_raw(self, path: str, **params: Any) -> Any:
        self.calls.append(("DELETE", path))
        user_id = path.rsplit("/", 1)[1]
        if self.delete_status in (200, 204):
            self.users = [user for user in self.users if user["Id"] != user_id]
        return self.delete_status, {}, b""

    # -- what the assertions read ------------------------------------------------------------

    def named(self, name: str) -> Any:
        return next((user for user in self.users if user["Name"] == name), None)

    def deletes(self) -> list[str]:
        return [path for method, path in self.calls if method == "DELETE"]

    def creations(self) -> list[str]:
        return [path for method, path in self.calls if method == "POST" and path == "/Users/New"]


def _administrator() -> Any:
    return differential.Identity(
        name="administrator",
        token="a token the run borrowed",
        user_id="0" * 32,
        created_by_the_run=False,
    )


def _sign_in(directory: FakeDirectory) -> Any:
    def sign_in(username: str, password: str) -> tuple[str, str]:
        user = directory.named(username)
        assert user is not None, f"{username} was asked to sign in and does not exist"
        assert directory.passwords[username] == password
        return f"token-for-{username}", user["Id"]

    return sign_in


def _roster(directory: FakeDirectory, *roles: Any, library: str = LIBRARY) -> Any:
    return differential.Roster(
        directory,
        _administrator(),
        roles or (differential.Role.ADMINISTRATOR, differential.Role.RESTRICTED),
        library_id=library,
        sign_in=_sign_in(directory),
    )


def test_the_role_values_are_the_strings_the_request_cases_are_written_against() -> None:
    """T6 wrote 84 cases against `_allowlist.ROLES`, so a value that drifts here narrows them.

    An `identities:` naming a seat no `Role` spells resolves to nothing, and `identities_for`
    would return an empty tuple — a case silently not run, which is this feature's own failure
    mode wearing a different hat.
    """
    assert tuple(role.value for role in differential.Role) == allowlist.ROLES


def test_a_one_identity_run_is_a_shorter_loop_and_not_a_different_code_path() -> None:
    """AC-14 from the other end: the case decides which seats it is meaningful for, out of the
    ones the run actually has, so a roster of one narrows the answer rather than bypassing it."""
    directory = FakeDirectory()
    with _roster(directory, differential.Role.ADMINISTRATOR) as roster:
        assert roster.names == ("administrator",)
        case = allowlist.RequestCase(
            id="both-seats",
            endpoint="GET /Items",
            query="",
            body="none",
            content_type="none",
            anchors=(),
            identities=("administrator", "restricted"),
            needs=(),
            what_it_is_for="a case meaningful for two seats",
        )
        assert case.identities_for(roster.names) == ("administrator",)
    with _roster(directory) as roster:
        assert roster.names == ("administrator", "restricted")
        assert case.identities_for(roster.names) == ("administrator", "restricted")


def test_a_seat_that_already_exists_refuses_the_run_and_names_it() -> None:
    """AC-15's precondition. Delete the `preflight` call in `__enter__` and this fails.

    The refusal has to name the account, because the operator's next action is to look at it and
    decide whether a run is in flight or a killed one left it behind.
    """
    name = differential.seat_name(differential.Role.RESTRICTED)
    directory = FakeDirectory(users=[{"Id": "b" * 32, "Name": name}])
    with pytest.raises(differential.SeatError) as refusal, _roster(directory):
        raise AssertionError("the run started with a seat already on the server")
    assert name in str(refusal.value)
    assert "b" * 32 in str(refusal.value)
    assert directory.creations() == [], "the pre-flight ran after something was created"
    assert directory.deletes() == [], "the pre-flight deleted an account it does not own"


def test_the_pre_flight_asks_for_every_user_and_not_a_filtered_page() -> None:
    """`isHidden` and `isDisabled` are optional *filters* on `GET /Users` `[spec: GetUsers]`, and
    the leftover most likely to be there is the one an earlier run disabled instead of deleting.
    A pre-flight that passed either would be blind to exactly that seat."""
    directory = FakeDirectory()
    differential.preflight(directory, [differential.Role.RESTRICTED])
    assert directory.calls == [("GET", "/Users")]


def test_a_run_that_created_a_seat_tears_it_down_on_the_exception_path() -> None:
    """The 28-playlist lesson, asserted rather than promised.

    On 2026-09-01 the reference server 009's probes had run against still held 28 playlists they
    had created; every one of those probes said in its own docstring that it deleted them. So the
    teardown is a test and not a sentence: raise inside the run, and every `Identity` whose
    `created_by_the_run` is true is still deleted.
    """
    directory = FakeDirectory()
    roles = (
        differential.Role.ADMINISTRATOR,
        differential.Role.RESTRICTED,
        differential.Role.PLAYBACK_DENIED,
    )
    fell_over = pytest.raises(RuntimeError, match="the sweep fell over")
    with fell_over, _roster(directory, *roles) as roster:
        made = {identity.user_id for identity in roster.created}
        assert len(made) == 2
        raise RuntimeError("the sweep fell over")
    assert sorted(directory.deletes()) == sorted(f"/Users/{user_id}" for user_id in made)
    assert directory.users == [], "a seat the run created survived it"


def test_the_administrator_is_never_torn_down() -> None:
    """`created_by_the_run` is a field of the identity for this reason: the administrator is
    somebody's real account, borrowed from `.env`, and a teardown that iterated the run instead
    of the identities would delete it."""
    directory = FakeDirectory()
    with _roster(directory) as roster:
        assert roster[differential.Role.ADMINISTRATOR].created_by_the_run is False
    assert f"/Users/{'0' * 32}" not in directory.deletes()


def test_a_seat_whose_policy_is_refused_stops_the_run_and_leaves_nothing_behind() -> None:
    """A run that cannot seat an identity refuses rather than proceeding with fewer.

    The half-made account is the interesting half: an account created and then not narrowed is an
    *ordinary* account, so a run that carried on would sweep as a second administrator and report
    parity it never measured — and the next run's pre-flight would refuse on the leftover.
    """
    directory = FakeDirectory(policy_status=403)
    with pytest.raises(differential.SeatError, match="403"), _roster(directory):
        raise AssertionError("the run started with a seat that has no policy")
    assert directory.users == [], "the half-made seat was left on the server"


def test_a_roster_that_cannot_make_a_seat_refuses_before_contacting_anything() -> None:
    """The restricted seat needs the library it may open, and without one it cannot be made.

    Refusing here rather than dropping the seat is the whole of spec §3.9: a run that quietly
    became an administrator-only run reports a surface of which 12 of 23 reads answer differently
    to somebody else, and says nothing about it.
    """
    directory = FakeDirectory()
    refusal = pytest.raises(differential.SeatError, match="rather than proceeding with fewer")
    with refusal, _roster(directory, library=""):
        raise AssertionError("the run started without the library the seat needs")
    assert directory.calls == [], "something was contacted before the refusal"


def test_a_seat_left_behind_by_a_successful_run_is_raised_and_not_logged() -> None:
    """A cleanup that reports success while leaking is the failure this whole section is about."""
    directory = FakeDirectory(delete_status=500)
    with pytest.raises(differential.SeatError, match="could not destroy"), _roster(directory):
        pass


def test_a_leak_on_the_exception_path_never_masks_the_failure_that_caused_it(
    capsys: Any,
) -> None:
    """The one place the teardown does not raise: the run is already failing, and replacing that
    exception with the teardown's own would hide why the run stopped."""
    directory = FakeDirectory(delete_status=500)
    with pytest.raises(RuntimeError, match="the reference stopped answering"), _roster(directory):
        raise RuntimeError("the reference stopped answering")
    assert "could not destroy" in capsys.readouterr().err


# -- the two policies -------------------------------------------------------------------------


def test_the_restricted_seat_is_narrowed_from_its_own_policy_and_not_from_a_fresh_object() -> None:
    """`POST /Users/{userId}/Policy` takes a whole `UserPolicy` and requires two of its 44
    properties `[spec: UpdateUserPolicy, UserPolicy]`, so a body naming only the folder pair is a
    complete policy in which everything else is whatever an absent value binds to. Read the
    account's policy, mutate it, post it back — which is what
    `tools/probe_restricted_surface.py` already does."""
    directory = FakeDirectory()
    with _roster(directory) as roster:
        seat = roster[differential.Role.RESTRICTED]
        written = directory.policies[seat.user_id]
    assert written["EnableAllFolders"] is False
    assert written["EnabledFolders"] == [LIBRARY]
    assert written["MaxActiveSessions"] == 3, "a property nobody touched was dropped"
    assert written["AuthenticationProviderId"] == STOCK_POLICY["AuthenticationProviderId"]


def test_the_denied_seat_denies_the_three_permissions_behaviours_2_21_names() -> None:
    """**The finding this task turned up, asserted so it cannot be undone by a tidier reading.**

    [Plan §6.7](../../specs/010-conformance-harness/plan.md) asks for the seat with *"the
    playback-processing permission denied"*, singular, and there are three of them. Behaviours
    §2.21 measured what each does: at negotiation they are **one gate** — `SupportsTranscoding`
    drops only when all three are denied, and any single denial changes nothing — and at delivery
    two of them are read per stream, from a video request only. A seat denying one is therefore
    observably a permitted seat on every negotiation both servers answer.
    """
    directory = FakeDirectory()
    roles = (differential.Role.ADMINISTRATOR, differential.Role.PLAYBACK_DENIED)
    with _roster(directory, *roles) as roster:
        seat = roster[differential.Role.PLAYBACK_DENIED]
        written = directory.policies[seat.user_id]
    assert [written[permission] for permission in differential.PLAYBACK_PROCESSING_PERMISSIONS] == [
        False,
        False,
        False,
    ]


def test_the_denied_seat_leaves_the_permission_whose_name_says_it_is_the_one() -> None:
    """`EnableMediaPlayback` is read by no playback route at all — only by the item DTO's
    `PlayAccess` and by the remote-control `Play` command (behaviours §2.21). Denying it would
    build a seat that looks denied, plays like a permitted one, and moves `PlayAccess` on every
    item body the sweep compares — a difference nobody asked for, in the seat that exists to
    measure one."""
    directory = FakeDirectory()
    roles = (differential.Role.ADMINISTRATOR, differential.Role.PLAYBACK_DENIED)
    with _roster(directory, *roles) as roster:
        written = directory.policies[roster[differential.Role.PLAYBACK_DENIED].user_id]
    assert written[differential.NEGOTIATION_INERT_PERMISSION] is True


def test_the_denied_seat_keeps_every_library_it_can_open() -> None:
    """It has to reach a video item to be compared at all: the delivery-time refusal is a video
    request (behaviours §2.21). A seat narrowed like the restricted one would answer the same
    refusal on both servers for the wrong reason — 006 T5's hostile-path test, here."""
    directory = FakeDirectory()
    roles = (differential.Role.ADMINISTRATOR, differential.Role.PLAYBACK_DENIED)
    with _roster(directory, *roles) as roster:
        written = directory.policies[roster[differential.Role.PLAYBACK_DENIED].user_id]
    assert written["EnableAllFolders"] is True
    assert written["EnabledFolders"] == []


def test_a_seat_name_is_fixed_so_the_next_run_can_recognise_the_wreckage() -> None:
    """A random name would make the pre-flight impossible to write: nothing would identify what a
    killed run left. Fixed is the property, and it is why AC-15's refusal can exist."""
    assert differential.seat_name(differential.Role.RESTRICTED) == "atrium-differential-restricted"
    assert (
        differential.seat_name(differential.Role.PLAYBACK_DENIED)
        == "atrium-differential-playback-denied"
    )


def test_the_seat_password_is_generated_per_run_and_never_a_constant() -> None:
    """Two runs never share a credential, and nothing in this repository holds one."""
    first, second = FakeDirectory(), FakeDirectory()
    with _roster(first):
        pass
    with _roster(second):
        pass
    name = differential.seat_name(differential.Role.RESTRICTED)
    assert first.passwords[name] != second.passwords[name]
    assert len(first.passwords[name]) >= 24


# --------------------------------------------------------------------------------------------
# The run loop, the report and the two-server guard — 010 T8, spec §3.2, §3.4, AC-3, AC-5, AC-14,
# AC-16
# --------------------------------------------------------------------------------------------
#
# The report is where this feature can lie. A run that could not reach a server, could not seat an
# identity or skipped a case produces a document that looks exactly like a clean one unless it says
# otherwise — so every test below asserts what the report says it did **not** do, and each of the
# three guards is proven by deleting it.
#
# Nothing here opens a socket. The wire is a stub, which is why `Wire` takes a base URL and the
# sweep takes an issuer.


ENDPOINT = differential.Endpoint(method="GET", path="/Items", level="L3", feature="005")
SECOND_ENDPOINT = differential.Endpoint(method="GET", path="/UserViews", level="L2", feature="005")


def _case(
    case_id: str,
    endpoint: str = "GET /Items",
    identities: tuple[str, ...] = (),
    needs: tuple[str, ...] = (),
    query: str = "",
    body: str = "none",
    content_type: str = "none",
    anchors: tuple[Any, ...] = (),
) -> Any:
    return allowlist.RequestCase(
        id=case_id,
        endpoint=endpoint,
        query=query,
        body=body,
        content_type=content_type,
        anchors=anchors,
        identities=identities,
        needs=needs,
        what_it_is_for="one case, written by hand so the sweep can be driven without a server",
    )


def _seat(role: str = "administrator") -> Any:
    return differential.Seat(
        role=role,
        atrium=differential.Identity(
            name=role, token=f"atrium-{role}", user_id="a" * 32, created_by_the_run=False
        ),
        reference=differential.Identity(
            name=role, token=f"reference-{role}", user_id="b" * 32, created_by_the_run=False
        ),
    )


class FakeWire:
    """One server, recorded. The sweep never learns it is not a socket."""

    def __init__(self, side: str, log: list[tuple[str, str, str]], body: Any = None) -> None:
        self.side = side
        self.log = log
        self.body = body if body is not None else {"Items": [], "TotalRecordCount": 0}
        self.sent: list[dict[str, Any]] = []

    def as_seat(self, token: str) -> FakeWire:
        return self

    def request(
        self,
        method: str,
        path: str,
        query: str = "",
        body: Any = None,
        content_type: str = "",
    ) -> Any:
        self.log.append((self.side, method, path))
        self.sent.append(
            {
                "method": method,
                "path": path,
                "query": query,
                "body": body,
                "content_type": content_type,
            }
        )
        return engine.Response(
            status=200,
            headers={"Content-Type": "application/json", "Server": self.side},
            body=copy.deepcopy(self.body),
            raw=b"{}",
        )


def _issuers(
    cases: list[Any], log: list[tuple[str, str, str]], bodies: tuple[Any, Any] = (None, None)
) -> tuple[dict[str, Any], dict[str, FakeWire]]:
    wires = {
        "atrium": FakeWire("atrium", log, bodies[0]),
        "reference": FakeWire("reference", log, bodies[1]),
    }
    issuers = {
        side: differential.Issuer(side, {"administrator": wire, "restricted": wire}, cases)
        for side, wire in wires.items()
    }
    return issuers, wires


def _report(**overrides: Any) -> Any:
    """A `RunReport` with everything a rendered report needs and nothing a server has to supply."""
    fields: dict[str, Any] = {
        "identities": ("administrator", "restricted"),
        "cases": 84,
        "comparisons": (),
        "named_run": (),
        "named_outstanding": (),
        "endpoints": (ENDPOINT,),
        "provenance": (
            ("date", "2026-09-02"),
            ("atrium sha", "0123456789ab"),
            ("reference version", "10.11.11"),
        ),
        "unused_entries": (),
    }
    fields.update(overrides)
    return differential.RunReport(**fields)


def _ran(identity: str = "administrator", **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "endpoint": ENDPOINT.key,
        "level": ENDPOINT.level,
        "case": "default",
        "identity": identity,
    }
    fields.update(overrides)
    return differential.Comparison(**fields)


# -- the two-server guard --------------------------------------------------------------------


def test_a_reference_that_is_actually_an_atrium_is_refused_by_the_server_header() -> None:
    """The guard `_probe.py` cannot be, and the reason it cannot (plan §6.12).

    `connect` refuses a server whose `ProductName` does not name Jellyfin, which is right for its
    own job — the near miss it exists to catch is an Emby. Atrium answers `"Jellyfin Server"`
    there on purpose (behaviours §4.1), so that check admits a run pointed at two Atriums: a
    comparison of this project with itself, reporting parity it never measured. The second half of
    this test is the half that matters — the pair the `Server` header refuses is a pair
    `ProductName` waves through.
    """
    ours = {"Server": "Atrium/0.1.0", "Content-Type": "application/json"}
    also_atrium = {"Server": "Atrium/0.1.0"}
    a_real_reference = {"server": "Kestrel"}

    with pytest.raises(differential.GuardError) as refused:
        differential.check_two_servers(ours, also_atrium)
    assert "Atrium" in str(refused.value)

    # The wrong guard, asked of the very pair the right one just refused.
    public = {"ProductName": "Jellyfin Server", "Version": "10.11.11"}
    assert differential.product_name(public) == "Jellyfin Server"
    assert differential.product_name(public) == differential.product_name(dict(public))

    # And the right pair passes, with the header name in the other case: HTTP says it may be.
    differential.check_two_servers(ours, a_real_reference)


def test_two_references_are_refused_as_well_as_two_atriums() -> None:
    """Both directions, because both report parity about nothing."""
    with pytest.raises(differential.GuardError) as refused:
        differential.check_two_servers({"Server": "Kestrel"}, {"Server": "Kestrel"})
    assert "--atrium" in str(refused.value)


# -- the report says what it did not ask -------------------------------------------------------


def test_a_report_built_from_one_identity_says_one_identity() -> None:
    """AC-14: the coverage line names what ran, and never the surface.

    A run that authenticated once measures one row of a two-row table — 12 of 23 reads answer
    differently to a restricted non-administrator — so a report that said *"59 endpoints"* and
    nothing about the seat would be the shape of claim this feature exists to prevent.
    """
    report = _report(identities=("administrator",), comparisons=(_ran(),))
    assert report.coverage() == (("administrator", 1, 0),)

    text = differential.render(report)
    assert "1 (administrator)" in text
    assert "| administrator | 1 | 0 |" in text
    # And it names the seats it did not have, by name, in the section a reader reaches first.
    conclusions = text.split("## Coverage")[0]
    assert "restricted" in conclusions
    assert "playback-denied" in conclusions
    assert "12 of twenty-three" in conclusions or "Twelve of twenty-three" in conclusions


def test_a_run_with_an_outstanding_named_comparison_is_not_clean() -> None:
    """AC-16: an unrun named comparison blocks the run, and the report names it and its need.

    Every difference here is triaged — there are none — and every declared case was issued. The
    only thing missing is one of the twenty differences a sweep cannot raise. Delete the named
    half of `is_clean` and this passes, which is the failure this feature exists to prevent: one
    directory away from the CI job that reported green because it ran nothing (008 T18).
    """
    outstanding = (
        (
            "playlist-entries-a-reader-cannot-reach",
            "fixture needs a reference instance and --fixture was not asked for",
        ),
    )
    report = _report(comparisons=(_ran(),), named_outstanding=outstanding)

    assert not report.is_clean()
    text = differential.render(report)
    assert "playlist-entries-a-reader-cannot-reach" in text
    assert "--fixture was not asked for" in text
    assert "THIS RUN IS NOT CLEAN." in text

    # The same run with nothing outstanding is clean, so the assertion above is about the named
    # half and not about something else being wrong.
    assert _report(comparisons=(_ran(),)).is_clean()


def test_a_case_that_could_not_be_issued_is_not_a_case_that_agreed() -> None:
    """A declared case the run did not issue keeps it from being clean, and says why.

    Spec §3.4 names two conditions; this is the third and it is the same fact wearing the sweep's
    clothes. A comparison that did not happen is not a comparison that agreed — and against a
    server with no fixture, or a seat that could not be made, that is most of them.
    """
    skipped = _ran(
        identity="restricted",
        unreachable="{itemId} has no anchor in request-cases.yaml",
    )
    report = _report(comparisons=(_ran(), skipped))
    assert not report.is_clean()
    assert report.unasked == (skipped,)

    text = differential.render(report)
    assert "## Cases this run did not ask, and why" in text
    assert "has no anchor in request-cases.yaml" in text
    assert "did not agree; it was not asked" in text


def test_the_report_ranks_missing_keys_first_in_its_own_table() -> None:
    """AC-5, at the report rather than at the engine: the order of the rows, and the label."""
    kinds = engine.Class
    findings = (
        engine.Difference(kinds.VALUE, "/Name", "here", "there"),
        engine.Difference(kinds.EXTRA_KEY, "/Extra", "ours", None),
        engine.Difference(kinds.MISSING_KEY, "/Missing", None, "theirs"),
    )
    report = _report(comparisons=(_ran(differences=findings),))
    text = differential.render(report)

    assert "Missing keys        (1)   <-- read these first" in text
    table = text.split("## Differences, missing keys first")[1]
    order = [line.split("|")[1].strip() for line in table.splitlines() if line.startswith("| ")]
    assert order[1:4] == ["MISSING_KEY", "EXTRA_KEY", "VALUE"]


def test_the_declared_conformance_level_is_printed_beside_every_endpoint() -> None:
    """*"What the gate changed"* §2: the `level` column nothing has ever checked.

    The eight `level: L3` rows are the only ones in this repository whose declared level this
    program is the only thing that can pay for, so the report prints the declaration beside what
    the run actually compared — including the endpoints it compared not at all.
    """
    report = _report(comparisons=(_ran(),), endpoints=(ENDPOINT, SECOND_ENDPOINT))
    text = differential.render(report)
    assert "| `GET /Items` | L3 | yes |" in text
    assert "| `GET /UserViews` | L2 | **no** |" in text


# -- the run loop ------------------------------------------------------------------------------


def test_the_two_servers_are_asked_back_to_back_per_case_and_never_one_sweep_then_the_other() -> (
    None
):
    """Plan §6.1: seconds matter to a draw and minutes matter to every clock-derived field.

    A harness that swept one server and then the other would compare answers taken minutes apart,
    which manufactures differences rather than finding them.
    """
    cases = [_case("default"), _case("second")]
    log: list[tuple[str, str, str]] = []
    issuers, _wires = _issuers(cases, log)
    differential.sweep(
        [ENDPOINT],
        cases,
        [],
        [_seat()],
        issuers,
        differential.Inputs(roles=("administrator",)),
        set(),
    )
    assert [side for side, _method, _path in log] == [
        "atrium",
        "reference",
        "atrium",
        "reference",
    ]


def test_the_identity_loop_is_outermost_so_a_reader_can_scan_one_seat_at_a_time() -> None:
    """Plan §6.1, and it is what makes a one-seat run a shorter loop over the same code."""
    cases = [_case("default")]
    log: list[tuple[str, str, str]] = []
    issuers, _wires = _issuers(cases, log)
    seats = [_seat("administrator"), _seat("restricted")]
    comparisons = differential.sweep(
        [ENDPOINT, SECOND_ENDPOINT],
        [*cases, _case("views", endpoint="GET /UserViews")],
        [],
        seats,
        issuers,
        differential.Inputs(roles=("administrator", "restricted")),
        set(),
    )
    assert [(c.identity, c.endpoint) for c in comparisons] == [
        ("administrator", "GET /Items"),
        ("administrator", "GET /UserViews"),
        ("restricted", "GET /Items"),
        ("restricted", "GET /UserViews"),
    ]


def test_a_case_meaningful_for_no_seat_this_run_has_is_reported_and_not_dropped() -> None:
    """The failure mode this feature is prone to, made visible instead of silent.

    A case naming only the `playback-denied` seat, in a run that has no such seat, is a question
    nobody asked. Dropping it would make a two-seat run look like a sweep of the surface.
    """
    cases = [_case("denied-only", identities=("playback-denied",))]
    log: list[tuple[str, str, str]] = []
    issuers, _wires = _issuers(cases, log)
    comparisons = differential.sweep(
        [ENDPOINT],
        cases,
        [],
        [_seat()],
        issuers,
        differential.Inputs(roles=("administrator",)),
        set(),
    )
    assert log == []
    assert len(comparisons) == 1
    assert "no seat in this run" in comparisons[0].unreachable
    assert "playback-denied" in comparisons[0].unreachable


def test_a_case_that_needs_a_fixture_instance_is_outstanding_with_that_reason() -> None:
    """Plan §6.5, ADR-0007: the dependency buys coverage, and its absence costs it and says so."""
    cases = [_case("multi-part", needs=("fixture",))]
    log: list[tuple[str, str, str]] = []
    issuers, _wires = _issuers(cases, log)
    comparisons = differential.sweep(
        [ENDPOINT],
        cases,
        [],
        [_seat()],
        issuers,
        differential.Inputs(roles=("administrator",), fixture_asked=True),
        set(),
    )
    assert log == []
    assert "reference instance" in comparisons[0].unreachable
    assert "010 T9" in comparisons[0].unreachable


def test_an_anchor_names_a_row_of_each_servers_own_listing_and_never_one_identifier() -> None:
    """Plan §6.1.1: the two servers derive identifiers differently by design (behaviours §1.4).

    The anchor is resolved against **each** server separately, so the two requests name two
    different items on purpose — which is the only way one case can address the same row twice.
    """
    listing = _case("movies-by-sort-name")
    anchored = _case(
        "bare-item",
        endpoint="GET /Items/{itemId}",
        anchors=(
            allowlist.Anchor(
                parameter="itemId",
                kind="listing",
                endpoint="GET /Items",
                case="movies-by-sort-name",
                at="0",
            ),
        ),
    )
    log: list[tuple[str, str, str]] = []
    issuers, wires = _issuers(
        [listing, anchored],
        log,
        bodies=({"Items": [{"Id": "ours"}]}, {"Items": [{"Id": "theirs"}]}),
    )
    seat = _seat()
    assert issuers["atrium"].fill(anchored, seat) == "/Items/ours"
    assert issuers["reference"].fill(anchored, seat) == "/Items/theirs"
    assert wires["atrium"].sent[0]["path"] == "/Items"


def test_a_userid_in_a_path_is_the_identitys_own_and_never_an_anchor() -> None:
    """Plan §6.1.1 in as many words, and it differs per server because a seat is an account."""
    case = _case("configuration", endpoint="POST /Users/{userId}/Configuration")
    issuers, _wires = _issuers([case], [])
    assert issuers["atrium"].fill(case, _seat()) == "/Users/" + "a" * 32 + "/Configuration"
    assert issuers["reference"].fill(case, _seat()) == "/Users/" + "b" * 32 + "/Configuration"


def test_a_case_that_substitutes_a_password_this_run_never_saw_is_unreachable_not_wrong() -> None:
    """`POST /Users/AuthenticateByName`'s body *is* the seat's credentials, and `Identity` has none.

    A created seat's password is the roster's, which is why `credentials_for` exists; the
    administrator's is the operator's, and a run that authenticated by token never saw one. The
    honest answer is a case reported unreachable with the reason, not a request with the literal
    text `<identity.password>` in it.
    """
    seat = _seat()
    assert differential.substitute("<identity.user_id>", seat, "atrium") == "a" * 32
    with pytest.raises(differential.UnreachableError) as refused:
        differential.substitute('{"Pw": "<identity.password>"}', seat, "reference")
    assert "identity.password" in str(refused.value)


# -- what the allowlist excuses, and what it merely explains ------------------------------------


def test_a_length_on_a_drawn_array_is_reported_with_the_argument_that_already_covers_it() -> None:
    """T4's inheritance: `Similar` answers `limit + 4` rows on a movie seed, on every run.

    The count stays compared and permanently reported — excusing it would leave the endpoint with
    nothing measured at all — and the report prints behaviours §3.24 beside it, because a reader
    who does not see the argument will try to fix it.
    """
    entry = allowlist.Entry(
        kind="drawn",
        endpoint="GET /Items/{itemId}/Similar",
        pointer="/Items",
        case="*",
        reason="a fresh draw per request",
        because="behaviours §3.23",
        since="2026-09-02",
    )
    length = engine.Difference(engine.Class.LENGTH, "/Items", 2, 6, note="2 against 6")
    assert differential.attribute(length, [entry]) == "behaviours §3.23"

    report = _report(comparisons=(_ran(attributed=((length, "behaviours §3.23"),)),))
    text = differential.render(report)
    assert "## Known divergences, reported every run" in text
    assert "behaviours §3.23" in text


def test_a_missing_key_inside_a_drawn_array_is_never_attributed_to_the_entry_that_excuses_it() -> (
    None
):
    """AC-17, from the other end. Excusing an array must not excuse the shape of what is in it.

    Widen `attribute` past `LENGTH` and this fails, which is the whole safeguard: an entry says
    this array is a draw, and a key missing from a row of it is still the class the report ranks
    first.
    """
    entry = allowlist.Entry(
        kind="drawn",
        endpoint="GET /Items/{itemId}/Similar",
        pointer="/Items",
        case="*",
        reason="a fresh draw per request",
        because="behaviours §3.23",
        since="2026-09-02",
    )
    missing = engine.Difference(engine.Class.MISSING_KEY, "/Items", None, "theirs")
    assert differential.attribute(missing, [entry]) == ""


def test_a_derivation_class_never_attributes_a_length() -> None:
    """AC-6's distinction, enforced where it would otherwise be forgotten.

    A derivation class is a fact about two separate installations — a scan's clock, a mount point,
    a hash over differently-derived inputs — and the number of rows in an answer is never one of
    those. Only a behaviours section, which is an argument somebody wrote, can cover a count.
    """
    entry = allowlist.Entry(
        kind="drawn",
        endpoint="*",
        pointer="/Items",
        case="*",
        reason="identifiers differ",
        because="derived-identifier",
        since="2026-09-02",
    )
    length = engine.Difference(engine.Class.LENGTH, "/Items", 2, 6)
    assert differential.attribute(length, [entry]) == ""


def test_an_untriaged_difference_blocks_the_run_and_a_known_one_is_printed_anyway() -> None:
    """The two are counted separately and both appear. Neither is ever silently dropped."""
    length = engine.Difference(engine.Class.LENGTH, "/Items", 2, 6)
    value = engine.Difference(engine.Class.VALUE, "/Name", "here", "there")
    known = _report(comparisons=(_ran(attributed=((length, "behaviours §3.24"),)),))
    assert known.is_clean()
    untriaged = _report(comparisons=(_ran(differences=(value,)),))
    assert not untriaged.is_clean()


# -- the needs vocabulary, and the twenty rows -------------------------------------------------


def test_the_twenty_named_comparisons_are_all_reported_even_though_none_can_run() -> None:
    """AC-16 against the register itself: twenty rows, none runnable, each outstanding by name."""
    register = allowlist.load_named()
    ran, outstanding = differential.named_outcomes(
        register, differential.Inputs(roles=("administrator", "restricted"))
    )
    assert ran == ()
    assert len(outstanding) == 20
    assert {row for row, _why in outstanding} == {row.id for row in register}
    assert all(why for _row, why in outstanding)


def test_an_outstanding_row_says_which_need_was_missing_and_not_merely_that_it_did_not_run() -> (
    None
):
    """Plan §4.2: *"four outstanding, and three of them because no fixture instance was
    available"* is a different sentence from *"four outstanding"*, and it is what `needs` earns."""
    register = {row.id: row for row in allowlist.load_named()}
    inputs = differential.Inputs(roles=("administrator",))
    reasons = dict(differential.named_outcomes(list(register.values()), inputs)[1])

    assert "restricted" in reasons["playlist-read-names-its-reader"]
    assert "instance" in reasons["multi-part-film-media-sources"]
    assert "T12" in reasons["playlist-de-duplication-misses"]


def test_a_reference_somebody_else_stood_up_makes_the_fixture_rows_askable() -> None:
    """`--reference-url` is the degradation ADR-0007 promises: coverage bought, and said so.

    Without a runtime and without T9, a machine still runs the sweep; with an instance somebody
    else is running, the rows that need one stop being blocked on the instance and are blocked
    only on the runner that has not been written.
    """
    without = differential.Inputs(roles=("administrator",), fixture_asked=True)
    with_one = differential.Inputs(
        roles=("administrator",), fixture_asked=True, instance_url="http://127.0.0.1:8097"
    )
    assert differential.unmet_need("fixture", without) != ""
    assert differential.unmet_need("fixture", with_one) == ""
    assert differential.unmet_need("wait", with_one) == ""
    assert differential.unmet_need("bytes", without) == ""


def test_selecting_one_named_comparison_leaves_the_other_nineteen_counted() -> None:
    """`--named` narrows what is attempted and never what is reported: AC-16 counts twenty."""
    register = allowlist.load_named()
    _ran_ids, outstanding = differential.named_outcomes(
        register,
        differential.Inputs(roles=("administrator",), named_selected=("subtitle-burn-in",)),
    )
    assert len(outstanding) == 20
    assert dict(outstanding)["manifest-announced-track-name"] == "not selected by --named"


# -- the wire ----------------------------------------------------------------------------------


def test_a_body_with_no_content_type_reaches_the_wire_without_one() -> None:
    """The reason this harness does not use `tools/_probe.py`'s `Server`, measured not assumed.

    `urllib.request` inserts `Content-type: application/x-www-form-urlencoded` into any request
    that carries a body and names no type, in `AbstractHTTPHandler.do_request_` — so a client
    built on it **cannot** issue the `body-with-no-content-type` case at all, which is one of the
    two register rows plan §6.4 makes an ordinary request case and four cases T6 wrote for it.
    """
    sent: dict[str, Any] = {}

    class FakeConnection:
        def __init__(self, host: str, port: Any, timeout: int = 30) -> None:
            sent["host"] = host

        def request(self, method: str, target: str, body: Any, headers: dict[str, str]) -> None:
            sent.update({"method": method, "target": target, "body": body, "headers": headers})

        def getresponse(self) -> Any:
            class Answer:
                status = 400

                @staticmethod
                def read() -> bytes:
                    return b"{}"

                @staticmethod
                def getheaders() -> list[tuple[str, str]]:
                    return [("Content-Type", "application/json")]

            return Answer()

        def close(self) -> None:
            return None

    import http.client

    original = http.client.HTTPConnection
    http.client.HTTPConnection = FakeConnection  # type: ignore[misc, assignment]
    try:
        answer = differential.Wire("http://localhost:8096", token="t").request(
            "POST", "/Items/x/PlaybackInfo", body=b"{}", content_type=""
        )
    finally:
        http.client.HTTPConnection = original  # type: ignore[misc]

    assert "Content-Type" not in sent["headers"]
    assert sent["headers"]["X-Emby-Token"] == "t"
    assert sent["body"] == b"{}"
    assert answer.status == 400


def test_a_delivery_response_compares_every_header_and_a_json_one_compares_the_content_type() -> (
    None
):
    """Spec §3.2 asks for headers on the delivery routes, and this is why the line is there.

    Comparing every header on every response would report a `Content-Length` difference on every
    JSON body — the two bodies legitimately differ in length wherever an identifier does — which
    is the cascade the `LENGTH` class exists to prevent, arriving through another door. A delivery
    route is recognised by its answer rather than by a list of paths somebody maintains: a
    response whose body is not JSON.
    """
    json_pair = [
        engine.Response(
            status=200,
            headers={"Content-Type": "application/json", "Content-Length": str(length)},
            body={"Name": "same"},
        )
        for length in (100, 200)
    ]
    assert differential.compare_pair(json_pair[0], json_pair[1], engine.NO_RULES) == ()

    delivery = [
        engine.Response(
            status=200,
            headers={"Content-Type": "video/mp4", "Content-Length": str(length)},
            body=None,
            raw=b"\x00",
        )
        for length in (100, 200)
    ]
    findings = differential.compare_pair(delivery[0], delivery[1], engine.NO_RULES)
    assert [found.pointer for found in findings] == ["header:content-length"]


def test_a_status_difference_stops_before_the_headers_as_well_as_before_the_bodies() -> None:
    """One finding that explains every other, and nothing after it to bury it."""
    ours = engine.Response(status=404, headers={"Content-Type": "application/json"}, body={})
    theirs = engine.Response(status=200, headers={"Content-Type": "application/json"}, body={})
    findings = differential.compare_pair(ours, theirs, engine.NO_RULES)
    assert len(findings) == 1
    assert findings[0].pointer == engine.STATUS_POINTER


# -- the surface, read through the validator's own parser --------------------------------------


def test_the_endpoints_come_from_the_surface_and_carry_the_level_it_declares() -> None:
    """One parser, not a second one: `tools/extract_v1_surface.py`'s own `parse_surface`."""
    endpoints = differential.load_endpoints(REPO_ROOT / "docs" / "compatibility" / "surface.yaml")
    assert len(endpoints) == 59
    assert sum(1 for endpoint in endpoints if endpoint.level == "L3") == 8
    assert differential.Endpoint("GET", "/System/Info/Public", "L3", "001") in endpoints


def test_every_endpoint_of_the_surface_is_reachable_by_at_least_one_declared_case() -> None:
    """AC-3's floor, asserted where the run reads it rather than only where the file is checked."""
    endpoints = differential.load_endpoints(REPO_ROOT / "docs" / "compatibility" / "surface.yaml")
    cases = allowlist.load_cases(entries=allowlist.load())
    for endpoint in endpoints:
        assert allowlist.cases_for(cases, endpoint.key), endpoint.key
