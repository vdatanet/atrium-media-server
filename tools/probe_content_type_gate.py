#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""When is a body's media type refused, and with what?

behaviours §5 carried an accepted gap from 2026-09-01 reading *"a required body that is missing
entirely is `400` and not `415`"*, on five named routes. It was measured on one of them, by
`probe_playlist_rename.py`, and 010's differential asked four more on 2026-09-06 and found the same
status. What none of them asked is the question this probe exists for: **what is the condition?** A
missing body and an unreadable one are two different requests, and a route whose body is required
and one whose body is optional are two different routes.

Asked one request at a time, on a route of each kind and across the media types a client might
send. The answer is that the gap's description named the wrong condition and one wrong route:

* the refusal is about the **media type of a body the server has to read**, not about a body being
  absent - a route whose body is optional answers a body-less request normally;
* `POST /Items/{itemId}/PlaybackInfo` is in that second group, so the row's five required-body
  routes were four;
* what counts as readable is a **suffix rule** - `application/json`, `text/json` and anything
  ending `+json`, in any case and with parameters - rather than a list;
* and the refusal is the ordinary problem-details body with no `errors` map, which makes it the
  fifth error shape of behaviours §1.11 rather than a variant of the fourth.

**It writes**, because two of the routes it asks are 007's play-state reporting routes and a valid
body there records play state. So it measures only an instance it creates and destroys, never a
server somebody owns.

Standard library only, on the 3.9 floor, and `--help` starts nothing.

Usage:
    python3 tools/probe_content_type_gate.py --allow-writes
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
TREE = REPOSITORY / "reference" / "content-type-tree"

#: One request per cell of the table this probe prints.
CASES: Tuple[Tuple[str, Optional[bytes], Optional[str]], ...] = (
    ("no body, no CT", None, None),
    ("body, no CT", b'{"ItemId":"%s"}', None),
    ("body, text/plain", b'{"ItemId":"%s"}', "text/plain"),
    ("valid body", b'{"ItemId":"%s"}', "application/json"),
)

#: The media types asked of one required-body route, to find the rule rather than a list.
MEDIA_TYPES: Tuple[str, ...] = (
    "application/json",
    "application/json; charset=utf-8",
    "APPLICATION/JSON",
    "text/json",
    "application/problem+json",
    "application/vnd.api+json",
    "application/x-www-form-urlencoded",
    "*/*",
    "",
)

EXPECTATION = (
    "behaviours section 1.11's fifth shape and section 5's row: the refusal is about the media "
    "type of a body the server must read - always for a required body, and only when a body "
    "arrives for an optional one - and it is problem details with no errors map"
)

DOCUMENT = "docs/compatibility/behaviours.md"
SECTION = "section 1.11"


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
    from tests.fixtures import reference_tree

    return reference_tree


def post(
    server: Any, path: str, body: Optional[bytes], content_type: Optional[str]
) -> Tuple[int, bytes]:
    request = urllib.request.Request(  # noqa: S310 - http(s) only, the instance this run made
        server.base + path, data=body, method="POST"
    )
    request.add_header("Authorization", f'MediaBrowser Token="{server.token}"')
    if content_type is not None:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:  # noqa: S310
            return answer.status, answer.read()
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read()


class Run:
    def drop_tree(self) -> None:
        if TREE.is_dir():
            shutil.rmtree(TREE, ignore_errors=True)

    @contextlib.contextmanager
    def connect(self, args: argparse.Namespace) -> Iterator[Any]:
        probe = load("_probe")
        reference = load("_reference")
        if getattr(args, "server", None):
            raise probe.ProbeError(
                "this probe refuses a server argument: it posts a valid body to 007's reporting "
                "routes, which records play state"
            )
        entry_point = fixture_entry_point()
        if TREE.exists():
            shutil.rmtree(TREE, ignore_errors=True)
        tree = entry_point.build(TREE)
        libraries = tuple(
            reference.Library(
                name=one.name,
                collection_type=one.collection_type,
                subpath=one.subpath,
                internet_providers=False,
            )
            for one in entry_point.libraries()
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
    film = server.get(
        "/Items", userId=server.user_id, recursive="true", includeItemTypes="Movie", limit=1
    ).get("Items", [])[0]
    identifier = str(film["Id"]).encode("ascii")

    found = probe.Probe(
        script="probe_content_type_gate.py",
        question="When is a body's media type refused, and with what?",
        document=DOCUMENT,
        section=SECTION,
        expectation=EXPECTATION,
    )

    routes = (
        ("POST /Sessions/Playing", "/Sessions/Playing", True),
        ("POST /Items/{itemId}/PlaybackInfo", "/Items/{}/PlaybackInfo".format(film["Id"]), False),
    )
    answers: Dict[str, List[int]] = {}
    for label, path, _required in routes:
        row = []
        for _case, body, content_type in CASES:
            payload = None if body is None else body % identifier
            status, _ = post(server, path, payload, content_type)
            row.append(status)
        answers[label] = row
        found.observe(
            label,
            # Indexed rather than zipped: `zip(..., strict=)` is 3.10 and this file runs on
            # the 3.9 floor, which `tests/unit/test_probe_convention.py` holds it to.
            "  ".join(f"{CASES[i][0]}={status}" for i, status in enumerate(row)),
        )

    accepted = []
    refused = []
    for media_type in MEDIA_TYPES:
        status, _ = post(server, "/Sessions/Playing", b'{"ItemId":"%s"}' % identifier, media_type)
        (accepted if status != 415 else refused).append(media_type or "(empty)")
    found.observe("readable", ", ".join(accepted))
    found.observe("refused", ", ".join(refused))

    _, body = post(server, "/Sessions/Playing", None, None)
    try:
        shape = list(json.loads(body.decode("utf-8")))
    except ValueError:
        shape = ["<not json>"]
    found.observe("the refusal's keys", ", ".join(shape))

    required_row = answers["POST /Sessions/Playing"]
    optional_row = answers["POST /Items/{itemId}/PlaybackInfo"]
    held = (
        required_row[:3] == [415, 415, 415]
        and optional_row[0] != 415
        and optional_row[1] == 415
        and shape == ["type", "title", "status", "traceId"]
    )
    found.conclude(
        (
            "the refusal is about the media type of a body the server must read: a required body "
            "refuses every unreadable request including one carrying nothing, an optional body "
            "answers a body-less request normally and refuses an unreadable one, what is readable "
            "is application/json, text/json and any +json suffix, and the body is problem details "
            "with no errors map"
        )
        if held
        else (
            "the condition is not what the documents say: "
            f"required={required_row} optional={optional_row} keys={shape}"
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
                "Measure when a body's media type is refused and with what, on a single-use "
                "instance this probe creates and destroys. It posts a valid body to a play-state "
                "route, so it never measures a server somebody owns."
            ),
            needs_writes=True,
            with_args=True,
            connect_with=run.connect,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
