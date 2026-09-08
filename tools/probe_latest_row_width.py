#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How wide is a `/Items/Latest` row — a list row, or something else?

005 §3.2 says `ChildCount` and `RecursiveItemCount` are on a **full body** of every container type
and on **no list row of any type**, and `tests/unit/test_user_world_routes.py`'s
`test_latest_rows_are_list_rows` holds this server to the narrow shape — *"nothing gated leaks"*.
That test asserts **this server's** shape and carries no citation: nobody has read a
`/Items/Latest` row on the reference and compared it to a list row of the same item.

**The differential run of 2026-09-07 says the two disagree**, and by one field above all others:
of 116 findings on that route, **35 are `ChildCount` the reference sends and this server does not**
`[probe: tools/differential.py --fixture, Jellyfin 10.11.11, 2026-09-07]`. The rest of that route's
findings are causes already owned - 003's naming and the metadata it does not resolve - and this
one is not.

There is a shape that would explain it and it has a precedent. `/UserViews` carries a `ChildCount`
this project does not send **because that route asks for every field**
`[source: Jellyfin.Api/Controllers/UserViewsController.cs:89 @ v10.11.11]`, which is how
behaviours §3.25's random number reaches a client at all. If `/Items/Latest` asks widely too, its
rows are not list rows there, and 005 §3.2's sentence is about a width this route does not use.

So this reads one item three ways and subtracts:

1. its row as `/Items/Latest` answers it,
2. its row as a plain `/Items` listing answers it,
3. its full body, which 005 §3.2 says carries everything unasked.

A `/Items/Latest` row equal to (2) is a list row and the `ChildCount` finding is something else. A
row between (2) and (3) is a **third width on this route**, which is the shape `/UserViews` already
has and which this project would then be answering narrowly.

**It writes nothing and cannot.** Every request is a `GET`, which is why it may be pointed at a
server somebody owns.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_latest_row_width.py
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

HERE = Path(__file__).resolve().parent

#: What 005 gates to a full body, and what this probe is looking for on a narrower one.
GATED = ("ChildCount", "RecursiveItemCount", "Overview", "SortName", "Genres", "Path")

DOCUMENT = "specs/005-item-query-api/spec.md"
SECTION = "section 3.2"

EXPECTATION = (
    "005 section 3.2: ChildCount and RecursiveItemCount are on a full body and on no list row of "
    "any type, and /Items/Latest answers list rows - so a Latest row should carry exactly what a "
    "plain /Items listing answers for the same item"
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


def keys(body: Optional[Dict[str, Any]]) -> Set[str]:
    return set(body) if body else set()


def named(properties: Set[str]) -> str:
    return ", ".join(sorted(properties)) if properties else "-"


def measure(server: Any, args: argparse.Namespace) -> Any:
    probe = load("_probe")
    found = probe.Probe(
        script="probe_latest_row_width.py",
        question="How wide is a /Items/Latest row - a list row, or something else?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )

    latest = server.get("/Items/Latest", userId=server.user_id, limit=1)
    rows = latest if isinstance(latest, list) else latest.get("Items", [])
    if not rows:
        found.note("this server answers no Latest rows, so the question has no subject")
        found.conclude("unanswered: no /Items/Latest row to read", matches_documentation=None)
        return found

    row = dict(rows[0])
    identifier = str(row.get("Id", ""))
    found.observe("the Latest row", "{} ({})".format(str(row.get("Name"))[:30], row.get("Type")))

    listed = server.get("/Items", userId=server.user_id, ids=identifier).get("Items", [])
    plain = dict(listed[0]) if listed else None
    full = dict(server.get(f"/Items/{identifier}", userId=server.user_id))

    latest_keys, plain_keys, full_keys = keys(row), keys(plain), keys(full)
    found.observe(
        "properties: Latest / list row / full body",
        f"{len(latest_keys)} / {len(plain_keys)} / {len(full_keys)}",
    )
    found.observe("Latest carries and a list row does not", named(latest_keys - plain_keys))
    found.observe("a list row carries and Latest does not", named(plain_keys - latest_keys))
    found.observe(
        "of the gated set, what Latest carries",
        named({name for name in GATED if name in latest_keys}),
    )

    # **And what the extra property says**, which decides whether it can be reproduced truthfully:
    # a film has no children at all, so a `ChildCount` on one is either `0` - a true count this
    # server can answer - or the shape behaviours 3.25 records on `/UserViews`, a number that is
    # not a count. Read across several rows and their types rather than the one above.
    several = server.get("/Items/Latest", userId=server.user_id, limit=6)
    sample = several if isinstance(several, list) else several.get("Items", [])
    found.observe(
        "ChildCount across Latest rows",
        "  ".join(
            "{}={}".format(str(one.get("Type")), one.get("ChildCount", "(absent)"))
            for one in sample
        )
        or "-",
    )

    wider = latest_keys - plain_keys
    held = not wider
    verdict = (
        "a /Items/Latest row is WIDER than a list row by "
        + named(wider)
        + ": this route is a third width on the reference, the way /UserViews is, and 005 3.2's "
        "sentence is about a width it does not use"
    )
    found.conclude(
        (
            "a /Items/Latest row is exactly a list row, so 005 3.2's sentence covers this route "
            "and the ChildCount difference the sweep reported is something else"
        )
        if held
        else verdict,
        matches_documentation=held,
    )
    return found


def main() -> int:
    return int(
        load("_probe").main(
            lambda server, args: measure(server, args),
            description=(
                "How wide a /Items/Latest row is, against a list row and a full body of the same "
                "item. Every request is a GET: this probe writes nothing, which is why it may be "
                "pointed at a server somebody owns."
            ),
            with_args=True,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
