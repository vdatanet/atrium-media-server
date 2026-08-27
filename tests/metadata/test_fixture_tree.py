# SPDX-License-Identifier: GPL-3.0-or-later
"""The checked-in fixture tree is exactly what it declares, and nothing in it is anybody's work.

003 held that property by committing no bytes at all. 004 has to commit bytes - a sidecar has to
be parsed, a container has to be opened - so the property is held from the other side: the tree
matches `inventory.py` in both directions, and two size caps make a file that passes too small to
be a recognisable piece of somebody's film or record.

The caps are not belt-and-braces over the hashes. A hash says *these* bytes were reviewed once; a
cap says whatever anybody adds later cannot be a copyrighted work even if the table is updated in
the same commit.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.fixtures.metadata.inventory import (
    BANNER,
    DESCRIBED_BY_A_README,
    FILES,
    MAX_FILE_BYTES,
    MAX_TREE_BYTES,
    NOT_SELF_DESCRIBING,
)

TREE = Path(__file__).resolve().parents[1] / "fixtures" / "metadata"


def _committed() -> list[Path]:
    return sorted(
        path
        for path in TREE.rglob("*")
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    )


def test_nothing_is_in_the_tree_that_the_inventory_does_not_declare() -> None:
    """The `.mkv` somebody helpfully added as an example."""
    found = {str(path.relative_to(TREE)) for path in _committed() if path.name != "README.md"}
    assert found == set(FILES), (
        f"undeclared: {sorted(found - set(FILES))}; missing: {sorted(set(FILES) - found)}. "
        f"Every committed byte under tests/fixtures/metadata is declared in inventory.py - that "
        f"is what keeps 'no fixture file is a copyrighted work' a property rather than a promise."
    )


@pytest.mark.parametrize("name", sorted(FILES))
def test_every_declared_file_still_has_the_bytes_it_was_committed_with(name: str) -> None:
    """The poster somebody swapped in behind an unchanged name."""
    raw = (TREE / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest()[:32] == FILES[name]


@pytest.mark.parametrize("name", sorted(FILES))
def test_no_fixture_is_large_enough_to_be_somebody_elses_work(name: str) -> None:
    """Measured on disk, not on a declared size: a cap read out of the same table it guards
    would be a cap somebody can raise by regenerating."""
    assert (TREE / name).stat().st_size <= MAX_FILE_BYTES


def test_the_tree_as_a_whole_stays_small() -> None:
    assert sum((TREE / name).stat().st_size for name in FILES) <= MAX_TREE_BYTES


def test_every_text_fixture_says_what_it_is() -> None:
    """A human who opens one should not have to read the inventory to know it is synthetic.

    A JSON payload cannot carry a comment, and putting one *in* the payload would change the shape
    the parser is being tested against - so a directory of them is described by a `README.md`
    beside them. The README has to actually be there.
    """
    for path in _committed():
        if path.name in NOT_SELF_DESCRIBING:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # a container or an image, which cannot carry a sentence
        if path.suffix in DESCRIBED_BY_A_README:
            assert (path.parent / "README.md").is_file(), (
                f"{path.relative_to(TREE)} cannot carry a banner and has no README beside it"
            )
            continue
        assert BANNER in text, f"{path.relative_to(TREE)} does not say it is synthetic"


def test_the_audio_templates_carry_no_tag_fields() -> None:
    """A template with tags of its own would put a tool's version inside every test case.

    Each muxer wrote its own `encoder` tag despite `-map_metadata -1` and `-bitexact`, and each
    was removed once, by hand, before the bytes were committed (README.md). Asserted here on the
    bytes rather than through mutagen, which is not a dependency until T7: the three tag systems
    name their fields in the file, so the field name is what must be absent.

    **What this does not assert.** All four containers still carry their muxer's version in a
    header field that is part of the format rather than a tag - the vendor string of a Vorbis
    comment block, the `Info` frame of an MP3, an atom in an M4A. A tag reader never returns
    those, so no test case can see them, and rewriting them would mean re-deriving each format's
    length fields for no gain. The property that matters - **a tag reader finds nothing** - needs
    a tag reader, and T7 asserts it the moment there is one.
    """
    fields = (b"REPLAYGAIN", b"TITLE=", b"ARTIST=", b"ALBUM=", b"TPE1", b"TALB", b"TIT2")
    for name in sorted(FILES):
        if not name.startswith("audio/"):
            continue
        raw = (TREE / name).read_bytes().upper()
        present = [f.decode() for f in fields if f in raw]
        assert not present, f"{name} already carries {present}"
