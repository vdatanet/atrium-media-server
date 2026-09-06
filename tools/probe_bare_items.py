#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What IS a bare `GET /Items` — and which parameters can change the answer?

010's first kept differential run reported the sharpest single row it found against 005 and put it
in none of its five classes: `GET /Items` with no parameters answered **77 rows here against 7**,
so the two servers disagree about what a bare listing *is*. The `LENGTH` guard stops the difference
cascading, so it costs four rows in a report and is worth more than four.

This probe asks the question that difference poses, and asks it **one parameter at a time**,
because the shape of the answer turned out to be the finding: with no `parentId`, without
`recursive`, and with no `ids`, the reference answers the reading account's top-level folders and
ignores everything else it was given - including `limit`, which is the reading that makes this a
*shape* rather than a narrowing, and including every filter a client might reasonably expect to
work. `ids` is the one escape, and it is measured here rather than assumed: without that reading, a
server replicating this would answer the folders to a client asking about one film by identifier.

**It never touches a server somebody owns**: the question needs a library scanned into the server
being asked, which is a write, so this stands up a single-use instance over a tree it builds itself
and destroys both, including on failure.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_bare_items.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

TREE = REPOSITORY / "reference" / "bare-items-tree"

EXPECTATION = (
    "005 section 3.3: a GET /Items with no parentId, without recursive and with no ids answers "
    "the reading account's top-level folders and ignores every other parameter, including limit; "
    "ids is the one parameter that escapes the shape"
)

DOCUMENT = "specs/005-item-query-api/spec.md"
SECTION = "section 3.3"

#: One request each, and the point is that all of them answer the same six rows. Every one is a
#: parameter a client sends and would expect to narrow a listing.
IGNORED: Tuple[Tuple[str, Dict[str, Any]], ...] = (
    ("includeItemTypes=Movie", {"includeItemTypes": "Movie"}),
    ("includeItemTypes=CollectionFolder", {"includeItemTypes": "CollectionFolder"}),
    ("excludeItemTypes=CollectionFolder", {"excludeItemTypes": "CollectionFolder"}),
    ("mediaTypes=Video", {"mediaTypes": "Video"}),
    ("searchTerm=a", {"searchTerm": "a"}),
    ("nameStartsWith=A", {"nameStartsWith": "A"}),
    ("years=2003", {"years": 2003}),
    ("genres=Rock", {"genres": "Rock"}),
    ("filters=IsFavorite", {"filters": "IsFavorite"}),
    ("isPlayed=false", {"isPlayed": "false"}),
    ("isFolder=false", {"isFolder": "false"}),
    ("sortBy=SortName&sortOrder=Descending", {"sortBy": "SortName", "sortOrder": "Descending"}),
    ("sortBy=Random", {"sortBy": "Random"}),
    ("limit=2", {"limit": 2}),
    ("startIndex=2", {"startIndex": 2}),
    ("recursive=false", {"recursive": "false"}),
)


def load(name: str) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    if spec is None or spec.loader is None:  # pragma: no cover - the files are beside this one
        raise SystemExit(f"tools/{name}.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture_entry_point() -> Any:
    root = str(REPOSITORY)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from tests.fixtures import reference_tree
    except ImportError as failure:  # pragma: no cover - a checkout missing its own tests
        probe = load("_probe")
        raise probe.ProbeError(
            f"could not import tests.fixtures.reference_tree: {failure}"
        ) from failure
    return reference_tree


def shape_of(server: Any, **params: Any) -> Tuple[int, int, Tuple[str, ...], Tuple[str, ...]]:
    """`(total, rows returned, the types, the names)` for one request."""
    answer = server.get("/Items", userId=server.user_id, **params)
    rows = answer.get("Items", [])
    return (
        int(answer.get("TotalRecordCount", 0)),
        len(rows),
        tuple(sorted({str(one.get("Type", "")) for one in rows})),
        tuple(str(one.get("Name", "")) for one in rows),
    )


class Run:
    def __init__(self) -> None:
        self.libraries: Tuple[Any, ...] = ()

    def drop_tree(self) -> None:
        if TREE.is_dir():
            shutil.rmtree(TREE, ignore_errors=True)

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument: answering its question means scanning a "
                "library into the server being asked, which is a write"
            )
        entry_point = fixture_entry_point()
        if TREE.exists():
            shutil.rmtree(TREE, ignore_errors=True)
        tree = entry_point.build(TREE)
        self.libraries = tuple(entry_point.libraries())
        libraries = tuple(
            reference.Library(
                name=one.name,
                collection_type=one.collection_type,
                subpath=one.subpath,
                internet_providers=False,
            )
            for one in self.libraries
        )
        try:
            with reference.ReferenceInstance(
                reference.InstanceSpec(fixture_root=tree, libraries=libraries)
            ) as instance:
                server = probe.Server(instance.url)
                server.connect(
                    instance.administrator.username, instance.administrator.password, None
                )
                yield server
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure
        finally:
            self.drop_tree()


def measure(server: Any, args: argparse.Namespace) -> Any:
    probe = load("_probe")
    bare_total, bare_rows, bare_types, bare_names = shape_of(server)

    moved: List[str] = []
    for label, params in IGNORED:
        total, rows, _types, names = shape_of(server, **params)
        if (total, rows, names) != (bare_total, bare_rows, bare_names):
            moved.append(f"{label} answered {rows} rows of {total}: {list(names)[:4]}")

    # The one parameter that must NOT be ignored, read against a real item.
    # Recursively from the root rather than under one view: which view is first is the server's
    # business, and asking a music library for a film finds nothing and reports it as a failed
    # escape - which is this probe getting its own question wrong, not an answer.
    films = server.get(
        "/Items", userId=server.user_id, recursive="true", includeItemTypes="Movie"
    ).get("Items", [])
    escaped = ()
    if films:
        escaped = shape_of(server, ids=str(films[0]["Id"]))

    recursive = shape_of(server, recursive="true")

    found = probe.Probe(
        script="probe_bare_items.py",
        question="What is a bare GET /Items, and which parameters can change it?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )
    found.observe("bare: rows", f"{bare_rows} of {bare_total}")
    found.observe("bare: types", ", ".join(bare_types))
    found.observe("bare: names", ", ".join(bare_names))
    found.observe(
        "parameters that changed nothing", f"{len(IGNORED) - len(moved)} of {len(IGNORED)}"
    )
    found.observe("recursive=true: rows", f"{recursive[1]} of {recursive[0]}")
    found.observe(
        "ids=<a film>: rows",
        f"{escaped[1] if escaped else '-'} {list(escaped[2]) if escaped else ''}",
    )
    for one in moved:
        found.note(one)

    ids_escaped = bool(escaped) and escaped[1] == 1 and escaped[2] == ("Movie",)
    held = not moved and ids_escaped and recursive[1] > bare_rows
    found.conclude(
        (
            f"a bare GET /Items is the account's {bare_rows} top-level folders, and "
            f"{len(IGNORED)} parameters a client would expect to narrow it change nothing at all - "
            f"limit and startIndex among them. `ids` escapes the shape and answers the item named; "
            f"`recursive=true` answers the whole library ({recursive[0]} rows)"
        )
        if held
        else (
            f"the shape is not what section 3.3 says: {len(moved)} parameters moved the answer"
            f"{'' if ids_escaped else ', and ids did not escape it'}"
        ),
        matches_documentation=held,
    )
    return found


def main() -> int:
    run = Run()
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "Measure what a bare GET /Items is on the reference, one parameter at a time, on "
                "a single-use instance this probe creates and destroys."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=run.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
