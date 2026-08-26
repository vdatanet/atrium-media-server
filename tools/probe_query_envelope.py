#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What shape does each list endpoint return?

Answers 005 OQ-6, and discharges the prior-probe debt on `StartIndex` registered in
docs/compatibility/reference-target.md.

The question matters because the shapes are not uniform and the difference is invisible until a
client decodes the wrong one. specs/005 section 3.1 claims that every list endpoint returns
{Items, TotalRecordCount, StartIndex} *except* /Items/Latest, which returns a bare array, and
/Items/Filters, which returns a filter summary. A client decoding a bare array as an envelope gets
nothing at all, so this asymmetry is load-bearing rather than cosmetic.

Read-only. Makes one request per endpoint and writes nothing.

Usage:
    python3 tools/probe_query_envelope.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

from _probe import Probe, ProbeError, Server, main

ENVELOPE = {"Items", "TotalRecordCount", "StartIndex"}
FILTERS = {"Genres", "Tags", "OfficialRatings", "Years"}

# (path, extra query, what specs/005 section 3.1 says the shape is)
ENDPOINTS = [
    ("/Items", {"Limit": 1, "Recursive": "true"}, "envelope"),
    ("/Items/Latest", {"Limit": 1}, "array"),
    ("/Items/Filters", {}, "filters"),
    ("/UserViews", {}, "envelope"),
    ("/UserItems/Resume", {"Limit": 1}, "envelope"),
    ("/Artists", {"Limit": 1}, "envelope"),
    ("/Artists/AlbumArtists", {"Limit": 1}, "envelope"),
    ("/Genres", {"Limit": 1}, "envelope"),
    ("/MusicGenres", {"Limit": 1}, "envelope"),
    ("/Years", {"Limit": 1}, "envelope"),
    ("/Shows/NextUp", {"Limit": 1}, "envelope"),
    ("/Search/Hints", {"SearchTerm": "a", "Limit": 1}, "hints"),
]


def classify(payload: object) -> tuple[str, str]:
    """Return (shape, detail) for one response body."""
    if isinstance(payload, list):
        return "array", f"{len(payload)} element(s)"
    if not isinstance(payload, dict):
        return "scalar", type(payload).__name__

    keys = set(payload)
    if keys >= ENVELOPE:
        return "envelope", "Items, TotalRecordCount, StartIndex"
    if {"Items", "TotalRecordCount"} <= keys:
        return "envelope-", "no StartIndex: " + ", ".join(sorted(keys))
    if "SearchHints" in keys:
        return "hints", ", ".join(sorted(keys))
    if keys and keys <= FILTERS:
        return "filters", ", ".join(sorted(keys))
    return "object", ", ".join(sorted(keys)) or "empty"


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_query_envelope.py",
        question="what shape does each list endpoint return?",
        document="specs/005-item-query-api/spec.md",
        section="section 3.1",
        expectation=(
            "every list endpoint returns {Items, TotalRecordCount, StartIndex}, except "
            "/Items/Latest which returns a bare array and /Items/Filters which returns a filter "
            "summary"
        ),
    )

    disagreements: list[str] = []
    unreachable = 0

    for path, extra, expected in ENDPOINTS:
        params = dict(extra)
        params.setdefault("UserId", server.user_id)
        try:
            shape, detail = classify(server.get(path, **params))
        except ProbeError as exc:
            probe.observe(f"GET {path}", f"unreachable - {exc}")
            unreachable += 1
            continue

        agrees = shape == expected
        marker = "" if agrees else "   <-- expected " + expected
        probe.observe(f"GET {path}", f"{shape:<9} {detail}{marker}")
        if not agrees:
            disagreements.append(f"{path} is {shape}, documented as {expected}")

    if unreachable == len(ENDPOINTS):
        raise ProbeError("no endpoint answered; the token may lack permission")

    if unreachable:
        probe.note(
            f"{unreachable} endpoint(s) could not be reached and are not part of the finding. "
            "An empty library answers most of these with an empty envelope, which is still a "
            "shape; an unreachable one is not."
        )

    if disagreements:
        probe.conclude("; ".join(disagreements), matches_documentation=False)
    else:
        probe.conclude(
            "every endpoint returns the shape specs/005 section 3.1 documents, and StartIndex is "
            "present on every envelope",
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
