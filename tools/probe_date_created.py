#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where does the reference get an item's `DateCreated` from?

The question 003's handover list left open on 2026-09-05, and it left it open with a **wrong
premise**: it said the reference takes the file's modification time *"which the fixture generator
fixes, so its items carry distinct and reproducible dates"*. When this probe was written the
generator fixed one instant for the *whole tree*, so the reference's dates were as tied as
Atrium's. **This probe marks five paths before the scan**, which is the whole reason it is a
program and not a reading: known instants years apart are what tell a modification time from a
directory's time from the moment of the scan, and no unmarked tree can do that however its times
are spread. The generators give each file its own fixed instant from 2026-09-06 - which makes the
orderings total and changes nothing here, because what these marks buy is knowing what the answer
should be rather than merely that answers differ.

What it measures, in one instance:

1. **A file-backed item's date, against its own file's modification time.** Three films are stamped
   with times years apart from each other and from the tree's fixed instant.
2. **A container's date, against its directory's.** One season directory is stamped four years into
   the past: if a container took its directory's time, that is where it would show.
3. **Which part of a two-part item speaks for it.** The two parts of one film are stamped two years
   apart, and the item carries one of them.
4. **Whether the date follows the file or records a first sighting.** One film's modification time
   is moved *after* the first scan and the library is refreshed, which is the reading that decides
   whether the column belongs on the update path as well as the insert path.

**It never touches a server somebody owns.** Answering the question means adding a library and
scanning it, which is a write, so the probe stands up a single-use instance of the pinned version
over a tree it builds itself and destroys both - including on failure. A server named on the
command line is refused rather than honoured, which is `probe_reference_scan.py`'s rule and for its
reason.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_date_created.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: This probe's own tree, and **not** `probe_reference_scan.py`'s. The two build the same fixture
#: from the same entry point, and this one stamps four paths inside it before the scan - so sharing
#: a directory would leave the other probe's next run reading a tree this one had marked.
TREE = REPOSITORY / "reference" / "date-created-tree"

#: What the documentation claims, and therefore what a finding is measured against (010 AC-7, AC-8).
#: Written on 2026-09-06 by the run that took the measurement: before it, no document in this
#: repository said where the field comes from, and 003's handover said something about the fixture
#: that was not true. A run that contradicts this exits non-zero and says which document to update.
EXPECTATION = (
    "behaviours section 2.29 and 003 spec section 3.9: a file-backed item's DateCreated is its "
    "file's modification time and follows it across a rescan; a container's is the moment the "
    "scan made the row, and not its directory's modification time; a two-part item carries the "
    "time of the part its Path names"
)

DOCUMENT = "docs/compatibility/behaviours.md"
SECTION = "section 2.29"

#: The four marks, as `(path under the tree, the time it is given, what it is here to answer)`.
#: Years apart from each other and from the tree's fixed instant, so that no reading can be a
#: coincidence and every failure names which mark it was.
MARKS: Tuple[Tuple[str, str, str], ...] = (
    ("Movies/2 Fast 2 Furious (2003).mkv", "2019-05-06T07:08:09Z", "a film's own file"),
    ("Movies/Wall-E (2008).mkv", "2020-06-07T08:09:10Z", "the film whose time moves later"),
    ("Shows/The Series/Season 02", "2022-08-09T10:11:12Z", "a season's directory"),
    (
        "Decodable/Movies/The Two Parter (2006)/The Two Parter (2006) - part1.mkv",
        "2013-01-01T01:01:01Z",
        "part one of a two-part film",
    ),
    (
        "Decodable/Movies/The Two Parter (2006)/The Two Parter (2006) - part2.mkv",
        "2015-02-02T02:02:02Z",
        "part two of the same film",
    ),
)

#: Where the film of mark two is moved to, after the first reading. Earlier than the time it was
#: given, so that a server which simply re-stamped everything with the clock could not pass.
MOVED_TO = "2017-03-02T01:02:03Z"

MOUNT = "/fixture"


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
    """`tests/fixtures/reference_tree.py`, imported rather than reimplemented.

    The tree this probe marks has to be the tree the suite builds, or the marks would be describing
    a fixture nothing else has.
    """
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


def moment(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def stamp(path: Path, text: str) -> datetime:
    """Give one path a modification time, and hand back what it now says."""
    when = moment(text)
    nanoseconds = int(when.timestamp()) * 1_000_000_000
    os.utime(path, ns=(nanoseconds, nanoseconds))
    return when


def parse(value: str) -> Optional[datetime]:
    """The reference's round-trip format, which carries seven fractional digits.

    `fromisoformat` on the 3.9 floor accepts three or six and not seven, so the fraction is cut to
    six rather than handed to a parser that would raise on the reference's own spelling.
    """
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        digits = tail[: tail.index("+")] if "+" in tail else tail
        offset = tail[tail.index("+") :] if "+" in tail else ""
        text = head + "." + digits[:6] + offset
    return datetime.fromisoformat(text)


def read(server: Any) -> List[Dict[str, Any]]:
    """Every item of every library, with the two fields this probe is about.

    `fields=Path,DateCreated` by name: neither is on a default list row (005 spec section 3.2), and
    the path is the only value that ties a row back to the file that was marked.
    """
    rows: List[Dict[str, Any]] = []
    for view in server.get("/UserViews", userId=server.user_id).get("Items", []):
        answer = server.get(
            "/Items",
            userId=server.user_id,
            parentId=str(view["Id"]),
            recursive="true",
            fields="Path,DateCreated",
            limit=10000,
            sortBy="SortName",
            sortOrder="Ascending",
        )
        for item in answer.get("Items", []):
            absolute = str(item.get("Path") or "")
            relative = absolute[len(MOUNT) + 1 :] if absolute.startswith(MOUNT + "/") else ""
            rows.append(
                {
                    "view": str(view.get("Name")),
                    "type": str(item.get("Type", "")),
                    "name": str(item.get("Name", "")),
                    "relative": relative,
                    "created": parse(str(item.get("DateCreated") or "")),
                }
            )
    return rows


def carrying(rows: Sequence[Dict[str, Any]], relative: str) -> Dict[str, Any]:
    found = [row for row in rows if row["relative"] == relative]
    if not found:
        probe = load("_probe")
        raise probe.ProbeError(f"no item on the instance carries the path {relative!r}")
    return found[0]


# ----------------------------------------------------------------------------------------------
# The four findings
# ----------------------------------------------------------------------------------------------


def file_backed(rows: Sequence[Dict[str, Any]], tree: Path) -> Tuple[int, int, List[str]]:
    """Every row that names a file, against that file's own modification time."""
    agreed = 0
    differed: List[str] = []
    for row in rows:
        if not row["relative"] or not (tree / row["relative"]).is_file():
            continue
        on_disk = datetime.fromtimestamp((tree / row["relative"]).stat().st_mtime, timezone.utc)
        if row["created"] is not None and abs((row["created"] - on_disk).total_seconds()) < 2:
            agreed += 1
        else:
            differed.append(
                "{} {!r}: DateCreated {} against a file modified {}".format(
                    row["type"], row["name"], row["created"], on_disk
                )
            )
    return agreed, len(differed), differed


def containers(rows: Sequence[Dict[str, Any]], scanned_after: datetime) -> Tuple[int, List[str]]:
    """Every row that names no file, against the moment the scan ran."""
    counted = 0
    early: List[str] = []
    for row in rows:
        if row["relative"] and "." in Path(row["relative"]).name:
            continue
        if row["created"] is None:
            continue
        counted += 1
        if row["created"] < scanned_after:
            early.append(
                "{} {!r}: DateCreated {} is before the scan began".format(
                    row["type"], row["name"], row["created"]
                )
            )
    return counted, early


def refreshed(server: Any, tree: Path, relative: str, moved: datetime) -> Optional[datetime]:
    """Move one file's modification time, refresh the library, and read the item again."""
    stamp(tree / relative, MOVED_TO)
    server.post("/Library/Refresh")
    for _ in range(40):
        time.sleep(3)
        row = carrying(read(server), relative)
        if row["created"] is not None and abs((row["created"] - moved).total_seconds()) < 2:
            return row["created"]
    return carrying(read(server), relative)["created"]


# ----------------------------------------------------------------------------------------------
# The run
# ----------------------------------------------------------------------------------------------


class Run:
    def __init__(self) -> None:
        self.tree: Optional[Path] = None
        self.libraries: Tuple[Any, ...] = ()
        self.image = ""
        self.version = ""

    def build_tree(self, entry_point: Any) -> Path:
        # Swept before it is built, for the reason the instance sweeps before it starts: the only
        # cleanup that survives a killed run is the one the next run performs.
        if TREE.exists():
            shutil.rmtree(TREE, ignore_errors=True)
        self.tree = entry_point.build(TREE)
        self.libraries = tuple(entry_point.libraries())
        for relative, when, what in MARKS:
            target = TREE / relative
            if not target.exists():
                probe = load("_probe")
                raise probe.ProbeError(f"the fixture has no {relative!r} to mark as {what}")
            stamp(target, when)
            print(f"mark: {relative} -> {when}  ({what})", file=sys.stderr)
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
        entry_point = fixture_entry_point()
        tree = self.build_tree(entry_point)
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
                self.image = instance.image
                server = probe.Server(instance.url)
                server.connect(
                    instance.administrator.username, instance.administrator.password, None
                )
                self.version = server.version
                yield server
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure
        finally:
            self.drop_tree()


#: How far before the reading the scan may have begun. The instance is scanned as it is
#: configured and this program's clock starts afterwards, so a container's date is legitimately a
#: little earlier than the first line of the run - and the marks it is being told apart from are
#: years away, not seconds.
SCAN_ALLOWANCE = timedelta(minutes=30)


def measure(server: Any, args: argparse.Namespace, run: Run) -> Any:
    """The four readings, in the order that leaves the moved file for last.

    Last because it is the only one that changes the tree: reading it first would leave every
    other reading describing a file whose time this program had already moved.
    """
    probe = load("_probe")
    tree = run.tree or TREE
    began = datetime.now(timezone.utc) - SCAN_ALLOWANCE
    rows = read(server)

    agreed, differed, complaints = file_backed(rows, tree)
    counted, early = containers(rows, began)
    two_parter = carrying(rows, MARKS[3][0])
    moved = refreshed(server, tree, MARKS[1][0], moment(MOVED_TO))

    found = probe.Probe(
        script="probe_date_created.py",
        question="Where does the reference get an item's DateCreated from?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )
    found.observe("rows read", len(rows))
    found.observe("file-backed rows carrying their file's modification time", agreed)
    found.observe("file-backed rows that did not", differed)
    found.observe("rows with no file", counted)
    found.observe("of those, dated before the scan began", len(early))
    found.observe("the marked season directory says", MARKS[2][1])
    found.observe("the two-part film carries", two_parter["created"])
    found.observe("its part one was marked", MARKS[3][1])
    found.observe("its part two was marked", MARKS[4][1])
    found.observe("a modification time moved to", MOVED_TO)
    found.observe("read back after a refresh as", moved)
    for one in complaints[:10]:
        found.note(one)
    for one in early[:10]:
        found.note(one)

    part_one = two_parter["created"] == moment(MARKS[3][1])
    followed = moved is not None and abs((moved - moment(MOVED_TO)).total_seconds()) < 2
    held = differed == 0 and not early and part_one and followed
    found.conclude(
        (
            f"a file-backed item's DateCreated is its file's modification time "
            f"({agreed} of {agreed + differed} rows), a container's is the moment of the scan "
            f"and not its directory's ({counted} rows, none "
            "earlier than the scan), a two-part film carries the time of the part its Path names, "
            "and moving a file's modification time moves the item's date on the next scan"
        )
        if held
        else (
            "the split did not hold: {} file-backed rows did not carry their file's time, {} "
            "container rows were dated before the scan, the two-part film carried {} against part "
            "one's {}, and a moved modification time read back as {}"
        ).format(differed, len(early), two_parter["created"], MARKS[3][1], moved),
        matches_documentation=held,
    )
    return found


def main() -> int:
    run = Run()
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args, run),
            description=(
                "Measure where a reference server gets an item's DateCreated from, by marking "
                "five paths of this repository's own fixture before the scan reads them. Stands "
                "up a single-use instance of the pinned version and destroys it - including on "
                "failure. It never measures a server somebody owns."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=run.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
