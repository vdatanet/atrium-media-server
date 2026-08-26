# SPDX-License-Identifier: GPL-3.0-or-later
"""Identifiers: lenient on the way in, canonical on the way out, derived rather than allocated."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

from atrium.compat.guids import CANONICAL, WireGuid, derive, new_id, normalise
from atrium.compat.model import AtriumModel

CANONICAL_EXAMPLE = "0d41983a5d18d53282f56e7460e2c2cd"


class Sample(AtriumModel):
    id: WireGuid


# --------------------------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------------------------


def test_new_id_is_canonical() -> None:
    for _ in range(100):
        assert CANONICAL.match(new_id())


def test_new_ids_differ() -> None:
    assert len({new_id() for _ in range(1000)}) == 1000


# --------------------------------------------------------------------------------------------
# Accepting what the reference accepts
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "accepted",
    [
        CANONICAL_EXAMPLE,
        "0D41983A5D18D53282F56E7460E2C2CD",  # uppercase
        "0d41983a-5d18-d532-82f5-6e7460e2c2cd",  # the dashed form
        "0D41983A-5D18-D532-82F5-6E7460E2C2CD",  # dashed and uppercase
        "{0d41983a-5d18-d532-82f5-6e7460e2c2cd}",  # braced, as .NET's "B" format
        "  0d41983a5d18d53282f56e7460e2c2cd  ",  # surrounding whitespace
    ],
)
def test_normalise_accepts_every_form_the_reference_parses(accepted: str) -> None:
    """A client that stored an id and sends it back dashed is served, as it would be upstream."""
    assert normalise(accepted) == CANONICAL_EXAMPLE


@pytest.mark.parametrize(
    "rejected",
    [
        "not-a-guid",
        "0d41983a",  # too short
        CANONICAL_EXAMPLE + "extra",  # too long
        "0d41983a5d18d53282f56e7460e2c2cg",  # 'g' is not hexadecimal
        "",
    ],
)
def test_the_type_rejects_what_is_not_an_identifier(rejected: str) -> None:
    with pytest.raises(ValidationError) as raised:
        Sample(id=rejected)
    assert "is not an identifier" in str(raised.value)
    assert "32 hexadecimal" in str(raised.value), (
        "the message must say what an identifier looks like; a regular expression in an error "
        "tells a reader what was wanted only if they can read one under time pressure"
    )


def test_output_is_always_canonical() -> None:
    body = json.loads(Sample(id="{0D41983A-5D18-D532-82F5-6E7460E2C2CD}").model_dump_json())
    assert body["Id"] == CANONICAL_EXAMPLE


# --------------------------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------------------------


def test_derive_is_canonical() -> None:
    assert CANONICAL.match(derive("Movie", "lib1", "Movies/The Film (1999).mkv"))


def test_derive_is_deterministic_within_a_process() -> None:
    parts = ("Movie", "lib1", "Movies/The Film (1999).mkv")
    assert derive(*parts) == derive(*parts)


def test_derive_is_deterministic_across_processes() -> None:
    """The guarantee that matters: a rescan in a new process must not change an identifier.

    Run in a subprocess rather than asserted twice in this one, because the failure mode this
    protects against - an identifier that depends on per-process state such as hash randomisation
    - is invisible to a same-process comparison.
    """
    script = (
        "from atrium.compat.guids import derive; "
        "print(derive('Movie', 'lib1', 'Movies/The Film (1999).mkv'))"
    )
    runs = [
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", script], capture_output=True, text=True, check=True
        ).stdout.strip()
        for _ in range(2)
    ]
    assert runs[0] == runs[1] == derive("Movie", "lib1", "Movies/The Film (1999).mkv")


def test_derive_separates_its_parts() -> None:
    """NUL-joined, so no two different tuples can concatenate to the same key."""
    assert derive("a", "bc") != derive("ab", "c")


def test_derive_distinguishes_item_types() -> None:
    """The same path resolved as two types is two items, and must not be one."""
    path = "Movies/The Film (1999).mkv"
    assert derive("Movie", "lib1", path) != derive("Episode", "lib1", path)


def test_derive_distinguishes_libraries() -> None:
    path = "The Film (1999).mkv"
    assert derive("Movie", "lib1", path) != derive("Movie", "lib2", path)


def test_derive_needs_something_to_derive_from() -> None:
    with pytest.raises(ValueError, match="at least one part"):
        derive()


def test_derive_handles_non_ascii_paths() -> None:
    assert CANONICAL.match(derive("Movie", "lib1", "Pel·lícules/Amélie (2001).mkv"))
    assert derive("Movie", "lib1", "Amélie") != derive("Movie", "lib1", "Amelie")
