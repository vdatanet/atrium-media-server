# SPDX-License-Identifier: GPL-3.0-or-later
"""The naming corpus, run.

`tests/corpus/naming.yaml` is the **specification** of naming behaviour rather than a description
of what the code happens to do (003 plan section 6.1). The reference's rules live in a large table
of regular expressions; copying it is a licence problem and a design problem at once (Principle
IV), so the rows come first and the patterns are whatever makes them pass.

**Which means the rows fail until a parser exists, and that pull request has to merge anyway.**
Every row whose parser has not landed carries `xfail(strict=True)`, keyed to the task that will
land it. `strict` is the whole mechanism: `pyproject.toml` sets no `xfail_strict`, so a lenient
`xfail` that starts passing is an `xpass` - green, silent, and indistinguishable from a row nobody
implemented. Strict, a row **cannot** start passing while its group is still listed in `AWAITING`,
so T10 to T13 each have to delete their own line to go green. The corpus being complete and the
code being incomplete are then two separate, visible facts.

The structural tests below are **not** xfailed. Whether every row states a reason, whether the
paths are unique, whether the groups are real - all of that is true today and is what stops the
corpus rotting while the parsers are written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from atrium.domain.items import CollectionType

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "naming.yaml"

#: Groups whose parser has not landed. **Each of T10-T13 deletes its own entry**, and `strict=True`
#: is what makes that mandatory rather than polite: leaving a line here once the parser works turns
#: every row in the group into a failure.
AWAITING: dict[str, str] = {
    "clean": "T10 - library/naming/clean.py",
    "movies": "T11 - library/naming/movies.py",
    "series": "T12 - library/naming/series.py",
    "music": "T13 - library/naming/music.py",
}

#: What a row may put in `expect`. A row asserts only the fields it names, so a row about title
#: extraction says nothing about season numbers and cannot go stale when something unrelated moves.
FIELDS: dict[str, frozenset[str]] = {
    "clean": frozenset({"name", "year"}),
    "movies": frozenset({"name", "year", "parts", "part_number"}),
    "series": frozenset({"series", "season", "episode", "end_episode", "name", "date"}),
    "music": frozenset({"artist", "album", "title", "track", "disc", "year"}),
}


def rows() -> list[dict[str, Any]]:
    loaded = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))
    return list(loaded["rows"])


def identify(row: dict[str, Any]) -> str:
    return f"{row['needs']}:{row['path']}"


def parse(row: dict[str, Any]) -> Any:
    """Hand the row to whichever parser owns it.

    Imported inside the function on purpose: until T10 these modules do not exist, and an import
    at the top of the file would turn a collection error into "no tests ran" rather than into the
    expected failures this file is built around.
    """
    from atrium.library import naming

    path, kind = row["path"], CollectionType(row["collection_type"])
    if row["needs"] == "clean":
        return naming.clean_name(path)
    if kind is CollectionType.MOVIES:
        return naming.parse_movie(path)
    if kind is CollectionType.TVSHOWS:
        return naming.parse_episode(path)
    return naming.parse_audio(path)


# ------------------------------------------------------------------------------------------
# The corpus itself
# ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("row", rows(), ids=identify)
def test_the_corpus(row: dict[str, Any], request: pytest.FixtureRequest) -> None:
    waiting = AWAITING.get(row["needs"])
    if waiting is not None:
        request.node.add_marker(
            pytest.mark.xfail(strict=True, reason=f"waiting for {waiting}", raises=Exception)
        )

    result = parse(row)
    for field, expected in row["expect"].items():
        actual = getattr(result, field)
        if isinstance(expected, list):
            actual = list(actual)
        assert actual == expected, (
            f"{row['path']!r}: {field} is {actual!r}, the corpus says {expected!r}.\n"
            f"This row exists because: {row['why']}\n"
            f"A failing row is either a bug or a corpus error, and telling them apart is the "
            f"work. It is not removed to make a pattern pass (plan section 6.1)."
        )


# ------------------------------------------------------------------------------------------
# The corpus's own rules, which hold today
# ------------------------------------------------------------------------------------------


def test_there_are_rows() -> None:
    """A sweep over nothing passes, and every test above would vanish silently with it."""
    assert len(rows()) > 50


@pytest.mark.parametrize("row", rows(), ids=identify)
def test_every_row_states_the_reason_it_exists(row: dict[str, Any]) -> None:
    """Plan section 6.1: a row with no reason is one nobody dares delete, and nobody dares keep."""
    why = row.get("why", "")
    assert len(why) > 20, f"{row['path']!r} says {why!r}"
    assert not why.endswith("."), f"{row['path']!r}: one line, not a paragraph"


@pytest.mark.parametrize("row", rows(), ids=identify)
def test_every_row_is_well_formed(row: dict[str, Any]) -> None:
    assert set(row) == {"path", "collection_type", "needs", "why", "expect"}
    assert row["needs"] in FIELDS
    CollectionType(row["collection_type"])
    assert row["expect"], f"{row['path']!r} expects nothing, so it asserts nothing"
    unknown = set(row["expect"]) - FIELDS[row["needs"]]
    assert not unknown, (
        f"{row['path']!r} expects {sorted(unknown)}, which no {row['needs']} parse has"
    )


def test_no_row_is_declared_twice() -> None:
    """Two rows for one path and group would either agree, and be noise, or disagree silently."""
    keys = [identify(row) for row in rows()]
    duplicated = {key for key in keys if keys.count(key) > 1}
    assert not duplicated, f"declared twice: {sorted(duplicated)}"


def test_no_row_uses_an_absolute_path() -> None:
    """Everything here is relative to a library root, like every path in this feature."""
    for row in rows():
        assert not row["path"].startswith("/"), row["path"]


def test_every_awaiting_group_has_rows_waiting_for_it() -> None:
    """An entry in AWAITING that no row uses is a task nobody will notice has finished."""
    used = {row["needs"] for row in rows()}
    assert set(AWAITING) <= used, f"{sorted(set(AWAITING) - used)} is awaited by nothing"


def test_the_acceptance_criteria_that_live_here_are_covered() -> None:
    """AC-4 to AC-9 are the naming half of section 5, and each names its criterion in its reason."""
    reasons = " ".join(row["why"] for row in rows())
    for criterion in ("AC-4", "AC-5", "AC-6", "AC-7", "AC-8", "AC-9"):
        assert criterion in reasons, f"no row says it is there for {criterion}"


def test_the_corpus_covers_the_cases_that_break_naive_scanners() -> None:
    """Plan section 6.1 names them; this asserts the list did not quietly shrink."""
    paths = " ".join(row["path"] for row in rows())
    assert "part1" in paths, "multi-part films"
    assert "S01E02-E03" in paths, "multi-episode files"
    assert "Specials" in paths, "season zero"
    assert "24/" in paths, "a series named with digits"
    assert "2024-01-31" in paths, "date-based episodes"
    assert "CD2" in paths, "multi-disc albums"
    assert "Various Artists" in paths, "compilations"
    assert "Amélie" in paths, "non-ASCII names"
    assert "the film (1999).mkv" in paths, "names differing only by case"
