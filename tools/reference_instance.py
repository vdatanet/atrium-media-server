#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stand up the single-use reference instance and leave it running, for a human.

`tools/differential.py` stands one up around its own sweep and destroys it in the same breath,
which is right for a run and useless for the person looking at a difference the run reported. This
is that person's command: one instance of the pinned version over a fixture tree, configured with
no human, left listening on loopback, with the address and the throwaway administrator printed.

**It is still single use.** Nothing here keeps an instance across runs on purpose - a surviving
instance accumulates what each run wrote, so the second run measures a library the first one
changed (ADR-0007). What this command leaves behind is left behind *deliberately and visibly*, and
the next thing that touches the runtime sweeps it: `--sweep` here, or any differential run.

**`--help` starts nothing**, reaches no server and does not even look for a runtime. That is not
politeness: CI runs `--help` on every command-line tool in this directory at both ends of the
supported Python range, and **no CI job may contact or start a Jellyfin**
([ADR-0007](../docs/decisions/0007-a-container-runtime-for-the-reference-instance.md), plan
section 6.11).

Usage:
    python3 tools/reference_instance.py --fixture-root /path/to/tree
    python3 tools/reference_instance.py --fixture-root /path/to/tree --check
    python3 tools/reference_instance.py --sweep
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence

HERE = Path(__file__).resolve().parent


def reference() -> Any:
    """`tools/_reference.py`, loaded by path and **on first use, never at import**.

    `tools/` is a directory of standalone programs and not an importable package, which is the
    same reason `tools/differential.py` reaches its siblings this way. Loading it here rather than
    at module scope is what keeps `--help` from touching anything.
    """
    name = "_reference"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "_reference.py")
    if spec is None or spec.loader is None:  # pragma: no cover - the file is beside this one
        raise SystemExit("tools/_reference.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_library(text: str) -> Any:
    """`name[:collectionType[:subpath]]`, so a caller can ask for the shape D-4 decides.

    An empty collection type is a mixed-content library, which is what the reference makes when
    `AddVirtualFolder` is called without one `[spec: AddVirtualFolder]`.
    """
    parts = [*text.split(":"), "", ""][:3]
    return reference().Library(name=parts[0], collection_type=parts[1], subpath=parts[2])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reference_instance.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Stand up the single-use reference instance of the pinned Jellyfin version over a "
            "fixture tree and leave it running, so a difference can be looked at by hand. The "
            "image is pinned by digest, the tree is mounted read-only, and nothing is written to "
            "any server somebody owns."
        ),
        epilog=(
            "Exit codes: 0 it stood up (or the sweep ran), 1 it could not.\n"
            "No CI job runs this and none may: no job may contact or start a Jellyfin "
            "(ADR-0007, 010 plan section 6.11). --help starts nothing.\n"
            "Whatever this leaves running is swept by the next run, or by --sweep here."
        ),
    )
    parser.add_argument(
        "--fixture-root",
        type=Path,
        help="The tree to mount read-only as the instance's only library",
    )
    parser.add_argument(
        "--library",
        action="append",
        default=[],
        metavar="NAME[:TYPE[:SUBPATH]]",
        help="A library to add over the mounted tree; repeatable. Defaults to one mixed-content "
        "library over the whole tree",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run the whole lifecycle and destroy the instance at the end, printing each step. "
        "The by-hand verification 010 T9 asks for",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Destroy every container and volume an earlier run labelled, say how many, and exit",
    )
    parser.add_argument(
        "--seats",
        action="store_true",
        help="With --check: drive the seat lifecycle of 010 T7 against the instance and print "
        "what every step answered. This is what settles the six claims T7 could make only from "
        "the pinned document, because creating and destroying users is a write and the only "
        "reachable Jellyfin was somebody's production server",
    )
    parser.add_argument("--scan-timeout", type=float, default=900.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    module = reference()

    if args.sweep:
        try:
            removed = module.sweep()
        except module.InstanceError as failure:
            print(f"reference_instance.py: {failure}", file=sys.stderr)
            return 1
        print(f"swept {removed} leftover container(s) and volume(s)")
        return 0

    if args.fixture_root is None:
        print(
            "reference_instance.py: --fixture-root names the tree the instance is given as its "
            "only library, and an instance with nothing mounted would scan an empty library",
            file=sys.stderr,
        )
        return 1

    libraries: List[Any] = [parse_library(text) for text in args.library]
    spec = module.InstanceSpec(
        fixture_root=args.fixture_root,
        libraries=tuple(libraries) or module.DEFAULT_LIBRARIES,
        ready_timeout=args.ready_timeout,
        scan_timeout=args.scan_timeout,
    )
    instance = module.ReferenceInstance(spec)

    try:
        if args.check:
            with instance:
                _describe(instance)
                if args.seats:
                    _measure_seats(instance)
                print("--check: destroying it now, which is the invariant this task is about")
            print(f"destroyed {instance.container} and {len(instance.volumes)} volume(s)")
            return 0
        instance.__enter__()
    except module.InstanceError as failure:
        print(f"reference_instance.py: {failure}", file=sys.stderr)
        return 1

    _describe(instance)
    runtime = instance.runtime().name
    print(
        "left running deliberately. Destroy it with "
        f"`python3 tools/reference_instance.py --sweep`, or `{runtime} rm -f {instance.container}`"
    )
    return 0


def differential() -> Any:
    """`tools/differential.py`, by path and on first use, for `--seats` and nothing else."""
    name = "differential"
    if name in sys.modules:
        return sys.modules[name]
    tools = str(HERE)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec = importlib.util.spec_from_file_location(name, HERE / "differential.py")
    if spec is None or spec.loader is None:  # pragma: no cover - the file is beside this one
        raise SystemExit("tools/differential.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _measure_seats(instance: Any) -> None:
    """The six claims 010 T7 could only read out of the pinned document, asked of a real server.

    T7 wrote the seat lifecycle without a Jellyfin it was allowed to write to, and said so: *"these
    six are **unmeasured**"*. Every one of them is a write - a created account, a narrowed policy,
    a listing that has to show a disabled leftover - so the instance is what makes them askable at
    all, and this is the run that asks. It uses `tools/differential.py`'s own client and its own
    `Roster`, because a measurement of a reimplementation measures the reimplementation.
    """
    cli = differential()
    administrator = instance.administrator
    wire = cli.Wire(instance.url)
    directory = cli.WireDirectory(wire)

    seat = cli.authenticate(wire, administrator.username, administrator.password, "")
    me = directory.get("/Users/Me")
    print("\n-- T7's six claims, measured --")
    print(
        f"wizard user      Name={me.get('Name')!r} Id={me.get('Id')} "
        f"IsAdministrator={me.get('Policy', {}).get('IsAdministrator')} "
        f"handed-in-id-matches={me.get('Id') == seat.user_id}"
    )

    name = "atrium-reference-probe-seat"
    # A throwaway credential on an instance that does not survive this function.
    password = "probe-" + instance.container
    status, _headers, body = directory.post_raw(
        "/Users/New", body={"Name": name, "Password": password}
    )
    made = json.loads(body) if body else {}
    print(f"POST /Users/New  {status}, Id={made.get('Id')!r}, keys={len(made)}")
    user_id = str(made.get("Id", ""))

    library = cli.movies_library_id(directory, seat.user_id)
    before = directory.get("/Users/" + user_id).get("Policy", {})
    narrowed = cli.restricted_policy(before, library)
    status, _headers, body = directory.post_raw("/Users/" + user_id + "/Policy", body=narrowed)
    after = directory.get("/Users/" + user_id).get("Policy", {})
    untouched = after.get("AuthenticationProviderId") == before.get("AuthenticationProviderId")
    print(
        f"POST .../Policy  {status}, EnableAllFolders={after.get('EnableAllFolders')}, "
        f"EnabledFolders={after.get('EnabledFolders')}, "
        f"untouched-property-survived={untouched}"
    )

    denied = cli.playback_denied_policy(before)
    directory.post_raw("/Users/" + user_id + "/Policy", body=denied)
    read_back = directory.get("/Users/" + user_id).get("Policy", {})
    print(
        "playback denial  "
        + ", ".join(
            f"{permission}={read_back.get(permission)}"
            for permission in cli.PLAYBACK_PROCESSING_PERMISSIONS
        )
        + f", {cli.NEGOTIATION_INERT_PERMISSION}={read_back.get(cli.NEGOTIATION_INERT_PERMISSION)}"
    )

    token, signed_in = cli.sign_in_against(instance.url)(name, password)
    print(f"sign in at once  token={bool(token)}, same-id={signed_in == user_id}")

    disabled = dict(read_back)
    disabled["IsDisabled"] = True
    directory.post_raw("/Users/" + user_id + "/Policy", body=disabled)
    listed = {str(user.get("Name")) for user in directory.get("/Users")}
    print(f"bare GET /Users  lists the disabled leftover: {name in listed} (of {len(listed)})")

    directory.delete_raw("/Users/" + user_id)
    roster = cli.Roster(
        directory,
        seat,
        [cli.Role.ADMINISTRATOR, cli.Role.RESTRICTED, cli.Role.PLAYBACK_DENIED],
        library_id=library,
        sign_in=cli.sign_in_against(instance.url),
    )
    with roster:
        print(f"roster           {roster.names} created {len(roster.created)}")
    left = {str(user.get("Name")) for user in directory.get("/Users")}
    print(f"after teardown   {sorted(left)}")


def _describe(instance: Any) -> None:
    administrator = instance.administrator
    print(f"url        {instance.url}")
    print(f"image      {instance.image}")
    print(f"container  {instance.container}")
    print(f"volumes    {', '.join(instance.volumes)}")
    if administrator is not None:
        # A throwaway account on a loopback instance that does not survive the next sweep. It is
        # printed because the whole reason this command exists is somebody signing in to look.
        print(f"username   {administrator.username}")
        print(f"password   {administrator.password}")


if __name__ == "__main__":
    raise SystemExit(main())
