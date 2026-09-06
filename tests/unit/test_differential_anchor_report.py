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
    assert "1 of 2 resolved to rows with different names" in rendered
    # It states rather than judges: nothing here calls the pair a defect, because a name is 003's
    # derivation and two spellings can be one item.
    assert "not a defect" in rendered


def test_a_run_that_resolved_no_anchor_gets_no_section() -> None:
    """An empty table under a heading reads as a finding of nothing; there was no question."""
    report = differential.RunReport(identities=(), cases=0, comparisons=())
    assert differential._anchor_section(report) == []
