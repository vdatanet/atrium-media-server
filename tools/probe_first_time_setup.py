#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What does a Jellyfin answer while its first-time setup is still unrun, and just after it?

[014](../specs/014-first-time-setup/spec.md) opened on 2026-09-13 with ten questions and no
measurements, three of them decisions and all three taken that day. **The other five are readings,
and there is exactly one Jellyfin they can be taken on**: an operator's server has finished its
setup and cannot be put back, so the state these operations exist for survives only in an instance
that has just started. This probe starts one of the pinned version, **does not configure it**, walks
the window in the order 014 specifies it, and destroys the instance with everything it wrote -
including on failure. Naming a server on the command line is refused rather than honoured.

What it answers, by 014's numbering:

* **OQ-4** - the refusal envelopes: the `404`, the three `400`s, the `401` and the `403`;
* **OQ-5** - the edges: a rename to an unusable name and to one another account holds, a second
  `POST /Startup/Complete`, and whether `movies` collides with an existing `Movies`;
* **OQ-6** - the five library types this server cannot scan, an omitted type, a type the reference
  does not declare, and what `GET /Library/VirtualFolders` states about a library;
* **OQ-7** - whether a setup that never calls `POST /Startup/Configuration` leaves a server an
  account can sign in to and browse;
* **OQ-8** - whether a scan is waited for, and what a library says while one runs.

It also checks the claims 014 already makes from the source - the order, the numbering from `2`, the
window closing - and reports a contradiction if one does not hold.

**Libraries are added with remote metadata providers off**, which is `_reference.library_options`'s
measured default: with them on, a scan of this fixture reads a third party's database rather than
the tree `[probe: tools/probe_reference_scan.py, Jellyfin 10.11.11, 2026-09-02]`, and a scan timing
would time that party too.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_first_time_setup.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import secrets
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

#: The fixture tree, mounted read-only at `_reference.FIXTURE_MOUNT`. Its `Movies` directory is what
#: a scan is timed over, and `Empty` is where a library goes whose type is the only question.
TREE = REPOSITORY / "reference" / "fixture-tree"

#: The account names this probe gives the window. Throwaway, and destroyed with the instance.
ADMINISTRATOR = "atrium-probe-setup"
NON_ADMINISTRATOR = "atrium-probe-viewer"

#: The eight types the reference declares `[spec: CollectionTypeOptions]`, split the way 014 §3.6.1
#: splits them: three this server scans and five it does not.
SCANNED_TYPES = ("movies", "tvshows", "music")
UNSCANNED_TYPES = ("musicvideos", "homevideos", "boxsets", "books", "mixed")

#: How long to wait for a scan to be reported finished before recording that it was not.
SCAN_WAIT_SECONDS = 180.0

DOCUMENT = "specs/014-first-time-setup/spec.md"
SECTION = "section 7, OQ-4 to OQ-8"
EXPECTATION = (
    "014 sections 3.1 to 3.7: POST /Startup/User answers 404 before GET /Startup/User creates the "
    "first account; an empty password and an empty library name and a missing path each answer "
    "400; the first-time-setup operations admit a caller with no token until POST "
    "/Startup/Complete and refuse it 401 afterwards, and refuse an authenticated "
    "non-administrator 403; POST /Library/Refresh refuses a caller with no token even during "
    "setup; a name already in use is numbered from 2; and movies does not collide with Movies"
)


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


def shape(answered: Tuple[int, Dict[str, str], bytes]) -> str:
    """A refusal as it arrived: status, content type and the body's first bytes, verbatim."""
    status, headers, payload = answered
    kind = headers.get("Content-Type") or headers.get("content-type") or "no Content-Type"
    return f"{status} {kind} {payload[:160]!r}"


def status_of(answered: Tuple[int, Dict[str, str], bytes]) -> int:
    return answered[0]


def folders(client: Any) -> List[Dict[str, Any]]:
    rows = client.get("/Library/VirtualFolders")
    return list(rows) if isinstance(rows, list) else []


def names_of(rows: List[Dict[str, Any]]) -> List[str]:
    return sorted(str(row.get("Name")) for row in rows)


def add_library(
    client: Any,
    options: Dict[str, Any],
    name: str,
    collection_type: Optional[str],
    path: str,
    refresh: bool = False,
) -> Tuple[int, Dict[str, str], bytes]:
    """`POST /Library/VirtualFolders` with the query 014 §3.6 describes and providers off."""
    params: Dict[str, Any] = {"name": name, "paths": path, "refreshLibrary": str(refresh).lower()}
    if collection_type is not None:
        params["collectionType"] = collection_type
    return client.post_raw("/Library/VirtualFolders", body={"LibraryOptions": options}, **params)


class Reading:
    """One unconfigured instance, and the window walked on it."""

    def __init__(self) -> None:
        self.instance: Optional[Any] = None

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument. Its question is what a Jellyfin answers "
                "before its first-time setup has run, which no server anybody owns is still in, "
                "and walking that window creates an administrator - so it measures only an "
                "instance it starts and destroys itself"
            )
        if not (TREE / "Movies").is_dir() or not (TREE / "Empty").is_dir():
            raise probe.ProbeError(
                f"{TREE} is not the built fixture tree (it needs Movies/ and Empty/). "
                "tools/differential.py --fixture builds it on its first run"
            )
        try:
            spec = reference.InstanceSpec(fixture_root=TREE, libraries=(), configure=False)
            with reference.ReferenceInstance(spec) as instance:
                self.instance = instance
                server = probe.Server(instance.url)
                # No account exists to sign in as, so the version is read the way `connect` reads
                # it and nothing else of `connect` runs: the citation has to name the server asked.
                info = server.get("/System/Info/Public")
                server.version = str(info.get("Version", "unknown"))
                yield server
        except reference.InstanceError as failure:
            raise probe.ProbeError(str(failure)) from failure

    def report(self, anonymous: Any, _args: argparse.Namespace) -> Any:
        module = load("_probe")
        reference = load("_reference")
        probe = module.Probe(
            script="probe_first_time_setup.py",
            question=(
                "What does a Jellyfin answer while its first-time setup is unrun, and just after?"
            ),
            document=DOCUMENT,
            section=SECTION,
            expectation=EXPECTATION,
        )
        probe.observe("instance", self.instance.image if self.instance else "unknown")
        mount = reference.FIXTURE_MOUNT

        def options(path: str) -> Dict[str, Any]:
            return reference.library_options(reference.Library(name="probe"), path)

        claims: Dict[str, bool] = {}

        # -- the window, before any account -------------------------------------------------
        before = anonymous.get("/System/Info/Public")
        probe.observe(
            "StartupWizardCompleted on a fresh instance", before.get("StartupWizardCompleted")
        )

        password = secrets.token_hex(16)
        early = anonymous.post_raw(
            "/Startup/User", body={"Name": ADMINISTRATOR, "Password": password}
        )
        probe.observe("OQ-4: POST /Startup/User before any account exists", shape(early))
        claims["404 before the account"] = status_of(early) == 404

        first = anonymous.get_raw("/Startup/User")
        probe.observe("GET /Startup/User (creates the account)", shape(first))
        created_name = str((anonymous.get("/Startup/User") or {}).get("Name"))
        probe.observe("the first account's name on this image", created_name)
        claims["GET /Startup/User answers 200"] = status_of(first) == 200

        # -- the account's edges, while nothing else is set --------------------------------
        empty_password = anonymous.post_raw(
            "/Startup/User", body={"Name": ADMINISTRATOR, "Password": ""}
        )
        probe.observe("OQ-4: POST /Startup/User with an empty password", shape(empty_password))
        claims["400 for an empty password"] = status_of(empty_password) == 400

        blank_password = anonymous.post_raw(
            "/Startup/User", body={"Name": ADMINISTRATOR, "Password": "   "}
        )
        probe.observe("OQ-4: POST /Startup/User with a whitespace password", shape(blank_password))

        for label, unusable in (("empty", ""), ("slash and colon", "bad/name:here")):
            renamed = anonymous.post_raw(
                "/Startup/User", body={"Name": unusable, "Password": password}
            )
            probe.observe(f"OQ-5: rename to an unusable name ({label})", shape(renamed))
            probe.observe(
                "  the account's name after it",
                str((anonymous.get("/Startup/User") or {}).get("Name")),
            )

        named = anonymous.post_raw(
            "/Startup/User", body={"Name": ADMINISTRATOR, "Password": password}
        )
        probe.observe("POST /Startup/User, valid", shape(named))

        # -- libraries, during setup, with no token -----------------------------------------
        refresh_early = anonymous.post_raw("/Library/Refresh")
        probe.observe("OQ-4: POST /Library/Refresh during setup, no token", shape(refresh_early))
        claims["Refresh refuses no token during setup"] = status_of(refresh_early) == 401

        movies_path = mount + "/Movies"
        empty_path = mount + "/Empty"
        added = add_library(anonymous, options(movies_path), "Movies", "movies", movies_path)
        probe.observe("AddVirtualFolder during setup, no token", shape(added))
        claims["the window admits no token"] = status_of(added) == 204

        again = add_library(anonymous, options(movies_path), "Movies", "movies", movies_path)
        lower = add_library(anonymous, options(movies_path), "movies", "movies", movies_path)
        trailing = add_library(anonymous, options(empty_path), "Movies?", "movies", empty_path)
        listed = names_of(folders(anonymous))
        probe.observe(
            "the same name twice, then 'movies', then 'Movies?'",
            f"{status_of(again)} {status_of(lower)} {status_of(trailing)}",
        )
        probe.observe("OQ-5: library names after them", listed)
        claims["numbered from 2"] = "Movies2" in listed
        claims["movies does not collide with Movies"] = (
            "movies" in listed and "movies2" not in listed
        )

        no_name = add_library(anonymous, options(empty_path), "", "movies", empty_path)
        probe.observe("OQ-4: AddVirtualFolder with an empty name", shape(no_name))
        claims["400 for an empty name"] = status_of(no_name) == 400
        # **Two 400s, not one.** An empty `name` is refused before the route runs, by validation of
        # a required query parameter; a name of spaces passes that and reaches the library
        # manager's own emptiness check. The bodies differ, so both are read.
        spaces = add_library(anonymous, options(empty_path), "   ", "movies", empty_path)
        probe.observe("OQ-4: AddVirtualFolder with a name of spaces", shape(spaces))

        no_path = add_library(
            anonymous, options(mount + "/nowhere"), "Nowhere", "movies", mount + "/nowhere"
        )
        probe.observe("OQ-4: AddVirtualFolder with a path that does not exist", shape(no_path))
        claims["400 for a missing path"] = status_of(no_path) == 400

        for kind in UNSCANNED_TYPES:
            typed = add_library(anonymous, options(empty_path), "type-" + kind, kind, empty_path)
            probe.observe(f"OQ-6: collectionType={kind}", shape(typed))
        untyped = add_library(anonymous, options(empty_path), "type-omitted", None, empty_path)
        probe.observe("OQ-6: collectionType omitted", shape(untyped))
        undeclared = add_library(
            anonymous, options(empty_path), "type-photos", "photos", empty_path
        )
        probe.observe(
            "OQ-6: collectionType=photos, which the reference does not declare", shape(undeclared)
        )

        rows = folders(anonymous)
        for row in rows:
            if row.get("Name") in ("Movies", "type-omitted", "type-books", "type-photos"):
                probe.observe(
                    f"OQ-6: GET /Library/VirtualFolders row {row.get('Name')!r}",
                    "CollectionType={!r} Locations={!r} ItemId={} PrimaryImageItemId={!r} "
                    "RefreshStatus={!r} RefreshProgress={!r} LibraryOptions keys={}".format(
                        row.get("CollectionType"),
                        row.get("Locations"),
                        "present" if row.get("ItemId") else "absent",
                        row.get("PrimaryImageItemId"),
                        row.get("RefreshStatus"),
                        row.get("RefreshProgress"),
                        len(row.get("LibraryOptions") or {}),
                    ),
                )

        # -- closing the window ---------------------------------------------------------------
        completed = anonymous.post_raw("/Startup/Complete")
        probe.observe("POST /Startup/Complete", shape(completed))
        after = anonymous.get("/System/Info/Public")
        probe.observe("StartupWizardCompleted after it", after.get("StartupWizardCompleted"))
        claims["the window closes"] = after.get("StartupWizardCompleted") is True

        closed = anonymous.get_raw("/Library/VirtualFolders")
        probe.observe("OQ-4: GET /Library/VirtualFolders after setup, no token", shape(closed))
        claims["401 with no token after setup"] = status_of(closed) == 401
        second_complete = anonymous.post_raw("/Startup/Complete")
        probe.observe("OQ-5: a second POST /Startup/Complete, no token", shape(second_complete))

        administrator = module.Server(anonymous.base, timeout=anonymous.timeout)
        administrator.connect(ADMINISTRATOR, password, None)
        administrator.version = anonymous.version
        again_complete = administrator.post_raw("/Startup/Complete")
        probe.observe("OQ-5: a second POST /Startup/Complete, administrator", shape(again_complete))

        viewer_password = secrets.token_hex(16)
        administrator.post(
            "/Users/New", body={"Name": NON_ADMINISTRATOR, "Password": viewer_password}
        )
        viewer = module.Server(anonymous.base, timeout=anonymous.timeout)
        viewer.connect(NON_ADMINISTRATOR, viewer_password, None)
        forbidden = viewer.get_raw("/Library/VirtualFolders")
        probe.observe(
            "OQ-4: GET /Library/VirtualFolders after setup, non-administrator", shape(forbidden)
        )
        claims["403 for a non-administrator"] = status_of(forbidden) == 403
        # A different policy from the one above - `RequiresElevation`, not first-time setup - so its
        # refusal is read on its own route rather than assumed to share the empty `403`.
        refresh_forbidden = viewer.post_raw("/Library/Refresh")
        probe.observe(
            "OQ-4: POST /Library/Refresh after setup, non-administrator", shape(refresh_forbidden)
        )
        claims["Refresh refuses a non-administrator 403"] = status_of(refresh_forbidden) == 403

        taken = administrator.post_raw(
            "/Startup/User", body={"Name": NON_ADMINISTRATOR, "Password": password}
        )
        probe.observe(
            "OQ-5: rename the first account to a name another account holds", shape(taken)
        )

        # -- OQ-7: a setup that never called POST /Startup/Configuration ----------------------
        views = administrator.get_raw("/UserViews", userId=administrator.user_id)
        probe.observe("OQ-7: /UserViews for the first account", shape(views))
        probe.observe("OQ-7: ServerName after a setup that skipped it", after.get("ServerName"))

        # -- OQ-8: is a scan waited for? -------------------------------------------------------
        # Answered by **what a client can browse**, counted immediately before and after each
        # response, and not by `RefreshStatus`: the first run of this probe read that field as
        # 'Idle' at every poll while the films appeared, so it is not evidence either way.
        def count(item_type: str) -> int:
            answered = administrator.get(
                "/Items", userId=administrator.user_id, recursive="true", includeItemTypes=item_type
            )
            return int((answered or {}).get("TotalRecordCount") or 0)

        def scan_state() -> str:
            tasks = administrator.get("/ScheduledTasks")
            for task in tasks if isinstance(tasks, list) else []:
                if isinstance(task, dict) and task.get("Key") == reference.SCAN_TASK_KEY:
                    return str(task.get("State"))
            return "no scan task"

        def row_state(library: str) -> str:
            rows = [row for row in folders(administrator) if row.get("Name") == library]
            if not rows:
                return "no row"
            return f"{rows[0].get('RefreshStatus')!r}/{rows[0].get('RefreshProgress')!r}"

        def settle(item_type: str, library: str) -> str:
            """Poll until the scan task is idle and the count has stopped moving, recording each
            change of the task, the count **and the library row's own refresh fields** - so a
            finished scan ends the wait instead of the deadline, and the row is read *during* the
            scan rather than only around it."""
            seen: List[str] = []
            steady = 0
            deadline = time.monotonic() + SCAN_WAIT_SECONDS
            while time.monotonic() < deadline:
                now = f"{scan_state()} {count(item_type)} row={row_state(library)}"
                if not seen or seen[-1] != now:
                    seen.append(now)
                    steady = 0
                else:
                    steady += 1
                if now.startswith("Idle") and steady >= 3:
                    return " -> ".join(seen)
                time.sleep(1.0)
            return " -> ".join(seen) + " (deadline reached)"

        probe.observe(
            "OQ-8: films browsable before any refresh (added with refreshLibrary=false)",
            count("Movie"),
        )
        started = time.monotonic()
        refreshed = administrator.post_raw("/Library/Refresh")
        answered_after = time.monotonic() - started
        probe.observe(
            "OQ-8: POST /Library/Refresh",
            f"{shape(refreshed)} after {answered_after:.2f}s; "
            f"films then {count('Movie')}, scan task {scan_state()}",
        )
        probe.observe(
            "OQ-8: scan task, films and the row, as they changed", settle("Movie", "Movies")
        )

        rows_now = [row for row in folders(administrator) if row.get("Name") == "Movies"]
        if rows_now:
            probe.observe(
                "OQ-8: Movies' RefreshStatus/RefreshProgress after it",
                f"{rows_now[0].get('RefreshStatus')!r}/{rows_now[0].get('RefreshProgress')!r}",
            )

        # A library that did not exist a moment ago cannot have been scanned already, which makes
        # this the reading that says whether `refreshLibrary=true` waits.
        started = time.monotonic()
        inline = add_library(
            administrator,
            options(mount + "/Shows"),
            "Shows",
            "tvshows",
            mount + "/Shows",
            refresh=True,
        )
        probe.observe(
            "OQ-8: AddVirtualFolder with refreshLibrary=true",
            f"{shape(inline)} after {time.monotonic() - started:.2f}s; "
            f"episodes then {count('Episode')}, scan task {scan_state()}",
        )
        probe.observe(
            "OQ-8: scan task, episodes and the row, as they changed", settle("Episode", "Shows")
        )

        failed = sorted(name for name, held in claims.items() if not held)
        probe.conclude(
            "every claim 014 makes from the source held on the instance - the 404 before the "
            "account, the 400s, the window admitting no token until it closes and then refusing "
            "401 and 403, the refresh refusing no token even during setup, the numbering from 2 "
            "and the case-sensitive collision; the readings above answer OQ-4 to OQ-8"
            if not failed
            else f"{len(failed)} claim(s) 014 makes from the source did not hold: {failed}",
            matches_documentation=not failed,
        )
        probe.note(
            "The instance was never configured: no first-time setup, no library and no account "
            "existed when this probe began, which is the state 014 is about and the one state no "
            "server anybody owns is still in."
        )
        probe.note(
            "OQ-7 is answered at the API only. Whether a client's own interface accepts a server "
            "whose setup skipped POST /Startup/Configuration is a question for a client, and this "
            "probe signs in and lists views rather than rendering them."
        )
        return probe


def main() -> int:
    reading = Reading()
    return int(
        load("_probe").main(
            reading.report,
            description=(
                "Measure what a Jellyfin answers while its first-time setup is unrun and just "
                "after (014 OQ-4 to OQ-8). Starts a single-use instance of the pinned version "
                "without configuring it, walks the window, and destroys the instance - including "
                "on failure. It never measures a server somebody owns."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=reading.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
