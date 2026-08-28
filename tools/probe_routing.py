#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How does the server match a request path to a route, and how does it refuse when it cannot?

Every specification in this repository writes paths in one canonical spelling - `/System/Info/
Public` - and it is easy to read that as the only spelling that works. It is not: the reference
routes **case-insensitively** and tolerates **one** trailing slash, so four requests a client might
plausibly send reach the same handler and a fifth does not.

The refusals matter as much as the matches, because they are what a client sees when it gets a path
or a method wrong, and because a framework's defaults here are never the reference's:

* an unknown path,
* a known path with a method it does not have - including `HEAD` and `OPTIONS`, which are not
  automatically anything.

It also measures the three header one-offs that ride every response and were hand-measured on
2026-08-26 (folded into this probe on 2026-08-28 - the L2 pattern of docs/audits/2026-08-28.md):

* `X-Response-Time-ms`, stamped on **every** response by middleware that is registered
  unconditionally - the refusals included (behaviours section 1.9),
* `Content-Type: application/json; charset=utf-8` on a JSON `200`, ASP.NET Core's formatter
  charset that Starlette's `JSONResponse` would not send (behaviours section 1.10),
* `Server: Kestrel` - the one header where Atrium deliberately diverges, so the reference's half
  of that divergence is pinned here (behaviours section 4.1).

Read-only. Every request is to an endpoint that answers without authentication.

Usage:
    python3 tools/probe_routing.py http://your-jellyfin:8096 -u username
"""

from __future__ import annotations

import urllib.error
import urllib.request

from _probe import Probe, ProbeError, Server, main

#: Answers unauthenticated, has no path parameters, and is the first request every client makes.
PATH = "/System/Info/Public"

#: Two methods on one path, which is what makes it the interesting case for `Allow`.
PING = "/System/Ping"

SPELLINGS = [
    (PATH, "the canonical spelling"),
    (PATH.lower(), "all lowercase"),
    (PATH.upper(), "all uppercase"),
    ("/System/info/Public", "mixed case"),
    (PATH + "/", "one trailing slash"),
    (PATH + "//", "two trailing slashes"),
]

REFUSALS = [
    ("GET", "/System/ThisRouteDoesNotExist", "an unknown path"),
    ("PUT", PING, "a method the path does not have"),
    ("DELETE", PING, "another method it does not have"),
    ("HEAD", PATH, "HEAD on a GET route"),
    ("OPTIONS", PATH, "OPTIONS on a GET route"),
]


def request(server: Server, method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    # S310: the URL is the operator's own server, given on the command line or in .env.
    req = urllib.request.Request(  # noqa: S310
        server.base + path, headers={"Accept": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=server.timeout) as response:  # noqa: S310
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except urllib.error.URLError as exc:
        raise ProbeError(f"{method} {path} -> {exc.reason}") from exc


def describe(headers: dict[str, str], body: bytes) -> str:
    """The three things that distinguish one refusal shape from another."""
    parts = [f"{len(body)} byte body"]
    content_type = headers.get("Content-Type")
    parts.append(f"Content-Type: {content_type}" if content_type else "no Content-Type")
    if "Allow" in headers:
        parts.append(f"Allow: {headers['Allow']}")
    return ", ".join(parts)


def run(server: Server) -> Probe:
    probe = Probe(
        script="probe_routing.py",
        question="how does the server match a path to a route, and how does it refuse?",
        document="specs/001-server-identity-and-discovery/spec.md",
        section="section 3.6",
        expectation=(
            "paths match case-insensitively and tolerate one trailing slash but not two; an "
            "unknown path and a wrong method are both refused with an empty body and no "
            "Content-Type, and the wrong method carries an Allow header listing every method the "
            "path does have; every response - the refusals included - carries a parseable "
            "X-Response-Time-ms; the JSON 200's Content-Type is application/json; charset=utf-8; "
            "and the Server header is Kestrel"
        ),
    )

    canonical, matched = None, []
    for path, label in SPELLINGS:
        status, _, body = request(server, "GET", path)
        if path == PATH:
            canonical = body
        same = " (same bytes)" if canonical is not None and body == canonical else ""
        probe.observe(f"GET {path}", f"{status}{same}   <- {label}")
        if status == 200:
            matched.append(label)

    for method, path, label in REFUSALS:
        status, headers, body = request(server, method, path)
        probe.observe(f"{method} {path}", f"{status}   {describe(headers, body)}   <- {label}")

    # The Allow *ordering* question. /System/Ping's methods are GET and POST, alphabetical in
    # either convention, so the observation above cannot separate "alphabetical" from
    # "registration order". The mark pair /UserFavoriteItems/{itemId} serves POST and DELETE,
    # where the two conventions disagree - src/atrium/compat/errors.py sorts, and behaviours
    # §1.11 records what the reference actually sends. Needs a token and one item.
    if server.token:
        try:
            rows = server.get("/Items", UserId=server.user_id, Recursive="true", Limit=1).get(
                "Items", []
            )
            if rows:
                _, mark_headers, _ = server._request(
                    "PUT", f"/UserFavoriteItems/{rows[0]['Id']}", raw=True
                )
                probe.observe(
                    "PUT /UserFavoriteItems/{itemId}",
                    f"Allow: {mark_headers.get('Allow', 'absent')}   <- POST+DELETE route, "
                    "the pair where alphabetical and registration order differ",
                )
            else:
                probe.note("Allow ordering on the mark pair unmeasured: the library is empty.")
        except ProbeError as exc:
            probe.note(f"Allow ordering on the mark pair unmeasured: {exc}")
    else:
        probe.note(
            "Allow ordering on the mark pair needs a token; run with credentials to measure it."
        )

    # -- the three headers that ride every response (behaviours 1.9, 1.10, 4.1) ----------------
    # One 200 and the two refusal shapes: the X-Response-Time-ms middleware is registered
    # unconditionally, so "every response" includes the responses that refuse.

    json_200 = request(server, "GET", PATH)
    _, unknown_headers, unknown_body = request(server, "GET", "/System/ThisRouteDoesNotExist")
    _, wrong_method_headers, wrong_method_body = request(server, "PUT", PING)

    unstamped = []
    for label, headers in (
        ("the 200", json_200[1]),
        ("the unknown-path 404", unknown_headers),
        ("the wrong-method 405", wrong_method_headers),
    ):
        value = headers.get("X-Response-Time-ms")
        probe.observe(f"X-Response-Time-ms on {label}", value or "absent")
        try:
            float(value or "")
        except ValueError:
            unstamped.append(label)

    content_type = json_200[1].get("Content-Type", "absent")
    server_header = json_200[1].get("Server", "absent")
    probe.observe("Content-Type on the JSON 200", content_type)
    probe.observe("Server header", server_header)

    # The finding is stated as the rules a reimplementation has to reproduce, because the
    # statuses alone do not say which of them is a rule and which is a coincidence.
    insensitive = {"all lowercase", "all uppercase", "mixed case"} <= set(matched)
    one_slash = "one trailing slash" in matched
    two_slashes = "two trailing slashes" in matched

    allow = wrong_method_headers.get("Allow", "")
    complete_allow = {part.strip() for part in allow.split(",") if part.strip()} == {"GET", "POST"}
    empty_refusals = not unknown_body and not wrong_method_body
    headers_hold = (
        not unstamped
        and content_type == "application/json; charset=utf-8"
        and server_header == "Kestrel"
    )

    if (
        insensitive
        and one_slash
        and not two_slashes
        and complete_allow
        and empty_refusals
        and headers_hold
    ):
        probe.conclude(
            "case-insensitive, one trailing slash tolerated and two not, and both refusals are "
            f"empty-bodied with no Content-Type - the wrong method carrying Allow: {allow}; "
            "X-Response-Time-ms rides the 200 and both refusals, the JSON charset and the "
            "Kestrel Server header as documented",
            matches_documentation=True,
        )
        return probe

    disagreements = []
    if not insensitive:
        disagreements.append(f"only these spellings matched: {', '.join(matched) or 'none'}")
    if not one_slash:
        disagreements.append("one trailing slash did not match")
    if two_slashes:
        disagreements.append("two trailing slashes matched")
    if not complete_allow:
        disagreements.append(f"Allow on a wrong method was {allow!r}, expected GET and POST")
    if not empty_refusals:
        disagreements.append(
            f"a refusal carried a body: unknown path {len(unknown_body)} bytes "
            f"({unknown_headers.get('Content-Type')}), wrong method {len(wrong_method_body)} bytes"
        )
    if unstamped:
        disagreements.append("X-Response-Time-ms missing or unparseable on " + ", ".join(unstamped))
    if content_type != "application/json; charset=utf-8":
        disagreements.append(
            f"the JSON 200's Content-Type is {content_type!r}, not the formatter charset of "
            "behaviours section 1.10"
        )
    if server_header != "Kestrel":
        disagreements.append(
            f"the Server header is {server_header!r}, not Kestrel (behaviours section 4.1)"
        )
    probe.conclude("; ".join(disagreements), matches_documentation=False)
    return probe


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0]))
