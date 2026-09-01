# SPDX-License-Identifier: GPL-3.0-or-later
"""The stale-index report has to show, or honestly count, every name it found.

`tools/extract_property_names.py --check` is the only thing that compares the committed
property-name index against a real document, and its output is the whole of what a reader learns
from it. On 2026-09-01 that output was wrong in the direction that matters: the difference was 2
names one way and 19 the other, and the tail called the nine it had hidden "1 more" - because the
count subtracted two full samples from the total regardless of how many it had actually printed.

The report is the product here, so it is tested the way a response body is: on the exact lines.

This imports the tool. It reaches no server - importing defines constants and functions, and
everything that reads a file is behind `main()`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
INDEX = Path("docs/compatibility/property-names.json")


@pytest.fixture(scope="module")
def extract() -> ModuleType:
    sys.path.insert(0, str(TOOLS))
    try:
        return importlib.import_module("extract_property_names")
    finally:
        sys.path.remove(str(TOOLS))


def index(names: list[str], version: str = "10.11.10") -> dict[str, Any]:
    return {"reference_version": version, "count": len(names), "names": sorted(names)}


def tail(lines: list[str]) -> str | None:
    return lines[-1] if lines[-1].lstrip().startswith("...") else None


def test_a_small_difference_is_shown_whole(extract: ModuleType) -> None:
    lines = extract.stale_report(index(["A", "B"]), index(["A", "C"], "10.11.11"), INDEX)
    assert tail(lines) is None, "nothing was hidden, so nothing should be counted as hidden"
    assert "  in the document, not in the index: C" in lines
    assert "  in the index, not in the document: B" in lines


def test_the_version_line_names_both_sides(extract: ModuleType) -> None:
    lines = extract.stale_report(index(["A"]), index(["A"], "10.11.11"), INDEX)
    assert lines[1] == "  version: index says 10.11.10, document says 10.11.11"


def test_the_tail_counts_what_was_not_printed(extract: ModuleType) -> None:
    """The measured shape of the real drift: lopsided, with one side under the sample size."""
    current = index(["shared"] + [f"only_in_index_{n:02d}" for n in range(19)])
    fresh = index(["shared", "OnlyInDocumentA", "OnlyInDocumentB"], "10.11.11")

    lines = extract.stale_report(current, fresh, INDEX)
    shown = [line for line in lines if line.startswith("  in the ")]

    assert len(shown) == 2 + extract.SAMPLE, "both missing names and one sample of the extras"
    assert tail(lines) == f"  ... and {19 - extract.SAMPLE} more", (
        "the tail counts the names this report did not print, not a fixed two samples"
    )


def test_both_sides_over_the_sample_are_counted_together(extract: ModuleType) -> None:
    current = index([f"index_{n:02d}" for n in range(25)])
    fresh = index([f"Document{n:02d}" for n in range(30)], "10.11.11")

    lines = extract.stale_report(current, fresh, INDEX)
    assert tail(lines) == f"  ... and {(30 - extract.SAMPLE) + (25 - extract.SAMPLE)} more"


def test_an_identical_pair_still_reports_a_version_move(extract: ModuleType) -> None:
    """Same names, different version: the only line that can say why is the version line."""
    lines = extract.stale_report(index(["A", "B"]), index(["A", "B"], "10.11.11"), INDEX)
    assert len(lines) == 2
    assert lines[0].startswith("error:")
    assert "10.11.11" in lines[1]
