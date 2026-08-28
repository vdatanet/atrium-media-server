#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""What shape does each list endpoint return, and how does one refuse?

Answers 005 OQ-6, and discharges the prior-probe debt on `StartIndex` registered in
docs/compatibility/reference-target.md.

The question matters because the shapes are not uniform and the difference is invisible until a
client decodes the wrong one. specs/005 section 3.1 claims that every list endpoint returns
{Items, TotalRecordCount, StartIndex} *except* /Items/Latest, which returns a bare array, and
/Items/Filters, which returns a filter summary. A client decoding a bare array as an envelope gets
nothing at all, so this asymmetry is load-bearing rather than cosmetic.

Since 2026-08-28 it also measures how these endpoints refuse and how their bodies are written -
the query-family claims hand-measured on 2026-08-26/27 and folded here (the L2 pattern of
docs/audits/2026-08-28.md):

* **An unrecognised token drops its filter; a type mismatch is a `400`** (behaviours section
  1.12). `/Genres?SortBy=NotASortOption` answers `200`, and so does `/Items` with an unknown
  token in `includeItemTypes`, `sortBy`, `fields` or `filters` - the dropped filter visible in
  the unfiltered total coming back - while `limit=abc` is the `400`. The line is
  token-versus-type, not parameter-versus-parameter.
* **The problem-details refusals** (behaviours section 1.11): the `400` carries
  `application/json; charset=utf-8` - not `application/problem+json` - with keys `type`,
  `title`, `status`, `errors`, `traceId` in that order; the `errors` key is the parameter's
  *declared* spelling (`Limit=abc` comes back keyed `limit`); the `type` URIs point at
  tools.ietf.org's RFC 9110 sections; and the keys stay camelCase under the PascalCase content
  profile. An unknown item that is *shaped* like an id is the problem-details `404`; an id that
  cannot parse is the `400` - which of the two a caller gets depends only on the shape of the
  value (005 spec section 3.5).
* **Query parameter names match case-insensitively** (behaviours section 1.15): `limit=1` binds,
  and a lowercased `sortby`/`sortorder` reorders exactly as the PascalCase spelling does.
* **Every non-ASCII character and seven ASCII ones are escaped `\\uXXXX` with uppercase hex**
  (behaviours section 1.16), measured by echoing them through a validation error - the one route
  that puts arbitrary client text in a response body.

Read-only. Writes nothing.

Usage:
    python3 tools/probe_query_envelope.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import json
from typing import Any

from _probe import Probe, ProbeError, Server, main

#: The reference's RFC 9457 `type` URIs - tools.ietf.org, not iana.org, pointing at RFC 9110's
#: status-code sections (src/atrium/compat/errors.py reproduces them).
TYPE_400 = "https://tools.ietf.org/html/rfc9110#section-15.5.1"
TYPE_404 = "https://tools.ietf.org/html/rfc9110#section-15.5.5"

#: The measured key order of a problem-details body, `errors` present only on the 400.
KEYS_400 = ["type", "title", "status", "errors", "traceId"]
KEYS_404 = ["type", "title", "status", "traceId"]

VALIDATION_TITLE = "One or more validation errors occurred."

#: 32 hex characters that are shaped like an id and name no item - the 404 half of the
#: shape-of-the-value line. Not the all-zeros GUID, which is the reference's empty GUID and
#: answers a different shape entirely (006 spec section 3.5's exception).
BOGUS_ID = "0123456789abcdef0123456789abcdef"

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


def parse(payload: bytes) -> dict[str, Any]:
    """A refusal body as a dict, or an empty one when it is not JSON at all."""
    try:
        body = json.loads(payload)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def first_id(page: Any) -> str:
    items = (page or {}).get("Items") or [{}]
    return str(items[0].get("Id", ""))


def measure_unknown_tokens(probe: Probe, server: Server, disagreements: list[str]) -> int:
    """behaviours section 1.12's first half: an unrecognised enum token drops its filter."""
    baseline = server.get("/Items", UserId=server.user_id, Recursive="true", Limit=1)
    total = int(baseline.get("TotalRecordCount", 0))
    probe.observe("unfiltered /Items total", str(total))

    for path, extra in [
        ("/Genres", {"SortBy": "NotASortOption"}),
        ("/Items", {"IncludeItemTypes": "NotAnItemType"}),
        ("/Items", {"SortBy": "NotASortOption"}),
        ("/Items", {"Fields": "NotAField"}),
        ("/Items", {"Filters": "NotAFilter"}),
    ]:
        parameter = next(iter(extra))
        params: dict[str, Any] = {"UserId": server.user_id, "Recursive": "true", "Limit": 1}
        params.update(extra)
        status, _, payload = server._request("GET", path, params=params, raw=True)
        count = parse(payload).get("TotalRecordCount") if status == 200 else None
        probe.observe(f"GET {path}?{parameter}={extra[parameter]}", f"{status}, total {count}")
        if status != 200:
            disagreements.append(
                f"an unrecognised {parameter} token on {path} answered {status}, not the "
                "dropped-filter 200 of behaviours section 1.12"
            )
        elif parameter == "IncludeItemTypes" and count != total:
            disagreements.append(
                f"an unrecognised includeItemTypes token filtered the result ({count} of "
                f"{total}) instead of being dropped"
            )
    return total


def measure_problem_details(probe: Probe, server: Server, disagreements: list[str]) -> None:
    """behaviours section 1.12's second half and 1.11's problem-details rows."""
    status, headers, payload = server.get_raw("/Items", UserId=server.user_id, Limit="abc")
    body = parse(payload)
    probe.observe(
        "/Items?Limit=abc",
        f"{status}, {headers.get('Content-Type')}, keys {list(body)}, "
        f"errors keyed {sorted(body.get('errors') or {})}",
    )
    if status != 400:
        disagreements.append(f"Limit=abc answered {status}, not the type-mismatch 400")
    if headers.get("Content-Type") != "application/json; charset=utf-8":
        disagreements.append(
            f"the 400 carries {headers.get('Content-Type')!r}, not application/json; "
            "charset=utf-8 (behaviours section 1.11)"
        )
    if list(body) != KEYS_400:
        disagreements.append(f"the 400 body's keys are {list(body)}, not {KEYS_400}")
    if body.get("type") != TYPE_400 or body.get("title") != VALIDATION_TITLE:
        disagreements.append(
            f"the 400's type or title is not the reference's: {body.get('type')!r}, "
            f"{body.get('title')!r}"
        )
    if sorted(body.get("errors") or {}) != ["limit"]:
        disagreements.append(
            f"Limit=abc came back keyed {sorted(body.get('errors') or {})}, not the declared "
            "spelling limit"
        )
    wording = (body.get("errors") or {}).get("limit")
    if wording != ["The value 'abc' is not valid."]:
        disagreements.append(
            f"the type-mismatch wording is {wording!r}, not the measured \"The value 'abc' is "
            'not valid." (src/atrium/compat/errors.py)'
        )

    status, _, payload = server._request(
        "GET",
        "/Items",
        params={"UserId": server.user_id, "Limit": "abc"},
        extra_headers={"Accept": 'application/json; profile="PascalCase"'},
        raw=True,
    )
    profile_keys = list(parse(payload))
    probe.observe("the same 400 under profile=PascalCase", f"{status}, keys {profile_keys}")
    if profile_keys != KEYS_400:
        disagreements.append(
            "the problem-details keys change under the PascalCase profile - "
            "src/atrium/compat/errors.py records them fixed camelCase"
        )

    status, _, payload = server.get_raw(f"/Items/{BOGUS_ID}", userId=server.user_id)
    body = parse(payload)
    probe.observe("/Items/{unknown, id-shaped}", f"{status}, keys {list(body)}")
    if status != 404 or list(body) != KEYS_404 or body.get("type") != TYPE_404:
        disagreements.append(
            f"an unknown id-shaped item answered {status} with keys {list(body)}, not the "
            "problem-details 404"
        )

    status, _, _ = server.get_raw("/Items/not-an-id", userId=server.user_id)
    probe.observe("/Items/not-an-id", str(status))
    if status != 400:
        disagreements.append(
            f"an id that cannot parse answered {status}, not the 400 half of the "
            "shape-of-the-value line (005 spec section 3.5)"
        )


def measure_case_insensitive_names(
    probe: Probe, server: Server, disagreements: list[str], total: int
) -> None:
    """behaviours section 1.15: parameter names bind whatever their case."""
    lower = server.get("/Items", userid=server.user_id, recursive="true", limit=1)
    upper = server.get("/Items", USERID=server.user_id, RECURSIVE="true", LIMIT=1)
    bound = (len(lower.get("Items") or []), len(upper.get("Items") or []))
    probe.observe("lowercase and uppercase parameter names", f"limit bound {bound[0]}, {bound[1]}")
    if total > 1 and bound != (1, 1):
        disagreements.append(
            "a lowercased or uppercased parameter name did not bind (behaviours section 1.15)"
        )

    pascal = server.get(
        "/Items",
        UserId=server.user_id,
        Recursive="true",
        Limit=1,
        SortBy="SortName",
        SortOrder="Descending",
    )
    folded = server.get(
        "/Items",
        UserId=server.user_id,
        Recursive="true",
        Limit=1,
        sortby="SortName",
        sortorder="Descending",
    )
    same = first_id(pascal) == first_id(folded)
    probe.observe(
        "sortby/sortorder lowercased", "same first row" if same else "DIFFERENT first row"
    )
    if not same:
        disagreements.append(
            "a lowercased sortby/sortorder did not reorder as the PascalCase spelling "
            "(behaviours section 1.15)"
        )


def measure_escaping(probe: Probe, server: Server, disagreements: list[str]) -> None:
    """behaviours section 1.16, echoed through the one route that echoes client text."""
    status, _, payload = server.get_raw("/Items", UserId=server.user_id, Limit="ñ\"&'+")
    expected = ["\\u00F1", "\\u0022", "\\u0026", "\\u0027", "\\u002B"]
    present = [escape for escape in expected if escape.encode("ascii") in payload]
    lowercase_hex = b"\\u00f1" in payload
    probe.observe(
        "escapes echoed through the 400",
        f"{len(present)} of {len(expected)} uppercase escapes present"
        + ("; LOWERCASE hex seen" if lowercase_hex else ""),
    )
    if status != 400 or present != expected or lowercase_hex:
        disagreements.append(
            "behaviours section 1.16's escaping did not reproduce: expected uppercase \\uXXXX "
            "for n-tilde, the quote, ampersand, apostrophe and plus in the echoed value"
        )


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_query_envelope.py",
        question="what shape does each list endpoint return, and how does one refuse?",
        document="specs/005-item-query-api/spec.md",
        section="section 3.1 (and behaviours sections 1.11, 1.12, 1.15, 1.16)",
        expectation=(
            "every list endpoint returns {Items, TotalRecordCount, StartIndex}, except "
            "/Items/Latest which returns a bare array and /Items/Filters which returns a filter "
            "summary; an unrecognised enum token drops its filter while a type mismatch is a "
            "400 in problem details carrying application/json; charset=utf-8 with camelCase "
            "keys whatever the profile, keyed by the declared parameter spelling; an unknown "
            "id-shaped item is the problem-details 404 and an unparseable id the 400; parameter "
            "names bind case-insensitively; and every non-ASCII character and seven ASCII ones "
            "are escaped uppercase-hex \\uXXXX"
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

    total = measure_unknown_tokens(probe, server, disagreements)
    measure_problem_details(probe, server, disagreements)
    measure_case_insensitive_names(probe, server, disagreements, total)
    measure_escaping(probe, server, disagreements)

    if disagreements:
        probe.conclude("; ".join(disagreements), matches_documentation=False)
    else:
        probe.conclude(
            "every endpoint returns the shape specs/005 section 3.1 documents, StartIndex is "
            "present on every envelope, and the refusal shapes, the token-versus-type line, the "
            "case-insensitive parameter names and the uppercase escaping all held as documented",
            matches_documentation=True,
        )
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
