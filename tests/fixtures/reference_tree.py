# SPDX-License-Identifier: GPL-3.0-or-later
"""The fixture tree as a reference instance is given it.

The entry point 010 plan section 6.6 names.

`tools/_reference.py` builds no tree: the caller hands it a root and it mounts that root read-only.
The harness therefore needs one place that says *which tree, in how many libraries, of which
collection types*, and this is it — in `tests/` rather than in `tools/` because the tree is the one
`tests/fixtures/library/generate.py` already builds and a second generator would disagree with the
first the day either changed (plan section 6.6).

**Nothing here is a third fixture world.** It is the declared 003 tree and the collection types its
own manifest gives each library, handed across the mount unchanged. The fixed modification time
`generate.py` stamps is load-bearing across that mount and a bind preserves it; a copy would not,
and a fixture whose timestamps moved between the two servers would put a difference into
`DateCreated` on every item — a field the allowlist excuses, which is worse than a visible failure
because the noise would be invisible.

Standard library only, and it imports nothing but the generator: `tools/probe_reference_scan.py`
reaches it from a `tools/` script on the Python 3.9 floor, where nothing of this project's runtime
environment exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from tests.fixtures.library.generate import build as build_fixture_library
from tests.fixtures.library.manifest import LIBRARIES


class ReferenceLibrary(NamedTuple):
    """One library the instance is asked to make over the mounted tree.

    `subpath` is where the library's root sits **under the mount**, which is what lets one bind
    mount carry three libraries. It is the directory name `generate.build` writes each library to,
    so the two cannot drift: a library renamed in the manifest is renamed here by construction.
    """

    name: str
    collection_type: str
    subpath: str


def libraries() -> tuple[ReferenceLibrary, ...]:
    """The libraries of the declared tree, in declaration order.

    Typed rather than mixed, and that is a measurement: a mixed-content library is what the
    reference makes when `AddVirtualFolder` is called without a collection type, and it is not what
    Atrium is being compared against — Atrium's own libraries carry the collection types this
    manifest declares, and a comparison that gave one server three typed libraries and the other one
    untyped library would be measuring the typing rather than the scan.
    """
    return tuple(
        ReferenceLibrary(
            name=library.name,
            collection_type=library.collection_type,
            subpath=library.name,
        )
        for library in LIBRARIES
    )


def build(destination: Path) -> Path:
    """Write the tree under `destination` and return the root a reference instance mounts.

    The root is `destination` itself: each library lands in a directory named after it, so the
    mount carries all three and `ReferenceLibrary.subpath` names each one under it.
    """
    destination.mkdir(parents=True, exist_ok=True)
    build_fixture_library(destination)
    return destination
