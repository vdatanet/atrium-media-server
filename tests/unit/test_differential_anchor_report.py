# SPDX-License-Identifier: GPL-3.0-or-later
"""The report says which row each listing anchor resolved to, on each side.

**A position is not an item.** [Plan §4.2](../../specs/010-conformance-harness/plan.md) keeps
identifiers out of anchors because the two servers derive them differently by design, so a case
carrying one would compare two different items — and every listing anchor in `request-cases.yaml`
names position `0` instead, which does the same thing the moment the two orderings differ. One of
them already does: measured 2026-09-05, `audio-by-sort-name@0` was `By One Artist` on Atrium and
`Ninety Six Kilohertz` on the reference, and the twelve cases anchored on it compared two different
tracks while reporting a delivery difference that was not one.

This is the cheapest honest remedy [010's list](../../specs/010-conformance-harness/tasks.md)
named, and the reason it is only a **statement**: a name difference does not prove a mis-pairing,
because 003's name derivation differs from the reference's whole-filename rule on dozens of rows,
so two spellings can be one item. What the section removes is the silence.

**And from 2026-09-07 the same list's other door is taken, which is why this module has two
halves.** The remedy the entry reserved was *"an anchor that names a row by something both servers
agree on"*, and the register now has one: a `named:` anchor takes the row whose `Name` is the one
the two servers were measured to share. The tests below the divider are that kind — the pairing
made, and the loud failure when it cannot be.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load() -> Any:
    path = REPO_ROOT / "tools" / "differential.py"
    name = "atrium_differential_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


differential = _load()


def issuers(ours: dict[str, dict[str, str]], theirs: dict[str, dict[str, str]]) -> dict[str, Any]:
    """The one thing `anchor_resolutions` reads off an issuer, and nothing else.

    A stub rather than a real `Issuer`, deliberately: a test that had to build two wires and a
    case register to assert a join would be asserting the constructor.
    """
    return {
        "atrium": SimpleNamespace(anchor_rows=ours),
        "reference": SimpleNamespace(anchor_rows=theirs),
    }


def row(name: str, rows: str = "10", identifier: str = "a" * 32) -> dict[str, str]:
    return {"id": identifier, "name": name, "rows": rows}


def test_two_sides_that_picked_the_same_name_are_reported_as_agreeing() -> None:
    resolved = differential.anchor_resolutions(
        issuers(
            {"administrator|GET /Items#movies-by-sort-name@0": row("2 Fast 2 Furious", "31")},
            {"administrator|GET /Items#movies-by-sort-name@0": row("2 Fast 2 Furious", "32")},
        )
    )
    assert len(resolved) == 1
    anchor, seat, ours, theirs, agreement = resolved[0]
    assert anchor == "GET /Items#movies-by-sort-name@0"
    assert seat == "administrator"
    assert agreement == "same name"
    # The row counts travel even when the names agree, because 31 against 32 is how this listing
    # comes to agree at position 0 by one row rather than by construction.
    assert ours == "2 Fast 2 Furious (of 31)"
    assert theirs == "2 Fast 2 Furious (of 32)"


def test_the_listing_that_actually_diverges_is_marked() -> None:
    """The measured case, and the one this section exists for."""
    resolved = differential.anchor_resolutions(
        issuers(
            {"restricted|GET /Items#audio-by-sort-name@0": row("By One Artist")},
            {"restricted|GET /Items#audio-by-sort-name@0": row("Ninety Six Kilohertz")},
        )
    )
    assert resolved[0][4] == "DIFFERENT"


def test_an_anchor_only_one_side_resolved_is_neither_agreement_nor_difference() -> None:
    """A case whose anchor was unreachable on one server resolved on the other, and a join that
    silently dropped it would report a comparison with no anchor at all."""
    resolved = differential.anchor_resolutions(
        issuers({"administrator|GET /Items#series-by-sort-name@0": row("24")}, {})
    )
    assert resolved[0][3] == ""
    assert resolved[0][4] == "one side only"


def test_the_section_says_how_many_differ_and_names_them() -> None:
    report = differential.RunReport(
        identities=("administrator",),
        cases=0,
        comparisons=(),
        anchors=(
            (
                "GET /Items#movies-by-sort-name@0",
                "administrator",
                "A (of 3)",
                "A (of 3)",
                "same name",
            ),
            (
                "GET /Items#audio-by-sort-name@0",
                "administrator",
                "B (of 3)",
                "C (of 4)",
                "DIFFERENT",
            ),
        ),
    )
    rendered = "\n".join(differential._anchor_section(report))

    assert "## What each listing anchor resolved to" in rendered
    assert "`GET /Items#audio-by-sort-name@0`" in rendered
    assert "**DIFFERENT**" in rendered
    assert "1 of 2 resolved to rows this run cannot pair" in rendered
    # It states rather than judges: nothing here calls the pair a defect, because a name is 003's
    # derivation and two spellings can be one item.
    assert "not a defect" in rendered


def test_a_run_that_resolved_no_anchor_gets_no_section() -> None:
    """An empty table under a heading reads as a finding of nothing; there was no question."""
    report = differential.RunReport(identities=(), cases=0, comparisons=())
    assert differential._anchor_section(report) == []


# ------------------------------------------------------------------------------------------
# The fourth anchor kind, added 2026-09-07: the pairing itself, where the section above could
# only ever be a statement about it
# ------------------------------------------------------------------------------------------


def named(name: str, rows: str = "12", at: str = "0") -> dict[str, str]:
    return {"id": "b" * 32, "name": name, "rows": rows, "at": at, "kind": "named"}


class _Answer:
    def __init__(self, body: Any, status: int = 200) -> None:
        self.body = body
        self.status = status


class _Issuer(differential.Issuer):
    """A real `Issuer` with the wire taken out, so `resolve` runs the code a run runs.

    Only `answer_of` is replaced: everything this exercises — the row walk, the two failures, what
    gets written into `anchor_rows` — is the method under test and not a stand-in for it.
    """

    def __init__(self, side: str, rows: list[Any]) -> None:
        self.side = side
        self.anchor_rows: dict[str, dict[str, str]] = {}
        self._rows = rows

    def answer_of(self, endpoint: str, case: str, seat: Any, depth: int) -> Any:
        return _Answer({"Items": self._rows})


def anchor(at: str, kind: str = "named") -> Any:
    return SimpleNamespace(
        parameter="itemId", kind=kind, endpoint="GET /Items", case="audio-by-sort-name", at=at
    )


def seat(role: str = "administrator") -> Any:
    return SimpleNamespace(role=role)


def track(name: str, identifier: str) -> dict[str, str]:
    return {"Id": identifier, "Name": name}


def test_a_named_anchor_finds_its_row_wherever_the_two_orderings_put_it() -> None:
    """The measured divergence, paired: one track, two positions, two servers, one item.

    `audio-by-sort-name@0` was `By One Artist` here and `Ninety Six Kilohertz` there on 2026-09-05.
    Named, both sides resolve to the track the fixture declares — and the recorded positions are
    what tell a reader the orderings still disagree underneath.
    """
    here = _Issuer(
        "atrium", [track("By One Artist", "a" * 32), track("Ninety Six Kilohertz", "n" * 32)]
    )
    there = _Issuer(
        "reference", [track("Ninety Six Kilohertz", "r" * 32), track("By One Artist", "z" * 32)]
    )

    assert here.resolve(anchor("Ninety Six Kilohertz"), seat(), 0) == "n" * 32
    assert there.resolve(anchor("Ninety Six Kilohertz"), seat(), 0) == "r" * 32

    key = "administrator|GET /Items#audio-by-sort-name@Ninety Six Kilohertz"
    assert here.anchor_rows[key]["at"] == "1"
    assert there.anchor_rows[key]["at"] == "0"


def test_a_named_anchor_that_finds_nothing_is_reported_and_not_guessed() -> None:
    """The whole trade the fourth kind makes: fewer comparisons, no unpairable comparison.

    A position always names a row while the listing is long enough, whatever that row holds. A name
    either finds the row both servers agree about or the case is reported unasked with the reason —
    which is the mis-pairing stated instead of made.
    """
    issuer = _Issuer("atrium", [track("By One Artist", "a" * 32)])
    try:
        issuer.resolve(anchor("Ninety Six Kilohertz"), seat(), 0)
    except differential.UnreachableError as refused:
        assert "no row" in str(refused) and "Ninety Six Kilohertz" in str(refused)
        assert "out of the 1 it holds" in str(refused)
    else:  # pragma: no cover - the assertion below is the failure message
        raise AssertionError("a named anchor that matched nothing resolved to something")
    assert issuer.anchor_rows == {}


def test_the_two_kinds_read_differently_in_the_table() -> None:
    """A `named:` row says where each side found it; a positional one says how many rows it had.

    `paired by name` is not `same name` wearing a longer word: the first is a pairing this run
    made and the second is a spelling this run observed, and a reader who could not tell them
    apart would read the trivial agreement of the first as evidence of the second.
    """
    resolved = differential.anchor_resolutions(
        issuers(
            {
                "administrator|GET /Items#audio-by-sort-name@Ninety Six Kilohertz": named(
                    "Ninety Six Kilohertz", at="1"
                )
            },
            {
                "administrator|GET /Items#audio-by-sort-name@Ninety Six Kilohertz": named(
                    "Ninety Six Kilohertz", at="0"
                )
            },
        )
    )
    _anchor, _seat, ours, theirs, agreement = resolved[0]
    assert agreement == "paired by name"
    assert ours == "Ninety Six Kilohertz (row 1 of 12)"
    assert theirs == "Ninety Six Kilohertz (row 0 of 12)"


def test_a_paired_anchor_is_not_counted_among_the_rows_that_cannot_be_paired() -> None:
    """The summary line counts what a reader must act on, and a pairing is not one of them."""
    report = differential.RunReport(
        identities=("administrator",),
        cases=0,
        comparisons=(),
        anchors=(
            (
                "GET /Items#audio-by-sort-name@Ninety Six Kilohertz",
                "administrator",
                "T (row 1 of 12)",
                "T (row 0 of 12)",
                "paired by name",
            ),
            (
                "GET /Items#movies-by-sort-name@0",
                "administrator",
                "A (of 31)",
                "B (of 32)",
                "DIFFERENT",
            ),
        ),
    )
    rendered = "\n".join(differential._anchor_section(report))
    assert "1 of 2 resolved to rows this run cannot pair" in rendered
    assert "| paired by name |" in rendered
