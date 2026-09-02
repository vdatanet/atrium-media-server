# SPDX-License-Identifier: GPL-3.0-or-later
"""The allowlist, proven by making its gate fire — 010 AC-6.

An allowlist entry excuses a difference, so this file is the one mechanism in the feature that can
silently delete the feature's value (010 plan §9). Three things are asserted, and only the first is
about the file being well formed:

1. **AC-6 fires.** A `because` that is neither a `behaviours.md` section nor one of the four
   declared derivation classes fails the load, and so does a fifth class. Both are proven by
   *constructing the bad entry*, not by asserting that today's good file passes — a test that only
   ever sees a valid file passes when the check is deleted.
2. **The scoping is load-bearing.** `ChildCount` is excused on a `/UserViews` row and refused
   everywhere else. Delete the `endpoint` column from the entry and this fails, which is the whole
   of plan §6.3's argument turned into an assertion.
3. **The two prose copies say what the file says.** `spec.md` §3.3's two tables and
   `conformance.md`'s L3 table are compared against `allowlist.yaml` row for row. That is the
   2026-09-01 audit's M1 finding — *"a table of tests is the section most prone to this: nothing
   reads it, so nothing fails when it drifts"* — applied to the table that decides what a run is
   allowed to ignore.

No server, no socket, no clock: the loader reads one file, which is why this runs in the default CI
job where there is no Jellyfin and must not be one.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = REPO_ROOT / "docs" / "compatibility" / "allowlist.yaml"
SURFACE = REPO_ROOT / "docs" / "compatibility" / "surface.yaml"
BEHAVIOURS = REPO_ROOT / "docs" / "compatibility" / "behaviours.md"
CONFORMANCE = REPO_ROOT / "docs" / "compatibility" / "conformance.md"
SPEC = REPO_ROOT / "specs" / "010-conformance-harness" / "spec.md"


def _load_module() -> Any:
    """`tools/` is a directory of standalone programs, not an importable package.

    Registered in `sys.modules` **before** it executes, because `dataclasses` resolves a field's
    annotation by looking the defining module up by name — the gotcha T2 recorded, and this module
    declares two dataclasses.
    """
    path = REPO_ROOT / "tools" / "_allowlist.py"
    name = "atrium_allowlist_reader"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


allowlist = _load_module()
ENTRIES = allowlist.load(ALLOWLIST)


def _row(**overrides: str) -> dict[str, str]:
    """A well-formed raw row, so a test can break exactly one thing about it."""
    row = {
        "kind": "field",
        "endpoint": "*",
        "pointer": "/Items/-/Id",
        "case": "*",
        "reason": "The item identifier a list row carries",
        "because": "derived-identifier",
        "since": "2026-09-02",
    }
    row.update(overrides)
    return row


# --------------------------------------------------------------------------------------------
# AC-6, proven by making it fire
# --------------------------------------------------------------------------------------------


def test_the_shipped_allowlist_loads() -> None:
    """The floor. Every other test here is about what the loader refuses."""
    assert len(ENTRIES) > 50
    assert allowlist.check([_row()]) == (
        allowlist.Entry(
            "field",
            "*",
            "/Items/-/Id",
            "*",
            "The item identifier a list row carries",
            "derived-identifier",
            "2026-09-02",
        ),
    )


def test_an_entry_with_no_because_fails_the_load() -> None:
    """AC-6's first half: *an entry that does not declare why fails the run*."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check([_row(because="")])
    assert "missing because" in str(raised.value)


def test_an_entry_whose_because_is_an_excuse_fails_the_load() -> None:
    """*"We do it differently"* is the sentence AC-6 was written to reject."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check([_row(because="we derive it differently")])
    assert "behaviours" in str(raised.value)


def test_a_fifth_derivation_class_fails_the_load() -> None:
    """AC-6's second half: four classes, and *a fifth is not added without review*."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check([_row(because="different-hardware")])
    assert "four declared derivation classes" in str(raised.value)


def test_a_behaviours_section_is_a_because_and_a_bare_section_number_is_not() -> None:
    """The divergence half of AC-6 is a citation, not a number somebody remembered."""
    assert allowlist.check([_row(because="behaviours §3.25")])[0].behaviours_section == "3.25"
    with pytest.raises(allowlist.AllowlistError):
        allowlist.check([_row(because="3.25")])
    with pytest.raises(allowlist.AllowlistError):
        allowlist.check([_row(because="behaviours §3")])


def test_a_bare_field_name_is_not_a_pointer() -> None:
    """The one spelling this file exists not to carry."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check([_row(pointer="ChildCount")])
    assert "bare field name" in str(raised.value)


def test_an_array_entry_cannot_name_a_header_or_the_status() -> None:
    """A header is not an array, and neither is a status."""
    for pointer in ("header:Server", "status"):
        with pytest.raises(allowlist.AllowlistError):
            allowlist.check([_row(kind="drawn", pointer=pointer)])


def test_two_entries_for_the_same_endpoint_pointer_and_case_fail_the_load() -> None:
    """Two reasons for one excused thing means one of them is unread."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check([_row(), _row(reason="something else")])
    assert "a second entry" in str(raised.value)


def test_a_malformed_endpoint_case_or_date_fails_the_load() -> None:
    for bad in (
        _row(endpoint="/Items"),  # no method
        _row(case="Not A Case Id"),
        _row(since="2026-9-2"),
        _row(kind="fields"),
    ):
        with pytest.raises(allowlist.AllowlistError):
            allowlist.check([bad])


# --------------------------------------------------------------------------------------------
# The scoping, which is the whole of plan §6.3's argument
# --------------------------------------------------------------------------------------------


def test_childcount_is_excused_on_a_library_view_and_nowhere_else() -> None:
    """behaviours §3.25's own closing paragraph, as an assertion.

    The reference's `ChildCount` on a `/UserViews` row is a fresh random integer. The same property
    on a series, a season or a multi-disc album is a real computed subtree aggregate on both
    servers — `db/item_queries.py`'s container aggregates, gated by `api/items.py` — and is exactly
    what L2 checks. Delete the `endpoint` column from that entry and the second half of this fails.
    """
    view = allowlist.resolve(ENTRIES, "GET /UserViews")
    assert "/Items/-/ChildCount" in view.excused_fields

    for elsewhere in ("GET /Items", "GET /Items/{itemId}", "GET /Shows/{seriesId}/Seasons"):
        resolved = allowlist.resolve(ENTRIES, elsewhere)
        assert "/Items/-/ChildCount" not in resolved.excused_fields, elsewhere


def test_a_request_case_condition_narrows_and_never_widens() -> None:
    """The seventh column, and the direction of its failure.

    `TotalRecordCount` is excused on a by-name listing that carries no limit and on nothing else,
    so a by-name request that *does* carry one still compares the count. An id no case declares
    matches nothing, which is the under-excusing direction.
    """
    without = allowlist.resolve(ENTRIES, "GET /Artists", case="by-name-without-limit")
    assert "/TotalRecordCount" in without.excused_fields

    for case in ("*", "by-name-with-limit", "anything-else"):
        resolved = allowlist.resolve(ENTRIES, "GET /Artists", case=case)
        assert "/TotalRecordCount" not in resolved.excused_fields, case


def test_the_three_excused_arrays_resolve_into_their_own_two_buckets() -> None:
    """AC-17 and AC-18 need the kinds kept apart, or `drawn` and `unordered` become one thing."""
    similar = allowlist.resolve(ENTRIES, "GET /Items/{itemId}/Similar")
    assert "/Items" in similar.drawn_arrays
    assert similar.unordered_arrays == {}

    drawn = allowlist.resolve(ENTRIES, "GET /Items", case="listing-ordered-at-random")
    assert "/Items" in drawn.drawn_arrays

    unordered = allowlist.resolve(ENTRIES, "GET /Items", case="listing-ordered-by-a-key-with-ties")
    assert "/Items" in unordered.unordered_arrays
    assert unordered.drawn_arrays == {}


def test_the_three_mappings_are_named_for_the_engines_three_rule_fields() -> None:
    """`Rules(**resolution.mappings())` is the contract between this module and the engine."""
    assert set(allowlist.resolve(ENTRIES, "GET /Items").mappings()) == {
        "excused_fields",
        "drawn_arrays",
        "unordered_arrays",
    }


def test_the_identity_is_accepted_and_selects_nothing() -> None:
    """Documented rather than silent: no row of spec §3.3 is conditioned on who asked.

    Spec §3.9 makes the identity a dimension of a *run* — 12 of 23 reads answer differently to a
    restricted non-administrator — but every one of those is a finding, not an excuse.
    """
    plain = allowlist.resolve(ENTRIES, "GET /Items")
    for identity in (None, "administrator", "restricted"):
        assert allowlist.resolve(ENTRIES, "GET /Items", identity=identity) == plain


# --------------------------------------------------------------------------------------------
# The file against the rest of the repository
# --------------------------------------------------------------------------------------------


def test_every_endpoint_named_is_a_row_of_the_surface() -> None:
    """An entry naming an endpoint no run will ever call excuses nothing, quietly."""
    text = SURFACE.read_text(encoding="utf-8")
    rows: set[str] = set()
    path = ""
    for line in text.splitlines():
        start = re.match(r'^\s*-\s+path:\s*"([^"]+)"\s*$', line)
        if start:
            path = start.group(1)
            continue
        method = re.match(r"^\s+method:\s*(\w+)\s*$", line)
        if method and path:
            rows.add(f"{method.group(1)} {path}")
    assert len(rows) == 59, "the surface parser and the surface file disagree"

    named = {entry.endpoint for entry in ENTRIES if entry.endpoint != "*"}
    assert named <= rows, sorted(named - rows)


def test_every_behaviours_section_cited_exists() -> None:
    """A citation to a section that is not there is a citation nobody checked."""
    headings = set(re.findall(r"^#+ (\d+\.\d+)\s", BEHAVIOURS.read_text(encoding="utf-8"), re.M))
    cited = {entry.behaviours_section for entry in ENTRIES if not entry.is_derivation}
    assert cited, "no entry excuses a divergence, which would mean the file lost its §4.1 rows"
    assert cited <= headings, sorted(cited - headings)


def test_datelastsaved_is_not_excused_because_it_is_not_a_property() -> None:
    """The row that did not survive being written into a file.

    `DateLastSaved` is an `ItemFields` token, not a property of an item body: the pinned document's
    `BaseItemDto` carries 153 properties and that is not one of them, and it is absent from
    `property-names.json`, which is this project's extraction of every property name the reference
    uses `[spec: BaseItemDto, ItemFields]`. An entry for it would have excused a field neither
    server can send — the allowlist is a metric, and a row that excuses nothing inflates it.
    """
    names = (REPO_ROOT / "docs" / "compatibility" / "property-names.json").read_text("utf-8")
    assert '"DateLastSaved"' not in names
    assert not any("DateLastSaved" in entry.pointer for entry in ENTRIES)
    assert "DateLastSaved" not in _prose_field_names(SPEC.read_text(encoding="utf-8"), "spec")


def test_no_entry_excuses_a_key_that_is_measured_identical_on_both_servers() -> None:
    """`ChannelId` is the case: an explicit `null` on every item of every response, 208 of 208.

    Excusing it would hide the day one server stopped sending it — and a missing key is the class
    the report ranks first.
    """
    assert not any(entry.pointer.endswith("/ChannelId") for entry in ENTRIES)


# --------------------------------------------------------------------------------------------
# The two prose copies, against the file
# --------------------------------------------------------------------------------------------

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_TICKED = re.compile(r"`([^`]+)`")


def _clean(cell: str) -> str:
    return _LINK.sub(r"\1", cell).replace("**", "").strip()


def _table_rows(text: str, header: str) -> list[list[str]]:
    """The rows of the one Markdown table whose header line is `header`."""
    lines = text.splitlines()
    for _index, line in enumerate(lines):
        if line.strip() == header:
            break
    else:  # pragma: no cover - the assertion below is the message
        raise AssertionError(f"no table with header {header!r}")
    rows = []
    for line in lines[_index + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([_clean(cell) for cell in line.strip().strip("|").split(" | ")])
    return rows


def _classify(token: str) -> tuple[str, str]:
    """A backticked token from a table's first column, as `(what, value)`."""
    if token.startswith("/"):
        return "endpoint", token
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", token):
        return "case", token
    return "name", token.split(".", 1)[0]


def _prose_field_names(text: str, _label: str) -> set[str]:
    rows = _table_rows(text, "| Field | Why it may differ | Because |")
    return {
        value
        for row in rows
        for token in _TICKED.findall(row[0])
        for what, value in [_classify(token)]
        if what == "name"
    }


def _prose_field_pairs(text: str) -> set[tuple[str, str]]:
    """`(property or header name, because)` for every field row of a prose table."""
    pairs = set()
    for row in _table_rows(text, "| Field | Why it may differ | Because |"):
        because = row[-1].strip("`")
        for token in _TICKED.findall(row[0]):
            what, value = _classify(token)
            if what == "name":
                pairs.add((value, because))
    return pairs


def _entry_name(entry: Any) -> str:
    """The name a prose row would call this entry's pointer by."""
    if entry.pointer.startswith("header:"):
        return entry.pointer.split(":", 1)[1]
    return entry.pointer.rsplit("/", 1)[-1]


def test_the_two_prose_tables_say_what_the_file_says() -> None:
    """§3.3's field table, conformance.md's rendering of it, and `allowlist.yaml`, row for row.

    Two prose copies of one list drift, and the only thing that stops it is something that reads
    both. They already had: conformance.md was carrying seven of §3.3's nine rows when this was
    written, missing `PlaySessionId`/`AccessToken` and `TotalRecordCount` outright.
    """
    spec_pairs = _prose_field_pairs(SPEC.read_text(encoding="utf-8"))
    conformance_pairs = _prose_field_pairs(CONFORMANCE.read_text(encoding="utf-8"))
    assert spec_pairs == conformance_pairs, sorted(spec_pairs ^ conformance_pairs)

    file_pairs = {(_entry_name(entry), entry.because) for entry in ENTRIES if entry.kind == "field"}
    assert file_pairs == spec_pairs, sorted(file_pairs ^ spec_pairs)


def test_the_prose_array_table_says_what_the_file_says() -> None:
    """The three excused arrays, keyed on the endpoint or the request case each names."""
    header = "| Array | Why it may differ | What is still compared | Because |"
    prose = set()
    for row in _table_rows(SPEC.read_text(encoding="utf-8"), header):
        because = row[-1].strip("`")
        for token in _TICKED.findall(row[0]):
            what, value = _classify(token)
            if what in {"endpoint", "case"}:
                prose.add((what, value, because))

    file_rows = set()
    for entry in ENTRIES:
        if entry.kind == "field":
            continue
        if entry.case != "*":
            file_rows.add(("case", entry.case, entry.because))
        else:
            file_rows.add(("endpoint", entry.endpoint.split(" ", 1)[1], entry.because))

    assert file_rows == prose, sorted(file_rows ^ prose)
    assert len(file_rows) == 3, "none of the three excused arrays is Atrium's to converge with"
