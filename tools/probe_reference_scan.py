#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a reference server's library contain, given this repository's fixture tree?

That is **D-4**, reserved by 010's plan on 2026-09-01 with its dependency stated: the 003 tree is
paths and filler bytes by design - its own generator says *"these are not decodable media"* - and
whether a reference makes items out of a file its prober cannot open was unmeasured, because
answering it needs a library scan and a scan is a **write**. The only reachable Jellyfin was an
operator's production server. This probe is the first run of the instance 010 T9 built, and it is
the task that takes the measurement (plan section 6.6, section 11 D-4).

**It never touches a server somebody owns.** It stands up a single-use instance of the pinned
version over a tree it builds itself, reads it, and destroys it - including on failure. Naming a
server on the command line is refused rather than honoured, because the question cannot be asked
without writing a library into the server being asked.

**And it writes the answer down.** `docs/compatibility/reference-fixture-reading.json` is the
reference's own reading of the fixture, with this probe's citation inside it, and
`tests/library/test_reference_reading.py` compares Atrium's scan of the same tree against that
file. Both servers are needed to *make* the reading, which is what this probe is for and what a
version bump re-runs; what is no longer needed to *check* it is a second server, so AC-2 is a test
in the default CI job rather than a command somebody remembers to run.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_reference_scan.py --allow-writes
    python3 tools/probe_reference_scan.py --allow-writes --skip-provider-comparison
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: Where the reading lands. JSON rather than the YAML the hand-written registers use, for the
#: reason `docs/compatibility/property-names.json` is JSON: a file a program writes is read by a
#: program, and the prose that would justify a row belongs in the probe that took it.
RECORD = REPOSITORY / "docs" / "compatibility" / "reference-fixture-reading.json"

#: Where the tree is built, and **not** a system temporary directory. A container runtime mounts
#: only the host paths it has been given, and on macOS the directory `tempfile` picks - under
#: `/var/folders` - is not one of them: the container starts, finds nothing at the mount, and exits
#: before it has answered anything, which arrives as a readiness timeout three minutes later. The
#: repository is a path the runtime can reach by construction, since the runtime is being driven
#: from it, and `reference/` is already git-ignored as the place development-time material lands.
TREE = REPOSITORY / "reference" / "fixture-tree"

#: What the documentation claims today, and therefore what a finding is measured against (AC-7).
#: Changed on 2026-09-02, in the commit that took the measurement: the plan's default was that the
#: reference makes nothing of a tree it cannot decode, and the first run of this probe contradicted
#: it. A run that finds the default true again is a behaviour that changed, and it exits non-zero
#: and says which document to update (AC-8).
EXPECTATION = (
    "010 plan section 6.6 and section 11 D-4: the reference DOES make items out of the 003 "
    "tree - measured 2026-09-02 - so both worlds go across as libraries of their own and AC-2 "
    "compares both"
)

DOCUMENT = "specs/010-conformance-harness/plan.md"
SECTION = "section 6.6 and section 11 D-4"


def load(name: str) -> Any:
    """A sibling of this script, loaded by path and **on first use, never at import**.

    `tools/` is a directory of standalone programs and not an importable package, which is how
    every other tool here reaches its siblings. Loading on first use is what keeps `--help` from
    touching a runtime, a server or a tree.
    """
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
    """`tests/fixtures/reference_tree.py`, the entry point plan section 6.6 names.

    Imported rather than reimplemented: the tree the reference is given has to be the tree the
    suite builds, and a second generator would disagree with the first the day either changed.
    The repository root goes on the path because `tests/` is a package of this repository and not
    an installed one; nothing else about the environment is needed, since that module and the
    generator under it are standard library only.
    """
    root = str(REPOSITORY)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from tests.fixtures import reference_tree
    except ImportError as failure:  # pragma: no cover - a checkout missing its own tests
        probe = load("_probe")
        raise probe.ProbeError(
            f"could not import tests.fixtures.reference_tree from {REPOSITORY}: {failure}. "
            "The probe builds the fixture through the suite's own generator, so that the tree "
            "the reference is given is the tree the suite asserts against"
        ) from failure
    return reference_tree


# --------------------------------------------------------------------------------------------
# Reading one instance
# --------------------------------------------------------------------------------------------


def files_under(root: Path) -> Dict[str, Tuple[str, int]]:
    """Every file of one library root, by its path relative to that root.

    This is what tells a row that names a **file** from a row that names a **directory**: the
    reference gives a `Path` to both - a season is a directory and an episode is a file - and the
    two are not comparable things. Atrium's containers have no path at all, because a path in this
    project belongs to a media source and a container has none.
    """
    found: Dict[str, Tuple[str, int]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found[path.relative_to(root).as_posix()] = (path.name, path.stat().st_size)
    return found


def read_library(server: Any, view_id: str, mount: str, files: Dict[str, Tuple[str, int]]) -> Any:
    """Every item of one library, canonicalised into rows two servers can be compared on.

    `recursive=true` and `fields=Path`, because **the path is not on a default list row** - 0 of
    1000, measured at this feature's own gate `[probe: tools/probe_differential_join.py, Jellyfin
    10.11.11, 2026-09-01]` - and it is the only value two servers scanning one tree can agree on.
    Here it is asked for by name, which OQ-1 rejected for the *sweep* because it changes the
    request a client sends; for a scan reading there is no client and no request to preserve.
    """
    answer = server.get(
        "/Items",
        userId=server.user_id,
        parentId=view_id,
        recursive="true",
        fields="Path",
        limit=10000,
        sortBy="SortName",
        sortOrder="Ascending",
    )
    items = answer.get("Items", [])
    total = int(answer.get("TotalRecordCount", len(items)))
    if total != len(items):  # pragma: no cover - the fixture is two orders below the limit
        probe = load("_probe")
        raise probe.ProbeError(
            f"the library reports {total} items and returned {len(items)}; the reading would be "
            "a page rather than a library"
        )
    rows = [row_of(item, mount, files) for item in items]
    return sorted(rows, key=lambda entry: (entry["type"], entry["name"], entry["path"] or ""))


def row_of(item: Any, mount: str, files: Dict[str, Tuple[str, int]]) -> Dict[str, Any]:
    absolute = str(item.get("Path") or "")
    relative = ""
    if absolute == mount:
        relative = ""
    elif absolute.startswith(mount + "/"):
        relative = absolute[len(mount) + 1 :]
    elif absolute:
        relative = absolute
    return {
        "type": str(item.get("Type", "")),
        "name": str(item.get("Name", "")),
        # The row's own file, when it has one. `null` for a container and for the **virtual**
        # season the reference invents for an episode whose season nothing names, which carries no
        # path at all - the same shape OQ-1 found on a virtual season of a real library.
        "file": relative if relative in files else None,
        "path": relative or None,
    }


def counts_by_type(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for entry in rows:
        counts[entry["type"]] = counts.get(entry["type"], 0) + 1
    return dict(sorted(counts.items()))


def read_instance(instance: Any, tree: Path, libraries: Sequence[Any]) -> List[Dict[str, Any]]:
    """One standing instance, read library by library."""
    probe = load("_probe")
    reference = load("_reference")
    administrator = instance.administrator
    server = probe.Server(instance.url)
    server.connect(administrator.username, administrator.password, None)

    views = {
        str(view.get("Name")): view
        for view in server.get("/UserViews", userId=server.user_id).get("Items", [])
    }
    readings: List[Dict[str, Any]] = []
    for library in libraries:
        view = views.get(library.name)
        if view is None:
            raise probe.ProbeError(
                f"the instance has no view named {library.name!r}; it has "
                f"{sorted(views)} - the library was added and the scan did not produce it"
            )
        mount = reference.FIXTURE_MOUNT
        if library.subpath:
            mount = mount + "/" + library.subpath
        rows = read_library(server, str(view["Id"]), mount, files_under(tree / library.subpath))
        readings.append(
            {
                "name": library.name,
                "collection_type": library.collection_type,
                # Carried into the record because the finding turns on it: the 003 tree is paths
                # and filler and the media world is media a prober opens, so "backed by a file
                # nothing can decode" is a statement about some of these libraries and not all of
                # them. Reading it off the entry point rather than off the file names keeps the
                # two declarations from drifting.
                "decodable": bool(library.decodable),
                "item_count": len(rows),
                "counts_by_type": counts_by_type(rows),
                "items": rows,
            }
        )
    return readings


# --------------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------------


class Scan:
    """The two readings this probe takes, and the instance the report is printed against.

    They are two because the first one was not a reading of the tree. A library added the obvious
    way - a `LibraryOptions` naming only its path - fetches metadata from the internet, and over
    the 003 tree that answered with names no part of the tree contains. The difference between the
    two readings is the finding, so the probe takes both rather than citing one it cannot
    reproduce.
    """

    def __init__(self) -> None:
        self.tree: Optional[Path] = None
        self.scratch: Optional[Path] = None
        self.libraries: Tuple[Any, ...] = ()
        self.recorded: List[Dict[str, Any]] = []
        self.fetched: List[Dict[str, Any]] = []
        self.compared_providers = False
        self.image = ""
        self.version = ""

    # -- the tree ---------------------------------------------------------------------------

    def build_tree(self, entry_point: Any) -> Path:
        # Swept before it is built, for the reason the instance sweeps before it starts: the only
        # cleanup that survives a killed run is the one the next run performs.
        if TREE.exists():
            shutil.rmtree(TREE, ignore_errors=True)
        self.scratch = TREE
        self.tree = entry_point.build(TREE)
        self.libraries = tuple(entry_point.libraries())
        return self.tree

    def drop_tree(self) -> None:
        if self.scratch is not None and self.scratch.is_dir():
            shutil.rmtree(self.scratch, ignore_errors=True)
        self.scratch = None

    # -- the instances ----------------------------------------------------------------------

    def instance_for(self, internet_providers: bool) -> Any:
        reference = load("_reference")
        libraries = tuple(
            reference.Library(
                name=library.name,
                collection_type=library.collection_type,
                subpath=library.subpath,
                internet_providers=internet_providers,
            )
            for library in self.libraries
        )
        return reference.ReferenceInstance(
            reference.InstanceSpec(fixture_root=Path(self.tree or ""), libraries=libraries)
        )

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        """Both readings, in the order that leaves the recorded one standing for the report.

        **Sequential and never nested**: an instance sweeps everything carrying the run's label
        before it starts, which is what makes a killed run harmless and what would make a second
        instance destroy the first one mid-read.
        """
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Answering its question means adding a "
                "library and scanning it, which is a write, so it measures only an instance it "
                "creates and destroys itself (010 spec section 3.1) - never a server somebody owns"
            )

        entry_point = fixture_entry_point()
        tree = self.build_tree(entry_point)
        print(
            f"fixture: {sum(1 for path in tree.rglob('*') if path.is_file())} files in "
            f"{len(self.libraries)} libraries, built by tests.fixtures.reference_tree",
            file=sys.stderr,
        )
        try:
            if not args.skip_provider_comparison:
                with self.instance_for(internet_providers=True) as fetching:
                    self.fetched = read_instance(fetching, tree, self.libraries)
                self.compared_providers = True

            with self.instance_for(internet_providers=False) as instance:
                self.image = instance.image
                administrator = instance.administrator
                server = probe.Server(instance.url)
                server.connect(administrator.username, administrator.password, None)
                self.version = server.version
                self.recorded = read_instance(instance, tree, self.libraries)
                yield server
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure
        finally:
            self.drop_tree()

    # -- the finding ------------------------------------------------------------------------

    def renamed_by_a_fetcher(self) -> List[Dict[str, str]]:
        """The rows whose name a remote provider supplied, matched on the row's own file."""
        if not self.compared_providers:
            return []
        differences: List[Dict[str, str]] = []
        # Indexed rather than zipped: `zip(..., strict=True)` is 3.10 and this floor is 3.9,
        # and a silent truncation is the failure a strict zip exists to prevent.
        for position, recorded in enumerate(self.recorded):
            fetched = self.fetched[position]
            here = {entry["path"]: entry for entry in recorded["items"] if entry["path"]}
            for entry in fetched["items"]:
                mine = here.get(entry["path"])
                if mine is not None and mine["name"] != entry["name"]:
                    differences.append(
                        {
                            "library": recorded["name"],
                            "path": str(entry["path"]),
                            "from_the_tree": mine["name"],
                            "from_a_fetcher": entry["name"],
                        }
                    )
        return differences

    def carried_forward(self, path: Path) -> Dict[str, Any]:
        """The provider comparison a previous record already holds, when this run skipped it.

        **Skipping it is the ordinary way to re-take the reading, and losing the finding with it
        would be wrong.** The comparison costs a second instance whose whole purpose is to *let*
        a third party's database answer - which is a run that contacts a metadata provider, and
        the only reason to make one is to measure that it happens. It was measured on 2026-09-02
        and it is a property of the reference and of the reference's own defaults, not of this
        repository's tree: nine names of the 003 tree came back from a fetcher, and no entry added
        here changes that.

        So a run with `--skip-provider-comparison` carries the previous record's list forward
        **with the citation it was taken under**, and says so. A reading with no such list at all
        would let `tests/library/test_reference_reading.py` stop asserting that the fetchers were
        the difference, which is the one thing keeping the record from being a reading of somebody
        else's database.
        """
        if not path.is_file():
            return {}
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:  # pragma: no cover - a hand-edited record
            return {}
        remote = previous.get("remote_metadata") or {}
        supplied = remote.get("names_a_fetcher_supplied") or []
        if not supplied:
            return {}
        return {
            "names_a_fetcher_supplied": supplied,
            "carried_forward_from": str(
                remote.get("carried_forward_from") or previous.get("citation") or ""
            ),
        }

    def record(self, path: Path, citation: str, finding: str) -> Dict[str, Any]:
        renamed = self.renamed_by_a_fetcher()
        carried = {} if self.compared_providers else self.carried_forward(path)
        document = {
            "_": (
                "The reference's own reading of this repository's fixture tree, written by the "
                "probe named below and compared against Atrium's scan by "
                "tests/library/test_reference_reading.py. Generated: edit it by re-running the "
                "probe against a reference instance, never by hand."
            ),
            "citation": citation,
            "question": (
                "Given the fixture tree, what does a reference server's library contain? "
                "(010 plan section 11, D-4)"
            ),
            "finding": finding,
            "jellyfin_version": self.version,
            "image": self.image,
            "fixture": {
                "entry_point": "tests.fixtures.reference_tree:build",
                "tree": "tests/fixtures/library (003's declared tree, paths and filler bytes)",
                "mount": load("_reference").FIXTURE_MOUNT,
            },
            "remote_metadata": {
                "enabled": False,
                "how": (
                    "LibraryOptions.TypeOptions, one entry per fetched type with an empty "
                    "MetadataFetchers list. LibraryOptions.EnableInternetProviders is declared, "
                    "stored and read by nothing in the reference"
                ),
                "names_a_fetcher_supplied": renamed or carried.get("names_a_fetcher_supplied", []),
                "compared": self.compared_providers,
                # Empty when this run took the comparison itself; the earlier probe's citation
                # when it carried the list forward, so a reader can tell a measurement from a
                # measurement that was not re-taken.
                "carried_forward_from": carried.get("carried_forward_from", ""),
            },
            "totals": {
                "libraries": len(self.recorded),
                "items": sum(library["item_count"] for library in self.recorded),
            },
            "libraries": self.recorded,
        }
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return document

    def report(self, server: Any, args: argparse.Namespace) -> Any:
        probe = load("_probe")
        today = datetime.now(timezone.utc).date().isoformat()
        citation = f"[probe: tools/probe_reference_scan.py, Jellyfin {server.version}, {today}]"

        items = sum(library["item_count"] for library in self.recorded)
        media = sum(
            1
            for library in self.recorded
            for entry in library["items"]
            if entry["file"] is not None
        )
        # **The two are counted apart, and the first run of this probe conflated them.** Until 010
        # T11 the tree was the 003 world alone, so every file-backed row was a row over a file no
        # prober could open and the finding said so about all of them. The composed tree is both
        # worlds, and calling a real `h264` file undecodable in the record would be a false
        # statement in the one document AC-2 is checked against.
        undecodable = sum(
            1
            for library in self.recorded
            if not library.get("decodable")
            for entry in library["items"]
            if entry["file"] is not None
        )
        makes_items = items > 0

        finding = (
            (
                f"the reference makes {items} items out of the fixture tree, {media} of them "
                f"backed by a file and {undecodable} of those over a file none of its probers can "
                f"open - so a tree of paths and filler bytes is a library to it, and D-4's second "
                f"branch is the measured one: both worlds go across as libraries of their own"
            )
            if makes_items
            else (
                "the reference makes no items at all out of the fixture tree, so D-4's default "
                "holds and only the media world can go across"
            )
        )

        found = probe.Probe(
            script="probe_reference_scan.py",
            question="Given the fixture tree, what does a reference server's library contain?",
            document=DOCUMENT,
            section=SECTION,
            expectation=EXPECTATION,
        )
        for library in self.recorded:
            found.observe(
                "{} ({}{})".format(
                    library["name"],
                    library["collection_type"],
                    "" if library.get("decodable") else ", filler",
                ),
                f"{library['item_count']} items: "
                + ", ".join(f"{name} {count}" for name, count in library["counts_by_type"].items()),
            )
        found.observe("items in total", items)
        found.observe("of them backed by a file", media)
        found.observe("of those over a file no prober can open", undecodable)

        renamed = self.renamed_by_a_fetcher()
        if self.compared_providers:
            found.observe("names a remote fetcher supplied", f"{len(renamed)} of {items}")
            for difference in renamed:
                found.note(
                    f"{difference['library']}/{difference['path']}: "
                    f"{difference['from_the_tree']!r} from the tree, "
                    f"{difference['from_a_fetcher']!r} from a fetcher"
                )
            found.note(
                "Those names are what a library added the obvious way answers. "
                "LibraryOptions.EnableInternetProviders does not stop them - it is declared, it "
                "stores, it reads back false, and nothing in the reference consults it "
                "[source: MediaBrowser.Model/Configuration/LibraryOptions.cs:64 @ v10.11.11]. "
                "What stops them is the library's own TypeOptions, which are an allowlist "
                "[source: MediaBrowser.Controller/BaseItemManager/BaseItemManager.cs:42 @ "
                "v10.11.11]. The item set is the same either way: only names moved."
            )
        else:
            carried = self.carried_forward(args.record)
            found.note(
                "--skip-provider-comparison: the reading was taken with the fetchers off and the "
                "one with them on was not taken, so nothing this run saw came from a metadata "
                "provider."
            )
            if carried:
                found.observe(
                    "names a remote fetcher supplied",
                    "{} carried forward from {}".format(
                        len(carried["names_a_fetcher_supplied"]),
                        carried["carried_forward_from"] or "an earlier record",
                    ),
                )

        if not args.skip_record:
            self.record(args.record, citation, finding)
            found.note(f"reading written to {args.record.relative_to(REPOSITORY)}")

        found.conclude(finding, matches_documentation=makes_items)
        return found


def options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record",
        type=Path,
        default=RECORD,
        help="Where to write the reference's reading. Defaults to "
        "docs/compatibility/reference-fixture-reading.json, which is what AC-2's test reads",
    )
    parser.add_argument(
        "--skip-record",
        action="store_true",
        help="Take the reading and print it without writing the file",
    )
    parser.add_argument(
        "--skip-provider-comparison",
        action="store_true",
        help="Take only the recorded reading. The default takes a second one with the remote "
        "metadata fetchers on, because the difference between the two is half the finding - and "
        "it costs a second instance",
    )


def main() -> int:
    scan = Scan()
    return int(
        load("_probe").main(
            scan.report,
            description=(
                "Measure what a reference server's library contains when it is given this "
                "repository's fixture tree, and write the reading down (010 T10, D-4). Stands up "
                "a single-use instance of the pinned version, reads it, and destroys it - "
                "including on failure. It never measures a server somebody owns."
            ),
            needs_writes=True,
            extra_arguments=options,
            with_args=True,
            connect_with=scan.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
