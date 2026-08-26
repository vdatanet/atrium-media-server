#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""How may a client present a token, which routes require one, and how is a refusal shaped?

Feature 002 rests on four claims that were measured before this repository existed and one that
was never measured at all. Each decides code that four tasks assert:

* **The four mechanisms** - `X-Emby-Token`, `Authorization: MediaBrowser Token="..."`, `?ApiKey=`
  and `?api_key=` - authenticate every authenticated route
  `[prior-probe: Jellyfin 10.11.11, 2026-06-13]`. The query forms exist because image loaders and
  media players are handed URLs and set no headers, so this is measured on an **image route and a
  delivery route** as well as an API one. Whether those two classes require a token at all is part
  of the question: a class that answers without one is not evidence that any mechanism works.
* **A disabled user is refused with `401`, indistinguishably from a wrong password** - specs/002
  section 3.3 assumes it and OQ-3 says so. A `403` is a different branch in every client: `401`
  means re-authenticate, anything else means show an error and stop.
* **A missing or unparseable `X-Emby-Authorization` is a `400`** - not a `401`, because a client
  reading it as one tells the user their password is wrong.
* **OQ-1** - whether that header is accepted outside authentication, and whether a request
  carrying it *and* a token behaves differently.

Which mechanism wins when a request carries two is measured rather than chosen. The plan calls the
order arbitrary; it does not have to be.

**This probe never tests lockout.** Failing N logins on purpose would lock a real account on the
operator's own server, and the counter it moves is not one this probe can reset. Every request
that carries credentials against a **real** account carries ones expected to be correct. Two
deliberate failures exist and neither can lock anyone out: a username no account can have, which
is the baseline every other refusal is compared against, and one wrong password for the disabled
account, which is the comparison OQ-3 exists to make and lands on an account already disabled.

The disabled-user question needs an account somebody has disabled. There is no way to make one
from here and no safe way to guess which account it is, so the probe takes its name and exits `2`
saying what to create when it is not given - every other finding still prints.

Read-only in the sense the other probes are: it writes nothing, but authenticating creates a
session on the reference, as every probe does.

Usage:
    python3 tools/probe_auth_mechanisms.py http://your-jellyfin:8096 -u username \\
        --disabled-user probe-disabled
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from _probe import Probe, ProbeError, Server, main

#: 32 hex characters that are not a token. It is how the precedence question gets asked: a request
#: carrying a real token and this one answers according to whichever it read.
BOGUS_TOKEN = "0" * 32  # the point of it is that it authenticates nobody

#: The two environment variables naming the disabled account. The name is not a secret; the
#: password is, and it stays in the git-ignored .env like every other one.
ENV_DISABLED_USERNAME = "JELLYFIN_DISABLED_USERNAME"
ENV_DISABLED_PASSWORD = "JELLYFIN_DISABLED_PASSWORD"  # noqa: S105 - a variable name

#: A device of our own, so the session this probe creates is recognisable in /Sessions and never
#: confused with a real client's.
PROBE_DEVICE = "atrium-probe-auth-0001"

CLIENT_HEADER = (
    'MediaBrowser Client="atrium-probe", Device="atrium-probe", '
    f'DeviceId="{PROBE_DEVICE}", Version="0.1"'
)

#: The same header with the one component that identifies a session removed.
CLIENT_HEADER_WITHOUT_DEVICE_ID = (
    'MediaBrowser Client="atrium-probe", Device="atrium-probe", Version="0.1"'
)

#: Answers for any authenticated user and needs no library content, which a reference may not
#: have. The image and delivery routes are discovered, and skipped with a note when there is
#: nothing to discover.
API_ROUTE = "/Users/Me"

AUTHENTICATE = "/Users/AuthenticateByName"

#: A username no account can have, so the refusal every other refusal is compared against costs
#: nothing to measure: there is no counter to move and no account to lock.
NO_SUCH_USER = "atrium-probe-no-such-user-0001"


# --------------------------------------------------------------------------------------------
# Requests, with exactly the headers given
# --------------------------------------------------------------------------------------------


def request(
    server: Server,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    data: bytes | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """One request, carrying nothing the caller did not ask for - no token is added behind our back.

    At most 4 KB of any response is read, which is what makes this safe to point at a delivery
    route: the socket closes after the first few bytes rather than downloading a film to learn a
    status code.
    """
    url = server.base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    sent = {"Accept": "application/json"}
    sent.update(headers or {})
    # S310: the URL is the operator's own server, given on the command line or in .env.
    req = urllib.request.Request(url, data=data, headers=sent, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=server.timeout) as response:  # noqa: S310
            return response.status, dict(response.headers), response.read(4096)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read(4096)
    except urllib.error.URLError as exc:
        raise ProbeError(f"{method} {path} -> {exc.reason}") from exc


def authenticate(server: Server, username: str, password: str, header: str | None) -> Any:
    """POST /Users/AuthenticateByName with exactly the client header given, or none at all."""
    headers = {"Content-Type": "application/json"}
    if header:
        headers["X-Emby-Authorization"] = header
    body = json.dumps({"Username": username, "Pw": password}).encode("utf-8")
    return request(server, "POST", AUTHENTICATE, headers=headers, data=body)


def mechanisms(token: str) -> list[tuple[str, dict[str, str], dict[str, str]]]:
    """The four ways specs/002 section 3.1 says a token may arrive."""
    return [
        ("X-Emby-Token header", {"X-Emby-Token": token}, {}),
        ("Authorization: MediaBrowser", {"Authorization": f'MediaBrowser Token="{token}"'}, {}),
        ("?ApiKey= query", {}, {"ApiKey": token}),
        ("?api_key= query", {}, {"api_key": token}),
    ]


def shape(status: int, headers: dict[str, str], body: bytes) -> str:
    """What distinguishes one refusal from another: status, size, type, and the first bytes.

    001 T13 measured two error shapes where the documentation described one, and the difference
    was visible in exactly these fields.

    **A body is previewed only when the request failed.** A successful authentication carries an
    access token, and a probe that prints one has published a live credential to a terminal, a
    scrollback buffer and whatever captured its output.
    """
    content_type = headers.get("Content-Type", "none")
    preview = ""
    if status >= 400 and body:
        preview = "  " + body[:60].decode("utf-8", "replace").replace("\n", " ")
    elif body:
        preview = "  (body withheld: a success carries a token)"
    return f"{status}  {len(body)}B  {content_type}{preview}"


# --------------------------------------------------------------------------------------------
# Route classes
# --------------------------------------------------------------------------------------------


def find_item(server: Server, **query: str) -> dict[str, Any] | None:
    """The first item matching, or None when the reference has no content to match."""
    try:
        page = server.get("/Items", userId=server.user_id, Recursive="true", Limit="24", **query)
    except ProbeError:
        return None
    items = (page or {}).get("Items") or []
    return items[0] if items else None


def find_image_item(server: Server) -> str | None:
    """An item carrying a primary image, or None."""
    try:
        page = server.get(
            "/Items",
            userId=server.user_id,
            Recursive="true",
            Limit="24",
            ImageTypeLimit="1",
            EnableImageTypes="Primary",
        )
    except ProbeError:
        return None
    for item in (page or {}).get("Items") or []:
        if (item.get("ImageTags") or {}).get("Primary"):
            image_id: str = item["Id"]
            return image_id
    return None


def measure_route_class(
    probe: Probe, server: Server, label: str, path: str, params: dict[str, str], token: str
) -> tuple[bool, bool]:
    """The five requests that say whether a route class is authenticated, and by what.

    Returns `(refuses_without_a_token, all_four_authenticated)`. The first is measured rather than
    assumed: a class that answers without a token proves nothing about any mechanism.
    """
    status_none, _, _ = request(server, "GET", path, params=dict(params))
    probe.observe(f"{label}: no token", str(status_none))

    worked = []
    for name, headers, query in mechanisms(token):
        merged = dict(params)
        merged.update(query)
        status, _, _ = request(server, "GET", path, headers=headers, params=merged)
        probe.observe(f"{label}: {name}", str(status))
        worked.append(status < 400)

    return status_none >= 400, all(worked)


# --------------------------------------------------------------------------------------------
# The probe
# --------------------------------------------------------------------------------------------


def run(server: Server, args: argparse.Namespace) -> Probe:
    probe = Probe(
        script="probe_auth_mechanisms.py",
        question="how may a client present a token, and how is a refusal shaped?",
        document="specs/002-authentication-users-and-sessions/spec.md",
        section="sections 3.1 and 3.3, and OQ-1 and OQ-3",
        expectation=(
            "all four mechanisms authenticate every authenticated route, on an image and a "
            "delivery route as well as an API one; a disabled user is refused with 401, "
            "indistinguishably from a wrong password; and a missing or unparseable "
            "X-Emby-Authorization is a 400 rather than a 401"
        ),
    )
    token = server.token or ""
    disagreements: list[str] = []

    # -- the four mechanisms, by route class ---------------------------------------------------

    api_refuses, api_all_four = measure_route_class(
        probe, server, f"API {API_ROUTE}", API_ROUTE, {}, token
    )
    if not api_refuses:
        disagreements.append(f"{API_ROUTE} answered without a token, so it authenticates nothing")
    if not api_all_four:
        disagreements.append("not all four mechanisms authenticated the API route")

    image_id = find_image_item(server)
    if image_id:
        refuses, all_four = measure_route_class(
            probe,
            server,
            "image /Items/{id}/Images/Primary",
            f"/Items/{image_id}/Images/Primary",
            {"maxWidth": "1"},
            token,
        )
        if not all_four:
            disagreements.append("not all four mechanisms authenticated the image route")
        if not refuses:
            probe.note(
                "the image route answered WITHOUT a token. That is a finding about the reference "
                "rather than about the mechanisms - AC-3 asserts that all four work on an image "
                "route, and on a route that authenticates nobody all four trivially do."
            )
    else:
        probe.note(
            "image route NOT measured: the reference has no item carrying a primary image. AC-3 "
            "covers three route classes and this run covers what it could reach."
        )

    video = find_item(server, IncludeItemTypes="Movie,Episode,Video", MediaTypes="Video")
    if video:
        refuses, all_four = measure_route_class(
            probe,
            server,
            "delivery /Videos/{id}/stream",
            f"/Videos/{video['Id']}/stream",
            {"static": "true"},
            token,
        )
        if not all_four:
            disagreements.append("not all four mechanisms authenticated the delivery route")
        if not refuses:
            probe.note(
                "the delivery route answered WITHOUT a token, which is the same finding as the "
                "image route above and matters more: it is what a leaked URL would reach."
            )
    else:
        probe.note("delivery route NOT measured: the reference has no video item.")

    # -- which mechanism wins when two disagree ------------------------------------------------

    pairs = [
        ("real header, bogus query", {"X-Emby-Token": token}, {"ApiKey": BOGUS_TOKEN}),
        ("bogus header, real query", {"X-Emby-Token": BOGUS_TOKEN}, {"ApiKey": token}),
        (
            "real X-Emby-Token, bogus Authorization",
            {"X-Emby-Token": token, "Authorization": f'MediaBrowser Token="{BOGUS_TOKEN}"'},
            {},
        ),
        (
            "bogus X-Emby-Token, real Authorization",
            {"X-Emby-Token": BOGUS_TOKEN, "Authorization": f'MediaBrowser Token="{token}"'},
            {},
        ),
    ]
    precedence = []
    for label, headers, query in pairs:
        status, _, _ = request(server, "GET", API_ROUTE, headers=headers, params=query)
        probe.observe(f"two at once: {label}", str(status))
        precedence.append(f"{label}: {status}")
    probe.note("precedence when a request carries two tokens - " + ", ".join(precedence))

    # -- how a refusal is shaped ---------------------------------------------------------------

    probe.observe("refusal: no token", shape(*request(server, "GET", API_ROUTE)))
    probe.observe(
        "refusal: unknown token",
        shape(*request(server, "GET", API_ROUTE, headers={"X-Emby-Token": BOGUS_TOKEN})),
    )

    # -- OQ-1: X-Emby-Authorization outside authentication -------------------------------------

    with_both, _, _ = request(
        server,
        "GET",
        API_ROUTE,
        headers={"X-Emby-Token": token, "X-Emby-Authorization": CLIENT_HEADER},
    )
    probe.observe("OQ-1: token and X-Emby-Authorization", str(with_both))

    alone = request(server, "GET", API_ROUTE, headers={"X-Emby-Authorization": CLIENT_HEADER})
    probe.observe("OQ-1: X-Emby-Authorization alone", shape(*alone))
    probe.note(
        f"OQ-1: the header alongside a token answers {with_both}, and alone it answers {alone[0]}. "
        "It identifies a client; it does not authenticate one."
        if with_both < 400 and alone[0] >= 400
        else f"OQ-1: alongside a token {with_both}, alone {alone[0]} - read the rows above"
    )

    # -- the two 400 paths on AuthenticateByName -----------------------------------------------

    missing_header: int | None = None
    missing_device: int | None = None
    if server.username_used and server.password_used is not None:
        username, password = server.username_used, server.password_used
        no_header = authenticate(server, username, password, header=None)
        missing_header = no_header[0]
        probe.observe(f"{AUTHENTICATE}: no X-Emby-Authorization", shape(*no_header))

        no_device = authenticate(server, username, password, header=CLIENT_HEADER_WITHOUT_DEVICE_ID)
        missing_device = no_device[0]
        probe.observe(f"{AUTHENTICATE}: header without DeviceId", shape(*no_device))

        if missing_header != 400:
            disagreements.append(
                f"a missing X-Emby-Authorization answered {missing_header}, not 400"
            )
        if missing_device != 400:
            disagreements.append(f"a header without DeviceId answered {missing_device}, not 400")
    else:
        probe.note(
            "the two 400 paths on AuthenticateByName were NOT measured: sending them needs a "
            "password, and this run authenticated with a token. Re-run with --username to measure "
            "them - correct credentials are used, so nothing counts as a failed attempt."
        )

    # -- OQ-3: the disabled user ---------------------------------------------------------------

    unknown = authenticate(server, NO_SUCH_USER, "not-a-password", header=CLIENT_HEADER)
    probe.observe("baseline: unknown username", shape(*unknown))

    disabled_user = args.disabled_user or os.environ.get(ENV_DISABLED_USERNAME)
    disabled_password = args.disabled_password or os.environ.get(ENV_DISABLED_PASSWORD) or ""
    disabled_status: int | None = None
    if disabled_user:
        right = authenticate(server, disabled_user, disabled_password, header=CLIENT_HEADER)
        disabled_status = right[0]
        probe.observe("OQ-3: disabled user, right password", shape(*right))

        wrong = authenticate(
            server, disabled_user, disabled_password + "-not-it", header=CLIENT_HEADER
        )
        probe.observe("OQ-3: same user, wrong password", shape(*wrong))

        if disabled_status != 401:
            disagreements.append(f"a disabled user answered {disabled_status}, not 401 (OQ-3)")
        if (right[0], right[2]) != (unknown[0], unknown[2]):
            disagreements.append(
                f"a disabled user ({right[0]}) and an unknown username ({unknown[0]}) are "
                "distinguishable, so a client can tell a disabled account from a rejected one"
            )
        if (right[0], right[2]) != (wrong[0], wrong[2]):
            disagreements.append(
                "for the disabled account, the right password and a wrong one answer differently "
                "- the refusal discloses whether the password was correct"
            )
        if disabled_status is not None and disabled_status < 400:
            disagreements.append(
                f"the account named by --disabled-user authenticated ({disabled_status}). It is "
                "not disabled, so OQ-3 was not measured - disable it and run again"
            )
    else:
        probe.note(
            f"OQ-3 NOT answered: no disabled account was named. Disable an account nobody uses on "
            f"the reference and pass --disabled-user, or set {ENV_DISABLED_USERNAME} and "
            f"{ENV_DISABLED_PASSWORD} in .env. Guessing here means failed logins against somebody "
            f"else's account, and this probe does not guess."
        )

    # -- the finding ---------------------------------------------------------------------------

    if disagreements:
        probe.conclude("; ".join(disagreements), matches_documentation=False)
    elif disabled_status is None:
        probe.conclude(
            "every mechanism measured authenticated every route class measured, and the refusal "
            "shapes are above - but OQ-3 was not answered, so the claim that decides AC-2 is "
            "still an assumption",
            matches_documentation=False,
        )
    else:
        probe.conclude(
            "every mechanism measured authenticated every route class measured, and a disabled "
            "user is refused with 401 indistinguishably from a wrong password",
            matches_documentation=True,
        )
    return probe


def arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--disabled-user",
        help="Name of an account that is DISABLED on the reference. OQ-3 needs one, and it must "
        f"be an account nobody uses. Defaults to ${ENV_DISABLED_USERNAME}",
    )
    parser.add_argument(
        "--disabled-password",
        help=f"Its password. Prefer ${ENV_DISABLED_PASSWORD} in .env - a command line is visible "
        "in the process list",
    )


if __name__ == "__main__":
    raise SystemExit(main(run, __doc__.splitlines()[0], extra_arguments=arguments, with_args=True))
