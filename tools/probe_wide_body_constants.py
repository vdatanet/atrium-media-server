#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which properties does a **full body** carry that a list row does not, and for which types?

005's §3.2 has carried a per-type matrix for list rows since T9 and, since 2026-09-03, an
eight-row table for what the two wide widths add. That table says *"and a list row carries none of
them"* and says nothing about **type**, because every one of its eight is on every type. This
probe asks the question the next tranche needs: of the properties 010's sweep reported missing
from a wide body, which types actually carry them, and does any of them also travel on a list row?

It reads **every item of every library twice** - once as it arrives in a listing, once as
`GET /Items/{itemId}` - so a per-type answer is a count over all of them rather than a sample. On
this repository's fixture that is 81 rows and 81 bodies.

**It never touches a server somebody owns.** The question needs a library scanned into the server
being asked, which is a write, so this stands up a single-use instance of the pinned version over
a tree it builds itself and destroys both, including on failure - `probe_reference_scan.py`'s rule
and for its reason.

**What it cannot answer, and says so rather than guessing.** Every value in the fixture's answers
is empty - `[]`, `{}`, `""`, `0` - because the tree carries no metadata of any kind. That is what
makes three of these safe to replicate as constants and the rest not: a field whose *only* observed
value is empty may be a constant or may be a real value this fixture cannot produce, and the two
are told apart by what the server under test could know, not by this reading. The report prints the
distinction rather than concluding it.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_wide_body_constants.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: This probe's own tree, like every other instance-owning probe's: one directory per question, so
#: that two of them cannot read each other's leftovers.
TREE = REPOSITORY / "reference" / "wide-body-tree"

#: The properties 010's sweep reported absent from a wide body, plus the two aggregates that make
#: the music containers' answer ambiguous. Every one is read at both widths.
WANTED: Tuple[str, ...] = (
    "ProductionLocations",
    "Trickplay",
    "AirDays",
    "SeriesStudio",
    "CumulativeRunTimeTicks",
    "RunTimeTicks",
    "AlbumCount",
    "SongCount",
    "ArtistCount",
    "MusicVideoCount",
    "MovieCount",
    "SeriesCount",
    "EpisodeCount",
    "ProgramCount",
    "TrailerCount",
    "ChildCount",
    "RecursiveItemCount",
)

#: What 005 §3.2 claims after the 2026-09-06 amendment, as `property -> (widths, types)`. A run
#: that disagrees exits non-zero and names the row to correct (010 AC-7, AC-8).
EXPECTATION = (
    "005 section 3.2: ProductionLocations is on a full body of a Movie and nowhere else, "
    "Trickplay on a full body of a Movie and an Episode and nowhere else, and AirDays on a Series "
    "at both widths and on no other type"
)

DOCUMENT = "specs/005-item-query-api/spec.md"
SECTION = "section 3.2"

#: `property -> (types carrying it on a FULL body, types carrying it on a LIST row)`.
CLAIMED: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "ProductionLocations": (("Movie",), ()),
    "Trickplay": (("Movie", "Episode"), ()),
    "AirDays": (("Series",), ("Series",)),
}


def load(name: str) -> Any:
    """A sibling of this script, loaded by path and on first use, never at import."""
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
            f"could not import tests.fixtures.reference_tree from {REPOSITORY}: {failure}"
        ) from failure
    return reference_tree


def read_both_widths(server: Any) -> Tuple[Dict[str, List[Any]], Dict[str, List[Any]]]:
    """Every item as a list row, and every item as a full body, keyed by type."""
    rows: Dict[str, List[Any]] = defaultdict(list)
    bodies: Dict[str, List[Any]] = defaultdict(list)
    for view in server.get("/UserViews", userId=server.user_id).get("Items", []):
        answer = server.get(
            "/Items",
            userId=server.user_id,
            parentId=str(view["Id"]),
            recursive="true",
            limit=10000,
            sortBy="SortName",
        )
        for item in answer.get("Items", []):
            kind = str(item.get("Type", ""))
            rows[kind].append(item)
            bodies[kind].append(server.get(f"/Items/{item['Id']}", userId=server.user_id))
    return dict(rows), dict(bodies)


def carrying(seen: Dict[str, List[Any]], field: str) -> Dict[str, Tuple[int, int, str]]:
    """`type -> (how many carry it, how many were read, the distinct values seen)`."""
    found: Dict[str, Tuple[int, int, str]] = {}
    for kind, items in sorted(seen.items()):
        present = [one for one in items if field in one]
        if not present:
            continue
        values = sorted({json.dumps(one[field])[:24] for one in present})
        found[kind] = (len(present), len(items), ", ".join(values[:3]))
    return found


def partial(seen: Dict[str, List[Any]], field: str) -> List[str]:
    """Types where **some** items carry the field and some do not, which no claim here allows."""
    uneven = []
    for kind, (count, total, _) in carrying(seen, field).items():
        if count != total:
            uneven.append(f"{field} on {count} of {total} {kind} rows")
    return uneven


class Run:
    def __init__(self) -> None:
        self.tree: Optional[Path] = None
        self.libraries: Tuple[Any, ...] = ()

    def build_tree(self, entry_point: Any) -> Path:
        if TREE.exists():
            shutil.rmtree(TREE, ignore_errors=True)
        self.tree = entry_point.build(TREE)
        self.libraries = tuple(entry_point.libraries())
        return TREE

    def drop_tree(self) -> None:
        if TREE.is_dir():
            shutil.rmtree(TREE, ignore_errors=True)

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Answering its question means adding a "
                "library and scanning it, which is a write, so it measures only an instance it "
                "creates and destroys itself - never a server somebody owns"
            )
        tree = self.build_tree(fixture_entry_point())
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
    rows, bodies = read_both_widths(server)

    found = probe.Probe(
        script="probe_wide_body_constants.py",
        question=(
            "Which properties does a full body carry that a list row does not, and for which types?"
        ),
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )
    found.observe("types read", ", ".join(sorted(bodies)))
    found.observe("items read at each width", sum(len(one) for one in bodies.values()))
    for field in WANTED:
        on_body = carrying(bodies, field)
        on_row = carrying(rows, field)
        found.observe(
            field,
            "full: {} | row: {}".format(
                "; ".join(f"{k} {v[0]}/{v[1]} = {v[2]}" for k, v in on_body.items()) or "-",
                "; ".join(f"{k} {v[0]}/{v[1]}" for k, v in on_row.items()) or "-",
            ),
        )

    wrong: List[str] = []
    for field, (full_types, row_types) in CLAIMED.items():
        on_body = set(carrying(bodies, field))
        on_row = set(carrying(rows, field))
        if on_body != set(full_types):
            wrong.append(f"{field} on a full body: {sorted(on_body)} against {list(full_types)}")
        if on_row != set(row_types):
            wrong.append(f"{field} on a list row: {sorted(on_row)} against {list(row_types)}")
        wrong.extend(partial(bodies, field))

    for one in wrong:
        found.note(one)
    found.conclude(
        (
            "the three replicated properties are on exactly the types 005 section 3.2 names, at "
            "the widths it names, and on every item of each - the rest of the tranche is reported "
            "above and decided nowhere here"
        )
        if not wrong
        else "the per-type shape of a wide body is not what section 3.2 says: " + "; ".join(wrong),
        matches_documentation=not wrong,
    )
    return found


def main() -> int:
    run = Run()
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "Read every item of this repository's fixture at both widths on a single-use "
                "reference instance, and report which properties a full body carries per type. "
                "Stands the instance up and destroys it, including on failure."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=run.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
