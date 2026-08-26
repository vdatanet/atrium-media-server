# SPDX-License-Identifier: GPL-3.0-or-later
"""Comparing a response to the bytes a client actually receives.

A golden test issues a request and compares the **raw body bytes** to a file checked in under
`tests/golden/`. The rule from
docs/compatibility/conformance.md section L1 is the whole point of the exercise:

> Compare bytes, not parsed objects. Casing, `null`-versus-absent and integer-versus-string are all
> part of the contract and all invisible after parsing.

`assert body["ItemId"] == ...` cannot fail on any of those. This can.

**Placeholders exist because a value is unstable, never because it is inconvenient.** Everything
that *can* be pinned is pinned in the fixture instead - see `test_golden.py`, which fixes the
server identity, the advertised address and the host architecture rather than substituting them
afterwards. Substitution is the last resort, and it keeps the quoting: a value replaced inside its
quotes still fails the comparison if it stops being a string.

**Golden files are reviewed, never blindly regenerated.** `--update-golden` writes them, and the
run then says so in the summary, because a diff in a golden file is a contract change.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest

#: Where the checked-in bodies live. tests/golden/, beside tests/conformance/.
GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"

UPDATE_OPTION = "--update-golden"

#: Names rewritten during this run, reported in the terminal summary by the root conftest.
REWRITTEN = pytest.StashKey[set[str]]()


def path_for(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def normalise(body: bytes, placeholders: Mapping[str, str]) -> bytes:
    """Replace each unstable value with its placeholder, in the body's own encoding.

    The replacement is done on the JSON-escaped spelling as well as the plain one, because a
    Windows path arrives on the wire with its separators doubled and would otherwise slip past.
    """
    for value, placeholder in placeholders.items():
        if not value:
            continue
        body = body.replace(value.encode("utf-8"), placeholder.encode("utf-8"))
        escaped = json.dumps(value)[1:-1]
        if escaped != value:
            body = body.replace(escaped.encode("utf-8"), placeholder.encode("utf-8"))
    return body


def _pretty(body: bytes) -> list[str]:
    """A readable rendering of a body, for the failure message only."""
    try:
        return json.dumps(json.loads(body), indent=2).splitlines()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [repr(body)]


def _first_difference(expected: bytes, actual: bytes) -> str:
    for offset, (left, right) in enumerate(zip(expected, actual, strict=False)):
        if left != right:
            window = slice(max(0, offset - 30), offset + 30)
            return (
                f"first difference at byte {offset}:\n"
                f"  golden   ...{expected[window]!r}...\n"
                f"  received ...{actual[window]!r}..."
            )
    return f"identical for {min(len(expected), len(actual))} bytes, then the lengths differ"


def assert_golden(
    name: str,
    response: httpx.Response,
    *,
    config: pytest.Config,
    placeholders: Mapping[str, str] | None = None,
) -> bytes:
    """Assert `response`'s body is byte-for-byte the golden `name`. Returns the compared bytes."""
    actual = normalise(response.content, placeholders or {})
    golden = path_for(name)

    if config.getoption(UPDATE_OPTION):
        if not golden.is_file() or golden.read_bytes() != actual:
            golden.parent.mkdir(parents=True, exist_ok=True)
            golden.write_bytes(actual)
            config.stash.setdefault(REWRITTEN, set()).add(golden.name)
        return actual

    if not golden.is_file():
        pytest.fail(
            f"there is no golden response at {golden.relative_to(Path.cwd())}.\n"
            f"Create it with `uv run pytest {UPDATE_OPTION}`, then read what it wrote: a golden "
            f"file is a statement about the contract, so it is reviewed like one."
        )

    expected = golden.read_bytes()
    if expected == actual:
        return actual

    diff = "\n".join(
        difflib.unified_diff(
            _pretty(expected),
            _pretty(actual),
            fromfile=f"golden/{golden.name}",
            tofile="received",
            lineterm="",
        )
    )
    pytest.fail(
        f"the response no longer matches golden/{golden.name}.\n\n"
        f"{diff or '(the parsed documents are equal; only the bytes differ)'}\n\n"
        f"{_first_difference(expected, actual)}\n\n"
        f"If this change is intended it is a change to what clients receive. Regenerate with "
        f"`uv run pytest {UPDATE_OPTION}` and put the diff in the pull request."
    )


__all__ = ["GOLDEN_DIR", "REWRITTEN", "UPDATE_OPTION", "assert_golden", "normalise", "path_for"]
