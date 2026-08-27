# SPDX-License-Identifier: GPL-3.0-or-later
"""The implementation and the probe reimplement one algorithm. Something must check they agree.

`tools/probe_sort_names.py` carries its own derivation, written from the reference's source, and it
cannot import this one: a probe is standard-library only and runs on a Python 3.9 that has no
environment built (tools/README.md). So the algorithm exists twice on purpose - and two copies of a
subtle algorithm drift, quietly, in the direction of whichever one somebody last debugged.

What that would cost is specific. The probe is the regression suite for the project's *beliefs*: it
exits non-zero when the reference stops behaving the way this repository claims. A probe that has
drifted from `atrium.domain.sorting` is still green while the server and the server we ship
disagree, which is the one failure the probe exists to prevent.

This imports the probe module. It reaches no server: importing defines constants and functions, and
everything that connects is behind `main()`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from atrium.domain.items import Item, ItemType
from atrium.domain.sorting import sort_name

TOOLS = Path(__file__).resolve().parents[2] / "tools"


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    sys.path.insert(0, str(TOOLS))
    try:
        return importlib.import_module("probe_sort_names")
    finally:
        sys.path.remove(str(TOOLS))


def test_the_base_derivations_agree_on_every_measured_case(probe: ModuleType) -> None:
    disagreements = []
    for name, rule in probe.CASES:
        item = Item(id="a" * 32, type=ItemType.MOVIE, name=name, library_id="b" * 32)
        ours, theirs = sort_name(item), probe.derive(name)
        if ours != theirs:
            disagreements.append(f"{name!r} [{rule}]: sorting.py {ours!r}, probe {theirs!r}")
    assert not disagreements, (
        "atrium.domain.sorting and tools/probe_sort_names.py have drifted:\n  "
        + "\n  ".join(disagreements)
        + "\nOne of them is wrong. If the reference changed, both change and behaviours.md "
        "section 2.6 records it; if this repository was wrong, both change together."
    )


@pytest.mark.parametrize(
    ("item_type", "parent", "index"),
    [
        (ItemType.AUDIO, 1, 3),
        (ItemType.AUDIO, None, 3),
        (ItemType.EPISODE, 1, 2),
        (ItemType.EPISODE, 12, 305),
        (ItemType.EPISODE, None, None),
    ],
)
def test_the_override_formulas_agree(
    probe: ModuleType, item_type: ItemType, parent: int | None, index: int | None
) -> None:
    item = Item(
        id="a" * 32,
        type=item_type,
        name="The Song",
        library_id="b" * 32,
        parent_index_number=parent,
        index_number=index,
    )
    theirs = probe.derive_override(
        {
            "Type": item_type.value,
            "Name": "The Song",
            "ParentIndexNumber": parent,
            "IndexNumber": index,
        }
    )
    assert sort_name(item) == theirs


@pytest.mark.parametrize("season", [4, None])
def test_the_season_formula_agrees(probe: ModuleType, season: int | None) -> None:
    """Season reads its number from IndexNumber where the other two read ParentIndexNumber, which
    is why the probe normalises before calling. Reproduced here rather than papered over.
    """
    item = Item(
        id="a" * 32,
        type=ItemType.SEASON,
        name="Season 4",
        library_id="b" * 32,
        index_number=season,
    )
    theirs = probe.derive_override(
        {
            "Type": "Season",
            "Name": "Season 4",
            "ParentIndexNumber": season,
            "IndexNumber": season,
        }
    )
    assert sort_name(item) == theirs


def test_the_configured_lists_are_the_same_on_both_sides(probe: ModuleType) -> None:
    """A default changed on one side and not the other reorders a library and nothing says so."""
    from atrium.domain.sorting import DEFAULT_RULES

    assert list(DEFAULT_RULES.articles) == probe.REMOVE_WORDS
    assert list(DEFAULT_RULES.removed) == probe.REMOVE_CHARS
    assert list(DEFAULT_RULES.replaced) == probe.REPLACE_CHARS
    assert DEFAULT_RULES.digit_pad == probe.DIGIT_PAD


def test_the_probe_still_measures_the_cases_this_repository_claims(probe: ModuleType) -> None:
    """If the probe's case list shrinks, a row of spec section 3.7.1 stopped being measured."""
    assert len(probe.CASES) == 15
