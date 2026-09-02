# SPDX-License-Identifier: GPL-3.0-or-later
"""The two registers a run is measured against — 010 AC-6 and AC-16.

The first is the allowlist, proven by making its gate fire. An allowlist entry excuses a
difference, so it is the one mechanism in the feature that can silently delete the feature's value
(010 plan §9). Three things are asserted, and only the first is about the file being well formed:

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

The second is the **named-comparison register**, `docs/compatibility/named-comparisons.yaml`: the
twenty differences a sweep cannot raise (spec §3.10). It is the other half of the same failure. The
allowlist can excuse a difference the run found; the register is what stops a run from reporting
clean on the questions it never asked — *"a harness that reports a clean run without them is
reporting the absence of the questions it did not ask"*. So the register is asserted to be spec
§3.10's table row for row, to count **twenty** since D-6, and to be readable by the thing that runs
it: every `needs` a declared value, every `behaviours` a section that exists, every `written_at` a
document of this repository that does.

No server, no socket, no clock: the loader reads two files, which is why this runs in the default
CI job where there is no Jellyfin and must not be one.
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
NAMED_COMPARISONS = REPO_ROOT / "docs" / "compatibility" / "named-comparisons.yaml"
SURFACE = REPO_ROOT / "docs" / "compatibility" / "surface.yaml"
BEHAVIOURS = REPO_ROOT / "docs" / "compatibility" / "behaviours.md"
CONFORMANCE = REPO_ROOT / "docs" / "compatibility" / "conformance.md"
REQUEST_CASES = REPO_ROOT / "docs" / "compatibility" / "request-cases.yaml"
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
NAMED = allowlist.load_named(NAMED_COMPARISONS)


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


# --------------------------------------------------------------------------------------------
# The named-comparison register — 010 AC-16, and spec §3.10's table row for row
# --------------------------------------------------------------------------------------------

#: The four rows D-6 added on 2026-09-02, by id. They are inside AC-16's count and not beside it,
#: which is the whole of that decision: the alternative was a run reporting *"sixteen of sixteen"*
#: while four questions with a written home went on being nobody's.
D6_ROWS = (
    "container-that-lost-every-file",
    "replaced-poster-default-rescan",
    "next-up-pristine-specials-season",
    "paused-session-ticker-freeze",
)

#: The six "what this feature owes the next ones" lists spec §3.10 collects, and §8 names.
INHERITED_LISTS = (
    "specs/005-item-query-api/tasks.md",
    "specs/006-images/tasks.md",
    "specs/007-user-data-and-playstate/tasks.md",
    "specs/008-playback-negotiation-and-delivery/tasks.md",
    "specs/009-playlists/tasks.md",
    "specs/011-subtitle-delivery/tasks.md",
)


def _named_row(**overrides: str) -> dict[str, str]:
    """A well-formed raw row, so a test can break exactly one thing about it."""
    row = {
        "id": "playlist-read-names-its-reader",
        "what": "A playlist read that names its own reader",
        "why_the_sweep_misses_it": "It needs a caller the run does not have",
        "needs": "[identity:restricted]",
        "behaviours": "behaviours §3.16",
        "written_at": "specs/009-playlists/tasks.md",
        "runner": "none",
    }
    row.update(overrides)
    return row


def test_the_register_is_spec_310s_table() -> None:
    """Row for row, in order, against the table it is a machine-readable copy of.

    Delete a row from either side and this fails, which is the protection the 2026-09-01 audit's M1
    finding asked for — applied here to the list that decides what a run has *not* asked.
    """
    header = "| The difference | Why the sweep misses it | What the named comparison is |"
    prose = [row[0] for row in _table_rows(SPEC.read_text(encoding="utf-8"), header)]
    assert [row.what for row in NAMED] == prose, "the register and spec §3.10 disagree"


def test_the_register_counts_twenty() -> None:
    """AC-16's count, and D-6's four rows inside it rather than beside it.

    The count is written down in three places since D-6 — AC-16, conformance.md's L3 section and
    this file — and this is what fails when one of them moves without the others.
    """
    assert len(NAMED) == 20
    assert len({row.id for row in NAMED}) == 20
    assert set(D6_ROWS) <= {row.id for row in NAMED}, "a D-6 row fell back out of the count"

    criterion = next(
        line
        for line in SPEC.read_text(encoding="utf-8").splitlines()
        if "named comparisons is either run or reported outstanding" in line
    )
    assert "twenty" in criterion, criterion
    assert "There are **twenty** of them" in CONFORMANCE.read_text(encoding="utf-8")


def test_every_row_names_a_behaviours_section_that_exists() -> None:
    """A citation to a section that is not there is a citation nobody checked.

    This is 006 T3's finding turned into a check: that task's own verification cited an exception
    **withdrawn three features earlier**, and nothing failed. `behaviours §5` resolves to the
    chapter, because four rows are answered by a row of its table and those have no anchor.
    """
    text = BEHAVIOURS.read_text(encoding="utf-8")
    headings = set(re.findall(r"^#+\s+(\d+(?:\.\d+)*)\.?\s", text, re.M))
    cited = {row.behaviours_section for row in NAMED if row.behaviours != allowlist.NONE}
    assert cited, "no row cites behaviours.md, which would mean the register lost its answers"
    assert cited <= headings, sorted(cited - headings)


def test_every_row_names_a_document_of_this_repository_that_exists() -> None:
    """`written_at` is where the reading is owed from, and a dead path owes nothing.

    Nineteen of the twenty came from one of the six inherited lists; behaviours §5.2 is the one
    that did not, which is what 010's task list meant by *"the six lists **and** the compatibility
    documents"*.
    """
    for row in NAMED:
        document = REPO_ROOT / row.written_at
        assert document.is_file(), f"{row.id}: {row.written_at} is not a file of this repository"
        if row.written_at in INHERITED_LISTS:
            assert "## What this feature owes the next ones" in document.read_text("utf-8"), row.id

    cited = {row.written_at for row in NAMED}
    assert set(INHERITED_LISTS) <= cited, sorted(set(INHERITED_LISTS) - cited)
    assert cited - set(INHERITED_LISTS) == {"docs/compatibility/behaviours.md"}


def test_the_two_rows_the_second_seat_is_the_whole_signal_for_declare_it() -> None:
    """The reason this register exists at all, asserted rather than left in a comment.

    Both are invisible to a run that authenticates as an administrator — which is every probe
    written in this repository before 2026-09-01. The named reader differs only for a restricted
    non-administrator, and the unreachable entries need that reader *and* a playlist spanning two
    libraries, because what the reference hides there is hidden by a parental-rating check and
    never by library access (behaviours §3.17).
    """
    rows = {row.id: row for row in NAMED}
    assert rows["playlist-read-names-its-reader"].needs == ("identity:restricted",)
    assert rows["playlist-entries-a-reader-cannot-reach"].needs == (
        "identity:restricted",
        "fixture",
    )


def test_every_row_that_d6_added_needs_the_single_use_instance() -> None:
    """D-6's argument, as an assertion: all four need exactly what OQ-5 unblocked.

    Three want the library changed between two scans and the fourth wants a deliberate silence, so
    none of them may be asked of an operator's server.
    """
    rows = {row.id: row for row in NAMED}
    for identifier in D6_ROWS[:2]:
        assert rows[identifier].needs == ("fixture", "rescan"), identifier
    assert rows["next-up-pristine-specials-season"].needs == ("fixture",)
    assert rows["paused-session-ticker-freeze"].needs == ("wait",)


def test_every_row_names_a_runner_and_none_of_them_is_none() -> None:
    """All twenty since 010 T12, where every one of them read `none` before it.

    The name is only half the check: `tests/conformance/test_differential.py` resolves each of
    these against `differential.RUNNERS`, so a row naming a function nobody wrote fails there
    rather than on the one run that needed it.
    """
    outstanding = [row.id for row in NAMED if row.is_outstanding]
    assert not outstanding, f"these rows still name no runner: {outstanding}"
    assert len({row.runner for row in NAMED}) == 20, "two rows name the same runner"


def test_an_unknown_need_fails_the_load() -> None:
    """A run reads `needs` to decide whether a row is askable, so a value it does not know would
    silently never be met — and a row that is never askable is a row that is never a miss."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_named([_named_row(needs="[a-second-jellyfin]")])
    assert "identity:restricted" in str(raised.value)


def test_an_empty_needs_is_a_value_and_a_missing_one_is_not() -> None:
    """Two rows carry `[]`: the last two of §3.10 are ordinary request cases, listed so a run
    counts them rather than triaging them twice. A row with no `needs` field at all is a row
    nothing can decide about."""
    assert allowlist.check_named([_named_row(needs="[]")])[0].needs == ()
    assert [row.id for row in NAMED if not row.needs] == [
        "body-binding-dollar-message",
        "body-with-no-content-type",
    ]
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_named([_named_row(needs="")])
    assert "missing needs" in str(raised.value)
    with pytest.raises(allowlist.AllowlistError):
        allowlist.check_named([_named_row(needs="fixture")])


def test_a_behaviours_value_that_is_neither_a_section_nor_none_fails_the_load() -> None:
    """`none` is a value here, where in the allowlist it is not: five of the twenty differences
    have no behaviours.md entry at all. What is not a value is a document nobody can resolve."""
    assert allowlist.check_named([_named_row(behaviours="none")])[0].behaviours_section == ""
    assert allowlist.check_named([_named_row(behaviours="behaviours §5")])[0].behaviours_section
    for bad in ("§3.16", "3.16", "007's list", ""):
        with pytest.raises(allowlist.AllowlistError):
            allowlist.check_named([_named_row(behaviours=bad)])


def test_a_written_at_outside_this_repository_fails_the_load() -> None:
    """AGENTS.md: provenance names a version and a date, or a file inside Jellyfin's own tree.
    A local path is neither verifiable by a reader nor ours to publish."""
    for bad in ("/Users/somebody/notes.md", "https://example.invalid/x.md", "behaviours §5.2"):
        with pytest.raises(allowlist.AllowlistError) as raised:
            allowlist.check_named([_named_row(written_at=bad)])
        assert "document of this repository" in str(raised.value)


def test_two_rows_with_one_id_fail_the_load() -> None:
    """The id is what the report prints, so two rows under one of them is one row unreadable."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_named([_named_row(), _named_row(what="something else")])
    assert "a second row" in str(raised.value)


# --------------------------------------------------------------------------------------------
# The request-case register — 010 AC-3, and the eight `level: L3` rows first
# --------------------------------------------------------------------------------------------

#: The three ids `allowlist.yaml` names and this register had to declare before they excused
#: anything. Two of them are T4's excused arrays, which were proven in the engine and unreachable
#: on the wire until a case carried the id; the third is T3's `TotalRecordCount` row.
IDS_THE_ALLOWLIST_NAMES = (
    "by-name-without-limit",
    "listing-ordered-at-random",
    "listing-ordered-by-a-key-with-ties",
)

#: The four routes where a body with no `Content-Type` has never been asked. 009 T13 measured the
#: fifth — the playlist rename — and its own list names 010 as the feature that asks these.
#: The endpoints whose case changes something about an account, or reads something a case changed:
#: a configuration, a favourite, a played flag, a playstate row, a playlist. Every case of one of
#: these names the seat the run created. The surface's other writes touch a session or an encoder
#: and outlive nothing — `POST /System/Ping`, `POST /Sessions/Capabilities/Full`,
#: `DELETE /Videos/ActiveEncodings`, `POST /Users/AuthenticateByName` and the negotiation — so
#: those are asked from both seats.
THE_RUNS_OWN_ACCOUNT = (
    "POST /Users/Configuration",
    "POST /UserFavoriteItems/{itemId}",
    "DELETE /UserFavoriteItems/{itemId}",
    "POST /UserPlayedItems/{itemId}",
    "DELETE /UserPlayedItems/{itemId}",
    "POST /Sessions/Playing",
    "POST /Sessions/Playing/Progress",
    "POST /Sessions/Playing/Stopped",
    "POST /Playlists",
    "GET /Playlists/{playlistId}/Items",
    "POST /Playlists/{playlistId}/Items",
    "DELETE /Playlists/{playlistId}/Items",
    "POST /Playlists/{playlistId}/Items/{itemId}/Move/{newIndex}",
    "DELETE /Items/{itemId}",
    "POST /Items/{itemId}",
)

CONTENT_TYPE_ROUTES = (
    "POST /Sessions/Playing",
    "POST /Sessions/Playing/Progress",
    "POST /Sessions/Playing/Stopped",
    "POST /Items/{itemId}/PlaybackInfo",
)


def _surface() -> list[dict[str, str]]:
    """`surface.yaml` through the surface validator's **own** parser, never a second one.

    A second parser of a file whose whole job is to be the single list is how the list stops being
    single, which is the 2026-09-01 audit's M1 finding one file along.
    """
    path = REPO_ROOT / "tools" / "extract_v1_surface.py"
    name = "atrium_surface_extractor"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _reference, endpoints = module.parse_surface(SURFACE.read_text(encoding="utf-8"))
    return list(endpoints)


SURFACE_ROWS = _surface()
CASES = allowlist.load_cases(REQUEST_CASES, ENTRIES)


def _case_row(**overrides: str) -> dict[str, str]:
    """A well-formed raw case, so a test can break exactly one thing about it."""
    row = {
        "id": "default",
        "endpoint": "GET /Items",
        "query": "",
        "body": "none",
        "content_type": "none",
        "anchors": "[]",
        "identities": "[administrator, restricted]",
        "needs": "[]",
        "what_it_is_for": "The bare listing",
    }
    row.update(overrides)
    return row


def test_the_shipped_request_cases_load() -> None:
    """The floor. Every other test here is about what the loader refuses."""
    assert len(CASES) > 59
    assert CASES[0].endpoint == "GET /System/Info/Public", "the eight L3 rows come first"


def test_every_surface_endpoint_has_at_least_one_case() -> None:
    """AC-3's floor, and it fails on the sixtieth endpoint the day one is added with no case."""
    surface = {f"{row['method']} {row['path']}" for row in SURFACE_ROWS}
    assert len(surface) == 59, "the surface parser and the surface file disagree"
    declared = {case.endpoint for case in CASES}
    assert surface - declared == set(), sorted(surface - declared)
    assert declared - surface == set(), sorted(declared - surface)


def test_every_l3_row_has_a_case_for_every_identity_it_is_meaningful_for() -> None:
    """*"What the gate changed"* §2, as an assertion.

    Eight rows of `surface.yaml` declare `level: L3` and **nothing has ever checked that a level is
    reached**: the surface validator checks only that the value is one of `L0..L3`, and
    `test_routes.py` reads `feature` and `consumers`. Every feature's definition of done has
    deferred the differential half here. So these eight get their cases first, and a run that asked
    them from one seat would be answering a two-row table with one row — which is what fails here.
    """
    rows = [row for row in SURFACE_ROWS if row["level"] == "L3"]
    assert len(rows) == 8, "the surface's L3 count moved; this test is what says so"
    for row in rows:
        endpoint = f"{row['method']} {row['path']}"
        cases = allowlist.cases_for(CASES, endpoint)
        assert cases, endpoint
        seats = {seat for case in cases for seat in case.identities_for(allowlist.ROLES)}
        assert {"administrator", "restricted"} <= seats, f"{endpoint}: only {sorted(seats)}"


def test_an_anchor_over_an_unordered_listing_is_refused() -> None:
    """**An anchor is only as sound as the ordering it indexes** (plan §6.1.1).

    A `listing:` anchor says *"the row at position 0"*, so a listing whose rows the allowlist
    excuses as `drawn` or `unordered` hands it an arbitrary row — and the case that follows is a
    comparison of two different items wearing one name. Both excused listings are refused, and the
    ordinary one beside them is not, which is what makes this a check and not a rejection of every
    anchor.
    """
    sound = allowlist.check_cases(
        [
            _case_row(id="movies-by-sort-name", query="sortBy=SortName"),
            _case_row(
                id="a-movie",
                endpoint="GET /Items/{itemId}",
                anchors="[itemId=listing:GET /Items#movies-by-sort-name@0]",
            ),
        ]
    )
    allowlist.check_anchor_orderings(sound, ENTRIES)

    for excused in ("listing-ordered-at-random", "listing-ordered-by-a-key-with-ties"):
        cases = allowlist.check_cases(
            [
                _case_row(id=excused, query="sortBy=Random"),
                _case_row(
                    id="a-movie",
                    endpoint="GET /Items/{itemId}",
                    anchors=f"[itemId=listing:GET /Items#{excused}@0]",
                ),
            ]
        )
        with pytest.raises(allowlist.AllowlistError) as raised:
            allowlist.check_anchor_orderings(cases, ENTRIES)
        assert "arbitrary row" in str(raised.value)


def test_the_three_case_ids_the_allowlist_names_are_declared() -> None:
    """The debt T3 and T4 both left, discharged.

    Until a case carried these ids, two of the three excused arrays *"excused nothing on the
    wire"* — proven in the engine and unreachable in a run — and the five `TotalRecordCount` rows
    excused a difference on a request nobody could send. An id no case declares matches nothing,
    which is the safe half of being wrong and is still not a working entry.
    """
    declared = {case.id for case in CASES}
    assert set(IDS_THE_ALLOWLIST_NAMES) <= declared, sorted(set(IDS_THE_ALLOWLIST_NAMES) - declared)

    named = {entry.case for entry in ENTRIES if entry.case != "*"}
    assert named <= declared, sorted(named - declared)

    by_name = {case.endpoint for case in CASES if case.id == "by-name-without-limit"}
    excused = {entry.endpoint for entry in ENTRIES if entry.case == "by-name-without-limit"}
    assert excused == by_name, sorted(excused ^ by_name)


def test_the_four_content_type_cases_are_the_four_the_register_owes() -> None:
    """009's list: five routes, measured on one. These are the other four.

    A `content_type` of `none` beside a real body is the whole case — `400` here and `415` there —
    and no combination of a query and a body can say it, which is why the field exists.
    """
    asked = {
        case.endpoint for case in CASES if case.content_type == allowlist.NONE and case.has_body
    }
    assert asked == set(CONTENT_TYPE_ROUTES), sorted(asked ^ set(CONTENT_TYPE_ROUTES))
    assert any(row.id == "body-with-no-content-type" for row in NAMED)


def test_the_malformed_body_the_register_names_is_an_ordinary_case() -> None:
    """The other *"here to be recognised, not discovered"* row. Its body is not JSON, which is
    only expressible because `body` is raw text sent verbatim rather than a parsed object."""
    malformed = [case for case in CASES if case.id == "malformed-body"]
    assert len(malformed) == 1
    assert malformed[0].body == "not-json"
    assert any(row.id == "body-binding-dollar-message" for row in NAMED)


def test_every_case_that_writes_names_the_seat_the_run_created() -> None:
    """Spec §3.5 asks a writing probe to remove what it made; this asks the sweep not to make it
    on somebody else's account at all.

    The administrator's seat is whatever `.env` points at, and on the only reference this project
    could reach before T9 that is an operator's own. The one exception is the playlist rename,
    which the reference declares administrator-only — so it runs as the administrator, over a
    playlist the restricted seat made.
    """
    writes = {case for case in CASES if case.endpoint in THE_RUNS_OWN_ACCOUNT}
    assert len({case.endpoint for case in writes}) == len(THE_RUNS_OWN_ACCOUNT)
    for case in writes:
        if case.endpoint == "POST /Items/{itemId}":
            assert case.identities == ("administrator",), case.id
            continue
        assert case.identities == ("restricted",), f"{case.endpoint} {case.id}"


def test_a_path_parameter_with_no_anchor_must_wait_on_the_fixture() -> None:
    """Three ways to account for a `{parameter}` and no fourth: an anchor, `userId` — which plan
    §6.1.1 says is the identity's own and never an anchor — or a case that declares `fixture` and
    leaves it for T11. A parameter that is none of the three would be sent literally."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases([_case_row(id="a-movie", endpoint="GET /Items/{itemId}")])
    assert "itemId" in str(raised.value)

    waiting = allowlist.check_cases(
        [_case_row(id="a-movie", endpoint="GET /Items/{itemId}", needs="[fixture]")]
    )
    assert waiting[0].needs == ("fixture",)

    own = allowlist.check_cases([_case_row(id="the-identitys-own", endpoint="GET /Users/{userId}")])
    assert own[0].anchors == ()


def test_an_anchor_names_a_case_this_register_declares() -> None:
    """An anchor is a cross-reference, and a cross-reference to nothing resolves to nothing."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases(
            [
                _case_row(
                    id="a-movie",
                    endpoint="GET /Items/{itemId}",
                    anchors="[itemId=listing:GET /Items#no-such-case@0]",
                )
            ]
        )
    assert "does not declare" in str(raised.value)


def test_the_three_anchor_kinds_and_nothing_else() -> None:
    """Plan §6.1.1 describes one kind and this register needs three.

    `literal` is the one that would look like a shortcut and is not: `{container}`, `{routeFormat}`,
    `{imageType}`, `{imageIndex}` and `{newIndex}` do not name items at all, so no listing and no
    response can fill them, and five routes are unaskable without it.
    """
    kinds = {anchor.kind for case in CASES for anchor in case.anchors}
    assert kinds == {"listing", "response", "literal"}

    for bad in (
        "[itemId=guess:GET /Items#default@0]",
        "[itemId=listing:GET /Items#default@first]",
        "[itemId=response:GET /Items#default@0]",
        "[itemId]",
    ):
        with pytest.raises(allowlist.AllowlistError):
            allowlist.check_cases(
                [_case_row(), _case_row(id="x", endpoint="GET /Items/{itemId}", anchors=bad)]
            )


def test_a_case_anchored_on_its_own_endpoint_fails_the_load() -> None:
    """It cannot be resolved before itself, and a run that tried would loop or guess."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases([_case_row(anchors="[parentId=listing:GET /Items#default@0]")])
    assert "before itself" in str(raised.value)


def test_an_undeclared_substitution_fails_the_load() -> None:
    """The vocabulary is three tokens, and a fourth would reach a server as literal text.

    Angle brackets rather than braces: a body is JSON, and a brace-delimited token matched the
    device profile's own nested objects the first time this was loaded.
    """
    good = allowlist.check_cases(
        [
            _case_row(
                id="username-and-pw",
                endpoint="POST /Users/AuthenticateByName",
                body='{"Username": "<identity.username>", "Pw": "<identity.password>"}',
                content_type="application/json",
            )
        ]
    )
    assert "<identity.username>" in good[0].body

    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases([_case_row(query="userId=<identity.id>")])
    assert "identity.user_id" in str(raised.value)


def test_an_anchor_can_fill_a_token_in_a_query_or_a_body() -> None:
    """010 T11's fourth vocabulary member, and the four shapes T6 could not express.

    An item id in a **body** (007's three reporting routes) and an item id in a **query** (`ids`
    on the playlist add, `entryIds` on the remove) are exactly as unfillable as an unanchored path
    parameter, and an anchor fills a path parameter by construction. `<anchor.p>` is the whole
    addition: it resolves to whatever the anchor named `p` resolves to, through the same three
    kinds and the same per-server resolution, so nothing new became resolvable and no case may
    carry an identifier.
    """
    filled = allowlist.check_cases(
        [
            _case_row(id="a-listing", endpoint="GET /Items"),
            _case_row(
                id="report-start",
                endpoint="POST /Sessions/Playing",
                body='{"ItemId": "<anchor.itemId>"}',
                content_type="application/json",
                anchors='["itemId=listing:GET /Items#a-listing@0"]',
            ),
        ]
    )
    assert filled[1].anchors[0].parameter == "itemId"

    # A token naming an anchor the case does not declare fills with nothing.
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases(
            [
                _case_row(
                    id="a-report", endpoint="POST /Sessions/Playing", query="ids=<anchor.itemId>"
                )
            ]
        )
    assert "anchor.itemId" in str(raised.value)


def test_an_anchor_that_fills_nothing_fails_the_load() -> None:
    """The other direction, and it is the one that would let a case *look* filled.

    An anchor naming neither a path parameter of its endpoint nor a `<anchor.p>` token in its
    query or body is read by nothing, so the case goes on sending exactly what it sent before -
    the shape T6 refused when it removed a placeholder item id that compared two `404`s and
    counted as coverage.
    """
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases(
            [
                _case_row(id="a-listing", endpoint="GET /Items"),
                _case_row(
                    id="reads-nothing",
                    endpoint="POST /Sessions/Playing",
                    body='{"PlaySessionId": "x"}',
                    content_type="application/json",
                    anchors='["itemId=listing:GET /Items#a-listing@0"]',
                ),
            ]
        )
    assert "fills no path parameter" in str(raised.value)


def test_a_body_a_get_cannot_carry_and_a_content_type_with_no_body() -> None:
    """Two shapes that describe nothing, refused rather than sent."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases([_case_row(body='{"a": 1}', content_type="application/json")])
    assert "cannot carry a body" in str(raised.value)

    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases([_case_row(content_type="application/json")])
    assert "describes nothing" in str(raised.value)


def test_an_empty_query_is_a_value_and_a_missing_one_is_not() -> None:
    """T5 found the same thing about an empty `needs`. Here it is the commonest value there is:
    the AC-3 floor case for most of the surface is a bare request."""
    assert allowlist.check_cases([_case_row(query="")])[0].query == ""
    assert len([case for case in CASES if not case.query]) > 20
    row = _case_row()
    del row["query"]
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases([row])
    assert "missing query" in str(raised.value)


def test_two_cases_with_one_id_on_one_endpoint_fail_the_load() -> None:
    """An id is unique **per endpoint**, not globally: `static` is a case of both stream routes and
    `by-name-without-limit` is a case of all five by-name endpoints, which is what lets one
    allowlist entry keyed on a case id cover a family. Two under one name on ONE endpoint is a
    difference the report cannot tell apart."""
    with pytest.raises(allowlist.AllowlistError) as raised:
        allowlist.check_cases([_case_row(), _case_row(query="limit=1")])
    assert "unique per endpoint" in str(raised.value)

    shared = {case.id for case in CASES}
    assert len(shared) < len(CASES), "an id is shared across endpoints on purpose"


def test_an_empty_identities_means_every_seat_and_not_the_first() -> None:
    """The value that says nothing has to mean **all** of them: the failure this feature is prone
    to is a case set that names one seat, and a default of "the first" would be that set."""
    case = allowlist.check_cases([_case_row(identities="[]")])[0]
    assert case.identities == ()
    assert case.identities_for(allowlist.ROLES) == allowlist.ROLES

    with pytest.raises(allowlist.AllowlistError):
        allowlist.check_cases([_case_row(identities="[owner]")])


def test_the_three_registers_are_valid_yaml() -> None:
    """The hand-written subset the tools parse is a *subset*, so it must also be YAML — and the
    third register is the one that proves it was worth checking: its bodies are JSON, whose double
    quotes make a single-quoted YAML scalar the only spelling both readers agree on."""
    yaml = pytest.importorskip("yaml")
    for path, block, expected in (
        (NAMED_COMPARISONS, "comparisons", len(NAMED)),
        (REQUEST_CASES, "cases", len(CASES)),
        (ALLOWLIST, "entries", len(ENTRIES)),
    ):
        loaded = yaml.safe_load(path.read_text("utf-8"))[block]
        assert len(loaded) == expected, path.name
    parsed = yaml.safe_load(REQUEST_CASES.read_text("utf-8"))["cases"]
    assert len(parsed) == len(CASES)
    for raw, case in zip(parsed, CASES, strict=True):
        assert raw["body"] == case.body, case.id
        assert raw["query"] == case.query, case.id
