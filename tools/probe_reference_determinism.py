#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Does the reference answer the same request the same way twice?

Answers 010 §7 OQ-3 - *can the differential run against a recorded session instead of a live one?*
A recording is only worth having if a replay of it would be indistinguishable from the server, and
that is a measurement rather than an opinion: issue each read of the surface three times over, and
compare the bytes.

Two things are being asked at once, and they have different answers.

* **Are the bodies stable?** If a request answers different bytes on two consecutive calls, no
  recording can stand in for the server and no differential can call a difference a difference.
* **Are the headers stable?** A header that changes on every response has to be masked by any
  comparison, recorded or live, and the project's own `X-Response-Time-ms`
  ([behaviours §1.9](../docs/compatibility/behaviours.md)) is the obvious candidate.

The `Random` sort and `/Items/{itemId}/Similar` are in the battery on purpose: both are draws
rather than readings (`tools/probe_similar_ranking.py`), and a probe that omitted them would report
a determinism the surface does not have. `/UserViews` was not expected to be a third, and is: its
`ChildCount` is a fresh random integer between 1 and 9 on every response, because the reference
declines to compute a top-level folder's count and substitutes a number so that clients "won't
think the folders are empty" `[source: Emby.Server.Implementations/Dto/DtoService.cs:516-526 @
v10.11.11]` - reached because that route asks for every field
`[source: Jellyfin.Api/Controllers/UserViewsController.cs:89 @ v10.11.11]`.

Read-only. Writes nothing. Note that it is not *inert*: authenticating creates a session, so
`/Sessions` is measured for what it is - a route whose answer depends on who has been talking to
the server lately.

Usage:
    python3 tools/probe_reference_determinism.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from _probe import Probe, ProbeError, Server, main

#: Repeats per case. Three separates "stable" from "happened to agree once".
RUNS = 3

#: Headers whose value is expected to move on every response, and which any comparison must mask.
#: Measured rather than assumed: the probe reports what actually varied, and this list is only
#: what it checks that finding against.
EXPECTED_VARYING = {"x-response-time-ms", "date"}


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()[:16]


def cases(server: Server) -> List[Tuple[str, str, Dict[str, Any]]]:
    """One request per read shape of the surface that needs no setup, plus the two draws."""
    user = server.user_id
    movies = server.get(
        "/Items",
        Recursive="true",
        IncludeItemTypes="Movie",
        Limit=1,
        SortBy="SortName",
        userId=user,
    ).get("Items", [])
    if not movies:
        raise ProbeError("the library holds no movie, so the item-shaped cases cannot be built")
    movie = str(movies[0]["Id"])
    return [
        ("public system info", "/System/Info/Public", {}),
        ("system info", "/System/Info", {}),
        ("public users", "/Users/Public", {}),
        ("the caller", "/Users/Me", {}),
        ("views", "/UserViews", {"userId": user}),
        (
            "items, sorted",
            "/Items",
            {"Recursive": "true", "Limit": 50, "SortBy": "SortName", "userId": user},
        ),
        ("items, unsorted", "/Items", {"Recursive": "true", "Limit": 50, "userId": user}),
        (
            "items, paged",
            "/Items",
            {"Recursive": "true", "Limit": 50, "StartIndex": 100, "userId": user},
        ),
        ("one item", "/Items/" + movie, {"userId": user}),
        ("latest", "/Items/Latest", {"userId": user, "limit": 20}),
        ("resume", "/UserItems/Resume", {"userId": user, "limit": 20}),
        ("next up", "/Shows/NextUp", {"userId": user, "limit": 20}),
        ("artists", "/Artists", {"userId": user, "Limit": 50}),
        ("genres", "/Genres", {"userId": user, "Limit": 50}),
        ("studios", "/Studios", {"userId": user, "Limit": 50}),
        ("filters", "/Items/Filters", {"userId": user}),
        ("sessions", "/Sessions", {}),
        (
            "items, Random",
            "/Items",
            {"Recursive": "true", "Limit": 20, "SortBy": "Random", "userId": user},
        ),
        ("similar", "/Items/" + movie + "/Similar", {"userId": user, "limit": 20}),
    ]


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_reference_determinism.py",
        question="does the reference answer the same request the same way twice?",
        document="specs/010-conformance-harness/spec.md",
        section="section 7 OQ-3",
        expectation=(
            "every read of the surface answers byte-identical bodies on repeated identical "
            "requests except three draws - a `Random` sort, `Similar`, and `/UserViews`, whose "
            "`ChildCount` is a random integer - and the only header values that move are the "
            "response time and the clock"
        ),
    )

    battery = cases(server)
    unstable: List[str] = []
    varying_headers: Dict[str, int] = {}

    for label, path, parameters in battery:
        bodies = []
        headers: List[Dict[str, str]] = []
        status = 0
        for _ in range(RUNS):
            status, header, payload = server.get_raw(path, **parameters)
            bodies.append(digest(payload))
            headers.append({key.lower(): value for key, value in header.items()})
        stable = len(set(bodies)) == 1
        if not stable:
            unstable.append(label)
        for key in headers[0]:
            if len({one.get(key) for one in headers}) > 1:
                varying_headers[key] = varying_headers.get(key, 0) + 1
        probe.observe(
            label,
            f"{status}  {'identical' if stable else 'DIFFERS ' + ' '.join(bodies)}",
        )

    probe.observe(
        "headers that moved",
        ", ".join(f"{key} ({n} cases)" for key, n in sorted(varying_headers.items())) or "none",
    )

    draws = {"views", "items, Random", "similar"}
    only_the_draws = set(unstable) == draws
    only_expected_headers = set(varying_headers) <= EXPECTED_VARYING

    probe.note(
        "The `/UserViews` instability is one property and not the route: the view rows arrive in "
        "the same order with the same names and ids, and only `ChildCount` moves. It is a value "
        "no server can reproduce and no client can rely on, which makes it an allowlist class "
        "rather than a difference to triage."
    )
    probe.note(
        "A stable body is necessary for a recording to stand in for the server, and it is not "
        "sufficient. A recording answers the requests it recorded; the class of defect a "
        "differential exists to find is the field nobody thought to ask for, and a request nobody "
        "thought to record cannot find it. It also cannot carry a write: the playlist routes "
        "change the state the next read reports, and one of them is a coin flip "
        "([behaviours §3.18](../docs/compatibility/behaviours.md))."
    )

    probe.conclude(
        (
            f"{len(battery) - len(unstable)} of {len(battery)} read cases answered "
            f"byte-identical bodies on {RUNS} identical requests; the unstable ones are "
            f"{', '.join(unstable) or 'none'}, and the only header values that moved are "
            f"{', '.join(sorted(varying_headers)) or 'none'}"
        ),
        matches_documentation=only_the_draws and only_expected_headers,
    )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, "Does the reference answer the same request the same way twice?"))
