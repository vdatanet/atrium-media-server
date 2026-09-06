#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The playlists folder: where it appears, where it does not, and what hangs off it.

009 §3.2 measured that the reference builds a playlist as a directory under a **playlists folder**,
read that the folder is absent from `/UserViews`, and concluded *"so this feature adds no view to a
005 response"*. The premise was measured and the conclusion was not: the route nobody had asked
either server for was a **bare `GET /Items`**, and the folder is in it. This probe asks both routes
in one run, on a server holding no playlists and then on the same server holding one, so the four
claims 009's sentence rests on are each a reading rather than an inference:

1. the folder is **not** in `/UserViews`;
2. it **is** in a bare `GET /Items`, on a stock server with no playlists at all;
3. a playlist created afterwards has that folder as its `ParentId`, and is listed under it;
4. its `ChildCount` is the reference's random number (behaviours §3.25) and not a count of
   anything - which is why the row's own arithmetic cannot be read as evidence either way.

**It writes**, and it writes the one thing it can clean up: a playlist, removed by the shared
teardown whatever happens. It never touches a server somebody owns - the question needs a library
scanned into the server being asked, so it stands up a single-use instance and destroys it.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_playlists_folder.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

TREE = REPOSITORY / "reference" / "playlists-folder-tree"

#: The type the reference gives it. Not `CollectionFolder`, which is what a library view is.
FOLDER_TYPE = "ManualPlaylistsFolder"

EXPECTATION = (
    "009 section 3.2 and behaviours section 5: the reference keeps a ManualPlaylistsFolder named "
    "Playlists that is absent from /UserViews and present in a bare GET /Items even with no "
    "playlists on the server, and it is the ParentId of every playlist; Atrium models no such "
    "container, which is an accepted gap"
)

DOCUMENT = "docs/compatibility/behaviours.md"
SECTION = "section 5"


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


def rows_of(answer: Any) -> List[Dict[str, Any]]:
    return list(answer.get("Items", []))


def named_folder(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for row in rows:
        if str(row.get("Type")) == FOLDER_TYPE:
            return row
    return None


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
                "this probe refuses a server argument: it scans a library and creates a playlist, "
                "and neither belongs on a server somebody owns"
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

    root = rows_of(server.get("/Items", userId=server.user_id))
    views = rows_of(server.get("/UserViews", userId=server.user_id))
    folder = named_folder(root)

    found = probe.Probe(
        script="probe_playlists_folder.py",
        question="Where does the reference's playlists folder appear, and what hangs off it?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )
    found.observe("root rows", ", ".join(f"{r.get('Type')}:{r.get('Name')}" for r in root))
    found.observe("/UserViews rows", ", ".join(f"{r.get('Type')}:{r.get('Name')}" for r in views))
    if folder is None:
        found.conclude(
            "no ManualPlaylistsFolder in a bare GET /Items: the behaviour this document records "
            "is not the one this server has",
            matches_documentation=False,
        )
        return found

    body = server.get(f"/Items/{folder['Id']}", userId=server.user_id)
    empty = rows_of(server.get("/Items", userId=server.user_id, parentId=str(folder["Id"])))
    found.observe(
        "folder Type / CollectionType", f"{folder.get('Type')} / {folder.get('CollectionType')}"
    )
    found.observe("folder Path", body.get("Path"))
    found.observe("under it, with no playlists", len(empty))
    found.observe("its ChildCount with no children", body.get("ChildCount"))

    made = server.post(
        "/Playlists", body={"Name": "atrium probe - playlists folder", "UserId": server.user_id}
    )
    listed = rows_of(server.get("/Items", userId=server.user_id, parentId=str(folder["Id"])))
    playlist = server.get(f"/Items/{made['Id']}", userId=server.user_id)
    after = server.get(f"/Items/{folder['Id']}", userId=server.user_id)
    found.observe("under it, with one playlist", len(listed))
    found.observe(
        "that playlist's ParentId is the folder", playlist.get("ParentId") == folder["Id"]
    )
    found.observe("its ChildCount with one child", after.get("ChildCount"))

    in_views = named_folder(views) is not None
    held = (
        not in_views and not empty and len(listed) == 1 and playlist.get("ParentId") == folder["Id"]
    )
    if in_views:
        found.note("the folder IS in /UserViews, which 009 section 3.2 measured it out of")
    found.conclude(
        (
            f"the reference keeps a {FOLDER_TYPE} named {folder.get('Name')!r} out of /UserViews "
            f"and in a bare GET /Items, on a server holding no playlists; a playlist created "
            f"afterwards is listed under it and names it as its ParentId. Its ChildCount answered "
            f"{body.get('ChildCount')} with no children and {after.get('ChildCount')} with one, "
            "which is behaviours section 3.25's random number and not a count"
        )
        if held
        else (
            f"the folder's shape is not what the documents say: in /UserViews={in_views}, "
            f"{len(empty)} rows under it before a playlist and {len(listed)} after"
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
                "Measure where the reference's playlists folder appears and what hangs off it, on "
                "a single-use instance this probe creates and destroys. It creates one playlist "
                "and the shared teardown removes it."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=run.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
